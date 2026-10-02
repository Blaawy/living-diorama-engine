"""Tests for ``ldyf.sgd_buildings`` (schema ``sgd_buildings_v1``).

The main fixture is built the way ``test_pcg_buildings`` builds its own: a real
``city_layout_v1`` document from ``city_layout.blocks`` and
``city_layout.building_slots``, so the slots are generated frontage slots with
real ids, yaws and widths rather than a hand-waved rectangle.  Hand-built
layouts are used where a test needs a *known* requested height (a degenerate
``height_band`` pins ``building_kits.massing_variation`` to one value).
"""

from __future__ import annotations

import copy
import json
import math

import pytest

from ldyf.city_layout import blocks, building_slots
from ldyf.sgd_buildings import (
    HEIGHT_BAND_CM,
    LANDMARK_FAMILY,
    LANDMARK_HEIGHT_BAND_CM,
    apply_height_bands,
    DEFAULT_MIN_HEIGHT_CM,
    FOUNDATION_ONLY_INSTANCES,
    ROLE_BAND_FAMILIES,
    SCHEMA_VERSION,
    SGD_ASSET_RE,
    SGD_PALETTE,
    STYLE_MIN_HEIGHT_CM,
    clamp_height,
    family_for,
    minimum_for,
    rect_corners,
    rects_overlap,
    role_band_for,
    set_style_minimums,
    sgd_asset_path,
    sgd_orders,
    style_minimums,
    validate_orders,
)

SEED = 11
DEPTH_CM = 1200.0
SPACING_CM = 4000.0
LANDMARK_FLOOR = 5600.0
ORDER_KEYS = {"id", "block_id", "center", "width_cm", "length_cm", "yaw_deg",
              "height_cm", "requested_height_cm", "family", "sgd_asset",
              "role", "seed"}


# ---------------------------------------------------------------- fixtures --


def _pt(x, y):
    return {"x": float(x), "y": float(y), "z": 0.0}


def make_lattice_spec(n_x: int, n_y: int, *, step_cm: float = 20000.0,
                      lane_width: float = 200.0) -> dict:
    """Hand-built lattice, same construction as ``test_city_layout``."""
    pos = {f"J{c}_{r}": _pt(c * step_cm, r * step_cm)
           for c in range(n_x) for r in range(n_y)}
    junctions = [{"id": jid, "type": "priority", "position": pos[jid],
                  "polygon": None, "incoming_edge_ids": []}
                 for jid in sorted(pos)]
    edges: list[dict] = []

    def add_edge(eid: str, a: str, b: str) -> None:
        edges.append({"id": eid, "from_junction": a, "to_junction": b,
                      "function": "normal", "priority": 1,
                      "lanes": [{"id": f"{eid}_0", "index": 0,
                                 "width_cm": lane_width,
                                 "width_cm_effective": lane_width,
                                 "width_source": "attribute",
                                 "speed_mps": 13.89, "length_m": 200.0,
                                 "allow": None, "disallow": None,
                                 "polyline": [dict(pos[a]), dict(pos[b])]}]})

    for r in range(n_y):
        for c in range(n_x - 1):
            add_edge(f"H{r}_{c}", f"J{c}_{r}", f"J{c + 1}_{r}")
    for c in range(n_x):
        for r in range(n_y - 1):
            add_edge(f"V{c}_{r}", f"J{c}_{r}", f"J{c}_{r + 1}")
    return {"schema_version": "road_spec_v1", "edges": edges,
            "junctions": junctions,
            "counts": {"edges": len(edges), "junctions": len(junctions)}}


def make_layout(n: int = 3, *, seed: int = SEED,
                step_cm: float = 20000.0) -> dict:
    """A ``city_layout_v1`` document: blocks + generated building slots."""
    spec = make_lattice_spec(n, n, step_cm=step_cm)
    return {"schema_version": "city_layout_v1", "seed": seed,
            "blocks": blocks(spec),
            "building_slots": building_slots(spec, kits=["a", "b", "c"],
                                             seed=seed, spacing_cm=SPACING_CM)}


def make_doc(layout: dict = None, **kw) -> dict:
    layout = make_layout() if layout is None else layout
    return sgd_orders(layout, seed=kw.pop("seed", SEED), **kw)


