"""Tests for the per-entity serializers.

Entities stay mutable after construction, so the constructor that validated one
cannot speak for its state now. A save is a permanent record: every test here
is about refusing to write down corrupt state rather than repairing it.
"""

import math

import pytest

from living_diorama.entities import (
    Boundary,
    InfrastructureType,
    IsolationState,
    ResourcePool,
    ResourceType,
)
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
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
    require_law_value,
    serialize_law,
)
from living_diorama.persistence.serializers.resource_pool_serializer import (
    deserialize_resource_pool,
    serialize_resource_pool,
)
from living_diorama.persistence.serializers.wall_serializer import (
    deserialize_wall,
    serialize_wall,
)
from persistence.conftest import build_district, build_infrastructure, build_law, build_wall

NONCANONICAL_IDS = ["", " ", "  ", "a ", " a", "a\t", "\na"]
"""Identifiers a save must refuse rather than silently strip."""

CORRUPT_UNIT_VALUES = [True, False, "0.5", float("nan"), float("inf"), -0.1, 1.1]
"""Values that are not a normalized score, however plausible they look."""


def round_trip(document: dict) -> dict:
    """Encode and decode a document, proving it survives real save bytes."""
    return loads_canonical(dumps_canonical(document))  # type: ignore[return-value]


# --- ResourcePool -----------------------------------------------------------


def test_every_resource_key_is_written_even_when_empty() -> None:
    """Omitting zero stocks would make the bytes depend on what happened to be full."""
    document = serialize_resource_pool(ResourcePool(stock={}), "resources")
    assert sorted(document) == sorted(resource.value for resource in ResourceType)
    assert all(amount == 0.0 for amount in document.values())


def test_resource_amounts_round_trip() -> None:
    """Stored amounts come back as the same numbers."""
    pool = ResourcePool(stock={ResourceType.FOOD: 5.5, ResourceType.ENERGY: 0.25})
    restored = deserialize_resource_pool(
        round_trip(serialize_resource_pool(pool, "resources")), "resources"
    )
    for resource in ResourceType:
        assert restored.amount_of(resource) == pool.amount_of(resource)


def test_an_unknown_persisted_resource_is_refused() -> None:
    """A resource this build does not know is a schema mismatch, not a detail."""
    document = serialize_resource_pool(ResourcePool(stock={}), "resources")
    document["PLUTONIUM"] = 1.0
    with pytest.raises(ValueError):
        deserialize_resource_pool(document, "resources")


def test_a_missing_persisted_resource_is_refused() -> None:
    """Silently defaulting it to zero would invent state the save never held."""
    document = serialize_resource_pool(ResourcePool(stock={}), "resources")
    del document[ResourceType.FOOD.value]
    with pytest.raises(ValueError):
        deserialize_resource_pool(document, "resources")


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf")])
def test_invalid_persisted_amounts_are_refused(bad: float) -> None:
    """Negative and non-finite stock cannot describe a real quantity."""
    document = serialize_resource_pool(ResourcePool(stock={}), "resources")
    document[ResourceType.FOOD.value] = bad
    with pytest.raises(ValueError):
        deserialize_resource_pool(document, "resources")


@pytest.mark.parametrize("bad", [True, "1.0", None])
def test_mistyped_persisted_amounts_are_refused(bad: object) -> None:
    """``True`` would otherwise read as one unit of food."""
    document = serialize_resource_pool(ResourcePool(stock={}), "resources")
    document[ResourceType.FOOD.value] = bad
    with pytest.raises(TypeError):
        deserialize_resource_pool(document, "resources")


# --- District ---------------------------------------------------------------


def test_a_district_round_trips_every_field() -> None:
    """Each stored value returns unchanged, including the isolation enum."""
    district = build_district(
        "district_a",
        population=120,
        food=5.5,
        materials=2.0,
        energy=0.25,
        production_rate=3.0,
        consumption_rate=1.5,
        scarcity=0.25,
        fear=0.4,
        trust=0.6,
        institutional_pressure=0.8,
        housing_capacity=300,
        isolation_state=IsolationState.PARTIAL,
        created_tick=4,
    )
    restored = deserialize_district(round_trip(serialize_district(district)), "district")

    assert restored.id == district.id
    assert restored.created_tick == 4
    assert restored.population == 120
    assert restored.production_rate == 3.0
    assert restored.consumption_rate == 1.5
    assert restored.scarcity == 0.25
    assert restored.fear == 0.4
    assert restored.trust == 0.6
    assert restored.institutional_pressure == 0.8
    assert restored.housing_capacity == 300
    assert restored.isolation_state is IsolationState.PARTIAL
    assert restored.resources.amount_of(ResourceType.FOOD) == 5.5


