"""Episode Media Encode Manifest format V1: one watchable projection, classified truth.

A media encode manifest says, for one audited Phase 33 assembly and one audited Phase 34
caption serialization, which final episode file was projected from them -- its exact bytes
and digest -- under which pinned invocation, carrying which byte-exact sidecars, with the
tool-attested stream facts recorded beside the byte-reprovable ones. Correction E,
structural: the ``source``, ``clock``, ``render``, ``video``, ``captions`` and
``completeness`` blocks are byte- or code-reprovable; the ``streams`` block and the two
recorded version lines are TOOL-ATTESTED -- this tool-free validator proves their internal
laws exactly and completely, and never claims to have probed or decoded the file itself.

The document shape is exact at every level this module governs. A key that is missing
means the manifest is incomplete; a key that is extra means it was written by something
this contract does not describe. Both are refused, never repaired.

Two laws here are stronger than shape. The ``invocation.logical_argv`` is REBUILT from
this manifest's own clock, streams and identity facts through the one frozen command
builder and required byte-equal -- so a flag edit, a missing, wrong-valued, duplicated or
misplaced ``-threads:v``, or a placeholder resolved to a real path refuses tool-free,
forever. And the ``render`` block is proven against the in-code render profile document
the digest chain names -- the one authority ``render_profile_sha256`` pins -- so a
dimension can never be invented here.
"""

from math import gcd
from typing import Final, cast

from living_diorama.caption_serialization.caption_serialization_spec import (
    SRT_SUFFIX,
    VTT_SUFFIX,
    sidecar_filename,
)
from living_diorama.media_encode.media_encode_command import build_media_encode_command
from living_diorama.media_encode.media_encode_probe import require_stream_facts
from living_diorama.media_encode.media_encode_spec import (
    MEDIA_ENCODE_MANIFEST_FORMAT,
    MEDIA_ENCODE_PROFILE_V1,
    MEDIA_ENCODE_SCHEMA_VERSION,
    MediaEncodeRefused,
    media_encode_id,
    media_filename,
    media_temp_filename,
)
from living_diorama.media_encode.media_encode_version import parse_version_first_line
from living_diorama.narration.narration_schema_v1 import MODE_BASELINE, PLAN_MODES
from living_diorama.persistence.schema.state_hash import require_hash_hex
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_text,
)
from living_diorama.render_execution.render_execution_spec import render_profile_document

SUPPORTED_MEDIA_ASSEMBLY_SCHEMA_VERSION: Final = 1
SUPPORTED_CAPTION_SERIALIZATION_SCHEMA_VERSION: Final = 1
"""The upstream contract versions this build speaks, restated per phase law."""

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
"""The JSON value shape this contract works in.

Declared here rather than imported from an upstream layer for the same reason every
locked phase declares its own: a shared alias is not worth a hole in a boundary.
"""

TOP_LEVEL_KEYS: Final = frozenset(
    {
        "captions",
        "clock",
        "completeness",
        "format",
        "invocation",
        "render",
        "schema_version",
        "source",
        "streams",
        "video",
    }
)
"""Exactly the ten top-level keys an episode media encode manifest carries."""

SOURCE_KEYS: Final = frozenset(
    {
        "caption_serialization_manifest_sha256",
        "caption_serialization_schema_version",
        "episode",
        "media_assembly_manifest_sha256",
        "media_assembly_schema_version",
        "mode",
        "previous_episode",
    }
)
"""Exactly the keys binding a manifest to the two manifests it consumed.

[byte-reprovable] Each digest is re-hashed from the provenance copy beside the manifest;
the deeper chain is bound transitively through those copies' own source blocks.
"""

CLOCK_KEYS: Final = frozenset(
    {
        "audio_sample_rate_hz",
        "audio_samples_total",
        "fps",
        "presentation_frames_total",
        "samples_per_presentation_frame",
        "semantic_final_frame",
        "semantic_first_frame",
        "witness_frame",
    }
)
"""Exactly the Phase 33 clock block, restated byte-for-byte. [byte-reprovable]"""

RENDER_KEYS: Final = frozenset({"height", "width"})
"""Exactly the restated authoritative render dimensions. [code-reprovable]"""

VIDEO_KEYS: Final = frozenset({"bytes", "file", "sha256"})
"""Exactly the keys the produced episode file's record carries. [byte-reprovable]"""

