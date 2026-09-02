"""Pure QA metrics for the Director Revision's camera grammar (V2 movement plans).

This module is the commander's mechanical acceptance signal for the camera-
movement rewrite: the same functions will run against the *new* movement
grammar once it exists, but they are written against the REAL document shapes
this build already produces -- a Shot Direction Plan V2 (``shot_id``,
``start_frame``/``end_frame``, optional ``camera_movement`` blocks with
``movement_type`` and ``start_transform``/``end_transform`` holding
``location``, ``look_at`` and ``lens_mm``), and the real camera-pose
vocabulary of ``cinematic_spec.CAMERA_ANCHORS``.

Everything here is pure and deterministic: no ``bpy`` import, no filesystem
access, no randomness. The only inputs are the documents and poses the engine
already emits, plus real world geometry (the wall stations of
``master_scene_v1.json``), so a test can run without Blender and a reviewer can
re-run it on any machine.

Every readability metric is explicitly a QA SIGNAL, not an aesthetic proof --
it measures whether an event object's full extent sits inside the camera's
frustum at a comfortable size, and how much of the real world shares the frame;
it never claims the result is beautiful. That matches the Director's own
framing of these checks as gates on the rewrite, not as taste tests.
"""

import math
from typing import Final, cast

from living_diorama.cinematic.camera_clearance import (
    RENDER_ASPECT,
    camera_half_fov_tangents,
)
from living_diorama.cinematic.camera_movement_planner import sample_movement_path
from living_diorama.cinematic.cinematic_schema_v1 import JsonValue
from living_diorama.cinematic.cinematic_spec import SHOT_ESTABLISHING

# The vertical extent of a wall-station slab, in world units. Real value from
# the world builder: visual/blender/scripts/apply_render_export.py:50
# (``WALL_HEIGHT = 16.0``).
WALL_STATION_HEIGHT: Final = 16.0

# The render aspect the anchors are framed at: the locked render profile is
# 1280x720 (render_execution_spec._OWNED_OUTPUT), i.e. 16:9. The anchors'
# sensor is 36x24 mm (3:2), so with Blender's AUTO sensor fit the horizontal
# field of view is the full sensor width and the vertical FOV follows the
# image aspect. The projection model itself is NOT restated here: it lives in
# exactly one place, ``camera_clearance.camera_half_fov_tangents`` (the
# lower-level geometry module), and this module imports it, so the two cannot
# disagree.
RADIAL_MOVEMENTS: Final = frozenset({"PUSH_IN", "PULL_OUT"})
"""The two movement types that move the camera along its view axis."""

TRAVEL_MOVEMENTS: Final = frozenset({"PAN", "TRACK", "REVEAL"})
"""The movement types that spatially travel or reframe (non-STATIC, non-axial)."""

WIDE_MOVEMENTS: Final = frozenset({"REVEAL", "PULL_OUT"})
"""Movement types that open the composition to a wider view."""

FRAME_FILL_COMFORTABLE_MAX: Final = 0.9
"""Above this projected-frame fill the subject is 'filling the frame' (QA bound)."""

FRAME_FILL_READABLE_MIN: Final = 0.02
"""Below this projected-frame fill the subject is a dot (QA bound)."""

type Vector3 = tuple[float, float, float]
type CameraBasis = tuple[Vector3, Vector3, Vector3]
"""The pose-basis types the frustum math works in."""


def _plan_shots(plan: object) -> list[dict[str, JsonValue]]:
    if type(plan) is not dict or type(plan.get("shots")) is not list:
        raise TypeError("camera QA metrics require a shot direction plan document")
    return cast(list[dict[str, JsonValue]], plan["shots"])


def _movement_type(shot: dict[str, JsonValue]) -> str | None:
    movement = shot.get("camera_movement")
    if not isinstance(movement, dict):
        return None
    value = movement.get("movement_type")
    return value if isinstance(value, str) else None


