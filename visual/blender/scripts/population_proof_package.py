"""Phase 18 proof package integrity: one inventory, and an executable contract.

Pure Python by design -- this module never imports ``bpy``, so the integrity of
a delivered Phase 18 package can be re-verified by a reviewer on any machine
with nothing installed but Python.

The rule is the one Phase 17 established and is deliberately unchanged:

    EVERY member of the package except the inventory itself is enumerated,
    with its byte size and its SHA-256.

That makes five failure modes decidable rather than judgement calls -- a
missing member, an unenumerated extra member, a wrong hash, a wrong size, and
a manifest that points at an artifact the package does not carry.

This is a SIBLING of :mod:`proof_package`, not a replacement and not a fork of
convenience. That module's format id, inventory filename and manifest prefix
are Phase 17 constants baked in at module level, and Phase 17 is locked. Making
a Phase 18 package carry a file called ``phase17_proof_package_manifest.json``
would be a lie about what the package is, and declaring the Phase 18 manifest
under a Phase 17 artifact prefix so the shared code would inspect it would be a
second one. Worse, getting the prefix wrong silently DISABLES the dangling
reference check -- the package would still "verify" while its manifest pointed
at a ``.blend`` nobody shipped, which is precisely the defect that check exists
to catch. So Phase 18 carries its own constants and its own rules, reuses the
generic, phase-agnostic helpers from the locked module, and touches nothing
that is locked.
"""

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

from manifest_io import require_clean_utf8_json, write_manifest_json
from proof_package import ProofPackageError, package_members

POPULATION_PACKAGE_FORMAT = "living_diorama_phase18_proof_package"
POPULATION_PACKAGE_SCHEMA_VERSION = 1

INVENTORY_NAME = "phase18_proof_package_manifest.json"

MANIFEST_ARTIFACT_PREFIX = "living_diorama_phase18"
"""Any JSON member declaring an ``artifact`` beginning with this is treated as
one of the package's own manifests, and its artifact references are checked."""


def population_members(directory: Path) -> list[Path]:
    """Every packaged file except THIS phase's inventory, in stable name order.

    Deliberately not :func:`proof_package.package_members`, which hides the
    Phase 17 inventory filename. In a Phase 18 package that name is not an
    inventory at all -- it is an ordinary member, and one the borrowed helper
    would drop from both the enumeration and the on-disk comparison, leaving a
    file that could be added, altered or smuggled in without the verifier ever
    hashing it. The locked helper is still called first, for the flat-directory
    and non-empty refusals it owns.
    """
    directory = Path(directory)
    package_members(directory)
    members = [
        entry
        for entry in sorted(directory.iterdir(), key=lambda item: item.name)
        if entry.is_file() and entry.name != INVENTORY_NAME
    ]
    if not members:
        raise ProofPackageError(f"{directory} holds no proof members")
    return members


