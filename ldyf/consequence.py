"""Consequence extractors -- EVIDENCE in, measured effects out.

Every extractor here follows the pattern established by
`ldyf.persistent_changes.extract_closure_effect_v1`, step for step:

1. it receives a SEALED `simulation_result` document and an evidence directory.
   It never accepts a number, a metric or a conclusion from its caller;
2. it re-reads every artefact it needs from disk and verifies its bytes against
   the identity sealed in that result (`ldyf.evidence.verify_artifact_on_disk`);
3. it COMPUTES the effect from those bytes;
4. it CROSS-CHECKS the artefacts against each other, in two directions:
   (a) between the arms -- both must have run on the same net, the same seed and
       the same demand, or the comparison is not a controlled experiment and the
       extractor raises;
   (b) inside each arm -- the tripinfo trip and walk counts must equal the
       arrivals derived independently from that arm's sealed trajectory record,
       exactly as the closure extractor checks them;
5. it emits `measured_effect` payloads naming ONLY metrics listed in
   `ldyf.persistent_changes._EFFECT_UNITS`. `_EMITTABLE_METRICS` below is the
   whole vocabulary this module may use, and the module refuses at import time
   if any name in it is not in that table.

NO METRIC IN THIS MODULE IS NEW: `avg_duration_s`, `avg_time_loss_s`,
`avg_waiting_time_s`, `trips_completed`, `walks_completed`, `avg_walk_length_m`
and `avg_walk_duration_s` are all already in `_EFFECT_UNITS`.

Artefacts each extractor requires
---------------------------------
All four need the closure extractor's six artefacts (`baseline_tripinfo`,
`ruled_tripinfo`, `baseline_record_manifest`, `baseline_record_frames`,
`ruled_record_manifest`, `ruled_record_frames`) plus:

* `baseline_demand` / `ruled_demand` -- one sealed `demand_manifest_v1` JSON per
  arm, naming the demand DEFINITION the arm ran (its route files and their
  hashes) and the counts it injected::

      {"schema_version": "demand_manifest_v1",
       "arm": "baseline",
       "route_files": [{"file": "demand.rou.xml", "sha256": "<64 hex>"}],
       "seed": 20260903,
       "injected": {"vehicle": 300, "person": 40},
       "scale": 1.0}

  Without this document there is nothing to hold the arms' demand identical to,
  and nothing to compare the record-derived count against, so a result that does
  not name one is refused.

* `traffic_light_effect_v1` additionally needs `tls_junction` -- a sealed
  `tls_junction_v1` JSON naming the controlled junction, so "the controlled
  junction approaches" is a set the evidence selects rather than a set the
  caller types::

      {"schema_version": "tls_junction_v1", "junction_id": "B1",
       "centre_unreal_cm": [0.0, 0.0], "approach_radius_cm": 500.0}

  An approach trip is a tripinfo trip whose vehicle the sealed record shows
  inside that radius at least once.

A note on `demand_flow_effect_v1`: a demand experiment's independent variable IS
the demand, so for that one extractor the arms' injected counts are allowed to
differ -- but only the counts. The demand definition (route files + demand seed)
must still be identical, and each arm's injected count must still equal the
count the sealed record shows. Every other extractor requires the two demand
manifests to be identical outright.
"""

from __future__ import annotations

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .evidence import EvidenceError, verify_artifact_on_disk
from .persistent_changes import (
    CONSEQUENCE_EXTRACTORS,
    _EFFECT_UNITS,
    _arrivals_from_record,
    _summarise_tripinfo,
)
from .sumo_record import COUNT_STRUCT, SAMPLE_STRUCT

__all__ = [
    "ARMS",
    "DEMAND_MANIFEST_VERSION",
    "JUNCTION_MANIFEST_VERSION",
    "TLS_JUNCTION_ARTIFACT",
    "extract_demand_flow_effect_v1",
    "extract_pedestrian_effect_v1",
    "extract_speed_limit_effect_v1",
    "extract_traffic_light_effect_v1",
]

DEMAND_MANIFEST_VERSION = "demand_manifest_v1"
JUNCTION_MANIFEST_VERSION = "tls_junction_v1"
TLS_JUNCTION_ARTIFACT = "tls_junction"

