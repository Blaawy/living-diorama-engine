"""Standalone validation of the Episode Audio Track Plan V1 envelope."""

import copy
from typing import Any

import pytest

from living_diorama.audio_track.audio_track_planner import build_episode_audio_track_plan_document
from living_diorama.audio_track.audio_track_schema_v1 import (
    ACCOUNTING_KEYS,
    CLOCK_KEYS,
    SOURCE_KEYS,
    SPEECH_KEYS,
    TOP_LEVEL_KEYS,
    validate_episode_audio_track_plan,
)


@pytest.fixture
def plan_ep1(
    voice_manifest_ep1: dict[str, Any], presentation_ep1: dict[str, Any]
) -> dict[str, Any]:
    """The audio track plan derived from episode 1's voice manifest and presentation plan."""
    return build_episode_audio_track_plan_document(voice_manifest_ep1, presentation_ep1)


def test_every_canonical_plan_validates(plan_ep1: dict[str, Any]) -> None:
    """Every canonical plan validates."""
    assert validate_episode_audio_track_plan(plan_ep1) == plan_ep1


def test_a_non_dict_document_is_refused() -> None:
    """A non-dict document is refused."""
    with pytest.raises(TypeError):
        validate_episode_audio_track_plan([])


@pytest.mark.parametrize("key", sorted(TOP_LEVEL_KEYS))
def test_a_missing_top_level_key_is_refused(plan_ep1: dict[str, Any], key: str) -> None:
    """A missing top-level key is refused."""
    document = dict(plan_ep1)
    del document[key]
    with pytest.raises(ValueError, match="missing"):
        validate_episode_audio_track_plan(document)


def test_an_extra_top_level_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An extra top-level key is refused."""
    document = {**plan_ep1, "extra": True}
    with pytest.raises(ValueError, match="unexpected"):
        validate_episode_audio_track_plan(document)


def test_a_wrong_format_tag_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A wrong format tag is refused."""
    document = {**plan_ep1, "format": "wrong"}
    with pytest.raises(ValueError, match="format"):
        validate_episode_audio_track_plan(document)


def test_a_wrong_policy_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A wrong policy is refused."""
    document = {**plan_ep1, "policy": "wrong_policy_v1"}
    with pytest.raises(ValueError, match="policy"):
        validate_episode_audio_track_plan(document)


def test_an_unsupported_schema_version_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An unsupported schema version is refused."""
    document = {**plan_ep1, "schema_version": 2}
    with pytest.raises(ValueError, match="schema version"):
        validate_episode_audio_track_plan(document)


@pytest.mark.parametrize("key", sorted(SOURCE_KEYS))
def test_a_missing_source_key_is_refused(plan_ep1: dict[str, Any], key: str) -> None:
    """A missing source key is refused."""
    source = dict(plan_ep1["source"])
    del source[key]
    document = {**plan_ep1, "source": source}
    with pytest.raises(ValueError, match="missing"):
        validate_episode_audio_track_plan(document)


def test_an_extra_source_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An extra source key is refused."""
    source = {**plan_ep1["source"], "extra": "x"}
    document = {**plan_ep1, "source": source}
    with pytest.raises(ValueError, match="unexpected"):
        validate_episode_audio_track_plan(document)


def test_a_malformed_digest_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A malformed digest is refused."""
    source = {**plan_ep1["source"], "voice_manifest_sha256": "not-a-digest"}
    document = {**plan_ep1, "source": source}
    with pytest.raises(ValueError, match="hexadecimal"):
        validate_episode_audio_track_plan(document)


def test_a_transition_joining_nonconsecutive_episodes_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A transition joining nonconsecutive episodes is refused."""
    source = {**plan_ep1["source"], "previous_episode": 99}
    document = {**plan_ep1, "source": source}
    with pytest.raises(ValueError, match="directly follow"):
        validate_episode_audio_track_plan(document)


@pytest.mark.parametrize("key", sorted(CLOCK_KEYS))
def test_a_missing_clock_key_is_refused(plan_ep1: dict[str, Any], key: str) -> None:
    """A missing clock key is refused."""
    clock = dict(plan_ep1["clock"])
    del clock[key]
    document = {**plan_ep1, "clock": clock}
    with pytest.raises(ValueError, match="missing"):
        validate_episode_audio_track_plan(document)


def test_a_wrong_samples_per_presentation_frame_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A wrong samples_per_presentation_frame is refused."""
    clock = {**plan_ep1["clock"], "samples_per_presentation_frame": 999}
    document = {**plan_ep1, "clock": clock}
    with pytest.raises(ValueError, match="resolves to"):
        validate_episode_audio_track_plan(document)


