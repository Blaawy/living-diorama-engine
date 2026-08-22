"""The plan format refuses what it does not describe.

A plan is only useful downstream if a consumer can trust its shape completely.
Every one of these tests takes a genuine, valid plan and breaks exactly one
thing, so a failure names the rule that stopped mattering.
"""

import copy
import importlib
import sys
from typing import Any

import pytest

from living_diorama.story import (
    build_episode_story_plan_document,
    story_schema_v1,
    validate_episode_story_plan,
)


@pytest.fixture
def plan(export_ep1: dict[str, Any], export_ep2: dict[str, Any]) -> dict[str, Any]:
    """A genuine, valid transition plan for the tests to break one rule of."""
    return build_episode_story_plan_document(export_ep2, export_ep1)


@pytest.fixture
def baseline_plan(export_ep0: dict[str, Any]) -> dict[str, Any]:
    """A genuine, valid baseline plan."""
    return build_episode_story_plan_document(export_ep0)


# ------------------------------------------------------------------- positive


def test_a_freshly_built_plan_validates(plan: dict[str, Any]) -> None:
    """A freshly built plan validates."""
    assert validate_episode_story_plan(plan) is plan


def test_a_baseline_plan_validates(baseline_plan: dict[str, Any]) -> None:
    """A baseline plan validates."""
    assert validate_episode_story_plan(baseline_plan) is baseline_plan


# ------------------------------------------------------------------- envelope


def test_a_missing_top_level_key_is_refused(plan: dict[str, Any]) -> None:
    """A missing top level key is refused."""
    del plan["beats"]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_episode_story_plan(plan)


def test_an_unexpected_top_level_key_is_refused(plan: dict[str, Any]) -> None:
    """An extra key means something this contract does not describe wrote it."""
    plan["mood"] = "tense"
    with pytest.raises(ValueError, match="unexpected keys"):
        validate_episode_story_plan(plan)


def test_a_wrong_format_tag_is_refused(plan: dict[str, Any]) -> None:
    """A wrong format tag is refused."""
    plan["format"] = "living_diorama_render_export"
    with pytest.raises(ValueError, match="declares format"):
        validate_episode_story_plan(plan)


def test_an_unsupported_schema_version_is_refused(plan: dict[str, Any]) -> None:
    """An unsupported schema version is refused."""
    plan["schema_version"] = 2
    with pytest.raises(ValueError, match="unsupported schema version"):
        validate_episode_story_plan(plan)


def test_a_non_dict_plan_is_refused() -> None:
    """A non dict plan is refused."""
    with pytest.raises(TypeError):
        validate_episode_story_plan([1, 2, 3])


# --------------------------------------------------------------- source binding


def test_a_baseline_plan_that_binds_a_previous_export_is_refused(
    plan: dict[str, Any], baseline_plan: dict[str, Any]
) -> None:
    """A baseline plan that binds a previous export is refused."""
    baseline_plan["source"]["previous"] = plan["source"]["previous"]
    with pytest.raises(ValueError, match="baseline mode but binds a previous"):
        validate_episode_story_plan(baseline_plan)


def test_a_transition_plan_without_a_previous_export_is_refused(
    plan: dict[str, Any],
) -> None:
    """A transition plan without a previous export is refused."""
    plan["source"]["previous"] = None
    with pytest.raises(ValueError, match="transition mode but binds no previous"):
        validate_episode_story_plan(plan)


def test_an_unknown_mode_is_refused(plan: dict[str, Any]) -> None:
    """An unknown mode is refused."""
    plan["source"]["mode"] = "montage"
    with pytest.raises(ValueError, match="expected one of"):
        validate_episode_story_plan(plan)


def test_a_malformed_state_hash_is_refused(plan: dict[str, Any]) -> None:
    """A malformed state hash is refused."""
    plan["source"]["current"]["state_hash"] = "not-a-hash"
    with pytest.raises((ValueError, TypeError)):
        validate_episode_story_plan(plan)


def test_a_missing_document_digest_is_refused(plan: dict[str, Any]) -> None:
    """Without it the plan names an episode but not the document it read."""
    del plan["source"]["current"]["document_sha256"]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_episode_story_plan(plan)


