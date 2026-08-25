"""The envelope proves everything a narration plan can prove about itself.

Exact key sets at every governed level, closed vocabularies, positional
identifiers, the shown/unshown pairing, and an accounting block measured from
the units actually present. What it deliberately does not prove is whether any
of it is true of the sources -- that is the cross-check's work, and keeping the
two apart is what stops a schema pass from being mistaken for source
verification.
"""

import copy
from typing import Any

import pytest

from living_diorama.narration.narration_schema_v1 import (
    ACCOUNTING_KEYS,
    NARRATION_PLAN_FORMAT,
    NARRATION_SCHEMA_VERSION,
    SOURCE_KEYS,
    TOP_LEVEL_KEYS,
    UNIT_KEYS,
    validate_episode_narration_plan,
)

from .conftest import build_plan


def _shown_unit(plan: dict[str, Any]) -> dict[str, Any]:
    """Return the plan's first shown unit."""
    for unit in plan["units"]:
        if unit["visibility"] == "SHOWN":
            return unit
    raise AssertionError("fixture plan carries no shown unit")


def _unshown_unit(plan: dict[str, Any]) -> dict[str, Any]:
    """Return the plan's first unshown unit."""
    for unit in plan["units"]:
        if unit["visibility"] == "UNSHOWN":
            return unit
    raise AssertionError("fixture plan carries no unshown unit")


# ---- the real plans validate


@pytest.mark.parametrize("episode", [0, 1, 2])
def test_the_canonical_plans_validate(episode: int) -> None:
    """Every plan the real chain produces passes its own contract."""
    assert validate_episode_narration_plan(build_plan(episode)) is not None


def test_validation_returns_the_document_itself(plan_ep1: dict[str, Any]) -> None:
    """The validator returns what it was given, never a repaired copy."""
    assert validate_episode_narration_plan(plan_ep1) is plan_ep1


# ---- envelope


def test_a_non_document_is_refused() -> None:
    """A list is not a plan."""
    with pytest.raises(TypeError, match="must be a dict"):
        validate_episode_narration_plan([])


def test_a_non_string_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """JSON object keys are strings, and a document that says otherwise is not JSON."""
    plan_ep1[7] = "seven"  # type: ignore[index]
    with pytest.raises(TypeError, match="keys must be str"):
        validate_episode_narration_plan(plan_ep1)


@pytest.mark.parametrize("key", sorted(TOP_LEVEL_KEYS))
def test_a_missing_top_level_key_is_refused(plan_ep1: dict[str, Any], key: str) -> None:
    """A missing key means the plan is incomplete."""
    del plan_ep1[key]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_episode_narration_plan(plan_ep1)


def test_an_extra_top_level_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An extra key means it was written by something this contract does not describe."""
    plan_ep1["audio_track"] = "narration.wav"
    with pytest.raises(ValueError, match="unexpected keys"):
        validate_episode_narration_plan(plan_ep1)


def test_a_foreign_format_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Another layer's document is not read as this one's."""
    plan_ep1["format"] = "living_diorama_episode_story_plan"
    with pytest.raises(ValueError, match="declares format"):
        validate_episode_narration_plan(plan_ep1)


def test_an_unsupported_schema_version_is_refused(plan_ep1: dict[str, Any]) -> None:
    """No migration is attempted; an unknown version is loudly broken."""
    plan_ep1["schema_version"] = NARRATION_SCHEMA_VERSION + 1
    with pytest.raises(ValueError, match="unsupported schema version"):
        validate_episode_narration_plan(plan_ep1)


def test_the_format_tag_is_this_contract(plan_ep1: dict[str, Any]) -> None:
    """What the derivation actually stamps on its output."""
    assert plan_ep1["format"] == NARRATION_PLAN_FORMAT
    assert plan_ep1["schema_version"] == NARRATION_SCHEMA_VERSION


# ---- source binding