def _digest(path: Path) -> tuple[str, int]:
    """SHA-256 and byte size of one file."""
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def artifact_references(directory: Path, members: Iterable[str]) -> dict[str, dict]:
    """Every artifact one of the package's own manifests points at.

    Two kinds matter. A manifest names the ``.blend`` a reviewer is meant to
    open, and it names the render export the whole population claim is derived
    from. If either is missing from the package, the manifest is describing
    something nobody can check: a world that cannot be opened, or a count that
    cannot be recomputed. Both are refusals.

    Keys are ``"<manifest>#<kind>"`` so one manifest can carry both without
    either quietly overwriting the other.
    """
    references: dict[str, dict] = {}
    for name in sorted(members):
        if not name.endswith(".json"):
            continue
        try:
            document = json.loads((Path(directory) / name).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ProofPackageError(f"{name} is not readable UTF-8 JSON: {error}") from error
        if not isinstance(document, dict):
            continue
        artifact = document.get("artifact")
        if not isinstance(artifact, str) or not artifact.startswith(MANIFEST_ARTIFACT_PREFIX):
            continue
        for kind in ("blend", "source_export"):
            reference = document.get(kind)
            if not isinstance(reference, dict) or not isinstance(reference.get("path"), str):
                continue
            references[f"{name}#{kind}"] = {
                "kind": kind,
                "source": name,
                "path": reference["path"],
                "sha256": reference.get("sha256"),
                "bytes": reference.get("bytes"),
            }
    return references


def write_population_inventory(directory: str | Path) -> Path:
    """Write the authoritative inventory of one Phase 18 proof package.

    Called last, once every member exists, so the inventory describes the
    package that is actually delivered rather than the one that was partway
    through being made.
    """
    directory = Path(directory)
    entries: dict[str, dict] = {}
    total = 0
    for member in population_members(directory):
        digest, size = _digest(member)
        entries[member.name] = {"sha256": digest, "bytes": size}
        total += size
    if not entries:
        raise ProofPackageError(f"{directory} holds no proof members")
    inventory = {
        "artifact": POPULATION_PACKAGE_FORMAT,
        "schema_version": POPULATION_PACKAGE_SCHEMA_VERSION,
        "inventory_file": INVENTORY_NAME,
        "member_count": len(entries),
        "total_bytes": total,
        "members": entries,
        "manifests": sorted(artifact_references(directory, entries)),
        "artifact_references": artifact_references(directory, entries),
    }
    target = directory / INVENTORY_NAME
    write_manifest_json(target, inventory)
    return target


def verify_population_inventory(directory: str | Path, required: Iterable[str] = ()) -> dict:
    """Refuse any Phase 18 proof package that disagrees with its own inventory.

    Checks, in order: the inventory parses as strict UTF-8 JSON with no BOM
    and declares this format; the enumerated set is exactly the set on disk
    (so a missing member and an unenumerated extra are both caught); every
    member's byte size and SHA-256 match; every required member is present;
    and every artifact a packaged manifest points at is itself a packaged
    member with the hash that manifest recorded.

    Raises:
        ProofPackageError: On the first inconsistency found.
    """
    directory = Path(directory)
    inventory_path = directory / INVENTORY_NAME
    if not inventory_path.exists():
        raise ProofPackageError(f"the package has no inventory at {INVENTORY_NAME}")
    inventory = require_clean_utf8_json(inventory_path)
    if inventory.get("artifact") != POPULATION_PACKAGE_FORMAT:
        raise ProofPackageError(
            f"the inventory declares artifact {inventory.get('artifact')!r}, "
            f"expected {POPULATION_PACKAGE_FORMAT!r}"
        )
    if inventory.get("schema_version") != POPULATION_PACKAGE_SCHEMA_VERSION:
        raise ProofPackageError(
            f"inventory schema_version must be {POPULATION_PACKAGE_SCHEMA_VERSION}, "
            f"got {inventory.get('schema_version')!r}"
        )
    entries = inventory.get("members")
    if not isinstance(entries, dict) or not entries:
        raise ProofPackageError("the inventory enumerates no members")

    on_disk = {member.name for member in population_members(directory)}
    enumerated = set(entries)
    missing = sorted(enumerated - on_disk)
    if missing:
        raise ProofPackageError(
            f"the inventory names members the package does not carry: {missing}"
        )
    unenumerated = sorted(on_disk - enumerated)
    if unenumerated:
        raise ProofPackageError(
            f"the package carries members the inventory never hashed: {unenumerated}"
        )

    for name in sorted(entries):
        entry = entries[name]
        if not isinstance(entry, dict):
            raise ProofPackageError(f"inventory entry for {name} is malformed")
        digest, size = _digest(directory / name)
        if entry.get("bytes") != size:
            raise ProofPackageError(
                f"{name} is {size} bytes, the inventory recorded {entry.get('bytes')}"
            )
        if entry.get("sha256") != digest:
            raise ProofPackageError(
                f"{name} hashes to {digest}, the inventory recorded {entry.get('sha256')}"
            )

    absent = sorted(name for name in required if name not in enumerated)
    if absent:
        raise ProofPackageError(f"the proof package is missing required members: {absent}")

    for source, reference in sorted(artifact_references(directory, enumerated).items()):
        target = reference["path"]
        if target not in enumerated:
            raise ProofPackageError(
                f"{source} references {reference['kind']} {target!r}, which the package "
                "does not carry; a manifest may not name an artifact a reviewer cannot open"
            )
        if reference["sha256"] is not None and reference["sha256"] != entries[target]["sha256"]:
            raise ProofPackageError(
                f"{source} records a different hash for {target!r} than the package holds"
            )
        if reference["bytes"] is not None and reference["bytes"] != entries[target]["bytes"]:
            raise ProofPackageError(
                f"{source} records a different size for {target!r} than the package holds"
            )

    return {
        "member_count": len(entries),
        "total_bytes": inventory.get("total_bytes"),
        "manifests": sorted(inventory.get("manifests") or []),
        "artifact_references": {
            source: reference["path"]
            for source, reference in artifact_references(directory, enumerated).items()
        },
        "verified": True,
    }
