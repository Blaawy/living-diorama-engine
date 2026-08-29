"""Phase 34: deterministic caption serialization of the locked Episode Caption Plan.

The caption plan froze WHAT is legible and WHEN, on the presentation clock; this package
gives it the one thing it deliberately lacks -- a target file format. One pinned integer
timestamp law (``caption_timestamp_policy_v1``: ``offset * 1000 // fps``, floor) projects
each cue's frames onto the wall clock, and two byte-sealed sidecar artifacts -- SRT and
WebVTT, under exact frozen grammars -- carry every locked sentence verbatim or not at all.
The published directory holds exactly four owned regular files: the manifest, the exact-
byte plan copy, and the two sidecars, whose basenames equal the directory id.

THE CAPTION SERIALIZATION MAKES A LOCKED PLAN LEGIBLE TO A TARGET FILE FORMAT. IT DECIDES
NO TIMING AND NO WORDING. It never rewrites, wraps, styles or positions a sentence; never
chooses a font; never measures speech; never performs recognition or alignment; never
burns a pixel; never encodes, muxes or packages anything. The viewer's actual display
surface belongs to the player that reads the sidecars, and to no phase of this project.

This phase's output is CLASS A deterministic: the same accepted plan bytes produce
byte-identical manifest, SRT and VTT on any machine, and the self-contained audit
re-serializes both sidecars from the copied plan and requires exact byte equality.

Downstream layers (final episode media) consume the artifacts this package produces and
are not part of it: no module here imports ``living_diorama.media_encode``, and the
boundary guard proves it.
"""

from living_diorama.caption_serialization.caption_serialization_audit import (
    audit_caption_serialization_directory,
)
from living_diorama.caption_serialization.caption_serialization_manifest import (
    build_episode_caption_serialization_manifest_bytes,
    build_episode_caption_serialization_manifest_document,
)
from living_diorama.caption_serialization.caption_serialization_publisher import (
    publish_episode_caption_serialization,
)
from living_diorama.caption_serialization.caption_serialization_schema_v1 import (
    validate_episode_caption_serialization_manifest,
)
from living_diorama.caption_serialization.caption_serialization_spec import (
    CAPTION_PLAN_COPY_FILENAME,
    CAPTION_SERIALIZATION_MANIFEST_FILENAME,
    CAPTION_SERIALIZATION_MANIFEST_FORMAT,
    CAPTION_SERIALIZATION_SCHEMA_VERSION,
    CAPTION_TIMESTAMP_POLICY_V1,
    CaptionSerializationRefused,
    caption_serialization_id,
    require_carriable_caption_text,
    sidecar_filename,
)
from living_diorama.caption_serialization.caption_serialization_staging import (
    CaptionSerializationDirectoryRefused,
)
from living_diorama.caption_serialization.caption_timestamp import (
    boundary_ms,
    cue_span_ms,
    derive_cue_spans,
    format_timestamp,
)
from living_diorama.caption_serialization.srt_writer import serialize_srt_bytes
from living_diorama.caption_serialization.vtt_writer import serialize_vtt_bytes

__all__ = [
    "CAPTION_PLAN_COPY_FILENAME",
    "CAPTION_SERIALIZATION_MANIFEST_FILENAME",
    "CAPTION_SERIALIZATION_MANIFEST_FORMAT",
    "CAPTION_SERIALIZATION_SCHEMA_VERSION",
    "CAPTION_TIMESTAMP_POLICY_V1",
    "CaptionSerializationDirectoryRefused",
    "CaptionSerializationRefused",
    "audit_caption_serialization_directory",
    "boundary_ms",
    "build_episode_caption_serialization_manifest_bytes",
    "build_episode_caption_serialization_manifest_document",
    "caption_serialization_id",
    "cue_span_ms",
    "derive_cue_spans",
    "format_timestamp",
    "publish_episode_caption_serialization",
    "require_carriable_caption_text",
    "serialize_srt_bytes",
    "serialize_vtt_bytes",
    "sidecar_filename",
    "validate_episode_caption_serialization_manifest",
]
