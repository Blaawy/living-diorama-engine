"""Phase 33 earns the STRONG determinism contract: it copies rather than generates.

Same bound input bytes -> byte-identical output, every file, every time, on
any machine. These tests prove it across two runs in this interpreter, and via
a causal, metamorphic proof that deliberately varying every non-authoritative
runtime input a fresh subprocess interpreter can report -- the hash seed, the
process id, the hostname, the wall clock, and the absolute temp root the
assembly is built under -- cannot move a single published byte.
"""

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from living_diorama.media_assembly.media_assembly_spec import (
    ASSEMBLY_DIRECTORY_ENTRIES,
    DELIVERY_PLAN_COPY_FILENAME,
    MEDIA_ASSEMBLY_MANIFEST_FILENAME,
    PROVENANCE_DIRECTORY,
    SHOT_PLAN_COPY_FILENAME,
)
from living_diorama.media_assembly.media_assembly_staging import _regular_file_link_count
from living_diorama.persistence.json_codec import loads_canonical

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFTEST_DIR = Path(__file__).parent


def _tree_hash(root: Path) -> str:
    """A deterministic digest over every file's relative path and bytes, sorted."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(root)).replace("\\", "/").encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def test_two_runs_into_different_roots_are_byte_identical(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any]
) -> None:
    """Two runs into different roots are byte identical."""
    from living_diorama.media_assembly.media_assembly_publisher import (
        publish_episode_media_assembly,
    )

    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    published_a = publish_episode_media_assembly(output_root=root_a, **assembly_inputs_ep0)
    published_b = publish_episode_media_assembly(output_root=root_b, **assembly_inputs_ep0)

    entries_a = {p.name for p in published_a.iterdir()}
    entries_b = {p.name for p in published_b.iterdir()}
    assert entries_a == entries_b == ASSEMBLY_DIRECTORY_ENTRIES
    assert _tree_hash(published_a) == _tree_hash(published_b)


def test_canonical_json_round_trip_equality(assembly_dir_ep1: Path) -> None:
    """Canonical json round trip equality."""
    for filename in (
        "episode_render_manifest.json",
        "episode_presentation_plan.json",
        "episode_audio_composition_manifest.json",
        MEDIA_ASSEMBLY_MANIFEST_FILENAME,
    ):
        raw = (assembly_dir_ep1 / filename).read_bytes()
        document = loads_canonical(raw, filename)
        from living_diorama.persistence.json_codec import dumps_canonical

        assert dumps_canonical(document, filename) == raw


def test_every_output_frame_digest_equals_its_source_frame_digest(
    assembly_dir_ep1: Path,
) -> None:
    """Every output frame digest equals its source frame digest."""
    from living_diorama.persistence.schema.state_hash import sha256_hex

    manifest = loads_canonical(
        (assembly_dir_ep1 / MEDIA_ASSEMBLY_MANIFEST_FILENAME).read_bytes(), "manifest"
    )
    for frame in manifest["frames"]:
        published = (assembly_dir_ep1 / frame["file"]).read_bytes()
        assert sha256_hex(published) == frame["sha256"]
        assert len(published) == frame["bytes"]


def test_both_witnesses_are_byte_identical_to_their_sources(
    assembly_dir_ep1: Path, assembly_inputs_ep1: dict[str, Any]
) -> None:
    """Both witnesses are byte identical to their sources."""
    delivery_published = (
        assembly_dir_ep1 / PROVENANCE_DIRECTORY / DELIVERY_PLAN_COPY_FILENAME
    ).read_bytes()
    shot_published = (
        assembly_dir_ep1 / PROVENANCE_DIRECTORY / SHOT_PLAN_COPY_FILENAME
    ).read_bytes()
    assert delivery_published == assembly_inputs_ep1["delivery_plan_bytes"]
    assert shot_published == assembly_inputs_ep1["shot_plan_bytes"]


def test_every_owned_regular_file_has_link_count_one_in_both_runs(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any]
) -> None:
    """Every owned regular file has link count one in both runs."""
    from living_diorama.media_assembly.media_assembly_publisher import (
        publish_episode_media_assembly,
    )

    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    for root in (root_a, root_b):
        published = publish_episode_media_assembly(output_root=root, **assembly_inputs_ep0)
        for path in published.rglob("*"):
            if path.is_file():
                assert _regular_file_link_count(path) == 1


def test_no_absolute_filesystem_path_syntax_in_json_documents(assembly_dir_ep1: Path) -> None:
    r"""No absolute filesystem path syntax appears in any published JSON document.

    A safe STRUCTURAL check, not a token scan: it looks for Windows drive-letter
    syntax (``C:\\`` / ``C:/``) or POSIX ``/home/`` / ``/Users/`` path syntax --
    never for a short decimal or string token that could coincide with legitimate
    deterministic content such as a SHA-256 digest, a byte count or a presentation
    coordinate. Binary payloads (PNG frames, the WAV) are exempt, since only the
    JSON documents are ever textual.
    """
    import re

    absolute_path_pattern = re.compile(rb"[A-Za-z]:[\\/][A-Za-z]|/(?:home|Users)/")
    for path in sorted(assembly_dir_ep1.rglob("*.json")):
        payload = path.read_bytes()
        match = absolute_path_pattern.search(payload)
        assert not match, f"{path} appears to contain an absolute filesystem path: {match}"


# ---------------------------------------------------------------------------
# The metamorphic runtime-context invariance proof
#
# The prior oracle scanned published bytes for the current process's raw PID and
# hostname as decimal/text substrings. That is unsound: the manifest is ~128 KB
# of SHA-256 digests, byte counts and coordinates, and a short decimal PID
# coincides with one of those substrings on a measurable fraction of real
# process ids (empirically, roughly 8% of 4-digit PIDs collide with a genuine
# ep1 manifest) -- a false positive with no bearing on determinism.
#
# The sound proof is causal, not textual: deliberately vary every non-authoritative
# runtime input this contract claims cannot influence output -- PYTHONHASHSEED, the
# visible process id, the visible hostname, the visible wall clock, and the
# absolute temp-root the assembly is built under -- while holding the
# authoritative fixture content fixed, and require the ENTIRE published tree to
# still reduce to one identical digest. Patching happens before any Phase 33 or
# render_execution import, in a fresh subprocess interpreter each time, so no
# cached true value can leak into the run under test.
# ---------------------------------------------------------------------------

_METAMORPHIC_SCRIPT = f"""
import os
import socket
import platform
import time

