"""Contract tests for the Phase 19 vehicle lane network.

Pure pytest -- no Blender. The synthetic fixtures here are STRUCTURAL TEST
GEOMETRY, never world history: a two-street corner and a dead-end street exist
so the rules can be exercised at their boundaries, which the canonical city
does not happen to offer.

The rules under test are the ones that decide where a vehicle may be: a lane is
an offset of an authored carriageway or it does not exist, a carriageway that
cannot hold two lanes gets one or none, a circuit must close at a legal speed,
and two routes must be separated by geometry rather than by a schedule.
"""

import importlib
import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "visual" / "blender" / "scripts"
CONFIG_DIR = REPO_ROOT / "visual" / "blender" / "config"


def _load(name: str):
    """Import one pure visual module the same way Blender does: by sibling name."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


vln = _load("vehicle_lane_network")
vehicle_kit = _load("vehicle_kit")
mobility_spec = _load("mobility_spec")
motion_time_spec = _load("motion_time_spec")
road_graph = _load("road_graph")
scene_spec = _load("scene_spec")
production_spec = _load("production_spec")
urban_fabric = _load("urban_fabric")

HALF = vehicle_kit.widest_vehicle() / 2.0


@pytest.fixture(name="spec", scope="module")
def spec_fixture() -> dict:
    """The canonical mobility spec."""
    return mobility_spec.load_daily_life_mobility_spec(CONFIG_DIR / "daily_life_mobility_v1.json")


@pytest.fixture(name="timeline", scope="module")
def timeline_fixture(spec: dict) -> dict:
    """The canonical mobility timeline, read from the locked Phase 17 spec."""
    motion = motion_time_spec.load_motion_time_spec(CONFIG_DIR / "motion_time_v1.json")
    return mobility_spec.resolve_mobility_timeline(spec, motion["timeline"])


@pytest.fixture(name="world", scope="module")
def world_fixture() -> dict:
    """The canonical city, built once."""
    master = scene_spec.load_master_scene_spec(CONFIG_DIR / "master_scene_v1.json")
    prod = production_spec.load_production_world_spec(CONFIG_DIR / "production_world_v1.json")
    graph = road_graph.build_road_graph(master, prod)
    fabric = urban_fabric.plan_urban_fabric(master, prod, graph)
    return {"master": master, "production": prod, "graph": graph, "fabric": fabric}


@pytest.fixture(name="lanes", scope="module")
def lanes_fixture(world: dict, spec: dict, timeline: dict) -> dict:
    """The canonical lane network and its selected routes, computed once."""
    return vln.plan_vehicle_lanes(
        world["master"], world["graph"], world["fabric"]["ground"], spec, HALF, timeline
    )


# ---------------------------------------------------------------------------
# Lane policy
# ---------------------------------------------------------------------------


def test_a_wide_carriageway_carries_two_lanes(spec: dict) -> None:
    """Right-hand traffic puts each direction on its own side."""
    for road_class in ("arterial", "collector"):
        policy = vln.lane_policy(road_class, spec, HALF)
        assert policy["policy"] == "dual"
        assert policy["offset"] == pytest.approx(vln.carriageway_half_width(road_class) / 2.0)


def test_a_narrow_carriageway_refuses_the_two_lane_split(spec: dict) -> None:
    """A 3.4m street cannot hold two lanes of a 2m vehicle, and says so."""
    for road_class in ("local", "service"):
        policy = vln.lane_policy(road_class, spec, HALF)
        assert policy["policy"] == "single"
        assert policy["offset"] == 0.0
        assert "refused" in policy["reason"]


def test_a_carriageway_too_narrow_for_any_lane_is_refused(spec: dict) -> None:
    """A vehicle wider than the street gets no lane at all."""
    policy = vln.lane_policy("local", spec, 3.0)
    assert policy["policy"] == "refused"


def test_an_unknown_road_class_is_refused() -> None:
    """The road graph decides what a street is."""
    with pytest.raises(vln.VehicleLaneError):
        vln.carriageway_half_width("motorway")


def test_a_single_lane_run_is_claimed_once_whichever_way_it_is_driven() -> None:
    """One centred lane cannot be shared, so its claim ignores direction."""
    entry = {"run": "lane#0", "policy": "single", "offset": 0.0}
    assert vln.lane_key(entry, True) == vln.lane_key(entry, False)


def test_a_dual_run_offers_two_independent_lanes() -> None:
    """Two circuits may share a street in opposite directions -- ordinary traffic."""
    entry = {"run": "lane#0", "policy": "dual", "offset": 1.3}
    assert vln.lane_key(entry, True) != vln.lane_key(entry, False)


def test_the_driving_side_is_a_declared_policy(spec: dict) -> None:
    """The convention is stated, not assumed by the offset arithmetic."""
    assert vln.driving_sign(spec) == 1.0
    assert vln.driving_sign({"vehicles": {"driving_side": "left"}}) == -1.0


# ---------------------------------------------------------------------------
# Lane geometry
# ---------------------------------------------------------------------------


def test_an_offset_lane_holds_its_distance_along_a_bend() -> None:
    """A mitred offset must not pinch at a corner, or the lane leaves its lane.

    Measured on the STRAIGHT stations. The mitre vertex itself sits further from
    the corner than a plain normal offset would -- that is the whole point of a
    mitre -- so it is checked separately, by the distance it holds from both
    legs rather than by the distance it sits from the vertex.
    """
    path = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    offset = vln.offset_polyline(path, 1.5)
    assert vln.distance_to_polyline(offset[0][0], offset[0][1], path) == pytest.approx(1.5)
    assert vln.distance_to_polyline(offset[-1][0], offset[-1][1], path) == pytest.approx(1.5)
    corner = offset[1]
    # Against each leg's INFINITE line. A finite leg ends at the corner vertex,
    # so its nearest point to a mitred offset is that vertex -- measuring there
    # would be measuring the mitre's own reach rather than the lane's offset.
    for a, b in ((path[0], path[1]), (path[1], path[2])):
        dx, dy = b[0] - a[0], b[1] - a[1]
        span = math.hypot(dx, dy)
        away = abs((corner[0] - a[0]) * dy - (corner[1] - a[1]) * dx) / span
        assert away == pytest.approx(1.5, abs=0.02)
    assert math.dist(corner, path[1]) > 1.5


def test_a_lane_offsets_to_the_right_of_travel() -> None:
    """Right-hand traffic is a sign convention, and the sign is checked."""
    lane = vln.offset_polyline([(0.0, 0.0), (10.0, 0.0)], 2.0)
    assert all(point[1] < 0.0 for point in lane)


def test_reversing_a_run_puts_its_lane_on_the_other_side(spec: dict) -> None:
    """The two directions of one street are two different lanes."""
    entry = {
        "run": "r#0",
        "policy": "dual",
        "offset": 1.3,
        "path": [(0.0, 0.0), (20.0, 0.0)],
    }
    forward = vln.run_lane(entry, True, spec)
    reverse = vln.run_lane(entry, False, spec)
    assert forward[0][1] < 0.0
    assert reverse[0][1] > 0.0


def test_resampling_preserves_every_component() -> None:
    """A lifted lane carries a height, and a resampler must not drop it."""
    line = [(0.0, 0.0, 0.9), (10.0, 0.0, 1.0)]
    resampled = vln.resample_polyline(line, 1.0)
    assert all(len(point) == 3 for point in resampled)
    assert resampled[-1] == (10.0, 0.0, 1.0)
    assert resampled[5][2] == pytest.approx(0.95, abs=0.02)


def test_length_is_measured_in_the_ground_plane() -> None:
    """Counting a road's ramp would put speed and wheel rotation out of step."""
    assert vln.polyline_length([(0.0, 0.0, 0.0), (3.0, 4.0, 9.0)]) == pytest.approx(5.0)