def band_layout(band_cm: float, n: int = 5, *, block_id: str = "b") -> dict:
    """``n`` hand-built slots in ONE block, all on a pinned height band.

    A degenerate band makes ``building_kits.massing_variation`` return exactly
    ``band_cm`` (``lo + (hi - lo) * u`` with ``lo == hi``), so the requested
    height of every order is known.  ``blocks`` is empty, which is the case
    ``pcg_buildings`` documents: the landmark falls back to the first slot in
    the stable order.
    """
    slots = [{"slot_id": "%s:f%d" % (block_id, i), "block_id": block_id,
              "kit": "A", "x": float(i) * SPACING_CM, "y": 4000.0,
              "yaw": 90.0, "width_cm": 900.0, "depth_cm": DEPTH_CM,
              "frontage_index": i, "height_band": [float(band_cm)] * 2}
             for i in range(n)]
    return {"schema_version": "city_layout_v1", "seed": SEED, "blocks": [],
            "building_slots": {"schema_version": "city_layout_v1", "seed": SEED,
                               "kits": ["A"], "slots": slots}}


def two_slot_layout() -> dict:
    """One north-facing (yaw 90) and one south-facing (yaw 270) frontage."""
    slots = [{"slot_id": "north:f0", "block_id": "north", "kit": "A",
              "x": 0.0, "y": 4000.0, "yaw": 90.0, "width_cm": 900.0,
              "depth_cm": DEPTH_CM, "frontage_index": 0},
             {"slot_id": "south:f0", "block_id": "south", "kit": "A",
              "x": 0.0, "y": -4000.0, "yaw": 270.0, "width_cm": 900.0,
              "depth_cm": DEPTH_CM, "frontage_index": 0}]
    return {"schema_version": "city_layout_v1", "seed": 5, "blocks": [],
            "building_slots": {"schema_version": "city_layout_v1", "seed": 5,
                               "kits": ["A"], "slots": slots}}


def layout_slots(layout: dict) -> list:
    """The layout's slots in the module's own stable order."""
    return sorted(layout["building_slots"]["slots"],
                  key=lambda s: (s["block_id"], s["frontage_index"],
                                 s["slot_id"]))


def json_bytes(doc: dict) -> bytes:
    return json.dumps(doc, sort_keys=True).encode("utf-8")


def midpoint(ring: list, k: int) -> tuple:
    return ((ring[k][0] + ring[(k + 1) % len(ring)][0]) / 2.0,
            (ring[k][1] + ring[(k + 1) % len(ring)][1]) / 2.0)


# ------------------------------------------------------- the order document --


def test_document_and_order_shape():
    layout = make_layout()
    doc = make_doc(layout)
    slots = layout["building_slots"]["slots"]
    assert doc["schema_version"] == SCHEMA_VERSION
    assert set(doc) >= {"schema_version", "orders", "landmark_id", "counts",
                        "clamps", "style_minimum_cm"}
    assert len(doc["orders"]) == len(slots)
    assert doc["counts"]["orders"] == len(doc["orders"])
    assert doc["counts"]["ordinary"] + doc["counts"]["landmark"] == \
        len(doc["orders"])
    assert sum(doc["counts"]["families"].values()) == len(doc["orders"])
    assert set(doc["orders"][0]["center"])
    for order in doc["orders"]:
        assert set(order) == ORDER_KEYS
        assert order["role"] in ("ordinary", "landmark")
        assert isinstance(order["seed"], int)
        assert not isinstance(order["seed"], bool)
        assert len(order["center"]) == 2
        assert order["family"] in SGD_PALETTE
        assert order["sgd_asset"] == sgd_asset_path(order["family"])
        assert order["width_cm"] > 0.0
        assert order["length_cm"] > 0.0
        assert order["height_cm"] > 0.0
        assert order["requested_height_cm"] > 0.0
    assert validate_orders(doc) == []


def test_orders_are_deterministic_byte_identical():
    layout = make_layout()
    first = sgd_orders(layout, seed=SEED)
    second = sgd_orders(make_layout(), seed=SEED)
    assert json_bytes(first) == json_bytes(second)
    # ... and the call does not mutate the layout it read.
    assert layout == make_layout()
    other = sgd_orders(layout, seed=SEED + 1)
    assert json_bytes(other) != json_bytes(first)


def test_counts_and_clamps_agree_with_the_orders():
    doc = make_doc(band_layout(1600.0, n=5))
    clamped_ids = {c["id"] for c in doc["clamps"]}
    for order in doc["orders"]:
        below = order["requested_height_cm"] < \
            doc["style_minimum_cm"][order["family"]]
        assert (order["id"] in clamped_ids) is below
        if below:
            assert order["height_cm"] == \
                doc["style_minimum_cm"][order["family"]]
        else:
            assert order["height_cm"] == order["requested_height_cm"]
    assert doc["clamps"]


# ------------------------------------------------------------------ palette --


