"""Render Export V1 schema contract: exact shape, exact types, no repair.

Every test starts from a genuinely valid document produced by the real
exporter over a real published episode, then breaks exactly one thing and
asserts the validator refuses it. A validator that cannot fail is not a
contract, so every mutation here is proven to be caught.
"""

import pytest

from living_diorama.render import (
    RENDER_EXPORT_FORMAT,
    RENDER_SCHEMA_VERSION,
    build_render_export_document,
    validate_render_export,
)
from persistence.conftest import temporary_save_root
from render.conftest import publish_calm_episode_zero, publish_scar_chain


def calm_document() -> dict[str, object]:
    """Return a fresh valid export document for a real episode 0."""
    with temporary_save_root() as root:
        publish_calm_episode_zero(root)
        return build_render_export_document(root, 0)


def scar_child_document() -> dict[str, object]:
    """Return a fresh valid export document for a real continued episode 1."""
    with temporary_save_root() as root:
        publish_scar_chain(root)
        return build_render_export_document(root, 1)


class TestTopLevelShape:
    """Exactly six top-level keys, exactly identified."""

    def test_valid_document_passes_and_is_returned(self) -> None:
        """The exporter's own output satisfies the contract."""
        document = calm_document()
        assert validate_render_export(document) is document

    def test_exactly_six_top_level_keys(self) -> None:
        """The valid document carries exactly the six contract keys."""
        document = calm_document()
        assert set(document) == {
            "events",
            "format",
            "memory",
            "schema_version",
            "source",
            "world",
        }

    def test_extra_top_level_key_is_rejected(self) -> None:
        """An unknown top-level key is refused, never ignored."""
        document = calm_document()
        document["camera"] = {}
        with pytest.raises(ValueError, match=r"unexpected keys: \['camera'\]"):
            validate_render_export(document)

    def test_missing_top_level_key_is_rejected(self) -> None:
        """An incomplete document is refused, never defaulted."""
        document = calm_document()
        del document["memory"]
        with pytest.raises(ValueError, match=r"missing required keys: \['memory'\]"):
            validate_render_export(document)

    def test_format_must_be_exact(self) -> None:
        """Only the render export format tag is accepted."""
        document = calm_document()
        document["format"] = "living_diorama_episode"
        with pytest.raises(ValueError, match="format must be 'living_diorama_render_export'"):
            validate_render_export(document)

    def test_format_must_be_a_string(self) -> None:
        """A non-string format tag is a type error, not a comparison miss."""
        document = calm_document()
        document["format"] = 1
        with pytest.raises(TypeError, match="format must be a str, got int"):
            validate_render_export(document)

    def test_schema_version_must_be_exactly_one(self) -> None:
        """An unknown render schema version is refused, never migrated."""
        document = calm_document()
        document["schema_version"] = 2
        with pytest.raises(ValueError, match="unsupported schema version 2"):
            validate_render_export(document)

    def test_schema_version_bool_is_rejected(self) -> None:
        """``True`` is not version 1; bool is refused outright."""
        document = calm_document()
        document["schema_version"] = True
        with pytest.raises(TypeError, match="schema_version must be an int, got bool"):
            validate_render_export(document)

    def test_document_must_be_an_object(self) -> None:
        """A render export is a JSON object, not an array or scalar."""
        with pytest.raises(TypeError, match="render export must be a JSON object"):
            validate_render_export([1, 2, 3])


