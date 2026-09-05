"""``foliage_plan_v1`` — where the Phase 2 vegetation goes.

Pure stdlib, no ``import unreal``.  This module plans *where* plants are
placed (planter slots, hedge runs, courtyard clusters); a separate editor
module later decides *which* mesh fills each slot.  The mesh inventory is
still being settled, so nothing here depends on it.

Input ``layout`` is a ``city_layout_v1`` document (see ``ldyf.city_layout``):
a dict whose ``"blocks"`` are quad dicts carrying ``id`` and a ``polygon`` —
a list of ``{"x", "y"}`` centimetre points, Unreal space (X east, Y south).
Blocks in this project are road-bounded, so every polygon edge faces a
street and is treated as a frontage (the convention of
``city_layout.frontages``, which walks every polygon edge).  ``yaw`` is the
outward edge normal in Unreal degrees computed with ``math.atan2`` only and
normalised to (-180, 180] via ``ldyf.coords.normalise_deg``.

Determinism laws (mirroring ``ldyf.roads`` / ``ldyf.city_layout`` /
``ldyf.dressing``): every float goes through ``_f3`` (3 decimals, ``-0.0``
killed), iteration is over ids sorted lexicographically, digests are sha256
of exact documented strings, and JSON is written with ``sort_keys=True`` so
the same layout serialises byte-identically.
"""

from __future__ import annotations

import hashlib
import math

from .coords import normalise_deg

FOLIAGE_PLAN_VERSION = "foliage_plan_v1"


# ---------------------------------------------------------------------------
# shared small helpers -------------------------------------------------------
# ---------------------------------------------------------------------------


def _f3(v: float) -> float:
    """Round to 3 decimals (cm resolution) and kill ``-0.0``."""
    r = round(float(v), 3)
    return 0.0 if r == 0.0 else r


def _require_positive(name: str, value, integer: bool = False):
    if integer:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(
                "%s must be a positive integer, got %r" % (name, value))
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("%s must be a number, got %r" % (name, value))
    value = float(value)
    if value <= 0.0:
        raise ValueError("%s must be positive, got %r" % (name, value))
    return value


def _blocks(layout):
    if isinstance(layout, dict):
        blks = layout.get("blocks")
        if blks is None:
            raise ValueError("layout dict has no 'blocks' key")
        return blks
    if isinstance(layout, list):
        return layout
    raise ValueError("layout must be a city_layout document dict or a list of "
                     "block dicts, got %r" % (type(layout).__name__,))


def _xy(p) -> tuple[float, float]:
    if isinstance(p, dict):
        return (float(p["x"]), float(p["y"]))
    return (float(p[0]), float(p[1]))


def _closed_polygon(block) -> list[tuple[float, float]]:
    """Block polygon as a closed list of (x, y) tuples."""
    raw = block.get("polygon")
    if raw is None:
        raise ValueError("block %r has no 'polygon' key" % (block.get("id"),))
    pts = [_xy(p) for p in raw]
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]          # already closed
    if len(pts) < 3:
        raise ValueError("block %r polygon has fewer than 3 points"
                         % (block.get("id"),))
    return pts + [pts[0]]


def _centroid(poly) -> tuple[float, float]:
    area2 = 0.0
    cx = cy = 0.0
    for i in range(len(poly) - 1):
        x0, y0 = poly[i]
        x1, y1 = poly[i + 1]
        cross = x0 * y1 - x1 * y0
        area2 += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if area2 == 0.0:
        return poly[0]
    return (cx / (3.0 * area2), cy / (3.0 * area2))


def _point_in_polygon(px: float, py: float, poly) -> bool:
    """Ray-casting test on a closed ring; boundary counts as outside."""
    inside = False
    for i in range(len(poly) - 1):
        xi, yi = poly[i]
        xj, yj = poly[i + 1]
        if (yi > py) != (yj > py):
            x_cross = (xj - xi) * (py - yi) / (yj - yi) + xi
            if px < x_cross:
                inside = not inside
    return inside


