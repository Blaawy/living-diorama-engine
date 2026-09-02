"""Deriving an Episode Language Realization Plan from its three sources.

The derivation is a pure function of its inputs. It reads no clock, draws no
randomness, consults no filesystem path, calls no model, opens no socket, and
depends on no iteration order that Python is free to vary. The same three
documents always produce the same bytes.

What it decides is human-facing wording, and only within the closed reviewed
policy. What it never decides is what mattered, what is framed, what is true,
or when anything is heard. Every atom a sentence speaks -- the entity, the
predicate, the tick, the relation -- is proven from the story plan's
structured evidence, the export's actual events and facts, and the world's
own entity records. The narration plan contributes identity and order; its
sentences are provenance history this module never reads, so a lying source
sentence over unchanged structure cannot move a single realized byte.

The wording register is a parameter of the derivation, not an input document:
``v1`` (the default) reproduces today's bytes exactly, and ``v2`` composes the
same atoms under the second reviewed table. The register the derivation used
is written into the plan it produces, so a reader never has to guess which
table a sentence came from. A ``v2`` plan additionally carries, on every
record, the binding the sentence is grounded in -- its category, the memory
fact it restates (when it restates one) and the export event index it cites --
and a top-level ``viewer_guidance`` list selected deterministically from the
world export.

The three documents must belong together, and that is checked before a single
sentence is composed. A narration plan names the story it restates and the
export it carried sentences from by digest; a story plan names the export it
read by digest. Deriving from a triple that does not join would produce a plan
whose every field validated and whose every sentence was about a different
episode.
"""

from typing import cast

