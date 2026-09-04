"""Phase-2 closure lane B: ``ldyf.city_layout`` building lots + furniture.

Tests use (a) a hand-built lattice spec (junctions/edges fabricated as plain
dicts -- no netconvert, no sumolib) and (b) the inline synthetic SUMO net
from ``test_roads`` when sumolib is importable (skipped otherwise).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path

import pytest

from ldyf.city_layout import (
    CITY_LAYOUT_VERSION,
    blocks,
    building_slots,
    crossing_slots,
    frontages,
    furniture_slots,
    nearest_lane_distance_cm,
    road_corridor_polygons,
    write_layout,
)

LANE_W = 200.0
_HAS_SUMOLIB = importlib.util.find_spec("sumolib") is not None


def _pt(x, y):
    return {"x": float(x), "y": float(y), "z": 0.0}


def make_lattice_spec(n_x: int, n_y: int, *, step_cm: float = 20000.0,
                      lane_width: float = LANE_W,
                      add_crossing: bool = False) -> dict:
    """Hand-built lattice: junctions on an n_x x n_y grid (columns -> x,
    rows -> y), one single-lane normal edge per street segment centred on the
    junction-to-junction line.  Optionally one crossing edge."""
    pos = {f"J{c}_{r}": _pt(c * step_cm, r * step_cm)
           for c in range(n_x) for r in range(n_y)}
    junctions = [{"id": jid, "type": "priority", "position": pos[jid],
                  "polygon": None, "incoming_edge_ids": []}
                 for jid in sorted(pos)]
    edges: list[dict] = []

    def add_edge(eid: str, a: str, b: str, function: str = "normal") -> None:
        edges.append({"id": eid, "from_junction": a, "to_junction": b,
                      "function": function, "priority": 1,
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
    if add_crossing:
        edges.append({"id": "X0", "from_junction": "J0_0", "to_junction": "J0_0",
                      "function": "crossing", "priority": 1,
                      "lanes": [{"id": "X0_0", "index": 0,
                                 "width_cm": lane_width,
                                 "width_cm_effective": lane_width,
                                 "width_source": "attribute",
                                 "speed_mps": 0.0, "length_m": 6.0,
                                 "allow": ["pedestrian"], "disallow": None,
                                 "polyline": [_pt(step_cm * 0.5, 0.0),
                                              _pt(step_cm * 0.5, 600.0)]}]})
    return {"schema_version": "road_spec_v1", "edges": edges,
            "junctions": junctions,
            "counts": {"edges": len(edges), "junctions": len(junctions)}}


def spec3():  # 3 x 3 lattice -> (3-1)^2 = 4 blocks
    return make_lattice_spec(3, 3)


def _block_for(spec, bid):
    for b in blocks(spec):
        if b["id"] == bid:
            return b
    raise AssertionError(f"block {bid} missing")


# --- corridors ---------------------------------------------------------------

def test_corridors_normal_edges_only_and_count():
    spec = make_lattice_spec(3, 3, add_crossing=True)
    cors = road_corridor_polygons(spec, margin_cm=0.0)
    assert len(cors) == 12  # 12 normal edges; the crossing edge is excluded
    for poly in cors:
        assert len(poly) == 4
        assert all(set(p) == {"x", "y"} for p in poly)


def test_corridor_covers_lane_union_band():
    spec = make_lattice_spec(3, 3)
    cors = road_corridor_polygons(spec, margin_cm=0.0)
    for e in sorted(spec["edges"], key=lambda e: e["id"]):
        xs = [p["x"] for ln in e["lanes"] for p in ln["polyline"]]
        ys = [p["y"] for ln in e["lanes"] for p in ln["polyline"]]
        assert not any(ln["polyline"] for ln in e["lanes"]) or xs
        found = False
        for poly in cors:
            rx = [p["x"] for p in poly]
            ry = [p["y"] for p in poly]
            if (min(rx) - 1e-6 <= min(xs) and max(rx) + 1e-6 >= max(xs)
                    and min(ry) - 1e-6 <= min(ys) and max(ry) + 1e-6 >= max(ys)):
                found = True
                break
        assert found, f"no corridor covers edge {e['id']}"


# --- blocks -----------------------------------------------------------------

def test_blocks_empty_spec():
    empty = {"schema_version": "road_spec_v1", "edges": [], "junctions": []}
    assert blocks(empty) == []


def test_blocks_3x3_lattice_is_4_blocks():
    got = blocks(spec3())
    assert len(got) == (3 - 1) ** 2 == 4
    for b in got:
        assert len(b["polygon"]) == 4
        assert b["area_cm2"] > 0.0
    assert len({b["id"] for b in got}) == 4


def test_blocks_lattice_inferred_rectangular_not_hardcoded():
    # 2 columns x 4 rows of junctions -> (2-1)*(4-1) = 3 blocks; a hardcoded
    # 4x4 assumption would give 9 and would fail here
    got = blocks(make_lattice_spec(2, 4))
    assert len(got) == 3
    got4 = blocks(make_lattice_spec(4, 4))
    assert len(got4) == 9


def test_blocks_cluster_tolerance_merges_jitter():
    base = make_lattice_spec(4, 4)
    jit = json.loads(json.dumps(base))
    jit["junctions"][0]["position"]["x"] += 60.0
    merged = blocks(jit, cluster_tol_cm=100.0)
    assert len(merged) == 9
    assert len({b["id"] for b in merged}) == 9


def test_blocks_geometry_area_bbox_centre():
    b = _block_for(spec3(), "block_1_1")
    xs = [p["x"] for p in b["polygon"]]
    ys = [p["y"] for p in b["polygon"]]
    assert b["bbox"]["x_min"] == min(xs)
    assert b["bbox"]["x_max"] == max(xs)
    assert b["bbox"]["y_min"] == min(ys)
    assert b["bbox"]["y_max"] == max(ys)
    w = b["bbox"]["x_max"] - b["bbox"]["x_min"]
    h = b["bbox"]["y_max"] - b["bbox"]["y_min"]
    assert b["area_cm2"] == pytest.approx(w * h)
    assert b["centre"]["x"] == pytest.approx((min(xs) + max(xs)) / 2.0)
    assert b["centre"]["y"] == pytest.approx((min(ys) + max(ys)) / 2.0)


# --- frontages --------------------------------------------------------------

def _facade_yaw_unit(f):
    a = math.radians(f["yaw"])
    return math.cos(a), math.sin(a)


def test_frontage_yaw_points_away_from_block_centre():
    spec = spec3()
    for b in blocks(spec):
        frs = frontages(b, spec, setback_cm=800.0, spacing_cm=2000.0,
                        min_frontage_cm=1000.0)
        assert frs
        for f in frs:
            ux, uy = _facade_yaw_unit(f)
            dot = (f["x"] - b["centre"]["x"]) * ux + \
                  (f["y"] - b["centre"]["y"]) * uy
            assert dot > 0.0  # outward normal must point away from the centre


def test_frontage_spacing_and_corner_gap():
    spec = spec3()
    b = _block_for(spec, "block_0_0")
    spacing, gap = 2000.0, 1000.0
    frs = frontages(b, spec, setback_cm=800.0, spacing_cm=spacing,
                    min_frontage_cm=gap)
    assert frs
    poly = b["polygon"]
    for f in frs:
        i = f["edge_index"]
        a, bb = poly[i], poly[(i + 1) % len(poly)]
        L = math.hypot(bb["x"] - a["x"], bb["y"] - a["y"])
        t = ((f["x"] - a["x"]) * (bb["x"] - a["x"]) +
             (f["y"] - a["y"]) * (bb["y"] - a["y"])) / L
        assert t >= gap - 1.0          # never hug a corner
        assert L - t >= gap - 1.0
        assert f["length_cm"] <= spacing + 1e-6


# --- building slots ---------------------------------------------------------

def test_building_slots_two_runs_byte_identical():
    spec = spec3()
    kw = dict(kits=["a", "b", "c"], seed=7)
    a = json.dumps(building_slots(spec, **kw), sort_keys=True)
    b = json.dumps(building_slots(spec, **kw), sort_keys=True)
    assert a == b
    assert "-0.0" not in a


def test_building_slots_counts_by_kit():
    res = building_slots(spec3(), kits=["a", "b", "c"], seed=7)
    assert res["schema_version"] == CITY_LAYOUT_VERSION
    assert res["counts"]["blocks"] == 4
    assert res["counts"]["slots"] == len(res["slots"]) == \
        sum(res["counts"]["by_kit"].values())
    assert set(res["counts"]["by_kit"]) <= {"a", "b", "c"}
    assert res["counts"]["slots"] > 0
    for s in res["slots"]:
        assert set(s) >= {"slot_id", "block_id", "kit", "x", "y", "yaw",
                          "width_cm", "depth_cm", "frontage_index"}
        assert 0.0 < s["width_cm"] <= 2000.0
        assert s["depth_cm"] == 1500.0


def test_building_slots_dominant_kit_floor_per_block():
    kits = ["alpha", "beta", "gamma"]
    res = building_slots(spec3(), kits=kits, seed=12345)
    by_block: dict[str, dict[str, int]] = {}
    for s in res["slots"]:
        d = by_block.setdefault(s["block_id"], {})
        d[s["kit"]] = d.get(s["kit"], 0) + 1
    assert len(by_block) == 4
    for bid, counts in by_block.items():
        total = sum(counts.values())
        share = max(counts.values()) / total
        assert share >= 0.60, f"block {bid} lost its dominant kit: {counts}"
        # the dominant kit is the block kit from the documented digest rule
        h = hashlib.sha256(f"{bid}|12345".encode("utf-8")).hexdigest()
        expected = kits[int(h[:16], 16) % len(kits)]
        assert counts[expected] >= math.ceil(0.60 * total)


def test_building_slots_clearance_default_margin():
    spec = spec3()
    res = building_slots(spec, kits=["a"], seed=1)
    assert res["slots"]
    for s in res["slots"]:
        d = nearest_lane_distance_cm(spec, s["x"], s["y"])
        assert d >= 800.0 - 1.0, s["slot_id"]


def test_building_slots_clearance_enforced_when_margin_small():
    # margin 0 puts the block edge ~100 cm from the lane centre; the facade
    # must be pulled back into the block until it clears setback_cm (800)
    spec = spec3()
    res = building_slots(spec, kits=["a"], seed=1, margin_cm=0.0,
                         setback_cm=800.0)
    assert res["slots"]
    for s in res["slots"]:
        d = nearest_lane_distance_cm(spec, s["x"], s["y"])
        assert d >= 800.0 - 1.0, s["slot_id"]


# --- furniture --------------------------------------------------------------

def test_furniture_offset_defaults_to_half_width_plus_150():
    spec = spec3()  # lanes of 200 cm -> offset 100 + 150 = 250
    res = furniture_slots(spec)
    assert res["slots"]
    for s in res["slots"]:
        assert s["offset_cm"] == pytest.approx(250.0)
        ln = next(ln for e in spec["edges"] for ln in e["lanes"]
                  if ln["id"] == s["lane_id"])
        d = nearest_lane_distance_cm({"edges": [{"lanes": [ln]}]},
                                     s["x"], s["y"])
        assert d == pytest.approx(250.0, abs=1.0)  # uses width_cm_effective


def test_furniture_explicit_offset_and_kinds_alternate():
    spec = spec3()
    res = furniture_slots(spec, offset_cm=123.0, kinds=("lamp", "sign"))
    assert res["slots"]
    kinds = [s["kind"] for s in res["slots"]]
    assert all(kinds[i] == ("lamp", "sign")[i % 2] for i in range(len(kinds)))
    for s in res["slots"]:
        assert s["offset_cm"] == pytest.approx(123.0)


def test_furniture_yaw_faces_road_centre():
    spec = spec3()
    res = furniture_slots(spec)
    for s in res["slots"]:
        ln = next(ln for e in spec["edges"] for ln in e["lanes"]
                  if ln["id"] == s["lane_id"])
        best, foot = float("inf"), None
        pts = ln["polyline"]
        for a, b in zip(pts, pts[1:]):
            ax, ay, bx, by = a["x"], a["y"], b["x"], b["y"]
            dx, dy = bx - ax, by - ay
            denom = dx * dx + dy * dy
            t = ((s["x"] - ax) * dx + (s["y"] - ay) * dy) / denom
            t = max(0.0, min(1.0, t))
            fx, fy = ax + dx * t, ay + dy * t
            d = math.hypot(s["x"] - fx, s["y"] - fy)
            if d < best:
                best, foot = d, (fx, fy)
        ux, uy = _facade_yaw_unit(s)
        dot = (foot[0] - s["x"]) * ux + (foot[1] - s["y"]) * uy
        assert dot > 0.0  # yaw points back toward the road centre


def test_furniture_empty_spec():
    empty = {"schema_version": "road_spec_v1", "edges": [], "junctions": []}
    res = furniture_slots(empty)
    assert res["slots"] == []
    assert res["counts"] == {}


# --- crossings --------------------------------------------------------------

def test_crossing_slots_reads_crossing_edges():
    spec = make_lattice_spec(3, 3, add_crossing=True)
    res = crossing_slots(spec)
    assert res["counts"]["slots"] == 1
    s = res["slots"][0]
    assert s["edge_id"] == "X0"
    assert s["x"] == pytest.approx(10000.0)
    assert s["y"] == pytest.approx(300.0)
    assert s["length_cm"] == pytest.approx(600.0)
    assert s["yaw"] == pytest.approx(90.0)


def test_crossing_slots_empty_spec():
    assert crossing_slots({"edges": [], "junctions": []})["slots"] == []


# --- write path -------------------------------------------------------------

def test_write_layout_round_trip_sorted_json(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec3()), encoding="utf-8")
    out_path = tmp_path / "out" / "layout.json"
    returned = write_layout(spec_path, out_path, kits=["a", "b"], seed=3)
    assert out_path.exists()
    text = out_path.read_text(encoding="utf-8")
    assert json.loads(text) == returned
    assert text == json.dumps(returned, indent=2, sort_keys=True)
    assert returned["schema_version"] == CITY_LAYOUT_VERSION
    assert returned["building_slots"]["counts"]["blocks"] == 4
    assert len(returned["corridors"]) == 12


# --- real-inline synthetic net from test_roads (sumolib-gated) --------------

@pytest.mark.skipif(not _HAS_SUMOLIB, reason="sumolib not installed")
def test_tiny_net_spec_smoke(tmp_path):
    """The inline synthetic net from test_roads: 2 junctions on one line ->
    no closed block, but corridors/furniture/crossing still behave."""
    from ldyf.roads import build_road_spec
    from ldyf.tests.test_roads import TINY_NET

    p = tmp_path / "tiny.net.xml"
    p.write_text(TINY_NET, encoding="utf-8")
    spec = build_road_spec(p)
    assert len(road_corridor_polygons(spec, margin_cm=0.0)) == 2
    assert blocks(spec) == []  # no closed cell between only two junctions
    bs = building_slots(spec, kits=["a"], seed=0)
    assert bs["counts"]["blocks"] == 0 and bs["slots"] == []
    assert furniture_slots(spec)["slots"]  # E1/E2 normal lanes exist
    assert crossing_slots(spec)["counts"]["slots"] == 0


def test_furniture_is_never_placed_on_a_carriageway_lane():
    """Street furniture walked EVERY normal lane, so the outer offset of an
    outer car lane put lamp posts, bins and benches in live traffic -- 336 of
    672 on the proof network, visible in the rendered frames.  Would break if
    furniture_slots went back to iterating lanes that disallow pedestrians."""
    import math
    walk = {"id": "E_0", "index": 0, "width_cm_effective": 200.0,
            "allow": ["pedestrian"], "disallow": None,
            "polyline": [_pt(740, 0), _pt(740, 20000)]}
    car1 = {"id": "E_1", "index": 1, "width_cm_effective": 320.0,
            "allow": None, "disallow": ["pedestrian"],
            "polyline": [_pt(480, 0), _pt(480, 20000)]}
    car2 = {"id": "E_2", "index": 2, "width_cm_effective": 320.0,
            "allow": None, "disallow": ["pedestrian"],
            "polyline": [_pt(160, 0), _pt(160, 20000)]}
    spec = {"schema_version": "road_spec_v1", "units": {"linear": "cm"},
            "edges": [{"id": "E", "function": "normal", "from_junction": "A",
                       "to_junction": "B", "lanes": [walk, car1, car2]}],
            "junctions": []}
    doc = furniture_slots(spec)
    assert doc["slots"], "the fix must not remove all furniture"
    assert {s["lane_id"] for s in doc["slots"]} == {"E_0"}
    for s in doc["slots"]:
        for lane in (car1, car2):
            hw = lane["width_cm_effective"] / 2.0
            for q in lane["polyline"]:
                assert math.dist((float(s["x"]), float(s["y"])),
                                 (float(q["x"]), float(q["y"]))) > hw or                        abs(float(s["x"]) - float(q["x"])) > hw, (
                    "furniture %s at (%s, %s) is inside car lane %s"
                    % (s["kind"], s["x"], s["y"], lane["id"]))
