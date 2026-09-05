"""``final_shots_v1`` -- the shot list for the 90 s visual-lock preview.

Why this module exists
----------------------
The Phase 2 preview plan (``ldyf.shot_planner``, five shots) never brings a
camera close enough for a viewer to recognise people as people -- the crowd is
only seen from roughly 20 m up (``tools_plan_preview_shots`` heights: 14000,
2200, 380, 2000, 5200 cm).  The Director's visual-lock spec asks for eleven
named things to be visible; this module plans eleven shots that together cover
all of them, and makes the one requirement the old plan fails **arithmetic**:
for the ``visible_humans`` shot it computes

    person_frame_fraction = person_height_cm /
                            (2 * distance_cm * tan(vertical_fov_deg / 2))

from the camera's actual vertical FOV, the real distance to the nearest planned
pedestrian in the direction of view, and a 175 cm person, then refuses to pass
a plan whose close shot falls below the floor (``validate_shots`` returns the
refusal as a problem string, never a bare assertion).

Input contract (documented because the caller builds these)
-----------------------------------------------------------
Nothing here reads binaries and nothing imports ``unreal`` -- pure stdlib and
deterministic, so the same inputs give byte-identical output.  The three inputs
are plain dicts whose geometry is in Unreal centimetres (X east, Y south,
Z up; yaw 0 = +X, increasing toward +Y -- ``ldyf.coords`` conventions):

``record`` -- a dense summary of the sealed frames record, pre-aggregated by
the caller from the record binary (frame-time conventions match
``record_manifest.json``)::

    {"clock":        {"t_begin": 0.0, "step_seconds": 1/24,
                      "frame_count": 2160},          # >= 1, else "empty record"
     "bounds_cm":    {"min_x": .., "min_y": .., "max_x": .., "max_y": ..},
     "people_cm":    [{"x": .., "y": ..}, ...],      # pedestrian samples
     "vehicles_cm":  [{"x": .., "y": ..}, ...]}      # vehicle samples

``layout`` -- a ``city_layout_v1`` document (blocks as polygon point lists)
plus the two derived datasets that carry the city's vertical life; the assembly
step must merge them in (``ldyf.building_kits.landmark_spec`` emits
``landmark``; the foliage plan emits ``foliage``)::

    {"blocks":    [{"id": .., "polygon": [{"x":..,"y":..}, ...]}, ...],
     "landmark":  {"x": .., "y": .., "yaw": .., "height_cm": ..},   # REQUIRED
     "foliage":   [{"x": .., "y": .., "canopy_height_cm": ..}, ...]} # REQUIRED

``closure`` -- the sealed closure (rule-manifest ``close_edges`` plus the
barricade location that ``ldyf.dressing.closure_props`` produced)::

    {"x": .., "y": .., "edge_ids": ["..", ...]}

A required key that is missing raises ``ValueError`` (never a made-up
coordinate): the plan must show the civic landmark and the trees, so it cannot
be built from a layout that does not say where they are.

Shot document (``final_shots_v1``)
----------------------------------
Returned by ``final_shot_plan``: ``{"schema_version", "shots", "coverage",
"total_seconds"}``.  Each shot is ``{"name", "kind", "start_s", "end_s",
"loc", "rot", "fov_deg", "covers"}`` where ``loc`` is ``[x, y, z]`` and ``rot``
is ``[pitch, yaw, roll]`` in the shape the editor's ``add_cameras`` converter
already uses (``tools_plan_preview_shots``).  Times are scheduled on an exact
integer frame grid (``seconds * fps`` frames, per-shot durations proportional
to the fixed 90 s table, largest-remainder rounding), so presentation times
tile [0, seconds] with no gap and no overlap.  The shot that claims
``visible_humans`` additionally carries ``person_frame_fraction`` and
``person_distance_cm``; ``coverage`` names, per requirement, which shot
satisfies it and carries the person arithmetic in its ``visible_humans``
entry.

Occlusion is deliberately out of scope here: every camera is anchored on data
(avenue axes, corridor edges, block frontages) and stands clear of the block
polygons it frames; the existing occlusion pass (``shot_planner.choose_bearing``)
belongs to the integration step that converts this plan into editor cameras.
"""

from __future__ import annotations

import math

