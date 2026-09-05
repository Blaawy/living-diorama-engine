"""Tests for ``ldyf.foliage_plan`` (planter slots, hedge runs, courtyard
clusters, the whole document and conflict detection).

Fixtures are inline city-layout-style block dicts (rectangles with
``{"x","y"}`` polygons, exactly what ``city_layout.blocks`` emits); no SUMO
net and no editor are involved.
"""

from __future__ import annotations

import json
import math

import pytest

from ldyf.foliage_plan import (
    FOLIAGE_PLAN_VERSION,
    conflicts,
    courtyard_clusters,
    foliage_plan,
    hedge_runs,
    planter_slots,
)


def _pt(x, y):
    return {"x": float(x), "y": float(y)}


def rect_block(bid, x0, y0, x1, y1):
    """Axis-aligned rectangle block; Unreal Y grows south."""
    return {"id": bid,
            "polygon": [_pt(x0, y0), _pt(x1, y0), _pt(x1, y1), _pt(x0, y1)],
            "centre": {"x": (x0 + x1) / 2.0, "y": (y0 + y1) / 2.0},
            "area_cm2": (x1 - x0) * (y1 - y0),
            "bbox": {"x_min": x0, "x_max": x1, "y_min": y0, "y_max": y1}}


def layout(*blocks):
    return {"schema_version": "city_layout_v1", "blocks": list(blocks)}


SQUARE = rect_block("block_0_0", 0.0, 0.0, 1000.0, 1000.0)
SQUARE_LAYOUT = layout(SQUARE)
TWO_BLOCK = layout(rect_block("block_0_0", 0.0, 0.0, 2000.0, 2000.0),
                   rect_block("block_1_1", 3000.0, 3000.0, 5000.0, 5000.0))


def _assert_yaw_outward(rows, block):
    cx = block["centre"]["x"]
    cy = block["centre"]["y"]
    for r in rows:
        pts = [(p["x"], p["y"]) for p in block["polygon"]]
        best = None
        for i in range(len(pts)):
            ax, ay = pts[i]
            bx, by = pts[(i + 1) % len(pts)]
            mid = ((ax + bx) / 2.0, (ay + by) / 2.0)
            seg = math.hypot(bx - ax, by - ay)
            ux, uy = (bx - ax) / seg, (by - ay) / seg
            nx, ny = -uy, ux
            if nx * (cx - mid[0]) + ny * (cy - mid[1]) > 0.0:
                nx, ny = -nx, -ny
            expected = math.degrees(math.atan2(ny, nx))
            got = r["yaw"]
            diff = abs((got - expected + 180.0) % 360.0 - 180.0)
            if best is None or diff < best[0]:
                best = (diff, expected)
        assert best[0] < 1e-6, (r["id"], r["yaw"], best)


# ---------------------------------------------------------------------------
# planters
# ---------------------------------------------------------------------------

def test_planter_rows_have_schema_fields():
    rows = planter_slots(SQUARE_LAYOUT, spacing_cm=300.0, inset_cm=40.0,
                         size_cm=120.0)
    assert rows
    for r in rows:
        assert set(r) == {"id", "block_id", "x", "y", "yaw",
                          "width_cm", "depth_cm", "kind"}
        assert r["kind"] == "planter"
        assert r["width_cm"] == 120.0
        assert r["depth_cm"] == 120.0


def test_planter_ids_sorted():
    rows = planter_slots(SQUARE_LAYOUT, spacing_cm=300.0, inset_cm=40.0,
                         size_cm=120.0)
    ids = [r["id"] for r in rows]
    assert ids == sorted(ids)
    assert ids[0].startswith("block_0_0:planter:")


def test_planter_count_per_edge():
    # 1000 cm edges, 300 cm spacing -> 3 per edge, 4 edges
    rows = planter_slots(SQUARE_LAYOUT, spacing_cm=300.0, inset_cm=40.0,
                         size_cm=120.0)
    assert len(rows) == 12


