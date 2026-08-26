"""Unit tests for the Phase 28 voice policy: identity constants and clock law.

These tests call ``samples_per_presentation_frame`` and
``capacity_samples_for_window`` directly, as plain functions -- never through
a document or a gate. The non-divisible-fps refusal is exercised here and
only here: under the current locked Motion & Time contract, a full document
chain can never carry a non-divisible fps and still pass the Phase 27 gate
(the pinned ``motion_time_sha256`` check refuses first), so this law's only
reachable coverage is a direct unit call.
"""

from typing import Any

import pytest

from living_diorama.voice import voice_spec


def test_voice_block_carries_exactly_the_fifteen_pinned_fields() -> None:
    """Voice block carries exactly the fifteen pinned fields."""
    assert set(voice_spec.VOICE_BLOCK) == {
        "engine",
        "engine_version",
        "g2p",
        "g2p_version",
        "model_repository",
        "model_revision",
        "model_weights_sha256",
        "model_config_sha256",
        "voice",
        "voice_pack_sha256",
        "lang_code",
        "speed_percent",
        "sample_rate_hz",
        "channels",
        "seed",
    }


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("engine", "kokoro"),
        ("engine_version", "0.9.4"),
        ("g2p", "misaki"),
        ("g2p_version", "0.9.4"),
        ("model_repository", "hexgrad/Kokoro-82M"),
        ("model_revision", "f3ff3571791e39611d31c381e3a41a3af07b4987"),
        (
            "model_weights_sha256",
            "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4",
        ),
        (
            "model_config_sha256",
            "5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f",
        ),
        ("voice", "af_heart"),
        (
            "voice_pack_sha256",
            "0ab5709b8ffab19bfd849cd11d98f75b60af7733253ad0d67b12382a102cb4ff",
        ),
        ("lang_code", "a"),
        ("speed_percent", 100),
        ("sample_rate_hz", 24_000),
        ("channels", 1),
        ("seed", 0),
    ],
)
def test_each_pinned_field_has_its_frozen_value(field: str, expected: Any) -> None:
    """Each pinned field has its frozen value."""
    assert voice_spec.VOICE_BLOCK[field] == expected


def test_no_pinned_field_is_a_float() -> None:
    """No pinned field is a float."""
    for value in voice_spec.VOICE_BLOCK.values():
        assert type(value) is not float


def test_the_voice_block_is_immutable() -> None:
    """The voice block is immutable."""
    with pytest.raises(TypeError):
        voice_spec.VOICE_BLOCK["engine"] = "other"  # type: ignore[index]


def test_the_canonical_pairing_resolves_to_one_thousand_samples_per_frame() -> None:
    """The canonical pairing resolves to one thousand samples per frame."""
    result = voice_spec.samples_per_presentation_frame(24)
    assert result == 1_000
    assert type(result) is int


def test_a_float_fps_is_refused_even_when_numerically_valid() -> None:
    """A float fps is refused even when numerically valid.

    ``24.0`` is numerically the canonical fps, but the public helper must
    refuse it outright rather than rely on some later, source-verified path
    to sanitize it -- the exact V1 defect this test closes.
    """
    with pytest.raises(TypeError, match="must be an int"):
        voice_spec.samples_per_presentation_frame(24.0)


def test_a_bool_fps_is_refused() -> None:
    """A bool fps is refused.

    ``True`` is numerically ``1`` and would otherwise silently pass every
    positivity and divisibility check, since ``bool`` subclasses ``int``.
    """
    with pytest.raises(TypeError, match="must be an int"):
        voice_spec.samples_per_presentation_frame(True)
    with pytest.raises(TypeError, match="must be an int"):
        voice_spec.samples_per_presentation_frame(False)


@pytest.mark.parametrize(
    "fps", [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 16, 20, 24, 25, 30, 40, 48, 50, 60]
)
def test_every_divisor_of_the_pinned_rate_resolves_exactly(fps: int) -> None:
    """Every divisor of the pinned rate resolves exactly."""
    result = voice_spec.samples_per_presentation_frame(fps)
    assert result * fps == voice_spec.SAMPLE_RATE_HZ
    assert type(result) is int


@pytest.mark.parametrize("fps", [7, 9, 11, 13, 14, 17, 19, 23, 26, 27, 29, 700])
def test_a_non_divisible_fps_is_refused(fps: int) -> None:
    """A non divisible fps is refused."""
    with pytest.raises(ValueError, match="not evenly divisible"):
        voice_spec.samples_per_presentation_frame(fps)


def test_a_zero_fps_is_refused() -> None:
    """A zero fps is refused."""
    with pytest.raises(ValueError):
        voice_spec.samples_per_presentation_frame(0)


@pytest.mark.parametrize(
    ("window_frames", "fps", "expected"),
    [
        (192, 24, 192_000),
        (144, 24, 144_000),
        (360, 24, 360_000),
        (1, 24, 1_000),
    ],
)
def test_capacity_samples_for_window_resolves_exactly(
    window_frames: int, fps: int, expected: int
) -> None:
    """Capacity samples for window resolves exactly."""
    result = voice_spec.capacity_samples_for_window(window_frames, fps)
    assert result == expected
    assert type(result) is int


def test_a_float_window_frames_is_refused_even_when_numerically_valid() -> None:
    """A float window frames is refused even when numerically valid."""
    with pytest.raises(TypeError, match="window_frames must be an int"):
        voice_spec.capacity_samples_for_window(144.0, 24)


def test_a_bool_window_frames_is_refused() -> None:
    """A bool window frames is refused."""
    with pytest.raises(TypeError, match="window_frames must be an int"):
        voice_spec.capacity_samples_for_window(True, 24)


def test_a_float_fps_is_refused_through_capacity_samples_for_window() -> None:
    """A float fps is refused through capacity samples for window.

    ``capacity_samples_for_window`` does not duplicate the fps type check --
    it delegates to :func:`samples_per_presentation_frame`, which already
    refuses a non-int fps. This proves the refusal actually propagates.
    """
    with pytest.raises(TypeError, match="fps must be an int"):
        voice_spec.capacity_samples_for_window(144, 24.0)


def test_capacity_samples_for_window_refuses_a_non_positive_length() -> None:
    """Capacity samples for window refuses a non positive length."""
    with pytest.raises(ValueError, match="window_frames"):
        voice_spec.capacity_samples_for_window(0, 24)


def test_capacity_samples_for_window_refuses_a_negative_length() -> None:
    """Capacity samples for window refuses a negative length."""
    with pytest.raises(ValueError, match="window_frames"):
        voice_spec.capacity_samples_for_window(-1, 24)


def test_capacity_samples_for_window_propagates_the_divisibility_refusal() -> None:
    """Capacity samples for window propagates the divisibility refusal."""
    with pytest.raises(ValueError, match="not evenly divisible"):
        voice_spec.capacity_samples_for_window(10, 7)


def test_max_voice_capacity_samples_is_the_frozen_phase28_constant() -> None:
    """Max voice capacity samples is the frozen phase28 constant.

    Deliberately tests only this layer's own frozen contract -- not an
    equality against Phase 27's ``MAX_PRESENTATION_FRAME``. The two values
    are comparable by hand in magnitude (documented in
    ``voice_spec.MAX_VOICE_CAPACITY_SAMPLES``'s own docstring), but that
    comparison is explanatory, never acceptance truth: this rail is an
    independent standalone plausibility ceiling, not a value derived from,
    or coupled to, a different phase's rail.
    """
    assert voice_spec.MAX_VOICE_CAPACITY_SAMPLES == 1_000_000_000
