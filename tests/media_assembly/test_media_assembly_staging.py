"""Filesystem ownership, atomic writes, and terminal publication -- Correction K family A.

Every governed-path indirection check, the single-link law on every owned
regular file, and the exact primitive-occurrence counts this module is
frozen to.
"""

import ast
import os
from pathlib import Path
from typing import Any

import pytest

from living_diorama.media_assembly import media_assembly_staging as staging
from living_diorama.media_assembly.media_assembly_spec import (
    AUDIO_COMPOSITION_MANIFEST_COPY_FILENAME,
    AUDIO_DIRECTORY,
    DELIVERY_PLAN_COPY_FILENAME,
    EPISODE_AUDIO_FILENAME,
    MEDIA_ASSEMBLY_MANIFEST_FILENAME,
    PRESENTATION_DIRECTORY,
    PRESENTATION_PLAN_COPY_FILENAME,
    PROVENANCE_DIRECTORY,
    RENDER_MANIFEST_COPY_FILENAME,
    SHOT_PLAN_COPY_FILENAME,
    WRITING_SUFFIX,
    presentation_frame_filename,
)

STAGING_SOURCE = Path(staging.__file__).read_text(encoding="utf-8")


def _can_hardlink(probe_dir: Path) -> bool:
    probe_dir.mkdir(parents=True, exist_ok=True)
    source = probe_dir / "_probe_source"
    source.write_bytes(b"x")
    try:
        os.link(source, probe_dir / "_probe_link")
    except OSError:
        return False
    return True


def _make_staging_tree(root: Path, name: str = "episode_0000_baseline.partial") -> Path:
    staging_dir = root / name
    (staging_dir / PRESENTATION_DIRECTORY).mkdir(parents=True)
    (staging_dir / AUDIO_DIRECTORY).mkdir()
    (staging_dir / PROVENANCE_DIRECTORY).mkdir()
    for filename in (
        RENDER_MANIFEST_COPY_FILENAME,
        PRESENTATION_PLAN_COPY_FILENAME,
        AUDIO_COMPOSITION_MANIFEST_COPY_FILENAME,
        MEDIA_ASSEMBLY_MANIFEST_FILENAME,
    ):
        (staging_dir / filename).write_bytes(b"{}")
    (staging_dir / PRESENTATION_DIRECTORY / presentation_frame_filename(1)).write_bytes(b"\x89PNG")
    (staging_dir / AUDIO_DIRECTORY / EPISODE_AUDIO_FILENAME).write_bytes(b"RIFF")
    (staging_dir / PROVENANCE_DIRECTORY / DELIVERY_PLAN_COPY_FILENAME).write_bytes(b"{}")
    (staging_dir / PROVENANCE_DIRECTORY / SHOT_PLAN_COPY_FILENAME).write_bytes(b"{}")
    return staging_dir


# ---------------------------------------------------------------------------
# require_owned_staging -- ownership acceptance and refusal
# ---------------------------------------------------------------------------


def test_a_well_formed_staging_tree_is_accepted(tmp_path: Path) -> None:
    """A well formed staging tree is accepted."""
    staging_dir = _make_staging_tree(tmp_path)
    staging.require_owned_staging(
        staging_dir, expected_parent=tmp_path, expected_name=staging_dir.name
    )


def test_a_foreign_top_level_entry_is_refused(tmp_path: Path) -> None:
    """A foreign top level entry is refused."""
    staging_dir = _make_staging_tree(tmp_path)
    (staging_dir / "intruder.txt").write_bytes(b"x")
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.require_owned_staging(
            staging_dir, expected_parent=tmp_path, expected_name=staging_dir.name
        )


def test_a_foreign_entry_inside_provenance_is_refused(tmp_path: Path) -> None:
    """A foreign entry inside provenance is refused."""
    staging_dir = _make_staging_tree(tmp_path)
    (staging_dir / PROVENANCE_DIRECTORY / "intruder.json").write_bytes(b"{}")
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.require_owned_staging(
            staging_dir, expected_parent=tmp_path, expected_name=staging_dir.name
        )


def test_a_foreign_entry_inside_presentation_is_refused(tmp_path: Path) -> None:
    """A foreign entry inside presentation is refused."""
    staging_dir = _make_staging_tree(tmp_path)
    (staging_dir / PRESENTATION_DIRECTORY / "frame_0000000.png").write_bytes(b"x")
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.require_owned_staging(
            staging_dir, expected_parent=tmp_path, expected_name=staging_dir.name
        )


