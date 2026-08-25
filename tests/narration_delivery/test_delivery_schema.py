"""The delivery plan's own contract: exact shape, exact identity, exact bounds.

Everything here validates or mutates a real canonical plan, so what is proven
is the contract over documents the pipeline actually produces. Every mutation
is one field, and every refusal is asserted by message, because a validator
that refuses for the wrong reason is two defects wearing one test.
"""

from typing import Any

import pytest

from living_diorama.cinematic.cinematic_schema_v1 import TIMELINE_KEYS
from living_diorama.narration_delivery import (
    DELIVERY_TIMELINE_KEYS,
    validate_episode_narration_delivery_plan,
)

# ---- the canonical plans validate


@pytest.mark.parametrize("episode", [0, 1, 2])
def test_every_canonical_plan_validates(episode: int) -> None:
    """The three real plans pass their own contract."""
    from .conftest import build_plan

    plan = build_plan(episode)
    assert validate_episode_narration_delivery_plan(plan) is plan


def test_the_timeline_key_set_still_agrees_with_phase_twenty_two() -> None:
    """The restated clock's shape is pinned against the cinematic contract.

    Restated rather than imported, so this schema version owns its own shape;
    this test is what makes drift between the two contracts fail loudly.
    """
    assert DELIVERY_TIMELINE_KEYS == TIMELINE_KEYS


# ---- the envelope


def test_a_non_dict_document_is_refused() -> None:
    """A list is not a plan."""
    with pytest.raises(TypeError, match="must be a dict"):
        validate_episode_narration_delivery_plan([])


