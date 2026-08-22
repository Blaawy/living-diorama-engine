"""A plan's claims are proven against its sources, not taken on faith.

The independent V1 review demonstrated three live mutations the standalone
validator accepted: an invented emphasis, invented beat ids, and a plan whose
beat shots were replaced by one neutral hold while keeping the story binding.
Every one of those is reproduced here, against the cross-validator that now
exists to kill them -- along with the clock-binding attacks (a plausible 30 fps
document, a wholesale frame shift) that the digest binding exists to kill.
"""

import copy
from typing import Any

import pytest

from living_diorama.cinematic import (
    build_shot_direction_plan_document,
    validate_shot_direction_plan_against_story,
)


@pytest.fixture
def plan(story_ep0_to_ep1: dict[str, Any], motion_time: bytes) -> dict[str, Any]:
    """A genuine four-shot transition plan."""
    return build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)


# ------------------------------------------------------------------- positive


@pytest.mark.parametrize("story_name", ["story_ep0", "story_ep0_to_ep1", "story_ep1_to_ep2"])
def test_every_canonical_plan_cross_validates_against_its_sources(
    story_name: str, motion_time: bytes, request: pytest.FixtureRequest
) -> None:
    """The three real plans survive the full source-binding audit."""
    story = request.getfixturevalue(story_name)
    plan = build_shot_direction_plan_document(story, motion_time)
    assert validate_shot_direction_plan_against_story(plan, story, motion_time) is plan


# ------------------------------------------- the review's live V1 mutations