@pytest.mark.parametrize("key", sorted(SOURCE_KEYS))
def test_a_missing_source_key_is_refused(plan_ep1: dict[str, Any], key: str) -> None:
    """The binding block is exact: every claim it should make, it makes."""
    del plan_ep1["source"][key]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_episode_narration_plan(plan_ep1)


def test_an_extra_source_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A render manifest binding is exactly the kind of extra this refuses."""
    plan_ep1["source"]["render_manifest_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="unexpected keys"):
        validate_episode_narration_plan(plan_ep1)


@pytest.mark.parametrize(
    "field", ["current_export_sha256", "shot_plan_sha256", "story_plan_sha256"]
)
def test_a_malformed_digest_is_refused(plan_ep1: dict[str, Any], field: str) -> None:
    """A digest field must hold something shaped like a digest."""
    plan_ep1["source"][field] = "not-a-digest"
    with pytest.raises((TypeError, ValueError)):
        validate_episode_narration_plan(plan_ep1)


def test_an_unknown_mode_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A plan is a baseline or a transition; there is no third kind."""
    plan_ep1["source"]["mode"] = "director_cut"
    with pytest.raises(ValueError, match="expected one of"):
        validate_episode_narration_plan(plan_ep1)


def test_an_unsupported_story_schema_version_is_refused(plan_ep1: dict[str, Any]) -> None:
    """This build narrates one story contract version."""
    plan_ep1["source"]["story_schema_version"] = 2
    with pytest.raises(ValueError, match="story schema version"):
        validate_episode_narration_plan(plan_ep1)


def test_an_unsupported_shot_schema_version_is_refused(plan_ep1: dict[str, Any]) -> None:
    """And one direction contract version."""
    plan_ep1["source"]["shot_schema_version"] = 9
    with pytest.raises(ValueError, match="shot schema version"):
        validate_episode_narration_plan(plan_ep1)


def test_a_baseline_naming_a_previous_episode_is_refused(plan_ep0: dict[str, Any]) -> None:
    """A baseline follows nothing, so it cannot name what it followed."""
    plan_ep0["source"]["previous_episode"] = 0
    with pytest.raises(ValueError, match="follows no episode"):
        validate_episode_narration_plan(plan_ep0)


def test_a_baseline_after_episode_zero_is_refused(plan_ep0: dict[str, Any]) -> None:
    """Only episode 0 has no history behind it."""
    plan_ep0["source"]["episode"] = 3
    with pytest.raises(ValueError, match="describes episode 0 only"):
        validate_episode_narration_plan(plan_ep0)


def test_a_transition_must_join_consecutive_episodes(plan_ep1: dict[str, Any]) -> None:
    """A transition joins N and N+1, never a gap."""
    plan_ep1["source"]["previous_episode"] = 7
    with pytest.raises(ValueError, match="consecutive episodes"):
        validate_episode_narration_plan(plan_ep1)


def test_a_transition_without_a_previous_episode_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A transition that followed nothing would not be a transition."""
    plan_ep1["source"]["previous_episode"] = None
    with pytest.raises(TypeError):
        validate_episode_narration_plan(plan_ep1)


# ---- units


def test_a_plan_with_no_units_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Emptiness is stated by a unit, never by absence."""
    plan_ep1["units"] = []
    plan_ep1["accounting"] = {"beats_total": 0, "units_shown": 0, "units_unshown": 0}
    with pytest.raises(ValueError, match="carries no units"):
        validate_episode_narration_plan(plan_ep1)


@pytest.mark.parametrize("key", sorted(UNIT_KEYS))
def test_a_missing_unit_key_is_refused(plan_ep1: dict[str, Any], key: str) -> None:
    """Every unit answers every question, including with null."""
    del plan_ep1["units"][0][key]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_episode_narration_plan(plan_ep1)


def test_an_extra_unit_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A voice line is a later phase's field, and is refused here."""
    plan_ep1["units"][0]["voice_line"] = "narrator"
    with pytest.raises(ValueError, match="unexpected keys"):
        validate_episode_narration_plan(plan_ep1)


