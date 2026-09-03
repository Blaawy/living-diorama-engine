"""Proof that THE WORLD REMEMBERS cannot be forged, and that only sealed
evidence plus a deterministic extractor can create simulation truth.

The centrepiece is the ATTACK section: every way an LLM or a manual caller might
try to invent a "simulation consequence" must fail.
"""

from __future__ import annotations

import copy
import json

import pytest

from ldyf.evidence import (
    EvidenceError,
    seal_rule_manifest,
    seal_simulation_result,
    sha256_file,
)
from ldyf.persistent_changes import (
    CONSEQUENCE_EXTRACTORS,
    GENESIS_HASH,
    LedgerError,
    active_changes,
    append_director_rule,
    append_reversal,
    append_simulation_consequence,
    changes_from_episode,
    compute_entry_hash,
    history_of,
    is_active,
    load,
    make_change_id,
    new_ledger,
    save,
    verify_ledger,
)

TRIPINFO_BASE = (
    '<?xml version="1.0"?>\n<tripinfos>\n'
    '  <tripinfo id="v1" duration="100" routeLength="900" waitingTime="30" timeLoss="50"/>\n'
    '  <tripinfo id="v2" duration="120" routeLength="900" waitingTime="30" timeLoss="50"/>\n'
    '  <personinfo id="p1"><walk duration="200" routeLength="232"/></personinfo>\n'
    "</tripinfos>\n"
)
TRIPINFO_RULED = (
    '<?xml version="1.0"?>\n<tripinfos>\n'
    '  <tripinfo id="v1" duration="140" routeLength="960" waitingTime="45" timeLoss="70"/>\n'
    '  <personinfo id="p1"><walk duration="200" routeLength="232"/></personinfo>\n'
    "</tripinfos>\n"
)


def make_rule(episode=1, rule_id="close_the_bridge", edges=("B1C1",), disallow=("passenger",)):
    return seal_rule_manifest({
        "schema_version": "rule_manifest_v1",
        "rule_id": rule_id,
        "episode_number": episode,
        "statement": "Close the bridge.",
        "applies_at_sim_second": 150.0,
        "change": {"close_edges": {"edge_ids": list(edges), "disallow": list(disallow)}},
        "manifest_hash": "",
    })


def make_evidence(tmp_path, episode=1):
    b = tmp_path / "baseline.tripinfo.xml"
    r = tmp_path / "ruled.tripinfo.xml"
    b.write_text(TRIPINFO_BASE)
    r.write_text(TRIPINFO_RULED)
    result = seal_simulation_result({
        "schema_version": "simulation_result_v1",
        "run_id": "ruled",
        "episode_number": episode,
        "arm": "ruled",
        "seed": 20260903,
        "applied_at_sim_second": 150.0,
        "artifacts": {
            "baseline_tripinfo": {"file": b.name, "sha256": sha256_file(b)},
            "ruled_tripinfo": {"file": r.name, "sha256": sha256_file(r)},
        },
        "result_hash": "",
    })
    return result


# ==========================================================================
# ATTACKS — an LLM or manual caller must not be able to invent truth
# ==========================================================================

def test_there_is_no_public_api_that_accepts_provenance():
    """The structural claim: you cannot hand the ledger a provenance string."""
    import inspect

    import ldyf.persistent_changes as pc

    public_writers = [
        n for n in dir(pc)
        if not n.startswith("_") and n.startswith("append") and callable(getattr(pc, n))
    ]
    assert set(public_writers) == {
        "append_director_rule", "append_reversal", "append_simulation_consequence"
    }, public_writers
    for name in public_writers:
        params = inspect.signature(getattr(pc, name)).parameters
        assert "provenance" not in params, f"{name} accepts caller-supplied provenance"
        assert "payload" not in params, f"{name} accepts a caller-authored payload"


def test_attack_free_form_append_change_no_longer_exists():
    import ldyf.persistent_changes as pc

    assert not hasattr(pc, "append_change"), (
        "the free-form writer must be gone; it let a caller label anything 'simulation'"
    )