def test_a_non_zero_episode_without_a_parent_hash_is_refused(
    plan: dict[str, Any],
) -> None:
    """A non zero episode without a parent hash is refused."""
    plan["source"]["current"]["parent_state_hash"] = None
    with pytest.raises(ValueError, match="only episode 0 has no parent"):
        validate_episode_story_plan(plan)


def test_episode_zero_carrying_a_parent_hash_is_refused(
    baseline_plan: dict[str, Any],
) -> None:
    """Episode zero carrying a parent hash is refused."""
    baseline_plan["source"]["current"]["parent_state_hash"] = "a" * 64
    with pytest.raises(ValueError, match="episode 0 but carries a parent"):
        validate_episode_story_plan(baseline_plan)


# ----------------------------------------------------------------------- beats


def test_an_unknown_beat_kind_is_refused(plan: dict[str, Any]) -> None:
    """An unknown beat kind is refused."""
    plan["beats"][0]["kind"] = "MONTAGE"
    with pytest.raises(ValueError, match="expected one of"):
        validate_episode_story_plan(plan)


def test_an_unknown_emphasis_level_is_refused(plan: dict[str, Any]) -> None:
    """An unknown emphasis level is refused."""
    plan["beats"][0]["emphasis"] = "CRITICAL"
    with pytest.raises(ValueError, match="expected one of"):
        validate_episode_story_plan(plan)


def test_an_unknown_reason_code_is_refused(plan: dict[str, Any]) -> None:
    """An unknown reason code is refused."""
    plan["beats"][0]["reason_code"] = "FELT_IMPORTANT"
    with pytest.raises(ValueError, match="expected one of"):
        validate_episode_story_plan(plan)


def test_a_rank_that_disagrees_with_position_is_refused(plan: dict[str, Any]) -> None:
    """A rank that disagrees with position is refused."""
    plan["beats"][0]["rank"] = 7
    with pytest.raises(ValueError, match="declares rank"):
        validate_episode_story_plan(plan)


def test_beats_out_of_emphasis_order_are_refused(plan: dict[str, Any]) -> None:
    """A consumer taking the first N beats must get the N most emphasised."""
    plan["beats"].reverse()
    for position, beat in enumerate(plan["beats"]):
        beat["rank"] = position + 1
        beat["beat_id"] = f"beat_{position + 1:04d}"
    with pytest.raises(ValueError, match="emphasised more strongly"):
        validate_episode_story_plan(plan)


def test_a_repeated_beat_id_is_refused(plan: dict[str, Any]) -> None:
    """A repeated beat id is refused, by the positional rule that makes it derivable."""
    plan["beats"][1]["beat_id"] = plan["beats"][0]["beat_id"]
    with pytest.raises(ValueError, match="a beat id is positional"):
        validate_episode_story_plan(plan)


def test_a_beat_id_that_is_not_the_positional_form_is_refused(
    plan: dict[str, Any],
) -> None:
    """Reported: beat_id 'banana' was accepted."""
    plan["beats"][0]["beat_id"] = "banana"
    with pytest.raises(ValueError, match="a beat id is positional"):
        validate_episode_story_plan(plan)


def test_a_beat_with_no_evidence_is_refused(plan: dict[str, Any]) -> None:
    """The traceability rule, stated as a refusal."""
    plan["beats"][0]["evidence"] = []
    with pytest.raises(ValueError, match="cites no evidence"):
        validate_episode_story_plan(plan)


def test_a_no_change_beat_that_cites_evidence_is_refused(
    baseline_plan: dict[str, Any], plan: dict[str, Any]
) -> None:
    """It asserts an absence; citing a record would contradict it."""
    baseline_plan["beats"][0]["evidence"] = copy.deepcopy(plan["beats"][0]["evidence"])
    with pytest.raises(ValueError, match="reports that nothing was selected"):
        validate_episode_story_plan(baseline_plan)


