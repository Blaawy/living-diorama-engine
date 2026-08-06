"""Serialization for :class:`Law`, including its scalar values."""

import math

from living_diorama.entities import Law
from living_diorama.entities.law import LawValue
from living_diorama.events.event import JsonValue
from living_diorama.persistence.json_codec import require_document
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_flag,
    require_identifier,
    require_text,
)

_KEYS = frozenset(
    {
        "active",
        "changed_episode",
        "created_tick",
        "current_value",
        "id",
        "name",
        "previous_value",
        "restored_tick",
    }
)
"""Exactly the keys a serialized law carries."""


def require_law_value(value: object, description: str) -> LawValue:
    """Return a law scalar unchanged, preserving its exact Python type.

    A law's value is the thing an episode changes, so its type carries meaning:
    ``True`` and ``1`` are different settings, and so are ``1`` and ``"1"``.
    Type checks are exact, which keeps ``bool`` from being read as an ``int``
    and keeps ``IntEnum`` and ``StrEnum`` members -- which subclass the
    primitives -- from slipping through and loading back as something else.

    Lists and dicts are refused: a law holds one scalar setting, and a
    structured value would mean the domain model has moved on without the save
    format noticing.

    Raises:
        TypeError: If the value is not ``None``, ``bool``, ``int``, ``float``,
            or ``str``.
        ValueError: If a float is not finite.
    """
    if value is None or type(value) is bool or type(value) is int or type(value) is str:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{description} must be finite, got {value!r}")
        return value
    raise TypeError(
        f"{description} must be null, a bool, an int, a finite float, or a str, "
        f"got {type(value).__name__}"
    )


def serialize_law(law: Law) -> dict[str, JsonValue]:
    """Return a law's stored state as a JSON object.

    Raises:
        TypeError: If the argument is not a Law or a field is mistyped.
        ValueError: If a field carries an invalid value.
    """
    if not isinstance(law, Law):
        raise TypeError(f"law must be a Law, got {type(law).__name__}")
    label = require_identifier(law.id, "law id")
    stored_restored_tick = law.restored_tick
    restored: int | None = (
        None
        if stored_restored_tick is None
        else require_exact_int(stored_restored_tick, f"restored_tick of law {label!r}")
    )
    return {
        "active": require_flag(law.active, f"active of law {label!r}"),
        "changed_episode": require_exact_int(
            law.changed_episode, f"changed_episode of law {label!r}"
        ),
        "created_tick": require_exact_int(law.created_tick, f"created_tick of law {label!r}"),
        "current_value": require_law_value(law.current_value, f"current_value of law {label!r}"),
        "id": label,
        "name": require_text(law.name, f"name of law {label!r}"),
        "previous_value": require_law_value(law.previous_value, f"previous_value of law {label!r}"),
        "restored_tick": restored,
    }


def deserialize_law(value: JsonValue, description: str) -> Law:
    """Rebuild a law from a JSON object.

    Raises:
        TypeError: If the value is not a JSON object or a field is mistyped.
        ValueError: If keys are missing or extra, or a field is invalid.
    """
    document = require_document(value, description)
    require_exact_keys(document, _KEYS, description)
    stored_restored_tick = document["restored_tick"]
    restored: int | None = (
        None
        if stored_restored_tick is None
        else require_exact_int(stored_restored_tick, f"{description} restored_tick")
    )
    return Law(
        id=require_identifier(document["id"], f"{description} id"),
        created_tick=require_exact_int(document["created_tick"], f"{description} created_tick"),
        name=require_text(document["name"], f"{description} name"),
        active=require_flag(document["active"], f"{description} active"),
        previous_value=require_law_value(
            document["previous_value"], f"{description} previous_value"
        ),
        current_value=require_law_value(document["current_value"], f"{description} current_value"),
        changed_episode=require_exact_int(
            document["changed_episode"], f"{description} changed_episode"
        ),
        restored_tick=restored,
    )
