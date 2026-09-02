r"""Tests for the V5 absolutely-static drone-camera lane (``plan_camera_movements_v5``).

These tests drive the real four-shot EP1 plan (``plan_ep1``) through the V5
lane and pin what the Director locked: ONE pose holds for the whole episode.
Every assertion reads the pose from the reviewed anchor catalogue
(``CAMERA_ANCHORS``) or from the real ``camera_clearance`` geometry helpers --
never a hand-copied coordinate, lens or timeline.

Pinned behaviour:

* every shot's ``camera_movement`` is a ``STATIC`` hold whose
  ``start_transform == end_transform``, both exactly the ``CAM_P16_SCAR_CONTEXT``
  catalogue pose; the movement-type histogram is ``{"STATIC": 4}``;
* every shot resolves to the same single ``camera_anchor_id``, so the whole
  episode is one pose;
* no shot carries a ``settle_frame`` and no shot emits ``PUSH_IN``,
  ``PULL_OUT``, ``PAN``, ``REVEAL`` or ``TRACK``; ``no_push_pull_oscillation``
  reports 0 and ``no_animated_lens_zoom`` passes;
* the wall's four real corners (both ``wall_segment_2d()`` endpoints at z=0 and
  at ``WALL_HEIGHT``) all lie inside ``point_in_camera_frustum`` for the locked
  pose;
* the V5 output validates under ``validate_shot_direction_plan_v2`` (this is
  the establishing-anchor law admitting ``CAM_P16_SCAR_CONTEXT``);
* the V4 lane still produces its own three REVEALs on the same input -- the V5
  lane's deep copy never disturbs the V4 lane or the caller's document.
"""

from typing import Any

import pytest

from living_diorama.cinematic.camera_clearance import (
    WALL_HEIGHT,
    point_in_camera_frustum,
    wall_segment_2d,
)
from living_diorama.cinematic.camera_direction_v4 import plan_camera_movements_v4
from living_diorama.cinematic.camera_direction_v5 import (
    V5_ANCHOR_ID,
    plan_camera_movements_v5,
)
from living_diorama.cinematic.camera_movement_planner import movement_metrics
from living_diorama.cinematic.camera_qa_metrics import (
    no_animated_lens_zoom,
    no_push_pull_oscillation,
)
from living_diorama.cinematic.cinematic_schema_v2 import validate_shot_direction_plan_v2
from living_diorama.cinematic.cinematic_spec import CAMERA_ANCHORS

FORBIDDEN_MOVEMENT_TYPES: tuple[str, ...] = ("PUSH_IN", "PULL_OUT", "PAN", "REVEAL", "TRACK")


@pytest.fixture
def v5_planned(plan_ep1: dict[str, Any]) -> dict[str, Any]:
    """The real four-shot EP1 plan under the V5 absolutely-static lane."""
    return plan_camera_movements_v5(plan_ep1)


def _locked_pose() -> dict[str, Any]:
    """The single V5 pose, read from the reviewed catalogue -- never hand-copied."""
    pose = CAMERA_ANCHORS[V5_ANCHOR_ID]
    return {
        "location": list(pose["location"]),
        "look_at": list(pose["look_at"]),
        "lens_mm": pose["lens_mm"],
    }


def _wall_corners() -> list[tuple[float, float, float]]:
    """The wall's four real corners: both endpoints at z=0 and at WALL_HEIGHT."""
    (ax, ay), (bx, by) = wall_segment_2d()
    return [
        (ax, ay, 0.0),
        (ax, ay, WALL_HEIGHT),
        (bx, by, 0.0),
        (bx, by, WALL_HEIGHT),
    ]


def test_v5_lane_is_four_static_holds_and_validates(v5_planned: dict[str, Any]) -> None:
    """The real EP1 plan: four deliberate STATIC holds, accepted by the V2 validator."""
    assert validate_shot_direction_plan_v2(v5_planned) is v5_planned
    assert len(v5_planned["shots"]) == 4
    assert movement_metrics(v5_planned)["movement_type_histogram"] == {"STATIC": 4}


def test_every_shot_holds_the_locked_catalogue_pose(v5_planned: dict[str, Any]) -> None:
    """Both endpoints equal each other and the CAM_P16_SCAR_CONTEXT catalogue pose."""
    expected = _locked_pose()
    for shot in v5_planned["shots"]:
        movement = shot["camera_movement"]
        assert movement["start_transform"] == expected
        assert movement["end_transform"] == expected
        assert movement["start_transform"] == movement["end_transform"]


def test_the_whole_episode_is_one_anchor_id(v5_planned: dict[str, Any]) -> None:
    """Every shot names the same single anchor, so the episode is one pose."""
    ids = {shot["camera_anchor_id"] for shot in v5_planned["shots"]}
    assert ids == {V5_ANCHOR_ID}
    assert len(ids) == 1


def test_no_shot_carries_a_settle_frame(v5_planned: dict[str, Any]) -> None:
    """A STATIC hold never travels, so no shot declares a settle frame."""
    for shot in v5_planned["shots"]:
        assert "settle_frame" not in shot["camera_movement"]


def test_no_forbidden_movement_type_appears(v5_planned: dict[str, Any]) -> None:
    """PUSH_IN / PULL_OUT / PAN / REVEAL / TRACK are all absent."""
    for shot in v5_planned["shots"]:
        movement = shot["camera_movement"]
        assert movement["movement_type"] not in FORBIDDEN_MOVEMENT_TYPES


def test_qa_metrics_report_a_fully_static_plan(v5_planned: dict[str, Any]) -> None:
    """No radial push/pull oscillation and no animated lens anywhere."""
    assert no_push_pull_oscillation(v5_planned)["oscillation_count"] == 0
    assert no_animated_lens_zoom(v5_planned)["passes"] is True


def test_all_four_wall_corners_are_inside_the_locked_frustum() -> None:
    """The locked pose frames the whole wall: both endpoints, top and bottom."""
    pose = CAMERA_ANCHORS[V5_ANCHOR_ID]
    for corner in _wall_corners():
        assert point_in_camera_frustum(
            pose["location"], pose["look_at"], float(pose["lens_mm"]), corner
        ), corner


def test_v4_lane_still_emits_its_three_reveals(plan_ep1: dict[str, Any]) -> None:
    """The V4 lane is undisturbed: the same input still yields three REVEALs."""
    planned_v4 = plan_camera_movements_v4(plan_ep1)
    assert validate_shot_direction_plan_v2(planned_v4) is planned_v4
    assert movement_metrics(planned_v4)["movement_type_histogram"] == {"REVEAL": 3, "STATIC": 1}
