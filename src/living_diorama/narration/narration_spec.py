"""Phase 24 narration policy: the closed, reviewable wording table.

Narration wording is presentation text, not authoritative world truth. Nothing
in this module decides what happened; it decides only how an already-selected
authoritative record is restated in one deterministic sentence, and it does so
through a finite table a reviewer can read in one sitting.

Two text sources exist, and the difference between them is the whole design.

A fact-backed beat carries the memory layer's own ``summary`` **verbatim**. That
sentence is a template the engine wrote when it recorded the fact, deliberately
so that "a later narration phase reads a stable, checkable string". Rewording it
here would replace a sentence the world wrote about itself with a sentence this
layer invented.

An event-backed beat has no such sentence, so one is composed from the table
below. The parameters are closed and minimal: the beat's sorted subject
identifiers and the tick its authoritative evidence carries. Event payloads are
never read. The story layer refuses to branch on prose or interpret payload
internals, and a narration layer that mined ``payload`` for richer wording would
be asserting detail no upstream contract proved.

Both ban lists below apply to every V1 narration sentence, whatever its source.
This layer publishes the text, so this layer declines to publish a causal claim
or a visual claim -- and it declines by refusing, never by rewording. A carried
summary is never edited to make it acceptable; a summary that could not be
narrated honestly stops the derivation and asks for a human.
"""

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from living_diorama.story import BEAT_KINDS

# --------------------------------------------------------------------------
# Text sources
# --------------------------------------------------------------------------

TEXT_SOURCE_MEMORY_FACT_SUMMARY: Final = "MEMORY_FACT_SUMMARY"
TEXT_SOURCE_NARRATION_TEMPLATE: Final = "NARRATION_TEMPLATE"

TEXT_SOURCES: Final = (TEXT_SOURCE_MEMORY_FACT_SUMMARY, TEXT_SOURCE_NARRATION_TEMPLATE)
"""Exactly the two ways a V1 narration sentence may come to exist."""

# --------------------------------------------------------------------------
# Visibility
# --------------------------------------------------------------------------

VISIBILITY_SHOWN: Final = "SHOWN"
VISIBILITY_UNSHOWN: Final = "UNSHOWN"

VISIBILITY_STATES: Final = (VISIBILITY_SHOWN, VISIBILITY_UNSHOWN)
"""Whether the directed episode frames this beat, as Phase 22 decided it.

Never a judgement of this layer's. A beat is SHOWN because exactly one shot
cites it, and UNSHOWN because the shot plan lists it as unshown with a reason.
"""

UNSHOWN_REASONS: Final = (
    "NOTHING_TO_EMPHASIZE",
    "TRANSITION_BUDGET_EXHAUSTED",
    "NO_FIXED_ANCHOR_WITH_VISUAL_EVIDENCE",
)
"""Phase 22's unshown reason vocabulary, restated rather than imported.

Restated for the same reason Phase 21 restates the memory contract's fact/event
mapping: this layer needs the vocabulary, not the camera package that owns it,
and reaching into ``cinematic_spec`` for three strings would pull anchor, lens
and framing vocabulary into a layer that must never define any. A test asserts
this tuple still agrees with Phase 22's own, so drift fails loudly.
"""

# --------------------------------------------------------------------------
# Which source each beat kind draws its sentence from
# --------------------------------------------------------------------------

TEXT_SOURCE_BY_KIND: Final[Mapping[str, str]] = MappingProxyType(
    {
        "LAW_CHANGE": TEXT_SOURCE_NARRATION_TEMPLATE,
        "LAW_RESTORATION": TEXT_SOURCE_NARRATION_TEMPLATE,
        "WALL_RAISED": TEXT_SOURCE_NARRATION_TEMPLATE,
        "WALL_STATE_CHANGE": TEXT_SOURCE_NARRATION_TEMPLATE,
        "POPULATION_MOVEMENT": TEXT_SOURCE_NARRATION_TEMPLATE,
        "DURABLE_CONSEQUENCE": TEXT_SOURCE_MEMORY_FACT_SUMMARY,
        "CONSEQUENCE_PERSISTED": TEXT_SOURCE_MEMORY_FACT_SUMMARY,
        "NO_EMPHASIZED_BEATS": TEXT_SOURCE_NARRATION_TEMPLATE,
    }
)
"""The text source each Phase 21 beat kind uses.

The two fact-backed kinds are exactly the two the memory layer writes a summary
for, so they restate that summary. Everything else is composed from the table
below. A test proves this mapping is total over Phase 21's ``BEAT_KINDS`` and
names nothing else: an unknown kind must never fall through to a guessed source.
"""

