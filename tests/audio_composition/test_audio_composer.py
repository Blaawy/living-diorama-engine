"""Pure composition: interval geometry, splicing, silence, per-span extraction."""

import copy

import pytest

from living_diorama.audio_composition.audio_composer import (
    CompositionRefused,
    compose_episode_audio_bytes,
    pcm_payload_of,
    require_placement_geometry,
    require_silence_complement,
    span_pcm,
)
from living_diorama.voice_execution.speech_audio import canonical_wav_bytes, pcm16_bytes

# ---- require_placement_geometry


def test_geometry_matches_canonical_ep1(audio_track_plan_ep1) -> None:
    """Geometry matches canonical ep1."""
    placements = require_placement_geometry(audio_track_plan_ep1)
    assert placements == ((24000, 24000), (168000, 24000), (528000, 24000))


def test_geometry_matches_canonical_ep2(audio_track_plan_ep2) -> None:
    """Geometry matches canonical ep2."""
    placements = require_placement_geometry(audio_track_plan_ep2)
    assert placements == ((0, 24000), (360000, 24000))


def test_geometry_refuses_overlap_even_when_zero(audio_track_plan_ep1) -> None:
    """Geometry refuses overlap even when zero."""
    plan = copy.deepcopy(audio_track_plan_ep1)
    if len(plan["speech"]) < 2:
        pytest.skip("episode has only one span")
    plan["speech"][1]["start_sample"] = plan["speech"][0]["start_sample"]
    with pytest.raises(CompositionRefused, match="overlap"):
        require_placement_geometry(plan)


def test_geometry_refuses_span_beyond_total(audio_track_plan_ep1) -> None:
    """Geometry refuses span beyond total."""
    plan = copy.deepcopy(audio_track_plan_ep1)
    plan["speech"][-1]["speech_samples"] = plan["clock"]["audio_samples_total"] * 10
    with pytest.raises(CompositionRefused):
        require_placement_geometry(plan)


def test_geometry_refuses_negative_start(audio_track_plan_ep1) -> None:
    """Geometry refuses negative start."""
    plan = copy.deepcopy(audio_track_plan_ep1)
    plan["speech"][0]["start_sample"] = -1
    with pytest.raises(CompositionRefused):
        require_placement_geometry(plan)


def test_geometry_refuses_zero_count(audio_track_plan_ep1) -> None:
    """Geometry refuses zero count."""
    plan = copy.deepcopy(audio_track_plan_ep1)
    plan["speech"][0]["speech_samples"] = 0
    with pytest.raises(CompositionRefused):
        require_placement_geometry(plan)


def test_geometry_refuses_bool_for_start(audio_track_plan_ep1) -> None:
    """Geometry refuses bool for start."""
    plan = copy.deepcopy(audio_track_plan_ep1)
    plan["speech"][0]["start_sample"] = True
    with pytest.raises(TypeError):
        require_placement_geometry(plan)


def test_geometry_refuses_bool_for_count(audio_track_plan_ep1) -> None:
    """Geometry refuses bool for count."""
    plan = copy.deepcopy(audio_track_plan_ep1)
    plan["speech"][0]["speech_samples"] = True
    with pytest.raises(TypeError):
        require_placement_geometry(plan)


def test_geometry_refuses_wrong_plan_type() -> None:
    """Geometry refuses wrong plan type."""
    with pytest.raises(TypeError):
        require_placement_geometry([])


def test_geometry_refuses_non_int_total(audio_track_plan_ep1) -> None:
    """Geometry refuses non int total."""
    plan = copy.deepcopy(audio_track_plan_ep1)
    plan["clock"]["audio_samples_total"] = "many"
    with pytest.raises(TypeError):
        require_placement_geometry(plan)


# ---- pcm_payload_of


def test_pcm_payload_of_strips_header() -> None:
    """PCM payload of strips header."""
    pcm = pcm16_bytes([0.5, -0.5, 0.25], "test")
    wav = canonical_wav_bytes(pcm, sample_rate_hz=24000, channels=1)
    assert pcm_payload_of(wav, expected_samples=3) == pcm


