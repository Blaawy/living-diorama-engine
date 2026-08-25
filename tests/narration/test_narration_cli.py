"""The command is a thin shell, and every refusal comes from the contract.

What these tests care about is the boundary the CLI owns and the layer does not:
canonical bytes on the way in, no overwrite, no output file left behind when a
check fails, a clean message instead of a traceback, and an exit code a gate can
read.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from living_diorama.cli import build_narration_plan
from living_diorama.narration import validate_narration_plan_against_sources
from living_diorama.persistence.json_codec import dumps_canonical

from .conftest import build_sources

Sources = tuple[dict[str, Any], dict[str, Any], dict[str, Any]]


def _write(path: Path, document: dict[str, Any], description: str) -> Path:
    """Write a document as canonical bytes and return its path."""
    path.write_bytes(dumps_canonical(document, description))
    return path


@pytest.fixture
def inputs(tmp_path: Path, sources_ep2: Sources) -> tuple[Path, Path, Path, Path]:
    """The canonical episode 1 -> 2 triple on disk, and an unused output path."""
    story, shots, export = sources_ep2
    return (
        _write(tmp_path / "story.json", story, "episode story plan"),
        _write(tmp_path / "shots.json", shots, "shot direction plan"),
        _write(tmp_path / "export.json", export, "render export"),
        tmp_path / "narration.json",
    )


def _argv(paths: tuple[Path, Path, Path, Path]) -> list[str]:
    """Return the command line for one input triple and output path."""
    story, shots, export, output = paths
    return [
        "--story",
        str(story),
        "--shots",
        str(shots),
        "--export",
        str(export),
        "--output",
        str(output),
    ]


# ---- the happy path


def test_the_command_writes_a_verifiable_plan(
    inputs: tuple[Path, Path, Path, Path], sources_ep2: Sources, capsys: Any
) -> None:
    """The file the command leaves behind passes the full source cross-check."""
    assert build_narration_plan.main(_argv(inputs)) == 0
    output = inputs[3]
    document = json.loads(output.read_text(encoding="utf-8"))
    assert validate_narration_plan_against_sources(document, *sources_ep2) is not None


def test_the_written_bytes_are_canonical(inputs: tuple[Path, Path, Path, Path]) -> None:
    """What lands on disk is the one encoding every downstream digest will assume."""
    build_narration_plan.main(_argv(inputs))
    raw = inputs[3].read_bytes()
    assert raw == dumps_canonical(json.loads(raw.decode("utf-8")), "episode narration plan")


def test_the_summary_reports_what_was_narrated(
    inputs: tuple[Path, Path, Path, Path], capsys: Any
) -> None:
    """The stdout summary is machine-readable and agrees with the file it describes."""
    build_narration_plan.main(_argv(inputs))
    reported = json.loads(capsys.readouterr().out)
    assert reported["episode"] == 2
    assert reported["mode"] == "transition"
    assert reported["units"] == 2
    assert reported["units_shown"] + reported["units_unshown"] == reported["units"]
    assert reported["bytes"] == len(inputs[3].read_bytes())


def test_the_command_creates_missing_parent_directories(
    inputs: tuple[Path, Path, Path, Path],
) -> None:
    """A caller may name an output path whose directory does not exist yet."""
    story, shots, export, output = inputs
    nested = output.parent / "a" / "b" / "narration.json"
    assert build_narration_plan.main(_argv((story, shots, export, nested))) == 0
    assert nested.is_file()


# ---- refusals


def test_an_existing_output_is_never_overwritten(
    inputs: tuple[Path, Path, Path, Path], capsys: Any
) -> None:
    """There is no overwrite option in V1, and the existing file is left untouched."""
    output = inputs[3]
    output.write_bytes(b"existing\n")
    assert build_narration_plan.main(_argv(inputs)) == 1
    assert "already exists" in capsys.readouterr().err
    assert output.read_bytes() == b"existing\n"


@pytest.mark.parametrize("index,flag", [(0, "--story"), (1, "--shots"), (2, "--export")])
def test_a_missing_input_is_reported_cleanly(
    inputs: tuple[Path, Path, Path, Path], index: int, flag: str, capsys: Any
) -> None:
    """An absent input names itself, and no output is written."""
    paths = list(inputs)
    paths[index] = paths[index].parent / "absent.json"
    assert build_narration_plan.main(_argv(tuple(paths))) == 1  # type: ignore[arg-type]
    assert "not found" in capsys.readouterr().err
    assert not inputs[3].exists()


@pytest.mark.parametrize("index", [0, 1, 2])
def test_pretty_printed_input_is_refused(
    inputs: tuple[Path, Path, Path, Path], index: int, capsys: Any
) -> None:
    """The plan binds each document's digest, so the file must be what its writer emitted."""
    path = inputs[index]
    document = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    assert build_narration_plan.main(_argv(inputs)) == 1
    assert "not canonical bytes" in capsys.readouterr().err
    assert not inputs[3].exists()


