"""Proof that sealed evidence identities behave like identities."""

from __future__ import annotations

import json

import pytest

from ldyf.evidence import (
    EvidenceError,
    compute_hash,
    seal_rule_manifest,
    seal_simulation_result,
    sha256_file,
    verify_artifact_on_disk,
    verify_rule_manifest,
    verify_simulation_result,
)


def rule(**over):
    d = {
        "schema_version": "rule_manifest_v1",
        "rule_id": "close_the_bridge",
        "episode_number": 1,
        "applies_at_sim_second": 150.0,
        "change": {"close_edges": {"edge_ids": ["B1C1"], "disallow": ["passenger"]}},
        "manifest_hash": "",
    }
    d.update(over)
    return d


def result(tmp_path, **over):
    f = tmp_path / "a.xml"
    f.write_text("<tripinfos></tripinfos>")
    d = {
        "schema_version": "simulation_result_v1",
        "run_id": "ruled",
        "episode_number": 1,
        "arm": "ruled",
        "seed": 20260903,
        "artifacts": {"ruled_tripinfo": {"file": f.name, "sha256": sha256_file(f)}},
        "result_hash": "",
    }
    d.update(over)
    return d


# --- sealing --------------------------------------------------------------

def test_seal_then_verify_rule_manifest():
    m = seal_rule_manifest(rule())
    verify_rule_manifest(m)
    assert len(m["manifest_hash"]) == 64


def test_seal_then_verify_simulation_result(tmp_path):
    r = seal_simulation_result(result(tmp_path))
    verify_simulation_result(r)
    assert len(r["result_hash"]) == 64


def test_hash_ignores_its_own_field():
    m = rule()
    a = compute_hash(m, "manifest_hash")
    m["manifest_hash"] = "deadbeef"
    assert compute_hash(m, "manifest_hash") == a


def test_key_order_does_not_change_identity():
    m = rule()
    assert compute_hash(m, "manifest_hash") == compute_hash(
        dict(reversed(list(m.items()))), "manifest_hash")


def test_reformatting_does_not_change_identity(tmp_path):
    m = seal_rule_manifest(rule())
    p = tmp_path / "m.json"
    p.write_text(json.dumps(m, indent=8))
    verify_rule_manifest(json.loads(p.read_text()))


@pytest.mark.parametrize("mutate", [
    lambda d: d.__setitem__("rule_id", "something_else"),
    lambda d: d.__setitem__("episode_number", 99),
    lambda d: d["change"]["close_edges"].__setitem__("edge_ids", ["EVERY_ROAD"]),
    lambda d: d.__setitem__("applies_at_sim_second", 0.0),
])
def test_any_content_change_breaks_the_seal(mutate):
    m = seal_rule_manifest(rule())
    mutate(m)
    with pytest.raises(EvidenceError, match="does not verify"):
        verify_rule_manifest(m)


# --- refusals -------------------------------------------------------------

def test_unsealed_document_is_refused():
    m = rule()
    with pytest.raises(EvidenceError, match="not sealed"):
        verify_rule_manifest(m)


def test_wrong_schema_version_is_refused():
    with pytest.raises(EvidenceError, match="schema_version"):
        seal_rule_manifest(rule(schema_version="something_v9"))


def test_missing_required_field_is_refused():
    d = rule()
    del d["change"]
    with pytest.raises(EvidenceError, match="change"):
        seal_rule_manifest(d)


def test_result_with_no_artifacts_is_refused(tmp_path):
    r = seal_simulation_result(result(tmp_path, artifacts={"x": {"sha256": "a" * 64}}))
    r2 = dict(r)
    r2["artifacts"] = {}
    with pytest.raises(EvidenceError):
        verify_simulation_result(r2)


def test_artifact_without_a_hash_is_refused(tmp_path):
    r = seal_simulation_result(result(tmp_path, artifacts={"x": {"file": "a.xml"}}))
    with pytest.raises(EvidenceError, match="sha256"):
        verify_simulation_result(r)


def test_a_non_document_is_refused():
    with pytest.raises(EvidenceError):
        verify_rule_manifest("source: simulation")  # type: ignore[arg-type]


# --- artefacts on disk ----------------------------------------------------

def test_artifact_bytes_are_checked(tmp_path):
    r = seal_simulation_result(result(tmp_path))
    verify_artifact_on_disk(r, "ruled_tripinfo", tmp_path)   # passes

    (tmp_path / "a.xml").write_text("<tripinfos>EDITED</tripinfos>")
    with pytest.raises(EvidenceError, match="does not match the sealed result"):
        verify_artifact_on_disk(r, "ruled_tripinfo", tmp_path)


def test_missing_artifact_is_refused(tmp_path):
    r = seal_simulation_result(result(tmp_path))
    (tmp_path / "a.xml").unlink()
    with pytest.raises(EvidenceError, match="not found on disk"):
        verify_artifact_on_disk(r, "ruled_tripinfo", tmp_path)


def test_unknown_artifact_name_is_refused(tmp_path):
    r = seal_simulation_result(result(tmp_path))
    with pytest.raises(EvidenceError, match="names no artefact"):
        verify_artifact_on_disk(r, "not_a_thing", tmp_path)