def _dist_pt_seg(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 <= 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / l2
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _edge_clearance(px, py, poly) -> float:
    """Distance from (px, py) to the nearest polygon boundary segment."""
    return min(_dist_pt_seg(px, py, poly[i][0], poly[i][1],
                            poly[i + 1][0], poly[i + 1][1])
               for i in range(len(poly) - 1))


def _outward_edge(a, b, poly):
    """(nx, ny, yaw) of the edge a->b pointing away from the block centre.

    Mirrors ``city_layout.frontages``: the perpendicular is picked by its dot
    with the centre->midpoint vector and ``yaw`` is ``atan2`` only, in Unreal
    degrees, normalised to (-180, 180].  Returns None for a zero-length edge.
    """
    seg = math.hypot(b[0] - a[0], b[1] - a[1])
    if seg <= 0.0:
        return None
    ux, uy = (b[0] - a[0]) / seg, (b[1] - a[1]) / seg
    mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
    cx, cy = _centroid(poly)
    nx, ny = -uy, ux
    if nx * (cx - mx) + ny * (cy - my) > 0.0:
        nx, ny = -nx, -ny          # flipped: was pointing into the block
    yaw = normalise_deg(math.degrees(math.atan2(ny, nx)))
    return nx, ny, yaw


def _inradius(poly) -> float:
    """Largest distance from an interior point to the boundary (cm).

    Exact for rectangles (the shape ``city_layout.blocks`` emits): the
    centroid is sampled first and gives min(side)/2; the grid refines the
    estimate for other convex polygons.  Conservative otherwise.
    """
    cx, cy = _centroid(poly)
    best = _edge_clearance(cx, cy, poly)
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    for i in range(33):
        for j in range(33):
            px = min_x + (max_x - min_x) * i / 32.0
            py = min_y + (max_y - min_y) * j / 32.0
            if not _point_in_polygon(px, py, poly):
                continue
            d = _edge_clearance(px, py, poly)
            if d > best:
                best = d
    return best


def _edge_length_cm(a, b) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


# ---------------------------------------------------------------------------
# planter slots --------------------------------------------------------------
# ---------------------------------------------------------------------------


def planter_slots(layout, *, spacing_cm, inset_cm, size_cm):
    """Rectangular planters along block frontages.

    A frontage is one polygon edge of a block.  ``size_cm``-wide planters sit
    with their centres ``spacing_cm`` apart along the edge; the run is trimmed
    symmetrically at both ends so every planter lies inside the edge.  Each
    planter centre is offset ``inset_cm`` *outward* from the block edge (on
    the street side of the kerb) and ``yaw`` is the outward normal, so a
    planter faces the street.  Rows:

    ``{"id","block_id","x","y","yaw","width_cm","depth_cm","kind":"planter"}``
    """
    spacing = _require_positive("spacing_cm", spacing_cm)
    inset = _require_positive("inset_cm", inset_cm)
    size = _require_positive("size_cm", size_cm)
    rows: list[dict] = []
    for blk in sorted(_blocks(layout), key=lambda b: str(b.get("id", ""))):
        bid = blk["id"]
        poly = _closed_polygon(blk)
        idx = 0
        for i in range(len(poly) - 1):
            a, b = poly[i], poly[i + 1]
            seg = _edge_length_cm(a, b)
            if seg < spacing:
                continue
            count = int(seg // spacing)          # full slots at this spacing
            if count < 1:
                continue
            margin = (seg - (count - 1) * spacing) / 2.0
            out = _outward_edge(a, b, poly)
            if out is None:
                continue
            nx, ny, yaw = out
            for k in range(count):
                s = margin + k * spacing
                f = s / seg
                bx = a[0] + (b[0] - a[0]) * f
                by = a[1] + (b[1] - a[1]) * f
                rows.append({
                    "id": "%s:planter:%03d" % (bid, idx),
                    "block_id": bid,
                    "x": _f3(bx + nx * inset),
                    "y": _f3(by + ny * inset),
                    "yaw": _f3(yaw),
                    "width_cm": _f3(size),
                    "depth_cm": _f3(size),
                    "kind": "planter",
                })
                idx += 1
    return sorted(rows, key=lambda r: str(r["id"]))


# ---------------------------------------------------------------------------
# hedge runs -----------------------------------------------------------------
# ---------------------------------------------------------------------------


def hedge_runs(layout, *, min_run_cm, offset_cm, segment_cm):
    """Runs of hedge along frontage stretches of at least ``min_run_cm``.

    A frontage polygon edge whose length >= ``min_run_cm`` is cut into pieces
    of at most ``segment_cm``, each an instanceable unit rather than one long
    mesh: ``ceil(length / segment_cm)`` pieces whose lengths are
    ``segment_cm`` except the final one, which keeps its true remainder.  Each
    piece centre is offset ``offset_cm`` outward from the block edge.  Rows:

    ``{"id","block_id","x","y","yaw","length_cm","kind":"hedge"}``
    """
    min_run = _require_positive("min_run_cm", min_run_cm)
    offset = _require_positive("offset_cm", offset_cm)
    segment = _require_positive("segment_cm", segment_cm)
    rows: list[dict] = []
    for blk in sorted(_blocks(layout), key=lambda b: str(b.get("id", ""))):
        bid = blk["id"]
        poly = _closed_polygon(blk)
        idx = 0
        for i in range(len(poly) - 1):
            a, b = poly[i], poly[i + 1]
            seg = _edge_length_cm(a, b)
            if seg < min_run:
                continue
            out = _outward_edge(a, b, poly)
            if out is None:
                continue
            nx, ny, yaw = out
            pieces = int(math.ceil(seg / segment - 1e-9))
            for k in range(pieces):
                piece_len = segment
                if k == pieces - 1:
                    piece_len = seg - (pieces - 1) * segment
                s = k * segment + piece_len / 2.0
                f = s / seg
                hx = a[0] + (b[0] - a[0]) * f
                hy = a[1] + (b[1] - a[1]) * f
                rows.append({
                    "id": "%s:hedge:%03d" % (bid, idx),
                    "block_id": bid,
                    "x": _f3(hx + nx * offset),
                    "y": _f3(hy + ny * offset),
                    "yaw": _f3(yaw),
                    "length_cm": _f3(piece_len),
                    "kind": "hedge",
                })
                idx += 1
    return sorted(rows, key=lambda r: str(r["id"]))


# ---------------------------------------------------------------------------
# courtyard clusters ---------------------------------------------------------
# ---------------------------------------------------------------------------


def _digest_uv(*parts: object) -> tuple[float, float]:
    """Two [0, 1) numbers from the sha256 digest of parts joined by '|'.

    Matches the digest rule of ``city_layout._digest`` (sha256 over
    ``"|".join(str(p) ...)``); u and v are the first two 64-bit chunks.
    """
    text = "|".join(str(p) for p in parts)
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return (int(h[0:16], 16) / float(1 << 64),
            int(h[16:32], 16) / float(1 << 64))


def courtyard_clusters(layout, *, per_block, radius_cm, seed):
    """Small clusters of vegetation inside each block's interior.

    ``per_block`` points per block, each generated from the sha256 digest of
    ``(block_id, index, seed)`` mapped onto the block's bounding box.  A
    candidate is accepted only when it is strictly inside the block polygon
    and at least ``radius_cm`` from every edge; rejected candidates re-digest
    with an appended trial counter (reject-and-redigest).  Nothing is clamped
    onto the boundary -- clamping would pile points on the edge and the whole
    point of the clearance is that a replant honours it.  Rows:

    ``{"id","block_id","x","y","radius_cm","kind":"cluster"}``
    """
    per = _require_positive("per_block", per_block, integer=True)
    radius = _require_positive("radius_cm", radius_cm)
    blks = list(_blocks(layout))
    if not blks:
        return []
    polys = {}
    for blk in sorted(blks, key=lambda b: str(b.get("id", ""))):
        try:
            polys[blk["id"]] = _closed_polygon(blk)
        except ValueError:
            continue
    if not polys:
        return []
    # Refuse before planting anything: a radius no block can honour would
    # silently produce an empty (or endless) placement.
    smallest = min(_inradius(p) for p in polys.values())
    if radius > smallest:
        raise ValueError(
            "radius_cm (%r) is larger than the smallest block inradius (%r); "
            "no point could sit %r cm from every edge"
            % (radius, smallest, radius))

    rows: list[dict] = []
    for bid in sorted(polys):
        poly = polys[bid]
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
        bw, bh = max_x - min_x, max_y - min_y
        placed = 0
        while placed < per:
            accepted = False
            for trial in range(20000):
                if trial == 0:
                    u, v = _digest_uv(bid, placed, seed)
                else:
                    u, v = _digest_uv(bid, placed, seed, trial)
                px = min_x + u * bw
                py = min_y + v * bh
                if not _point_in_polygon(px, py, poly):
                    continue
                if _edge_clearance(px, py, poly) < radius:
                    continue
                rows.append({
                    "id": "%s:cluster:%03d" % (bid, placed),
                    "block_id": bid,
                    "x": _f3(px),
                    "y": _f3(py),
                    "radius_cm": _f3(radius),
                    "kind": "cluster",
                })
                accepted = True
                break
            if not accepted:
                raise RuntimeError(
                    "could not place cluster %d in block %r at radius_cm=%r "
                    "after 20000 digests" % (placed, bid, radius))
            placed += 1
    return sorted(rows, key=lambda r: str(r["id"]))


# ---------------------------------------------------------------------------
# whole plan -----------------------------------------------------------------
# ---------------------------------------------------------------------------


def foliage_plan(layout, *, spacing_cm=500.0, inset_cm=40.0, size_cm=120.0,
                 min_run_cm=800.0, offset_cm=60.0, segment_cm=400.0,
                 per_block=3, radius_cm=80.0, seed="foliage-v1"):
    """The whole ``foliage_plan_v1`` document.

    Returns ``{"schema_version","params","counts","planters","hedges",
    "clusters"}``; the three row lists are sorted by id, every float has been
    through ``_f3``, and the document is byte-deterministic under
    ``json.dumps(..., sort_keys=True)``.
    """
    planters = planter_slots(layout, spacing_cm=spacing_cm,
                             inset_cm=inset_cm, size_cm=size_cm)
    hedges = hedge_runs(layout, min_run_cm=min_run_cm, offset_cm=offset_cm,
                        segment_cm=segment_cm)
    clusters = courtyard_clusters(layout, per_block=per_block,
                                  radius_cm=radius_cm, seed=seed)
    params = {
        "spacing_cm": _f3(spacing_cm),
        "inset_cm": _f3(inset_cm),
        "size_cm": _f3(size_cm),
        "min_run_cm": _f3(min_run_cm),
        "offset_cm": _f3(offset_cm),
        "segment_cm": _f3(segment_cm),
        "per_block": per,
        "radius_cm": _f3(radius_cm),
        "seed": seed,
    }
    return {
        "schema_version": FOLIAGE_PLAN_VERSION,
        "params": params,
        "counts": {"planters": len(planters), "hedges": len(hedges),
                   "clusters": len(clusters)},
        "planters": planters,
        "hedges": hedges,
        "clusters": clusters,
    }


# ---------------------------------------------------------------------------
# conflict detection ---------------------------------------------------------
# ---------------------------------------------------------------------------


def _row_radius_cm(row: dict) -> float:
    """Foliage footprint radius used by ``conflicts``.

    Hedges: half the piece length (a piece centred on (x, y) spans up to
    length/2 either way along the frontage, so a disc of radius length/2 is
    the conservative cover that needs no extra geometry in the row).
    Planters: half the footprint diagonal (circumscribed disc).  Clusters:
    their own radius.
    """
    if row["kind"] == "hedge":
        return float(row["length_cm"]) / 2.0
    if row["kind"] == "planter":
        w = float(row.get("width_cm", 0.0))
        d = float(row.get("depth_cm", 0.0))
        return math.hypot(w, d) / 2.0
    return float(row.get("radius_cm", 0.0))


def conflicts(plan: dict, occupied, *, clearance_cm):
    """Return every foliage row closer than ``clearance_cm`` to an obstacle.

    ``occupied`` is a list of ``{"x","y","radius_cm"}`` for things already
    placed (street furniture, tree pits, signals).  A row conflicts with an
    obstacle when the gap between their footprints is below ``clearance_cm``:

        gap = dist(row, obstacle) - row_radius - obstacle_radius

    Each conflict entry identifies the row and the obstacle and reports the
    gap.  A plan that puts a hedge through a lamp post must be able to say so.
    """
    clearance = _require_positive("clearance_cm", clearance_cm)
    obstacles = [{"x": float(o["x"]), "y": float(o["y"]),
                  "radius_cm": float(o.get("radius_cm", 0.0))}
                 for o in occupied]
    out: list[dict] = []
    for section in ("planters", "hedges", "clusters"):
        for row in plan.get(section, []):
            rx, ry = float(row["x"]), float(row["y"])
            rr = _row_radius_cm(row)
            for o in obstacles:
                dist = math.hypot(rx - o["x"], ry - o["y"])
                gap = dist - rr - o["radius_cm"]
                if gap < clearance:
                    out.append({
                        "row_id": row["id"],
                        "kind": row.get("kind"),
                        "block_id": row.get("block_id"),
                        "obstacle_x": _f3(o["x"]),
                        "obstacle_y": _f3(o["y"]),
                        "obstacle_radius_cm": _f3(o["radius_cm"]),
                        "gap_cm": _f3(gap),
                    })
    out.sort(key=lambda c: (str(c["row_id"]), c["obstacle_x"],
                            c["obstacle_y"]))
    return out
