"""Wall: the permanent physical scar that may emerge on a boundary."""

from dataclasses import dataclass

from living_diorama.entities.base_entity import (
    BaseEntity,
    EntityId,
    Tick,
    require_non_empty_id,
    require_unit_interval,
)


@dataclass(slots=True)
class Wall(BaseEntity):
    """A wall standing on one boundary between two districts.

    The wall is the artifact the whole MVP exists to produce: it may only come
    into being through sustained causal pressure, and once ``permanent`` it
    outlives the law that caused it. This class stores that state and nothing
    else -- decay, removal, strengthening, and dependency growth are the
    business of BoundaryDecisionSystem and InfrastructureAdaptationSystem in
    later phases.

    Attributes:
        boundary_id: Identifier of the boundary this wall stands on.
        built_tick: Tick at which construction completed. Never earlier than
            ``created_tick``.
        integrity: Normalized structural integrity, 0.0-1.0.
        active: Whether the wall is currently in force.
        permanent: Whether the wall persists regardless of later law changes.
        dependency_score: Normalized overall dependence the world has developed
            on this wall, 0.0-1.0.
        transport_dependency: Normalized transport dependence, 0.0-1.0.
        resource_dependency: Normalized resource-routing dependence, 0.0-1.0.
    """

    boundary_id: EntityId
    built_tick: Tick
    integrity: float
    active: bool
    permanent: bool
    dependency_score: float
    transport_dependency: float
    resource_dependency: float

    def __post_init__(self) -> None:
        """Validate the wall's stored state.

        Raises:
            ValueError: If ``boundary_id`` is blank, if ``built_tick`` precedes
                ``created_tick``, or if any normalized score falls outside
                0.0-1.0.
        """
        BaseEntity.__post_init__(self)
        self.boundary_id = require_non_empty_id(self.boundary_id, "boundary_id")
        if self.built_tick < self.created_tick:
            raise ValueError(
                f"built_tick must be >= created_tick, got {self.built_tick} < {self.created_tick}"
            )
        require_unit_interval(self.integrity, "integrity")
        require_unit_interval(self.dependency_score, "dependency_score")
        require_unit_interval(self.transport_dependency, "transport_dependency")
        require_unit_interval(self.resource_dependency, "resource_dependency")
