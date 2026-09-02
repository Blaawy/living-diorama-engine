"""Cross-validation of an Episode Language Realization Plan against its sources.

:func:`living_diorama.language_realization.realization_schema_v1.validate_episode_language_realization_plan`
proves everything a realization plan can prove about itself, the wording bans
included. What it cannot prove is that the plan's claims are *true of its
sources*: that the three digests it carries name the documents actually
offered, that those documents name each other, that every record realizes its
positional unit and beat, and that every sentence is exactly the one the
reviewed policy derives from the structural evidence. A plan whose SHA fields
are syntactically digests is not thereby source-verified.

This module closes that gap. Given the plan and the three documents it claims
to realize, it verifies every binding and every per-record agreement, and then
seals the whole question by re-deriving the plan from those sources: the
realization contract is a deterministic single-output function of its inputs,
so the one valid plan for a given narration plan, story plan and export is the
plan the planner derives. Anything else is refused, named check by named check
first so a failure says which claim stopped being true.

The wording register the plan was written under is read from the plan itself
-- absent means ``v1`` -- and threaded into every re-derivation, so a V2 plan
is verified by deriving V2 text against itself, never against a V1 assumption.
A V2 plan is also verified where a V1 plan cannot be: every record's fact and
event bindings are resolved against the real sources (an unbound or wrong
binding is refused), and every viewer guidance entry's grounding is resolved
against the real world export (an ungrounded entry is refused).
"""

from typing import cast

from living_diorama.language_realization.realization_atoms import (
    EVIDENCE_EVENT,
    EVIDENCE_MEMORY_FACT,
    realized_text_for_beat,
)
from living_diorama.language_realization.realization_guidance import (
    validate_guidance_grounding,
)
from living_diorama.language_realization.realization_planner import (
    _require_unit_beat_agreement,
    build_episode_language_realization_plan_bytes,
)
from living_diorama.language_realization.realization_schema_v1 import (
    JsonValue,
    validate_episode_language_realization_plan,
)
from living_diorama.language_realization.realization_spec import (
    WORDING_PROFILE_V1,
    WORDING_PROFILE_V2,
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

__all__ = ["validate_language_realization_plan_against_sources"]


def _document(value: object, description: str) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], value)


