"""Deterministic composition of one episode's audio track from an audited voice execution.

This package owns one question: for a finished, audited Phase 29 voice
execution and the sealed Phase 30 audio track plan that placed it, what does
the episode's one audio artifact actually contain, byte for byte?

AUDIO COMPOSITION WRITES A PLACED EPISODE'S ONE TRACK. IT PLACES NOTHING.

It never decides where a unit's speech begins -- already decided, and
already proven, by the layer beneath it -- never measures a sample --
already measured, and already audited, by the layer beneath that -- never
rewords, never retimes, and never reaches into live simulation. It imports
no synthesis engine, no G2P library, no third-party dependency of any kind:
this phase's only artifact operation is copying bytes Phase 29 already
produced to the offset Phase 30 already sealed, filling everything else
with silence.

This package is a read-only consumer of two finished documents -- the
Episode Audio Track Plan and an audited Phase 29 voice execution directory
-- reused whole through the locked Phase 30 source-verification gate before
any byte is ever copied. It must never reach into live simulation, never
import ``living_diorama.story``, ``living_diorama.render``,
``living_diorama.render_execution``, ``living_diorama.memory`` or
``living_diorama.caption`` -- the paired sibling this phase never consumes
and is never consumed by.

The one artifact profile is the request already pinned by the audited
execution's own WAVs: PCM16 little-endian, mono, the execution's own sample
rate, exactly forty-four canonical WAV header bytes and nothing else --
reused whole from :mod:`living_diorama.voice_execution.speech_audio`, never
reimplemented.

Downstream layers (media assembly, encode) consume the composed track this
package produces and are not part of it.
"""

from living_diorama.audio_composition.audio_composer import (
    CompositionRefused,
    compose_episode_audio_bytes,
    pcm_payload_of,
    require_placement_geometry,
    require_silence_complement,
    span_pcm,
)
from living_diorama.audio_composition.audio_composition_audit import (
    audit_audio_composition_directory,
)
from living_diorama.audio_composition.audio_composition_binding import (
    require_composition_matches_plan_and_witness,
    require_voice_manifest_bytes,
    require_voice_unit_bytes,
)
from living_diorama.audio_composition.audio_composition_manifest import (
    build_episode_audio_composition_manifest_bytes,
    build_episode_audio_composition_manifest_document,
)
from living_diorama.audio_composition.audio_composition_publisher import publish_episode_audio
from living_diorama.audio_composition.audio_composition_schema_v1 import (
    validate_episode_audio_composition_manifest,
)
from living_diorama.audio_composition.audio_composition_spec import (
    AUDIO_COMPOSITION_MANIFEST_FORMAT,
    AUDIO_COMPOSITION_MANIFEST_SCHEMA_VERSION,
    AUDIO_DIRECTORY,
    EPISODE_AUDIO_FILENAME,
    audio_composition_id,
    classify_audio_composition_directory_entry,
    episode_audio_relative_path,
)
from living_diorama.audio_composition.audio_composition_staging import CompositionDirectoryRefused

__all__ = [
    "AUDIO_COMPOSITION_MANIFEST_FORMAT",
    "AUDIO_COMPOSITION_MANIFEST_SCHEMA_VERSION",
    "AUDIO_DIRECTORY",
    "EPISODE_AUDIO_FILENAME",
    "CompositionDirectoryRefused",
    "CompositionRefused",
    "audio_composition_id",
    "audit_audio_composition_directory",
    "build_episode_audio_composition_manifest_bytes",
    "build_episode_audio_composition_manifest_document",
    "classify_audio_composition_directory_entry",
    "compose_episode_audio_bytes",
    "episode_audio_relative_path",
    "pcm_payload_of",
    "publish_episode_audio",
    "require_composition_matches_plan_and_witness",
    "require_placement_geometry",
    "require_silence_complement",
    "require_voice_manifest_bytes",
    "require_voice_unit_bytes",
    "span_pcm",
    "validate_episode_audio_composition_manifest",
]
