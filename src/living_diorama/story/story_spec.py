"""Phase 21 emphasis policy: the closed, reviewable rule table.

Story emphasis is presentation metadata, not authoritative world truth. Nothing
in this module decides what is *true*; it decides only what downstream
presentation should pay attention to, and it does so through a finite table that
a reviewer can read in one sitting.

The tables are keyed on authoritative type names -- the render export's event
``type`` strings and memory ``fact_type`` strings. They never inspect prose. A
memory fact's ``summary`` is free-form text and is deliberately absent from every
rule here: prose may be carried through as opaque presentation text, but it may
never drive a selection decision.

A type this module does not know is never given invented semantics. It degrades
neutrally into the plan's ``unclassified`` section, carrying a reason code that
says so.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

# --------------------------------------------------------------------------
# Emphasis levels
# --------------------------------------------------------------------------

EMPHASIS_PRIMARY: Final = "PRIMARY"
EMPHASIS_SECONDARY: Final = "SECONDARY"
EMPHASIS_BACKGROUND: Final = "BACKGROUND"

EMPHASIS_LEVELS: Final = (EMPHASIS_PRIMARY, EMPHASIS_SECONDARY, EMPHASIS_BACKGROUND)
"""Every emphasis level a beat may carry, strongest first."""

EMPHASIS_ORDER: Final[Mapping[str, int]] = MappingProxyType(
    {level: index for index, level in enumerate(EMPHASIS_LEVELS)}
)
"""Sort weight per emphasis level. Lower sorts earlier."""

# --------------------------------------------------------------------------
# Beat kinds
# --------------------------------------------------------------------------

BEAT_LAW_CHANGE: Final = "LAW_CHANGE"
BEAT_LAW_RESTORATION: Final = "LAW_RESTORATION"
BEAT_WALL_RAISED: Final = "WALL_RAISED"
BEAT_WALL_STATE_CHANGE: Final = "WALL_STATE_CHANGE"
BEAT_POPULATION_MOVEMENT: Final = "POPULATION_MOVEMENT"
BEAT_DURABLE_CONSEQUENCE: Final = "DURABLE_CONSEQUENCE"
BEAT_CONSEQUENCE_PERSISTED: Final = "CONSEQUENCE_PERSISTED"
BEAT_NO_EMPHASIZED_BEATS: Final = "NO_EMPHASIZED_BEATS"

BEAT_KINDS: Final = (
    BEAT_LAW_CHANGE,
    BEAT_LAW_RESTORATION,
    BEAT_WALL_RAISED,
    BEAT_WALL_STATE_CHANGE,
    BEAT_POPULATION_MOVEMENT,
    BEAT_DURABLE_CONSEQUENCE,
    BEAT_CONSEQUENCE_PERSISTED,
    BEAT_NO_EMPHASIZED_BEATS,
)
"""Exactly the beat kinds this build emits. A plan carrying any other is refused.

``NO_EMPHASIZED_BEATS`` is a statement about this layer's output and nothing
more: it says the emphasis policy selected nothing. It must never be read as a
claim that no authoritative change occurred -- an episode can publish hundreds of
genuine telemetry events and still emphasise none of them. What the world did is
the simulation's to assert, not this layer's.
"""

# --------------------------------------------------------------------------
# Reason codes
# --------------------------------------------------------------------------

REASON_EVENT_TYPE_RULE: Final = "EVENT_TYPE_RULE"
REASON_MEMORY_FACT_NEW: Final = "MEMORY_FACT_NEW"
REASON_HIGH_FREQUENCY_TELEMETRY: Final = "HIGH_FREQUENCY_TELEMETRY"
REASON_REPEAT_SUPPRESSED: Final = "REPEAT_SUPPRESSED"
REASON_UNKNOWN_EVENT_TYPE: Final = "UNKNOWN_EVENT_TYPE"
REASON_UNKNOWN_FACT_TYPE: Final = "UNKNOWN_FACT_TYPE"
REASON_NO_BEATS_DERIVED: Final = "NO_BEATS_DERIVED"

REASON_CODES: Final = (
    REASON_EVENT_TYPE_RULE,
    REASON_MEMORY_FACT_NEW,
    REASON_HIGH_FREQUENCY_TELEMETRY,
    REASON_REPEAT_SUPPRESSED,
    REASON_UNKNOWN_EVENT_TYPE,
    REASON_UNKNOWN_FACT_TYPE,
    REASON_NO_BEATS_DERIVED,
)
"""Exactly the reason codes this build emits."""

# --------------------------------------------------------------------------
# Repeat policy
# --------------------------------------------------------------------------

POLICY_EVERY: Final = "EVERY"
POLICY_FIRST_PER_SUBJECT: Final = "FIRST_PER_SUBJECT"
REPEAT_POLICIES: Final = (POLICY_EVERY, POLICY_FIRST_PER_SUBJECT)
"""How often an event type may earn a beat.

