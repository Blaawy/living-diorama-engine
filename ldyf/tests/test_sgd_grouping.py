"""Tests for ``ldyf.sgd_grouping`` (schema ``sgd_grouping_v1``).

The main fixture is the REAL layout: ``city_layout.json`` in the repo root, 252
frontage slots across 9 blocks of 28 slots each (4 sides x 7), loaded from disk
rather than hand-built, so every test runs over ``block_1_1``'s landmark block
and the eight ordinary ones alike.

Hand-built layouts are used only where a test needs geometry the real layout
cannot show: the four ownership orientations (:func:`ring_layout` mirrors
``block_1_1``'s slot ring exactly, so an owner can be forced onto any of the four
sides at the south-east corner) and the degenerate blocks behind the value-error
paths.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from ldyf.sgd_buildings import (
    LANDMARK_FAMILY,
    SGD_PALETTE,
    STYLE_MIN_HEIGHT_CM,
    minimum_for,
    rect_corners,
    rects_overlap,
    sgd_asset_path,
)
from ldyf.sgd_grouping import (
    CLEARANCE_CM,
    DEPTH_BAND_CM,
    GEOM_EPS_CM,
    GROUP_SIZE_CHOICES,
    LANDMARK_GROUP_SLOTS,
    MIN_GROUP_DIMENSION_CM,
    SCHEMA_VERSION,
    SIDE_YAW,
    corner_owner,
    group_corners,
    group_slots,
    grouped_orders,
    rect_overlap_metrics,
    rect_separation_cm,
    validate_groups,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LAYOUT = json.loads((REPO_ROOT / "city_layout.json").read_text(encoding="utf-8"))
BLOCK_IDS = [str(b["id"]) for b in LAYOUT["blocks"]]
SEED = int(LAYOUT["building_slots"]["seed"])  # the seed lives on building_slots
LANDMARK_BLOCK = "block_1_1"

ORDER_KEYS = {"id", "block_id", "center", "width_cm", "length_cm", "yaw_deg",
              "height_cm", "requested_height_cm", "family", "sgd_asset", "role",
              "seed"}
GROUP_KEYS = {"group_id", "block_id", "side_yaw", "slot_ids", "center",
              "width_cm", "depth_cm", "yaw_deg", "role", "trimmed"}
CORNERS = ("SE", "NE", "NW", "SW")
CORNER_SIDES = {"SE": ("south", "east"), "NE": ("north", "east"),
                "NW": ("north", "west"), "SW": ("south", "west")}
SIDE_OF_YAW = {270.0: "south", 0.0: "east", 90.0: "north", 180.0: "west"}
HORIZONTAL = ("south", "north")
TOL = GEOM_EPS_CM


# ---------------------------------------------------------------- fixtures --


def slots_of(layout: dict, block_id: str) -> list:
    return [s for s in layout["building_slots"]["slots"]
            if str(s["block_id"]) == block_id]


def block_bounds(layout: dict, block_id: str) -> tuple:
    for block in layout["blocks"]:
        if str(block["id"]) == block_id:
            bbox = block["bbox"]
            return (bbox["x_min"], bbox["x_max"], bbox["y_min"], bbox["y_max"])
    raise AssertionError("no block record for %r" % (block_id,))


def side_of_slot(slot: dict) -> str:
    return SIDE_OF_YAW[float(slot["yaw"]) % 360.0]


def side_slots(layout: dict, block_id: str) -> dict:
    out: dict[str, list] = {}
    for slot in slots_of(layout, block_id):
        out.setdefault(side_of_slot(slot), []).append(slot)
    return out


def rect_of(group: dict) -> dict:
    """A group as the rectangle ``rects_overlap`` / ``rect_corners`` read."""
    return {"center": group["center"], "width_cm": group["width_cm"],
            "length_cm": group["depth_cm"], "yaw_deg": group["yaw_deg"]}


def along_span(group: dict) -> tuple:
    """``(low, high)`` of a group's rectangle on its own frontage axis."""
    side = SIDE_OF_YAW[float(group["side_yaw"]) % 360.0]
    index = 0 if side in HORIZONTAL else 1
    values = [corner[index] for corner in rect_corners(rect_of(group))]
    return min(values), max(values)


def corner_coord(layout: dict, block_id: str, corner: str, side: str) -> float:
    x_min, x_max, y_min, y_max = block_bounds(layout, block_id)
    key = corner.upper()
    if side in HORIZONTAL:
        return x_max if "E" in key else x_min
    return y_min if "S" in key else y_max


def corner_group(groups: list, layout: dict, block_id: str, corner: str,
                 side: str) -> dict:
    """The group of ``side`` that sits at ``corner``."""
    coord = corner_coord(layout, block_id, corner, side)
    return min(groups, key=lambda g: min(abs(along_span(g)[0] - coord),
                                         abs(along_span(g)[1] - coord)))


def axis_groups(groups: list) -> dict:
    out: dict[str, list] = {}
    for group in groups:
        out.setdefault(SIDE_OF_YAW[float(group["side_yaw"]) % 360.0], []).append(group)
    for side in out:
        out[side].sort(key=lambda g: along_span(g))
    return out


def order_of(doc: dict, group_id: str) -> dict:
    for order in doc["orders"]:
        if order["id"] == group_id:
            return order
    raise AssertionError("no order %r" % (group_id,))


def group_of_order(doc: dict, order_id: str) -> dict:
    for group in doc["groups"]:
        if group["group_id"] == order_id:
            return group
    raise AssertionError("no group %r" % (order_id,))


def separation(a: dict, b: dict) -> float:
    """Best separating-axis gap between two rectangles (negative == overlap).

    Mirrors ``rects_overlap``'s axis set: the largest positive gap found on the
    four face normals is how far apart the rectangles are.
    """
    rings = [rect_corners(a), rect_corners(b)]
    axes = []
    for rect in (a, b):
        rad = math.radians(float(rect["yaw_deg"]))
        ux, uy = math.cos(rad), math.sin(rad)
        axes.extend(((ux, uy), (-uy, ux)))
    gaps = []
    for ax, ay in axes:
        projected = [[p[0] * ax + p[1] * ay for p in ring] for ring in rings]
        gaps.append(max(min(projected[0]), min(projected[1]))
                    - min(max(projected[0]), max(projected[1])))
    return max(gaps)


def json_bytes(doc: dict) -> bytes:
    return json.dumps(doc, sort_keys=True).encode("utf-8")