def test_a_unit_id_out_of_position_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A unit id is positional, not a free label."""
    plan_ep1["units"][0]["unit_id"] = "unit_0009"
    with pytest.raises(ValueError, match="is positional"):
        validate_episode_narration_plan(plan_ep1)


def test_a_beat_id_out_of_position_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Narration follows the story's own order, one unit per beat."""
    plan_ep1["units"][0]["beat_id"] = "beat_0003"
    with pytest.raises(ValueError, match="one unit per beat"):
        validate_episode_narration_plan(plan_ep1)


def test_reordered_units_are_refused(plan_ep1: dict[str, Any]) -> None:
    """Positional identifiers make a reorder unrepresentable."""
    plan_ep1["units"].reverse()
    with pytest.raises(ValueError, match="is positional|one unit per beat"):
        validate_episode_narration_plan(plan_ep1)


def test_a_duplicated_unit_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Positional identifiers make a duplicate unrepresentable."""
    plan_ep1["units"].append(copy.deepcopy(plan_ep1["units"][0]))
    plan_ep1["accounting"]["beats_total"] += 1
    plan_ep1["accounting"]["units_shown"] += 1
    with pytest.raises(ValueError, match="is positional|one unit per beat"):
        validate_episode_narration_plan(plan_ep1)


def test_an_unknown_beat_kind_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Citizen vocabulary is not Phase 21's, so it is not narratable here."""
    plan_ep1["units"][0]["kind"] = "CITIZEN_BIOGRAPHY"
    with pytest.raises(ValueError, match="expected one of"):
        validate_episode_narration_plan(plan_ep1)


def test_an_unknown_emphasis_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Emphasis comes from Phase 21's closed vocabulary."""
    plan_ep1["units"][0]["emphasis"] = "CRITICAL"
    with pytest.raises(ValueError, match="expected one of"):
        validate_episode_narration_plan(plan_ep1)


def test_unsorted_subject_ids_are_refused(plan_ep1: dict[str, Any]) -> None:
    """Refused rather than sorted: repairing would hide a plan that lost the property."""
    unit = _unshown_unit(plan_ep1)
    unit["subject_ids"] = sorted(unit["subject_ids"], reverse=True)
    with pytest.raises(ValueError, match="must be sorted"):
        validate_episode_narration_plan(plan_ep1)


def test_repeated_subject_ids_are_refused(plan_ep1: dict[str, Any]) -> None:
    """And refused rather than de-duplicated, for the same reason."""
    unit = plan_ep1["units"][0]
    unit["subject_ids"] = [*unit["subject_ids"], *unit["subject_ids"]]
    with pytest.raises(ValueError, match="repeats a subject id"):
        validate_episode_narration_plan(plan_ep1)


def test_the_empty_result_unit_may_not_name_subjects(plan_ep0: dict[str, Any]) -> None:
    """It is a statement about the story layer's output, not about any entity."""
    plan_ep0["units"][0]["subject_ids"] = ["district_a"]
    with pytest.raises(ValueError, match="not about any entity"):
        validate_episode_narration_plan(plan_ep0)


def test_the_empty_result_unit_is_the_whole_plan(
    plan_ep0: dict[str, Any], plan_ep1: dict[str, Any]
) -> None:
    """A story that emphasised nothing cannot also have emphasised something."""
    smuggled = copy.deepcopy(plan_ep1["units"][0])
    smuggled["unit_id"] = "unit_0002"
    smuggled["beat_id"] = "beat_0002"
    plan_ep0["units"].append(smuggled)
    plan_ep0["accounting"] = {"beats_total": 2, "units_shown": 1, "units_unshown": 1}
    with pytest.raises(ValueError, match="whole story or it is not true"):
        validate_episode_narration_plan(plan_ep0)


# ---- text