def test_attack_forging_a_simulation_entry_by_hand_is_rejected(tmp_path):
    """Craft an entry claiming simulation provenance and splice it in."""
    lg = new_ledger("riverside")
    lg, _ = append_director_rule(lg, rule_manifest=make_rule())

    forged = {
        "change_id": "chg_" + "a" * 16,
        "change_type": "infrastructure_added",
        "origin_episode": 2,
        "applied_at_sim_second": 0.0,
        "rule_id": None,
        "reverses": None,
        # the exact string the old design accepted
        "provenance": {"source": "simulation", "run_id": "ruled"},
        "payload": {"kind": "infrastructure", "infra_id": "detour_sign_01",
                    "infra_kind": "sign", "operation": "added"},
        "prev_hash": lg["entries"][-1]["entry_hash"],
    }
    forged["entry_hash"] = compute_entry_hash(forged)
    bad = copy.deepcopy(lg)
    bad["entries"].append(forged)
    from ldyf.persistent_changes import compute_ledger_hash
    bad["ledger_hash"] = compute_ledger_hash(bad["entries"])

    with pytest.raises(LedgerError, match="simulation_result"):
        verify_ledger(bad)


def test_attack_simulation_entry_without_an_extractor_is_rejected():
    lg = new_ledger("riverside")
    lg, _ = append_director_rule(lg, rule_manifest=make_rule())
    bad = copy.deepcopy(lg)
    e = copy.deepcopy(bad["entries"][0])
    e["provenance"] = {"source": "simulation", "simulation_result_sha256": "b" * 64}
    e["entry_hash"] = compute_entry_hash(e)
    bad["entries"] = [e]
    from ldyf.persistent_changes import compute_ledger_hash
    bad["ledger_hash"] = compute_ledger_hash(bad["entries"])
    with pytest.raises(LedgerError, match="extractor"):
        verify_ledger(bad)


def test_attack_unregistered_extractor_is_rejected(tmp_path):
    result = make_evidence(tmp_path)
    lg = new_ledger("riverside")
    with pytest.raises(LedgerError, match="unknown extractor"):
        append_simulation_consequence(
            lg, simulation_result=result,
            extractor_name="my_helpful_llm_summary", evidence_dir=tmp_path)


def test_attack_unsealed_simulation_result_is_rejected(tmp_path):
    result = make_evidence(tmp_path)
    result["result_hash"] = ""
    lg = new_ledger("riverside")
    with pytest.raises(EvidenceError, match="not sealed"):
        append_simulation_consequence(
            lg, simulation_result=result,
            extractor_name="closure_effect_v1", evidence_dir=tmp_path)


def test_attack_tampering_with_the_result_after_sealing_is_rejected(tmp_path):
    result = make_evidence(tmp_path)
    result["episode_number"] = 99          # rewrite history's episode
    lg = new_ledger("riverside")
    with pytest.raises(EvidenceError, match="does not verify"):
        append_simulation_consequence(
            lg, simulation_result=result,
            extractor_name="closure_effect_v1", evidence_dir=tmp_path)


def test_attack_editing_the_evidence_file_after_sealing_is_rejected(tmp_path):
    """The killer case: real sealed result, but the artefact was edited."""
    result = make_evidence(tmp_path)
    (tmp_path / "ruled.tripinfo.xml").write_text(
        '<?xml version="1.0"?>\n<tripinfos>\n'
        '  <tripinfo id="v1" duration="9999" routeLength="9999" waitingTime="9999" timeLoss="9999"/>\n'
        "</tripinfos>\n"
    )
    lg = new_ledger("riverside")
    with pytest.raises(EvidenceError, match="does not match the sealed result"):
        append_simulation_consequence(
            lg, simulation_result=result,
            extractor_name="closure_effect_v1", evidence_dir=tmp_path)


def test_attack_caller_cannot_choose_the_consequence(tmp_path):
    """The caller supplies evidence, never conclusions.

    There is no argument through which a desired consequence can be injected —
    the extractor computes every value from the sealed artefacts.
    """
    import inspect

    from ldyf.persistent_changes import append_simulation_consequence as f

    params = set(inspect.signature(f).parameters)
    assert params == {"ledger", "simulation_result", "extractor_name",
                      "evidence_dir", "rule_id"}, params

    result = make_evidence(tmp_path)
    lg, ids = append_simulation_consequence(
        new_ledger("riverside"), simulation_result=result,
        extractor_name="closure_effect_v1", evidence_dir=tmp_path)
    # every recorded value is what the files actually say
    for e in lg["entries"]:
        p = e["payload"]
        assert p["delta"] == round(p["ruled_value"] - p["baseline_value"], 4)


def test_attack_unsealed_rule_manifest_is_rejected():
    rule = make_rule()
    rule["manifest_hash"] = ""
    with pytest.raises(EvidenceError, match="not sealed"):
        append_director_rule(new_ledger("riverside"), rule_manifest=rule)


def test_attack_rule_manifest_edited_after_sealing_is_rejected():
    rule = make_rule()
    rule["change"]["close_edges"]["edge_ids"] = ["EVERY_ROAD"]
    with pytest.raises(EvidenceError, match="does not verify"):
        append_director_rule(new_ledger("riverside"), rule_manifest=rule)


def test_attack_rule_declaring_two_changes_is_rejected():
    rule = seal_rule_manifest({
        "schema_version": "rule_manifest_v1", "rule_id": "greedy", "episode_number": 1,
        "applies_at_sim_second": 0.0,
        "change": {"close_edges": {"edge_ids": ["A"], "disallow": ["passenger"]},
                   "speed_limit": {"target_kind": "edge", "target_ids": ["B"], "mps": 5.0}},
        "manifest_hash": "",
    })
    with pytest.raises(LedgerError, match="exactly ONE change"):
        append_director_rule(new_ledger("riverside"), rule_manifest=rule)


def test_attack_pedestrian_barring_rule_is_rejected():
    rule = make_rule(disallow=("passenger", "pedestrian"))
    with pytest.raises(LedgerError, match="footway"):
        append_director_rule(new_ledger("riverside"), rule_manifest=rule)


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
    assert e["provenance"]["source"] == "director_rule"
    assert e["provenance"]["rule_manifest_sha256"] == rule["manifest_hash"]
    assert e["origin_episode"] == 1
    assert e["applied_at_sim_second"] == 150.0


@pytest.mark.parametrize("change,expected_type", [
    ({"close_lanes": {"lane_ids": ["B1C1_1"], "disallow": ["passenger"]}}, "lane_closure"),
    ({"access_permission": {"target_kind": "edge", "target_ids": ["B1C1"],
                            "allow": ["bus"], "disallow": ["passenger"]}}, "access_permission"),
    ({"speed_limit": {"target_kind": "edge", "target_ids": ["A1B1"], "mps": 8.33}}, "speed_limit"),
    ({"tls_program": {"tls_id": "B1", "program_id": "night"}}, "traffic_light_program"),
])
def test_every_director_change_kind_round_trips(change, expected_type):
    rule = seal_rule_manifest({
        "schema_version": "rule_manifest_v1", "rule_id": "r", "episode_number": 2,
        "applies_at_sim_second": 0.0, "change": change, "manifest_hash": "",
    })
    lg, _ = append_director_rule(new_ledger("riverside"), rule_manifest=rule)
    verify_ledger(lg)
    assert lg["entries"][0]["change_type"] == expected_type


def test_simulation_consequence_is_computed_from_the_files(tmp_path):
    result = make_evidence(tmp_path)
    lg, ids = append_simulation_consequence(
        new_ledger("riverside"), simulation_result=result,
        extractor_name="closure_effect_v1", evidence_dir=tmp_path)
    verify_ledger(lg)
    assert ids, "the extractor should have derived at least one effect"
    by_metric = {e["payload"]["metric"]: e["payload"] for e in lg["entries"]}
    # baseline has 2 trips, ruled has 1 -> the extractor must find -1
    assert by_metric["trips_completed"]["delta"] == -1.0
    assert by_metric["avg_time_loss_s"]["baseline_value"] == 50.0
    assert by_metric["avg_time_loss_s"]["ruled_value"] == 70.0
    assert by_metric["avg_time_loss_s"]["delta"] == 20.0
    for e in lg["entries"]:
        assert e["provenance"]["extractor"] == "closure_effect_v1"
        assert e["provenance"]["simulation_result_sha256"] == result["result_hash"]


def test_a_metric_that_did_not_move_is_not_remembered(tmp_path):
    """The world does not remember a consequence that did not occur."""
    result = make_evidence(tmp_path)
    lg, _ = append_simulation_consequence(
        new_ledger("riverside"), simulation_result=result,
        extractor_name="closure_effect_v1", evidence_dir=tmp_path)
    metrics = {e["payload"]["metric"] for e in lg["entries"]}
    # walks are identical in both fixtures
    assert "walks_completed" not in metrics
    assert "avg_walk_length_m" not in metrics


def test_identical_evidence_yields_identical_entries(tmp_path):
    """The extractor is deterministic."""
    result = make_evidence(tmp_path)
    a, _ = append_simulation_consequence(new_ledger("riverside"), simulation_result=result,
                                         extractor_name="closure_effect_v1", evidence_dir=tmp_path)
    b, _ = append_simulation_consequence(new_ledger("riverside"), simulation_result=result,
                                         extractor_name="closure_effect_v1", evidence_dir=tmp_path)
    assert a["ledger_hash"] == b["ledger_hash"]


def test_extractor_registry_is_a_closed_set():
    assert set(CONSEQUENCE_EXTRACTORS) == {"closure_effect_v1"}


# ==========================================================================
# Chain integrity
# ==========================================================================

def build_ledger():
    lg = new_ledger("riverside")
    lg, c1 = append_director_rule(lg, rule_manifest=make_rule())
    lg, c2 = append_director_rule(lg, rule_manifest=seal_rule_manifest({
        "schema_version": "rule_manifest_v1", "rule_id": "slow_it", "episode_number": 2,
        "applies_at_sim_second": 0.0,
        "change": {"speed_limit": {"target_kind": "edge", "target_ids": ["A1B1"], "mps": 8.33}},
        "manifest_hash": "",
    }))
    return lg, c1, c2


def test_chain_verifies():
    lg, _, _ = build_ledger()
    verify_ledger(lg)
    assert lg["entries"][0]["prev_hash"] == GENESIS_HASH
    assert lg["entries"][1]["prev_hash"] == lg["entries"][0]["entry_hash"]


def test_editing_an_entry_is_detected():
    lg, _, _ = build_ledger()
    bad = copy.deepcopy(lg)
    bad["entries"][0]["payload"]["reason"] = "rewritten history"
    with pytest.raises(LedgerError, match="modified after it was written"):
        verify_ledger(bad)


def test_deleting_an_entry_is_detected():
    lg, _, _ = build_ledger()
    bad = copy.deepcopy(lg)
    del bad["entries"][0]
    with pytest.raises(LedgerError):
        verify_ledger(bad)


def test_reordering_entries_is_detected():
    lg, _, _ = build_ledger()
    bad = copy.deepcopy(lg)
    bad["entries"].reverse()
    with pytest.raises(LedgerError, match="chain broken"):
        verify_ledger(bad)


def test_ledger_hash_must_match_the_chain():
    lg, _, _ = build_ledger()
    bad = copy.deepcopy(lg)
    bad["ledger_hash"] = "0" * 64
    with pytest.raises(LedgerError, match="ledger_hash"):
        verify_ledger(bad)


def test_change_ids_are_stable_and_content_derived():
    payload = {"kind": "edge_closure", "edge_ids": ["B1C1"], "disallow": ["passenger"]}
    a = make_change_id(world_id="riverside", origin_episode=1,
                       change_type="edge_closure", payload=payload)
    b = make_change_id(world_id="riverside", origin_episode=1,
                       change_type="edge_closure", payload=payload)
    c = make_change_id(world_id="riverside", origin_episode=2,
                       change_type="edge_closure", payload=payload)
    assert a == b and a != c


# ==========================================================================
# Permanence
# ==========================================================================

def test_no_delete_function_exists():
    import ldyf.persistent_changes as pc

    names = [n for n in dir(pc) if not n.startswith("_")]
    for forbidden in ("delete_change", "remove_change", "edit_change",
                      "drop_entry", "clear_ledger", "update_change", "append_change"):
        assert forbidden not in names


def test_reversal_keeps_the_original_visible():
    lg, c1, _ = build_ledger()
    before = len(lg["entries"])
    reopen = seal_rule_manifest({
        "schema_version": "rule_manifest_v1", "rule_id": "reopen", "episode_number": 5,
        "applies_at_sim_second": 0.0, "statement": "Reopen the bridge.",
        "change": {"access_permission": {"target_kind": "edge", "target_ids": ["B1C1"],
                                         "allow": ["passenger"], "disallow": []}},
        "manifest_hash": "",
    })
    lg, _ = append_reversal(lg, rule_manifest=reopen, reverses_change_id=c1)
    verify_ledger(lg)
    assert len(lg["entries"]) == before + 1
    assert any(e["change_id"] == c1 for e in lg["entries"]), "the original must survive"
    assert not is_active(lg, c1)
    assert lg["entries"][0]["origin_episode"] == 1, "origin episode is never rewritten"
    assert len(history_of(lg, c1)) == 2


def test_a_change_cannot_be_reversed_twice():
    lg, c1, _ = build_ledger()
    reopen = seal_rule_manifest({
        "schema_version": "rule_manifest_v1", "rule_id": "reopen", "episode_number": 5,
        "applies_at_sim_second": 0.0,
        "change": {"speed_limit": {"target_kind": "edge", "target_ids": ["X"], "mps": 1.0}},
        "manifest_hash": "",
    })
    lg, _ = append_reversal(lg, rule_manifest=reopen, reverses_change_id=c1)
    with pytest.raises(LedgerError, match="already reversed"):
        append_reversal(lg, rule_manifest=reopen, reverses_change_id=c1)


def test_cannot_reverse_an_unknown_change():
    lg, _, _ = build_ledger()
    reopen = make_rule(episode=5, rule_id="reopen")
    with pytest.raises(LedgerError, match="unknown change"):
        append_reversal(lg, rule_manifest=reopen, reverses_change_id="chg_" + "0" * 16)


def test_active_changes_excludes_reversed_ones():
    lg, c1, c2 = build_ledger()
    assert {e["change_id"] for e in active_changes(lg)} == {c1, c2}
    reopen = make_rule(episode=5, rule_id="reopen")
    lg, _ = append_reversal(lg, rule_manifest=reopen, reverses_change_id=c1)
    assert {e["change_id"] for e in active_changes(lg)} == {c2}


def test_append_does_not_mutate_the_input_ledger():
    lg = new_ledger("riverside")
    snapshot = copy.deepcopy(lg)
    append_director_rule(lg, rule_manifest=make_rule())
    assert lg == snapshot, "history must never be half-written in place"


def test_episode_lineage_is_queryable():
    lg, c1, c2 = build_ledger()
    assert [e["change_id"] for e in changes_from_episode(lg, 1)] == [c1]
    assert [e["change_id"] for e in changes_from_episode(lg, 2)] == [c2]
    assert changes_from_episode(lg, 99) == []


def test_changes_accumulate_across_episodes():
    lg = new_ledger("riverside")
    ids = []
    for ep in range(1, 6):
        lg, cid = append_director_rule(lg, rule_manifest=make_rule(
            episode=ep, rule_id=f"r{ep}", edges=(f"E{ep}",)))
        ids.append(cid)
    verify_ledger(lg)
    assert [e["origin_episode"] for e in lg["entries"]] == [1, 2, 3, 4, 5]
    assert {e["change_id"] for e in active_changes(lg)} == set(ids)


# ==========================================================================
# IO and schema
# ==========================================================================

def test_save_load_round_trip(tmp_path):
    lg, _, _ = build_ledger()
    p = tmp_path / "pc.json"
    h = save(lg, p)
    assert load(p)["ledger_hash"] == h


def test_load_refuses_a_tampered_file(tmp_path):
    lg, _, _ = build_ledger()
    p = tmp_path / "pc.json"
    save(lg, p)
    doc = json.loads(p.read_text())
    doc["entries"][0]["payload"]["reason"] = "tampered"
    p.write_text(json.dumps(doc))
    with pytest.raises(LedgerError):
        load(p)


def test_a_real_ledger_validates_against_the_json_schema(tmp_path):
    """A schema no instance validates against is decorative."""
    from pathlib import Path

    from jsonschema import Draft202012Validator

    schema = json.loads(
        (Path(__file__).parent.parent / "schemas" / "persistent_changes.schema.json").read_text()
    )
    lg, c1, _ = build_ledger()
    lg, _ = append_simulation_consequence(
        lg, simulation_result=make_evidence(tmp_path),
        extractor_name="closure_effect_v1", evidence_dir=tmp_path)
    lg, _ = append_reversal(lg, rule_manifest=make_rule(episode=5, rule_id="reopen"),
                            reverses_change_id=c1)
    verify_ledger(lg)
    errors = sorted(Draft202012Validator(schema).iter_errors(lg), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors[:5])