def no_animated_lens_zoom(plan: object) -> dict[str, object]:
    """Return whether ANY frame of ANY shot carries a changing lens value.

    Real structural check, not a hardcoded pass, checked at both levels the
    document can express a lens change:

    * the movement block's own endpoints: a ``start_transform.lens_mm`` that
      differs from ``end_transform.lens_mm`` is an animated focal length;
    * the sampled per-frame path (``camera_movement_planner.sample_movement_path``):
      any sampled pose whose ``lens_mm`` differs from the block's start lens.

    Shots without a movement block have no sampled frames and cannot animate a
    lens (the fixed anchor's locked lens is never keyframed by this layer), so
    they contribute nothing to the verdict. This build never re-lenses (the V2
    planner keeps the anchor's locked lens constant), so the metric is expected
    to pass -- but it is computed from the real plan, and a future grammar that
    animated the focal length would be caught here.

    Args:
        plan: A Shot Direction Plan V1 or V2 document.

    Returns:
        A dict with ``passes`` (bool), ``violating_shot_ids`` (list of shot
        ids whose movement changes ``lens_mm`` at endpoint or sampled-path
        level) and ``sampled_shots`` (how many movement paths were actually
        sampled).
    """
    shots = _plan_shots(plan)
    violating: list[str] = []
    sampled = 0
    for shot in shots:
        path = sample_movement_path(shot)
        if not path:
            continue
        sampled += 1
        movement = shot.get("camera_movement")
        start = movement.get("start_transform") if isinstance(movement, dict) else None
        end = movement.get("end_transform") if isinstance(movement, dict) else None
        if (
            isinstance(start, dict)
            and isinstance(end, dict)
            and start.get("lens_mm") != end.get("lens_mm")
        ):
            violating.append(cast(str, shot["shot_id"]))
            continue
        first_lens = path[0][1]["lens_mm"]
        for _, pose in path[1:]:
            if pose["lens_mm"] != first_lens:
                violating.append(cast(str, shot["shot_id"]))
                break
    return {
        "passes": not violating,
        "violating_shot_ids": violating,
        "sampled_shots": sampled,
    }


def no_push_pull_oscillation(plan: object) -> dict[str, object]:
    """Count radial push/pull oscillation pairs across the shot list, in order.

    A PUSH_IN immediately followed by a PULL_OUT -- or the reverse -- with no
    non-radial movement between them reads as pumping, the camera breathing in
    and out across a cut. Radial movements are ``PUSH_IN`` and ``PULL_OUT``;
    every other movement type (and a shot with no movement block) is
    non-radial and breaks a potential pair.

    Args:
        plan: A Shot Direction Plan V1 or V2 document.

    Returns:
        A dict with ``oscillation_count`` (int) and ``pairs``, a list of
        ``{"shot_ids": (before, after), "movement_types": (before, after)}``
        records for every adjacent radial pair whose directions oppose.
    """
    shots = _plan_shots(plan)
    ordered: list[tuple[str, str | None]] = [
        (cast(str, shot["shot_id"]), _movement_type(shot)) for shot in shots
    ]
    pairs: list[dict[str, object]] = []
    for (before_id, before_type), (after_id, after_type) in zip(ordered, ordered[1:], strict=False):
        if before_type not in RADIAL_MOVEMENTS or after_type not in RADIAL_MOVEMENTS:
            continue
        if before_type == after_type:
            continue  # two push-ins in a row are not pumping, they are a ramp
        pairs.append(
            {
                "shot_ids": (before_id, after_id),
                "movement_types": (before_type, after_type),
            }
        )
    return {"oscillation_count": len(pairs), "pairs": pairs}


# --------------------------------------------------------------------------
# Camera-space geometry (pure, shared by the readability metrics)
# --------------------------------------------------------------------------


