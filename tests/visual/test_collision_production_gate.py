"""Production-boundary refusal tests for the V2 collision gate (pure pytest).

The gate under test is the fail-closed block inside
``visual/blender/scripts/episode_scene.py`` ``compose_episode_world``: the
profile validation (lines 139-153) and, under ``mobility_profile="v2"``, the
collision gate (lines 212-239) that runs
``collision_core_v2.verify_v2_collisions`` and raises
``mobility_plan.MobilityPlanError`` when the violation count is non-zero.
These tests drive THAT code -- never a copy -- and prove the refusal fires
and blocks production.

Why the gate is unit-tested through a harness instead of called bare
--------------------------------------------------------------------
``episode_scene`` itself is bpy-free at module level (pinned here), but
``compose_episode_world``'s FIRST statements (episode_scene.py:112-117)
import six appliers that each ``import bpy`` at module level (column 1):
apply_mobility.py:61, apply_mobility_v2.py:21, apply_motion_plan.py:37,
apply_population_presence.py:41, apply_state_response.py:38 and
apply_state_response_motion.py:23. A bare call therefore dies with
ImportError in a bpy-less pytest process BEFORE the profile validation and
the gate ever run. The tests install six inert stand-in modules under those
names in ``sys.modules`` (restored afterwards) so the REAL compose code
runs, and stub the PURE planning chain (spec loaders and planners,
episode_scene.py:155-199) to feed the gate tiny synthetic plans in the exact
shape the real verifier consumes. No gate code is extracted or
re-implemented: the merge (``episode_scene.merge_mobility_v2_plan``), the
verifier (``collision_core_v2.verify_v2_collisions``), the count check, the
refusal raise and the message text all come from production source.

Gate and CLI share one implementation (case 8)
----------------------------------------------
``compose_episode_world`` binds the gate verifier with
``import collision_core_v2 as collision_verifier`` (episode_scene.py:118)
and calls ``collision_verifier.verify_v2_collisions`` (line 218). The CLI
shell ``visual/blender/tools/verify_traffic_collisions_v2.py`` re-exports
that same function (lines 57-63). Because ``importlib`` caches one module
object per name in ``sys.modules``, the identity assertions in
``test_gate_and_cli_share_one_collision_implementation`` prove both entry
points are the SAME function object, so a future fork of the maths fails
here.

Honesty
-------
These tests were NOT executed in this workspace (no shell, no interpreter).
Expected verdicts are hand-derived from the core's published geometry
(collision_core_v2.py:25-57) and from the already-reviewed adversarial suite
``tests/visual/test_traffic_collisions_v2.py``; every fixture's expected
count and first-violation frame is stated so a failure names its own cause.
"""

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "visual" / "blender" / "scripts"
TOOLS_DIR = REPO_ROOT / "visual" / "blender" / "tools"
CONFIG_DIR = REPO_ROOT / "visual" / "blender" / "config"


def _load(name: str, *, path: Path | None = None):
    """Import one pure visual/blender module by sibling name.

    Mirrors ``tests/visual/conftest.py::load_visual_module`` and the inline
    loader ``test_traffic_collisions_v2.py::_load``: expose the scripts (or
    tools) directory on ``sys.path`` just long enough to import, then remove
    it. ``importlib`` caches one module object per name in ``sys.modules``,
    so every caller in this process shares that single object.
    """
    directory = str(path) if path is not None else str(SCRIPTS_DIR)
    # The scripts directory STAYS on sys.path. episode_scene defers its sibling
    # imports into compose_episode_world (episode_scene.py:123) so that merely
    # importing the module stays bpy-free; those imports resolve when the gate
    # is CALLED, long after this loader returns. Removing the path here would
    # make every gate test die with ModuleNotFoundError at call time.
    if directory not in sys.path:
        sys.path.insert(0, directory)
    return importlib.import_module(name)


