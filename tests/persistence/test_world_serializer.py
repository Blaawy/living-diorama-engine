"""Tests for whole-world serialization, validation, and reconstruction."""

import pytest

from living_diorama.entities import Boundary, ResourcePool, ResourceType
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.serializers.world_serializer import (
    deserialize_world,
    entity_counts,
    require_rng_state,
    serialize_world,
    validate_world,
)
from living_diorama.simulation.rng import DeterministicRNG
from living_diorama.simulation.world import World
from persistence.conftest import (
    build_district,
    build_law,
    build_wall,
    consumed_rng,
    minimal_world,
    rich_world,
    rng_sequence,
    structural_state,
)


def round_trip(world: World) -> World:
    """Serialize a world through real save bytes and rebuild it."""
    return deserialize_world(loads_canonical(dumps_canonical(serialize_world(world))))


# --- Shape ------------------------------------------------------------------


def test_the_document_carries_exactly_the_expected_top_level_keys() -> None:
    """A fixed shape is what makes an unexpected key detectable as corruption."""
    document = serialize_world(rich_world())
    assert sorted(document) == [
        "boundaries",
        "districts",
        "episode",
        "infrastructure",
        "laws",
        "rng_state",
        "schema_version",
        "tick",
        "walls",
    ]
    assert document["schema_version"] == 1


def test_entity_arrays_are_sorted_by_id() -> None:
    """Sorted arrays make the bytes describe the world, not how it was built."""
    document = serialize_world(rich_world())
    for key in ("boundaries", "districts", "infrastructure", "laws", "walls"):
        ids = [entry["id"] for entry in document[key]]
        assert ids == sorted(ids), key


def test_registration_order_does_not_change_the_bytes() -> None:
    """Two worlds holding the same entities must hash identically.

    Otherwise the state hash would record the order districts happened to be
    added, and two runs of the same episode would disagree for no reason.
    """

    def build(reverse: bool) -> World:
        """Build the same world with registration order optionally reversed."""
        world = World(rng=consumed_rng(), tick=5, episode=0)
        districts = [build_district(f"district_{name}") for name in ("a", "b", "c")]
        for district in reversed(districts) if reverse else districts:
            world.add_district(district)
        pairs = [
            ("boundary_ab", "district_a", "district_b"),
            ("boundary_bc", "district_b", "district_c"),
        ]
        for boundary_id, first, second in reversed(pairs) if reverse else pairs:
            world.add_boundary(
                Boundary(
                    id=boundary_id,
                    created_tick=0,
                    district_a_id=first,
                    district_b_id=second,
                )
            )
        laws = [build_law("law_a"), build_law("law_b")]
        for law in reversed(laws) if reverse else laws:
            world.add_law(law)
        return world

    assert dumps_canonical(serialize_world(build(False))) == dumps_canonical(
        serialize_world(build(True))
    )


def test_resource_mapping_insertion_order_does_not_change_the_bytes() -> None:
    """The same holds inside a resource pool."""
    forward = minimal_world()
    backward = minimal_world()
    forward.districts["district_a"].resources = ResourcePool(
        stock={ResourceType.FOOD: 1.0, ResourceType.ENERGY: 2.0}
    )
    backward.districts["district_a"].resources = ResourcePool(
        stock={ResourceType.ENERGY: 2.0, ResourceType.FOOD: 1.0}
    )
    assert dumps_canonical(serialize_world(forward)) == dumps_canonical(serialize_world(backward))


def test_entity_counts_match_the_registries() -> None:
    """The counts the manifest records come straight from the aggregate."""
    world = rich_world()
    assert entity_counts(world) == {
        "boundaries": len(world.boundaries),
        "districts": len(world.districts),
        "infrastructure": len(world.infrastructure),
        "laws": len(world.laws),
        "walls": len(world.walls),
    }


# --- Fidelity ---------------------------------------------------------------


def test_a_rich_world_round_trips_structurally() -> None:
    """Every stored field of every entity returns unchanged."""
    original = rich_world()
    assert structural_state(round_trip(original)) == structural_state(original)


def test_reserialization_produces_identical_bytes() -> None:
    """Saving, loading, and saving again must land on the same bytes.

    A round trip that merely looked equivalent could still drift the hash, and
    then a child episode would fail to link to a parent that had not changed.
    """
    original = rich_world()
    first = dumps_canonical(serialize_world(original))
    second = dumps_canonical(serialize_world(round_trip(original)))
    assert first == second


