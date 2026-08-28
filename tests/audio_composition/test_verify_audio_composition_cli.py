"""The verify_audio_composition CLI: self-contained, no --voice-dir, exit codes."""

import shutil

import pytest

from living_diorama.cli import verify_audio_composition


def test_cli_passes_on_clean_composition(composition_dir_ep1, capsys) -> None:
    """CLI passes on clean composition."""
    exit_code = verify_audio_composition.main(["--composition-dir", str(composition_dir_ep1)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "passed" in captured.out


def test_cli_fails_on_missing_directory(tmp_path) -> None:
    """CLI fails on missing directory."""
    exit_code = verify_audio_composition.main(["--composition-dir", str(tmp_path / "nowhere")])
    assert exit_code == 1


def test_cli_fails_on_tampered_manifest(composition_dir_ep1) -> None:
    """CLI fails on tampered manifest."""
    manifest_path = composition_dir_ep1 / "episode_audio_composition_manifest.json"
    manifest_path.unlink()
    exit_code = verify_audio_composition.main(["--composition-dir", str(composition_dir_ep1)])
    assert exit_code == 1


def test_cli_succeeds_after_original_voice_directory_deleted(
    composition_dir_ep1, voice_directory_ep1, capsys
) -> None:
    """CLI succeeds after original voice directory deleted."""
    shutil.rmtree(voice_directory_ep1)
    exit_code = verify_audio_composition.main(["--composition-dir", str(composition_dir_ep1)])
    assert exit_code == 0


def test_cli_prints_problems_to_stderr_on_failure(composition_dir_ep1, capsys) -> None:
    """CLI prints problems to stderr on failure."""
    (composition_dir_ep1 / "audio" / "episode_audio.wav").unlink()
    exit_code = verify_audio_composition.main(["--composition-dir", str(composition_dir_ep1)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "PROBLEM" in captured.err


def test_cli_has_no_voice_dir_flag() -> None:
    """CLI has no voice dir flag."""
    exit_code = None
    try:
        verify_audio_composition.main(["--voice-dir", "somewhere"])
    except SystemExit as error:
        exit_code = error.code
    assert exit_code not in (0,)


def test_cli_refuses_symlink_composition_dir_before_is_dir_traversal(
    tmp_path, composition_dir_ep1, capsys
) -> None:
    """A symlinked ``--composition-dir`` exits 1 before ``is_dir()`` ever follows it.

    The link's target would otherwise audit perfectly clean -- proving the
    exit-1 is genuinely about the indirection, not about the composition
    behind it being untrustworthy.
    """
    link = tmp_path / "link_composition"
    try:
        link.symlink_to(composition_dir_ep1, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform/account")
    exit_code = verify_audio_composition.main(["--composition-dir", str(link)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "symlink or junction" in captured.err
    assert "PROBLEM" not in captured.err  # refused before the audit ever ran


def test_cli_refuses_junction_composition_dir(tmp_path, composition_dir_ep1) -> None:
    """A junctioned ``--composition-dir`` exits 1 (Windows junction coverage)."""
    import subprocess

    link = tmp_path / "junction_composition"
    try:
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(composition_dir_ep1)],
            capture_output=True,
            check=False,
        )
    except OSError:
        pytest.skip("junction creation not available on this platform")
    if result.returncode != 0:
        pytest.skip("junction creation not available on this platform")
    exit_code = verify_audio_composition.main(["--composition-dir", str(link)])
    assert exit_code == 1


def test_cli_reports_expected_audit_failure_as_exit_1_without_traceback(
    composition_dir_ep1, capsys, monkeypatch
) -> None:
    """An expected audit-level failure exits 1 with a diagnostic, not a traceback."""
    from living_diorama.audio_composition.audio_composition_spec import (
        AUDIO_COMPOSITION_MANIFEST_FILENAME,
    )

    (composition_dir_ep1 / AUDIO_COMPOSITION_MANIFEST_FILENAME).unlink()
    exit_code = verify_audio_composition.main(["--composition-dir", str(composition_dir_ep1)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "PROBLEM" in captured.err
