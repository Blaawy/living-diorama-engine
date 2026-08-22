"""Deterministic emphasis over verified episode history.

This package owns one question: which authoritative records should downstream
presentation pay attention to? It answers structurally, from a closed rule table,
and binds every answer back to the exact export document and array position it
came from.

STORY EMPHASIS IS PRESENTATION METADATA, NOT AUTHORITATIVE WORLD TRUTH.

Story is a read-only consumer of Render Export V1. It may only ever read that
contract through ``living_diorama.render`` and the ``living_diorama.persistence``
validation vocabulary -- it must never reach into live simulation, mutate its
inputs, write a save, or call a network service. Downstream layers (cinematic
direction, narration, editing, packaging) consume the plan this package produces
and are not part of it.
"""

from living_diorama.story.story_lineage import (
    require_consecutive_exports,
    require_memory_progression,
)
from living_diorama.story.story_planner import (
    build_episode_story_plan_bytes,
    build_episode_story_plan_document,
)
from living_diorama.story.story_schema_v1 import (
    MODE_BASELINE,
    MODE_TRANSITION,
    STORY_PLAN_FORMAT,
    STORY_SCHEMA_VERSION,
    validate_episode_story_plan,
)
from living_diorama.story.story_spec import (
    BEAT_KINDS,
    EMPHASIS_LEVELS,
    EVENT_BEAT_RULES,
    EVENT_EXCLUSIONS,
    FACT_BEAT_RULES,
    REASON_CODES,
)

__all__ = [
    "BEAT_KINDS",
    "EMPHASIS_LEVELS",
    "EVENT_BEAT_RULES",
    "EVENT_EXCLUSIONS",
    "FACT_BEAT_RULES",
    "MODE_BASELINE",
    "MODE_TRANSITION",
    "REASON_CODES",
    "STORY_PLAN_FORMAT",
    "STORY_SCHEMA_VERSION",
    "build_episode_story_plan_bytes",
    "build_episode_story_plan_document",
    "require_consecutive_exports",
    "require_memory_progression",
    "validate_episode_story_plan",
]