CAPTION_RECORD_KEYS: Final = frozenset({"bytes", "file", "sha256"})
"""Exactly the keys one carried sidecar's record carries. [byte-reprovable]"""

CAPTIONS_KEYS: Final = frozenset({"srt", "vtt"})
"""Exactly the two records the captions block carries."""

INVOCATION_KEYS: Final = frozenset(
    {"ffmpeg_version", "ffprobe_version", "logical_argv", "profile_id"}
)
"""Exactly the keys the path-neutral invocation record carries.

[tool-attested in origin, structurally validated forever] The version lines are the
tools' recorded first lines; the logical argv is rebuilt and byte-compared here.
"""

STREAMS_KEYS: Final = frozenset(
    {
        "audio_channels",
        "audio_codec",
        "audio_duration_ts",
        "audio_index",
        "audio_sample_rate",
        "audio_samples_decoded",
        "audio_start_time",
        "audio_time_base",
        "container_formats",
        "nb_streams",
        "video_avg_frame_rate",
        "video_codec",
        "video_duration_ts",
        "video_frames_counted",
        "video_height",
        "video_index",
        "video_pix_fmt",
        "video_r_frame_rate",
        "video_start_time",
        "video_time_base",
        "video_width",
    }
)
"""Exactly the twenty-one normalized stream facts. [TOOL-ATTESTED]

This validator proves their internal laws -- types, reduced rationals, and every
equality and closure the recorded integers can prove among themselves and against the
clock and render authorities -- and never claims to have probed or decoded the file:
that re-proof belongs to the tool-bearing executor, its no-op, and the acceptance.
"""

COMPLETENESS_KEYS: Final = frozenset({"complete", "video_frames_counted", "video_frames_expected"})
"""Exactly the keys the completeness block carries. [byte-reprovable internally]"""


def _require_document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    for key in value:
        if type(key) is not str:
            raise TypeError(f"{description} keys must be str, got {type(key).__name__}")
    return cast(dict[str, JsonValue], value)


def _require_member(value: object, allowed: tuple[str, ...], description: str) -> str:
    text = require_text(value, description)
    if text not in allowed:
        raise ValueError(f"{description} is {text!r}; expected one of {list(allowed)}")
    return text


def _require_null(value: object, description: str, because: str) -> None:
    if value is not None:
        raise ValueError(f"{description} is {value!r}, but {because}")


def _require_rational(value: object, description: str) -> tuple[int, int]:
    if type(value) is not list:
        raise TypeError(f"{description} must be a two-int list, got {type(value).__name__}")
    pair = cast(list[JsonValue], value)
    if len(pair) != 2:
        raise ValueError(f"{description} must carry exactly two members, got {len(pair)}")
    numerator = pair[0]
    denominator = pair[1]
    if type(numerator) is not int or type(denominator) is not int:
        raise TypeError(f"{description} members must be int, got {pair!r}")
    if denominator < 1:
        raise ValueError(f"{description} denominator must be >= 1, got {denominator}")
    if gcd(abs(numerator), denominator) not in (0, 1):
        raise ValueError(f"{description} must be a reduced rational, got {pair!r}")
    return (numerator, denominator)


def _validate_file_record(
    value: object, description: str, *, expected_file: str
) -> dict[str, JsonValue]:
    record = _require_document(value, description)
    require_exact_keys(record, CAPTION_RECORD_KEYS, description)
    byte_length = require_exact_int(record.get("bytes"), f"{description} bytes")
    if byte_length < 1:
        raise ValueError(f"{description} bytes must be >= 1, got {byte_length}")
    file_value = require_text(record.get("file"), f"{description} file")
    if file_value != expected_file:
        raise ValueError(f"{description} file is {file_value!r}, expected {expected_file!r}")
    require_hash_hex(record.get("sha256"), f"{description} sha256")
    return record


