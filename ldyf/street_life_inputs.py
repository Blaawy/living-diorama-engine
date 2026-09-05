"""``street_life_inputs_v1`` -- the geometry ``ldyf.street_life`` needs but
``ldyf.city_layout`` does not emit.

``street_life`` expects two things the layout document does not carry:

* ``rooftop_props`` wants, per building, a **roof polygon** (a list of
  ``{x, y}`` in Unreal cm), while ``city_layout.building_slots`` emits facade
  *slots*: a point on the street-facing wall, an outward ``yaw`` and a
  ``width_cm`` frontage -- no plan shape;
* ``parked_cars`` reads the road spec from ``layout["spec"]`` (street_life.py
  line 833: ``spec = layout.get("spec")``) but ``city_layout.write_layout``
  never stores it, so kerb geometry is unknowable and parking is omitted.

This module closes both gaps with pure stdlib, deterministic geometry
(no ``random``, no ``import unreal``, same input document -> byte-identical
output).  Nothing here is a design decision for the city; it is the missing
plumbing between two already-built modules.

Sign convention (the one fix this module exists to get right)
-------------------------------------------------------------
``city_layout.frontages`` builds each facade with ``yaw`` = the *outward*
edge normal, i.e. pointing away from the block centre toward the road
(city_layout.py lines 350-353), and ``building_slots`` copies that ``yaw``
straight onto the slot (city_layout.py line 423).  ``building_kits`` states
the consequence (building_kits.py lines 38-41): *"the slot's yaw is the
outward edge normal ... the footway side of the footprint is the side the
slot's yaw points away from the block centre"*.

So the street wall (the frontage) is the line through the slot point spanned
by the *tangent* of ``yaw``, and the building mass lies on the *opposite*
side of that line, at ``-yaw`` -- the side toward the block centre.  This
module TRUSTS the slot field ``yaw`` (the field ``city_layout`` emits and the
field ``building_kits`` documents); a ``yaw_deg`` key is honoured as an alias
for hand-built slot docs but is never emitted by ``city_layout``.  The unit
vector for a yaw is ``(cos, sin)`` -- ``ldyf.coords.unreal_yaw_unit_vector``
(coords.py lines 102-107) -- so the footprint rectangle is centred
``depth_cm / 2`` *behind* the slot point, at
``slot - (depth_cm / 2) * (cos yaw, sin yaw)``, and its street side is the
line through the slot point.  A generator that instead pushes the mass
*toward* the street puts every building in the road; that sign error is what
``validate_inputs`` detects against the carriageway lanes of the embedded
road spec (see below).

Schema
------
``street_life_inputs(layout, road_spec, ...)`` returns
``{"schema_version", "layout", "buildings", "counts"}``, ready to hand to
``street_life.build_street_life(layout=doc["layout"], buildings=doc["buildings"])``.

Each building record carries the join-critical fields ``id``, ``polygon``
(the **roof** outline, footprint inset by ``inset_cm``), ``block_id`` and
``height_cm``, plus the source slot geometry and the full ``footprint``
outline.  ``rooftop_props`` only reads ``id`` and ``polygon`` (street_life.py
lines 645-650), so the extra fields are inert to it, and ``validate_inputs``
needs the actual footprint of each record to check lane overlap -- it cannot
re-derive a footprint from the slot, because a mirrored document would then
validate itself.

ID guarantee: every building record's ``id`` is the slot's ``slot_id``
(``"<block_id>:f<i>"``), and ``building_kits.build_kits`` keys its building
entries by exactly that value -- ``bid = s["slot_id"]`` then
``"building_id": bid`` (building_kits.py lines 743 and 756).  The two
collections therefore join on ``id`` == ``building_id`` by construction.

``height_cm`` is a deterministic roof-plane height: a slot that already
carries a positive ``height_cm`` is kept, otherwise the mid band of
``building_kits`` (1600-2600 cm) is sampled by digest of ``(id, seed)`` and
snapped UP to a 300 cm storey (values 1800/2100/2400).  It exists so the
record always has a roof height; when the caller also runs
``building_kits.build_kits`` the massing height against the same
``building_id`` is the authoritative one (per-building heights depend on
block band classification, which is building_kits' job).

Validation problems are returned as a list of human-readable strings; an
empty list means the document is valid.  A ``ValueError`` is raised for
non-positive ``depth_cm``/``inset_cm`` and for an ``inset_cm`` large enough
to collapse a polygon.
"""

