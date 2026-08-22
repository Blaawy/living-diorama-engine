"""A memory fact's source event reference must be proven, not assumed.

``source_event_index`` addresses the event array of the episode that *recorded*
the fact. Durable memory is cumulative, so a later episode still carries earlier
facts with their original indices -- in the canonical chain, episode 1's
``WALL_BUILT`` fact is carried into episode 2 still pointing at index 61, which
in episode 2's array is an unrelated ``SOCIAL_STABILITY_CHANGED`` event about a
different district at a different tick.

Following such a reference would attach a confidently wrong citation to a beat.
These tests prove the layer refuses every way that can go wrong instead.
"""

import copy
from typing import Any

import pytest

from living_diorama.memory.world_memory import MemoryFactType
from living_diorama.story import build_episode_story_plan_document
from living_diorama.story.story_facts import (
    FACT_SOURCE_EVENT_TYPES,
    require_fact_shape,
    require_new_fact_episode,
    require_subject_ids,
    resolve_source_event,
)


@pytest.fixture
def fact(export_ep2: dict[str, Any]) -> dict[str, Any]:
    """The episode-2 persistence fact, which genuinely resolves in episode 2."""
    return copy.deepcopy(export_ep2["memory"]["facts"][-1])


@pytest.fixture
def events(export_ep2: dict[str, Any]) -> list[dict[str, Any]]:
    """Episode 2's event array."""
    return copy.deepcopy(export_ep2["events"])


# --------------------------------------------------------- vocabulary agreement


def test_the_local_source_event_map_agrees_with_the_engine() -> None:
    """The story layer restates this mapping; it must not drift from the engine."""
    engine_types = {member.value for member in MemoryFactType}
    assert set(FACT_SOURCE_EVENT_TYPES) == engine_types


# ------------------------------------------------------------------- positive


def test_a_genuine_reference_resolves(
    fact: dict[str, Any], events: list[dict[str, Any]]
) -> None:
    """A genuine reference resolves."""
    resolved = resolve_source_event(fact, events, "fact")
    assert resolved is not None
    index, event = resolved
    assert index == fact["source_event_index"]
    assert event["type"] == fact["source_event_type"]
    assert event["tick"] == fact["tick"]


def test_a_carried_fact_presented_as_new_is_refused(
    export_ep2: dict[str, Any], events: list[dict[str, Any]]
) -> None:
    """The episode-1 fact carried into episode 2 is prefix history, never new.

    Its index 61 is in range and points at a perfectly valid event -- just an
    entirely unrelated one. Declining to dereference it is not enough: a fact
    offered as new must prove it belongs to this episode, or the reference check
    can be skipped by editing one integer.
    """
    carried = copy.deepcopy(export_ep2["memory"]["facts"][0])
    assert carried["episode"] == 1
    assert 0 <= carried["source_event_index"] < len(events)
    assert events[carried["source_event_index"]]["type"] != carried["source_event_type"]
    with pytest.raises(ValueError, match="belongs to the episode that recorded it"):
        require_new_fact_episode(carried, 2, "fact")


# ------------------------------------------------------------------- negative


def test_a_negative_index_is_refused(
    fact: dict[str, Any], events: list[dict[str, Any]]
) -> None:
    """A negative index is refused."""
    fact["source_event_index"] = -1
    with pytest.raises(ValueError):
        require_fact_shape(fact, "fact")


def test_a_bool_index_is_refused(
    fact: dict[str, Any], events: list[dict[str, Any]]
) -> None:
    """``True`` is an int in Python, and would silently mean index 1."""
    fact["source_event_index"] = True
    with pytest.raises(TypeError):
        require_fact_shape(fact, "fact")


def test_a_float_index_is_refused(fact: dict[str, Any]) -> None:
    """A float index is refused."""
    fact["source_event_index"] = 23.0
    with pytest.raises(TypeError):
        require_fact_shape(fact, "fact")


