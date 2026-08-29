"""Filesystem ownership, atomic writes, and terminal publication -- Phase 34 caption serialization.

Every governed-path indirection check, the single-link law on every owned
regular file, and the flat four-file contract of a caption serialization
staging tree.
"""

import itertools
import os
from pathlib import Path

import pytest

from living_diorama.caption_serialization import caption_serialization_staging as staging
from living_diorama.caption_serialization.caption_serialization_spec import (
    CAPTION_PLAN_COPY_FILENAME,
    CAPTION_SERIALIZATION_MANIFEST_FILENAME,
    PARTIAL_SUFFIX,
    SRT_SUFFIX,
    VTT_SUFFIX,
    WRITING_SUFFIX,
    sidecar_filename,
)

EPISODE_ID = "episode_0000_to_0001"
STAGING_NAME = f"{EPISODE_ID}{PARTIAL_SUFFIX}"

_OWNED_FILENAMES = (
    CAPTION_SERIALIZATION_MANIFEST_FILENAME,
    CAPTION_PLAN_COPY_FILENAME,
    sidecar_filename(EPISODE_ID, SRT_SUFFIX),
    sidecar_filename(EPISODE_ID, VTT_SUFFIX),
)

# Every non-empty subset of the four owned names: any of them must be accepted.
_SUBSETS = [
    subset
    for size in range(1, len(_OWNED_FILENAMES) + 1)
    for subset in itertools.combinations(_OWNED_FILENAMES, size)
]


def _can_hardlink(probe_dir: Path) -> bool:
    probe_dir.mkdir(parents=True, exist_ok=True)
    source = probe_dir / "_probe_source"
    source.write_bytes(b"x")
    try:
        os.link(source, probe_dir / "_probe_link")
    except OSError:
        return False
    return True


def _hardlink_replace(original: Path, other: Path) -> None:
    other.write_bytes(b"placeholder")
    other.unlink()
    os.link(original, other)


def _make_staging_tree(
    root: Path, name: str = STAGING_NAME, filenames: tuple[str, ...] = _OWNED_FILENAMES
) -> Path:
    staging_dir = root / name
    staging_dir.mkdir()
    for filename in filenames:
        (staging_dir / filename).write_bytes(b"{}")
    return staging_dir


# ---------------------------------------------------------------------------
# require_owned_staging -- ownership acceptance and refusal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("subset", _SUBSETS)
def test_require_owned_staging_accepts_any_subset_of_owned_files(
    tmp_path: Path, subset: tuple[str, ...]
) -> None:
    """Require owned staging accepts any subset of the owned files."""
    staging_dir = _make_staging_tree(tmp_path, filenames=subset)
    staging.require_owned_staging(
        staging_dir, expected_parent=tmp_path, expected_name=STAGING_NAME, episode_id=EPISODE_ID
    )


def test_require_owned_staging_accepts_writing_forms(tmp_path: Path) -> None:
    """Require owned staging accepts the .writing forms of every owned name."""
    staging_dir = _make_staging_tree(
        tmp_path, filenames=tuple(name + WRITING_SUFFIX for name in _OWNED_FILENAMES)
    )
    staging.require_owned_staging(
        staging_dir, expected_parent=tmp_path, expected_name=STAGING_NAME, episode_id=EPISODE_ID
    )


def test_require_owned_staging_refuses_a_wrong_name(tmp_path: Path) -> None:
    """Require owned staging refuses a wrong name."""
    staging_dir = _make_staging_tree(tmp_path)
    with pytest.raises(staging.CaptionSerializationDirectoryRefused):
        staging.require_owned_staging(
            staging_dir,
            expected_parent=tmp_path,
            expected_name="wrong_name.partial",
            episode_id=EPISODE_ID,
        )


def test_require_owned_staging_refuses_a_wrong_parent(tmp_path: Path) -> None:
    """Require owned staging refuses a staging nested one level deeper."""
    nested = tmp_path / "nested"
    nested.mkdir()
    staging_dir = _make_staging_tree(nested)
    with pytest.raises(staging.CaptionSerializationDirectoryRefused):
        staging.require_owned_staging(
            staging_dir,
            expected_parent=tmp_path,
            expected_name=STAGING_NAME,
            episode_id=EPISODE_ID,
        )


