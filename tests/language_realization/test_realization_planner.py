"""The planner: canonical realizations, joins, and prose independence.

The expected sentences below are written as independent golden literals --
never derived by calling the production renderer inside the expectation --
so a template drift cannot silently agree with itself.
"""

import copy
from typing import Any

import pytest

from living_diorama.cinematic import build_shot_direction_plan_document
from living_diorama.language_realization import (
    build_episode_language_realization_plan_document,
    validate_episode_language_realization_plan,
)
from living_diorama.narration import (
    build_episode_narration_plan_document,
    validate_episode_narration_plan,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.story import build_episode_story_plan_document

from .conftest import MOTION_CONFIG, build_realization_sources, load_export

EXPECTED_EP0 = ["No beats were emphasized for this episode."]
EXPECTED_EP1 = [
    "At tick 7, the movement resource sharing law changed.",
    "At tick 9, a permanent wall was built on the boundary between District A and District B.",
    "At tick 9, the wall between District A and District B changed state.",
]
EXPECTED_EP2 = [
    "At tick 22, the movement resource sharing law was restored; the permanent wall on "
    "the boundary between District A and District B, built at tick 9, remained in the "
    "world.",
    "At tick 21, the wall between District A and District B changed state.",
]


def _texts(plan: dict[str, Any]) -> list[str]:
    return [record["realized_text"] for record in plan["realizations"]]


def _rebuild_chain(export: dict[str, Any], episode: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Re-derive (narration, story) honestly around a mutated export."""
    previous = load_export(episode - 1) if episode else None
    story = build_episode_story_plan_document(copy.deepcopy(export), previous)
    shots = build_shot_direction_plan_document(story, MOTION_CONFIG.read_bytes())
    narration = build_episode_narration_plan_document(story, shots, copy.deepcopy(export))
    return narration, story


def test_the_baseline_realizes_exactly(plan_ep0: dict[str, Any]) -> None:
    """Episode 0 realizes its one absence unit to the carried sentence."""
    assert _texts(plan_ep0) == EXPECTED_EP0
    assert plan_ep0["accounting"] == {
        "fact_backed": 0,
        "realizations_total": 1,
        "template_backed": 1,
    }


def test_episode_one_realizes_exactly(plan_ep1: dict[str, Any]) -> None:
    """Episode 1 realizes its three units to the reviewed sentences, in order."""
    assert _texts(plan_ep1) == EXPECTED_EP1
    assert plan_ep1["accounting"] == {
        "fact_backed": 1,
        "realizations_total": 3,
        "template_backed": 2,
    }


def test_episode_two_realizes_exactly(plan_ep2: dict[str, Any]) -> None:
    """Episode 2 realizes its two units to the reviewed sentences, in order."""
    assert _texts(plan_ep2) == EXPECTED_EP2
    assert plan_ep2["accounting"] == {
        "fact_backed": 1,
        "realizations_total": 2,
        "template_backed": 1,
    }


def test_records_are_one_to_one_and_positional(plan_ep1: dict[str, Any]) -> None:
    """Each record carries its positional identifiers and nothing extra."""
    for position, record in enumerate(plan_ep1["realizations"], start=1):
        assert record["realization_id"] == f"realization_{position:04d}"
        assert record["unit_id"] == f"unit_{position:04d}"
        assert set(record) == {"realization_id", "realized_text", "unit_id"}


def test_a_forged_unit_fact_id_is_refused(sources_ep1: tuple) -> None:
    """A standalone-valid unit naming another fact dies at the ancestry check.

    The narration schema's fact_id rule is format-only, so the forged
    identifier keeps the document standalone-valid -- proven inside the test
    -- and only the join to the story's own evidence can refuse.
    """
    narration, story, export = sources_ep1
    narration = copy.deepcopy(narration)
    narration["units"][1]["fact_id"] = "fact_" + "0" * 64
    validate_episode_narration_plan(narration)
    with pytest.raises(ValueError, match="about one record"):
        build_episode_language_realization_plan_document(narration, story, export)


def test_a_truncated_narration_is_refused(sources_ep1: tuple) -> None:
    """A narration missing a unit no longer realizes every story beat.

    The truncated narration's own accounting is recounted so the document
    stays standalone-valid; only the units-versus-beats law can refuse.
    """
    narration, story, export = sources_ep1
    narration = copy.deepcopy(narration)
    del narration["units"][2]
    units = narration["units"]
    shown = sum(1 for unit in units if unit["shot_id"] is not None)
    narration["accounting"] = {
        "beats_total": len(units),
        "units_shown": shown,
        "units_unshown": len(units) - shown,
    }
    with pytest.raises(ValueError, match="every beat is realized exactly once"):
        build_episode_language_realization_plan_document(narration, story, export)


def test_a_lying_narration_sentence_moves_nothing(sources_ep1: tuple) -> None:
    """Structure wins: a mutated source sentence leaves every realized byte alone.

    The tampered narration plan still passes its own standalone schema -- the
    text-vs-source proof lives in Phase 24's cross-check, which needs the shot
    plan -- so this planner meets it exactly as a hand-edited file would
    arrive. Its realizations must be byte-identical to the honest chain's,
    because no semantic input of this layer changed. The whole document still
    changes, because ``narration_plan_sha256`` binds the changed input --
    wording invariance is not document identity.
    """
    narration, story, export = sources_ep1
    honest = build_episode_language_realization_plan_document(
        copy.deepcopy(narration), copy.deepcopy(story), copy.deepcopy(export)
    )
    lying = copy.deepcopy(narration)
    lying["units"][0]["text"] = "At tick 7, law lunar_calendar changed."
    tampered = build_episode_language_realization_plan_document(lying, story, export)
    assert dumps_canonical(tampered["realizations"], "realizations") == dumps_canonical(
        honest["realizations"], "realizations"
    )
    assert tampered["source"]["narration_plan_sha256"] != honest["source"]["narration_plan_sha256"]


def test_a_mutated_summary_moves_no_wording() -> None:
    """A reworded fact summary over unchanged details changes no realized text.

    The whole chain is honestly rebuilt around the mutated export, so every
    digest is natively consistent -- and the realized sentences still cannot
    move, because only the structured details are read.
    """
    honest_plan = build_episode_language_realization_plan_document(*build_realization_sources(1))

    export = load_export(1)
    new_fact = next(fact for fact in export["memory"]["facts"] if fact["episode"] == 1)
    new_fact["summary"] = "A wall now divides two districts, recorded at tick 9."
    narration, story = _rebuild_chain(export, 1)
    mutated_plan = build_episode_language_realization_plan_document(
        narration, story, copy.deepcopy(export)
    )

    assert _texts(mutated_plan) == _texts(honest_plan)
    assert (
        mutated_plan["source"]["current_export_sha256"]
        != honest_plan["source"]["current_export_sha256"]
    )


def test_a_mutated_structural_atom_changes_wording() -> None:
    """A changed authoritative law name flows deterministically into the label.

    The name is mutated in the world record and the whole chain rebuilt, so
    every digest is natively consistent; the realized label follows the
    world's own name, exactly as the reviewed rule derives it.
    """
    export = load_export(1)
    export["world"]["laws"][0]["name"] = "movement_resource_pooling"
    narration, story = _rebuild_chain(export, 1)
    plan = build_episode_language_realization_plan_document(narration, story, copy.deepcopy(export))
    assert plan["realizations"][0]["realized_text"] == (
        "At tick 7, the movement resource pooling law changed."
    )


def test_a_stale_story_is_refused(sources_ep1: tuple) -> None:
    """The narration plan's story binding must name the offered story.

    The mutation keeps the story standalone-valid -- a provenance tick moved
    inside its own bounds -- so the digest join is the check that refuses.
    """
    narration, story, export = sources_ep1
    story = copy.deepcopy(story)
    story["source"]["current"]["tick"] += 1
    with pytest.raises(ValueError, match="not about the same story"):
        build_episode_language_realization_plan_document(narration, story, export)


def test_a_stale_export_is_refused(sources_ep1: tuple) -> None:
    """The narration plan's export binding must name the offered export."""
    narration, story, export = sources_ep1
    export = copy.deepcopy(export)
    export["memory"]["facts"][0]["summary"] = "Edited in place."
    with pytest.raises(ValueError, match="not the document the narration read"):
        build_episode_language_realization_plan_document(narration, story, export)


def test_a_mixed_triple_is_refused(sources_ep1: tuple, sources_ep2: tuple) -> None:
    """A narration plan cannot be realized under another episode's story."""
    narration, _story, export = sources_ep1
    _narration2, story2, _export2 = sources_ep2
    with pytest.raises(ValueError, match="not about the same story"):
        build_episode_language_realization_plan_document(narration, story2, export)


def test_a_unit_kind_disagreement_is_refused(sources_ep1: tuple) -> None:
    """A unit and its positional beat must agree on kind.

    Swapping the kind to another template-backed one keeps the narration plan
    standalone-valid -- its text-source classification still matches -- and
    keeps every digest claim true, so the per-unit agreement check is what
    refuses.
    """
    narration, story, export = sources_ep1
    narration = copy.deepcopy(narration)
    narration["units"][0]["kind"] = "LAW_RESTORATION"
    with pytest.raises(ValueError, match="declares kind"):
        build_episode_language_realization_plan_document(narration, story, export)


def test_a_unit_emphasis_disagreement_is_refused(sources_ep1: tuple) -> None:
    """A unit and its positional beat must agree on emphasis."""
    narration, story, export = sources_ep1
    narration = copy.deepcopy(narration)
    narration["units"][2]["emphasis"] = "PRIMARY"
    with pytest.raises(ValueError, match="declares emphasis"):
        build_episode_language_realization_plan_document(narration, story, export)


def test_a_unit_subject_disagreement_is_refused(sources_ep1: tuple) -> None:
    """A unit and its positional beat must agree on subjects."""
    narration, story, export = sources_ep1
    narration = copy.deepcopy(narration)
    narration["units"][0]["subject_ids"] = ["district_a"]
    with pytest.raises(ValueError, match="declares subject_ids"):
        build_episode_language_realization_plan_document(narration, story, export)


def test_the_planner_validates_its_own_output(plan_ep1: dict[str, Any]) -> None:
    """The built document passes the realization schema by construction."""
    assert validate_episode_language_realization_plan(plan_ep1) is plan_ep1
