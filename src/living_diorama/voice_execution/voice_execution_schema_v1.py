"""Episode Voice Manifest format V1: what a completed voice execution proves.

A voice manifest is the document that proves what a Phase 29 execution
actually produced: which unit's speech landed in which file, how many bytes
and samples that file actually holds, and whether every unit fit its Phase 28
capacity. It restates the bound voice plan's own positional identity per unit
-- never a semantic claim about wording -- and adds exactly what only a
finished execution knows: a file, a byte count, a digest and a measured
sample count.

The document shape is exact at every level this module governs. A key that
is missing means the manifest is incomplete; a key that is extra means it
was written by something this contract does not describe. Both are refused,
never repaired.

This validator is deliberately self-contained: it proves everything the
manifest can prove about itself, including that every unit's own recorded
``bytes`` closes against its own recorded ``speech_samples`` by the WAV
header arithmetic, and that every unit's own recorded ``speech_samples`` sits
at or under its own recorded ``capacity_samples`` -- the *standalone* FIT
law. It cannot prove that ``bytes``, ``sha256`` or ``speech_samples`` are
true of the actual WAV file on disk, or that the plan-side fields are true of
an actual bound voice plan: those are facts about other objects entirely
(a file, a second document), and standalone validity never claims to prove a
fact about something it was not given. Whether the manifest's claims are
true *of* the file it names is proven by
:func:`living_diorama.voice_execution.voice_execution_audit.audit_voice_directory`,
which opens the file. Whether they are true *of* the bound plan is proven by
:func:`living_diorama.voice_execution.voice_execution_binding.require_manifest_matches_plan`.
"""

from typing import Final, cast

from living_diorama.language_realization.realization_spec import REALIZATION_ID_FORM
from living_diorama.narration.narration_schema_v1 import MODE_BASELINE, PLAN_MODES, UNIT_ID_FORM
from living_diorama.persistence.schema.state_hash import require_hash_hex
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_flag,
    require_identifier,
    require_text,
)
from living_diorama.presentation.presentation_spec import WINDOW_ID_FORM
from living_diorama.voice.voice_spec import MAX_VOICE_CAPACITY_SAMPLES, VOICE_UNIT_ID_FORM
from living_diorama.voice_execution.speech_audio import PCM_BYTES_PER_SAMPLE, WAV_HEADER_BYTES
from living_diorama.voice_execution.voice_execution_spec import (
    DEVICE_CPU,
    MAX_SPEECH_SAMPLES,
    SPACY_MODEL,
    SPEECH_DIRECTORY,
    VOICE_MANIFEST_FORMAT,
    VOICE_MANIFEST_SCHEMA_VERSION,
    unit_audio_filename,
)

SUPPORTED_PRESENTATION_SCHEMA_VERSION: Final = 1
SUPPORTED_REALIZATION_SCHEMA_VERSION: Final = 1
"""The upstream contract versions this build speaks."""

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
"""The JSON value shape this contract works in.

Declared here rather than imported from an upstream layer for the same
reason every locked phase declares its own: a shared alias is not worth a
hole in a boundary.
"""

TOP_LEVEL_KEYS: Final = frozenset(
    {"completeness", "environment", "format", "schema_version", "source", "voice_units"}
)
"""Exactly the top-level keys an episode voice manifest carries."""

SOURCE_KEYS: Final = frozenset(
    {
        "episode",
        "mode",
        "previous_episode",
        "presentation_plan_sha256",
        "presentation_schema_version",
        "realization_plan_sha256",
        "realization_schema_version",
        "voice_plan_sha256",
    }
)
"""Exactly the keys binding a manifest to the plan it executes.

Every one of the voice plan's own seven source keys, restated, plus
``voice_plan_sha256`` itself -- the manifest binds everything the plan bound,
plus the plan itself, exactly as a render manifest binds everything its plan
bound plus the plan's own digest.
"""

