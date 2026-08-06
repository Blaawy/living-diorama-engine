"""Accumulated institutional pressure becomes a permanent wall on a boundary."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from living_diorama.entities import BaseEntity, Boundary, District, EntityId, Wall
from living_diorama.events import Event, EventBus, EventType
from living_diorama.events.event import FrozenJsonValue
from living_diorama.systems._pressure import validate_unit_scalar
from living_diorama.systems.base_system import BaseSystem

if TYPE_CHECKING:  # pragma: no cover - import exists for typing only
    from living_diorama.simulation.world import World

DECISION_MODE = "UNILATERAL_MAX"
"""How a boundary's pressure is read from its two endpoints.

Either populated side may decide a barrier is necessary; the other side does
not get a veto. The boundary's pressure is therefore the larger of the active
endpoints' institutional pressures, not their average and not their agreement.
"""

WALL_ID_PREFIX = "wall_"
"""Prefix for the identifier of a wall built on a boundary.

A wall's identifier is derived from the boundary it stands on, so the same
world always produces the same name for the same scar. Nothing here consults a
counter, a clock, a hash, or a random source.
"""


def _validate_population(value: int, field_name: str) -> int:
    """Validate a stored population and return it unchanged.

    Checked as found rather than coerced. ``int(1.5)`` is a perfectly ordinary
    1 and ``int("10")`` a perfectly ordinary 10, so converting first would
    repair the very corruption this is looking for. ``bool`` is refused for the
    same reason it is refused everywhere else in the engine: it subclasses
    ``int``, so ``True`` would silently read as a district of one person.

    Args:
        value: The stored population to check.
        field_name: What is being checked, used in the error message.

    Returns:
        The population unchanged.

    Raises:
        TypeError: If the value is not an exact ``int``.
        ValueError: If the population is negative.
    """
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0, got {value}")
    return value


def _validate_identifier(value: str, field_name: str) -> EntityId:
    """Validate a stored identifier exactly as found, without normalizing it.

    The entity constructors accept an identifier with surrounding whitespace and
    silently strip it. That is fine at construction, but entities stay mutable,
    so a corrupted registry can hold ``"zzz "`` as both its key and its
    ``id`` -- the two agree, and a naive key/id check passes. Building a wall
    for that boundary then constructs a ``Wall`` whose ``boundary_id`` is
    normalized back to ``"zzz"``, which no longer resolves, so registration
    fails *after* earlier walls have already been applied.

    Stripping here would recreate exactly that mismatch, so a noncanonical
    identifier is refused rather than repaired.

    Args:
        value: The stored identifier to check.
        field_name: What is being checked, used in the error message.

    Returns:
        The identifier unchanged.

    Raises:
        TypeError: If the value is not exactly a ``str``.
        ValueError: If it is empty, whitespace-only, or carries surrounding
            whitespace.
    """
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a str, got {type(value).__name__}")
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    if not value.strip():
        raise ValueError(f"{field_name} must not be only whitespace, got {value!r}")
    if value.strip() != value:
        raise ValueError(f"{field_name} must not carry surrounding whitespace, got {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class _StagedWall:
    """One fully decided wall, held back until every boundary has been checked."""

    boundary_id: EntityId
    wall: Wall
    event: Event


class BoundaryDecisionSystem(BaseSystem):
    """Builds a permanent wall where institutional pressure has run high enough.

    Runs last, after the institutional layer, so the pressure it reads is what
    a district finally arrived at this tick.

    **Where "sustained" comes from.** This system keeps no streak counter and no
    history of its own. It does not need one: ``District.institutional_pressure``
    already *is* the accumulated record, because InstitutionalPressureSystem
    moves it only a fraction of the way toward its target each tick. A single
    bad tick lifts it a little; a sustained crisis lifts it repeatedly until it
    crosses the threshold; relief lowers it again. Adding a second memory on
    top of that would be two mechanisms disagreeing about the same fact.

    **Why either side may decide.** A boundary's pressure is the larger of its
    populated endpoints' pressures. Walls in this world are built by whoever
    feels the need for one, and a district under severe strain does not wait
    for its calmer neighbour to agree. Averaging would let a comfortable
    neighbour veto a desperate one, which is not how a barrier comes to exist.

    **Construction only.** A boundary that already carries a wall is left
    entirely alone -- not reinforced, not reactivated, not touched. Changing an
    existing wall is a different concern and belongs to a different phase.

    **The scar is permanent.** Every wall is created ``permanent=True`` and
    ``active=True``. This system never removes, weakens, or deactivates one, and
    it never asks whether a law is in force before deciding: restoring a law
    later cannot unbuild what a crisis built. That permanence is the whole point
    of the series -- the consequence outlives the rule that caused it.

    The system consumes no randomness and holds no state between ticks.
    """

    __slots__ = ("_build_threshold",)

    def __init__(self, build_threshold: float = 0.75) -> None:
        """Create a boundary decision system.

        Args:
            build_threshold: The institutional pressure at or above which a
                wall-free boundary gets a wall. Reaching the threshold exactly
                is enough.

        Raises:
            TypeError: If the threshold is not a real number, or is a bool.
            ValueError: If it is not finite or falls outside 0.0-1.0.
        """
        self._build_threshold = validate_unit_scalar(build_threshold, "build_threshold")

    @property
    def build_threshold(self) -> float:
        """The pressure at or above which a wall-free boundary gets a wall."""
        return self._build_threshold

    def update(self, world: "World", bus: EventBus) -> None:
        """Build every wall this tick calls for, or build none at all.

        The whole world's topology is checked before any decision is made, every
        wall is constructed in memory before any is registered, and events are
        published only once every wall is in place. A half-built tick would
        leave the world with a scar whose cause was never recorded, so the
        update either completes or leaves nothing behind.

        Args:
            world: The world whose boundaries may gain walls.
            bus: The bus on which wall construction is announced.

        Raises:
            TypeError: If a stored population is not an int, or a stored
                institutional pressure is not a real number.
            ValueError: If the existing topology is inconsistent, a stored
                value is out of range, or a wall identifier is already taken.
        """
        self._verify_registry_coherence(world)
        self._verify_topology(world)

        staged = self._stage_walls(world)
        if not staged:
            return

        for entry in staged:
            world.add_wall(entry.wall)

        for entry in staged:
            bus.publish(entry.event)

    @staticmethod
    def _typed_registries(
        world: "World",
    ) -> tuple[tuple[str, Mapping[EntityId, BaseEntity]], ...]:
        """Return every public typed registry, paired with what it holds.

        Laws and infrastructure are included for one reason only: an identifier
        must be unique across the whole world, so proving a candidate wall name
        is free means checking everywhere a name can live. Nothing here reads a
        behavioural field of either, and neither takes any part in the decision.
        """
        return (
            ("district", world.districts),
            ("boundary", world.boundaries),
            ("wall", world.walls),
            ("law", world.laws),
            ("infrastructure", world.infrastructure),
        )

    @classmethod
    def _verify_registry_coherence(cls, world: "World") -> None:
        """Check the typed registries and the aggregate index still agree.

        ``has_entity`` answers from the aggregate index, so trusting it alone to
        prove a name is free assumes the index knows about everything the typed
        registries hold. If those drift apart, a district can exist under a name
        the index has forgotten, and a wall built on that name would leave two
        entities claiming one identifier with the aggregate lookup resolving to
        whichever was written last.

        So the two views are reconciled first, using public accessors only:
        every typed entry must be canonically named, must agree with its own
        ``id``, must be unique across all five registries, and must resolve
        through the aggregate index to the very same object.

        Raises:
            TypeError: If any registry key or entity id is not a ``str``.
            ValueError: If a name is noncanonical, a key disagrees with its
                entity, one name appears in two registries, or the aggregate
                index is missing an entry or resolves it to a different object.
        """
        seen: dict[EntityId, str] = {}

        for kind, registry in cls._typed_registries(world):
            entries = dict(registry)
            for key in sorted(entries, key=repr):
                entity = entries[key]
                _validate_identifier(key, f"{kind} registry key")
                entity_id = entity.id
                _validate_identifier(entity_id, f"id of {kind} {key!r}")
                if entity_id != key:
                    raise ValueError(
                        f"{kind} registry key {key!r} disagrees with its entity's id {entity_id!r}"
                    )
                if key in seen:
                    raise ValueError(
                        f"identifier {key!r} is held by both a {seen[key]} and a {kind}; "
                        "identifiers must be unique across the whole world"
                    )
                seen[key] = kind

                if not world.has_entity(key):
                    raise ValueError(f"{kind} {key!r} is absent from the aggregate entity index")
                if world.get_entity(key) is not entity:
                    raise ValueError(
                        f"the aggregate entity index resolves {key!r} to a different "
                        f"object than the {kind} registry holds"
                    )

    @staticmethod
    def _verify_topology(world: "World") -> None:
        """Check every boundary-wall relationship before anything is decided.

        A wall is permanent, so building one onto a world whose references are
        already inconsistent would make the inconsistency permanent too. None of
        this is repaired: a dangling reference means something upstream is
        broken, and quietly patching it here would hide that.

        Raises:
            ValueError: If any registry key disagrees with the entity it holds,
                any reference dangles, any back-reference disagrees, or more
                than one wall claims the same boundary.
        """
        for district_id in sorted(world.districts):
            district = world.districts[district_id]
            if district.id != district_id:
                raise ValueError(
                    f"district registry key {district_id!r} disagrees with its "
                    f"district's id {district.id!r}"
                )

        for boundary_id in sorted(world.boundaries):
            boundary = world.boundaries[boundary_id]
            if boundary.id != boundary_id:
                raise ValueError(
                    f"boundary registry key {boundary_id!r} disagrees with its "
                    f"boundary's id {boundary.id!r}"
                )
            _validate_identifier(
                boundary.district_a_id, f"district_a_id of boundary {boundary_id!r}"
            )
            _validate_identifier(
                boundary.district_b_id, f"district_b_id of boundary {boundary_id!r}"
            )
            if boundary.district_a_id == boundary.district_b_id:
                raise ValueError(
                    f"boundary {boundary_id!r} joins district "
                    f"{boundary.district_a_id!r} to itself; a boundary must separate "
                    "two distinct districts"
                )
            for endpoint in (boundary.district_a_id, boundary.district_b_id):
                if endpoint not in world.districts:
                    raise ValueError(
                        f"boundary {boundary_id!r} references unknown district {endpoint!r}"
                    )
            if boundary.wall_id is not None:
                _validate_identifier(boundary.wall_id, f"wall_id of boundary {boundary_id!r}")
                wall = world.walls.get(boundary.wall_id)
                if wall is None:
                    raise ValueError(
                        f"boundary {boundary_id!r} references unknown wall {boundary.wall_id!r}"
                    )
                if wall.boundary_id != boundary_id:
                    raise ValueError(
                        f"boundary {boundary_id!r} claims wall {boundary.wall_id!r}, "
                        f"but that wall stands on boundary {wall.boundary_id!r}"
                    )

        claimed: dict[EntityId, EntityId] = {}
        for wall_id in sorted(world.walls):
            wall = world.walls[wall_id]
            if wall.id != wall_id:
                raise ValueError(
                    f"wall registry key {wall_id!r} disagrees with its wall's id {wall.id!r}"
                )
            _validate_identifier(wall.boundary_id, f"boundary_id of wall {wall_id!r}")
            linked_boundary = world.boundaries.get(wall.boundary_id)
            if linked_boundary is None:
                raise ValueError(
                    f"wall {wall_id!r} references unknown boundary {wall.boundary_id!r}"
                )
            if linked_boundary.wall_id != wall_id:
                raise ValueError(
                    f"wall {wall_id!r} stands on boundary {wall.boundary_id!r}, "
                    f"but that boundary carries {linked_boundary.wall_id!r}"
                )
            if wall.boundary_id in claimed:
                raise ValueError(
                    f"boundary {wall.boundary_id!r} is claimed by both "
                    f"{claimed[wall.boundary_id]!r} and {wall_id!r}"
                )
            claimed[wall.boundary_id] = wall_id

    def _stage_walls(self, world: "World") -> list[_StagedWall]:
        """Decide and build every qualifying wall in memory, touching nothing.

        Boundaries are visited in sorted identifier order, which fixes both the
        order walls are registered and the order their events appear.
        """
        staged: list[_StagedWall] = []
        taken: set[EntityId] = set()

        for boundary_id in sorted(world.boundaries):
            boundary = world.boundaries[boundary_id]
            if boundary.wall_id is not None:
                continue

            reading = self._read_boundary(world, boundary)
            if reading is None:
                continue

            wall_id = self._reserve_wall_id(world, boundary_id, taken)
            wall = Wall(
                id=wall_id,
                created_tick=world.tick,
                boundary_id=boundary_id,
                built_tick=world.tick,
                integrity=1.0,
                active=True,
                permanent=True,
                dependency_score=0.0,
                transport_dependency=0.0,
                resource_dependency=0.0,
            )
            self._verify_staged_wall(wall, wall_id, boundary_id, world.tick)
            event = Event(
                tick=world.tick,
                type=EventType.WALL_BUILT,
                payload=self._build_payload(wall, boundary, reading),
                source_id=wall_id,
            )
            staged.append(_StagedWall(boundary_id=boundary_id, wall=wall, event=event))

        return staged

    @staticmethod
    def _verify_staged_wall(
        wall: Wall, wall_id: EntityId, boundary_id: EntityId, tick: int
    ) -> None:
        """Confirm construction kept the identifiers and ticks it was given.

        ``Wall`` normalizes its identifiers on construction, so a value that
        went in slightly different comes back out changed -- and a wall whose
        ``boundary_id`` no longer matches the boundary it was staged for would
        fail registration only after earlier walls had already been applied.
        Everything upstream should already make that impossible; this is the
        check that says so out loud rather than assuming it.

        Raises:
            ValueError: If construction altered an identifier or a tick.
        """
        if wall.id != wall_id:
            raise ValueError(
                f"constructing the wall for boundary {boundary_id!r} changed its id "
                f"from {wall_id!r} to {wall.id!r}"
            )
        if wall.boundary_id != boundary_id:
            raise ValueError(
                f"constructing wall {wall_id!r} changed its boundary_id from "
                f"{boundary_id!r} to {wall.boundary_id!r}"
            )
        if wall.created_tick != tick or wall.built_tick != tick:
            raise ValueError(
                f"wall {wall_id!r} must be created and built on tick {tick}, got "
                f"created_tick={wall.created_tick} built_tick={wall.built_tick}"
            )

    def _read_boundary(
        self, world: "World", boundary: Boundary
    ) -> tuple[int, int, float | None, float | None, float] | None:
        """Read both endpoints and decide whether this boundary calls for a wall.

        Returns the two populations, the two pressures -- ``None`` for an
        endpoint that has nobody left, whose stored pressure is deliberately
        never read -- and the resulting boundary pressure. Returns ``None``
        entirely when the boundary has no populated endpoint or does not reach
        the threshold.

        An abandoned district's historical pressure is not a reason to wall
        anything: there is nobody there to want it. Its stored value is left
        untouched, corrupted or not, since reading it would be the only way for
        that corruption to matter.
        """
        district_a = world.districts[boundary.district_a_id]
        district_b = world.districts[boundary.district_b_id]

        population_a = _validate_population(
            district_a.population, f"population of {district_a.id!r}"
        )
        population_b = _validate_population(
            district_b.population, f"population of {district_b.id!r}"
        )

        pressure_a = self._read_pressure(district_a) if population_a > 0 else None
        pressure_b = self._read_pressure(district_b) if population_b > 0 else None

        active = [pressure for pressure in (pressure_a, pressure_b) if pressure is not None]
        if not active:
            return None

        boundary_pressure = max(active)
        if boundary_pressure < self._build_threshold:
            return None

        return population_a, population_b, pressure_a, pressure_b, boundary_pressure

    @staticmethod
    def _read_pressure(district: District) -> float:
        """Return a populated district's stored institutional pressure, as found.

        Handed to the validator without conversion, so a corrupted ``True`` or
        ``"0.5"`` is refused rather than quietly becoming a number that could
        justify a permanent wall.

        Raises:
            TypeError: If the stored value is not a real number, or is a bool.
            ValueError: If it is not finite or lies outside 0.0-1.0.
        """
        return validate_unit_scalar(
            district.institutional_pressure, f"institutional pressure of {district.id!r}"
        )

    @classmethod
    def _reserve_wall_id(
        cls, world: "World", boundary_id: EntityId, taken: set[EntityId]
    ) -> EntityId:
        """Derive this boundary's wall identifier and confirm nothing else holds it.

        A collision is reported rather than worked around. Appending a suffix
        would silently produce a differently-named scar for the same boundary,
        and overwriting would destroy whatever already held the name; both hide
        a naming problem that someone needs to see.

        Every typed registry is checked directly rather than relying on
        ``has_entity`` alone, because that answers from the aggregate index. If
        the index has drifted, it can report a name as free while a district
        still holds it.

        Raises:
            ValueError: If the identifier already belongs to any entity in the
                world, or to another wall staged during this same update.
        """
        wall_id = _validate_identifier(
            f"{WALL_ID_PREFIX}{boundary_id}", f"wall identifier for boundary {boundary_id!r}"
        )
        for kind, registry in cls._typed_registries(world):
            if wall_id in registry:
                raise ValueError(
                    f"wall identifier {wall_id!r} for boundary {boundary_id!r} is already "
                    f"used by a {kind}"
                )
        if world.has_entity(wall_id):
            existing = type(world.get_entity(wall_id)).__name__
            raise ValueError(
                f"wall identifier {wall_id!r} for boundary {boundary_id!r} is already "
                f"used by a {existing}"
            )
        if wall_id in taken:
            raise ValueError(
                f"wall identifier {wall_id!r} for boundary {boundary_id!r} collides with "
                "another wall staged this tick"
            )
        taken.add(wall_id)
        return wall_id

    def _build_payload(
        self,
        wall: Wall,
        boundary: Boundary,
        reading: tuple[int, int, float | None, float | None, float],
    ) -> dict[str, FrozenJsonValue]:
        """Describe one construction decision as strictly JSON-compatible primitives.

        Both endpoints are reported even when only one of them mattered, so the
        recorded history shows what the other side looked like at the moment the
        wall went up. An endpoint with nobody in it reports ``None`` rather than
        a number, because its pressure was deliberately never read.
        """
        population_a, population_b, pressure_a, pressure_b, boundary_pressure = reading
        active_endpoint_count = sum(
            1 for pressure in (pressure_a, pressure_b) if pressure is not None
        )

        return {
            "wall_id": wall.id,
            "boundary_id": boundary.id,
            "district_a_id": boundary.district_a_id,
            "district_b_id": boundary.district_b_id,
            "district_a_population": population_a,
            "district_b_population": population_b,
            "district_a_institutional_pressure": pressure_a,
            "district_b_institutional_pressure": pressure_b,
            "active_endpoint_count": active_endpoint_count,
            "boundary_pressure": boundary_pressure,
            "build_threshold": self._build_threshold,
            "decision_mode": DECISION_MODE,
            "created_tick": wall.created_tick,
            "built_tick": wall.built_tick,
            "integrity": wall.integrity,
            "active": wall.active,
            "permanent": wall.permanent,
        }
