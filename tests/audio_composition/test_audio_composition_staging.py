"""The Phase 31 staging primitives: ownership, atomic writes, terminal publication.

Windows junction tests are skipped where the platform or the invoking
account cannot create a junction -- explicit, architecture-authorized
platform behaviour, never a silent pass.
"""

import pytest

from living_diorama.audio_composition.audio_composition_staging import (
    CompositionDirectoryRefused,
    discard_owned_staging,
    fsync_directory,
    publish_owned_staging,
    require_owned_staging,
    write_atomically,
)


def _make_junction(link: "object", target: "object") -> bool:
    """Attempt to create a Windows junction; return whether it succeeded."""
    import subprocess

    try:
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


# ---- require_owned_staging


def test_require_owned_staging_happy_path(tmp_path) -> None:
    """Require owned staging happy path."""
    staging = tmp_path / "episode_0000_baseline.partial"
    staging.mkdir()
    (staging / "audio").mkdir()
    require_owned_staging(staging, expected_parent=tmp_path, expected_name=staging.name)


def test_require_owned_staging_refuses_wrong_name(tmp_path) -> None:
    """Require owned staging refuses wrong name."""
    staging = tmp_path / "actual_name"
    staging.mkdir()
    with pytest.raises(CompositionDirectoryRefused):
        require_owned_staging(staging, expected_parent=tmp_path, expected_name="other_name")


def test_require_owned_staging_refuses_wrong_parent(tmp_path) -> None:
    """Require owned staging refuses wrong parent."""
    staging = tmp_path / "child"
    staging.mkdir()
    wrong_parent = tmp_path / "wrong"
    wrong_parent.mkdir()
    with pytest.raises(CompositionDirectoryRefused):
        require_owned_staging(staging, expected_parent=wrong_parent, expected_name="child")


def test_require_owned_staging_refuses_foreign_entry(tmp_path) -> None:
    """Require owned staging refuses foreign entry."""
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "stray.txt").write_text("hi", encoding="utf-8")
    with pytest.raises(CompositionDirectoryRefused):
        require_owned_staging(staging, expected_parent=tmp_path, expected_name="staging")


def test_require_owned_staging_refuses_foreign_audio_entry(tmp_path) -> None:
    """Require owned staging refuses foreign audio entry."""
    staging = tmp_path / "staging"
    audio_dir = staging / "audio"
    audio_dir.mkdir(parents=True)
    (audio_dir / "stray.wav").write_bytes(b"\x00")
    with pytest.raises(CompositionDirectoryRefused):
        require_owned_staging(staging, expected_parent=tmp_path, expected_name="staging")


def test_require_owned_staging_refuses_missing_directory(tmp_path) -> None:
    """Require owned staging refuses missing directory."""
    missing = tmp_path / "gone"
    with pytest.raises(CompositionDirectoryRefused):
        require_owned_staging(missing, expected_parent=tmp_path, expected_name="gone")


