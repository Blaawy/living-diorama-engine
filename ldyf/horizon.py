"""horizon.py -- world-edge treatment for the Living Diorama Phase 2 world.

The Phase 2 road world is a finite square of ground; seen from inside, its
edge is visible.  This module builds the "horizon plan": a subdivided skirt
ring that continues the ground outward, a deterministic backdrop ring of
distant building masses, and fog settings whose distances are derived from
the world's own size.  Pure stdlib - no `unreal`, no `random`.
"""
import hashlib
import math

HORIZON_PLAN_VERSION = "horizon_plan_v1"


def _f3(value):
    """Round any float to three decimals (mirrors ldyf/dressing.py)."""
    return round(float(value), 3)


def _frac(*parts):
    """Deterministic value in [0, 1) from a sha256 digest of parts.

    Deliberately not `random`: a replay of the same spec and seed must
    reproduce the same skyline.
    """
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def _bounds_numbers(bounds):
    missing = [key for key in ("x_min", "x_max", "y_min", "y_max")
               if key not in bounds]
    if missing:
        raise ValueError("bounds missing required keys: %s" % (missing,))
    return (float(bounds["x_min"]), float(bounds["x_max"]),
            float(bounds["y_min"]), float(bounds["y_max"]))


def _polyline_points(polyline):
    """Normalise one polyline to [(x, y), ...].

    Points may be {'x': .., 'y': ..} dicts, {'point': [x, y]} dicts, or
    two-value sequences.
    """
    points = []
    for item in polyline:
        if isinstance(item, dict):
            if "x" in item and "y" in item:
                points.append((float(item["x"]), float(item["y"])))
            else:
                seq = None
                for key in ("point", "pos", "xy"):
                    if key in item:
                        seq = item[key]
                        break
                if seq is None:
                    raise ValueError(
                        "polyline point dict has no x/y coordinates: %r" % (item,))
                points.append((float(seq[0]), float(seq[1])))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            points.append((float(item[0]), float(item[1])))
        else:
            raise ValueError("unrecognised polyline point: %r" % (item,))
    return points


def _iter_polylines(node, out):
    """Collect every lane 'polyline' list in a road_spec_v1.

    Accepts spec["lanes"] as a list or a dict of lanes, and spec["roads"]
    -> lanes nesting, so common road_spec_v1 shapes all work.
    """
    if isinstance(node, dict):
        if isinstance(node.get("polyline"), (list, tuple)):
            out.append(node["polyline"])
        for key in ("lanes", "roads"):
            if key in node:
                _iter_polylines(node[key], out)
    elif isinstance(node, (list, tuple)):
        for child in node:
            _iter_polylines(child, out)


def world_bounds(spec):
    """Bounding box of every lane polyline in a road_spec_v1.

    Returns {"x_min", "x_max", "y_min", "y_max", "centre", "size_cm"} with
    centre {"x", "y"} and size_cm [width, height], all floats through _f3.
    """
    if not isinstance(spec, dict):
        raise ValueError("world_bounds expects a road_spec_v1 dict, got %r" % (spec,))
    polylines = []
    _iter_polylines(spec, polylines)
    if not polylines:
        raise ValueError("road_spec_v1 contains no lane polylines; "
                         "cannot compute world bounds")
    xs, ys = [], []
    for polyline in polylines:
        points = _polyline_points(polyline)
        if len(points) < 2:
            raise ValueError("every lane polyline needs at least two points")
        for x, y in points:
            xs.append(x)
            ys.append(y)
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    if not (x_max > x_min and y_max > y_min):
        raise ValueError("lane polylines are degenerate (zero width or height)")
    return {
        "x_min": _f3(x_min), "x_max": _f3(x_max),
        "y_min": _f3(y_min), "y_max": _f3(y_max),
        "centre": {"x": _f3((x_min + x_max) / 2.0), "y": _f3((y_min + y_max) / 2.0)},
        "size_cm": [_f3(x_max - x_min), _f3(y_max - y_min)],
    }


def _quad_row(rid, x0, y0, x1, y1, cx, cy):
    """One axis-aligned skirt quad as a row dict; yaw points at the centre."""
    polygon = [
        {"x": _f3(x0), "y": _f3(y0)},
        {"x": _f3(x1), "y": _f3(y0)},
        {"x": _f3(x1), "y": _f3(y1)},
        {"x": _f3(x0), "y": _f3(y1)},
    ]
    rx = (x0 + x1) / 2.0
    ry = (y0 + y1) / 2.0
    yaw = math.degrees(math.atan2(cy - ry, cx - rx)) % 360.0
    return {"id": rid, "polygon": polygon,
            "centre": {"x": _f3(rx), "y": _f3(ry)},
            "yaw": _f3(yaw), "kind": "skirt"}


