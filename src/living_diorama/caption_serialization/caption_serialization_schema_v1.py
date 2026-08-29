"""Episode Caption Serialization Manifest format V1: two sealed sidecars, proven.

A caption serialization manifest says, for one locked Episode Caption Plan, which
two sidecar artifacts were derived from it -- their exact filenames, byte lengths
and digests -- under which timestamp policy, restating the plan's own clock and
its frame-authoritative accounting byte-for-byte. It asserts nothing about
display, nothing about audio, and nothing a millisecond ledger would add: the
only wall-clock representation of the plan is the sidecar bytes themselves, and
those are re-derived, never summarized.

The document shape is exact at every level this module governs. A key that is
missing means the manifest is incomplete; a key that is extra means it was
written by something this contract does not describe. Both are refused, never
repaired.

This validator is deliberately self-contained: it proves everything the manifest
can prove about itself, including that its accounting closes on its own clock
and that its sidecar records name exactly the two files the frozen suffix law
derives for its own episode identity. It cannot prove a recorded digest is true
of an actual file, or that the restated values are true of an actual caption
plan: those facts are proven by the self-contained audit,
``audit_caption_serialization_directory``, which re-reads every byte
beside the manifest.
"""

from typing import Final, cast

from living_diorama.caption.caption_spec import CAPTION_SCHEMA_VERSION, MAX_CAPTION_FRAME
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
from living_diorama.narration.narration_schema_v1 import MODE_BASELINE, PLAN_MODES
from living_diorama.persistence.schema.state_hash import require_hash_hex
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_text,
)

SUPPORTED_PRESENTATION_SCHEMA_VERSION: Final = 1
SUPPORTED_REALIZATION_SCHEMA_VERSION: Final = 1
"""The upstream contract versions this build speaks, restated per phase law."""

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
"""The JSON value shape this contract works in.

Declared here rather than imported from an upstream layer for the same reason
every locked phase declares its own: a shared alias is not worth a hole in a
boundary.
"""

TOP_LEVEL_KEYS: Final = frozenset(
    {"accounting", "clock", "format", "policy", "schema_version", "sidecars", "source"}
)
"""Exactly the top-level keys an episode caption serialization manifest carries."""

SOURCE_KEYS: Final = frozenset(
    {
        "caption_plan_sha256",
        "caption_schema_version",
        "episode",
        "mode",
        "presentation_plan_sha256",
        "presentation_schema_version",
        "previous_episode",
        "realization_plan_sha256",
        "realization_schema_version",
    }
)
"""Exactly the keys binding a manifest to the plan it serialized.

The Phase 32 plan's own seven source keys, restated, plus the plan's own digest
and schema version -- byte-for-byte the Phase 31 pattern: the manifest binds
everything the plan bound, plus the plan itself.
"""

CLOCK_KEYS: Final = frozenset({"fps", "presentation_frames_total"})
"""Exactly the keys the restated, gate-verified clock block carries."""

ACCOUNTING_KEYS: Final = frozenset(
    {"caption_frames_total", "captions_total", "uncaptioned_frames_total"}
)
"""Exactly the keys the accounting block carries.

The Phase 32 plan's own three, restated byte-for-byte -- FRAME-authoritative,
never milliseconds: a second, millisecond-based truth ledger is exactly what
this phase refuses to create.
"""

SIDECAR_KEYS: Final = frozenset({"srt", "vtt"})
"""Exactly the two records the sidecars block carries."""

SIDECAR_RECORD_KEYS: Final = frozenset({"bytes", "file", "format", "sha256"})
"""Exactly the keys one sidecar record carries.

Deliberately no cue list, no timestamp, no duration and no line count: the
artifact's own bytes are its whole content, identified by length and digest,
and the audit re-derives them from the plan copy rather than reading a summary.
"""


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


