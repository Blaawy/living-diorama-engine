"""Deterministic viewer-facing legibility over a finished realization and a finished presentation.

This package owns one question: for a finished language realization and the
presentation plan whose windows already name it, for how many presentation
frames is each locked realized sentence legible?

THE CAPTION PLAN MAKES LOCKED WORDING LEGIBLE ON THE PRESENTATION CLOCK. IT
REWORDS NOTHING.

It never rewords a sentence, never re-derives a window from a slot or a
hold, never measures speech, never reads a sample, and never reaches into
live simulation. It imports no audio module of any kind, and never imports
``living_diorama.audio_composition`` -- the paired sibling this phase never
consumes and is never consumed by.

Caption is a read-only consumer of two finished documents: an Episode
Language Realization Plan and the Episode Presentation Plan built from it.
It must never reach into live simulation, never import
``living_diorama.story``, ``living_diorama.render``,
``living_diorama.render_execution``, ``living_diorama.memory``,
``living_diorama.voice``, ``living_diorama.voice_execution`` or
``living_diorama.audio_track``. Before any upstream window or wording truth
becomes authoritative, this layer's cross-check reuses -- in full,
unweakened -- the locked Phase 27 source-verification gate that already owns
that proof.

Downstream layers (caption serialization, media assembly) consume the plan
this package produces and are not part of it.
"""

from living_diorama.caption.caption_cross_check import (
    validate_episode_caption_plan_against_sources,
)
from living_diorama.caption.caption_planner import (
    build_episode_caption_plan_bytes,
    build_episode_caption_plan_document,
    caption_texts,
)
from living_diorama.caption.caption_schema_v1 import validate_episode_caption_plan
from living_diorama.caption.caption_spec import (
    CAPTION_ID_FORM,
    CAPTION_PLAN_FORMAT,
    CAPTION_POLICY_V1,
    CAPTION_SCHEMA_VERSION,
    MAX_CAPTION_FRAME,
    caption_frames_for_window,
)

__all__ = [
    "CAPTION_ID_FORM",
    "CAPTION_PLAN_FORMAT",
    "CAPTION_POLICY_V1",
    "CAPTION_SCHEMA_VERSION",
    "MAX_CAPTION_FRAME",
    "build_episode_caption_plan_bytes",
    "build_episode_caption_plan_document",
    "caption_frames_for_window",
    "caption_texts",
    "validate_episode_caption_plan",
    "validate_episode_caption_plan_against_sources",
]
