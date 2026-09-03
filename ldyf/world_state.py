"""THE WORLD REMEMBERS -- the state hash chain.

Inherited directly from the old engine (DNA-02): every episode's world state
carries its own `state_hash` and its parent's. Episode N+1 may only be built
from an episode N whose hash actually verifies. A world cannot silently reset,
and an episode cannot be quietly reordered or forged.

This module is the only writer and the only verifier of that chain.

Canonical serialisation
-----------------------
The hash must be reproducible on any machine, so the bytes hashed are pinned:

    json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

with `state_hash` set to the empty string during hashing. Anything else -- a
different indent, a different key order, a locale-dependent float -- would make
the same world hash differently, which would break inheritance for no reason.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "world_state_v1"
_EMPTY = ""


class ChainError(RuntimeError):
    """Raised when the inheritance chain is broken. Never downgraded to a warning."""


def canonical_bytes(doc: dict[str, Any]) -> bytes:
    """The exact bytes a world state hashes over."""
    d = copy.deepcopy(doc)
    d["state_hash"] = _EMPTY
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def compute_state_hash(doc: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(doc)).hexdigest()


def seal(doc: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `doc` with a correct `state_hash` written in."""
    out = copy.deepcopy(doc)
    out["state_hash"] = compute_state_hash(out)
    return out


def verify(doc: dict[str, Any]) -> bool:
    """True when the document's stored hash matches its content."""
    stored = doc.get("state_hash")
    if not isinstance(stored, str) or len(stored) != 64:
        return False
    return stored == compute_state_hash(doc)


def verify_or_raise(doc: dict[str, Any], *, what: str = "world state") -> None:
    if not verify(doc):
        raise ChainError(
            f"{what} failed hash verification: stored={doc.get('state_hash')!r} "
            f"computed={compute_state_hash(doc)!r}"
        )


def inherit(parent: dict[str, Any], *, episode_number: int | None = None) -> dict[str, Any]:
    """Begin episode N+1 from an accepted episode N.

    Refuses to build on an unverified parent. This is the structural guarantee:
    there is no code path in this module that produces a child of a world whose
    hash does not check out.
    """
    verify_or_raise(parent, what="parent world state")

    child = copy.deepcopy(parent)
    child["parent_state_hash"] = parent["state_hash"]
    child["episode_number"] = (
        parent["episode_number"] + 1 if episode_number is None else episode_number
    )
    if child["episode_number"] <= parent["episode_number"]:
        raise ChainError(
            f"episode number must increase: parent={parent['episode_number']} "
            f"child={child['episode_number']}"
        )

    history = list(parent.get("version_history", []))
    history.append(
        {
            "episode_number": parent["episode_number"],
            "state_hash": parent["state_hash"],
            "created_utc": parent["created_utc"],
        }
    )
    child["version_history"] = history
    child["state_hash"] = _EMPTY
    return child


def verify_lineage(chain: list[dict[str, Any]]) -> None:
    """Verify a whole lineage, oldest first.

    Checks each document's own hash, that each parent pointer resolves to the
    previous document, and that episode numbers strictly increase.
    """
    if not chain:
        raise ChainError("empty lineage")

    for i, doc in enumerate(chain):
        verify_or_raise(doc, what=f"episode {doc.get('episode_number')}")

        if i == 0:
            continue

        prev = chain[i - 1]
        if doc.get("parent_state_hash") != prev["state_hash"]:
            raise ChainError(
                f"episode {doc.get('episode_number')} does not descend from "
                f"episode {prev.get('episode_number')}: "
                f"parent_state_hash={doc.get('parent_state_hash')!r} "
                f"expected={prev['state_hash']!r}"
            )
        if doc["episode_number"] <= prev["episode_number"]:
            raise ChainError(
                f"episode numbers must strictly increase: "
                f"{prev['episode_number']} -> {doc['episode_number']}"
            )


# --- permanence -----------------------------------------------------------


def close_edges(
    doc: dict[str, Any], edge_ids: list[str], *, episode_number: int, reason: str
) -> dict[str, Any]:
    """Record a permanent closure.

    Mirrors the old engine's wall-persistence invariant (DNA-03): closures live
    in the *world*, not in the rule that caused them. This module exposes no
    function that removes a closure, so restoring or reversing a rule cannot
    delete the scar it left. Reopening is a separate, explicitly-recorded act
    that must add a new entry rather than erase the old one.
    """
    out = copy.deepcopy(doc)
    net = out.setdefault("network", {})
    closed = net.setdefault("closed_edges", [])
    existing = {c["edge_id"] for c in closed}
    for eid in edge_ids:
        if eid not in existing:
            closed.append(
                {"edge_id": eid, "closed_in_episode": episode_number, "reason": reason}
            )
    closed.sort(key=lambda c: (c["closed_in_episode"], c["edge_id"]))
    return out


def load(path: str | Path) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    verify_or_raise(doc, what=str(path))
    return doc


def save(doc: dict[str, Any], path: str | Path) -> str:
    """Seal and write. Returns the state hash actually written."""
    sealed = seal(doc)
    Path(path).write_text(
        json.dumps(sealed, indent=2, sort_keys=True, ensure_ascii=True), encoding="utf-8"
    )
    return sealed["state_hash"]