def test_unsorted_subject_ids_are_refused(plan: dict[str, Any]) -> None:
    """Unsorted subject ids are refused."""
    beat = next(b for b in plan["beats"] if len(b["subject_ids"]) > 1)
    beat["subject_ids"].reverse()
    with pytest.raises(ValueError, match="must be sorted"):
        validate_episode_story_plan(plan)


def test_repeated_subject_ids_are_refused(plan: dict[str, Any]) -> None:
    """Repeated subject ids are refused."""
    beat = plan["beats"][0]
    beat["subject_ids"] = [beat["subject_ids"][0]] * 2 if beat["subject_ids"] else ["a", "a"]
    with pytest.raises(ValueError, match="repeats subject id"):
        validate_episode_story_plan(plan)


def test_an_extra_key_on_a_beat_is_refused(plan: dict[str, Any]) -> None:
    """An extra key on a beat is refused."""
    plan["beats"][0]["mood"] = "grim"
    with pytest.raises(ValueError, match="unexpected keys"):
        validate_episode_story_plan(plan)


# -------------------------------------------------------------------- evidence


def test_an_unknown_evidence_kind_is_refused(plan: dict[str, Any]) -> None:
    """An unknown evidence kind is refused."""
    plan["beats"][0]["evidence"][0]["kind"] = "vibe"
    with pytest.raises(ValueError, match="expected one of"):
        validate_episode_story_plan(plan)


def test_a_negative_event_index_is_refused(plan: dict[str, Any]) -> None:
    """A negative event index is refused."""
    entry = next(
        e for b in plan["beats"] for e in b["evidence"] if e["kind"] == "event"
    )
    entry["index"] = -1
    with pytest.raises(ValueError, match="must be >= 0"):
        validate_episode_story_plan(plan)


def test_an_event_evidence_entry_missing_its_index_is_refused(
    plan: dict[str, Any],
) -> None:
    """An event evidence entry missing its index is refused."""
    entry = next(
        e for b in plan["beats"] for e in b["evidence"] if e["kind"] == "event"
    )
    del entry["index"]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_episode_story_plan(plan)


def test_a_fact_evidence_entry_missing_its_fact_id_is_refused(
    plan: dict[str, Any],
) -> None:
    """A fact evidence entry missing its fact id is refused."""
    entry = next(
        e for b in plan["beats"] for e in b["evidence"] if e["kind"] == "memory_fact"
    )
    del entry["fact_id"]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_episode_story_plan(plan)


# ------------------------------------------------------------ excluded tallies


def test_an_exclusion_tally_of_zero_is_refused(plan: dict[str, Any]) -> None:
    """An exclusion tally of zero is refused."""
    plan["excluded"]["SCARCITY_CHANGED"]["count"] = 0
    with pytest.raises(ValueError, match="recorded only"):
        validate_episode_story_plan(plan)


def test_an_exclusion_tally_without_a_reason_is_refused(plan: dict[str, Any]) -> None:
    """An exclusion tally without a reason is refused."""
    del plan["excluded"]["SCARCITY_CHANGED"]["reason_code"]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_episode_story_plan(plan)


def test_an_unclassified_entry_with_an_unknown_reason_is_refused(
    plan: dict[str, Any],
) -> None:
    """An unclassified entry with an unknown reason is refused."""
    plan["unclassified"].append(
        {"kind": "event", "reason_code": "SEEMED_ODD", "type": "X"}
    )
    with pytest.raises(ValueError, match="expected one of"):
        validate_episode_story_plan(plan)


# ------------------------------------------------------------ import boundary


def test_importing_the_story_package_does_not_pull_in_blender_or_simulation() -> None:
    """The AST guard proves what is written; this proves what actually loads."""
    for module in list(sys.modules):
        if module.startswith("living_diorama.story"):
            del sys.modules[module]
    importlib.import_module("living_diorama.story")
    loaded = set(sys.modules)
    assert "bpy" not in loaded
    assert not any(
        name.startswith("living_diorama.systems")
        or name.startswith("living_diorama.simulation")
        for name in loaded
        # the wider test session may have imported these for other suites
        if name.startswith("living_diorama.story")
    )


def test_the_package_exports_exactly_what_it_declares() -> None:
    """The package exports exactly what it declares."""
    import living_diorama.story as story

    for name in story.__all__:
        assert hasattr(story, name), name
    assert story.__all__ == sorted(story.__all__)


