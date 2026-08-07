"""Tests for MemoryFact: identity, wording, immutability, and exact validation.

A fact is a claim the engine will still be repeating many episodes from now, so
almost everything here is about refusing to record one that cannot be trusted:
an identifier that says something different from the content it names, a
summary that asserts more than the events proved, or a detail that would not
survive a round trip as the same Python value.
"""

import json
import math
import pathlib
from dataclasses import dataclass

import pytest

from living_diorama.events import EventType
from living_diorama.memory import MemoryFact, MemoryFactType
from memory.conftest import BOUNDARY_ID, LAW_ID, WALL_ID, wall_built_fact, wall_persisted_fact


def wall_details(**overrides: object) -> dict:
    """Return valid wall-construction details with optional replacements."""
    details = {
        "boundary_id": BOUNDARY_ID,
        "built_tick": 120,
        "district_a_id": "district_a",
        "district_b_id": "district_b",
        "permanent": True,
        "source_event_payload": {},
        "wall_id": WALL_ID,
    }
    details.update(overrides)
    return details


def build_fact(**overrides: object) -> MemoryFact:
    """Build a wall-construction fact with optional field replacements."""
    fields: dict = {
        "fact_type": MemoryFactType.WALL_BUILT,
        "episode": 0,
        "tick": 120,
        "source_event_index": 0,
        "source_event_type": EventType.WALL_BUILT,
        "source_id": WALL_ID,
        "subject_ids": tuple(sorted({BOUNDARY_ID, "district_a", "district_b", WALL_ID})),
        "details": wall_details(),
    }
    fields.update(overrides)
    return MemoryFact(**fields)


# --- Construction -----------------------------------------------------------


def test_a_wall_construction_fact_carries_what_it_claims() -> None:
    """Every field is exactly what was recorded, with the derived ones added."""
    fact = wall_built_fact()

    assert fact.fact_type is MemoryFactType.WALL_BUILT
    assert fact.source_event_type is EventType.WALL_BUILT
    assert fact.source_id == WALL_ID
    assert fact.episode == 0
    assert fact.tick == 120
    assert fact.subject_ids == (BOUNDARY_ID, "district_a", "district_b", WALL_ID)
    assert sorted(fact.details) == [
        "boundary_id",
        "built_tick",
        "district_a_id",
        "district_b_id",
        "permanent",
        "source_event_payload",
        "wall_id",
    ]


def test_a_wall_persistence_fact_carries_what_it_claims() -> None:
    """Including the closing dependency values it records without interpreting."""
    fact = wall_persisted_fact()

    assert fact.fact_type is MemoryFactType.LAW_RESTORED_WALL_PERSISTED
    assert fact.source_event_type is EventType.LAW_RESTORED
    assert fact.source_id == LAW_ID
    assert fact.subject_ids == (BOUNDARY_ID, LAW_ID, WALL_ID)
    assert fact.details["wall_dependency_score_at_episode_close"] == 0.78
    assert fact.details["wall_active_at_episode_close"] is True


