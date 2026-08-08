"""Blender executable resolution for the Phase 15 local gate.

The gate must resolve Blender from portable, operator-controlled sources
only: the explicit ``--blender`` argument, the ``BLENDER_EXECUTABLE``
environment variable, or the system PATH -- in that order, refusing clearly
otherwise. A hard-coded machine path in the repository is a defect; the last
test pins that regression.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CHECKS_PATH = REPO_ROOT / "visual" / "blender" / "run_phase15_checks.py"


def load_checks_module():
    """Import the gate script from its file path, uncached."""
    spec = importlib.util.spec_from_file_location("phase15_checks_under_test", CHECKS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["phase15_checks_under_test"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules["phase15_checks_under_test"]
    return module


@pytest.fixture(name="checks")
def checks_fixture():
    """The gate module under test."""
    return load_checks_module()


def test_explicit_argument_wins(checks, tmp_path: Path) -> None:
    """An existing --blender path is returned as given, before any fallback."""
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"")
    resolved = checks.locate_blender(str(executable), environ={})
    assert resolved == executable


def test_explicit_argument_beats_environment(checks, tmp_path: Path) -> None:
    """--blender outranks BLENDER_EXECUTABLE when both are present."""
    from_flag = tmp_path / "flag" / "blender.exe"
    from_flag.parent.mkdir()
    from_flag.write_bytes(b"")
    from_env = tmp_path / "env" / "blender.exe"
    from_env.parent.mkdir()
    from_env.write_bytes(b"")
    resolved = checks.locate_blender(
        str(from_flag), environ={checks.BLENDER_EXECUTABLE_ENV: str(from_env)}
    )
    assert resolved == from_flag


def test_missing_explicit_argument_is_refused(checks, tmp_path: Path) -> None:
    """A --blender path that does not exist fails loudly, never falls back."""
    with pytest.raises(FileNotFoundError, match="--blender"):
        checks.locate_blender(str(tmp_path / "absent.exe"), environ={})


def test_environment_variable_is_second(checks, tmp_path: Path) -> None:
    """Without --blender, BLENDER_EXECUTABLE resolves the executable."""
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"")
    resolved = checks.locate_blender(None, environ={checks.BLENDER_EXECUTABLE_ENV: str(executable)})
    assert resolved == executable


def test_missing_environment_target_is_refused(checks, tmp_path: Path) -> None:
    """A BLENDER_EXECUTABLE pointing nowhere fails loudly, never falls back."""
    with pytest.raises(FileNotFoundError, match=checks.BLENDER_EXECUTABLE_ENV):
        checks.locate_blender(
            None, environ={checks.BLENDER_EXECUTABLE_ENV: str(tmp_path / "absent.exe")}
        )


def test_path_lookup_is_last(checks, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without --blender or the environment variable, PATH is consulted."""
    executable = tmp_path / "blender"
    executable.write_bytes(b"")
    monkeypatch.setattr(
        checks.shutil, "which", lambda name: str(executable) if name == "blender" else None
    )
    resolved = checks.locate_blender(None, environ={})
    assert resolved == executable


def test_no_source_at_all_is_refused(checks, monkeypatch: pytest.MonkeyPatch) -> None:
    """With no argument, no environment variable, and no PATH hit: refuse."""
    monkeypatch.setattr(checks.shutil, "which", lambda name: None)
    with pytest.raises(FileNotFoundError, match="no Blender executable found"):
        checks.locate_blender(None, environ={})


def test_no_machine_specific_path_in_gate_source() -> None:
    """The gate never hard-codes a user- or machine-specific Blender path.

    Candidate V1 shipped a fallback pointing into one developer's Desktop;
    this pins the removal. Any drive-letter or home-directory literal in the
    gate source is a regression.
    """
    source = CHECKS_PATH.read_text(encoding="utf-8")
    for marker in ("C:\\", "C:/", "Desktop", "Users\\", "Users/", "/home/"):
        assert marker not in source, f"machine-specific path marker {marker!r} in gate source"
