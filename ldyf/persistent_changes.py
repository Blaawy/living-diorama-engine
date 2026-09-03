"""THE WORLD REMEMBERS, generalised -- the append-only change ledger.

The old engine remembered exactly one kind of durable change: a wall. This
module generalises that to every durable change the new world can undergo --
closures, permissions, speed limits, signal programmes, infrastructure, and
measured effects -- while keeping the property that made the original good:
**the scar outlives the rule that made it.**

SIMULATION CREATES TRUTH, structurally
--------------------------------------
An earlier revision let a caller append an entry carrying
`provenance={"source": "simulation"}`. That was not good enough: the string is a
*claim* that a simulation produced something, and anything -- including an LLM --
can type it. Nothing in the ledger checked it, so "simulation truth" was
whatever the caller said it was.

There is now **no public function that accepts a provenance argument.** Truth
enters through exactly two doors, and both bind to sealed evidence identities:

* `append_director_rule(ledger, rule_manifest=...)`
  The payload is **derived from the sealed manifest's own `change` block**, not
  from caller input. An unsealed or tampered manifest is refused.

* `append_simulation_consequence(ledger, simulation_result=..., extractor_name=...)`
  The caller supplies **evidence, never conclusions**. A named deterministic
  extractor from `CONSEQUENCE_EXTRACTORS` re-reads the sealed artefacts from
  disk, verifies their bytes against the sealed result, and *computes* the
  consequence. Whatever the caller believes happened is irrelevant: the entry
  is built from what the extractor derives.

Reversal is a Director act and goes through `append_reversal`, which also
requires a sealed manifest.

The four laws, enforced structurally (DNA-03)
---------------------------------------------
1. **Append only.** No function deletes or edits an entry. Undoing means
   appending a `reversal`; the original stays forever.
2. **Hash chained.** Every entry carries `prev_hash`.
3. **Evidence-bound.** Every entry stores the identity of the sealed document it
   came from, plus -- for consequences -- the extractor that derived it.
4. **No caller-authored provenance.** The library constructs it.
"""

from __future__ import annotations

import copy
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable

from .evidence import (
    EvidenceError,
    verify_artifact_on_disk,
    verify_rule_manifest,
    verify_simulation_result,
)

SCHEMA_VERSION = "persistent_changes_v2"
GENESIS_HASH = "0" * 64

CHANGE_TYPES = (
    "edge_closure",
    "lane_closure",
    "access_permission",
    "speed_limit",
    "traffic_light_program",
    "infrastructure_added",
    "infrastructure_removed",
    "measured_effect",
    "reversal",
)

_PAYLOAD_KIND = {
    "edge_closure": "edge_closure",
    "lane_closure": "lane_closure",
    "access_permission": "access_permission",
    "speed_limit": "speed_limit",
    "traffic_light_program": "traffic_light_program",
    "infrastructure_added": "infrastructure",
    "infrastructure_removed": "infrastructure",
    "measured_effect": "measured_effect",
    "reversal": "reversal",
}

_REQUIRED_PAYLOAD_FIELDS = {
    "edge_closure": ("edge_ids", "disallow"),
    "lane_closure": ("lane_ids", "disallow"),
    "access_permission": ("target_kind", "target_ids", "allow", "disallow"),
    "speed_limit": ("target_kind", "target_ids", "mps"),
    "traffic_light_program": ("tls_id", "program_id"),
    "infrastructure": ("infra_id", "infra_kind", "operation"),
    "measured_effect": ("metric", "baseline_value", "ruled_value", "delta", "unit", "source_field"),
    "reversal": ("reverses_change_id",),
}

PEDESTRIAN_VCLASS = "pedestrian"


class LedgerError(RuntimeError):
    """Raised when the ledger is invalid. Never downgraded to a warning."""


