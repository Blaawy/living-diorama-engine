"""Per-block ground surfaces for the Living Diorama world.

Pure stdlib.  No ``import unreal``.  Deterministic: the same inputs always
produce a byte-identical ``json.dumps(..., sort_keys=True)`` document.

Why this module exists
----------------------
The Phase 2 ground was one enormous ~600 m quad whose UVs spanned a
kilometre, so texel density was far below one texel per pixel everywhere and
the material showed harsh black/white speckle regardless of albedo, normal
map, roughness, tiling or ``cast_shadow``.  Fixing that speckle is a geometry
job: emit one modest ground surface per city block plus the verge strips
between a block's edge and the adjacent road corridor, each with its own sane
UV scale, and subdivide any surface wider or taller than ``max_polygon_cm``
into a grid of smaller quads so texture density stays sane everywhere.

``city_layout`` data model (see city_layout.py)
-----------------------------------------------
* ``layout["blocks"]``  (city_layout.py:256-319): list of dicts, each with
  ``id`` ("block_<i>_<j>"), ``polygon`` (list of ``{"x","y"}``, an
  axis-aligned quad), ``centre``, ``area_cm2`` and ``bbox`` keyed by
  ``x_min/x_max/y_min/y_max``.
* ``layout["corridors"]`` (city_layout.py:602): a plain list of raw corridor
  polygons (lists of four ``{"x","y"}``), no ids and no bbox dict.  Each is
  the lane-union band of a normal road edge expanded by the layout's own
  ``margin_cm`` (city_layout.py:173-205, 208-218).
"""

from __future__ import annotations

import json
import math

GROUND_PLAN_VERSION = "ground_plan_v1"

# World size of one texture repeat used when a caller does not supply a
# texture_metres value (2 m surfaces -> 200 cm).
DEFAULT_UV_SCALE_CM = 200.0

_EPS = 1e-6


# --------------------------------------------------------------------------- #
# deterministic numeric + geometric helpers
# --------------------------------------------------------------------------- #


def _f3(value):
    """dressing.py/city_layout.py convention: round to 3 decimals, kill -0.0."""
    r = round(float(value), 3)
    return 0.0 if r == 0.0 else r


def _pt(x, y):
    return {"x": _f3(x), "y": _f3(y)}


def _polygon(points):
    """Normalise any iterable of {"x","y"} to a fresh list of rounded points."""
    return [_pt(p["x"], p["y"]) for p in points]


def _signed_area(poly):
    total = 0.0
    n = len(poly)
    for i in range(n):
        a = poly[i]
        b = poly[(i + 1) % n]
        total += a["x"] * b["y"] - b["x"] * a["y"]
    return total / 2.0


def _area(poly):
    return abs(_signed_area(poly))


def _bbox(poly):
    xs = [p["x"] for p in poly]
    ys = [p["y"] for p in poly]
    return {
        "min_x": _f3(min(xs)),
        "min_y": _f3(min(ys)),
        "max_x": _f3(max(xs)),
        "max_y": _f3(max(ys)),
    }


def _centre(bbox):
    return {
        "x": _f3((bbox["min_x"] + bbox["max_x"]) / 2.0),
        "y": _f3((bbox["min_y"] + bbox["max_y"]) / 2.0),
    }


def _centroid(poly):
    """Area centroid as a raw (x, y) tuple; used only for offsetting."""
    n = len(poly)
    if n == 0:
        return (0.0, 0.0)
    sa = _signed_area(poly)
    if abs(sa) < _EPS:
        return (sum(p["x"] for p in poly) / n, sum(p["y"] for p in poly) / n)
    cx = cy = 0.0
    for i in range(n):
        a = poly[i]
        b = poly[(i + 1) % n]
        f = a["x"] * b["y"] - b["x"] * a["y"]
        cx += (a["x"] + b["x"]) * f
        cy += (a["y"] + b["y"]) * f
    return (cx / (6.0 * sa), cy / (6.0 * sa))


