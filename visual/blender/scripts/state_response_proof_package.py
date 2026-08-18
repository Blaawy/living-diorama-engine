"""Phase 20 proof package integrity: one inventory, and an executable contract.

Pure Python by design -- this module never imports ``bpy``, so the integrity of a
delivered Phase 20 package can be re-verified by a reviewer on any machine with
nothing installed but Python.

The rule is the one Phase 17 established and every phase since has kept,
deliberately unchanged:

    EVERY member of the package except the inventory itself is enumerated,
    with its byte size and its SHA-256.

That makes five failure modes decidable rather than judgement calls -- a missing
member, an unenumerated extra member, a wrong hash, a wrong size, and a manifest
that points at an artifact the package does not carry.

This is a SIBLING of :mod:`proof_package`, :mod:`population_proof_package` and
:mod:`mobility_proof_package`, not a fork of convenience. Each phase's format id,
inventory filename and manifest prefix are baked in at module level and each
earlier phase is locked, so a Phase 20 package carrying a file called
``phase19_proof_package_manifest.json`` would be a lie about what the package is.
Worse, declaring the Phase 20 manifest under an earlier artifact prefix silently
DISABLES the dangling-reference check: the package would still "verify" while its
manifest pointed at a ``.blend`` nobody shipped, which is exactly the defect that
check exists to catch.

Phase 20 widens the reference set rather than narrowing it. The claim of this
phase is a COMPARISON between three authoritative episodes, so all three render
exports are references, alongside the two plan documents every reading, response
and directive is derived from. A reviewer who cannot open episode 1 cannot check
the leg that produced the "the world remembers" result, and a reviewer who cannot
open the plans cannot recompute a single number in the manifest.

Phase 20 also owns one contract no earlier phase needed: COMPARISON DISCIPLINE.
Two stills that are meant to show a changed world must have been taken from the
SAME camera, or the difference a reviewer sees could be the framing rather than
the world. :func:`require_identical_comparison_cameras` makes that checkable
outside Blender, from the manifest's own render table, so the producer and the
gate both hold the same rule and neither has to take the other's word for it.

The inventory's own summary fields are RECOMPUTED here rather than read back out
of the artifact being verified. Its filename, member count, total bytes, manifest
list and complete artifact-reference table are claims the inventory makes about
itself, and a claim checked against itself cannot fail; all are derived again
from the members this module just hashed, and a disagreement is a refusal.
"""

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

from manifest_io import require_clean_utf8_json, write_manifest_json
from proof_package import ProofPackageError, package_members

STATE_RESPONSE_PACKAGE_FORMAT = "living_diorama_phase20_proof_package"
STATE_RESPONSE_PACKAGE_SCHEMA_VERSION = 1

INVENTORY_NAME = "phase20_proof_package_manifest.json"

MANIFEST_ARTIFACT_PREFIX = "living_diorama_phase20"
"""Any JSON member declaring an ``artifact`` beginning with this is treated as
one of the package's own manifests, and its artifact references are checked."""

REFERENCE_KINDS = (
    "blend",
    "source_export_after",
    "source_export_before",
    "source_export_mid",
    "state_response_motion_plans",
    "state_response_plans",
)
"""What a Phase 20 manifest may point at, and therefore what must be packaged.

``blend`` is the world a reviewer opens. The three exports are the authoritative
episodes the whole claim rests on -- and all three are named, because Phase 20's
result is a comparison across the chain rather than a reading of one state; the
"the world remembers" leg is invisible without the middle episode. The two plan
documents carry every reading, response, directive and frame window, so a
manifest naming any of the six without shipping it would be describing something
nobody can check."""

EXPECTED_ARTIFACT_REFERENCE_COUNT = len(REFERENCE_KINDS)
"""Exactly one Phase 20 manifest must carry every reference kind above."""

COMPARISON_PAIRS = (
    ("phase20_world_before.png", "phase20_world_after.png"),
    ("phase20_district_pair_before.png", "phase20_district_pair_after.png"),
)
"""The still pairs whose whole meaning is that only the WORLD changed between them.

Each pair is one camera photographed at two episodes. Moving the camera between
them -- even by a metre, even to make the second frame prettier -- would turn a
proof of a changed world into a pair of unrelated pictures that a reviewer has no
way of comparing. So the pairing is written down here, in a module with no
Blender in it, and both the producer and the gate check it."""


