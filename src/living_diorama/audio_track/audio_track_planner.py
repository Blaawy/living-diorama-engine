"""Deriving an Episode Audio Track Plan from a voice manifest and a presentation plan.

The derivation is a pure function of its inputs. It reads no clock, draws no
randomness, consults no filesystem path, parses no audio, and depends on no
iteration order that Python is free to vary. The same two documents always
produce the same bytes.

What it decides is exactly where each unit's already-measured speech begins
on the episode's single audio-sample clock, and therefore exactly what is
silence -- and only from structure: a window's own presentation-frame
position and the pinned samples-per-frame crossing. What it never decides is
whether real speech fits (Phase 29's measured question, already answered by
the manifest this module reads) or what is said (never read here at all --
no module in this package touches ``realized_text``).

This module performs the same lightweight join every upstream planner
performs: it proves the two documents it receives actually name each other,
so a voice manifest and a presentation plan built for different episodes can
never be joined into one audio track plan. It does **not** re-run the deep
source-verification chain that proves the voice manifest is true of a real
executed WAV, or that the presentation plan's windows are true of a
delivery, narration, shot, story and export chain -- those locked gates are
:func:`living_diorama.voice_execution.audit_voice_directory` and
:func:`living_diorama.voice.voice_cross_check.validate_episode_voice_plan_against_sources`,
and this layer's own cross-check runs both before this planner's derivation
may be trusted with any upstream measurement or window truth.
"""

from typing import cast

from living_diorama.audio_track.audio_track_schema_v1 import (
    JsonValue,
    validate_episode_audio_track_plan,
)
from living_diorama.audio_track.audio_track_spec import (
    AUDIO_TRACK_PLAN_FORMAT,
    AUDIO_TRACK_POLICY_V1,
    AUDIO_TRACK_SCHEMA_VERSION,
    SPEECH_ID_FORM,
    samples_per_presentation_frame,
    speech_start_sample,
)
from living_diorama.narration.narration_schema_v1 import UNIT_ID_FORM
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.presentation.presentation_schema_v1 import validate_episode_presentation_plan
from living_diorama.voice_execution.voice_execution_schema_v1 import (
    validate_episode_voice_manifest,
)

__all__ = [
    "build_episode_audio_track_plan_bytes",
    "build_episode_audio_track_plan_document",
]


def _document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    return cast(dict[str, JsonValue], value)


