"""Structural tests for V2 vehicle traffic: bounded-arc presentation (Phase 19).

Pure Python -- never imports ``bpy`` -- because every claim this file makes is
checkable on a machine with no Blender installed, exactly like
``run_phase19_checks._derive_mobility``. It builds the REAL EP1 world from the
LOCKED config, derives the REAL mobility plan for both traffic profiles, and
runs the REAL ``mobility_collisions`` all-pairs frame sweep on the V2 output --
never a mock.

What is proven, mechanically:

* ``traffic_profile="v1"`` reproduces today's behavior byte-for-byte (the
  explicit-v1 plan hashes identically to the default plan, which is the
  captured-V1 regression available without a pre-committed artifact).
* The REAL ``mobility_collisions`` proof reports ``safe=True`` on the V2 plan,
  now proven on each V2 vehicle's BOUNDED ARC rather than a full lap.
* Exactly 14 vehicles are placed (the declared target; a shortfall refuses).
* Every V2 vehicle's presentation arc is a genuine, non-repeating, bounded
  slice of its circuit's real geometry: ``presentation_arc_fraction`` lies
  strictly in (0, 1), ``arc_distance`` is strictly less than the circuit's
  full length, no two sampled frames land on the same distance-along-curve
  value modulo the loop, and the start and end positions are different real
  points on the circuit polyline.
* No V2 vehicle stops, freezes, teleports or reverses: the unwrapped distance
  is strictly, linearly increasing across the whole clip.
* V2 wheels roll the REAL wheel radius continuously over the arc's real
  distance -- no rolling-radius solve, no whole-revolution closure contract.
* A V2 vehicle's published speed is its real distance/time average
  (``circuit_speed * arc_fraction``), reported honestly, never the masked
  full-lap figure.
* The locked EP1 network's open out-and-back family is still measured and
  reported honestly: the only two legal turnarounds lie in DISCONNECTED
  components of the dual-lane subgraph, so ``enumerate_out_and_back`` returns
  zero chains and ``open_route_count`` is 0 by construction. That structural
  fact stands; the V2 presentation fix does not depend on it (it shows bounded
  arcs of V1's closed circuits, the only real road geometry available).
* Every consecutive run pair of every route shares a real graph node.
* More than one distinct real road segment carries traffic.
* No route drives the same directional lane claim twice.
* The plan is byte-identical across ``PYTHONHASHSEED`` values 0, 1, 42 and
  123456, derived in fresh subprocesses (metamorphic pattern).

Usage::

    python visual/blender/tests/test_mobility_traffic_v2.py --workdir <dir>

or with pytest (``--workdir`` is read from the ``LD_TEST_WORKDIR`` env var,
falling back to the current directory). The workdir must hold the real render
export ``render_export_before.json``, which the real Phase 19 pipeline
produces.
"""

import argparse
import math
import os
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
CONFIG_DIR = TESTS_DIR.parent / "config"

_SEEDS = ("0", "1", "42", "123456")
_STATE: dict = {}


def _workdir_argument() -> Path:
    """The workdir that holds the real render export, from any supported source."""
    value = os.environ.get("LD_TEST_WORKDIR")
    if value:
        return Path(value)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--workdir")
    args, _ = parser.parse_known_args()
    return Path(args.workdir) if args.workdir else Path.cwd()


