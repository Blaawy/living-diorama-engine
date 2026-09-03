"""THE WORLD REMEMBERS, generalised -- the append-only change ledger.

The old engine remembered exactly one kind of durable change: a wall. This
module generalises that to every durable change the new world can undergo --
closures, permissions, speed limits, signal programmes, infrastructure, and
measured effects -- while keeping the property that made the original good:
**the scar outlives the rule that made it.**

SIMULATION CREATES TRUTH, structurally
--------------------------------------
There is **no public function that accepts a provenance argument.** Truth enters
through exactly two doors, and both bind to sealed evidence identities:

* `append_director_rule(ledger, rule_manifest=...)`
  The payload is **derived from the sealed manifest's own `change` block**.

* `append_simulation_consequence(ledger, simulation_result=..., extractor_name=...)`
  The caller supplies **evidence, never conclusions**. A named deterministic
  extractor re-reads the sealed artefacts from disk, verifies their bytes, and
  *computes* the consequence. The extractor also **cross-checks the artefacts
  against each other**: tripinfo trip and walk counts must agree with arrivals
  derived independently from the sealed trajectory record. That raises the bar
  from "type a number" to "fabricate a consistent record" -- it does not make
  fabrication impossible for someone who can write the evidence directory
  (attacker #2 demonstrated a consistent miniature). See point 4 below.

What this module guarantees, stated exactly (per the Phase 1 adversarial review)
--------------------------------------------------------------------------------
1. Entry content is extractor-derived from sealed bytes, never caller-chosen.
2. `verify_ledger(ledger)` re-applies every append-time rule: chain hashes,
   payload/provenance shape, extractor-output invariants, reversal semantics,
   rule attribution, episode ordering. **That authenticates structure, not
   origin**: a well-formed entry with fabricated-but-valid hashes passes it.
   `verify_ledger(ledger, evidence_dir=...)` additionally re-opens every
   sealed `simulation_result` a simulation entry names, re-verifies its
   artefacts on disk, **re-runs the extractor, and requires the recorded
   payloads to equal what it derives**. Use that form whenever the evidence is
   available; the plain form is for chain integrity only.
3. Artefacts must be mutually consistent (tripinfo vs record), so fabricating
   one file is not enough.
4. It does **not** prove a SUMO process ran. Sealing is a keyed-by-nothing
   hash. The trust boundary is: seal results **machine-side** (see
   `ldyf.closure.seal_run_result`) into a directory the author of prose cannot
   write. This library enforces everything up to that boundary and states the
   boundary rather than pretending it away.

Laws enforced structurally (DNA-03)
-----------------------------------
Append only (no delete/edit path). Hash chained (`prev_hash`). Evidence bound.
No caller-authored provenance. Reversal is a Director act and cannot target a
measurement.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable

from .evidence import (
    EvidenceError,
    verify_artifact_on_disk,
    verify_rule_manifest,
    verify_simulation_result,
)

__all__ = [
    "LedgerError",
    "CHANGE_TYPES",
    "CONSEQUENCE_EXTRACTORS",
    "new_ledger",
    "append_director_rule",
    "append_simulation_consequence",
    "append_reversal",
    "verify_ledger",
    "is_active",
    "active_changes",
    "changes_from_episode",
    "history_of",
    "save",
    "load",
    "compute_entry_hash",
    "compute_ledger_hash",
    "make_change_id",
    "extract_closure_effect_v1",
]

SCHEMA_VERSION = "persistent_changes_v2"
GENESIS_HASH = "0" * 64
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

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

# The closed set of metrics an extractor may emit, with their units. A
# measured_effect naming any other metric is a forgery by definition.
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

# Extractors that MUST NOT be trusted to run only from append time: verify_ledger
# re-validates their payload invariants without re-running them.
CONSEQUENCE_EXTRACTORS: dict[str, Callable[[dict[str, Any], Path], list[dict[str, Any]]]] = {}


class LedgerError(RuntimeError):
    """Raised when the ledger is invalid. Never downgraded to a warning."""


# --- hashing --------------------------------------------------------------


def _canonical(obj: Any) -> bytes:
    # allow_nan=False: a NaN/Infinity would otherwise serialise as non-JSON
    # and hash "successfully". Refuse instead.
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()


def compute_entry_hash(entry: dict[str, Any]) -> str:
    d = copy.deepcopy(entry)
    d.pop("entry_hash", None)
    try:
        return hashlib.sha256(_canonical(d)).hexdigest()
    except ValueError as e:      # non-finite float somewhere in the entry
        raise LedgerError(f"entry contains a non-finite number and cannot be hashed: {e}") from e


def compute_ledger_hash(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return GENESIS_HASH
    return hashlib.sha256(_canonical([e["entry_hash"] for e in entries])).hexdigest()


def make_change_id(
    *, world_id: str, origin_episode: int, change_type: str, payload: dict[str, Any], nonce: int = 0
) -> str:
    """Deterministic, stable, content-derived identity.

    16 hex chars (64 bits) is deliberate and schema-locked: ids only need to be
    unique within one world's ledger, the nonce loop guarantees that locally,
    and the entry_hash (256 bits) is the real identity. Widening ids would
    invalidate every existing ledger for no security gain.
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


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _validate_payload(change_type: str, payload: dict[str, Any]) -> None:
    expected_kind = _PAYLOAD_KIND[change_type]
    if not isinstance(payload, dict) or payload.get("kind") != expected_kind:
        raise LedgerError(
            f"change_type {change_type!r} requires payload kind {expected_kind!r}, "
            f"got {payload.get('kind') if isinstance(payload, dict) else type(payload).__name__!r}"
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
    if change_type == "speed_limit" and not (_finite(payload.get("mps")) and payload["mps"] > 0):
        raise LedgerError("speed_limit requires a positive finite mps")

    if change_type == "measured_effect":
        # Extractor-output invariants. A hand-built measured_effect that does not
        # satisfy exactly what the extractor would have produced is a forgery.
        metric = payload["metric"]
        if metric not in _EFFECT_UNITS:
            raise LedgerError(f"measured_effect names unknown metric {metric!r}")
        for f in ("baseline_value", "ruled_value", "delta"):
            if not _finite(payload[f]):
                raise LedgerError(f"measured_effect.{f} must be a finite number")
        if payload["delta"] != round(payload["ruled_value"] - payload["baseline_value"], 4):
            raise LedgerError("measured_effect.delta does not equal ruled - baseline")
        if payload["delta"] == 0:
            raise LedgerError("measured_effect with zero delta is not a consequence")
        if payload["unit"] != _EFFECT_UNITS[metric]:
            raise LedgerError(f"measured_effect.unit for {metric!r} must be {_EFFECT_UNITS[metric]!r}")
        if payload["source_field"] != f"tripinfo.{metric}":
            raise LedgerError("measured_effect.source_field must name its tripinfo metric")
        # Shape the real extractor emits: counts are non-negative integers
        # (stored as floats), averages are rounded to 2 dp. Anything else is
        # a value the extractor cannot produce.
        if metric in ("trips_completed", "walks_completed"):
            for f in ("baseline_value", "ruled_value"):
                v = payload[f]
                if v < 0 or v != int(v):
                    raise LedgerError(f"measured_effect.{f} for {metric!r} must be a non-negative integer")
        else:
            for f in ("baseline_value", "ruled_value"):
                if round(payload[f], 2) != payload[f]:
                    raise LedgerError(f"measured_effect.{f} for {metric!r} must be rounded to 2 dp")


def _validate_provenance(prov: dict[str, Any]) -> None:
    """Provenance must name sealed evidence identities in the correct shape."""
    if not isinstance(prov, dict):
        raise LedgerError("provenance must be an object")
    src = prov.get("source")
    if src not in ("simulation", "director_rule"):
        raise LedgerError(f"provenance.source must be 'simulation' or 'director_rule', got {src!r}")
    if src == "director_rule":
        h = prov.get("rule_manifest_sha256")
        if not (isinstance(h, str) and _HEX64.match(h)):
            raise LedgerError(
                "a director_rule entry must bind to a sealed rule_manifest sha256 "
                "(64 lowercase hex). Use append_director_rule()."
            )
        if not prov.get("rule_id"):
            raise LedgerError("a director_rule entry must carry the manifest's rule_id")
    else:
        h = prov.get("simulation_result_sha256")
        if not (isinstance(h, str) and _HEX64.match(h)):
            raise LedgerError(
                "a simulation entry must bind to a sealed simulation_result sha256 "
                "(64 lowercase hex). Use append_simulation_consequence()."
            )
        ex = prov.get("extractor")
        if not ex:
            raise LedgerError(
                "a simulation entry must name the deterministic extractor that derived it. "
                "A consequence with no extractor is an assertion, not simulation truth."
            )
        if ex not in CONSEQUENCE_EXTRACTORS:
            raise LedgerError(
                f"unknown extractor {ex!r}; only registered deterministic extractors "
                f"may create simulation truth: {sorted(CONSEQUENCE_EXTRACTORS)}"
            )
        if not prov.get("run_id"):
            raise LedgerError("a simulation entry must carry the sealed result's run_id")
        rec = prov.get("record_sha256")
        if not (isinstance(rec, str) and _HEX64.match(rec)):
            raise LedgerError(
                "a simulation entry must bind to the trajectory record sha256; the "
                "record is what makes tripinfo forgery detectable"
            )


# --- construction (internal) ----------------------------------------------


def new_ledger(world_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "world_id": world_id,
        "entries": [],
        "ledger_hash": GENESIS_HASH,
    }


def _check_entry_against_chain(entries: list[dict[str, Any]], entry: dict[str, Any]) -> None:
    """The rules that depend on what came before. Applied at append AND verify."""
    ct = entry["change_type"]
    prov = entry["provenance"]
    known = {e["change_id"]: e for e in entries}

    ep = entry.get("origin_episode")
    if not isinstance(ep, int) or isinstance(ep, bool) or ep < 0:
        raise LedgerError(f"origin_episode must be a non-negative integer, got {ep!r}")
    if entries and ep < entries[-1]["origin_episode"]:
        raise LedgerError(
            f"origin_episode must not decrease along the ledger: {entries[-1]['origin_episode']} -> {ep}"
        )
    t_ = entry.get("applied_at_sim_second")
    if not _finite(t_) or t_ < 0:
        raise LedgerError(f"applied_at_sim_second must be a finite non-negative number, got {t_!r}")

    if ct == "reversal":
        if prov.get("source") != "director_rule":
            raise LedgerError("a reversal is a Director act; it cannot carry simulation provenance")
        target = entry["payload"]["reverses_change_id"]
        if entry.get("reverses") != target:
            raise LedgerError("reversal.reverses must equal payload.reverses_change_id")
        if target not in known:
            raise LedgerError(f"cannot reverse unknown change {target!r}")
        if known[target]["change_type"] in ("reversal", "measured_effect"):
            raise LedgerError(
                f"cannot reverse a {known[target]['change_type']}: a measurement or a "
                "reversal is a fact, not a standing change"
            )
        if any(e.get("reverses") == target for e in entries):
            raise LedgerError(f"change {target!r} was already reversed")
    else:
        if entry.get("reverses") is not None:
            raise LedgerError("only a reversal may set 'reverses'")

    if prov.get("source") == "simulation" and entry.get("rule_id"):
        # A consequence attributed to a rule must follow that rule on the chain.
        if not any(
            e["provenance"].get("source") == "director_rule"
            and e.get("rule_id") == entry["rule_id"]
            for e in entries
        ):
            raise LedgerError(
                f"consequence attributed to rule {entry['rule_id']!r}, but no director_rule "
                "entry with that rule_id precedes it on the ledger"
            )


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
    """The only writer. Private: provenance is constructed by this module.

    Calling this directly buys an attacker nothing: `verify_ledger` re-applies
    every check below on load, so a forged entry is refused the moment the
    ledger is read back.
    """
    if change_type not in CHANGE_TYPES:
        raise LedgerError(f"unknown change_type {change_type!r}")
    _validate_payload(change_type, payload)
    _validate_provenance(provenance)

    entries = list(ledger["entries"])
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
        "origin_episode": int(origin_episode),
        "applied_at_sim_second": float(applied_at_sim_second),
        "rule_id": rule_id,
        "reverses": reverses,
        "provenance": provenance,
        "payload": payload,
        "prev_hash": entries[-1]["entry_hash"] if entries else GENESIS_HASH,
    }
    _check_entry_against_chain(entries, entry)
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


