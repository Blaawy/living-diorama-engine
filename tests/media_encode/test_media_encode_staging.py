"""Filesystem ownership, atomic writes and terminal publication -- Phase 35 staging laws.

Matrix V56-V60 (staging side) and V73: the full working-temporary whitelist, every
governed-path indirection check, the single-link law on every owned regular file, the
crash-recovery discard, and the atomic write / publish primitives of
``living_diorama.media_encode.media_encode_staging``, for the episode id
``episode_0000_to_0001``.
"""

import os
from pathlib import Path

import pytest

from living_diorama.caption_serialization.caption_serialization_spec import (
    SRT_SUFFIX,
    VTT_SUFFIX,
    sidecar_filename,
)
from living_diorama.media_encode import media_encode_staging as staging
from living_diorama.media_encode.media_encode_spec import (
    ASSEMBLY_MANIFEST_COPY_FILENAME,
    CAPTIONS_MANIFEST_COPY_FILENAME,
    ENCODING_SUFFIX,
    MEDIA_ENCODE_MANIFEST_FILENAME,
    PARTIAL_SUFFIX,
    PREFLIGHT_AUDIO_FILENAME,
    PREFLIGHT_MEDIA_FILENAME,
    PROVENANCE_DIRECTORY,
    PROVENANCE_DIRECTORY_ENTRIES,
    SNAPSHOT_AUDIO_FILENAME,
    WRITING_SUFFIX,
    media_filename,
)

EPISODE_ID = "episode_0000_to_0001"
STAGING_NAME = EPISODE_ID + PARTIAL_SUFFIX
FINAL_NAME = EPISODE_ID
MEDIA_NAME = media_filename(EPISODE_ID)
SRT_NAME = sidecar_filename(EPISODE_ID, SRT_SUFFIX)
VTT_NAME = sidecar_filename(EPISODE_ID, VTT_SUFFIX)


def _can_symlink(probe_dir: Path) -> bool:
    probe_dir.mkdir(parents=True, exist_ok=True)
    target = probe_dir / "_probe_target"
    target.write_bytes(b"x")
    try:
        (probe_dir / "_probe_link").symlink_to(target)
    except OSError:
        return False
    return True


def _can_hardlink(probe_dir: Path) -> bool:
    probe_dir.mkdir(parents=True, exist_ok=True)
    source = probe_dir / "_probe_source"
    source.write_bytes(b"x")
    try:
        os.link(source, probe_dir / "_probe_link")
    except OSError:
        return False
    return True


def _make_staging_tree(root: Path, name: str = STAGING_NAME) -> Path:
    """Build the full whitelist tree: every owned file and every working temporary form."""
    staging_dir = root / name
    staging_dir.mkdir()
    (staging_dir / PROVENANCE_DIRECTORY).mkdir()
    for filename in (MEDIA_ENCODE_MANIFEST_FILENAME, MEDIA_NAME, SRT_NAME, VTT_NAME):
        (staging_dir / filename).write_bytes(b"{}")
        (staging_dir / (filename + WRITING_SUFFIX)).write_bytes(b"{}")
    (staging_dir / (MEDIA_NAME + ENCODING_SUFFIX)).write_bytes(b"partial")
    (staging_dir / PREFLIGHT_MEDIA_FILENAME).write_bytes(b"preflight")
    (staging_dir / PREFLIGHT_AUDIO_FILENAME).write_bytes(b"wav")
    (staging_dir / (PREFLIGHT_AUDIO_FILENAME + WRITING_SUFFIX)).write_bytes(b"wav")
    (staging_dir / SNAPSHOT_AUDIO_FILENAME).write_bytes(b"wav")
    (staging_dir / (SNAPSHOT_AUDIO_FILENAME + WRITING_SUFFIX)).write_bytes(b"wav")
    for filename in PROVENANCE_DIRECTORY_ENTRIES:
        (staging_dir / PROVENANCE_DIRECTORY / filename).write_bytes(b"{}")
        (staging_dir / PROVENANCE_DIRECTORY / (filename + WRITING_SUFFIX)).write_bytes(b"{}")
    return staging_dir


