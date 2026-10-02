"""Proof that THE WORLD REMEMBERS cannot be forged, and that only sealed,
mutually consistent evidence plus a deterministic extractor can create
simulation truth.

The centrepiece is the ATTACK section. It includes every attack the Phase 1
adversarial review (DeepSeek worker `attack_provenance`) found, each of which
must now fail.
"""

from __future__ import annotations

import copy
import json
import struct
from pathlib import Path

import pytest

from ldyf.evidence import artifact_sha256, EvidenceError, seal_rule_manifest, seal_simulation_result, sha256_file
from ldyf.persistent_changes import (
    CONSEQUENCE_EXTRACTORS,
    GENESIS_HASH,
    LedgerError,
    _append_entry,
    active_changes,
    append_director_rule,
    append_reversal,
    append_simulation_consequence,
    changes_from_episode,
    compute_entry_hash,
    compute_ledger_hash,
    history_of,
    is_active,
    load,
    make_change_id,
    new_ledger,
    save,
    verify_ledger,
)

_SAMPLE = struct.Struct("<Ifffff")
_COUNT = struct.Struct("<I")


# --------------------------------------------------------------------------
# Fixture builders: a synthetic run whose tripinfo and record AGREE, with a
# knob to make them disagree. Mirrors ldyf.sumo_record's binary layout.
# --------------------------------------------------------------------------

def write_record(dir_: Path, *, vehicles: int, persons: int, arrive_v: int, arrive_p: int,
                 frames: int = 20) -> None:
    """Actors 0..arrive-1 leave before the final frame (they 'arrived');
    the rest are present through the last frame."""
    dir_.mkdir(parents=True, exist_ok=True)
    actors = ([{"uid": f"vehicle:{i}", "id": str(i), "kind": "vehicle", "type": "T", "first_seen_time": 0.0}
               for i in range(vehicles)] +
              [{"uid": f"person:{i}", "id": str(i), "kind": "person", "type": "P", "first_seen_time": 0.0}
               for i in range(persons)])
    arriving = set(range(arrive_v)) | set(range(vehicles, vehicles + arrive_p))
    blob = bytearray()
    for f in range(frames):
        rows = []
        for idx in range(len(actors)):
            if idx in arriving and f >= frames - 2:
                continue                       # gone before the last frame
            rows.append((idx, float(f), float(idx), 0.0, 0.0, 1.0))
        blob += _COUNT.pack(len(rows))
        for r in rows:
            blob += _SAMPLE.pack(*r)
    (dir_ / "frames.bin").write_bytes(bytes(blob))
    manifest = {"format": "simulation_record_v1", "actors": actors,
                "clock": {"step_seconds": 0.1, "frame_count": frames, "t_begin": 0.0, "t_end": 0.1 * (frames - 1)},
                "binary": {"file": "frames.bin", "sha256": sha256_file(dir_ / "frames.bin")}}
    (dir_ / "record_manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")


def write_tripinfo(path: Path, *, trips: list[tuple[float, float, float, float]],
                   walks: list[tuple[float, float]]) -> None:
    lines = ['<?xml version="1.0"?>', "<tripinfos>"]
    for i, (d, rl, wt, tl) in enumerate(trips):
        lines.append(f'  <tripinfo id="v{i}" duration="{d}" routeLength="{rl}" waitingTime="{wt}" timeLoss="{tl}"/>')
    for i, (rl, d) in enumerate(walks):
        lines.append(f'  <personinfo id="p{i}"><walk duration="{d}" routeLength="{rl}"/></personinfo>')
    lines.append("</tripinfos>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_evidence(tmp_path: Path, *, episode: int = 1, consistent: bool = True,
                  base_trips=((100, 900, 30, 50), (120, 900, 30, 50)),
                  ruled_trips=((140, 960, 45, 70),),
                  walks=((232, 200),)) -> dict:
    """Two arms: baseline completes len(base_trips), ruled completes len(ruled_trips)."""
    write_tripinfo(tmp_path / "baseline.tripinfo.xml", trips=list(base_trips), walks=list(walks))
    write_tripinfo(tmp_path / "ruled.tripinfo.xml", trips=list(ruled_trips), walks=list(walks))
    # records: 3 vehicles + 1 person in each arm
    write_record(tmp_path / "record_baseline", vehicles=3, persons=1,
                 arrive_v=len(base_trips), arrive_p=len(walks))
    write_record(tmp_path / "record_ruled", vehicles=3, persons=1,
                 arrive_v=len(ruled_trips) if consistent else len(ruled_trips) + 1,
                 arrive_p=len(walks))
    arts = {}
    for name, rel in (("baseline_tripinfo", "baseline.tripinfo.xml"),
                      ("ruled_tripinfo", "ruled.tripinfo.xml"),
                      ("baseline_record_manifest", "record_baseline/record_manifest.json"),
                      ("baseline_record_frames", "record_baseline/frames.bin"),
                      ("ruled_record_manifest", "record_ruled/record_manifest.json"),
                      ("ruled_record_frames", "record_ruled/frames.bin")):
        arts[name] = {"file": rel, "sha256": artifact_sha256(tmp_path / rel)}
    return seal_simulation_result({
        "schema_version": "simulation_result_v1", "run_id": "ruled",
        "episode_number": episode, "arm": "ruled", "seed": 20260903,
        "sumo_version": "1.27.1", "applied_at_sim_second": 150.0,
        "artifacts": arts, "result_hash": "",
    })