def test_a_foreign_entry_inside_audio_is_refused(tmp_path: Path) -> None:
    """A foreign entry inside audio is refused."""
    staging_dir = _make_staging_tree(tmp_path)
    (staging_dir / AUDIO_DIRECTORY / "extra.wav").write_bytes(b"x")
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.require_owned_staging(
            staging_dir, expected_parent=tmp_path, expected_name=staging_dir.name
        )


def test_a_directory_inside_presentation_is_refused(tmp_path: Path) -> None:
    """A directory inside presentation is refused."""
    staging_dir = _make_staging_tree(tmp_path)
    (staging_dir / PRESENTATION_DIRECTORY / "subdir").mkdir()
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.require_owned_staging(
            staging_dir, expected_parent=tmp_path, expected_name=staging_dir.name
        )


def test_wrong_name_is_refused(tmp_path: Path) -> None:
    """Wrong name is refused."""
    staging_dir = _make_staging_tree(tmp_path)
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.require_owned_staging(
            staging_dir, expected_parent=tmp_path, expected_name="wrong_name.partial"
        )


def test_wrong_location_is_refused(tmp_path: Path) -> None:
    """Wrong location is refused."""
    staging_dir = _make_staging_tree(tmp_path)
    other = tmp_path / "elsewhere"
    other.mkdir()
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.require_owned_staging(
            staging_dir, expected_parent=other, expected_name=staging_dir.name
        )


def test_symlink_staging_directory_refused(tmp_path: Path) -> None:
    """Symlink staging directory refused."""
    real = _make_staging_tree(tmp_path, name="real.partial")
    link = tmp_path / "link.partial"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.require_owned_staging(link, expected_parent=tmp_path, expected_name=link.name)


def test_symlink_inside_staging_refused(tmp_path: Path) -> None:
    """Symlink inside staging refused."""
    staging_dir = _make_staging_tree(tmp_path)
    target = tmp_path / "target_dir"
    target.mkdir()
    try:
        (staging_dir / "sneaky").symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.require_owned_staging(
            staging_dir, expected_parent=tmp_path, expected_name=staging_dir.name
        )


