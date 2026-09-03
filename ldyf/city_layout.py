"""Closure lane B -- ``city_layout_v1``: building lots and street furniture
slots derived deterministically from a ``road_spec_v1`` (see ``ldyf.roads``).

What this module does
---------------------
Given a road spec whose coordinates are Unreal centimetres (X east, Y south,
Z up) it produces, with pure Python (stdlib) only:

* ``road_corridor_polygons`` - per normal edge, the rectangle swept by the
  lane union band, expanded by ``margin_cm`` on every side.
* ``blocks`` - the closed areas bounded by roads.  Junction positions form a
  lattice; junction x's and y's are clustered with a tolerance argument, and a
  block is the quad between four neighbouring occupied lattice points, inset
  on each side by ``margin_cm`` plus the extent of that side's road lane band
  measured into the cell.  The lattice is *inferred*, never hardcoded to 4x4.
* ``frontages`` - facade positions along the block edges that face roads.
  ``yaw`` is the outward edge normal in Unreal degrees computed with
  ``math.atan2`` only (no 90-degree additions, no axis negation - the polygon
  is already in Unreal space).  A facade whose boundary point is closer than
  ``setback_cm`` to the nearest lane polyline is pulled back into the block
  until it clears the setback.
* ``building_slots`` - per block, walk the frontages and emit one slot per
  facade.  Kit rule (documented in ``building_slots``): block kit =
  ``digest(block_id, seed) % len(kits)``; per slot 70% dominant kit, 30%
  another kit, chosen by sha256 digests of ``(slot_id, seed)``.  A block keeps
  a dominant kit: if the dominant share would fall below 60% of the block's
  slots, the lowest-id non-dominant slots are flipped to the dominant kit
  until the 60% floor holds.
* ``furniture_slots`` - points along each normal lane's *outer* edge (offset
  defaults to half the lane's ``width_cm_effective`` + 150 cm), kinds
  alternating deterministically by global index, ``yaw`` facing the road
  centre.
* ``crossing_slots`` - centres of crossing edges (``function == "crossing"``)
  with yaw along the edge, for crosswalk decals.

Determinism laws (mirroring ``ldyf.roads``): every float is rounded to 3
decimals (``_f3``, which also kills ``-0.0``), iteration is over ids sorted
lexicographically, digests are sha256 of exact documented strings, and JSON is
written with ``json.dumps(..., indent=2, sort_keys=True)``.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .coords import normalise_deg

CITY_LAYOUT_VERSION = "city_layout_v1"

# Kit rule constants (documented rule, not per-call tunables).
_KIT_DOMINANT_PERCENT = 70.0   # per-slot chance of the block (dominant) kit
_BLOCK_DOMINANT_FLOOR = 0.60   # minimum dominant-kit share inside one block


# --- small deterministic helpers -------------------------------------------


def _f3(v: float) -> float:
    """Round to 3 decimals (cm resolution) and kill ``-0.0`` (byte determinism)."""
    return round(float(v), 3) + 0.0


def _digest(*parts: Any) -> int:
    """sha256 of the parts joined by ``'|'`` -> int from the first 16 hex chars."""
    text = "|".join(str(p) for p in parts)
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def _len2(a: dict, b: dict) -> float:
    return math.hypot(b["x"] - a["x"], b["y"] - a["y"])


def _polyline_len(points: list[dict]) -> float:
    return sum(_len2(a, b) for a, b in zip(points, points[1:]))


def _point_on(points: list[dict], s: float) -> dict:
    """Point at arc length ``s`` along a polyline (2D x/y)."""
    travelled = 0.0
    for a, b in zip(points, points[1:]):
        seg = _len2(a, b)
        if seg <= 0.0:
            continue
        if travelled + seg >= s:
            f = (s - travelled) / seg
            return {"x": _f3(a["x"] + (b["x"] - a["x"]) * f),
                    "y": _f3(a["y"] + (b["y"] - a["y"]) * f)}
        travelled += seg
    last = points[-1]
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
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def nearest_lane_distance_cm(spec: dict, x: float, y: float) -> float:
    """Distance from (x, y) to the nearest lane *polyline* (centre line) of any
    edge in the spec, 2D cm.  Lets frontages honour setbacks and lets tests
    prove slot clearance against the roads."""
    best = float("inf")
    for e in spec.get("edges", []):
        for ln in e.get("lanes", []):
            pts = ln.get("polyline") or []
            for a, b in zip(pts, pts[1:]):
                d = _dist_pt_seg(x, y, a["x"], a["y"], b["x"], b["y"])
                if d < best:
                    best = d
    return best


def _cluster_reps(values: list[float], tol: float) -> list[float]:
    """Sorted 1-D cluster representatives: a value within ``tol`` of the
    cluster's lowest member joins that cluster (lattice inference)."""
    reps: list[float] = []
    for v in sorted(values):
        if reps and v - reps[-1] <= tol:
            continue
        reps.append(v)
    return reps


