"""Orchestration: geometry, source binding, copy and publish -- Correction K family C.

Cheap scenario tests call the real publisher directly against the already-built
``assembly_inputs_ep0`` bundle (192 frames), so each fresh-publish scenario
costs only the publish itself, not the whole upstream pipeline. The
already-published, session-shared ``assembly_dir_ep1`` (720 frames) is used
for read-only structural assertions that need no fresh publish.
"""

import os
from pathlib import Path
from typing import Any

import pytest

from living_diorama.media_assembly import media_assembly_publisher as publisher_module
from living_diorama.media_assembly import media_assembly_staging as staging_module
from living_diorama.media_assembly.media_assembly_audit import audit_media_assembly_directory
from living_diorama.media_assembly.media_assembly_mapping import MediaAssemblyRefused
from living_diorama.media_assembly.media_assembly_publisher import publish_episode_media_assembly
from living_diorama.media_assembly.media_assembly_spec import (
    ASSEMBLY_DIRECTORY_ENTRIES,
    AUDIO_DIRECTORY,
    DELIVERY_PLAN_COPY_FILENAME,
    EPISODE_AUDIO_FILENAME,
    MEDIA_ASSEMBLY_MANIFEST_FILENAME,
    PARTIAL_SUFFIX,
    PRESENTATION_DIRECTORY,
    PROVENANCE_DIRECTORY,
    RENDER_MANIFEST_COPY_FILENAME,
    SHOT_PLAN_COPY_FILENAME,
    media_assembly_id,
    presentation_frame_filename,
)
from living_diorama.media_assembly.media_assembly_staging import (
    MediaAssemblyDirectoryRefused,
    _regular_file_link_count,
)
from living_diorama.persistence.json_codec import loads_canonical


def _can_hardlink(probe_dir: Path) -> bool:
    probe_dir.mkdir(parents=True, exist_ok=True)
    source = probe_dir / "_probe_source"
    source.write_bytes(b"x")
    try:
        os.link(source, probe_dir / "_probe_link")
    except OSError:
        return False
    return True


def _publish(inputs: dict[str, Any], output_root: Path) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    return publish_episode_media_assembly(output_root=output_root, **inputs)


# ---------------------------------------------------------------------------
# Happy path -- structural assertions on the shared, already-published ep1
# ---------------------------------------------------------------------------


def test_happy_path_publishes_exactly_seven_entries(assembly_dir_ep1: Path) -> None:
    """Happy path publishes exactly seven entries."""
    entries = {entry.name for entry in assembly_dir_ep1.iterdir()}
    assert entries == ASSEMBLY_DIRECTORY_ENTRIES


def test_frame_count_equals_presentation_frames_total(assembly_dir_ep1: Path) -> None:
    """Frame count equals presentation frames total."""
    manifest = loads_canonical(
        (assembly_dir_ep1 / MEDIA_ASSEMBLY_MANIFEST_FILENAME).read_bytes(), "manifest"
    )
    frame_files = list((assembly_dir_ep1 / PRESENTATION_DIRECTORY).iterdir())
    assert len(frame_files) == manifest["clock"]["presentation_frames_total"]
    assert manifest["completeness"]["presentation_frames_assembled"] == len(frame_files)


