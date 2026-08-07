"""Serialization for :class:`District`."""

from living_diorama.entities import District, IsolationState
from living_diorama.events.event import JsonValue
from living_diorama.persistence.json_codec import require_document
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_identifier,
    require_non_negative_real,
    require_unit_interval,
)
from living_diorama.persistence.serializers._runtime_types import is_runtime_instance
from living_diorama.persistence.serializers.resource_pool_serializer import (
    deserialize_resource_pool,
    serialize_resource_pool,
)

_KEYS = frozenset(
    {
        "consumption_rate",
        "created_tick",
        "fear",
        "housing_capacity",
        "id",
        "institutional_pressure",
        "isolation_state",
        "population",
        "production_rate",
        "resources",
        "scarcity",
        "trust",
    }
)
"""Exactly the keys a serialized district carries."""


def _isolation_state(value: JsonValue, description: str) -> IsolationState:
    """Return the isolation state named by a stable enum value.

    Raises:
        TypeError: If the value is not a ``str``.
        ValueError: If it names no known isolation state.
    """
    if type(value) is not str:
        raise TypeError(f"{description} must be a str, got {type(value).__name__}")
    try:
        return IsolationState(value)
    except ValueError as error:
        known = sorted(state.value for state in IsolationState)
        raise ValueError(f"{description} must be one of {known}, got {value!r}") from error


def serialize_district(district: District) -> dict[str, JsonValue]:
    """Return a district's stored state as a JSON object.

    Every value is validated exactly as stored rather than coerced. Writing a
    repaired copy of corrupt state would make the save disagree with the world
    it claims to record.

    Raises:
        TypeError: If the argument is not a District or a field is mistyped.
        ValueError: If a field carries an invalid value.
    """
    if not is_runtime_instance(district, District):
        raise TypeError(f"district must be a District, got {type(district).__name__}")
    label = require_identifier(district.id, "district id")
    if not is_runtime_instance(district.isolation_state, IsolationState):
        raise TypeError(
            f"isolation_state of district {label!r} must be an IsolationState, "
            f"got {type(district.isolation_state).__name__}"
        )
    return {
        "consumption_rate": require_non_negative_real(
            district.consumption_rate, f"consumption_rate of district {label!r}"
        ),
        "created_tick": require_exact_int(
            district.created_tick, f"created_tick of district {label!r}"
        ),
        "fear": require_unit_interval(district.fear, f"fear of district {label!r}"),
        "housing_capacity": require_exact_int(
            district.housing_capacity, f"housing_capacity of district {label!r}"
        ),
        "id": label,
        "institutional_pressure": require_unit_interval(
            district.institutional_pressure, f"institutional_pressure of district {label!r}"
        ),
        "isolation_state": district.isolation_state.value,
        "population": require_exact_int(district.population, f"population of district {label!r}"),
        "production_rate": require_non_negative_real(
            district.production_rate, f"production_rate of district {label!r}"
        ),
        "resources": serialize_resource_pool(
            district.resources, f"resources of district {label!r}"
        ),
        "scarcity": require_unit_interval(district.scarcity, f"scarcity of district {label!r}"),
        "trust": require_unit_interval(district.trust, f"trust of district {label!r}"),
    }


def deserialize_district(value: JsonValue, description: str) -> District:
    """Rebuild a district from a JSON object.

    Raises:
        TypeError: If the value is not a JSON object or a field is mistyped.
        ValueError: If keys are missing or extra, or a field is invalid.
    """
    document = require_document(value, description)
    require_exact_keys(document, _KEYS, description)
    label = require_identifier(document["id"], f"{description} id")
    return District(
        id=label,
        created_tick=require_exact_int(document["created_tick"], f"{description} created_tick"),
        population=require_exact_int(document["population"], f"{description} population"),
        resources=deserialize_resource_pool(document["resources"], f"{description} resources"),
        production_rate=require_non_negative_real(
            document["production_rate"], f"{description} production_rate"
        ),
        consumption_rate=require_non_negative_real(
            document["consumption_rate"], f"{description} consumption_rate"
        ),
        scarcity=require_unit_interval(document["scarcity"], f"{description} scarcity"),
        fear=require_unit_interval(document["fear"], f"{description} fear"),
        trust=require_unit_interval(document["trust"], f"{description} trust"),
        institutional_pressure=require_unit_interval(
            document["institutional_pressure"], f"{description} institutional_pressure"
        ),
        housing_capacity=require_exact_int(
            document["housing_capacity"], f"{description} housing_capacity"
        ),
        isolation_state=_isolation_state(
            document["isolation_state"], f"{description} isolation_state"
        ),
    )
