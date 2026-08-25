"""Phase 26 realization policy: the closed, reviewed human-wording rules.

A language realization says each locked narration unit again, for a human ear,
without changing what it means. Everything it is allowed to say is in this
module: one template per supported beat kind, one template per supported
durable-fact type, and one closed label authority that turns entity identity
into human-facing words. There is no other wording path -- a kind or fact type
without a reviewed entry here is refused, never paraphrased.

The policy identifier is part of this contract's schema version exactly as the
Phase 24 wording table is part of its own: changing a template or a label rule
changes what a plan of this version says, so it is a reviewed version change,
never a quiet edit.

Three vocabulary decisions are deliberate. Labels are composed from structured
authority only -- an authoritative name field, a reviewed identifier grammar,
or a relationship read from the world's own records -- so an internal
identifier can never leak into speech by accident. Relationship phrases are
derived from the bound export's structure rather than stored as aliases, so a
label can never quietly contradict the world it describes. And the explicit
label table for entities no rule covers is present but empty: it is the
reviewed home a future entity class would occupy, not a prettifier for
arbitrary identifiers.
"""

import re
import string
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

REALIZATION_PLAN_FORMAT: Final = "living_diorama_episode_language_realization_plan"
"""The format tag every episode language realization plan declares."""

REALIZATION_SCHEMA_VERSION: Final = 1
"""The realization plan schema version this build reads and writes.

Independent from the narration, story, render and persistence schema versions.
The wording tables and label rules in this module are part of this version.
"""

REALIZATION_POLICY_V1: Final = "language_realization_policy_v1"
"""The one realization policy this build derives and validates.

Declared in the document rather than merely implied, so a future plan written
under a revised policy can never be mistaken for this one. The validator
requires the field to equal this constant exactly.
"""

REALIZATION_ID_FORM: Final = "realization_%04d"
"""A realization identifier is positional and nothing else, so it is derivable.

A record sits at the position of the narration unit it realizes, which is the
position of the beat that unit restates. One index carries the whole
one-record-per-unit contract: none missing, none repeated, none invented, none
reordered.
"""

ABSENCE_KIND: Final = "NO_EMPHASIZED_BEATS"
"""Phase 21's empty-result beat kind, restated so this table can name it.

A test asserts the restatement still agrees with the story vocabulary, so
drift fails loudly rather than silently orphaning the entry below.
"""

EVENT_REALIZATION_TEMPLATES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "LAW_CHANGE": "At tick {tick}, {subject_label} changed.",
        "LAW_RESTORATION": "At tick {tick}, {subject_label} was restored.",
        "WALL_RAISED": "At tick {tick}, {subject_label} was built.",
        "WALL_STATE_CHANGE": "At tick {tick}, {subject_label} changed state.",
        "POPULATION_MOVEMENT": "At tick {tick}, {subject_label} recorded population movement.",
        "NO_EMPHASIZED_BEATS": "No beats were emphasized for this episode.",
    }
)
"""One deterministic human-facing sentence per template-backed beat kind.

Each entry says exactly what the Phase 24 sentence for that kind says -- same
event, same entity, same tick -- with the quoted internal identifier replaced
by a reviewed label. ``NO_EMPHASIZED_BEATS`` is carried unchanged: it already
names no entity, and it must never be read, or written, as a claim that
nothing happened.
"""

EVENT_REALIZATION_PARAMETERS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "LAW_CHANGE": ("subject_label", "tick"),
        "LAW_RESTORATION": ("subject_label", "tick"),
        "WALL_RAISED": ("subject_label", "tick"),
        "WALL_STATE_CHANGE": ("subject_label", "tick"),
        "POPULATION_MOVEMENT": ("subject_label", "tick"),
        "NO_EMPHASIZED_BEATS": (),
    }
)
"""The parameters each template declares it uses.

Declared rather than inferred so a test can prove the declaration and the
sentence agree in both directions: a template carrying an undeclared
placeholder is refused, and so is a declaration naming a placeholder the
sentence does not contain.
"""

