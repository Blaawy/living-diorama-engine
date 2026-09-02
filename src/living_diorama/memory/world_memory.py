"""Durable facts and the cumulative memory that carries them across episodes.

A :class:`MemoryFact` is the smallest thing the world remembers permanently. It
is not a summary of an event; it is a claim about something that happened,
carrying its own provenance back to the exact event that produced it and to the
verified state that made it significant.

Everything here is deliberately mechanical. Identifiers and summaries are
derived from the fact's own content by fixed rules, so two runs that agree on
what happened agree byte-for-byte on how it is recorded, and nothing about the
wording can drift between builds.
"""

import hashlib
import json
import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Final, cast

try:  # typing.TypeIs exists only on Python >= 3.13
    from typing import TypeIs
except ImportError:  # Python 3.12: typing_extensions provides it
    from typing_extensions import TypeIs  # noqa: UP035 -- intentional 3.12 fallback

from living_diorama.entities import EntityId
from living_diorama.events import EventType
from living_diorama.events.event import FrozenJsonValue, JsonValue

FACT_ID_PREFIX: Final = "fact_"
"""Prefix distinguishing a fact identifier from an entity identifier."""


class MemoryFactType(Enum):
    """The kinds of thing the world remembers permanently.

    Deliberately tiny. A durable fact is a claim the engine will still be
    repeating many episodes later, so a type earns its place only when the
    state that backs it can be verified exactly at the moment the fact is made.
    Everything else stays in the episode's event log, where it is still
    recoverable but is not asserted as lasting history.
    """

    WALL_BUILT = "WALL_BUILT"
    LAW_RESTORED_WALL_PERSISTED = "LAW_RESTORED_WALL_PERSISTED"


_SOURCE_EVENT_TYPES: Final[Mapping[MemoryFactType, EventType]] = MappingProxyType(
    {
        MemoryFactType.WALL_BUILT: EventType.WALL_BUILT,
        MemoryFactType.LAW_RESTORED_WALL_PERSISTED: EventType.LAW_RESTORED,
    }
)
"""The one event type each fact type may be derived from."""

_DETAILS_KEYS: Final[Mapping[MemoryFactType, frozenset[str]]] = MappingProxyType(
    {
        MemoryFactType.WALL_BUILT: frozenset(
            {
                "boundary_id",
                "built_tick",
                "district_a_id",
                "district_b_id",
                "permanent",
                "source_event_payload",
                "wall_id",
            }
        ),
        MemoryFactType.LAW_RESTORED_WALL_PERSISTED: frozenset(
            {
                "boundary_id",
                "law_current_value",
                "law_id",
                "law_name",
                "law_previous_value",
                "restored_tick",
                "source_event_payload",
                "wall_active_at_episode_close",
                "wall_built_tick",
                "wall_dependency_score_at_episode_close",
                "wall_id",
                "wall_permanent",
                "wall_resource_dependency_at_episode_close",
                "wall_transport_dependency_at_episode_close",
            }
        ),
    }
)
"""Exactly the detail keys each fact type carries -- no more, no fewer."""

_SUBJECT_KEYS: Final[Mapping[MemoryFactType, tuple[str, ...]]] = MappingProxyType(
    {
        MemoryFactType.WALL_BUILT: (
            "boundary_id",
            "district_a_id",
            "district_b_id",
            "wall_id",
        ),
        MemoryFactType.LAW_RESTORED_WALL_PERSISTED: ("boundary_id", "law_id", "wall_id"),
    }
)
"""Which details a fact's subject identifiers are drawn from.

Subjects are sorted so that a query for an entity finds every fact touching it
regardless of the role it played. The roles themselves stay in ``details``,
where sorting cannot scramble which district was A and which was B.
"""

_FACT_DOCUMENT_KEYS: Final = frozenset(
    {
        "details",
        "episode",
        "fact_id",
        "fact_type",
        "source_event_index",
        "source_event_type",
        "source_id",
        "subject_ids",
        "summary",
        "tick",
    }
)
"""Exactly the keys a persisted fact document carries."""


def require_exact_int(value: object, description: str) -> int:
    """Return the value if it is an exact non-negative ``int``, else raise.

    ``bool`` is refused because it subclasses ``int``: a ``True`` episode would
    otherwise become episode 1, and nothing downstream could tell.

    Raises:
        TypeError: If the value is not an exact ``int``.
        ValueError: If it is negative.
    """
    if type(value) is not int:
        raise TypeError(f"{description} must be an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{description} must be >= 0, got {value}")
    return value


def require_exact_str(value: object, description: str) -> str:
    """Return the value if it is exactly a ``str``, else raise.

    Deliberately separate from :func:`require_identifier`: a summary is prose,
    not a name, so blank and whitespace rules do not apply to it. What does apply
    is exactness -- a ``str`` subclass compares equal to a plain string, so a
    comparison alone would accept one and the value would come back as something
    other than what a save may hold.

    Raises:
        TypeError: If the value is not exactly a ``str``.
    """
    if type(value) is not str:
        raise TypeError(f"{description} must be a str, got {type(value).__name__}")
    return value