# ---- patch every non-authoritative runtime provider BEFORE any Phase 33 import ----
_pid = int(os.environ["PHASE33_TEST_PID"])
_host = os.environ["PHASE33_TEST_HOST"]
_t = float(os.environ["PHASE33_TEST_TIME"])
_t_ns = int(os.environ["PHASE33_TEST_TIME_NS"])
os.getpid = lambda: _pid
socket.gethostname = lambda: _host
platform.node = lambda: _host
time.time = lambda: _t
time.time_ns = lambda: _t_ns

import sys
sys.path.insert(0, {str(CONFTEST_DIR)!r})
sys.path.insert(0, {str(REPO_ROOT / "src")!r})

import hashlib
import shutil
import tempfile
from pathlib import Path

import conftest as fixtures
from living_diorama.media_assembly.media_assembly_publisher import publish_episode_media_assembly
from living_diorama.render_execution import build_episode_render_plan_document

sources = fixtures.build_sources(0)
realization, presentation, delivery, narration, shots, story, export = sources
plan = build_episode_render_plan_document(shots, story)

# a deliberately distinct absolute temp root per runtime context
root_tag = os.environ["PHASE33_TEST_ROOT_TAG"]
tmp_root = tempfile.mkdtemp(prefix=f"phase33_ctx_{{root_tag}}_")
try:
    tmp_path = Path(tmp_root)
    render_dir, render_manifest = fixtures.write_render_directory(tmp_path / "render_root", plan)
    composition_dir = fixtures.build_composition(
        tmp_path / "composition_root", sources, patterned=False, label="metamorphic"
    )
    inputs = fixtures.build_assembly_inputs(sources, (render_dir, render_manifest), composition_dir)
    output_root = tmp_path / "out"
    output_root.mkdir()
    published = publish_episode_media_assembly(output_root=output_root, **inputs)

    digest = hashlib.sha256()
    for path in sorted(published.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(published)).replace("\\\\", "/").encode("utf-8"))
            digest.update(path.read_bytes())
    print(digest.hexdigest())
finally:
    shutil.rmtree(tmp_root, ignore_errors=True)
"""

_METAMORPHIC_CONTEXTS = [
    {
        "seed": "0",
        "pid": "410001",
        "host": "ci-runner-alpha.example",
        "t": "1000000000.0",
        "t_ns": "1000000000000000000",
        "tag": "ctxA",
    },
    {
        "seed": "1",
        "pid": "520002",
        "host": "build-node-beta.internal",
        "t": "1500000000.5",
        "t_ns": "1500000000500000000",
        "tag": "ctxB",
    },
    {
        "seed": "42",
        "pid": "630003",
        "host": "runner-gamma-42",
        "t": "1700000000.25",
        "t_ns": "1700000000250000000",
        "tag": "ctxC",
    },
    {
        "seed": "123456",
        "pid": "740004",
        "host": "worker-delta-999",
        "t": "1999999999.75",
        "t_ns": "1999999999750000000",
        "tag": "ctxD",
    },
]


def test_metamorphic_runtime_context_invariance_across_hash_seeds() -> None:
    """The published tree is one identical digest across four distinct runtime contexts.

    Directly proves the frozen "digest set of cardinality 1" requirement: fresh
    interpreters under ``PYTHONHASHSEED`` in {0, 1, 42, 123456}, each additionally
    given its own deliberately distinct process id, hostname, wall-clock reading
    and absolute temp-root -- four independent axes of variance the contract
    claims cannot influence a single published byte. If any of them did leak in,
    the four digests would diverge; they do not.
    """
    digests: list[str] = []
    for context in _METAMORPHIC_CONTEXTS:
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = context["seed"]
        env["PHASE33_TEST_PID"] = context["pid"]
        env["PHASE33_TEST_HOST"] = context["host"]
        env["PHASE33_TEST_TIME"] = context["t"]
        env["PHASE33_TEST_TIME_NS"] = context["t_ns"]
        env["PHASE33_TEST_ROOT_TAG"] = context["tag"]
        result = subprocess.run(
            [sys.executable, "-c", _METAMORPHIC_SCRIPT],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        digest = result.stdout.strip()
        assert digest, f"context {context['tag']} produced no digest: {result.stderr}"
        digests.append(digest)

    assert len(digests) == len(_METAMORPHIC_CONTEXTS)
    tags = (c["tag"] for c in _METAMORPHIC_CONTEXTS)
    assert len(set(digests)) == 1, (
        "the published tree diverged across runtime contexts that should never "
        f"influence it: {list(zip(tags, digests, strict=True))}"
    )
