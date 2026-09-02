"""The compose_episode_audio CLI.

The audited-directory precondition and parent-indirection entry.
"""

import json

import pytest

from living_diorama.cli import compose_episode_audio
from living_diorama.persistence.json_codec import dumps_canonical

from .conftest import build_manifest, write_voice_directory


def _write(path, document, description) -> None:
    """Write."""
    path.write_bytes(dumps_canonical(document, description))


def _write_all_sources(tmp_path, sources_ep1, voice_plan_ep1):
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


def _write_audio_track_plan(tmp_path, audio_track_plan_ep1):
    """Write audio track plan."""
    path = tmp_path / "audio_track_plan.json"
    _write(path, audio_track_plan_ep1, "audio track plan")
    return path


def test_cli_end_to_end_success(
    tmp_path, sources_ep1, voice_plan_ep1, audio_track_plan_ep1, voice_directory_ep1, capsys
) -> None:
    """CLI end to end success."""
    root = _write_all_sources(tmp_path, sources_ep1, voice_plan_ep1)
    plan_path = _write_audio_track_plan(tmp_path, audio_track_plan_ep1)
    output_root = tmp_path / "audio_tracks"
    exit_code = compose_episode_audio.main(
        [
            "--audio-track",
            str(plan_path),
            "--voice-dir",
            str(voice_directory_ep1),
            "--presentation",
            str(root / "presentation.json"),
            "--realization",
            str(root / "realization.json"),
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
            "--output-root",
            str(output_root),
        ]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["episode"] == 1
    assert summary["speech_spans_total"] == 3


def test_cli_indirect_output_root_refuses(
    tmp_path, sources_ep1, voice_plan_ep1, audio_track_plan_ep1, voice_directory_ep1, capsys
) -> None:
    """CLI indirect output root refuses."""
    root = _write_all_sources(tmp_path, sources_ep1, voice_plan_ep1)
    plan_path = _write_audio_track_plan(tmp_path, audio_track_plan_ep1)
    real_root = tmp_path / "real_root"
    real_root.mkdir()
    link_root = tmp_path / "link_root"
    try:
        link_root.symlink_to(real_root, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform/account")
    exit_code = compose_episode_audio.main(
        [
            "--audio-track",
            str(plan_path),
            "--voice-dir",
            str(voice_directory_ep1),
            "--presentation",
            str(root / "presentation.json"),
            "--realization",
            str(root / "realization.json"),
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
            "--output-root",
            str(link_root),
        ]
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "error:" in captured.err
    assert list(real_root.iterdir()) == []


def test_cli_refuses_when_voice_directory_audit_fails(
    tmp_path, sources_ep1, voice_plan_ep1, audio_track_plan_ep1, voice_directory_ep1
) -> None:
    """CLI refuses when voice directory audit fails."""
    root = _write_all_sources(tmp_path, sources_ep1, voice_plan_ep1)
    plan_path = _write_audio_track_plan(tmp_path, audio_track_plan_ep1)
    # Corrupt the voice directory so audit_voice_directory returns problems.
    (voice_directory_ep1 / "episode_voice_manifest.json").unlink()
    exit_code = compose_episode_audio.main(
        [
            "--audio-track",
            str(plan_path),
            "--voice-dir",
            str(voice_directory_ep1),
            "--presentation",
            str(root / "presentation.json"),
            "--realization",
            str(root / "realization.json"),
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
            "--output-root",
            str(tmp_path / "out"),
        ]
    )
    assert exit_code == 1


def test_cli_refuses_missing_input_file(
    tmp_path, sources_ep1, voice_plan_ep1, audio_track_plan_ep1, voice_directory_ep1
) -> None:
    """CLI refuses missing input file."""
    root = _write_all_sources(tmp_path, sources_ep1, voice_plan_ep1)
    plan_path = _write_audio_track_plan(tmp_path, audio_track_plan_ep1)
    exit_code = compose_episode_audio.main(
        [
            "--audio-track",
            str(plan_path),
            "--voice-dir",
            str(voice_directory_ep1),
            "--presentation",
            str(root / "does_not_exist.json"),
            "--realization",
            str(root / "realization.json"),
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
            "--output-root",
            str(tmp_path / "out"),
        ]
    )
    assert exit_code == 1


def _all_args(tmp_path, root, plan_path, voice_directory_ep1, output_root) -> list:
    """All args."""
    return [
        "--audio-track",
        str(plan_path),
        "--voice-dir",
        str(voice_directory_ep1),
        "--presentation",
        str(root / "presentation.json"),
        "--realization",
        str(root / "realization.json"),
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
        "--output-root",
        str(output_root),
    ]


def test_compose_reads_the_audio_track_path_exactly_once_at_runtime(
    tmp_path, sources_ep1, voice_plan_ep1, audio_track_plan_ep1, voice_directory_ep1, monkeypatch
) -> None:
    """``audio_track_path.read_bytes()`` is invoked exactly once during a real ``compose()``."""
    from pathlib import Path

    root = _write_all_sources(tmp_path, sources_ep1, voice_plan_ep1)
    plan_path = _write_audio_track_plan(tmp_path, audio_track_plan_ep1)
    output_root = tmp_path / "audio_tracks"

    real_read_bytes = Path.read_bytes
    counts: dict[str, int] = {}

    def _counting_read_bytes(self, *args, **kwargs):
        if self == plan_path:
            counts[str(self)] = counts.get(str(self), 0) + 1
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", _counting_read_bytes)
    exit_code = compose_episode_audio.main(
        _all_args(tmp_path, root, plan_path, voice_directory_ep1, output_root)
    )
    assert exit_code == 0
    assert counts.get(str(plan_path)) == 1


def test_old_two_observation_race_is_structurally_impossible(
    tmp_path, sources_ep1, voice_plan_ep1, audio_track_plan_ep1, voice_directory_ep1, monkeypatch
) -> None:
    """A second, mutated observation of the plan path is never consulted.

    If ``compose()`` still read the file twice (the withdrawn V1 law), a
    monkeypatch that returns valid bytes on the first call and corrupt bytes
    on every subsequent call would make the second read fail differently
    from the first -- proving a race window exists. With the single-capture
    law, the composition either succeeds cleanly (one read only) or the
    corrupt-second-call branch is never reached at all; either way, the run
    cannot observe two different byte strings for the same path.
    """
    from pathlib import Path

    root = _write_all_sources(tmp_path, sources_ep1, voice_plan_ep1)
    plan_path = _write_audio_track_plan(tmp_path, audio_track_plan_ep1)
    output_root = tmp_path / "audio_tracks"

    real_read_bytes = Path.read_bytes
    call_count = {"n": 0}

    def _mutate_after_first_read(self, *args, **kwargs):
        if self == plan_path:
            call_count["n"] += 1
            if call_count["n"] > 1:
                return b"{not even json, a second read would blow up here}"
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", _mutate_after_first_read)
    exit_code = compose_episode_audio.main(
        _all_args(tmp_path, root, plan_path, voice_directory_ep1, output_root)
    )
    # A second read would have fed the corrupt bytes to loads_canonical and
    # refused with exit 1; the single-capture law means the run genuinely
    # only ever reads the file once, so it succeeds exactly as the
    # unpatched baseline does.
    assert exit_code == 0
    assert call_count["n"] == 1


def test_non_canonical_audio_track_plan_still_refuses(
    tmp_path, sources_ep1, voice_plan_ep1, audio_track_plan_ep1, voice_directory_ep1
) -> None:
    """A non-canonical audio track plan file still refuses, unchanged in observable behavior."""
    import json

    root = _write_all_sources(tmp_path, sources_ep1, voice_plan_ep1)
    plan_path = _write_audio_track_plan(tmp_path, audio_track_plan_ep1)
    reformatted = (json.dumps(audio_track_plan_ep1, sort_keys=False, indent=2) + "\n").encode(
        "utf-8"
    )
    plan_path.write_bytes(reformatted)
    output_root = tmp_path / "audio_tracks"
    exit_code = compose_episode_audio.main(
        _all_args(tmp_path, root, plan_path, voice_directory_ep1, output_root)
    )
    assert exit_code == 1


def test_missing_audio_track_plan_still_refuses(
    tmp_path, sources_ep1, voice_plan_ep1, voice_directory_ep1
) -> None:
    """A missing audio track plan path still refuses with the same exit code as before."""
    root = _write_all_sources(tmp_path, sources_ep1, voice_plan_ep1)
    missing_plan_path = tmp_path / "does_not_exist.json"
    output_root = tmp_path / "audio_tracks"
    exit_code = compose_episode_audio.main(
        _all_args(tmp_path, root, missing_plan_path, voice_directory_ep1, output_root)
    )
    assert exit_code == 1


def test_cli_direct_output_root_verified_no_op(
    tmp_path, sources_ep1, voice_plan_ep1, audio_track_plan_ep1, voice_directory_ep1, capsys
) -> None:
    """CLI direct output root verified no op."""
    root = _write_all_sources(tmp_path, sources_ep1, voice_plan_ep1)
    plan_path = _write_audio_track_plan(tmp_path, audio_track_plan_ep1)
    output_root = tmp_path / "audio_tracks"
    args = [
        "--audio-track",
        str(plan_path),
        "--voice-dir",
        str(voice_directory_ep1),
        "--presentation",
        str(root / "presentation.json"),
        "--realization",
        str(root / "realization.json"),
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
        "--output-root",
        str(output_root),
    ]
    assert compose_episode_audio.main(args) == 0
    capsys.readouterr()
    assert compose_episode_audio.main(args) == 0  # verified no-op, still exit 0


# ---------------------------------------------------------------------------
# The --presentation-profile flag: a real v3 presentation plan end to end
# ---------------------------------------------------------------------------


def _v3_chain(tmp_path, sources_ep1):
    """Build a fully v3-consistent chain; return (v3_sources, v3_track, v3_voice_dir)."""
    from living_diorama.audio_track import build_episode_audio_track_plan_document
    from living_diorama.presentation import build_episode_presentation_plan_document
    from living_diorama.voice import build_episode_voice_plan_document

    realization, _presentation, delivery, narration, shots, story, export = sources_ep1
    v3_presentation = build_episode_presentation_plan_document(
        delivery, narration, realization, presentation_profile="v3"
    )
    v3_voice_plan = build_episode_voice_plan_document(realization, v3_presentation)
    v3_manifest = build_manifest(v3_voice_plan, patterned=True)
    v3_voice_dir = write_voice_directory(
        tmp_path / "voice", v3_voice_plan, v3_manifest, patterned=True
    )
    v3_track = build_episode_audio_track_plan_document(v3_manifest, v3_presentation)
    v3_sources = (realization, v3_presentation, delivery, narration, shots, story, export)
    return v3_sources, v3_track, v3_voice_dir


def test_the_v3_presentation_profile_flag_accepts_a_real_v3_presentation_plan(
    tmp_path, sources_ep1, capsys
) -> None:
    """``--presentation-profile v3`` admits the real frozen, content-sized plan.

    A real V3 presentation plan carries no ``motion_windows``, so under the
    default (v1) derivation the reused Phase 30 gate re-derives V1 bytes and
    refuses; the explicit v3 flag makes the gate re-derive the plan it was
    actually built under, and the composition is published.
    """
    v3_sources, v3_track, v3_voice_dir = _v3_chain(tmp_path, sources_ep1)
    root = _write_all_sources(tmp_path, v3_sources, None)
    plan_path = _write_audio_track_plan(tmp_path, v3_track)
    output_root = tmp_path / "audio_tracks"
    exit_code = compose_episode_audio.main(
        _all_args(tmp_path, root, plan_path, v3_voice_dir, output_root)
        + ["--presentation-profile", "v3"]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["episode"] == 1
    assert summary["speech_spans_total"] == 3


def test_without_the_flag_a_v3_presentation_plan_is_still_refused(
    tmp_path, sources_ep1, capsys
) -> None:
    """Omitting the flag keeps today's refusal of a V3 plan, publishing nothing."""
    v3_sources, v3_track, v3_voice_dir = _v3_chain(tmp_path, sources_ep1)
    root = _write_all_sources(tmp_path, v3_sources, None)
    plan_path = _write_audio_track_plan(tmp_path, v3_track)
    output_root = tmp_path / "audio_tracks"
    exit_code = compose_episode_audio.main(
        _all_args(tmp_path, root, plan_path, v3_voice_dir, output_root)
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "does not equal the deterministic derivation" in captured.err
    assert "Traceback" not in captured.err
    assert not output_root.exists()