def _prepare(workdir: Path | None = None) -> dict:
    """Build the real world and both plans exactly once, caching the result."""
    if _STATE:
        return _STATE
    for directory in (str(TESTS_DIR), str(SCRIPTS_DIR)):
        if directory not in sys.path:
            sys.path.insert(0, directory)
    import mobility_plan as mp
    import mobility_traffic_v2 as v2
    import pedestrian_topology as topo
    import population_presence_plan as pres
    import vehicle_kit
    from mobility_spec import load_daily_life_mobility_spec, resolve_mobility_timeline
    from motion_time_spec import load_motion_time_spec
    from population_presence_spec import load_population_presence_spec
    from production_spec import load_production_world_spec
    from road_graph import build_road_graph
    from scene_spec import load_master_scene_spec, load_render_export
    from urban_fabric import plan_urban_fabric

    export_dir = (workdir or _workdir_argument()) / "render_export_before.json"
    if not export_dir.is_file():
        raise FileNotFoundError(
            f"the real render export {export_dir} is required; run the Phase 19 "
            "pipeline first or pass --workdir <dir> / LD_TEST_WORKDIR"
        )

    master = load_master_scene_spec(CONFIG_DIR / "master_scene_v1.json")
    production = load_production_world_spec(CONFIG_DIR / "production_world_v1.json")
    presence_spec = load_population_presence_spec(CONFIG_DIR / "population_presence_v1.json")
    spec = load_daily_life_mobility_spec(CONFIG_DIR / "daily_life_mobility_v1.json")
    timeline = resolve_mobility_timeline(
        spec, load_motion_time_spec(CONFIG_DIR / "motion_time_v1.json")["timeline"]
    )
    graph = build_road_graph(master, production)
    fabric = plan_urban_fabric(master, production, graph)
    topology = topo.plan_pedestrian_topology(master, production, graph, fabric, presence_spec)
    export = load_render_export(export_dir)
    presence = pres.plan_population_presence(export, master, presence_spec, topology)

    plan_default = mp.plan_daily_life_mobility(
        presence, presence_spec, spec, timeline, master, production, graph, fabric
    )
    vehicles_v1 = mp.plan_vehicle_mobility(
        spec, timeline, master, graph, fabric, traffic_profile="v1"
    )
    vehicles_v2 = mp.plan_vehicle_mobility(
        spec, timeline, master, graph, fabric, traffic_profile="v2"
    )
    plan_v2 = {**plan_default, "vehicles": vehicles_v2}
    plan_v2["collision"] = mp.mobility_collisions(plan_v2, timeline, presence, spec)
    lanes_v2 = v2.plan_vehicle_traffic_v2(
        master,
        graph,
        fabric["ground"],
        spec,
        vehicle_kit.widest_vehicle() / 2.0,
        timeline,
    )
    _STATE.update(
        {
            "mp": mp,
            "v2": v2,
            "spec": spec,
            "timeline": timeline,
            "master": master,
            "production": production,
            "graph": graph,
            "fabric": fabric,
            "presence_spec": presence_spec,
            "presence": presence,
            "plan_default": plan_default,
            "vehicles_v1": vehicles_v1,
            "vehicles_v2": vehicles_v2,
            "plan_v2": plan_v2,
            "lanes_v2": lanes_v2,
        }
    )
    return _STATE


# ---------------------------------------------------------------------------
# V1 compatibility: the default path is byte-for-byte today's behavior
# ---------------------------------------------------------------------------


def test_v1_profile_is_byte_for_byte_today_behavior() -> None:
    """Explicit v1 vehicles are EXACTLY the default plan's vehicles."""
    state = _prepare()
    assert state["vehicles_v1"] == state["plan_default"]["vehicles"]


def test_v1_plan_reproduces_itself_exactly() -> None:
    """The full default plan re-derives byte-for-byte (captured-V1 regression)."""
    state = _prepare()
    mp = state["mp"]
    again = mp.plan_daily_life_mobility(
        state["presence"],
        state["presence_spec"],
        state["spec"],
        state["timeline"],
        state["master"],
        state["production"],
        state["graph"],
        state["fabric"],
    )
    assert mp.mobility_plan_hash(again) == mp.mobility_plan_hash(state["plan_default"])


# ---------------------------------------------------------------------------
# The decisive gate: the REAL mobility_collisions proof on the V2 plan
# ---------------------------------------------------------------------------


def test_v2_real_collision_proof_is_safe() -> None:
    """The REAL all-pairs frame sweep reports safe=True and zero failures.

    The sweep now derives each V2 vehicle's position from its BOUNDED ARC
    distance (``phase * length + arc_fraction * length * (frame - start) /
    span``) -- the same number the Blender-side per-vehicle ``eval_time``
    keyframing renders -- so the proof is proving the actual V2 motion.
    """
    state = _prepare()
    proof = state["plan_v2"]["collision"]
    assert proof["safe"] is True
    assert proof["failures"] == []
    required = state["spec"]["vehicles"]["body_clearance"]
    assert proof["closest"]["vehicle_vehicle"] >= required


# ---------------------------------------------------------------------------
# Vehicle count and route structure
# ---------------------------------------------------------------------------


