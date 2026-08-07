"""Shared integrity rules for durable history.

The significance contract has to hold in three places: when an episode is
distilled, when a memory is offered to be saved, and when one is read back. This
module is that contract, written once. Implementing it three times would let the
three drift apart, and the one that drifted would be whichever nobody was
looking at.

Everything here is pure. No file is read or written, no event is published, no
random number is drawn, and no input is modified.
"""

from collections.abc import Mapping, Sequence
from typing import Final

from living_diorama.entities import Boundary, District, EntityId, Law, Wall
from living_diorama.events import Event, EventLog, EventType
from living_diorama.memory.world_memory import (
    MemoryFact,
    MemoryFactType,
    WorldMemory,
    _is_runtime_instance,
    _thaw,
    require_exact_int,
    require_exact_str,
    require_flag,
    require_identifier,
    require_law_value,
    require_text,
    require_unit_interval,
    wall_build_facts,
)
from living_diorama.simulation.world import World

SIGNIFICANT_EVENT_TYPES: Final[frozenset[EventType]] = frozenset(
    {EventType.WALL_BUILT, EventType.LAW_RESTORED}
)
"""The only event types the MVP converts into durable facts.

Everything else stays in the episode log. Nothing is lost -- the log is
persisted in full -- but only these two are asserted as history the world will
still be repeating many episodes from now.
"""


def snapshot_event_log(event_log: EventLog) -> tuple[Event, ...]:
    """Read a log once and return exact base Events holding its semantic values.

    Capturing ``tuple(event_log.events())`` freezes which objects are in the log.
    It does not freeze what those objects say. An Event subclass may answer
    ``payload_as_dict()`` differently on its third call than its first, and the
    later phases of a save -- validation, serialization, the manifest count --
    each ask again. That is how a writer ends up publishing an episode whose
    stored events contradict its stored memory, and which its own loader refuses.

    So each field is read exactly once and a plain :class:`Event` is built from
    the captured values. The base constructor performs the usual deep freeze and
    exact validation, and no caller-owned object survives into the result.

    The captured ``source_id`` is validated as itself before the base Event is
    built. The base constructor is forgiving on purpose -- it strips surrounding
    whitespace and accepts ``str`` subclasses -- but a snapshot's job is to
    record what the event reported, not to repair it. A padded or subclassed
    identifier laundered into a clean one would let a corrupt event pass
    validation as something it never said, so it is refused instead. ``None``
    remains permitted for event types that legitimately carry no source, and
    internal whitespace remains legal.

    Args:
        event_log: The caller's log. Read once, never modified.

    Returns:
        Exact base Events, in occurrence order, duplicates preserved.

    Raises:
        TypeError: If the argument is not an ``EventLog``, an entry is not an
            ``Event``, or a captured ``source_id`` is neither ``None`` nor
            exactly a ``str``.
        ValueError: If a captured ``source_id`` is blank or carries surrounding
            whitespace, or a captured field fails Event validation.
    """
    if not _is_runtime_instance(event_log, EventLog):
        raise TypeError(f"event_log must be an EventLog, got {type(event_log).__name__}")

    occurrences = tuple(event_log.events())
    captured: list[Event] = []
    for index, event in enumerate(occurrences):
        if not _is_runtime_instance(event, Event):
            raise TypeError(f"event_log entry {index} must be an Event, got {type(event).__name__}")
        # One read each. Re-reading is what let a stateful subclass say one thing
        # to validation and another to serialization.
        tick = event.tick
        event_type = event.type
        source_id = event.source_id
        if source_id is not None:
            source_id = require_identifier(source_id, f"event_log entry {index} source_id")
        payload = event.payload_as_dict()
        captured.append(
            Event(
                tick=tick,
                type=event_type,
                # The base constructor deep-freezes and validates this thawed
                # payload at runtime. Its field annotation describes the frozen
                # result, which the freeze refuses as input by design, so the
                # supplied shape cannot be expressed to the checker.
                payload=payload,  # type: ignore[arg-type]
                source_id=source_id,
            )
        )
    return tuple(captured)


