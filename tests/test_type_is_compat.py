"""Version-compat guard: the three modules that use ``typing.TypeIs``.

``typing.TypeIs`` was added in Python 3.13; on Python 3.12 it lives only in the
third-party ``typing_extensions`` package. The Kokoro voice-synthesis script
runs under a separate Python 3.12 interpreter and imports ``living_diorama``,
so the three modules below must fall back to ``typing_extensions`` when
``typing`` lacks the symbol. These tests simulate that environment in a fresh
subprocess and prove the fallback branch is the one that executes.
"""

import ast
import importlib
import subprocess
import sys
import typing
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"

MODULES = (
    "living_diorama.memory.world_memory",
    "living_diorama.systems.rule_system",
    "living_diorama.persistence.serializers._runtime_types",
)

_SOURCES = (
    SRC / "living_diorama" / "memory" / "world_memory.py",
    SRC / "living_diorama" / "systems" / "rule_system.py",
    SRC / "living_diorama" / "persistence" / "serializers" / "_runtime_types.py",
)

_FALLBACK_SCRIPT = """
import importlib
import sys
import types
import typing

# Simulate Python 3.12: the typing module has no TypeIs attribute.
if hasattr(typing, "TypeIs"):
    del typing.TypeIs

# The real Python 3.12 Kokoro environment ships typing_extensions. If this
# interpreter happens not to have it, stand in with a minimal module so the
# fallback import line is still the branch under test.
try:
    import typing_extensions
except ImportError:
    typing_extensions = types.ModuleType("typing_extensions")
    typing_extensions.TypeIs = object
    sys.modules["typing_extensions"] = typing_extensions

for name in {modules!r}:
    module = importlib.import_module(name)
    if module.TypeIs is not typing_extensions.TypeIs:
        raise SystemExit(name + " did not bind TypeIs from typing_extensions")
print("fallback-ok")
"""


def test_modules_import_when_typing_has_no_type_is() -> None:
    """Deleting typing.TypeIs forces every module onto the fallback import."""
    script = f"import sys\nsys.path.insert(0, {str(SRC)!r})\n" + _FALLBACK_SCRIPT.format(
        modules=MODULES
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert completed.stdout.strip() == "fallback-ok"


def test_modules_bind_type_is_from_typing_when_available() -> None:
    """On Python 3.13+ the normal path still resolves typing.TypeIs."""
    if not hasattr(typing, "TypeIs"):
        pytest.skip("typing.TypeIs unavailable in this interpreter")
    for name in MODULES:
        assert importlib.import_module(name).TypeIs is typing.TypeIs


def test_each_module_guards_type_is_with_an_import_error_fallback() -> None:
    """Static guard, in this repo's AST-audit style: the fallback import exists."""
    for path in _SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ExceptHandler)
            and isinstance(node.type, ast.Name)
            and node.type.id == "ImportError"
            for inner in ast.walk(node)
            if isinstance(inner, ast.ImportFrom) and inner.module == "typing_extensions"
            for alias in inner.names
        }
        assert "TypeIs" in imported, f"{path.name} lacks a typing_extensions.TypeIs fallback"