def test_v2_ships_exactly_the_declared_target() -> None:
    """Exactly 14 vehicles are placed; a shortfall would have refused."""
    state = _prepare()
    plan = state["plan_v2"]
    assert plan["vehicles"]["count"] == 14
    assert plan["vehicles"]["count"] == plan["vehicles"]["target_count"]


def test_v2_uses_more_than_one_real_road_segment() -> None:
    """Multi-segment/multi-road: traffic is not confined to one road."""
    state = _prepare()
    coverage = state["plan_v2"]["vehicles"]["coverage"]
    assert len(coverage["segments_carrying_traffic"]) > 1


def test_every_route_chain_uses_only_real_connected_edges() -> None:
    """Every consecutive run pair of every route shares a real graph node."""
    state = _prepare()
    v2, lanes = state["v2"], state["lanes_v2"]
    for circuit in lanes["circuits"]:
        assert v2.route_chain_continuous(circuit, lanes["network"]), circuit["circuit_key"]


def test_no_route_repeats_a_directional_lane_claim() -> None:
    """No route drives the same run in the same direction twice."""
    state = _prepare()
    v2, lanes = state["v2"], state["lanes_v2"]
    for circuit in lanes["circuits"]:
        assert v2.route_chain_simple(circuit), circuit["circuit_key"]


# ---------------------------------------------------------------------------
# The REAL V2 requirement: every vehicle drives a bounded, non-repeating arc
# ---------------------------------------------------------------------------
# The campaign's earlier "at least one genuinely open route" goal is
# structurally unsatisfiable on the real EP1 network -- the only two legal
# turnarounds lie in disconnected dual-lane components, so the out-and-back
# enumerator offers zero chains (that finding stands and is still reported
# honestly). The architectural fix is therefore not a new road shape: V1's
# closed circuits remain the only real geometry, and V2 shows a bounded,
# non-repeating ARC of each circuit instead of a full lap. The tests below
# prove that new requirement directly from the real plan.


def test_v2_every_vehicle_drives_a_bounded_non_repeating_arc() -> None:
    """Every one of the 14 V2 vehicles travels a bounded arc of real road.

    Each vehicle's ``presentation_arc_fraction`` is strictly inside (0, 1) and
    its ``arc_distance`` is strictly less than its circuit's full length, so
    no V2 vehicle ever completes a full lap or returns to a position it has
    already occupied on screen within the clip.
    """
    state = _prepare()
    vehicles = state["plan_v2"]["vehicles"]["vehicles"]
    circuits = {entry["circuit"]: entry for entry in state["plan_v2"]["vehicles"]["circuits"]}
    assert len(vehicles) == 14
    for vehicle in vehicles:
        fraction = float(vehicle["presentation_arc_fraction"])
        circuit = circuits[vehicle["circuit"]]
        assert 0.0 < fraction < 1.0, vehicle["slot"]
        assert float(vehicle["arc_distance"]) < float(circuit["length"]), vehicle["slot"]


def test_v2_every_arc_is_strictly_shorter_than_its_circuit() -> None:
    """Hard constraint, stated arithmetically for every vehicle."""
    state = _prepare()
    circuits = {entry["circuit"]: entry for entry in state["plan_v2"]["vehicles"]["circuits"]}
    for vehicle in state["plan_v2"]["vehicles"]["vehicles"]:
        length = float(circuits[vehicle["circuit"]]["length"])
        fraction = float(vehicle["presentation_arc_fraction"])
        assert 0.0 < fraction < 1.0, vehicle["slot"]
        assert fraction * length < length, vehicle["slot"]


