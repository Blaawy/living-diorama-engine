"""Tests for RuleSystem: one validated law intervention, applied exactly once.

The schedule is the show's script: at most one changed rule per episode. These
tests pin the schedule's validation, the timing contract around the scheduled
tick, the exact Law mutation and event payloads, and the refusals -- missed
actions, meaningless changes, corrupted stored state -- that keep an episode's
intervention honest.
"""

import ast
from dataclasses import FrozenInstanceError
from enum import IntEnum, StrEnum
from pathlib import Path

import pytest
from systems_builders import LAW_ID, build_district

from living_diorama.entities import Law
from living_diorama.events import EventBus, EventLog, EventType
from living_diorama.simulation import DeterministicRNG, World
from living_diorama.systems import (
    BaseSystem,
    RuleSystem,
    ScheduledLawChange,
    ScheduledLawRestore,
)

RULE_SYSTEM_SOURCE = (
    Path(__file__).resolve().parents[2] / "src" / "living_diorama" / "systems" / "rule_system.py"
)
"""The production module under static audit."""


class ExactnessEnum(IntEnum):
    """An int carried by a subclass through the enum machinery."""

    ONE = 1


class ExactnessStrEnum(StrEnum):
    """A str carried by a subclass through the enum machinery."""

    LABEL = "label"


class IntSubclass(int):
    """Equal to an ``int``, but not exactly one."""


class FloatSubclass(float):
    """Equal to a ``float``, but not exactly one."""


class StrSubclass(str):
    """Equal to a ``str``, but not exactly one."""


class HostileClass:
    """Raises from ``__class__`` instead of answering."""

    @property
    def __class__(self) -> type:
        """Raise instead of revealing a type."""
        raise RuntimeError("boom")


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


def world_with(law: Law | None, *, episode: int = 0, tick: int = 0) -> World:
    """Build a minimal world holding one law at a chosen episode and tick."""
    world = World(rng=DeterministicRNG(1), tick=tick, episode=episode)
    if law is not None:
        world.add_law(law)
    return world


def run_rule(
    world: World, *actions: ScheduledLawChange | ScheduledLawRestore
) -> tuple[EventLog, RuleSystem]:
    """Run one RuleSystem update over the world and return the log and system."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    system = RuleSystem(actions)
    system.update(world, bus)
    return log, system


def change_at(tick: int, *, episode: int = 0, new_value: object = False) -> ScheduledLawChange:
    """Build the standard deactivating change used across these tests."""
    return ScheduledLawChange(
        episode=episode,
        tick=tick,
        law_id=LAW_ID,
        new_value=new_value,  # type: ignore[arg-type]
        active=False,
    )


def restore_at(tick: int, *, episode: int = 0) -> ScheduledLawRestore:
    """Build the standard restoration used across these tests."""
    return ScheduledLawRestore(episode=episode, tick=tick, law_id=LAW_ID)


# --- exports and construction ------------------------------------------------


def test_the_new_classes_are_exported_from_systems() -> None:
    """The Phase 12 public surface arrives through the systems package."""
    assert issubclass(RuleSystem, BaseSystem)
    assert ScheduledLawChange(episode=0, tick=1, law_id="x", new_value=None, active=True)
    assert ScheduledLawRestore(episode=0, tick=1, law_id="x")


def test_scheduled_actions_are_immutable() -> None:
    """A schedule entry is a fact about the plan, not a mutable request."""
    action = change_at(5)
    with pytest.raises(FrozenInstanceError):
        action.tick = 6  # type: ignore[misc]


@pytest.mark.parametrize("episode", [True, False, -1, 1.5, "0", None, IntSubclass(0)])
def test_a_change_refuses_an_inexact_episode(episode: object) -> None:
    """Episodes are exact non-negative ints; bool and subclasses are not."""
    with pytest.raises((TypeError, ValueError)):
        ScheduledLawChange(
            episode=episode,  # type: ignore[arg-type]
            tick=1,
            law_id=LAW_ID,
            new_value=None,
            active=True,
        )


@pytest.mark.parametrize("tick", [True, -1, 1.5, "5", None])
def test_a_change_refuses_an_inexact_tick(tick: object) -> None:
    """Ticks are exact non-negative ints."""
    with pytest.raises((TypeError, ValueError)):
        ScheduledLawChange(
            episode=0,
            tick=tick,  # type: ignore[arg-type]
            law_id=LAW_ID,
            new_value=None,
            active=True,
        )


@pytest.mark.parametrize("law_id", ["", " ", "law ", " law", "law\t", 5, None, StrSubclass("law")])
def test_a_change_refuses_a_noncanonical_law_id(law_id: object) -> None:
    """Corrupted identifiers are refused as supplied, never stripped."""
    with pytest.raises((TypeError, ValueError)):
        ScheduledLawChange(
            episode=0,
            tick=1,
            law_id=law_id,  # type: ignore[arg-type]
            new_value=None,
            active=True,
        )


@pytest.mark.parametrize(
    "new_value",
    [
        ExactnessEnum.ONE,
        ExactnessStrEnum.LABEL,
        IntSubclass(1),
        FloatSubclass(1.0),
        StrSubclass("x"),
        [1],
        {"a": 1},
        (1,),
        object(),
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_a_change_refuses_an_inexact_law_value(new_value: object) -> None:
    """A law's value is an exact JSON scalar; lookalikes are refused."""
    with pytest.raises((TypeError, ValueError)):
        ScheduledLawChange(
            episode=0,
            tick=1,
            law_id=LAW_ID,
            new_value=new_value,  # type: ignore[arg-type]
            active=True,
        )


