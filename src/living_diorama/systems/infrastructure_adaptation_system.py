"""A standing wall becomes load-bearing as the world reorganizes around it."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from living_diorama.entities import (
    BaseEntity,
    Boundary,
    EntityId,
    Infrastructure,
    InfrastructureType,
    Wall,
)
from living_diorama.events import Event, EventBus, EventType
from living_diorama.events.event import FrozenJsonValue
from living_diorama.systems._pressure import validate_unit_scalar
from living_diorama.systems._resource_config import require_finite
from living_diorama.systems.base_system import BaseSystem

if TYPE_CHECKING:  # pragma: no cover - import exists for typing only
    from living_diorama.simulation.world import World

TRANSPORT_TYPE = InfrastructureType.TRANSIT_ROUTE
"""The infrastructure kind that feeds a wall's transport dependency."""

RESOURCE_TYPE = InfrastructureType.RESOURCE_ROUTE
"""The infrastructure kind that feeds a wall's resource dependency."""

_LOWER_RESIDUE_LIMIT = math.nextafter(0.0, -math.inf)
"""The largest negative float that can only be rounding residue below zero."""

_UPPER_RESIDUE_LIMIT = math.nextafter(1.0, math.inf)
"""The smallest float above one that can only be rounding residue above it."""


def _validate_identifier(value: str, field_name: str) -> EntityId:
    """Validate a stored identifier exactly as found, without normalizing it.

    Entity constructors accept an identifier with surrounding whitespace and
    silently strip it, but entities stay mutable, so a corrupted registry can
    hold ``"gate "`` as both its key and its ``id`` -- the two agree, and a
    naive key/id check passes while every lookup against the canonical name
    fails. Stripping here would recreate exactly that mismatch, so a
    noncanonical identifier is refused rather than repaired.

    Internal whitespace is fine: ``"north gate"`` is a perfectly good name.

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


def _validate_tick(value: int, field_name: str) -> int:
    """Validate a stored tick exactly as found.

    ``bool`` is refused for the reason it is refused everywhere in the engine:
    it subclasses ``int``, so ``True`` would read as tick 1.

    Raises:
        TypeError: If the value is not an exact ``int``.
        ValueError: If the tick is negative.
    """
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0, got {value}")
    return value


def _validate_flag(value: bool, field_name: str) -> bool:
    """Validate a stored boolean exactly as found.

    ``0``, ``1``, and ``"true"`` are all refused. A flag that decides whether a
    wall is standing has to be a flag, not something merely truthy.

    Raises:
        TypeError: If the value is not exactly a ``bool``.
    """
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a bool, got {type(value).__name__}")
    return value


def _validate_capacity(value: float, field_name: str) -> float:
    """Validate stored capacity exactly as found.

    Capacity does not gate adaptation, but a corrupted value here means the
    entity is not trustworthy, and it is reported in the event payload.

    Raises:
        TypeError: If the value is not a real number, or is a bool.
        ValueError: If it is not finite or is negative.
    """
    if type(value) is bool or not isinstance(value, int | float):
        raise TypeError(f"{field_name} must be a real number, got {type(value).__name__}")
    capacity = float(value)
    if not math.isfinite(capacity):
        raise ValueError(f"{field_name} must be finite, got {value!r}")
    if capacity < 0.0:
        raise ValueError(f"{field_name} must be >= 0, got {capacity}")
    return capacity


def _validate_infrastructure_type(value: InfrastructureType, field_name: str) -> InfrastructureType:
    """Validate a stored infrastructure kind exactly as found.

    The string ``"TRANSIT_ROUTE"`` and a member of some unrelated enum both
    look plausible and neither is this enum. Category routing depends on the
    real member, so nothing else is accepted.

    Raises:
        TypeError: If the value is not an ``InfrastructureType`` member.
    """
    if type(value) is not InfrastructureType:
        raise TypeError(f"{field_name} must be an InfrastructureType, got {type(value).__name__}")
    return value


def _clamp_unit(value: float, description: str) -> float:
    """Flatten one-ULP residue outside 0.0-1.0, and refuse anything larger.

    Every quantity here is built from values already inside the unit interval,
    so the only way a result can land outside it is the last bit of an addition
    or multiplication going the wrong way. That is a single ULP wide, and it is
    flattened.

    Anything further out is not residue. Reporting 2.0 as 1.0 would turn a
    defect into a plausible-looking dependency score nobody could later
    distinguish from infrastructure the world genuinely cannot do without.

    This is deliberately a private copy of the rule other systems apply rather
    than an import of one. Concrete systems do not depend on one another, and a
    shared private helper between two of them would be that dependency wearing
    a different hat.

    Raises:
        ValueError: If the value is not finite, or lies more than one ULP
            outside 0.0-1.0.
    """
    require_finite(value, description)
    if value < _LOWER_RESIDUE_LIMIT or value > _UPPER_RESIDUE_LIMIT:
        raise ValueError(f"{description} must be within 0.0-1.0, got {value!r}")
    return min(1.0, max(0.0, value))


@dataclass(frozen=True, slots=True)
class _InfrastructureState:
    """One infrastructure's validated stored state and its staged new score."""

    infrastructure_id: EntityId
    boundary_id: EntityId
    wall_id: EntityId | None
    infrastructure_type: InfrastructureType
    capacity: float
    degraded: bool
    previous_dependency: float
    new_dependency: float

    @property
    def changed(self) -> bool:
        """Whether this infrastructure's dependency actually moved."""
        return self.new_dependency != self.previous_dependency


