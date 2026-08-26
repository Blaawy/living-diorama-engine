"""Deterministic viewer-facing presentation timing over a finished delivery schedule.

This package owns one question: for how many presentation frames may the
viewer see each locked semantic playback frame, so that every narration
unit's Phase 25 delivery slot receives sufficient deterministic viewer-facing
capacity? It answers from structure alone -- each unit's already
story-proven ``text_source`` classification and the length of the slot it
already owns -- and binds every answer back to the exact delivery plan,
narration plan and language realization plan it read.

PRESENTATION MAY EXTEND HOW LONG THE VIEWER SEES LOCKED SEMANTIC TRUTH. IT
DECIDES NOTHING ELSE.

It never invents a semantic frame, drops one, reorders one, or exposes the
terminal witness; never changes world truth, simulation time, story truth,
narration meaning or realized wording; never re-directs a camera or alters a
rendered frame's identity; and never performs speech synthesis, creates
audio, inspects a pixel, or reads Phase 23's render manifest. A held frame
means the viewer keeps looking at locked truth for longer -- never that new
world time was invented, never that a shot was re-cut, and never that moving
footage was slowed down: a hold is one still frame, never a dilated run.

Presentation is a read-only consumer of finished documents: an Episode
Narration Delivery Plan, the Episode Narration Plan it schedules, and the
Episode Language Realization Plan built from that same narration. It must
never reach into live simulation, never import ``living_diorama.story``,
``living_diorama.render``, ``living_diorama.render_execution`` or
``living_diorama.memory``, never read a narration unit's ``text``, a
realization's ``realized_text``, or a memory fact's ``summary``, never mutate
its inputs, and never call a model or a network service at runtime. Before
any upstream timing or classification truth becomes authoritative, this
layer's cross-check reuses -- in full, unweakened -- the two locked upstream
source-verification gates that already own those proofs: Phase 25's, against
the actual narration and shot plans, and Phase 26's, against the actual story
plan and render export. The Shot Direction Plan, Episode Story Plan and
Render Export travel through this layer only as arguments to those two
gates; none of the three is ever bound in this plan's own source block or
consumed by its own derivation.

The one presentation policy has exactly two tunable constants -- a window
floor for a template-backed unit and one for a fact-backed unit -- fixed at
review time in ``presentation_spec``, and is part of this contract's schema
version.

Downstream layers (voice realization, caption projection, audio and episode
assembly) consume the plan this package produces and are not part of it. A
future voice plan speaks a realized sentence beginning at its window's first
presentation frame and must fit the window or refuse; a future assembly layer
performs the physical frame repetition this plan only plans. Neither may
move a window, and nothing downstream may turn an unshown beat into
something the viewer was shown.
"""

from living_diorama.presentation.presentation_cross_check import (
    validate_episode_presentation_plan_against_sources,
)
from living_diorama.presentation.presentation_planner import (
    build_episode_presentation_plan_bytes,
    build_episode_presentation_plan_document,
)
from living_diorama.presentation.presentation_schema_v1 import (
    SUPPORTED_DELIVERY_SCHEMA_VERSION,
    SUPPORTED_NARRATION_SCHEMA_VERSION,
    SUPPORTED_REALIZATION_SCHEMA_VERSION,
    validate_episode_presentation_plan,
)
from living_diorama.presentation.presentation_spec import (
    MAX_PRESENTATION_FRAME,
    PRESENTATION_PLAN_FORMAT,
    PRESENTATION_POLICY_V1,
    PRESENTATION_SCHEMA_VERSION,
    SEGMENT_ID_FORM,
    WINDOW_FRAMES_BY_TEXT_SOURCE,
    WINDOW_ID_FORM,
    WINDOW_PRESENTATION_FRAMES_FACT,
    WINDOW_PRESENTATION_FRAMES_TEMPLATE,
    window_and_hold,
    window_frames_for_text_source,
)

__all__ = [
    "MAX_PRESENTATION_FRAME",
    "PRESENTATION_PLAN_FORMAT",
    "PRESENTATION_POLICY_V1",
    "PRESENTATION_SCHEMA_VERSION",
    "SEGMENT_ID_FORM",
    "SUPPORTED_DELIVERY_SCHEMA_VERSION",
    "SUPPORTED_NARRATION_SCHEMA_VERSION",
    "SUPPORTED_REALIZATION_SCHEMA_VERSION",
    "WINDOW_FRAMES_BY_TEXT_SOURCE",
    "WINDOW_ID_FORM",
    "WINDOW_PRESENTATION_FRAMES_FACT",
    "WINDOW_PRESENTATION_FRAMES_TEMPLATE",
    "build_episode_presentation_plan_bytes",
    "build_episode_presentation_plan_document",
    "validate_episode_presentation_plan",
    "validate_episode_presentation_plan_against_sources",
    "window_and_hold",
    "window_frames_for_text_source",
]
