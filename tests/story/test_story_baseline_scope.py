"""A baseline plan describes episode 0 and no other episode.

Durable memory is cumulative: episode 2's export still carries episode 1's
``WALL_BUILT`` fact. A baseline plan treats every carried fact as new, so
building one for a later episode would report old history as if it had just
happened -- and would date the wall to the wrong episode entirely.

The plan for a later episode is a transition, which needs the previous export to
tell new history from carried history. Asking for a baseline instead is refused.
"""

from typing import Any

import pytest

from living_diorama.story import build_episode_story_plan_document


def test_a_baseline_plan_for_episode_zero_succeeds(export_ep0: dict[str, Any]) -> None:
    """A baseline plan for episode zero succeeds."""
    plan = build_episode_story_plan_document(export_ep0)
    assert plan["source"]["mode"] == "baseline"
    assert plan["source"]["current"]["episode"] == 0


def test_a_baseline_plan_for_episode_one_is_refused(export_ep1: dict[str, Any]) -> None:
    """A baseline plan for episode one is refused."""
    with pytest.raises(ValueError, match="baseline plan describes episode 0 only"):
        build_episode_story_plan_document(export_ep1)


def test_a_baseline_plan_for_episode_two_is_refused(export_ep2: dict[str, Any]) -> None:
    """The case that would have mis-dated the wall to episode 2."""
    with pytest.raises(ValueError, match="baseline plan describes episode 0 only"):
        build_episode_story_plan_document(export_ep2)


def test_the_refusal_names_the_remedy(export_ep2: dict[str, Any]) -> None:
    """A refusal that does not say what to do instead is a dead end."""
    with pytest.raises(ValueError, match="supply the previous export"):
        build_episode_story_plan_document(export_ep2)


def test_transition_mode_is_unchanged_for_episode_one(
    export_ep0: dict[str, Any], export_ep1: dict[str, Any]
) -> None:
    """Transition mode is unchanged for episode one."""
    plan = build_episode_story_plan_document(export_ep1, export_ep0)
    assert plan["source"]["mode"] == "transition"
    assert plan["beats"]


def test_transition_mode_is_unchanged_for_episode_two(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Transition mode is unchanged for episode two."""
    plan = build_episode_story_plan_document(export_ep2, export_ep1)
    assert plan["source"]["mode"] == "transition"
    assert any(beat["kind"] == "CONSEQUENCE_PERSISTED" for beat in plan["beats"])


def test_a_later_episode_never_reports_an_earlier_episodes_fact_as_new(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """The property the baseline restriction exists to protect."""
    plan = build_episode_story_plan_document(export_ep2, export_ep1)
    for beat in plan["beats"]:
        for entry in beat["evidence"]:
            if entry["kind"] == "memory_fact":
                assert entry["episode"] == 2, (
                    f"beat {beat['beat_id']} cites a fact from episode "
                    f"{entry['episode']} as new history"
                )
