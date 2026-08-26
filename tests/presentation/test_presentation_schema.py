"""The presentation plan's own contract: exact shape, exact identity, exact bounds.

Everything here validates or mutates a real canonical plan, so what is proven
is the contract over documents the pipeline actually produces. Every mutation
is one field, and every refusal is asserted by message, because a validator
that refuses for the wrong reason is two defects wearing one test.
"""

import copy
from typing import Any

import pytest

from living_diorama.presentation import validate_episode_presentation_plan
from living_diorama.presentation.presentation_spec import MAX_PRESENTATION_FRAME

# ---- the canonical plans validate


@pytest.mark.parametrize("episode", [0, 1, 2])
def test_every_canonical_plan_validates(episode: int) -> None:
    """Every canonical plan validates."""
    from .conftest import build_plan

    plan = build_plan(episode)
    assert validate_episode_presentation_plan(plan) is plan


# ---- the envelope


def test_a_non_dict_document_is_refused() -> None:
    """A non dict document is refused."""
    with pytest.raises(TypeError, match="must be a dict"):
        validate_episode_presentation_plan([])


def test_a_missing_top_level_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A missing top level key is refused."""
    del plan_ep1["policy"]
    with pytest.raises(ValueError, match="missing required keys.*policy"):
        validate_episode_presentation_plan(plan_ep1)


def test_an_extra_top_level_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An extra top level key is refused."""
    plan_ep1["notes"] = "reviewed"
    with pytest.raises(ValueError, match="unexpected keys.*notes"):
        validate_episode_presentation_plan(plan_ep1)


def test_a_wrong_format_tag_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A wrong format tag is refused."""
    plan_ep1["format"] = "living_diorama_episode_narration_delivery_plan"
    with pytest.raises(ValueError, match="declares format"):
        validate_episode_presentation_plan(plan_ep1)


def test_an_unsupported_schema_version_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An unsupported schema version is refused."""
    plan_ep1["schema_version"] = 2
    with pytest.raises(ValueError, match="unsupported schema version 2"):
        validate_episode_presentation_plan(plan_ep1)


def test_an_unknown_policy_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An unknown policy is refused."""
    plan_ep1["policy"] = "presentation_policy_v2"
    with pytest.raises(ValueError, match="declares policy"):
        validate_episode_presentation_plan(plan_ep1)


# ---- the source block


def test_a_missing_source_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A missing source key is refused."""
    del plan_ep1["source"]["motion_time_sha256"]
    with pytest.raises(ValueError, match="missing required keys.*motion_time_sha256"):
        validate_episode_presentation_plan(plan_ep1)


def test_an_extra_source_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An extra source key is refused."""
    plan_ep1["source"]["render_plan_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="unexpected keys.*render_plan_sha256"):
        validate_episode_presentation_plan(plan_ep1)


def test_story_plan_sha256_is_not_a_valid_source_key(plan_ep1: dict[str, Any]) -> None:
    """The forbidden-input rule, structural: no story digest may even exist here."""
    plan_ep1["source"]["story_plan_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="unexpected keys.*story_plan_sha256"):
        validate_episode_presentation_plan(plan_ep1)


def test_current_export_sha256_is_not_a_valid_source_key(plan_ep1: dict[str, Any]) -> None:
    """Current export sha256 is not a valid source key."""
    plan_ep1["source"]["current_export_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="unexpected keys.*current_export_sha256"):
        validate_episode_presentation_plan(plan_ep1)


def test_shot_plan_sha256_is_not_a_valid_source_key(plan_ep1: dict[str, Any]) -> None:
    """Shot plan sha256 is not a valid source key."""
    plan_ep1["source"]["shot_plan_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="unexpected keys.*shot_plan_sha256"):
        validate_episode_presentation_plan(plan_ep1)


@pytest.mark.parametrize(
    "field",
    [
        "delivery_plan_sha256",
        "motion_time_sha256",
        "narration_plan_sha256",
        "realization_plan_sha256",
    ],
)
def test_a_malformed_digest_is_refused(plan_ep1: dict[str, Any], field: str) -> None:
    """A malformed digest is refused."""
    plan_ep1["source"][field] = "not-a-digest"
    with pytest.raises(ValueError, match="64 lowercase hexadecimal"):
        validate_episode_presentation_plan(plan_ep1)


def test_an_unsupported_delivery_schema_version_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An unsupported delivery schema version is refused."""
    plan_ep1["source"]["delivery_schema_version"] = 2
    with pytest.raises(ValueError, match="derived from delivery schema version 2"):
        validate_episode_presentation_plan(plan_ep1)


