"""The realization plan's own envelope: exact keys, positions, wording bans.

Every mutation is one field, and every refusal is asserted by message, because
a validator that refuses for the wrong reason is two defects wearing one test.
"""

from typing import Any

import pytest

from living_diorama.language_realization import validate_episode_language_realization_plan


def test_the_canonical_plans_validate(
    plan_ep0: dict[str, Any], plan_ep1: dict[str, Any], plan_ep2: dict[str, Any]
) -> None:
    """All three canonical realization plans pass their own contract."""
    for plan in (plan_ep0, plan_ep1, plan_ep2):
        assert validate_episode_language_realization_plan(plan) is plan


def test_a_non_dict_plan_is_refused() -> None:
    """The envelope is a document, not a list or a scalar."""
    with pytest.raises(TypeError, match="must be a dict"):
        validate_episode_language_realization_plan([])


def test_an_extra_top_level_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A key this contract does not describe was written by something else."""
    plan_ep1["timing"] = {}
    with pytest.raises(ValueError, match="unexpected keys"):
        validate_episode_language_realization_plan(plan_ep1)


def test_a_missing_top_level_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A missing key means the plan is incomplete."""
    del plan_ep1["accounting"]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_episode_language_realization_plan(plan_ep1)


def test_a_wrong_format_tag_is_refused(plan_ep1: dict[str, Any]) -> None:
    """This build reads its own format only."""
    plan_ep1["format"] = "living_diorama_episode_narration_plan"
    with pytest.raises(ValueError, match="this build reads"):
        validate_episode_language_realization_plan(plan_ep1)


def test_an_unsupported_schema_version_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A future schema version is not quietly read as this one."""
    plan_ep1["schema_version"] = 2
    with pytest.raises(ValueError, match="unsupported schema version"):
        validate_episode_language_realization_plan(plan_ep1)


def test_an_unknown_policy_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Wording written under another policy is never mistaken for this one."""
    plan_ep1["policy"] = "language_realization_policy_v2"
    with pytest.raises(ValueError, match="declares policy"):
        validate_episode_language_realization_plan(plan_ep1)


def test_an_extra_source_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A shot plan binding would be exactly the kind of extra this refuses."""
    plan_ep1["source"]["shot_plan_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="unexpected keys"):
        validate_episode_language_realization_plan(plan_ep1)


def test_a_missing_source_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Every binding is present or the plan is incomplete."""
    del plan_ep1["source"]["story_plan_sha256"]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_episode_language_realization_plan(plan_ep1)


def test_a_malformed_digest_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A digest field is sixty-four lowercase hex characters, exactly."""
    plan_ep1["source"]["narration_plan_sha256"] = "not-a-digest"
    with pytest.raises(ValueError, match="64 lowercase hex"):
        validate_episode_language_realization_plan(plan_ep1)


def test_an_unknown_mode_is_refused(plan_ep1: dict[str, Any]) -> None:
    """The mode vocabulary is closed."""
    plan_ep1["source"]["mode"] = "montage"
    with pytest.raises(ValueError, match="expected one of"):
        validate_episode_language_realization_plan(plan_ep1)


def test_an_unsupported_narration_version_is_refused(plan_ep1: dict[str, Any]) -> None:
    """This build realizes narration schema version one only."""
    plan_ep1["source"]["narration_schema_version"] = 2
    with pytest.raises(ValueError, match="narration schema version"):
        validate_episode_language_realization_plan(plan_ep1)


def test_an_unsupported_story_version_is_refused(plan_ep1: dict[str, Any]) -> None:
    """This build realizes story schema version one only."""
    plan_ep1["source"]["story_schema_version"] = 2
    with pytest.raises(ValueError, match="story schema version"):
        validate_episode_language_realization_plan(plan_ep1)


def test_a_baseline_with_a_previous_episode_is_refused(plan_ep0: dict[str, Any]) -> None:
    """A baseline follows no episode."""
    plan_ep0["source"]["previous_episode"] = 0
    with pytest.raises(ValueError, match="follows no episode"):
        validate_episode_language_realization_plan(plan_ep0)


def test_a_baseline_beyond_episode_zero_is_refused(plan_ep0: dict[str, Any]) -> None:
    """A baseline describes episode 0 only."""
    plan_ep0["source"]["episode"] = 1
    with pytest.raises(ValueError, match="episode 0 only"):
        validate_episode_language_realization_plan(plan_ep0)


def test_a_transition_without_a_previous_episode_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A transition names the episode it follows."""
    plan_ep1["source"]["previous_episode"] = None
    with pytest.raises(TypeError, match="previous_episode"):
        validate_episode_language_realization_plan(plan_ep1)


def test_a_non_consecutive_transition_is_refused(plan_ep2: dict[str, Any]) -> None:
    """A transition joins consecutive episodes."""
    plan_ep2["source"]["previous_episode"] = 0
    with pytest.raises(ValueError, match="consecutive"):
        validate_episode_language_realization_plan(plan_ep2)


def test_an_empty_realizations_list_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Every narration plan holds at least one unit."""
    plan_ep1["realizations"] = []
    plan_ep1["accounting"] = {"fact_backed": 0, "realizations_total": 0, "template_backed": 0}
    with pytest.raises(ValueError, match="carries no realizations"):
        validate_episode_language_realization_plan(plan_ep1)


def test_an_extra_record_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A timing field on a record belongs to a later layer and is refused."""
    plan_ep1["realizations"][0]["start_frame"] = 25
    with pytest.raises(ValueError, match="unexpected keys"):
        validate_episode_language_realization_plan(plan_ep1)


