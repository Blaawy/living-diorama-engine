"""The independent review of the version-admission work, attack by attack.

A read-only reviewer was asked to break the explicit schema versions. It found
that the version STRING was admitted soundly and that almost everything hung
from it was thin: "no mixing" was two name checks, the declared JSON schema was
never applied, and a current-version ledger could not be verified through its
own module. Each test here is one of its attacks, run against the real
functions, and each one is refused now.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ldyf import evidence as ev
from ldyf import persistent_changes as pc
from ldyf.tests.test_consequence import make_evidence as make_p3_evidence
from ldyf.tests.test_persistent_changes import (_resealed, make_evidence, make_rule,
                                                rule_doc)

SEALED = Path(__file__).resolve().parent / "data" / "sealed_phase1"
V2, V3 = pc.LEGACY_SCHEMA_VERSION, pc.SCHEMA_VERSION


def sealed_ledger() -> dict:
    return json.loads((SEALED / "persistent_changes.json").read_text(encoding="utf-8"))


def rule(version: str, change: dict, rule_id: str = "the_rule", episode: int = 1) -> dict:
    doc = rule_doc(episode, rule_id, change)
    doc["schema_version"] = version
    return ev.seal_rule_manifest(doc)


SPEED = {"speed_limit": {"target_kind": "edge", "target_ids": ["B1B2"], "mps": 4.0}}
TLS = {"tls_program": {"tls_id": "B1", "program_id": "0"}}
DEMAND = {"demand_flow": {"flow_id": "f1", "from_edge": "A0A1", "to_edge": "B2C2",
                          "vehicles_per_hour": 120.0, "depart_begin": 0.0,
                          "depart_end": 300.0, "vtype": "DEFAULT_VEHTYPE"}}
CLOSE = {"close_edges": {"edge_ids": ["B1C1"], "disallow": ["passenger"]}}


# -- B1: a measurement cannot be filed under another rule class's extractor --

@pytest.mark.parametrize("change", [SPEED, TLS, DEMAND])
def test_the_closure_extractor_cannot_measure_another_rule_class(tmp_path, change):
    """`closure_effect_v1` summarises trip statistics and would summarise ANY run.

    That was the door: a speed-limit, traffic-light or demand measurement went
    into a ledger by being filed under the legacy extractor's name, and passed
    evidence-backed verification because the function really had run.
    """
    result = make_evidence(tmp_path)
    lg, _ = pc.append_director_rule(pc.new_ledger("riverside"),
                                    rule_manifest=rule("rule_manifest_v2", change))
    with pytest.raises(pc.LedgerError, match="cannot be filed under another rule class"):
        pc.append_simulation_consequence(
            lg, simulation_result=result, extractor_name="closure_effect_v1",
            evidence_dir=tmp_path, rule_id="the_rule")


def test_a_measurement_with_no_rule_is_refused(tmp_path):
    """The reviewer put a demand run's numbers into a ledger with no rule at all."""
    result = make_evidence(tmp_path)
    for version in (V2, V3):
        with pytest.raises(pc.LedgerError, match="must be attributed to a rule"):
            pc.append_simulation_consequence(
                pc.new_ledger("riverside", schema_version=version),
                simulation_result=result, extractor_name="closure_effect_v1",
                evidence_dir=tmp_path)


def test_relabelling_a_phase_3_ledger_as_legacy_closure_is_refused(tmp_path):
    """The forgery variant: v3 -> v2, every extractor renamed, hashes recomputed."""
    result = make_p3_evidence(tmp_path)
    lg, _ = pc.append_director_rule(pc.new_ledger("riverside"),
                                    rule_manifest=rule("rule_manifest_v2", SPEED))
    lg, _ = pc.append_simulation_consequence(
        lg, simulation_result=result, extractor_name="speed_limit_effect_v1",
        evidence_dir=tmp_path, rule_id="the_rule")
    forged = copy.deepcopy(lg)
    forged["schema_version"] = V2
    for e in forged["entries"]:
        if e["provenance"].get("extractor"):
            e["provenance"]["extractor"] = "closure_effect_v1"
    forged = _resealed(forged, forged["entries"])
    with pytest.raises(pc.LedgerError):
        pc.verify_ledger(forged)
    # and with the version left honest, the relabelled extractor alone is refused
    honest_version = copy.deepcopy(forged)
    honest_version["schema_version"] = V3
    with pytest.raises(pc.LedgerError, match="cannot be filed under another rule class"):
        pc.verify_ledger(honest_version)