def test_the_restored_generator_continues_the_same_sequence() -> None:
    """A save resumes the stream rather than restarting it.

    Both sides are compared from equivalent restored states, so neither
    generator is read further than the other before the comparison starts.
    """
    original = rich_world()
    restored = round_trip(original)

    reference = DeterministicRNG(0)
    reference.set_state(original.rng.get_state())
    assert rng_sequence(restored.rng) == rng_sequence(reference)


def test_serializing_does_not_consume_randomness() -> None:
    """Drawing a number to check the generator would advance the episode."""
    world = rich_world()
    before = world.rng.get_state()
    serialize_world(world)
    assert world.rng.get_state() == before


def test_an_empty_world_round_trips() -> None:
    """A world with nothing in it is valid and must survive a save."""
    world = World(rng=consumed_rng(), tick=0, episode=0)
    assert structural_state(round_trip(world)) == structural_state(world)


def test_a_wall_free_boundary_survives_reconstruction() -> None:
    """Absence of a wall is state too, and must not be filled in."""
    restored = round_trip(rich_world())
    assert restored.boundaries["boundary_open"].wall_id is None
    assert restored.boundaries["boundary_ab"].wall_id == "wall_boundary_ab"


def test_reconstruction_rebuilds_the_wall_back_reference_through_the_aggregate() -> None:
    """The link is built by ``World.add_wall``, then checked against the save."""
    restored = round_trip(rich_world())
    for wall_id, wall in restored.walls.items():
        assert restored.boundaries[wall.boundary_id].wall_id == wall_id


# --- Validation before writing ----------------------------------------------


def test_a_registry_key_disagreeing_with_its_entity_is_refused() -> None:
    """The key and the entity have to be talking about the same thing."""
    world = minimal_world()
    world.districts["district_a"].id = "renamed"
    with pytest.raises(ValueError):
        serialize_world(world)


@pytest.mark.parametrize("bad", ["district_a ", " district_a", "", "   "])
def test_a_noncanonical_registry_key_is_refused(bad: str) -> None:
    """Key and id can agree and still both be wrong."""
    world = minimal_world()
    world._districts[bad] = world._districts.pop("district_a")
    world._districts[bad].id = bad
    world._entities[bad] = world._entities.pop("district_a")
    with pytest.raises((TypeError, ValueError)):
        serialize_world(world)


def test_an_id_missing_from_the_aggregate_index_is_refused() -> None:
    """``has_entity`` cannot vouch for a world whose two views have drifted."""
    world = minimal_world()
    del world._entities["district_a"]
    with pytest.raises(ValueError):
        serialize_world(world)


def test_an_aggregate_index_pointing_at_another_object_is_refused() -> None:
    """An index entry must resolve to the very object the registry holds."""
    world = minimal_world()
    world._entities["district_a"] = world._districts["district_b"]
    with pytest.raises(ValueError):
        serialize_world(world)


def test_a_phantom_aggregate_index_entry_is_refused() -> None:
    """A name the index knows but no registry holds cannot be found any other way.

    Every public lookup needs the name you are asking about, so a phantom entry
    is invisible until the index itself is inspected.
    """
    world = minimal_world()
    world._entities["ghost"] = world._districts["district_a"]
    with pytest.raises(ValueError):
        serialize_world(world)


def test_the_same_id_in_two_typed_registries_is_refused() -> None:
    """One identifier may not name two things."""
    world = minimal_world()
    world._laws["district_a"] = build_law("district_a")
    with pytest.raises(ValueError):
        serialize_world(world)


def test_a_mutated_self_loop_boundary_is_refused() -> None:
    """The constructor forbids it; the entity stays mutable afterwards."""
    world = minimal_world()
    world.boundaries["boundary_ab"].district_b_id = "district_a"
    with pytest.raises(ValueError):
        serialize_world(world)


def test_a_boundary_pointing_at_a_missing_district_is_refused() -> None:
    """A dangling endpoint cannot be written down as though it resolved."""
    world = minimal_world()
    world.boundaries["boundary_ab"].district_b_id = "nowhere"
    with pytest.raises(ValueError):
        serialize_world(world)


