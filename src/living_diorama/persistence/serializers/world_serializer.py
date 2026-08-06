"""Serialization and reconstruction of the whole :class:`World` aggregate.

This module owns two things the individual entity serializers cannot: the
whole-aggregate validation that runs before anything is written, and the
ordered reconstruction that rebuilds a world through its public constructors.

The validation is deliberately thorough. A save is the only thing standing
between one episode and the next, so a world whose registries and references
have drifted must be refused rather than written down -- a corrupt save would
make the corruption permanent and, worse, look official.
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from living_diorama.entities import BaseEntity, Boundary, EntityId
from living_diorama.events.event import JsonValue
from living_diorama.persistence.json_codec import require_document
from living_diorama.persistence.schema.world_schema_v1 import (
    ENTITY_COUNT_KEYS,
    SCHEMA_VERSION,
    require_exact_int,
    require_exact_keys,
    require_identifier,
    require_schema_version,
    require_sorted_unique,
)
from living_diorama.persistence.serializers.boundary_serializer import (
    deserialize_boundary,
    serialize_boundary,
)
from living_diorama.persistence.serializers.district_serializer import (
    deserialize_district,
    serialize_district,
)
from living_diorama.persistence.serializers.infrastructure_serializer import (
    deserialize_infrastructure,
    serialize_infrastructure,
)
from living_diorama.persistence.serializers.law_serializer import (
    deserialize_law,
    serialize_law,
)
from living_diorama.persistence.serializers.wall_serializer import (
    deserialize_wall,
    serialize_wall,
)
from living_diorama.simulation.rng import DeterministicRNG
from living_diorama.simulation.world import World

if TYPE_CHECKING:  # pragma: no cover - import exists for typing only
    from living_diorama.entities import Infrastructure

_KEYS: Final = frozenset(
    {
        "boundaries",
        "districts",
        "episode",
        "infrastructure",
        "laws",
        "rng_state",
        "schema_version",
        "tick",
        "walls",
    }
)
"""Exactly the keys a serialized world carries."""

_RESTORE_SEED: Final = 0
"""Seed for the generator that is about to have its state replaced anyway."""

_RNG_STATE_FORMAT_KEY: Final = "state_format"
"""Key naming the RNG state representation version."""

_RNG_STATE_KEYS: Final = frozenset({_RNG_STATE_FORMAT_KEY, "random_state"})
"""Exactly the keys a persisted RNG state carries."""

_SUPPORTED_RNG_STATE_FORMAT: Final = 1
"""The only RNG state format this build reads or writes."""


def _typed_registries(world: World) -> tuple[tuple[str, Mapping[EntityId, BaseEntity]], ...]:
    """Return every public typed registry, paired with what it holds."""
    return (
        ("district", world.districts),
        ("boundary", world.boundaries),
        ("wall", world.walls),
        ("law", world.laws),
        ("infrastructure", world.infrastructure),
    )


def _aggregate_index(world: World) -> Mapping[EntityId, BaseEntity]:
    """Return a read-only view of the aggregate entity index.

    This is the one place persistence looks at a private ``World`` attribute,
    and it is read-only. A phantom index entry -- a name the index knows that
    belongs to no typed registry -- cannot be detected through the public API,
    because every public lookup needs the name you are asking about. Saving a
    world in that state would record an identifier collision as though it were
    the truth.

    The index is never mutated here, and ``World`` is not weakened to make this
    easier.
    """
    return dict(world._entities)  # noqa: SLF001 - read-only integrity check


def validate_world(world: World) -> None:
    """Verify the whole aggregate before any of it is written.

    Checks registry keys, identifier canonicality, world-wide uniqueness, the
    agreement between typed registries and the aggregate index, and the entire
    boundary/wall/infrastructure topology.

    Raises:
        TypeError: If a stored value is of the wrong kind.
        ValueError: If an identifier is noncanonical, a key disagrees with its
            entity, a name is reused, the index disagrees with a registry, or
            the topology is inconsistent.
    """
    if not isinstance(world, World):
        raise TypeError(f"world must be a World, got {type(world).__name__}")
    require_exact_int(world.tick, "world tick")
    require_exact_int(world.episode, "world episode")

    seen: dict[EntityId, str] = {}
    for kind, registry in _typed_registries(world):
        entries = dict(registry)
        for key in sorted(entries, key=repr):
            entity = entries[key]
            require_identifier(key, f"{kind} registry key")
            entity_id = entity.id
            require_identifier(entity_id, f"id of {kind} {key!r}")
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
                    f"the aggregate entity index resolves {key!r} to a different object "
                    f"than the {kind} registry holds"
                )

    index = _aggregate_index(world)
    phantom = sorted(set(index) - set(seen), key=repr)
    if phantom:
        raise ValueError(
            f"the aggregate entity index carries entries no typed registry holds: {phantom}"
        )

    _validate_topology(world)


def _validate_topology(world: World) -> None:
    """Verify every boundary, wall, and infrastructure reference resolves.

    Raises:
        ValueError: If an endpoint is unknown, a boundary joins a district to
            itself, a back-reference disagrees, or two walls claim a boundary.
    """
    for boundary_id in sorted(world.boundaries):
        boundary = world.boundaries[boundary_id]
        for endpoint in (boundary.district_a_id, boundary.district_b_id):
            require_identifier(endpoint, f"endpoint of boundary {boundary_id!r}")
            if endpoint not in world.districts:
                raise ValueError(
                    f"boundary {boundary_id!r} references unknown district {endpoint!r}"
                )
        if boundary.district_a_id == boundary.district_b_id:
            raise ValueError(
                f"boundary {boundary_id!r} joins district {boundary.district_a_id!r} to "
                "itself; a boundary must separate two distinct districts"
            )
        if boundary.wall_id is not None:
            require_identifier(boundary.wall_id, f"wall_id of boundary {boundary_id!r}")
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

    claimed: dict[EntityId, EntityId] = {}
    for wall_id in sorted(world.walls):
        wall = world.walls[wall_id]
        require_identifier(wall.boundary_id, f"boundary_id of wall {wall_id!r}")
        wall_boundary = world.boundaries.get(wall.boundary_id)
        if wall_boundary is None:
            raise ValueError(f"wall {wall_id!r} references unknown boundary {wall.boundary_id!r}")
        if wall_boundary.wall_id != wall_id:
            raise ValueError(
                f"wall {wall_id!r} stands on boundary {wall.boundary_id!r}, but that "
                f"boundary carries {wall_boundary.wall_id!r}"
            )
        if wall.boundary_id in claimed:
            raise ValueError(
                f"boundary {wall.boundary_id!r} is claimed by both "
                f"{claimed[wall.boundary_id]!r} and {wall_id!r}"
            )
        claimed[wall.boundary_id] = wall_id

    for infrastructure_id in sorted(world.infrastructure):
        infrastructure = world.infrastructure[infrastructure_id]
        require_identifier(
            infrastructure.boundary_id, f"boundary_id of infrastructure {infrastructure_id!r}"
        )
        if infrastructure.boundary_id not in world.boundaries:
            raise ValueError(
                f"infrastructure {infrastructure_id!r} references unknown boundary "
                f"{infrastructure.boundary_id!r}"
            )


def entity_counts(world: World) -> dict[str, int]:
    """Return how many entities each typed registry holds."""
    return {
        "boundaries": len(world.boundaries),
        "districts": len(world.districts),
        "infrastructure": len(world.infrastructure),
        "laws": len(world.laws),
        "walls": len(world.walls),
    }


def serialize_world(world: World) -> dict[str, JsonValue]:
    """Return the whole world as a JSON object, after validating it.

    Entity arrays are sorted by identifier so the bytes depend only on the
    state. Two worlds holding the same entities registered in different orders
    therefore hash identically, which is what makes the state hash a statement
    about the world rather than about how it was assembled.

    Raises:
        TypeError: If the argument is not a World or a stored value is mistyped.
        ValueError: If the aggregate is inconsistent or a field is invalid.
    """
    validate_world(world)
    return {
        "boundaries": [
            serialize_boundary(world.boundaries[key]) for key in sorted(world.boundaries)
        ],
        "districts": [serialize_district(world.districts[key]) for key in sorted(world.districts)],
        "episode": world.episode,
        "infrastructure": [
            serialize_infrastructure(world.infrastructure[key])
            for key in sorted(world.infrastructure)
        ],
        "laws": [serialize_law(world.laws[key]) for key in sorted(world.laws)],
        "rng_state": _serialize_rng_state(world),
        "schema_version": SCHEMA_VERSION,
        "tick": world.tick,
        "walls": [serialize_wall(world.walls[key]) for key in sorted(world.walls)],
    }


def require_rng_state(value: JsonValue, description: str = "rng_state") -> dict[str, JsonValue]:
    """Validate a generator state document strictly, and return it.

    ``DeterministicRNG.set_state`` is deliberately forgiving: it checks that two
    keys are present and compares the format with ``!=``, which accepts ``True``
    because ``True == 1``, and ignores any extra keys entirely. That is a
    reasonable in-memory contract, but a save is a permanent record, so
    persistence enforces the stricter schema around it rather than delegating to
    it. ``DeterministicRNG`` itself is locked and is not changed for this.

    Restorability is proven by handing the state to a throwaway generator. That
    draws no numbers, so neither the world's generator nor the saved sequence
    moves.

    Args:
        value: The state document to validate.
        description: What is being checked, used in error messages.

    Returns:
        The validated document.

    Raises:
        TypeError: If the document, or ``state_format``, is of the wrong type.
        ValueError: If keys are missing or extra, the format is unsupported, or
            the random state cannot be restored.
    """
    document = require_document(value, description)
    require_exact_keys(document, _RNG_STATE_KEYS, description)

    state_format = document[_RNG_STATE_FORMAT_KEY]
    if type(state_format) is not int:
        raise TypeError(
            f"{description} {_RNG_STATE_FORMAT_KEY} must be an int, "
            f"got {type(state_format).__name__}"
        )
    if state_format != _SUPPORTED_RNG_STATE_FORMAT:
        raise ValueError(
            f"{description} declares unsupported RNG state format {state_format}; "
            f"this build reads format {_SUPPORTED_RNG_STATE_FORMAT} only"
        )

    probe = DeterministicRNG(_RESTORE_SEED)
    try:
        probe.set_state(document)
    except (TypeError, ValueError, LookupError, OverflowError, AttributeError) as error:
        # ``LookupError`` covers both the missing-index and missing-key shapes a
        # malformed random state can produce; every one of them means the same
        # thing here, and all of them surface as a persistence ValueError with
        # the original cause preserved.
        raise ValueError(f"{description} cannot be restored: {error}") from error
    return document


def _serialize_rng_state(world: World) -> dict[str, JsonValue]:
    """Return the generator's exported state without disturbing it.

    The exported state is taken as-is and validated. Nothing here draws a
    number: doing so would advance the very sequence the save exists to
    preserve, and the next episode would silently start one step late.

    Raises:
        TypeError: If the exported state is not JSON-compatible.
        ValueError: If it is not a restorable state document.
    """
    return require_rng_state(require_document(world.rng.get_state(), "rng_state"))


def _require_array(document: dict[str, JsonValue], key: str) -> list[JsonValue]:
    """Return a named array from a world document.

    Raises:
        TypeError: If the value is not a list.
    """
    value = document[key]
    if type(value) is not list:
        raise TypeError(f"world state {key} must be a list, got {type(value).__name__}")
    return value


def deserialize_world(value: JsonValue) -> World:
    """Rebuild a world from a JSON object, through public constructors only.

    Entities are added in dependency order, and boundaries go in without their
    wall references so that ``World.add_wall`` can establish each link itself.
    Afterwards every reconstructed back-reference is compared against the one
    that was saved, so a save claiming a link the aggregate would not build is
    rejected rather than silently loaded as something slightly different.

    Raises:
        TypeError: If the document or a field is of the wrong type.
        ValueError: If keys are missing or extra, an array is unsorted or holds
            duplicates, the schema version is unsupported, or the reconstructed
            topology disagrees with what was saved.
    """
    document = require_document(value, "world state")
    require_exact_keys(document, _KEYS, "world state")
    require_schema_version(document, "world state")

    tick = require_exact_int(document["tick"], "world state tick")
    episode = require_exact_int(document["episode"], "world state episode")

    rng = DeterministicRNG(_RESTORE_SEED)
    rng.set_state(require_rng_state(document["rng_state"], "world state rng_state"))
    world = World(rng=rng, tick=tick, episode=episode)

    districts = [
        deserialize_district(entry, f"district {index}")
        for index, entry in enumerate(_require_array(document, "districts"))
    ]
    require_sorted_unique([district.id for district in districts], "world state districts")
    for district in districts:
        world.add_district(district)

    staged: list[tuple[Boundary, str | None]] = [
        deserialize_boundary(entry, f"boundary {index}")
        for index, entry in enumerate(_require_array(document, "boundaries"))
    ]
    require_sorted_unique([boundary.id for boundary, _ in staged], "world state boundaries")
    for boundary, _ in staged:
        world.add_boundary(boundary)

    laws = [
        deserialize_law(entry, f"law {index}")
        for index, entry in enumerate(_require_array(document, "laws"))
    ]
    require_sorted_unique([law.id for law in laws], "world state laws")
    for law in laws:
        world.add_law(law)

    walls = [
        deserialize_wall(entry, f"wall {index}")
        for index, entry in enumerate(_require_array(document, "walls"))
    ]
    require_sorted_unique([wall.id for wall in walls], "world state walls")
    for wall in walls:
        world.add_wall(wall)

    for boundary, expected_wall_id in staged:
        rebuilt = world.boundaries[boundary.id].wall_id
        if rebuilt != expected_wall_id:
            raise ValueError(
                f"boundary {boundary.id!r} was saved carrying wall {expected_wall_id!r}, "
                f"but reconstruction produced {rebuilt!r}"
            )

    infrastructure: list[Infrastructure] = [
        deserialize_infrastructure(entry, f"infrastructure {index}")
        for index, entry in enumerate(_require_array(document, "infrastructure"))
    ]
    require_sorted_unique([entity.id for entity in infrastructure], "world state infrastructure")
    for entity in infrastructure:
        world.add_infrastructure(entity)

    validate_world(world)
    return world


def require_entity_counts(world: World, counts: Mapping[str, int]) -> None:
    """Verify recorded entity counts match the world that was loaded.

    Raises:
        ValueError: If any count disagrees.
    """
    actual = entity_counts(world)
    for key in ENTITY_COUNT_KEYS:
        if counts.get(key) != actual[key]:
            raise ValueError(
                f"manifest records {counts.get(key)!r} {key} but the world state holds "
                f"{actual[key]}"
            )
