"""Determinism of the Phase 29 canonical package: same inputs, same bytes, no dependency leak."""

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.voice_execution import build_episode_voice_manifest_bytes

HASH_SEEDS = ("0", "1", "42", "123456")


def test_the_manifest_survives_a_canonical_round_trip(manifest_ep1: dict[str, Any]) -> None:
    """The manifest survives a canonical round trip."""
    payload = dumps_canonical(manifest_ep1, "voice manifest")
    assert loads_canonical(payload, "voice manifest") == manifest_ep1
    assert dumps_canonical(loads_canonical(payload, "voice manifest"), "voice manifest") == payload


def test_the_encoding_is_canonical(manifest_ep1: dict[str, Any]) -> None:
    """The encoding is canonical: sorted keys, compact separators, one trailing newline."""
    payload = dumps_canonical(manifest_ep1, "voice manifest")
    assert payload.endswith(b"\n")
    assert payload.count(b"\n") == 1
    assert b", " not in payload
    assert b": " not in payload


def test_building_the_same_sources_twice_produces_identical_bytes(
    plan_ep1: dict[str, Any], voice_environment: dict[str, str]
) -> None:
    """Building the same sources twice produces identical bytes."""
    import hashlib

    def results_for(plan: dict[str, Any]) -> dict[int, dict[str, object]]:
        out = {}
        for position, unit in enumerate(plan["voice_units"], start=1):
            samples = min(24000, unit["capacity_samples"])
            payload = b"\x00" * (44 + samples * 2)
            out[position] = {
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "speech_samples": samples,
            }
        return out

    results = results_for(plan_ep1)
    first = build_episode_voice_manifest_bytes(
        voice_plan=plan_ep1, results=results, environment=voice_environment
    )
    second = build_episode_voice_manifest_bytes(
        voice_plan=plan_ep1, results=results_for(plan_ep1), environment=dict(voice_environment)
    )
    assert first == second


def test_a_plan_carrying_a_non_finite_float_cannot_be_written(manifest_ep1: dict[str, Any]) -> None:
    """A document carrying a non-finite float cannot be written."""
    import math

    document = dict(manifest_ep1)
    document["poisoned"] = math.nan
    with pytest.raises((TypeError, ValueError)):
        dumps_canonical(document, "voice manifest")


DIGEST_SCRIPT = """
import sys
sys.path.insert(0, {src!r})
import hashlib
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.voice_execution.voice_execution_spec import (
    classify_voice_directory_entry,
    unit_audio_filename,
    voice_execution_id,
)

print(voice_execution_id(mode="baseline", episode=0, previous_episode=None))
print(unit_audio_filename(3))
print(classify_voice_directory_entry("episode_voice_plan.json"))
"""


@pytest.mark.parametrize("seed", HASH_SEEDS)
def test_naming_and_classification_are_stable_across_hash_seeds(seed: str) -> None:
    """Naming and classification helpers are stable across PYTHONHASHSEED values."""
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
    assert lines == ["episode_0000_baseline", "voice_unit_0003.wav", "owned"]


def test_no_synthesis_dependency_is_importable_from_this_process() -> None:
    """No synthesis dependency has entered this process after exercising the canonical package."""
    for forbidden in ("kokoro", "misaki", "torch", "numpy", "spacy", "num2words"):
        assert forbidden not in sys.modules
