"""C4 road geometry proof: the pure checker is exact on synthetic data.

The spec is built by the SAME code path the real world uses --
``roads.build_road_spec`` over the inline tiny net pattern of
``test_roads.TINY_NET`` (hand-written SUMO XML, never netconvert). Snapshots
are hand-shaped like the in-editor sampler's component snapshot: one strip per
lane spanning the lane's spec polyline, mesh width 400 cm (SM_Lane_Car_400_500,
EVIDENCE_road_mesh_bounds.json size 500 x 400 x 20), scale_y = width_effective
/ 400, strip top z 20 cm; a J0 junction slab covering the polygon bbox; ground
covering everything at top 0. The tiny net's normal lanes are E1_0/E1_1/E2_0/
E2_1 (widths_effective 320 / 350 / 320 / 320 cm).
"""

from __future__ import annotations

import json

import pytest

from ldyf.roads import build_road_spec
from ldyf.road_geometry_check import (
    ROAD_GEOMETRY_VERSION,
    build_report,
    check_centrelines,
    check_ground,
    check_junctions,
    check_widths,
    match_strip_to_lane,
    strip_centreline,
    write_report,
)
from ldyf.tests.test_roads import TINY_NET

MESH = "/CitySamplePCG/Meshes/Roads/SM_Lane_Car_400_500"
MESH_WIDTH_CM = 400.0


# --- spec + snapshot builders ---------------------------------------------


@pytest.fixture(scope="session")
def spec(tmp_path_factory):
    p = tmp_path_factory.mktemp("road_net") / "tiny.net.xml"
    p.write_text(TINY_NET, encoding="utf-8")
    return build_road_spec(p)


def lane_by_id(spec: dict, lid: str) -> dict:
    for e in spec["edges"]:
        for ln in e["lanes"]:
            if ln["id"] == lid:
                return ln
    raise AssertionError(f"lane {lid} missing")


def lane_polyline(spec: dict, lid: str) -> list[dict]:
    return lane_by_id(spec, lid)["polyline"]


def make_strip(spec: dict, lid: str, *, lane_id=None, dx=0.0, dy=0.0,
               scale_y=None, top_z=20.0, mesh_width=MESH_WIDTH_CM) -> dict:
    poly = lane_polyline(spec, lid)
    a, b = dict(poly[0]), dict(poly[-1])
    a["x"] += dx
    a["y"] += dy
    b["x"] += dx
    b["y"] += dy
    w_eff = lane_by_id(spec, lid)["width_cm_effective"]
    if scale_y is None:
        scale_y = w_eff / mesh_width
    return {
        # None = PCG tag absent: the snapshot strip carries no lane_id and the
        # checker must recover the lane by midpoint (match_strip_to_lane).
        "lane_id": lane_id,
        "kind": "road",
        "mesh": MESH,
        "mesh_width_cm": mesh_width,
        "start": a,
        "end": b,
        "start_scale_y": scale_y,
        "end_scale_y": scale_y,
        "top_z": top_z,
    }


def all_strips(spec: dict, **kw) -> list[dict]:
    # Default fixture strips carry their real lane id (the sampler read the
    # PCG tag); pass lane_id=None into make_strip to simulate an untagged strip.
    return [
        make_strip(spec, lid, lane_id=lane_by_id(spec, lid)["id"], **kw)
        for lid in ("E1_0", "E1_1", "E2_0", "E2_1")
    ]


def j0_slab(spec: dict, *, top_z=20.0) -> dict:
    j0 = next(j for j in spec["junctions"] if j["id"] == "J0")
    xs = [p["x"] for p in j0["polygon"]]
    ys = [p["y"] for p in j0["polygon"]]
    return {
        "id": "slab_J0",
        "bounds_min": {"x": min(xs), "y": min(ys), "z": 0.0},
        "bounds_max": {"x": max(xs), "y": max(ys), "z": 0.0},
        "top_z": top_z,
    }


def full_snapshot(spec: dict, *, strips=None, slab_top=20.0, ground_top=0.0) -> dict:
    return {
        "strips": all_strips(spec) if strips is None else strips,
        "slabs": [j0_slab(spec, top_z=slab_top)],
        "ground": {
            "bounds_min": {"x": -100.0, "y": -2000.0, "z": 0.0},
            "bounds_max": {"x": 10100.0, "y": 500.0, "z": 0.0},
            "top_z": ground_top,
        },
    }


