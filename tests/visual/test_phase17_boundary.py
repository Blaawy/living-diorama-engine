"""Import-boundary and ownership guards for the Phase 17 motion layer.

Phase 15 already sweeps ``visual/blender`` for engine imports and Phase 16
added its own specifics; these tests own the Phase 17 boundaries:

* the timeline and the planner stay PURE, so a MotionPlan can be derived,
  hashed and disproved on a machine with no Blender at all;
* the Blender runtime never learns what a simulation is;
* the gate orchestrates subprocesses and never imports ``bpy`` itself;
* the engine-side story tool is the only Phase 17 file allowed to import
  ``living_diorama``, and it may never import Blender;
* the Phase 17 structural runner executes the LOCKED Phase 15 and Phase 16
  suites before its own, so motion can never be made to pass by weakening
  what came before it.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "visual" / "blender" / "scripts"
GATE = REPO_ROOT / "visual" / "blender" / "run_phase17_checks.py"
RUNNER = REPO_ROOT / "visual" / "blender" / "tests" / "run_blender_tests_p17.py"
STORY_TOOL = REPO_ROOT / "tools" / "phase17_motion" / "generate_motion_story.py"

PURE_MODULES = ("motion_time_spec.py", "motion_plan.py")

BLENDER_MODULES = ("apply_motion_plan.py", "produce_motion_proof.py")


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


def test_the_timeline_and_planner_never_import_blender() -> None:
    """A MotionPlan must be provable without Blender installed."""
    for name in PURE_MODULES:
        roots = imported_roots(SCRIPTS / name)
        assert "bpy" not in roots and "bmesh" not in roots, f"{name} imports Blender"


def test_the_timeline_and_planner_never_import_the_engine() -> None:
    """Motion consumes exports and specs, never simulation internals."""
    for name in PURE_MODULES:
        roots = imported_roots(SCRIPTS / name)
        assert "living_diorama" not in roots, f"{name} imports the engine"


def test_the_motion_runtime_never_imports_the_engine() -> None:
    """The engine stays unaware of Blender, and Blender of the engine."""
    for name in BLENDER_MODULES:
        roots = imported_roots(SCRIPTS / name)
        assert "living_diorama" not in roots, f"{name} imports the engine"


def test_the_motion_runtime_consumes_the_pure_plan() -> None:
    """The applier is a consumer of the plan, not a second decision-maker."""
    roots = imported_roots(SCRIPTS / "apply_motion_plan.py")
    assert "motion_plan" in roots and "motion_time_spec" in roots


def test_the_phase17_gate_never_imports_bpy() -> None:
    """The gate orchestrates Blender subprocesses; it never becomes one."""
    roots = imported_roots(GATE)
    assert "bpy" not in roots and "bmesh" not in roots


def test_the_story_tool_is_engine_side_only() -> None:
    """Producing real exports is engine work and must stay out of the visual tree."""
    roots = imported_roots(STORY_TOOL)
    assert "living_diorama" in roots, "the story must come from the real engine"
    assert "bpy" not in roots and "bmesh" not in roots


def test_no_machine_paths_in_the_phase17_layer() -> None:
    """No hard-coded drive-letter path survives into the repository."""
    for path in (
        GATE,
        RUNNER,
        STORY_TOOL,
        *(SCRIPTS / name for name in PURE_MODULES),
        *(SCRIPTS / name for name in BLENDER_MODULES),
    ):
        source = path.read_text(encoding="utf-8")
        assert "C:\\\\" not in source and "C:/Users" not in source, (
            f"{path.name} carries a machine-specific path"
        )


def test_the_phase17_runner_runs_the_locked_suites_first() -> None:
    """Phase 15, then Phase 16, then Phase 17 -- in that order, every run.

    A motion suite that ran alone could pass while quietly breaking the
    founding world, so the locked structural tests execute first and against
    the same scene the motion tests will then animate.

    The order is read out of the runner's ``SUITES`` declaration rather than
    out of file positions: the imports above it are sorted alphabetically by
    the formatter and say nothing about execution order.
    """
    assert "test_motion_time" in imported_roots(RUNNER)
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    suites = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SUITES" for target in node.targets)
    )
    declared = []
    for entry in suites.elts:
        phase = entry.elts[0].value
        declared.append((phase, [module.id for module in entry.elts[1].elts]))
    assert [phase for phase, _ in declared] == ["phase15", "phase16", "phase17"]
    assert declared[0][1] == ["test_master_scene", "test_apply_render_export"]
    assert declared[1][1] == ["test_production_world"]
    assert declared[2][1] == ["test_motion_time"]


def test_the_phase17_layer_declares_no_forbidden_scope() -> None:
    """Phase 17 is motion, not story, crowds, traffic, or a shot system."""
    forbidden = (
        "pedestrian",
        "crowd_system",
        "traffic_route",
        "story_compiler",
        "narration",
        "voiceover",
    )
    for path in (GATE, RUNNER, *(SCRIPTS / name for name in PURE_MODULES + BLENDER_MODULES)):
        source = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in source, f"{path.name} mentions out-of-scope {token}"
