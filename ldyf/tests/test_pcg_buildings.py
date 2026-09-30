"""Tests for ``ldyf.pcg_buildings`` -- the per-building PCG order sheet.

The fixture is built the way ``test_city_layout`` builds it: a hand-made road
lattice (``make_lattice_spec``, copied from ``test_building_integration``) run
through ``city_layout.blocks`` and ``city_layout.building_slots``, so the slots
are real generated frontage slots with real ids and yaws rather than a
convenient toy.

One deviation, stated: the fixture passes ``spacing_cm=4000`` to
``building_slots`` so that neighbouring frontage footprints can only ever touch.
With the default spacing (2000 cm) ``frontages`` starts a slot ``spacing/2`` from
every block corner, so the last slot of an edge can come within
``(seg - s)/2 + spacing/4`` of the corner -- which at the default spacing can be
as little as 1000 cm, less than the 1200 cm footprint depth used here.  The
strict "no two footprints overlap" assertions below are about *this module*, not
about the generator's corner arithmetic, so the fixture takes the margin.

Nothing here executes PCG or Unreal; these are the decisions (winding, closure,
roles, levels) that a driver would hand to it.
"""

from __future__ import annotations

import copy

import pytest

from ldyf.city_layout import blocks, building_slots
from ldyf.pcg_buildings import (
    SCHEMA_VERSION,
    _as_pairs,
    _ring_self_intersects,
    _signed_area,
    building_orders,
    to_spline_points,
    validate_orders,
)
from ldyf.street_life_inputs import attach_road_spec, building_footprint

DEPTH_CM = 1200.0
SEED = 11
SPACING_CM = 4000.0
ORDER_KEYS = {"id", "block_id", "footprint", "height_cm", "levels", "style",
              "rule_asset", "family", "role", "seed", "yaw_deg"}


# ---------------------------------------------------------------- fixtures --

def _pt(x, y):
    return {"x": float(x), "y": float(y), "z": 0.0}


def make_lattice_spec(n_x: int, n_y: int, *, step_cm: float = 20000.0,
                      lane_width: float = 200.0, disallow=None) -> dict:
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
                                 "allow": None, "disallow": disallow,
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
    return building_orders(layout, depth_cm=kw.pop("depth_cm", DEPTH_CM),
                           seed=kw.pop("seed", SEED), **kw)


def ring_of(order: dict) -> list:
    """The open (cyclic) ring of an order's closed footprint."""
    fp = order["footprint"]
    return _as_pairs(fp[:-1] if fp[0] == fp[-1] else fp)


def slots_by_id(layout: dict) -> dict:
    return {str(s["slot_id"]): s for s in layout["building_slots"]["slots"]}


def centre_of(ring: list) -> tuple:
    return (sum(p[0] for p in ring) / len(ring),
            sum(p[1] for p in ring) / len(ring))


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


# ------------------------------------------------------- the order document --

def test_document_and_order_shape():
    doc = make_doc()
    assert doc["schema_version"] == SCHEMA_VERSION
    assert {"schema_version", "orders", "landmark_id", "counts"} <= set(doc)
    assert doc["orders"], "no orders emitted"
    for order in doc["orders"]:
        assert set(order) == ORDER_KEYS
        assert isinstance(order["id"], str) and order["id"]
        assert order["role"] in ("ordinary", "landmark")
        assert order["family"] and order["style"] and order["rule_asset"]
        assert isinstance(order["levels"], int) and order["levels"] >= 1
    assert doc["counts"] == {"orders": len(doc["orders"]),
                             "ordinary": sum(1 for o in doc["orders"]
                                             if o["role"] == "ordinary"),
                             "landmark": sum(1 for o in doc["orders"]
                                             if o["role"] == "landmark")}


