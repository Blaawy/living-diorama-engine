"""Architectural test: the entity layer must not import any other package.

``entities`` is the innermost layer. If it ever imports ``systems``, ``events``,
``persistence``, or anything else from ``living_diorama``, the Dependency Rule
is broken and the architecture has quietly inverted. This test fails the build
at that moment rather than at code-review time.
"""

import ast
from pathlib import Path

import living_diorama.entities

ENTITIES_DIR = Path(living_diorama.entities.__file__).parent
ALLOWED_PREFIX = "living_diorama.entities"


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


def test_entity_layer_imports_no_other_living_diorama_package() -> None:
    """Every in-project import inside entities/ must stay inside entities/."""
    offenders: list[str] = []
    for path in sorted(ENTITIES_DIR.glob("*.py")):
        for module in _imported_modules(path.read_text(encoding="utf-8")):
            if module.startswith("living_diorama") and not module.startswith(ALLOWED_PREFIX):
                offenders.append(f"{path.name} imports {module}")
    assert offenders == []


def test_entity_layer_files_were_actually_scanned() -> None:
    """Guard against the boundary test silently passing on an empty file list."""
    scanned = list(ENTITIES_DIR.glob("*.py"))
    assert len(scanned) >= 8