# The REAL modules. `verifier` is the ONE collision implementation the gate
# and the CLI share; `episode_scene` carries the real gate code.
verifier = _load("collision_core_v2")
episode_scene = _load("episode_scene")
mobility_plan = _load("mobility_plan")
scene_spec = _load("scene_spec")
production_spec = _load("production_spec")
motion_time_spec = _load("motion_time_spec")
road_graph = _load("road_graph")
urban_fabric = _load("urban_fabric")
population_presence_spec = _load("population_presence_spec")
pedestrian_topology = _load("pedestrian_topology")
population_presence_plan = _load("population_presence_plan")
mobility_spec_module = _load("mobility_spec")
state_response_spec = _load("state_response_spec")

# The SHIPPED constants, read from the configs the core's own docstring cites
# (collision_core_v2.py:54-56), so this suite can never drift from the real
# clearances:
# * separation 1.15    <- population_presence_v1.json:18 ("proxy"."separation")
# * body_radius 0.34   <- population_presence_v1.json:17 ("proxy"."radius")
# * body_clearance 0.4 <- daily_life_mobility_v1.json:69 ("vehicles")
# * pedestrian_clearance 1.0 <- daily_life_mobility_v1.json:70 ("vehicles")
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

# The exact blocker: compose_episode_world imports these six appliers as its
# first statements (episode_scene.py:112-117), and each imports bpy at module
# level (column 1), so a bare call in a bpy-less process dies before the
# profile validation (episode_scene.py:139) and the gate (episode_scene.py:212).
# Values are the line numbers of each module-level `import bpy`.
_BPY_APPLIERS = {
    "apply_mobility": 61,
    "apply_mobility_v2": 21,
    "apply_motion_plan": 37,
    "apply_population_presence": 41,
    "apply_state_response": 38,
    "apply_state_response_motion": 23,
}


@pytest.fixture
def bpy_applier_stubs():
    """Install inert stand-ins so the REAL compose code runs bpy-free."""
    saved = {name: sys.modules.get(name) for name in _BPY_APPLIERS}
    for name in _BPY_APPLIERS:
        if name not in sys.modules:
            stub = types.ModuleType(name)
            stub.__file__ = str(SCRIPTS_DIR / f"{name}.py")
            sys.modules[name] = stub
    yield
    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


class GatePassed(Exception):
    """Raised by the stubbed state-response loader when compose clears the gate."""


@pytest.fixture
def drive_gate(monkeypatch, bpy_applier_stubs):
    """Run the REAL compose_episode_world to/through the V2 collision gate.

    The pre-gate planning chain (spec loaders and planners, episode_scene.py
    lines 155-199) is stubbed to return the caller's synthetic pieces; the
    gate itself -- merge, verifier, count check, raise and message -- is the
    real production code. ``load_state_response_spec`` is stubbed to raise
    ``GatePassed``, so a SAFE plan proves it cleared the gate by reaching the
    state-response layer (line 241, the first statement after the gate).
    """

    def _patch(module, name, value):
        monkeypatch.setattr(module, name, value)

    def _drive(*, ped_plan, veh_plan, presence, mobility_spec, timeline):
        _patch(scene_spec, "load_master_scene_spec", lambda path: {"master": True})
        _patch(production_spec, "load_production_world_spec", lambda path: {"production": True})
        _patch(motion_time_spec, "load_motion_time_spec", lambda path: {"timeline": timeline})
        _patch(road_graph, "build_road_graph", lambda master, production: {"graph": True})
        _patch(
            urban_fabric,
            "plan_urban_fabric",
            lambda master, production, graph: {"fabric": True},
        )
        _patch(
            population_presence_spec,
            "load_population_presence_spec",
            lambda path: {"presence_spec": True},
        )
        _patch(
            pedestrian_topology,
            "plan_pedestrian_topology",
            lambda *args, **kwargs: {"topology": True},
        )
        _patch(scene_spec, "load_render_export", lambda path: {"export": True})
        _patch(
            population_presence_plan,
            "plan_population_presence",
            lambda *args, **kwargs: presence,
        )
        _patch(mobility_spec_module, "load_daily_life_mobility_spec", lambda path: mobility_spec)
        _patch(
            mobility_spec_module,
            "resolve_mobility_timeline",
            lambda spec, motion_timeline: timeline,
        )
        _patch(mobility_plan, "plan_daily_life_mobility", lambda *args, **kwargs: ped_plan)
        _patch(mobility_plan, "plan_vehicle_mobility", lambda *args, **kwargs: veh_plan)

        def _gate_passed(*args, **kwargs):
            raise GatePassed("compose passed the V2 collision gate (state-response layer)")

        _patch(state_response_spec, "load_state_response_spec", _gate_passed)

        return episode_scene.compose_episode_world(
            spec_path=Path("spec.json"),
            production_path=Path("production.json"),
            motion_path=Path("motion.json"),
            presence_path=Path("presence.json"),
            mobility_path=Path("mobility.json"),
            state_response_path=Path("state_response.json"),
            before_path=Path("before.json"),
            after_path=Path("after.json"),
            mobility_profile="v2",
            traffic_profile="v2",
        )

    return _drive


