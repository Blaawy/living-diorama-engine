"""Group ``city_layout_v1`` building slots into RECTANGULAR city-block masses.

The production path builds a building from ``Width`` / ``Length`` / ``Height`` /
``ShapeGrammarDefinition`` and can therefore only make **rectangles**.  The first
converted block produced 28 small towers and was rejected: from above it reads as
narrow fins, not a city block.  This module changes the *massing* only -- no
building architecture, no roads, no sidewalks, no SUMO geometry, no mesh paths,
no vertices, no ``import unreal``, no ``random`` (sha256 digests only).

Input is the real ``city_layout_v1`` slot list (``slot_id, block_id, kit, x, y,
yaw, width_cm, depth_cm, frontage_index``); output is an
``sgd_buildings_v1``-shaped document of grouped rectangular orders the existing
driver consumes unchanged (see :func:`grouped_orders`).

Geometry, once, so the rest of the module reads plainly
------------------------------------------------------

``yaw`` is the slot's OUTWARD frontage normal -- ``(cos yaw, sin yaw)`` points at
the street -- so the mass recedes *inward* along ``-(cos yaw, sin yaw)``.  For
``block_1_1`` (bbox x 22040..37960, y -37960..-22040) that gives four sides:

=========  ======  ==================  =========  ==========
side       yaw     frontage line       inward     along axis
=========  ======  ==================  =========  ==========
south      270     ``y = y_min``       ``+y``     x
east       0       ``x = x_max``       ``-x``     y
north      90      ``y = y_max``       ``-y``     x
west       180     ``x = x_min``       ``+x``     y
=========  ======  ==================  =========  ==========

Yaw is normalised with ``yaw % 360`` before use, so ``-90`` and ``270`` land on
the same side.  ``frontage_index`` is unique per slot (a slot ORDER index, never
a side id) and is not consulted for side assignment.

A group's rectangle runs from the frontage line INWARD by ``depth_cm`` and spans
``width_cm`` along the frontage, matching ``sgd_buildings._derive_rectangle``'s
convention (``u`` = outward normal, extents in the rectangle's own frame).  So
the emitted order's ``width_cm`` is the merged frontage span and ``length_cm``
the depth.

Corner ownership: the one rule that makes perpendicular sides safe
------------------------------------------------------------------

Each of a block's four corners is owned by exactly ONE of its two adjacent sides
(:func:`corner_owner` returns that side's normalised yaw):

* the OWNING side runs its rectangle out to the corner: the corner-end group of
  the owning side has its span end set to the block corner coordinate;
* the NON-OWNING side starts after an inset of ``owner_depth + clearance``: its
  corner-end group is TRIMMED to that inset.

Worked with the brief's numbers: south side, an east side of depth 4000 owning
the SE corner, so ``37960 - 4000 - 200 = 33760`` bounds the south rectangle.
South slots past that (f5 centred 33040, f6 centred 35040) stay *sources* of
that group -- their design intent is folded in -- but the rectangle does not span
them.  Slots define design intent, not immutable boundaries: a rectangle may be
trimmed, inset or resized, and every slot is still attributed to exactly one
group, whether or not the rectangle covers it.

The rule is chosen so a perpendicular intersection is geometrically impossible
rather than merely unobserved: the two rectangles meeting at a corner are
separated on the *non-owning* side's own axis (its projection can only end at or
before ``corner - owner_depth - clearance``, while the owner's projection reaches
the corner), so no separating-axis test can find them overlapping.  The trim is a
no-op when the non-owning side's slots already stop short of the inset line --
which, on the real ``city_layout``, several of them do.

The owner's depth is shrunk -- depth first, as the brief requires -- when the
inset would otherwise leave the non-owning side a footprint below
:data:`MIN_GROUP_DIMENSION_CM`, and that reduction is recorded in the *owner's*
``trimmed`` field.  A group can be a corner group at exactly one corner, so one
group's depth is capped at most once.

Stability of :func:`corner_owner`: ownership alternates around the block, so each
side owns exactly one of the two corners it touches (symmetric massing, no side
dominating a block) and every corner's owner is one of its own adjacent sides.
The alternation is rotated one step when
``sha256("sgd_grouping_corner", block_id, seed)`` is odd, which lets neighbouring
blocks hand a shared boundary to a different side.  It reads nothing but
``(block_id, seed)`` and fixed tables -- not slot order, not slot contents, not
dict iteration order -- so it cannot change when a layout is edited elsewhere.

Trimming and clearance
----------------------

* two neighbouring groups of one side split their shared boundary and each back
  off half of a per-block clearance drawn from :data:`CLEARANCE_CM` (150 or
  300 cm), so no two rectangles in a block are closer than 150 cm;
* a corner-driven trim -- or a corner-driven depth reduction -- is recorded in
  the group's ``trimmed`` field; ``None`` when nothing was reduced;
* depths start inside :data:`DEPTH_BAND_CM` (3000..4500 cm) and are shrunk FIRST
  if a rectangle would collide with an unrelated one.  The width is shrunk
  second, and only once the depth floor is reached.

Reference walk-through (``block_1_1``, all four sides carry 7 slots)
-------------------------------------------------------------------

Real slot spans from ``city_layout.json`` (``depth_cm`` 1500 everywhere, widths
2000 with a 1920 last slot on each side):

* south (yaw ``-90``, ``y = -37960``): f0..f6 span x 22040 -> 36000, so the ring
  stops 1960 short of ``x_max``;
* east (yaw ``0``, ``x = 37960``): f7..f13 span y -37960 -> -24000;
* north (yaw ``90``, ``y = -22040``): f14..f20 span x 24000 -> 37960;
* west (yaw ``180``, ``x = 22040``): f21..f27 span y -36000 -> -22040.

A 7-slot side splits 4+3 (or 3+4, digest-chosen), so each side yields two groups
and an ordinary block composes 8 buildings.  ``block_1_1`` also carries the
landmark: its own run of :data:`LANDMARK_GROUP_SLOTS` = 2 slots that is never
merged into a generic rectangle, plus the remaining 5 slots chunked 3+2, so that
block composes 9 -- inside the 7-9 target.  With the SE corner owned by the south
side and an east group of depth 4000 owning it in the brief's example, the south
group that ends the run extends from 36000 out to 37960 while the east group's
start is inset to ``-33760 = -37960 + 4000 + 200``: the two rectangles are
separated on the east side's axis, and the corner slot f7 (centre -36960) is
trimmed out of the east rectangle while staying a source of its group.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Mapping, Sequence

try:  # pragma: no cover - package import path
    from ldyf import rect_overlap as _rect
    from ldyf import sgd_buildings as _sgd
except ImportError:  # pragma: no cover - script-mode import path
    import rect_overlap as _rect  # type: ignore
    import sgd_buildings as _sgd  # type: ignore


SCHEMA_VERSION = "sgd_grouping_v1"

#: Span lengths, in slots, that a group prefers (see :func:`_chunk_sizes`).
GROUP_SIZE_CHOICES: tuple[int, ...] = (3, 4)

#: Inward depth of a group's rectangle, in cm, measured from the frontage line.
DEPTH_BAND_CM: tuple[float, float] = (3000.0, 4500.0)

#: Gap two unrelated rectangles must keep, in cm.  :func:`_clearance_cm` picks
#: one end of this band per block, deterministically.
CLEARANCE_CM: tuple[float, float] = (150.0, 300.0)

#: Slots the landmark's own mass spans (the landmark slot plus one neighbour).
LANDMARK_GROUP_SLOTS = 2

#: Concrete depths drawn from inside :data:`DEPTH_BAND_CM`.
DEPTH_CHOICES_CM: tuple[float, ...] = (3000.0, 3750.0, 4500.0)

#: ``(tier, hint cm)`` -- the hint height handed to ``family_for`` so the role
#: band, and hence the family, actually varies.  A raw 1600-2400 cm request would
#: put every group in the low-rise band, where ``SFD`` stands alone.
TIER_HINTS_CM: tuple[tuple[str, float], ...] = (
    ("low", 1700.0), ("mid", 2800.0), ("tall", 6500.0))

#: The landmark is always this much taller than the tallest ordinary group of its
#: block, so it stays the block's landmark after clamping.
LANDMARK_MARGIN_CM = 500.0

#: Smallest rectangle this layer emits on either axis, in cm.  This layer's own
#: choice, of the same order as ``sgd_buildings.DEFAULT_FOOTPRINT_DEPTH_CM``: a
#: shape grammar given a degenerate footprint emits nothing.
MIN_GROUP_DIMENSION_CM = 1200.0

#: Step used when a collision forces a rectangle to shrink.
SHRINK_STEP_CM = 50.0

#: Safety margin, in cm, when a depth is capped so a trimmed group stays buildable.
_CAP_MARGIN_CM = 1.0
_SHRINK_GUARD = 400

#: Geometry tolerance in centimetres; the authoritative predicate's own.
GEOM_EPS_CM = _rect.GEOM_EPS_CM

#: Sides in the order the corner alternation walks them.
SIDE_ORDER: tuple[str, ...] = ("south", "east", "north", "west")

#: Normalised yaw of each side (its outward frontage normal).
SIDE_YAW: dict[str, float] = {"south": 270.0, "east": 0.0,
                              "north": 90.0, "west": 180.0}

#: Sides whose frontage runs along x.
HORIZONTAL_SIDES: tuple[str, ...] = ("south", "north")

#: Corners, counter-clockwise from the south-east one.
CORNER_ORDER: tuple[str, ...] = ("SE", "NE", "NW", "SW")

#: The two sides adjacent to each corner (the horizontal one first).
CORNER_SIDES: dict[str, tuple[str, str]] = {
    "SE": ("south", "east"),
    "NE": ("north", "east"),
    "NW": ("north", "west"),
    "SW": ("south", "west"),
}

#: Inward unit vector per side (``-(cos yaw, sin yaw)``).
INWARD: dict[str, tuple[float, float]] = {
    "south": (0.0, 1.0), "east": (-1.0, 0.0),
    "north": (0.0, -1.0), "west": (1.0, 0.0)}

_CARDINALS: tuple[tuple[float, float, str], ...] = (
    (1.0, 0.0, "east"), (0.0, 1.0, "north"),
    (-1.0, 0.0, "west"), (0.0, -1.0, "south"))

_LETTER_SIDE = {"s": "south", "n": "north", "e": "east", "w": "west"}

_GROUP_KEYS = ("group_id", "block_id", "side_yaw", "slot_ids", "center",
               "width_cm", "depth_cm", "yaw_deg", "role", "trimmed")

_ORDER_KEYS = ("id", "block_id", "center", "width_cm", "length_cm", "yaw_deg",
               "height_cm", "requested_height_cm", "family", "sgd_asset", "role",
               "seed")


# ---------------------------------------------------------------------------
# small numeric / hashing helpers (stdlib only; sha256 only, never random)
# ---------------------------------------------------------------------------


def _f3(value: Any) -> float:
    """Round cm to three decimals (millimetres), as the project does."""
    return float(round(float(value), 3))


def _digest(*parts: Any) -> int:
    """A stable non-negative digest of ``parts`` (sha256; never ``random``)."""
    blob = hashlib.sha256()
    for part in parts:
        blob.update(repr(part).encode("utf-8"))
        blob.update(b"\x00")
    return int.from_bytes(blob.digest()[:8], "big")


def _require_seed(seed: Any) -> int:
    """``seed`` as a positive int; ``ValueError`` otherwise."""
    if seed is None or isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an int, got %r" % (seed,))
    if seed <= 0:
        raise ValueError("seed must be positive, got %r" % (seed,))
    return int(seed)


def _positive(value: Any, what: str) -> float:
    """``value`` as a positive float; ``ValueError`` for anything else."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be a positive number, got %r" % (what, value))
    if not number > 0.0:
        raise ValueError("%s must be positive, got %r" % (what, value))
    return number


