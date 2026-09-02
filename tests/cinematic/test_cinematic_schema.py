"""The shot plan format refuses what it does not describe.

Every test takes a genuine, valid plan and breaks exactly one thing, so a failure
names the rule that stopped mattering.
"""

from typing import Any

import pytest

from living_diorama.cinematic import (
    build_shot_direction_plan_document,
    validate_shot_direction_plan,
    validate_shot_direction_plan_v2,
)
from living_diorama.cinematic.camera_movement_planner import plan_camera_movements


@pytest.fixture
def plan(story_ep0_to_ep1: dict[str, Any], motion_time: bytes) -> dict[str, Any]:
    """A genuine four-shot transition plan for the tests to break one rule of."""
    return build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)


@pytest.fixture
def baseline(story_ep0: dict[str, Any], motion_time: bytes) -> dict[str, Any]:
    """A genuine single-shot baseline plan."""
    return build_shot_direction_plan_document(story_ep0, motion_time)


# ------------------------------------------------------------------- positive


def test_a_freshly_built_plan_validates(plan: dict[str, Any]) -> None:
    """A freshly built plan validates."""
    assert validate_shot_direction_plan(plan) is plan


def test_a_baseline_plan_validates(baseline: dict[str, Any]) -> None:
    """A baseline plan validates."""
    assert validate_shot_direction_plan(baseline) is baseline


# ------------------------------------------------------------------- envelope


def test_a_missing_top_level_key_is_refused(plan: dict[str, Any]) -> None:
    """A missing top level key is refused."""
    del plan["shots"]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_shot_direction_plan(plan)


def test_an_unexpected_top_level_key_is_refused(plan: dict[str, Any]) -> None:
    """An extra key means something this contract does not describe wrote it."""
    plan["mood"] = "tense"
    with pytest.raises(ValueError, match="unexpected keys"):
        validate_shot_direction_plan(plan)


def test_a_wrong_format_tag_is_refused(plan: dict[str, Any]) -> None:
    """A wrong format tag is refused."""
    plan["format"] = "living_diorama_episode_story_plan"
    with pytest.raises(ValueError, match="declares format"):
        validate_shot_direction_plan(plan)


def test_an_unsupported_schema_version_is_refused(plan: dict[str, Any]) -> None:
    """An unsupported schema version is refused."""
    plan["schema_version"] = 2
    with pytest.raises(ValueError, match="unsupported schema version"):
        validate_shot_direction_plan(plan)


def test_a_non_dict_plan_is_refused() -> None:
    """A non dict plan is refused."""
    with pytest.raises(TypeError):
        validate_shot_direction_plan([1, 2, 3])


# ------------------------------------------------------------ story binding


def test_an_unsupported_story_schema_version_is_refused(plan: dict[str, Any]) -> None:
    """A plan derived from a story format this build cannot direct is refused."""
    plan["source"]["story_schema_version"] = 99
    with pytest.raises(ValueError, match="story schema version"):
        validate_shot_direction_plan(plan)


def test_a_malformed_story_digest_is_refused(plan: dict[str, Any]) -> None:
    """A malformed story digest is refused."""
    plan["source"]["story_plan_sha256"] = "not-a-hash"
    with pytest.raises((ValueError, TypeError)):
        validate_shot_direction_plan(plan)


def test_a_missing_story_digest_is_refused(plan: dict[str, Any]) -> None:
    """Without it the plan could be silently paired with another story plan."""
    del plan["source"]["story_plan_sha256"]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_shot_direction_plan(plan)


def test_a_baseline_naming_a_previous_episode_is_refused(
    baseline: dict[str, Any],
) -> None:
    """A baseline naming a previous episode is refused."""
    baseline["source"]["previous_episode"] = 0
    with pytest.raises(ValueError, match="names a previous episode"):
        validate_shot_direction_plan(baseline)


def test_a_baseline_for_a_later_episode_is_refused(baseline: dict[str, Any]) -> None:
    """A baseline for a later episode is refused."""
    baseline["source"]["episode"] = 2
    with pytest.raises(ValueError, match="episode 0 only"):
        validate_shot_direction_plan(baseline)


def test_a_transition_binding_non_consecutive_episodes_is_refused(
    plan: dict[str, Any],
) -> None:
    """A transition binding non consecutive episodes is refused."""
    plan["source"]["previous_episode"] = 5
    with pytest.raises(ValueError, match="consecutive episodes"):
        validate_shot_direction_plan(plan)