# ---------------------------------------------------------------------------
# Synthetic world pieces, in the exact shape verify_v2_collisions consumes
# (the fixture style of test_traffic_collisions_v2.py, split into the two
# halves episode_scene.merge_mobility_v2_plan joins).
# ---------------------------------------------------------------------------


def _walker(slot, points, speed, offset, route_length):
    """A V2 walker entry, in the shape the verifier reads (collision_core_v2.py:249-253)."""
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


# A 16 m square loop. loop_stations closes it with the first vertex repeated
# at s == 16, so sample_loop interpolates a real perimeter, not a degenerate
# one (see the identical fixture note in test_traffic_collisions_v2.py:116-131).
_RING = [
    [0.0, 0.0, 0.0],
    [4.0, 0.0, 0.0],
    [4.0, 4.0, 0.0],
    [0.0, 4.0, 0.0],
    [0.0, 0.0, 0.0],
]
# The same loop shifted 10 m in +x: a car on it stays at least ~6 m from
# walkers working around the origin, so it can never violate pedestrian
# clearance (1.0) -- the safe-plan fixture's vehicle half.
_RING_FAR = [
    [10.0, 0.0, 0.0],
    [14.0, 0.0, 0.0],
    [14.0, 4.0, 0.0],
    [10.0, 4.0, 0.0],
    [10.0, 0.0, 0.0],
]


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


def _pedestrians(walkers, stationary_slots=()):
    """The pedestrians half of a merged V2 plan (``plan["pedestrians"]``)."""
    return {
        "pedestrians": {
            "walkers": list(walkers),
            "stationary_slots": list(stationary_slots),
            "body_radius": BODY_RADIUS,
            "separation": SEPARATION,
        }
    }


def _vehicles(vehicles, circuits):
    """The vehicles half of a merged V2 plan (``plan["vehicles"]``)."""
    return {
        "circuits": [{"circuit": name, "points": points} for name, points in circuits],
        "vehicles": list(vehicles),
    }


def _spec():
    """The mobility-spec shape the verifier reads (collision_core_v2.py:302-303)."""
    return {
        "vehicles": {
            "body_clearance": BODY_CLEARANCE,
            "pedestrian_clearance": PEDESTRIAN_CLEARANCE,
        }
    }


def _merged(ped_plan, veh_plan):
    """The REAL merge compose_episode_world applies before the gate."""
    return episode_scene.merge_mobility_v2_plan(ped_plan, veh_plan)


# ---------------------------------------------------------------------------
# The refusal message must say WHAT, WHERE and WHO (episode_scene.py:226-239).
# ---------------------------------------------------------------------------


