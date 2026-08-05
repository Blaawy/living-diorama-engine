"""Shared builders for the Phase 4 resource-system tests.

Not named conftest.py: pytest imports every conftest under the module name
``conftest`` in its default prepend import mode, which would collide with
tests/entities/conftest.py.
"""

from collections.abc import Mapping

from living_diorama.entities import (
    Boundary,
    District,
    Infrastructure,
    InfrastructureType,
    IsolationState,
    Law,
    ResourcePool,
    ResourceType,
    Wall,
)
from living_diorama.simulation import DeterministicRNG, World

EVEN_ALLOCATION: Mapping[ResourceType, float] = {
    ResourceType.FOOD: 0.5,
    ResourceType.MATERIALS: 0.3,
    ResourceType.ENERGY: 0.2,
}

FOOD_ONLY_ALLOCATION: Mapping[ResourceType, float] = {
    ResourceType.FOOD: 1.0,
    ResourceType.MATERIALS: 0.0,
    ResourceType.ENERGY: 0.0,
}

LAW_ID = "law_movement_sharing"


def build_district(
    district_id: str,
    *,
    population: int = 10,
    production_rate: float = 0.0,
    consumption_rate: float = 0.0,
    food: float = 0.0,
    materials: float = 0.0,
    energy: float = 0.0,
    housing_capacity: int = 9999,
    isolation_state: IsolationState = IsolationState.OPEN,
) -> District:
    """Build a district with explicit stock and rates.

    ``housing_capacity`` and ``isolation_state`` default to the values every
    pre-Phase-5 test relied on, so existing behaviour is unchanged; migration
    tests override them to exercise capacity limits and isolation.
    """
    return District(
        id=district_id,
        created_tick=0,
        population=population,
        resources=ResourcePool(
            stock={
                ResourceType.FOOD: food,
                ResourceType.MATERIALS: materials,
                ResourceType.ENERGY: energy,
            }
        ),
        production_rate=production_rate,
        consumption_rate=consumption_rate,
        scarcity=0.0,
        fear=0.0,
        trust=0.5,
        institutional_pressure=0.0,
        housing_capacity=housing_capacity,
        isolation_state=isolation_state,
    )


def build_law(*, active: bool = True, current_value: object = True) -> Law:
    """Build the sharing law, optionally in a malformed state for tests."""
    return Law(
        id=LAW_ID,
        created_tick=0,
        name="movement_resource_sharing",
        active=active,
        previous_value=None,
        current_value=current_value,  # type: ignore[arg-type]
        changed_episode=0,
        restored_tick=None,
    )


def build_wall(wall_id: str, boundary_id: str, *, active: bool, permanent: bool = True) -> Wall:
    """Build a wall in a chosen activation state."""
    return Wall(
        id=wall_id,
        created_tick=0,
        boundary_id=boundary_id,
        built_tick=0,
        integrity=1.0,
        active=active,
        permanent=permanent,
        dependency_score=0.0,
        transport_dependency=0.0,
        resource_dependency=0.0,
    )


def build_infrastructure(infra_id: str, boundary_id: str) -> Infrastructure:
    """Build infrastructure attached to a boundary."""
    return Infrastructure(
        id=infra_id,
        created_tick=0,
        boundary_id=boundary_id,
        infrastructure_type=InfrastructureType.TRANSIT_ROUTE,
        capacity=1.0,
        dependency_score=0.0,
        degraded=False,
    )


def build_world(
    districts: list[District],
    *,
    boundaries: list[tuple[str, str, str]] | None = None,
    law: Law | None = None,
    seed: int = 1,
    tick: int = 0,
) -> World:
    """Assemble a world from districts, boundary triples, and an optional law.

    Args:
        districts: Districts to register, in the order given.
        boundaries: Triples of (boundary_id, district_a_id, district_b_id).
        law: The sharing law to register, if any.
        seed: RNG seed.
        tick: Starting tick.

    Returns:
        A world with everything registered in dependency order.
    """
    world = World(rng=DeterministicRNG(seed), tick=tick)
    for district in districts:
        world.add_district(district)
    for boundary_id, first, second in boundaries or []:
        world.add_boundary(
            Boundary(
                id=boundary_id,
                created_tick=0,
                district_a_id=first,
                district_b_id=second,
            )
        )
    if law is not None:
        world.add_law(law)
    return world


def stocks(world: World, resource: ResourceType) -> dict[str, float]:
    """Read one resource across every district, keyed by district id."""
    return {
        district_id: world.districts[district_id].resources.amount_of(resource)
        for district_id in sorted(world.districts)
    }


def total_of(world: World, resource: ResourceType) -> float:
    """Sum one resource across the whole world."""
    return sum(stocks(world, resource).values())
