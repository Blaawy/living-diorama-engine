"""The V4 elevated drone-camera lane (``camera_grammar="v4"``), additive.

The Director's standing law for EP1: every major event view must BEGIN already
elevated (roughly 20-40 world units), wide and city-readable; street-level event
framing is forbidden, and PUSH_IN / PULL_OUT / PAN / zoom / oscillation / any
move that is visually undone may never be emitted. V4 is an edit layer over the
same locked V1 document the other lanes consume:

* it re-binds the street-level event anchors to elevated catalogue members via
  the additive :data:`BEAT_ANCHORS_V4` table (the frozen V1 ``BEAT_ANCHORS`` is
  never touched), applied AFTER the V1 plan is built so the V1 planner, its
  merging and its reason codes stay byte-identical;
* it then assigns movement through the existing ``camera_grammar="v2"`` lane
  (which is already zero-push-in and clearance-proven) and rewrites EVERY
  non-closing movement -- whatever the lane produced (``REVEAL``, ``PAN``,
  ``PULL_OUT`` or ``STATIC``) -- into an in-place reveal that starts offset
  from the shot's own anchor look_at by ``V4_WALL_REVEAL_YAW_RADIANS`` (0.20
  rad) and ends EXACTLY on the anchor's composed framing: the camera rotates
  toward the event it covers and never turns away from it (the native REVEAL
  and the PAN rewrite swung the other way and drifted the wall off frame);
* the closing shot alone keeps its deliberate ``STATIC`` hold (the world still
  advances around a fixed, elevated camera, and a static camera has no swept
  path, which removes the building-clipping problem entirely).

The result never emits ``PUSH_IN``, ``PULL_OUT`` or ``PAN``, and the real EP1
plan ends with every anchor at z >= 20. Everything is derived from the shot's
own locked fields and the closed tables -- no randomness, no wall clock -- so
the same plan always yields the same V4 assignment, and the cross-check can
re-derive it byte for byte.
"""

import copy
import math
from typing import Final, cast

from living_diorama.cinematic.camera_movement_planner import (
    plan_camera_movements,
)
from living_diorama.cinematic.cinematic_schema_v1 import JsonValue
from living_diorama.cinematic.cinematic_spec import BEAT_ANCHORS, BEAT_ANCHORS_V4

V4_REBIND_BY_V1_ANCHOR: Final = {
    BEAT_ANCHORS[kind]: anchor for kind, anchor in BEAT_ANCHORS_V4.items() if kind in BEAT_ANCHORS
}
"""The V4 elevated-anchor rebinding, keyed by the V1 anchor it replaces.

Derived from the two closed tables rather than restated, so they cannot drift:
every beat kind the V4 lane re-anchors was framed by ``BEAT_ANCHORS`` in the V1
plan, and the V4 lane moves exactly those shots onto the elevated catalogue
member the V4 table names. In today's catalogue this is
``CAM_SEAL_DETAIL -> CAM_P16_CORE_CONTEXT`` and
``CAM_SCAR_DETAIL -> CAM_P16_SCAR_CONTEXT``.
"""

V4_WALL_REVEAL_YAW_RADIANS: Final = 0.20
"""The wall shot's in-place reveal, in radians (about 11.5 degrees).

Derived, not guessed. Sweeping the real frustum against the real wall segment
shows the wall leaves full frame beyond +0.23 rad, so 0.20 keeps it wholly
framed with margin at every point of the rotation. Spread over the wall shot's
112 frames that is 0.00179 rad/frame -- not the seal shot's rate: its real
spans give 0.00122 rad/frame (164 frames on the V4 clock) or 0.00282 (71 on
the canonical clock), so the earlier 0.00183 figure matched neither real span.
"""

V4_PERMITTED_MOVEMENTS: Final = frozenset({"STATIC", "REVEAL", "TRACK"})
"""The movement vocabulary the drone law permits: nothing radial, no pan.

``STATIC`` is a deliberate hold on the fixed elevated anchor (a static CAMERA is
allowed -- the world still moves because pedestrians and vehicles keep
advancing; a static IMAGE is not). ``REVEAL`` opens the composition in place;
``TRACK`` follows the population flow. ``PUSH_IN``, ``PULL_OUT`` and ``PAN``
must never be emitted.

This constant is documentation of the permitted vocabulary, not a gate: it has
no consumer anywhere in the codebase and enforces nothing. The vocabulary is
enforced by tests (``tests/cinematic/test_camera_direction_v4.py``) rather than
by code, so the next reader must not read it as a runtime constraint.
"""


def _rewrite_closing_to_static(movement: dict[str, JsonValue], shot: dict[str, JsonValue]) -> None:
    """Rewrite the closing shot's movement into a deliberate STATIC hold.

    The render pipeline's closure proof compares the final playback frame with
    an independent witness frame, and both must observe the camera fully at
    rest. The shared lane normally guarantees that with a ``settle_frame`` set
    ``SETTLE_MARGIN_FRAMES`` before the shot's end -- but that margin only fits
    when the closing shot is longer than the margin, and the V4 clock's tight
    end hold deliberately makes it shorter (a longer tail would breach the
    Director's dead-air law). A real render measured the consequence: a closing
    REVEAL still turning into the witness frame produced a boundary difference
    of 7.44 against a 1.0 tolerance.

    A static closing camera removes the conflict rather than trading one law
    for the other: the drone law explicitly permits static elevated
    observation, the world underneath keeps moving (pedestrians and vehicles
    advance, so the IMAGE is never frozen), and the closure proof sees a
    camera genuinely at rest.
    """
    movement["movement_type"] = "STATIC"
    movement["end_transform"] = copy.deepcopy(movement["start_transform"])
    # A STATIC block never travels, so it carries no settle frame -- exactly as
    # the shared planner derives one.
    movement.pop("settle_frame", None)
    # The reason must cite the shot's own reason code; an unmotivated move is refused.
    movement["reason_for_move"] = f"{shot['reason_code']} deliberate static hold on the wider city"


