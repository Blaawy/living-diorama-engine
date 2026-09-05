"""Tests for ``ldyf.street_life`` (schema ``street_life_v1``).

Fixtures are hand-built plain dicts in the same shapes ``city_layout`` and
``roads`` produce: blocks with polygon + centre, building slots with x/y/yaw,
a road spec whose normal edges carry a car lane and a sidewalk lane, crossing
edges for the crosswalk exclusions, and building records with roof polygons.
"""

from __future__ import annotations

import json
import math

import pytest

from ldyf.street_life import (
    STREET_LIFE_VERSION,
    build_street_life,
    conflicts,
    parked_cars,
    rooftop_props,
    sign_slots,
    storefront_slots,
)


def _pt(x, y):
    return {"x": float(x), "y": float(y)}


def _rect_corners(x, y, yaw_deg, width, depth, offset_along=0.0):
    """Same corner convention as the module (tests recompute independently)."""
    r = math.radians(yaw_deg)
    ux, uy = math.cos(r), math.sin(r)
    px, py = -uy, ux
    cx, cy = x + ux * offset_along, y + uy * offset_along
    hw, hd = width / 2.0, depth / 2.0
    return [(cx + ux * sd * hd + px * sa * hw,
             cy + uy * sd * hd + py * sa * hw)
            for sd in (-1.0, 1.0) for sa in (-1.0, 1.0)]


def _xy(p):
    """Polygon points are ``{x, y}`` dicts -- the format street_life documents
    and _roof_rect builds. Indexing them as tuples raises KeyError, which is
    what these helpers used to do."""
    if isinstance(p, dict):
        return (float(p["x"]), float(p["y"]))
    return (float(p[0]), float(p[1]))


def _point_in_poly(px, py, poly):
    inside = False
    n = len(poly)
    for i in range(n):
        ax, ay = _xy(poly[i])
        bx, by = _xy(poly[(i + 1) % n])
        if (ay > py) != (by > py):
            x_at = ax + (py - ay) * (bx - ax) / (by - ay)
            if x_at > px:
                inside = not inside
    return inside


