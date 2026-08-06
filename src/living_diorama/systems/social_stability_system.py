"""Economic and demographic pressure becomes fear and trust, gradually."""

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from living_diorama.entities import District, EntityId
from living_diorama.events import Event, EventBus, EventType
from living_diorama.events.event import FrozenJsonValue
from living_diorama.systems._pressure import validate_unit_scalar
from living_diorama.systems._resource_config import require_finite
from living_diorama.systems.base_system import BaseSystem

if TYPE_CHECKING:  # pragma: no cover - import exists for typing only
    from living_diorama.simulation.world import World


def _validate_weight(value: float, field_name: str) -> float:
    """Validate a pressure weight and return it as a float.

    Weights are relative importances rather than normalized scores, so unlike a
    rate they are not capped at 1.0 -- only required to be a real, finite,
    non-negative number. What matters is their ratio, which is why weights of
    1 and 1 mean exactly what weights of 10 and 10 mean.

    Args:
        value: The weight to check.
        field_name: Name of the field, used in error messages.

    Returns:
        The weight as a float.

    Raises:
        TypeError: If the value is not a real number, or is a bool. ``bool`` is
            rejected explicitly because it subclasses ``int``, so ``True``
            would silently mean a weight of 1.0.
        ValueError: If the weight is not finite or is negative.
    """
    if type(value) is bool or not isinstance(value, int | float):
        raise TypeError(f"{field_name} must be a real number, got {type(value).__name__}")
    weight = float(value)
    if not math.isfinite(weight):
        raise ValueError(f"{field_name} must be finite, got {weight!r}")
    if weight < 0.0:
        raise ValueError(f"{field_name} must be >= 0, got {weight}")
    return weight


_LOWER_RESIDUE_LIMIT = math.nextafter(0.0, -math.inf)
"""The largest negative float that can only be rounding residue below zero."""

_UPPER_RESIDUE_LIMIT = math.nextafter(1.0, math.inf)
"""The smallest float above one that can only be rounding residue above it."""


def _clamp_unit(value: float, description: str) -> float:
    """Flatten one-ULP residue outside 0.0-1.0, and refuse anything larger.

    Every quantity here is a normalized score built from values already inside
    the unit interval, so the only way a result can land outside it is the last
    bit of a division or a subtraction going the wrong way. That is a single
    ULP wide, and it is flattened.

    Anything further out is not residue. A value of 2.0 means the formula that
    produced it is wrong, or the state it read was corrupt, and silently
    reporting it as 1.0 would turn a defect into a plausible-looking simulation
    outcome that nobody could later distinguish from a genuinely desperate
    district. So the bound is exactly one ULP either side and everything beyond
    it raises.

    Args:
        value: The computed value.
        description: What the value represents, used in the error message.

    Returns:
        The value, with at most one ULP of residue removed.

    Raises:
        ValueError: If the value is not finite, or lies more than one ULP
            outside 0.0-1.0.
    """
    require_finite(value, description)
    if value < _LOWER_RESIDUE_LIMIT or value > _UPPER_RESIDUE_LIMIT:
        raise ValueError(f"{description} must be within 0.0-1.0, got {value!r}")
    return min(1.0, max(0.0, value))


def housing_pressure(population: int, housing_capacity: int) -> float:
    """Return the share of a district's people it has no housing for.

    Zero while everybody fits, rising to one when nobody does. Expressed as a
    share of the population rather than as an absolute overspill so that it
    stays comparable with scarcity: both answer "what fraction of this district
    is in trouble", which is what makes averaging them meaningful.

    A district with no people is not overcrowded and has no share to compute,
    so callers are expected to skip it; this returns 0.0 rather than dividing
    by zero.

    Args:
        population: The district's final population for the tick.
        housing_capacity: How many people its housing holds.

    Returns:
        A value in 0.0-1.0.

    Raises:
        ValueError: If the computed value is not finite.
    """
    if population <= 0:
        return 0.0

    unhoused_share = (float(population) - float(housing_capacity)) / float(population)
    if unhoused_share <= 0.0:
        # Spare housing is not negative pressure. A district with room to grow
        # is simply not overcrowded, so the floor at zero is a statement about
        # the domain rather than the tidying-up of a rounding error -- which is
        # why it is applied here and not left to the residue guard below, whose
        # job is to refuse values this far out of range.
        return 0.0
    return _clamp_unit(unhoused_share, "housing pressure")