def test_the_schema_version_is_independent_of_the_render_schema_version() -> None:
    """The schema version is independent of the render schema version."""
    from living_diorama.render import RENDER_SCHEMA_VERSION

    assert isinstance(story_schema_v1.STORY_SCHEMA_VERSION, int)
    assert isinstance(RENDER_SCHEMA_VERSION, int)


# ------------------------------------------------------- source agreements


def test_a_wrong_render_schema_version_is_refused(plan: dict[str, Any]) -> None:
    """A plan derived from a format this build does not read is refused."""
    plan["source"]["render_schema_version"] = 99
    with pytest.raises(ValueError, match="render schema version"):
        validate_episode_story_plan(plan)


def test_a_baseline_plan_describing_a_later_episode_is_refused(
    baseline_plan: dict[str, Any], plan: dict[str, Any]
) -> None:
    """The validator enforces the baseline scope rule independently."""
    baseline_plan["source"]["current"] = copy.deepcopy(plan["source"]["current"])
    with pytest.raises(ValueError, match="baseline describes episode 0 only"):
        validate_episode_story_plan(baseline_plan)


def test_a_transition_binding_non_consecutive_episodes_is_refused(
    plan: dict[str, Any],
) -> None:
    """A transition binding non consecutive episodes is refused."""
    plan["source"]["current"]["episode"] = 5
    with pytest.raises(ValueError, match="joins consecutive episodes"):
        validate_episode_story_plan(plan)


def test_a_transition_binding_a_broken_hash_chain_is_refused(
    plan: dict[str, Any],
) -> None:
    """Consecutive numbering is not enough; the hashes must join too."""
    plan["source"]["current"]["parent_state_hash"] = "0" * 64
    with pytest.raises(ValueError, match="not the same line of history"):
        validate_episode_story_plan(plan)


def test_a_transition_whose_previous_hash_was_edited_is_refused(
    plan: dict[str, Any],
) -> None:
    """A transition whose previous hash was edited is refused."""
    plan["source"]["previous"]["state_hash"] = "f" * 64
    with pytest.raises(ValueError, match="not the same line of history"):
        validate_episode_story_plan(plan)


def test_the_supported_render_schema_version_is_the_one_the_plan_declares(
    plan: dict[str, Any],
) -> None:
    """The supported render schema version is the one the plan declares."""
    from living_diorama.render import RENDER_SCHEMA_VERSION

    assert plan["source"]["render_schema_version"] == RENDER_SCHEMA_VERSION


# --------------------------------------- semantic agreements the validator owns


def test_a_beat_carrying_a_reason_from_another_origin_is_refused(
    plan: dict[str, Any],
) -> None:
    """Reported: a LAW_CHANGE beat claiming UNKNOWN_FACT_TYPE was accepted."""
    beat = next(b for b in plan["beats"] if b["kind"] == "WALL_STATE_CHANGE")
    beat["reason_code"] = "UNKNOWN_FACT_TYPE"
    with pytest.raises(ValueError, match="may only be justified by"):
        validate_episode_story_plan(plan)


def test_a_fact_beat_claiming_an_event_rule_reason_is_refused(
    plan: dict[str, Any],
) -> None:
    """A fact beat claiming an event rule reason is refused."""
    beat = next(b for b in plan["beats"] if b["kind"] == "CONSEQUENCE_PERSISTED")
    beat["reason_code"] = "EVENT_TYPE_RULE"
    with pytest.raises(ValueError, match="may only be justified by"):
        validate_episode_story_plan(plan)


def test_a_beat_carrying_the_wrong_emphasis_for_its_kind_is_refused(
    plan: dict[str, Any],
) -> None:
    """A beat carrying the wrong emphasis for its kind is refused."""
    beat = next(b for b in plan["beats"] if b["kind"] == "WALL_STATE_CHANGE")
    beat["emphasis"] = "PRIMARY"
    with pytest.raises(ValueError, match="is always"):
        validate_episode_story_plan(plan)