def test_a_boundary_naming_a_missing_wall_is_refused() -> None:
    """A back-reference to nothing is a broken world."""
    world = minimal_world()
    world.boundaries["boundary_ab"].wall_id = "ghost"
    with pytest.raises(ValueError):
        serialize_world(world)


def test_a_wall_and_boundary_disagreeing_is_refused() -> None:
    """References must be consistent in both directions."""
    world = rich_world()
    world.walls["wall_boundary_ab"].boundary_id = "boundary_open"
    with pytest.raises(ValueError):
        serialize_world(world)


def test_two_walls_claiming_one_boundary_is_refused() -> None:
    """At most one wall may stand on a boundary."""
    world = rich_world()
    intruder = build_wall("wall_intruder", "boundary_ab", active=True)
    world._walls["wall_intruder"] = intruder
    world._entities["wall_intruder"] = intruder
    with pytest.raises(ValueError):
        serialize_world(world)


def test_infrastructure_pointing_at_an_unknown_boundary_is_refused() -> None:
    """A dangling attachment cannot be persisted."""
    world = rich_world()
    world.infrastructure["infra_0"].boundary_id = "nowhere"
    with pytest.raises(ValueError):
        serialize_world(world)


def test_validate_world_rejects_a_non_world() -> None:
    """Validation is about the aggregate, not about anything shaped like one."""
    with pytest.raises(TypeError):
        validate_world({"tick": 0})  # type: ignore[arg-type]


# --- Validation while loading -----------------------------------------------


def test_an_unsorted_entity_array_is_refused() -> None:
    """This writer sorts; a file that is out of order came from somewhere else."""
    document = serialize_world(rich_world())
    document["districts"] = list(reversed(document["districts"]))
    with pytest.raises(ValueError):
        deserialize_world(document)


def test_a_duplicate_entity_id_is_refused() -> None:
    """Two entries claiming one name cannot both be loaded."""
    document = serialize_world(rich_world())
    document["districts"] = [document["districts"][0], document["districts"][0]]
    with pytest.raises(ValueError):
        deserialize_world(document)


def test_an_unsupported_schema_version_is_refused() -> None:
    """Guessing how to migrate an unknown version is how a save becomes wrong."""
    document = serialize_world(rich_world())
    document["schema_version"] = 2
    with pytest.raises(ValueError):
        deserialize_world(document)


def test_a_missing_top_level_key_is_refused() -> None:
    """An incomplete document cannot be completed by assumption."""
    document = serialize_world(rich_world())
    del document["laws"]
    with pytest.raises(ValueError):
        deserialize_world(document)


def test_an_unexpected_top_level_key_is_refused() -> None:
    """A key this build does not understand may be carrying meaning."""
    document = serialize_world(rich_world())
    document["surprise"] = 1
    with pytest.raises(ValueError):
        deserialize_world(document)


@pytest.mark.parametrize("bad", [{}, {"random_state": []}, {"state_format": "unknown"}])
def test_a_corrupt_rng_state_is_refused(bad: dict) -> None:
    """A generator that cannot be restored would silently restart the stream."""
    document = serialize_world(rich_world())
    document["rng_state"] = bad
    with pytest.raises((TypeError, ValueError)):
        deserialize_world(document)


def test_a_persisted_boundary_claiming_the_wrong_wall_is_refused() -> None:
    """Reconstruction compares the link it rebuilds against the one saved."""
    document = serialize_world(rich_world())
    for entry in document["boundaries"]:
        if entry["id"] == "boundary_open":
            entry["wall_id"] = "wall_boundary_ab"
    with pytest.raises(ValueError):
        deserialize_world(document)


def test_a_persisted_boundary_dropping_its_wall_is_refused() -> None:
    """A save that omits a link the aggregate would rebuild is not this world."""
    document = serialize_world(rich_world())
    for entry in document["boundaries"]:
        if entry["id"] == "boundary_ab":
            entry["wall_id"] = None
    with pytest.raises(ValueError):
        deserialize_world(document)


def test_a_persisted_wall_on_an_unknown_boundary_is_refused() -> None:
    """The aggregate refuses it, and the error is not swallowed."""
    document = serialize_world(rich_world())
    for entry in document["walls"]:
        entry["boundary_id"] = "nowhere"
    with pytest.raises(ValueError):
        deserialize_world(document)


