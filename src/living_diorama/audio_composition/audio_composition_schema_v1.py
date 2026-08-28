"""Episode Audio Composition Manifest format V1: what a completed composition proves.

A composition manifest is the document that proves what a Phase 31 execution
actually produced: the episode's one audio artifact -- its byte length, its
digest, its recomputed sample count -- and, per placed span, exactly what
occupies that interval. It restates the bound Phase 30 audio track plan's own
positional identity per span -- never a placement claim of its own -- and
adds exactly what only a finished composition knows: an artifact and a
per-span digest.

The document shape is exact at every level this module governs. A key that
is missing means the manifest is incomplete; a key that is extra means it
was written by something this contract does not describe. Both are refused,
never repaired.

This validator is deliberately self-contained: it proves everything the
manifest can prove about itself, including that every span's own recorded
geometry is contained and non-overlapping, and that its own accounting
closes on the records present. It cannot prove that the recorded artifact
facts are true of the actual file on disk, or that the spans are true of an
actual bound plan and witness: those are facts about other objects entirely,
and standalone validity never claims to prove a fact about something it was
not given. Whether the manifest's claims are true *of* the file it names is
proven by
:func:`living_diorama.audio_composition.audio_composition_audit.audit_audio_composition_directory`,
which opens the file. Whether they are true *of* the bound plan and witness
is proven by
:func:`living_diorama.audio_composition.audio_composition_binding.require_composition_matches_plan_and_witness`.
"""

from typing import Final, cast

from living_diorama.audio_composition.audio_composition_spec import (
    AUDIO_COMPOSITION_MANIFEST_FORMAT,
    AUDIO_COMPOSITION_MANIFEST_SCHEMA_VERSION,
    MAX_EPISODE_AUDIO_SAMPLES,
    episode_audio_relative_path,
)
from living_diorama.audio_track.audio_track_spec import SPEECH_ID_FORM
from living_diorama.narration.narration_schema_v1 import MODE_BASELINE, PLAN_MODES
from living_diorama.persistence.schema.state_hash import require_hash_hex
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_flag,
    require_identifier,
    require_text,
)
from living_diorama.voice.voice_spec import VOICE_UNIT_ID_FORM
from living_diorama.voice_execution.speech_audio import PCM_BYTES_PER_SAMPLE, WAV_HEADER_BYTES

SUPPORTED_VOICE_MANIFEST_SCHEMA_VERSION: Final = 1
SUPPORTED_PRESENTATION_SCHEMA_VERSION: Final = 1
"""The upstream contract versions this build speaks."""

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
"""The JSON value shape this contract works in.

Declared here rather than imported from an upstream layer for the same
reason every locked phase declares its own: a shared alias is not worth a
hole in a boundary.
"""

TOP_LEVEL_KEYS: Final = frozenset(
    {"audio", "completeness", "format", "schema_version", "source", "spans"}
)
"""Exactly the top-level keys an episode audio composition manifest carries.

Deliberately no ``policy``: this is a filesystem execution, not a plan, and
carries no reviewed policy identifier -- the exact shape a voice manifest
carries too.
"""

SOURCE_KEYS: Final = frozenset(
    {
        "audio_track_plan_sha256",
        "episode",
        "mode",
        "presentation_plan_sha256",
        "presentation_schema_version",
        "previous_episode",
        "voice_manifest_sha256",
        "voice_manifest_schema_version",
    }
)
"""Exactly the keys binding a manifest to the plan it composed.

Phase 30's own seven source keys, restated, plus ``audio_track_plan_sha256``
itself -- the manifest binds everything the plan bound, plus the plan's own
digest, exactly as a voice manifest binds everything its plan bound plus
``voice_plan_sha256``.
"""

AUDIO_KEYS: Final = frozenset(
    {"audio_samples", "bytes", "channels", "file", "sample_rate_hz", "sha256"}
)
"""Exactly the keys the composed track's own artifact block carries."""

SPAN_KEYS: Final = frozenset(
    {"pcm_sha256", "speech_id", "speech_samples", "start_sample", "voice_unit_id"}
)
"""Exactly the keys one placed speech-span record carries.

Restated from the bound plan's own speech record: ``speech_id``,
``voice_unit_id``, ``start_sample`` and ``speech_samples``, plus the one new
measured fact this layer adds, ``pcm_sha256``. Deliberately no ``unit_id``,
``realization_id`` or ``window_id``: those identities are proven by position
against the bound plan, never restated a second time here.
"""