def _director_provenance(rule_manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "director_rule",
        "rule_manifest_sha256": rule_manifest["manifest_hash"],
        "rule_id": rule_manifest["rule_id"],
    }


def append_director_rule(
    ledger: dict[str, Any], *, rule_manifest: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    """Record the Director's declared rule, derived from its sealed manifest."""
    verify_rule_manifest(rule_manifest)

    change = rule_manifest["change"]
    keys = list(change.keys())
    if len(keys) != 1:
        raise LedgerError(
            f"a rule manifest must declare exactly ONE change; found {keys or 'none'}"
        )
    key = keys[0]
    if key not in _CHANGE_BLOCK_TO_TYPE:
        # The schema admits it as an experiment input; the ledger records only
        # durable changes to the WORLD. demand_scale alters demand, not the world.
        raise LedgerError(
            f"rule change {key!r} is a valid experiment input but not a durable world "
            f"change; the ledger records only {sorted(_CHANGE_BLOCK_TO_TYPE)}"
        )
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

    return _append_entry(
        ledger,
        change_type=change_type,
        origin_episode=int(rule_manifest["episode_number"]),
        applied_at_sim_second=float(rule_manifest.get("applies_at_sim_second", 0.0)),
        payload=payload,
        provenance=_director_provenance(rule_manifest),
        rule_id=rule_manifest["rule_id"],
    )


def append_reversal(
    ledger: dict[str, Any], *, rule_manifest: dict[str, Any], reverses_change_id: str
) -> tuple[dict[str, Any], str]:
    """Undo a standing change by appending a reversal. The original is never removed."""
    verify_rule_manifest(rule_manifest)
    payload = {"kind": "reversal", "reverses_change_id": reverses_change_id}
    if "statement" in rule_manifest:
        payload["reason"] = rule_manifest["statement"]
    return _append_entry(
        ledger,
        change_type="reversal",
        origin_episode=int(rule_manifest["episode_number"]),
        applied_at_sim_second=float(rule_manifest.get("applies_at_sim_second", 0.0)),
        payload=payload,
        provenance=_director_provenance(rule_manifest),
        rule_id=rule_manifest["rule_id"],
        reverses=reverses_change_id,
    )


# --- door 2: simulation consequence truth ---------------------------------


def _summarise_tripinfo(path: Path) -> dict[str, float]:
    """Pure-stdlib tripinfo aggregation. Refuses non-finite values."""
    trips: list[tuple[float, float, float, float]] = []
    walks: list[tuple[float, float]] = []

    def num(el: ET.Element, attr: str) -> float:
        v = float(el.get(attr, 0))
        if not math.isfinite(v):
            raise LedgerError(f"non-finite {attr}={el.get(attr)!r} in {path.name}; refusing")
        return v

    for _ev, el in ET.iterparse(str(path), events=("end",)):
        if el.tag == "tripinfo":
            trips.append((num(el, "duration"), num(el, "routeLength"),
                          num(el, "waitingTime"), num(el, "timeLoss")))
        elif el.tag == "personinfo":
            for w in el:
                if w.tag == "walk":
                    walks.append((num(w, "routeLength"), num(w, "duration")))
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


_REC_SAMPLE = struct.Struct("<Ifffff")
_REC_COUNT = struct.Struct("<I")


def _arrivals_from_record(manifest_path: Path, frames_path: Path) -> dict[str, int]:
    """Independently derive how many actors ARRIVED, from the trajectory record.

    An actor whose last appearance precedes the final frame left the simulation
    before it ended -- i.e. it arrived (or was removed). This is computed from
    the binary record alone, so it can be compared against the tripinfo count a
    forger might have typed.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    kinds = [a["kind"] for a in manifest["actors"]]
    data = frames_path.read_bytes()
    last_seen: dict[int, int] = {}
    off = 0
    frame = 0
    n_total = len(data)
    while off + _REC_COUNT.size <= n_total:
        (n,) = _REC_COUNT.unpack_from(data, off)
        off += _REC_COUNT.size
        for k in range(n):
            idx = _REC_SAMPLE.unpack_from(data, off + k * _REC_SAMPLE.size)[0]
            last_seen[idx] = frame
        off += n * _REC_SAMPLE.size
        frame += 1
    last_frame = frame - 1
    out = {"vehicle": 0, "person": 0}
    for idx, lf in last_seen.items():
        if lf < last_frame:
            out[kinds[idx]] = out.get(kinds[idx], 0) + 1
    return out


def extract_closure_effect_v1(
    simulation_result: dict[str, Any], evidence_dir: Path
) -> list[dict[str, Any]]:
    """Derive the measured effect of a closure from sealed artefacts.

    Deterministic and evidence-bound. Requires FOUR sealed artefacts --
    baseline/ruled tripinfo AND baseline/ruled trajectory records -- and refuses
    unless each tripinfo's completed-trip and completed-walk counts equal the
    arrivals derived independently from its record. Emits one
    `measured_effect` per metric that actually moved.
    """
    base = verify_artifact_on_disk(simulation_result, "baseline_tripinfo", evidence_dir)
    ruled = verify_artifact_on_disk(simulation_result, "ruled_tripinfo", evidence_dir)
    base_rec = verify_artifact_on_disk(simulation_result, "baseline_record_frames", evidence_dir)
    ruled_rec = verify_artifact_on_disk(simulation_result, "ruled_record_frames", evidence_dir)
    base_man = verify_artifact_on_disk(simulation_result, "baseline_record_manifest", evidence_dir)
    ruled_man = verify_artifact_on_disk(simulation_result, "ruled_record_manifest", evidence_dir)

    bm = _summarise_tripinfo(base)
    rm = _summarise_tripinfo(ruled)

    for label, summary, man, rec in (("baseline", bm, base_man, base_rec),
                                     ("ruled", rm, ruled_man, ruled_rec)):
        arrivals = _arrivals_from_record(man, rec)
        if int(summary["trips_completed"]) != arrivals.get("vehicle", 0):
            raise EvidenceError(
                f"{label}: tripinfo claims {int(summary['trips_completed'])} completed trips "
                f"but the trajectory record shows {arrivals.get('vehicle', 0)} vehicle "
                "arrivals. The artefacts are not from the same run; refusing."
            )
        if int(summary["walks_completed"]) != arrivals.get("person", 0):
            raise EvidenceError(
                f"{label}: tripinfo claims {int(summary['walks_completed'])} completed walks "
                f"but the trajectory record shows {arrivals.get('person', 0)} person "
                "arrivals. The artefacts are not from the same run; refusing."
            )

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
                "unit": _EFFECT_UNITS[metric],
                "source_field": f"tripinfo.{metric}",   # DNA-08: one channel, one field
            }
        )
    return payloads


CONSEQUENCE_EXTRACTORS["closure_effect_v1"] = extract_closure_effect_v1


def append_simulation_consequence(
    ledger: dict[str, Any],
    *,
    simulation_result: dict[str, Any],
    extractor_name: str,
    evidence_dir: str | Path,
    rule_id: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Record what the simulation actually produced. Evidence in, entries out."""
    verify_simulation_result(simulation_result)

    if extractor_name not in CONSEQUENCE_EXTRACTORS:
        raise LedgerError(
            f"unknown extractor {extractor_name!r}; only registered deterministic "
            f"extractors may create simulation truth: {sorted(CONSEQUENCE_EXTRACTORS)}"
        )
    extractor = CONSEQUENCE_EXTRACTORS[extractor_name]

    try:
        payloads = extractor(simulation_result, Path(evidence_dir))
    except (EvidenceError, LedgerError):
        raise
    except Exception as e:
        raise LedgerError(f"extractor {extractor_name!r} failed on its evidence: {e}") from e

    arts = simulation_result.get("artifacts", {})
    provenance = {
        "source": "simulation",
        "simulation_result_sha256": simulation_result["result_hash"],
        "run_id": simulation_result["run_id"],
        "extractor": extractor_name,
        "record_sha256": arts.get("ruled_record_frames", {}).get("sha256"),
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


def verify_ledger(ledger: dict[str, Any], *, evidence_dir: str | Path | None = None) -> None:
    """Re-apply every append-time rule to a ledger. Raise naming the first failure.

    Without `evidence_dir` this authenticates the chain and every entry's
    structure. With it, each simulation entry is additionally traced back to a
    sealed `simulation_result.json` on disk whose `result_hash` equals the
    entry's `simulation_result_sha256`; the artefacts are re-verified, the named
    extractor is re-run, and the recorded payload must be one the extractor
    derives. A fabricated-but-well-formed entry fails here.
    """
    if ledger.get("schema_version") != SCHEMA_VERSION:
        raise LedgerError(f"unexpected schema_version {ledger.get('schema_version')!r}")

    entries = ledger.get("entries", [])
    prev = GENESIS_HASH
    seen: set[str] = set()
    for i, e in enumerate(entries):
        cid = e.get("change_id")
        if not isinstance(cid, str) or not re.match(r"^chg_[0-9a-f]{16}$", cid):
            raise LedgerError(f"malformed change_id at index {i}: {cid!r}")
        if cid in seen:
            raise LedgerError(f"duplicate change_id {cid!r} at index {i}")
        seen.add(cid)
        if e.get("change_type") not in CHANGE_TYPES:
            raise LedgerError(f"entry {cid!r}: unknown change_type {e.get('change_type')!r}")
        if e.get("prev_hash") != prev:
            raise LedgerError(
                f"chain broken at index {i} ({cid}): prev_hash={e.get('prev_hash')!r} "
                f"expected {prev!r}"
            )
        if e.get("entry_hash") != compute_entry_hash(e):
            raise LedgerError(f"entry {cid!r} at index {i} was modified after it was written")
        _validate_payload(e["change_type"], e["payload"])
        _validate_provenance(e["provenance"])
        _check_entry_against_chain(entries[:i], e)
        prev = e["entry_hash"]

    if ledger.get("ledger_hash") != compute_ledger_hash(entries):
        raise LedgerError("ledger_hash does not match the entry chain")

    if evidence_dir is not None:
        _verify_entries_against_evidence(entries, Path(evidence_dir))


def _verify_entries_against_evidence(entries: list[dict[str, Any]], evidence_dir: Path) -> None:
    """Trace every simulation entry back to sealed evidence and re-derive it."""
    derived_cache: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        prov = e["provenance"]
        if prov.get("source") != "simulation":
            continue
        want = prov["simulation_result_sha256"]
        if want not in derived_cache:
            match = None
            for c in sorted(evidence_dir.rglob("simulation_result*.json")):
                try:
                    doc = json.loads(c.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if doc.get("result_hash") == want:
                    verify_simulation_result(doc)
                    match = (doc, c.parent)
                    break
            if match is None:
                raise LedgerError(
                    f"entry {e['change_id']} names simulation_result {want[:16]}..., but no sealed "
                    f"simulation_result.json with that hash exists under {evidence_dir}"
                )
            doc, base = match
            ex = CONSEQUENCE_EXTRACTORS[prov["extractor"]]
            derived_cache[want] = ex(doc, base)
            rec = doc.get("artifacts", {}).get("ruled_record_frames", {}).get("sha256")
            if prov.get("record_sha256") != rec:
                raise LedgerError(f"entry {e['change_id']}: record_sha256 does not match the sealed result")
        if e["payload"] not in derived_cache[want]:
            raise LedgerError(
                f"entry {e['change_id']}: payload is not one the extractor derives from the sealed "
                "evidence -- fabricated or stale"
            )


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
        json.dumps(ledger, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False),
        encoding="utf-8",
    )
    return ledger["ledger_hash"]


def load(path: str | Path, *, evidence_dir: str | Path | None = None) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    verify_ledger(doc, evidence_dir=evidence_dir)
    return doc
