"""Dereferencing the memory fact whose sentence a narration unit carries.

Phase 21 cites a durable fact structurally: a beat's evidence names the
``fact_id``, its type, its episode, its tick and its subject, and deliberately
does **not** carry the fact's prose. That is the right boundary for a layer that
must never branch on wording -- and it leaves the sentence itself one hop away,
in the render export the story plan binds by digest.

This module takes that hop, and takes it suspiciously. A fact reached by
identifier is not thereby the fact the beat cites: every field the evidence
already stated is checked against the fact that answered to the name, so a
mutated export cannot substitute one record's sentence for another's. The
summary is then carried **verbatim**. Nothing here rewords, truncates,
re-punctuates or normalises it: the memory layer wrote that sentence as a
template precisely so a later narration phase would read a stable, checkable
string, and editing it would replace what the world recorded with what this
layer preferred.

This layer never imports ``living_diorama.memory``. It reads memory facts *as
exported*, through the render contract, exactly as the story layer does -- a
second opinion about what durable memory is would be a second authority.
"""

from typing import Final, cast

from living_diorama.persistence.schema.world_schema_v1 import require_text
from living_diorama.story.story_facts import require_fact_shape

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

SUMMARY_KEY: Final = "summary"
"""The export field holding the memory layer's own sentence about a fact."""

EVIDENCE_AGREEMENT_FIELDS: Final = ("episode", "fact_type", "source_id", "tick")
"""Every field a beat's fact evidence states that the fact itself must confirm.

``fact_id`` is excluded because it is the lookup key, not a claim to re-check:
the fact was found *by* it.
"""

__all__ = [
    "EVIDENCE_AGREEMENT_FIELDS",
    "SUMMARY_KEY",
    "fact_summary_for_evidence",
    "resolve_fact",
]


def _document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    return cast(dict[str, JsonValue], value)


def _facts(export: dict[str, JsonValue]) -> list[JsonValue]:
    memory = _document(export.get("memory"), "render export memory")
    entries = memory.get("facts")
    if type(entries) is not list:
        raise TypeError("render export memory facts must be a list")
    return entries


def resolve_fact(
    export: dict[str, JsonValue], fact_id: str, description: str
) -> dict[str, JsonValue]:
    """Return the one exported fact carrying this identifier.

    Args:
        export: The verified current render export the story plan binds.
        fact_id: The identifier a beat's evidence cites.
        description: What is being resolved, used in error messages.

    Returns:
        The fact document, proven structurally sound.

    Raises:
        TypeError: If the export or the fact has the wrong shape.
        ValueError: If no fact answers to the identifier, or if more than one
            does. A repeated identifier is refused rather than resolved to the
            first or the last: durable memory guarantees unique fact ids, so an
            export carrying two did not come from the engine, and picking one
            would narrate a record nobody chose.
    """
    matches = [
        _document(entry, f"{description} candidate")
        for entry in _facts(export)
        if type(entry) is dict and entry.get("fact_id") == fact_id
    ]
    if not matches:
        raise ValueError(
            f"{description} cites memory fact {fact_id!r}, which the bound render export "
            "does not carry; a narration sentence is never written for a record the "
            "export cannot produce"
        )
    if len(matches) > 1:
        raise ValueError(
            f"{description} cites memory fact {fact_id!r}, which the bound render export "
            f"carries {len(matches)} times; durable memory ids are unique, so this export "
            "did not come from the engine"
        )
    return require_fact_shape(matches[0], description)


def fact_summary_for_evidence(
    export: dict[str, JsonValue], evidence: dict[str, JsonValue], description: str
) -> str:
    """Return the exported sentence for the fact a beat cites, verbatim.

    The fact is looked up by ``fact_id`` and then made to agree with every other
    claim the evidence already made about it. Only then is its summary read.

    Args:
        export: The verified current render export the story plan binds.
        evidence: The beat's memory-fact evidence entry.
        description: What is being narrated, used in error messages.

    Returns:
        The fact's ``summary`` exactly as the export carries it.

    Raises:
        TypeError: If the export, the fact, or the summary has the wrong type.
        ValueError: If the fact is missing, duplicated, disagrees with the
            evidence, or carries no usable sentence.
    """
    fact_id = require_text(evidence.get("fact_id"), f"{description} evidence fact_id")
    fact = resolve_fact(export, fact_id, description)

    for field in EVIDENCE_AGREEMENT_FIELDS:
        cited = evidence.get(field)
        recorded = fact.get(field)
        if cited != recorded or type(cited) is not type(recorded):
            raise ValueError(
                f"{description} cites memory fact {fact_id!r} with {field} {cited!r}, but "
                f"the exported fact records {recorded!r}; the sentence this beat would "
                "carry belongs to a different record than the one it names"
            )

    if SUMMARY_KEY not in fact:
        raise ValueError(
            f"{description} resolves memory fact {fact_id!r}, which carries no "
            f"{SUMMARY_KEY!r}; this beat is narrated by restating the sentence the world "
            "recorded, and there is none to restate"
        )
    return require_text(fact[SUMMARY_KEY], f"{description} memory fact {fact_id} summary")