def test_document_carries_no_geometry():
    """Epic's system makes the geometry; this module must not."""
    doc = make_doc()
    banned = ("triangle", "vertex", "vertices", "mesh", "material", "pbr",
              ".fbx", ".obj", ".uasset")
    for order in doc["orders"]:
        for key, value in order.items():
            assert not any(w in key.lower() for w in banned), key
            if isinstance(value, str):
                assert not any(w in value.lower() for w in banned), value


def test_orders_are_deterministic_and_do_not_touch_the_layout():
    layout = make_layout()
    frozen = copy.deepcopy(layout)
    a = building_orders(layout, depth_cm=DEPTH_CM, seed=SEED)
    b = building_orders(copy.deepcopy(layout), depth_cm=DEPTH_CM, seed=SEED)
    assert a == b
    assert layout == frozen
    assert [o["seed"] for o in a["orders"]] == \
        [o["seed"] for o in b["orders"]]


# ------------------------------------------------------------- the winding --

def test_every_footprint_is_closed_ccw_and_not_self_intersecting():
    doc = make_doc()
    for order in doc["orders"]:
        fp = order["footprint"]
        assert len(fp) >= 4, order["id"]
        assert _as_pairs([fp[0]])[0] == _as_pairs([fp[-1]])[0], order["id"]
        ring = ring_of(order)
        assert len(ring) == 4  # city_layout slots are rectangles
        assert _signed_area(ring) > 0.0, "wound clockwise: %s" % order["id"]
        assert not _ring_self_intersects(ring), order["id"]
        # deterministic start: the lexicographically smallest corner
        assert min(range(len(ring)), key=lambda i: tuple(ring[i])) == 0


def test_north_and_south_frontages_wind_the_same_way():
    """Hand-check of the winding sign, north-facing vs south-facing."""
    layout = two_slot_layout()
    doc = building_orders(layout, depth_cm=DEPTH_CM, seed=5)
    raw = {s["slot_id"]: _as_pairs(building_footprint(s, depth_cm=DEPTH_CM))
           for s in layout["building_slots"]["slots"]}
    # the shared helper emits the same (clockwise) sign for both frontages ...
    assert _signed_area(raw["north:f0"]) < 0.0
    assert _signed_area(raw["south:f0"]) < 0.0
    assert _signed_area(raw["north:f0"]) == _signed_area(raw["south:f0"])
    # ... and every order is normalised to the same positive sign.
    areas = {o["id"]: _signed_area(ring_of(o)) for o in doc["orders"]}
    assert set(areas) == {"north:f0", "south:f0"}
    assert all(a > 0.0 for a in areas.values())
    assert areas["north:f0"] == areas["south:f0"] == 900.0 * DEPTH_CM * 2.0


def test_footprint_is_the_slot_rectangle_facing_the_street():
    layout = make_layout()
    doc = building_orders(layout, depth_cm=DEPTH_CM, seed=SEED)
    by_id = slots_by_id(layout)
    for order in doc["orders"]:
        slot = by_id[order["id"]]
        ring = ring_of(order)
        lengths = [(((ring[(i + 1) % 4][0] - ring[i][0]) ** 2
                     + (ring[(i + 1) % 4][1] - ring[i][1]) ** 2) ** 0.5)
                   for i in range(4)]
        # ADJACENT edges carry the two dimensions; edges 0 and 2 are OPPOSITE
        # sides of a rectangle and are therefore equal, which the next
        # assertion states. Comparing 0 and 2 against {width, depth} could only
        # hold if width == depth, so the two assertions contradicted each other.
        assert sorted([lengths[0], lengths[1]]) == \
            pytest.approx(sorted([float(slot["width_cm"]), DEPTH_CM]), abs=0.02)
        assert lengths[0] == pytest.approx(lengths[2], abs=0.02)   # rectangle
        assert lengths[1] == pytest.approx(lengths[3], abs=0.02)   # rectangle
        mids = [((ring[i][0] + ring[(i + 1) % 4][0]) / 2.0,
                 (ring[i][1] + ring[(i + 1) % 4][1]) / 2.0) for i in range(4)]
        near = min(((m[0] - slot["x"]) ** 2 + (m[1] - slot["y"]) ** 2) ** 0.5
                   for m in mids)
        assert near <= 0.002, (order["id"], near)  # frontage on the slot point


