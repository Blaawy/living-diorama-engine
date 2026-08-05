"""Tests for the Event value object and its payload immutability guarantees.

A published event is history. These tests pin down that it cannot be edited
afterwards through any route: not through the dict the caller passed in, not
through the event's own payload attribute, and not at any nesting depth.
"""

import json
import math
from dataclasses import FrozenInstanceError
from enum import Enum, IntEnum

import pytest

from living_diorama.events import Event, EventType


class _Colour(Enum):
    RED = "RED"


class _Level(IntEnum):
    HIGH = 3


def test_constructs_with_valid_values() -> None:
    """A well-formed event keeps the tick, type, payload, and source given."""
    event = Event(
        tick=42,
        type=EventType.WALL_BUILT,
        payload={"boundary_id": "boundary_north_east"},
        source_id="wall_0001",
    )
    assert event.tick == 42
    assert event.type is EventType.WALL_BUILT
    assert event.payload["boundary_id"] == "boundary_north_east"
    assert event.source_id == "wall_0001"


def test_source_id_is_optional() -> None:
    """Not every event concerns a specific entity."""
    assert Event(tick=0, type=EventType.LAW_CHANGED, payload={}).source_id is None


def test_rejects_negative_tick() -> None:
    """Nothing can happen before the world begins."""
    with pytest.raises(ValueError):
        Event(tick=-1, type=EventType.LAW_CHANGED, payload={})


def test_rejects_blank_source_id() -> None:
    """A source identifier must either be absent or actually identify something."""
    with pytest.raises(ValueError):
        Event(tick=0, type=EventType.LAW_CHANGED, payload={}, source_id="")
    with pytest.raises(ValueError):
        Event(tick=0, type=EventType.LAW_CHANGED, payload={}, source_id="   ")


def test_strips_source_id() -> None:
    """Identifiers are normalized so later lookups and queries match."""
    event = Event(tick=0, type=EventType.LAW_CHANGED, payload={}, source_id="  law_1  ")
    assert event.source_id == "law_1"


def test_rejects_non_string_payload_keys() -> None:
    """JSON object keys are strings, so payload keys must be too."""
    with pytest.raises(TypeError):
        Event(tick=0, type=EventType.LAW_CHANGED, payload={1: "value"})  # type: ignore[dict-item]


def test_rejects_nested_non_string_payload_keys() -> None:
    """Key validation applies at every depth, not just the top level."""
    with pytest.raises(TypeError):
        Event(tick=0, type=EventType.LAW_CHANGED, payload={"outer": {2: "value"}})


def test_rejects_unsupported_payload_values() -> None:
    """Anything that would not survive a JSON round trip is refused."""
    for bad in ({1, 2}, (1, 2), object(), _Colour.RED):
        with pytest.raises(TypeError):
            Event(tick=0, type=EventType.LAW_CHANGED, payload={"x": bad})


def test_rejects_int_and_str_enum_subclasses() -> None:
    """IntEnum and StrEnum subclass int and str, so exact type checks are required.

    An isinstance-based check would let these through, and they would serialize
    into something that no longer round-trips back to the same value.
    """
    with pytest.raises(TypeError):
        Event(tick=0, type=EventType.LAW_CHANGED, payload={"x": _Level.HIGH})


def test_rejects_unsupported_values_nested_deeply() -> None:
    """Validation recurses, so a bad value cannot hide inside a list or dict."""
    with pytest.raises(TypeError):
        Event(tick=0, type=EventType.LAW_CHANGED, payload={"a": [1, {"b": {1, 2}}]})


def test_accepts_all_json_scalar_types_and_nesting() -> None:
    """The permitted payload shape covers what MVP events actually need."""
    event = Event(
        tick=0,
        type=EventType.SCARCITY_CHANGED,
        payload={
            "none": None,
            "bool": True,
            "int": 3,
            "float": 0.5,
            "str": "text",
            "list": [1, "two", None],
            "dict": {"nested": {"deep": [1.5]}},
        },
    )
    assert event.payload["int"] == 3
    assert event.payload_as_dict()["dict"] == {"nested": {"deep": [1.5]}}


