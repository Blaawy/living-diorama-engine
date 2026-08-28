"""Shared fixtures for the Phase 33 episode media assembly tests.

The exports under ``fixtures/`` are byte-identical copies of the Phase
27/31 suites' own render exports. Story, shot, narration, delivery,
realization and presentation plans are all derived from them at test time
by the locked upstream layers, exactly as the Phase 27 and Phase 31 suites
already do -- nothing here hand-writes a document one of those layers is
supposed to produce.

The render manifest and its playback/witness PNGs are built from a real
``episode_render_plan`` via the real, pure
:func:`build_episode_render_manifest_document`, then written to a real
render directory. Every frame's ``sha256``, ``bytes`` and ``image_sha256``
are measured from the file actually written, never fabricated -- so a test
that reads a frame back is reading what a real render would have left
behind, not a hand-typed digest that happens to match.

Two synthetic speech generators exist for the same reason the Phase 31
suite carries them: ``silent_speech_wav_bytes`` proves lawful zero-valued
speech is accepted, and ``patterned_speech_wav_bytes`` produces
deterministic non-zero PCM so a composed track built only from silence
cannot make a mutation test pass vacuously.
"""

import copy
import functools
import json
import shutil
import struct
import zlib
from pathlib import Path
from typing import Any

import pytest

from living_diorama.audio_composition.audio_composition_publisher import publish_episode_audio
from living_diorama.audio_composition.audio_composition_spec import (
    AUDIO_COMPOSITION_MANIFEST_FILENAME,
    EPISODE_AUDIO_FILENAME,
)
from living_diorama.audio_composition.audio_composition_spec import (
    AUDIO_DIRECTORY as COMPOSITION_AUDIO_DIRECTORY,
)
from living_diorama.audio_track.audio_track_planner import build_episode_audio_track_plan_document
from living_diorama.cinematic import build_shot_direction_plan_document
from living_diorama.language_realization import build_episode_language_realization_plan_document
from living_diorama.media_assembly.media_assembly_publisher import publish_episode_media_assembly
from living_diorama.narration import build_episode_narration_plan_document
from living_diorama.narration_delivery import build_episode_narration_delivery_plan_document
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.presentation import build_episode_presentation_plan_document
from living_diorama.render_execution import (
    build_episode_render_manifest_document,
    build_episode_render_plan_document,
)
from living_diorama.render_execution.frame_image import image_stream_digest
from living_diorama.render_execution.render_execution_spec import (
    FRAMES_DIRECTORY,
    RENDER_MANIFEST_FILENAME,
    ROLE_PLAYBACK,
    WITNESS_DIRECTORY,
    render_profile_dimensions,
)
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

PROFILE_WIDTH, PROFILE_HEIGHT = render_profile_dimensions()

VOICE_ENVIRONMENT: dict[str, str] = {
    "device": "cpu",
    "python_version": "3.13.15",
    "torch_version": "2.13.0+cpu",
    "spacy_version": "3.8.16",
    "spacy_model": "en_core_web_sm",
    "spacy_model_version": "3.8.0",
    "num2words_version": "0.5.14",
}

