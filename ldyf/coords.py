"""The single authority for SUMO <-> Unreal spatial conversion.

DNA-03 (structural guarantee): every conversion between SUMO space and Unreal
space in this project goes through this module. No other module is permitted to
multiply by 100, negate an axis, or add 90 to an angle. If a transform bug ever
exists, it exists in exactly one place and one test file proves it.

SUMO space
    x  : metres, increasing EAST
    y  : metres, increasing NORTH
    z  : metres, increasing UP
    angle: degrees, compass convention -- 0 = NORTH, 90 = EAST, clockwise.

Unreal space
    X  : centimetres, increasing EAST
    Y  : centimetres, increasing SOUTH   (left-handed; SUMO north maps to -Y)
    Z  : centimetres, increasing UP
    yaw: degrees, 0 = +X, increasing toward +Y

Derivation of the yaw rule
    SUMO 90 (east)  -> unit (1, 0) SUMO -> (+X, 0) Unreal      -> yaw   0
    SUMO  0 (north) -> unit (0, 1) SUMO -> (0, -Y) Unreal      -> yaw -90
    SUMO 180 (south)-> unit (0,-1) SUMO -> (0, +Y) Unreal      -> yaw  90
    therefore  yaw = sumo_angle - 90, normalised to (-180, 180].
"""

from __future__ import annotations

from dataclasses import dataclass

# The only place this constant is allowed to appear.
METRES_TO_UNREAL_UNITS = 100.0


def normalise_deg(a: float) -> float:
    """Normalise degrees into the half-open interval (-180, 180]."""
    a = a % 360.0
    if a > 180.0:
        a -= 360.0
    # -180 folds onto +180 so the interval is half-open and round-trips exactly.
    if a == -180.0:
        a = 180.0
    return a


@dataclass(frozen=True)
class SumoPose:
    x: float
    y: float
    z: float
    angle: float  # compass degrees, 0 = north, clockwise


@dataclass(frozen=True)
class UnrealPose:
    x: float
    y: float
    z: float
    yaw: float  # degrees, 0 = +X


def sumo_to_unreal(p: SumoPose) -> UnrealPose:
    """Convert a SUMO pose to an Unreal pose. The only forward transform."""
    return UnrealPose(
        x=p.x * METRES_TO_UNREAL_UNITS,
        y=-p.y * METRES_TO_UNREAL_UNITS,
        z=p.z * METRES_TO_UNREAL_UNITS,
        yaw=normalise_deg(p.angle - 90.0),
    )


def unreal_to_sumo(p: UnrealPose) -> SumoPose:
    """Convert an Unreal pose back to SUMO. The only inverse transform.

    Exists so the forward transform can be proven invertible by test rather
    than by inspection.
    """
    return SumoPose(
        x=p.x / METRES_TO_UNREAL_UNITS,
        y=-p.y / METRES_TO_UNREAL_UNITS,
        z=p.z / METRES_TO_UNREAL_UNITS,
        angle=(p.yaw + 90.0) % 360.0,
    )


def sumo_heading_unit_vector(angle_deg: float) -> tuple[float, float]:
    """The SUMO-space unit vector a compass angle points along.

    Used by the tests to check the yaw rule against direction rather than
    against itself.
    """
    import math

    r = math.radians(angle_deg)
    # compass: 0 = north = +y, 90 = east = +x
    return (math.sin(r), math.cos(r))


def unreal_yaw_unit_vector(yaw_deg: float) -> tuple[float, float]:
    """The Unreal-space unit vector a yaw points along."""
    import math

    r = math.radians(yaw_deg)
    return (math.cos(r), math.sin(r))
