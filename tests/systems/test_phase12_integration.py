"""Phase 12 end to end: a scheduled rule change moves the world the same tick.

The show's premise is that changing one rule changes everything downstream.
These tests prove it with the real engine: a real ``SimulationLoop`` advances
the tick, the real ``RuleSystem`` runs first, and real downstream systems
observe the new law during the very tick it changed -- then the whole result
survives the real persistence layer.
"""

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from systems_builders import (
    EVEN_ALLOCATION,
    LAW_ID,
    build_district,
    build_infrastructure,
    build_law,
    build_wall,
    build_world,
)

from living_diorama.entities import Law, ResourceType
from living_diorama.events import EventBus, EventLog, EventType
from living_diorama.memory import MemorySignificance
from living_diorama.persistence import SaveManager
from living_diorama.persistence.serializers.world_serializer import serialize_world
from living_diorama.simulation import DeterministicRNG, SimulationLoop, World
from living_diorama.systems import (
    BoundaryDecisionSystem,
    ConsumptionSystem,
    InfrastructureAdaptationSystem,
    InstitutionalPressureSystem,
    MigrationSystem,
    ProductionSystem,
    ResourceFlowSystem,
    RuleSystem,
    ScarcitySystem,
    ScheduledLawChange,
    ScheduledLawRestore,
    SocialStabilitySystem,
)

CHANGE_TICK = 5
"""The tick at which every same-tick scenario schedules its intervention."""


@contextmanager
def temporary_save_root() -> Iterator[Path]:
    """Yield a disposable directory for a save root, removed afterwards."""
    with tempfile.TemporaryDirectory() as name:
        yield Path(name)


def sharing_law(
    *,
    active: bool = True,
    previous_value: object = None,
    current_value: object = True,
    changed_episode: int = 0,
    restored_tick: int | None = None,
) -> Law:
    """Build the sharing law in an arbitrary provenance state."""
    return Law(
        id=LAW_ID,
        created_tick=0,
        name="movement_resource_sharing",
        active=active,
        previous_value=previous_value,  # type: ignore[arg-type]
        current_value=current_value,  # type: ignore[arg-type]
        changed_episode=changed_episode,
        restored_tick=restored_tick,
    )