def snapshot_memory_fact(value: object, description: str) -> MemoryFact:
    """Return an exact base MemoryFact holding this fact's semantic values.

    ``__eq__``, ``to_document()``, and ``details_as_dict()`` are all overridable.
    A subclass can therefore compare equal to the fact validation expects while
    serializing something else entirely -- validation and persistence would be
    consulting two different objects that merely agree when asked politely.

    Each semantic field is read once and a plain :class:`MemoryFact` is rebuilt
    from it. The rebuilt fact derives its own identifier and summary, and the
    values the caller claimed must match them. From then on only the base object
    is used, so its ``to_document()`` is the only document that can reach disk.

    The claimed identifier and summary are validated as exact plain strings
    before they are compared, matching what ``MemoryFact.from_document`` already
    demands of a persisted document. Equality alone would accept a ``str``
    subclass -- or anything whose ``__eq__`` chooses to agree -- and a malformed
    derived field must be refused as it stands, never silently replaced with the
    normalized one.

    Args:
        value: The fact to normalize.
        description: What is being normalized, used in error messages.

    Returns:
        An exact base ``MemoryFact``.

    Raises:
        TypeError: If the value is not a ``MemoryFact``, a field is mistyped, or
            the claimed identifier or summary is not exactly a ``str``.
        ValueError: If the claimed identifier or summary is not what the fact's
            own content implies.
    """
    if not _is_runtime_instance(value, MemoryFact):
        raise TypeError(f"{description} must be a MemoryFact, got {type(value).__name__}")

    fact_type = value.fact_type
    episode = value.episode
    tick = value.tick
    source_event_index = value.source_event_index
    source_event_type = value.source_event_type
    source_id = value.source_id
    subject_ids = value.subject_ids
    # Thawed with this package's own converter rather than the fact's
    # ``details_as_dict()``, which a subclass may override. The stored mapping is
    # already frozen, and the constructor re-freezes from plain JSON.
    details = _thaw(value.details)
    claimed_id = require_exact_str(value.fact_id, f"{description} fact_id")
    claimed_summary = require_exact_str(value.summary, f"{description} summary")

    normalized = MemoryFact(
        fact_type=fact_type,
        episode=episode,
        tick=tick,
        source_event_index=source_event_index,
        source_event_type=source_event_type,
        source_id=source_id,
        subject_ids=subject_ids,
        # The constructor re-freezes and validates the thawed details at
        # runtime. Its field annotation describes the frozen result, which
        # ``_freeze`` refuses as input by design, so the supplied shape cannot
        # be expressed to the checker.
        details=details,  # type: ignore[arg-type]
    )
    if claimed_id != normalized.fact_id:
        raise ValueError(
            f"{description} claims fact_id {claimed_id!r} but its content implies "
            f"{normalized.fact_id!r}"
        )
    if claimed_summary != normalized.summary:
        raise ValueError(f"{description} claims a summary that its content does not imply")
    return normalized


def snapshot_world_memory(value: object, description: str = "world_memory") -> WorldMemory:
    """Return an exact base WorldMemory holding this memory's semantic values.

    The same argument as for facts, one level up: ``facts``, ``through_episode``,
    and ``through_tick`` are all overridable properties, and a memory that
    reported one fact to validation and none to serialization would publish an
    episode whose events describe something its memory does not.

    Each is read once, every fact is normalized, and the result is rebuilt
    through the ordinary constructor -- so canonical ordering, duplicate
    identifiers, cross-fact provenance, and the checkpoint are all re-established
    on the object that will actually be used.

    Args:
        value: The memory to normalize.
        description: What is being normalized, used in error messages.

    Returns:
        An exact base ``WorldMemory`` whose facts are exact base facts.

    Raises:
        TypeError: If the value is not a ``WorldMemory`` or a field is mistyped.
        ValueError: If the captured facts do not form a valid memory.
    """
    if not _is_runtime_instance(value, WorldMemory):
        raise TypeError(f"{description} must be a WorldMemory, got {type(value).__name__}")

    through_episode = value.through_episode
    through_tick = value.through_tick
    facts = value.facts
    if type(facts) is not tuple:
        raise TypeError(f"{description} facts must be a tuple, got {type(facts).__name__}")
    normalized = tuple(
        snapshot_memory_fact(fact, f"{description} facts[{index}]")
        for index, fact in enumerate(facts)
    )
    return WorldMemory(normalized, through_episode=through_episode, through_tick=through_tick)


