"""Contract tests for the Daily Life Mobility Plan V1.

Pure pytest -- no Blender. The canonical plan is derived once and then
interrogated: every claim is recomputed from what the plan SAYS, so a plan that
is internally inconsistent fails even when the code that produced it is right.

The rules under test are the ones that make a moving city an honest claim: no
new people, every walker on its own Phase 18 anchor, every route closed at a
legal speed, every wheel revolution whole, and every pair of moving things apart
on every frame of the canonical timeline.
"""

import copy
import importlib
import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "visual" / "blender" / "scripts"
CONFIG_DIR = REPO_ROOT / "visual" / "blender" / "config"
WORK_EXPORT = Path(r"C:\Users\BLaAw\Desktop\main\p19work\render_export_before.json")


def _load(name: str):
    """Import one pure visual module the same way Blender does: by sibling name."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


mp = _load("mobility_plan")
mobility_spec = _load("mobility_spec")
motion_time_spec = _load("motion_time_spec")
scene_spec = _load("scene_spec")
production_spec = _load("production_spec")
road_graph = _load("road_graph")
urban_fabric = _load("urban_fabric")
topo = _load("pedestrian_topology")
pres = _load("population_presence_plan")
vehicle_kit = _load("vehicle_kit")
pps = _load("population_presence_spec")


def _synthetic_export(master: dict) -> dict:
    """A render export built from the master scene's own districts.

    STRUCTURAL TEST DATA, never world history. The suite must prove the planning
    RULES, and it must not depend on a generated story file being present.
    """
    return {
        "format": "living_diorama_render_export",
        "schema_version": 1,
        "source": {"episode": 0},
        "world": {
            "districts": [
                {"id": district_id, "population": 100, "character": entry["character"]}
                for district_id, entry in sorted(master["districts"].items())
            ],
            "boundaries": [],
            "infrastructure": [],
        },
        "events": [],
        "memory": {},
    }


@pytest.fixture(name="built", scope="module")
def built_fixture() -> dict:
    """The canonical mobility plan and everything it was derived from."""
    master = scene_spec.load_master_scene_spec(CONFIG_DIR / "master_scene_v1.json")
    prod = production_spec.load_production_world_spec(CONFIG_DIR / "production_world_v1.json")
    presence_spec = pps.load_population_presence_spec(CONFIG_DIR / "population_presence_v1.json")
    spec = mobility_spec.load_daily_life_mobility_spec(CONFIG_DIR / "daily_life_mobility_v1.json")
    timeline = mobility_spec.resolve_mobility_timeline(
        spec, motion_time_spec.load_motion_time_spec(CONFIG_DIR / "motion_time_v1.json")["timeline"]
    )
    graph = road_graph.build_road_graph(master, prod)
    fabric = urban_fabric.plan_urban_fabric(master, prod, graph)
    topology = topo.plan_pedestrian_topology(master, prod, graph, fabric, presence_spec)
    export = (
        scene_spec.load_render_export(WORK_EXPORT)
        if WORK_EXPORT.exists()
        else _synthetic_export(master)
    )
    presence = pres.plan_population_presence(export, master, presence_spec, topology)
    plan = mp.plan_daily_life_mobility(
        presence, presence_spec, spec, timeline, master, prod, graph, fabric
    )
    return {
        "plan": plan,
        "presence": presence,
        "presence_spec": presence_spec,
        "spec": spec,
        "timeline": timeline,
        "master": master,
        "production": prod,
        "graph": graph,
        "fabric": fabric,
    }


# ---------------------------------------------------------------------------
# Identity and honesty
# ---------------------------------------------------------------------------


def test_the_plan_declares_itself(built: dict) -> None:
    """Format, version, and the sentence that bounds the claim."""
    plan = built["plan"]
    assert plan["format"] == mp.MOBILITY_PLAN_FORMAT
    assert plan["schema_version"] == mp.MOBILITY_PLAN_SCHEMA_VERSION
    assert plan["statement"] == mp.PRESENTATION_STATEMENT
    assert "not individual citizen schedules" in plan["statement"]


def test_the_plan_validates_against_its_own_numbers(built: dict) -> None:
    """The audit is independent of the planner and finds nothing."""
    assert mp.validate_mobility_plan(built["plan"], built["presence"], built["spec"]) == []


def test_the_plan_is_deterministic(built: dict) -> None:
    """The same world and the same specs always produce the same plan."""
    again = mp.plan_daily_life_mobility(
        built["presence"],
        built["presence_spec"],
        built["spec"],
        built["timeline"],
        built["master"],
        built["production"],
        built["graph"],
        built["fabric"],
    )
    assert mp.mobility_plan_hash(again) == mp.mobility_plan_hash(built["plan"])


def test_the_plan_hash_is_stable_under_key_order(built: dict) -> None:
    """A plan is its values, not the order they were written in."""
    shuffled = copy.deepcopy(built["plan"])
    shuffled["vehicles"] = dict(reversed(list(shuffled["vehicles"].items())))
    assert mp.mobility_plan_hash(shuffled) == mp.mobility_plan_hash(built["plan"])


@pytest.mark.skipif(
    not WORK_EXPORT.exists(),
    reason="the canonical world export is absent on this machine; the structural "
    "rules are proven against the synthetic export instead, and the accepted "
    "figures can only be pinned against the world that produced them",
)
def test_the_canonical_world_pins_its_own_numbers(built: dict) -> None:
    """Eighty proxies, twenty-four walking, fourteen driving -- exactly.

    The relational tests prove the RULES; this pins the OUTCOME. The stored
    gate plans were verified field-identical to a fresh derivation of these
    numbers, so a change here is not a tuning knob drifting -- it is the
    frozen evidence moving, and it must be argued for, not slid past.
    """
    plan = built["plan"]
    summary = plan["summary"]
    assert summary["total_population_proxies"] == 80
    assert summary["moving_pedestrians"] == 24
    assert summary["stationary_pedestrians"] == 56
    assert summary["moving_vehicles"] == 14
    assert summary["total_moving_root_objects"] == 38
    timeline = plan["timeline"]
    assert timeline["start_frame"] == 1
    assert timeline["end_frame"] == 193
    assert timeline["frame_span"] == 192
    assert timeline["collision_frame_stride"] == 1
    assert plan["collision"]["frames_sampled"] == 193


# ---------------------------------------------------------------------------
# Pedestrians
# ---------------------------------------------------------------------------


def test_the_plan_creates_nobody(built: dict) -> None:
    """Every walker is an existing Phase 18 proxy, and the count is unchanged."""
    plan, presence = built["plan"], built["presence"]
    known = {proxy["slot"] for proxy in presence["proxies"]}
    assert set(plan["pedestrians"]["moving_slots"]) <= known
    assert plan["summary"]["total_population_proxies"] == len(known)
    assert plan["summary"]["moving_pedestrians"] + plan["summary"]["stationary_pedestrians"] == len(
        known
    )


def test_the_motion_counts_are_named_precisely(built: dict) -> None:
    """A mover count is not a number this project may be vague about."""
    summary = built["plan"]["summary"]
    assert summary["total_visible_population_and_vehicles"] == (
        summary["total_population_proxies"] + summary["moving_vehicles"]
    )
    assert summary["total_moving_root_objects"] == (
        summary["moving_pedestrians"] + summary["moving_vehicles"]
    )
    assert summary["total_moving_root_objects"] < summary["total_visible_population_and_vehicles"]


def test_every_walker_starts_and_ends_on_its_own_anchor(built: dict) -> None:
    """A route goes nowhere, on purpose."""
    plan, timeline = built["plan"], built["timeline"]
    tolerance = built["spec"]["pedestrians"]["route"]["anchor_tolerance"]
    for walker in plan["pedestrians"]["walkers"]:
        points = [tuple(point) for point in walker["points"]]
        assert math.dist(points[0], points[-1]) < 1.0e-6
        anchor = walker["anchor"]
        assert math.hypot(points[0][0] - anchor["x"], points[0][1] - anchor["y"]) <= tolerance
        stations = mp.loop_stations(points)
        # The distance authority here must be the published polyline itself:
        # walker["route_length"] is separately rounded metadata (its agreement
        # with the geometry has its own test), and on another libm the two
        # roundings can disagree by just over the closure tolerance.
        published_length = stations[-1]["s"]
        start = mp.sample_loop(stations, 0.0)
        end = mp.sample_loop(
            stations,
            mp.frame_distance(timeline["end_frame"], timeline, published_length, walker["cycles"]),
        )
        for axis in ("x", "y", "z", "heading"):
            # A micrometre. The route's points are published rounded to six
            # decimals and the arc-length walk accumulates over ninety-odd
            # segments, so the endpoints agree to about a hundredth of a
            # micrometre rather than to the last bit -- which is closure by any
            # standard a render could notice.
            assert start[axis] == pytest.approx(end[axis], abs=1.0e-6)


def test_every_route_is_exactly_as_long_as_its_speed_demands(built: dict) -> None:
    """The loop contract, checked per walker."""
    timeline = built["timeline"]
    for walker in built["plan"]["pedestrians"]["walkers"]:
        wanted = mobility_spec.pedestrian_route_length(walker["speed"], timeline) * walker["cycles"]
        assert walker["route_length"] == pytest.approx(wanted, abs=1.0e-3)


def test_every_excursion_sits_inside_the_declared_bounds(built: dict) -> None:
    """Route length is spec-owned, and the plan is held to it."""
    route = built["spec"]["pedestrians"]["route"]
    for walker in built["plan"]["pedestrians"]["walkers"]:
        if walker["route_family"] == "full_ring":
            continue
        assert route["excursion_min"] <= walker["excursion"] <= route["excursion_max"]


def test_every_gait_matches_its_travel(built: dict) -> None:
    """``stride = 4 L sin(swing)`` on every walker in the city."""
    for walker in built["plan"]["pedestrians"]["walkers"]:
        gait = walker["gait"]
        reach = 4.0 * gait["leg_length"] * math.sin(gait["leg_swing"])
        assert reach == pytest.approx(gait["effective_stride"], abs=1.0e-4)
        assert gait["effective_stride"] * gait["cycles"] == pytest.approx(
            walker["route_length"], abs=1.0e-3
        )


def test_the_moving_fraction_is_honoured(built: dict) -> None:
    """Twenty-four of eighty walk; the rest keep standing."""
    plan, spec = built["plan"], built["spec"]
    wanted = int(
        math.floor(
            plan["summary"]["total_population_proxies"] * spec["pedestrians"]["moving_fraction"]
            + 0.5
        )
    )
    assert plan["pedestrians"]["moving"] == min(wanted, spec["pedestrians"]["max_moving"])


def test_every_refusal_explains_itself(built: dict) -> None:
    """A slot that could not walk says why, so the ceiling is arguable."""
    for slot, reason in built["plan"]["pedestrians"]["refused"].items():
        assert reason.strip(), slot


def test_a_pool_that_exhausts_short_is_refused(
    built: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The crowd is the declared size or the plan does not exist.

    Every route request is made to fail, so the pool exhausts at zero accepted
    walkers. The planner must refuse -- naming the count it wanted, the count
    it achieved, and the recorded reasons -- exactly as the vehicle side
    refuses a shortfall. A quietly smaller crowd would ship a city less alive
    than the spec declares and nothing downstream would ever know.
    """
    wanted = built["plan"]["pedestrians"]["requested_moving"]

    def refuse(*_args: object, **_kwargs: object) -> dict:
        raise mp.MobilityPlanError("the ground under this slot refuses every candidate")

    monkeypatch.setattr(mp, "_walker_route", refuse)
    with pytest.raises(mp.MobilityPlanError) as caught:
        mp.plan_pedestrian_mobility(
            built["presence"],
            built["spec"],
            built["timeline"],
            built["master"],
            built["production"],
            built["presence_spec"],
            built["graph"],
            built["fabric"],
        )
    message = str(caught.value)
    assert f"asks {wanted}" in message
    assert "exhausted at 0" in message
    assert "refuses every candidate" in message


