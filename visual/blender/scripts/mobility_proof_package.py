"""Phase 19 proof package integrity: one inventory, and an executable contract.

Pure Python by design -- this module never imports ``bpy``, so the integrity of
a delivered Phase 19 package can be re-verified by a reviewer on any machine
with nothing installed but Python.

The rule is the one Phase 17 established and Phase 18 kept, deliberately
unchanged:

    EVERY member of the package except the inventory itself is enumerated,
    with its byte size and its SHA-256.

That makes five failure modes decidable rather than judgement calls -- a missing
member, an unenumerated extra member, a wrong hash, a wrong size, and a manifest
that points at an artifact the package does not carry.

This is a SIBLING of :mod:`proof_package` and :mod:`population_proof_package`,
not a fork of convenience. Each phase's format id, inventory filename and
manifest prefix are baked in at module level and each earlier phase is locked,
so a Phase 19 package carrying a file called
``phase18_proof_package_manifest.json`` would be a lie about what the package
is. Worse, declaring the Phase 19 manifest under an earlier artifact prefix
silently DISABLES the dangling-reference check: the package would still
"verify" while its manifest pointed at a ``.blend`` nobody shipped, which is
exactly the defect that check exists to catch.

Phase 19 adds one reference kind of its own. A mobility manifest names the
MOBILITY PLAN it was rendered from, and a reviewer who cannot open that plan
cannot recompute a single claim in the manifest -- not the routes, not the
collision verdict, not the coverage. So the plan is checked like the ``.blend``
and the render export: named, packaged, and hashed.

The inventory's own summary fields are RECOMPUTED here rather than read back out
of the artifact being verified. Its filename, member count, total bytes,
manifest list and complete artifact-reference table are claims the inventory
makes about itself, and a claim checked against itself cannot fail; all are
derived again from the members this module just hashed, and a disagreement is a
refusal.

Phase 19 also owns the contact sheet, whose frame list is a promise about what
the sheet shows. :func:`require_contact_sheet_frames` keeps that promise
checkable outside Blender, so a frame the render never produced stops the proof
instead of quietly shrinking the sheet.
"""

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

from manifest_io import require_clean_utf8_json, write_manifest_json
from proof_package import ProofPackageError, package_members

MOBILITY_PACKAGE_FORMAT = "living_diorama_phase19_proof_package"
MOBILITY_PACKAGE_SCHEMA_VERSION = 1

INVENTORY_NAME = "phase19_proof_package_manifest.json"

MANIFEST_ARTIFACT_PREFIX = "living_diorama_phase19"
"""Any JSON member declaring an ``artifact`` beginning with this is treated as
one of the package's own manifests, and its artifact references are checked."""

REFERENCE_KINDS = ("blend", "source_export", "mobility_plan")
"""What a Phase 19 manifest may point at, and therefore what must be packaged.

``blend`` is the world a reviewer opens, ``source_export`` the authoritative
render export the population claim rests on, and ``mobility_plan`` the document
every route, speed and collision verdict is derived from. A manifest naming any
of the three without shipping it would be describing something nobody can
check."""

EXPECTED_ARTIFACT_REFERENCE_COUNT = len(REFERENCE_KINDS)
"""Exactly one Phase 19 manifest must carry every reference kind above."""

VIDEO_SUFFIXES = frozenset((".mp4", ".mkv", ".avi"))
MINIMUM_CLIP_BYTES = 1024
"""A 193-frame proof clip cannot honestly be a container-header-sized stub."""


def mobility_members(directory: Path) -> list[Path]:
    """Every packaged file except THIS phase's inventory, in stable name order.

    Deliberately not :func:`proof_package.package_members`, which hides the
    Phase 17 inventory filename. In a Phase 19 package that name is not an
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

    Keys are ``"<manifest>#<kind>"`` so one manifest can carry all three
    without any of them quietly overwriting another.
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
    """Refuse anything other than one complete three-reference manifest.

    Discovery deliberately remains tolerant enough to describe what is on
    disk. Verification is not: omitting a reference object, its path, its
    SHA-256 or its byte count must not make that obligation disappear from the
    inventory merely because :func:`artifact_references` could not extract it.
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
            "the proof package must declare exactly three complete artifact references "
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
                "the proof package must declare exactly three complete artifact references; "
                f"{source} is missing a non-empty path, lowercase SHA-256, or positive byte count"
            )


def require_contact_sheet_frames(directory: str | Path, names: Iterable[str]) -> list[Path]:
    """Resolve every frame a contact sheet was told to show, or refuse.

    The sheet is the one page a reviewer scans before opening anything, and it
    used to be composed by skipping any named frame that was not on disk. A gait
    render that failed therefore produced a SMALLER sheet, a manifest naming a
    frame nobody shipped, and a gate that still printed PASS -- the missing
    evidence was indistinguishable from a sheet that had always held five tiles.
    A sheet is told which frames it shows, so a frame it cannot find is a
    refusal rather than a quieter sheet.

    Raises:
        ProofPackageError: If the frame list is empty, or names a file the
            render never produced.
    """
    directory = Path(directory)
    ordered = list(names)
    if not ordered:
        raise ProofPackageError("a contact sheet must be told which frames it shows")
    absent = [name for name in ordered if not (directory / name).is_file()]
    if absent:
        raise ProofPackageError(
            f"the contact sheet was told to show frames the render never produced: {absent}"
        )
    return [directory / name for name in ordered]


