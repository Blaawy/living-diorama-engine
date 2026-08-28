"""The Phase 27 presentation mapping, expanded, and the integer clock it must cross.

This module owns two pure, integer-only questions: for a validated Phase 27 presentation
plan, which semantic frame does each presentation frame show; and, for the three bound
primaries, does the integer clock -- fps, sample rate, presentation-frame total, audio
sample total, and the semantic/witness frame span -- close on itself.

Nothing here touches the filesystem, decodes an image, or reads a byte of a rendered
frame. It reasons about integers and validated documents alone.
"""

from typing import Final, cast

from living_diorama.audio_composition.audio_composition_schema_v1 import (
    validate_episode_audio_composition_manifest,
)
from living_diorama.media_assembly.media_assembly_schema_v1 import JsonValue
from living_diorama.presentation.presentation_schema_v1 import validate_episode_presentation_plan
from living_diorama.render_execution.render_execution_schema_v1 import (
    validate_episode_render_manifest,
)
from living_diorama.render_execution.render_execution_spec import ROLE_PLAYBACK

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
"""Restated from :mod:`media_assembly_schema_v1` for this module's own return-shape doc."""


class MediaAssemblyRefused(ValueError):
    """The geometry, a bound source, or a produced artifact refuses this assembly."""


def presentation_frame_map(presentation_plan: object) -> tuple[int, ...]:
    """Return the semantic frame shown at each presentation frame.

    Index ``i`` (0-based) carries the semantic frame shown at presentation frame ``i + 1``.
    The returned length is the plan's own ``accounting.presentation_frames_total``.

    The plan's own standalone validator already proves this expansion is well-formed --
    contiguous, gap-free, and closing on its own accounting total. This function re-derives
    the same span from the segments alone, belt-and-braces: two independent derivations
    agreeing is this project's own idiom, and a later mapping re-proof (the self-contained
    audit) reuses this exact function against a copied plan with no gate available to lean
    on.

    Args:
        presentation_plan: The Episode Presentation Plan V1 document.

    Returns:
        One semantic frame per presentation frame, in presentation order.

    Raises:
        TypeError: If a value is of the wrong exact type.
        MediaAssemblyRefused: If the segments are not contiguous, do not close on the
            plan's own accounting total, or the plan is otherwise malformed in a way its
            own standalone validator did not already catch.
    """
    presentation = validate_episode_presentation_plan(presentation_plan)
    segments = cast(list[dict[str, JsonValue]], presentation["segments"])
    accounting = cast(dict[str, JsonValue], presentation["accounting"])

    mapping: list[int] = []
    presentation_cursor = 1
    for position, segment in enumerate(segments, start=1):
        semantic_start = cast(int, segment["semantic_start_frame"])
        semantic_end = cast(int, segment["semantic_end_frame"])
        dwell = cast(int, segment["dwell_frames"])
        presentation_start = cast(int, segment["presentation_start_frame"])
        presentation_end = cast(int, segment["presentation_end_frame"])

        if presentation_start != presentation_cursor:
            raise MediaAssemblyRefused(
                f"presentation plan segments[{position - 1}] starts at presentation frame "
                f"{presentation_start}, but the previous segment left off at "
                f"{presentation_cursor}; segments must tile the presentation timeline with "
                "no gap and no overlap"
            )
        for semantic in range(semantic_start, semantic_end + 1):
            mapping.extend([semantic] * dwell)
        presentation_cursor = presentation_end + 1
        if len(mapping) + 1 != presentation_cursor:
            raise MediaAssemblyRefused(
                f"presentation plan segments[{position - 1}] declares presentation_end_frame "
                f"{presentation_end}, but its expansion produced {len(mapping)} presentation "
                "frames so far"
            )

    expected_total = cast(int, accounting["presentation_frames_total"])
    if len(mapping) != expected_total:
        raise MediaAssemblyRefused(
            f"presentation plan segments expand to {len(mapping)} presentation frames, but "
            f"accounting.presentation_frames_total is {expected_total}"
        )
    return tuple(mapping)


def require_playback_lookup(render_manifest: object) -> dict[int, dict[str, JsonValue]]:
    """Return ``{semantic_frame: record}`` for the manifest's playback records only.

    Witness records -- the terminal boundary frame -- never enter this lookup, because it
    is built by filtering on ``role``, never by excluding a name. A semantic frame the
    presentation plan needs but this lookup lacks refuses with a named error the first time
    it is consulted.

    Args:
        render_manifest: The Episode Render Manifest V1 document.

    Returns:
        A mapping from semantic frame number to its playback frame record.

    Raises:
        TypeError: If a value is of the wrong exact type.
        MediaAssemblyRefused: If two playback records name the same semantic frame.
    """
    manifest = validate_episode_render_manifest(render_manifest)
    frames = cast(list[dict[str, JsonValue]], manifest["frames"])

    lookup: dict[int, dict[str, JsonValue]] = {}
    for record in frames:
        if record["role"] != ROLE_PLAYBACK:
            continue
        semantic = cast(int, record["frame"])
        if semantic in lookup:
            raise MediaAssemblyRefused(
                f"render manifest names semantic frame {semantic} in more than one playback "
                "record; a playback frame is expected exactly once"
            )
        lookup[semantic] = record
    return lookup