def _dist_pt_seg(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 <= 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / l2
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


# --- storefront fixtures -----------------------------------------------------


def _block_layout():
    """One 3000x3000 block with one building slot per edge (edge midpoints).

    Block centre (1500, 1500).  Outward directions are known: top edge faces
    -y (yaw -90), right edge +x (yaw 0), bottom +y (yaw 90), left -x (yaw 180).
    """
    poly = [_pt(0, 0), _pt(3000, 0), _pt(3000, 3000), _pt(0, 3000)]
    block = {"id": "block_0_0", "polygon": poly,
             "centre": {"x": 1500.0, "y": 1500.0},
             "bbox": {"x_min": 0.0, "x_max": 3000.0,
                      "y_min": 0.0, "y_max": 3000.0}}
    slots = [
        {"slot_id": "block_0_0:f0", "block_id": "block_0_0",
         "x": 1500.0, "y": 0.0, "yaw": -90.0, "width_cm": 2000.0},
        {"slot_id": "block_0_0:f1", "block_id": "block_0_0",
         "x": 3000.0, "y": 1500.0, "yaw": 0.0, "width_cm": 2000.0},
        {"slot_id": "block_0_0:f2", "block_id": "block_0_0",
         "x": 1500.0, "y": 3000.0, "yaw": 90.0, "width_cm": 2000.0},
        {"slot_id": "block_0_0:f3", "block_id": "block_0_0",
         "x": 0.0, "y": 1500.0, "yaw": 180.0, "width_cm": 2000.0},
    ]
    return {"blocks": [block], "building_slots": {"slots": slots},
            "furniture_slots": {"slots": []}, "crossing_slots": {"slots": []}}


def _sign_fixture(footway_cm=180.0, n=24, seed=0):
    """Storefronts all on one wall: x=0, yaw=90 (facing +y).  The kerb is at
    y = footway_cm, so a projecting sign of ``projection_cm`` reaches y =
    projection_cm at most; anything above ``footway_cm`` would be over the
    carriageway."""
    return [{"id": "sf_%d" % i, "x": 100.0 * i, "y": 0.0,
             "yaw_deg": 90.0, "kind": "entrance", "width_cm": 200.0,
             "depth_cm": 60.0, "footway_cm": float(footway_cm)}
            for i in range(n)]


# --- roof fixtures -----------------------------------------------------------


def _roof_rect(x0, y0, x1, y1):
    return [_pt(x0, y0), _pt(x1, y0), _pt(x1, y1), _pt(x0, y1)]


# --- road spec fixtures for parked cars --------------------------------------


def _car_lane(lid, index, x, width=400.0):
    return {"id": lid, "index": index, "width_cm": width,
            "width_cm_effective": width, "width_source": "attribute",
            "speed_mps": 13.89, "length_m": 60.0,
            "allow": None, "disallow": ["pedestrian"],
            "polyline": [_pt(x, 0), _pt(x, 6000)]}


def _walk_lane(lid, index, x, width=200.0):
    return {"id": lid, "index": index, "width_cm": width,
            "width_cm_effective": width, "width_source": "attribute",
            "speed_mps": 0.0, "length_m": 60.0,
            "allow": ["pedestrian"], "disallow": [],
            "polyline": [_pt(x, 0), _pt(x, 6000)]}


def _crossing_lane():
    # crossing spanning the carriageway at y=3000, along x (perpendicular to
    # the north-running car lane), depth (width) 400 cm along travel
    return {"id": "X_0", "index": 0, "width_cm": 400.0,
            "width_cm_effective": 400.0, "width_source": "attribute",
            "speed_mps": 0.0, "length_m": 6.0,
            "allow": ["pedestrian"], "disallow": None,
            "polyline": [_pt(0, 3000), _pt(400, 3000)]}


def _parking_spec(with_crossing=False):
    """Road ``N`` running north along x=0 between J0=(0,0) and J1=(0,6000).

    Car lane ``N_c``: centre x=0, width 400 (spans x -200..200).  Sidewalk
    lane ``N_w``: centre x=350, width 200 (spans 250..450).  The kerb is the
    car lane's outer edge at x=200; the sidewalk sits toward +x.
    """
    junctions = [{"id": "J0", "type": "priority",
                  "position": _pt(0, 0), "polygon": None,
                  "incoming_edge_ids": []},
                 {"id": "J1", "type": "priority",
                  "position": _pt(0, 6000), "polygon": None,
                  "incoming_edge_ids": []}]
    edges = [{"id": "N", "from_junction": "J0", "to_junction": "J1",
              "function": "normal", "priority": 1,
              "lanes": [_car_lane("N_c", 0, 0), _walk_lane("N_w", 1, 350)]}]
    if with_crossing:
        edges.append({"id": "X", "from_junction": "J0", "to_junction": "J0",
                      "function": "crossing", "priority": 1,
                      "lanes": [_crossing_lane()]})
    return {"schema_version": "road_spec_v1", "edges": edges,
            "junctions": junctions,
            "counts": {"edges": len(edges), "junctions": len(junctions)}}


def _parking_layout(with_crossing=False, closed=(), spec=None):
    return {"blocks": [], "building_slots": {"slots": []},
            "furniture_slots": {"slots": []},
            "crossing_slots": {"slots": []},
            "spec": _parking_spec(with_crossing) if spec is None else spec,
            "closed_edge_ids": sorted(str(e) for e in closed)}


# --- 1. determinism ----------------------------------------------------------

def test_build_street_life_deterministic():
    layout = _block_layout()
    layout["spec"] = _parking_spec()
    buildings = [{"id": "b0", "polygon": _roof_rect(0, 0, 3000, 3000)}]
    existing = [{"id": "furn0", "x": 500.0, "y": 500.0, "kind": "lamp",
                 "lane_id": "N_w", "distance_cm": 200.0, "offset_cm": 250.0}]
    a = build_street_life(layout, buildings, existing, seed=7)
    b = build_street_life(layout, buildings, existing, seed=7)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["schema_version"] == STREET_LIFE_VERSION
    for key in ("storefronts", "signs", "rooftop_props", "parked_cars"):
        assert a["counts"][key] == len(a[key])


def test_schema_keys_and_sorted_ids():
    layout = _block_layout()
    layout["spec"] = _parking_spec()
    doc = build_street_life(
        layout, [{"id": "b0", "polygon": _roof_rect(0, 0, 3000, 3000)}],
        existing=None, seed=1)
    assert set(doc.keys()) == {"schema_version", "params", "storefronts",
                               "signs", "rooftop_props", "parked_cars",
                               "counts", "conflicts"}
    for rows in (doc["storefronts"], doc["signs"], doc["rooftop_props"],
                 doc["parked_cars"]):
        ids = [r["id"] for r in rows]
        assert ids == sorted(ids)
    assert "conflict_pairs" in doc["counts"]


# --- 2. storefront yaw faces the street --------------------------------------

def test_storefront_yaw_points_outward_from_known_frontages():
    """For each block edge the outward direction is known (block centre at
    (1500, 1500), so: top -y/-90, right +x/0, bottom +y/90, left -x/180)."""
    layout = _block_layout()
    rows = storefront_slots(layout, spacing_cm=100.0, setback_cm=0.0, seed=0)
    by_id = {r["id"]: r for r in rows}
    assert set(by_id) == {"storefront_block_0_0:f0", "storefront_block_0_0:f1",
                          "storefront_block_0_0:f2", "storefront_block_0_0:f3"}
    expected_yaw = {"block_0_0:f0": -90.0, "block_0_0:f1": 0.0,
                    "block_0_0:f2": 90.0, "block_0_0:f3": 180.0}
    centre = (1500.0, 1500.0)
    for slot_suffix, yaw in expected_yaw.items():
        r = by_id["storefront_%s" % slot_suffix]
        assert r["yaw_deg"] == pytest.approx(yaw)
        # the sign of the result: yaw points AWAY from the block centre
        ux, uy = math.cos(math.radians(r["yaw_deg"])), \
            math.sin(math.radians(r["yaw_deg"]))
        outward = (r["x"] - centre[0]) * ux + (r["y"] - centre[1]) * uy
        assert outward > 0.0
        assert r["block_id"] == "block_0_0"
        assert r["width_cm"] > 0.0
        assert r["kind"] in ("entrance", "shopfront")


def test_storefront_yaw_rejects_slot_glued_to_wrong_edge():
    """A slot whose yaw points INTO the block (inward) must be dropped, not
    emitted facing the wrong way."""
    layout = _block_layout()
    # slot sits on the top edge but its yaw points +y (into the block)
    layout["building_slots"]["slots"].append(
        {"slot_id": "block_0_0:bad", "block_id": "block_0_0",
         "x": 1500.0, "y": 0.0, "yaw": 90.0, "width_cm": 2000.0})
    rows = storefront_slots(layout, spacing_cm=100.0, setback_cm=0.0, seed=0)
    ids = [r["id"] for r in rows]
    assert "storefront_block_0_0:bad" not in ids


def test_storefront_spacing_and_corner_setback():
    layout = _block_layout()
    # two slots on the same (top) edge, 1000 cm apart: with spacing 6000 only
    # the first one may survive
    layout["building_slots"]["slots"] = [
        {"slot_id": "block_0_0:a", "block_id": "block_0_0",
         "x": 500.0, "y": 0.0, "yaw": -90.0, "width_cm": 2000.0},
        {"slot_id": "block_0_0:b", "block_id": "block_0_0",
         "x": 1500.0, "y": 0.0, "yaw": -90.0, "width_cm": 2000.0},
    ]
    sparse = storefront_slots(layout, spacing_cm=6000.0, setback_cm=0.0, seed=0)
    assert len(sparse) == 1
    dense = storefront_slots(layout, spacing_cm=800.0, setback_cm=0.0, seed=0)
    assert len(dense) == 2
    # corner setback: slot 200 cm from a corner is refused
    layout["building_slots"]["slots"] = [
        {"slot_id": "block_0_0:c", "block_id": "block_0_0",
         "x": 200.0, "y": 0.0, "yaw": -90.0, "width_cm": 2000.0}]
    assert storefront_slots(layout, spacing_cm=800.0, setback_cm=400.0,
                            seed=0) == []
    assert len(storefront_slots(layout, spacing_cm=800.0, setback_cm=100.0,
                                seed=0)) == 1


# --- 3. projecting signs never cross the kerb --------------------------------

def test_projecting_sign_clamped_to_footway_never_crosses_kerb():
    footway = 180.0  # kerb line at y=footway from the facade (y=0)
    sf_rows = _sign_fixture(footway_cm=footway, n=64, seed=0)
    signs = sign_slots(sf_rows, seed=0, sign_share=1.0)
    assert signs
    projecting = [s for s in signs if s["kind"] == "projecting"]
    assert projecting  # deterministic; astronomically unlikely to be empty
    for s in projecting:
        assert s["projection_cm"] <= footway + 1e-6  # the clamp
        assert s["y"] + s["projection_cm"] <= footway + 1e-6  # tip <= kerb
    for s in signs:
        assert s["height_cm"] >= 0.0
        assert s["storefront_id"].startswith("sf_")


def test_projecting_sign_clamped_hard_for_narrow_footway():
    """A storefront on a 90 cm footway must never emit a >90 cm projection,
    even though the desired projection range starts at 120 cm."""
    sf_rows = _sign_fixture(footway_cm=90.0, n=64, seed=3)
    signs = sign_slots(sf_rows, seed=3, sign_share=1.0)
    projecting = [s for s in signs if s["kind"] == "projecting"]
    assert projecting
    assert all(s["projection_cm"] <= 90.0 + 1e-6 for s in projecting)


# --- 4. rooftop props --------------------------------------------------------

def _corner_clearance(corners, poly):
    best = float("inf")
    for (x, y) in corners:
        for a, b in zip(poly, poly[1:] + poly[:1]):
            ax, ay = _xy(a)
            bx, by = _xy(b)
            d = _dist_pt_seg(x, y, ax, ay, bx, by)
            best = min(best, d)
    return best


def test_rooftop_props_inside_inset_polygon_and_separated():
    margin = 60.0
    poly = _roof_rect(0, 0, 10000, 8000)
    buildings = [{"id": "big", "polygon": poly}]
    props = rooftop_props(buildings, seed=0, margin_cm=margin,
                          max_per_roof=4)
    assert 2 <= len(props) <= 4
    for p in props:
        corners = _rect_corners(p["x"], p["y"], p["yaw_deg"],
                                p["width_cm"], p["depth_cm"])
        assert all(_point_in_poly(x, y, poly) for (x, y) in corners)
        # every footprint corner is at least margin off the parapet edge
        assert _corner_clearance(corners, poly) >= margin - 1e-6
    # mutual separation: circumcircles (half diagonals) never intersect
    for i in range(len(props)):
        for j in range(i + 1, len(props)):
            a, b = props[i], props[j]
            ra = math.hypot(a["width_cm"], a["depth_cm"]) / 2.0
            rb = math.hypot(b["width_cm"], b["depth_cm"]) / 2.0
            d = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
            assert d + 1e-6 >= ra + rb


def test_rooftop_props_small_roof_one_prop_deterministic():
    buildings = [{"id": "small", "polygon": _roof_rect(0, 0, 2000, 2000)}]
    p0 = rooftop_props(buildings, seed=0)
    assert len(p0) == 1
    # same seed -> identical; different seed -> still one prop on this roof
    p0b = rooftop_props(buildings, seed=0)
    p1 = rooftop_props(buildings, seed=99)
    assert json.dumps(p0, sort_keys=True) == json.dumps(p0b, sort_keys=True)
    assert len(p1) == 1


def test_rooftop_props_missing_polygon_raises():
    with pytest.raises(ValueError):
        rooftop_props([{"id": "no_poly"}], seed=0)


# --- 5. parked cars ----------------------------------------------------------

def _car_t(car):
    """Along-lane parameter t of a car: for the vertical lane N the car centre
    y equals the along-lane distance from the lane start (0, 0)."""
    return car["y"]


def test_parked_cars_full_occupancy_gaps_and_junction_clear():
    layout = _parking_layout(with_crossing=False)
    cars = parked_cars(layout, occupancy=1.0, seed=0)
    # legal run t in [900, 5100], step 460+80=540: 8 candidates
    assert len(cars) == 8
    ts = sorted(_car_t(c) for c in cars)
    for t in ts:
        assert 900.0 - 1e-6 <= t <= 5100.0 + 1e-6
    # aligned with the lane direction: lane runs north (+y) -> yaw 90
    for c in cars:
        assert c["yaw_deg"] == pytest.approx(90.0)
        assert c["edge_id"] == "N"
    # never overlap: bumper-to-bumper gap >= 80 cm, i.e. centre distance 540
    for a, b in zip(cars, cars[1:]):
        assert math.hypot(a["x"] - b["x"], a["y"] - b["y"]) >= 539.0
    # kerb band: car spans x -5..185, kerb at x=200 (15 cm clear, never on the
    # pavement, never beyond the road edge)
    for c in cars:
        assert abs(c["x"] - 90.0) < 1e-6
        assert c["length_cm"] == pytest.approx(460.0)
        assert c["variant"] in ("sedan", "hatch", "suv", "compact")


def test_parked_cars_occupancy_subset_and_value_errors():
    layout = _parking_layout()
    assert parked_cars(layout, occupancy=0.0, seed=0) == []
    cars_half = parked_cars(layout, occupancy=0.5, seed=0)
    assert len(cars_half) == 4  # round(0.5 * 8)
    ts = sorted(_car_t(c) for c in cars_half)
    assert ts == [900.0, 1980.0, 3060.0, 4140.0]  # indices 0,2,4,6 of 8
    with pytest.raises(ValueError):
        parked_cars(layout, occupancy=-0.1, seed=0)
    with pytest.raises(ValueError):
        parked_cars(layout, occupancy=1.5, seed=0)


def test_parked_cars_never_on_crosswalk():
    layout = _parking_layout(with_crossing=True)
    cars = parked_cars(layout, occupancy=1.0, seed=0)
    # crossing at t=3000, depth 400: excluded band is
    # [3000 - 200 - 100 - 230, 3000 + 200 + 100 + 230] = [2470, 3530]
    for c in cars:
        t = _car_t(c)
        assert not (2470.0 - 1e-6 <= t <= 3530.0 + 1e-6)
    assert len(cars) == 6  # 2520 and 3060 removed from the 8 candidates


def test_parked_cars_never_in_junction_or_closure_zone():
    # closure zone: edge sealed -> no cars at all on it
    layout = _parking_layout(closed=("N",))
    assert parked_cars(layout, occupancy=1.0, seed=0) == []
    # without a spec the kerb is unknowable: documented, nothing placed
    no_spec = {k: v for k, v in _parking_layout().items() if k != "spec"}
    assert parked_cars(no_spec, occupancy=1.0, seed=0) == []


# --- 6. conflicts ------------------------------------------------------------

def test_conflicts_finds_planted_overlap_and_stays_quiet_when_clear():
    a = {"id": "a", "x": 0.0, "y": 0.0, "yaw_deg": 0.0,
         "width_cm": 200.0, "depth_cm": 100.0}
    b = {"id": "b", "x": 40.0, "y": 0.0, "yaw_deg": 0.0,
         "width_cm": 200.0, "depth_cm": 100.0}   # overlaps a
    c = {"id": "c", "x": 5000.0, "y": 5000.0, "yaw_deg": 0.0,
         "width_cm": 200.0, "depth_cm": 100.0}   # far away
    rows = conflicts([a, b, c])
    assert any(r["id_a"] == "a" and r["id_b"] == "b" for r in rows)
    assert not any("c" in (r["id_a"], r["id_b"]) for r in rows)


def test_conflicts_against_existing_furniture_doc():
    storefront = {"id": "sf1", "x": 0.0, "y": 0.0, "yaw_deg": 90.0,
                  "width_cm": 260.0, "depth_cm": 60.0}
    furn_doc = {"schema_version": "city_layout_v1",
                "slots": [{"id": "lamp1", "x": 5.0, "y": 0.0,
                           "kind": "lamp", "yaw": 0.0}]}
    rows = conflicts([storefront], furn_doc)
    assert rows and rows[0]["collection_a"] == "items"
    assert rows[0]["collection_b"] == "city_layout_v1"
    assert rows[0]["id_a"] == "sf1" and rows[0]["id_b"] == "lamp1"


def test_conflicts_rect_vs_rect_just_outside_no_report():
    a = {"id": "a", "x": 0.0, "y": 0.0, "yaw_deg": 0.0,
         "width_cm": 100.0, "depth_cm": 100.0}   # spans x -50..50, y -50..50
    b = {"id": "b", "x": 150.0, "y": 0.0, "yaw_deg": 0.0,
         "width_cm": 100.0, "depth_cm": 100.0}   # spans x 100..200: 50 cm gap
    assert conflicts([a, b]) == []


# --- 7. ValueError paths -----------------------------------------------------

def test_value_errors():
    layout = _block_layout()
    with pytest.raises(ValueError):
        storefront_slots(layout, spacing_cm=0.0, setback_cm=0.0, seed=0)
    with pytest.raises(ValueError):
        storefront_slots(layout, spacing_cm=-5.0, setback_cm=0.0, seed=0)
    with pytest.raises(ValueError):
        storefront_slots(layout, spacing_cm=100.0, setback_cm=-1.0, seed=0)