def rule_doc(episode=1, rule_id="close_the_bridge", change=None, statement="Close the bridge."):
    """A contract-complete ONE RULE manifest (unsealed)."""
    return {
        "schema_version": "rule_manifest_v1", "rule_id": rule_id, "episode_number": episode,
        "declared_utc": "2026-09-03T00:00:00Z", "statement": statement,
        "applies_at_sim_second": 150.0, "permanent": True, "baseline_required": True,
        "prediction": {"text": "Trips through the centre lengthen and fewer complete.",
                       "declared_before_run": True, "metric": "trips_completed",
                       "direction": "decrease"},
        "change": change or {"close_edges": {"edge_ids": ["B1C1"], "disallow": ["passenger"]}},
        "manifest_hash": "",
    }


def make_rule(episode=1, rule_id="close_the_bridge", edges=("B1C1",), disallow=("passenger",)):
    return seal_rule_manifest(rule_doc(
        episode, rule_id,
        {"close_edges": {"edge_ids": list(edges), "disallow": list(disallow)}}))


def ruled_ledger(episode=1):
    """A ledger that already carries the closure rule a measurement is OF.

    A measured effect must be attributed to a rule on the ledger, of a class its
    extractor is for; an unattributed measurement is refused. Tests that are
    about something else start from here.
    """
    lg, _ = append_director_rule(new_ledger("riverside"), rule_manifest=make_rule(episode=episode))
    return lg


RULE = "close_the_bridge"


def sim_prov(result: dict) -> dict:
    return {"source": "simulation", "simulation_result_sha256": result["result_hash"],
            "run_id": "ruled", "extractor": "closure_effect_v1",
            "record_sha256": result["artifacts"]["ruled_record_frames"]["sha256"]}


def _resealed(ledger: dict, entries: list) -> dict:
    """Attacker helper: splice entries and recompute all chain hashes correctly."""
    bad = copy.deepcopy(ledger)
    prev = GENESIS_HASH
    fixed = []
    for e in entries:
        e = copy.deepcopy(e)
        e["prev_hash"] = prev
        e["entry_hash"] = compute_entry_hash(e)
        prev = e["entry_hash"]
        fixed.append(e)
    bad["entries"] = fixed
    bad["ledger_hash"] = compute_ledger_hash(fixed)
    return bad


# ==========================================================================
# ATTACKS -- every one must fail
# ==========================================================================

def test_no_public_writer_accepts_provenance_or_payload():
    import inspect

    import ldyf.persistent_changes as pc

    assert "append_change" not in pc.__all__ and not hasattr(pc, "append_change")
    assert "_append_entry" not in pc.__all__
    for name in ("append_director_rule", "append_reversal", "append_simulation_consequence"):
        params = inspect.signature(getattr(pc, name)).parameters
        assert "provenance" not in params and "payload" not in params, name


def test_attack_direct_append_entry_forgery_fails_verify(tmp_path):
    """Worker finding 2: call the private writer directly with a made-up effect."""
    result = make_evidence(tmp_path)
    lg = new_ledger("riverside")
    forged_payload = {"kind": "measured_effect", "metric": "trips_completed",
                      "baseline_value": 381.0, "ruled_value": 0.0, "delta": -999.0,
                      "unit": "trips", "source_field": "tripinfo.trips_completed"}
    with pytest.raises(LedgerError, match="delta does not equal"):
        _append_entry(lg, change_type="measured_effect", origin_episode=1,
                      applied_at_sim_second=0.0, payload=forged_payload,
                      provenance=sim_prov(result))


def test_attack_forged_entry_with_bogus_seal_hash_is_rejected_on_verify(tmp_path):
    """Worker finding 2b: hand-splice an entry whose provenance hash is not 64-hex."""
    lg, _ = append_director_rule(new_ledger("riverside"), rule_manifest=make_rule())
    forged = copy.deepcopy(lg["entries"][0])
    forged["change_id"] = "chg_" + "a" * 16
    forged["change_type"] = "measured_effect"
    forged["payload"] = {"kind": "measured_effect", "metric": "avg_time_loss_s",
                         "baseline_value": 50.0, "ruled_value": 70.0, "delta": 20.0,
                         "unit": "s", "source_field": "tripinfo.avg_time_loss_s"}
    forged["provenance"] = {"source": "simulation", "simulation_result_sha256": "0" * 64,
                            "run_id": "ruled", "extractor": "closure_effect_v1"}
    bad = _resealed(lg, lg["entries"] + [forged])
    with pytest.raises(LedgerError, match="record sha256|record_sha256"):
        verify_ledger(bad)


