"""``python -m living_diorama.cli.serialize_episode_captions`` -- the serializing CLI."""

import json
from pathlib import Path
from typing import Any

import pytest

from living_diorama.caption_serialization.caption_serialization_audit import (
    audit_caption_serialization_directory,
)
from living_diorama.caption_serialization.caption_serialization_spec import (
    CAPTION_SERIALIZATION_MANIFEST_FILENAME,
)
from living_diorama.cli import serialize_episode_captions as cli

SUMMARY_KEYS = {
    "caption_frames_total",
    "captions_dir",
    "captions_total",
    "episode",
    "fps",
    "mode",
    "presentation_frames_total",
    "srt_sha256",
    "vtt_sha256",
}

FLAG_ORDER = (
    "caption_plan",
    "realization",
    "presentation",
    "delivery",
    "narration",
    "shots",
    "story",
    "export",
    "output_root",
)


def _argv(inputs: dict[str, Path], output_root: Path | None = None) -> list[str]:
    """Build the full nine-flag argv list from a fixture dict keyed by flag name."""
    argv: list[str] = []
    for key in FLAG_ORDER:
        flag = "--" + key.replace("_", "-")
        value = output_root if key == "output_root" and output_root is not None else inputs[key]
        argv.extend([flag, str(value)])
    return argv


# ---------------------------------------------------------------------------
# Argument parsing / exit codes / output shape
# ---------------------------------------------------------------------------


def test_all_nine_flags_are_parsed(cli_inputs_ep1: dict[str, Path]) -> None:
    """All nine flags are parsed."""
    exit_code = cli.main(_argv(cli_inputs_ep1))
    assert exit_code == 0


def test_a_missing_required_flag_is_an_argparse_error(
    cli_inputs_ep1: dict[str, Path],
) -> None:
    """A missing required flag is an argparse error, exit code 2."""
    argv = _argv(cli_inputs_ep1)
    index = argv.index("--narration")
    del argv[index : index + 2]
    with pytest.raises(SystemExit) as excinfo:
        cli.main(argv)
    assert excinfo.value.code == 2