FINAL_SHOTS_SCHEMA = "final_shots_v1"

# --- stated requirements (the coverage vocabulary) -------------------------

REQUIREMENTS: tuple[str, ...] = (
    "city_overview",      # 1 strong wide city overview (establishing aerial)
    "street_level",       # 2 street-level city shot, eye height 140-180 cm
    "visible_humans",     # 3 person recognisable: person_frame_fraction >= floor
    "traffic_motion",     # 4 traffic in motion
    "facade_detail",      # 5 buildings: ground-floor band + entrances legible
    "leafy_vegetation",   # 6 tree canopy against the sky
    "civic_landmark",     # 7 landmark silhouette reads
    "storefront_life",    # 8 storefront / street life
    "road_closure",       # 9 the road closure
    "traffic_reaction",   # 10 traffic reacting (queue or diversion)
    "final_city_view",    # 11 final city view to close
)

# --- tunables, documented as the stated numbers ----------------------------

PERSON_HEIGHT_CM = 175.0            # the person used in the fraction arithmetic
PERSON_FRAME_FRACTION_FLOOR = 0.20  # >= 20 % of frame height: recognisably human
ASPECT_RATIO = 16.0 / 9.0           # stored fov_deg is HORIZONTAL; vertical derived
MIN_SHOT_SECONDS = 4.0              # a shorter cut reads as a glitch
TOTAL_SECONDS_MIN = 60.0            # validate_shots: total must stay in 60..120
TOTAL_SECONDS_MAX = 120.0
TIMELINE_TOLERANCE_S = 1e-3         # start/end values are ms-rounded (_f3)
END_TOLERANCE_S = 0.1               # final end vs total (<= ~1 frame at 24 fps)
FOV_DEG = 60.0                      # horizontal FOV used for every shot
_CLOSE_DISTANCE_CM = 700.0          # design standoff to the chosen pedestrian
_STANDOFF_CM = 1400.0               # across-street standoff for facade framing

# per-shot durations (s) on the 90 s template, in timeline order.  Every value
# is >= MIN_SHOT_SECONDS * 90/60, so scaling down to the 60 s floor of the
# valid band still leaves every cut >= the 4 s minimum.
_DURATIONS = (11.0, 9.0, 9.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 7.0, 6.0)


def _f3(v: float) -> float:
    """Round to 3 decimals and kill ``-0.0`` (dressing.py:79 convention)."""
    r = round(float(v), 3)
    return 0.0 if r == 0.0 else r


def _f(v: float) -> float:
    return float(v)


def vertical_fov_deg(horizontal_fov_deg: float) -> float:
    """Vertical FOV implied by a horizontal FOV at ASPECT_RATIO (16:9).

    tan(v/2) = tan(h/2) / aspect, so this is exact for the standard projection.
    """
    return math.degrees(2.0 * math.atan(
        math.tan(math.radians(horizontal_fov_deg) / 2.0) / ASPECT_RATIO))


def person_frame_fraction(distance_cm: float, horizontal_fov_deg: float,
                          person_height_cm: float = PERSON_HEIGHT_CM) -> float:
    """Share of frame height a standing person occupies at ``distance_cm``.

    ``fraction = person_height / (2 * distance * tan(vfov / 2))`` -- the
    person's height compared with the vertical span the frame covers at that
    distance.  Distance is the ground distance to the pedestrian's base; the
    camera aims near eye height, so slant distance ~= ground distance and the
    small-angle centre-frame model is the documented approximation.
    """
    if not distance_cm > 0:
        raise ValueError(f"distance_cm must be positive, got {distance_cm!r}")
    vhalf = math.tan(math.radians(vertical_fov_deg(horizontal_fov_deg)) / 2.0)
    return _f3(person_height_cm / (2.0 * distance_cm * vhalf))


# --- small geometry helpers -------------------------------------------------


def _bounds_centre(bounds: dict) -> tuple[float, float]:
    return ((_f(bounds["min_x"]) + _f(bounds["max_x"])) / 2.0,
            (_f(bounds["min_y"]) + _f(bounds["max_y"])) / 2.0)


def _extent_half(bounds: dict) -> float:
    dx = _f(bounds["max_x"]) - _f(bounds["min_x"])
    dy = _f(bounds["max_y"]) - _f(bounds["min_y"])
    return max(dx, dy) / 2.0


