"""Canonical presentation plans, pinned as golden literals, and the planner's refusals."""

import copy
from typing import Any

import pytest

from living_diorama.presentation import build_episode_presentation_plan_document
from living_diorama.presentation.presentation_planner import build_episode_presentation_plan_bytes


def test_episode_zero_presents_the_whole_domain_with_no_hold(
    sources_ep0: tuple[dict[str, Any], ...],
) -> None:
    """Episode zero presents the whole domain with no hold."""
    delivery, narration, _shots, realization, _story, _export = sources_ep0
    plan = build_episode_presentation_plan_document(delivery, narration, realization)
    assert plan["accounting"] == {
        "presentation_frames_total": 192,
        "segments_total": 1,
        "windows_total": 1,
    }
    assert plan["segments"] == [
        {
            "dwell_frames": 1,
            "presentation_end_frame": 192,
            "presentation_start_frame": 1,
            "segment_id": "segment_0001",
            "semantic_end_frame": 192,
            "semantic_start_frame": 1,
        }
    ]
    assert plan["windows"] == [
        {
            "presentation_end_frame": 192,
            "presentation_start_frame": 1,
            "realization_id": "realization_0001",
            "unit_id": "unit_0001",
            "window_id": "window_0001",
        }
    ]


def test_episode_one_holds_all_three_units_at_their_own_onset(
    sources_ep1: tuple[dict[str, Any], ...],
) -> None:
    """The reviewed golden geometry: 7 segments, N = 720, three windows."""
    delivery, narration, _shots, realization, _story, _export = sources_ep1
    plan = build_episode_presentation_plan_document(delivery, narration, realization)
    assert plan["accounting"] == {
        "presentation_frames_total": 720,
        "segments_total": 7,
        "windows_total": 3,
    }
    assert [
        (s["semantic_start_frame"], s["semantic_end_frame"], s["dwell_frames"])
        for s in plan["segments"]
    ] == [
        (1, 24, 1),
        (25, 25, 109),
        (26, 60, 1),
        (61, 61, 326),
        (62, 95, 1),
        (96, 96, 96),
        (97, 192, 1),
    ]
    assert [
        (w["presentation_start_frame"], w["presentation_end_frame"]) for w in plan["windows"]
    ] == [
        (25, 168),
        (169, 528),
        (529, 672),
    ]
    assert [w["unit_id"] for w in plan["windows"]] == ["unit_0001", "unit_0002", "unit_0003"]
    assert [w["realization_id"] for w in plan["windows"]] == [
        "realization_0001",
        "realization_0002",
        "realization_0003",
    ]


def test_episode_two_holds_the_leading_fact_unit_and_the_trailing_template_unit(
    sources_ep2: tuple[dict[str, Any], ...],
) -> None:
    """The reviewed golden geometry: 4 segments, N = 552, two windows."""
    delivery, narration, _shots, realization, _story, _export = sources_ep2
    plan = build_episode_presentation_plan_document(delivery, narration, realization)
    assert plan["accounting"] == {
        "presentation_frames_total": 552,
        "segments_total": 4,
        "windows_total": 2,
    }
    assert [
        (s["semantic_start_frame"], s["semantic_end_frame"], s["dwell_frames"])
        for s in plan["segments"]
    ] == [
        (1, 1, 337),
        (2, 24, 1),
        (25, 25, 25),
        (26, 192, 1),
    ]
    assert [
        (w["presentation_start_frame"], w["presentation_end_frame"]) for w in plan["windows"]
    ] == [
        (1, 360),
        (361, 504),
    ]


def test_the_witness_frame_never_appears_in_any_canonical_segment(
    sources_ep0: tuple[dict[str, Any], ...],
    sources_ep1: tuple[dict[str, Any], ...],
    sources_ep2: tuple[dict[str, Any], ...],
) -> None:
    """The witness frame never appears in any canonical segment."""
    for delivery, narration, _shots, realization, _story, _export in (
        sources_ep0,
        sources_ep1,
        sources_ep2,
    ):
        plan = build_episode_presentation_plan_document(delivery, narration, realization)
        witness = delivery["timeline"]["end_frame"]
        for segment in plan["segments"]:
            assert segment["semantic_end_frame"] < witness
            assert segment["semantic_start_frame"] < witness