def test_caller_cannot_mutate_payload_after_construction() -> None:
    """The event copies its payload, so the caller's dict is no longer connected."""
    source: dict[str, object] = {"count": 1, "items": [1, 2]}
    event = Event(
        tick=0,
        type=EventType.RESOURCE_PRODUCED,
        payload=source,  # type: ignore[arg-type]
    )

    source["count"] = 999
    assert isinstance(source["items"], list)
    source["items"].append(3)

    assert event.payload["count"] == 1
    assert event.payload["items"] == (1, 2)


def test_direct_mutation_of_payload_fails() -> None:
    """The published payload offers no mutation path at the top level."""
    event = Event(tick=0, type=EventType.LAW_CHANGED, payload={"a": 1})
    with pytest.raises(TypeError):
        event.payload["a"] = 2  # type: ignore[index]


def test_direct_mutation_of_nested_payload_fails() -> None:
    """Freezing is recursive, so nested structures are sealed too."""
    event = Event(tick=0, type=EventType.LAW_CHANGED, payload={"outer": {"inner": 1}})
    nested = event.payload["outer"]
    with pytest.raises(TypeError):
        nested["inner"] = 2  # type: ignore[index]


def test_nested_lists_become_immutable_sequences() -> None:
    """Lists are stored as tuples, so no append can rewrite recorded history."""
    event = Event(tick=0, type=EventType.LAW_CHANGED, payload={"items": [1, 2]})
    assert event.payload["items"] == (1, 2)
    assert not hasattr(event.payload["items"], "append")


def test_payload_as_dict_returns_an_independent_mutable_copy() -> None:
    """The sanctioned escape hatch hands out detached, JSON-shaped data."""
    event = Event(tick=0, type=EventType.LAW_CHANGED, payload={"a": {"b": [1]}})
    copy = event.payload_as_dict()

    assert copy == {"a": {"b": [1]}}
    assert isinstance(copy["a"], dict)

    copy["a"]["b"].append(2)  # type: ignore[index,union-attr]
    copy["new"] = True
    assert event.payload_as_dict() == {"a": {"b": [1]}}


def test_event_fields_cannot_be_rebound() -> None:
    """Events are frozen: history is replaced by new events, never edited."""
    event = Event(tick=0, type=EventType.LAW_CHANGED, payload={})
    with pytest.raises(FrozenInstanceError):
        event.tick = 5  # type: ignore[misc]


def test_equality_is_value_based() -> None:
    """Two events describing the same occurrence are equal, whoever built them."""
    first = Event(tick=1, type=EventType.WALL_BUILT, payload={"a": [1]}, source_id="w1")
    second = Event(tick=1, type=EventType.WALL_BUILT, payload={"a": [1]}, source_id="w1")
    assert first == second


def test_events_differing_in_any_field_are_not_equal() -> None:
    """Every field participates in identity, including the payload."""
    base = Event(tick=1, type=EventType.WALL_BUILT, payload={"a": 1}, source_id="w1")
    assert base != Event(tick=2, type=EventType.WALL_BUILT, payload={"a": 1}, source_id="w1")
    assert base != Event(tick=1, type=EventType.WALL_CHANGED, payload={"a": 1}, source_id="w1")
    assert base != Event(tick=1, type=EventType.WALL_BUILT, payload={"a": 2}, source_id="w1")
    assert base != Event(tick=1, type=EventType.WALL_BUILT, payload={"a": 1}, source_id="w2")


def test_every_mvp_event_type_is_constructible() -> None:
    """The declared vocabulary must be usable, not aspirational."""
    for event_type in EventType:
        assert Event(tick=0, type=event_type, payload={}).type is event_type


def test_rejects_non_finite_floats_at_the_top_level() -> None:
    """NaN and the infinities are not valid JSON numbers, so they never enter a payload."""
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            Event(tick=0, type=EventType.LAW_CHANGED, payload={"value": bad})