def test_palette_is_the_one_family_with_real_walls():
    # NYAE and NYAF were dropped after the full-city render: the project's NY
    # kits hold only the 28-69 cm Wall_01S filler with null materials, so those
    # buildings cover 3-11 % of their facade and render as shafts. SFD covers
    # 1.02-1.09 on every floor up to 9000 cm and is the only family left.
    assert set(SGD_PALETTE) == {"SFD"}
    assert set(STYLE_MIN_HEIGHT_CM) == set(SGD_PALETTE)
    assert STYLE_MIN_HEIGHT_CM["SFD"] == 2500.0
    assert LANDMARK_FAMILY == "SFD"
    # every minimum is measured now, so none may be left unknown
    assert all(v is not None for v in STYLE_MIN_HEIGHT_CM.values())
    # nothing is landmark-only: the landmark shares SFD with every ordinary
    # building and is marked out by height instead
    assert [f for f, e in SGD_PALETTE.items() if e.get("landmark_only")] == []
    for family, entry in SGD_PALETTE.items():
        assert entry["instances"] > FOUNDATION_ONLY_INSTANCES
        path = sgd_asset_path(family)
        assert SGD_ASSET_RE.fullmatch(path)
        assert path.endswith(".SGD_%s_A" % family)
        assert path.startswith(
            "/CitySamplePCG/PCG/DataAssets/Buildings/%s/" % family)


def test_every_palette_family_is_reachable_and_none_other_is():
    seen = set()
    for height in (1500.0, 2000.0, 3000.0, 5000.0, 7000.0, 9000.0):
        for i in range(64):
            family = family_for("slot:%d" % i, height, SEED)
            assert family in SGD_PALETTE
            seen.add(family)
    assert seen == set(SGD_PALETTE)
    assert family_for("slot:0", 9000.0, SEED, landmark=True) == "SFD"
    assert family_for("slot:0", 9000.0, SEED, landmark=True) == \
        family_for("slot:1", 1500.0, SEED, landmark=True)


def test_role_bands_cover_the_palette():
    covered = {f for fams in ROLE_BAND_FAMILIES.values() for f in fams}
    assert covered == set(SGD_PALETTE)
    assert role_band_for(1500.0) == "low-rise"
    assert role_band_for(2300.0) == "mid-rise"
    assert role_band_for(5000.0) == "upper-mid"
    assert role_band_for(9000.0) == "tall"
    # every band is served by the one family that has walls
    assert family_for("slot:0", 1600.0, SEED) == "SFD"
    assert family_for("slot:0", 9000.0, SEED) == "SFD"


def test_no_order_carries_a_family_outside_the_palette():
    doc = make_doc()
    assert {o["family"] for o in doc["orders"]} <= set(SGD_PALETTE)
    for order in doc["orders"]:
        assert SGD_ASSET_RE.fullmatch(order["sgd_asset"])
        assert sgd_asset_path(order["family"]) == order["sgd_asset"]


# ----------------------------------------------------------------- landmark --


def test_exactly_one_landmark_and_it_is_the_tallest():
    layout = make_layout()
    doc = make_doc(layout)
    landmarks = [o for o in doc["orders"] if o["role"] == "landmark"]
    assert len(landmarks) == 1
    assert doc["landmark_id"] == landmarks[0]["id"]
    assert doc["counts"]["landmark"] == 1
    assert doc["counts"]["ordinary"] == len(doc["orders"]) - 1
    assert landmarks[0]["family"] == "SFD"
    assert landmarks[0]["sgd_asset"] == \
        "/CitySamplePCG/PCG/DataAssets/Buildings/SFD/SGD_SFD_A.SGD_SFD_A"
    # an ordinary order wears SFD too -- the landmark shares the family and
    # is distinguished by height, so only the height hierarchy is asserted
    _lm = next(o for o in doc["orders"] if o["role"] == "landmark")
    for order in doc["orders"]:
        if order["role"] != "landmark":
            assert order["height_cm"] < _lm["height_cm"]
    # the landmark is the slot pcg_buildings picks, and it is stable
    assert sgd_orders(layout, seed=SEED)["landmark_id"] == doc["landmark_id"]


def test_landmark_requested_height_is_lifted_to_the_existing_floor():
    doc = make_doc(band_layout(1600.0, n=4))
    landmark = [o for o in doc["orders"] if o["role"] == "landmark"][0]
    assert landmark["requested_height_cm"] == LANDMARK_FLOOR
    # SFD's measured minimum (2500) is BELOW the 5600 landmark floor, so the
    # landmark is not clamped upward -- it simply keeps its floor. History:
    # under an earlier landmark family whose minimum was recorded as 6000 it
    # was the other way round and the clamp was load-bearing.
    assert STYLE_MIN_HEIGHT_CM["SFD"] < LANDMARK_FLOOR
    assert landmark["height_cm"] == LANDMARK_FLOOR
    assert not any(c["id"] == landmark["id"] for c in doc["clamps"])


# -------------------------------------------------------------------- clamp --


