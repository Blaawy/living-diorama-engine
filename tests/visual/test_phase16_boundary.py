"""Import-boundary and ownership guards for the Phase 16 layer.

The Phase 15 boundary tests already sweep every file under
``visual/blender`` for engine imports; these tests add the Phase 16
specifics: the pure planning modules stay pure (no ``bpy``), the Phase 16
gate stays orchestration-only, and no machine-specific path sneaks into the
repository.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "visual" / "blender" / "scripts"
GATE = REPO_ROOT / "visual" / "blender" / "run_phase16_checks.py"

PURE_MODULES = (
    "production_spec.py",
    "road_graph.py",
    "urban_fabric.py",
    "city_ground.py",
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


def test_planning_modules_never_import_blender() -> None:
    """The road graph and fabric plan stay provable without Blender."""
    for name in PURE_MODULES:
        roots = imported_roots(SCRIPTS / name)
        assert "bpy" not in roots and "bmesh" not in roots, f"{name} imports Blender"


def test_planning_modules_never_import_the_engine() -> None:
    """The production plan consumes specs, never simulation internals."""
    for name in PURE_MODULES:
        roots = imported_roots(SCRIPTS / name)
        assert "living_diorama" not in roots, f"{name} imports the engine"


def test_phase16_gate_never_imports_bpy() -> None:
    """The gate orchestrates Blender subprocesses, never bpy itself."""
    roots = imported_roots(GATE)
    assert "bpy" not in roots and "bmesh" not in roots


def test_no_machine_paths_in_the_phase16_layer() -> None:
    """No hard-coded drive-letter path survives into the repository."""
    for path in (
        GATE,
        *(SCRIPTS / name for name in PURE_MODULES),
        SCRIPTS / "build_production_world.py",
        SCRIPTS / "produce_production_world_proof.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert "C:\\\\" not in source and "C:/Users" not in source, (
            f"{path.name} carries a machine-specific path"
        )


def test_production_builder_consumes_the_plan_only() -> None:
    """The Blender builder imports the pure planners, not the engine."""
    for name in ("build_production_world.py", "produce_production_world_proof.py"):
        roots = imported_roots(SCRIPTS / name)
        assert "living_diorama" not in roots, f"{name} imports the engine"
        assert "road_graph" in roots or "urban_fabric" in roots or "production_spec" in roots