COMPLETENESS_KEYS: Final = frozenset(
    {"complete", "silence_samples_total", "speech_spans_composed", "speech_spans_expected"}
)
"""Exactly the keys the accounting block carries.

The aggregate verdict, stated in a way a truncated composition cannot fake:
every count is measured from the records present, including silence, which
is never a record of its own -- only the structural complement of the
speech that is.
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


def _validate_audio(value: object) -> dict[str, JsonValue]:
    """Verify the composed track's own artifact block."""
    description = "audio composition manifest audio"
    audio = _require_document(value, description)
    require_exact_keys(audio, AUDIO_KEYS, description)

    file_name = require_text(audio.get("file"), f"{description} file")
    expected_file = episode_audio_relative_path()
    if file_name != expected_file:
        raise ValueError(
            f"{description} file is {file_name!r}; the composed track lands at the positional, "
            f"deterministic {expected_file!r}"
        )

    sample_rate_hz = require_exact_int(audio.get("sample_rate_hz"), f"{description} sample_rate_hz")
    if sample_rate_hz < 1:
        raise ValueError(f"{description} sample_rate_hz must be >= 1, got {sample_rate_hz}")
    channels = require_exact_int(audio.get("channels"), f"{description} channels")
    if channels < 1:
        raise ValueError(f"{description} channels must be >= 1, got {channels}")

    audio_samples = require_exact_int(audio.get("audio_samples"), f"{description} audio_samples")
    if not 1 <= audio_samples <= MAX_EPISODE_AUDIO_SAMPLES:
        raise ValueError(
            f"{description} audio_samples must be within [1, {MAX_EPISODE_AUDIO_SAMPLES}], got "
            f"{audio_samples}"
        )

    size = require_exact_int(audio.get("bytes"), f"{description} bytes")
    expected_bytes = WAV_HEADER_BYTES + audio_samples * PCM_BYTES_PER_SAMPLE
    if size != expected_bytes:
        raise ValueError(
            f"{description} bytes is {size}, but {audio_samples} samples at "
            f"{PCM_BYTES_PER_SAMPLE} bytes each plus the {WAV_HEADER_BYTES}-byte header is "
            f"{expected_bytes}; a canonical WAV's length is exact arithmetic over its own "
            "recorded sample count"
        )
    require_hash_hex(audio.get("sha256"), f"{description} sha256")
    return audio


def _validate_span(
    value: object,
    description: str,
    position: int,
    *,
    audio_samples_total: int,
    previous_end: int,
) -> tuple[int, int]:
    """Verify one placed speech-span record, and return ``(start_sample, speech_samples)``."""
    record = _require_document(value, description)
    require_exact_keys(record, SPAN_KEYS, description)

    speech_id = require_identifier(record.get("speech_id"), f"{description} speech_id")
    expected_speech = SPEECH_ID_FORM % position
    if speech_id != expected_speech:
        raise ValueError(
            f"{description} declares speech_id {speech_id!r} but sits at position {position}, "
            f"where the identifier is {expected_speech!r}; a speech-span id is positional, not "
            "a free label"
        )
    voice_unit_id = require_identifier(record.get("voice_unit_id"), f"{description} voice_unit_id")
    expected_voice_unit = VOICE_UNIT_ID_FORM % position
    if voice_unit_id != expected_voice_unit:
        raise ValueError(
            f"{description} names voice unit {voice_unit_id!r} but sits at position {position}, "
            f"where the audited execution's unit is {expected_voice_unit!r}"
        )

    start_sample = require_exact_int(record.get("start_sample"), f"{description} start_sample")
    if start_sample < previous_end:
        raise ValueError(
            f"{description} starts at {start_sample}, before the previous span ends at "
            f"{previous_end}; speech spans never overlap and always follow narration order"
        )
    speech_samples = require_exact_int(
        record.get("speech_samples"), f"{description} speech_samples"
    )
    if speech_samples < 1:
        raise ValueError(f"{description} speech_samples must be >= 1, got {speech_samples}")
    span_end = start_sample + speech_samples
    if span_end > audio_samples_total:
        raise ValueError(
            f"{description} spans [{start_sample}, {span_end}), beyond the composed track's own "
            f"{audio_samples_total} total samples"
        )
    require_hash_hex(record.get("pcm_sha256"), f"{description} pcm_sha256")
    return start_sample, speech_samples


