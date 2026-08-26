"""Cross-check: the plan's claims must be true of its actual sources.

Every test here builds real canonical documents from the locked upstream
planners and tampers with exactly one honest claim, so what is proven is the
cross-check's refusal of a real forgery -- never a hand-built fixture that
merely looks plausible.
"""

import copy
from typing import Any

import pytest

from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.presentation import build_episode_presentation_plan_document
from living_diorama.presentation.presentation_cross_check import (
    validate_episode_presentation_plan_against_sources,
)


def _verify(sources: tuple[dict[str, Any], ...], plan: dict[str, Any]) -> dict[str, Any]:
    delivery, narration, shots, realization, story, export = sources
    return validate_episode_presentation_plan_against_sources(
        plan, delivery, narration, shots, realization, story, export
    )


# ---- the honest cases pass


@pytest.mark.parametrize("episode", [0, 1, 2])
def test_every_canonical_plan_is_source_verified(
    episode: int, request: pytest.FixtureRequest
) -> None:
    """Every canonical plan is source verified."""
    sources = request.getfixturevalue(f"sources_ep{episode}")
    plan = request.getfixturevalue(f"plan_ep{episode}")
    assert _verify(sources, plan) is plan


# ---- gate 1: the locked Phase 25 source proof


def test_a_forged_delivery_plan_that_is_standalone_valid_is_refused_by_gate_one(
    sources_ep1: tuple[dict[str, Any], ...], plan_ep1: dict[str, Any]
) -> None:
    """A widened slot, with accounting patched to still close, dies at gate 1.

    Without the reused Phase 25 gate, this forgery would be standalone-valid
    and would only be caught by this plan's own re-derivation seal -- which
    would still refuse it, but for the wrong reason if the gate were skipped.
    This proves the gate itself is what stops it, not merely the seal.
    """
    delivery, narration, shots, realization, story, export = sources_ep1
    forged = copy.deepcopy(delivery)
    forged["deliveries"][0]["end_frame"] += 1
    forged["deliveries"][1]["start_frame"] += 1
    with pytest.raises(ValueError):
        validate_episode_presentation_plan_against_sources(
            plan_ep1, forged, narration, shots, realization, story, export
        )


def test_a_wrong_shot_plan_at_the_phase_25_gate_is_refused(
    sources_ep1: tuple[dict[str, Any], ...],
    sources_ep2: tuple[dict[str, Any], ...],
    plan_ep1: dict[str, Any],
) -> None:
    """A wrong shot plan at the phase 25 gate is refused."""
    delivery, narration, _shots, realization, story, export = sources_ep1
    _delivery2, _narration2, wrong_shots, _realization2, _story2, _export2 = sources_ep2
    with pytest.raises(ValueError):
        validate_episode_presentation_plan_against_sources(
            plan_ep1, delivery, narration, wrong_shots, realization, story, export
        )


def test_a_wrong_narration_plan_at_the_phase_25_gate_is_refused(
    sources_ep1: tuple[dict[str, Any], ...],
    sources_ep2: tuple[dict[str, Any], ...],
    plan_ep1: dict[str, Any],
) -> None:
    """A wrong narration plan at the phase 25 gate is refused."""
    delivery, _narration, shots, realization, story, export = sources_ep1
    _delivery2, wrong_narration, _shots2, _realization2, _story2, _export2 = sources_ep2
    with pytest.raises(ValueError):
        validate_episode_presentation_plan_against_sources(
            plan_ep1, delivery, wrong_narration, shots, realization, story, export
        )


# ---- gate 2: the locked Phase 26 source proof


def test_narration_kind_and_text_source_forged_together_is_refused_by_gate_two(
    sources_ep1: tuple[dict[str, Any], ...], plan_ep1: dict[str, Any]
) -> None:
    """A TEMPLATE unit rewritten as a FACT kind, standalone-valid throughout.

    Both ``kind`` and ``text_source`` are changed together so the narration
    plan's own schema (which only proves the two agree with each other) never
    objects. Only the actual story beat -- proven true by the locked Phase 26
    gate -- can catch that the unit no longer restates it.
    """
    delivery, narration, shots, realization, story, export = sources_ep1
    forged_narration = copy.deepcopy(narration)
    unit = forged_narration["units"][1]
    assert unit["kind"] == "DURABLE_CONSEQUENCE"
    unit["kind"] = "WALL_STATE_CHANGE"
    unit["text_source"] = "NARRATION_TEMPLATE"
    unit["fact_id"] = None
    with pytest.raises(ValueError):
        validate_episode_presentation_plan_against_sources(
            plan_ep1, delivery, forged_narration, shots, realization, story, export
        )


