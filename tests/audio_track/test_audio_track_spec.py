"""Unit tests for the Phase 30 audio track policy: the onset law and its rail."""

import pytest

from living_diorama.audio_track.audio_track_spec import (
    MAX_AUDIO_TRACK_SAMPLES,
    samples_per_presentation_frame,
    speech_start_sample,
)
from living_diorama.voice.voice_spec import samples_per_presentation_frame as voice_crossing


def test_speech_start_sample_frame_one_is_zero() -> None:
    """Frame 1's onset is sample 0."""
    assert speech_start_sample(1, 24) == 0


def test_speech_start_sample_frame_twenty_five_at_fps_24() -> None:
    """Frame 25 at fps 24 is sample 24,000."""
    assert speech_start_sample(25, 24) == 24000


def test_speech_start_sample_scales_with_frame() -> None:
    """The onset scales linearly with the frame."""
    assert speech_start_sample(361, 24) == 360000


def test_a_zero_presentation_start_frame_is_refused() -> None:
    """A zero presentation_start_frame is refused."""
    with pytest.raises(ValueError, match=">= 1"):
        speech_start_sample(0, 24)


def test_a_negative_presentation_start_frame_is_refused() -> None:
    """A negative presentation_start_frame is refused."""
    with pytest.raises(ValueError, match=">= 1"):
        speech_start_sample(-1, 24)


def test_a_float_presentation_start_frame_is_refused() -> None:
    """A float presentation_start_frame is refused."""
    with pytest.raises(TypeError):
        speech_start_sample(1.0, 24)  # type: ignore[arg-type]


def test_a_bool_presentation_start_frame_is_refused() -> None:
    """A bool presentation_start_frame is refused."""
    with pytest.raises(TypeError):
        speech_start_sample(True, 24)  # type: ignore[arg-type]


def test_a_non_divisible_fps_propagates_the_crossing_refusal() -> None:
    """A non-divisible fps propagates the crossing law's own refusal."""
    with pytest.raises(ValueError, match="do not"):
        speech_start_sample(2, 7)


def test_the_crossing_law_is_the_imported_one_not_a_copy() -> None:
    """samples_per_presentation_frame is the Phase 28-owned function, re-exported."""
    assert samples_per_presentation_frame is voice_crossing


def test_max_audio_track_samples_is_the_frozen_phase30_constant() -> None:
    """MAX_AUDIO_TRACK_SAMPLES is the frozen Phase 30 constant."""
    assert MAX_AUDIO_TRACK_SAMPLES == 1_000_000_000