def test_a_hostile_law_value_is_refused_without_being_consulted() -> None:
    """A raising ``__class__`` cannot preempt schedule validation."""
    with pytest.raises(TypeError, match="new_value must be null, a bool"):
        ScheduledLawChange(
            episode=0,
            tick=1,
            law_id=LAW_ID,
            new_value=HostileClass(),  # type: ignore[arg-type]
            active=True,
        )


@pytest.mark.parametrize("active", [1, 0, None, "True"])
def test_a_change_refuses_an_inexact_active_flag(active: object) -> None:
    """The active flag is exactly a bool."""
    with pytest.raises(TypeError):
        ScheduledLawChange(
            episode=0,
            tick=1,
            law_id=LAW_ID,
            new_value=None,
            active=active,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("value", [None, True, False, 0, 7, 0.5, "limit"])
def test_valid_law_values_are_stored_exactly(value: object) -> None:
    """Accepted scalars are stored as the very object supplied."""
    action = ScheduledLawChange(
        episode=0,
        tick=1,
        law_id=LAW_ID,
        new_value=value,  # type: ignore[arg-type]
        active=True,
    )
    assert action.new_value is value


@pytest.mark.parametrize("field", ["episode", "tick", "law_id"])
def test_a_restore_validates_its_fields_exactly(field: str) -> None:
    """The restoration entry applies the same exact-type rules."""
    good: dict[str, object] = {"episode": 0, "tick": 1, "law_id": LAW_ID}
    for bad in (True, -1, "x ", None):
        arguments = dict(good)
        arguments[field] = bad
        with pytest.raises((TypeError, ValueError)):
            ScheduledLawRestore(**arguments)  # type: ignore[arg-type]


# --- the schedule ------------------------------------------------------------


def test_the_schedule_is_defensively_copied() -> None:
    """Mutating the caller's list afterwards changes nothing."""
    entries: list[ScheduledLawChange | ScheduledLawRestore] = [change_at(5)]
    system = RuleSystem(entries)
    entries.append(restore_at(9, episode=1))
    entries.clear()
    assert system.schedule == (change_at(5),)
    assert type(system.schedule) is tuple


def test_an_episode_may_hold_exactly_one_action() -> None:
    """One changed rule per episode is the show's core mechanic."""
    with pytest.raises(ValueError, match="episode 3"):
        RuleSystem(
            [
                ScheduledLawChange(
                    episode=3, tick=10, law_id="law_a", new_value=False, active=False
                ),
                ScheduledLawRestore(episode=3, tick=99, law_id="law_b"),
            ]
        )
    with pytest.raises(ValueError, match="episode 3"):
        RuleSystem(
            [
                ScheduledLawChange(
                    episode=3, tick=10, law_id="law_a", new_value=False, active=False
                ),
                ScheduledLawChange(episode=3, tick=20, law_id="law_b", new_value=True, active=True),
            ]
        )
    assert RuleSystem(
        [change_at(10, episode=0), restore_at(20, episode=1), change_at(30, episode=2)]
    ).schedule


def test_a_duplicate_episode_is_reported_before_a_later_invalid_entry() -> None:
    """Entries are validated in supplied order; the earliest problem wins."""
    with pytest.raises(ValueError, match="episode 0"):
        RuleSystem([change_at(10), change_at(20), object()])  # type: ignore[list-item]


def test_a_non_action_schedule_entry_is_refused() -> None:
    """Only real scheduled actions may enter the plan, decided by true type."""
    with pytest.raises(TypeError, match="schedule\\[0\\]"):
        RuleSystem([object()])  # type: ignore[list-item]
    with pytest.raises(TypeError, match="got HostileClass"):
        RuleSystem([HostileClass()])  # type: ignore[list-item]


def test_an_empty_schedule_is_valid_and_inert() -> None:
    """No plan means no action, at any tick, with no events."""
    law = sharing_law()
    world = world_with(law, tick=500)
    log, _ = run_rule(world)
    assert len(log) == 0
    assert law == sharing_law()


def test_an_unscheduled_episode_is_a_no_op() -> None:
    """An episode absent from the schedule is left entirely alone."""
    law = sharing_law()
    world = world_with(law, episode=7, tick=500)
    rng_before = world.rng.get_state()
    log, _ = run_rule(world, change_at(100, episode=2))
    assert len(log) == 0
    assert law == sharing_law()
    assert world.rng.get_state() == rng_before


# --- timing ------------------------------------------------------------------


def test_nothing_happens_before_the_scheduled_tick() -> None:
    """The plan waits for its moment."""
    law = sharing_law()
    world = world_with(law, tick=99)
    rng_before = world.rng.get_state()
    log, _ = run_rule(world, change_at(100))
    assert len(log) == 0
    assert law == sharing_law()
    assert world.rng.get_state() == rng_before


def test_a_change_applies_exactly_at_the_scheduled_tick() -> None:
    """At tick T the law changes, provenance updates, and one event says so."""
    law = sharing_law(active=True, previous_value=None, current_value=True)
    world = world_with(law, tick=100)
    rng_before = world.rng.get_state()
    log, _ = run_rule(world, change_at(100, new_value=False))

    assert law.previous_value is True
    assert law.current_value is False
    assert law.active is False
    assert law.changed_episode == 0
    assert law.restored_tick is None

    events = log.query(event_type=EventType.LAW_CHANGED)
    assert len(events) == 1
    assert len(log) == 1
    assert events[0].tick == 100
    assert events[0].source_id == LAW_ID
    assert events[0].payload_as_dict() == {
        "active": False,
        "changed_episode": 0,
        "current_value": False,
        "previous_value": True,
    }
    assert world.rng.get_state() == rng_before


def test_a_change_clears_an_earlier_restoration_record() -> None:
    """A fresh change supersedes restoration provenance from an earlier episode."""
    law = sharing_law(
        active=True, previous_value=False, current_value=True, changed_episode=1, restored_tick=250
    )
    world = world_with(law, episode=2, tick=400)
    log, _ = run_rule(world, change_at(400, episode=2, new_value=False))
    assert law.restored_tick is None
    assert law.changed_episode == 2
    assert len(log) == 1


def test_an_applied_change_is_recognized_after_its_tick() -> None:
    """A World that already records the action is left alone, silently."""
    law = sharing_law(active=False, previous_value=True, current_value=False, changed_episode=0)
    world = world_with(law, tick=150)
    rng_before = world.rng.get_state()
    log, _ = run_rule(world, change_at(100, new_value=False))
    assert len(log) == 0
    assert law.current_value is False
    assert world.rng.get_state() == rng_before


def test_a_missed_change_is_refused_loudly() -> None:
    """A skipped intervention is an error, never a silent shrug."""
    law = sharing_law(active=True, previous_value=None, current_value=True)
    world = world_with(law, tick=101)
    rng_before = world.rng.get_state()
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    with pytest.raises(ValueError, match="missed"):
        RuleSystem([change_at(100, new_value=False)]).update(world, bus)
    assert law == sharing_law(active=True, previous_value=None, current_value=True)
    assert len(log) == 0
    assert world.rng.get_state() == rng_before


def test_a_missed_restoration_is_refused_loudly() -> None:
    """The same lateness rule holds for restorations."""
    law = sharing_law(active=False, previous_value=True, current_value=False)
    world = world_with(law, tick=300)
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    with pytest.raises(ValueError, match="missed"):
        RuleSystem([restore_at(250)]).update(world, bus)
    assert law == sharing_law(active=False, previous_value=True, current_value=False)
    assert len(log) == 0


def test_duplicate_updates_apply_once_and_emit_once() -> None:
    """The World's own provenance makes repeated updates harmless."""
    law = sharing_law(active=True, previous_value=None, current_value=True)
    world = world_with(law, tick=100)
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    system = RuleSystem([change_at(100, new_value=False)])
    system.update(world, bus)
    system.update(world, bus)
    system.update(world, bus)
    assert len(log) == 1
    assert law.current_value is False


# --- change preconditions ----------------------------------------------------


def test_a_semantic_no_op_change_is_refused() -> None:
    """An intervention that would change nothing is a scripting error."""
    law = sharing_law(active=True, previous_value=None, current_value=True, changed_episode=5)
    world = world_with(law, episode=6, tick=100)
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    with pytest.raises(ValueError, match="would not change"):
        RuleSystem(
            [ScheduledLawChange(episode=6, tick=100, law_id=LAW_ID, new_value=True, active=True)]
        ).update(world, bus)
    assert len(log) == 0
    assert law.changed_episode == 5


# --- restoration -------------------------------------------------------------


def test_a_restoration_swaps_values_and_records_the_tick() -> None:
    """The canonical Phase 11 example, produced by the real system."""
    law = sharing_law(active=False, previous_value=True, current_value=False, changed_episode=0)
    world = world_with(law, episode=1, tick=250)
    log, _ = run_rule(world, restore_at(250, episode=1))

    assert law.active is True
    assert law.previous_value is False
    assert law.current_value is True
    assert law.changed_episode == 1
    assert law.restored_tick == 250

    events = log.query(event_type=EventType.LAW_RESTORED)
    assert len(events) == 1
    assert len(log) == 1
    assert events[0].tick == 250
    assert events[0].source_id == LAW_ID
    assert events[0].payload_as_dict() == {
        "active": True,
        "changed_episode": 1,
        "current_value": True,
        "previous_value": False,
        "restored_tick": 250,
    }


def test_a_restoration_restores_exactly_the_stored_previous_value() -> None:
    """The schedule names no target; the law's own history is the target."""
    law = sharing_law(active=False, previous_value="open", current_value="sealed")
    world = world_with(law, tick=40)
    run_rule(world, restore_at(40))
    assert law.current_value == "open"
    assert law.previous_value == "sealed"


def test_an_active_law_cannot_be_restored() -> None:
    """Restoration switches a rule back; an active rule has nothing to switch."""
    law = sharing_law(active=True, previous_value=False, current_value=True)
    world = world_with(law, tick=250)
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    with pytest.raises(ValueError, match="inactive"):
        RuleSystem([restore_at(250)]).update(world, bus)
    assert len(log) == 0
    assert law.active is True


def test_a_previously_restored_law_is_not_restored_again() -> None:
    """A stale restoration record is inconsistent with restoring again."""
    law = sharing_law(active=False, previous_value=True, current_value=False, restored_tick=90)
    world = world_with(law, tick=250)
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    with pytest.raises(ValueError, match="already records a restoration"):
        RuleSystem([restore_at(250)]).update(world, bus)
    assert len(log) == 0


def test_an_applied_restoration_is_recognized_after_its_tick() -> None:
    """Once the World records the restoration, later updates stay silent."""
    law = sharing_law(
        active=True, previous_value=False, current_value=True, changed_episode=1, restored_tick=250
    )
    world = world_with(law, episode=1, tick=260)
    log, _ = run_rule(world, restore_at(250, episode=1))
    assert len(log) == 0
    assert law.restored_tick == 250


# --- corrupted stored state --------------------------------------------------


def corruptions() -> list[tuple[str, object]]:
    """Field corruptions that must be refused as found, never normalized."""
    return [
        ("id", "law_movement_sharing "),
        ("id", 5),
        ("name", "  "),
        ("name", " padded"),
        ("name", 7),
        ("active", 1),
        ("previous_value", (1,)),
        ("previous_value", IntSubclass(1)),
        ("current_value", float("nan")),
        ("current_value", ExactnessStrEnum.LABEL),
        ("changed_episode", True),
        ("changed_episode", -1),
        ("restored_tick", True),
        ("restored_tick", -5),
        ("restored_tick", "90"),
    ]


@pytest.mark.parametrize(("field", "bad"), corruptions())
def test_corrupted_stored_law_state_is_refused_before_mutation(field: str, bad: object) -> None:
    """Entities stay mutable, so stored state is validated as found."""
    law = sharing_law(active=True, previous_value=None, current_value=True)
    setattr(law, field, bad)
    world = world_with(law, tick=100)
    rng_before = world.rng.get_state()
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    with pytest.raises((TypeError, ValueError)):
        RuleSystem([change_at(100, new_value=False)]).update(world, bus)
    assert len(log) == 0
    assert world.rng.get_state() == rng_before
    assert getattr(law, field) is bad or getattr(law, field) == bad


def test_a_missing_law_is_refused() -> None:
    """A schedule naming an absent law cannot proceed."""
    world = world_with(None, tick=100)
    bus = EventBus()
    with pytest.raises(ValueError, match="does not exist"):
        RuleSystem([change_at(100)]).update(world, bus)


def test_an_identifier_of_another_entity_kind_is_refused() -> None:
    """A district's identifier is not a law, however real the district is."""
    world = world_with(sharing_law(), tick=100)
    world.add_district(build_district("district_a"))
    bus = EventBus()
    action = ScheduledLawChange(
        episode=0, tick=100, law_id="district_a", new_value=False, active=False
    )
    with pytest.raises(ValueError, match="does not exist"):
        RuleSystem([action]).update(world, bus)


def test_a_registry_and_index_disagreement_is_refused() -> None:
    """The two views of the law must agree on the very same object."""
    law = sharing_law()
    world = world_with(law, tick=100)
    world._entities[LAW_ID] = sharing_law()
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    with pytest.raises(ValueError, match="disagrees"):
        RuleSystem([change_at(100)]).update(world, bus)
    assert len(log) == 0


def test_a_shifty_law_subclass_cannot_reach_mutation() -> None:
    """A law that answers validation one way and application another is refused."""
    lie = {"armed": False}

    class ShiftyLaw(Law):
        """Reports inactive to validation, active to the apply check."""

        def __getattribute__(self, name: str) -> object:
            """Flip the active flag after arming."""
            if name == "active" and lie["armed"]:
                return True
            return super().__getattribute__(name)

    law = ShiftyLaw(
        id=LAW_ID,
        created_tick=0,
        name="movement_resource_sharing",
        active=False,
        previous_value=True,  # type: ignore[arg-type]
        current_value=False,  # type: ignore[arg-type]
        changed_episode=0,
        restored_tick=None,
    )
    world = world_with(law, tick=250)
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    system = RuleSystem([restore_at(250)])

    lie["armed"] = True
    with pytest.raises(ValueError):
        system.update(world, bus)
    assert len(log) == 0
    assert law.restored_tick is None


# --- static guards -----------------------------------------------------------


def test_rule_system_calls_no_direct_isinstance() -> None:
    """Type decisions come from the true runtime type, never ``__class__``."""
    tree = ast.parse(RULE_SYSTEM_SOURCE.read_text(encoding="utf-8"))
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "isinstance"
    ]
    assert offenders == []