def test_lane_stations_publish_the_lanes_own_tangent() -> None:
    """A vehicle is oriented by the road, never by anything it decided."""
    stations = vln.lane_stations([(0.0, 0.0, 1.0), (10.0, 0.0, 1.0), (0.0, 0.0, 1.0)], 1.0)
    assert stations[0]["heading"] == pytest.approx(0.0)
    assert abs(stations[-3]["heading"]) == pytest.approx(math.pi, abs=0.01)


def test_a_turnaround_reverses_the_heading_without_a_pivot() -> None:
    """A half circle at a real radius, not a lane-width spin."""
    turn = vln.turnaround_lane((0.0, 0.0), (1.0, 0.0), 1.3, 3.0, 0.4)
    assert len(turn) > 8
    start = math.atan2(turn[1][1] - turn[0][1], turn[1][0] - turn[0][0])
    end = math.atan2(turn[-1][1] - turn[-2][1], turn[-1][0] - turn[-2][0])
    swept = abs(math.atan2(math.sin(end - start), math.cos(end - start)))
    assert swept > math.radians(150.0)
    for a, b in zip(turn, turn[1:], strict=False):
        assert math.dist(a, b) < 1.0


def test_a_turnaround_finishes_wider_than_the_lane_it_rejoins() -> None:
    """Twice the radius of displacement is arithmetic, and the caller must merge."""
    offset, radius = 1.3, 3.0
    arriving = (1.0, 0.0)
    right = (arriving[1], -arriving[0])
    turn = vln.turnaround_lane((0.0, 0.0), arriving, offset, radius, 0.4)
    along_right = turn[-1][0] * right[0] + turn[-1][1] * right[1]
    assert along_right == pytest.approx(offset - 2.0 * radius, abs=1.0e-6)


