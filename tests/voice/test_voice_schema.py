"""Standalone validation of the Episode Voice Plan V1 envelope.

Every test here proves what the document can prove about itself alone --
never that a ``capacity_samples`` value is true of a real Phase 27 window,
which only the source cross-check may claim.
"""

import copy
from typing import Any

import pytest

from living_diorama.voice.voice_schema_v1 import validate_episode_voice_plan


@pytest.mark.parametrize("episode", [0, 1, 2])
def test_every_canonical_plan_validates(episode: int, request: pytest.FixtureRequest) -> None:
    """Every canonical plan validates."""
    plan = request.getfixturevalue(f"plan_ep{episode}")
    assert validate_episode_voice_plan(plan) == plan


def test_a_non_dict_document_is_refused() -> None:
    """A non dict document is refused."""
    with pytest.raises(TypeError):
        validate_episode_voice_plan(["not", "a", "dict"])


def test_a_missing_top_level_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A missing top level key is refused."""
    broken = copy.deepcopy(plan_ep1)
    del broken["voice"]
    with pytest.raises(ValueError, match="missing"):
        validate_episode_voice_plan(broken)


def test_an_extra_top_level_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An extra top level key is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["measured_samples"] = 1
    with pytest.raises(ValueError, match="unexpected"):
        validate_episode_voice_plan(broken)


def test_a_wrong_format_tag_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A wrong format tag is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["format"] = "not_the_right_format"
    with pytest.raises(ValueError, match="format"):
        validate_episode_voice_plan(broken)


def test_an_unsupported_schema_version_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An unsupported schema version is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["schema_version"] = 2
    with pytest.raises(ValueError, match="schema version"):
        validate_episode_voice_plan(broken)


def test_an_unknown_policy_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An unknown policy is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["policy"] = "voice_policy_v2"
    with pytest.raises(ValueError, match="policy"):
        validate_episode_voice_plan(broken)


def test_a_missing_source_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A missing source key is refused."""
    broken = copy.deepcopy(plan_ep1)
    del broken["source"]["episode"]
    with pytest.raises(ValueError, match="missing"):
        validate_episode_voice_plan(broken)