def test_an_unsupported_narration_schema_version_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An unsupported narration schema version is refused."""
    plan_ep1["source"]["narration_schema_version"] = 2
    with pytest.raises(ValueError, match="derived from narration schema version 2"):
        validate_episode_presentation_plan(plan_ep1)


def test_an_unsupported_realization_schema_version_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An unsupported realization schema version is refused."""
    plan_ep1["source"]["realization_schema_version"] = 2
    with pytest.raises(ValueError, match="derived from realization schema version 2"):
        validate_episode_presentation_plan(plan_ep1)


def test_a_baseline_with_a_previous_episode_is_refused(plan_ep0: dict[str, Any]) -> None:
    """A baseline with a previous episode is refused."""
    plan_ep0["source"]["previous_episode"] = 3
    with pytest.raises(ValueError, match="but a baseline"):
        validate_episode_presentation_plan(plan_ep0)


def test_a_baseline_describing_a_nonzero_episode_is_refused(plan_ep0: dict[str, Any]) -> None:
    """A baseline describing a nonzero episode is refused."""
    plan_ep0["source"]["episode"] = 5
    with pytest.raises(ValueError, match="baseline describes episode 0 only"):
        validate_episode_presentation_plan(plan_ep0)


def test_a_transition_with_no_previous_episode_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A transition with no previous episode is refused."""
    plan_ep1["source"]["previous_episode"] = None
    with pytest.raises(TypeError):
        validate_episode_presentation_plan(plan_ep1)


def test_a_transition_joining_nonconsecutive_episodes_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A transition joining nonconsecutive episodes is refused."""
    plan_ep1["source"]["previous_episode"] = 4
    with pytest.raises(ValueError, match="a transition joins consecutive episodes"):
        validate_episode_presentation_plan(plan_ep1)


# ---- the timeline