def _assert_refusal_message(
    text,
    *,
    count,
    frames,
    first_frame,
    entity_a,
    entity_b,
    type_a,
    type_b,
    distance,
    required,
    min_pp,
    min_vv,
    min_vp,
):
    """Assert every diagnostic the gate's refusal message must carry."""
    first_line = (
        f"First violation: frame {first_frame}, {entity_a} ({type_a}) vs {entity_b} ({type_b})"
    )
    assert f"{count} collision violation(s)" in text
    assert f"across {frames} sampled frame(s)" in text
    assert "Minimum clearances" in text
    assert f"pedestrian-pedestrian {min_pp}" in text
    assert f"vehicle-vehicle {min_vv}" in text
    assert f"vehicle-pedestrian {min_vp}" in text
    assert first_line in text
    assert f"distance {distance}" in text
    assert f"required clearance {required}" in text
    assert "The world will not be composed." in text


# ---------------------------------------------------------------------------
# 1. Module-level bpy freedom, and the exact blocker of a bare compose call
# ---------------------------------------------------------------------------


def test_episode_scene_module_is_bpy_free_at_module_level():
    """The REAL episode_scene imports without Blender (module level is pure)."""
    assert episode_scene.__name__ == "episode_scene"
    assert episode_scene.__file__ == str(SCRIPTS_DIR / "episode_scene.py")
    source = (SCRIPTS_DIR / "episode_scene.py").read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        assert not (stripped.startswith("import bpy") or stripped.startswith("from bpy")), (
            f"episode_scene.py must not import bpy: {line}"
        )


def test_bare_compose_call_is_blocked_by_module_level_bpy_applier_imports():
    """Pin exactly what blocks a bare compose call in a bpy-less pytest run.

    compose_episode_world's first statements import six appliers
    (episode_scene.py:112-117) that each import bpy at module level -- before
    the profile validation (line 139) and the gate (line 212) ever run. This
    test pins the blocker so a future refactor that removes it makes the
    harness below unnecessary.
    """
    source = (SCRIPTS_DIR / "episode_scene.py").read_text(encoding="utf-8")
    lines = source.splitlines()
    for line_no in range(112, 118):
        assert "import apply_" in lines[line_no - 1], f"line {line_no}: {lines[line_no - 1]}"
    for name, bpy_line in _BPY_APPLIERS.items():
        applier_lines = (SCRIPTS_DIR / f"{name}.py").read_text(encoding="utf-8").splitlines()
        assert applier_lines[bpy_line - 1].strip() == "import bpy", f"{name}.py:{bpy_line}"


# ---------------------------------------------------------------------------
# 7. Unknown / unsupported profiles refuse, with an explaining message
# ---------------------------------------------------------------------------


def _compose_call(**overrides):
    """Call the REAL compose_episode_world with dummy paths.

    The profile validation (episode_scene.py:139-153) is the first code after
    the import block, so with the bpy applier stubs in place an invalid
    profile raises before any path is ever opened.
    """
    base = {
        "spec_path": Path("spec.json"),
        "production_path": Path("production.json"),
        "motion_path": Path("motion.json"),
        "presence_path": Path("presence.json"),
        "mobility_path": Path("mobility.json"),
        "state_response_path": Path("state_response.json"),
        "before_path": Path("before.json"),
        "after_path": Path("after.json"),
    }
    base.update(overrides)
    return episode_scene.compose_episode_world(**base)


def test_unknown_mobility_profile_refuses(bpy_applier_stubs):
    """An unknown mobility_profile refuses instead of falling into the V1 branch."""
    with pytest.raises(mobility_plan.MobilityPlanError) as excinfo:
        _compose_call(mobility_profile="v3")
    text = str(excinfo.value)
    assert "unknown mobility_profile 'v3'" in text
    assert "expected 'v1' or 'v2'" in text


