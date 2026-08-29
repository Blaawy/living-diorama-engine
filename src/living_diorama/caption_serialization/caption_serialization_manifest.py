"""Turn one serialization's captured facts into an Episode Caption Serialization Manifest.

This module is pure and knows nothing about the filesystem. It is handed the
validated caption plan, the exact captured bytes that plan was parsed from, and
the two serialized sidecar artifacts, and turns them into the document that
proves what exists. Keeping it here means the manifest's rules can be attacked
in ordinary tests, and means the publisher cannot quietly restate an accounting
the plan does not carry.

Every restated value -- the seven source facts, the clock, the three
frame-authoritative accounting counts -- is copied from the validated plan,
never recomputed and never converted: the only wall-clock representation of the
plan is the sidecar bytes themselves.
"""

from typing import cast

from living_diorama.caption.caption_schema_v1 import validate_episode_caption_plan
from living_diorama.caption_serialization.caption_serialization_schema_v1 import (
    JsonValue,
    validate_episode_caption_serialization_manifest,
)
from living_diorama.caption_serialization.caption_serialization_spec import (
    CAPTION_SERIALIZATION_MANIFEST_FORMAT,
    CAPTION_SERIALIZATION_SCHEMA_VERSION,
    CAPTION_TIMESTAMP_POLICY_V1,
    SRT_FORMAT_NAME,
    SRT_SUFFIX,
    VTT_FORMAT_NAME,
    VTT_SUFFIX,
    caption_serialization_id,
    sidecar_filename,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex


def build_episode_caption_serialization_manifest_document(
    *,
    caption_plan: object,
    caption_plan_bytes: bytes,
    srt_bytes: bytes,
    vtt_bytes: bytes,
) -> dict[str, JsonValue]:
    """Return the manifest for one completed caption serialization.

    Args:
        caption_plan: The parsed, gate-verified Phase 32 caption plan this
            serialization bound.
        caption_plan_bytes: The exact captured bytes ``caption_plan`` was parsed
            from; their digest is bound as ``caption_plan_sha256`` and they must
            be the plan's own canonical encoding -- the single-capture law.
        srt_bytes: The serialized SRT artifact's exact bytes.
        vtt_bytes: The serialized WebVTT artifact's exact bytes.

    Returns:
        The complete, validated manifest document.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If the plan is invalid, or the captured bytes are not the
            plan's own canonical encoding.
    """
    plan = validate_episode_caption_plan(caption_plan)
    if type(caption_plan_bytes) is not bytes:
        raise TypeError(
            f"caption_plan_bytes must be bytes, got {type(caption_plan_bytes).__name__}"
        )
    if type(srt_bytes) is not bytes:
        raise TypeError(f"srt_bytes must be bytes, got {type(srt_bytes).__name__}")
    if type(vtt_bytes) is not bytes:
        raise TypeError(f"vtt_bytes must be bytes, got {type(vtt_bytes).__name__}")
    if caption_plan_bytes != dumps_canonical(plan, "caption plan"):
        raise ValueError(
            "caption_plan_bytes are not the canonical encoding of the validated caption "
            "plan; the manifest binds the digest of the one captured observation, never a "
            "second serialization of it"
        )

    plan_source = cast(dict[str, JsonValue], plan["source"])
    plan_clock = cast(dict[str, JsonValue], plan["clock"])
    plan_accounting = cast(dict[str, JsonValue], plan["accounting"])

    source: dict[str, JsonValue] = {
        "caption_plan_sha256": sha256_hex(caption_plan_bytes),
        "caption_schema_version": plan["schema_version"],
        "episode": plan_source["episode"],
        "mode": plan_source["mode"],
        "presentation_plan_sha256": plan_source["presentation_plan_sha256"],
        "presentation_schema_version": plan_source["presentation_schema_version"],
        "previous_episode": plan_source["previous_episode"],
        "realization_plan_sha256": plan_source["realization_plan_sha256"],
        "realization_schema_version": plan_source["realization_schema_version"],
    }

    episode_id = caption_serialization_id(
        mode=cast(str, plan_source["mode"]),
        episode=cast(int, plan_source["episode"]),
        previous_episode=cast("int | None", plan_source["previous_episode"]),
    )

    document: dict[str, JsonValue] = {
        "accounting": {
            "caption_frames_total": plan_accounting["caption_frames_total"],
            "captions_total": plan_accounting["captions_total"],
            "uncaptioned_frames_total": plan_accounting["uncaptioned_frames_total"],
        },
        "clock": {
            "fps": plan_clock["fps"],
            "presentation_frames_total": plan_clock["presentation_frames_total"],
        },
        "format": CAPTION_SERIALIZATION_MANIFEST_FORMAT,
        "policy": CAPTION_TIMESTAMP_POLICY_V1,
        "schema_version": CAPTION_SERIALIZATION_SCHEMA_VERSION,
        "sidecars": {
            "srt": {
                "bytes": len(srt_bytes),
                "file": sidecar_filename(episode_id, SRT_SUFFIX),
                "format": SRT_FORMAT_NAME,
                "sha256": sha256_hex(srt_bytes),
            },
            "vtt": {
                "bytes": len(vtt_bytes),
                "file": sidecar_filename(episode_id, VTT_SUFFIX),
                "format": VTT_FORMAT_NAME,
                "sha256": sha256_hex(vtt_bytes),
            },
        },
        "source": source,
    }
    return validate_episode_caption_serialization_manifest(document)


def build_episode_caption_serialization_manifest_bytes(
    *,
    caption_plan: object,
    caption_plan_bytes: bytes,
    srt_bytes: bytes,
    vtt_bytes: bytes,
) -> bytes:
    """Return the canonical bytes of one episode caption serialization manifest."""
    return dumps_canonical(
        build_episode_caption_serialization_manifest_document(
            caption_plan=caption_plan,
            caption_plan_bytes=caption_plan_bytes,
            srt_bytes=srt_bytes,
            vtt_bytes=vtt_bytes,
        ),
        "episode caption serialization manifest",
    )


__all__ = [
    "build_episode_caption_serialization_manifest_bytes",
    "build_episode_caption_serialization_manifest_document",
]
