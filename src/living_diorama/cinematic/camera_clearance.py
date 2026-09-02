"""Camera-to-geometry clearance validation for the Director-revision grammar.

The Director's revision rule for EP1 is context-first movement: no camera may
move closer to the wall, and every movement pose must stand clear of the real
solid geometry of the scene. This module is the pure, Blender-free half of that
rule -- exactly the codebase's established "pure planning function + separate
Blender applier" pattern. It knows only the locked geometry restated below and
the shot's own movement endpoints; it imports no ``bpy``, reads no filesystem,
and is fully testable without Blender.

The geometry is RESTATED here, not read from the configs, for the same reason
``cinematic_spec.CAMERA_ANCHORS`` is restated: the planner is pure and touches
no filesystem. Every constant cites its locked source, and a test asserts the
restatement still agrees with ``master_scene_v1.json`` and the builders'
constants field for field, so the two cannot drift.

Wall geometry sources (all real, all cited):

* ``visual/blender/config/master_scene_v1.json`` lines 75-85 -- the EP1 wall
  is ``boundaries.boundary_ab.wall_station``: center ``(17.0, -1.0)``,
  direction ``(-0.22, 1.0)``, length ``44.0``. Episode 1's render export
  (``tests/cinematic/fixtures/render_export_ep1.json``) builds exactly one
  wall, ``wall_boundary_ab`` on ``boundary_ab``, so this is the one real solid
  wall of EP1.
* ``visual/blender/scripts/apply_render_export.py`` lines 50-51 -- the built
  wall is ``WALL_HEIGHT = 16.0`` tall and ``WALL_THICKNESS = 2.8`` thick.
* ``visual/blender/scripts/build_master_scene.py`` ``build_avenues`` -- the
  avenue that runs along the wall's boundary is a ``7.0``-unit-wide road
  ribbon centered on the boundary path, with sidewalks at ``4.7``.

District geometry (for the surrounding-context claim only):

* ``visual/blender/config/master_scene_v1.json`` lines 9-50 -- the four
  district discs (center + radius) the city is made of. EP1's camera poses
  are reported against them; the wall shot's poses lie outside every disc.
  (The fixed Seal anchor deliberately sits inside district_a's disc -- it
  frames the Golden Seal plaza -- so the district check is informational, not
  a refusal; the refusal threshold is the wall.)
"""

import math
from typing import Final, cast

from living_diorama.cinematic.cinematic_schema_v1 import JsonValue
from living_diorama.cinematic.cinematic_spec import (
    ANCHOR_SENSOR_HEIGHT,
    ANCHOR_SENSOR_WIDTH,
)

# --------------------------------------------------------------------------
# Locked geometry, restated from the sources cited in the module docstring
# --------------------------------------------------------------------------

WALL_CENTER: Final = (17.0, -1.0)
"""``master_scene_v1.json`` boundary_ab.wall_station.center."""

WALL_DIRECTION: Final = (-0.22, 1.0)
"""``master_scene_v1.json`` boundary_ab.wall_station.direction (un-normalised)."""

WALL_LENGTH: Final = 44.0
"""``master_scene_v1.json`` boundary_ab.wall_station.length (world units)."""

WALL_HEIGHT: Final = 16.0
"""``apply_render_export.py`` ``WALL_HEIGHT``: the built wall's full height."""

WALL_THICKNESS: Final = 2.8
"""``apply_render_export.py`` ``WALL_THICKNESS``: the built wall's full width."""

ROAD_WIDTH: Final = 7.0
"""``build_master_scene.build_avenues``: the avenue ribbon along the wall."""

#: A camera may come no closer to the wall's centerline than the far edge of
#: the avenue that runs beside it: wall half-thickness (1.4) plus road
#: half-width (3.5). Inside that corridor a camera would stand in traffic at
#: the wall's base -- never a legitimate EP1 viewpoint. 4.9 units, derived,
#: not a round number.
WALL_CENTERLINE_CLEARANCE: Final = WALL_THICKNESS / 2.0 + ROAD_WIDTH / 2.0

DISTRICT_RECORDS: Final = (
    ("district_a", (-16.0, 6.0), 26.0),
    ("district_b", (38.0, -6.0), 19.0),
    ("district_c", (-30.0, -34.0), 21.0),
    ("district_d", (-2.0, 42.0), 22.0),
)
"""``master_scene_v1.json`` districts: (name, center, radius)."""

#: The real render aspect the fixed anchors are proven against: 1280 x 720,
#: ``render_execution_spec._OWNED_OUTPUT`` (``resolution_x=1280``,
#: ``resolution_y=720``), i.e. 16:9.
RENDER_ASPECT: Final = 16.0 / 9.0

