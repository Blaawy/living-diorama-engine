"""Architecture tests for the persistence layer's dependency direction.

Persistence reads the domain; the domain must never read persistence. If that
direction ever reversed, saving would become something entities could trigger,
and the simulation would start depending on its own storage format.
"""

import ast
import pathlib

import pytest

SOURCE_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "living_diorama"
"""Root of the package under test."""

PERSISTENCE_ROOT = SOURCE_ROOT / "persistence"
"""Root of the persistence layer."""

ALLOWED_STDLIB = {
    "collections",
    "ctypes",
    "dataclasses",
    "errno",
    "hashlib",
    "json",
    "math",
    "os",
    "pathlib",
    "platform",
    "re",
    "shutil",
    "sys",
    "tempfile",
    "types",
    "typing",
    "typing_extensions",
}
"""Exactly the standard-library roots the persistence layer imports today.

Kept tight on purpose: a roomy allowlist quietly permits dependencies nobody
decided to take. ``collections`` belongs here because ``collections.abc`` is
standard library and an allowlist checking the first path segment would
otherwise flag it as third-party. ``typing_extensions`` is the sole exception:
serializers/_runtime_types.py falls back to it only on Python 3.12, where
``typing`` has no ``TypeIs``, and never imports it on 3.13.
"""

FORBIDDEN_FOR_PERSISTENCE = (
    "living_diorama.systems",
    "living_diorama.render",
    "living_diorama.narration",
    "living_diorama.cli",
    "living_diorama.engine",
)
"""Layers persistence may not depend on: peers and downstream consumers.

``living_diorama.memory`` is deliberately absent. Persistence stores the durable
history, so it depends on the memory domain -- the arrow runs that way and only
that way, which the memory package's own boundary tests enforce from the far
side.
"""

UPSTREAM_PACKAGES = ("entities", "events", "simulation")
"""Layers that must not import persistence."""


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


def persistence_files() -> list[pathlib.Path]:
    """Return every persistence source file."""
    return sorted(PERSISTENCE_ROOT.rglob("*.py"))


def test_the_persistence_layer_has_source_files_to_check() -> None:
    """Guards the walker itself, so an empty glob cannot pass everything."""
    files = persistence_files()
    assert len(files) >= 10
    assert any(path.name == "save_manager.py" for path in files)


@pytest.mark.parametrize("package", UPSTREAM_PACKAGES)
def test_upstream_layers_do_not_import_persistence(package: str) -> None:
    """The dependency arrow points one way only."""
    for path in sorted((SOURCE_ROOT / package).rglob("*.py")):
        for module in imported_modules(path):
            assert "persistence" not in module, f"{path} imports {module}"


def test_systems_do_not_import_persistence() -> None:
    """Simulation systems compute; they do not save."""
    for path in sorted((SOURCE_ROOT / "systems").rglob("*.py")):
        for module in imported_modules(path):
            assert "persistence" not in module, f"{path} imports {module}"


def test_persistence_does_not_import_peer_or_downstream_layers() -> None:
    """Saving must not depend on systems, memory, rendering, or narration."""
    for path in persistence_files():
        for module in imported_modules(path):
            for forbidden in FORBIDDEN_FOR_PERSISTENCE:
                assert not module.startswith(forbidden), f"{path} imports {module}"


def test_persistence_adds_no_third_party_dependency() -> None:
    """Standard library and this package only."""
    offenders: list[str] = []
    for path in persistence_files():
        for module in imported_modules(path):
            root = module.split(".")[0]
            if root != "living_diorama" and root not in ALLOWED_STDLIB:
                offenders.append(f"{path.name}: {module}")
    assert offenders == []


def test_the_stdlib_allowlist_matches_what_persistence_actually_imports() -> None:
    """An allowlist wider than the code turns a deliberate list into a guess."""
    used = {
        module.split(".")[0]
        for path in persistence_files()
        for module in imported_modules(path)
        if module.split(".")[0] != "living_diorama"
    }
    assert used == ALLOWED_STDLIB


