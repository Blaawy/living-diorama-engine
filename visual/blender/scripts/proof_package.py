"""Proof package integrity: one inventory, and an executable contract.

Pure Python by design -- this module never imports ``bpy``, so the integrity
of a delivered proof package can be re-verified by a reviewer on any machine,
with nothing installed but Python.

A proof package is only evidence if it is SELF-CONTAINED. A manifest that
names a ``.blend`` the package does not carry, or a package member that no
manifest ever hashed, both turn "verified" into a claim rather than a fact.
So exactly one file -- ``phase17_proof_package_manifest.json`` -- is the
authoritative inventory of the package, and it obeys a single rule:

    EVERY member of the package except the inventory itself is enumerated,
    with its byte size and its SHA-256.

That rule makes all five failure modes decidable rather than judgement calls:
a missing member, an unenumerated extra member, a wrong hash, a wrong size,
and a manifest that points at an artifact the package does not carry. Each
one is a refusal.

The per-run manifests (``motion_manifest.json`` and its persistence
counterpart) deliberately do NOT carry member lists of their own. Each is
written while its own renders are finishing, so any list it produced would be
a snapshot of a package that was still being assembled -- exactly the
inconsistency this module exists to remove. They record their own run; the
inventory records the package.
"""

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

from manifest_io import require_clean_utf8_json, write_manifest_json

PROOF_PACKAGE_FORMAT = "living_diorama_phase17_proof_package"
PROOF_PACKAGE_SCHEMA_VERSION = 1

INVENTORY_NAME = "phase17_proof_package_manifest.json"

MANIFEST_ARTIFACT_PREFIX = "living_diorama_phase17"
"""Any JSON member declaring an ``artifact`` beginning with this is treated as
one of the package's own manifests, and its artifact references are checked."""


class ProofPackageError(RuntimeError):
    """The proof package does not match its own inventory.

    Raised for a missing member, an unenumerated member, a size or hash
    mismatch, a dangling artifact reference, or a missing required member.
    Always a refusal: a package that cannot prove its own contents is not
    evidence.
    """


def _digest(path: Path) -> tuple[str, int]:
    """SHA-256 and byte size of one file."""
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def package_members(directory: Path) -> list[Path]:
    """Every packaged file except the inventory, in stable name order.

    Raises:
        ProofPackageError: If the package is empty or holds a subdirectory,
            which a flat inventory could not describe honestly.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise ProofPackageError(f"{directory} is not a proof directory")
    members = []
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if entry.is_dir():
            raise ProofPackageError(
                f"{entry.name} is a directory; a proof package is flat so that its "
                "inventory can enumerate every member without ambiguity"
            )
        if entry.name != INVENTORY_NAME:
            members.append(entry)
    if not members:
        raise ProofPackageError(f"{directory} holds no proof members")
    return members


def _artifact_references(directory: Path, members: Iterable[str]) -> dict[str, dict]:
    """Every artifact one of the package's own manifests points at.

    Currently the ``blend`` reference each per-run manifest records. Anything
    a manifest names has to be in the package, or the manifest is describing a
    world the reviewer cannot open.
    """
    references: dict[str, dict] = {}
    for name in sorted(members):
        if not name.endswith(".json"):
            continue
        try:
            document = json.loads((directory / name).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ProofPackageError(f"{name} is not readable UTF-8 JSON: {error}") from error
        if not isinstance(document, dict):
            continue
        artifact = document.get("artifact")
        if not isinstance(artifact, str) or not artifact.startswith(MANIFEST_ARTIFACT_PREFIX):
            continue
        blend = document.get("blend")
        if isinstance(blend, dict) and isinstance(blend.get("path"), str):
            references[name] = {
                "kind": "blend",
                "path": blend["path"],
                "sha256": blend.get("sha256"),
                "bytes": blend.get("bytes"),
            }
    return references


def write_package_inventory(directory: str | Path) -> Path:
    """Write the authoritative inventory of one proof package.

    Called last, once every member exists, so the inventory describes the
    package that is actually delivered rather than the one that was partway
    through being made.
    """
    directory = Path(directory)
    members = package_members(directory)
    entries: dict[str, dict] = {}
    total = 0
    for member in members:
        digest, size = _digest(member)
        entries[member.name] = {"sha256": digest, "bytes": size}
        total += size
    inventory = {
        "artifact": PROOF_PACKAGE_FORMAT,
        "schema_version": PROOF_PACKAGE_SCHEMA_VERSION,
        "inventory_file": INVENTORY_NAME,
        "member_count": len(entries),
        "total_bytes": total,
        "members": entries,
        "manifests": sorted(_artifact_references(directory, entries)),
        "artifact_references": _artifact_references(directory, entries),
    }
    target = directory / INVENTORY_NAME
    write_manifest_json(target, inventory)
    return target


def verify_package_inventory(directory: str | Path, required: Iterable[str] = ()) -> dict:
    """Refuse any proof package that disagrees with its own inventory.

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
    if inventory.get("artifact") != PROOF_PACKAGE_FORMAT:
        raise ProofPackageError(
            f"the inventory declares artifact {inventory.get('artifact')!r}, "
            f"expected {PROOF_PACKAGE_FORMAT!r}"
        )
    if inventory.get("schema_version") != PROOF_PACKAGE_SCHEMA_VERSION:
        raise ProofPackageError(
            f"inventory schema_version must be {PROOF_PACKAGE_SCHEMA_VERSION}, "
            f"got {inventory.get('schema_version')!r}"
        )
    entries = inventory.get("members")
    if not isinstance(entries, dict) or not entries:
        raise ProofPackageError("the inventory enumerates no members")

    on_disk = {member.name for member in package_members(directory)}
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

    for source, reference in sorted(_artifact_references(directory, enumerated).items()):
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
            for source, reference in _artifact_references(directory, enumerated).items()
        },
        "verified": True,
    }