def require_registry_entry[EntityT](
    world: World,
    registry: Mapping[EntityId, object],
    expected_id: EntityId,
    *,
    kind: str,
    expected_type: type[EntityT],
) -> EntityT:
    """Return a registry entry after proving it is the entity it claims to be.

    A dictionary lookup is not proof of exactness. A ``str`` subclass hashes and
    compares like the string it copies, so ``registry[expected_id]`` finds an
    entry stored under a subclass key, and ``entity.id != expected_id`` is false
    for a subclass id. Both would then travel into a fact and into a save as
    something that is not the ``str`` the engine's stored-state contract
    requires.

    So the actual stored key is located and checked as itself, and so is the
    entity's own identifier. The aggregate index is checked too, because a fact
    depending on an entity should not be recorded while the world's two views of
    that entity disagree.

    Carrying the right attribute names is not the same as being the right thing.
    A typed registry is supposed to hold domain entities, and an object that
    merely answers to ``id`` and ``built_tick`` has none of the validation those
    classes perform -- so a durable fact derived from it would record state the
    engine never agreed to. The runtime type is therefore required before any
    entity-specific field is read, matching what the Phase 10 serializers already
    demand.

    A runtime-type subclass check rather than an exact type check: a legitimate
    subclass of a domain entity is not forbidden by any existing contract, and
    inventing that prohibition here would be a rule nobody agreed to. The check
    still never consults the stored object's own ``__class__``.

    Args:
        world: The world the registry belongs to.
        registry: The typed registry to look in.
        expected_id: The identifier being resolved.
        kind: What is being resolved, used in error messages.
        expected_type: The domain class this registry is supposed to hold.

    Returns:
        The stored entity.

    Raises:
        TypeError: If an identifier or key is not exactly a ``str``, or the
            stored object is not an instance of ``expected_type``.
        ValueError: If the entry is missing, its key or id is noncanonical or
            does not match, or the aggregate index disagrees.
    """
    require_identifier(expected_id, f"{kind} id")
    matches = [key for key in registry if key == expected_id]
    if not matches:
        raise ValueError(f"{kind} {expected_id!r} does not exist in the world")
    if len(matches) > 1:  # pragma: no cover - a mapping cannot hold equal keys twice
        raise ValueError(f"{kind} {expected_id!r} is stored under several keys")

    actual_key = matches[0]
    require_identifier(actual_key, f"{kind} registry key")
    if actual_key != expected_id:  # pragma: no cover - guaranteed by the match above
        raise ValueError(f"{kind} registry key {actual_key!r} disagrees with {expected_id!r}")

    entity = registry[actual_key]
    if not _is_runtime_instance(entity, expected_type):
        raise TypeError(
            f"{kind} {expected_id!r} must be a {expected_type.__name__}, got "
            f"{type(entity).__name__}"
        )
    entity_id = getattr(entity, "id", None)
    require_identifier(entity_id, f"id of {kind} {expected_id!r}")
    if entity_id != expected_id:
        raise ValueError(
            f"{kind} registry key {expected_id!r} disagrees with its entity's id {entity_id!r}"
        )

    require_aggregate_entry(world, expected_id, entity, kind)
    return entity


def require_aggregate_entry(world: World, expected_id: EntityId, entity: object, kind: str) -> None:
    """Verify the aggregate entity index agrees about this entity.

    The one place this module looks at a private ``World`` attribute, and it only
    reads. The index key has to be inspected as itself for the same reason a
    registry key does: a subclass key is found by every public lookup, so no
    public accessor can reveal that the index is holding something other than a
    plain string.

    Raises:
        TypeError: If the stored index key is not exactly a ``str``.
        ValueError: If the entity is absent from the index, or the index resolves
            its identifier to a different object.
    """
    if not world.has_entity(expected_id):
        raise ValueError(f"{kind} {expected_id!r} is absent from the aggregate entity index")
    if world.get_entity(expected_id) is not entity:
        raise ValueError(
            f"the aggregate entity index resolves {expected_id!r} to a different object than "
            f"the {kind} registry holds"
        )
    index_keys = [key for key in world._entities if key == expected_id]  # noqa: SLF001
    if not index_keys:  # pragma: no cover - has_entity already proved one exists
        raise ValueError(f"{kind} {expected_id!r} is absent from the aggregate entity index")
    require_identifier(index_keys[0], f"aggregate index key for {kind} {expected_id!r}")


