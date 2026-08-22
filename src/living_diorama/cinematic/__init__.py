"""Deterministic cinematic direction over verified episode emphasis.

This package owns one question: given what Phase 21 says mattered, which
already-existing camera anchor should be looking, and for how long?

CINEMATIC DIRECTION IS PRESENTATION METADATA, NOT AUTHORITATIVE WORLD TRUTH.

It selects among cameras the world builders already created; it never creates,
moves, rotates, re-lenses, or animates one. It cuts between fixed anchors inside
the Phase 17 timeline whose exact document bytes it is handed as data; it invents
no frame, invents no clock, and reorders no world animation. Phase 21 owns what
mattered and this layer copies that ranking without ever recomputing it.

Downstream layers (editing, packaging, narration) consume the plan this package
produces and are not part of it.
"""

from living_diorama.cinematic.cinematic_cross_check import (
    validate_shot_direction_plan_against_story,
)
from living_diorama.cinematic.cinematic_schema_v1 import (
    CANONICAL_MOTION_TIME_SHA256,
    SHOT_PLAN_FORMAT,
    SHOT_SCHEMA_VERSION,
    validate_shot_direction_plan,
)
from living_diorama.cinematic.cinematic_spec import (
    BEAT_ANCHORS,
    CAMERA_ANCHORS,
    EMPHASIS_WEIGHTS,
    ESTABLISHING_ANCHOR,
    MIN_SHOT_FRAMES,
    REASON_CODES,
    SHOT_KINDS,
    catalogue_document,
    catalogue_sha256,
)
from living_diorama.cinematic.shot_planner import (
    build_shot_direction_plan_bytes,
    build_shot_direction_plan_document,
    resolve_motion_time_binding,
)

__all__ = [
    "BEAT_ANCHORS",
    "CAMERA_ANCHORS",
    "CANONICAL_MOTION_TIME_SHA256",
    "EMPHASIS_WEIGHTS",
    "ESTABLISHING_ANCHOR",
    "MIN_SHOT_FRAMES",
    "REASON_CODES",
    "SHOT_KINDS",
    "SHOT_PLAN_FORMAT",
    "SHOT_SCHEMA_VERSION",
    "build_shot_direction_plan_bytes",
    "build_shot_direction_plan_document",
    "catalogue_document",
    "catalogue_sha256",
    "resolve_motion_time_binding",
    "validate_shot_direction_plan",
    "validate_shot_direction_plan_against_story",
]