def test_an_invented_emphasis_is_refused_against_the_story(
    plan: dict[str, Any], story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """Review mutation A: emphasis = "BANANA" on a beat shot.

    The tightened schema already refuses the invented word; even a vocabulary
    member that merely differs from the story's own emphasis dies here.
    """
    beat_shot = next(s for s in plan["shots"] if s["kind"] == "BEAT")
    beat_shot["emphasis"] = "BANANA"
    with pytest.raises(ValueError):
        validate_shot_direction_plan_against_story(plan, story_ep0_to_ep1, motion_time)


def test_a_vocabulary_legal_but_wrong_emphasis_is_refused(
    plan: dict[str, Any], story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """Emphasis is copied from the story, never restated at a different level."""
    beat_shot = next(s for s in plan["shots"] if s["kind"] == "BEAT")
    wrong = "BACKGROUND" if beat_shot["emphasis"] != "BACKGROUND" else "PRIMARY"
    beat_shot["emphasis"] = wrong
    with pytest.raises(ValueError, match="emphasis is copied, never recomputed"):
        validate_shot_direction_plan_against_story(plan, story_ep0_to_ep1, motion_time)


def test_an_invented_beat_id_is_refused(
    plan: dict[str, Any], story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """Review mutation B: replace genuine beat ids with beat_fake_0001."""
    beat_shot = next(s for s in plan["shots"] if s["kind"] == "BEAT")
    beat_shot["source_beat_ids"] = ["beat_fake_0001"]
    with pytest.raises(ValueError, match="no beat is ever invented"):
        validate_shot_direction_plan_against_story(plan, story_ep0_to_ep1, motion_time)


def test_replacing_the_beat_shots_with_one_neutral_hold_is_refused(
    story_ep0: dict[str, Any],
    story_ep0_to_ep1: dict[str, Any],
    motion_time: bytes,
) -> None:
    """Review mutation C: a neutral plan wearing a transition story's binding.

    The mutated plan validates standalone -- that was the review's point -- but
    the cross-validator sees a story full of beats and a plan that accounts for
    none of them.
    """
    plan = build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)
    neutral = build_shot_direction_plan_document(story_ep0, motion_time)
    plan["shots"] = copy.deepcopy(neutral["shots"])
    plan["unshown"] = []
    with pytest.raises(ValueError, match="unaccounted"):
        validate_shot_direction_plan_against_story(plan, story_ep0_to_ep1, motion_time)


def test_an_omitted_beat_is_refused(story_adjacent: dict[str, Any], motion_time: bytes) -> None:
    """Dropping one beat from a merged shot leaves it unaccounted for."""
    merged_plan = build_shot_direction_plan_document(story_adjacent, motion_time)
    merged = next(s for s in merged_plan["shots"] if len(s["source_beat_ids"]) > 1)
    merged["source_beat_ids"] = merged["source_beat_ids"][:1]
    with pytest.raises(ValueError):
        validate_shot_direction_plan_against_story(merged_plan, story_adjacent, motion_time)


# ----------------------------------------------------------- story bindings


def test_a_plan_paired_with_a_different_story_is_refused(
    plan: dict[str, Any], story_ep1_to_ep2: dict[str, Any], motion_time: bytes
) -> None:
    """The digest names the document; a different story is not that document."""
    with pytest.raises(ValueError, match="does not direct that story"):
        validate_shot_direction_plan_against_story(plan, story_ep1_to_ep2, motion_time)


def test_a_tampered_story_digest_is_refused(
    plan: dict[str, Any], story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """A syntactically valid digest that names nothing on offer is refused."""
    plan["source"]["story_plan_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="does not direct that story"):
        validate_shot_direction_plan_against_story(plan, story_ep0_to_ep1, motion_time)


def test_a_mode_mismatch_is_refused(story_ep0: dict[str, Any], motion_time: bytes) -> None:
    """A baseline plan cannot claim a transition mode over a baseline story.

    The story digest still matches -- the story itself was not touched -- so
    this isolates the mode agreement check specifically.
    """
    plan = build_shot_direction_plan_document(story_ep0, motion_time)
    tampered = copy.deepcopy(plan)
    tampered["source"]["mode"] = "transition"
    tampered["source"]["previous_episode"] = 0
    tampered["source"]["episode"] = 1
    with pytest.raises(ValueError):
        validate_shot_direction_plan_against_story(tampered, story_ep0, motion_time)


# ----------------------------------------------------------- clock bindings


def test_no_plan_can_exist_against_an_alternate_clock(
    story_ep0_to_ep1: dict[str, Any], alternate_clock: Any
) -> None:
    """A self-consistent 30 fps document is plausible, and still not the clock.

    Under the V3 canonical pin the refusal moved all the way forward: the
    planner itself refuses the bytes, so a plan cut against an alternate clock
    cannot even be built for cross-validation to reject.
    """
    with pytest.raises(ValueError, match="not the canonical"):
        build_shot_direction_plan_document(story_ep0_to_ep1, alternate_clock(fps=30))


def test_no_plan_can_exist_against_a_shifted_clock(
    story_ep0_to_ep1: dict[str, Any], alternate_clock: Any
) -> None:
    """A wholesale frame shift that keeps its own arithmetic never builds."""
    with pytest.raises(ValueError, match="not the canonical"):
        build_shot_direction_plan_document(story_ep0_to_ep1, alternate_clock(start_frame=1001))


def test_no_plan_can_exist_against_a_resized_transition(
    story_ep0_to_ep1: dict[str, Any], alternate_clock: Any
) -> None:
    """Altered hold lengths whose arithmetic closes are refused at the source."""
    with pytest.raises(ValueError, match="not the canonical"):
        build_shot_direction_plan_document(story_ep0_to_ep1, alternate_clock(transition_frames=6))


def test_a_tampered_restated_timeline_is_refused(
    plan: dict[str, Any], story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """The restated clock must equal what the bound document resolves to.

    The tampering keeps the timeline self-consistent (the end hold shrinks as
    the transition grows, every bound stays legal), so only the comparison
    against the resolved source catches it.
    """
    plan["timeline"]["transition_frames"] += 24
    plan["timeline"]["end_hold_frames"] -= 24
    plan["timeline"]["transition_end"] += 24
    with pytest.raises(ValueError, match="resolves to"):
        validate_shot_direction_plan_against_story(plan, story_ep0_to_ep1, motion_time)


def test_a_tampered_motion_digest_is_refused(
    plan: dict[str, Any], story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """A syntactically valid motion digest that names other bytes is refused.

    Under the V3 pin the standalone validator inside cross-validation already
    knows the one canonical digest, so the refusal now names the pin.
    """
    plan["source"]["motion_time_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="not the canonical Phase 17 source"):
        validate_shot_direction_plan_against_story(plan, story_ep0_to_ep1, motion_time)


# --------------------------------------------------------- policy agreement


def test_a_beat_shown_on_the_wrong_anchor_is_refused(
    story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """The direction policy is closed; a re-aimed beat is a policy violation.

    The first transition's single-beat seal shot (the law change) is moved to
    another legal anchor -- the cross-validator refuses, because the policy
    table says where that beat kind is framed.
    """
    plan = build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)
    seal = next(s for s in plan["shots"] if s["camera_anchor_id"] == "CAM_SEAL_DETAIL")
    seal["camera_anchor_id"] = "CAM_P16_URBAN"
    with pytest.raises(ValueError, match="frames"):
        validate_shot_direction_plan_against_story(plan, story_ep0_to_ep1, motion_time)


def test_a_wrong_reason_code_for_the_derivation_case_is_refused(
    plan: dict[str, Any], story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """A single known beat's shot says BEAT_KIND_RULE, and nothing else."""
    single = next(s for s in plan["shots"] if len(s["source_beat_ids"]) == 1)
    single["reason_code"] = "ADJACENT_SAME_ANCHOR_MERGED"
    with pytest.raises(ValueError):
        validate_shot_direction_plan_against_story(plan, story_ep0_to_ep1, motion_time)


def test_an_illegal_unshown_reason_for_a_viewable_beat_is_refused(
    story_wide: dict[str, Any], motion_time: bytes
) -> None:
    """A beat with a viewpoint goes unshown only as budget-exhausted.

    The synthetic 22-beat story overflows the canonical transition, so a
    genuine budget-exhausted entry exists under the real clock; its reason is
    then forged to the empty-result code, isolating the reason-legality check.
    """
    plan = build_shot_direction_plan_document(story_wide, motion_time)
    assert plan["unshown"]
    plan["unshown"][0]["reason_code"] = "NOTHING_TO_EMPHASIZE"
    with pytest.raises(ValueError, match="goes unshown"):
        validate_shot_direction_plan_against_story(plan, story_wide, motion_time)


def test_the_empty_result_beat_cannot_be_framed(
    story_ep0: dict[str, Any], motion_time: bytes
) -> None:
    """Framing the statement that nothing was emphasized is framing nothing."""
    plan = build_shot_direction_plan_document(story_ep0, motion_time)
    empty_beat = story_ep0["beats"][0]["beat_id"]
    plan["unshown"] = []
    shot = plan["shots"][0]
    shot["kind"] = "BEAT"
    shot["reason_code"] = "BEAT_KIND_RULE"
    shot["emphasis"] = "BACKGROUND"
    shot["source_beat_ids"] = [empty_beat]
    with pytest.raises(ValueError, match="fabricate visibility"):
        validate_shot_direction_plan_against_story(plan, story_ep0, motion_time)


def test_a_plan_that_survives_the_named_checks_but_differs_is_refused(
    plan: dict[str, Any], story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """The re-derivation seal: durations are part of the contract too.

    One frame is moved between two beat shots. Every named check still passes
    -- tiling, anchors, reasons, emphasis, accounting -- and the plan is still
    not the plan these sources produce.
    """
    beats = [s for s in plan["shots"] if s["kind"] == "BEAT"]
    first, second = beats[0], beats[1]
    first["end_frame"] += 1
    second["start_frame"] += 1
    with pytest.raises(ValueError, match="deterministic derivation"):
        validate_shot_direction_plan_against_story(plan, story_ep0_to_ep1, motion_time)


def test_removing_the_establishing_bookends_is_refused_by_the_seal(
    story_adjacent: dict[str, Any], motion_time: bytes
) -> None:
    """The adversarial construction that survives every named check.

    The two-law story's lone seal shot stretched across the whole timeline:
    tiling holds, the loop trivially closes on itself, the anchor/reason/
    emphasis/accounting all agree with the story -- and it is still not the
    plan these sources produce, because the derivation opens and closes on
    the neutral hold.
    """
    plan = build_shot_direction_plan_document(story_adjacent, motion_time)
    seal_shot = next(s for s in plan["shots"] if s["camera_anchor_id"] == "CAM_SEAL_DETAIL")
    stretched = dict(seal_shot)
    stretched["shot_id"] = "shot_0001"
    stretched["start_frame"] = plan["timeline"]["start_frame"]
    stretched["end_frame"] = plan["timeline"]["end_frame"]
    other_beats = [
        beat for shot in plan["shots"] for beat in shot["source_beat_ids"] if shot is not seal_shot
    ]
    plan["shots"] = [stretched]
    plan["unshown"] = sorted(
        list(plan["unshown"])
        + [{"beat_id": b, "reason_code": "TRANSITION_BUDGET_EXHAUSTED"} for b in other_beats],
        key=lambda entry: entry["beat_id"],
    )
    with pytest.raises(ValueError, match="deterministic derivation"):
        validate_shot_direction_plan_against_story(plan, story_adjacent, motion_time)


def test_reordered_unshown_entries_are_refused_by_the_seal(
    story_wide: dict[str, Any], motion_time: bytes
) -> None:
    """The unshown list's order is part of the canonical bytes too.

    The synthetic 22-beat story leaves two beats unshown under the canonical
    clock; swapping their order changes no named claim and is still not the
    plan the sources produce.
    """
    plan = build_shot_direction_plan_document(story_wide, motion_time)
    assert len(plan["unshown"]) >= 2
    plan["unshown"] = list(reversed(plan["unshown"]))
    with pytest.raises(ValueError, match="deterministic derivation"):
        validate_shot_direction_plan_against_story(plan, story_wide, motion_time)


def test_an_episode_lie_with_a_matching_digest_is_refused(
    plan: dict[str, Any], story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """Episode numbers are proven against the story, not taken from the plan.

    Both fields are bumped together so the standalone consecutive-episode rule
    still passes and the digest is untouched; only the story comparison fires.
    """
    plan["source"]["episode"] += 1
    plan["source"]["previous_episode"] += 1
    with pytest.raises(ValueError, match="describes episode"):
        validate_shot_direction_plan_against_story(plan, story_ep0_to_ep1, motion_time)


def test_an_invented_unshown_beat_id_is_refused(
    plan: dict[str, Any], story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """The unshown list cannot invent beats either."""
    plan["unshown"] = [{"beat_id": "beat_9999", "reason_code": "TRANSITION_BUDGET_EXHAUSTED"}]
    with pytest.raises(ValueError, match="no beat is ever invented"):
        validate_shot_direction_plan_against_story(plan, story_ep0_to_ep1, motion_time)


def test_a_budget_reason_forged_onto_the_empty_result_beat_is_refused(
    story_ep0: dict[str, Any], motion_time: bytes
) -> None:
    """The empty-result beat's one legal unshown reason is enforced both ways."""
    plan = build_shot_direction_plan_document(story_ep0, motion_time)
    plan["unshown"][0]["reason_code"] = "TRANSITION_BUDGET_EXHAUSTED"
    with pytest.raises(ValueError, match="goes unshown"):
        validate_shot_direction_plan_against_story(plan, story_ep0, motion_time)


def test_beats_swapped_across_shots_are_refused(
    story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """History reordered across shots never survives.

    With the canonical stories, a swap that keeps every anchor-policy check
    happy is not even constructible -- same kind means same anchor means one
    merged shot -- so the swap is refused at the policy layer before the rank
    check ever speaks, and the rank check remains the backstop for any future
    story where two kinds share an anchor.
    """
    plan = build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)
    beat_shots = [s for s in plan["shots"] if s["kind"] == "BEAT"]
    first, second = beat_shots[0], beat_shots[1]
    first["source_beat_ids"], second["source_beat_ids"] = (
        second["source_beat_ids"],
        first["source_beat_ids"],
    )
    with pytest.raises(ValueError):
        validate_shot_direction_plan_against_story(plan, story_ep0_to_ep1, motion_time)


def test_a_budget_exhausted_plan_cross_validates_under_the_canonical_clock(
    story_wide: dict[str, Any], motion_time: bytes
) -> None:
    """The truncated path is positively source-verified under the real clock.

    Twenty-two alternating-anchor beats overflow the canonical transition's
    twenty-shot capacity; the un-forged plan -- twenty beat shots, two
    TRANSITION_BUDGET_EXHAUSTED entries -- must pass the full cross-validation
    against the canonical bytes, accounting and re-derivation seal included.
    """
    plan = build_shot_direction_plan_document(story_wide, motion_time)
    assert len(plan["unshown"]) == 2
    assert all(entry["reason_code"] == "TRANSITION_BUDGET_EXHAUSTED" for entry in plan["unshown"])
    assert validate_shot_direction_plan_against_story(plan, story_wide, motion_time) is plan