def resolve_wall_and_boundary(world: World, wall_id: EntityId) -> tuple[Wall, Boundary]:
    """Return a wall and its boundary, after verifying the whole relationship.

    Checks both directions of every reference, that the endpoints exist and are
    distinct, and that no second wall claims the same boundary.

    Raises:
        TypeError: If a stored value is of the wrong kind.
        ValueError: If the wall or boundary is missing, a registry key disagrees
            with its entity, a back-reference disagrees, an endpoint is unknown
            or repeated, or two walls claim one boundary.
    """
    wall = require_registry_entry(world, world.walls, wall_id, kind="wall", expected_type=Wall)
    require_exact_int(wall.built_tick, f"built_tick of wall {wall_id!r}")

    boundary_id = require_identifier(wall.boundary_id, f"boundary_id of wall {wall_id!r}")
    boundary = require_registry_entry(
        world, world.boundaries, boundary_id, kind="boundary", expected_type=Boundary
    )
    if boundary.wall_id is None:
        raise ValueError(
            f"wall {wall_id!r} stands on boundary {boundary_id!r}, but that boundary carries "
            "no wall"
        )
    require_identifier(boundary.wall_id, f"wall_id of boundary {boundary_id!r}")
    if boundary.wall_id != wall_id:
        raise ValueError(
            f"wall {wall_id!r} stands on boundary {boundary_id!r}, but that boundary "
            f"carries {boundary.wall_id!r}"
        )

    claimants = sorted(
        other_id for other_id, other in world.walls.items() if other.boundary_id == boundary_id
    )
    if len(claimants) > 1:
        raise ValueError(f"boundary {boundary_id!r} is claimed by several walls: {claimants}")
    return wall, boundary


def resolve_endpoints(world: World, boundary: Boundary) -> tuple[EntityId, EntityId]:
    """Return a boundary's two district endpoints, after verifying them.

    Raises:
        TypeError: If an endpoint identifier is not a ``str``.
        ValueError: If an endpoint is noncanonical, unknown, or repeated.
    """
    district_a = require_identifier(
        boundary.district_a_id, f"district_a_id of boundary {boundary.id!r}"
    )
    district_b = require_identifier(
        boundary.district_b_id, f"district_b_id of boundary {boundary.id!r}"
    )
    if district_a == district_b:
        raise ValueError(f"boundary {boundary.id!r} joins district {district_a!r} to itself")
    for endpoint in (district_a, district_b):
        require_registry_entry(
            world, world.districts, endpoint, kind="district", expected_type=District
        )
    return district_a, district_b


def require_remembered_wall(world: World, build_fact: MemoryFact) -> tuple[Wall, Boundary]:
    """Verify a remembered wall still matches the world exactly.

    Run on every episode, including one in which nothing happened. A quiet
    episode does not suspend history: a permanent wall that has quietly vanished,
    lost its boundary, or changed which districts it separates means the world
    and the memory disagree, and saving on top of that would make the
    disagreement permanent.

    Raises:
        TypeError: If a stored value is of the wrong kind.
        ValueError: If the wall is missing, is no longer permanent, or no longer
            matches what the fact recorded.
    """
    details = build_fact.details
    wall_id = require_identifier(details["wall_id"], "remembered wall_id")
    wall, boundary = resolve_wall_and_boundary(world, wall_id)

    if require_flag(wall.permanent, f"permanent of wall {wall_id!r}") is not True:
        raise ValueError(f"wall {wall_id!r} is remembered as permanent but is no longer marked so")
    if wall.built_tick != details["built_tick"]:
        raise ValueError(
            f"wall {wall_id!r} is remembered as built at tick {details['built_tick']!r} but "
            f"now records {wall.built_tick}"
        )
    if boundary.id != details["boundary_id"]:
        raise ValueError(
            f"wall {wall_id!r} is remembered on boundary {details['boundary_id']!r} but now "
            f"stands on {boundary.id!r}"
        )

    district_a, district_b = resolve_endpoints(world, boundary)
    if district_a != details["district_a_id"] or district_b != details["district_b_id"]:
        raise ValueError(
            f"boundary {boundary.id!r} no longer joins the districts recorded when wall "
            f"{wall_id!r} was built"
        )
    return wall, boundary


def require_remembered_walls(world: World, memory_facts: Sequence[MemoryFact]) -> None:
    """Verify every remembered wall in a history still matches the world.

    Raises:
        TypeError: If a stored value is of the wrong kind.
        ValueError: If any remembered wall no longer matches.
    """
    for fact in memory_facts:
        if fact.fact_type is MemoryFactType.WALL_BUILT:
            require_remembered_wall(world, fact)