def _as_pair(value: Any) -> tuple[float, float] | None:
    """``value`` as a 2-float tuple, or ``None`` if it is not one."""
    if isinstance(value, str) or not isinstance(value, Sequence):
        return None
    if len(value) != 2:
        return None
    try:
        return float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# layout reading (mirrors pcg_buildings._slots_of; this module adds no rule)
# ---------------------------------------------------------------------------


def _slots_of(layout: Mapping[str, Any]) -> list[dict]:
    """Slots of a ``city_layout_v1`` document (``building_slots.slots``)."""
    if not isinstance(layout, Mapping):
        raise ValueError("layout must be a mapping, got %r" % (type(layout),))
    bs = layout.get("building_slots")
    if isinstance(bs, Mapping):
        slots = bs.get("slots")
    elif isinstance(bs, list):
        slots = bs
    else:
        slots = None
    if slots is None:
        slots = layout.get("slots")
    return [s for s in (slots or []) if isinstance(s, Mapping)]


def _block_records(layout: Mapping[str, Any]) -> list[dict]:
    """Every block record the layout carries, whichever container holds it."""
    if not isinstance(layout, Mapping):
        return []
    for container in (layout, layout.get("building_slots")):
        if isinstance(container, Mapping):
            blocks = container.get("blocks")
            if isinstance(blocks, list):
                return [b for b in blocks if isinstance(b, Mapping)]
    return []


def _block_record(layout: Mapping[str, Any], block_id: str) -> dict | None:
    for record in _block_records(layout):
        if str(record.get("id") or record.get("block_id") or "") == block_id:
            return record
    return None


def _slot_id(slot: Mapping[str, Any]) -> str:
    return str(slot.get("slot_id") or slot.get("building_id") or "b")


def _slot_block(slot: Mapping[str, Any]) -> str:
    return str(slot.get("block_id") or "")


def _slot_yaw_deg(slot: Mapping[str, Any]) -> float:
    """Slot yaw: ``yaw`` (the trusted field), alias ``yaw_deg``."""
    for key in ("yaw", "yaw_deg"):
        if slot.get(key) is not None:
            return float(slot[key])
    raise ValueError("slot %r has no yaw" % (slot.get("slot_id"),))


def _yaw_norm(yaw: float) -> float:
    """Normalise a yaw to ``[0, 360)`` so ``-90`` and ``270`` coincide."""
    return float(yaw) % 360.0


def _side_of_yaw(yaw: float) -> str:
    """The side a yaw points at, by nearest cardinal outward normal."""
    rad = math.radians(_yaw_norm(yaw))
    ux, uy = math.cos(rad), math.sin(rad)
    return max(_CARDINALS, key=lambda c: c[0] * ux + c[1] * uy)[2]


def _side_of(slot: Mapping[str, Any]) -> str:
    return _side_of_yaw(_slot_yaw_deg(slot))


def _along(slot: Mapping[str, Any], side: str) -> float:
    """The slot's coordinate along its side's frontage."""
    axis = "x" if side in HORIZONTAL_SIDES else "y"
    if slot.get(axis) is None:
        raise ValueError("slot %r has no %r" % (_slot_id(slot), axis))
    return float(slot[axis])


def _slot_width_cm(slot: Mapping[str, Any]) -> float:
    """The slot's frontage width; ``ValueError`` when zero or negative."""
    return _positive(slot.get("width_cm"), "slot %s width_cm" % _slot_id(slot))


def _slot_depth_cm(slot: Mapping[str, Any]) -> float:
    """The slot's depth; ``ValueError`` when zero or negative."""
    return _positive(slot.get("depth_cm"), "slot %s depth_cm" % _slot_id(slot))