# --- Correction 3: the persisted RNG schema is stricter than the in-memory one
#
# ``DeterministicRNG.set_state`` accepts extra keys and compares its format with
# ``!=``, which lets ``True`` through because ``True == 1``. That is a workable
# in-memory contract, but a save is permanent, so persistence enforces the
# stricter schema around it. ``DeterministicRNG`` itself is locked and unchanged.


def valid_rng_state() -> dict:
    """Return a real exported generator state."""
    return consumed_rng().get_state()


def test_a_valid_rng_state_is_accepted_unchanged() -> None:
    """The control case: strictness must not reject a genuine state."""
    state = valid_rng_state()
    assert require_rng_state(state) == state


def test_an_rng_state_with_an_extra_key_is_refused() -> None:
    """The locked in-memory contract ignores extra keys; a save may not."""
    with pytest.raises(ValueError):
        require_rng_state({**valid_rng_state(), "extra": 1})


@pytest.mark.parametrize("missing", ["state_format", "random_state"])
def test_an_rng_state_missing_a_key_is_refused(missing: str) -> None:
    """Both keys are required; neither is defaulted."""
    state = valid_rng_state()
    del state[missing]
    with pytest.raises(ValueError):
        require_rng_state(state)


@pytest.mark.parametrize("bad", [True, False, 1.0, "1", None])
def test_a_mistyped_rng_state_format_is_refused(bad: object) -> None:
    """``True == 1`` is why this is an exact type check rather than a comparison."""
    with pytest.raises(TypeError):
        require_rng_state({**valid_rng_state(), "state_format": bad})


@pytest.mark.parametrize("bad", [0, 2, 99])
def test_an_unsupported_rng_state_format_is_refused(bad: int) -> None:
    """An exact integer this build does not understand still fails."""
    with pytest.raises(ValueError):
        require_rng_state({**valid_rng_state(), "state_format": bad})


@pytest.mark.parametrize(
    "bad",
    [
        [],
        [1, 2],
        "not a state",
        {"k": "v"},
        [3, [1, 2, 3], None],
        [3, ["a"] * 625, None],
    ],
)
def test_a_malformed_random_state_is_refused(bad: object) -> None:
    """Restorability is proven by trying it, not assumed from the shape."""
    with pytest.raises((TypeError, ValueError)):
        require_rng_state({"state_format": 1, "random_state": bad})


def test_validating_an_rng_state_consumes_no_randomness() -> None:
    """The probe generator is a throwaway; nothing draws from the world's."""
    world = rich_world()
    before = world.rng.get_state()
    require_rng_state(world.rng.get_state())
    serialize_world(world)
    assert world.rng.get_state() == before


def test_a_corrupt_rng_state_is_refused_during_save() -> None:
    """Validated on the way out as well as the way in.

    A world whose generator state cannot be restored would produce a save that
    silently restarts the sequence instead of resuming it.
    """
    world = minimal_world()
    original = DeterministicRNG.get_state

    def broken(self: DeterministicRNG) -> dict:
        """Stand in for the exporter and return an unrestorable state."""
        return {"state_format": 1, "random_state": [3, [1, 2], None]}

    # Patched on the class: DeterministicRNG uses __slots__, so an instance
    # cannot carry a replacement attribute.
    DeterministicRNG.get_state = broken  # type: ignore[method-assign]
    try:
        with pytest.raises(ValueError):
            serialize_world(world)
    finally:
        DeterministicRNG.get_state = original  # type: ignore[method-assign]


def test_a_persisted_rng_state_with_an_extra_key_is_refused_on_load() -> None:
    """The same schema applies to a file as to an in-memory export."""
    document = serialize_world(rich_world())
    document["rng_state"] = {**document["rng_state"], "extra": 1}
    with pytest.raises(ValueError):
        deserialize_world(document)


def test_the_restored_generator_continues_after_a_strict_load() -> None:
    """Strictness must not change what a valid state restores to."""
    original = rich_world()
    restored = round_trip(original)

    reference = DeterministicRNG(0)
    reference.set_state(original.rng.get_state())
    assert rng_sequence(restored.rng) == rng_sequence(reference)


# --- Correction 6: a corrupted ResourcePool is refused, not repaired --------