def test_a_missing_timeline_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A missing timeline key is refused."""
    del plan_ep1["timeline"]["fps"]
    with pytest.raises(ValueError, match="missing required keys.*fps"):
        validate_episode_presentation_plan(plan_ep1)


def test_a_timeline_that_disagrees_with_its_own_arithmetic_is_refused(
    plan_ep1: dict[str, Any],
) -> None:
    """A timeline that disagrees with its own arithmetic is refused."""
    plan_ep1["timeline"]["end_frame"] = 9999
    with pytest.raises(ValueError, match="its own phases close on"):
        validate_episode_presentation_plan(plan_ep1)


def test_an_out_of_bounds_fps_is_refused(plan_ep1: dict[str, Any]) -> None:
    """An out of bounds fps is refused."""
    plan_ep1["timeline"]["fps"] = 0
    with pytest.raises(ValueError, match="fps must be within"):
        validate_episode_presentation_plan(plan_ep1)


# ---- segments: tiling, witness, minimality, dilation


def test_a_segment_gap_is_refused(plan_ep1: dict[str, Any]) -> None:
    """The first segment shrinks by one frame, opening a semantic gap.

    Its own presentation span is shrunk to match, so it still closes on its
    own arithmetic; only the tiling against the next segment is now broken.
    """
    first = plan_ep1["segments"][0]
    first["semantic_end_frame"] -= 1
    first["presentation_end_frame"] -= first["dwell_frames"]
    with pytest.raises(ValueError, match="previous segment left off"):
        validate_episode_presentation_plan(plan_ep1)


def test_a_segment_that_does_not_start_at_the_playback_domains_first_frame_is_refused(
    plan_ep1: dict[str, Any],
) -> None:
    """Dropping the first segment leaves the rest starting after frame 1."""
    remaining = plan_ep1["segments"][1:]
    for position, segment in enumerate(remaining, start=1):
        segment["segment_id"] = f"segment_{position:04d}"
    plan_ep1["segments"] = remaining
    with pytest.raises(ValueError, match="previous segment left off"):
        validate_episode_presentation_plan(plan_ep1)


def test_a_segment_overlap_is_refused(plan_ep1: dict[str, Any]) -> None:
    """The first segment grows by one frame, overlapping the next segment's onset.

    Its own presentation span grows to match, so it still closes on its own
    arithmetic; only the tiling against the next segment -- this time an
    overlap rather than a gap -- is now broken. The same inequality check
    catches both directions; this proves the overlap direction specifically.
    """
    first = plan_ep1["segments"][0]
    first["semantic_end_frame"] += 1
    first["presentation_end_frame"] += first["dwell_frames"]
    with pytest.raises(ValueError, match="previous segment left off"):
        validate_episode_presentation_plan(plan_ep1)


def test_a_semantic_reorder_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Two whole, individually valid segments swap list order.

    Distinct in construction from the gap and overlap tests above -- neither
    segment's own fields are touched at all. Segments[2] ([26, 60], dwell 1)
    and segments[3] ([61, 61], dwell 326) trade places, so the playback
    frames a reader of the list would encounter no longer appear in locked
    ascending order: frame 61 is listed before frame 26. The semantic tiling
    check fires on the very first mismatch it reaches.
    """
    segments = plan_ep1["segments"]
    id_2, id_3 = segments[2]["segment_id"], segments[3]["segment_id"]
    segments[2], segments[3] = segments[3], segments[2]
    segments[2]["segment_id"], segments[3]["segment_id"] = id_2, id_3
    with pytest.raises(ValueError, match="previous segment left off"):
        validate_episode_presentation_plan(plan_ep1)


def test_a_non_monotone_presentation_mapping_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Every segment after the first regresses its presentation coordinates by one frame.

    Distinct from the presentation-gap test (which shifts later segments
    forward) and from the window-overlap test (which is a window-level, not
    segment-level, check): here segment 1's declared presentation_start_frame
    (24) falls *behind* the cursor left by segment 0 (25), so segment 1's
    presentation span actually overlaps -- moves backward into -- segment
    0's own span, rather than merely failing to advance. The same
    presentation-cursor contiguity check catches the regression direction.
    """
    for later in plan_ep1["segments"][1:]:
        later["presentation_start_frame"] -= 1
        later["presentation_end_frame"] -= 1
    with pytest.raises(ValueError, match="presentation coordinates are contiguous"):
        validate_episode_presentation_plan(plan_ep1)


def test_segments_that_do_not_cover_the_final_playback_frame_are_refused(
    plan_ep1: dict[str, Any],
) -> None:
    """Segments that do not cover the final playback frame are refused."""
    last = plan_ep1["segments"][-1]
    last["semantic_end_frame"] -= 1
    last["presentation_end_frame"] -= last["dwell_frames"]
    with pytest.raises(ValueError, match="every playback frame is presented"):
        validate_episode_presentation_plan(plan_ep1)


def test_the_witness_frame_is_never_representable_in_a_segment(plan_ep0: dict[str, Any]) -> None:
    """Extending the final segment onto the witness frame is refused outright."""
    plan_ep0["segments"][-1]["semantic_end_frame"] = 193
    plan_ep0["segments"][-1]["presentation_end_frame"] += 1
    with pytest.raises(ValueError):
        validate_episode_presentation_plan(plan_ep0)


def test_a_dwell_below_one_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A dwell below one is refused."""
    plan_ep1["segments"][0]["dwell_frames"] = 0
    with pytest.raises(ValueError, match="dwell_frames must be within"):
        validate_episode_presentation_plan(plan_ep1)