def require_identifier(value: object, description: str) -> EntityId:
    """Return the value if it is a canonical identifier, else raise.

    Entities stay mutable, and their constructors silently strip surrounding
    whitespace, so a registry can hold ``"gate "`` as both its key and its id.
    Stripping here would record a different identifier than the world uses, so a
    noncanonical one is refused. Internal whitespace is fine.

    Raises:
        TypeError: If the value is not exactly a ``str``.
        ValueError: If it is empty, whitespace-only, or carries surrounding
            whitespace.
    """
    if type(value) is not str:
        raise TypeError(f"{description} must be a str, got {type(value).__name__}")
    if not value:
        raise ValueError(f"{description} must not be empty")
    if not value.strip():
        raise ValueError(f"{description} must not be only whitespace, got {value!r}")
    if value.strip() != value:
        raise ValueError(f"{description} must not carry surrounding whitespace, got {value!r}")
    return value


def require_flag(value: object, description: str) -> bool:
    """Return the value if it is exactly a ``bool``, else raise.

    Raises:
        TypeError: If the value is not exactly a ``bool``.
    """
    if type(value) is not bool:
        raise TypeError(f"{description} must be a bool, got {type(value).__name__}")
    return value


def require_unit_interval(value: object, description: str) -> float:
    """Return a finite real number inside 0.0-1.0, else raise.

    Raises:
        TypeError: If the value is not a real number, or is a ``bool``.
        ValueError: If it is not finite or falls outside 0.0-1.0.
    """
    # ``type(...)`` alone decides. It reads the true runtime type without
    # consulting ``__class__``, which a hostile object can override to raise or
    # to lie; ``isinstance`` would hand control to that override before the
    # value was validated. Exactness also refuses bools and number subclasses.
    # The cast is sound because the check has already proven the type is
    # exactly ``int`` or ``float``.
    value_type = type(value)
    if value_type is not int and value_type is not float:
        raise TypeError(f"{description} must be a real number, got {value_type.__name__}")
    number = float(cast(int | float, value))
    if not math.isfinite(number):
        raise ValueError(f"{description} must be finite, got {value!r}")
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{description} must be within 0.0-1.0, got {number}")
    return number


def require_law_value(value: object, description: str) -> JsonValue:
    """Return a law scalar unchanged, preserving its exact Python type.

    A law's value is what an episode changes, so its type carries meaning:
    ``True``, ``1``, and ``"1"`` are three different settings. Exact checks keep
    ``IntEnum`` and ``StrEnum`` members -- which subclass the primitives -- from
    slipping through and coming back as something else.

    Raises:
        TypeError: If the value is not ``None``, ``bool``, ``int``, ``float``,
            or ``str``.
        ValueError: If a float is not finite.
    """
    # ``type(...)`` alone decides, before any ``isinstance`` could consult a
    # caller-controlled ``__class__``. Exactness keeps IntEnum and StrEnum
    # members -- which subclass the primitives -- from slipping through and
    # coming back as something else. The casts are sound because each exact
    # check has already proven the type.
    if value is None:
        return None
    value_type = type(value)
    if value_type is bool:
        return cast(bool, value)
    if value_type is int:
        return cast(int, value)
    if value_type is str:
        return cast(str, value)
    if value_type is float:
        number = cast(float, value)
        if not math.isfinite(number):
            raise ValueError(f"{description} must be finite, got {number!r}")
        return number
    raise TypeError(
        f"{description} must be null, a bool, an int, a finite float, or a str, "
        f"got {value_type.__name__}"
    )


def _freeze(value: object, description: str) -> FrozenJsonValue:
    """Return a deeply immutable, strictly JSON-compatible copy of a value.

    Lists become tuples and mappings become read-only, so a fact offers no
    mutation path at any depth and a caller cannot reach back through a retained
    reference to change what was recorded.

    Type checks are exact. A tuple is refused on input even though one is used
    internally: accepting it would mean a caller could hand in something that is
    not a JSON list and have it silently recorded as one.

    Raises:
        TypeError: If the value, or anything nested, is of a type a fact may not
            carry, or a mapping key is not a ``str``.
        ValueError: If a float is not finite.
    """
    # ``type(...)`` alone decides, before any ``isinstance`` could consult a
    # caller-controlled ``__class__``. Exactness keeps IntEnum and StrEnum
    # members -- and every other primitive or container subclass -- from
    # slipping through, and a tuple stays refused on input. The casts are
    # sound because each exact check has already proven the type.
    if value is None:
        return None
    value_type = type(value)
    if value_type is bool:
        return cast(bool, value)
    if value_type is int:
        return cast(int, value)
    if value_type is str:
        return cast(str, value)
    if value_type is float:
        number = cast(float, value)
        if not math.isfinite(number):
            raise ValueError(f"{description} must be a finite number, got {number!r}")
        return number
    if value_type is list:
        items = cast(list[object], value)
        return tuple(_freeze(item, f"{description}[{index}]") for index, item in enumerate(items))
    if value_type is dict:
        document = cast(dict[object, object], value)
        frozen: dict[str, FrozenJsonValue] = {}
        for key, item in document.items():
            if type(key) is not str:
                raise TypeError(
                    f"{description} has a non-string key {key!r} of type "
                    f"{type(key).__name__}; JSON object keys must be strings"
                )
            frozen[key] = _freeze(item, f"{description}[{key!r}]")
        return MappingProxyType(frozen)
    raise TypeError(f"{description} must be JSON-compatible, got {value_type.__name__}")


