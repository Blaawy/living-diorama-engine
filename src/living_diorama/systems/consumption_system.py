"""District populations draw down resources each tick."""

from collections.abc import Mapping
from typing import TYPE_CHECKING

from living_diorama.entities import ResourceType
from living_diorama.events import Event, EventBus, EventType
from living_diorama.events.event import FrozenJsonValue
from living_diorama.systems._resource_config import (
    RESOURCE_ORDER,
    build_pool,
    clamp_near_zero,
    require_finite,
    stock_snapshot,
    sum_amounts,
    validate_allocation,
)
from living_diorama.systems.base_system import BaseSystem

if TYPE_CHECKING:  # pragma: no cover - import exists for typing only
    from living_diorama.simulation.world import World


class ConsumptionSystem(BaseSystem):
    """Consumes what each district's population demands, capped by what it has.

    Demand is population times the district's aggregate ``consumption_rate``,
    split across resource kinds by a normalized allocation supplied at
    construction. Demand that cannot be met is not an error: the shortfall is
    reported as ``unmet`` in the event, which is the raw material a later
    scarcity system will read. Stock is never driven below zero to satisfy
    demand.

    The system is stateless between ticks.
    """

    __slots__ = ("_allocation",)

    def __init__(self, allocation: Mapping[ResourceType, float]) -> None:
        """Create a consumption system with a fixed resource allocation.

        Args:
            allocation: Normalized weight per resource kind, summing to 1.0.
                Defensively copied; the caller's mapping is not retained.

        Raises:
            TypeError: If the mapping or any key or weight is the wrong kind.
            ValueError: If a resource is missing, a weight is negative or
                non-finite, or the weights do not sum to 1.0.
        """
        self._allocation = validate_allocation(allocation, "consumption allocation")

    @property
    def allocation(self) -> Mapping[ResourceType, float]:
        """Read-only view of the configured consumption weights."""
        return self._allocation

    def update(self, world: "World", bus: EventBus) -> None:
        """Consume resources for every district and publish one event each.

        Districts are processed in sorted identifier order. A district with no
        population or a zero consumption rate still emits an event, for the same
        reason a zero-production district does.

        Args:
            world: The world whose districts consume.
            bus: The bus on which consumption events are published.

        Raises:
            ValueError: If existing stock is invalid, or a computed value is
                not finite or would drive stock meaningfully negative.
        """
        for district_id in sorted(world.districts):
            district = world.districts[district_id]
            requested_total = require_finite(
                float(district.population) * float(district.consumption_rate),
                f"requested consumption of {district_id!r}",
            )

            current = stock_snapshot(district.resources)
            consumed: dict[ResourceType, float] = {}
            unmet: dict[ResourceType, float] = {}
            new_amounts: dict[ResourceType, float] = {}

            for resource in RESOURCE_ORDER:
                requested = require_finite(
                    requested_total * self._allocation[resource],
                    f"requested {resource.value} in {district_id!r}",
                )
                taken = min(current[resource], requested)
                consumed[resource] = clamp_near_zero(
                    taken, f"consumed {resource.value} in {district_id!r}"
                )
                unmet[resource] = clamp_near_zero(
                    requested - consumed[resource],
                    f"unmet {resource.value} in {district_id!r}",
                )
                new_amounts[resource] = clamp_near_zero(
                    current[resource] - consumed[resource],
                    f"new stock of {resource.value} in {district_id!r}",
                )

            district.resources = build_pool(new_amounts)

            consumed_total = sum_amounts(consumed)
            unmet_total = sum_amounts(unmet)

            payload: dict[str, FrozenJsonValue] = {
                "district_id": district_id,
                "requested_total": requested_total,
                "consumed_total": consumed_total,
                "unmet_total": unmet_total,
                "consumed": {resource.value: consumed[resource] for resource in RESOURCE_ORDER},
                "unmet": {resource.value: unmet[resource] for resource in RESOURCE_ORDER},
            }
            bus.publish(
                Event(
                    tick=world.tick,
                    type=EventType.RESOURCE_CONSUMED,
                    payload=payload,
                    source_id=district_id,
                )
            )