def resolve_restored_law(world: World, law_id: EntityId, tick: int, episode: int) -> Law:
    """Return the law a restoration concerns, after verifying it matches exactly.

    Every field is checked for exact type before being compared. ``True == 1``,
    so an equality-only check would accept a boolean where an episode number or
    a tick belongs, and the mismatch would never surface again.

    Raises:
        TypeError: If a stored field is of the wrong kind.
        ValueError: If the law is missing, its registry key disagrees, it is not
            in force, or its recorded restoration does not match the event.
    """
    law = require_registry_entry(world, world.laws, law_id, kind="law", expected_type=Law)
    require_text(law.name, f"name of law {law_id!r}")
    require_law_value(law.previous_value, f"previous_value of law {law_id!r}")
    require_law_value(law.current_value, f"current_value of law {law_id!r}")

    if require_flag(law.active, f"active of law {law_id!r}") is not True:
        raise ValueError(f"law {law_id!r} was restored but is not in force")
    if require_exact_int(law.changed_episode, f"changed_episode of law {law_id!r}") != episode:
        raise ValueError(
            f"law {law_id!r} records changed_episode {law.changed_episode!r} but the episode "
            f"being distilled is {episode}"
        )
    if law.restored_tick is None:
        raise ValueError(f"law {law_id!r} was restored but records no restored_tick")
    if require_exact_int(law.restored_tick, f"restored_tick of law {law_id!r}") != tick:
        raise ValueError(
            f"law {law_id!r} records restored_tick {law.restored_tick!r} but its LAW_RESTORED "
            f"event happened at tick {tick}"
        )
    return law


def expected_facts_for_event(
    *,
    world: World,
    event: Event,
    source_event_index: int,
    built_facts: Mapping[EntityId, MemoryFact],
) -> tuple[MemoryFact, ...]:
    """Return exactly the facts one event must produce, in canonical order.

    The single definition of significance. Distillation calls this to build a
    history; validation calls it to check one. Two implementations would be two
    opinions, and only one of them would be enforced.

    Args:
        world: The world as the episode left it.
        event: The event being considered.
        source_event_index: Its zero-based position in the episode log.
        built_facts: Wall-construction facts known so far, keyed by wall.

    Returns:
        The facts this event requires. Empty for a non-significant event, and
        empty for a restoration with nothing standing that qualifies.

    Raises:
        TypeError: If a stored value is of the wrong kind.
        ValueError: If the event names nothing, or the final state contradicts it.
    """
    if event.type not in SIGNIFICANT_EVENT_TYPES:
        return ()
    if event.type is EventType.WALL_BUILT:
        return (_wall_built_fact(world, event, source_event_index, built_facts),)
    return _wall_persistence_facts(world, event, source_event_index, built_facts)


def _wall_built_fact(
    world: World,
    event: Event,
    source_event_index: int,
    built_facts: Mapping[EntityId, MemoryFact],
) -> MemoryFact:
    """Return the durable fact for one verified wall construction.

    Raises:
        ValueError: If the event names no wall, the wall does not exist or is not
            permanent, the topology disagrees, or the wall is already remembered.
    """
    if event.source_id is None:
        raise ValueError(f"the WALL_BUILT event at index {source_event_index} names no wall")
    wall_id = require_identifier(
        event.source_id, f"WALL_BUILT event {source_event_index} source_id"
    )
    if wall_id in built_facts:
        raise ValueError(f"wall {wall_id!r} is already remembered as built; a wall is built once")

    wall, boundary = resolve_wall_and_boundary(world, wall_id)
    if wall.built_tick != event.tick:
        raise ValueError(
            f"wall {wall_id!r} records built_tick {wall.built_tick} but its WALL_BUILT event "
            f"happened at tick {event.tick}"
        )
    if require_flag(wall.permanent, f"permanent of wall {wall_id!r}") is not True:
        raise ValueError(f"wall {wall_id!r} is not permanent; only a permanent wall is remembered")

    district_a, district_b = resolve_endpoints(world, boundary)
    return MemoryFact(
        fact_type=MemoryFactType.WALL_BUILT,
        episode=world.episode,
        tick=require_exact_int(event.tick, "event tick"),
        source_event_index=source_event_index,
        source_event_type=EventType.WALL_BUILT,
        source_id=wall_id,
        subject_ids=tuple(sorted({boundary.id, district_a, district_b, wall_id})),
        details={
            "boundary_id": boundary.id,
            "built_tick": wall.built_tick,
            "district_a_id": district_a,
            "district_b_id": district_b,
            "permanent": wall.permanent,
            # Thawed plain JSON: the fact's constructor deep-freezes and
            # validates it, and refuses already-frozen input by design, so the
            # frozen entry type the annotation expects cannot be supplied.
            "source_event_payload": event.payload_as_dict(),  # type: ignore[dict-item]
            "wall_id": wall_id,
        },
    )


