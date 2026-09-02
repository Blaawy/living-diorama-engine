"""Architecture tests for the memory layer's dependency direction.

Memory decides what is worth remembering; persistence stores the result. The
arrow runs one way. If it ever reversed, deciding significance would become
something the save layer could influence, and no test could then tell a recorded
fact from an invented one.
"""

import ast
import pathlib

import pytest

SOURCE_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "living_diorama"
"""Root of the package under test."""

MEMORY_ROOT = SOURCE_ROOT / "memory"
"""Root of the memory layer."""

ALLOWED_STDLIB = {
    "collections",
    "dataclasses",
    "enum",
    "hashlib",
    "json",
    "math",
    "types",
    "typing",
    "typing_extensions",
}
"""Exactly the standard-library roots the memory layer imports today.

Kept tight on purpose: a roomy allowlist quietly permits dependencies nobody
decided to take. ``collections`` belongs here because ``collections.abc`` is
standard library and an allowlist checking the first path segment would
otherwise flag it as third-party. ``typing_extensions`` is the sole exception:
world_memory.py falls back to it only on Python 3.12, where ``typing`` has no
``TypeIs``, and never imports it on 3.13.
"""

FORBIDDEN_FOR_MEMORY = (
    "living_diorama.persistence",
    "living_diorama.systems",
    "living_diorama.cli",
    "living_diorama.render",
    "living_diorama.narration",
    "living_diorama.engine",
)
"""Layers memory may not depend on."""

MUST_NOT_IMPORT_MEMORY = ("entities", "events", "systems", "simulation")
"""Layers that must not import memory."""


