"""Deterministic narrator-request identity and audio capacity over a finished chain.

This package owns one question: which reviewed narrator request speaks each
locked realized sentence, and how many audio samples does its Phase 27
presentation window offer that request to fill? It answers from structure --
the window's own presentation-frame length and the proven presentation fps --
and binds every answer back to the exact realization plan and presentation
plan it read.

THE VOICE PLAN DEFINES REVIEWED SPEECH AND REVIEWED CAPACITY. IT MEASURES
NOTHING.

It never synthesizes speech, never measures a waveform, never produces an
audio file, never decides whether real speech fits, never reads a narration
unit's ``text``, a realization's ``realized_text``, a memory fact's
``summary``, or an event's ``source_event_payload`` -- not carried, not
counted, not compared, not even for length. A voice unit names its sentence
by ``realization_id`` only. Whole-document canonical serialization of the
offered realization plan is required, to bind its exact bytes by digest;
that is never a semantic read of any field inside it.

Voice is a read-only consumer of finished documents: an Episode Language
Realization Plan and the Episode Presentation Plan built over the same
episode's delivery, narration, shot, story and render-export chain. It must
never reach into live simulation, never import ``living_diorama.story``,
``living_diorama.render``, ``living_diorama.render_execution``,
``living_diorama.memory``, ``living_diorama.narration`` or
``living_diorama.narration_delivery`` beyond the shared vocabulary constants
those packages already export publicly, never mutate its inputs, and never
call a model or a network service at runtime -- no Kokoro, no misaki, no
torch, no numpy, anywhere in this package. Before any upstream window or
realization truth becomes authoritative, this layer's cross-check reuses --
in full, unweakened -- the one locked upstream source-verification gate that
already owns those proofs: Phase 27's, which itself reruns Phase 25's and
Phase 26's gates in full. The Delivery Plan, Narration Plan, Shot Direction
Plan, Story Plan and Render Export travel through this layer only as
arguments to that gate; none of the five is ever bound in this plan's own
source block or consumed by its own derivation.

The one voice policy is a single reviewed narrator request -- fifteen pinned
fields, from engine identity through the three artifact digests to the
sample rate and seed -- fixed at review time in ``voice_spec``, and is part
of this contract's schema version, exactly as the two presentation window
floors are part of Phase 27's.

Downstream layers (voice execution, captions, audio and episode assembly)
consume the plan this package produces and are not part of it. A future
voice execution phase synthesizes each unit exactly once under this plan's
pinned request, owns the resulting audio, recomputes its own sample count
from the bytes it actually produced -- never trusting a count some document
merely asserts -- and proves that count fits this plan's ``capacity_samples``
or refuses. Neither may reword a sentence, move a window, or change what
this plan's own ``capacity_samples`` says.
"""

from living_diorama.voice.voice_cross_check import validate_episode_voice_plan_against_sources
from living_diorama.voice.voice_planner import (
    build_episode_voice_plan_bytes,
    build_episode_voice_plan_document,
)
from living_diorama.voice.voice_schema_v1 import (
    SUPPORTED_PRESENTATION_SCHEMA_VERSION,
    SUPPORTED_REALIZATION_SCHEMA_VERSION,
    validate_episode_voice_plan,
)
from living_diorama.voice.voice_spec import (
    MAX_VOICE_CAPACITY_SAMPLES,
    SAMPLE_RATE_HZ,
    VOICE_BLOCK,
    VOICE_PLAN_FORMAT,
    VOICE_PLAN_SCHEMA_VERSION,
    VOICE_POLICY_V1,
    VOICE_UNIT_ID_FORM,
    capacity_samples_for_window,
    samples_per_presentation_frame,
)

__all__ = [
    "MAX_VOICE_CAPACITY_SAMPLES",
    "SAMPLE_RATE_HZ",
    "SUPPORTED_PRESENTATION_SCHEMA_VERSION",
    "SUPPORTED_REALIZATION_SCHEMA_VERSION",
    "VOICE_BLOCK",
    "VOICE_PLAN_FORMAT",
    "VOICE_PLAN_SCHEMA_VERSION",
    "VOICE_POLICY_V1",
    "VOICE_UNIT_ID_FORM",
    "build_episode_voice_plan_bytes",
    "build_episode_voice_plan_document",
    "capacity_samples_for_window",
    "samples_per_presentation_frame",
    "validate_episode_voice_plan",
    "validate_episode_voice_plan_against_sources",
]