def test_clamp_height_raises_the_height_and_reports_the_clamp():
    got = clamp_height("SFD", 1500.0)
    assert got == {"height_cm": 2500.0, "requested_cm": 1500.0,
                   "clamped": True, "minimum_cm": 2500.0}
    assert clamp_height("SFD", 2500.0) == {"height_cm": 2500.0,
                                           "requested_cm": 2500.0,
                                           "clamped": False,
                                           "minimum_cm": 2500.0}
    # never lowered
    assert clamp_height("SFD", 9000.0)["height_cm"] == 9000.0
    assert clamp_height("SFD", 9000.0)["clamped"] is False
    # every palette family is measured now, so the DEFAULT fallback is only
    # reachable through an explicit table that leaves a family unknown
    assert minimum_for("SFD", {"SFD": None}) == DEFAULT_MIN_HEIGHT_CM
    assert minimum_for("SFD") == 2500.0
    assert clamp_height("SFD", 1500.0)["clamped"] is True
    # SFD's measured minimum (2500) is ABOVE DEFAULT_MIN_HEIGHT_CM (2000),
    # so a request at the default still clamps; the no-clamp case is the
    # measured minimum itself.
    assert clamp_height("SFD", 2500.0)["clamped"] is False


def test_requested_height_below_minimum_never_survives_into_an_order():
    doc = make_doc(band_layout(1600.0, n=5))
    minima = doc["style_minimum_cm"]
    # every ORDINARY order clamps in this band (1600 against SFD's 2500
    # minimum) and the landmark does not: its 5600 floor clears 2500. History:
    # under an earlier landmark family with a 6000 minimum it clamped as well.
    assert len(doc["clamps"]) == len(doc["orders"]) - 1
    for order in doc["orders"]:
        assert order["height_cm"] >= minima[order["family"]]
        if order["role"] == "landmark":
            continue
        assert order["requested_height_cm"] == 1600.0  # the pinned band
        assert order["height_cm"] == minima[order["family"]]
        assert any(c["id"] == order["id"]
                   and c["height_cm"] == order["height_cm"]
                   for c in doc["clamps"])
    assert validate_orders(doc) == []


def test_set_style_minimums_injects_a_measured_table():
    before = style_minimums()
    try:
        table = set_style_minimums({"SFD": 4200.0})
        assert table["SFD"] == 4200.0
        assert minimum_for("SFD") == 4200.0
        assert clamp_height("SFD", 3000.0)["height_cm"] == 4200.0
        doc = make_doc()
        assert doc["style_minimum_cm"]["SFD"] == 4200.0
        assert validate_orders(doc) == []
        assert set_style_minimums({"SFD": None})["SFD"] is None
        assert minimum_for("SFD") == DEFAULT_MIN_HEIGHT_CM
    finally:
        set_style_minimums(before)
    assert style_minimums() == before


# -------------------------------------------------------- rectangles / yaw --


def test_rectangles_do_not_overlap():
    layout = make_layout()
    doc = make_doc(layout)
    assert validate_orders(doc) == []
    for i in range(len(doc["orders"])):
        for j in range(i + 1, len(doc["orders"])):
            assert not rects_overlap(doc["orders"][i], doc["orders"][j])
    # independent check, as in test_pcg_buildings: the lattice's frontages are
    # axis-aligned, so a plain bounding-box test is a valid second opinion.
    boxes = []
    for order in doc["orders"]:
        ring = rect_corners(order)
        boxes.append((order["id"], min(p[0] for p in ring),
                      min(p[1] for p in ring), max(p[0] for p in ring),
                      max(p[1] for p in ring)))
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            _, ax0, ay0, ax1, ay1 = boxes[i]
            _, bx0, by0, bx1, by1 = boxes[j]
            assert not (min(ax1, bx1) - max(ax0, bx0) > 1e-6
                        and min(ay1, by1) - max(ay0, by0) > 1e-6), \
                "%s and %s overlap" % (boxes[i][0], boxes[j][0])


def test_rects_overlap_is_axis_aware():
    a = {"center": [0.0, 0.0], "width_cm": 1000.0, "length_cm": 1000.0,
         "yaw_deg": 0.0}
    same_place = {"center": [0.0, 0.0], "width_cm": 1000.0,
                  "length_cm": 1000.0, "yaw_deg": 45.0}
    # same centre, rotated 45 degrees: still overlapping
    assert rects_overlap(a, same_place)
    # a 45-degree pair offset along their own axis, where a world-axis box test
    # would be at its least reliable: they still overlap
    diagonal = {"center": [600.0, 600.0], "width_cm": 1000.0,
                "length_cm": 1000.0, "yaw_deg": 45.0}
    shifted = {"center": [607.0, 607.0], "width_cm": 1000.0,
               "length_cm": 1000.0, "yaw_deg": 45.0}
    assert rects_overlap(diagonal, shifted)
    # sharing an edge exactly is not an overlap
    beside = {"center": [1000.0, 0.0], "width_cm": 1000.0,
              "length_cm": 1000.0, "yaw_deg": 0.0}
    assert not rects_overlap(a, beside)