def test_an_out_of_range_index_is_refused(
    fact: dict[str, Any], events: list[dict[str, Any]]
) -> None:
    """A dangling reference fails closed rather than being ignored."""
    fact["source_event_index"] = 10_000
    with pytest.raises(ValueError, match="carries only"):
        resolve_source_event(fact, events, "fact")


def test_a_reference_to_the_wrong_event_type_is_refused(
    fact: dict[str, Any], events: list[dict[str, Any]]
) -> None:
    """In range is not enough; the event must be the right kind of event."""
    index = next(i for i, e in enumerate(events) if e["type"] == "RESOURCE_PRODUCED")
    fact["source_event_index"] = index
    with pytest.raises(ValueError, match="does not identify the moment"):
        resolve_source_event(fact, events, "fact")


def test_a_reference_to_the_wrong_subject_is_refused(
    fact: dict[str, Any], events: list[dict[str, Any]]
) -> None:
    """A reference to the wrong subject is refused."""
    events[fact["source_event_index"]]["source_id"] = "some_other_law"
    with pytest.raises(ValueError, match="was published by"):
        resolve_source_event(fact, events, "fact")


def test_a_reference_to_the_wrong_tick_is_refused(
    fact: dict[str, Any], events: list[dict[str, Any]]
) -> None:
    """A fact and the event it derives from share a tick."""
    events[fact["source_event_index"]]["tick"] = fact["tick"] + 1
    with pytest.raises(ValueError, match="share a tick"):
        resolve_source_event(fact, events, "fact")


def test_a_recognised_fact_naming_the_wrong_source_event_type_is_refused(
    fact: dict[str, Any], events: list[dict[str, Any]]
) -> None:
    """A LAW_RESTORED_WALL_PERSISTED fact can only come from a LAW_RESTORED event."""
    fact["source_event_type"] = "WALL_BUILT"
    with pytest.raises(ValueError, match="must derive from"):
        resolve_source_event(fact, events, "fact")


def test_a_fact_missing_a_required_field_is_refused(fact: dict[str, Any]) -> None:
    """A fact missing a required field is refused."""
    del fact["source_event_type"]
    with pytest.raises(ValueError, match="missing required keys"):
        require_fact_shape(fact, "fact")


def test_a_blank_source_id_is_refused(fact: dict[str, Any]) -> None:
    """A blank source id is refused."""
    fact["source_id"] = "  "
    with pytest.raises(ValueError):
        require_fact_shape(fact, "fact")


# ------------------------------------------------------- through the planner