# --- road corridors --------------------------------------------------------


def _edge_union_band(edge: dict) -> tuple[float, float] | None:
    """(lo, hi) of a normal edge's lane union band in the edge's own frame,
    measured from the first point of the first lane along the perpendicular."""
    lanes = [l for l in edge.get("lanes", []) if l.get("polyline")]
    if not lanes:
        return None
    ref = lanes[0]["polyline"]
    if len(ref) < 2:
        return None
    p0, p1 = ref[0], ref[-1]
    seg = _len2(p0, p1)
    if seg <= 0.0:
        return None
    ux, uy = (p1["x"] - p0["x"]) / seg, (p1["y"] - p0["y"]) / seg
    nx, ny = -uy, ux
    lo, hi = float("inf"), float("-inf")
    for ln in lanes:
        w = ln.get("width_cm_effective")
        if w is None:
            w = ln.get("width_cm")
        if w is None:
            continue
        half = w / 2.0
        for p in ln["polyline"]:
            o = (p["x"] - p0["x"]) * nx + (p["y"] - p0["y"]) * ny
            lo = min(lo, o - half)
            hi = max(hi, o + half)
    if lo == float("inf"):
        return None
    return (lo, hi)


def _edge_corridor_polygon(edge: dict, margin_cm: float) -> list[dict] | None:
    """Rectangle covering one normal edge's lane union band expanded by
    ``margin_cm`` on all four sides; corners in travel-frame order."""
    lanes = [l for l in edge.get("lanes", []) if l.get("polyline")]
    if not lanes:
        return None
    band = _edge_union_band(edge)
    if band is None:
        return None
    lo, hi = band
    ref = lanes[0]["polyline"]
    p0, p1 = ref[0], ref[-1]
    seg = _len2(p0, p1)
    if seg <= 0.0:
        return None
    ux, uy = (p1["x"] - p0["x"]) / seg, (p1["y"] - p0["y"]) / seg
    nx, ny = -uy, ux
    tmin, tmax = float("inf"), float("-inf")
    for ln in lanes:
        for p in ln["polyline"]:
            t = (p["x"] - p0["x"]) * ux + (p["y"] - p0["y"]) * uy
            tmin = min(tmin, t)
            tmax = max(tmax, t)
    tmin -= margin_cm
    tmax += margin_cm
    lo -= margin_cm
    hi += margin_cm

    def pt(t: float, o: float) -> dict:
        return {"x": _f3(p0["x"] + ux * t + nx * o),
                "y": _f3(p0["y"] + uy * t + ny * o)}

    return [pt(tmin, lo), pt(tmax, lo), pt(tmax, hi), pt(tmin, hi)]


def road_corridor_polygons(spec: dict, *, margin_cm: float) -> list[list[dict]]:
    """Per *normal* edge, the rectangle swept by its lanes (union width)
    expanded by ``margin_cm``.  Crossing/internal edges are excluded."""
    out: list[list[dict]] = []
    for e in sorted(spec.get("edges", []), key=lambda e: e["id"]):
        if e.get("function") not in (None, "normal"):
            continue
        poly = _edge_corridor_polygon(e, margin_cm)
        if poly is not None:
            out.append(poly)
    return out


