"""Per-building order sheet for Epic's City Sample PCG building system.

This module emits **decisions, never geometry**.  For every city_layout
building slot it produces one order describing *where* a building goes, *how
tall* it is and *which style* it wears; a thin editor driver hands that order to
a PCG graph, and PCG makes the triangles, the vertices, the materials and the
mesh assets.  There are deliberately no triangles, no vertices, no materials
and no mesh paths anywhere in this file.

Two rules of this module were inherited from bugs that already bit the project
twice, so they are stated here rather than discovered again:

**Winding.**  ``footprint`` is always **counter-clockwise** in the right-handed
world (x east, y north, centimetres) frame: the shoelace sum
``sum(x_i * y_{i+1} - x_{i+1} * y_i)`` of the ring is **strictly positive**.
``street_life_inputs.building_footprint`` hands back the *clockwise* ring that
``_rect_corners`` emits (its lateral axis is ``t = (-sin yaw, cos yaw)`` and its
corner cycle runs ``(-t, -d) -> (-t, +d) -> (+t, +d) -> (+t, -d)``), so
:func:`_canonical_footprint` reverses any ring whose shoelace sum is negative
and then rotates it so the starting corner is the lexicographically smallest
``(x, y)``.  Every order therefore starts at a reproducible corner and every
order winds the same way, for any frontage yaw -- the rotation-free property of
the underlying rectangle frame (``det = +1`` for every yaw) is what makes that
possible.  This project has already paid twice for inconsistent corners: once
as a nested-loop "Z" that produced a self-intersecting bowtie
(``street_life_inputs._rect_corners`` documents the fix) and once as Z-ordered
roof corners.

**Closure.**  The polygon is emitted as a closed ring of ``len(ring) + 1``
``[x, y]`` pairs: the first corner is repeated as the last entry, so
``footprint[0] == footprint[-1]`` and ``footprint[:-1]`` is the cyclic corner
list.

Schema ``pcg_buildings_v1``.  Pure stdlib (``hashlib``/``math`` only), no
``import unreal``, deterministic (sha256 digests, no ``random``), floats routed
through :func:`_f3`.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Callable, Iterable, Sequence

SCHEMA_VERSION = "pcg_buildings_v1"

#: Winding convention for every emitted footprint (see module docstring).
WINDING = "counter-clockwise"

#: Storey height in cm used to turn a height into a level count when no style
#: resolver states one.  Matches ``building_kits``'s coarse storey snap.
DEFAULT_STOREY_CM = 350.0

#: Fallbacks that keep this module total when ``building_kits`` is unreachable
#: (``building_kits`` is the authority for both of them).
DEFAULT_LANDMARK_MIN_HEIGHT_CM = 5600.0
DEFAULT_CIVIC_FAMILY = "civic_stone"

#: Layout keys that may carry road data.  ``street_life_inputs.attach_road_spec``
#: stores the road spec under ``layout["spec"]``; the rest are conveniences for
#: hand-built layouts.
_ROAD_KEYS = ("spec", "road_spec", "roads", "road", "carriageway_lanes", "lanes")


# ---------------------------------------------------------------------------
# small numeric helpers (the project-wide 3-dp / sha256 conventions)
# ---------------------------------------------------------------------------


def _f3(v: float) -> float:
    """Round to 3 decimals (the project-wide float convention)."""
    return round(float(v) + 0.0, 3)


def _digest(*parts: Any) -> int:
    """Deterministic sha256 digest over ``parts`` (no ``random``)."""
    h = hashlib.sha256()
    for p in parts:
        h.update(repr(p).encode("utf-8"))
        h.update(b"\x1f")
    return int.from_bytes(h.digest()[:8], "big")


def _unit(*parts: Any) -> float:
    """Deterministic value in ``[0, 1)`` for ``parts``."""
    return _digest(*parts) / float(1 << 64)


# ---------------------------------------------------------------------------
# ring predicates: closure, winding, self-intersection, overlap
# ---------------------------------------------------------------------------


def _signed_area(ring: Sequence[Sequence[float]]) -> float:
    """Twice the signed area of an **open** ring of ``[x, y]`` pairs.

    Positive means counter-clockwise in the x-east/y-north frame, which is the
    convention every footprint in this module satisfies.
    """
    total = 0.0
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        total += x0 * y1 - x1 * y0
    return _f3(total)


def _as_pairs(points: Iterable[Any]) -> list[list[float]]:
    """``[{x, y} | (x, y) | [x, y]]`` -> ``[[x, y], ...]`` (3-dp floats)."""
    out: list[list[float]] = []
    for p in points:
        if isinstance(p, dict):
            out.append([_f3(p["x"]), _f3(p["y"])])
        else:
            out.append([_f3(p[0]), _f3(p[1])])
    return out


def _canonical_footprint(corners: Sequence[Any]) -> list[list[float]]:
    """One building footprint in the module winding convention.

    Takes whatever ring the single shared footprint helper produced (``{"x",
    "y"}`` dicts, as ``street_life_inputs.building_footprint`` returns), drops
    an accidental repeated closing point, reverses it when its signed area is
    negative, rotates the ring so the lexicographically smallest ``(x, y)``
    corner comes first, and closes it by repeating that first corner.  The
    result is counter-clockwise with a deterministic start for every yaw.
    """
    pts = _as_pairs(corners)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        raise ValueError("footprint needs at least 3 corners")
    if _signed_area(pts) < 0.0:
        pts.reverse()
    i0 = min(range(len(pts)), key=lambda i: (pts[i][0], pts[i][1]))
    pts = pts[i0:] + pts[:i0]
    return [list(p) for p in pts] + [list(pts[0])]


def _orient(ax: float, ay: float, bx: float, by: float,
            cx: float, cy: float) -> float:
    v = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    return 0.0 if v == 0.0 else (1.0 if v > 0.0 else -1.0)


def _segs_cross(a: Sequence[float], b: Sequence[float],
                c: Sequence[float], d: Sequence[float]) -> bool:
    """True when open segments ``ab`` and ``cd`` cross properly (touch = no)."""
    o1 = _orient(a[0], a[1], b[0], b[1], c[0], c[1])
    o2 = _orient(a[0], a[1], b[0], b[1], d[0], d[1])
    o3 = _orient(c[0], c[1], d[0], d[1], a[0], a[1])
    o4 = _orient(c[0], c[1], d[0], d[1], b[0], b[1])
    return o1 * o2 < 0.0 and o3 * o4 < 0.0


def _point_in_ring(px: float, py: float,
                   ring: Sequence[Sequence[float]]) -> bool:
    """Strict point-in-polygon (ray cast); a boundary point is not inside.

    The ray cast alone does NOT honour that promise: a vertex lying exactly on
    another ring's edge lands inside or outside depending on which side of the
    crossing test it falls, so two buildings that merely share a party wall got
    reported as overlapping. Adjacent slots on one block frontage abut by
    construction, so that made every neighbouring pair a false positive. Test
    the boundary explicitly first and call it outside.
    """
    n = len(ring)
    for i in range(n):
        ax, ay = ring[i - 1][0], ring[i - 1][1]
        bx, by = ring[i][0], ring[i][1]
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        if seg <= 0.0:
            continue
        t = ((px - ax) * dx + (py - ay) * dy) / seg
        if t < 0.0 or t > 1.0:
            continue
        cx, cy = ax + t * dx, ay + t * dy
        if (px - cx) ** 2 + (py - cy) ** 2 <= 1e-6:
            return False
    inside = False
    for i in range(n):
        x0, y0 = ring[i - 1][0], ring[i - 1][1]
        x1, y1 = ring[i][0], ring[i][1]
        if (y0 > py) != (y1 > py):
            xc = x0 + (py - y0) * (x1 - x0) / (y1 - y0)
            if px < xc:
                inside = not inside
    return inside


def _ring_self_intersects(ring: Sequence[Sequence[float]]) -> bool:
    """True for a bowtie or any crossing between non-adjacent edges."""
    n = len(ring)
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        for j in range(i + 1, n):
            if (j + 1) % n == i or (i + 1) % n == j:
                continue  # adjacent edges share an endpoint
            c, d = ring[j], ring[(j + 1) % n]
            if _segs_cross(a, b, c, d):
                return True
    return False


def _rings_overlap(a: Sequence[Sequence[float]],
                   b: Sequence[Sequence[float]]) -> bool:
    """True when two **open** rings share interior area.

    Edges that merely touch (a shared wall, a corner touch) do not count; a
    proper edge crossing or one ring's corner strictly inside the other does.
    """
    na, nb = len(a), len(b)
    for i in range(na):
        for j in range(nb):
            if _segs_cross(a[i], a[(i + 1) % na], b[j], b[(j + 1) % nb]):
                return True
    for p in a:
        if _point_in_ring(p[0], p[1], b):
            return True
    for p in b:
        if _point_in_ring(p[0], p[1], a):
            return True
    # Vertices alone miss the case where the rings are identical or one sits
    # wholly inside the other: every vertex then lies ON the other's boundary,
    # which the strict interior test correctly calls outside. A centroid is
    # strictly interior for these convex footprints, so it catches both.
    for ring, other in ((a, b), (b, a)):
        n = len(ring)
        if not n:
            continue
        cx = sum(pt[0] for pt in ring) / n
        cy = sum(pt[1] for pt in ring) / n
        if _point_in_ring(cx, cy, other):
            return True
    return False


# ---------------------------------------------------------------------------
# adapters onto the sibling modules (they own the rules; this module does not)
# ---------------------------------------------------------------------------


def _slots_of(layout: dict) -> list[dict]:
    """Slots of a ``city_layout_v1`` document (``building_slots.slots``)."""
    bs = layout.get("building_slots")
    if isinstance(bs, dict):
        slots = bs.get("slots")
    elif isinstance(bs, list):
        slots = bs
    else:
        slots = None
    if slots is None:
        slots = layout.get("slots")
    return list(slots or [])


def _slot_yaw_deg(slot: dict) -> float:
    """Slot yaw: ``yaw`` (the trusted city_layout field), alias ``yaw_deg``."""
    if slot.get("yaw") is not None:
        return float(slot["yaw"])
    if slot.get("yaw_deg") is not None:
        return float(slot["yaw_deg"])
    return 0.0


def _footprint_of(slot: dict, depth_cm: float) -> list[dict]:
    """``street_life_inputs.building_footprint`` -- the single footprint rule."""
    try:
        from ldyf.street_life_inputs import building_footprint
    except ImportError:  # pragma: no cover - script-mode import
        from street_life_inputs import building_footprint  # type: ignore
    return building_footprint(slot, depth_cm=depth_cm)


def _building_kits():
    try:
        from ldyf import building_kits
    except ImportError:  # pragma: no cover - script-mode import
        import building_kits  # type: ignore
    return building_kits


def _cars_lane_bands(spec: dict) -> list[list[list[float]]]:
    """Carriageway lane bands of a road spec, as open rings of ``[x, y]``.

    ``street_life_inputs._car_lane_bands`` is the project's authority on lane
    bands (a carriageway lane is one that disallows pedestrians) and is reused
    when present.  Only if it is unavailable does this module read an explicit
    ``carriageway_lanes``/``lanes``/``car_lanes`` list off the spec.
    """
    if not isinstance(spec, dict):
        return []
    try:
        from ldyf.street_life_inputs import _car_lane_bands
    except ImportError:  # pragma: no cover - script-mode import
        try:
            from street_life_inputs import _car_lane_bands  # type: ignore
        except ImportError:
            _car_lane_bands = None  # type: ignore
    if _car_lane_bands is not None:
        try:
            bands = _car_lane_bands(spec)
        except Exception:  # pragma: no cover - unexpected spec shape
            bands = None
        out = []
        for band in bands or []:
            ring = _as_pairs(band)
            if len(ring) > 1 and ring[0] == ring[-1]:
                ring = ring[:-1]
            if len(ring) >= 3:
                out.append(ring)
        if out:
            return out
    out = []
    for key in ("carriageway_lanes", "lanes", "car_lanes"):
        for band in spec.get(key) or []:
            ring = _as_pairs(band)
            if len(ring) > 1 and ring[0] == ring[-1]:
                ring = ring[:-1]
            if len(ring) >= 3:
                out.append(ring)
    return out


def _layout_lane_bands(layout: dict) -> list[list[list[float]]]:
    """Lane bands attached to a layout, if any.

    Returns ``[]`` when the layout carries no road data, which is why
    :func:`building_orders` copies any bands it does find into the document
    before ``validate_orders`` ever runs.
    """
    if not isinstance(layout, dict):
        return []
    for key in _ROAD_KEYS:
        spec = layout.get(key)
        if isinstance(spec, dict):
            bands = _cars_lane_bands(spec)
            if bands:
                return bands
            nested = spec.get("spec") or spec.get("road_spec")
            if isinstance(nested, dict):
                bands = _cars_lane_bands(nested)
                if bands:
                    return bands
        elif isinstance(spec, list) and spec:
            bands = _cars_lane_bands({key: spec})
            if bands:
                return bands
    return []


def _landmark_slot(layout: dict, seed: int) -> dict | None:
    """The slot ``building_kits`` would replace with the landmark.

    The landmark decision lives in ``building_kits`` (block nearest the layout
    centroid, tie broken by block id, then a digest pick among that block's
    slots).  It is **called**, not re-implemented.  ``None`` means "no blocks to
    decide from"; the caller then falls back to the first slot by id so the
    document still holds exactly one landmark.
    """
    pick = getattr(_building_kits(), "_pick_landmark_slot", None)
    if pick is None:  # pragma: no cover - building_kits always has it
        return None
    try:
        return pick(layout, seed)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# style resolution
# ---------------------------------------------------------------------------


def _style_module_resolver() -> Callable | None:
    """Resolver from a sibling ``ldyf.building_styles``, if it has landed.

    Looked up by name so this module does not block on that file; ``None`` when
    the module -- or a resolver entry point in it -- is missing.
    """
    try:
        from ldyf import building_styles  # type: ignore
    except ImportError:
        try:
            import building_styles  # type: ignore
        except ImportError:
            return None
    for name in ("resolve_style", "style_for", "resolve"):
        fn = getattr(building_styles, name, None)
        if callable(fn):
            return fn
    return None


def _fallback_style(family: str, height_cm: float) -> dict:
    """Deterministic placeholder style, used when no real resolver exists.

    ``building_styles`` (the module that maps a family plus a height onto a real
    City Sample style and level) has not landed yet, so ``style`` and
    ``rule_asset`` are logical ids, **not** invented asset paths; a driver must
    be handed a ``style_resolver`` before these are used for real geometry.
    """
    return {
        "style": "fallback_style::%s" % family,
        "rule_asset": "pcg_building_rule::%s" % family,
        "levels": max(1, int(round(float(height_cm) / DEFAULT_STOREY_CM))),
    }


def _call_resolver(resolver: Callable, family: str, height_cm: float) -> Any:
    """Call a style resolver, preferring keywords but accepting positionals."""
    try:
        return resolver(family=family, height_cm=height_cm)
    except TypeError:
        return resolver(family, height_cm)


def _resolve_style(resolver: Callable | None, family: str,
                   height_cm: float) -> tuple[dict, dict | None]:
    """``(style_record, style_limits_or_None)`` for one building.

    ``style_record`` always has ``style``, ``rule_asset`` and ``levels``.  A
    resolver may return a mapping with those keys (plus optional
    ``min_levels``/``max_levels``, or a two-item ``levels_range``) or a plain
    ``(style, levels)`` pair.  Limits are collected into the document so
    ``validate_orders`` can police a level range without being handed the
    resolver again.
    """
    if resolver is None:
        return _fallback_style(family, height_cm), None
    got = _call_resolver(resolver, family, height_cm)
    if got is None:
        return _fallback_style(family, height_cm), None
    if isinstance(got, dict):
        style = str(got.get("style") or got.get("style_name")
                    or "fallback_style::%s" % family)
        levels = got.get("levels", got.get("level_count"))
        if levels is None:
            levels = max(1, int(round(float(height_cm) / DEFAULT_STOREY_CM)))
        lo = got.get("min_levels", got.get("levels_min"))
        hi = got.get("max_levels", got.get("levels_max"))
        rng = got.get("levels_range")
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            lo = rng[0] if lo is None else lo
            hi = rng[1] if hi is None else hi
        limits = None
        if lo is not None and hi is not None:
            limits = {"min_levels": int(lo), "max_levels": int(hi)}
        return {
            "style": style,
            "rule_asset": str(got.get("rule_asset")
                              or "pcg_building_rule::%s" % style),
            "levels": max(1, int(round(float(levels)))),
        }, limits
    if isinstance(got, (list, tuple)) and len(got) >= 2:
        return {
            "style": str(got[0]),
            "rule_asset": (str(got[2]) if len(got) > 2
                           else "pcg_building_rule::%s" % (got[0],)),
            "levels": max(1, int(round(float(got[1])))),
        }, None
    raise TypeError("style_resolver returned %r" % (got,))


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def building_orders(layout: dict, *, depth_cm: float, seed: int,
                    style_resolver: Callable | None = None) -> dict:
    """One PCG building order per ``city_layout`` slot.

    Returns ``{"schema_version", "orders", "landmark_id", "counts"}`` plus the
    diagnostics the validator needs: ``carriageway_lanes`` (copied from the
    layout's road data when present, so ``validate_orders`` can spot a footprint
    sitting in a traffic lane) and ``style_limits`` (per style, the level range
    a ``style_resolver`` reported).  ``depth_cm`` and ``seed`` are echoed for
    the driver.

    Each order is exactly::

        {"id", "block_id", "footprint", "height_cm", "levels", "style",
         "rule_asset", "family", "role", "seed", "yaw_deg"}

    ``footprint`` is the closed counter-clockwise ring described in the module
    docstring.  ``yaw_deg`` is the slot's outward frontage normal, so a driver
    can face the building at the street instead of at the world axes.  Heights
    come from ``building_kits.massing_variation``, families from
    ``building_kits.assign_family``, and the single ``"landmark"`` role is the
    slot ``building_kits`` picks, lifted to the landmark minimum height and
    wearing the civic family.  The footprint depth used for massing is the
    ``depth_cm`` argument, not the slot's own ``depth_cm``, so massing and the
    footprint agree.

    Raises ``ValueError`` for a non-positive ``depth_cm`` or a layout with no
    building slots.
    """
    depth = float(depth_cm)
    if not depth > 0.0:
        raise ValueError("depth_cm must be positive, got %r" % (depth_cm,))
    slots = _slots_of(layout)
    if not slots:
        raise ValueError("layout has no building slots")

    kits = _building_kits()
    assign_family = getattr(kits, "assign_family", None)
    massing = getattr(kits, "massing_variation", None)
    landmark_min = float(getattr(kits, "LANDMARK_MIN_HEIGHT_CM",
                                 DEFAULT_LANDMARK_MIN_HEIGHT_CM))
    civic_family = str(getattr(kits, "CIVIC_FAMILY", DEFAULT_CIVIC_FAMILY))

    if style_resolver is None:
        style_resolver = _style_module_resolver()

    chosen = _landmark_slot(layout, int(seed))
    if chosen is None:
        chosen = sorted(slots, key=lambda s: str(s.get("slot_id")
                                                 or s.get("building_id")
                                                 or ""))[0]
    landmark_key = str(chosen.get("slot_id") or chosen.get("building_id") or "")

    orders: list[dict] = []
    limits: dict[str, dict] = {}
    for slot in slots:
        sid = str(slot.get("slot_id") or slot.get("building_id") or "b")
        block_id = str(slot.get("block_id") or "")
        is_landmark = sid == landmark_key
        family = (civic_family if is_landmark
                  else (assign_family(block_id, sid) if assign_family
                        else "fallback_family"))
        mass_in = dict(slot)
        mass_in["depth_cm"] = depth  # massing must see the depth actually used
        mass = massing(mass_in, seed=int(seed)) if massing else {}
        height = float(mass.get("height_cm") or depth)
        if is_landmark:
            height = max(height, landmark_min)
        height = _f3(height)
        style, got_limits = _resolve_style(style_resolver, family, height)
        if got_limits:
            limits[style["style"]] = got_limits
        corners = _footprint_of(slot, depth)
        orders.append({
            "id": sid,
            "block_id": block_id,
            "footprint": _canonical_footprint(corners),
            "height_cm": height,
            "levels": int(style["levels"]),
            "style": style["style"],
            "rule_asset": style["rule_asset"],
            "family": family,
            "role": "landmark" if is_landmark else "ordinary",
            "seed": _digest("pcg_order", int(seed), sid) % (1 << 31),
            "yaw_deg": _f3(_slot_yaw_deg(slot)),
        })

    orders.sort(key=lambda o: o["id"])
    landmark_id = next((o["id"] for o in orders if o["role"] == "landmark"),
                       None)
    doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "orders": orders,
        "landmark_id": landmark_id,
        "counts": {
            "orders": len(orders),
            "ordinary": sum(1 for o in orders if o["role"] == "ordinary"),
            "landmark": sum(1 for o in orders if o["role"] == "landmark"),
        },
        "depth_cm": depth,
        "seed": int(seed),
    }
    lanes = _layout_lane_bands(layout)
    if lanes:
        doc["carriageway_lanes"] = lanes
    if limits:
        doc["style_limits"] = limits
    return doc


def to_spline_points(order: dict) -> list:
    """The footprint as a PCG spline component's point list.

    Point order, stated so the geometry contract can be tested on its own: the
    returned list is the order's closed **counter-clockwise** ring as ``[x, y]``
    pairs, index 0 being the same reproducible start corner as the footprint and
    the final pair repeating index 0 to close the loop (``pts[-1] == pts[0]``).
    Drivers whose spline component wants unique control points plus a closed
    loop flag should drop the final pair and set that flag; the ring is then
    ``pts[:-1]``.
    """
    return _as_pairs(order["footprint"])


def validate_orders(doc: dict) -> list:
    """Problems with a ``pcg_buildings_v1`` document; empty means valid.

    Catches a footprint that is not closed, has fewer than 3 corners, has zero
    area, is wound clockwise (inconsistent with the module convention) or
    self-intersects (a bowtie); two footprints that overlap; a non-positive
    height; a level outside the range ``style_limits`` records for that style
    (only when a resolver supplied limits); more or fewer than one landmark; and
    a footprint lying on a carriageway lane carried by the document.
    """
    problems: list[str] = []
    orders = doc.get("orders")
    if not isinstance(orders, list) or not orders:
        return ["document has no orders"]
    if doc.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version is %r, expected %r"
                        % (doc.get("schema_version"), SCHEMA_VERSION))

    seen: set[str] = set()
    rings: list[tuple[str, list[list[float]]]] = []
    landmarks = [o for o in orders if o.get("role") == "landmark"]
    if len(landmarks) != 1:
        problems.append("expected exactly one landmark, found %d"
                        % len(landmarks))
    elif doc.get("landmark_id") != landmarks[0].get("id"):
        problems.append("landmark_id %r does not name the landmark order %r"
                        % (doc.get("landmark_id"), landmarks[0].get("id")))

    limits = doc.get("style_limits") or {}
    for order in orders:
        oid = str(order.get("id"))
        if oid in seen:
            problems.append("duplicate order id %r" % (oid,))
        seen.add(oid)
        fp = order.get("footprint")
        if not isinstance(fp, list) or len(fp) < 4:
            problems.append("order %s: footprint needs at least 3 corners plus "
                            "its closing point" % oid)
        else:
            first, last = _as_pairs([fp[0]])[0], _as_pairs([fp[-1]])[0]
            if first != last:
                problems.append("order %s: footprint is not closed "
                                "(first %r != last %r)" % (oid, first, last))
            ring = _as_pairs(fp[:-1] if first == last else fp)
            if len(ring) < 3:
                problems.append("order %s: footprint has fewer than 3 corners"
                                % oid)
            else:
                rings.append((oid, ring))
                area = _signed_area(ring)
                if abs(area) < 1e-9:
                    problems.append("order %s: footprint is degenerate "
                                    "(zero area)" % oid)
                if _ring_self_intersects(ring):
                    problems.append("order %s: footprint self-intersects "
                                    "(bowtie)" % oid)
                elif area < 0.0:
                    problems.append("order %s: footprint is wound clockwise "
                                    "(expected %s)" % (oid, WINDING))
        try:
            height = float(order.get("height_cm"))
        except (TypeError, ValueError):
            height = 0.0
        if not height > 0.0:
            problems.append("order %s: height_cm must be positive, got %r"
                            % (oid, order.get("height_cm")))
        levels = order.get("levels")
        if not isinstance(levels, int) or isinstance(levels, bool) or levels < 1:
            problems.append("order %s: levels must be a positive int, got %r"
                            % (oid, levels))
        limit = limits.get(order.get("style"))
        if limit is not None and isinstance(levels, int):
            lo = int(limit.get("min_levels", 0))
            hi = int(limit.get("max_levels", 1 << 30))
            if not lo <= levels <= hi:
                problems.append("order %s: %d levels is outside what style %r "
                                "supports (%d..%d)"
                                % (oid, levels, order.get("style"), lo, hi))
        yaw = order.get("yaw_deg")
        if not isinstance(yaw, (int, float)) or isinstance(yaw, bool) \
                or not math.isfinite(float(yaw)):
            problems.append("order %s: yaw_deg must be a finite number, got %r"
                            % (oid, yaw))

    for i in range(len(rings)):
        for j in range(i + 1, len(rings)):
            (ia, ra), (ib, rb) = rings[i], rings[j]
            if _rings_overlap(ra, rb):
                problems.append("footprints of %s and %s overlap" % (ia, ib))

    for oid, ring in rings:
        for k, lane in enumerate(doc.get("carriageway_lanes") or []):
            if _rings_overlap(ring, _as_pairs(lane)):
                problems.append("footprint of %s lies on carriageway lane %d"
                                % (oid, k))
                break
    return problems