def _offset_polygon(poly, delta_cm):
    """Push every vertex along the ray from the area centroid by delta_cm
    (positive = outward/expansion, negative = inward/shrink).  Vertices whose
    centroid distance would drop to zero or below are dropped (shrinking)."""
    cx, cy = _centroid(poly)
    out = []
    for p in poly:
        dx = p["x"] - cx
        dy = p["y"] - cy
        d = math.hypot(dx, dy)
        if d <= _EPS:
            out.append(_pt(p["x"], p["y"]))
            continue
        if d + delta_cm <= _EPS:
            continue  # shrunk away
        s = (d + delta_cm) / d
        out.append(_pt(cx + dx * s, cy + dy * s))
    return out


def _expand_polygon(poly, margin_cm):
    return _offset_polygon(poly, margin_cm)


# --------------------------------------------------------------------------- #
# polygon clipping (Sutherland-Hodgman against a convex clip polygon)
# --------------------------------------------------------------------------- #


def _clip_subject(subject, clip):
    """Intersection of ``subject`` with convex ``clip``; [] when disjoint."""
    out = [dict(p) for p in subject]
    n = len(clip)
    if n < 3:
        return []
    clip_sign = 1.0 if _signed_area(clip) >= 0.0 else -1.0
    for i in range(n):
        if len(out) < 3:
            return []
        a = clip[i]
        b = clip[(i + 1) % n]
        ex = b["x"] - a["x"]
        ey = b["y"] - a["y"]

        def inside(p):
            cross = ex * (p["y"] - a["y"]) - ey * (p["x"] - a["x"])
            return cross * clip_sign >= -_EPS

        def intersect(p, q):
            pdx = q["x"] - p["x"]
            pdy = q["y"] - p["y"]
            denom = ex * pdy - ey * pdx
            if abs(denom) <= _EPS:
                return _pt(q["x"], q["y"])
            t = (ex * (p["y"] - a["y"]) - ey * (p["x"] - a["x"])) / denom
            return _pt(p["x"] + t * pdx, p["y"] + t * pdy)

        nxt = []
        m = len(out)
        for j in range(m):
            p = out[j]
            q = out[(j + 1) % m]
            pin = inside(p)
            qin = inside(q)
            if pin and qin:
                nxt.append(q)
            elif pin and not qin:
                nxt.append(intersect(p, q))
            elif not pin and qin:
                nxt.append(intersect(p, q))
                nxt.append(q)
        out = nxt
    return out


def _intersection_area(poly_a, poly_b):
    clip_poly = _clip_subject(poly_a, poly_b)
    if len(clip_poly) < 3:
        return 0.0
    return _area(clip_poly)


# --------------------------------------------------------------------------- #
# city_layout adapters: normalise block / corridor shapes
# --------------------------------------------------------------------------- #


def _as_polygon(obj):
    """Polygon from a dict with ``polygon``/``bbox`` or a raw point list."""
    if isinstance(obj, dict):
        if "polygon" in obj:
            poly = _polygon(obj["polygon"])
            if len(poly) >= 3:
                return poly
        b = _dict_bbox(obj)
        if b is not None:
            return [
                _pt(b["min_x"], b["min_y"]),
                _pt(b["max_x"], b["min_y"]),
                _pt(b["max_x"], b["max_y"]),
                _pt(b["min_x"], b["max_y"]),
            ]
    if isinstance(obj, (list, tuple)):
        pts = list(obj)
        if pts and all(isinstance(p, dict) and "x" in p and "y" in p for p in pts):
            poly = _polygon(pts)
            if len(poly) >= 3:
                return poly
    return None