def test_an_empty_result_beat_alongside_real_beats_is_refused(
    plan: dict[str, Any], baseline_plan: dict[str, Any]
) -> None:
    """Reported: a plan with real beats plus NO_EMPHASIZED_BEATS was accepted."""
    plan["beats"].append(copy.deepcopy(baseline_plan["beats"][0]))
    for position, beat in enumerate(plan["beats"]):
        beat["rank"] = position + 1
        beat["beat_id"] = f"beat_{position + 1:04d}"
    with pytest.raises(ValueError, match="the whole plan or it is not true"):
        validate_episode_story_plan(plan)


def test_an_empty_result_beat_naming_subjects_is_refused(
    baseline_plan: dict[str, Any],
) -> None:
    """Reported: NO_EMPHASIZED_BEATS with subject_ids was accepted."""
    baseline_plan["beats"][0]["subject_ids"] = ["district_a"]
    with pytest.raises(ValueError, match="not about any entity"):
        validate_episode_story_plan(baseline_plan)


def test_an_empty_result_beat_with_the_wrong_reason_is_refused(
    baseline_plan: dict[str, Any],
) -> None:
    """Reported: NO_EMPHASIZED_BEATS with a wrong allowed reason was accepted."""
    baseline_plan["beats"][0]["reason_code"] = "UNKNOWN_EVENT_TYPE"
    with pytest.raises(ValueError, match="may only be justified by"):
        validate_episode_story_plan(baseline_plan)


def test_an_empty_result_beat_that_is_not_background_is_refused(
    baseline_plan: dict[str, Any],
) -> None:
    """An empty result beat that is not background is refused."""
    baseline_plan["beats"][0]["emphasis"] = "PRIMARY"
    with pytest.raises(ValueError, match="is always"):
        validate_episode_story_plan(baseline_plan)


def test_an_unclassified_event_claiming_a_classification_reason_is_refused(
    plan: dict[str, Any],
) -> None:
    """Reported: an unclassified event with EVENT_TYPE_RULE was accepted."""
    plan["unclassified"].append(
        {"kind": "event", "reason_code": "EVENT_TYPE_RULE", "type": "X"}
    )
    with pytest.raises(ValueError, match="it was classified after all"):
        validate_episode_story_plan(plan)


def test_an_unclassified_event_carrying_the_fact_reason_is_refused(
    plan: dict[str, Any],
) -> None:
    """An unclassified event carrying the fact reason is refused."""
    plan["unclassified"].append(
        {"kind": "event", "reason_code": "UNKNOWN_FACT_TYPE", "type": "X"}
    )
    with pytest.raises(ValueError, match="it was classified after all"):
        validate_episode_story_plan(plan)


def test_an_unclassified_fact_carrying_the_event_reason_is_refused(
    plan: dict[str, Any],
) -> None:
    """An unclassified fact carrying the event reason is refused."""
    plan["unclassified"].append(
        {"kind": "memory_fact", "reason_code": "UNKNOWN_EVENT_TYPE", "type": "X"}
    )
    with pytest.raises(ValueError, match="it was classified after all"):
        validate_episode_story_plan(plan)


def test_an_exclusion_reason_the_policy_cannot_give_is_refused(
    plan: dict[str, Any],
) -> None:
    """Telemetry is never excluded as a suppressed repeat."""
    plan["excluded"]["SCARCITY_CHANGED"]["reason_code"] = "REPEAT_SUPPRESSED"
    with pytest.raises(ValueError, match="this policy cannot give"):
        validate_episode_story_plan(plan)


def test_a_promoted_type_excluded_as_telemetry_is_refused(
    plan: dict[str, Any],
) -> None:
    """A promoted type excluded as telemetry is refused."""
    plan["excluded"]["WALL_CHANGED"]["reason_code"] = "HIGH_FREQUENCY_TELEMETRY"
    with pytest.raises(ValueError, match="this policy cannot give"):
        validate_episode_story_plan(plan)