@pytest.mark.parametrize("state", list(IsolationState))
def test_every_isolation_state_round_trips(state: IsolationState) -> None:
    """Serialized as its stable value, never as a Python repr or index."""
    district = build_district("district_a", isolation_state=state)
    document = serialize_district(district)
    assert document["isolation_state"] == state.value
    assert deserialize_district(round_trip(document), "district").isolation_state is state


@pytest.mark.parametrize("value", [0.0, 1.0])
def test_unit_interval_boundaries_are_accepted(value: float) -> None:
    """Both ends of the interval are legitimate state."""
    district = build_district("district_a", scarcity=value, fear=value, trust=value)
    restored = deserialize_district(round_trip(serialize_district(district)), "district")
    assert restored.scarcity == value


@pytest.mark.parametrize("field", ["scarcity", "fear", "trust", "institutional_pressure"])
@pytest.mark.parametrize("bad", CORRUPT_UNIT_VALUES)
def test_corrupt_district_scores_are_refused(field: str, bad: object) -> None:
    """A score outside the interval, or of the wrong kind, is never written down."""
    district = build_district("district_a")
    setattr(district, field, bad)
    with pytest.raises((TypeError, ValueError)):
        serialize_district(district)


@pytest.mark.parametrize("field", ["population", "housing_capacity", "created_tick"])
@pytest.mark.parametrize("bad", [True, False, 1.5, "10", -1])
def test_corrupt_district_counts_are_refused(field: str, bad: object) -> None:
    """``bool`` is not a count: ``True`` would persist as a population of one."""
    district = build_district("district_a")
    setattr(district, field, bad)
    with pytest.raises((TypeError, ValueError)):
        serialize_district(district)


@pytest.mark.parametrize("bad", NONCANONICAL_IDS)
def test_noncanonical_district_ids_are_refused(bad: str) -> None:
    """Stripping here would save a different identifier than the world uses."""
    district = build_district("district_a")
    district.id = bad
    with pytest.raises(ValueError):
        serialize_district(district)


def test_an_internal_space_in_an_identifier_is_legal() -> None:
    """Only surrounding whitespace is the problem; ``north gate`` is a fine name."""
    district = build_district("north gate")
    assert serialize_district(district)["id"] == "north gate"


def test_a_corrupt_isolation_state_is_refused() -> None:
    """A plain string looks plausible and is not the enum."""
    district = build_district("district_a")
    district.isolation_state = "OPEN"  # type: ignore[assignment]
    with pytest.raises(TypeError):
        serialize_district(district)


def test_an_unknown_persisted_isolation_state_is_refused() -> None:
    """An unrecognized value means the save knows something this build does not."""
    document = serialize_district(build_district("district_a"))
    document["isolation_state"] = "SEALED"
    with pytest.raises(ValueError):
        deserialize_district(document, "district")


def test_unexpected_and_missing_district_keys_are_refused() -> None:
    """Both directions matter: one is incomplete, the other is unrecognized."""
    document = serialize_district(build_district("district_a"))
    with pytest.raises(ValueError):
        deserialize_district({**document, "surprise": 1}, "district")
    reduced = dict(document)
    del reduced["trust"]
    with pytest.raises(ValueError):
        deserialize_district(reduced, "district")


def test_an_integer_rate_is_persisted_as_a_float() -> None:
    """Real-valued fields load back as floats regardless of how they were stored."""
    district = build_district("district_a")
    district.production_rate = 3
    document = serialize_district(district)
    assert type(document["production_rate"]) is float
    restored = deserialize_district(round_trip(document), "district")
    assert type(restored.production_rate) is float
    assert restored.production_rate == 3.0


# --- Boundary ---------------------------------------------------------------


def test_endpoint_roles_are_preserved_not_normalized() -> None:
    """Which district is A is part of the world's identity, not a detail to sort."""
    boundary = Boundary(
        id="boundary_zx", created_tick=2, district_a_id="zulu", district_b_id="alpha"
    )
    document = serialize_boundary(boundary)
    assert document["district_a_id"] == "zulu"
    assert document["district_b_id"] == "alpha"


def test_a_boundary_round_trips_detached_from_its_wall() -> None:
    """The wall reference comes back separately so the aggregate can rebuild it."""
    boundary = Boundary(
        id="boundary_ab", created_tick=1, district_a_id="a", district_b_id="b", wall_id="w"
    )
    restored, expected_wall = deserialize_boundary(
        round_trip(serialize_boundary(boundary)), "boundary"
    )
    assert restored.id == "boundary_ab"
    assert restored.created_tick == 1
    assert restored.wall_id is None, "the link is rebuilt by World.add_wall"
    assert expected_wall == "w"