# --- hashing --------------------------------------------------------------


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def compute_entry_hash(entry: dict[str, Any]) -> str:
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
    """Deterministic, stable, content-derived identity."""
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
    if payload.get("kind") != expected_kind:
        raise LedgerError(
            f"change_type {change_type!r} requires payload kind {expected_kind!r}, "
            f"got {payload.get('kind')!r}"
        )
    for f in _REQUIRED_PAYLOAD_FIELDS[expected_kind]:
        if f not in payload:
            raise LedgerError(f"payload for {change_type!r} is missing required field {f!r}")

    if change_type in ("edge_closure", "lane_closure", "access_permission"):
        if PEDESTRIAN_VCLASS in payload.get("disallow", []):
            raise LedgerError(
                "refusing to record a change that bars pedestrians: closing a "
                "carriageway does not close the footway. This is a semantic "
                "guarantee -- pedestrian access stays structurally protected. "
                "It is NOT the SUMO crash fix: measured, barring pedestrians "
                "through TraCI does not crash SUMO (see RT-09)."
            )
    if change_type == "infrastructure_added" and payload.get("operation") != "added":
        raise LedgerError("infrastructure_added must carry operation 'added'")
    if change_type == "infrastructure_removed" and payload.get("operation") != "removed":
        raise LedgerError("infrastructure_removed must carry operation 'removed'")
    if change_type == "speed_limit" and not payload.get("mps", 0) > 0:
        raise LedgerError("speed_limit requires a positive mps")


def _validate_provenance(prov: dict[str, Any]) -> None:
    """Provenance must name a sealed evidence identity, not a claim."""
    src = prov.get("source")
    if src not in ("simulation", "director_rule"):
        raise LedgerError(
            f"provenance.source must be 'simulation' or 'director_rule', got {src!r}"
        )
    if src == "director_rule":
        if not prov.get("rule_manifest_sha256"):
            raise LedgerError(
                "a director_rule entry must bind to a sealed rule_manifest hash. "
                "Use append_director_rule(); provenance is never caller-supplied."
            )
    else:
        if not prov.get("simulation_result_sha256"):
            raise LedgerError(
                "a simulation entry must bind to a sealed simulation_result hash. "
                "Use append_simulation_consequence(); provenance is never caller-supplied."
            )
        if not prov.get("extractor"):
            raise LedgerError(
                "a simulation entry must name the deterministic extractor that derived it. "
                "A consequence with no extractor is an assertion, not simulation truth."
            )
        if prov["extractor"] not in CONSEQUENCE_EXTRACTORS:
            raise LedgerError(
                f"unknown extractor {prov['extractor']!r}; only registered deterministic "
                f"extractors may create simulation truth: {sorted(CONSEQUENCE_EXTRACTORS)}"
            )


# --- construction (internal) ----------------------------------------------


def new_ledger(world_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "world_id": world_id,
        "entries": [],
        "ledger_hash": GENESIS_HASH,
    }