def test_an_unknown_source_mode_is_refused(plan: dict[str, Any]) -> None:
    """An unknown source mode is refused."""
    plan["source"]["mode"] = "montage"
    with pytest.raises(ValueError, match="expected 'baseline' or 'transition'"):
        validate_shot_direction_plan(plan)


# ----------------------------------------------------- motion clock binding


def test_a_wrong_motion_format_is_refused(plan: dict[str, Any]) -> None:
    """A plan claiming to be cut against something else is refused."""
    plan["source"]["motion_time_format"] = "living_diorama_render_export"
    with pytest.raises(ValueError, match="motion format"):
        validate_shot_direction_plan(plan)


def test_an_unsupported_motion_schema_version_is_refused(plan: dict[str, Any]) -> None:
    """An unsupported motion schema version is refused."""
    plan["source"]["motion_time_schema_version"] = 9
    with pytest.raises(ValueError, match="motion schema version"):
        validate_shot_direction_plan(plan)


def test_a_malformed_motion_digest_is_refused(plan: dict[str, Any]) -> None:
    """A malformed motion digest is refused."""
    plan["source"]["motion_time_sha256"] = "yes"
    with pytest.raises((ValueError, TypeError)):
        validate_shot_direction_plan(plan)


def test_a_missing_motion_binding_is_refused(plan: dict[str, Any]) -> None:
    """Without it the plan could be silently paired with an invented clock."""
    del plan["source"]["motion_time_sha256"]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_shot_direction_plan(plan)