def test_planter_spacing_is_constant_along_edge():
    rows = planter_slots(SQUARE_LAYOUT, spacing_cm=300.0, inset_cm=40.0,
                         size_cm=120.0)
    top = [r for r in rows if r["yaw"] == -90.0]
    top.sort(key=lambda r: r["x"])
    xs = [r["x"] for r in top]
    assert len(xs) == 3
    for a, b in zip(xs, xs[1:]):
        assert abs((b - a) - 300.0) < 1e-6
    # symmetric trimming: first/last centres sit 200 cm in from the corners
    assert abs(xs[0] - 200.0) < 1e-6
    assert abs(xs[-1] - 800.0) < 1e-6


def test_planter_inset_outward_of_edge():
    rows = planter_slots(SQUARE_LAYOUT, spacing_cm=300.0, inset_cm=40.0,
                         size_cm=120.0)
    for r in rows:
        if r["yaw"] == -90.0:      # top edge, outward is -Y
            assert abs(r["y"] - (-40.0)) < 1e-6
        elif r["yaw"] == 90.0:     # bottom edge, outward is +Y
            assert abs(r["y"] - 1040.0) < 1e-6
        elif r["yaw"] == 180.0:    # left edge
            assert abs(r["x"] - (-40.0)) < 1e-6
        else:                      # right edge, outward is +X
            assert abs(r["x"] - 1040.0) < 1e-6


def test_planter_yaw_matches_outward_normal():
    rows = planter_slots(SQUARE_LAYOUT, spacing_cm=300.0, inset_cm=40.0,
                         size_cm=120.0)
    _assert_yaw_outward(rows, SQUARE)


def test_planter_short_edge_yields_nothing():
    small = layout(rect_block("block_0_0", 0.0, 0.0, 200.0, 200.0))
    rows = planter_slots(small, spacing_cm=300.0, inset_cm=40.0,
                         size_cm=120.0)
    assert rows == []


def test_planter_spacing_matches_exact_multiple():
    big = layout(rect_block("block_0_0", 0.0, 0.0, 1200.0, 1000.0))
    rows = planter_slots(big, spacing_cm=300.0, inset_cm=40.0,
                         size_cm=120.0)
    # 1200 edge -> 4, 1000 edge -> 3, times two each
    assert len(rows) == 14


@pytest.mark.parametrize("bad", [
    {"spacing_cm": 0.0},
    {"spacing_cm": -5.0},
    {"inset_cm": 0.0},
    {"size_cm": -1.0},
])
def test_planter_value_error(bad):
    kwargs = {"spacing_cm": 300.0, "inset_cm": 40.0, "size_cm": 120.0}
    kwargs.update(bad)
    with pytest.raises(ValueError):
        planter_slots(SQUARE_LAYOUT, **kwargs)


# ---------------------------------------------------------------------------
# hedges
# ---------------------------------------------------------------------------

def test_hedge_rows_have_schema_fields():
    rows = hedge_runs(SQUARE_LAYOUT, min_run_cm=800.0, offset_cm=60.0,
                      segment_cm=400.0)
    assert rows
    for r in rows:
        assert set(r) == {"id", "block_id", "x", "y", "yaw", "length_cm",
                          "kind"}
        assert r["kind"] == "hedge"


def test_hedge_short_frontage_yields_nothing():
    small = layout(rect_block("block_0_0", 0.0, 0.0, 500.0, 500.0))
    rows = hedge_runs(small, min_run_cm=800.0, offset_cm=60.0,
                      segment_cm=400.0)
    assert rows == []


def test_hedge_emitted_when_run_equals_min_run():
    small = layout(rect_block("block_0_0", 0.0, 0.0, 800.0, 800.0))
    rows = hedge_runs(small, min_run_cm=800.0, offset_cm=60.0,
                      segment_cm=400.0)
    assert len(rows) == 8       # 4 edges x 2 pieces of 400


