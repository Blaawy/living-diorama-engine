"""Phase-2 lane L1: the road spec must faithfully mirror the SUMO net file.

The synthetic network is written inline as an XML string (the real SUMO net
format) and parsed by the same sumolib code path ``build_road_spec`` uses --
no netconvert is ever invoked. Tests exercise the transform authority
(ldyf.coords), attribute copying vs ``null`` for absent attributes, payload
hashing, determinism, the geometry helpers and (skipped unless present) the
real proof network.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from ldyf.coords import SumoPose, sumo_to_unreal
from ldyf.roads import (
    ROAD_SPEC_VERSION,
    build_road_spec,
    centreline_error_cm,
    check_centrelines,
    lane_polyline_unreal,
    resample_polyline,
    write_road_spec,
)
from ldyf.sumo_record import _sha256_payload

# Two edges (E1 J0->J1, E2 J1->J0), four lanes, two junctions. Only J0 carries
# a polygon shape. E2_0 has no width and E2 has no priority attribute, so the
# "absent attribute -> null" rule is exercised. E2_1 carries allow/disallow.
TINY_NET = """<?xml version="1.0" encoding="UTF-8"?>
<!-- synthetic fixture for test_roads: hand-written, never netconvert -->
<net version="1.20">
    <location netOffset="0.00,0.00" convBoundary="0.00,0.00,200.00,100.00" origBoundary="-10000000000.00,-10000000000.00,10000000000.00,10000000000.00" projParameter="!"/>
    <edge id="E1" from="J0" to="J1" priority="3">
        <lane id="E1_0" index="0" speed="13.89" length="100.00" width="3.20" shape="0.00,0.00 100.00,0.00"/>
        <lane id="E1_1" index="1" speed="8.33" length="100.00" width="3.50" shape="0.00,3.20 100.00,3.20"/>
    </edge>
    <edge id="E2" from="J1" to="J0">
        <lane id="E2_0" index="0" speed="13.89" length="100.00" shape="100.00,8.00 0.00,8.00"/>
        <lane id="E2_1" index="1" speed="13.89" length="100.00" width="3.20" allow="passenger bus" disallow="truck" shape="100.00,11.20 0.00,11.20"/>
    </edge>
    <junction id="J0" type="priority" x="0.00" y="0.00" incLanes="E2_0 E2_1" intLanes="" shape="0.00,-2.00 2.00,-2.00 2.00,14.00 0.00,14.00"/>
    <junction id="J1" type="priority" x="100.00" y="0.00" incLanes="E1_0 E1_1" intLanes=""/>
