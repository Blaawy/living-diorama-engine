"""Episode Media Assembly Manifest format V1.

An episode media assembly manifest says what a Phase 33 assembly actually produced: which
documents it bound, on what integer clock, and -- one record per physical presentation
frame -- exactly which bytes landed at which position. The document shape is exact at
every level this module governs: a missing key means the manifest is incomplete, an extra
key means it was written by something this contract does not describe, and both are
refused rather than repaired.

This module imports only the standard library and the ``living_diorama`` validation
vocabulary. It never touches the filesystem and never imports a Blender or synthesis
module.
"""

from typing import Final, cast

from living_diorama.media_assembly.media_assembly_spec import (
    MEDIA_ASSEMBLY_MANIFEST_FORMAT,
    MEDIA_ASSEMBLY_MANIFEST_SCHEMA_VERSION,
    presentation_frame_relative_path,
)
from living_diorama.persistence.schema.state_hash import require_hash_hex
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_text,
)

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
"""The JSON value shape this contract works in.

Declared here rather than imported from an upstream layer for the same reason Phase 24,
Phase 25, Phase 26, Phase 27 and Phase 31 each declare their own: a shared alias is not
worth a hole in a boundary.
"""

TOP_LEVEL_KEYS: Final = frozenset(
    {"audio", "clock", "completeness", "format", "frames", "schema_version", "source"}
)
"""Exactly the top-level keys an episode media assembly manifest carries.

Deliberately no ``policy``: this is a filesystem execution, not a plan, exactly the shape
a Phase 31 composition manifest and a Phase 29 voice manifest carry.
"""

SOURCE_KEYS: Final = frozenset(
    {
        "audio_composition_manifest_sha256",
        "audio_composition_schema_version",
        "delivery_plan_sha256",
        "episode",
        "mode",
        "motion_time_sha256",
        "presentation_plan_sha256",
        "presentation_schema_version",
        "previous_episode",
        "render_manifest_sha256",
        "render_manifest_schema_version",
        "shot_plan_sha256",
    }
)
"""Exactly the keys binding a manifest to the three primaries and two witnesses it read.

Every one of these twelve is a fact the manifest's own self-contained audit can re-verify
from the published directory alone: the three primary digests and their schema versions
are re-hashed from the copied documents beside this one; the two witness digests are
re-hashed from ``provenance/`` and cross-proved against the copied primaries that bind
them; ``episode``, ``mode`` and ``previous_episode`` are compared against all three
primaries' own source blocks; and ``motion_time_sha256`` is the one deliberate
restatement, carried by both the render manifest and the presentation plan.
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
"""Exactly the keys the restated, gate-verified integer clock block carries.

``witness_frame`` is here so the frame-193 exclusion proof is verifiable from the
published manifest alone, forever -- without it an auditor would have to re-open the
copied render manifest just to know which semantic frame must never appear.
"""

FRAME_KEYS: Final = frozenset({"bytes", "file", "presentation_frame", "semantic_frame", "sha256"})
"""Exactly the keys one realized presentation frame carries.

Deliberately no ``segment_id``, no ``dwell_frames``, no ``source_file``, no ``shot_id``, no
``camera_anchor_id``, no ``image_sha256``, no window or unit identity, no audio offset, no
caption reference, no timestamp -- and no link count, because ``st_nlink`` is a filesystem
property measured at audit time, never a document claim that could be forged.

``semantic_frame`` is a recorded result, never an authority: the self-contained audit
derives the expected semantic frame from the bound Phase 27 plan and requires this field
to agree with it, but never lets this field choose which Phase 23 record a frame must
match.
"""

AUDIO_KEYS: Final = frozenset(
    {"audio_samples", "bytes", "channels", "file", "sample_rate_hz", "sha256"}
)
"""Exactly the keys the carried track's own artifact block carries.