def _dict_bbox(obj):
    """Canonical min_x/min_y/max_x/max_y bbox from a dict carrying any of the
    accepted key flavours (city_layout blocks use x_min/x_max/y_min/y_max)."""
    if not isinstance(obj, dict):
        return None
    if all(k in obj for k in ("min_x", "min_y", "max_x", "max_y")):
        return {k: float(obj[k]) for k in ("min_x", "min_y", "max_x", "max_y")}
    if all(k in obj for k in ("x_min", "y_min", "x_max", "y_max")):
        return {"min_x": float(obj["x_min"]), "min_y": float(obj["y_min"]),
                "max_x": float(obj["x_max"]), "max_y": float(obj["y_max"])}
    if all(k in obj for k in ("x0", "y0", "x1", "y1")):
        return {"min_x": float(obj["x0"]), "min_y": float(obj["y0"]),
                "max_x": float(obj["x1"]), "max_y": float(obj["y1"])}
    if "bbox" in obj and isinstance(obj["bbox"], dict):
        return _dict_bbox(obj["bbox"])
    return None


def _polygon_of_block(block):
    if not isinstance(block, dict):
        raise ValueError("block entry must be a dict with 'id' and geometry")
    poly = _as_polygon(block)
    if poly is None:
        raise ValueError("block %s must carry a polygon or a bbox" % (block.get("id"),))
    return poly


def _corridor_polygon(corridor):
    """Raw corridor polygon (city_layout list of 4 pts) or dict-with-polygon.
    Returns None when the corridor cannot be turned into a polygon."""
    if isinstance(corridor, (list, tuple)):
        return _as_polygon(list(corridor))
    if isinstance(corridor, dict):
        return _as_polygon(corridor)
    return None


def _corridor_id(corridor, index):
    if isinstance(corridor, dict) and "id" in corridor:
        return str(corridor["id"])
    return "corridor_%d" % index


def _axis_aligned_rect_bbox(poly):
    """BBox of an axis-aligned rectangle polygon, else None (rotated
    corridors are skipped: their verge strips are not axis aligned)."""
    b = _bbox(poly)
    corners = {(b["min_x"], b["min_y"]), (b["max_x"], b["min_y"]),
               (b["max_x"], b["max_y"]), (b["min_x"], b["max_y"])}
    pts = {(p["x"], p["y"]) for p in poly}
    if pts == corners:
        return b
    return None


def _key(item):
    return str(item["id"])


# --------------------------------------------------------------------------- #
# row construction
# --------------------------------------------------------------------------- #


def _row(surface_id, poly, kind, uv_scale_cm=DEFAULT_UV_SCALE_CM):
    bbox = _bbox(poly)
    return {
        "id": str(surface_id),
        "kind": kind,
        "polygon": poly,
        "area_cm2": _f3(_area(poly)),
        "bbox": bbox,
        "centre": _centre(bbox),
        "uv_scale_cm": _f3(uv_scale_cm),
    }


def _validate_layout(layout):
    if not isinstance(layout, dict) or not isinstance(layout.get("blocks"), list):
        raise ValueError("layout must be a dict with a 'blocks' list")
    if not layout["blocks"]:
        raise ValueError("empty layout: no blocks to build ground from")
    blocks = sorted(layout["blocks"], key=_key)
    for block in blocks:
        _polygon_of_block(block)  # fail fast on malformed entries
    corridors = layout.get("corridors")
    if corridors is not None and not isinstance(corridors, list):
        raise ValueError("layout['corridors'] must be a list")
    return blocks


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #


def block_ground_polygons(layout, *, margin_cm):
    """One ground surface per city block: the block polygon expanded outward
    by ``margin_cm`` so it tucks under the kerb instead of leaving a seam."""
    blocks = _validate_layout(layout)
    if margin_cm < 0:
        raise ValueError("margin_cm must be >= 0")
    rows = []
    for block in blocks:
        poly = _expand_polygon(_polygon_of_block(block), margin_cm)
        if len(poly) < 3:
            raise ValueError("block %s collapsed under margin_cm=%s"
                             % (block["id"], margin_cm))
        rows.append(_row(block["id"], poly, "ground"))
    return rows