def validate_episode_audio_composition_manifest(value: object) -> dict[str, JsonValue]:
    """Verify a document's Episode Audio Composition Manifest V1 envelope, and return it.

    This validator is deliberately self-contained: it proves everything the
    manifest can prove about itself, and nothing that needs the bound plan,
    the bound witness, or the actual WAV file it names. See the module
    docstring for what it cannot prove and which functions prove those facts
    instead.

    Raises:
        TypeError: If any value has the wrong exact type.
        ValueError: If any key set, vocabulary member, ordering, arithmetic
            or internal agreement is violated.
    """
    document = _require_document(value, "audio composition manifest")
    require_exact_keys(document, TOP_LEVEL_KEYS, "audio composition manifest")

    tag = require_text(document.get("format"), "audio composition manifest format")
    if tag != AUDIO_COMPOSITION_MANIFEST_FORMAT:
        raise ValueError(
            f"audio composition manifest declares format {tag!r}; this build reads "
            f"{AUDIO_COMPOSITION_MANIFEST_FORMAT!r} only"
        )
    version = require_exact_int(
        document.get("schema_version"), "audio composition manifest schema_version"
    )
    if version != AUDIO_COMPOSITION_MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"audio composition manifest declares unsupported schema version {version}; this "
            f"build reads version {AUDIO_COMPOSITION_MANIFEST_SCHEMA_VERSION} only"
        )

    source = _require_document(document.get("source"), "audio composition manifest source")
    require_exact_keys(source, SOURCE_KEYS, "audio composition manifest source")
    mode = _require_member(source.get("mode"), PLAN_MODES, "audio composition manifest source mode")
    episode = require_exact_int(source.get("episode"), "audio composition manifest source episode")

    voice_manifest_version = require_exact_int(
        source.get("voice_manifest_schema_version"),
        "audio composition manifest source voice_manifest_schema_version",
    )
    if voice_manifest_version != SUPPORTED_VOICE_MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"audio composition manifest was composed from voice manifest schema version "
            f"{voice_manifest_version}; this build speaks version "
            f"{SUPPORTED_VOICE_MANIFEST_SCHEMA_VERSION} only"
        )
    presentation_version = require_exact_int(
        source.get("presentation_schema_version"),
        "audio composition manifest source presentation_schema_version",
    )
    if presentation_version != SUPPORTED_PRESENTATION_SCHEMA_VERSION:
        raise ValueError(
            f"audio composition manifest was composed from presentation schema version "
            f"{presentation_version}; this build speaks version "
            f"{SUPPORTED_PRESENTATION_SCHEMA_VERSION} only"
        )
    for field in ("audio_track_plan_sha256", "voice_manifest_sha256", "presentation_plan_sha256"):
        require_hash_hex(source.get(field), f"audio composition manifest source {field}")

    previous = source.get("previous_episode")
    if mode == MODE_BASELINE:
        _require_null(
            previous,
            "audio composition manifest source previous_episode",
            "a baseline composition places one export's speech and follows no episode",
        )
        if episode != 0:
            raise ValueError(
                f"audio composition manifest source declares mode 'baseline' with episode "
                f"{episode}; a baseline is always episode 0"
            )
    else:
        previous_episode = require_exact_int(
            previous, "audio composition manifest source previous_episode"
        )
        if episode != previous_episode + 1:
            raise ValueError(
                f"audio composition manifest source declares episode {episode} following "
                f"{previous_episode}; a transition's episode always directly follows its "
                "previous episode"
            )

    audio = _validate_audio(document.get("audio"))
    audio_samples_total = cast(int, audio["audio_samples"])

    spans = _require_list(document.get("spans"), "audio composition manifest spans")
    if not spans:
        raise ValueError("audio composition manifest spans must not be empty")

    speech_samples_total = 0
    previous_end = 0
    for position, record in enumerate(spans, start=1):
        start_sample, speech_samples = _validate_span(
            record,
            f"audio composition manifest spans[{position - 1}]",
            position,
            audio_samples_total=audio_samples_total,
            previous_end=previous_end,
        )
        previous_end = start_sample + speech_samples
        speech_samples_total += speech_samples

    completeness = _require_document(
        document.get("completeness"), "audio composition manifest completeness"
    )
    require_exact_keys(completeness, COMPLETENESS_KEYS, "audio composition manifest completeness")
    expected = require_exact_int(
        completeness.get("speech_spans_expected"),
        "audio composition manifest completeness speech_spans_expected",
    )
    composed = require_exact_int(
        completeness.get("speech_spans_composed"),
        "audio composition manifest completeness speech_spans_composed",
    )
    if expected != len(spans):
        raise ValueError(
            f"audio composition manifest completeness speech_spans_expected is {expected}, but "
            f"the manifest carries {len(spans)} span records"
        )
    if composed != len(spans):
        raise ValueError(
            f"audio composition manifest completeness speech_spans_composed is {composed}, but "
            f"the manifest carries {len(spans)} span records"
        )
    recorded_silence = require_exact_int(
        completeness.get("silence_samples_total"),
        "audio composition manifest completeness silence_samples_total",
    )
    expected_silence = audio_samples_total - speech_samples_total
    if recorded_silence != expected_silence:
        raise ValueError(
            f"audio composition manifest completeness silence_samples_total is "
            f"{recorded_silence}, but {audio_samples_total} total samples minus "
            f"{speech_samples_total} speech samples is {expected_silence}"
        )
    complete = require_flag(
        completeness.get("complete"), "audio composition manifest completeness complete"
    )
    expected_complete = composed == expected
    if complete != expected_complete:
        raise ValueError(
            f"audio composition manifest completeness complete is {complete}, but "
            f"speech_spans_composed == speech_spans_expected is {expected_complete}; "
            "completeness is measured from the records present, never asserted beside them"
        )

    return document


__all__ = [
    "AUDIO_KEYS",
    "COMPLETENESS_KEYS",
    "SOURCE_KEYS",
    "SPAN_KEYS",
    "SUPPORTED_PRESENTATION_SCHEMA_VERSION",
    "SUPPORTED_VOICE_MANIFEST_SCHEMA_VERSION",
    "TOP_LEVEL_KEYS",
    "JsonValue",
    "validate_episode_audio_composition_manifest",
]
