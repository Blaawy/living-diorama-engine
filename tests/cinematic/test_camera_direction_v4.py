r"""Tests for the V4 elevated drone-camera lane (``plan_camera_movements_v4``).

Until now no test exercised this module. These tests pin the NARROW Director
revision on the real four-shot EP1 plan (``plan_ep1``): the wall build spans
shot_0002 and shot_0003, and the camera must never turn away from it.

Pinned behaviour:

* every non-closing shot ends on its composed anchor framing -- ``end_transform``
  is exactly the anchor's locked pose, and ``start_transform.look_at`` is offset
  from the anchor's own look_at by exactly ``V4_WALL_REVEAL_YAW_RADIANS`` (0.20
  rad), the toward-the-anchor form;
* the wall (midpoint (17.0, -1.0, 8.0), derived from the real
  ``camera_clearance`` constants, never hand-copied) is strictly CLOSER to
  frame centre at the end of every non-closing shot than at its start;
* the wall's four real corners -- both ``wall_segment_2d()`` endpoints at z=0
  and at ``WALL_HEIGHT`` (16.0) -- are inside the frustum at both endpoints of
  every shot, with exactly one documented exception: ``end_B_top`` (the far
  endpoint's top corner) is OUTSIDE at shot_0001's ``start_transform``, which
  is harmless because shot_0001 is the pre-transition start hold during which
  the wall has not yet risen (proved against the real clock by
  ``test_the_one_out_of_frame_corner_predates_the_wall_rise``); the off-axis
  fractions are computed with the real ``camera_clearance`` frustum helpers
  (``camera_half_fov_tangents``, ``point_in_camera_frustum``), never a
  hand-copied constant;
* the closing shot is still a STATIC hold with no settle frame;
* no shot emits PUSH_IN, PULL_OUT or PAN; ``no_push_pull_oscillation`` reports
  0 and ``no_animated_lens_zoom`` passes;
* camera ``location`` is identical at both endpoints of every shot (in-place
  rotation only -- this preserves the accepted height and guarantees no swept
  path).

The absolute fractions are pinned at the values this code really produces in
frustum space (shot_0001 0.7237 -> 0.2532, shot_0002 0.6437 -> 0.2577,
shot_0003 0.4406 -> 0.0252, to abs=0.001). The independently measured table
from rendered frames (0.77 -> 0.28, 0.73 -> 0.30, 0.48 -> 0.03) is the same
quantity by a different method and differs by up to ~0.09 on the widest shot,
so it is kept as context rather than pinned. The exact relationships (end ==
anchor pose, start == anchor pose rotated by exactly 0.20 rad) are pinned to
machine precision separately.
"""

import json
import math
from pathlib import Path
from typing import Any

import pytest

from living_diorama.cinematic.camera_clearance import (
    WALL_CENTER,
    WALL_HEIGHT,
    camera_half_fov_tangents,
    point_in_camera_frustum,
    wall_segment_2d,
)
from living_diorama.cinematic.camera_direction_v4 import (
    V4_WALL_REVEAL_YAW_RADIANS,
    plan_camera_movements_v4,
)
from living_diorama.cinematic.camera_movement_planner import movement_metrics
from living_diorama.cinematic.camera_qa_metrics import (
    no_animated_lens_zoom,
    no_push_pull_oscillation,
)
from living_diorama.cinematic.cinematic_schema_v2 import validate_shot_direction_plan_v2
from living_diorama.cinematic.cinematic_spec import CAMERA_ANCHORS

# The real wall midpoint, derived from the locked geometry constants -- never
# a hand-copied literal: WALL_CENTER (17.0, -1.0) at half the real wall height
# (16.0 / 2).
WALL_MIDPOINT: tuple[float, float, float] = (WALL_CENTER[0], WALL_CENTER[1], WALL_HEIGHT / 2.0)

# The real V4 clock document, read at test time -- never a hand-copied
# timeline -- for the harmless-exception proof.
DIRECTOR_V4_CLOCK = (
    Path(__file__).resolve().parents[2]
    / "visual"
    / "blender"
    / "config"
    / "motion_time_director_v4.json"
)