def test_require_owned_staging_refuses_a_file_in_place_of_a_directory(tmp_path: Path) -> None:
    """Require owned staging refuses a staging path that is a file, not a directory."""
    staging_path = tmp_path / STAGING_NAME
    staging_path.write_bytes(b"{}")
    with pytest.raises(staging.CaptionSerializationDirectoryRefused):
        staging.require_owned_staging(
            staging_path,
            expected_parent=tmp_path,
            expected_name=STAGING_NAME,
            episode_id=EPISODE_ID,
        )


def test_require_owned_staging_refuses_a_foreign_entry(tmp_path: Path) -> None:
    """Require owned staging refuses an entry outside the whitelist."""
    staging_dir = _make_staging_tree(tmp_path)
    (staging_dir / "intruder.txt").write_bytes(b"x")
    with pytest.raises(staging.CaptionSerializationDirectoryRefused):
        staging.require_owned_staging(
            staging_dir,
            expected_parent=tmp_path,
            expected_name=STAGING_NAME,
            episode_id=EPISODE_ID,
        )


def test_require_owned_staging_refuses_a_directory_inside_staging(tmp_path: Path) -> None:
    """Require owned staging refuses a directory inside staging; the tree is flat."""
    staging_dir = _make_staging_tree(tmp_path)
    (staging_dir / "subdir").mkdir()
    with pytest.raises(staging.CaptionSerializationDirectoryRefused):
        staging.require_owned_staging(
            staging_dir,
            expected_parent=tmp_path,
            expected_name=STAGING_NAME,
            episode_id=EPISODE_ID,
        )


def test_require_owned_staging_refuses_a_symlinked_entry(tmp_path: Path) -> None:
    """Require owned staging refuses a symlinked entry, even under an owned name."""
    staging_dir = _make_staging_tree(tmp_path, filenames=(CAPTION_PLAN_COPY_FILENAME,))
    target = tmp_path / "target.json"
    target.write_bytes(b"{}")
    try:
        (staging_dir / CAPTION_SERIALIZATION_MANIFEST_FILENAME).symlink_to(target)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    with pytest.raises(staging.CaptionSerializationDirectoryRefused):
        staging.require_owned_staging(
            staging_dir,
            expected_parent=tmp_path,
            expected_name=STAGING_NAME,
            episode_id=EPISODE_ID,
        )


