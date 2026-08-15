"""Import-boundary and scope guards for the Phase 19 daily-life mobility layer.

Phases 15 to 18 each own their own boundaries; these tests own Phase 19's:

* the spec, the kits, the lane network, the pedestrian mobility, the planner and
  the package verifier stay PURE, so a mobility plan can be derived, hashed and
  DISPROVED -- and a delivered proof package re-verified -- on a machine with no
  Blender at all;
* the Blender runtime never learns what a simulation is;
* the runtime consumes the pure plan rather than deciding anything itself;
* the gate orchestrates subprocesses and never imports ``bpy``;
* the Phase 19 structural runner executes the LOCKED Phase 15, 16, 17 and 18
  suites before its own, so mobility can never be made to pass by weakening
  anything that came before it;
* Phase 19 never writes to the engine or to the locked visual layers;
* and Phase 19 declares none of the scope it was explicitly told not to build.

The scope guard reads CODE, not prose. Phase 19 is allowed to say "route",
"gait" and "lane" -- those are its subject. What it may not do is IMPLEMENT an
identity, a family, a job, a schedule, a behaviour tree, or a mapping from a
simulation variable to how the city moves, because those are other phases' work
and, in the first four cases, work this project has decided never to do.
"""

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "visual" / "blender" / "scripts"
GATE = REPO_ROOT / "visual" / "blender" / "run_phase19_checks.py"
RUNNER = REPO_ROOT / "visual" / "blender" / "tests" / "run_blender_tests_p19.py"
CONFIG = REPO_ROOT / "visual" / "blender" / "config" / "daily_life_mobility_v1.json"

PURE_MODULES = (
    "mobility_spec.py",
    "vehicle_kit.py",
    "vehicle_lane_network.py",
    "pedestrian_mobility.py",
    "mobility_plan.py",
    "mobility_proof_package.py",
)

BLENDER_MODULES = (
    "apply_mobility.py",
    "produce_mobility_proof.py",
    "produce_vehicle_style_plate.py",
)

LOCKED_PHASE18_FILES = (
    "figure_kit.py",
    "population_presence_spec.py",
    "pedestrian_topology.py",
    "population_presence_plan.py",
    "apply_population_presence.py",
)


def imported_roots(path: Path) -> set[str]:
    """Top-level package names imported anywhere in one Python file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


# ---------------------------------------------------------------------------
# Purity
# ---------------------------------------------------------------------------


def test_the_mobility_planning_layer_never_imports_blender() -> None:
    """A mobility plan must be provable without Blender installed."""
    for name in PURE_MODULES:
        roots = imported_roots(SCRIPTS / name)
        assert "bpy" not in roots and "bmesh" not in roots, f"{name} imports Blender"


def test_the_mobility_planning_layer_never_imports_the_engine() -> None:
    """Presentation mobility is downstream of the simulation and never inside it."""
    for name in PURE_MODULES:
        roots = imported_roots(SCRIPTS / name)
        assert "living_diorama" not in roots, f"{name} imports the engine"


def test_the_blender_runtime_never_imports_the_engine() -> None:
    """The renderer is told what to build; it never asks the world."""
    for name in BLENDER_MODULES:
        assert (SCRIPTS / name).exists(), f"{name} is guarded but missing"
        roots = imported_roots(SCRIPTS / name)
        assert "living_diorama" not in roots, f"{name} imports the engine"


def test_the_gate_never_imports_blender() -> None:
    """The gate orchestrates Blender as a subprocess; it never becomes it."""
    roots = imported_roots(GATE)
    assert "bpy" not in roots and "bmesh" not in roots


def test_the_runtime_imports_the_pure_plan_rather_than_planning() -> None:
    """The builder instantiates. Deciding anything here would be deciding twice."""
    roots = imported_roots(SCRIPTS / "apply_mobility.py")
    assert "mobility_plan" in roots or "pedestrian_mobility" in roots


# ---------------------------------------------------------------------------
# Locked-layer protection
# ---------------------------------------------------------------------------


def test_phase19_never_imports_a_phase18_private_name() -> None:
    """Reaching into another phase's privates is reaching past its contract."""
    for name in PURE_MODULES + BLENDER_MODULES:
        path = SCRIPTS / name
        assert path.exists(), f"{name} is guarded but missing"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in {
                module.removesuffix(".py") for module in LOCKED_PHASE18_FILES
            }:
                for alias in node.names:
                    assert not alias.name.startswith("_"), f"{name} imports {alias.name}"


def test_phase19_never_assigns_into_a_locked_module() -> None:
    """Monkey-patching a locked module would reopen it without changing it."""
    locked = {module.removesuffix(".py") for module in LOCKED_PHASE18_FILES} | {
        "road_graph",
        "urban_fabric",
        "city_ground",
        "production_spec",
        "scene_spec",
        "spatial_occupancy",
        "motion_time_spec",
        "motion_plan",
    }
    for name in PURE_MODULES + BLENDER_MODULES:
        path = SCRIPTS / name
        assert path.exists(), f"{name} is guarded but missing"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                    assert target.value.id not in locked, (
                        f"{name} assigns into locked module {target.value.id}"
                    )


def test_phase19_declares_no_phase17_motion_channel() -> None:
    """Phase 19 has its own animation system and never extends Phase 17's."""
    for name in PURE_MODULES + BLENDER_MODULES:
        path = SCRIPTS / name
        assert path.exists(), f"{name} is guarded but missing"
        source = path.read_text(encoding="utf-8")
        assert "SUPPORTED_CHANNELS" not in source, f"{name} touches the Phase 17 channel list"


