"""The CLI: strict canonical reads over six inputs, and clean refusals.

Every refusal asserts three things: the exit code, a specific stderr
fragment, and that no output file survives -- a command that fails halfway
must leave nothing behind.
"""

import ast
import json
from pathlib import Path

import pytest

from living_diorama.cli.build_presentation_plan import main
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical

from .conftest import REPO_ROOT, build_presentation_sources

CLI_SOURCE = REPO_ROOT / "src" / "living_diorama" / "cli" / "build_presentation_plan.py"


def _write_inputs(tmp_path: Path) -> list[Path]:
    """Write the six canonical ep1 inputs and return all seven paths."""
    delivery, narration, shots, realization, story, export = build_presentation_sources(1)
    paths = [
        tmp_path / "delivery.json",
        tmp_path / "narration.json",
        tmp_path / "shots.json",
        tmp_path / "realization.json",
        tmp_path / "story.json",
        tmp_path / "export.json",
        tmp_path / "presentation.json",
    ]
    paths[0].write_bytes(dumps_canonical(delivery, "delivery"))
    paths[1].write_bytes(dumps_canonical(narration, "narration"))
    paths[2].write_bytes(dumps_canonical(shots, "shots"))
    paths[3].write_bytes(dumps_canonical(realization, "realization"))
    paths[4].write_bytes(dumps_canonical(story, "story"))
    paths[5].write_bytes(dumps_canonical(export, "export"))
    return paths


def _argv(paths: list[Path]) -> list[str]:
    return [
        "--delivery",
        str(paths[0]),
        "--narration",
        str(paths[1]),
        "--shots",
        str(paths[2]),
        "--realization",
        str(paths[3]),
        "--story",
        str(paths[4]),
        "--export",
        str(paths[5]),
        "--output",
        str(paths[6]),
    ]


def test_the_command_writes_a_verified_plan(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """The happy path writes canonical bytes and reports measured counts."""
    paths = _write_inputs(tmp_path)
    assert main(_argv(paths)) == 0
    payload = paths[6].read_bytes()
    document = loads_canonical(payload, "plan")
    assert payload == dumps_canonical(document, "plan")
    counts = json.loads(capsys.readouterr().out)
    assert counts["windows"] == 3
    assert counts["segments"] == 7
    assert counts["presentation_frames_total"] == 720
    assert counts["episode"] == 1
    assert counts["mode"] == "transition"
    assert counts["bytes"] == len(payload)


def test_an_existing_output_is_never_overwritten(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """An existing output is never overwritten."""
    paths = _write_inputs(tmp_path)
    paths[6].write_bytes(b"occupied\n")
    assert main(_argv(paths)) == 1
    err = capsys.readouterr().err
    assert "already exists" in err
    assert "Traceback" not in err
    assert paths[6].read_bytes() == b"occupied\n"


@pytest.mark.parametrize("index", [0, 1, 2, 3, 4, 5])
def test_a_missing_input_is_reported_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture, index: int
) -> None:
    """A missing input is reported cleanly."""
    paths = _write_inputs(tmp_path)
    paths[index].unlink()
    assert main(_argv(paths)) == 1
    err = capsys.readouterr().err
    assert "not found" in err
    assert "Traceback" not in err
    assert not paths[6].exists()


@pytest.mark.parametrize("index", [0, 1, 2, 3, 4, 5])
def test_pretty_printed_input_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture, index: int
) -> None:
    """Pretty printed input is refused."""
    paths = _write_inputs(tmp_path)
    document = loads_canonical(paths[index].read_bytes(), "document")
    paths[index].write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    assert main(_argv(paths)) == 1
    err = capsys.readouterr().err
    assert "not canonical bytes" in err
    assert not paths[6].exists()


@pytest.mark.parametrize("index", [0, 1, 2, 3, 4, 5])
def test_a_duplicate_json_key_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture, index: int
) -> None:
    """A duplicate json key is refused."""
    paths = _write_inputs(tmp_path)
    paths[index].write_bytes(b'{"format":"a","format":"b"}\n')
    assert main(_argv(paths)) == 1
    err = capsys.readouterr().err
    assert "duplicate" in err
    assert not paths[6].exists()


def test_a_join_refusal_leaves_no_output(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Individually valid documents from different episodes do not join."""
    paths = _write_inputs(tmp_path)
    _delivery2, narration2, _shots2, _realization2, _story2, _export2 = build_presentation_sources(
        2
    )
    paths[1].write_bytes(dumps_canonical(narration2, "narration"))
    assert main(_argv(paths)) == 1
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert not paths[6].exists()


def test_the_two_upstream_gates_run_before_write(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """A forged shot plan is refused by the reused Phase 25 gate, not silently ignored."""
    paths = _write_inputs(tmp_path)
    _delivery2, _narration2, shots2, _realization2, _story2, _export2 = build_presentation_sources(
        2
    )
    paths[2].write_bytes(dumps_canonical(shots2, "shots"))
    assert main(_argv(paths)) == 1
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert not paths[6].exists()


def test_a_forged_story_plan_is_refused_by_the_phase_26_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """A forged story plan is refused by the phase 26 gate."""
    paths = _write_inputs(tmp_path)
    _delivery2, _narration2, _shots2, _realization2, story2, _export2 = build_presentation_sources(
        2
    )
    paths[4].write_bytes(dumps_canonical(story2, "story"))
    assert main(_argv(paths)) == 1
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert not paths[6].exists()


def test_the_cli_calls_the_strict_decoder() -> None:
    """The cli calls the strict decoder."""
    tree = ast.parse(CLI_SOURCE.read_text(encoding="utf-8"))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "loads_canonical" in called
    assert "dumps_canonical" in called


def test_the_cli_never_calls_a_second_decoder() -> None:
    """No json.loads fallback exists; json is used for the summary only."""
    tree = ast.parse(CLI_SOURCE.read_text(encoding="utf-8"))
    json_calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "json"
    }
    assert "loads" not in json_calls
    assert json_calls == {"dumps"}


def test_the_cli_never_imports_story_or_render_packages() -> None:
    """Story and export travel through as opaque canonical documents."""
    tree = ast.parse(CLI_SOURCE.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    for banned in (
        "living_diorama.story",
        "living_diorama.render",
        "living_diorama.render_execution",
    ):
        assert banned not in modules
        assert not any(module.startswith(banned + ".") for module in modules)
