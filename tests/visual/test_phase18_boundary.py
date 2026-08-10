"""Import-boundary and ownership guards for the Phase 18 population layer.

Phase 15 already sweeps ``visual/blender`` for engine imports, and Phases 16
and 17 added their own specifics; these tests own the Phase 18 boundaries:

* the spec, the topology, the planner and the package verifier stay PURE, so
  a presence plan can be derived, hashed and disproved -- and a delivered
  proof package re-verified -- on a machine with no Blender at all;
* the Blender runtime never learns what a simulation is;
* the builder consumes the pure plan rather than deciding anything itself;
* the gate orchestrates subprocesses and never imports ``bpy``;
* the Phase 18 structural runner executes the LOCKED Phase 15, 16 and 17
  suites before its own, so presence can never be made to pass by weakening
  what came before it;
* and Phase 18 declares none of the scope it was explicitly told not to build.
"""

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "visual" / "blender" / "scripts"
GATE = REPO_ROOT / "visual" / "blender" / "run_phase18_checks.py"
RUNNER = REPO_ROOT / "visual" / "blender" / "tests" / "run_blender_tests_p18.py"
CONFIG = REPO_ROOT / "visual" / "blender" / "config" / "population_presence_v1.json"

PURE_MODULES = (
    "figure_kit.py",
    "population_presence_spec.py",
    "pedestrian_topology.py",
    "population_presence_plan.py",
    "population_proof_package.py",
)

BLENDER_MODULES = (
    "apply_population_presence.py",
    "produce_population_presence_proof.py",
    "produce_population_style_plate.py",
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


def test_the_presence_layer_planning_never_imports_blender() -> None:
    """A presence plan must be provable without Blender installed."""
    for name in PURE_MODULES:
        roots = imported_roots(SCRIPTS / name)
        assert "bpy" not in roots and "bmesh" not in roots, f"{name} imports Blender"


def test_the_presence_layer_planning_never_imports_the_engine() -> None:
    """Presence consumes exports and specs, never simulation internals."""
    for name in PURE_MODULES:
        roots = imported_roots(SCRIPTS / name)
        assert "living_diorama" not in roots, f"{name} imports the engine"


def test_the_population_runtime_never_imports_the_engine() -> None:
    """The engine stays unaware of Blender, and Blender of the engine."""
    for name in BLENDER_MODULES:
        roots = imported_roots(SCRIPTS / name)
        assert "living_diorama" not in roots, f"{name} imports the engine"


def test_the_builder_consumes_the_pure_plan() -> None:
    """The applier is a consumer of the plan, not a second decision-maker."""
    roots = imported_roots(SCRIPTS / "apply_population_presence.py")
    assert "population_presence_plan" in roots
    assert "figure_kit" in roots, "the builder consumes the kit, it does not redefine bodies"
    assert "pedestrian_topology" not in roots, (
        "the builder must not be able to decide where anybody stands"
    )


def test_the_phase18_gate_never_imports_bpy() -> None:
    """The gate orchestrates Blender subprocesses; it never becomes one."""
    roots = imported_roots(GATE)
    assert "bpy" not in roots and "bmesh" not in roots


DRIVE_LETTER_PATH = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]")
"""Any Windows drive-letter path, in every form source can spell one.

Deliberately stronger than a substring scan for ``C:\\\\``. That form only
appears in a NON-raw string literal with escaped separators; a raw string
``r"C:\\Users\\..."`` or a forward-slash path ``"C:/Work/..."`` carries a
single separator and slips straight past it. This machine writes paths in
exactly those two forms, so the weaker guard would have been decorative here.
"""


def test_no_machine_paths_in_the_phase18_layer() -> None:
    """No hard-coded drive-letter path survives into the repository."""
    for path in (
        GATE,
        RUNNER,
        REPO_ROOT / "visual" / "blender" / "tests" / "test_population_presence.py",
        CONFIG,
        *(SCRIPTS / name for name in PURE_MODULES),
        *(SCRIPTS / name for name in BLENDER_MODULES),
    ):
        source = path.read_text(encoding="utf-8")
        found = DRIVE_LETTER_PATH.search(source)
        assert found is None, (
            f"{path.name} carries a machine-specific path at offset {found.start()}: "
            f"{source[found.start() : found.start() + 60]!r}"
        )


def test_the_machine_path_guard_can_actually_fail() -> None:
    """Proven, not assumed: every spelling this machine produces is caught."""
    for spelling in (
        r'BLENDER = r"C:\Users\someone\blender.exe"',
        'BLENDER = "C:/Users/someone/blender.exe"',
        'BLENDER = "C:\\\\Users\\\\someone\\\\blender.exe"',
        'WORKSPACE = "D:/scratch"',
    ):
        assert DRIVE_LETTER_PATH.search(spelling), f"the guard missed {spelling!r}"
    for innocent in (
        "ratio = a/b",
        'label = "phase18: 80 proxies"',
        "value = spec['density']",
        "https://example.invalid/docs",
    ):
        assert DRIVE_LETTER_PATH.search(innocent) is None, f"the guard flagged {innocent!r}"


