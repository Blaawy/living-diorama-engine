"""The V5 absolutely-static drone-camera lane (``camera_grammar="v5"``), additive.

The Director's standing law for EP1: the camera MUST NOT MOVE. One fixed,
elevated, zoomed-out drone view holds for the whole episode while people move,
cars move and the world changes; camera motion is never again used to satisfy
pixel-difference metrics. For every playback frame the location, rotation and
lens are those of the single locked pose ``CAM_P16_SCAR_CONTEXT``. V5 is an
edit layer over the same locked V1 document the other lanes consume:

* it deep-copies the input plan (never mutates the caller's document) and
  re-binds EVERY shot's ``camera_anchor_id`` to ``CAM_P16_SCAR_CONTEXT`` -- the
  frozen ``BEAT_ANCHORS``, ``BEAT_ANCHORS_V4`` and ``CAMERA_ANCHORS`` tables are
  never touched, so the anchor catalogue digest is unchanged;
* it then assigns movement through the shared ``camera_grammar="v2"`` lane,
  exactly as the V4 lane does -- this supplies the movement blocks, their
  endpoint shapes and their reason bindings from the shot's own locked fields;
* finally it rewrites EVERY shot's movement -- whatever the v2 lane produced --
  into a deliberate ``STATIC`` hold on the locked pose, so
  ``start_transform == end_transform`` on every shot and the whole episode is
  one pose.

The STATIC rewrite is the shared closing-agnostic helper
``camera_direction_v4._rewrite_closing_to_static``, IMPORTED rather than lifted:
the helper is already closing-agnostic (it forces ``STATIC``, sets
``end_transform = start_transform``, pops ``settle_frame`` and binds
``reason_for_move`` to the shot's own ``reason_code``), and lifting it into a
third shared module would mean editing ``camera_direction_v4.py``, which must
stay byte-identical under the V4 lane's own tests. Importing it reuses the one
implementation without touching the V4 file.

The result never emits ``PUSH_IN``, ``PULL_OUT``, ``PAN``, ``REVEAL`` or
``TRACK``, carries no ``settle_frame``, and every shot resolves to the same
anchor id. Everything is derived from the shot's own locked fields and the
closed tables -- no randomness, no wall clock -- so the same plan always yields
the same V5 assignment, and the cross-check can re-derive it byte for byte.
"""

import copy
from typing import Final, cast

from living_diorama.cinematic.camera_direction_v4 import _rewrite_closing_to_static
from living_diorama.cinematic.camera_movement_planner import (
    plan_camera_movements,
)
from living_diorama.cinematic.cinematic_schema_v1 import JsonValue
from living_diorama.cinematic.cinematic_spec import CAMERA_ANCHORS

V5_ANCHOR_ID: Final = "CAM_P16_SCAR_CONTEXT"
"""The single anchor every V5 shot resolves to.

The Director's locked pose: location ``(70.0, -36.0, 24.0)``, look_at
``(14.0, 0.0, 7.0)``, lens ``38.0``, depth of field on, focus
``(17.0, -1.0, 8.0)`` -- read at use time from :data:`CAMERA_ANCHORS`, never
restated as numbers here. A prior analysis confirmed the wall is fully
contained in this frustum with margin, so no framing correction is needed.
"""


def _static_movement_from_anchor(shot: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Build a STATIC movement block from the shot's (locked) anchor pose.

    The shared v2 lane gives every role-bearing shot a movement block; this is
    the defensive fallback for a shot that somehow arrived without one. It
    mirrors exactly the shape ``camera_movement_planner`` derives for STATIC:
    ``start_transform`` is the anchor's locked pose, ``end_transform`` is a deep
    copy of it, and the reason cites the shot's own ``reason_code`` so the
    mechanical binding in the V2 validator accepts it.
    """
    anchor_id = cast(str, shot["camera_anchor_id"])
    pose = CAMERA_ANCHORS[anchor_id]
    location = [float(cast("int | float", v)) for v in cast(list[object], pose["location"])]
    look_at = [float(cast("int | float", v)) for v in cast(list[object], pose["look_at"])]
    lens_mm = float(cast("int | float", pose["lens_mm"]))
    start: dict[str, JsonValue] = {
        "location": cast(JsonValue, location),
        "look_at": cast(JsonValue, look_at),
        "lens_mm": lens_mm,
    }
    return {
        "movement_type": "STATIC",
        "start_transform": start,
        "end_transform": copy.deepcopy(start),
        "easing": "EASE_IN_OUT",
        "reason_for_move": (
            f"{cast(str, shot['reason_code'])} deliberate static hold on the wider city"
        ),
    }


def plan_camera_movements_v5(plan: object) -> dict[str, JsonValue]:
    """Return a deep copy of a validated V1 shot plan under the V5 static lane.

    The V5 assignment is a pure function of the shot's own locked fields:

    1. every shot's ``camera_anchor_id`` is re-bound to
       ``CAM_P16_SCAR_CONTEXT`` on the deep copy (the frozen anchor tables are
       never touched);
    2. movement is assigned through the shared ``camera_grammar="v2"`` lane,
       which is deterministic and clearance-proven;
    3. every shot's movement -- whatever the v2 lane produced -- is rewritten
       to a deliberate ``STATIC`` hold on the locked pose via the shared
       closing-agnostic helper ``_rewrite_closing_to_static``; a shot that
       carries no movement block is given a STATIC block built from its anchor
       pose first. The returned plan never carries a forbidden movement, never
       carries a ``settle_frame``, and every shot ends exactly where it began.

    The input document is never mutated. The returned plan is a V2-format
    document (it carries ``camera_movement`` blocks), valid under the V2
    validator exactly like the other movement lanes.

    Raises:
        TypeError: If the plan is not a document carrying a shots list.
        ValueError: If any underlying movement derivation or clearance check
            fails (the v2 lane's own refusals).
    """
    if type(plan) is not dict or type(plan.get("shots")) is not list:
        raise TypeError("V5 camera planning requires a shot direction plan document")
    result = copy.deepcopy(plan)
    shots = cast(list[dict[str, JsonValue]], result["shots"])
    for shot in shots:
        shot["camera_anchor_id"] = V5_ANCHOR_ID
    moved = plan_camera_movements(result, camera_grammar="v2")
    moved_shots = cast(list[dict[str, JsonValue]], moved["shots"])
    for shot in moved_shots:
        movement = shot.get("camera_movement")
        if not isinstance(movement, dict):
            movement = _static_movement_from_anchor(shot)
            shot["camera_movement"] = movement
        # The helper is closing-agnostic: it forces STATIC, sets
        # end_transform = start_transform, pops settle_frame and binds the
        # reason to the shot's own reason code -- exactly the rewrite every
        # V5 shot needs, closing or not.
        _rewrite_closing_to_static(movement, shot)
    return moved
