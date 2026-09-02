"""Adversarial tests for the V2 temporal collision core (pure pytest).

No ``bpy``, no Blender, no wall clock, no randomness. The REAL shared collision
core (``visual/blender/scripts/collision_core_v2.py``) is imported directly via
the same sibling-import mechanism this file already uses for ``mobility_plan``
and run on tiny, hand-built synthetic plans. The expected verdicts below were
derived by hand from the core's own published geometry (docstring lines 25-57
of the core), NOT by re-implementing its maths in this file -- so a verifier
that stops being temporal, stops sweeping, wraps an open path, or drops a pair
fails loudly here.

Real functions imported (file:line)
-----------------------------------
* ``collision_core_v2.verify_v2_collisions``
  -- visual/blender/scripts/collision_core_v2.py:281
* ``collision_core_v2._open_stations`` -- :104
* ``collision_core_v2._sample_open`` -- :145
* ``collision_core_v2._v2_distance_keys`` -- :179
* ``collision_core_v2._v2_distance_at_frame`` -- :214
* ``mobility_plan.loop_stations`` -- visual/blender/scripts/mobility_plan.py:122
* ``mobility_plan.sample_loop`` -- visual/blender/scripts/mobility_plan.py:153
  (the core imports ``mobility_plan`` itself at collision_core_v2.py:72 and
  calls the REAL planner's vehicle loop/sample maths, never a test copy)
* ``spatial_occupancy.circle/rect/shape_gap`` are imported by the core itself
  at collision_core_v2.py:77.

Fixture constants come from the SHIPPED config files the core's own docstring
cites (collision_core_v2.py:54-56), so this suite can never drift from the
real clearances:
* separation 1.15    <- population_presence_v1.json:18 ("proxy"."separation")
* body_radius 0.34   <- population_presence_v1.json:17 ("proxy"."radius")
* body_clearance 0.4 <- daily_life_mobility_v1.json:69 ("vehicles")
* pedestrian_clearance 1.0 <- daily_life_mobility_v1.json:70 ("vehicles")

Honesty: these tests were NOT executed in this workspace (no shell, no
interpreter). Expected verdicts are hand-derived from the core source; every
fixture's expected frame range is stated so a failure names its cause.
"""

import importlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "visual" / "blender" / "scripts"
TOOLS_DIR = REPO_ROOT / "visual" / "blender" / "tools"
CONFIG_DIR = REPO_ROOT / "visual" / "blender" / "config"