def test_the_phase19_runner_runs_every_locked_suite_first() -> None:
    """Mobility cannot be made to pass by weakening what came before it."""
    source = RUNNER.read_text(encoding="utf-8")
    order = [
        source.index('"phase15"'),
        source.index('"phase16"'),
        source.index('"phase17"'),
        source.index('"phase18"'),
        source.index('"phase19"'),
    ]
    assert order == sorted(order), "the structural suites are not in phase order"


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------

FORBIDDEN_IDENTIFIERS = re.compile(
    r"\b("
    r"citizen_name|resident_name|person_name|full_name|given_name|surname|"
    r"family_id|household|kinship|parent_of|child_of|spouse|relative|"
    r"workplace|employer|job_title|occupation|commute|errand|"
    r"schedule|timetable|itinerary|daily_routine|appointment|"
    r"behaviour_tree|behavior_tree|decision_tree|utility_ai|steering_agent|"
    r"npc|agent_brain|blackboard|"
    r"passenger|driver_name|vehicle_owner|licence_plate|license_plate|registration_number"
    r")\b",
    re.IGNORECASE,
)
"""Names Phase 19 must not DEFINE. Every one of them would be a claim about an
individual, a relationship, a job, a plan or an autonomous decision -- none of
which the simulation holds and none of which presentation mobility may invent."""

PHASE20_MAPPINGS = re.compile(
    r"\b("
    r"fear|trust|scarcity|institutional_pressure|social_stability|"
    r"law_state|resource_shortage|migration_pressure"
    r")\b",
    re.IGNORECASE,
)
"""Simulation variables Phase 19 must not read. Connecting mobility to world
state is Phase 20's work; doing it here would steal the next phase and make the
mobility layer a claim about causes it has not proven."""


def defined_names(path: Path) -> set[str]:
    """Every name this file DEFINES: functions, classes, assignments, arguments.

    Definitions rather than every token, so a docstring explaining that Phase 19
    holds no schedules does not read to the scanner exactly like a schedule.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.update(argument.arg for argument in node.args.args)
                names.update(argument.arg for argument in node.args.kwonlyargs)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # String KEYS are how a JSON-shaped plan names its own fields, so a
            # forbidden field name has to be caught here too -- but only where it
            # is a plain identifier-shaped literal, never inside prose.
            if re.fullmatch(r"[a-z][a-z0-9_]{2,}", node.value):
                names.add(node.value)
    return names


def test_phase19_defines_no_individual_identity() -> None:
    """A moving proxy is a representative proxy, and the code cannot say otherwise."""
    for name in PURE_MODULES + BLENDER_MODULES:
        path = SCRIPTS / name
        assert path.exists(), f"{name} is guarded but missing"
        for defined in sorted(defined_names(path)):
            assert not FORBIDDEN_IDENTIFIERS.fullmatch(defined), f"{name} defines {defined!r}"


def test_phase19_reads_no_simulation_variable() -> None:
    """Mobility that responded to fear or scarcity would be Phase 20's work."""
    for name in PURE_MODULES + BLENDER_MODULES:
        path = SCRIPTS / name
        assert path.exists(), f"{name} is guarded but missing"
        for defined in sorted(defined_names(path)):
            assert not PHASE20_MAPPINGS.fullmatch(defined), f"{name} defines {defined!r}"


def test_the_scope_guard_would_actually_bite(tmp_path: Path) -> None:
    """A guard nobody has seen fail is a guard nobody has tested.

    Two synthetic files, one carrying a forbidden definition and one a Phase 20
    mapping, prove the scanner finds what it claims to find rather than passing
    because its pattern never matches anything.
    """
    offender = tmp_path / "offender.py"
    offender.write_text(
        "def workplace(agent_brain):\n    schedule = {'commute': 1}\n    return schedule\n",
        encoding="utf-8",
    )
    found = {name for name in defined_names(offender) if FORBIDDEN_IDENTIFIERS.fullmatch(name)}
    assert {"workplace", "agent_brain", "schedule", "commute"} <= found

    phase20 = tmp_path / "phase20.py"
    phase20.write_text("fear = 0.5\ndef trust():\n    return fear\n", encoding="utf-8")
    caught = {name for name in defined_names(phase20) if PHASE20_MAPPINGS.fullmatch(name)}
    assert {"fear", "trust"} <= caught


def test_the_scope_guard_tolerates_the_words_phase19_owns() -> None:
    """Route, gait, lane and turnaround are Phase 19's subject, not its scope creep."""
    for word in (
        "route",
        "gait",
        "lane",
        "walking",
        "turnaround",
        "circuit",
        "vehicle",
        "wheel_turns",
        "mobility",
        "walker",
        "pedestrian_cycles",
        "driving_side",
    ):
        assert not FORBIDDEN_IDENTIFIERS.fullmatch(word), word
        assert not PHASE20_MAPPINGS.fullmatch(word), word


def test_the_config_declares_no_forbidden_policy() -> None:
    """The spec has nowhere to put a citizen, and this proves it has not grown one."""
    source = CONFIG.read_text(encoding="utf-8")
    for match in FORBIDDEN_IDENTIFIERS.finditer(source):
        raise AssertionError(f"the mobility spec names {match.group(0)!r}")
    for match in PHASE20_MAPPINGS.finditer(source):
        raise AssertionError(f"the mobility spec reads simulation variable {match.group(0)!r}")


def test_the_plan_carries_its_presentation_statement() -> None:
    """The claim is bounded in the plan itself, not only in a report."""
    source = (SCRIPTS / "mobility_plan.py").read_text(encoding="utf-8")
    assert "presentation mobility" in source
    assert "not individual citizen schedules" in source
    assert "authoritative destinations" in source