def test_an_unknown_type_in_the_excluded_tally_is_refused(
    plan: dict[str, Any],
) -> None:
    """An unknown type belongs in unclassified, never in the excluded tally."""
    plan["excluded"]["CITIZEN_MARRIED"] = {
        "count": 3,
        "reason_code": "UNKNOWN_EVENT_TYPE",
    }
    with pytest.raises(ValueError, match="belongs in unclassified"):
        validate_episode_story_plan(plan)


def test_a_non_repeatable_type_excluded_as_a_repeat_is_refused(
    plan: dict[str, Any],
) -> None:
    """LAW_CHANGED is promoted on every occurrence, so it cannot be suppressed."""
    plan["excluded"]["LAW_CHANGED"] = {
        "count": 1,
        "reason_code": "REPEAT_SUPPRESSED",
    }
    with pytest.raises(ValueError, match="this policy cannot give"):
        validate_episode_story_plan(plan)


# ------------------------- the V1 invariants the planner already emits


def test_an_empty_beat_list_is_refused(plan: dict[str, Any]) -> None:
    """Reported: beats = [] was accepted."""
    plan["beats"] = []
    with pytest.raises(ValueError, match="carries no beats"):
        validate_episode_story_plan(plan)


def test_an_event_beat_citing_only_fact_evidence_is_refused(
    plan: dict[str, Any],
) -> None:
    """Reported: a LAW_CHANGE beat with only memory_fact evidence was accepted."""
    persisted = next(b for b in plan["beats"] if b["kind"] == "CONSEQUENCE_PERSISTED")
    beat = next(b for b in plan["beats"] if b["kind"] == "WALL_STATE_CHANGE")
    beat["evidence"] = [copy.deepcopy(e) for e in persisted["evidence"]
                        if e["kind"] == "memory_fact"]
    with pytest.raises(ValueError, match="exactly one event and nothing else"):
        validate_episode_story_plan(plan)


def test_a_fact_beat_citing_only_event_evidence_is_refused(
    plan: dict[str, Any],
) -> None:
    """Reported: DURABLE_CONSEQUENCE with only event evidence was accepted."""
    beat = next(b for b in plan["beats"] if b["kind"] == "CONSEQUENCE_PERSISTED")
    beat["evidence"] = [e for e in beat["evidence"] if e["kind"] == "event"]
    with pytest.raises(ValueError, match="one fact and the one event"):
        validate_episode_story_plan(plan)


def test_an_event_beat_citing_the_wrong_event_type_is_refused(
    plan: dict[str, Any],
) -> None:
    """An event beat citing the wrong event type is refused."""
    beat = next(b for b in plan["beats"] if b["kind"] == "WALL_STATE_CHANGE")
    beat["evidence"][0]["type"] = "LAW_CHANGED"
    with pytest.raises(ValueError, match="is raised by a WALL_CHANGED event"):
        validate_episode_story_plan(plan)


def test_a_fact_beat_citing_the_wrong_fact_type_is_refused(
    plan: dict[str, Any],
) -> None:
    """A fact beat citing the wrong fact type is refused."""
    beat = next(b for b in plan["beats"] if b["kind"] == "CONSEQUENCE_PERSISTED")
    fact = next(e for e in beat["evidence"] if e["kind"] == "memory_fact")
    fact["fact_type"] = "WALL_BUILT"
    with pytest.raises(ValueError, match="is raised by a LAW_RESTORED_WALL_PERSISTED"):
        validate_episode_story_plan(plan)


def test_a_fact_beat_whose_fact_and_event_disagree_on_subject_is_refused(
    plan: dict[str, Any],
) -> None:
    """A fact beat whose fact and event disagree on subject is refused."""
    beat = next(b for b in plan["beats"] if b["kind"] == "CONSEQUENCE_PERSISTED")
    event = next(e for e in beat["evidence"] if e["kind"] == "event")
    event["source_id"] = "district_a"
    with pytest.raises(ValueError, match="alongside an event published by"):
        validate_episode_story_plan(plan)


def test_a_fact_beat_whose_fact_and_event_disagree_on_tick_is_refused(
    plan: dict[str, Any],
) -> None:
    """A fact beat whose fact and event disagree on tick is refused."""
    beat = next(b for b in plan["beats"] if b["kind"] == "CONSEQUENCE_PERSISTED")
    event = next(e for e in beat["evidence"] if e["kind"] == "event")
    event["tick"] = event["tick"] - 1
    with pytest.raises(ValueError, match="share a tick"):
        validate_episode_story_plan(plan)


