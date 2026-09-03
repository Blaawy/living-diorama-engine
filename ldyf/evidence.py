"""Sealed evidence documents — the identities the ledger binds to.

A provenance string is not evidence. `source: "simulation"` is a *claim* that a
simulation produced something, and any caller — including an LLM — can type it.
This module exists so the ledger can bind to **identities of sealed documents**
instead of to claims about them.

Two document kinds are sealed here:

* **rule_manifest** — the Director's declared independent variable for an
  episode. Sealed before the run, so the rule cannot be chosen after seeing the
  result.
* **simulation_result** — what a run actually produced, including the hashes of
  the artefacts it wrote.

Sealing is the same canonical-JSON SHA-256 used for world state: the document is
hashed with its own hash field blanked, so the hash covers content and nothing
else. Re-formatting a file cannot change its identity; changing one character
of content always does.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

RULE_MANIFEST_VERSION = "rule_manifest_v1"
SIMULATION_RESULT_VERSION = "simulation_result_v1"


class EvidenceError(RuntimeError):
    """Raised when a document is not sealed, or its seal does not verify."""


def _canonical(doc: dict[str, Any], hash_field: str) -> bytes:
    d = copy.deepcopy(doc)
    d[hash_field] = ""
    try:
        # allow_nan=False: identical to the ledger's canonicaliser. A NaN would
        # otherwise seal "successfully" and detonate later inside the doors.
        return json.dumps(
            d, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
    except ValueError as e:
        raise EvidenceError(f"document contains a non-finite number and cannot be sealed: {e}") from e


# --- generic seal/verify --------------------------------------------------


def compute_hash(doc: dict[str, Any], hash_field: str) -> str:
    return hashlib.sha256(_canonical(doc, hash_field)).hexdigest()


def _seal(doc: dict[str, Any], hash_field: str, expected_version: str) -> dict[str, Any]:
    if doc.get("schema_version") != expected_version:
        raise EvidenceError(
            f"expected schema_version {expected_version!r}, got {doc.get('schema_version')!r}"
        )
    out = copy.deepcopy(doc)
    out[hash_field] = compute_hash(out, hash_field)
    return out


def _verify(doc: dict[str, Any], hash_field: str, expected_version: str, what: str) -> None:
    if not isinstance(doc, dict):
        raise EvidenceError(f"{what} must be a document, got {type(doc).__name__}")
    if doc.get("schema_version") != expected_version:
        raise EvidenceError(
            f"{what}: expected schema_version {expected_version!r}, "
            f"got {doc.get('schema_version')!r}"
        )
    stored = doc.get(hash_field)
    if not isinstance(stored, str) or len(stored) != 64:
        raise EvidenceError(
            f"{what} is not sealed: {hash_field} is {stored!r}. "
            "An unsealed document can never be admitted as evidence."
        )
    actual = compute_hash(doc, hash_field)
    if stored != actual:
        raise EvidenceError(
            f"{what} seal does not verify: stored={stored} computed={actual}. "
            "The document was modified after it was sealed."
        )


# --- rule manifest --------------------------------------------------------


_SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
_RULE_SCHEMA_CACHE: dict[str, Any] | None = None


def _rule_schema_validator():
    """The ONE RULE contract, loaded once from the package's own schema."""
    global _RULE_SCHEMA_CACHE
    from jsonschema import Draft202012Validator

    if _RULE_SCHEMA_CACHE is None:
        _RULE_SCHEMA_CACHE = json.loads(
            (_SCHEMA_DIR / "rule_manifest.schema.json").read_text(encoding="utf-8")
        )
    return Draft202012Validator(_RULE_SCHEMA_CACHE)


def _check_rule_contract(doc: dict[str, Any]) -> None:
    """A rule that does not satisfy the ONE RULE contract cannot be sealed.

    This is what makes `declared_utc`, `baseline_required` and a
    before-the-run `prediction` load-bearing rather than decorative: the ledger
    binds only to sealed manifests, and only contract-complete manifests seal.
    """
    if not isinstance(doc, dict):
        raise EvidenceError("rule_manifest must be a document")
    errors = sorted(_rule_schema_validator().iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        e = errors[0]
        where = "/".join(str(x) for x in e.path) or "<root>"
        raise EvidenceError(
            f"rule_manifest violates the ONE RULE contract at {where}: {e.message}"
        )


def seal_rule_manifest(doc: dict[str, Any]) -> dict[str, Any]:
    _check_rule_contract(doc)
    return _seal(doc, "manifest_hash", RULE_MANIFEST_VERSION)


def verify_rule_manifest(doc: dict[str, Any]) -> None:
    _verify(doc, "manifest_hash", RULE_MANIFEST_VERSION, "rule_manifest")
    _check_rule_contract(doc)


# --- simulation result ----------------------------------------------------


_RESULT_REQUIRED = ("run_id", "episode_number", "arm", "seed", "sumo_version", "artifacts")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def _check_result_shape(doc: dict[str, Any]) -> None:
    for f in _RESULT_REQUIRED:
        if f not in doc:
            raise EvidenceError(f"simulation_result is missing required field {f!r}")
    if doc["arm"] not in ("baseline", "ruled"):
        raise EvidenceError(f"simulation_result.arm must be 'baseline' or 'ruled', got {doc['arm']!r}")
    arts = doc.get("artifacts")
    if not isinstance(arts, dict) or not arts:
        raise EvidenceError("simulation_result.artifacts must name at least one sealed artefact")
    for name, meta in arts.items():
        if not isinstance(meta, dict) or not isinstance(meta.get("sha256"), str) \
                or not _HEX64_RE.match(meta["sha256"]):
            raise EvidenceError(f"artifact {name!r} must carry a 64-hex sha256")
        rel = str(meta.get("file", name))
        if rel.startswith(("/", "\\")) or ".." in Path(rel).parts or ":" in rel:
            raise EvidenceError(f"artifact {name!r} file path must be relative and traversal-free")


def seal_simulation_result(doc: dict[str, Any]) -> dict[str, Any]:
    _check_result_shape(doc)
    return _seal(doc, "result_hash", SIMULATION_RESULT_VERSION)


def verify_simulation_result(doc: dict[str, Any]) -> None:
    _verify(doc, "result_hash", SIMULATION_RESULT_VERSION, "simulation_result")
    _check_result_shape(doc)


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_artifact_on_disk(result: dict[str, Any], name: str, base_dir: str | Path) -> Path:
    """Resolve one artefact named by a sealed result and check its bytes.

    This is the step that stops a caller pointing a real result document at a
    file someone edited afterwards.
    """
    arts = result.get("artifacts", {})
    if name not in arts:
        raise EvidenceError(f"simulation_result names no artefact {name!r}")
    meta = arts[name]
    path = Path(base_dir) / meta.get("file", name)
    if not path.exists():
        raise EvidenceError(f"artefact {name!r} not found on disk at {path}")
    actual = sha256_file(path)
    if actual != meta["sha256"]:
        raise EvidenceError(
            f"artefact {name!r} does not match the sealed result: "
            f"on disk {actual}, sealed {meta['sha256']}"
        )
    return path