def test_no_two_footprints_overlap():
    doc = make_doc()
    assert validate_orders(doc) == []
    # independent check: axis-aligned bounding boxes of the lattice rectangles
    boxes = []
    for order in doc["orders"]:
        ring = ring_of(order)
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


def test_exactly_one_landmark_and_it_is_the_tallest():
    doc = make_doc()
    landmarks = [o for o in doc["orders"] if o["role"] == "landmark"]
    assert len(landmarks) == 1
    assert doc["landmark_id"] == landmarks[0]["id"]
    assert doc["counts"]["landmark"] == 1
    ordinary = [o for o in doc["orders"] if o["role"] == "ordinary"]
    assert ordinary
    assert landmarks[0]["height_cm"] >= 5600.0
    assert landmarks[0]["height_cm"] > max(o["height_cm"] for o in ordinary)


# ------------------------------------------------------------ spline export --

def test_to_spline_points_round_trips_the_footprint():
    doc = make_doc()
    for order in doc["orders"]:
        pts = to_spline_points(order)
        assert pts == [list(p) for p in order["footprint"]]
        assert pts[0] == pts[-1]                       # closed loop
        assert len(pts) == 5
        assert pts.index(pts[0]) == 0                  # start corner is first
        assert _signed_area(pts[:-1]) > 0.0            # same ccw ring


# ---------------------------------------------------------------- validation --

def test_validate_catches_a_bowtie_footprint():
    doc = copy.deepcopy(make_doc())
    doc["orders"][0]["footprint"] = [[0.0, 0.0], [6.0, 6.0], [10.0, 0.0],
                                     [0.0, 10.0], [0.0, 0.0]]
    problems = validate_orders(doc)
    assert any("self-intersect" in p for p in problems), problems


def test_validate_catches_a_nested_loop_z_footprint():
    """The other historical shape: a Z-ordered quad (a degenerate bowtie)."""
    doc = copy.deepcopy(make_doc())
    doc["orders"][1]["footprint"] = [[0.0, 0.0], [10.0, 0.0], [0.0, 10.0],
                                     [10.0, 10.0], [0.0, 0.0]]
    problems = validate_orders(doc)
    assert any("self-intersect" in p or "degenerate" in p
               for p in problems), problems


def test_validate_catches_an_unclosed_footprint():
    doc = copy.deepcopy(make_doc())
    doc["orders"][0]["footprint"] = doc["orders"][0]["footprint"][:-1]
    assert any("not closed" in p for p in validate_orders(doc))


def test_validate_catches_clockwise_winding():
    doc = copy.deepcopy(make_doc())
    ring = ring_of(doc["orders"][0])
    doc["orders"][0]["footprint"] = [list(p) for p in reversed(ring)] + \
        [list(ring[-1])]
    assert any("clockwise" in p for p in validate_orders(doc))


def test_validate_catches_overlapping_footprints():
    doc = copy.deepcopy(make_doc())
    doc["orders"][1]["footprint"] = copy.deepcopy(doc["orders"][0]["footprint"])
    problems = validate_orders(doc)
    assert any("overlap" in p for p in problems), problems


def test_validate_catches_a_non_positive_height():
    doc = copy.deepcopy(make_doc())
    doc["orders"][0]["height_cm"] = 0.0
    assert any("height_cm must be positive" in p for p in validate_orders(doc))


def test_validate_catches_landmark_count():
    none = copy.deepcopy(make_doc())
    for order in none["orders"]:
        order["role"] = "ordinary"
    assert any("exactly one landmark" in p for p in validate_orders(none))

    two = copy.deepcopy(make_doc())
    two["orders"][0]["role"] = "landmark"
    assert any("exactly one landmark" in p for p in validate_orders(two))


