"""Phase 34 earns the STRONG determinism contract: same plan bytes, byte-identical publication.

The same accepted caption plan bytes produce byte-identical manifest, SRT and
VTT on any machine, and the self-contained audit re-serializes both sidecars
from the copied plan and requires exact byte equality. These tests prove it
across two runs in this interpreter, across a rerun into the same root (a
verified no-op), and via a causal, metamorphic proof that deliberately varying
the hash seed a fresh subprocess interpreter can report -- while holding the
fixture export fixed -- cannot move a single published byte. A final guard
proves importing the package leaks no target-format or tool module.
"""

import hashlib
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

from living_diorama.caption_serialization import (
    CAPTION_PLAN_COPY_FILENAME,
    CAPTION_SERIALIZATION_MANIFEST_FILENAME,
)
from living_diorama.persistence.json_codec import loads_canonical

from .conftest import FIXTURES, serialize_into

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFTEST_DIR = Path(__file__).parent
HASH_SEEDS = ("0", "1", "42", "123456")


def _tree_hash(root: Path) -> str:
    """A deterministic digest over every file's relative path and bytes, sorted."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(root)).replace("\\", "/").encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def test_two_runs_into_different_roots_are_byte_identical(
    tmp_path: Path, sources_ep1: tuple[dict[str, Any], ...]
) -> None:
    """Two runs into different roots are byte identical."""
    published_a = serialize_into(tmp_path / "a", sources_ep1)
    published_b = serialize_into(tmp_path / "b", sources_ep1)
    entries_a = {p.name for p in published_a.iterdir()}
    entries_b = {p.name for p in published_b.iterdir()}
    assert entries_a == entries_b
    assert _tree_hash(published_a) == _tree_hash(published_b)


def test_rerun_same_root_is_verified_noop(
    tmp_path: Path, sources_ep1: tuple[dict[str, Any], ...]
) -> None:
    """Rerunning into the same root is a verified no-op: the tree is unchanged."""
    output_root = tmp_path / "out"
    published = serialize_into(output_root, sources_ep1)
    before = _tree_hash(published)
    again = serialize_into(output_root, sources_ep1)
    assert again == published
    assert _tree_hash(again) == before


def test_canonical_json_round_trip_equality(captions_dir_ep1: Path) -> None:
    """Canonical json round trip equality for every published JSON document."""
    from living_diorama.persistence.json_codec import dumps_canonical

    for path in sorted(captions_dir_ep1.rglob("*.json")):
        raw = path.read_bytes()
        document = loads_canonical(raw, path.name)
        assert dumps_canonical(document, path.name) == raw


def test_published_sidecars_and_plan_copy_match_the_manifest(
    captions_dir_ep1: Path, caption_plan_ep1: tuple[dict[str, Any], bytes]
) -> None:
    """The published SRT/VTT bytes match their manifest records, and the plan copy is exact."""
    from living_diorama.persistence.schema.state_hash import sha256_hex

    _document, caption_plan_bytes = caption_plan_ep1
    manifest = loads_canonical(
        (captions_dir_ep1 / CAPTION_SERIALIZATION_MANIFEST_FILENAME).read_bytes(),
        "episode caption serialization manifest",
    )
    assert (captions_dir_ep1 / CAPTION_PLAN_COPY_FILENAME).read_bytes() == caption_plan_bytes
    for record_key in ("srt", "vtt"):
        record = manifest["sidecars"][record_key]
        published = (captions_dir_ep1 / record["file"]).read_bytes()
        assert sha256_hex(published) == record["sha256"]
        assert len(published) == record["bytes"]


def test_no_absolute_filesystem_path_syntax_in_json_documents(captions_dir_ep1: Path) -> None:
    r"""No absolute filesystem path syntax appears in any published JSON document.

    A safe STRUCTURAL check, not a token scan: it looks for Windows drive-letter
    syntax (``C:\\`` / ``C:/``) or POSIX ``/home/`` / ``/Users/`` path syntax --
    never for a short decimal or string token that could coincide with legitimate
    deterministic content such as a SHA-256 digest or a byte count. Binary
    payloads (the SRT/VTT sidecars) are exempt, since only the JSON documents
    are ever textual.
    """
    absolute_path_pattern = re.compile(rb"[A-Za-z]:[\\/][A-Za-z]|/(?:home|Users)/")
    for path in sorted(captions_dir_ep1.rglob("*.json")):
        payload = path.read_bytes()
        match = absolute_path_pattern.search(payload)
        assert not match, f"{path} appears to contain an absolute filesystem path: {match}"


# ---------------------------------------------------------------------------
# The metamorphic runtime-context invariance proof
#
# The sound proof is causal: deliberately vary every non-authoritative runtime
# input this contract claims cannot influence output -- PYTHONHASHSEED -- while
# holding the authoritative fixture content fixed, and require the ENTIRE
# published tree to still reduce to one identical digest. Each run happens in a
# fresh subprocess interpreter, so no cached true value can leak into the run
# under test. The child builds the whole locked chain from the fixture export
# path passed via argv, publishes through the real publisher, and prints the
# tree hash.
# ---------------------------------------------------------------------------

_METAMORPHIC_SCRIPT = textwrap.dedent(
    f"""
    import sys
    from pathlib import Path

    sys.path.insert(0, {str(CONFTEST_DIR)!r})
    sys.path.insert(0, {str(REPO_ROOT / "src")!r})

    import conftest as fixtures
    from living_diorama.caption import build_episode_caption_plan_document
    from living_diorama.caption_serialization import publish_episode_caption_serialization
    from living_diorama.persistence.json_codec import dumps_canonical

    export_path = Path(sys.argv[1])
    fixtures.FIXTURES = export_path.parent
    sources = fixtures.build_sources(1)
    realization, presentation, delivery, narration, shots, story, export = sources
    caption_plan = build_episode_caption_plan_document(realization, presentation)
    caption_plan_bytes = dumps_canonical(caption_plan, "caption plan")

    import hashlib
    import shutil
    import tempfile

    tmp_root = tempfile.mkdtemp(prefix="phase34_ctx_")
    try:
        output_root = Path(tmp_root) / "out"
        output_root.mkdir(parents=True, exist_ok=True)
        published = publish_episode_caption_serialization(
            caption_plan=caption_plan,
            caption_plan_bytes=caption_plan_bytes,
            realization_plan=realization,
            presentation_plan=presentation,
            delivery_plan=delivery,
            narration_plan=narration,
            shot_plan=shots,
            story_plan=story,
            current_export=export,
            output_root=output_root,
        )

        digest = hashlib.sha256()
        for path in sorted(published.rglob("*")):
            if path.is_file():
                digest.update(
                    str(path.relative_to(published)).replace("\\\\", "/").encode("utf-8")
                )
                digest.update(path.read_bytes())
        print(digest.hexdigest())
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
    """
)


def test_metamorphic_runtime_context_invariance_across_hash_seeds() -> None:
    """The published tree is one identical digest across four hash seeds, twice each.

    Directly proves the frozen "digest set of cardinality 1" requirement: fresh
    interpreters under ``PYTHONHASHSEED`` in {0, 1, 42, 123456}, each run twice,
    must reduce the entire published tree to one identical digest. If the seed
    leaked into any published byte, the eight digests would diverge; they do not.
    """
    export_path = FIXTURES / "render_export_ep1.json"
    digests: list[str] = []
    for seed in HASH_SEEDS:
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = str(REPO_ROOT / "src")
        for _ in range(2):
            result = subprocess.run(
                [sys.executable, "-c", _METAMORPHIC_SCRIPT, str(export_path)],
                capture_output=True,
                text=True,
                env=env,
                check=True,
            )
            digest = result.stdout.strip()
            assert digest, f"seed {seed} produced no digest: {result.stderr}"
            digests.append(digest)

    assert len(digests) == len(HASH_SEEDS) * 2
    assert len(set(digests)) == 1, (
        "the published tree diverged across hash seeds that should never influence it: "
        f"{sorted(set(digests))}"
    )


def test_no_forbidden_top_level_import_leak() -> None:
    """Importing the P34 package leaks no srt/webvtt/ffmpeg/subprocess top-level module.

    The serialization carries its own frozen SRT and WebVTT writers and never
    spawns a tool: after ``import living_diorama.caption_serialization`` in a
    fresh interpreter, none of the target-format or tool module roots may appear
    among the top-level names of ``sys.modules``.
    """
    script = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(REPO_ROOT / "src")!r})
        import living_diorama.caption_serialization  # noqa: F401
        forbidden = {{"srt", "webvtt", "ffmpeg", "subprocess"}}
        hit = forbidden & set(m.split(".")[0] for m in sys.modules)
        print(sorted(hit))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert completed.stdout.strip() == "[]", completed.stdout