def test_hedge_subdivision_counts_and_last_segment():
    # 1000 cm edge -> 400+400+200 (last piece keeps its true remainder)
    rows = hedge_runs(SQUARE_LAYOUT, min_run_cm=800.0, offset_cm=60.0,
                      segment_cm=400.0)
    top = [r for r in rows if r["yaw"] == -90.0]
    top.sort(key=lambda r: r["x"])
    assert len(top) == 3
    assert [r["length_cm"] for r in top] == [400.0, 400.0, 200.0]
    # centres of the pieces along the edge: 200, 600, 900
    xs = [r["x"] for r in top]
    assert abs(xs[0] - 200.0) < 1e-6
    assert abs(xs[1] - 600.0) < 1e-6
    assert abs(xs[2] - 900.0) < 1e-6


def test_hedge_last_piece_length_for_exact_multiple():
    big = layout(rect_block("block_0_0", 0.0, 0.0, 1200.0, 1000.0))
    rows = hedge_runs(big, min_run_cm=800.0, offset_cm=60.0,
                      segment_cm=400.0)
    top = [r for r in rows if r["yaw"] == -90.0]
    top.sort(key=lambda r: r["x"])
    # 1200 = 3 x 400 exactly; no short tail
    assert [r["length_cm"] for r in top] == [400.0, 400.0, 400.0]


def test_hedge_offset_outward():
    rows = hedge_runs(SQUARE_LAYOUT, min_run_cm=800.0, offset_cm=60.0,
                      segment_cm=400.0)
    for r in rows:
        if r["yaw"] == -90.0:
            assert abs(r["y"] - (-60.0)) < 1e-6


def test_hedge_yaw_outward():
    rows = hedge_runs(SQUARE_LAYOUT, min_run_cm=800.0, offset_cm=60.0,
                      segment_cm=400.0)
    _assert_yaw_outward(rows, SQUARE)


def test_hedge_no_piece_exceeds_segment():
    rows = hedge_runs(layout(rect_block("block_0_0", 0.0, 0.0, 10000.0,
                                        500.0)),
                      min_run_cm=800.0, offset_cm=60.0, segment_cm=400.0)
    assert all(r["length_cm"] <= 400.0 + 1e-6 for r in rows)


@pytest.mark.parametrize("bad", [
    {"min_run_cm": 0.0},
    {"min_run_cm": -3.0},
    {"offset_cm": 0.0},
    {"segment_cm": -100.0},
])
def test_hedge_value_error(bad):
    kwargs = {"min_run_cm": 800.0, "offset_cm": 60.0, "segment_cm": 400.0}
    kwargs.update(bad)
    with pytest.raises(ValueError):
        hedge_runs(SQUARE_LAYOUT, **kwargs)


# ---------------------------------------------------------------------------
# clusters
# ---------------------------------------------------------------------------

def test_cluster_rows_have_schema_fields():
    rows = courtyard_clusters(SQUARE_LAYOUT, per_block=3, radius_cm=150.0,
                              seed="s1")
    assert len(rows) == 3
    for r in rows:
        assert set(r) == {"id", "block_id", "x", "y", "radius_cm", "kind"}
        assert r["kind"] == "cluster"
        assert r["radius_cm"] == 150.0


def test_cluster_points_inside_and_clear_of_edges():
    rows = courtyard_clusters(SQUARE_LAYOUT, per_block=10, radius_cm=150.0,
                              seed="s1")
    assert len(rows) == 10
    for r in rows:
        x, y = r["x"], r["y"]
        assert 150.0 - 1e-6 <= x <= 1000.0 - 150.0 + 1e-6
        assert 150.0 - 1e-6 <= y <= 1000.0 - 150.0 + 1e-6


def test_clusters_deterministic_across_calls():
    a = courtyard_clusters(SQUARE_LAYOUT, per_block=5, radius_cm=100.0,
                           seed="same-seed")
    b = courtyard_clusters(SQUARE_LAYOUT, per_block=5, radius_cm=100.0,
                           seed="same-seed")
    assert a == b


def test_clusters_different_seeds_differ():
    a = courtyard_clusters(SQUARE_LAYOUT, per_block=5, radius_cm=100.0,
                           seed="seed-a")
    b = courtyard_clusters(SQUARE_LAYOUT, per_block=5, radius_cm=100.0,
                           seed="seed-b")
    assert a != b
    assert {r["id"] for r in a} == {r["id"] for r in b}


