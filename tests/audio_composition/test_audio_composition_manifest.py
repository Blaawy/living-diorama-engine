"""Building an Episode Audio Composition Manifest from measured composition results."""

import pytest

from living_diorama.audio_composition.audio_composition_manifest import (
    build_episode_audio_composition_manifest_bytes,
    build_episode_audio_composition_manifest_document,
)
from living_diorama.persistence.json_codec import loads_canonical


def _audio_result(audio_track_plan) -> dict:
    """Audio result."""
    total = audio_track_plan["clock"]["audio_samples_total"]
    return {
        "audio_samples": total,
        "bytes": 44 + total * 2,
        "channels": 1,
        "sample_rate_hz": 24000,
        "sha256": "a" * 64,
    }


def _spans(audio_track_plan) -> dict:
    """Spans."""
    return {
        position: {"pcm_sha256": "b" * 64}
        for position in range(1, len(audio_track_plan["speech"]) + 1)
    }


def test_builds_valid_manifest_ep1(audio_track_plan_ep1) -> None:
    """Builds valid manifest ep1."""
    document = build_episode_audio_composition_manifest_document(
        audio_track_plan=audio_track_plan_ep1,
        audio=_audio_result(audio_track_plan_ep1),
        spans=_spans(audio_track_plan_ep1),
    )
    assert document["format"] == "living_diorama_episode_audio_composition_manifest"
    assert document["schema_version"] == 1
    assert len(document["spans"]) == 3


def test_source_restates_plan_voice_manifest_sha256(audio_track_plan_ep1) -> None:
    """Source restates plan voice manifest SHA256."""
    document = build_episode_audio_composition_manifest_document(
        audio_track_plan=audio_track_plan_ep1,
        audio=_audio_result(audio_track_plan_ep1),
        spans=_spans(audio_track_plan_ep1),
    )
    assert (
        document["source"]["voice_manifest_sha256"]
        == audio_track_plan_ep1["source"]["voice_manifest_sha256"]
    )


def test_span_identities_restated_from_plan(audio_track_plan_ep1) -> None:
    """Span identities restated from plan."""
    document = build_episode_audio_composition_manifest_document(
        audio_track_plan=audio_track_plan_ep1,
        audio=_audio_result(audio_track_plan_ep1),
        spans=_spans(audio_track_plan_ep1),
    )
    for span, plan_span in zip(document["spans"], audio_track_plan_ep1["speech"], strict=True):
        assert span["speech_id"] == plan_span["speech_id"]
        assert span["voice_unit_id"] == plan_span["voice_unit_id"]
        assert span["start_sample"] == plan_span["start_sample"]
        assert span["speech_samples"] == plan_span["speech_samples"]


def test_silence_samples_total_computed(audio_track_plan_ep1) -> None:
    """Silence samples total computed."""
    audio = _audio_result(audio_track_plan_ep1)
    document = build_episode_audio_composition_manifest_document(
        audio_track_plan=audio_track_plan_ep1, audio=audio, spans=_spans(audio_track_plan_ep1)
    )
    speech_total = sum(span["speech_samples"] for span in document["spans"])
    assert (
        document["completeness"]["silence_samples_total"] == audio["audio_samples"] - speech_total
    )


def test_audio_file_field_is_positional(audio_track_plan_ep1) -> None:
    """Audio file field is positional."""
    document = build_episode_audio_composition_manifest_document(
        audio_track_plan=audio_track_plan_ep1,
        audio=_audio_result(audio_track_plan_ep1),
        spans=_spans(audio_track_plan_ep1),
    )
    assert document["audio"]["file"] == "audio/episode_audio.wav"


def test_refuses_missing_span_result(audio_track_plan_ep1) -> None:
    """Refuses missing span result."""
    spans = _spans(audio_track_plan_ep1)
    del spans[1]
    with pytest.raises(ValueError):
        build_episode_audio_composition_manifest_document(
            audio_track_plan=audio_track_plan_ep1,
            audio=_audio_result(audio_track_plan_ep1),
            spans=spans,
        )


def test_refuses_extra_span_position(audio_track_plan_ep1) -> None:
    """Refuses extra span position."""
    spans = _spans(audio_track_plan_ep1)
    spans[999] = {"pcm_sha256": "c" * 64}
    with pytest.raises(ValueError):
        build_episode_audio_composition_manifest_document(
            audio_track_plan=audio_track_plan_ep1,
            audio=_audio_result(audio_track_plan_ep1),
            spans=spans,
        )


def test_refuses_wrong_span_result_keys(audio_track_plan_ep1) -> None:
    """Refuses wrong span result keys."""
    spans = _spans(audio_track_plan_ep1)
    spans[1] = {"pcm_sha256": "c" * 64, "extra": 1}
    with pytest.raises(ValueError):
        build_episode_audio_composition_manifest_document(
            audio_track_plan=audio_track_plan_ep1,
            audio=_audio_result(audio_track_plan_ep1),
            spans=spans,
        )


def test_refuses_wrong_audio_result_keys(audio_track_plan_ep1) -> None:
    """Refuses wrong audio result keys."""
    audio = _audio_result(audio_track_plan_ep1)
    audio["extra"] = 1
    with pytest.raises(ValueError):
        build_episode_audio_composition_manifest_document(
            audio_track_plan=audio_track_plan_ep1, audio=audio, spans=_spans(audio_track_plan_ep1)
        )


def test_refuses_non_dict_audio(audio_track_plan_ep1) -> None:
    """Refuses non dict audio."""
    with pytest.raises(TypeError):
        build_episode_audio_composition_manifest_document(
            audio_track_plan=audio_track_plan_ep1, audio=[], spans=_spans(audio_track_plan_ep1)
        )


def test_refuses_non_dict_spans(audio_track_plan_ep1) -> None:
    """Refuses non dict spans."""
    with pytest.raises(TypeError):
        build_episode_audio_composition_manifest_document(
            audio_track_plan=audio_track_plan_ep1,
            audio=_audio_result(audio_track_plan_ep1),
            spans=[],
        )


def test_bytes_round_trip_through_canonical_codec(audio_track_plan_ep1) -> None:
    """Bytes round trip through canonical codec."""
    payload = build_episode_audio_composition_manifest_bytes(
        audio_track_plan=audio_track_plan_ep1,
        audio=_audio_result(audio_track_plan_ep1),
        spans=_spans(audio_track_plan_ep1),
    )
    document = loads_canonical(payload, "audio composition manifest")
    assert document["format"] == "living_diorama_episode_audio_composition_manifest"
