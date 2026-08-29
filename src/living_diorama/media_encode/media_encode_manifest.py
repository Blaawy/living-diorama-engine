"""Turn one encode's captured facts into an Episode Media Encode Manifest.

This module is pure and knows nothing about the filesystem or any tool. It is handed the
two bound manifests this encode consumed (and their exact captured bytes), what the run
measured about the one captured MP4 observation, the normalized tool-attested streams
block, and the two recorded version lines, and turns them into the document that proves
what exists. Keeping it here means the manifest's rules can be attacked in ordinary
tests, and means the executor cannot quietly restate a fact its captures do not carry.

Every cross join is proven here before a document exists: the two consumed manifests must
agree on the episode identity, the presentation clock (fps and frames), and -- the
decisive lineage join -- the ``presentation_plan_sha256`` both descended from, so the
assembly and the captions can never come from different presentations.
"""

from typing import cast

from living_diorama.caption_serialization.caption_serialization_schema_v1 import (
    validate_episode_caption_serialization_manifest,
)
from living_diorama.media_assembly.media_assembly_schema_v1 import (
    validate_episode_media_assembly_manifest,
)
from living_diorama.media_encode.media_encode_command import build_media_encode_command
from living_diorama.media_encode.media_encode_schema_v1 import (
    JsonValue,
    validate_episode_media_encode_manifest,
)
from living_diorama.media_encode.media_encode_spec import (
    MEDIA_ENCODE_MANIFEST_FORMAT,
    MEDIA_ENCODE_PROFILE_V1,
    MEDIA_ENCODE_SCHEMA_VERSION,
    MediaEncodeRefused,
    media_encode_id,
    media_filename,
    media_temp_filename,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.render_execution.render_execution_spec import render_profile_document


def require_encode_sources_join(
    assembly_manifest: object, captions_manifest: object
) -> tuple[dict[str, JsonValue], dict[str, JsonValue]]:
    """Verify the two consumed manifests join, and return them validated.

    The joins, whole: both documents validate under their LOCKED schemas; their episode
    identities (mode, episode, previous_episode) are equal; the captions manifest's
    two-key clock equals the assembly clock's fps and presentation_frames_total; and both
    bind the SAME ``presentation_plan_sha256`` -- the decisive lineage join, re-provable
    forever from the two provenance copies a published directory carries.

    Raises:
        TypeError: If a document carries a wrongly typed value.
        ValueError: If either document is invalid.
        MediaEncodeRefused: If any join fails.
    """
    assembly = validate_episode_media_assembly_manifest(assembly_manifest)
    captions = validate_episode_caption_serialization_manifest(captions_manifest)

    assembly_source = cast(dict[str, JsonValue], assembly["source"])
    captions_source = cast(dict[str, JsonValue], captions["source"])
    for field in ("episode", "mode", "previous_episode"):
        if assembly_source.get(field) != captions_source.get(field):
            raise MediaEncodeRefused(
                f"the assembly manifest's source.{field} is {assembly_source.get(field)!r}, "
                f"but the caption serialization manifest's is {captions_source.get(field)!r}; "
                "one episode has one identity"
            )

    assembly_clock = cast(dict[str, JsonValue], assembly["clock"])
    captions_clock = cast(dict[str, JsonValue], captions["clock"])
    for field in ("fps", "presentation_frames_total"):
        if assembly_clock.get(field) != captions_clock.get(field):
            raise MediaEncodeRefused(
                f"the assembly clock's {field} is {assembly_clock.get(field)!r}, but the "
                f"caption serialization clock's is {captions_clock.get(field)!r}; both "
                "descend from one presentation"
            )

    if assembly_source.get("presentation_plan_sha256") != captions_source.get(
        "presentation_plan_sha256"
    ):
        raise MediaEncodeRefused(
            f"the assembly binds presentation_plan_sha256 "
            f"{assembly_source.get('presentation_plan_sha256')!r}, but the caption "
            f"serialization binds {captions_source.get('presentation_plan_sha256')!r}; the "
            "two inputs descend from different presentations and are never joined"
        )
    return assembly, captions


def build_episode_media_encode_manifest_document(
    *,
    assembly_manifest: object,
    assembly_manifest_bytes: bytes,
    captions_manifest: object,
    captions_manifest_bytes: bytes,
    video_bytes: int,
    video_sha256: str,
    streams: dict[str, object],
    ffmpeg_version: str,
    ffprobe_version: str,
) -> dict[str, JsonValue]:
    """Return the manifest for one completed final-media projection.

    Args:
        assembly_manifest: The parsed, audit-verified Phase 33 manifest this encode bound.
        assembly_manifest_bytes: Its exact captured bytes; digest-bound and copied.
        captions_manifest: The parsed, audit-verified Phase 34 manifest this encode bound.
        captions_manifest_bytes: Its exact captured bytes; digest-bound and copied.
        video_bytes: The captured MP4 observation's exact byte length.
        video_sha256: The captured MP4 observation's digest.
        streams: The normalized 21-key tool-attested streams block, decoded count
            included.
        ffmpeg_version: The gated encoder's recorded first version line.
        ffprobe_version: The gated prober's recorded first version line.

    Returns:
        The complete, validated manifest document.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If a bound document is invalid or a captured byte string is not the
            document's own canonical encoding.
        MediaEncodeRefused: If the two consumed manifests do not join.
    """
    assembly, captions = require_encode_sources_join(assembly_manifest, captions_manifest)
    if type(assembly_manifest_bytes) is not bytes:
        raise TypeError(
            f"assembly_manifest_bytes must be bytes, got {type(assembly_manifest_bytes).__name__}"
        )
    if type(captions_manifest_bytes) is not bytes:
        raise TypeError(
            f"captions_manifest_bytes must be bytes, got {type(captions_manifest_bytes).__name__}"
        )
    if assembly_manifest_bytes != dumps_canonical(assembly, "episode media assembly manifest"):
        raise ValueError(
            "assembly_manifest_bytes are not the canonical encoding of the validated "
            "assembly manifest; the manifest binds the one captured observation"
        )
    if captions_manifest_bytes != dumps_canonical(
        captions, "episode caption serialization manifest"
    ):
        raise ValueError(
            "captions_manifest_bytes are not the canonical encoding of the validated "
            "caption serialization manifest; the manifest binds the one captured observation"
        )
    if type(video_bytes) is not int or video_bytes < 1:
        raise ValueError(f"video_bytes must be a positive int, got {video_bytes!r}")
    if type(streams) is not dict:
        raise TypeError(f"streams must be a dict, got {type(streams).__name__}")
    for key in ("audio_channels", "video_frames_counted"):
        if type(streams.get(key)) is not int:
            raise ValueError(
                f"streams {key} must be an int before a manifest is built, got {streams.get(key)!r}"
            )

    assembly_source = cast(dict[str, JsonValue], assembly["source"])
    mode = cast(str, assembly_source["mode"])
    episode = cast(int, assembly_source["episode"])
    previous_episode = cast("int | None", assembly_source["previous_episode"])
    episode_id = media_encode_id(mode=mode, episode=episode, previous_episode=previous_episode)

    assembly_clock = cast(dict[str, JsonValue], assembly["clock"])
    captions_sidecars = cast(dict[str, JsonValue], captions["sidecars"])
    srt_record = cast(dict[str, JsonValue], captions_sidecars["srt"])
    vtt_record = cast(dict[str, JsonValue], captions_sidecars["vtt"])

    profile_owned = cast(dict[str, object], render_profile_document()["owned"])

    document: dict[str, JsonValue] = {
        "captions": {
            "srt": {
                "bytes": srt_record["bytes"],
                "file": srt_record["file"],
                "sha256": srt_record["sha256"],
            },
            "vtt": {
                "bytes": vtt_record["bytes"],
                "file": vtt_record["file"],
                "sha256": vtt_record["sha256"],
            },
        },
        "clock": {key: assembly_clock[key] for key in sorted(assembly_clock)},
        "completeness": {
            "complete": cast(int, streams["video_frames_counted"])
            == cast(int, assembly_clock["presentation_frames_total"]),
            "video_frames_counted": cast(JsonValue, streams["video_frames_counted"]),
            "video_frames_expected": assembly_clock["presentation_frames_total"],
        },
        "format": MEDIA_ENCODE_MANIFEST_FORMAT,
        "invocation": {
            "ffmpeg_version": ffmpeg_version,
            "ffprobe_version": ffprobe_version,
            "logical_argv": list(
                build_media_encode_command(
                    fps=cast(int, assembly_clock["fps"]),
                    presentation_frames_total=cast(
                        int, assembly_clock["presentation_frames_total"]
                    ),
                    audio_sample_rate_hz=cast(int, assembly_clock["audio_sample_rate_hz"]),
                    audio_channels=cast(int, streams["audio_channels"]),
                    media_temp_filename=media_temp_filename(episode_id),
                )
            ),
            "profile_id": MEDIA_ENCODE_PROFILE_V1,
        },
        "render": {
            "height": cast(int, profile_owned["resolution_y"]),
            "width": cast(int, profile_owned["resolution_x"]),
        },
        "schema_version": MEDIA_ENCODE_SCHEMA_VERSION,
        "source": {
            "caption_serialization_manifest_sha256": sha256_hex(captions_manifest_bytes),
            "caption_serialization_schema_version": captions["schema_version"],
            "episode": episode,
            "media_assembly_manifest_sha256": sha256_hex(assembly_manifest_bytes),
            "media_assembly_schema_version": assembly["schema_version"],
            "mode": mode,
            "previous_episode": previous_episode,
        },
        "streams": cast(dict[str, JsonValue], dict(streams)),
        "video": {
            "bytes": video_bytes,
            "file": media_filename(episode_id),
            "sha256": video_sha256,
        },
    }
    return validate_episode_media_encode_manifest(document)


def build_episode_media_encode_manifest_bytes(
    *,
    assembly_manifest: object,
    assembly_manifest_bytes: bytes,
    captions_manifest: object,
    captions_manifest_bytes: bytes,
    video_bytes: int,
    video_sha256: str,
    streams: dict[str, object],
    ffmpeg_version: str,
    ffprobe_version: str,
) -> bytes:
    """Return the canonical bytes of one episode media encode manifest."""
    return dumps_canonical(
        build_episode_media_encode_manifest_document(
            assembly_manifest=assembly_manifest,
            assembly_manifest_bytes=assembly_manifest_bytes,
            captions_manifest=captions_manifest,
            captions_manifest_bytes=captions_manifest_bytes,
            video_bytes=video_bytes,
            video_sha256=video_sha256,
            streams=streams,
            ffmpeg_version=ffmpeg_version,
            ffprobe_version=ffprobe_version,
        ),
        "episode media encode manifest",
    )


__all__ = [
    "build_episode_media_encode_manifest_bytes",
    "build_episode_media_encode_manifest_document",
    "require_encode_sources_join",
]
