"""Shared fixtures for the Phase 29 voice execution tests.

The exports under ``fixtures/`` are byte-identical copies of the Phase 28
suite's own render exports (proved in ``test_phase29_boundary.py``). Story
plans, shot plans, narration plans, delivery plans, realization plans,
presentation plans and voice plans are all derived from them at test time by
the locked upstream layers, so what these tests speak is whatever those
layers actually say -- never a hand-authored story, cut, sentence, window or
narrator request.

Speech artifacts are wholly synthetic, built by this suite's own canonical
writer (:func:`speech_wav_bytes`), never by a real engine. No historical
measured sample count from any external evidence is used anywhere in this
suite.
"""

import copy
import functools
import json
from pathlib import Path
from typing import Any

import pytest

from living_diorama.cinematic import build_shot_direction_plan_document
from living_diorama.language_realization import build_episode_language_realization_plan_document
from living_diorama.narration import build_episode_narration_plan_document
from living_diorama.narration_delivery import build_episode_narration_delivery_plan_document
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.presentation import build_episode_presentation_plan_document
from living_diorama.story import build_episode_story_plan_document
from living_diorama.voice import build_episode_voice_plan_document
from living_diorama.voice_execution import (
    build_episode_voice_manifest_document,
    canonical_wav_bytes,
    pcm16_bytes,
    unit_audio_filename,
    voice_execution_id,
)
from living_diorama.voice_execution.voice_execution_spec import (
    SPEECH_DIRECTORY,
    VOICE_MANIFEST_FILENAME,
    VOICE_PLAN_FILENAME,
)

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]
"""The repository root -- exported for modules that need to locate source files."""

MOTION_CONFIG = REPO_ROOT / "visual" / "blender" / "config" / "motion_time_v1.json"

ENVIRONMENT: dict[str, str] = {
    "device": "cpu",
    "python_version": "3.13.15",
    "torch_version": "2.13.0+cpu",
    "spacy_version": "3.8.16",
    "spacy_model": "en_core_web_sm",
    "spacy_model_version": "3.8.0",
    "num2words_version": "0.5.14",
}
"""A structurally valid, synthetic environment block.

Not evidence of any real execution -- every value is illustrative, chosen
only to satisfy the manifest's own shape.
"""


def load_export(episode: int) -> dict[str, Any]:
    """Return an independent copy of one fixture render export."""
    return json.loads((FIXTURES / f"render_export_ep{episode}.json").read_text(encoding="utf-8"))