def test_yaw_derivation_is_stable_for_north_and_south_frontages():
    layout = two_slot_layout()
    doc = make_doc(layout)
    by_id = {o["id"]: o for o in doc["orders"]}
    slots = {s["slot_id"]: s for s in layout["building_slots"]["slots"]}
    north, south = by_id["north:f0"], by_id["south:f0"]
    assert north["yaw_deg"] == 90.0
    assert south["yaw_deg"] == 270.0
    for order in (north, south):
        assert order["width_cm"] == 900.0        # the slot's frontage width
        assert order["length_cm"] == DEPTH_CM    # the slot's own depth
    # the mass sits BEHIND the slot point, on the block side: 600 cm back
    assert north["center"] == [0.0, 3400.0]
    assert south["center"] == [0.0, -3400.0]
    # ... and the front wall is the edge whose mid-point IS the slot point,
    # 900 cm wide, with its outward normal along +yaw (i.e. at the street).
    for order in (north, south):
        slot = slots[order["id"]]
        ring = rect_corners(order)
        gaps = [math.dist(midpoint(ring, k), (slot["x"], slot["y"]))
                for k in range(4)]
        assert min(gaps) == pytest.approx(0.0, abs=1e-6)
        front = gaps.index(min(gaps))
        start, end = ring[front], ring[(front + 1) % 4]
        edge = (end[0] - start[0], end[1] - start[1])
        width = math.hypot(*edge)
        assert width == pytest.approx(900.0, abs=1e-6)
        normal = (-edge[1] / width, edge[0] / width)
        rad = math.radians(order["yaw_deg"])
        outward = (math.cos(rad), math.sin(rad))
        assert (normal[0] * outward[0] + normal[1] * outward[1]) == \
            pytest.approx(1.0, abs=1e-6)


def test_a_one_family_band_repeats_that_family_and_nothing_else():
    # family_for can only rotate when a band offers an alternative. With SFD
    # the only family that has walls, every slot wears it; what keeps two
    # neighbours apart is HEIGHT, which sgd_grouping enforces and tests.
    layout = band_layout(2300.0, n=8)
    doc = make_doc(layout)
    by_id = {o["id"]: o for o in doc["orders"]}
    families = [by_id[s["slot_id"]]["family"] for s in layout_slots(layout)]
    assert set(families) == {"SFD"}
    assert set(families) <= set(ROLE_BAND_FAMILIES["mid-rise"])
    assert family_for("slot:0", 2300.0, SEED, avoid="SFD") == "SFD"


# ---------------------------------------------------------------- validator --


