"""Phase 30 audio track policy: the onset law and its clock-crossing arithmetic.

An episode audio track plan decides exactly one new fact per voice unit:
where its measured speech begins on the episode's single audio-sample clock.
Nothing here places audio, produces audio, or reads a sample of it -- the
policy is pure arithmetic over two already-proven integers: a unit's Phase 27
presentation window and the Phase 28/29-pinned samples-per-frame crossing.

THE AUDIO TRACK PLAN PLACES MEASURED SPEECH ON THE PRESENTATION CLOCK. IT
PRODUCES NO AUDIO.
"""

from typing import Final

from living_diorama.voice.voice_spec import samples_per_presentation_frame

__all__ = [
    "AUDIO_TRACK_PLAN_FORMAT",
    "AUDIO_TRACK_POLICY_V1",
    "AUDIO_TRACK_SCHEMA_VERSION",
    "MAX_AUDIO_TRACK_SAMPLES",
    "SPEECH_ID_FORM",
    "samples_per_presentation_frame",
    "speech_start_sample",
]

AUDIO_TRACK_PLAN_FORMAT: Final = "living_diorama_episode_audio_track_plan"
"""The format tag every episode audio track plan declares."""

AUDIO_TRACK_SCHEMA_VERSION: Final = 1
"""The audio track plan schema version this build reads and writes."""

AUDIO_TRACK_POLICY_V1: Final = "audio_track_policy_v1"
"""The one audio track policy this build derives and validates.

Declared in the document rather than merely implied, so a plan written under
a revised policy can never be mistaken for this one.
"""

SPEECH_ID_FORM: Final = "speech_%04d"
"""A speech-span identifier is positional and nothing else, so it is derivable."""

MAX_AUDIO_TRACK_SAMPLES: Final = 1_000_000_000
"""This layer's own structural rail on the episode audio track's total length.

Deliberately an independent literal, for the same reason
``MAX_VOICE_CAPACITY_SAMPLES`` and ``MAX_SPEECH_SAMPLES`` are independent:
standalone validation of an audio track plan document never opens a second
document, so at that point there is no proven presentation total to compare
against. This is a plausibility ceiling only, never timing authority -- the
one authoritative track length is recomputed, in the cross-check, from the
actual verified Phase 27 presentation total.
"""


def speech_start_sample(presentation_start_frame: int, fps: int) -> int:
    """Return the first audio sample of the presentation frame a window's onset owns.

    This is the whole of the onset *derivation*: Phase 25 and Phase 27 own
    the onset *policy* ("a unit's speech begins at its slot's, and its
    window's, first frame"); this function is the one place that policy
    becomes a stored sample offset. There is no offset knob and no moved
    onset -- the onset is structurally the window's first frame, always.

    Args:
        presentation_start_frame: The window's own
            ``presentation_start_frame``, 1-based.
        fps: The proven Phase 27 presentation timeline's frames-per-second.

    Returns:
        ``(presentation_start_frame - 1) * samples_per_presentation_frame(fps)``,
        exact.

    Raises:
        TypeError: If ``presentation_start_frame`` is not an exact ``int``
            (``bool`` is refused because it subclasses ``int``).
        ValueError: If ``presentation_start_frame`` is not positive, or if
            the sample rate and fps do not cross exactly (see
            :func:`samples_per_presentation_frame`).
    """
    if type(presentation_start_frame) is not int:
        got = type(presentation_start_frame).__name__
        raise TypeError(f"presentation_start_frame must be an int, got {got}")
    if presentation_start_frame < 1:
        raise ValueError(f"presentation_start_frame must be >= 1, got {presentation_start_frame}")
    return (presentation_start_frame - 1) * samples_per_presentation_frame(fps)