def test_the_phase18_runner_runs_the_locked_suites_first() -> None:
    """Phase 15, 16, 17, then Phase 18 -- in that order, every run.

    A presence suite that ran alone could pass while quietly breaking the
    founding world, the production city, or the motion layer, so the locked
    structural tests execute first and against the same scene.

    The order is read out of the runner's ``SUITES`` declaration rather than
    out of file positions: the imports above it are sorted alphabetically by
    the formatter and say nothing about execution order.
    """
    assert "test_population_presence" in imported_roots(RUNNER)
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
    assert [phase for phase, _ in declared] == ["phase15", "phase16", "phase17", "phase18"]
    assert declared[0][1] == ["test_master_scene", "test_apply_render_export"]
    assert declared[1][1] == ["test_production_world"]
    assert declared[2][1] == ["test_motion_time"]
    assert declared[3][1] == ["test_population_presence"]
    executed = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.For)
        and isinstance(node.iter, ast.Name)
        and node.iter.id == "SUITES"
    ]
    assert executed, (
        "the runner must iterate SUITES directly; wrapping it in reversed() or sorted() "
        "would leave this declaration intact while running the phases in another order"
    )


FORBIDDEN_SCOPE = (
    "walk_cycle",
    "crowd_simulation",
    "route_plan",
    "commute",
    "traffic",
    "vehicle",
    "schedule",
    "npc_ai",
    "pedestrian_ai",
    "dialogue",
    "personality",
    "citizen_identity",
    "migration_ai",
)
"""Everything the directive explicitly placed outside Phase 18."""


def _is_documentation(node: ast.stmt) -> bool:
    """True for a bare string statement: a module, class, function or attribute docstring."""
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def strip_documentation(tree: ast.AST) -> ast.AST:
    """Drop every bare string statement, wherever it appears.

    Not just the first statement of a module or a def: this codebase documents
    module-level constants with a string literal placed AFTER the assignment,
    and those attribute docstrings are prose too. A stripper that only removed
    the leading one would leave most of the project's documentation in place
    and turn the scope guard back into a text search.
    """
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        kept = [statement for statement in body if not _is_documentation(statement)]
        node.body = kept or [ast.Pass()]
    return ast.fix_missing_locations(tree)


def code_only(path: Path) -> str:
    """One file's source with every docstring and comment removed.

    The scope guard has to read CODE, not prose. The Phase 18 modules
    deliberately SAY what they do not do -- "no proxy has a home, a
    destination, a schedule" is the honest statement of the non-goals, and a
    plain text scan would forbid the project from writing it down. Comments
    never reach the AST, and docstrings are dropped here, so what is left is
    what the layer actually implements.
    """
    return ast.unparse(strip_documentation(ast.parse(path.read_text(encoding="utf-8")))).lower()


def test_the_phase18_layer_implements_no_forbidden_scope() -> None:
    """Phase 18 is visible presence, not daily life.

    Presence answers where people ARE. Nothing here may answer where they are
    going, who they are, or what they do next -- shipping any of it would
    claim more simulation than the world actually has.
    """
    for path in (
        GATE,
        RUNNER,
        *(SCRIPTS / name for name in PURE_MODULES + BLENDER_MODULES),
    ):
        source = code_only(path)
        for token in FORBIDDEN_SCOPE:
            assert token not in source, f"{path.name} implements out-of-scope {token}"


def test_the_scope_guard_can_actually_fail() -> None:
    """The guard is proven, not assumed.

    A stripper that removed too much would silently pass everything forever,
    so this feeds it a file that genuinely declares forbidden scope and
    requires the tokens to survive -- while the prose saying the same words,
    in all three of the shapes this codebase writes documentation in, does
    not.
    """
    guilty = ast.parse(
        '"""No schedule here."""\n'
        "\n"
        "LIMIT = 3\n"
        '"""An attribute docstring mentioning traffic."""\n'
        "\n"
        "def plan_commute(vehicle):\n"
        '    """A function docstring mentioning a vehicle."""\n'
        "    return vehicle\n"
    )
    stripped = ast.unparse(strip_documentation(guilty)).lower()
    assert "commute" in stripped, "the stripper ate real code"
    assert "vehicle" in stripped
    assert "no schedule here" not in stripped
    assert "attribute docstring" not in stripped
    assert "function docstring" not in stripped


def test_the_presence_layer_owns_only_additive_paths() -> None:
    """Every Phase 18 file this suite guards exists where it was declared."""
    for path in (
        GATE,
        RUNNER,
        CONFIG,
        REPO_ROOT / "docs" / "population_presence.md",
        REPO_ROOT / "visual" / "blender" / "tests" / "test_population_presence.py",
        *(SCRIPTS / name for name in PURE_MODULES + BLENDER_MODULES),
    ):
        assert path.exists(), f"{path} is missing from the Phase 18 layer"


def test_the_population_layer_keeps_out_of_the_locked_material_family() -> None:
    """Phase 18 materials carry their own prefix.

    The Phase 16 structural suite proves the ``LD_MAT__`` family is unchanged
    by later work. A population material named into that family would break a
    locked test from the outside, so the prefix is pinned here too.
    """
    source = (SCRIPTS / "apply_population_presence.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    prefix = next(
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "MATERIAL_PREFIX"
            for target in node.targets
        )
    )
    assert prefix == "LD_POP_MAT__"
    assert not prefix.startswith("LD_MAT__")


def test_the_phase18_package_verifier_reuses_the_locked_generic_helpers() -> None:
    """The sibling package module extends Phase 17, it does not fork it."""
    roots = imported_roots(SCRIPTS / "population_proof_package.py")
    assert "proof_package" in roots, "the Phase 18 verifier must reuse the locked helpers"
    assert "manifest_io" in roots
