"""Cross-validation of an Episode Audio Track Plan against its actual sources.

:func:`living_diorama.audio_track.audio_track_schema_v1.validate_episode_audio_track_plan`
proves everything an audio track plan can prove about itself: its onsets sit
on presentation-frame boundaries, its spans never overlap, and every span
fits inside its own track total. What it cannot prove is that the plan's
claims are *true of its sources* -- and, more than any other proof in this
chain, it cannot prove that the values it consumed from those sources were
themselves proven true of *their* sources. An audio track plan whose
``speech_samples`` was never checked against the voice manifest's own
measured, audited artifact, or whose bound presentation plan was never
checked against the actual delivery, narration, shot, story and
render-export chain, would be syntactically perfect and semantically
worthless.

This module closes both gaps by reusing, in full and unweakened, the two
upstream proofs that already own them:
:func:`living_diorama.voice.voice_cross_check.validate_episode_voice_plan_against_sources`,
which proves the presentation plan's windows and the whole upstream chain
true, and
:func:`living_diorama.voice_execution.require_manifest_matches_plan`, which
proves the voice manifest genuinely executes the gate-verified voice plan.
Once both pass, this module verifies the audio track plan's own bindings and
every per-span placement, then seals the whole question by re-deriving the
plan from its two bound sources: the audio track contract is a deterministic
single-output function of its inputs, so the one valid plan for a given
voice manifest and presentation plan is the plan the planner derives.

Voice Plan, Language Realization Plan, Narration Delivery Plan, Narration
Plan, Shot Direction Plan, Story Plan and Render Export travel through this
module only as arguments to the reused Phase 28 gate: no audio track module
treats any of the seven as derivation authority, and no audio track field
ever restates a digest of any of them.

**No module here parses a WAV file.** The one place artifact truth is proven
is the reused Phase 29 directory audit, run by the CLI as a precondition
before this gate is ever called (see
:mod:`living_diorama.cli.build_audio_track_plan`) -- this module trusts the
audited, gate-verified voice manifest it is handed, and never opens a
speech file itself.
"""

from typing import cast

