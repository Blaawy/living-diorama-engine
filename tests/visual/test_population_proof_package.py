"""Contract tests for the Phase 18 proof package inventory.

Pure pytest -- no Blender. Each test builds a small package on disk, inventories
it, and then breaks it in exactly one way. The point of an inventory is that
every failure mode is DECIDABLE rather than a judgement call, so every failure
mode gets its own test:

* a member the inventory names but the package does not carry;
* a member the package carries but the inventory never hashed;
* a member whose bytes changed;
* a member whose size changed;
* a manifest pointing at an artifact nobody packaged;
* a manifest recording a different hash or size than the package holds;
* a required member that is simply absent.

The last group matters most. A verifier that silently skipped the manifest's
own references would let a package ship a manifest describing a ``.blend`` that
was never delivered -- and it would still say "verified".
"""

import hashlib
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


package = _load("population_proof_package")
proof_package = _load("proof_package")


def build_package(root: Path, *, blend_reference: bool = True) -> Path:
    """A small but realistic Phase 18 proof package."""
    directory = root / "population_proof"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "phase18_world_with_population.png").write_bytes(b"\x89PNG frame")
    (directory / "phase18_structural_results.txt").write_text(
        "ok   test_population_presence.test_one\n", encoding="utf-8", newline="\n"
    )
    blend = directory / "living_diorama_phase18_population_presence.blend"
    blend.write_bytes(b"BLENDER-v450 pretend")
    export = directory / "render_export_before.json"
    export.write_text('{"format": "living_diorama_render_export"}\n', encoding="utf-8")
    manifest = {
        "artifact": "living_diorama_phase18_population_presence_proof",
        "schema_version": 1,
        "plan_hash": "0" * 64,
        "source_export": {
            "path": export.name,
            "sha256": hashlib.sha256(export.read_bytes()).hexdigest(),
            "bytes": export.stat().st_size,
        },
    }
    if blend_reference:
        manifest["blend"] = {
            "path": blend.name,
            "sha256": hashlib.sha256(blend.read_bytes()).hexdigest(),
            "bytes": blend.stat().st_size,
        }
    (directory / "population_presence_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return directory


def test_a_complete_package_verifies(tmp_path) -> None:
    """The happy path, so every refusal below means something."""
    directory = build_package(tmp_path)
    package.write_population_inventory(directory)
    report = package.verify_population_inventory(directory)
    assert report["verified"] is True
    assert report["member_count"] == 5
    assert report["artifact_references"] == {
        "population_presence_manifest.json#blend": (
            "living_diorama_phase18_population_presence.blend"
        ),
        "population_presence_manifest.json#source_export": "render_export_before.json",
    }


def test_a_dangling_source_export_reference_is_refused(tmp_path) -> None:
    """The export the whole population claim rests on must be in the package.

    A manifest that names the render export while the package does not carry it
    leaves a reviewer unable to recompute a single proxy count. That is the
    same defect as a dangling ``.blend``, and it is refused the same way.
    """
    directory = build_package(tmp_path)
    (directory / "render_export_before.json").unlink()
    package.write_population_inventory(directory)
    with pytest.raises(proof_package.ProofPackageError, match="does not carry"):
        package.verify_population_inventory(directory)


def test_a_forged_source_export_hash_is_refused(tmp_path) -> None:
    """The export delivered must be the export the plan was derived from."""
    directory = build_package(tmp_path)
    manifest_path = directory / "population_presence_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_export"]["sha256"] = "e" * 64
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    package.write_population_inventory(directory)
    with pytest.raises(proof_package.ProofPackageError, match="different hash"):
        package.verify_population_inventory(directory)


def test_both_reference_kinds_are_checked_independently(tmp_path) -> None:
    """One manifest carries two references, and neither masks the other."""
    directory = build_package(tmp_path)
    package.write_population_inventory(directory)
    references = package.artifact_references(
        directory, [entry.name for entry in directory.iterdir()]
    )
    kinds = {reference["kind"] for reference in references.values()}
    assert kinds == {"blend", "source_export"}
    assert len(references) == 2, "a shared key would let one reference hide the other"


def test_the_inventory_declares_the_phase18_format(tmp_path) -> None:
    """A Phase 18 package says it is one, in its own file name and its format."""
    directory = build_package(tmp_path)
    inventory_path = package.write_population_inventory(directory)
    assert inventory_path.name == "phase18_proof_package_manifest.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    assert inventory["artifact"] == "living_diorama_phase18_proof_package"
    assert inventory["schema_version"] == 1