from __future__ import annotations

import copy
import hashlib
import math
from typing import Any, Sequence

SCHEMA_VERSION = "street_life_inputs_v1"

# Defaults chosen to compose with the rest of the pipeline:
# * the layout's own slot depth (city_layout.building_slots default
#   depth_cm=1500.0) is the natural building depth;
# * street_life's parapet margin default is 60 cm
#   (street_life.py DEFAULT_ROOFTOP_MARGIN_CM = 60.0), so an inset of 60 cm
#   keeps rooftop props off the parapet edge before street_life re-checks.
DEFAULT_DEPTH_CM = 1500.0
DEFAULT_INSET_CM = 60.0

# building_kits HEIGHT_BAND_MID, used only as the deterministic placeholder
# band when the layout has not stamped per-building heights.
_HEIGHT_BAND_MID = (1600.0, 2600.0)
_STOREY_CM = 300.0
_EPS = 1e-6


# --- small pure helpers (mirroring the private ones in sibling modules) -----


def _f3(v: float) -> float:
    """Round to 3 decimals and kill ``-0.0`` (byte determinism, same as
    ``city_layout._f3``)."""
    return round(float(v), 3) + 0.0


def _digest(*parts: Any) -> int:
    """sha256 of the parts joined by ``'|'`` -> int of the first 16 hex chars.

    Same scheme as ``city_layout._digest`` / ``building_kits._digest`` so a
    digest over ``(id, seed)`` composes with the rest of the pipeline.
    """
    text = "|".join(str(p) for p in parts)
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def _yaw_unit(yaw_deg: float) -> tuple[float, float]:
    """Unreal-space unit vector a yaw points along: (cos, sin).

    This is ``ldyf.coords.unreal_yaw_unit_vector`` inlined so this module
    stays dependency-free; coords.py is the single authority for the rule.
    """
    r = math.radians(float(yaw_deg))
    return (math.cos(r), math.sin(r))


def _slots_of(layout: dict) -> list[dict]:
    """Building slots of a layout: ``layout["building_slots"]["slots"]`` or a
    bare list (the two shapes street_life accepts)."""
    bs = layout.get("building_slots")
    if isinstance(bs, dict):
        return list(bs.get("slots") or [])
    if isinstance(bs, list):
        return list(bs)
    return []


def _slot_yaw_deg(slot: dict) -> float:
    """Yaw of a facade slot.

    Trusted field: ``yaw`` -- the field ``city_layout.frontages``/``building_slots``
    emit (outward edge normal, away from the block centre).  ``yaw_deg`` is
    honoured as an alias for hand-built slot documents.
    """
    if slot.get("yaw") is not None:
        return float(slot["yaw"])
    if slot.get("yaw_deg") is not None:
        return float(slot["yaw_deg"])
    raise ValueError("slot has neither yaw nor yaw_deg: %r" % (slot.get("id"),))


def _point_in_poly(px: float, py: float, poly: Sequence[dict]) -> bool:
    """Even-odd ray cast; works for clockwise and counter-clockwise polygons."""
    inside = False
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]["x"], poly[i]["y"]
        bx, by = poly[(i + 1) % n]["x"], poly[(i + 1) % n]["y"]
        if ((ay > py) != (by > py)) and \
                (px < (bx - ax) * (py - ay) / (by - ay) + ax):
            inside = not inside
    return inside