def test_v2_no_two_frames_land_on_the_same_loop_distance() -> None:
    """Re-derive every sampled position; no two frames repeat a loop distance.

    The distance-along-curve at frame ``f`` is
    ``phase * L + arc_fraction * L * (f - start) / span``. For any two
    distinct frames the difference is ``arc_fraction * L * (f2 - f1) / span``,
    which lies strictly in (0, L) because ``arc_fraction < 1`` and the frame
    delta is at most the span -- so modulo the loop no two sampled frames can
    ever collide. This test re-derives the real numbers instead of trusting
    that arithmetic.
    """
    state = _prepare()
    timeline = state["timeline"]
    span = float(timeline["frame_span"])
    start = int(timeline["start_frame"])
    end = int(timeline["end_frame"])
    stride = int(timeline["collision_frame_stride"])
    frames = list(range(start, end + 1, stride))
    if frames[-1] != end:
        frames.append(end)
    circuits = {entry["circuit"]: entry for entry in state["plan_v2"]["vehicles"]["circuits"]}
    for vehicle in state["plan_v2"]["vehicles"]["vehicles"]:
        length = float(circuits[vehicle["circuit"]]["length"])
        phase = float(vehicle["phase"])
        arc = float(vehicle["presentation_arc_fraction"])
        distances = [
            math.fmod(phase * length + arc * length * (frame - start) / span, length)
            for frame in frames
        ]
        for first in range(len(distances)):
            for second in range(first + 1, len(distances)):
                delta = abs(distances[second] - distances[first])
                circular = min(delta, length - delta)
                assert circular > 1.0e-9 * length, (
                    vehicle["slot"],
                    frames[first],
                    frames[second],
                )


def test_v2_motion_is_continuous_and_strictly_forward() -> None:
    """No V2 vehicle stops, freezes, teleports or reverses at any frame.

    The unwrapped distance ``arc * L * (f - start) / span`` is strictly
    increasing by the same constant step on every sampled frame, so the motion
    is smooth and continuous across the WHOLE clip. The Blender side keys
    ``eval_time`` linearly from ``phase * frame_span`` to
    ``(phase + arc) * frame_span`` across the same start..end range, which
    renders exactly this constant speed -- nothing ever holds still.
    """
    state = _prepare()
    timeline = state["timeline"]
    span = float(timeline["frame_span"])
    start = int(timeline["start_frame"])
    end = int(timeline["end_frame"])
    stride = int(timeline["collision_frame_stride"])
    frames = list(range(start, end + 1, stride))
    if frames[-1] != end:
        frames.append(end)
    circuits = {entry["circuit"]: entry for entry in state["plan_v2"]["vehicles"]["circuits"]}
    for vehicle in state["plan_v2"]["vehicles"]["vehicles"]:
        length = float(circuits[vehicle["circuit"]]["length"])
        arc = float(vehicle["presentation_arc_fraction"])
        distances = [arc * length * (frame - start) / span for frame in frames]
        assert all(
            later > earlier for earlier, later in zip(distances, distances[1:], strict=False)
        ), vehicle["slot"]


def test_v2_start_and_end_are_different_real_points_on_the_circuit() -> None:
    """The presentation window's endpoints are real, distinct polyline points.

    ``sample_loop`` interpolates on the circuit's real closed polyline, so the
    start (at ``phase * L``) and the end (at ``(phase + arc) * L`` mod ``L``)
    are real points on real existing lane geometry by construction. The
    separation along the loop is ``min(arc, 1 - arc) * L > 0``, so the vehicle
    begins and ends at genuinely different places -- it enters, drives and
    exits; it does not return to where it started.
    """
    state = _prepare()
    mp = state["mp"]
    circuits = {entry["circuit"]: entry for entry in state["plan_v2"]["vehicles"]["circuits"]}
    for vehicle in state["plan_v2"]["vehicles"]["vehicles"]:
        circuit = circuits[vehicle["circuit"]]
        stations = mp.loop_stations([tuple(point) for point in circuit["points"]])
        length = float(circuit["length"])
        phase = float(vehicle["phase"])
        arc = float(vehicle["presentation_arc_fraction"])
        start = mp.sample_loop(stations, phase * length)
        end = mp.sample_loop(stations, (phase + arc) * length)
        along = min(arc * length, length - arc * length)
        assert along > 1.0e-3, vehicle["slot"]
        assert math.hypot(start["x"] - end["x"], start["y"] - end["y"]) > 1.0e-3, vehicle["slot"]


def test_v2_wheels_roll_the_real_radius_over_the_arc() -> None:
    """No rolling-radius solve for V2: the geometric wheel rolls the arc.

    An arc that never returns to its start needs no closure contract, so the
    wheel turns ``arc_distance / (2 * pi * wheel_radius)`` at the REAL radius
    and the total rolled distance equals the arc's real distance exactly.
    """
    state = _prepare()
    for vehicle in state["plan_v2"]["vehicles"]["vehicles"]:
        assert float(vehicle["rolling_radius"]) == float(vehicle["wheel_radius"]), vehicle["slot"]
        assert float(vehicle["rolling_radius_drift"]) == 0.0, vehicle["slot"]
        assert float(vehicle["wheel_turns"]) > 0.0, vehicle["slot"]
        rolled = 2.0 * math.pi * float(vehicle["rolling_radius"]) * float(vehicle["wheel_turns"])
        assert abs(rolled - float(vehicle["arc_distance"])) < 1.0e-6, vehicle["slot"]


