"""What the derivation actually produces, over real canonical history.

The three episodes in ``fixtures/`` are the engine's own chain: a baseline that
emphasised nothing, the episode a wall was built in, and the episode a law came
back while the wall stayed. Between them they exercise every V1 case that
history has produced -- including the one this layer was built for, where a
PRIMARY beat is honestly unshown and words are the only way it reaches anyone.
"""

import copy
from typing import Any

import pytest

from living_diorama.narration import (
    build_episode_narration_plan_bytes,
    build_episode_narration_plan_document,
)
from living_diorama.persistence.json_codec import dumps_canonical

from .conftest import build_sources

Sources = tuple[dict[str, Any], dict[str, Any], dict[str, Any]]


def _unit_by_beat(plan: dict[str, Any], beat_id: str) -> dict[str, Any]:
    """Return the unit restating one beat."""
    return next(unit for unit in plan["units"] if unit["beat_id"] == beat_id)


# ---- one unit per beat, in the story's order


@pytest.mark.parametrize("episode", [0, 1, 2])
def test_every_beat_is_narrated_exactly_once(episode: int) -> None:
    """The unit list is the beat list, one for one, in the same order."""
    story, shots, export = build_sources(episode)
    plan = build_episode_narration_plan_document(story, shots, export)
    assert [unit["beat_id"] for unit in plan["units"]] == [
        beat["beat_id"] for beat in story["beats"]
    ]


@pytest.mark.parametrize("episode", [0, 1, 2])
def test_unit_ids_are_positional(episode: int) -> None:
    """Identifiers are derivable from position, so they cannot drift."""
    story, shots, export = build_sources(episode)
    plan = build_episode_narration_plan_document(story, shots, export)
    assert [unit["unit_id"] for unit in plan["units"]] == [
        f"unit_{position:04d}" for position in range(1, len(story["beats"]) + 1)
    ]


@pytest.mark.parametrize("episode", [0, 1, 2])
def test_emphasis_and_subjects_are_copied_never_recomputed(episode: int) -> None:
    """Phase 21's account of a beat survives into narration unchanged."""
    story, shots, export = build_sources(episode)
    plan = build_episode_narration_plan_document(story, shots, export)
    for unit, beat in zip(plan["units"], story["beats"], strict=True):
        assert unit["kind"] == beat["kind"]
        assert unit["emphasis"] == beat["emphasis"]
        assert unit["subject_ids"] == beat["subject_ids"]


# ---- the baseline


def test_the_baseline_narrates_its_empty_result(sources_ep0: Sources) -> None:
    """An episode that emphasised nothing still gets a unit saying so."""
    plan = build_episode_narration_plan_document(*sources_ep0)
    assert plan["accounting"] == {"beats_total": 1, "units_shown": 0, "units_unshown": 1}
    unit = plan["units"][0]
    assert unit["kind"] == "NO_EMPHASIZED_BEATS"
    assert unit["visibility"] == "UNSHOWN"
    assert unit["unshown_reason"] == "NOTHING_TO_EMPHASIZE"
    assert unit["subject_ids"] == []
    assert unit["fact_id"] is None
    assert unit["text"] == "No beats were emphasized for this episode."


def test_the_baseline_binds_no_previous_episode(sources_ep0: Sources) -> None:
    """A baseline describes episode 0 and follows nothing."""
    plan = build_episode_narration_plan_document(*sources_ep0)
    assert plan["source"]["mode"] == "baseline"
    assert plan["source"]["previous_episode"] is None
    assert plan["source"]["episode"] == 0


# ---- the episode the wall was built in


def test_the_wall_episode_narrates_three_beats(sources_ep1: Sources) -> None:
    """Two shown, one unshown, and the accounting says which is which."""
    plan = build_episode_narration_plan_document(*sources_ep1)
    assert plan["accounting"] == {"beats_total": 3, "units_shown": 2, "units_unshown": 1}


def test_a_shown_beat_carries_its_own_shot_and_span(sources_ep1: Sources) -> None:
    """The window comes from the shot that actually cites the beat."""
    story, shots, export = sources_ep1
    plan = build_episode_narration_plan_document(story, shots, export)
    unit = _unit_by_beat(plan, "beat_0001")
    shot = next(s for s in shots["shots"] if "beat_0001" in s["source_beat_ids"])
    assert unit["visibility"] == "SHOWN"
    assert unit["shot_id"] == shot["shot_id"]
    assert unit["start_frame"] == shot["start_frame"]
    assert unit["end_frame"] == shot["end_frame"]
    assert unit["unshown_reason"] is None