class TestSourceSection:
    """Provenance is exact: keys, integer discipline, hash form, lineage."""

    def test_source_has_exactly_the_approved_keys(self) -> None:
        """The source section carries exactly its seven keys."""
        document = calm_document()
        source = document["source"]
        assert isinstance(source, dict)
        assert set(source) == {
            "engine_version",
            "entity_counts",
            "episode",
            "event_count",
            "parent_state_hash",
            "state_hash",
            "tick",
        }

    def test_extra_source_key_is_rejected(self) -> None:
        """No provenance key beyond the contract is accepted."""
        document = calm_document()
        source = document["source"]
        assert isinstance(source, dict)
        source["exported_at"] = "2026-08-08"
        with pytest.raises(ValueError, match=r"unexpected keys: \['exported_at'\]"):
            validate_render_export(document)

    def test_source_episode_bool_is_rejected(self) -> None:
        """``True`` is not episode 1; bool is refused for every exact int."""
        document = calm_document()
        source = document["source"]
        assert isinstance(source, dict)
        source["episode"] = True
        with pytest.raises(TypeError, match="episode must be an int, got bool"):
            validate_render_export(document)

    def test_event_count_bool_is_rejected(self) -> None:
        """``False`` is not zero events."""
        document = calm_document()
        source = document["source"]
        assert isinstance(source, dict)
        source["event_count"] = False
        with pytest.raises(TypeError, match="event_count must be an int, got bool"):
            validate_render_export(document)

    def test_state_hash_must_have_canonical_form(self) -> None:
        """A state hash is 64 lowercase hex characters, nothing else."""
        document = calm_document()
        source = document["source"]
        assert isinstance(source, dict)
        state_hash = source["state_hash"]
        assert isinstance(state_hash, str)
        source["state_hash"] = state_hash.upper()
        with pytest.raises(ValueError, match="64 lowercase hexadecimal"):
            validate_render_export(document)

    def test_episode_zero_parent_hash_must_be_null(self) -> None:
        """Episode 0 begins the lineage; it records no parent."""
        document = calm_document()
        source = document["source"]
        assert isinstance(source, dict)
        source["parent_state_hash"] = "a" * 64
        with pytest.raises(ValueError, match="episode 0 must record a null parent_state_hash"):
            validate_render_export(document)

    def test_later_episode_parent_hash_must_not_be_null(self) -> None:
        """A continued episode must name the parent it descends from."""
        document = scar_child_document()
        source = document["source"]
        assert isinstance(source, dict)
        source["parent_state_hash"] = None
        with pytest.raises(ValueError, match="must record its parent state hash"):
            validate_render_export(document)

    def test_malformed_parent_hash_is_rejected(self) -> None:
        """A parent hash is null or canonical hex; nothing in between."""
        document = scar_child_document()
        source = document["source"]
        assert isinstance(source, dict)
        source["parent_state_hash"] = "not-a-hash"
        with pytest.raises(ValueError, match="64 lowercase hexadecimal"):
            validate_render_export(document)

    def test_engine_version_must_not_be_blank(self) -> None:
        """The source engine version is real provenance, not padding."""
        document = calm_document()
        source = document["source"]
        assert isinstance(source, dict)
        source["engine_version"] = "   "
        with pytest.raises(ValueError):
            validate_render_export(document)


class TestInternalAgreements:
    """The document's sections must agree with each other."""

    def test_event_count_must_equal_events_length(self) -> None:
        """A count that disagrees with the history is refused."""
        document = scar_child_document()
        source = document["source"]
        assert isinstance(source, dict)
        assert isinstance(source["event_count"], int)
        source["event_count"] = source["event_count"] + 1
        with pytest.raises(ValueError, match="but the events section holds"):
            validate_render_export(document)

    def test_entity_counts_must_equal_world_arrays(self) -> None:
        """Every per-kind count must match its exported array."""
        document = calm_document()
        source = document["source"]
        assert isinstance(source, dict)
        entity_counts = source["entity_counts"]
        assert isinstance(entity_counts, dict)
        entity_counts["districts"] = entity_counts["districts"] + 1
        with pytest.raises(ValueError, match="districts but the world section holds"):
            validate_render_export(document)

    def test_entity_counts_keys_are_exact(self) -> None:
        """The count object carries exactly the five entity kinds."""
        document = calm_document()
        source = document["source"]
        assert isinstance(source, dict)
        entity_counts = source["entity_counts"]
        assert isinstance(entity_counts, dict)
        entity_counts["cameras"] = 0
        with pytest.raises(ValueError, match=r"unexpected keys: \['cameras'\]"):
            validate_render_export(document)

    def test_memory_checkpoint_must_match_source_episode(self) -> None:
        """The memory must describe exactly the exported episode."""
        document = calm_document()
        memory = document["memory"]
        assert isinstance(memory, dict)
        assert isinstance(memory["through_episode"], int)
        memory["through_episode"] = memory["through_episode"] + 1
        with pytest.raises(ValueError, match="through episode .* but the source episode"):
            validate_render_export(document)

    def test_memory_checkpoint_must_match_source_tick(self) -> None:
        """The memory must describe exactly the exported moment."""
        document = calm_document()
        memory = document["memory"]
        assert isinstance(memory, dict)
        assert isinstance(memory["through_tick"], int)
        memory["through_tick"] = memory["through_tick"] + 1
        with pytest.raises(ValueError, match="through tick .* but the source tick"):
            validate_render_export(document)

    def test_memory_through_tick_bool_is_rejected(self) -> None:
        """``True`` is not tick 1, in memory as everywhere."""
        document = calm_document()
        memory = document["memory"]
        assert isinstance(memory, dict)
        memory["through_tick"] = True
        with pytest.raises(TypeError, match="through_tick must be an int, got bool"):
            validate_render_export(document)


