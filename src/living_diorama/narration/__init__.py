"""Deterministic narration over an emphasized story and a directed episode.

This package owns one question: what truthful sentence restates each beat the
story layer emphasised, and was the viewer shown it? It answers structurally,
from a closed versioned wording table and from the sentences the world already
recorded about itself, and binds every answer back to the exact documents it
read.

NARRATION PLANNING RESTATES SELECTED TRUTH. IT DECIDES NOTHING.

It never selects what mattered, never re-ranks a beat, never reorders history,
never points a camera, and never decides that something was shown. Phase 21 owns
emphasis, Phase 22 owns what the viewer looks at, Phase 17 owns the clock, and
this layer says in words what those decisions already settled -- including, and
especially, that a beat which mattered was honestly not shown.

Narration is a read-only consumer of finished documents: an Episode Story Plan,
a Shot Direction Plan, and the Render Export the story plan was derived from. It
must never reach into live simulation, never import ``living_diorama.memory``,
never mutate its inputs, never write a save, and never call a model or a network
service at runtime. The wording it publishes is fixed at review time, in
``narration_spec``, and is part of this contract's schema version.

Downstream layers (caption and subtitle realization, voice and audio realization,
editing, encoding, packaging) consume the plan this package produces and are not
part of it. A future language realization may rephrase a unit's sentence; it may
never add a fact, drop a unit, change an actor or a quantity, reorder the plan,
or turn an unshown beat into something the viewer was shown.
"""

from living_diorama.narration.narration_cross_check import (
    validate_narration_plan_against_sources,
)
from living_diorama.narration.narration_facts import fact_summary_for_evidence, resolve_fact
from living_diorama.narration.narration_planner import (
    build_episode_narration_plan_bytes,
    build_episode_narration_plan_document,
)
from living_diorama.narration.narration_schema_v1 import (
    NARRATION_PLAN_FORMAT,
    NARRATION_SCHEMA_VERSION,
    validate_episode_narration_plan,
)
from living_diorama.narration.narration_spec import (
    CAUSAL_TOKENS,
    DEIXIS_TOKENS,
    NARRATION_TEMPLATES,
    TEXT_SOURCES,
    UNSHOWN_REASONS,
    VISIBILITY_STATES,
    forbidden_wording_hit,
)

__all__ = [
    "CAUSAL_TOKENS",
    "DEIXIS_TOKENS",
    "NARRATION_PLAN_FORMAT",
    "NARRATION_SCHEMA_VERSION",
    "NARRATION_TEMPLATES",
    "TEXT_SOURCES",
    "UNSHOWN_REASONS",
    "VISIBILITY_STATES",
    "build_episode_narration_plan_bytes",
    "build_episode_narration_plan_document",
    "fact_summary_for_evidence",
    "forbidden_wording_hit",
    "resolve_fact",
    "validate_episode_narration_plan",
    "validate_narration_plan_against_sources",
]