def gap_polygons(layout, spec, *, margin_cm):
    """Ground that is neither a block nor carriageway: the axis-aligned strip
    between a block's (margin-expanded) edge and the corridor band that runs
    along that side, as computed by city_layout.  Strips are derived from the
    *expanded* block edges, so the output is disjoint from
    ``block_ground_polygons`` by construction.  A verge strip is emitted for a
    block on the side facing the corridor band that lies on its north side
    (corridor above the block); a block that sits on the corridor's far side
    (corridor below the block) generates no strip from that corridor.  Rotated
    corridor rectangles and corridor/block pairs with no positive gap produce
    nothing."""
    blocks = _validate_layout(layout)
    if margin_cm < 0:
        raise ValueError("margin_cm must be >= 0")
    corridors = layout.get("corridors") or []
    strips = []
    seen = set()
    for block in blocks:
        block_id = str(block["id"])
        # same deterministic expansion as block_ground_polygons
        poly = _expand_polygon(_polygon_of_block(block), margin_cm)
        bb = _bbox(poly)
        for index, cor in enumerate(corridors):
            cor_poly = _corridor_polygon(cor)
            if cor_poly is None:
                continue
            cb = _axis_aligned_rect_bbox(cor_poly)
            if cb is None:
                continue
            cor_id = _corridor_id(cor, index)
            for tag, strip_poly in _strips_between(bb, cb):
                key = tuple((p["x"], p["y"]) for p in strip_poly)
                if key in seen:
                    continue
                seen.add(key)
                row = _row("%s|verge|%s|%s" % (block_id, cor_id, tag),
                           strip_poly, "verge")
                row["source_block"] = block_id
                row["source_corridor"] = cor_id
                strips.append(row)
    strips.sort(key=_key)
    return strips


def _strips_between(block_bb, corridor_bb):
    """Axis-aligned rectangles lying between a block edge and a corridor band
    on the block's north side (the corridor runs along that side of the block),
    wherever the two are separated by a positive gap.  A block that lies on the
    far (north) side of a corridor does not face it and gets no verge strip."""
    out = []

    def maybe(tag, x0, y0, x1, y1):
        if x1 - x0 > _EPS and y1 - y0 > _EPS:
            out.append((tag, [_pt(x0, y0), _pt(x1, y0),
                              _pt(x1, y1), _pt(x0, y1)]))

    ox = (max(block_bb["min_x"], corridor_bb["min_x"]),
          min(block_bb["max_x"], corridor_bb["max_x"]))
    # corridor above the block: the block faces it across the strip that spans
    # the shared x-overlap between the block's north edge and the corridor's
    # near (kerb) edge.
    if corridor_bb["min_y"] >= block_bb["max_y"] + _EPS:
        maybe("above", ox[0], block_bb["max_y"], ox[1], corridor_bb["min_y"])
    return out


def _subdivide_surface(row, max_polygon_cm):
    """Split a surface whose bbox exceeds ``max_polygon_cm`` on any side into
    a grid of smaller quads; every piece keeps the parent's id in
    ``parent_id`` and gets its own id.  Cells are clipped against the parent
    polygon, so the pieces tile the parent exactly."""
    bbox = row["bbox"]
    width = bbox["max_x"] - bbox["min_x"]
    height = bbox["max_y"] - bbox["min_y"]
    cols = max(1, math.ceil(width / max_polygon_cm - _EPS))
    rows = max(1, math.ceil(height / max_polygon_cm - _EPS))
    if cols == 1 and rows == 1:
        return [row]
    x0, y0 = bbox["min_x"], bbox["min_y"]
    dx = width / cols
    dy = height / rows
    parent_id = row["id"]
    pieces = []
    for r in range(rows):
        for c in range(cols):
            cell = [_pt(x0 + c * dx, y0 + r * dy),
                    _pt(x0 + (c + 1) * dx, y0 + r * dy),
                    _pt(x0 + (c + 1) * dx, y0 + (r + 1) * dy),
                    _pt(x0 + c * dx, y0 + (r + 1) * dy)]
            clipped = _clip_subject(row["polygon"], cell)
            if len(clipped) < 3:
                continue
            piece = _row("%s#%dx%d" % (parent_id, r, c), clipped,
                         row["kind"], row["uv_scale_cm"])
            piece["parent_id"] = parent_id
            pieces.append(piece)
    if not pieces:
        return [row]
    return pieces