def test_a_wall_free_boundary_round_trips_with_a_null_reference() -> None:
    """Absence is recorded explicitly rather than by omitting the key."""
    boundary = Boundary(id="boundary_ab", created_tick=0, district_a_id="a", district_b_id="b")
    document = serialize_boundary(boundary)
    assert document["wall_id"] is None
    _, expected_wall = deserialize_boundary(round_trip(document), "boundary")
    assert expected_wall is None


def test_a_mutated_self_loop_boundary_is_refused() -> None:
    """The constructor forbids it, but ``Boundary`` stays mutable afterwards."""
    boundary = Boundary(id="boundary_ab", created_tick=0, district_a_id="a", district_b_id="b")
    boundary.district_b_id = "a"
    with pytest.raises(ValueError):
        serialize_boundary(boundary)


def test_a_persisted_self_loop_boundary_is_refused() -> None:
    """The same check applies on the way back in."""
    document = serialize_boundary(
        Boundary(id="boundary_ab", created_tick=0, district_a_id="a", district_b_id="b")
    )
    document["district_b_id"] = "a"
    with pytest.raises(ValueError):
        deserialize_boundary(document, "boundary")


@pytest.mark.parametrize("field", ["district_a_id", "district_b_id", "wall_id"])
def test_noncanonical_boundary_references_are_refused(field: str) -> None:
    """A reference carrying whitespace resolves to nothing."""
    boundary = Boundary(
        id="boundary_ab", created_tick=0, district_a_id="a", district_b_id="b", wall_id="w"
    )
    setattr(boundary, field, "x ")
    with pytest.raises(ValueError):
        serialize_boundary(boundary)


# --- Wall -------------------------------------------------------------------


def test_a_wall_round_trips_every_dependency_field() -> None:
    """Accumulated reliance is the whole point of a wall surviving an episode."""
    wall = build_wall(
        "wall_ab",
        "boundary_ab",
        active=False,
        permanent=True,
        integrity=0.75,
        dependency_score=0.55,
        transport_dependency=0.4,
        resource_dependency=1.0,
        created_tick=5,
        built_tick=6,
    )
    restored = deserialize_wall(round_trip(serialize_wall(wall)), "wall")

    assert restored.active is False
    assert restored.permanent is True
    assert restored.integrity == 0.75
    assert restored.dependency_score == 0.55
    assert restored.transport_dependency == 0.4
    assert restored.resource_dependency == 1.0
    assert restored.created_tick == 5
    assert restored.built_tick == 6


def test_an_inactive_permanent_wall_stays_inactive_and_permanent() -> None:
    """Persistence records the wall; it does not reinterpret it."""
    restored = deserialize_wall(
        round_trip(serialize_wall(build_wall("w", "b", active=False, permanent=True))), "wall"
    )
    assert restored.active is False
    assert restored.permanent is True


@pytest.mark.parametrize("field", ["active", "permanent"])
@pytest.mark.parametrize("bad", [0, 1, "true", None])
def test_corrupt_wall_flags_are_refused(field: str, bad: object) -> None:
    """A flag deciding whether a wall stands has to be a flag."""
    wall = build_wall("w", "b", active=True)
    setattr(wall, field, bad)
    with pytest.raises(TypeError):
        serialize_wall(wall)


@pytest.mark.parametrize(
    "field",
    ["dependency_score", "transport_dependency", "resource_dependency", "integrity"],
)
@pytest.mark.parametrize("bad", CORRUPT_UNIT_VALUES)
def test_corrupt_wall_scores_are_refused(field: str, bad: object) -> None:
    """A wall carrying an impossible score is not one to write down."""
    wall = build_wall("w", "b", active=True)
    setattr(wall, field, bad)
    with pytest.raises((TypeError, ValueError)):
        serialize_wall(wall)


def test_a_wall_built_before_it_was_created_is_refused() -> None:
    """Causality is a stored invariant, and it stays mutable."""
    wall = build_wall("w", "b", active=True, created_tick=5, built_tick=6)
    wall.built_tick = 2
    with pytest.raises(ValueError):
        serialize_wall(wall)


# --- Infrastructure ---------------------------------------------------------


@pytest.mark.parametrize("kind", list(InfrastructureType))
def test_every_infrastructure_kind_round_trips(kind: InfrastructureType) -> None:
    """Serialized as its stable value so category routing survives a reload."""
    entity = build_infrastructure("infra", "boundary_ab", kind=kind)
    document = serialize_infrastructure(entity)
    assert document["infrastructure_type"] == kind.value
    assert deserialize_infrastructure(round_trip(document), "infra").infrastructure_type is kind


def test_degraded_and_zero_capacity_infrastructure_round_trips() -> None:
    """Both are ordinary states that a save must carry unchanged."""
    entity = build_infrastructure(
        "infra", "boundary_ab", capacity=0.0, degraded=True, dependency_score=0.6
    )
    restored = deserialize_infrastructure(round_trip(serialize_infrastructure(entity)), "infra")
    assert restored.capacity == 0.0
    assert restored.degraded is True
    assert restored.dependency_score == 0.6