def test_an_extra_source_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An extra source key is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["source"]["voice_measurement_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="unexpected"):
        validate_episode_voice_plan(broken)


@pytest.mark.parametrize(
    "field",
    [
        "narration_plan_sha256",
        "delivery_plan_sha256",
        "shot_plan_sha256",
        "story_plan_sha256",
        "current_export_sha256",
        "motion_time_sha256",
        "voice_measurement_sha256",
    ],
)
def test_a_deleted_v1_source_key_is_never_a_valid_source_key(
    plan_ep1: dict[str, Any], field: str
) -> None:
    """A deleted v1 source key is never a valid source key."""
    broken = copy.deepcopy(plan_ep1)
    broken["source"][field] = "a" * 64
    with pytest.raises(ValueError, match="unexpected"):
        validate_episode_voice_plan(broken)


@pytest.mark.parametrize("field", ["presentation_plan_sha256", "realization_plan_sha256"])
def test_a_malformed_digest_is_refused(plan_ep1: dict[str, Any], field: str) -> None:
    """A malformed digest is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["source"][field] = "not-hex"
    with pytest.raises(ValueError, match="hexadecimal"):
        validate_episode_voice_plan(broken)


def test_an_unsupported_presentation_schema_version_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An unsupported presentation schema version is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["source"]["presentation_schema_version"] = 2
    with pytest.raises(ValueError, match="presentation schema version"):
        validate_episode_voice_plan(broken)


def test_an_unsupported_realization_schema_version_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An unsupported realization schema version is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["source"]["realization_schema_version"] = 2
    with pytest.raises(ValueError, match="realization schema version"):
        validate_episode_voice_plan(broken)


def test_a_baseline_with_a_previous_episode_is_refused(plan_ep0: dict[str, Any]) -> None:
    """A baseline with a previous episode is refused."""
    broken = copy.deepcopy(plan_ep0)
    broken["source"]["previous_episode"] = 0
    with pytest.raises(ValueError, match="previous_episode"):
        validate_episode_voice_plan(broken)


def test_a_baseline_describing_a_nonzero_episode_is_refused(plan_ep0: dict[str, Any]) -> None:
    """A baseline describing a nonzero episode is refused."""
    broken = copy.deepcopy(plan_ep0)
    broken["source"]["episode"] = 1
    with pytest.raises(ValueError, match="baseline"):
        validate_episode_voice_plan(broken)


def test_a_transition_with_no_previous_episode_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A transition with no previous episode is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["source"]["previous_episode"] = None
    with pytest.raises(TypeError):
        validate_episode_voice_plan(broken)


def test_a_transition_joining_nonconsecutive_episodes_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A transition joining nonconsecutive episodes is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["source"]["previous_episode"] = 5
    with pytest.raises(ValueError, match="consecutive"):
        validate_episode_voice_plan(broken)


def test_a_missing_voice_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A missing voice key is refused."""
    broken = copy.deepcopy(plan_ep1)
    del broken["voice"]["seed"]
    with pytest.raises(ValueError, match="missing"):
        validate_episode_voice_plan(broken)


def test_an_extra_voice_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An extra voice key is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice"]["device"] = "cpu"
    with pytest.raises(ValueError, match="unexpected"):
        validate_episode_voice_plan(broken)


@pytest.mark.parametrize(
    ("field", "forged"),
    [
        ("engine", "piper"),
        ("engine_version", "0.9.5"),
        ("g2p", "espeak"),
        ("g2p_version", "0.9.5"),
        ("model_repository", "hexgrad/Kokoro-100M"),
        ("model_revision", "0" * 40),
        ("model_weights_sha256", "0" * 64),
        ("model_config_sha256", "0" * 64),
        ("voice", "af_bella"),
        ("voice_pack_sha256", "0" * 64),
        ("lang_code", "b"),
        ("speed_percent", 150),
        ("sample_rate_hz", 22_050),
        ("channels", 2),
        ("seed", 1),
    ],
)
def test_each_voice_field_forged_individually_is_refused(
    plan_ep1: dict[str, Any], field: str, forged: Any
) -> None:
    """Each voice field forged individually is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice"][field] = forged
    with pytest.raises(ValueError):
        validate_episode_voice_plan(broken)


def test_a_float_speed_percent_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A float speed percent is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice"]["speed_percent"] = 100.0
    with pytest.raises(TypeError):
        validate_episode_voice_plan(broken)


def test_a_bool_seed_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A bool seed is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice"]["seed"] = False
    with pytest.raises(TypeError):
        validate_episode_voice_plan(broken)


def test_no_voice_units_at_all_is_refused(plan_ep1: dict[str, Any]) -> None:
    """No voice units at all is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"] = []
    with pytest.raises(ValueError, match="no voice units"):
        validate_episode_voice_plan(broken)


def test_a_voice_units_list_that_is_not_a_list_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A voice units list that is not a list is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"] = {}
    with pytest.raises(TypeError):
        validate_episode_voice_plan(broken)


def test_a_voice_unit_missing_a_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A voice unit missing a key is refused."""
    broken = copy.deepcopy(plan_ep1)
    del broken["voice_units"][0]["capacity_samples"]
    with pytest.raises(ValueError, match="missing"):
        validate_episode_voice_plan(broken)


def test_a_voice_unit_with_an_extra_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A voice unit with an extra key is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"][0]["measured_speech_samples"] = 1
    with pytest.raises(ValueError, match="unexpected"):
        validate_episode_voice_plan(broken)


def test_a_wrong_voice_unit_id_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A wrong voice unit id is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"][0]["voice_unit_id"] = "voice_unit_9999"
    with pytest.raises(ValueError, match="positional"):
        validate_episode_voice_plan(broken)


def test_a_wrong_unit_id_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A wrong unit id is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"][0]["unit_id"] = "unit_9999"
    with pytest.raises(ValueError, match="own order"):
        validate_episode_voice_plan(broken)


def test_a_wrong_realization_id_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A wrong realization id is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"][0]["realization_id"] = "realization_9999"
    with pytest.raises(ValueError, match="own order"):
        validate_episode_voice_plan(broken)


def test_a_wrong_window_id_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A wrong window id is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"][0]["window_id"] = "window_9999"
    with pytest.raises(ValueError, match="own order"):
        validate_episode_voice_plan(broken)


def test_reordered_voice_units_are_refused(plan_ep1: dict[str, Any]) -> None:
    """Reordered voice units are refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"][0], broken["voice_units"][1] = (
        broken["voice_units"][1],
        broken["voice_units"][0],
    )
    with pytest.raises(ValueError, match="positional"):
        validate_episode_voice_plan(broken)