def social_stability_of(fear: float, trust: float) -> float:
    """Return the derived stability score for a district's social state.

    The mean of how much a district trusts and how much it is not afraid. This
    is a reporting value only: it is derived on demand for events and tests and
    is deliberately not stored, because the persistent social state of a
    district is its fear and its trust, and a stored average would be a third
    thing that could fall out of step with them.

    Args:
        fear: Normalized fear, 0.0-1.0.
        trust: Normalized trust, 0.0-1.0.

    Returns:
        A value in 0.0-1.0.

    Raises:
        ValueError: If the computed value is not finite.
    """
    return _clamp_unit((trust + (1.0 - fear)) / 2.0, "social stability")


@dataclass(frozen=True, slots=True)
class _StagedUpdate:
    """One district's computed social update, held back until every one is ready."""

    district_id: EntityId
    scarcity_pressure: float
    housing_pressure: float
    social_pressure: float
    previous_fear: float
    target_fear: float
    new_fear: float
    previous_trust: float
    target_trust: float
    new_trust: float


class SocialStabilitySystem(BaseSystem):
    """Turns scarcity and overcrowding into gradual movement in fear and trust.

    Runs after the resource and demographic systems, so what it reads is a
    district's settled position for the tick: the scarcity ScarcitySystem
    recorded, and the population MigrationSystem left behind.

    **What social pressure means here.** Two things weigh on a district in this
    model: how much of its projected need it cannot cover, and how much of its
    population it cannot house. Both are already expressed as a fraction of the
    district in trouble, so they combine into one normalized score by weighted
    average. That score is this simulation's definition of pressure and nothing
    more. The weights and the response rate are simulation parameters chosen to
    produce legible behaviour over an episode; they are not measured social
    constants, and no output of this system should be read as a claim about how
    real populations respond to hardship.

    **Why the change is gradual.** Fear and trust move a configured fraction of
    the way toward their targets each tick rather than jumping to them. That is
    what makes the social layer have a memory: a district that has been afraid
    for a long time does not become calm the moment one harvest improves, and a
    single bad tick does not collapse a district that was previously secure.
    Where a district ends up therefore depends on the path it took, which is the
    property the series depends on.

    **What it does not do.** It records how a district feels; it decides
    nothing. Walls, boundaries, laws, isolation, and institutional pressure are
    all read-only here -- several of them are not even read. Turning fear into
    action belongs to a later phase, and this system deliberately stops short
    of it.

    The system consumes no randomness and holds no state between ticks.
    """

    __slots__ = ("_housing_pressure_weight", "_response_rate", "_scarcity_weight")

    def __init__(
        self,
        scarcity_weight: float = 1.0,
        housing_pressure_weight: float = 1.0,
        response_rate: float = 0.25,
    ) -> None:
        """Create a social stability system.

        Args:
            scarcity_weight: How heavily unmet projected need counts toward
                social pressure. Finite and not negative.
            housing_pressure_weight: How heavily overcrowding counts toward
                social pressure. Finite and not negative.
            response_rate: The share of the remaining gap between a district's
                current social state and its target that closes each tick. The
                default of 0.25 closes a quarter of the gap per tick. Zero
                freezes social state; one snaps it to the target immediately.

        Raises:
            TypeError: If any argument is not a real number, or is a bool.
            ValueError: If a weight is negative or non-finite, if both weights
                are zero, or if the response rate falls outside 0.0-1.0.
        """
        self._scarcity_weight = _validate_weight(scarcity_weight, "scarcity_weight")
        self._housing_pressure_weight = _validate_weight(
            housing_pressure_weight, "housing_pressure_weight"
        )
        if self._scarcity_weight == 0.0 and self._housing_pressure_weight == 0.0:
            raise ValueError(
                "scarcity_weight and housing_pressure_weight must not both be zero, "
                "or social pressure would have nothing to measure"
            )
        self._response_rate = validate_unit_scalar(response_rate, "response_rate")

    @property
    def scarcity_weight(self) -> float:
        """How heavily unmet projected need counts toward social pressure."""
        return self._scarcity_weight

    @property
    def housing_pressure_weight(self) -> float:
        """How heavily overcrowding counts toward social pressure."""
        return self._housing_pressure_weight

    @property
    def response_rate(self) -> float:
        """Share of the remaining gap to the target that closes each tick."""
        return self._response_rate

    def update(self, world: "World", bus: EventBus) -> None:
        """Move every populated district's fear and trust toward its pressure.

        Districts are read in sorted identifier order and their updates are
        computed in full before any is written. Nothing in this phase makes one
        district's result depend on another's -- there is no social contagion
        between neighbours here -- but staging keeps that independence a
        property of the code rather than of the order it happens to run in, and
        makes it impossible for a later change to introduce order sensitivity
        unnoticed.

        Args:
            world: The world whose districts are scored.
            bus: The bus on which social stability events are published.

        Raises:
            ValueError: If a district's stored scarcity is not finite or lies
                outside 0.0-1.0, or if a computed value is not finite.
        """
        staged = [
            self._compute(world.districts[district_id])
            for district_id in sorted(world.districts)
            if world.districts[district_id].population > 0
        ]

        changed = [update for update in staged if self._has_changed(update)]
        if not changed:
            return

        for update in changed:
            district = world.districts[update.district_id]
            district.fear = update.new_fear
            district.trust = update.new_trust

        for update in changed:
            bus.publish(
                Event(
                    tick=world.tick,
                    type=EventType.SOCIAL_STABILITY_CHANGED,
                    payload=_build_payload(update),
                    source_id=update.district_id,
                )
            )

    def _compute(self, district: District) -> _StagedUpdate:
        """Work out one district's social update without touching the world."""
        scarcity_pressure = self._read_scarcity(district)
        crowding = housing_pressure(district.population, district.housing_capacity)
        pressure = self._combine(scarcity_pressure, crowding)

        previous_fear, previous_trust = self._read_social_state(district)
        target_fear = pressure
        target_trust = _clamp_unit(1.0 - pressure, f"target trust of {district.id!r}")

        return _StagedUpdate(
            district_id=district.id,
            scarcity_pressure=scarcity_pressure,
            housing_pressure=crowding,
            social_pressure=pressure,
            previous_fear=previous_fear,
            target_fear=target_fear,
            new_fear=self._approach(previous_fear, target_fear, f"fear of {district.id!r}"),
            previous_trust=previous_trust,
            target_trust=target_trust,
            new_trust=self._approach(previous_trust, target_trust, f"trust of {district.id!r}"),
        )

    @staticmethod
    def _read_scarcity(district: District) -> float:
        """Return the district's stored scarcity, refusing corrupted state.

        Scarcity is the forward-looking exposure ScarcitySystem recorded: the
        share of next tick's projected demand the district cannot cover from
        what it holds now. It is read, never recomputed, so that the social
        layer and the economic layer can never disagree about how bad things
        are.

        The stored value is handed to the validator exactly as found, never
        converted first. A conversion would repair the very corruption being
        looked for: ``float(True)`` is a perfectly ordinary 1.0, and
        ``float("0.5")`` is a perfectly ordinary 0.5, so the validator would be
        shown a clean number and would have nothing to object to.

        Raises:
            TypeError: If the stored value is not a real number, or is a bool.
            ValueError: If it is not finite or is outside 0.0-1.0. The entity
                forbids all of these at construction, so any of them here can
                only mean the field was overwritten afterwards.
        """
        return validate_unit_scalar(district.scarcity, f"scarcity of {district.id!r}")

    @staticmethod
    def _read_social_state(district: District) -> tuple[float, float]:
        """Return the district's stored fear and trust, refusing corrupted state.

        District fields stay mutable after construction, so the entity's own
        validation only speaks for the moment the district was built. A fear of
        100.0 -- or of ``True``, or of ``"0.5"`` -- reaching this system means
        something wrote it there afterwards, and quietly reading any of them as
        an ordinary number would produce a district that looks merely
        frightened rather than broken.

        Both values are handed to the validator exactly as found, for the same
        reason: converting first would turn a corrupted ``True`` or ``"0.5"``
        into a valid-looking float before anything had a chance to reject it.

        Raises:
            TypeError: If either value is not a real number, or is a bool.
            ValueError: If either is not finite or is outside 0.0-1.0.
        """
        return (
            validate_unit_scalar(district.fear, f"fear of {district.id!r}"),
            validate_unit_scalar(district.trust, f"trust of {district.id!r}"),
        )

    def _combine(self, scarcity_pressure: float, crowding: float) -> float:
        """Blend the two pressures into one normalized score.

        Only the ratio of the weights matters, so the pair is first divided by
        the larger of them. That makes the arithmetic safe at any finite scale:
        weights of 1e308 each would otherwise sum to infinity and drive the
        result to zero, and weights of 5e-324 each would underflow their
        products to zero and do the same -- both of which would silently report
        a district in crisis as untroubled.

        After normalizing, the larger weight is exactly 1.0 and the smaller is
        somewhere in 0.0-1.0, so the denominator is between 1 and 2 and neither
        overflow nor underflow is reachable.
        """
        scale = max(self._scarcity_weight, self._housing_pressure_weight)
        normalized_scarcity_weight = self._scarcity_weight / scale
        normalized_housing_weight = self._housing_pressure_weight / scale

        denominator = normalized_scarcity_weight + normalized_housing_weight
        numerator = (
            normalized_scarcity_weight * scarcity_pressure + normalized_housing_weight * crowding
        )
        return _clamp_unit(numerator / denominator, "social pressure")

    def _approach(self, previous: float, target: float, description: str) -> float:
        """Move a value part of the way toward its target and keep it in range."""
        return _clamp_unit(previous + self._response_rate * (target - previous), description)

    @staticmethod
    def _has_changed(update: _StagedUpdate) -> bool:
        """Return whether this update actually moves a district's social state.

        Compared exactly, because the question is simply whether the value that
        would be stored differs from the one already stored. Any threshold here
        would silently convert a small positive response rate into a zero one:
        a rate of 1e-10 produces real, monotonic movement toward the target,
        and suppressing it would freeze the district forever while appearing to
        be configured to move.

        If a computation rounds to the same IEEE-754 float the district already
        holds, then nothing changed, and no event is published.
        """
        return update.new_fear != update.previous_fear or update.new_trust != update.previous_trust


def _build_payload(update: _StagedUpdate) -> dict[str, FrozenJsonValue]:
    """Describe one social update as strictly JSON-compatible primitives.

    Stability and strain are included for both the previous and the new state
    because they are what a later reader most often wants and are tedious to
    recompute from fear and trust after the fact. They are derived here and
    stored nowhere.
    """
    previous_stability = social_stability_of(update.previous_fear, update.previous_trust)
    new_stability = social_stability_of(update.new_fear, update.new_trust)

    return {
        "district_id": update.district_id,
        "scarcity_pressure": update.scarcity_pressure,
        "housing_pressure": update.housing_pressure,
        "social_pressure": update.social_pressure,
        "previous_fear": update.previous_fear,
        "target_fear": update.target_fear,
        "new_fear": update.new_fear,
        "previous_trust": update.previous_trust,
        "target_trust": update.target_trust,
        "new_trust": update.new_trust,
        "previous_social_stability": previous_stability,
        "new_social_stability": new_stability,
        "previous_social_strain": 1.0 - previous_stability,
        "new_social_strain": 1.0 - new_stability,
    }
