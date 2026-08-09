"""Contract tests for the Phase 17 proof package inventory.

Pure pytest -- no Blender. A proof package is only evidence if it can prove
its own contents, so these tests are written as attacks: take a package that
verifies, break it one way, and require a refusal. The five ways a package can
lie about itself are each covered, because "I checked" is not verification.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "visual" / "blender" / "scripts"


def _load(name: str):
    """Import one pure visual module the same way Blender does: by sibling name."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


pp = _load("proof_package")


def build_package(root: Path, *, blend_name: str = "world.blend") -> Path:
    """A minimal but realistic proof package: frames, a manifest, a .blend."""
    directory = root / "motion_proof"
    directory.mkdir()
    (directory / "phase17_start.png").write_bytes(b"start-frame-bytes")
    (directory / "phase17_end.png").write_bytes(b"end-frame-bytes")
    (directory / "phase17_structural_results.txt").write_text(
        "LD_BLENDER_TESTS_P17: 57 passed, 0 failed\n", encoding="utf-8"
    )
    blend = directory / blend_name
    blend.write_bytes(b"fake-blend-payload")
    digest, size = pp._digest(blend)
    (directory / "motion_manifest.json").write_text(
        json.dumps(
            {
                "artifact": "living_diorama_phase17_motion_time_proof",
                "blend": {"path": blend_name, "sha256": digest, "bytes": size},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return directory


@pytest.fixture(name="package")
def package_fixture(tmp_path) -> Path:
    """A package with a freshly written, self-consistent inventory."""
    directory = build_package(tmp_path)
    pp.write_package_inventory(directory)
    return directory


def test_a_self_consistent_package_verifies(package) -> None:
    """The happy path: what the inventory says is what the package holds."""
    summary = pp.verify_package_inventory(package)
    assert summary["verified"] is True
    assert summary["member_count"] == 5
    assert summary["manifests"] == ["motion_manifest.json"]
    assert summary["artifact_references"] == {"motion_manifest.json": "world.blend"}


def test_the_inventory_never_enumerates_itself(package) -> None:
    """Self-hashing is impossible, so the inventory is excluded by rule."""
    inventory = json.loads((package / pp.INVENTORY_NAME).read_text(encoding="utf-8"))
    assert pp.INVENTORY_NAME not in inventory["members"]
    assert inventory["inventory_file"] == pp.INVENTORY_NAME
    assert inventory["member_count"] == len(inventory["members"])
    assert inventory["total_bytes"] == sum(
        entry["bytes"] for entry in inventory["members"].values()
    )


def test_the_inventory_is_plain_utf8_with_no_bom(package) -> None:
    """Written through the project's strict manifest writer, like every other."""
    data = (package / pp.INVENTORY_NAME).read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    assert json.loads(data.decode("utf-8"))


def test_every_member_is_enumerated_with_size_and_hash(package) -> None:
    """No member is described by name alone."""
    inventory = json.loads((package / pp.INVENTORY_NAME).read_text(encoding="utf-8"))
    for name, entry in inventory["members"].items():
        digest, size = pp._digest(package / name)
        assert entry["sha256"] == digest
        assert entry["bytes"] == size


def test_a_missing_proof_member_is_refused(package) -> None:
    """ATTACK: delete a file the inventory promised."""
    (package / "phase17_end.png").unlink()
    with pytest.raises(pp.ProofPackageError) as error:
        pp.verify_package_inventory(package)
    assert "does not carry" in str(error.value)
    assert "phase17_end.png" in str(error.value)


def test_an_extra_proof_member_is_refused(package) -> None:
    """ATTACK: slip a file in after the inventory was written."""
    (package / "phase17_sneaked_in.png").write_bytes(b"unaccounted")
    with pytest.raises(pp.ProofPackageError) as error:
        pp.verify_package_inventory(package)
    assert "never hashed" in str(error.value)
    assert "phase17_sneaked_in.png" in str(error.value)


def test_a_mutated_member_is_refused(package) -> None:
    """ATTACK: change one byte of a proof frame."""
    frame = package / "phase17_start.png"
    data = bytearray(frame.read_bytes())
    data[0] ^= 0xFF
    frame.write_bytes(bytes(data))
    with pytest.raises(pp.ProofPackageError) as error:
        pp.verify_package_inventory(package)
    assert "hashes to" in str(error.value)


def test_a_resized_member_is_refused(package) -> None:
    """ATTACK: append to a member so its size no longer matches."""
    frame = package / "phase17_end.png"
    frame.write_bytes(frame.read_bytes() + b"more")
    with pytest.raises(pp.ProofPackageError) as error:
        pp.verify_package_inventory(package)
    assert "bytes, the inventory recorded" in str(error.value)


def test_a_dangling_blend_reference_is_refused(tmp_path) -> None:
    """ATTACK: a manifest that names a .blend the package does not carry.

    This is the exact defect independent review found: the persistence
    manifest recorded a hash for a ``.blend`` that was never packaged. The
    inventory is regenerated AFTER the removal here, so the member checks all
    pass and only the reference check can catch it.
    """
    directory = build_package(tmp_path)
    (directory / "world.blend").unlink()
    pp.write_package_inventory(directory)
    with pytest.raises(pp.ProofPackageError) as error:
        pp.verify_package_inventory(directory)
    assert "does not carry" in str(error.value)
    assert "world.blend" in str(error.value)


def test_a_blend_reference_with_the_wrong_hash_is_refused(package) -> None:
    """ATTACK: the packaged .blend is not the one the manifest describes."""
    manifest_path = package / "motion_manifest.json"
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["blend"]["sha256"] = "0" * 64
    manifest_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    pp.write_package_inventory(package)
    with pytest.raises(pp.ProofPackageError) as error:
        pp.verify_package_inventory(package)
    assert "different hash" in str(error.value)


def test_a_blend_reference_with_the_wrong_size_is_refused(package) -> None:
    """ATTACK: the manifest's recorded size disagrees with the packaged file."""
    manifest_path = package / "motion_manifest.json"
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["blend"]["bytes"] = 1
    manifest_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    pp.write_package_inventory(package)
    with pytest.raises(pp.ProofPackageError) as error:
        pp.verify_package_inventory(package)
    assert "different size" in str(error.value)


def test_a_missing_required_member_is_refused(package) -> None:
    """A package may be self-consistent and still be incomplete."""
    pp.verify_package_inventory(package, required=("phase17_start.png",))
    with pytest.raises(pp.ProofPackageError) as error:
        pp.verify_package_inventory(package, required=("phase17_contact_sheet.png",))
    assert "missing required members" in str(error.value)


def test_a_package_with_no_inventory_is_refused(tmp_path) -> None:
    """An unverifiable package is refused, not assumed good."""
    directory = build_package(tmp_path)
    with pytest.raises(pp.ProofPackageError) as error:
        pp.verify_package_inventory(directory)
    assert "no inventory" in str(error.value)


def test_a_forged_inventory_identity_is_refused(package) -> None:
    """Some other JSON file renamed into place is not this contract."""
    path = package / pp.INVENTORY_NAME
    document = json.loads(path.read_text(encoding="utf-8"))
    document["artifact"] = "something_else"
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
    with pytest.raises(pp.ProofPackageError) as error:
        pp.verify_package_inventory(package)
    assert "declares artifact" in str(error.value)

    document["artifact"] = pp.PROOF_PACKAGE_FORMAT
    document["schema_version"] = 99
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
    with pytest.raises(pp.ProofPackageError) as error:
        pp.verify_package_inventory(package)
    assert "schema_version" in str(error.value)


def test_an_empty_or_nested_package_is_refused(tmp_path) -> None:
    """A flat, non-empty package is the only shape the inventory can describe."""
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(pp.ProofPackageError):
        pp.package_members(empty)
    nested = build_package(tmp_path)
    (nested / "extra_frames").mkdir()
    with pytest.raises(pp.ProofPackageError) as error:
        pp.package_members(nested)
    assert "flat" in str(error.value)


def test_writing_the_inventory_twice_is_stable(package) -> None:
    """Re-running the packaging step does not change the package."""
    first = (package / pp.INVENTORY_NAME).read_bytes()
    pp.write_package_inventory(package)
    assert (package / pp.INVENTORY_NAME).read_bytes() == first
    assert pp.verify_package_inventory(package)["verified"] is True
