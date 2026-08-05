"""The Event value object and the MVP event vocabulary.

An event is a statement about something that happened at a tick. Once
published it is history, so it is immutable all the way down: the payload is
defensively copied and recursively frozen at construction, and no accessor
hands back anything a caller could edit.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from living_diorama.entities import EntityId, Tick

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
"""A value that survives a JSON round trip unchanged.

This is the accepted shape of event payload input. Anything else -- enums,
tuples, sets, dataclasses, entity instances -- is rejected, because an event
that cannot be serialized cannot be part of a persisted history.
"""

type FrozenJsonValue = (
    None | bool | int | float | str | tuple[FrozenJsonValue, ...] | Mapping[str, FrozenJsonValue]
)
"""The frozen counterpart of :data:`JsonValue`, as stored inside an Event.

Lists become tuples and dicts become read-only mappings, so a published payload
offers no mutation path at any depth.
"""

_ALLOWED_NON_FLOAT_SCALARS = (bool, int, str)


class EventType(Enum):
    """The vocabulary of things that can happen in the district-level MVP.

    Deliberately limited to what the district-level slice can actually emit.
    Citizen-level events belong to a later phase and are not declared here in
    advance.

    Values are stable uppercase strings so that later persistence work can
    serialize them by name without an extra mapping table.
    """

    LAW_CHANGED = "LAW_CHANGED"
    LAW_RESTORED = "LAW_RESTORED"
    RESOURCE_PRODUCED = "RESOURCE_PRODUCED"
    RESOURCE_CONSUMED = "RESOURCE_CONSUMED"
    RESOURCE_TRANSFERRED = "RESOURCE_TRANSFERRED"
    POPULATION_MIGRATED = "POPULATION_MIGRATED"
    SCARCITY_CHANGED = "SCARCITY_CHANGED"
    SOCIAL_STABILITY_CHANGED = "SOCIAL_STABILITY_CHANGED"
    INSTITUTIONAL_PRESSURE_CHANGED = "INSTITUTIONAL_PRESSURE_CHANGED"
    WALL_BUILT = "WALL_BUILT"
    WALL_CHANGED = "WALL_CHANGED"
    INFRASTRUCTURE_ADAPTED = "INFRASTRUCTURE_ADAPTED"


def _freeze_value(value: object, path: str) -> FrozenJsonValue:
    """Validate one payload value and return an immutable equivalent.

    Validation and freezing happen in one traversal so that a payload can never
    be partially checked. Type checks are exact rather than ``isinstance``
    based, which is what keeps ``IntEnum`` and ``StrEnum`` members out: they
    subclass ``int`` and ``str`` and would otherwise pass unnoticed, then
    serialize into something that no longer round-trips.

    Two exception types are used, and the split is deliberate: ``TypeError``
    means the value is of a kind a payload may never contain, while
    ``ValueError`` means the kind is fine but this particular value is not
    representable. A non-finite float is the second case -- ``float`` is a
    permitted payload type, but NaN and the infinities are not valid JSON
    numbers.

    Args:
        value: The value to validate.
        path: Dotted location of this value, used in error messages.

    Returns:
        The value itself for scalars, a tuple for lists, or a read-only mapping
        for dicts.

    Raises:
        TypeError: If the value, or anything nested inside it, is of a type that
            is not JSON-compatible, or if a nested mapping has a non-string key.
        ValueError: If a float anywhere in the structure is not finite.
    """
    if value is None or type(value) in _ALLOWED_NON_FLOAT_SCALARS:
        return value  # type: ignore[return-value]
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"payload value at {path} must be a finite number, got {value!r}")
        return value
    if type(value) is list:
        return tuple(_freeze_value(item, f"{path}[{index}]") for index, item in enumerate(value))
    if type(value) is dict:
        frozen: dict[str, FrozenJsonValue] = {}
        for key, nested in value.items():
            if type(key) is not str:
                raise TypeError(f"payload keys must be strings, got {type(key).__name__} at {path}")
            frozen[key] = _freeze_value(nested, f"{path}.{key}")
        return MappingProxyType(frozen)
    raise TypeError(f"payload value at {path} is not JSON-compatible: {type(value).__name__}")


def _thaw_value(value: FrozenJsonValue) -> JsonValue:
    """Return a mutable, JSON-compatible copy of a frozen payload value.

    Args:
        value: A frozen value stored inside an event.

    Returns:
        The same data with tuples restored to lists and read-only mappings
        restored to dicts, detached from the event.
    """
    if isinstance(value, tuple):
        return [_thaw_value(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _thaw_value(nested) for key, nested in value.items()}
    return value


@dataclass(frozen=True, slots=True)
class Event:
    """One immutable statement about something that happened at a tick.

    Events compare by value, so two events describing the same occurrence are
    equal regardless of which system constructed them.

    The payload is copied and recursively frozen during construction, which
    means a caller cannot alter published history by holding on to the dict it
    passed in, and cannot reach into ``event.payload`` to edit it afterwards.
    Use :meth:`payload_as_dict` when a mutable JSON-compatible copy is needed.

    Every float in the payload is required to be finite, so a published event
    is always serializable under strict JSON rules
    (``json.dumps(..., allow_nan=False)``).

    Note:
        Events are not hashable, because the frozen payload mapping is not.
        They are held in lists and compared by value; nothing needs to key on
        them.

    Attributes:
        tick: When this happened. Never negative.
        type: What kind of occurrence this is.
        payload: Read-only, recursively frozen detail about the occurrence.
        source_id: Identifier of the entity this concerns, if any. Stored
            stripped of surrounding whitespace.
    """

    tick: Tick
    type: EventType
    payload: Mapping[str, FrozenJsonValue]
    source_id: EntityId | None = None

    def __post_init__(self) -> None:
        """Validate the event and replace its payload with a frozen copy.

        Type checks run before value checks, so a caller never sees a value
        complaint about something that was the wrong kind of thing to begin
        with. ``tick`` is checked for exact ``int`` type because ``bool`` is an
        ``int`` subclass, and ``Event(tick=True, ...)`` is far more likely to be
        an argument-order mistake than an intent to record tick 1.

        Raises:
            TypeError: If ``tick`` is not an int, ``type`` is not an
                :class:`EventType`, ``source_id`` is neither None nor a str, the
                payload is not a mapping, or the payload contains a non-string
                key or a value of a non-JSON-compatible type.
            ValueError: If ``tick`` is negative, ``source_id`` is blank, or any
                float in the payload is not finite.
        """
        if type(self.tick) is not int:
            raise TypeError(f"tick must be an int, got {type(self.tick).__name__}")
        if self.tick < 0:
            raise ValueError(f"tick must be >= 0, got {self.tick}")

        if not isinstance(self.type, EventType):
            raise TypeError(f"type must be an EventType, got {type(self.type).__name__}")

        if self.source_id is not None:
            if not isinstance(self.source_id, str):
                raise TypeError(
                    f"source_id must be None or a str, got {type(self.source_id).__name__}"
                )
            stripped = self.source_id.strip()
            if not stripped:
                raise ValueError("source_id must be None or a non-empty string")
            object.__setattr__(self, "source_id", stripped)

        if not isinstance(self.payload, Mapping):
            raise TypeError(f"payload must be a mapping, got {type(self.payload).__name__}")

        frozen = _freeze_value(dict(self.payload), "payload")
        object.__setattr__(self, "payload", frozen)

    def payload_as_dict(self) -> dict[str, JsonValue]:
        """Return an independent, mutable, JSON-compatible copy of the payload.

        Returns:
            A new dict with tuples restored to lists. Mutating it cannot affect
            this event, which is why this is the only accessor that hands out
            mutable data.
        """
        return {key: _thaw_value(value) for key, value in self.payload.items()}