def test_an_audio_field_on_a_record_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A voice asset citation is a later phase's field, and is refused here."""
    plan_ep1["realizations"][0]["asset"] = "unit_0001.wav"
    with pytest.raises(ValueError, match="unexpected keys"):
        validate_episode_language_realization_plan(plan_ep1)


def test_a_missing_record_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A record without its sentence is incomplete."""
    del plan_ep1["realizations"][0]["realized_text"]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_episode_language_realization_plan(plan_ep1)


def test_a_realization_id_out_of_position_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A realization id is positional, not a free label."""
    plan_ep1["realizations"][0]["realization_id"] = "realization_0002"
    with pytest.raises(ValueError, match="positional, not a free label"):
        validate_episode_language_realization_plan(plan_ep1)


def test_a_unit_id_out_of_position_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Realization follows the narration plan's own order."""
    plan_ep1["realizations"][0]["unit_id"] = "unit_0002"
    with pytest.raises(ValueError, match="narration plan's own order"):
        validate_episode_language_realization_plan(plan_ep1)


def test_reordered_records_are_refused(plan_ep1: dict[str, Any]) -> None:
    """Swapping two whole records breaks both positional identifier laws."""
    records = plan_ep1["realizations"]
    records[0], records[1] = records[1], records[0]
    with pytest.raises(ValueError, match="positional, not a free label"):
        validate_episode_language_realization_plan(plan_ep1)


def test_a_duplicated_record_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A repeated record sits at a position whose identifier it cannot carry."""
    plan_ep1["realizations"].append(dict(plan_ep1["realizations"][-1]))
    plan_ep1["accounting"]["realizations_total"] += 1
    plan_ep1["accounting"]["template_backed"] += 1
    with pytest.raises(ValueError, match="positional, not a free label"):
        validate_episode_language_realization_plan(plan_ep1)


def test_an_omitted_record_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Dropping a record leaves the accounting measured against fewer rows."""
    plan_ep1["realizations"].pop()
    with pytest.raises(ValueError, match="measured from the records present"):
        validate_episode_language_realization_plan(plan_ep1)


def test_an_empty_sentence_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A realization without wording realized nothing."""
    plan_ep1["realizations"][0]["realized_text"] = "   "
    with pytest.raises(ValueError, match="realized_text"):
        validate_episode_language_realization_plan(plan_ep1)


def test_a_causal_claim_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Realized wording never introduces causality the sources cannot prove."""
    plan_ep1["realizations"][0]["realized_text"] = (
        "At tick 7, the law changed because pressure rose."
    )
    with pytest.raises(ValueError, match="causal or"):
        validate_episode_language_realization_plan(plan_ep1)


def test_a_visual_claim_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Realized wording never claims the viewer saw anything."""
    plan_ep1["realizations"][0]["realized_text"] = "The law was shown changing at tick 7."
    with pytest.raises(ValueError, match="causal or"):
        validate_episode_language_realization_plan(plan_ep1)


def test_an_underscore_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An internal identifier never leaks into human-facing wording."""
    plan_ep1["realizations"][0]["realized_text"] = "At tick 7, law_movement_sharing changed."
    with pytest.raises(ValueError, match="underscore"):
        validate_episode_language_realization_plan(plan_ep1)


def test_a_straight_quote_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Entities are named by label, never by quoted identifier."""
    plan_ep1["realizations"][0]["realized_text"] = 'At tick 7, the "movement" law changed.'
    with pytest.raises(ValueError, match="quotation mark"):
        validate_episode_language_realization_plan(plan_ep1)


def test_an_extra_accounting_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """The accounting vocabulary is closed."""
    plan_ep1["accounting"]["seconds"] = 8
    with pytest.raises(ValueError, match="unexpected keys"):
        validate_episode_language_realization_plan(plan_ep1)


def test_a_missing_accounting_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Every accounting field is present or the block is incomplete."""
    del plan_ep1["accounting"]["fact_backed"]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_episode_language_realization_plan(plan_ep1)


def test_a_total_disagreeing_with_the_records_is_refused(plan_ep1: dict[str, Any]) -> None:
    """The total is measured from the records present, never asserted."""
    plan_ep1["accounting"]["realizations_total"] = 4
    with pytest.raises(ValueError, match="measured from the records present"):
        validate_episode_language_realization_plan(plan_ep1)


def test_a_split_that_does_not_close_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Every record is in exactly one class."""
    plan_ep1["accounting"]["fact_backed"] += 1
    with pytest.raises(ValueError, match="exactly one class"):
        validate_episode_language_realization_plan(plan_ep1)


def test_a_fractional_count_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Counts are exact integers, never floats."""
    plan_ep1["accounting"]["realizations_total"] = 3.0
    with pytest.raises(TypeError, match="realizations_total"):
        validate_episode_language_realization_plan(plan_ep1)


def test_a_boolean_count_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A boolean is not an integer, even though Python subclasses it."""
    plan_ep1["accounting"]["fact_backed"] = True
    with pytest.raises(TypeError, match="fact_backed"):
        validate_episode_language_realization_plan(plan_ep1)


def test_a_string_episode_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Identity fields are exact integers."""
    plan_ep1["source"]["episode"] = "1"
    with pytest.raises(TypeError, match="episode"):
        validate_episode_language_realization_plan(plan_ep1)


def test_a_container_type_swap_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A list where a document belongs is a different shape, not a variant."""
    plan_ep1["realizations"] = {}
    with pytest.raises(TypeError, match="must be a list"):
        validate_episode_language_realization_plan(plan_ep1)