def test_a_blank_sentence_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A unit with nothing to say is not a narration unit."""
    plan_ep1["units"][0]["text"] = ""
    with pytest.raises(ValueError, match="must not be empty"):
        validate_episode_narration_plan(plan_ep1)


def test_a_sentence_with_surrounding_whitespace_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Refused rather than trimmed, so the published text is the checked text."""
    plan_ep1["units"][0]["text"] += " "
    with pytest.raises(ValueError, match="surrounding whitespace"):
        validate_episode_narration_plan(plan_ep1)


def test_an_unknown_text_source_is_refused(plan_ep1: dict[str, Any]) -> None:
    """There are two ways a V1 sentence exists, and a model is not one of them."""
    plan_ep1["units"][0]["text_source"] = "LLM"
    with pytest.raises(ValueError, match="expected one of"):
        validate_episode_narration_plan(plan_ep1)


def test_a_mislabelled_text_source_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A carried summary and a composed sentence are different claims."""
    plan_ep1["units"][0]["text_source"] = "MEMORY_FACT_SUMMARY"
    with pytest.raises(ValueError, match="different claims about where the wording"):
        validate_episode_narration_plan(plan_ep1)


def test_a_fact_unit_relabelled_as_composed_is_refused(plan_ep2: dict[str, Any]) -> None:
    """And the other direction: a recorded sentence may not pose as a template's."""
    _unshown_unit(plan_ep2)["text_source"] = "NARRATION_TEMPLATE"
    with pytest.raises(ValueError, match="no memory fact wrote it|different claims"):
        validate_episode_narration_plan(plan_ep2)


def test_an_injected_causal_connective_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Causation the evidence never proved is not published, whoever wrote it."""
    unit = plan_ep1["units"][0]
    unit["text"] = "The wall rose because the law changed."
    with pytest.raises(ValueError, match="does not publish"):
        validate_episode_narration_plan(plan_ep1)


def test_an_injected_visual_claim_is_refused(plan_ep2: dict[str, Any]) -> None:
    """The case this layer exists to make impossible.

    The episode 1 -> 2 plan's first unit is a PRIMARY consequence Phase 22
    honestly left unshown. A sentence claiming the viewer was shown it is
    exactly the fabrication the ban list forbids.
    """
    unit = _unshown_unit(plan_ep2)
    unit["text"] = "The wall is shown standing at tick 22."
    with pytest.raises(ValueError, match="visibility the shot plan never granted"):
        validate_episode_narration_plan(plan_ep2)


# ---- fact identity


def test_a_template_unit_naming_a_fact_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A composed sentence has no memory record behind it to name."""
    _shown_unit(plan_ep1)["fact_id"] = "fact_" + "a" * 8
    with pytest.raises(ValueError, match="no memory fact wrote it"):
        validate_episode_narration_plan(plan_ep1)


def test_a_fact_unit_without_a_fact_id_is_refused(plan_ep2: dict[str, Any]) -> None:
    """A carried sentence must say which record it was carried from."""
    _unshown_unit(plan_ep2)["fact_id"] = None
    with pytest.raises(TypeError, match="must be a str"):
        validate_episode_narration_plan(plan_ep2)


# ---- visibility pairing


def test_an_unknown_visibility_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A beat is shown or it is not; Phase 22 offers no middle state."""
    plan_ep1["units"][0]["visibility"] = "PARTIAL"
    with pytest.raises(ValueError, match="expected one of"):
        validate_episode_narration_plan(plan_ep1)


def test_a_shown_unit_without_a_shot_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Being shown means being shown by something."""
    _shown_unit(plan_ep1)["shot_id"] = None
    with pytest.raises(TypeError, match="must be a str"):
        validate_episode_narration_plan(plan_ep1)


def test_a_shown_unit_carrying_an_unshown_reason_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A shown beat has no reason for having gone unshown."""
    _shown_unit(plan_ep1)["unshown_reason"] = "TRANSITION_BUDGET_EXHAUSTED"
    with pytest.raises(ValueError, match="was not left unshown"):
        validate_episode_narration_plan(plan_ep1)


def test_a_shown_unit_ending_before_it_starts_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A span runs forwards."""
    unit = _shown_unit(plan_ep1)
    unit["start_frame"], unit["end_frame"] = unit["end_frame"], unit["start_frame"]
    with pytest.raises(ValueError, match="before it starts"):
        validate_episode_narration_plan(plan_ep1)