def test_a_duplicated_voice_unit_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A duplicated voice unit is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"][1] = copy.deepcopy(broken["voice_units"][0])
    broken["voice_units"][1]["voice_unit_id"] = "voice_unit_0002"
    with pytest.raises(ValueError):
        validate_episode_voice_plan(broken)


def test_an_omitted_voice_unit_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An omitted voice unit is refused."""
    broken = copy.deepcopy(plan_ep1)
    del broken["voice_units"][1]
    # The remaining tail record shifts into a position it does not hold a
    # positional identifier for, so this dies on positional identity before
    # accounting is ever reached -- omission is unrepresentable twice over.
    with pytest.raises(ValueError, match="positional"):
        validate_episode_voice_plan(broken)


def test_a_float_capacity_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A float capacity is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"][0]["capacity_samples"] = 144000.0
    with pytest.raises(TypeError):
        validate_episode_voice_plan(broken)


def test_a_bool_capacity_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A bool capacity is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"][0]["capacity_samples"] = True
    with pytest.raises(TypeError):
        validate_episode_voice_plan(broken)


def test_a_negative_capacity_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A negative capacity is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"][0]["capacity_samples"] = -1
    # require_exact_int's own >= 0 rule fires before this layer's own [1,
    # MAX] rail is ever consulted -- refused either way, never repaired.
    with pytest.raises(ValueError, match=">= 0"):
        validate_episode_voice_plan(broken)


def test_a_zero_capacity_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A zero capacity is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"][0]["capacity_samples"] = 0
    with pytest.raises(ValueError, match=r"\[1,"):
        validate_episode_voice_plan(broken)


def test_a_capacity_over_the_maximum_rail_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A capacity over the maximum rail is refused."""
    from living_diorama.voice.voice_spec import MAX_VOICE_CAPACITY_SAMPLES

    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"][0]["capacity_samples"] = MAX_VOICE_CAPACITY_SAMPLES + 1
    with pytest.raises(ValueError, match=r"\[1,"):
        validate_episode_voice_plan(broken)


def test_a_capacity_at_exactly_the_maximum_rail_is_accepted_standalone(
    plan_ep1: dict[str, Any],
) -> None:
    """A capacity at exactly the maximum rail is accepted standalone."""
    from living_diorama.voice.voice_spec import MAX_VOICE_CAPACITY_SAMPLES

    broken = copy.deepcopy(plan_ep1)
    original = broken["voice_units"][0]["capacity_samples"]
    broken["voice_units"][0]["capacity_samples"] = MAX_VOICE_CAPACITY_SAMPLES
    broken["accounting"]["capacity_samples_total"] += MAX_VOICE_CAPACITY_SAMPLES - original
    # Standalone validity never proves this is true of a real window -- it
    # only proves the value sits inside the plausibility rail. This test
    # documents exactly that boundary: the value passes here, and would be
    # refused by the source cross-check instead (see test_voice_cross_check).
    validate_episode_voice_plan(broken)


def test_a_missing_accounting_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A missing accounting key is refused."""
    broken = copy.deepcopy(plan_ep1)
    del broken["accounting"]["voice_units_total"]
    with pytest.raises(ValueError, match="missing"):
        validate_episode_voice_plan(broken)


def test_an_extra_accounting_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An extra accounting key is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["accounting"]["measured_samples_total"] = 1
    with pytest.raises(ValueError, match="unexpected"):
        validate_episode_voice_plan(broken)


def test_a_wrong_voice_units_total_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A wrong voice units total is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["accounting"]["voice_units_total"] += 1
    with pytest.raises(ValueError, match="voice units but carries"):
        validate_episode_voice_plan(broken)


def test_a_wrong_capacity_samples_total_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A wrong capacity samples total is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["accounting"]["capacity_samples_total"] += 1
    with pytest.raises(ValueError, match="total capacity samples"):
        validate_episode_voice_plan(broken)
