"""The external run plan that configures one episode continuation.

A continuation run is driven by a single JSON plan file. The plan is operator
input, not world state: it never enters an episode save directory, and nothing
about the Phase 10 save schema knows it exists. It names the parent episode to
continue from, how many ticks the new episode runs, exactly one scheduled rule
intervention, and every parameter the canonical causal systems need -- nothing
is defaulted from test helpers, and nothing is invented here.

The plan's top level carries exactly four keys::

    parent_episode   exact integer >= 0; the verified episode to continue from
    ticks            exact integer > 0; how many ticks the new episode runs
    intervention     exactly one scheduled law change or restoration
    systems          explicit configuration for the nine causal systems

The target episode is never part of the plan. It is always derived as
``parent_episode + 1``, so an operator plan cannot disagree with the
continuation chain. For the same reason the intervention carries no ``episode``
field: its episode is the derived child episode, always.

The intervention ``tick`` is an ABSOLUTE world tick. The loaded parent world
owns the starting tick, and the tick is never reset, so a plan schedules its
intervention on the world's own clock. Whether the tick falls inside the run
window can only be judged against the verified parent, so that check belongs to
the runner, not to this parser.

Parsing follows the engine's semantic snapshot rule: the JSON bytes are decoded
strictly (duplicate object keys, ``NaN``, ``Infinity``, and malformed input are
refused, never repaired), each semantic value is read exactly once, validated
exactly, and captured into frozen objects. No mutable parsed structure is
retained, so a plan that passed validation cannot change underneath the run.

There is deliberately no ``seed`` anywhere in a plan. A continuation inherits
the parent's saved RNG state; accepting a seed would silently restart the very
sequence the save exists to preserve.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, cast

from living_diorama.entities import EntityId, LawValue, ResourceType
from living_diorama.events.event import JsonValue
from living_diorama.persistence.json_codec import loads_canonical, require_document
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_identifier,
)
from living_diorama.systems import ScheduledLawChange, ScheduledLawRestore

_PLAN_KEYS: Final = frozenset({"intervention", "parent_episode", "systems", "ticks"})
"""Exactly the top-level keys a run plan carries."""

_CHANGE_KEYS: Final = frozenset({"active", "kind", "law_id", "new_value", "tick"})
"""Exactly the keys a change intervention carries. There is no episode key."""

_RESTORE_KEYS: Final = frozenset({"kind", "law_id", "tick"})
"""Exactly the keys a restore intervention carries. There is no episode key."""

_SYSTEMS_KEYS: Final = frozenset(
    {
        "boundary_decision",
        "consumption_allocation",
        "infrastructure_adaptation",
        "institutional_pressure",
        "migration",
        "movement_law_id",
        "production_allocation",
        "resource_flow",
        "social_stability",
    }
)
"""Exactly the keys the systems section carries."""

_RESOURCE_FLOW_KEYS: Final = frozenset({"reserve_ticks"})
_MIGRATION_KEYS: Final = frozenset(
    {"migration_rate", "min_pressure_gap", "partial_isolation_factor"}
)
_SOCIAL_STABILITY_KEYS: Final = frozenset(
    {"housing_pressure_weight", "response_rate", "scarcity_weight"}
)
_INSTITUTIONAL_PRESSURE_KEYS: Final = frozenset(
    {"distrust_weight", "fear_weight", "response_rate", "scarcity_weight"}
)
_BOUNDARY_DECISION_KEYS: Final = frozenset({"build_threshold"})
_INFRASTRUCTURE_ADAPTATION_KEYS: Final = frozenset({"adaptation_rate"})

_CHANGE_KIND: Final = "change"
_RESTORE_KIND: Final = "restore"


def _require_real_number(value: object, description: str) -> float:
    """Return an exact ``int`` or ``float`` unchanged, else raise.

    ``bool`` is refused before anything else because it subclasses ``int``:
    ``True`` would otherwise configure a rate of 1 with nothing downstream able
    to tell. The value is returned as supplied, never converted -- conversion is
    the receiving system constructor's own documented behavior, and doing it
    here would hand the constructor something other than what the plan said.

    Raises:
        TypeError: If the value is not an exact ``int`` or ``float``.
        ValueError: If it is not finite.
    """
    if type(value) is bool or type(value) not in (int, float):
        raise TypeError(f"{description} must be a real number, got {type(value).__name__}")
    number = cast("int | float", value)
    if not math.isfinite(number):
        raise ValueError(f"{description} must be finite, got {number!r}")
    return number


def _snapshot_allocation(value: object, description: str) -> Mapping[ResourceType, float]:
    """Capture one resource allocation into a fresh read-only mapping.

    The external representation keys weights by resource NAME. Every current
    ``ResourceType`` member must appear exactly once and no unknown name may
    appear at all; each name is converted to the exact enum member before any
    system sees it. Weight arithmetic (non-negativity, summing to 1.0) is the
    receiving constructor's own contract and is deliberately not repeated here.

    Raises:
        TypeError: If the value is not a mapping or a weight is not a real
            number.
        ValueError: If a resource name is missing, unknown, or a weight is not
            finite.
    """
    if isinstance(value, Mapping):
        entries = dict(value)
    else:
        raise TypeError(f"{description} must be a mapping, got {type(value).__name__}")

    expected_names = frozenset(member.name for member in ResourceType)
    present = set()
    for key in entries:
        if type(key) is ResourceType:
            raise TypeError(
                f"{description} keys must be resource names such as "
                f"{sorted(expected_names)}, not ResourceType members"
            )
        if type(key) is not str:
            raise TypeError(
                f"{description} keys must be str resource names, got {type(key).__name__}"
            )
        present.add(key)

    unknown = sorted(present - expected_names)
    if unknown:
        raise ValueError(f"{description} names unknown resources: {unknown}")
    missing = sorted(expected_names - present)
    if missing:
        raise ValueError(f"{description} is missing resources: {missing}")

    allocation = {
        member: _require_real_number(entries[member.name], f"{description}[{member.name}]")
        for member in ResourceType
    }
    return MappingProxyType(allocation)


def _snapshot_enum_allocation(value: object, description: str) -> Mapping[ResourceType, float]:
    """Capture an already enum-keyed allocation into a fresh read-only mapping.

    This is the direct-construction door: :class:`SystemsConfiguration` accepts
    a mapping keyed by exact ``ResourceType`` members and re-captures it, so a
    caller-owned dict is never retained and a later mutation of it cannot reach
    the frozen configuration.

    Raises:
        TypeError: If the value is not a mapping, a key is not an exact
            ``ResourceType`` member, or a weight is not a real number.
        ValueError: If a member is missing or a weight is not finite.
    """
    if not isinstance(value, Mapping):
        raise TypeError(f"{description} must be a mapping, got {type(value).__name__}")
    entries = dict(value)
    for key in entries:
        if type(key) is not ResourceType:
            raise TypeError(
                f"{description} keys must be ResourceType members, got {type(key).__name__}"
            )
    missing = sorted(member.value for member in ResourceType if member not in entries)
    if missing:
        raise ValueError(f"{description} is missing resources: {missing}")
    allocation = {
        member: _require_real_number(entries[member], f"{description}[{member.value}]")
        for member in ResourceType
    }
    return MappingProxyType(allocation)


@dataclass(frozen=True, slots=True, kw_only=True)
class SystemsConfiguration:
    """Every parameter the nine canonical causal systems are built from.

    One frozen capture of the plan's ``systems`` section. Field names follow
    the constructor parameters of the systems they configure; where two systems
    share a parameter name (``scarcity_weight``, ``response_rate``) the field is
    prefixed with the owning system. The two allocations are re-captured into
    read-only mappings at construction, so the caller's objects are never
    retained.

    Only structural and exact-type contracts are enforced here. Numeric domain
    contracts -- weight sums, unit intervals, non-negativity -- belong to the
    system constructors themselves and fire when the systems are built, which
    still happens before any simulation begins.

    Attributes:
        production_allocation: Weights splitting production across resources.
        consumption_allocation: Weights splitting demand across resources; the
            same allocation feeds consumption, resource flow, migration, and
            scarcity, which the engine requires to agree.
        movement_law_id: The movement/resource-sharing law both the resource
            flow and migration systems consult.
        reserve_ticks: Ticks of demand a donor district keeps before sharing.
        migration_rate: Fraction of pressured population that moves per tick.
        min_pressure_gap: Smallest pressure difference that causes migration.
        partial_isolation_factor: Migration multiplier through partial
            isolation.
        social_scarcity_weight: Scarcity weight of social pressure.
        housing_pressure_weight: Housing weight of social pressure.
        social_response_rate: How fast fear and trust move toward pressure.
        institutional_scarcity_weight: Scarcity weight of institutional
            pressure.
        fear_weight: Fear weight of institutional pressure.
        distrust_weight: Distrust weight of institutional pressure.
        institutional_response_rate: How fast institutional pressure responds.
        build_threshold: Boundary pressure at which a wall is built.
        adaptation_rate: How fast infrastructure grows dependent on a wall.
    """

    production_allocation: Mapping[ResourceType, float]
    consumption_allocation: Mapping[ResourceType, float]
    movement_law_id: EntityId
    reserve_ticks: float
    migration_rate: float
    min_pressure_gap: float
    partial_isolation_factor: float
    social_scarcity_weight: float
    housing_pressure_weight: float
    social_response_rate: float
    institutional_scarcity_weight: float
    fear_weight: float
    distrust_weight: float
    institutional_response_rate: float
    build_threshold: float
    adaptation_rate: float

    def __post_init__(self) -> None:
        """Capture and validate every field exactly as supplied.

        Each caller-owned mapping is read once and replaced by a fresh
        read-only capture (the standard frozen-dataclass normalization, using
        ``object.__setattr__`` on this instance's own slots during its own
        construction). Scalars are checked for exact type and finiteness; the
        identifier is refused rather than repaired if it is noncanonical,
        because stripping it would target a different law than the one the
        plan named.

        Raises:
            TypeError: If a field is of the wrong exact type.
            ValueError: If an allocation names the wrong resources, a scalar is
                not finite, or the law identifier is noncanonical.
        """
        object.__setattr__(
            self,
            "production_allocation",
            _snapshot_enum_allocation(self.production_allocation, "production_allocation"),
        )
        object.__setattr__(
            self,
            "consumption_allocation",
            _snapshot_enum_allocation(self.consumption_allocation, "consumption_allocation"),
        )
        require_identifier(self.movement_law_id, "movement_law_id")
        _require_real_number(self.reserve_ticks, "reserve_ticks")
        _require_real_number(self.migration_rate, "migration_rate")
        _require_real_number(self.min_pressure_gap, "min_pressure_gap")
        _require_real_number(self.partial_isolation_factor, "partial_isolation_factor")
        _require_real_number(self.social_scarcity_weight, "social_stability scarcity_weight")
        _require_real_number(self.housing_pressure_weight, "housing_pressure_weight")
        _require_real_number(self.social_response_rate, "social_stability response_rate")
        _require_real_number(
            self.institutional_scarcity_weight, "institutional_pressure scarcity_weight"
        )
        _require_real_number(self.fear_weight, "fear_weight")
        _require_real_number(self.distrust_weight, "distrust_weight")
        _require_real_number(
            self.institutional_response_rate, "institutional_pressure response_rate"
        )
        _require_real_number(self.build_threshold, "build_threshold")
        _require_real_number(self.adaptation_rate, "adaptation_rate")


@dataclass(frozen=True, slots=True, kw_only=True)
class EpisodePlan:
    """One validated, frozen continuation plan.

    Everything the runner reads comes from this capture: the parsed JSON is
    gone by the time an instance exists, and every field is immutable. The
    child episode is not stored -- it is always derived from the parent, and
    the scheduled action must already agree with that derivation, so a plan
    whose action targets any other episode cannot be constructed.

    Attributes:
        parent_episode: The verified episode the continuation starts from.
        ticks: How many ticks the new episode runs. Always positive, because
            every continuation episode must contain its one intervention.
        action: The single scheduled intervention, already carrying the derived
            child episode.
        systems: The frozen configuration for the nine causal systems.
    """

    parent_episode: int
    ticks: int
    action: ScheduledLawChange | ScheduledLawRestore
    systems: SystemsConfiguration

    def __post_init__(self) -> None:
        """Validate every field exactly as supplied.

        Raises:
            TypeError: If a field is of the wrong exact type.
            ValueError: If a number is out of range or the action's episode
                disagrees with the derived child episode.
        """
        require_exact_int(self.parent_episode, "parent_episode")
        require_exact_int(self.ticks, "ticks")
        if self.ticks == 0:
            raise ValueError(
                "ticks must be > 0; a continuation episode must run long enough to "
                "contain its one scheduled intervention"
            )
        if type(self.action) not in (ScheduledLawChange, ScheduledLawRestore):
            raise TypeError(
                "action must be exactly a ScheduledLawChange or ScheduledLawRestore, "
                f"got {type(self.action).__name__}"
            )
        if self.action.episode != self.parent_episode + 1:
            raise ValueError(
                f"the action is scheduled for episode {self.action.episode} but the "
                f"continuation of episode {self.parent_episode} is episode "
                f"{self.parent_episode + 1}; the child episode is always derived, "
                "never chosen"
            )
        if type(self.systems) is not SystemsConfiguration:
            raise TypeError(
                f"systems must be a SystemsConfiguration, got {type(self.systems).__name__}"
            )

    @property
    def child_episode(self) -> int:
        """The episode this plan creates: always the parent's direct successor."""
        return self.parent_episode + 1


