"""District: the unit of population and social state in the MVP world model."""

from dataclasses import dataclass
from enum import Enum

from living_diorama.entities.base_entity import (
    BaseEntity,
    require_non_negative,
    require_unit_interval,
)
from living_diorama.entities.resource_pool import ResourcePool


class IsolationState(Enum):
    """How connected a district currently is to its neighbours.

    Values are stable uppercase strings so that later persistence work can
    serialize them by name without an extra mapping table.
    """

    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    ISOLATED = "ISOLATED"


@dataclass(slots=True)
class District(BaseEntity):
    """One district's aggregate population, resources, and social state.

    The MVP simulates population as an aggregate count rather than as
    individual citizens. Every field here is *stored* state: the district
    validates its own values but never computes them. Production, consumption,
    scarcity, fear, trust, and institutional pressure are all written by their
    respective systems in later phases.

    Attributes:
        population: Number of people currently in the district.
        resources: Current resource stock, as an immutable value object.
        production_rate: Resource units generated per tick.
        consumption_rate: Resource units drawn down per tick.
        scarcity: Normalized scarcity score, 0.0-1.0.
        fear: Normalized fear score, 0.0-1.0.
        trust: Normalized trust score, 0.0-1.0.
        institutional_pressure: Normalized pressure toward institutional
            action, 0.0-1.0.
        housing_capacity: Population the district's housing can hold.
        isolation_state: How connected this district currently is.
    """

    population: int
    resources: ResourcePool
    production_rate: float
    consumption_rate: float
    scarcity: float
    fear: float
    trust: float
    institutional_pressure: float
    housing_capacity: int
    isolation_state: IsolationState

    def __post_init__(self) -> None:
        """Validate the district's stored state.

        Raises:
            ValueError: If any count or rate is negative, or if any normalized
                score falls outside 0.0-1.0.
        """
        BaseEntity.__post_init__(self)
        require_non_negative(self.population, "population")
        require_non_negative(self.housing_capacity, "housing_capacity")
        require_non_negative(self.production_rate, "production_rate")
        require_non_negative(self.consumption_rate, "consumption_rate")
        require_unit_interval(self.scarcity, "scarcity")
        require_unit_interval(self.fear, "fear")
        require_unit_interval(self.trust, "trust")
        require_unit_interval(self.institutional_pressure, "institutional_pressure")