def skirt_ring(bounds, *, inner_margin_cm, width_cm, segments):
    """Ring of quads continuing the ground outward from the world bbox.

    The annulus between the world bbox grown by inner_margin_cm and the same
    bbox grown by inner_margin_cm + width_cm is tiled by four side strips of
    `segments` quads each plus four corner quads.  Subdivision matters: one
    enormous ground quad is exactly what renders as speckle.
    """
    x0, x1, y0, y1 = _bounds_numbers(bounds)
    margin = float(inner_margin_cm)
    width = float(width_cm)
    segments = int(segments)
    if width <= 0.0:
        raise ValueError("skirt width_cm must be positive, got %r" % (width_cm,))
    if margin < 0.0:
        raise ValueError("skirt inner_margin_cm must be >= 0, got %r" % (inner_margin_cm,))
    if segments <= 0:
        raise ValueError("skirt segments must be a positive integer, got %r" % (segments,))
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    xi0, xi1 = x0 - margin, x1 + margin
    yi0, yi1 = y0 - margin, y1 + margin
    xo0, xo1 = xi0 - width, xi1 + width
    yo0, yo1 = yi0 - width, yi1 + width
    rows = []
    segw = (xi1 - xi0) / float(segments)
    for i in range(segments):
        a, b = xi0 + segw * i, xi0 + segw * (i + 1)
        rows.append(_quad_row("skirt_b_%03d" % i, a, yo0, b, yi0, cx, cy))
    segh = (yi1 - yi0) / float(segments)
    for j in range(segments):
        a, b = yi0 + segh * j, yi0 + segh * (j + 1)
        rows.append(_quad_row("skirt_r_%03d" % j, xi1, a, xo1, b, cx, cy))
    for i in range(segments):
        a, b = xi0 + segw * i, xi0 + segw * (i + 1)
        rows.append(_quad_row("skirt_t_%03d" % i, a, yi1, b, yo1, cx, cy))
    for j in range(segments):
        a, b = yi0 + segh * j, yi0 + segh * (j + 1)
        rows.append(_quad_row("skirt_l_%03d" % j, xo0, a, xi0, b, cx, cy))
    rows.append(_quad_row("skirt_c_sw", xo0, yo0, xi0, yi0, cx, cy))
    rows.append(_quad_row("skirt_c_se", xi1, yo0, xo1, yi0, cx, cy))
    rows.append(_quad_row("skirt_c_ne", xi1, yi1, xo1, yo1, cx, cy))
    rows.append(_quad_row("skirt_c_nw", xo0, yi1, xi0, yo1, cx, cy))
    rows.sort(key=lambda row: row["id"])
    return rows


def backdrop_blocks(bounds, *, ring_radius_cm, count, height_range_cm,
                    depth_cm, seed):
    """Deterministic ring of distant building masses beyond the skirt.

    Blocks sit at angle step*i plus a sha256-derived jitter u in
    [-0.35, 0.35]*step, so neighbouring centres are at least 0.3*step apart.
    Block width is capped so its angular half-width (atan2(w/2, ring radius))
    stays below 0.95 * half of that gap - blocks can never overlap.  Heights,
    angles, widths and radial offsets all come from sha256(id, seed); no
    `random`.  yaw (degrees, 0 = +x) points at the world centre.
    """
    x0, x1, y0, y1 = _bounds_numbers(bounds)
    radius = float(ring_radius_cm)
    depth = float(depth_cm)
    count = int(count)
    if count <= 0:
        raise ValueError("backdrop count must be a positive integer, got %r" % (count,))
    if radius <= 0.0:
        raise ValueError("ring_radius_cm must be positive, got %r" % (ring_radius_cm,))
    if depth <= 0.0:
        raise ValueError("backdrop depth_cm must be positive, got %r" % (depth_cm,))
    height_lo, height_hi = float(height_range_cm[0]), float(height_range_cm[1])
    if height_lo > height_hi:
        raise ValueError("height_range_cm must be [low, high], got %r" % (height_range_cm,))
    half_diag = math.hypot(x1 - x0, y1 - y0) / 2.0
    if radius < half_diag:
        raise ValueError(
            "ring_radius_cm %.3f is smaller than the world's half-diagonal %.3f; "
            "a backdrop inside the city is a bug, not a fallback" % (radius, half_diag))
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    step = 2.0 * math.pi / float(count)
    min_gap = (1.0 - 2.0 * 0.35) * step          # >= 0.3 * step
    half_gap = 0.5 * min_gap
    cap_angle = 0.95 * half_gap                  # safety margin vs touching
    width_cap = 2.0 * radius * math.tan(cap_angle)
    blocks = []
    for i in range(count):
        block_id = "block_%03d" % i
        fh = _frac(block_id, seed, "height")
        fa = _frac(block_id, seed, "angle")
        fw = _frac(block_id, seed, "width")
        fr = _frac(block_id, seed, "radius")
        theta = step * (i + (fa - 0.5) * 2.0 * 0.35)
        centre_radius = radius + depth / 2.0 + fr * depth / 2.0
        x = cx + centre_radius * math.cos(theta)
        y = cy + centre_radius * math.sin(theta)
        yaw = math.degrees(math.atan2(cy - y, cx - x)) % 360.0
        blocks.append({
            "id": block_id,
            "x": _f3(x), "y": _f3(y),
            "yaw": _f3(yaw),
            "width_cm": _f3(width_cap * (0.55 + 0.45 * fw)),
            "depth_cm": _f3(depth),
            "height_cm": _f3(height_lo + fh * (height_hi - height_lo)),
        })
    blocks.sort(key=lambda block: block["id"])
    return blocks