def _wall_persistence_facts(
    world: World,
    event: Event,
    source_event_index: int,
    built_facts: Mapping[EntityId, MemoryFact],
) -> tuple[MemoryFact, ...]:
    """Return one fact per permanent wall that outlived this restoration.

    Walls are traversed in identifier order so the set is deterministic, and the
    resulting facts are then sorted into canonical memory order. Those two orders
    are not the same: every canonical sort field before ``fact_id`` is equal for
    facts from one event, so the tie falls to a digest, which has no reason to
    agree with an alphabetical wall list.

    Raises:
        ValueError: If the event names no law, the law does not match the
            restoration it claims, or a qualifying wall contradicts its
            recorded provenance.
    """
    if event.source_id is None:
        raise ValueError(f"the LAW_RESTORED event at index {source_event_index} names no law")
    law_id = require_identifier(
        event.source_id, f"LAW_RESTORED event {source_event_index} source_id"
    )
    law = resolve_restored_law(world, law_id, event.tick, world.episode)
    payload = event.payload_as_dict()

    facts: list[MemoryFact] = []
    for wall_id in sorted(built_facts):
        build_fact = built_facts[wall_id]
        wall, boundary = require_remembered_wall(world, build_fact)
        # Strict: a wall raised during the very tick the law was restored was not
        # already standing when the restoration happened, so it did not persist
        # through it.
        if wall.built_tick >= event.tick:
            continue
        facts.append(
            MemoryFact(
                fact_type=MemoryFactType.LAW_RESTORED_WALL_PERSISTED,
                episode=world.episode,
                tick=require_exact_int(event.tick, "event tick"),
                source_event_index=source_event_index,
                source_event_type=EventType.LAW_RESTORED,
                source_id=law_id,
                subject_ids=tuple(sorted({boundary.id, law_id, wall_id})),
                details={
                    "boundary_id": boundary.id,
                    "law_current_value": law.current_value,
                    "law_id": law_id,
                    "law_name": law.name,
                    "law_previous_value": law.previous_value,
                    "restored_tick": event.tick,
                    # Thawed plain JSON: the fact's constructor deep-freezes
                    # and validates it, and refuses already-frozen input by
                    # design, so the frozen entry type cannot be supplied.
                    "source_event_payload": payload,  # type: ignore[dict-item]
                    # Recorded exactly as found. An inactive wall still
                    # persisted; activity is not permanence, and conflating them
                    # would let the fact assert more than it knows.
                    "wall_active_at_episode_close": require_flag(
                        wall.active, f"active of wall {wall_id!r}"
                    ),
                    "wall_built_tick": wall.built_tick,
                    "wall_dependency_score_at_episode_close": require_unit_interval(
                        wall.dependency_score, f"dependency_score of wall {wall_id!r}"
                    ),
                    "wall_id": wall_id,
                    "wall_permanent": wall.permanent,
                    "wall_resource_dependency_at_episode_close": require_unit_interval(
                        wall.resource_dependency, f"resource_dependency of wall {wall_id!r}"
                    ),
                    "wall_transport_dependency_at_episode_close": require_unit_interval(
                        wall.transport_dependency, f"transport_dependency of wall {wall_id!r}"
                    ),
                },
            )
        )
    return tuple(sorted(facts, key=MemoryFact.sort_key))


def expected_episode_facts(
    *, world: World, events: tuple[Event, ...], previous_memory: WorldMemory
) -> tuple[MemoryFact, ...]:
    """Return exactly the facts this episode must add, in canonical order.

    Takes an already-captured tuple rather than an ``EventLog``. Chronology and
    fact generation must reason about the same history, and an ``EventLog`` is a
    mutable object owned by the caller: asking it twice is asking twice, not
    reading twice.

    Args:
        world: The world as the episode left it.
        events: The single snapshot of this episode's history.
        previous_memory: The memory carried in from the previous episode.

    Raises:
        TypeError: If a stored value is of the wrong kind.
        ValueError: If the log is inconsistent with the world, or a significant
            event is contradicted by the final state.
    """
    verify_chronology(events, previous_memory, world.tick)
    require_remembered_walls(world, previous_memory.facts)

    built_facts = dict(wall_build_facts(previous_memory))
    produced: list[MemoryFact] = []
    for source_event_index, event in enumerate(events):
        for fact in expected_facts_for_event(
            world=world,
            event=event,
            source_event_index=source_event_index,
            built_facts=built_facts,
        ):
            if fact.fact_type is MemoryFactType.WALL_BUILT:
                built_facts[str(fact.details["wall_id"])] = fact
            produced.append(fact)
    return tuple(produced)


