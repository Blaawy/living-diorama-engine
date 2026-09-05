"""Tests for ``ldyf.street_life_inputs`` -- the missing geometry inputs for
``street_life`` (roof polygons per building, embedded road spec).

Fixtures are hand-built lattice specs + ``city_layout.building_slots`` output,
exactly the way ``test_city_layout`` builds them: no SUMO, no Unreal, no disk.
"""

from __future__ import annotations

import copy
import json
import math
import re

import pytest

from ldyf.building_kits import build_kits
from ldyf.city_layout import building_slots, blocks
from ldyf.street_life import rooftop_props
from ldyf.street_life_inputs import (
    SCHEMA_VERSION,
    attach_road_spec,
    building_footprint,
    roof_polygons,
    street_life_inputs,
    validate_inputs,
)

LANE_W = 200.0


def _pt(x, y):
    return {"x": float(x), "y": float(y), "z": 0.0}


def make_lattice_spec(n_x: int, n_y: int, *, step_cm: float = 20000.0,
                      lane_width: float = LANE_W,
                      carriageway: bool = True) -> dict:
    """Hand-built lattice: junctions on an n_x x n_y grid, one normal edge per
    street segment.  ``carriageway=True`` flags every lane as one cars drive
    on (``disallow: ["pedestrian"]``) so the sign-error detector has real
    lanes to collide with; ``carriageway=False`` leaves lanes unlabelled like
    the plain test_city_layout lattice."""
    pos = {f"J{c}_{r}": _pt(c * step_cm, r * step_cm)
           for c in range(n_x) for r in range(n_y)}
    junctions = [{"id": jid, "type": "priority", "position": pos[jid],
                  "polygon": None, "incoming_edge_ids": []}
                 for jid in sorted(pos)]
    edges: list[dict] = []

    def add_edge(eid: str, a: str, b: str) -> None:
        disallow = ["pedestrian"] if carriageway else None
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


def make_layout(*, seed: int = 3, carriageway: bool = True) -> dict:
    """A city_layout-shaped document with blocks + building slots, built the
    way test_city_layout builds its fixtures (lattice spec -> building_slots)."""
    spec = make_lattice_spec(3, 3, carriageway=carriageway)
    bs = building_slots(spec, kits=["a", "b"], seed=seed)
    layout = {"schema_version": "city_layout_v1", "seed": seed,
              "blocks": blocks(spec), "building_slots": bs}
    return layout


def _slot(yaw: float, x: float = 0.0, y: float = 0.0,
          width_cm: float = 2000.0) -> dict:
    return {"slot_id": "b0:f0", "block_id": "b0", "kit": "a",
            "x": x, "y": y, "yaw": yaw, "width_cm": width_cm,
            "depth_cm": 1500.0, "frontage_index": 0}


# --- footprint sign: extends AWAY from the street --------------------------


def test_footprint_recedes_away_from_street_all_four_cardinal_yaws():
    """For yaw 0/90/180/-90 the street is at the slot point and the whole mass
    sits on the far side (corners are verified numerically below)."""
    depth = 1500.0
    # yaw 0: outward +X, so the front edge is on x == 0 and the back on x == -depth
    fp = building_footprint(_slot(0.0), depth_cm=depth)
    xs = [c["x"] for c in fp]
    assert max(xs) == 0.0 and min(xs) == -depth  # mass strictly in -X
    assert sorted(xs) == [-depth, -depth, 0.0, 0.0]
    assert sorted(c["y"] for c in fp) == [-1000.0, -1000.0, 1000.0, 1000.0]
    # yaw 90: outward +Y (south), mass strictly in -Y
    fp = building_footprint(_slot(90.0), depth_cm=depth)
    ys = [c["y"] for c in fp]
    assert max(ys) == 0.0 and min(ys) == -depth
    assert sorted(c["x"] for c in fp) == [-1000.0, -1000.0, 1000.0, 1000.0]
    # yaw 180: outward -X, mass strictly in +X
    fp = building_footprint(_slot(180.0), depth_cm=depth)
    xs = [c["x"] for c in fp]
    assert min(xs) == 0.0 and max(xs) == depth
    # yaw -90 (== 270): outward -Y, mass strictly in +Y
    fp = building_footprint(_slot(-90.0), depth_cm=depth)
    ys = [c["y"] for c in fp]
    assert min(ys) == 0.0 and max(ys) == depth


