"""Read-only export of persisted world snapshots for external visualization.

This package may only ever read persisted output through
``living_diorama.persistence`` -- it must never mutate simulation state, draw
randomness, or write anything into a save root. Phase 14 implements the first
layer: the deterministic, consumer-neutral Render Export projection of one
verified episode. Later media layers (master scene, narration, editing) are
downstream consumers of that contract and are not part of this package yet.
"""

from living_diorama.render.render_exporter import (
    build_render_export_bytes,
    build_render_export_document,
    write_render_export,
)
from living_diorama.render.render_schema_v1 import (
    RENDER_EXPORT_FORMAT,
    RENDER_SCHEMA_VERSION,
    validate_render_export,
)

__all__ = [
    "RENDER_EXPORT_FORMAT",
    "RENDER_SCHEMA_VERSION",
    "build_render_export_bytes",
    "build_render_export_document",
    "validate_render_export",
    "write_render_export",
]
