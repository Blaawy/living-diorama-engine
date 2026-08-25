"""Whether the plan's claims are true of its sources, and then the seal.

Schema validity and relationship validity are different questions. Every plan
mutated here still passes ``validate_episode_narration_plan`` -- that is the
point of the module: each one is a document that is perfectly well formed and
quietly false about where it came from, what it was shown, or what the world
recorded.

The last test in each group is the interesting one. A tamper that survives every
named check still has to survive the re-derivation seal, and a deterministic
single-output contract leaves it nowhere to hide.
"""

import copy
from typing import Any

import pytest

from living_diorama.narration import (
    build_episode_narration_plan_document,
    validate_episode_narration_plan,
    validate_narration_plan_against_sources,
)

from .conftest import build_sources

Sources = tuple[dict[str, Any], dict[str, Any], dict[str, Any]]


def _plan(sources: Sources) -> dict[str, Any]:
    """Derive the narration plan for one source triple."""
    return build_episode_narration_plan_document(*sources)


def _unshown(plan: dict[str, Any]) -> dict[str, Any]:
    """Return the plan's first unshown unit."""
    return next(unit for unit in plan["units"] if unit["visibility"] == "UNSHOWN")


def _shown(plan: dict[str, Any]) -> dict[str, Any]:
    """Return the plan's first shown unit."""
    return next(unit for unit in plan["units"] if unit["visibility"] == "SHOWN")


# ---- the honest plans pass


@pytest.mark.parametrize("episode", [0, 1, 2])
def test_a_derived_plan_verifies_against_its_sources(episode: int) -> None:
    """The honest case, for all three canonical episodes."""
    sources = build_sources(episode)
    plan = _plan(sources)
    assert validate_narration_plan_against_sources(plan, *sources) is plan


# ---- bindings