def test_validate_catches_a_level_outside_the_style():
    def resolver(*, family, height_cm):
        return {"style": "CS_%s" % family, "rule_asset": "/Game/CS/%s" % family,
                "levels": 3, "min_levels": 2, "max_levels": 6}

    doc = make_doc(style_resolver=resolver)
    assert validate_orders(doc) == []
    assert all(o["style"].startswith("CS_") for o in doc["orders"])
    assert all(o["levels"] == 3 for o in doc["orders"])
    assert doc["style_limits"][doc["orders"][0]["style"]] == \
        {"min_levels": 2, "max_levels": 6}
    doc["orders"][0]["levels"] = 40
    assert any("outside what style" in p for p in validate_orders(doc))


def test_validate_catches_a_footprint_on_a_carriageway_lane():
    doc = copy.deepcopy(make_doc())
    assert "carriageway_lanes" not in doc
    cx, cy = centre_of(ring_of(doc["orders"][0]))
    doc["carriageway_lanes"] = [[[cx - 10.0, cy - 10.0], [cx + 10.0, cy - 10.0],
                                 [cx + 10.0, cy + 10.0], [cx - 10.0, cy + 10.0]]]
    problems = validate_orders(doc)
    assert any("carriageway lane" in p for p in problems), problems


def test_lane_bands_are_taken_from_the_layout_road_spec():
    layout = make_layout()
    doc = building_orders(layout, depth_cm=DEPTH_CM, seed=SEED)
    cx, cy = centre_of(ring_of(doc["orders"][0]))
    spec = make_lattice_spec(3, 3, disallow=["pedestrian"])
    lane = spec["edges"][0]["lanes"][0]
    lane["width_cm"] = lane["width_cm_effective"] = 300.0
    lane["polyline"] = [_pt(cx - 5000.0, cy), _pt(cx + 5000.0, cy)]
    attached = attach_road_spec(layout, spec)
    doc = building_orders(attached, depth_cm=DEPTH_CM, seed=SEED)
    assert doc["carriageway_lanes"], "road spec lanes were not picked up"
    assert any("carriageway lane" in p for p in validate_orders(doc))


def test_validate_rejects_an_empty_document():
    assert validate_orders({"schema_version": SCHEMA_VERSION, "orders": []})


# ------------------------------------------------------------- style shapes --

def test_style_resolver_shapes():
    def positional_only(family, height_cm, /):
        return "CS_POS_%s" % family, 4

    def returns_none(*, family, height_cm):
        return None

    doc = make_doc(style_resolver=positional_only)
    assert all(o["style"].startswith("CS_POS_") for o in doc["orders"])
    assert all(o["levels"] == 4 for o in doc["orders"])
    assert "style_limits" not in doc

    doc = make_doc(style_resolver=returns_none)
    assert all(o["style"].startswith("fallback_style::") for o in doc["orders"])

    plain = make_doc()
    assert plain == make_doc(style_resolver=None)
    assert all(o["rule_asset"].startswith("pcg_building_rule::")
               for o in plain["orders"])


# -------------------------------------------------------------- ValueError --

def test_value_errors():
    layout = make_layout()
    with pytest.raises(ValueError):
        building_orders(layout, depth_cm=0.0, seed=SEED)
    with pytest.raises(ValueError):
        building_orders(layout, depth_cm=-1200.0, seed=SEED)
    empty = copy.deepcopy(layout)
    empty["building_slots"]["slots"] = []
    with pytest.raises(ValueError):
        building_orders(empty, depth_cm=DEPTH_CM, seed=SEED)
    with pytest.raises(ValueError):
        building_orders({"schema_version": "city_layout_v1"},
                        depth_cm=DEPTH_CM, seed=SEED)
