"""Tests for ldyf/ground_plan.py — pure stdlib, nothing read from disk.

Run from the repository root:
    python -m unittest ldyf.tests.test_ground_plan -v
"""

from __future__ import annotations

import json
import math
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from ldyf import ground_plan as gp  # noqa: E402


def _rect_poly(x0, y0, x1, y1):
    return [
        {"x": x0, "y": y0},
        {"x": x1, "y": y0},
        {"x": x1, "y": y1},
        {"x": x0, "y": y1},
    ]


def _block(bid, x0, y0, x1, y1):
    return {
        "id": bid,
        "polygon": _rect_poly(x0, y0, x1, y1),
        "bbox": {"x_min": x0, "y_min": y0, "x_max": x1, "y_max": y1},
    }


def _corridor(x0, y0, x1, y1):
    # city_layout emits corridors as raw polygons (road_corridor_polygons)
    return _rect_poly(x0, y0, x1, y1)


def _layout(blocks, corridors=()):
    return {"blocks": list(blocks), "corridors": list(corridors)}


def _dist(x0, y0, x1, y1):
    return math.hypot(x1 - x0, y1 - y0)


def _single_block_plan(block, **kwargs):
    """ground_plan for a lone block with sane defaults overridable by kwargs."""
    defaults = dict(margin_cm=0.0, texture_metres=2.0, max_polygon_cm=500.0)
    defaults.update(kwargs)
    layout = _layout([block])
    return gp.ground_plan(layout, {}, **defaults)