def test_attack_forged_measured_effect_with_unknown_metric_is_rejected(tmp_path):
    result = make_evidence(tmp_path)
    lg, _ = append_director_rule(new_ledger("riverside"), rule_manifest=make_rule())
    forged = copy.deepcopy(lg["entries"][0])
    forged["change_id"] = "chg_" + "b" * 16
    forged["change_type"] = "measured_effect"
    forged["payload"] = {"kind": "measured_effect", "metric": "citizens_made_happy",
                         "baseline_value": 0.0, "ruled_value": 1000.0, "delta": 1000.0,
                         "unit": "", "source_field": "tripinfo.citizens_made_happy"}
    forged["provenance"] = sim_prov(result)
    bad = _resealed(lg, lg["entries"] + [forged])
    with pytest.raises(LedgerError, match="unknown metric|schema violation at entries/1/payload"):
        verify_ledger(bad)


def test_attack_own_fabricated_tripinfo_without_records_is_refused(tmp_path):
    """Worker finding 1: seal your own tripinfo. Now refused: records are required."""
    (tmp_path / "baseline.tripinfo.xml").write_text(
        '<?xml version="1.0"?><tripinfos><tripinfo id="v" duration="1" routeLength="1" waitingTime="0" timeLoss="0"/></tripinfos>')
    (tmp_path / "ruled.tripinfo.xml").write_text(
        '<?xml version="1.0"?><tripinfos></tripinfos>')
    result = seal_simulation_result({
        "schema_version": "simulation_result_v1", "run_id": "ruled", "episode_number": 1,
        "arm": "ruled", "seed": 1, "sumo_version": "1.27.1",
        "artifacts": {"baseline_tripinfo": {"file": "baseline.tripinfo.xml",
                                            "sha256": artifact_sha256(tmp_path / "baseline.tripinfo.xml")},
                      "ruled_tripinfo": {"file": "ruled.tripinfo.xml",
                                         "sha256": artifact_sha256(tmp_path / "ruled.tripinfo.xml")}},
        "result_hash": ""})
    with pytest.raises(EvidenceError, match="names no artefact 'baseline_record_frames'"):
        append_simulation_consequence(new_ledger("riverside"), simulation_result=result,
                                      extractor_name="closure_effect_v1", evidence_dir=tmp_path)


def test_attack_fabricated_tripinfo_inconsistent_with_record_is_refused(tmp_path):
    """Worker finding 1, hardened: tripinfo and trajectory record must agree."""
    result = make_evidence(tmp_path, consistent=False)
    with pytest.raises(EvidenceError, match="not from the same run"):
        append_simulation_consequence(new_ledger("riverside"), simulation_result=result,
                                      extractor_name="closure_effect_v1", evidence_dir=tmp_path)


def test_attack_editing_tripinfo_after_sealing_is_refused(tmp_path):
    result = make_evidence(tmp_path)
    write_tripinfo(tmp_path / "ruled.tripinfo.xml", trips=[(9999, 9999, 9999, 9999)], walks=[(232, 200)])
    with pytest.raises(EvidenceError, match="does not match the sealed result"):
        append_simulation_consequence(new_ledger("riverside"), simulation_result=result,
                                      extractor_name="closure_effect_v1", evidence_dir=tmp_path)


def test_attack_simulation_entry_without_extractor_is_rejected(tmp_path):
    result = make_evidence(tmp_path)
    lg, _ = append_director_rule(new_ledger("riverside"), rule_manifest=make_rule())
    e = copy.deepcopy(lg["entries"][0])
    e["provenance"] = {"source": "simulation", "simulation_result_sha256": result["result_hash"],
                       "run_id": "ruled", "record_sha256": "c" * 64}
    bad = _resealed(lg, [e])
    with pytest.raises(LedgerError, match="extractor"):
        verify_ledger(bad)


def test_attack_unregistered_extractor_is_rejected(tmp_path):
    result = make_evidence(tmp_path)
    with pytest.raises(LedgerError, match="unknown extractor"):
        append_simulation_consequence(new_ledger("riverside"), simulation_result=result,
                                      extractor_name="my_helpful_llm_summary", evidence_dir=tmp_path)


def test_attack_unsealed_or_tampered_result_is_rejected(tmp_path):
    result = make_evidence(tmp_path)
    unsealed = dict(result); unsealed["result_hash"] = ""
    with pytest.raises(EvidenceError, match="not sealed"):
        append_simulation_consequence(new_ledger("riverside"), simulation_result=unsealed,
                                      extractor_name="closure_effect_v1", evidence_dir=tmp_path)
    tampered = dict(result); tampered["episode_number"] = 99
    with pytest.raises(EvidenceError, match="does not verify"):
        append_simulation_consequence(new_ledger("riverside"), simulation_result=tampered,
                                      extractor_name="closure_effect_v1", evidence_dir=tmp_path)