def test_a_standalone_valid_forged_realized_text_is_refused_by_gate_two(
    sources_ep1: tuple[dict[str, Any], ...], plan_ep1: dict[str, Any]
) -> None:
    """A safe-looking sentence, with the lineage digests copied honestly."""
    delivery, narration, shots, realization, story, export = sources_ep1
    forged_realization = copy.deepcopy(realization)
    forged_realization["realizations"][0]["realized_text"] = "A safe but incorrect sentence."
    with pytest.raises(ValueError):
        validate_episode_presentation_plan_against_sources(
            plan_ep1, delivery, narration, shots, forged_realization, story, export
        )


def test_a_wrong_story_plan_at_the_phase_26_gate_is_refused(
    sources_ep1: tuple[dict[str, Any], ...],
    sources_ep2: tuple[dict[str, Any], ...],
    plan_ep1: dict[str, Any],
) -> None:
    """A wrong story plan at the phase 26 gate is refused."""
    delivery, narration, shots, realization, _story, export = sources_ep1
    _delivery2, _narration2, _shots2, _realization2, wrong_story, _export2 = sources_ep2
    with pytest.raises(ValueError):
        validate_episode_presentation_plan_against_sources(
            plan_ep1, delivery, narration, shots, realization, wrong_story, export
        )


def test_a_wrong_render_export_at_the_phase_26_gate_is_refused(
    sources_ep1: tuple[dict[str, Any], ...],
    sources_ep2: tuple[dict[str, Any], ...],
    plan_ep1: dict[str, Any],
) -> None:
    """A wrong render export at the phase 26 gate is refused."""
    delivery, narration, shots, realization, story, _export = sources_ep1
    _delivery2, _narration2, _shots2, _realization2, _story2, wrong_export = sources_ep2
    with pytest.raises(ValueError):
        validate_episode_presentation_plan_against_sources(
            plan_ep1, delivery, narration, shots, realization, story, wrong_export
        )


def test_a_wrong_realization_digest_is_refused(
    sources_ep1: tuple[dict[str, Any], ...],
    sources_ep2: tuple[dict[str, Any], ...],
    plan_ep1: dict[str, Any],
) -> None:
    """A wrong realization digest is refused."""
    delivery, narration, shots, _realization, story, export = sources_ep1
    _delivery2, _narration2, _shots2, wrong_realization, _story2, _export2 = sources_ep2
    with pytest.raises(ValueError):
        validate_episode_presentation_plan_against_sources(
            plan_ep1, delivery, narration, shots, wrong_realization, story, export
        )


# ---- honest rebuild: geometry governed only by the locked policy


def test_an_honest_narration_and_realization_rebuild_still_verifies(
    sources_ep1: tuple[dict[str, Any], ...],
) -> None:
    """Rebuilding the whole chain again from the same export changes nothing.

    A genuinely re-derived set of documents -- not a forgery -- must still
    pass every gate and re-derive byte for byte, because the derivation is
    deterministic. ``sources_ep1`` is itself one such honest rebuild, freshly
    derived by the conftest's own call to the locked upstream planners.
    """
    delivery, narration, shots, realization, story, export = sources_ep1
    plan = build_episode_presentation_plan_document(delivery, narration, realization)
    verified = validate_episode_presentation_plan_against_sources(
        plan, delivery, narration, shots, realization, story, export
    )
    assert verified is plan


# ---- this plan's own bindings