def validate_episode_media_encode_manifest(value: object) -> dict[str, JsonValue]:
    """Verify a document's Episode Media Encode Manifest V1 envelope, and return it.

    This validator is deliberately self-contained and tool-free: it proves everything the
    manifest can prove about itself -- including the rebuilt logical argv and the in-code
    render authority -- and nothing that needs the provenance copies, the published files,
    or a tool. See the module docstring for the truth classes and which layer proves the
    rest.

    Raises:
        TypeError: If any value has the wrong exact type.
        ValueError: If any key set, vocabulary member, ordering, bound, closure or
            internal agreement is violated.
    """
    document = _require_document(value, "media encode manifest")
    require_exact_keys(document, TOP_LEVEL_KEYS, "media encode manifest")

    tag = require_text(document.get("format"), "media encode manifest format")
    if tag != MEDIA_ENCODE_MANIFEST_FORMAT:
        raise ValueError(
            f"media encode manifest declares format {tag!r}; this build reads "
            f"{MEDIA_ENCODE_MANIFEST_FORMAT!r} only"
        )
    version = require_exact_int(
        document.get("schema_version"), "media encode manifest schema_version"
    )
    if version != MEDIA_ENCODE_SCHEMA_VERSION:
        raise ValueError(
            f"media encode manifest declares unsupported schema version {version}; this "
            f"build reads version {MEDIA_ENCODE_SCHEMA_VERSION} only"
        )

    source = _require_document(document.get("source"), "media encode manifest source")
    require_exact_keys(source, SOURCE_KEYS, "media encode manifest source")
    mode = _require_member(source.get("mode"), PLAN_MODES, "media encode manifest source mode")
    episode = require_exact_int(source.get("episode"), "media encode manifest source episode")
    assembly_version = require_exact_int(
        source.get("media_assembly_schema_version"),
        "media encode manifest source media_assembly_schema_version",
    )
    if assembly_version != SUPPORTED_MEDIA_ASSEMBLY_SCHEMA_VERSION:
        raise ValueError(
            f"media encode manifest binds media assembly schema version {assembly_version}; "
            f"this build speaks version {SUPPORTED_MEDIA_ASSEMBLY_SCHEMA_VERSION} only"
        )
    captions_version = require_exact_int(
        source.get("caption_serialization_schema_version"),
        "media encode manifest source caption_serialization_schema_version",
    )
    if captions_version != SUPPORTED_CAPTION_SERIALIZATION_SCHEMA_VERSION:
        raise ValueError(
            f"media encode manifest binds caption serialization schema version "
            f"{captions_version}; this build speaks version "
            f"{SUPPORTED_CAPTION_SERIALIZATION_SCHEMA_VERSION} only"
        )
    for field in ("caption_serialization_manifest_sha256", "media_assembly_manifest_sha256"):
        require_hash_hex(source.get(field), f"media encode manifest source {field}")

    previous = source.get("previous_episode")
    if mode == MODE_BASELINE:
        _require_null(
            previous,
            "media encode manifest source previous_episode",
            "a baseline projection presents one export's episode and follows no episode",
        )
        if episode != 0:
            raise ValueError(
                f"media encode manifest source declares mode 'baseline' with episode "
                f"{episode}; a baseline is always episode 0"
            )
        previous_episode: int | None = None
    else:
        previous_episode = require_exact_int(
            previous, "media encode manifest source previous_episode"
        )
        if episode != previous_episode + 1:
            raise ValueError(
                f"media encode manifest source declares episode {episode} following "
                f"{previous_episode}; a transition's episode always directly follows its "
                "previous episode"
            )
    episode_id = media_encode_id(mode=mode, episode=episode, previous_episode=previous_episode)

    # ---- the restated Phase 33 clock, with its own integer closure re-run whole ----
    clock = _require_document(document.get("clock"), "media encode manifest clock")
    require_exact_keys(clock, CLOCK_KEYS, "media encode manifest clock")
    resolved: dict[str, int] = {}
    for key in sorted(CLOCK_KEYS):
        resolved[key] = require_exact_int(clock.get(key), f"media encode manifest clock {key}")
    if resolved["fps"] < 1:
        raise ValueError(f"media encode manifest clock fps must be >= 1, got {resolved['fps']}")
    if resolved["presentation_frames_total"] < 1:
        raise ValueError(
            "media encode manifest clock presentation_frames_total must be >= 1, got "
            f"{resolved['presentation_frames_total']}"
        )
    if resolved["audio_sample_rate_hz"] % resolved["fps"] != 0:
        raise ValueError(
            f"media encode manifest clock audio_sample_rate_hz "
            f"{resolved['audio_sample_rate_hz']} is not evenly divisible by fps "
            f"{resolved['fps']}; the integer clock does not close"
        )
    expected_spf = resolved["audio_sample_rate_hz"] // resolved["fps"]
    if resolved["samples_per_presentation_frame"] != expected_spf:
        raise ValueError(
            f"media encode manifest clock samples_per_presentation_frame is "
            f"{resolved['samples_per_presentation_frame']}, but the rate and fps derive "
            f"{expected_spf}"
        )
    expected_total = resolved["presentation_frames_total"] * expected_spf
    if resolved["audio_samples_total"] != expected_total:
        raise ValueError(
            f"media encode manifest clock audio_samples_total is "
            f"{resolved['audio_samples_total']}, but {resolved['presentation_frames_total']} "
            f"frames at {expected_spf} samples per frame is {expected_total}"
        )
    if resolved["semantic_first_frame"] < 1:
        raise ValueError(
            "media encode manifest clock semantic_first_frame must be >= 1, got "
            f"{resolved['semantic_first_frame']}"
        )
    if resolved["semantic_final_frame"] < resolved["semantic_first_frame"]:
        raise ValueError(
            f"media encode manifest clock semantic_final_frame "
            f"{resolved['semantic_final_frame']} precedes semantic_first_frame "
            f"{resolved['semantic_first_frame']}"
        )
    if resolved["witness_frame"] != resolved["semantic_final_frame"] + 1:
        raise ValueError(
            f"media encode manifest clock witness_frame must equal semantic_final_frame + 1; "
            f"got {resolved['witness_frame']}"
        )

    # ---- the restated render authority, proven against the digest-named in-code profile --
    render = _require_document(document.get("render"), "media encode manifest render")
    require_exact_keys(render, RENDER_KEYS, "media encode manifest render")
    profile_owned = cast(dict[str, object], render_profile_document()["owned"])
    expected_width = cast(int, profile_owned["resolution_x"])
    expected_height = cast(int, profile_owned["resolution_y"])
    width = require_exact_int(render.get("width"), "media encode manifest render width")
    height = require_exact_int(render.get("height"), "media encode manifest render height")
    if width != expected_width or height != expected_height:
        raise ValueError(
            f"media encode manifest render is {width}x{height}, but the render profile the "
            f"digest chain names is {expected_width}x{expected_height}; a dimension is "
            "derived, never invented"
        )

    # ---- the produced episode file and the carried sidecars [byte-reprovable] ----
    _validate_file_record(
        document.get("video"),
        "media encode manifest video",
        expected_file=media_filename(episode_id),
    )
    captions = _require_document(document.get("captions"), "media encode manifest captions")
    require_exact_keys(captions, CAPTIONS_KEYS, "media encode manifest captions")
    _validate_file_record(
        captions.get("srt"),
        "media encode manifest captions srt",
        expected_file=sidecar_filename(episode_id, SRT_SUFFIX),
    )
    _validate_file_record(
        captions.get("vtt"),
        "media encode manifest captions vtt",
        expected_file=sidecar_filename(episode_id, VTT_SUFFIX),
    )

    # ---- the tool-attested streams block: internal laws proven whole, tool-free ----
    streams = _require_document(document.get("streams"), "media encode manifest streams")
    require_exact_keys(streams, STREAMS_KEYS, "media encode manifest streams")
    for key in (
        "audio_channels",
        "audio_duration_ts",
        "audio_index",
        "audio_sample_rate",
        "audio_samples_decoded",
        "nb_streams",
        "video_duration_ts",
        "video_frames_counted",
        "video_height",
        "video_index",
        "video_width",
    ):
        require_exact_int(streams.get(key), f"media encode manifest streams {key}")
    for key in (
        "audio_start_time",
        "audio_time_base",
        "video_avg_frame_rate",
        "video_r_frame_rate",
        "video_start_time",
        "video_time_base",
    ):
        _require_rational(streams.get(key), f"media encode manifest streams {key}")
    for key in ("audio_codec", "video_codec", "video_pix_fmt"):
        require_text(streams.get(key), f"media encode manifest streams {key}")
    container = streams.get("container_formats")
    if type(container) is not list or not container:
        raise TypeError("media encode manifest streams container_formats must be a non-empty list")
    for member in container:
        if type(member) is not str or not member:
            raise ValueError(
                "media encode manifest streams container_formats members must be non-empty "
                f"strings, got {member!r}"
            )
    try:
        require_stream_facts(
            cast(dict[str, object], streams),
            fps=resolved["fps"],
            presentation_frames_total=resolved["presentation_frames_total"],
            audio_sample_rate_hz=resolved["audio_sample_rate_hz"],
            audio_channels=cast(int, streams["audio_channels"]),
            audio_samples_total=resolved["audio_samples_total"],
            width=expected_width,
            height=expected_height,
        )
    except MediaEncodeRefused as error:
        raise ValueError(f"media encode manifest streams violate a recorded law: {error}") from None

    # ---- the path-neutral invocation, rebuilt whole and required byte-equal ----
    invocation = _require_document(document.get("invocation"), "media encode manifest invocation")
    require_exact_keys(invocation, INVOCATION_KEYS, "media encode manifest invocation")
    profile_id = require_text(
        invocation.get("profile_id"), "media encode manifest invocation profile_id"
    )
    if profile_id != MEDIA_ENCODE_PROFILE_V1:
        raise ValueError(
            f"media encode manifest invocation declares profile {profile_id!r}; this build "
            f"constructs {MEDIA_ENCODE_PROFILE_V1!r} only"
        )
    ffmpeg_version = require_text(
        invocation.get("ffmpeg_version"), "media encode manifest invocation ffmpeg_version"
    )
    ffprobe_version = require_text(
        invocation.get("ffprobe_version"), "media encode manifest invocation ffprobe_version"
    )
    try:
        parse_version_first_line(ffmpeg_version, "ffmpeg")
        parse_version_first_line(ffprobe_version, "ffprobe")
    except MediaEncodeRefused as error:
        raise ValueError(
            f"media encode manifest invocation records an ungated tool: {error}"
        ) from None

    logical_argv = invocation.get("logical_argv")
    if type(logical_argv) is not list:
        raise TypeError(
            "media encode manifest invocation logical_argv must be a list, got "
            f"{type(logical_argv).__name__}"
        )
    expected_argv = list(
        build_media_encode_command(
            fps=resolved["fps"],
            presentation_frames_total=resolved["presentation_frames_total"],
            audio_sample_rate_hz=resolved["audio_sample_rate_hz"],
            audio_channels=cast(int, streams["audio_channels"]),
            media_temp_filename=media_temp_filename(episode_id),
        )
    )
    if logical_argv != expected_argv:
        raise ValueError(
            "media encode manifest invocation logical_argv does not equal the reviewed "
            "profile rebuilt from this manifest's own clock and identity; a recorded "
            "invocation is re-derived, never trusted"
        )

    # ---- completeness: the verdict block, internally closed ----
    completeness = _require_document(
        document.get("completeness"), "media encode manifest completeness"
    )
    require_exact_keys(completeness, COMPLETENESS_KEYS, "media encode manifest completeness")
    counted = require_exact_int(
        completeness.get("video_frames_counted"),
        "media encode manifest completeness video_frames_counted",
    )
    expected_frames = require_exact_int(
        completeness.get("video_frames_expected"),
        "media encode manifest completeness video_frames_expected",
    )
    if counted != cast(int, streams["video_frames_counted"]):
        raise ValueError(
            f"media encode manifest completeness video_frames_counted is {counted}, but the "
            f"streams block records {streams['video_frames_counted']!r}"
        )
    if expected_frames != resolved["presentation_frames_total"]:
        raise ValueError(
            f"media encode manifest completeness video_frames_expected is {expected_frames}, "
            f"but the clock carries {resolved['presentation_frames_total']}"
        )
    complete = completeness.get("complete")
    if type(complete) is not bool:
        raise TypeError(
            "media encode manifest completeness complete must be a bool, got "
            f"{type(complete).__name__}"
        )
    if complete != (counted == expected_frames):
        raise ValueError(
            "media encode manifest completeness complete disagrees with its own counts"
        )

    return document


__all__ = [
    "CAPTIONS_KEYS",
    "CAPTION_RECORD_KEYS",
    "CLOCK_KEYS",
    "COMPLETENESS_KEYS",
    "INVOCATION_KEYS",
    "JsonValue",
    "RENDER_KEYS",
    "SOURCE_KEYS",
    "STREAMS_KEYS",
    "SUPPORTED_CAPTION_SERIALIZATION_SCHEMA_VERSION",
    "SUPPORTED_MEDIA_ASSEMBLY_SCHEMA_VERSION",
    "TOP_LEVEL_KEYS",
    "VIDEO_KEYS",
    "validate_episode_media_encode_manifest",
]