def _make_finished_tree(root: Path, name: str = STAGING_NAME) -> Path:
    """Build a minimal FINISHED tree: manifest, mp4, both sidecars, two provenance copies."""
    staging_dir = root / name
    staging_dir.mkdir()
    (staging_dir / PROVENANCE_DIRECTORY).mkdir()
    (staging_dir / MEDIA_ENCODE_MANIFEST_FILENAME).write_bytes(b"{}")
    (staging_dir / MEDIA_NAME).write_bytes(b"\x00\x00\x00\x18ftypmp42")
    (staging_dir / SRT_NAME).write_bytes(b"1\n00:00:00,000 --> 00:00:01,000\nHi\n")
    (staging_dir / VTT_NAME).write_bytes(b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHi\n")
    for filename in PROVENANCE_DIRECTORY_ENTRIES:
        (staging_dir / PROVENANCE_DIRECTORY / filename).write_bytes(b"{}")
    return staging_dir


def _require_owned(staging_dir: Path, root: Path) -> None:
    staging.require_owned_staging(
        staging_dir,
        expected_parent=root,
        expected_name=staging_dir.name,
        episode_id=EPISODE_ID,
    )


def _discard(staging_dir: Path, root: Path) -> None:
    staging.discard_owned_staging(
        staging_dir,
        expected_parent=root,
        expected_name=staging_dir.name,
        episode_id=EPISODE_ID,
    )


def _publish(staging_dir: Path, final_dir: Path, root: Path) -> None:
    staging.publish_owned_staging(
        staging_dir,
        final_dir,
        expected_parent=root,
        expected_staging_name=staging_dir.name,
        expected_final_name=final_dir.name,
        episode_id=EPISODE_ID,
    )


# ---------------------------------------------------------------------------
# require_owned_staging -- whitelist acceptance and refusal
# ---------------------------------------------------------------------------


def test_the_full_working_temporary_whitelist_tree_is_accepted(tmp_path: Path) -> None:
    """The full working-temporary whitelist tree is accepted.

    A tree holding the manifest, the mp4, both sidecars, every preflight and
    snapshot temporary (.writing and .encoding forms) and the two provenance
    copies passes.
    """
    staging_dir = _make_staging_tree(tmp_path)
    _require_owned(staging_dir, tmp_path)  # must not raise


def test_a_foreign_top_level_file_is_refused(tmp_path: Path) -> None:
    """A foreign top level file is refused as not owned."""
    staging_dir = _make_staging_tree(tmp_path)
    (staging_dir / "x.bin").write_bytes(b"x")
    with pytest.raises(staging.MediaEncodeDirectoryRefused, match="is not owned"):
        _require_owned(staging_dir, tmp_path)


def test_a_foreign_provenance_entry_is_refused(tmp_path: Path) -> None:
    """A foreign entry inside provenance is refused."""
    staging_dir = _make_staging_tree(tmp_path)
    (staging_dir / PROVENANCE_DIRECTORY / "intruder.json").write_bytes(b"{}")
    with pytest.raises(staging.MediaEncodeDirectoryRefused, match="not an owned provenance"):
        _require_owned(staging_dir, tmp_path)


def test_a_stray_directory_other_than_provenance_is_refused_as_not_owned(tmp_path: Path) -> None:
    """A stray top-level directory is refused as not owned.

    The 'expected to be a directory' wording is a provenance-only refusal and
    is never reached for a stray top-level directory.
    """
    staging_dir = _make_staging_tree(tmp_path)
    (staging_dir / "junk").mkdir()
    with pytest.raises(staging.MediaEncodeDirectoryRefused, match="is not owned"):
        _require_owned(staging_dir, tmp_path)


def test_wrong_staging_name_is_refused(tmp_path: Path) -> None:
    """A staging directory whose name does not match the expected name is refused."""
    staging_dir = _make_staging_tree(tmp_path)
    with pytest.raises(staging.MediaEncodeDirectoryRefused, match="does not match the expected"):
        staging.require_owned_staging(
            staging_dir,
            expected_parent=tmp_path,
            expected_name="wrong_name.partial",
            episode_id=EPISODE_ID,
        )


def test_wrong_parent_depth_is_refused(tmp_path: Path) -> None:
    """A staging directory nested one level too deep is refused by exact location."""
    deeper = tmp_path / "deeper"
    deeper.mkdir()
    staging_dir = _make_staging_tree(deeper)
    with pytest.raises(staging.MediaEncodeDirectoryRefused, match="does not sit directly under"):
        _require_owned(staging_dir, tmp_path)


def test_a_hardlinked_mp4_is_refused_never_a_hardlink(tmp_path: Path) -> None:
    """A hardlinked mp4 is refused: an owned regular file must be one physical copy."""
    if not _can_hardlink(tmp_path / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    staging_dir = _make_staging_tree(tmp_path)
    other = tmp_path / "elsewhere.mp4"
    other.write_bytes(b"x")
    media_path = staging_dir / MEDIA_NAME
    media_path.unlink()
    os.link(other, media_path)
    with pytest.raises(staging.MediaEncodeDirectoryRefused, match="never a hardlink"):
        _require_owned(staging_dir, tmp_path)


def test_a_symlinked_entry_inside_staging_is_refused(tmp_path: Path) -> None:
    """A symlinked entry inside staging is refused."""
    if not _can_symlink(tmp_path / "probe_area"):
        pytest.skip("platform cannot create a symlink")
    staging_dir = _make_staging_tree(tmp_path)
    target = tmp_path / "target.bin"
    target.write_bytes(b"x")
    (staging_dir / "sneaky").symlink_to(target)
    with pytest.raises(
        staging.MediaEncodeDirectoryRefused, match="symlink or junction inside staging"
    ):
        _require_owned(staging_dir, tmp_path)


def test_a_symlinked_parent_is_refused(tmp_path: Path) -> None:
    """A symlinked expected parent is refused before anything is traversed."""
    if not _can_symlink(tmp_path / "probe_area"):
        pytest.skip("platform cannot create a symlink")
    real_parent = tmp_path / "real_parent"
    real_parent.mkdir()
    link_parent = tmp_path / "link_parent"
    link_parent.symlink_to(real_parent, target_is_directory=True)
    staging_dir = _make_staging_tree(link_parent)
    with pytest.raises(staging.MediaEncodeDirectoryRefused, match="symlink or junction"):
        staging.require_owned_staging(
            staging_dir,
            expected_parent=link_parent,
            expected_name=staging_dir.name,
            episode_id=EPISODE_ID,
        )


def test_a_provenance_subdirectory_is_never_permitted(tmp_path: Path) -> None:
    """A subdirectory inside provenance is refused as never permitted."""
    staging_dir = _make_staging_tree(tmp_path)
    (staging_dir / PROVENANCE_DIRECTORY / "sub").mkdir()
    with pytest.raises(staging.MediaEncodeDirectoryRefused, match="never permitted"):
        _require_owned(staging_dir, tmp_path)


# ---------------------------------------------------------------------------
# discard_owned_staging
# ---------------------------------------------------------------------------


def test_discard_owned_staging_is_silent_when_absent(tmp_path: Path) -> None:
    """Discard on a missing staging tree is a silent no op."""
    missing = tmp_path / "nothing_here.partial"
    staging.discard_owned_staging(
        missing,
        expected_parent=tmp_path,
        expected_name=missing.name,
        episode_id=EPISODE_ID,
    )  # must not raise


def test_discard_owned_staging_refuses_foreign_content_and_keeps_the_tree(
    tmp_path: Path,
) -> None:
    """Foreign content refuses discard and the tree survives."""
    staging_dir = _make_staging_tree(tmp_path)
    (staging_dir / "x.bin").write_bytes(b"x")
    with pytest.raises(staging.MediaEncodeDirectoryRefused, match="is not owned"):
        _discard(staging_dir, tmp_path)
    assert staging_dir.exists()
    assert (staging_dir / "x.bin").exists()


def test_discard_owned_staging_removes_the_owned_full_tree(tmp_path: Path) -> None:
    """The owned full tree, working .encoding temporaries included, is removed."""
    staging_dir = _make_staging_tree(tmp_path)
    _discard(staging_dir, tmp_path)
    assert not staging_dir.exists()


def test_crash_leftover_encoding_temps_are_provably_owned_and_discarded(tmp_path: Path) -> None:
    """The wedge-hazard regression: crash-leftover .encoding temps discard cleanly.

    A tree holding 'source_audio.wav.encoding' and a partial
    'episode_0000_to_0001.mp4.encoding' MUST discard cleanly.

    The staging whitelist deliberately admits every working temporary this phase can
    create (``media_encode_spec.ENCODING_SUFFIX``: the extension buys the truthful
    ``"partial"`` label), so a crash at ANY point leaves a tree the next run's discard
    provably owns and removes -- the skeptic-closed crash-recovery law.
    """
    staging_dir = tmp_path / STAGING_NAME
    staging_dir.mkdir()
    (staging_dir / MEDIA_ENCODE_MANIFEST_FILENAME).write_bytes(b"{}")
    (staging_dir / SNAPSHOT_AUDIO_FILENAME).write_bytes(b"wav")
    (staging_dir / (MEDIA_NAME + ENCODING_SUFFIX)).write_bytes(b"partial")
    _discard(staging_dir, tmp_path)
    assert not staging_dir.exists()


def test_discard_owned_staging_refuses_a_dangling_staging_symlink_before_exists(
    tmp_path: Path,
) -> None:
    """A dangling staging symlink is refused before exists() short-circuits."""
    if not _can_symlink(tmp_path / "probe_area"):
        pytest.skip("platform cannot create a symlink")
    missing = tmp_path / "does_not_exist.partial"
    link = tmp_path / "dangling.partial"
    link.symlink_to(missing, target_is_directory=True)
    with pytest.raises(staging.MediaEncodeDirectoryRefused, match="symlink or junction"):
        _discard(link, tmp_path)
    assert link.is_symlink()


# ---------------------------------------------------------------------------
# write_atomically
# ---------------------------------------------------------------------------


def test_write_atomically_writes_bytes_and_leaves_no_writing_temp(tmp_path: Path) -> None:
    """Write atomically writes the payload and leaves no .writing temp on success."""
    destination = tmp_path / "doc.json"
    staging.write_atomically(destination, b"{}")
    assert destination.read_bytes() == b"{}"
    assert not (tmp_path / ("doc.json" + WRITING_SUFFIX)).exists()


# ---------------------------------------------------------------------------
# fsync_file
# ---------------------------------------------------------------------------


def test_fsync_file_syncs_an_existing_file_without_raising(tmp_path: Path) -> None:
    """Fsync on an existing regular file must not raise."""
    path = tmp_path / "solo.bin"
    path.write_bytes(b"payload")
    staging.fsync_file(path)  # must not raise


def test_fsync_file_raises_oserror_on_a_missing_path(tmp_path: Path) -> None:
    """Fsync on a missing path raises OSError."""
    with pytest.raises(OSError):
        staging.fsync_file(tmp_path / "missing.bin")


# ---------------------------------------------------------------------------
# read_file_bytes
# ---------------------------------------------------------------------------


def test_read_file_bytes_returns_the_exact_bytes(tmp_path: Path) -> None:
    """Read file bytes returns the exact payload bytes."""
    payload = b"\x00\x01\x02payload\xff"
    path = tmp_path / "blob.bin"
    path.write_bytes(payload)
    assert staging.read_file_bytes(path) == payload


# ---------------------------------------------------------------------------
# remove_owned_temporary
# ---------------------------------------------------------------------------


def test_remove_owned_temporary_unlinks_a_direct_child(tmp_path: Path) -> None:
    """A direct child of staging is unlinked and nothing else is touched."""
    staging_dir = _make_staging_tree(tmp_path)
    path = staging_dir / SNAPSHOT_AUDIO_FILENAME
    staging.remove_owned_temporary(path, staging_dir=staging_dir)
    assert not path.exists()
    assert staging_dir.exists()


def test_remove_owned_temporary_refuses_a_path_outside_staging(tmp_path: Path) -> None:
    """A path that does not sit directly inside staging is refused."""
    staging_dir = _make_staging_tree(tmp_path)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"x")
    with pytest.raises(staging.MediaEncodeDirectoryRefused, match="does not sit directly inside"):
        staging.remove_owned_temporary(outside, staging_dir=staging_dir)
    assert outside.exists()


def test_remove_owned_temporary_refuses_a_symlink_child(tmp_path: Path) -> None:
    """A symlink child is refused and never deleted through."""
    if not _can_symlink(tmp_path / "probe_area"):
        pytest.skip("platform cannot create a symlink")
    staging_dir = _make_staging_tree(tmp_path)
    target = tmp_path / "target.bin"
    target.write_bytes(b"x")
    link = staging_dir / "sneaky"
    link.symlink_to(target)
    with pytest.raises(staging.MediaEncodeDirectoryRefused, match="symlink or junction"):
        staging.remove_owned_temporary(link, staging_dir=staging_dir)
    assert link.is_symlink()
    assert target.exists()


def test_remove_owned_temporary_refuses_a_directory_child(tmp_path: Path) -> None:
    """A directory child is refused as not a regular file."""
    staging_dir = _make_staging_tree(tmp_path)
    subdir = staging_dir / "junk"
    subdir.mkdir()
    with pytest.raises(staging.MediaEncodeDirectoryRefused, match="not a regular file"):
        staging.remove_owned_temporary(subdir, staging_dir=staging_dir)
    assert subdir.is_dir()


def test_remove_owned_temporary_refuses_a_missing_file_as_not_a_regular_file(
    tmp_path: Path,
) -> None:
    """A missing path is refused as 'not a regular file'; no OSError is reached."""
    staging_dir = _make_staging_tree(tmp_path)
    missing = staging_dir / "missing.bin"
    with pytest.raises(staging.MediaEncodeDirectoryRefused, match="not a regular file"):
        staging.remove_owned_temporary(missing, staging_dir=staging_dir)


# ---------------------------------------------------------------------------
# publish_owned_staging
# ---------------------------------------------------------------------------


def test_publish_owned_staging_renames_a_finished_tree_onto_the_final(tmp_path: Path) -> None:
    """A minimal FINISHED tree publishes onto the final name, atomically."""
    staging_dir = _make_finished_tree(tmp_path)
    final_dir = tmp_path / FINAL_NAME
    _publish(staging_dir, final_dir, tmp_path)
    assert final_dir.is_dir()
    assert not staging_dir.exists()
    assert (final_dir / MEDIA_NAME).read_bytes() == b"\x00\x00\x00\x18ftypmp42"
    assert (final_dir / PROVENANCE_DIRECTORY / ASSEMBLY_MANIFEST_COPY_FILENAME).exists()
    assert (final_dir / PROVENANCE_DIRECTORY / CAPTIONS_MANIFEST_COPY_FILENAME).exists()


def test_publish_owned_staging_refuses_when_final_already_exists(tmp_path: Path) -> None:
    """An existing final is refused: nothing is deleted or overwritten."""
    staging_dir = _make_finished_tree(tmp_path)
    final_dir = tmp_path / FINAL_NAME
    final_dir.mkdir()
    with pytest.raises(
        staging.MediaEncodeDirectoryRefused, match="nothing is deleted or overwritten"
    ):
        _publish(staging_dir, final_dir, tmp_path)
    assert staging_dir.exists()


def test_publish_owned_staging_publishes_a_tree_with_a_leftover_encoding_temp(
    tmp_path: Path,
) -> None:
    """A staging tree still holding a .encoding working temporary STILL publishes.

    Division of labor, asserted as the code actually behaves: the staging whitelist
    deliberately labels every working temporary -- .writing and .encoding alike -- as
    this phase's own, so ``require_owned_staging`` passes and the terminal rename goes
    through. Refusing a *published* directory that still holds a leftover is the
    terminal AUDIT's law (``audit_media_encode_directory`` classifies such names
    "partial" and reports "a directory holding one is not a finished build"), not a
    staging-law refusal: staging law proves ownership and permits recovery; the audit
    judges finishedness.
    """
    staging_dir = _make_staging_tree(tmp_path)
    final_dir = tmp_path / FINAL_NAME
    _publish(staging_dir, final_dir, tmp_path)
    assert final_dir.is_dir()
    assert not staging_dir.exists()
    assert (final_dir / SNAPSHOT_AUDIO_FILENAME).exists(), "the leftover rode along"


def test_publish_owned_staging_refuses_a_dangling_final_symlink_before_exists(
    tmp_path: Path,
) -> None:
    """A dangling final symlink is refused before exists() would report False."""
    if not _can_symlink(tmp_path / "probe_area"):
        pytest.skip("platform cannot create a symlink")
    staging_dir = _make_finished_tree(tmp_path)
    missing_target = tmp_path / "nowhere"
    final_dir = tmp_path / FINAL_NAME
    final_dir.symlink_to(missing_target, target_is_directory=True)
    with pytest.raises(staging.MediaEncodeDirectoryRefused, match="symlink or junction"):
        _publish(staging_dir, final_dir, tmp_path)
    assert staging_dir.exists(), "nothing was published or deleted"


def test_fsync_directory_is_silent_on_an_absent_path(tmp_path: Path) -> None:
    """Fsync directory on an absent path is silent, not a failure."""
    staging.fsync_directory(tmp_path / "does_not_exist")  # must not raise