def test_dangling_staging_symlink_refused_before_exists(tmp_path: Path) -> None:
    """Dangling staging symlink refused before exists."""
    missing = tmp_path / "does_not_exist.partial"
    link = tmp_path / "dangling.partial"
    try:
        link.symlink_to(missing, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.require_owned_staging(link, expected_parent=tmp_path, expected_name=link.name)


# ---------------------------------------------------------------------------
# discard_owned_staging
# ---------------------------------------------------------------------------


def test_discard_owned_staging_removes_a_well_formed_tree(tmp_path: Path) -> None:
    """Discard owned staging removes a well formed tree."""
    staging_dir = _make_staging_tree(tmp_path)
    staging.discard_owned_staging(
        staging_dir, expected_parent=tmp_path, expected_name=staging_dir.name
    )
    assert not staging_dir.exists()


def test_discard_owned_staging_on_a_missing_tree_is_a_silent_no_op(tmp_path: Path) -> None:
    """Discard owned staging on a missing tree is a silent no op."""
    missing = tmp_path / "nothing_here.partial"
    staging.discard_owned_staging(
        missing, expected_parent=tmp_path, expected_name=missing.name
    )  # must not raise


def test_discard_owned_staging_refuses_a_dangling_symlink_before_exists(tmp_path: Path) -> None:
    """Discard owned staging refuses a dangling symlink before exists."""
    missing = tmp_path / "does_not_exist.partial"
    link = tmp_path / "dangling.partial"
    try:
        link.symlink_to(missing, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.discard_owned_staging(link, expected_parent=tmp_path, expected_name=link.name)
    assert link.is_symlink()


def test_discard_owned_staging_refuses_a_foreign_entry_without_deleting(tmp_path: Path) -> None:
    """Discard owned staging refuses a foreign entry without deleting."""
    staging_dir = _make_staging_tree(tmp_path)
    (staging_dir / "intruder.txt").write_bytes(b"x")
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.discard_owned_staging(
            staging_dir, expected_parent=tmp_path, expected_name=staging_dir.name
        )
    assert staging_dir.exists()


# ---------------------------------------------------------------------------
# write_atomically / write_frame_exclusively
# ---------------------------------------------------------------------------


def test_write_atomically_leaves_no_writing_temp_on_success(tmp_path: Path) -> None:
    """Write atomically leaves no writing temp on success."""
    destination = tmp_path / "doc.json"
    staging.write_atomically(destination, b"{}")
    assert destination.read_bytes() == b"{}"
    assert not (tmp_path / ("doc.json" + WRITING_SUFFIX)).exists()


def test_write_frame_exclusively_writes_the_payload(tmp_path: Path) -> None:
    """Write frame exclusively writes the payload."""
    destination = tmp_path / "frame_0000001.png"
    staging.write_frame_exclusively(destination, b"\x89PNG")
    assert destination.read_bytes() == b"\x89PNG"


def test_write_frame_exclusively_refuses_a_second_write_to_the_same_path(tmp_path: Path) -> None:
    """Write frame exclusively refuses a second write to the same path."""
    destination = tmp_path / "frame_0000001.png"
    staging.write_frame_exclusively(destination, b"\x89PNG")
    with pytest.raises(FileExistsError):
        staging.write_frame_exclusively(destination, b"\x89PNG")


def test_write_frame_exclusively_calls_fsync_inside_the_with_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Write frame exclusively calls fsync inside the with block."""
    calls: list[str] = []
    real_fsync = os.fsync

    def _tracking_fsync(fd: int) -> None:
        calls.append("fsync")
        real_fsync(fd)

    monkeypatch.setattr(staging.os, "fsync", _tracking_fsync)
    destination = tmp_path / "frame_0000001.png"
    staging.write_frame_exclusively(destination, b"\x89PNG")
    assert calls == ["fsync"]
    assert destination.exists()


def test_write_frame_exclusively_propagates_an_fsync_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Write frame exclusively propagates an fsync oserror."""

    def _failing_fsync(fd: int) -> None:
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(staging.os, "fsync", _failing_fsync)
    destination = tmp_path / "frame_0000001.png"
    with pytest.raises(OSError):
        staging.write_frame_exclusively(destination, b"\x89PNG")


# ---------------------------------------------------------------------------
# fsync_directory / publish_owned_staging -- call order
# ---------------------------------------------------------------------------


def test_fsync_directory_is_best_effort_on_an_unsupported_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fsync directory is best effort on an unsupported platform."""

    def _failing_open(*args: Any, **kwargs: Any) -> int:
        raise OSError("simulated: directory fsync unsupported")

    monkeypatch.setattr(staging.os, "open", _failing_open)
    staging.fsync_directory(tmp_path)  # must not raise


def test_publish_owned_staging_replaces_then_fsyncs_the_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publish owned staging replaces then fsyncs the parent."""
    staging_dir = _make_staging_tree(tmp_path, name="episode_0000_baseline.partial")
    final_dir = tmp_path / "episode_0000_baseline"

    order: list[str] = []
    real_replace = staging.os.replace
    real_fsync_directory = staging.fsync_directory

    def _tracking_replace(src: Any, dst: Any) -> None:
        order.append("replace")
        real_replace(src, dst)

    def _tracking_fsync_directory(path: Path) -> None:
        order.append("fsync_directory")
        real_fsync_directory(path)

    monkeypatch.setattr(staging.os, "replace", _tracking_replace)
    monkeypatch.setattr(staging, "fsync_directory", _tracking_fsync_directory)

    staging.publish_owned_staging(
        staging_dir,
        final_dir,
        expected_parent=tmp_path,
        expected_staging_name=staging_dir.name,
        expected_final_name=final_dir.name,
    )
    assert order == ["replace", "fsync_directory"]
    assert final_dir.exists()
    assert not staging_dir.exists()


def test_a_failing_parent_fsync_does_not_undo_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing parent fsync does not undo publication."""
    staging_dir = _make_staging_tree(tmp_path, name="episode_0000_baseline.partial")
    final_dir = tmp_path / "episode_0000_baseline"

    def _failing_open(*args: Any, **kwargs: Any) -> int:
        raise OSError("simulated: parent fsync fails")

    monkeypatch.setattr(staging.os, "open", _failing_open)
    staging.publish_owned_staging(
        staging_dir,
        final_dir,
        expected_parent=tmp_path,
        expected_staging_name=staging_dir.name,
        expected_final_name=final_dir.name,
    )
    assert final_dir.exists()
    assert not staging_dir.exists()


def test_publish_owned_staging_refuses_when_final_already_exists(tmp_path: Path) -> None:
    """Publish owned staging refuses when final already exists."""
    staging_dir = _make_staging_tree(tmp_path, name="episode_0000_baseline.partial")
    final_dir = tmp_path / "episode_0000_baseline"
    final_dir.mkdir()
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.publish_owned_staging(
            staging_dir,
            final_dir,
            expected_parent=tmp_path,
            expected_staging_name=staging_dir.name,
            expected_final_name=final_dir.name,
        )
    assert staging_dir.exists()


def test_publish_owned_staging_refuses_a_dangling_final_symlink_before_exists(
    tmp_path: Path,
) -> None:
    """Publish owned staging refuses a dangling final symlink before exists."""
    staging_dir = _make_staging_tree(tmp_path, name="episode_0000_baseline.partial")
    missing_target = tmp_path / "nowhere"
    final_dir = tmp_path / "episode_0000_baseline"
    try:
        final_dir.symlink_to(missing_target, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.publish_owned_staging(
            staging_dir,
            final_dir,
            expected_parent=tmp_path,
            expected_staging_name=staging_dir.name,
            expected_final_name=final_dir.name,
        )


# ---------------------------------------------------------------------------
# Correction K -- _regular_file_link_count / _require_single_link_regular_file
# ---------------------------------------------------------------------------


def test_regular_file_link_count_accepts_a_freshly_written_file(tmp_path: Path) -> None:
    """Regular file link count accepts a freshly written file."""
    path = tmp_path / "solo.json"
    path.write_bytes(b"{}")
    assert staging._regular_file_link_count(path) == 1
    staging._require_single_link_regular_file(path, "solo file")  # must not raise


def test_regular_file_link_count_uses_lstat_and_does_not_follow_an_indirection(
    tmp_path: Path,
) -> None:
    """Regular file link count uses lstat and does not follow an indirection."""
    target = tmp_path / "target.json"
    target.write_bytes(b"{}")
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    # A symlink's own lstat link count is 1 regardless of the target's own count.
    assert staging._regular_file_link_count(link) == os.lstat(link).st_nlink


def test_require_single_link_regular_file_refuses_a_hardlink(tmp_path: Path) -> None:
    """Require single link regular file refuses a hardlink."""
    if not _can_hardlink(tmp_path / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    original = tmp_path / "original.json"
    original.write_bytes(b"{}")
    other_name = tmp_path / "other_name.json"
    os.link(original, other_name)
    assert staging._regular_file_link_count(original) == 2
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging._require_single_link_regular_file(original, "hardlinked file")


def test_require_single_link_regular_file_refuses_a_directory(tmp_path: Path) -> None:
    """Require single link regular file refuses a directory."""
    directory = tmp_path / "a_directory"
    directory.mkdir()
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging._require_single_link_regular_file(directory, "a directory")


# ---------------------------------------------------------------------------
# Correction K -- hardlinked staged entries, at every position
# ---------------------------------------------------------------------------


def _hardlink_replace(original: Path, other: Path) -> None:
    other.write_bytes(b"placeholder")
    other.unlink()
    os.link(original, other)


def test_a_staged_presentation_frame_hardlinked_to_another_is_refused(tmp_path: Path) -> None:
    """A staged presentation frame hardlinked to another is refused."""
    if not _can_hardlink(tmp_path / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    staging_dir = _make_staging_tree(tmp_path)
    frame_one = staging_dir / PRESENTATION_DIRECTORY / presentation_frame_filename(1)
    frame_two = staging_dir / PRESENTATION_DIRECTORY / presentation_frame_filename(2)
    _hardlink_replace(frame_one, frame_two)
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.require_owned_staging(
            staging_dir, expected_parent=tmp_path, expected_name=staging_dir.name
        )


def test_a_staged_wav_hardlink_is_refused(tmp_path: Path) -> None:
    """A staged WAV hardlink is refused."""
    if not _can_hardlink(tmp_path / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    staging_dir = _make_staging_tree(tmp_path)
    wav = staging_dir / AUDIO_DIRECTORY / EPISODE_AUDIO_FILENAME
    other = tmp_path / "elsewhere.wav"
    other.write_bytes(b"RIFF")
    os.link(other, wav.with_name("second.wav"))
    _hardlink_replace(other, wav)
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.require_owned_staging(
            staging_dir, expected_parent=tmp_path, expected_name=staging_dir.name
        )


def test_a_staged_provenance_witness_hardlink_is_refused(tmp_path: Path) -> None:
    """A staged provenance witness hardlink is refused."""
    if not _can_hardlink(tmp_path / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    staging_dir = _make_staging_tree(tmp_path)
    witness = staging_dir / PROVENANCE_DIRECTORY / SHOT_PLAN_COPY_FILENAME
    other = tmp_path / "elsewhere_shot_plan.json"
    other.write_bytes(b"{}")
    _hardlink_replace(other, witness)
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.require_owned_staging(
            staging_dir, expected_parent=tmp_path, expected_name=staging_dir.name
        )


def test_a_staged_top_level_document_hardlink_is_refused(tmp_path: Path) -> None:
    """A staged top level document hardlink is refused."""
    if not _can_hardlink(tmp_path / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    staging_dir = _make_staging_tree(tmp_path)
    document = staging_dir / RENDER_MANIFEST_COPY_FILENAME
    other = tmp_path / "elsewhere_render_manifest.json"
    other.write_bytes(b"{}")
    _hardlink_replace(other, document)
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.require_owned_staging(
            staging_dir, expected_parent=tmp_path, expected_name=staging_dir.name
        )


def test_a_staged_writing_temporary_hardlink_is_refused(tmp_path: Path) -> None:
    """A staged writing temporary hardlink is refused."""
    if not _can_hardlink(tmp_path / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    staging_dir = _make_staging_tree(tmp_path)
    temp = staging_dir / (RENDER_MANIFEST_COPY_FILENAME + WRITING_SUFFIX)
    other = tmp_path / "elsewhere_writing.json"
    other.write_bytes(b"{}")
    os.link(other, temp)
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.require_owned_staging(
            staging_dir, expected_parent=tmp_path, expected_name=staging_dir.name
        )


def test_a_stale_partial_tree_containing_a_hardlink_is_not_deleted(tmp_path: Path) -> None:
    """A stale partial tree containing a hardlink is not deleted."""
    if not _can_hardlink(tmp_path / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    staging_dir = _make_staging_tree(tmp_path)
    document = staging_dir / RENDER_MANIFEST_COPY_FILENAME
    other = tmp_path / "elsewhere_render_manifest.json"
    other.write_bytes(b"{}")
    _hardlink_replace(other, document)
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.discard_owned_staging(
            staging_dir, expected_parent=tmp_path, expected_name=staging_dir.name
        )
    assert staging_dir.exists()
    assert document.exists()


# ---------------------------------------------------------------------------
# Frozen primitive source-occurrence counts (§21)
# ---------------------------------------------------------------------------


def _dotted_name(node: ast.expr) -> str | None:
    """Return ``"a.b.c"`` for a plain dotted-attribute chain, else ``None``."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _call_counts(source: str) -> dict[str, int]:
    """Count actual call-expression occurrences by AST, immune to docstring/comment mentions."""
    tree = ast.parse(source)
    counts: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _dotted_name(node.func)
            if name is not None:
                counts[name] = counts.get(name, 0) + 1
        elif isinstance(node, ast.Attribute) and node.attr == "lstat":
            counts["*.lstat"] = counts.get("*.lstat", 0) + 1
    return counts


def test_source_occurrence_counts_hold() -> None:
    """Source occurrence counts hold."""
    counts = _call_counts(STAGING_SOURCE)
    assert counts.get("open", 0) == 2
    assert counts.get("os.open", 0) == 1
    assert counts.get("os.fsync", 0) == 3
    assert counts.get("os.close", 0) == 1
    assert counts.get("os.replace", 0) == 2
    assert counts.get("shutil.rmtree", 0) == 1
    assert counts.get("*.lstat", 0) == 1


# ---------------------------------------------------------------------------
# The JUNCTION half of _is_path_indirection, exercised on staging and publication
#
# Windows junction creation is not portable across every filesystem this suite may
# run on, so the junction branch is driven directly, one exact path at a time.
# ``is_symlink()`` is deliberately left alone and still returns False for the same
# path, so a test that passes here proves the JUNCTION branch alone produced the
# refusal -- it cannot be satisfied by the symlink branch. The real symlink tests
# above are untouched and still run.
# ---------------------------------------------------------------------------


def _junction_only(monkeypatch: pytest.MonkeyPatch, junction_path: Path) -> None:
    """Make exactly one path report as a junction, with symlink still False."""
    real_is_junction = Path.is_junction
    target = str(junction_path)

    def _patched(self: Path) -> bool:
        if str(self) == target:
            return True
        return real_is_junction(self)

    monkeypatch.setattr(Path, "is_junction", _patched)
    assert junction_path.is_junction()
    assert not junction_path.is_symlink()


def test_a_junction_staging_directory_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A junction staging directory is refused."""
    staging_dir = _make_staging_tree(tmp_path)
    _junction_only(monkeypatch, staging_dir)
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.require_owned_staging(
            staging_dir, expected_parent=tmp_path, expected_name=staging_dir.name
        )


def test_a_junction_output_root_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A junction output root is refused by _require_direct_parent."""
    _junction_only(monkeypatch, tmp_path)
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging._require_direct_parent(tmp_path)


@pytest.mark.parametrize(
    "governed", [PRESENTATION_DIRECTORY, AUDIO_DIRECTORY, PROVENANCE_DIRECTORY]
)
def test_a_junction_governed_directory_inside_staging_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, governed: str
) -> None:
    """A junction governed directory inside staging is refused."""
    staging_dir = _make_staging_tree(tmp_path)
    _junction_only(monkeypatch, staging_dir / governed)
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.require_owned_staging(
            staging_dir, expected_parent=tmp_path, expected_name=staging_dir.name
        )


@pytest.mark.parametrize(
    "governed",
    [
        RENDER_MANIFEST_COPY_FILENAME,
        MEDIA_ASSEMBLY_MANIFEST_FILENAME,
        f"{PRESENTATION_DIRECTORY}/{presentation_frame_filename(1)}",
        f"{AUDIO_DIRECTORY}/{EPISODE_AUDIO_FILENAME}",
        f"{PROVENANCE_DIRECTORY}/{SHOT_PLAN_COPY_FILENAME}",
    ],
)
def test_a_junction_governed_file_inside_staging_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, governed: str
) -> None:
    """A junction governed regular-file path inside staging is refused."""
    staging_dir = _make_staging_tree(tmp_path)
    _junction_only(monkeypatch, staging_dir / governed)
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.require_owned_staging(
            staging_dir, expected_parent=tmp_path, expected_name=staging_dir.name
        )


