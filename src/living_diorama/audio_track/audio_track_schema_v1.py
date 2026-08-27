"""Episode Audio Track Plan format V1: measured speech placed on the sample clock.

An audio track plan says, for a finished voice execution and the
presentation plan its windows come from, exactly where each unit's measured
speech begins on the episode's single audio-sample clock, and therefore
exactly what is silence. It asserts nothing about wording, nothing about
capacity, and nothing about the audio bytes themselves -- those live in the
documents it binds, and stay there.

The document shape is exact at every level this module governs. A key that
is missing means the plan is incomplete; a key that is extra means it was
written by something this contract does not describe. Both are refused,
never repaired.

This validator is deliberately self-contained: it proves everything the plan
can prove about itself, including that every span's onset sits on a
presentation-frame boundary, that spans never overlap, and that every span
fits inside the track's own recomputed total. It cannot prove a span's
``speech_samples`` is true of an actual executed WAV, or that the plan's two
bound documents are true of everything upstream of them -- those facts are
proven by
:func:`living_diorama.audio_track.audio_track_cross_check.validate_episode_audio_track_plan_against_sources`,
which takes the bound sources as arguments and, before that, reuses the
Phase 29 directory audit whole.
"""

from typing import Final, cast

from living_diorama.audio_track.audio_track_spec import (
    AUDIO_TRACK_PLAN_FORMAT,
    AUDIO_TRACK_POLICY_V1,
    AUDIO_TRACK_SCHEMA_VERSION,
    MAX_AUDIO_TRACK_SAMPLES,
    SPEECH_ID_FORM,
    samples_per_presentation_frame,
)
from living_diorama.language_realization.realization_spec import REALIZATION_ID_FORM
from living_diorama.narration.narration_schema_v1 import MODE_BASELINE, PLAN_MODES, UNIT_ID_FORM
from living_diorama.persistence.schema.state_hash import require_hash_hex
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_identifier,
    require_text,
)
from living_diorama.presentation.presentation_spec import MAX_PRESENTATION_FRAME, WINDOW_ID_FORM
from living_diorama.voice.voice_spec import VOICE_UNIT_ID_FORM

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
    {"accounting", "clock", "format", "policy", "schema_version", "source", "speech"}
)
"""Exactly the top-level keys an episode audio track plan carries."""

SOURCE_KEYS: Final = frozenset(
    {
        "episode",
        "mode",
        "previous_episode",
        "voice_manifest_sha256",
        "voice_manifest_schema_version",
        "presentation_plan_sha256",
        "presentation_schema_version",
    }
)
"""Exactly the keys binding a plan to the two documents it speaks.

Two digests, because this plan claims nothing that the voice manifest and the
presentation plan alone would not already prove: measured speech, named by
identity, and the window it was placed against. The voice plan, realization
plan, delivery plan, narration plan, shot plan, story plan and render export
are never bound here; every one of those relationships is proven by the
reused Phase 28 gate and the reused Phase 29 relationship gate this plan's
own cross-check runs in full.
"""

CLOCK_KEYS: Final = frozenset(
    {
        "audio_samples_total",
        "fps",
        "presentation_frames_total",
        "samples_per_presentation_frame",
    }
)
"""Exactly the keys the restated, gate-verified clock block carries."""

SPEECH_KEYS: Final = frozenset(
    {
        "speech_id",
        "voice_unit_id",
        "unit_id",
        "realization_id",
        "window_id",
        "start_sample",
        "speech_samples",
    }
)
"""Exactly the keys one speech-span record carries.

Deliberately no end sample (derivable), no file path, no WAV digest, no
capacity, no text and no margin: a speech span names its unit by identity,
states where it starts and how many samples it measured, and nothing else.
"""

