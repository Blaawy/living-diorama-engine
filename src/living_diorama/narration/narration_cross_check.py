"""Cross-validation of an Episode Narration Plan against the documents it names.

:func:`living_diorama.narration.narration_schema_v1.validate_episode_narration_plan`
proves everything a plan can prove about itself. What it cannot prove is that
the plan's claims are *true of its sources*: that the three digests it carries
name the documents actually offered, that every beat the story plan holds is
narrated exactly once, that no beat was invented, that each unit's visibility is
the visibility Phase 22 actually granted, and that each sentence is the sentence
those sources produce. A plan whose SHA fields are syntactically digests is not
thereby source-verified.

This module closes that gap. Given the plan and the three documents it claims to
narrate, it verifies every binding and every per-unit agreement, and then seals
the whole question by re-deriving the plan from those sources: the Episode
Narration Plan contract is a deterministic single-output function of its inputs,
so the one valid plan for a given story, direction and export is the plan the
planner derives. Anything else is refused, named check by named check first so a
failure says which claim stopped being true.
"""

from typing import cast

from living_diorama.cinematic import validate_shot_direction_plan
from living_diorama.narration.narration_facts import fact_summary_for_evidence
from living_diorama.narration.narration_planner import (
    EVIDENCE_EVENT,
    EVIDENCE_MEMORY_FACT,
    build_episode_narration_plan_bytes,
)
from living_diorama.narration.narration_schema_v1 import (
    MODE_BASELINE,
    JsonValue,
    validate_episode_narration_plan,
)
from living_diorama.narration.narration_spec import (
    TEXT_SOURCE_MEMORY_FACT_SUMMARY,
    VISIBILITY_SHOWN,
    VISIBILITY_UNSHOWN,
    render_narration_text,
    text_source_for_kind,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.render.render_schema_v1 import validate_render_export
from living_diorama.story import validate_episode_story_plan

__all__ = ["validate_narration_plan_against_sources"]


def _document(value: object, description: str) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], value)


def _check_bindings(
    source: dict[str, JsonValue],
    story: dict[str, JsonValue],
    shots: dict[str, JsonValue],
    export: dict[str, JsonValue],
) -> None:
    """Verify the plan names the exact documents offered, and that they join."""
    story_digest = sha256_hex(dumps_canonical(story, "episode story plan"))
    shot_digest = sha256_hex(dumps_canonical(shots, "shot direction plan"))
    export_digest = sha256_hex(dumps_canonical(export, "render export"))

    for field, offered, label in (
        ("story_plan_sha256", story_digest, "story plan"),
        ("shot_plan_sha256", shot_digest, "shot direction plan"),
        ("current_export_sha256", export_digest, "render export"),
    ):
        if source[field] != offered:
            raise ValueError(
                f"episode narration plan binds {label} {source[field]!r}, but the offered "
                f"{label}'s canonical bytes hash to {offered!r}; this plan does not "
                f"narrate that document"
            )

    story_source = _document(story["source"], "episode story plan source")
    story_current = _document(story_source["current"], "episode story plan source current")
    if source["current_export_sha256"] != story_current["document_sha256"]:
        raise ValueError(
            f"episode narration plan carries export {source['current_export_sha256']!r}, "
            f"but the story plan it narrates was derived from export "
            f"{story_current['document_sha256']!r}; a narration sentence must come from the "
            "document its own story actually read"
        )

    shot_source = _document(shots["source"], "shot direction plan source")
    if shot_source["story_plan_sha256"] != source["story_plan_sha256"]:
        raise ValueError(
            f"episode narration plan narrates story plan {source['story_plan_sha256']!r} "
            f"under a shot plan that directs {shot_source['story_plan_sha256']!r}; the "
            "direction and the story are not the same episode's"
        )

    if source["story_schema_version"] != story["schema_version"]:
        raise ValueError(
            f"episode narration plan records story schema version "
            f"{source['story_schema_version']}, but the story plan declares "
            f"{story['schema_version']}"
        )
    if source["shot_schema_version"] != shots["schema_version"]:
        raise ValueError(
            f"episode narration plan records shot schema version "
            f"{source['shot_schema_version']}, but the shot plan declares "
            f"{shots['schema_version']}"
        )
    if source["mode"] != story_source["mode"]:
        raise ValueError(
            f"episode narration plan is {source['mode']!r} mode but the story plan is "
            f"{story_source['mode']!r} mode"
        )
    if source["episode"] != story_current["episode"]:
        raise ValueError(
            f"episode narration plan describes episode {source['episode']} but the story "
            f"plan describes episode {story_current['episode']}"
        )
    if story_source["mode"] == MODE_BASELINE:
        if source["previous_episode"] is not None:
            raise ValueError(
                "episode narration plan names a previous episode but the story plan is a baseline"
            )
    else:
        story_previous = _document(story_source["previous"], "episode story plan source previous")
        if source["previous_episode"] != story_previous["episode"]:
            raise ValueError(
                f"episode narration plan names previous episode "
                f"{source['previous_episode']!r} but the story plan transitions from episode "
                f"{story_previous['episode']!r}"
            )