def _seg_intersect(a: dict, b: dict, c: dict, d: dict) -> bool:
    """True when segment ab properly intersects segment cd (not merely
    touching at an endpoint, so shared corners of concentric rectangles do
    not count as crossings)."""

    def orient(p: dict, q: dict, r: dict) -> float:
        return (q["x"] - p["x"]) * (r["y"] - p["y"]) - \
               (q["y"] - p["y"]) * (r["x"] - p["x"])

    o1 = orient(a, b, c)
    o2 = orient(a, b, d)
    o3 = orient(c, d, a)
    o4 = orient(c, d, b)
    if o1 == 0.0 or o2 == 0.0 or o3 == 0.0 or o4 == 0.0:
        return False  # collinear / endpoint touch is not a crossing
    return ((o1 > 0.0) != (o2 > 0.0)) and ((o3 > 0.0) != (o4 > 0.0))


def _dist_pt_seg(px: float, py: float, ax: float, ay: float,
                 bx: float, by: float) -> float:
    """Distance from (px, py) to segment ab."""
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _polys_overlap(a: Sequence[dict], b: Sequence[dict]) -> bool:
    """True when two (convex) polygons overlap: a vertex of either inside the
    other, or a proper edge crossing between them."""
    for p in a:
        if _point_in_poly(p["x"], p["y"], b):
            return True
    for p in b:
        if _point_in_poly(p["x"], p["y"], a):
            return True
    na, nb = len(a), len(b)
    for i in range(na):
        for j in range(nb):
            if _seg_intersect(a[i], a[(i + 1) % na], b[j], b[(j + 1) % nb]):
                return True
    return False


def _poly_edge_distance(px: float, py: float, poly: Sequence[dict]) -> float:
    """Minimum distance from (px, py) to the edges of ``poly``."""
    n = len(poly)
    best = float("inf")
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        best = min(best, _dist_pt_seg(px, py, a["x"], a["y"], b["x"], b["y"]))
    return best


def _rect_corners(cx: float, cy: float, yaw_deg: float,
                  width_cm: float, depth_cm: float) -> list[dict]:
    """Corners of a ``width_cm`` x ``depth_cm`` rectangle centred on (cx, cy).

    Lateral axis is the yaw tangent ``t = (-sin, cos)``; depth axis is ``-u``
    where ``u = (cos, sin)`` is the yaw direction (the rectangle recedes
    opposite its yaw, i.e. away from the street).  Each corner rounded with
    ``_f3`` for byte determinism.
    """
    ux, uy = _yaw_unit(yaw_deg)
    tx, ty = -uy, ux
    hw, hd = width_cm / 2.0, depth_cm / 2.0
    # Corners are emitted as a CYCLE, not as a nested-loop Z. The nested form
    # gives (-t,-d), (-t,+d), (+t,-d), (+t,+d), whose 2nd->3rd edge is a
    # diagonal, so the "polygon" self-intersects into a bowtie and every
    # containment test on it is meaningless -- which is exactly why every roof
    # polygon reported that it crossed its own footprint. The identical winding
    # bug was already found once in street_life._rect_corners.
    out: list[dict] = []
    for sign_t, sign_d in ((-1.0, -1.0), (-1.0, 1.0), (1.0, 1.0), (1.0, -1.0)):
        out.append({"x": _f3(cx + sign_t * hw * tx - sign_d * hd * ux),
                    "y": _f3(cy + sign_t * hw * ty - sign_d * hd * uy)})
    return out


def _footprint_corners(slot: dict, depth_cm: float) -> list[dict]:
    """Footprint corners for one slot: a ``width_cm`` x ``depth_cm``
    rectangle whose street side is centred on the slot point.  The rectangle
    centre sits ``depth_cm / 2`` behind the slot along the outward normal, so
    the mass recedes away from the street.  ``building_footprint`` and
    ``roof_polygons`` both build their footprint from this one helper so
    neither can silently flip the sign."""
    yaw = _slot_yaw_deg(slot)
    ux, uy = _yaw_unit(yaw)
    cx = float(slot["x"]) - (depth_cm / 2.0) * ux
    cy = float(slot["y"]) - (depth_cm / 2.0) * uy
    return _rect_corners(cx, cy, yaw, float(slot["width_cm"]), depth_cm)


# --- the documented entry points -------------------------------------------