def test_unknown_traffic_profile_refuses(bpy_applier_stubs):
    """An unknown traffic_profile refuses rather than being silently ignored."""
    with pytest.raises(mobility_plan.MobilityPlanError) as excinfo:
        _compose_call(traffic_profile="v3")
    text = str(excinfo.value)
    assert "unknown traffic_profile 'v3'" in text
    assert "expected 'v1' or 'v2'" in text


def test_v1_mobility_with_v2_traffic_refuses(bpy_applier_stubs):
    """(v1, v2) refuses: the V1 path cannot carry V2 traffic, and used to downgrade it silently."""
    with pytest.raises(mobility_plan.MobilityPlanError) as excinfo:
        _compose_call(mobility_profile="v1", traffic_profile="v2")
    text = str(excinfo.value)
    assert "cannot carry traffic_profile='v2'" in text
    assert "Refusing rather than silently reinterpreting" in text
    assert "mobility_profile='v2' to carry V2 traffic" in text


# ---------------------------------------------------------------------------
# 1 and 6. Safe plans and the temporal law: the gate must NOT refuse
# ---------------------------------------------------------------------------


def test_safe_v2_plan_passes_the_gate(drive_gate):
    """A collision-free merged V2 plan gets NO refusal from the gate."""
    w_a = _walker("walker_a", [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0)], 2.0, 0.0, 4.0)
    w_b = _walker("walker_b", [(0.0, 1.5, 0.0), (4.0, 1.5, 0.0)], 2.0, 0.0, 4.0)
    ped = _pedestrians([w_a, w_b])
    veh = _vehicles([_vehicle("car_a", "ring_far", 0.0)], [("ring_far", _RING_FAR)])
    timeline = _timeline(1, 49)
    presence = {"proxies": []}
    spec = _spec()

    # Premise via the REAL maths the gate consumes: parallel tracks 1.5 m
    # apart (gap 1.5 > separation 1.15) and a car >= 6 m away (clearance 1.0).
    report = verifier.verify_v2_collisions(_merged(ped, veh), timeline, presence, spec)
    assert report["summary"]["collision_violation_count"] == 0
    assert report["collision"]["safe"] is True

    # The gate lets it through: compose reaches the state-response layer.
    with pytest.raises(GatePassed, match="passed the V2 collision gate"):
        drive_gate(
            ped_plan=ped, veh_plan=veh, presence=presence, mobility_spec=spec, timeline=timeline
        )


def test_same_place_different_time_passes_the_gate(drive_gate):
    """Two entities crossing the same point at separated frames must NOT refuse.

    walker_a occupies (2, 0) on frame 25; walker_b occupied (2, 0) on frame 1
    -- 24 frames apart. The gate must inherit the TEMPORAL law, not a
    geometric one.
    """
    w_a = _walker("walker_a", [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0)], 2.0, 0.0, 4.0)
    w_b = _walker("walker_b", [(2.0, 0.0, 0.0), (6.0, 0.0, 0.0)], 2.0, 0.0, 4.0)
    ped = _pedestrians([w_a, w_b])
    veh = _vehicles([], [])
    timeline = _timeline(1, 49)
    presence = {"proxies": []}
    spec = _spec()

    report = verifier.verify_v2_collisions(_merged(ped, veh), timeline, presence, spec)
    assert report["rows"] == []
    assert report["summary"]["collision_violation_count"] == 0
    assert report["collision"]["closest"]["walker_walker"] == 2.0

    with pytest.raises(GatePassed, match="passed the V2 collision gate"):
        drive_gate(
            ped_plan=ped, veh_plan=veh, presence=presence, mobility_spec=spec, timeline=timeline
        )


# ---------------------------------------------------------------------------
# 2-5. Each pair class refuses with MobilityPlanError and a full message
# ---------------------------------------------------------------------------


