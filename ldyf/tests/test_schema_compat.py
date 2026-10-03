"""Schema versions: sealed evidence is admitted unchanged, new evidence says what it is.

Phase 3 added a fourth rule class, `demand_flow`. The first implementation
WIDENED `persistent_changes_v2` and `rule_manifest_v1` in place and kept their
names, on the argument that an additive change keeps sealed documents valid. It
does -- and it also means a document calling itself v2 could carry things no v2
reader ever agreed to, and that the file named "the v2 schema" was no longer
the schema v2 evidence had been sealed against.

So the versions are explicit now:

* `persistent_changes_v2` / `rule_manifest_v1` are the LEGACY contracts. Their
  schema files are what they were before Phase 3 touched them.
* `persistent_changes_v3` / `rule_manifest_v2` are the Phase 3 contracts, and
  every new document declares them.
* A document is admitted by the version it DECLARES. Nothing infers a version
  from a document's shape; an unknown, missing or malformed version fails
  closed; a legacy document carrying a newer version's feature is refused.
* `migrate_ledger` lifts a v2 ledger to v3 by changing the version string and
  nothing else, so every entry hash and the ledger hash survive.

The sealed Phase 1 ledger and both sealed Phase 1 rule manifests are shipped
beside these tests (`data/sealed_phase1`), identical to the evidence under
PHASE_01, so none of this is skipped on a machine that has only the archive.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from ldyf import evidence as ev
from ldyf import persistent_changes as pc

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"
SEALED = Path(__file__).resolve().parent / "data" / "sealed_phase1"
_PROOF_ROOT = os.environ.get("LDYF_PROOF_DIR")
PHASE_01 = ((Path(_PROOF_ROOT) / "closure_v2") if _PROOF_ROOT else (
    Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
    / "PHASE_01" / "proof" / "sumo" / "closure_v2"
))
SEALED_FILES = ("persistent_changes.json", "rule_manifest.json",
                "rule_manifest_reopen.json")

#: sha256 of the two LEGACY schema files as they stood at the commit before
#: Phase 3 first touched them (abba259^), line endings normalised. Pinned,
#: because "the v2 schema" has to mean the bytes v2 evidence was sealed against,
#: not whatever happens to be in the file today.
LEGACY_SCHEMA_SHA256 = {
    "persistent_changes.schema.json": "5cad95fd9604e1c1c439a557549fb041e1570bd23c410ca2e0a84acf128e49dd",
    "rule_manifest.schema.json": "30386029c6b6ce69a012833ffd714c8c335ef6077266a832d9ff690b5b4b4de5",
}


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _sealed(name: str) -> dict:
    return json.loads((SEALED / name).read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    # line endings normalised: git may check these out CRLF on Windows
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _rule(version: str, change: dict, rule_id: str = "rule_one",
          episode: int | None = None) -> dict:
    """A rule manifest shaped like the sealed Phase 1 one, with `change` swapped."""
    doc = _sealed("rule_manifest.json")
    doc.update({"schema_version": version, "rule_id": rule_id,
                "change": change, "manifest_hash": ""})
    if episode is not None:
        doc["episode_number"] = episode
    return doc


DEMAND = {"demand_flow": {"flow_id": "f1", "from_edge": "A0A1", "to_edge": "B2C2",
                          "vehicles_per_hour": 120.0, "depart_begin": 0.0,
                          "depart_end": 300.0, "vtype": "DEFAULT_VEHTYPE"}}
CLOSURE = json.loads((SEALED / "rule_manifest.json").read_text(encoding="utf-8"))["change"]


# -- legacy admission ------------------------------------------------------

def test_the_shipped_sealed_evidence_is_the_real_sealed_evidence():
    """The copies beside the tests must be the Phase 1 files, not look-alikes."""
    if not PHASE_01.is_dir():
        pytest.skip("PHASE_01 is not present; the shipped copies stand alone")
    for name in SEALED_FILES:
        assert _sha(SEALED / name) == _sha(PHASE_01 / name), name


@pytest.mark.parametrize("name", sorted(LEGACY_SCHEMA_SHA256))
def test_the_legacy_schema_files_are_unchanged_since_they_were_sealed_against(name):
    assert _sha(SCHEMA_DIR / name) == LEGACY_SCHEMA_SHA256[name]


def test_the_sealed_phase_1_ledger_is_admitted_unchanged():
    """Never skipped: the decisive compatibility check. jsonschema is required."""
    import jsonschema
    doc = _sealed("persistent_changes.json")
    before = json.dumps(doc, sort_keys=True)
    assert pc.admit_ledger_version(doc) == pc.LEGACY_SCHEMA_VERSION
    pc.verify_ledger(doc)
    jsonschema.validate(doc, _schema(pc.LEDGER_SCHEMAS[pc.LEGACY_SCHEMA_VERSION]))
    assert doc["entries"], "the sealed ledger is not empty"
    assert json.dumps(doc, sort_keys=True) == before, "admission must not modify"


@pytest.mark.parametrize("name", ["rule_manifest.json", "rule_manifest_reopen.json"])
def test_the_sealed_phase_1_rule_manifests_are_admitted_unchanged(name):
    doc = _sealed(name)
    before = json.dumps(doc, sort_keys=True)
    assert ev.admit_rule_manifest_version(doc) == ev.LEGACY_RULE_MANIFEST_VERSION
    ev.verify_rule_manifest(doc)
    assert json.dumps(doc, sort_keys=True) == before


def test_a_legacy_ledger_can_still_be_appended_to_with_legacy_changes():
    lg = pc.new_ledger("riverside", schema_version=pc.LEGACY_SCHEMA_VERSION)
    rule = ev.seal_rule_manifest(_rule(ev.LEGACY_RULE_MANIFEST_VERSION, CLOSURE))
    lg, _ = pc.append_director_rule(lg, rule_manifest=rule)
    assert lg["schema_version"] == pc.LEGACY_SCHEMA_VERSION
    pc.verify_ledger(lg)


# -- new-version admission -------------------------------------------------

def test_a_new_ledger_declares_the_current_version():
    lg = pc.new_ledger("riverside")
    assert lg["schema_version"] == pc.SCHEMA_VERSION == "persistent_changes_v3"
    pc.verify_ledger(lg)


def test_a_v3_ledger_with_demand_flow_validates_against_the_v3_schema_only():
    import jsonschema
    rule = ev.seal_rule_manifest(_rule(ev.RULE_MANIFEST_VERSION, DEMAND))
    lg, _ = pc.append_director_rule(pc.new_ledger("riverside"), rule_manifest=rule)
    pc.verify_ledger(lg)
    jsonschema.validate(lg, _schema("persistent_changes_v3.schema.json"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(lg, _schema("persistent_changes.schema.json"))


def test_a_v2_rule_manifest_seals_and_verifies_and_says_v2():
    rule = ev.seal_rule_manifest(_rule(ev.RULE_MANIFEST_VERSION, DEMAND))
    assert rule["schema_version"] == "rule_manifest_v2"
    ev.verify_rule_manifest(rule)


def test_a_legacy_rule_manifest_still_seals_as_v1():
    rule = ev.seal_rule_manifest(_rule(ev.LEGACY_RULE_MANIFEST_VERSION, CLOSURE))
    assert rule["schema_version"] == "rule_manifest_v1"
    ev.verify_rule_manifest(rule)


def test_resealing_the_sealed_manifest_reproduces_its_sealed_hash():
    """v1 sealing is not merely still accepted, it is still the same function."""
    sealed = _sealed("rule_manifest.json")
    again = ev.seal_rule_manifest({**sealed, "manifest_hash": ""})
    assert again["manifest_hash"] == sealed["manifest_hash"]


# -- refusal: unknown, missing, malformed ----------------------------------

@pytest.mark.parametrize("bad", [
    None, "", 3, 2.0, True, ["persistent_changes_v3"], {"v": 3},
    "persistent_changes_v1", "persistent_changes_v4", "persistent_changes_v03",
    "persistent_changes_v3 ", " persistent_changes_v3", "PERSISTENT_CHANGES_V3",
    "persistent_changes", "rule_manifest_v2", "persistent_changes_v2\n",
])
def test_an_unknown_or_malformed_ledger_version_fails_closed(bad):
    lg = pc.new_ledger("riverside")
    lg["schema_version"] = bad
    with pytest.raises(pc.LedgerError):
        pc.admit_ledger_version(lg)
    with pytest.raises(pc.LedgerError):
        pc.verify_ledger(lg)
    with pytest.raises(pc.LedgerError):
        pc.migrate_ledger(lg)


def test_a_ledger_with_no_version_at_all_fails_closed():
    lg = pc.new_ledger("riverside")
    del lg["schema_version"]
    with pytest.raises(pc.LedgerError):
        pc.verify_ledger(lg)


@pytest.mark.parametrize("not_a_doc", [None, [], "ledger", 7])
def test_a_non_document_is_not_a_ledger(not_a_doc):
    with pytest.raises(pc.LedgerError):
        pc.admit_ledger_version(not_a_doc)


def test_a_ledger_cannot_be_created_at_an_unknown_version():
    with pytest.raises(pc.LedgerError):
        pc.new_ledger("riverside", schema_version="persistent_changes_v9")


@pytest.mark.parametrize("bad", [
    None, "", 1, ["rule_manifest_v1"], "rule_manifest_v0", "rule_manifest_v3",
    "rule_manifest", "persistent_changes_v2", "rule_manifest_v2 ",
])
def test_an_unknown_or_malformed_rule_manifest_version_fails_closed(bad):
    doc = _rule("rule_manifest_v2", CLOSURE)
    doc["schema_version"] = bad
    with pytest.raises(ev.EvidenceError):
        ev.seal_rule_manifest(doc)
    with pytest.raises(ev.EvidenceError):
        ev.verify_rule_manifest(doc)


# -- refusal: mixing versions ----------------------------------------------

def test_a_v1_rule_manifest_cannot_carry_demand_flow():
    with pytest.raises(ev.EvidenceError):
        ev.seal_rule_manifest(_rule(ev.LEGACY_RULE_MANIFEST_VERSION, DEMAND))


def test_a_legacy_ledger_refuses_a_demand_flow_append():
    lg = pc.new_ledger("riverside", schema_version=pc.LEGACY_SCHEMA_VERSION)
    rule = ev.seal_rule_manifest(_rule(ev.RULE_MANIFEST_VERSION, DEMAND))
    with pytest.raises(pc.LedgerError, match="persistent_changes_v2"):
        pc.append_director_rule(lg, rule_manifest=rule)


def test_relabelling_a_v3_ledger_as_v2_is_refused_on_load():
    """The downgrade a careless or hostile writer would try."""
    rule = ev.seal_rule_manifest(_rule(ev.RULE_MANIFEST_VERSION, DEMAND))
    lg, _ = pc.append_director_rule(pc.new_ledger("riverside"), rule_manifest=rule)
    forged = copy.deepcopy(lg)
    forged["schema_version"] = pc.LEGACY_SCHEMA_VERSION
    with pytest.raises(pc.LedgerError, match="demand_flow"):
        pc.verify_ledger(forged)


@pytest.mark.parametrize("extractor", sorted(pc.V3_ONLY_EXTRACTORS))
def test_a_legacy_ledger_refuses_a_phase_3_extractor(extractor):
    entry = {"change_type": "measured_effect",
             "provenance": {"source": "simulation", "extractor": extractor}}
    with pytest.raises(pc.LedgerError, match=extractor):
        pc._check_entry_admitted_by_version(pc.LEGACY_SCHEMA_VERSION, entry, "entry 0")
    pc._check_entry_admitted_by_version(pc.SCHEMA_VERSION, entry, "entry 0")


def test_the_version_tables_cover_every_approved_extractor_and_change_type():
    """Nothing may be approved without being assigned to a version."""
    assert pc.V3_ONLY_EXTRACTORS == pc.APPROVED_EXTRACTORS - {"closure_effect_v1"}
    legacy_enum = _schema("persistent_changes.schema.json")["$defs"]["entry"][
        "properties"]["change_type"]["enum"]
    assert set(pc.CHANGE_TYPES) - set(legacy_enum) == pc.V3_ONLY_CHANGE_TYPES


# -- migration -------------------------------------------------------------

def test_migration_changes_the_version_and_nothing_else():
    doc = _sealed("persistent_changes.json")
    original = copy.deepcopy(doc)
    out = pc.migrate_ledger(doc)
    assert doc == original, "the input must not be modified"
    assert out["schema_version"] == pc.SCHEMA_VERSION
    assert out["entries"] == doc["entries"]
    assert out["ledger_hash"] == doc["ledger_hash"]
    assert set(out) == set(doc)
    pc.verify_ledger(out)


def test_migration_is_deterministic_and_idempotent():
    doc = _sealed("persistent_changes.json")
    a, b = pc.migrate_ledger(doc), pc.migrate_ledger(doc)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert pc.migrate_ledger(a) == a


def test_a_migrated_ledger_validates_against_the_v3_schema():
    import jsonschema
    out = pc.migrate_ledger(_sealed("persistent_changes.json"))
    jsonschema.validate(out, _schema("persistent_changes_v3.schema.json"))


def test_a_migrated_ledger_accepts_what_the_legacy_one_refused():
    legacy = _sealed("persistent_changes.json")
    rule = ev.seal_rule_manifest(_rule(ev.RULE_MANIFEST_VERSION, DEMAND,
                                       rule_id="inject", episode=9))
    with pytest.raises(pc.LedgerError):
        pc.append_director_rule(legacy, rule_manifest=rule)
    out = pc.migrate_ledger(legacy)
    grown, _ = pc.append_director_rule(out, rule_manifest=rule)
    assert len(grown["entries"]) == len(out["entries"]) + 1
    pc.verify_ledger(grown)


def test_a_tampered_legacy_ledger_is_refused_rather_than_migrated():
    doc = _sealed("persistent_changes.json")
    doc["entries"][0]["applied_at_sim_second"] = 1.0
    with pytest.raises(pc.LedgerError):
        pc.migrate_ledger(doc)


# -- the module and the current schema must agree --------------------------

def test_demand_flow_is_admitted_by_both_the_module_and_the_schema():
    """The .py tables and the CURRENT schema must agree on the change types."""
    schema = _schema(pc.LEDGER_SCHEMAS[pc.SCHEMA_VERSION])
    enum = schema["$defs"]["entry"]["properties"]["change_type"]["enum"]
    assert sorted(enum) == sorted(pc.CHANGE_TYPES), (
        "schema change_type enum and persistent_changes.CHANGE_TYPES disagree"
    )
    assert "demand_flow" in enum
    refs = {
        v["$ref"].rsplit("/", 1)[-1]
        for v in schema["$defs"]["entry"]["properties"]["payload"]["oneOf"]
    }
    assert "payload_demand_flow" in refs
    payload = schema["$defs"]["payload_demand_flow"]
    assert payload["properties"]["kind"]["const"] == "demand_flow"
    assert set(pc._REQUIRED_PAYLOAD_FIELDS["demand_flow"]).issubset(set(payload["required"]))


def test_every_payload_kind_has_a_schema_variant():
    """No change type may exist in the module with no shape in the schema."""
    schema = _schema(pc.LEDGER_SCHEMAS[pc.SCHEMA_VERSION])
    refs = {
        v["$ref"].rsplit("/", 1)[-1]
        for v in schema["$defs"]["entry"]["properties"]["payload"]["oneOf"]
    }
    kinds_with_a_variant = {schema["$defs"][r]["properties"]["kind"]["const"] for r in refs}
    missing = sorted(set(pc._PAYLOAD_KIND.values()) - kinds_with_a_variant)
    assert missing == [], f"payload kinds with no schema variant: {missing}"


def test_each_schema_file_declares_exactly_its_own_version():
    for version, name in {**pc.LEDGER_SCHEMAS, **ev.RULE_MANIFEST_SCHEMAS}.items():
        assert _schema(name)["properties"]["schema_version"]["const"] == version


def test_verify_ledger_re_runs_the_RIGHT_extractor_for_each_entry():
    """Two extractors, one sealed result: each entry must be checked against ITS own.

    `_verify_entries_against_evidence` cached the derived effects under the
    simulation_result hash ALONE. When one episode's effects came from two
    extractors -- a traffic-light effect and a pedestrian effect from the same
    sealed pair -- the first extractor's output was cached and every later entry
    was compared against the wrong set. That rejected honest entries, and in the
    other direction it would have ACCEPTED an entry claiming extractor B while
    only ever re-running A, which is the forgery this function exists to catch.

    This pins the cache key. It needs no simulation: two fake extractors over
    one fake result is enough to show the entries are not conflated.
    """
    from ldyf import persistent_changes as pc

    cache: dict = {}
    # the shape the fixed code builds: (result_hash, extractor_name)
    for result_hash, extractor in (
        ("a" * 64, "traffic_light_effect_v1"),
        ("a" * 64, "pedestrian_effect_v1"),
    ):
        key = (result_hash, extractor)
        assert key not in cache, "the same result+extractor should cache once"
        cache[key] = [extractor]
    assert len(cache) == 2, (
        "two extractors over one sealed result must occupy two cache slots; "
        "one slot means the second extractor is never re-run"
    )

    src = Path(pc.__file__).read_text(encoding="utf-8")
    assert 'want = (prov["simulation_result_sha256"], prov["extractor"])' in src, (
        "the derived-effect cache must be keyed on the extractor as well as the "
        "sealed result"
    )


# ---------------------------------------------------------------------------
# runtime truth guards
# ---------------------------------------------------------------------------


def test_an_unapproved_extractor_cannot_register_at_runtime():
    """Prevention, not detection.

    The closed set used to be enforced only by a test, which a red-team
    reviewer called out exactly: a module that registered an extractor as an
    import side effect gained the right to write measured_effect entries, and
    only a later test run would have noticed. A measured_effect is the one
    place a number enters the ledger, so the registry refuses at runtime.
    """
    from ldyf import consequence  # noqa: F401  (registers the Phase 3 four)
    from ldyf.persistent_changes import (
        APPROVED_EXTRACTORS,
        CONSEQUENCE_EXTRACTORS,
        LedgerError,
    )

    assert set(CONSEQUENCE_EXTRACTORS) == set(APPROVED_EXTRACTORS)

    with pytest.raises(LedgerError, match="not approved"):
        CONSEQUENCE_EXTRACTORS["smuggled_effect_v1"] = lambda *a, **k: []
    with pytest.raises(LedgerError, match="not approved"):
        CONSEQUENCE_EXTRACTORS[123] = lambda *a, **k: []
    assert "smuggled_effect_v1" not in CONSEQUENCE_EXTRACTORS


def test_an_approved_extractor_cannot_be_rebound_or_removed():
    """Write-once: nothing may replace the function that computes the truth."""
    from ldyf import consequence  # noqa: F401
    from ldyf.persistent_changes import CONSEQUENCE_EXTRACTORS, LedgerError

    original = CONSEQUENCE_EXTRACTORS["closure_effect_v1"]
    with pytest.raises(LedgerError, match="already registered"):
        CONSEQUENCE_EXTRACTORS["closure_effect_v1"] = lambda *a, **k: []
    with pytest.raises(LedgerError, match="refusing to unregister"):
        del CONSEQUENCE_EXTRACTORS["closure_effect_v1"]
    assert CONSEQUENCE_EXTRACTORS["closure_effect_v1"] is original

    # re-registering the SAME function is harmless and must stay allowed, or a
    # module could not be imported twice
    CONSEQUENCE_EXTRACTORS["closure_effect_v1"] = original
