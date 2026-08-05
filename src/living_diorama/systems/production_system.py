"""Districts generate resources each tick."""

from collections.abc import Mapping
from typing import TYPE_CHECKING

from living_diorama.entities import ResourceType
from living_diorama.events import Event, EventBus, EventType, JsonValue
from living_diorama.systems._resource_config import (
    RESOURCE_ORDER,
    build_pool,
    clamp_near_zero,
    require_finite,
    stock_snapshot,
    validate_allocation,
)
from living_diorama.systems.base_system import BaseSystem

if TYPE_CHECKING:  # pragma: no cover - import exists for typing only
    from living_diorama.simulation.world import World


class ProductionSystem(BaseSystem):
    """Adds each district's per-tick production to its resource stock.

    A district carries a single aggregate ``production_rate``. This system
    splits that one number across resource kinds using a normalized allocation
    supplied at construction, rather than inventing three separate rates on the
    District entity. The allocation is configuration, not world state, which is
    why it lives here and why changing it is a change to the experiment rather
    than to the world.

    The system is stateless between ticks: it holds its allocation and nothing
    else, and keeps no per-tick data after ``update`` returns.
    """

    __slots__ = ("_allocation",)

    def __init__(self, allocation: Mapping[ResourceType, float]) -> None:
        """Create a production system with a fixed resource allocation.

        Args:
            allocation: Normalized weight per resource kind, summing to 1.0.
                Defensively copied; the caller's mapping is not retained.

        Raises:
            TypeError: If the mapping or any key or weight is the wrong kind.
            ValueError: If a resource is missing, a weight is negative or
                non-finite, or the weights do not sum to 1.0.
        """
        self._allocation = validate_allocation(allocation, "production allocation")

    @property
    def allocation(self) -> Mapping[ResourceType, float]:
        """Read-only view of the configured production weights."""
        return self._allocation

    def update(self, world: "World", bus: EventBus) -> None:
        """Produce resources for every district and publish one event each.

        Districts are processed in sorted identifier order so that both the
        arithmetic and the resulting event sequence are reproducible. A district
        producing nothing still emits an event: "nothing was produced here" is a
        fact about the tick, and a gap in the log would be indistinguishable
        from a system that failed to run.

        Args:
            world: The world whose districts produce.
            bus: The bus on which production events are published.

        Raises:
            ValueError: If existing stock is invalid, or a computed value is
                not finite.
        """
        for district_id in sorted(world.districts):
            district = world.districts[district_id]
            total_produced = require_finite(
                float(district.production_rate), f"production_rate of {district_id!r}"
            )

            current = stock_snapshot(district.resources)
            produced: dict[ResourceType, float] = {}
            new_amounts: dict[ResourceType, float] = {}
            for resource in RESOURCE_ORDER:
                amount = require_finite(
                    total_produced * self._allocation[resource],
                    f"production of {resource.value} in {district_id!r}",
                )
                produced[resource] = amount
                new_amounts[resource] = clamp_near_zero(
                    current[resource] + amount,
                    f"new stock of {resource.value} in {district_id!r}",
                )

            district.resources = build_pool(new_amounts)

            payload: dict[str, JsonValue] = {
                "district_id": district_id,
                "total_produced": total_produced,
                "resources": {
                    resource.value: produced[resource] for resource in RESOURCE_ORDER
                },
            }
            bus.publish(
                Event(
                    tick=world.tick,
                    type=EventType.RESOURCE_PRODUCED,
                    payload=payload,
                    source_id=district_id,
                )
            )