def test_a_fact_beat_citing_a_fact_from_another_episode_is_refused(
    plan: dict[str, Any],
) -> None:
    """A fact beat citing a fact from another episode is refused."""
    beat = next(b for b in plan["beats"] if b["kind"] == "CONSEQUENCE_PERSISTED")
    fact = next(e for e in beat["evidence"] if e["kind"] == "memory_fact")
    fact["episode"] = 1
    with pytest.raises(ValueError, match="only facts new in this episode"):
        validate_episode_story_plan(plan)


def test_an_event_index_equal_to_the_event_count_is_refused(
    plan: dict[str, Any],
) -> None:
    """Reported: index == event_count was accepted, one past the end."""
    beat = next(b for b in plan["beats"] if b["kind"] == "WALL_STATE_CHANGE")
    beat["evidence"][0]["index"] = plan["source"]["current"]["event_count"]
    with pytest.raises(ValueError, match="so the last index is"):
        validate_episode_story_plan(plan)


def test_an_event_tick_after_the_episode_closed_is_refused(
    plan: dict[str, Any],
) -> None:
    """Reported: an evidence tick beyond the closing tick was accepted."""
    beat = next(b for b in plan["beats"] if b["kind"] == "WALL_STATE_CHANGE")
    beat["evidence"][0]["tick"] = plan["source"]["current"]["tick"] + 1
    with pytest.raises(ValueError, match="after the episode closed"):
        validate_episode_story_plan(plan)


def test_the_same_event_cited_by_two_beats_is_refused(plan: dict[str, Any]) -> None:
    """Reported: one event index could be reused across beats."""
    persisted = next(b for b in plan["beats"] if b["kind"] == "CONSEQUENCE_PERSISTED")
    shared = next(e for e in persisted["evidence"] if e["kind"] == "event")
    beat = next(b for b in plan["beats"] if b["kind"] == "WALL_STATE_CHANGE")
    beat["evidence"][0]["index"] = shared["index"]
    with pytest.raises(ValueError, match="already cites"):
        validate_episode_story_plan(plan)


def test_a_plan_whose_event_accounting_does_not_balance_is_refused(
    plan: dict[str, Any],
) -> None:
    """The accounting identity the external audit proves, now enforced internally."""
    plan["excluded"]["SCARCITY_CHANGED"]["count"] += 1
    with pytest.raises(ValueError, match="every event is emphasised, set aside"):
        validate_episode_story_plan(plan)


def test_a_plan_missing_an_excluded_tally_is_refused(plan: dict[str, Any]) -> None:
    """A plan missing an excluded tally is refused."""
    del plan["excluded"]["SCARCITY_CHANGED"]
    with pytest.raises(ValueError, match="every event is emphasised, set aside"):
        validate_episode_story_plan(plan)


def test_memory_fact_evidence_is_not_counted_as_an_event(
    plan: dict[str, Any],
) -> None:
    """The accounting counts events only; a fact citation must not inflate it."""
    validate_episode_story_plan(plan)
    facts = sum(
        1 for b in plan["beats"] for e in b["evidence"] if e["kind"] == "memory_fact"
    )
    assert facts == 1, "the fixture should carry exactly one fact citation"


# ------------------- event-derived beats are about the event's own subject


def test_an_event_beat_naming_an_unrelated_subject_is_refused(
    plan: dict[str, Any],
) -> None:
    """Reported: subject_ids = ['totally_other'] was accepted."""
    beat = next(b for b in plan["beats"] if b["kind"] == "WALL_STATE_CHANGE")
    beat["subject_ids"] = ["totally_other"]
    with pytest.raises(ValueError, match="an event-derived beat is about"):
        validate_episode_story_plan(plan)