# --- blocks -----------------------------------------------------------------


def _lattice_index(value: float, reps: list[float], tol: float) -> int | None:
    for i, r in enumerate(reps):
        if abs(value - r) <= tol:
            return i
    return None


def _side_band_into_cell(spec: dict, jid_a: str, jid_b: str,
                         ax: float, ay: float,
                         n_in: tuple[float, float]) -> float:
    """Farthest lane-union extent into the cell from the side line through the
    two junction corners, over the normal edges joining them (cm)."""
    best = 0.0
    pair = {jid_a, jid_b}
    for e in spec.get("edges", []):
        if e.get("function") not in (None, "normal"):
            continue
        if {e.get("from_junction"), e.get("to_junction")} != pair:
            continue
        for ln in e.get("lanes", []):
            w = ln.get("width_cm_effective")
            if w is None:
                w = ln.get("width_cm")
            if w is None:
                continue
            half = w / 2.0
            for p in ln.get("polyline", []):
                d = (p["x"] - ax) * n_in[0] + (p["y"] - ay) * n_in[1]
                best = max(best, d + half)
    return max(0.0, best)


def blocks(spec: dict, *, margin_cm: float = 1200.0,
           cluster_tol_cm: float = 1.0) -> list[dict]:
    """Closed areas bounded by roads, derived from the junction lattice.

    Junction x's and y's are clustered with tolerance ``cluster_tol_cm``
    (inferred - never a hardcoded lattice size).  A block is the quad between
    four neighbouring lattice points that each carry a junction, inset toward
    its centre on every side by ``margin_cm`` plus the extent of that side's
    road lane band measured into the cell (so block edges sit clear of the
    margin-expanded corridors).  Each block dict carries ``id``, ``polygon``
    (list of ``{x, y}``), ``centre``, ``area_cm2`` and ``bbox``.
    """
    junctions = [j for j in spec.get("junctions", [])
                 if j.get("position") is not None]
    xs = _cluster_reps([j["position"]["x"] for j in junctions], cluster_tol_cm)
    ys = _cluster_reps([j["position"]["y"] for j in junctions], cluster_tol_cm)
    if not xs or not ys:
        return []

    occ: dict[tuple[int, int], dict] = {}
    for j in junctions:
        ix = _lattice_index(j["position"]["x"], xs, cluster_tol_cm)
        iy = _lattice_index(j["position"]["y"], ys, cluster_tol_cm)
        if ix is None or iy is None:
            continue
        key = (ix, iy)
        if key not in occ:  # first junction wins at a lattice point
            occ[key] = j

    out: list[dict] = []
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            corners = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            if not all(c in occ for c in corners):
                continue
            x0, x1 = xs[i], xs[i + 1]
            y0, y1 = ys[j], ys[j + 1]
            j00, j10 = occ[(i, j)]["id"], occ[(i + 1, j)]["id"]
            j11, j01 = occ[(i + 1, j + 1)]["id"], occ[(i, j + 1)]["id"]
            in_top = margin_cm + _side_band_into_cell(spec, j00, j10, x0, y0, (0.0, 1.0))
            in_bot = margin_cm + _side_band_into_cell(spec, j01, j11, x0, y1, (0.0, -1.0))
            in_lef = margin_cm + _side_band_into_cell(spec, j00, j01, x0, y0, (1.0, 0.0))
            in_rig = margin_cm + _side_band_into_cell(spec, j10, j11, x1, y0, (-1.0, 0.0))
            xl, xr = x0 + in_lef, x1 - in_rig
            yt, yb = y0 + in_top, y1 - in_bot
            if xr - xl <= 0.0 or yb - yt <= 0.0:
                continue
            poly = [{"x": _f3(xl), "y": _f3(yt)},
                    {"x": _f3(xr), "y": _f3(yt)},
                    {"x": _f3(xr), "y": _f3(yb)},
                    {"x": _f3(xl), "y": _f3(yb)}]
            area = 0.0
            for a, b in zip(poly, poly[1:] + poly[:1]):
                area += a["x"] * b["y"] - b["x"] * a["y"]
            area = abs(area) / 2.0
            out.append({
                "id": f"block_{i}_{j}",
                "polygon": poly,
                "centre": {"x": _f3((xl + xr) / 2.0), "y": _f3((yt + yb) / 2.0)},
                "area_cm2": _f3(area),
                "bbox": {"x_min": _f3(xl), "x_max": _f3(xr),
                         "y_min": _f3(yt), "y_max": _f3(yb)},
            })
    return out


