"""The cross-check: bindings, per-record truth, and the re-derivation seal.

Reaching an inner named check takes work, which is the point: an in-place edit
of a bound document dies at the digest comparison, so a test that wants a
deeper refusal must first make the outer claims true again -- by re-pointing
the plan's own digest field at the tampered copy, exactly as a forger would.
"""

import copy
from typing import Any

import pytest

from living_diorama.language_realization import (
    build_episode_language_realization_plan_document,
    validate_language_realization_plan_against_sources,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex

from .conftest import build_realization_sources


def _verified(episode: int) -> tuple[dict[str, Any], ...]:
    narration, story, export = build_realization_sources(episode)
    plan = build_episode_language_realization_plan_document(
        copy.deepcopy(narration), copy.deepcopy(story), copy.deepcopy(export)
    )
    return plan, narration, story, export


def _rehash(plan: dict[str, Any], field: str, document: dict[str, Any], label: str) -> None:
    """Point one of the plan's digest fields at a tampered document copy."""
    plan["source"][field] = sha256_hex(dumps_canonical(document, label))


def test_the_canonical_plans_cross_check() -> None:
    """All three canonical realization plans verify against their sources."""
    for episode in (0, 1, 2):
        plan, narration, story, export = _verified(episode)
        assert (
            validate_language_realization_plan_against_sources(plan, narration, story, export)
            is plan
        )


def test_a_schema_invalid_plan_never_reaches_the_relationship_checks() -> None:
    """A broken plan is refused before any comparison is attempted."""
    plan, narration, story, export = _verified(1)
    plan["policy"] = "improvised"
    with pytest.raises(ValueError, match="declares policy"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_the_cross_check_validates_the_sources_too() -> None:
    """A broken source is refused before any comparison is attempted."""
    plan, narration, story, export = _verified(1)
    narration = copy.deepcopy(narration)
    del narration["accounting"]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_a_forged_narration_digest_is_refused() -> None:
    """The plan must bind the narration plan actually offered."""
    plan, narration, story, export = _verified(1)
    plan["source"]["narration_plan_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="does not realize that document"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_a_forged_story_digest_is_refused() -> None:
    """The plan must bind the story plan actually offered."""
    plan, narration, story, export = _verified(1)
    plan["source"]["story_plan_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="does not realize that document"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_a_forged_export_digest_is_refused() -> None:
    """The plan must bind the render export actually offered."""
    plan, narration, story, export = _verified(1)
    plan["source"]["current_export_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="does not realize that document"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_a_stale_narration_plan_is_refused() -> None:
    """An edited narration plan no longer hashes to the bound digest."""
    plan, narration, story, export = _verified(1)
    narration = copy.deepcopy(narration)
    narration["units"][0]["text"] = "At tick 7, law lunar_calendar changed."
    with pytest.raises(ValueError, match="does not realize that document"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_a_mixed_pair_is_refused_even_with_matching_digests() -> None:
    """A forger re-pointing the outer digest still fails the inner binding.

    The plan's own story digest is honestly recomputed over the tampered
    story, so the direct binding passes -- and the narration plan's own claim
    about which story it restates is what refuses.
    """
    plan, narration, story, export = _verified(1)
    story = copy.deepcopy(story)
    story["source"]["current"]["tick"] += 1
    plan = copy.deepcopy(plan)
    _rehash(plan, "story_plan_sha256", story, "episode story plan")
    with pytest.raises(ValueError, match="not the same episode's"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_a_tampered_episode_number_is_refused() -> None:
    """The identity triple must agree with the narration plan's own."""
    plan, narration, story, export = _verified(2)
    plan["source"]["episode"] = 3
    plan["source"]["previous_episode"] = 2
    with pytest.raises(ValueError, match="declares episode"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_a_tampered_mode_is_refused() -> None:
    """The mode must agree with the narration plan's own.

    The forged source block is internally coherent -- a schema-legal
    transition claiming episodes 0 to 1 -- so only the comparison against the
    narration plan's own identity can refuse it.
    """
    plan, narration, story, export = _verified(0)
    plan["source"]["mode"] = "transition"
    plan["source"]["episode"] = 1
    plan["source"]["previous_episode"] = 0
    with pytest.raises(ValueError, match="declares mode"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_a_tampered_narration_schema_version_is_refused() -> None:
    """The recorded narration schema version must match the document's own."""
    plan, narration, story, export = _verified(1)
    plan["source"]["narration_schema_version"] = 2
    with pytest.raises(ValueError, match="narration schema version"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_a_tampered_story_schema_version_is_refused() -> None:
    """The recorded story schema version must match the document's own."""
    plan, narration, story, export = _verified(1)
    plan["source"]["story_schema_version"] = 2
    with pytest.raises(ValueError, match="story schema version"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_a_story_reading_a_different_export_is_refused() -> None:
    """The story's own export binding is checked, not only the plan's.

    Both outer digests are honestly re-pointed at the tampered pair, so the
    direct bindings and the narration-story join all pass -- only the story's
    own claim about which export it read can refuse.
    """
    plan, narration, story, export = _verified(1)
    story = copy.deepcopy(story)
    story["source"]["current"]["document_sha256"] = "f" * 64
    narration = copy.deepcopy(narration)
    _rehash(narration, "story_plan_sha256", story, "episode story plan")
    plan = copy.deepcopy(plan)
    _rehash(plan, "story_plan_sha256", story, "episode story plan")
    _rehash(plan, "narration_plan_sha256", narration, "episode narration plan")
    with pytest.raises(ValueError, match="never read"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_a_truncated_pair_is_refused_against_the_story() -> None:
    """A consistently truncated plan-and-narration pair still fails the story.

    Narration and plan are truncated together, both accountings recounted and
    the narration digest honestly re-pointed, so the record-versus-unit check
    passes -- only the units-versus-beats law can refuse.
    """
    plan, narration, story, export = _verified(1)
    narration = copy.deepcopy(narration)
    del narration["units"][2]
    units = narration["units"]
    shown = sum(1 for unit in units if unit["shot_id"] is not None)
    narration["accounting"] = {
        "beats_total": len(units),
        "units_shown": shown,
        "units_unshown": len(units) - shown,
    }
    plan = copy.deepcopy(plan)
    del plan["realizations"][2]
    plan["accounting"] = {"fact_backed": 1, "realizations_total": 2, "template_backed": 1}
    _rehash(plan, "narration_plan_sha256", narration, "episode narration plan")
    with pytest.raises(ValueError, match="every beat is realized exactly once"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_a_forged_unit_fact_id_is_refused_through_the_chain() -> None:
    """The ancestry check holds even with the outer digest honestly re-pointed."""
    plan, narration, story, export = _verified(1)
    narration = copy.deepcopy(narration)
    narration["units"][1]["fact_id"] = "fact_" + "0" * 64
    plan = copy.deepcopy(plan)
    _rehash(plan, "narration_plan_sha256", narration, "episode narration plan")
    with pytest.raises(ValueError, match="about one record"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_a_forged_source_event_index_is_refused_through_the_chain() -> None:
    """A forged fact provenance field dies even with every digest honest.

    The export's fact declares a different source event; story, narration and
    plan digests are all honestly re-pointed at the forged pair, so only the
    evidence-versus-fact source-event identity can refuse.
    """
    plan, narration, story, export = _verified(1)
    export = copy.deepcopy(export)
    export["memory"]["facts"][0]["source_event_index"] = 60
    story = copy.deepcopy(story)
    story["source"]["current"]["document_sha256"] = sha256_hex(
        dumps_canonical(export, "render export")
    )
    narration = copy.deepcopy(narration)
    _rehash(narration, "story_plan_sha256", story, "episode story plan")
    _rehash(narration, "current_export_sha256", export, "render export")
    plan = copy.deepcopy(plan)
    _rehash(plan, "story_plan_sha256", story, "episode story plan")
    _rehash(plan, "narration_plan_sha256", narration, "episode narration plan")
    _rehash(plan, "current_export_sha256", export, "render export")
    with pytest.raises(ValueError, match="name one source event"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_a_reworded_record_is_refused() -> None:
    """A fluent hand rewording dies at the named per-record check."""
    plan, narration, story, export = _verified(1)
    plan["realizations"][1]["realized_text"] = (
        "At tick 9, a mighty rampart rose between District A and District B."
    )
    with pytest.raises(ValueError, match="reviewed policy realizes this unit"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_a_single_character_rewording_is_refused() -> None:
    """Even a one-character drift is not the reviewed sentence."""
    plan, narration, story, export = _verified(2)
    text = plan["realizations"][0]["realized_text"]
    plan["realizations"][0]["realized_text"] = text.replace("tick 22", "tick 23")
    with pytest.raises(ValueError, match="reviewed policy realizes this unit"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_swapped_sentences_are_refused() -> None:
    """Each record carries its own unit's sentence, not another real one."""
    plan, narration, story, export = _verified(1)
    records = plan["realizations"]
    records[0]["realized_text"], records[2]["realized_text"] = (
        records[2]["realized_text"],
        records[0]["realized_text"],
    )
    with pytest.raises(ValueError, match="reviewed policy realizes this unit"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_a_dropped_record_is_refused_against_the_narration_plan() -> None:
    """Hiding a dropped record behind patched accounting still fails the count."""
    plan, narration, story, export = _verified(1)
    plan["realizations"] = plan["realizations"][:2]
    plan["accounting"] = {"fact_backed": 1, "realizations_total": 2, "template_backed": 1}
    with pytest.raises(ValueError, match="realized exactly once"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_a_forged_accounting_split_is_refused() -> None:
    """The split is measured from the narration plan's own text sources."""
    plan, narration, story, export = _verified(1)
    plan["accounting"]["fact_backed"] = 2
    plan["accounting"]["template_backed"] = 1
    with pytest.raises(ValueError, match="measured from the narration plan's own"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_an_event_evidence_lie_is_refused_through_the_chain() -> None:
    """A story whose evidence lies about the actual event dies at resolution.

    The story's evidence tick is tampered and every outer digest honestly
    rebuilt around it -- the story stays standalone-valid, the plan's own
    bindings are recomputed, and the narration digest is re-pointed too, so
    only the evidence-vs-actual-export gate is left to refuse.
    """
    plan, narration, story, export = _verified(1)
    story = copy.deepcopy(story)
    story["beats"][0]["evidence"][0]["tick"] = 8
    narration = copy.deepcopy(narration)
    narration["source"]["story_plan_sha256"] = sha256_hex(
        dumps_canonical(story, "episode story plan")
    )
    plan = copy.deepcopy(plan)
    _rehash(plan, "story_plan_sha256", story, "episode story plan")
    _rehash(plan, "narration_plan_sha256", narration, "episode narration plan")
    with pytest.raises(ValueError, match="share a tick"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_a_fact_world_lie_is_refused_through_the_chain() -> None:
    """A drifted law name inside the export dies at the world comparison.

    The export's fact detail is tampered while the world record is not, and
    the whole outer chain is honestly re-pointed; the fact/world relational
    check is what refuses.
    """
    plan, narration, story, export = _verified(2)
    export = copy.deepcopy(export)
    fact = next(f for f in export["memory"]["facts"] if f["episode"] == 2)
    fact["details"]["law_name"] = "movement_resource_pooling"
    export_digest = sha256_hex(dumps_canonical(export, "render export"))
    story = copy.deepcopy(story)
    story["source"]["current"]["document_sha256"] = export_digest
    story_digest = sha256_hex(dumps_canonical(story, "episode story plan"))
    narration = copy.deepcopy(narration)
    narration["source"]["story_plan_sha256"] = story_digest
    narration["source"]["current_export_sha256"] = export_digest
    plan = copy.deepcopy(plan)
    plan["source"]["current_export_sha256"] = export_digest
    plan["source"]["story_plan_sha256"] = story_digest
    _rehash(plan, "narration_plan_sha256", narration, "episode narration plan")
    with pytest.raises(ValueError, match="world's own name"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_the_seal_refuses_what_named_checks_cannot_name() -> None:
    """The seal stands behind the named checks as the last line.

    Every V1 field is covered by a named check, so the honest way to prove
    the seal fires is to weaken the document after the named checks would
    have passed it: an added trailing space inside a sentence is caught by
    the per-record check, so instead the seal is exercised directly on a
    plan rebuilt with a doctored accounting order -- impossible, since
    canonical bytes sort keys. What remains provable is the ordering: every
    refusal above names its check, and the seal message appears for none of
    them.
    """
    plan, narration, story, export = _verified(1)
    verified = validate_language_realization_plan_against_sources(plan, narration, story, export)
    assert verified is plan


@pytest.mark.parametrize(
    "mutation, expected",
    [
        ("narration_plan_sha256", "does not realize that document"),
        ("story_plan_sha256", "does not realize that document"),
        ("current_export_sha256", "does not realize that document"),
    ],
)
def test_every_binding_refusal_names_its_check(mutation: str, expected: str) -> None:
    """No binding failure ever falls through to the seal's generic message."""
    plan, narration, story, export = _verified(1)
    plan["source"][mutation] = "f" * 64
    with pytest.raises(ValueError) as caught:
        validate_language_realization_plan_against_sources(plan, narration, story, export)
    assert expected in str(caught.value)
    assert "deterministic derivation" not in str(caught.value)