def _is_runtime_instance[ExpectedT](value: object, expected: type[ExpectedT]) -> TypeIs[ExpectedT]:
    """Report whether the value's true runtime type is an ``expected`` subclass.

    The safe replacement for ``isinstance`` on caller-owned input: when its
    fast path fails, ``isinstance`` may consult the instance's ``__class__``
    attribute, handing control to the very object being validated -- and a
    hostile override could then replace the documented refusal with its own
    exception. ``issubclass`` on ``type(value)`` answers the same question,
    legitimate subclasses included, without executing anything the caller
    owns. ``expected`` must be a concrete class; the abstract ``Mapping``
    boundary goes through :func:`_has_mapping_type` instead.
    """
    return issubclass(type(value), expected)


def _has_mapping_type(value: object) -> bool:
    """Report whether the value's true runtime type is a ``Mapping`` subclass.

    The same safe runtime-type check as :func:`_is_runtime_instance`, for the
    one accepted type that is abstract. Legitimate ``Mapping`` subclasses,
    including ABC registrations, still qualify -- ``issubclass`` asks the ABC
    about the true type, never the instance.
    """
    return issubclass(type(value), Mapping)


def _is_frozen_mapping(value: FrozenJsonValue) -> TypeIs[Mapping[str, FrozenJsonValue]]:
    """Report whether a frozen value is its mapping member, decided safely.

    The same runtime check as :func:`_has_mapping_type`, typed precisely for
    values already known to be frozen JSON.
    """
    return issubclass(type(value), Mapping)


def _thaw(value: FrozenJsonValue) -> JsonValue:
    """Return an independent, mutable JSON copy of a frozen value.

    A value reaching here may have been exposed by a caller-owned object, so
    its kind is decided from its true runtime type, never through the value
    itself.
    """
    if _is_frozen_mapping(value):
        return {key: _thaw(item) for key, item in value.items()}
    if _is_runtime_instance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _compact_json(document: JsonValue) -> bytes:
    """Encode a document the one way fact identity is defined over.

    Deliberately implemented here rather than borrowed from the persistence
    codec. A fact's identity must not depend on a layer the memory package is
    forbidden to import, and it must not shift if the save format ever changes
    its framing.
    """
    return json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _quote(identifier: str) -> str:
    """Return an identifier quoted for inclusion in a summary sentence."""
    return json.dumps(identifier, ensure_ascii=False, allow_nan=False)


