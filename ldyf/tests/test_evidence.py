"""Proof that sealed evidence identities behave like identities."""

from __future__ import annotations

import json

import pytest

from ldyf.evidence import (
    artifact_sha256,
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
        "declared_utc": "2026-09-03T00:00:00Z",
        "statement": "Close the bridge.",
        "applies_at_sim_second": 150.0,
        "permanent": True,
        "baseline_required": True,
        "prediction": {"text": "Fewer trips complete.", "declared_before_run": True,
                       "metric": "trips_completed", "direction": "decrease"},
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
        "sumo_version": "1.27.1",
        "artifacts": {"ruled_tripinfo": {"file": f.name, "sha256": artifact_sha256(f)}},
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


def test_key_order_and_reformatting_do_not_change_identity(tmp_path):
    m = rule()
    assert compute_hash(m, "manifest_hash") == compute_hash(dict(reversed(list(m.items()))), "manifest_hash")
    sealed = seal_rule_manifest(m)
    p = tmp_path / "m.json"
    p.write_text(json.dumps(sealed, indent=8))
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
    with pytest.raises(EvidenceError, match="not sealed"):
        verify_rule_manifest(rule())


def test_wrong_schema_version_is_refused():
    with pytest.raises(EvidenceError, match="schema_version"):
        seal_rule_manifest(rule(schema_version="something_v9"))


def test_missing_required_field_is_refused():
    d = rule(); del d["change"]
    with pytest.raises(EvidenceError, match="ONE RULE contract"):
        seal_rule_manifest(d)


def test_result_requires_sumo_version(tmp_path):
    """The adversarial review noted the seal accepted results with no simulator identity."""
    d = result(tmp_path); del d["sumo_version"]
    with pytest.raises(EvidenceError, match="sumo_version"):
        seal_simulation_result(d)


def test_result_arm_must_be_baseline_or_ruled(tmp_path):
    with pytest.raises(EvidenceError, match="arm"):
        seal_simulation_result(result(tmp_path, arm="whatever_i_like"))


def test_result_with_no_artifacts_is_refused(tmp_path):
    with pytest.raises(EvidenceError, match="at least one"):
        seal_simulation_result(result(tmp_path, artifacts={}))


def test_artifact_without_a_valid_hash_is_refused(tmp_path):
    with pytest.raises(EvidenceError, match="64-hex sha256"):
        seal_simulation_result(result(tmp_path, artifacts={"x": {"file": "a.xml"}}))
    with pytest.raises(EvidenceError, match="64-hex sha256"):
        seal_simulation_result(result(tmp_path, artifacts={"x": {"file": "a.xml", "sha256": "nothex"}}))


@pytest.mark.parametrize("bad", ["../../secrets", "/abs/path", "C:\\abs\\path", "..\\up"])
def test_artifact_path_traversal_is_refused(tmp_path, bad):
    with pytest.raises(EvidenceError, match="traversal"):
        seal_simulation_result(result(tmp_path, artifacts={"x": {"file": bad, "sha256": "a" * 64}}))


def test_a_non_document_is_refused():
    with pytest.raises(EvidenceError):
        verify_rule_manifest("source: simulation")  # type: ignore[arg-type]


# --- artefacts on disk ----------------------------------------------------

def test_artifact_bytes_are_checked(tmp_path):
    r = seal_simulation_result(result(tmp_path))
    verify_artifact_on_disk(r, "ruled_tripinfo", tmp_path)
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



# --- artefact identity is the payload, not the timestamped bytes ------------

def test_xml_artifact_identity_ignores_the_provenance_header(tmp_path):
    body = "<tripinfos>\n  <tripinfo id=\"v\" duration=\"1\"/>\n</tripinfos>\n"
    a = tmp_path / "a.xml"; a.write_text('<?xml version="1.0"?>\n<!-- generated on 2026-01-01T00:00:00 by sumo -->\n' + body)
    b = tmp_path / "b.xml"; b.write_text('<?xml version="1.0"?>\n<!-- generated on 2099-12-31T23:59:59 by sumo -->\n' + body)
    assert sha256_file(a) != sha256_file(b)
    assert artifact_sha256(a) == artifact_sha256(b)
    c = tmp_path / "c.xml"; c.write_text('<?xml version="1.0"?>\n<!-- x -->\n' + body.replace('duration="1"', 'duration="2"'))
    assert artifact_sha256(a) != artifact_sha256(c)


def test_non_xml_artifact_identity_is_raw_bytes(tmp_path):
    p = tmp_path / "frames.bin"; p.write_bytes(b"\x00\x01\x02")
    assert artifact_sha256(p) == sha256_file(p)