def _camera_basis(pose: dict[str, object]) -> CameraBasis:
    """Return (right, up, forward) unit axes for a pose.

    The pose vocabulary is the anchor catalogue's: ``location`` and ``look_at``
    as three-number lists, ``lens_mm`` as a number. Forward points from the
    camera toward ``look_at``; right and up are the standard view basis with
    the world +Z axis as the up reference.
    """
    location = cast(list[object], pose["location"])
    look_at = cast(list[object], pose["look_at"])
    camera = (
        float(cast("int | float", location[0])),
        float(cast("int | float", location[1])),
        float(cast("int | float", location[2])),
    )
    target = (
        float(cast("int | float", look_at[0])),
        float(cast("int | float", look_at[1])),
        float(cast("int | float", look_at[2])),
    )

    def normalize(v: Vector3) -> Vector3:
        length = math.sqrt(sum(axis * axis for axis in v))
        if length < 1e-9:
            raise ValueError("camera pose has a zero-length view direction")
        return (v[0] / length, v[1] / length, v[2] / length)

    def cross(a: Vector3, b: Vector3) -> Vector3:
        return (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        )

    forward = normalize((target[0] - camera[0], target[1] - camera[1], target[2] - camera[2]))
    right = normalize(cross(forward, (0.0, 0.0, 1.0)))
    up = cross(right, forward)
    return right, up, forward


def _camera_space(pose: dict[str, object], point: Vector3) -> Vector3:
    """Return (x, y, z) of ``point`` in the pose's camera space (z = depth)."""
    right, up, forward = _camera_basis(pose)
    location = cast(list[object], pose["location"])
    camera = (
        float(cast("int | float", location[0])),
        float(cast("int | float", location[1])),
        float(cast("int | float", location[2])),
    )
    delta = tuple(point[i] - camera[i] for i in range(3))
    return (
        sum(delta[i] * right[i] for i in range(3)),
        sum(delta[i] * up[i] for i in range(3)),
        sum(delta[i] * forward[i] for i in range(3)),
    )


def _point_in_frustum(
    pose: dict[str, object],
    point: Vector3,
    *,
    near: float = 0.1,
    render_aspect: float = RENDER_ASPECT,
) -> tuple[bool, float, float]:
    """Return (inside, ndc_x, ndc_y) for one world point.

    ``ndc`` is the projected position normalised to [-1, 1] per axis; a point
    is inside when it lies in front of the near plane and both NDC coordinates
    are within [-1, 1]. The projection model is the single shared
    ``camera_clearance.camera_half_fov_tangents`` (Blender AUTO sensor fit:
    width-governed for the 16:9 render against the 3:2 sensor), never a local
    restatement.
    """
    lens = float(cast("int | float", pose["lens_mm"]))
    tan_x, tan_y = camera_half_fov_tangents(lens, render_aspect=render_aspect)
    x, y, z = _camera_space(pose, point)
    if z <= near:
        return False, float("inf"), float("inf")
    ndc_x = x / (z * tan_x)
    ndc_y = y / (z * tan_y)
    return -1.0 <= ndc_x <= 1.0 and -1.0 <= ndc_y <= 1.0, ndc_x, ndc_y


def _wall_station_segment(
    wall_station: dict[str, object], height: float
) -> tuple[Vector3, Vector3]:
    """Return the two ground endpoints of a wall station's centre line.

    ``wall_station`` is the real record of ``master_scene_v1.json``: a
    ``center`` [x, y], a ``direction`` [dx, dy] and a ``length`` in world
    units. The segment runs ``length/2`` either side of the center along the
    normalised direction, matching the world builder's own ``_wall_frame``
    interpretation (apply_render_export.py:63).
    """
    center = cast(list[object], wall_station["center"])
    direction = cast(list[object], wall_station["direction"])
    cx, cy = float(cast("int | float", center[0])), float(cast("int | float", center[1]))
    dx, dy = float(cast("int | float", direction[0])), float(cast("int | float", direction[1]))
    magnitude = math.hypot(dx, dy)
    if magnitude < 1e-9:
        raise ValueError("wall_station direction must be a non-zero vector")
    length = float(cast("int | float", wall_station["length"]))
    half = (dx / magnitude) * (length / 2.0), (dy / magnitude) * (length / 2.0)
    return (
        (cx - half[0], cy - half[1], 0.0),
        (cx + half[0], cy + half[1], 0.0),
    )