def verify_chronology(
    events: Sequence[Event], previous_memory: WorldMemory, world_tick: int
) -> None:
    """Verify a log is ordered and sits inside this episode's window.

    Raises:
        TypeError: If an entry is not an Event, or a tick is not an exact ``int``.
        ValueError: If ticks decrease, an event postdates the world, or an event
            falls inside a window already processed.
    """
    previous_tick: int | None = None
    for index, event in enumerate(events):
        if not _is_runtime_instance(event, Event):
            raise TypeError(f"event_log entry {index} must be an Event, got {type(event).__name__}")
        # Checked here because every event passes through this walk before any
        # significance decision. A malformed type is not a nonsignificant event:
        # classifying it as one would let a corrupt log look uneventful, and the
        # episode would be remembered as having produced nothing.
        if type(event.type) is not EventType:
            raise TypeError(
                f"event {index} type must be an EventType, got {type(event.type).__name__}"
            )
        tick = require_exact_int(event.tick, f"event {index} tick")
        if previous_tick is not None and tick < previous_tick:
            raise ValueError(
                f"event {index} happened at tick {tick}, before event {index - 1} at tick "
                f"{previous_tick}; an episode log is chronological"
            )
        if tick > world_tick:
            raise ValueError(
                f"event {index} happened at tick {tick}, after the world reached tick {world_tick}"
            )
        if previous_memory.through_tick is not None and tick <= previous_memory.through_tick:
            raise ValueError(
                f"event {index} happened at tick {tick}, which was already processed through "
                f"tick {previous_memory.through_tick}"
            )
        previous_tick = tick


def _verify_fact_provenance(fact: MemoryFact, events: Sequence[Event]) -> None:
    """Verify a fact points at the event it claims to have come from.

    The event is resolved by index rather than by equality: the bus permits
    identical events to be published more than once, and only the position tells
    two occurrences apart.

    Raises:
        ValueError: If the index is out of range, or the resolved event disagrees
            with the fact about its type, tick, subject, or payload.
    """
    if fact.source_event_index >= len(events):
        raise ValueError(
            f"fact {fact.fact_id} cites event index {fact.source_event_index}, but the "
            f"episode log holds {len(events)} events"
        )
    event = events[fact.source_event_index]
    if fact.source_event_type is not event.type:
        raise ValueError(
            f"fact {fact.fact_id} claims a {fact.source_event_type.value} event but index "
            f"{fact.source_event_index} holds a {event.type.value} event"
        )
    if fact.tick != event.tick:
        raise ValueError(
            f"fact {fact.fact_id} records tick {fact.tick} but its source event happened at "
            f"tick {event.tick}"
        )
    if fact.source_id != event.source_id:
        raise ValueError(
            f"fact {fact.fact_id} names {fact.source_id!r} but its source event names "
            f"{event.source_id!r}"
        )
    recorded = fact.details_as_dict()["source_event_payload"]
    if recorded != event.payload_as_dict():
        raise ValueError(
            f"fact {fact.fact_id} carries a source_event_payload that is not what its source "
            "event published"
        )


def validate_memory_transition(
    *,
    previous_memory: WorldMemory | None,
    current_memory: WorldMemory,
    world: World,
    event_log: EventLog,
) -> None:
    """Normalize the caller's objects, then validate the transition against them.

    A thin wrapper. Every input is turned into an exact base-domain snapshot
    first, so no part of the validation can be looking at a different history --
    or a different memory -- than another part.

    Raises:
        TypeError: If an argument or a stored value is of the wrong kind.
        ValueError: If the transition is invalid.
    """
    validate_memory_transition_events(
        previous_memory=(
            None
            if previous_memory is None
            else snapshot_world_memory(previous_memory, "previous_memory")
        ),
        current_memory=snapshot_world_memory(current_memory, "current_memory"),
        world=world,
        events=snapshot_event_log(event_log),
    )