def corrupt_stock(world: World, stock: object) -> None:
    """Replace a district's stored stock mapping, bypassing the constructor."""
    object.__setattr__(world.districts["district_a"].resources, "stock", stock)


def test_an_unknown_resource_key_is_refused_rather_than_dropped() -> None:
    """Candidate V1 wrote a repaired subset and discarded the unknown entry.

    Silently normalizing means the save disagrees with the world it claims to
    record, and the disagreement is invisible afterwards.
    """
    world = minimal_world()
    corrupt_stock(world, {**{r: 1.0 for r in ResourceType}, "UNKNOWN": 5.0})
    with pytest.raises(ValueError):
        serialize_world(world)


def test_a_string_pretending_to_be_a_resource_is_refused() -> None:
    """A key that merely spells the name is not the enum member."""
    world = minimal_world()
    corrupt_stock(world, {**{r: 1.0 for r in ResourceType}, "FOOD": 9.0})
    with pytest.raises(ValueError):
        serialize_world(world)


def test_a_missing_resource_is_refused_rather_than_defaulted() -> None:
    """Defaulting it to zero would invent state the world never held."""
    world = minimal_world()
    corrupt_stock(world, {ResourceType.FOOD: 1.0, ResourceType.MATERIALS: 1.0})
    with pytest.raises(ValueError):
        serialize_world(world)


def test_a_non_mapping_stock_is_refused() -> None:
    """The stock has to be a mapping before its keys can mean anything."""
    world = minimal_world()
    corrupt_stock(world, [1.0, 2.0, 3.0])
    with pytest.raises(TypeError):
        serialize_world(world)


@pytest.mark.parametrize("bad", [True, "1.0", None, float("nan"), float("inf"), -1.0])
def test_a_corrupt_resource_amount_is_refused(bad: object) -> None:
    """Amounts are validated as found, not coerced."""
    world = minimal_world()
    corrupt_stock(world, {**{r: 1.0 for r in ResourceType}, ResourceType.FOOD: bad})
    with pytest.raises((TypeError, ValueError)):
        serialize_world(world)


def test_a_healthy_resource_pool_still_serializes() -> None:
    """The control case for the new key check."""
    world = minimal_world()
    corrupt_stock(world, {r: 2.5 for r in ResourceType})
    document = serialize_world(world)
    district = next(entry for entry in document["districts"] if entry["id"] == "district_a")
    assert district["resources"] == {resource.value: 2.5 for resource in ResourceType}


# --- hostile __class__ inside a full world -----------------------------------


class HostileClass:
    """Raises from ``__class__`` instead of answering."""

    @property
    def __class__(self) -> type:
        """Raise instead of revealing a type."""
        raise RuntimeError("boom")


def plant_hostile(world: World, registry_attr: str) -> None:
    """Replace one entity of the given registry with a hostile lookalike."""
    registry = getattr(world, registry_attr)
    key = sorted(registry)[0]
    fake = HostileClass()
    for klass in type(registry[key]).__mro__:
        for name in getattr(klass, "__slots__", ()):
            setattr(fake, name, getattr(registry[key], name))
    registry[key] = fake
    world._entities[key] = fake


@pytest.mark.parametrize(
    ("registry_attr", "message"),
    [
        ("_districts", "district must be a District, got HostileClass"),
        ("_boundaries", "boundary must be a Boundary, got HostileClass"),
        ("_walls", "wall must be a Wall, got HostileClass"),
        ("_laws", "law must be a Law, got HostileClass"),
        ("_infrastructure", "infrastructure must be an Infrastructure, got HostileClass"),
    ],
)
def test_a_hostile_entity_inside_a_world_is_refused_deterministically(
    registry_attr: str, message: str
) -> None:
    """Each hostile entity gets the documented refusal, never its own exception."""
    world = rich_world()
    plant_hostile(world, registry_attr)
    with pytest.raises(TypeError, match=message):
        serialize_world(world)


def test_a_legitimate_world_subclass_serializes_identically() -> None:
    """A World subclass produces exactly the document its base twin produces."""

    class ObservantWorld(World):
        """A World subclass that changes nothing."""

    world = rich_world()
    twin = ObservantWorld.__new__(ObservantWorld)
    for klass in type(world).__mro__:
        for name in getattr(klass, "__slots__", ()):
            setattr(twin, name, getattr(world, name))

    assert serialize_world(twin) == serialize_world(world)
