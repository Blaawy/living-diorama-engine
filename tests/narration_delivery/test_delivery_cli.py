"""The command is a thin shell, and every refusal comes from the contract.

What these tests care about is the boundary the CLI owns and the layer does
not: canonical bytes on the way in, no overwrite, no output file left behind
when a check fails, a clean message instead of a traceback, and an exit code a
gate can read. The structural tests at the end prove the command routes every
decode through the repository's one strict reader, so a regression back to a
second hand-rolled decoder fails even if every behavioural test still passes.
"""

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from living_diorama.cli import build_narration_delivery_plan
from living_diorama.narration_delivery import (
    build_episode_narration_delivery_plan_bytes,
    validate_narration_delivery_plan_against_sources,
)
from living_diorama.persistence.json_codec import dumps_canonical

from .conftest import build_delivery_sources

Sources = tuple[dict[str, Any], dict[str, Any]]

Inputs = tuple[Path, Path, Path]


def _write(path: Path, document: dict[str, Any], description: str) -> Path:
    """Write a document as canonical bytes and return its path."""
    path.write_bytes(dumps_canonical(document, description))
    return path


@pytest.fixture
def inputs(tmp_path: Path, sources_ep1: Sources) -> Inputs:
    """The canonical episode 0 -> 1 pair on disk, and an unused output path."""
    narration, shots = sources_ep1
    return (
        _write(tmp_path / "narration.json", narration, "episode narration plan"),
        _write(tmp_path / "shots.json", shots, "shot direction plan"),
        tmp_path / "delivery.json",
    )


def _argv(paths: Inputs) -> list[str]:
    """Return the command line for one input pair and output path."""
    narration, shots, output = paths
    return [
        "--narration",
        str(narration),
        "--shots",
        str(shots),
        "--output",
        str(output),
    ]


# ---- the happy path


def test_the_command_writes_a_verifiable_plan(
    inputs: Inputs, sources_ep1: Sources, capsys: Any
) -> None:
    """The file the command leaves behind passes the full source cross-check."""
    assert build_narration_delivery_plan.main(_argv(inputs)) == 0
    document = json.loads(inputs[2].read_text(encoding="utf-8"))
    assert validate_narration_delivery_plan_against_sources(document, *sources_ep1) is not None


def test_the_written_bytes_are_the_derivation(inputs: Inputs, sources_ep1: Sources) -> None:
    """What lands on disk is byte for byte what the planner derives."""
    build_narration_delivery_plan.main(_argv(inputs))
    assert inputs[2].read_bytes() == build_episode_narration_delivery_plan_bytes(*sources_ep1)


def test_the_written_bytes_are_canonical(inputs: Inputs) -> None:
    """One encoding, the one every downstream digest will assume."""
    build_narration_delivery_plan.main(_argv(inputs))
    raw = inputs[2].read_bytes()
    assert raw == dumps_canonical(json.loads(raw.decode("utf-8")), "narration delivery plan")


def test_the_summary_reports_what_was_scheduled(inputs: Inputs, capsys: Any) -> None:
    """The stdout summary is machine-readable and agrees with the file."""
    build_narration_delivery_plan.main(_argv(inputs))
    reported = json.loads(capsys.readouterr().out)
    assert reported["episode"] == 1
    assert reported["mode"] == "transition"
    assert reported["deliveries"] == 3
    assert reported["shot_anchored"] == 2
    assert reported["allocated_unshown"] == 1
    assert reported["bytes"] == len(inputs[2].read_bytes())


def test_the_command_creates_missing_parent_directories(inputs: Inputs) -> None:
    """A caller may name an output path whose directory does not exist yet."""
    narration, shots, output = inputs
    nested = output.parent / "a" / "b" / "delivery.json"
    assert build_narration_delivery_plan.main(_argv((narration, shots, nested))) == 0
    assert nested.is_file()


# ---- refusals


def test_an_existing_output_is_never_overwritten(inputs: Inputs, capsys: Any) -> None:
    """There is no overwrite option in V1, and the existing file is untouched."""
    inputs[2].write_bytes(b"existing\n")
    assert build_narration_delivery_plan.main(_argv(inputs)) == 1
    assert "already exists" in capsys.readouterr().err
    assert inputs[2].read_bytes() == b"existing\n"


@pytest.mark.parametrize("index", [0, 1])
def test_a_missing_input_is_reported_cleanly(inputs: Inputs, index: int, capsys: Any) -> None:
    """An absent input names itself, and no output is written."""
    paths = list(inputs)
    paths[index] = paths[index].parent / "absent.json"
    assert build_narration_delivery_plan.main(_argv((paths[0], paths[1], paths[2]))) == 1
    assert "not found" in capsys.readouterr().err
    assert not inputs[2].exists()


