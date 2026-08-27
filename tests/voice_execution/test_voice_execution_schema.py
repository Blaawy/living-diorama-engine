"""Standalone validation of the Episode Voice Manifest V1 envelope."""

import copy
import hashlib
from typing import Any

import pytest

from living_diorama.voice_execution import build_episode_voice_manifest_document
from living_diorama.voice_execution.voice_execution_schema_v1 import (
    COMPLETENESS_KEYS,
    ENVIRONMENT_KEYS,
    SOURCE_KEYS,
    TOP_LEVEL_KEYS,
    VOICE_UNIT_KEYS,
    validate_episode_voice_manifest,
)


def test_every_canonical_manifest_validates(
    manifest_ep0: dict[str, Any], manifest_ep1: dict[str, Any], manifest_ep2: dict[str, Any]
) -> None:
    """Every canonical manifest validates."""
    for manifest in (manifest_ep0, manifest_ep1, manifest_ep2):
        assert validate_episode_voice_manifest(manifest) == manifest


def test_a_non_dict_document_is_refused() -> None:
    """A non-dict document is refused."""
    with pytest.raises(TypeError):
        validate_episode_voice_manifest([])


@pytest.mark.parametrize("key", sorted(TOP_LEVEL_KEYS))
def test_a_missing_top_level_key_is_refused(manifest_ep1: dict[str, Any], key: str) -> None:
    """A missing top-level key is refused."""
    document = dict(manifest_ep1)
    del document[key]
    with pytest.raises(ValueError, match="missing"):
        validate_episode_voice_manifest(document)


def test_an_extra_top_level_key_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """An extra top-level key is refused."""
    document = {**manifest_ep1, "extra": True}
    with pytest.raises(ValueError, match="unexpected"):
        validate_episode_voice_manifest(document)


def test_a_wrong_format_tag_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """A wrong format tag is refused."""
    document = {**manifest_ep1, "format": "wrong"}
    with pytest.raises(ValueError, match="format"):
        validate_episode_voice_manifest(document)


def test_an_unsupported_schema_version_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """An unsupported schema version is refused."""
    document = {**manifest_ep1, "schema_version": 2}
    with pytest.raises(ValueError, match="schema version"):
        validate_episode_voice_manifest(document)


@pytest.mark.parametrize("key", sorted(SOURCE_KEYS))
def test_a_missing_source_key_is_refused(manifest_ep1: dict[str, Any], key: str) -> None:
    """A missing source key is refused."""
    source = dict(manifest_ep1["source"])
    del source[key]
    document = {**manifest_ep1, "source": source}
    with pytest.raises(ValueError, match="missing"):
        validate_episode_voice_manifest(document)


def test_an_extra_source_key_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """An extra source key is refused."""
    source = {**manifest_ep1["source"], "extra": "x"}
    document = {**manifest_ep1, "source": source}
    with pytest.raises(ValueError, match="unexpected"):
        validate_episode_voice_manifest(document)


def test_a_deleted_v1_aggregate_fit_key_is_never_a_valid_key() -> None:
    """The deleted V1 aggregate-fit flag is never a valid key anywhere in this contract."""
    assert "fit_all" not in SOURCE_KEYS
    assert "fit_all" not in COMPLETENESS_KEYS
    assert "fit_all" not in VOICE_UNIT_KEYS


def test_a_malformed_digest_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """A malformed digest is refused."""
    source = {**manifest_ep1["source"], "voice_plan_sha256": "not-a-digest"}
    document = {**manifest_ep1, "source": source}
    with pytest.raises(ValueError, match="hexadecimal"):
        validate_episode_voice_manifest(document)


def test_a_baseline_with_a_previous_episode_is_refused(manifest_ep0: dict[str, Any]) -> None:
    """A baseline with a previous episode is refused."""
    source = {**manifest_ep0["source"], "previous_episode": 0}
    document = {**manifest_ep0, "source": source}
    with pytest.raises(ValueError):
        validate_episode_voice_manifest(document)