def _visibility_claims(shots: dict[str, JsonValue]) -> dict[str, dict[str, JsonValue]]:
    """Return what the shot plan says about every beat it accounts for."""
    claims: dict[str, dict[str, JsonValue]] = {}
    for shot in cast(list[dict[str, JsonValue]], shots["shots"]):
        for beat_id in cast(list[str], shot["source_beat_ids"]):
            claims[beat_id] = {
                "end_frame": shot["end_frame"],
                "shot_id": shot["shot_id"],
                "start_frame": shot["start_frame"],
                "unshown_reason": None,
                "visibility": VISIBILITY_SHOWN,
            }
    for entry in cast(list[dict[str, JsonValue]], shots["unshown"]):
        claims[cast(str, entry["beat_id"])] = {
            "end_frame": None,
            "shot_id": None,
            "start_frame": None,
            "unshown_reason": entry["reason_code"],
            "visibility": VISIBILITY_UNSHOWN,
        }
    return claims


def _check_unit_against_beat(
    unit: dict[str, JsonValue],
    beat: dict[str, JsonValue],
    export: dict[str, JsonValue],
    label: str,
) -> None:
    """Verify one unit restates its beat, and says only what its sources say."""
    for field in ("kind", "emphasis", "subject_ids"):
        if unit[field] != beat[field]:
            raise ValueError(
                f"{label} declares {field} {unit[field]!r}, but beat "
                f"{beat['beat_id']!r} carries {beat[field]!r}; narration copies the story's "
                "own account of a beat and never restates it differently"
            )

    kind = cast(str, beat["kind"])
    expected_source = text_source_for_kind(kind)
    if unit["text_source"] != expected_source:
        raise ValueError(
            f"{label} claims its sentence came from {unit['text_source']!r}, but a {kind} "
            f"beat is narrated from {expected_source!r}"
        )

    if expected_source == TEXT_SOURCE_MEMORY_FACT_SUMMARY:
        evidence = [
            entry
            for entry in cast(list[dict[str, JsonValue]], beat["evidence"])
            if entry["kind"] == EVIDENCE_MEMORY_FACT
        ]
        if len(evidence) != 1:
            raise ValueError(
                f"{label} restates a {kind} beat citing {len(evidence)} memory facts; that "
                "kind cites exactly one"
            )
        if unit["fact_id"] != evidence[0]["fact_id"]:
            raise ValueError(
                f"{label} names memory fact {unit['fact_id']!r}, but beat "
                f"{beat['beat_id']!r} cites {evidence[0]['fact_id']!r}; the sentence and "
                "the evidence must be about one record"
            )
        recorded = fact_summary_for_evidence(export, evidence[0], label)
        if unit["text"] != recorded:
            raise ValueError(
                f"{label} carries text {unit['text']!r}, but memory fact "
                f"{unit['fact_id']!r} records {recorded!r}; a carried summary is restated "
                "verbatim or it is not a carried summary"
            )
        return

    if unit["fact_id"] is not None:
        raise ValueError(
            f"{label} names memory fact {unit['fact_id']!r}, but a {kind} beat's sentence "
            "is composed from the template table and no memory fact wrote it"
        )
    tick = 0
    events = [
        entry
        for entry in cast(list[dict[str, JsonValue]], beat["evidence"])
        if entry["kind"] == EVIDENCE_EVENT
    ]
    if events:
        tick = cast(int, events[0]["tick"])
    expected = render_narration_text(kind, cast(list[str], beat["subject_ids"]), tick)
    if unit["text"] != expected:
        raise ValueError(
            f"{label} carries text {unit['text']!r}, but the versioned template for a "
            f"{kind} beat produces {expected!r}; a composed sentence is the table's "
            "sentence or it was written by something this contract does not describe"
        )


