"""The build_caption_plan CLI: never-overwrite, exact summary keys, exit codes."""

import json

import pytest

from living_diorama.caption import build_episode_caption_plan_bytes
from living_diorama.cli import build_caption_plan
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.presentation import build_episode_presentation_plan_bytes


def _write(path, document, description) -> None:
    """Write."""
    path.write_bytes(dumps_canonical(document, description))


def _write_all_sources(tmp_path, sources_ep1):
    """Write all sources."""
    realization, presentation, delivery, narration, shots, story, export = sources_ep1
    root = tmp_path / "sources"
    root.mkdir(parents=True)
    _write(root / "realization.json", realization, "language realization plan")
    _write(root / "presentation.json", presentation, "presentation plan")
    _write(root / "delivery.json", delivery, "narration delivery plan")
    _write(root / "narration.json", narration, "episode narration plan")
    _write(root / "shots.json", shots, "shot direction plan")
    _write(root / "story.json", story, "episode story plan")
    _write(root / "export.json", export, "render export")
    return root


def _args(root, output, *, presentation_profile: str | None = None):
    """Args."""
    args = [
        "--realization",
        str(root / "realization.json"),
        "--presentation",
        str(root / "presentation.json"),
        "--delivery",
        str(root / "delivery.json"),
        "--narration",
        str(root / "narration.json"),
        "--shots",
        str(root / "shots.json"),
        "--story",
        str(root / "story.json"),
        "--export",
        str(root / "export.json"),
        "--output",
        str(output),
    ]
    if presentation_profile is not None:
        args += ["--presentation-profile", presentation_profile]
    return args


def test_cli_end_to_end_success(tmp_path, sources_ep1, capsys) -> None:
    """CLI end to end success."""
    root = _write_all_sources(tmp_path, sources_ep1)
    output = tmp_path / "caption_plan.json"
    exit_code = build_caption_plan.main(_args(root, output))
    assert exit_code == 0
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["captions_total"] == 3
    assert summary["caption_frames_total"] == 648


def test_cli_never_overwrites(tmp_path, sources_ep1) -> None:
    """CLI never overwrites."""
    root = _write_all_sources(tmp_path, sources_ep1)
    output = tmp_path / "caption_plan.json"
    assert build_caption_plan.main(_args(root, output)) == 0
    exit_code = build_caption_plan.main(_args(root, output))
    assert exit_code == 1


def test_cli_refuses_missing_input(tmp_path, sources_ep1) -> None:
    """CLI refuses missing input."""
    root = _write_all_sources(tmp_path, sources_ep1)
    output = tmp_path / "caption_plan.json"
    args = _args(root, output)
    args[1] = str(root / "does_not_exist.json")
    exit_code = build_caption_plan.main(args)
    assert exit_code == 1


def test_cli_writes_builders_exact_bytes(tmp_path, sources_ep1) -> None:
    """CLI writes builders exact bytes."""
    root = _write_all_sources(tmp_path, sources_ep1)
    output = tmp_path / "caption_plan.json"
    build_caption_plan.main(_args(root, output))
    realization, presentation, *_ = sources_ep1
    expected = build_episode_caption_plan_bytes(realization, presentation)
    assert output.read_bytes() == expected


def test_the_default_omitted_flag_reproduces_todays_bytes_exactly(tmp_path, sources_ep1) -> None:
    """No flag (and an explicit v1) reproduce today's exact caption plan bytes.

    A genuine regression guard: the CLI's whole write path -- the reused
    Phase 27 gate included -- must emit byte-for-byte the same document the
    library derives for a V1 presentation plan, before and after this flag
    exists.
    """
    realization, presentation, *_ = sources_ep1
    expected = build_episode_caption_plan_bytes(realization, presentation)

    root = _write_all_sources(tmp_path, sources_ep1)
    output = tmp_path / "caption_plan.json"
    assert build_caption_plan.main(_args(root, output)) == 0
    assert output.read_bytes() == expected

    explicit_root = _write_all_sources(tmp_path / "explicit", sources_ep1)
    explicit_output = tmp_path / "explicit" / "caption_plan.json"
    assert (
        build_caption_plan.main(_args(explicit_root, explicit_output, presentation_profile="v1"))
        == 0
    )
    assert explicit_output.read_bytes() == expected