def _rewrite_to_in_place_reveal(movement: dict[str, JsonValue], shot: dict[str, JsonValue]) -> None:
    """Rewrite any v2 movement block into an in-place REVEAL that ends on the anchor.

    The Director's standing law for the wall build: a camera must never turn
    away from the event it is covering. The v2 lane can hand this layer
    REVEAL, PAN, PULL_OUT or STATIC -- and the native REVEAL/PAN forms sweep
    AWAY from the anchor (a +0.30 rad yaw swings the wall out of frame on the
    widest shot). Every non-closing shot's movement is therefore rewritten to
    the toward-the-anchor form: the rotation runs from an offset start (the
    anchor's own look_at direction rotated by ``V4_WALL_REVEAL_YAW_RADIANS``)
    TO the anchor's own look_at, so each shot ENDS on its composed anchor
    framing and the wall arrives centred rather than drifting toward the frame
    edge.

    The rewrite is an IN-PLACE yaw: it keeps the camera's location fixed, so
    the shot has no swept path and therefore cannot clip a building -- the
    property that made STATIC attractive in the first place -- while adding
    continuous visible change (a deliberate STATIC hold at this framing was
    measured to leave the picture near-static for seconds, which the dead-air
    law forbids).
    """
    start = cast(dict[str, JsonValue], movement["start_transform"])
    location = cast(list[object], start["location"])
    look_at = cast(list[object], start["look_at"])
    direction = [
        float(cast("int | float", look_at[axis])) - float(cast("int | float", location[axis]))
        for axis in range(3)
    ]
    cosine, sine = math.cos(V4_WALL_REVEAL_YAW_RADIANS), math.sin(V4_WALL_REVEAL_YAW_RADIANS)
    offset = (
        direction[0] * cosine - direction[1] * sine,
        direction[0] * sine + direction[1] * cosine,
        direction[2],
    )
    movement["movement_type"] = "REVEAL"
    movement["end_transform"] = copy.deepcopy(start)
    movement["start_transform"] = {
        "location": [float(cast("int | float", v)) for v in location],
        "look_at": [float(cast("int | float", location[axis])) + offset[axis] for axis in range(3)],
        "lens_mm": start["lens_mm"],
    }
    # The reason must cite the shot's own reason code; an unmotivated move is refused.
    movement["reason_for_move"] = f"{shot['reason_code']} reveal the wider world"


def plan_camera_movements_v4(plan: object) -> dict[str, JsonValue]:
    """Return a deep copy of a validated V1 shot plan under the V4 drone lane.

    The V4 assignment is a pure function of the shot's own locked fields:

    1. the elevated-anchor rebinding is applied to the deep copy (any shot
       whose V1 anchor is ``CAM_SEAL_DETAIL`` or ``CAM_SCAR_DETAIL`` moves to
       the elevated context member the V4 table names -- the only V1 anchors
       the drone law rejects);
    2. movement is assigned through the shared ``camera_grammar="v2"`` lane,
       which is already zero-push-in, clearance-proven and deterministic;
    3. every non-closing movement is rewritten to the toward-the-anchor
       in-place reveal (``_rewrite_to_in_place_reveal``) so each shot ends on
       its composed anchor framing instead of drifting off it, and the closing
       shot is rewritten to a deliberate ``STATIC`` hold
       (``_rewrite_closing_to_static``) -- the returned plan never carries a
       forbidden movement and never turns away from the event it covers.

    The input document is never mutated. The returned plan is a V2-format
    document (it carries ``camera_movement`` blocks), valid under the V2
    validator exactly like the other movement lanes.

    Raises:
        TypeError: If the plan is not a document carrying a shots list.
        ValueError: If any underlying movement derivation or clearance check
            fails (the v2 lane's own refusals).
    """
    if type(plan) is not dict or type(plan.get("shots")) is not list:
        raise TypeError("V4 camera planning requires a shot direction plan document")
    result = copy.deepcopy(plan)
    shots = cast(list[dict[str, JsonValue]], result["shots"])
    for shot in shots:
        elevated = V4_REBIND_BY_V1_ANCHOR.get(cast(str, shot.get("camera_anchor_id")))
        if elevated is not None:
            shot["camera_anchor_id"] = elevated
    moved = plan_camera_movements(result, camera_grammar="v2")
    moved_shots = cast(list[dict[str, JsonValue]], moved["shots"])
    closing_shot_id = moved_shots[-1]["shot_id"] if moved_shots else None
    for shot in moved_shots:
        movement = shot.get("camera_movement")
        if not isinstance(movement, dict):
            continue
        # The closing shot must end fully at rest for the render pipeline's
        # closure proof; see _rewrite_closing_to_static for the measurement
        # that forced this.
        if shot["shot_id"] == closing_shot_id:
            _rewrite_closing_to_static(movement, shot)
            continue
        # Every non-closing shot, whatever the v2 lane produced (REVEAL, PAN,
        # PULL_OUT or STATIC), ends on its composed anchor framing: an in-place
        # reveal that starts offset from the anchor's own look_at and rotates
        # TOWARD it, so the camera never turns away from the event it covers.
        _rewrite_to_in_place_reveal(movement, shot)
    return moved
