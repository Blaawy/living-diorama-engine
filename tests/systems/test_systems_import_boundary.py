"""Architectural tests for the systems and simulation layers.

The most delicate rule in this phase: ``systems`` must not depend on
``simulation`` at runtime, because ``simulation`` depends on ``systems`` for the
loop. BaseSystem still needs the ``World`` type for its signature, so the import
is deferred behind ``TYPE_CHECKING``. These tests assert that arrangement holds,
rather than trusting that nobody will later "tidy up" the import.
"""

import ast
from pathlib import Path

import living_diorama.simulation
import living_diorama.systems

SYSTEMS_DIR = Path(living_diorama.systems.__file__).parent
SIMULATION_DIR = Path(living_diorama.simulation.__file__).parent

FORBIDDEN_DOWNSTREAM = (
    "living_diorama.persistence",
    "living_diorama.memory",
    "living_diorama.render",
    "living_diorama.narration",
    "living_diorama.cli",
)


def _split_imports(source: str) -> tuple[list[str], list[str]]:
    """Return (runtime, type_checking_only) absolute module names imported."""
    tree = ast.parse(source)
    type_checking_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            is_guard = (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
                isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
            )
            if is_guard:
                for inner in ast.walk(node):
                    type_checking_nodes.add(id(inner))

    runtime: list[str] = []
    deferred: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            continue
        (deferred if id(node) in type_checking_nodes else runtime).extend(names)
    return runtime, deferred


def test_systems_do_not_import_simulation_at_runtime() -> None:
    """A runtime import here would create a systems <-> simulation cycle."""
    offenders: list[str] = []
    for path in sorted(SYSTEMS_DIR.glob("*.py")):
        runtime, _ = _split_imports(path.read_text(encoding="utf-8"))
        offenders.extend(
            f"{path.name} imports {module}"
            for module in runtime
            if module.startswith("living_diorama.simulation")
        )
    assert offenders == []


def test_base_system_defers_the_world_import_for_typing() -> None:
    """The World type is still available to type checkers, just not at runtime."""
    _, deferred = _split_imports((SYSTEMS_DIR / "base_system.py").read_text(encoding="utf-8"))
    assert any(module.startswith("living_diorama.simulation") for module in deferred)


def test_systems_do_not_import_downstream_packages() -> None:
    """Systems know about entities and events, and nothing further along."""
    offenders: list[str] = []
    for path in sorted(SYSTEMS_DIR.glob("*.py")):
        runtime, deferred = _split_imports(path.read_text(encoding="utf-8"))
        offenders.extend(
            f"{path.name} imports {module}"
            for module in runtime + deferred
            if module.startswith(FORBIDDEN_DOWNSTREAM)
        )
    assert offenders == []


def test_simulation_does_not_import_downstream_packages() -> None:
    """The simulation layer must not reach into persistence, memory, or output."""
    offenders: list[str] = []
    for path in sorted(SIMULATION_DIR.glob("*.py")):
        runtime, deferred = _split_imports(path.read_text(encoding="utf-8"))
        offenders.extend(
            f"{path.name} imports {module}"
            for module in runtime + deferred
            if module.startswith(FORBIDDEN_DOWNSTREAM)
        )
    assert offenders == []


def test_world_imports_no_third_party_packages() -> None:
    """The engine has no runtime dependencies, and World must not add one."""
    allowed_stdlib = {"collections", "types", "typing"}
    runtime, deferred = _split_imports((SIMULATION_DIR / "world.py").read_text(encoding="utf-8"))
    offenders = [
        module
        for module in runtime + deferred
        if module.split(".")[0] != "living_diorama" and module.split(".")[0] not in allowed_stdlib
    ]
    assert offenders == []


def test_world_does_not_perform_io() -> None:
    """World holds state; reading and writing files belongs to persistence."""
    source = (SIMULATION_DIR / "world.py").read_text(encoding="utf-8")
    for forbidden in ("open(", "json", "Path(", "EventBus"):
        assert forbidden not in source, f"world.py must not reference {forbidden!r}"


def test_layers_were_actually_scanned() -> None:
    """Guard against these boundary tests passing on an empty file list."""
    assert len(list(SYSTEMS_DIR.glob("*.py"))) >= 2
    assert len(list(SIMULATION_DIR.glob("*.py"))) >= 4


def test_package_exports() -> None:
    """Both packages expose exactly their intended public API.

    The systems set grows as each phase adds a stage to the pipeline; it is
    asserted exactly so that an accidental export is caught, and updated
    deliberately when a phase genuinely adds one.
    """
    assert set(living_diorama.systems.__all__) == {
        "BaseSystem",
        "ConsumptionSystem",
        "MigrationSystem",
        "ProductionSystem",
        "ResourceFlowSystem",
        "ScarcitySystem",
    }
    assert set(living_diorama.simulation.__all__) == {
        "DeterministicRNG",
        "SimulationLoop",
        "World",
    }
    for name in living_diorama.simulation.__all__:
        assert hasattr(living_diorama.simulation, name)


def test_phase_four_systems_are_importable_from_the_package() -> None:
    """The pipeline stages are reachable through the package's public surface."""
    from living_diorama.systems import (  # noqa: PLC0415
        BaseSystem,
        ConsumptionSystem,
        ProductionSystem,
        ResourceFlowSystem,
    )

    for system_type in (BaseSystem, ConsumptionSystem, ProductionSystem, ResourceFlowSystem):
        assert isinstance(system_type, type)
    for system_type in (ConsumptionSystem, ProductionSystem, ResourceFlowSystem):
        assert issubclass(system_type, BaseSystem)


def test_private_resource_config_is_not_exported() -> None:
    """Shared validation is an implementation detail of the systems package."""
    assert "_resource_config" not in living_diorama.systems.__all__
    assert not any(name.startswith("_") for name in living_diorama.systems.__all__)


def test_entity_and_event_layers_do_not_import_systems() -> None:
    """Dependencies point inward: the layers below must not know systems exist."""
    import living_diorama.entities  # noqa: PLC0415
    import living_diorama.events  # noqa: PLC0415

    for package in (living_diorama.entities, living_diorama.events):
        directory = Path(package.__file__).parent
        for path in sorted(directory.glob("*.py")):
            runtime, deferred = _split_imports(path.read_text(encoding="utf-8"))
            offenders = [
                module
                for module in runtime + deferred
                if module.startswith("living_diorama.systems")
            ]
            assert offenders == [], f"{path.name} imports {offenders}"


def test_every_systems_module_defers_its_world_import() -> None:
    """Every system needs the World type but none may depend on simulation at runtime."""
    for path in sorted(SYSTEMS_DIR.glob("*.py")):
        runtime, _ = _split_imports(path.read_text(encoding="utf-8"))
        assert not any(module.startswith("living_diorama.simulation") for module in runtime)