def test_require_owned_staging_refuses_symlink_expected_parent(tmp_path) -> None:
    """Require owned staging refuses symlink expected parent."""
    real_parent = tmp_path / "real_parent"
    real_parent.mkdir()
    staging = real_parent / "staging"
    staging.mkdir()
    link_parent = tmp_path / "link_parent"
    try:
        link_parent.symlink_to(real_parent, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform/account")
    with pytest.raises(CompositionDirectoryRefused):
        require_owned_staging(
            real_parent / "staging", expected_parent=link_parent, expected_name="staging"
        )


def test_require_owned_staging_refuses_junction_expected_parent(tmp_path) -> None:
    """Require owned staging refuses junction expected parent."""
    real_parent = tmp_path / "real_parent2"
    real_parent.mkdir()
    staging = real_parent / "staging"
    staging.mkdir()
    link_parent = tmp_path / "link_parent2"
    if not _make_junction(link_parent, real_parent):
        pytest.skip("junction creation not available on this platform")
    with pytest.raises(CompositionDirectoryRefused):
        require_owned_staging(
            real_parent / "staging", expected_parent=link_parent, expected_name="staging"
        )


def test_require_owned_staging_refuses_symlink_staging_dir(tmp_path) -> None:
    """Require owned staging refuses symlink staging dir."""
    real = tmp_path / "real_staging"
    real.mkdir()
    link = tmp_path / "link_staging"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform/account")
    with pytest.raises(CompositionDirectoryRefused):
        require_owned_staging(link, expected_parent=tmp_path, expected_name="link_staging")


# ---- discard_owned_staging


def test_discard_owned_staging_no_op_when_absent(tmp_path) -> None:
    """Discard owned staging no op when absent."""
    discard_owned_staging(tmp_path / "gone", expected_parent=tmp_path, expected_name="gone")


def test_discard_owned_staging_removes_owned_tree(tmp_path) -> None:
    """Discard owned staging removes owned tree."""
    staging = tmp_path / "owned.partial"
    (staging / "audio").mkdir(parents=True)
    discard_owned_staging(staging, expected_parent=tmp_path, expected_name="owned.partial")
    assert not staging.exists()


def test_discard_owned_staging_refuses_foreign_tree_without_deleting(tmp_path) -> None:
    """Discard owned staging refuses foreign tree without deleting."""
    staging = tmp_path / "foreign.partial"
    staging.mkdir()
    (staging / "not_owned.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(CompositionDirectoryRefused):
        discard_owned_staging(staging, expected_parent=tmp_path, expected_name="foreign.partial")
    assert staging.exists()
    assert (staging / "not_owned.txt").is_file()


def test_discard_owned_staging_refuses_indirect_parent_and_deletes_nothing(tmp_path) -> None:
    """Discard owned staging refuses indirect parent and deletes nothing."""
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    target = real_parent / "staging.partial"
    target.mkdir()
    (target / "marker.txt").write_text("keep", encoding="utf-8")
    link_parent = tmp_path / "link"
    try:
        link_parent.symlink_to(real_parent, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform/account")
    # Point at a name that does NOT exist under the indirect parent, so an
    # inherited-only check (via require_owned_staging) would short-circuit
    # cleanly on `not staging_dir.exists()` and never refuse -- proving the
    # guard must run before that existence check, not only inside the
    # delegated call.
    absent_under_link = link_parent / "nonexistent.partial"
    with pytest.raises(CompositionDirectoryRefused):
        discard_owned_staging(
            absent_under_link, expected_parent=link_parent, expected_name="nonexistent.partial"
        )
    assert target.exists()
    assert (target / "marker.txt").is_file()


def test_discard_owned_staging_refuses_dangling_staging_symlink(tmp_path) -> None:
    """A dangling staging symlink refuses, rather than being treated as absent.

    ``Path.exists()`` follows a symlink and reports based on the *target*,
    so a dangling symlink (target absent) would make ``exists()`` return
    ``False`` -- proving the indirection check must run before that
    short-circuit, not only inside the delegated ``require_owned_staging``
    call, which this dangling case would never even reach.
    """
    link = tmp_path / "dangling.partial"
    nowhere = tmp_path / "does_not_exist_target"
    try:
        link.symlink_to(nowhere)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform/account")
    with pytest.raises(CompositionDirectoryRefused):
        discard_owned_staging(link, expected_parent=tmp_path, expected_name="dangling.partial")
    # The dangling link itself is untouched -- nothing was deleted through it.
    assert link.is_symlink()


def test_discard_owned_staging_refuses_symlink_to_a_live_populated_directory(tmp_path) -> None:
    """A staging symlink to a real, populated directory refuses without traversal or deletion."""
    real = tmp_path / "real_owned.partial"
    (real / "audio").mkdir(parents=True)
    (real / "marker.txt").write_text("keep", encoding="utf-8")
    link = tmp_path / "link_owned.partial"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform/account")
    with pytest.raises(CompositionDirectoryRefused):
        discard_owned_staging(link, expected_parent=tmp_path, expected_name="link_owned.partial")
    assert link.is_symlink()
    assert real.exists()
    assert (real / "marker.txt").is_file()


def test_discard_owned_staging_refuses_junction_staging_dir(tmp_path) -> None:
    """A staging junction refuses without traversal or deletion (Windows junction coverage)."""
    real = tmp_path / "real_junction_owned.partial"
    (real / "audio").mkdir(parents=True)
    link = tmp_path / "link_junction_owned.partial"
    if not _make_junction(link, real):
        pytest.skip("junction creation not available on this platform")
    with pytest.raises(CompositionDirectoryRefused):
        discard_owned_staging(
            link, expected_parent=tmp_path, expected_name="link_junction_owned.partial"
        )
    assert real.exists()


# ---- write_atomically / fsync_directory


def test_write_atomically_writes_exact_bytes(tmp_path) -> None:
    """Write atomically writes exact bytes."""
    target = tmp_path / "doc.json"
    write_atomically(target, b"hello\n")
    assert target.read_bytes() == b"hello\n"
    assert not (tmp_path / "doc.json.writing").exists()


def test_write_atomically_overwrites_cleanly(tmp_path) -> None:
    """Write atomically overwrites cleanly."""
    target = tmp_path / "doc.json"
    write_atomically(target, b"first\n")
    write_atomically(target, b"second\n")
    assert target.read_bytes() == b"second\n"


def test_fsync_directory_best_effort_on_missing(tmp_path) -> None:
    # Must not raise even when the path does not exist.
    """Fsync directory best effort on missing."""
    fsync_directory(tmp_path / "does_not_exist")


def test_fsync_directory_succeeds_on_real_directory(tmp_path) -> None:
    """Fsync directory succeeds on real directory."""
    fsync_directory(tmp_path)


# ---- publish_owned_staging


def test_publish_owned_staging_happy_path(tmp_path) -> None:
    """Publish owned staging happy path."""
    staging = tmp_path / "id.partial"
    (staging / "audio").mkdir(parents=True)
    final = tmp_path / "id"
    publish_owned_staging(
        staging,
        final,
        expected_parent=tmp_path,
        expected_staging_name="id.partial",
        expected_final_name="id",
    )
    assert final.is_dir()
    assert not staging.exists()


def test_publish_owned_staging_refuses_wrong_staging_name(tmp_path) -> None:
    """Publish owned staging refuses wrong staging name."""
    staging = tmp_path / "id.partial"
    staging.mkdir()
    final = tmp_path / "id"
    with pytest.raises(CompositionDirectoryRefused):
        publish_owned_staging(
            staging,
            final,
            expected_parent=tmp_path,
            expected_staging_name="wrong.partial",
            expected_final_name="id",
        )


def test_publish_owned_staging_refuses_wrong_final_name(tmp_path) -> None:
    """Publish owned staging refuses wrong final name."""
    staging = tmp_path / "id.partial"
    staging.mkdir()
    final = tmp_path / "id"
    with pytest.raises(CompositionDirectoryRefused):
        publish_owned_staging(
            staging,
            final,
            expected_parent=tmp_path,
            expected_staging_name="id.partial",
            expected_final_name="wrong",
        )


def test_publish_owned_staging_refuses_wrong_staging_parent(tmp_path) -> None:
    """Publish owned staging refuses wrong staging parent."""
    staging = tmp_path / "id.partial"
    staging.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    final = other / "id"
    with pytest.raises(CompositionDirectoryRefused):
        publish_owned_staging(
            staging,
            final,
            expected_parent=other,
            expected_staging_name="id.partial",
            expected_final_name="id",
        )


def test_publish_owned_staging_refuses_wrong_final_parent(tmp_path) -> None:
    """Publish owned staging refuses wrong final parent."""
    staging = tmp_path / "id.partial"
    staging.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    final = other / "id"
    with pytest.raises(CompositionDirectoryRefused):
        publish_owned_staging(
            staging,
            final,
            expected_parent=tmp_path,
            expected_staging_name="id.partial",
            expected_final_name="id",
        )


def test_publish_owned_staging_refuses_symlink_staging(tmp_path) -> None:
    """Publish owned staging refuses symlink staging."""
    real = tmp_path / "real.partial"
    real.mkdir()
    link = tmp_path / "id.partial"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform/account")
    final = tmp_path / "id"
    with pytest.raises(CompositionDirectoryRefused):
        publish_owned_staging(
            link,
            final,
            expected_parent=tmp_path,
            expected_staging_name="id.partial",
            expected_final_name="id",
        )


def test_publish_owned_staging_refuses_existing_final_path(tmp_path) -> None:
    """Publish owned staging refuses existing final path."""
    staging = tmp_path / "id.partial"
    staging.mkdir()
    final = tmp_path / "id"
    final.mkdir()
    with pytest.raises(CompositionDirectoryRefused):
        publish_owned_staging(
            staging,
            final,
            expected_parent=tmp_path,
            expected_staging_name="id.partial",
            expected_final_name="id",
        )
    assert staging.exists()  # never deleted


def test_publish_owned_staging_refuses_dangling_symlink_final(tmp_path) -> None:
    """Publish owned staging refuses dangling symlink final."""
    staging = tmp_path / "id.partial"
    staging.mkdir()
    final = tmp_path / "id"
    nowhere = tmp_path / "does_not_exist_target"
    try:
        final.symlink_to(nowhere)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform/account")
    with pytest.raises(CompositionDirectoryRefused):
        publish_owned_staging(
            staging,
            final,
            expected_parent=tmp_path,
            expected_staging_name="id.partial",
            expected_final_name="id",
        )


def test_publish_owned_staging_refuses_indirect_expected_parent(tmp_path) -> None:
    """Publish owned staging refuses indirect expected parent."""
    real_parent = tmp_path / "real3"
    real_parent.mkdir()
    staging = real_parent / "id.partial"
    staging.mkdir()
    final = real_parent / "id"
    link_parent = tmp_path / "link3"
    try:
        link_parent.symlink_to(real_parent, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform/account")
    with pytest.raises(CompositionDirectoryRefused):
        publish_owned_staging(
            real_parent / "id.partial",
            real_parent / "id",
            expected_parent=link_parent,
            expected_staging_name="id.partial",
            expected_final_name="id",
        )
    assert staging.exists()
    assert not final.exists()


def test_publish_owned_staging_terminal_publication_performs_no_overwrite(tmp_path) -> None:
    """A first publish succeeds; nothing about the API accepts overwriting that result."""
    staging = tmp_path / "id.partial"
    (staging / "audio").mkdir(parents=True)
    final = tmp_path / "id"
    publish_owned_staging(
        staging,
        final,
        expected_parent=tmp_path,
        expected_staging_name="id.partial",
        expected_final_name="id",
    )
    assert final.is_dir()
    # A second staging tree for the same final name is refused outright,
    # never merged or overwritten.
    staging2 = tmp_path / "id.partial"
    (staging2 / "audio").mkdir(parents=True)
    with pytest.raises(CompositionDirectoryRefused):
        publish_owned_staging(
            staging2,
            final,
            expected_parent=tmp_path,
            expected_staging_name="id.partial",
            expected_final_name="id",
        )