def donor_receiver_world(law: Law) -> World:
    """Build a two-district world where 'a' would share food with 'b'."""
    return build_world(
        [
            build_district("a", population=0, consumption_rate=1.0, food=100.0),
            build_district("b", population=10, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("bound", "a", "b")],
        law=law,
        tick=CHANGE_TICK - 1,
    )


def flow_system() -> ResourceFlowSystem:
    """Build the standard flow system bound to the sharing law."""
    return ResourceFlowSystem(
        law_id=LAW_ID, consumption_allocation=EVEN_ALLOCATION, reserve_ticks=1.0
    )


def run_one_tick(world: World, systems: tuple) -> EventLog:
    """Run one real SimulationLoop tick and return everything published."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    SimulationLoop(systems, bus).run(world, 1)
    return log


def full_pipeline(rule: RuleSystem) -> tuple:
    """The canonical runtime order, RuleSystem first."""
    return (
        rule,
        ProductionSystem(allocation=EVEN_ALLOCATION),
        ConsumptionSystem(allocation=EVEN_ALLOCATION),
        ResourceFlowSystem(
            law_id=LAW_ID, consumption_allocation=EVEN_ALLOCATION, reserve_ticks=1.0
        ),
        MigrationSystem(
            law_id=LAW_ID,
            consumption_allocation=EVEN_ALLOCATION,
            migration_rate=0.2,
            min_pressure_gap=0.05,
            partial_isolation_factor=0.5,
        ),
        ScarcitySystem(consumption_allocation=EVEN_ALLOCATION),
        SocialStabilitySystem(response_rate=0.25),
        InstitutionalPressureSystem(response_rate=0.20),
        BoundaryDecisionSystem(),
        InfrastructureAdaptationSystem(),
    )


# --- same-tick effect --------------------------------------------------------


def test_a_scheduled_deactivation_stops_sharing_in_its_own_tick() -> None:
    """The law goes down at tick T and the flow system already obeys at T."""
    world = donor_receiver_world(build_law(active=True, current_value=True))
    rule = RuleSystem(
        [
            ScheduledLawChange(
                episode=0, tick=CHANGE_TICK, law_id=LAW_ID, new_value=False, active=False
            )
        ]
    )
    log = run_one_tick(world, (rule, flow_system()))

    assert world.tick == CHANGE_TICK
    changed = log.query(event_type=EventType.LAW_CHANGED)
    assert len(changed) == 1
    assert changed[0].tick == CHANGE_TICK
    assert log.query(event_type=EventType.RESOURCE_TRANSFERRED) == ()
    assert world.districts["b"].resources.amount_of(ResourceType.FOOD) == 0.0
    assert world.districts["a"].resources.amount_of(ResourceType.FOOD) == 100.0


def test_the_deactivation_control_still_shares() -> None:
    """Identical world, no scheduled change: the transfer happens at T."""
    world = donor_receiver_world(build_law(active=True, current_value=True))
    log = run_one_tick(world, (RuleSystem(()), flow_system()))

    assert log.query(event_type=EventType.LAW_CHANGED) == ()
    assert len(log.query(event_type=EventType.RESOURCE_TRANSFERRED)) == 1
    assert world.districts["b"].resources.amount_of(ResourceType.FOOD) == 5.0


def test_a_scheduled_restoration_enables_sharing_in_its_own_tick() -> None:
    """The law comes back at tick T and resources flow during T itself."""
    world = donor_receiver_world(
        sharing_law(active=False, previous_value=True, current_value=False)
    )
    rule = RuleSystem([ScheduledLawRestore(episode=0, tick=CHANGE_TICK, law_id=LAW_ID)])
    log = run_one_tick(world, (rule, flow_system()))

    law = world.laws[LAW_ID]
    assert law.active is True
    assert law.previous_value is False
    assert law.current_value is True
    assert law.changed_episode == 0
    assert law.restored_tick == CHANGE_TICK

    kinds = [event.type for event in log]
    assert kinds.index(EventType.LAW_RESTORED) < kinds.index(EventType.RESOURCE_TRANSFERRED)
    assert world.districts["b"].resources.amount_of(ResourceType.FOOD) == 5.0


def test_the_restoration_control_does_not_share() -> None:
    """Identical world, no scheduled restoration: the law stays down."""
    world = donor_receiver_world(
        sharing_law(active=False, previous_value=True, current_value=False)
    )
    log = run_one_tick(world, (RuleSystem(()), flow_system()))

    assert log.query(event_type=EventType.LAW_RESTORED) == ()
    assert log.query(event_type=EventType.RESOURCE_TRANSFERRED) == ()
    assert world.districts["b"].resources.amount_of(ResourceType.FOOD) == 0.0


def test_rule_system_first_in_the_full_canonical_pipeline() -> None:
    """All ten systems run; the law event precedes every downstream event."""
    world = donor_receiver_world(build_law(active=True, current_value=True))
    rule = RuleSystem(
        [
            ScheduledLawChange(
                episode=0, tick=CHANGE_TICK, law_id=LAW_ID, new_value=False, active=False
            )
        ]
    )
    log = run_one_tick(world, full_pipeline(rule))

    kinds = [event.type for event in log]
    assert kinds[0] is EventType.LAW_CHANGED
    assert EventType.RESOURCE_TRANSFERRED not in kinds
    assert world.districts["b"].resources.amount_of(ResourceType.FOOD) == 0.0


def test_a_duplicate_rule_system_in_the_pipeline_emits_once() -> None:
    """SimulationLoop permits duplicates; the World's provenance defuses them."""
    world = donor_receiver_world(build_law(active=True, current_value=True))
    rule = RuleSystem(
        [
            ScheduledLawChange(
                episode=0, tick=CHANGE_TICK, law_id=LAW_ID, new_value=False, active=False
            )
        ]
    )
    log = run_one_tick(world, (rule, rule))
    assert len(log.query(event_type=EventType.LAW_CHANGED)) == 1


# --- write scope -------------------------------------------------------------


def walled_world(*, law: Law, tick: int) -> World:
    """Build a serializable world with a permanent wall and infrastructure."""
    world = build_world(
        [build_district("a", food=10.0), build_district("b", food=10.0)],
        boundaries=[("bound", "a", "b")],
        law=law,
        tick=tick,
    )
    world.add_wall(build_wall("wall_bound", "bound", active=False, permanent=True))
    world.add_infrastructure(build_infrastructure("infra_bound", "bound"))
    return world


def test_rule_system_writes_law_state_and_nothing_else() -> None:
    """A full-world snapshot proves the write scope is exactly the target law."""
    world = walled_world(
        law=sharing_law(active=False, previous_value=True, current_value=False),
        tick=250,
    )
    identities = {
        "district": world.districts["a"],
        "boundary": world.boundaries["bound"],
        "wall": world.walls["wall_bound"],
    }
    registry_keys = {
        "districts": sorted(world.districts),
        "boundaries": sorted(world.boundaries),
        "walls": sorted(world.walls),
        "laws": sorted(world.laws),
        "infrastructure": sorted(world.infrastructure),
    }
    before = serialize_world(world)
    rng_before = world.rng.get_state()

    bus = EventBus()
    RuleSystem([ScheduledLawRestore(episode=0, tick=250, law_id=LAW_ID)]).update(world, bus)

    after = serialize_world(world)
    expected = dict(before)
    expected["laws"] = [
        {
            **entry,
            "active": True,
            "previous_value": False,
            "current_value": True,
            "changed_episode": 0,
            "restored_tick": 250,
        }
        if entry["id"] == LAW_ID
        else entry
        for entry in before["laws"]
    ]
    assert after == expected

    assert world.districts["a"] is identities["district"]
    assert world.boundaries["bound"] is identities["boundary"]
    assert world.walls["wall_bound"] is identities["wall"]
    assert registry_keys == {
        "districts": sorted(world.districts),
        "boundaries": sorted(world.boundaries),
        "walls": sorted(world.walls),
        "laws": sorted(world.laws),
        "infrastructure": sorted(world.infrastructure),
    }
    assert world.rng.get_state() == rng_before
    assert world.tick == 250
    assert world.episode == 0


def test_a_restoration_leaves_the_permanent_wall_untouched() -> None:
    """RuleSystem restores the rule; it never undoes the rule's consequences."""
    world = walled_world(
        law=sharing_law(active=False, previous_value=True, current_value=False),
        tick=249,
    )
    wall_before = (
        world.walls["wall_bound"].id,
        world.walls["wall_bound"].boundary_id,
        world.walls["wall_bound"].built_tick,
        world.walls["wall_bound"].integrity,
        world.walls["wall_bound"].active,
        world.walls["wall_bound"].permanent,
        world.walls["wall_bound"].dependency_score,
        world.walls["wall_bound"].transport_dependency,
        world.walls["wall_bound"].resource_dependency,
    )
    boundary_wall_id = world.boundaries["bound"].wall_id
    infrastructure_before = world.infrastructure["infra_bound"]

    rule = RuleSystem([ScheduledLawRestore(episode=0, tick=250, law_id=LAW_ID)])
    log = run_one_tick(world, (rule,))

    assert len(log.query(event_type=EventType.LAW_RESTORED)) == 1
    assert world.laws[LAW_ID].active is True
    assert (
        world.walls["wall_bound"].id,
        world.walls["wall_bound"].boundary_id,
        world.walls["wall_bound"].built_tick,
        world.walls["wall_bound"].integrity,
        world.walls["wall_bound"].active,
        world.walls["wall_bound"].permanent,
        world.walls["wall_bound"].dependency_score,
        world.walls["wall_bound"].transport_dependency,
        world.walls["wall_bound"].resource_dependency,
    ) == wall_before
    assert world.boundaries["bound"].wall_id == boundary_wall_id
    assert world.infrastructure["infra_bound"] is infrastructure_before


# --- multi-episode schedules -------------------------------------------------


def second_law(law_id: str = "law_curfew") -> Law:
    """Build an unrelated second law for cross-episode scenarios."""
    return Law(
        id=law_id,
        created_tick=0,
        name="curfew",
        active=False,
        previous_value=None,
        current_value=False,  # type: ignore[arg-type]
        changed_episode=0,
        restored_tick=None,
    )


def test_a_multi_episode_schedule_applies_one_action_per_episode() -> None:
    """Each episode sees exactly its own entry, and entries never leak."""
    schedule = [
        ScheduledLawChange(episode=0, tick=100, law_id=LAW_ID, new_value=False, active=False),
        ScheduledLawRestore(episode=1, tick=250, law_id=LAW_ID),
        ScheduledLawChange(episode=2, tick=400, law_id="law_curfew", new_value=True, active=True),
    ]
    rule = RuleSystem(schedule)

    episode_zero = World(rng=DeterministicRNG(1), tick=100, episode=0)
    episode_zero.add_law(sharing_law(active=True, previous_value=None, current_value=True))
    episode_zero.add_law(second_law())
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    rule.update(episode_zero, bus)
    assert [event.type for event in log] == [EventType.LAW_CHANGED]
    assert episode_zero.laws[LAW_ID].current_value is False
    assert episode_zero.laws["law_curfew"] == second_law()

    episode_one = World(rng=DeterministicRNG(1), tick=250, episode=1)
    episode_one.add_law(sharing_law(active=False, previous_value=True, current_value=False))
    episode_one.add_law(second_law())
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    rule.update(episode_one, bus)
    assert [event.type for event in log] == [EventType.LAW_RESTORED]
    assert episode_one.laws[LAW_ID].restored_tick == 250
    assert episode_one.laws["law_curfew"] == second_law()

    episode_two = World(rng=DeterministicRNG(1), tick=400, episode=2)
    episode_two.add_law(sharing_law())
    episode_two.add_law(second_law())
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    rule.update(episode_two, bus)
    assert [event.type for event in log] == [EventType.LAW_CHANGED]
    assert episode_two.laws["law_curfew"].current_value is True
    assert episode_two.laws[LAW_ID] == sharing_law()

    episode_nine = World(rng=DeterministicRNG(1), tick=999, episode=9)
    episode_nine.add_law(sharing_law())
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    rule.update(episode_nine, bus)
    assert len(log) == 0

    assert rule.schedule == tuple(schedule), "applying never consumes the plan"


# --- determinism -------------------------------------------------------------


def test_identical_worlds_and_schedules_produce_identical_outcomes() -> None:
    """Same input, same tick, same events, same law -- every time."""
    results = []
    for _ in range(2):
        world = donor_receiver_world(
            sharing_law(active=False, previous_value=True, current_value=False)
        )
        rule = RuleSystem([ScheduledLawRestore(episode=0, tick=CHANGE_TICK, law_id=LAW_ID)])
        log = run_one_tick(world, (rule, flow_system()))
        results.append(
            (
                world.laws[LAW_ID]
                == sharing_law(
                    active=True,
                    previous_value=False,
                    current_value=True,
                    restored_tick=CHANGE_TICK,
                ),
                [
                    (event.tick, event.type.value, event.source_id, event.payload_as_dict())
                    for event in log
                ],
            )
        )
    assert results[0] == results[1]


# --- persistence -------------------------------------------------------------


def test_a_real_restoration_survives_save_and_load() -> None:
    """The Law state, the event, and the untouched wall all round-trip."""
    world = walled_world(
        law=sharing_law(active=False, previous_value=True, current_value=False),
        tick=249,
    )
    rule = RuleSystem([ScheduledLawRestore(episode=0, tick=250, law_id=LAW_ID)])
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    SimulationLoop((rule,), bus).run(world, 1)

    memory = MemorySignificance().distill_episode(world=world, event_log=log, previous_memory=None)

    with temporary_save_root() as root:
        manager = SaveManager(root)
        manager.save_episode(world, log, world_memory=memory)
        loaded = manager.load_episode(0)

        law = loaded.world.laws[LAW_ID]
        assert law.active is True
        assert law.previous_value is False
        assert law.current_value is True
        assert law.changed_episode == 0
        assert law.restored_tick == 250

        restored_events = [
            event for event in loaded.event_log.events() if event.type is EventType.LAW_RESTORED
        ]
        assert len(restored_events) == 1
        assert restored_events[0].tick == 250
        assert restored_events[0].source_id == LAW_ID
        assert restored_events[0].payload_as_dict() == {
            "active": True,
            "changed_episode": 0,
            "current_value": True,
            "previous_value": False,
            "restored_tick": 250,
        }

        wall = loaded.world.walls["wall_bound"]
        assert wall == world.walls["wall_bound"]
        assert wall.permanent is True


def test_a_shifting_action_cannot_persist_a_contradictory_episode() -> None:
    """The reviewer's blocking case: event and world must agree after reload.

    A caller-owned action subclass that answers ``new_value`` differently on
    later reads must not be able to publish one value into the event log while
    a different value lands in the saved world. The normalized action snapshot
    captured at RuleSystem construction is authoritative for both.
    """
    lie = {"armed": False}
    reads = {"count": 0}

    class ShiftySaveChange(ScheduledLawChange):
        """Answers False to the first armed new_value read, then shifts."""

        def __getattribute__(self, name: str) -> object:
            """Shift new_value after its first armed read."""
            if lie["armed"] and name == "new_value":
                reads["count"] += 1
                return False if reads["count"] == 1 else "changed-after-event"
            return super().__getattribute__(name)

    world = walled_world(
        law=sharing_law(active=True, previous_value=None, current_value=True),
        tick=249,
    )
    action = ShiftySaveChange(episode=0, tick=250, law_id=LAW_ID, new_value=False, active=False)
    system = RuleSystem([action])
    lie["armed"] = True

    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    SimulationLoop((system,), bus).run(world, 1)

    memory = MemorySignificance().distill_episode(world=world, event_log=log, previous_memory=None)
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manager.save_episode(world, log, world_memory=memory)
        loaded = manager.load_episode(0)

        changed = [
            event for event in loaded.event_log.events() if event.type is EventType.LAW_CHANGED
        ]
        assert len(changed) == 1
        payload = changed[0].payload_as_dict()
        law = loaded.world.laws[LAW_ID]
        assert payload["current_value"] == law.current_value
        assert payload["previous_value"] == law.previous_value
        assert law.current_value is False
        assert law.previous_value is True
