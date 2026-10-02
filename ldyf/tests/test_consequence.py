"""Proof that the consequence extractors compute effects from sealed evidence,
that they refuse a comparison between arms that differ in anything but the rule,
and that they emit only metrics `_EFFECT_UNITS` lists.

The fixtures write a synthetic two-arm experiment straight to disk (tripinfo XML,
a Simulation Record V1 directory, a per-arm demand manifest) whose tripinfo and
record AGREE, with knobs for every way they can be made to disagree.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from ldyf.consequence import (
    METRICS_DEMAND_FLOW,
    METRICS_PEDESTRIAN,
    METRICS_SPEED_LIMIT,
    METRICS_TRAFFIC_LIGHT,
    _EMITTABLE_METRICS,
    extract_demand_flow_effect_v1,
    extract_pedestrian_effect_v1,
    extract_speed_limit_effect_v1,
    extract_traffic_light_effect_v1,
)
from ldyf.evidence import (
    EvidenceError,
    artifact_sha256,
    seal_simulation_result,
    sha256_file,
)
from ldyf.persistent_changes import (
    CONSEQUENCE_EXTRACTORS,
    LedgerError,
    _EFFECT_UNITS,
    append_simulation_consequence,
    compute_entry_hash,
    compute_ledger_hash,
    new_ledger,
    verify_ledger,
)

COUNT = struct.Struct("<I")
SAMPLE = struct.Struct("<Ifffff")

FRAMES = 20
STEP = 0.1
T_BEGIN = 0.0
SEED = 20260903
NET_A = "aa" * 32
NET_B = "bb" * 32
ROUTE = [{"file": "demand.rou.xml", "sha256": "cd" * 32}]
OTHER_ROUTE = [{"file": "other.rou.xml", "sha256": "ef" * 32}]
JUNCTION = {
    "schema_version": "tls_junction_v1",
    "junction_id": "B1",
    "centre_unreal_cm": [0.0, 0.0],
    "approach_radius_cm": 500.0,
}

# Two arms of one experiment: the rule lengthens every trip and its time loss.
# tripinfo ids are the record's actor ids, so an "approach" set derived from the
# record can be matched to a trip.
BASE_TRIPS = [("v0", 100, 900, 30, 50), ("v1", 120, 900, 30, 50)]
BASE_WALKS = [("p0", 200, 232), ("p1", 300, 150)]
RULED_TRIPS = [("v0", 140, 960, 45, 70), ("v1", 160, 960, 45, 70)]
RULED_WALKS = [("p0", 200, 240), ("p1", 300, 250), ("p2", 400, 260)]

BASE_ARM = dict(trips=BASE_TRIPS, walks=BASE_WALKS, vehicles=3, persons=4, approach=(0,))
RULED_ARM = dict(trips=RULED_TRIPS, walks=RULED_WALKS, vehicles=3, persons=4, approach=(0,))

# A demand experiment: same definition, same seed, the ruled arm injects more
# vehicles (and therefore completes fewer trips, which is the effect measured).
DEMAND_FLOW_ARMS = dict(
    baseline_over=dict(
        trips=[("v0", 100, 900, 30, 50), ("v1", 100, 900, 30, 50), ("v2", 100, 900, 30, 50)],
        walks=BASE_WALKS, vehicles=3, persons=4,
    ),
    ruled_over=dict(
        trips=[("v0", 160, 960, 45, 70), ("v1", 160, 960, 45, 70)],
        walks=BASE_WALKS, vehicles=5, persons=4, scale=1.5,
    ),
)


# --- fixture writers ------------------------------------------------------


def write_tripinfo(path: Path, *, trips=(), walks=()) -> None:
    lines = ['<?xml version="1.0"?>', "<tripinfos>"]
    for tid, duration, length, waiting, loss in trips:
        lines.append(
            f'  <tripinfo id="{tid}" duration="{duration}" routeLength="{length}" '
            f'waitingTime="{waiting}" timeLoss="{loss}"/>'
        )
    for person, length, duration in walks:
        lines.append(
            f'  <personinfo id="{person}"><walk duration="{duration}" routeLength="{length}"/></personinfo>'
        )
    lines.append("</tripinfos>")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_record(
    directory: Path,
    *,
    vehicles: int,
    persons: int,
    arrive_v: int,
    arrive_p: int,
    approach=(),
    frames: int = FRAMES,
    step_seconds: float = STEP,
    t_begin: float = T_BEGIN,
    net_sha256=NET_A,
    seed=SEED,
    net_file: str = "net.net.xml",
) -> Path:
    """A record whose first `arrive_v` vehicles and `arrive_p` persons leave
    before the final frame (they arrived); the rest are present to the end."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    last_seen = t_begin + max(0, frames - 1) * step_seconds
    arrived_seen = t_begin + max(0, frames - 3) * step_seconds
    actors = []
    for i in range(vehicles):
        actors.append(
            {"uid": f"vehicle:v{i}", "id": f"v{i}", "kind": "vehicle", "type": "passenger",
             "first_seen_time": t_begin,
             "last_seen_time": arrived_seen if i < arrive_v else last_seen}
        )
    for j in range(persons):
        actors.append(
            {"uid": f"person:p{j}", "id": f"p{j}", "kind": "person", "type": "pedestrian",
             "first_seen_time": t_begin,
             "last_seen_time": arrived_seen if j < arrive_p else last_seen}
        )

    arriving = set(range(arrive_v)) | set(range(vehicles, vehicles + arrive_p))
    blob = bytearray()
    samples = 0
    for f in range(frames):
        rows = []
        for idx in range(len(actors)):
            if idx in arriving and f >= frames - 2:
                continue
            if idx < vehicles:
                if idx in approach:
                    x, y = (f - frames // 2) * 100.0, 0.0
                else:
                    x, y = 10_000.0 + 200.0 * idx, 10_000.0
            else:
                x, y = 20_000.0 + 200.0 * (idx - vehicles), 20_000.0
            rows.append((idx, x, y, 0.0, 0.0, 1.0))
        samples += len(rows)
        blob += COUNT.pack(len(rows))
        for r in rows:
            blob += SAMPLE.pack(*r)

    frames_path = directory / "frames.bin"
    frames_path.write_bytes(bytes(blob))
    manifest = {
        "format": "simulation_record_v1",
        "coordinate_system": {"target": "unreal", "linear_units": "centimetres"},
        "clock": {
            "step_seconds": step_seconds,
            "frame_count": frames,
            "t_begin": t_begin,
            "t_end": t_begin + max(0, frames - 1) * step_seconds,
            "frame_time_rule": "t(i) = t_begin + i * step_seconds",
        },
        "counts": {
            "actors": len(actors),
            "samples": samples,
            "peak_concurrent_actors": len(actors),
            "by_kind": {"vehicle": vehicles, "person": persons},
        },
        "source": {
            "fcd_file": f"{directory.name}.fcd.xml",
            "net_file": net_file,
            "net_sha256": net_sha256,
            "seed": seed,
            "sumo_version": "1.27.1",
        },
        "binary": {
            "file": "frames.bin",
            "sample_struct": "<Ifffff",
            "sample_bytes": SAMPLE.size,
            "sha256": sha256_file(frames_path),
            "bytes": len(blob),
        },
        "actors": actors,
    }
    (directory / "record_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return directory


def write_demand(path: Path, *, arm: str, route_files, seed, injected, scale: float = 1.0) -> None:
    doc = {
        "schema_version": "demand_manifest_v1",
        "arm": arm,
        "route_files": route_files,
        "seed": seed,
        "injected": injected,
        "scale": scale,
    }
    Path(path).write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")


def write_junction(path: Path, doc: dict = JUNCTION) -> None:
    Path(path).write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")


def arm_files(
    tmp_path: Path,
    arm: str,
    *,
    trips=(),
    walks=(),
    vehicles: int = 3,
    persons: int = 4,
    arrive_v=None,
    arrive_p=None,
    approach=(0,),
    net_sha256=NET_A,
    seed=SEED,
    injected=None,
    route_files=None,
    demand_seed=None,
    scale: float = 1.0,
    frames: int = FRAMES,
    inflate_trips: int = 0,
    inflate_walks: int = 0,
) -> dict:
    """Write one arm's four artefacts; return their evidence-relative names."""
    arrive_v = len(trips) if arrive_v is None else arrive_v
    arrive_p = len(walks) if arrive_p is None else arrive_p
    trip_file = f"{arm}.tripinfo.xml"
    record_dir = f"record_{arm}"
    demand_file = f"{arm}.demand.json"

    write_tripinfo(
        tmp_path / trip_file,
        trips=list(trips) + [("invented", 1.0, 1.0, 0.0, 0.0)] * inflate_trips,
        walks=list(walks) + [("invented", 1.0, 1.0)] * inflate_walks,
    )
    write_record(
        tmp_path / record_dir,
        vehicles=vehicles,
        persons=persons,
        arrive_v=arrive_v,
        arrive_p=arrive_p,
        approach=approach,
        frames=frames,
        net_sha256=net_sha256,
        seed=seed,
    )
    write_demand(
        tmp_path / demand_file,
        arm=arm,
        route_files=ROUTE if route_files is None else route_files,
        seed=seed if demand_seed is None else demand_seed,
        injected={"vehicle": vehicles, "person": persons} if injected is None else injected,
        scale=scale,
    )
    return {
        "tripinfo": trip_file,
        "record_manifest": f"{record_dir}/record_manifest.json",
        "record_frames": f"{record_dir}/frames.bin",
        "demand": demand_file,
    }


def make_evidence(
    tmp_path: Path,
    *,
    baseline_over=None,
    ruled_over=None,
    junction: bool = True,
    episode: int = 1,
    run_seed: int = SEED,
) -> dict:
    """Build and seal a two-arm `simulation_result` over the written artefacts."""
    base = arm_files(tmp_path, "baseline", **{**BASE_ARM, **(baseline_over or {})})
    ruled = arm_files(tmp_path, "ruled", **{**RULED_ARM, **(ruled_over or {})})

    artifacts: dict = {}
    for arm, files in (("baseline", base), ("ruled", ruled)):
        artifacts[f"{arm}_tripinfo"] = {
            "file": files["tripinfo"], "sha256": artifact_sha256(tmp_path / files["tripinfo"])}
        artifacts[f"{arm}_record_manifest"] = {
            "file": files["record_manifest"],
            "sha256": artifact_sha256(tmp_path / files["record_manifest"])}
        artifacts[f"{arm}_record_frames"] = {
            "file": files["record_frames"],
            "sha256": artifact_sha256(tmp_path / files["record_frames"])}
        artifacts[f"{arm}_demand"] = {
            "file": files["demand"], "sha256": artifact_sha256(tmp_path / files["demand"])}
    if junction:
        write_junction(tmp_path / "tls_junction.json")
        artifacts["tls_junction"] = {
            "file": "tls_junction.json", "sha256": artifact_sha256(tmp_path / "tls_junction.json")}

    return seal_simulation_result(
        {
            "schema_version": "simulation_result_v1",
            "run_id": "ruled",
            "episode_number": episode,
            "arm": "ruled",
            "seed": run_seed,
            "sumo_version": "1.27.1",
            "applied_at_sim_second": 150.0,
            "artifacts": artifacts,
            "result_hash": "",
        }
    )


def resealed(result: dict, **artifacts) -> dict:
    """Re-seal a result with artefact byte-identities replaced (`name=sha256`)."""
    doc = json.loads(json.dumps(result))
    for name, sha in artifacts.items():
        doc["artifacts"][name]["sha256"] = sha
    doc["result_hash"] = ""
    return seal_simulation_result(doc)


def by_metric(payloads: list) -> dict:
    return {p["metric"]: p for p in payloads}


# ==========================================================================
# Registration and the closed metric vocabulary
# ==========================================================================


def test_all_four_extractors_are_registered():
    assert CONSEQUENCE_EXTRACTORS["speed_limit_effect_v1"] is extract_speed_limit_effect_v1
    assert CONSEQUENCE_EXTRACTORS["traffic_light_effect_v1"] is extract_traffic_light_effect_v1
    assert CONSEQUENCE_EXTRACTORS["demand_flow_effect_v1"] is extract_demand_flow_effect_v1
    assert CONSEQUENCE_EXTRACTORS["pedestrian_effect_v1"] is extract_pedestrian_effect_v1


def test_no_extractor_may_emit_a_metric_outside_the_effect_units_table():
    assert set(_EMITTABLE_METRICS) <= set(_EFFECT_UNITS)
    for metrics in (METRICS_SPEED_LIMIT, METRICS_TRAFFIC_LIGHT, METRICS_DEMAND_FLOW, METRICS_PEDESTRIAN):
        assert set(metrics) <= set(_EFFECT_UNITS), metrics
        assert set(metrics) <= set(_EMITTABLE_METRICS), metrics


# ==========================================================================
# The four extractors, computing
# ==========================================================================


def test_speed_limit_effect_is_mean_duration_and_time_loss(tmp_path):
    result = make_evidence(tmp_path)
    payloads = extract_speed_limit_effect_v1(result, tmp_path)
    got = by_metric(payloads)
    assert set(got) == {"avg_duration_s", "avg_time_loss_s"}
    assert got["avg_duration_s"]["baseline_value"] == 110.0        # (100 + 120) / 2
    assert got["avg_duration_s"]["ruled_value"] == 150.0           # (140 + 160) / 2
    assert got["avg_duration_s"]["delta"] == 40.0
    assert got["avg_time_loss_s"]["delta"] == 20.0
    for p in payloads:
        assert p["unit"] == _EFFECT_UNITS[p["metric"]]
        assert p["source_field"] == f"tripinfo.{p['metric']}"
        assert p["kind"] == "measured_effect"


def test_traffic_light_effect_measures_only_the_junction_approaches(tmp_path):
    """Only vehicle v0 drives through the sealed junction centre; v1 does not.
    Its waiting time barely moves while v1's explodes, so an unfiltered mean
    would report a different number."""
    result = make_evidence(
        tmp_path,
        baseline_over=dict(trips=[("v0", 100, 900, 30, 50), ("v1", 120, 900, 10, 50)]),
        ruled_over=dict(trips=[("v0", 140, 960, 35, 70), ("v1", 160, 960, 100, 70)]),
    )
    got = by_metric(extract_traffic_light_effect_v1(result, tmp_path))
    assert set(got) == {"avg_waiting_time_s"}
    assert got["avg_waiting_time_s"]["baseline_value"] == 30.0
    assert got["avg_waiting_time_s"]["ruled_value"] == 35.0
    assert got["avg_waiting_time_s"]["delta"] == 5.0               # not 47.5


def test_traffic_light_effect_reports_nothing_when_the_junction_is_unchanged(tmp_path):
    """No metric moved at the junction, so nothing is claimed about it."""
    result = make_evidence(
        tmp_path,
        baseline_over=dict(trips=[("v0", 100, 900, 30, 50), ("v1", 120, 900, 10, 50)]),
        ruled_over=dict(trips=[("v0", 140, 960, 30, 70), ("v1", 160, 960, 100, 70)]),
    )
    assert extract_traffic_light_effect_v1(result, tmp_path) == []


def test_demand_flow_effect_counts_trips_and_duration(tmp_path):
    result = make_evidence(tmp_path, **DEMAND_FLOW_ARMS)
    got = by_metric(extract_demand_flow_effect_v1(result, tmp_path))
    assert set(got) == {"trips_completed", "avg_duration_s"}
    assert got["trips_completed"]["baseline_value"] == 3.0
    assert got["trips_completed"]["ruled_value"] == 2.0
    assert got["trips_completed"]["delta"] == -1.0
    assert got["avg_duration_s"]["baseline_value"] == 100.0
    assert got["avg_duration_s"]["ruled_value"] == 160.0
    assert got["avg_duration_s"]["delta"] == 60.0


def test_pedestrian_effect_reports_walks(tmp_path):
    result = make_evidence(tmp_path)
    got = by_metric(extract_pedestrian_effect_v1(result, tmp_path))
    assert set(got) == {"walks_completed", "avg_walk_duration_s", "avg_walk_length_m"}
    assert got["walks_completed"]["baseline_value"] == 2.0
    assert got["walks_completed"]["ruled_value"] == 3.0
    assert got["walks_completed"]["delta"] == 1.0
    assert got["avg_walk_length_m"]["baseline_value"] == 250.0     # (200 + 300) / 2
    assert got["avg_walk_length_m"]["ruled_value"] == 300.0        # (200 + 300 + 400) / 3
    assert got["avg_walk_length_m"]["delta"] == 50.0
    assert got["avg_walk_duration_s"]["baseline_value"] == 191.0   # (232 + 150) / 2
    assert got["avg_walk_duration_s"]["ruled_value"] == 250.0
    assert got["avg_walk_duration_s"]["delta"] == 59.0


def test_extractors_are_deterministic(tmp_path):
    result = make_evidence(tmp_path)
    assert extract_speed_limit_effect_v1(result, tmp_path) == extract_speed_limit_effect_v1(result, tmp_path)


# ==========================================================================
# Cross-checks between the arms
# ==========================================================================


def test_attack_mismatched_net_between_arms_is_refused(tmp_path):
    result = make_evidence(tmp_path, ruled_over=dict(net_sha256=NET_B))
    with pytest.raises(EvidenceError, match="DIFFERENT nets"):
        extract_speed_limit_effect_v1(result, tmp_path)


def test_attack_mismatched_seed_between_arms_is_refused(tmp_path):
    result = make_evidence(tmp_path, ruled_over=dict(seed=SEED + 1))
    with pytest.raises(EvidenceError, match="DIFFERENT seeds"):
        extract_speed_limit_effect_v1(result, tmp_path)


def test_attack_a_record_that_declares_no_seed_is_refused(tmp_path):
    result = make_evidence(tmp_path, ruled_over=dict(seed=None, demand_seed=SEED))
    with pytest.raises(EvidenceError, match="does not record the seed"):
        extract_speed_limit_effect_v1(result, tmp_path)


def test_attack_mismatched_demand_between_arms_is_refused(tmp_path):
    """Both arms' records match their own declared demand, but it is not the
    same demand -- so the comparison is not controlled."""
    result = make_evidence(
        tmp_path, ruled_over=dict(vehicles=4, injected={"vehicle": 4, "person": 4})
    )
    with pytest.raises(EvidenceError, match="demand differs between the arms"):
        extract_speed_limit_effect_v1(result, tmp_path)


def test_attack_a_different_demand_scale_between_arms_is_refused(tmp_path):
    result = make_evidence(tmp_path, ruled_over=dict(scale=1.5))
    with pytest.raises(EvidenceError, match="DIFFERENT demand scales"):
        extract_speed_limit_effect_v1(result, tmp_path)


def test_attack_different_demand_definitions_are_refused(tmp_path):
    result = make_evidence(tmp_path, ruled_over=dict(route_files=OTHER_ROUTE))
    with pytest.raises(EvidenceError, match="DIFFERENT demand definitions"):
        extract_speed_limit_effect_v1(result, tmp_path)


def test_attack_a_demand_seed_that_contradicts_the_record_is_refused(tmp_path):
    result = make_evidence(tmp_path, ruled_over=dict(demand_seed=SEED + 5))
    with pytest.raises(EvidenceError, match="demand seed"):
        extract_speed_limit_effect_v1(result, tmp_path)


def test_attack_an_injected_count_that_contradicts_the_record_is_refused(tmp_path):
    """The demand manifest claims 4 vehicles; the sealed record shows 3."""
    result = make_evidence(tmp_path, baseline_over=dict(injected={"vehicle": 4, "person": 4}))
    with pytest.raises(EvidenceError, match="must equal the count derivable from the record"):
        extract_speed_limit_effect_v1(result, tmp_path)


def test_attack_a_demand_experiment_whose_demand_did_not_change_is_refused(tmp_path):
    """Identical arms make a demand effect unmeasurable, so nothing is claimed."""
    result = make_evidence(tmp_path)
    with pytest.raises(EvidenceError, match="no demand effect to measure"):
        extract_demand_flow_effect_v1(result, tmp_path)


# ==========================================================================
# Cross-checks inside an arm: tripinfo against the record
# ==========================================================================


def test_attack_tripinfo_trip_count_disagreeing_with_the_record_is_refused(tmp_path):
    result = make_evidence(tmp_path, ruled_over=dict(inflate_trips=1))
    with pytest.raises(EvidenceError, match="not from the same run"):
        extract_speed_limit_effect_v1(result, tmp_path)


def test_attack_tripinfo_walk_count_disagreeing_with_the_record_is_refused(tmp_path):
    result = make_evidence(tmp_path, baseline_over=dict(inflate_walks=1))
    with pytest.raises(EvidenceError, match="not from the same run"):
        extract_pedestrian_effect_v1(result, tmp_path)


def test_attack_tripinfo_edited_after_sealing_is_refused(tmp_path):
    result = make_evidence(tmp_path)
    write_tripinfo(tmp_path / "ruled.tripinfo.xml", trips=[("v0", 999, 1, 1, 1)], walks=[])
    with pytest.raises(EvidenceError, match="does not match the sealed result"):
        extract_speed_limit_effect_v1(result, tmp_path)


# ==========================================================================
# Refusing an unusable record
# ==========================================================================


def test_attack_a_record_truncated_after_sealing_is_refused(tmp_path):
    result = make_evidence(tmp_path)
    frames = tmp_path / "record_ruled" / "frames.bin"
    frames.write_bytes(frames.read_bytes()[:-5])
    with pytest.raises(EvidenceError, match="does not match the sealed result"):
        extract_speed_limit_effect_v1(result, tmp_path)


def test_attack_a_truncated_record_resealed_is_refused(tmp_path):
    result = make_evidence(tmp_path)
    frames = tmp_path / "record_ruled" / "frames.bin"
    frames.write_bytes(frames.read_bytes()[:-5])
    result = resealed(result, ruled_record_frames=sha256_file(frames))
    with pytest.raises(EvidenceError, match="truncated"):
        extract_speed_limit_effect_v1(result, tmp_path)


def test_attack_an_empty_record_resealed_is_refused(tmp_path):
    result = make_evidence(tmp_path)
    frames = tmp_path / "record_ruled" / "frames.bin"
    frames.write_bytes(b"")
    result = resealed(result, ruled_record_frames=sha256_file(frames))
    with pytest.raises(EvidenceError, match="empty"):
        extract_speed_limit_effect_v1(result, tmp_path)


def test_attack_a_tripinfo_with_a_non_finite_duration_is_refused(tmp_path):
    result = make_evidence(tmp_path)
    (tmp_path / "ruled.tripinfo.xml").write_text(
        '<?xml version="1.0"?>\n<tripinfos>\n'
        '  <tripinfo id="v0" duration="nan" routeLength="960" waitingTime="45" timeLoss="70"/>\n'
        '  <tripinfo id="v1" duration="160" routeLength="960" waitingTime="45" timeLoss="70"/>\n'
        "</tripinfos>\n",
        encoding="utf-8",
    )
    result = resealed(result, ruled_tripinfo=artifact_sha256(tmp_path / "ruled.tripinfo.xml"))
    with pytest.raises(EvidenceError, match="non-finite"):
        extract_speed_limit_effect_v1(result, tmp_path)


def test_a_record_manifest_that_lies_about_its_frame_count_is_refused(tmp_path):
    result = make_evidence(tmp_path)
    manifest_path = tmp_path / "record_ruled" / "record_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["clock"]["frame_count"] = FRAMES + 7
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    result = resealed(result, ruled_record_manifest=sha256_file(manifest_path))
    with pytest.raises(EvidenceError, match="declares"):
        extract_speed_limit_effect_v1(result, tmp_path)


# ==========================================================================
# Missing evidence
# ==========================================================================


def test_attack_a_result_without_demand_artefacts_is_refused(tmp_path):
    result = make_evidence(tmp_path)
    doc = json.loads(json.dumps(result))
    del doc["artifacts"]["baseline_demand"]
    doc["result_hash"] = ""
    with pytest.raises(EvidenceError, match="names no artefact 'baseline_demand'"):
        extract_speed_limit_effect_v1(seal_simulation_result(doc), tmp_path)


def test_attack_a_missing_artefact_on_disk_is_refused(tmp_path):
    result = make_evidence(tmp_path)
    (tmp_path / "record_baseline" / "frames.bin").unlink()
    with pytest.raises(EvidenceError, match="not found on disk"):
        extract_speed_limit_effect_v1(result, tmp_path)


def test_attack_a_result_without_a_junction_artefact_is_refused(tmp_path):
    result = make_evidence(tmp_path, junction=False)
    with pytest.raises(EvidenceError, match="names no artefact 'tls_junction'"):
        extract_traffic_light_effect_v1(result, tmp_path)


def test_attack_a_junction_that_selects_no_completed_trip_is_refused(tmp_path):
    """Vehicle v2 drives the junction but never finished, so it has no tripinfo
    record: a mean over zero trips is not a measurement."""
    result = make_evidence(tmp_path, baseline_over=dict(approach=(2,)), ruled_over=dict(approach=(2,)))
    with pytest.raises(EvidenceError, match="no completed trip"):
        extract_traffic_light_effect_v1(result, tmp_path)


# ==========================================================================
# Through the ledger
# ==========================================================================


@pytest.mark.parametrize(
    "extractor,over",
    [
        ("speed_limit_effect_v1", {}),
        ("traffic_light_effect_v1", {}),
        ("pedestrian_effect_v1", {}),
        ("demand_flow_effect_v1", DEMAND_FLOW_ARMS),
    ],
)
def test_each_extractor_round_trips_through_the_ledger(tmp_path, extractor, over):
    result = make_evidence(tmp_path, **over)
    (tmp_path / "simulation_result.json").write_text(json.dumps(result), encoding="utf-8")

    ledger, ids = append_simulation_consequence(
        new_ledger("riverside"),
        simulation_result=result,
        extractor_name=extractor,
        evidence_dir=tmp_path,
    )
    verify_ledger(ledger)
    verify_ledger(ledger, evidence_dir=tmp_path)            # re-derives from the sealed bytes
    assert ids
    for entry in ledger["entries"]:
        payload = entry["payload"]
        assert payload["metric"] in _EFFECT_UNITS
        assert payload["unit"] == _EFFECT_UNITS[payload["metric"]]
        assert payload["source_field"] == f"tripinfo.{payload['metric']}"
        assert entry["provenance"]["extractor"] == extractor
        assert entry["provenance"]["record_sha256"] == result["artifacts"]["ruled_record_frames"]["sha256"]


def test_an_edited_effect_is_refused_by_evidence_aware_verification(tmp_path):
    result = make_evidence(tmp_path)
    (tmp_path / "simulation_result.json").write_text(json.dumps(result), encoding="utf-8")
    ledger, _ = append_simulation_consequence(
        new_ledger("riverside"), simulation_result=result,
        extractor_name="speed_limit_effect_v1", evidence_dir=tmp_path,
    )
    tampered = json.loads(json.dumps(ledger))
    tampered["entries"][0]["payload"]["ruled_value"] = 999.0
    tampered["entries"][0]["payload"]["delta"] = 889.0
    prev = "0" * 64
    for entry in tampered["entries"]:
        entry["prev_hash"] = prev
        entry["entry_hash"] = compute_entry_hash(entry)
        prev = entry["entry_hash"]
    tampered["ledger_hash"] = compute_ledger_hash(tampered["entries"])
    with pytest.raises(LedgerError, match="not one the extractor derives"):
        verify_ledger(tampered, evidence_dir=tmp_path)
