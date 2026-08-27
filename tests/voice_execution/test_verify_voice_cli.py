"""The verify_voice CLI: exit codes, stderr shape, and that nothing is written."""

from pathlib import Path

from living_diorama.cli.verify_voice import main
from living_diorama.voice_execution.voice_execution_spec import (
    SPEECH_DIRECTORY,
    VOICE_PLAN_FILENAME,
)


def test_the_cli_passes_a_truthful_directory(voice_directory_ep1: Path, capsys) -> None:
    """The CLI passes a truthful directory."""
    exit_code = main(["--voice-dir", str(voice_directory_ep1)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "voice audit passed" in out


def test_the_cli_fails_on_a_tampered_directory(voice_directory_ep1: Path, capsys) -> None:
    """The CLI fails on a tampered directory, printing problems to stderr."""
    (voice_directory_ep1 / "intruder.txt").write_bytes(b"x")
    exit_code = main(["--voice-dir", str(voice_directory_ep1)])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "PROBLEM" in err
    assert "voice audit failed" in err
    assert "Traceback" not in err


def test_the_cli_refuses_a_non_directory(tmp_path: Path, capsys) -> None:
    """The CLI refuses a path that is not a directory."""
    not_a_dir = tmp_path / "nope.json"
    not_a_dir.write_bytes(b"{}")
    exit_code = main(["--voice-dir", str(not_a_dir)])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "not a directory" in err


def test_nothing_is_written_by_the_audit(voice_directory_ep1: Path) -> None:
    """Nothing is written by the audit -- it is read-only."""
    before = {path: path.read_bytes() for path in voice_directory_ep1.rglob("*") if path.is_file()}
    main(["--voice-dir", str(voice_directory_ep1)])
    after = {path: path.read_bytes() for path in voice_directory_ep1.rglob("*") if path.is_file()}
    assert before == after


def test_a_surviving_partial_temp_is_reported(voice_directory_ep1: Path, capsys) -> None:
    """A surviving .writing temporary is reported as a problem, not silently accepted."""
    (voice_directory_ep1 / f"{VOICE_PLAN_FILENAME}.writing").write_bytes(b"{}")
    exit_code = main(["--voice-dir", str(voice_directory_ep1)])
    assert exit_code == 1


def test_missing_speech_directory_is_reported(voice_directory_ep1: Path, capsys) -> None:
    """A missing speech/ directory is reported."""
    import shutil

    shutil.rmtree(voice_directory_ep1 / SPEECH_DIRECTORY)
    exit_code = main(["--voice-dir", str(voice_directory_ep1)])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "missing from disk" in err or "is missing" in err