ENVIRONMENT_KEYS: Final = frozenset(
    {
        "device",
        "python_version",
        "torch_version",
        "spacy_version",
        "spacy_model",
        "spacy_model_version",
        "num2words_version",
    }
)
"""Exactly the keys the execution environment block carries.

``device`` and ``spacy_model`` are exact-value laws, checked below. The
remaining five are executor-reported attestation: the manifest records this
metadata, and no check anywhere in this phase claims to independently prove
which Python, Torch or spaCy environment actually produced a given WAV.
"""

VOICE_UNIT_KEYS: Final = frozenset(
    {
        "voice_unit_id",
        "unit_id",
        "realization_id",
        "window_id",
        "capacity_samples",
        "file",
        "bytes",
        "sha256",
        "speech_samples",
    }
)
"""Exactly the keys a voice-unit result record carries.

The bound plan's own five unit keys, restated, plus the four measured facts
only a finished execution knows: ``file``, ``bytes``, ``sha256`` and
``speech_samples``. Deliberately no realized text, no text hash, no fit
margin and no duration float -- a unit result names what it produced and
where, and nothing about how long it takes to say.
"""

COMPLETENESS_KEYS: Final = frozenset(
    {"voice_units_expected", "voice_units_synthesized", "speech_samples_total", "complete"}
)
"""Exactly the keys the completeness block carries.

The aggregate verdict, stated in a way a truncated execution cannot fake:
every count is measured from the records present, and there is deliberately
no separate aggregate fit flag -- a manifest is never built for an episode
holding an unfit unit, so ``complete`` alone is the whole verdict.
"""


def _require_document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    for key in value:
        if type(key) is not str:
            raise TypeError(f"{description} keys must be str, got {type(key).__name__}")
    return cast(dict[str, JsonValue], value)


def _require_list(value: object, description: str) -> list[JsonValue]:
    if type(value) is not list:
        raise TypeError(f"{description} must be a list, got {type(value).__name__}")
    return cast(list[JsonValue], value)


def _require_member(value: object, allowed: tuple[str, ...], description: str) -> str:
    text = require_text(value, description)
    if text not in allowed:
        raise ValueError(f"{description} is {text!r}; expected one of {list(allowed)}")
    return text


def _require_null(value: object, description: str, because: str) -> None:
    if value is not None:
        raise ValueError(f"{description} is {value!r}, but {because}")


def _validate_environment(value: object) -> dict[str, JsonValue]:
    """Verify the environment block carries exactly its seven keys and two laws.

    The manifest records this metadata; it never independently proves it. See
    the module docstring and ``ENVIRONMENT_KEYS``.
    """
    description = "voice manifest environment"
    environment = _require_document(value, description)
    require_exact_keys(environment, ENVIRONMENT_KEYS, description)
    for key in sorted(ENVIRONMENT_KEYS):
        require_text(environment.get(key), f"{description} {key}")
    device = cast(str, environment["device"])
    if device != DEVICE_CPU:
        raise ValueError(
            f"{description} device is {device!r}; this build executes on {DEVICE_CPU!r} only"
        )
    spacy_model = cast(str, environment["spacy_model"])
    if spacy_model != SPACY_MODEL:
        raise ValueError(
            f"{description} spacy_model is {spacy_model!r}; this build's G2P policy is pinned "
            f"to {SPACY_MODEL!r} only"
        )
    return environment