def test_a_forged_story_digest_is_refused(sources_ep1: Sources) -> None:
    """A syntactically valid digest is not a source-verified one."""
    plan = _plan(sources_ep1)
    plan["source"]["story_plan_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="does not narrate that document"):
        validate_narration_plan_against_sources(plan, *sources_ep1)


def test_a_forged_shot_digest_is_refused(sources_ep1: Sources) -> None:
    """The direction binding is checked against the document actually offered."""
    plan = _plan(sources_ep1)
    plan["source"]["shot_plan_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="does not narrate that document"):
        validate_narration_plan_against_sources(plan, *sources_ep1)


def test_a_forged_export_digest_is_refused(sources_ep1: Sources) -> None:
    """So is the export the carried sentences would have come from."""
    plan = _plan(sources_ep1)
    plan["source"]["current_export_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="does not narrate that document"):
        validate_narration_plan_against_sources(plan, *sources_ep1)


def test_a_stale_export_is_refused(sources_ep1: Sources) -> None:
    """Right shape, right episode's neighbour, wrong document."""
    story, shots, _export = sources_ep1
    _s, _sh, other_export = build_sources(2)
    plan = _plan(sources_ep1)
    with pytest.raises(ValueError, match="does not narrate that document"):
        validate_narration_plan_against_sources(plan, story, shots, other_export)


def test_a_story_and_shot_plan_from_different_episodes_are_refused(
    sources_ep1: Sources,
) -> None:
    """A shot plan directing another story cannot be paired with this one."""
    story, _shots, export = sources_ep1
    _s2, other_shots, _e2 = build_sources(2)
    plan = _plan(sources_ep1)
    with pytest.raises(ValueError, match="does not narrate that document"):
        validate_narration_plan_against_sources(plan, story, other_shots, export)


def test_a_plan_narrating_another_episodes_sources_is_refused(sources_ep2: Sources) -> None:
    """A well-formed plan for episode 1 is not a plan for episode 2."""
    other = build_sources(1)
    plan = _plan(other)
    with pytest.raises(ValueError, match="does not narrate that document"):
        validate_narration_plan_against_sources(plan, *sources_ep2)


# ---- per-unit agreement with the story


def test_a_unit_restating_a_nonexistent_beat_is_refused(sources_ep1: Sources) -> None:
    """The schema cannot catch this: position and form are still correct."""
    story, shots, export = sources_ep1
    story = copy.deepcopy(story)
    plan = _plan((story, shots, export))
    trimmed = copy.deepcopy(story)
    trimmed["beats"] = trimmed["beats"][:-1]
    with pytest.raises(ValueError):
        validate_narration_plan_against_sources(plan, trimmed, shots, export)


def test_a_changed_emphasis_is_refused(sources_ep1: Sources) -> None:
    """Emphasis is copied from Phase 21, never restated differently."""
    plan = _plan(sources_ep1)
    unit = next(u for u in plan["units"] if u["emphasis"] == "SECONDARY")
    unit["emphasis"] = "PRIMARY"
    validate_episode_narration_plan(plan)
    with pytest.raises(ValueError, match="narration copies the story's own account"):
        validate_narration_plan_against_sources(plan, *sources_ep1)


def test_a_changed_kind_is_refused(sources_ep1: Sources) -> None:
    """A unit's kind is the beat's kind, checked rather than trusted."""
    plan = _plan(sources_ep1)
    _shown(plan)["kind"] = "WALL_RAISED"
    with pytest.raises(ValueError):
        validate_narration_plan_against_sources(plan, *sources_ep1)


def test_changed_subjects_are_refused(sources_ep2: Sources) -> None:
    """Naming an entity the story never named would point a reader at the wrong one."""
    plan = _plan(sources_ep2)
    unit = _unshown(plan)
    unit["subject_ids"] = sorted([*unit["subject_ids"], "district_z"])
    validate_episode_narration_plan(plan)
    with pytest.raises(ValueError, match="narration copies the story's own account"):
        validate_narration_plan_against_sources(plan, *sources_ep2)


# ---- visibility honesty


def test_a_shown_unit_bound_to_an_unshown_beat_is_refused(sources_ep2: Sources) -> None:
    """The forgery this layer exists to make impossible.

    Episode 1 -> 2's first beat is the persisted consequence: PRIMARY, and
    honestly unshown because no approved camera can see the register. A plan
    that promoted it to SHOWN and pointed it at a real shot is well formed, and
    is a lie about what the viewer was given.
    """
    plan = _plan(sources_ep2)
    unit = _unshown(plan)
    borrowed = _shown(plan)
    unit["visibility"] = "SHOWN"
    unit["shot_id"] = borrowed["shot_id"]
    unit["start_frame"] = borrowed["start_frame"]
    unit["end_frame"] = borrowed["end_frame"]
    unit["unshown_reason"] = None
    plan["accounting"] = {"beats_total": 2, "units_shown": 2, "units_unshown": 0}
    validate_episode_narration_plan(plan)
    with pytest.raises(ValueError, match="Phase 22's decision, reported here and never re-made"):
        validate_narration_plan_against_sources(plan, *sources_ep2)


def test_a_shifted_frame_span_is_refused(sources_ep1: Sources) -> None:
    """A span is copied from the citing shot and must still equal it."""
    plan = _plan(sources_ep1)
    unit = _shown(plan)
    unit["start_frame"] += 1
    validate_episode_narration_plan(plan)
    with pytest.raises(ValueError, match="the shot direction plan grants"):
        validate_narration_plan_against_sources(plan, *sources_ep1)


def test_a_borrowed_shot_id_is_refused(sources_ep1: Sources) -> None:
    """Citing another beat's shot is a claim about framing nobody granted."""
    plan = _plan(sources_ep1)
    units = [u for u in plan["units"] if u["visibility"] == "SHOWN"]
    units[0]["shot_id"] = units[1]["shot_id"]
    validate_episode_narration_plan(plan)
    with pytest.raises(ValueError, match="the shot direction plan grants"):
        validate_narration_plan_against_sources(plan, *sources_ep1)


def test_a_changed_unshown_reason_is_refused(sources_ep2: Sources) -> None:
    """Why a beat went unshown is Phase 22's finding, not this layer's summary of it."""
    plan = _plan(sources_ep2)
    _unshown(plan)["unshown_reason"] = "TRANSITION_BUDGET_EXHAUSTED"
    validate_episode_narration_plan(plan)
    with pytest.raises(ValueError, match="the shot direction plan grants"):
        validate_narration_plan_against_sources(plan, *sources_ep2)


# ---- wording


def test_a_carried_summary_altered_by_one_character_is_refused(sources_ep2: Sources) -> None:
    """Verbatim means verbatim."""
    plan = _plan(sources_ep2)
    unit = _unshown(plan)
    unit["text"] = unit["text"].replace("remained", "remainedd")
    validate_episode_narration_plan(plan)
    with pytest.raises(ValueError, match="restated verbatim"):
        validate_narration_plan_against_sources(plan, *sources_ep2)


def test_a_template_sentence_altered_by_one_character_is_refused(sources_ep1: Sources) -> None:
    """Composed wording is the table's wording exactly."""
    plan = _plan(sources_ep1)
    unit = _shown(plan)
    unit["text"] = unit["text"].replace("At tick", "at tick")
    validate_episode_narration_plan(plan)
    with pytest.raises(ValueError, match="the versioned template"):
        validate_narration_plan_against_sources(plan, *sources_ep1)


def test_a_plausible_rewrite_is_refused(sources_ep1: Sources) -> None:
    """A better sentence is still not this contract's sentence.

    This is what a language model would produce if it were allowed to write
    here. It is fluent, it is arguably true, and it is refused -- rephrasing
    belongs to a later realization layer that must prove it changed nothing.
    """
    plan = _plan(sources_ep1)
    unit = _shown(plan)
    unit["text"] = "The movement-sharing law was suspended at tick 7."
    validate_episode_narration_plan(plan)
    with pytest.raises(ValueError, match="the versioned template"):
        validate_narration_plan_against_sources(plan, *sources_ep1)


def test_a_swapped_fact_id_is_refused(sources_ep2: Sources) -> None:
    """The sentence and the evidence must be about one record."""
    story, shots, export = sources_ep2
    plan = _plan(sources_ep2)
    other = next(fact["fact_id"] for fact in export["memory"]["facts"] if fact["episode"] != 2)
    _unshown(plan)["fact_id"] = other
    validate_episode_narration_plan(plan)
    with pytest.raises(ValueError, match="about one record"):
        validate_narration_plan_against_sources(plan, story, shots, export)


# ---- accounting


def test_an_omitted_beat_is_refused(sources_ep1: Sources) -> None:
    """Dropping a beat is caught even with the accounting block adjusted to match."""
    plan = _plan(sources_ep1)
    dropped = plan["units"].pop()
    plan["accounting"]["beats_total"] -= 1
    key = "units_shown" if dropped["visibility"] == "SHOWN" else "units_unshown"
    plan["accounting"][key] -= 1
    validate_episode_narration_plan(plan)
    with pytest.raises(ValueError, match="every beat is narrated exactly once"):
        validate_narration_plan_against_sources(plan, *sources_ep1)


def test_an_omitted_primary_beat_is_refused(sources_ep2: Sources) -> None:
    """Including the PRIMARY one nobody would notice was missing from the picture."""
    plan = _plan(sources_ep2)
    assert plan["units"][0]["emphasis"] == "PRIMARY"
    plan["units"] = plan["units"][1:]
    plan["units"][0]["unit_id"] = "unit_0001"
    plan["units"][0]["beat_id"] = "beat_0001"
    plan["accounting"] = {"beats_total": 1, "units_shown": 1, "units_unshown": 0}
    validate_episode_narration_plan(plan)
    with pytest.raises(ValueError):
        validate_narration_plan_against_sources(plan, *sources_ep2)


# ---- the seal


def test_key_order_does_not_change_a_plans_identity(sources_ep1: Sources) -> None:
    """The seal compares meaning, not the order a dict happened to be built in.

    Canonical encoding sorts keys, so a document rebuilt in reverse key order
    is byte-identical once encoded and must still verify. A seal that failed
    here would be testing Python dict ordering rather than the contract.
    """
    plan = _plan(sources_ep1)
    plan["units"][0] = {key: plan["units"][0][key] for key in reversed(list(plan["units"][0]))}
    plan["source"] = {key: plan["source"][key] for key in sorted(plan["source"], reverse=True)}
    assert validate_narration_plan_against_sources(plan, *sources_ep1) is plan


def test_the_seal_is_the_last_line_and_not_the_only_one() -> None:
    """An honest statement of what the seal is for.

    Every field V1 defines is already pinned by a named check above: the source
    block by :func:`_check_bindings`, each unit's story agreement, visibility,
    wording and fact identity by the per-unit checks, and the identifiers,
    ordering and accounting by the schema. So no V1 tamper reaches the seal
    without a named check having refused it first, which is why the tests above
    assert specific messages rather than a generic refusal.

    The seal earns its place by closing the degrees of freedom a *later* version
    might open -- a new field, a new derivation case, a wording table that grew
    -- where a named check does not yet exist. Byte equality with the derivation
    needs no maintenance to keep covering them.
    """
    sources = build_sources(1)
    from living_diorama.narration import build_episode_narration_plan_bytes
    from living_diorama.persistence.json_codec import dumps_canonical

    plan = _plan(sources)
    assert dumps_canonical(plan, "plan") == build_episode_narration_plan_bytes(*sources)


def test_the_seal_catches_an_added_unit(sources_ep0: Sources) -> None:
    """A unit with no beat behind it cannot survive re-derivation."""
    plan = _plan(sources_ep0)
    extra = copy.deepcopy(plan["units"][0])
    extra["unit_id"] = "unit_0002"
    extra["beat_id"] = "beat_0002"
    plan["units"].append(extra)
    plan["accounting"] = {"beats_total": 2, "units_shown": 0, "units_unshown": 2}
    with pytest.raises(ValueError):
        validate_narration_plan_against_sources(plan, *sources_ep0)


def test_the_cross_check_validates_the_sources_too(sources_ep1: Sources) -> None:
    """A broken source is refused before any comparison is attempted."""
    story, shots, export = sources_ep1
    plan = _plan(sources_ep1)
    broken = copy.deepcopy(story)
    broken["format"] = "something_else"
    with pytest.raises(ValueError, match="declares format"):
        validate_narration_plan_against_sources(plan, broken, shots, export)


def test_a_schema_invalid_plan_never_reaches_the_relationship_checks(
    sources_ep1: Sources,
) -> None:
    """Schema validity is the precondition, so it is proven first."""
    plan = _plan(sources_ep1)
    del plan["accounting"]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_narration_plan_against_sources(plan, *sources_ep1)
