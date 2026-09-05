"""``street_life_v1`` -- the human scale: shopfronts, signs, rooftop plant and
kerbside parked cars, derived deterministically from the ``city_layout_v1``
document (``ldyf.city_layout``) and, for the parked cars, from the ``road_spec``
the layout was built from.

Pure stdlib, no ``import unreal``.  Determinism laws mirror ``ldyf.roads`` /
``ldyf.city_layout`` / ``ldyf.dressing``: every float goes through ``_f3``
(which also kills ``-0.0``), iteration is over ids sorted lexicographically,
and all variation comes from ``hashlib.sha256`` digests of exact documented
strings -- never from ``random``.

The rule this module inherits (``city_layout.furniture_slots`` docstring)
-------------------------------------------------------------------------
Nothing may be placed where vehicles drive -- except parked cars, which belong
exactly at the kerbside and nowhere else.  An earlier ``furniture_slots`` walked
every lane and put 336 of 672 pieces of street furniture in live traffic; the
fix was to skip lanes that disallow pedestrians.  The collections here respect
the same principle:

* storefronts and signs sit **on the building facade** or project into the
  footway only, and their projection is clamped to the footway width, so they
  never reach the carriageway;
* rooftop props sit on roofs;
* parked cars are the one deliberate exception: they occupy a narrow band just
  inside the kerb of the carriageway (the legal kerbside parking strip of the
  outermost car lane), aligned with the lane direction, and are kept out of
  junctions, crosswalks and the closure zone.

Restraint (the Director's instruction)
--------------------------------------
The Director asks for "only enough professional detail to stop the city
feeling empty" and explicitly warns against clutter and busywork.  Densities
chosen (all tunable, all written into the document's ``params`` block):

* storefronts -- **one per 6000 cm of built frontage (1.7 per 100 m)**: a 200 m
  block face shows roughly 3 active frontages per side, enough to read as an
  inhabited street, sparse enough not to become a mall.
* signs -- at most one sign per storefront and only on a minority (default 35%)
  of storefronts: about 0.6 projecting/flat signs per 100 m of frontage.
* rooftop props -- one prop per roughly 700 m2 of roof (vent / AC / stair /
  antenna), so a 20 m x 15 m roof gets a single prop and only larger roofs get
  more.  Roofs are not junkyards.
* parked cars -- occupancy defaults to 30% of the *legal* kerbside run
  (junction ends, crosswalk bands and closed edges removed first), so streets
  read as having residents, not as a car park.

Input expectations (documented contract)
----------------------------------------
* ``storefront_slots`` / ``parked_cars`` take ``layout`` -- the document
  assembled by ``city_layout.write_layout``, i.e. a dict carrying ``blocks``,
  ``building_slots`` (dict with ``slots`` or a bare list), ``furniture_slots``
  and ``crossing_slots``.  ``parked_cars`` additionally needs ``layout["spec"]``
  (the ``road_spec_v1`` the layout was derived from): kerb lines, lane
  direction and crosswalk geometry are read from it.  Without the spec the kerb
  cannot be known and parking is omitted (no cars invented in the dark).
  Closure-zone edges are read from ``layout["closed_edge_ids"]`` when present.
* ``rooftop_props`` takes ``buildings`` -- building records that each carry
  ``id`` and ``polygon`` (roof outline, list of ``{x, y}`` in Unreal cm).
  ``city_layout`` gives facade slots, not footprints, so the caller supplies
  the roof polygons; a record without a ``polygon`` raises ``ValueError``
  because the "inside the roof, off the parapet" guarantee cannot be honoured.
* ``conflicts`` takes iterables of placed items; each item contributes a
  footprint: an oriented rectangle when it carries ``width_cm``/``depth_cm``
  (``length_cm`` counts as depth for parked cars), else a disc of
  ``footprint_radius_cm`` (default 45).  Items report overlap pairs; the caller
  decides what to do with them.

``_f3`` every float; ``ValueError`` for non-positive spacing and for occupancy
outside [0, 1].
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Iterable, Sequence

from .coords import normalise_deg

STREET_LIFE_VERSION = "street_life_v1"

# Density defaults (documented in the module docstring, per 100 m of frontage).
DEFAULT_STOREFRONT_SPACING_CM = 6000.0   # -> 1.7 storefronts per 100 m
DEFAULT_STOREFRONT_SETBACK_CM = 900.0    # no storefront within 9 m of a corner
DEFAULT_SIGN_SHARE = 0.35                # minority of storefronts get a sign
DEFAULT_FOOTWAY_CM = 300.0               # facade->kerb when layout cannot say
DEFAULT_ROOFTOP_MARGIN_CM = 60.0         # parapet clearance, documented default
DEFAULT_ROOFTOP_MAX_PER_ROOF = 4
DEFAULT_ROOFTOP_AREA_PER_PROP_CM2 = 7_000_000.0  # 1 prop per ~700 m2 of roof
DEFAULT_OCCUPANCY = 0.30                 # fraction of the legal kerb run used
DEFAULT_CAR_LENGTH_CM = 460.0
DEFAULT_CAR_WIDTH_CM = 190.0
DEFAULT_CAR_BUMPER_GAP_CM = 80.0         # enforced min bumper-to-bumper gap
DEFAULT_CAR_KERB_GAP_CM = 15.0           # car side edge stays this far off kerb
DEFAULT_JUNCTION_CLEAR_CM = 900.0        # no parking within 9 m of a junction
DEFAULT_CROSSWALK_CLEAR_CM = 100.0       # plus half crossing depth each side

_SIGN_KINDS = ("flat", "projecting")
_STOREFRONT_KINDS = ("entrance", "shopfront")
_ROOF_KINDS = ("vent", "ac_unit", "stair_house", "antenna")
# (width_cm, depth_cm, height_cm) per roof prop kind.
_ROOF_KIND_SIZE = {
    "vent": (120.0, 120.0, 90.0),
    "ac_unit": (150.0, 120.0, 110.0),
    "stair_house": (300.0, 220.0, 260.0),
    "antenna": (60.0, 60.0, 320.0),
}
_CAR_VARIANTS = ("sedan", "hatch", "suv", "compact")


# --- small deterministic helpers --------------------------------------------


def _f3(v: float) -> float:
    """Round to 3 decimals (cm resolution) and kill ``-0.0`` (byte determinism)."""
    return round(float(v), 3) + 0.0


def _digest(*parts: Any) -> int:
    """sha256 of the parts joined by ``'|'`` -> int from the first 16 hex chars.

    Mirrors ``ldyf.city_layout._digest`` so seeds compose the same way.
    """
    text = "|".join(str(p) for p in parts)
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def _unit(dx: float, dy: float) -> tuple[float, float]:
    n = math.hypot(dx, dy)
    if n == 0.0:
        return (0.0, 0.0)
    return (dx / n, dy / n)


def _yaw_of(dx: float, dy: float) -> float:
    return _f3(normalise_deg(math.degrees(math.atan2(dy, dx))))


def _len2(a: dict, b: dict) -> float:
    return math.hypot(b["x"] - a["x"], b["y"] - a["y"])


def _polyline_len(pts: Sequence[dict]) -> float:
    return sum(_len2(a, b) for a, b in zip(pts, pts[1:]))


def _mid(pts: Sequence[dict]) -> tuple[float, float]:
    return ((pts[0]["x"] + pts[-1]["x"]) / 2.0,
            (pts[0]["y"] + pts[-1]["y"]) / 2.0)


def _point_on(pts: Sequence[dict], s: float) -> dict:
    """Point at arc length ``s`` along a polyline (2D x/y, clamped at ends)."""
    travelled = 0.0
    for a, b in zip(pts, pts[1:]):
        seg = _len2(a, b)
        if seg <= 0.0:
            continue
        if travelled + seg >= s:
            f = max(0.0, min(1.0, (s - travelled) / seg))
            return {"x": _f3(a["x"] + (b["x"] - a["x"]) * f),
                    "y": _f3(a["y"] + (b["y"] - a["y"]) * f)}
        travelled += seg
    last = pts[-1]
    return {"x": _f3(last["x"]), "y": _f3(last["y"])}


def _dist_pt_seg(px: float, py: float, ax: float, ay: float,
                 bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 <= 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / l2
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _poly_area(poly: Sequence[dict]) -> float:
    area = 0.0
    for a, b in zip(poly, list(poly[1:]) + list(poly[:1])):
        area += a["x"] * b["y"] - b["x"] * a["y"]
    return abs(area) / 2.0


def _poly_centroid(poly: Sequence[dict]) -> tuple[float, float]:
    cx = sum(p["x"] for p in poly) / len(poly)
    cy = sum(p["y"] for p in poly) / len(poly)
    return (cx, cy)


def _point_in_poly(px: float, py: float, poly: Sequence[dict]) -> bool:
    """Even-odd ray cast; works for clockwise and counter-clockwise polygons."""
    inside = False
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if (a["y"] > py) != (b["y"] > py):
            x_at = a["x"] + (py - a["y"]) * (b["x"] - a["x"]) \
                / (b["y"] - a["y"])
            if x_at > px:
                inside = not inside
    return inside


def _edge_clearance(px: float, py: float, poly: Sequence[dict]) -> float:
    """Distance from (px, py) to the nearest polygon edge (cm)."""
    best = float("inf")
    for a, b in zip(poly, list(poly[1:]) + list(poly[:1])):
        d = _dist_pt_seg(px, py, a["x"], a["y"], b["x"], b["y"])
        if d < best:
            best = d
    return best


def _slots_of(doc: Any) -> list[dict]:
    """Accept a ``{..., "slots": [...]}`` doc or a bare list of slot dicts."""
    if doc is None:
        return []
    if isinstance(doc, dict) and "slots" in doc:
        return list(doc["slots"])
    return list(doc)


def _id_of(item: dict, fallback: str) -> str:
    return str(item.get("id", fallback))


# --- footprints and the shared conflict guard --------------------------------


def _item_size(item: dict) -> tuple[float, float]:
    """(width_cm across yaw, depth_cm along yaw) of an item's footprint.

    ``length_cm`` (parked cars) is the extent along the facing direction and is
    therefore treated as depth.  Items that declare no footprint fall back to a
    small disc handled by ``conflicts`` directly.
    """
    w = item.get("width_cm")
    d = item.get("depth_cm")
    if d is None:
        d = item.get("length_cm")
    if w is None or d is None:
        return (0.0, 0.0)
    return (float(w), float(d))


def _rect_corners(x: float, y: float, yaw: float,
                  width: float, depth: float,
                  offset_along: float = 0.0) -> list[tuple[float, float]]:
    """Rectangle corners around (x, y) in CYCLIC order, with the rectangle
    pushed ``offset_along`` cm along the facing direction (used for projecting
    signs, whose mass hangs in front of the wall).

    The winding matters and is not cosmetic. Both ``_rect_rect_overlap`` and
    ``_rect_disc_overlap`` walk consecutive corners as EDGES. Emitting the four
    corners in nested-loop order gives (-w,-d), (-w,+d), (+w,-d), (+w,+d),
    whose "edges" include a diagonal, so the separating-axis test projects onto
    a wrong axis and finds an overlap between rectangles that are plainly
    apart -- two 100 cm squares 50 cm from each other were reported as
    conflicting. Corners are therefore emitted as a proper cycle.
    """
    r = math.radians(yaw)
    ux, uy = math.cos(r), math.sin(r)
    px, py = -uy, ux
    cx = x + ux * offset_along
    cy = y + uy * offset_along
    hw, hd = width / 2.0, depth / 2.0
    corners = []
    for sa, sd in ((-1.0, -1.0), (-1.0, 1.0), (1.0, 1.0), (1.0, -1.0)):
        corners.append((cx + ux * (sd * hd) + px * (sa * hw),
                        cy + uy * (sd * hd) + py * (sa * hw)))
    return corners


def _rect_rect_overlap(a: Sequence[tuple[float, float]],
                       b: Sequence[tuple[float, float]]) -> bool:
    """Separating-axis test for two convex polygons (here rectangles)."""
    for poly in (a, b):
        for i in range(4):
            ax0, ay0 = poly[i]
            ax1, ay1 = poly[(i + 1) % 4]
            nx, ny = ay0 - ay1, ax1 - ax0  # edge normal
            len_n = math.hypot(nx, ny)
            if len_n <= 0.0:
                continue
            nx, ny = nx / len_n, ny / len_n
            pa = [p[0] * nx + p[1] * ny for p in a]
            pb = [p[0] * nx + p[1] * ny for p in b]
            if max(pa) < min(pb) or max(pb) < min(pa):
                return False
    return True


def _rect_disc_overlap(corners: Sequence[tuple[float, float]],
                       cx: float, cy: float, radius: float) -> bool:
    """Rect (convex polygon) vs disc: true if the disc centre is within
    ``radius`` of the rectangle's closest point."""
    best = float("inf")
    n = len(corners)
    for i in range(n):
        ax, ay = corners[i]
        bx, by = corners[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        if l2 <= 0.0:
            d = math.hypot(cx - ax, cy - ay)
        else:
            t = ((cx - ax) * dx + (cy - ay) * dy) / l2
            t = max(0.0, min(1.0, t))
            d = math.hypot(cx - (ax + t * dx), cy - (ay + t * dy))
        if d < best:
            best = d
    return best <= radius


def conflicts(*collections: Any, footprint_radius_cm: float = 45.0) -> list[dict]:
    """Every pair of placed items whose footprints overlap.

    Each argument is a labelled or bare collection of items:

    * ``(label, items)`` -- a named collection;
    * a dict with a ``"slots"`` key (a ``city_layout``-style document) -- the
      items are ``doc["slots"]`` and the label is ``doc["schema_version"]``;
    * a bare iterable -- label ``"items"``.

    A footprint is an oriented rectangle when the item carries ``width_cm`` and
    ``depth_cm`` (``length_cm`` counts as depth); otherwise the item is a disc
    of ``footprint_radius_cm``.  Pairs are reported, never silently dropped:
    each result is ``{"collection_a", "id_a", "collection_b", "id_b"}`` with
    ids from the items (positional ``<label>[i]`` when an item has no ``id``).
    Results are sorted by the four keys so the report is deterministic.
    """
    labelled: list[tuple[str, list[dict]]] = []
    for col in collections:
        if (isinstance(col, tuple) and len(col) == 2
                and isinstance(col[0], str)):
            label, items = col
            items = _slots_of(items)
            if not label:
                label = "items"
        elif isinstance(col, dict) and "slots" in col:
            label = str(col.get("schema_version") or "existing")
            items = _slots_of(col)
        else:
            label = "items"
            items = _slots_of(col)
        if items:
            labelled.append((label, items))

    expanded: list[tuple[str, str, dict]] = []  # (label, id, item)
    for label, items in labelled:
        for i, item in enumerate(items):
            expanded.append((label, _id_of(item, "%s[%d]" % (label, i)), item))

    pairs: list[dict] = []
    for i in range(len(expanded)):
        la, ia, a = expanded[i]
        for j in range(i + 1, len(expanded)):
            lb, ib, b = expanded[j]
            if _items_overlap(a, b, footprint_radius_cm=footprint_radius_cm):
                pairs.append({"collection_a": la, "id_a": ia,
                              "collection_b": lb, "id_b": ib})
    pairs.sort(key=lambda p: (p["collection_a"], p["id_a"],
                              p["collection_b"], p["id_b"]))
    return pairs


def _items_overlap(a: dict, b: dict, *, footprint_radius_cm: float) -> bool:
    wa, da = _item_size(a)
    wb, db = _item_size(b)
    ax, ay = float(a.get("x", 0.0)), float(a.get("y", 0.0))
    bx, by = float(b.get("x", 0.0)), float(b.get("y", 0.0))
    yawa = float(a.get("yaw_deg", a.get("yaw", 0.0)))
    yawb = float(b.get("yaw_deg", b.get("yaw", 0.0)))
    if wa > 0.0 and da > 0.0 and wb > 0.0 and db > 0.0:
        oa = float(a.get("offset_along_cm", a.get("projection_cm", 0.0)) / 2.0)
        ob = float(b.get("offset_along_cm", b.get("projection_cm", 0.0)) / 2.0)
        ca = _rect_corners(ax, ay, yawa, wa, da, offset_along=oa)
        cb = _rect_corners(bx, by, yawb, wb, db, offset_along=ob)
        return _rect_rect_overlap(ca, cb)
    if wa > 0.0 and da > 0.0:
        oa = float(a.get("offset_along_cm", a.get("projection_cm", 0.0)) / 2.0)
        ca = _rect_corners(ax, ay, yawa, wa, da, offset_along=oa)
        return _rect_disc_overlap(ca, bx, by, footprint_radius_cm)
    if wb > 0.0 and db > 0.0:
        ob = float(b.get("offset_along_cm", b.get("projection_cm", 0.0)) / 2.0)
        cb = _rect_corners(bx, by, yawb, wb, db, offset_along=ob)
        return _rect_disc_overlap(cb, ax, ay, footprint_radius_cm)
    return math.hypot(ax - bx, ay - by) <= 2.0 * footprint_radius_cm


# --- frontages that face a footway ------------------------------------------
#
# A block of ``city_layout`` is bounded by roads on every side and
# ``building_slots`` exist only on the block edges that face a road; the footway
# is the band between that facade line and the carriageway kerb that the layout
# already reserved by insetting the block (``blocks`` inset every side by
# ``margin_cm`` + the road lane band) and by pulling facade slots back to the
# setback from the nearest lane polyline (``frontages``).  A building slot is
# therefore on a footway-facing frontage by construction.  We still *verify*
# geometry per slot (the slot point must lie on a block edge whose outward
# normal matches the slot's own outward yaw) rather than trusting the slot.


def _block_edges(blk: dict) -> list[dict]:
    """Per block polygon edge: a, b, length, unit tangent and the OUTWARD unit
    normal -- the perpendicular that points away from the block centre (the
    street side), mirroring ``city_layout.frontages``."""
    poly = blk["polygon"]
    centre = blk.get("centre") or {}
    cx = centre.get("x")
    cy = centre.get("y")
    if cx is None or cy is None:
        cx, cy = _poly_centroid(poly)
    out = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        seg = _len2(a, b)
        if seg <= 1e-9:
            continue
        ux, uy = (b["x"] - a["x"]) / seg, (b["y"] - a["y"]) / seg
        px, py = -uy, ux
        # outward = away from the block centre; dot(perp, centre - mid) <= 0
        mx, my = (a["x"] + b["x"]) / 2.0, (a["y"] + b["y"]) / 2.0
        if px * (cx - mx) + py * (cy - my) > 0.0:
            px, py = -px, -py
        out.append({"a": a, "b": b, "length_cm": seg,
                    "ux": ux, "uy": uy, "nx": px, "ny": py})
    return out


def _match_frontage(slot: dict, edges: Sequence[dict]) -> dict | None:
    """The block edge this building slot faces, or None.

    A slot point may have been pulled inside the block by the layout's setback
    rule; we take the edge with the smallest point-to-segment distance and
    require that its outward normal agrees with the slot's outward yaw, so a
    slot never gets glued to the wrong (side) edge of its block.
    """
    sx, sy = float(slot["x"]), float(slot["y"])
    syaw = math.radians(float(slot.get("yaw", 0.0)))
    svx, svy = math.cos(syaw), math.sin(syaw)
    best = None
    best_d = float("inf")
    for ed in edges:
        d = _dist_pt_seg(sx, sy, ed["a"]["x"], ed["a"]["y"],
                         ed["b"]["x"], ed["b"]["y"])
        if d < best_d:
            best_d = d
            best = ed
    if best is None or best_d > 1500.0:
        return None
    if svx * best["nx"] + svy * best["ny"] < 0.3:
        return None  # slot yaw disagrees with this edge's outward normal
    return best


def _param_along(slot: dict, ed: dict) -> float:
    """Arc parameter of the slot point's projection onto the frontage edge."""
    sx, sy = float(slot["x"]), float(slot["y"])
    a, b = ed["a"], ed["b"]
    seg = ed["length_cm"]
    if seg <= 0.0:
        return 0.0
    t = ((sx - a["x"]) * (b["x"] - a["x"])
         + (sy - a["y"]) * (b["y"] - a["y"])) / (seg * seg)
    return max(0.0, min(seg, t * seg))


# --- 1. storefronts ---------------------------------------------------------


def storefront_slots(layout: dict, *, spacing_cm: float = DEFAULT_STOREFRONT_SPACING_CM,
                     setback_cm: float = DEFAULT_STOREFRONT_SETBACK_CM,
                     seed: int = 0) -> list[dict]:
    """Positions along building frontages that face a footway.

    A storefront is placed on a ``building_slot`` whose block edge it provably
    faces (see ``_match_frontage``); consecutive storefronts along the same
    block edge are kept at least ``spacing_cm`` apart and every storefront
    stays ``setback_cm`` away from both corners of its frontage segment, so no
    shopfront crowds a street corner.

    Outward facing: the returned ``yaw_deg`` is NOT copied from the slot.  It
    is re-derived from the frontage segment's unit normal, and the outward side
    is the perpendicular that points away from the block centre
    (``dot(perp, centre - midpoint) <= 0``): the block interior is the building,
    so the street -- and the footway in front of it -- is the side the normal
    points away from.  A sign facing into the building is worse than no sign,
    so any frontage whose normal does not agree with the slot's own yaw within
    ~72 degrees is rejected instead of being placed facing the wrong way.

    Each entry: ``{"id", "x", "y", "yaw_deg", "kind", "width_cm", "block_id"}``
    plus ``footway_cm`` (facade-to-kerb estimate used to clamp projecting
    signs; defaults to ``DEFAULT_FOOTWAY_CM`` because the layout document does
    not carry kerb geometry -- layout-level margin data is not a footway).
    """
    if spacing_cm <= 0:
        raise ValueError("spacing_cm must be positive, got %r" % (spacing_cm,))
    if setback_cm < 0:
        raise ValueError("setback_cm must be >= 0, got %r" % (setback_cm,))
    blocks_by_id = {b["id"]: b for b in layout.get("blocks", [])}
    out: list[dict] = []
    # per (block_id, edge_index) -> last accepted point on that frontage
    last_on_edge: dict[tuple[str, int], tuple[float, float]] = {}
    for slot in sorted(_slots_of(layout.get("building_slots")),
                       key=lambda s: str(s.get("slot_id", s.get("id")))):
        blk = blocks_by_id.get(str(slot.get("block_id")))
        if blk is None:
            continue
        edges = _block_edges(blk)
        ed = _match_frontage(slot, edges)
        if ed is None:
            continue
        edge_index = next(i for i, e in enumerate(edges) if e is ed)
        t = _param_along(slot, ed)
        if t < setback_cm or ed["length_cm"] - t < setback_cm:
            continue  # too close to a block corner / junction return
        key = (str(slot.get("block_id")), edge_index)
        prev = last_on_edge.get(key)
        sx, sy = float(slot["x"]), float(slot["y"])
        if prev is not None and math.hypot(sx - prev[0], sy - prev[1]) < spacing_cm:
            continue
        last_on_edge[key] = (sx, sy)
        sid = str(slot.get("slot_id", slot.get("id")))
        sf_id = "storefront_%s" % sid
        kind = _STOREFRONT_KINDS[
            _digest(sf_id, seed, "storefront_kind") % len(_STOREFRONT_KINDS)]
        slot_w = float(slot.get("width_cm") or spacing_cm)
        if kind == "shopfront":
            width_cm = min(slot_w, 1400.0)
        else:  # entrance: just the door leaf and its frame
            width_cm = min(slot_w, 260.0)
        out.append({
            "id": sf_id,
            "x": _f3(sx), "y": _f3(sy),
            "yaw_deg": _f3(_yaw_of(ed["nx"], ed["ny"])),
            "kind": kind,
            "width_cm": _f3(max(width_cm, 0.0)),
            "block_id": str(slot.get("block_id")),
            "depth_cm": _f3(60.0 if kind == "entrance" else 90.0),
            "footway_cm": _f3(DEFAULT_FOOTWAY_CM),
            "slot_id": sid,
        })
    return sorted(out, key=lambda s: s["id"])


# --- 2. signs ---------------------------------------------------------------


def sign_slots(storefronts: Iterable[dict], *, seed: int = 0,
               sign_share: float = DEFAULT_SIGN_SHARE) -> list[dict]:
    """Projecting and flat signs on a subset of storefronts.

    At most one sign per storefront and only on a ``sign_share`` fraction
    (default 0.35) of storefronts, decided by digest -- restrained by design
    (about 0.6 signs per 100 m of frontage at the default storefront spacing).

    A **projecting** sign sticks out from the wall into the footway.  It must
    not overhang the carriageway, so its ``projection_cm`` is clamped to the
    footway width in front of that storefront::

        projection_cm = min(desired, storefront["footway_cm"])

    with ``footway_cm`` carried by the storefront (facade-to-kerb distance).
    The tip therefore reaches at most the kerb line and never crosses it.  A
    flat sign has ``projection_cm`` 0 (it hugs the wall, cleared by
    ``height_cm`` above the pavement).

    Entry: ``{"id", "storefront_id", "x", "y", "yaw_deg", "kind",
    "width_cm", "height_cm", "projection_cm", "offset_along_cm"}``.  ``x``/``y``
    are the mounting point on the facade; ``offset_along_cm`` (= projection/2)
    lets the shared footprint guard place the sign's mass in front of the wall.
    """
    if not 0.0 <= sign_share <= 1.0:
        raise ValueError("sign_share must be within [0, 1], got %r" % (sign_share,))
    rows: list[dict] = []
    for sf in sorted(_slots_of(storefronts), key=lambda s: str(s.get("id"))):
        sf_id = str(sf.get("id"))
        if _digest(sf_id, seed, "sign") % 10000 >= int(round(sign_share * 10000)):
            continue
        kind = _SIGN_KINDS[_digest(sf_id, seed, "sign_kind") % len(_SIGN_KINDS)]
        if kind == "projecting":
            desired = 120.0 + float(_digest(sf_id, seed, "sign_len") % 6) * 20.0
            footway = float(sf.get("footway_cm", DEFAULT_FOOTWAY_CM))
            projection = min(desired, max(0.0, footway))  # the clamp
        else:
            projection = 0.0
        rows.append({
            "id": "sign_%s" % sf_id,
            "storefront_id": sf_id,
            "x": sf.get("x"), "y": sf.get("y"),
            "yaw_deg": sf.get("yaw_deg", 0.0),
            "kind": kind,
            "width_cm": _f3(80.0 + float(_digest(sf_id, seed, "sign_w") % 4) * 20.0),
            "height_cm": _f3(220.0 + float(_digest(sf_id, seed, "sign_h") % 4) * 40.0),
            "projection_cm": _f3(projection),
            "offset_along_cm": _f3(projection / 2.0),
            "depth_cm": _f3(15.0 + projection),
        })
    return sorted(rows, key=lambda s: str(s.get("id")))


# --- 3. rooftop props -------------------------------------------------------


def rooftop_props(buildings: Any, *, seed: int = 0,
                  margin_cm: float = DEFAULT_ROOFTOP_MARGIN_CM,
                  max_per_roof: int = DEFAULT_ROOFTOP_MAX_PER_ROOF,
                  area_per_prop_cm2: float = DEFAULT_ROOFTOP_AREA_PER_PROP_CM2) -> list[dict]:
    """Vents, AC units, stair housings and antennae on building roofs.

    Every prop must lie **inside** the roof polygon, inset from the parapet
    edge by ``margin_cm``, and must not intersect any other prop on the same
    roof.  Both are enforced geometrically before a prop is accepted:

    * clearance -- the prop centre keeps ``margin_cm + half_diagonal`` from
      every roof edge, so the furthest footprint corner is still at least
      ``margin_cm`` off the parapet (never on the edge);
    * separation -- a candidate prop is only accepted when its centre is
      further than ``ra + rb + gap`` from every already-accepted prop, where
      ``ra``/``rb`` are the circumradii (half diagonals), which guarantees no
      intersection for any orientation.

    ``buildings`` is a list of records, each with ``id`` and ``polygon`` (roof
    outline, list of ``{x, y}`` in cm).  A record without a polygon raises
    ``ValueError`` -- the guarantee cannot be honoured blind.

    Density: at most one prop per ``area_per_prop_cm2`` (default 7,000,000 cm2
    = 700 m2 of roof), capped at ``max_per_roof`` per roof.  A typical 20 m x
    15 m roof (3,000,000 cm2) therefore gets exactly one prop.
    """
    if margin_cm < 0:
        raise ValueError("margin_cm must be >= 0, got %r" % (margin_cm,))
    if area_per_prop_cm2 <= 0:
        raise ValueError("area_per_prop_cm2 must be positive")
    blobs = _slots_of(buildings)
    out: list[dict] = []
    for i, bld in enumerate(blobs):
        poly = bld.get("polygon")
        if poly is None or len(poly) < 3:
            raise ValueError(
                "rooftop_props needs a roof polygon per building; record %s has none"
                % (bld.get("id", i)))
        bid = str(bld.get("id", "building_%d" % i))
        pts = [dict(p) for p in poly]
        area = _poly_area(pts)
        want = min(max_per_roof, 1 + int(area / max(area_per_prop_cm2, 1.0)))
        if want <= 0:
            continue
        xs = [p["x"] for p in pts]
        ys = [p["y"] for p in pts]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        pitch = 240.0
        candidates: list[dict] = []
        gy = y_min + pitch / 2.0
        while gy < y_max:
            gx = x_min + pitch / 2.0
            while gx < x_max:
                candidates.append({"x": gx, "y": gy})
                gx += pitch
            gy += pitch
        # deterministic visit order: digest of the candidate key, so different
        # seeds place props on different roofs without any randomness
        candidates.sort(key=lambda c: _digest(bid, _f3(c["x"]), _f3(c["y"]),
                                              seed, "roof_candidate"))
        accepted: list[dict] = []
        for cand in candidates:
            if len(accepted) >= want:
                break
            ckey = "%s|%s|%s" % (bid, _f3(cand["x"]), _f3(cand["y"]))
            kind = _ROOF_KINDS[_digest(ckey, seed, "roof_kind") % len(_ROOF_KINDS)]
            w, d, h = _ROOF_KIND_SIZE[kind]
            rad = math.hypot(w, d) / 2.0
            if not _point_in_poly(cand["x"], cand["y"], pts):
                continue
            if _edge_clearance(cand["x"], cand["y"], pts) < margin_cm + rad:
                continue  # would put the prop on or over the parapet
            ok = True
            for acc in accepted:
                dx = cand["x"] - acc["x"]
                dy = cand["y"] - acc["y"]
                need = acc["radius_cm"] + rad + 20.0
                if math.hypot(dx, dy) < need:
                    ok = False
                    break
            if not ok:
                continue
            n = len(accepted)
            accepted.append({
                "id": "roof_%s_%d" % (bid, n),
                "building_id": bid,
                "x": _f3(cand["x"]), "y": _f3(cand["y"]),
                "yaw_deg": _f3(float(_digest(ckey, seed, "roof_yaw") % 360)),
                "kind": kind,
                "width_cm": _f3(w), "depth_cm": _f3(d), "height_cm": _f3(h),
                "radius_cm": _f3(rad),
            })
        out.extend(accepted)
    out.sort(key=lambda p: str(p.get("id")))
    for p in out:
        p.pop("radius_cm", None)  # internal only; not part of the schema
    return out


# --- 4. parked cars ---------------------------------------------------------


def _is_car_lane(lane: dict) -> bool:
    """A lane cars drive on: it explicitly disallows pedestrians (dressing.py)."""
    return "pedestrian" in (lane.get("disallow") or [])


def _is_sidewalk_lane(lane: dict) -> bool:
    return "pedestrian" in (lane.get("allow") or [])


def _sidewalk_lanes(edge: dict) -> list[dict]:
    return [l for l in edge.get("lanes", []) if _is_sidewalk_lane(l)]


def _edge_crosswalk_bands(spec: dict, lane_pts: Sequence[dict]) -> list[tuple[float, float]]:
    """Bands of along-lane parameter ``t`` (cm) a parked car must keep clear of,
    because a crosswalk crosses the carriageway there.

    The crossing's lane polyline spans the carriageway (perpendicular to
    travel); its own width (``width_cm_effective``) is the crossing's depth
    along the direction cars travel.  Each crossing contributes
    ``[t_min - w/2 - clear - car_len/2, t_max + w/2 + clear + car_len/2]`` in
    the along-lane parameter of the parking lane, where ``t_min``/``t_max`` are
    the projections of the crossing polyline's points onto the lane direction
    and ``car_len/2`` accounts for the parked car's own half length.
    """
    if len(lane_pts) < 2:
        return []
    p0 = lane_pts[0]
    seg = _polyline_len(lane_pts)
    if seg <= 1e-9:
        return []
    ux, uy = (lane_pts[-1]["x"] - p0["x"]) / seg, (lane_pts[-1]["y"] - p0["y"]) / seg
    bands: list[tuple[float, float]] = []
    for e in spec.get("edges", []):
        if e.get("function") != "crossing":
            continue
        lanes = e.get("lanes") or [{}]
        pts = lanes[0].get("polyline") or []
        if len(pts) < 2:
            continue
        w = lanes[0].get("width_cm_effective")
        if w is None:
            w = lanes[0].get("width_cm")
        depth = float(w) if w else 400.0
        ts = [(p["x"] - p0["x"]) * ux + (p["y"] - p0["y"]) * uy for p in pts]
        half = depth / 2.0 + DEFAULT_CROSSWALK_CLEAR_CM + DEFAULT_CAR_LENGTH_CM / 2.0
        bands.append((min(ts) - half, max(ts) + half))
    return bands


def _parking_lane(edge: dict) -> dict | None:
    """The car lane whose outer edge is the kerb: the car lane whose midpoint
    is closest to the sidewalk lanes' midpoint (measured by distance, so the
    lane adjacent to the pavement wins regardless of lane indexing)."""
    cars = [l for l in edge.get("lanes", [])
            if l.get("polyline") and _is_car_lane(l)]
    walks = [l for l in edge.get("lanes", [])
             if l.get("polyline") and _is_sidewalk_lane(l)]
    if not cars or not walks:
        return None
    wx = sum(_mid(ln["polyline"])[0] for ln in walks) / len(walks)
    wy = sum(_mid(ln["polyline"])[1] for ln in walks) / len(walks)
    best = None
    best_d = float("inf")
    for ln in cars:
        mx, my = _mid(ln["polyline"])
        d = math.hypot(wx - mx, wy - my)
        if d < best_d:
            best, best_d = ln, d
    return best


def _lateral_side(edge: dict, kerb_lane: dict) -> tuple[float, float]:
    """Unit normal from the carriageway toward the sidewalk for ``edge``."""
    mx, my = _mid(kerb_lane["polyline"])
    walks = _sidewalk_lanes(edge)
    wx = sum(_mid(ln["polyline"])[0] for ln in walks) / len(walks)
    wy = sum(_mid(ln["polyline"])[1] for ln in walks) / len(walks)
    return _unit(wx - mx, wy - my)


def parked_cars(layout: dict, *, occupancy: float = DEFAULT_OCCUPANCY,
                seed: int = 0,
                car_length_cm: float = DEFAULT_CAR_LENGTH_CM,
                car_width_cm: float = DEFAULT_CAR_WIDTH_CM,
                bumper_gap_cm: float = DEFAULT_CAR_BUMPER_GAP_CM,
                junction_clear_cm: float = DEFAULT_JUNCTION_CLEAR_CM) -> list[dict]:
    """Vehicles parked at the kerb, aligned with the lane direction.

    A parked car belongs exactly at the kerbside -- the one deliberate
    exception to "nothing where vehicles drive".  For every normal edge that
    carries at least one car lane and one sidewalk lane:

    * the kerb is the outer boundary of the car lane nearest the sidewalk, and
      the car sits inside the carriageway beside that kerb, its kerb-side edge
      ``DEFAULT_CAR_KERB_GAP_CM`` off the kerb line (never on the pavement);
    * the car's long axis follows the lane direction (its ``yaw_deg`` is the
      lane polyline's travel direction);
    * candidates are removed when they fall inside a junction (within
      ``junction_clear_cm`` of either lane end), across a crosswalk (any
      along-lane overlap with the crossing bands of ``_edge_crosswalk_bands``)
      or on an edge the closure zone has sealed (``layout["closed_edge_ids"]``
      -- a closed street is a worksite, not a car park);
    * candidates are pitched ``car_length_cm + bumper_gap_cm`` apart, which
      enforces the minimum bumper-to-bumper gap and therefore no overlap;
    * ``occupancy`` in [0, 1] selects a deterministic, evenly spread subset of
      the legal run: for a run holding ``n`` cars it keeps ``round(occupancy*n)``
      cars at indices ``i*n//k`` (deterministic, no randomness).

    Requires ``layout["spec"]`` (the road spec the layout was derived from) to
    read kerb, lane-direction and crosswalk geometry; without it the kerb is
    unknowable and nothing is placed (documented -- no cars invented in the
    dark).  Entries: ``{"id", "x", "y", "yaw_deg", "length_cm", "variant",
    "edge_id"}`` plus ``width_cm``/``depth_cm`` (= length) for the footprint
    guard.
    """
    if not 0.0 <= occupancy <= 1.0:
        raise ValueError("occupancy must be within [0, 1], got %r" % (occupancy,))
    spec = layout.get("spec")
    if not spec:
        return []  # kerb geometry unknowable; parking omitted, documented
    closed = {str(e) for e in (layout.get("closed_edge_ids") or ())}
    out: list[dict] = []
    edges = sorted((e for e in spec.get("edges", [])
                    if e.get("function") in (None, "normal")),
                   key=lambda e: str(e["id"]))
    for edge in edges:
        eid = str(edge["id"])
        if eid in closed:
            continue  # inside the closure zone
        kerb_lane = _parking_lane(edge)
        if kerb_lane is None:
            continue
        pts = kerb_lane["polyline"]
        if len(pts) < 2:
            continue
        w = kerb_lane.get("width_cm_effective")
        if w is None:
            w = kerb_lane.get("width_cm")
        if not w:
            continue
        # the car plus its two kerb margins must fit inside the lane width
        if float(w) < car_width_cm + 2.0 * DEFAULT_CAR_KERB_GAP_CM + 40.0:
            continue
        total = _polyline_len(pts)
        if total <= 2.0 * junction_clear_cm + car_length_cm:
            continue
        nkx, nky = _lateral_side(edge, kerb_lane)
        # car centre lateral offset from the lane centreline: kerb at w/2 along
        # nk, car pulled back into the carriageway by width/2 + kerb gap
        lat = w / 2.0 - (car_width_cm / 2.0 + DEFAULT_CAR_KERB_GAP_CM)
        bands = _edge_crosswalk_bands(spec, pts)
        run_start = junction_clear_cm
        run_end = total - junction_clear_cm
        step = car_length_cm + bumper_gap_cm
        ts: list[float] = []
        t = run_start
        while t <= run_end - 1e-6:
            if not any(lo - 1e-6 <= t <= hi + 1e-6 for (lo, hi) in bands):
                ts.append(t)
            t += step
        n = len(ts)
        k = int(round(occupancy * n))
        if k > n:
            k = n
        chosen_idx = [(i * n) // k for i in range(k)] if k else []
        ux, uy = _unit(pts[-1]["x"] - pts[0]["x"], pts[-1]["y"] - pts[0]["y"])
        for idx in chosen_idx:
            t = ts[idx]
            pt = _point_on(pts, t)
            cx = _f3(pt["x"] + nkx * lat)
            cy = _f3(pt["y"] + nky * lat)
            out.append({
                "id": "parked_%s_%d" % (eid, idx),
                "x": cx, "y": cy,
                "yaw_deg": _f3(_yaw_of(ux, uy)),
                "length_cm": _f3(car_length_cm),
                "width_cm": _f3(car_width_cm),
                "depth_cm": _f3(car_length_cm),
                "variant": _CAR_VARIANTS[_digest(eid, _f3(t), seed, "car_variant")
                                         % len(_CAR_VARIANTS)],
                "edge_id": eid,
            })
    return sorted(out, key=lambda c: str(c.get("id")))


# --- 6. the assembled document ---------------------------------------------


def build_street_life(layout: dict, buildings: Any = None,
                      existing: Any = None, *,
                      seed: int = 0,
                      storefront_spacing_cm: float = DEFAULT_STOREFRONT_SPACING_CM,
                      storefront_setback_cm: float = DEFAULT_STOREFRONT_SETBACK_CM,
                      sign_share: float = DEFAULT_SIGN_SHARE,
                      rooftop_margin_cm: float = DEFAULT_ROOFTOP_MARGIN_CM,
                      rooftop_max_per_roof: int = DEFAULT_ROOFTOP_MAX_PER_ROOF,
                      parked_occupancy: float = DEFAULT_OCCUPANCY,
                      closed_edge_ids: Iterable[str] = ()) -> dict:
    """The whole ``street_life_v1`` document.

    ``layout`` is the ``city_layout_v1`` doc (``parked_cars`` additionally
    reads ``layout["spec"]``), ``buildings`` is the roof-polygon record list
    for ``rooftop_props`` (None -> no rooftop props), and ``existing`` is a
    furniture/tree collection (a ``{"slots": [...]}`` doc, a bare list, or a
    ``{label: collection}`` dict) that ``conflicts`` checks the new items
    against.  ``closed_edge_ids`` is forwarded into the layout copy used by
    ``parked_cars`` so sealed streets never receive parked cars.
    """
    if closed_edge_ids:
        layout = dict(layout)
        layout["closed_edge_ids"] = sorted({str(e) for e in closed_edge_ids})
    storefronts = storefront_slots(layout, spacing_cm=storefront_spacing_cm,
                                   setback_cm=storefront_setback_cm, seed=seed)
    signs = sign_slots(storefronts, seed=seed, sign_share=sign_share)
    roofs = ([] if buildings is None
             else rooftop_props(buildings, seed=seed,
                                margin_cm=rooftop_margin_cm,
                                max_per_roof=rooftop_max_per_roof))
    cars = parked_cars(layout, occupancy=parked_occupancy, seed=seed)

    labelled: list[Any] = [("storefronts", storefronts),
                           ("signs", signs),
                           ("rooftop_props", roofs),
                           ("parked_cars", cars)]
    if isinstance(existing, dict):
        # {"furniture": doc, "trees": doc} or a bare doc {"slots": [...]}
        if "slots" in existing and set(existing.keys()) <= {"slots",
                                                           "schema_version",
                                                           "counts"}:
            labelled.append(("existing", existing["slots"]))
        else:
            for label in sorted(existing):
                labelled.append((str(label), existing[label]))
    elif existing is not None:
        labelled.append(("existing", _slots_of(existing)))
    conflict_rows = conflicts(*labelled)

    return {
        "schema_version": STREET_LIFE_VERSION,
        "params": {
            "seed": int(seed),
            "storefront_spacing_cm": _f3(storefront_spacing_cm),
            "storefront_setback_cm": _f3(storefront_setback_cm),
            "sign_share": _f3(sign_share),
            "rooftop_margin_cm": _f3(rooftop_margin_cm),
            "rooftop_max_per_roof": int(rooftop_max_per_roof),
            "parked_occupancy": _f3(parked_occupancy),
            "closed_edge_ids": sorted({str(e) for e in closed_edge_ids}),
        },
        "storefronts": storefronts,
        "signs": signs,
        "rooftop_props": roofs,
        "parked_cars": cars,
        "counts": {
            "storefronts": len(storefronts),
            "signs": len(signs),
            "rooftop_props": len(roofs),
            "parked_cars": len(cars),
            "conflict_pairs": len(conflict_rows),
        },
        "conflicts": conflict_rows,
    }