RENDER_ENVIRONMENT: dict[str, str] = {
    "blender_version": "4.5.12",
    "engine": "CYCLES",
    "device": "OPTIX",
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


@pytest.fixture(scope="session")
def sources_ep0() -> tuple[dict[str, Any], ...]:
    """Sources ep0. Session-scoped: pure, expensive to rebuild, never mutated in place."""
    return build_sources(0)


@pytest.fixture(scope="session")
def sources_ep1() -> tuple[dict[str, Any], ...]:
    """Sources ep1. Session-scoped: pure, expensive to rebuild, never mutated in place."""
    return build_sources(1)


@pytest.fixture(scope="session")
def sources_ep2() -> tuple[dict[str, Any], ...]:
    """Sources ep2. Session-scoped: pure, expensive to rebuild, never mutated in place."""
    return build_sources(2)


@functools.lru_cache(maxsize=1024)
def png_bytes(*, width: int = PROFILE_WIDTH, height: int = PROFILE_HEIGHT, fill: int = 0) -> bytes:
    """Return a real, structurally complete PNG with correct chunk CRCs, at the profile size."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes([fill, fill, fill] * width) for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def write_render_directory(root: Path, render_plan: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    """Write a real, structurally complete render directory and return (render_dir, manifest).

    Every playback and witness frame is a genuine distinct PNG (the fill
    byte varies with the frame index), written to disk before its digests
    are measured, so ``results`` records exactly what a real render would
    have left behind.
    """
    directory = root / "render"
    frames_dir = directory / FRAMES_DIRECTORY
    witness_dir = directory / WITNESS_DIRECTORY
    frames_dir.mkdir(parents=True)
    witness_dir.mkdir(parents=True)

    results: dict[int, dict[str, object]] = {}
    for index, entry in enumerate(render_plan["frames"]):
        frame = entry["frame"]
        role = entry["role"]
        filename = entry["file"]
        payload = png_bytes(fill=index % 256)
        destination = (frames_dir if role == ROLE_PLAYBACK else witness_dir) / filename
        destination.write_bytes(payload)
        results[frame] = {
            "bytes": len(payload),
            "sha256": sha256_hex(payload),
            "image_sha256": image_stream_digest(destination),
        }

    manifest = build_episode_render_manifest_document(
        render_plan=render_plan,
        results=results,
        environment=dict(RENDER_ENVIRONMENT),
        witness_difference=0.08,
    )
    (directory / RENDER_MANIFEST_FILENAME).write_bytes(
        dumps_canonical(manifest, "episode render manifest")
    )
    return directory, manifest


@pytest.fixture(scope="session")
def render_ep0(
    tmp_path_factory: pytest.TempPathFactory, sources_ep0: tuple[dict[str, Any], ...]
) -> tuple[Path, dict[str, Any]]:
    """Render dir + manifest ep0.

    Session-scoped: building a real render directory measures every frame's
    real digests from real PNG bytes, which is the expensive part of this
    suite. Every test that uses this fixture deep-copies before mutating, so
    sharing one built directory across the whole session is safe.
    """
    _realization, _presentation, _delivery, _narration, shots, story, _export = sources_ep0
    plan = build_episode_render_plan_document(shots, story)
    return write_render_directory(tmp_path_factory.mktemp("render_root_ep0"), plan)


@pytest.fixture(scope="session")
def render_ep1(
    tmp_path_factory: pytest.TempPathFactory, sources_ep1: tuple[dict[str, Any], ...]
) -> tuple[Path, dict[str, Any]]:
    """Render dir + manifest ep1. Session-scoped; see :func:`render_ep0`."""
    _realization, _presentation, _delivery, _narration, shots, story, _export = sources_ep1
    plan = build_episode_render_plan_document(shots, story)
    return write_render_directory(tmp_path_factory.mktemp("render_root_ep1"), plan)


@pytest.fixture(scope="session")
def render_ep2(
    tmp_path_factory: pytest.TempPathFactory, sources_ep2: tuple[dict[str, Any], ...]
) -> tuple[Path, dict[str, Any]]:
    """Render dir + manifest ep2. Session-scoped; see :func:`render_ep0`."""
    _realization, _presentation, _delivery, _narration, shots, story, _export = sources_ep2
    plan = build_episode_render_plan_document(shots, story)
    return write_render_directory(tmp_path_factory.mktemp("render_root_ep2"), plan)


@functools.lru_cache(maxsize=512)
def silent_speech_wav_bytes(
    *, samples: int = 24000, sample_rate_hz: int = 24000, channels: int = 1
) -> bytes:
    """Build a real, structurally complete, all-zero synthetic canonical WAV, cached."""
    values = [0.0] * samples
    pcm = pcm16_bytes(values, "synthetic silent speech")
    return canonical_wav_bytes(pcm, sample_rate_hz=sample_rate_hz, channels=channels)


@functools.lru_cache(maxsize=512)
def patterned_speech_wav_bytes(
    *, samples: int, seed: int = 1, sample_rate_hz: int = 24000, channels: int = 1
) -> bytes:
    """Build a real, structurally complete, deterministic NON-ZERO synthetic WAV, cached."""
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


def build_voice_plan(realization: dict[str, Any], presentation: dict[str, Any]) -> dict[str, Any]:
    """Return the voice plan for one episode's sources."""
    return build_episode_voice_plan_document(realization, presentation)


def build_voice_manifest(voice_plan: dict[str, Any], *, patterned: bool = False) -> dict[str, Any]:
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
        voice_plan=voice_plan, results=results, environment=dict(VOICE_ENVIRONMENT)
    )


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


def compose_into(
    output_root: Path,
    audio_track_plan: dict[str, Any],
    voice_manifest: dict[str, Any],
    voice_dir: Path,
) -> Path:
    """Compose via the real Phase 31 publisher, and return the published composition directory."""
    output_root.mkdir(parents=True, exist_ok=True)
    return publish_episode_audio(
        audio_track_plan=audio_track_plan,
        audio_track_plan_bytes=dumps_canonical(audio_track_plan, "audio track plan"),
        voice_manifest=voice_manifest,
        voice_manifest_bytes=dumps_canonical(voice_manifest, "voice manifest"),
        voice_dir=voice_dir,
        output_root=output_root,
    )