def test_the_corner_radius_ladder_runs_from_target_to_floor(spec: dict) -> None:
    """A wide turn is tried first; a tighter one is the fallback."""
    ladder = vln.corner_radius_ladder(spec)
    assert ladder[0] == spec["vehicles"]["lane"]["corner_radius"]
    assert ladder[-1] == pytest.approx(spec["vehicles"]["lane"]["corner_radius_min"])
    assert list(ladder) == sorted(ladder, reverse=True)


# ---------------------------------------------------------------------------
# The canonical network
# ---------------------------------------------------------------------------


def test_the_network_offers_only_paved_ring_runs(lanes: dict) -> None:
    """A buried ring sector is not a road, and driving it would be underground."""
    refused = lanes["network"]["refused"]
    assert refused
    assert all("buried" in reason for reason in refused.values())


def test_every_offered_run_belongs_to_a_real_street(lanes: dict, world: dict) -> None:
    """A lane is an offset of an authored carriageway or it does not exist."""
    for entry in lanes["network"]["runs"].values():
        assert entry["segment"] in world["graph"]["segments"]


def test_every_selected_circuit_closes(lanes: dict) -> None:
    """The loop contract, checked on the geometry rather than on a claim."""
    for circuit in lanes["circuits"]:
        points = circuit["line"]
        assert math.dist(points[0][:2], points[-1][:2]) < 1.0e-6


def test_every_selected_circuit_can_be_driven_at_a_legal_speed(
    lanes: dict, spec: dict, timeline: dict
) -> None:
    """A circuit outside the band is refused, never raced or left half-driven."""
    low, high = mobility_spec.vehicle_route_length_bounds(spec, timeline)
    band = spec["vehicles"]["speed"]
    for circuit in lanes["circuits"]:
        assert low <= circuit["length"] <= high
        assert band["min"] <= circuit["speed"] <= band["max"]
        assert circuit["speed"] == pytest.approx(
            circuit["length"] / timeline["vehicle_cycle_seconds"]
        )


def test_every_selected_lane_stays_on_the_carriageway(lanes: dict, world: dict, spec: dict) -> None:
    """Re-proved from the road graph, not taken from the planner."""
    envelope = vln.drivable_envelope(world["graph"])
    step = spec["vehicles"]["lane"]["sample_step"]
    for circuit in lanes["circuits"]:
        for station in vln.lane_stations(circuit["line"], step):
            assert vln.on_carriageway(station["x"], station["y"], envelope), circuit["circuit"]


def test_the_carriageway_test_would_actually_bite(world: dict) -> None:
    """A guard nobody has seen refuse anything is a guard nobody has tested."""
    envelope = vln.drivable_envelope(world["graph"])
    assert not vln.on_carriageway(0.0, 200.0, envelope)


def test_selected_circuits_never_share_a_lane(lanes: dict) -> None:
    """Lane disjointness is what stops two routes meeting head-on in one lane."""
    seen: set = set()
    for circuit in lanes["circuits"]:
        keys = {tuple(key) for key in circuit["claims"]}
        assert not keys & seen, circuit["circuit"]
        seen |= keys


