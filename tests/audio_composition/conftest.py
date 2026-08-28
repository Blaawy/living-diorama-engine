"""Shared fixtures for the Phase 31 audio composition tests.

The exports under ``fixtures/`` are byte-identical copies of the Phase
28/29/30 suites' own render exports. Story, shot, narration, delivery,
realization, presentation, voice and audio track plans are all derived from
them at test time by the locked upstream layers. Speech is wholly synthetic
-- no historical measured sample count is used anywhere in this suite.

Two synthetic speech generators exist deliberately. ``silent_speech_wav_bytes``
produces all-zero PCM, which proves lawful zero-valued speech is *accepted*.
``patterned_speech_wav_bytes`` produces deterministic *non-zero* PCM from a
pure integer recurrence -- no ``random``, no clock -- because a composed
track built only from silence would make the silence-complement check and
every one-bit-mutation test pass vacuously.
"""

import copy
import functools
import json
from pathlib import Path
from typing import Any

import pytest

from living_diorama.audio_composition.audio_composition_publisher import publish_episode_audio
from living_diorama.audio_track.audio_track_planner import build_episode_audio_track_plan_document
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


def load_export(episode: int) -> dict[str, Any]:
    """Return an independent copy of one fixture render export."""
    return json.loads((FIXTURES / f"render_export_ep{episode}.json").read_text(encoding="utf-8"))