def _wall_station_corners(wall_station: dict[str, object], height: float) -> list[Vector3]:
    """Return the eight corners of a wall station's vertical slab (an AABB)."""
    start, end = _wall_station_segment(wall_station, height)
    xs = sorted((start[0], end[0]))
    ys = sorted((start[1], end[1]))
    return [(xs[i], ys[j], z) for i in range(2) for j in range(2) for z in (0.0, height)]


def _distance_point_to_slab(
    point: Vector3,
    start: Vector3,
    end: Vector3,
    height: float,
) -> float:
    """Return the exact distance from ``point`` to a vertical slab.

    The slab is the rectangle whose centre line runs from ``start`` to ``end``
    on the ground and whose height is ``height``. The point is expressed in the
    slab's own frame -- along the centre line, up the height axis, and off the
    plane -- and the distance is the Euclidean norm of the clamped frame
    coordinates plus the off-plane component. This is exact for interior
    projections as well as for edge and corner cases.
    """
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    segment_length = math.hypot(dx, dy)
    if segment_length < 1e-12:
        segment_length = 1.0
        dx, dy = 0.0, 0.0
    along = (dx / segment_length, dy / segment_length)
    # Slab plane normal (horizontal, perpendicular to the centre line).
    normal = (along[1], -along[0], 0.0)
    delta = (point[0] - start[0], point[1] - start[1], point[2] - start[2])
    s = delta[0] * along[0] + delta[1] * along[1]
    z = delta[2]
    off_plane = delta[0] * normal[0] + delta[1] * normal[1] + delta[2] * normal[2]
    s_clamped = max(0.0, min(segment_length, s))
    z_clamped = max(0.0, min(height, z))
    return math.sqrt((s - s_clamped) ** 2 + (z - z_clamped) ** 2 + off_plane * off_plane)


def event_object_fully_readable(
    camera_pose: dict[str, object],
    event_object: dict[str, object],
    *,
    height: float = WALL_STATION_HEIGHT,
    max_frame_fill_fraction: float = FRAME_FILL_COMFORTABLE_MAX,
    min_frame_fill_fraction: float = FRAME_FILL_READABLE_MIN,
    render_aspect: float = RENDER_ASPECT,
) -> dict[str, object]:
    """Return whether a real event object's full extent sits comfortably in frame.

    QA SIGNAL, NOT AN AESTHETIC PROOF: this measures geometry only. The event
    object is a real wall-station record (``center``/``direction``/``length``
    from ``master_scene_v1.json``) modelled as a vertical slab of the real wall
    height (16.0 world units, from the world builder). ``fully_readable`` is
    True exactly when (a) all eight corners of the slab project inside the
    pose's frustum and (b) the slab's largest projected NDC extent lies between
    ``min_frame_fill_fraction`` and ``max_frame_fill_fraction`` -- i.e. it is
    neither clipped by the frame edge nor filling near-100% of it. The camera
    pose uses the real anchor vocabulary: ``location``, ``look_at``,
    ``lens_mm``.

    Args:
        camera_pose: The real pose dict (anchor or movement endpoint shape).
        event_object: The real wall-station record.
        height: Slab height in world units (defaults to the real wall height).
        max_frame_fill_fraction: Above this projected fill the subject is
            considered to fill the frame (default 0.9).
        min_frame_fill_fraction: Below this projected fill the subject is a dot
            (default 0.02).
        render_aspect: The locked render aspect (default 16:9).

    Returns:
        A dict with ``fully_readable`` (bool), ``in_frustum`` (bool, all eight
        corners inside), ``frame_fill_fraction`` (float, largest |NDC| extent
        of any corner, clipped at 1.0 for reporting), ``distance_to_center``
        (float) and ``reasons`` (list of human-readable findings).
    """
    corners = _wall_station_corners(event_object, height)
    center = (
        (min(corner[0] for corner in corners) + max(corner[0] for corner in corners)) / 2.0,
        (min(corner[1] for corner in corners) + max(corner[1] for corner in corners)) / 2.0,
        height / 2.0,
    )
    inside = True
    fill = 0.0
    for corner in corners:
        in_frustum, ndc_x, ndc_y = _point_in_frustum(
            camera_pose, corner, render_aspect=render_aspect
        )
        if not in_frustum:
            inside = False
        if math.isfinite(ndc_x) and math.isfinite(ndc_y):
            fill = max(fill, abs(ndc_x), abs(ndc_y))
    location = cast(list[object], camera_pose["location"])
    camera = (
        float(cast("int | float", location[0])),
        float(cast("int | float", location[1])),
        float(cast("int | float", location[2])),
    )
    distance = math.sqrt(sum((center[i] - camera[i]) ** 2 for i in range(3)))
    reasons: list[str] = []
    if not inside:
        reasons.append("some part of the event object projects outside the frustum")
    if fill >= max_frame_fill_fraction:
        reasons.append(
            f"event object fills {fill:.2f} of the frame (max {max_frame_fill_fraction})"
        )
    if fill < min_frame_fill_fraction:
        reasons.append(f"event object is a dot in frame ({fill:.4f} fill)")
    return {
        "fully_readable": inside and min_frame_fill_fraction <= fill < max_frame_fill_fraction,
        "in_frustum": inside,
        "frame_fill_fraction": round(min(fill, 1.0), 6),
        "distance_to_center": round(distance, 6),
        "reasons": reasons,
    }