# --- frontages --------------------------------------------------------------


def frontages(block: dict, spec: dict, *, setback_cm: float,
              spacing_cm: float, min_frontage_cm: float) -> list[dict]:
    """Facade positions along the block edges that face a road.

    Each facade: ``{"x","y","yaw","edge_index","length_cm"}``.  Candidates
    walk each polygon edge from ``min_frontage_cm`` past every corner, spaced
    ``spacing_cm``.  ``yaw`` is the outward edge normal in Unreal degrees from
    ``math.atan2`` only.  A candidate whose boundary point is closer than
    ``setback_cm`` to the nearest lane polyline is pulled back into the block
    until it clears the setback.
    """
    poly = block["polygon"]
    n = len(poly)
    if n < 3:
        return []
    cx, cy = block["centre"]["x"], block["centre"]["y"]
    out: list[dict] = []
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        seg = _len2(a, b)
        if seg <= 1e-9:
            continue
        ux, uy = (b["x"] - a["x"]) / seg, (b["y"] - a["y"]) / seg
        px, py = -uy, ux
        mx, my = (a["x"] + b["x"]) / 2.0, (a["y"] + b["y"]) / 2.0
        # pick the perpendicular that points away from the block centre
        if px * (cx - mx) + py * (cy - my) > 0.0:
            px, py = -px, -py
        yaw = normalise_deg(math.degrees(math.atan2(py, px)))
        run_end = seg - min_frontage_cm
        if run_end <= 0.0:
            continue
        s = min_frontage_cm
        while s <= run_end + 1e-6:
            f = s / seg
            bx = a["x"] + (b["x"] - a["x"]) * f
            by = a["y"] + (b["y"] - a["y"]) * f
            clear = nearest_lane_distance_cm(spec, bx, by)
            if clear < setback_cm:
                pull = setback_cm - clear + 1.0
                bx = bx - px * pull
                by = by - py * pull
            length = spacing_cm
            if s + spacing_cm > run_end + 1e-6:
                length = run_end - s
            out.append({"x": _f3(bx), "y": _f3(by), "yaw": yaw,
                        "edge_index": i,
                        "length_cm": _f3(max(length, 0.0))})
            if s + spacing_cm > run_end + 1e-6:
                break
            s += spacing_cm
    return out


# --- building slots ---------------------------------------------------------