def test_attack_artifact_path_traversal_is_refused(tmp_path):
    with pytest.raises(EvidenceError, match="traversal"):
        seal_simulation_result({
            "schema_version": "simulation_result_v1", "run_id": "r", "episode_number": 1,
            "arm": "ruled", "seed": 1, "sumo_version": "1.27.1",
            "artifacts": {"baseline_tripinfo": {"file": "../../etc/passwd", "sha256": "a" * 64}},
            "result_hash": ""})


def test_attack_consequence_rule_id_must_reference_a_recorded_rule(tmp_path):
    """Worker finding 4: rule attribution is checked against the chain."""
    result = make_evidence(tmp_path)
    with pytest.raises(LedgerError, match="no director_rule entry with that rule_id"):
        append_simulation_consequence(new_ledger("riverside"), simulation_result=result,
                                      extractor_name="closure_effect_v1", evidence_dir=tmp_path,
                                      rule_id="a_rule_nobody_declared")


def test_attack_verify_rejects_double_reversal_and_unknown_target(tmp_path):
    """Worker finding 3: reversal semantics are re-checked on load."""
    lg, c1 = append_director_rule(new_ledger("riverside"), rule_manifest=make_rule())
    reopen = make_rule(episode=5, rule_id="reopen")
    lg, r1 = append_reversal(lg, rule_manifest=reopen, reverses_change_id=c1)
    dup = copy.deepcopy(lg["entries"][-1]); dup["change_id"] = "chg_" + "d" * 16
    with pytest.raises(LedgerError, match="already reversed"):
        verify_ledger(_resealed(lg, lg["entries"] + [dup]))
    ghost = copy.deepcopy(lg["entries"][-1]); ghost["change_id"] = "chg_" + "e" * 16
    ghost["payload"]["reverses_change_id"] = "chg_" + "0" * 16; ghost["reverses"] = "chg_" + "0" * 16
    with pytest.raises(LedgerError, match="unknown change"):
        verify_ledger(_resealed(lg, [lg["entries"][0], ghost]))


def test_attack_reversal_cannot_target_a_measurement(tmp_path):
    result = make_evidence(tmp_path)
    lg, c1 = append_director_rule(new_ledger("riverside"), rule_manifest=make_rule())
    lg, ids = append_simulation_consequence(lg, simulation_result=result,
                                            extractor_name="closure_effect_v1", evidence_dir=tmp_path,
                                            rule_id="close_the_bridge")
    with pytest.raises(LedgerError, match="cannot reverse a measured_effect"):
        append_reversal(lg, rule_manifest=make_rule(episode=5, rule_id="reopen"), reverses_change_id=ids[0])


def test_attack_reversal_with_simulation_provenance_is_rejected(tmp_path):
    result = make_evidence(tmp_path)
    lg, c1 = append_director_rule(new_ledger("riverside"), rule_manifest=make_rule())
    with pytest.raises(LedgerError, match="Director act"):
        _append_entry(lg, change_type="reversal", origin_episode=5, applied_at_sim_second=0.0,
                      payload={"kind": "reversal", "reverses_change_id": c1},
                      provenance=sim_prov(result), reverses=c1)


def test_attack_nan_in_tripinfo_creates_nothing(tmp_path):
    """Worker finding 5: non-finite values are refused, not propagated."""
    result = make_evidence(tmp_path)
    (tmp_path / "ruled.tripinfo.xml").write_text(
        '<?xml version="1.0"?>\n<tripinfos>\n'
        '  <tripinfo id="v0" duration="nan" routeLength="960" waitingTime="45" timeLoss="70"/>\n'
        '  <personinfo id="p0"><walk duration="200" routeLength="232"/></personinfo>\n</tripinfos>\n')
    # re-seal over the NaN file so the bytes match and only the NaN check can refuse it
    result = dict(result); arts = dict(result["artifacts"])
    arts["ruled_tripinfo"] = {"file": "ruled.tripinfo.xml", "sha256": artifact_sha256(tmp_path / "ruled.tripinfo.xml")}
    result["artifacts"] = arts; result["result_hash"] = ""
    result = seal_simulation_result(result)
    with pytest.raises(LedgerError, match="non-finite"):
        append_simulation_consequence(new_ledger("riverside"), simulation_result=result,
                                      extractor_name="closure_effect_v1", evidence_dir=tmp_path)


