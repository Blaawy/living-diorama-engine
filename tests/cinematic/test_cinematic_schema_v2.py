"""Shot Direction Plan V2: V1 identity plus optional camera movement.

Every test here takes a genuine, valid V1 plan and proves either that V2 treats
it exactly as V1 does (the identity guarantee), or that a camera_movement block
is governed by the mechanical rules this layer exists to enforce.
"""

import copy
from typing import Any

import pytest

from living_diorama.cinematic import (
    build_shot_direction_plan_document,
    validate_shot_direction_plan,
)
from living_diorama.cinematic.camera_movement_planner import plan_camera_movements
from living_diorama.cinematic.cinematic_schema_v1 import SHOT_KEYS
from living_diorama.cinematic.cinematic_schema_v2 import (
    SHOT_KEYS_V2,
    reason_for_move_is_bound,
    validate_camera_movement,
    validate_shot_direction_plan_v2,
)


@pytest.fixture
def plan_ep1(story_ep0_to_ep1: dict[str, Any], motion_time: bytes) -> dict[str, Any]:
    """The genuine four-shot episode 0 -> 1 transition plan."""
    return build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)


@pytest.fixture
def plan_ep2(story_ep1_to_ep2: dict[str, Any], motion_time: bytes) -> dict[str, Any]:
    """The genuine episode 1 -> 2 transition plan."""
    return build_shot_direction_plan_document(story_ep1_to_ep2, motion_time)


@pytest.fixture
def baseline(story_ep0: dict[str, Any], motion_time: bytes) -> dict[str, Any]:
    """The genuine single-shot baseline plan."""
    return build_shot_direction_plan_document(story_ep0, motion_time)


@pytest.fixture
def wide(story_wide: dict[str, Any], motion_time: bytes) -> dict[str, Any]:
    """A genuine plan whose beats overflow the transition budget."""
    return build_shot_direction_plan_document(story_wide, motion_time)


@pytest.fixture
def adjacent(story_adjacent: dict[str, Any], motion_time: bytes) -> dict[str, Any]:
    """A genuine plan with an adjacent-anchor merged two-beat shot."""
    return build_shot_direction_plan_document(story_adjacent, motion_time)


# ----------------------------------------------------- V1 identity guarantee


def test_every_golden_v1_plan_validates_unchanged_under_v2(
    plan_ep1: dict[str, Any],
    plan_ep2: dict[str, Any],
    baseline: dict[str, Any],
    wide: dict[str, Any],
    adjacent: dict[str, Any],
) -> None:
    """Every genuine V1 golden plan is accepted unchanged by the V2 validator."""
    for label, plan in (
        ("ep0_to_ep1", plan_ep1),
        ("ep1_to_ep2", plan_ep2),
        ("baseline", baseline),
        ("wide", wide),
        ("adjacent", adjacent),
    ):
        assert validate_shot_direction_plan_v2(plan) is plan, label
        assert validate_shot_direction_plan(plan) is plan, label


def test_the_v2_shot_key_set_is_the_v1_set_plus_camera_movement() -> None:
    """V2 adds exactly one optional key and removes nothing."""
    assert SHOT_KEYS | frozenset({"camera_movement"}) == SHOT_KEYS_V2


def test_v1_and_v2_refuse_the_same_broken_plan(
    plan_ep1: dict[str, Any],
) -> None:
    """A battery of single breaks: V2 refuses wherever V1 refuses, identically.

    Every mutation keeps zero camera_movement blocks, so both validators run
    the V1 envelope; the delegation must not have loosened a single rule.
    """
    mutations: list[tuple[str, Any]] = [
        ("missing shots", lambda p: p.pop("shots")),
        ("unexpected top level key", lambda p: p.__setitem__("mood", "tense")),
        ("wrong format", lambda p: p.__setitem__("format", "other")),
        ("unsupported version", lambda p: p.__setitem__("schema_version", 2)),
        ("malformed story digest", lambda p: p["source"].__setitem__("story_plan_sha256", "x")),
        ("unapproved anchor", lambda p: p["shots"][1].__setitem__("camera_anchor_id", "BANANA")),
        ("bad shot id", lambda p: p["shots"][1].__setitem__("shot_id", "shot_0099")),
        ("unsorted beats", lambda p: p["shots"][1].__setitem__("source_beat_ids", ["b2", "b1"])),
        ("duplicate beats", lambda p: p["shots"][1].__setitem__("source_beat_ids", ["b1", "b1"])),
        ("gap in tiling", lambda p: p["shots"][1].__setitem__("start_frame", 30)),
        (
            "adjacent same anchor",
            lambda p: p["shots"][2].__setitem__("camera_anchor_id", "CAM_SEAL_DETAIL"),
        ),
        (
            "beat shown twice",
            lambda p: p["shots"][2].__setitem__(
                "source_beat_ids", list(p["shots"][1]["source_beat_ids"])
            ),
        ),
        ("shot without beats", lambda p: p["shots"][1].__setitem__("source_beat_ids", [])),
        (
            "unknown reason on a beat shot",
            lambda p: p["shots"][1].__setitem__("reason_code", "TRANSITION_BUDGET_EXHAUSTED"),
        ),
    ]
    for label, mutate in mutations:
        v1_broken = copy.deepcopy(plan_ep1)
        v2_broken = copy.deepcopy(plan_ep1)
        mutate(v1_broken)
        mutate(v2_broken)
        with pytest.raises((TypeError, ValueError)) as v1_error:
            validate_shot_direction_plan(v1_broken)
        with pytest.raises((TypeError, ValueError)) as v2_error:
            validate_shot_direction_plan_v2(v2_broken)
        assert type(v1_error.value) is type(v2_error.value), label
        assert str(v1_error.value) == str(v2_error.value), label


