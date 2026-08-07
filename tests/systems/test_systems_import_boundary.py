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
        "BoundaryDecisionSystem",
        "ConsumptionSystem",
        "InfrastructureAdaptationSystem",
        "InstitutionalPressureSystem",
        "MigrationSystem",
        "ProductionSystem",
        "ResourceFlowSystem",
        "RuleSystem",
        "ScarcitySystem",
        "ScheduledLawChange",
        "ScheduledLawRestore",
        "SocialStabilitySystem",
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


def test_social_stability_system_imports_only_permitted_layers() -> None:
    """The Phase 6 system depends on entities, events, and shared helpers only.

    It must not import another concrete system, nor anything downstream, nor
    any later-phase module. Its only knowledge of ``World`` is a deferred
    typing import, the same arrangement every other system uses.
    """
    path = SYSTEMS_DIR / "social_stability_system.py"
    runtime, deferred = _split_imports(path.read_text(encoding="utf-8"))

    assert not any(module.startswith("living_diorama.simulation") for module in runtime)
    assert any(module.startswith("living_diorama.simulation") for module in deferred)

    for module in runtime + deferred:
        assert not module.startswith(FORBIDDEN_DOWNSTREAM), module

    concrete_systems = (
        "production_system",
        "consumption_system",
        "resource_flow_system",
        "migration_system",
        "scarcity_system",
    )
    for module in runtime + deferred:
        assert not any(name in module for name in concrete_systems), module


def test_social_stability_system_adds_no_third_party_dependency() -> None:
    """The engine has no runtime dependencies, and Phase 6 must not add one."""
    allowed_stdlib = {"collections", "dataclasses", "enum", "math", "types", "typing"}
    path = SYSTEMS_DIR / "social_stability_system.py"
    runtime, deferred = _split_imports(path.read_text(encoding="utf-8"))

    offenders = [
        module
        for module in runtime + deferred
        if module.split(".")[0] != "living_diorama" and module.split(".")[0] not in allowed_stdlib
    ]
    assert offenders == []


def test_social_stability_system_is_exported_like_every_other_system() -> None:
    """Public export follows the existing convention exactly."""
    from living_diorama.systems import BaseSystem, SocialStabilitySystem  # noqa: PLC0415

    assert issubclass(SocialStabilitySystem, BaseSystem)
    assert "SocialStabilitySystem" in living_diorama.systems.__all__
    assert not any(name.startswith("_") for name in living_diorama.systems.__all__)


def test_institutional_pressure_system_imports_only_permitted_layers() -> None:
    """The Phase 7 system depends on entities, events, and shared helpers only.

    It must not import another concrete system -- least of all the social system
    whose output it consumes, since reading a value off the world is the only
    sanctioned way for one system's work to reach another.
    """
    path = SYSTEMS_DIR / "institutional_pressure_system.py"
    runtime, deferred = _split_imports(path.read_text(encoding="utf-8"))

    assert not any(module.startswith("living_diorama.simulation") for module in runtime)
    assert any(module.startswith("living_diorama.simulation") for module in deferred)

    for module in runtime + deferred:
        assert not module.startswith(FORBIDDEN_DOWNSTREAM), module

    concrete_systems = (
        "production_system",
        "consumption_system",
        "resource_flow_system",
        "migration_system",
        "scarcity_system",
        "social_stability_system",
    )
    for module in runtime + deferred:
        assert not any(name in module for name in concrete_systems), module


def test_institutional_pressure_system_adds_no_third_party_dependency() -> None:
    """The engine has no runtime dependencies, and Phase 7 must not add one."""
    allowed_stdlib = {"collections", "dataclasses", "enum", "math", "types", "typing"}
    path = SYSTEMS_DIR / "institutional_pressure_system.py"
    runtime, deferred = _split_imports(path.read_text(encoding="utf-8"))

    offenders = [
        module
        for module in runtime + deferred
        if module.split(".")[0] != "living_diorama" and module.split(".")[0] not in allowed_stdlib
    ]
    assert offenders == []


def test_institutional_pressure_system_is_exported_like_every_other_system() -> None:
    """Public export follows the existing convention, and no helper leaks out."""
    from living_diorama.systems import BaseSystem, InstitutionalPressureSystem  # noqa: PLC0415

    assert issubclass(InstitutionalPressureSystem, BaseSystem)
    assert "InstitutionalPressureSystem" in living_diorama.systems.__all__
    assert not any(name.startswith("_") for name in living_diorama.systems.__all__)
    assert "_clamp_unit" not in living_diorama.systems.__all__