def context_visibility_score(
    camera_pose: dict[str, object],
    context_objects: list[dict[str, object]],
    *,
    render_aspect: float = RENDER_ASPECT,
) -> dict[str, object]:
    """Return how many distinct real context categories share the pose's frustum.

    QA SIGNAL, NOT AN AESTHETIC PROOF: a context object counts as visible when
    its named representative point projects inside the pose's frustum. Each
    record is ``{"name", "category", "location": [x, y, z]}`` -- the real named
    objects of ``master_scene_v1.json`` (districts, boundary wall stations, the
    golden-seal landmark, the platform) and ``production_world_v1.json``
    (neighborhoods). The score is the number of DISTINCT categories with at
    least one visible representative, so one district and one wall station in
    frame count as two categories, not two objects.

    Args:
        camera_pose: The real pose dict (anchor or movement endpoint shape).
        context_objects: Real named context objects with positions.
        render_aspect: The locked render aspect (default 16:9).

    Returns:
        A dict with ``visible_category_count`` (int),
        ``visible_categories`` (sorted list of category names) and
        ``visible_objects`` (sorted list of object names).
    """
    visible_objects: list[str] = []
    visible_categories: set[str] = set()
    for entry in context_objects:
        name = cast(str, entry["name"])
        category = cast(str, entry["category"])
        location = cast(list[object], entry["location"])
        point = (
            float(cast("int | float", location[0])),
            float(cast("int | float", location[1])),
            float(cast("int | float", location[2])),
        )
        inside, _, _ = _point_in_frustum(camera_pose, point, render_aspect=render_aspect)
        if inside:
            visible_objects.append(name)
            visible_categories.add(category)
    return {
        "visible_category_count": len(visible_categories),
        "visible_categories": sorted(visible_categories),
        "visible_objects": sorted(visible_objects),
    }