def state_response_members(directory: Path) -> list[Path]:
    """Every packaged file except THIS phase's inventory, in stable name order.

    Deliberately not :func:`proof_package.package_members`, which hides the
    Phase 17 inventory filename. In a Phase 20 package that name is not an
    inventory at all -- it is an ordinary member, and one the borrowed helper
    would drop from both the enumeration and the on-disk comparison, leaving a
    file that could be added, altered or smuggled in without the verifier ever
    hashing it. The locked helper is still called first, for the flat-directory
    and non-empty refusals it owns.

    Args:
        directory: The proof package directory.

    Returns:
        Every member path, sorted by name.

    Raises:
        ProofPackageError: If the directory is not flat, or holds no members.
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

    Keys are ``"<manifest>#<kind>"`` so one manifest can carry all six without
    any of them quietly overwriting another.

    Args:
        directory: The proof package directory.
        members: The member names to consider.

    Returns:
        The reference table, keyed by manifest and kind.

    Raises:
        ProofPackageError: If a JSON member is not readable UTF-8 JSON.
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
        for kind in REFERENCE_KINDS:
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


def _require_complete_artifact_references(references: dict[str, dict]) -> None:
    """Refuse anything other than one complete six-reference manifest.

    Discovery deliberately remains tolerant enough to describe what is on disk.
    Verification is not: omitting a reference object, its path, its SHA-256 or
    its byte count must not make that obligation disappear from the inventory
    merely because :func:`artifact_references` could not extract it.

    Args:
        references: The reference table recomputed from the packaged manifests.

    Raises:
        ProofPackageError: If the references are not exactly one manifest's
            complete set, or any one of them is malformed.
    """
    sources = {reference.get("source") for reference in references.values()}
    kinds = {reference.get("kind") for reference in references.values()}
    complete_shape = (
        len(references) == EXPECTED_ARTIFACT_REFERENCE_COUNT
        and len(sources) == 1
        and kinds == set(REFERENCE_KINDS)
    )
    if not complete_shape:
        raise ProofPackageError(
            "the proof package must declare exactly "
            f"{EXPECTED_ARTIFACT_REFERENCE_COUNT} complete artifact references "
            f"({', '.join(REFERENCE_KINDS)}); found {sorted(references)}"
        )

    for source, reference in sorted(references.items()):
        path = reference.get("path")
        digest = reference.get("sha256")
        size = reference.get("bytes")
        if (
            not isinstance(path, str)
            or not path
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
        ):
            raise ProofPackageError(
                "the proof package must declare exactly "
                f"{EXPECTED_ARTIFACT_REFERENCE_COUNT} complete artifact references; "
                f"{source} is missing a non-empty path, lowercase SHA-256, or positive byte count"
            )


def require_rendered_stills(directory: str | Path, names: Iterable[str]) -> list[Path]:
    """Resolve every still the proof was told to deliver, or refuse.

    A still that the render never produced must stop the run where it failed.
    The alternative -- carrying on and letting the manifest name a frame nobody
    shipped -- is the defect Phase 19's contact sheet taught: missing evidence
    that is indistinguishable from evidence that was never promised.

    Args:
        directory: The proof directory.
        names: The still filenames the proof promises.

    Returns:
        The resolved paths, in the order given.

    Raises:
        ProofPackageError: If the list is empty, or names a file the render
            never produced.
    """
    directory = Path(directory)
    ordered = list(names)
    if not ordered:
        raise ProofPackageError("a Phase 20 proof must be told which stills it delivers")
    absent = [name for name in ordered if not (directory / name).is_file()]
    if absent:
        raise ProofPackageError(
            f"the proof was told to deliver stills the render never produced: {absent}"
        )
    return [directory / name for name in ordered]


def require_identical_comparison_cameras(
    renders: Iterable[dict], pairs: Iterable[tuple[str, str]] = COMPARISON_PAIRS
) -> dict[str, str]:
    """Refuse a before/after pair that was not photographed from ONE camera.

    This is the whole evidentiary value of Phase 20's stills. The claim is that
    the world changed between two episodes; the only way a reviewer can see that
    is to compare two frames in which nothing else did. A camera nudged between
    them makes every difference in the frame ambiguous, and -- unlike a missing
    file -- it leaves no trace at all in the delivered package. So the pairing is
    checked against the manifest's own render table, where the camera each frame
    was taken from is recorded.

    Args:
        renders: The manifest's render entries, each with ``file`` and ``camera``.
        pairs: The still pairs that must share a camera.

    Returns:
        A mapping of ``"<first>|<second>"`` to the shared camera name.

    Raises:
        ProofPackageError: If a paired still is missing from the render table,
            recorded twice, or was taken from a different camera than its twin.
    """
    by_file: dict[str, str] = {}
    for entry in renders:
        if not isinstance(entry, dict):
            raise ProofPackageError(f"the render table carries a malformed entry: {entry!r}")
        name = entry.get("file")
        camera = entry.get("camera")
        if not isinstance(name, str) or not isinstance(camera, str) or not camera:
            raise ProofPackageError(f"the render table entry {entry!r} names no file and camera")
        if name in by_file:
            raise ProofPackageError(
                f"the render table records {name!r} twice; which camera it was taken from "
                "is then a matter of opinion"
            )
        by_file[name] = camera

    shared: dict[str, str] = {}
    for first, second in pairs:
        missing = sorted(name for name in (first, second) if name not in by_file)
        if missing:
            raise ProofPackageError(
                f"the comparison pair ({first}, {second}) is incomplete; the render table "
                f"never mentions {missing}"
            )
        if by_file[first] != by_file[second]:
            raise ProofPackageError(
                f"the comparison stills {first!r} and {second!r} were taken from "
                f"{by_file[first]!r} and {by_file[second]!r}; a before/after pair must be one "
                "camera at two episodes, or the difference a reviewer sees is the framing "
                "rather than the world"
            )
        shared[f"{first}|{second}"] = by_file[first]
    if not shared:
        raise ProofPackageError("a Phase 20 proof must declare at least one comparison pair")
    return shared


def write_state_response_inventory(directory: str | Path) -> Path:
    """Write the authoritative inventory of one Phase 20 proof package.

    Called last, once every member exists, so the inventory describes the
    package that is actually delivered rather than the one that was partway
    through being made.

    Args:
        directory: The proof package directory.

    Returns:
        The path the inventory was written to.

    Raises:
        ProofPackageError: If the package holds no members.
    """
    directory = Path(directory)
    entries: dict[str, dict] = {}
    total = 0
    for member in state_response_members(directory):
        digest, size = _digest(member)
        entries[member.name] = {"sha256": digest, "bytes": size}
        total += size
    if not entries:
        raise ProofPackageError(f"{directory} holds no proof members")
    references = artifact_references(directory, entries)
    inventory = {
        "artifact": STATE_RESPONSE_PACKAGE_FORMAT,
        "schema_version": STATE_RESPONSE_PACKAGE_SCHEMA_VERSION,
        "inventory_file": INVENTORY_NAME,
        "member_count": len(entries),
        "total_bytes": total,
        "members": entries,
        "manifests": sorted(references),
        "artifact_references": references,
    }
    target = directory / INVENTORY_NAME
    write_manifest_json(target, inventory)
    return target


def verify_state_response_inventory(
    directory: str | Path,
    required: Iterable[str] = (),
    *,
    exact_required: bool = False,
) -> dict:
    """Refuse any Phase 20 proof package that disagrees with its own inventory.

    Checks, in order: the inventory parses as strict UTF-8 JSON with no BOM and
    declares this format; the enumerated set is exactly the set on disk (so a
    missing member and an unenumerated extra are both caught); every member's
    byte size and SHA-256 match; the recorded ``total_bytes`` equals the sizes
    just measured; every required member is present; every artifact a packaged
    manifest points at is itself a packaged member with the hash that manifest
    recorded; the comparison stills were taken from one camera per pair; the
    inventory's own filename, member count, manifest list and artifact-reference
    table are recomputed; and, when ``exact_required`` is true, the
    required-member set is the ENTIRE package contract rather than a minimum
    list that permits unrelated extras.

    Those inventory-summary checks are recomputations. Returning a count,
    ``total_bytes`` or reference table verbatim out of the inventory would check
    the artifact against itself: any value could be written there and the
    package would still "verify", and the gate would then print that unverified
    value as though the verifier had stood behind it.

    Args:
        directory: The proof package directory.
        required: Members the package must carry.
        exact_required: Whether ``required`` is the entire contract.

    Returns:
        The recomputed summary of the verified package.

    Raises:
        ProofPackageError: On the first inconsistency found.
    """
    directory = Path(directory)
    inventory_path = directory / INVENTORY_NAME
    if not inventory_path.exists():
        raise ProofPackageError(f"the package has no inventory at {INVENTORY_NAME}")
    inventory = require_clean_utf8_json(inventory_path)
    if inventory.get("artifact") != STATE_RESPONSE_PACKAGE_FORMAT:
        raise ProofPackageError(
            f"the inventory declares artifact {inventory.get('artifact')!r}, "
            f"expected {STATE_RESPONSE_PACKAGE_FORMAT!r}"
        )
    if inventory.get("schema_version") != STATE_RESPONSE_PACKAGE_SCHEMA_VERSION:
        raise ProofPackageError(
            f"inventory schema_version must be {STATE_RESPONSE_PACKAGE_SCHEMA_VERSION}, "
            f"got {inventory.get('schema_version')!r}"
        )
    if inventory.get("inventory_file") != INVENTORY_NAME:
        raise ProofPackageError(
            f"inventory_file must be {INVENTORY_NAME!r}, got {inventory.get('inventory_file')!r}"
        )
    entries = inventory.get("members")
    if not isinstance(entries, dict) or not entries:
        raise ProofPackageError("the inventory enumerates no members")
    if inventory.get("member_count") != len(entries):
        raise ProofPackageError(
            f"the inventory records member_count {inventory.get('member_count')!r}; "
            f"its member table contains {len(entries)}"
        )

    on_disk = {member.name for member in state_response_members(directory)}
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

    measured_bytes = 0
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
        measured_bytes += size

    if inventory.get("total_bytes") != measured_bytes:
        raise ProofPackageError(
            f"the inventory records {inventory.get('total_bytes')!r} total bytes; the members "
            f"it enumerates hold {measured_bytes}"
        )

    required_set = set(required)
    absent = sorted(required_set - enumerated)
    if absent:
        raise ProofPackageError(f"the proof package is missing required members: {absent}")
    if exact_required:
        unexpected = sorted(enumerated - required_set)
        if unexpected:
            raise ProofPackageError(
                f"the authoritative proof package carries unexpected members: {unexpected}"
            )

    references = artifact_references(directory, enumerated)
    _require_complete_artifact_references(references)
    declared = inventory.get("manifests")
    measured_manifests = sorted(references)
    if not isinstance(declared, list) or sorted(declared) != measured_manifests:
        raise ProofPackageError(
            f"the inventory records manifests {declared!r}; the package's own "
            f"manifests declare {measured_manifests}"
        )
    declared_references = inventory.get("artifact_references")
    if declared_references != references:
        raise ProofPackageError(
            f"the inventory's artifact_references disagree with the "
            f"{EXPECTED_ARTIFACT_REFERENCE_COUNT} references recomputed from the packaged manifest"
        )

    for source, reference in sorted(references.items()):
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

    manifest_name = sorted({reference["source"] for reference in references.values()})[0]
    manifest = require_clean_utf8_json(directory / manifest_name)
    cameras = require_identical_comparison_cameras(manifest.get("renders") or [])

    return {
        "comparison_cameras": cameras,
        "member_count": len(entries),
        "total_bytes": measured_bytes,
        "manifests": measured_manifests,
        "artifact_references": {
            source: reference["path"] for source, reference in references.items()
        },
        "verified": True,
    }


__all__ = [
    "COMPARISON_PAIRS",
    "EXPECTED_ARTIFACT_REFERENCE_COUNT",
    "INVENTORY_NAME",
    "MANIFEST_ARTIFACT_PREFIX",
    "REFERENCE_KINDS",
    "STATE_RESPONSE_PACKAGE_FORMAT",
    "STATE_RESPONSE_PACKAGE_SCHEMA_VERSION",
    "artifact_references",
    "require_identical_comparison_cameras",
    "require_rendered_stills",
    "state_response_members",
    "verify_state_response_inventory",
    "write_state_response_inventory",
]
