"""Deriving an Episode Caption Plan: the golden structural geometry, and text carriage."""

import copy

import pytest

from living_diorama.caption.caption_planner import (
    build_episode_caption_plan_bytes,
    build_episode_caption_plan_document,
    caption_texts,
)


def test_ep0_golden_geometry(realization_ep0, presentation_ep0) -> None:
    """Ep0 golden geometry."""
    plan = build_episode_caption_plan_document(realization_ep0, presentation_ep0)
    assert [
        (c["presentation_start_frame"], c["presentation_end_frame"]) for c in plan["captions"]
    ] == [
        (1, 192),
    ]


def test_ep1_golden_geometry(realization_ep1, presentation_ep1) -> None:
    """Ep1 golden geometry."""
    plan = build_episode_caption_plan_document(realization_ep1, presentation_ep1)
    assert [
        (c["presentation_start_frame"], c["presentation_end_frame"]) for c in plan["captions"]
    ] == [
        (25, 168),
        (169, 528),
        (529, 672),
    ]


def test_ep2_golden_geometry(realization_ep2, presentation_ep2) -> None:
    """Ep2 golden geometry."""
    plan = build_episode_caption_plan_document(realization_ep2, presentation_ep2)
    assert [
        (c["presentation_start_frame"], c["presentation_end_frame"]) for c in plan["captions"]
    ] == [
        (1, 360),
        (361, 504),
    ]


def test_captions_carry_realized_text_verbatim(realization_ep1, presentation_ep1) -> None:
    """Captions carry realized text verbatim."""
    plan = build_episode_caption_plan_document(realization_ep1, presentation_ep1)
    expected_texts = [record["realized_text"] for record in realization_ep1["realizations"]]
    actual_texts = [cue["caption_text"] for cue in plan["captions"]]
    assert actual_texts == expected_texts


def test_caption_texts_returns_exact_sentences(realization_ep1) -> None:
    """Caption texts returns exact sentences."""
    texts = caption_texts(realization_ep1)
    expected = [record["realized_text"] for record in realization_ep1["realizations"]]
    assert texts == expected


def test_caption_ids_positional(realization_ep1, presentation_ep1) -> None:
    """Caption ids positional."""
    plan = build_episode_caption_plan_document(realization_ep1, presentation_ep1)
    assert [c["caption_id"] for c in plan["captions"]] == [
        "caption_0001",
        "caption_0002",
        "caption_0003",
    ]


def test_window_id_carried_from_presentation(realization_ep1, presentation_ep1) -> None:
    """Window ID carried from presentation."""
    plan = build_episode_caption_plan_document(realization_ep1, presentation_ep1)
    for cue, window in zip(plan["captions"], presentation_ep1["windows"], strict=True):
        assert cue["window_id"] == window["window_id"]


def test_join_refuses_mismatched_episode(realization_ep1, presentation_ep2) -> None:
    """Join refuses mismatched episode."""
    with pytest.raises(ValueError):
        build_episode_caption_plan_document(realization_ep1, presentation_ep2)


def test_refuses_unit_count_mismatch(realization_ep1, presentation_ep1) -> None:
    """Refuses unit count mismatch."""
    tampered_realization = copy.deepcopy(realization_ep1)
    tampered_realization["realizations"] = tampered_realization["realizations"][:1]
    tampered_realization["accounting"] = dict(tampered_realization["accounting"])
    tampered_realization["accounting"]["realizations_total"] = 1
    tampered_realization["accounting"]["template_backed"] = min(
        1, tampered_realization["accounting"]["template_backed"]
    )
    tampered_realization["accounting"]["fact_backed"] = (
        1 - tampered_realization["accounting"]["template_backed"]
    )
    with pytest.raises((ValueError, TypeError)):
        build_episode_caption_plan_document(tampered_realization, presentation_ep1)


def test_frames_never_derived_from_text_length(sources_ep1) -> None:
    """Mutating realized_text moves caption_text exactly, but never moves a frame.

    The presentation plan is rebuilt from the mutated realization too, since
    a presentation plan binds its realization plan's digest -- otherwise the
    join would refuse on an unrelated digest mismatch before this claim is
    ever exercised.
    """
    from living_diorama.presentation import build_episode_presentation_plan_document

    realization, presentation, delivery, narration, shots, story, export = sources_ep1
    plan_before = build_episode_caption_plan_document(realization, presentation)

    tampered_realization = copy.deepcopy(realization)
    original = tampered_realization["realizations"][0]["realized_text"]
    tampered_realization["realizations"][0]["realized_text"] = (
        original.replace("law", "rule", 1) if "law" in original else original + " Indeed."
    )
    tampered_presentation = build_episode_presentation_plan_document(
        delivery, narration, tampered_realization
    )
    plan_after = build_episode_caption_plan_document(tampered_realization, tampered_presentation)

    frames_before = [
        (c["presentation_start_frame"], c["presentation_end_frame"])
        for c in plan_before["captions"]
    ]
    frames_after = [
        (c["presentation_start_frame"], c["presentation_end_frame"]) for c in plan_after["captions"]
    ]
    assert frames_before == frames_after
    assert plan_after["captions"][0]["caption_text"] != plan_before["captions"][0]["caption_text"]


def test_bytes_round_trip(realization_ep1, presentation_ep1) -> None:
    """Bytes round trip."""
    from living_diorama.persistence.json_codec import loads_canonical

    payload = build_episode_caption_plan_bytes(realization_ep1, presentation_ep1)
    document = loads_canonical(payload, "caption plan")
    assert document["accounting"]["captions_total"] == 3


def test_deterministic_bytes_across_two_calls(realization_ep1, presentation_ep1) -> None:
    """Deterministic bytes across two calls."""
    first = build_episode_caption_plan_bytes(realization_ep1, presentation_ep1)
    second = build_episode_caption_plan_bytes(realization_ep1, presentation_ep1)
    assert first == second


def test_refuses_wrong_realization_type(presentation_ep1) -> None:
    """Refuses wrong realization type."""
    with pytest.raises(TypeError):
        build_episode_caption_plan_document([], presentation_ep1)


def test_refuses_wrong_presentation_type(realization_ep1) -> None:
    """Refuses wrong presentation type."""
    with pytest.raises(TypeError):
        build_episode_caption_plan_document(realization_ep1, [])