def test_the_fact_id_is_derived_and_reproducible() -> None:
    """Identity is a hash of content, so the same history names facts the same."""
    first = wall_built_fact()
    second = wall_built_fact()

    assert first.fact_id == second.fact_id
    assert first.fact_id.startswith("fact_")
    digest = first.fact_id.removeprefix("fact_")
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_the_fact_id_matches_the_documented_construction() -> None:
    """Pinned against the exact identity document and encoding."""
    import hashlib  # noqa: PLC0415

    fact = wall_built_fact()
    encoded = json.dumps(
        fact.identity_document(),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    assert not encoded.endswith(b"\n"), "fact identity carries no trailing newline"
    assert fact.fact_id == "fact_" + hashlib.sha256(encoded).hexdigest()


def test_the_fact_id_ignores_mapping_insertion_order() -> None:
    """Two payloads holding the same data must name the same fact."""
    forward = wall_built_fact(payload={"a": 1, "b": {"x": 1, "y": 2}})
    backward = wall_built_fact(payload={"b": {"y": 2, "x": 1}, "a": 1})
    assert forward.fact_id == backward.fact_id


def test_different_content_produces_a_different_fact_id() -> None:
    """Including the event position, which is what separates two dispatches."""
    assert wall_built_fact().fact_id != wall_built_fact(source_event_index=1).fact_id
    assert wall_built_fact().fact_id != wall_built_fact(tick=121).fact_id


def test_the_summary_matches_the_documented_template() -> None:
    """Structured prose, quoted exactly as specified."""
    assert wall_built_fact().summary == (
        'Wall "wall_boundary_ab" was built on boundary "boundary_ab" between districts '
        '"district_a" and "district_b" at tick 120; it was marked permanent.'
    )
    assert wall_persisted_fact().summary == (
        'Law "resource_sharing" ("Resource Sharing") was restored at tick 250; permanent '
        'wall "wall_boundary_ab" on boundary "boundary_ab", built at tick 120, remained in '
        "the world."
    )


@pytest.mark.parametrize(
    "word", ["caused", "because of", "therefore", "responsible for", "forced", "led to"]
)
def test_no_summary_asserts_a_causality_the_events_never_proved(word: str) -> None:
    """A persistence fact says two things were true, not that one made the other."""
    for fact in (wall_built_fact(), wall_persisted_fact()):
        assert word not in fact.summary


def test_facts_compare_by_value() -> None:
    """Two facts recording the same claim are the same fact."""
    assert wall_built_fact() == wall_built_fact()
    assert wall_built_fact() != wall_built_fact(tick=121)


# --- Immutability -----------------------------------------------------------


def test_mutating_the_supplied_details_afterwards_changes_nothing() -> None:
    """The fact copies what it was given; a retained reference is not a back door."""
    payload = {"list": [1, 2], "nested": {"k": "v"}}
    details = wall_details(source_event_payload=payload)
    fact = build_fact(details=details)
    recorded = fact.details_as_dict()

    details["wall_id"] = "other"
    payload["list"].append(3)
    payload["nested"]["k"] = "changed"

    assert fact.details["wall_id"] == WALL_ID
    assert fact.details_as_dict() == recorded


def test_the_details_cannot_be_mutated_at_any_depth() -> None:
    """Read-only mappings and tuples all the way down."""
    fact = build_fact(details=wall_details(source_event_payload={"nested": {"k": [1, 2]}}))

    with pytest.raises(TypeError):
        fact.details["wall_id"] = "other"  # type: ignore[index]
    with pytest.raises(TypeError):
        fact.details["source_event_payload"]["nested"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        fact.details["source_event_payload"]["nested"]["k"] = []  # type: ignore[index]
    assert isinstance(fact.details["source_event_payload"]["nested"]["k"], tuple)


def test_the_fact_itself_cannot_be_rewritten() -> None:
    """Frozen, including the derived identifier and summary."""
    fact = wall_built_fact()
    for attribute in ("tick", "fact_id", "summary", "details"):
        with pytest.raises(AttributeError):
            setattr(fact, attribute, "rewritten")


def test_details_as_dict_is_detached_and_mutable() -> None:
    """A caller gets an ordinary copy to work with, not the stored mapping."""
    fact = build_fact(details=wall_details(source_event_payload={"k": [1]}))
    detached = fact.details_as_dict()

    detached["wall_id"] = "other"
    detached["source_event_payload"]["k"].append(2)

    assert fact.details["wall_id"] == WALL_ID
    assert fact.details_as_dict()["source_event_payload"]["k"] == [1]


# --- Exact validation -------------------------------------------------------


@pytest.mark.parametrize("field", ["episode", "tick", "source_event_index"])
@pytest.mark.parametrize("bad", [True, False, 1.0, "1", None])
def test_mistyped_counters_are_refused(field: str, bad: object) -> None:
    """``True == 1``, so a bool would silently become episode or tick one."""
    with pytest.raises(TypeError):
        build_fact(**{field: bad})


@pytest.mark.parametrize("field", ["episode", "tick", "source_event_index"])
def test_negative_counters_are_refused(field: str) -> None:
    """Nothing happened before the world began."""
    with pytest.raises(ValueError):
        build_fact(**{field: -1})


@pytest.mark.parametrize("bad", ["WALL_BUILT", None, 0, EventType.WALL_BUILT])
def test_a_fact_type_that_is_not_the_enum_is_refused(bad: object) -> None:
    """A string naming the type is not the type."""
    with pytest.raises(TypeError):
        build_fact(fact_type=bad)


@pytest.mark.parametrize("bad", ["WALL_BUILT", None, MemoryFactType.WALL_BUILT])
def test_a_source_event_type_that_is_not_the_enum_is_refused(bad: object) -> None:
    """The same rule for the event vocabulary."""
    with pytest.raises(TypeError):
        build_fact(source_event_type=bad)


@pytest.mark.parametrize("bad", [None, "", "   ", " wall", "wall ", 1, True])
def test_a_missing_or_noncanonical_source_id_is_refused(bad: object) -> None:
    """Stripping would record a different entity than the world uses."""
    with pytest.raises((TypeError, ValueError)):
        build_fact(source_id=bad)


def test_duplicate_subjects_are_refused() -> None:
    """One entity, one entry."""
    with pytest.raises(ValueError):
        build_fact(subject_ids=(BOUNDARY_ID, BOUNDARY_ID, "district_a", "district_b", WALL_ID))


def test_unsorted_subjects_are_refused() -> None:
    """Sorted subjects are what make a subject query total."""
    with pytest.raises(ValueError):
        build_fact(subject_ids=(WALL_ID, BOUNDARY_ID, "district_a", "district_b"))


def test_a_subject_set_that_does_not_match_the_details_is_refused() -> None:
    """Subjects are derived from the claim, not supplied independently."""
    with pytest.raises(ValueError):
        build_fact(subject_ids=(BOUNDARY_ID, "district_a", "district_b"))
    with pytest.raises(ValueError):
        build_fact(
            subject_ids=tuple(sorted({BOUNDARY_ID, "district_a", "district_b", WALL_ID, "extra"}))
        )


def test_a_missing_details_key_is_refused() -> None:
    """An incomplete claim cannot be completed by assumption."""
    details = wall_details()
    del details["permanent"]
    with pytest.raises(ValueError):
        build_fact(details=details)


def test_an_unexpected_details_key_is_refused() -> None:
    """A key this build does not understand may be carrying meaning."""
    with pytest.raises(ValueError):
        build_fact(details=wall_details(surprise=1))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_in_details_are_refused(bad: float) -> None:
    """A value JSON cannot represent cannot be part of durable history."""
    with pytest.raises(ValueError):
        build_fact(details=wall_details(source_event_payload={"value": bad}))


@pytest.mark.parametrize(
    "bad",
    [
        {1: "one"},
        {"k": (1, 2)},
        {"k": {1, 2}},
        {"k": frozenset({1})},
        {"k": pathlib.Path("/tmp")},
        {"k": EventType.WALL_BUILT},
        {"k": MemoryFactType.WALL_BUILT},
        {"k": object()},
        {"k": b"bytes"},
    ],
)
def test_values_a_fact_may_not_carry_are_refused(bad: dict) -> None:
    """Anything that would not round-trip as the same Python value."""
    with pytest.raises(TypeError):
        build_fact(details=wall_details(source_event_payload=bad))


def test_a_dataclass_inside_details_is_refused() -> None:
    """Even one that would serialize; a fact stores JSON, not objects."""

    @dataclass
    class Thing:
        """A plain dataclass standing in for any domain object."""

        value: int

    with pytest.raises(TypeError):
        build_fact(details=wall_details(source_event_payload={"k": Thing(1)}))


def test_a_details_mapping_that_is_not_a_mapping_is_refused() -> None:
    """The details are an object, not a list of pairs."""
    with pytest.raises(TypeError):
        build_fact(details=[("wall_id", WALL_ID)])


def test_subject_ids_must_be_a_tuple() -> None:
    """A list would offer a mutation path into the fact."""
    with pytest.raises(TypeError):
        build_fact(subject_ids=[BOUNDARY_ID, "district_a", "district_b", WALL_ID])


# --- Cross-field validation -------------------------------------------------


def test_a_wall_fact_from_a_restoration_event_is_refused() -> None:
    """Each fact type has exactly one event type it may be derived from."""
    with pytest.raises(ValueError):
        build_fact(source_event_type=EventType.LAW_RESTORED)


def test_a_persistence_fact_from_a_wall_event_is_refused() -> None:
    """And the same in the other direction."""
    fact = wall_persisted_fact()
    with pytest.raises(ValueError):
        MemoryFact(
            fact_type=MemoryFactType.LAW_RESTORED_WALL_PERSISTED,
            episode=fact.episode,
            tick=fact.tick,
            source_event_index=0,
            source_event_type=EventType.WALL_BUILT,
            source_id=LAW_ID,
            subject_ids=fact.subject_ids,
            details=fact.details_as_dict(),
        )


def test_a_wall_fact_sourced_from_another_entity_is_refused() -> None:
    """A wall's construction is reported by that wall's own event."""
    with pytest.raises(ValueError):
        build_fact(
            source_id="district_a",
            subject_ids=tuple(sorted({BOUNDARY_ID, "district_a", "district_b", WALL_ID})),
        )


def test_a_persistence_fact_sourced_from_another_entity_is_refused() -> None:
    """A restoration is reported by the law that was restored."""
    fact = wall_persisted_fact()
    with pytest.raises(ValueError):
        MemoryFact(
            fact_type=MemoryFactType.LAW_RESTORED_WALL_PERSISTED,
            episode=fact.episode,
            tick=fact.tick,
            source_event_index=0,
            source_event_type=EventType.LAW_RESTORED,
            source_id=WALL_ID,
            subject_ids=fact.subject_ids,
            details=fact.details_as_dict(),
        )


@pytest.mark.parametrize("bad", [False, 1, "true", None])
def test_a_wall_fact_that_is_not_exactly_permanent_is_refused(bad: object) -> None:
    """Only a permanent wall is remembered as built."""
    with pytest.raises((TypeError, ValueError)):
        build_fact(details=wall_details(permanent=bad))


def test_a_wall_fact_whose_build_tick_disagrees_with_its_own_tick_is_refused() -> None:
    """The fact is recorded at the moment the wall went up."""
    with pytest.raises(ValueError):
        build_fact(details=wall_details(built_tick=119))


def test_a_boundary_joining_a_district_to_itself_is_refused() -> None:
    """The entity layer forbids it, and a fact must not record it either."""
    with pytest.raises(ValueError):
        build_fact(
            details=wall_details(district_b_id="district_a"),
            subject_ids=tuple(sorted({BOUNDARY_ID, "district_a", WALL_ID})),
        )


def test_a_persistence_fact_whose_restored_tick_disagrees_is_refused() -> None:
    """The fact tick is the restoration tick."""
    fact = wall_persisted_fact()
    details = fact.details_as_dict()
    details["restored_tick"] = 249
    with pytest.raises(ValueError):
        MemoryFact(
            fact_type=fact.fact_type,
            episode=fact.episode,
            tick=fact.tick,
            source_event_index=0,
            source_event_type=fact.source_event_type,
            source_id=fact.source_id,
            subject_ids=fact.subject_ids,
            details=details,
        )


@pytest.mark.parametrize("wall_built_tick", [250, 251])
def test_a_wall_not_already_standing_at_the_restoration_is_refused(
    wall_built_tick: int,
) -> None:
    """The comparison is strict.

    A wall raised during the very tick the law was restored was not already
    standing when the restoration happened, so describing it as having persisted
    through that restoration would be a claim the ordering does not support.
    """
    with pytest.raises(ValueError):
        wall_persisted_fact(wall_built_tick=wall_built_tick)


def test_a_wall_built_one_tick_earlier_qualifies() -> None:
    """The boundary case on the permitted side."""
    assert wall_persisted_fact(wall_built_tick=249).details["wall_built_tick"] == 249


# --- Documents --------------------------------------------------------------


def test_a_fact_round_trips_through_its_document() -> None:
    """Serialization keeps every field, and rebuilding recomputes the derived ones."""
    for fact in (wall_built_fact(), wall_persisted_fact()):
        assert MemoryFact.from_document(fact.to_document()) == fact


def test_a_document_carries_exactly_the_persisted_keys() -> None:
    """The stored shape is fixed, which is what makes an extra key detectable."""
    assert sorted(wall_built_fact().to_document()) == [
        "details",
        "episode",
        "fact_id",
        "fact_type",
        "source_event_index",
        "source_event_type",
        "source_id",
        "subject_ids",
        "summary",
        "tick",
    ]


def test_a_document_recording_the_wrong_fact_id_is_refused() -> None:
    """The stored identifier is a claim to check, not data to load."""
    document = wall_built_fact().to_document()
    document["fact_id"] = "fact_" + "0" * 64
    with pytest.raises(ValueError):
        MemoryFact.from_document(document)


def test_a_document_recording_the_wrong_summary_is_refused() -> None:
    """Wording is derived, so a rewritten summary means a tampered file."""
    document = wall_built_fact().to_document()
    document["summary"] = "Something else entirely happened."
    with pytest.raises(ValueError):
        MemoryFact.from_document(document)


def test_a_document_whose_details_were_edited_is_refused() -> None:
    """Editing content without rewriting the identifier breaks the hash."""
    document = wall_built_fact().to_document()
    document["details"]["boundary_id"] = "boundary_elsewhere"
    document["subject_ids"] = sorted({"boundary_elsewhere", "district_a", "district_b", WALL_ID})
    with pytest.raises(ValueError):
        MemoryFact.from_document(document)


@pytest.mark.parametrize("key", ["details", "episode", "fact_id", "summary", "tick"])
def test_a_document_missing_a_key_is_refused(key: str) -> None:
    """An incomplete document is never completed by assumption."""
    document = wall_built_fact().to_document()
    del document[key]
    with pytest.raises(ValueError):
        MemoryFact.from_document(document)


def test_a_document_with_an_extra_key_is_refused() -> None:
    """An unrecognized key may be carrying meaning this build would ignore."""
    document = wall_built_fact().to_document()
    document["surprise"] = 1
    with pytest.raises(ValueError):
        MemoryFact.from_document(document)


@pytest.mark.parametrize("bad", ["MOON_LANDING", "", 1, None])
def test_a_document_naming_an_unknown_fact_type_is_refused(bad: object) -> None:
    """An unknown type cannot be guessed into a known one."""
    document = wall_built_fact().to_document()
    document["fact_type"] = bad
    with pytest.raises((TypeError, ValueError)):
        MemoryFact.from_document(document)


def test_a_document_naming_an_unknown_source_event_type_is_refused() -> None:
    """The same rule for the event vocabulary."""
    document = wall_built_fact().to_document()
    document["source_event_type"] = "MOON_LANDING"
    with pytest.raises(ValueError):
        MemoryFact.from_document(document)


def test_a_document_whose_subjects_are_not_a_list_is_refused() -> None:
    """Subjects persist as a JSON array."""
    document = wall_built_fact().to_document()
    document["subject_ids"] = {"a": 1}
    with pytest.raises(TypeError):
        MemoryFact.from_document(document)


def test_the_identity_document_excludes_the_derived_fields() -> None:
    """Including them would make identity circular."""
    document = wall_built_fact().identity_document()
    assert "fact_id" not in document
    assert "summary" not in document


def test_a_document_survives_a_real_json_round_trip() -> None:
    """Nothing in a fact depends on Python types JSON cannot carry."""
    for fact in (wall_built_fact(), wall_persisted_fact()):
        decoded = json.loads(json.dumps(fact.to_document(), allow_nan=False))
        assert MemoryFact.from_document(decoded) == fact


def test_a_negative_zero_detail_survives_intact() -> None:
    """The sign is part of the stored number."""
    fact = wall_built_fact(payload={"value": -0.0})
    assert math.copysign(1.0, fact.details["source_event_payload"]["value"]) == -1.0


# --- Derived fields are compared as exact strings ---------------------------
#
# ``fact_id`` and ``summary`` are recomputed and compared with what a document
# records. A ``str`` subclass compares equal to the recomputed value, so the
# comparison alone would accept one -- and the fact would then carry a value that
# is not the ``str`` a save may hold.


class StringSubclass(str):
    """A ``str`` subclass: equal to a plain string, and not one."""


def test_the_subclass_passes_every_comparison_a_plain_string_would() -> None:
    """Guards the technique used by the two tests below."""
    document = wall_built_fact().to_document()
    copied = StringSubclass(document["fact_id"])

    assert copied == document["fact_id"]
    assert hash(copied) == hash(document["fact_id"])
    assert type(copied) is not str


def test_a_fact_id_of_a_string_subclass_is_refused() -> None:
    """Exactness is checked before the value is compared."""
    document = wall_built_fact().to_document()
    document["fact_id"] = StringSubclass(document["fact_id"])

    with pytest.raises(TypeError):
        MemoryFact.from_document(document)


def test_a_summary_of_a_string_subclass_is_refused() -> None:
    """The same rule for the derived wording."""
    document = wall_built_fact().to_document()
    document["summary"] = StringSubclass(document["summary"])

    with pytest.raises(TypeError):
        MemoryFact.from_document(document)


@pytest.mark.parametrize("key", ["fact_id", "summary"])
@pytest.mark.parametrize("bad", [None, 1, True, b"bytes", ["text"]])
def test_a_derived_field_of_the_wrong_type_is_refused(key: str, bad: object) -> None:
    """Neither field is coerced into a string before being checked."""
    document = wall_built_fact().to_document()
    document[key] = bad

    with pytest.raises(TypeError):
        MemoryFact.from_document(document)


def test_plain_derived_strings_still_load() -> None:
    """The control case for the exactness checks above."""
    fact = wall_built_fact()
    restored = MemoryFact.from_document(fact.to_document())

    assert type(restored.fact_id) is str
    assert type(restored.summary) is str
    assert restored == fact