def test_footprint_front_edge_centred_on_slot_point():
    fp = building_footprint(_slot(0.0, x=500.0, y=700.0), depth_cm=1500.0)
    xs = [c["x"] for c in fp]
    assert max(xs) == 500.0
    assert min(xs) == 500.0 - 1500.0
    assert sorted(c["y"] for c in fp) == [700.0 - 1000.0, 700.0 - 1000.0,
                                          700.0 + 1000.0, 700.0 + 1000.0]


def test_footprint_and_roofs_deterministic():
    assert roof_polygons(make_layout(seed=7)) == \
        roof_polygons(make_layout(seed=7))
    assert building_footprint(_slot(37.0), depth_cm=1500.0) == \
        building_footprint(_slot(37.0), depth_cm=1500.0)


# --- roofs strictly inside footprints on a real layout ---------------------


def _point_in_poly(px: float, py: float, poly) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]["x"], poly[i]["y"]
        bx, by = poly[(i + 1) % n]["x"], poly[(i + 1) % n]["y"]
        if ((ay > py) != (by > py)) and \
                (px < (bx - ax) * (py - ay) / (by - ay) + ax):
            inside = not inside
    return inside


def test_real_layout_roofs_strictly_inside_and_doc_valid():
    layout = make_layout()
    doc = street_life_inputs(layout, make_lattice_spec(3, 3))
    assert doc["schema_version"] == SCHEMA_VERSION
    assert validate_inputs(doc) == []
    assert doc["counts"]["buildings"] == len(doc["buildings"]) > 0
    for b in doc["buildings"]:
        assert len(b["polygon"]) == 4 and len(b["footprint"]) == 4
        for p in b["polygon"]:
            assert _point_in_poly(p["x"], p["y"], b["footprint"])


def test_roof_ids_join_building_kits_ids():
    """roof record ids == slot ids == the ids building_kits keys buildings by
    (building_id), landmark slot included."""
    layout = make_layout()
    roofs = roof_polygons(layout)
    slot_ids = {s["slot_id"] for s in layout["building_slots"]["slots"]}
    assert {b["id"] for b in roofs} == slot_ids
    for b in roofs:
        assert re.fullmatch(r".+?:f\d+", b["id"])
    kits = build_kits(layout)  # pure: reads only the layout
    kit_ids = {e["building_id"] for e in kits["buildings"]}
    kit_ids.add(kits["landmark"]["building_id"])
    assert {b["id"] for b in roofs} == kit_ids
    # the actual consumer runs on these records
    props = rooftop_props(roofs, seed=5)
    assert props and all(p["building_id"] in slot_ids for p in props)


def test_roof_records_have_block_id_and_height():
    layout = make_layout()
    for b in roof_polygons(layout):
        assert b["block_id"].startswith("block_")
        assert 1600.0 <= b["height_cm"] <= 2600.0
        assert b["height_cm"] % 300.0 == 0.0


# --- attach_road_spec: no mutation, argument wins --------------------------


def test_attach_road_spec_does_not_mutate_input():
    layout = make_layout()
    spec = make_lattice_spec(3, 3)
    before = json.dumps(layout, sort_keys=True)
    out = attach_road_spec(layout, spec)
    assert json.dumps(layout, sort_keys=True) == before  # untouched
    assert out is not layout
    assert out["spec"] == spec
    assert "spec_replaced_previous" not in out


def test_attach_road_spec_argument_wins_and_records_replacement():
    layout = make_layout()
    layout["spec"] = {"schema_version": "road_spec_v1", "stale": True}
    spec = make_lattice_spec(3, 3)
    out = attach_road_spec(layout, spec)
    assert out["spec"] == spec  # argument won
    assert out["spec_replaced_previous"] is True  # replacement recorded
    assert layout["spec"]["stale"] is True  # input still carries its own


def test_street_life_inputs_embeds_spec_under_key_parked_cars_reads():
    doc = street_life_inputs(make_layout(), make_lattice_spec(3, 3))
    assert doc["layout"]["spec"]["schema_version"] == "road_spec_v1"


# --- validate_inputs catches the four problem classes ----------------------


