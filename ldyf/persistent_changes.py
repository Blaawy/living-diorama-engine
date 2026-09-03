"""THE WORLD REMEMBERS, generalised -- the append-only change ledger.

The old engine remembered exactly one kind of durable change: a wall. This
module generalises that to every durable change the new world can undergo --
closures, permissions, speed limits, signal programmes, infrastructure -- while
keeping the property that made the original good: **the scar outlives the rule
that made it.**

Three laws, enforced structurally rather than by convention (DNA-03):

1. **Append only.** This module exposes no function that deletes or edits an
   entry. Undoing a change means appending a `reversal` that names it; the
   original entry stays in the ledger forever.
2. **Hash chained.** Every entry carries `prev_hash`, so reordering, editing or
   removing any entry invalidates every entry after it and `verify_ledger`
   says exactly which one broke.
3. **Provenance required.** An entry must name where its truth came from --
   `simulation` or `director_rule`. There is no code path by which prose, an
   LLM, or an unattributed assertion becomes a remembered fact (DNA-07).
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "persistent_changes_v1"
GENESIS_HASH = "0" * 64

CHANGE_TYPES = (
    "edge_closure",
    "lane_closure",
    "access_permission",
    "speed_limit",
    "traffic_light_program",
    "infrastructure_added",
    "infrastructure_removed",
    "reversal",
)

# Which payload `kind` each change_type must carry.
_PAYLOAD_KIND = {
    "edge_closure": "edge_closure",
    "lane_closure": "lane_closure",
    "access_permission": "access_permission",
    "speed_limit": "speed_limit",
    "traffic_light_program": "traffic_light_program",
    "infrastructure_added": "infrastructure",
    "infrastructure_removed": "infrastructure",
    "reversal": "reversal",
}

_REQUIRED_PAYLOAD_FIELDS = {
    "edge_closure": ("edge_ids", "disallow"),
    "lane_closure": ("lane_ids", "disallow"),
    "access_permission": ("target_kind", "target_ids", "allow", "disallow"),
    "speed_limit": ("target_kind", "target_ids", "mps"),
    "traffic_light_program": ("tls_id", "program_id"),
    "infrastructure": ("infra_id", "infra_kind", "operation"),
    "reversal": ("reverses_change_id",),
}

PEDESTRIAN_VCLASS = "pedestrian"


class LedgerError(RuntimeError):
    """Raised when the ledger is invalid. Never downgraded to a warning."""


# --- hashing --------------------------------------------------------------


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def compute_entry_hash(entry: dict[str, Any]) -> str:
    """Hash an entry over everything except its own hash field."""
    d = copy.deepcopy(entry)
    d.pop("entry_hash", None)
    return hashlib.sha256(_canonical(d)).hexdigest()


def compute_ledger_hash(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return GENESIS_HASH
    return hashlib.sha256(_canonical([e["entry_hash"] for e in entries])).hexdigest()


def make_change_id(
    *, world_id: str, origin_episode: int, change_type: str, payload: dict[str, Any], nonce: int = 0
) -> str:
    """Deterministic, stable identity.

    Derived from content rather than a counter, so the same change proposed by
    the same episode always gets the same id and a rebuild cannot renumber
    history.
    """
    seed = _canonical(
        {
            "world_id": world_id,
            "origin_episode": origin_episode,
            "change_type": change_type,
            "payload": payload,
            "nonce": nonce,
        }
    )
    return "chg_" + hashlib.sha256(seed).hexdigest()[:16]


# --- validation -----------------------------------------------------------


def _validate_payload(change_type: str, payload: dict[str, Any]) -> None:
    expected_kind = _PAYLOAD_KIND[change_type]
    kind = payload.get("kind")
    if kind != expected_kind:
        raise LedgerError(
            f"change_type {change_type!r} requires payload kind {expected_kind!r}, got {kind!r}"
        )
    for f in _REQUIRED_PAYLOAD_FIELDS[expected_kind]:
        if f not in payload:
            raise LedgerError(f"payload for {change_type!r} is missing required field {f!r}")

    if change_type in ("edge_closure", "lane_closure", "access_permission"):
        if PEDESTRIAN_VCLASS in payload.get("disallow", []):
            raise LedgerError(
                "refusing to record a change that bars pedestrians: closing a "
                "carriageway does not close the footway, and barring pedestrians "
                "crashes SUMO 1.27.1 (RISK-1)"
            )
    if change_type == "infrastructure_added" and payload.get("operation") != "added":
        raise LedgerError("infrastructure_added must carry operation 'added'")
    if change_type == "infrastructure_removed" and payload.get("operation") != "removed":
        raise LedgerError("infrastructure_removed must carry operation 'removed'")
    if change_type == "speed_limit" and not payload.get("mps", 0) > 0:
        raise LedgerError("speed_limit requires a positive mps")


def _validate_provenance(prov: dict[str, Any]) -> None:
    src = prov.get("source")
    if src not in ("simulation", "director_rule"):
        raise LedgerError(
            f"provenance.source must be 'simulation' or 'director_rule', got {src!r}. "
            "An unattributed or LLM-authored change may never be remembered."
        )
    if not prov.get("run_id"):
        raise LedgerError("provenance.run_id is required")


# --- construction ---------------------------------------------------------


def new_ledger(world_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "world_id": world_id,
        "entries": [],
        "ledger_hash": GENESIS_HASH,
    }


def append_change(
    ledger: dict[str, Any],
    *,
    change_type: str,
    origin_episode: int,
    applied_at_sim_second: float,
    payload: dict[str, Any],
    provenance: dict[str, Any],
    rule_id: str | None = None,
    reverses: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Append one change. Returns (new_ledger, change_id).

    The input ledger is not mutated -- a caller cannot accidentally half-write
    history.
    """
    if change_type not in CHANGE_TYPES:
        raise LedgerError(f"unknown change_type {change_type!r}")
    _validate_payload(change_type, payload)
    _validate_provenance(provenance)

    entries = list(ledger["entries"])

    if change_type == "reversal":
        target = payload["reverses_change_id"]
        known = {e["change_id"] for e in entries}
        if target not in known:
            raise LedgerError(f"cannot reverse unknown change {target!r}")
        already = [e for e in entries if e.get("reverses") == target]
        if already:
            raise LedgerError(f"change {target!r} was already reversed by {already[0]['change_id']}")
        reverses = target

    # Stable id; nonce only disambiguates a genuinely identical repeat.
    nonce = 0
    while True:
        cid = make_change_id(
            world_id=ledger["world_id"],
            origin_episode=origin_episode,
            change_type=change_type,
            payload=payload,
            nonce=nonce,
        )
        if cid not in {e["change_id"] for e in entries}:
            break
        nonce += 1

    entry = {
        "change_id": cid,
        "change_type": change_type,
        "origin_episode": origin_episode,
        "applied_at_sim_second": applied_at_sim_second,
        "rule_id": rule_id,
        "reverses": reverses,
        "provenance": provenance,
        "payload": payload,
        "prev_hash": entries[-1]["entry_hash"] if entries else GENESIS_HASH,
    }
    entry["entry_hash"] = compute_entry_hash(entry)
    entries.append(entry)

    out = dict(ledger)
    out["entries"] = entries
    out["ledger_hash"] = compute_ledger_hash(entries)
    return out, cid