def test_a_well_formed_foreign_clock_digest_is_refused(plan: dict[str, Any]) -> None:
    """A 64-hex digest that is not the canonical source is refused by the pin."""
    plan["source"]["motion_time_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="not the canonical Phase 17 source"):
        validate_shot_direction_plan(plan)


def test_a_tampered_catalogue_binding_is_refused(plan: dict[str, Any]) -> None:
    """The camera set the plan was cut for must be the approved one."""
    plan["source"]["catalogue_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="not the approved canonical catalogue"):
        validate_shot_direction_plan(plan)


def test_a_missing_catalogue_binding_is_refused(plan: dict[str, Any]) -> None:
    """A missing catalogue binding is refused."""
    del plan["source"]["catalogue_sha256"]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_shot_direction_plan(plan)


# ---------------------------------------------------------- timeline binding


def test_a_missing_timeline_field_is_refused(plan: dict[str, Any]) -> None:
    """A missing timeline field is refused."""
    del plan["timeline"]["fps"]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_shot_direction_plan(plan)


def test_a_timeline_that_breaks_its_own_arithmetic_is_refused(plan: dict[str, Any]) -> None:
    """The derived boundaries must equal Phase 17's arithmetic over the holds."""
    plan["timeline"]["transition_start"] = 900
    with pytest.raises(ValueError, match="disagrees with its own phases"):
        validate_shot_direction_plan(plan)


def test_a_shifted_whole_timeline_is_refused_by_the_shots(plan: dict[str, Any]) -> None:
    """A wholesale +1000 shift keeps the arithmetic but strands every shot.

    The timeline section alone stays self-consistent, which is exactly why the
    digest binding exists -- but the plan as a whole still fails, because its
    shots no longer tile the shifted clock.
    """
    for field in ("start_frame", "transition_start", "transition_end", "end_frame"):
        plan["timeline"][field] += 1000
    with pytest.raises(ValueError):
        validate_shot_direction_plan(plan)


def test_an_implausible_fps_is_refused(plan: dict[str, Any]) -> None:
    """999 fps is outside Phase 17's own bound."""
    plan["timeline"]["fps"] = 999
    with pytest.raises(ValueError, match="fps"):
        validate_shot_direction_plan(plan)


def test_a_zero_hold_is_refused(plan: dict[str, Any]) -> None:
    """Both holds are at least one frame long, as Phase 17 requires."""
    plan["timeline"]["start_hold_frames"] = 0
    with pytest.raises(ValueError, match="start_hold_frames"):
        validate_shot_direction_plan(plan)


# ----------------------------------------------------------------------- shots


def test_an_empty_shot_list_is_refused(plan: dict[str, Any]) -> None:
    """Every episode is directed, even a neutral one."""
    plan["shots"] = []
    with pytest.raises(ValueError, match="carries no shots"):
        validate_shot_direction_plan(plan)


def test_a_shot_id_that_is_not_positional_is_refused(plan: dict[str, Any]) -> None:
    """A shot id that is not positional is refused."""
    plan["shots"][0]["shot_id"] = "banana"
    with pytest.raises(ValueError, match="a shot id is positional"):
        validate_shot_direction_plan(plan)


def test_an_unknown_camera_anchor_is_refused(plan: dict[str, Any]) -> None:
    """The catalogue is closed; an invented viewpoint cannot enter a plan."""
    plan["shots"][1]["camera_anchor_id"] = "CAM_INVENTED"
    with pytest.raises(ValueError, match="expected one of"):
        validate_shot_direction_plan(plan)


def test_a_proof_only_camera_is_refused(plan: dict[str, Any]) -> None:
    """P18 and P19 cameras are not in the built scene this layer directs."""
    plan["shots"][1]["camera_anchor_id"] = "CAM_P18_PLAZA"
    with pytest.raises(ValueError, match="expected one of"):
        validate_shot_direction_plan(plan)


def test_an_unknown_shot_kind_is_refused(plan: dict[str, Any]) -> None:
    """An unknown shot kind is refused."""
    plan["shots"][0]["kind"] = "MONTAGE"
    with pytest.raises(ValueError, match="expected one of"):
        validate_shot_direction_plan(plan)


def test_an_unknown_reason_code_is_refused(plan: dict[str, Any]) -> None:
    """An unknown reason code is refused."""
    plan["shots"][1]["reason_code"] = "FELT_RIGHT"
    with pytest.raises(ValueError, match="expected one of"):
        validate_shot_direction_plan(plan)


def test_an_invented_emphasis_is_refused(plan: dict[str, Any]) -> None:
    """Emphasis comes from Phase 21's closed vocabulary, or not at all.

    The independent review demonstrated that V1 accepted ``BANANA`` here; the
    vocabulary is now closed at the schema, so the mutation dies before any
    cross-validation is even asked for.
    """
    beat_shot = next(s for s in plan["shots"] if s["kind"] == "BEAT")
    beat_shot["emphasis"] = "BANANA"
    with pytest.raises(ValueError, match="expected one of"):
        validate_shot_direction_plan(plan)


def test_a_frame_before_the_timeline_is_refused(plan: dict[str, Any]) -> None:
    """Phase 22 invents no frames."""
    plan["shots"][0]["start_frame"] = 0
    with pytest.raises(ValueError, match="outside the locked timeline"):
        validate_shot_direction_plan(plan)


def test_a_frame_after_the_timeline_is_refused(plan: dict[str, Any]) -> None:
    """A frame after the timeline is refused."""
    plan["shots"][-1]["end_frame"] = 194
    with pytest.raises(ValueError, match="outside the locked timeline"):
        validate_shot_direction_plan(plan)


def test_a_reversed_shot_is_refused(plan: dict[str, Any]) -> None:
    """A reversed shot is refused."""
    plan["shots"][0]["end_frame"] = 0
    with pytest.raises(ValueError, match="before it starts"):
        validate_shot_direction_plan(plan)


def test_a_gap_between_shots_is_refused(plan: dict[str, Any]) -> None:
    """Every frame is directed."""
    plan["shots"][1]["start_frame"] += 2
    with pytest.raises(ValueError, match="no gap and no overlap"):
        validate_shot_direction_plan(plan)


def test_an_overlap_between_shots_is_refused(plan: dict[str, Any]) -> None:
    """An overlap between shots is refused."""
    plan["shots"][0]["end_frame"] += 3
    with pytest.raises(ValueError, match="no gap and no overlap"):
        validate_shot_direction_plan(plan)


def test_an_uncovered_tail_is_refused(plan: dict[str, Any]) -> None:
    """An uncovered tail is refused."""
    plan["shots"][-1]["end_frame"] -= 4
    with pytest.raises(ValueError, match="every frame is directed"):
        validate_shot_direction_plan(plan)


def test_two_adjacent_shots_on_one_anchor_are_refused(plan: dict[str, Any]) -> None:
    """A cut to the camera you are already on is not a cut."""
    plan["shots"][2]["camera_anchor_id"] = plan["shots"][1]["camera_anchor_id"]
    with pytest.raises(ValueError, match="never share an anchor"):
        validate_shot_direction_plan(plan)


def test_adjacent_shots_sharing_a_non_drone_anchor_are_still_refused(
    plan: dict[str, Any],
) -> None:
    """The V2 repeat exception is closed: any non-drone shared anchor is refused.

    The static-drone lane may repeat its one locked pose across shots (it never
    cuts); every OTHER anchor shared by adjacent shots is still a cut to the
    camera you are already on. Real camera_movement blocks put the plan on the
    V2 code path, where the exception lives; V1 has no exception at all.
    """
    v2 = plan_camera_movements(plan)
    v2["shots"][2]["camera_anchor_id"] = v2["shots"][1]["camera_anchor_id"]
    with pytest.raises(ValueError, match="never share an anchor"):
        validate_shot_direction_plan_v2(v2)


def test_a_broken_loop_is_refused(plan: dict[str, Any]) -> None:
    """The Phase 17 loop is frame-equivalent, so the camera must match at both ends.

    The closing shot is turned into a legal beat shot on a different anchor, so
    the only rule left to catch it is loop closure itself.
    """
    closing = plan["shots"][-1]
    closing["camera_anchor_id"] = "CAM_P16_ROADS"
    closing["kind"] = "BEAT"
    closing["reason_code"] = "BEAT_KIND_RULE"
    closing["emphasis"] = "SECONDARY"
    closing["source_beat_ids"] = ["beat_0099"]
    with pytest.raises(ValueError, match="the loop jumps"):
        validate_shot_direction_plan(plan)


def test_a_duplicate_shot_id_is_refused(plan: dict[str, Any]) -> None:
    """A duplicate shot id is refused."""
    plan["shots"][1]["shot_id"] = plan["shots"][0]["shot_id"]
    with pytest.raises(ValueError, match="a shot id is positional"):
        validate_shot_direction_plan(plan)


def test_one_beat_shown_by_two_shots_is_refused(plan: dict[str, Any]) -> None:
    """A beat is shown once."""
    plan["shots"][2]["source_beat_ids"] = [plan["shots"][1]["source_beat_ids"][0]]
    with pytest.raises(ValueError, match="a beat is shown once"):
        validate_shot_direction_plan(plan)


def test_unsorted_beat_ids_are_refused(story_adjacent: dict[str, Any], motion_time: bytes) -> None:
    """Unsorted beat ids are refused (proven on the synthetic merged shot)."""
    merged = build_shot_direction_plan_document(story_adjacent, motion_time)
    shot = next(s for s in merged["shots"] if len(s["source_beat_ids"]) > 1)
    shot["source_beat_ids"].reverse()
    with pytest.raises(ValueError, match="must be sorted"):
        validate_shot_direction_plan(merged)


def test_a_repeated_beat_id_inside_one_shot_is_refused(plan: dict[str, Any]) -> None:
    """A repeated beat id inside one shot is refused."""
    shot = next(s for s in plan["shots"] if s["source_beat_ids"])
    shot["source_beat_ids"] = shot["source_beat_ids"] * 2
    with pytest.raises(ValueError, match="repeats a source beat id"):
        validate_shot_direction_plan(plan)


# ------------------------------------------------- establishing vs beat shots


def test_an_establishing_shot_citing_beats_is_refused(plan: dict[str, Any]) -> None:
    """It is neutral by definition and claims no emphasis."""
    plan["shots"][0]["source_beat_ids"] = ["beat_0001"]
    with pytest.raises(ValueError, match="neutral by definition"):
        validate_shot_direction_plan(plan)


def test_an_establishing_shot_on_another_anchor_is_refused(
    plan: dict[str, Any],
) -> None:
    """An establishing shot on another anchor is refused."""
    plan["shots"][0]["camera_anchor_id"] = "CAM_P16_ROADS"
    with pytest.raises(ValueError, match="the neutral anchor is"):
        validate_shot_direction_plan(plan)


def test_a_third_establishing_anchor_is_still_refused(plan: dict[str, Any]) -> None:
    """The establishing-anchor law is a closed set of two, never a shape test.

    Real camera_movement blocks put the plan on the V2 code path -- without one
    the V2 validator delegates to V1, whose single-anchor message cannot prove
    the two-member set. A THIRD anchor, neither CAM_HERO_WORLD nor the
    static-drone anchor, is still refused.
    """
    v2 = plan_camera_movements(plan)
    v2["shots"][0]["camera_anchor_id"] = "CAM_P16_URBAN"
    with pytest.raises(ValueError, match="permitted neutral anchors are"):
        validate_shot_direction_plan_v2(v2)


def test_an_establishing_shot_with_emphasis_is_refused(plan: dict[str, Any]) -> None:
    """An establishing shot with emphasis is refused."""
    plan["shots"][0]["emphasis"] = "PRIMARY"
    with pytest.raises(ValueError, match="it carries none"):
        validate_shot_direction_plan(plan)


def test_an_establishing_shot_with_a_beat_reason_is_refused(
    plan: dict[str, Any],
) -> None:
    """An establishing shot carries the neutral reason and no other."""
    plan["shots"][0]["reason_code"] = "BEAT_KIND_RULE"
    with pytest.raises(ValueError, match="expected one of"):
        validate_shot_direction_plan(plan)


def test_a_beat_shot_citing_no_beat_is_refused(plan: dict[str, Any]) -> None:
    """Every non-neutral shot is caused by a Phase 21 beat."""
    plan["shots"][1]["source_beat_ids"] = []
    with pytest.raises(ValueError, match="cites no beat"):
        validate_shot_direction_plan(plan)


def test_a_beat_shot_with_the_neutral_reason_is_refused(plan: dict[str, Any]) -> None:
    """A beat shot with the neutral reason is refused."""
    plan["shots"][1]["reason_code"] = "NEUTRAL_ESTABLISHING"
    with pytest.raises(ValueError, match="expected one of"):
        validate_shot_direction_plan(plan)


def test_a_beat_shot_with_an_unshown_reason_is_refused(plan: dict[str, Any]) -> None:
    """The reason vocabularies partition by shape; an unshown code on a shot lies."""
    plan["shots"][1]["reason_code"] = "TRANSITION_BUDGET_EXHAUSTED"
    with pytest.raises(ValueError, match="expected one of"):
        validate_shot_direction_plan(plan)


def test_a_multi_beat_shot_that_is_not_a_merge_is_refused(
    story_adjacent: dict[str, Any], motion_time: bytes
) -> None:
    """Several beats share a shot only through an adjacent-anchor merge."""
    merged = build_shot_direction_plan_document(story_adjacent, motion_time)
    shot = next(s for s in merged["shots"] if len(s["source_beat_ids"]) > 1)
    shot["reason_code"] = "BEAT_KIND_RULE"
    with pytest.raises(ValueError, match="adjacent-anchor merge"):
        validate_shot_direction_plan(merged)


def test_an_unknown_kind_shot_off_the_neutral_anchor_is_refused(
    plan: dict[str, Any],
) -> None:
    """An unknown beat kind is never given a guessed viewpoint."""
    single = next(s for s in plan["shots"] if len(s["source_beat_ids"]) == 1)
    single["reason_code"] = "UNKNOWN_BEAT_KIND"
    with pytest.raises(ValueError, match="never given a guessed viewpoint"):
        validate_shot_direction_plan(plan)


# -------------------------------------------------------------------- unshown


def test_an_unshown_beat_that_a_shot_cites_is_refused(plan: dict[str, Any]) -> None:
    """A beat cannot be both shown and unshown."""
    beat_id = plan["shots"][1]["source_beat_ids"][0]
    plan["unshown"].append({"beat_id": beat_id, "reason_code": "TRANSITION_BUDGET_EXHAUSTED"})
    with pytest.raises(ValueError, match="but a shot cites it"):
        validate_shot_direction_plan(plan)


def test_an_unshown_entry_with_an_unknown_reason_is_refused(
    plan: dict[str, Any],
) -> None:
    """An unshown entry with an unknown reason is refused."""
    plan["unshown"].append({"beat_id": "beat_0099", "reason_code": "SEEMED_DULL"})
    with pytest.raises(ValueError, match="expected one of"):
        validate_shot_direction_plan(plan)


def test_an_unshown_entry_with_a_shot_reason_is_refused(plan: dict[str, Any]) -> None:
    """A beat-shot code on an unshown entry claims a cause this layer cannot produce."""
    plan["unshown"].append({"beat_id": "beat_0099", "reason_code": "BEAT_KIND_RULE"})
    with pytest.raises(ValueError, match="expected one of"):
        validate_shot_direction_plan(plan)


def test_an_unshown_entry_with_an_extra_key_is_refused(plan: dict[str, Any]) -> None:
    """An unshown entry with an extra key is refused."""
    plan["unshown"].append(
        {"beat_id": "beat_0099", "reason_code": "TRANSITION_BUDGET_EXHAUSTED", "why": "x"}
    )
    with pytest.raises(ValueError, match="unexpected keys"):
        validate_shot_direction_plan(plan)


# ------------------------------------------------------------ import boundary


def test_importing_the_cinematic_package_pulls_in_no_blender() -> None:
    """The pure layer must be testable with Python and JSON alone."""
    import importlib
    import sys

    for module in list(sys.modules):
        if module.startswith("living_diorama.cinematic"):
            del sys.modules[module]
    importlib.import_module("living_diorama.cinematic")
    assert "bpy" not in sys.modules


def test_the_package_exports_exactly_what_it_declares() -> None:
    """The package exports exactly what it declares."""
    import living_diorama.cinematic as cinematic

    for name in cinematic.__all__:
        assert hasattr(cinematic, name), name
    assert cinematic.__all__ == sorted(cinematic.__all__)