def _append_entry(
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
    """The only writer. Deliberately private: provenance is built by this module."""
    if change_type not in CHANGE_TYPES:
        raise LedgerError(f"unknown change_type {change_type!r}")
    _validate_payload(change_type, payload)
    _validate_provenance(provenance)

    entries = list(ledger["entries"])

    if change_type == "reversal":
        target = payload["reverses_change_id"]
        if target not in {e["change_id"] for e in entries}:
            raise LedgerError(f"cannot reverse unknown change {target!r}")
        already = [e for e in entries if e.get("reverses") == target]
        if already:
            raise LedgerError(
                f"change {target!r} was already reversed by {already[0]['change_id']}"
            )
        reverses = target

    nonce = 0
    known = {e["change_id"] for e in entries}
    while True:
        cid = make_change_id(
            world_id=ledger["world_id"],
            origin_episode=origin_episode,
            change_type=change_type,
            payload=payload,
            nonce=nonce,
        )
        if cid not in known:
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


# --- door 1: Director rule truth ------------------------------------------

_CHANGE_BLOCK_TO_TYPE = {
    "close_edges": "edge_closure",
    "close_lanes": "lane_closure",
    "access_permission": "access_permission",
    "speed_limit": "speed_limit",
    "tls_program": "traffic_light_program",
}


def append_director_rule(
    ledger: dict[str, Any], *, rule_manifest: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    """Record the Director's declared rule, derived from its sealed manifest.

    The payload comes from the manifest's own `change` block. A caller cannot
    describe a different change from the one the sealed manifest declares,
    because the caller does not supply the payload at all.
    """
    verify_rule_manifest(rule_manifest)

    change = rule_manifest["change"]
    present = [k for k in _CHANGE_BLOCK_TO_TYPE if k in change]
    if len(present) != 1:
        raise LedgerError(
            f"a rule manifest must declare exactly ONE change; found {present or 'none'}"
        )
    key = present[0]
    change_type = _CHANGE_BLOCK_TO_TYPE[key]
    spec = change[key]

    if change_type == "edge_closure":
        payload = {"kind": "edge_closure", "edge_ids": list(spec["edge_ids"]),
                   "disallow": list(spec["disallow"])}
    elif change_type == "lane_closure":
        payload = {"kind": "lane_closure", "lane_ids": list(spec["lane_ids"]),
                   "disallow": list(spec["disallow"])}
    elif change_type == "access_permission":
        payload = {"kind": "access_permission", "target_kind": spec["target_kind"],
                   "target_ids": list(spec["target_ids"]),
                   "allow": list(spec.get("allow", [])),
                   "disallow": list(spec.get("disallow", []))}
    elif change_type == "speed_limit":
        payload = {"kind": "speed_limit", "target_kind": spec["target_kind"],
                   "target_ids": list(spec["target_ids"]), "mps": spec["mps"]}
    else:
        payload = {"kind": "traffic_light_program", "tls_id": spec["tls_id"],
                   "program_id": spec["program_id"]}
    if "statement" in rule_manifest:
        payload["reason"] = rule_manifest["statement"]

    provenance = {
        "source": "director_rule",
        "rule_manifest_sha256": rule_manifest["manifest_hash"],
        "rule_id": rule_manifest["rule_id"],
    }
    return _append_entry(
        ledger,
        change_type=change_type,
        origin_episode=int(rule_manifest["episode_number"]),
        applied_at_sim_second=float(rule_manifest.get("applies_at_sim_second", 0.0)),
        payload=payload,
        provenance=provenance,
        rule_id=rule_manifest["rule_id"],
    )


def append_reversal(
    ledger: dict[str, Any], *, rule_manifest: dict[str, Any], reverses_change_id: str
) -> tuple[dict[str, Any], str]:
    """Undo a change by appending a reversal. The original is never removed."""
    verify_rule_manifest(rule_manifest)
    payload = {"kind": "reversal", "reverses_change_id": reverses_change_id}
    if "statement" in rule_manifest:
        payload["reason"] = rule_manifest["statement"]
    provenance = {
        "source": "director_rule",
        "rule_manifest_sha256": rule_manifest["manifest_hash"],
        "rule_id": rule_manifest["rule_id"],
    }
    return _append_entry(
        ledger,
        change_type="reversal",
        origin_episode=int(rule_manifest["episode_number"]),
        applied_at_sim_second=float(rule_manifest.get("applies_at_sim_second", 0.0)),
        payload=payload,
        provenance=provenance,
        rule_id=rule_manifest["rule_id"],
    )


# --- door 2: simulation consequence truth ---------------------------------


def _summarise_tripinfo(path: Path) -> dict[str, float]:
    """Pure-stdlib tripinfo aggregation. No SUMO import, so the ledger has no
    dependency on the simulator to verify its own evidence."""
    trips: list[tuple[float, float, float, float]] = []
    walks: list[tuple[float, float]] = []
    for _ev, el in ET.iterparse(str(path), events=("end",)):
        if el.tag == "tripinfo":
            trips.append((float(el.get("duration", 0)), float(el.get("routeLength", 0)),
                          float(el.get("waitingTime", 0)), float(el.get("timeLoss", 0))))
        elif el.tag == "personinfo":
            for w in el:
                if w.tag == "walk":
                    walks.append((float(w.get("routeLength", 0)), float(w.get("duration", 0))))
        else:
            continue          # never clear a child: clear() drops attributes
        el.clear()

    def avg(xs: list[float]) -> float:
        return round(sum(xs) / len(xs), 2) if xs else 0.0

    return {
        "trips_completed": float(len(trips)),
        "avg_duration_s": avg([t[0] for t in trips]),
        "avg_route_length_m": avg([t[1] for t in trips]),
        "avg_waiting_time_s": avg([t[2] for t in trips]),
        "avg_time_loss_s": avg([t[3] for t in trips]),
        "walks_completed": float(len(walks)),
        "avg_walk_length_m": avg([w[0] for w in walks]),
        "avg_walk_duration_s": avg([w[1] for w in walks]),
    }


_EFFECT_UNITS = {
    "trips_completed": "trips",
    "avg_duration_s": "s",
    "avg_route_length_m": "m",
    "avg_waiting_time_s": "s",
    "avg_time_loss_s": "s",
    "walks_completed": "walks",
    "avg_walk_length_m": "m",
    "avg_walk_duration_s": "s",
}


def extract_closure_effect_v1(
    simulation_result: dict[str, Any], evidence_dir: Path
) -> list[dict[str, Any]]:
    """Derive the measured effect of a closure from sealed tripinfo artefacts.

    Deterministic and evidence-bound: it re-reads the two tripinfo files named
    by the sealed result, verifies their bytes against the sealed hashes, and
    computes the deltas itself. The caller contributes nothing but the evidence.

    Emits one `measured_effect` payload per metric whose value actually differs.
    A metric that did not move produces no entry -- the world does not remember
    a consequence that did not occur.
    """
    base = verify_artifact_on_disk(simulation_result, "baseline_tripinfo", evidence_dir)
    ruled = verify_artifact_on_disk(simulation_result, "ruled_tripinfo", evidence_dir)

    bm = _summarise_tripinfo(base)
    rm = _summarise_tripinfo(ruled)

    payloads: list[dict[str, Any]] = []
    for metric in sorted(bm):
        b, r = bm[metric], rm[metric]
        delta = round(r - b, 4)
        if delta == 0:
            continue
        payloads.append(
            {
                "kind": "measured_effect",
                "metric": metric,
                "baseline_value": b,
                "ruled_value": r,
                "delta": delta,
                "unit": _EFFECT_UNITS.get(metric, ""),
                # DNA-08: one channel maps exactly one authoritative field.
                "source_field": f"tripinfo.{metric}",
            }
        )
    return payloads


CONSEQUENCE_EXTRACTORS: dict[str, Callable[[dict[str, Any], Path], list[dict[str, Any]]]] = {
    "closure_effect_v1": extract_closure_effect_v1,
}


def append_simulation_consequence(
    ledger: dict[str, Any],
    *,
    simulation_result: dict[str, Any],
    extractor_name: str,
    evidence_dir: str | Path,
    rule_id: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Record what the simulation actually produced.

    The caller supplies **evidence, not conclusions**. Returns the new ledger and
    the ids of every entry the extractor derived (possibly none).
    """
    verify_simulation_result(simulation_result)

    if extractor_name not in CONSEQUENCE_EXTRACTORS:
        raise LedgerError(
            f"unknown extractor {extractor_name!r}; only registered deterministic "
            f"extractors may create simulation truth: {sorted(CONSEQUENCE_EXTRACTORS)}"
        )
    extractor = CONSEQUENCE_EXTRACTORS[extractor_name]

    try:
        payloads = extractor(simulation_result, Path(evidence_dir))
    except EvidenceError:
        raise
    except Exception as e:  # an extractor that cannot read its evidence creates nothing
        raise LedgerError(f"extractor {extractor_name!r} failed on its evidence: {e}") from e

    provenance = {
        "source": "simulation",
        "simulation_result_sha256": simulation_result["result_hash"],
        "run_id": simulation_result["run_id"],
        "extractor": extractor_name,
        "record_sha256": simulation_result.get("artifacts", {})
        .get("record_frames", {})
        .get("sha256"),
    }

    ids: list[str] = []
    for payload in payloads:
        ledger, cid = _append_entry(
            ledger,
            change_type="measured_effect",
            origin_episode=int(simulation_result["episode_number"]),
            applied_at_sim_second=float(simulation_result.get("applied_at_sim_second", 0.0)),
            payload=payload,
            provenance=provenance,
            rule_id=rule_id,
        )
        ids.append(cid)
    return ledger, ids


# --- verification ---------------------------------------------------------


def verify_ledger(ledger: dict[str, Any]) -> None:
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
        if e.get("entry_hash") != compute_entry_hash(e):
            raise LedgerError(f"entry {cid!r} at index {i} was modified after it was written")
        _validate_payload(e["change_type"], e["payload"])
        _validate_provenance(e["provenance"])
        prev = e["entry_hash"]

    if ledger.get("ledger_hash") != compute_ledger_hash(entries):
        raise LedgerError("ledger_hash does not match the entry chain")


def is_active(ledger: dict[str, Any], change_id: str) -> bool:
    if change_id not in {e["change_id"] for e in ledger["entries"]}:
        raise LedgerError(f"unknown change {change_id!r}")
    return not any(e.get("reverses") == change_id for e in ledger["entries"])


def active_changes(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    reversed_ids = {e["reverses"] for e in ledger["entries"] if e.get("reverses")}
    return [
        e for e in ledger["entries"]
        if e["change_type"] != "reversal" and e["change_id"] not in reversed_ids
    ]


def changes_from_episode(ledger: dict[str, Any], episode: int) -> list[dict[str, Any]]:
    return [e for e in ledger["entries"] if e["origin_episode"] == episode]


def history_of(ledger: dict[str, Any], change_id: str) -> list[dict[str, Any]]:
    return [
        e for e in ledger["entries"]
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