def test_every_approved_extractor_has_a_rule_class():
    assert set(pc.EXTRACTOR_RULE_TYPES) == set(pc.APPROVED_EXTRACTORS)
    for name, allowed in pc.EXTRACTOR_RULE_TYPES.items():
        assert allowed is None or allowed <= set(pc.CHANGE_TYPES), name


def test_the_right_extractor_for_the_rule_is_still_accepted(tmp_path):
    result = make_evidence(tmp_path)
    lg, _ = pc.append_director_rule(pc.new_ledger("riverside"), rule_manifest=make_rule())
    lg, ids = pc.append_simulation_consequence(
        lg, simulation_result=result, extractor_name="closure_effect_v1",
        evidence_dir=tmp_path, rule_id="close_the_bridge")
    assert ids
    pc.verify_ledger(lg, evidence_dir=None)


# -- B2: the declared schema is applied, all of it ---------------------------

def _mutations():
    def no_entries(d):
        del d["entries"], d["world_id"]

    def top_level_extra(d):
        d["phase3_extras"] = {"demand_flow": {"flow_id": "f"}}

    def entry_level_extra(d):
        d["entries"][0]["demand_flow"] = {"flow_id": "f"}

    def provenance_extra(d):
        d["entries"][0]["provenance"]["phase3_extractor"] = "speed_limit_effect_v1"

    def demand_under_a_legacy_type(d):
        d["entries"][0]["payload"].update(DEMAND["demand_flow"])

    def world_id_not_a_string(d):
        d["world_id"] = 7

    def entries_not_a_list(d):
        d["entries"] = "x"

    def entry_not_an_object(d):
        d["entries"] = ["x"]

    return [no_entries, top_level_extra, entry_level_extra, provenance_extra,
            demand_under_a_legacy_type, world_id_not_a_string, entries_not_a_list,
            entry_not_an_object]


@pytest.mark.parametrize("mutate", _mutations(), ids=lambda f: f.__name__)
def test_a_legacy_ledger_that_breaks_its_own_schema_is_refused(mutate):
    """Each of these verified before: the schema was never applied."""
    doc = sealed_ledger()
    mutate(doc)
    if isinstance(doc.get("entries"), list) and all(isinstance(e, dict) for e in doc["entries"]):
        doc = _resealed(doc, doc["entries"])          # the attacker reseals
    with pytest.raises(pc.LedgerError):                # a typed refusal, not a crash
        pc.verify_ledger(doc)
    with pytest.raises(pc.LedgerError):
        pc.migrate_ledger(doc)


@pytest.mark.parametrize("field,value", [
    ("vehicles_per_hour", "lots"), ("vehicles_per_hour", -5), ("vehicles_per_hour", 0),
    ("depart_end", -1), ("flow_id", ""), ("from_edge", None), ("vtype", [1, 2]),
])
def test_a_malformed_demand_flow_payload_is_refused(field, value):
    lg, _ = pc.append_director_rule(pc.new_ledger("riverside"),
                                    rule_manifest=rule("rule_manifest_v2", DEMAND))
    bad = copy.deepcopy(lg)
    bad["entries"][0]["payload"][field] = value
    bad = _resealed(bad, bad["entries"])
    with pytest.raises(pc.LedgerError):
        pc.verify_ledger(bad)


def test_the_sealed_legacy_ledger_still_satisfies_the_schema_now_enforced():
    pc.verify_ledger(sealed_ledger())


# -- B3: the current version is readable through its own module -------------

def test_a_v3_ledger_verifies_without_anyone_importing_consequence(tmp_path):
    """Run in a fresh interpreter: test order hid this in-process."""
    result = make_p3_evidence(tmp_path)
    lg, _ = pc.append_director_rule(pc.new_ledger("riverside"),
                                    rule_manifest=rule("rule_manifest_v2", SPEED))
    lg, _ = pc.append_simulation_consequence(
        lg, simulation_result=result, extractor_name="speed_limit_effect_v1",
        evidence_dir=tmp_path, rule_id="the_rule")
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(lg), encoding="utf-8")
    code = (
        "import sys, json\n"
        "import ldyf.persistent_changes as pc\n"
        "assert 'ldyf.consequence' not in sys.modules\n"
        f"pc.verify_ledger(json.load(open(r'{path}')))\n"
        "print('VERIFIED')\n"
    )
    root = Path(__file__).resolve().parents[2]
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(root))
    assert "VERIFIED" in out.stdout, out.stderr[-600:]


