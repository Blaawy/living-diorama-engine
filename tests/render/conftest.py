"""Shared builders for the Phase 14 render export tests.

Every fixture is real: episode 0 worlds are published through the real
persistence layer, and the multi-episode scar chain is produced by the real
Phase 13 continuation runner -- the same locked engine path an operator would
use. The render layer under test then reads only what the real loader
verifies.
"""

from pathlib import Path

from cli.conftest import (
    build_parent_world,
    build_scar_world,
    plan_bytes,
    restore_plan_document,
    save_episode_zero,
    scar_event_log,
)
from living_diorama.cli.episode_plan import parse_episode_plan
from living_diorama.cli.run_episode import run_continuation
from living_diorama.entities import Boundary, District, IsolationState, Law, ResourcePool
from living_diorama.simulation import DeterministicRNG, World

TYPED_LAW_VALUES = {
    "law_flag": (None, True),
    "law_motto": ("old", "1"),
    "law_quota": (False, None),
    "law_rate": (1, 1.0),
}
"""Law ids mapped to (previous_value, current_value) covering every scalar kind.

Chosen adversarially: ``True``, ``1``, ``1.0``, and ``"1"`` all compare equal
under plain ``==``, so any coercion anywhere in the export path would collapse
them and fail the fidelity assertions.
"""


def build_typed_laws_world(*, episode: int = 0, tick: int = 3) -> World:
    """Build an episode 0 world whose laws exercise every law-value type."""
    world = World(rng=DeterministicRNG(20260808), tick=tick, episode=episode)
    world.add_district(
        District(
            id="district_a",
            created_tick=0,
            population=50,
            resources=ResourcePool(stock={}),
            production_rate=1.0,
            consumption_rate=0.1,
            scarcity=0.1,
            fear=0.2,
            trust=0.7,
            institutional_pressure=0.2,
            housing_capacity=100,
            isolation_state=IsolationState.OPEN,
        )
    )
    world.add_district(
        District(
            id="district_b",
            created_tick=0,
            population=30,
            resources=ResourcePool(stock={}),
            production_rate=1.0,
            consumption_rate=0.1,
            scarcity=0.2,
            fear=0.3,
            trust=0.6,
            institutional_pressure=0.3,
            housing_capacity=100,
            isolation_state=IsolationState.OPEN,
        )
    )
    world.add_boundary(
        Boundary(
            id="boundary_ab",
            created_tick=0,
            district_a_id="district_a",
            district_b_id="district_b",
        )
    )
    # Endpoint roles deliberately reversed relative to alphabetical order:
    # any normalization of district_a_id/district_b_id anywhere in the export
    # path would rewrite this boundary and fail the fidelity assertions.
    world.add_boundary(
        Boundary(
            id="boundary_ba",
            created_tick=0,
            district_a_id="district_b",
            district_b_id="district_a",
        )
    )
    for index, (law_id, (previous_value, current_value)) in enumerate(
        sorted(TYPED_LAW_VALUES.items())
    ):
        world.add_law(
            Law(
                id=law_id,
                created_tick=0,
                name=f"Typed Law {index}",
                active=True,
                previous_value=previous_value,
                current_value=current_value,
                changed_episode=0,
                restored_tick=None,
            )
        )
    return world


def publish_calm_episode_zero(root: Path) -> None:
    """Publish the calm two-district episode 0 through the real save layer."""
    save_episode_zero(root, build_parent_world())


def publish_scar_chain(root: Path) -> None:
    """Publish the real scar chain through the real continuation runner.

    Episode 0 holds the permanent wall, its ``WALL_BUILT`` event, and the
    movement law switched off with its original value stored. The
    continuation restores the law; the wall persists; memory gains the
    persisted-wall fact. Episode 1 is therefore the canonical scar export
    source.
    """
    save_episode_zero(root, build_scar_world(), scar_event_log())
    run_continuation(save_root=root, plan=parse_episode_plan(plan_bytes(restore_plan_document())))


def publish_typed_laws_episode_zero(root: Path) -> None:
    """Publish the typed-laws episode 0 through the real save layer."""
    save_episode_zero(root, build_typed_laws_world())


def tree_bytes(root: Path) -> dict[str, bytes]:
    """Return every file under a directory, keyed by relative path."""
    return {
        str(entry.relative_to(root)): entry.read_bytes()
        for entry in sorted(root.rglob("*"))
        if entry.is_file()
    }


def tree_entries(root: Path) -> list[str]:
    """Return every directory entry (files and directories) under a root."""
    return sorted(str(entry.relative_to(root)) for entry in root.rglob("*"))
