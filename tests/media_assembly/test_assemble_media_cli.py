"""``python -m living_diorama.cli.assemble_episode_media`` -- the assembling CLI."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from living_diorama.cli import assemble_episode_media as cli
from living_diorama.media_assembly.media_assembly_audit import audit_media_assembly_directory
from living_diorama.media_assembly.media_assembly_staging import MediaAssemblyDirectoryRefused
from living_diorama.persistence.json_codec import dumps_canonical


def _argv(inputs: dict[str, Path], output_root: Path | None = None) -> list[str]:
    return [
        "--render-dir",
        str(inputs["render_dir"]),
        "--composition-dir",
        str(inputs["composition_dir"]),
        "--presentation",
        str(inputs["presentation"]),
        "--delivery",
        str(inputs["delivery"]),
        "--shots",
        str(inputs["shots"]),
        "--narration",
        str(inputs["narration"]),
        "--realization",
        str(inputs["realization"]),
        "--story",
        str(inputs["story"]),
        "--export",
        str(inputs["export"]),
        "--output-root",
        str(output_root if output_root is not None else inputs["output_root"]),
    ]


def _call_assemble(inputs: dict[str, Path], output_root: Path | None = None) -> Path:
    root = output_root if output_root is not None else inputs["output_root"]
    return cli.assemble(
        inputs["render_dir"],
        inputs["composition_dir"],
        inputs["presentation"],
        inputs["delivery"],
        inputs["shots"],
        inputs["narration"],
        inputs["realization"],
        inputs["story"],
        inputs["export"],
        root,
    )


# ---------------------------------------------------------------------------
# Argument parsing / exit codes / output shape
# ---------------------------------------------------------------------------


def test_all_ten_flags_are_parsed(cli_inputs_ep0: dict[str, Path]) -> None:
    """All ten flags are parsed."""
    exit_code = cli.main(_argv(cli_inputs_ep0))
    assert exit_code == 0


def test_a_missing_required_flag_is_an_argparse_error(cli_inputs_ep0: dict[str, Path]) -> None:
    """A missing required flag is an argparse error."""
    argv = _argv(cli_inputs_ep0)
    # drop --shots and its value
    index = argv.index("--shots")
    del argv[index : index + 2]
    with pytest.raises(SystemExit) as excinfo:
        cli.main(argv)
    assert excinfo.value.code != 0


def test_exit_zero_on_success(
    cli_inputs_ep0: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit zero on success."""
    exit_code = cli.main(_argv(cli_inputs_ep0))
    assert exit_code == 0
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert set(summary) == {
        "assembly_dir",
        "audio_samples_total",
        "episode",
        "fps",
        "mode",
        "presentation_frames_total",
        "shot_plan_sha256",
        "track_sha256",
        "unique_semantic_frames_used",
    }


