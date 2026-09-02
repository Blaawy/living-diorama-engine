"""Apply V2 camera movement to the built scene as NEW camera identities.

V2 direction is an EDIT layer over V1. For every shot that carries a
``camera_movement`` block (with a movement type other than ``STATIC``), this
applier creates ONE NEW camera object -- named from the shot id, never colliding
with the fourteen approved fixed anchors -- keyframes it smoothly
(ease-in/ease-out, no jitter) between the block's ``start_transform`` and
``end_transform`` across the shot's frame window, and binds it active for that
window with a timeline marker, exactly as Phase 22's applier binds its fixed
anchors with markers.

What this applier never does is the point of the phase boundary: it never
touches, animates, re-poses or re-lenses any existing fixed anchor camera
object, and it never modifies ``apply_cinematic_direction.py`` or its markers.
A movement camera is a separate object ``apply_cinematic_direction.py`` never
inspects -- its anchor checks run only over the plan's own camera anchors.

RENDER PATH -- INTEGRATED. This applier's output renders: the executor and the
engine's render-plan validator both admit the derived ``CAM_MOVEMENT_`` identity
for a non-STATIC movement shot's frames, under ``camera_profile="v2"`` only, by
re-deriving the identity from the frame's own shot id:

* ``render_episode.py``: the ``APPROVED_CAMERA_ANCHORS`` membership check is
  supplemented -- a V2 frame of a movement shot may carry
  ``_movement_camera_name(entry["shot_id"])`` instead of a fixed anchor.
* ``render_execution_schema_v1.py``: the engine validator supplements
  ``cinematic_spec.ANCHOR_NAMES`` the same way under V2.
* ``apply_cinematic_direction.py`` ``_require_no_foreign_camera_markers``:
  accepts a ``movement_marker_prefix`` carve-out for this applier's
  ``P22_MOVE_`` markers, and ``episode_scene.py`` runs this applier FIRST under
  ``camera_profile="v2"``, so every movement camera exists and is marker-bound
  before direction accepts the plan.

The pure math (easing, sampling) is restated below exactly as the engine's
``camera_movement_planner`` implements it, because this side imports nothing
from the engine -- the same borrowing rule every sibling applier follows. A
pure test asserts the two implementations agree.
"""

import hashlib
import json
import math
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:  # pragma: no cover - import-path bootstrap
    sys.path.insert(0, str(SCRIPTS_DIR))

MARKER_PREFIX = "P22_MOVE_"
"""Every timeline marker this applier owns starts here, and nothing else does."""

CAMERA_PREFIX = "CAM_MOVEMENT_"
"""Every camera object this applier creates starts here.

Deliberately disjoint from the ``CAM_*`` names of the fourteen fixed anchors,
so a movement camera can never be mistaken for an anchor the world built.
"""

CANONICAL_MOTION_TIME_SHA256 = "bfcbfcfd8d2b33f0ca8a0bc51655a1028babc601a73cdd42ca3c8caf3f9da673"
"""The one canonical Phase 17 Motion & Time Spec this build directs, restated."""

APPROVED_CATALOGUE_SHA256 = "d9110cfcbb51aeec40ae55e461298ecf7668a81e31945ed7d41fd843a9c0f82d"
"""The canonical digest of the approved fourteen-anchor catalogue, restated."""

CANONICAL_TIMELINE = {
    "end_frame": 193,
    "end_hold_frames": 48,
    "fps": 24,
    "start_frame": 1,
    "start_hold_frames": 24,
    "transition_end": 145,
    "transition_frames": 120,
    "transition_start": 25,
}
"""The canonical resolved clock, restated as data beside its source digest."""

DIRECTOR_V4_MOTION_TIME_SHA256 = "a821049b648c0d37a9bc5c6cbc74142cffb0c21a817ad3e2b10764dfeaa4079c"
"""The reviewed Director V4 Motion & Time Spec digest, restated beside the canonical one."""

DIRECTOR_V4_TIMELINE = {
    "end_frame": 319,
    "end_hold_frames": 18,
    "fps": 24,
    "start_frame": 1,
    "start_hold_frames": 24,
    "transition_end": 301,
    "transition_frames": 276,
    "transition_start": 25,
}
"""The resolved Director V4 clock, restated as data beside its source digest."""

REVIEWED_CLOCKS = {
    CANONICAL_MOTION_TIME_SHA256: CANONICAL_TIMELINE,
    DIRECTOR_V4_MOTION_TIME_SHA256: DIRECTOR_V4_TIMELINE,
}
"""The closed set of reviewed clocks this build directs: digest -> resolved clock.

A plan is admitted only when its bound digest is one of these AND the clock it
restates is exactly what that digest resolves to -- a document cannot claim one
clock while binding another, and any digest outside this closed set is refused
outright, however internally consistent.
"""