def test_a_dwell_above_the_presentation_bound_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A dwell above the presentation bound is refused."""
    plan_ep1["segments"][1]["dwell_frames"] = MAX_PRESENTATION_FRAME + 1
    span_delta = MAX_PRESENTATION_FRAME + 1 - 109
    plan_ep1["segments"][1]["presentation_end_frame"] += span_delta
    for later in plan_ep1["segments"][2:]:
        later["presentation_start_frame"] += span_delta
        later["presentation_end_frame"] += span_delta
    with pytest.raises(ValueError):
        validate_episode_presentation_plan(plan_ep1)


def test_a_multi_frame_segment_with_dwell_above_one_is_refused(plan_ep1: dict[str, Any]) -> None:
    """Distributed dilation of moving footage is not representable."""
    segment = plan_ep1["segments"][0]
    segment["semantic_end_frame"] = segment["semantic_start_frame"] + 1
    segment["dwell_frames"] = 2
    segment["presentation_end_frame"] = segment["presentation_start_frame"] + 3
    for later in plan_ep1["segments"][1:]:
        later["presentation_start_frame"] += 2
        later["presentation_end_frame"] += 2
    with pytest.raises(ValueError, match="spans exactly one semantic frame"):
        validate_episode_presentation_plan(plan_ep1)


def test_adjacent_segments_sharing_a_dwell_are_refused(plan_ep1: dict[str, Any]) -> None:
    """A run that could have been one segment is not two."""
    segments = plan_ep1["segments"]
    # Split segment[0] ([1,24]@1) into two adjacent same-dwell segments.
    first, second = segments[0], segments[0]
    split_point = 12
    new_first = {**first, "semantic_end_frame": split_point, "presentation_end_frame": split_point}
    new_second = {
        **second,
        "segment_id": "segment_0002",
        "semantic_start_frame": split_point + 1,
        "presentation_start_frame": split_point + 1,
    }
    remaining = []
    for position, segment in enumerate(segments[1:], start=3):
        remaining.append({**segment, "segment_id": f"segment_{position:04d}"})
    plan_ep1["segments"] = [new_first, new_second, *remaining]
    with pytest.raises(ValueError, match="never share a dwell"):
        validate_episode_presentation_plan(plan_ep1)


def test_a_presentation_gap_between_segments_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A presentation gap between segments is refused."""
    for later in plan_ep1["segments"][1:]:
        later["presentation_start_frame"] += 1
        later["presentation_end_frame"] += 1
    with pytest.raises(ValueError, match="presentation coordinates are contiguous"):
        validate_episode_presentation_plan(plan_ep1)


def test_a_wrong_segment_id_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A wrong segment ID is refused."""
    plan_ep1["segments"][0]["segment_id"] = "segment_0099"
    with pytest.raises(ValueError, match="segment id is positional"):
        validate_episode_presentation_plan(plan_ep1)


def test_a_segment_missing_a_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A segment missing a key is refused."""
    del plan_ep1["segments"][0]["dwell_frames"]
    with pytest.raises(ValueError, match="missing required keys.*dwell_frames"):
        validate_episode_presentation_plan(plan_ep1)


def test_no_segments_at_all_is_refused(plan_ep1: dict[str, Any]) -> None:
    """No segments at all is refused."""
    plan_ep1["segments"] = []
    with pytest.raises(ValueError, match="carries no segments"):
        validate_episode_presentation_plan(plan_ep1)


# ---- windows


def test_a_wrong_window_id_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A wrong window ID is refused."""
    plan_ep1["windows"][0]["window_id"] = "window_0099"
    with pytest.raises(ValueError, match="window id is positional"):
        validate_episode_presentation_plan(plan_ep1)


def test_a_wrong_unit_id_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A wrong unit ID is refused."""
    plan_ep1["windows"][0]["unit_id"] = "unit_0099"
    with pytest.raises(ValueError, match="follows the narration plan's own order"):
        validate_episode_presentation_plan(plan_ep1)


