"""Deriving an Episode Narration Plan from a story, a direction and an export.

The derivation is a pure function of its inputs. It reads no clock, draws no
randomness, consults no filesystem path, calls no model, opens no socket, and
depends on no iteration order that Python is free to vary. The same three
documents always produce the same bytes.

What it decides is wording, and only within a closed table. What it never
decides is what mattered, what is framed, or what is true. Emphasis is copied
from Phase 21 and never recomputed. Visibility is copied from Phase 22 and never
re-judged: a beat is shown here because a shot cites it there, and unshown here
because the shot plan says so and gives its reason. Sentences either restate the
memory layer's own recorded summary verbatim or come from the versioned template
table, and nothing in this module branches on the content of either.

The three documents must belong together, and that is checked before a single
sentence is composed. A story plan names the export it read by digest; a shot
plan names the story it directs by digest. Deriving from a triple that does not
join would produce a plan whose every field validated and whose every sentence
was about a different episode.
"""

from typing import Final, cast

from living_diorama.cinematic import validate_shot_direction_plan
from living_diorama.narration.narration_facts import fact_summary_for_evidence
from living_diorama.narration.narration_schema_v1 import (
    NARRATION_PLAN_FORMAT,
    NARRATION_SCHEMA_VERSION,
    UNIT_ID_FORM,
    JsonValue,
    validate_episode_narration_plan,
)
from living_diorama.narration.narration_spec import (
    PARAM_TICK,
    TEMPLATE_PARAMETERS_BY_KIND,
    TEXT_SOURCE_MEMORY_FACT_SUMMARY,
    VISIBILITY_SHOWN,
    VISIBILITY_UNSHOWN,
    forbidden_wording_hit,
    render_narration_text,
    text_source_for_kind,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.render.render_schema_v1 import validate_render_export
from living_diorama.story import validate_episode_story_plan

EVIDENCE_EVENT: Final = "event"
EVIDENCE_MEMORY_FACT: Final = "memory_fact"
"""Phase 21's evidence kinds, restated to select without importing its internals."""

__all__ = [
    "build_episode_narration_plan_bytes",
    "build_episode_narration_plan_document",
]


def _document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    return cast(dict[str, JsonValue], value)


def _evidence_of_kind(beat: dict[str, JsonValue], kind: str) -> list[dict[str, JsonValue]]:
    evidence = cast(list[dict[str, JsonValue]], beat["evidence"])
    return [entry for entry in evidence if entry["kind"] == kind]


def _require_join(
    story: dict[str, JsonValue],
    shot_plan: dict[str, JsonValue],
    export: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Prove the three documents describe one episode, and return the binding.

    Digest equality is the load-bearing check in both directions: the story plan
    already recorded which export document it read, and the shot plan already
    recorded which story plan it directs, so a narration layer never has to
    decide whether three files "look like" the same episode. It asks each
    document what it bound and compares.

    Raises:
        ValueError: If any binding does not hold.
    """
    story_source = _document(story["source"], "episode story plan source")
    story_current = _document(story_source["current"], "episode story plan source current")
    shot_source = _document(shot_plan["source"], "shot direction plan source")

    story_digest = sha256_hex(dumps_canonical(story, "episode story plan"))
    shot_digest = sha256_hex(dumps_canonical(shot_plan, "shot direction plan"))
    export_digest = sha256_hex(dumps_canonical(export, "render export"))

    if export_digest != story_current["document_sha256"]:
        raise ValueError(
            f"the offered render export hashes to {export_digest}, but the story plan was "
            f"derived from export {story_current['document_sha256']}; the sentences this "
            "narration would carry come from a document the story never read"
        )
    if shot_source["story_plan_sha256"] != story_digest:
        raise ValueError(
            f"the shot direction plan directs story plan {shot_source['story_plan_sha256']}, "
            f"but the offered story plan hashes to {story_digest}; these two plans are not "
            "about the same story"
        )
    if shot_source["mode"] != story_source["mode"]:
        raise ValueError(
            f"the shot direction plan is {shot_source['mode']!r} mode but the story plan is "
            f"{story_source['mode']!r} mode"
        )
    if shot_source["episode"] != story_current["episode"]:
        raise ValueError(
            f"the shot direction plan describes episode {shot_source['episode']} but the "
            f"story plan describes episode {story_current['episode']}"
        )

    previous_episode: JsonValue = None
    if story_source["mode"] != "baseline":
        story_previous = _document(story_source["previous"], "episode story plan source previous")
        previous_episode = story_previous["episode"]
    if shot_source["previous_episode"] != previous_episode:
        raise ValueError(
            f"the shot direction plan follows episode {shot_source['previous_episode']!r} but "
            f"the story plan follows episode {previous_episode!r}"
        )

    return {
        "current_export_sha256": export_digest,
        "episode": story_current["episode"],
        "mode": story_source["mode"],
        "previous_episode": previous_episode,
        "shot_plan_sha256": shot_digest,
        "shot_schema_version": shot_plan["schema_version"],
        "story_plan_sha256": story_digest,
        "story_schema_version": story["schema_version"],
    }


def _visibility_index(
    shot_plan: dict[str, JsonValue],
) -> dict[str, dict[str, JsonValue]]:
    """Map every beat the shot plan accounts for to its visibility facts.

    Phase 22's own contract already guarantees each beat appears once, in one
    place. This index is built without assuming it: a beat claimed twice is
    refused here rather than resolved to whichever entry was read last.
    """
    index: dict[str, dict[str, JsonValue]] = {}

    def _claim(beat_id: str, record: dict[str, JsonValue]) -> None:
        if beat_id in index:
            raise ValueError(
                f"the shot direction plan accounts for beat {beat_id!r} more than once; a "
                "beat is shown exactly once or recorded unshown exactly once"
            )
        index[beat_id] = record

    for shot in cast(list[dict[str, JsonValue]], shot_plan["shots"]):
        for beat_id in cast(list[str], shot["source_beat_ids"]):
            _claim(
                beat_id,
                {
                    "end_frame": shot["end_frame"],
                    "shot_id": shot["shot_id"],
                    "start_frame": shot["start_frame"],
                    "unshown_reason": None,
                    "visibility": VISIBILITY_SHOWN,
                },
            )
    for entry in cast(list[dict[str, JsonValue]], shot_plan["unshown"]):
        _claim(
            cast(str, entry["beat_id"]),
            {
                "end_frame": None,
                "shot_id": None,
                "start_frame": None,
                "unshown_reason": entry["reason_code"],
                "visibility": VISIBILITY_UNSHOWN,
            },
        )
    return index


def _narration_text(
    beat: dict[str, JsonValue],
    export: dict[str, JsonValue],
    description: str,
) -> tuple[str, str, JsonValue]:
    """Return the sentence for one beat, its source, and the fact id behind it."""
    kind = cast(str, beat["kind"])
    source = text_source_for_kind(kind)
    subjects = cast(list[str], beat["subject_ids"])

    if source == TEXT_SOURCE_MEMORY_FACT_SUMMARY:
        facts = _evidence_of_kind(beat, EVIDENCE_MEMORY_FACT)
        if len(facts) != 1:
            raise ValueError(
                f"{description} is a {kind} beat narrated by restating a recorded summary, "
                f"so it cites exactly one memory fact; it cites {len(facts)}"
            )
        evidence = facts[0]
        text = fact_summary_for_evidence(export, evidence, description)
        hit = forbidden_wording_hit(text)
        if hit is not None:
            raise ValueError(
                f"{description} would carry the summary of memory fact "
                f"{evidence['fact_id']!r}, which uses {hit!r}; this layer restates a "
                "recorded sentence or it refuses -- it never rewords one into something "
                "it is willing to publish"
            )
        return text, source, evidence["fact_id"]

    tick = 0
    if PARAM_TICK in TEMPLATE_PARAMETERS_BY_KIND[kind]:
        events = _evidence_of_kind(beat, EVIDENCE_EVENT)
        if len(events) != 1:
            raise ValueError(
                f"{description} is a {kind} beat whose sentence records the tick of the "
                f"event that raised it, so it cites exactly one event; it cites "
                f"{len(events)}"
            )
        tick = cast(int, events[0]["tick"])
    elif beat["evidence"]:
        raise ValueError(
            f"{description} is a {kind} beat whose sentence takes no parameters, but it "
            "cites evidence; that beat reports an absence and cites nothing"
        )
    return render_narration_text(kind, subjects, tick), source, None


def build_episode_narration_plan_document(
    story_plan: object, shot_plan: object, current_export: object
) -> dict[str, JsonValue]:
    """Return the Episode Narration Plan document for one directed episode.

    Args:
        story_plan: The Episode Story Plan V1 whose beats are restated.
        shot_plan: The Shot Direction Plan V1 that directed them.
        current_export: The Render Export V1 the story plan was derived from,
            which carries the memory sentences the fact-backed beats restate.

    Returns:
        A validated Episode Narration Plan V1 document.

    Raises:
        TypeError: If any input has the wrong shape.
        ValueError: If any input fails its own contract, if the three do not
            join, if the shot plan leaves a beat unaccounted for, if a cited
            memory fact does not resolve and agree with its evidence, or if a
            sentence would make a causal or visual claim.
    """
    story = validate_episode_story_plan(story_plan)
    shots = validate_shot_direction_plan(shot_plan)
    export = cast(dict[str, JsonValue], validate_render_export(current_export))

    source = _require_join(story, shots, export)
    visibility = _visibility_index(shots)

    units: list[JsonValue] = []
    narrated: set[str] = set()
    shown = 0
    for position, beat in enumerate(cast(list[dict[str, JsonValue]], story["beats"]), start=1):
        beat_id = cast(str, beat["beat_id"])
        narrated.add(beat_id)
        description = f"episode narration plan units[{position - 1}]"

        framing = visibility.get(beat_id)
        if framing is None:
            raise ValueError(
                f"{description} restates beat {beat_id!r}, which the shot direction plan "
                "neither shows nor records as unshown; narration reports the direction it "
                "was given and never decides visibility for itself"
            )
        text, text_source, fact_id = _narration_text(beat, export, description)
        if framing["visibility"] == VISIBILITY_SHOWN:
            shown += 1

        units.append(
            {
                "beat_id": beat_id,
                "emphasis": beat["emphasis"],
                "end_frame": framing["end_frame"],
                "fact_id": fact_id,
                "kind": beat["kind"],
                "shot_id": framing["shot_id"],
                "start_frame": framing["start_frame"],
                "subject_ids": list(cast(list[str], beat["subject_ids"])),
                "text": text,
                "text_source": text_source,
                "unit_id": UNIT_ID_FORM % position,
                "unshown_reason": framing["unshown_reason"],
                "visibility": framing["visibility"],
            }
        )

    unaccounted = sorted(set(visibility) - narrated)
    if unaccounted:
        raise ValueError(
            f"the shot direction plan accounts for beats {unaccounted}, which the story "
            "plan does not hold; narration restates the story it was given and invents no "
            "beat"
        )

    document: dict[str, JsonValue] = {
        "accounting": {
            "beats_total": len(units),
            "units_shown": shown,
            "units_unshown": len(units) - shown,
        },
        "format": NARRATION_PLAN_FORMAT,
        "schema_version": NARRATION_SCHEMA_VERSION,
        "source": source,
        "units": units,
    }
    return validate_episode_narration_plan(document)


def build_episode_narration_plan_bytes(
    story_plan: object, shot_plan: object, current_export: object
) -> bytes:
    """Return the canonical Episode Narration Plan bytes for the given sources.

    The returned bytes are the one canonical encoding of the plan: sorted keys,
    tight separators, no non-finite floats, and exactly one trailing newline.
    """
    document = build_episode_narration_plan_document(story_plan, shot_plan, current_export)
    return dumps_canonical(document, "episode narration plan")