def ground_plan(layout, spec, *, margin_cm, texture_metres, max_polygon_cm):
    """The whole ``ground_plan_v1`` document."""
    if max_polygon_cm <= 0:
        raise ValueError("max_polygon_cm must be positive, got %s" % (max_polygon_cm,))
    if texture_metres <= 0:
        raise ValueError("texture_metres must be positive, got %s" % (texture_metres,))
    _validate_layout(layout)  # raises on empty layout

    uv = _f3(float(texture_metres) * 100.0)
    block_rows = block_ground_polygons(layout, margin_cm=margin_cm)
    gap_rows = gap_polygons(layout, spec, margin_cm=margin_cm)
    surfaces = []
    subdivided_parents = 0
    subdivision_pieces = 0
    for row in block_rows + gap_rows:
        row["uv_scale_cm"] = uv
        pieces = _subdivide_surface(row, max_polygon_cm)
        if len(pieces) > 1:
            subdivided_parents += 1
            subdivision_pieces += len(pieces)
        surfaces.extend(pieces)
    surfaces.sort(key=_key)

    try:
        spec_plain = json.loads(json.dumps(spec, sort_keys=True))
    except TypeError:
        spec_plain = None

    counts = {
        "surfaces": len(surfaces),
        "blocks": len(block_rows),
        "verges": len(gap_rows),
        "subdivided_parents": subdivided_parents,
        "subdivision_pieces": subdivision_pieces,
    }
    return {
        "schema_version": GROUND_PLAN_VERSION,
        "params": {
            "margin_cm": _f3(margin_cm),
            "texture_metres": _f3(texture_metres),
            "max_polygon_cm": _f3(max_polygon_cm),
            "spec": spec_plain,
        },
        "counts": counts,
        "surfaces": surfaces,
    }


def total_area_cm2(plan):
    """Sum of every surface's area.  Because subdivision tiles the parent
    exactly, this is also the check that no area was lost or duplicated."""
    total = 0.0
    for surface in plan.get("surfaces", []):
        total += float(surface["area_cm2"])
    return _f3(total)


def overlaps(plan, *, tol_cm):
    """Any pair of surfaces that genuinely overlap.  ``tol_cm`` is a clearance
    tolerance: each polygon is first shrunk inward by ``tol_cm`` and only
    pairs whose shrunk forms still intersect with positive area are reported —
    a clean plan returns an empty list.  (Polygon intersection is
    Sutherland-Hodgman, exact for the convex quads/strips this module emits.)"""
    if tol_cm < 0:
        raise ValueError("tol_cm must be >= 0")
    surfaces = list(plan.get("surfaces", []))
    surfaces.sort(key=_key)
    pairs = []
    n = len(surfaces)
    for i in range(n):
        for j in range(i + 1, n):
            a = surfaces[i]
            b = surfaces[j]
            ab = a["bbox"]
            bb = b["bbox"]
            if (ab["max_x"] <= bb["min_x"] or bb["max_x"] <= ab["min_x"]
                    or ab["max_y"] <= bb["min_y"] or bb["max_y"] <= ab["min_y"]):
                continue
            sa = _offset_polygon(a["polygon"], -tol_cm)
            sb = _offset_polygon(b["polygon"], -tol_cm)
            if len(sa) < 3 or len(sb) < 3:
                continue
            overlap = _intersection_area(sa, sb)
            if overlap > _EPS:
                pairs.append({"a": a["id"], "b": b["id"],
                              "overlap_area_cm2": _f3(overlap)})
    return pairs