def test_a_quietly_smaller_crowd_is_caught_by_the_validator(built: dict) -> None:
    """A plan that walks fewer proxies than the fraction derives is refused.

    One walker is removed and every bookkeeping field is adjusted to agree, so
    the partition checks all pass and only the derived-want comparison can
    catch the shortfall -- which is the check under test.
    """
    plan = copy.deepcopy(built["plan"])
    pedestrians = plan["pedestrians"]
    dropped = pedestrians["walkers"].pop()
    pedestrians["moving"] -= 1
    pedestrians["stationary"] += 1
    pedestrians["moving_slots"] = [
        slot for slot in pedestrians["moving_slots"] if slot != dropped["slot"]
    ]
    pedestrians["stationary_slots"] = sorted([*pedestrians["stationary_slots"], dropped["slot"]])
    errors = mp.validate_mobility_plan(plan, built["presence"], built["spec"])
    assert any("declared fraction derives" in error for error in errors)


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------


def test_the_canonical_vehicle_target_is_met(built: dict) -> None:
    """Fourteen, exactly, and never silently fewer."""
    vehicles = built["plan"]["vehicles"]
    assert vehicles["count"] == vehicles["target_count"] == 14
    assert vehicles["capacity"] >= vehicles["count"]


def test_route_slots_are_a_stable_prefix(built: dict) -> None:
    """Raising the count extends the traffic; it never reshuffles it."""
    slots = built["plan"]["vehicles"]["vehicles"]
    assert [entry["slot"] for entry in slots] == [
        f"vehicle_slot_{index:03d}" for index in range(1, len(slots) + 1)
    ]


