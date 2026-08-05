"""Tests for the World aggregate root: registries, uniqueness, and referential integrity.

World is the only place cross-entity references are checked. If it accepts a
boundary pointing at a district that does not exist, every later phase inherits
a world that cannot be reasoned about, so these tests are about what World
refuses as much as what it accepts.
"""

import pytest
from simulation_builders import (
    build_boundary,
    build_district,
    build_infrastructure,
    build_law,
    build_linked_world,
    build_wall,
    build_world,
)

from living_diorama.entities import Boundary, District, Infrastructure, Law, Wall
from living_diorama.simulation import DeterministicRNG, World


def test_empty_world_constructs_with_valid_state() -> None:
    """A new world starts empty, at the tick and episode it was given."""
    world = build_world(tick=0, episode=3)
    assert world.tick == 0
    assert world.episode == 3
    assert isinstance(world.rng, DeterministicRNG)
    assert len(world.districts) == 0
    assert len(world.boundaries) == 0


def test_world_can_resume_from_a_nonzero_tick() -> None:
    """Resuming an episode starts from the saved tick, not from zero."""
    assert build_world(tick=4200).tick == 4200


def test_rejects_negative_tick() -> None:
    """Time starts at zero; a world cannot begin before it."""
    with pytest.raises(ValueError):
        build_world(tick=-1)


def test_rejects_bool_tick() -> None:
    """Bool subclasses int, so True would silently mean tick 1."""
    with pytest.raises(TypeError):
        World(rng=DeterministicRNG(1), tick=True)  # type: ignore[arg-type]


def test_rejects_negative_episode() -> None:
    """Episodes are numbered from zero."""
    with pytest.raises(ValueError):
        build_world(episode=-1)


def test_rejects_bool_episode() -> None:
    """An episode number must be a genuine int, not a bool."""
    with pytest.raises(TypeError):
        World(rng=DeterministicRNG(1), episode=True)  # type: ignore[arg-type]


def test_rejects_missing_rng() -> None:
    """A world without a generator could not run deterministically."""
    with pytest.raises(TypeError):
        World(rng="not-an-rng")  # type: ignore[arg-type]


def test_district_can_be_added_and_retrieved() -> None:
    """The basic registry round trip."""
    world = build_world()
    district = build_district(id="district_north")
    world.add_district(district)

    assert world.get_district("district_north") is district
    assert world.districts["district_north"] is district
    assert world.has_entity("district_north")


def test_registry_key_matches_entity_id() -> None:
    """Registries are keyed by the entity's own id, never anything else."""
    world = build_world()
    world.add_district(build_district(id="district_north"))
    assert list(world.districts) == ["district_north"]


def test_rejects_duplicate_id_within_the_same_entity_type() -> None:
    """Two districts cannot share an identifier."""
    world = build_world()
    world.add_district(build_district(id="district_north"))
    with pytest.raises(ValueError):
        world.add_district(build_district(id="district_north"))


def test_rejects_duplicate_id_across_different_entity_types() -> None:
    """Identifiers are unique world-wide, not merely within one registry.

    A law sharing an id with a district would make get_entity ambiguous and
    would collide the moment the world is serialized into a flat id space.
    """
    world = build_world()
    world.add_district(build_district(id="shared_id"))
    with pytest.raises(ValueError):
        world.add_law(build_law(id="shared_id"))


def test_boundary_cannot_be_added_before_its_districts_exist() -> None:
    """Dependency order is enforced, not merely recommended."""
    world = build_world()
    with pytest.raises(ValueError):
        world.add_boundary(build_boundary())


def test_boundary_rejected_when_only_one_endpoint_exists() -> None:
    """Both endpoints are checked, not just the first."""
    world = build_world()
    world.add_district(build_district(id="district_north"))
    with pytest.raises(ValueError):
        world.add_boundary(build_boundary())


def test_boundary_with_valid_endpoints_succeeds() -> None:
    """A boundary joining two registered districts is accepted."""
    world = build_world()
    world.add_district(build_district(id="district_north"))
    world.add_district(build_district(id="district_east"))
    boundary = build_boundary()
    world.add_boundary(boundary)
    assert world.get_boundary(boundary.id) is boundary


def test_wall_cannot_be_added_before_its_boundary_exists() -> None:
    """A wall must stand on something that exists."""
    world = build_world()
    with pytest.raises(ValueError):
        world.add_wall(build_wall())


def test_infrastructure_cannot_be_added_before_its_boundary_exists() -> None:
    """Infrastructure must attach to a boundary that exists."""
    world = build_world()
    with pytest.raises(ValueError):
        world.add_infrastructure(build_infrastructure())


def test_adding_a_wall_links_the_boundary_back_to_it() -> None:
    """The aggregate maintains the back-reference, so callers never set it by hand."""
    world = build_world()
    world.add_district(build_district(id="district_north"))
    world.add_district(build_district(id="district_east"))
    world.add_boundary(build_boundary())
    world.add_wall(build_wall(id="wall_0001"))
    assert world.get_boundary("boundary_north_east").wall_id == "wall_0001"