def _validate_sidecar_record(
    value: object, description: str, *, expected_file: str, expected_format: str
) -> None:
    """Verify one sidecar record against its frozen filename and format literals."""
    record = _require_document(value, description)
    require_exact_keys(record, SIDECAR_RECORD_KEYS, description)
    byte_length = require_exact_int(record.get("bytes"), f"{description} bytes")
    if byte_length < 1:
        raise ValueError(f"{description} bytes must be >= 1, got {byte_length}")
    file_value = require_text(record.get("file"), f"{description} file")
    if file_value != expected_file:
        raise ValueError(f"{description} file is {file_value!r}, expected {expected_file!r}")
    format_value = require_text(record.get("format"), f"{description} format")
    if format_value != expected_format:
        raise ValueError(f"{description} format is {format_value!r}, expected {expected_format!r}")
    require_hash_hex(record.get("sha256"), f"{description} sha256")


def validate_episode_caption_serialization_manifest(value: object) -> dict[str, JsonValue]:
    """Verify a document's Episode Caption Serialization Manifest V1 envelope.

    This validator is deliberately self-contained: it proves everything the
    manifest can prove about itself, and nothing that needs the plan copy or
    the sidecar files. See the module docstring for what it cannot prove and
    which function proves those facts instead.

    Raises:
        TypeError: If any value has the wrong exact type.
        ValueError: If any key set, vocabulary member, bound or internal
            agreement is violated.
    """
    document = _require_document(value, "caption serialization manifest")
    require_exact_keys(document, TOP_LEVEL_KEYS, "caption serialization manifest")

    tag = require_text(document.get("format"), "caption serialization manifest format")
    if tag != CAPTION_SERIALIZATION_MANIFEST_FORMAT:
        raise ValueError(
            f"caption serialization manifest declares format {tag!r}; this build reads "
            f"{CAPTION_SERIALIZATION_MANIFEST_FORMAT!r} only"
        )
    version = require_exact_int(
        document.get("schema_version"), "caption serialization manifest schema_version"
    )
    if version != CAPTION_SERIALIZATION_SCHEMA_VERSION:
        raise ValueError(
            f"caption serialization manifest declares unsupported schema version {version}; "
            f"this build reads version {CAPTION_SERIALIZATION_SCHEMA_VERSION} only"
        )
    policy = require_text(document.get("policy"), "caption serialization manifest policy")
    if policy != CAPTION_TIMESTAMP_POLICY_V1:
        raise ValueError(
            f"caption serialization manifest declares policy {policy!r}; this build derives "
            f"and validates {CAPTION_TIMESTAMP_POLICY_V1!r} only"
        )

    source = _require_document(document.get("source"), "caption serialization manifest source")
    require_exact_keys(source, SOURCE_KEYS, "caption serialization manifest source")
    mode = _require_member(
        source.get("mode"), PLAN_MODES, "caption serialization manifest source mode"
    )
    episode = require_exact_int(
        source.get("episode"), "caption serialization manifest source episode"
    )
    caption_version = require_exact_int(
        source.get("caption_schema_version"),
        "caption serialization manifest source caption_schema_version",
    )
    if caption_version != CAPTION_SCHEMA_VERSION:
        raise ValueError(
            f"caption serialization manifest was derived from caption schema version "
            f"{caption_version}; this build speaks version {CAPTION_SCHEMA_VERSION} only"
        )
    presentation_version = require_exact_int(
        source.get("presentation_schema_version"),
        "caption serialization manifest source presentation_schema_version",
    )
    if presentation_version != SUPPORTED_PRESENTATION_SCHEMA_VERSION:
        raise ValueError(
            f"caption serialization manifest restates presentation schema version "
            f"{presentation_version}; this build speaks version "
            f"{SUPPORTED_PRESENTATION_SCHEMA_VERSION} only"
        )
    realization_version = require_exact_int(
        source.get("realization_schema_version"),
        "caption serialization manifest source realization_schema_version",
    )
    if realization_version != SUPPORTED_REALIZATION_SCHEMA_VERSION:
        raise ValueError(
            f"caption serialization manifest restates realization schema version "
            f"{realization_version}; this build speaks version "
            f"{SUPPORTED_REALIZATION_SCHEMA_VERSION} only"
        )
    for field in ("caption_plan_sha256", "presentation_plan_sha256", "realization_plan_sha256"):
        require_hash_hex(source.get(field), f"caption serialization manifest source {field}")

    previous = source.get("previous_episode")
    if mode == MODE_BASELINE:
        _require_null(
            previous,
            "caption serialization manifest source previous_episode",
            "a baseline serialization presents one export's captions and follows no episode",
        )
        if episode != 0:
            raise ValueError(
                f"caption serialization manifest source declares mode 'baseline' with episode "
                f"{episode}; a baseline is always episode 0"
            )
        previous_episode: int | None = None
    else:
        previous_episode = require_exact_int(
            previous, "caption serialization manifest source previous_episode"
        )
        if episode != previous_episode + 1:
            raise ValueError(
                f"caption serialization manifest source declares episode {episode} following "
                f"{previous_episode}; a transition's episode always directly follows its "
                "previous episode"
            )

    clock = _require_document(document.get("clock"), "caption serialization manifest clock")
    require_exact_keys(clock, CLOCK_KEYS, "caption serialization manifest clock")
    fps = require_exact_int(clock.get("fps"), "caption serialization manifest clock fps")
    if fps < 1:
        raise ValueError(f"caption serialization manifest clock fps must be >= 1, got {fps}")
    presentation_frames_total = require_exact_int(
        clock.get("presentation_frames_total"),
        "caption serialization manifest clock presentation_frames_total",
    )
    if not 1 <= presentation_frames_total <= MAX_CAPTION_FRAME:
        raise ValueError(
            "caption serialization manifest clock presentation_frames_total must be within "
            f"[1, {MAX_CAPTION_FRAME}], got {presentation_frames_total}"
        )

    accounting = _require_document(
        document.get("accounting"), "caption serialization manifest accounting"
    )
    require_exact_keys(accounting, ACCOUNTING_KEYS, "caption serialization manifest accounting")
    captions_total = require_exact_int(
        accounting.get("captions_total"), "caption serialization manifest accounting captions_total"
    )
    if captions_total < 1:
        raise ValueError(
            f"caption serialization manifest accounting captions_total must be >= 1, got "
            f"{captions_total}"
        )
    caption_frames_total = require_exact_int(
        accounting.get("caption_frames_total"),
        "caption serialization manifest accounting caption_frames_total",
    )
    if not 1 <= caption_frames_total <= presentation_frames_total:
        raise ValueError(
            "caption serialization manifest accounting caption_frames_total must be within "
            f"[1, {presentation_frames_total}], got {caption_frames_total}"
        )
    uncaptioned = require_exact_int(
        accounting.get("uncaptioned_frames_total"),
        "caption serialization manifest accounting uncaptioned_frames_total",
    )
    expected_uncaptioned = presentation_frames_total - caption_frames_total
    if uncaptioned != expected_uncaptioned:
        raise ValueError(
            f"caption serialization manifest accounting uncaptioned_frames_total is "
            f"{uncaptioned}, but {presentation_frames_total} total frames minus "
            f"{caption_frames_total} captioned frames is {expected_uncaptioned}"
        )

    episode_id = caption_serialization_id(
        mode=mode, episode=episode, previous_episode=previous_episode
    )
    sidecars = _require_document(
        document.get("sidecars"), "caption serialization manifest sidecars"
    )
    require_exact_keys(sidecars, SIDECAR_KEYS, "caption serialization manifest sidecars")
    _validate_sidecar_record(
        sidecars.get("srt"),
        "caption serialization manifest sidecars srt",
        expected_file=sidecar_filename(episode_id, SRT_SUFFIX),
        expected_format=SRT_FORMAT_NAME,
    )
    _validate_sidecar_record(
        sidecars.get("vtt"),
        "caption serialization manifest sidecars vtt",
        expected_file=sidecar_filename(episode_id, VTT_SUFFIX),
        expected_format=VTT_FORMAT_NAME,
    )

    return document


__all__ = [
    "ACCOUNTING_KEYS",
    "CLOCK_KEYS",
    "JsonValue",
    "SIDECAR_KEYS",
    "SIDECAR_RECORD_KEYS",
    "SOURCE_KEYS",
    "SUPPORTED_PRESENTATION_SCHEMA_VERSION",
    "SUPPORTED_REALIZATION_SCHEMA_VERSION",
    "TOP_LEVEL_KEYS",
    "validate_episode_caption_serialization_manifest",
]