def test_a_malformed_shot_citation_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A camera anchor is not a shot identifier."""
    _shown_unit(plan_ep1)["shot_id"] = "CAM_HERO_WORLD"
    with pytest.raises(ValueError, match="not a Phase 22 shot identifier"):
        validate_episode_narration_plan(plan_ep1)


@pytest.mark.parametrize("field", ["shot_id", "start_frame", "end_frame"])
def test_an_unshown_unit_may_not_invent_a_window(plan_ep2: dict[str, Any], field: str) -> None:
    """Never fabricate a shot or a timing window for a beat nobody framed."""
    value = "shot_0001" if field == "shot_id" else 25
    _unshown_unit(plan_ep2)[field] = value
    with pytest.raises(ValueError, match="framed by no shot|occupies no frames"):
        validate_episode_narration_plan(plan_ep2)


def test_an_unshown_unit_without_a_reason_is_refused(plan_ep2: dict[str, Any]) -> None:
    """An unshown beat always says why, because Phase 22 always did."""
    _unshown_unit(plan_ep2)["unshown_reason"] = None
    with pytest.raises(TypeError, match="must be a str"):
        validate_episode_narration_plan(plan_ep2)


def test_an_unknown_unshown_reason_is_refused(plan_ep2: dict[str, Any]) -> None:
    """The reason comes from Phase 22's closed vocabulary, not from prose."""
    _unshown_unit(plan_ep2)["unshown_reason"] = "DIRECTOR_PREFERENCE"
    with pytest.raises(ValueError, match="expected one of"):
        validate_episode_narration_plan(plan_ep2)


def test_the_empty_result_unit_carries_its_own_reason(plan_ep0: dict[str, Any]) -> None:
    """Nothing was emphasised, so there was nothing to point a camera at."""
    plan_ep0["units"][0]["unshown_reason"] = "TRANSITION_BUDGET_EXHAUSTED"
    with pytest.raises(ValueError, match="nothing to point a camera at"):
        validate_episode_narration_plan(plan_ep0)


# ---- accounting


@pytest.mark.parametrize("key", sorted(ACCOUNTING_KEYS))
def test_a_missing_accounting_key_is_refused(plan_ep1: dict[str, Any], key: str) -> None:
    """The verdict block is exact."""
    del plan_ep1["accounting"][key]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_episode_narration_plan(plan_ep1)


def test_an_extra_accounting_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Counting something this contract does not define is a different document."""
    plan_ep1["accounting"]["units_spoken"] = 1
    with pytest.raises(ValueError, match="unexpected keys"):
        validate_episode_narration_plan(plan_ep1)


@pytest.mark.parametrize("key", sorted(ACCOUNTING_KEYS))
def test_an_accounting_block_that_disagrees_with_the_units_is_refused(
    plan_ep1: dict[str, Any], key: str
) -> None:
    """The verdict is measured from the units present, never asserted beside them."""
    plan_ep1["accounting"][key] += 1
    with pytest.raises(ValueError, match="measured from the units present"):
        validate_episode_narration_plan(plan_ep1)


def test_a_dropped_unit_is_caught_by_accounting(plan_ep1: dict[str, Any]) -> None:
    """Silently omitting a beat is a count mismatch, not a judgement call."""
    plan_ep1["units"].pop()
    with pytest.raises(ValueError, match="measured from the units present"):
        validate_episode_narration_plan(plan_ep1)


def test_the_accounting_block_partitions_the_units(plan_ep1: dict[str, Any]) -> None:
    """Shown plus unshown is the whole plan, on the real documents."""
    accounting = plan_ep1["accounting"]
    assert accounting["units_shown"] + accounting["units_unshown"] == accounting["beats_total"]
    assert accounting["beats_total"] == len(plan_ep1["units"])