def test_the_inventory_never_enumerates_itself(tmp_path) -> None:
    """Hashing the inventory inside the inventory could never be consistent."""
    directory = build_package(tmp_path)
    package.write_population_inventory(directory)
    inventory = json.loads((directory / package.INVENTORY_NAME).read_text(encoding="utf-8"))
    assert package.INVENTORY_NAME not in inventory["members"]
    assert inventory["member_count"] == len(inventory["members"])


def test_the_inventory_is_written_without_a_bom(tmp_path) -> None:
    """A BOM breaks ``json.load(open(path, encoding='utf-8'))`` for everybody."""
    directory = build_package(tmp_path)
    inventory_path = package.write_population_inventory(directory)
    assert not inventory_path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_rewriting_the_inventory_is_stable(tmp_path) -> None:
    """Inventorying twice describes the same package the same way."""
    directory = build_package(tmp_path)
    package.write_population_inventory(directory)
    first = (directory / package.INVENTORY_NAME).read_bytes()
    package.write_population_inventory(directory)
    assert (directory / package.INVENTORY_NAME).read_bytes() == first


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_missing_member_is_refused(tmp_path) -> None:
    """A file the inventory names must be in the package."""
    directory = build_package(tmp_path)
    package.write_population_inventory(directory)
    (directory / "phase18_world_with_population.png").unlink()
    with pytest.raises(proof_package.ProofPackageError, match="does not carry"):
        package.verify_population_inventory(directory)


def test_an_unenumerated_member_is_refused(tmp_path) -> None:
    """A file nobody hashed is a file nobody reviewed."""
    directory = build_package(tmp_path)
    package.write_population_inventory(directory)
    (directory / "surprise.png").write_bytes(b"\x89PNG smuggled")
    with pytest.raises(proof_package.ProofPackageError, match="never hashed"):
        package.verify_population_inventory(directory)


def test_a_smuggled_phase17_inventory_is_refused(tmp_path) -> None:
    """The one filename the borrowed helper hides must not be invisible here.

    ``proof_package.package_members`` drops ``phase17_proof_package_manifest``
    because that IS the inventory of a Phase 17 package. In a Phase 18 package
    it is an ordinary file, and enumerating through the borrowed helper would
    let it be added, altered or smuggled in without ever being hashed.
    """
    directory = build_package(tmp_path)
    package.write_population_inventory(directory)
    (directory / "phase17_proof_package_manifest.json").write_bytes(b"unreviewed payload")
    with pytest.raises(proof_package.ProofPackageError, match="never hashed"):
        package.verify_population_inventory(directory)


def test_a_smuggled_phase17_inventory_is_enumerated_when_present(tmp_path) -> None:
    """And when it is there at inventory time, it is hashed like any member."""
    directory = build_package(tmp_path)
    (directory / "phase17_proof_package_manifest.json").write_text(
        '{"note": "an ordinary member, not this package\'s inventory"}\n', encoding="utf-8"
    )
    package.write_population_inventory(directory)
    inventory = json.loads((directory / package.INVENTORY_NAME).read_text(encoding="utf-8"))
    assert "phase17_proof_package_manifest.json" in inventory["members"]
    assert package.verify_population_inventory(directory)["verified"] is True


def test_a_mutated_member_is_refused(tmp_path) -> None:
    """Same size, different bytes: only the hash catches this one."""
    directory = build_package(tmp_path)
    package.write_population_inventory(directory)
    target = directory / "phase18_world_with_population.png"
    original = target.read_bytes()
    target.write_bytes(b"\x89PNG framf")
    assert len(target.read_bytes()) == len(original), "this test must not change the size"
    with pytest.raises(proof_package.ProofPackageError, match="hashes to"):
        package.verify_population_inventory(directory)


def test_a_resized_member_is_refused(tmp_path) -> None:
    """Different size is caught before the hash even matters."""
    directory = build_package(tmp_path)
    package.write_population_inventory(directory)
    (directory / "phase18_world_with_population.png").write_bytes(b"\x89PNG frame and more")
    with pytest.raises(proof_package.ProofPackageError, match="bytes"):
        package.verify_population_inventory(directory)


def test_a_missing_required_member_is_refused(tmp_path) -> None:
    """The gate names what a Phase 18 package must contain."""
    directory = build_package(tmp_path)
    package.write_population_inventory(directory)
    with pytest.raises(proof_package.ProofPackageError, match="missing required"):
        package.verify_population_inventory(
            directory, required=("phase18_population_contact_sheet.png",)
        )