def test_a_forged_delivery_digest_in_the_plan_itself_is_refused(
    sources_ep1: tuple[dict[str, Any], ...], plan_ep1: dict[str, Any]
) -> None:
    """A forged delivery digest in the plan itself is refused."""
    tampered = copy.deepcopy(plan_ep1)
    tampered["source"]["delivery_plan_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="does not present that document"):
        _verify(sources_ep1, tampered)


def test_a_forged_narration_digest_in_the_plan_itself_is_refused(
    sources_ep1: tuple[dict[str, Any], ...], plan_ep1: dict[str, Any]
) -> None:
    """A forged narration digest in the plan itself is refused."""
    tampered = copy.deepcopy(plan_ep1)
    tampered["source"]["narration_plan_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="does not present that document"):
        _verify(sources_ep1, tampered)


def test_a_forged_realization_digest_in_the_plan_itself_is_refused(
    sources_ep1: tuple[dict[str, Any], ...], plan_ep1: dict[str, Any]
) -> None:
    """A forged realization digest in the plan itself is refused."""
    tampered = copy.deepcopy(plan_ep1)
    tampered["source"]["realization_plan_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="does not present that document"):
        _verify(sources_ep1, tampered)


def test_a_forged_motion_time_digest_is_refused(
    sources_ep1: tuple[dict[str, Any], ...], plan_ep1: dict[str, Any]
) -> None:
    """A forged motion time digest is refused."""
    tampered = copy.deepcopy(plan_ep1)
    tampered["source"]["motion_time_sha256"] = "d" * 64
    with pytest.raises(ValueError, match="Motion & Time"):
        _verify(sources_ep1, tampered)


def test_a_timeline_that_disagrees_with_the_delivery_plans_is_refused(
    sources_ep1: tuple[dict[str, Any], ...], plan_ep1: dict[str, Any]
) -> None:
    """A timeline that disagrees with the delivery plans is refused."""
    tampered = copy.deepcopy(plan_ep1)
    tampered["timeline"]["fps"] = 30
    tampered["timeline"]["start_frame"] = tampered["timeline"]["start_frame"]
    with pytest.raises(ValueError):
        _verify(sources_ep1, tampered)


def test_a_wrong_episode_binding_is_refused(
    sources_ep0: tuple[dict[str, Any], ...], plan_ep1: dict[str, Any]
) -> None:
    """Episode 1's plan offered against episode 0's sources."""
    with pytest.raises(ValueError):
        _verify(sources_ep0, plan_ep1)


def test_an_omitted_window_relative_to_the_actual_sources_is_refused(
    sources_ep1: tuple[dict[str, Any], ...], plan_ep1: dict[str, Any]
) -> None:
    """Standalone-valid (accounting patched to match), but proven wrong here."""
    tampered = copy.deepcopy(plan_ep1)
    dropped = tampered["windows"].pop()
    tampered["accounting"]["windows_total"] = len(tampered["windows"])
    tampered["segments"][-1]["presentation_end_frame"] = dropped["presentation_start_frame"] - 1
    tampered["accounting"]["presentation_frames_total"] = dropped["presentation_start_frame"] - 1
    with pytest.raises(ValueError):
        _verify(sources_ep1, tampered)


def test_an_extra_window_relative_to_the_actual_sources_is_refused(
    sources_ep0: tuple[dict[str, Any], ...], plan_ep0: dict[str, Any]
) -> None:
    """An extra window relative to the actual sources is refused."""
    tampered = copy.deepcopy(plan_ep0)
    extra = copy.deepcopy(tampered["windows"][0])
    extra["window_id"] = "window_0002"
    extra["unit_id"] = "unit_0002"
    extra["realization_id"] = "realization_0002"
    tampered["windows"].append(extra)
    tampered["accounting"]["windows_total"] = len(tampered["windows"])
    with pytest.raises(ValueError):
        _verify(sources_ep0, tampered)


def test_the_seal_refuses_a_forgery_no_named_check_names(
    sources_ep2: tuple[dict[str, Any], ...], plan_ep2: dict[str, Any]
) -> None:
    """Shrink the leading hold by one frame and grow the closing hold by one.

    Both segments still close on their own arithmetic, the tiling and
    presentation cursors still close (the plan's own standalone schema
    accepts it), every id and binding still agrees -- only the exact policy
    arithmetic is wrong, which only the byte-for-byte seal can catch.
    """
    tampered = copy.deepcopy(plan_ep2)
    segments = tampered["segments"]
    leading_hold = segments[0]
    trailing_hold = segments[2]
    assert leading_hold["dwell_frames"] > 1
    assert trailing_hold["dwell_frames"] > 1
    leading_hold["dwell_frames"] -= 1
    leading_hold["presentation_end_frame"] -= 1
    segments[1]["presentation_start_frame"] -= 1
    segments[1]["presentation_end_frame"] -= 1
    trailing_hold["presentation_start_frame"] -= 1
    trailing_hold["dwell_frames"] += 1
    trailing_hold["presentation_end_frame"] += 0
    tampered["windows"][0]["presentation_end_frame"] -= 1
    tampered["windows"][1]["presentation_start_frame"] -= 1
    from living_diorama.presentation import validate_episode_presentation_plan

    validate_episode_presentation_plan(tampered)  # still standalone-valid
    with pytest.raises(ValueError, match="deterministic derivation"):
        _verify(sources_ep2, tampered)


def test_a_window_one_frame_short_of_the_reviewed_floor_is_refused(
    sources_ep1: tuple[dict[str, Any], ...], plan_ep1: dict[str, Any]
) -> None:
    """A fact-backed window one frame short of its reviewed floor.

    Every id, count and binding still agrees; only the seal, which closes on
    the exact policy arithmetic, can catch a floor shaved by one frame.
    """
    tampered = copy.deepcopy(plan_ep1)
    tampered["windows"][1]["presentation_end_frame"] -= 1
    with pytest.raises(ValueError):
        _verify(sources_ep1, tampered)


def test_a_template_unit_given_fact_capacity_is_refused(
    sources_ep1: tuple[dict[str, Any], ...], plan_ep1: dict[str, Any]
) -> None:
    """A TEMPLATE unit's window inflated to the FACT floor.

    unit_0001 is NARRATION_TEMPLATE (floor 144); its hold is inflated to the
    360-frame FACT floor instead, with every downstream coordinate and
    accounting total shifted to stay internally consistent (standalone-valid
    throughout). Only the seal, which knows which floor a TEMPLATE unit
    actually owns, can catch a unit given the wrong class's capacity.
    """
    tampered = copy.deepcopy(plan_ep1)
    held = tampered["segments"][1]
    assert held["semantic_start_frame"] == held["semantic_end_frame"] == 25
    old_dwell = held["dwell_frames"]
    new_dwell = old_dwell + (360 - 144)  # promote unit_0001's window to the FACT floor
    shift = new_dwell - old_dwell
    held["dwell_frames"] = new_dwell
    held["presentation_end_frame"] += shift
    for later in tampered["segments"][2:]:
        later["presentation_start_frame"] += shift
        later["presentation_end_frame"] += shift
    for window in tampered["windows"]:
        if window["presentation_start_frame"] > held["presentation_start_frame"]:
            window["presentation_start_frame"] += shift
        if window["presentation_end_frame"] >= held["presentation_start_frame"]:
            window["presentation_end_frame"] += shift
    tampered["accounting"]["presentation_frames_total"] += shift
    from living_diorama.presentation import validate_episode_presentation_plan

    validate_episode_presentation_plan(tampered)  # still standalone-valid
    with pytest.raises(ValueError, match="deterministic derivation"):
        _verify(sources_ep1, tampered)


def test_a_hold_moved_off_its_onset_frame_is_refused(
    sources_ep1: tuple[dict[str, Any], ...], plan_ep1: dict[str, Any]
) -> None:
    """unit_0002's 325-frame hold relocated from its onset (61) to frame 70.

    The policy places a unit's entire hold on its delivery slot's own
    ``start_frame`` and nowhere else. Here the same 325 extra frames of
    capacity are moved nine semantic frames downstream, inside the same
    unit's span but off its onset. The total span across frames [61, 95] is
    kept at exactly 360 (unchanged), so every segment closes on its own
    arithmetic, the tiling is exact, no two adjacent segments share a dwell,
    and -- because the misplaced hold still occupies a single semantic frame
    -- the schema's own dilation ban does not fire either: the document is
    standalone-valid. Because the total span is unchanged, the presentation
    image of the slot is *also* unchanged, so even both windows survive
    untouched; only the re-derivation seal, which knows the real delivery
    slot's onset is frame 61, can catch a hold sitting on frame 70 instead.
    """
    tampered = copy.deepcopy(plan_ep1)
    segments = tampered["segments"]
    before, onset_hold, after = segments[2], segments[3], segments[4]
    assert (before["semantic_start_frame"], before["semantic_end_frame"]) == (26, 60)
    assert (onset_hold["semantic_start_frame"], onset_hold["dwell_frames"]) == (61, 326)
    assert (after["semantic_start_frame"], after["semantic_end_frame"]) == (62, 95)

    # Merge [26,60] and the true onset frame 61 into one dwell-1 run, so the
    # misplaced hold can sit on frame 70 instead without ever creating an
    # adjacent same-dwell pair (which would be refused for an unrelated
    # reason -- non-minimal RLE -- before the seal is ever reached).
    merged_end = 69
    merged_length = merged_end - before["semantic_start_frame"] + 1  # 26..69
    merged_span = merged_length * 1
    before["semantic_end_frame"] = merged_end
    before["presentation_end_frame"] = before["presentation_start_frame"] + merged_span - 1

    misplaced_start = onset_hold["presentation_start_frame"] + merged_length - (60 - 26 + 1)
    misplaced = {
        "dwell_frames": onset_hold["dwell_frames"],
        "presentation_end_frame": misplaced_start + onset_hold["dwell_frames"] - 1,
        "presentation_start_frame": misplaced_start,
        "segment_id": "segment_0004",
        "semantic_end_frame": 70,
        "semantic_start_frame": 70,
    }
    after["semantic_start_frame"] = 71
    after["presentation_start_frame"] = misplaced["presentation_end_frame"] + 1
    after["presentation_end_frame"] = after["presentation_start_frame"] + (95 - 71 + 1) - 1
    after["segment_id"] = "segment_0005"

    tampered["segments"] = [segments[0], segments[1], before, misplaced, after, *segments[5:]]
    for position, segment in enumerate(tampered["segments"], start=1):
        segment["segment_id"] = f"segment_{position:04d}"

    from living_diorama.presentation import validate_episode_presentation_plan

    validated = validate_episode_presentation_plan(tampered)  # still standalone-valid
    assert validated["accounting"] == plan_ep1["accounting"]
    assert validated["windows"] == plan_ep1["windows"]
    with pytest.raises(ValueError, match="deterministic derivation"):
        _verify(sources_ep1, tampered)


def test_a_holds_capacity_split_across_two_frames_is_refused(
    sources_ep1: tuple[dict[str, Any], ...], plan_ep1: dict[str, Any]
) -> None:
    """unit_0003's single 95-frame hold split into two smaller holds.

    Instead of one hold of 95 extra frames on frame 96 (dwell 96), the same
    95 frames of extra capacity are split into 50 extra frames on frame 96
    (dwell 51) and 45 extra frames on frame 120 (dwell 46) -- two distinct,
    individually single-semantic-frame segments. Each one alone satisfies the
    schema's ``dwell_frames > 1 implies one semantic frame`` rule, so that
    rule alone cannot reject a *split* hold; the total span across [96, 144]
    is kept at 192 (unchanged), so both windows and the grand total survive
    untouched. Only the re-derivation seal, which knows the policy grants one
    hold per unit and places all of it on the one onset frame, refuses this.
    """
    tampered = copy.deepcopy(plan_ep1)
    segments = tampered["segments"]
    onset_hold, tail = segments[5], segments[6]
    assert (onset_hold["semantic_start_frame"], onset_hold["dwell_frames"]) == (96, 96)
    assert (tail["semantic_start_frame"], tail["semantic_end_frame"]) == (97, 192)

    start = onset_hold["presentation_start_frame"]
    first_hold = {
        "dwell_frames": 51,
        "presentation_end_frame": start + 51 - 1,
        "presentation_start_frame": start,
        "segment_id": "segment_0006",
        "semantic_end_frame": 96,
        "semantic_start_frame": 96,
    }
    gap_length = 119 - 97 + 1
    gap = {
        "dwell_frames": 1,
        "presentation_end_frame": first_hold["presentation_end_frame"] + gap_length,
        "presentation_start_frame": first_hold["presentation_end_frame"] + 1,
        "segment_id": "segment_0007",
        "semantic_end_frame": 119,
        "semantic_start_frame": 97,
    }
    second_hold = {
        "dwell_frames": 46,
        "presentation_end_frame": gap["presentation_end_frame"] + 46,
        "presentation_start_frame": gap["presentation_end_frame"] + 1,
        "segment_id": "segment_0008",
        "semantic_end_frame": 120,
        "semantic_start_frame": 120,
    }
    tail_length = 192 - 121 + 1
    remainder = {
        "dwell_frames": 1,
        "presentation_end_frame": second_hold["presentation_end_frame"] + tail_length,
        "presentation_start_frame": second_hold["presentation_end_frame"] + 1,
        "segment_id": "segment_0009",
        "semantic_end_frame": 192,
        "semantic_start_frame": 121,
    }
    tampered["segments"] = [*segments[:5], first_hold, gap, second_hold, remainder]
    tampered["accounting"]["segments_total"] = len(tampered["segments"])

    from living_diorama.presentation import validate_episode_presentation_plan

    validated = validate_episode_presentation_plan(tampered)  # still standalone-valid
    assert (
        validated["accounting"]["presentation_frames_total"]
        == (plan_ep1["accounting"]["presentation_frames_total"])
    )
    assert validated["windows"] == plan_ep1["windows"]
    with pytest.raises(ValueError, match="deterministic derivation"):
        _verify(sources_ep1, tampered)


def test_a_fact_unit_given_template_capacity_is_refused(
    sources_ep1: tuple[dict[str, Any], ...], plan_ep1: dict[str, Any]
) -> None:
    """A MEMORY_FACT_SUMMARY unit's window shrunk to the TEMPLATE floor.

    The inverse of the TEMPLATE-given-FACT-capacity forgery above:
    unit_0002 is MEMORY_FACT_SUMMARY (floor 360); its hold is shrunk to the
    144-frame TEMPLATE floor instead, with every downstream coordinate and
    accounting total shifted to stay internally consistent (standalone-valid
    throughout). This is a genuine 360 -> 144 class substitution, not a
    one-frame shave off the real floor. Only the seal, which knows which
    floor a FACT unit actually owns, can catch a unit given the wrong
    class's (smaller) capacity.
    """
    tampered = copy.deepcopy(plan_ep1)
    held = tampered["segments"][3]
    assert held["semantic_start_frame"] == held["semantic_end_frame"] == 61
    old_dwell = held["dwell_frames"]
    assert old_dwell == 326
    new_dwell = 1 + (144 - 35)  # demote unit_0002's window to the TEMPLATE floor
    shift = new_dwell - old_dwell
    held["dwell_frames"] = new_dwell
    held["presentation_end_frame"] += shift
    for later in tampered["segments"][4:]:
        later["presentation_start_frame"] += shift
        later["presentation_end_frame"] += shift
    for window in tampered["windows"]:
        if window["presentation_start_frame"] > held["presentation_start_frame"]:
            window["presentation_start_frame"] += shift
        if window["presentation_end_frame"] >= held["presentation_start_frame"]:
            window["presentation_end_frame"] += shift
    tampered["accounting"]["presentation_frames_total"] += shift

    from living_diorama.presentation import validate_episode_presentation_plan

    validate_episode_presentation_plan(tampered)  # still standalone-valid
    with pytest.raises(ValueError, match="deterministic derivation"):
        _verify(sources_ep1, tampered)


def test_a_byte_identical_plan_from_a_different_object_still_verifies(
    sources_ep1: tuple[dict[str, Any], ...], plan_ep1: dict[str, Any]
) -> None:
    """Cross-check compares canonical bytes, not object identity."""
    rebuilt = dumps_canonical(copy.deepcopy(plan_ep1), "presentation plan")
    from living_diorama.persistence.json_codec import loads_canonical

    reloaded = loads_canonical(rebuilt, "presentation plan")
    verified = _verify(sources_ep1, reloaded)
    assert verified == plan_ep1