def require_clock_closure(
    presentation_plan: object,
    render_manifest: object,
    audio_composition_manifest: object,
) -> dict[str, int]:
    """Prove the presentation, visual and audio clocks close on one another, exactly.

    Every value here is an exact ``int``; no float and no wall clock is authoritative
    anywhere in this function.

    Args:
        presentation_plan: The Episode Presentation Plan V1 document.
        render_manifest: The Episode Render Manifest V1 document.
        audio_composition_manifest: The Episode Audio Composition Manifest V1 document.

    Returns:
        The eight-key resolved clock block (``CLOCK_KEYS``).

    Raises:
        TypeError: If a value is of the wrong exact type.
        MediaAssemblyRefused: If any clock law does not hold.
    """
    presentation = validate_episode_presentation_plan(presentation_plan)
    manifest = validate_episode_render_manifest(render_manifest)
    composition = validate_episode_audio_composition_manifest(audio_composition_manifest)

    timeline = cast(dict[str, JsonValue], presentation["timeline"])
    accounting = cast(dict[str, JsonValue], presentation["accounting"])
    emission = cast(dict[str, JsonValue], manifest["emission"])
    audio = cast(dict[str, JsonValue], composition["audio"])

    fps = cast(int, timeline["fps"])
    presentation_frames_total = cast(int, accounting["presentation_frames_total"])
    audio_sample_rate_hz = cast(int, audio["sample_rate_hz"])
    audio_samples_total = cast(int, audio["audio_samples"])
    semantic_first_frame = cast(int, emission["first_frame"])
    semantic_final_frame = cast(int, emission["final_frame"])
    witness_frame = cast(int, emission["witness_frame"])
    playback_fps = cast(int, emission["playback_fps"])

    if fps < 1:
        raise MediaAssemblyRefused(f"presentation plan timeline fps must be >= 1, got {fps}")
    if playback_fps != fps:
        raise MediaAssemblyRefused(
            f"render manifest emission playback_fps is {playback_fps}, but the presentation "
            f"plan's own timeline fps is {fps}; the visual and presentation clocks disagree"
        )
    if audio_sample_rate_hz < 1:
        raise MediaAssemblyRefused(
            f"audio composition manifest audio sample_rate_hz must be >= 1, got "
            f"{audio_sample_rate_hz}"
        )
    if audio_sample_rate_hz % fps != 0:
        raise MediaAssemblyRefused(
            f"the audio sample rate {audio_sample_rate_hz} is not evenly divisible by fps "
            f"{fps}; the audio and presentation clocks do not cross exactly, and this policy "
            "refuses rather than approximate"
        )
    samples_per_presentation_frame = audio_sample_rate_hz // fps
    expected_audio_total = presentation_frames_total * samples_per_presentation_frame
    if audio_samples_total != expected_audio_total:
        raise MediaAssemblyRefused(
            f"audio_samples_total is {audio_samples_total}, but {presentation_frames_total} "
            f"presentation frames at {samples_per_presentation_frame} samples per frame is "
            f"{expected_audio_total}"
        )

    if semantic_final_frame < semantic_first_frame:
        raise MediaAssemblyRefused(
            f"render manifest emission final_frame {semantic_final_frame} is before "
            f"first_frame {semantic_first_frame}"
        )
    if witness_frame != semantic_final_frame + 1:
        raise MediaAssemblyRefused(
            f"render manifest emission witness_frame must equal final_frame + 1; got "
            f"{witness_frame} for final_frame {semantic_final_frame}"
        )

    segments = cast(list[dict[str, JsonValue]], presentation["segments"])
    if not segments:
        raise MediaAssemblyRefused("presentation plan carries no segments")
    plan_semantic_first = cast(int, segments[0]["semantic_start_frame"])
    plan_semantic_final = cast(int, segments[-1]["semantic_end_frame"])
    if plan_semantic_first != semantic_first_frame or plan_semantic_final != semantic_final_frame:
        raise MediaAssemblyRefused(
            f"presentation plan semantic coverage is [{plan_semantic_first}, "
            f"{plan_semantic_final}], but the render manifest's own emission span is "
            f"[{semantic_first_frame}, {semantic_final_frame}]"
        )

    return {
        "audio_sample_rate_hz": audio_sample_rate_hz,
        "audio_samples_total": audio_samples_total,
        "fps": fps,
        "presentation_frames_total": presentation_frames_total,
        "samples_per_presentation_frame": samples_per_presentation_frame,
        "semantic_final_frame": semantic_final_frame,
        "semantic_first_frame": semantic_first_frame,
        "witness_frame": witness_frame,
    }


def require_witness_frame_excluded(mapping: tuple[int, ...], clock: dict[str, int]) -> None:
    """Refuse unless no presentation position maps to the witness frame.

    Args:
        mapping: The expanded presentation-to-semantic frame map.
        clock: The resolved clock block returned by :func:`require_clock_closure`.

    Raises:
        MediaAssemblyRefused: If any position maps to the witness frame, or outside the
            proven semantic span.
    """
    witness_frame = clock["witness_frame"]
    semantic_first = clock["semantic_first_frame"]
    semantic_final = clock["semantic_final_frame"]
    for position, semantic in enumerate(mapping, start=1):
        if semantic == witness_frame:
            raise MediaAssemblyRefused(
                f"presentation frame {position} maps to semantic frame {semantic}, which is "
                "the witness frame; the witness frame is never presented"
            )
        if not (semantic_first <= semantic <= semantic_final):
            raise MediaAssemblyRefused(
                f"presentation frame {position} maps to semantic frame {semantic}, outside "
                f"[{semantic_first}, {semantic_final}]"
            )


__all__ = [
    "CLOCK_KEYS",
    "MediaAssemblyRefused",
    "presentation_frame_map",
    "require_clock_closure",
    "require_playback_lookup",
    "require_witness_frame_excluded",
]