def building_slots(spec: dict, *, kits: list[str], seed: int,
                   setback_cm: float = 800.0, spacing_cm: float = 2000.0,
                   depth_cm: float = 1500.0,
                   margin_cm: float = 1200.0) -> dict:
    """Emit building slots for every block of the lattice.

    Kit rule (documented, deterministic): block kit =
    ``digest(block_id, seed) % len(kits)`` where ``digest`` is the int from
    the first 16 hex chars of ``sha256("<block_id>|<seed>")``.  Per slot, 70%
    the dominant (block) kit and 30% another kit, both chosen by the same
    digest scheme from ``"<slot_id>|<seed>|dominant"`` / ``"|other"``.  A
    block keeps a dominant kit: if the dominant share would fall below 60% of
    the block's slots, the lowest-id non-dominant slots are flipped to the
    dominant kit until the floor holds.

    Returns ``{"schema_version","seed","kits","counts":{"blocks","slots",
    "by_kit"},"slots":[...]}`` with slots carrying ``slot_id``, ``block_id``,
    ``kit``, ``x``, ``y``, ``yaw``, ``width_cm``, ``depth_cm`` and
    ``frontage_index``.
    """
    if not kits:
        raise ValueError("kits must be a non-empty list")
    blks = blocks(spec, margin_cm=margin_cm)
    slots: list[dict] = []
    counts_by_kit = {k: 0 for k in kits}
    for blk in blks:
        bid = blk["id"]
        dominant = kits[_digest(bid, seed) % len(kits)]
        frs = frontages(blk, spec, setback_cm=setback_cm,
                        spacing_cm=spacing_cm,
                        min_frontage_cm=spacing_cm / 2.0)
        block_slots: list[dict] = []
        for idx, fr in enumerate(frs):
            sid = f"{bid}:f{idx}"
            if _digest(sid, seed, "dominant") % 100 < _KIT_DOMINANT_PERCENT:
                kit = dominant
            else:
                kit = kits[_digest(sid, seed, "other") % len(kits)]
            width = min(spacing_cm, fr["length_cm"]) if fr["length_cm"] > 0.0 \
                else spacing_cm
            block_slots.append({"slot_id": sid, "block_id": bid, "kit": kit,
                                "x": fr["x"], "y": fr["y"], "yaw": fr["yaw"],
                                "width_cm": _f3(width),
                                "depth_cm": _f3(depth_cm),
                                "frontage_index": idx})
        need = math.ceil(_BLOCK_DOMINANT_FLOOR * len(block_slots))
        dom_n = sum(1 for s in block_slots if s["kit"] == dominant)
        for s in block_slots:  # already in slot-id order: lowest ids first
            if dom_n >= need:
                break
            if s["kit"] != dominant:
                s["kit"] = dominant
                dom_n += 1
        for s in block_slots:
            counts_by_kit[s["kit"]] = counts_by_kit.get(s["kit"], 0) + 1
            slots.append(s)
    return {"schema_version": CITY_LAYOUT_VERSION,
            "seed": seed,
            "kits": list(kits),
            "counts": {"blocks": len(blks), "slots": len(slots),
                       "by_kit": counts_by_kit},
            "slots": slots}


# --- furniture --------------------------------------------------------------


def _edge_outer_lane_side(edge: dict, ln: dict) -> float | None:
    """Outward sign (-1 low / +1 high) of a lane of a normal edge, or None if
    the lane is not an outermost lane of the edge (no outer edge of its own)."""
    lanes = [l for l in edge.get("lanes", []) if l.get("polyline")]
    if not lanes or ln not in lanes:
        return None
    band = _edge_union_band(edge)
    if band is None:
        return None
    ref = lanes[0]["polyline"]
    p0r = ref[0]
    pts = ln["polyline"]
    seg = _len2(pts[0], pts[-1])
    if seg <= 1e-9:
        return None
    ux, uy = (pts[-1]["x"] - pts[0]["x"]) / seg, (pts[-1]["y"] - pts[0]["y"]) / seg
    nx, ny = -uy, ux
    w = ln.get("width_cm_effective")
    if w is None:
        w = ln.get("width_cm")
    if w is None:
        return None
    half = w / 2.0
    lo_i, hi_i = float("inf"), float("-inf")
    for p in pts:
        o = (p["x"] - p0r["x"]) * nx + (p["y"] - p0r["y"]) * ny
        lo_i = min(lo_i, o - half)
        hi_i = max(hi_i, o + half)
    on_low = abs(lo_i - band[0]) <= 1e-6
    on_high = abs(hi_i - band[1]) <= 1e-6
    if on_low:
        return -1.0
    if on_high:
        return 1.0
    return None


