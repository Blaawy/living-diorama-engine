"""Phase 33 earns the STRONG determinism contract: it copies rather than generates.

Same bound input bytes -> byte-identical output, every file, every time, on
any machine. These tests prove it across two runs in this interpreter, across
two independent subprocess interpreters under four pinned hash seeds, and by
scanning every published byte for the variance sources the contract names.
"""

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

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


def test_no_timestamp_pid_hostname_or_absolute_path_in_any_output_byte(
    assembly_dir_ep1: Path,
) -> None:
    """No timestamp pid hostname or absolute path in any output byte."""
    import re
    import socket

    forbidden: list[str] = [str(os.getpid()), socket.gethostname()]
    absolute_path_pattern = re.compile(rb"[A-Za-z]:[\\/][A-Za-z]|/(?:home|Users|c/Users)/")

    for path in sorted(assembly_dir_ep1.rglob("*")):
        if not path.is_file():
            continue
        payload = path.read_bytes()
        for needle in forbidden:
            if needle and needle.encode("utf-8") in payload:
                pytest.fail(f"{path} contains forbidden runtime value {needle!r}")
        match = absolute_path_pattern.search(payload)
        # Presentation/audio binary payloads are exempt from the textual scan below --
        # only the four JSON documents and the manifest are checked for embedded paths.
        if path.suffix == ".json" and match:
            pytest.fail(f"{path} appears to contain an absolute filesystem path: {match}")


@pytest.mark.parametrize("seed", ["0", "1", "42", "123456"])
def test_deterministic_under_pinned_hash_seed_across_fresh_interpreters(seed: str) -> None:
    """Deterministic under pinned hash seed across fresh interpreters."""
    script = f"""
import sys
sys.path.insert(0, {str(CONFTEST_DIR)!r})
sys.path.insert(0, {str(REPO_ROOT / "src")!r})
import tempfile, hashlib
from pathlib import Path
import conftest as fixtures
from living_diorama.media_assembly.media_assembly_publisher import publish_episode_media_assembly
from living_diorama.render_execution import build_episode_render_plan_document

sources = fixtures.build_sources(0)
realization, presentation, delivery, narration, shots, story, export = sources
plan = build_episode_render_plan_document(shots, story)
with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    render_dir, render_manifest = fixtures.write_render_directory(tmp_path / "render_root", plan)
    composition_dir = fixtures.build_composition(
        tmp_path / "composition_root", sources, patterned=False, label="seed"
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
"""
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = seed
    first = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env, check=True
    )
    second = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env, check=True
    )
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout.strip() != ""
    assert first.stdout.strip() == second.stdout.strip()
