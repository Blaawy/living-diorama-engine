"""The World aggregate root: the complete in-memory state of one simulation.

World owns every entity registry and the run's random generator, and it is the
only place where cross-entity referential integrity is enforced. It is a
container and a gatekeeper, not a simulator: it performs no calculations,
publishes no events, and touches no files. Systems do all of that.
"""

from collections.abc import Mapping
from types import MappingProxyType

from living_diorama.entities import (
    BaseEntity,
    Boundary,
    District,
    EntityId,
    Infrastructure,
    Law,
    Tick,
    Wall,
)
from living_diorama.simulation.rng import DeterministicRNG


def _require_non_negative_int(value: int, field_name: str) -> None:
    """Validate that a counter is a genuine non-negative int.

    ``bool`` is checked for explicitly because it subclasses ``int``, and
    ``World(tick=True)`` is far more likely to be an argument mistake than an
    intent to start at tick 1.

    Args:
        value: The value to check.
        field_name: Name of the field, used in the error message.

    Raises:
        TypeError: If the value is not an int, or is a bool.
        ValueError: If the value is negative.
    """
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0, got {value}")


class World:
    """The mutable aggregate root holding one world's complete state.

    **Registries are private.** Each entity kind is stored in a private dict and
    exposed only as a read-only mapping view, so nothing outside can insert an
    entity that has not passed reference validation. Every mutation goes through
    an ``add_*`` method. The views are live: an entity added through the proper
    door appears in them immediately.

    **Identifiers are unique world-wide**, not merely within a registry. A
    single index across all kinds backs :meth:`get_entity` and :meth:`has_entity`
    and makes the uniqueness check cheap and total.

    **Entities are added in dependency order.** Districts before the boundaries
    that join them, boundaries before the walls and infrastructure that attach
    to them. Each ``add_*`` validates its references against what already
    exists, so an out-of-order add is refused rather than accepted and patched
    up later. This is the simplest of the designs considered -- no builder, no
    deferred validation pass, and no window during which a world is half-valid.

    **Unknown identifiers raise ``KeyError``.** The typed getters return the
    entity type itself rather than an optional, because a ``None`` leaking into
    a later arithmetic system would surface far from its cause. Ask
    :meth:`has_entity` when absence is a legitimate answer.

    World is deliberately mutable and deliberately has no value equality: it is
    an identity-bearing aggregate carrying live RNG state, and comparing two
    worlds by field is not a meaningful operation in this phase.
    """

    __slots__ = (
        "_boundaries",
        "_districts",
        "_entities",
        "_episode",
        "_infrastructure",
        "_laws",
        "_rng",
        "_tick",
        "_walls",
    )

    def __init__(self, *, rng: DeterministicRNG, tick: Tick = 0, episode: int = 0) -> None:
        """Create an empty world.

        Args:
            rng: The seeded generator this world owns. All simulation
                randomness must be drawn from it.
            tick: Starting tick, normally 0 for a new world or the saved tick
                when resuming an episode.
            episode: Episode number this world belongs to.

        Raises:
            TypeError: If ``rng`` is not a DeterministicRNG, or if ``tick`` or
                ``episode`` is not an int.
            ValueError: If ``tick`` or ``episode`` is negative.
        """
        if not isinstance(rng, DeterministicRNG):
            raise TypeError(f"rng must be a DeterministicRNG, got {type(rng).__name__}")
        _require_non_negative_int(tick, "tick")
        _require_non_negative_int(episode, "episode")

        self._rng = rng
        self._tick = tick
        self._episode = episode

        self._districts: dict[EntityId, District] = {}
        self._boundaries: dict[EntityId, Boundary] = {}
        self._walls: dict[EntityId, Wall] = {}
        self._laws: dict[EntityId, Law] = {}
        self._infrastructure: dict[EntityId, Infrastructure] = {}
        self._entities: dict[EntityId, BaseEntity] = {}

    @property
    def tick(self) -> Tick:
        """The tick currently being simulated."""
        return self._tick

    @property
    def episode(self) -> int:
        """The episode number this world belongs to."""
        return self._episode

    @property
    def rng(self) -> DeterministicRNG:
        """The generator this world owns. Systems draw all randomness from it."""
        return self._rng

    @property
    def districts(self) -> Mapping[EntityId, District]:
        """Read-only view of the district registry, keyed by entity id."""
        return MappingProxyType(self._districts)

    @property
    def boundaries(self) -> Mapping[EntityId, Boundary]:
        """Read-only view of the boundary registry, keyed by entity id."""
        return MappingProxyType(self._boundaries)

    @property
    def walls(self) -> Mapping[EntityId, Wall]:
        """Read-only view of the wall registry, keyed by entity id."""
        return MappingProxyType(self._walls)

    @property
    def laws(self) -> Mapping[EntityId, Law]:
        """Read-only view of the law registry, keyed by entity id."""
        return MappingProxyType(self._laws)

    @property
    def infrastructure(self) -> Mapping[EntityId, Infrastructure]:
        """Read-only view of the infrastructure registry, keyed by entity id."""
        return MappingProxyType(self._infrastructure)

    def advance_tick(self) -> None:
        """Move the world forward by exactly one tick.

        The only mutation of time available, and the only one the simulation
        loop needs. Time cannot be set to an arbitrary value from outside,
        which keeps a run's tick count equal to the number of ticks actually
        simulated.
        """
        self._tick += 1

    def add_district(self, district: District) -> None:
        """Register a district.

        Args:
            district: The district to add.

        Raises:
            TypeError: If the argument is not a District.
            ValueError: If its id is already in use anywhere in this world.
        """
        self._require_type(district, District, "district")
        self._require_unused_id(district.id)
        self._districts[district.id] = district
        self._entities[district.id] = district

    def add_boundary(self, boundary: Boundary) -> None:
        """Register a boundary between two existing districts.

        Both endpoints must already exist as districts, which is why districts
        are added first. A boundary carrying a ``wall_id`` is accepted only if
        that wall already exists and names this same boundary; ordinarily the
        field is left ``None`` and filled in by :meth:`add_wall`.

        Args:
            boundary: The boundary to add.

        Raises:
            TypeError: If the argument is not a Boundary.
            ValueError: If its id is in use, if either endpoint is not an
                existing district, if a referenced wall does not exist or names
                a different boundary, or if that wall already belongs to
                another boundary.
        """
        self._require_type(boundary, Boundary, "boundary")
        self._require_unused_id(boundary.id)

        for endpoint in (boundary.district_a_id, boundary.district_b_id):
            if endpoint not in self._districts:
                raise ValueError(
                    f"boundary {boundary.id!r} references unknown district {endpoint!r}; "
                    "add districts before the boundaries that join them"
                )

        if boundary.wall_id is not None:
            wall = self._walls.get(boundary.wall_id)
            if wall is None:
                raise ValueError(
                    f"boundary {boundary.id!r} references unknown wall {boundary.wall_id!r}"
                )
            if wall.boundary_id != boundary.id:
                raise ValueError(
                    f"back-reference mismatch: boundary {boundary.id!r} claims wall "
                    f"{wall.id!r}, but that wall stands on boundary {wall.boundary_id!r}"
                )

        self._boundaries[boundary.id] = boundary
        self._entities[boundary.id] = boundary

    def add_wall(self, wall: Wall) -> None:
        """Register a wall on an existing boundary and link the two together.

        At most one wall may stand on a boundary in the MVP. On success the
        boundary's ``wall_id`` is set to this wall, so the back-reference is
        maintained by the aggregate rather than left to the caller -- a caller
        setting it by hand would be mutating registry state without passing
        through validation.

        Args:
            wall: The wall to add.

        Raises:
            TypeError: If the argument is not a Wall.
            ValueError: If its id is in use, if its boundary does not exist, if
                that boundary already carries a different wall, or if the
                boundary's existing ``wall_id`` names a different wall.
        """
        self._require_type(wall, Wall, "wall")
        self._require_unused_id(wall.id)

        boundary = self._boundaries.get(wall.boundary_id)
        if boundary is None:
            raise ValueError(
                f"wall {wall.id!r} references unknown boundary {wall.boundary_id!r}; "
                "add the boundary before the wall that stands on it"
            )

        if boundary.wall_id is not None and boundary.wall_id != wall.id:
            raise ValueError(
                f"boundary {boundary.id!r} already carries wall {boundary.wall_id!r}; "
                "at most one wall may stand on a boundary"
            )

        existing = self._wall_on_boundary(wall.boundary_id)
        if existing is not None:
            raise ValueError(
                f"boundary {wall.boundary_id!r} already carries wall {existing.id!r}; "
                "at most one wall may stand on a boundary"
            )

        self._walls[wall.id] = wall
        self._entities[wall.id] = wall
        boundary.wall_id = wall.id

    def add_law(self, law: Law) -> None:
        """Register a law.

        Laws reference no other entity, so there is nothing to validate beyond
        identifier uniqueness.

        Args:
            law: The law to add.

        Raises:
            TypeError: If the argument is not a Law.
            ValueError: If its id is already in use anywhere in this world.
        """
        self._require_type(law, Law, "law")
        self._require_unused_id(law.id)
        self._laws[law.id] = law
        self._entities[law.id] = law

    def add_infrastructure(self, infrastructure: Infrastructure) -> None:
        """Register infrastructure attached to an existing boundary.

        Args:
            infrastructure: The infrastructure to add.

        Raises:
            TypeError: If the argument is not an Infrastructure.
            ValueError: If its id is in use or its boundary does not exist.
        """
        self._require_type(infrastructure, Infrastructure, "infrastructure")
        self._require_unused_id(infrastructure.id)

        if infrastructure.boundary_id not in self._boundaries:
            raise ValueError(
                f"infrastructure {infrastructure.id!r} references unknown boundary "
                f"{infrastructure.boundary_id!r}; add the boundary first"
            )

        self._infrastructure[infrastructure.id] = infrastructure
        self._entities[infrastructure.id] = infrastructure

    def has_entity(self, entity_id: EntityId) -> bool:
        """Return whether any entity in this world carries the given id.

        Args:
            entity_id: The identifier to look for.

        Returns:
            True if an entity of any kind has this id.
        """
        return entity_id in self._entities

    def get_entity(self, entity_id: EntityId) -> BaseEntity:
        """Return the entity with this id, whatever kind it is.

        Args:
            entity_id: The identifier to look up.

        Returns:
            The entity registered under this id.

        Raises:
            KeyError: If no entity in this world has this id.
        """
        try:
            return self._entities[entity_id]
        except KeyError:
            raise KeyError(f"no entity with id {entity_id!r}") from None

    def get_district(self, entity_id: EntityId) -> District:
        """Return the district with this id.

        Args:
            entity_id: The identifier to look up.

        Returns:
            The district registered under this id.

        Raises:
            KeyError: If no district has this id, including when an entity of a
                different kind does.
        """
        return self._get_typed(self._districts, entity_id, "district")

    def get_boundary(self, entity_id: EntityId) -> Boundary:
        """Return the boundary with this id.

        Args:
            entity_id: The identifier to look up.

        Returns:
            The boundary registered under this id.

        Raises:
            KeyError: If no boundary has this id.
        """
        return self._get_typed(self._boundaries, entity_id, "boundary")

    def get_wall(self, entity_id: EntityId) -> Wall:
        """Return the wall with this id.

        Args:
            entity_id: The identifier to look up.

        Returns:
            The wall registered under this id.

        Raises:
            KeyError: If no wall has this id.
        """
        return self._get_typed(self._walls, entity_id, "wall")

    def get_law(self, entity_id: EntityId) -> Law:
        """Return the law with this id.

        Args:
            entity_id: The identifier to look up.

        Returns:
            The law registered under this id.

        Raises:
            KeyError: If no law has this id.
        """
        return self._get_typed(self._laws, entity_id, "law")

    def get_infrastructure(self, entity_id: EntityId) -> Infrastructure:
        """Return the infrastructure with this id.

        Args:
            entity_id: The identifier to look up.

        Returns:
            The infrastructure registered under this id.

        Raises:
            KeyError: If no infrastructure has this id.
        """
        return self._get_typed(self._infrastructure, entity_id, "infrastructure")

    def _get_typed[EntityT](
        self, registry: dict[EntityId, EntityT], entity_id: EntityId, kind: str
    ) -> EntityT:
        """Look an entity up in one registry, reporting a type mismatch clearly."""
        entity = registry.get(entity_id)
        if entity is None:
            if entity_id in self._entities:
                actual = type(self._entities[entity_id]).__name__
                raise KeyError(f"no {kind} with id {entity_id!r}; it is a {actual}")
            raise KeyError(f"no {kind} with id {entity_id!r}")
        return entity

    def _wall_on_boundary(self, boundary_id: EntityId) -> Wall | None:
        """Return the wall standing on a boundary, if any."""
        for wall in self._walls.values():
            if wall.boundary_id == boundary_id:
                return wall
        return None

    def _require_unused_id(self, entity_id: EntityId) -> None:
        """Reject an identifier already used by any entity in this world."""
        if entity_id in self._entities:
            existing = type(self._entities[entity_id]).__name__
            raise ValueError(
                f"id {entity_id!r} is already used by a {existing}; "
                "identifiers must be unique across the whole world"
            )

    @staticmethod
    def _require_type(value: object, expected: type, label: str) -> None:
        """Reject an argument that is not the entity kind this method registers."""
        if not isinstance(value, expected):
            raise TypeError(f"{label} must be a {expected.__name__}, got {type(value).__name__}")