def furniture_slots(spec: dict, *, spacing_cm: float = 2500.0,
                    offset_cm: float | None = None,
                    kinds=("lamp", "sign", "bin")) -> dict:
    """Points along every normal lane's *outer* edge.

    ``offset_cm`` defaults to half the lane's ``width_cm_effective`` + 150 cm
    (the sidewalk offset beyond the kerb).  Kinds alternate deterministically
    by global emission index over edges/lanes sorted by id.  Each slot carries
    ``x``, ``y``, ``yaw``, ``kind``, ``lane_id``, ``distance_cm`` and
    ``offset_cm``; ``yaw`` faces the road centre (back across the lane)."""
    if not kinds:
        raise ValueError("kinds must be a non-empty sequence")
    slots: list[dict] = []
    idx = 0
    for e in sorted(spec.get("edges", []), key=lambda e: e["id"]):
        if e.get("function") not in (None, "normal"):
            continue
        for ln in sorted(e.get("lanes", []), key=lambda l: l["id"]):
            outward = _edge_outer_lane_side(e, ln)
            if outward is None:
                continue  # interior lane: no outer edge
            pts = ln["polyline"] or []
            if len(pts) < 2:
                continue
            w = ln.get("width_cm_effective")
            if w is None:
                w = ln.get("width_cm")
            if w is None:
                continue
            seg = _polyline_len(pts)
            if seg <= spacing_cm:
                continue
            p0 = pts[0]
            L = _len2(p0, pts[-1])
            if L <= 1e-9:
                continue
            ux, uy = (pts[-1]["x"] - p0["x"]) / L, (pts[-1]["y"] - p0["y"]) / L
            nx, ny = -uy, ux
            off = (w / 2.0 + 150.0) if offset_cm is None else offset_cm
            s = spacing_cm
            while s <= seg - 1e-6:
                pt = _point_on(pts, s)
                ox, oy = nx * outward * off, ny * outward * off
                # yaw faces the road centre: from the furniture back across the lane
                inx, iny = -ox, -oy
                yaw = normalise_deg(math.degrees(math.atan2(iny, inx)))
                slots.append({"x": _f3(pt["x"] + ox), "y": _f3(pt["y"] + oy),
                              "yaw": yaw,
                              "kind": kinds[idx % len(kinds)],
                              "lane_id": ln["id"],
                              "distance_cm": _f3(s),
                              "offset_cm": _f3(off)})
                idx += 1
                s += spacing_cm
    counts: dict[str, int] = {}
    for s in slots:
        counts[s["kind"]] = counts.get(s["kind"], 0) + 1
    return {"schema_version": CITY_LAYOUT_VERSION, "counts": counts,
            "slots": slots}


# --- crossings --------------------------------------------------------------


def crossing_slots(spec: dict) -> dict:
    """Crosswalk slots from the spec's crossing edges (``function ==
    "crossing"``): centre point of the edge polyline, yaw along the edge and
    the total polyline length."""
    slots: list[dict] = []
    for e in sorted(spec.get("edges", []), key=lambda e: e["id"]):
        if e.get("function") != "crossing":
            continue
        pts = (e.get("lanes") or [{}])[0].get("polyline") or []
        if len(pts) < 2:
            continue
        seg = _polyline_len(pts)
        mid = _point_on(pts, seg / 2.0)
        a, b = pts[0], pts[-1]
        yaw = normalise_deg(math.degrees(math.atan2(b["y"] - a["y"],
                                                    b["x"] - a["x"])))
        slots.append({"x": mid["x"], "y": mid["y"], "yaw": yaw,
                      "edge_id": e["id"], "length_cm": _f3(seg)})
    return {"schema_version": CITY_LAYOUT_VERSION,
            "counts": {"slots": len(slots)}, "slots": slots}


# --- write path -------------------------------------------------------------


def write_layout(spec_path: str | Path, out_path: str | Path, **kwargs: Any) -> dict:
    """Load a road spec JSON, build corridors, blocks, building slots,
    furniture slots and crossing slots, then write sorted-key JSON.

    ``kwargs`` are forwarded to the builders (``kits`` and ``seed`` are
    required for building slots).  Returns the assembled layout dict."""
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    margin_cm = kwargs.get("margin_cm", 1200.0)
    layout = {
        "schema_version": CITY_LAYOUT_VERSION,
        "corridors": road_corridor_polygons(spec, margin_cm=margin_cm),
        "blocks": blocks(spec, margin_cm=margin_cm),
        "building_slots": building_slots(spec, **kwargs),
        "furniture_slots": furniture_slots(spec),
        "crossing_slots": crossing_slots(spec),
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(layout, indent=2, sort_keys=True), encoding="utf-8")
    return layout
