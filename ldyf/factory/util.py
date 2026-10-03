"""Canonical bytes, hashing and sealed JSON documents for the factory.

One serialiser for every factory document, pinned by test to the three
canonical serialisers that already exist (`world_state.canonical_bytes`,
`evidence._canonical`, `persistent_changes._canonical`): sorted keys, compact
separators, UTF-8, NaN and Infinity refused. A document is SEALED by storing
the sha256 of its canonical bytes with the hash field blanked, which is the
convention every earlier phase uses.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from . import FactoryError


class SealError(FactoryError):
    stage = "seal"


def canonical_bytes(doc: Any) -> bytes:
    try:
        return json.dumps(doc, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as e:
        raise SealError("not_canonical", f"document cannot be serialised canonically: {e}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def doc_hash(doc: dict[str, Any], hash_field: str) -> str:
    body = dict(doc)
    body[hash_field] = ""
    return sha256_bytes(canonical_bytes(body))


def seal(doc: dict[str, Any], hash_field: str) -> dict[str, Any]:
    out = dict(doc)
    out[hash_field] = doc_hash(out, hash_field)
    return out


def verify_seal(doc: Any, hash_field: str, what: str) -> None:
    if not isinstance(doc, dict):
        raise SealError("not_an_object", f"{what} is not a JSON object")
    have = doc.get(hash_field)
    if not isinstance(have, str) or len(have) != 64:
        raise SealError("unsealed", f"{what} carries no {hash_field}")
    want = doc_hash(doc, hash_field)
    if have != want:
        raise SealError(
            "seal_broken",
            f"{what}: {hash_field} is {have[:12]}.. but its content hashes to {want[:12]}..; "
            "the document was changed after it was sealed")


def write_json(path: str | Path, doc: Any) -> str:
    """Write a document deterministically (and atomically); returns its sha256.

    Atomic because a stage interrupted half-way through a write must leave
    either the old file or the new one, never a truncated document that a
    resume would then have to guess about.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = (json.dumps(doc, sort_keys=True, indent=1, ensure_ascii=False,
                           allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as e:
        raise SealError("not_canonical", f"{path.name} cannot be written canonically: {e}")
    _replace_atomically(path, data)
    return sha256_bytes(data)


def write_text(path: str | Path, text: str) -> str:
    """A text artefact (captions), written like a document: atomically, typed refusal."""
    data = text.encode("utf-8")
    _replace_atomically(Path(path), data)
    return sha256_bytes(data)


def _replace_atomically(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(data)
    except OSError as e:
        raise SealError("write_failed", f"{path.name} could not be written: {e}")
    # On Windows the replace is refused while another process (a scanner, an
    # indexer) holds the old file open for a moment. Wait it out; if it never
    # lets go, refuse with a typed error rather than a traceback, and leave no
    # .tmp behind.
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as e:
            if attempt == 19:
                tmp.unlink(missing_ok=True)
                # A reader that keeps the file open without delete-sharing (seen: a
                # file-watching tool holding a handle for an hour) blocks the replace
                # for good, but not a write in place. Fall back to that and read it
                # back. It is not atomic; a write torn by an interruption leaves a
                # document whose seal no longer verifies, which every reader refuses
                # and a resume recomputes.
                try:
                    with path.open("r+b") as f:
                        f.truncate(0)
                        f.write(data)
                        f.flush()
                        os.fsync(f.fileno())
                    if path.read_bytes() == data:
                        return
                except OSError:
                    pass
                raise SealError("write_failed", f"{path.name} could not be replaced: {e}")
            time.sleep(0.25)
        except OSError as e:
            tmp.unlink(missing_ok=True)
            raise SealError("write_failed", f"{path.name} could not be replaced: {e}")


def read_json(path: str | Path, what: str, *, error=SealError) -> Any:
    path = Path(path)
    if not path.is_file():
        raise error("missing", f"{what} is missing: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 - reported as a typed refusal
        raise error("corrupt", f"{what} is not parseable JSON ({path.name}): {e}")