def building_footprint(slot: dict, *, depth_cm: float) -> list[dict]:
    """The four ``{x, y}`` corners of one building's footprint.

    The slot point is the MIDDLE of the street-facing frontage; the frontage
    is ``slot["width_cm"]`` wide; the building extends ``depth_cm`` AWAY FROM
    the street, i.e. opposite the outward normal.

    Sign fix (stated because getting it backwards puts every building in the
    road): ``city_layout`` defines the slot's trusted ``yaw`` field as the
    OUTWARD edge normal -- away from the block centre toward the road
    (city_layout.py ``frontages`` lines 350-353) -- and ``building_kits``
    confirms the footway lies on the side the yaw points away from the block
    centre (building_kits.py lines 38-41).  The footprint is therefore a
    ``width_cm`` x ``depth_cm`` rectangle whose STREET side is centred on the
    slot point; the rectangle's centre sits ``depth_cm / 2`` behind the slot,
    at ``slot - (depth_cm / 2) * (cos yaw, sin yaw)``, and the whole mass
    recedes toward the block centre, never toward the street.  Raises
    ``ValueError`` for non-positive ``depth_cm`` or a slot without a positive
    ``width_cm``/position/yaw.
    """
    depth = float(depth_cm)
    if not depth > 0.0:
        raise ValueError("depth_cm must be positive, got %r" % (depth_cm,))
    width = float(slot.get("width_cm") or 0.0)
    if not width > 0.0:
        raise ValueError("slot needs a positive width_cm (frontage), got %r"
                         % (slot.get("width_cm"),))
    if slot.get("x") is None or slot.get("y") is None:
        raise ValueError("slot needs x and y, got %r" % (slot.get("id"),))
    return _footprint_corners(slot, depth)


def roof_polygons(layout: dict, *, depth_cm: float = DEFAULT_DEPTH_CM,
                  inset_cm: float = DEFAULT_INSET_CM) -> list[dict]:
    """One building record per facade slot: the roof polygon, inset so
    rooftop props cannot sit on the parapet edge.

    Each record: ``{"id", "polygon", "block_id", "height_cm"}`` (the fields
    ``street_life.rooftop_props`` and the join to ``building_kits`` need)
    plus the source geometry and the full ``footprint`` outline, which
    ``validate_inputs`` reads.  The roof polygon is the footprint shrunk by
    ``inset_cm`` on every side (a rectangle concentric with the footprint),
    so it shares the footprint's sign: both recede away from the street.

    IDs join ``building_kits`` by construction: ``id`` is the slot's
    ``slot_id`` and ``building_kits.build_kits`` emits
    ``"building_id": s["slot_id"]`` for exactly those slots (building_kits.py
    lines 743, 756), so the roof list and the kit list can be joined on
    ``id`` == ``building_id``.

    ``height_cm`` is kept from the slot when present, else sampled by digest
    of ``(id, seed)`` inside the documented mid band (1600-2600 cm) and
    snapped UP to a 300 cm storey (values 1800/2100/2400) -- a deterministic
    roof-plane height, not the building_kits massing height.

    Raises ``ValueError`` for non-positive ``depth_cm``/``inset_cm`` or an
    ``inset_cm`` >= half of a slot's smaller side (the polygon would
    collapse).  Deterministic: slots are visited in sorted ``slot_id`` order
    and every number is ``_f3``-rounded.
    """
    depth = float(depth_cm)
    if not depth > 0.0:
        raise ValueError("depth_cm must be positive, got %r" % (depth_cm,))
    inset = float(inset_cm)
    if not inset > 0.0:
        raise ValueError("inset_cm must be positive, got %r" % (inset_cm,))
    seed = int(layout.get("seed", 0) or
               layout.get("building_slots", {}).get("seed", 0) or 0)
    slots = sorted(_slots_of(layout), key=lambda s: str(s.get("slot_id", "")))
    out: list[dict] = []
    for s in slots:
        sid = str(s.get("slot_id"))
        if not sid:
            continue
        w = float(s.get("width_cm") or 0.0)
        if not w > 0.0:
            raise ValueError("slot %s needs a positive width_cm" % sid)
        if 2.0 * inset >= w or 2.0 * inset >= depth:
            raise ValueError(
                "inset_cm %.3f >= half of the smaller footprint side of %s "
                "(width %.3f, depth %.3f) -- the roof polygon would collapse"
                % (inset, sid, w, depth))
        yaw = _slot_yaw_deg(s)
        ux, uy = _yaw_unit(yaw)
        cx = float(s["x"]) - (depth / 2.0) * ux
        cy = float(s["y"]) - (depth / 2.0) * uy
        footprint = [{"x": _f3(p["x"]), "y": _f3(p["y"])}
                     for p in _footprint_corners(s, depth)]
        roof = [{"x": _f3(p["x"]), "y": _f3(p["y"])}
                for p in _rect_corners(cx, cy, yaw, w - 2.0 * inset,
                                       depth - 2.0 * inset)]
        height = float(s.get("height_cm") or 0.0)
        if not height > 0.0:
            lo, hi = _HEIGHT_BAND_MID
            unit = _digest(sid, seed, "height") / float(0xFFFFFFFFFFFFFFFF)
            sampled = lo + (hi - lo) * unit
            height = _STOREY_CM * max(math.ceil(lo / _STOREY_CM),
                                      math.floor(sampled / _STOREY_CM))
        out.append({
            "id": sid,
            "polygon": roof,
            "block_id": str(s.get("block_id") or ""),
            "height_cm": _f3(height),
            "footprint": footprint,
            "x": _f3(float(s["x"])), "y": _f3(float(s["y"])),
            "yaw": _f3(yaw), "width_cm": _f3(w), "depth_cm": _f3(depth),
            "inset_cm": _f3(inset),
        })
    out.sort(key=lambda b: str(b["id"]))
    return out