def test_phase_seven_does_not_borrow_the_phase_six_private_helper() -> None:
    """Each concrete system owns its own numeric guard.

    The two strict unit bounds are deliberately separate copies. Sharing one
    through an import would be a dependency between concrete systems wearing a
    different hat, and would make a future change to one silently change the
    other.
    """
    source = (SYSTEMS_DIR / "institutional_pressure_system.py").read_text(encoding="utf-8")
    assert "social_stability_system" not in source


def test_boundary_decision_system_imports_only_permitted_layers() -> None:
    """The Phase 8 system depends on entities, events, and shared helpers only.

    It reads institutional pressure off the district, not from the system that
    wrote it, so it must not import that system. Its only knowledge of
    ``World`` is a deferred typing import, as everywhere else.
    """
    path = SYSTEMS_DIR / "boundary_decision_system.py"
    runtime, deferred = _split_imports(path.read_text(encoding="utf-8"))

    assert not any(module.startswith("living_diorama.simulation") for module in runtime)
    assert any(module.startswith("living_diorama.simulation") for module in deferred)

    for module in runtime + deferred:
        assert not module.startswith(FORBIDDEN_DOWNSTREAM), module

    concrete_systems = (
        "production_system",
        "consumption_system",
        "resource_flow_system",
        "migration_system",
        "scarcity_system",
        "social_stability_system",
        "institutional_pressure_system",
    )
    for module in runtime + deferred:
        assert not any(name in module for name in concrete_systems), module


def test_boundary_decision_system_does_not_import_topology() -> None:
    """Parallel boundaries are decided individually, so no topology view is used.

    ``_topology`` collapses parallel routes for movement purposes. Phase 8
    decides per physical boundary, and borrowing that view would silently make
    two parallel boundaries share one decision.
    """
    path = SYSTEMS_DIR / "boundary_decision_system.py"
    runtime, deferred = _split_imports(path.read_text(encoding="utf-8"))

    for module in runtime + deferred:
        assert "_topology" not in module, module
        assert "_flow_allocation" not in module, module
        assert "_resource_config" not in module, module


def test_boundary_decision_system_adds_no_third_party_dependency() -> None:
    """The engine has no runtime dependencies, and Phase 8 must not add one."""
    allowed_stdlib = {"collections", "dataclasses", "typing"}
    path = SYSTEMS_DIR / "boundary_decision_system.py"
    runtime, deferred = _split_imports(path.read_text(encoding="utf-8"))

    offenders = [
        module
        for module in runtime + deferred
        if module.split(".")[0] != "living_diorama" and module.split(".")[0] not in allowed_stdlib
    ]
    assert offenders == []


def test_boundary_decision_system_uses_no_randomness() -> None:
    """Wall identifiers are derived, never drawn; nothing here may import random."""
    path = SYSTEMS_DIR / "boundary_decision_system.py"
    runtime, deferred = _split_imports(path.read_text(encoding="utf-8"))

    for module in runtime + deferred:
        assert module.split(".")[0] not in {"random", "uuid", "secrets", "time", "hashlib"}


def test_boundary_decision_system_touches_no_private_world_registry() -> None:
    """Walls are added through ``World.add_wall``, never by writing a registry.

    The aggregate owns insertion and the boundary back-reference together;
    reaching past it would set one without the other.
    """
    path = SYSTEMS_DIR / "boundary_decision_system.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    private_attributes = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr.startswith("_")
    }
    for forbidden in ("_walls", "_entities", "_boundaries", "_districts"):
        assert forbidden not in private_attributes


def test_boundary_decision_system_is_exported_like_every_other_system() -> None:
    """Public export follows the existing convention exactly."""
    assert "BoundaryDecisionSystem" in living_diorama.systems.__all__
    assert hasattr(living_diorama.systems, "BoundaryDecisionSystem")


def test_boundary_decision_private_helpers_are_not_exported() -> None:
    """Internal helpers stay internal."""
    for name in ("_StagedWall", "_validate_population"):
        assert name not in living_diorama.systems.__all__
        assert not hasattr(living_diorama.systems, name)


PHASE_NINE_STDLIB = {"collections", "dataclasses", "math", "typing"}
"""Exactly the standard-library roots infrastructure_adaptation_system.py imports.

Kept tight on purpose: a roomy allowlist quietly permits dependencies nobody
decided to take. Phase 8's list is separate and covers a different module.
"""