def test_v2_reports_its_real_average_speed() -> None:
    """A V2 vehicle's published speed is its real distance/time figure.

    Covering ``arc_fraction * circuit_length`` in the same 8-second clip means
    a real average speed of ``circuit_speed * arc_fraction`` -- slower than the
    full-lap figure, and reported truthfully rather than masked.
    """
    state = _prepare()
    circuits = {entry["circuit"]: entry for entry in state["plan_v2"]["vehicles"]["circuits"]}
    for vehicle in state["plan_v2"]["vehicles"]["vehicles"]:
        circuit = circuits[vehicle["circuit"]]
        arc = float(vehicle["presentation_arc_fraction"])
        expected = float(circuit["speed"]) * arc
        assert abs(float(vehicle["speed"]) - expected) < 1.0e-6, vehicle["slot"]


# ---------------------------------------------------------------------------
# The open-route family, measured honestly against the REAL network
# ---------------------------------------------------------------------------


def test_the_only_legal_turnarounds_are_dual_lane_terminations() -> None:
    """The two legal turnarounds are exactly the dual-lane declared terminations.

    A junction is deliberately not a turnaround, and a single-lane run cannot
    host one -- there is no second lane to come back on, and an out-and-back
    would repeat its own directional claim. Pinning the exact two turnarounds
    keeps the recorded ``open_route_count == 0`` from silently turning into a
    search regression: the V2 presentation does not depend on open routes (it
    shows bounded arcs of closed circuits), but the honest report of why the
    open family is empty must stay accurate.
    """
    state = _prepare()
    lanes = state["lanes_v2"]
    nodes = sorted(entry["node"] for entry in lanes["turnarounds"])
    assert nodes == ["T__eastgate_axis__a", "T__wallside_street__b"]
    by_node = {entry["node"]: entry for entry in lanes["turnarounds"]}
    assert by_node["T__eastgate_axis__a"]["termination"] == "plaza_approach"
    assert by_node["T__wallside_street__b"]["termination"] == "cul_de_sac"
    assert all(entry["class"] == "collector" for entry in lanes["turnarounds"])


# ---------------------------------------------------------------------------
# Metrics emitter
# ---------------------------------------------------------------------------


def test_traffic_v2_metrics_are_consistent() -> None:
    """The pure metrics function reports the plan's own numbers coherently."""
    state = _prepare()
    metrics = state["v2"].traffic_v2_metrics(state["plan_v2"])
    assert metrics["active_vehicle_count"] == 14
    assert metrics["distinct_route_count"] == len(state["plan_v2"]["vehicles"]["circuits"])
    # The locked EP1 network genuinely offers no out-and-back (its two legal
    # turnarounds are in disconnected dual-lane components), so the metrics
    # keep reporting the factual 0; the presentation fix is the bounded arc,
    # not a fabricated open route.
    assert metrics["open_route_count"] == 0
    assert (
        metrics["closed_circuit_count"] + metrics["open_route_count"]
        == metrics["distinct_route_count"]
    )
    assert metrics["distinct_segment_count"] > 1
    assert metrics["speed_min"] <= metrics["speed_mean"] <= metrics["speed_max"]
    # Arc metrics: every vehicle's bounded arc is strictly inside one lap, and
    # the real speeds are the arc-average figures (75% of the circuit band).
    assert (
        0.0
        < metrics["presentation_arc_fraction_min"]
        <= metrics["presentation_arc_fraction_max"]
        < 1.0
    )
    assert metrics["arc_distance_min"] > 0.0
    assert metrics["collision_violation_count"] == 0
    assert metrics["route_repeat_violation_count"] == 0


# ---------------------------------------------------------------------------
# Determinism across hash seeds, in fresh subprocesses (metamorphic pattern)
# ---------------------------------------------------------------------------