@pytest.mark.parametrize("bad", [0, 1, "false", None])
def test_a_corrupt_degraded_flag_is_refused(bad: object) -> None:
    """Truthiness is not a flag."""
    entity = build_infrastructure("infra", "boundary_ab")
    entity.degraded = bad  # type: ignore[assignment]
    with pytest.raises(TypeError):
        serialize_infrastructure(entity)


@pytest.mark.parametrize("bad", [True, "1.0", float("nan"), float("inf"), -0.1])
def test_corrupt_capacity_is_refused(bad: object) -> None:
    """Capacity must be a finite, non-negative real number."""
    entity = build_infrastructure("infra", "boundary_ab")
    entity.capacity = bad  # type: ignore[assignment]
    with pytest.raises((TypeError, ValueError)):
        serialize_infrastructure(entity)


def test_a_corrupt_infrastructure_type_is_refused() -> None:
    """A string naming the kind is not the kind."""
    entity = build_infrastructure("infra", "boundary_ab")
    entity.infrastructure_type = "TRANSIT_ROUTE"  # type: ignore[assignment]
    with pytest.raises(TypeError):
        serialize_infrastructure(entity)


def test_an_unknown_persisted_infrastructure_type_is_refused() -> None:
    """An unrecognized kind cannot be guessed into a known one."""
    document = serialize_infrastructure(build_infrastructure("infra", "boundary_ab"))
    document["infrastructure_type"] = "TELEPORTER"
    with pytest.raises(ValueError):
        deserialize_infrastructure(document, "infra")


# --- Law --------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, True, False, 0, 1, -7, 2.5, -0.0, "text", "", "1"])
def test_law_scalars_round_trip_with_their_exact_type(value: object) -> None:
    """A law's value type carries meaning: ``True``, ``1``, and ``"1"`` differ."""
    law = build_law("law", previous_value=value, current_value=value)
    restored = deserialize_law(round_trip(serialize_law(law)), "law")

    assert restored.current_value == value
    assert type(restored.current_value) is type(value)
    assert restored.previous_value == value
    assert type(restored.previous_value) is type(value)


def test_true_does_not_become_one_and_one_does_not_become_true() -> None:
    """The conversion that would quietly rewrite what a rule says."""
    boolean = deserialize_law(
        round_trip(serialize_law(build_law("law", current_value=True))), "law"
    )
    integer = deserialize_law(round_trip(serialize_law(build_law("law", current_value=1))), "law")
    assert boolean.current_value is True
    assert type(integer.current_value) is int
    assert integer.current_value is not True


@pytest.mark.parametrize("bad", [[1, 2], {"k": "v"}, (1,), {1, 2}, IsolationState.OPEN, object()])
def test_structured_law_values_are_refused(bad: object) -> None:
    """A law holds one scalar setting; a structure means the model moved on."""
    with pytest.raises(TypeError):
        require_law_value(bad, "current_value")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_law_values_are_refused(bad: float) -> None:
    """A value JSON cannot represent cannot be a persisted setting."""
    with pytest.raises(ValueError):
        require_law_value(bad, "current_value")


def test_a_law_round_trips_every_field() -> None:
    """Including the optional restored tick and the changed episode."""
    law = build_law(
        "tariff",
        name="Tariff",
        active=False,
        previous_value=1,
        current_value=2.5,
        changed_episode=3,
        restored_tick=4,
        created_tick=2,
    )
    restored = deserialize_law(round_trip(serialize_law(law)), "law")

    assert restored.name == "Tariff"
    assert restored.active is False
    assert restored.changed_episode == 3
    assert restored.restored_tick == 4
    assert restored.created_tick == 2


def test_an_absent_restored_tick_stays_absent() -> None:
    """``None`` is a meaningful value here, not a missing one."""
    document = serialize_law(build_law("law", restored_tick=None))
    assert document["restored_tick"] is None
    assert deserialize_law(round_trip(document), "law").restored_tick is None


@pytest.mark.parametrize("bad", ["Tariff ", " Tariff", "", "   "])
def test_a_law_name_carrying_surrounding_whitespace_is_refused(bad: str) -> None:
    """The constructor strips on the way in; a save must not disagree with it."""
    law = build_law("law", name="Tariff")
    law.name = bad
    with pytest.raises(ValueError):
        serialize_law(law)


def test_negative_zero_survives_as_a_law_value() -> None:
    """The sign is part of the stored float."""
    restored = deserialize_law(
        round_trip(serialize_law(build_law("law", current_value=-0.0))), "law"
    )
    assert math.copysign(1.0, restored.current_value) == -1.0  # type: ignore[arg-type]