``EVERY`` suits a type that marks a genuinely discrete decision, where a second
occurrence is a second decision. ``FIRST_PER_SUBJECT`` suits a type the engine
re-emits as a value drifts: the wall in the canonical chain publishes
``WALL_CHANGED`` twelve times in one episode as its dependency score climbs, and
a viewer needs to be told once that the wall's state is moving, not twelve
times. Later occurrences are counted and reported, never silently dropped.
"""

# --------------------------------------------------------------------------
# The event rule table
# --------------------------------------------------------------------------

EVENT_BEAT_RULES: Final[Mapping[str, tuple[str, str, str]]] = MappingProxyType(
    {
        "LAW_CHANGED": (BEAT_LAW_CHANGE, EMPHASIS_PRIMARY, POLICY_EVERY),
        "LAW_RESTORED": (BEAT_LAW_RESTORATION, EMPHASIS_PRIMARY, POLICY_EVERY),
        "WALL_BUILT": (BEAT_WALL_RAISED, EMPHASIS_PRIMARY, POLICY_EVERY),
        "WALL_CHANGED": (
            BEAT_WALL_STATE_CHANGE,
            EMPHASIS_SECONDARY,
            POLICY_FIRST_PER_SUBJECT,
        ),
        "POPULATION_MIGRATED": (
            BEAT_POPULATION_MOVEMENT,
            EMPHASIS_SECONDARY,
            POLICY_FIRST_PER_SUBJECT,
        ),
    }
)
"""Event types that earn a beat, mapped to (beat kind, emphasis, repeat policy).

An event type earns a beat when it marks a discrete decision or a change of
institutional fact -- something a viewer could be shown once and understand.
"""

EVENT_EXCLUSIONS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "RESOURCE_PRODUCED": REASON_HIGH_FREQUENCY_TELEMETRY,
        "RESOURCE_CONSUMED": REASON_HIGH_FREQUENCY_TELEMETRY,
        "RESOURCE_TRANSFERRED": REASON_HIGH_FREQUENCY_TELEMETRY,
        "SCARCITY_CHANGED": REASON_HIGH_FREQUENCY_TELEMETRY,
        "SOCIAL_STABILITY_CHANGED": REASON_HIGH_FREQUENCY_TELEMETRY,
        "INSTITUTIONAL_PRESSURE_CHANGED": REASON_HIGH_FREQUENCY_TELEMETRY,
        "INFRASTRUCTURE_ADAPTED": REASON_HIGH_FREQUENCY_TELEMETRY,
    }
)
"""Known event types that deliberately earn no beat, with the reason.

These fire every tick for every district. They are the world's telemetry, not
its story. They are excluded explicitly and counted in the plan, never silently
dropped -- a reviewer can see exactly how much was set aside and why.
"""

# --------------------------------------------------------------------------
# The memory fact rule table
# --------------------------------------------------------------------------

FACT_BEAT_RULES: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        "WALL_BUILT": (BEAT_DURABLE_CONSEQUENCE, EMPHASIS_PRIMARY),
        "LAW_RESTORED_WALL_PERSISTED": (BEAT_CONSEQUENCE_PERSISTED, EMPHASIS_PRIMARY),
    }
)
"""Durable memory fact types that earn a beat, mapped to (beat kind, emphasis).

A durable fact is the strongest evidence the engine offers: a claim it will
still be repeating many episodes later. Facts outrank events, and when a fact
names the event it came from, that event is absorbed into the fact's beat rather
than emitting a second, weaker beat about the same moment.
"""

# --------------------------------------------------------------------------
# Vocabulary the tables are defined against
# --------------------------------------------------------------------------

BEAT_REASON_CODES: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        BEAT_LAW_CHANGE: frozenset({REASON_EVENT_TYPE_RULE}),
        BEAT_LAW_RESTORATION: frozenset({REASON_EVENT_TYPE_RULE}),
        BEAT_WALL_RAISED: frozenset({REASON_EVENT_TYPE_RULE}),
        BEAT_WALL_STATE_CHANGE: frozenset({REASON_EVENT_TYPE_RULE}),
        BEAT_POPULATION_MOVEMENT: frozenset({REASON_EVENT_TYPE_RULE}),
        BEAT_DURABLE_CONSEQUENCE: frozenset({REASON_MEMORY_FACT_NEW}),
        BEAT_CONSEQUENCE_PERSISTED: frozenset({REASON_MEMORY_FACT_NEW}),
        BEAT_NO_EMPHASIZED_BEATS: frozenset({REASON_NO_BEATS_DERIVED}),
    }
)
"""The reason codes each beat kind may carry.