# --------------------------------------------------------------------------
# The template table
# --------------------------------------------------------------------------

PARAM_SUBJECTS: Final = "{subjects}"
PARAM_TICK: Final = "{tick}"

TEMPLATE_PARAMETERS: Final = (PARAM_SUBJECTS, PARAM_TICK)
"""Every placeholder a V1 template may carry, and the whole parameter surface.

Two values, both structural: the beat's own sorted subject identifiers, and the
tick its authoritative evidence records. Nothing else is available to a
template, which is what keeps wording from quietly acquiring detail no upstream
layer proved.
"""

NARRATION_TEMPLATES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "LAW_CHANGE": "At tick {tick}, law {subjects} changed.",
        "LAW_RESTORATION": "At tick {tick}, law {subjects} was restored.",
        "WALL_RAISED": "At tick {tick}, wall {subjects} was built.",
        "WALL_STATE_CHANGE": "At tick {tick}, wall {subjects} changed state.",
        "POPULATION_MOVEMENT": "At tick {tick}, district {subjects} recorded population movement.",
        "NO_EMPHASIZED_BEATS": "No beats were emphasized for this episode.",
    }
)
"""One deterministic sentence per template-backed beat kind.

Each states what the authoritative record states and stops there. The entity
noun in each sentence is the one the engine's own rule table guarantees: a
``LAW_CHANGE`` beat is raised by a ``LAW_CHANGED`` event whose subject is the
law, a ``POPULATION_MOVEMENT`` beat by a ``POPULATION_MIGRATED`` event whose
subject is the district the movement was published by. Where the movement went
and how many moved live in the event payload, which this layer never opens.

``NO_EMPHASIZED_BEATS`` takes no parameters and says only what its beat says:
that the emphasis policy selected nothing. It must never be read, or written, as
a claim that nothing happened -- an episode can publish hundreds of genuine
telemetry events and still emphasise none of them.
"""

TEMPLATE_PARAMETERS_BY_KIND: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "LAW_CHANGE": (PARAM_SUBJECTS, PARAM_TICK),
        "LAW_RESTORATION": (PARAM_SUBJECTS, PARAM_TICK),
        "WALL_RAISED": (PARAM_SUBJECTS, PARAM_TICK),
        "WALL_STATE_CHANGE": (PARAM_SUBJECTS, PARAM_TICK),
        "POPULATION_MOVEMENT": (PARAM_SUBJECTS, PARAM_TICK),
        "NO_EMPHASIZED_BEATS": (),
    }
)
"""The parameters each template declares it uses.

Declared rather than inferred so a test can prove the declaration and the
sentence agree in both directions: a template carrying an undeclared placeholder
is refused, and so is a declaration naming a placeholder the sentence does not
contain.
"""

# --------------------------------------------------------------------------
# Wording safety
# --------------------------------------------------------------------------

CAUSAL_TOKENS: Final = (
    "caused",
    "cause",
    "causes",
    "causing",
    "because",
    "therefore",
    "thus",
    "hence",
    "consequently",
    "led to",
    "leads to",
    "due to",
    "owing to",
    "resulted in",
    "results in",
    "resulting in",
    "responsible for",
    "in response to",
    "so that",
)
"""Words that would assert a causal link the evidence never proved.

The memory layer already refuses to write these into a summary; this layer
refuses to publish them whoever wrote them. Phase 21 keeps causality out of
selection, Phase 22 keeps it out of framing, and this keeps it out of language.
"""

DEIXIS_TOKENS: Final = (
    "see",
    "sees",
    "seen",
    "saw",
    "show",
    "shows",
    "shown",
    "showing",
    "watch",
    "watches",
    "watched",
    "watching",
    "view",
    "views",
    "viewed",
    "viewing",
    "viewer",
    "camera",
    "cameras",
    "frame",
    "frames",
    "framed",
    "framing",
    "screen",
    "screens",
    "onscreen",
    "visible",
    "visibly",
    "visually",
    "depicts",
    "depicted",
    "pictured",
    "footage",
    "image",
    "images",
)
"""Words that would claim the viewer is looking at something.

Whether a beat is on screen is Phase 22's decision and lives in this plan's
``visibility`` field, where a machine can check it against the shot plan. Keeping
it out of the sentence entirely is what makes it structurally impossible for an
UNSHOWN beat -- a durable consequence no approved camera can see -- to be
narrated as though the viewer had just watched it. A sentence cannot fabricate
visibility it has no vocabulary for.
"""