def test_validate_catches_each_failure_it_claims():
    base = make_doc()
    assert validate_orders(base) == []

    def problems_of(mutate):
        doc = copy.deepcopy(base)
        mutate(doc)
        return validate_orders(doc)

    problems = problems_of(lambda d: d["orders"][0].__setitem__("family", "ZZZ"))
    assert any("palette families" in p for p in problems), problems

    def below_minimum(d):
        order = next(o for o in d["orders"] if o["role"] == "ordinary")
        order["family"] = "SFD"
        order["sgd_asset"] = sgd_asset_path("SFD")
        order["height_cm"] = 1500.0
    problems = problems_of(below_minimum)
    assert any("below the SFD minimum" in p for p in problems), problems

    # a family that was in the palette before the render gate is refused now
    def dropped_family(d):
        order = next(o for o in d["orders"] if o["role"] == "ordinary")
        order["family"] = "NYAF"
        order["sgd_asset"] = \
            "/CitySamplePCG/PCG/DataAssets/Buildings/NYAF/SGD_NYAF_A.SGD_NYAF_A"
    problems = problems_of(dropped_family)
    assert any("palette families" in p for p in problems), problems

    def no_landmark(d):
        order = next(o for o in d["orders"] if o["role"] == "landmark")
        order["role"] = "ordinary"
        order["family"] = "SFD"
        order["sgd_asset"] = sgd_asset_path("SFD")
    problems = problems_of(no_landmark)
    assert any("exactly one landmark" in p for p in problems), problems

    def two_landmarks(d):
        order = next(o for o in d["orders"] if o["role"] == "ordinary")
        order["role"] = "landmark"
    problems = problems_of(two_landmarks)
    assert any("exactly one landmark" in p for p in problems), problems

    def nyg_on_an_ordinary_order(d):
        order = next(o for o in d["orders"] if o["role"] == "ordinary")
        order["family"] = LANDMARK_FAMILY
        order["sgd_asset"] = sgd_asset_path(LANDMARK_FAMILY)
    # exclusivity is now gated on the palette flag, so enable it for this
    # assertion rather than deleting the branch's only coverage
    SGD_PALETTE[LANDMARK_FAMILY]["landmark_only"] = True
    try:
        problems = problems_of(nyg_on_an_ordinary_order)
        assert any("landmark-only" in p for p in problems), problems
    finally:
        SGD_PALETTE[LANDMARK_FAMILY]["landmark_only"] = False

    def overlapping(d):
        d["orders"][1]["center"] = list(d["orders"][0]["center"])
    problems = problems_of(overlapping)
    assert any("rectangles overlap" in p for p in problems), problems

    problems = problems_of(lambda d: d["orders"][0].__setitem__("width_cm", 0.0))
    assert any("width_cm" in p and "not positive" in p
               for p in problems), problems

    problems = problems_of(
        lambda d: d["orders"][0].__setitem__("length_cm", -5.0))
    assert any("length_cm" in p and "not positive" in p
               for p in problems), problems

    problems = problems_of(lambda d: d["orders"][0].__setitem__("height_cm", 0.0))
    assert any("height_cm" in p and "not positive" in p
               for p in problems), problems

    problems = problems_of(
        lambda d: d["orders"][0].__setitem__("height_cm", -1.0))
    assert any("height_cm" in p for p in problems), problems

    def bad_asset(d):
        order = d["orders"][0]
        order["sgd_asset"] = (
            "/CitySamplePCG/PCG/DataAssets/Buildings/%s/SGD_%s_A"
            % (order["family"], order["family"]))
    problems = problems_of(bad_asset)
    assert any("does not match the documented pattern" in p
               for p in problems), problems

    def asset_names_another_family(d):
        order = d["orders"][0]
        order["sgd_asset"] = \
            "/CitySamplePCG/PCG/DataAssets/Buildings/NYAE/SGD_NYAE_A.SGD_NYAE_A"
    problems = problems_of(asset_names_another_family)
    assert any("not the documented path for family" in p
               for p in problems), problems

    problems = problems_of(lambda d: d.__setitem__("schema_version", "nope"))
    assert any("schema_version" in p for p in problems), problems

    problems = problems_of(lambda d: d.__setitem__("landmark_id", "nope"))
    assert any("landmark_id" in p for p in problems), problems

    def duplicate_id(d):
        d["orders"][1]["id"] = d["orders"][0]["id"]
    problems = problems_of(duplicate_id)
    assert any("duplicate order id" in p for p in problems), problems

    problems = problems_of(lambda d: d["orders"][0].__setitem__("center", [0.0]))
    assert any("do not describe a rectangle" in p for p in problems), problems

    problems = problems_of(
        lambda d: d["orders"][0].__setitem__("yaw_deg", None))
    assert any("do not describe a rectangle" in p for p in problems), problems

    assert validate_orders({"orders": []}) == ["document has no orders"]
    # the untouched document stays valid, and the base really has both roles
    assert validate_orders(base) == []
    assert {o["role"] for o in base["orders"]} == {"ordinary", "landmark"}


def test_validate_accepts_a_zero_yaw():
    doc = copy.deepcopy(make_doc())
    for order in doc["orders"]:
        order["yaw_deg"] = 0.0
    # Rewriting yaw rotates every rectangle in place, which can legitimately
    # make neighbours overlap -- the validator is correct to say so. What this
    # test exists to check is narrower: a zero yaw is not itself a complaint.
    assert not [p for p in validate_orders(doc) if "yaw" in p.lower()]


# ------------------------------------------------------------ ValueErrors --


def test_value_errors():
    with pytest.raises(ValueError):
        sgd_orders({}, seed=SEED)
    with pytest.raises(ValueError):
        sgd_orders({"building_slots": {"slots": []}}, seed=SEED)
    with pytest.raises(ValueError):
        sgd_orders(make_layout(), seed=None)
    with pytest.raises(ValueError):
        sgd_orders(make_layout(), seed="11")
    with pytest.raises(ValueError):
        sgd_orders(make_layout(), seed=True)
    with pytest.raises(ValueError):
        sgd_orders(make_layout(), seed=SEED, minimums={"QQ": 1000.0})
    with pytest.raises(ValueError):
        clamp_height("QQ", 3000.0)
    with pytest.raises(ValueError):
        clamp_height("SFD", 0.0)
    with pytest.raises(ValueError):
        clamp_height("SFD", -1.0)
    with pytest.raises(ValueError):
        family_for("slot:0", 0.0, SEED)
    with pytest.raises(ValueError):
        minimum_for("QQ")
    with pytest.raises(ValueError):
        sgd_asset_path("NYAB")
    with pytest.raises(ValueError):
        set_style_minimums({"QQ": 1000.0})
    with pytest.raises(ValueError):
        set_style_minimums({"SFD": 0.0})
    with pytest.raises(ValueError):
        set_style_minimums({"SFD": -5.0})