@pytest.mark.parametrize("index", [0, 1, 2])
def test_malformed_json_is_reported_cleanly(
    inputs: tuple[Path, Path, Path, Path], index: int, capsys: Any
) -> None:
    """Unparseable input is a refusal, not a crash.

    The message comes from ``loads_canonical`` -- the CLI defines no JSON error
    text of its own -- so it says "not valid JSON", never the old ad hoc "not
    valid UTF-8 JSON" the hand-rolled reader used to say for two different
    failures at once.
    """
    inputs[index].write_bytes(b"{not json\n")
    assert build_narration_plan.main(_argv(inputs)) == 1
    captured = capsys.readouterr()
    assert "is not valid JSON" in captured.err
    assert "Traceback" not in captured.err
    assert not inputs[3].exists()


@pytest.mark.parametrize("index", [0, 1, 2])
def test_malformed_utf8_is_reported_cleanly(
    inputs: tuple[Path, Path, Path, Path], index: int, capsys: Any
) -> None:
    """Bytes that are not UTF-8 are refused before anything tries to parse JSON."""
    inputs[index].write_bytes(b'{"format":"\xff\xfe"}\n')
    assert build_narration_plan.main(_argv(inputs)) == 1
    captured = capsys.readouterr()
    assert "is not valid UTF-8" in captured.err
    assert "Traceback" not in captured.err
    assert not inputs[3].exists()


@pytest.mark.parametrize("index", [0, 1, 2])
def test_duplicate_json_keys_are_refused_through_the_cli(
    inputs: tuple[Path, Path, Path, Path], index: int, capsys: Any
) -> None:
    """Python's default decoder keeps the last occurrence; the strict one refuses.

    Exercised through ``main()`` on every input position, not by calling
    ``loads_canonical`` directly -- proving the CLI actually routes through it,
    which is the whole point of Blocker B.
    """
    inputs[index].write_bytes(b'{"format":"a","format":"b"}\n')
    assert build_narration_plan.main(_argv(inputs)) == 1
    captured = capsys.readouterr()
    assert "duplicate JSON object key" in captured.err
    assert "Traceback" not in captured.err
    assert not inputs[3].exists()


@pytest.mark.parametrize(
    "index,literal,fragment",
    [
        (0, b"NaN", "non-standard JSON constant 'NaN'"),
        (1, b"Infinity", "non-standard JSON constant 'Infinity'"),
        (2, b"-Infinity", "non-standard JSON constant '-Infinity'"),
    ],
)
def test_non_standard_constants_are_refused_through_the_cli(
    inputs: tuple[Path, Path, Path, Path], index: int, literal: bytes, fragment: str, capsys: Any
) -> None:
    """``NaN``, ``Infinity`` and ``-Infinity`` are not standard JSON, and are refused.

    Plain ``json.loads`` accepts all three by default; the strict decoder
    Blocker B requires does not, and the CLI must actually be using it.
    """
    inputs[index].write_bytes(b'{"schema_version":' + literal + b"}\n")
    assert build_narration_plan.main(_argv(inputs)) == 1
    captured = capsys.readouterr()
    assert fragment in captured.err
    assert "Traceback" not in captured.err
    assert not inputs[3].exists()


@pytest.mark.parametrize("index", [0, 1, 2])
def test_an_overflowing_numeric_literal_is_refused_through_the_cli(
    inputs: tuple[Path, Path, Path, Path], index: int, capsys: Any
) -> None:
    """``1e999`` parses to infinity without ever reaching ``parse_constant``.

    A value that cannot round-trip may not enter a document this command binds
    by digest, so the finiteness check downstream of parsing is what catches it.
    """
    inputs[index].write_bytes(b'{"schema_version":1e999}\n')
    assert build_narration_plan.main(_argv(inputs)) == 1
    captured = capsys.readouterr()
    assert "must be a finite number" in captured.err
    assert "Traceback" not in captured.err
    assert not inputs[3].exists()


