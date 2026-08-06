"""Material and social stress accumulate into pressure for institutions to act."""

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

_LOWER_RESIDUE_LIMIT = math.nextafter(0.0, -math.inf)
"""The largest negative float that can only be rounding residue below zero."""

_UPPER_RESIDUE_LIMIT = math.nextafter(1.0, math.inf)
"""The smallest float above one that can only be rounding residue above it."""


def _validate_weight(value: float, field_name: str) -> float:
    """Validate an institutional weight and return it as a float.

    Weights are relative importances rather than normalized scores, so unlike a
    rate they are not capped at 1.0 -- only required to be a real, finite,
    non-negative number. What matters is their ratio, which is why weights of
    1, 1, 1 mean exactly what weights of 10, 10, 10 mean.

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


def _clamp_unit(value: float, description: str) -> float:
    """Flatten one-ULP residue outside 0.0-1.0, and refuse anything larger.

    Every quantity here is a normalized score built from values already inside
    the unit interval, so the only way a result can land outside it is the last
    bit of a division or a subtraction going the wrong way. That is a single
    ULP wide, and it is flattened.

    Anything further out is not residue. A value of 2.0 means the formula that
    produced it is wrong, or the state it read was corrupt, and silently
    reporting it as 1.0 would turn a defect into a plausible-looking simulation
    outcome nobody could later distinguish from a district genuinely at the
    limit. So the bound is exactly one ULP either side and everything beyond it
    raises.

    This is deliberately a private copy of the same rule Phase 6 applies rather
    than an import of it. Concrete systems do not depend on one another, and a
    shared private helper between two of them would be exactly that dependency
    wearing a different hat.

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


@dataclass(frozen=True, slots=True)
class _StagedUpdate:
    """One district's computed institutional update, held until every one is ready."""

    district_id: EntityId
    scarcity: float
    fear: float
    trust: float
    distrust: float
    social_stability: float
    target_pressure: float
    previous_pressure: float
    new_pressure: float