def _parse_intervention(
    value: JsonValue, child_episode: int
) -> ScheduledLawChange | ScheduledLawRestore:
    """Build the one scheduled action from the plan's intervention object.

    The plan may not carry an episode for the intervention: the episode is the
    derived child episode, always, so a plan cannot disagree with the chain it
    extends. Field validation belongs to the scheduled-action dataclasses
    themselves -- constructing one is the validation.

    Raises:
        TypeError: If the intervention is not a JSON object, the kind is not a
            string, or a field is of the wrong exact type.
        ValueError: If keys are missing or extra, the kind is unknown, the
            intervention carries an episode field, or a field value is invalid.
    """
    document = require_document(value, "intervention")
    if "episode" in document:
        raise ValueError(
            "intervention must not carry an 'episode' field; the episode is always "
            "derived as parent_episode + 1"
        )

    kind = document.get("kind")
    if type(kind) is not str:
        raise TypeError(f"intervention kind must be a str, got {type(kind).__name__}")
    if kind == _CHANGE_KIND:
        require_exact_keys(document, _CHANGE_KEYS, "change intervention")
        return ScheduledLawChange(
            episode=child_episode,
            tick=cast(int, document["tick"]),
            law_id=cast(str, document["law_id"]),
            new_value=cast(LawValue, document["new_value"]),
            active=cast(bool, document["active"]),
        )
    if kind == _RESTORE_KIND:
        require_exact_keys(document, _RESTORE_KEYS, "restore intervention")
        return ScheduledLawRestore(
            episode=child_episode,
            tick=cast(int, document["tick"]),
            law_id=cast(str, document["law_id"]),
        )
    raise ValueError(
        f"intervention kind must be {_CHANGE_KIND!r} or {_RESTORE_KIND!r}, got {kind!r}"
    )