def _cam_look(px: float, py: float, pz: float,
              tx: float, ty: float, tz: float) -> tuple[list[float], list[float]]:
    """Camera at (px,py,pz) looking at target (tx,ty,tz).

    Returns ``([x,y,z], [pitch,yaw,roll])`` -- yaw/pitch from ``math.atan2``
    only, roll 0, floats through ``_f3`` (mirrors shot_planner.frame_shot).
    """
    dx, dy = tx - px, ty - py
    horiz = math.hypot(dx, dy)
    if horiz <= 0.0:
        raise ValueError("camera and target coincide in plan (x/y identical)")
    yaw = math.degrees(math.atan2(dy, dx))
    pitch = math.degrees(math.atan2(tz - pz, horiz))
    return ([_f3(px), _f3(py), _f3(pz)],
            [_f3(pitch), _f3(yaw), 0.0])


def _sorted_points(points: list[dict]) -> list[dict]:
    return sorted(points, key=lambda p: (_f(p["x"]), _f(p["y"])))


def _median_point(points: list[dict]) -> dict:
    """Deterministic anchor: the middle point of the (x, y)-sorted list."""
    ordered = _sorted_points(points)
    if not ordered:
        raise ValueError("need at least one point, got none")
    return ordered[len(ordered) // 2]


def _polygon_centroid(polygon: list[dict]) -> tuple[float, float]:
    xs = [_f(p["x"]) for p in polygon]
    ys = [_f(p["y"]) for p in polygon]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _edge_midpoints(polygon: list[dict]) -> list[dict]:
    """Per polygon edge: midpoint, outward unit normal and edge direction.

    ``outward`` is approximated by the direction from the polygon centroid to
    the edge midpoint (correct for convex lots, which city blocks are).
    ``ux/uy`` is the edge direction; the avenue runs along the edge, so either
    sign of (ux, uy) is a valid avenue axis."""
    cx, cy = _polygon_centroid(polygon)
    pts = polygon + [polygon[0]]
    out = []
    for i in range(len(polygon)):
        a, b = pts[i], pts[i + 1]
        mx, my = (_f(a["x"]) + _f(b["x"])) / 2.0, (_f(a["y"]) + _f(b["y"])) / 2.0
        length = math.hypot(_f(b["x"]) - _f(a["x"]), _f(b["y"]) - _f(a["y"]))
        if length <= 0.0:
            continue
        ux, uy = (_f(b["x"]) - _f(a["x"])) / length, (_f(b["y"]) - _f(a["y"])) / length
        ox, oy = -uy, ux           # rotate edge dir +90
        # keep the normal that points away from the centroid
        if ox * (mx - cx) + oy * (my - cy) < 0.0:
            ox, oy = -ox, -oy
        out.append({"mx": _f3(mx), "my": _f3(my),
                    "ox": _f3(ox), "oy": _f3(oy),
                    "ux": _f3(ux), "uy": _f3(uy), "index": i})
    return out


def _nearest_edge(block: dict, qx: float, qy: float) -> dict:
    """Edge of ``block`` whose midpoint is nearest (qx, qy); ties by index."""
    edges = _edge_midpoints(block["polygon"])
    if not edges:
        raise ValueError(f"block {block.get('id', '?')} has no usable edges")
    return min(edges, key=lambda e: (math.hypot(e["mx"] - qx, e["my"] - qy),
                                     e["index"]))


def _anchor_block(layout: dict, qx: float, qy: float) -> dict:
    """Block whose centroid is nearest (qx, qy) -- the downtown anchor."""
    blocks = sorted(layout.get("blocks", []),
                    key=lambda b: str(b.get("id", "")))
    if not blocks:
        raise ValueError("layout has no blocks; cannot frame street/facade shots")
    def dist(b):
        cx, cy = _polygon_centroid(b["polygon"])
        return math.hypot(cx - qx, cy - qy), str(b.get("id", ""))
    return min(blocks, key=dist)


def _avenue_unit(edge: dict, px: float, py: float, record: dict) -> tuple[float, float]:
    """Avenue axis at ``edge``, oriented toward the record bounds centre.

    The edge direction is (ux, uy) == (oy, -ox); whichever sign runs toward
    the city centre is chosen so targets stay inside the city."""
    tx, ty = edge["oy"], -edge["ox"]
    cx, cy = _bounds_centre(record["bounds_cm"])
    dx, dy = cx - px, cy - py
    length = math.hypot(dx, dy)
    if length > 0.0 and tx * dx + ty * dy < 0.0:
        tx, ty = -tx, -ty
    return tx, ty


def _nearest_forward(points: list[dict], px: float, py: float,
                     tx: float, ty: float) -> float:
    """Distance to the nearest point with a positive view-direction dot.

    A pedestrian standing behind the camera is not "in the frame"; only points
    whose projection onto the view direction is positive are candidates.  The
    anchor point itself (the chosen pedestrian, also in ``points``) is always
    a candidate, so this never fails for a non-empty list.
    """
    vx, vy = tx - px, ty - py
    length = math.hypot(vx, vy)
    ux, uy = vx / length, vy / length
    best = None
    for p in points:
        rx, ry = _f(p["x"]) - px, _f(p["y"]) - py
        if rx * ux + ry * uy > 0.0:
            best = min(best, math.hypot(rx, ry)) if best is not None \
                else math.hypot(rx, ry)
    if best is None:
        raise ValueError("no pedestrian ahead of the close-shot camera")
    return best


# --- per-shot builders ------------------------------------------------------
# Every builder takes (record, layout, closure); each coordinate derives from
# the inputs.  A shot may cover several requirements; coverage is fixed here.


def _shot_city_overview(record: dict, layout: dict, closure: dict) -> dict:
    """Req 1: establishing aerial, whole city in the horizontal FOV."""
    del layout, closure
    bounds = record["bounds_cm"]
    cx, cy = _bounds_centre(bounds)
    half = _extent_half(bounds)
    slant = half / math.tan(math.radians(FOV_DEG) / 2.0)   # city fits FOV
    elev = math.radians(32.0)
    horiz, height = slant * math.cos(elev), slant * math.sin(elev)
    bearing = math.radians(135.0)
    px, py = cx + horiz * math.cos(bearing), cy + horiz * math.sin(bearing)
    loc, rot = _cam_look(px, py, height, cx, cy, 0.0)
    return {"name": "city_aerial_overview", "kind": "wide_overview",
            "loc": loc, "rot": rot, "fov_deg": FOV_DEG,
            "covers": ["city_overview"]}


def _shot_street_level(record: dict, layout: dict, closure: dict) -> dict:
    """Req 2: eye-height (160 cm) shot down the avenue at the downtown block."""
    blk = _anchor_block(layout, _f(closure["x"]), _f(closure["y"]))
    edge = _nearest_edge(blk, _f(closure["x"]), _f(closure["y"]))
    # stand on the avenue the edge faces, at eye height
    px = edge["mx"] + edge["ox"] * _STANDOFF_CM
    py = edge["my"] + edge["oy"] * _STANDOFF_CM
    # look down the avenue axis toward the city centre
    ux, uy = _avenue_unit(edge, px, py, record)
    tx, ty = px + ux * 9000.0, py + uy * 9000.0
    loc, rot = _cam_look(px, py, 160.0, tx, ty, 160.0)
    return {"name": "street_level_avenue", "kind": "street_level",
            "loc": loc, "rot": rot, "fov_deg": FOV_DEG,
            "covers": ["street_level"]}


def _shot_visible_humans(record: dict, layout: dict, closure: dict) -> dict:
    """Req 3: a person recognisably fills part of the frame -- arithmetic."""
    del layout, closure
    people = record["people_cm"]
    anchor = _median_point(people)
    ax, ay = _f(anchor["x"]), _f(anchor["y"])
    # camera 700 cm west of the chosen pedestrian (away from the building)
    px, py = ax - _CLOSE_DISTANCE_CM, ay
    loc, rot = _cam_look(px, py, 160.0, ax, ay, 150.0)
    nearest = _nearest_forward(people, px, py, ax, ay)
    fraction = person_frame_fraction(nearest, FOV_DEG)
    return {"name": "people_recognisable", "kind": "close_human",
            "loc": loc, "rot": rot, "fov_deg": FOV_DEG,
            "covers": ["visible_humans"],
            "person_distance_cm": _f3(nearest),
            "person_frame_fraction": fraction}


def _shot_traffic_motion(record: dict, layout: dict, closure: dict) -> dict:
    """Req 4: cars along the avenue, camera above the flow line."""
    del layout, closure
    vehicle = _median_point(record["vehicles_cm"])
    vx, vy = _f(vehicle["x"]), _f(vehicle["y"])
    # camera 3500 cm behind the median vehicle along the avenue
    px, py = vx, vy - 3500.0
    loc, rot = _cam_look(px, py, 700.0, vx, vy, 0.0)
    return {"name": "traffic_in_motion", "kind": "traffic_flow",
            "loc": loc, "rot": rot, "fov_deg": FOV_DEG,
            "covers": ["traffic_motion"]}


def _shot_facade_detail(record: dict, layout: dict, closure: dict) -> dict:
    """Req 5: across the street at eye height; ground-floor band fills frame.

    Target is the edge midpoint raised to 400 cm (ground-floor band, where the
    entrances live); camera 1400 cm out on the road, z = 160 cm."""
    del record
    blk = _anchor_block(layout, _f(closure["x"]), _f(closure["y"]))
    edge = _nearest_edge(blk, _f(closure["x"]), _f(closure["y"]))
    px = edge["mx"] + edge["ox"] * _STANDOFF_CM
    py = edge["my"] + edge["oy"] * _STANDOFF_CM
    loc, rot = _cam_look(px, py, 160.0, edge["mx"], edge["my"], 400.0)
    return {"name": "facade_ground_floor", "kind": "facade",
            "loc": loc, "rot": rot, "fov_deg": FOV_DEG,
            "covers": ["facade_detail"]}


def _shot_leafy_vegetation(record: dict, layout: dict, closure: dict) -> dict:
    """Req 6: a tree canopy against the sky, camera below the canopy."""
    del record, closure
    trees = layout["foliage"]
    tree = _median_point(trees)
    canopy = _f(tree.get("canopy_height_cm", 0.0))
    if not canopy > 0.0:
        raise ValueError("foliage entries need canopy_height_cm > 0")
    tx, ty = _f(tree["x"]), _f(tree["y"])
    # camera 1000 cm away at eye height, looking up at the canopy centre
    px, py = tx - 1000.0, ty
    loc, rot = _cam_look(px, py, 160.0, tx, ty, 0.8 * canopy)
    return {"name": "tree_canopy_sky", "kind": "vegetation",
            "loc": loc, "rot": rot, "fov_deg": FOV_DEG,
            "covers": ["leafy_vegetation"]}


def _shot_civic_landmark(record: dict, layout: dict, closure: dict) -> dict:
    """Req 7: the clock-tower silhouette against sky, framed from its block.

    The camera stands behind the landmark's street face (toward the block
    interior) at a raised vantage and aims up at the tower head, so the
    background above the far roofline is sky -- the silhouette reads."""
    del record, closure
    lm = layout["landmark"]
    lx, ly = _f(lm["x"]), _f(lm["y"])
    height = _f(lm.get("height_cm", 0.0))
    if not height > 0.0:
        raise ValueError("layout.landmark needs height_cm > 0")
    yaw = math.radians(_f(lm.get("yaw", 0.0)))
    d = 0.82 * height                       # standoff behind the tower
    cam_z = 0.45 * height                   # raised vantage on the block
    px, py = lx - d * math.cos(yaw), ly - d * math.sin(yaw)
    loc, rot = _cam_look(px, py, cam_z, lx, ly, 0.9 * height)
    return {"name": "civic_clock_tower", "kind": "landmark",
            "loc": loc, "rot": rot, "fov_deg": FOV_DEG,
            "covers": ["civic_landmark"]}


def _shot_storefront_life(record: dict, layout: dict, closure: dict) -> dict:
    """Req 8: street life right in front of the downtown storefront band."""
    blk = _anchor_block(layout, _f(closure["x"]), _f(closure["y"]))
    edge = _nearest_edge(blk, _f(closure["x"]), _f(closure["y"]))
    # stand on the sidewalk immediately out from the facade (300 cm), looking
    # along the frontage toward the city centre so pedestrians pass through
    px = edge["mx"] + edge["ox"] * 300.0
    py = edge["my"] + edge["oy"] * 300.0
    ux, uy = _avenue_unit(edge, px, py, record)
    tx, ty = px + ux * 3000.0, py + uy * 3000.0
    loc, rot = _cam_look(px, py, 160.0, tx, ty, 160.0)
    return {"name": "storefront_street_life", "kind": "storefront",
            "loc": loc, "rot": rot, "fov_deg": FOV_DEG,
            "covers": ["storefront_life"]}


def _shot_road_closure(record: dict, layout: dict, closure: dict) -> dict:
    """Req 9: the barrier itself at street level, on the far side of approach."""
    del record, layout
    cx, cy = _f(closure["x"]), _f(closure["y"])
    # camera stands south of the barrier (downstream of the queued approach)
    loc, rot = _cam_look(cx - 200.0, cy + 800.0, 160.0, cx, cy, 120.0)
    return {"name": "closure_barrier", "kind": "road_closure",
            "loc": loc, "rot": rot, "fov_deg": FOV_DEG,
            "covers": ["road_closure"]}


def _shot_traffic_reaction(record: dict, layout: dict, closure: dict) -> dict:
    """Req 10: queue tail and barrier in one elevated view along the flow."""
    del layout
    cx, cy = _f(closure["x"]), _f(closure["y"])
    vehicle = _median_point(record["vehicles_cm"])
    vx, vy = _f(vehicle["x"]), _f(vehicle["y"])
    # stand behind the tail of the queue, look along it toward the barrier
    px, py = vx, min(vy, cy) - 2600.0
    loc, rot = _cam_look(px, py, 1400.0, cx, cy, 0.0)
    return {"name": "traffic_queue_at_barrier", "kind": "traffic_react",
            "loc": loc, "rot": rot, "fov_deg": FOV_DEG,
            "covers": ["traffic_reaction"]}


def _shot_final_city_view(record: dict, layout: dict, closure: dict) -> dict:
    """Req 11: closing view -- moderate-height look across the skyline."""
    del layout, closure
    bounds = record["bounds_cm"]
    cx, cy = _bounds_centre(bounds)
    half = _extent_half(bounds)
    slant = 2.1 * half
    elev = math.radians(20.0)
    horiz, height = slant * math.cos(elev), slant * math.sin(elev)
    bearing = math.radians(315.0)
    px, py = cx + horiz * math.cos(bearing), cy + horiz * math.sin(bearing)
    loc, rot = _cam_look(px, py, height, cx, cy, 0.0)
    return {"name": "city_final_view", "kind": "final_view",
            "loc": loc, "rot": rot, "fov_deg": FOV_DEG,
            "covers": ["final_city_view"]}


# --- assembly ---------------------------------------------------------------


def _check_record(record: dict) -> dict:
    """Input sanity: raises ValueError for an empty or malformed record."""
    if not isinstance(record, dict) or not record:
        raise ValueError("record is empty")
    clock = record.get("clock")
    bounds = record.get("bounds_cm")
    people = record.get("people_cm") or []
    vehicles = record.get("vehicles_cm") or []
    if not isinstance(clock, dict) or not _f(clock.get("frame_count", 0)) > 0:
        raise ValueError("record is empty: clock.frame_count must be >= 1")
    if not isinstance(bounds, dict):
        raise ValueError("record.bounds_cm is required")
    if not people and not vehicles:
        raise ValueError("record is empty: no people_cm and no vehicles_cm")
    for key in ("min_x", "min_y", "max_x", "max_y"):
        if key not in bounds:
            raise ValueError(f"record.bounds_cm is missing {key!r}")
    return record


def _check_layout(layout: dict) -> dict:
    """The plan must frame the landmark and the trees, so both are required."""
    if not isinstance(layout, dict) or not layout.get("blocks"):
        raise ValueError("layout is empty or has no blocks")
    if not isinstance(layout.get("landmark"), dict):
        raise ValueError("layout has no landmark (building_kits.landmark_spec "
                         "output) -- cannot frame the civic landmark shot")
    if not layout.get("foliage"):
        raise ValueError("layout has no foliage entries -- cannot frame the "
                         "tree-canopy shot")
    return layout


def _check_closure(closure: dict) -> dict:
    if not isinstance(closure, dict) or "x" not in closure or "y" not in closure:
        raise ValueError("closure needs x and y (barricade location in cm)")
    return closure


_BUILDERS = (
    ("city_aerial_overview", _shot_city_overview),
    ("street_level_avenue", _shot_street_level),
    ("people_recognisable", _shot_visible_humans),
    ("traffic_in_motion", _shot_traffic_motion),
    ("facade_ground_floor", _shot_facade_detail),
    ("tree_canopy_sky", _shot_leafy_vegetation),
    ("civic_clock_tower", _shot_civic_landmark),
    ("storefront_street_life", _shot_storefront_life),
    ("closure_barrier", _shot_road_closure),
    ("traffic_queue_at_barrier", _shot_traffic_reaction),
    ("city_final_view", _shot_final_city_view),
)

_TEMPLATE_SECONDS = 90.0  # _DURATIONS sum


def _schedule_frames(fps: float, seconds: float) -> tuple[int, list[int]]:
    """Exact integer-frame schedule tiling [0, seconds].

    Total frame count is ``round(seconds * fps)``; each shot receives frames
    proportional to its template duration, with largest-remainder rounding so
    the per-shot frame counts sum to the total exactly.  Raises ValueError
    when any shot would come out shorter than MIN_SHOT_SECONDS (a preview too
    short for eleven readable cuts)."""
    n_total = int(round(seconds * fps))
    if n_total < 1:
        raise ValueError(f"preview is too short: {seconds} s at {fps} fps "
                         "gives no frames")
    raw = [dur / _TEMPLATE_SECONDS * n_total for dur in _DURATIONS]
    frames = [int(math.floor(r)) for r in raw]
    deficit = n_total - sum(frames)
    # give the deficit frames to the shots with the largest remainders;
    # ties resolve to the earliest shot (stable sort, no randomness)
    order = sorted(range(len(raw)),
                   key=lambda i: (raw[i] - frames[i], i), reverse=True)
    for i in order[:deficit]:
        frames[i] += 1
    for i, f in enumerate(frames):
        if f / fps < MIN_SHOT_SECONDS - 1e-9:
            raise ValueError(
                f"preview of {seconds} s at {fps} fps makes shot "
                f"{_BUILDERS[i][0]} only {f / fps:.2f} s; use at least "
                f"{MIN_SHOT_SECONDS} s per shot (seconds >= {TOTAL_SECONDS_MIN})")
    return n_total, frames


def final_shot_plan(record: dict, layout: dict, closure: dict, *,
                    fps: float = 24.0, seconds: float = 90.0) -> dict:
    """Build the whole ``final_shots_v1`` document (see module docstring).

    Eleven shots tile [0, seconds] with no gap and no overlap (integer-frame
    schedule), each named shot covers the requirement listed in ``coverage``,
    and ``validate_shots`` is run before returning -- a plan that fails it
    raises ``ValueError``.
    """
    if not fps > 0:
        raise ValueError(f"fps must be positive, got {fps!r}")
    if not seconds > 0:
        raise ValueError(f"seconds must be positive, got {seconds!r}")
    record = _check_record(record)
    layout = _check_layout(layout)
    closure = _check_closure(closure)

    if len(_DURATIONS) != len(_BUILDERS):
        raise AssertionError("duration table must match builder count")
    if abs(sum(_DURATIONS) - _TEMPLATE_SECONDS) > 1e-9:
        raise AssertionError("duration table must sum to the template length")

    n_total, frames = _schedule_frames(fps, seconds)

    shots = []
    frame = 0
    for (name, builder), n_frames in zip(_BUILDERS, frames):
        shot = builder(record, layout, closure)
        if shot["name"] != name:
            raise AssertionError(f"builder order mismatch: {shot['name']!r} != {name!r}")
        shot["start_s"] = _f3(frame / fps)
        frame += n_frames
        shot["end_s"] = _f3(frame / fps)
        shot["covers"] = list(shot["covers"])
        shots.append(shot)

    coverage: dict[str, dict] = {}
    for req in REQUIREMENTS:
        names = [s["name"] for s in shots if req in s["covers"]]
        entry: dict = {"shots": names}
        if req == "visible_humans":
            close = next(s for s in shots if "visible_humans" in s["covers"])
            entry.update({
                "person_height_cm": PERSON_HEIGHT_CM,
                "distance_to_nearest_pedestrian_cm": close["person_distance_cm"],
                "person_frame_fraction": close["person_frame_fraction"],
                "vertical_fov_deg": _f3(vertical_fov_deg(FOV_DEG)),
                "horizontal_fov_deg": FOV_DEG,
                "floor": PERSON_FRAME_FRACTION_FLOOR,
                "method": "person_height / (2 * distance * tan(vfov / 2))",
            })
        coverage[req] = entry

    doc = {
        "schema_version": FINAL_SHOTS_SCHEMA,
        "shots": shots,
        "coverage": coverage,
        "total_seconds": _f3(seconds),
    }
    problems = validate_shots(doc)
    if problems:
        raise ValueError("final_shot_plan built an invalid plan: " + "; ".join(problems))
    return doc


# --- validation --------------------------------------------------------------


def validate_shots(doc: dict) -> list[str]:
    """Problems with a ``final_shots_v1`` doc, one string per refusal.

    Refuses: gaps/overlaps in the timeline; a total duration outside
    60..120 s; a requirement with no covering shot; a ``person_frame_fraction``
    below the floor on the shot claiming ``visible_humans``; a camera below
    ground; a shot shorter than MIN_SHOT_SECONDS.  Empty list == valid.
    """
    problems: list[str] = []
    if not isinstance(doc, dict) or doc.get("schema_version") != FINAL_SHOTS_SCHEMA:
        return [f"not a {FINAL_SHOTS_SCHEMA} document"]
    shots = doc.get("shots") or []
    if not shots:
        return ["document has no shots"]

    total = _f(doc.get("total_seconds", 0.0))
    if not (TOTAL_SECONDS_MIN <= total <= TOTAL_SECONDS_MAX):
        problems.append(f"total duration {total} s outside "
                        f"{TOTAL_SECONDS_MIN}-{TOTAL_SECONDS_MAX} s")

    ordered = sorted(shots, key=lambda s: _f(s["start_s"]))
    prev_end = 0.0
    for i, s in enumerate(ordered):
        start, end = _f(s["start_s"]), _f(s["end_s"])
        if not end > start:
            problems.append(f"shot {s.get('name', '?')}: end_s ({end}) must "
                            f"exceed start_s ({start})")
        if i == 0:
            if abs(start - 0.0) > TIMELINE_TOLERANCE_S:
                problems.append(f"timeline does not start at 0 (shot "
                                f"{s.get('name', '?')} starts at {start})")
        elif abs(start - prev_end) > TIMELINE_TOLERANCE_S:
            problems.append(f"timeline gap or overlap between "
                            f"{prev_end} and {start} (shot {s.get('name', '?')})")
        if end - start < MIN_SHOT_SECONDS - 1e-9:
            problems.append(f"shot {s.get('name', '?')} is only "
                            f"{end - start} s, below the {MIN_SHOT_SECONDS} s minimum")
        loc = s.get("loc")
        if not isinstance(loc, (list, tuple)) or len(loc) != 3 or loc[2] < 0.0:
            problems.append(f"shot {s.get('name', '?')}: camera below ground "
                            f"or bad loc {loc!r}")
        prev_end = end
    if ordered and abs(prev_end - total) > END_TOLERANCE_S:
        problems.append(f"timeline ends at {prev_end}, not total {total}")

    covered = set()
    for s in shots:
        covered.update(s.get("covers") or ())
    for req in REQUIREMENTS:
        if req not in covered:
            problems.append(f"requirement {req!r} has no covering shot")
        entry = (doc.get("coverage") or {}).get(req)
        if not entry or not entry.get("shots"):
            problems.append(f"coverage names no shot for requirement {req!r}")

    if "visible_humans" in covered:
        close = next((s for s in shots if "visible_humans" in s.get("covers", ())),
                     None)
        if close is None:
            problems.append("no single shot claims visible_humans")
        else:
            frac = _f(close.get("person_frame_fraction", -1.0))
            if frac < PERSON_FRAME_FRACTION_FLOOR:
                problems.append(
                    f"close shot {close.get('name', '?')} person_frame_fraction "
                    f"{frac} below floor {PERSON_FRAME_FRACTION_FLOOR}")
    return problems