def build_sources(
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
    """Return the (realization, presentation, delivery, narration, shots, story, export) tuple."""
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


def build_voice_plan(episode: int) -> dict[str, Any]:
    """Return the voice plan for one canonical episode."""
    realization, presentation, *_ = build_sources(episode)
    return build_episode_voice_plan_document(realization, presentation)


@pytest.fixture
def sources_ep0() -> tuple[dict[str, Any], ...]:
    """Sources ep0."""
    return build_sources(0)


@pytest.fixture
def sources_ep1() -> tuple[dict[str, Any], ...]:
    """Sources ep1."""
    return build_sources(1)


@pytest.fixture
def sources_ep2() -> tuple[dict[str, Any], ...]:
    """Sources ep2."""
    return build_sources(2)


@pytest.fixture
def voice_plan_ep0() -> dict[str, Any]:
    """Voice plan ep0."""
    return build_voice_plan(0)


@pytest.fixture
def voice_plan_ep1() -> dict[str, Any]:
    """Voice plan ep1."""
    return build_voice_plan(1)


@pytest.fixture
def voice_plan_ep2() -> dict[str, Any]:
    """Voice plan ep2."""
    return build_voice_plan(2)


@pytest.fixture
def presentation_ep0(sources_ep0: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Presentation ep0."""
    return sources_ep0[1]


@pytest.fixture
def presentation_ep1(sources_ep1: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Presentation ep1."""
    return sources_ep1[1]


@pytest.fixture
def presentation_ep2(sources_ep2: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Presentation ep2."""
    return sources_ep2[1]


@functools.lru_cache(maxsize=512)
def silent_speech_wav_bytes(
    *, samples: int = 24000, sample_rate_hz: int = 24000, channels: int = 1
) -> bytes:
    """Build a real, structurally complete, all-zero synthetic canonical WAV, cached.

    Proves that lawful zero-valued speech is accepted -- silence is legal
    content, never mistaken for structural silence.
    """
    values = [0.0] * samples
    pcm = pcm16_bytes(values, "synthetic silent speech")
    return canonical_wav_bytes(pcm, sample_rate_hz=sample_rate_hz, channels=channels)


@functools.lru_cache(maxsize=512)
def patterned_speech_wav_bytes(
    *, samples: int, seed: int = 1, sample_rate_hz: int = 24000, channels: int = 1
) -> bytes:
    """Build a real, structurally complete, deterministic NON-ZERO synthetic canonical WAV, cached.

    A pure integer linear-congruential recurrence -- no ``random``, no
    clock, no third-party dependency -- so the same ``(samples, seed)``
    always produces the same bytes.
    """
    state = seed if seed else 1
    values: list[float] = []
    for _ in range(samples):
        state = (state * 1_103_515_245 + 12_345) & 0x7FFFFFFF
        value = ((state % 20_000) - 10_000) / 10_000.0
        if value == 0.0:
            value = 0.0001
        values.append(value)
    pcm = pcm16_bytes(values, "synthetic patterned speech")
    return canonical_wav_bytes(pcm, sample_rate_hz=sample_rate_hz, channels=channels)


def build_manifest(voice_plan: dict[str, Any], *, patterned: bool = False) -> dict[str, Any]:
    """Return a synthetic, internally consistent voice manifest for one voice plan."""
    results: dict[int, dict[str, object]] = {}
    for position, unit in enumerate(voice_plan["voice_units"], start=1):
        samples = min(24000, unit["capacity_samples"])
        wav = (
            patterned_speech_wav_bytes(samples=samples, seed=position)
            if patterned
            else silent_speech_wav_bytes(samples=samples)
        )
        results[position] = {
            "bytes": len(wav),
            "sha256": sha256_hex(wav),
            "speech_samples": samples,
        }
    return build_episode_voice_manifest_document(
        voice_plan=voice_plan, results=results, environment=dict(ENVIRONMENT)
    )


@pytest.fixture
def voice_manifest_ep0(voice_plan_ep0: dict[str, Any]) -> dict[str, Any]:
    """A synthetic, internally consistent, all-zero voice manifest for the baseline episode."""
    return build_manifest(voice_plan_ep0)


@pytest.fixture
def voice_manifest_ep1(voice_plan_ep1: dict[str, Any]) -> dict[str, Any]:
    """A synthetic, internally consistent, deterministic NON-ZERO voice manifest for ep0 -> 1."""
    return build_manifest(voice_plan_ep1, patterned=True)


@pytest.fixture
def voice_manifest_ep2(voice_plan_ep2: dict[str, Any]) -> dict[str, Any]:
    """A synthetic, internally consistent, deterministic NON-ZERO voice manifest for ep1 -> 2."""
    return build_manifest(voice_plan_ep2, patterned=True)


@pytest.fixture
def audio_track_plan_ep0(
    voice_manifest_ep0: dict[str, Any], presentation_ep0: dict[str, Any]
) -> dict[str, Any]:
    """Audio track plan ep0."""
    return build_episode_audio_track_plan_document(voice_manifest_ep0, presentation_ep0)


@pytest.fixture
def audio_track_plan_ep1(
    voice_manifest_ep1: dict[str, Any], presentation_ep1: dict[str, Any]
) -> dict[str, Any]:
    """Audio track plan ep1."""
    return build_episode_audio_track_plan_document(voice_manifest_ep1, presentation_ep1)


@pytest.fixture
def audio_track_plan_ep2(
    voice_manifest_ep2: dict[str, Any], presentation_ep2: dict[str, Any]
) -> dict[str, Any]:
    """Audio track plan ep2."""
    return build_episode_audio_track_plan_document(voice_manifest_ep2, presentation_ep2)


def write_voice_directory(
    root: Path, voice_plan: dict[str, Any], manifest: dict[str, Any], *, patterned: bool = False
) -> Path:
    """Materialise a truthful, complete, published voice execution directory."""
    source = voice_plan["source"]
    directory = root / voice_execution_id(
        mode=source["mode"], episode=source["episode"], previous_episode=source["previous_episode"]
    )
    speech_dir = directory / SPEECH_DIRECTORY
    speech_dir.mkdir(parents=True)
    (directory / VOICE_PLAN_FILENAME).write_bytes(dumps_canonical(voice_plan, "voice plan"))
    for position, unit in enumerate(manifest["voice_units"], start=1):
        samples = unit["speech_samples"]
        wav = (
            patterned_speech_wav_bytes(samples=samples, seed=position)
            if patterned
            else silent_speech_wav_bytes(samples=samples)
        )
        (speech_dir / unit_audio_filename(position)).write_bytes(wav)
    (directory / VOICE_MANIFEST_FILENAME).write_bytes(dumps_canonical(manifest, "voice manifest"))
    return directory


@pytest.fixture
def voice_directory_ep0(
    tmp_path: Path, voice_plan_ep0: dict[str, Any], voice_manifest_ep0: dict[str, Any]
) -> Path:
    """Voice directory ep0."""
    return write_voice_directory(tmp_path, voice_plan_ep0, voice_manifest_ep0)


@pytest.fixture
def voice_directory_ep1(
    tmp_path: Path, voice_plan_ep1: dict[str, Any], voice_manifest_ep1: dict[str, Any]
) -> Path:
    """Voice directory ep1."""
    return write_voice_directory(tmp_path, voice_plan_ep1, voice_manifest_ep1, patterned=True)


@pytest.fixture
def voice_directory_ep2(
    tmp_path: Path, voice_plan_ep2: dict[str, Any], voice_manifest_ep2: dict[str, Any]
) -> Path:
    """Voice directory ep2."""
    return write_voice_directory(tmp_path, voice_plan_ep2, voice_manifest_ep2, patterned=True)


def compose_into(
    output_root: Path,
    audio_track_plan: dict[str, Any],
    voice_manifest: dict[str, Any],
    voice_dir: Path,
) -> Path:
    """Compose via the real publisher, and return the published composition directory."""
    output_root.mkdir(parents=True, exist_ok=True)
    return publish_episode_audio(
        audio_track_plan=audio_track_plan,
        audio_track_plan_bytes=dumps_canonical(audio_track_plan, "audio track plan"),
        voice_manifest=voice_manifest,
        voice_manifest_bytes=dumps_canonical(voice_manifest, "voice manifest"),
        voice_dir=voice_dir,
        output_root=output_root,
    )


@pytest.fixture
def composition_dir_ep0(
    tmp_path: Path,
    audio_track_plan_ep0: dict[str, Any],
    voice_manifest_ep0: dict[str, Any],
    voice_directory_ep0: Path,
) -> Path:
    """Composition dir ep0."""
    return compose_into(
        tmp_path / "audio_tracks", audio_track_plan_ep0, voice_manifest_ep0, voice_directory_ep0
    )


@pytest.fixture
def composition_dir_ep1(
    tmp_path: Path,
    audio_track_plan_ep1: dict[str, Any],
    voice_manifest_ep1: dict[str, Any],
    voice_directory_ep1: Path,
) -> Path:
    """Composition dir ep1."""
    return compose_into(
        tmp_path / "audio_tracks", audio_track_plan_ep1, voice_manifest_ep1, voice_directory_ep1
    )


@pytest.fixture
def composition_dir_ep2(
    tmp_path: Path,
    audio_track_plan_ep2: dict[str, Any],
    voice_manifest_ep2: dict[str, Any],
    voice_directory_ep2: Path,
) -> Path:
    """Composition dir ep2."""
    return compose_into(
        tmp_path / "audio_tracks", audio_track_plan_ep2, voice_manifest_ep2, voice_directory_ep2
    )