def _parse_systems(value: JsonValue) -> SystemsConfiguration:
    """Build the frozen systems configuration from the plan's systems object.

    Every subsection is checked for exactly its expected keys before any value
    is read, so an unknown or missing parameter is refused with its section
    named rather than silently defaulted or ignored.

    Raises:
        TypeError: If a section is not a JSON object or a value is of the
            wrong exact type.
        ValueError: If keys are missing or extra anywhere, or a value is
            invalid.
    """
    document = require_document(value, "systems")
    require_exact_keys(document, _SYSTEMS_KEYS, "systems")

    resource_flow = require_document(document["resource_flow"], "resource_flow")
    require_exact_keys(resource_flow, _RESOURCE_FLOW_KEYS, "resource_flow")
    migration = require_document(document["migration"], "migration")
    require_exact_keys(migration, _MIGRATION_KEYS, "migration")
    social = require_document(document["social_stability"], "social_stability")
    require_exact_keys(social, _SOCIAL_STABILITY_KEYS, "social_stability")
    institutional = require_document(document["institutional_pressure"], "institutional_pressure")
    require_exact_keys(institutional, _INSTITUTIONAL_PRESSURE_KEYS, "institutional_pressure")
    boundary = require_document(document["boundary_decision"], "boundary_decision")
    require_exact_keys(boundary, _BOUNDARY_DECISION_KEYS, "boundary_decision")
    infrastructure = require_document(
        document["infrastructure_adaptation"], "infrastructure_adaptation"
    )
    require_exact_keys(infrastructure, _INFRASTRUCTURE_ADAPTATION_KEYS, "infrastructure_adaptation")

    return SystemsConfiguration(
        production_allocation=_snapshot_allocation(
            document["production_allocation"], "production_allocation"
        ),
        consumption_allocation=_snapshot_allocation(
            document["consumption_allocation"], "consumption_allocation"
        ),
        movement_law_id=require_identifier(document["movement_law_id"], "movement_law_id"),
        reserve_ticks=cast(float, resource_flow["reserve_ticks"]),
        migration_rate=cast(float, migration["migration_rate"]),
        min_pressure_gap=cast(float, migration["min_pressure_gap"]),
        partial_isolation_factor=cast(float, migration["partial_isolation_factor"]),
        social_scarcity_weight=cast(float, social["scarcity_weight"]),
        housing_pressure_weight=cast(float, social["housing_pressure_weight"]),
        social_response_rate=cast(float, social["response_rate"]),
        institutional_scarcity_weight=cast(float, institutional["scarcity_weight"]),
        fear_weight=cast(float, institutional["fear_weight"]),
        distrust_weight=cast(float, institutional["distrust_weight"]),
        institutional_response_rate=cast(float, institutional["response_rate"]),
        build_threshold=cast(float, boundary["build_threshold"]),
        adaptation_rate=cast(float, infrastructure["adaptation_rate"]),
    )