def test_traffic_is_spread_across_every_selected_route(built: dict) -> None:
    """The slot order interleaves circuits, so a prefix spreads across the city."""
    used = {entry["circuit"] for entry in built["plan"]["vehicles"]["vehicles"]}
    assert used == {entry["circuit"] for entry in built["plan"]["vehicles"]["circuits"]}


def test_every_vehicle_keeps_its_slot_pitch(built: dict) -> None:
    """Any subset of the slots stays at least a pitch apart along its circuit."""
    plan, spec = built["plan"], built["spec"]
    lengths = {entry["circuit"]: entry["length"] for entry in plan["vehicles"]["circuits"]}
    by_circuit: dict[str, list[float]] = {}
    for vehicle in plan["vehicles"]["vehicles"]:
        by_circuit.setdefault(vehicle["circuit"], []).append(vehicle["phase"])
    for circuit, phases in sorted(by_circuit.items()):
        ordered = sorted(phases)
        for first, second in zip(ordered, ordered[1:], strict=False):
            assert (second - first) * lengths[circuit] >= spec["vehicles"]["slot_pitch"] - 1.0e-6


def test_every_wheel_closes_on_whole_revolutions(built: dict) -> None:
    """The loop contract for wheels, and the rolling radius that makes it hold."""
    tolerance = built["spec"]["vehicles"]["rolling_radius_tolerance"]
    drifts = []
    for vehicle in built["plan"]["vehicles"]["vehicles"]:
        assert float(vehicle["wheel_turns"]).is_integer()
        rolled = 2.0 * math.pi * vehicle["rolling_radius"] * vehicle["wheel_turns"]
        assert rolled == pytest.approx(vehicle["route_length"] * vehicle["cycles"], abs=1.0e-6)
        drift = abs(vehicle["rolling_radius"] / vehicle["wheel_radius"] - 1.0)
        drifts.append(drift)
        assert drift <= tolerance
    assert max(drifts) < 0.02