def test_attack_unsealed_or_edited_rule_manifest_is_rejected():
    rule = make_rule(); rule["manifest_hash"] = ""
    with pytest.raises(EvidenceError, match="not sealed"):
        append_director_rule(new_ledger("riverside"), rule_manifest=rule)
    rule = make_rule(); rule["change"]["close_edges"]["edge_ids"] = ["EVERY_ROAD"]
    with pytest.raises(EvidenceError, match="does not verify"):
        append_director_rule(new_ledger("riverside"), rule_manifest=rule)


def test_attack_two_changes_in_one_rule_and_pedestrian_barring_are_rejected():
    # Two changes in one rule are refused at SEAL time by the contract (oneOf),
    # before the ledger is ever reached.
    with pytest.raises(EvidenceError, match="ONE RULE contract"):
        seal_rule_manifest(rule_doc(1, "greedy",
            {"close_edges": {"edge_ids": ["A"], "disallow": ["passenger"]},
             "speed_limit": {"target_kind": "edge", "target_ids": ["B"], "mps": 5.0}}))
    with pytest.raises(LedgerError, match="footway"):
        append_director_rule(new_ledger("riverside"), rule_manifest=make_rule(disallow=("passenger", "pedestrian")))


# ==========================================================================
# The two doors, working
# ==========================================================================

def test_director_rule_payload_is_derived_from_the_sealed_manifest():
    rule = make_rule(edges=("B1C1", "C1B1"))
    lg, cid = append_director_rule(new_ledger("riverside"), rule_manifest=rule)
    verify_ledger(lg)
    e = lg["entries"][0]
    assert e["change_type"] == "edge_closure"
    assert e["payload"]["edge_ids"] == ["B1C1", "C1B1"]
    assert e["provenance"]["rule_manifest_sha256"] == rule["manifest_hash"]
    assert e["origin_episode"] == 1 and e["applied_at_sim_second"] == 150.0


@pytest.mark.parametrize("change,expected_type", [
    ({"close_lanes": {"lane_ids": ["B1C1_1"], "disallow": ["passenger"]}}, "lane_closure"),
    ({"access_permission": {"target_kind": "edge", "target_ids": ["B1C1"],
                            "allow": ["bus"], "disallow": ["passenger"]}}, "access_permission"),
    ({"speed_limit": {"target_kind": "edge", "target_ids": ["A1B1"], "mps": 8.33}}, "speed_limit"),
    ({"tls_program": {"tls_id": "B1", "program_id": "night"}}, "traffic_light_program"),
])
def test_every_director_change_kind_round_trips(change, expected_type):
    rule = seal_rule_manifest(rule_doc(2, "rule_r", change))
    lg, _ = append_director_rule(new_ledger("riverside"), rule_manifest=rule)
    verify_ledger(lg)
    assert lg["entries"][0]["change_type"] == expected_type


def test_simulation_consequence_is_computed_from_consistent_files(tmp_path):
    result = make_evidence(tmp_path)
    lg, ids = append_simulation_consequence(ruled_ledger(), simulation_result=result,
                                            extractor_name="closure_effect_v1", evidence_dir=tmp_path,
                                            rule_id=RULE)
    verify_ledger(lg)
    measured = [e for e in lg["entries"] if e["change_type"] == "measured_effect"]
    assert len(measured) == len(ids) == len(lg["entries"]) - 1     # entry 0 is the rule
    by = {e["payload"]["metric"]: e["payload"] for e in measured}
    assert by["trips_completed"]["delta"] == -1.0           # 2 baseline trips -> 1 ruled
    assert by["avg_time_loss_s"]["delta"] == 20.0
    assert "walks_completed" not in by and "avg_walk_length_m" not in by   # unchanged: not remembered
    for e in measured:
        assert e["provenance"]["extractor"] == "closure_effect_v1"
        assert e["provenance"]["record_sha256"] == result["artifacts"]["ruled_record_frames"]["sha256"]


def test_identical_evidence_yields_identical_ledger_hash(tmp_path):
    result = make_evidence(tmp_path)
    a, _ = append_simulation_consequence(ruled_ledger(), simulation_result=result,
                                         extractor_name="closure_effect_v1", evidence_dir=tmp_path,
                                         rule_id=RULE)
    b, _ = append_simulation_consequence(ruled_ledger(), simulation_result=result,
                                         extractor_name="closure_effect_v1", evidence_dir=tmp_path,
                                         rule_id=RULE)
    assert a["ledger_hash"] == b["ledger_hash"]


def test_consequence_attributed_to_a_recorded_rule_is_accepted(tmp_path):
    result = make_evidence(tmp_path)
    lg, _ = append_director_rule(new_ledger("riverside"), rule_manifest=make_rule())
    lg, ids = append_simulation_consequence(lg, simulation_result=result, extractor_name="closure_effect_v1",
                                            evidence_dir=tmp_path, rule_id="close_the_bridge")
    verify_ledger(lg)
    assert ids and all(e["rule_id"] == "close_the_bridge" for e in lg["entries"][1:])


