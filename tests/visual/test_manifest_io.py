"""Encoding contract for Visual DNA manifests (pure Python).

Independent review found a UTF-8 BOM in a generated manifest, which breaks
the ordinary ``json.load(open(path, encoding="utf-8"))`` consumer path.
These tests pin the repaired contract: the pipeline's writer can only
produce plain UTF-8 JSON, and the guard refuses BOM-prefixed files loudly.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MODULE_PATH = REPO_ROOT / "visual" / "blender" / "scripts" / "manifest_io.py"


def load_manifest_io():
    """Import the pure manifest-encoding module from its file path."""
    spec = importlib.util.spec_from_file_location("manifest_io_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["manifest_io_under_test"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules["manifest_io_under_test"]
    return module


@pytest.fixture(name="manifest_io")
def manifest_io_fixture():
    """The manifest-encoding module under test."""
    return load_manifest_io()


def test_writer_produces_plain_utf8_without_bom(manifest_io, tmp_path: Path) -> None:
    """The pipeline writer emits no BOM and stays strict-UTF-8 readable."""
    path = tmp_path / "manifest.json"
    manifest_io.write_manifest_json(path, {"artifact": "proof", "value": "é✓"})
    data = path.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf"), "writer emitted a UTF-8 BOM"
    assert json.loads(data.decode("utf-8"))["value"] == "é✓"
    with path.open("r", encoding="utf-8") as handle:
        assert json.load(handle)["artifact"] == "proof"


def test_guard_refuses_a_bom_prefixed_manifest(manifest_io, tmp_path: Path) -> None:
    """A BOM-prefixed manifest is refused loudly, never silently accepted."""
    path = tmp_path / "manifest.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"artifact": "proof"}).encode("utf-8"))
    with pytest.raises(ValueError, match="BOM"):
        manifest_io.require_clean_utf8_json(path)


def test_guard_accepts_and_parses_a_clean_manifest(manifest_io, tmp_path: Path) -> None:
    """A plain UTF-8 manifest round-trips through the guard."""
    path = tmp_path / "manifest.json"
    path.write_bytes(json.dumps({"artifact": "proof", "n": 1}).encode("utf-8"))
    assert manifest_io.require_clean_utf8_json(path) == {"artifact": "proof", "n": 1}


def test_guard_refuses_non_object_documents(manifest_io, tmp_path: Path) -> None:
    """Manifests are JSON objects; a bare list or scalar is refused."""
    path = tmp_path / "manifest.json"
    path.write_bytes(b"[1, 2, 3]")
    with pytest.raises(ValueError, match="JSON object"):
        manifest_io.require_clean_utf8_json(path)


def test_module_stays_pure(manifest_io) -> None:
    """The encoding contract never depends on Blender."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "import bpy" not in source and "import bmesh" not in source