class GroundPlanTests(unittest.TestCase):

    def test_schema_version_constant(self):
        self.assertEqual(gp.GROUND_PLAN_VERSION, "ground_plan_v1")

    def test_f3_kills_neg_zero(self):
        self.assertEqual(gp._f3(-0.0001), 0.0)
        self.assertFalse(math.copysign(1.0, gp._f3(-0.0001)) < 0)
        self.assertEqual(gp._f3(1.23456), 1.235)

    def test_one_block_one_surface_out(self):
        layout = _layout([_block("b0", 0, 0, 1000, 1000)])
        rows = gp.block_ground_polygons(layout, margin_cm=0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "b0")
        self.assertEqual(rows[0]["kind"], "ground")

    def test_block_row_shape(self):
        layout = _layout([_block("b0", 0, 0, 100, 200)])
        row = gp.block_ground_polygons(layout, margin_cm=0)[0]
        for key in ("id", "polygon", "area_cm2", "bbox", "centre", "uv_scale_cm"):
            self.assertIn(key, row)
        self.assertEqual(row["area_cm2"], 20000.0)

    def test_block_area_rectangle_known(self):
        layout = _layout([_block("b0", 0, 0, 500, 300)])
        rows = gp.block_ground_polygons(layout, margin_cm=0)
        self.assertEqual(rows[0]["area_cm2"], 150000.0)

    def test_zero_margin_keeps_vertices(self):
        layout = _layout([_block("b0", 10, 20, 110, 220)])
        row = gp.block_ground_polygons(layout, margin_cm=0)[0]
        self.assertEqual([(p["x"], p["y"]) for p in row["polygon"]],
                         [(10.0, 20.0), (110.0, 20.0),
                          (110.0, 220.0), (10.0, 220.0)])

    def test_margin_expands_vertices_outward(self):
        layout = _layout([_block("b0", 0, 0, 100, 100)])
        margin = 10.0
        row = gp.block_ground_polygons(layout, margin_cm=margin)[0]
        cx, cy = 50.0, 50.0
        self.assertEqual(len(row["polygon"]), 4)
        old_corners = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
        for old, new in zip(old_corners,
                            [(p["x"], p["y"]) for p in row["polygon"]]):
            self.assertGreater(_dist(cx, cy, new[0], new[1]),
                               _dist(cx, cy, old[0], old[1]))
            # every vertex pushed radially outward by (about) the margin
            self.assertAlmostEqual(_dist(cx, cy, new[0], new[1])
                                   - _dist(cx, cy, old[0], old[1]),
                                   margin, delta=0.01)

    def test_negative_margin_raises(self):
        layout = _layout([_block("b0", 0, 0, 100, 100)])
        with self.assertRaises(ValueError):
            gp.block_ground_polygons(layout, margin_cm=-1)

    def test_large_block_subdivision_count(self):
        # 100 x 200 cm parent, max piece 80 cm -> cols=2 rows=3 -> 6 pieces
        plan = _single_block_plan(_block("b0", 0, 0, 100, 200),
                                  max_polygon_cm=80.0)
        self.assertEqual(plan["counts"]["surfaces"], 6)
        self.assertEqual(plan["counts"]["subdivided_parents"], 1)
        self.assertEqual(plan["counts"]["subdivision_pieces"], 6)
        self.assertEqual(len(plan["surfaces"]), 6)

    def test_pieces_tile_parent_area(self):
        plan = _single_block_plan(_block("b0", 0, 0, 100, 200),
                                  max_polygon_cm=80.0)
        piece_sum = sum(s["area_cm2"] for s in plan["surfaces"])
        self.assertAlmostEqual(piece_sum, 100.0 * 200.0, delta=0.01)

    def test_pieces_have_parent_id(self):
        plan = _single_block_plan(_block("b0", 0, 0, 100, 200),
                                  max_polygon_cm=80.0)
        ids = [s["id"] for s in plan["surfaces"]]
        self.assertNotIn("b0", ids)  # the parent was replaced by its pieces
        for s in plan["surfaces"]:
            self.assertEqual(s["parent_id"], "b0")
            self.assertNotEqual(s["id"], "b0")

    def test_piece_ids_unique_and_sorted(self):
        plan = _single_block_plan(_block("b0", 0, 0, 100, 200),
                                  max_polygon_cm=80.0)
        ids = [s["id"] for s in plan["surfaces"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, sorted(ids))

    def test_piece_bbox_within_max(self):
        plan = _single_block_plan(_block("b0", 0, 0, 500, 400),
                                  max_polygon_cm=200.0)
        for s in plan["surfaces"]:
            bb = s["bbox"]
            self.assertLessEqual(bb["max_x"] - bb["min_x"], 200.0 + 1e-6)
            self.assertLessEqual(bb["max_y"] - bb["min_y"], 200.0 + 1e-6)

    def test_no_subdivision_when_small(self):
        plan = _single_block_plan(_block("b0", 0, 0, 100, 100),
                                  max_polygon_cm=500.0)
        self.assertEqual(plan["counts"]["surfaces"], 1)
        self.assertEqual(plan["counts"]["subdivided_parents"], 0)
        self.assertEqual(plan["surfaces"][0]["id"], "b0")
        self.assertNotIn("parent_id", plan["surfaces"][0])

    def test_subdivision_both_axes_grid(self):
        # 250 x 150, max 100 -> cols=3 rows=2 -> 6 quads
        plan = _single_block_plan(_block("b0", 0, 0, 250, 150),
                                  max_polygon_cm=100.0)
        self.assertEqual(plan["counts"]["surfaces"], 6)
        for s in plan["surfaces"]:
            self.assertEqual(len(s["polygon"]), 4)

    def test_uv_scale_honoured(self):
        plan = _single_block_plan(_block("b0", 0, 0, 100, 100),
                                  texture_metres=4.0)
        self.assertEqual(plan["surfaces"][0]["uv_scale_cm"], 400.0)
        rows = gp.block_ground_polygons(_layout([_block("b0", 0, 0, 100, 100)]),
                                        margin_cm=0)
        self.assertEqual(rows[0]["uv_scale_cm"], gp.DEFAULT_UV_SCALE_CM)

    def test_gap_polygons_kind_verge(self):
        layout = _layout([_block("b0", 0, 0, 100, 100)],
                         [_corridor(0, 150, 200, 250)])
        rows = gp.gap_polygons(layout, {}, margin_cm=0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "verge")
        self.assertEqual(rows[0]["source_block"], "b0")
        self.assertEqual(rows[0]["source_corridor"], "corridor_0")

    def test_gap_polygons_area(self):
        layout = _layout([_block("b0", 0, 0, 100, 100)],
                         [_corridor(0, 150, 200, 250)])
        rows = gp.gap_polygons(layout, {}, margin_cm=0)
        # strip 100 wide (x overlap 0..100) x 50 tall (y 100..150)
        self.assertEqual(rows[0]["area_cm2"], 5000.0)

    def test_gap_strips_disjoint_from_block_ground(self):
        layout = _layout([_block("b0", 0, 0, 100, 100)],
                         [_corridor(0, 140, 200, 240)])
        plan = gp.ground_plan(layout, {}, margin_cm=20.0, texture_metres=2.0,
                              max_polygon_cm=500.0)
        # margin expansion is radial, so the 100x100 block's y-extent grows
        # to 50 + 50*(sqrt(2)*50+20)/(sqrt(2)*50) = 114.14; the verge strip
        # must start exactly there and end at the corridor's near edge (140)
        self.assertEqual(plan["counts"]["verges"], 1)
        block_row = [s for s in plan["surfaces"] if s["kind"] == "ground"][0]
        strip_row = [s for s in plan["surfaces"] if s["kind"] == "verge"][0]
        self.assertAlmostEqual(block_row["bbox"]["max_y"], 114.142, delta=0.01)
        self.assertEqual(strip_row["bbox"]["min_y"], block_row["bbox"]["max_y"])
        self.assertEqual(strip_row["bbox"]["max_y"], 140.0)
        self.assertEqual(gp.overlaps(plan, tol_cm=0), [])

    def test_ground_plan_document_schema(self):
        plan = _single_block_plan(_block("b0", 0, 0, 100, 100),
                                  margin_cm=5.0)
        self.assertEqual(plan["schema_version"], gp.GROUND_PLAN_VERSION)
        self.assertEqual(plan["params"]["margin_cm"], 5.0)
        self.assertEqual(plan["params"]["texture_metres"], 2.0)
        self.assertEqual(plan["params"]["max_polygon_cm"], 500.0)
        self.assertEqual(plan["params"]["spec"], {})
        self.assertIn("counts", plan)
        self.assertIn("surfaces", plan)

    def test_ground_plan_counts(self):
        layout = _layout(
            [_block("b0", 0, 0, 100, 100), _block("b1", 300, 0, 400, 100)],
            [_corridor(0, 150, 400, 250)],
        )
        plan = gp.ground_plan(layout, {}, margin_cm=0.0, texture_metres=2.0,
                              max_polygon_cm=500.0)
        self.assertEqual(plan["counts"]["blocks"], 2)
        self.assertEqual(plan["counts"]["verges"], 2)
        self.assertEqual(plan["counts"]["surfaces"], 4)

    def test_total_area_arithmetic(self):
        layout = _layout([_block("b0", 0, 0, 100, 100),
                          _block("b1", 200, 0, 250, 50)])
        plan = gp.ground_plan(layout, {}, margin_cm=0, texture_metres=2.0,
                              max_polygon_cm=500.0)
        self.assertEqual(gp.total_area_cm2(plan), 10000.0 + 2500.0)

    def test_total_area_matches_after_subdivision(self):
        plan = _single_block_plan(_block("b0", 0, 0, 100, 200),
                                  max_polygon_cm=80.0)
        self.assertAlmostEqual(gp.total_area_cm2(plan), 20000.0, delta=0.01)

    def test_overlaps_finds_deliberate_pair(self):
        layout = _layout([_block("b0", 0, 0, 100, 100),
                          _block("b1", 50, 50, 150, 150)])
        plan = gp.ground_plan(layout, {}, margin_cm=0, texture_metres=2.0,
                              max_polygon_cm=500.0)
        result = gp.overlaps(plan, tol_cm=0)
        self.assertEqual(len(result), 1)
        self.assertEqual({result[0]["a"], result[0]["b"]}, {"b0", "b1"})
        self.assertGreater(result[0]["overlap_area_cm2"], 0)

    def test_overlaps_clean_plan_empty(self):
        layout = _layout([_block("b0", 0, 0, 100, 100),
                          _block("b1", 200, 0, 300, 100)])
        plan = gp.ground_plan(layout, {}, margin_cm=0, texture_metres=2.0,
                              max_polygon_cm=500.0)
        self.assertEqual(gp.overlaps(plan, tol_cm=0), [])

    def test_overlaps_adjacent_sharing_edge_is_clean(self):
        layout = _layout([_block("b0", 0, 0, 100, 100),
                          _block("b1", 100, 0, 200, 100)])
        plan = gp.ground_plan(layout, {}, margin_cm=0, texture_metres=2.0,
                              max_polygon_cm=500.0)
        self.assertEqual(gp.overlaps(plan, tol_cm=0), [])

    def test_overlaps_tolerance_ignores_sliver(self):
        layout = _layout([_block("b0", 0, 0, 100, 100),
                          _block("b1", 99, 0, 199, 100)])
        plan = gp.ground_plan(layout, {}, margin_cm=0, texture_metres=2.0,
                              max_polygon_cm=500.0)
        # 1 cm sliver: tol_cm=0 sees it; the tol_cm=10 shrink separates them
        self.assertEqual(len(gp.overlaps(plan, tol_cm=0)), 1)
        self.assertEqual(gp.overlaps(plan, tol_cm=10), [])

    def test_negative_tol_raises(self):
        plan = _single_block_plan(_block("b0", 0, 0, 100, 100))
        with self.assertRaises(ValueError):
            gp.overlaps(plan, tol_cm=-1)

    def test_determinism_byte_identical(self):
        layout = _layout(
            [_block("b0", 0, 0, 300, 200), _block("b1", 500, 100, 900, 700)],
            [_corridor(0, 400, 900, 450)],
        )
        args = dict(margin_cm=15.0, texture_metres=2.0, max_polygon_cm=200.0)
        p1 = gp.ground_plan(layout, {"k": [1, 2]}, **args)
        p2 = gp.ground_plan(layout, {"k": [1, 2]}, **args)
        self.assertEqual(json.dumps(p1, sort_keys=True),
                         json.dumps(p2, sort_keys=True))

    def test_empty_layout_raises(self):
        layout = _layout([])
        with self.assertRaises(ValueError):
            gp.ground_plan(layout, {}, margin_cm=0, texture_metres=2.0,
                           max_polygon_cm=500.0)
        with self.assertRaises(ValueError):
            gp.block_ground_polygons(layout, margin_cm=0)

    def test_nonpositive_max_polygon_raises(self):
        block = _block("b0", 0, 0, 100, 100)
        for bad in (0.0, -5.0):
            with self.assertRaises(ValueError):
                _single_block_plan(block, max_polygon_cm=bad)

    def test_nonpositive_texture_metres_raises(self):
        block = _block("b0", 0, 0, 100, 100)
        for bad in (0.0, -2.0):
            with self.assertRaises(ValueError):
                _single_block_plan(block, texture_metres=bad)

    def test_margin_expansion_grows_area(self):
        layout = _layout([_block("b0", 0, 0, 100, 100)])
        plain = gp.block_ground_polygons(layout, margin_cm=0)[0]
        grown = gp.block_ground_polygons(layout, margin_cm=10)[0]
        self.assertGreater(grown["area_cm2"], plain["area_cm2"])
        self.assertAlmostEqual(grown["area_cm2"], 10000.0, delta=4200.0)

    def test_block_bbox_centre_fields(self):
        layout = _layout([_block("b0", 10, 20, 210, 320)])
        row = gp.block_ground_polygons(layout, margin_cm=0)[0]
        self.assertEqual(row["bbox"],
                         {"min_x": 10.0, "min_y": 20.0,
                          "max_x": 210.0, "max_y": 320.0})
        self.assertEqual(row["centre"], {"x": 110.0, "y": 170.0})

    def test_block_bbox_style_x_min_accepted(self):
        # city_layout blocks carry bbox keyed x_min/x_max/y_min/y_max
        block = {"id": "b0",
                 "bbox": {"x_min": 10.0, "y_min": 20.0,
                          "x_max": 210.0, "y_max": 320.0}}
        row = gp.block_ground_polygons(_layout([block]), margin_cm=0)[0]
        self.assertEqual(row["bbox"]["min_x"], 10.0)
        self.assertEqual(row["bbox"]["max_y"], 320.0)
        self.assertEqual(row["area_cm2"], 200.0 * 300.0)

    def test_ground_plan_returns_per_block_plus_verges(self):
        # two blocks + one corridor: b0 gets a verge, far b1 gets none
        layout = _layout(
            [_block("b0", 0, 0, 100, 100), _block("b1", 300, 300, 400, 400)],
            [_corridor(0, 150, 400, 250)],
        )
        plan = gp.ground_plan(layout, {}, margin_cm=0, texture_metres=2.0,
                              max_polygon_cm=500.0)
        self.assertEqual(plan["counts"]["blocks"], 2)
        self.assertEqual(plan["counts"]["verges"], 1)
        self.assertEqual(plan["counts"]["surfaces"], 3)


if __name__ == "__main__":
    unittest.main()
