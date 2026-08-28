"""The build_caption_plan CLI: never-overwrite, exact summary keys, exit codes."""

import json

import pytest

from living_diorama.cli import build_caption_plan
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical


def _write(path, document, description) -> None:
    """Write."""
    path.write_bytes(dumps_canonical(document, description))


def _write_all_sources(tmp_path, sources_ep1):
    """Write all sources."""
    realization, presentation, delivery, narration, shots, story, export = sources_ep1
    root = tmp_path / "sources"
    root.mkdir()
    _write(root / "realization.json", realization, "language realization plan")
    _write(root / "presentation.json", presentation, "presentation plan")
    _write(root / "delivery.json", delivery, "narration delivery plan")
    _write(root / "narration.json", narration, "episode narration plan")
    _write(root / "shots.json", shots, "shot direction plan")
    _write(root / "story.json", story, "episode story plan")
    _write(root / "export.json", export, "render export")
    return root


def _args(root, output):
    """Args."""
    return [
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
    from living_diorama.caption import build_episode_caption_plan_bytes

    root = _write_all_sources(tmp_path, sources_ep1)
    output = tmp_path / "caption_plan.json"
    build_caption_plan.main(_args(root, output))
    realization, presentation, *_ = sources_ep1
    expected = build_episode_caption_plan_bytes(realization, presentation)
    assert output.read_bytes() == expected


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