#: ``cinematic_spec.ANCHOR_SENSOR_WIDTH`` / ``ANCHOR_SENSOR_HEIGHT``: the
#: supported Blender's factory sensor, 36 x 24 mm (a 3:2 aspect). Imported
#: from the locked catalogue so the two cannot drift.
SENSOR_WIDTH_MM: Final = ANCHOR_SENSOR_WIDTH
SENSOR_HEIGHT_MM: Final = ANCHOR_SENSOR_HEIGHT
SENSOR_ASPECT: Final = SENSOR_WIDTH_MM / SENSOR_HEIGHT_MM


def wall_segment_2d() -> tuple[tuple[float, float], tuple[float, float]]:
    """Return the wall's two endpoints in the ground plane, from real data.

    The wall stands on the segment ``center +/- (length / 2) * direction_hat``,
    exactly as ``apply_render_export._wall_frame`` lays it out.
    """
    dx, dy = WALL_DIRECTION
    norm = math.hypot(dx, dy)
    half = WALL_LENGTH / 2.0
    cx, cy = WALL_CENTER
    ux, uy = dx / norm, dy / norm
    return ((cx - half * ux, cy - half * uy), (cx + half * ux, cy + half * uy))


def _distance_point_to_segment_2d(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    """Euclidean distance from a ground point to a 2-D segment."""
    abx, aby = bx - ax, by - ay
    length_sq = abx * abx + aby * aby
    if length_sq < 1e-12:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * abx + (py - ay) * aby) / length_sq
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * abx), py - (ay + t * aby))


def camera_min_distance_to_wall_centerline(location: object) -> float:
    """Return the camera's ground-plane distance to the wall's centerline.

    The wall is vertical, so the clearance is a pure ground-plane quantity:
    the distance from ``(x, y)`` to the wall segment. Negative never occurs --
    a distance is a distance.
    """
    x, y = (float(cast("int | float", v)) for v in cast(list[object], location)[:2])
    (ax, ay), (bx, by) = wall_segment_2d()
    return _distance_point_to_segment_2d(x, y, ax, ay, bx, by)


def camera_min_distance_to_wall_face(location: object) -> float:
    """Return the distance from the camera to the wall's nearest face."""
    return camera_min_distance_to_wall_centerline(location) - WALL_THICKNESS / 2.0


def camera_min_distance_to_district_edge(location: object) -> float:
    """Return the smallest signed distance to any district disc.

    Negative means the camera is inside that district's disc (true of the
    fixed Seal anchor, which frames the Golden Seal plaza inside district_a).
    Informational only -- the refusal threshold is the wall.
    """
    x, y = (float(cast("int | float", v)) for v in cast(list[object], location)[:2])
    return min(math.hypot(x - cx, y - cy) - radius for _name, (cx, cy), radius in DISTRICT_RECORDS)


# --------------------------------------------------------------------------
# Frustum math (for proving which real objects the wall shot actually frames)
# --------------------------------------------------------------------------


def camera_half_fov_tangents(
    lens_mm: float, *, render_aspect: float = RENDER_ASPECT
) -> tuple[float, float]:
    """Return (horizontal, vertical) half-FOV tangents for a locked lens.

    This is the single, shared projection model for every frustum computation
    in this revision (``camera_qa_metrics`` imports it). It implements
    Blender's ``sensor_fit = "AUTO"`` rule -- the fixed anchors inherit
    ``ANCHOR_SENSOR_FIT = "AUTO"`` and the applier refuses any re-fitted
    sensor -- which picks whichever sensor axis is the tighter constraint
    against the RENDER's aspect ratio:

    * the real render is 1280 x 720 (16:9), which is WIDER than the 3:2
      sensor (36.0 / 24.0 = 1.5), so the sensor WIDTH governs: the horizontal
      half-FOV comes from the full sensor width,
      ``tan(h/2) = (sensor_width / 2) / lens``, and the vertical half-FOV
      follows the RENDER's own aspect, not the sensor's height:
      ``tan(v/2) = tan(h/2) * resolution_y / resolution_x``;
    * the else branch (a render narrower than the sensor) is the mirror image,
      kept so this one function is the correct AUTO-fit model for any locked
      render, exactly as ``camera_qa_metrics`` derived it.

    A height-governed model would make the frame look wider than the real
    render -- backwards for a safety/clearance check -- so no module in this
    revision may restate the formula independently.

    Raises:
        ValueError: If ``lens_mm`` is not positive.
    """
    if lens_mm <= 0.0:
        raise ValueError(f"lens_mm must be positive, got {lens_mm}")
    half_x = math.atan(SENSOR_WIDTH_MM / (2.0 * lens_mm))
    if render_aspect >= SENSOR_ASPECT:
        half_y = math.atan(math.tan(half_x) / render_aspect)
    else:
        half_y = math.atan(SENSOR_HEIGHT_MM / (2.0 * lens_mm))
        half_x = math.atan(math.tan(half_y) * render_aspect)
    return math.tan(half_x), math.tan(half_y)