from living_diorama.language_realization.realization_atoms import (
    EVIDENCE_EVENT,
    EVIDENCE_MEMORY_FACT,
    realized_text_for_beat,
)
from living_diorama.language_realization.realization_guidance import select_viewer_guidance
from living_diorama.language_realization.realization_schema_v1 import (
    JsonValue,
    validate_episode_language_realization_plan,
)
from living_diorama.language_realization.realization_spec import (
    REALIZATION_ID_FORM,
    REALIZATION_PLAN_FORMAT,
    REALIZATION_POLICY_V1,
    REALIZATION_SCHEMA_VERSION,
    WORDING_PROFILE_V1,
    require_wording_profile,
)
from living_diorama.narration import validate_episode_narration_plan
from living_diorama.narration.narration_spec import (
    TEXT_SOURCE_MEMORY_FACT_SUMMARY,
    text_source_for_kind,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.render.render_schema_v1 import validate_render_export
from living_diorama.story import validate_episode_story_plan

__all__ = [
    "build_episode_language_realization_plan_bytes",
    "build_episode_language_realization_plan_document",
]


def _document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    return cast(dict[str, JsonValue], value)


def _require_join(
    narration: dict[str, JsonValue],
    story: dict[str, JsonValue],
    export: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Prove the three documents describe one episode, and return the binding.

    Digest equality is the load-bearing check in every direction: the
    narration plan already recorded which story plan it restates and which
    export it carried sentences from, and the story plan already recorded
    which export it read, so a realization layer never has to decide whether
    three files "look like" the same episode. It asks each document what it
    bound and compares.

    Raises:
        ValueError: If any binding or identity does not hold.
    """
    narration_source = _document(narration["source"], "episode narration plan source")
    story_source = _document(story["source"], "episode story plan source")
    story_current = _document(story_source["current"], "episode story plan source current")

    narration_digest = sha256_hex(dumps_canonical(narration, "episode narration plan"))
    story_digest = sha256_hex(dumps_canonical(story, "episode story plan"))
    export_digest = sha256_hex(dumps_canonical(export, "render export"))

    if narration_source["story_plan_sha256"] != story_digest:
        raise ValueError(
            f"the narration plan restates story plan {narration_source['story_plan_sha256']}, "
            f"but the offered story plan hashes to {story_digest}; these two plans are not "
            "about the same story"
        )
    if narration_source["current_export_sha256"] != export_digest:
        raise ValueError(
            f"the narration plan carried sentences from export "
            f"{narration_source['current_export_sha256']}, but the offered render export "
            f"hashes to {export_digest}; the structure this realization would prove against "
            "is not the document the narration read"
        )
    if export_digest != story_current["document_sha256"]:
        raise ValueError(
            f"the offered render export hashes to {export_digest}, but the story plan was "
            f"derived from export {story_current['document_sha256']}; the atoms this "
            "realization would speak come from a document the story never read"
        )
    if narration_source["mode"] != story_source["mode"]:
        raise ValueError(
            f"the narration plan is {narration_source['mode']!r} mode but the story plan "
            f"is {story_source['mode']!r} mode"
        )
    if narration_source["episode"] != story_current["episode"]:
        raise ValueError(
            f"the narration plan describes episode {narration_source['episode']} but the "
            f"story plan describes episode {story_current['episode']}"
        )

    previous_episode: JsonValue = None
    if story_source["mode"] != "baseline":
        story_previous = _document(story_source["previous"], "episode story plan source previous")
        previous_episode = story_previous["episode"]
    if narration_source["previous_episode"] != previous_episode:
        raise ValueError(
            f"the narration plan follows episode {narration_source['previous_episode']!r} "
            f"but the story plan follows episode {previous_episode!r}"
        )

    return {
        "current_export_sha256": export_digest,
        "episode": narration_source["episode"],
        "mode": narration_source["mode"],
        "narration_plan_sha256": narration_digest,
        "narration_schema_version": narration["schema_version"],
        "previous_episode": narration_source["previous_episode"],
        "story_plan_sha256": story_digest,
        "story_schema_version": story["schema_version"],
    }


def _require_unit_beat_agreement(
    unit: dict[str, JsonValue],
    beat: dict[str, JsonValue],
    position: int,
) -> str:
    """Verify a unit restates its positional beat exactly, and return the kind.

    For a fact-backed unit this includes ancestry: the unit's own ``fact_id``
    must name the very memory fact the beat's evidence cites, so a
    standalone-valid narration cannot borrow the beat's sentence for a
    different record.

    Raises:
        ValueError: If the unit and the beat disagree about identity, kind,
            subjects, emphasis, the text-source classification the kind
            demands, or the fact the sentence is about.
    """
    label = f"episode narration plan units[{position - 1}]"
    if unit["beat_id"] != beat["beat_id"]:
        raise ValueError(
            f"{label} restates beat {unit['beat_id']!r}, but the story plan holds "
            f"{beat['beat_id']!r} at that position; realization follows the story's own "
            "order"
        )
    for field in ("kind", "subject_ids", "emphasis"):
        if unit[field] != beat[field]:
            raise ValueError(
                f"{label} declares {field} {unit[field]!r}, but beat {beat['beat_id']!r} "
                f"holds {beat[field]!r}; a realization restates the story's own record "
                "and never re-decides it"
            )
    kind = cast(str, unit["kind"])
    expected_source = text_source_for_kind(kind)
    if unit["text_source"] != expected_source:
        raise ValueError(
            f"{label} declares text_source {unit['text_source']!r}, but a {kind} beat is "
            f"narrated from {expected_source!r}; the classification is the kind's, never "
            "a free label"
        )
    if expected_source == TEXT_SOURCE_MEMORY_FACT_SUMMARY:
        cited = [
            entry
            for entry in cast(list[dict[str, JsonValue]], beat["evidence"])
            if entry["kind"] == EVIDENCE_MEMORY_FACT
        ]
        if len(cited) != 1:
            raise ValueError(
                f"beat {beat['beat_id']!r} is narrated from a recorded fact, so it cites "
                f"exactly one memory fact; it cites {len(cited)}"
            )
        unit_fact = unit["fact_id"]
        beat_fact = cited[0]["fact_id"]
        if unit_fact != beat_fact or type(unit_fact) is not type(beat_fact):
            raise ValueError(
                f"{label} names memory fact {unit_fact!r}, but beat {beat['beat_id']!r} "
                f"cites {beat_fact!r}; the sentence and the story's evidence are about "
                "one record"
            )
    return kind


def _event_index_for_beat(
    beat: dict[str, JsonValue],
    description: str,
) -> JsonValue:
    """Return the export event index a beat's evidence cites, or ``None``.

    An event-derived or fact-derived beat cites exactly one event; an absence
    beat cites none. The index is the beat's own claim, which the atoms layer
    proves against the actual export event before any sentence is composed.
    """
    indices = [
        cast(int, entry["index"])
        for entry in cast(list[dict[str, JsonValue]], beat["evidence"])
        if entry["kind"] == EVIDENCE_EVENT
    ]
    if not indices:
        return None
    if len(indices) != 1:
        raise ValueError(
            f"{description} cites {len(indices)} events; a beat names exactly one event or none"
        )
    return indices[0]


def build_episode_language_realization_plan_document(
    narration_plan: object,
    story_plan: object,
    current_export: object,
    *,
    wording_profile: str = WORDING_PROFILE_V1,
) -> dict[str, JsonValue]:
    """Return the Episode Language Realization Plan document for one episode.

    Args:
        narration_plan: The Episode Narration Plan V1 whose units are realized.
        story_plan: The Episode Story Plan V1 whose structured evidence
            licenses every spoken atom.
        current_export: The Render Export V1 whose events, facts and world
            entities every claim and label is proven against.
        wording_profile: The reviewed register to compose under; ``v1`` (the
            default) reproduces today's derivation byte for byte, and a plan
            written under it carries no ``wording_profile`` field. A ``v2``
            plan records the register it was written under, binds every record
            to its category, fact and event, and carries the deterministic
            viewer guidance selected from the world export.

    Returns:
        A validated Episode Language Realization Plan V1 document.

    Raises:
        TypeError: If any input has the wrong shape.
        ValueError: If any input fails its own contract, if the three do not
            join, if any unit disagrees with its beat, if the wording profile
            is unreviewed, or if any sentence's structural proof fails.
    """
    require_wording_profile(wording_profile, "language realization plan")
    narration = validate_episode_narration_plan(narration_plan)
    story = validate_episode_story_plan(story_plan)
    export = cast(dict[str, JsonValue], validate_render_export(current_export))

    source = _require_join(narration, story, export)

    units = cast(list[dict[str, JsonValue]], narration["units"])
    beats = cast(list[dict[str, JsonValue]], story["beats"])
    if len(units) != len(beats):
        raise ValueError(
            f"the narration plan holds {len(units)} units for a story holding "
            f"{len(beats)} beats; every beat is realized exactly once"
        )

    is_v2 = wording_profile != WORDING_PROFILE_V1
    realizations: list[JsonValue] = []
    fact_backed = 0
    for position, (unit, beat) in enumerate(zip(units, beats, strict=True), start=1):
        kind = _require_unit_beat_agreement(unit, beat, position)
        description = f"episode story plan beats[{position - 1}]"
        text = realized_text_for_beat(
            kind, beat, export, description, wording_profile=wording_profile
        )
        if text_source_for_kind(kind) == TEXT_SOURCE_MEMORY_FACT_SUMMARY:
            fact_backed += 1
        record: dict[str, JsonValue] = {
            "realization_id": REALIZATION_ID_FORM % position,
            "realized_text": text,
            "unit_id": unit["unit_id"],
        }
        if is_v2:
            record["category"] = "fact"
            record["fact_id"] = unit["fact_id"]
            record["event_id"] = _event_index_for_beat(beat, description)
        realizations.append(record)

    document: dict[str, JsonValue] = {
        "accounting": {
            "fact_backed": fact_backed,
            "realizations_total": len(realizations),
            "template_backed": len(realizations) - fact_backed,
        },
        "format": REALIZATION_PLAN_FORMAT,
        "policy": REALIZATION_POLICY_V1,
        "realizations": realizations,
        "schema_version": REALIZATION_SCHEMA_VERSION,
        "source": source,
    }
    if is_v2:
        document["wording_profile"] = wording_profile
        document["viewer_guidance"] = cast(
            JsonValue, select_viewer_guidance(export, cast(int, source["episode"]))
        )
    return validate_episode_language_realization_plan(document)


def build_episode_language_realization_plan_bytes(
    narration_plan: object,
    story_plan: object,
    current_export: object,
    *,
    wording_profile: str = WORDING_PROFILE_V1,
) -> bytes:
    """Return the canonical Episode Language Realization Plan bytes.

    The returned bytes are the one canonical encoding of the plan: sorted keys,
    tight separators, no non-finite floats, and exactly one trailing newline.
    The ``wording_profile`` argument selects the reviewed register the plan was
    written under, exactly as for the document builder.
    """
    document = build_episode_language_realization_plan_document(
        narration_plan, story_plan, current_export, wording_profile=wording_profile
    )
    return dumps_canonical(document, "language realization plan")