def test_infrastructure_adaptation_system_imports_only_permitted_layers() -> None:
    """The Phase 9 system depends on entities, events, and shared helpers only.

    It reads walls off the world, not from the system that built them, so it
    must not import that system. Its only knowledge of ``World`` is a deferred
    typing import, as everywhere else.
    """
    path = SYSTEMS_DIR / "infrastructure_adaptation_system.py"
    runtime, deferred = _split_imports(path.read_text(encoding="utf-8"))

    assert not any(module.startswith("living_diorama.simulation") for module in runtime)
    assert any(module.startswith("living_diorama.simulation") for module in deferred)

    for module in runtime + deferred:
        assert not module.startswith(FORBIDDEN_DOWNSTREAM), module

    concrete_systems = (
        "production_system",
        "consumption_system",
        "resource_flow_system",
        "migration_system",
        "scarcity_system",
        "social_stability_system",
        "institutional_pressure_system",
        "boundary_decision_system",
    )
    for module in runtime + deferred:
        assert not any(name in module for name in concrete_systems), module


def test_infrastructure_adaptation_system_does_not_import_topology() -> None:
    """Adaptation is decided per boundary, so no collapsed topology view is used."""
    path = SYSTEMS_DIR / "infrastructure_adaptation_system.py"
    runtime, deferred = _split_imports(path.read_text(encoding="utf-8"))

    for module in runtime + deferred:
        assert "_topology" not in module, module
        assert "_flow_allocation" not in module, module


def test_infrastructure_adaptation_system_adds_no_third_party_dependency() -> None:
    """The engine has no runtime dependencies, and Phase 9 must not add one.

    The list is exactly what the module imports today, so a new standard-library
    dependency has to be added here deliberately rather than slipping through a
    roomy allowlist. ``collections`` belongs on it because ``collections.abc`` is
    standard library; omitting it would report a stdlib import as third-party.
    """
    allowed_stdlib = PHASE_NINE_STDLIB
    path = SYSTEMS_DIR / "infrastructure_adaptation_system.py"
    runtime, deferred = _split_imports(path.read_text(encoding="utf-8"))

    offenders = [
        module
        for module in runtime + deferred
        if module.split(".")[0] != "living_diorama" and module.split(".")[0] not in allowed_stdlib
    ]
    assert offenders == []


def test_the_stdlib_allowlist_recognises_collections_abc() -> None:
    """Guards the allowlist itself against the mistake it exists to prevent.

    ``collections.abc`` resolves to the ``collections`` root, so an allowlist
    checking the first path segment must contain ``collections`` or it would
    flag a standard-library import as a third-party dependency.
    """
    assert ["collections", "abc"][0] in PHASE_NINE_STDLIB
    assert "collections" in PHASE_NINE_STDLIB


def test_the_phase_nine_allowlist_matches_what_the_module_actually_imports() -> None:
    """An allowlist wider than the code turns a deliberate list into a guess."""
    path = SYSTEMS_DIR / "infrastructure_adaptation_system.py"
    runtime, deferred = _split_imports(path.read_text(encoding="utf-8"))

    used = {
        module.split(".")[0]
        for module in runtime + deferred
        if module.split(".")[0] != "living_diorama"
    }
    assert used == PHASE_NINE_STDLIB


def test_infrastructure_adaptation_system_uses_no_randomness() -> None:
    """Dependency is derived from stored state alone."""
    path = SYSTEMS_DIR / "infrastructure_adaptation_system.py"
    runtime, deferred = _split_imports(path.read_text(encoding="utf-8"))

    for module in runtime + deferred:
        assert module.split(".")[0] not in {"random", "uuid", "secrets", "time", "hashlib"}


def test_infrastructure_adaptation_system_touches_no_private_world_registry() -> None:
    """Everything goes through the public registries and public lookups."""
    path = SYSTEMS_DIR / "infrastructure_adaptation_system.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    private_attributes = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr.startswith("_")
    }
    for forbidden in (
        "_walls",
        "_entities",
        "_boundaries",
        "_districts",
        "_laws",
        "_infrastructure",
        "_tick",
    ):
        assert forbidden not in private_attributes


def test_infrastructure_adaptation_system_is_exported_like_every_other_system() -> None:
    """Public export follows the existing convention exactly."""
    assert "InfrastructureAdaptationSystem" in living_diorama.systems.__all__
    assert hasattr(living_diorama.systems, "InfrastructureAdaptationSystem")


def test_infrastructure_adaptation_private_helpers_are_not_exported() -> None:
    """Internal helpers stay internal."""
    for name in ("_InfrastructureState", "_WallState", "_validate_identifier", "_clamp_unit"):
        assert name not in living_diorama.systems.__all__
        assert not hasattr(living_diorama.systems, name)