def point_in_camera_frustum(
    location: object, look_at: object, lens_mm: float, point: object
) -> bool:
    """Return whether a world point lies inside the camera's viewing frustum.

    Builds the same view basis the Blender applier derives
    (``apply_camera_movement._rotation_euler_from_view``): forward along
    ``look_at - location``, up as world +Z projected perpendicular, right as
    ``forward x up``. A point is in frame when it is in front of the lens and
    its horizontal and vertical offsets stay inside the half-FOV tangents.
    """
    lx, ly, lz = (float(cast("int | float", v)) for v in cast(list[object], location))
    ax, ay, az = (float(cast("int | float", v)) for v in cast(list[object], look_at))
    px, py, pz = (float(cast("int | float", v)) for v in cast(list[object], point))
    fx, fy, fz = ax - lx, ay - ly, az - lz
    length = math.sqrt(fx * fx + fy * fy + fz * fz)
    if length == 0.0:
        raise ValueError("camera look_at coincides with its location")
    fx, fy, fz = fx / length, fy / length, fz / length
    up_x, up_y, up_z = -fz * fx, -fz * fy, 1.0 - fz * fz
    up_len = math.sqrt(up_x * up_x + up_y * up_y + up_z * up_z)
    if up_len < 1e-9:
        up_x, up_y, up_z = 0.0, 1.0, 0.0
    else:
        up_x, up_y, up_z = up_x / up_len, up_y / up_len, up_z / up_len
    rx, ry, rz = (
        fy * up_z - fz * up_y,
        fz * up_x - fx * up_z,
        fx * up_y - fy * up_x,
    )
    dx, dy, dz = px - lx, py - ly, pz - lz
    forward = fx * dx + fy * dy + fz * dz
    if forward <= 0.0:
        return False
    right = rx * dx + ry * dy + rz * dz
    up = up_x * dx + up_y * dy + up_z * dz
    h_tan, v_tan = camera_half_fov_tangents(lens_mm)
    return abs(right) <= forward * h_tan and abs(up) <= forward * v_tan


# --------------------------------------------------------------------------
# The refusal gate
# --------------------------------------------------------------------------


def validate_movement_clearance(shot: object) -> dict[str, JsonValue]:
    """Verify one shot's movement endpoints against the real geometry.

    Refuses (raises ``ValueError``) when either the start or the end camera
    pose of a movement comes closer to the wall's centerline than
    ``WALL_CENTERLINE_CLEARANCE``. A PUSH_IN's end pose -- the one that moves
    toward the subject -- is therefore the pose this gate cares most about,
    and both are checked.

    Args:
        shot: A V2 shot carrying an optional ``camera_movement`` block.

    Returns:
        The shot, unchanged, when every pose clears the geometry.

    Raises:
        ValueError: If any movement endpoint violates the clearance threshold.
    """
    cast_shot = cast(dict[str, JsonValue], shot)
    movement = cast_shot.get("camera_movement")
    if movement is None:
        return cast_shot
    block = cast(dict[str, JsonValue], movement)
    for label in ("start_transform", "end_transform"):
        transform = cast(dict[str, JsonValue], block[label])
        location = transform["location"]
        distance = camera_min_distance_to_wall_centerline(location)
        if distance < WALL_CENTERLINE_CLEARANCE:
            raise ValueError(
                f"shot {cast_shot['shot_id']!r} {label} camera at {location!r} is "
                f"{distance:.3f} units from the EP1 wall's centerline, below the "
                f"{WALL_CENTERLINE_CLEARANCE:.1f}-unit clearance (wall half-thickness "
                f"{WALL_THICKNESS / 2.0} + road half-width {ROAD_WIDTH / 2.0}); "
                "no camera pose may enter the wall's avenue corridor"
            )
    return cast_shot


def validate_plan_clearance(plan: object) -> dict[str, JsonValue]:
    """Verify every movement endpoint in a plan against the real geometry.

    Args:
        plan: A shot direction plan (V1 or V2).

    Returns:
        The plan, unchanged, when every movement pose clears the geometry.

    Raises:
        ValueError: If any movement endpoint violates the clearance threshold.
        TypeError: If the plan is not a document carrying a shots list.
    """
    if type(plan) is not dict or type(plan.get("shots")) is not list:
        raise TypeError("clearance validation requires a shot direction plan document")
    result = cast(dict[str, JsonValue], plan)
    for shot in cast(list[JsonValue], result["shots"]):
        validate_movement_clearance(shot)
    return result