def attach_road_spec(layout: dict, road_spec: dict) -> dict:
    """A NEW layout document carrying the road spec under ``layout["spec"]``
    -- the key ``street_life.parked_cars`` reads (street_life.py line 833).

    The input ``layout`` is never mutated (deep copy).  If the input already
    carries a spec the ARGUMENT wins; the returned document then also marks
    the replacement with ``spec_replaced_previous: True`` so the choice is
    recorded, not silent.
    """
    out = copy.deepcopy(layout)
    if out.get("spec"):
        out["spec_replaced_previous"] = True
    out["spec"] = copy.deepcopy(road_spec)
    return out


def street_life_inputs(layout: dict, road_spec: dict, **kw: Any) -> dict:
    """The convenience assembly: a ``street_life_inputs_v1`` document ready
    to hand straight to ``street_life.build_street_life(doc["layout"],
    doc["buildings"], ...)``.

    Returns ``{"schema_version", "layout", "buildings", "counts"}`` where
    ``layout`` has the road spec embedded (``parked_cars`` can then run) and
    ``buildings`` are the roof-polygon records for ``rooftop_props``.  ``kw``
    forwards ``depth_cm``/``inset_cm`` to ``roof_polygons``.
    """
    depth = float(kw.get("depth_cm", DEFAULT_DEPTH_CM))
    inset = float(kw.get("inset_cm", DEFAULT_INSET_CM))
    buildings = roof_polygons(layout, depth_cm=depth, inset_cm=inset)
    return {
        "schema_version": SCHEMA_VERSION,
        "layout": attach_road_spec(layout, road_spec),
        "buildings": buildings,
        "counts": {
            "buildings": len(buildings),
            "blocks": len({b["block_id"] for b in buildings
                           if b["block_id"]}),
        },
    }