# -- B4: what migration does and does not refuse ----------------------------

def test_migration_refuses_a_resealed_fabrication_when_given_the_evidence(tmp_path):
    """Unkeyed hashes cannot tell a resealed tamper from an honest ledger.

    Evidence can. `migrate_ledger` takes the evidence directory for that
    reason, and the claim is stated with the limit: without evidence it
    guarantees what `verify_ledger` without evidence guarantees.
    """
    result = make_evidence(tmp_path)
    (tmp_path / "simulation_result.json").write_text(json.dumps(result), encoding="utf-8")
    lg, _ = pc.append_director_rule(
        pc.new_ledger("riverside", schema_version=V2), rule_manifest=make_rule())
    lg, _ = pc.append_simulation_consequence(
        lg, simulation_result=result, extractor_name="closure_effect_v1",
        evidence_dir=tmp_path, rule_id="close_the_bridge")
    assert pc.migrate_ledger(lg, evidence_dir=tmp_path)["schema_version"] == V3

    fabricated = copy.deepcopy(lg)
    payload = fabricated["entries"][1]["payload"]
    payload["ruled_value"] = round(payload["baseline_value"] + 777.0, 2)
    payload["delta"] = 777.0
    if payload["metric"] in ("trips_completed", "walks_completed"):
        payload["ruled_value"] = float(int(payload["ruled_value"]))
        payload["delta"] = round(payload["ruled_value"] - payload["baseline_value"], 4)
    fabricated = _resealed(fabricated, fabricated["entries"])
    with pytest.raises(pc.LedgerError, match="not one the extractor derives"):
        pc.migrate_ledger(fabricated, evidence_dir=tmp_path)


def test_a_migrated_ledger_always_satisfies_the_current_schema():
    out = pc.migrate_ledger(sealed_ledger())
    pc._check_declared_schema(out, V3)


# -- B5: a str subclass is not a version ------------------------------------

class _Sneaky(str):
    def __ne__(self, other):
        return True


class _Chameleon(str):
    def __eq__(self, other):
        return True

    def __hash__(self):
        return hash(pc.LEGACY_SCHEMA_VERSION)


@pytest.mark.parametrize("version", [_Sneaky("persistent_changes_v2"),
                                     _Chameleon("garbage_v9"),
                                     _Chameleon("persistent_changes_v2")])
def test_a_str_subclass_is_not_admitted_as_a_ledger_version(version):
    lg = pc.new_ledger("riverside")
    lg["schema_version"] = version
    with pytest.raises(pc.LedgerError):
        pc.admit_ledger_version(lg)
    with pytest.raises(pc.LedgerError):
        pc.verify_ledger(lg)
    with pytest.raises(pc.LedgerError):
        pc.new_ledger("riverside", schema_version=version)


def test_a_str_subclass_is_not_admitted_as_a_rule_manifest_version():
    class Fake(str):
        def __eq__(self, other):
            return True

        def __hash__(self):
            return hash("rule_manifest_v2")

    doc = rule_doc(1, "the_rule", DEMAND)
    doc["schema_version"] = Fake("rule_manifest_v1")
    with pytest.raises(ev.EvidenceError):
        ev.seal_rule_manifest(doc)


# -- B6: refusals are typed -------------------------------------------------

@pytest.mark.parametrize("bad", [["persistent_changes_v3"], {"v": 3}, None, 3, b"x"])
def test_new_ledger_refuses_an_unhashable_or_wrong_typed_version_cleanly(bad):
    with pytest.raises(pc.LedgerError):
        pc.new_ledger("riverside", schema_version=bad)


@pytest.mark.parametrize("extractor", [["speed_limit_effect_v1"], {"a": 1}])
def test_an_unhashable_extractor_name_is_a_typed_refusal(extractor):
    doc = sealed_ledger()
    doc["entries"][1]["provenance"]["extractor"] = extractor
    doc = _resealed(doc, doc["entries"])
    with pytest.raises(pc.LedgerError):
        pc.verify_ledger(doc)


# -- B7: the query functions read a ledger too ------------------------------

@pytest.mark.parametrize("version", ["persistent_changes_v4", None])
def test_the_query_functions_refuse_an_unadmitted_ledger(version):
    doc = sealed_ledger()
    cid = doc["entries"][0]["change_id"]
    doc["schema_version"] = version
    for call in (lambda: pc.is_active(doc, cid), lambda: pc.active_changes(doc),
                 lambda: pc.changes_from_episode(doc, 1), lambda: pc.history_of(doc, cid)):
        with pytest.raises(pc.LedgerError):
            call()