def parse_episode_plan(data: bytes) -> EpisodePlan:
    """Decode and validate one run plan, and return its frozen capture.

    Decoding is strict: malformed JSON, non-UTF-8 bytes, duplicate object
    keys, ``NaN``, ``Infinity``, ``-Infinity``, and overflowing numeric
    literals are refused outright, never repaired. Every semantic value is
    then read exactly once and captured into frozen objects; nothing parsed
    is retained.

    Args:
        data: The exact bytes of the plan file.

    Returns:
        The validated, immutable plan.

    Raises:
        TypeError: If ``data`` is not ``bytes`` or a plan value is of the
            wrong exact type.
        ValueError: If the bytes are not a strict JSON object, keys are
            missing or extra anywhere, or any value is invalid.
    """
    document = require_document(loads_canonical(data, "episode plan"), "episode plan")
    require_exact_keys(document, _PLAN_KEYS, "episode plan")

    parent_episode = require_exact_int(document["parent_episode"], "parent_episode")
    ticks = require_exact_int(document["ticks"], "ticks")
    if ticks == 0:
        raise ValueError(
            "ticks must be > 0; a continuation episode must run long enough to "
            "contain its one scheduled intervention"
        )

    return EpisodePlan(
        parent_episode=parent_episode,
        ticks=ticks,
        action=_parse_intervention(document["intervention"], parent_episode + 1),
        systems=_parse_systems(document["systems"]),
    )