def camera_geometry_clearance(
    camera_pose: dict[str, object],
    geometry: dict[str, object] | list[dict[str, object]],
    min_clearance: float | None = None,
    *,
    height: float = WALL_STATION_HEIGHT,
) -> dict[str, object]:
    """Return the minimum real-world distance from the camera to the geometry.

    The geometry is the same real wall-station record(s) the readability
    metrics use: a vertical slab whose centre line is the station segment. The
    minimum is the exact distance from the camera location to the nearest
    point of every slab (interior projections included), in world units.

    No threshold is invented here: when ``min_clearance`` is None the function
    reports the distance only, and the safety threshold of the camera-grammar
    task is supplied by its caller. When a threshold IS supplied, ``passes``
    reports whether the measured distance meets it.

    Args:
        camera_pose: The real pose dict (anchor or movement endpoint shape).
        geometry: One wall-station record, or a list of them.
        min_clearance: Optional required minimum distance in world units.
        height: Slab height in world units (defaults to the real wall height).

    Returns:
        A dict with ``min_distance`` (float) and, when ``min_clearance`` is
        given, ``passes`` (bool) and ``required_clearance`` (float).
    """
    stations = geometry if isinstance(geometry, list) else [geometry]
    location = cast(list[object], camera_pose["location"])
    camera = (
        float(cast("int | float", location[0])),
        float(cast("int | float", location[1])),
        float(cast("int | float", location[2])),
    )
    minimum = float("inf")
    for station in stations:
        start, end = _wall_station_segment(station, height)
        minimum = min(minimum, _distance_point_to_slab(camera, start, end, height))
    result: dict[str, object] = {"min_distance": round(minimum, 6)}
    if min_clearance is not None:
        result["required_clearance"] = min_clearance
        result["passes"] = minimum >= min_clearance
    return result


def shot_grammar_coverage(plan: object) -> dict[str, object]:
    """Report the mechanical grammar-coverage facts of a movement plan.

    Reporting function, not a pass/fail gate: it computes the three required
    grammar elements the camera-grammar task cares about and presents the
    wide/medium-wide time fraction derived from the plan's own real per-shot
    frame windows. No hard threshold is enforced here unless the camera-grammar
    task defines one; the commander applies its own acceptance rule to the
    reported numbers.

    Required elements:
    * an establishing wide -- an ``ESTABLISHING`` shot or a ``REVEAL`` move;
    * a ``STATIC`` hold;
    * a spatial travel move -- ``PAN``, ``TRACK`` or ``REVEAL``.

    Wide/medium-wide frames are defined as the frames of shots whose movement
    is ``REVEAL``/``PULL_OUT`` plus the frames of ``ESTABLISHING`` shots (the
    neutral wide anchor), which is the closest mechanical reading of
    "wide/medium-wide" the movement vocabulary supports.

    Args:
        plan: A Shot Direction Plan V1 or V2 document.

    Returns:
        A dict with the three presence booleans, the movement histogram, and
        ``wide_medium_wide_frames`` / ``total_frames`` /
        ``wide_medium_wide_fraction`` (fraction rounded to six decimals).
    """
    shots = _plan_shots(plan)
    histogram: dict[str, int] = {}
    establishing_wide_present = False
    static_hold_present = False
    spatial_travel_present = False
    wide_frames = 0
    total_frames = 0
    for shot in shots:
        movement_type = _movement_type(shot)
        start = int(cast("int | float", shot["start_frame"]))
        end = int(cast("int | float", shot["end_frame"]))
        frames = end - start + 1
        total_frames += frames
        if movement_type is not None:
            histogram[movement_type] = histogram.get(movement_type, 0) + 1
        if shot.get("kind") == SHOT_ESTABLISHING or movement_type == "REVEAL":
            establishing_wide_present = True
        if movement_type == "STATIC":
            static_hold_present = True
        if movement_type in TRAVEL_MOVEMENTS:
            spatial_travel_present = True
        if movement_type in WIDE_MOVEMENTS or shot.get("kind") == SHOT_ESTABLISHING:
            wide_frames += frames
    fraction = (wide_frames / total_frames) if total_frames else 0.0
    return {
        "shot_count": len(shots),
        "movement_type_histogram": dict(sorted(histogram.items())),
        "establishing_wide_present": establishing_wide_present,
        "static_hold_present": static_hold_present,
        "spatial_travel_present": spatial_travel_present,
        "wide_medium_wide_frames": wide_frames,
        "total_frames": total_frames,
        "wide_medium_wide_fraction": round(fraction, 6),
    }