def test_extractor_registry_is_a_closed_set():
    """The registry is CLOSED: an extractor arrives only by review, never by import.

    The set grew in Phase 3 from one entry to five, because the world gained
    three more rule classes and a pedestrian consequence. The guard is kept
    exactly as strict -- it still pins the whole set -- so a module that
    registers an extractor as a side effect of being imported fails here
    instead of quietly becoming able to write measured_effect entries.
    """
    assert set(CONSEQUENCE_EXTRACTORS) == {
        "closure_effect_v1",          # Phase 1
        "speed_limit_effect_v1",      # Phase 3
        "traffic_light_effect_v1",    # Phase 3
        "demand_flow_effect_v1",      # Phase 3
        "pedestrian_effect_v1",       # Phase 3
    }


# ==========================================================================
# Chain integrity and permanence
# ==========================================================================

def build_ledger():
    lg = new_ledger("riverside")
    lg, c1 = append_director_rule(lg, rule_manifest=make_rule())
    lg, c2 = append_director_rule(lg, rule_manifest=seal_rule_manifest(rule_doc(
        2, "slow_it", {"speed_limit": {"target_kind": "edge", "target_ids": ["A1B1"], "mps": 8.33}})))
    return lg, c1, c2


def test_chain_verifies():
    lg, _, _ = build_ledger()
    verify_ledger(lg)
    assert lg["entries"][0]["prev_hash"] == GENESIS_HASH
    assert lg["entries"][1]["prev_hash"] == lg["entries"][0]["entry_hash"]


@pytest.mark.parametrize("mutate,match", [
    (lambda b: b["entries"][0]["payload"].__setitem__("reason", "rewritten"), "modified after"),
    (lambda b: b["entries"].__delitem__(0), None),
    (lambda b: b["entries"].reverse(), "chain broken"),
    (lambda b: b.__setitem__("ledger_hash", "0" * 64), "ledger_hash"),
])
def test_tampering_is_detected(mutate, match):
    lg, _, _ = build_ledger()
    bad = copy.deepcopy(lg); mutate(bad)
    with pytest.raises(LedgerError, match=match) if match else pytest.raises(LedgerError):
        verify_ledger(bad)


def test_change_ids_are_stable_and_content_derived():
    payload = {"kind": "edge_closure", "edge_ids": ["B1C1"], "disallow": ["passenger"]}
    a = make_change_id(world_id="riverside", origin_episode=1, change_type="edge_closure", payload=payload)
    b = make_change_id(world_id="riverside", origin_episode=1, change_type="edge_closure", payload=payload)
    c = make_change_id(world_id="riverside", origin_episode=2, change_type="edge_closure", payload=payload)
    assert a == b and a != c


def test_no_delete_or_edit_function_exists():
    import ldyf.persistent_changes as pc
    for forbidden in ("delete_change", "remove_change", "edit_change", "drop_entry",
                      "clear_ledger", "update_change", "append_change"):
        assert not hasattr(pc, forbidden)


def test_reversal_keeps_the_original_visible():
    lg, c1, _ = build_ledger()
    before = len(lg["entries"])
    lg, _ = append_reversal(lg, rule_manifest=make_rule(episode=5, rule_id="reopen"), reverses_change_id=c1)
    verify_ledger(lg)
    assert len(lg["entries"]) == before + 1
    assert any(e["change_id"] == c1 for e in lg["entries"])
    assert not is_active(lg, c1)
    assert lg["entries"][0]["origin_episode"] == 1
    assert len(history_of(lg, c1)) == 2


def test_a_change_cannot_be_reversed_twice():
    lg, c1, _ = build_ledger()
    reopen = make_rule(episode=5, rule_id="reopen")
    lg, _ = append_reversal(lg, rule_manifest=reopen, reverses_change_id=c1)
    with pytest.raises(LedgerError, match="already reversed"):
        append_reversal(lg, rule_manifest=reopen, reverses_change_id=c1)


def test_active_changes_excludes_reversed_ones():
    lg, c1, c2 = build_ledger()
    assert {e["change_id"] for e in active_changes(lg)} == {c1, c2}
    lg, _ = append_reversal(lg, rule_manifest=make_rule(episode=5, rule_id="reopen"), reverses_change_id=c1)
    assert {e["change_id"] for e in active_changes(lg)} == {c2}


def test_append_does_not_mutate_the_input_ledger():
    lg = new_ledger("riverside"); snapshot = copy.deepcopy(lg)
    append_director_rule(lg, rule_manifest=make_rule())
    assert lg == snapshot


def test_lineage_accumulates_and_is_queryable():
    lg = new_ledger("riverside"); ids = []
    for ep in range(1, 6):
        lg, cid = append_director_rule(lg, rule_manifest=make_rule(episode=ep, rule_id=f"rule_{ep}", edges=(f"E{ep}",)))
        ids.append(cid)
    verify_ledger(lg)
    assert [e["origin_episode"] for e in lg["entries"]] == [1, 2, 3, 4, 5]
    assert [e["change_id"] for e in changes_from_episode(lg, 3)] == [ids[2]]
    assert {e["change_id"] for e in active_changes(lg)} == set(ids)