def test_pcm_payload_of_refuses_wrong_length() -> None:
    """PCM payload of refuses wrong length."""
    pcm = pcm16_bytes([0.5, -0.5], "test")
    wav = canonical_wav_bytes(pcm, sample_rate_hz=24000, channels=1)
    with pytest.raises(CompositionRefused):
        pcm_payload_of(wav, expected_samples=3)


def test_pcm_payload_of_refuses_non_positive_samples() -> None:
    """PCM payload of refuses non positive samples."""
    with pytest.raises(CompositionRefused):
        pcm_payload_of(b"\x00" * 44, expected_samples=0)


def test_pcm_payload_of_refuses_wrong_type() -> None:
    """PCM payload of refuses wrong type."""
    with pytest.raises(TypeError):
        pcm_payload_of("not bytes", expected_samples=1)


# ---- compose_episode_audio_bytes


def test_compose_produces_correct_length(audio_track_plan_ep1) -> None:
    """Compose produces correct length."""
    placements = require_placement_geometry(audio_track_plan_ep1)
    payloads = {
        i + 1: pcm16_bytes([0.1] * count, "test") for i, (start, count) in enumerate(placements)
    }
    wav = compose_episode_audio_bytes(
        audio_track_plan=audio_track_plan_ep1, payloads=payloads, sample_rate_hz=24000, channels=1
    )
    expected_total = audio_track_plan_ep1["clock"]["audio_samples_total"]
    assert len(wav) == 44 + expected_total * 2


def test_compose_places_payload_at_correct_offset(audio_track_plan_ep1) -> None:
    """Compose places payload at correct offset."""
    placements = require_placement_geometry(audio_track_plan_ep1)
    payloads = {
        i + 1: pcm16_bytes([0.5] * count, "test") for i, (start, count) in enumerate(placements)
    }
    wav = compose_episode_audio_bytes(
        audio_track_plan=audio_track_plan_ep1, payloads=payloads, sample_rate_hz=24000, channels=1
    )
    pcm = pcm_payload_of(wav, expected_samples=audio_track_plan_ep1["clock"]["audio_samples_total"])
    start, count = placements[0]
    expected_span = pcm16_bytes([0.5] * count, "test")
    assert pcm[start * 2 : start * 2 + count * 2] == expected_span


def test_compose_fills_silence_with_zero(audio_track_plan_ep1) -> None:
    """Compose fills silence with zero."""
    placements = require_placement_geometry(audio_track_plan_ep1)
    payloads = {
        i + 1: pcm16_bytes([0.5] * count, "test") for i, (start, count) in enumerate(placements)
    }
    wav = compose_episode_audio_bytes(
        audio_track_plan=audio_track_plan_ep1, payloads=payloads, sample_rate_hz=24000, channels=1
    )
    pcm = pcm_payload_of(wav, expected_samples=audio_track_plan_ep1["clock"]["audio_samples_total"])
    assert pcm[0:100] == b"\x00" * 100  # before the first hold, silence


def test_compose_refuses_missing_payload(audio_track_plan_ep1) -> None:
    """Compose refuses missing payload."""
    with pytest.raises(CompositionRefused):
        compose_episode_audio_bytes(
            audio_track_plan=audio_track_plan_ep1, payloads={}, sample_rate_hz=24000, channels=1
        )


def test_compose_refuses_wrong_payload_length(audio_track_plan_ep1) -> None:
    """Compose refuses wrong payload length."""
    placements = require_placement_geometry(audio_track_plan_ep1)
    payloads = {
        i + 1: pcm16_bytes([0.1] * (count - 1), "test")
        for i, (start, count) in enumerate(placements)
    }
    with pytest.raises(CompositionRefused):
        compose_episode_audio_bytes(
            audio_track_plan=audio_track_plan_ep1,
            payloads=payloads,
            sample_rate_hz=24000,
            channels=1,
        )