def test_the_planner_refuses_a_fact_pointing_outside_the_event_array(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """The refusal reaches the top-level API, not just the helper."""
    export_ep2["memory"]["facts"][-1]["source_event_index"] = 10_000
    with pytest.raises(ValueError, match="carries only"):
        build_episode_story_plan_document(export_ep2, export_ep1)


def test_the_planner_refuses_a_fact_pointing_at_an_unrelated_event(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """An in-range reference to a valid but unrelated event is still refused."""
    events = export_ep2["events"]
    index = next(i for i, e in enumerate(events) if e["type"] == "SCARCITY_CHANGED")
    export_ep2["memory"]["facts"][-1]["source_event_index"] = index
    with pytest.raises(ValueError, match="does not identify the moment"):
        build_episode_story_plan_document(export_ep2, export_ep1)


def test_the_planner_refuses_a_fact_whose_tick_disagrees(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """The planner refuses a fact whose tick disagrees."""
    fact = export_ep2["memory"]["facts"][-1]
    export_ep2["events"][fact["source_event_index"]]["tick"] = fact["tick"] + 5
    with pytest.raises(ValueError, match="share a tick"):
        build_episode_story_plan_document(export_ep2, export_ep1)


def test_a_resolved_reference_is_cited_and_absorbed(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """When the reference is genuine, the event is cited and not double-reported."""
    plan = build_episode_story_plan_document(export_ep2, export_ep1)
    beat = next(b for b in plan["beats"] if b["kind"] == "CONSEQUENCE_PERSISTED")
    kinds = {entry["kind"] for entry in beat["evidence"]}
    assert kinds == {"memory_fact", "event"}
    assert "LAW_RESTORED" not in plan["excluded"]
    assert not any(b["kind"] == "LAW_RESTORATION" for b in plan["beats"])


# --------------------------------------- the episode bypass, reproduced exactly


def test_a_new_fact_claiming_an_earlier_episode_is_refused(
    export_ep0: dict[str, Any], export_ep1: dict[str, Any]
) -> None:
    """The reported bypass: mutate only ``episode`` 1 -> 0 and the checks lapse.

    Without the episode rule the fact was promoted with no event evidence, and
    the genuine WALL_BUILT event was then reported a second time on its own.
    """
    export_ep1["memory"]["facts"][0]["episode"] = 0
    with pytest.raises(ValueError, match="belongs to the episode that recorded it"):
        build_episode_story_plan_document(export_ep1, export_ep0)


def test_a_new_fact_claiming_a_future_episode_is_refused(
    export_ep0: dict[str, Any], export_ep1: dict[str, Any]
) -> None:
    """A new fact claiming a future episode is refused."""
    export_ep1["memory"]["facts"][0]["episode"] = 2
    with pytest.raises(ValueError, match="belongs to the episode that recorded it"):
        build_episode_story_plan_document(export_ep1, export_ep0)


def test_an_episode_two_fact_claiming_episode_one_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """An episode two fact claiming episode one is refused."""
    export_ep2["memory"]["facts"][-1]["episode"] = 1
    with pytest.raises(ValueError, match="belongs to the episode that recorded it"):
        build_episode_story_plan_document(export_ep2, export_ep1)


def test_a_baseline_fact_claiming_another_episode_is_refused(
    export_ep0: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Baseline episode 0 holds the same rule: a new fact must declare episode 0."""
    export_ep0["memory"]["facts"] = [copy.deepcopy(export_ep2["memory"]["facts"][-1])]
    export_ep0["memory"]["through_episode"] = 0
    with pytest.raises(ValueError, match="belongs to the episode that recorded it"):
        build_episode_story_plan_document(export_ep0)


def test_the_mutated_fact_cannot_reach_a_beat_without_its_event(
    export_ep0: dict[str, Any], export_ep1: dict[str, Any]
) -> None:
    """The property the refusal protects: no beat without proven provenance.

    The untouched export still produces the fact-backed beat citing both the
    fact and its genuine event, so the guard refuses the mutation without
    refusing the real thing.
    """
    genuine = build_episode_story_plan_document(copy.deepcopy(export_ep1), export_ep0)
    durable = next(b for b in genuine["beats"] if b["kind"] == "DURABLE_CONSEQUENCE")
    assert {entry["kind"] for entry in durable["evidence"]} == {"memory_fact", "event"}
    assert not any(b["kind"] == "WALL_RAISED" for b in genuine["beats"])

    export_ep1["memory"]["facts"][0]["episode"] = 0
    with pytest.raises(ValueError, match="belongs to the episode that recorded it"):
        build_episode_story_plan_document(export_ep1, export_ep0)


# ------------------------------------------------- subject ids: refuse, never repair


def test_subject_ids_accept_the_canonical_shape(fact: dict[str, Any]) -> None:
    """Subject ids accept the canonical shape."""
    assert require_subject_ids(fact["subject_ids"], "subjects") == fact["subject_ids"]


def test_an_integer_subject_is_refused(fact: dict[str, Any]) -> None:
    """Previously dropped silently, leaving a shorter list that looked valid."""
    fact["subject_ids"] = ["district_a", 7]
    with pytest.raises(TypeError):
        require_subject_ids(fact["subject_ids"], "subjects")


def test_a_bool_subject_is_refused(fact: dict[str, Any]) -> None:
    """A bool subject is refused."""
    fact["subject_ids"] = ["district_a", True]
    with pytest.raises(TypeError):
        require_subject_ids(fact["subject_ids"], "subjects")


def test_a_blank_subject_is_refused(fact: dict[str, Any]) -> None:
    """A blank subject is refused."""
    with pytest.raises(ValueError):
        require_subject_ids(["district_a", "   "], "subjects")


def test_a_subject_with_surrounding_whitespace_is_refused() -> None:
    """A subject with surrounding whitespace is refused."""
    with pytest.raises(ValueError, match="surrounding whitespace"):
        require_subject_ids([" district_a"], "subjects")


def test_a_duplicate_subject_is_refused() -> None:
    """Previously de-duplicated silently."""
    with pytest.raises(ValueError, match="repeats"):
        require_subject_ids(["district_a", "district_a"], "subjects")


def test_an_unsorted_subject_list_is_refused() -> None:
    """The memory contract guarantees sorted subjects; sorting here would hide a fault."""
    with pytest.raises(ValueError, match="must be sorted"):
        require_subject_ids(["district_b", "district_a"], "subjects")


def test_a_non_list_subject_field_is_refused() -> None:
    """A non list subject field is refused."""
    with pytest.raises(TypeError):
        require_subject_ids("district_a", "subjects")


def test_the_planner_refuses_a_malformed_subject_list(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """The refusal reaches the top-level API."""
    export_ep2["memory"]["facts"][-1]["subject_ids"] = ["wall_boundary_ab", 7]
    with pytest.raises(TypeError):
        build_episode_story_plan_document(export_ep2, export_ep1)


def test_the_planner_refuses_a_duplicated_subject(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """The planner refuses a duplicated subject."""
    subjects = export_ep2["memory"]["facts"][-1]["subject_ids"]
    export_ep2["memory"]["facts"][-1]["subject_ids"] = [subjects[0], *subjects]
    with pytest.raises(ValueError, match="repeats"):
        build_episode_story_plan_document(export_ep2, export_ep1)


# ------------------- unknown fact types are proven before they are excused


def make_unknown(export: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Turn the newest fact into an unrecognised future type, with overrides."""
    fact = export["memory"]["facts"][-1]
    fact["fact_type"] = "FUTURE_UNKNOWN_FACT"
    fact.update(overrides)
    return export


def test_a_structurally_valid_unknown_fact_degrades_neutrally(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """The behaviour that must survive: unknown, well formed, safely set aside."""
    plan = build_episode_story_plan_document(make_unknown(export_ep2), export_ep1)
    entries = [e for e in plan["unclassified"] if e["type"] == "FUTURE_UNKNOWN_FACT"]
    assert len(entries) == 1
    assert entries[0]["reason_code"] == "UNKNOWN_FACT_TYPE"
    assert not any(b["kind"] == "CONSEQUENCE_PERSISTED" for b in plan["beats"])


def test_an_unknown_fact_claiming_an_earlier_episode_is_refused(
    export_ep0: dict[str, Any], export_ep1: dict[str, Any]
) -> None:
    """Reported: fact_type unknown + episode 0 was accepted as unclassified."""
    with pytest.raises(ValueError, match="belongs to the episode that recorded it"):
        build_episode_story_plan_document(
            make_unknown(export_ep1, episode=0), export_ep0
        )


def test_an_unknown_fact_claiming_a_future_episode_is_refused(
    export_ep0: dict[str, Any], export_ep1: dict[str, Any]
) -> None:
    """Reported: fact_type unknown + episode 2 was also accepted."""
    with pytest.raises(ValueError, match="belongs to the episode that recorded it"):
        build_episode_story_plan_document(
            make_unknown(export_ep1, episode=2), export_ep0
        )


def test_an_unknown_fact_with_a_dangling_index_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """An unknown fact with a dangling index is refused."""
    with pytest.raises(ValueError, match="carries only"):
        build_episode_story_plan_document(
            make_unknown(export_ep2, source_event_index=10_000), export_ep1
        )


def test_an_unknown_fact_with_a_mismatched_event_type_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """No known mapping applies, but the declared type must still be the truth."""
    with pytest.raises(ValueError, match="does not identify the moment"):
        build_episode_story_plan_document(
            make_unknown(export_ep2, source_event_type="SCARCITY_CHANGED"), export_ep1
        )


def test_an_unknown_fact_with_the_wrong_source_id_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """An unknown fact with the wrong source id is refused."""
    with pytest.raises(ValueError, match="was published by"):
        build_episode_story_plan_document(
            make_unknown(export_ep2, source_id="district_a"), export_ep1
        )


def test_an_unknown_fact_with_the_wrong_tick_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """An unknown fact with the wrong tick is refused."""
    with pytest.raises(ValueError, match="share a tick"):
        build_episode_story_plan_document(
            make_unknown(export_ep2, tick=27), export_ep1
        )


def test_an_unknown_fact_with_malformed_subjects_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Shape checks apply to unrecognised facts too."""
    with pytest.raises(TypeError):
        build_episode_story_plan_document(
            make_unknown(export_ep2, subject_ids=["wall_boundary_ab", 7]), export_ep1
        )


def test_an_unknown_fact_does_not_absorb_its_source_event(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """No beat exists to hold the event, so it must stay in the normal pass."""
    plan = build_episode_story_plan_document(make_unknown(export_ep2), export_ep1)
    law_beats = [b for b in plan["beats"] if b["kind"] == "LAW_RESTORATION"]
    assert len(law_beats) == 1, "the LAW_RESTORED event must still be reported"


# ------------- scalar equality must never stand in for a type check


def unknown_pair(export: dict[str, Any], tick: Any) -> dict[str, Any]:
    """An unknown fact and its unknown source event, with a chosen event tick.

    Both types are unrecognised, so neither becomes evidence and neither passes
    through the plan's exact-int validator later. If the comparison here does not
    validate first, nothing else ever will.
    """
    fact = export["memory"]["facts"][-1]
    fact["fact_type"] = "FUTURE_UNKNOWN_FACT"
    fact["source_event_type"] = "FUTURE_UNKNOWN_EVENT"
    fact["tick"] = 1
    event = export["events"][fact["source_event_index"]]
    event["type"] = "FUTURE_UNKNOWN_EVENT"
    event["source_id"] = fact["source_id"]
    event["tick"] = tick
    return export


def test_a_true_source_event_tick_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Reported: True == 1 in Python, so a boolean tick satisfied an int tick."""
    with pytest.raises(TypeError):
        build_episode_story_plan_document(unknown_pair(export_ep2, True), export_ep1)


def test_a_false_source_event_tick_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """A false source event tick is refused."""
    with pytest.raises(TypeError):
        build_episode_story_plan_document(unknown_pair(export_ep2, False), export_ep1)


def test_a_float_source_event_tick_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """1.0 == 1 as well, and is refused for the same reason."""
    with pytest.raises(TypeError):
        build_episode_story_plan_document(unknown_pair(export_ep2, 1.0), export_ep1)


def test_a_string_source_event_tick_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """A string source event tick is refused."""
    with pytest.raises(TypeError):
        build_episode_story_plan_document(unknown_pair(export_ep2, "1"), export_ep1)


def test_a_negative_source_event_tick_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """A negative source event tick is refused."""
    with pytest.raises(ValueError, match="must be >= 0"):
        build_episode_story_plan_document(unknown_pair(export_ep2, -1), export_ep1)


def test_a_non_canonical_source_event_source_id_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """A non canonical source event source id is refused."""
    export = unknown_pair(export_ep2, 1)
    fact = export["memory"]["facts"][-1]
    export["events"][fact["source_event_index"]]["source_id"] = 7
    with pytest.raises(TypeError):
        build_episode_story_plan_document(export, export_ep1)


def test_a_matching_unknown_pair_still_degrades_neutrally(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """The positive case must survive: sound but unrecognised stays unclassified."""
    plan = build_episode_story_plan_document(unknown_pair(export_ep2, 1), export_ep1)
    entries = [e for e in plan["unclassified"] if e["type"] == "FUTURE_UNKNOWN_FACT"]
    assert len(entries) == 1
    assert entries[0]["reason_code"] == "UNKNOWN_FACT_TYPE"
    events = [e for e in plan["unclassified"] if e["kind"] == "event"]
    assert any(e["type"] == "FUTURE_UNKNOWN_EVENT" for e in events)