def test_a_mismatched_triple_is_refused(
    inputs: tuple[Path, Path, Path, Path], tmp_path: Path, capsys: Any
) -> None:
    """Three individually valid documents that do not join produce no plan."""
    story, shots, _export, output = inputs
    _s, _sh, other_export = build_sources(1)
    stale = _write(tmp_path / "stale.json", other_export, "render export")
    assert build_narration_plan.main(_argv((story, shots, stale, output))) == 1
    assert "the story never read" in capsys.readouterr().err
    assert not output.exists()


def test_no_output_survives_a_refusal(
    inputs: tuple[Path, Path, Path, Path], tmp_path: Path
) -> None:
    """A plan file never exists without its bindings having been proven."""
    story, _shots, export, output = inputs
    _s, other_shots, _e = build_sources(1)
    wrong = _write(tmp_path / "wrong_shots.json", other_shots, "shot direction plan")
    assert build_narration_plan.main(_argv((story, wrong, export, output))) == 1
    assert not output.exists()


def test_a_refusal_prints_no_traceback(inputs: tuple[Path, Path, Path, Path], capsys: Any) -> None:
    """An anticipated failure reports one line on stderr and exits 1."""
    inputs[0].write_bytes(b"{}\n")
    assert build_narration_plan.main(_argv(inputs)) == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("error: ")
    assert "Traceback" not in captured.err


def test_a_directory_given_as_input_is_refused(
    inputs: tuple[Path, Path, Path, Path], tmp_path: Path, capsys: Any
) -> None:
    """A path that is not a file is refused before anything tries to read it."""
    story, shots, _export, output = inputs
    directory = tmp_path / "a_directory"
    directory.mkdir()
    assert build_narration_plan.main(_argv((story, shots, directory, output))) == 1
    assert "not found" in capsys.readouterr().err


def test_the_output_path_is_never_derived_from_document_content(
    inputs: tuple[Path, Path, Path, Path],
) -> None:
    """Every path this command touches came from an argument, never from a file.

    A document cannot name where it is written, so no hostile input can redirect
    the write or traverse out of the directory the caller chose.
    """
    source = Path(build_narration_plan.__file__).read_text(encoding="utf-8")
    assert "namespace.output" in source
    for hostile in ("document[", "story[", "shots[", "export["):
        assert f"Path({hostile}" not in source


def test_missing_required_arguments_exit_nonzero(
    inputs: tuple[Path, Path, Path, Path],
) -> None:
    """Argparse owns argument errors, and exits 2 as it always has."""
    with pytest.raises(SystemExit) as exit_info:
        build_narration_plan.main(["--story", str(inputs[0])])
    assert exit_info.value.code == 2


# ---- the CLI actually routes through the central strict decoder


def test_the_module_imports_the_central_decoder() -> None:
    """A behavioural test proves malformed input fails; this proves *why*.

    The tests above show every malformed case is refused, but a refusal alone
    does not prove which code path produced it. This checks the import
    directly, so a future edit that reintroduces a second hand-rolled decoder
    -- one that happened to refuse the same cases by coincidence -- would be
    caught here even if every behavioural test still passed.
    """
    source = Path(build_narration_plan.__file__).read_text(encoding="utf-8")
    assert "from living_diorama.persistence.json_codec import" in source
    assert "loads_canonical" in source


def test_the_module_calls_no_other_json_decoder() -> None:
    """``json.loads(`` may not appear as a call; only ``json.dumps`` for stdout.

    Checked over the parsed syntax tree rather than the file text, so a
    docstring explaining what the module used to do -- as this one's own
    module docstring does, by name -- is not mistaken for the module doing it.
    A second decoder, even one that mimics ``loads_canonical``'s rules, would
    duplicate the one place this project's canonical-bytes contract is allowed
    to live.
    """
    import ast

    source = Path(build_narration_plan.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = {
        f"{node.func.value.id}.{node.func.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    }
    assert "json.loads" not in calls
    assert "json.dumps" in calls
