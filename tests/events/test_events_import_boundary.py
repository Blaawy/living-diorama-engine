"""Architectural tests: the event and RNG layers must not reach downstream.

The event layer sits just above entities. If it ever imports systems,
persistence, memory, render, narration, or cli, the Dependency Rule has
inverted and later phases would be free to create cycles. The RNG is stricter
still: it may depend on nothing in the project at all.
"""

import ast
from pathlib import Path

import living_diorama.events
import living_diorama.simulation

EVENTS_DIR = Path(living_diorama.events.__file__).parent
RNG_FILE = Path(living_diorama.simulation.__file__).parent / "rng.py"

FORBIDDEN_FOR_EVENTS = (
    "living_diorama.systems",
    "living_diorama.persistence",
    "living_diorama.memory",
    "living_diorama.render",
    "living_diorama.narration",
    "living_diorama.cli",
    "living_diorama.simulation",
)


def _imported_modules(source: str) -> list[str]:
    """Return every absolute module name imported by the given source text."""
    tree = ast.parse(source)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module)
    return modules


def test_event_layer_does_not_import_downstream_packages() -> None:
    """Events may know about entities, and nothing further along the chain."""
    offenders: list[str] = []
    for path in sorted(EVENTS_DIR.glob("*.py")):
        for module in _imported_modules(path.read_text(encoding="utf-8")):
            if module.startswith(FORBIDDEN_FOR_EVENTS):
                offenders.append(f"{path.name} imports {module}")
    assert offenders == []


def test_event_layer_imports_no_third_party_packages() -> None:
    """The engine has no runtime dependencies, and the event layer must not add one."""
    allowed_stdlib = {"collections", "dataclasses", "enum", "itertools", "math", "types", "typing"}
    offenders: list[str] = []
    for path in sorted(EVENTS_DIR.glob("*.py")):
        for module in _imported_modules(path.read_text(encoding="utf-8")):
            root = module.split(".")[0]
            if root != "living_diorama" and root not in allowed_stdlib:
                offenders.append(f"{path.name} imports {module}")
    assert offenders == []


def test_event_bus_does_not_reference_world_memory() -> None:
    """The bus must not know which events matter; significance is memory's job."""
    source = (EVENTS_DIR / "event_bus.py").read_text(encoding="utf-8")
    assert "WorldMemory" not in source
    assert "memory" not in _imported_modules(source)


def test_rng_imports_nothing_from_the_project() -> None:
    """Randomness is a primitive and must not depend on any domain module."""
    modules = _imported_modules(RNG_FILE.read_text(encoding="utf-8"))
    assert [module for module in modules if module.startswith("living_diorama")] == []


def test_rng_imports_only_the_standard_library() -> None:
    """No third-party dependency may sneak in through the RNG."""
    allowed = {"random", "collections"}
    modules = _imported_modules(RNG_FILE.read_text(encoding="utf-8"))
    assert [module for module in modules if module.split(".")[0] not in allowed] == []


def test_event_layer_files_were_actually_scanned() -> None:
    """Guard against these boundary tests passing on an empty file list."""
    assert len(list(EVENTS_DIR.glob("*.py"))) >= 4
    assert RNG_FILE.exists()
