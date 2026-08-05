"""Typed construction helpers shared by the entity-layer tests.

These builders exist so each test can state only the field it is actually
exercising, instead of repeating every required field at every construction
site. They are fully typed rather than kwargs-splatted, so a field rename in
the entity layer surfaces here as a type error rather than as a runtime
surprise inside a test.
"""

from living_diorama.entities import (
    Boundary,
    District,
    Infrastructure,
    InfrastructureType,
    IsolationState,
    Law,
    LawValue,
    ResourcePool,
    ResourceType,
    Wall,
)


def build_pool(food: float = 10.0) -> ResourcePool:
    """Build a valid resource pool holding the given amount of food."""
    return ResourcePool(stock={ResourceType.FOOD: food})


def build_district(
    *,
    id: str = "district_north",
    created_tick: int = 0,
    population: int = 120,
    resources: ResourcePool | None = None,
    production_rate: float = 1.0,
    consumption_rate: float = 0.5,
    scarcity: float = 0.1,
    fear: float = 0.2,
    trust: float = 0.7,
    institutional_pressure: float = 0.3,
    housing_capacity: int = 200,
    isolation_state: IsolationState = IsolationState.OPEN,
) -> District:
    """Build a valid district, overriding only the fields a test cares about."""
    return District(
        id=id,
        created_tick=created_tick,
        population=population,
        resources=build_pool() if resources is None else resources,
        production_rate=production_rate,
        consumption_rate=consumption_rate,
        scarcity=scarcity,
        fear=fear,
        trust=trust,
        institutional_pressure=institutional_pressure,
        housing_capacity=housing_capacity,
        isolation_state=isolation_state,
    )


def build_boundary(
    *,
    id: str = "boundary_north_east",
    created_tick: int = 0,
    district_a_id: str = "district_north",
    district_b_id: str = "district_east",
    wall_id: str | None = None,
) -> Boundary:
    """Build a valid boundary, overriding only the fields a test cares about."""
    return Boundary(
        id=id,
        created_tick=created_tick,
        district_a_id=district_a_id,
        district_b_id=district_b_id,
        wall_id=wall_id,
    )


def build_wall(
    *,
    id: str = "wall_0001",
    created_tick: int = 100,
    boundary_id: str = "boundary_north_east",
    built_tick: int = 100,
    integrity: float = 1.0,
    active: bool = True,
    permanent: bool = True,
    dependency_score: float = 0.0,
    transport_dependency: float = 0.0,
    resource_dependency: float = 0.0,
) -> Wall:
    """Build a valid wall, overriding only the fields a test cares about."""
    return Wall(
        id=id,
        created_tick=created_tick,
        boundary_id=boundary_id,
        built_tick=built_tick,
        integrity=integrity,
        active=active,
        permanent=permanent,
        dependency_score=dependency_score,
        transport_dependency=transport_dependency,
        resource_dependency=resource_dependency,
    )


def build_law(
    *,
    id: str = "law_movement_sharing",
    created_tick: int = 0,
    name: str = "movement_resource_sharing",
    active: bool = True,
    previous_value: LawValue = None,
    current_value: LawValue = True,
    changed_episode: int = 0,
    restored_tick: int | None = None,
) -> Law:
    """Build a valid law, overriding only the fields a test cares about."""
    return Law(
        id=id,
        created_tick=created_tick,
        name=name,
        active=active,
        previous_value=previous_value,
        current_value=current_value,
        changed_episode=changed_episode,
        restored_tick=restored_tick,
    )


def build_infrastructure(
    *,
    id: str = "infra_transit_ne",
    created_tick: int = 0,
    boundary_id: str = "boundary_north_east",
    infrastructure_type: InfrastructureType = InfrastructureType.TRANSIT_ROUTE,
    capacity: float = 1.0,
    dependency_score: float = 0.0,
    degraded: bool = False,
) -> Infrastructure:
    """Build a valid infrastructure entity, overriding only what a test cares about."""
    return Infrastructure(
        id=id,
        created_tick=created_tick,
        boundary_id=boundary_id,
        infrastructure_type=infrastructure_type,
        capacity=capacity,
        dependency_score=dependency_score,
        degraded=degraded,
    )