def clip_outputs(path: str | Path) -> list[Path]:
    """Every video file Blender could have emitted for one proof-clip stem."""
    path = Path(path)
    stem = path.with_suffix("").name
    return [
        candidate
        for candidate in sorted(path.parent.glob(f"{stem}*"), key=lambda item: item.name)
        if candidate.is_file() and candidate.suffix.lower() in VIDEO_SUFFIXES
    ]


def clear_clip_outputs(path: str | Path) -> None:
    """Remove only prior video outputs for one clip stem before rendering it.

    Blender appends a frame range to animation filenames. An aborted render can
    therefore leave a numbered stub beside the canonical clip; if both survive
    into the next run, selecting by filename order can overwrite the fresh
    render with the stale stub while the inventory still verifies it faithfully.
    """
    for candidate in clip_outputs(path):
        candidate.unlink()


def finalize_clip_output(path: str | Path) -> Path:
    """Canonicalize exactly one fresh Blender video output, or refuse it."""
    path = Path(path)
    candidates = clip_outputs(path)
    if len(candidates) != 1:
        raise ProofPackageError(
            f"the render for {path.name} produced {len(candidates)} video files: "
            f"{[candidate.name for candidate in candidates]}"
        )
    produced = candidates[0]
    if produced != path:
        produced.replace(path)
    size = path.stat().st_size
    if size < MINIMUM_CLIP_BYTES:
        raise ProofPackageError(
            f"the render for {path.name} is only {size} bytes; expected at least "
            f"{MINIMUM_CLIP_BYTES}"
        )
    return path


def write_mobility_inventory(directory: str | Path) -> Path:
    """Write the authoritative inventory of one Phase 19 proof package.

    Called last, once every member exists, so the inventory describes the
    package that is actually delivered rather than the one that was partway
    through being made.
    """
    directory = Path(directory)
    entries: dict[str, dict] = {}
    total = 0
    for member in mobility_members(directory):
        digest, size = _digest(member)
        entries[member.name] = {"sha256": digest, "bytes": size}
        total += size
    if not entries:
        raise ProofPackageError(f"{directory} holds no proof members")
    references = artifact_references(directory, entries)
    inventory = {
        "artifact": MOBILITY_PACKAGE_FORMAT,
        "schema_version": MOBILITY_PACKAGE_SCHEMA_VERSION,
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


def verify_mobility_inventory(
    directory: str | Path,
    required: Iterable[str] = (),
    *,
    exact_required: bool = False,
) -> dict:
    """Refuse any Phase 19 proof package that disagrees with its own inventory.

    Checks, in order: the inventory parses as strict UTF-8 JSON with no BOM and
    declares this format; the enumerated set is exactly the set on disk (so a
    missing member and an unenumerated extra are both caught); every member's
    byte size and SHA-256 match; the recorded ``total_bytes`` equals the sizes
    just measured; every required member is present; every artifact a packaged
    manifest points at is itself a packaged member with the hash that manifest
    recorded; the inventory's own filename, member count, manifest list and
    artifact-reference table are recomputed; and, when ``exact_required`` is
    true, the required-member set is the ENTIRE package contract rather than a
    minimum list that permits unrelated extras.

    Those inventory-summary checks are recomputations. Returning a count,
    ``total_bytes`` or reference table verbatim out of the inventory, as this
    function once did, checked the artifact against itself: any value could be
    written there and the package would still "verify", and the gate would then
    print that unverified value as though the verifier had stood behind it.

    Raises:
        ProofPackageError: On the first inconsistency found.
    """
    directory = Path(directory)
    inventory_path = directory / INVENTORY_NAME
    if not inventory_path.exists():
        raise ProofPackageError(f"the package has no inventory at {INVENTORY_NAME}")
    inventory = require_clean_utf8_json(inventory_path)
    if inventory.get("artifact") != MOBILITY_PACKAGE_FORMAT:
        raise ProofPackageError(
            f"the inventory declares artifact {inventory.get('artifact')!r}, "
            f"expected {MOBILITY_PACKAGE_FORMAT!r}"
        )
    if inventory.get("schema_version") != MOBILITY_PACKAGE_SCHEMA_VERSION:
        raise ProofPackageError(
            f"inventory schema_version must be {MOBILITY_PACKAGE_SCHEMA_VERSION}, "
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

    on_disk = {member.name for member in mobility_members(directory)}
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
            "the inventory's artifact_references disagree with the three references "
            "recomputed from the packaged manifest"
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

    return {
        "member_count": len(entries),
        "total_bytes": measured_bytes,
        "manifests": measured_manifests,
        "artifact_references": {
            source: reference["path"] for source, reference in references.items()
        },
        "verified": True,
    }
