"""Deriving an Episode Story Plan from real canonical exports.

These tests run against the genuine three-episode chain the engine produced, so
what they assert about the canonical story is what the engine actually did.
"""

import copy
from typing import Any

import pytest

from living_diorama.story import build_episode_story_plan_document, story_spec


def beats_of(plan: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """Every beat in the plan of the given kind."""
    return [beat for beat in plan["beats"] if beat["kind"] == kind]


# ------------------------------------------------------------------ baseline


def test_a_baseline_plan_describes_one_export_and_binds_no_previous(
    export_ep0: dict[str, Any],
) -> None:
    """A baseline plan describes one export and binds no previous."""
    plan = build_episode_story_plan_document(export_ep0)
    assert plan["source"]["mode"] == "baseline"
    assert plan["source"]["previous"] is None
    assert plan["source"]["current"]["episode"] == 0


def test_the_baseline_episode_reports_that_nothing_was_emphasized(
    export_ep0: dict[str, Any],
) -> None:
    """Episode 0 has no events and no durable memory, so nothing is selected."""
    plan = build_episode_story_plan_document(export_ep0)
    assert len(plan["beats"]) == 1
    beat = plan["beats"][0]
    assert beat["kind"] == story_spec.BEAT_NO_EMPHASIZED_BEATS
    assert beat["reason_code"] == story_spec.REASON_NO_BEATS_DERIVED
    assert beat["evidence"] == []


# -------------------------------------------------- the canonical transitions


def test_the_first_transition_reports_the_law_change_and_the_wall(
    export_ep0: dict[str, Any], export_ep1: dict[str, Any]
) -> None:
    """Episode 0 -> 1: the law is suspended and the wall rises."""
    plan = build_episode_story_plan_document(export_ep1, export_ep0)
    assert plan["source"]["mode"] == "transition"
    kinds = [beat["kind"] for beat in plan["beats"]]
    assert story_spec.BEAT_LAW_CHANGE in kinds
    assert story_spec.BEAT_DURABLE_CONSEQUENCE in kinds
    assert story_spec.BEAT_NO_EMPHASIZED_BEATS not in kinds


def test_the_second_transition_reports_persistence_not_silence(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Episode 1 -> 2: the law returns and the damage does not lift.

    This is the case the layer exists for. The engine's honest answer to "what
    moved?" is "almost nothing" -- and the plan must still say that an earlier
    consequence is standing, rather than reporting an empty episode.
    """
    plan = build_episode_story_plan_document(export_ep2, export_ep1)
    persisted = beats_of(plan, story_spec.BEAT_CONSEQUENCE_PERSISTED)
    assert len(persisted) == 1
    assert persisted[0]["emphasis"] == story_spec.EMPHASIS_PRIMARY
    assert persisted[0]["rank"] == 1
    assert beats_of(plan, story_spec.BEAT_NO_EMPHASIZED_BEATS) == []


def test_the_persistence_beat_is_backed_by_the_durable_fact_not_by_prose(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """The persistence beat is backed by the durable fact not by prose."""
    plan = build_episode_story_plan_document(export_ep2, export_ep1)
    beat = beats_of(plan, story_spec.BEAT_CONSEQUENCE_PERSISTED)[0]
    facts = [e for e in beat["evidence"] if e["kind"] == "memory_fact"]
    assert len(facts) == 1
    assert facts[0]["fact_type"] == "LAW_RESTORED_WALL_PERSISTED"
    assert beat["reason_code"] == story_spec.REASON_MEMORY_FACT_NEW


def test_a_persisted_consequence_is_not_reported_as_an_empty_plan(
    export_ep0: dict[str, Any], export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """An empty selection and a standing consequence are different kinds."""
    quiet = build_episode_story_plan_document(export_ep0)
    standing = build_episode_story_plan_document(export_ep2, export_ep1)
    quiet_kinds = {beat["kind"] for beat in quiet["beats"]}
    standing_kinds = {beat["kind"] for beat in standing["beats"]}
    assert quiet_kinds == {story_spec.BEAT_NO_EMPHASIZED_BEATS}
    assert story_spec.BEAT_NO_EMPHASIZED_BEATS not in standing_kinds


# ------------------------------------------------------------ source binding


def test_a_transition_plan_binds_both_exports_by_hash(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """A transition plan binds both exports by hash."""
    plan = build_episode_story_plan_document(export_ep2, export_ep1)
    source = plan["source"]
    assert source["current"]["state_hash"] == export_ep2["source"]["state_hash"]
    assert source["previous"]["state_hash"] == export_ep1["source"]["state_hash"]
    assert source["current"]["parent_state_hash"] == source["previous"]["state_hash"]


def test_the_document_digest_changes_when_the_export_changes(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """The binding names the exact document, not merely the episode number."""
    first = build_episode_story_plan_document(export_ep2, export_ep1)
    tampered = copy.deepcopy(export_ep2)
    tampered["world"]["districts"][0]["population"] += 1
    second = build_episode_story_plan_document(tampered, export_ep1)
    assert (
        first["source"]["current"]["document_sha256"]
        != second["source"]["current"]["document_sha256"]
    )


# --------------------------------------------------------------- traceability


def test_every_beat_cites_evidence_that_resolves_in_the_source_export(
    export_ep0: dict[str, Any], export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """The whole contract in one test: no beat may point at nothing."""
    for current, previous in ((export_ep1, export_ep0), (export_ep2, export_ep1)):
        plan = build_episode_story_plan_document(current, previous)
        events = current["events"]
        fact_ids = {fact["fact_id"] for fact in current["memory"]["facts"]}
        for beat in plan["beats"]:
            assert beat["evidence"], beat["kind"]
            for entry in beat["evidence"]:
                if entry["kind"] == "event":
                    index = entry["index"]
                    assert 0 <= index < len(events)
                    assert events[index]["type"] == entry["type"]
                    assert events[index]["tick"] == entry["tick"]
                    assert events[index]["source_id"] == entry["source_id"]
                else:
                    assert entry["fact_id"] in fact_ids


def test_event_evidence_indexes_the_array_in_its_canonical_append_order(
    export_ep0: dict[str, Any], export_ep1: dict[str, Any]
) -> None:
    """The index is the reference; sorting the history would destroy it."""
    plan = build_episode_story_plan_document(export_ep1, export_ep0)
    law = beats_of(plan, story_spec.BEAT_LAW_CHANGE)[0]
    entry = law["evidence"][0]
    assert export_ep1["events"][entry["index"]]["type"] == "LAW_CHANGED"


def test_the_planner_does_not_mutate_the_exports_it_reads(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """The planner does not mutate the exports it reads."""
    before_current = copy.deepcopy(export_ep2)
    before_previous = copy.deepcopy(export_ep1)
    build_episode_story_plan_document(export_ep2, export_ep1)
    assert export_ep2 == before_current
    assert export_ep1 == before_previous


# ----------------------------------------------------------------- selection


def test_high_frequency_telemetry_is_excluded_by_count_and_reason_not_dropped(
    export_ep0: dict[str, Any], export_ep1: dict[str, Any]
) -> None:
    """A reviewer must be able to see how much was set aside, and why."""
    plan = build_episode_story_plan_document(export_ep1, export_ep0)
    excluded = plan["excluded"]
    assert excluded["SCARCITY_CHANGED"]["reason_code"] == (
        story_spec.REASON_HIGH_FREQUENCY_TELEMETRY
    )
    counted = sum(entry["count"] for entry in excluded.values())
    beat_events = sum(
        1
        for beat in plan["beats"]
        for entry in beat["evidence"]
        if entry["kind"] == "event"
    )
    assert counted + beat_events == len(export_ep1["events"])


def test_a_repeating_event_earns_one_beat_and_the_rest_are_counted(
    export_ep0: dict[str, Any], export_ep1: dict[str, Any]
) -> None:
    """The wall publishes WALL_CHANGED twelve times as its dependency climbs."""
    plan = build_episode_story_plan_document(export_ep1, export_ep0)
    changes = beats_of(plan, story_spec.BEAT_WALL_STATE_CHANGE)
    assert len(changes) == 1
    tally = plan["excluded"]["WALL_CHANGED"]
    assert tally["reason_code"] == story_spec.REASON_REPEAT_SUPPRESSED
    occurrences = sum(1 for e in export_ep1["events"] if e["type"] == "WALL_CHANGED")
    assert tally["count"] == occurrences - 1


def test_an_event_named_by_a_memory_fact_is_absorbed_rather_than_reported_twice(
    export_ep0: dict[str, Any], export_ep1: dict[str, Any]
) -> None:
    """The wall is one moment, so it earns one beat citing both records."""
    plan = build_episode_story_plan_document(export_ep1, export_ep0)
    assert beats_of(plan, story_spec.BEAT_WALL_RAISED) == []
    durable = beats_of(plan, story_spec.BEAT_DURABLE_CONSEQUENCE)[0]
    kinds = {entry["kind"] for entry in durable["evidence"]}
    assert kinds == {"memory_fact", "event"}
    # Absorbed, not excluded: it is represented in the plan, so counting it as
    # set aside would make the plan's own arithmetic contradict itself.
    assert "WALL_BUILT" not in plan["excluded"]


def test_only_memory_facts_new_in_this_episode_earn_beats(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Episode 2 still carries episode 1's wall fact; it is not re-reported."""
    plan = build_episode_story_plan_document(export_ep2, export_ep1)
    assert beats_of(plan, story_spec.BEAT_DURABLE_CONSEQUENCE) == []
    assert len(beats_of(plan, story_spec.BEAT_CONSEQUENCE_PERSISTED)) == 1



# ------------------------------------------------------------------ ordering


def test_beats_are_ordered_strongest_first_with_agreeing_ranks(
    export_ep0: dict[str, Any], export_ep1: dict[str, Any]
) -> None:
    """Beats are ordered strongest first with agreeing ranks."""
    plan = build_episode_story_plan_document(export_ep1, export_ep0)
    weights = [
        story_spec.EMPHASIS_ORDER[beat["emphasis"]] for beat in plan["beats"]
    ]
    assert weights == sorted(weights)
    assert [beat["rank"] for beat in plan["beats"]] == list(
        range(1, len(plan["beats"]) + 1)
    )
    assert [beat["beat_id"] for beat in plan["beats"]] == [
        f"beat_{rank:04d}" for rank in range(1, len(plan["beats"]) + 1)
    ]


def test_beats_of_equal_emphasis_keep_history_order(
    export_ep0: dict[str, Any], export_ep1: dict[str, Any]
) -> None:
    """Beats of equal emphasis keep history order."""
    plan = build_episode_story_plan_document(export_ep1, export_ep0)
    primary = [
        beat for beat in plan["beats"] if beat["emphasis"] == story_spec.EMPHASIS_PRIMARY
    ]
    ticks = [min(entry["tick"] for entry in beat["evidence"]) for beat in primary]
    assert ticks == sorted(ticks)


def test_subject_ids_are_sorted_and_unique(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Subject ids are sorted and unique."""
    plan = build_episode_story_plan_document(export_ep2, export_ep1)
    for beat in plan["beats"]:
        assert beat["subject_ids"] == sorted(set(beat["subject_ids"]))


# ------------------------------------------------------- unknown type safety


def test_an_unknown_event_type_lands_in_unclassified_with_no_invented_meaning(
    export_ep0: dict[str, Any], export_ep1: dict[str, Any]
) -> None:
    """An unknown event type lands in unclassified with no invented meaning."""
    export_ep1["events"].append(
        {
            "payload": {"note": "from a later build"},
            "source_id": "district_a",
            "tick": 20,
            "type": "CITIZEN_MARRIED",
        }
    )
    export_ep1["source"]["event_count"] = len(export_ep1["events"])
    plan = build_episode_story_plan_document(export_ep1, export_ep0)
    entries = [e for e in plan["unclassified"] if e["type"] == "CITIZEN_MARRIED"]
    assert len(entries) == 1
    assert entries[0]["reason_code"] == story_spec.REASON_UNKNOWN_EVENT_TYPE
    assert entries[0]["kind"] == "event"
    for beat in plan["beats"]:
        for entry in beat["evidence"]:
            assert entry.get("type") != "CITIZEN_MARRIED"


def test_an_unknown_memory_fact_type_lands_in_unclassified(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """An unknown memory fact type lands in unclassified."""
    fact = copy.deepcopy(export_ep2["memory"]["facts"][-1])
    fact["fact_id"] = "fact_" + "b" * 64
    fact["fact_type"] = "CITIZEN_REMEMBERED"
    export_ep2["memory"]["facts"].append(fact)
    plan = build_episode_story_plan_document(export_ep2, export_ep1)
    entries = [e for e in plan["unclassified"] if e["type"] == "CITIZEN_REMEMBERED"]
    assert len(entries) == 1
    assert entries[0]["reason_code"] == story_spec.REASON_UNKNOWN_FACT_TYPE



# ---------------------------------------------------------------- malformed


def test_a_malformed_export_is_refused(export_ep1: dict[str, Any]) -> None:
    """A malformed export is refused."""
    del export_ep1["memory"]
    with pytest.raises((ValueError, TypeError)):
        build_episode_story_plan_document(export_ep1)


def test_an_export_with_an_unknown_format_tag_is_refused(
    export_ep1: dict[str, Any],
) -> None:
    """An export with an unknown format tag is refused."""
    export_ep1["format"] = "something_else"
    with pytest.raises(ValueError):
        build_episode_story_plan_document(export_ep1)


def test_an_export_with_an_unsupported_schema_version_is_refused(
    export_ep1: dict[str, Any],
) -> None:
    """An export with an unsupported schema version is refused."""
    export_ep1["schema_version"] = 99
    with pytest.raises(ValueError):
        build_episode_story_plan_document(export_ep1)