# ==========================================================================
# IO and schema
# ==========================================================================

def test_save_load_round_trip_and_tamper_refusal(tmp_path):
    lg, _, _ = build_ledger()
    p = tmp_path / "pc.json"
    h = save(lg, p)
    assert load(p)["ledger_hash"] == h
    doc = json.loads(p.read_text()); doc["entries"][0]["payload"]["reason"] = "tampered"
    p.write_text(json.dumps(doc))
    with pytest.raises(LedgerError):
        load(p)


def test_a_real_ledger_validates_against_the_json_schema(tmp_path):
    from jsonschema import Draft202012Validator

    from ldyf import persistent_changes as _pc
    # the schema for the version a NEW ledger declares, never a fixed file
    schema = json.loads((Path(__file__).parent.parent / "schemas"
                         / _pc.LEDGER_SCHEMAS[_pc.SCHEMA_VERSION]).read_text())
    lg, c1, _ = build_ledger()                       # rules in episodes 1 and 2
    # a consequence measured in episode 2 (episodes never run backwards)
    lg, _ = append_simulation_consequence(lg, simulation_result=make_evidence(tmp_path, episode=2),
                                          extractor_name="closure_effect_v1", evidence_dir=tmp_path,
                                          rule_id="close_the_bridge")
    lg, _ = append_reversal(lg, rule_manifest=make_rule(episode=5, rule_id="reopen"), reverses_change_id=c1)
    verify_ledger(lg)
    errors = sorted(Draft202012Validator(schema).iter_errors(lg), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors[:5])


# ==========================================================================
# The ONE RULE contract is load-bearing
# ==========================================================================

@pytest.mark.parametrize("strip", ["declared_utc", "prediction", "baseline_required", "statement"])
def test_a_rule_missing_contract_fields_cannot_be_sealed(strip):
    d = rule_doc(); del d[strip]
    with pytest.raises(EvidenceError, match="ONE RULE contract"):
        seal_rule_manifest(d)


def test_a_prediction_not_declared_before_the_run_cannot_be_sealed():
    d = rule_doc(); d["prediction"]["declared_before_run"] = False
    with pytest.raises(EvidenceError, match="ONE RULE contract"):
        seal_rule_manifest(d)


def test_a_rule_without_baseline_cannot_be_sealed():
    d = rule_doc(); d["baseline_required"] = False
    with pytest.raises(EvidenceError, match="ONE RULE contract"):
        seal_rule_manifest(d)


def test_a_sealed_rule_edited_to_break_the_contract_is_refused_by_the_ledger():
    r = make_rule()
    del r["prediction"]
    with pytest.raises(EvidenceError):
        append_director_rule(new_ledger("riverside"), rule_manifest=r)


def test_schema_and_ledger_agree_on_the_rule_vocabulary():
    """The schema is the single authority; the ledger must map every durable kind
    it declares, and refuse (clearly) the one that is not a world change."""
    schema = json.loads((Path(__file__).parent.parent / "schemas" / "rule_manifest_v2.schema.json").read_text())
    kinds = set(schema["properties"]["change"]["properties"])
    from ldyf.persistent_changes import _CHANGE_BLOCK_TO_TYPE

    assert set(_CHANGE_BLOCK_TO_TYPE) <= kinds, "ledger maps a kind the schema does not define"
    assert kinds - set(_CHANGE_BLOCK_TO_TYPE) == {"demand_scale"}


def test_demand_scale_is_a_valid_rule_but_not_a_world_change():
    r = seal_rule_manifest(rule_doc(3, "rush_hour", {"demand_scale": {"factor": 1.5}}))   # seals fine
    with pytest.raises(LedgerError, match="not a durable world change"):
        append_director_rule(new_ledger("riverside"), rule_manifest=r)


# ==========================================================================
# Second-attacker findings (DeepSeek worker `attack2`) -- each must now fail
# ==========================================================================

def test_attack_B2_well_formed_forgery_fails_evidence_aware_verify(tmp_path):
    """A fabricated entry with valid-looking hashes passes plain verify (structure
    only) but MUST fail once the ledger is traced back to sealed evidence."""
    result = make_evidence(tmp_path)
    lg, _ = append_director_rule(new_ledger("riverside"), rule_manifest=make_rule())
    forged = copy.deepcopy(lg["entries"][0])
    forged["change_id"] = "chg_" + "c" * 16
    forged["change_type"] = "measured_effect"
    forged["payload"] = {"kind": "measured_effect", "metric": "trips_completed",
                         "baseline_value": 0.0, "ruled_value": 100.0, "delta": 100.0,
                         "unit": "trips", "source_field": "tripinfo.trips_completed"}
    forged["provenance"] = {"source": "simulation", "simulation_result_sha256": "0" * 64,
                            "run_id": "ruled", "extractor": "closure_effect_v1",
                            "record_sha256": "0" * 64}
    bad = _resealed(lg, lg["entries"] + [forged])
    verify_ledger(bad)                                   # structure-only: passes, by design
    with pytest.raises(LedgerError, match="no sealed simulation_result.json with that hash"):
        verify_ledger(bad, evidence_dir=tmp_path)


