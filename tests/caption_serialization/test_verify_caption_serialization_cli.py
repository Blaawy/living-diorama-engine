"""``python -m living_diorama.cli.verify_caption_serialization`` -- the auditing CLI."""

import inspect
from pathlib import Path

import pytest

from living_diorama.cli import verify_caption_serialization as cli


def test_exit_zero_on_a_clean_captions_directory(
    captions_dir_ep1_copy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit zero on a clean captions directory."""
    exit_code = cli.main(["--caption-dir", str(captions_dir_ep1_copy)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "passed" in captured.out
    assert captured.err == ""


def test_exit_one_with_per_problem_lines(
    captions_dir_ep1_copy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit one with per problem lines when a sidecar byte is tampered."""
    srt_files = sorted(captions_dir_ep1_copy.glob("*.srt"))
    assert len(srt_files) == 1
    tampered = srt_files[0].read_bytes() + b"X"
    srt_files[0].write_bytes(tampered)
    exit_code = cli.main(["--caption-dir", str(captions_dir_ep1_copy)])
    assert exit_code == 1
    captured = capsys.readouterr()
    problem_lines = [line for line in captured.err.splitlines() if line.startswith("  PROBLEM ")]
    assert len(problem_lines) >= 1
    assert "failed:" in captured.err


def test_a_missing_directory_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A missing directory is refused with 'not a directory'."""
    missing = tmp_path / "does_not_exist"
    exit_code = cli.main(["--caption-dir", str(missing)])
    assert exit_code == 1
    assert "not a directory" in capsys.readouterr().err


def test_a_plain_file_refused_as_a_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A plain file in place of a directory is refused."""
    plain = tmp_path / "just_a_file.txt"
    plain.write_bytes(b"x")
    exit_code = cli.main(["--caption-dir", str(plain)])
    assert exit_code == 1
    assert "not a directory" in capsys.readouterr().err


def test_indirection_refused_before_any_query(
    tmp_path: Path,
    captions_dir_ep1_copy: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A symlinked captions directory is refused with 'symlink or junction'."""
    link = tmp_path / "captions_link"
    try:
        link.symlink_to(captions_dir_ep1_copy, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    exit_code = cli.main(["--caption-dir", str(link)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "symlink or junction" in captured.err


def test_a_missing_required_flag_is_an_argparse_error() -> None:
    """A missing required flag is an argparse error, exit code 2."""
    with pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == 2


def test_the_cli_exposes_only_caption_dir() -> None:
    """The CLI exposes exactly one flag: --caption-dir."""
    source = inspect.getsource(cli.main)
    assert source.count("add_argument(") == 1
    assert '"--caption-dir"' in source


def test_an_upstream_document_flag_is_rejected() -> None:
    """An upstream document flag is not a valid argument to the verify CLI.

    The audit is self-contained by design: it accepts exactly one directory
    and no upstream document path -- so ``--caption-plan`` is an argparse
    error, never a silently ignored extra input.
    """
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--caption-dir", "x", "--caption-plan", "y"])
    assert excinfo.value.code == 2