def test_a_missing_top_level_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An incomplete plan is refused, never guessed at."""
    del plan_ep1["policy"]
    with pytest.raises(ValueError, match="missing required keys.*policy"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_an_extra_top_level_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A key this contract does not describe was written by something else."""
    plan_ep1["notes"] = "reviewed"
    with pytest.raises(ValueError, match="unexpected keys.*notes"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_wrong_format_tag_is_refused(plan_ep1: dict[str, Any]) -> None:
    """The tag names this exact contract."""
    plan_ep1["format"] = "living_diorama_episode_narration_plan"
    with pytest.raises(ValueError, match="declares format"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_an_unsupported_schema_version_is_refused(plan_ep1: dict[str, Any]) -> None:
    """No migration is attempted; an unknown version is refused loudly."""
    plan_ep1["schema_version"] = 2
    with pytest.raises(ValueError, match="unsupported schema version 2"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_an_unknown_policy_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A slot cut under another policy must never be mistaken for one of these."""
    plan_ep1["policy"] = "narration_delivery_policy_v2"
    with pytest.raises(ValueError, match="declares policy"):
        validate_episode_narration_delivery_plan(plan_ep1)


# ---- the source block


def test_a_missing_source_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Every binding is present or the plan is incomplete."""
    del plan_ep1["source"]["motion_time_sha256"]
    with pytest.raises(ValueError, match="missing required keys.*motion_time_sha256"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_render_manifest_binding_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Execution proof is exactly the kind of extra this contract refuses.

    A delivery slot is semantic presentation time; binding a manifest would tie
    this document's stability to render execution and it would stop surviving
    a re-render of an unchanged episode.
    """
    plan_ep1["source"]["render_manifest_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="unexpected keys.*render_manifest_sha256"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_render_plan_binding_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Neither half of Phase 23 is an input to this layer."""
    plan_ep1["source"]["render_plan_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="unexpected keys.*render_plan_sha256"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_malformed_digest_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A digest field is 64 lowercase hex characters or it is not a digest."""
    plan_ep1["source"]["narration_plan_sha256"] = "not-a-digest"
    with pytest.raises(ValueError, match="64 lowercase hexadecimal"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_an_unknown_mode_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A plan schedules a baseline or a transition; there is no third mode."""
    plan_ep1["source"]["mode"] = "montage"
    with pytest.raises(ValueError, match="expected one of"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_an_unsupported_narration_version_is_refused(plan_ep1: dict[str, Any]) -> None:
    """This build schedules narration schema version 1 only."""
    plan_ep1["source"]["narration_schema_version"] = 2
    with pytest.raises(ValueError, match="narration schema version 2"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_an_unsupported_shot_version_is_refused(plan_ep1: dict[str, Any]) -> None:
    """And shot schema version 1 only."""
    plan_ep1["source"]["shot_schema_version"] = 3
    with pytest.raises(ValueError, match="shot schema version 3"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_baseline_with_a_previous_episode_is_refused(plan_ep0: dict[str, Any]) -> None:
    """A baseline follows no episode."""
    plan_ep0["source"]["previous_episode"] = 4
    with pytest.raises(ValueError, match="follows no episode"):
        validate_episode_narration_delivery_plan(plan_ep0)


def test_a_baseline_beyond_episode_zero_is_refused(plan_ep0: dict[str, Any]) -> None:
    """A baseline describes episode 0 only."""
    plan_ep0["source"]["episode"] = 3
    with pytest.raises(ValueError, match="episode 0 only"):
        validate_episode_narration_delivery_plan(plan_ep0)


def test_a_transition_without_a_previous_episode_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A transition names the episode it follows."""
    plan_ep1["source"]["previous_episode"] = None
    with pytest.raises(TypeError, match="previous_episode"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_non_consecutive_transition_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A transition joins consecutive episodes."""
    plan_ep1["source"]["previous_episode"] = 5
    with pytest.raises(ValueError, match="consecutive episodes"):
        validate_episode_narration_delivery_plan(plan_ep1)


# ---- the timeline block


def test_a_missing_timeline_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """The restated clock is complete or it is not a clock."""
    del plan_ep1["timeline"]["fps"]
    with pytest.raises(ValueError, match="missing required keys.*fps"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_an_extra_timeline_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Seconds are derivable, never stored; frames are the only unit here."""
    plan_ep1["timeline"]["duration_seconds"] = 8.0
    with pytest.raises(ValueError, match="unexpected keys.*duration_seconds"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_fractional_frame_count_is_refused(plan_ep1: dict[str, Any]) -> None:
    """The clock is integer frames; nothing here rounds."""
    plan_ep1["timeline"]["transition_frames"] = 120.5
    with pytest.raises(TypeError, match="transition_frames"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_zero_fps_clock_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A clock ticks at least once per second."""
    plan_ep1["timeline"]["fps"] = 0
    with pytest.raises(ValueError, match=r"fps must be within \[1, 240\]"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_an_implausible_fps_is_refused(plan_ep1: dict[str, Any]) -> None:
    """The restated clock is held to Phase 22's own upper bound on frame rate."""
    plan_ep1["timeline"]["fps"] = 241
    with pytest.raises(ValueError, match=r"fps must be within \[1, 240\]"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_zero_length_phase_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Phase 22's own floor: every timeline phase is at least one frame.

    The mutation keeps the closure arithmetic consistent, so only the
    restated bound itself can refuse it.
    """
    plan_ep1["timeline"]["start_hold_frames"] = 0
    plan_ep1["timeline"]["transition_start"] = 1
    plan_ep1["timeline"]["transition_end"] = 121
    plan_ep1["timeline"]["end_frame"] = 169
    with pytest.raises(ValueError, match=r"start_hold_frames must be within \[1, 100000\]"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_an_implausible_frame_number_is_refused(plan_ep1: dict[str, Any]) -> None:
    """And Phase 22's own cap on a plausible frame number."""
    plan_ep1["timeline"]["end_frame"] = 100_001
    with pytest.raises(ValueError, match=r"end_frame must be within \[0, 100000\]"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_timeline_that_does_not_close_is_refused(plan_ep1: dict[str, Any]) -> None:
    """The declared end frame must equal the sum of the declared phases."""
    plan_ep1["timeline"]["end_frame"] = 194
    with pytest.raises(ValueError, match="close on 193"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_wrong_transition_start_is_refused(plan_ep1: dict[str, Any]) -> None:
    """The derived boundaries are arithmetic, not free fields."""
    plan_ep1["timeline"]["transition_start"] = 26
    with pytest.raises(ValueError, match="transition_start"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_wrong_transition_end_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Both of them."""
    plan_ep1["timeline"]["transition_end"] = 144
    with pytest.raises(ValueError, match="transition_end"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_negative_phase_length_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A phase length is a frame count; the shared integer vocabulary refuses it."""
    plan_ep1["timeline"]["start_hold_frames"] = -1
    with pytest.raises(ValueError, match="start_hold_frames must be >= 0"):
        validate_episode_narration_delivery_plan(plan_ep1)


# ---- delivery records


def test_a_missing_record_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A record is a slot and an identity, all five fields of them."""
    del plan_ep1["deliveries"][0]["placement"]
    with pytest.raises(ValueError, match="missing required keys.*placement"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_text_field_on_a_record_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Wording stays authoritative in the narration plan, never copied here."""
    plan_ep1["deliveries"][0]["text"] = "At tick 21, the wall changed state."
    with pytest.raises(ValueError, match="unexpected keys.*text"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_visibility_copy_on_a_record_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Visibility is inherited through unit_id; a copy could drift from it."""
    plan_ep1["deliveries"][0]["visibility"] = "SHOWN"
    with pytest.raises(ValueError, match="unexpected keys.*visibility"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_an_audio_field_on_a_record_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A future voice layer's fields do not start here."""
    plan_ep1["deliveries"][0]["audio_asset"] = "unit_0001.wav"
    with pytest.raises(ValueError, match="unexpected keys.*audio_asset"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_caption_field_on_a_record_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Nor a future caption layer's."""
    plan_ep1["deliveries"][0]["caption_cue"] = "00:00:01,041 --> 00:00:02,500"
    with pytest.raises(ValueError, match="unexpected keys.*caption_cue"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_seconds_field_on_a_record_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Frames on the pinned clock are the only time unit a record speaks."""
    plan_ep1["deliveries"][0]["start_seconds"] = 1.0
    with pytest.raises(ValueError, match="unexpected keys.*start_seconds"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_an_out_of_position_delivery_id_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A delivery id is positional, not a free label."""
    plan_ep1["deliveries"][0]["delivery_id"] = "delivery_0002"
    with pytest.raises(ValueError, match="positional"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_an_out_of_position_unit_id_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A slot schedules the unit at its own position, in the plan's own order."""
    plan_ep1["deliveries"][0]["unit_id"] = "unit_0003"
    with pytest.raises(ValueError, match="one slot per unit"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_reordered_records_are_refused(plan_ep1: dict[str, Any]) -> None:
    """Swapping two records breaks both positional identities at once."""
    deliveries = plan_ep1["deliveries"]
    deliveries[0], deliveries[1] = deliveries[1], deliveries[0]
    with pytest.raises(ValueError, match="positional"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_duplicated_record_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A unit scheduled twice is unrepresentable under positional identifiers."""
    plan_ep1["deliveries"].append(dict(plan_ep1["deliveries"][-1]))
    with pytest.raises(ValueError, match="positional|accounting"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_an_omitted_record_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Dropping the trapped PRIMARY consequence breaks the accounting."""
    del plan_ep1["deliveries"][1]
    with pytest.raises(ValueError, match="positional|accounting"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_an_unknown_placement_is_refused(plan_ep1: dict[str, Any]) -> None:
    """The placement vocabulary is closed at two."""
    plan_ep1["deliveries"][0]["placement"] = "VOICE_OVER"
    with pytest.raises(ValueError, match="expected one of"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_an_inverted_slot_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A slot ends at or after the frame it starts on."""
    plan_ep1["deliveries"][0]["end_frame"] = 24
    with pytest.raises(ValueError, match="before it starts"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_fractional_frame_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Slots are integer frames."""
    plan_ep1["deliveries"][0]["start_frame"] = 25.5
    with pytest.raises(TypeError, match="start_frame"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_slot_before_playback_is_refused(plan_ep2: dict[str, Any]) -> None:
    """Frame zero is not on the clock."""
    plan_ep2["deliveries"][0]["start_frame"] = 0
    with pytest.raises(ValueError, match="outside the playback domain"):
        validate_episode_narration_delivery_plan(plan_ep2)


def test_a_slot_on_the_witness_frame_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Frame 193 is rendered once as evidence and never played back."""
    plan_ep1["deliveries"][2]["end_frame"] = 193
    with pytest.raises(ValueError, match="never played back"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_overlapping_slots_are_refused(plan_ep1: dict[str, Any]) -> None:
    """One narrator, one sentence at a time."""
    plan_ep1["deliveries"][1]["start_frame"] = 60
    with pytest.raises(ValueError, match="never overlap"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_slot_crossing_narration_order_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A later unit never speaks before an earlier one."""
    plan_ep1["deliveries"][1]["start_frame"] = 1
    plan_ep1["deliveries"][1]["end_frame"] = 24
    with pytest.raises(ValueError, match="follow narration order"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_adjacent_slots_are_allowed(plan_ep1: dict[str, Any]) -> None:
    """The canonical fold's slots touch exactly, and that is the contract."""
    first = plan_ep1["deliveries"][0]
    second = plan_ep1["deliveries"][1]
    assert second["start_frame"] == first["end_frame"] + 1
    validate_episode_narration_delivery_plan(plan_ep1)


def test_an_empty_deliveries_list_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Every narration plan holds at least one unit, so a plan schedules one."""
    plan_ep1["deliveries"] = []
    with pytest.raises(ValueError, match="carries no deliveries"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_wrong_container_type_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A block of the wrong shape is a type error, not something to coerce."""
    plan_ep1["deliveries"] = {}
    with pytest.raises(TypeError, match="deliveries must be a list, got dict"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_wrong_source_container_type_is_refused(plan_ep1: dict[str, Any]) -> None:
    """The source block is a document, never a list of one."""
    plan_ep1["source"] = [plan_ep1["source"]]
    with pytest.raises(TypeError, match="source must be a dict, got list"):
        validate_episode_narration_delivery_plan(plan_ep1)


# ---- accounting


def test_asserted_accounting_must_match_measured(plan_ep1: dict[str, Any]) -> None:
    """The verdict is measured from the records, never asserted beside them."""
    plan_ep1["accounting"]["shot_anchored"] = 3
    with pytest.raises(ValueError, match="measured from the records"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_a_missing_accounting_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """The aggregate verdict is complete or absent, never partial."""
    del plan_ep1["accounting"]["allocated_unshown"]
    with pytest.raises(ValueError, match="missing required keys.*allocated_unshown"):
        validate_episode_narration_delivery_plan(plan_ep1)


def test_an_extra_accounting_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """No field this contract does not describe."""
    plan_ep1["accounting"]["units_spoken"] = 3
    with pytest.raises(ValueError, match="unexpected keys.*units_spoken"):
        validate_episode_narration_delivery_plan(plan_ep1)