def _car_lane_bands(spec: dict) -> list[list[dict]]:
    """Per carriageway lane of every normal edge: the swept full-width band,
    as one quad per polyline segment.

    A carriageway lane is one cars drive on -- ``street_life._is_car_lane``
    defines it as a lane that explicitly disallows pedestrians
    (``"pedestrian" in (lane.get("disallow") or [])``, street_life.py
    lines 715-717); the same test is used here so a layout whose lanes
    declare neither still has nothing to collide with.
    """
    bands: list[list[dict]] = []
    for e in sorted(spec.get("edges", []), key=lambda e: str(e["id"])):
        if e.get("function") not in (None, "normal"):
            continue
        for ln in sorted(e.get("lanes", []), key=lambda l: str(l["id"])):
            if "pedestrian" not in (ln.get("disallow") or []):
                continue  # sidewalk / unspecified lane: not a carriageway lane
            pts = ln.get("polyline") or []
            if len(pts) < 2:
                continue
            w = ln.get("width_cm_effective")
            if w is None:
                w = ln.get("width_cm")
            if not w or float(w) <= 0.0:
                continue
            half = float(w) / 2.0
            for i in range(len(pts) - 1):
                ax, ay = pts[i]["x"], pts[i]["y"]
                bx, by = pts[i + 1]["x"], pts[i + 1]["y"]
                seg = math.hypot(bx - ax, by - ay)
                if seg <= 1e-9:
                    continue
                ux, uy = (bx - ax) / seg, (by - ay) / seg
                nx, ny = -uy, ux
                q = [{"x": ax + nx * half, "y": ay + ny * half},
                     {"x": bx + nx * half, "y": by + ny * half},
                     {"x": bx - nx * half, "y": by - ny * half},
                     {"x": ax - nx * half, "y": ay - ny * half}]
                bands.append(q)
    return bands


def validate_inputs(doc: dict) -> list[str]:
    """Problems with a ``street_life_inputs_v1`` document; empty = valid.

    Catches, as real geometric checks:

    * a layout with no embedded road spec (``parked_cars`` would omit every
      car in the dark -- street_life.py lines 833-835);
    * a duplicate building ``id``;
    * a footprint that overlaps a carriageway lane of the embedded road spec
      -- the sign-error detector.  A correct footprint recedes AWAY from the
      street and never reaches a lane; a mirrored one (back wall pushed
      toward the road) is swept by the lane band and is reported.  Carriage
      lanes are those that disallow pedestrians, exactly like
      ``street_life._is_car_lane``, and each lane's band is its full-width
      sweep so even a kerbside lane counts;
    * a roof polygon that is not strictly inside its own footprint (a roof
      vertex outside the footprint, a roof edge crossing a footprint edge,
      or a roof vertex sitting on the footprint boundary).
    """
    problems: list[str] = []
    layout = doc.get("layout") or {}
    if not isinstance(layout, dict) or not layout.get("spec"):
        problems.append("layout carries no embedded road spec (key 'spec'); "
                        "parked_cars cannot place a single car")
    buildings = doc.get("buildings") or []
    seen: set[str] = set()
    for b in buildings:
        bid = str(b.get("id"))
        if bid in seen:
            problems.append("duplicate building id: %s" % bid)
        seen.add(bid)
    # --- footprint vs carriageway lane (sign-error detector) ---------------
    spec = layout.get("spec")
    if spec:
        bands = _car_lane_bands(spec)
        for b in buildings:
            fp = b.get("footprint") or []
            if len(fp) < 3:
                continue
            for band in bands:
                if _polys_overlap(fp, band):
                    problems.append(
                        "footprint of building %s overlaps a carriageway "
                        "lane -- the footprint points at the street instead "
                        "of away from it" % b.get("id"))
                    break
    # --- roof strictly inside its footprint --------------------------------
    for b in buildings:
        roof = b.get("polygon") or []
        fp = b.get("footprint") or []
        if len(roof) < 3 or len(fp) < 3:
            problems.append("building %s needs polygon and footprint with at "
                            "least 3 corners each" % b.get("id"))
            continue
        for p in roof:
            if not _point_in_poly(p["x"], p["y"], fp):
                problems.append("roof polygon of building %s is not strictly "
                                "inside its footprint (vertex outside)"
                                % b.get("id"))
                break
            if _poly_edge_distance(p["x"], p["y"], fp) < _EPS:
                problems.append("roof polygon of building %s touches the "
                                "footprint boundary (not strictly inside)"
                                % b.get("id"))
                break
        for i in range(len(roof)):
            for j in range(len(fp)):
                if _seg_intersect(roof[i], roof[(i + 1) % len(roof)],
                                  fp[j], fp[(j + 1) % len(fp)]):
                    problems.append("roof polygon of building %s crosses the "
                                    "footprint boundary" % b.get("id"))
                    break
            else:
                continue
            break
    return problems
