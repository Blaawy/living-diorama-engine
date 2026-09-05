"""Tests for ldyf.horizon - stdlib unittest, inline fixtures only."""
import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from ldyf import horizon as hz  # noqa: E402


def sample_spec():
    """Hand-built road_spec_v1: two straight lanes, world 400 x 90 cm."""
    return {"schema_version": "road_spec_v1", "lanes": [
        {"lane_id": "a", "polyline": [{"x": -100.0, "y": -50.0},
                                      {"x": 300.0, "y": -50.0}]},
        {"lane_id": "b", "polyline": [{"x": 0.0, "y": 40.0},
                                      {"x": 300.0, "y": 40.0}]},
    ]}


def sample_bounds():
    return hz.world_bounds(sample_spec())


def rect(row):
    xs = [p["x"] for p in row["polygon"]]
    ys = [p["y"] for p in row["polygon"]]
    return (min(xs), max(xs), min(ys), max(ys))


def rects_overlap(a, b):
    (ax0, ax1, ay0, ay1), (bx0, bx1, by0, by1) = a, b
    return (ax0 < bx1 - 1e-9 and bx0 < ax1 - 1e-9 and
            ay0 < by1 - 1e-9 and by0 < ay1 - 1e-9)


def block_corners(block, cx, cy):
    w = block["width_cm"] / 2.0
    d = block["depth_cm"] / 2.0
    rad = math.radians((block["yaw"] + 180.0) % 360.0)   # outward radial
    tan = rad + math.pi / 2.0                             # tangential
    pts = []
    for su in (-1.0, 1.0):
        for sv in (-1.0, 1.0):
            pts.append((block["x"] + su * w * math.cos(tan) + sv * d * math.cos(rad),
                        block["y"] + su * w * math.sin(tan) + sv * d * math.sin(rad)))
    return pts


class TestWorldBounds(unittest.TestCase):
    def test_world_bounds_values(self):
        b = sample_bounds()
        self.assertEqual(b["x_min"], -100.0)
        self.assertEqual(b["x_max"], 300.0)
        self.assertEqual(b["y_min"], -50.0)
        self.assertEqual(b["y_max"], 40.0)

    def test_world_bounds_centre_and_size(self):
        b = sample_bounds()
        self.assertEqual(b["centre"], {"x": 100.0, "y": -5.0})
        self.assertEqual(b["size_cm"], [400.0, 90.0])

    def test_world_bounds_numeric_pairs(self):
        spec = {"schema_version": "road_spec_v1", "lanes": [
            {"lane_id": "a", "polyline": [[0, 0], [10, 0], [10, 5]]}]}
        b = hz.world_bounds(spec)
        self.assertEqual((b["x_min"], b["x_max"]), (0.0, 10.0))
        self.assertEqual((b["y_min"], b["y_max"]), (0.0, 5.0))

    def test_world_bounds_roads_nesting(self):
        spec = {"schema_version": "road_spec_v1", "roads": [
            {"road_id": 1, "lanes": [
                {"lane_id": "a", "polyline": [{"x": 2, "y": 3}, {"x": 12, "y": 3}]}]}]}
        b = hz.world_bounds(spec)
        self.assertEqual((b["x_min"], b["x_max"]), (2.0, 12.0))

    def test_world_bounds_no_polylines_raises(self):
        with self.assertRaises(ValueError):
            hz.world_bounds({"schema_version": "road_spec_v1", "lanes": []})

    def test_world_bounds_degenerate_raises(self):
        spec = {"schema_version": "road_spec_v1", "lanes": [
            {"lane_id": "a", "polyline": [{"x": 1, "y": 1}, {"x": 1, "y": 1}]}]}
        with self.assertRaises(ValueError):
            hz.world_bounds(spec)

    def test_world_bounds_floats_three_decimals(self):
        b = sample_bounds()
        for key, value in b.items():
            if key in ("centre",):
                for v in value.values():
                    self.assertEqual(v, round(v, 3))
            elif key != "size_cm":
                self.assertEqual(value, round(value, 3))