def test_clusters_per_block_and_sorted_ids():
    rows = courtyard_clusters(TWO_BLOCK, per_block=4, radius_cm=150.0,
                              seed="multi")
    assert len(rows) == 8
    ids = [r["id"] for r in rows]
    assert ids == sorted(ids)
    assert sum(1 for r in rows if r["block_id"] == "block_0_0") == 4
    assert sum(1 for r in rows if r["block_id"] == "block_1_1") == 4


def test_clusters_inside_block_polygon_two_blocks():
    rows = courtyard_clusters(TWO_BLOCK, per_block=6, radius_cm=200.0,
                              seed="poly")
    for r in rows:
        if r["block_id"] == "block_0_0":
            lo_x = lo_y = 0.0
            hi_x = hi_y = 2000.0
        else:
            lo_x = lo_y = 3000.0
            hi_x = hi_y = 5000.0
        assert lo_x + 200.0 - 1e-6 <= r["x"] <= hi_x - 200.0 + 1e-6
        assert lo_y + 200.0 - 1e-6 <= r["y"] <= hi_y - 200.0 + 1e-6


@pytest.mark.parametrize("bad", [{"per_block": 0}, {"per_block": -2},
                                 {"per_block": 1.5}, {"per_block": True}])
def test_clusters_per_block_value_error(bad):
    kwargs = {"per_block": 3, "radius_cm": 100.0, "seed": "s"}
    kwargs.update(bad)
    with pytest.raises(ValueError):
        courtyard_clusters(SQUARE_LAYOUT, **kwargs)


def test_clusters_radius_value_error():
    with pytest.raises(ValueError):
        courtyard_clusters(SQUARE_LAYOUT, per_block=3, radius_cm=-10.0,
                           seed="s")


def test_clusters_radius_bigger_than_smallest_inradius_value_error():
    # block_0_0 is 400x400 (inradius 200); block_1_1 is 2000x2000
    mixed = layout(rect_block("block_0_0", 0.0, 0.0, 400.0, 400.0),
                   rect_block("block_1_1", 5000.0, 5000.0, 7000.0, 7000.0))
    with pytest.raises(ValueError):
        courtyard_clusters(mixed, per_block=2, radius_cm=250.0, seed="s")


def test_clusters_radius_under_inradius_is_accepted():
    # 400x400 block, inradius 200: a 100 cm clearance is comfortably plantable
    small = layout(rect_block("block_0_0", 0.0, 0.0, 400.0, 400.0))
    rows = courtyard_clusters(small, per_block=2, radius_cm=100.0, seed="s")
    assert len(rows) == 2
    for r in rows:
        assert 100.0 - 1e-6 <= r["x"] <= 300.0 + 1e-6
        assert 100.0 - 1e-6 <= r["y"] <= 300.0 + 1e-6


def test_clusters_empty_layout():
    assert courtyard_clusters(layout(), per_block=3, radius_cm=100.0,
                              seed="s") == []


# ---------------------------------------------------------------------------
# whole plan + determinism
# ---------------------------------------------------------------------------

def test_foliage_plan_document_keys_and_counts():
    doc = foliage_plan(SQUARE_LAYOUT, spacing_cm=300.0, min_run_cm=800.0,
                       per_block=3)
    assert doc["schema_version"] == FOLIAGE_PLAN_VERSION
    assert set(doc) == {"schema_version", "params", "counts", "planters",
                        "hedges", "clusters"}
    assert doc["counts"]["planters"] == len(doc["planters"])
    assert doc["counts"]["hedges"] == len(doc["hedges"])
    assert doc["counts"]["clusters"] == len(doc["clusters"])
    assert doc["counts"]["planters"] == 12
    assert doc["counts"]["clusters"] == 3