def test_an_event_backed_beat_is_narrated_from_the_template(sources_ep1: Sources) -> None:
    """No memory sentence exists for it, so the versioned table composes one."""
    plan = build_episode_narration_plan_document(*sources_ep1)
    unit = _unit_by_beat(plan, "beat_0001")
    assert unit["text_source"] == "NARRATION_TEMPLATE"
    assert unit["text"] == 'At tick 7, law "law_movement_sharing" changed.'
    assert unit["fact_id"] is None


def test_a_durable_consequence_is_unshown_and_still_narrated(sources_ep1: Sources) -> None:
    """PRIMARY, and the viewer is never shown it. Words are all it gets."""
    plan = build_episode_narration_plan_document(*sources_ep1)
    unit = _unit_by_beat(plan, "beat_0002")
    assert unit["kind"] == "DURABLE_CONSEQUENCE"
    assert unit["emphasis"] == "PRIMARY"
    assert unit["visibility"] == "UNSHOWN"
    assert unit["unshown_reason"] == "NO_FIXED_ANCHOR_WITH_VISUAL_EVIDENCE"
    assert unit["shot_id"] is None
    assert unit["start_frame"] is None
    assert unit["end_frame"] is None
    assert unit["text_source"] == "MEMORY_FACT_SUMMARY"
    assert "was built" in unit["text"]


# ---- the episode the consequence persisted in


def test_the_persisted_consequence_carries_the_recorded_sentence(sources_ep2: Sources) -> None:
    """The world remembers, and now it can say so.

    Nobody is shown the memory register -- no approved camera can see it -- so
    without this unit the episode would render, verify, and never mention that
    the wall outlived the law that raised it.
    """
    story, shots, export = sources_ep2
    plan = build_episode_narration_plan_document(story, shots, export)
    unit = _unit_by_beat(plan, "beat_0001")
    assert unit["kind"] == "CONSEQUENCE_PERSISTED"
    assert unit["emphasis"] == "PRIMARY"
    assert unit["visibility"] == "UNSHOWN"
    assert unit["text_source"] == "MEMORY_FACT_SUMMARY"

    recorded = next(
        fact for fact in export["memory"]["facts"] if fact["fact_id"] == unit["fact_id"]
    )["summary"]
    assert unit["text"] == recorded
    assert "remained in the world" in unit["text"]


def test_the_carried_sentence_is_byte_identical_to_the_export(sources_ep2: Sources) -> None:
    """Verbatim is asserted on the encoded bytes, not on a string comparison alone."""
    story, shots, export = sources_ep2
    plan = build_episode_narration_plan_document(story, shots, export)
    for unit in plan["units"]:
        if unit["text_source"] != "MEMORY_FACT_SUMMARY":
            continue
        recorded = next(f for f in export["memory"]["facts"] if f["fact_id"] == unit["fact_id"])[
            "summary"
        ]
        assert unit["text"].encode("utf-8") == recorded.encode("utf-8")


# ---- source binding


@pytest.mark.parametrize("episode", [0, 1, 2])
def test_the_plan_binds_the_documents_it_read(episode: int) -> None:
    """All three digests are real, and the export is the story plan's own."""
    from living_diorama.persistence.schema.state_hash import sha256_hex

    story, shots, export = build_sources(episode)
    plan = build_episode_narration_plan_document(story, shots, export)
    source = plan["source"]
    assert source["story_plan_sha256"] == sha256_hex(dumps_canonical(story, "story"))
    assert source["shot_plan_sha256"] == sha256_hex(dumps_canonical(shots, "shots"))
    assert source["current_export_sha256"] == sha256_hex(dumps_canonical(export, "export"))
    assert source["current_export_sha256"] == story["source"]["current"]["document_sha256"]


def test_the_plan_binds_no_render_manifest(sources_ep1: Sources) -> None:
    """Narration authoring is settled before a pixel exists."""
    plan = build_episode_narration_plan_document(*sources_ep1)
    assert not [key for key in plan["source"] if "manifest" in key or "render_plan" in key]


# ---- refusals


def test_a_story_and_export_that_do_not_join_are_refused(sources_ep1: Sources) -> None:
    """The sentences would come from a document the story never read."""
    story, shots, _export = sources_ep1
    _s2, _sh2, other_export = build_sources(2)
    with pytest.raises(ValueError, match="document the story never read"):
        build_episode_narration_plan_document(story, shots, other_export)