def _validate_voice_unit(value: object, description: str, position: int) -> int:
    """Verify one voice-unit result record, and return its ``speech_samples``."""
    record = _require_document(value, description)
    require_exact_keys(record, VOICE_UNIT_KEYS, description)

    voice_unit_id = require_identifier(record.get("voice_unit_id"), f"{description} voice_unit_id")
    expected_voice_unit = VOICE_UNIT_ID_FORM % position
    if voice_unit_id != expected_voice_unit:
        raise ValueError(
            f"{description} declares voice_unit_id {voice_unit_id!r} but sits at position "
            f"{position}, where the identifier is {expected_voice_unit!r}; a voice-unit id is "
            "positional, not a free label"
        )
    unit_id = require_identifier(record.get("unit_id"), f"{description} unit_id")
    expected_unit = UNIT_ID_FORM % position
    if unit_id != expected_unit:
        raise ValueError(
            f"{description} speaks unit {unit_id!r} but sits at position {position}, where the "
            f"narration plan's unit is {expected_unit!r}; a voice-unit result follows the "
            "narration plan's own order"
        )
    realization_id = require_identifier(
        record.get("realization_id"), f"{description} realization_id"
    )
    expected_realization = REALIZATION_ID_FORM % position
    if realization_id != expected_realization:
        raise ValueError(
            f"{description} names realization {realization_id!r} but sits at position "
            f"{position}, where the realization plan's record is {expected_realization!r}"
        )
    window_id = require_identifier(record.get("window_id"), f"{description} window_id")
    expected_window = WINDOW_ID_FORM % position
    if window_id != expected_window:
        raise ValueError(
            f"{description} names window {window_id!r} but sits at position {position}, where "
            f"the presentation plan's window is {expected_window!r}"
        )

    capacity = require_exact_int(record.get("capacity_samples"), f"{description} capacity_samples")
    if not 1 <= capacity <= MAX_VOICE_CAPACITY_SAMPLES:
        raise ValueError(
            f"{description} capacity_samples must be within [1, {MAX_VOICE_CAPACITY_SAMPLES}], "
            f"got {capacity}"
        )

    file_name = require_text(record.get("file"), f"{description} file")
    expected_file = f"{SPEECH_DIRECTORY}/{unit_audio_filename(position)}"
    if file_name != expected_file:
        raise ValueError(
            f"{description} file is {file_name!r}; a unit's speech lands at the positional, "
            f"deterministic {expected_file!r}"
        )

    size = require_exact_int(record.get("bytes"), f"{description} bytes")
    minimum_bytes = WAV_HEADER_BYTES + PCM_BYTES_PER_SAMPLE
    if size < minimum_bytes:
        raise ValueError(
            f"{description} bytes is {size}, but a canonical WAV carrying at least one sample "
            f"is at least {minimum_bytes} bytes"
        )
    require_hash_hex(record.get("sha256"), f"{description} sha256")

    speech_samples = require_exact_int(
        record.get("speech_samples"), f"{description} speech_samples"
    )
    if not 1 <= speech_samples <= MAX_SPEECH_SAMPLES:
        raise ValueError(
            f"{description} speech_samples must be within [1, {MAX_SPEECH_SAMPLES}], got "
            f"{speech_samples}"
        )
    if speech_samples > capacity:
        raise ValueError(
            f"{description} speech_samples is {speech_samples}, but its own capacity_samples is "
            f"{capacity}; a voice manifest is never written for a unit whose recorded speech "
            "overflows its own recorded capacity"
        )

    expected_bytes = WAV_HEADER_BYTES + speech_samples * PCM_BYTES_PER_SAMPLE
    if size != expected_bytes:
        raise ValueError(
            f"{description} bytes is {size}, but {speech_samples} samples at "
            f"{PCM_BYTES_PER_SAMPLE} bytes each plus the {WAV_HEADER_BYTES}-byte header is "
            f"{expected_bytes}; a canonical WAV's length is exact arithmetic over its own "
            "recorded sample count"
        )
    return speech_samples