def build_composition(
    root: Path,
    sources: tuple[dict[str, Any], ...],
    *,
    patterned: bool,
    label: str,
) -> Path:
    """Build a real, published Phase 31 composition directory for one episode's sources."""
    realization, presentation, _delivery, _narration, _shots, _story, _export = sources
    voice_plan = build_voice_plan(realization, presentation)
    voice_manifest = build_voice_manifest(voice_plan, patterned=patterned)
    voice_dir = write_voice_directory(
        root / f"voice_{label}", voice_plan, voice_manifest, patterned=patterned
    )
    audio_track_plan = build_episode_audio_track_plan_document(voice_manifest, presentation)
    return compose_into(root / f"audio_tracks_{label}", audio_track_plan, voice_manifest, voice_dir)


@pytest.fixture(scope="session")
def composition_ep0(
    tmp_path_factory: pytest.TempPathFactory, sources_ep0: tuple[dict[str, Any], ...]
) -> Path:
    """Composition dir ep0. Session-scoped; see :func:`render_ep0`."""
    return build_composition(
        tmp_path_factory.mktemp("composition_ep0"), sources_ep0, patterned=False, label="ep0"
    )


@pytest.fixture(scope="session")
def composition_ep1(
    tmp_path_factory: pytest.TempPathFactory, sources_ep1: tuple[dict[str, Any], ...]
) -> Path:
    """Composition dir ep1. Session-scoped; see :func:`render_ep0`."""
    return build_composition(
        tmp_path_factory.mktemp("composition_ep1"), sources_ep1, patterned=True, label="ep1"
    )


@pytest.fixture(scope="session")
def composition_ep2(
    tmp_path_factory: pytest.TempPathFactory, sources_ep2: tuple[dict[str, Any], ...]
) -> Path:
    """Composition dir ep2. Session-scoped; see :func:`render_ep0`."""
    return build_composition(
        tmp_path_factory.mktemp("composition_ep2"), sources_ep2, patterned=True, label="ep2"
    )


def build_assembly_inputs(
    sources: tuple[dict[str, Any], ...],
    render: tuple[Path, dict[str, Any]],
    composition_dir: Path,
) -> dict[str, Any]:
    """Return the exact keyword bundle ``publish_episode_media_assembly`` requires.

    Every document is read back from its own real, canonical bytes -- never
    handed over as the in-memory object that built it -- so the bytes a test
    mutates are the same bytes the publisher would actually receive.
    """
    _realization, presentation, delivery, _narration, shots, _story, _export = sources
    render_dir, render_manifest = render

    render_manifest_bytes = (render_dir / RENDER_MANIFEST_FILENAME).read_bytes()
    presentation_plan_bytes = dumps_canonical(presentation, "episode presentation plan")
    delivery_plan_bytes = dumps_canonical(delivery, "episode narration delivery plan")
    shot_plan_bytes = dumps_canonical(shots, "shot direction plan")
    composition_manifest_bytes = (
        composition_dir / AUDIO_COMPOSITION_MANIFEST_FILENAME
    ).read_bytes()
    wav_bytes = (
        composition_dir / COMPOSITION_AUDIO_DIRECTORY / EPISODE_AUDIO_FILENAME
    ).read_bytes()

    return {
        "render_manifest": loads_canonical(render_manifest_bytes, "episode render manifest"),
        "render_manifest_bytes": render_manifest_bytes,
        "presentation_plan": loads_canonical(presentation_plan_bytes, "episode presentation plan"),
        "presentation_plan_bytes": presentation_plan_bytes,
        "audio_composition_manifest": loads_canonical(
            composition_manifest_bytes, "episode audio composition manifest"
        ),
        "audio_composition_manifest_bytes": composition_manifest_bytes,
        "delivery_plan": loads_canonical(delivery_plan_bytes, "episode narration delivery plan"),
        "delivery_plan_bytes": delivery_plan_bytes,
        "shot_plan_bytes": shot_plan_bytes,
        "wav_bytes": wav_bytes,
        "render_dir": render_dir,
    }


@pytest.fixture(scope="session")
def assembly_inputs_ep0(
    sources_ep0: tuple[dict[str, Any], ...],
    render_ep0: tuple[Path, dict[str, Any]],
    composition_ep0: Path,
) -> dict[str, Any]:
    """The exact publisher keyword bundle, ep0. Session-scoped; see :func:`render_ep0`.

    Every value here is either an immutable ``bytes`` object or a dict every
    test deep-copies before mutating -- never mutated in place.
    """
    return build_assembly_inputs(sources_ep0, render_ep0, composition_ep0)