from living_diorama.audio_track.audio_track_planner import build_episode_audio_track_plan_bytes
from living_diorama.audio_track.audio_track_schema_v1 import (
    JsonValue,
    validate_episode_audio_track_plan,
)
from living_diorama.audio_track.audio_track_spec import (
    samples_per_presentation_frame,
    speech_start_sample,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.presentation.presentation_schema_v1 import validate_episode_presentation_plan
from living_diorama.voice.voice_cross_check import validate_episode_voice_plan_against_sources
from living_diorama.voice_execution.voice_execution_binding import require_manifest_matches_plan
from living_diorama.voice_execution.voice_execution_schema_v1 import (
    validate_episode_voice_manifest,
)

__all__ = ["validate_episode_audio_track_plan_against_sources"]


def _document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    return cast(dict[str, JsonValue], value)


def _check_bindings(
    source: dict[str, JsonValue],
    voice_manifest: dict[str, JsonValue],
    presentation: dict[str, JsonValue],
) -> None:
    """Verify the plan names the exact documents offered, and that they agree."""
    manifest_digest = sha256_hex(dumps_canonical(voice_manifest, "voice manifest"))
    presentation_digest = sha256_hex(dumps_canonical(presentation, "presentation plan"))

    for field, offered, label in (
        ("voice_manifest_sha256", manifest_digest, "voice manifest"),
        ("presentation_plan_sha256", presentation_digest, "presentation plan"),
    ):
        if source[field] != offered:
            raise ValueError(
                f"audio track plan binds {label} {source[field]!r}, but the offered {label}'s "
                f"canonical bytes hash to {offered!r}; this plan does not place that document"
            )

    manifest_source = _document(voice_manifest["source"], "voice manifest source")
    if manifest_source["presentation_plan_sha256"] != presentation_digest:
        raise ValueError(
            f"audio track plan presents a voice manifest built from presentation "
            f"{manifest_source['presentation_plan_sha256']!r} against a presentation plan that "
            f"hashes to {presentation_digest!r}; the voice manifest and the presentation plan "
            "are not the same episode's"
        )

    if source["voice_manifest_schema_version"] != voice_manifest["schema_version"]:
        raise ValueError(
            f"audio track plan records voice manifest schema version "
            f"{source['voice_manifest_schema_version']}, but the voice manifest declares "
            f"{voice_manifest['schema_version']}"
        )
    if source["presentation_schema_version"] != presentation["schema_version"]:
        raise ValueError(
            f"audio track plan records presentation schema version "
            f"{source['presentation_schema_version']}, but the presentation plan declares "
            f"{presentation['schema_version']}"
        )
    for field in ("episode", "mode", "previous_episode"):
        if source[field] != manifest_source[field]:
            raise ValueError(
                f"audio track plan declares {field} {source[field]!r}, but the voice manifest "
                f"it places declares {manifest_source[field]!r}"
            )


def validate_episode_audio_track_plan_against_sources(
    audio_track_plan: object,
    voice_manifest: object,
    presentation_plan: object,
    voice_plan: object,
    realization_plan: object,
    delivery_plan: object,
    narration_plan: object,
    shot_plan: object,
    story_plan: object,
    current_export: object,
) -> dict[str, JsonValue]:
    """Verify an Episode Audio Track Plan against its actual sources.

    Args:
        audio_track_plan: The Episode Audio Track Plan V1 document to verify.
        voice_manifest: The Episode Voice Manifest V1 whose measured speech
            this plan places. Bound in this plan's source block.
        presentation_plan: The Episode Presentation Plan V1 whose windows
            this plan's spans draw their onset from. Bound in this plan's
            source block.
        voice_plan: The Episode Voice Plan V1 the manifest executes.
            Verification-only: an argument to the reused Phase 28 gate and
            to the reused Phase 29 relationship gate.
        realization_plan: Verification-only: an argument to the reused gate.
        delivery_plan: Verification-only: an argument to the reused gate.
        narration_plan: Verification-only: an argument to the reused gate.
        shot_plan: Verification-only: an argument to the reused gate.
        story_plan: Verification-only: an argument to the reused gate.
        current_export: Verification-only: an argument to the reused gate.

    The named checks, in order:

    * the locked Phase 28 gate passes in full -- proving the presentation
      plan's windows and the whole upstream chain true of the actual
      delivery, narration, shot, story and render-export chain
    * the reused Phase 29 relationship gate passes -- proving the voice
      manifest genuinely executes the gate-verified voice plan
    * the audio track plan validates under its own contract
    * the two bound documents validate under their own contracts
    * the plan's two digests name exactly the voice manifest and
      presentation documents offered, and those documents name each other
    * schema versions, mode, episode and previous episode agree across the
      audio track plan and the voice manifest it places
    * the restated clock (fps, presentation frame total, samples-per-frame
      crossing, audio sample total) agrees with the presentation plan's own
      proven values
    * every speech span names its positional unit, realization, window and
      voice unit; its ``speech_samples`` equals the manifest's measured
      value; its ``start_sample`` equals the actual window's proven onset;
      and it never escapes its own window's sample image
    * accounting is recomputed from the records present

    Finally the plan is re-derived from its two bound sources and must equal
    it byte for byte, which closes every remaining degree of freedom --
    every ``start_sample`` value itself included.

    Returns:
        The verified audio track plan.

    Raises:
        TypeError: If any input has the wrong Python type.
        ValueError: If either reused gate refuses, or if any binding,
            identity, agreement, placement or derivation check fails.
    """
    # No measured speech, and no presentation window truth, becomes
    # authoritative before the two documents that prove them both true of
    # their own sources have been verified in full.
    validate_episode_voice_plan_against_sources(
        voice_plan,
        realization_plan,
        presentation_plan,
        delivery_plan,
        narration_plan,
        shot_plan,
        story_plan,
        current_export,
    )
    voice_manifest_doc = validate_episode_voice_manifest(voice_manifest)
    require_manifest_matches_plan(voice_manifest_doc, voice_plan)

    plan = validate_episode_audio_track_plan(audio_track_plan)
    presentation = validate_episode_presentation_plan(presentation_plan)

    source = _document(plan["source"], "audio track plan source")
    _check_bindings(source, voice_manifest_doc, presentation)

    clock = _document(plan["clock"], "audio track plan clock")
    timeline = _document(presentation["timeline"], "presentation plan timeline")
    fps = cast(int, timeline["fps"])
    if clock["fps"] != fps:
        raise ValueError(
            f"audio track plan clock fps is {clock['fps']!r}, but the presentation plan's "
            f"actual timeline fps is {fps!r}"
        )
    presentation_accounting = _document(presentation["accounting"], "presentation plan accounting")
    presentation_frames_total = cast(int, presentation_accounting["presentation_frames_total"])
    if clock["presentation_frames_total"] != presentation_frames_total:
        raise ValueError(
            f"audio track plan clock presentation_frames_total is "
            f"{clock['presentation_frames_total']!r}, but the presentation plan's actual total "
            f"is {presentation_frames_total!r}"
        )
    spf = samples_per_presentation_frame(fps)
    if clock["samples_per_presentation_frame"] != spf:
        raise ValueError(
            f"audio track plan clock samples_per_presentation_frame is "
            f"{clock['samples_per_presentation_frame']!r}, but the proven crossing is {spf!r}"
        )
    audio_samples_total = presentation_frames_total * spf
    if clock["audio_samples_total"] != audio_samples_total:
        raise ValueError(
            f"audio track plan clock audio_samples_total is {clock['audio_samples_total']!r}, "
            f"but {presentation_frames_total} frames at {spf} samples per frame is "
            f"{audio_samples_total!r}"
        )

    speech = cast(list[dict[str, JsonValue]], plan["speech"])
    manifest_units = cast(list[dict[str, JsonValue]], voice_manifest_doc["voice_units"])
    windows = cast(list[dict[str, JsonValue]], presentation["windows"])
    if not (len(speech) == len(manifest_units) == len(windows)):
        raise ValueError(
            f"audio track plan carries {len(speech)} speech spans for a voice manifest "
            f"executing {len(manifest_units)} units and a presentation plan presenting "
            f"{len(windows)} windows; every unit is placed exactly once"
        )

    for position, (span, unit, window) in enumerate(
        zip(speech, manifest_units, windows, strict=True)
    ):
        label = f"audio track plan speech[{position}]"
        if span["unit_id"] != unit["unit_id"]:
            raise ValueError(
                f"{label} places unit {span['unit_id']!r}, but the voice manifest executes "
                f"{unit['unit_id']!r} at that position"
            )
        if span["unit_id"] != window["unit_id"]:
            raise ValueError(
                f"{label} places unit {span['unit_id']!r}, but the presentation plan presents "
                f"{window['unit_id']!r} at that position"
            )
        if span["realization_id"] != unit["realization_id"]:
            raise ValueError(
                f"{label} names realization {span['realization_id']!r}, but the voice manifest "
                f"holds {unit['realization_id']!r} at that position"
            )
        if span["window_id"] != window["window_id"]:
            raise ValueError(
                f"{label} names window {span['window_id']!r}, but the presentation plan holds "
                f"{window['window_id']!r} at that position"
            )
        if span["voice_unit_id"] != unit["voice_unit_id"]:
            raise ValueError(
                f"{label} names voice unit {span['voice_unit_id']!r}, but the voice manifest "
                f"holds {unit['voice_unit_id']!r} at that position"
            )
        if span["speech_samples"] != unit["speech_samples"]:
            raise ValueError(
                f"{label} declares speech_samples {span['speech_samples']!r}, but the voice "
                f"manifest measured {unit['speech_samples']!r} for that unit"
            )
        expected_start = speech_start_sample(cast(int, window["presentation_start_frame"]), fps)
        if span["start_sample"] != expected_start:
            raise ValueError(
                f"{label} declares start_sample {span['start_sample']!r}, but its actual "
                f"window's onset resolves to {expected_start!r}; onset is proven true of the "
                "real window, never merely plausible"
            )
        window_end_sample = cast(int, window["presentation_end_frame"]) * spf
        span_end = cast(int, span["start_sample"]) + cast(int, span["speech_samples"])
        if span_end > window_end_sample:
            raise ValueError(
                f"{label} spans up to sample {span_end}, beyond its own window's sample image "
                f"ending at {window_end_sample}; a placed span never escapes the window it was "
                "proven to fit"
            )

    accounting = _document(plan["accounting"], "audio track plan accounting")
    speech_samples_total = sum(cast(int, record["speech_samples"]) for record in speech)
    if accounting["speech_total"] != len(speech):
        raise ValueError(
            f"audio track plan accounts {accounting['speech_total']!r} speech spans but "
            f"carries {len(speech)}"
        )
    if accounting["speech_samples_total"] != speech_samples_total:
        raise ValueError(
            f"audio track plan accounts speech_samples_total "
            f"{accounting['speech_samples_total']!r}, but the records present sum to "
            f"{speech_samples_total}"
        )
    expected_silence = audio_samples_total - speech_samples_total
    if accounting["silence_samples_total"] != expected_silence:
        raise ValueError(
            f"audio track plan accounts silence_samples_total "
            f"{accounting['silence_samples_total']!r}, but {audio_samples_total} total samples "
            f"minus {speech_samples_total} speech samples is {expected_silence}"
        )

    # The contract is a deterministic single-output function of its two
    # bound sources, so the one valid plan for this manifest and this
    # presentation plan is the one the planner derives. Byte equality closes
    # every remaining degree of freedom -- every start_sample value itself
    # included. The voice plan, realization plan, delivery plan, narration
    # plan, shot plan, story plan and render export never enter this
    # derivation: they are the reused gates' arguments, not this layer's own.
    derived = build_episode_audio_track_plan_bytes(voice_manifest_doc, presentation)
    offered = dumps_canonical(plan, "audio track plan")
    if offered != derived:
        raise ValueError(
            "audio track plan does not equal the deterministic derivation from the voice "
            "manifest and presentation plan it binds; a plan is source-verified only when it "
            "is the plan those two documents produce"
        )

    return plan