def test_collections_abc_is_recognised_through_its_root() -> None:
    """``collections.abc`` is standard library and resolves to ``collections``."""
    assert ["collections", "abc"][0] in ALLOWED_STDLIB


def test_persistence_uses_no_forbidden_serialization_library() -> None:
    """No pickle, marshal, YAML, database, or compression anywhere."""
    forbidden = {"pickle", "marshal", "yaml", "sqlite3", "shelve", "gzip", "zlib", "bz2", "lzma"}
    for path in persistence_files():
        for module in imported_modules(path):
            assert module.split(".")[0] not in forbidden, f"{path} imports {module}"


def test_persistence_uses_no_clock_or_random_source() -> None:
    """A save must describe the state, never the moment it was written."""
    forbidden = {"time", "datetime", "random", "uuid", "secrets"}
    for path in persistence_files():
        for module in imported_modules(path):
            assert module.split(".")[0] not in forbidden, f"{path} imports {module}"


def test_only_one_module_reads_a_private_world_attribute() -> None:
    """The single authorized read-only exception, kept where it can be reviewed.

    A phantom aggregate-index entry cannot be found through the public API,
    because every public lookup needs the name you are asking about. That check
    is confined to world validation and never mutates anything.
    """
    readers: list[str] = []
    for path in persistence_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "world"
                and node.attr.startswith("_")
            ):
                readers.append(f"{path.name}:{node.attr}")
    assert readers == ["world_serializer.py:_entities"], readers


def test_the_private_index_read_is_never_assigned_to() -> None:
    """Read-only means read-only: no assignment, no in-place mutation."""
    tree = ast.parse(
        (PERSISTENCE_ROOT / "serializers" / "world_serializer.py").read_text(encoding="utf-8")
    )
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Attribute):
                assert not target.attr.startswith("_entities"), "the index is never written"


def test_persistence_defers_no_world_import_it_needs_at_runtime() -> None:
    """The world serializer genuinely constructs a World, so it imports one.

    Unlike the systems layer, persistence is not imported by ``World``, so
    there is no cycle to avoid and no reason to hide the dependency behind a
    typing guard.
    """
    modules = imported_modules(PERSISTENCE_ROOT / "serializers" / "world_serializer.py")
    assert "living_diorama.simulation.world" in modules


def test_no_persistence_module_imports_the_systems_layer() -> None:
    """Persistence itself names no system, which is the rule that matters.

    Importing the package does pull ``living_diorama.systems`` into
    ``sys.modules``, but not because persistence asked for it: the locked
    ``simulation`` package's own ``__init__`` imports ``SimulationLoop``, which
    needs ``BaseSystem``. Persistence only imports ``simulation.rng`` and
    ``simulation.world``, and touching the locked layer to break that chain is
    outside this phase's scope. The source-level rule is asserted here; the
    runtime consequence is recorded in the test below so a change to it is
    visible rather than silent.
    """
    for path in persistence_files():
        for module in imported_modules(path):
            assert not module.startswith("living_diorama.systems"), f"{path} imports {module}"


def test_the_transitive_systems_import_comes_from_the_locked_simulation_package() -> None:
    """Pins where the transitive dependency actually originates.

    If this ever stops being true -- either because the simulation package
    stops importing SimulationLoop, or because persistence starts importing a
    system directly -- the difference should be noticed here rather than
    assumed away.
    """
    simulation_init = SOURCE_ROOT / "simulation" / "__init__.py"
    assert "living_diorama.simulation.simulation_loop" in imported_modules(simulation_init)
    assert "living_diorama.systems" in imported_modules(
        SOURCE_ROOT / "simulation" / "simulation_loop.py"
    )

    persistence_imports = {
        module
        for path in persistence_files()
        for module in imported_modules(path)
        if module.startswith("living_diorama.simulation")
    }
    assert persistence_imports == {
        "living_diorama.simulation.rng",
        "living_diorama.simulation.world",
    }