@dataclass(frozen=True, slots=True)
class MemoryFact:
    """One durable claim about something that happened, with its provenance.

    A fact records what occurred, when, which entities it concerns, and the
    exact event it came from -- including that event's position in the log,
    because the bus permits identical events to be published more than once and
    equality alone cannot tell two occurrences apart.

    ``fact_id`` and ``summary`` are derived, never supplied. Identity is a hash
    of the fact's own content, so the same history always produces the same
    identifiers, and a persisted fact whose id or wording does not match what
    its content implies is rejected rather than trusted.

    Attributes:
        fact_type: What kind of claim this is.
        episode: Episode during which it happened.
        tick: Tick at which it happened.
        source_event_index: Zero-based position of the source event in the
            episode log.
        source_event_type: Type of the event this was derived from.
        source_id: Identifier of the entity the source event concerned.
        subject_ids: Every entity this fact concerns, sorted and unique.
        details: Read-only, recursively frozen specifics of the claim.
        fact_id: Derived deterministic identifier.
        summary: Derived narration-ready sentence.
    """

    fact_type: MemoryFactType
    episode: int
    tick: int
    source_event_index: int
    source_event_type: EventType
    source_id: EntityId
    subject_ids: tuple[EntityId, ...]
    details: Mapping[str, FrozenJsonValue]
    fact_id: str = field(init=False)
    summary: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate every field, freeze the details, and derive id and summary.

        Raises:
            TypeError: If any field is of the wrong type, or the details carry a
                value a fact may not hold.
            ValueError: If a number is out of range, an identifier is
                noncanonical, the details or subjects are not exactly what this
                fact type requires, or a cross-field rule is broken.
        """
        if type(self.fact_type) is not MemoryFactType:
            raise TypeError(
                f"fact_type must be a MemoryFactType, got {type(self.fact_type).__name__}"
            )
        if type(self.source_event_type) is not EventType:
            raise TypeError(
                "source_event_type must be an EventType, got "
                f"{type(self.source_event_type).__name__}"
            )
        expected_event_type = _SOURCE_EVENT_TYPES[self.fact_type]
        if self.source_event_type is not expected_event_type:
            raise ValueError(
                f"a {self.fact_type.value} fact must come from a "
                f"{expected_event_type.value} event, got {self.source_event_type.value}"
            )

        require_exact_int(self.episode, "episode")
        require_exact_int(self.tick, "tick")
        require_exact_int(self.source_event_index, "source_event_index")
        require_identifier(self.source_id, "source_id")

        frozen_details = self._validated_details()
        object.__setattr__(self, "details", frozen_details)
        self._validate_subjects(frozen_details)
        self._validate_cross_fields(frozen_details)

        object.__setattr__(self, "fact_id", self._derive_fact_id())
        object.__setattr__(self, "summary", self._derive_summary())

    def _validated_details(self) -> Mapping[str, FrozenJsonValue]:
        """Return the details frozen, after checking they are exactly right.

        Raises:
            TypeError: If the details are not a mapping or hold a forbidden type.
            ValueError: If the key set is not exactly this fact type's.
        """
        if not _has_mapping_type(self.details):
            raise TypeError(f"details must be a mapping, got {type(self.details).__name__}")
        # Frozen directly from what was supplied. Normalizing first -- thawing
        # to plain JSON and re-freezing -- would quietly turn a tuple into a
        # list, accepting input the fact is supposed to refuse.
        frozen = _freeze(dict(self.details), "details")
        if not _is_frozen_mapping(frozen):  # pragma: no cover - a dict freezes to a Mapping
            raise TypeError("details must freeze to a mapping")

        expected = _DETAILS_KEYS[self.fact_type]
        present = set(frozen)
        missing = sorted(expected - present)
        unexpected = sorted(present - expected)
        if missing:
            raise ValueError(f"details for {self.fact_type.value} is missing keys: {missing}")
        if unexpected:
            raise ValueError(
                f"details for {self.fact_type.value} carries unexpected keys: {unexpected}"
            )
        return frozen

    def _validate_subjects(self, details: Mapping[str, FrozenJsonValue]) -> None:
        """Verify the subjects are exactly the entities this fact concerns.

        Raises:
            TypeError: If ``subject_ids`` is not a tuple of strings.
            ValueError: If it repeats an entity, is unsorted, or does not match
                the identifiers the details name.
        """
        if type(self.subject_ids) is not tuple:
            raise TypeError(f"subject_ids must be a tuple, got {type(self.subject_ids).__name__}")
        for index, subject in enumerate(self.subject_ids):
            require_identifier(subject, f"subject_ids[{index}]")
        if len(set(self.subject_ids)) != len(self.subject_ids):
            raise ValueError(f"subject_ids must not repeat an entity, got {self.subject_ids}")
        if list(self.subject_ids) != sorted(self.subject_ids):
            raise ValueError(f"subject_ids must be sorted, got {self.subject_ids}")

        expected = tuple(
            sorted(
                {
                    require_identifier(details[key], f"details[{key!r}]")
                    for key in _SUBJECT_KEYS[self.fact_type]
                }
            )
        )
        if self.subject_ids != expected:
            raise ValueError(
                f"subject_ids for {self.fact_type.value} must be {list(expected)}, "
                f"got {list(self.subject_ids)}"
            )

    def _validate_cross_fields(self, details: Mapping[str, FrozenJsonValue]) -> None:
        """Verify the details agree with each other and with the fact's own fields.

        Raises:
            TypeError: If a detail is of the wrong type.
            ValueError: If a detail contradicts another or the fact's tick.
        """
        if self.fact_type is MemoryFactType.WALL_BUILT:
            self._validate_wall_built(details)
        else:
            self._validate_law_restored_wall_persisted(details)

    def _validate_wall_built(self, details: Mapping[str, FrozenJsonValue]) -> None:
        """Verify a wall-construction fact is internally consistent.

        Raises:
            TypeError: If a detail is of the wrong type.
            ValueError: If the fact contradicts itself.
        """
        wall_id = require_identifier(details["wall_id"], "details['wall_id']")
        boundary_id = require_identifier(details["boundary_id"], "details['boundary_id']")
        district_a = require_identifier(details["district_a_id"], "details['district_a_id']")
        district_b = require_identifier(details["district_b_id"], "details['district_b_id']")
        built_tick = require_exact_int(details["built_tick"], "details['built_tick']")
        require_mapping(details["source_event_payload"], "details['source_event_payload']")

        if self.source_id != wall_id:
            raise ValueError(
                f"a WALL_BUILT fact must be sourced from its own wall; source_id is "
                f"{self.source_id!r} but the wall is {wall_id!r}"
            )
        if district_a == district_b:
            raise ValueError(
                f"boundary {boundary_id!r} cannot join district {district_a!r} to itself"
            )
        if built_tick != self.tick:
            raise ValueError(
                f"a WALL_BUILT fact must be recorded at the tick the wall was built; "
                f"fact tick is {self.tick} but built_tick is {built_tick}"
            )
        if require_flag(details["permanent"], "details['permanent']") is not True:
            raise ValueError("only a permanent wall is remembered as built")

    def _validate_law_restored_wall_persisted(self, details: Mapping[str, FrozenJsonValue]) -> None:
        """Verify a wall-persistence fact is internally consistent.

        Raises:
            TypeError: If a detail is of the wrong type.
            ValueError: If the fact contradicts itself, or claims a wall built at
                or after the restoration survived it.
        """
        law_id = require_identifier(details["law_id"], "details['law_id']")
        require_identifier(details["wall_id"], "details['wall_id']")
        require_identifier(details["boundary_id"], "details['boundary_id']")
        require_text(details["law_name"], "details['law_name']")
        require_law_value(details["law_previous_value"], "details['law_previous_value']")
        require_law_value(details["law_current_value"], "details['law_current_value']")
        restored_tick = require_exact_int(details["restored_tick"], "details['restored_tick']")
        wall_built_tick = require_exact_int(
            details["wall_built_tick"], "details['wall_built_tick']"
        )
        require_flag(
            details["wall_active_at_episode_close"], "details['wall_active_at_episode_close']"
        )
        require_mapping(details["source_event_payload"], "details['source_event_payload']")
        for key in (
            "wall_dependency_score_at_episode_close",
            "wall_resource_dependency_at_episode_close",
            "wall_transport_dependency_at_episode_close",
        ):
            require_unit_interval(details[key], f"details[{key!r}]")

        if self.source_id != law_id:
            raise ValueError(
                f"a LAW_RESTORED_WALL_PERSISTED fact must be sourced from its own law; "
                f"source_id is {self.source_id!r} but the law is {law_id!r}"
            )
        if restored_tick != self.tick:
            raise ValueError(
                f"the fact tick must be the restoration tick; fact tick is {self.tick} but "
                f"restored_tick is {restored_tick}"
            )
        if require_flag(details["wall_permanent"], "details['wall_permanent']") is not True:
            raise ValueError("only a permanent wall is remembered as persisting")
        if wall_built_tick >= restored_tick:
            raise ValueError(
                f"a wall built at tick {wall_built_tick} was not already standing when the "
                f"law was restored at tick {restored_tick}; the comparison is strict"
            )

    def _derive_fact_id(self) -> str:
        """Return the deterministic identifier implied by this fact's content."""
        return FACT_ID_PREFIX + hashlib.sha256(_compact_json(self.identity_document())).hexdigest()

    def identity_document(self) -> dict[str, JsonValue]:
        """Return the exact document this fact's identifier is computed over.

        Everything that distinguishes one fact from another appears here, and
        nothing derived does. Including the id or summary would make identity
        circular; excluding the event index would let two identical events
        published in the same tick collapse into one fact.
        """
        return {
            "details": self.details_as_dict(),
            "episode": self.episode,
            "fact_type": self.fact_type.value,
            "source_event_index": self.source_event_index,
            "source_event_type": self.source_event_type.value,
            "source_id": self.source_id,
            "subject_ids": list(self.subject_ids),
            "tick": self.tick,
        }

    def _derive_summary(self) -> str:
        """Return the fixed sentence this fact's content implies.

        Structured prose, not generated text. The wording is a template so that
        a later narration phase reads a stable, checkable string, and so that
        nothing here can quietly assert a causal link the events never proved.
        """
        details = self.details
        if self.fact_type is MemoryFactType.WALL_BUILT:
            return (
                f"Wall {_quote(str(details['wall_id']))} was built on boundary "
                f"{_quote(str(details['boundary_id']))} between districts "
                f"{_quote(str(details['district_a_id']))} and "
                f"{_quote(str(details['district_b_id']))} at tick {self.tick}; "
                "it was marked permanent."
            )
        return (
            f"Law {_quote(str(details['law_id']))} ({_quote(str(details['law_name']))}) was "
            f"restored at tick {self.tick}; permanent wall "
            f"{_quote(str(details['wall_id']))} on boundary "
            f"{_quote(str(details['boundary_id']))}, built at tick "
            f"{details['wall_built_tick']}, remained in the world."
        )

    def details_as_dict(self) -> dict[str, JsonValue]:
        """Return a detached, mutable JSON copy of this fact's details."""
        return {key: _thaw(value) for key, value in self.details.items()}

    def to_document(self) -> dict[str, JsonValue]:
        """Return this fact as the JSON object a save stores."""
        document = self.identity_document()
        document["fact_id"] = self.fact_id
        document["summary"] = self.summary
        return document

    @classmethod
    def from_document(cls, value: object, description: str = "fact") -> "MemoryFact":
        """Rebuild a fact from a stored document, recomputing what is derived.

        The stored identifier and summary are treated as claims to check, not as
        data to load. Both are recomputed from the semantic content and compared:
        a document whose id or wording disagrees with what its own content
        implies was not written by this build and is refused.

        Raises:
            TypeError: If the document or a field is of the wrong type.
            ValueError: If keys are missing or extra, a value is invalid, or the
                recorded id or summary does not match the content.
        """
        # One read, and everything below works from the result. Validating the
        # caller's mapping and then reading it again would let a stateful mapping
        # be checked in one shape and used in another.
        document = _snapshot_exact_string_mapping(value, description)
        present = set(document)
        missing = sorted(_FACT_DOCUMENT_KEYS - present)
        unexpected = sorted(present - _FACT_DOCUMENT_KEYS)
        if missing:
            raise ValueError(f"{description} is missing required keys: {missing}")
        if unexpected:
            raise ValueError(f"{description} carries unexpected keys: {unexpected}")

        subjects = document["subject_ids"]
        if type(subjects) is not list:
            raise TypeError(
                f"{description} subject_ids must be a list, got {type(subjects).__name__}"
            )
        details = _snapshot_exact_string_mapping(document["details"], f"{description} details")

        fact = cls(
            fact_type=_named_member(
                MemoryFactType, document["fact_type"], f"{description} fact_type"
            ),
            episode=require_exact_int(document["episode"], f"{description} episode"),
            tick=require_exact_int(document["tick"], f"{description} tick"),
            source_event_index=require_exact_int(
                document["source_event_index"], f"{description} source_event_index"
            ),
            source_event_type=_named_member(
                EventType, document["source_event_type"], f"{description} source_event_type"
            ),
            source_id=require_identifier(document["source_id"], f"{description} source_id"),
            subject_ids=tuple(
                require_identifier(subject, f"{description} subject_ids[{index}]")
                for index, subject in enumerate(subjects)
            ),
            # The constructor deep-freezes and validates this plain-JSON
            # mapping at runtime. Its field annotation describes the frozen
            # result, which ``_freeze`` refuses as input by design, so the
            # supplied shape cannot be expressed to the checker.
            details=details,  # type: ignore[arg-type]
        )

        recorded_id = require_exact_str(document["fact_id"], f"{description} fact_id")
        if recorded_id != fact.fact_id:
            raise ValueError(
                f"{description} records fact_id {recorded_id!r} but its content implies "
                f"{fact.fact_id!r}"
            )
        recorded_summary = require_exact_str(document["summary"], f"{description} summary")
        if recorded_summary != fact.summary:
            raise ValueError(f"{description} records a summary that its content does not imply")
        return fact

    def __hash__(self) -> int:
        """Hash by derived identifier.

        The identifier is a hash of everything that distinguishes one fact from
        another, so two equal facts always share it -- which is exactly the
        contract ``__hash__`` owes ``__eq__``. The generated implementation could
        not be used: it would traverse ``details``, whose read-only mappings are
        not hashable, and would fail at the moment a caller first put a fact in a
        set.
        """
        return hash(self.fact_id)

    def sort_key(self) -> tuple[int, int, int, str, str]:
        """Return the canonical ordering key for this fact.

        Chronological first, then by the position of the event that produced it,
        so a tick that produced several facts replays in the order the engine
        actually emitted them. Type and identifier break any remaining tie
        deterministically.
        """
        return (
            self.episode,
            self.tick,
            self.source_event_index,
            self.fact_type.value,
            self.fact_id,
        )


