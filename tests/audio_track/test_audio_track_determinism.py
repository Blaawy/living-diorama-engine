"""Determinism of the Phase 30 canonical package: same inputs, same bytes, no dependency leak."""

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from living_diorama.audio_track.audio_track_planner import build_episode_audio_track_plan_bytes
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical


def test_the_plan_survives_a_canonical_round_trip(
    voice_manifest_ep1: dict[str, Any], presentation_ep1: dict[str, Any]
) -> None:
    """The plan survives a canonical round trip."""
    payload = build_episode_audio_track_plan_bytes(voice_manifest_ep1, presentation_ep1)
    document = loads_canonical(payload, "audio track plan")
    assert dumps_canonical(document, "audio track plan") == payload


def test_identical_bytes_across_repeated_builds(
    voice_manifest_ep1: dict[str, Any], presentation_ep1: dict[str, Any]
) -> None:
    """Identical bytes are produced across repeated builds."""
    first = build_episode_audio_track_plan_bytes(voice_manifest_ep1, presentation_ep1)
    second = build_episode_audio_track_plan_bytes(voice_manifest_ep1, presentation_ep1)
    assert first == second


def test_the_encoding_is_canonical(
    voice_manifest_ep1: dict[str, Any], presentation_ep1: dict[str, Any]
) -> None:
    """The encoding is canonical: sorted keys, compact separators, one trailing newline."""
    payload = build_episode_audio_track_plan_bytes(voice_manifest_ep1, presentation_ep1)
    assert payload.endswith(b"\n")
    assert payload.count(b"\n") == 1
    assert b", " not in payload
    assert b": " not in payload


DIGEST_SCRIPT = """
import sys
sys.path.insert(0, {src!r})
from living_diorama.audio_track.audio_track_spec import speech_start_sample
print(speech_start_sample(25, 24))
print(speech_start_sample(1, 24))
"""


@pytest.mark.parametrize("seed", ("0", "1", "42", "123456"))
def test_the_onset_law_is_stable_across_hash_seeds(seed: str) -> None:
    """The onset law is stable across PYTHONHASHSEED values."""
    repo_root = Path(__file__).resolve().parents[2]
    script = DIGEST_SCRIPT.format(src=str(repo_root / "src"))
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONHASHSEED": seed, "PATH": "", "PYTHONPATH": str(repo_root / "src")},
    )
    lines = completed.stdout.strip().splitlines()
    assert lines == ["24000", "0"]


def test_no_clock_or_randomness_is_read(
    voice_manifest_ep1: dict[str, Any], presentation_ep1: dict[str, Any]
) -> None:
    """No clock or randomness is read: identical calls always agree."""
    results = {
        build_episode_audio_track_plan_bytes(voice_manifest_ep1, presentation_ep1) for _ in range(5)
    }
    assert len(results) == 1


def test_no_synthesis_dependency_is_importable_from_this_process() -> None:
    """No synthesis dependency has entered this process."""
    for forbidden in ("kokoro", "misaki", "torch", "numpy", "spacy", "num2words"):
        assert forbidden not in sys.modules