def ring_layout(block_id: str = "ring", *, south_yaw: float = 270.0,
                seed: int = SEED, slots_per_side: int = 7) -> dict:
    """One square block whose slot ring mirrors ``block_1_1``'s.

    x and y both span 0..15920 (15,920 cm, as the real block does); every side
    carries ``slots_per_side`` slots of width 2000 (last 1920), depth 1500.  Each
    side reaches one corner and stops 1960 cm short of the other, exactly as
    ``block_1_1`` does, so corner ownership has real work to do.
    """
    span, depth = 15920.0, 1500.0
    slots: list[dict] = []
    index = 0

    def add(x: float, y: float, yaw: float, width: float) -> None:
        nonlocal index
        slots.append({"slot_id": "%s:f%d" % (block_id, index),
                      "block_id": block_id, "kit": "NYA", "x": float(x),
                      "y": float(y), "yaw": float(yaw), "width_cm": float(width),
                      "depth_cm": depth, "frontage_index": index})
        index += 1

    for i in range(slots_per_side):
        add(1000.0 + 2000.0 * i, 0.0, south_yaw,
            1920.0 if i == slots_per_side - 1 else 2000.0)
    for i in range(slots_per_side):
        add(span, 1000.0 + 2000.0 * i, 0.0,
            1920.0 if i == slots_per_side - 1 else 2000.0)
    for i in range(slots_per_side):
        add(span - 1000.0 - 2000.0 * i, span, 90.0,
            1920.0 if i == slots_per_side - 1 else 2000.0)
    for i in range(slots_per_side):
        add(0.0, span - 1000.0 - 2000.0 * i, 180.0,
            1920.0 if i == slots_per_side - 1 else 2000.0)
    polygon = [{"x": 0.0, "y": 0.0}, {"x": span, "y": 0.0},
               {"x": span, "y": span}, {"x": 0.0, "y": span}]
    block = {"id": block_id, "bbox": {"x_min": 0.0, "x_max": span,
                                      "y_min": 0.0, "y_max": span},
             "centre": {"x": span / 2.0, "y": span / 2.0}, "polygon": polygon}
    return {"schema_version": "city_layout_v1", "seed": seed, "blocks": [block],
            "building_slots": {"schema_version": "city_layout_v1", "seed": seed,
                               "kits": ["NYA"], "slots": slots}}


def block_id_with_corner_owner(corner: str, yaw: float,
                               *, seed: int = SEED) -> str:
    """A synthetic block id that hands ``corner`` to one of its adjacent sides."""
    assert yaw in [SIDE_YAW[s] for s in CORNER_SIDES[corner]]
    for attempt in range(400):
        block_id = "adv_%s_%s_%d" % (corner, int(yaw), attempt)
        if corner_owner(block_id, corner, seed=seed) == yaw:
            return block_id
    raise AssertionError("no block id found for %s owner yaw %s" % (corner, yaw))


def corner_pair(doc: dict, layout: dict, block_id: str, corner: str) -> tuple:
    """``(owner group, non-owner group, owner side, non-owner side)`` at a corner."""
    groups = axis_groups(doc["groups"])
    owner = SIDE_OF_YAW[corner_owner(block_id, corner, seed=doc["seed"])]
    horizontal, vertical = CORNER_SIDES[corner]
    non_owner = vertical if horizontal == owner else horizontal
    return (corner_group(groups[owner], layout, block_id, corner, owner),
            corner_group(groups[non_owner], layout, block_id, corner, non_owner),
            owner, non_owner)


# ------------------------------------------------------ the grouped document --


@pytest.mark.parametrize("block_id", BLOCK_IDS)
def test_every_real_block_validates_clean(block_id):
    doc = grouped_orders(LAYOUT, block_id, seed=SEED)
    assert doc["schema_version"] == SCHEMA_VERSION
    assert set(doc) >= {"schema_version", "orders", "landmark_id", "counts",
                        "clamps", "style_minimum_cm", "seed", "groups"}
    assert validate_groups(doc, LAYOUT, block_id) == []