FORBIDDEN_WORDING = re.compile(
    r"(?i)(?<![0-9A-Za-z_])(?:"
    + "|".join(token.replace(" ", r"\s+") for token in (*CAUSAL_TOKENS, *DEIXIS_TOKENS))
    + r")(?![0-9A-Za-z_])"
)
"""The two lists, matched on whole words only.

Underscores count as word characters here as well as letters and digits, so an
identifier such as ``frame_budget_district`` is not a hit while the bare word
``frame`` is. That matters because subject identifiers are substituted into
these sentences: an entity whose name merely contains a banned word must not
make an honest sentence unpublishable.
"""


def forbidden_wording_hit(text: str) -> str | None:
    """Return the banned word a narration sentence uses, or None.

    Args:
        text: The finished sentence, after any substitution.

    Returns:
        The matched word, lowercased, or ``None`` if the sentence is clean.
    """
    match = FORBIDDEN_WORDING.search(text)
    return match.group(0).lower() if match is not None else None


def render_subjects(subject_ids: tuple[str, ...] | list[str]) -> str:
    """Return the subject identifiers as quoted text, in the order given.

    The order is the story plan's, which the Phase 21 contract already proved
    sorted and unique. Sorting again here would hide a plan that had lost that
    property rather than refuse it.
    """
    return ", ".join(f'"{subject}"' for subject in subject_ids)


def render_narration_text(kind: str, subject_ids: tuple[str, ...] | list[str], tick: int) -> str:
    """Return the deterministic sentence for a template-backed beat kind.

    Substitution is explicit and exhaustive: every declared parameter is
    replaced, and the result is checked for any placeholder left behind, so a
    template and its declaration can never silently disagree at derivation time.

    Args:
        kind: The Phase 21 beat kind.
        subject_ids: The beat's subject identifiers, already ordered.
        tick: The tick the beat's authoritative evidence records.

    Returns:
        One sentence.

    Raises:
        KeyError: If the kind has no template, which means this build was asked
            to narrate a beat kind it does not know.
        ValueError: If a placeholder survives substitution.
    """
    text = NARRATION_TEMPLATES[kind]
    declared = TEMPLATE_PARAMETERS_BY_KIND[kind]
    if PARAM_SUBJECTS in declared:
        text = text.replace(PARAM_SUBJECTS, render_subjects(subject_ids))
    if PARAM_TICK in declared:
        text = text.replace(PARAM_TICK, str(tick))
    for parameter in TEMPLATE_PARAMETERS:
        if parameter in text:
            raise ValueError(
                f"narration template for {kind} still carries {parameter} after "
                "substitution; the template and its declared parameters disagree"
            )
    return text


def text_source_for_kind(kind: str) -> str:
    """Return the text source a beat kind draws its sentence from.

    Raises:
        ValueError: If the kind is not one Phase 21 emits. A kind this build
            does not know is never given a guessed source; the derivation stops.
    """
    source = TEXT_SOURCE_BY_KIND.get(kind)
    if source is None:
        raise ValueError(
            f"beat kind {kind!r} has no narration text source; this build narrates "
            f"exactly {sorted(TEXT_SOURCE_BY_KIND)}"
        )
    return source


TEMPLATE_BACKED_KINDS: Final = tuple(
    sorted(
        kind
        for kind, source in TEXT_SOURCE_BY_KIND.items()
        if source == TEXT_SOURCE_NARRATION_TEMPLATE
    )
)
"""Beat kinds whose sentence is composed here."""

FACT_BACKED_KINDS: Final = tuple(
    sorted(
        kind
        for kind, source in TEXT_SOURCE_BY_KIND.items()
        if source == TEXT_SOURCE_MEMORY_FACT_SUMMARY
    )
)
"""Beat kinds whose sentence is the memory layer's own, carried verbatim."""

KNOWN_BEAT_KINDS: Final = tuple(sorted(BEAT_KINDS))
"""Phase 21's beat vocabulary, sorted, for total-coverage assertions."""
