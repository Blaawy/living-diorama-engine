"""Proof that the truth audit refuses an uncited claim, a citation of a field
the artefact does not have, a citation of an artefact that does not exist, and a
claim whose stated number differs from the measured one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ldyf.truth_audit import TruthAuditError, audit_claims

MEASURED = {
    "schema_version": "measured_v1",
    "trips": {"baseline": 400, "ruled": 381, "delta": -19},
    "waiting": {"baseline": 12.53, "ruled": 30.0},
    "closure": {"edges": ["B1C1"], "hash": "ab" * 32},
    "rows": [{"value": 7}],
}


def evidence_dir(tmp_path: Path, measured: dict = MEASURED) -> Path:
    (tmp_path / "measured.json").write_text(json.dumps(measured, indent=2), encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir(exist_ok=True)
    (sub / "other.json").write_text(json.dumps({"count": 5}), encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not json", encoding="utf-8")
    return tmp_path


def claim(text, cites):
    return {"text": text, "cites": cites}


def one(tmp_path, text, cites, **kw):
    """Audit a single claim and return its verdict row."""
    report = audit_claims([claim(text, cites)], evidence_dir(tmp_path), **kw)
    return report, report["claims"][0]


# ==========================================================================
# Claims the artefacts do support
# ==========================================================================


def test_a_claim_whose_numbers_come_from_its_citations_is_supported(tmp_path):
    report, row = one(
        tmp_path,
        "The closure cut completed trips from 400 to 381.",
        [["measured.json", "trips.baseline"], ["measured.json", "trips.ruled"]],
    )
    assert row["verdict"] == "supported"
    assert row["reasons"] == []
    assert report["pass"] is True
    assert report["supported_claims"] == 1
    assert [c["value"] for c in row["citations"]] == [400, 381]


def test_a_claim_with_no_numbers_needs_only_a_resolvable_citation(tmp_path):
    report, row = one(
        tmp_path,
        "The closure bars passenger traffic from the bridge.",
        [["measured.json", "closure.edges"]],
    )
    assert row["verdict"] == "supported"
    assert report["pass"] is True


def test_a_claim_may_cite_a_field_inside_a_list(tmp_path):
    report, row = one(
        tmp_path, "One measured row held 7.", [["measured.json", "rows.0.value"]]
    )
    assert row["verdict"] == "supported"


def test_a_claim_may_cite_an_artefact_in_a_subdirectory(tmp_path):
    report, row = one(tmp_path, "The count reached 5.", [["sub/other.json", "count"]])
    assert row["verdict"] == "supported"


def test_a_negative_number_must_match_too(tmp_path):
    _, row = one(tmp_path, "The delta was -19 trips.", [["measured.json", "trips.delta"]])
    assert row["verdict"] == "supported"


def test_a_stated_number_may_round_the_measurement(tmp_path):
    _, row = one(tmp_path, "The mean wait was 12.5 s.", [["measured.json", "waiting.baseline"]])
    assert row["verdict"] == "supported"


# ==========================================================================
# Refusals
# ==========================================================================


def test_a_claim_with_no_citation_is_refused(tmp_path):
    report, row = one(tmp_path, "Only 381 trips completed.", [])
    assert row["verdict"] == "refused"
    assert any("cites nothing" in r for r in row["reasons"])
    assert report["pass"] is False
    assert report["refused_claims"] == [0]


def test_a_claim_without_a_cites_key_is_refused(tmp_path):
    report = audit_claims([{"text": "Only 381 trips completed."}], evidence_dir(tmp_path))
    assert report["claims"][0]["verdict"] == "refused"
    assert any("cites nothing" in r for r in report["claims"][0]["reasons"])
    assert report["pass"] is False


def test_a_citation_of_a_field_the_artefact_lacks_is_refused(tmp_path):
    _, row = one(
        tmp_path, "The count reached 9.", [["measured.json", "trips.no_such_field"]]
    )
    assert row["verdict"] == "refused"
    assert any("has no field" in r for r in row["reasons"])


def test_a_citation_of_a_field_below_a_non_object_is_refused(tmp_path):
    _, row = one(tmp_path, "The count reached 9.", [["measured.json", "trips.baseline.deeper"]])
    assert row["verdict"] == "refused"
    assert any("has no field" in r for r in row["reasons"])


def test_a_citation_of_an_artefact_that_does_not_exist_is_refused(tmp_path):
    _, row = one(tmp_path, "The count reached 9.", [["nowhere.json", "trips.ruled"]])
    assert row["verdict"] == "refused"
    assert any("does not exist" in r for r in row["reasons"])


def test_a_stated_number_that_differs_from_the_measurement_is_refused(tmp_path):
    _, row = one(
        tmp_path,
        "The closure cut completed trips from 400 to 384.",
        [["measured.json", "trips.baseline"], ["measured.json", "trips.ruled"]],
    )
    assert row["verdict"] == "refused"
    assert any("384" in r and "differs" in r for r in row["reasons"])


def test_a_rounding_that_overstates_the_measurement_is_refused(tmp_path):
    _, row = one(tmp_path, "The mean wait was 12.6 s.", [["measured.json", "waiting.baseline"]])
    assert row["verdict"] == "refused"
    assert any("12.6" in r for r in row["reasons"])


def test_a_number_that_no_numeric_citation_can_back_is_refused(tmp_path):
    _, row = one(tmp_path, "The trips fell by 19.", [["measured.json", "closure.hash"]])
    assert row["verdict"] == "refused"
    assert any("resolves to a measured number" in r for r in row["reasons"])


def test_a_citation_that_is_not_an_artefact_field_pair_is_refused(tmp_path):
    for cites in ([["measured.json"]], [["measured.json", "trips.ruled", "extra"]],
                  ["measured.json#trips.ruled"], [[7, "trips.ruled"]]):
        report = audit_claims([claim("The count reached 381.", cites)], evidence_dir(tmp_path))
        assert report["claims"][0]["verdict"] == "refused", cites
        assert report["pass"] is False, cites


def test_a_citation_that_climbs_out_of_the_evidence_directory_is_refused(tmp_path):
    for artefact in ("../measured.json", "/etc/passwd", "sub/../../measured.json", "C:/x.json"):
        report = audit_claims(
            [claim("The count reached 381.", [[artefact, "trips.ruled"]])], evidence_dir(tmp_path)
        )
        row = report["claims"][0]
        assert row["verdict"] == "refused", artefact
        assert any("plain relative path" in r for r in row["reasons"]), artefact


def test_a_citation_of_a_file_that_is_not_json_is_refused(tmp_path):
    _, row = one(tmp_path, "The count reached 5.", [["notes.txt", "count"]])
    assert row["verdict"] == "refused"
    assert any("not parseable JSON" in r for r in row["reasons"])


def test_a_claim_that_is_not_an_object_is_refused(tmp_path):
    report = audit_claims(["the bridge closed"], evidence_dir(tmp_path))
    assert report["claims"][0]["verdict"] == "refused"
    assert report["pass"] is False


def test_a_claim_with_no_text_is_refused(tmp_path):
    report = audit_claims([{"cites": [["measured.json", "trips.ruled"]]}], evidence_dir(tmp_path))
    assert report["claims"][0]["verdict"] == "refused"
    assert any("no text" in r for r in report["claims"][0]["reasons"])


# ==========================================================================
# The report as a whole
# ==========================================================================


def test_the_report_refuses_exactly_the_unsupported_claims(tmp_path):
    doc = [
        claim("Trips fell from 400 to 381.", [["measured.json", "trips.baseline"],
                                             ["measured.json", "trips.ruled"]]),
        claim("Trips fell to 999.", [["measured.json", "trips.ruled"]]),
        claim("The world got nicer.", []),
        claim("One row held 7.", [["measured.json", "rows.0.value"]]),
    ]
    report = audit_claims(doc, evidence_dir(tmp_path))
    assert report["claims_total"] == 4
    assert report["supported_claims"] == 2
    assert report["refused_claims"] == [1, 2]
    assert report["pass"] is False
    assert [c["verdict"] for c in report["claims"]] == [
        "supported", "refused", "refused", "supported"]


def test_an_empty_document_passes_vacuously(tmp_path):
    report = audit_claims([], evidence_dir(tmp_path))
    assert report["claims_total"] == 0
    assert report["pass"] is True


def test_strict_mode_raises_instead_of_reporting(tmp_path):
    doc = [claim("Trips fell to 999.", [["measured.json", "trips.ruled"]])]
    with pytest.raises(TruthAuditError, match="refused 1 of 1 claim"):
        audit_claims(doc, evidence_dir(tmp_path), strict=True)
    report = audit_claims(doc, evidence_dir(tmp_path))
    assert report["pass"] is False


def test_a_document_that_is_not_a_list_is_refused(tmp_path):
    with pytest.raises(TruthAuditError, match="LIST"):
        audit_claims({"text": "x", "cites": []}, evidence_dir(tmp_path))


def test_a_missing_evidence_directory_is_refused(tmp_path):
    with pytest.raises(TruthAuditError, match="not a directory"):
        audit_claims([], tmp_path / "nowhere")
