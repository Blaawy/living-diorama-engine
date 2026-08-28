"""``python -m living_diorama.cli.verify_media_assembly`` -- the auditing CLI."""

import os
from pathlib import Path

import pytest

from living_diorama.cli import verify_media_assembly as cli
from living_diorama.media_assembly.media_assembly_spec import RENDER_MANIFEST_COPY_FILENAME
from living_diorama.media_assembly.media_assembly_staging import _regular_file_link_count


def _can_hardlink(probe_dir: Path) -> bool:
    probe_dir.mkdir(parents=True, exist_ok=True)
    source = probe_dir / "_probe_source"
    source.write_bytes(b"x")
    try:
        os.link(source, probe_dir / "_probe_link")
    except OSError:
        return False
    return True


def test_exit_zero_on_a_clean_assembly(
    assembly_dir_ep1: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit zero on a clean assembly."""
    exit_code = cli.main(["--assembly-dir", str(assembly_dir_ep1)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "passed" in captured.out
    assert captured.err == ""


def test_exit_one_with_per_problem_lines(
    assembly_dir_ep1_copy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit one with per problem lines."""
    (assembly_dir_ep1_copy / RENDER_MANIFEST_COPY_FILENAME).unlink()
    exit_code = cli.main(["--assembly-dir", str(assembly_dir_ep1_copy)])
    assert exit_code == 1
    captured = capsys.readouterr()
    problem_lines = [line for line in captured.err.splitlines() if line.startswith("  PROBLEM ")]
    assert len(problem_lines) >= 1
    assert "failed" in captured.err


def test_indirection_refused_before_any_query(tmp_path: Path, assembly_dir_ep1: Path) -> None:
    """Indirection refused before any query."""
    link = tmp_path / "assembly_link"
    try:
        link.symlink_to(assembly_dir_ep1, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    exit_code = cli.main(["--assembly-dir", str(link)])
    assert exit_code == 1


def test_non_directory_refused(tmp_path: Path) -> None:
    """Non directory refused."""
    not_a_directory = tmp_path / "just_a_file.txt"
    not_a_directory.write_bytes(b"x")
    exit_code = cli.main(["--assembly-dir", str(not_a_directory)])
    assert exit_code == 1


def test_a_missing_directory_refused(tmp_path: Path) -> None:
    """A missing directory refused."""
    exit_code = cli.main(["--assembly-dir", str(tmp_path / "does_not_exist")])
    assert exit_code == 1


def test_succeeds_with_every_upstream_path_deleted(assembly_dir_ep1: Path, tmp_path: Path) -> None:
    """Succeeds with every upstream path deleted.

    No upstream render/composition/presentation/delivery/shot path is passed at all --
    the CLI's own signature proves it never needs one.
    """
    exit_code = cli.main(["--assembly-dir", str(assembly_dir_ep1)])
    assert exit_code == 0


def test_the_cli_exposes_only_assembly_dir() -> None:
    """The CLI exposes only assembly dir."""
    import inspect

    source = inspect.getsource(cli.main)
    flags = [line.strip() for line in source.splitlines() if "add_argument(" in line]
    assert len(flags) == 1
    assert '"--assembly-dir"' in flags[0]


# ---------------------------------------------------------------------------
# Correction K -- a hardlinked assembly exits 1 and names the file
# ---------------------------------------------------------------------------


def test_a_hardlinked_assembly_exits_one_and_names_the_file(
    assembly_dir_ep1_copy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A hardlinked assembly exits one and names the file."""
    if not _can_hardlink(assembly_dir_ep1_copy.parent / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    document = assembly_dir_ep1_copy / RENDER_MANIFEST_COPY_FILENAME
    outside = assembly_dir_ep1_copy.parent / "outside_render_manifest.json"
    outside.write_bytes(document.read_bytes())
    document.unlink()
    os.link(outside, document)
    assert _regular_file_link_count(document) == 2

    exit_code = cli.main(["--assembly-dir", str(assembly_dir_ep1_copy)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert str(document) in captured.err