def test_load_save_and_every_append_refuse_a_bad_version(tmp_path):
    result = make_evidence(tmp_path)
    for version in ("persistent_changes_v4", None):
        lg = pc.new_ledger("riverside")
        lg["schema_version"] = version
        with pytest.raises(pc.LedgerError):
            pc.save(lg, tmp_path / "x.json")
        with pytest.raises(pc.LedgerError):
            pc.append_director_rule(lg, rule_manifest=make_rule())
        with pytest.raises(pc.LedgerError):
            pc.append_reversal(lg, rule_manifest=make_rule(), reverses_change_id="chg_" + "0" * 16)
        with pytest.raises(pc.LedgerError):
            pc.append_simulation_consequence(
                lg, simulation_result=result, extractor_name="closure_effect_v1",
                evidence_dir=tmp_path, rule_id="close_the_bridge")
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(lg), encoding="utf-8")
        with pytest.raises(pc.LedgerError):
            pc.load(p)


# -- B8: a legacy ledger binds legacy manifests only ------------------------

def test_a_legacy_ledger_refuses_a_newer_rule_manifest_even_for_a_legacy_change():
    lg = pc.new_ledger("riverside", schema_version=V2)
    newer = rule("rule_manifest_v2", CLOSE)
    with pytest.raises(pc.LedgerError, match="binds only rule_manifest_v1"):
        pc.append_director_rule(lg, rule_manifest=newer)
    lg, cid = pc.append_director_rule(lg, rule_manifest=rule("rule_manifest_v1", CLOSE))
    with pytest.raises(pc.LedgerError, match="binds only rule_manifest_v1"):
        pc.append_reversal(lg, rule_manifest=rule("rule_manifest_v2", CLOSE, "reopen", 2),
                           reverses_change_id=cid)


def test_a_current_ledger_may_bind_a_legacy_rule_manifest():
    lg, _ = pc.append_director_rule(pc.new_ledger("riverside"),
                                    rule_manifest=rule("rule_manifest_v1", CLOSE))
    pc.verify_ledger(lg)


# -- B9: one document, one meaning ------------------------------------------

def test_a_ledger_file_with_a_duplicated_key_is_refused(tmp_path):
    """Last-key-wins and first-key-wins parsers would read two different ledgers."""
    lg, _ = pc.append_director_rule(pc.new_ledger("riverside"),
                                    rule_manifest=rule("rule_manifest_v2", DEMAND))
    text = json.dumps(lg)
    assert text.startswith('{"schema_version": "persistent_changes_v3"')
    doubled = '{"schema_version": "persistent_changes_v2", ' + text[1:]
    p = tmp_path / "doubled.json"
    p.write_text(doubled, encoding="utf-8")
    assert json.loads(doubled)["schema_version"] == V3      # what a naive reader sees
    with pytest.raises(pc.LedgerError, match="duplicate key"):
        pc.load(p)


def test_a_file_that_is_not_json_is_a_typed_refusal(tmp_path):
    p = tmp_path / "junk.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(pc.LedgerError):
        pc.load(p)


# -- B10: fields no hash covers are still checked ---------------------------

@pytest.mark.parametrize("world_id", [float("nan"), float("inf"), None, 3, ""])
def test_a_world_id_that_is_not_a_proper_string_is_refused(world_id):
    doc = sealed_ledger()
    doc["world_id"] = world_id
    with pytest.raises(pc.LedgerError):
        pc.verify_ledger(doc)


# -- the reviewer's UNPROVEN list --------------------------------------------

def test_jsonschema_is_a_hard_dependency_not_an_optional_one():
    """Four tests used importorskip; a check that can skip is not a check."""
    import jsonschema  # noqa: F401  -- a missing import fails this test loudly

    text = (Path(__file__).resolve().parent / "test_schema_compat.py").read_text(encoding="utf-8")
    assert "importorskip" not in text


def test_an_extractor_that_derives_nothing_still_meets_admission(tmp_path, monkeypatch):
    """Admission used to live inside the per-payload loop: no payloads, no check."""
    result = make_evidence(tmp_path)
    lg = pc.new_ledger("riverside")
    lg["schema_version"] = "persistent_changes_v9"
    with pytest.raises(pc.LedgerError, match="schema_version"):
        pc.append_simulation_consequence(
            lg, simulation_result=result, extractor_name="closure_effect_v1",
            evidence_dir=tmp_path, rule_id="close_the_bridge")
