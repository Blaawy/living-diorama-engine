"""One scheduled rule intervention per episode, applied first in the tick.

The show's core mechanic is a single changed rule per episode: at a chosen
tick, exactly one law changes or is restored, and everything else that happens
is downstream consequence. RuleSystem owns that intervention. It mutates law
state *only* -- never districts, resources, boundaries, walls, infrastructure,
time, or randomness -- which is what makes a restored law incapable of erasing
a permanent wall.

The system holds a fixed schedule and no other state. Whether an action has
already been applied is read from the Law's own provenance fields, so a
duplicate pipeline entry or a repeated update cannot double-apply an action or
publish a second event: the World is the authority, not a process-local flag.

Validation here follows the engine's hardened discipline: caller-owned values
are judged by their true runtime type (``type(...) is`` for exact scalar
contracts, ``issubclass(type(...), ...)`` for domain objects), never through
``isinstance``, which can hand control to a hostile ``__class__`` override.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeIs, cast

from living_diorama.entities import EntityId, Law, LawValue, Tick
from living_diorama.events import Event, EventBus, EventType
from living_diorama.systems.base_system import BaseSystem

if TYPE_CHECKING:  # pragma: no cover - import exists for typing only
    from living_diorama.simulation.world import World


def _require_exact_int(value: object, description: str) -> int:
    """Return the value if it is an exact non-negative ``int``, else raise.

    ``bool`` is refused because it subclasses ``int``: a ``True`` episode would
    otherwise become episode 1, and nothing downstream could tell.

    Raises:
        TypeError: If the value is not an exact ``int``.
        ValueError: If it is negative.
    """
    if type(value) is not int:
        raise TypeError(f"{description} must be an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{description} must be >= 0, got {value}")
    return value


def _require_exact_bool(value: object, description: str) -> bool:
    """Return the value if it is exactly a ``bool``, else raise.

    Raises:
        TypeError: If the value is not exactly a ``bool``.
    """
    if type(value) is not bool:
        raise TypeError(f"{description} must be a bool, got {type(value).__name__}")
    return value


def _require_identifier(value: object, description: str) -> EntityId:
    """Return the value if it is a canonical identifier, else raise.

    Corrupted identifiers are refused as found, never stripped or repaired:
    normalizing here would target a different entity than the one configured.

    Raises:
        TypeError: If the value is not exactly a ``str``.
        ValueError: If it is empty, whitespace-only, or carries surrounding
            whitespace.
    """
    if type(value) is not str:
        raise TypeError(f"{description} must be a str, got {type(value).__name__}")
    if not value:
        raise ValueError(f"{description} must not be empty")
    if not value.strip():
        raise ValueError(f"{description} must not be only whitespace, got {value!r}")
    if value.strip() != value:
        raise ValueError(f"{description} must not carry surrounding whitespace, got {value!r}")
    return value


def _require_law_value(value: object, description: str) -> LawValue:
    """Return a law scalar unchanged, preserving its exact Python type.

    A law's value is what an episode changes, so its type carries meaning:
    ``True``, ``1``, and ``"1"`` are three different settings. ``type(...)``
    alone decides, refusing IntEnum and StrEnum members, primitive subclasses,
    containers, and non-finite floats. The casts are sound because each exact
    check has already proven the type.

    Raises:
        TypeError: If the value is not ``None``, ``bool``, ``int``, ``float``,
            or ``str``.
        ValueError: If a float is not finite.
    """
    if value is None:
        return None
    value_type = type(value)
    if value_type is bool:
        return cast(bool, value)
    if value_type is int:
        return cast(int, value)
    if value_type is str:
        return cast(str, value)
    if value_type is float:
        number = cast(float, value)
        if not math.isfinite(number):
            raise ValueError(f"{description} must be finite, got {number!r}")
        return number
    raise TypeError(
        f"{description} must be null, a bool, an int, a finite float, or a str, "
        f"got {value_type.__name__}"
    )


def _same_value(left: LawValue, right: LawValue) -> bool:
    """Report whether two law values agree in both exact type and value.

    Plain equality would conflate ``True`` with ``1`` and ``1`` with ``1.0``;
    a law's setting is its exact scalar, so agreement requires both.
    """
    return type(left) is type(right) and left == right


@dataclass(frozen=True, slots=True)
class ScheduledLawChange:
    """One planned law change: at an episode and tick, a law takes a new value.

    At the scheduled moment the law's ``current_value`` becomes its
    ``previous_value``, ``new_value`` becomes ``current_value``, ``active``
    becomes the law's active flag, ``changed_episode`` becomes the world's
    episode, and ``restored_tick`` returns to ``None``. Exactly one
    ``LAW_CHANGED`` event describes the change.

    Attributes:
        episode: Episode in which the change applies.
        tick: Absolute world tick at which the change applies.
        law_id: Identifier of the law to change.
        new_value: The exact scalar the law will hold afterwards.
        active: Whether the law is in force afterwards.
    """

    episode: int
    tick: Tick
    law_id: EntityId
    new_value: LawValue
    active: bool

    def __post_init__(self) -> None:
        """Validate every field exactly as supplied.

        Raises:
            TypeError: If a field is of the wrong exact type.
            ValueError: If a number is negative or not finite, or the
                identifier is noncanonical.
        """
        _require_exact_int(self.episode, "episode")
        _require_exact_int(self.tick, "tick")
        _require_identifier(self.law_id, "law_id")
        _require_law_value(self.new_value, "new_value")
        _require_exact_bool(self.active, "active")


@dataclass(frozen=True, slots=True)
class ScheduledLawRestore:
    """One planned restoration: at an episode and tick, a law is switched back.

    At the scheduled moment the value being restored is exactly the law's
    stored ``previous_value``. The old ``current_value`` becomes the new
    ``previous_value``, the restored value becomes ``current_value``, the law
    becomes active, ``changed_episode`` becomes the world's episode, and
    ``restored_tick`` records the world tick. Exactly one ``LAW_RESTORED``
    event describes the restoration.

    Attributes:
        episode: Episode in which the restoration applies.
        tick: Absolute world tick at which the restoration applies.
        law_id: Identifier of the law to restore.
    """

    episode: int
    tick: Tick
    law_id: EntityId

    def __post_init__(self) -> None:
        """Validate every field exactly as supplied.

        Raises:
            TypeError: If a field is of the wrong exact type.
            ValueError: If a number is negative or the identifier is
                noncanonical.
        """
        _require_exact_int(self.episode, "episode")
        _require_exact_int(self.tick, "tick")
        _require_identifier(self.law_id, "law_id")


def _is_change_like(value: object) -> TypeIs[ScheduledLawChange]:
    """Report whether a value is in the change family, from its true type."""
    return issubclass(type(value), ScheduledLawChange)


def _is_restore_like(value: object) -> TypeIs[ScheduledLawRestore]:
    """Report whether a value is in the restore family, from its true type."""
    return issubclass(type(value), ScheduledLawRestore)


def _snapshot_action(value: object, index: int) -> ScheduledLawChange | ScheduledLawRestore:
    """Capture one schedule entry into an exact base scheduled action.

    The caller's object is consulted exactly once per semantic field and never
    retained, so a subclass that answers construction one way and later
    updates another cannot move an action between episodes, ticks, laws, or
    values. Constructing the exact base class revalidates every captured
    value.

    Raises:
        TypeError: If the value is not a scheduled action, or a captured field
            is of the wrong exact type.
        ValueError: If a captured field carries an invalid value.
    """
    if _is_change_like(value):
        episode = value.episode
        tick = value.tick
        law_id = value.law_id
        new_value = value.new_value
        active = value.active
        return ScheduledLawChange(
            episode=episode, tick=tick, law_id=law_id, new_value=new_value, active=active
        )
    if _is_restore_like(value):
        episode = value.episode
        tick = value.tick
        law_id = value.law_id
        return ScheduledLawRestore(episode=episode, tick=tick, law_id=law_id)
    raise TypeError(
        f"schedule[{index}] must be a ScheduledLawChange or "
        f"ScheduledLawRestore, got {type(value).__name__}"
    )


@dataclass(frozen=True, slots=True)
class _LawSnapshot:
    """One semantic reading of a Law, captured before any decision is made.

    Validation, idempotency, preconditions, the event, and the mutation all
    reason from this single immutable capture, so a stateful Law subclass
    cannot answer validation one way and application another.
    """

    id: EntityId
    created_tick: Tick
    name: str
    active: bool
    previous_value: LawValue
    current_value: LawValue
    changed_episode: int
    restored_tick: Tick | None


class RuleSystem(BaseSystem):
    """Applies at most one scheduled law action for the current episode.

    The schedule is fixed at construction and validated as a whole: an episode
    may hold exactly one action, because one changed rule per episode is the
    world's core mechanic. The system runs first in the canonical pipeline --
    an ordering held by ``SimulationLoop``, not by this class -- so a change
    scheduled for tick T is visible to every downstream system during tick T.

    Whether the action already happened is read from the Law's own provenance
    (``changed_episode``, ``restored_tick``, ``active``, ``current_value``),
    never from hidden internal state, so repeated updates and duplicate
    pipeline entries are harmless no-ops once the World records the action.

    RuleSystem performs no persistence, no memory distillation, no filesystem
    I/O, calls no other system, and draws no randomness.
    """

    __slots__ = ("_schedule",)

    def __init__(self, schedule: Sequence[ScheduledLawChange | ScheduledLawRestore]) -> None:
        """Create a rule system over a validated, defensively copied schedule.

        Args:
            schedule: The planned actions, at most one per episode. May be
                empty. Copied; the caller's sequence is never retained.

        Raises:
            TypeError: If an entry is not a scheduled action.
            ValueError: If two entries claim the same episode.
        """
        # Each caller entry is captured once into an exact base action; the
        # caller's objects are never stored and never consulted again. The
        # snapshot and the duplicate-episode check run entry by entry, so a
        # schedule with several problems reports the earliest one.
        normalized: list[ScheduledLawChange | ScheduledLawRestore] = []
        claimed: set[int] = set()
        for index, entry in enumerate(schedule):
            action = _snapshot_action(entry, index)
            if action.episode in claimed:
                raise ValueError(
                    f"the schedule holds more than one action for episode "
                    f"{action.episode}; an episode changes exactly one rule"
                )
            claimed.add(action.episode)
            normalized.append(action)
        self._schedule = tuple(normalized)

    @property
    def schedule(self) -> tuple[ScheduledLawChange | ScheduledLawRestore, ...]:
        """The validated schedule, in the order it was supplied."""
        return self._schedule

    def update(self, world: "World", bus: EventBus) -> None:
        """Apply the current episode's scheduled action when its tick arrives.

        Before the scheduled tick, and in episodes with no scheduled action,
        this is a no-op. At the scheduled tick the action is applied exactly
        once. After the scheduled tick, a World whose Law state already records
        the action is left alone; a World that missed the action is refused.

        Raises:
            TypeError: If the world's clock or the stored Law state is
                mistyped.
            ValueError: If the scheduled law is missing or corrupted, the
                action was missed, or a change would not change anything.
        """
        episode = _require_exact_int(world.episode, "world.episode")
        tick = _require_exact_int(world.tick, "world.tick")

        action = next((entry for entry in self._schedule if entry.episode == episode), None)
        if action is None:
            return
        if tick < action.tick:
            return

        law, snapshot = self._resolve_law(world, action.law_id)
        if _is_change_like(action):
            self._apply_change(bus, action, law, snapshot, episode, tick)
        else:
            self._apply_restore(bus, action, law, snapshot, episode, tick)

    def _resolve_law(self, world: "World", law_id: EntityId) -> tuple[Law, _LawSnapshot]:
        """Return the scheduled law and one validated semantic snapshot of it.

        Entities stay mutable after construction, so nothing the constructor
        proved is assumed to still hold. The typed registry and the aggregate
        entity index must agree on the same object, each semantic field is read
        exactly once, and the validated capture is the only state any later
        decision may consult.

        Raises:
            TypeError: If the stored object is not a Law or a field is
                mistyped.
            ValueError: If the law is missing, its identity disagrees with the
                registry, or a stored value is corrupted.
        """
        registry = world.laws
        if law_id not in registry:
            raise ValueError(f"scheduled law {law_id!r} does not exist in the world")
        law = registry[law_id]
        if not issubclass(type(law), Law):
            raise TypeError(f"law {law_id!r} must be a Law, got {type(law).__name__}")
        if not world.has_entity(law_id) or world.get_entity(law_id) is not law:
            raise ValueError(
                f"the aggregate entity index disagrees with the law registry about {law_id!r}"
            )

        # One read per semantic field. A stateful subclass need not answer the
        # same way twice, so validation, every decision, the event, and the
        # mutation all reason from these captures alone.
        raw_id = law.id
        raw_created = law.created_tick
        name = law.name
        raw_active = law.active
        raw_previous = law.previous_value
        raw_current = law.current_value
        raw_changed = law.changed_episode
        raw_restored = law.restored_tick

        stored_id = _require_identifier(raw_id, f"id of law {law_id!r}")
        if stored_id != law_id:
            raise ValueError(f"law registry key {law_id!r} disagrees with its entity's id")
        created_tick = _require_exact_int(raw_created, f"created_tick of law {law_id!r}")
        if type(name) is not str:
            raise TypeError(f"name of law {law_id!r} must be a str, got {type(name).__name__}")
        if not name.strip():
            raise ValueError(f"name of law {law_id!r} must not be blank")
        if name.strip() != name:
            raise ValueError(f"name of law {law_id!r} carries surrounding whitespace")
        active = _require_exact_bool(raw_active, f"active of law {law_id!r}")
        previous_value = _require_law_value(raw_previous, f"previous_value of law {law_id!r}")
        current_value = _require_law_value(raw_current, f"current_value of law {law_id!r}")
        changed_episode = _require_exact_int(raw_changed, f"changed_episode of law {law_id!r}")
        restored_tick = (
            None
            if raw_restored is None
            else _require_exact_int(raw_restored, f"restored_tick of law {law_id!r}")
        )
        return law, _LawSnapshot(
            id=stored_id,
            created_tick=created_tick,
            name=name,
            active=active,
            previous_value=previous_value,
            current_value=current_value,
            changed_episode=changed_episode,
            restored_tick=restored_tick,
        )

    def _apply_change(
        self,
        bus: EventBus,
        action: ScheduledLawChange,
        law: Law,
        snapshot: _LawSnapshot,
        episode: int,
        tick: Tick,
    ) -> None:
        """Apply one scheduled change, or recognize it as already applied.

        Every decision, the event, and the mutation reason from the one
        validated snapshot; the live law is touched only to write.

        Raises:
            ValueError: If the action was missed, or would not change the law.
        """
        applied = (
            snapshot.changed_episode == episode
            and snapshot.active is action.active
            and _same_value(snapshot.current_value, action.new_value)
            and snapshot.restored_tick is None
        )
        if applied:
            return
        if tick > action.tick:
            raise ValueError(
                f"the change scheduled for episode {episode} tick {action.tick} was "
                f"missed; the world is already at tick {tick} and the law does not "
                f"record it"
            )
        if snapshot.active is action.active and _same_value(
            snapshot.current_value, action.new_value
        ):
            raise ValueError(
                f"the change scheduled for episode {episode} tick {action.tick} would "
                f"not change law {snapshot.id!r}; a scheduled intervention must mean "
                f"something"
            )

        # Stage everything before touching the law: the event is built from the
        # captured pre-mutation state, and only a fully constructed event may
        # be published after the mutation lands.
        event = Event(
            tick=tick,
            type=EventType.LAW_CHANGED,
            payload={
                "active": action.active,
                "changed_episode": episode,
                "current_value": action.new_value,
                "previous_value": snapshot.current_value,
            },
            source_id=snapshot.id,
        )

        law.previous_value = snapshot.current_value
        law.current_value = action.new_value
        law.active = action.active
        law.changed_episode = episode
        law.restored_tick = None
        bus.publish(event)

    def _apply_restore(
        self,
        bus: EventBus,
        action: ScheduledLawRestore,
        law: Law,
        snapshot: _LawSnapshot,
        episode: int,
        tick: Tick,
    ) -> None:
        """Apply one scheduled restoration, or recognize it as already applied.

        The value restored is exactly the captured ``previous_value``; the
        schedule never carries a separate restore target, and every decision,
        the event, and the mutation reason from the one validated snapshot.

        Raises:
            ValueError: If the action was missed, or the stored state is not a
                legitimate restoration candidate.
        """
        applied = (
            snapshot.changed_episode == episode
            and snapshot.restored_tick == action.tick
            and snapshot.active is True
        )
        if applied:
            return
        if tick > action.tick:
            raise ValueError(
                f"the restoration scheduled for episode {episode} tick {action.tick} "
                f"was missed; the world is already at tick {tick} and the law does "
                f"not record it"
            )
        if snapshot.active is not False:
            raise ValueError(
                f"law {snapshot.id!r} cannot be restored: only a law that is currently "
                f"inactive can be switched back"
            )
        if snapshot.restored_tick is not None:
            raise ValueError(
                f"law {snapshot.id!r} cannot be restored: it already records a "
                f"restoration at tick {snapshot.restored_tick}"
            )

        restored_value = snapshot.previous_value
        displaced_value = snapshot.current_value
        event = Event(
            tick=tick,
            type=EventType.LAW_RESTORED,
            payload={
                "active": True,
                "changed_episode": episode,
                "current_value": restored_value,
                "previous_value": displaced_value,
                "restored_tick": tick,
            },
            source_id=snapshot.id,
        )

        law.previous_value = displaced_value
        law.current_value = restored_value
        law.active = True
        law.changed_episode = episode
        law.restored_tick = tick
        bus.publish(event)