def _wall_corners() -> dict[str, tuple[float, float, float]]:
    """The real wall segment's four corners, from the locked geometry helpers.

    ``wall_segment_2d()`` yields the two ground-plane endpoints (A, then B);
    each has a bottom corner at z=0 and a top corner at ``WALL_HEIGHT`` (16.0).
    ``end_B_top`` (B's top corner) is the corner the widest framing misses --
    named after the segment's own order, never hand-copied coordinates.
    """
    (ax, ay), (bx, by) = wall_segment_2d()
    return {
        "A_bottom": (ax, ay, 0.0),
        "A_top": (ax, ay, WALL_HEIGHT),
        "B_bottom": (bx, by, 0.0),
        "B_top": (bx, by, WALL_HEIGHT),
    }


def _movement_by_id(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {shot["shot_id"]: shot for shot in plan["shots"]}


def _off_axis_fraction(transform: dict[str, Any]) -> float:
    """The wall's signed horizontal offset, as a fraction of the frame half-width.

    Builds the same view basis ``camera_clearance.point_in_camera_frustum``
    derives (forward along ``look_at - location``, up as world +Z projected
    perpendicular, right as ``forward x up``) and normalises the wall's
    horizontal offset by ``depth * h_tan`` with the shared
    ``camera_half_fov_tangents`` helper -- the same projection model the
    clearance and QA modules use, never a local restatement.
    """
    location = [float(v) for v in transform["location"]]
    look_at = [float(v) for v in transform["look_at"]]
    lens = float(transform["lens_mm"])
    fx, fy, fz = (look_at[i] - location[i] for i in range(3))
    length = math.sqrt(fx * fx + fy * fy + fz * fz)
    fx, fy, fz = fx / length, fy / length, fz / length
    up_x, up_y, up_z = -fz * fx, -fz * fy, 1.0 - fz * fz
    up_len = math.sqrt(up_x * up_x + up_y * up_y + up_z * up_z)
    up_x, up_y, up_z = up_x / up_len, up_y / up_len, up_z / up_len
    rx, ry, rz = (fy * up_z - fz * up_y, fz * up_x - fx * up_z, fx * up_y - fy * up_x)
    dx, dy, dz = (WALL_MIDPOINT[i] - location[i] for i in range(3))
    depth = fx * dx + fy * dy + fz * dz
    right = rx * dx + ry * dy + rz * dz
    h_tan, _v_tan = camera_half_fov_tangents(lens)
    return right / (depth * h_tan)


def _anchor_rotated_transform(anchor_id: str) -> dict[str, Any]:
    """The anchor pose whose look_at direction is rotated by the V4 yaw.

    Mirrors exactly what ``_rewrite_to_in_place_reveal`` computes as the new
    ``start_transform``: the anchor's locked location and lens, with look_at
    derived from the anchor's own look_at direction rotated in the ground plane
    by ``V4_WALL_REVEAL_YAW_RADIANS``.
    """
    pose = CAMERA_ANCHORS[anchor_id]
    location = [float(v) for v in pose["location"]]
    look_at = [float(v) for v in pose["look_at"]]
    direction = [look_at[i] - location[i] for i in range(3)]
    cosine, sine = math.cos(V4_WALL_REVEAL_YAW_RADIANS), math.sin(V4_WALL_REVEAL_YAW_RADIANS)
    rotated = (
        direction[0] * cosine - direction[1] * sine,
        direction[0] * sine + direction[1] * cosine,
        direction[2],
    )
    return {
        "location": location,
        "look_at": [location[i] + rotated[i] for i in range(3)],
        "lens_mm": float(pose["lens_mm"]),
    }


def test_v4_lane_emits_only_reveal_and_static_on_the_real_ep1_plan(
    plan_ep1: dict[str, Any],
) -> None:
    """The real EP1 plan: three in-place reveals, one closing static, nothing else."""
    planned = plan_camera_movements_v4(plan_ep1)
    assert validate_shot_direction_plan_v2(planned) is planned
    assert movement_metrics(planned)["movement_type_histogram"] == {"REVEAL": 3, "STATIC": 1}
    by_id = _movement_by_id(planned)
    assert by_id["shot_0001"]["camera_movement"]["movement_type"] == "REVEAL"
    assert by_id["shot_0002"]["camera_movement"]["movement_type"] == "REVEAL"
    assert by_id["shot_0003"]["camera_movement"]["movement_type"] == "REVEAL"
    assert by_id["shot_0004"]["camera_movement"]["movement_type"] == "STATIC"
    for shot in planned["shots"]:
        movement = shot.get("camera_movement")
        if movement is not None:
            assert movement["movement_type"] not in ("PUSH_IN", "PULL_OUT", "PAN")
    assert no_push_pull_oscillation(planned)["oscillation_count"] == 0
    assert no_animated_lens_zoom(planned)["passes"] is True


def test_closing_shot_is_static_hold_with_no_settle_frame(plan_ep1: dict[str, Any]) -> None:
    """The closing shot keeps the deliberate STATIC hold, with no settle frame."""
    planned = plan_camera_movements_v4(plan_ep1)
    closing = planned["shots"][-1]
    assert closing["shot_id"] == "shot_0004"
    movement = closing["camera_movement"]
    assert movement["movement_type"] == "STATIC"
    assert "settle_frame" not in movement
    assert movement["start_transform"] == movement["end_transform"]


def test_every_non_closing_shot_ends_on_its_anchor_framing(plan_ep1: dict[str, Any]) -> None:
    """Every non-closing shot's end_transform is exactly its anchor's locked pose."""
    planned = plan_camera_movements_v4(plan_ep1)
    for shot in planned["shots"][:-1]:
        movement = shot["camera_movement"]
        anchor = CAMERA_ANCHORS[shot["camera_anchor_id"]]
        end = movement["end_transform"]
        assert end["location"] == list(anchor["location"])
        assert end["look_at"] == list(anchor["look_at"])
        assert end["lens_mm"] == anchor["lens_mm"]
        # The start is offset from the anchor's own look_at -- never equal to it.
        assert movement["start_transform"]["look_at"] != list(anchor["look_at"])


def test_every_start_is_the_anchor_pose_rotated_by_exactly_the_v4_yaw(
    plan_ep1: dict[str, Any],
) -> None:
    """The start offset is exactly V4_WALL_REVEAL_YAW_RADIANS, toward the anchor.

    Re-derives the expected start_transform from the locked anchor catalogue and
    the single V4 constant, so a change of direction, magnitude, or a second
    constant anywhere in the rewrite fails here to machine precision.
    """
    planned = plan_camera_movements_v4(plan_ep1)
    for shot in planned["shots"][:-1]:
        movement = shot["camera_movement"]
        expected = _anchor_rotated_transform(shot["camera_anchor_id"])
        assert movement["start_transform"]["look_at"] == pytest.approx(
            expected["look_at"], abs=1e-9
        )
        assert movement["start_transform"]["location"] == expected["location"]
        assert movement["start_transform"]["lens_mm"] == expected["lens_mm"]


def test_location_is_identical_at_both_endpoints_of_every_shot(plan_ep1: dict[str, Any]) -> None:
    """In-place rotation only: location never moves, so no swept path exists.

    This is what preserves the accepted camera height and positions exactly.
    """
    planned = plan_camera_movements_v4(plan_ep1)
    for shot in planned["shots"]:
        movement = shot.get("camera_movement")
        if movement is None:
            continue
        assert movement["start_transform"]["location"] == movement["end_transform"]["location"]


def test_wall_moves_toward_frame_centre_and_stays_fully_in_frame(
    plan_ep1: dict[str, Any],
) -> None:
    """The wall is strictly closer to centre at the end; all four corners in frame.

    The toward-centre assertions use the real wall MIDPOINT (as before). The
    containment check runs all four corners of the real segment -- both
    ``wall_segment_2d()`` endpoints at z=0 and at ``WALL_HEIGHT`` (16.0) --
    through the real ``point_in_camera_frustum`` at both endpoints of every
    shot, and pins the single measured exception: ``end_B_top`` is OUTSIDE at
    shot_0001's ``start_transform``. That corner belongs to the pre-transition
    start hold, in which the wall has not yet risen -- proven against the real
    clock by ``test_the_one_out_of_frame_corner_predates_the_wall_rise``.
    Pinning it outside means any change of framing that brings it inside FAILS
    here and forces a re-review instead of silently drifting.
    """
    planned = plan_camera_movements_v4(plan_ep1)
    corners = _wall_corners()
    for shot in planned["shots"][:-1]:
        movement = shot["camera_movement"]
        start_fraction = _off_axis_fraction(movement["start_transform"])
        end_fraction = _off_axis_fraction(movement["end_transform"])
        # Strictly closer to frame centre at the end of the shot.
        assert abs(end_fraction) < abs(start_fraction)
        # The correction is substantial: at least a fifth of a half-width.
        assert abs(start_fraction) - abs(end_fraction) >= 0.20
    for shot in planned["shots"]:
        movement = shot["camera_movement"]
        for label in ("start_transform", "end_transform"):
            transform = movement[label]
            for name, corner in corners.items():
                inside = point_in_camera_frustum(
                    transform["location"],
                    transform["look_at"],
                    transform["lens_mm"],
                    list(corner),
                )
                # The single measured exception, pinned as OUTSIDE: end_B_top at
                # shot_0001's start_transform. If it ever reads inside, the
                # framing has changed -- fail and force re-review.
                is_pinned_exception = (
                    shot["shot_id"] == "shot_0001"
                    and label == "start_transform"
                    and name == "B_top"
                )
                if is_pinned_exception:
                    assert not inside, (
                        "end_B_top moved INSIDE at shot_0001's start_transform -- "
                        "framing changed; re-review before relaxing this pin"
                    )
                else:
                    assert inside, f"{shot['shot_id']} {label} : {name} OUTSIDE the frustum"


def test_the_one_out_of_frame_corner_predates_the_wall_rise(plan_ep1: dict[str, Any]) -> None:
    """The pinned out-of-frame corner belongs to frames in which the wall has not risen.

    ``end_B_top`` is outside the frustum only at shot_0001's ``start_transform``.
    shot_0001 is the pre-transition start hold -- frames 1..24 on the real V4
    clock (``start_hold_frames == 24``) -- and the ``wall_presence`` channel's
    window starts at 0.05 of the transition, i.e. after the hold, so the wall
    has not been built during shot_0001's frames and a corner outside the frame
    then clips nothing. Driven by the real clock document
    (``motion_time_director_v4.json``), never by a comment.
    """
    clock = json.loads(DIRECTOR_V4_CLOCK.read_text(encoding="utf-8"))
    timeline = clock["timeline"]
    assert timeline["start_hold_frames"] == 24
    start_hold_end = timeline["start_frame"] + timeline["start_hold_frames"] - 1
    wall_presence_start = next(
        channel["window"][0]
        for channel in clock["channels"]
        if channel["channel"] == "wall_presence"
    )
    assert wall_presence_start > 0.0, "wall_presence must begin only after the start hold"
    shot_0001 = _movement_by_id(plan_ep1)["shot_0001"]
    assert shot_0001["start_frame"] >= timeline["start_frame"]
    assert shot_0001["end_frame"] <= start_hold_end


def test_wall_off_axis_fractions_match_the_measured_table(plan_ep1: dict[str, Any]) -> None:
    """The real frustum-space fractions, recomputed with the shared helpers.

    Context -- the table measured independently against RENDERED frames:
        shot_0001  0.77 -> 0.28
        shot_0002  0.73 -> 0.30
        shot_0003  0.48 -> 0.03
    The two measurements are of the same quantity by different methods --
    rendered-frame pixels there vs. the pure frustum-space projection below --
    and differ by up to ~0.09 on the widest shot, which is why the
    frustum-space numbers are the ones pinned here (abs=0.001): they are
    exact, deterministic outputs of this code, while the rendered table
    carries measurement noise.
    """
    planned = plan_camera_movements_v4(plan_ep1)
    by_id = _movement_by_id(planned)
    expected = {
        "shot_0001": (0.7237, 0.2532),
        "shot_0002": (0.6437, 0.2577),
        "shot_0003": (0.4406, 0.0252),
    }
    for shot_id, (expected_start, expected_end) in expected.items():
        movement = by_id[shot_id]["camera_movement"]
        start_fraction = _off_axis_fraction(movement["start_transform"])
        end_fraction = _off_axis_fraction(movement["end_transform"])
        assert start_fraction == pytest.approx(expected_start, abs=0.001)
        assert end_fraction == pytest.approx(expected_end, abs=0.001)
        # Every value stays far below the old, rejected away-rotation figures
        # (1.02 / 0.95), so a reversion is caught by meaning, not magnitude.
        assert max(abs(start_fraction), abs(end_fraction)) < 0.95, (
            f"{shot_id} drifted toward the old away-rotation figures (1.02 / 0.95)"
        )