def build_voice_sources(
    episode: int,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    """Return the (realization, presentation, delivery, narration, shots, story, export) tuple.

    ``episode`` 0 is the baseline; 1 and 2 are transitions from the episode
    before them. The ordering matches
    :func:`living_diorama.voice.voice_cross_check.validate_episode_voice_plan_against_sources`'s
    own parameter order, minus the voice plan itself.
    """
    export = load_export(episode)
    previous = load_export(episode - 1) if episode else None
    story = build_episode_story_plan_document(copy.deepcopy(export), previous)
    shots = build_shot_direction_plan_document(story, MOTION_CONFIG.read_bytes())
    narration = build_episode_narration_plan_document(story, shots, copy.deepcopy(export))
    delivery = build_episode_narration_delivery_plan_document(narration, shots)
    realization = build_episode_language_realization_plan_document(
        narration, story, copy.deepcopy(export)
    )
    presentation = build_episode_presentation_plan_document(delivery, narration, realization)
    return realization, presentation, delivery, narration, shots, story, export


def build_plan(episode: int) -> dict[str, Any]:
    """Return the voice plan for one canonical episode."""
    realization, presentation, _delivery, _narration, _shots, _story, _export = build_voice_sources(
        episode
    )
    return build_episode_voice_plan_document(realization, presentation)


@pytest.fixture(scope="session")
def motion_time() -> bytes:
    """The exact bytes of the shipped Phase 17 Motion & Time Spec."""
    return MOTION_CONFIG.read_bytes()


@pytest.fixture
def sources_ep0() -> tuple[dict[str, Any], ...]:
    """Episode 0 baseline: one whole-window template unit."""
    return build_voice_sources(0)


@pytest.fixture
def sources_ep1() -> tuple[dict[str, Any], ...]:
    """Episode 0 -> 1: two template units and one fact-backed unit."""
    return build_voice_sources(1)


@pytest.fixture
def sources_ep2() -> tuple[dict[str, Any], ...]:
    """Episode 1 -> 2: a fact-backed unit leading, then a template unit."""
    return build_voice_sources(2)


@pytest.fixture
def plan_ep0() -> dict[str, Any]:
    """The voice plan for the baseline episode."""
    return build_plan(0)


@pytest.fixture
def plan_ep1() -> dict[str, Any]:
    """The voice plan for the episode the wall was built in."""
    return build_plan(1)


@pytest.fixture
def plan_ep2() -> dict[str, Any]:
    """The voice plan for the episode the consequence persisted in."""
    return build_plan(2)


@pytest.fixture
def voice_environment() -> dict[str, str]:
    """A structurally valid, synthetic environment block, fresh per test."""
    return dict(ENVIRONMENT)


@functools.lru_cache(maxsize=512)
def speech_wav_bytes(
    *, samples: int = 24000, sample_rate_hz: int = 24000, channels: int = 1
) -> bytes:
    """Build a real, structurally complete synthetic canonical WAV.

    Building these is the expensive part, so the result is cached -- exactly
    as the Phase 23 render-execution suite's own ``png_bytes`` caches its
    fabricated artifacts.
    """
    values = [0.0] * samples
    pcm = pcm16_bytes(values, "synthetic speech")
    return canonical_wav_bytes(pcm, sample_rate_hz=sample_rate_hz, channels=channels)


def build_manifest(voice_plan: dict[str, Any]) -> dict[str, Any]:
    """Return a synthetic, internally consistent manifest for one voice plan.

    Every unit's ``speech_samples`` is well under its own capacity, so every
    unit fits with margin. No historical measured sample count is ever used.
    """
    voice_units = voice_plan["voice_units"]
    results: dict[int, dict[str, object]] = {}
    for position, unit in enumerate(voice_units, start=1):
        samples = min(24000, unit["capacity_samples"])
        wav = speech_wav_bytes(samples=samples)
        results[position] = {
            "bytes": len(wav),
            "sha256": sha256_hex(wav),
            "speech_samples": samples,
        }
    return build_episode_voice_manifest_document(
        voice_plan=voice_plan, results=results, environment=dict(ENVIRONMENT)
    )


@pytest.fixture
def manifest_ep0(plan_ep0: dict[str, Any]) -> dict[str, Any]:
    """A synthetic, internally consistent voice manifest for the baseline episode."""
    return build_manifest(plan_ep0)


@pytest.fixture
def manifest_ep1(plan_ep1: dict[str, Any]) -> dict[str, Any]:
    """A synthetic, internally consistent voice manifest for episode 0 -> 1."""
    return build_manifest(plan_ep1)


@pytest.fixture
def manifest_ep2(plan_ep2: dict[str, Any]) -> dict[str, Any]:
    """A synthetic, internally consistent voice manifest for episode 1 -> 2."""
    return build_manifest(plan_ep2)


def write_voice_directory(root: Path, voice_plan: dict[str, Any], manifest: dict[str, Any]) -> Path:
    """Materialise a truthful, complete, published voice execution directory.

    Bypasses the executor entirely -- the point is a directory the audit can
    be run against, not a real synthesis.
    """
    source = voice_plan["source"]
    directory = root / voice_execution_id(
        mode=source["mode"],
        episode=source["episode"],
        previous_episode=source["previous_episode"],
    )
    speech_dir = directory / SPEECH_DIRECTORY
    speech_dir.mkdir(parents=True)
    (directory / VOICE_PLAN_FILENAME).write_bytes(dumps_canonical(voice_plan, "voice plan"))
    for position, unit in enumerate(manifest["voice_units"], start=1):
        wav = speech_wav_bytes(samples=unit["speech_samples"])
        (speech_dir / unit_audio_filename(position)).write_bytes(wav)
    (directory / VOICE_MANIFEST_FILENAME).write_bytes(dumps_canonical(manifest, "voice manifest"))
    return directory


@pytest.fixture
def voice_directory_ep0(
    tmp_path: Path, plan_ep0: dict[str, Any], manifest_ep0: dict[str, Any]
) -> Path:
    """A truthful, published voice execution directory for the baseline episode."""
    return write_voice_directory(tmp_path, plan_ep0, manifest_ep0)


@pytest.fixture
def voice_directory_ep1(
    tmp_path: Path, plan_ep1: dict[str, Any], manifest_ep1: dict[str, Any]
) -> Path:
    """A truthful, published voice execution directory for episode 0 -> 1."""
    return write_voice_directory(tmp_path, plan_ep1, manifest_ep1)


@pytest.fixture
def voice_directory_ep2(
    tmp_path: Path, plan_ep2: dict[str, Any], manifest_ep2: dict[str, Any]
) -> Path:
    """A truthful, published voice execution directory for episode 1 -> 2."""
    return write_voice_directory(tmp_path, plan_ep2, manifest_ep2)