ARMS = ("baseline", "ruled")

_ARM_ARTIFACTS = {
    "baseline": {
        "tripinfo": "baseline_tripinfo",
        "manifest": "baseline_record_manifest",
        "frames": "baseline_record_frames",
        "demand": "baseline_demand",
    },
    "ruled": {
        "tripinfo": "ruled_tripinfo",
        "manifest": "ruled_record_manifest",
        "frames": "ruled_record_frames",
        "demand": "ruled_demand",
    },
}

# Every metric this module is permitted to emit. The union is checked against
# `persistent_changes._EFFECT_UNITS` at import time: an extractor may emit ONLY
# metrics present in that table.
_EMITTABLE_METRICS = (
    "avg_duration_s",
    "avg_time_loss_s",
    "avg_waiting_time_s",
    "trips_completed",
    "walks_completed",
    "avg_walk_length_m",
    "avg_walk_duration_s",
)
_UNLISTED = tuple(m for m in _EMITTABLE_METRICS if m not in _EFFECT_UNITS)
if _UNLISTED:                       # pragma: no cover - a programming error
    raise RuntimeError(
        f"ldyf.consequence would emit metrics that are not in "
        f"persistent_changes._EFFECT_UNITS: {_UNLISTED}. Add them to that table or "
        "do not emit them."
    )

METRICS_SPEED_LIMIT = ("avg_duration_s", "avg_time_loss_s")
METRICS_TRAFFIC_LIGHT = ("avg_waiting_time_s",)
METRICS_DEMAND_FLOW = ("trips_completed", "avg_duration_s")
METRICS_PEDESTRIAN = ("walks_completed", "avg_walk_duration_s", "avg_walk_length_m")


# --- small helpers --------------------------------------------------------


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _hex64(x: Any) -> bool:
    return isinstance(x, str) and len(x) == 64 and all(c in "0123456789abcdef" for c in x)


def _read_json(path: Path, what: str, extractor_name: str) -> dict[str, Any]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        raise EvidenceError(
            f"{extractor_name}: the {what} at {Path(path).name} is not parseable JSON: {e}"
        ) from e
    if not isinstance(doc, dict):
        raise EvidenceError(f"{extractor_name}: the {what} must be a JSON object")
    return doc


# --- evidence loading -----------------------------------------------------


def _load_arms(simulation_result: dict[str, Any], evidence_dir: Path, extractor_name: str) -> dict[str, Any]:
    """Resolve and byte-verify the four sealed artefacts each arm requires."""
    if not isinstance(simulation_result, dict):
        raise EvidenceError(f"{extractor_name}: simulation_result must be a document")
    arms: dict[str, Any] = {}
    for arm, names in _ARM_ARTIFACTS.items():
        paths = {
            kind: verify_artifact_on_disk(simulation_result, name, evidence_dir)
            for kind, name in names.items()
        }
        manifest_path = paths["manifest"]
        manifest = _read_json(manifest_path, f"{arm} record manifest", extractor_name)
        demand = _read_json(paths["demand"], f"{arm} demand manifest", extractor_name)
        arms[arm] = {
            "tripinfo": paths["tripinfo"],
            "frames": paths["frames"],
            "manifest_path": manifest_path,
            "manifest": manifest,
            "demand": _demand_definition(arm, demand, extractor_name),
        }
    return arms