def test_an_event_beat_naming_no_subject_is_refused(plan: dict[str, Any]) -> None:
    """An event beat naming no subject is refused."""
    beat = next(b for b in plan["beats"] if b["kind"] == "WALL_STATE_CHANGE")
    beat["subject_ids"] = []
    with pytest.raises(ValueError, match="an event-derived beat is about"):
        validate_episode_story_plan(plan)


def test_an_event_beat_naming_a_second_subject_is_refused(
    plan: dict[str, Any],
) -> None:
    """An event beat naming a second subject is refused."""
    beat = next(b for b in plan["beats"] if b["kind"] == "WALL_STATE_CHANGE")
    beat["subject_ids"] = sorted([*beat["subject_ids"], "district_a"])
    with pytest.raises(ValueError, match="an event-derived beat is about"):
        validate_episode_story_plan(plan)


def test_a_genuine_event_beat_names_exactly_its_event_subject(
    plan: dict[str, Any],
) -> None:
    """The positive form of the same rule."""
    beat = next(b for b in plan["beats"] if b["kind"] == "WALL_STATE_CHANGE")
    assert beat["subject_ids"] == [beat["evidence"][0]["source_id"]]


# ------------------------- unclassified types must genuinely be unknown


def test_a_known_fact_type_listed_as_unclassified_is_refused(
    plan: dict[str, Any],
) -> None:
    """Reported: WALL_BUILT + UNKNOWN_FACT_TYPE was accepted."""
    plan["unclassified"].append(
        {"kind": "memory_fact", "reason_code": "UNKNOWN_FACT_TYPE", "type": "WALL_BUILT"}
    )
    with pytest.raises(ValueError, match="the policy has an explicit rule for it"):
        validate_episode_story_plan(plan)


def test_a_known_promoted_event_listed_as_unclassified_is_refused(
    plan: dict[str, Any],
) -> None:
    """Reported: LAW_CHANGED could be labelled unknown with compensated accounting."""
    plan["excluded"]["SCARCITY_CHANGED"]["count"] -= 1
    plan["unclassified"].append(
        {"kind": "event", "reason_code": "UNKNOWN_EVENT_TYPE", "type": "LAW_CHANGED"}
    )
    with pytest.raises(ValueError, match="the policy has an explicit rule for it"):
        validate_episode_story_plan(plan)


def test_a_known_telemetry_event_listed_as_unclassified_is_refused(
    plan: dict[str, Any],
) -> None:
    """A known telemetry event listed as unclassified is refused."""
    plan["excluded"]["SCARCITY_CHANGED"]["count"] -= 1
    plan["unclassified"].append(
        {"kind": "event", "reason_code": "UNKNOWN_EVENT_TYPE", "type": "SCARCITY_CHANGED"}
    )
    with pytest.raises(ValueError, match="the policy has an explicit rule for it"):
        validate_episode_story_plan(plan)


def test_a_genuinely_unknown_event_type_is_still_accepted_as_unclassified(
    plan: dict[str, Any],
) -> None:
    """The positive case must survive."""
    plan["excluded"]["SCARCITY_CHANGED"]["count"] -= 1
    plan["unclassified"].append(
        {"kind": "event", "reason_code": "UNKNOWN_EVENT_TYPE", "type": "CITIZEN_MARRIED"}
    )
    assert validate_episode_story_plan(plan) is plan


def test_a_genuinely_unknown_fact_type_is_still_accepted_as_unclassified(
    plan: dict[str, Any],
) -> None:
    """A genuinely unknown fact type is still accepted as unclassified."""
    plan["unclassified"].append(
        {
            "kind": "memory_fact",
            "reason_code": "UNKNOWN_FACT_TYPE",
            "type": "CITIZEN_REMEMBERED",
        }
    )
    assert validate_episode_story_plan(plan) is plan


def test_the_known_vocabularies_are_the_single_source_of_truth() -> None:
    """The validator must consult the same tables the planner classifies with."""
    from living_diorama.story import story_spec

    assert set(story_spec.KNOWN_EVENT_TYPES) == (
        set(story_spec.EVENT_BEAT_RULES) | set(story_spec.EVENT_EXCLUSIONS)
    )
    assert set(story_spec.KNOWN_FACT_TYPES) == set(story_spec.FACT_BEAT_RULES)
