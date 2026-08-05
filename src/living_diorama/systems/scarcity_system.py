"""Each district records how exposed it is to the demand coming next tick."""

from collections.abc import Mapping
from typing import TYPE_CHECKING

from living_diorama.entities import ResourceType
from living_diorama.events import Event, EventBus, EventType
from living_diorama.events.event import FrozenJsonValue
from living_diorama.systems._pressure import shortfall_breakdown, shortfall_ratio
from living_diorama.systems._resource_config import (
    RESOURCE_ORDER,
    require_finite,
    validate_allocation,
)
from living_diorama.systems.base_system import BaseSystem

if TYPE_CHECKING:  # pragma: no cover - import exists for typing only
    from living_diorama.simulation.world import World


class ScarcitySystem(BaseSystem):
    """Writes each district's scarcity from the state it ends the tick in.

    Runs last of the resource systems, after production, consumption, sharing,
    and migration, so the number it records describes the district as it
    actually stands rather than as it started. That ordering is the point: a
    district that was starving at the top of the tick but was fed by a
    neighbour, or that shed the people it could not feed, should not be scored
    as though neither had happened.

    **The measure is forward-looking.** Scarcity is the fraction of the
    district's *projected* demand -- what its population will need next tick --
    that its *remaining* stock cannot cover. It is measured per resource kind
    and summed, so a glut of one resource never disguises a famine in another.
    Nothing left and mouths to feed scores one; a full tick of supply in hand
    scores zero; a district with no projected demand at all scores zero,
    because emptiness is not hardship.

    **It is not a second reading of this tick's hunger.** ConsumptionSystem
    already reports what went unmet while people ate, as ``unmet_total``. This
    reports something else, and the two can disagree sharply. A district that
    began the tick with exactly one tick of supply meets its needs in full --
    ``unmet_total`` is zero -- and ends holding nothing, so its scarcity is
    one. Both are correct: nobody went hungry today, and there is nothing left
    for tomorrow. The payload names every projected quantity as such so the
    distinction is visible in the recorded history rather than only here.

    This system writes exactly one field. Population, resources, laws, walls,
    boundaries, infrastructure, fear, trust, and institutional pressure are all
    left as it found them, and it consumes no randomness.
    """

    __slots__ = ("_consumption_allocation",)

    def __init__(self, consumption_allocation: Mapping[ResourceType, float]) -> None:
        """Create a scarcity system.

        Args:
            consumption_allocation: Normalized weight per resource kind, used
                to size each district's demand. Defensively copied. Must match
                what ConsumptionSystem uses, or scarcity would be measured
                against a demand the district never had.

        Raises:
            TypeError: If the mapping or any key or weight is the wrong kind.
            ValueError: If a resource is missing, a weight is negative or
                non-finite, or the weights do not sum to 1.0.
        """
        self._consumption_allocation = validate_allocation(
            consumption_allocation, "consumption allocation"
        )

    @property
    def consumption_allocation(self) -> Mapping[ResourceType, float]:
        """Read-only view of the weights used to size district demand."""
        return self._consumption_allocation

    def update(self, world: "World", bus: EventBus) -> None:
        """Score every district and publish one event each.

        Districts are processed in sorted identifier order, reading each one's
        final population and stock for the tick. Every district emits,
        including one whose scarcity has not moved: this is a per-tick state
        reading, in the same manner as production and consumption, and a gap in
        the record would be indistinguishable from a system that failed to run.

        Args:
            world: The world whose districts are scored.
            bus: The bus on which scarcity events are published.

        Raises:
            ValueError: If a computed value is not finite.
        """
        for district_id in sorted(world.districts):
            district = world.districts[district_id]

            previous = float(district.scarcity)
            updated = shortfall_ratio(district, self._consumption_allocation)
            projected_required, projected_shortfall = shortfall_breakdown(
                district, self._consumption_allocation
            )

            district.scarcity = require_finite(updated, f"scarcity of {district_id!r}")

            payload: dict[str, FrozenJsonValue] = {
                "district_id": district_id,
                "previous_scarcity": previous,
                "new_scarcity": updated,
                "projected_required_total": projected_required,
                "projected_shortfall_total": projected_shortfall,
                "population": district.population,
                "projected_shortfall": {
                    resource.value: max(
                        0.0,
                        float(district.population)
                        * float(district.consumption_rate)
                        * self._consumption_allocation[resource]
                        - district.resources.amount_of(resource),
                    )
                    for resource in RESOURCE_ORDER
                },
            }
            bus.publish(
                Event(
                    tick=world.tick,
                    type=EventType.SCARCITY_CHANGED,
                    payload=payload,
                    source_id=district_id,
                )
            )
