"""Reaching a recorded sentence, suspiciously.

A fact reached by identifier is not thereby the fact a beat cites. These tests
prove the dereference refuses every way an export could answer to the right name
with the wrong record, and that the sentence it returns is carried byte for byte.
"""

import copy
from typing import Any

import pytest

from living_diorama.narration.narration_facts import (
    EVIDENCE_AGREEMENT_FIELDS,
    fact_summary_for_evidence,
    resolve_fact,
)

from .conftest import build_sources, load_export

FACT_BEARING_EPISODE = 2
"""Episode 1 -> 2 carries two facts, one of them new: the persisted consequence."""


def _fact_evidence(story: dict[str, Any]) -> dict[str, Any]:
    """Return the first memory-fact evidence entry a story cites."""
    for beat in story["beats"]:
        for entry in beat["evidence"]:
            if entry["kind"] == "memory_fact":
                return entry
    raise AssertionError("fixture story cites no memory fact")


@pytest.fixture
def export() -> dict[str, Any]:
    """An independent copy of the fact-bearing render export."""
    return load_export(FACT_BEARING_EPISODE)


@pytest.fixture
def evidence() -> dict[str, Any]:
    """The memory-fact evidence entry the persisted-consequence beat cites."""
    story, _shots, _export = build_sources(FACT_BEARING_EPISODE)
    return _fact_evidence(story)


# ---- resolution


def test_a_fact_resolves_by_identifier(export: dict[str, Any], evidence: dict[str, Any]) -> None:
    """The happy path: the cited record is found in the bound export."""
    fact = resolve_fact(export, evidence["fact_id"], "unit")
    assert fact["fact_id"] == evidence["fact_id"]


def test_an_absent_fact_is_refused(export: dict[str, Any]) -> None:
    """A sentence is never written for a record the export cannot produce."""
    with pytest.raises(ValueError, match="does not carry"):
        resolve_fact(export, "fact_" + "f" * 8, "unit")


def test_a_duplicated_fact_id_is_refused(export: dict[str, Any], evidence: dict[str, Any]) -> None:
    """Refused rather than resolved to the first or the last.

    Durable memory guarantees unique ids, so an export carrying two did not come
    from the engine, and picking one would narrate a record nobody chose.
    """
    twin = copy.deepcopy(
        next(f for f in export["memory"]["facts"] if f["fact_id"] == evidence["fact_id"])
    )
    export["memory"]["facts"].append(twin)
    with pytest.raises(ValueError, match="carries 2 times|carries 2"):
        resolve_fact(export, evidence["fact_id"], "unit")


def test_a_malformed_facts_section_is_refused(export: dict[str, Any]) -> None:
    """The export's own shape is checked before anything is searched."""
    export["memory"]["facts"] = {}
    with pytest.raises(TypeError, match="must be a list"):
        resolve_fact(export, "fact_x", "unit")


def test_a_missing_memory_section_is_refused() -> None:
    """An export with no memory section is refused rather than treated as empty."""
    with pytest.raises(TypeError, match="must be a dict"):
        resolve_fact({"memory": None}, "fact_x", "unit")


def test_a_structurally_broken_fact_is_refused(
    export: dict[str, Any], evidence: dict[str, Any]
) -> None:
    """The story layer's own fact-shape contract still applies here."""
    fact = next(f for f in export["memory"]["facts"] if f["fact_id"] == evidence["fact_id"])
    del fact["source_event_index"]
    with pytest.raises(ValueError, match="missing required keys"):
        resolve_fact(export, evidence["fact_id"], "unit")


# ---- agreement with the evidence


def test_the_summary_is_carried_verbatim(export: dict[str, Any], evidence: dict[str, Any]) -> None:
    """What comes back is the export's own sentence, unmodified."""
    recorded = next(f for f in export["memory"]["facts"] if f["fact_id"] == evidence["fact_id"])[
        "summary"
    ]
    assert fact_summary_for_evidence(export, evidence, "unit") == recorded


@pytest.mark.parametrize("field", EVIDENCE_AGREEMENT_FIELDS)
def test_a_fact_disagreeing_with_its_evidence_is_refused(
    export: dict[str, Any], evidence: dict[str, Any], field: str
) -> None:
    """Every field the evidence already stated must be confirmed by the record.

    Without this a mutated export could substitute one record's sentence for
    another's while the identifier still matched.
    """
    fact = next(f for f in export["memory"]["facts"] if f["fact_id"] == evidence["fact_id"])
    fact[field] = 999_999 if isinstance(fact[field], int) else "something_else"
    with pytest.raises(ValueError, match="belongs to a different record"):
        fact_summary_for_evidence(export, evidence, "unit")


def test_a_boolean_never_satisfies_an_integer_field(
    export: dict[str, Any], evidence: dict[str, Any]
) -> None:
    """``True == 1`` in Python, so equality alone would let a boolean through."""
    fact = next(f for f in export["memory"]["facts"] if f["fact_id"] == evidence["fact_id"])
    evidence = {**evidence, "tick": True}
    fact["tick"] = 1
    with pytest.raises(ValueError, match="belongs to a different record"):
        fact_summary_for_evidence(export, evidence, "unit")


# ---- the sentence itself


def test_a_fact_without_a_summary_is_refused(
    export: dict[str, Any], evidence: dict[str, Any]
) -> None:
    """This beat is narrated by restating a recorded sentence; there must be one."""
    fact = next(f for f in export["memory"]["facts"] if f["fact_id"] == evidence["fact_id"])
    del fact["summary"]
    with pytest.raises(ValueError, match="there is none to restate"):
        fact_summary_for_evidence(export, evidence, "unit")


def test_a_blank_summary_is_refused(export: dict[str, Any], evidence: dict[str, Any]) -> None:
    """Whitespace is not a sentence."""
    fact = next(f for f in export["memory"]["facts"] if f["fact_id"] == evidence["fact_id"])
    fact["summary"] = "   "
    with pytest.raises(ValueError, match="only whitespace"):
        fact_summary_for_evidence(export, evidence, "unit")


def test_a_non_string_summary_is_refused(export: dict[str, Any], evidence: dict[str, Any]) -> None:
    """Nor is a list that happens to sit under the right key."""
    fact = next(f for f in export["memory"]["facts"] if f["fact_id"] == evidence["fact_id"])
    fact["summary"] = ["a", "sentence"]
    with pytest.raises(TypeError, match="must be a str"):
        fact_summary_for_evidence(export, evidence, "unit")


def test_evidence_without_a_fact_id_is_refused(export: dict[str, Any]) -> None:
    """The lookup key is required before any lookup is attempted."""
    with pytest.raises(TypeError, match="must be a str"):
        fact_summary_for_evidence(export, {"kind": "memory_fact"}, "unit")


def test_the_dereference_does_not_read_details(
    export: dict[str, Any], evidence: dict[str, Any]
) -> None:
    """Payload internals are not this layer's to interpret.

    Emptying ``details`` -- which carries the whole source event payload -- must
    not change the sentence, because nothing here reads it.
    """
    before = fact_summary_for_evidence(export, evidence, "unit")
    fact = next(f for f in export["memory"]["facts"] if f["fact_id"] == evidence["fact_id"])
    fact["details"] = {}
    assert fact_summary_for_evidence(export, evidence, "unit") == before