ACCOUNTING_KEYS: Final = frozenset(
    {"speech_total", "speech_samples_total", "silence_samples_total"}
)
"""Exactly the keys the accounting block carries.

The aggregate verdict, stated in a way a truncated plan cannot fake: every
count is measured from the records present, including silence, which is
never a record of its own -- only the structural complement of the speech
that is.
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


def _validate_clock(value: object) -> dict[str, JsonValue]:
    """Verify the restated clock block closes its own arithmetic."""
    description = "audio track plan clock"
    clock = _require_document(value, description)
    require_exact_keys(clock, CLOCK_KEYS, description)

    fps = require_exact_int(clock.get("fps"), f"{description} fps")
    if fps < 1:
        raise ValueError(f"{description} fps must be >= 1, got {fps}")
    spf = require_exact_int(
        clock.get("samples_per_presentation_frame"),
        f"{description} samples_per_presentation_frame",
    )
    expected_spf = samples_per_presentation_frame(fps)
    if spf != expected_spf:
        raise ValueError(
            f"{description} samples_per_presentation_frame is {spf}, but the pinned sample "
            f"rate crossed with fps {fps} resolves to {expected_spf}"
        )
    presentation_frames_total = require_exact_int(
        clock.get("presentation_frames_total"), f"{description} presentation_frames_total"
    )
    if not 1 <= presentation_frames_total <= MAX_PRESENTATION_FRAME:
        raise ValueError(
            f"{description} presentation_frames_total must be within "
            f"[1, {MAX_PRESENTATION_FRAME}], got {presentation_frames_total}"
        )
    audio_samples_total = require_exact_int(
        clock.get("audio_samples_total"), f"{description} audio_samples_total"
    )
    expected_total = presentation_frames_total * spf
    if audio_samples_total != expected_total:
        raise ValueError(
            f"{description} audio_samples_total is {audio_samples_total}, but "
            f"{presentation_frames_total} frames at {spf} samples per frame is {expected_total}"
        )
    if not 1 <= audio_samples_total <= MAX_AUDIO_TRACK_SAMPLES:
        raise ValueError(
            f"{description} audio_samples_total must be within [1, {MAX_AUDIO_TRACK_SAMPLES}], "
            f"got {audio_samples_total}"
        )
    return clock


def _validate_speech_record(
    value: object,
    description: str,
    position: int,
    *,
    spf: int,
    audio_samples_total: int,
) -> tuple[int, int]:
    """Verify one speech-span record, and return ``(start_sample, speech_samples)``."""
    record = _require_document(value, description)
    require_exact_keys(record, SPEECH_KEYS, description)

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
            f"where the voice manifest's unit is {expected_voice_unit!r}"
        )
    unit_id = require_identifier(record.get("unit_id"), f"{description} unit_id")
    expected_unit = UNIT_ID_FORM % position
    if unit_id != expected_unit:
        raise ValueError(
            f"{description} speaks unit {unit_id!r} but sits at position {position}, where the "
            f"narration plan's unit is {expected_unit!r}"
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

    start_sample = require_exact_int(record.get("start_sample"), f"{description} start_sample")
    if start_sample % spf != 0:
        raise ValueError(
            f"{description} start_sample {start_sample} is not a multiple of {spf}; every "
            "onset sits on a presentation-frame boundary"
        )
    speech_samples = require_exact_int(
        record.get("speech_samples"), f"{description} speech_samples"
    )
    if speech_samples < 1:
        raise ValueError(f"{description} speech_samples must be >= 1, got {speech_samples}")
    span_end = start_sample + speech_samples
    if span_end > audio_samples_total:
        raise ValueError(
            f"{description} spans [{start_sample}, {span_end}), beyond the track's own "
            f"{audio_samples_total} total samples"
        )
    return start_sample, speech_samples


def validate_episode_audio_track_plan(value: object) -> dict[str, JsonValue]:
    """Verify a document's Episode Audio Track Plan V1 envelope, and return it.

    This validator is deliberately self-contained: it proves everything the
    plan can prove about itself, and nothing that needs the two bound
    sources. See the module docstring for what it cannot prove and which
    function proves those facts instead.

    Raises:
        TypeError: If any value has the wrong exact type.
        ValueError: If any key set, vocabulary member, ordering, bound or
            internal agreement is violated.
    """
    document = _require_document(value, "audio track plan")
    require_exact_keys(document, TOP_LEVEL_KEYS, "audio track plan")

    tag = require_text(document.get("format"), "audio track plan format")
    if tag != AUDIO_TRACK_PLAN_FORMAT:
        raise ValueError(
            f"audio track plan declares format {tag!r}; this build reads "
            f"{AUDIO_TRACK_PLAN_FORMAT!r} only"
        )
    version = require_exact_int(document.get("schema_version"), "audio track plan schema_version")
    if version != AUDIO_TRACK_SCHEMA_VERSION:
        raise ValueError(
            f"audio track plan declares unsupported schema version {version}; this build reads "
            f"version {AUDIO_TRACK_SCHEMA_VERSION} only"
        )
    policy = require_text(document.get("policy"), "audio track plan policy")
    if policy != AUDIO_TRACK_POLICY_V1:
        raise ValueError(
            f"audio track plan declares policy {policy!r}; this build derives and validates "
            f"{AUDIO_TRACK_POLICY_V1!r} only"
        )

    source = _require_document(document.get("source"), "audio track plan source")
    require_exact_keys(source, SOURCE_KEYS, "audio track plan source")
    mode = _require_member(source.get("mode"), PLAN_MODES, "audio track plan source mode")
    episode = require_exact_int(source.get("episode"), "audio track plan source episode")
    voice_manifest_version = require_exact_int(
        source.get("voice_manifest_schema_version"),
        "audio track plan source voice_manifest_schema_version",
    )
    if voice_manifest_version != SUPPORTED_VOICE_MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"audio track plan was derived from voice manifest schema version "
            f"{voice_manifest_version}; this build speaks version "
            f"{SUPPORTED_VOICE_MANIFEST_SCHEMA_VERSION} only"
        )
    presentation_version = require_exact_int(
        source.get("presentation_schema_version"),
        "audio track plan source presentation_schema_version",
    )
    if presentation_version != SUPPORTED_PRESENTATION_SCHEMA_VERSION:
        raise ValueError(
            f"audio track plan was derived from presentation schema version "
            f"{presentation_version}; this build speaks version "
            f"{SUPPORTED_PRESENTATION_SCHEMA_VERSION} only"
        )
    for field in ("voice_manifest_sha256", "presentation_plan_sha256"):
        require_hash_hex(source.get(field), f"audio track plan source {field}")

    previous = source.get("previous_episode")
    if mode == MODE_BASELINE:
        _require_null(
            previous,
            "audio track plan source previous_episode",
            "a baseline speaks one export's placement and follows no episode",
        )
        if episode != 0:
            raise ValueError(
                f"audio track plan source declares mode 'baseline' with episode {episode}; a "
                "baseline is always episode 0"
            )
    else:
        previous_episode = require_exact_int(previous, "audio track plan source previous_episode")
        if episode != previous_episode + 1:
            raise ValueError(
                f"audio track plan source declares episode {episode} following "
                f"{previous_episode}; a transition's episode always directly follows its "
                "previous episode"
            )

    clock = _validate_clock(document.get("clock"))
    spf = cast(int, clock["samples_per_presentation_frame"])
    audio_samples_total = cast(int, clock["audio_samples_total"])

    speech = _require_list(document.get("speech"), "audio track plan speech")
    if not speech:
        raise ValueError("audio track plan speech must not be empty")

    speech_samples_total = 0
    previous_end: int | None = None
    for position, record in enumerate(speech, start=1):
        start_sample, speech_samples = _validate_speech_record(
            record,
            f"audio track plan speech[{position - 1}]",
            position,
            spf=spf,
            audio_samples_total=audio_samples_total,
        )
        if previous_end is not None and start_sample < previous_end:
            raise ValueError(
                f"audio track plan speech[{position - 1}] starts at {start_sample}, before the "
                f"previous span ends at {previous_end}; speech spans never overlap and always "
                "follow narration order"
            )
        previous_end = start_sample + speech_samples
        speech_samples_total += speech_samples

    accounting = _require_document(document.get("accounting"), "audio track plan accounting")
    require_exact_keys(accounting, ACCOUNTING_KEYS, "audio track plan accounting")
    speech_total = require_exact_int(
        accounting.get("speech_total"), "audio track plan accounting speech_total"
    )
    if speech_total != len(speech):
        raise ValueError(
            f"audio track plan accounting speech_total is {speech_total}, but the plan carries "
            f"{len(speech)} speech records"
        )
    recorded_samples_total = require_exact_int(
        accounting.get("speech_samples_total"), "audio track plan accounting speech_samples_total"
    )
    if recorded_samples_total != speech_samples_total:
        raise ValueError(
            f"audio track plan accounting speech_samples_total is {recorded_samples_total}, but "
            f"the records present sum to {speech_samples_total}"
        )
    silence_samples_total = require_exact_int(
        accounting.get("silence_samples_total"),
        "audio track plan accounting silence_samples_total",
    )
    expected_silence = audio_samples_total - speech_samples_total
    if silence_samples_total != expected_silence:
        raise ValueError(
            f"audio track plan accounting silence_samples_total is {silence_samples_total}, but "
            f"{audio_samples_total} total samples minus {speech_samples_total} speech samples "
            f"is {expected_silence}"
        )

    return document