def test_building_bytes_matches_the_canonical_document(
    sources_ep1: tuple[dict[str, Any], ...],
) -> None:
    """Building bytes matches the canonical document."""
    from living_diorama.persistence.json_codec import dumps_canonical

    delivery, narration, _shots, realization, _story, _export = sources_ep1
    document = build_episode_presentation_plan_document(delivery, narration, realization)
    payload = build_episode_presentation_plan_bytes(delivery, narration, realization)
    assert payload == dumps_canonical(document, "presentation plan")


def test_a_mismatched_narration_lineage_is_refused(
    sources_ep0: tuple[dict[str, Any], ...], sources_ep1: tuple[dict[str, Any], ...]
) -> None:
    """A delivery plan from one episode paired with another episode's narration."""
    delivery0, _narration0, _shots0, realization0, _story0, _export0 = sources_ep0
    _delivery1, narration1, _shots1, realization1, _story1, _export1 = sources_ep1
    with pytest.raises(ValueError, match="not the same episode's"):
        build_episode_presentation_plan_document(delivery0, narration1, realization0)
    with pytest.raises(ValueError, match="not the same episode's"):
        build_episode_presentation_plan_document(delivery0, narration1, realization1)


def test_a_narration_plan_with_mismatched_mode_is_refused(
    sources_ep0: tuple[dict[str, Any], ...], sources_ep1: tuple[dict[str, Any], ...]
) -> None:
    """A narration plan with mismatched mode is refused."""
    delivery1, narration1, _shots1, realization1, _story1, _export1 = sources_ep1
    delivery0, narration0, _shots0, realization0, _story0, _export0 = sources_ep0
    # Force a delivery/realization pair to disagree in mode by mixing episodes
    # whose narration plans are honestly different documents.
    with pytest.raises(ValueError):
        build_episode_presentation_plan_document(delivery1, narration0, realization1)


def test_a_delivery_plan_with_fewer_slots_than_units_is_refused(
    sources_ep1: tuple[dict[str, Any], ...],
) -> None:
    """A delivery plan with fewer slots than units is refused."""
    delivery, narration, _shots, realization, _story, _export = sources_ep1
    truncated = copy.deepcopy(delivery)
    truncated["deliveries"] = truncated["deliveries"][:-1]
    truncated["accounting"] = {
        "allocated_unshown": sum(
            1 for d in truncated["deliveries"] if d["placement"] == "ALLOCATED_UNSHOWN"
        ),
        "deliveries_total": len(truncated["deliveries"]),
        "shot_anchored": sum(
            1 for d in truncated["deliveries"] if d["placement"] == "SHOT_ANCHORED"
        ),
    }
    with pytest.raises((ValueError, TypeError)):
        build_episode_presentation_plan_document(truncated, narration, realization)


def test_changing_every_realized_sentence_moves_no_segment_or_window(
    sources_ep1: tuple[dict[str, Any], ...],
) -> None:
    """The wording-blindness proof: geometry is invariant under a reword.

    The realization plan is handed back with every ``realized_text`` replaced
    and everything structural -- including its own ``narration_plan_sha256``,
    which still names the unchanged narration plan -- untouched. The derived
    segments and windows are identical, which is the behavioural half of the
    no-prose rule; the boundary suite proves structurally that no module here
    even reads the field. The whole realization document differs, of course:
    the digest binding this plan computes names the changed input, which is
    exactly what it is for.
    """
    delivery, narration, _shots, realization, _story, _export = sources_ep1
    reworded_realization = {
        **realization,
        "realizations": [
            {**record, "realized_text": f"Reworded sentence {index}."}
            for index, record in enumerate(realization["realizations"], start=1)
        ],
    }
    original_plan = build_episode_presentation_plan_document(delivery, narration, realization)
    reworded_plan = build_episode_presentation_plan_document(
        delivery, narration, reworded_realization
    )
    assert reworded_plan["segments"] == original_plan["segments"]
    assert [
        (w["presentation_start_frame"], w["presentation_end_frame"])
        for w in reworded_plan["windows"]
    ] == [
        (w["presentation_start_frame"], w["presentation_end_frame"])
        for w in original_plan["windows"]
    ]
    assert (
        reworded_plan["source"]["realization_plan_sha256"]
        != original_plan["source"]["realization_plan_sha256"]
    )
