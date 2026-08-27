"""Deterministic episode audio-track placement over an executed voice manifest.

This package owns one question: for a finished, audited Phase 29 voice
execution and the Phase 27 presentation plan its windows come from, exactly
where does each unit's already-measured speech begin on the episode's single
audio-sample clock -- and therefore exactly what is silence? It answers from
structure alone: a window's own presentation-frame position and the pinned
samples-per-frame crossing, plus the one measured fact it restates from the
manifest, ``speech_samples``.

THE AUDIO TRACK PLAN PLACES MEASURED SPEECH ON THE PRESENTATION CLOCK. IT
PRODUCES NO AUDIO.

It never synthesizes speech, never opens a WAV file, never measures a
sample, never decides whether real speech fits (already decided, and already
proven, by the layer beneath it), never reads a narration unit's ``text``, a
realization's ``realized_text``, or a memory fact's ``summary`` -- not
carried, not counted, not compared, not even for length. A speech span names
its unit by identity only.

Audio track is a read-only consumer of two finished documents: an Episode
Voice Manifest and the Episode Presentation Plan its underlying voice plan
was built over. It must never reach into live simulation, never import
``living_diorama.story``, ``living_diorama.render``,
``living_diorama.render_execution`` or ``living_diorama.memory``, and never
import a synthesis engine, a G2P library, ``torch``, or the standard
library's own ``wave`` module -- this package never opens an audio file of
any kind. Before any upstream measurement or window truth becomes
authoritative, this layer's cross-check reuses -- in full, unweakened -- the
locked Phase 28 source-verification gate and the Phase 29 relationship gate
that already own those proofs. The Voice Plan, Language Realization Plan,
Narration Delivery Plan, Narration Plan, Shot Direction Plan, Story Plan and
Render Export travel through this layer only as arguments to the reused
gate; none of the seven is ever bound in this plan's own source block or
consumed by its own derivation.

Artifact truth -- that the bound manifest is true of the actual executed
WAV bytes -- is proven separately, by reusing the Phase 29 directory audit
whole, as a precondition the CLI runs before this package's own gate is
ever called. No module in this package parses an audio file itself.

Downstream layers (episode audio composition, media assembly, encode)
consume the plan this package produces and are not part of it. A future
composition layer joins each unit's measured speech to its placed offset and
fills the structural silence this plan only accounts for; it may not move an
onset, retrim a span, or recompute what this plan already measured and
placed.
"""

from living_diorama.audio_track.audio_track_cross_check import (
    validate_episode_audio_track_plan_against_sources,
)
from living_diorama.audio_track.audio_track_planner import (
    build_episode_audio_track_plan_bytes,
    build_episode_audio_track_plan_document,
)
from living_diorama.audio_track.audio_track_schema_v1 import (
    SUPPORTED_PRESENTATION_SCHEMA_VERSION,
    SUPPORTED_VOICE_MANIFEST_SCHEMA_VERSION,
    validate_episode_audio_track_plan,
)
from living_diorama.audio_track.audio_track_spec import (
    AUDIO_TRACK_PLAN_FORMAT,
    AUDIO_TRACK_POLICY_V1,
    AUDIO_TRACK_SCHEMA_VERSION,
    MAX_AUDIO_TRACK_SAMPLES,
    SPEECH_ID_FORM,
    samples_per_presentation_frame,
    speech_start_sample,
)

__all__ = [
    "AUDIO_TRACK_PLAN_FORMAT",
    "AUDIO_TRACK_POLICY_V1",
    "AUDIO_TRACK_SCHEMA_VERSION",
    "MAX_AUDIO_TRACK_SAMPLES",
    "SPEECH_ID_FORM",
    "SUPPORTED_PRESENTATION_SCHEMA_VERSION",
    "SUPPORTED_VOICE_MANIFEST_SCHEMA_VERSION",
    "build_episode_audio_track_plan_bytes",
    "build_episode_audio_track_plan_document",
    "samples_per_presentation_frame",
    "speech_start_sample",
    "validate_episode_audio_track_plan",
    "validate_episode_audio_track_plan_against_sources",
]