APPROVED_ANCHOR_NAMES = frozenset(
    {
        "CAM_HERO_SCAR",
        "CAM_HERO_WORLD",
        "CAM_P16_COMPOSITION",
        "CAM_P16_CORE_CONTEXT",
        "CAM_P16_DENSITY",
        "CAM_P16_ROADS",
        "CAM_P16_SCAR_CONTEXT",
        "CAM_P16_SYSTEM",
        "CAM_P16_URBAN",
        "CAM_P16_VALIDITY",
        "CAM_P16_WORLD_HERO",
        "CAM_SCAR_DETAIL",
        "CAM_SEAL_DETAIL",
        "CAM_VERIFY_TOPOLOGY",
    }
)
"""The fixed anchor names this applier must never create or touch, restated."""


class CameraMovementApplyError(RuntimeError):
    """Raised when the scene cannot honour the movement plan exactly."""


def _catalogue_digest(catalogue) -> str:
    """Return the SHA-256 of the supplied catalogue's canonical serialization."""
    text = json.dumps(
        catalogue,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(text.encode("utf-8") + b"\n").hexdigest()


# --------------------------------------------------------------------------
# Pure motion math, restated (pinned equal to the engine by a pure test)
# --------------------------------------------------------------------------


def eased(t: float, easing: str) -> float:
    """Map a linear parameter in [0, 1] through an easing curve."""
    if easing == "LINEAR":
        return t
    if easing == "EASE_IN_OUT":
        return t * t * (3.0 - 2.0 * t)
    raise CameraMovementApplyError(f"unknown easing {easing!r}; expected LINEAR or EASE_IN_OUT")


def sample_transform(start: dict, end: dict, easing: str, t: float) -> dict:
    """Interpolate location and look_at between two movement endpoints."""
    if not 0.0 <= t <= 1.0:
        raise CameraMovementApplyError(f"sample parameter t must be within [0, 1], got {t}")
    factor = eased(t, easing)
    return {
        "location": [
            float(a) + (float(b) - float(a)) * factor
            for a, b in zip(start["location"], end["location"], strict=True)
        ],
        "look_at": [
            float(a) + (float(b) - float(a)) * factor
            for a, b in zip(start["look_at"], end["look_at"], strict=True)
        ],
        "lens_mm": start["lens_mm"],
    }


def movement_camera_name(shot_id: str) -> str:
    """Return the single new camera identity a movement shot earns."""
    return f"{CAMERA_PREFIX}{shot_id}"


def keyframe_spec(shot: dict) -> list[dict]:
    """Return the (frame, pose) keyframes for one shot's movement.

    Two keyframes: ``start_transform`` at the shot's start frame and
    ``end_transform`` at the block's ``settle_frame`` when the movement carries
    one (else at the shot's end frame), under the block's easing. The poses are
    the block's own endpoints -- this function only places them on the timeline.
    Landing the second keyframe on ``settle_frame`` (when present) makes the
    F-curve's constant extrapolation hold the settled ``end_transform`` flat
    through the closure witness frame, exactly as the planner's sampling does.
    """
    movement = shot.get("camera_movement")
    if movement is None or movement["movement_type"] == "STATIC":
        return []
    settle_frame = movement.get("settle_frame", shot["end_frame"])
    return [
        {
            "frame": int(shot["start_frame"]),
            "pose": sample_transform(
                movement["start_transform"], movement["end_transform"], movement["easing"], 0.0
            ),
        },
        {
            "frame": int(settle_frame),
            "pose": sample_transform(
                movement["start_transform"], movement["end_transform"], movement["easing"], 1.0
            ),
        },
    ]


def _rotation_euler_from_view(location, look_at) -> tuple:
    """Return the XYZ euler a camera stores when aimed along ``look_at - location``.

    Builds the rotation matrix column by column -- camera ``-Z`` along the view
    direction, camera ``+Y`` rolled toward world ``+Z`` -- and extracts the XYZ
    euler, the builders' own look-at derivation. Proven against the engine's
    anchor poses by a pure test.
    """
    direction = tuple(float(a) - float(b) for a, b in zip(look_at, location, strict=True))
    length = math.sqrt(sum(component * component for component in direction))
    if length == 0.0:
        raise CameraMovementApplyError("camera look_at coincides with its location")
    forward = tuple(component / length for component in direction)
    projected = (
        -forward[2] * forward[0],
        -forward[2] * forward[1],
        1.0 - forward[2] * forward[2],
    )
    magnitude = math.sqrt(sum(component * component for component in projected))
    up = (0.0, 1.0, 0.0) if magnitude < 1e-6 else tuple(c / magnitude for c in projected)
    z_axis = tuple(-component for component in forward)
    x_axis = (
        up[1] * z_axis[2] - up[2] * z_axis[1],
        up[2] * z_axis[0] - up[0] * z_axis[2],
        up[0] * z_axis[1] - up[1] * z_axis[0],
    )
    rotation = (
        (x_axis[0], up[0], z_axis[0]),
        (x_axis[1], up[1], z_axis[1]),
        (x_axis[2], up[2], z_axis[2]),
    )
    ey = math.asin(max(-1.0, min(1.0, -rotation[2][0])))
    ex = math.atan2(rotation[2][1], rotation[2][2])
    ez = math.atan2(rotation[1][0], rotation[0][0])
    return (ex, ey, ez)


# --------------------------------------------------------------------------
# The apply entry point
# --------------------------------------------------------------------------


def apply_camera_movements(bpy, plan: dict, catalogue: dict) -> dict:
    """Create one new camera per movement-bearing shot and keyframe it.

    Refuses (never repairs): a plan not cut on a reviewed clock or the
    approved catalogue; a scene on a different frame range; a movement camera
    name that collides with an approved fixed anchor or an object already in
    the scene; a STATIC block (it needs no new camera -- the fixed anchor
    already holds); or a shot whose movement endpoints fail the same checks
    the V2 validator applies.

    Args:
        bpy: The Blender Python module.
        plan: A Shot Direction Plan V2 document (V1 shape plus optional
            ``camera_movement`` blocks).
        catalogue: The Phase 22 camera anchor catalogue, passed as data.

    Returns:
        A report of the cameras created, keyframes placed and markers bound.

    Raises:
        CameraMovementApplyError: On any refusal above.
    """
    bound_clock = plan["source"]["motion_time_sha256"]
    if bound_clock not in REVIEWED_CLOCKS:
        raise CameraMovementApplyError(
            f"plan binds motion time spec {bound_clock}, which is not the canonical "
            f"Phase 17 source this build directs (admissible reviewed clocks: "
            f"{', '.join(sorted(REVIEWED_CLOCKS))})"
        )
    if dict(plan["timeline"]) != dict(REVIEWED_CLOCKS[bound_clock]):
        raise CameraMovementApplyError(
            f"plan restates timeline {dict(plan['timeline'])!r}, which is not what the "
            f"reviewed Phase 17 source {bound_clock} resolves to"
        )
    bound_catalogue = plan["source"]["catalogue_sha256"]
    if bound_catalogue != APPROVED_CATALOGUE_SHA256:
        raise CameraMovementApplyError(
            f"plan binds camera catalogue {bound_catalogue}, which is not the approved "
            f"canonical catalogue ({APPROVED_CATALOGUE_SHA256})"
        )
    if _catalogue_digest(catalogue) != bound_catalogue:
        raise CameraMovementApplyError(
            f"the supplied camera catalogue hashes to {_catalogue_digest(catalogue)}, but "
            f"the plan was cut for catalogue {bound_catalogue}"
        )

    scene = bpy.context.scene
    timeline_start = plan["timeline"]["start_frame"]
    timeline_end = plan["timeline"]["end_frame"]
    if scene.frame_start != timeline_start or scene.frame_end != timeline_end:
        raise CameraMovementApplyError(
            f"scene frame range {scene.frame_start}..{scene.frame_end} disagrees with "
            f"the plan's locked timeline {timeline_start}..{timeline_end}"
        )

    existing = {obj.name for obj in bpy.data.objects}
    created = []
    for shot in plan["shots"]:
        movement = shot.get("camera_movement")
        if movement is None or movement["movement_type"] == "STATIC":
            continue  # no new camera: the fixed anchor already holds this shot
        shot_id = shot["shot_id"]
        name = movement_camera_name(shot_id)
        if name in APPROVED_ANCHOR_NAMES:
            raise CameraMovementApplyError(
                f"movement camera name {name!r} collides with an approved fixed anchor"
            )
        if name in existing:
            raise CameraMovementApplyError(
                f"movement camera name {name!r} already exists in the scene; a movement "
                "shot gets exactly one new camera, never a reuse"
            )
        frames = keyframe_spec(shot)
        if not frames:
            raise CameraMovementApplyError(
                f"{shot_id} carries a non-static movement but yields no keyframes"
            )
        camera_data = bpy.data.cameras.new(name)
        camera = bpy.data.objects.new(name, camera_data)
        bpy.context.collection.objects.link(camera)
        existing.add(name)
        for entry in frames:
            frame = entry["frame"]
            pose = entry["pose"]
            camera.location = tuple(float(value) for value in pose["location"])
            camera.rotation_euler = _rotation_euler_from_view(pose["location"], pose["look_at"])
            camera.keyframe_insert("location", frame=frame)
            camera.keyframe_insert("rotation_euler", frame=frame)
        # Hold flat past the last keyframe: if the F-curves extrapolated LINEAR,
        # the still-moving ease-out tail would extend past the second keyframe
        # and re-introduce exactly the closure gap ``settle_frame`` removes.
        # Set the mode explicitly so the guarantee never depends on Blender's
        # per-version default.
        for curve in camera.animation_data.action.fcurves:
            curve.extrapolation = "CONSTANT"
        marker = scene.timeline_markers.new(f"{MARKER_PREFIX}{shot_id}", frame=shot["start_frame"])
        marker.camera = camera
        created.append(
            {
                "shot_id": shot_id,
                "camera": name,
                "marker": marker.name,
                "start_frame": shot["start_frame"],
                "end_frame": shot["end_frame"],
                "keyframes": [entry["frame"] for entry in frames],
            }
        )

    bpy.context.view_layer.update()
    return {"cameras_created": created, "count": len(created)}
