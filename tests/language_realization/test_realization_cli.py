"""The CLI: strict canonical reads over three inputs, and clean refusals.

Every refusal asserts three things: the exit code, a specific stderr
fragment, and that no output file survives -- a command that fails halfway
must leave nothing behind.
"""

import ast
import json
from pathlib import Path

import pytest

from living_diorama.cli.build_language_realization_plan import main
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical

from .conftest import REPO_ROOT, build_realization_sources

CLI_SOURCE = REPO_ROOT / "src" / "living_diorama" / "cli" / "build_language_realization_plan.py"


def _write_inputs(tmp_path: Path) -> list[Path]:
    """Write the three canonical ep1 inputs and return all four paths."""
    narration, story, export = build_realization_sources(1)
    paths = [
        tmp_path / "narration.json",
        tmp_path / "story.json",
        tmp_path / "export.json",
        tmp_path / "realization.json",
    ]
    paths[0].write_bytes(dumps_canonical(narration, "narration"))
    paths[1].write_bytes(dumps_canonical(story, "story"))
    paths[2].write_bytes(dumps_canonical(export, "export"))
    return paths


def _argv(paths: list[Path]) -> list[str]:
    return [
        "--narration",
        str(paths[0]),
        "--story",
        str(paths[1]),
        "--export",
        str(paths[2]),
        "--output",
        str(paths[3]),
    ]


def test_the_command_writes_a_verified_plan(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """The happy path writes canonical bytes and reports measured counts."""
    paths = _write_inputs(tmp_path)
    assert main(_argv(paths)) == 0
    payload = paths[3].read_bytes()
    document = loads_canonical(payload, "plan")
    assert payload == dumps_canonical(document, "plan")
    counts = json.loads(capsys.readouterr().out)
    assert counts["realizations"] == 3
    assert counts["fact_backed"] == 1
    assert counts["template_backed"] == 2
    assert counts["episode"] == 1
    assert counts["mode"] == "transition"
    assert counts["bytes"] == len(payload)


def test_an_existing_output_is_never_overwritten(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Plans are never overwritten."""
    paths = _write_inputs(tmp_path)
    paths[3].write_bytes(b"occupied\n")
    assert main(_argv(paths)) == 1
    err = capsys.readouterr().err
    assert "already exists" in err
    assert "Traceback" not in err
    assert paths[3].read_bytes() == b"occupied\n"


@pytest.mark.parametrize("index", [0, 1, 2])
def test_a_missing_input_is_reported_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture, index: int
) -> None:
    """An absent file at any position refuses with a message, not a traceback."""
    paths = _write_inputs(tmp_path)
    paths[index].unlink()
    assert main(_argv(paths)) == 1
    err = capsys.readouterr().err
    assert "not found" in err
    assert "Traceback" not in err
    assert not paths[3].exists()


@pytest.mark.parametrize("index", [0, 1, 2])
def test_pretty_printed_input_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture, index: int
) -> None:
    """The same document in non-canonical bytes is refused at any position."""
    paths = _write_inputs(tmp_path)
    document = loads_canonical(paths[index].read_bytes(), "document")
    paths[index].write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    assert main(_argv(paths)) == 1
    err = capsys.readouterr().err
    assert "not canonical bytes" in err
    assert not paths[3].exists()


@pytest.mark.parametrize("index", [0, 1, 2])
def test_a_duplicate_json_key_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture, index: int
) -> None:
    """A duplicate object key is refused by the strict decoder at any position."""
    paths = _write_inputs(tmp_path)
    paths[index].write_bytes(b'{"format":"a","format":"b"}\n')
    assert main(_argv(paths)) == 1
    err = capsys.readouterr().err
    assert "duplicate" in err
    assert not paths[3].exists()


@pytest.mark.parametrize("index, literal", [(0, b"NaN"), (1, b"Infinity"), (2, b"-Infinity")])
def test_a_non_standard_constant_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture, index: int, literal: bytes
) -> None:
    """The non-standard JSON constants are refused at every position."""
    paths = _write_inputs(tmp_path)
    paths[index].write_bytes(b'{"schema_version":' + literal + b"}\n")
    assert main(_argv(paths)) == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "non-standard JSON constant" in err
    assert not paths[3].exists()


@pytest.mark.parametrize("index", [0, 1, 2])
def test_malformed_utf8_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture, index: int
) -> None:
    """Bytes that are not UTF-8 are refused at any position."""
    paths = _write_inputs(tmp_path)
    paths[index].write_bytes(b'{"format":"\xff\xfe"}\n')
    assert main(_argv(paths)) == 1
    err = capsys.readouterr().err
    assert "not valid UTF-8" in err
    assert not paths[3].exists()


@pytest.mark.parametrize("index", [0, 1, 2])
def test_a_truncated_real_file_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture, index: int
) -> None:
    """A genuine canonical file cut mid-object is not valid JSON."""
    paths = _write_inputs(tmp_path)
    raw = paths[index].read_bytes()
    paths[index].write_bytes(raw[: len(raw) // 2])
    assert main(_argv(paths)) == 1
    err = capsys.readouterr().err
    assert "not valid JSON" in err
    assert not paths[3].exists()


def test_swapped_inputs_are_refused(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Each document validates under its own contract, so a swap dies at once.

    The story plan handed to the narration position fails the narration
    plan's own exact-key envelope before any format comparison is reached --
    a different document is a different shape, not merely a different tag.
    """
    paths = _write_inputs(tmp_path)
    argv = [
        "--narration",
        str(paths[1]),
        "--story",
        str(paths[0]),
        "--export",
        str(paths[2]),
        "--output",
        str(paths[3]),
    ]
    assert main(argv) == 1
    err = capsys.readouterr().err
    assert "missing required keys" in err
    assert "Traceback" not in err
    assert not paths[3].exists()


def test_a_join_refusal_leaves_no_output(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Individually valid documents from different episodes do not join."""
    paths = _write_inputs(tmp_path)
    _narration2, story2, _export2 = build_realization_sources(2)
    paths[1].write_bytes(dumps_canonical(story2, "story"))
    assert main(_argv(paths)) == 1
    err = capsys.readouterr().err
    assert "not about the same story" in err
    assert not paths[3].exists()


def test_the_cli_calls_the_strict_decoder() -> None:
    """The command routes every read through loads_canonical."""
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
