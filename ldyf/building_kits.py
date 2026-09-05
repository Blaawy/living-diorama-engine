"""Closure lane B -- ``building_kits_v1``: real City Sample building
materials, per-building massing, ground-floor and roof kits.

This module turns a ``city_layout_v1`` document into per-building "kits":
which facade family (real ``/Game/Building/Material/...`` instances, all
taken from ``asset_probe_v3.json``) a building wears, how tall and how
shaped it is (with an optional street-wall setback), where its entrances go,
what its roof looks like, and one deterministic civic landmark.

Design rules (each is stated here because tests and the driver rely on them):

* Determinism -- every choice is derived from ``sha256`` digests over
  stable ids (``block_id``, ``building_id``/slot id, an optional ``seed``).
  No ``random``, no clock, no ``import unreal``.  The same layout document
  reproduces byte-identical kits across replays.

* Facade family assignment (``assign_family``) -- families are drawn from a
  per-block rotation ``(a + b * i) mod F`` where ``i`` is the building's
  frontage ordinal inside its block, ``a`` and ``b`` come from digests of
  ``block_id``, ``F`` is the family count and ``b`` is coprime with ``F``
  (so consecutive frontages along a block perimeter never share a family).
  A building whose id cannot be parsed as ``...:f<i>`` falls back to a plain
  digest pick (documented: the difference guarantee is lost, determinism is
  not).

* Height band rule -- downtown reads taller than the edges.  Every block is
  classified by the distance of its centre from the centroid of all block
  centres: distance <= 35% of the maximum is ``core`` (2300-3600 cm),
  <= 70% is ``mid`` (1600-2600 cm), otherwise ``edge`` (1100-1900 cm).
  All buildings on one block share their block's band; each building picks a
  height inside the band by digest.  ``massing_variation`` uses the band
  attached to the building as ``height_band`` and falls back to the ``mid``
  band when it is absent (e.g. direct calls with a hand-built fixture).

* Ground floor (``ground_floor_spec``) -- entrances/shopfronts sit on the
  facade that faces a footway.  ``city_layout.building_slots`` only emits
  slots on ``frontages``, i.e. block edges that face a road
  (city_layout.py docstring, frontages()/building_slots()); the slot's
  ``yaw`` is the outward edge normal, and the sidewalk band lies between the
  street wall and the carriageway, so the footway side of the footprint is
  the side the slot's ``yaw`` points away from the block centre.  Every kit
  therefore marks ``frontage_faces_footway: true``.

* Roof (``roof_spec``) -- roofs always use real roof materials (never the
  window material -- the window grid is a wall treatment and is never
  applied to a roof).  Plant rooms are pushed into the rear-left corner of
  the roof plane (local frame: x lateral, positive toward the left when
  facing the footway; y depth, positive into the block).  This leaves the
  street-front strip and the middle of the roof clear for the rooftop-prop
  lane (parapet-adjacent units and access paths).

* Landmark -- exactly one civic landmark per city.  It replaces one ordinary
  slot on the block whose centre is closest to the centroid of all block
  centres (tie broken by lowest block id), i.e. it lands downtown.  Its
  total height is >= ``LANDMARK_MIN_HEIGHT_CM`` (5600 cm), which is above
  the top of the tallest ordinary band (core 3600 cm), it wears its own
  ``civic_stone`` family that no ordinary building is assigned, and its
  stepped silhouette is returned as stacked boxes plus cylinder details so a
  driver can assemble it from primitives.

Validation catches: material paths absent from the probe list, heights
outside the building's stated band, setbacks wider/deeper than the
footprint, entrances on a frontage that has no footway, and a document with
anything other than exactly one landmark.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Iterable

SCHEMA_VERSION = "building_kits_v1"

# ---------------------------------------------------------------------------
# Ground truth: the building material list of asset_probe_v3.json (lines
# 4-122 of that file, 119 entries), transcribed verbatim.  Every material
# path this module emits is a member of this tuple, and the validator checks
# emitted paths against it (mirroring the probe file so tests can reload the
# JSON themselves and compare).
# ---------------------------------------------------------------------------

_P = "/Game/Building/Material/"
_PROBE_SEGMENTS: tuple[str, ...] = (
    "MI/Block/ForGym/MI_Bldg_Block_Granite_Beige_FG",
    "MI/Block/ForGym/MI_Bldg_Block_Granite_Black_FG",
    "MI/Block/ForGym/MI_Bldg_Block_Granite_Brown_FG",
    "MI/Block/ForGym/MI_Bldg_Block_Granite_Grey_FG",
    "MI/Block/ForGym/MI_Bldg_Block_Granite_White_FG",
    "MI/Block/ForGym/MI_Bldg_Block_Limestone_Beige_FG",
    "MI/Block/ForGym/MI_Bldg_Block_Limestone_BrownDark_FG",
    "MI/Block/ForGym/MI_Bldg_Block_Limestone_Brown_FG",
    "MI/Block/ForGym/MI_Bldg_Block_Limestone_Grey_FG",
    "MI/Block/MI_Bldg_Block_Granite",
    "MI/Block/MI_Bldg_Block_Granite_Beige",
    "MI/Block/MI_Bldg_Block_Granite_Black",
    "MI/Block/MI_Bldg_Block_Granite_Brown",
    "MI/Block/MI_Bldg_Block_Granite_Grey",
    "MI/Block/MI_Bldg_Block_Granite_White",
    "MI/Block/MI_Bldg_Block_Limestone",
    "MI/Block/MI_Bldg_Block_Limestone_Beige",
    "MI/Block/MI_Bldg_Block_Limestone_Brown",
    "MI/Block/MI_Bldg_Block_Limestone_BrownDark",
    "MI/Block/MI_Bldg_Block_Limestone_Grey",
    "MI/Brick/ForGym/MI_Bldg_BrickGym",
    "MI/Brick/ForGym/MI_Bldg_BrickOffset_Beige_FG",
    "MI/Brick/ForGym/MI_Bldg_BrickOffset_Brown_FG",
    "MI/Brick/ForGym/MI_Bldg_BrickOffset_Green_FG",
    "MI/Brick/ForGym/MI_Bldg_BrickOffset_Red_FG",
    "MI/Brick/ForGym/MI_Bldg_BrickOffset_White_FG",
    "MI/Brick/ForGym/MI_Bldg_BrickOffset_YellowWorn_FG",
    "MI/Brick/ForGym/MI_Bldg_BrickOffset_Yellow_FG",
    "MI/Brick/ForGym/MI_Bldg_BrickStacked_Grey_FG",
    "MI/Brick/ForGym/MI_Bldg_BrickStacked_Yellow_FG",
    "MI/Brick/MI_Bldg_BrickOffsetAlt",
    "MI/Brick/MI_Bldg_BrickOffset_Beige",
    "MI/Brick/MI_Bldg_BrickOffset_Brown",
    "MI/Brick/MI_Bldg_BrickOffset_Green",
    "MI/Brick/MI_Bldg_BrickOffset_Red",
    "MI/Brick/MI_Bldg_BrickOffset_White",
    "MI/Brick/MI_Bldg_BrickOffset_Yellow",
    "MI/Brick/MI_Bldg_BrickOffset_YellowWorn",
    "MI/Brick/MI_Bldg_BrickStacked_Grey",
    "MI/Concrete/ForGym/MI_Bldg_Concrete_Dirty_FG",
    "MI/Concrete/ForGym/MI_Bldg_Concrete_FG",
    "MI/Concrete/MI_Bldg_Concrete_Dirty",
    "MI/Glass/MI_Bldg_glass_opaque",
    "MI/MI_Bldg_Base",
    "MI/MI_Bldg_Block",
    "MI/MI_Bldg_Brick",
    "MI/MI_Bldg_Glass",
    "MI/MI_Bldg_Metal",
    "MI/MI_Bldg_PaintedMetal",
    "MI/MI_Bldg_PaintedStone",
    "MI/MI_Bldg_Prop",
    "MI/MI_Bldg_Smooth",
    "MI/MI_Bldg_Wood",
    "MI/MI_GrdDecal",
    "MI/Metal/ForGym/MI_Bldg_Metal_Brass_FG",
    "MI/Metal/ForGym/MI_Bldg_Metal_BrushedWorn_FG",
    "MI/Metal/ForGym/MI_Bldg_Metal_Brushed_FG",
    "MI/Metal/ForGym/MI_Bldg_Metal_Chrome_FG",
    "MI/Metal/ForGym/MI_Bldg_Metal_CopperOx_FG",
    "MI/Metal/ForGym/MI_Bldg_Metal_Copper_FG",
    "MI/Metal/ForGym/MI_Bldg_Metal_GoldMatte_FG",
    "MI/Metal/MI_Bldg_Metal_Brass",
    "MI/Metal/MI_Bldg_Metal_Brushed",
    "MI/Metal/MI_Bldg_Metal_BrushedPanel",
    "MI/Metal/MI_Bldg_Metal_BrushedWorn",
    "MI/Metal/MI_Bldg_Metal_Chrome",
    "MI/Metal/MI_Bldg_Metal_Copper",
    "MI/Metal/MI_Bldg_Metal_CopperOx",
    "MI/Metal/MI_Bldg_Metal_GoldMatte",
    "MI/Metal/MI_Bldg_Mirror",
    "MI/Paint/ForGym/MI_Bldg_PaintedMetal_Black_FG",
    "MI/Paint/ForGym/MI_Bldg_PaintedMetal_Blue_FG",
    "MI/Paint/ForGym/MI_Bldg_PaintedMetal_Brown_FG",
    "MI/Paint/ForGym/MI_Bldg_PaintedMetal_Green_FG",
    "MI/Paint/ForGym/MI_Bldg_PaintedMetal_Grey_FG",
    "MI/Paint/ForGym/MI_Bldg_PaintedMetal_Red_FG",
    "MI/Paint/ForGym/MI_Bldg_PaintedMetal_White_FG",
    "MI/Paint/ForGym/MI_Bldg_PaintedStone_Beige_FG",
    "MI/Paint/ForGym/MI_Bldg_PaintedStone_Black_FG",
    "MI/Paint/ForGym/MI_Bldg_PaintedStone_Brown_FG",
    "MI/Paint/ForGym/MI_Bldg_PaintedStone_Green_FG",
    "MI/Paint/ForGym/MI_Bldg_PaintedStone_Khaki_FG",
    "MI/Paint/ForGym/MI_Bldg_PaintedStone_Red_FG",
    "MI/Paint/ForGym/MI_Bldg_PaintedStone_White_FG",
    "MI/Paint/ForGym/MI_Bldg_PaintedStone_Yellow_FG",
    "MI/Paint/ForGym/MI_Bldg_PaintedStone_charcoal_FG",
    "MI/Paint/MI_Bldg_PaintedMetal_Beige",
    "MI/Paint/MI_Bldg_PaintedMetal_Black",
    "MI/Paint/MI_Bldg_PaintedMetal_Blue",
    "MI/Paint/MI_Bldg_PaintedMetal_Brown",
    "MI/Paint/MI_Bldg_PaintedMetal_Green",
    "MI/Paint/MI_Bldg_PaintedMetal_Grey",
    "MI/Paint/MI_Bldg_PaintedMetal_Red",
    "MI/Paint/MI_Bldg_PaintedMetal_Roof",
    "MI/Paint/MI_Bldg_PaintedMetal_White",
    "MI/Paint/MI_Bldg_PaintedStone_Beige",
    "MI/Paint/MI_Bldg_PaintedStone_Black",
    "MI/Paint/MI_Bldg_PaintedStone_Brown",
    "MI/Paint/MI_Bldg_PaintedStone_Green",
    "MI/Paint/MI_Bldg_PaintedStone_Khaki",
    "MI/Paint/MI_Bldg_PaintedStone_Red",
    "MI/Paint/MI_Bldg_PaintedStone_White",
    "MI/Paint/MI_Bldg_PaintedStone_Yellow",
    "MI/Paint/MI_Bldg_PaintedStone_charcoal",
    "MI/Wood/ForGym/MI_Bldg_Wood_Cedar_FG",
    "MI/Wood/ForGym/MI_Bldg_Wood_Walnut_FG",
    "MI/Wood/MI_Bldg_Wood_Cedar",
    "MI/Wood/MI_Bldg_Wood_Walnut",
    "M_Bldg_Base",
    "M_Bldg_Block",
    "M_Bldg_Prop",
    "M_DirtSkirt",
    "M_Vert_Color_Simple",
    "M_WireFrameEdge",
    "Roof/M_ORM_Master",
    "Roof/M_Roof",
    "Window/MI_Sticker_Dbuffer",
    "Window/M_Sticker_Dbuffer",
    "Window/M_Window",
)

PROBE_BUILDING_MATERIALS: tuple[str, ...] = tuple(_P + s for s in _PROBE_SEGMENTS)
PROBE_MATERIAL_SET = frozenset(PROBE_BUILDING_MATERIALS)

# Named masters that the task calls out explicitly.
ROOF_MASTER = _P + "Roof/M_Roof"
WINDOW_MASTER = _P + "Window/M_Window"
ROOF_ORM_MASTER = _P + "Roof/M_ORM_Master"
METAL_ROOF = _P + "MI/Paint/MI_Bldg_PaintedMetal_Roof"

# Named single materials reused by ground floors / landmark / plant rooms.
GRANITE_BLACK = _P + "MI/Block/MI_Bldg_Block_Granite_Black"
GRANITE_BROWN = _P + "MI/Block/MI_Bldg_Block_Granite_Brown"
GRANITE_WHITE = _P + "MI/Block/MI_Bldg_Block_Granite_White"
LIMESTONE = _P + "MI/Block/MI_Bldg_Block_Limestone"
PAINTED_STONE_BEIGE = _P + "MI/Paint/MI_Bldg_PaintedStone_Beige"
PAINTED_STONE_WHITE = _P + "MI/Paint/MI_Bldg_PaintedStone_White"
PAINTED_METAL_BLACK = _P + "MI/Paint/MI_Bldg_PaintedMetal_Black"
BRICK_BROWN = _P + "MI/Brick/MI_Bldg_BrickOffset_Brown"
CONCRETE_DIRTY = _P + "MI/Concrete/MI_Bldg_Concrete_Dirty"
COPPER_OX = _P + "MI/Metal/MI_Bldg_Metal_CopperOx"
GOLD_MATTE = _P + "MI/Metal/MI_Bldg_Metal_GoldMatte"
CHROME = _P + "MI/Metal/MI_Bldg_Metal_Chrome"
GLASS_OPAQUE = _P + "MI/Glass/MI_Bldg_glass_opaque"

# --- facade families -------------------------------------------------------
# Each family maps a visual name to concrete probe material instances.
# Non-_FG and _FG twins are kept as separate members: both exist in the
# probe file and are distinct assets with a tint difference.

FACADE_FAMILIES: dict[str, tuple[str, ...]] = {
    "granite_dark": (
        _P + "MI/Block/MI_Bldg_Block_Granite",
        _P + "MI/Block/MI_Bldg_Block_Granite_Black",
        _P + "MI/Block/MI_Bldg_Block_Granite_Grey",
        _P + "MI/Block/MI_Bldg_Block_Granite_Brown",
        _P + "MI/Block/ForGym/MI_Bldg_Block_Granite_Black_FG",
        _P + "MI/Block/ForGym/MI_Bldg_Block_Granite_Grey_FG",
    ),
    "granite_light": (
        _P + "MI/Block/MI_Bldg_Block_Granite_Beige",
        _P + "MI/Block/MI_Bldg_Block_Granite_White",
        _P + "MI/Block/ForGym/MI_Bldg_Block_Granite_Beige_FG",
        _P + "MI/Block/ForGym/MI_Bldg_Block_Granite_White_FG",
    ),
    "limestone": (
        _P + "MI/Block/MI_Bldg_Block_Limestone",
        _P + "MI/Block/MI_Bldg_Block_Limestone_Beige",
        _P + "MI/Block/MI_Bldg_Block_Limestone_Grey",
        _P + "MI/Block/MI_Bldg_Block_Limestone_Brown",
        _P + "MI/Block/MI_Bldg_Block_Limestone_BrownDark",
        _P + "MI/Block/ForGym/MI_Bldg_Block_Limestone_Beige_FG",
        _P + "MI/Block/ForGym/MI_Bldg_Block_Limestone_Grey_FG",
    ),
    "brick": (
        _P + "MI/MI_Bldg_Brick",
        _P + "MI/Brick/MI_Bldg_BrickOffsetAlt",
        _P + "MI/Brick/MI_Bldg_BrickOffset_Red",
        _P + "MI/Brick/MI_Bldg_BrickOffset_Brown",
        _P + "MI/Brick/MI_Bldg_BrickOffset_Beige",
        _P + "MI/Brick/MI_Bldg_BrickStacked_Grey",
        _P + "MI/Brick/ForGym/MI_Bldg_BrickOffset_Red_FG",
        _P + "MI/Brick/ForGym/MI_Bldg_BrickOffset_Brown_FG",
    ),
    "painted_stone": (
        _P + "MI/MI_Bldg_PaintedStone",
        _P + "MI/Paint/MI_Bldg_PaintedStone_Beige",
        _P + "MI/Paint/MI_Bldg_PaintedStone_White",
        _P + "MI/Paint/MI_Bldg_PaintedStone_Khaki",
        _P + "MI/Paint/MI_Bldg_PaintedStone_Yellow",
        _P + "MI/Paint/ForGym/MI_Bldg_PaintedStone_Beige_FG",
        _P + "MI/Paint/ForGym/MI_Bldg_PaintedStone_White_FG",
    ),
    "concrete": (
        _P + "MI/Concrete/MI_Bldg_Concrete_Dirty",
        _P + "MI/Concrete/ForGym/MI_Bldg_Concrete_Dirty_FG",
        _P + "MI/Concrete/ForGym/MI_Bldg_Concrete_FG",
    ),
}

# Landmark family: real light stone/white granite instances, never assigned
# to ordinary buildings by ``assign_family``.
CIVIC_FAMILY = "civic_stone"
LANDMARK_MATERIALS: tuple[str, ...] = (
    PAINTED_STONE_BEIGE,
    PAINTED_STONE_WHITE,
    GRANITE_WHITE,
    LIMESTONE,
)

GROUND_MATERIALS: tuple[str, ...] = (
    GRANITE_BLACK,
    GRANITE_BROWN,
    PAINTED_METAL_BLACK,
    BRICK_BROWN,
    CONCRETE_DIRTY,
)

# Height bands in cm.  Rule (module docstring + ``_band_for_block``):
# per-block band chosen from block-centre distance to the layout centroid.
HEIGHT_BAND_EDGE = (1100.0, 1900.0)
HEIGHT_BAND_MID = (1600.0, 2600.0)
HEIGHT_BAND_CORE = (2300.0, 3600.0)
_BAND_CORE_FRAC = 0.35
_BAND_MID_FRAC = 0.70

LANDMARK_MIN_HEIGHT_CM = 5600.0  # > core top (3600) by construction
_STOREY_CM = 300.0

# Roof kinds understood by the driver lane.
ROOF_KINDS = ("flat", "crown")

_FAMILY_NAMES: tuple[str, ...] = tuple(sorted(FACADE_FAMILIES))
_FAMILY_COUNT = len(_FAMILY_NAMES)
_COPRIME_STEPS = tuple(n for n in range(1, _FAMILY_COUNT)
                       if math.gcd(n, _FAMILY_COUNT) == 1)

# Guard: every emitted constant must really be in the probe list.
_ALL_EMITTED = list(FACADE_FAMILIES.values()) + [
    (ROOF_MASTER,), (WINDOW_MASTER,), (ROOF_ORM_MASTER,), (METAL_ROOF,),
    GROUND_MATERIALS, LANDMARK_MATERIALS,
]
for _group in _ALL_EMITTED:
    for _path in _group:
        if _path not in PROBE_MATERIAL_SET:  # pragma: no cover - import guard
            raise AssertionError(f"material path not in asset_probe_v3.json: {_path}")


# ---------------------------------------------------------------------------
# digest helpers
# ---------------------------------------------------------------------------


def _digest(*parts: Any) -> int:
    """Deterministic int from the first 16 hex chars of a sha256 digest."""
    text = "|".join(str(p) for p in parts)
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def _unit(*parts: Any) -> float:
    """Deterministic float in [0.0, 1.0)."""
    return _digest(*parts) / float(0xFFFFFFFFFFFFFFFF)


def _f3(v: float) -> float:
    return round(float(v), 3)


def _band_for_block(layout: dict, block: dict) -> tuple[float, float]:
    """Band for a block: distance from the centroid of all block centres.

    Rule: <= 35% of the max distance -> core; <= 70% -> mid; else edge.
    A layout without blocks or with a single block falls back to ``mid``
    (documented; an isolated test layout should not pretend to be a city).
    """
    blks = [b for b in layout.get("blocks", []) if b.get("centre")]
    if len(blks) < 2:
        return HEIGHT_BAND_MID
    cx = sum(b["centre"]["x"] for b in blks) / len(blks)
    cy = sum(b["centre"]["y"] for b in blks) / len(blks)
    centre = block.get("centre")
    if centre is None:
        return HEIGHT_BAND_MID
    dist = math.hypot(centre["x"] - cx, centre["y"] - cy)
    dists = [math.hypot(b["centre"]["x"] - cx, b["centre"]["y"] - cy)
             for b in blks]
    r_max = max(dists) if dists else 0.0
    if r_max <= 0.0:
        return HEIGHT_BAND_MID
    frac = dist / r_max
    if frac <= _BAND_CORE_FRAC:
        return HEIGHT_BAND_CORE
    if frac <= _BAND_MID_FRAC:
        return HEIGHT_BAND_MID
    return HEIGHT_BAND_EDGE


def _frontage_ordinal(building_id: str) -> int | None:
    """Frontage index ``i`` of a slot id shaped ``<block_id>:f<i>``."""
    if ":" not in building_id:
        return None
    tail = building_id.rsplit(":", 1)[-1]
    if not tail.startswith("f") or not tail[1:].isdigit():
        return None
    return int(tail[1:])


def _members_digest(members: Iterable[str], *parts: Any) -> str:
    """Deterministic member pick from an ordered collection."""
    lst = tuple(members)
    if not lst:
        raise ValueError("material list must not be empty")
    return lst[_digest(*parts) % len(lst)]


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def assign_family(block_id: str, building_id: str) -> str:
    """Deterministic facade family for one building.

    Digests of ``block_id`` give a rotation phase ``a`` and a step ``b``
    coprime with the family count ``F``; the building's frontage ordinal
    ``i`` (parsed from ``building_id``, which city_layout forms as
    ``"<block_id>:f<i>"``) then maps to family ``(a + b * i) mod F``.
    Because ``b`` is coprime to ``F``, two buildings whose frontage
    ordinals differ by 1 always land in *different* families, so adjacent
    buildings along a block perimeter never wear the same family.  Both
    ``a`` and ``b`` are functions of ``block_id`` only, so the whole city
    reproduces the same arrangement across replays.  A ``building_id`` that
    cannot be parsed as ``...:f<i>`` falls back to a plain digest
    (deterministic, but the neighbour guarantee is lost -- documented).
    """
    fam = sorted(FACADE_FAMILIES)
    if not fam:
        raise ValueError("no facade families configured")
    i = _frontage_ordinal(building_id)
    if i is None:
        return fam[_digest(block_id, building_id) % len(fam)]
    a = _digest(block_id, "family_phase") % len(fam)
    b = _COPRIME_STEPS[_digest(block_id, "family_step") % len(_COPRIME_STEPS)]
    return fam[(a + b * i) % len(fam)]


def massing_variation(building: dict, *, seed: int) -> dict:
    """Height and shape variation for one building slot.

    ``building`` is a city_layout slot dict (``width_cm``, ``depth_cm``,
    ``building_id`` or ``slot_id``) optionally carrying ``height_band`` as
    ``[lo, hi]`` (build_kits attaches the block's band).  Without a band the
    ``mid`` band is used.  Heights are drawn uniformly (by digest) inside
    the band.  A setback (upper tower mass pulled back from the street wall)
    appears more often on tall buildings and never exceeds 30% of the
    smaller footprint side, so ``2 * setback_cm <= width_cm`` and
    ``setback_cm <= depth_cm`` always hold.  Raises ``ValueError`` for
    non-positive width/depth or an invalid band.
    """
    width = building.get("width_cm", 0.0)
    depth = building.get("depth_cm", 0.0)
    if width <= 0.0 or depth <= 0.0:
        raise ValueError("width_cm and depth_cm must be positive")
    bid = str(building.get("building_id") or building.get("slot_id") or "b")
    band = tuple(building.get("height_band") or HEIGHT_BAND_MID)
    lo, hi = float(band[0]), float(band[1])
    if lo <= 0.0 or hi < lo:
        raise ValueError("height_band must be [lo, hi] with lo > 0")
    height = lo + (hi - lo) * _unit(bid, seed, "height")
    # Snap to a coarse storey so a driver can read floors off the height.
    height = max(lo, _STOREY_CM * math.floor(height / _STOREY_CM))
    height = min(hi, height)
    height = _f3(height)

    band_mid = (lo + hi) / 2.0
    p_setback = 0.20 + 0.5 * max(0.0, min(1.0, (band_mid - 1000.0) / 2600.0))
    has_setback = _unit(bid, seed, "setback") < p_setback
    if has_setback:
        room = min(width, depth)
        setback = _unit(bid, seed, "setback_cm") * 0.30 * room
        setback = _f3(min(setback, width / 2.0 - 1.0, depth - 1.0))
        start_lo = 0.45 * height
        start_hi = max(start_lo + 1.0, 0.80 * height)
        setback_start = _f3(start_lo + (start_hi - start_lo)
                            * _unit(bid, seed, "setback_start"))
    else:
        setback = 0.0
        setback_start = 0.0

    roof_roll = _unit(bid, seed, "roof_kind")
    has_parapet = has_setback or roof_roll < 0.55
    roof_kind = "crown" if (has_parapet and roof_roll < 0.35) else "flat"
    return {
        "height_cm": height,
        "setback_cm": _f3(setback),
        "setback_start_cm": _f3(setback_start),
        "has_parapet": bool(has_parapet),
        "roof_kind": roof_kind,
    }


def _street_side(building: dict) -> dict:
    """Which side of the footprint faces a footway.

    city_layout emits slots only on frontages (block edges that face a
    road) and gives each slot a ``yaw`` equal to the outward edge normal
    (frontages()/building_slots() in city_layout.py).  The footway band
    runs between the street wall and the carriageway, so the entrance side
    is the side the footprint faces along ``yaw`` -- the side away from the
    block centre.  This is recorded, not computed from road data (the slot
    has none).
    """
    yaw = float(building.get("yaw", 0.0))
    return {"side": "frontage", "yaw_deg": _f3(yaw),
            "faces_footway": True}


def ground_floor_spec(building: dict) -> dict:
    """Entrance / shopfront band of one building.

    Entrance face: the slot's frontage side (see ``_street_side``): every
    city_layout slot faces a road, and the footway lies between the street
    wall and the road, so ``frontage_faces_footway`` is true for every slot
    this module consumes.  Entrances are spread along the facade width by
    digest: 1 door under 800 cm of frontage, 2 up to 1600 cm, 3 beyond.
    Raises ``ValueError`` for non-positive width/depth.
    """
    width = building.get("width_cm", 0.0)
    depth = building.get("depth_cm", 0.0)
    if width <= 0.0 or depth <= 0.0:
        raise ValueError("width_cm and depth_cm must be positive")
    bid = str(building.get("building_id") or building.get("slot_id") or "b")
    height_cm = _f3(300.0 + 160.0 * _unit(bid, "ground_height"))
    roll = _unit(bid, "entrance_count")
    if width < 800.0:
        count = 1
    elif width < 1600.0:
        count = 1 if roll < 0.35 else 2
    else:
        count = 3 if roll < 0.30 else (2 if roll < 0.75 else 1)
    if count == 1:
        positions = [0.5]
    elif count == 2:
        positions = [0.3, 0.7]
    else:
        positions = [0.2, 0.5, 0.8]
    side = _street_side(building)
    material = _members_digest(GROUND_MATERIALS, bid, "ground_material")
    return {
        "height_cm": height_cm,
        "entrance_count": count,
        "entrance_positions": [_f3(p) for p in positions],
        "material": material,
        "frontage_faces_footway": side["faces_footway"],
        "frontage_yaw_deg": side["yaw_deg"],
    }


def roof_spec(building: dict) -> dict:
    """Roof treatment for one building (real roof materials only).

    The plant-room box is pushed to the rear-left corner of the roof plane
    (local x positive toward the left when facing the footway, y positive
    into the block), so the street-front strip and the middle of the roof
    stay clear for the rooftop-prop lane.  Raises ``ValueError`` for
    non-positive width/depth.
    """
    width = building.get("width_cm", 0.0)
    depth = building.get("depth_cm", 0.0)
    if width <= 0.0 or depth <= 0.0:
        raise ValueError("width_cm and depth_cm must be positive")
    bid = str(building.get("building_id") or building.get("slot_id") or "b")
    roll = _unit(bid, "roof_material")
    material = ROOF_MASTER if roll < 0.75 else METAL_ROOF

    wants_parapet = bool(building.get("massing", {}).get("has_parapet")) \
        if isinstance(building.get("massing"), dict) else False
    parapet_height_cm = _f3(0.0 if not wants_parapet
                            else 60.0 + 80.0 * _unit(bid, "parapet"))

    big = width * depth >= 2_400_000.0
    has_plant = (big and _unit(bid, "plant_room") < 0.85) \
        or (not big and _unit(bid, "plant_room") < 0.45)
    if has_plant:
        pw = max(200.0, min(900.0, 0.24 * width))
        pd = max(200.0, min(700.0, 0.26 * depth))
        ph = _f3(260.0 + 160.0 * _unit(bid, "plant_room_height"))
        # rear-left corner: +x = left when facing the footway, +y = into block
        ox = max(0.0, 0.5 * width - 0.5 * pw - 20.0)
        oy = max(0.0, 0.5 * depth - 0.5 * pd - 20.0)
        footprint = {
            "width_cm": _f3(pw), "depth_cm": _f3(pd), "height_cm": ph,
            "offset_lateral_cm": _f3(ox), "offset_depth_cm": _f3(oy),
            "corner": "rear_left",
        }
    else:
        footprint = None
    return {
        "material": material,
        "parapet_height_cm": parapet_height_cm,
        "has_plant_room": bool(has_plant),
        "plant_room_footprint": footprint,
    }


def _pick_landmark_slot(layout: dict, seed: int) -> dict:
    """Slot the landmark replaces: on the block nearest the layout centroid.

    Deterministic tie-break: the lowest block id among equal distances.
    The slot is chosen by digest over (block_id, seed) among that block's
    slots (sorted by slot id).  Raises ``ValueError`` if the layout has no
    blocks with slots.
    """
    blks = [b for b in layout.get("blocks", []) if b.get("centre")]
    slots_by_block: dict[str, list[dict]] = {}
    for s in layout.get("building_slots", {}).get("slots", []):
        slots_by_block.setdefault(s["block_id"], []).append(s)
    if not blks or not slots_by_block:
        raise ValueError("landmark_spec needs at least one block with slots")
    cx = sum(b["centre"]["x"] for b in blks) / len(blks)
    cy = sum(b["centre"]["y"] for b in blks) / len(blks)

    def key(b: dict) -> tuple[float, str]:
        return (math.hypot(b["centre"]["x"] - cx, b["centre"]["y"] - cy),
                b["id"])

    block = min(blks, key=key)
    while block["id"] not in slots_by_block:
        blks.remove(block)
        if not blks:
            raise ValueError("no block with slots for the landmark")
        block = min(blks, key=key)
    block_slots = sorted(slots_by_block[block["id"]], key=lambda s: s["slot_id"])
    chosen = block_slots[_digest("landmark", seed, block["id"])
                         % len(block_slots)]
    return chosen


def landmark_spec(layout: dict) -> dict:
    """Geometry for the single civic/utility landmark of a city.

    The landmark replaces one ordinary slot on the block nearest the
    centroid of all block centres (downtown by construction; tie broken by
    block id), so it inherits a real footway frontage from the slot.  It is
    visibly different from every ordinary building:

    * total height >= ``LANDMARK_MIN_HEIGHT_CM`` (5600 cm), which exceeds
      the top of the tallest ordinary band (core band tops out at 3600 cm);
    * its own ``civic_stone`` material family (never handed out by
      ``assign_family``);
    * a stepped silhouette -- podium, wider-than-tall hall, clock-tower
      shaft, crown, lantern and portico columns -- returned as stacked
      boxes/cylinders with sizes and offsets in the slot's local frame
      (origin at the footprint centre on the ground, x lateral positive
      toward the left when facing the footway, y depth positive into the
      block, z up).

    Raises ``ValueError`` for non-positive slot dimensions or an empty
    layout.
    """
    seed = int(layout.get("seed", 0) or
               layout.get("building_slots", {}).get("seed", 0) or 0)
    slot = _pick_landmark_slot(layout, seed)
    w = float(slot.get("width_cm", 0.0))
    d = float(slot.get("depth_cm", 0.0))
    if w <= 0.0 or d <= 0.0:
        raise ValueError("landmark slot width_cm/depth_cm must be positive")

    h = LANDMARK_MIN_HEIGHT_CM
    family = CIVIC_FAMILY
    # levels as fractions of the total height, converted below
    podium_top = 0.30 * h
    hall_top = 0.52 * h
    shaft_top = 0.93 * h

    def box(name: str, material: str, wcm: float, dcm: float, hcm: float,
            ox: float, oy: float, zc: float) -> dict:
        return {"name": name, "kind": "box", "material": material,
                "size_cm": [_f3(wcm), _f3(dcm), _f3(hcm)],
                "offset_cm": [_f3(ox), _f3(oy), _f3(zc)]}

    parts = [
        box("podium", PAINTED_STONE_BEIGE, 0.94 * w, 0.90 * d, podium_top,
            0.0, 0.04 * d, podium_top / 2.0),
        box("hall", LIMESTONE, 0.70 * w, 0.64 * d, hall_top - podium_top,
            0.0, 0.02 * d, (podium_top + hall_top) / 2.0),
    ]
    shaft = 0.17 * w
    shaft_oy = -0.14 * d  # toward the footway (front), where towers read
    parts.append(box("tower_shaft", GRANITE_WHITE, shaft, shaft,
                     shaft_top - hall_top, 0.0, shaft_oy,
                     (hall_top + shaft_top) / 2.0))
    parts.append(box("crown", COPPER_OX, 1.18 * shaft, 1.18 * shaft,
                     h - shaft_top, 0.0, shaft_oy,
                     (shaft_top + h) / 2.0))
    # lantern (vertical-axis cylinder) on the crown
    parts.append({
        "name": "lantern", "kind": "cylinder", "material": GOLD_MATTE,
        "radius_cm": _f3(0.45 * shaft), "height_cm": _f3(0.14 * h),
        "offset_cm": [0.0, _f3(shaft_oy),
                      _f3(h + 0.07 * h)],
    })
    # portico columns flanking the podium front
    col_r = 0.016 * w
    for sign in (-1.0, 1.0):
        parts.append({
            "name": f"portico_column_{'L' if sign < 0 else 'R'}",
            "kind": "cylinder", "material": CHROME,
            "radius_cm": _f3(col_r),
            "height_cm": _f3(0.30 * h),
            "offset_cm": [_f3(sign * 0.42 * w), _f3(-0.42 * d),
                          _f3(0.15 * h)],
        })
    return {
        "kind": "civic_clock_tower",
        "label": "civic hall with clock tower",
        "block_id": slot["block_id"],
        "building_id": slot["slot_id"],
        "family": family,
        "material": _members_digest(LANDMARK_MATERIALS,
                                    "landmark", seed, slot["block_id"]),
        "x": _f3(slot["x"]), "y": _f3(slot["y"]), "yaw": _f3(slot["yaw"]),
        "footprint_cm": {"width_cm": _f3(w), "depth_cm": _f3(d),
                         "height_cm": _f3(h)},
        "height_cm": _f3(h),
        "parts": parts,
    }


def build_kits(layout: dict, **kw: Any) -> dict:
    """Assemble ``building_kits_v1`` for a ``city_layout_v1`` document.

    Every ordinary slot (one is replaced by the landmark) receives a family,
    a concrete wall material, massing, a ground-floor spec and a roof spec.
    Output: ``{"schema_version", "seed", "buildings", "landmark",
    "families_used", "counts"}``.  ``kw`` may override ``seed``; otherwise
    the layout's seed (or 0) is used.  Raises ``ValueError`` when the
    layout has no building slots.
    """
    slots = list(layout.get("building_slots", {}).get("slots", []))
    if not slots:
        raise ValueError("build_kits needs at least one building slot")
    seed = int(kw.get("seed", layout.get("seed", 0) or
                      layout.get("building_slots", {}).get("seed", 0) or 0))
    blocks = layout.get("blocks", [])

    landmark = landmark_spec(layout)
    landmark_slot_ids = {landmark["building_id"]}
    ordinary = [s for s in slots if s["slot_id"] not in landmark_slot_ids]
    ordinary = sorted(ordinary, key=lambda s: s["slot_id"])

    band_by_block: dict[str, tuple[float, float]] = {}
    for blk in blocks:
        if blk.get("centre") is not None:
            band_by_block[blk["id"]] = _band_for_block(layout, blk)

    buildings: list[dict] = []
    for s in ordinary:
        bid = s["slot_id"]
        block_id = s["block_id"]
        fam = assign_family(block_id, bid)
        wall = _members_digest(FACADE_FAMILIES[fam], bid, "wall")
        building = dict(s)  # shallow copy: slot geometry + ids
        building["height_band"] = list(
            band_by_block.get(block_id, HEIGHT_BAND_MID))
        massing = massing_variation(building, seed=seed)
        gf = ground_floor_spec(building)
        b_with_massing = dict(building)
        b_with_massing["massing"] = massing
        roof = roof_spec(b_with_massing)
        entry = {
            "building_id": bid,
            "block_id": block_id,
            "family": fam,
            "wall_material": wall,
            "window_material": WINDOW_MASTER,
            "x": _f3(s["x"]), "y": _f3(s["y"]), "yaw": _f3(s["yaw"]),
            "width_cm": _f3(s["width_cm"]), "depth_cm": _f3(s["depth_cm"]),
            "height_cm": massing["height_cm"],
            "height_band_cm": [float(building["height_band"][0]),
                               float(building["height_band"][1])],
            "massing": massing,
            "ground_floor": gf,
            "roof": roof,
        }
        buildings.append(entry)
    buildings.sort(key=lambda e: e["building_id"])

    families_used: dict[str, dict[str, Any]] = {}
    for fam in sorted(FACADE_FAMILIES):
        families_used[fam] = {"members": list(FACADE_FAMILIES[fam]),
                              "count": sum(1 for b in buildings
                                           if b["family"] == fam)}
    families_used[CIVIC_FAMILY] = {"members": list(LANDMARK_MATERIALS),
                                   "count": 1}

    return {
        "schema_version": SCHEMA_VERSION,
        "seed": seed,
        "buildings": buildings,
        "landmark": landmark,
        "families_used": families_used,
        "counts": {
            "buildings": len(buildings),
            "landmark": 1,
            "blocks_with_slots": len({b["block_id"] for b in buildings}),
            "by_family": {f: families_used[f]["count"]
                          for f in sorted(families_used)},
        },
    }


def validate_kits(doc: dict) -> list:
    """Problems with a building-kits document; empty list means valid.

    Checks (all failures return a human-readable problem string):
    * a material path not present in the probe file's material list
      (mirrored by ``PROBE_BUILDING_MATERIALS``);
    * a massing height outside the building's stated ``height_band_cm``;
    * a setback wider than the building footprint (``2*setback > width``)
      or deeper than the footprint depth;
    * an entrance on a frontage that does not face a footway;
    * anything other than exactly one landmark.
    """
    problems: list[str] = []
    if doc.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"unknown schema_version {doc.get('schema_version')!r}")
    buildings = doc.get("buildings", [])
    for i, b in enumerate(buildings):
        bid = b.get("building_id", f"#{i}")
        mats = [b.get("wall_material"), b.get("window_material"),
                (b.get("ground_floor") or {}).get("material"),
                (b.get("roof") or {}).get("material")]
        for m in mats:
            if m and m not in PROBE_MATERIAL_SET:
                problems.append(f"{bid}: material {m} not in probe list")
        massing = b.get("massing") or {}
        h = massing.get("height_cm")
        band = b.get("height_band_cm")
        if h is None:
            problems.append(f"{bid}: massing has no height_cm")
        elif band and not (float(band[0]) <= float(h) <= float(band[1])):
            problems.append(
                f"{bid}: height {h} outside stated band {band}")
        w = float(b.get("width_cm", 0.0))
        d = float(b.get("depth_cm", 0.0))
        sb = massing.get("setback_cm", 0.0)
        if sb:
            if 2.0 * sb > w:
                problems.append(
                    f"{bid}: setback {sb} wider than building {w}")
            if sb > d:
                problems.append(
                    f"{bid}: setback {sb} deeper than building depth {d}")
        gf = b.get("ground_floor") or {}
        if gf.get("entrance_count", 0) > 0 \
                and gf.get("frontage_faces_footway") is not True:
            problems.append(
                f"{bid}: entrance on frontage with no footway")
    lm = doc.get("landmark")
    if not isinstance(lm, dict) or not lm.get("parts"):
        problems.append("exactly one landmark required (missing or empty)")
    else:
        for p in lm.get("parts", []):
            m = p.get("material")
            if m and m not in PROBE_MATERIAL_SET:
                problems.append(
                    f"landmark part {p.get('name')}: material {m} "
                    "not in probe list")
    return problems