def test_a_shot_plan_for_another_story_is_refused(sources_ep1: Sources) -> None:
    """Direction and story must be the same episode's."""
    story, _shots, export = sources_ep1
    _s2, other_shots, _e2 = build_sources(2)
    with pytest.raises(ValueError, match="not about the same story"):
        build_episode_narration_plan_document(story, other_shots, export)


def test_a_story_the_shot_plan_does_not_account_for_is_refused(sources_ep1: Sources) -> None:
    """Narration reports the direction it was given and never decides visibility."""
    story, shots, export = sources_ep1
    shots = copy.deepcopy(shots)
    shots["unshown"] = []
    with pytest.raises(ValueError):
        build_episode_narration_plan_document(story, shots, export)


def test_a_malformed_story_is_refused(sources_ep1: Sources) -> None:
    """Inputs are validated under their own contracts before anything is derived."""
    story, shots, export = sources_ep1
    story = copy.deepcopy(story)
    del story["beats"][0]["evidence"]
    with pytest.raises((TypeError, ValueError)):
        build_episode_narration_plan_document(story, shots, export)


def test_a_malformed_export_is_refused(sources_ep1: Sources) -> None:
    """Including the export, whose sentences would otherwise be read unchecked."""
    story, shots, export = sources_ep1
    export = copy.deepcopy(export)
    del export["memory"]
    with pytest.raises((TypeError, ValueError)):
        build_episode_narration_plan_document(story, shots, export)


def test_editing_a_summary_breaks_the_export_binding(sources_ep2: Sources) -> None:
    """A tampered export cannot be slipped past the story plan that read it.

    Changing one character of one summary changes the export's canonical digest,
    which the story plan already recorded. The sentence never even gets looked
    at: the triple stops joining first.
    """
    story, shots, export = sources_ep2
    export = copy.deepcopy(export)
    export["memory"]["facts"][0]["summary"] += "."
    with pytest.raises(ValueError, match="document the story never read"):
        build_episode_narration_plan_document(story, shots, export)


def test_a_summary_making_a_visual_claim_stops_the_derivation() -> None:
    """This layer restates a recorded sentence or it refuses. It never rewords one.

    Reaching the wording check at all takes work, which is the point. Editing an
    export in place breaks its digest binding; editing a *carried* fact breaks
    Phase 21's memory-progression rule, because remembered history is never
    rewritten. Only the fact new in this episode can be altered, and only with
    the whole triple rebuilt around it. A dishonest sentence can therefore
    arrive only from a fully self-consistent chain -- and the wording guard is
    what stops it even then.
    """
    from living_diorama.cinematic import build_shot_direction_plan_document
    from living_diorama.story import build_episode_story_plan_document

    from .conftest import MOTION_CONFIG, load_export

    export = load_export(2)
    new_fact = next(fact for fact in export["memory"]["facts"] if fact["episode"] == 2)
    new_fact["summary"] = "The wall is shown standing at tick 22."
    story = build_episode_story_plan_document(copy.deepcopy(export), load_export(1))
    shots = build_shot_direction_plan_document(story, MOTION_CONFIG.read_bytes())
    with pytest.raises(ValueError, match="never rewords one"):
        build_episode_narration_plan_document(story, shots, copy.deepcopy(export))


# ---- purity


@pytest.mark.parametrize("episode", [0, 1, 2])
def test_the_derivation_does_not_mutate_its_inputs(episode: int) -> None:
    """A read-only consumer leaves its sources exactly as it found them."""
    story, shots, export = build_sources(episode)
    before = (
        dumps_canonical(story, "story"),
        dumps_canonical(shots, "shots"),
        dumps_canonical(export, "export"),
    )
    build_episode_narration_plan_document(story, shots, export)
    after = (
        dumps_canonical(story, "story"),
        dumps_canonical(shots, "shots"),
        dumps_canonical(export, "export"),
    )
    assert before == after


def test_the_bytes_wrapper_is_the_canonical_encoding(sources_ep1: Sources) -> None:
    """The bytes helper and the document helper cannot disagree."""
    story, shots, export = sources_ep1
    document = build_episode_narration_plan_document(story, shots, export)
    payload = build_episode_narration_plan_bytes(story, shots, export)
    assert payload == dumps_canonical(document, "episode narration plan")
    assert payload.endswith(b"\n")
    assert not payload.endswith(b"\n\n")