Byte-for-byte Phase 31's own ``AUDIO_RESULT_FIELDS`` plus ``file``: the block is a carried
copy of Phase 31's own measurement of an artifact this phase never re-measures, so the
binding check is a straight field-for-field equality with no translation seam.
"""

COMPLETENESS_KEYS: Final = frozenset(
    {
        "complete",
        "presentation_frames_assembled",
        "presentation_frames_expected",
        "unique_semantic_frames_used",
    }
)
"""Exactly the keys the accounting block carries.

The aggregate verdict, stated in a way a truncated assembly cannot fake: every count is
measured from the records present. ``unique_semantic_frames_used`` is this layer's
structural analogue of Phase 31's ``silence_samples_total`` -- an aggregate a
frame-dropping assembly cannot fake.
"""

_EPISODE_AUDIO_FILE: Final = "audio/episode_audio.wav"


def _require_document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    for key in value:
        if type(key) is not str:
            raise TypeError(f"{description} keys must be str, got {type(key).__name__}")
    return cast(dict[str, JsonValue], value)


def _require_sequence(value: object, description: str) -> list[JsonValue]:
    if type(value) is not list:
        raise TypeError(f"{description} must be a list, got {type(value).__name__}")
    return cast(list[JsonValue], value)


def _validate_source(source: dict[str, JsonValue], description: str) -> None:
    """Validate the source block's own shape, exactly.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If any digest is not 64 lowercase hex characters.
    """
    require_exact_keys(source, SOURCE_KEYS, description)
    for key in (
        "render_manifest_sha256",
        "presentation_plan_sha256",
        "audio_composition_manifest_sha256",
        "delivery_plan_sha256",
        "shot_plan_sha256",
        "motion_time_sha256",
    ):
        require_hash_hex(source.get(key), f"{description} {key}")
    for key in (
        "render_manifest_schema_version",
        "presentation_schema_version",
        "audio_composition_schema_version",
        "episode",
    ):
        require_exact_int(source.get(key), f"{description} {key}")
    require_text(source.get("mode"), f"{description} mode")
    previous_episode = source.get("previous_episode")
    if previous_episode is not None:
        require_exact_int(previous_episode, f"{description} previous_episode")


def _validate_clock(clock: dict[str, JsonValue], description: str) -> dict[str, int]:
    """Validate the clock block and its integer closure law, returning the resolved values.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If the clock does not close: the sample rate and fps do not cross
            exactly, the derived sample count disagrees, or the semantic/witness frames
            are not consistent.
    """
    require_exact_keys(clock, CLOCK_KEYS, description)
    resolved: dict[str, int] = {
        key: require_exact_int(clock.get(key), f"{description} {key}") for key in CLOCK_KEYS
    }

    fps = resolved["fps"]
    sample_rate = resolved["audio_sample_rate_hz"]
    if fps < 1:
        raise ValueError(f"{description} fps must be >= 1, got {fps}")
    if sample_rate < 1:
        raise ValueError(f"{description} audio_sample_rate_hz must be >= 1, got {sample_rate}")
    if sample_rate % fps != 0:
        raise ValueError(
            f"{description} audio_sample_rate_hz {sample_rate} is not evenly divisible by fps "
            f"{fps}; the audio and presentation clocks do not cross exactly, and this policy "
            "refuses rather than approximate"
        )
    expected_spf = sample_rate // fps
    if resolved["samples_per_presentation_frame"] != expected_spf:
        raise ValueError(
            f"{description} samples_per_presentation_frame is "
            f"{resolved['samples_per_presentation_frame']}, but {sample_rate} // {fps} is "
            f"{expected_spf}"
        )

    presentation_frames_total = resolved["presentation_frames_total"]
    if presentation_frames_total < 1:
        raise ValueError(
            f"{description} presentation_frames_total must be >= 1, got {presentation_frames_total}"
        )
    expected_total = presentation_frames_total * expected_spf
    if resolved["audio_samples_total"] != expected_total:
        raise ValueError(
            f"{description} audio_samples_total is {resolved['audio_samples_total']}, but "
            f"{presentation_frames_total} frames at {expected_spf} samples per frame is "
            f"{expected_total}"
        )

    semantic_first = resolved["semantic_first_frame"]
    semantic_final = resolved["semantic_final_frame"]
    if semantic_first < 1:
        raise ValueError(f"{description} semantic_first_frame must be >= 1, got {semantic_first}")
    if semantic_final < semantic_first:
        raise ValueError(
            f"{description} semantic_final_frame {semantic_final} is before "
            f"semantic_first_frame {semantic_first}"
        )
    if resolved["witness_frame"] != semantic_final + 1:
        raise ValueError(
            f"{description} witness_frame must equal semantic_final_frame + 1; got "
            f"{resolved['witness_frame']} for semantic_final_frame {semantic_final}"
        )
    return resolved


def _validate_frame_record(
    value: object, position: int, clock: dict[str, int], description: str
) -> dict[str, JsonValue]:
    """Validate one frame record's own shape and its positional/range laws.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If the record's position, semantic-frame range, witness exclusion, or
            file path does not hold.
    """
    label = f"{description}[{position}]"
    record = _require_document(value, label)
    require_exact_keys(record, FRAME_KEYS, label)

    presentation_frame = require_exact_int(
        record.get("presentation_frame"), f"{label} presentation_frame"
    )
    if presentation_frame != position + 1:
        raise ValueError(
            f"{label} presentation_frame is {presentation_frame}, but its position in the "
            f"array requires {position + 1}; frames are positional and gap-free"
        )

    semantic_frame = require_exact_int(record.get("semantic_frame"), f"{label} semantic_frame")
    if not (clock["semantic_first_frame"] <= semantic_frame <= clock["semantic_final_frame"]):
        raise ValueError(
            f"{label} semantic_frame {semantic_frame} is outside "
            f"[{clock['semantic_first_frame']}, {clock['semantic_final_frame']}]"
        )
    if semantic_frame == clock["witness_frame"]:
        raise ValueError(
            f"{label} semantic_frame equals the witness frame {clock['witness_frame']}; the "
            "witness frame is never presented"
        )

    expected_file = presentation_frame_relative_path(presentation_frame)
    file_value = require_text(record.get("file"), f"{label} file")
    if file_value != expected_file:
        raise ValueError(f"{label} file is {file_value!r}, expected {expected_file!r}")

    byte_length = require_exact_int(record.get("bytes"), f"{label} bytes")
    if byte_length < 1:
        raise ValueError(f"{label} bytes must be >= 1, got {byte_length}")
    require_hash_hex(record.get("sha256"), f"{label} sha256")

    return record


def _validate_audio(value: object, description: str) -> dict[str, JsonValue]:
    """Validate the carried audio block's own shape.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If ``file`` is not the one deterministic carried-track path.
    """
    block = _require_document(value, description)
    require_exact_keys(block, AUDIO_KEYS, description)

    file_value = require_text(block.get("file"), f"{description} file")
    if file_value != _EPISODE_AUDIO_FILE:
        raise ValueError(f"{description} file is {file_value!r}, expected {_EPISODE_AUDIO_FILE!r}")

    byte_length = require_exact_int(block.get("bytes"), f"{description} bytes")
    if byte_length < 1:
        raise ValueError(f"{description} bytes must be >= 1, got {byte_length}")
    require_hash_hex(block.get("sha256"), f"{description} sha256")
    require_exact_int(block.get("audio_samples"), f"{description} audio_samples")
    require_exact_int(block.get("sample_rate_hz"), f"{description} sample_rate_hz")
    require_exact_int(block.get("channels"), f"{description} channels")

    return block


def _validate_completeness(
    value: object,
    frames: list[JsonValue],
    clock: dict[str, int],
    description: str,
) -> dict[str, JsonValue]:
    """Validate the completeness block, measuring every count from the records present.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If any measured aggregate disagrees with the frame records present.
    """
    block = _require_document(value, description)
    require_exact_keys(block, COMPLETENESS_KEYS, description)

    expected = clock["presentation_frames_total"]
    expected_field = require_exact_int(
        block.get("presentation_frames_expected"), f"{description} presentation_frames_expected"
    )
    if expected_field != expected:
        raise ValueError(
            f"{description} presentation_frames_expected is {expected_field}, but the clock's "
            f"own presentation_frames_total is {expected}"
        )

    assembled = require_exact_int(
        block.get("presentation_frames_assembled"), f"{description} presentation_frames_assembled"
    )
    if assembled != len(frames):
        raise ValueError(
            f"{description} presentation_frames_assembled is {assembled}, but {len(frames)} "
            "frame records are present; this count is measured, never asserted"
        )

    measured_unique = len({cast(dict[str, JsonValue], frame)["semantic_frame"] for frame in frames})
    unique = require_exact_int(
        block.get("unique_semantic_frames_used"), f"{description} unique_semantic_frames_used"
    )
    if unique != measured_unique:
        raise ValueError(
            f"{description} unique_semantic_frames_used is {unique}, but {measured_unique} "
            "distinct semantic frames appear in the records present"
        )

    complete = block.get("complete")
    if type(complete) is not bool:
        raise TypeError(f"{description} complete must be a bool, got {type(complete).__name__}")
    if complete != (assembled == expected):
        raise ValueError(
            f"{description} complete is {complete}, but {assembled} of {expected} expected "
            "frames are present"
        )

    return block


def validate_episode_media_assembly_manifest(value: object) -> dict[str, JsonValue]:
    """Validate one episode media assembly manifest, exactly.

    A manifest that validates says something strong: every source digest is well-formed,
    the integer clock closes on itself, every frame record sits at its own position with a
    semantic frame inside the proven range and never the witness frame, the carried audio
    block is well-formed, and the completeness block's every count is measured from the
    records present rather than asserted beside them.

    Args:
        value: The parsed manifest document.

    Returns:
        The same document, once every rule holds.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If any rule of the contract is broken.
    """
    manifest = _require_document(value, "episode media assembly manifest")
    require_exact_keys(manifest, TOP_LEVEL_KEYS, "episode media assembly manifest")

    declared_format = require_text(manifest.get("format"), "episode media assembly manifest format")
    if declared_format != MEDIA_ASSEMBLY_MANIFEST_FORMAT:
        raise ValueError(
            f"episode media assembly manifest declares format {declared_format!r}, expected "
            f"{MEDIA_ASSEMBLY_MANIFEST_FORMAT!r}"
        )
    version = require_exact_int(
        manifest.get("schema_version"), "episode media assembly manifest schema_version"
    )
    if version != MEDIA_ASSEMBLY_MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"episode media assembly manifest declares schema version {version}; this build "
            f"reads version {MEDIA_ASSEMBLY_MANIFEST_SCHEMA_VERSION} only"
        )

    source = _require_document(manifest.get("source"), "episode media assembly manifest source")
    _validate_source(source, "episode media assembly manifest source")

    clock = _require_document(manifest.get("clock"), "episode media assembly manifest clock")
    resolved_clock = _validate_clock(clock, "episode media assembly manifest clock")

    frames = _require_sequence(manifest.get("frames"), "episode media assembly manifest frames")
    if len(frames) != resolved_clock["presentation_frames_total"]:
        raise ValueError(
            f"episode media assembly manifest carries {len(frames)} frame records, but the "
            f"clock's presentation_frames_total is {resolved_clock['presentation_frames_total']}"
        )
    for position, frame in enumerate(frames):
        _validate_frame_record(
            frame, position, resolved_clock, "episode media assembly manifest frames"
        )

    _validate_audio(manifest.get("audio"), "episode media assembly manifest audio")

    _validate_completeness(
        manifest.get("completeness"),
        frames,
        resolved_clock,
        "episode media assembly manifest completeness",
    )

    return manifest


__all__ = [
    "AUDIO_KEYS",
    "CLOCK_KEYS",
    "COMPLETENESS_KEYS",
    "FRAME_KEYS",
    "JsonValue",
    "SOURCE_KEYS",
    "TOP_LEVEL_KEYS",
    "validate_episode_media_assembly_manifest",
]