def require_text(value: object, description: str) -> str:
    """Return a non-blank ``str`` carrying no surrounding whitespace, else raise.

    Raises:
        TypeError: If the value is not a ``str``.
        ValueError: If it is blank or carries surrounding whitespace.
    """
    return require_identifier(value, description)


def _snapshot_exact_string_mapping(value: object, description: str) -> dict[str, object]:
    """Read a mapping exactly once, validating its keys as they are exposed.

    Set arithmetic and dictionary lookup both work through equality and hashing,
    so a ``str`` subclass or a ``StrEnum`` member behaves exactly like the key it
    copies. Checking the keys is therefore necessary -- but checking them and
    then reading the mapping again is not enough. Nothing obliges a mapping to
    answer the same way twice, so one that exposes ordinary keys while being
    validated and subclass keys afterwards would pass the check and still be read
    through keys the format forbids.

    The fix is not a stricter check but a single read: everything the caller goes
    on to use comes from the snapshot taken here, so validation and use are
    guaranteed to be looking at the same document.

    Values are carried across untouched and keys are never coerced with
    ``str()``. A mapping whose keys are not exact strings is refused as it
    stands, and the original is left exactly as it was.

    Args:
        value: The mapping to snapshot.
        description: What is being read, used in error messages.

    Returns:
        A new ``dict`` holding exactly what the mapping exposed.

    Raises:
        TypeError: If the value is not a mapping, or a key is not exactly a
            ``str``.
        ValueError: If the mapping exposes the same key more than once.
    """
    if not _has_mapping_type(value):
        raise TypeError(f"{description} must be a mapping, got {type(value).__name__}")
    # Sound: the check above proved the true runtime type is a Mapping. Keys
    # are deliberately object here -- they are validated one by one below.
    mapping = cast(Mapping[object, object], value)

    snapshot: dict[str, object] = {}
    for key, item in mapping.items():
        if type(key) is not str:
            raise TypeError(f"{description} keys must be exact strings, got {type(key).__name__}")
        if key in snapshot:
            raise ValueError(f"{description} repeats key {key!r}")
        snapshot[key] = item
    return snapshot