def test_a_baseline_describing_a_nonzero_episode_is_refused(manifest_ep0: dict[str, Any]) -> None:
    """A baseline describing a nonzero episode is refused."""
    source = {**manifest_ep0["source"], "episode": 1}
    document = {**manifest_ep0, "source": source}
    with pytest.raises(ValueError, match="baseline"):
        validate_episode_voice_manifest(document)


def test_a_transition_with_no_previous_episode_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """A transition with no previous episode is refused."""
    source = {**manifest_ep1["source"], "previous_episode": None}
    document = {**manifest_ep1, "source": source}
    with pytest.raises(TypeError):
        validate_episode_voice_manifest(document)


def test_a_transition_joining_nonconsecutive_episodes_is_refused(
    manifest_ep2: dict[str, Any],
) -> None:
    """A transition joining nonconsecutive episodes is refused."""
    source = {**manifest_ep2["source"], "previous_episode": 0}
    document = {**manifest_ep2, "source": source}
    with pytest.raises(ValueError, match="directly follow"):
        validate_episode_voice_manifest(document)


@pytest.mark.parametrize("key", sorted(ENVIRONMENT_KEYS))
def test_a_missing_environment_key_is_refused(manifest_ep1: dict[str, Any], key: str) -> None:
    """A missing environment key is refused."""
    environment = dict(manifest_ep1["environment"])
    del environment[key]
    document = {**manifest_ep1, "environment": environment}
    with pytest.raises(ValueError, match="missing"):
        validate_episode_voice_manifest(document)


def test_an_extra_environment_key_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """An extra environment key is refused."""
    environment = {**manifest_ep1["environment"], "extra": "x"}
    document = {**manifest_ep1, "environment": environment}
    with pytest.raises(ValueError, match="unexpected"):
        validate_episode_voice_manifest(document)


def test_a_non_cpu_device_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """A non-cpu device is refused."""
    environment = {**manifest_ep1["environment"], "device": "cuda"}
    document = {**manifest_ep1, "environment": environment}
    with pytest.raises(ValueError, match="cpu"):
        validate_episode_voice_manifest(document)


def test_a_wrong_spacy_model_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """A wrong spaCy model name is refused."""
    environment = {**manifest_ep1["environment"], "spacy_model": "en_core_web_trf"}
    document = {**manifest_ep1, "environment": environment}
    with pytest.raises(ValueError, match="en_core_web_sm"):
        validate_episode_voice_manifest(document)


def test_a_non_str_environment_value_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """A non-str environment value is refused."""
    environment = {**manifest_ep1["environment"], "torch_version": 2}
    document = {**manifest_ep1, "environment": environment}
    with pytest.raises(TypeError):
        validate_episode_voice_manifest(document)


def test_no_voice_units_at_all_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """No voice units at all is refused."""
    document = {**manifest_ep1, "voice_units": []}
    with pytest.raises(ValueError, match="empty"):
        validate_episode_voice_manifest(document)


def test_a_voice_units_list_that_is_not_a_list_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """A voice_units value that is not a list is refused."""
    document = {**manifest_ep1, "voice_units": {}}
    with pytest.raises(TypeError):
        validate_episode_voice_manifest(document)


@pytest.mark.parametrize("key", sorted(VOICE_UNIT_KEYS))
def test_a_voice_unit_missing_a_key_is_refused(manifest_ep1: dict[str, Any], key: str) -> None:
    """A voice unit missing a key is refused."""
    voice_units = copy.deepcopy(manifest_ep1["voice_units"])
    del voice_units[0][key]
    document = {**manifest_ep1, "voice_units": voice_units}
    with pytest.raises(ValueError, match="missing"):
        validate_episode_voice_manifest(document)


