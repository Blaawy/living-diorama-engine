"""Two exports must be proven consecutive before a transition may be described.

A story plan that spans a transition asserts that this episode followed that one.
These tests are the negative controls for that assertion: every way a pair can
fail to be consecutive canonical history must be refused, never repaired.
"""

import copy
from typing import Any

import pytest

from living_diorama.story import (
    build_episode_story_plan_document,
    require_consecutive_exports,
    require_memory_progression,
)

# ------------------------------------------------------------------- positive


def test_a_genuine_consecutive_pair_is_accepted(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """A genuine consecutive pair is accepted."""
    previous, current = require_consecutive_exports(export_ep1, export_ep2)
    assert previous["source"]["episode"] == 1
    assert current["source"]["episode"] == 2


# ------------------------------------------------------------------- ordering


def test_a_reversed_pair_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Argument order is not evidence; the provenance is."""
    with pytest.raises(ValueError, match="not consecutive"):
        require_consecutive_exports(export_ep2, export_ep1)


def test_a_reversed_pair_is_refused_by_the_planner_too(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """A reversed pair is refused by the planner too."""
    with pytest.raises(ValueError):
        build_episode_story_plan_document(export_ep1, export_ep2)


def test_a_non_consecutive_pair_is_refused(
    export_ep0: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Episode 0 to episode 2 skips the episode that did the damage."""
    with pytest.raises(ValueError, match="not consecutive"):
        require_consecutive_exports(export_ep0, export_ep2)


def test_the_same_export_twice_is_refused(export_ep1: dict[str, Any]) -> None:
    """The same export twice is refused."""
    with pytest.raises(ValueError, match="not consecutive"):
        require_consecutive_exports(export_ep1, copy.deepcopy(export_ep1))


# ------------------------------------------------------------------- lineage


def test_a_broken_parent_state_hash_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Consecutive numbering is not enough; the chain must actually join."""
    export_ep2["source"]["parent_state_hash"] = "0" * 64
    with pytest.raises(ValueError, match="not the same line of history"):
        require_consecutive_exports(export_ep1, export_ep2)


def test_a_pair_from_two_different_runs_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Filenames would say these belong together. The hashes say otherwise."""
    export_ep1["source"]["state_hash"] = "f" * 64
    with pytest.raises(ValueError, match="not the same line of history"):
        require_consecutive_exports(export_ep1, export_ep2)


def test_a_backwards_memory_checkpoint_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """A backwards memory checkpoint is refused."""
    export_ep2["memory"]["through_episode"] = 0
    with pytest.raises((ValueError, TypeError)):
        require_consecutive_exports(export_ep1, export_ep2)


def test_a_changed_district_set_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Two exports of different worlds are not a transition."""
    export_ep2["world"]["districts"] = export_ep2["world"]["districts"][:-1]
    export_ep2["source"]["entity_counts"]["districts"] = len(
        export_ep2["world"]["districts"]
    )
    with pytest.raises(ValueError, match="world identity changed"):
        require_consecutive_exports(export_ep1, export_ep2)


def test_a_malformed_export_is_refused_before_any_lineage_check(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """A malformed export is refused before any lineage check."""
    del export_ep2["source"]["state_hash"]
    with pytest.raises((ValueError, TypeError)):
        require_consecutive_exports(export_ep1, export_ep2)


# ------------------------------------------------------- memory monotonicity


def test_new_facts_are_the_suffix_after_the_previous_episode(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """New facts are the suffix after the previous episode."""
    previous = export_ep1["memory"]["facts"]
    current = export_ep2["memory"]["facts"]
    new_facts = require_memory_progression(previous, current)
    assert len(new_facts) == len(current) - len(previous)
    assert new_facts[0]["fact_type"] == "LAW_RESTORED_WALL_PERSISTED"


def test_memory_that_shrank_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """A world that forgot is not two consecutive states of one world."""
    with pytest.raises(ValueError, match="shrank"):
        require_memory_progression(
            export_ep2["memory"]["facts"], export_ep1["memory"]["facts"]
        )


def test_a_disappearing_historical_fact_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """A disappearing historical fact is refused."""
    previous = export_ep1["memory"]["facts"]
    current = copy.deepcopy(export_ep2["memory"]["facts"])
    del current[0]
    with pytest.raises(ValueError, match="shrank|changed"):
        require_memory_progression(previous, current)


def test_a_mutated_historical_fact_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Remembered history is never rewritten, not even in one field."""
    previous = export_ep1["memory"]["facts"]
    current = copy.deepcopy(export_ep2["memory"]["facts"])
    current[0]["details"]["built_tick"] = 999
    with pytest.raises(ValueError, match="changed between"):
        require_memory_progression(previous, current)


def test_a_reordered_history_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """A reordered history is refused."""
    previous = export_ep1["memory"]["facts"]
    current = copy.deepcopy(export_ep2["memory"]["facts"])
    current.reverse()
    with pytest.raises(ValueError, match="changed between"):
        require_memory_progression(previous, current)


def test_a_repeated_fact_id_is_refused(export_ep2: dict[str, Any]) -> None:
    """A repeated fact id is refused."""
    current = copy.deepcopy(export_ep2["memory"]["facts"])
    current.append(copy.deepcopy(current[0]))
    with pytest.raises(ValueError, match="repeats fact_id"):
        require_memory_progression([], current)


def test_the_planner_refuses_a_pair_whose_memory_went_backwards(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """The planner refuses a pair whose memory went backwards."""
    export_ep2["memory"]["facts"] = []
    export_ep2["memory"]["through_episode"] = 2
    with pytest.raises((ValueError, TypeError)):
        build_episode_story_plan_document(export_ep2, export_ep1)


# ------------------------------------------- world identity: refuse, never repair


def duplicate_first(export: dict[str, Any], array: str) -> None:
    """Replace the second entry with a copy of the first, keeping the length."""
    entries = export["world"][array]
    entries[1] = copy.deepcopy(entries[0])


def test_duplicate_district_ids_are_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Reported: duplicates collapsed into a set and compared equal."""
    duplicate_first(export_ep1, "districts")
    duplicate_first(export_ep2, "districts")
    with pytest.raises(ValueError, match="more than once"):
        require_consecutive_exports(export_ep1, export_ep2)


def test_duplicate_boundary_ids_are_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Duplicate boundary ids are refused."""
    duplicate_first(export_ep1, "boundaries")
    duplicate_first(export_ep2, "boundaries")
    with pytest.raises(ValueError, match="more than once"):
        require_consecutive_exports(export_ep1, export_ep2)


def test_a_district_id_with_surrounding_whitespace_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Reported: matching malformed spellings were accepted on both sides."""
    export_ep1["world"]["districts"][0]["id"] = " district_a"
    export_ep2["world"]["districts"][0]["id"] = " district_a"
    with pytest.raises(ValueError, match="surrounding whitespace"):
        require_consecutive_exports(export_ep1, export_ep2)


def test_a_boundary_id_with_surrounding_whitespace_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """A boundary id with surrounding whitespace is refused."""
    export_ep1["world"]["boundaries"][0]["id"] = "boundary_ab "
    export_ep2["world"]["boundaries"][0]["id"] = "boundary_ab "
    with pytest.raises(ValueError, match="surrounding whitespace"):
        require_consecutive_exports(export_ep1, export_ep2)


def test_a_blank_district_id_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """A blank district id is refused."""
    export_ep1["world"]["districts"][0]["id"] = "   "
    export_ep2["world"]["districts"][0]["id"] = "   "
    with pytest.raises(ValueError):
        require_consecutive_exports(export_ep1, export_ep2)


def test_a_blank_boundary_id_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """A blank boundary id is refused."""
    export_ep1["world"]["boundaries"][0]["id"] = ""
    export_ep2["world"]["boundaries"][0]["id"] = ""
    with pytest.raises(ValueError):
        require_consecutive_exports(export_ep1, export_ep2)


def test_a_non_string_district_id_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """A non string district id is refused."""
    export_ep1["world"]["districts"][0]["id"] = 7
    export_ep2["world"]["districts"][0]["id"] = 7
    with pytest.raises(TypeError):
        require_consecutive_exports(export_ep1, export_ep2)


def test_a_non_string_boundary_id_is_refused(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """A non string boundary id is refused."""
    export_ep1["world"]["boundaries"][0]["id"] = None
    export_ep2["world"]["boundaries"][0]["id"] = None
    with pytest.raises(TypeError):
        require_consecutive_exports(export_ep1, export_ep2)