ENTITY_CLASS_LAW: Final = "law"
ENTITY_CLASS_WALL: Final = "wall"
ENTITY_CLASS_DISTRICT: Final = "district"
"""The world-entity classes a template subject may resolve through."""

SUBJECT_ENTITY_CLASS_BY_KIND: Final[Mapping[str, str]] = MappingProxyType(
    {
        "LAW_CHANGE": ENTITY_CLASS_LAW,
        "LAW_RESTORATION": ENTITY_CLASS_LAW,
        "WALL_RAISED": ENTITY_CLASS_WALL,
        "WALL_STATE_CHANGE": ENTITY_CLASS_WALL,
        "POPULATION_MOVEMENT": ENTITY_CLASS_DISTRICT,
    }
)
"""Which entity class an event-derived beat's single subject belongs to.

The kind decides the class, so a subject identifier is resolved in exactly one
world collection and an identifier that happens to exist elsewhere can never
be labeled as something it is not. The absence kind takes no subject and has
no entry.
"""

FACT_REALIZATION_TEMPLATES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "WALL_BUILT": ("At tick {built_tick}, a permanent wall was built on {boundary_label}."),
        "LAW_RESTORED_WALL_PERSISTED": (
            "At tick {restored_tick}, {law_label} was restored; the permanent wall on "
            "{boundary_label}, built at tick {wall_built_tick}, remained in the world."
        ),
    }
)
"""One deterministic human-facing sentence per supported durable-fact type.

Each entry presents exactly the atoms the memory layer's own recorded summary
presents for that type -- nothing the locked presentation semantics omit, such
as dependency scores or the raw activity flag, is promoted into speech, and
nothing the summary presents is dropped.
"""

FACT_REALIZATION_PARAMETERS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "WALL_BUILT": ("boundary_label", "built_tick"),
        "LAW_RESTORED_WALL_PERSISTED": (
            "boundary_label",
            "law_label",
            "restored_tick",
            "wall_built_tick",
        ),
    }
)
"""The parameters each fact template declares it uses."""

REQUIRED_FACT_DETAILS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "WALL_BUILT": (
            "boundary_id",
            "built_tick",
            "district_a_id",
            "district_b_id",
            "permanent",
            "wall_id",
        ),
        "LAW_RESTORED_WALL_PERSISTED": (
            "boundary_id",
            "law_id",
            "law_name",
            "restored_tick",
            "wall_built_tick",
            "wall_id",
            "wall_permanent",
        ),
    }
)
"""Exactly the structured detail fields each fact realization reads.

Deliberately not the fact's whole detail key set: the memory layer also
records fields its own summary never presents -- dependency scores, raw law
values, the activity flag, and the source event payload -- and this layer
neither names, requires, nor reads them. Reading the payload would assert
detail no locked presentation contract proved.
"""

DISTRICT_ID_PATTERN: Final = re.compile(r"\Adistrict_([a-z])\Z")
"""The one reviewed district-identifier grammar the V1 label rule accepts.

District entities carry no authoritative name field, so their label rests on
this exact grammar and nothing wider. An identifier outside it is refused --
never trimmed, cased, or prettified into a guess.
"""

LAW_NAME_PATTERN: Final = re.compile(r"\A[a-z]+(?:_[a-z]+)*\Z")
"""The one reviewed law-name grammar the V1 label rule accepts.

The law's ``name`` field is authoritative human-readable data, but the label
rule still holds it to an exact shape before speaking it: a name this grammar
does not cover is refused rather than formatted into something unreviewed.
"""

EXPLICIT_LABELS: Final[Mapping[str, str]] = MappingProxyType({})
"""The reviewed explicit label table for entities no rule covers.

Empty in V1: every canonical entity resolves through an authoritative name,
a reviewed grammar, or a structure-derived relationship phrase. The table
exists so a future entity class has a reviewed home -- an entry here is a
version change, and an entity resolving through neither a rule nor an entry
is refused.
"""