# ------------------------------------------------------- movement validation


def test_a_planner_produced_movement_block_validates(plan_ep1: dict[str, Any]) -> None:
    """A camera_movement block derived from the shot's own fields validates."""
    v2 = plan_camera_movements(plan_ep1)
    movement = v2["shots"][1]["camera_movement"]
    assert movement is not None
    assert validate_camera_movement(movement, v2["shots"][1], "camera_movement") is movement


def test_a_full_v2_plan_with_movement_validates(plan_ep1: dict[str, Any]) -> None:
    """The whole V2 document (V1 envelope plus movement) validates."""
    v2 = plan_camera_movements(plan_ep1)
    assert validate_shot_direction_plan_v2(v2) is v2
    for shot in v2["shots"]:
        if "camera_movement" not in shot:
            assert set(shot) == set(SHOT_KEYS), shot["shot_id"]


def test_a_movement_block_missing_a_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A movement block missing a key is refused, never repaired."""
    v2 = plan_camera_movements(plan_ep1)
    shot = v2["shots"][1]
    movement = copy.deepcopy(shot["camera_movement"])
    movement.pop("easing")
    with pytest.raises(ValueError, match="missing required keys"):
        validate_camera_movement(movement, shot, "camera_movement")


def test_a_movement_block_with_an_extra_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An extra key means something this contract does not describe wrote it."""
    v2 = plan_camera_movements(plan_ep1)
    shot = v2["shots"][1]
    movement = copy.deepcopy(shot["camera_movement"])
    movement["mood"] = "tense"
    with pytest.raises(ValueError, match="unexpected keys"):
        validate_camera_movement(movement, shot, "camera_movement")


def test_an_unknown_movement_type_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A movement type outside the closed vocabulary is refused."""
    v2 = plan_camera_movements(plan_ep1)
    shot = v2["shots"][1]
    movement = copy.deepcopy(shot["camera_movement"])
    movement["movement_type"] = "ZOOM"
    with pytest.raises(ValueError, match="expected one of"):
        validate_camera_movement(movement, shot, "camera_movement")


def test_a_transform_with_wrong_location_shape_is_refused(plan_ep1: dict[str, Any]) -> None:
    """The transform must use the anchor pose shape: three-number vectors."""
    v2 = plan_camera_movements(plan_ep1)
    shot = v2["shots"][1]
    movement = copy.deepcopy(shot["camera_movement"])
    movement["start_transform"]["location"] = [1.0, 2.0]
    with pytest.raises(ValueError, match="list of three numbers"):
        validate_camera_movement(movement, shot, "camera_movement")


def test_an_out_of_range_lens_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A lens outside the plausible range is refused."""
    v2 = plan_camera_movements(plan_ep1)
    shot = v2["shots"][1]
    movement = copy.deepcopy(shot["camera_movement"])
    movement["end_transform"]["lens_mm"] = 4000.0
    with pytest.raises(ValueError, match="outside"):
        validate_camera_movement(movement, shot, "camera_movement")


# --------------------------------------------------- reason_for_move binding


def test_a_bound_reason_is_accepted(plan_ep1: dict[str, Any]) -> None:
    """A reason that references the shot's own reason_code is accepted."""
    v2 = plan_camera_movements(plan_ep1)
    for shot in v2["shots"]:
        movement = shot.get("camera_movement")
        if movement is None:
            continue
        assert reason_for_move_is_bound(movement["reason_for_move"], shot)
        assert validate_camera_movement(movement, shot, "camera_movement") is movement