def test_boundary_referencing_an_unknown_wall_is_rejected() -> None:
    """A boundary may not claim a wall that does not exist."""
    world = build_world()
    world.add_district(build_district(id="district_north"))
    world.add_district(build_district(id="district_east"))
    with pytest.raises(ValueError):
        world.add_boundary(build_boundary(wall_id="wall_does_not_exist"))


def test_back_reference_mismatch_is_rejected() -> None:
    """A boundary claiming a wall that stands somewhere else is incoherent."""
    world = build_world()
    for name in ("district_north", "district_east", "district_south"):
        world.add_district(build_district(id=name))
    world.add_boundary(build_boundary(id="boundary_a"))
    world.add_wall(build_wall(id="wall_on_a", boundary_id="boundary_a"))

    with pytest.raises(ValueError):
        world.add_boundary(
            build_boundary(
                id="boundary_b",
                district_a_id="district_north",
                district_b_id="district_south",
                wall_id="wall_on_a",
            )
        )


def test_second_wall_on_the_same_boundary_is_rejected() -> None:
    """At most one wall stands on a boundary in the MVP."""
    world = build_linked_world()
    with pytest.raises(ValueError):
        world.add_wall(build_wall(id="wall_0002", boundary_id="boundary_north_east"))


def test_get_entity_finds_every_supported_entity_type() -> None:
    """A single id space covers all five entity kinds."""
    world = build_linked_world()
    expected = {
        "district_north": District,
        "boundary_north_east": Boundary,
        "wall_0001": Wall,
        "infra_transit_ne": Infrastructure,
        "law_movement_sharing": Law,
    }
    for entity_id, entity_type in expected.items():
        assert isinstance(world.get_entity(entity_id), entity_type)


def test_get_entity_raises_for_unknown_id() -> None:
    """Unknown identifiers raise rather than returning None."""
    with pytest.raises(KeyError):
        build_world().get_entity("nope")


def test_typed_getters_raise_consistently_for_unknown_ids() -> None:
    """Every typed getter uses the same unknown-id policy."""
    world = build_world()
    getters = (
        world.get_district,
        world.get_boundary,
        world.get_wall,
        world.get_law,
        world.get_infrastructure,
    )
    for getter in getters:
        with pytest.raises(KeyError):
            getter("nope")


def test_typed_getter_raises_when_the_id_belongs_to_another_kind() -> None:
    """Asking for a district by a wall's id is a miss, not a silent success."""
    world = build_linked_world()
    with pytest.raises(KeyError):
        world.get_district("wall_0001")


def test_has_entity_is_the_non_raising_way_to_ask() -> None:
    """Presence checks have a dedicated method, so absence need not be exceptional."""
    world = build_linked_world()
    assert world.has_entity("wall_0001")
    assert not world.has_entity("nope")


def test_registries_cannot_be_mutated_from_outside() -> None:
    """Every registry is a read-only view, so nothing bypasses add_* validation."""
    world = build_linked_world()
    views = (
        world.districts,
        world.boundaries,
        world.walls,
        world.laws,
        world.infrastructure,
    )
    for view in views:
        with pytest.raises(TypeError):
            view["smuggled"] = None  # type: ignore[index]


def test_registry_attributes_cannot_be_replaced() -> None:
    """Registries are properties over private storage and cannot be swapped out."""
    world = build_world()
    with pytest.raises(AttributeError):
        world.districts = {}  # type: ignore[misc]
    assert not hasattr(world, "__dict__")


def test_registry_views_reflect_newly_added_entities() -> None:
    """The views are live, so a valid addition shows up immediately."""
    world = build_world()
    districts = world.districts
    assert len(districts) == 0
    world.add_district(build_district(id="district_north"))
    assert len(districts) == 1


def test_add_methods_reject_the_wrong_entity_type() -> None:
    """Each registry accepts only its own kind."""
    world = build_world()
    with pytest.raises(TypeError):
        world.add_district(build_law())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        world.add_law(build_district())  # type: ignore[arg-type]


def test_advance_tick_moves_time_forward_by_one() -> None:
    """Time changes only through the deliberate method."""
    world = build_world(tick=5)
    world.advance_tick()
    assert world.tick == 6


def test_tick_cannot_be_set_directly() -> None:
    """A read-only property keeps the tick count equal to ticks actually simulated."""
    world = build_world()
    with pytest.raises(AttributeError):
        world.tick = 100  # type: ignore[misc]


def test_episode_cannot_be_set_directly() -> None:
    """An episode number is fixed for the lifetime of a world in memory."""
    world = build_world()
    with pytest.raises(AttributeError):
        world.episode = 9  # type: ignore[misc]


def test_world_does_not_use_value_equality() -> None:
    """World is an identity-bearing aggregate; two worlds are never interchangeable."""
    assert build_world() != build_world()
    world = build_world()
    assert world == world