def test_walker_walker_violation_refuses(drive_gate):
    """Two walkers whose paths put them within separation at the same frame."""
    w_a = _walker("walker_a", [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0)], 2.0, 0.0, 4.0)
    w_b = _walker("walker_b", [(4.0, 0.0, 0.0), (0.0, 0.0, 0.0)], 2.0, 0.0, 4.0)
    ped = _pedestrians([w_a, w_b])
    veh = _vehicles([], [])
    timeline = _timeline(1, 49)
    presence = {"proxies": []}
    spec = _spec()

    # Premise: gap = |2d - 4| with d = (f-1)/12 < 1.15 exactly on frames
    # 19..31 (13 violations; first frame 19), hand-derived like the
    # adversarial suite's test_pedestrian_pedestrian_collision_is_caught.
    report = verifier.verify_v2_collisions(_merged(ped, veh), timeline, presence, spec)
    assert report["summary"]["collision_violation_count"] == 13

    with pytest.raises(mobility_plan.MobilityPlanError) as excinfo:
        drive_gate(
            ped_plan=ped, veh_plan=veh, presence=presence, mobility_spec=spec, timeline=timeline
        )
    _assert_refusal_message(
        str(excinfo.value),
        count=13,
        frames=49,
        first_frame=19,
        entity_a="walker_a",
        entity_b="walker_b",
        type_a="walker",
        type_b="walker",
        distance="1.0",
        required="1.15",
        min_pp="0.0",
        min_vv="None",
        min_vp="None",
    )


def test_walker_stationary_violation_refuses(drive_gate):
    """A walker passing within separation of a standing presence proxy."""
    w_a = _walker("walker_a", [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0)], 2.0, 0.0, 4.0)
    ped = _pedestrians([w_a], stationary_slots=["stn_1"])
    veh = _vehicles([], [])
    timeline = _timeline(1, 49)
    presence = {"proxies": [{"slot": "stn_1", "x": 2.0, "y": 0.0}]}
    spec = _spec()

    # Premise: the walker's x = (f-1)/12 crosses the stationary proxy at
    # (2, 0); gap = |2 - d| < 1.15 exactly on frames 12..38 (27 violations;
    # first frame 12, gap 1.083333). The proxy sits ON the path, so the
    # minimum pedestrian-pedestrian clearance is 0.0 at frame 25.
    report = verifier.verify_v2_collisions(_merged(ped, veh), timeline, presence, spec)
    assert report["summary"]["collision_violation_count"] == 27
    assert report["rows"][0]["entity_type_b"] == "stationary"

    with pytest.raises(mobility_plan.MobilityPlanError) as excinfo:
        drive_gate(
            ped_plan=ped, veh_plan=veh, presence=presence, mobility_spec=spec, timeline=timeline
        )
    _assert_refusal_message(
        str(excinfo.value),
        count=27,
        frames=49,
        first_frame=12,
        entity_a="walker_a",
        entity_b="stn_1",
        type_a="walker",
        type_b="stationary",
        distance="1.083333",
        required="1.15",
        min_pp="0.0",
        min_vv="None",
        min_vp="None",
    )


def test_vehicle_walker_violation_refuses(drive_gate):
    """A walker standing on a circuit a vehicle drives over, co-timed."""
    ped = _pedestrians([_hold_walker("walker_a", 0.0, 0.0)])
    veh = _vehicles([_vehicle("car_a", "ring", 0.0)], [("ring", _RING)])
    timeline = _timeline(1, 9)
    presence = {"proxies": []}
    spec = _spec()

    # Premise from the adversarial suite's
    # test_vehicle_pedestrian_collision_is_caught: 4 violations on frames
    # [1, 2, 8, 9]; the car's body overlaps the walker's circle on frame 1
    # (distance 0.0 < pedestrian_clearance 1.0), which is the first row.
    report = verifier.verify_v2_collisions(_merged(ped, veh), timeline, presence, spec)
    assert report["summary"]["collision_violation_count"] == 4
    assert sorted({row["presentation_frame"] for row in report["rows"]}) == [1, 2, 8, 9]

    with pytest.raises(mobility_plan.MobilityPlanError) as excinfo:
        drive_gate(
            ped_plan=ped, veh_plan=veh, presence=presence, mobility_spec=spec, timeline=timeline
        )
    _assert_refusal_message(
        str(excinfo.value),
        count=4,
        frames=9,
        first_frame=1,
        entity_a="car_a",
        entity_b="walker_a",
        type_a="vehicle",
        type_b="walker",
        distance="0.0",
        required="1.0",
        min_pp="None",
        min_vv="None",
        min_vp="0.0",
    )