def test_rule_system_imports_stay_inside_the_architecture() -> None:
    """RuleSystem touches entities, events, and its base class -- nothing more."""
    tree = ast.parse(RULE_SYSTEM_SOURCE.read_text(encoding="utf-8"))
    forbidden = (
        "living_diorama.persistence",
        "living_diorama.memory",
        "living_diorama.cli",
        "living_diorama.render",
        "living_diorama.narration",
    )
    runtime_modules: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            runtime_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            runtime_modules.append(node.module or "")
    for module in runtime_modules:
        assert not module.startswith(forbidden), module
        assert not module.startswith("living_diorama.simulation"), (
            "World must arrive under TYPE_CHECKING only"
        )
    assert "living_diorama.systems.base_system" in runtime_modules


def test_rule_system_performs_no_io_and_draws_no_randomness() -> None:
    """No file I/O, no RNG access, and no calls into other systems."""
    tree = ast.parse(RULE_SYSTEM_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "open"
        if isinstance(node, ast.Attribute):
            assert node.attr != "rng"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr != "update", "systems never call systems"


# --- the schedule is a semantic snapshot -------------------------------------


def shifty_change(lie: dict, field: str, shifted: object, **fields: object) -> ScheduledLawChange:
    """Build a change subclass that misreports one field once armed."""

    class ShiftyChange(ScheduledLawChange):
        """Answers honestly until armed, then lies about one field."""

        def __getattribute__(self, name: str) -> object:
            """Misreport the chosen field while the lie is armed."""
            if lie["armed"] and name == field:
                return shifted
            return super().__getattribute__(name)

    arguments: dict[str, object] = {
        "episode": 0,
        "tick": 100,
        "law_id": LAW_ID,
        "new_value": False,
        "active": False,
    }
    arguments.update(fields)
    return ShiftyChange(**arguments)  # type: ignore[arg-type]


def test_an_episode_migrating_action_cannot_move_episodes() -> None:
    """The schedule is what was captured, not what the caller later claims."""
    lie = {"armed": False}
    action = shifty_change(lie, "episode", 1)
    system = RuleSystem([action])
    lie["armed"] = True

    (entry,) = system.schedule
    assert type(entry) is ScheduledLawChange
    assert entry.episode == 0

    law = sharing_law()
    world = world_with(law, episode=1, tick=100)
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    system.update(world, bus)
    assert len(log) == 0
    assert law == sharing_law()


def test_a_tick_migrating_action_keeps_its_captured_tick() -> None:
    """The captured tick is authoritative for when the action fires."""
    lie = {"armed": False}
    action = shifty_change(lie, "tick", 999)
    system = RuleSystem([action])
    lie["armed"] = True

    law = sharing_law()
    world = world_with(law, tick=100)
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    system.update(world, bus)
    assert len(log) == 1
    assert law.current_value is False


def test_a_law_id_migrating_action_keeps_its_captured_target() -> None:
    """Only the originally captured law identifier is ever resolved."""
    lie = {"armed": False}
    action = shifty_change(lie, "law_id", "law_other")
    system = RuleSystem([action])
    lie["armed"] = True

    law = sharing_law()
    world = world_with(law, tick=100)
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    system.update(world, bus)
    assert len(log) == 1
    assert log.query(event_type=EventType.LAW_CHANGED)[0].source_id == LAW_ID
    assert law.current_value is False


def test_a_value_migrating_action_cannot_split_event_and_world() -> None:
    """Event, mutation, and capture all agree on one new value."""
    lie = {"armed": False}
    action = shifty_change(lie, "new_value", "shifted")
    system = RuleSystem([action])
    lie["armed"] = True

    law = sharing_law()
    world = world_with(law, tick=100)
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    system.update(world, bus)

    event = log.query(event_type=EventType.LAW_CHANGED)[0]
    assert event.payload_as_dict()["current_value"] is False
    assert law.current_value is False


def test_an_active_migrating_action_cannot_split_event_and_world() -> None:
    """The captured active flag is authoritative for event and law alike."""
    lie = {"armed": False}
    action = shifty_change(lie, "active", True)
    system = RuleSystem([action])
    lie["armed"] = True

    law = sharing_law()
    world = world_with(law, tick=100)
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    system.update(world, bus)

    event = log.query(event_type=EventType.LAW_CHANGED)[0]
    assert event.payload_as_dict()["active"] is False
    assert law.active is False


def test_the_schedule_holds_only_exact_base_actions() -> None:
    """No caller subclass survives into the stored schedule."""
    lie = {"armed": False}
    system = RuleSystem(
        [
            shifty_change(lie, "episode", 5),
            ScheduledLawRestore(episode=1, tick=250, law_id=LAW_ID),
        ]
    )
    assert type(system.schedule) is tuple
    assert [type(entry) for entry in system.schedule] == [
        ScheduledLawChange,
        ScheduledLawRestore,
    ]


def test_every_action_field_is_read_exactly_once_at_construction() -> None:
    """The snapshot reads each semantic field once and never returns."""
    counts = {"episode": 0, "tick": 0, "law_id": 0, "new_value": 0, "active": 0}
    armed = {"on": False}

    class CountingChange(ScheduledLawChange):
        """Counts armed reads of every semantic field."""

        def __getattribute__(self, name: str) -> object:
            """Tally the read when armed, then answer honestly."""
            if armed["on"] and name in counts:
                counts[name] += 1
            return super().__getattribute__(name)

    action = CountingChange(episode=0, tick=100, law_id=LAW_ID, new_value=False, active=False)
    armed["on"] = True
    system = RuleSystem([action])
    assert counts == {"episode": 1, "tick": 1, "law_id": 1, "new_value": 1, "active": 1}

    law = sharing_law()
    world = world_with(law, tick=100)
    bus = EventBus()
    system.update(world, bus)
    assert counts == {"episode": 1, "tick": 1, "law_id": 1, "new_value": 1, "active": 1}, (
        "the caller's action is never consulted again after construction"
    )


# --- the law is a semantic snapshot ------------------------------------------


def test_a_shifting_current_value_cannot_split_event_and_mutation() -> None:
    """The first validated read of current_value is the one authoritative value."""
    lie = {"armed": False}
    reads = {"count": 0}

    class ShiftyValueLaw(Law):
        """Answers True to the first armed current_value read, then shifts."""

        def __getattribute__(self, name: str) -> object:
            """Shift current_value after its first armed read."""
            if lie["armed"] and name == "current_value":
                reads["count"] += 1
                return True if reads["count"] == 1 else "later"
            return super().__getattribute__(name)

    law = ShiftyValueLaw(
        id=LAW_ID,
        created_tick=0,
        name="movement_resource_sharing",
        active=True,
        previous_value=None,
        current_value=True,  # type: ignore[arg-type]
        changed_episode=0,
        restored_tick=None,
    )
    world = world_with(law, tick=100)
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)

    lie["armed"] = True
    RuleSystem([change_at(100, new_value=False)]).update(world, bus)
    lie["armed"] = False

    event = log.query(event_type=EventType.LAW_CHANGED)[0]
    assert event.payload_as_dict()["previous_value"] is True
    assert law.previous_value is True
    assert law.current_value is False