</net>
"""


def write_tiny_net(tmp_path: Path) -> Path:
    p = tmp_path / "tiny.net.xml"
    p.write_text(TINY_NET, encoding="utf-8")
    return p


def lane_by_id(spec: dict, lid: str) -> dict:
    for e in spec["edges"]:
        for ln in e["lanes"]:
            if ln["id"] == lid:
                return ln
    raise AssertionError(f"lane {lid} missing from spec")


def junction_by_id(spec: dict, jid: str) -> dict:
    for j in spec["junctions"]:
        if j["id"] == jid:
            return j
    raise AssertionError(f"junction {jid} missing from spec")


def edge_by_id(spec: dict, eid: str) -> dict:
    for e in spec["edges"]:
        if e["id"] == eid:
            return e
    raise AssertionError(f"edge {eid} missing from spec")


# --- fidelity: values copied, never invented ------------------------------

def test_widths_speeds_lengths_copied_not_invented(tmp_path):
    net = write_tiny_net(tmp_path)
    spec = build_road_spec(net)
    assert lane_by_id(spec, "E1_0")["width_cm"] == pytest.approx(320.0)
    assert lane_by_id(spec, "E1_1")["width_cm"] == pytest.approx(350.0)
    assert lane_by_id(spec, "E1_0")["speed_mps"] == pytest.approx(13.89)
    assert lane_by_id(spec, "E1_1")["speed_mps"] == pytest.approx(8.33)
    assert lane_by_id(spec, "E1_0")["length_m"] == pytest.approx(100.0)


def test_absent_attributes_are_null_not_guessed(tmp_path):
    spec = build_road_spec(write_tiny_net(tmp_path))
    # E2_0 has no width attribute in the net file
    assert lane_by_id(spec, "E2_0")["width_cm"] is None
    # E2 has no priority attribute
    assert edge_by_id(spec, "E2")["priority"] is None
    assert edge_by_id(spec, "E1")["priority"] == 3
    # lanes without allow/disallow attributes are null, not empty lists
    assert lane_by_id(spec, "E1_0")["allow"] is None
    assert lane_by_id(spec, "E1_0")["disallow"] is None
    # class tokens come from the file verbatim
    assert lane_by_id(spec, "E2_1")["allow"] == ["passenger", "bus"]
    assert lane_by_id(spec, "E2_1")["disallow"] == ["truck"]


def test_edges_and_lanes_sorted_by_id_and_function_tagged(tmp_path):
    spec = build_road_spec(write_tiny_net(tmp_path))
    assert [e["id"] for e in spec["edges"]] == ["E1", "E2"]
    assert [l["id"] for l in edge_by_id(spec, "E1")["lanes"]] == ["E1_0", "E1_1"]
    assert all(e["function"] == "normal" for e in spec["edges"])
    assert edge_by_id(spec, "E1")["from_junction"] == "J0"
    assert edge_by_id(spec, "E1")["to_junction"] == "J1"


def test_transform_matches_coords_authority_for_a_vertex(tmp_path):
    """One vertex: the spec polyline equals what sumo_to_unreal alone says."""
    spec = build_road_spec(write_tiny_net(tmp_path))
    poly = lane_by_id(spec, "E1_0")["polyline"]
    u = sumo_to_unreal(SumoPose(x=100.0, y=0.0, z=0.0, angle=0.0))
    assert poly[-1]["x"] == pytest.approx(u.x, abs=1e-6)
    assert poly[-1]["y"] == pytest.approx(u.y, abs=1e-6)
    assert poly[-1]["z"] == pytest.approx(u.z, abs=1e-6)
    # every spec polyline point is finite and carries x, y, z
    for p in poly:
        assert set(p) == {"x", "y", "z"}
        assert all(math.isfinite(p[k]) for k in ("x", "y", "z"))


def test_junction_positions_and_polygon_are_transformed(tmp_path):
    spec = build_road_spec(write_tiny_net(tmp_path))
    j1 = junction_by_id(spec, "J1")
    u = sumo_to_unreal(SumoPose(x=100.0, y=0.0, z=0.0, angle=0.0))
    assert j1["position"]["x"] == pytest.approx(u.x, abs=1e-6)
    assert j1["position"]["y"] == pytest.approx(u.y, abs=1e-6)
    # only J0 has a polygon shape in the file
    j0 = junction_by_id(spec, "J0")
    assert j0["polygon"] == lane_polyline_unreal(
        [(0.0, -2.0), (2.0, -2.0), (2.0, 14.0), (0.0, 14.0)]
    )
    assert len(j0["polygon"]) == 4
    assert junction_by_id(spec, "J1")["polygon"] is None
    assert j0["type"] == "priority"


def test_incoming_edge_ids_are_sorted_and_correct(tmp_path):
    spec = build_road_spec(write_tiny_net(tmp_path))
    assert junction_by_id(spec, "J0")["incoming_edge_ids"] == ["E2"]
    assert junction_by_id(spec, "J1")["incoming_edge_ids"] == ["E1"]


def test_counts_and_schema_header(tmp_path):
    spec = build_road_spec(write_tiny_net(tmp_path))
    assert spec["schema_version"] == ROAD_SPEC_VERSION == "road_spec_v1"
    assert spec["units"] == {"linear": "centimetres", "angular": "degrees"}
    assert spec["source"]["transform_authority"] == "ldyf.coords"
    assert spec["counts"] == {
        "edges": 2, "lanes": 4, "junctions": 2, "polyline_points": 8,
    }


def test_payload_sha256_present_and_matches_record_helper(tmp_path):
    net = write_tiny_net(tmp_path)
    spec = build_road_spec(net)
    assert spec["source"]["net_file"] == "tiny.net.xml"
    assert spec["source"]["net_payload_sha256"] == _sha256_payload(net)
    assert len(spec["source"]["net_payload_sha256"]) == 64


# --- determinism and write path -------------------------------------------

def test_build_twice_is_byte_identical(tmp_path):
    net = write_tiny_net(tmp_path)
    a = json.dumps(build_road_spec(net), indent=2, sort_keys=True)
    b = json.dumps(build_road_spec(net), indent=2, sort_keys=True)
    assert a == b
    assert "-0.0" not in a  # no negative-zero byte drift in the JSON


def test_write_road_spec_writes_json_and_returns_spec(tmp_path):
    net = write_tiny_net(tmp_path)
    out = tmp_path / "spec" / "road_spec.json"
    returned = write_road_spec(net, out)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert json.loads(text) == returned
    assert text == json.dumps(returned, indent=2, sort_keys=True)


# --- resample / centreline helpers -----------------------------------------

def test_resample_keeps_endpoints_and_step_spacing(tmp_path):
    pts = [{"x": 0.0, "y": 0.0, "z": 0.0}, {"x": 1000.0, "y": 0.0, "z": 0.0}]
    got = resample_polyline(pts, 100.0)
    assert got[0] == pts[0]
    assert got[-1] == pts[-1]
    assert len(got) == 11
    for a, b in zip(got, got[1:]):
        d = math.hypot(b["x"] - a["x"], b["y"] - a["y"])
        assert abs(d - 100.0) <= 1.0  # within 1 % of step_cm


def test_resample_keeps_endpoints_on_multiple_segments(tmp_path):
    pts = [
        {"x": 0.0, "y": 0.0, "z": 0.0},
        {"x": 500.0, "y": 0.0, "z": 0.0},
        {"x": 500.0, "y": 500.0, "z": 0.0},
    ]
    got = resample_polyline(pts, 100.0)
    assert got[0] == pts[0]
    assert got[-1] == pts[-1]
    assert len(got) == 11  # 0..1000 cm at 100 cm steps, no duplicates
    ds = [math.hypot(b["x"] - a["x"], b["y"] - a["y"]) for a, b in zip(got, got[1:])]
    assert all(abs(d - 100.0) <= 1.0 for d in ds)


def test_resample_short_polyline_keeps_only_endpoints(tmp_path):
    pts = [{"x": 0.0, "y": 0.0, "z": 0.0}, {"x": 30.0, "y": 0.0, "z": 0.0}]
    got = resample_polyline(pts, 100.0)
    assert got == pts


def test_centreline_error_is_exact_on_a_4cm_offset(tmp_path):
    spec_poly = [{"x": 0.0, "y": 0.0, "z": 0.0}, {"x": 1000.0, "y": 0.0, "z": 0.0}]
    measured = [{"x": 500.0, "y": 4.0, "z": 0.0}]
    err = centreline_error_cm(spec_poly, measured)
    assert err["n"] == 1
    assert err["max_cm"] == pytest.approx(4.0)
    assert err["mean_cm"] == pytest.approx(4.0)
    assert err["worst_index"] == 0


def test_centreline_error_segment_projection_and_worst_index(tmp_path):
    spec_poly = [{"x": 0.0, "y": 0.0, "z": 0.0}, {"x": 1000.0, "y": 0.0, "z": 0.0}]
    # one point right on the line, one off it -> mean < max, index points at off
    measured = [{"x": 100.0, "y": 0.0, "z": 0.0}, {"x": 900.0, "y": 6.0, "z": 0.0}]
    err = centreline_error_cm(spec_poly, measured)
    assert err["max_cm"] == pytest.approx(6.0)
    assert err["worst_index"] == 1
    assert err["mean_cm"] == pytest.approx(3.0)


def test_centreline_error_clamps_to_segment_endpoints(tmp_path):
    spec_poly = [{"x": 0.0, "y": 0.0, "z": 0.0}, {"x": 100.0, "y": 0.0, "z": 0.0}]
    # measured beyond the far end projects past the segment, so the distance is
    # measured to the clamped endpoint (100,0): hypot(400-100, 300-0) = 300*sqrt(2)
    # ~= 424.264. (500.0 would be the distance to the *near* endpoint (0,0),
    # which is not the closest point on the segment.)
    measured = [{"x": 400.0, "y": 300.0, "z": 0.0}]
    err = centreline_error_cm(spec_poly, measured)
    assert err["max_cm"] == pytest.approx(math.hypot(300.0, 300.0))


def test_check_centrelines_passes_at_5cm_and_fails_at_3cm(tmp_path):
    spec = build_road_spec(write_tiny_net(tmp_path))
    # E1_0 lies along SUMO y=0 -> Unreal y=0 cm; a point 4 cm off the line
    measured_by_lane = {"E1_0": [{"x": 500.0, "y": 4.0, "z": 0.0}]}
    ok = check_centrelines(spec, measured_by_lane, tolerance_cm=5.0)
    assert ok["lanes_checked"] == 1
    assert ok["pass"] is True
    assert ok["lanes_failed"] == []
    assert ok["worst_cm"] == pytest.approx(4.0)
    bad = check_centrelines(spec, measured_by_lane, tolerance_cm=3.0)
    assert bad["pass"] is False
    assert bad["lanes_failed"] == ["E1_0"]
    assert bad["worst_cm"] == pytest.approx(4.0)


def test_check_centrelines_unknown_lane_raises(tmp_path):
    spec = build_road_spec(write_tiny_net(tmp_path))
    with pytest.raises(KeyError):
        check_centrelines(spec, {"NO_SUCH_LANE": [{"x": 0.0, "y": 0.0, "z": 0.0}]})


# --- real proof network (skipped when absent) ------------------------------

def _find_proof_dir() -> Path:
    """Locate the proof network: LDYF_PROOF_DIR, MASTER layout, dev repo."""
    import os

    candidates = []
    env = os.environ.get("LDYF_PROOF_DIR")
    if env:
        candidates.append(Path(env))
    here = Path(__file__).resolve()
    candidates.append(here.parents[3] / "evidence" / "simulation")
    candidates.append(
        Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
        / "PHASE_01" / "proof" / "sumo"
    )
    for c in candidates:
        if (c / "grid.net.xml").exists():
            return c
    return candidates[-1]


PROOF = _find_proof_dir()
NET = PROOF / "grid.net.xml"
needs_net = pytest.mark.skipif(not NET.exists(), reason="proof network not present")


@needs_net
def test_real_network_spec_counts_positive_and_polylines_sane():
    spec = build_road_spec(NET)
    c = spec["counts"]
    assert c["edges"] > 0
    assert c["lanes"] > 0
    assert c["junctions"] > 0
    assert c["polyline_points"] > 0
    seen_edges = []
    for e in spec["edges"]:
        seen_edges.append(e["id"])
        for ln in e["lanes"]:
            assert len(ln["polyline"]) >= 2, f"lane {ln['id']} degenerate"
            for p in ln["polyline"]:
                assert all(math.isfinite(p[k]) for k in ("x", "y", "z"))
    assert seen_edges == sorted(seen_edges)