class TestSkirtRing(unittest.TestCase):
    MARGIN, WIDTH, SEG = 2.0, 100.0, 6

    def ring(self):
        return hz.skirt_ring(sample_bounds(), inner_margin_cm=self.MARGIN,
                             width_cm=self.WIDTH, segments=self.SEG)

    def test_skirt_row_schema(self):
        row = self.ring()[0]
        self.assertEqual(row["kind"], "skirt")
        self.assertIn("id", row)
        self.assertEqual(len(row["polygon"]), 4)
        self.assertTrue(all(set(p) == {"x", "y"} for p in row["polygon"]))
        self.assertEqual(set(row["centre"]), {"x", "y"})
        self.assertIsInstance(row["yaw"], float)

    def test_skirt_row_count(self):
        self.assertEqual(len(self.ring()), 4 * self.SEG + 4)

    def test_skirt_segments_honoured_per_side(self):
        ids = [r["id"] for r in self.ring()]
        for prefix in ("skirt_b_", "skirt_r_", "skirt_t_", "skirt_l_"):
            self.assertEqual(sum(1 for i in ids if i.startswith(prefix)), self.SEG)

    def test_skirt_inner_edge_at_margin_all_sides(self):
        b = sample_bounds()
        rows = self.ring()
        bottoms = [rect(r) for r in rows if r["id"].startswith("skirt_b_")]
        tops = [rect(r) for r in rows if r["id"].startswith("skirt_t_")]
        lefts = [rect(r) for r in rows if r["id"].startswith("skirt_l_")]
        rights = [rect(r) for r in rows if r["id"].startswith("skirt_r_")]
        self.assertTrue(all(abs(r[3] - (b["y_min"] - self.MARGIN)) < 1e-6 for r in bottoms))
        self.assertTrue(all(abs(r[2] - (b["y_max"] + self.MARGIN)) < 1e-6 for r in tops))
        self.assertTrue(all(abs(r[1] - (b["x_min"] - self.MARGIN)) < 1e-6 for r in lefts))
        self.assertTrue(all(abs(r[0] - (b["x_max"] + self.MARGIN)) < 1e-6 for r in rights))

    def test_skirt_outer_reach_all_sides(self):
        b = sample_bounds()
        rows = self.ring()
        b0, x1, y0, y1 = b["x_min"], b["x_max"], b["y_min"], b["y_max"]
        out_m, out_w = self.MARGIN, self.WIDTH
        bottoms = [rect(r) for r in rows if r["id"].startswith("skirt_b_")]
        tops = [rect(r) for r in rows if r["id"].startswith("skirt_t_")]
        lefts = [rect(r) for r in rows if r["id"].startswith("skirt_l_")]
        rights = [rect(r) for r in rows if r["id"].startswith("skirt_r_")]
        self.assertTrue(all(abs(r[2] - (y0 - out_m - out_w)) < 1e-6 for r in bottoms))
        self.assertTrue(all(abs(r[3] - (y1 + out_m + out_w)) < 1e-6 for r in tops))
        self.assertTrue(all(abs(r[0] - (b0 - out_m - out_w)) < 1e-6 for r in lefts))
        self.assertTrue(all(abs(r[1] - (x1 + out_m + out_w)) < 1e-6 for r in rights))

    def test_skirt_covers_probes_on_all_sides(self):
        b = sample_bounds()
        rows = self.ring()
        cx, cy = b["centre"]["x"], b["centre"]["y"]
        probes = [(cx, b["y_min"] - self.MARGIN - 5.0),
                  (cx, b["y_max"] + self.MARGIN + 5.0),
                  (b["x_min"] - self.MARGIN - 5.0, cy),
                  (b["x_max"] + self.MARGIN + 5.0, cy)]
        for px, py in probes:
            hits = [r for r in rows
                    if rect(r)[0] - 1e-9 <= px <= rect(r)[1] + 1e-9
                    and rect(r)[2] - 1e-9 <= py <= rect(r)[3] + 1e-9]
            self.assertEqual(len(hits), 1, "probe (%s, %s)" % (px, py))

    def test_skirt_covers_diagonal_corners(self):
        b = sample_bounds()
        rows = self.ring()
        off = self.MARGIN + self.WIDTH / 2.0
        probes = [(b["x_min"] - off, b["y_min"] - off),
                  (b["x_max"] + off, b["y_min"] - off),
                  (b["x_max"] + off, b["y_max"] + off),
                  (b["x_min"] - off, b["y_max"] + off)]
        for px, py in probes:
            hits = [r for r in rows
                    if rect(r)[0] - 1e-9 <= px <= rect(r)[1] + 1e-9
                    and rect(r)[2] - 1e-9 <= py <= rect(r)[3] + 1e-9]
            self.assertEqual(len(hits), 1, "corner probe (%s, %s)" % (px, py))

    def test_skirt_no_two_quads_overlap(self):
        rows = self.ring()
        rects = [rect(r) for r in rows]
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                self.assertFalse(rects_overlap(rects[i], rects[j]),
                                 "overlap %s/%s" % (rows[i]["id"], rows[j]["id"]))

    def test_skirt_area_tiles_annulus(self):
        b = sample_bounds()
        m, w = self.MARGIN, self.WIDTH
        sx = (b["x_max"] - b["x_min"]) + 2.0 * m
        sy = (b["y_max"] - b["y_min"]) + 2.0 * m
        expected = (sx + 2.0 * w) * (sy + 2.0 * w) - sx * sy
        total = sum((r[1] - r[0]) * (r[3] - r[2]) for r in map(rect, self.ring()))
        self.assertAlmostEqual(total, expected, delta=0.01)

    def test_skirt_subdivision_widths(self):
        b = sample_bounds()
        bottoms = [rect(r) for r in self.ring() if r["id"].startswith("skirt_b_")]
        inner_w = (b["x_max"] - b["x_min"]) + 2.0 * self.MARGIN
        for r in bottoms:
            self.assertAlmostEqual(r[1] - r[0], inner_w / self.SEG, delta=0.01)

    def test_skirt_yaw_faces_centre(self):
        b = sample_bounds()
        cx, cy = b["centre"]["x"], b["centre"]["y"]
        for row in self.ring():
            expected = math.degrees(math.atan2(cy - row["centre"]["y"],
                                               cx - row["centre"]["x"])) % 360.0
            self.assertAlmostEqual(row["yaw"], expected, delta=0.01)

    def test_skirt_ids_unique_and_sorted(self):
        rows = self.ring()
        ids = [r["id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, sorted(ids))

    def test_skirt_width_nonpositive_raises(self):
        with self.assertRaises(ValueError):
            hz.skirt_ring(sample_bounds(), inner_margin_cm=0.0,
                          width_cm=0.0, segments=4)

    def test_skirt_segments_nonpositive_raises(self):
        with self.assertRaises(ValueError):
            hz.skirt_ring(sample_bounds(), inner_margin_cm=0.0,
                          width_cm=10.0, segments=0)

    def test_skirt_negative_margin_raises(self):
        with self.assertRaises(ValueError):
            hz.skirt_ring(sample_bounds(), inner_margin_cm=-1.0,
                          width_cm=10.0, segments=4)

    def test_skirt_deterministic(self):
        a = self.ring()
        b = self.ring()
        self.assertEqual(a, b)


class TestBackdrop(unittest.TestCase):
    RING, COUNT, DEPTH = 300.0, 16, 40.0
    HEIGHTS = (600.0, 1500.0)
    SEED = "sky_test"

    def blocks(self, seed=SEED, ring=RING, count=COUNT, depth=DEPTH,
               heights=HEIGHTS):
        return hz.backdrop_blocks(sample_bounds(), ring_radius_cm=ring,
                                  count=count, height_range_cm=heights,
                                  depth_cm=depth, seed=seed)

    def test_backdrop_schema_keys(self):
        blk = self.blocks()[0]
        self.assertEqual(set(blk), {"id", "x", "y", "yaw",
                                    "width_cm", "depth_cm", "height_cm"})

    def test_backdrop_count_and_ids(self):
        blocks = self.blocks()
        self.assertEqual(len(blocks), self.COUNT)
        ids = [b["id"] for b in blocks]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(ids[0], "block_000")
        self.assertEqual(ids[-1], "block_%03d" % (self.COUNT - 1))

    def test_backdrop_ring_too_small_raises(self):
        # world half-diagonal is exactly 205.0 cm for the sample spec
        with self.assertRaises(ValueError):
            hz.backdrop_blocks(sample_bounds(), ring_radius_cm=100.0,
                               count=8, height_range_cm=self.HEIGHTS,
                               depth_cm=40.0, seed="s")

    def test_backdrop_nonpositive_count_raises(self):
        with self.assertRaises(ValueError):
            hz.backdrop_blocks(sample_bounds(), ring_radius_cm=self.RING,
                               count=0, height_range_cm=self.HEIGHTS,
                               depth_cm=40.0, seed="s")

    def test_backdrop_bad_height_range_raises(self):
        with self.assertRaises(ValueError):
            hz.backdrop_blocks(sample_bounds(), ring_radius_cm=self.RING,
                               count=8, height_range_cm=(900.0, 100.0),
                               depth_cm=40.0, seed="s")

    def test_backdrop_nonpositive_depth_raises(self):
        with self.assertRaises(ValueError):
            hz.backdrop_blocks(sample_bounds(), ring_radius_cm=self.RING,
                               count=8, height_range_cm=self.HEIGHTS,
                               depth_cm=0.0, seed="s")

    def test_backdrop_vertices_outside_ring(self):
        b = sample_bounds()
        cx, cy = b["centre"]["x"], b["centre"]["y"]
        for blk in self.blocks():
            for px, py in block_corners(blk, cx, cy):
                self.assertGreaterEqual(math.hypot(px - cx, py - cy),
                                        self.RING - 1e-6)

    def test_backdrop_centres_beyond_ring(self):
        b = sample_bounds()
        cx, cy = b["centre"]["x"], b["centre"]["y"]
        for blk in self.blocks():
            self.assertGreater(math.hypot(blk["x"] - cx, blk["y"] - cy),
                               self.RING)

    def test_backdrop_yaw_faces_centre(self):
        b = sample_bounds()
        cx, cy = b["centre"]["x"], b["centre"]["y"]
        for blk in self.blocks():
            expected = math.degrees(math.atan2(cy - blk["y"],
                                               cx - blk["x"])) % 360.0
            self.assertAlmostEqual(blk["yaw"], expected, delta=0.01)

    def test_backdrop_heights_in_range(self):
        lo, hi = self.HEIGHTS
        for blk in self.blocks():
            self.assertGreaterEqual(blk["height_cm"], lo - 1e-9)
            self.assertLessEqual(blk["height_cm"], hi + 1e-9)

    def test_backdrop_widths_positive_and_capped(self):
        # max width is 2 * ring * tan(0.95 * half of 0.3 * step)
        step = 2.0 * math.pi / self.COUNT
        cap_angle = 0.95 * 0.5 * (0.3 * step)
        cap = 2.0 * self.RING * math.tan(cap_angle)
        for blk in self.blocks():
            self.assertGreater(blk["width_cm"], 0.0)
            self.assertLessEqual(blk["width_cm"], cap + 1e-6)

    def test_backdrop_no_angular_overlap(self):
        b = sample_bounds()
        cx, cy = b["centre"]["x"], b["centre"]["y"]
        blocks = self.blocks()
        spans = []
        for blk in blocks:
            mid = math.atan2(blk["y"] - cy, blk["x"] - cx)
            angs = [math.atan2(py - cy, px - cx)
                    for px, py in block_corners(blk, cx, cy)]
            alpha = max(abs(a - mid) for a in angs)
            spans.append((mid - alpha, mid + alpha))
        spans.sort()
        n = len(spans)
        for i in range(n):
            j = (i + 1) % n
            left_j = spans[j][0] + (2.0 * math.pi if j == 0 else 0.0)
            self.assertGreaterEqual(left_j, spans[i][1] - 1e-9)

    def test_backdrop_centre_angles_spaced(self):
        b = sample_bounds()
        cx, cy = b["centre"]["x"], b["centre"]["y"]
        angs = sorted(math.atan2(blk["y"] - cy, blk["x"] - cx)
                      for blk in self.blocks())
        step = 2.0 * math.pi / self.COUNT
        for i in range(len(angs)):
            j = (i + 1) % len(angs)
            gap = angs[j] - angs[i]
            if j == 0:
                gap += 2.0 * math.pi
            self.assertGreater(gap, 0.3 * step - 1e-6)

    def test_backdrop_deterministic(self):
        self.assertEqual(self.blocks(), self.blocks())

    def test_backdrop_seed_changes_heights(self):
        a = self.blocks(seed="seed_a")
        c = self.blocks(seed="seed_c")
        self.assertNotEqual([blk["height_cm"] for blk in a],
                            [blk["height_cm"] for blk in c])
        # each seed still fully deterministic
        self.assertEqual(a, self.blocks(seed="seed_a"))

    def test_backdrop_digest_matches_manual_sha256(self):
        import hashlib
        blk = self.blocks()[0]
        payload = "|".join((blk["id"], self.SEED, "height")).encode("utf-8")
        frac = int.from_bytes(hashlib.sha256(payload).digest()[:8],
                              "big") / float(1 << 64)
        lo, hi = self.HEIGHTS
        self.assertAlmostEqual(blk["height_cm"], lo + frac * (hi - lo), delta=1e-3)

    def test_backdrop_no_random_module(self):
        src = open(hz.__file__, "r", encoding="utf-8").read()
        self.assertNotIn("import random", src)
        self.assertNotIn("from random", src)


class TestFog(unittest.TestCase):
    def test_fog_cutoff_scales_with_diagonal(self):
        # sample world diagonal is exactly 410.0 cm
        f = hz.fog_settings(sample_bounds(), visibility_fraction=0.8)
        self.assertAlmostEqual(f["cutoff_distance_cm"], 328.0, delta=0.01)
        f2 = hz.fog_settings(sample_bounds(), visibility_fraction=0.5)
        self.assertAlmostEqual(f2["cutoff_distance_cm"], 205.0, delta=0.01)

    def test_fog_start_between_zero_and_cutoff(self):
        f = hz.fog_settings(sample_bounds(), visibility_fraction=0.8)
        self.assertGreater(f["start_distance_cm"], 0.0)
        self.assertLess(f["start_distance_cm"], f["cutoff_distance_cm"])

    def test_fog_density_positive_and_consistent(self):
        f = hz.fog_settings(sample_bounds(), visibility_fraction=0.8)
        self.assertGreater(f["fog_density"], 0.0)
        opacity = 1.0 - math.exp(-f["fog_density"] *
                                 (f["cutoff_distance_cm"] - f["start_distance_cm"]))
        self.assertAlmostEqual(opacity, 0.95, delta=0.01)

    def test_fog_invalid_visibility_raises(self):
        for bad in (0.0, -0.1, 1.5):
            with self.assertRaises(ValueError):
                hz.fog_settings(sample_bounds(), visibility_fraction=bad)

    def test_fog_deterministic(self):
        a = hz.fog_settings(sample_bounds(), visibility_fraction=0.8)
        b = hz.fog_settings(sample_bounds(), visibility_fraction=0.8)
        self.assertEqual(a, b)


class TestHorizonPlan(unittest.TestCase):
    def test_plan_document_keys(self):
        doc = hz.horizon_plan(sample_spec())
        self.assertEqual(doc["schema_version"], hz.HORIZON_PLAN_VERSION)
        self.assertEqual(set(doc), {"schema_version", "params", "counts",
                                    "bounds", "skirt", "backdrop", "fog"})

    def test_plan_counts_consistent(self):
        doc = hz.horizon_plan(sample_spec())
        self.assertEqual(doc["counts"]["skirt_rows"], len(doc["skirt"]))
        self.assertEqual(doc["counts"]["backdrop_blocks"], len(doc["backdrop"]))
        self.assertEqual(len(doc["skirt"]), 4 * 16 + 4)
        self.assertEqual(len(doc["backdrop"]), 48)

    def test_plan_json_byte_identical(self):
        doc = hz.horizon_plan(sample_spec())
        doc2 = hz.horizon_plan(sample_spec())
        self.assertEqual(doc, doc2)
        a = json.dumps(doc, sort_keys=True).encode("utf-8")
        b = json.dumps(doc2, sort_keys=True).encode("utf-8")
        self.assertEqual(a, b)

    def test_plan_default_ring_beyond_skirt(self):
        doc = hz.horizon_plan(sample_spec())
        ring = doc["params"]["ring_radius_cm"]
        b = doc["bounds"]
        margin = doc["params"]["inner_margin_cm"]
        width = doc["params"]["width_cm"]
        outer_corner = math.hypot((b["x_max"] - b["x_min"]) / 2.0 + margin + width,
                                  (b["y_max"] - b["y_min"]) / 2.0 + margin + width)
        self.assertGreater(ring, outer_corner)

    def test_plan_explicit_ring_too_small_raises(self):
        with self.assertRaises(ValueError):
            hz.horizon_plan(sample_spec(), ring_radius_cm=10.0)

    def test_plan_params_resolved(self):
        doc = hz.horizon_plan(sample_spec(), width_cm=500.0, skirt_segments=4,
                              backdrop_count=12, seed="fixed",
                              fog_visibility_fraction=0.7)
        p = doc["params"]
        self.assertEqual(p["width_cm"], 500.0)
        self.assertEqual(p["skirt_segments"], 4)
        self.assertEqual(p["backdrop_count"], 12)
        self.assertEqual(p["seed"], "fixed")
        self.assertEqual(p["fog_visibility_fraction"], 0.7)
        self.assertEqual(doc["counts"]["skirt_rows"], 4 * 4 + 4)
        self.assertEqual(doc["counts"]["backdrop_blocks"], 12)


if __name__ == "__main__":
    unittest.main()