def _require_join(
    manifest: dict[str, JsonValue], presentation: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    """Prove the two documents place one executed, presented episode's speech.

    Digest equality is the load-bearing check: the voice manifest already
    recorded which presentation plan its underlying voice plan named, so this
    layer never has to decide whether two files "look like" the same
    episode. It asks the manifest what it bound and compares against the
    presentation plan actually offered.

    Raises:
        ValueError: If any binding or identity does not hold.
    """
    manifest_source = _document(manifest["source"], "voice manifest source")
    presentation_source = _document(presentation["source"], "presentation plan source")

    presentation_digest = sha256_hex(dumps_canonical(presentation, "presentation plan"))
    if manifest_source["presentation_plan_sha256"] != presentation_digest:
        raise ValueError(
            f"the voice manifest binds presentation plan "
            f"{manifest_source['presentation_plan_sha256']!r}, but the offered presentation "
            f"plan hashes to {presentation_digest!r}; the manifest and the presentation plan "
            "are not the same episode's"
        )
    for field in ("mode", "episode", "previous_episode"):
        if manifest_source[field] != presentation_source[field]:
            raise ValueError(
                f"the voice manifest declares {field} {manifest_source[field]!r}, but the "
                f"presentation plan it names declares {presentation_source[field]!r}"
            )

    manifest_digest = sha256_hex(dumps_canonical(manifest, "voice manifest"))
    return {
        "episode": manifest_source["episode"],
        "mode": manifest_source["mode"],
        "previous_episode": manifest_source["previous_episode"],
        "voice_manifest_sha256": manifest_digest,
        "voice_manifest_schema_version": manifest["schema_version"],
        "presentation_plan_sha256": presentation_digest,
        "presentation_schema_version": presentation["schema_version"],
    }


def build_episode_audio_track_plan_document(
    voice_manifest: object, presentation_plan: object
) -> dict[str, JsonValue]:
    """Return the Episode Audio Track Plan document for one executed, presented episode.

    Args:
        voice_manifest: The Episode Voice Manifest V1 whose measured speech
            this plan places by identity, never by re-parsing audio.
        presentation_plan: The Episode Presentation Plan V1 whose windows
            this plan's speech spans draw their onset from.

    Returns:
        A validated Episode Audio Track Plan V1 document.

    Raises:
        TypeError: If either input has the wrong shape.
        ValueError: If either input fails its own contract, if the two do
            not join, or if the unit and window counts disagree.
    """
    manifest = validate_episode_voice_manifest(voice_manifest)
    presentation = validate_episode_presentation_plan(presentation_plan)

    source = _require_join(manifest, presentation)

    voice_units = cast(list[dict[str, JsonValue]], manifest["voice_units"])
    windows = cast(list[dict[str, JsonValue]], presentation["windows"])
    if len(voice_units) != len(windows):
        raise ValueError(
            f"the voice manifest executes {len(voice_units)} units, but the presentation plan "
            f"presents {len(windows)}; every unit is placed exactly once"
        )

    timeline = _document(presentation["timeline"], "presentation plan timeline")
    fps = cast(int, timeline["fps"])
    presentation_accounting = _document(presentation["accounting"], "presentation plan accounting")
    presentation_frames_total = cast(int, presentation_accounting["presentation_frames_total"])
    spf = samples_per_presentation_frame(fps)
    audio_samples_total = presentation_frames_total * spf

    speech: list[JsonValue] = []
    speech_samples_total = 0
    for position, (unit, window) in enumerate(zip(voice_units, windows, strict=True), start=1):
        expected_unit = UNIT_ID_FORM % position
        if unit["unit_id"] != expected_unit:
            raise ValueError(
                f"voice manifest voice_units[{position - 1}] speaks unit {unit['unit_id']!r}, "
                f"not the positional {expected_unit!r}"
            )
        if window["unit_id"] != expected_unit:
            raise ValueError(
                f"presentation plan windows[{position - 1}] presents unit "
                f"{window['unit_id']!r}, not the positional {expected_unit!r}"
            )
        if unit["realization_id"] != window["realization_id"]:
            raise ValueError(
                f"voice manifest voice_units[{position - 1}] names realization "
                f"{unit['realization_id']!r}, but the presentation plan's window at that "
                f"position names {window['realization_id']!r}"
            )
        if unit["window_id"] != window["window_id"]:
            raise ValueError(
                f"voice manifest voice_units[{position - 1}] names window "
                f"{unit['window_id']!r}, but the presentation plan's window at that position "
                f"is {window['window_id']!r}"
            )

        start_sample = speech_start_sample(cast(int, window["presentation_start_frame"]), fps)
        speech_samples = cast(int, unit["speech_samples"])
        speech_samples_total += speech_samples
        speech.append(
            {
                "speech_id": SPEECH_ID_FORM % position,
                "voice_unit_id": unit["voice_unit_id"],
                "unit_id": expected_unit,
                "realization_id": unit["realization_id"],
                "window_id": unit["window_id"],
                "start_sample": start_sample,
                "speech_samples": speech_samples,
            }
        )

    document: dict[str, JsonValue] = {
        "accounting": {
            "speech_total": len(speech),
            "speech_samples_total": speech_samples_total,
            "silence_samples_total": audio_samples_total - speech_samples_total,
        },
        "clock": {
            "audio_samples_total": audio_samples_total,
            "fps": fps,
            "presentation_frames_total": presentation_frames_total,
            "samples_per_presentation_frame": spf,
        },
        "format": AUDIO_TRACK_PLAN_FORMAT,
        "policy": AUDIO_TRACK_POLICY_V1,
        "schema_version": AUDIO_TRACK_SCHEMA_VERSION,
        "source": source,
        "speech": speech,
    }
    return validate_episode_audio_track_plan(document)


def build_episode_audio_track_plan_bytes(
    voice_manifest: object, presentation_plan: object
) -> bytes:
    """Return the canonical Episode Audio Track Plan bytes for the given sources.

    The returned bytes are the one canonical encoding of the plan: sorted
    keys, tight separators, no non-finite floats, and exactly one trailing
    newline.
    """
    document = build_episode_audio_track_plan_document(voice_manifest, presentation_plan)
    return dumps_canonical(document, "audio track plan")
