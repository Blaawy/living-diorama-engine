"""An empty plan says nothing was emphasized, never that nothing happened.

Story emphasis is presentation metadata. When the policy selects no beat, the
honest statement is about this layer's own output. An episode can publish
hundreds of genuine authoritative events and still emphasise none of them, and
claiming "no authoritative change" in that case would be a false statement about
the world made by a layer with no authority to make it.
"""

import copy
from typing import Any

import pytest

from living_diorama.story import build_episode_story_plan_document, story_spec


def strip_beat_worthy_events(export: dict[str, Any]) -> dict[str, Any]:
    """Remove every event and fact the emphasis policy would promote.

    What remains is a busy episode of pure telemetry: plenty happened, none of
    it selected.
    """
    trimmed = copy.deepcopy(export)
    trimmed["events"] = [
        event for event in trimmed["events"] if event["type"] not in story_spec.EVENT_BEAT_RULES
    ]
    trimmed["source"]["event_count"] = len(trimmed["events"])
    return trimmed


def test_the_vocabulary_contains_no_kind_claiming_absence_of_world_change() -> None:
    """The name itself must not overclaim."""
    for kind in story_spec.BEAT_KINDS:
        assert kind != "NO_AUTHORITATIVE_CHANGE"
        assert "AUTHORITATIVE_CHANGE" not in kind
    assert story_spec.BEAT_NO_EMPHASIZED_BEATS == "NO_EMPHASIZED_BEATS"


def test_an_episode_of_pure_telemetry_reports_no_emphasized_beats(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Hundreds of real events, none selected. That is what the plan must say."""
    trimmed = strip_beat_worthy_events(export_ep2)
    trimmed["memory"]["facts"] = copy.deepcopy(export_ep1["memory"]["facts"])
    plan = build_episode_story_plan_document(trimmed, export_ep1)

    assert len(plan["beats"]) == 1
    beat = plan["beats"][0]
    assert beat["kind"] == story_spec.BEAT_NO_EMPHASIZED_BEATS
    assert beat["reason_code"] == story_spec.REASON_NO_BEATS_DERIVED
    assert beat["evidence"] == []


def test_that_episode_still_reports_the_authoritative_events_it_set_aside(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """The proof the empty result is not a claim of stillness."""
    trimmed = strip_beat_worthy_events(export_ep2)
    trimmed["memory"]["facts"] = copy.deepcopy(export_ep1["memory"]["facts"])
    plan = build_episode_story_plan_document(trimmed, export_ep1)

    excluded_total = sum(entry["count"] for entry in plan["excluded"].values())
    assert excluded_total == len(trimmed["events"])
    assert excluded_total > 100, "this fixture is supposed to be a busy episode"


def test_no_plan_anywhere_emits_a_kind_that_asserts_world_stillness(
    export_ep0: dict[str, Any], export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Across every real plan this build produces."""
    plans = [
        build_episode_story_plan_document(export_ep0),
        build_episode_story_plan_document(export_ep1, export_ep0),
        build_episode_story_plan_document(export_ep2, export_ep1),
    ]
    for plan in plans:
        for beat in plan["beats"]:
            assert "AUTHORITATIVE_CHANGE" not in beat["kind"]


def test_the_empty_result_is_only_used_when_nothing_was_selected(
    export_ep0: dict[str, Any], export_ep1: dict[str, Any]
) -> None:
    """A plan with real beats never also carries the empty-result beat."""
    plan = build_episode_story_plan_document(export_ep1, export_ep0)
    kinds = [beat["kind"] for beat in plan["beats"]]
    assert len(kinds) > 1
    assert story_spec.BEAT_NO_EMPHASIZED_BEATS not in kinds


def test_episode_zero_uses_the_same_presentation_level_result(
    export_ep0: dict[str, Any],
) -> None:
    """Episode 0 uses the same presentation level result."""
    plan = build_episode_story_plan_document(export_ep0)
    assert plan["beats"][0]["kind"] == story_spec.BEAT_NO_EMPHASIZED_BEATS


def test_the_documentation_does_not_promise_absence_of_world_change() -> None:
    """The doc is part of the contract; it must not reintroduce the claim."""
    from pathlib import Path

    doc = Path(__file__).resolve().parents[2] / "docs" / "episode_story_plan.md"
    text = doc.read_text(encoding="utf-8")
    assert "NO_AUTHORITATIVE_CHANGE" not in text
    assert "NO_EMPHASIZED_BEATS" in text


@pytest.mark.parametrize("kind", story_spec.BEAT_KINDS)
def test_every_beat_kind_names_a_presentation_decision_or_an_authoritative_record(
    kind: str,
) -> None:
    """No beat kind may be phrased as a claim about the simulation's state."""
    assert not kind.startswith("NO_") or kind == story_spec.BEAT_NO_EMPHASIZED_BEATS