def test_foliage_plan_byte_identical_json():
    doc1 = foliage_plan(TWO_BLOCK, spacing_cm=300.0, min_run_cm=800.0,
                        per_block=3, radius_cm=150.0, seed="stable")
    doc2 = foliage_plan(TWO_BLOCK, spacing_cm=300.0, min_run_cm=800.0,
                        per_block=3, radius_cm=150.0, seed="stable")
    assert json.dumps(doc1, sort_keys=True) == json.dumps(doc2, sort_keys=True)


def test_foliage_plan_all_floats_rounded_and_no_neg_zero():
    doc = foliage_plan(TWO_BLOCK, spacing_cm=300.0, per_block=3,
                       radius_cm=150.0)

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, float):
            assert o == 0.0 or abs(o - round(o, 3)) < 1e-9
            assert not (o == 0.0 and math.copysign(1.0, o) < 0.0)

    walk(doc)


# ---------------------------------------------------------------------------
# conflicts
# ---------------------------------------------------------------------------

def _hedge_plan(x=100.0, y=100.0, length=400.0):
    return {"planters": [],
            "hedges": [{"id": "block_0_0:hedge:000", "block_id": "block_0_0",
                        "x": x, "y": y, "yaw": -90.0, "length_cm": length,
                        "kind": "hedge"}],
            "clusters": []}


def test_conflicts_finds_hedge_over_lamp_post():
    plan = _hedge_plan(x=100.0, y=100.0)
    occupied = [{"x": 100.0, "y": 100.0, "radius_cm": 30.0}]  # lamp post
    hits = conflicts(plan, occupied, clearance_cm=10.0)
    assert len(hits) == 1
    assert hits[0]["row_id"] == "block_0_0:hedge:000"
    assert hits[0]["kind"] == "hedge"
    assert hits[0]["gap_cm"] < 10.0


def test_conflicts_finds_planter_and_cluster():
    plan = {"planters": [{"id": "b:p:0", "block_id": "b", "x": 0.0, "y": 0.0,
                          "yaw": 0.0, "width_cm": 120.0, "depth_cm": 120.0,
                          "kind": "planter"}],
            "hedges": [],
            "clusters": [{"id": "b:c:0", "block_id": "b", "x": 50.0,
                          "y": 50.0, "radius_cm": 20.0, "kind": "cluster"}]}
    occupied = [{"x": 0.0, "y": 0.0, "radius_cm": 30.0},
                {"x": 50.0, "y": 50.0, "radius_cm": 30.0}]
    hits = conflicts(plan, occupied, clearance_cm=5.0)
    assert {h["row_id"] for h in hits} == {"b:p:0", "b:c:0"}


def test_conflicts_empty_when_clear():
    plan = _hedge_plan(x=0.0, y=0.0, length=400.0)
    occupied = [{"x": 5000.0, "y": 5000.0, "radius_cm": 30.0}]
    assert conflicts(plan, occupied, clearance_cm=10.0) == []


def test_conflicts_respects_clearance_threshold():
    # obstacle radius 30 + hedge radius 200; centre distance 240 -> gap 10
    plan = _hedge_plan(x=0.0, y=0.0, length=400.0)
    occupied = [{"x": 240.0, "y": 0.0, "radius_cm": 30.0}]
    assert conflicts(plan, occupied, clearance_cm=9.0) == []
    assert len(conflicts(plan, occupied, clearance_cm=11.0)) == 1


def test_conflicts_clearance_value_error():
    plan = _hedge_plan()
    occupied = [{"x": 0.0, "y": 0.0, "radius_cm": 10.0}]
    with pytest.raises(ValueError):
        conflicts(plan, occupied, clearance_cm=0.0)
    with pytest.raises(ValueError):
        conflicts(plan, occupied, clearance_cm=-1.0)


def test_conflicts_multiple_obstacles_one_hit_one_clear():
    plan = _hedge_plan(x=100.0, y=100.0)
    occupied = [{"x": 100.0, "y": 100.0, "radius_cm": 30.0},
                {"x": 9000.0, "y": 9000.0, "radius_cm": 30.0}]
    hits = conflicts(plan, occupied, clearance_cm=10.0)
    assert len(hits) == 1
    assert hits[0]["obstacle_x"] == 100.0