def test_a_wrong_audio_samples_total_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A wrong audio_samples_total is refused."""
    clock = {**plan_ep1["clock"], "audio_samples_total": 1}
    document = {**plan_ep1, "clock": clock}
    with pytest.raises(ValueError):
        validate_episode_audio_track_plan(document)


def test_no_speech_records_at_all_is_refused(plan_ep1: dict[str, Any]) -> None:
    """No speech records at all is refused."""
    document = {**plan_ep1, "speech": []}
    with pytest.raises(ValueError, match="empty"):
        validate_episode_audio_track_plan(document)


@pytest.mark.parametrize("key", sorted(SPEECH_KEYS))
def test_a_speech_record_missing_a_key_is_refused(plan_ep1: dict[str, Any], key: str) -> None:
    """A speech record missing a key is refused."""
    speech = copy.deepcopy(plan_ep1["speech"])
    del speech[0][key]
    document = {**plan_ep1, "speech": speech}
    with pytest.raises(ValueError, match="missing"):
        validate_episode_audio_track_plan(document)


def test_a_speech_record_with_an_extra_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A speech record with an extra key is refused."""
    speech = copy.deepcopy(plan_ep1["speech"])
    speech[0]["extra"] = "x"
    document = {**plan_ep1, "speech": speech}
    with pytest.raises(ValueError, match="unexpected"):
        validate_episode_audio_track_plan(document)


def test_a_wrong_speech_id_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A wrong speech_id is refused."""
    speech = copy.deepcopy(plan_ep1["speech"])
    speech[0]["speech_id"] = "speech_9999"
    document = {**plan_ep1, "speech": speech}
    with pytest.raises(ValueError, match="positional"):
        validate_episode_audio_track_plan(document)


def test_an_onset_not_on_a_frame_boundary_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An onset not on a presentation-frame boundary is refused."""
    speech = copy.deepcopy(plan_ep1["speech"])
    speech[0]["start_sample"] += 1
    document = {**plan_ep1, "speech": speech}
    with pytest.raises(ValueError, match="boundary"):
        validate_episode_audio_track_plan(document)


def test_a_bool_start_sample_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A bool start_sample is refused."""
    speech = copy.deepcopy(plan_ep1["speech"])
    speech[0]["start_sample"] = True
    document = {**plan_ep1, "speech": speech}
    with pytest.raises(TypeError):
        validate_episode_audio_track_plan(document)


def test_a_float_speech_samples_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A float speech_samples is refused."""
    speech = copy.deepcopy(plan_ep1["speech"])
    speech[0]["speech_samples"] = float(speech[0]["speech_samples"])
    document = {**plan_ep1, "speech": speech}
    with pytest.raises(TypeError):
        validate_episode_audio_track_plan(document)


def test_a_zero_speech_samples_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Zero speech_samples is refused."""
    speech = copy.deepcopy(plan_ep1["speech"])
    speech[0]["speech_samples"] = 0
    document = {**plan_ep1, "speech": speech}
    with pytest.raises(ValueError):
        validate_episode_audio_track_plan(document)


def test_a_span_escaping_the_track_total_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A span escaping the track's own total is refused."""
    speech = copy.deepcopy(plan_ep1["speech"])
    speech[-1]["speech_samples"] += plan_ep1["clock"]["audio_samples_total"]
    document = {**plan_ep1, "speech": speech}
    with pytest.raises(ValueError, match="beyond"):
        validate_episode_audio_track_plan(document)


def test_an_overlapping_span_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An overlapping span is refused."""
    speech = copy.deepcopy(plan_ep1["speech"])
    if len(speech) < 2:
        pytest.skip("needs at least two units")
    speech[1]["start_sample"] = speech[0]["start_sample"]
    document = {**plan_ep1, "speech": speech}
    with pytest.raises(ValueError, match="overlap"):
        validate_episode_audio_track_plan(document)


def test_reordered_speech_records_are_refused(plan_ep1: dict[str, Any]) -> None:
    """Reordered speech records are refused."""
    speech = list(reversed(copy.deepcopy(plan_ep1["speech"])))
    document = {**plan_ep1, "speech": speech}
    with pytest.raises(ValueError):
        validate_episode_audio_track_plan(document)


@pytest.mark.parametrize("key", sorted(ACCOUNTING_KEYS))
def test_a_missing_accounting_key_is_refused(plan_ep1: dict[str, Any], key: str) -> None:
    """A missing accounting key is refused."""
    accounting = dict(plan_ep1["accounting"])
    del accounting[key]
    document = {**plan_ep1, "accounting": accounting}
    with pytest.raises(ValueError, match="missing"):
        validate_episode_audio_track_plan(document)


def test_a_wrong_silence_samples_total_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A wrong silence_samples_total is refused."""
    accounting = {**plan_ep1["accounting"], "silence_samples_total": 1}
    document = {**plan_ep1, "accounting": accounting}
    with pytest.raises(ValueError):
        validate_episode_audio_track_plan(document)
