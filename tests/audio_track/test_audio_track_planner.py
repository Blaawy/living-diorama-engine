"""Deriving an Episode Audio Track Plan: the golden structural geometry."""

from typing import Any

import pytest

from living_diorama.audio_track.audio_track_planner import (
    build_episode_audio_track_plan_bytes,
    build_episode_audio_track_plan_document,
)


def test_episode_zero_golden_geometry(
    voice_manifest_ep0: dict[str, Any], presentation_ep0: dict[str, Any]
) -> None:
    """Episode zero: start_sample [0], audio_samples_total 192,000."""
    plan = build_episode_audio_track_plan_document(voice_manifest_ep0, presentation_ep0)
    assert plan["clock"]["audio_samples_total"] == 192_000
    assert [record["start_sample"] for record in plan["speech"]] == [0]


def test_episode_one_golden_geometry(
    voice_manifest_ep1: dict[str, Any], presentation_ep1: dict[str, Any]
) -> None:
    """Episode one: start_sample [24000, 168000, 528000], audio_samples_total 720,000."""
    plan = build_episode_audio_track_plan_document(voice_manifest_ep1, presentation_ep1)
    assert plan["clock"]["audio_samples_total"] == 720_000
    assert [record["start_sample"] for record in plan["speech"]] == [24000, 168000, 528000]


def test_episode_two_golden_geometry(
    voice_manifest_ep2: dict[str, Any], presentation_ep2: dict[str, Any]
) -> None:
    """Episode two: start_sample [0, 360000], audio_samples_total 552,000."""
    plan = build_episode_audio_track_plan_document(voice_manifest_ep2, presentation_ep2)
    assert plan["clock"]["audio_samples_total"] == 552_000
    assert [record["start_sample"] for record in plan["speech"]] == [0, 360000]


def test_derivation_is_stable_across_repeated_calls(
    voice_manifest_ep1: dict[str, Any], presentation_ep1: dict[str, Any]
) -> None:
    """Derivation is stable across repeated calls."""
    first = build_episode_audio_track_plan_bytes(voice_manifest_ep1, presentation_ep1)
    second = build_episode_audio_track_plan_bytes(voice_manifest_ep1, presentation_ep1)
    assert first == second


def test_the_source_block_binds_the_exact_offered_documents(
    voice_manifest_ep1: dict[str, Any], presentation_ep1: dict[str, Any]
) -> None:
    """The source block binds the exact offered documents by digest."""
    from living_diorama.persistence.json_codec import dumps_canonical
    from living_diorama.persistence.schema.state_hash import sha256_hex

    plan = build_episode_audio_track_plan_document(voice_manifest_ep1, presentation_ep1)
    assert plan["source"]["voice_manifest_sha256"] == sha256_hex(
        dumps_canonical(voice_manifest_ep1, "voice manifest")
    )
    assert plan["source"]["presentation_plan_sha256"] == sha256_hex(
        dumps_canonical(presentation_ep1, "presentation plan")
    )


def test_accounting_sums_to_the_track_total(
    voice_manifest_ep1: dict[str, Any], presentation_ep1: dict[str, Any]
) -> None:
    """speech_samples_total + silence_samples_total == audio_samples_total."""
    plan = build_episode_audio_track_plan_document(voice_manifest_ep1, presentation_ep1)
    accounting = plan["accounting"]
    assert (
        accounting["speech_samples_total"] + accounting["silence_samples_total"]
        == plan["clock"]["audio_samples_total"]
    )


def test_a_manifest_from_a_different_episode_is_refused(
    voice_manifest_ep1: dict[str, Any], presentation_ep2: dict[str, Any]
) -> None:
    """A manifest built for one episode joined against another episode's presentation is refused."""
    with pytest.raises(ValueError):
        build_episode_audio_track_plan_document(voice_manifest_ep1, presentation_ep2)


def test_a_manifest_never_presented_by_this_presentation_plan_is_refused(
    voice_manifest_ep0: dict[str, Any], presentation_ep1: dict[str, Any]
) -> None:
    """A manifest the presentation plan never named is refused."""
    with pytest.raises(ValueError):
        build_episode_audio_track_plan_document(voice_manifest_ep0, presentation_ep1)


def test_the_plan_carries_no_prose(
    voice_manifest_ep1: dict[str, Any], presentation_ep1: dict[str, Any]
) -> None:
    """The plan carries no realized text, WAV path, digest, or capacity."""
    plan = build_episode_audio_track_plan_document(voice_manifest_ep1, presentation_ep1)
    for record in plan["speech"]:
        assert "realized_text" not in record
        assert "text" not in record
        assert "file" not in record
        assert "sha256" not in record
        assert "capacity_samples" not in record
        assert "end_sample" not in record
