"""Deterministic human-facing realization over a finished narration plan.

This package owns one question: how may each locked Phase 24 narration unit be
said to a human without changing what it means? It answers from structure --
the story plan's evidence, the render export's actual events, facts and world
entities, and one closed reviewed wording policy -- and binds every answer
back to the exact documents it proved.

LANGUAGE REALIZATION RESTATES MEANING IN HUMAN WORDS. IT DECIDES NOTHING.

It never adds a fact, drops a unit, changes an actor, a quantity or a tick,
introduces causality, reorders the plan, changes emphasis, or turns an unshown
beat into something the viewer was shown. Wording history stays authoritative
in the narration plan; world truth stays in the export; what mattered stays in
the story plan. This layer's one new claim per unit is a reviewed sentence
whose every atom those documents already prove.

Prose is never semantic input. No module here reads a narration unit's
``text`` or a memory fact's ``summary`` -- realized wording is derived from
structured authority alone, so a lying source sentence over unchanged
structure cannot move a realized byte. Labels come from a closed authority:
an entity's own authoritative name, a reviewed identifier grammar, or a
relationship phrase composed from the world's own records; an entity no
reviewed source covers is refused, never prettified.

Realization is a read-only consumer of finished documents: an Episode
Narration Plan, the Episode Story Plan it restates, and the render export
they were derived from. It must never reach delivery timing, cinematic
direction, render execution, live memory, audio, or a runtime model, and it
knows nothing about how long anything takes to say -- a one-second slot and a
twenty-second slot realize the same unit to the same bytes.

Downstream layers (presentation timing, voice, captions, assembly) consume
the plan this package produces and are not part of it. A future presentation
plan joins these sentences to windows on its own clock; a future voice plan
speaks exactly these bytes or refuses. Neither may reword a sentence, and
nothing downstream may turn an unshown beat into something the viewer was
shown.
"""

from living_diorama.language_realization.realization_cross_check import (
    validate_language_realization_plan_against_sources,
)
from living_diorama.language_realization.realization_guidance import (
    VIEWER_GUIDANCE_POOL,
    select_viewer_guidance,
    validate_guidance_grounding,
)
from living_diorama.language_realization.realization_planner import (
    build_episode_language_realization_plan_bytes,
    build_episode_language_realization_plan_document,
)
from living_diorama.language_realization.realization_schema_v1 import (
    SUPPORTED_NARRATION_SCHEMA_VERSION,
    SUPPORTED_STORY_SCHEMA_VERSION,
    validate_episode_language_realization_plan,
)
from living_diorama.language_realization.realization_spec import (
    EVENT_REALIZATION_TEMPLATES,
    EVENT_REALIZATION_TEMPLATES_V2,
    EXPLICIT_LABELS,
    FACT_REALIZATION_TEMPLATES,
    FACT_REALIZATION_TEMPLATES_V2,
    FORBIDDEN_V2_JARGON,
    REALIZATION_ID_FORM,
    REALIZATION_PLAN_FORMAT,
    REALIZATION_POLICY_V1,
    REALIZATION_SCHEMA_VERSION,
    WORDING_PROFILE_V1,
    WORDING_PROFILE_V2,
    WORDING_PROFILES,
    district_label,
    law_label,
)

__all__ = [
    "EVENT_REALIZATION_TEMPLATES",
    "EVENT_REALIZATION_TEMPLATES_V2",
    "EXPLICIT_LABELS",
    "FACT_REALIZATION_TEMPLATES",
    "FACT_REALIZATION_TEMPLATES_V2",
    "FORBIDDEN_V2_JARGON",
    "REALIZATION_ID_FORM",
    "REALIZATION_PLAN_FORMAT",
    "REALIZATION_POLICY_V1",
    "REALIZATION_SCHEMA_VERSION",
    "SUPPORTED_NARRATION_SCHEMA_VERSION",
    "SUPPORTED_STORY_SCHEMA_VERSION",
    "VIEWER_GUIDANCE_POOL",
    "WORDING_PROFILE_V1",
    "WORDING_PROFILE_V2",
    "WORDING_PROFILES",
    "build_episode_language_realization_plan_bytes",
    "build_episode_language_realization_plan_document",
    "district_label",
    "law_label",
    "select_viewer_guidance",
    "validate_episode_language_realization_plan",
    "validate_guidance_grounding",
    "validate_language_realization_plan_against_sources",
]