def test_every_vehicle_matches_the_kit_it_claims(built: dict) -> None:
    """A plan cannot describe a vehicle the kit does not build."""
    for vehicle in built["plan"]["vehicles"]["vehicles"]:
        size = vehicle_kit.vehicle_dimensions(vehicle["archetype"])
        assert vehicle["length"] == pytest.approx(size["length"])
        assert vehicle["width"] == pytest.approx(size["width"])
        assert vehicle["paint"] in vehicle_kit.PAINT_FAMILIES


def test_the_traffic_uses_more_than_one_archetype(built: dict) -> None:
    """Traffic made of one repeated car is a conveyor belt."""
    assert len(built["plan"]["vehicles"]["by_archetype"]) >= 3


def test_the_vehicle_layer_fits_its_budget(built: dict) -> None:
    """Performance is a contract."""
    budget = built["spec"]["vehicles"]["budget"]
    assert built["plan"]["vehicles"]["layer_triangles"] <= budget["layer_triangles"]


def test_the_coverage_report_is_carried_by_the_plan(built: dict) -> None:
    """Geographic spread is measured in the plan, not only in a report."""
    coverage = built["plan"]["vehicles"]["coverage"]
    assert coverage["segments_carrying_traffic"]
    assert coverage["regions_with_traffic"]
    assert built["plan"]["summary"]["road_segment_coverage"] == coverage["segment_coverage"]


