"""Deterministic execution of a reviewed voice request into audited real speech.

This package owns one question: for the exact narrator request and windows a
Phase 28 voice plan already proved, what does that request's real speech
actually sound like, and does it fit? It answers by synthesizing each voice
unit exactly once under the pinned request, converting the resulting
waveform into a canonical WAV, and recomputing every measured fact --
sample count, byte length, digest -- from the artifact it actually produced,
never from a document's own claim about itself.

VOICE EXECUTION SPEAKS A PLANNED EPISODE. IT PLANS NOTHING.

It never reweights a window, rewords a sentence, moves an onset, changes a
capacity, chooses a narrator, or repairs an overflowing unit. Whether a unit
fits is decided once, from the artifact this phase produced, and an
episode with even one unfit unit publishes nothing: refuse, never repair.

This package is a read-only consumer of one finished document -- the Episode
Voice Plan -- reused whole through the locked Phase 28 source-verification
gate before any synthesis is trusted to speak from it. It must never reach
into live simulation, never import ``living_diorama.story``,
``living_diorama.render``, ``living_diorama.render_execution`` or
``living_diorama.memory``, and the canonical package itself never imports a
synthesis engine, a G2P library or ``torch`` -- no ``kokoro``, no
``misaki``, no ``numpy``, no ``spacy``, no ``num2words``, anywhere in this
package. The one module that legitimately performs synthesis,
``audio.kokoro.scripts.synthesize_episode``, lives outside this package and
outside ``src`` entirely, deferring every third-party import into a function
body so this package's own tests can exercise it with a fake engine and CI
never loads a model.

The one artifact profile is a single reviewed format: PCM16 little-endian,
mono, the request's own pinned sample rate, exactly forty-four canonical WAV
header bytes and nothing else -- fixed at review time in
:mod:`living_diorama.voice_execution.speech_audio`, and part of this
contract's schema version exactly as the presentation window floors are part
of Phase 27's.

Downstream layers (the episode audio track plan, captions, audio
composition, assembly) consume the manifest this package produces and are
not part of it. A future audio track plan binds this manifest's digest,
places each unit's measured speech on the presentation sample clock, and
must never resynthesize, retrim or reweigh anything this package already
measured.
"""

from living_diorama.voice_execution.speech_audio import (
    SpeechAudioProblem,
    canonical_wav_bytes,
    pcm16_bytes,
    read_wav_facts,
    speech_sample_count,
    verify_speech_audio,
)
from living_diorama.voice_execution.voice_execution_audit import audit_voice_directory
from living_diorama.voice_execution.voice_execution_binding import (
    require_manifest_matches_plan,
    require_voice_plan_bytes,
)
from living_diorama.voice_execution.voice_execution_schema_v1 import (
    validate_episode_voice_manifest,
)
from living_diorama.voice_execution.voice_execution_spec import (
    VOICE_MANIFEST_FORMAT,
    VOICE_MANIFEST_SCHEMA_VERSION,
    unit_audio_filename,
    voice_execution_id,
)
from living_diorama.voice_execution.voice_manifest import (
    build_episode_voice_manifest_bytes,
    build_episode_voice_manifest_document,
)

__all__ = [
    "SpeechAudioProblem",
    "VOICE_MANIFEST_FORMAT",
    "VOICE_MANIFEST_SCHEMA_VERSION",
    "audit_voice_directory",
    "build_episode_voice_manifest_bytes",
    "build_episode_voice_manifest_document",
    "canonical_wav_bytes",
    "pcm16_bytes",
    "read_wav_facts",
    "require_manifest_matches_plan",
    "require_voice_plan_bytes",
    "speech_sample_count",
    "unit_audio_filename",
    "validate_episode_voice_manifest",
    "verify_speech_audio",
    "voice_execution_id",
]
