"""Deterministic simulation behavior, one system per causal concern.

Systems read and mutate World state and publish events to the
``living_diorama.events`` EventBus. Systems never call each other directly and
never touch persistence or rendering. The fixed per-tick execution order is
documented in ``docs/architecture.md`` (section 7) and enforced by
``living_diorama.simulation.SimulationLoop``, which is the only component that
knows that order.
"""

from living_diorama.systems.base_system import BaseSystem
from living_diorama.systems.consumption_system import ConsumptionSystem
from living_diorama.systems.production_system import ProductionSystem
from living_diorama.systems.resource_flow_system import ResourceFlowSystem

__all__ = [
    "BaseSystem",
    "ConsumptionSystem",
    "ProductionSystem",
    "ResourceFlowSystem",
]
