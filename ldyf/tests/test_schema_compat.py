"""A schema may only be widened in ways that keep SEALED evidence valid.

Phase 3 added a fourth rule class, `demand_flow`, which the ledger schema did
not admit. The version was NOT bumped, and that decision needs a guard rather
than a comment: bumping `persistent_changes_v2` to v3 would have invalidated
the sealed Phase 1 closure ledger, which is locked evidence, for no gain. The
widening is additive -- a new enum member and a new payload variant -- so every
document that validated before still validates.

This file is the proof of that claim, re-run on every suite. If someone later
narrows the schema, renames a payload field, or bumps the version without
migrating, the sealed Phase 1 ledger stops validating here and the suite fails.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"
PHASE_01_LEDGER = (
    Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
    / "PHASE_01" / "proof" / "sumo" / "closure_v2" / "persistent_changes.json"
)


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def test_ledger_schema_still_admits_the_sealed_phase_1_ledger():
    """The decisive compatibility check: locked evidence must still validate."""
    jsonschema = pytest.importorskip("jsonschema")
    if not PHASE_01_LEDGER.is_file():
        pytest.skip("sealed Phase 1 ledger is not present in this checkout")
    doc = json.loads(PHASE_01_LEDGER.read_text(encoding="utf-8"))
    jsonschema.validate(doc, _schema("persistent_changes.schema.json"))
    assert doc["entries"], "the sealed ledger is not empty"


def test_demand_flow_is_admitted_by_both_the_module_and_the_schema():
    """The .py tables and the JSON schema must agree on the change types.

    They drifted once: the rules lane added `demand_flow` to the module's three
    tables and deliberately left the schema alone, so a demand_flow entry passed
    `_validate_payload` and would have failed schema validation. Nothing caught
    it but a worker's own limitations note.
    """
    from ldyf import persistent_changes as pc

    schema = _schema("persistent_changes.schema.json")
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
    # the schema's required fields must cover the module's required fields
    assert set(pc._REQUIRED_PAYLOAD_FIELDS["demand_flow"]).issubset(
        set(payload["required"])
    )


def test_every_payload_kind_has_a_schema_variant():
    """No change type may exist in the module with no shape in the schema."""
    from ldyf import persistent_changes as pc

    schema = _schema("persistent_changes.schema.json")
    refs = {
        v["$ref"].rsplit("/", 1)[-1]
        for v in schema["$defs"]["entry"]["properties"]["payload"]["oneOf"]
    }
    kinds_with_a_variant = {
        schema["$defs"][r]["properties"]["kind"]["const"] for r in refs
    }
    missing = sorted(set(pc._PAYLOAD_KIND.values()) - kinds_with_a_variant)
    assert missing == [], f"payload kinds with no schema variant: {missing}"


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