def test_attack_B2_real_entry_with_swapped_payload_fails_evidence_aware_verify(tmp_path):
    """Real seal hashes, but the recorded numbers were edited to something the
    extractor does not derive."""
    result = make_evidence(tmp_path)
    (tmp_path / "simulation_result.json").write_text(json.dumps(result), encoding="utf-8")
    lg, ids = append_simulation_consequence(ruled_ledger(), simulation_result=result,
                                            extractor_name="closure_effect_v1", evidence_dir=tmp_path,
                                            rule_id=RULE)
    verify_ledger(lg, evidence_dir=tmp_path)             # genuine: passes
    tampered = copy.deepcopy(lg["entries"])
    assert tampered[1]["change_type"] == "measured_effect"   # entry 0 is the rule
    tampered[1]["payload"]["baseline_value"] = 0.0
    tampered[1]["payload"]["ruled_value"] = 5.0
    tampered[1]["payload"]["delta"] = 5.0
    bad = _resealed(lg, tampered)
    with pytest.raises(LedgerError, match="not one the extractor derives"):
        verify_ledger(bad, evidence_dir=tmp_path)


def test_attack_B3_fractional_or_negative_counts_are_rejected(tmp_path):
    result = make_evidence(tmp_path)
    for b, r in ((0.0, -3.0), (0.5, 2.5)):
        with pytest.raises(LedgerError, match="non-negative integer"):
            _append_entry(new_ledger("riverside"), change_type="measured_effect", origin_episode=1,
                          applied_at_sim_second=0.0,
                          payload={"kind": "measured_effect", "metric": "trips_completed",
                                   "baseline_value": b, "ruled_value": r, "delta": round(r - b, 4),
                                   "unit": "trips", "source_field": "tripinfo.trips_completed"},
                          provenance=sim_prov(result))
    with pytest.raises(LedgerError, match="rounded to 2 dp"):
        _append_entry(new_ledger("riverside"), change_type="measured_effect", origin_episode=1,
                      applied_at_sim_second=0.0,
                      payload={"kind": "measured_effect", "metric": "avg_time_loss_s",
                               "baseline_value": 1.23456, "ruled_value": 2.0, "delta": round(2.0 - 1.23456, 4),
                               "unit": "s", "source_field": "tripinfo.avg_time_loss_s"},
                      provenance=sim_prov(result))


def test_attack_B4_out_of_order_episodes_and_bad_sim_time_are_rejected():
    lg, _ = append_director_rule(new_ledger("riverside"), rule_manifest=make_rule(episode=5, rule_id="later"))
    with pytest.raises(LedgerError, match="must not decrease"):
        append_director_rule(lg, rule_manifest=make_rule(episode=1, rule_id="earlier"))
    d = rule_doc(); d["applies_at_sim_second"] = -5.0
    with pytest.raises(EvidenceError, match="ONE RULE contract"):     # refused at the seal already
        seal_rule_manifest(d)
    # and re-checked on verify for a hand-edited ledger
    bad = copy.deepcopy(lg); bad["entries"][0]["applied_at_sim_second"] = -1.0
    bad = _resealed(bad, bad["entries"])
    with pytest.raises(LedgerError, match="finite non-negative|less than the minimum"):
        verify_ledger(bad)


def test_attack_B6_nan_cannot_be_sealed_or_hashed(tmp_path):
    d = rule_doc(); d["applies_at_sim_second"] = float("nan")
    with pytest.raises(EvidenceError):
        seal_rule_manifest(d)
    lg, _ = append_director_rule(new_ledger("riverside"), rule_manifest=make_rule())
    bad = copy.deepcopy(lg); bad["entries"][0]["applied_at_sim_second"] = float("inf")
    with pytest.raises(LedgerError, match="non-finite"):
        compute_entry_hash(bad["entries"][0])


def test_real_ledger_passes_evidence_aware_verification_when_evidence_is_present():
    """The shipped ledger must trace back to its shipped sealed evidence."""
    import os
    base = Path(os.environ.get("LDYF_PROOF_DIR",
                r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY\PHASE_01\proof\sumo"))
    ev = base / "closure_v2"
    if not (ev / "persistent_changes.json").exists():
        pytest.skip("real closure evidence not present")
    lg = load(ev / "persistent_changes.json", evidence_dir=ev)
    assert sum(1 for e in lg["entries"] if e["change_type"] == "measured_effect") == 6