def test_a_reason_bound_to_a_real_beat_id_is_accepted(plan_ep1: dict[str, Any]) -> None:
    """A reason that names a real source beat id is a valid mechanical binding."""
    v2 = plan_camera_movements(plan_ep1)
    shot = v2["shots"][1]
    beat_id = shot["source_beat_ids"][0]
    movement = copy.deepcopy(shot["camera_movement"])
    movement["reason_for_move"] = f"camera tracks to keep {beat_id} framed"
    assert validate_camera_movement(movement, shot, "camera_movement") is movement


def test_a_generic_unmotivated_reason_is_rejected(plan_ep1: dict[str, Any]) -> None:
    """'make the scene more cinematic' references neither cause nor subject."""
    v2 = plan_camera_movements(plan_ep1)
    shot = v2["shots"][1]
    movement = copy.deepcopy(shot["camera_movement"])
    movement["reason_for_move"] = "make the scene more cinematic"
    with pytest.raises(ValueError, match="references neither"):
        validate_camera_movement(movement, shot, "camera_movement")
    assert not reason_for_move_is_bound(movement["reason_for_move"], shot)


def test_a_reason_for_a_different_shot_is_rejected(plan_ep1: dict[str, Any]) -> None:
    """A reason bound to another shot's cause is still unmotivated for this shot.

    The establishing shot's reason (NEUTRAL_ESTABLISHING) is not the beat shot's
    reason (BEAT_KIND_RULE), so borrowing it cannot bind here.
    """
    v2 = plan_camera_movements(plan_ep1)
    target = v2["shots"][1]
    establishing_reason = v2["shots"][0]["camera_movement"]["reason_for_move"]
    movement = copy.deepcopy(target["camera_movement"])
    movement["reason_for_move"] = establishing_reason
    with pytest.raises(ValueError, match="references neither"):
        validate_camera_movement(movement, target, "camera_movement")


def test_a_reason_for_the_wrong_beat_id_is_rejected(plan_ep1: dict[str, Any]) -> None:
    """A beat id the shot does not cite is not a binding, even if it is real elsewhere."""
    v2 = plan_camera_movements(plan_ep1)
    shot = v2["shots"][2]
    movement = copy.deepcopy(shot["camera_movement"])
    foreign_beat = v2["shots"][1]["source_beat_ids"][0]
    movement["reason_for_move"] = f"push in because of {foreign_beat}"
    with pytest.raises(ValueError, match="references neither"):
        validate_camera_movement(movement, shot, "camera_movement")


# --------------------------------------------------- movement-type agreement


def test_a_static_block_with_differing_endpoints_is_rejected(plan_ep1: dict[str, Any]) -> None:
    """STATIC with differing endpoints is not static."""
    v2 = plan_camera_movements(plan_ep1)
    shot = v2["shots"][1]
    movement = copy.deepcopy(shot["camera_movement"])
    movement["movement_type"] = "STATIC"
    with pytest.raises(ValueError, match="STATIC but its endpoints differ"):
        validate_camera_movement(movement, shot, "camera_movement")


def test_a_pan_that_moves_its_location_is_rejected(plan_ep1: dict[str, Any]) -> None:
    """A PAN must rotate in place."""
    v2 = plan_camera_movements(plan_ep1)
    shot = v2["shots"][1]
    movement = copy.deepcopy(shot["camera_movement"])
    movement["movement_type"] = "PAN"
    with pytest.raises(ValueError, match="PAN but moves its location"):
        validate_camera_movement(movement, shot, "camera_movement")


def test_a_push_in_that_moves_away_is_rejected(plan_ep1: dict[str, Any]) -> None:
    """A PUSH_IN must end closer to the look-at point."""
    v2 = plan_camera_movements(plan_ep1)
    shot = v2["shots"][1]
    movement = copy.deepcopy(shot["camera_movement"])
    movement["movement_type"] = "PUSH_IN"
    movement["start_transform"], movement["end_transform"] = (
        movement["end_transform"],
        movement["start_transform"],
    )
    with pytest.raises(ValueError, match="PUSH_IN but ends"):
        validate_camera_movement(movement, shot, "camera_movement")


def test_a_tilt_that_keeps_the_look_at_height_is_rejected(plan_ep1: dict[str, Any]) -> None:
    """A TILT must change the look_at height; a flat rotation is a PAN."""
    v2 = plan_camera_movements(plan_ep1)
    shot = v2["shots"][0]  # the establishing shot: location fixed, look_at rotated
    movement = copy.deepcopy(shot["camera_movement"])
    movement["movement_type"] = "TILT"
    with pytest.raises(ValueError, match="TILT but keeps the look_at height"):
        validate_camera_movement(movement, shot, "camera_movement")