def test_a_slot_with_no_usable_footprint_is_a_value_error():
    layout = band_layout(2300.0, n=2)
    layout["building_slots"]["slots"][0]["width_cm"] = 0.0
    with pytest.raises(ValueError):
        sgd_orders(layout, seed=SEED)


# ------------------------------------------------------- recommended bands --


def test_height_bands_cover_the_palette_and_start_at_the_measured_minimum():
    assert set(HEIGHT_BAND_CM) == set(SGD_PALETTE)
    for family, (lo, hi) in HEIGHT_BAND_CM.items():
        assert lo == STYLE_MIN_HEIGHT_CM[family]  # band floor IS the measurement
        assert hi > lo


def test_apply_height_bands_spreads_requests_and_keeps_ordering():
    doc = make_doc()
    before = copy.deepcopy(doc)
    banded = apply_height_bands(doc)
    assert doc == before, "apply_height_bands must not mutate its input"
    assert banded is not doc
    for order in banded["orders"]:
        lo, hi = (LANDMARK_HEIGHT_BAND_CM if order["role"] == "landmark"
                  else HEIGHT_BAND_CM[order["family"]])
        assert lo <= order["height_cm"] <= hi
        assert order["height_cm"] >= STYLE_MIN_HEIGHT_CM[order["family"]]
    # within one family, a taller request is never a shorter building
    by_family = {}
    for order in banded["orders"]:
        by_family.setdefault(order["family"], []).append(order)
    for family, group in by_family.items():
        group.sort(key=lambda o: o["requested_height_cm"])
        heights = [o["height_cm"] for o in group]
        assert heights == sorted(heights), family


def test_apply_height_bands_puts_the_landmark_at_the_top_of_its_band():
    banded = apply_height_bands(make_doc())
    landmark = [o for o in banded["orders"] if o["role"] == "landmark"][0]
    assert landmark["height_cm"] == LANDMARK_HEIGHT_BAND_CM[1]
    # and the landmark is taller than every ordinary building
    others = [o["height_cm"] for o in banded["orders"]
              if o["role"] != "landmark"]
    assert all(landmark["height_cm"] > h for h in others)


def test_apply_height_bands_excludes_the_landmark_from_normalisation():
    # the landmark's request dwarfs the ordinary ones; if it were included in the
    # range, every ordinary building would collapse to the bottom of its band
    banded = apply_height_bands(make_doc())
    ordinary = [o for o in banded["orders"] if o["role"] != "landmark"]
    assert len({o["height_cm"] for o in ordinary}) > 1


def test_apply_height_bands_refuses_an_empty_document():
    with pytest.raises(ValueError):
        apply_height_bands({"orders": []})


def test_apply_height_bands_never_lower_only_lifts_ordinary_orders():
    doc = make_doc()
    for order in doc["orders"]:
        if order["role"] != "landmark":
            order["height_cm"] = 6500.0   # a tier above the family band top
            break
    banded = apply_height_bands(doc, never_lower=True)
    for before, after in zip(doc["orders"], banded["orders"]):
        if before["role"] != "landmark":
            assert after["height_cm"] >= before["height_cm"]
    # without the flag the same order is pulled back inside its band
    plain = apply_height_bands(doc)
    assert any(a["height_cm"] < b["height_cm"]
               for a, b in zip(plain["orders"], doc["orders"]))


def test_predicted_top_never_exceeds_the_measured_builds():
    from ldyf.sgd_buildings import predicted_top_cm
    # (family, planned, measured built) from the full-city build
    measured = (("NYAE", 2800.0, 2599.8), ("NYAE", 2930.0, 2599.8),
                ("NYAE", 3074.0, 2924.9), ("NYAE", 5200.0, 4874.8),
                ("NYAF", 2800.0, 2789.5), ("NYAF", 3074.0, 2789.5),
                ("NYAF", 5200.0, 5064.5), ("NYAF", 6500.0, 6364.5),
                ("NYAF", 9000.0, 8964.5))
    exact = 0
    for fam, planned, built in measured:
        got = predicted_top_cm(fam, planned)
        # a LOWER bound: it may under-predict by a floor, never over-predict
        assert got <= built + 1.0, (fam, planned, got, built)
        assert built - got <= 325.0 + 1.0, (fam, planned, got, built)
        exact += abs(got - built) < 1.0
    assert exact >= 8      # only NYAE 3074 sits on the bracketed boundary
    # SFD now has a MEASURED row, so it is held to the same lower-bound
    # contract as the retired families: never over-predict, and never by more
    # than one floor.
    for planned, built in ((3400.0, 3634.8), (4200.0, 4414.8),
                           (5000.0, 5194.8), (6500.0, 6624.8),
                           (9000.0, 9224.8)):
        got = predicted_top_cm("SFD", planned)
        assert got <= built + 1.0, (planned, got, built)
        assert built - got <= 130.0 + 1.0, (planned, got, built)
    # a family outside the palette and outside the ladder is still answered
    # with the plan; a family INSIDE the palette without a row must raise.
    assert predicted_top_cm("NOT_A_FAMILY", 2500.0) == 2500.0