def test_a_dangling_blend_reference_is_refused(tmp_path) -> None:
    """A manifest may not name a world the reviewer cannot open."""
    directory = build_package(tmp_path)
    manifest_path = directory / "population_presence_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["blend"]["path"] = "a_blend_nobody_packaged.blend"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    package.write_population_inventory(directory)
    with pytest.raises(proof_package.ProofPackageError, match="does not carry"):
        package.verify_population_inventory(directory)


def test_a_forged_blend_hash_is_refused(tmp_path) -> None:
    """The manifest's record of the blend must match the blend delivered."""
    directory = build_package(tmp_path)
    manifest_path = directory / "population_presence_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["blend"]["sha256"] = "f" * 64
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    package.write_population_inventory(directory)
    with pytest.raises(proof_package.ProofPackageError, match="different hash"):
        package.verify_population_inventory(directory)


def test_a_forged_blend_size_is_refused(tmp_path) -> None:
    """Size is checked alongside the hash, so neither alone can be spoofed."""
    directory = build_package(tmp_path)
    manifest_path = directory / "population_presence_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["blend"]["bytes"] = 1
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    package.write_population_inventory(directory)
    with pytest.raises(proof_package.ProofPackageError, match="different size"):
        package.verify_population_inventory(directory)


def test_a_package_with_no_inventory_is_refused(tmp_path) -> None:
    """An uninventoried package proves nothing about itself."""
    directory = build_package(tmp_path)
    with pytest.raises(proof_package.ProofPackageError, match="no inventory"):
        package.verify_population_inventory(directory)


def test_a_phase17_inventory_is_not_accepted_as_a_phase18_one(tmp_path) -> None:
    """The two package formats are distinct, and the verifier says so.

    This is why Phase 18 carries its own constants: a Phase 17 inventory
    dropped into a Phase 18 package would otherwise be read as a valid one,
    and its artifact-prefix filter would silently skip the Phase 18 manifest's
    blend reference -- the check would pass while proving nothing.
    """
    directory = build_package(tmp_path)
    package.write_population_inventory(directory)
    inventory_path = directory / package.INVENTORY_NAME
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["artifact"] = proof_package.PROOF_PACKAGE_FORMAT
    inventory_path.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(proof_package.ProofPackageError, match="declares artifact"):
        package.verify_population_inventory(directory)


def test_a_wrong_schema_version_is_refused(tmp_path) -> None:
    """A future inventory schema is not silently read as this one."""
    directory = build_package(tmp_path)
    package.write_population_inventory(directory)
    inventory_path = directory / package.INVENTORY_NAME
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["schema_version"] = 9
    inventory_path.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(proof_package.ProofPackageError, match="schema_version"):
        package.verify_population_inventory(directory)


def test_an_empty_inventory_is_refused(tmp_path) -> None:
    """A package that enumerates nothing has not described itself."""
    directory = build_package(tmp_path)
    package.write_population_inventory(directory)
    inventory_path = directory / package.INVENTORY_NAME
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["members"] = {}
    inventory_path.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(proof_package.ProofPackageError, match="enumerates no members"):
        package.verify_population_inventory(directory)


def test_a_subdirectory_is_refused(tmp_path) -> None:
    """A flat package is what makes a flat inventory honest."""
    directory = build_package(tmp_path)
    (directory / "extras").mkdir()
    (directory / "extras" / "hidden.png").write_bytes(b"\x89PNG")
    with pytest.raises(proof_package.ProofPackageError, match="flat"):
        package.write_population_inventory(directory)


def test_an_empty_directory_is_refused(tmp_path) -> None:
    """There is nothing to inventory, and that is an error not a pass."""
    directory = tmp_path / "empty"
    directory.mkdir()
    with pytest.raises(proof_package.ProofPackageError):
        package.write_population_inventory(directory)


def test_an_unreadable_manifest_is_refused(tmp_path) -> None:
    """A manifest that is not UTF-8 JSON cannot be checked, so it is refused."""
    directory = build_package(tmp_path)
    (directory / "population_presence_manifest.json").write_bytes(b"\xff\xfe not json")
    with pytest.raises(proof_package.ProofPackageError, match="not readable UTF-8 JSON"):
        package.write_population_inventory(directory)


def test_a_manifest_without_a_blend_reference_still_verifies(tmp_path) -> None:
    """The reference check is per-kind, not a hidden required field."""
    directory = build_package(tmp_path, blend_reference=False)
    package.write_population_inventory(directory)
    report = package.verify_population_inventory(directory)
    assert set(report["artifact_references"]) == {"population_presence_manifest.json#source_export"}
    assert report["verified"] is True
