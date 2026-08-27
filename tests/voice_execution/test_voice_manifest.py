"""Building an Episode Voice Manifest from recorded voice execution results."""

import hashlib
from typing import Any

import pytest

from living_diorama.voice_execution import (
    build_episode_voice_manifest_bytes,
    build_episode_voice_manifest_document,
)
from living_diorama.voice_execution.voice_execution_spec import UNIT_RESULT_FIELDS


def _synthetic_results(plan: dict[str, Any]) -> dict[int, dict[str, object]]:
    results: dict[int, dict[str, object]] = {}
    for position, unit in enumerate(plan["voice_units"], start=1):
        samples = min(24000, unit["capacity_samples"])
        payload = b"\x00" * (44 + samples * 2)
        results[position] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "speech_samples": samples,
        }
    return results


def test_the_manifest_is_built_and_round_trips_canonically(
    plan_ep1: dict[str, Any], voice_environment: dict[str, str]
) -> None:
    """The manifest is built and round-trips canonically."""
    results = _synthetic_results(plan_ep1)
    document = build_episode_voice_manifest_document(
        voice_plan=plan_ep1, results=results, environment=voice_environment
    )
    payload = build_episode_voice_manifest_bytes(
        voice_plan=plan_ep1, results=results, environment=voice_environment
    )
    assert document["completeness"]["complete"] is True
    assert document["completeness"]["voice_units_synthesized"] == len(plan_ep1["voice_units"])
    from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical

    assert loads_canonical(payload, "voice manifest") == document
    assert dumps_canonical(document, "voice manifest") == payload


def test_a_missing_result_refuses_the_build(
    plan_ep1: dict[str, Any], voice_environment: dict[str, str]
) -> None:
    """A missing result refuses the build; a manifest is never written for a partial episode."""
    results = _synthetic_results(plan_ep1)
    del results[1]
    with pytest.raises(ValueError, match="no execution result"):
        build_episode_voice_manifest_document(
            voice_plan=plan_ep1, results=results, environment=voice_environment
        )


def test_an_extra_result_position_refuses_the_build(
    plan_ep1: dict[str, Any], voice_environment: dict[str, str]
) -> None:
    """A result naming a position the plan never planned refuses the build."""
    results = _synthetic_results(plan_ep1)
    results[999] = {"bytes": 100, "sha256": hashlib.sha256(b"x").hexdigest(), "speech_samples": 1}
    with pytest.raises(ValueError, match="never planned"):
        build_episode_voice_manifest_document(
            voice_plan=plan_ep1, results=results, environment=voice_environment
        )


def test_the_exact_three_field_result_is_accepted(
    plan_ep1: dict[str, Any], voice_environment: dict[str, str]
) -> None:
    """A result carrying exactly UNIT_RESULT_FIELDS, no more and no fewer, is accepted."""
    results = _synthetic_results(plan_ep1)
    assert set(results[1].keys()) == set(UNIT_RESULT_FIELDS)
    document = build_episode_voice_manifest_document(
        voice_plan=plan_ep1, results=results, environment=voice_environment
    )
    assert document["completeness"]["complete"] is True


def test_a_result_missing_bytes_refuses_the_build(
    plan_ep1: dict[str, Any], voice_environment: dict[str, str]
) -> None:
    """A result missing the required `bytes` field refuses the build."""
    results = _synthetic_results(plan_ep1)
    del results[1]["bytes"]
    with pytest.raises(ValueError, match="exactly"):
        build_episode_voice_manifest_document(
            voice_plan=plan_ep1, results=results, environment=voice_environment
        )


def test_a_result_missing_sha256_refuses_the_build(
    plan_ep1: dict[str, Any], voice_environment: dict[str, str]
) -> None:
    """A result missing the required `sha256` field refuses the build."""
    results = _synthetic_results(plan_ep1)
    del results[1]["sha256"]
    with pytest.raises(ValueError, match="exactly"):
        build_episode_voice_manifest_document(
            voice_plan=plan_ep1, results=results, environment=voice_environment
        )


def test_a_result_missing_speech_samples_refuses_the_build(
    plan_ep1: dict[str, Any], voice_environment: dict[str, str]
) -> None:
    """A result missing the required `speech_samples` field refuses the build."""
    results = _synthetic_results(plan_ep1)
    del results[1]["speech_samples"]
    with pytest.raises(ValueError, match="exactly"):
        build_episode_voice_manifest_document(
            voice_plan=plan_ep1, results=results, environment=voice_environment
        )


def test_a_result_with_an_extra_key_refuses_the_build(
    plan_ep1: dict[str, Any], voice_environment: dict[str, str]
) -> None:
    """A result carrying one key beyond UNIT_RESULT_FIELDS refuses the build."""
    results = _synthetic_results(plan_ep1)
    results[1]["duration_seconds"] = 1.5
    with pytest.raises(ValueError, match="exactly"):
        build_episode_voice_manifest_document(
            voice_plan=plan_ep1, results=results, environment=voice_environment
        )


def test_a_non_dict_result_entry_is_refused_cleanly(
    plan_ep1: dict[str, Any], voice_environment: dict[str, str]
) -> None:
    """A single result entry that is not itself a dict is refused cleanly."""
    results = _synthetic_results(plan_ep1)
    results[1] = ["bytes", "sha256", "speech_samples"]  # type: ignore[assignment]
    with pytest.raises(TypeError, match="must be a dict"):
        build_episode_voice_manifest_document(
            voice_plan=plan_ep1, results=results, environment=voice_environment
        )


def test_a_result_overflowing_capacity_refuses_the_build(
    plan_ep1: dict[str, Any], voice_environment: dict[str, str]
) -> None:
    """A unit whose measured speech overflows its own capacity refuses the whole build."""
    results = _synthetic_results(plan_ep1)
    capacity = plan_ep1["voice_units"][0]["capacity_samples"]
    results[1]["speech_samples"] = capacity + 1
    with pytest.raises(ValueError, match="capacity"):
        build_episode_voice_manifest_document(
            voice_plan=plan_ep1, results=results, environment=voice_environment
        )


def test_a_non_dict_results_is_refused(
    plan_ep1: dict[str, Any], voice_environment: dict[str, str]
) -> None:
    """A non-dict results argument is refused."""
    with pytest.raises(TypeError):
        build_episode_voice_manifest_document(
            voice_plan=plan_ep1,
            results=[],
            environment=voice_environment,  # type: ignore[arg-type]
        )


def test_a_non_dict_environment_is_refused(plan_ep1: dict[str, Any]) -> None:
    """A non-dict environment argument is refused."""
    results = _synthetic_results(plan_ep1)
    with pytest.raises(TypeError):
        build_episode_voice_manifest_document(
            voice_plan=plan_ep1,
            results=results,
            environment=[],  # type: ignore[arg-type]
        )


def test_the_manifest_carries_no_prose(
    plan_ep1: dict[str, Any], voice_environment: dict[str, str]
) -> None:
    """The manifest carries no realized text, text hash, or presentation coordinates."""
    results = _synthetic_results(plan_ep1)
    document = build_episode_voice_manifest_document(
        voice_plan=plan_ep1, results=results, environment=voice_environment
    )
    for unit in document["voice_units"]:
        assert "realized_text" not in unit
        assert "text" not in unit
        assert "presentation_start_frame" not in unit
        assert "presentation_end_frame" not in unit