def _demand_definition(arm: str, doc: dict[str, Any], extractor_name: str) -> dict[str, Any]:
    """Validate one arm's sealed demand manifest and return its definition."""
    where = f"{extractor_name}: {arm} demand manifest"
    if doc.get("schema_version") != DEMAND_MANIFEST_VERSION:
        raise EvidenceError(
            f"{where} declares schema_version {doc.get('schema_version')!r}, expected "
            f"{DEMAND_MANIFEST_VERSION!r}"
        )
    routes = doc.get("route_files")
    if not isinstance(routes, list) or not routes:
        raise EvidenceError(f"{where} names no route_files; the demand definition is unknown")
    normalised = []
    for r in routes:
        if not isinstance(r, dict) or not isinstance(r.get("file"), str) or not _hex64(r.get("sha256")):
            raise EvidenceError(f"{where} route_files entries must be {{file, sha256(64 hex)}}")
        normalised.append({"file": r["file"], "sha256": r["sha256"]})
    normalised.sort(key=lambda r: (r["file"], r["sha256"]))
    seed = doc.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise EvidenceError(f"{where} must carry the integer demand seed it was generated with")
    injected = doc.get("injected")
    if not isinstance(injected, dict):
        raise EvidenceError(f"{where} carries no 'injected' counts")
    counts: dict[str, int] = {}
    for kind in ("vehicle", "person"):
        v = injected.get(kind, 0)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise EvidenceError(f"{where} injected.{kind} must be a non-negative integer, got {v!r}")
        counts[kind] = v
    scale = doc.get("scale", 1.0)
    if not _finite(scale) or scale <= 0:
        raise EvidenceError(f"{where} scale must be a positive finite number, got {scale!r}")
    return {"route_files": normalised, "seed": seed, "injected": counts, "scale": float(scale)}


# --- the sealed trajectory record ----------------------------------------


def _scan_record(
    arm: str,
    evidence: dict[str, Any],
    extractor_name: str,
    *,
    centre: tuple[float, float] | None = None,
    radius_cm: float | None = None,
) -> dict[str, Any]:
    """One strict, sequential pass over frames.bin.

    Returns the frames read, the actor indices the record actually shows, those
    seen inside `radius_cm` of `centre`, and the observed per-kind counts. Every
    structural defect (empty file, truncated frame, an actor index the manifest
    does not have, a frame count that disagrees with the manifest, an actor the
    manifest names that never appears) is refused rather than mis-counted.
    """
    manifest = evidence["manifest"]
    actors = manifest.get("actors")
    if not isinstance(actors, list) or not actors:
        raise EvidenceError(
            f"{extractor_name}: the {arm} record manifest names no actors; a record with an "
            "empty actor table is not evidence"
        )
    data = evidence["frames"].read_bytes()
    if not data:
        raise EvidenceError(
            f"{extractor_name}: the {arm} trajectory record is empty (0 bytes); an empty "
            "record is not evidence of anything"
        )

    observed: set[int] = set()
    near: set[int] = set()
    frame = 0
    off = 0
    total = len(data)
    while off < total:
        if total - off < COUNT_STRUCT.size:
            raise EvidenceError(
                f"{extractor_name}: the {arm} trajectory record is truncated -- a partial "
                f"frame header at byte {off}; refusing"
            )
        (n,) = COUNT_STRUCT.unpack_from(data, off)
        off += COUNT_STRUCT.size
        need = n * SAMPLE_STRUCT.size
        if total - off < need:
            raise EvidenceError(
                f"{extractor_name}: the {arm} trajectory record is truncated -- frame {frame} "
                f"declares {n} samples but only {(total - off) // SAMPLE_STRUCT.size} fit; refusing"
            )
        for k in range(n):
            idx, x, y, _z, _yaw, _speed = SAMPLE_STRUCT.unpack_from(data, off + k * SAMPLE_STRUCT.size)
            if idx >= len(actors):
                raise EvidenceError(
                    f"{extractor_name}: frame {frame} of the {arm} record names actor index {idx}, "
                    f"which the actor table ({len(actors)} actors) does not have; refusing"
                )
            observed.add(idx)
            if centre is not None and radius_cm is not None:
                if math.hypot(x - centre[0], y - centre[1]) <= radius_cm:
                    near.add(idx)
        off += need
        frame += 1

    if len(observed) != len(actors):
        raise EvidenceError(
            f"{extractor_name}: the {arm} actor table names {len(actors)} actors but the "
            f"trajectory record only ever shows {len(observed)}; the table and the frames are not "
            "the same run; refusing"
        )
    clock = manifest.get("clock") or {}
    declared_frames = clock.get("frame_count")
    if declared_frames is not None and int(declared_frames) != frame:
        raise EvidenceError(
            f"{extractor_name}: the {arm} record manifest declares {declared_frames} frames but "
            f"frames.bin holds {frame}; refusing"
        )
    declared_sha = (manifest.get("binary") or {}).get("sha256")
    if isinstance(declared_sha, str):
        actual = hashlib.sha256(data).hexdigest()
        if declared_sha != actual:
            raise EvidenceError(
                f"{extractor_name}: the {arm} record manifest names frames.bin sha256 "
                f"{declared_sha}, but the file on disk hashes to {actual}; the manifest and the "
                "frames are not the same run; refusing"
            )

    by_kind: dict[str, int] = {}
    for idx in sorted(observed):
        kind = actors[idx].get("kind")
        if not isinstance(kind, str) or not kind:
            raise EvidenceError(f"{extractor_name}: {arm} actor index {idx} has no kind")
        by_kind[kind] = by_kind.get(kind, 0) + 1
    declared_counts = (manifest.get("counts") or {}).get("by_kind")
    if isinstance(declared_counts, dict):
        try:
            normalised = {str(k): int(v) for k, v in declared_counts.items()}
        except (TypeError, ValueError) as e:
            raise EvidenceError(
                f"{extractor_name}: the {arm} record manifest counts.by_kind is not a count map: {e}"
            ) from e
        if normalised != by_kind:
            raise EvidenceError(
                f"{extractor_name}: the {arm} record manifest counts {normalised} do not match the "
                f"actors its frames actually show ({by_kind}); refusing"
            )
    return {"frames": frame, "observed": observed, "near": near, "by_kind": by_kind}