def test_rejects_non_finite_floats_nested_in_a_dict() -> None:
    """The finiteness check recurses into nested mappings."""
    with pytest.raises(ValueError):
        Event(
            tick=0,
            type=EventType.SCARCITY_CHANGED,
            payload={"nested": {"value": float("-inf")}},
        )


def test_rejects_non_finite_floats_nested_in_a_list() -> None:
    """The finiteness check recurses into nested sequences."""
    with pytest.raises(ValueError):
        Event(
            tick=0,
            type=EventType.RESOURCE_PRODUCED,
            payload={"items": [1.0, float("nan")]},
        )


def test_rejects_non_finite_floats_nested_deeply() -> None:
    """No nesting depth hides a value that would break strict serialization."""
    with pytest.raises(ValueError):
        Event(
            tick=0,
            type=EventType.LAW_CHANGED,
            payload={"a": [{"b": [{"c": float("inf")}]}]},
        )


def test_non_finite_floats_fail_at_construction_not_at_serialization() -> None:
    """The event must never exist in the first place, rather than fail later at save time.

    Catching this only during serialization would mean an episode could run to
    completion and then fail while writing its save file, with the offending
    event already dispatched to every handler.
    """
    with pytest.raises(ValueError):
        Event(tick=0, type=EventType.LAW_CHANGED, payload={"value": float("nan")})


def test_finite_floats_are_accepted_including_extremes() -> None:
    """Ordinary floats, including very large and very small ones, still work."""
    values = [0.0, -0.0, 1.5, -2.75, 1e308, -1e308, 5e-324]
    event = Event(tick=0, type=EventType.LAW_CHANGED, payload={"items": values})
    assert event.payload["items"] == tuple(values)
    assert all(math.isfinite(value) for value in values)


def test_payload_is_serializable_under_strict_json_rules() -> None:
    """A constructed event is guaranteed to survive strict, RFC-compliant serialization."""
    event = Event(
        tick=7,
        type=EventType.INFRASTRUCTURE_ADAPTED,
        payload={
            "none": None,
            "bool": False,
            "int": 12,
            "float": 0.125,
            "str": "text",
            "list": [1, 2.5, "three", None],
            "dict": {"nested": {"deep": [1.5, {"deeper": 2.0}]}},
        },
        source_id="infra_transit_ne",
    )
    encoded = json.dumps(event.payload_as_dict(), allow_nan=False)
    assert json.loads(encoded) == event.payload_as_dict()


def test_rejects_bool_as_tick() -> None:
    """Bool subclasses int, so True would silently mean tick 1 without an exact check."""
    with pytest.raises(TypeError):
        Event(tick=True, type=EventType.LAW_CHANGED, payload={})  # type: ignore[arg-type]


def test_rejects_non_int_tick() -> None:
    """A tick is a discrete step; floats and strings are argument mistakes."""
    for bad in (1.0, "0", None):
        with pytest.raises(TypeError):
            Event(tick=bad, type=EventType.LAW_CHANGED, payload={})  # type: ignore[arg-type]


def test_rejects_non_event_type() -> None:
    """The event vocabulary is closed; a bare string is not a member of it."""
    with pytest.raises(TypeError):
        Event(tick=0, type="LAW_CHANGED", payload={})  # type: ignore[arg-type]


def test_rejects_non_string_source_id() -> None:
    """source_id is checked for type before strip() is reached."""
    with pytest.raises(TypeError):
        Event(
            tick=0,
            type=EventType.LAW_CHANGED,
            payload={},
            source_id=123,  # type: ignore[arg-type]
        )


def test_rejects_non_mapping_payload() -> None:
    """A payload is a JSON object, not a list or a scalar."""
    for bad in ([], "text", 5):
        with pytest.raises(TypeError):
            Event(tick=0, type=EventType.LAW_CHANGED, payload=bad)  # type: ignore[arg-type]