# --- strip / matching helpers ---------------------------------------------


def test_strip_centreline_returns_start_end_segment(spec):
    strip = make_strip(spec, "E1_0")
    cl = strip_centreline(strip)
    assert cl == [strip["start"], strip["end"]]
    assert cl[0] is not strip["start"]  # copies, not aliases


def test_match_strip_to_lane_finds_nearest_lane(spec):
    assert match_strip_to_lane(make_strip(spec, "E1_0"), spec, max_cm=50.0) == "E1_0"
    # E1_1's polyline is 320 cm away in Y; a strip ON it must not match E1_0
    assert match_strip_to_lane(make_strip(spec, "E1_1"), spec, max_cm=50.0) == "E1_1"
    assert match_strip_to_lane(make_strip(spec, "E2_1"), spec, max_cm=50.0) == "E2_1"


def test_match_strip_to_lane_returns_none_beyond_max_cm(spec):
    strip = make_strip(spec, "E1_0", dy=-20000.0)
    assert match_strip_to_lane(strip, spec, max_cm=50.0) is None


def test_strip_with_null_lane_id_is_matched_by_midpoint(spec):
    strips = [make_strip(spec, lid, lane_id=None) for lid in ("E1_0", "E2_0")]
    snap = full_snapshot(spec, strips=strips)
    out = check_centrelines(snap, spec)
    assert out["strips_unmatched"] == []
    assert out["per_lane"]["E1_0"]["pass"] is True
    assert out["per_lane"]["E2_0"]["pass"] is True


def test_unknown_lane_id_raises_keyerror(spec):
    strip = make_strip(spec, "E1_0", lane_id="NO_SUCH_LANE")
    with pytest.raises(KeyError):
        check_centrelines(full_snapshot(spec, strips=[strip]), spec)


# --- centreline checks ----------------------------------------------------


def test_exact_strips_pass_centrelines(spec):
    out = check_centrelines(full_snapshot(spec), spec)
    assert out["pass"] is True
    assert out["lanes_failed"] == []
    assert out["lanes_uncovered"] == []
    assert out["lanes_scope"] == 4
    for lid, row in out["per_lane"].items():
        assert row["coverage"] == pytest.approx(1.0)
        assert row["centreline_max_cm"] == pytest.approx(0.0)


def test_strip_offset_6cm_fails_at_tol_5_passes_at_tol_7(spec):
    strips = [make_strip(spec, lid, dy=(6.0 if lid == "E1_0" else 0.0)) for lid in ("E1_0", "E1_1", "E2_0", "E2_1")]
    snap = full_snapshot(spec, strips=strips)
    bad = check_centrelines(snap, spec, tol_cm=5.0)
    assert bad["pass"] is False
    assert "E1_0" in bad["lanes_failed"]
    assert bad["per_lane"]["E1_0"]["centreline_max_cm"] == pytest.approx(6.0)
    ok = check_centrelines(snap, spec, tol_cm=7.0)
    assert ok["pass"] is True


def test_lane_without_strip_reported_uncovered(spec):
    strips = [make_strip(spec, lid) for lid in ("E1_0", "E2_0", "E2_1")]  # E1_1 missing
    out = check_centrelines(full_snapshot(spec, strips=strips), spec)
    assert out["pass"] is False
    assert "E1_1" in out["lanes_uncovered"]
    assert "E1_1" in out["lanes_failed"]
    assert out["per_lane"]["E1_1"]["coverage"] == pytest.approx(0.0)
    assert out["per_lane"]["E1_1"]["strips"] == 0


def test_unmatched_strip_reported(spec):
    orphan = make_strip(spec, "E1_0", lane_id=None, dy=-30000.0)
    strips = all_strips(spec) + [orphan]
    out = check_centrelines(full_snapshot(spec, strips=strips), spec)
    assert out["pass"] is False
    assert out["strips_unmatched"] == [4]


# --- width checks ---------------------------------------------------------


def test_width_scale_0_8_matches_spec_320(spec):
    # E1_0: width_cm_effective 320; 0.8 x 400 = 320
    strip = make_strip(spec, "E1_0", scale_y=0.8)
    out = check_widths(full_snapshot(spec, strips=[strip]), spec)
    assert out["pass"] is True
    row = out  # single strip, single row
    assert row["rows"] == 1
    assert row["failed"] == []