class TestSectionShapes:
    """World, events, and memory carry exactly their contracted shapes."""

    def test_world_has_exactly_the_five_entity_arrays(self) -> None:
        """The world section is the five arrays and nothing else."""
        document = calm_document()
        world = document["world"]
        assert isinstance(world, dict)
        assert set(world) == {"boundaries", "districts", "infrastructure", "laws", "walls"}

    def test_extra_world_key_is_rejected(self) -> None:
        """Continuation internals cannot ride along in the world section."""
        document = calm_document()
        world = document["world"]
        assert isinstance(world, dict)
        world["rng_state"] = {}
        with pytest.raises(ValueError, match=r"unexpected keys: \['rng_state'\]"):
            validate_render_export(document)

    def test_world_array_must_be_a_list(self) -> None:
        """An entity collection is an array, never an object."""
        document = calm_document()
        world = document["world"]
        assert isinstance(world, dict)
        world["districts"] = {}
        with pytest.raises(TypeError, match="districts must be a JSON array, got dict"):
            validate_render_export(document)

    def test_events_must_be_a_list(self) -> None:
        """History is an ordered array, never an object."""
        document = calm_document()
        document["events"] = {}
        with pytest.raises(TypeError, match="events must be a JSON array, got dict"):
            validate_render_export(document)

    def test_memory_has_exactly_three_keys(self) -> None:
        """The memory section is checkpoint plus facts and nothing else."""
        document = calm_document()
        memory = document["memory"]
        assert isinstance(memory, dict)
        assert set(memory) == {"facts", "through_episode", "through_tick"}

    def test_memory_facts_must_be_a_list(self) -> None:
        """The fact history is an ordered array, never an object."""
        document = calm_document()
        memory = document["memory"]
        assert isinstance(memory, dict)
        memory["facts"] = {}
        with pytest.raises(TypeError, match="facts must be a JSON array, got dict"):
            validate_render_export(document)

    def test_extra_memory_key_is_rejected(self) -> None:
        """No narrative extras may enter the memory section."""
        document = calm_document()
        memory = document["memory"]
        assert isinstance(memory, dict)
        memory["summary"] = "the world remembers"
        with pytest.raises(ValueError, match=r"unexpected keys: \['summary'\]"):
            validate_render_export(document)


class TestConstants:
    """The exported constants say exactly what the contract says."""

    def test_format_constant(self) -> None:
        """The format tag is the render export tag, not the save format."""
        assert RENDER_EXPORT_FORMAT == "living_diorama_render_export"

    def test_schema_version_constant(self) -> None:
        """The render schema version is the exact integer one."""
        assert RENDER_SCHEMA_VERSION == 1
        assert type(RENDER_SCHEMA_VERSION) is int