class InstitutionalPressureSystem(BaseSystem):
    """Turns settled material and social stress into pressure for institutions to act.

    Runs last, after the social layer, so what it reads is a district's final
    position for the tick: the scarcity ScarcitySystem recorded and the fear
    and trust SocialStabilitySystem just wrote.

    **Three inputs, not one.** Scarcity, fear, and distrust say different
    things about different moments. Scarcity is the district's forward-looking
    material exposure right now; fear and distrust are social state accumulated
    over previous ticks. Keeping all three lets a sudden shortage start pushing
    on institutions immediately, and lets pressure stay high after the shortage
    passes while confidence is still damaged. That is where the path dependence
    comes from -- not from any hidden history inside this system, which holds
    none.

    **Why the change is gradual.** Pressure moves a configured fraction of the
    way toward its target each tick. Institutions are slow: they do not mobilize
    the instant one harvest fails, and they do not stand down the instant one
    harvest succeeds. The stored ``District.institutional_pressure`` is the
    entire memory, which is what keeps this system stateless and the behaviour
    reproducible from world state alone.

    **What it does not do.** It records how much pressure a district is under
    and decides nothing with it. Walls, boundaries, isolation, and laws are
    neither read nor written -- not even consulted. Turning pressure into a
    decision belongs to a later phase and this system deliberately stops short
    of it.

    The weights and the response rate are simulation parameters chosen to
    produce legible behaviour across an episode. They are not measured
    constants, and no output here should be read as a claim about how real
    institutions respond to hardship.

    The system consumes no randomness and holds no state between ticks.
    """

    __slots__ = (
        "_distrust_weight",
        "_fear_weight",
        "_response_rate",
        "_scarcity_weight",
    )

    def __init__(
        self,
        scarcity_weight: float = 1.0,
        fear_weight: float = 1.0,
        distrust_weight: float = 1.0,
        response_rate: float = 0.20,
    ) -> None:
        """Create an institutional pressure system.

        Args:
            scarcity_weight: How heavily current material exposure counts.
                Finite and not negative.
            fear_weight: How heavily accumulated alarm counts. Finite and not
                negative.
            distrust_weight: How heavily lost confidence counts. Finite and not
                negative.
            response_rate: The share of the remaining gap between a district's
                current pressure and its target that closes each tick. The
                default of 0.20 closes a fifth of the gap per tick. Zero
                freezes institutional pressure; one snaps it to the target.

        Raises:
            TypeError: If any argument is not a real number, or is a bool.
            ValueError: If a weight is negative or non-finite, if all three
                weights are zero, or if the response rate falls outside
                0.0-1.0.
        """
        self._scarcity_weight = _validate_weight(scarcity_weight, "scarcity_weight")
        self._fear_weight = _validate_weight(fear_weight, "fear_weight")
        self._distrust_weight = _validate_weight(distrust_weight, "distrust_weight")
        if (
            self._scarcity_weight == 0.0
            and self._fear_weight == 0.0
            and self._distrust_weight == 0.0
        ):
            raise ValueError(
                "scarcity_weight, fear_weight, and distrust_weight must not all be zero, "
                "or institutional pressure would have nothing to measure"
            )
        self._response_rate = validate_unit_scalar(response_rate, "response_rate")

    @property
    def scarcity_weight(self) -> float:
        """How heavily current material exposure counts toward the target."""
        return self._scarcity_weight

    @property
    def fear_weight(self) -> float:
        """How heavily accumulated alarm counts toward the target."""
        return self._fear_weight

    @property
    def distrust_weight(self) -> float:
        """How heavily lost confidence counts toward the target."""
        return self._distrust_weight

    @property
    def response_rate(self) -> float:
        """Share of the remaining gap to the target that closes each tick."""
        return self._response_rate

    def update(self, world: "World", bus: EventBus) -> None:
        """Move every populated district's institutional pressure toward its target.

        Districts are read in sorted identifier order and every update is
        computed in full before any is written. Nothing here makes one
        district's result depend on another's -- there is no institutional
        coordination between districts in this phase -- but staging keeps that
        independence a property of the code rather than of the order it happens
        to run in, and it is what makes a corrupted district abort the whole
        update without having already changed a healthy one.

        Args:
            world: The world whose districts are scored.
            bus: The bus on which institutional pressure events are published.

        Raises:
            TypeError: If a district's stored scarcity, fear, trust, or
                institutional pressure is not a real number.
            ValueError: If any of those is not finite or lies outside 0.0-1.0,
                or if a computed value is invalid.
        """
        staged = [
            self._compute(world.districts[district_id])
            for district_id in sorted(world.districts)
            if world.districts[district_id].population > 0
        ]

        changed = [update for update in staged if update.new_pressure != update.previous_pressure]
        if not changed:
            return

        for update in changed:
            world.districts[update.district_id].institutional_pressure = update.new_pressure

        for update in changed:
            bus.publish(
                Event(
                    tick=world.tick,
                    type=EventType.INSTITUTIONAL_PRESSURE_CHANGED,
                    payload=self._build_payload(update),
                    source_id=update.district_id,
                )
            )

    def _compute(self, district: District) -> _StagedUpdate:
        """Work out one district's institutional update without touching the world."""
        scarcity, fear, trust, previous = self._read_inputs(district)

        distrust = _clamp_unit(1.0 - trust, f"distrust of {district.id!r}")
        target = self._target_pressure(district, scarcity, fear, distrust)
        new_pressure = _clamp_unit(
            previous + self._response_rate * (target - previous),
            f"institutional pressure of {district.id!r}",
        )

        return _StagedUpdate(
            district_id=district.id,
            scarcity=scarcity,
            fear=fear,
            trust=trust,
            distrust=distrust,
            social_stability=_clamp_unit(
                (trust + (1.0 - fear)) / 2.0, f"social stability of {district.id!r}"
            ),
            target_pressure=target,
            previous_pressure=previous,
            new_pressure=new_pressure,
        )

    @staticmethod
    def _read_inputs(district: District) -> tuple[float, float, float, float]:
        """Return the district's stored inputs, refusing corrupted state.

        District fields stay mutable after construction, so the entity's own
        validation only speaks for the moment the district was built. Anything
        that overwrote one of these afterwards is exactly what this has to
        catch.

        Each value is handed to the validator exactly as found, never converted
        first. A conversion would repair the very corruption being looked for:
        ``float(True)`` is a perfectly ordinary 1.0 and ``float("0.5")`` a
        perfectly ordinary 0.5, so the validator would be shown a clean number
        and would have nothing to object to -- and a district reading as
        maximally alarmed would be indistinguishable from one genuinely so.

        Raises:
            TypeError: If any stored value is not a real number, or is a bool.
            ValueError: If any is not finite or lies outside 0.0-1.0.
        """
        return (
            validate_unit_scalar(district.scarcity, f"scarcity of {district.id!r}"),
            validate_unit_scalar(district.fear, f"fear of {district.id!r}"),
            validate_unit_scalar(district.trust, f"trust of {district.id!r}"),
            validate_unit_scalar(
                district.institutional_pressure,
                f"institutional pressure of {district.id!r}",
            ),
        )

    def _target_pressure(
        self, district: District, scarcity: float, fear: float, distrust: float
    ) -> float:
        """Blend the three stresses into the pressure this district is heading for.

        Only the ratio of the weights matters, so the three are first divided by
        the largest of them. That makes the arithmetic safe at any finite scale:
        weights of 1e308 each would otherwise sum to infinity and drive the
        result to zero, and weights of 5e-324 each would underflow their
        products to zero and do the same -- both of which would report a
        district in crisis as untroubled.

        After normalizing, the largest weight is exactly 1.0 and the others lie
        in 0.0-1.0, so the denominator is between 1 and 3 and neither overflow
        nor underflow is reachable.
        """
        scale = max(self._scarcity_weight, self._fear_weight, self._distrust_weight)
        normalized_scarcity_weight = self._scarcity_weight / scale
        normalized_fear_weight = self._fear_weight / scale
        normalized_distrust_weight = self._distrust_weight / scale

        denominator = (
            normalized_scarcity_weight + normalized_fear_weight + normalized_distrust_weight
        )
        numerator = (
            normalized_scarcity_weight * scarcity
            + normalized_fear_weight * fear
            + normalized_distrust_weight * distrust
        )
        return _clamp_unit(
            numerator / denominator, f"target institutional pressure of {district.id!r}"
        )

    def _build_payload(self, update: _StagedUpdate) -> dict[str, FrozenJsonValue]:
        """Describe one institutional update as strictly JSON-compatible primitives.

        The configuration is reported alongside the values because the target is
        meaningless without it: the same three stresses produce a different
        target under a different weighting, and a reader of the recorded history
        would otherwise be unable to reconstruct why.
        """
        return {
            "district_id": update.district_id,
            "scarcity": update.scarcity,
            "fear": update.fear,
            "trust": update.trust,
            "distrust": update.distrust,
            "social_stability": update.social_stability,
            "social_strain": 1.0 - update.social_stability,
            "scarcity_weight": self._scarcity_weight,
            "fear_weight": self._fear_weight,
            "distrust_weight": self._distrust_weight,
            "response_rate": self._response_rate,
            "target_institutional_pressure": update.target_pressure,
            "previous_institutional_pressure": update.previous_pressure,
            "new_institutional_pressure": update.new_pressure,
        }
