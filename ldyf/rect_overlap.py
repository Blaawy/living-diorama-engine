"""The ONE cardinal rectangle-overlap predicate of the grouped-building path.

``sgd_grouping.validate_groups``, the grouping tests and the Block V2 machine
gate (``block_gate``) all call :func:`overlap_metrics` / :func:`find_overlaps`
from here, so "does A overlap B" has exactly one answer everywhere.  Two
implementations is how the first grouping landed blind: the validator and the
measurement that caught it disagreed about which way a rectangle lies.

Everything here works on world-axis bounds ``(x_min, x_max, y_min, y_max)`` in
centimetres.  Grouped buildings are cardinal (yaw a multiple of 90 degrees), so
a world-axis box IS the rectangle; :func:`cardinal_bounds` refuses any other
yaw rather than silently boxing a rotated rectangle.

The rule
--------

* a **positive-area intersection** -- more than ``eps`` on BOTH world axes -- is
  an overlap;
* touching, or anything within ``eps``, is **not** an overlap (a shared party
  wall is legal);
* an overlap is reported with both ids and its ``width_cm`` (extent on world
  x), ``depth_cm`` (extent on world y) and ``area_cm2``.

Which way a rectangle lies
--------------------------

An order's ``yaw_deg`` is its OUTWARD frontage normal.  ``width_cm`` runs along
the frontage (the tangent) and ``length_cm`` / ``depth_cm`` recedes along the
normal -- the convention of ``sgd_buildings.rect_corners``.  So an east-facing
rectangle (yaw 0) is ``length_cm`` wide on world x and ``width_cm`` on world y.

Epic's ``PCG_Bldg_SGD_test`` lays its ``Width`` parameter along the actor's
local **X** -- the normal, not the tangent.  That was measured on the live
block (``EVIDENCE/PHASE_02/block_v2/live_before_axis_fix.json``): every
building came out turned a quarter turn, up to 1686 cm outside its block.
:func:`engine_bounds` reproduces that legacy as-built box so the regression can
hold the old geometry to the same predicate; ``sgd_buildings.graph_parameters``
is the fix (it hands ``Width`` the depth and ``Length`` the frontage).

Pure stdlib, no ``import unreal``, no ``random``.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

#: Geometry tolerance in centimetres.  Matches the project's 3-decimal rounding.
GEOM_EPS_CM = 0.01

Bounds = tuple[float, float, float, float]

#: Yaws a grouped rectangle may carry, after ``% 360``.
CARDINAL_YAWS: tuple[float, ...] = (0.0, 90.0, 180.0, 270.0)


def _f3(value: Any) -> float:
    return float(round(float(value), 3))


def _cardinal_yaw(yaw: Any) -> float:
    """``yaw % 360`` snapped to a cardinal, or ``ValueError``."""
    value = float(yaw) % 360.0
    for cardinal in CARDINAL_YAWS:
        if abs(value - cardinal) <= 1e-6 or abs(value - cardinal - 360.0) <= 1e-6:
            return cardinal
    raise ValueError("yaw %r is not cardinal" % (yaw,))


def _dimensions(rect: Mapping[str, Any]) -> tuple[float, float, float, float, float]:
    """``(cx, cy, frontage, depth, cardinal yaw)`` of an order or a group."""
    center = rect.get("center")
    if isinstance(center, (str, bytes)) or not isinstance(center, Sequence) \
            or len(center) != 2:
        raise ValueError("rectangle has no usable center: %r" % (center,))
    depth = rect.get("length_cm", rect.get("depth_cm"))
    try:
        cx, cy = float(center[0]), float(center[1])
        frontage, depth = float(rect.get("width_cm")), float(depth)
    except (TypeError, ValueError):
        raise ValueError("rectangle has non-numeric geometry")
    if not (frontage > 0.0 and depth > 0.0):
        raise ValueError("rectangle dimensions must be positive, got %r x %r"
                         % (frontage, depth))
    return cx, cy, frontage, depth, _cardinal_yaw(rect.get("yaw_deg"))


def _box(cx: float, cy: float, on_x: float, on_y: float) -> Bounds:
    return (_f3(cx - on_x / 2.0), _f3(cx + on_x / 2.0),
            _f3(cy - on_y / 2.0), _f3(cy + on_y / 2.0))


def cardinal_bounds(rect: Mapping[str, Any]) -> Bounds:
    """World bounds of an order or group: frontage on the tangent, depth inward.

    Accepts ``length_cm`` (an order) or ``depth_cm`` (a group).  ``ValueError``
    for a missing centre, a non-positive dimension or a non-cardinal yaw.
    """
    cx, cy, frontage, depth, yaw = _dimensions(rect)
    if yaw in (0.0, 180.0):          # normal on world x, frontage on world y
        return _box(cx, cy, depth, frontage)
    return _box(cx, cy, frontage, depth)


def engine_bounds(rect: Mapping[str, Any]) -> Bounds:
    """The LEGACY as-built box: ``width_cm`` handed to the grammar as ``Width``.

    The grammar lays ``Width`` along the actor's local X, i.e. along the yaw
    normal, so this is :func:`cardinal_bounds` turned a quarter turn about the
    same centre.  Kept only so regressions can measure what the unfixed driver
    actually built; nothing in production calls it.
    """
    cx, cy, frontage, depth, yaw = _dimensions(rect)
    if yaw in (0.0, 180.0):
        return _box(cx, cy, frontage, depth)
    return _box(cx, cy, depth, frontage)


def as_bounds(item: Any) -> Bounds:
    """``item`` as bounds: a 4-sequence passes through, a mapping is a rectangle."""
    if isinstance(item, Mapping):
        return cardinal_bounds(item)
    if isinstance(item, (str, bytes)) or not isinstance(item, Sequence) \
            or len(item) != 4:
        raise ValueError("not a rectangle or (x_min, x_max, y_min, y_max): %r"
                         % (item,))
    x0, x1, y0, y1 = (float(v) for v in item)
    if not (x1 > x0 and y1 > y0):
        raise ValueError("bounds are not a positive rectangle: %r" % (item,))
    return (x0, x1, y0, y1)


def overlap_metrics(a: Any, b: Any, eps: float = GEOM_EPS_CM) -> dict | None:
    """The positive-area intersection of two rectangles, or ``None``.

    ``None`` for separated rectangles and for rectangles that merely touch
    (within ``eps`` on either axis).  Otherwise ``{"width_cm", "depth_cm",
    "area_cm2"}`` -- the intersection's extent on world x, on world y, and its
    area.
    """
    ax0, ax1, ay0, ay1 = as_bounds(a)
    bx0, bx1, by0, by1 = as_bounds(b)
    on_x = min(ax1, bx1) - max(ax0, bx0)
    on_y = min(ay1, by1) - max(ay0, by0)
    if on_x <= eps or on_y <= eps:
        return None
    return {"width_cm": _f3(on_x), "depth_cm": _f3(on_y),
            "area_cm2": _f3(on_x * on_y)}


def separation_cm(a: Any, b: Any) -> float:
    """The gap between two rectangles on their best separating world axis.

    Zero when they touch, negative only when they overlap.
    """
    ax0, ax1, ay0, ay1 = as_bounds(a)
    bx0, bx1, by0, by1 = as_bounds(b)
    return _f3(max(max(ax0, bx0) - min(ax1, bx1),
                   max(ay0, by0) - min(ay1, by1)))


def find_overlaps(items: Iterable[tuple[Any, Any]],
                  eps: float = GEOM_EPS_CM) -> list[dict]:
    """Every overlapping pair among ``(id, rectangle-or-bounds)`` items.

    Each report is ``{"a", "b", "width_cm", "depth_cm", "area_cm2"}`` with
    ``a`` / ``b`` the two ids in input order.  ``ValueError`` if any item is not
    a comparable rectangle: an unreadable rectangle must never pass as "no
    overlap".
    """
    boxes = [(key, as_bounds(item)) for key, item in items]
    out: list[dict] = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            hit = overlap_metrics(boxes[i][1], boxes[j][1], eps)
            if hit is not None:
                out.append({"a": boxes[i][0], "b": boxes[j][0], **hit})
    return out


def contains(outer: Any, inner: Any, eps: float = GEOM_EPS_CM) -> bool:
    """Is ``inner`` entirely inside ``outer`` (edges may touch, within ``eps``)?"""
    ox0, ox1, oy0, oy1 = as_bounds(outer)
    ix0, ix1, iy0, iy1 = as_bounds(inner)
    return (ix0 >= ox0 - eps and ix1 <= ox1 + eps
            and iy0 >= oy0 - eps and iy1 <= oy1 + eps)