def test_vehicle_vehicle_violation_refuses(drive_gate):
    """Two vehicles on one circuit whose bodies come within body_clearance."""
    ped = _pedestrians([])
    veh = _vehicles(
        [_vehicle("car_a", "ring", 0.0), _vehicle("car_b", "ring", 0.05)],
        [("ring", _RING)],
    )
    timeline = _timeline(1, 9)
    presence = {"proxies": []}
    spec = _spec()

    # Premise from the adversarial suite's test_vehicle_vehicle_collision_is_caught:
    # centers stay 0.8 m apart with identical heading, so the 3.0 m bodies
    # overlap on EVERY frame (9 violations, first frame 1, distance 0.0).
    report = verifier.verify_v2_collisions(_merged(ped, veh), timeline, presence, spec)
    assert report["summary"]["collision_violation_count"] == 9
    assert {row["presentation_frame"] for row in report["rows"]} == set(range(1, 10))

    with pytest.raises(mobility_plan.MobilityPlanError) as excinfo:
        drive_gate(
            ped_plan=ped, veh_plan=veh, presence=presence, mobility_spec=spec, timeline=timeline
        )
    _assert_refusal_message(
        str(excinfo.value),
        count=9,
        frames=9,
        first_frame=1,
        entity_a="car_a",
        entity_b="car_b",
        type_a="vehicle",
        type_b="vehicle",
        distance="0.0",
        required="0.4",
        min_pp="None",
        min_vv="0.0",
        min_vp="None",
    )


# ---------------------------------------------------------------------------
# 8. Gate and CLI share ONE collision implementation
# ---------------------------------------------------------------------------


def test_gate_and_cli_share_one_collision_implementation():
    """The gate's verifier IS the CLI's re-exported verifier: same function object.

    ``compose_episode_world`` binds the gate verifier with
    ``import collision_core_v2 as collision_verifier`` (episode_scene.py:118)
    and calls it at line 218; the CLI shell re-exports that same name
    (verify_traffic_collisions_v2.py:57-63). importlib keeps ONE module
    object per name in sys.modules, so identity here proves a future fork of
    the maths breaks the gate-vs-CLI contract.
    """
    cli = _load("verify_traffic_collisions_v2", path=TOOLS_DIR)
    core = sys.modules["collision_core_v2"]
    assert cli.verify_v2_collisions is core.verify_v2_collisions
    assert core.verify_v2_collisions is verifier.verify_v2_collisions

    source = (SCRIPTS_DIR / "episode_scene.py").read_text(encoding="utf-8")
    assert "import collision_core_v2 as collision_verifier" in source
    assert "collision_verifier.verify_v2_collisions(" in source

    # For the same authoritative inputs, the gate's verifier and the CLI's
    # re-export return the identical document (the vehicle-walker fixture).
    ped = _pedestrians([_hold_walker("walker_a", 0.0, 0.0)])
    veh = _vehicles([_vehicle("car_a", "ring", 0.0)], [("ring", _RING)])
    timeline = _timeline(1, 9)
    presence = {"proxies": []}
    spec = _spec()
    plan = _merged(ped, veh)

    via_gate = core.verify_v2_collisions(plan, timeline, presence, spec)
    via_cli = cli.verify_v2_collisions(plan, timeline, presence, spec)
    assert via_gate == via_cli
    assert via_gate["summary"]["collision_violation_count"] == 4