def test_a_voice_unit_with_an_extra_key_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """A voice unit with an extra key is refused."""
    voice_units = copy.deepcopy(manifest_ep1["voice_units"])
    voice_units[0]["extra"] = "x"
    document = {**manifest_ep1, "voice_units": voice_units}
    with pytest.raises(ValueError, match="unexpected"):
        validate_episode_voice_manifest(document)


def test_a_wrong_voice_unit_id_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """A wrong voice_unit_id is refused."""
    voice_units = copy.deepcopy(manifest_ep1["voice_units"])
    voice_units[0]["voice_unit_id"] = "voice_unit_9999"
    document = {**manifest_ep1, "voice_units": voice_units}
    with pytest.raises(ValueError, match="positional"):
        validate_episode_voice_manifest(document)


def test_a_wrong_unit_id_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """A wrong unit_id is refused."""
    voice_units = copy.deepcopy(manifest_ep1["voice_units"])
    voice_units[0]["unit_id"] = "unit_9999"
    document = {**manifest_ep1, "voice_units": voice_units}
    with pytest.raises(ValueError):
        validate_episode_voice_manifest(document)


def test_a_wrong_realization_id_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """A wrong realization_id is refused."""
    voice_units = copy.deepcopy(manifest_ep1["voice_units"])
    voice_units[0]["realization_id"] = "realization_9999"
    document = {**manifest_ep1, "voice_units": voice_units}
    with pytest.raises(ValueError):
        validate_episode_voice_manifest(document)


def test_a_wrong_window_id_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """A wrong window_id is refused."""
    voice_units = copy.deepcopy(manifest_ep1["voice_units"])
    voice_units[0]["window_id"] = "window_9999"
    document = {**manifest_ep1, "voice_units": voice_units}
    with pytest.raises(ValueError):
        validate_episode_voice_manifest(document)


def test_a_wrong_file_field_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """A wrong deterministic file field is refused."""
    voice_units = copy.deepcopy(manifest_ep1["voice_units"])
    voice_units[0]["file"] = "speech/wrong.wav"
    document = {**manifest_ep1, "voice_units": voice_units}
    with pytest.raises(ValueError):
        validate_episode_voice_manifest(document)


def test_reordered_voice_units_are_refused(manifest_ep1: dict[str, Any]) -> None:
    """Reordered voice units are refused."""
    voice_units = list(reversed(copy.deepcopy(manifest_ep1["voice_units"])))
    document = {**manifest_ep1, "voice_units": voice_units}
    with pytest.raises(ValueError):
        validate_episode_voice_manifest(document)


def test_a_float_capacity_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """A float capacity_samples is refused."""
    voice_units = copy.deepcopy(manifest_ep1["voice_units"])
    voice_units[0]["capacity_samples"] = float(voice_units[0]["capacity_samples"])
    document = {**manifest_ep1, "voice_units": voice_units}
    with pytest.raises(TypeError):
        validate_episode_voice_manifest(document)


def test_a_bool_speech_samples_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """A bool speech_samples is refused."""
    voice_units = copy.deepcopy(manifest_ep1["voice_units"])
    voice_units[0]["speech_samples"] = True
    document = {**manifest_ep1, "voice_units": voice_units}
    with pytest.raises(TypeError):
        validate_episode_voice_manifest(document)


def test_a_zero_speech_samples_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """Zero speech_samples is refused."""
    voice_units = copy.deepcopy(manifest_ep1["voice_units"])
    voice_units[0]["speech_samples"] = 0
    voice_units[0]["bytes"] = 44
    document = {**manifest_ep1, "voice_units": voice_units}
    with pytest.raises(ValueError):
        validate_episode_voice_manifest(document)


def test_speech_samples_exceeding_capacity_is_refused_standalone(
    manifest_ep1: dict[str, Any],
) -> None:
    """speech_samples exceeding capacity_samples is refused, standalone -- the FIT law."""
    voice_units = copy.deepcopy(manifest_ep1["voice_units"])
    capacity = voice_units[0]["capacity_samples"]
    voice_units[0]["speech_samples"] = capacity + 1
    voice_units[0]["bytes"] = 44 + (capacity + 1) * 2
    document = {**manifest_ep1, "voice_units": voice_units}
    with pytest.raises(ValueError, match="capacity"):
        validate_episode_voice_manifest(document)