def test_a_shifting_law_cannot_corrupt_a_restoration() -> None:
    """The first validated reads are what the restoration restores."""
    lie = {"armed": False}
    reads = {"previous_value": 0, "current_value": 0}

    class ShiftyRestoreLaw(Law):
        """Answers honestly on first armed reads, then shifts both values."""

        def __getattribute__(self, name: str) -> object:
            """Shift the value fields after their first armed reads."""
            if lie["armed"] and name in reads:
                reads[name] += 1
                if reads[name] > 1:
                    return f"different-{name}"
            return super().__getattribute__(name)

    law = ShiftyRestoreLaw(
        id=LAW_ID,
        created_tick=0,
        name="movement_resource_sharing",
        active=False,
        previous_value=True,  # type: ignore[arg-type]
        current_value=False,  # type: ignore[arg-type]
        changed_episode=0,
        restored_tick=None,
    )
    world = world_with(law, tick=250)
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)

    lie["armed"] = True
    RuleSystem([restore_at(250)]).update(world, bus)
    lie["armed"] = False

    event = log.query(event_type=EventType.LAW_RESTORED)[0]
    assert event.payload_as_dict()["current_value"] is True
    assert event.payload_as_dict()["previous_value"] is False
    assert law.previous_value is False
    assert law.current_value is True


