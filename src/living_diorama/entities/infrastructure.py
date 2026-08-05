"""Infrastructure: capacity attached to a boundary that can grow wall-dependent."""

from dataclasses import dataclass
from enum import Enum

from living_diorama.entities.base_entity import (
    BaseEntity,
    EntityId,
    require_non_empty_id,
    require_non_negative,
    require_unit_interval,
)


class InfrastructureType(Enum):
    """The kinds of infrastructure the district-level MVP tracks.

    Values are stable uppercase strings so that later persistence work can
    serialize them by name without an extra mapping table.
    """

    TRANSIT_ROUTE = "TRANSIT_ROUTE"
    RESOURCE_ROUTE = "RESOURCE_ROUTE"
    HOUSING = "HOUSING"
    CIVIC_SERVICE = "CIVIC_SERVICE"


@dataclass(slots=True)
class Infrastructure(BaseEntity):
    """A piece of infrastructure attached to one boundary.

    Infrastructure is how a wall stops being a wall and becomes load-bearing:
    over time the world routes around it and comes to depend on it, which is
    why removing the original law no longer removes the consequence. This class
    stores that state only -- degradation and adaptation are the business of
    InfrastructureAdaptationSystem in a later phase.

    Attributes:
        boundary_id: Identifier of the boundary this infrastructure serves.
        infrastructure_type: What kind of infrastructure this is.
        capacity: Throughput or size this infrastructure provides.
        dependency_score: Normalized dependence that has accumulated on this
            infrastructure, 0.0-1.0.
        degraded: Whether this infrastructure is currently degraded.
    """

    boundary_id: EntityId
    infrastructure_type: InfrastructureType
    capacity: float
    dependency_score: float
    degraded: bool

    def __post_init__(self) -> None:
        """Validate the infrastructure's stored state.

        Raises:
            ValueError: If ``boundary_id`` is blank, if ``capacity`` is
                negative, or if ``dependency_score`` falls outside 0.0-1.0.
        """
        BaseEntity.__post_init__(self)
        self.boundary_id = require_non_empty_id(self.boundary_id, "boundary_id")
        require_non_negative(self.capacity, "capacity")
        require_unit_interval(self.dependency_score, "dependency_score")