def test_speech_samples_exactly_at_capacity_is_accepted_standalone(
    plan_ep1: dict[str, Any], voice_environment: dict[str, str]
) -> None:
    """speech_samples exactly equal to capacity_samples is accepted -- the inclusive boundary."""
    results: dict[int, dict[str, object]] = {}
    for position, unit in enumerate(plan_ep1["voice_units"], start=1):
        samples = unit["capacity_samples"]
        payload = b"\x00" * (44 + samples * 2)
        results[position] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "speech_samples": samples,
        }
    manifest = build_episode_voice_manifest_document(
        voice_plan=plan_ep1, results=results, environment=voice_environment
    )
    assert manifest["completeness"]["complete"] is True


def test_the_bytes_arithmetic_law_is_enforced(manifest_ep1: dict[str, Any]) -> None:
    """Bytes must equal the header plus exactly speech_samples * 2."""
    voice_units = copy.deepcopy(manifest_ep1["voice_units"])
    voice_units[0]["bytes"] += 1
    document = {**manifest_ep1, "voice_units": voice_units}
    with pytest.raises(ValueError, match="arithmetic|bytes"):
        validate_episode_voice_manifest(document)


@pytest.mark.parametrize("key", sorted(COMPLETENESS_KEYS))
def test_a_missing_completeness_key_is_refused(manifest_ep1: dict[str, Any], key: str) -> None:
    """A missing completeness key is refused."""
    completeness = dict(manifest_ep1["completeness"])
    del completeness[key]
    document = {**manifest_ep1, "completeness": completeness}
    with pytest.raises(ValueError, match="missing"):
        validate_episode_voice_manifest(document)


def test_an_extra_completeness_key_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """An extra completeness key is refused -- including a resurrected aggregate-fit flag."""
    completeness = {**manifest_ep1["completeness"], "fit_all": True}
    document = {**manifest_ep1, "completeness": completeness}
    with pytest.raises(ValueError, match="unexpected"):
        validate_episode_voice_manifest(document)


def test_a_wrong_voice_units_expected_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """A wrong voice_units_expected is refused."""
    completeness = {**manifest_ep1["completeness"], "voice_units_expected": 999}
    document = {**manifest_ep1, "completeness": completeness}
    with pytest.raises(ValueError):
        validate_episode_voice_manifest(document)


def test_a_wrong_voice_units_synthesized_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """A wrong voice_units_synthesized is refused."""
    completeness = {**manifest_ep1["completeness"], "voice_units_synthesized": 999}
    document = {**manifest_ep1, "completeness": completeness}
    with pytest.raises(ValueError):
        validate_episode_voice_manifest(document)


def test_a_wrong_speech_samples_total_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """A wrong speech_samples_total is refused."""
    completeness = {**manifest_ep1["completeness"], "speech_samples_total": 1}
    document = {**manifest_ep1, "completeness": completeness}
    with pytest.raises(ValueError, match="sum"):
        validate_episode_voice_manifest(document)


def test_complete_false_with_a_full_set_of_units_is_refused(manifest_ep1: dict[str, Any]) -> None:
    """complete=False while every unit is present is refused -- recomputed, never asserted."""
    completeness = {**manifest_ep1["completeness"], "complete": False}
    document = {**manifest_ep1, "completeness": completeness}
    with pytest.raises(ValueError, match="complete"):
        validate_episode_voice_manifest(document)


def test_a_bool_complete_flag_is_required_not_an_int() -> None:
    """require_flag refuses 0/1 in place of a bool -- confirmed against the shared helper."""
    from living_diorama.persistence.schema.world_schema_v1 import require_flag

    with pytest.raises(TypeError):
        require_flag(1, "x")