def test_width_scale_1_0_fails_against_spec_320(spec):
    # 1.0 x 400 = 400 vs spec 320 -> error 80 cm
    strip = make_strip(spec, "E1_0", scale_y=1.0)
    out = check_widths(full_snapshot(spec, strips=[strip]), spec)
    assert out["pass"] is False
    assert out["failed"] == [0]
    assert out["worst_cm"] == pytest.approx(80.0)


def test_width_all_strips_at_spec_scales_pass(spec):
    out = check_widths(full_snapshot(spec), spec)
    assert out["pass"] is True
    assert out["failed"] == []
    assert out["rows"] == 4


# --- junction checks ------------------------------------------------------


def test_junction_slab_top_20_matches_strip_top_20(spec):
    snap = full_snapshot(spec, slab_top=20.0)
    out = check_junctions(snap, spec)
    assert out["pass"] is True
    assert out["junctions_checked"] == 1  # only J0 has a polygon
    assert out["rows"]["J0"]["covered"] is True
    assert out["rows"]["J0"]["z_error_cm"] == pytest.approx(0.0)


def test_junction_slab_top_0_vs_strip_top_20_fails(spec):
    snap = full_snapshot(spec, slab_top=0.0)
    out = check_junctions(snap, spec, tol_cm=5.0)
    assert out["pass"] is False
    assert "J0" in out["failed"]
    assert out["rows"]["J0"]["z_error_cm"] == pytest.approx(20.0)


def test_junction_missing_slab_fails(spec):
    snap = full_snapshot(spec, strips=all_strips(spec))
    snap["slabs"] = []
    out = check_junctions(snap, spec)
    assert out["pass"] is False
    assert out["rows"]["J0"]["covered"] is False


# --- ground ---------------------------------------------------------------


def test_ground_covers_extent_and_sits_below_strips(spec):
    out = check_ground(full_snapshot(spec), spec)
    assert out["pass"] is True
    assert out["extent_covered"] is True
    assert out["ground_below_strips"] is True


def test_ground_top_not_below_strip_top_fails(spec):
    # ground top 20 == strip top 20: the road would be buried, not ON the ground
    out = check_ground(full_snapshot(spec, ground_top=20.0), spec)
    assert out["pass"] is False
    assert "not below" in " ".join(out["reasons"])


# --- report ---------------------------------------------------------------


def test_build_report_schema_tolerances_and_pass(spec):
    report = build_report(full_snapshot(spec), spec, tol_cm=5.0)
    assert report["schema_version"] == ROAD_GEOMETRY_VERSION == "road_geometry_v1"
    assert report["pass"] is True
    assert report["tolerances"] == {"centreline_cm": 5.0, "width_cm": 5.0,
                                    "junction_cm": 5.0, "coverage_gap_cm": 5.0,
                                    "match_max_cm": 50.0}
    assert set(report["checks"]) == {"centrelines", "widths", "junctions", "ground"}
    assert report["totals"]["lanes_scope"] == 4
    assert report["totals"]["strips"] == 4
    assert report["worst"]["centreline_cm"]["max_cm"] == 0.0
    for c in report["checks"].values():
        assert c["pass"] is True


def test_build_report_fails_when_any_check_fails(spec):
    bad_strip = make_strip(spec, "E1_0", scale_y=1.0)  # width error 80 cm
    strips = [bad_strip] + [make_strip(spec, lid) for lid in ("E1_1", "E2_0", "E2_1")]
    report = build_report(full_snapshot(spec, strips=strips), spec)
    assert report["pass"] is False
    assert report["checks"]["widths"]["pass"] is False
    assert report["totals"]["width_failures"] == 1


def test_report_deterministic_json(spec):
    a = build_report(full_snapshot(spec), spec)
    b = build_report(full_snapshot(spec), spec)
    text = json.dumps(a, indent=2, sort_keys=True)
    assert text == json.dumps(b, indent=2, sort_keys=True)
    assert "-0.0" not in text


def test_write_report_writes_sorted_json_roundtrip(spec, tmp_path):
    report = build_report(full_snapshot(spec), spec)
    out = tmp_path / "sub" / "road_geometry.json"
    returned = write_report(report, out)
    assert returned == report
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert json.loads(text) == report
    assert text == json.dumps(report, indent=2, sort_keys=True)