@pytest.fixture(scope="session")
def assembly_inputs_ep1(
    sources_ep1: tuple[dict[str, Any], ...],
    render_ep1: tuple[Path, dict[str, Any]],
    composition_ep1: Path,
) -> dict[str, Any]:
    """The exact publisher keyword bundle, ep1. Session-scoped; see :func:`assembly_inputs_ep0`."""
    return build_assembly_inputs(sources_ep1, render_ep1, composition_ep1)


@pytest.fixture(scope="session")
def assembly_inputs_ep2(
    sources_ep2: tuple[dict[str, Any], ...],
    render_ep2: tuple[Path, dict[str, Any]],
    composition_ep2: Path,
) -> dict[str, Any]:
    """The exact publisher keyword bundle, ep2. Session-scoped; see :func:`assembly_inputs_ep0`."""
    return build_assembly_inputs(sources_ep2, render_ep2, composition_ep2)


def publish_into(inputs: dict[str, Any], output_root: Path) -> Path:
    """Publish one episode's media assembly via the real publisher, into a fresh root."""
    output_root.mkdir(parents=True, exist_ok=True)
    return publish_episode_media_assembly(output_root=output_root, **inputs)


@pytest.fixture(scope="session")
def assembly_dir_ep1(
    tmp_path_factory: pytest.TempPathFactory, assembly_inputs_ep1: dict[str, Any]
) -> Path:
    """A real, published Phase 33 media assembly directory for ep1, session-scoped.

    A shared, read-only publication: any test that needs to attack the
    published *files* (a tamper, a hardlink, a foreign entry) must copy this
    tree into its own ``tmp_path`` first, via ``shutil.copytree``, and mutate
    the copy -- never this directory itself.
    """
    return publish_into(assembly_inputs_ep1, tmp_path_factory.mktemp("assembly_ep1") / "out")


@pytest.fixture
def assembly_dir_ep1_copy(tmp_path: Path, assembly_dir_ep1: Path) -> Path:
    """A fresh, function-scoped, writable copy of the published ep1 assembly.

    For tests that must tamper with published *files* on disk -- a tamper, a
    hardlink, a foreign entry -- without disturbing the session-shared
    original every other test relies on.
    """
    destination = tmp_path / assembly_dir_ep1.name
    shutil.copytree(assembly_dir_ep1, destination)
    return destination


def write_cli_inputs(
    root: Path,
    sources: tuple[dict[str, Any], ...],
    render: tuple[Path, dict[str, Any]],
    composition_dir: Path,
) -> dict[str, Path]:
    """Write every real file the ``assemble_episode_media`` CLI takes as a flag, to disk.

    Returns a dict keyed by CLI flag name (without the leading ``--``, dashes
    as underscores) plus ``output_root``, ready to build an argv list from.
    """
    realization, presentation, delivery, narration, shots, story, export = sources
    render_dir, _render_manifest = render

    paths: dict[str, Path] = {}
    for name, document, description in (
        ("presentation", presentation, "episode presentation plan"),
        ("delivery", delivery, "episode narration delivery plan"),
        ("shots", shots, "shot direction plan"),
        ("narration", narration, "episode narration plan"),
        ("realization", realization, "episode language realization plan"),
        ("story", story, "episode story plan"),
        ("export", export, "render export"),
    ):
        path = root / f"{name}.json"
        path.write_bytes(dumps_canonical(document, description))
        paths[name] = path

    paths["render_dir"] = render_dir
    paths["composition_dir"] = composition_dir
    paths["output_root"] = root / "media_assembly"
    return paths


@pytest.fixture
def cli_inputs_ep0(
    tmp_path: Path,
    sources_ep0: tuple[dict[str, Any], ...],
    render_ep0: tuple[Path, dict[str, Any]],
    composition_ep0: Path,
) -> dict[str, Path]:
    """Every real on-disk input the CLI takes, ep0."""
    return write_cli_inputs(tmp_path, sources_ep0, render_ep0, composition_ep0)


@pytest.fixture
def cli_inputs_ep1(
    tmp_path: Path,
    sources_ep1: tuple[dict[str, Any], ...],
    render_ep1: tuple[Path, dict[str, Any]],
    composition_ep1: Path,
) -> dict[str, Path]:
    """Every real on-disk input the CLI takes, ep1."""
    return write_cli_inputs(tmp_path, sources_ep1, render_ep1, composition_ep1)