def test_a_wrong_realization_id_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A wrong realization ID is refused."""
    plan_ep1["windows"][0]["realization_id"] = "realization_0099"
    with pytest.raises(ValueError, match="follows the narration plan's own order"):
        validate_episode_presentation_plan(plan_ep1)


def test_swapped_realization_ids_between_two_windows_are_refused(plan_ep1: dict[str, Any]) -> None:
    """Swapped realization ids between two windows are refused."""
    windows = plan_ep1["windows"]
    windows[0]["realization_id"], windows[1]["realization_id"] = (
        windows[1]["realization_id"],
        windows[0]["realization_id"],
    )
    with pytest.raises(ValueError):
        validate_episode_presentation_plan(plan_ep1)


def test_reordered_windows_are_refused(plan_ep1: dict[str, Any]) -> None:
    """Reordered windows are refused."""
    plan_ep1["windows"] = list(reversed(plan_ep1["windows"]))
    with pytest.raises(ValueError):
        validate_episode_presentation_plan(plan_ep1)


def test_a_duplicated_window_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A duplicated window is refused."""
    plan_ep1["windows"].append(copy.deepcopy(plan_ep1["windows"][0]))
    with pytest.raises(ValueError):
        validate_episode_presentation_plan(plan_ep1)


def test_no_windows_at_all_is_refused(plan_ep1: dict[str, Any]) -> None:
    """No windows at all is refused."""
    plan_ep1["windows"] = []
    plan_ep1["accounting"]["windows_total"] = 0
    with pytest.raises(ValueError, match="carries no windows"):
        validate_episode_presentation_plan(plan_ep1)


def test_overlapping_windows_are_refused(plan_ep1: dict[str, Any]) -> None:
    """Overlapping windows are refused."""
    plan_ep1["windows"][1]["presentation_start_frame"] = plan_ep1["windows"][0][
        "presentation_start_frame"
    ]
    with pytest.raises(ValueError, match="windows follow narration order and never overlap"):
        validate_episode_presentation_plan(plan_ep1)


def test_a_window_beyond_the_plans_own_total_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A window beyond the plans own total is refused."""
    plan_ep1["windows"][-1]["presentation_end_frame"] += 10_000
    with pytest.raises(ValueError, match="beyond the plan's own total"):
        validate_episode_presentation_plan(plan_ep1)


def test_a_window_that_ends_before_it_starts_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A window that ends before it starts is refused."""
    window = plan_ep1["windows"][0]
    window["presentation_end_frame"] = window["presentation_start_frame"] - 1
    with pytest.raises(ValueError, match="ends at frame .* before it starts"):
        validate_episode_presentation_plan(plan_ep1)


def test_a_window_presentation_frame_above_the_bound_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A window presentation frame above the bound is refused."""
    plan_ep1["windows"][-1]["presentation_end_frame"] = MAX_PRESENTATION_FRAME + 1
    with pytest.raises(ValueError):
        validate_episode_presentation_plan(plan_ep1)


# ---- accounting


def test_a_forged_presentation_frames_total_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A forged presentation frames total is refused."""
    plan_ep1["accounting"]["presentation_frames_total"] += 1
    with pytest.raises(ValueError, match="total presentation frames"):
        validate_episode_presentation_plan(plan_ep1)


def test_a_forged_segments_total_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A forged segments total is refused."""
    plan_ep1["accounting"]["segments_total"] += 1
    with pytest.raises(ValueError, match="declares .* segments but carries"):
        validate_episode_presentation_plan(plan_ep1)


def test_a_forged_windows_total_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A forged windows total is refused."""
    plan_ep1["accounting"]["windows_total"] += 1
    with pytest.raises(ValueError, match="declares .* windows but carries"):
        validate_episode_presentation_plan(plan_ep1)


def test_a_missing_accounting_key_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A missing accounting key is refused."""
    del plan_ep1["accounting"]["segments_total"]
    with pytest.raises(ValueError, match="missing required keys.*segments_total"):
        validate_episode_presentation_plan(plan_ep1)