# --- tripinfo -------------------------------------------------------------


def _num(el: ET.Element, attr: str, path: Path) -> float:
    raw = el.get(attr, 0)
    try:
        v = float(raw)
    except (TypeError, ValueError) as e:
        raise EvidenceError(f"tripinfo {path.name}: {attr}={raw!r} is not a number") from e
    if not math.isfinite(v):
        raise EvidenceError(f"tripinfo {path.name}: non-finite {attr}={raw!r}; refusing")
    return v


def _read_tripinfo(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Per-record tripinfo parse: one dict per completed trip and per walk.

    The clear() discipline is the shipped one: a `<walk>` is a CHILD of
    `<personinfo>`, so clearing it on its own end event would strip the
    attributes its parent is read from.
    """
    trips: list[dict[str, Any]] = []
    walks: list[dict[str, Any]] = []
    try:
        for _ev, el in ET.iterparse(str(path), events=("end",)):
            if el.tag == "tripinfo":
                trips.append(
                    {
                        "id": el.get("id"),
                        "duration": _num(el, "duration", path),
                        "routeLength": _num(el, "routeLength", path),
                        "waitingTime": _num(el, "waitingTime", path),
                        "timeLoss": _num(el, "timeLoss", path),
                    }
                )
            elif el.tag == "personinfo":
                for w in el:
                    if w.tag == "walk":
                        walks.append(
                            {
                                "person": el.get("id"),
                                "routeLength": _num(w, "routeLength", path),
                                "duration": _num(w, "duration", path),
                            }
                        )
            else:
                continue
            el.clear()
    except ET.ParseError as e:
        raise EvidenceError(f"tripinfo {path.name} is not parseable XML: {e}") from e
    return trips, walks


def _avg(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 2) if xs else 0.0


def _tripinfo_summary(arm: str, evidence: dict[str, Any], extractor_name: str) -> dict[str, Any]:
    """This module's parse, plus a self-check against the shipped aggregator.

    `ldyf.persistent_changes._summarise_tripinfo` is the aggregator the closure
    extractor uses. This extractor needs per-trip records, so it parses the file
    itself; the two must agree exactly or one of them is lying about the same
    bytes, and that is refused.
    """
    path = evidence["tripinfo"]
    trips, walks = _read_tripinfo(path)
    summary = {
        "trips_completed": float(len(trips)),
        "avg_duration_s": _avg([t["duration"] for t in trips]),
        "avg_route_length_m": _avg([t["routeLength"] for t in trips]),
        "avg_waiting_time_s": _avg([t["waitingTime"] for t in trips]),
        "avg_time_loss_s": _avg([t["timeLoss"] for t in trips]),
        "walks_completed": float(len(walks)),
        "avg_walk_length_m": _avg([w["routeLength"] for w in walks]),
        "avg_walk_duration_s": _avg([w["duration"] for w in walks]),
    }
    shipped = _summarise_tripinfo(path)
    if summary != shipped:
        differ = sorted(k for k in shipped if summary.get(k) != shipped[k])
        raise EvidenceError(
            f"{extractor_name}: this module's tripinfo reader disagrees with the shipped "
            f"aggregator on the {arm} tripinfo at {differ} "
            f"(read {[summary.get(k) for k in differ]}, shipped {[shipped[k] for k in differ]}); "
            "one of them is not reading those bytes; refusing"
        )
    return {"trips": trips, "walks": walks, "summary": summary}


def _cross_check_counts(label: str, evidence: dict[str, Any], summary: dict[str, float]) -> dict[str, int]:
    """tripinfo counts must equal arrivals derived from that arm's record.

    Identical in form and message to the closure extractor's check: the record is
    read independently, straight from the sealed binary.
    """
    arrivals = _arrivals_from_record(evidence["manifest_path"], evidence["frames"])
    if int(summary["trips_completed"]) != arrivals.get("vehicle", 0):
        raise EvidenceError(
            f"{label}: tripinfo claims {int(summary['trips_completed'])} completed trips but the "
            f"trajectory record shows {arrivals.get('vehicle', 0)} vehicle arrivals. The artefacts "
            "are not from the same run; refusing."
        )
    if int(summary["walks_completed"]) != arrivals.get("person", 0):
        raise EvidenceError(
            f"{label}: tripinfo claims {int(summary['walks_completed'])} completed walks but the "
            f"trajectory record shows {arrivals.get('person', 0)} person arrivals. The artefacts "
            "are not from the same run; refusing."
        )
    return arrivals


# --- the controlled-experiment cross-check --------------------------------


def _check_controlled_arms(
    extractor_name: str,
    simulation_result: dict[str, Any],
    arms: dict[str, Any],
    record_counts: dict[str, dict[str, int]],
    *,
    demand_is_the_rule: bool = False,
) -> None:
    """Both arms must differ ONLY in the rule.

    Same net, same seed, same demand definition. Unless the measured rule IS the
    demand change (`demand_is_the_rule`), the injected counts must be identical
    too. Any disagreement raises: a comparison between arms differing in anything
    but the rule is not a controlled experiment.
    """
    sources: dict[str, dict[str, Any]] = {}
    for arm in ARMS:
        src = arms[arm]["manifest"].get("source")
        if not isinstance(src, dict):
            raise EvidenceError(
                f"{extractor_name}: the {arm} record manifest carries no 'source' block, so the "
                "net it ran on and the seed it used are unknown; refusing"
            )
        sources[arm] = src

    nets = {arm: sources[arm].get("net_sha256") for arm in ARMS}
    for arm in ARMS:
        if not _hex64(nets[arm]):
            raise EvidenceError(
                f"{extractor_name}: the {arm} record does not record the net hash it ran on "
                f"(source.net_sha256={nets[arm]!r}); refusing"
            )
    if nets["baseline"] != nets["ruled"]:
        raise EvidenceError(
            f"{extractor_name}: the arms ran on DIFFERENT nets (baseline {nets['baseline']}, "
            f"ruled {nets['ruled']}); a comparison between arms differing in anything but the rule "
            "is not a controlled experiment."
        )

    seeds = {arm: sources[arm].get("seed") for arm in ARMS}
    for arm in ARMS:
        if not isinstance(seeds[arm], int) or isinstance(seeds[arm], bool):
            raise EvidenceError(
                f"{extractor_name}: the {arm} record does not record the seed it ran with "
                f"(source.seed={seeds[arm]!r}); two arms cannot be shown to share a seed that "
                "neither declares; refusing"
            )
    if seeds["baseline"] != seeds["ruled"]:
        raise EvidenceError(
            f"{extractor_name}: the arms ran with DIFFERENT seeds (baseline {seeds['baseline']}, "
            f"ruled {seeds['ruled']}); a comparison between arms differing in anything but the rule "
            "is not a controlled experiment."
        )
    result_seed = simulation_result.get("seed")
    if result_seed is not None and result_seed != seeds["baseline"]:
        raise EvidenceError(
            f"{extractor_name}: the sealed result declares seed {result_seed!r} but the records ran "
            f"with {seeds['baseline']!r}; refusing"
        )

    demands = {arm: arms[arm]["demand"] for arm in ARMS}
    for arm in ARMS:
        if demands[arm]["seed"] != seeds[arm]:
            raise EvidenceError(
                f"{extractor_name}: the {arm} demand manifest declares demand seed "
                f"{demands[arm]['seed']!r} but the record ran with {seeds[arm]!r}; refusing"
            )
    if demands["baseline"]["route_files"] != demands["ruled"]["route_files"]:
        raise EvidenceError(
            f"{extractor_name}: the arms ran DIFFERENT demand definitions (baseline "
            f"{demands['baseline']['route_files']}, ruled {demands['ruled']['route_files']}); a "
            "comparison between arms differing in anything but the rule is not a controlled "
            "experiment."
        )
    if demands["baseline"]["seed"] != demands["ruled"]["seed"]:
        raise EvidenceError(
            f"{extractor_name}: the arms declare DIFFERENT demand seeds "
            f"({demands['baseline']['seed']!r} vs {demands['ruled']['seed']!r}); the generated "
            "demand is not the same demand; refusing"
        )

    # The BASELINE arm must realise exactly the demand it was offered: nothing
    # there suppresses an insertion, so a mismatch means the manifest does not
    # describe the run and no comparison is trustworthy.
    #
    # The RULED arm is deliberately NOT held to that equality. A rule whose
    # effect is to suppress or add insertions makes offered and realised differ
    # BY DESIGN -- a closure that stops two vehicles entering is exactly the
    # consequence being measured -- and the original form of this check refused
    # to measure any such rule, because it read that difference as a broken
    # experiment. What keeps the comparison controlled is that the demand
    # DEFINITION (route files, seed, scale, offered counts) is identical across
    # the arms, and that is checked separately above and below.
    injected = demands["baseline"]["injected"]
    shown = record_counts["baseline"]
    if injected["vehicle"] != shown.get("vehicle", 0) or injected["person"] != shown.get("person", 0):
        raise EvidenceError(
            f"{extractor_name}: the baseline demand manifest declares {injected['vehicle']} "
            f"injected vehicle(s) and {injected['person']} person(s), but the sealed trajectory "
            f"record shows {shown.get('vehicle', 0)} vehicle(s) and {shown.get('person', 0)} "
            "person(s); the injected count must equal the count derivable from the record."
        )

    if not demand_is_the_rule:
        if demands["baseline"]["injected"] != demands["ruled"]["injected"]:
            raise EvidenceError(
                f"{extractor_name}: demand differs between the arms (baseline "
                f"{demands['baseline']['injected']} vs ruled {demands['ruled']['injected']}); a "
                "comparison between arms differing in anything but the rule is not a controlled "
                "experiment."
            )
        if demands["baseline"]["scale"] != demands["ruled"]["scale"]:
            raise EvidenceError(
                f"{extractor_name}: the arms declare DIFFERENT demand scales "
                f"({demands['baseline']['scale']} vs {demands['ruled']['scale']}); refusing"
            )
    elif demands["baseline"] == demands["ruled"]:
        raise EvidenceError(
            f"{extractor_name}: the two arms' demand manifests are identical, so the demand did not "
            "change and there is no demand effect to measure; refusing"
        )


# --- effect emission ------------------------------------------------------


def _effects(
    extractor_name: str,
    metrics: tuple[str, ...],
    baseline: dict[str, float],
    ruled: dict[str, float],
) -> list[dict[str, Any]]:
    """One `measured_effect` payload per metric that actually moved.

    An unlisted metric is refused here rather than reaching the ledger: an
    extractor may emit ONLY metrics present in
    `ldyf.persistent_changes._EFFECT_UNITS`.
    """
    payloads: list[dict[str, Any]] = []
    for metric in metrics:
        if metric not in _EFFECT_UNITS:
            raise EvidenceError(
                f"{extractor_name} would emit metric {metric!r}, which is not listed in "
                "ldyf.persistent_changes._EFFECT_UNITS; an extractor may emit ONLY listed metrics."
            )
        b = float(baseline[metric])
        r = float(ruled[metric])
        delta = round(r - b, 4)
        if delta == 0.0:
            continue
        payloads.append(
            {
                "kind": "measured_effect",
                "metric": metric,
                "baseline_value": b,
                "ruled_value": r,
                "delta": delta,
                "unit": _EFFECT_UNITS[metric],
                "source_field": f"tripinfo.{metric}",
            }
        )
    return payloads


# --- extractor 1: speed limit --------------------------------------------


def extract_speed_limit_effect_v1(
    simulation_result: dict[str, Any], evidence_dir: Path
) -> list[dict[str, Any]]:
    """Mean trip duration and time loss, baseline vs ruled.

    Metrics (both already in `_EFFECT_UNITS`): `avg_duration_s`, `avg_time_loss_s`.
    """
    name = "speed_limit_effect_v1"
    evidence_dir = Path(evidence_dir)
    arms = _load_arms(simulation_result, evidence_dir, name)
    counts = {arm: _scan_record(arm, arms[arm], name)["by_kind"] for arm in ARMS}
    _check_controlled_arms(name, simulation_result, arms, counts)

    summaries: dict[str, dict[str, float]] = {}
    for arm in ARMS:
        parsed = _tripinfo_summary(arm, arms[arm], name)
        _cross_check_counts(arm, arms[arm], parsed["summary"])
        summaries[arm] = parsed["summary"]
    return _effects(name, METRICS_SPEED_LIMIT, summaries["baseline"], summaries["ruled"])


# --- extractor 2: traffic light ------------------------------------------


def _read_junction(simulation_result: dict[str, Any], evidence_dir: Path, extractor_name: str) -> dict[str, Any]:
    """The controlled junction, from sealed evidence rather than from a caller."""
    path = verify_artifact_on_disk(simulation_result, TLS_JUNCTION_ARTIFACT, evidence_dir)
    doc = _read_json(path, "tls_junction", extractor_name)
    where = f"{extractor_name}: tls_junction {path.name}"
    if doc.get("schema_version") != JUNCTION_MANIFEST_VERSION:
        raise EvidenceError(
            f"{where} declares schema_version {doc.get('schema_version')!r}, expected "
            f"{JUNCTION_MANIFEST_VERSION!r}"
        )
    junction_id = doc.get("junction_id")
    if not isinstance(junction_id, str) or not junction_id:
        raise EvidenceError(f"{where} names no junction_id")
    centre = doc.get("centre_unreal_cm")
    if not isinstance(centre, (list, tuple)) or len(centre) != 2 or not all(_finite(v) for v in centre):
        raise EvidenceError(
            f"{where} centre_unreal_cm must be [x, y] in Unreal centimetres, got {centre!r}"
        )
    radius = doc.get("approach_radius_cm")
    if not _finite(radius) or radius <= 0:
        raise EvidenceError(f"{where} approach_radius_cm must be a positive finite number, got {radius!r}")
    return {
        "junction_id": junction_id,
        "centre": (float(centre[0]), float(centre[1])),
        "radius_cm": float(radius),
    }


def extract_traffic_light_effect_v1(
    simulation_result: dict[str, Any], evidence_dir: Path
) -> list[dict[str, Any]]:
    """Mean waiting time on the controlled junction approaches.

    The junction, and therefore the approach set, comes from the sealed
    `tls_junction` artefact and from the sealed record: a vehicle is on an
    approach if the record shows it inside `approach_radius_cm` of
    `centre_unreal_cm` at least once. Only its tripinfo trip counts, and a
    vehicle still in the network when the run ended has no tripinfo record --
    such a vehicle is reported by its absence, never invented a number.

    Metric (already in `_EFFECT_UNITS`): `avg_waiting_time_s`.
    """
    name = "traffic_light_effect_v1"
    evidence_dir = Path(evidence_dir)
    arms = _load_arms(simulation_result, evidence_dir, name)
    junction = _read_junction(simulation_result, evidence_dir, name)
    centre, radius = junction["centre"], junction["radius_cm"]

    counts: dict[str, dict[str, int]] = {}
    approach_ids: dict[str, set[str]] = {}
    for arm in ARMS:
        scan = _scan_record(arm, arms[arm], name, centre=centre, radius_cm=radius)
        counts[arm] = scan["by_kind"]
        actors = arms[arm]["manifest"]["actors"]
        approach_ids[arm] = {
            actors[idx].get("id")
            for idx in scan["near"]
            if actors[idx].get("kind") == "vehicle"
        }
    _check_controlled_arms(name, simulation_result, arms, counts)

    measured: dict[str, dict[str, float]] = {}
    for arm in ARMS:
        parsed = _tripinfo_summary(arm, arms[arm], name)
        _cross_check_counts(arm, arms[arm], parsed["summary"])
        near = approach_ids[arm]
        waits = [t["waitingTime"] for t in parsed["trips"] if t["id"] in near]
        if not waits:
            raise EvidenceError(
                f"{name}: the sealed junction {junction['junction_id']!r} selects no completed trip "
                f"in the {arm} arm ({len(near)} vehicle(s) approached, "
                f"{len(near - {t['id'] for t in parsed['trips']})} of them without a tripinfo "
                "record); a mean over zero trips is not a measurement; refusing"
            )
        measured[arm] = {"avg_waiting_time_s": _avg(waits)}
    return _effects(name, METRICS_TRAFFIC_LIGHT, measured["baseline"], measured["ruled"])


# --- extractor 3: demand flow --------------------------------------------


def extract_demand_flow_effect_v1(
    simulation_result: dict[str, Any], evidence_dir: Path
) -> list[dict[str, Any]]:
    """Trips completed and mean duration under a changed demand.

    The injected count is not taken on trust: each arm's sealed demand manifest
    must declare exactly the number of vehicles and persons the sealed trajectory
    record shows. The arms' demand DEFINITION (route files and demand seed) must
    still be identical -- the only thing allowed to differ between them is the
    demand the experiment scaled.

    Metrics (both already in `_EFFECT_UNITS`): `trips_completed`, `avg_duration_s`.
    """
    name = "demand_flow_effect_v1"
    evidence_dir = Path(evidence_dir)
    arms = _load_arms(simulation_result, evidence_dir, name)
    counts = {arm: _scan_record(arm, arms[arm], name)["by_kind"] for arm in ARMS}
    _check_controlled_arms(name, simulation_result, arms, counts, demand_is_the_rule=True)

    summaries: dict[str, dict[str, float]] = {}
    for arm in ARMS:
        parsed = _tripinfo_summary(arm, arms[arm], name)
        _cross_check_counts(arm, arms[arm], parsed["summary"])
        summaries[arm] = parsed["summary"]
    return _effects(name, METRICS_DEMAND_FLOW, summaries["baseline"], summaries["ruled"])


# --- extractor 4: pedestrians --------------------------------------------


def extract_pedestrian_effect_v1(
    simulation_result: dict[str, Any], evidence_dir: Path
) -> list[dict[str, Any]]:
    """Completed walks, mean walk duration and mean walk length.

    Metrics (all already in `_EFFECT_UNITS`): `walks_completed`,
    `avg_walk_duration_s`, `avg_walk_length_m`.
    """
    name = "pedestrian_effect_v1"
    evidence_dir = Path(evidence_dir)
    arms = _load_arms(simulation_result, evidence_dir, name)
    counts = {arm: _scan_record(arm, arms[arm], name)["by_kind"] for arm in ARMS}
    _check_controlled_arms(name, simulation_result, arms, counts)

    summaries: dict[str, dict[str, float]] = {}
    for arm in ARMS:
        parsed = _tripinfo_summary(arm, arms[arm], name)
        _cross_check_counts(arm, arms[arm], parsed["summary"])
        summaries[arm] = parsed["summary"]
    return _effects(name, METRICS_PEDESTRIAN, summaries["baseline"], summaries["ruled"])


# --- registration ---------------------------------------------------------

CONSEQUENCE_EXTRACTORS["speed_limit_effect_v1"] = extract_speed_limit_effect_v1
CONSEQUENCE_EXTRACTORS["traffic_light_effect_v1"] = extract_traffic_light_effect_v1
CONSEQUENCE_EXTRACTORS["demand_flow_effect_v1"] = extract_demand_flow_effect_v1
CONSEQUENCE_EXTRACTORS["pedestrian_effect_v1"] = extract_pedestrian_effect_v1