def test_a_junction_final_destination_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A junction final destination is refused before it is ever queried."""
    staging_dir = _make_staging_tree(tmp_path, name="episode_0000_baseline.partial")
    final_dir = tmp_path / "episode_0000_baseline"
    _junction_only(monkeypatch, final_dir)
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.publish_owned_staging(
            staging_dir,
            final_dir,
            expected_parent=tmp_path,
            expected_staging_name=staging_dir.name,
            expected_final_name=final_dir.name,
        )
    assert staging_dir.exists(), "nothing was published or deleted"


def test_a_junction_staging_directory_is_never_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """discard_owned_staging refuses a junction staging tree and deletes nothing."""
    staging_dir = _make_staging_tree(tmp_path)
    _junction_only(monkeypatch, staging_dir)
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.discard_owned_staging(
            staging_dir, expected_parent=tmp_path, expected_name=staging_dir.name
        )
    assert staging_dir.exists()


# ---------------------------------------------------------------------------
# G3 -- a governed subdirectory inside staging is a symlink (literal)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "governed", [PRESENTATION_DIRECTORY, AUDIO_DIRECTORY, PROVENANCE_DIRECTORY]
)
def test_g3_a_governed_subdirectory_inside_staging_is_a_symlink(
    tmp_path: Path, governed: str
) -> None:
    """G3 presentation/, audio/ or provenance/ inside staging is a symlink."""
    staging_dir = _make_staging_tree(tmp_path)
    real = staging_dir / governed
    moved = tmp_path / f"moved_{governed}"
    real.rename(moved)
    try:
        real.symlink_to(moved, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    with pytest.raises(staging.MediaAssemblyDirectoryRefused):
        staging.require_owned_staging(
            staging_dir, expected_parent=tmp_path, expected_name=staging_dir.name
        )