@pytest.mark.parametrize("index", [0, 1])
def test_noncanonical_bytes_are_refused(inputs: Inputs, index: int, capsys: Any) -> None:
    """A pretty-printed copy of a valid document is the same data, not the same file.

    The plan binds the digest of every document it read, so each input must be
    exactly what its writer emitted.
    """
    document = json.loads(inputs[index].read_text(encoding="utf-8"))
    inputs[index].write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    assert build_narration_delivery_plan.main(_argv(inputs)) == 1
    captured = capsys.readouterr()
    assert "not canonical bytes" in captured.err
    assert "Traceback" not in captured.err
    assert not inputs[2].exists()


@pytest.mark.parametrize("index", [0, 1])
def test_a_duplicate_json_key_is_refused(inputs: Inputs, index: int, capsys: Any) -> None:
    """Python's default decoder keeps the last occurrence; the strict one refuses.

    Exercised through ``main()`` on every input position, not by calling
    ``loads_canonical`` directly -- proving the CLI actually routes through it.
    """
    inputs[index].write_bytes(b'{"format":"a","format":"b"}\n')
    assert build_narration_delivery_plan.main(_argv(inputs)) == 1
    captured = capsys.readouterr()
    assert "duplicate JSON object key" in captured.err
    assert "Traceback" not in captured.err
    assert not inputs[2].exists()


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("literal", [b"NaN", b"Infinity", b"-Infinity", b"1e999"])
def test_a_non_finite_literal_is_refused(
    inputs: Inputs, index: int, literal: bytes, capsys: Any
) -> None:
    """The non-standard constants plain ``json.loads`` would accept are refused."""
    inputs[index].write_bytes(b'{"schema_version":' + literal + b"}\n")
    assert build_narration_delivery_plan.main(_argv(inputs)) == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("error:")
    assert "Traceback" not in captured.err
    assert not inputs[2].exists()


@pytest.mark.parametrize("index", [0, 1])
def test_malformed_utf8_is_refused(inputs: Inputs, index: int, capsys: Any) -> None:
    """Bytes that are not text are refused before they are parsed."""
    inputs[index].write_bytes(b'{"format":"\xff\xfe"}\n')
    assert build_narration_delivery_plan.main(_argv(inputs)) == 1
    captured = capsys.readouterr()
    assert "not valid UTF-8" in captured.err
    assert "Traceback" not in captured.err
    assert not inputs[2].exists()


@pytest.mark.parametrize("index", [0, 1])
def test_malformed_json_is_refused(inputs: Inputs, index: int, capsys: Any) -> None:
    """A truncated document reports cleanly, whichever input carries it."""
    inputs[index].write_bytes(b'{"format":')
    assert build_narration_delivery_plan.main(_argv(inputs)) == 1
    captured = capsys.readouterr()
    assert "not valid JSON" in captured.err
    assert "Traceback" not in captured.err
    assert not inputs[2].exists()


def test_a_mismatched_pair_is_refused(inputs: Inputs, tmp_path: Path, capsys: Any) -> None:
    """Episode 1's narration under episode 2's direction writes nothing."""
    _, wrong_shots = build_delivery_sources(2)
    wrong = _write(tmp_path / "wrong_shots.json", wrong_shots, "shot direction plan")
    assert build_narration_delivery_plan.main(_argv((inputs[0], wrong, inputs[2]))) == 1
    captured = capsys.readouterr()
    assert "not about the same directed episode" in captured.err
    assert "Traceback" not in captured.err
    assert not inputs[2].exists()


def test_a_swapped_pair_is_refused(inputs: Inputs, capsys: Any) -> None:
    """Handing the shot plan as the narration plan is a contract error, not a crash."""
    assert build_narration_delivery_plan.main(_argv((inputs[1], inputs[0], inputs[2]))) == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert not inputs[2].exists()


# ---- the decode path is the strict one, structurally


def _cli_tree() -> ast.Module:
    """Parse the command's source."""
    source = Path(build_narration_delivery_plan.__file__).read_text(encoding="utf-8")
    return ast.parse(source)


def test_the_cli_calls_the_strict_decoder() -> None:
    """Every decode routes through ``loads_canonical``."""
    calls = {
        node.func.id
        for node in ast.walk(_cli_tree())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "loads_canonical" in calls


def test_the_cli_never_calls_a_second_decoder() -> None:
    """``json`` is imported for the stdout summary only; nothing decodes with it."""
    calls = {
        f"{node.func.value.id}.{node.func.attr}"
        for node in ast.walk(_cli_tree())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    }
    assert "json.loads" not in calls
    assert "json.dumps" in calls