def fog_settings(bounds, *, visibility_fraction):
    """Atmospheric settings that hide the far edge.

    Fog is what makes a bounded world read as an unbounded one.  The numbers
    are derived from the world's own size, not typed constants: the cutoff is
    `visibility_fraction` of the world's diagonal (beyond it nothing may be
    visible), the start is 60% of that cutoff so the city interior (within
    half a diagonal) stays clear, and the density makes the exponential
    falloff 1 - exp(-density * d) reach 95% opacity at the cutoff.
    """
    x0, x1, y0, y1 = _bounds_numbers(bounds)
    fraction = float(visibility_fraction)
    if not (0.0 < fraction <= 1.0):
        raise ValueError("visibility_fraction must be in (0, 1], got %r"
                         % (visibility_fraction,))
    diagonal = math.hypot(x1 - x0, y1 - y0)
    cutoff = diagonal * fraction
    start = 0.6 * cutoff
    density = math.log(20.0) / (cutoff - start)
    return {"start_distance_cm": _f3(start),
            "fog_density": _f3(density),
            "cutoff_distance_cm": _f3(cutoff)}


def horizon_plan(spec, *, inner_margin_cm=1.0, width_cm=4000.0,
                 skirt_segments=16, ring_radius_cm=None, backdrop_count=48,
                 height_range_cm=(600.0, 1500.0), backdrop_depth_cm=120.0,
                 seed="horizon_v1", fog_visibility_fraction=0.9):
    """The whole horizon document: schema_version, params, counts, bounds,
    skirt, backdrop, fog.

    Deterministic: the same spec and params produce byte-identical
    json.dumps(..., sort_keys=True).  A ring_radius_cm below the world's
    half-diagonal is rejected rather than silently placing the skyline
    inside the city.
    """
    bounds = world_bounds(spec)
    x0, x1, y0, y1 = _bounds_numbers(bounds)
    margin = float(inner_margin_cm)
    width = float(width_cm)
    segments = int(skirt_segments)
    count = int(backdrop_count)
    depth = float(backdrop_depth_cm)
    height_lo, height_hi = float(height_range_cm[0]), float(height_range_cm[1])
    fraction = float(fog_visibility_fraction)
    if ring_radius_cm is None:
        outer_side = max((x1 - x0) / 2.0, (y1 - y0) / 2.0) + margin + width
        ring_radius = math.hypot(outer_side, outer_side) + 500.0
    else:
        ring_radius = float(ring_radius_cm)
    skirt = skirt_ring(bounds, inner_margin_cm=margin, width_cm=width,
                       segments=segments)
    backdrop = backdrop_blocks(bounds, ring_radius_cm=ring_radius, count=count,
                               height_range_cm=(height_lo, height_hi),
                               depth_cm=depth, seed=seed)
    fog = fog_settings(bounds, visibility_fraction=fraction)
    return {
        "schema_version": HORIZON_PLAN_VERSION,
        "params": {
            "inner_margin_cm": _f3(margin),
            "width_cm": _f3(width),
            "skirt_segments": segments,
            "ring_radius_cm": _f3(ring_radius),
            "backdrop_count": count,
            "height_range_cm": [_f3(height_lo), _f3(height_hi)],
            "backdrop_depth_cm": _f3(depth),
            "seed": seed,
            "fog_visibility_fraction": _f3(fraction),
        },
        "counts": {"skirt_rows": len(skirt), "backdrop_blocks": len(backdrop)},
        "bounds": bounds,
        "skirt": skirt,
        "backdrop": backdrop,
        "fog": fog,
    }