def test_exit_one_on_a_missing_input_file(
    cli_inputs_ep0: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit one on a missing input file."""
    argv = _argv(cli_inputs_ep0)
    argv[argv.index("--shots") + 1] = str(cli_inputs_ep0["shots"].with_name("nonexistent.json"))
    exit_code = cli.main(argv)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err
    assert "Traceback" not in captured.err


def test_error_message_not_a_traceback_on_refusal(
    cli_inputs_ep0: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Error message not a traceback on refusal."""
    output_root = cli_inputs_ep0["output_root"]
    output_root.mkdir(parents=True)
    try:
        (output_root.with_suffix(".link")).symlink_to(output_root, target_is_directory=True)
        target = output_root.with_suffix(".link")
    except OSError:
        pytest.skip("platform cannot create a symlink")
    argv = _argv(cli_inputs_ep0, output_root=target)
    exit_code = cli.main(argv)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "error:" in captured.err


# ---------------------------------------------------------------------------
# _require_direct_parent is the first statement
# ---------------------------------------------------------------------------


def test_require_direct_parent_is_the_first_statement(
    cli_inputs_ep0: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Require direct parent is the first statement."""
    calls: list[str] = []
    real = cli._require_direct_parent

    def _tracking(expected_parent: Path) -> None:
        calls.append("_require_direct_parent")
        real(expected_parent)

    # Make every other read observably fail if reached first.
    def _boom(*args: Any, **kwargs: Any) -> Any:
        calls.append("_read_canonical_with_bytes")
        raise AssertionError("a document was read before _require_direct_parent ran")

    monkeypatch.setattr(cli, "_require_direct_parent", _tracking)
    monkeypatch.setattr(cli, "_read_canonical_with_bytes", _boom)
    monkeypatch.setattr(cli, "_read_canonical", _boom)
    with pytest.raises(AssertionError):
        _call_assemble(cli_inputs_ep0)
    assert calls[0] == "_require_direct_parent"


def test_indirect_output_root_refuses_even_when_a_valid_assembly_exists_behind_it(
    cli_inputs_ep0: dict[str, Path],
) -> None:
    """Indirect output root refuses even when a valid assembly exists behind it."""
    output_root = cli_inputs_ep0["output_root"]
    _call_assemble(cli_inputs_ep0, output_root)  # publish once, legitimately
    assert output_root.is_dir()

    link = cli_inputs_ep0["output_root"].with_name("output_root_link")
    try:
        link.symlink_to(output_root, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    with pytest.raises(MediaAssemblyDirectoryRefused):
        _call_assemble(cli_inputs_ep0, link)


# ---------------------------------------------------------------------------
# Missing input file / non-canonical bytes
# ---------------------------------------------------------------------------


def test_missing_input_file_refuses(cli_inputs_ep0: dict[str, Path]) -> None:
    """Missing input file refuses."""
    cli_inputs_ep0["narration"].unlink()
    with pytest.raises(FileNotFoundError):
        _call_assemble(cli_inputs_ep0)


def test_non_canonical_input_bytes_refuse(cli_inputs_ep0: dict[str, Path]) -> None:
    """Non canonical input bytes refuse."""
    cli_inputs_ep0["shots"].write_bytes(b'{ "spaced" : true }')
    with pytest.raises(ValueError):
        _call_assemble(cli_inputs_ep0)


# ---------------------------------------------------------------------------
# The Phase 27 gate is called; no upstream directory audit is called
# ---------------------------------------------------------------------------


def test_the_phase_27_gate_is_called(
    cli_inputs_ep0: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The phase 27 gate is called."""
    calls: list[Any] = []
    real = cli.validate_episode_presentation_plan_against_sources

    def _tracking(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(cli, "validate_episode_presentation_plan_against_sources", _tracking)
    _call_assemble(cli_inputs_ep0)
    assert len(calls) == 1
    assert len(calls[0]) == 7


def test_no_upstream_directory_audit_is_imported() -> None:
    """No upstream directory audit is imported."""
    import inspect

    source = inspect.getsource(cli)
    assert "audit_render_directory" not in source
    assert "audit_audio_composition_directory" not in source


# ---------------------------------------------------------------------------
# Single-capture: each input path is read exactly once
# ---------------------------------------------------------------------------


def test_each_input_path_is_read_exactly_once(
    cli_inputs_ep0: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each input path is read exactly once."""
    counts: dict[Path, int] = {}
    real_read_bytes = Path.read_bytes

    def _counting_read_bytes(self: Path, *args: Any, **kwargs: Any) -> bytes:
        counts[self] = counts.get(self, 0) + 1
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", _counting_read_bytes)
    _call_assemble(cli_inputs_ep0)

    names = ("presentation", "delivery", "shots", "narration", "realization", "story", "export")
    for name in names:
        path = cli_inputs_ep0[name]
        assert counts.get(path, 0) == 1, f"{name} was read {counts.get(path, 0)} times"


def test_a_mutation_between_reads_is_refused(cli_inputs_ep0: dict[str, Path]) -> None:
    """A mutation between reads is refused.

    ``_read_canonical`` reads once and re-checks canonical form from that same read;
    mutating the file to a still-canonical but different document produces a document that
    disagrees with everything downstream expects -- refused by the join/gate, not silently
    accepted as a stale second observation.
    """
    delivery_bytes_original = cli_inputs_ep0["delivery"].read_bytes()
    # Corrupt into something that still parses as JSON but is not the real delivery plan.
    cli_inputs_ep0["delivery"].write_bytes(b'{"not":"a delivery plan"}\n')
    with pytest.raises((TypeError, ValueError)):
        _call_assemble(cli_inputs_ep0)
    # restore is unnecessary -- tmp_path is per-test -- but documents intent
    assert delivery_bytes_original != cli_inputs_ep0["delivery"].read_bytes()


# ---------------------------------------------------------------------------
# End-to-end: the published assembly is truthful
# ---------------------------------------------------------------------------


def test_a_successful_assemble_publishes_a_clean_assembly(cli_inputs_ep0: dict[str, Path]) -> None:
    """A successful assemble publishes a clean assembly."""
    published = _call_assemble(cli_inputs_ep0)
    assert audit_media_assembly_directory(published) == []


# ---------------------------------------------------------------------------
# H1 - H5 -- a standalone-valid document of the WRONG KIND in each slot
#
# Every substitute below is a real, standalone-valid document produced by its own
# locked upstream layer. Nothing here is a malformed blob: each row proves the slot
# is type-pinned, not merely shape-checked.
# ---------------------------------------------------------------------------


def _isolated_render_dir(tmp_path: Path, render_dir: Path) -> Path:
    """Return a private copy of a render directory, safe to damage."""
    destination = tmp_path / "isolated_render"
    shutil.copytree(render_dir, destination)
    return destination


def _isolated_composition_dir(tmp_path: Path, composition_dir: Path) -> Path:
    """Return a private copy of a composition directory, safe to damage."""
    destination = tmp_path / "isolated_composition"
    shutil.copytree(composition_dir, destination)
    return destination


def test_h1_a_caption_plan_passed_where_the_presentation_plan_is_expected(
    cli_inputs_ep0: dict[str, Path], sources_ep0: tuple[dict[str, Any], ...]
) -> None:
    """H1 a caption plan passed where the presentation plan is expected."""
    from living_diorama.caption import build_episode_caption_plan_document

    realization, presentation = sources_ep0[0], sources_ep0[1]
    caption_plan = build_episode_caption_plan_document(realization, presentation)
    cli_inputs_ep0["presentation"].write_bytes(
        dumps_canonical(caption_plan, "episode caption plan")
    )
    with pytest.raises((TypeError, ValueError)):
        _call_assemble(cli_inputs_ep0)


def test_h2_a_phase_30_audio_track_plan_passed_as_the_composition_manifest(
    tmp_path: Path, cli_inputs_ep0: dict[str, Path]
) -> None:
    """H2 a Phase 30 audio track plan passed as the composition manifest."""
    from living_diorama.audio_composition.audio_composition_spec import (
        AUDIO_COMPOSITION_MANIFEST_FILENAME,
        AUDIO_TRACK_PLAN_FILENAME,
    )

    isolated = _isolated_composition_dir(tmp_path, cli_inputs_ep0["composition_dir"])
    # The real, standalone-valid Phase 30 audio track plan this composition was
    # built from is published inside the composition directory itself.
    track_plan_bytes = (isolated / AUDIO_TRACK_PLAN_FILENAME).read_bytes()
    (isolated / AUDIO_COMPOSITION_MANIFEST_FILENAME).write_bytes(track_plan_bytes)
    cli_inputs_ep0["composition_dir"] = isolated
    with pytest.raises((TypeError, ValueError)):
        _call_assemble(cli_inputs_ep0)


def test_h3_a_phase_23_render_plan_passed_as_the_render_manifest(
    tmp_path: Path,
    cli_inputs_ep0: dict[str, Path],
    sources_ep0: tuple[dict[str, Any], ...],
) -> None:
    """H3 a Phase 23 render plan passed as the render manifest."""
    from living_diorama.render_execution import build_episode_render_plan_document
    from living_diorama.render_execution.render_execution_spec import RENDER_MANIFEST_FILENAME

    shots, story = sources_ep0[4], sources_ep0[5]
    render_plan = build_episode_render_plan_document(shots, story)

    isolated = _isolated_render_dir(tmp_path, cli_inputs_ep0["render_dir"])
    (isolated / RENDER_MANIFEST_FILENAME).write_bytes(
        dumps_canonical(render_plan, "episode render plan")
    )
    cli_inputs_ep0["render_dir"] = isolated
    with pytest.raises((TypeError, ValueError)):
        _call_assemble(cli_inputs_ep0)


def test_h4_a_narration_plan_passed_as_the_delivery_witness(
    cli_inputs_ep0: dict[str, Path], sources_ep0: tuple[dict[str, Any], ...]
) -> None:
    """H4 a narration plan passed as the delivery witness."""
    narration = sources_ep0[3]
    cli_inputs_ep0["delivery"].write_bytes(dumps_canonical(narration, "episode narration plan"))
    with pytest.raises((TypeError, ValueError)):
        _call_assemble(cli_inputs_ep0)


def test_h5_a_story_plan_passed_as_the_shot_witness(
    cli_inputs_ep0: dict[str, Path], sources_ep0: tuple[dict[str, Any], ...]
) -> None:
    """H5 a story plan passed as the shot witness."""
    story = sources_ep0[5]
    cli_inputs_ep0["shots"].write_bytes(dumps_canonical(story, "episode story plan"))
    with pytest.raises((TypeError, ValueError)):
        _call_assemble(cli_inputs_ep0)


# ---------------------------------------------------------------------------
# T1 / T2 / T4 / T6 -- the second read that would diverge does not exist
#
# Each test serves the true bytes once for one authoritative input and attacker
# bytes on every later read of that same path. A run that still succeeds, with a
# read count of exactly one, proves the mutation has no seam to land in: there is
# no second observation for it to poison.
# ---------------------------------------------------------------------------


def _poison_second_read(
    monkeypatch: pytest.MonkeyPatch, target: Path, poison: bytes
) -> dict[str, int]:
    """Serve true bytes once for ``target``, then attacker bytes on every later read."""
    counter = {"reads": 0}
    real_read_bytes = Path.read_bytes

    def _patched(self: Path, *args: Any, **kwargs: Any) -> bytes:
        if self == target:
            counter["reads"] += 1
            if counter["reads"] > 1:
                return poison
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", _patched)
    return counter


def test_t1_the_render_manifest_mutated_between_the_digest_and_the_parse(
    cli_inputs_ep0: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """T1 render manifest mutated between digest and parse."""
    from living_diorama.render_execution.render_execution_spec import RENDER_MANIFEST_FILENAME

    target = cli_inputs_ep0["render_dir"] / RENDER_MANIFEST_FILENAME
    counter = _poison_second_read(monkeypatch, target, b'{"format":"forged"}\n')
    published = _call_assemble(cli_inputs_ep0)
    assert counter["reads"] == 1
    assert audit_media_assembly_directory(published) == []


def test_t2_the_presentation_plan_mutated_between_the_gate_and_the_digest(
    cli_inputs_ep0: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """T2 presentation plan mutated between the gate and the digest."""
    target = cli_inputs_ep0["presentation"]
    counter = _poison_second_read(monkeypatch, target, b'{"format":"forged"}\n')
    published = _call_assemble(cli_inputs_ep0)
    assert counter["reads"] == 1
    assert audit_media_assembly_directory(published) == []


def test_t4_the_composition_manifest_mutated_between_validation_and_the_audio_join(
    cli_inputs_ep0: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """T4 composition manifest mutated between validation and the audio join."""
    from living_diorama.audio_composition.audio_composition_spec import (
        AUDIO_COMPOSITION_MANIFEST_FILENAME,
    )

    target = cli_inputs_ep0["composition_dir"] / AUDIO_COMPOSITION_MANIFEST_FILENAME
    counter = _poison_second_read(monkeypatch, target, b'{"format":"forged"}\n')
    published = _call_assemble(cli_inputs_ep0)
    assert counter["reads"] == 1
    assert audit_media_assembly_directory(published) == []


@pytest.mark.parametrize("witness", ["shots", "delivery"])
def test_t6_a_witness_mutated_between_the_gate_and_its_digest(
    cli_inputs_ep0: dict[str, Path], monkeypatch: pytest.MonkeyPatch, witness: str
) -> None:
    """T6 a witness mutated between the gate and its digest."""
    target = cli_inputs_ep0[witness]
    counter = _poison_second_read(monkeypatch, target, b'{"format":"forged"}\n')
    published = _call_assemble(cli_inputs_ep0)
    assert counter["reads"] == 1
    assert audit_media_assembly_directory(published) == []


# ---------------------------------------------------------------------------
# B8 -- a bound document re-serialized with different spacing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flag", ["presentation", "delivery", "shots"])
def test_b8_a_bound_document_reserialized_with_different_spacing(
    cli_inputs_ep0: dict[str, Path], flag: str
) -> None:
    """B8 any bound document re-serialized with different spacing.

    The document still parses to exactly the same value; only its byte encoding
    changed. Phase 33 binds bytes, so the non-canonical encoding is refused rather
    than silently normalised.
    """
    import json

    document = json.loads(cli_inputs_ep0[flag].read_text(encoding="utf-8"))
    respaced = json.dumps(document, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    assert respaced != cli_inputs_ep0[flag].read_bytes()
    assert json.loads(respaced.decode("utf-8")) == document
    cli_inputs_ep0[flag].write_bytes(respaced)
    with pytest.raises(ValueError):
        _call_assemble(cli_inputs_ep0)
