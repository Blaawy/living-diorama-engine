"""The emphasis policy is a closed, finite, reviewable table.

These tests guard the property that makes Phase 21 auditable: every decision it
makes comes from a table small enough to read, defined against a vocabulary the
engine actually emits, with no gaps and no overlaps.
"""

from living_diorama.events.event import EventType
from living_diorama.memory.world_memory import MemoryFactType
from living_diorama.story import story_spec

# ---------------------------------------------------------------- vocabulary


def test_every_event_rule_names_a_type_the_engine_can_actually_emit() -> None:
    """A rule for a type the engine never emits is dead policy."""
    engine = {member.value for member in EventType}
    for event_type in story_spec.EVENT_BEAT_RULES:
        assert event_type in engine, f"{event_type} is not an engine event type"


def test_every_event_exclusion_names_a_type_the_engine_can_actually_emit() -> None:
    """The same applies to a type deliberately set aside."""
    engine = {member.value for member in EventType}
    for event_type in story_spec.EVENT_EXCLUSIONS:
        assert event_type in engine, f"{event_type} is not an engine event type"


def test_every_fact_rule_names_a_type_the_engine_can_actually_remember() -> None:
    """Every fact rule names a type the engine can actually remember."""
    engine = {member.value for member in MemoryFactType}
    for fact_type in story_spec.FACT_BEAT_RULES:
        assert fact_type in engine, f"{fact_type} is not an engine memory fact type"


def test_the_event_table_has_an_opinion_about_every_engine_event_type() -> None:
    """No engine event type may fall through to the unknown path unnoticed.

    An unknown type still degrades neutrally at runtime, but a type this build
    ships alongside should have been considered explicitly.
    """
    engine = {member.value for member in EventType}
    covered = set(story_spec.EVENT_BEAT_RULES) | set(story_spec.EVENT_EXCLUSIONS)
    assert engine - covered == set(), f"no policy for: {sorted(engine - covered)}"


def test_the_fact_table_has_an_opinion_about_every_engine_fact_type() -> None:
    """The fact table has an opinion about every engine fact type."""
    engine = {member.value for member in MemoryFactType}
    assert engine - set(story_spec.FACT_BEAT_RULES) == set()


def test_a_type_is_never_both_promoted_and_excluded() -> None:
    """Overlap would make the outcome depend on lookup order."""
    overlap = set(story_spec.EVENT_BEAT_RULES) & set(story_spec.EVENT_EXCLUSIONS)
    assert overlap == set(), f"both promoted and excluded: {sorted(overlap)}"


# ------------------------------------------------------------ table integrity


def test_every_event_rule_uses_declared_vocabulary() -> None:
    """Every event rule uses declared vocabulary."""
    for event_type, (kind, emphasis, policy) in story_spec.EVENT_BEAT_RULES.items():
        assert kind in story_spec.BEAT_KINDS, event_type
        assert emphasis in story_spec.EMPHASIS_LEVELS, event_type
        assert policy in story_spec.REPEAT_POLICIES, event_type


def test_every_fact_rule_uses_declared_vocabulary() -> None:
    """Every fact rule uses declared vocabulary."""
    for fact_type, (kind, emphasis) in story_spec.FACT_BEAT_RULES.items():
        assert kind in story_spec.BEAT_KINDS, fact_type
        assert emphasis in story_spec.EMPHASIS_LEVELS, fact_type


def test_every_exclusion_names_a_declared_reason_code() -> None:
    """Every exclusion names a declared reason code."""
    for event_type, reason in story_spec.EVENT_EXCLUSIONS.items():
        assert reason in story_spec.REASON_CODES, event_type


def test_emphasis_order_covers_every_level_and_is_strongest_first() -> None:
    """Emphasis order covers every level and is strongest first."""
    assert set(story_spec.EMPHASIS_ORDER) == set(story_spec.EMPHASIS_LEVELS)
    weights = [story_spec.EMPHASIS_ORDER[level] for level in story_spec.EMPHASIS_LEVELS]
    assert weights == sorted(weights)
    assert story_spec.EMPHASIS_ORDER[story_spec.EMPHASIS_PRIMARY] == 0


def test_the_declared_vocabularies_have_no_duplicates() -> None:
    """The declared vocabularies have no duplicates."""
    for vocabulary in (
        story_spec.BEAT_KINDS,
        story_spec.EMPHASIS_LEVELS,
        story_spec.REASON_CODES,
        story_spec.REPEAT_POLICIES,
    ):
        assert len(set(vocabulary)) == len(vocabulary), vocabulary


def test_the_tables_are_read_only() -> None:
    """A mutable policy table is a policy that can drift at runtime."""
    for table in (
        story_spec.EVENT_BEAT_RULES,
        story_spec.EVENT_EXCLUSIONS,
        story_spec.FACT_BEAT_RULES,
        story_spec.EMPHASIS_ORDER,
    ):
        assert not hasattr(table, "__setitem__") or type(table).__name__ == "mappingproxy"


# -------------------------------------------------------------- classification


def test_a_promoted_event_type_classifies_with_the_event_type_rule_reason() -> None:
    """A promoted event type classifies with the event type rule reason."""
    result = story_spec.classify_event("LAW_CHANGED")
    assert result is not None
    kind, emphasis, reason, policy = result
    assert kind == story_spec.BEAT_LAW_CHANGE
    assert emphasis == story_spec.EMPHASIS_PRIMARY
    assert reason == story_spec.REASON_EVENT_TYPE_RULE
    assert policy == story_spec.POLICY_EVERY


def test_an_excluded_event_type_classifies_as_no_beat_with_its_declared_reason() -> None:
    """An excluded event type classifies as no beat with its declared reason."""
    assert story_spec.classify_event("SCARCITY_CHANGED") is None
    assert (
        story_spec.event_exclusion_reason("SCARCITY_CHANGED")
        == story_spec.REASON_HIGH_FREQUENCY_TELEMETRY
    )


def test_an_unknown_event_type_degrades_neutrally_rather_than_being_guessed() -> None:
    """The one property that keeps a future event type from being misread."""
    assert story_spec.classify_event("CITIZEN_MARRIED") is None
    assert (
        story_spec.event_exclusion_reason("CITIZEN_MARRIED") == story_spec.REASON_UNKNOWN_EVENT_TYPE
    )


def test_an_unknown_fact_type_degrades_neutrally() -> None:
    """An unknown fact type degrades neutrally."""
    assert story_spec.classify_fact("CITIZEN_REMEMBERED") is None


def test_the_persistence_fact_type_earns_its_own_distinct_beat_kind() -> None:
    """The difference between 'nothing happened' and 'it is still standing'."""
    result = story_spec.classify_fact("LAW_RESTORED_WALL_PERSISTED")
    assert result is not None
    kind, emphasis, reason = result
    assert kind == story_spec.BEAT_CONSEQUENCE_PERSISTED
    assert kind != story_spec.BEAT_NO_EMPHASIZED_BEATS
    assert emphasis == story_spec.EMPHASIS_PRIMARY
    assert reason == story_spec.REASON_MEMORY_FACT_NEW


def test_no_rule_is_keyed_on_prose() -> None:
    """Selection must never depend on a summary string.

    The rule tables are keyed on type names only. If a key ever contained a
    space, it would no longer be a type name.
    """
    for table in (
        story_spec.EVENT_BEAT_RULES,
        story_spec.EVENT_EXCLUSIONS,
        story_spec.FACT_BEAT_RULES,
    ):
        for key in table:
            assert key == key.upper(), key
            assert " " not in key, key
