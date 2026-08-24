"""Episode render execution: deterministic documents, measured pixels.

This package owns one question: given a directed episode that Phase 22 already
cut, which frames become image files, named how, rendered under which
presentation profile -- and did that actually happen.

RENDER EXECUTION REALIZES PRESENTATION. IT DIRECTS NOTHING.

It never chooses a camera, never moves a shot boundary, never re-ranks a beat,
and never decides that something should have been shown. Phase 21 owns what
mattered, Phase 22 owns where the viewer looks, Phase 17 owns the clock, and
this layer photographs the result of those decisions exactly as they stand. A
beat that Phase 22 honestly left unshown stays unshown here: no frame is
rendered to make up for it.

Downstream layers (editing, audio, narration realization, encoding, packaging)
consume the frames and manifest this package produces and are not part of it.
"""

from living_diorama.render_execution.render_execution_schema_v1 import (
    validate_episode_render_manifest,
    validate_episode_render_plan,
)
from living_diorama.render_execution.render_execution_spec import (
    RENDER_MANIFEST_FORMAT,
    RENDER_PLAN_FORMAT,
    derive_emission,
    frame_filename,
    render_id,
    render_profile_document,
    render_profile_sha256,
)
from living_diorama.render_execution.render_manifest import (
    build_episode_render_manifest_bytes,
    build_episode_render_manifest_document,
)
from living_diorama.render_execution.render_planner import (
    build_episode_render_plan_bytes,
    build_episode_render_plan_document,
    load_episode_render_plan,
)

__all__ = [
    "RENDER_MANIFEST_FORMAT",
    "RENDER_PLAN_FORMAT",
    "build_episode_render_manifest_bytes",
    "build_episode_render_manifest_document",
    "build_episode_render_plan_bytes",
    "build_episode_render_plan_document",
    "derive_emission",
    "frame_filename",
    "load_episode_render_plan",
    "render_id",
    "render_profile_document",
    "render_profile_sha256",
    "validate_episode_render_manifest",
    "validate_episode_render_plan",
]