@dataclass(frozen=True, slots=True)
class _WallState:
    """One wall's validated stored state and its staged dependency aggregates."""

    wall_id: EntityId
    boundary_id: EntityId
    active: bool
    permanent: bool
    integrity: float
    connected_count: int
    adapted_count: int
    previous_dependency: float
    new_dependency: float
    previous_transport: float
    new_transport: float
    previous_resource: float
    new_resource: float

    @property
    def changed(self) -> bool:
        """Whether any of the three dependency fields actually moved."""
        return (
            self.new_dependency != self.previous_dependency
            or self.new_transport != self.previous_transport
            or self.new_resource != self.previous_resource
        )


class InfrastructureAdaptationSystem(BaseSystem):
    """Turns a standing wall into something the world cannot easily do without.

    Runs last, after the boundary decision, so a wall built this tick is already
    standing when this system looks -- and starts accumulating dependency
    immediately, with no waiting period.

    **What dependency means.** Not whether infrastructure is healthy or busy,
    but how far the world has reorganized itself around the wall being there.
    That is why a degraded route and a zero-capacity one both keep accumulating:
    a bad road everyone has come to rely on is exactly the case that makes a
    wall permanent in practice. Capacity and degradation are read for the record
    and never gate the growth.

    **Why growth is gradual.** Each tick closes a fixed fraction of the distance
    to total reliance, so dependency approaches 1.0 without ever jumping there.
    Reorganizing around a barrier takes time.

    **Why it never decays.** A wall that stops being active stops *adding*
    dependency, but nothing gives back what was already accumulated. Routes were
    rebuilt, journeys re-planned, services relocated; taking the wall down does
    not un-move them. This asymmetry is the mechanism behind the show's premise
    -- repealing the rule does not repeal the consequence -- so decay is
    deliberately absent rather than merely unimplemented.

    **Why walls aggregate by maximum.** A wall is as load-bearing as the single
    system most dependent on it. Summing would make two identical routes
    register as twice the reliance, and averaging would let one indifferent
    piece of infrastructure dilute a critical one. Maximum is also the only
    choice invariant to how many equivalent objects happen to exist and to the
    order they were registered.

    The system consumes no randomness and holds no state between ticks: the
    stored dependency scores are the entire memory.
    """

    __slots__ = ("_adaptation_rate",)

    def __init__(self, adaptation_rate: float = 0.10) -> None:
        """Create an infrastructure adaptation system.

        Args:
            adaptation_rate: The share of the remaining distance to total
                reliance that closes each tick while a wall stands. Zero freezes
                dependency where it is; one makes infrastructure wholly
                dependent immediately.

        Raises:
            TypeError: If the rate is not a real number, or is a bool.
            ValueError: If it is not finite or falls outside 0.0-1.0.
        """
        self._adaptation_rate = validate_unit_scalar(adaptation_rate, "adaptation_rate")

    @property
    def adaptation_rate(self) -> float:
        """Share of the remaining distance to total reliance closed each tick."""
        return self._adaptation_rate

    def update(self, world: "World", bus: EventBus) -> None:
        """Grow dependency wherever an active wall stands, or change nothing.

        The whole world is validated before any score moves, every new value is
        computed in memory, and events are published only once every mutation
        has been applied. Dependency is permanent, so a half-applied tick would
        leave a reliance nobody could account for.

        Args:
            world: The world whose infrastructure and walls may adapt.
            bus: The bus on which adaptation is announced.

        Raises:
            TypeError: If any stored value is of the wrong kind.
            ValueError: If any stored value is out of range, or the world's
                identifiers and references are inconsistent.
        """
        tick = _validate_tick(world.tick, "world.tick")
        self._verify_registry_coherence(world)
        self._verify_topology(world, tick)

        infrastructure = self._stage_infrastructure(world, tick)
        walls = self._stage_walls(world, infrastructure)

        infrastructure_events = [
            Event(
                tick=tick,
                type=EventType.INFRASTRUCTURE_ADAPTED,
                payload=self._build_infrastructure_payload(state, world),
                source_id=state.infrastructure_id,
            )
            for state in infrastructure
            if state.changed
        ]
        wall_events = [
            Event(
                tick=tick,
                type=EventType.WALL_CHANGED,
                payload=self._build_wall_payload(state),
                source_id=state.wall_id,
            )
            for state in walls
            if state.changed
        ]

        for infrastructure_state in infrastructure:
            if infrastructure_state.changed:
                world.infrastructure[
                    infrastructure_state.infrastructure_id
                ].dependency_score = infrastructure_state.new_dependency

        for wall_state in walls:
            if wall_state.changed:
                wall = world.walls[wall_state.wall_id]
                wall.dependency_score = wall_state.new_dependency
                wall.transport_dependency = wall_state.new_transport
                wall.resource_dependency = wall_state.new_resource

        for event in infrastructure_events:
            bus.publish(event)
        for event in wall_events:
            bus.publish(event)

    # --- preflight ----------------------------------------------------------

    @staticmethod
    def _typed_registries(world: "World") -> tuple[tuple[str, Mapping[EntityId, BaseEntity]], ...]:
        """Return every public typed registry, paired with what it holds.

        Districts and laws appear for one reason only: an identifier must be
        unique across the whole world, so proving the registries and the
        aggregate index agree means checking everywhere a name can live. No
        behavioural field of either is read, and neither takes any part in
        adaptation.
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

        ``has_entity`` answers from the aggregate index, so trusting it alone
        assumes that index knows about everything the typed registries hold. If
        the two drift apart, an entity can exist under a name the index has
        forgotten, and identifier uniqueness stops meaning anything.

        Everything here goes through public accessors.

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

    @classmethod
    def _verify_topology(cls, world: "World", tick: int) -> None:
        """Validate every boundary, wall, and infrastructure before anything moves.

        Dependency growth is permanent, so applying it to a world whose
        references are already inconsistent would make the inconsistency
        permanent too. Nothing is repaired: a dangling reference means something
        upstream is broken, and quietly patching it here would hide that.

        Raises:
            TypeError: If a stored value is of the wrong kind.
            ValueError: If a reference dangles, a back-reference disagrees, more
                than one wall claims a boundary, or a stored value is out of
                range.
        """
        for boundary_id in sorted(world.boundaries):
            cls._verify_boundary(world, world.boundaries[boundary_id], boundary_id)

        claimed: dict[EntityId, EntityId] = {}
        for wall_id in sorted(world.walls):
            wall = world.walls[wall_id]
            cls._verify_wall(world, wall, wall_id, tick)
            if wall.boundary_id in claimed:
                raise ValueError(
                    f"boundary {wall.boundary_id!r} is claimed by both "
                    f"{claimed[wall.boundary_id]!r} and {wall_id!r}"
                )
            claimed[wall.boundary_id] = wall_id

        for infrastructure_id in sorted(world.infrastructure):
            cls._verify_infrastructure(
                world, world.infrastructure[infrastructure_id], infrastructure_id, tick
            )

    @staticmethod
    def _verify_boundary(world: "World", boundary: Boundary, boundary_id: EntityId) -> None:
        """Validate one boundary's identifiers, endpoints, and wall reference."""
        _validate_identifier(boundary.district_a_id, f"district_a_id of boundary {boundary_id!r}")
        _validate_identifier(boundary.district_b_id, f"district_b_id of boundary {boundary_id!r}")
        if boundary.district_a_id == boundary.district_b_id:
            raise ValueError(
                f"boundary {boundary_id!r} joins district {boundary.district_a_id!r} to "
                "itself; a boundary must separate two distinct districts"
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
                    f"boundary {boundary_id!r} claims wall {boundary.wall_id!r}, but that "
                    f"wall stands on boundary {wall.boundary_id!r}"
                )

    @staticmethod
    def _verify_wall(world: "World", wall: Wall, wall_id: EntityId, tick: int) -> None:
        """Validate one wall's identifiers, ticks, flags, and dependency fields."""
        _validate_identifier(wall.boundary_id, f"boundary_id of wall {wall_id!r}")
        boundary = world.boundaries.get(wall.boundary_id)
        if boundary is None:
            raise ValueError(f"wall {wall_id!r} references unknown boundary {wall.boundary_id!r}")
        if boundary.wall_id != wall_id:
            raise ValueError(
                f"wall {wall_id!r} stands on boundary {wall.boundary_id!r}, but that "
                f"boundary carries {boundary.wall_id!r}"
            )

        created = _validate_tick(wall.created_tick, f"created_tick of wall {wall_id!r}")
        built = _validate_tick(wall.built_tick, f"built_tick of wall {wall_id!r}")
        if created > built:
            raise ValueError(
                f"wall {wall_id!r} was built on tick {built} before it was created on "
                f"tick {created}"
            )
        if built > tick:
            raise ValueError(
                f"wall {wall_id!r} claims to have been built on tick {built}, which is "
                f"after the current tick {tick}"
            )

        _validate_flag(wall.active, f"active of wall {wall_id!r}")
        _validate_flag(wall.permanent, f"permanent of wall {wall_id!r}")
        validate_unit_scalar(wall.integrity, f"integrity of wall {wall_id!r}")
        validate_unit_scalar(wall.dependency_score, f"dependency_score of wall {wall_id!r}")
        validate_unit_scalar(wall.transport_dependency, f"transport_dependency of wall {wall_id!r}")
        validate_unit_scalar(wall.resource_dependency, f"resource_dependency of wall {wall_id!r}")

    @staticmethod
    def _verify_infrastructure(
        world: "World",
        infrastructure: Infrastructure,
        infrastructure_id: EntityId,
        tick: int,
    ) -> None:
        """Validate one infrastructure's identifiers, kind, capacity, and score."""
        _validate_identifier(
            infrastructure.boundary_id, f"boundary_id of infrastructure {infrastructure_id!r}"
        )
        if infrastructure.boundary_id not in world.boundaries:
            raise ValueError(
                f"infrastructure {infrastructure_id!r} references unknown boundary "
                f"{infrastructure.boundary_id!r}"
            )

        created = _validate_tick(
            infrastructure.created_tick, f"created_tick of infrastructure {infrastructure_id!r}"
        )
        if created > tick:
            raise ValueError(
                f"infrastructure {infrastructure_id!r} claims to have been created on tick "
                f"{created}, which is after the current tick {tick}"
            )

        _validate_infrastructure_type(
            infrastructure.infrastructure_type,
            f"infrastructure_type of infrastructure {infrastructure_id!r}",
        )
        _validate_capacity(
            infrastructure.capacity, f"capacity of infrastructure {infrastructure_id!r}"
        )
        _validate_flag(infrastructure.degraded, f"degraded of infrastructure {infrastructure_id!r}")
        validate_unit_scalar(
            infrastructure.dependency_score,
            f"dependency_score of infrastructure {infrastructure_id!r}",
        )

    # --- staging ------------------------------------------------------------

    def _stage_infrastructure(self, world: "World", tick: int) -> list[_InfrastructureState]:
        """Work out every infrastructure's new dependency without touching the world."""
        staged: list[_InfrastructureState] = []

        for infrastructure_id in sorted(world.infrastructure):
            infrastructure = world.infrastructure[infrastructure_id]
            boundary = world.boundaries[infrastructure.boundary_id]
            wall = world.walls.get(boundary.wall_id) if boundary.wall_id is not None else None

            previous = validate_unit_scalar(
                infrastructure.dependency_score,
                f"dependency_score of infrastructure {infrastructure_id!r}",
            )
            if wall is not None and wall.active:
                new_dependency = _clamp_unit(
                    previous + self._adaptation_rate * (1.0 - previous),
                    f"dependency of infrastructure {infrastructure_id!r}",
                )
            else:
                new_dependency = previous

            staged.append(
                _InfrastructureState(
                    infrastructure_id=infrastructure_id,
                    boundary_id=infrastructure.boundary_id,
                    wall_id=None if wall is None else wall.id,
                    infrastructure_type=infrastructure.infrastructure_type,
                    capacity=float(infrastructure.capacity),
                    degraded=infrastructure.degraded,
                    previous_dependency=previous,
                    new_dependency=new_dependency,
                )
            )

        return staged

    def _stage_walls(
        self, world: "World", infrastructure: list[_InfrastructureState]
    ) -> list[_WallState]:
        """Aggregate each active wall's dependency from the staged new scores.

        Deliberately reads the staged values rather than what is still stored:
        the wall and the infrastructure it carries must describe the same
        moment, and using stale scores would leave the wall a tick behind
        forever.
        """
        staged: list[_WallState] = []

        for wall_id in sorted(world.walls):
            wall = world.walls[wall_id]
            connected = [state for state in infrastructure if state.boundary_id == wall.boundary_id]
            previous_dependency = validate_unit_scalar(
                wall.dependency_score, f"dependency_score of wall {wall_id!r}"
            )
            previous_transport = validate_unit_scalar(
                wall.transport_dependency, f"transport_dependency of wall {wall_id!r}"
            )
            previous_resource = validate_unit_scalar(
                wall.resource_dependency, f"resource_dependency of wall {wall_id!r}"
            )

            if not wall.active or not connected:
                # Nothing to adapt, so nothing to aggregate. A wall with no
                # infrastructure attached is not being depended upon by anything
                # this tick, and one that is not standing has stopped being
                # depended upon further. Both keep exactly what they had.
                #
                # The empty case matters on its own: the overall score folds in
                # the two category scores, so running the aggregation with no
                # infrastructure would let a higher historical category pull the
                # overall figure up out of nowhere -- reporting growth in
                # reliance that no infrastructure produced. The three fields are
                # independently valid and may legitimately disagree, so the
                # answer is to leave them alone, not to reconcile them.
                new_transport = previous_transport
                new_resource = previous_resource
                new_dependency = previous_dependency
            else:
                new_transport = self._aggregate(
                    previous_transport, connected, TRANSPORT_TYPE, wall_id, "transport"
                )
                new_resource = self._aggregate(
                    previous_resource, connected, RESOURCE_TYPE, wall_id, "resource"
                )
                overall = max(state.new_dependency for state in connected)
                new_dependency = _clamp_unit(
                    max(previous_dependency, overall, new_transport, new_resource),
                    f"dependency of wall {wall_id!r}",
                )

            staged.append(
                _WallState(
                    wall_id=wall_id,
                    boundary_id=wall.boundary_id,
                    active=wall.active,
                    permanent=wall.permanent,
                    integrity=float(wall.integrity),
                    connected_count=len(connected),
                    adapted_count=sum(1 for state in connected if state.changed),
                    previous_dependency=previous_dependency,
                    new_dependency=new_dependency,
                    previous_transport=previous_transport,
                    new_transport=new_transport,
                    previous_resource=previous_resource,
                    new_resource=new_resource,
                )
            )

        return staged

    @staticmethod
    def _aggregate(
        previous: float,
        connected: list[_InfrastructureState],
        kind: InfrastructureType,
        wall_id: EntityId,
        label: str,
    ) -> float:
        """Return a category score, never below what the wall already carried.

        A category with nothing attached contributes 0.0, which the ``max``
        against the previous value turns into "leave it alone". That is what
        stops a removed route from erasing a reliance the world already built
        up around it.
        """
        candidate = max(
            (state.new_dependency for state in connected if state.infrastructure_type is kind),
            default=0.0,
        )
        return _clamp_unit(max(previous, candidate), f"{label} dependency of wall {wall_id!r}")

    # --- payloads -----------------------------------------------------------

    def _build_infrastructure_payload(
        self, state: _InfrastructureState, world: "World"
    ) -> dict[str, FrozenJsonValue]:
        """Describe one adaptation as strictly JSON-compatible primitives."""
        wall = world.walls[state.wall_id] if state.wall_id is not None else None
        return {
            "infrastructure_id": state.infrastructure_id,
            "boundary_id": state.boundary_id,
            "wall_id": state.wall_id,
            "infrastructure_type": state.infrastructure_type.value,
            "capacity": state.capacity,
            "degraded": state.degraded,
            "adaptation_rate": self._adaptation_rate,
            "previous_dependency_score": state.previous_dependency,
            "new_dependency_score": state.new_dependency,
            "wall_active": None if wall is None else wall.active,
            "wall_permanent": None if wall is None else wall.permanent,
            "wall_built_tick": None if wall is None else wall.built_tick,
        }

    def _build_wall_payload(self, state: _WallState) -> dict[str, FrozenJsonValue]:
        """Describe one wall's dependency growth as JSON-compatible primitives."""
        return {
            "wall_id": state.wall_id,
            "boundary_id": state.boundary_id,
            "active": state.active,
            "permanent": state.permanent,
            "integrity": state.integrity,
            "adaptation_rate": self._adaptation_rate,
            "connected_infrastructure_count": state.connected_count,
            "adapted_infrastructure_count": state.adapted_count,
            "previous_dependency_score": state.previous_dependency,
            "new_dependency_score": state.new_dependency,
            "previous_transport_dependency": state.previous_transport,
            "new_transport_dependency": state.new_transport,
            "previous_resource_dependency": state.previous_resource,
            "new_resource_dependency": state.new_resource,
        }