@pytest.mark.parametrize("block_id", BLOCK_IDS)
def test_order_and_group_shapes(block_id):
    doc = grouped_orders(LAYOUT, block_id, seed=SEED)
    assert doc["counts"]["orders"] == len(doc["orders"])
    assert doc["counts"]["ordinary"] + doc["counts"]["landmark"] == len(doc["orders"])
    assert sum(doc["counts"]["families"].values()) == len(doc["orders"])
    assert doc["style_minimum_cm"] == {family: STYLE_MIN_HEIGHT_CM[family]
                                       for family in SGD_PALETTE}
    for order in doc["orders"]:
        assert set(order) == ORDER_KEYS
        assert order["block_id"] == block_id
        assert order["role"] in ("ordinary", "landmark")
        assert isinstance(order["seed"], int) and not isinstance(order["seed"], bool)
        assert len(order["center"]) == 2
        assert order["family"] in SGD_PALETTE
        assert order["sgd_asset"] == sgd_asset_path(order["family"])
        assert order["yaw_deg"] in tuple(SIDE_YAW.values())
        assert order["width_cm"] > 0.0 and order["length_cm"] > 0.0
        assert order["height_cm"] >= order["requested_height_cm"] > 0.0
    for group in doc["groups"]:
        assert set(group) == GROUP_KEYS
        assert group["block_id"] == block_id
        assert group["side_yaw"] == group["yaw_deg"]
        assert group["role"] in ("ordinary", "landmark")
        assert group["slot_ids"]
        assert len(set(group["slot_ids"])) == len(group["slot_ids"])
    ids = [group["group_id"] for group in doc["groups"]]
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("block_id", BLOCK_IDS)
def test_seven_to_nine_buildings_per_block(block_id):
    doc = grouped_orders(LAYOUT, block_id, seed=SEED)
    count = len(doc["orders"])
    assert 7 <= count <= 9, "%s composed %d buildings" % (block_id, count)
    # Independent derivation: every seven-slot side becomes exactly two
    # contiguous 3/4-slot groups, including the landmark side.
    expected = sum(max(1, (len(items) + 3) // 4)
                   for items in side_slots(LAYOUT, block_id).values())
    assert count == expected == 8
    if block_id == LANDMARK_BLOCK:
        assert doc["landmark_id"] is not None
    else:
        assert doc["landmark_id"] is None


@pytest.mark.parametrize("block_id", BLOCK_IDS)
def test_every_real_block_has_four_sides_of_seven_slots(block_id):
    """The composition numbers above rest on this; state it as a test."""
    counts = side_slots(LAYOUT, block_id)
    assert sorted(counts) == ["east", "north", "south", "west"]
    assert all(len(items) == 7 for items in counts.values())
    assert len(slots_of(LAYOUT, block_id)) == 28


@pytest.mark.parametrize("block_id", BLOCK_IDS)
def test_regeneration_is_byte_identical_and_group_ids_are_stable(block_id):
    first = grouped_orders(LAYOUT, block_id, seed=SEED)
    second = grouped_orders(copy.deepcopy(LAYOUT), block_id, seed=SEED)
    assert json_bytes(first) == json_bytes(second)
    assert [g["group_id"] for g in first["groups"]] == \
        [g["group_id"] for g in second["groups"]]
    assert [o["id"] for o in first["orders"]] == [o["id"] for o in second["orders"]]
    other = grouped_orders(LAYOUT, block_id, seed=SEED + 1)
    assert [g["group_id"] for g in other["groups"]] == \
        [g["group_id"] for g in first["groups"]]
    assert json_bytes(other) != json_bytes(first)


def test_the_layout_is_not_mutated():
    before = json_bytes(LAYOUT)
    for block_id in BLOCK_IDS:
        grouped_orders(LAYOUT, block_id, seed=SEED)
    assert json_bytes(LAYOUT) == before


# ----------------------------------------------------------------- geometry --


@pytest.mark.parametrize("block_id", BLOCK_IDS)
def test_no_rectangles_overlap_anywhere(block_id):
    doc = grouped_orders(LAYOUT, block_id, seed=SEED)
    orders = doc["orders"]
    for i in range(len(orders)):
        for j in range(i + 1, len(orders)):
            assert not rects_overlap(orders[i], orders[j]), \
                "%s overlaps %s in %s" % (orders[i]["id"], orders[j]["id"], block_id)


@pytest.mark.parametrize("block_id", BLOCK_IDS)
def test_unrelated_rectangles_keep_the_clearance(block_id):
    doc = grouped_orders(LAYOUT, block_id, seed=SEED)
    orders = doc["orders"]
    for i in range(len(orders)):
        for j in range(i + 1, len(orders)):
            assert rect_overlap_metrics(orders[i], orders[j]) is None
            gap = rect_separation_cm(orders[i], orders[j])
            assert gap >= CLEARANCE_CM[0] - TOL, \
                "%s and %s are %s cm apart in %s" % (orders[i]["id"],
                                                     orders[j]["id"], gap, block_id)


@pytest.mark.parametrize("block_id", BLOCK_IDS)
def test_every_rectangle_sits_inside_its_block(block_id):
    doc = grouped_orders(LAYOUT, block_id, seed=SEED)
    x_min, x_max, y_min, y_max = block_bounds(LAYOUT, block_id)
    for group in doc["groups"]:
        corners = group_corners(group)
        assert corners is not None
        for x, y in corners:
            assert x_min - TOL <= x <= x_max + TOL
            assert y_min - TOL <= y <= y_max + TOL
    # ... and nothing reaches into another block, i.e. across a street.
    others = [block_bounds(LAYOUT, other) for other in BLOCK_IDS
              if other != block_id]
    for group in doc["groups"]:
        for x, y in group_corners(group):
            for ox_min, ox_max, oy_min, oy_max in others:
                assert not (ox_min < x < ox_max and oy_min < y < oy_max), \
                    "group %s reaches into another block" % (group["group_id"],)


@pytest.mark.parametrize("block_id", BLOCK_IDS)
def test_corner_ownership_never_intersects_at_a_corner(block_id):
    """The owning side runs out; the non-owning side is inset and separated."""
    doc = grouped_orders(LAYOUT, block_id, seed=SEED)
    for corner in CORNERS:
        owner_group, non_group, owner, non_owner = corner_pair(doc, LAYOUT,
                                                               block_id, corner)
        assert owner in CORNER_SIDES[corner]
        assert owner != non_owner
        # the owner's rectangle reaches the corner ...
        owner_coord = corner_coord(LAYOUT, block_id, corner, owner)
        assert min(abs(edge - owner_coord)
                   for edge in along_span(owner_group)) < TOL, \
            "the owner %s did not run out to %s" % (owner, corner)
        # ... and the non-owner starts after owner depth + clearance
        non_coord = corner_coord(LAYOUT, block_id, corner, non_owner)
        span = along_span(non_group)
        low_end = abs(span[0] - non_coord) < abs(span[1] - non_coord)
        owner_depth = max(g["depth_cm"]
                          for g in axis_groups(doc["groups"])[owner])
        inset = owner_depth + CLEARANCE_CM[0]
        if low_end:
            assert span[0] >= non_coord + inset - TOL, \
                "%s is not inset from %s" % (non_owner, corner)
        else:
            assert span[1] <= non_coord - inset + TOL, \
                "%s is not inset from %s" % (non_owner, corner)
        assert not rects_overlap(rect_of(owner_group), rect_of(non_group))
        assert separation(rect_of(owner_group), rect_of(non_group)) >= \
            CLEARANCE_CM[0] - TOL


VALID_CORNER_OWNERS = [
    (corner, SIDE_YAW[side])
    for corner in CORNERS
    for side in CORNER_SIDES[corner]
]


@pytest.mark.parametrize("corner,owner_yaw", VALID_CORNER_OWNERS)
def test_adversarial_ownership_orientation_at_all_four_corners(corner, owner_yaw):
    """Exercise both valid owner choices at every corner."""
    block_id = block_id_with_corner_owner(corner, owner_yaw)
    layout = ring_layout(block_id)
    assert corner_owner(block_id, corner, seed=SEED) == owner_yaw
    doc = grouped_orders(layout, block_id, seed=SEED)
    assert validate_groups(doc, layout, block_id) == []
    for check_corner in CORNERS:
        owner_group, non_group, owner, non_owner = corner_pair(
            doc, layout, block_id, check_corner)
        owner_coord = corner_coord(layout, block_id, check_corner, owner)
        assert min(abs(edge - owner_coord)
                   for edge in along_span(owner_group)) < TOL
        non_coord = corner_coord(layout, block_id, check_corner, non_owner)
        span = along_span(non_group)
        low_end = abs(span[0] - non_coord) < abs(span[1] - non_coord)
        owner_depth = max(g["depth_cm"]
                          for g in axis_groups(doc["groups"])[owner])
        inset = owner_depth + CLEARANCE_CM[0]
        if low_end:
            assert span[0] >= non_coord + inset - TOL
        else:
            assert span[1] <= non_coord - inset + TOL
        assert rect_overlap_metrics(rect_of(owner_group), rect_of(non_group)) is None
        assert rect_separation_cm(rect_of(owner_group), rect_of(non_group)) >= \
            CLEARANCE_CM[0] - TOL


def test_ownership_is_an_alternation_covering_every_side_once():
    for block in BLOCK_IDS:
        owners = [corner_owner(block, corner, seed=SEED) for corner in CORNERS]
        assert len(set(owners)) == 4, owners
        for corner, owner in zip(CORNERS, owners):
            assert owner in [SIDE_YAW[side] for side in CORNER_SIDES[corner]]
    for corner, owner_yaw in VALID_CORNER_OWNERS:
        block_id = block_id_with_corner_owner(corner, owner_yaw)
        assert corner_owner(block_id, corner, seed=SEED) == owner_yaw


def test_yaw_normalisation_treats_minus_90_as_270():
    """Grouping does not depend on the sign convention of a side's yaw."""
    plain = grouped_orders(ring_layout("neg90", south_yaw=-90.0), "neg90",
                           seed=SEED)
    normalised = grouped_orders(ring_layout("neg90", south_yaw=270.0), "neg90",
                                seed=SEED)
    assert json_bytes(plain) == json_bytes(normalised)
    assert 270.0 in [g["side_yaw"] for g in plain["groups"]]
    # the real block's -90 south slots group with the same yaw as 270 would
    south = [s for s in slots_of(LAYOUT, LANDMARK_BLOCK)
             if float(s["yaw"]) % 360.0 == 270.0]
    assert south
    assert all(side_of_slot(s) == "south" for s in south)


# ------------------------------------------------------------------ slots --


@pytest.mark.parametrize("block_id", BLOCK_IDS)
def test_every_source_slot_is_attributed_to_exactly_one_group(block_id):
    doc = grouped_orders(LAYOUT, block_id, seed=SEED)
    wanted = {str(slot["slot_id"]) for slot in slots_of(LAYOUT, block_id)}
    seen: dict[str, str] = {}
    for group in doc["groups"]:
        for slot_id in group["slot_ids"]:
            assert slot_id not in seen, "%s is in two groups" % (slot_id,)
            seen[slot_id] = group["group_id"]
    assert set(seen) == wanted
    assert sum(len(g["slot_ids"]) for g in doc["groups"]) == len(wanted)
    for group in doc["groups"]:
        if group["trimmed"] is not None:
            assert group["slot_ids"]


@pytest.mark.parametrize("block_id", BLOCK_IDS)
def test_group_sizes_prefer_three_and_four_slots(block_id):
    doc = grouped_orders(LAYOUT, block_id, seed=SEED)
    for group in doc["groups"]:
        assert 1 <= len(group["slot_ids"]) <= max(GROUP_SIZE_CHOICES)
    for side, groups in axis_groups(doc["groups"]).items():
        if len(side_slots(LAYOUT, block_id).get(side, [])) != 7:
            continue
        sizes = sorted(len(g["slot_ids"]) for g in groups)
        assert sizes == [3, 4], (block_id, side, sizes)


# --------------------------------------------------------------- landmark --


def test_landmark_is_preserved_and_tallest_in_its_block():
    from ldyf import building_kits
    from ldyf.sgd_buildings import HEIGHT_BAND_CM

    doc = grouped_orders(LAYOUT, LANDMARK_BLOCK, seed=SEED)
    assert doc["landmark_id"] is not None
    landmarks = [o for o in doc["orders"] if o["role"] == "landmark"]
    assert len(landmarks) == 1
    landmark = landmarks[0]
    assert landmark["id"] == doc["landmark_id"]
    assert landmark["family"] == LANDMARK_FAMILY
    # grouped_orders does not apply height bands -- that is apply_height_bands'
    # job -- so the landmark here carries the LANDMARK_FLOOR. What must hold at
    # this stage is the hierarchy, not a specific band value.
    assert landmark["height_cm"] == max(o["height_cm"] for o in doc["orders"])
    assert doc["counts"]["landmark"] == 1
    ordinary = [o for o in doc["orders"] if o["role"] == "ordinary"]
    assert ordinary
    # the landmark family is shared now; the hierarchy is the invariant
    assert landmark["height_cm"] > max(o["height_cm"] for o in ordinary)

    selected = building_kits._pick_landmark_slot(LAYOUT, SEED)
    selected_id = str(selected["slot_id"])
    group = group_of_order(doc, landmark["id"])
    assert group["role"] == "landmark"
    assert len(group["slot_ids"]) in GROUP_SIZE_CHOICES
    assert selected_id in group["slot_ids"]

    side = side_of_slot(selected)
    ordered = sorted(side_slots(LAYOUT, LANDMARK_BLOCK)[side],
                     key=lambda s: (float(s["frontage_index"]), str(s["slot_id"])))
    indices = [i for i, slot in enumerate(ordered)
               if str(slot["slot_id"]) in set(group["slot_ids"])]
    assert indices == list(range(min(indices), max(indices) + 1))

    corners = group_corners(group)
    xs, ys = [p[0] for p in corners], [p[1] for p in corners]
    assert min(xs) - TOL <= float(selected["x"]) <= max(xs) + TOL
    assert min(ys) - TOL <= float(selected["y"]) <= max(ys) + TOL

    for other in doc["groups"]:
        if other["group_id"] == group["group_id"]:
            continue
        assert set(other["slot_ids"]).isdisjoint(group["slot_ids"])
        assert rect_overlap_metrics(rect_of(other), rect_of(group)) is None


def test_other_blocks_carry_no_landmark():
    for block_id in BLOCK_IDS:
        if block_id == LANDMARK_BLOCK:
            continue
        doc = grouped_orders(LAYOUT, block_id, seed=SEED)
        assert doc["landmark_id"] is None
        assert all(o["role"] == "ordinary" for o in doc["orders"])


# -------------------------------------------------------------- variation --


def test_variation_is_present_and_deterministic():
    doc = grouped_orders(LAYOUT, LANDMARK_BLOCK, seed=SEED)
    # one family (the only one with real walls), so the variation that is left
    # is massing: height tiers and group sizes
    heights = {o["height_cm"] for o in doc["orders"] if o["role"] == "ordinary"}
    sizes = {len(g["slot_ids"]) for g in doc["groups"]}
    assert {o["family"] for o in doc["orders"]} == {"SFD"}
    assert len(heights) >= 2
    assert len(sizes) >= 2
    assert json_bytes(doc) == json_bytes(
        grouped_orders(LAYOUT, LANDMARK_BLOCK, seed=SEED))


@pytest.mark.parametrize("block_id", BLOCK_IDS)
def test_adjacent_groups_on_a_side_never_look_alike(block_id):
    from ldyf.sgd_buildings import apply_height_bands
    from ldyf.sgd_grouping import NEIGHBOUR_HEIGHT_STEP_CM
    raw = grouped_orders(LAYOUT, block_id, seed=SEED)
    # the rule must hold for the plan AND for what is actually sent to Unreal
    for doc in (raw, apply_height_bands(raw, never_lower=True)):
        for groups in axis_groups(doc["groups"]).values():
            pairs = [order_of(doc, g["group_id"]) for g in groups]
            for a, b in zip(pairs, pairs[1:]):
                assert (a["family"] != b["family"]
                        or abs(a["height_cm"] - b["height_cm"])
                        >= NEIGHBOUR_HEIGHT_STEP_CM), \
                    "%s and %s both wear %s at %s / %s" % (
                        a["id"], b["id"], a["family"],
                        a["height_cm"], b["height_cm"])


# --------------------------------------------------------------- dimensions --


@pytest.mark.parametrize("block_id", BLOCK_IDS)
def test_dimensions_respect_the_sgd_minimum(block_id):
    doc = grouped_orders(LAYOUT, block_id, seed=SEED)
    for order in doc["orders"]:
        assert order["width_cm"] >= 3000.0 - TOL
        assert DEPTH_BAND_CM[0] - TOL <= order["length_cm"] <= \
            DEPTH_BAND_CM[1] + TOL
        assert order["height_cm"] >= minimum_for(order["family"])
    assert validate_groups(doc, LAYOUT, block_id) == []


def test_a_thin_side_still_yields_buildable_groups():
    """Two slots per side: the trim must not push a rectangle below the floor."""
    layout = ring_layout("thin", slots_per_side=2)
    doc = grouped_orders(layout, "thin", seed=SEED)
    assert validate_groups(doc, layout, "thin") == []
    assert len(doc["orders"]) == 4          # 3 ordinary sides + the landmark run
    for order in doc["orders"]:
        assert order["width_cm"] >= MIN_GROUP_DIMENSION_CM - 1e-6
        assert order["length_cm"] >= MIN_GROUP_DIMENSION_CM - 1e-6
    orders = doc["orders"]
    for i in range(len(orders)):
        for j in range(i + 1, len(orders)):
            assert not rects_overlap(orders[i], orders[j])


# -------------------------------------------------------------- validation --


def broken(block_id: str = LANDMARK_BLOCK) -> dict:
    return copy.deepcopy(grouped_orders(LAYOUT, block_id, seed=SEED))


def test_validate_rejects_a_dropped_slot_and_a_duplicated_one():
    doc = broken()
    victim = doc["groups"][0]["slot_ids"].pop()
    problems = validate_groups(doc, LAYOUT, LANDMARK_BLOCK)
    assert any(victim in p and "no group" in p for p in problems), problems

    doc = broken()
    doc["groups"][1]["slot_ids"].append(doc["groups"][0]["slot_ids"][0])
    problems = validate_groups(doc, LAYOUT, LANDMARK_BLOCK)
    assert any("attributed to both" in p for p in problems), problems

    doc = broken()
    doc["groups"][0]["slot_ids"] = ["not_a_slot"]
    problems = validate_groups(doc, LAYOUT, LANDMARK_BLOCK)
    assert any("not in block" in p for p in problems), problems


def test_validate_rejects_an_overlap():
    doc = broken()
    doc["orders"][1]["center"] = list(doc["orders"][0]["center"])
    doc["orders"][1]["width_cm"] = doc["orders"][0]["width_cm"]
    doc["orders"][1]["length_cm"] = doc["orders"][0]["length_cm"]
    doc["orders"][1]["yaw_deg"] = doc["orders"][0]["yaw_deg"]
    problems = validate_groups(doc, LAYOUT, LANDMARK_BLOCK)
    metric_hits = [p for p in problems if "overlap width=" in p]
    assert metric_hits, problems
    assert all("depth=" in p and "area=" in p for p in metric_hits)
    assert any("geometry/role disagrees" in p for p in problems), problems


def test_validate_rejects_a_rectangle_outside_the_block():
    doc = broken()
    group = doc["groups"][0]
    order = group_of_order(doc, group["group_id"])
    _x_min, _x_max, y_min, y_max = block_bounds(LAYOUT, LANDMARK_BLOCK)
    shift = (y_max - y_min) * 4.0
    for target in (order, group):
        target["center"] = [target["center"][0], target["center"][1] + shift]
    problems = validate_groups(doc, LAYOUT, LANDMARK_BLOCK)
    assert any("leaves the block region" in p for p in problems), problems


def test_validate_rejects_bad_dimensions():
    doc = broken()
    doc["orders"][0]["width_cm"] = 0.0
    assert any("positive" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    doc = broken()
    doc["orders"][0]["length_cm"] = MIN_GROUP_DIMENSION_CM / 2.0
    assert any("below the SGD minimum" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    doc = broken()
    doc["orders"][0]["length_cm"] = DEPTH_BAND_CM[1] * 3.0
    assert any("deeper than the band" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    doc = broken()
    doc["groups"][0]["width_cm"] = -1.0
    assert any("positive" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    doc = broken()
    doc["groups"][0]["depth_cm"] = MIN_GROUP_DIMENSION_CM / 4.0
    assert any("below the SGD minimum" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))


def test_validate_rejects_bad_families_heights_and_yaws():
    doc = broken()
    doc["orders"][0]["family"] = "NOPE"
    assert any("outside SGD_PALETTE" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    doc = broken()
    ordinary = next(o for o in doc["orders"] if o["role"] == "ordinary")
    ordinary["family"] = LANDMARK_FAMILY
    ordinary["sgd_asset"] = sgd_asset_path(LANDMARK_FAMILY)
    # gated on the palette flag; enable it so the branch keeps its coverage
    SGD_PALETTE[LANDMARK_FAMILY]["landmark_only"] = True
    try:
        assert any("landmark-only" in p for p in
                   validate_groups(doc, LAYOUT, LANDMARK_BLOCK))
    finally:
        SGD_PALETTE[LANDMARK_FAMILY]["landmark_only"] = False

    doc = broken()
    doc["orders"][0]["sgd_asset"] = "not/a/path"
    assert any("sgd_asset" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    doc = broken()
    doc["orders"][0]["height_cm"] = minimum_for(doc["orders"][0]["family"]) / 2.0
    problems = validate_groups(doc, LAYOUT, LANDMARK_BLOCK)
    assert any("minimum" in p for p in problems), problems

    doc = broken()
    doc["orders"][0]["height_cm"] = doc["orders"][0]["requested_height_cm"] / 2.0
    assert any("below its request" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    doc = broken()
    doc["orders"][0]["yaw_deg"] = 45.0
    assert any("cardinal" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    doc = broken()
    doc["groups"][0]["yaw_deg"] = 45.0
    assert any("cardinal" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    doc = broken()
    doc["groups"][0]["role"] = "curiosity"
    assert any("role" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    doc = broken()
    doc["groups"][0]["slot_ids"] = []
    assert any("has no slots" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))


def test_validate_rejects_a_second_or_damaged_landmark():
    doc = broken()
    ordinary = next(o for o in doc["orders"] if o["role"] == "ordinary")
    ordinary["role"] = "landmark"
    ordinary["family"] = LANDMARK_FAMILY
    ordinary["sgd_asset"] = sgd_asset_path(LANDMARK_FAMILY)
    problems = validate_groups(doc, LAYOUT, LANDMARK_BLOCK)
    assert any("claim the landmark role" in p for p in problems), problems

    doc = broken()
    landmark = next(o for o in doc["orders"] if o["role"] == "landmark")
    landmark["height_cm"] = MIN_GROUP_DIMENSION_CM
    problems = validate_groups(doc, LAYOUT, LANDMARK_BLOCK)
    assert any("not taller" in p for p in problems), problems

    doc = broken()
    landmark = next(o for o in doc["orders"] if o["role"] == "landmark")
    landmark["family"] = "NYAE"
    landmark["sgd_asset"] = \
        "/CitySamplePCG/PCG/DataAssets/Buildings/NYAE/SGD_NYAE_A.SGD_NYAE_A"
    problems = validate_groups(doc, LAYOUT, LANDMARK_BLOCK)
    assert any("expected SFD" in p for p in problems), problems

    doc = broken()
    doc["landmark_id"] = "nope"
    assert any("is not an order id" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))


def test_validate_accepts_a_block_without_a_landmark_order():
    """An ORDINARY block has no landmark, and that is not a problem.

    This used to strip the landmark out of block_1_1 and expect validation to
    pass. That was the test being wrong, not the validator: block_1_1 is the
    block the layout designates as carrying the landmark, so a block_1_1
    document with no landmark order IS invalid. The real intent -- "a block
    that is not supposed to have a landmark validates without one" -- is
    checked against an ordinary block instead.
    """
    ordinary = next(b for b in BLOCK_IDS if b != LANDMARK_BLOCK)
    doc = grouped_orders(LAYOUT, ordinary, seed=SEED)
    assert doc["landmark_id"] is None
    assert not [o for o in doc["orders"] if o["role"] == "landmark"]
    assert validate_groups(doc, LAYOUT, ordinary) == []


def test_validate_rejects_the_landmark_block_missing_its_landmark():
    """Removing the landmark from the block that must carry it is a defect."""
    doc = broken()
    doc["orders"] = [o for o in doc["orders"] if o["role"] != "landmark"]
    doc["landmark_id"] = None
    doc["counts"]["orders"] = len(doc["orders"])
    doc["counts"]["ordinary"] = len(doc["orders"])
    doc["counts"]["landmark"] = 0
    problems = validate_groups(doc, LAYOUT, LANDMARK_BLOCK)
    assert any("landmark" in p for p in problems), problems


def test_validate_rejects_counts_clamps_and_schema_damage():
    doc = broken()
    doc["schema_version"] = "sgd_buildings_v1"
    assert any("schema_version" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    doc = broken()
    doc["counts"]["orders"] = 99
    assert any("counts.orders" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    doc = broken()
    doc["counts"]["groups"] = 99
    assert any("counts.groups" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    doc = broken()
    doc["counts"]["landmark"] = 7
    assert any("counts.landmark" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    doc = broken()
    del doc["counts"]
    assert any("counts" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    doc = broken()
    doc["clamps"] = [{"id": "nope", "height_cm": 1.0, "requested_cm": 2.0}]
    assert any("does not name an order" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    doc = broken()
    doc["clamps"] = "not a list"
    assert any("clamps" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    doc = broken()
    doc["orders"][0].pop("family")
    assert any("lacks keys" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    doc = broken()
    doc["groups"][0].pop("trimmed")
    assert any("lacks keys" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    doc = broken()
    doc["orders"][0]["block_id"] = "somewhere_else"
    assert any("is not in block" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    doc = broken()
    doc["orders"] = "not a list"
    assert any("not a list" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))

    assert validate_groups("not a document", LAYOUT, LANDMARK_BLOCK)


def test_validate_rejects_same_family_neighbours_at_the_same_height():
    doc = broken()
    rewritten = False
    for groups in axis_groups(doc["groups"]).values():
        for first, second in zip(groups, groups[1:]):
            if first["role"] == "landmark" or second["role"] == "landmark":
                continue
            # same family already; flatten the pair to one height
            order_of(doc, second["group_id"])["height_cm"] = \
                order_of(doc, first["group_id"])["height_cm"]
            rewritten = True
            break
        if rewritten:
            break
    assert rewritten, "no adjacent ordinary pair on a side to damage"
    assert any("both wear" in p for p in
               validate_groups(doc, LAYOUT, LANDMARK_BLOCK))


def test_validate_reports_an_unknown_block():
    doc = grouped_orders(LAYOUT, LANDMARK_BLOCK, seed=SEED)
    problems = validate_groups(doc, LAYOUT, "not_a_block")
    assert problems
    assert any("is not in block" in p for p in problems)


def test_validate_rejects_too_few_buildings_for_a_big_block():
    doc = broken()
    doc["orders"] = doc["orders"][:5]
    doc["groups"] = doc["groups"][:5]
    problems = validate_groups(doc, LAYOUT, LANDMARK_BLOCK)
    assert any("outside the 7-9 target" in p for p in problems), problems


# ----------------------------------------------------------- value errors --


def test_value_errors_on_the_arguments():
    for seed in (0, -1, -100):
        with pytest.raises(ValueError):
            group_slots(LAYOUT, LANDMARK_BLOCK, seed=seed)
        with pytest.raises(ValueError):
            grouped_orders(LAYOUT, LANDMARK_BLOCK, seed=seed)
        with pytest.raises(ValueError):
            corner_owner(LANDMARK_BLOCK, "SE", seed=seed)
    for seed in (None, True, 3.5, "11"):
        with pytest.raises(ValueError):
            group_slots(LAYOUT, LANDMARK_BLOCK, seed=seed)
        with pytest.raises(ValueError):
            corner_owner(LANDMARK_BLOCK, "SE", seed=seed)
    with pytest.raises(ValueError):
        group_slots(LAYOUT, "no_such_block", seed=SEED)
    with pytest.raises(ValueError):
        grouped_orders(LAYOUT, "no_such_block", seed=SEED)
    with pytest.raises(ValueError):
        group_slots({"blocks": [], "building_slots": {"slots": []}}, "empty",
                    seed=SEED)
    with pytest.raises(ValueError):
        group_slots("not a layout", LANDMARK_BLOCK, seed=SEED)
    for corner in ("XX", "NN", "", "north-east-south", None, 7):
        with pytest.raises(ValueError):
            corner_owner(LANDMARK_BLOCK, corner, seed=SEED)


def test_corner_spellings_are_accepted():
    for spelling in ("SE", "se", "eS", "south-east", "east south", "SE "):
        assert corner_owner("b", spelling, seed=SEED) == \
            corner_owner("b", "SE", seed=SEED)


def test_value_errors_on_degenerate_slots():
    layout = ring_layout("tiny")
    layout["building_slots"]["slots"][0]["width_cm"] = 0.0
    with pytest.raises(ValueError):
        group_slots(layout, "tiny", seed=SEED)

    layout = ring_layout("tiny")
    layout["building_slots"]["slots"][3]["width_cm"] = -2000.0
    with pytest.raises(ValueError):
        group_slots(layout, "tiny", seed=SEED)

    layout = ring_layout("tiny")
    layout["building_slots"]["slots"][3]["depth_cm"] = -1500.0
    with pytest.raises(ValueError):
        group_slots(layout, "tiny", seed=SEED)

    layout = ring_layout("tiny")
    del layout["building_slots"]["slots"][5]["yaw"]
    with pytest.raises(ValueError):
        group_slots(layout, "tiny", seed=SEED)


def test_a_block_without_a_block_record_groups_from_its_slots():
    """Bounds fall back to the ring itself when the layout has no block records."""
    layout = ring_layout("ringless")
    layout["blocks"] = []
    doc = grouped_orders(layout, "ringless", seed=SEED)
    assert doc["landmark_id"] is None
    assert validate_groups(doc, layout, "ringless") == []
    for order in doc["orders"]:
        assert order["length_cm"] >= MIN_GROUP_DIMENSION_CM


@pytest.mark.parametrize("seed", [1, SEED, SEED + 1, SEED + 17, SEED + 101])
def test_multi_seed_geometry_and_clearance_stays_green(seed):
    for block_id in BLOCK_IDS:
        doc = grouped_orders(LAYOUT, block_id, seed=seed)
        assert 7 <= len(doc["orders"]) <= 9
        assert validate_groups(doc, LAYOUT, block_id) == []
        orders = doc["orders"]
        for i in range(len(orders)):
            for j in range(i + 1, len(orders)):
                assert rect_overlap_metrics(orders[i], orders[j]) is None
                assert rect_separation_cm(orders[i], orders[j]) >= \
                    CLEARANCE_CM[0] - TOL


@pytest.mark.parametrize("seed", [1, SEED, SEED + 1, SEED + 17, SEED + 101])
def test_landmark_group_keeps_selected_slot_in_a_contiguous_run(seed):
    from ldyf import building_kits

    selected = building_kits._pick_landmark_slot(LAYOUT, seed)
    block_id = str(selected["block_id"])
    doc = grouped_orders(LAYOUT, block_id, seed=seed)
    landmarks = [g for g in doc["groups"] if g["role"] == "landmark"]
    assert len(landmarks) == 1
    group = landmarks[0]
    assert str(selected["slot_id"]) in group["slot_ids"]

    side = side_of_slot(selected)
    ordered = sorted(side_slots(LAYOUT, block_id)[side],
                     key=lambda s: (float(s["frontage_index"]), str(s["slot_id"])))
    wanted = set(group["slot_ids"])
    indices = [i for i, slot in enumerate(ordered)
               if str(slot["slot_id"]) in wanted]
    assert indices == list(range(min(indices), max(indices) + 1))
    assert len(indices) in GROUP_SIZE_CHOICES


# ------------------------------------------- known-bad regression fixture --


KNOWN_BAD_PATH = (Path(__file__).resolve().parent / "data"
                  / "sgd_grouping_067c039_block_1_1.json")


def test_known_bad_067c039_document_is_rejected():
    """The rejected v1 output must never validate clean again.

    `ldyf/tests/data/sgd_grouping_067c039_block_1_1.json` is the real document
    the grouping module produced at commit 067c039, kept verbatim.

    A correction worth recording, because it nearly went the other way: that
    document was first reported as containing four rectangle OVERLAPS. It does
    not. The measurement behind that claim had the yaw->axis mapping backwards
    -- `yaw` is the OUTWARD facing direction, so depth runs along X for yaw
    0/180 and along Y for yaw 90/270, and the check swapped on the wrong pair.
    Re-measured correctly the document has ZERO overlaps, and the validator of
    the day was right to report none.

    What it really contains is 16 defects of other kinds: three pairs separated
    by only 10, 49 and 10 cm against a 150 cm minimum clearance, seven
    footprints below the 3000 cm production minimum, a 1201 cm sliver frontage,
    and a landmark at 7000 cm against a 14000 cm target with an ordinary
    neighbour at 6500. The validator of the day returned `[]` for all of that,
    which is the regression this pins.
    """
    doc = json.loads(KNOWN_BAD_PATH.read_text(encoding="utf-8"))
    problems = validate_groups(doc, LAYOUT, LANDMARK_BLOCK)
    assert problems, "the known-bad 067c039 document validated clean"
    joined = " | ".join(problems).lower()
    assert "clearance" in joined, problems
    assert "minimum" in joined, problems
    assert "landmark" in joined, problems


def test_known_bad_067c039_has_no_overlaps_but_violates_clearance():
    """Pin the exact distinction the first measurement got wrong.

    The shared predicate must report NO overlap for these pairs, and the
    separation must still be below the production clearance. Asserting both
    halves keeps a future change from "fixing" clearance by letting rectangles
    intersect, or from calling a 10 cm gap acceptable.
    """
    doc = json.loads(KNOWN_BAD_PATH.read_text(encoding="utf-8"))
    by_id = {o["id"]: o for o in doc["orders"]}
    tight = [
        ("block_1_1:east:0", "block_1_1:south:1", 10.0),
        ("block_1_1:east:2", "block_1_1:north:1", 49.0),
        ("block_1_1:south:0", "block_1_1:west:0", 10.0),
    ]
    for a, b, gap in tight:
        assert a in by_id and b in by_id, (a, b)
        assert rect_overlap_metrics(by_id[a], by_id[b]) is None,             "%s / %s do not actually overlap" % (a, b)
        got = rect_separation_cm(by_id[a], by_id[b])
        assert abs(got - gap) < 1.0, (a, b, got, gap)
        assert got < 150.0


def test_every_block_clears_the_production_clearance():
    """What the known-bad document failed, the current output must pass."""
    for block_id in BLOCK_IDS:
        doc = grouped_orders(LAYOUT, block_id, seed=SEED)
        orders = doc["orders"]
        for i in range(len(orders)):
            for j in range(i + 1, len(orders)):
                assert rect_overlap_metrics(orders[i], orders[j]) is None,                     (block_id, orders[i]["id"], orders[j]["id"])
                # tolerance matches the module's own GEOM_EPS_CM: centres and
                # spans pass through _f3, so a gap can land at 149.999 without
                # being a real clearance defect
                assert rect_separation_cm(orders[i], orders[j]) >= 150.0 - 0.01,                     (block_id, orders[i]["id"], orders[j]["id"])


# ---------------------------------------------------------------------------
# red team (2026-10-02): the neighbour rule looked along one side at a time
# ---------------------------------------------------------------------------


def _neighbour_pairs(doc):
    from ldyf.sgd_grouping import neighbour_pairs
    groups = doc["groups"]
    for i, j in neighbour_pairs(groups):
        yield groups[i], groups[j]


def test_neighbour_pairs_are_the_ring_of_a_block():
    # 8 groups, 2 per side: 4 pairs along the sides + 4 round the corners, and
    # the corner pairs are found whatever the gap (150 cm to over 10 m on the
    # real layout), which a distance threshold could not do
    from ldyf.sgd_grouping import neighbour_pairs, rect_separation_cm
    widest = 0.0
    for block_id in BLOCK_IDS:
        groups = grouped_orders(LAYOUT, block_id, seed=SEED)["groups"]
        pairs = neighbour_pairs(groups)
        assert len(pairs) == len(groups) == 8
        same = [p for p in pairs
                if groups[p[0]]["side_yaw"] == groups[p[1]]["side_yaw"]]
        assert len(same) == 4 and len(pairs) - len(same) == 4
        widest = max([widest] + [rect_separation_cm(groups[i], groups[j])
                                 for i, j in pairs])
    assert widest > 400.0
    assert neighbour_pairs([]) == []
    assert neighbour_pairs([{"group_id": "damaged"}]) == []


@pytest.mark.parametrize("block_id", BLOCK_IDS)
def test_neighbours_round_a_corner_never_look_alike(block_id):
    # 17 corner pairs of the real city were the same family at the same height:
    # one L-shaped mass wrapping the corner. The rule now sees corners.
    from ldyf.sgd_buildings import apply_height_bands
    from ldyf.sgd_grouping import NEIGHBOUR_HEIGHT_STEP_CM
    corners_seen = 0
    for seed in (SEED, 1, 2, 3, 17, 20260905):
        raw = grouped_orders(LAYOUT, block_id, seed=seed)
        for doc in (raw, apply_height_bands(raw, never_lower=True)):
            for first, second in _neighbour_pairs(doc):
                a = order_of(doc, first["group_id"])
                b = order_of(doc, second["group_id"])
                corners_seen += first["side_yaw"] != second["side_yaw"]
                assert (a["family"] != b["family"]
                        or abs(a["height_cm"] - b["height_cm"])
                        >= NEIGHBOUR_HEIGHT_STEP_CM), (seed, a["id"], b["id"])
    assert corners_seen > 0      # the test really did look round corners


def test_every_group_has_two_neighbours_so_three_tiers_suffice():
    # the generator's guarantee rests on the groups forming a ring
    for block_id in BLOCK_IDS:
        doc = grouped_orders(LAYOUT, block_id, seed=SEED)
        degree = {g["group_id"]: 0 for g in doc["groups"]}
        for first, second in _neighbour_pairs(doc):
            degree[first["group_id"]] += 1
            degree[second["group_id"]] += 1
        assert set(degree.values()) == {2}, (block_id, degree)


def test_validate_rejects_look_alike_neighbours_round_a_corner():
    doc = broken()
    pair = next((a, b) for a, b in _neighbour_pairs(doc)
                if a["side_yaw"] != b["side_yaw"]
                and "landmark" not in (a["role"], b["role"]))
    order_of(doc, pair[1]["group_id"])["height_cm"] = \
        order_of(doc, pair[0]["group_id"])["height_cm"]
    problems = validate_groups(doc, LAYOUT, LANDMARK_BLOCK)
    assert any("are neighbours, both wear" in p for p in problems), problems


def test_grouped_orders_fails_closed_when_slot_requests_defeat_the_tiers():
    # A tier is a FLOOR on a group's height: the tallest slot request wins over
    # the hint. Slots that all ask for ~3600 put a "low" group at 3600 beside a
    # "mid" group at 3800 -- 200 cm apart. That must raise, not be emitted.
    layout = copy.deepcopy(LAYOUT)
    slots = layout["building_slots"]["slots"]
    for slot in slots:
        slot["height_band"] = [3500.0, 3700.0]
    raised = emitted = 0
    for seed in range(1, 25):
        for block_id in BLOCK_IDS:
            try:
                doc = grouped_orders(layout, block_id, seed=seed)
            except ValueError as exc:
                assert "look-alike neighbours" in str(exc)
                raised += 1
            else:
                emitted += 1
                assert validate_groups(doc, layout, block_id) == []
    assert raised > 0            # the adversarial input really bites
    assert raised + emitted == 24 * len(BLOCK_IDS)


def test_tier_choice_raises_when_every_tier_is_taken():
    from ldyf.sgd_grouping import TIER_HINTS_CM, _family_and_hint
    taken = {("SFD", tier) for tier, _hint in TIER_HINTS_CM}
    with pytest.raises(ValueError):
        _family_and_hint("g", SEED, None, False, taken)
    # two taken leaves exactly the third
    for tier, _hint in TIER_HINTS_CM:
        got = _family_and_hint("g", SEED, None, False, taken - {("SFD", tier)})
        assert got[1] == tier


def test_validate_holds_the_landmark_to_the_landmark_band():
    # the check used to read the ORDINARY band top (5200), so a 4700 cm
    # "landmark" over 3800 cm neighbours validated clean
    from ldyf.sgd_buildings import LANDMARK_HEIGHT_BAND_CM
    doc = broken()
    for order in doc["orders"]:
        if order["role"] == "landmark":
            order["height_cm"] = LANDMARK_HEIGHT_BAND_CM[0] - 100.0
        else:
            order["height_cm"] = min(order["height_cm"], 3800.0)
    problems = validate_groups(doc, LAYOUT, LANDMARK_BLOCK)
    assert any("below the landmark band floor" in p for p in problems), problems