def require_mapping(value: object, description: str) -> Mapping[str, object]:
    """Return the value if it is a mapping, else raise.

    Raises:
        TypeError: If the value is not a mapping.
    """
    if not _has_mapping_type(value):
        raise TypeError(f"{description} must be a mapping, got {type(value).__name__}")
    # Sound: the check above proved the true runtime type is a Mapping. The
    # string-keyed view restates this function's documented contract; every
    # consumer validates the keys it reads, exactly as before.
    return cast(Mapping[str, object], value)


def _named_member[MemberT: Enum](
    enum_type: type[MemberT], value: object, description: str
) -> MemberT:
    """Return the enum member named by a stable value, else raise.

    Raises:
        TypeError: If the value is not a ``str``.
        ValueError: If it names no member of the enum.
    """
    if type(value) is not str:
        raise TypeError(f"{description} must be a str, got {type(value).__name__}")
    try:
        return enum_type(value)
    except ValueError as error:
        known = sorted(str(member.value) for member in enum_type)
        raise ValueError(f"{description} must be one of {known}, got {value!r}") from error


class WorldMemory:
    """The complete, cumulative history of everything the world remembers.

    Append-only by construction. Nothing here removes, rewrites, reorders, or
    compacts a fact, because the whole promise of the series is that a
    consequence outlives the episode that caused it -- and a memory that could
    quietly drop an old fact would make that promise unverifiable.

    A memory also records how far it has been processed. The checkpoint lives on
    the Python object rather than in the save file: the episode manifest already
    states the authoritative episode and tick, and storing them twice would
    create two sources of truth that could disagree.
    """

    __slots__ = ("_facts", "_through_episode", "_through_tick")

    def __init__(
        self,
        facts: Sequence[MemoryFact] = (),
        *,
        through_episode: int | None = None,
        through_tick: int | None = None,
    ) -> None:
        """Create a memory holding the given facts at the given checkpoint.

        Args:
            facts: The complete history, already in canonical order.
            through_episode: Episode this memory has been processed through, or
                ``None`` when nothing has been processed yet.
            through_tick: Tick this memory has been processed through, or
                ``None`` when nothing has been processed yet.

        Raises:
            TypeError: If a fact is not a ``MemoryFact`` or the checkpoint is of
                the wrong type.
            ValueError: If only one checkpoint field is given, an unprocessed
                memory carries facts, the facts are out of canonical order, an
                identifier or wall-build claim repeats, or a fact lies beyond the
                checkpoint.
        """
        ordered = tuple(facts)
        for index, fact in enumerate(ordered):
            if not _is_runtime_instance(fact, MemoryFact):
                raise TypeError(f"facts[{index}] must be a MemoryFact, got {type(fact).__name__}")

        if (through_episode is None) != (through_tick is None):
            raise ValueError("through_episode and through_tick must both be set or both be absent")
        if through_episode is not None:
            require_exact_int(through_episode, "through_episode")
        if through_tick is not None:
            require_exact_int(through_tick, "through_tick")

        if through_episode is None and ordered:
            raise ValueError(
                "an unprocessed memory cannot already hold facts; a fact only exists "
                "because an episode was distilled"
            )

        _require_canonical_order(ordered)
        _require_unique_identity(ordered)
        if through_episode is not None and through_tick is not None:
            _require_within_checkpoint(ordered, through_episode, through_tick)

        self._facts = ordered
        self._through_episode = through_episode
        self._through_tick = through_tick

    @classmethod
    def empty(cls) -> "WorldMemory":
        """Return a memory that has processed nothing and holds nothing."""
        return cls()

    @property
    def facts(self) -> tuple[MemoryFact, ...]:
        """Every remembered fact, in canonical order."""
        return self._facts

    @property
    def through_episode(self) -> int | None:
        """Episode this memory has been processed through, if any."""
        return self._through_episode

    @property
    def through_tick(self) -> int | None:
        """Tick this memory has been processed through, if any."""
        return self._through_tick

    def advance(
        self, *, episode: int, tick: int, new_facts: Sequence[MemoryFact] = ()
    ) -> "WorldMemory":
        """Return a new memory carrying these facts on top of this one.

        The checkpoint advances whether or not anything was remembered: an
        episode in which nothing significant happened is still an episode that
        was processed, and leaving the checkpoint behind would make the next one
        look like a gap.

        Args:
            episode: The episode just processed.
            tick: The world tick at the close of that episode.
            new_facts: Facts distilled from that episode, in canonical order.

        Returns:
            A new memory. This one is left untouched.

        Raises:
            TypeError: If an argument is of the wrong type.
            ValueError: If the episode does not follow directly, time moves
                backward, or a new fact does not belong to the new episode.
        """
        require_exact_int(episode, "episode")
        require_exact_int(tick, "tick")
        added = tuple(new_facts)

        if self._through_episode is None:
            if episode != 0:
                raise ValueError(f"the first processed episode must be episode 0, got {episode}")
        else:
            expected = self._through_episode + 1
            if episode != expected:
                raise ValueError(
                    f"episode {episode} does not directly follow the processed episode "
                    f"{self._through_episode}"
                )
            if self._through_tick is not None and tick < self._through_tick:
                raise ValueError(
                    f"world time cannot move backward: tick {tick} precedes the processed "
                    f"tick {self._through_tick}"
                )

        for index, fact in enumerate(added):
            if not _is_runtime_instance(fact, MemoryFact):
                raise TypeError(
                    f"new_facts[{index}] must be a MemoryFact, got {type(fact).__name__}"
                )
            if fact.episode != episode:
                raise ValueError(
                    f"new_facts[{index}] belongs to episode {fact.episode}, not the episode "
                    f"being processed ({episode})"
                )
            if fact.tick > tick:
                raise ValueError(
                    f"new_facts[{index}] happened at tick {fact.tick}, after the episode "
                    f"closed at tick {tick}"
                )
            if self._through_tick is not None and fact.tick <= self._through_tick:
                raise ValueError(
                    f"new_facts[{index}] happened at tick {fact.tick}, which was already "
                    f"processed through tick {self._through_tick}"
                )

        return WorldMemory(self._facts + added, through_episode=episode, through_tick=tick)

    def __len__(self) -> int:
        """Return how many facts are remembered."""
        return len(self._facts)

    def __iter__(self) -> Iterator[MemoryFact]:
        """Iterate the remembered facts in canonical order."""
        return iter(self._facts)

    def __eq__(self, other: object) -> bool:
        """Compare by remembered facts and processed checkpoint."""
        if not _is_runtime_instance(other, WorldMemory):
            return NotImplemented
        return (
            self._facts == other._facts
            and self._through_episode == other._through_episode
            and self._through_tick == other._through_tick
        )

    def __hash__(self) -> int:
        """Hash by processed checkpoint and the ordered fact identifiers.

        Identifiers rather than the facts themselves: a fact's identifier already
        summarizes its whole content, and hashing the objects would recurse into
        details that are not hashable.
        """
        return hash(
            (self._through_episode, self._through_tick, tuple(f.fact_id for f in self._facts))
        )

    def __repr__(self) -> str:
        """Return a short, deterministic description of this memory."""
        return (
            f"WorldMemory(facts={len(self._facts)}, through_episode={self._through_episode}, "
            f"through_tick={self._through_tick})"
        )