def _mirror(poly, yaw_deg, depth_cm):
    """Reflect a footprint/roof rectangle across its street-side edge: the
    back wall lands ``depth_cm`` out in the road -- exactly what a
    sign-flipped generator emits.

    Outward ``u = (cos yaw, sin yaw)`` points to the street; a correct
    rectangle sits BEHIND the slot, so its street-side (front) corners are the
    two with the LARGEST projection along ``u``.  The mirror keeps that front
    edge and pushes the back wall ``+depth_cm * u`` out into the road.
    """
    r = math.radians(float(yaw_deg))
    ux, uy = math.cos(r), math.sin(r)
    dots = [p["x"] * ux + p["y"] * uy for p in poly]
    # Exact float equality picks only one corner: the two front corners have
    # the same projection in exact arithmetic, but the corners are rounded by
    # _f3 first, so they differ in the last place. Compare with a tolerance.
    hi = max(dots)
    front = [poly[i] for i in range(len(poly)) if abs(dots[i] - hi) < 1e-6]
    assert len(front) == 2, (dots, hi)
    back = [{"x": p["x"] + depth_cm * ux, "y": p["y"] + depth_cm * uy}
            for p in front]
    return front + back


def test_validate_catches_mirrored_footprint_in_lane():
    """The sign-error detector: a footprint that points at the street lands in
    a carriageway lane and must be reported."""
    layout = make_layout()  # carriageway lanes present
    rec = roof_polygons(layout)[0]
    bad = dict(rec)
    bad["footprint"] = _mirror(rec["footprint"], rec["yaw"], rec["depth_cm"])
    bad["polygon"] = _mirror(rec["polygon"], rec["yaw"], rec["depth_cm"])
    doc = {"schema_version": SCHEMA_VERSION,
           "layout": attach_road_spec(layout, make_lattice_spec(3, 3)),
           "buildings": [bad]}
    problems = validate_inputs(doc)
    assert any("overlaps a carriageway lane" in p for p in problems)


def test_validate_catches_roof_not_inside_footprint():
    layout = make_layout()
    rec = roof_polygons(layout)[0]
    shifted = [{"x": p["x"] + 400.0, "y": p["y"]} for p in rec["polygon"]]
    bad = dict(rec)
    bad["polygon"] = shifted
    doc = {"schema_version": SCHEMA_VERSION,
           "layout": attach_road_spec(layout, make_lattice_spec(3, 3)),
           "buildings": [bad]}
    problems = validate_inputs(doc)
    assert any("not strictly inside" in p or "crosses the footprint" in p
               for p in problems)


def test_validate_catches_duplicate_id_and_missing_spec():
    layout = make_layout()
    roofs = roof_polygons(layout)
    dup = dict(roofs[0])
    dup["id"] = roofs[1]["id"]
    doc = {"schema_version": SCHEMA_VERSION,
           "layout": attach_road_spec(layout, make_lattice_spec(3, 3)),
           "buildings": roofs + [dup]}
    problems = validate_inputs(doc)
    assert any("duplicate building id" in p for p in problems)

    no_spec = copy.deepcopy(doc)
    del no_spec["layout"]["spec"]
    problems = validate_inputs(no_spec)
    assert any("no embedded road spec" in p for p in problems)


def test_validate_accepts_layout_whose_lanes_declare_nothing():
    """A lane that declares neither allow nor disallow is not a carriageway
    lane (same rule as street_life._is_car_lane), so nothing is swept and a
    clean document validates."""
    layout = make_layout(carriageway=False)
    doc = street_life_inputs(layout, make_lattice_spec(3, 3,
                                                       carriageway=False))
    assert validate_inputs(doc) == []


# --- every documented ValueError -------------------------------------------


def test_value_errors():
    slot = _slot(0.0)
    with pytest.raises(ValueError):
        building_footprint(slot, depth_cm=0.0)
    with pytest.raises(ValueError):
        building_footprint(slot, depth_cm=-5.0)
    with pytest.raises(ValueError):
        building_footprint({"x": 0.0, "y": 0.0, "yaw": 0.0,
                            "width_cm": 0.0}, depth_cm=1500.0)
    layout = {"schema_version": "city_layout_v1", "seed": 1,
              "building_slots": {"slots": [_slot(0.0)]}}
    with pytest.raises(ValueError):
        roof_polygons(layout, depth_cm=0.0)
    with pytest.raises(ValueError):
        roof_polygons(layout, inset_cm=0.0)
    with pytest.raises(ValueError):
        roof_polygons(layout, inset_cm=-1.0)
    # inset 1000 >= width/2 (2000/2): roof collapses
    with pytest.raises(ValueError):
        roof_polygons(layout, inset_cm=1000.0)
    # inset 750 >= depth/2 (1500/2): roof collapses
    with pytest.raises(ValueError):
        roof_polygons(layout, inset_cm=750.0)
    # an inset that is fine on this slot is fine
    assert len(roof_polygons(layout, inset_cm=60.0)) == 1