def test_a_shifting_id_cannot_relabel_the_event_source() -> None:
    """The validated snapshot identifier is the event's source, always."""
    lie = {"armed": False}
    reads = {"count": 0}

    class ShiftyIdLaw(Law):
        """Answers the registry key once, then claims another identifier."""

        def __getattribute__(self, name: str) -> object:
            """Shift the id after its first armed read."""
            if lie["armed"] and name == "id":
                reads["count"] += 1
                return LAW_ID if reads["count"] == 1 else "other_law"
            return super().__getattribute__(name)

    law = ShiftyIdLaw(
        id=LAW_ID,
        created_tick=0,
        name="movement_resource_sharing",
        active=True,
        previous_value=None,
        current_value=True,  # type: ignore[arg-type]
        changed_episode=0,
        restored_tick=None,
    )
    world = world_with(law, tick=100)
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)

    lie["armed"] = True
    RuleSystem([change_at(100, new_value=False)]).update(world, bus)
    lie["armed"] = False

    assert log.query(event_type=EventType.LAW_CHANGED)[0].source_id == LAW_ID


def test_every_law_semantic_field_is_read_exactly_once() -> None:
    """One semantic capture, and no live re-read between validation and mutation."""
    counts = {
        "id": 0,
        "created_tick": 0,
        "name": 0,
        "active": 0,
        "previous_value": 0,
        "current_value": 0,
        "changed_episode": 0,
        "restored_tick": 0,
    }
    armed = {"on": False}

    class CountingLaw(Law):
        """Counts armed reads of every semantic field."""

        def __getattribute__(self, name: str) -> object:
            """Tally the read when armed, then answer honestly."""
            if armed["on"] and name in counts:
                counts[name] += 1
            return super().__getattribute__(name)

    law = CountingLaw(
        id=LAW_ID,
        created_tick=0,
        name="movement_resource_sharing",
        active=True,
        previous_value=None,
        current_value=True,  # type: ignore[arg-type]
        changed_episode=0,
        restored_tick=None,
    )
    world = world_with(law, tick=100)
    bus = EventBus()
    system = RuleSystem([change_at(100, new_value=False)])

    armed["on"] = True
    system.update(world, bus)
    armed["on"] = False

    assert counts == {
        "id": 1,
        "created_tick": 1,
        "name": 1,
        "active": 1,
        "previous_value": 1,
        "current_value": 1,
        "changed_episode": 1,
        "restored_tick": 1,
    }