def validate_narration_plan_against_sources(
    narration_plan: object, story_plan: object, shot_plan: object, current_export: object
) -> dict[str, JsonValue]:
    """Verify an Episode Narration Plan against its actual sources, and return it.

    Args:
        narration_plan: The Episode Narration Plan V1 document to verify.
        story_plan: The Episode Story Plan V1 it claims to restate.
        shot_plan: The Shot Direction Plan V1 whose visibility it reports.
        current_export: The Render Export V1 whose recorded sentences it carries.

    The named checks, in order:

    * all four documents validate under their own contracts
    * the plan's three digests name exactly these documents, the export is the
      one the story plan actually read, and the shot plan directs exactly this
      story plan
    * schema versions, mode, episode and previous episode agree across all three
    * every story beat is narrated exactly once, in the story's own order, with
      no invented and no omitted beat
    * every unit copies its beat's kind, emphasis and subjects unchanged
    * every unit's visibility, shot citation and frame span are exactly what the
      shot plan granted -- an unshown beat carries the shot plan's own reason and
      no frames
    * every carried summary is the bound export's own sentence for the fact the
      beat cites, verbatim, and every composed sentence is the versioned
      template's output for that beat

    Finally the plan is re-derived from the three sources and must equal it byte
    for byte, which closes every remaining degree of freedom -- ordering,
    identifier assignment, accounting and wording included.

    Returns:
        The verified narration plan.

    Raises:
        TypeError: If any input has the wrong Python type.
        ValueError: If any binding, accounting, agreement or derivation check
            fails.
    """
    plan = validate_episode_narration_plan(narration_plan)
    story = validate_episode_story_plan(story_plan)
    shots = validate_shot_direction_plan(shot_plan)
    export = cast(dict[str, JsonValue], validate_render_export(current_export))

    source = _document(plan["source"], "episode narration plan source")
    _check_bindings(source, story, shots, export)

    beats = cast(list[dict[str, JsonValue]], story["beats"])
    units = cast(list[dict[str, JsonValue]], plan["units"])
    if len(units) != len(beats):
        raise ValueError(
            f"episode narration plan carries {len(units)} units for a story plan holding "
            f"{len(beats)} beats; every beat is narrated exactly once"
        )

    beats_by_id = {cast(str, beat["beat_id"]): beat for beat in beats}
    claims = _visibility_claims(shots)
    seen: set[str] = set()

    for position, unit in enumerate(units):
        label = f"episode narration plan units[{position}]"
        beat_id = cast(str, unit["beat_id"])
        beat = beats_by_id.get(beat_id)
        if beat is None:
            raise ValueError(
                f"{label} restates beat {beat_id!r}, which the story plan does not hold; no "
                "beat is ever invented"
            )
        if beat_id in seen:
            raise ValueError(
                f"{label} restates beat {beat_id!r}, which another unit already restates; a "
                "beat is narrated once"
            )
        seen.add(beat_id)
        if cast(str, beats[position]["beat_id"]) != beat_id:
            raise ValueError(
                f"{label} restates beat {beat_id!r}, but the story plan holds "
                f"{beats[position]['beat_id']!r} at that position; narration follows the "
                "story's own order and never reorders history"
            )

        claim = claims.get(beat_id)
        if claim is None:
            raise ValueError(
                f"{label} restates beat {beat_id!r}, which the shot direction plan neither "
                "shows nor records as unshown"
            )
        for field in ("visibility", "shot_id", "start_frame", "end_frame", "unshown_reason"):
            if unit[field] != claim[field]:
                raise ValueError(
                    f"{label} declares {field} {unit[field]!r}, but the shot direction plan "
                    f"grants {claim[field]!r} for beat {beat_id!r}; what the viewer is shown "
                    "is Phase 22's decision, reported here and never re-made"
                )

        _check_unit_against_beat(unit, beat, export, label)

    missing = sorted(set(beats_by_id) - seen)
    if missing:
        raise ValueError(
            f"episode narration plan leaves story beats {missing} unnarrated; every beat is "
            "restated exactly once, whether or not the episode shows it"
        )

    # The contract is a deterministic single-output function of its sources, so
    # the one valid plan for this story, direction and export is the one the
    # planner derives. Byte equality closes every degree of freedom the named
    # checks above leave open.
    derived = build_episode_narration_plan_bytes(story, shots, export)
    offered = dumps_canonical(plan, "episode narration plan")
    if offered != derived:
        raise ValueError(
            "episode narration plan does not equal the deterministic derivation from the "
            "story plan, shot direction plan and render export it binds; a plan is "
            "source-verified only when it is the plan those sources produce"
        )

    return plan