# ---------------------------------------------------------------------------
# Routing invariance
# ---------------------------------------------------------------------------


def test_vehicle_visual_changes_never_move_a_route(
    built: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The architecture's central claim, held as a regression test.

    The planners read the RESERVED envelope, never the sculpture, so reshaping
    a car's visible geometry must never move the city's traffic. The kit's two
    visual outputs the planner touches at plan time -- the measured bounds
    inside :func:`vehicle_kit.vehicle_dimensions` and the triangle counts --
    are perturbed at exactly those seams, the whole plan is rebuilt, and every
    route-bearing field must come out identical. The triangle accounting is
    proven to MOVE, so the patch is known to bite; :data:`PAINT_FAMILIES` is
    deliberately left alone, because paint is plan content and reordering it
    would legitimately repaint the traffic.
    """
    real_bounds = vehicle_kit.measured_visual_bounds
    real_triangles = vehicle_kit.vehicle_triangles

    def inflated_bounds(archetype: str) -> dict:
        return {axis: value + 1.0 for axis, value in real_bounds(archetype).items()}

    monkeypatch.setattr(vehicle_kit, "measured_visual_bounds", inflated_bounds)
    monkeypatch.setattr(vehicle_kit, "vehicle_triangles", lambda name: real_triangles(name) - 16)
    reshaped = mp.plan_daily_life_mobility(
        built["presence"],
        built["presence_spec"],
        built["spec"],
        built["timeline"],
        built["master"],
        built["production"],
        built["graph"],
        built["fabric"],
    )
    plan = built["plan"]

    # The patch bit: the triangle accounting moved with the visual change.
    assert reshaped["vehicles"]["layer_triangles"] != plan["vehicles"]["layer_triangles"]
    assert reshaped["vehicles"]["triangles"] != plan["vehicles"]["triangles"]

    # The routes did not. Every route-bearing vehicle field, both circuits'
    # polylines, every pedestrian route, the timeline, and the collision proof
    # the routes imply are all bit-identical to the canonical plan.
    route_fields = (
        "slot",
        "circuit",
        "circuit_index",
        "phase",
        "speed",
        "route_length",
        "cycles",
        "length",
        "width",
        "height",
        "wheel_radius",
        "rolling_radius",
        "wheel_turns",
        "archetype",
    )
    for before, after in zip(
        plan["vehicles"]["vehicles"], reshaped["vehicles"]["vehicles"], strict=True
    ):
        for field in route_fields:
            assert after[field] == before[field], (before["slot"], field)
    assert reshaped["vehicles"]["circuits"] == plan["vehicles"]["circuits"]
    assert reshaped["vehicles"]["count"] == plan["vehicles"]["count"]
    assert reshaped["vehicles"]["capacity"] == plan["vehicles"]["capacity"]
    assert reshaped["pedestrians"] == plan["pedestrians"]
    assert reshaped["timeline"] == plan["timeline"]
    assert reshaped["collision"] == plan["collision"]


# ---------------------------------------------------------------------------
# Space and time
# ---------------------------------------------------------------------------


def test_the_collision_proof_covers_every_frame(built: dict) -> None:
    """Not the start, not a sample -- every frame of the canonical timeline."""
    plan, timeline = built["plan"], built["timeline"]
    assert plan["collision"]["frames_sampled"] == timeline["frame_span"] + 1
    assert plan["collision"]["frame_stride"] == 1
    assert plan["collision"]["safe"] is True
    assert not plan["collision"]["failures"]


def test_every_pair_class_is_checked_and_clear(built: dict) -> None:
    """All four dynamic pair classes clear their required margins."""
    collision = built["plan"]["collision"]
    expected = {
        "walker_walker",
        "walker_stationary",
        "vehicle_vehicle",
        "walker_vehicle",
    }
    assert set(collision["required"]) == expected
    assert set(collision["closest"]) == expected
    for key in sorted(expected):
        required = collision["required"][key]
        assert collision["closest"][key] is not None, key
        assert collision["closest"][key] >= required, (key, collision["closest"][key])
    assert collision["pairs_checked"]["vehicle_pedestrian"] > 0


def test_no_walker_ever_enters_a_carriageway(built: dict) -> None:
    """Structurally impossible by topology, and checked anyway."""
    validator = topo.build_presence_occupancy(
        built["master"], built["production"], built["graph"], built["fabric"]
    )
    roads = topo.street_occupancy_shapes(validator)
    radius = built["plan"]["pedestrians"]["body_radius"]
    from spatial_occupancy import circle, shape_gap  # noqa: PLC0415

    for walker in built["plan"]["pedestrians"]["walkers"]:
        for x, y, _z in walker["points"]:
            body = circle(x, y, radius)
            for shape in roads:
                assert shape_gap(body, shape) > 0.0, walker["slot"]


def test_the_collision_proof_would_actually_bite(built: dict) -> None:
    """A validator nobody has seen refuse anything proves nothing.

    Two walkers are moved onto the same route, so they occupy the same place at
    the same time. The proof must find it.
    """
    plan = copy.deepcopy(built["plan"])
    walkers = plan["pedestrians"]["walkers"]
    walkers[1] = {
        **walkers[1],
        "points": copy.deepcopy(walkers[0]["points"]),
        "route_length": walkers[0]["route_length"],
        "cycles": walkers[0]["cycles"],
    }
    report = mp.mobility_collisions(plan, built["timeline"], built["presence"], built["spec"])
    assert not report["safe"]
    assert report["failures"]


def test_a_tampered_plan_is_caught_by_the_validator(built: dict) -> None:
    """The audit recomputes rather than trusts."""
    plan = copy.deepcopy(built["plan"])
    plan["vehicles"]["vehicles"][0]["wheel_turns"] += 1
    errors = mp.validate_mobility_plan(plan, built["presence"], built["spec"])
    assert errors


def test_an_invented_walker_is_caught_by_the_validator(built: dict) -> None:
    """A plan that walked somebody Phase 18 never placed is refused."""
    plan = copy.deepcopy(built["plan"])
    plan["pedestrians"]["moving_slots"] = [*plan["pedestrians"]["moving_slots"], "ghost__slot_001"]
    errors = mp.validate_mobility_plan(plan, built["presence"], built["spec"])
    assert any("never placed" in error for error in errors)