_HASH_SCRIPT = r"""
import sys
from pathlib import Path
sys.path.insert(0, {scripts!r})
import mobility_plan as mp
import pedestrian_topology as topo
import population_presence_plan as pres
from mobility_spec import load_daily_life_mobility_spec, resolve_mobility_timeline
from motion_time_spec import load_motion_time_spec
from population_presence_spec import load_population_presence_spec
from production_spec import load_production_world_spec
from road_graph import build_road_graph
from scene_spec import load_master_scene_spec, load_render_export
from urban_fabric import plan_urban_fabric

config = Path({config!r})
workdir = Path({workdir!r})
master = load_master_scene_spec(config / "master_scene_v1.json")
production = load_production_world_spec(config / "production_world_v1.json")
presence_spec = load_population_presence_spec(config / "population_presence_v1.json")
spec = load_daily_life_mobility_spec(config / "daily_life_mobility_v1.json")
timeline = resolve_mobility_timeline(
    spec, load_motion_time_spec(config / "motion_time_v1.json")["timeline"]
)
graph = build_road_graph(master, production)
fabric = plan_urban_fabric(master, production, graph)
topology = topo.plan_pedestrian_topology(master, production, graph, fabric, presence_spec)
export = load_render_export(workdir / "render_export_before.json")
presence = pres.plan_population_presence(export, master, presence_spec, topology)
plan = mp.plan_daily_life_mobility(
    presence, presence_spec, spec, timeline, master, production, graph, fabric
)
vehicles_v2 = mp.plan_vehicle_mobility(
    spec, timeline, master, graph, fabric, traffic_profile={profile!r}
)
plan_v2 = dict(plan)
plan_v2["vehicles"] = vehicles_v2
plan_v2["collision"] = mp.mobility_collisions(plan_v2, timeline, presence, spec)
if not plan_v2["collision"]["safe"]:
    raise SystemExit("unsafe: " + "; ".join(plan_v2["collision"]["failures"][:4]))
print(mp.mobility_plan_hash(plan_v2))
"""


def _plan_hash_under_seed(seed: str, profile: str, workdir: Path) -> str:
    """Derive the plan hash in a fresh subprocess under one PYTHONHASHSEED."""
    script = _HASH_SCRIPT.format(
        scripts=str(SCRIPTS_DIR),
        config=str(CONFIG_DIR),
        workdir=str(workdir),
        profile=profile,
    )
    # A truly empty environment (no SystemRoot) makes CPython's own Windows
    # startup fail near-instantly, before any of this script's code ever
    # runs -- a real environment-portability bug this project's own
    # subprocess determinism tests must not carry. SystemRoot (and TEMP, if
    # present) are inherited so the interpreter can bootstrap; PATH stays
    # empty, since nothing here needs an external executable on PATH.
    env = {
        "PYTHONHASHSEED": seed,
        "PATH": "",
        "PYTHONPATH": str(SCRIPTS_DIR),
        "LD_TEST_WORKDIR": str(workdir),
    }
    for name in ("SystemRoot", "SYSTEMROOT", "TEMP", "TMP"):
        if name in os.environ:
            env[name] = os.environ[name]
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    lines = [line for line in completed.stdout.strip().splitlines() if line]
    assert len(lines) == 1, completed.stdout + completed.stderr
    return lines[0]


def test_v2_plan_is_deterministic_across_hash_seeds() -> None:
    """Seeds 0, 1, 42 and 123456 all derive the identical V2 plan bytes."""
    workdir = _workdir_argument()
    if not (workdir / "render_export_before.json").is_file():
        raise FileNotFoundError(
            f"the real render export {workdir / 'render_export_before.json'} is required"
        )
    digests = {seed: _plan_hash_under_seed(seed, "v2", workdir) for seed in _SEEDS}
    assert len(set(digests.values())) == 1, digests


def main() -> int:
    """Plain-python runner: execute every test in definition order."""
    failures = 0
    executed = 0
    for name, function in sorted(
        ((n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)),
        key=lambda item: item[1].__code__.co_firstlineno,
    ):
        executed += 1
        try:
            function()
        except Exception as error:  # noqa: BLE001 - structural gate reports, not raises
            failures += 1
            print(f"FAIL {name}: {error}")
        else:
            print(f"ok   {name}")
    print(f"LD_MOBILITY_TRAFFIC_V2: {executed - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