def _check_bindings(
    source: dict[str, JsonValue],
    narration: dict[str, JsonValue],
    story: dict[str, JsonValue],
    export: dict[str, JsonValue],
) -> None:
    """Verify the plan names the exact documents offered, and that they join."""
    narration_digest = sha256_hex(dumps_canonical(narration, "episode narration plan"))
    story_digest = sha256_hex(dumps_canonical(story, "episode story plan"))
    export_digest = sha256_hex(dumps_canonical(export, "render export"))

    for field, offered, label in (
        ("narration_plan_sha256", narration_digest, "narration plan"),
        ("story_plan_sha256", story_digest, "story plan"),
        ("current_export_sha256", export_digest, "render export"),
    ):
        if source[field] != offered:
            raise ValueError(
                f"language realization plan binds {label} {source[field]!r}, but the "
                f"offered {label}'s canonical bytes hash to {offered!r}; this plan does "
                "not realize that document"
            )

    narration_source = _document(narration["source"], "episode narration plan source")
    if narration_source["story_plan_sha256"] != source["story_plan_sha256"]:
        raise ValueError(
            f"language realization plan realizes narration restated from story plan "
            f"{narration_source['story_plan_sha256']!r} under story plan "
            f"{source['story_plan_sha256']!r}; the narration and the story are not the "
            "same episode's"
        )
    if narration_source["current_export_sha256"] != source["current_export_sha256"]:
        raise ValueError(
            f"language realization plan realizes narration carried from export "
            f"{narration_source['current_export_sha256']!r} under export "
            f"{source['current_export_sha256']!r}; the narration and the export are not "
            "the same episode's"
        )
    story_source = _document(story["source"], "episode story plan source")
    story_current = _document(story_source["current"], "episode story plan source current")
    if story_current["document_sha256"] != source["current_export_sha256"]:
        raise ValueError(
            f"language realization plan binds render export "
            f"{source['current_export_sha256']!r}, but the story plan was derived from "
            f"export {story_current['document_sha256']!r}; the atoms this plan speaks "
            "come from a document the story never read"
        )

    if source["narration_schema_version"] != narration["schema_version"]:
        raise ValueError(
            f"language realization plan records narration schema version "
            f"{source['narration_schema_version']}, but the narration plan declares "
            f"{narration['schema_version']}"
        )
    if source["story_schema_version"] != story["schema_version"]:
        raise ValueError(
            f"language realization plan records story schema version "
            f"{source['story_schema_version']}, but the story plan declares "
            f"{story['schema_version']}"
        )

    for field in ("mode", "episode", "previous_episode"):
        if source[field] != narration_source[field]:
            raise ValueError(
                f"language realization plan declares {field} {source[field]!r}, but the "
                f"narration plan it realizes declares {narration_source[field]!r}"
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


def _check_v2_record_bindings(
    record: dict[str, JsonValue],
    beat: dict[str, JsonValue],
    label: str,
) -> None:
    """Verify a V2 record's fact and event bindings against its beat's evidence.

    The atoms derivation proves the beat's evidence resolves against the real
    export, so the record's bindings must equal the beat's own claims exactly:
    the event index the beat cites (or ``null`` for an absence beat) and the
    memory fact the beat cites (or ``null`` for a template-backed beat). A
    missing or wrong binding means the record was written by something this
    contract does not describe.

    Raises:
        ValueError: If the record's bindings disagree with the beat's evidence.
    """
    event_entries = [
        entry
        for entry in cast(list[dict[str, JsonValue]], beat["evidence"])
        if entry["kind"] == EVIDENCE_EVENT
    ]
    if len(event_entries) > 1:
        raise ValueError(
            f"{label} is bound to a beat citing {len(event_entries)} events; a beat "
            "cites exactly one event or none"
        )
    expected_event = event_entries[0]["index"] if event_entries else None
    if record["event_id"] != expected_event:
        raise ValueError(
            f"{label} binds event_id {record['event_id']!r}, but the beat it realizes "
            f"cites event {expected_event!r}; a record's event binding is the beat's own"
        )
    fact_entries = [
        entry
        for entry in cast(list[dict[str, JsonValue]], beat["evidence"])
        if entry["kind"] == EVIDENCE_MEMORY_FACT
    ]
    expected_fact = fact_entries[0]["fact_id"] if fact_entries else None
    if record["fact_id"] != expected_fact:
        raise ValueError(
            f"{label} binds fact_id {record['fact_id']!r}, but the beat it realizes "
            f"cites {expected_fact!r}; a record's fact binding is the beat's own"
        )


def validate_language_realization_plan_against_sources(
    realization_plan: object,
    narration_plan: object,
    story_plan: object,
    current_export: object,
) -> dict[str, JsonValue]:
    """Verify an Episode Language Realization Plan against its actual sources.

    Args:
        realization_plan: The Episode Language Realization Plan V1 to verify.
        narration_plan: The Episode Narration Plan V1 it claims to realize.
        story_plan: The Episode Story Plan V1 whose evidence licenses it.
        current_export: The Render Export V1 its atoms and labels resolve
            through.

    The named checks, in order:

    * all four documents validate under their own contracts
    * the plan's three digests name exactly these documents, the narration
      plan itself restates exactly this story plan and carried sentences from
      exactly this export, and the story plan read exactly this export
    * schema versions, mode, episode and previous episode agree everywhere
      they are stated
    * every record realizes its positional narration unit: one realization per
      unit, in the narration plan's own order
    * every unit restates its positional story beat -- identity, kind,
      subjects, emphasis and text-source classification
    * every record's sentence equals the one deterministic derivation from the
      structural evidence, actual export events and facts, and reviewed labels,
      under the wording register the plan itself declares (absent means ``v1``)
    * under ``v2`` only, every record's fact and event bindings equal the beat's
      own evidence claims, and every viewer guidance entry's grounding resolves
      against the real world export
    * the accounting block agrees with the sources' own classification

    Finally the plan is re-derived from the three sources under that same
    register and must equal it byte for byte, which closes every remaining
    degree of freedom.

    Returns:
        The verified realization plan.

    Raises:
        TypeError: If any input has the wrong Python type.
        ValueError: If any binding, identity, agreement or derivation check
            fails.
    """
    plan = validate_episode_language_realization_plan(realization_plan)
    narration = validate_episode_narration_plan(narration_plan)
    story = validate_episode_story_plan(story_plan)
    export = cast(dict[str, JsonValue], validate_render_export(current_export))

    wording_profile = cast(str, plan.get("wording_profile", WORDING_PROFILE_V1))

    source = _document(plan["source"], "language realization plan source")
    _check_bindings(source, narration, story, export)

    units = cast(list[dict[str, JsonValue]], narration["units"])
    beats = cast(list[dict[str, JsonValue]], story["beats"])
    realizations = cast(list[dict[str, JsonValue]], plan["realizations"])
    if len(realizations) != len(units):
        raise ValueError(
            f"language realization plan carries {len(realizations)} records for a "
            f"narration plan holding {len(units)} units; every unit is realized exactly "
            "once"
        )
    if len(units) != len(beats):
        raise ValueError(
            f"the narration plan holds {len(units)} units for a story holding "
            f"{len(beats)} beats; every beat is realized exactly once"
        )

    fact_backed = 0
    for position, (record, unit, beat) in enumerate(
        zip(realizations, units, beats, strict=True), start=1
    ):
        label = f"language realization plan realizations[{position - 1}]"
        if record["unit_id"] != unit["unit_id"]:
            raise ValueError(
                f"{label} realizes unit {record['unit_id']!r}, but the narration plan "
                f"holds {unit['unit_id']!r} at that position; realization follows the "
                "narration plan's own order"
            )
        kind = _require_unit_beat_agreement(unit, beat, position)
        description = f"episode story plan beats[{position - 1}]"
        expected = realized_text_for_beat(
            kind, beat, export, description, wording_profile=wording_profile
        )
        if record["realized_text"] != expected:
            raise ValueError(
                f"{label} carries wording {record['realized_text']!r}, but the reviewed "
                f"policy realizes this unit as {expected!r}; realized wording is the "
                "table's or it was written by something this contract does not describe"
            )
        if wording_profile == WORDING_PROFILE_V2:
            _check_v2_record_bindings(record, beat, label)
        if text_source_for_kind(kind) == TEXT_SOURCE_MEMORY_FACT_SUMMARY:
            fact_backed += 1

    if wording_profile == WORDING_PROFILE_V2:
        for entry in cast(list[dict[str, JsonValue]], plan.get("viewer_guidance", [])):
            validate_guidance_grounding(cast(dict[str, str], entry), export)

    accounting = _document(plan["accounting"], "language realization plan accounting")
    measured = {
        "fact_backed": fact_backed,
        "realizations_total": len(realizations),
        "template_backed": len(realizations) - fact_backed,
    }
    for field in sorted(measured):
        expected_count = measured[field]
        if accounting[field] != expected_count:
            raise ValueError(
                f"language realization plan accounts {field} {accounting[field]!r}, but "
                f"the sources classify {expected_count!r}; the split is measured from "
                "the narration plan's own text sources, never asserted beside them"
            )

    derived = build_episode_language_realization_plan_bytes(
        narration, story, export, wording_profile=wording_profile
    )
    offered = dumps_canonical(plan, "language realization plan")
    if offered != derived:
        raise ValueError(
            "language realization plan does not equal the deterministic derivation from "
            "the narration plan, story plan and render export it binds; a plan is "
            "source-verified only when it is the plan those sources produce"
        )

    return plan