def test_require_owned_staging_refuses_a_hardlinked_owned_file(tmp_path: Path) -> None:
    """Require owned staging refuses an owned file that is a hardlink."""
    if not _can_hardlink(tmp_path / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    staging_dir = _make_staging_tree(tmp_path, filenames=(CAPTION_SERIALIZATION_MANIFEST_FILENAME,))
    other = tmp_path / "elsewhere_manifest.json"
    other.write_bytes(b"{}")
    _hardlink_replace(other, staging_dir / CAPTION_SERIALIZATION_MANIFEST_FILENAME)
    with pytest.raises(staging.CaptionSerializationDirectoryRefused):
        staging.require_owned_staging(
            staging_dir,
            expected_parent=tmp_path,
            expected_name=STAGING_NAME,
            episode_id=EPISODE_ID,
        )


def test_require_owned_staging_refuses_a_symlinked_staging_directory(tmp_path: Path) -> None:
    """Require owned staging refuses a staging directory that is itself a symlink."""
    real = _make_staging_tree(tmp_path, name="real.partial")
    link = tmp_path / STAGING_NAME
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    with pytest.raises(staging.CaptionSerializationDirectoryRefused):
        staging.require_owned_staging(
            link, expected_parent=tmp_path, expected_name=STAGING_NAME, episode_id=EPISODE_ID
        )


def test_require_owned_staging_refuses_a_symlinked_expected_parent(tmp_path: Path) -> None:
    """Require owned staging refuses an expected parent that is a symlink."""
    real = tmp_path / "real_output_root"
    real.mkdir()
    staging_dir = _make_staging_tree(real)
    link = tmp_path / "linked_output_root"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    with pytest.raises(staging.CaptionSerializationDirectoryRefused):
        staging.require_owned_staging(
            staging_dir, expected_parent=link, expected_name=STAGING_NAME, episode_id=EPISODE_ID
        )


# ---------------------------------------------------------------------------
# discard_owned_staging
# ---------------------------------------------------------------------------


def test_discard_owned_staging_removes_a_proven_tree(tmp_path: Path) -> None:
    """Discard owned staging removes a proven-own tree."""
    staging_dir = _make_staging_tree(tmp_path)
    staging.discard_owned_staging(
        staging_dir, expected_parent=tmp_path, expected_name=STAGING_NAME, episode_id=EPISODE_ID
    )
    assert not staging_dir.exists()


def test_discard_owned_staging_on_a_missing_dir_is_a_silent_no_op(tmp_path: Path) -> None:
    """Discard owned staging on a missing directory is a silent no op."""
    missing = tmp_path / "nothing_here.partial"
    staging.discard_owned_staging(
        missing, expected_parent=tmp_path, expected_name=missing.name, episode_id=EPISODE_ID
    )  # must not raise


def test_discard_owned_staging_refuses_a_foreign_entry_without_deleting(tmp_path: Path) -> None:
    """Discard owned staging refuses a foreign entry without deleting the tree."""
    staging_dir = _make_staging_tree(tmp_path)
    (staging_dir / "intruder.txt").write_bytes(b"x")
    with pytest.raises(staging.CaptionSerializationDirectoryRefused):
        staging.discard_owned_staging(
            staging_dir,
            expected_parent=tmp_path,
            expected_name=STAGING_NAME,
            episode_id=EPISODE_ID,
        )
    assert staging_dir.exists()


def test_discard_owned_staging_refuses_a_dangling_symlink_before_exists(tmp_path: Path) -> None:
    """Discard owned staging refuses a dangling staging symlink before exists."""
    missing = tmp_path / "does_not_exist.partial"
    link = tmp_path / "dangling.partial"
    try:
        link.symlink_to(missing, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    with pytest.raises(staging.CaptionSerializationDirectoryRefused):
        staging.discard_owned_staging(
            link, expected_parent=tmp_path, expected_name=link.name, episode_id=EPISODE_ID
        )
    assert link.is_symlink()


def test_discard_owned_staging_refuses_a_symlinked_expected_parent(tmp_path: Path) -> None:
    """Discard owned staging refuses an expected parent that is a symlink."""
    real = tmp_path / "real_output_root"
    real.mkdir()
    staging_dir = _make_staging_tree(real)
    link = tmp_path / "linked_output_root"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    with pytest.raises(staging.CaptionSerializationDirectoryRefused):
        staging.discard_owned_staging(
            staging_dir, expected_parent=link, expected_name=STAGING_NAME, episode_id=EPISODE_ID
        )
    assert staging_dir.exists()


# ---------------------------------------------------------------------------
# write_atomically
# ---------------------------------------------------------------------------


def test_write_atomically_writes_the_payload_and_leaves_no_temp(tmp_path: Path) -> None:
    """Write atomically writes the payload and leaves no .writing temp."""
    destination = tmp_path / "episode_caption_plan.json"
    staging.write_atomically(destination, b"{}")
    assert destination.read_bytes() == b"{}"
    assert not (tmp_path / ("episode_caption_plan.json" + WRITING_SUFFIX)).exists()


def test_write_atomically_overwrites_an_existing_file(tmp_path: Path) -> None:
    """Write atomically overwrites an existing file; the second payload wins."""
    destination = tmp_path / "episode_caption_plan.json"
    staging.write_atomically(destination, b"first payload")
    staging.write_atomically(destination, b"second payload")
    assert destination.read_bytes() == b"second payload"
    assert not (tmp_path / ("episode_caption_plan.json" + WRITING_SUFFIX)).exists()


# ---------------------------------------------------------------------------
# fsync_directory / publish_owned_staging
# ---------------------------------------------------------------------------


def test_fsync_directory_on_a_missing_path_returns_silently(tmp_path: Path) -> None:
    """Fsync directory on a missing path returns silently."""
    staging.fsync_directory(tmp_path / "does_not_exist")  # must not raise


def test_publish_owned_staging_renames_staging_onto_final(tmp_path: Path) -> None:
    """Publish owned staging renames staging onto the final name."""
    staging_dir = _make_staging_tree(tmp_path)
    final_dir = tmp_path / EPISODE_ID
    staging.publish_owned_staging(
        staging_dir,
        final_dir,
        expected_parent=tmp_path,
        expected_staging_name=STAGING_NAME,
        expected_final_name=EPISODE_ID,
        episode_id=EPISODE_ID,
    )
    assert final_dir.exists()
    assert not staging_dir.exists()
    assert (final_dir / CAPTION_SERIALIZATION_MANIFEST_FILENAME).exists()


def test_publish_owned_staging_refuses_when_final_already_exists(tmp_path: Path) -> None:
    """Publish owned staging refuses when the final already exists."""
    staging_dir = _make_staging_tree(tmp_path)
    final_dir = tmp_path / EPISODE_ID
    final_dir.mkdir()
    with pytest.raises(staging.CaptionSerializationDirectoryRefused):
        staging.publish_owned_staging(
            staging_dir,
            final_dir,
            expected_parent=tmp_path,
            expected_staging_name=STAGING_NAME,
            expected_final_name=EPISODE_ID,
            episode_id=EPISODE_ID,
        )
    assert staging_dir.exists()


def test_publish_owned_staging_refuses_a_final_name_mismatch(tmp_path: Path) -> None:
    """Publish owned staging refuses when the final name does not match."""
    staging_dir = _make_staging_tree(tmp_path)
    final_dir = tmp_path / EPISODE_ID
    with pytest.raises(staging.CaptionSerializationDirectoryRefused):
        staging.publish_owned_staging(
            staging_dir,
            final_dir,
            expected_parent=tmp_path,
            expected_staging_name=STAGING_NAME,
            expected_final_name="wrong_final_name",
            episode_id=EPISODE_ID,
        )
    assert staging_dir.exists()
    assert not final_dir.exists()


def test_publish_owned_staging_refuses_unproven_staging(tmp_path: Path) -> None:
    """Publish owned staging refuses a staging tree with a foreign entry."""
    staging_dir = _make_staging_tree(tmp_path)
    (staging_dir / "intruder.txt").write_bytes(b"x")
    final_dir = tmp_path / EPISODE_ID
    with pytest.raises(staging.CaptionSerializationDirectoryRefused):
        staging.publish_owned_staging(
            staging_dir,
            final_dir,
            expected_parent=tmp_path,
            expected_staging_name=STAGING_NAME,
            expected_final_name=EPISODE_ID,
            episode_id=EPISODE_ID,
        )
    assert staging_dir.exists()
    assert not final_dir.exists()


def test_publish_owned_staging_refuses_a_dangling_final_symlink_before_exists(
    tmp_path: Path,
) -> None:
    """Publish owned staging refuses a dangling final symlink before exists."""
    staging_dir = _make_staging_tree(tmp_path)
    missing_target = tmp_path / "nowhere"
    final_dir = tmp_path / EPISODE_ID
    try:
        final_dir.symlink_to(missing_target, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    with pytest.raises(staging.CaptionSerializationDirectoryRefused):
        staging.publish_owned_staging(
            staging_dir,
            final_dir,
            expected_parent=tmp_path,
            expected_staging_name=STAGING_NAME,
            expected_final_name=EPISODE_ID,
            episode_id=EPISODE_ID,
        )
    assert staging_dir.exists()
    assert final_dir.is_symlink()