def _load(name: str):
    """Import one pure visual/blender/scripts module by sibling name."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


# The REAL shared collision core, loaded by the same sibling-import mechanism
# used for mobility_plan. It imports mobility_plan and spatial_occupancy
# itself (collision_core_v2.py:72,77), so this load is bpy-free.
verifier = _load("collision_core_v2")

# The SHIPPED constants, read from the configs the core's docstring cites.
_PRESENCE_CONFIG = json.loads(
    (CONFIG_DIR / "population_presence_v1.json").read_text(encoding="utf-8")
)
_MOBILITY_CONFIG = json.loads(
    (CONFIG_DIR / "daily_life_mobility_v1.json").read_text(encoding="utf-8")
)
SEPARATION = float(_PRESENCE_CONFIG["proxy"]["separation"])  # 1.15
BODY_RADIUS = float(_PRESENCE_CONFIG["proxy"]["radius"])  # 0.34
BODY_CLEARANCE = float(_MOBILITY_CONFIG["vehicles"]["body_clearance"])  # 0.4
PEDESTRIAN_CLEARANCE = float(_MOBILITY_CONFIG["vehicles"]["pedestrian_clearance"])  # 1.0


# ---------------------------------------------------------------------------
# Tiny synthetic fixtures in the exact shape verify_v2_collisions consumes
# ---------------------------------------------------------------------------


def _walker(slot, points, speed, offset, route_length):
    """A V2 walker entry, in the shape the verifier reads.

    The fields _v2_distance_keys and _v2_tracks consume
    (collision_core_v2.py:249-253, 179-212).
    """
    return {
        "slot": slot,
        "points": [[float(x), float(y), float(z)] for x, y, z in points],
        "route_length": float(route_length),
        "preferred_speed": float(speed),
        "start_offset": float(offset),
        "micro_behavior_schedule": [],
    }


def _hold_walker(slot, x, y):
    """A walker that never moves: seeded offset far beyond any test timeline."""
    return _walker(slot, [(x, y, 0.0), (x + 1.0, y, 0.0)], 1.0, 1000.0, 1.0)


def _timeline(start, end, fps=24, stride=1):
    """A resolved mobility timeline in the exact shape the verifier reads."""
    return {
        "fps": fps,
        "start_frame": start,
        "end_frame": end,
        "frame_span": end - start,
        "duration_seconds": (end - start) / fps,
        "collision_frame_stride": stride,
    }


# A 16 m square loop. loop_stations closes it with the first vertex repeated at
# s == 16, so sample_loop interpolates a real perimeter, not a degenerate one.
_RING = [
    [0.0, 0.0, 0.0],
    [4.0, 0.0, 0.0],
    [4.0, 4.0, 0.0],
    [0.0, 4.0, 0.0],
    [0.0, 0.0, 0.0],
]
# The closing vertex is deliberate. The vehicle's travelled distance wraps on
# the CIRCUIT'S OWN station length, which comes from these points -- not from
# the declared route_length. Without the closing vertex the four corners give a
# 12 m open polyline, so a distance of 12 would wrap to (0, 0) at frame 7 and
# the ring would not be the 16 m loop this fixture claims. Note also that
# `route_length` drives the distance law while `length` (3.0) is the vehicle's
# BODY length feeding half_length -- the two must never be conflated.


def _vehicle(slot, circuit, phase, body_length=3.0, width=1.0, route_length=16.0, arc=1.0):
    """A V2 vehicle entry: the fields _v2_tracks reads (lines 260-271)."""
    return {
        "slot": slot,
        "circuit": circuit,
        "route_length": float(route_length),
        "phase": float(phase),
        "presentation_arc_fraction": float(arc),
        "length": float(body_length),
        "width": float(width),
    }


def _plan(walkers, vehicles=(), circuits=(), stationary_slots=()):
    """A plan in the shape verify_v2_collisions consumes (lines 294-304)."""
    return {
        "pedestrians": {
            "walkers": list(walkers),
            "stationary_slots": list(stationary_slots),
            "body_radius": BODY_RADIUS,
            "separation": SEPARATION,
        },
        "vehicles": {
            "circuits": [{"circuit": name, "points": points} for name, points in circuits],
            "vehicles": list(vehicles),
        },
    }


def _run(plan, timeline, presence=None, spec=None):
    """Run the REAL verifier on a synthetic world.

    Returns the (collision, rows, summary) triple of
    verify_v2_collisions (collision_core_v2.py:516).
    """
    presence_plan = {"proxies": []} if presence is None else presence
    mobility_spec = (
        {
            "vehicles": {
                "body_clearance": BODY_CLEARANCE,
                "pedestrian_clearance": PEDESTRIAN_CLEARANCE,
            }
        }
        if spec is None
        else spec
    )
    result = verifier.verify_v2_collisions(plan, timeline, presence_plan, mobility_spec)
    return result["collision"], result["rows"], result["summary"]


def _sample(walker, timeline, frame):
    """Where the REAL V2 trajectory laws put a walker at an integer frame."""
    stations = verifier._open_stations([tuple(point) for point in walker["points"]])
    keys = verifier._v2_distance_keys(walker, timeline)
    return verifier._sample_open(stations, verifier._v2_distance_at_frame(keys, frame))


# ---------------------------------------------------------------------------
# The 8 adversarial cases
# ---------------------------------------------------------------------------


def test_vehicle_pedestrian_collision_is_caught():
    """A walker standing on a circuit a vehicle drives over, co-timed."""
    plan = _plan(
        walkers=[_hold_walker("walker_a", 0.0, 0.0)],
        vehicles=[_vehicle("car_a", "ring", 0.0)],
        circuits=[("ring", _RING)],
    )
    timeline = _timeline(1, 9)
    collision, rows, summary = _run(plan, timeline)

    # Vehicle distance d = phase*L + arc_fraction*L*(f-1)/8 sweeps the 16 m
    # loop; the walker's circle (0,0,r=0.34) is within pedestrian_clearance
    # (1.0) of the 3.0 m x 1.0 m body on frames 1, 2, 8, 9 only (hand-derived
    # from spatial_occupancy._rect_point_distance: gaps 0, 0.16, 0.16, 0).
    assert collision["safe"] is False
    assert summary["collision_violation_count"] == 4
    assert sorted({row["presentation_frame"] for row in rows}) == [1, 2, 8, 9]
    for row in rows:
        assert row["entity_type_a"] == "vehicle"
        assert row["entity_type_b"] == "walker"
        assert row["distance"] < row["required_clearance"]
        assert row["required_clearance"] == PEDESTRIAN_CLEARANCE
    assert collision["required"]["walker_vehicle"] == PEDESTRIAN_CLEARANCE


def test_vehicle_vehicle_collision_is_caught():
    """Two vehicles on one circuit whose bodies come within body_clearance."""
    plan = _plan(
        walkers=[],
        vehicles=[
            _vehicle("car_a", "ring", 0.0),
            _vehicle("car_b", "ring", 0.05),
        ],
        circuits=[("ring", _RING)],
    )
    timeline = _timeline(1, 9)
    collision, rows, summary = _run(plan, timeline)

    # Both cars share the arc term, so their centers stay 0.05 * 16 = 0.8 m
    # apart with identical heading; 3.0 m-long bodies overlap on EVERY frame
    # (shape_gap clamps overlap to 0.0 < body_clearance 0.4).
    assert collision["safe"] is False
    assert summary["collision_violation_count"] == 9
    assert {row["presentation_frame"] for row in rows} == set(range(1, 10))
    for row in rows:
        assert row["entity_type_a"] == "vehicle"
        assert row["entity_type_b"] == "vehicle"
        assert row["distance"] < row["required_clearance"]
        assert row["required_clearance"] == BODY_CLEARANCE
    assert collision["required"]["vehicle_vehicle"] == BODY_CLEARANCE


def test_pedestrian_pedestrian_collision_is_caught():
    """Two walkers whose paths put them within separation at the same frame."""
    plan = _plan(
        walkers=[
            _walker("walker_a", [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0)], 2.0, 0.0, 4.0),
            _walker("walker_b", [(4.0, 0.0, 0.0), (0.0, 0.0, 0.0)], 2.0, 0.0, 4.0),
        ],
    )
    timeline = _timeline(1, 49)
    collision, rows, summary = _run(plan, timeline)

    # a and b walk toward each other at 2 m/s on a 4 m track; gap = |2d - 4|
    # with d = (f-1)/12, so gap < 1.15 exactly on frames 19..31 (13 frames).
    assert collision["safe"] is False
    assert summary["collision_violation_count"] == 13
    assert sorted({row["presentation_frame"] for row in rows}) == list(range(19, 32))
    for row in rows:
        assert row["entity_type_a"] == "walker"
        assert row["entity_type_b"] == "walker"
        assert row["distance"] < row["required_clearance"]
        assert row["required_clearance"] == SEPARATION


def test_same_space_different_time_is_not_a_collision():
    """The single most important test: the check is TEMPORAL, not geometric.

    Both walkers traverse the shared corridor x in [2, 4]; walker_a is there
    on frames 25..49, walker_b was there on frames 1..25. The same point
    (2, 0) is occupied 24 frames apart, so zero violations must be reported.
    """
    w_a = _walker("walker_a", [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0)], 2.0, 0.0, 4.0)
    w_b = _walker("walker_b", [(2.0, 0.0, 0.0), (6.0, 0.0, 0.0)], 2.0, 0.0, 4.0)
    plan = _plan(walkers=[w_a, w_b])
    timeline = _timeline(1, 49)
    collision, rows, summary = _run(plan, timeline)

    # Premise, via the REAL trajectory laws: identical point, separated frames.
    at_a = _sample(w_a, timeline, 25)
    at_b = _sample(w_b, timeline, 1)
    assert (round(at_a["x"], 6), round(at_a["y"], 6)) == (2.0, 0.0)
    assert (round(at_b["x"], 6), round(at_b["y"], 6)) == (2.0, 0.0)

    # Constant headway of 2.0 (> 1.15) on every sampled frame.
    assert rows == []
    assert collision["safe"] is True
    assert summary["collision_violation_count"] == 0
    assert collision["closest"]["walker_walker"] == 2.0


def test_near_miss_above_clearance_is_not_a_violation():
    """Separation comfortably above the threshold is clean."""
    w_a = _walker("walker_a", [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0)], 2.0, 0.0, 4.0)
    w_b = _walker("walker_b", [(0.0, 1.5, 0.0), (4.0, 1.5, 0.0)], 2.0, 0.0, 4.0)
    plan = _plan(walkers=[w_a, w_b])
    timeline = _timeline(1, 49)
    collision, rows, summary = _run(plan, timeline)

    # Parallel tracks 1.5 m apart: gap stays exactly 1.5 > separation (1.15).
    assert rows == []
    assert collision["safe"] is True
    assert summary["collision_violation_count"] == 0
    assert collision["closest"]["walker_walker"] == 1.5
    assert SEPARATION < 1.5


def test_clearance_boundary_is_pinned_by_epsilon():
    """The clearance boundary is pinned from BOTH sides.

    Below by epsilon -> one violation; above by epsilon -> zero. A one-frame
    timeline isolates the pair so 'exactly one violation' is literal (no
    vehicles, so frame_span 0 is never divided by).
    """
    timeline = _timeline(1, 1)

    below = _plan(
        walkers=[
            _hold_walker("walker_a", 0.0, 0.0),
            _hold_walker("walker_b", SEPARATION - 1.0e-3, 0.0),
        ],
    )
    collision, rows, summary = _run(below, timeline)
    assert summary["collision_violation_count"] == 1
    assert collision["safe"] is False
    row = rows[0]
    assert row["entity_type_a"] == "walker" and row["entity_type_b"] == "walker"
    assert row["required_clearance"] == SEPARATION
    assert row["distance"] < row["required_clearance"]
    assert abs(row["distance"] - (SEPARATION - 1.0e-3)) < 1.0e-6

    above = _plan(
        walkers=[
            _hold_walker("walker_a", 0.0, 0.0),
            _hold_walker("walker_b", SEPARATION + 1.0e-3, 0.0),
        ],
    )
    collision, rows, summary = _run(above, timeline)
    assert rows == []
    assert collision["safe"] is True
    assert summary["collision_violation_count"] == 0
    assert collision["closest"]["walker_walker"] == round(SEPARATION + 1.0e-3, 4)


def test_endpoint_hold_is_caught_for_the_whole_hold():
    """The real-world defect class: an arrival that holds inside another body.

    A walker ARRIVES and then holds at its route end within clearance of another
    body. Every hold frame, not just the
    arrival frame, must be flagged.
    """
    w_a = _walker("walker_a", [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)], 1.0, 0.0, 2.0)
    w_b = _hold_walker("walker_b", 2.0, 1.0)
    plan = _plan(walkers=[w_a, w_b])
    timeline = _timeline(1, 72)
    collision, rows, summary = _run(plan, timeline)

    # w_a arrives at (2, 0) on frame 49 (1 + 2 m / 1 m/s * 24 fps) and holds;
    # w_b stands at (2, 1), exactly 1.0 inside separation. Hand-derived: the
    # pair is within 1.15 from frame 36 (approach tail) through 72 (end).
    frames = {row["presentation_frame"] for row in rows}
    assert frames == set(range(36, 73))
    assert 49 in frames  # the arrival frame itself
    assert 72 in frames  # the very last sampled frame of the hold
    hold = set(range(49, 73))
    assert hold <= frames  # EVERY hold frame is swept, not only the arrival
    assert summary["collision_violation_count"] == len(frames)
    for row in rows:
        assert row["distance"] < row["required_clearance"]
        assert row["required_clearance"] == SEPARATION


def test_open_trajectory_holds_at_both_ends_and_never_wraps():
    """V2 paths are OPEN and never wrap.

    Hold at the start until start_offset elapses, walk, then hold at the route
    end forever -- never wrapping back to the beginning.
    """
    walker = _walker("walker_a", [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0)], 2.0, 1.0, 4.0)
    timeline = _timeline(1, 100)
    keys = verifier._v2_distance_keys(walker, timeline)

    # hold at START before start_offset (1.0 s == 24 frames) elapses
    assert verifier._v2_distance_at_frame(keys, 1) == 0.0
    assert verifier._v2_distance_at_frame(keys, 24) == 0.0
    assert verifier._v2_distance_at_frame(keys, 25) == 0.0
    assert verifier._v2_distance_at_frame(keys, 26) > 0.0

    # arrive at the route end on frame 73 (25 + 4 m / 2 m/s * 24 fps) and HOLD
    assert verifier._v2_distance_at_frame(keys, 73) == 4.0
    assert verifier._v2_distance_at_frame(keys, 100) == 4.0
    travelled = [verifier._v2_distance_at_frame(keys, frame) for frame in range(1, 101)]
    assert travelled == sorted(travelled)  # never decreases: no wrap to 0

    # position after arrival IS the route end (open path, not a loop)
    stations = verifier._open_stations([tuple(point) for point in walker["points"]])
    start_pos = verifier._sample_open(stations, 0.0)
    end_pos = verifier._sample_open(stations, 4.0)
    beyond_pos = verifier._sample_open(stations, 100.0)
    assert (round(start_pos["x"], 6), round(start_pos["y"], 6)) == (0.0, 0.0)
    assert (round(end_pos["x"], 6), round(end_pos["y"], 6)) == (4.0, 0.0)
    assert (round(beyond_pos["x"], 6), round(beyond_pos["y"], 6)) == (4.0, 0.0)

    # end-to-end: a lone walker on the open trajectory is swept clean
    collision, rows, summary = _run(_plan(walkers=[walker]), _timeline(1, 100))
    assert rows == []
    assert collision["safe"] is True
    assert summary["collision_violation_count"] == 0


# ---------------------------------------------------------------------------
# The summary contract, and the bpy-freedom guarantee
# ---------------------------------------------------------------------------


def test_summary_contract_fields_and_counts():
    """The summary carries V1's contract fields and a count matching the rows."""
    plan = _plan(
        walkers=[_hold_walker("walker_a", 0.0, 0.0)],
        vehicles=[_vehicle("car_a", "ring", 0.0)],
        circuits=[("ring", _RING)],
    )
    collision, rows, summary = _run(plan, _timeline(1, 9))

    for key in (
        "frames_sampled",
        "frame_stride",
        "pairs_checked",
        "closest",
        "required",
        "failures",
        "safe",
    ):
        assert key in collision
    assert collision["frames_sampled"] == 9
    assert collision["frame_stride"] == 1
    assert collision["pairs_checked"] == {
        "walker_walker": 0,
        "walker_stationary": 0,
        "vehicle_vehicle": 0,
        "vehicle_pedestrian": 1,
    }
    assert set(collision["required"]) == {
        "walker_walker",
        "walker_stationary",
        "vehicle_vehicle",
        "walker_vehicle",
    }
    assert isinstance(collision["failures"], list)
    assert collision["safe"] is False
    assert summary["collision_violation_count"] == len(rows) == 4
    assert all(row["violation"] for row in rows)
    assert summary["collision_violation_count"] == len([row for row in rows if row["violation"]])


def test_verifier_and_its_modules_never_import_bpy():
    """The verifier and everything it reaches run without Blender."""
    for path in (
        TOOLS_DIR / "verify_traffic_collisions_v2.py",
        SCRIPTS_DIR / "collision_core_v2.py",
        SCRIPTS_DIR / "mobility_plan.py",
        SCRIPTS_DIR / "spatial_occupancy.py",
    ):
        source = path.read_text(encoding="utf-8")
        offenders = [
            line
            for line in source.splitlines()
            if line.lstrip().startswith(("import bpy", "from bpy"))
        ]
        assert not offenders, f"{path} imports bpy: {offenders}"