# ---------------------------------------------------------------------------
# block bounds
# ---------------------------------------------------------------------------


def _bounds_from_mapping(bbox: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    """``(x_min, x_max, y_min, y_max)`` from a bounds-like mapping."""
    def pick(*keys: str) -> float | None:
        for key in keys:
            if bbox.get(key) is None:
                continue
            try:
                return float(bbox[key])
            except (TypeError, ValueError):
                return None
        return None

    x_min = pick("x_min", "min_x", "xmin", "left")
    x_max = pick("x_max", "max_x", "xmax", "right")
    y_min = pick("y_min", "min_y", "ymin", "bottom")
    y_max = pick("y_max", "max_y", "ymax", "top")
    if x_min is None or x_max is None or y_min is None or y_max is None:
        return None
    if not x_max > x_min or not y_max > y_min:
        raise ValueError("block bounds are not a positive rectangle: %r" % (bbox,))
    return x_min, x_max, y_min, y_max


def _block_bounds(record: Mapping[str, Any], slots: list[dict],
                  block_id: str) -> tuple[float, float, float, float]:
    """The block's legal region: bbox, then polygon, then the slots themselves."""
    if isinstance(record, Mapping):
        for key in ("bbox", "bounds", "rect", "aabb"):
            nested = record.get(key)
            if isinstance(nested, Mapping):
                found = _bounds_from_mapping(nested)
                if found is not None:
                    return found
        polygon = record.get("polygon")
        if isinstance(polygon, list) and len(polygon) >= 3:
            points = [p for p in (_as_pair(p) for p in polygon) if p is not None]
            if points:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                return (min(xs), max(xs), min(ys), max(ys))
    if slots:
        lo_x = hi_x = lo_y = hi_y = None
        for slot in slots:
            x, y = float(slot.get("x", 0.0)), float(slot.get("y", 0.0))
            half = _slot_width_cm(slot) / 2.0
            depth = _slot_depth_cm(slot)
            rad = math.radians(_slot_yaw_deg(slot))
            ux, uy = math.cos(rad), math.sin(rad)
            tx, ty = -uy, ux
            for along, inward in ((-half, 0.0), (half, 0.0), (0.0, 0.0),
                                  (0.0, -depth)):
                px = x + tx * along + ux * inward
                py = y + ty * along + uy * inward
                lo_x = px if lo_x is None else min(lo_x, px)
                hi_x = px if hi_x is None else max(hi_x, px)
                lo_y = py if lo_y is None else min(lo_y, py)
                hi_y = py if hi_y is None else max(hi_y, py)
        if None not in (lo_x, hi_x, lo_y, hi_y) and hi_x > lo_x and hi_y > lo_y:
            return lo_x, hi_x, lo_y, hi_y
    raise ValueError("block %r carries no usable bounds" % (block_id,))


def _frontage_coord(side: str, bounds: tuple[float, float, float, float]) -> float:
    """The frontage line of ``side`` (an edge of the block region)."""
    x_min, x_max, y_min, y_max = bounds
    return {"south": y_min, "north": y_max, "east": x_max, "west": x_min}[side]


def _along_min(side: str, bounds: tuple[float, float, float, float]) -> float:
    x_min, x_max, y_min, y_max = bounds
    return x_min if side in HORIZONTAL_SIDES else y_min


def _along_max(side: str, bounds: tuple[float, float, float, float]) -> float:
    x_min, x_max, y_min, y_max = bounds
    return x_max if side in HORIZONTAL_SIDES else y_max


def _corner_coords(corner: str,
                   bounds: tuple[float, float, float, float]) -> tuple[float, float]:
    """``(x, y)`` of a canonical SE/NE/NW/SW corner."""
    key = _corner_key(corner)
    x_min, x_max, y_min, y_max = bounds
    cx = x_max if "E" in key else x_min
    cy = y_min if "S" in key else y_max
    return cx, cy


def _corner_along(corner: str, side: str,
                  bounds: tuple[float, float, float, float]) -> float:
    """The corner's coordinate on ``side``'s own along-frontage axis."""
    cx, cy = _corner_coords(corner, bounds)
    return cx if side in HORIZONTAL_SIDES else cy


def _corner_at_low(corner: str, side: str,
                   bounds: tuple[float, float, float, float]) -> bool:
    """Is the corner at the low end of ``side``'s along axis?"""
    return abs(_corner_along(corner, side, bounds)
               - _along_min(side, bounds)) < 1e-6


# ---------------------------------------------------------------------------
# corners
# ---------------------------------------------------------------------------


def _corner_key(corner: Any) -> str:
    """Canonical corner key from a flexible spelling ("SE", "es", "south-east")."""
    if not isinstance(corner, str):
        raise ValueError("corner must be a string, got %r" % (corner,))
    sides = sorted({_LETTER_SIDE[ch] for ch in corner.lower() if ch in "snew"})
    for key, pair in CORNER_SIDES.items():
        if sides == sorted(pair):
            return key
    raise ValueError("unknown corner %r (expected one of %s)"
                     % (corner, ", ".join(CORNER_ORDER)))


def corner_owner(block_id: Any, corner: Any, *, seed: int) -> float:
    """The normalised yaw of the side that OWNS ``corner`` of ``block_id``.

    Ownership alternates around the block (:data:`CORNER_ORDER` against
    :data:`SIDE_ORDER`), so every side owns exactly one of the two corners it
    touches and every corner's owner is one of its own adjacent sides.  The
    alternation is rotated one step when
    ``sha256("sgd_grouping_corner", block_id, seed)`` is odd, so neighbouring
    blocks can hand a shared boundary to a different side while no side ever owns
    both of its corners.

    Stable because it depends only on ``(block_id, seed)`` and the fixed tables
    above -- never on slot order, slot contents or dict iteration order -- so a
    layout edit elsewhere cannot move an owner.

    ``ValueError`` for an unknown ``corner`` and for a non-positive or
    non-integer ``seed``.
    """
    seed = _require_seed(seed)
    key = _corner_key(corner)
    offset = _digest("sgd_grouping_corner", str(block_id), seed) % 2
    index = CORNER_ORDER.index(key)
    return SIDE_YAW[SIDE_ORDER[(index + offset) % len(SIDE_ORDER)]]


# ---------------------------------------------------------------------------
# grouping
# ---------------------------------------------------------------------------


def _clearance_cm(block_id: str, seed: int) -> float:
    """This block's clearance: one end of :data:`CLEARANCE_CM`."""
    lo, hi = CLEARANCE_CM
    return lo if _digest("sgd_grouping_clearance", block_id, seed) % 2 == 0 else hi


def _depth_cm(group_id: str, seed: int) -> float:
    """This group's starting depth: one of :data:`DEPTH_CHOICES_CM`."""
    return DEPTH_CHOICES_CM[_digest("sgd_group_depth", group_id, seed)
                            % len(DEPTH_CHOICES_CM)]


def _chunk_sizes(count: int, *, key: str, seed: int) -> list[int]:
    """Split ``count`` slots into group sizes of about :data:`GROUP_SIZE_CHOICES`.

    At most four slots per group, so a side of seven becomes 4+3 and a side of
    five becomes 3+2.  Which size comes first is drawn from a digest, so a block
    shows both 3-slot and 4-slot spans.  Digest-driven only.
    """
    if count <= 0:
        return []
    chunks = min(count, max(1, (count + 3) // 4))
    base, extra = divmod(count, chunks)
    sizes = [base + (1 if i < extra else 0) for i in range(chunks)]
    if len(sizes) > 1 and _digest("sgd_group_chunk", key, seed) % 2:
        sizes.sort(reverse=True)
    return sizes


def _slices(slots: list[dict], sizes: list[int]) -> list[list[dict]]:
    """``slots`` cut into consecutive runs of ``sizes``."""
    out, start = [], 0
    for size in sizes:
        out.append(slots[start:start + size])
        start += size
    return [chunk for chunk in out if chunk]


def _kit_module() -> Any:
    """The project's kit module, or ``None`` where it cannot be imported.

    This layer imports on the stdlib alone, so a kit module that only exists
    inside the editor degrades to ``None`` instead of failing the import.
    """
    try:
        try:
            from ldyf import building_kits as kits  # type: ignore
        except ImportError:
            import building_kits as kits  # type: ignore
        return kits
    except Exception:  # pragma: no cover - only where the kit needs the editor
        return None


def _landmark_slot_id(layout: Mapping[str, Any], block_id: str,
                      seed: int) -> str | None:
    """The slot id the kit picks as the landmark, when it lies in this block.

    ``pcg_buildings._landmark_slot`` / ``building_kits._pick_landmark_slot`` own
    that decision and are CALLED, never re-implemented.  ``None`` means "this
    block carries no landmark".
    """
    kits = _kit_module()
    pick = getattr(kits, "_pick_landmark_slot", None) if kits is not None else None
    if not callable(pick):
        return None
    try:
        chosen = pick(layout, int(seed))
    except Exception:  # pragma: no cover - the kit refused the layout
        return None
    if not isinstance(chosen, Mapping) or _slot_block(chosen) != block_id:
        return None
    return _slot_id(chosen)


def _slot_request_cm(slot: Mapping[str, Any], seed: int) -> float:
    """The height massing asks of one slot, in cm.

    ``building_kits.massing_variation`` is the project's own request source and is
    used whenever it can be imported, exactly as ``sgd_buildings.sgd_orders``
    uses it.  Without it, the layout's own request range -- 1600-2400 cm per
    ``HEIGHT_BAND_CM``'s note -- is reproduced deterministically from the slot id.
    """
    kits = _kit_module()
    massing = getattr(kits, "massing_variation", None) if kits is not None else None
    if callable(massing):
        try:
            mass = massing(dict(slot), seed=int(seed)) or {}
            height = float(mass.get("height_cm") or 0.0)
            if height > 0.0:
                return _f3(height)
        except Exception:  # pragma: no cover - the kit refused the slot
            pass
    return _f3(1600.0 + 100.0 * (_digest("sgd_slot_request", _slot_id(slot), seed) % 9))


def _side_runs(side: str, ordered: list[dict], *, block_id: str, seed: int,
               landmark_id: str | None) -> list[list[dict]]:
    """The slot runs of ONE side, in along-frontage order.

    Without the landmark on this side: :func:`_chunk_sizes` (7 slots -> 4+3).
    With it: the landmark keeps its own run of :data:`LANDMARK_GROUP_SLOTS` slots
    -- itself plus the neighbour nearer the run's start -- which is never merged
    into a generic rectangle, and the slots on either side of it are chunked
    separately.
    """
    ids = [_slot_id(s) for s in ordered]
    if landmark_id is None or landmark_id not in ids:
        return _slices(ordered, _chunk_sizes(len(ordered), seed=seed,
                                             key="%s:%s" % (block_id, side)))
    index = ids.index(landmark_id)
    take = min(LANDMARK_GROUP_SLOTS, len(ordered))
    start = max(0, min(index - 1 if index >= 1 else 0, len(ordered) - take))
    parts = ((ordered[:start], "head"), (ordered[start:start + take], None),
             (ordered[start + take:], "tail"))
    runs: list[list[dict]] = []
    for part, name in parts:
        if not part:
            continue
        if name is None:
            runs.append(part)
            continue
        runs.extend(_slices(part, _chunk_sizes(len(part), seed=seed,
                                              key="%s:%s:%s" % (block_id, side, name))))
    return runs


def _chunk(block_id: str, side: str, index: int, slots: list[dict], seed: int) -> dict:
    """One side-run as a working chunk (span, depth, sources, role)."""
    group_id = "%s:%s:%d" % (block_id, side, index)
    lo = hi = None
    for slot in slots:
        centre = _along(slot, side)
        half = _slot_width_cm(slot) / 2.0
        lo = centre - half if lo is None else min(lo, centre - half)
        hi = centre + half if hi is None else max(hi, centre + half)
    if lo is None or hi is None or not hi > lo:
        raise ValueError("group %r has a degenerate frontage span" % (group_id,))
    return {"group_id": group_id, "block_id": block_id, "side": side,
            "slot_ids": [_slot_id(s) for s in slots],
            "lo": _f3(lo), "hi": _f3(hi), "depth": _depth_cm(group_id, seed),
            "trimmed": None}


def _center_of(side: str, along_mid: float, depth: float,
               bounds: tuple[float, float, float, float]) -> list[float]:
    """The centre of ``side``'s rectangle at ``along_mid`` with ``depth``.

    The rectangle's near edge is the frontage line and it recedes inward along
    ``INWARD[side]``, so its centre sits half a depth inside the block.
    """
    i_x, i_y = INWARD[side]
    frontage = _frontage_coord(side, bounds)
    if side in HORIZONTAL_SIDES:
        return [_f3(along_mid + i_x * depth / 2.0),
                _f3(frontage + i_y * depth / 2.0)]
    return [_f3(frontage + i_x * depth / 2.0),
            _f3(along_mid + i_y * depth / 2.0)]


def _rect_of(chunk: Mapping[str, Any], bounds: tuple[float, float, float, float]) -> dict:
    """A chunk as the ``rects_overlap``-ready rectangle of its side."""
    side = str(chunk["side"])
    return {"center": _center_of(side,
                                 (float(chunk["lo"]) + float(chunk["hi"])) / 2.0,
                                 float(chunk["depth"]), bounds),
            "width_cm": _f3(float(chunk["hi"]) - float(chunk["lo"])),
            "length_cm": _f3(float(chunk["depth"])),
            "yaw_deg": _f3(SIDE_YAW[side])}


def _corner_chunk(chunks: Sequence[dict], corner: str, side: str,
                  bounds: tuple[float, float, float, float]) -> dict | None:
    """The group of ``side`` that touches ``corner`` (the run at that end)."""
    if not chunks:
        return None
    if _corner_at_low(corner, side, bounds):
        return min(chunks, key=lambda c: (c["lo"], c["group_id"]))
    return max(chunks, key=lambda c: (c["hi"], c["group_id"]))


def _group_sort_key(group: Mapping[str, Any]) -> tuple:
    """Order groups by side, then along the frontage."""
    side = _side_of_yaw(float(group["side_yaw"]))
    centre = _as_pair(group["center"]) or (0.0, 0.0)
    along = centre[0] if side in HORIZONTAL_SIDES else centre[1]
    return (SIDE_ORDER.index(side), along, str(group["group_id"]))


def group_slots(layout: Mapping[str, Any], block_id: Any, *, seed: int) -> list[dict]:
    """Group one block into deterministic, contiguous rectangular masses.

    The original frontage slots are provenance/design intent.  Each seven-slot
    side becomes two contiguous 3/4-slot groups.  If a group contains the
    project-selected landmark slot it becomes the landmark mass; no head/tail
    slots are merged across it.  Corner ownership is geometric: an owner reaches
    the corner, while the perpendicular non-owner is inset by the maximum depth
    on the owner side plus this block's deterministic clearance.
    """
    seed = _require_seed(seed)
    block_id = str(block_id)
    record = _block_record(layout, block_id)
    block_slots = [s for s in _slots_of(layout) if _slot_block(s) == block_id]
    if not block_slots:
        raise ValueError("block %r has no slots" % block_id)

    bounds = _block_bounds(record or {}, block_slots, block_id)
    clearance = _clearance_cm(block_id, seed)
    landmark_id = _landmark_slot_id(layout, block_id, seed)

    by_side: dict[str, list[dict]] = {}
    for slot in block_slots:
        side = _side_of(slot)
        _slot_width_cm(slot)
        _slot_depth_cm(slot)
        by_side.setdefault(side, []).append(slot)
    per_side: dict[str, list[dict]] = {}
    for side in SIDE_ORDER:
        ordered = sorted(by_side.get(side, []),
                         key=lambda s: (_along(s, side), _slot_id(s)))
        if not ordered:
            continue
        sizes = _chunk_sizes(len(ordered), key="%s:%s" % (block_id, side), seed=seed)
        runs = _slices(ordered, sizes)
        chunks = []
        for index, run in enumerate(runs):
            chunk = _chunk(block_id, side, index, run, seed)
            chunk["role"] = ("landmark" if landmark_id is not None
                             and landmark_id in chunk["slot_ids"] else "ordinary")
            chunks.append(chunk)
        per_side[side] = chunks

    end_corners = {
        "south": ("SW", "SE"),
        "east": ("SE", "NE"),
        "north": ("NW", "NE"),
        "west": ("SW", "NW"),
    }

    def owner_side(corner: str) -> str:
        return _side_of_yaw(corner_owner(block_id, corner, seed=seed))

    def owner_max_depth(corner: str) -> float:
        chunks = per_side.get(owner_side(corner), [])
        return max((float(c["depth"]) for c in chunks), default=0.0)
    for side in SIDE_ORDER:
        chunks = per_side.get(side, [])
        if not chunks:
            continue
        low_corner, high_corner = end_corners[side]
        legal_lo = _along_min(side, bounds)
        legal_hi = _along_max(side, bounds)
        low_inset = high_inset = 0.0

        if owner_side(low_corner) != side:
            low_inset = owner_max_depth(low_corner) + clearance
            legal_lo += low_inset
        if owner_side(high_corner) != side:
            high_inset = owner_max_depth(high_corner) + clearance
            legal_hi -= high_inset

        gaps = clearance * max(0, len(chunks) - 1)
        usable = legal_hi - legal_lo - gaps
        weights = [len(c["slot_ids"]) for c in chunks]
        total_weight = float(sum(weights))
        widths = [usable * weight / total_weight for weight in weights]
        if usable <= 0.0 or any(width < MIN_GROUP_DIMENSION_CM
                                for width in widths):
            raise ValueError(
                "block %s side %s cannot fit %d valid groups in %.3f cm"
                % (block_id, side, len(chunks), usable))

        cursor = legal_lo
        for index, (chunk, width) in enumerate(zip(chunks, widths)):
            chunk["lo"] = _f3(cursor)
            chunk["hi"] = _f3(legal_hi if index == len(chunks) - 1
                               else cursor + width)
            cursor = float(chunk["hi"]) + clearance
            notes = []
            if index == 0 and low_inset:
                notes.append({"corner": low_corner, "inset_cm": _f3(low_inset)})
            if index == len(chunks) - 1 and high_inset:
                notes.append({"corner": high_corner, "inset_cm": _f3(high_inset)})
            chunk["trimmed"] = (
                {"reason": "rectangular non-owner corner inset", "insets": notes}
                if notes else None)

    groups = []
    for side in SIDE_ORDER:
        for chunk in per_side.get(side, []):
            width = _f3(float(chunk["hi"]) - float(chunk["lo"]))
            depth = _f3(chunk["depth"])
            if width < MIN_GROUP_DIMENSION_CM:
                raise ValueError("group %r is a sliver (%.3f cm)"
                                 % (chunk["group_id"], width))
            if not DEPTH_BAND_CM[0] <= depth <= DEPTH_BAND_CM[1]:
                raise ValueError("group %r depth %.3f left production band"
                                 % (chunk["group_id"], depth))
            center = _center_of(
                side, (float(chunk["lo"]) + float(chunk["hi"])) / 2.0,
                depth, bounds)
            groups.append({
                "group_id": chunk["group_id"],
                "block_id": block_id,
                "side_yaw": _f3(SIDE_YAW[side]),
                "slot_ids": list(chunk["slot_ids"]),
                "center": center,
                "width_cm": width,
                "depth_cm": depth,
                "yaw_deg": _f3(SIDE_YAW[side]),
                "role": chunk["role"],
                "trimmed": chunk["trimmed"],
            })

    # Fail closed: construction should make both conditions true by design.
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            hit = rect_overlap_metrics(groups[i], groups[j])
            if hit is not None:
                raise ValueError(
                    "grouping overlap %s/%s width=%s depth=%s area=%s"
                    % (groups[i]["group_id"], groups[j]["group_id"],
                       hit["width_cm"], hit["depth_cm"], hit["area_cm2"]))
            gap = rect_separation_cm(groups[i], groups[j])
            if gap < CLEARANCE_CM[0] - GEOM_EPS_CM:
                raise ValueError(
                    "grouping clearance %s/%s is %.3f cm"
                    % (groups[i]["group_id"], groups[j]["group_id"], gap))

    groups.sort(key=_group_sort_key)
    return groups

# ---------------------------------------------------------------------------
# grouped orders
# ---------------------------------------------------------------------------


def _family_and_hint(group_id: str, seed: int, avoid: str | None,
                     landmark: bool) -> tuple[str, str, float]:
    """``(family, tier, hint)`` for one group.

    Tiers are tried in a digest-rotated order and the first whose family differs
    from ``avoid`` (the previous group of the same side) wins, so two groups
    adjacent along a side never share a family.  ``avoid`` is always reachable:
    every band except the low-rise one offers two candidates, and the low-rise
    family is never the family of a mid or tall tier.
    """
    offset = _digest("sgd_group_tier", group_id, seed) % len(TIER_HINTS_CM)
    rotation = TIER_HINTS_CM[offset:] + TIER_HINTS_CM[:offset]
    if landmark:
        tier, hint = rotation[0]
        return _sgd.family_for(group_id, hint, seed, landmark=True), tier, hint
    family, tier, hint = None, rotation[0][0], rotation[0][1]
    for tier, hint in rotation:
        family = _sgd.family_for(group_id, hint, seed, avoid=avoid)
        if family != avoid:
            break
    return family, tier, hint


def _slot_requests_cm(layout: Mapping[str, Any], seed: int) -> dict[str, float]:
    """Every slot's requested height, in cm, keyed by slot id."""
    return {_slot_id(slot): _slot_request_cm(slot, seed) for slot in _slots_of(layout)}


def grouped_orders(layout: Mapping[str, Any], block_id: Any, *, seed: int) -> dict:
    """The grouped ``sgd_buildings_v1``-shaped order document for one block.

    The document is what the existing driver already consumes::

        {"schema_version", "orders", "landmark_id", "counts", "clamps",
         "style_minimum_cm", "seed", "groups"}

    and each order is exactly the key set it reads::

        {"id", "block_id", "center", "width_cm", "length_cm", "yaw_deg",
         "height_cm", "requested_height_cm", "family", "sgd_asset", "role",
         "seed"}

    ``width_cm`` is the group's merged frontage span and ``length_cm`` its depth
    (``group_slots``'s ``depth_cm``).  A group's requested height is the tallest
    request among its slots, floored by its tier hint -- so the family varies at
    all -- and every height goes through ``sgd_buildings.clamp_height``, the only
    place a height changes.  The landmark keeps ``role == "landmark"`` and family
    ``NYG`` and is made taller than every ordinary group of its block by
    ``LANDMARK_MARGIN_CM``.  ``ValueError`` as for :func:`group_slots`.
    """
    seed = _require_seed(seed)
    block_id = str(block_id)
    groups = group_slots(layout, block_id, seed=seed)
    requests = _slot_requests_cm(layout, seed)
    previous: dict[float, str] = {}
    orders: list[dict] = []
    clamps: list[dict] = []
    landmark_group: dict | None = None
    ordinary_top = 0.0

    for group in groups:
        group_id = group["group_id"]
        is_landmark = group["role"] == "landmark"
        side_yaw = float(group["side_yaw"])
        family, _tier_name, hint = _family_and_hint(group_id, seed,
                                                    previous.get(side_yaw),
                                                    is_landmark)
        if not is_landmark:
            previous[side_yaw] = family
        wanted = [hint] + [requests[sid] for sid in group["slot_ids"]
                           if sid in requests]
        requested = _f3(max(wanted))
        if is_landmark:
            landmark_group = group
            continue
        clamp = _sgd.clamp_height(family, requested)
        if clamp["clamped"]:
            clamps.append({"id": group_id, "block_id": block_id, "family": family,
                           "requested_cm": clamp["requested_cm"],
                           "height_cm": clamp["height_cm"],
                           "minimum_cm": clamp["minimum_cm"]})
        ordinary_top = max(ordinary_top, float(clamp["height_cm"]))
        orders.append(_order(group, family, clamp, seed))

    if landmark_group is not None:
        group_id = landmark_group["group_id"]
        family, _tier_name, _hint = _family_and_hint(group_id, seed, None, True)
        production_target = float(_sgd.HEIGHT_BAND_CM[family][1])
        requested = _f3(max(LANDMARK_MARGIN_CM + ordinary_top,
                            float(_sgd.LANDMARK_FLOOR_CM),
                            production_target))
        clamp = _sgd.clamp_height(family, requested)
        if clamp["clamped"]:
            clamps.append({"id": group_id, "block_id": block_id, "family": family,
                           "requested_cm": clamp["requested_cm"],
                           "height_cm": clamp["height_cm"],
                           "minimum_cm": clamp["minimum_cm"]})
        orders.append(_order(landmark_group, family, clamp, seed))

    orders.sort(key=lambda o: o["id"])
    clamps.sort(key=lambda c: c["id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "orders": orders,
        "landmark_id": next((o["id"] for o in orders
                             if o["role"] == "landmark"), None),
        "counts": {
            "orders": len(orders),
            "ordinary": sum(1 for o in orders if o["role"] == "ordinary"),
            "landmark": sum(1 for o in orders if o["role"] == "landmark"),
            "groups": len(groups),
            "families": {fam: sum(1 for o in orders if o["family"] == fam)
                         for fam in sorted(_sgd.SGD_PALETTE)
                         if any(o["family"] == fam for o in orders)},
        },
        "clamps": clamps,
        "style_minimum_cm": {fam: _sgd.minimum_for(fam)
                             for fam in sorted(_sgd.SGD_PALETTE)},
        "seed": int(seed),
        "groups": groups,
    }


def _order(group: Mapping[str, Any], family: str, clamp: Mapping[str, Any],
           seed: int) -> dict:
    """One group as the ``sgd_buildings_v1`` order the driver consumes."""
    return {
        "id": str(group["group_id"]),
        "block_id": str(group["block_id"]),
        "center": [float(group["center"][0]), float(group["center"][1])],
        "width_cm": _f3(group["width_cm"]),
        "length_cm": _f3(group["depth_cm"]),
        "yaw_deg": _f3(group["yaw_deg"]),
        "height_cm": _f3(clamp["height_cm"]),
        "requested_height_cm": _f3(clamp["requested_cm"]),
        "family": family,
        "sgd_asset": _sgd.sgd_asset_path(family),
        "role": group["role"],
        "seed": _digest("sgd_group_order", seed, str(group["group_id"])) % (1 << 31),
    }


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def group_corners(group: Mapping[str, Any]) -> list[tuple[float, float]] | None:
    """The four ``(x, y)`` corners of an order or group rectangle, or ``None``.

    ``sgd_buildings.rect_corners`` is the project's corner rule; this adapter maps
    a group's ``depth_cm`` onto the ``length_cm`` it expects.
    """
    rect = {"center": group.get("center"), "width_cm": group.get("width_cm"),
            "length_cm": group.get("length_cm", group.get("depth_cm")),
            "yaw_deg": group.get("yaw_deg")}
    if _as_pair(rect["center"]) is None:
        return None
    try:
        corners = _sgd.rect_corners(rect)
    except (KeyError, TypeError, ValueError):
        return None
    out = []
    for corner in corners:
        pair = _as_pair(corner)
        if pair is None:
            return None
        out.append(pair)
    return out


def rect_overlap_metrics(a: Mapping[str, Any], b: Mapping[str, Any],
                         eps: float = GEOM_EPS_CM) -> dict[str, float] | None:
    """``rect_overlap.overlap_metrics`` -- the one authoritative predicate."""
    return _rect.overlap_metrics(a, b, eps)


def rect_separation_cm(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    """``rect_overlap.separation_cm`` -- gap on the best separating axis."""
    return _rect.separation_cm(a, b)


def overlap_report(items: Any) -> list[dict]:
    """Every overlapping pair, as ``{"a", "b", "width_cm", "depth_cm", "area_cm2"}``.

    ``items`` is a grouped document (its ``orders`` are compared), a list of
    orders / groups, or ``(id, rectangle-or-bounds)`` pairs.  This is
    ``rect_overlap.find_overlaps`` and nothing else, so ``validate_groups``, the
    tests and the Block V2 machine gate report the same pairs with the same
    numbers.  ``ValueError`` for a rectangle that cannot be compared.
    """
    if isinstance(items, Mapping):
        items = items.get("orders") or []
    pairs = []
    for item in items:
        if isinstance(item, Mapping):
            pairs.append((item.get("id", item.get("group_id")), item))
        else:
            pairs.append((item[0], item[1]))
    return _rect.find_overlaps(pairs)


def validate_groups(doc: Mapping[str, Any], layout: Mapping[str, Any],
                    block_id: Any) -> list:
    """Every problem this layer claims to prevent; an empty list means valid.

    Claims checked: the schema tag; the order and group key sets; every order and
    group belongs to ``block_id``; positive dimensions, at least
    ``MIN_GROUP_DIMENSION_CM`` on either axis and never deeper than
    ``DEPTH_BAND_CM[1]``; palette families only, ``NYG`` landmark-only;
    ``sgd_asset`` matching the family; heights at or above the family's measured
    ``STYLE_MIN_HEIGHT_CM`` and never below the request; exactly one landmark,
    ``NYG``, taller than every ordinary order of the block; every source slot
    attributed to exactly one group and no slot left over; no two rectangles
    overlapping (``rects_overlap``); every rectangle inside the block region; yaw
    values on the four cardinal sides; no two groups adjacent along a side
    sharing a family; counts and ``clamps`` consistent with the orders; and, for
    a block of at least 24 slots, 7-9 buildings.
    """
    problems: list[str] = []
    if not isinstance(doc, Mapping):
        return ["document is not a mapping: %r" % (type(doc).__name__,)]
    block_id = str(block_id)
    if doc.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version is %r, expected %r"
                        % (doc.get("schema_version"), SCHEMA_VERSION))
    orders = doc.get("orders")
    groups = doc.get("groups")
    if not isinstance(orders, list):
        problems.append("orders is not a list: %r" % (type(orders).__name__,))
        orders = []
    if not isinstance(groups, list):
        problems.append("groups is not a list: %r" % (type(groups).__name__,))
        groups = []

    for group in groups:
        if not isinstance(group, Mapping):
            problems.append("group is not a mapping: %r" % (group,))
            continue
        gid = group.get("group_id")
        missing = [key for key in _GROUP_KEYS if key not in group]
        if missing:
            problems.append("group %r lacks keys %s" % (gid, missing))
        if str(group.get("block_id")) != block_id:
            problems.append("group %r is not in block %s" % (gid, block_id))
        if _as_pair(group.get("center")) is None:
            problems.append("group %r has no usable center" % (gid,))
        for key in ("width_cm", "depth_cm"):
            try:
                value = _positive(group.get(key), "group %s %s" % (gid, key))
            except ValueError as exc:
                problems.append(str(exc))
                continue
            if value < MIN_GROUP_DIMENSION_CM - 1e-6:
                problems.append("group %r %s %s is below the SGD minimum %s"
                                % (gid, key, value, MIN_GROUP_DIMENSION_CM))
        if group.get("yaw_deg") not in tuple(SIDE_YAW.values()):
            problems.append("group %r yaw_deg %r is not a cardinal side yaw"
                            % (gid, group.get("yaw_deg")))
        if group.get("side_yaw") not in tuple(SIDE_YAW.values()):
            problems.append("group %r side_yaw %r is not a cardinal side yaw"
                            % (gid, group.get("side_yaw")))
        if group.get("role") not in ("ordinary", "landmark"):
            problems.append("group %r role %r is unknown" % (gid, group.get("role")))
        if not group.get("slot_ids"):
            problems.append("group %r has no slots" % (gid,))

    for order in orders:
        if not isinstance(order, Mapping):
            problems.append("order is not a mapping: %r" % (order,))
            continue
        oid = order.get("id")
        missing = [key for key in _ORDER_KEYS if key not in order]
        if missing:
            problems.append("order %r lacks keys %s" % (oid, missing))
        if str(order.get("block_id")) != block_id:
            problems.append("order %r is not in block %s" % (oid, block_id))
        if order.get("role") not in ("ordinary", "landmark"):
            problems.append("order %r role %r is unknown" % (oid, order.get("role")))
        family = order.get("family")
        if family not in _sgd.SGD_PALETTE:
            problems.append("order %r family %r is outside SGD_PALETTE"
                            % (oid, family))
        else:
            if family == _sgd.LANDMARK_FAMILY and order.get("role") != "landmark":
                problems.append("order %r wears the landmark-only family %s as %r"
                                % (oid, _sgd.LANDMARK_FAMILY, order.get("role")))
            if order.get("sgd_asset") != _sgd.sgd_asset_path(family):
                problems.append("order %r sgd_asset %r does not match family %s"
                                % (oid, order.get("sgd_asset"), family))
            minimum = _sgd.minimum_for(family)
            if float(order.get("height_cm") or 0.0) + 1e-9 < minimum:
                problems.append("order %r height_cm %r is below %s's minimum %s"
                                % (oid, order.get("height_cm"), family, minimum))
        try:
            width = _positive(order.get("width_cm"), "order %s width_cm" % oid)
            length = _positive(order.get("length_cm"), "order %s length_cm" % oid)
            height = _positive(order.get("height_cm"), "order %s height_cm" % oid)
            requested = _positive(order.get("requested_height_cm"),
                                  "order %s requested_height_cm" % oid)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        for key, value in (("width_cm", width), ("length_cm", length)):
            if value < MIN_GROUP_DIMENSION_CM - 1e-6:
                problems.append("order %r %s %s is below the SGD minimum %s"
                                % (oid, key, value, MIN_GROUP_DIMENSION_CM))
        if length > DEPTH_BAND_CM[1] + 1e-6:
            problems.append("order %r length_cm %s is deeper than the band %s"
                            % (oid, length, DEPTH_BAND_CM[1]))
        if height + 1e-9 < requested:
            problems.append("order %r height_cm %s is below its request %s"
                            % (oid, height, requested))
        if _as_pair(order.get("center")) is None:
            problems.append("order %r has no usable center" % (oid,))
        if order.get("yaw_deg") not in tuple(SIDE_YAW.values()):
            problems.append("order %r yaw_deg %r is not a cardinal side yaw"
                            % (oid, order.get("yaw_deg")))

    # -- the landmark ---------------------------------------------------------
    landmarks = [o for o in orders if isinstance(o, Mapping)
                 and o.get("role") == "landmark"]
    if len(landmarks) > 1:
        problems.append("%d orders claim the landmark role" % len(landmarks))
    # The landmark is not optional where the layout puts it: the project's own
    # pick (never re-implemented here) names the block that must carry it.
    doc_seed = doc.get("seed")
    if isinstance(doc_seed, int) and not isinstance(doc_seed, bool) and doc_seed > 0:
        wanted_slot = _landmark_slot_id(layout, block_id, doc_seed)
        if wanted_slot is not None and not landmarks:
            problems.append("block %s must carry the landmark (slot %r) but no "
                            "order has the landmark role" % (block_id, wanted_slot))
        if wanted_slot is None and landmarks:
            problems.append("block %s carries a landmark order %r but the layout "
                            "puts the landmark elsewhere"
                            % (block_id, landmarks[0].get("id")))
        if wanted_slot is not None:
            holders = [g.get("group_id") for g in groups if isinstance(g, Mapping)
                       and wanted_slot in [str(s) for s in (g.get("slot_ids") or [])]]
            roles = [g.get("role") for g in groups if isinstance(g, Mapping)
                     and g.get("group_id") in holders]
            if roles != ["landmark"]:
                problems.append("landmark slot %r is held by %r with role %r, "
                                "expected exactly one landmark group"
                                % (wanted_slot, holders, roles))
    else:
        problems.append("seed is %r, expected a positive int" % (doc_seed,))
    ids = [o.get("id") for o in orders if isinstance(o, Mapping)]
    for kind, seen_ids in (("order", ids),
                           ("group", [g.get("group_id") for g in groups
                                      if isinstance(g, Mapping)])):
        for dup in sorted({str(i) for i in seen_ids if seen_ids.count(i) > 1}):
            problems.append("duplicate %s id %r" % (kind, dup))
    for missing_order in sorted({str(g.get("group_id")) for g in groups
                                 if isinstance(g, Mapping)} - {str(i) for i in ids}):
        problems.append("group %r has no matching order" % (missing_order,))
    if doc.get("landmark_id") is not None and doc["landmark_id"] not in ids:
        problems.append("landmark_id %r is not an order id" % (doc.get("landmark_id"),))
    if landmarks:
        if landmarks[0].get("id") != doc.get("landmark_id"):
            problems.append("landmark_id %r is not the landmark order %r"
                            % (doc.get("landmark_id"), landmarks[0].get("id")))
        if landmarks[0].get("family") != _sgd.LANDMARK_FAMILY:
            problems.append("landmark order %r family is %r, expected %s"
                            % (landmarks[0].get("id"), landmarks[0].get("family"),
                               _sgd.LANDMARK_FAMILY))
        landmark_height = float(landmarks[0].get("height_cm") or 0.0)
        target = float(_sgd.HEIGHT_BAND_CM[_sgd.LANDMARK_FAMILY][1])
        if landmark_height < 0.90 * target - GEOM_EPS_CM:
            problems.append("landmark %r height %s is below 90%% of target %s"
                            % (landmarks[0].get("id"), landmark_height, target))
        ordinary = [o for o in orders if isinstance(o, Mapping)
                    and o.get("role") == "ordinary"]
        if ordinary:
            top = max(float(o.get("height_cm") or 0.0) for o in ordinary)
            if landmark_height <= top:
                problems.append("landmark %r is %s cm, not taller than the block's "
                                "tallest ordinary %s cm"
                                % (landmarks[0].get("id"), landmark_height, top))

    # -- every slot attributed to exactly one group ---------------------------
    block_slots = [s for s in _slots_of(layout) if _slot_block(s) == block_id]
    known = {_slot_id(s) for s in block_slots}
    seen: dict[str, str] = {}
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        for slot_id in (group.get("slot_ids") or []):
            slot_id = str(slot_id)
            if slot_id not in known:
                problems.append("group %r claims slot %r, which is not in block %s"
                                % (group.get("group_id"), slot_id, block_id))
            if slot_id in seen:
                problems.append("slot %r is attributed to both %r and %r"
                                % (slot_id, seen[slot_id], group.get("group_id")))
            seen[slot_id] = str(group.get("group_id"))
    for slot_id in sorted(known - set(seen)):
        problems.append("slot %r is attributed to no group" % (slot_id,))

    # -- provenance: a group's slots are one contiguous run of its own side ---
    side_runs: dict[str, list[str]] = {}
    for slot in block_slots:
        try:
            side_runs.setdefault(_side_of(slot), []).append(slot)
        except ValueError:
            continue
    order_on_side = {
        side: [_slot_id(s) for s in sorted(
            items, key=lambda s, side=side: (_along(s, side), _slot_id(s)))]
        for side, items in side_runs.items()}
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        try:
            side = _side_of_yaw(float(group.get("side_yaw")))
        except (TypeError, ValueError):
            continue
        run = order_on_side.get(side, [])
        mine = [str(s) for s in (group.get("slot_ids") or []) if str(s) in known]
        if any(s not in run for s in mine):
            problems.append("group %r holds slots that are not on its %s side"
                            % (group.get("group_id"), side))
            continue
        positions = sorted(run.index(s) for s in mine)
        if positions and positions != list(range(positions[0], positions[-1] + 1)):
            problems.append("group %r slots are not a contiguous run of the %s side"
                            % (group.get("group_id"), side))

    # -- geometry: authoritative overlap/clearance + order/group consistency --
    rects = [(o.get("id"), o) for o in orders if isinstance(o, Mapping)]
    group_by_id = {g.get("group_id"): g for g in groups if isinstance(g, Mapping)}
    for oid, order in rects:
        group = group_by_id.get(oid)
        if group is None:
            problems.append("order %r has no matching group" % oid)
            continue
        centre_o, centre_g = _as_pair(order.get("center")), _as_pair(group.get("center"))
        if centre_o is None or centre_g is None:
            continue
        mismatch = (
            abs(centre_o[0] - centre_g[0]) > GEOM_EPS_CM
            or abs(centre_o[1] - centre_g[1]) > GEOM_EPS_CM
            or abs(float(order.get("width_cm") or 0.0)
                   - float(group.get("width_cm") or 0.0)) > GEOM_EPS_CM
            or abs(float(order.get("length_cm") or 0.0)
                   - float(group.get("depth_cm") or 0.0)) > GEOM_EPS_CM
            or abs(float(order.get("yaw_deg") or 0.0)
                   - float(group.get("yaw_deg") or 0.0)) > GEOM_EPS_CM
            or order.get("role") != group.get("role")
        )
        if mismatch:
            problems.append("order %r geometry/role disagrees with its group" % oid)

    # Fail closed: a rectangle the predicate cannot read is a problem, never a
    # silent "no overlap".  Groups are checked as well as orders, so a group
    # cannot hide an overlap its order does not show.
    for kind, rows in (("orders", rects),
                       ("groups", sorted(group_by_id.items(),
                                         key=lambda kv: str(kv[0])))):
        comparable = []
        for rid, row in rows:
            try:
                comparable.append((rid, _rect.cardinal_bounds(row)))
            except ValueError as exc:
                problems.append("%s %r cannot be compared: %s"
                                % (kind[:-1], rid, exc))
        for hit in overlap_report(comparable):
            problems.append(
                "%s %r and %r overlap width=%s depth=%s area=%s"
                % (kind, hit["a"], hit["b"], hit["width_cm"],
                   hit["depth_cm"], hit["area_cm2"]))
        hits = {(hit["a"], hit["b"]) for hit in overlap_report(comparable)}
        for i in range(len(comparable)):
            for j in range(i + 1, len(comparable)):
                if (comparable[i][0], comparable[j][0]) in hits:
                    continue
                gap = _rect.separation_cm(comparable[i][1], comparable[j][1])
                if gap < CLEARANCE_CM[0] - GEOM_EPS_CM:
                    problems.append("%s %r and %r clearance %.3f is below %s"
                                    % (kind, comparable[i][0], comparable[j][0],
                                       gap, CLEARANCE_CM[0]))

    if len(block_slots) >= 24:
        for oid, order in rects:
            if float(order.get("width_cm") or 0.0) < 3000.0 - GEOM_EPS_CM:
                problems.append("order %r frontage is below the 3000 cm production minimum"
                                % oid)
            if float(order.get("length_cm") or 0.0) < DEPTH_BAND_CM[0] - GEOM_EPS_CM:
                problems.append("order %r depth is below the 3000 cm production minimum"
                                % oid)

    if block_slots:
        bounds = _block_bounds(_block_record(layout, block_id) or {}, block_slots,
                               block_id)
        x_min, x_max, y_min, y_max = bounds
        for kind, rows in (("group", groups), ("order", orders)):
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                corners = group_corners(row)
                rid = row.get("group_id") if kind == "group" else row.get("id")
                if corners is None:
                    problems.append("%s %r has no comparable rectangle" % (kind, rid))
                    continue
                for x, y in corners:
                    if not (x_min - GEOM_EPS_CM <= x <= x_max + GEOM_EPS_CM
                            and y_min - GEOM_EPS_CM <= y <= y_max + GEOM_EPS_CM):
                        problems.append("%s %r corner [%s, %s] leaves the block region"
                                        % (kind, rid, x, y))
                        break

    # -- families alternate along a side --------------------------------------
    order_by_id = {o.get("id"): o for o in orders if isinstance(o, Mapping)}
    by_side: dict[float, list[Mapping[str, Any]]] = {}
    for group in groups:
        if isinstance(group, Mapping):
            by_side.setdefault(float(group.get("side_yaw") or 0.0), []).append(group)
    for side_yaw, side_groups in by_side.items():
        vertical = side_yaw in (SIDE_YAW["east"], SIDE_YAW["west"])
        ordered_groups = sorted(
            side_groups,
            key=lambda g: (_as_pair(g.get("center")) or (0.0, 0.0))[1 if vertical else 0])
        for first, second in zip(ordered_groups, ordered_groups[1:]):
            f1 = (order_by_id.get(first.get("group_id")) or {}).get("family")
            f2 = (order_by_id.get(second.get("group_id")) or {}).get("family")
            if f1 and f1 == f2:
                problems.append("groups %r and %r on side yaw %s both wear %s"
                                % (first.get("group_id"), second.get("group_id"),
                                   side_yaw, f1))

    # -- counts, clamps, composition ------------------------------------------
    counts = doc.get("counts")
    if not isinstance(counts, Mapping):
        problems.append("counts is missing or not a mapping")
    else:
        if counts.get("orders") != len(orders):
            problems.append("counts.orders %r != %d orders"
                            % (counts.get("orders"), len(orders)))
        if counts.get("groups") != len(groups):
            problems.append("counts.groups %r != %d groups"
                            % (counts.get("groups"), len(groups)))
        if counts.get("ordinary") != sum(1 for o in orders if isinstance(o, Mapping)
                                        and o.get("role") == "ordinary"):
            problems.append("counts.ordinary disagrees with the orders")
        if counts.get("landmark") != len(landmarks):
            problems.append("counts.landmark %r != %d landmark orders"
                            % (counts.get("landmark"), len(landmarks)))
    clamps = doc.get("clamps")
    if not isinstance(clamps, list):
        problems.append("clamps is not a list: %r" % (type(clamps).__name__,))
    else:
        order_ids = set(ids)
        for entry in clamps:
            if not isinstance(entry, Mapping) or entry.get("id") not in order_ids:
                problems.append("clamp %r does not name an order" % (entry,))
                continue
            if float(entry.get("height_cm") or 0.0) < float(entry.get("requested_cm")
                                                            or 0.0):
                problems.append("clamp %r lowered the height" % (entry.get("id"),))
    if len(block_slots) >= 24 and not 7 <= len(orders) <= 9:
        problems.append("block %s composes %d buildings, outside the 7-9 target"
                        % (block_id, len(orders)))
    return problems
