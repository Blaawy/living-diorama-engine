"""Typed construction helpers shared by the World and SimulationLoop tests.

Deliberately not named conftest.py: pytest imports every conftest under the
top-level module name ``conftest`` in its default prepend import mode, so a
second one alongside tests/entities/conftest.py would collide. A uniquely
named helper module sidesteps that entirely.

Builders let each test state only the field it exercises. The recording system
is the standard probe used to observe what the loop did without giving the loop
anything domain-specific to run.
"""

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
from living_diorama.events import EventBus
from living_diorama.simulation import DeterministicRNG, World
from living_diorama.systems import BaseSystem


def build_world(*, tick: int = 0, episode: int = 0, seed: int = 1) -> World:
    """Build an empty world with its own seeded generator."""
    return World(rng=DeterministicRNG(seed), tick=tick, episode=episode)


def build_district(*, id: str = "district_north", created_tick: int = 0) -> District:
    """Build a valid district for registry tests."""
    return District(
        id=id,
        created_tick=created_tick,
        population=120,
        resources=ResourcePool(stock={ResourceType.FOOD: 10.0}),
        production_rate=1.0,
        consumption_rate=0.5,
        scarcity=0.1,
        fear=0.2,
        trust=0.7,
        institutional_pressure=0.3,
        housing_capacity=200,
        isolation_state=IsolationState.OPEN,
    )


def build_boundary(
    *,
    id: str = "boundary_north_east",
    district_a_id: str = "district_north",
    district_b_id: str = "district_east",
    wall_id: str | None = None,
) -> Boundary:
    """Build a valid boundary for registry tests."""
    return Boundary(
        id=id,
        created_tick=0,
        district_a_id=district_a_id,
        district_b_id=district_b_id,
        wall_id=wall_id,
    )


def build_wall(*, id: str = "wall_0001", boundary_id: str = "boundary_north_east") -> Wall:
    """Build a valid wall for registry tests."""
    return Wall(
        id=id,
        created_tick=0,
        boundary_id=boundary_id,
        built_tick=0,
        integrity=1.0,
        active=True,
        permanent=True,
        dependency_score=0.0,
        transport_dependency=0.0,
        resource_dependency=0.0,
    )


def build_law(*, id: str = "law_movement_sharing") -> Law:
    """Build a valid law for registry tests."""
    return Law(
        id=id,
        created_tick=0,
        name="movement_resource_sharing",
        active=True,
        previous_value=None,
        current_value=True,
        changed_episode=0,
        restored_tick=None,
    )


def build_infrastructure(
    *, id: str = "infra_transit_ne", boundary_id: str = "boundary_north_east"
) -> Infrastructure:
    """Build a valid infrastructure entity for registry tests."""
    return Infrastructure(
        id=id,
        created_tick=0,
        boundary_id=boundary_id,
        infrastructure_type=InfrastructureType.TRANSIT_ROUTE,
        capacity=1.0,
        dependency_score=0.0,
        degraded=False,
    )


def build_linked_world() -> World:
    """Build a world with two districts, a boundary, a wall, and infrastructure."""
    world = build_world()
    world.add_district(build_district(id="district_north"))
    world.add_district(build_district(id="district_east"))
    world.add_boundary(build_boundary())
    world.add_wall(build_wall())
    world.add_infrastructure(build_infrastructure())
    world.add_law(build_law())
    return world


class RecordingSystem(BaseSystem):
    """A system that records what it was passed, so the loop can be observed.

    Deliberately domain-free: it exists to answer questions about ordering,
    call counts, and argument identity, not to simulate anything.
    """

    def __init__(self, name: str, journal: list[str]) -> None:
        """Create a system that appends its name to a shared journal."""
        self.name = name
        self.journal = journal
        self.calls = 0
        self.seen_worlds: list[World] = []
        self.seen_buses: list[EventBus] = []
        self.seen_ticks: list[int] = []

    def update(self, world: World, bus: EventBus) -> None:
        """Record the call, the arguments received, and the observed tick."""
        self.calls += 1
        self.journal.append(self.name)
        self.seen_worlds.append(world)
        self.seen_buses.append(bus)
        self.seen_ticks.append(world.tick)


class FailingSystem(BaseSystem):
    """A system that always raises, used to exercise failure semantics."""

    def __init__(self, journal: list[str], error: Exception) -> None:
        """Create a system that records its call and then raises."""
        self.journal = journal
        self.error = error

    def update(self, world: World, bus: EventBus) -> None:
        """Record the call, then raise the configured exception."""
        self.journal.append("failing")
        raise self.error