def _require_canonical_order(facts: Sequence[MemoryFact]) -> None:
    """Verify facts are already in canonical order.

    A memory read from disk is never quietly sorted. Facts arriving out of order
    mean the file was written by something other than this build, and reordering
    them would hide that while changing what the history says happened first.

    Raises:
        ValueError: If any fact precedes the one before it.
    """
    for index in range(1, len(facts)):
        if facts[index].sort_key() < facts[index - 1].sort_key():
            raise ValueError(
                f"facts must be in canonical order; facts[{index}] "
                f"({facts[index].fact_id}) precedes facts[{index - 1}] "
                f"({facts[index - 1].fact_id})"
            )


def _require_unique_identity(facts: Sequence[MemoryFact]) -> None:
    """Verify no fact identifier repeats and no wall is built twice.

    Raises:
        ValueError: If an identifier repeats, or two facts claim the same wall
            was built.
    """
    seen: set[str] = set()
    built: dict[EntityId, MemoryFact] = {}
    for index, fact in enumerate(facts):
        if fact.fact_id in seen:
            raise ValueError(f"facts[{index}] repeats fact_id {fact.fact_id}")
        seen.add(fact.fact_id)
        if fact.fact_type is MemoryFactType.WALL_BUILT:
            wall_id = str(fact.details["wall_id"])
            if wall_id in built:
                raise ValueError(
                    f"facts[{index}] claims wall {wall_id!r} was built, but an earlier fact "
                    "already records its construction"
                )
            built[wall_id] = fact
        else:
            _require_build_provenance(fact, index, built)