def test_every_output_frame_digest_equals_its_source_frame_digest(
    assembly_dir_ep1: Path, assembly_inputs_ep1: dict[str, Any]
) -> None:
    """Every output frame digest equals its source frame digest."""
    from living_diorama.media_assembly.media_assembly_mapping import (
        presentation_frame_map,
        require_playback_lookup,
    )
    from living_diorama.persistence.schema.state_hash import sha256_hex
    from living_diorama.render_execution.render_execution_spec import FRAMES_DIRECTORY

    mapping = presentation_frame_map(assembly_inputs_ep1["presentation_plan"])
    lookup = require_playback_lookup(assembly_inputs_ep1["render_manifest"])
    for position in (1, len(mapping) // 2, len(mapping)):
        semantic = mapping[position - 1]
        source_bytes = (
            assembly_inputs_ep1["render_dir"] / FRAMES_DIRECTORY / lookup[semantic]["file"]
        ).read_bytes()
        published_bytes = (
            assembly_dir_ep1 / PRESENTATION_DIRECTORY / presentation_frame_filename(position)
        ).read_bytes()
        assert sha256_hex(published_bytes) == sha256_hex(source_bytes)


def test_wav_and_both_witnesses_are_byte_identical_to_their_sources(
    assembly_dir_ep1: Path, assembly_inputs_ep1: dict[str, Any]
) -> None:
    """WAV and both witnesses are byte identical to their sources."""
    assert (
        assembly_dir_ep1 / AUDIO_DIRECTORY / EPISODE_AUDIO_FILENAME
    ).read_bytes() == assembly_inputs_ep1["wav_bytes"]
    assert (
        assembly_dir_ep1 / PROVENANCE_DIRECTORY / DELIVERY_PLAN_COPY_FILENAME
    ).read_bytes() == assembly_inputs_ep1["delivery_plan_bytes"]
    assert (
        assembly_dir_ep1 / PROVENANCE_DIRECTORY / SHOT_PLAN_COPY_FILENAME
    ).read_bytes() == assembly_inputs_ep1["shot_plan_bytes"]


def test_every_published_regular_file_has_link_count_one(assembly_dir_ep1: Path) -> None:
    """Every published regular file has link count one."""
    for path in assembly_dir_ep1.rglob("*"):
        if path.is_file():
            assert _regular_file_link_count(path) == 1


# ---------------------------------------------------------------------------
# Primitive call counts -- a fresh, instrumented publish against ep0 (192 frames)
# ---------------------------------------------------------------------------


def test_write_frame_exclusively_called_once_per_staged_frame(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Write frame exclusively called once per staged frame."""
    calls: list[Path] = []
    real = publisher_module.write_frame_exclusively

    def _tracking(path: Path, payload: bytes) -> None:
        calls.append(path)
        real(path, payload)

    monkeypatch.setattr(publisher_module, "write_frame_exclusively", _tracking)
    published = _publish(assembly_inputs_ep0, tmp_path / "out")
    manifest = loads_canonical(
        (published / MEDIA_ASSEMBLY_MANIFEST_FILENAME).read_bytes(), "manifest"
    )
    assert len(calls) == manifest["clock"]["presentation_frames_total"]


def test_write_atomically_called_once_per_document_plus_once_for_the_wav(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Write atomically called once per document plus once for the WAV."""
    calls: list[Path] = []
    real = publisher_module.write_atomically

    def _tracking(path: Path, payload: bytes) -> None:
        calls.append(path)
        real(path, payload)

    monkeypatch.setattr(publisher_module, "write_atomically", _tracking)
    _publish(assembly_inputs_ep0, tmp_path / "out")
    # 3 top-level docs (render, presentation, composition) + 2 provenance witnesses
    # + 1 WAV + 1 final assembly manifest == 7.
    assert len(calls) == 7


def test_fsync_directory_called_five_times_the_fifth_after_the_rename(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fsync directory called five times the fifth after the rename."""
    order: list[str] = []
    real_fsync_directory = publisher_module.fsync_directory
    real_replace = os.replace

    def _tracking_fsync_directory(path: Path) -> None:
        order.append("fsync_directory")
        real_fsync_directory(path)

    def _tracking_replace(src: Any, dst: Any) -> None:
        order.append("replace")
        real_replace(src, dst)

    # publish_owned_staging's own post-rename call goes through staging_module's own
    # binding, not the publisher's imported alias -- both must be patched to observe
    # all five calls.
    monkeypatch.setattr(publisher_module, "fsync_directory", _tracking_fsync_directory)
    monkeypatch.setattr(staging_module, "fsync_directory", _tracking_fsync_directory)
    monkeypatch.setattr(os, "replace", _tracking_replace)
    _publish(assembly_inputs_ep0, tmp_path / "out")
    assert order.count("fsync_directory") == 5
    # The final fsync_directory call (of the parent, post-rename) must follow the rename.
    last_replace_index = max(i for i, v in enumerate(order) if v == "replace")
    last_fsync_index = max(i for i, v in enumerate(order) if v == "fsync_directory")
    assert last_fsync_index > last_replace_index


# ---------------------------------------------------------------------------
# Refusal / cleanup semantics
# ---------------------------------------------------------------------------


def test_a_handled_refusal_leaves_no_partial(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any]
) -> None:
    """A handled refusal leaves no partial."""
    broken = dict(assembly_inputs_ep0)
    broken["wav_bytes"] = b"not the right wav bytes at all"
    output_root = tmp_path / "out"
    output_root.mkdir()
    with pytest.raises((MediaAssemblyRefused, ValueError)):
        publish_episode_media_assembly(output_root=output_root, **broken)
    assert list(output_root.iterdir()) == []


def test_an_unexpected_exception_class_leaves_partial_intact(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unexpected exception class leaves partial intact."""

    class _UnexpectedError(Exception):
        pass

    def _boom(path: Path, payload: bytes) -> None:
        raise _UnexpectedError("simulated unrecognised crash")

    monkeypatch.setattr(publisher_module, "write_frame_exclusively", _boom)
    output_root = tmp_path / "out"
    output_root.mkdir()
    with pytest.raises(_UnexpectedError):
        publish_episode_media_assembly(output_root=output_root, **assembly_inputs_ep0)
    remaining = list(output_root.iterdir())
    assert len(remaining) == 1
    assert remaining[0].name.endswith(PARTIAL_SUFFIX)


def _stale_staging_name(inputs: dict[str, Any]) -> str:
    source = inputs["render_manifest"]["source"]
    return (
        media_assembly_id(
            mode=source["mode"],
            episode=source["episode"],
            previous_episode=source["previous_episode"],
        )
        + PARTIAL_SUFFIX
    )


def test_a_stale_prior_run_staging_tree_is_discarded(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any]
) -> None:
    """A stale tree from a dead run is discarded.

    A stale tree from a dead run is still provably this phase's own -- only legitimately
    named, empty subdirectories, as a run that died right after ``mkdir`` would leave -- so
    ``discard_owned_staging`` accepts and removes it before this run creates its own.
    """
    output_root = tmp_path / "out"
    output_root.mkdir()
    stale = output_root / _stale_staging_name(assembly_inputs_ep0)
    (stale / PRESENTATION_DIRECTORY).mkdir(parents=True)
    (stale / AUDIO_DIRECTORY).mkdir()
    (stale / PROVENANCE_DIRECTORY).mkdir()
    published = _publish(assembly_inputs_ep0, output_root)
    assert audit_media_assembly_directory(published) == []
    assert not stale.exists()


def test_a_foreign_staging_tree_refuses_without_deletion(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any]
) -> None:
    """A foreign staging tree refuses without deletion."""
    output_root = tmp_path / "out"
    output_root.mkdir()
    stale = output_root / _stale_staging_name(assembly_inputs_ep0)
    stale.mkdir()
    (stale / "definitely_not_ours").mkdir()
    with pytest.raises(MediaAssemblyDirectoryRefused):
        _publish(assembly_inputs_ep0, output_root)
    assert stale.exists()
    assert (stale / "definitely_not_ours").exists()


def test_verified_no_op_reads_the_manifest_once_with_stat_unchanged_and_no_staging(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verified no op reads the manifest once with stat unchanged and no staging."""
    output_root = tmp_path / "out"
    first = _publish(assembly_inputs_ep0, output_root)
    manifest_path = first / MEDIA_ASSEMBLY_MANIFEST_FILENAME
    before_stat = manifest_path.stat()

    calls: list[Path] = []
    real_read_bytes = Path.read_bytes

    def _tracking_read_bytes(self: Path, *args: Any, **kwargs: Any) -> bytes:
        if self == manifest_path:
            calls.append(self)
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", _tracking_read_bytes)
    second = _publish(assembly_inputs_ep0, output_root)

    assert second == first
    after_stat = manifest_path.stat()
    assert before_stat.st_mtime_ns == after_stat.st_mtime_ns
    assert before_stat.st_size == after_stat.st_size
    assert calls.count(manifest_path) == 1
    staging_leftovers = [p for p in output_root.iterdir() if p.name.endswith(PARTIAL_SUFFIX)]
    assert staging_leftovers == []


def test_refusal_when_any_bound_digest_differs(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any], assembly_inputs_ep1: dict[str, Any]
) -> None:
    """Refusal when any bound digest differs."""
    broken = dict(assembly_inputs_ep0)
    broken["delivery_plan"] = assembly_inputs_ep1["delivery_plan"]
    broken["delivery_plan_bytes"] = assembly_inputs_ep1["delivery_plan_bytes"]
    output_root = tmp_path / "out"
    output_root.mkdir()
    with pytest.raises((MediaAssemblyRefused, ValueError, TypeError)):
        publish_episode_media_assembly(output_root=output_root, **broken)


def test_simulated_enospc_is_a_handled_refusal(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulated enospc is a handled refusal."""

    def _enospc(path: Path, payload: bytes) -> None:
        raise OSError(28, "No space left on device")  # errno.ENOSPC

    monkeypatch.setattr(publisher_module, "write_frame_exclusively", _enospc)
    output_root = tmp_path / "out"
    output_root.mkdir()
    with pytest.raises(OSError):
        publish_episode_media_assembly(output_root=output_root, **assembly_inputs_ep0)
    assert list(output_root.iterdir()) == []


def test_simulated_fsync_failure_is_a_handled_refusal(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulated fsync failure is a handled refusal."""

    def _failing_fsync(fd: int) -> None:
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(os, "fsync", _failing_fsync)
    output_root = tmp_path / "out"
    output_root.mkdir()
    with pytest.raises(OSError):
        publish_episode_media_assembly(output_root=output_root, **assembly_inputs_ep0)
    assert list(output_root.iterdir()) == []


# ---------------------------------------------------------------------------
# Correction K -- K10, an otherwise byte-perfect existing final with one hardlink
# ---------------------------------------------------------------------------


def test_k10_existing_final_with_one_hardlink_is_not_a_verified_no_op(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any]
) -> None:
    """K10 existing final with one hardlink is not a verified no op."""
    if not _can_hardlink(tmp_path / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    output_root = tmp_path / "out"
    published = _publish(assembly_inputs_ep0, output_root)
    document = published / RENDER_MANIFEST_COPY_FILENAME
    outside = tmp_path / "outside_render_manifest.json"
    outside.write_bytes(document.read_bytes())
    document.unlink()
    os.link(outside, document)

    with pytest.raises(MediaAssemblyDirectoryRefused):
        _publish(assembly_inputs_ep0, output_root)

    # Nothing was deleted to make room, and the hardlink is still there afterwards.
    assert document.exists()
    assert _regular_file_link_count(document) == 2


# ---------------------------------------------------------------------------
# G5 / G6 -- existing-final refusal, nothing deleted
# ---------------------------------------------------------------------------


def test_g5_an_existing_final_directory_that_is_a_different_assembly(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any], assembly_inputs_ep1: dict[str, Any]
) -> None:
    """G5 an existing final directory that is a different assembly.

    A complete, truthful ep0 assembly already occupies the final name a second run
    wants. That run binds a different source set, so it refuses -- and deletes
    nothing to make room.
    """
    output_root = tmp_path / "out"
    published = _publish(assembly_inputs_ep0, output_root)
    assert audit_media_assembly_directory(published) == []
    before = sorted(p.name for p in published.iterdir())

    # Re-point ep1's inputs at ep0's final directory name by publishing ep1 into the
    # same root under a colliding name: forge ep0's identity onto ep1's bound digests
    # is not possible without breaking the joins, so the honest reproduction is to
    # publish ep0 again with one bound digest deliberately different.
    colliding = dict(assembly_inputs_ep0)
    colliding["delivery_plan_bytes"] = assembly_inputs_ep1["delivery_plan_bytes"]
    colliding["delivery_plan"] = assembly_inputs_ep1["delivery_plan"]

    refusals = (MediaAssemblyDirectoryRefused, MediaAssemblyRefused, ValueError, TypeError)
    with pytest.raises(refusals):
        publish_episode_media_assembly(output_root=output_root, **colliding)

    assert sorted(p.name for p in published.iterdir()) == before
    assert audit_media_assembly_directory(published) == []
    assert [p for p in output_root.iterdir() if p.name.endswith(PARTIAL_SUFFIX)] == []


def test_g6_an_existing_final_directory_that_fails_its_own_audit(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any]
) -> None:
    """G6 an existing final directory that fails its own audit.

    The existing directory is this exact source set's own assembly, but it has been
    damaged. It must NOT be accepted as a verified no-op, and nothing is deleted or
    repaired to make room.
    """
    output_root = tmp_path / "out"
    published = _publish(assembly_inputs_ep0, output_root)
    damaged = published / PRESENTATION_DIRECTORY / presentation_frame_filename(1)
    mutated = bytearray(damaged.read_bytes())
    mutated[-1] ^= 0xFF
    damaged.write_bytes(bytes(mutated))
    assert audit_media_assembly_directory(published) != []

    with pytest.raises(MediaAssemblyDirectoryRefused):
        _publish(assembly_inputs_ep0, output_root)

    assert damaged.read_bytes() == bytes(mutated), "nothing was repaired"
    assert [p for p in output_root.iterdir() if p.name.endswith(PARTIAL_SUFFIX)] == []


# ---------------------------------------------------------------------------
# B1 / B6 -- wrong-episode pairings
# ---------------------------------------------------------------------------


def test_b1_ep0_render_manifest_with_the_ep1_presentation_plan(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any], assembly_inputs_ep1: dict[str, Any]
) -> None:
    """B1 EP0 render manifest with the EP1 presentation plan."""
    mixed = dict(assembly_inputs_ep1)
    mixed["render_manifest"] = assembly_inputs_ep0["render_manifest"]
    mixed["render_manifest_bytes"] = assembly_inputs_ep0["render_manifest_bytes"]
    mixed["render_dir"] = assembly_inputs_ep0["render_dir"]
    output_root = tmp_path / "out"
    output_root.mkdir()
    refusals = (MediaAssemblyRefused, MediaAssemblyDirectoryRefused, ValueError, TypeError)
    with pytest.raises(refusals):
        publish_episode_media_assembly(output_root=output_root, **mixed)
    assert list(output_root.iterdir()) == []


def test_b6_a_phase_31_composition_of_another_episode(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any], assembly_inputs_ep1: dict[str, Any]
) -> None:
    """B6 a Phase 31 composition of another episode."""
    mixed = dict(assembly_inputs_ep1)
    mixed["audio_composition_manifest"] = assembly_inputs_ep0["audio_composition_manifest"]
    mixed["audio_composition_manifest_bytes"] = assembly_inputs_ep0[
        "audio_composition_manifest_bytes"
    ]
    mixed["wav_bytes"] = assembly_inputs_ep0["wav_bytes"]
    output_root = tmp_path / "out"
    output_root.mkdir()
    refusals = (MediaAssemblyRefused, MediaAssemblyDirectoryRefused, ValueError, TypeError)
    with pytest.raises(refusals):
        publish_episode_media_assembly(output_root=output_root, **mixed)
    assert list(output_root.iterdir()) == []


# ---------------------------------------------------------------------------
# C1 (matrix row) -- a playback PNG missing from the render directory
# ---------------------------------------------------------------------------


def test_c1_one_playback_png_deleted_from_the_render_directory(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any]
) -> None:
    """C1 one playback PNG deleted from the render directory.

    A handled ``FileNotFoundError``: the run refuses and its own staging is
    discarded, so the output root is left exactly as it was found.
    """
    from living_diorama.media_assembly.media_assembly_mapping import (
        presentation_frame_map,
        require_playback_lookup,
    )
    from living_diorama.render_execution.render_execution_spec import FRAMES_DIRECTORY

    inputs = dict(assembly_inputs_ep0)
    mapping = presentation_frame_map(inputs["presentation_plan"])
    lookup = require_playback_lookup(inputs["render_manifest"])
    victim = inputs["render_dir"] / FRAMES_DIRECTORY / lookup[mapping[0]]["file"]
    rescued = victim.read_bytes()
    victim.unlink()
    try:
        output_root = tmp_path / "out"
        output_root.mkdir()
        with pytest.raises(FileNotFoundError):
            publish_episode_media_assembly(output_root=output_root, **inputs)
        assert list(output_root.iterdir()) == []
    finally:
        # the render fixture is session-scoped: restore it for every later test
        victim.write_bytes(rescued)


# ---------------------------------------------------------------------------
# T3 / T5 -- single capture: the second read that would diverge never happens
# ---------------------------------------------------------------------------


def _poison_second_read(
    monkeypatch: pytest.MonkeyPatch, target: Path, poison: bytes
) -> dict[str, int]:
    """Serve the true bytes once for ``target``, then attacker bytes on every later read.

    If the implementation ever read the same path a second time, it would consume
    ``poison`` and diverge from what it validated. A run that still succeeds proves
    the second read does not exist.
    """
    counter = {"reads": 0}
    real_read_bytes = Path.read_bytes

    def _patched(self: Path, *args: Any, **kwargs: Any) -> bytes:
        if self == target:
            counter["reads"] += 1
            if counter["reads"] > 1:
                return poison
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", _patched)
    return counter


def test_t3_a_png_mutated_between_the_digest_check_and_the_copy(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """T3 a PNG mutated between digest check and copy.

    The source frame is read exactly once, and that same captured payload supplies
    every presentation position it is held across -- so there is no second read for
    a mutation to land between.
    """
    from living_diorama.media_assembly.media_assembly_mapping import (
        presentation_frame_map,
        require_playback_lookup,
    )
    from living_diorama.render_execution.render_execution_spec import FRAMES_DIRECTORY

    inputs = dict(assembly_inputs_ep0)
    mapping = presentation_frame_map(inputs["presentation_plan"])
    lookup = require_playback_lookup(inputs["render_manifest"])
    target = inputs["render_dir"] / FRAMES_DIRECTORY / lookup[mapping[0]]["file"]

    counter = _poison_second_read(monkeypatch, target, b"\x89PNG mutated by an attacker")
    output_root = tmp_path / "out"
    published = _publish(inputs, output_root)

    assert counter["reads"] == 1, "the source frame must be read exactly once"
    assert audit_media_assembly_directory(published) == []


def test_t5_the_wav_mutated_between_join_c2_and_the_copy(
    tmp_path: Path, assembly_inputs_ep0: dict[str, Any], composition_ep0: Path
) -> None:
    """T5 the WAV mutated between join C2 and the copy.

    ``wav_bytes`` is captured once by the caller and both proven and written from
    that single capture; the publisher never re-opens the composition directory.
    Mutating the on-disk WAV after capture therefore cannot change what is
    published, and the published copy still equals the captured, proven bytes.
    """
    from living_diorama.audio_composition.audio_composition_spec import (
        AUDIO_DIRECTORY as COMPOSITION_AUDIO_DIRECTORY,
    )
    from living_diorama.audio_composition.audio_composition_spec import (
        EPISODE_AUDIO_FILENAME as COMPOSITION_WAV_NAME,
    )

    inputs = dict(assembly_inputs_ep0)
    captured = inputs["wav_bytes"]
    on_disk = composition_ep0 / COMPOSITION_AUDIO_DIRECTORY / COMPOSITION_WAV_NAME
    rescued = on_disk.read_bytes()
    mutated = bytearray(rescued)
    mutated[-1] ^= 0xFF
    on_disk.write_bytes(bytes(mutated))
    try:
        output_root = tmp_path / "out"
        published = _publish(inputs, output_root)
        carried = (published / AUDIO_DIRECTORY / EPISODE_AUDIO_FILENAME).read_bytes()
        assert carried == captured, "the published WAV is the captured, proven payload"
        assert carried != bytes(mutated), "the post-capture mutation never reached the output"
        assert audit_media_assembly_directory(published) == []
    finally:
        # the composition fixture is session-scoped: restore it for every later test
        on_disk.write_bytes(rescued)