def test_compose_accepts_all_zero_lawful_silence(audio_track_plan_ep1) -> None:
    """All-zero speech is lawful content, not confused with structural silence."""
    placements = require_placement_geometry(audio_track_plan_ep1)
    payloads = {
        i + 1: pcm16_bytes([0.0] * count, "test") for i, (start, count) in enumerate(placements)
    }
    wav = compose_episode_audio_bytes(
        audio_track_plan=audio_track_plan_ep1, payloads=payloads, sample_rate_hz=24000, channels=1
    )
    total = audio_track_plan_ep1["clock"]["audio_samples_total"]
    assert len(wav) == 44 + total * 2


def test_compose_zero_destination_check_is_unreachable_when_geometry_holds(
    audio_track_plan_ep1,
) -> None:
    """The non-zero-destination check is unreachable when geometry already holds.

    It is defence in depth for a state ``require_placement_geometry`` already
    refuses -- proven unreachable here because every valid plan passes
    geometry first, exactly the "asserted but cannot fire" shape Phase 23's
    own known limitations document.
    """
    placements = require_placement_geometry(audio_track_plan_ep1)
    payloads = {
        i + 1: pcm16_bytes([0.1] * count, "test") for i, (start, count) in enumerate(placements)
    }
    # No CompositionRefused about "unexpected non-zero destination content"
    # can occur here: geometry already proved every span is contained and
    # non-overlapping, so the buffer at each span's offset is still zero
    # when that span's payload is spliced in.
    wav = compose_episode_audio_bytes(
        audio_track_plan=audio_track_plan_ep1, payloads=payloads, sample_rate_hz=24000, channels=1
    )
    assert len(wav) == 44 + audio_track_plan_ep1["clock"]["audio_samples_total"] * 2


def test_compose_deterministic_across_two_calls(audio_track_plan_ep1) -> None:
    """Compose deterministic across two calls."""
    placements = require_placement_geometry(audio_track_plan_ep1)
    payloads = {
        i + 1: pcm16_bytes([0.3] * count, "test") for i, (start, count) in enumerate(placements)
    }
    wav1 = compose_episode_audio_bytes(
        audio_track_plan=audio_track_plan_ep1, payloads=payloads, sample_rate_hz=24000, channels=1
    )
    wav2 = compose_episode_audio_bytes(
        audio_track_plan=audio_track_plan_ep1, payloads=payloads, sample_rate_hz=24000, channels=1
    )
    assert wav1 == wav2


# ---- span_pcm


def test_span_pcm_extracts_correct_slice() -> None:
    """Span PCM extracts correct slice."""
    pcm = pcm16_bytes([float(i) / 100 for i in range(-50, 50)], "test")
    result = span_pcm(pcm, start_sample=10, speech_samples=5)
    assert result == pcm[20:30]


def test_span_pcm_refuses_escaping_interval() -> None:
    """Span PCM refuses escaping interval."""
    pcm = pcm16_bytes([0.1] * 10, "test")
    with pytest.raises(CompositionRefused):
        span_pcm(pcm, start_sample=8, speech_samples=5)


def test_span_pcm_refuses_wrong_type() -> None:
    """Span PCM refuses wrong type."""
    with pytest.raises(TypeError):
        span_pcm("not bytes", start_sample=0, speech_samples=1)


# ---- require_silence_complement


def test_silence_complement_accepts_true_silence() -> None:
    """Silence complement accepts true silence."""
    pcm = pcm16_bytes([0.5, 0.5] + [0.0] * 8, "test")
    require_silence_complement(pcm, [(0, 2)])


def test_silence_complement_refuses_non_zero_outside() -> None:
    """Silence complement refuses non zero outside."""
    pcm = pcm16_bytes([0.5, 0.5, 0.3] + [0.0] * 7, "test")
    with pytest.raises(CompositionRefused):
        require_silence_complement(pcm, [(0, 2)])


def test_silence_complement_refuses_wrong_type() -> None:
    """Silence complement refuses wrong type."""
    with pytest.raises(TypeError):
        require_silence_complement("not bytes", [])


def test_silence_complement_accepts_fully_covered_track() -> None:
    """Silence complement accepts fully covered track."""
    pcm = pcm16_bytes([0.1, 0.2, 0.3], "test")
    require_silence_complement(pcm, [(0, 3)])
