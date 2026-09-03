"""Proof that the SUMO <-> Unreal transform is correct.

These tests deliberately avoid restating the formula. A test that asserts
`yaw == angle - 90` proves only that the author typed the same thing twice.
Instead the yaw rule is checked against *direction*: the Unreal heading vector
must point the same physical way as the SUMO heading vector, after the known
axis mapping (east -> +X, north -> -Y).
"""

from __future__ import annotations

import math

import pytest

from ldyf.coords import (
    SumoPose,
    UnrealPose,
    normalise_deg,
    sumo_heading_unit_vector,
    sumo_to_unreal,
    unreal_to_sumo,
    unreal_yaw_unit_vector,
)


# --- axis mapping ---------------------------------------------------------

def test_east_is_plus_x():
    u = sumo_to_unreal(SumoPose(10.0, 0.0, 0.0, 90.0))
    assert u.x == pytest.approx(1000.0)
    assert u.y == pytest.approx(0.0)


def test_north_is_minus_y():
    u = sumo_to_unreal(SumoPose(0.0, 10.0, 0.0, 0.0))
    assert u.y == pytest.approx(-1000.0)


def test_up_is_plus_z():
    u = sumo_to_unreal(SumoPose(0.0, 0.0, 3.5, 0.0))
    assert u.z == pytest.approx(350.0)


# --- the yaw rule, checked against direction ------------------------------

@pytest.mark.parametrize("angle", [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0, 359.0, 12.34])
def test_yaw_points_the_same_physical_direction(angle):
    """The heart of the proof.

    Take the direction SUMO says the vehicle faces, map that *vector* into
    Unreal space using only the axis rule, and require that the yaw the
    transform produced points along it.
    """
    sx, sy = sumo_heading_unit_vector(angle)
    expected_x, expected_y = sx, -sy          # axis rule only, no angle maths

    yaw = sumo_to_unreal(SumoPose(0.0, 0.0, 0.0, angle)).yaw
    got_x, got_y = unreal_yaw_unit_vector(yaw)

    assert got_x == pytest.approx(expected_x, abs=1e-9)
    assert got_y == pytest.approx(expected_y, abs=1e-9)


def test_a_wrong_yaw_rule_would_fail_this_test():
    """Guard against the test being vacuous.

    The most plausible wrong rule (yaw = angle + 90) must be rejected by the
    same direction check, otherwise the test above proves nothing.
    """
    angle = 30.0
    sx, sy = sumo_heading_unit_vector(angle)
    wrong_x, wrong_y = unreal_yaw_unit_vector(normalise_deg(angle + 90.0))
    assert not (
        math.isclose(wrong_x, sx, abs_tol=1e-9)
        and math.isclose(wrong_y, -sy, abs_tol=1e-9)
    )


# --- invertibility --------------------------------------------------------

@pytest.mark.parametrize("angle", [0.0, 1.0, 89.9, 90.0, 180.0, 270.0, 359.9])
@pytest.mark.parametrize("pos", [(0.0, 0.0, 0.0), (123.456, -78.9, 2.5), (600.0, 600.0, 0.0)])
def test_round_trip_is_identity(angle, pos):
    original = SumoPose(pos[0], pos[1], pos[2], angle)
    back = unreal_to_sumo(sumo_to_unreal(original))
    assert back.x == pytest.approx(original.x, abs=1e-9)
    assert back.y == pytest.approx(original.y, abs=1e-9)
    assert back.z == pytest.approx(original.z, abs=1e-9)
    assert back.angle % 360.0 == pytest.approx(original.angle % 360.0, abs=1e-9)


# --- normalisation --------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [(0.0, 0.0), (180.0, 180.0), (-180.0, 180.0), (181.0, -179.0), (360.0, 0.0), (-90.0, -90.0), (450.0, 90.0)],
)
def test_normalise_deg(raw, expected):
    assert normalise_deg(raw) == pytest.approx(expected)


def test_normalised_yaw_is_always_in_range():
    for a in range(0, 3600):
        yaw = sumo_to_unreal(SumoPose(0, 0, 0, a / 10.0)).yaw
        assert -180.0 < yaw <= 180.0


# --- scale ----------------------------------------------------------------

def test_metres_become_centimetres():
    u = sumo_to_unreal(SumoPose(1.0, 1.0, 1.0, 0.0))
    assert abs(u.x) == pytest.approx(100.0)
    assert abs(u.y) == pytest.approx(100.0)
    assert abs(u.z) == pytest.approx(100.0)


def test_unreal_pose_is_immutable():
    u = UnrealPose(1.0, 2.0, 3.0, 4.0)
    with pytest.raises(Exception):
        u.x = 9.0  # type: ignore[misc]