def imported_modules(path: pathlib.Path) -> list[str]:
    """Return every module name imported by one source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
    return modules


def memory_files() -> list[pathlib.Path]:
    """Return every memory source file."""
    return sorted(MEMORY_ROOT.rglob("*.py"))


def test_the_memory_layer_has_source_files_to_check() -> None:
    """Guards the walker itself, so an empty glob cannot pass everything."""
    names = {path.name for path in memory_files()}
    assert {"world_memory.py", "memory_significance.py", "memory_query.py"} <= names


def test_memory_does_not_import_persistence_or_downstream_layers() -> None:
    """The rule that keeps significance out of the save layer."""
    for path in memory_files():
        for module in imported_modules(path):
            for forbidden in FORBIDDEN_FOR_MEMORY:
                assert not module.startswith(forbidden), f"{path.name} imports {module}"


@pytest.mark.parametrize("package", MUST_NOT_IMPORT_MEMORY)
def test_upstream_layers_do_not_import_memory(package: str) -> None:
    """Memory reads them; none of them may read memory."""
    for path in sorted((SOURCE_ROOT / package).rglob("*.py")):
        for module in imported_modules(path):
            assert "living_diorama.memory" not in module, f"{path} imports {module}"


def test_memory_adds_no_third_party_dependency() -> None:
    """Standard library and this package only."""
    offenders = [
        f"{path.name}: {module}"
        for path in memory_files()
        for module in imported_modules(path)
        if module.split(".")[0] != "living_diorama" and module.split(".")[0] not in ALLOWED_STDLIB
    ]
    assert offenders == []


def test_the_stdlib_allowlist_matches_what_memory_actually_imports() -> None:
    """An allowlist wider than the code turns a deliberate list into a guess."""
    used = {
        module.split(".")[0]
        for path in memory_files()
        for module in imported_modules(path)
        if module.split(".")[0] != "living_diorama"
    }
    assert used == ALLOWED_STDLIB


def test_collections_abc_is_recognised_through_its_root() -> None:
    """``collections.abc`` is standard library, not a third-party package."""
    assert "collections" in ALLOWED_STDLIB


def test_memory_uses_no_clock_random_or_identifier_source() -> None:
    """A fact must describe the world, never the moment it was distilled."""
    forbidden = {"time", "datetime", "random", "uuid", "secrets", "os", "pathlib", "socket"}
    for path in memory_files():
        for module in imported_modules(path):
            assert module.split(".")[0] not in forbidden, f"{path.name} imports {module}"


def test_memory_implements_its_own_json_encoding() -> None:
    """Fact identity must not depend on a layer memory may not import.

    Borrowing the persistence codec would make a fact's identifier shift if the
    save format ever changed its framing -- and would invert the dependency.
    Checked through the imports rather than the raw text, so a docstring
    explaining the rule does not read as a violation of it.
    """
    source = (MEMORY_ROOT / "world_memory.py").read_text(encoding="utf-8")
    assert "json.dumps" in source
    assert "json" in imported_modules(MEMORY_ROOT / "world_memory.py")
    for module in imported_modules(MEMORY_ROOT / "world_memory.py"):
        assert "persistence" not in module


def test_persistence_may_import_memory() -> None:
    """The permitted direction, asserted so a future change is deliberate."""
    imports = {
        module
        for path in sorted((SOURCE_ROOT / "persistence").rglob("*.py"))
        for module in imported_modules(path)
    }
    assert any(module.startswith("living_diorama.memory") for module in imports)


def test_no_source_module_imports_pytest_or_a_test_helper() -> None:
    """Production code must not depend on the tests that exercise it."""
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        for module in imported_modules(path):
            root = module.split(".")[0]
            assert root != "pytest", f"{path} imports pytest"
            assert root not in {"conftest", "tests"}, f"{path} imports {module}"


def test_importing_memory_creates_nothing_and_loads_no_persistence() -> None:
    """Importing the package must not write, save, or reach the storage layer."""
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    script = (
        "import sys, pathlib;"
        f"sys.path.insert(0, {str(SOURCE_ROOT.parent)!r});"
        "before = set(pathlib.Path('.').iterdir());"
        "import living_diorama.memory;"
        "after = set(pathlib.Path('.').iterdir());"
        "print(before == after, "
        "any(n.startswith('living_diorama.persistence') for n in sys.modules))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert completed.stdout.split() == ["True", "False"]


def test_the_transitive_systems_import_comes_from_the_locked_simulation_package() -> None:
    """Memory names no system; the chain runs through a locked package.

    Importing memory does pull ``living_diorama.systems`` into ``sys.modules``,
    but not because memory asked for it: memory imports
    ``simulation.world``, and the locked ``simulation`` package's own
    ``__init__`` imports ``SimulationLoop``, which needs ``BaseSystem``.
    Touching the locked layer to break that chain is outside this phase's scope.
    The source-level rule is asserted above; the runtime consequence is pinned
    here so a change to it is visible rather than assumed away.
    """
    simulation_init = SOURCE_ROOT / "simulation" / "__init__.py"
    assert "living_diorama.simulation.simulation_loop" in imported_modules(simulation_init)
    assert "living_diorama.systems" in imported_modules(
        SOURCE_ROOT / "simulation" / "simulation_loop.py"
    )

    memory_imports = {
        module
        for path in memory_files()
        for module in imported_modules(path)
        if module.startswith("living_diorama.simulation")
    }
    assert memory_imports == {"living_diorama.simulation.world"}


def test_only_one_module_reads_a_private_world_attribute() -> None:
    """The single authorized read-only exception, kept where it can be reviewed.

    A non-exact aggregate-index key cannot be found through the public API: every
    public lookup takes the identifier you are asking about, so a subclass key
    stored in the index answers all of them exactly as a plain string would. The
    key has to be inspected as itself, which means reading the index.
    """
    readers: list[str] = []
    for path in memory_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "world"
                and node.attr.startswith("_")
            ):
                readers.append(f"{path.name}:{node.attr}")
    assert readers == ["_integrity.py:_entities"], readers


def test_the_private_index_is_never_written() -> None:
    """Read-only means read-only: no assignment, no in-place mutation."""
    tree = ast.parse((MEMORY_ROOT / "_integrity.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Attribute):
                assert not target.attr.startswith("_entities"), "the index is never written"


AUDITED_FOR_DIRECT_ISINSTANCE = (
    *sorted(MEMORY_ROOT.glob("*.py")),
    SOURCE_ROOT / "persistence" / "save_manager.py",
    SOURCE_ROOT / "persistence" / "serializers" / "world_memory_serializer.py",
)
"""Phase 11 production files that must not call built-in ``isinstance`` directly."""


def test_the_audited_phase11_files_never_call_isinstance_directly() -> None:
    """Type validation must not consult a caller-controlled ``__class__``.

    When its fast path fails, ``isinstance`` may read the instance's
    ``__class__`` attribute, executing code owned by the very object under
    validation. The audited Phase 11 files decide type through the safe
    runtime-type helper instead. Only real AST calls count, so a mention in a
    comment, docstring, or string does not trip the guard. Ruff and mypy
    remain the source of truth for style and typing.
    """
    offenders: list[str] = []
    for path in AUDITED_FOR_DIRECT_ISINSTANCE:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "isinstance"
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []
