"""Proof that THE WORLD REMEMBERS generalises correctly and cannot be forged."""

from __future__ import annotations

import copy
import json

import pytest

from ldyf.persistent_changes import (
    GENESIS_HASH,
    LedgerError,
    active_changes,
    append_change,
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

SIM_PROV = {"source": "simulation", "run_id": "run_0001", "record_sha256": "a" * 64}
RULE_PROV = {"source": "director_rule", "run_id": "run_0001"}


def closure_payload(edges=("B1C1",), disallow=("passenger",)):
    return {"kind": "edge_closure", "edge_ids": list(edges),
            "disallow": list(disallow), "reason": "bridge closed"}


def build_ledger():
    lg = new_ledger("riverside")
    lg, c1 = append_change(lg, change_type="edge_closure", origin_episode=1,
                           applied_at_sim_second=150.0, payload=closure_payload(),
                           provenance=RULE_PROV, rule_id="close_the_bridge")
    lg, c2 = append_change(lg, change_type="speed_limit", origin_episode=2,
                           applied_at_sim_second=0.0,
                           payload={"kind": "speed_limit", "target_kind": "edge",
                                    "target_ids": ["A1B1"], "mps": 8.33,
                                    "previous_mps": 13.89},
                           provenance=RULE_PROV, rule_id="slow_the_high_street")
    return lg, c1, c2


# --- every required change type round-trips -------------------------------

@pytest.mark.parametrize(
    "change_type,payload",
    [
        ("edge_closure", {"kind": "edge_closure", "edge_ids": ["B1C1"], "disallow": ["passenger"]}),
        ("lane_closure", {"kind": "lane_closure", "lane_ids": ["B1C1_1"], "disallow": ["passenger"]}),
        ("access_permission", {"kind": "access_permission", "target_kind": "edge",
                               "target_ids": ["B1C1"], "allow": ["bus"], "disallow": ["passenger"]}),
        ("speed_limit", {"kind": "speed_limit", "target_kind": "lane",
                         "target_ids": ["A1B1_1"], "mps": 8.33}),
        ("traffic_light_program", {"kind": "traffic_light_program", "tls_id": "B1",
                                   "program_id": "night", "previous_program_id": "0"}),
        ("infrastructure_added", {"kind": "infrastructure", "infra_id": "bridge_01",
                                  "infra_kind": "bridge", "operation": "added"}),
        ("infrastructure_removed", {"kind": "infrastructure", "infra_id": "kiosk_02",
                                    "infra_kind": "kiosk", "operation": "removed"}),
    ],
)
def test_each_change_type_is_recordable(change_type, payload):
    lg = new_ledger("riverside")
    lg, cid = append_change(lg, change_type=change_type, origin_episode=3,
                            applied_at_sim_second=10.0, payload=payload,
                            provenance=SIM_PROV)
    verify_ledger(lg)
    assert lg["entries"][0]["change_type"] == change_type
    assert cid.startswith("chg_") and len(cid) == 20
    assert is_active(lg, cid)


# --- identity -------------------------------------------------------------

def test_change_ids_are_stable_and_content_derived():
    a = make_change_id(world_id="riverside", origin_episode=1,
                       change_type="edge_closure", payload=closure_payload())
    b = make_change_id(world_id="riverside", origin_episode=1,
                       change_type="edge_closure", payload=closure_payload())
    assert a == b, "the same change must always get the same id"
    c = make_change_id(world_id="riverside", origin_episode=2,
                       change_type="edge_closure", payload=closure_payload())
    assert a != c, "a different episode must get a different id"


def test_duplicate_changes_get_distinct_ids():
    lg = new_ledger("riverside")
    lg, c1 = append_change(lg, change_type="edge_closure", origin_episode=1,
                           applied_at_sim_second=1.0, payload=closure_payload(),
                           provenance=RULE_PROV)
    lg, c2 = append_change(lg, change_type="edge_closure", origin_episode=1,
                           applied_at_sim_second=2.0, payload=closure_payload(),
                           provenance=RULE_PROV)
    assert c1 != c2
    verify_ledger(lg)


# --- the chain cannot be forged -------------------------------------------

def test_chain_verifies():
    lg, _, _ = build_ledger()
    verify_ledger(lg)
    assert lg["entries"][0]["prev_hash"] == GENESIS_HASH
    assert lg["entries"][1]["prev_hash"] == lg["entries"][0]["entry_hash"]


def test_editing_an_entry_is_detected():
    lg, c1, _ = build_ledger()
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


def test_appending_a_forged_entry_is_detected():
    lg, _, _ = build_ledger()
    bad = copy.deepcopy(lg)
    forged = copy.deepcopy(bad["entries"][-1])
    forged["change_id"] = "chg_" + "f" * 16
    forged["payload"] = closure_payload(edges=("D3D2",))
    forged["entry_hash"] = compute_entry_hash(forged)   # attacker rehashes correctly
    bad["entries"].append(forged)
    with pytest.raises(LedgerError, match="chain broken"):
        verify_ledger(bad)


def test_ledger_hash_must_match_the_chain():
    lg, _, _ = build_ledger()
    bad = copy.deepcopy(lg)
    bad["ledger_hash"] = "0" * 64
    with pytest.raises(LedgerError, match="ledger_hash"):
        verify_ledger(bad)


# --- permanence: the scar outlives the rule -------------------------------

def test_no_delete_function_exists():
    """DNA-03 enforced structurally."""
    import ldyf.persistent_changes as pc

    names = [n for n in dir(pc) if not n.startswith("_")]
    for forbidden in ("delete_change", "remove_change", "edit_change",
                      "drop_entry", "clear_ledger", "update_change"):
        assert forbidden not in names


def test_reversal_keeps_the_original_visible():
    lg, c1, _ = build_ledger()
    before = len(lg["entries"])
    lg, rev = append_change(lg, change_type="reversal", origin_episode=5,
                            applied_at_sim_second=0.0,
                            payload={"kind": "reversal", "reverses_change_id": c1,
                                     "reason": "the bridge reopened"},
                            provenance=RULE_PROV, rule_id="reopen_the_bridge")
    verify_ledger(lg)
    assert len(lg["entries"]) == before + 1, "a reversal must ADD an entry"
    assert any(e["change_id"] == c1 for e in lg["entries"]), "the original must survive"
    assert not is_active(lg, c1)
    assert lg["entries"][0]["origin_episode"] == 1, "origin episode is never rewritten"
    assert len(history_of(lg, c1)) == 2


def test_a_change_cannot_be_reversed_twice():
    lg, c1, _ = build_ledger()
    lg, _ = append_change(lg, change_type="reversal", origin_episode=5,
                          applied_at_sim_second=0.0,
                          payload={"kind": "reversal", "reverses_change_id": c1},
                          provenance=RULE_PROV)
    with pytest.raises(LedgerError, match="already reversed"):
        append_change(lg, change_type="reversal", origin_episode=6,
                      applied_at_sim_second=0.0,
                      payload={"kind": "reversal", "reverses_change_id": c1},
                      provenance=RULE_PROV)


def test_cannot_reverse_an_unknown_change():
    lg, _, _ = build_ledger()
    with pytest.raises(LedgerError, match="unknown change"):
        append_change(lg, change_type="reversal", origin_episode=5,
                      applied_at_sim_second=0.0,
                      payload={"kind": "reversal", "reverses_change_id": "chg_" + "0" * 16},
                      provenance=RULE_PROV)


def test_active_changes_excludes_reversed_ones():
    lg, c1, c2 = build_ledger()
    assert {e["change_id"] for e in active_changes(lg)} == {c1, c2}
    lg, _ = append_change(lg, change_type="reversal", origin_episode=5,
                          applied_at_sim_second=0.0,
                          payload={"kind": "reversal", "reverses_change_id": c1},
                          provenance=RULE_PROV)
    assert {e["change_id"] for e in active_changes(lg)} == {c2}


def test_append_does_not_mutate_the_input_ledger():
    lg = new_ledger("riverside")
    snapshot = copy.deepcopy(lg)
    append_change(lg, change_type="edge_closure", origin_episode=1,
                  applied_at_sim_second=1.0, payload=closure_payload(),
                  provenance=RULE_PROV)
    assert lg == snapshot, "history must never be half-written in place"


# --- provenance is mandatory ----------------------------------------------

def test_an_unattributed_change_is_refused():
    lg = new_ledger("riverside")
    with pytest.raises(LedgerError, match="provenance.source"):
        append_change(lg, change_type="edge_closure", origin_episode=1,
                      applied_at_sim_second=1.0, payload=closure_payload(),
                      provenance={"source": "llm_summary", "run_id": "x"})


def test_provenance_requires_a_run_id():
    lg = new_ledger("riverside")
    with pytest.raises(LedgerError, match="run_id"):
        append_change(lg, change_type="edge_closure", origin_episode=1,
                      applied_at_sim_second=1.0, payload=closure_payload(),
                      provenance={"source": "simulation"})


# --- payload validation ---------------------------------------------------

def test_payload_kind_must_match_change_type():
    lg = new_ledger("riverside")
    with pytest.raises(LedgerError, match="requires payload kind"):
        append_change(lg, change_type="speed_limit", origin_episode=1,
                      applied_at_sim_second=1.0, payload=closure_payload(),
                      provenance=RULE_PROV)


def test_missing_payload_field_is_refused():
    lg = new_ledger("riverside")
    with pytest.raises(LedgerError, match="missing required field"):
        append_change(lg, change_type="edge_closure", origin_episode=1,
                      applied_at_sim_second=1.0,
                      payload={"kind": "edge_closure", "edge_ids": ["B1C1"]},
                      provenance=RULE_PROV)


def test_a_change_barring_pedestrians_is_refused():
    """RISK-1 cannot be re-entered through the ledger either."""
    lg = new_ledger("riverside")
    with pytest.raises(LedgerError, match="footway"):
        append_change(lg, change_type="edge_closure", origin_episode=1,
                      applied_at_sim_second=1.0,
                      payload=closure_payload(disallow=("passenger", "pedestrian")),
                      provenance=RULE_PROV)


def test_infrastructure_operation_must_match_type():
    lg = new_ledger("riverside")
    with pytest.raises(LedgerError, match="operation 'added'"):
        append_change(lg, change_type="infrastructure_added", origin_episode=1,
                      applied_at_sim_second=1.0,
                      payload={"kind": "infrastructure", "infra_id": "b1",
                               "infra_kind": "bridge", "operation": "removed"},
                      provenance=SIM_PROV)


def test_non_positive_speed_limit_refused():
    lg = new_ledger("riverside")
    with pytest.raises(LedgerError, match="positive mps"):
        append_change(lg, change_type="speed_limit", origin_episode=1,
                      applied_at_sim_second=1.0,
                      payload={"kind": "speed_limit", "target_kind": "edge",
                               "target_ids": ["A1B1"], "mps": 0},
                      provenance=RULE_PROV)


def test_unknown_change_type_refused():
    lg = new_ledger("riverside")
    with pytest.raises(LedgerError, match="unknown change_type"):
        append_change(lg, change_type="teleport_the_city", origin_episode=1,
                      applied_at_sim_second=1.0, payload={"kind": "x"},
                      provenance=RULE_PROV)


# --- lineage --------------------------------------------------------------

def test_episode_lineage_is_queryable():
    lg, c1, c2 = build_ledger()
    assert [e["change_id"] for e in changes_from_episode(lg, 1)] == [c1]
    assert [e["change_id"] for e in changes_from_episode(lg, 2)] == [c2]
    assert changes_from_episode(lg, 99) == []


def test_changes_accumulate_across_episodes():
    """Episode N+1 inherits everything episode N remembered."""
    lg = new_ledger("riverside")
    ids = []
    for ep in range(1, 6):
        lg, cid = append_change(lg, change_type="edge_closure", origin_episode=ep,
                                applied_at_sim_second=float(ep),
                                payload=closure_payload(edges=(f"E{ep}",)),
                                provenance=RULE_PROV)
        ids.append(cid)
    verify_ledger(lg)
    assert len(lg["entries"]) == 5
    assert [e["origin_episode"] for e in lg["entries"]] == [1, 2, 3, 4, 5]
    assert {e["change_id"] for e in active_changes(lg)} == set(ids)


# --- io -------------------------------------------------------------------

def test_save_load_round_trip(tmp_path):
    lg, _, _ = build_ledger()
    p = tmp_path / "pc.json"
    h = save(lg, p)
    back = load(p)
    assert back["ledger_hash"] == h
    assert back == lg


def test_load_refuses_a_tampered_file(tmp_path):
    lg, _, _ = build_ledger()
    p = tmp_path / "pc.json"
    save(lg, p)
    doc = json.loads(p.read_text())
    doc["entries"][0]["payload"]["reason"] = "tampered"
    p.write_text(json.dumps(doc))
    with pytest.raises(LedgerError):
        load(p)


# --- the instance must satisfy the published JSON Schema ------------------

def test_a_real_ledger_validates_against_the_json_schema():
    """A schema no instance validates against is decorative."""
    from pathlib import Path

    from jsonschema import Draft202012Validator

    schema = json.loads(
        (Path(__file__).parent.parent / "schemas" / "persistent_changes.schema.json").read_text()
    )
    lg = new_ledger("riverside")
    for ct, payload in [
        ("edge_closure", {"kind": "edge_closure", "edge_ids": ["B1C1"], "disallow": ["passenger"]}),
        ("lane_closure", {"kind": "lane_closure", "lane_ids": ["B1C1_1"], "disallow": ["passenger"]}),
        ("access_permission", {"kind": "access_permission", "target_kind": "edge",
                               "target_ids": ["B1C1"], "allow": ["bus"], "disallow": ["passenger"]}),
        ("speed_limit", {"kind": "speed_limit", "target_kind": "edge",
                         "target_ids": ["A1B1"], "mps": 8.33, "previous_mps": 13.89}),
        ("traffic_light_program", {"kind": "traffic_light_program", "tls_id": "B1",
                                   "program_id": "night", "previous_program_id": "0"}),
        ("infrastructure_added", {"kind": "infrastructure", "infra_id": "bridge_01",
                                  "infra_kind": "bridge", "operation": "added",
                                  "location": {"x_m": 1.0, "y_m": 2.0}}),
        ("infrastructure_removed", {"kind": "infrastructure", "infra_id": "kiosk_02",
                                    "infra_kind": "kiosk", "operation": "removed"}),
    ]:
        lg, _ = append_change(lg, change_type=ct, origin_episode=1,
                              applied_at_sim_second=1.0, payload=payload,
                              provenance=SIM_PROV, rule_id="r1")
    first = lg["entries"][0]["change_id"]
    lg, _ = append_change(lg, change_type="reversal", origin_episode=2,
                          applied_at_sim_second=0.0,
                          payload={"kind": "reversal", "reverses_change_id": first},
                          provenance=RULE_PROV)
    verify_ledger(lg)
    errors = sorted(Draft202012Validator(schema).iter_errors(lg), key=lambda e: e.path)
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors[:5])
    assert len(lg["entries"]) == 8
