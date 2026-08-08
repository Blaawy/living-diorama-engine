"""Directory-ownership and import-boundary guards for the Blender layer.

The conceptual boundary of Phase 15 is: the Blender runtime under
``visual/blender/`` consumes only Render Export V1 documents. Engine-side
tooling (the real proof-story generator, which legitimately imports the
locked engine) lives under ``tools/phase15_proof/`` instead. These tests
prove both directions of that ownership split with the AST, not with
conventions.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
VISUAL_BLENDER = REPO_ROOT / "visual" / "blender"
PROOF_TOOL = REPO_ROOT / "tools" / "phase15_proof" / "generate_proof_exports.py"


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


def visual_python_files() -> list[Path]:
    """Every Python file in the Blender runtime tree."""
    files = sorted(VISUAL_BLENDER.rglob("*.py"))
    assert files, "the visual/blender tree holds no Python files"
    return files


def test_blender_runtime_never_imports_the_engine() -> None:
    """No file under visual/blender imports living_diorama.

    The Blender layer is downstream of Render Export V1 only; an engine
    import here would collapse the simulation/visual boundary.
    """
    for path in visual_python_files():
        assert "living_diorama" not in imported_roots(path), (
            f"{path.relative_to(REPO_ROOT)} imports the engine; the Blender "
            "runtime consumes Render Export documents only"
        )


def test_proof_generator_lives_under_tools() -> None:
    """The engine-side proof generator sits outside the Blender runtime tree."""
    assert PROOF_TOOL.is_file(), "tools/phase15_proof/generate_proof_exports.py is missing"
    strays = [path for path in visual_python_files() if path.name == "generate_proof_exports.py"]
    assert strays == [], f"proof generator also present in visual/blender: {strays}"


def test_proof_generator_uses_only_public_engine_api() -> None:
    """The proof generator composes public living_diorama packages only.

    It builds the real three-episode story, so it imports the engine -- but
    never private modules, so the locked internals stay sealed.
    """
    roots = imported_roots(PROOF_TOOL)
    assert "living_diorama" in roots, "the proof generator must drive the real engine"
    tree = ast.parse(PROOF_TOOL.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            parts = node.module.split(".")
            if parts[0] != "living_diorama":
                continue
            assert not any(part.startswith("_") for part in parts), (
                f"private engine module imported: {node.module}"
            )
            for alias in node.names:
                assert not alias.name.startswith("_"), (
                    f"private engine name imported: {node.module}.{alias.name}"
                )


def test_pure_contract_module_never_imports_bpy() -> None:
    """scene_spec stays importable without Blender installed."""
    roots = imported_roots(VISUAL_BLENDER / "scripts" / "scene_spec.py")
    assert "bpy" not in roots and "bmesh" not in roots


def test_gate_script_never_imports_bpy() -> None:
    """The local gate orchestrates Blender subprocesses, never bpy itself."""
    roots = imported_roots(VISUAL_BLENDER / "run_phase15_checks.py")
    assert "bpy" not in roots and "bmesh" not in roots