def validate_episode_voice_manifest(value: object) -> dict[str, JsonValue]:
    """Verify a document's Episode Voice Manifest V1 envelope, and return it.

    This validator is deliberately self-contained: it proves everything the
    manifest can prove about itself, and nothing that needs the bound voice
    plan or the actual WAV files it names. See the module docstring for what
    it cannot prove and which functions prove those facts instead.

    Raises:
        TypeError: If any value has the wrong exact type.
        ValueError: If any key set, vocabulary member, ordering, arithmetic
            or internal agreement is violated.
    """
    document = _require_document(value, "voice manifest")
    require_exact_keys(document, TOP_LEVEL_KEYS, "voice manifest")

    tag = require_text(document.get("format"), "voice manifest format")
    if tag != VOICE_MANIFEST_FORMAT:
        raise ValueError(
            f"voice manifest declares format {tag!r}; this build reads "
            f"{VOICE_MANIFEST_FORMAT!r} only"
        )
    version = require_exact_int(document.get("schema_version"), "voice manifest schema_version")
    if version != VOICE_MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"voice manifest declares unsupported schema version {version}; this build reads "
            f"version {VOICE_MANIFEST_SCHEMA_VERSION} only"
        )

    source = _require_document(document.get("source"), "voice manifest source")
    require_exact_keys(source, SOURCE_KEYS, "voice manifest source")
    mode = _require_member(source.get("mode"), PLAN_MODES, "voice manifest source mode")
    episode = require_exact_int(source.get("episode"), "voice manifest source episode")
    presentation_version = require_exact_int(
        source.get("presentation_schema_version"),
        "voice manifest source presentation_schema_version",
    )
    if presentation_version != SUPPORTED_PRESENTATION_SCHEMA_VERSION:
        raise ValueError(
            f"voice manifest was executed from presentation schema version "
            f"{presentation_version}; this build speaks version "
            f"{SUPPORTED_PRESENTATION_SCHEMA_VERSION} only"
        )
    realization_version = require_exact_int(
        source.get("realization_schema_version"), "voice manifest source realization_schema_version"
    )
    if realization_version != SUPPORTED_REALIZATION_SCHEMA_VERSION:
        raise ValueError(
            f"voice manifest was executed from realization schema version "
            f"{realization_version}; this build speaks version "
            f"{SUPPORTED_REALIZATION_SCHEMA_VERSION} only"
        )
    for field in ("presentation_plan_sha256", "realization_plan_sha256", "voice_plan_sha256"):
        require_hash_hex(source.get(field), f"voice manifest source {field}")

    previous = source.get("previous_episode")
    if mode == MODE_BASELINE:
        _require_null(
            previous,
            "voice manifest source previous_episode",
            "a baseline execution speaks one export's narration and follows no episode",
        )
        if episode != 0:
            raise ValueError(
                f"voice manifest source declares mode 'baseline' with episode {episode}; a "
                "baseline is always episode 0"
            )
    else:
        previous_episode = require_exact_int(previous, "voice manifest source previous_episode")
        if episode != previous_episode + 1:
            raise ValueError(
                f"voice manifest source declares episode {episode} following "
                f"{previous_episode}; a transition's episode always directly follows its "
                "previous episode"
            )

    _validate_environment(document.get("environment"))

    voice_units = _require_list(document.get("voice_units"), "voice manifest voice_units")
    if not voice_units:
        raise ValueError("voice manifest voice_units must not be empty")

    speech_samples_total = 0
    for position, unit in enumerate(voice_units, start=1):
        speech_samples_total += _validate_voice_unit(
            unit, f"voice manifest voice_units[{position - 1}]", position
        )

    completeness = _require_document(document.get("completeness"), "voice manifest completeness")
    require_exact_keys(completeness, COMPLETENESS_KEYS, "voice manifest completeness")
    expected = require_exact_int(
        completeness.get("voice_units_expected"), "voice manifest completeness voice_units_expected"
    )
    synthesized = require_exact_int(
        completeness.get("voice_units_synthesized"),
        "voice manifest completeness voice_units_synthesized",
    )
    if expected != len(voice_units):
        raise ValueError(
            f"voice manifest completeness voice_units_expected is {expected}, but the manifest "
            f"carries {len(voice_units)} voice-unit records"
        )
    if synthesized != len(voice_units):
        raise ValueError(
            f"voice manifest completeness voice_units_synthesized is {synthesized}, but the "
            f"manifest carries {len(voice_units)} voice-unit records"
        )
    recorded_total = require_exact_int(
        completeness.get("speech_samples_total"), "voice manifest completeness speech_samples_total"
    )
    if recorded_total != speech_samples_total:
        raise ValueError(
            f"voice manifest completeness speech_samples_total is {recorded_total}, but the "
            f"records present sum to {speech_samples_total}"
        )
    complete = require_flag(completeness.get("complete"), "voice manifest completeness complete")
    expected_complete = synthesized == expected
    if complete != expected_complete:
        raise ValueError(
            f"voice manifest completeness complete is {complete}, but "
            f"voice_units_synthesized == voice_units_expected is {expected_complete}; "
            "completeness is measured from the records present, never asserted beside them"
        )

    return document
