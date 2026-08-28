"""Standalone validation of the Episode Audio Composition Manifest V1 envelope."""

import pytest

from living_diorama.audio_composition.audio_composition_manifest import (
    build_episode_audio_composition_manifest_document,
)
from living_diorama.audio_composition.audio_composition_schema_v1 import (
    validate_episode_audio_composition_manifest,
)


def _valid_manifest(audio_track_plan_ep1, sha_prefix: str = "a") -> dict:
    """Valid manifest."""
    spans: dict[int, dict[str, object]] = {}
    speech = audio_track_plan_ep1["speech"]
    for position, _record in enumerate(speech, start=1):
        digest = (sha_prefix * 64)[:64]
        spans[position] = {"pcm_sha256": digest}
    audio_samples_total = audio_track_plan_ep1["clock"]["audio_samples_total"]
    audio = {
        "audio_samples": audio_samples_total,
        "bytes": 44 + audio_samples_total * 2,
        "channels": 1,
        "sample_rate_hz": 24000,
        "sha256": ("b" * 64),
    }
    return build_episode_audio_composition_manifest_document(
        audio_track_plan=audio_track_plan_ep1, audio=audio, spans=spans
    )


def test_valid_manifest_round_trips(audio_track_plan_ep1) -> None:
    """Valid manifest round trips."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    validated = validate_episode_audio_composition_manifest(manifest)
    assert validated == manifest


def test_top_level_missing_key_refused(audio_track_plan_ep1) -> None:
    """Top level missing key refused."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    del manifest["audio"]
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_top_level_extra_key_refused(audio_track_plan_ep1) -> None:
    """Top level extra key refused."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["extra"] = 1
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_no_policy_field_present(audio_track_plan_ep1) -> None:
    """No policy field present."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    assert "policy" not in manifest


def test_wrong_format_refused(audio_track_plan_ep1) -> None:
    """Wrong format refused."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["format"] = "wrong"
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_wrong_schema_version_refused(audio_track_plan_ep1) -> None:
    """Wrong schema version refused."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["schema_version"] = 2
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_source_has_exactly_eight_keys(audio_track_plan_ep1) -> None:
    """Source has exactly eight keys."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    assert set(manifest["source"].keys()) == {
        "audio_track_plan_sha256",
        "episode",
        "mode",
        "presentation_plan_sha256",
        "presentation_schema_version",
        "previous_episode",
        "voice_manifest_sha256",
        "voice_manifest_schema_version",
    }


def test_source_missing_key_refused(audio_track_plan_ep1) -> None:
    """Source missing key refused."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    del manifest["source"]["mode"]
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_source_bad_hash_refused(audio_track_plan_ep1) -> None:
    """Source bad hash refused."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["source"]["audio_track_plan_sha256"] = "not-a-hash"
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_baseline_requires_null_previous_episode(audio_track_plan_ep0) -> None:
    """Baseline requires null previous episode."""
    manifest = _valid_manifest(audio_track_plan_ep0)
    assert manifest["source"]["previous_episode"] is None
    manifest["source"]["previous_episode"] = 0
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_transition_requires_direct_succession(audio_track_plan_ep1) -> None:
    """Transition requires direct succession."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["source"]["previous_episode"] = 5
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_audio_keys_exact(audio_track_plan_ep1) -> None:
    """Audio keys exact."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    assert set(manifest["audio"].keys()) == {
        "audio_samples",
        "bytes",
        "channels",
        "file",
        "sample_rate_hz",
        "sha256",
    }


def test_audio_file_is_positional(audio_track_plan_ep1) -> None:
    """Audio file is positional."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    assert manifest["audio"]["file"] == "audio/episode_audio.wav"


def test_audio_bytes_must_equal_header_plus_samples(audio_track_plan_ep1) -> None:
    """Audio bytes must equal header plus samples."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["audio"]["bytes"] -= 1
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_audio_sample_rate_must_be_positive(audio_track_plan_ep1) -> None:
    """Audio sample rate must be positive."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["audio"]["sample_rate_hz"] = 0
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_audio_channels_must_be_positive(audio_track_plan_ep1) -> None:
    """Audio channels must be positive."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["audio"]["channels"] = 0
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_span_keys_exact(audio_track_plan_ep1) -> None:
    """Span keys exact."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    for span in manifest["spans"]:
        assert set(span.keys()) == {
            "pcm_sha256",
            "speech_id",
            "speech_samples",
            "start_sample",
            "voice_unit_id",
        }


def test_spans_must_not_be_empty(audio_track_plan_ep1) -> None:
    """Spans must not be empty."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["spans"] = []
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_span_speech_id_must_be_positional(audio_track_plan_ep1) -> None:
    """Span speech ID must be positional."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["spans"][0]["speech_id"] = "speech_9999"
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_span_voice_unit_id_must_be_positional(audio_track_plan_ep1) -> None:
    """Span voice unit ID must be positional."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["spans"][0]["voice_unit_id"] = "voice_unit_9999"
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_span_speech_samples_must_be_positive(audio_track_plan_ep1) -> None:
    """Span speech samples must be positive."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["spans"][0]["speech_samples"] = 0
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_span_containment_enforced(audio_track_plan_ep1) -> None:
    """Span containment enforced."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["spans"][-1]["speech_samples"] = manifest["audio"]["audio_samples"] * 10
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_span_overlap_refused(audio_track_plan_ep1) -> None:
    """Span overlap refused."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    if len(manifest["spans"]) < 2:
        pytest.skip("episode has only one span")
    manifest["spans"][1]["start_sample"] = manifest["spans"][0]["start_sample"]
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_span_bad_pcm_sha256_refused(audio_track_plan_ep1) -> None:
    """Span bad PCM SHA256 refused."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["spans"][0]["pcm_sha256"] = "short"
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_completeness_keys_exact(audio_track_plan_ep1) -> None:
    """Completeness keys exact."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    assert set(manifest["completeness"].keys()) == {
        "complete",
        "silence_samples_total",
        "speech_spans_composed",
        "speech_spans_expected",
    }


def test_completeness_expected_matches_len(audio_track_plan_ep1) -> None:
    """Completeness expected matches len."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["completeness"]["speech_spans_expected"] += 1
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_completeness_composed_matches_len(audio_track_plan_ep1) -> None:
    """Completeness composed matches len."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["completeness"]["speech_spans_composed"] += 1
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_completeness_silence_recomputed(audio_track_plan_ep1) -> None:
    """Completeness silence recomputed."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["completeness"]["silence_samples_total"] += 1
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_completeness_complete_must_match_derived(audio_track_plan_ep1) -> None:
    """Completeness complete must match derived."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["completeness"]["complete"] = False
    with pytest.raises(ValueError):
        validate_episode_audio_composition_manifest(manifest)


def test_wrong_type_document_refused() -> None:
    """Wrong type document refused."""
    with pytest.raises(TypeError):
        validate_episode_audio_composition_manifest([])


def test_wrong_type_source_refused(audio_track_plan_ep1) -> None:
    """Wrong type source refused."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["source"] = []
    with pytest.raises(TypeError):
        validate_episode_audio_composition_manifest(manifest)