def test_snap_to_floors_only_raises_and_clears_the_fidelity_gate():
    from ldyf.sgd_buildings import predicted_top_cm, snap_to_floors
    doc = make_doc()
    target = next(o for o in doc["orders"] if o["role"] != "landmark")
    target["family"] = "NYAE"
    target["height_cm"] = 2930.0          # the exact case that failed: 0.887
    before = copy.deepcopy(doc)
    snapped = snap_to_floors(doc)
    assert doc == before                  # input untouched
    for a, b in zip(doc["orders"], snapped["orders"]):
        assert b["height_cm"] >= a["height_cm"]
        if b["role"] == "landmark":
            assert b["height_cm"] == a["height_cm"]
        if b["family"] in ("NYAE", "NYAF") and b["role"] != "landmark":
            ratio = predicted_top_cm(b["family"], b["height_cm"]) / b["height_cm"]
            assert ratio >= 0.92, (b["id"], ratio)
    moved = [s for s in snapped["floor_snaps"] if s["id"] == target["id"]]
    assert moved and moved[0]["height_cm"] == 3095.0   # 150 + 9 floors + 20
    with pytest.raises(ValueError):
        snap_to_floors({"orders": []})


# ---------------------------------------------------------------------------
# red team (2026-10-02)
# ---------------------------------------------------------------------------


def test_banding_refuses_to_invert_the_landmark_hierarchy():
    # the landmark is pinned to the top of its band; never_lower keeps an
    # ordinary order where it came in. A very tall ordinary order would end up
    # above the landmark, so that input must raise instead.
    from ldyf.sgd_buildings import LANDMARK_HEIGHT_BAND_CM, apply_height_bands
    doc = make_doc()
    tall = next(o for o in doc["orders"] if o["role"] != "landmark")
    tall["height_cm"] = LANDMARK_HEIGHT_BAND_CM[1] + 500.0
    with pytest.raises(ValueError, match="at or above the landmark"):
        apply_height_bands(doc, never_lower=True)
    # without never_lower the ordinary order is banded down and it is fine
    out = apply_height_bands(doc)
    lm = next(o for o in out["orders"] if o["role"] == "landmark")
    assert all(o["height_cm"] < lm["height_cm"]
               for o in out["orders"] if o["role"] != "landmark")


def test_snap_to_floors_refuses_a_non_positive_height():
    from ldyf.sgd_buildings import snap_to_floors
    doc = make_doc()
    doc["orders"][0]["height_cm"] = 0.0
    with pytest.raises(ValueError, match="non-positive height"):
        snap_to_floors(doc)


def test_every_palette_family_has_a_measured_floor_ladder():
    # The hole both p2p_atk adversaries found: a family in the palette with no
    # ladder row skipped height snapping silently. The invariant that closes it
    # is this one, and it must hold for whatever the palette becomes.
    from ldyf.sgd_buildings import FLOOR_LADDER_CM
    missing = sorted(set(SGD_PALETTE) - set(FLOOR_LADDER_CM))
    assert missing == [], missing


def test_predicted_top_refuses_a_palette_family_without_a_ladder(monkeypatch):
    import ldyf.sgd_buildings as sb
    monkeypatch.setitem(sb.SGD_PALETTE, "ZZZ", {"role_band": "test",
                                                "instances": 1,
                                                "landmark_only": False})
    with pytest.raises(ValueError, match="no FLOOR_LADDER_CM row"):
        sb.predicted_top_cm("ZZZ", 3000.0)
    doc = make_doc()
    doc["orders"][0]["family"] = "ZZZ"
    with pytest.raises(ValueError, match="no FLOOR_LADDER_CM row"):
        sb.snap_to_floors(doc)


def test_snap_to_floors_does_not_move_the_production_palette():
    # SFD has a measured row now, but it builds TALLER than asked at every
    # production height (ratio 1.019-1.069), so nothing is ever snapped. This
    # asserts the outcome, not the absence of a table row.
    from ldyf.sgd_buildings import snap_to_floors
    doc = make_doc()
    out = snap_to_floors(doc)
    assert out["floor_snaps"] == []
    assert [o["height_cm"] for o in out["orders"]] == \
        [o["height_cm"] for o in doc["orders"]]