def _require_build_provenance(
    fact: MemoryFact, index: int, built: Mapping[EntityId, MemoryFact]
) -> None:
    """Verify a persistence fact rests on an earlier construction it agrees with.

    A fact saying a wall survived a restoration is meaningless without the fact
    saying the wall was built. Allowing an orphan would let a memory assert its
    own unproven origin -- history invented backwards from a conclusion.

    Raises:
        ValueError: If no earlier construction exists for the wall, or the two
            facts disagree about it.
    """
    wall_id = str(fact.details["wall_id"])
    build_fact = built.get(wall_id)
    if build_fact is None:
        raise ValueError(
            f"facts[{index}] says wall {wall_id!r} persisted, but no earlier fact records "
            "that it was ever built"
        )
    if build_fact.details["boundary_id"] != fact.details["boundary_id"]:
        raise ValueError(
            f"facts[{index}] places wall {wall_id!r} on boundary "
            f"{fact.details['boundary_id']!r}, but it was built on "
            f"{build_fact.details['boundary_id']!r}"
        )
    if build_fact.details["built_tick"] != fact.details["wall_built_tick"]:
        raise ValueError(
            f"facts[{index}] records wall {wall_id!r} as built at tick "
            f"{fact.details['wall_built_tick']!r}, but its construction records "
            f"{build_fact.details['built_tick']!r}"
        )
    if build_fact.tick >= fact.tick:
        raise ValueError(
            f"facts[{index}] says wall {wall_id!r} persisted through tick {fact.tick}, but "
            f"its construction is recorded at tick {build_fact.tick}"
        )


def _require_within_checkpoint(
    facts: Sequence[MemoryFact], through_episode: int, through_tick: int
) -> None:
    """Verify no fact lies beyond the processed checkpoint.

    Raises:
        ValueError: If a fact belongs to a later episode, or happened after the
            checkpoint tick.
    """
    for index, fact in enumerate(facts):
        if fact.episode > through_episode:
            raise ValueError(
                f"facts[{index}] belongs to episode {fact.episode}, beyond the processed "
                f"episode {through_episode}"
            )
        if fact.tick > through_tick:
            raise ValueError(
                f"facts[{index}] happened at tick {fact.tick}, beyond the processed tick "
                f"{through_tick}"
            )


def wall_build_facts(memory: WorldMemory) -> dict[EntityId, MemoryFact]:
    """Return every remembered wall-construction fact, keyed by wall identifier.

    Used to answer the only question the persistence rule needs: does this wall
    have recorded provenance for having been built?
    """
    return {
        str(fact.details["wall_id"]): fact
        for fact in memory.facts
        if fact.fact_type is MemoryFactType.WALL_BUILT
    }