def test_selected_circuits_are_separated_by_geometry_not_timing(lanes: dict, spec: dict) -> None:
    """Two routes must never bring the largest vehicle on each within clearance."""
    floor = spec["vehicles"]["body_clearance"]
    step = spec["vehicles"]["lane"]["sample_step"]
    longest_half = vehicle_kit.longest_vehicle() / 2.0
    circuits = lanes["circuits"]
    for index, first in enumerate(circuits):
        for second in circuits[index + 1 :]:
            gap = vln.worst_body_gap(
                vln.lane_stations(first["line"], step),
                vln.lane_stations(second["line"], step),
                longest_half,
                HALF,
            )
            assert gap >= floor, (first["circuit"], second["circuit"], gap)


def test_the_network_reaches_the_canonical_vehicle_target(lanes: dict, spec: dict) -> None:
    """The canonical fourteen must actually fit at the declared pitch."""
    assert lanes["summary"]["capacity"] >= spec["vehicles"]["target_count"]


def test_every_rejected_route_says_why(lanes: dict) -> None:
    """A route that vanished without a reason is a route nobody can argue with."""
    assert lanes["rejected"]
    for key, reason in lanes["rejected"].items():
        assert reason.strip(), key


def test_the_turnaround_inventory_is_dual_lane_only(lanes: dict) -> None:
    """A single-lane street has no second lane to come back on."""
    for entry in lanes["turnarounds"]:
        assert lanes["network"]["runs"][entry["run"]]["policy"] == "dual"
        assert entry["termination"] in vln.TURNAROUND_TERMINATIONS


def test_the_coverage_summary_measures_what_traffic_reaches(lanes: dict) -> None:
    """Geographic spread is an objective, so it is reported as numbers."""
    coverage = lanes["coverage"]
    assert coverage["routes"] == len(lanes["circuits"])
    assert coverage["segments_carrying_traffic"]
    assert coverage["segments_without_traffic"]
    assert 0.0 < coverage["segment_coverage"] < 1.0
    assert coverage["traffic_extent_area"] > 0.0
    assert coverage["regions_with_traffic"]
    for entry in coverage["regions"].values():
        assert entry["offered"] >= entry["accepted"]


def test_rejected_regions_carry_their_geometric_reason(lanes: dict) -> None:
    """Saying the map cannot support it is not an answer; a fillet radius is."""
    for key in lanes["coverage"]["regions_offered_but_unusable"]:
        assert lanes["coverage"]["regions"][key]["reasons"], key


def test_the_network_is_deterministic(world: dict, spec: dict, timeline: dict, lanes: dict) -> None:
    """The same city and the same spec always produce the same routes."""
    again = vln.plan_vehicle_lanes(
        world["master"], world["graph"], world["fabric"]["ground"], spec, HALF, timeline
    )
    assert again["summary"] == lanes["summary"]
    assert [entry["line"] for entry in again["circuits"]] == [
        entry["line"] for entry in lanes["circuits"]
    ]


def test_the_road_surface_level_follows_the_street_family(world: dict) -> None:
    """A vehicle drives on the road mesh, and each family sits at its own height."""
    master = world["master"]
    production = {"segment": "orbital", "class": "arterial"}
    collector = {"segment": "cd_extension", "class": "collector"}
    avenue = {"segment": "avenue_boundary_ab", "class": "arterial"}
    spur = {"segment": "spur_boundary_cd_district_d", "class": "collector"}
    ring = {"segment": "ring_district_d", "class": "collector"}
    assert vln.road_surface_level(production, master) == pytest.approx(0.98)
    assert vln.road_surface_level(collector, master) == pytest.approx(0.972)
    assert vln.road_surface_level(avenue, master) == pytest.approx(0.98)
    assert vln.road_surface_level(spur, master) == pytest.approx(0.96)
    assert vln.road_surface_level(ring, master) == pytest.approx(
        master["districts"]["district_d"]["elevation"] + 0.61
    )


def test_an_unknown_ring_district_is_refused(world: dict) -> None:
    """A ring naming a district the world does not have has no height."""
    with pytest.raises(vln.VehicleLaneError):
        vln.road_surface_level(
            {"segment": "ring_district_z", "class": "collector"}, world["master"]
        )