# --- verification ---------------------------------------------------------


def verify_ledger(ledger: dict[str, Any]) -> None:
    """Raise LedgerError naming the first entry that fails."""
    if ledger.get("schema_version") != SCHEMA_VERSION:
        raise LedgerError(f"unexpected schema_version {ledger.get('schema_version')!r}")

    entries = ledger.get("entries", [])
    prev = GENESIS_HASH
    seen: set[str] = set()
    for i, e in enumerate(entries):
        cid = e.get("change_id")
        if cid in seen:
            raise LedgerError(f"duplicate change_id {cid!r} at index {i}")
        seen.add(cid)
        if e.get("prev_hash") != prev:
            raise LedgerError(
                f"chain broken at index {i} ({cid}): prev_hash={e.get('prev_hash')!r} "
                f"expected {prev!r}"
            )
        recomputed = compute_entry_hash(e)
        if e.get("entry_hash") != recomputed:
            raise LedgerError(f"entry {cid!r} at index {i} was modified after it was written")
        _validate_payload(e["change_type"], e["payload"])
        _validate_provenance(e["provenance"])
        prev = e["entry_hash"]

    if ledger.get("ledger_hash") != compute_ledger_hash(entries):
        raise LedgerError("ledger_hash does not match the entry chain")


def is_active(ledger: dict[str, Any], change_id: str) -> bool:
    """True when a change is still in force (recorded and not reversed)."""
    ids = {e["change_id"] for e in ledger["entries"]}
    if change_id not in ids:
        raise LedgerError(f"unknown change {change_id!r}")
    return not any(e.get("reverses") == change_id for e in ledger["entries"])


def active_changes(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Every non-reversal change still in force, in ledger order."""
    reversed_ids = {e["reverses"] for e in ledger["entries"] if e.get("reverses")}
    return [
        e
        for e in ledger["entries"]
        if e["change_type"] != "reversal" and e["change_id"] not in reversed_ids
    ]


def changes_from_episode(ledger: dict[str, Any], episode: int) -> list[dict[str, Any]]:
    return [e for e in ledger["entries"] if e["origin_episode"] == episode]


def history_of(ledger: dict[str, Any], change_id: str) -> list[dict[str, Any]]:
    """The entry plus anything that later referenced it."""
    return [
        e
        for e in ledger["entries"]
        if e["change_id"] == change_id or e.get("reverses") == change_id
    ]


# --- io -------------------------------------------------------------------


def save(ledger: dict[str, Any], path: str | Path) -> str:
    verify_ledger(ledger)
    Path(path).write_text(
        json.dumps(ledger, indent=2, sort_keys=True, ensure_ascii=True), encoding="utf-8"
    )
    return ledger["ledger_hash"]


def load(path: str | Path) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    verify_ledger(doc)
    return doc