def test_exit_zero_on_success(
    cli_inputs_ep1: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit zero on success; stdout JSON carries the full summary key set."""
    exit_code = cli.main(_argv(cli_inputs_ep1))
    assert exit_code == 0
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert set(summary) == SUMMARY_KEYS
    assert "captions_total" in summary
    assert "srt_sha256" in summary


def test_exit_one_on_a_missing_input_file(
    cli_inputs_ep1: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit one on a missing input file, with a message rather than a traceback."""
    argv = _argv(cli_inputs_ep1)
    argv[argv.index("--caption-plan") + 1] = str(
        cli_inputs_ep1["caption_plan"].with_name("nonexistent.json")
    )
    exit_code = cli.main(argv)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err
    assert "Traceback" not in captured.err


# ---------------------------------------------------------------------------
# Non-canonical bytes / cross-document slots
# ---------------------------------------------------------------------------


def test_non_canonical_input_bytes_refuse(
    cli_inputs_ep1: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Non canonical input bytes refuse with 'canonical' in the message."""
    cli_inputs_ep1["caption_plan"].write_bytes(b"{ }")
    exit_code = cli.main(_argv(cli_inputs_ep1))
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "canonical" in captured.err
    assert "Traceback" not in captured.err


def test_a_presentation_plan_in_the_caption_plan_slot_is_refused(
    cli_inputs_ep1: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """A presentation-plan-shaped document as --caption-plan is refused by the locked gate."""
    presentation_bytes = cli_inputs_ep1["presentation"].read_bytes()
    cli_inputs_ep1["caption_plan"].write_bytes(presentation_bytes)
    exit_code = cli.main(_argv(cli_inputs_ep1))
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "caption plan" in captured.err
    assert "Traceback" not in captured.err


def test_stdout_is_empty_on_refusal(
    cli_inputs_ep1: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Refusals print nothing on stdout."""
    argv = _argv(cli_inputs_ep1)
    argv[argv.index("--export") + 1] = str(cli_inputs_ep1["export"].with_name("gone.json"))
    assert cli.main(argv) == 1
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# End-to-end: the published captions directory is truthful
# ---------------------------------------------------------------------------


def test_a_successful_publish_produces_a_clean_captions_directory(
    cli_inputs_ep1: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """A successful publish produces a clean captions directory."""
    assert cli.main(_argv(cli_inputs_ep1)) == 0
    captured = capsys.readouterr()
    captions_dir = Path(json.loads(captured.out)["captions_dir"])
    assert captions_dir.is_dir()
    assert audit_caption_serialization_directory(captions_dir) == []


def test_the_published_directory_is_under_the_output_root(
    cli_inputs_ep1: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """The published directory lives directly under the output root."""
    assert cli.main(_argv(cli_inputs_ep1)) == 0
    captured = capsys.readouterr()
    captions_dir = Path(json.loads(captured.out)["captions_dir"])
    assert captions_dir.parent == cli_inputs_ep1["output_root"]


def test_rerun_is_a_no_op(
    cli_inputs_ep1: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Rerunning the same inputs exits 0 and changes nothing."""
    assert cli.main(_argv(cli_inputs_ep1)) == 0
    first = capsys.readouterr()
    first_dir = Path(json.loads(first.out)["captions_dir"])
    manifest_before = (first_dir / CAPTION_SERIALIZATION_MANIFEST_FILENAME).read_bytes()

    assert cli.main(_argv(cli_inputs_ep1)) == 0
    second = capsys.readouterr()
    second_dir = Path(json.loads(second.out)["captions_dir"])
    assert second_dir == first_dir
    manifest_after = (second_dir / CAPTION_SERIALIZATION_MANIFEST_FILENAME).read_bytes()
    assert manifest_after == manifest_before
    assert audit_caption_serialization_directory(second_dir) == []


# ---------------------------------------------------------------------------
# Single-capture: each input path is read exactly once
# ---------------------------------------------------------------------------


def test_each_input_path_is_read_exactly_once(
    cli_inputs_ep1: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each input path is read exactly once -- the single-capture law."""
    counts: dict[Path, int] = {}
    real_read_bytes = Path.read_bytes

    def _counting_read_bytes(self: Path, *args: Any, **kwargs: Any) -> bytes:
        counts[self] = counts.get(self, 0) + 1
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", _counting_read_bytes)
    assert cli.main(_argv(cli_inputs_ep1)) == 0
    for key in (
        "caption_plan",
        "realization",
        "presentation",
        "delivery",
        "narration",
        "shots",
        "story",
        "export",
    ):
        path = cli_inputs_ep1[key]
        assert counts.get(path, 0) == 1, f"{key} was read {counts.get(path, 0)} times"


# ---------------------------------------------------------------------------
# The --presentation-profile flag: a real v3 presentation plan end to end
# ---------------------------------------------------------------------------


def _write_v3_inputs(cli_inputs_ep1: dict[str, Path], sources_ep1) -> None:
    """Overwrite the presentation and caption-plan files with real v3 documents."""
    from living_diorama.caption import build_episode_caption_plan_document
    from living_diorama.persistence.json_codec import dumps_canonical
    from living_diorama.presentation import build_episode_presentation_plan_document

    realization, _presentation, delivery, narration, _shots, _story, _export = sources_ep1
    v3_presentation = build_episode_presentation_plan_document(
        delivery, narration, realization, presentation_profile="v3"
    )
    v3_caption_plan = build_episode_caption_plan_document(realization, v3_presentation)
    cli_inputs_ep1["presentation"].write_bytes(
        dumps_canonical(v3_presentation, "presentation plan")
    )
    cli_inputs_ep1["caption_plan"].write_bytes(dumps_canonical(v3_caption_plan, "caption plan"))


def test_the_v3_presentation_profile_flag_accepts_a_real_v3_presentation_plan(
    cli_inputs_ep1: dict[str, Path],
    sources_ep1,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--presentation-profile v3`` admits the real frozen, content-sized plan.

    A real V3 presentation plan carries no ``motion_windows``, so under the
    default (v1) derivation the reused Phase 27 gate inside the Phase 32
    verification re-derives V1 bytes and refuses; the explicit v3 flag makes
    the gate re-derive the plan it was actually built under, and the caption
    serialization is published.
    """
    _write_v3_inputs(cli_inputs_ep1, sources_ep1)
    exit_code = cli.main(_argv(cli_inputs_ep1) + ["--presentation-profile", "v3"])
    assert exit_code == 0
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["captions_total"] == 3


def test_without_the_flag_a_v3_presentation_plan_is_still_refused(
    cli_inputs_ep1: dict[str, Path],
    sources_ep1,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Omitting the flag keeps today's refusal of a V3 plan, publishing nothing."""
    _write_v3_inputs(cli_inputs_ep1, sources_ep1)
    exit_code = cli.main(_argv(cli_inputs_ep1))
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "does not equal the deterministic derivation" in captured.err
    assert "Traceback" not in captured.err