def district_label(district_id: str, description: str) -> str:
    """Return the human-facing label for a district identifier.

    Args:
        district_id: The district's world identifier.
        description: What is being labeled, for refusal messages.

    Returns:
        The reviewed display label, e.g. ``District A``.

    Raises:
        ValueError: If the identifier lies outside the reviewed grammar.
    """
    match = DISTRICT_ID_PATTERN.fullmatch(district_id)
    if match is None:
        raise ValueError(
            f"{description} names district {district_id!r}, which the reviewed district "
            "label grammar does not cover; a label is reviewed or it is refused, never "
            "improvised from an identifier"
        )
    letter = match.group(1)
    capital = string.ascii_uppercase[string.ascii_lowercase.index(letter)]
    return f"District {capital}"


def law_label(law_name: str, description: str) -> str:
    """Return the human-facing label for a law, from its authoritative name.

    Args:
        law_name: The law entity's own ``name`` field.
        description: What is being labeled, for refusal messages.

    Returns:
        The reviewed display label, e.g. ``the movement resource sharing law``.

    Raises:
        ValueError: If the name lies outside the reviewed grammar.
    """
    if LAW_NAME_PATTERN.fullmatch(law_name) is None:
        raise ValueError(
            f"{description} names a law called {law_name!r}, which the reviewed law "
            "label grammar does not cover; a label is reviewed or it is refused, never "
            "improvised from a name"
        )
    return "the " + law_name.replace("_", " ") + " law"


def boundary_phrase(district_a_label: str, district_b_label: str) -> str:
    """Return the relationship phrase for a boundary between two districts.

    The endpoints are read from the world's own boundary record by the caller,
    so the phrase can never claim endpoints the bound world disagrees with.
    """
    return f"the boundary between {district_a_label} and {district_b_label}"


def wall_phrase(district_a_label: str, district_b_label: str) -> str:
    """Return the relationship phrase for a wall standing on a boundary.

    The districts are the resolved boundary's own endpoints, reached through
    the wall's boundary reference only after the reciprocal integrity gate has
    proven the boundary claims the wall back.
    """
    return f"the wall between {district_a_label} and {district_b_label}"


def render_event_realization(kind: str, subject_label: str | None, tick: int | None) -> str:
    """Return the realized sentence for a template-backed beat kind.

    Args:
        kind: The beat kind, which must hold a reviewed template.
        subject_label: The resolved subject label, or ``None`` for the
            absence kind, whose sentence names no entity.
        tick: The authoritative event tick, or ``None`` for the absence kind.

    Returns:
        The realized sentence, exactly as the reviewed table composes it.

    Raises:
        ValueError: If the kind has no reviewed template, or the parameters
            offered disagree with the template's declaration.
    """
    template = EVENT_REALIZATION_TEMPLATES.get(kind)
    if template is None:
        raise ValueError(
            f"no reviewed realization template exists for beat kind {kind!r}; an "
            "unreviewed kind is refused, never paraphrased"
        )
    declared = EVENT_REALIZATION_PARAMETERS[kind]
    if not declared:
        if subject_label is not None or tick is not None:
            raise ValueError(
                f"the {kind} template takes no parameters, but a subject or tick was "
                "offered; that beat reports an absence and names nothing"
            )
        return template
    if subject_label is None or tick is None:
        raise ValueError(
            f"the {kind} template declares parameters {list(declared)}, but a subject "
            "or tick is missing; a template is filled completely or not at all"
        )
    return template.format(subject_label=subject_label, tick=tick)


def render_wall_built(built_tick: int, boundary_label: str) -> str:
    """Return the realized sentence for a WALL_BUILT durable fact."""
    return FACT_REALIZATION_TEMPLATES["WALL_BUILT"].format(
        built_tick=built_tick, boundary_label=boundary_label
    )


def render_law_restored_wall_persisted(
    restored_tick: int,
    law_label_text: str,
    boundary_label: str,
    wall_built_tick: int,
) -> str:
    """Return the realized sentence for a LAW_RESTORED_WALL_PERSISTED fact."""
    return FACT_REALIZATION_TEMPLATES["LAW_RESTORED_WALL_PERSISTED"].format(
        restored_tick=restored_tick,
        law_label=law_label_text,
        boundary_label=boundary_label,
        wall_built_tick=wall_built_tick,
    )
