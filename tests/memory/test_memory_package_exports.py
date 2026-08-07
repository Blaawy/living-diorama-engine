"""Tests for the memory package's public surface."""

import inspect

import pytest

import living_diorama.memory as memory
from living_diorama.memory import (
    MemoryFact,
    MemoryFactType,
    MemoryQuery,
    MemorySignificance,
    WorldMemory,
)

EXPECTED_EXPORTS = [
    "MemoryFact",
    "MemoryFactType",
    "MemoryQuery",
    "MemorySignificance",
    "WorldMemory",
]
"""The intended public surface, listed here so a change has to be deliberate."""

INTERNAL_NAMES = ["SIGNIFICANT_EVENT_TYPES", "validate_memory_transition"]
"""Names that enforce the rules and are therefore not offered as choices."""


def test_the_documented_names_import() -> None:
    """The five names the phase contract promises."""
    assert MemoryFact is not None
    assert MemoryFactType is not None
    assert MemoryQuery is not None
    assert MemorySignificance is not None
    assert WorldMemory is not None


def test_the_public_surface_is_exactly_as_declared() -> None:
    """An accidental export is as much a defect as a missing one."""
    assert sorted(memory.__all__) == sorted(EXPECTED_EXPORTS)
    for name in EXPECTED_EXPORTS:
        assert hasattr(memory, name), name


def test_no_private_helper_is_exported() -> None:
    """Freezing helpers and identifier builders stay internal."""
    assert not any(name.startswith("_") for name in memory.__all__)
    for name in ("_freeze", "_thaw", "_compact_json", "_quote", "_named_member"):
        assert name not in memory.__all__
        assert not hasattr(memory, name)


@pytest.mark.parametrize("name", INTERNAL_NAMES)
def test_enforcement_machinery_is_not_part_of_the_public_surface(name: str) -> None:
    """The rules are enforced, not offered.

    A caller does not choose which events are significant, and does not decide
    whether to validate a transition. Exporting either would invite dependence on
    internals that exist in order to change.
    """
    assert name not in memory.__all__
    assert not hasattr(memory, name)


def test_the_enforcement_machinery_still_exists_privately() -> None:
    """Persistence reaches it by its private path, which stays available."""
    from living_diorama.memory import _integrity  # noqa: PLC0415

    assert callable(_integrity.validate_memory_transition)
    assert callable(_integrity.validate_memory_transition_events)
    assert isinstance(_integrity.SIGNIFICANT_EVENT_TYPES, frozenset)


@pytest.mark.parametrize(
    "name", ["validate_memory_transition", "validate_memory_transition_events"]
)
def test_neither_transition_entry_point_is_exported(name: str) -> None:
    """The snapshot-based path is machinery too, and stays private."""
    assert name not in memory.__all__
    assert not hasattr(memory, name)


def test_persistence_reaches_the_validator_through_the_private_module() -> None:
    """Read from the source, so a re-export cannot creep back in unnoticed."""
    import ast  # noqa: PLC0415
    import pathlib  # noqa: PLC0415

    path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src"
        / "living_diorama"
        / "persistence"
        / "save_manager.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    sources = {
        node.module: {alias.name for alias in node.names}
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "validate_memory_transition_events" in sources["living_diorama.memory._integrity"]
    assert not sources.get("living_diorama.memory", set()) & {
        "validate_memory_transition",
        "validate_memory_transition_events",
    }


def test_the_fact_vocabulary_is_exactly_the_two_mvp_types() -> None:
    """Widening it has to be a deliberate act, not an accident."""
    assert [member.value for member in MemoryFactType] == [
        "WALL_BUILT",
        "LAW_RESTORED_WALL_PERSISTED",
    ]


def test_the_distillation_entry_point_has_the_agreed_signature() -> None:
    """Keyword-only, so a caller cannot silently transpose world and log."""
    signature = inspect.signature(MemorySignificance.distill_episode)
    assert list(signature.parameters) == ["self", "world", "event_log", "previous_memory"]
    for name in ("world", "event_log", "previous_memory"):
        assert signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY


def test_the_query_api_offers_every_documented_filter() -> None:
    """Each filter the contract promises is available and keyword-only."""
    facts = inspect.signature(MemoryQuery.facts)
    assert list(facts.parameters) == [
        "self",
        "fact_type",
        "episode",
        "tick_start",
        "tick_end",
        "source_event_type",
        "source_id",
        "subject_id",
    ]
    narration = inspect.signature(MemoryQuery.narration_context)
    assert list(narration.parameters) == ["self", "limit", "fact_type", "subject_id"]


def test_memory_exposes_no_mutable_internal_collection() -> None:
    """Everything handed out is a tuple or a read-only mapping."""
    from memory.conftest import wall_built_fact  # noqa: PLC0415

    stored = WorldMemory.empty().advance(episode=0, tick=120, new_facts=(wall_built_fact(),))
    assert isinstance(stored.facts, tuple)
    with pytest.raises(TypeError):
        stored.facts[0].details["wall_id"] = "other"  # type: ignore[index]


def test_every_public_symbol_is_documented() -> None:
    """A public name without a docstring is a name nobody has to explain."""
    for name in memory.__all__:
        symbol = getattr(memory, name)
        if inspect.isclass(symbol) or inspect.isfunction(symbol):
            assert inspect.getdoc(symbol), name


def test_the_package_module_documents_its_dependency_direction() -> None:
    """The load-bearing architectural rule is stated where it is enforced."""
    documentation = inspect.getdoc(memory)
    assert documentation
    assert "persistence" in documentation.lower()