def test_the_v3_presentation_profile_flag_accepts_a_real_v3_presentation_plan(
    tmp_path, sources_ep1
) -> None:
    """``--presentation-profile v3`` admits the real frozen, content-sized plan.

    A real V3 presentation plan carries no ``motion_windows``, so under the
    default (v1) derivation the reused Phase 27 gate re-derives V1 bytes and
    refuses; the explicit v3 flag makes the gate re-derive the plan it was
    actually built under, and the caption plan is written.
    """
    realization, _presentation, delivery, narration, _shots, _story, _export = sources_ep1
    v3_document = loads_canonical(
        build_episode_presentation_plan_bytes(
            delivery, narration, realization, presentation_profile="v3"
        ),
        "presentation plan",
    )
    root = _write_all_sources(tmp_path, sources_ep1)
    _write(root / "presentation.json", v3_document, "presentation plan")
    output = tmp_path / "caption_plan.json"
    assert build_caption_plan.main(_args(root, output, presentation_profile="v3")) == 0
    assert output.read_bytes() == build_episode_caption_plan_bytes(realization, v3_document)


def test_without_the_flag_a_v3_presentation_plan_is_still_refused(
    tmp_path, sources_ep1, capsys
) -> None:
    """Omitting the flag keeps today's refusal of a V3 plan, leaving no output."""
    realization, _presentation, delivery, narration, _shots, _story, _export = sources_ep1
    v3_document = loads_canonical(
        build_episode_presentation_plan_bytes(
            delivery, narration, realization, presentation_profile="v3"
        ),
        "presentation plan",
    )
    root = _write_all_sources(tmp_path, sources_ep1)
    _write(root / "presentation.json", v3_document, "presentation plan")
    output = tmp_path / "caption_plan.json"
    assert build_caption_plan.main(_args(root, output)) == 1
    err = capsys.readouterr().err
    assert "does not equal the deterministic derivation" in err
    assert "Traceback" not in err
    assert not output.exists()


def test_cli_summary_has_exact_keys(tmp_path, sources_ep1, capsys) -> None:
    """CLI summary has exact keys."""
    root = _write_all_sources(tmp_path, sources_ep1)
    output = tmp_path / "caption_plan.json"
    build_caption_plan.main(_args(root, output))
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert set(summary.keys()) == {
        "bytes",
        "caption_frames_total",
        "captions_total",
        "episode",
        "mode",
        "presentation_frames_total",
        "uncaptioned_frames_total",
    }


def test_cli_refuses_non_canonical_input(tmp_path, sources_ep1) -> None:
    """CLI refuses non canonical input."""
    root = _write_all_sources(tmp_path, sources_ep1)
    # Reformat the realization file so it is valid JSON but not canonical bytes.
    document = loads_canonical(
        (root / "realization.json").read_bytes(), "language realization plan"
    )
    (root / "realization.json").write_bytes((json.dumps(document, indent=2) + "\n").encode("utf-8"))
    output = tmp_path / "caption_plan.json"
    exit_code = build_caption_plan.main(_args(root, output))
    assert exit_code == 1


def test_cli_all_seven_flags_required(tmp_path, sources_ep1) -> None:
    """CLI all seven flags required."""
    root = _write_all_sources(tmp_path, sources_ep1)
    output = tmp_path / "caption_plan.json"
    args = _args(root, output)
    truncated = args[:-4]  # drop --story --output pairs partially
    with pytest.raises(SystemExit):
        build_caption_plan.main(truncated)