def validate_memory_transition_events(
    *,
    previous_memory: WorldMemory | None,
    current_memory: WorldMemory,
    world: World,
    events: tuple[Event, ...],
) -> None:
    """Verify one episode's memory follows correctly from the one before it.

    World-state lineage proves an episode descends from its parent's *state*. It
    says nothing about the parent's *history*, so without this a child could drop
    every inherited fact, rewrite one, or invent a fact no event supports -- and
    every hash and lineage check would still pass.

    The rule is exact: the current memory must begin with the previous memory's
    facts, in order, unchanged, and may then append only the facts this episode's
    own events require.

    Args:
        previous_memory: The verified memory of episode N-1, or ``None`` for
            episode 0.
        current_memory: The memory offered for this episode.
        world: The world as the episode left it.
        events: The single snapshot of this episode's history. A tuple rather
            than an ``EventLog``, so no nested helper can reacquire a different
            one partway through.

    Raises:
        TypeError: If an argument or a stored value is of the wrong kind.
        ValueError: If the checkpoint disagrees with the world, the inherited
            prefix is not intact, or the appended facts are not exactly what this
            episode's events require.
    """
    if not _is_runtime_instance(world, World):
        raise TypeError(f"world must be a World, got {type(world).__name__}")
    if type(events) is not tuple:
        raise TypeError(f"events must be a tuple, got {type(events).__name__}")
    # The internal path is snapshot-only. Anything reaching it should already
    # have been normalized, and a subclass here would mean a caller-owned object
    # slipped past a public boundary.
    for index, event in enumerate(events):
        if type(event) is not Event:
            raise TypeError(f"events[{index}] must be an exact Event, got {type(event).__name__}")
    if not _is_runtime_instance(current_memory, WorldMemory):
        raise TypeError(
            f"current_memory must be a WorldMemory, got {type(current_memory).__name__}"
        )
    previous = WorldMemory.empty() if previous_memory is None else previous_memory
    if not _is_runtime_instance(previous, WorldMemory):
        raise TypeError(
            f"previous_memory must be a WorldMemory, got {type(previous_memory).__name__}"
        )

    episode = require_exact_int(world.episode, "world.episode")
    tick = require_exact_int(world.tick, "world.tick")
    if current_memory.through_episode != episode or current_memory.through_tick != tick:
        raise ValueError(
            f"the memory was processed through episode {current_memory.through_episode} at "
            f"tick {current_memory.through_tick}, but the world records episode {episode} at "
            f"tick {tick}"
        )

    if episode == 0:
        if previous.through_episode is not None:
            raise ValueError("episode 0 must begin from an unprocessed memory")
    elif previous.through_episode != episode - 1:
        raise ValueError(
            f"episode {episode} must continue from episode {episode - 1}, but the previous "
            f"memory was processed through episode {previous.through_episode}"
        )

    # World time accumulates across episodes. Checked here rather than only where
    # facts are appended, because a quiet episode adds none -- and a rollback with
    # nothing to append is exactly the case that would otherwise slip through, in
    # a save whose every byte, length, hash, and state-lineage edge is correct.
    if previous.through_tick is not None and tick < previous.through_tick:
        raise ValueError(
            f"world time cannot move backward: episode {episode} closes at tick {tick}, "
            f"before episode {previous.through_episode} closed at tick "
            f"{previous.through_tick}"
        )

    inherited = previous.facts
    if current_memory.facts[: len(inherited)] != inherited:
        raise ValueError(
            "the memory does not begin with the inherited history; a later episode may only "
            "append to what it was given, never drop, rewrite, or reorder it"
        )

    suffix = current_memory.facts[len(inherited) :]
    # Before any fact is compared against an event, the log itself has to be a
    # log: ordered, inside this episode's window, and carrying real event types.
    verify_chronology(events, previous, tick)
    for fact in suffix:
        if fact.episode != episode:
            raise ValueError(
                f"fact {fact.fact_id} belongs to episode {fact.episode}, not the episode "
                f"being saved ({episode})"
            )
        _verify_fact_provenance(fact, events)

    expected = expected_episode_facts(world=world, events=events, previous_memory=previous)
    if suffix != expected:
        raise ValueError(
            f"this episode's events require {len(expected)} new facts but the memory adds "
            f"{len(suffix)}; the appended history is not what the episode actually produced"
        )
    require_remembered_walls(world, current_memory.facts)
