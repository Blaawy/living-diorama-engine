"""The build_audio_track_plan CLI: the audited-directory precondition and never-overwrite."""

import json
from pathlib import Path
from typing import Any

from living_diorama.cli.build_audio_track_plan import main
from living_diorama.persistence.json_codec import dumps_canonical


def _write_all(tmp_path: Path, sources: tuple[Any, ...]) -> dict[str, Path]:
    realization, presentation, delivery, narration, shots, story, export = sources
    paths = {}
    for name, document in (
        ("presentation", presentation),
        ("realization", realization),
        ("delivery", delivery),
        ("narration", narration),
        ("shots", shots),
        ("story", story),
        ("export", export),
    ):
        path = tmp_path / f"{name}.json"
        path.write_bytes(dumps_canonical(document, name))
        paths[name] = path
    return paths


def _argv(voice_dir: Path, paths: dict[str, Path], output: Path) -> list[str]:
    return [
        "--voice-dir",
        str(voice_dir),
        "--presentation",
        str(paths["presentation"]),
        "--realization",
        str(paths["realization"]),
        "--delivery",
        str(paths["delivery"]),
        "--narration",
        str(paths["narration"]),
        "--shots",
        str(paths["shots"]),
        "--story",
        str(paths["story"]),
        "--export",
        str(paths["export"]),
        "--output",
        str(output),
    ]


def test_the_command_writes_a_verified_plan(
    voice_directory_ep1: Path, sources_ep1: tuple[Any, ...], tmp_path: Path, capsys: Any
) -> None:
    """The command writes a verified plan and reports its summary."""
    paths = _write_all(tmp_path, sources_ep1)
    output = tmp_path / "audio_track_plan.json"
    exit_code = main(_argv(voice_directory_ep1, paths, output))
    assert exit_code == 0
    assert output.is_file()
    document = json.loads(output.read_bytes())
    assert document["format"] == "living_diorama_episode_audio_track_plan"
    out = capsys.readouterr().out
    counts = json.loads(out)
    assert counts["audio_samples_total"] == document["clock"]["audio_samples_total"]


def test_an_existing_output_is_never_overwritten(
    voice_directory_ep1: Path, sources_ep1: tuple[Any, ...], tmp_path: Path
) -> None:
    """An existing output is never overwritten."""
    paths = _write_all(tmp_path, sources_ep1)
    output = tmp_path / "audio_track_plan.json"
    output.write_bytes(b"occupied\n")
    exit_code = main(_argv(voice_directory_ep1, paths, output))
    assert exit_code == 1
    assert output.read_bytes() == b"occupied\n"


def test_a_voice_directory_failing_the_audit_refuses_and_writes_nothing(
    voice_directory_ep1: Path, sources_ep1: tuple[Any, ...], tmp_path: Path, capsys: Any
) -> None:
    """A voice directory failing the audit refuses, with the audit's problems surfaced."""
    (voice_directory_ep1 / "intruder.txt").write_bytes(b"x")
    paths = _write_all(tmp_path, sources_ep1)
    output = tmp_path / "audio_track_plan.json"
    exit_code = main(_argv(voice_directory_ep1, paths, output))
    assert exit_code == 1
    assert not output.exists()
    err = capsys.readouterr().err
    assert "error:" in err


def test_pretty_printed_input_is_refused(
    voice_directory_ep1: Path, sources_ep1: tuple[Any, ...], tmp_path: Path
) -> None:
    """Pretty-printed (non-canonical) input is refused."""
    paths = _write_all(tmp_path, sources_ep1)
    document = json.loads(paths["presentation"].read_bytes())
    paths["presentation"].write_text(json.dumps(document, indent=2), encoding="utf-8")
    output = tmp_path / "audio_track_plan.json"
    exit_code = main(_argv(voice_directory_ep1, paths, output))
    assert exit_code == 1
    assert not output.exists()


def test_a_missing_input_is_reported_cleanly(
    voice_directory_ep1: Path, sources_ep1: tuple[Any, ...], tmp_path: Path, capsys: Any
) -> None:
    """A missing input is reported cleanly, without a traceback."""
    paths = _write_all(tmp_path, sources_ep1)
    paths["story"].unlink()
    output = tmp_path / "audio_track_plan.json"
    exit_code = main(_argv(voice_directory_ep1, paths, output))
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "Traceback" not in err


def test_there_is_no_flag_accepting_a_detached_manifest() -> None:
    """There is no CLI flag accepting a detached, unaudited manifest file."""
    from living_diorama.cli import build_audio_track_plan as module

    # Reconstruct the parser exactly as main() does, without invoking it.
    source = module.__file__
    assert source is not None
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    assert "--voice-manifest" not in text
    assert "--manifest" not in text