A beat kind names where the beat came from, so its reason code is not a free
label: an event-derived beat cannot honestly claim it came from a memory fact.
Checking only that the string appears somewhere in the vocabulary would let a
plan describe an origin it does not have.
"""

BEAT_EMPHASIS_LEVELS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        BEAT_LAW_CHANGE: frozenset({EMPHASIS_PRIMARY}),
        BEAT_LAW_RESTORATION: frozenset({EMPHASIS_PRIMARY}),
        BEAT_WALL_RAISED: frozenset({EMPHASIS_PRIMARY}),
        BEAT_WALL_STATE_CHANGE: frozenset({EMPHASIS_SECONDARY}),
        BEAT_POPULATION_MOVEMENT: frozenset({EMPHASIS_SECONDARY}),
        BEAT_DURABLE_CONSEQUENCE: frozenset({EMPHASIS_PRIMARY}),
        BEAT_CONSEQUENCE_PERSISTED: frozenset({EMPHASIS_PRIMARY}),
        BEAT_NO_EMPHASIZED_BEATS: frozenset({EMPHASIS_BACKGROUND}),
    }
)
"""The emphasis each beat kind may carry, fixed by the same rule tables."""


FACT_SOURCE_EVENT_TYPES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "WALL_BUILT": "WALL_BUILT",
        "LAW_RESTORED_WALL_PERSISTED": "LAW_RESTORED",
    }
)
"""The event type each known fact type must have been derived from.

Restated from the engine's memory contract rather than imported, because the
story layer may not reach into ``living_diorama.memory``. A test asserts this
mapping still agrees with the engine's own.
"""

BEAT_EVENT_TYPES: Final[Mapping[str, str]] = MappingProxyType(
    {kind: event_type for event_type, (kind, _e, _p) in EVENT_BEAT_RULES.items()}
)
"""The event type an event-derived beat kind must cite. The rule table, inverted."""

BEAT_FACT_TYPES: Final[Mapping[str, str]] = MappingProxyType(
    {kind: fact_type for fact_type, (kind, _e) in FACT_BEAT_RULES.items()}
)
"""The fact type a memory-derived beat kind must cite. The rule table, inverted."""


def allowed_exclusion_reasons(event_type: str) -> frozenset[str]:
    """Return the reasons this policy could give for excluding an event type.

    A type the policy promotes can only be excluded as a suppressed repeat, and
    only if its repeat policy allows repeats to be suppressed. A type the policy
    sets aside can only carry that type's declared reason. Anything else is a
    combination this build cannot produce.
    """
    rule = EVENT_BEAT_RULES.get(event_type)
    if rule is not None:
        _kind, _emphasis, policy = rule
        if policy == POLICY_FIRST_PER_SUBJECT:
            return frozenset({REASON_REPEAT_SUPPRESSED})
        return frozenset()
    declared = EVENT_EXCLUSIONS.get(event_type)
    if declared is not None:
        return frozenset({declared})
    return frozenset()


KNOWN_EVENT_TYPES: Final = tuple(sorted(set(EVENT_BEAT_RULES) | set(EVENT_EXCLUSIONS)))
"""Every event type this build has an explicit opinion about."""

KNOWN_FACT_TYPES: Final = tuple(sorted(FACT_BEAT_RULES))
"""Every memory fact type this build has an explicit opinion about."""


def classify_event(event_type: str) -> tuple[str, str, str, str] | None:
    """Return (beat kind, emphasis, reason code, repeat policy), or None.

    None means the type earns no beat. Callers must distinguish the two reasons
    for that using :func:`event_exclusion_reason`: a known type deliberately set
    aside, or an unknown type degrading neutrally.
    """
    rule = EVENT_BEAT_RULES.get(event_type)
    if rule is None:
        return None
    kind, emphasis, policy = rule
    return kind, emphasis, REASON_EVENT_TYPE_RULE, policy


def event_exclusion_reason(event_type: str) -> str:
    """Return why an event type earns no beat.

    A type named in :data:`EVENT_EXCLUSIONS` returns its declared reason. Any
    other unrecognised type returns :data:`REASON_UNKNOWN_EVENT_TYPE` -- it is
    never given a guessed meaning.
    """
    return EVENT_EXCLUSIONS.get(event_type, REASON_UNKNOWN_EVENT_TYPE)


def classify_fact(fact_type: str) -> tuple[str, str, str] | None:
    """Return (beat kind, emphasis, reason code) for a fact type, or None.

    None means the fact type is unknown to this build. It degrades neutrally
    into the plan's unclassified section rather than receiving invented
    semantics.
    """
    rule = FACT_BEAT_RULES.get(fact_type)
    if rule is None:
        return None
    kind, emphasis = rule
    return kind, emphasis, REASON_MEMORY_FACT_NEW
