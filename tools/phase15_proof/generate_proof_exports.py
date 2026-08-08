"""Produce the Phase 15 proof inputs with the real engine, end to end.

This is engine-side tooling, not Blender code: it composes only public
Living Diorama APIs to create a genuine three-episode story and the two
Render Export documents the Blender layer consumes. Nothing is hand-edited;
the wall in the "after" world exists because the engine's own causal pipeline
built it.

The story:

    Episode 0  (before)   four districts, movement law in force, no wall.
    Episode 1             the episode rule turns movement/sharing OFF; the
                          eastern annex starves, pressure crosses the build
                          threshold, and BoundaryDecisionSystem raises a
                          permanent wall on its only boundary.
    Episode 2  (after)    the rule is RESTORED -- and the wall remains, with
                          infrastructure visibly dependent on it. The world
                          remembers.

Outputs, under the given workspace directory:

    saves/                       the real three-episode chain
    render_export_before.json    Phase 14 export of episode 0
    render_export_after.json     Phase 14 export of episode 2
    proof_inputs_manifest.json   episodes, ticks, and SHA-256 of every input
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from living_diorama.cli.episode_plan import parse_episode_plan
from living_diorama.cli.run_episode import run_continuation
from living_diorama.entities import (
    Boundary,
    District,
    Infrastructure,
    InfrastructureType,
    IsolationState,
    Law,
    ResourcePool,
    ResourceType,
)
from living_diorama.events import EventLog
from living_diorama.memory import MemorySignificance, WorldMemory
from living_diorama.persistence import SaveManager, sha256_hex
from living_diorama.render import write_render_export
from living_diorama.simulation import DeterministicRNG, World

MOVEMENT_LAW_ID = "law_movement_sharing"

DISTRICTS = (
    # id, population, production, consumption, food, materials, energy,
    # scarcity, fear, trust, pressure, housing
    ("district_a", 140, 30.0, 0.10, 90.0, 60.0, 40.0, 0.05, 0.10, 0.85, 0.15, 400),
    ("district_b", 60, 4.0, 0.35, 10.0, 6.0, 4.0, 0.50, 0.70, 0.20, 0.62, 150),
    ("district_c", 90, 16.0, 0.10, 60.0, 40.0, 25.0, 0.05, 0.12, 0.80, 0.15, 300),
    ("district_d", 110, 20.0, 0.12, 70.0, 45.0, 30.0, 0.08, 0.15, 0.75, 0.20, 350),
)

BOUNDARIES = (
    ("boundary_ab", "district_a", "district_b"),
    ("boundary_ac", "district_a", "district_c"),
    ("boundary_ad", "district_a", "district_d"),
    ("boundary_cd", "district_c", "district_d"),
)

INFRASTRUCTURE = (
    ("infra_ab_transit", "boundary_ab", InfrastructureType.TRANSIT_ROUTE),
    ("infra_ab_resource", "boundary_ab", InfrastructureType.RESOURCE_ROUTE),
    ("infra_ac_transit", "boundary_ac", InfrastructureType.TRANSIT_ROUTE),
    ("infra_ad_transit", "boundary_ad", InfrastructureType.TRANSIT_ROUTE),
    ("infra_cd_transit", "boundary_cd", InfrastructureType.TRANSIT_ROUTE),
)

EPISODE_ZERO_TICK = 6


def systems_section() -> dict[str, object]:
    """The explicit causal-system configuration used for both continuations."""
    return {
        "production_allocation": {"FOOD": 0.5, "MATERIALS": 0.3, "ENERGY": 0.2},
        "consumption_allocation": {"FOOD": 0.5, "MATERIALS": 0.3, "ENERGY": 0.2},
        "movement_law_id": MOVEMENT_LAW_ID,
        "resource_flow": {"reserve_ticks": 2.0},
        "migration": {
            "migration_rate": 0.15,
            "min_pressure_gap": 0.1,
            "partial_isolation_factor": 0.5,
        },
        "social_stability": {
            "scarcity_weight": 1.0,
            "housing_pressure_weight": 0.2,
            "response_rate": 0.35,
        },
        "institutional_pressure": {
            "scarcity_weight": 1.0,
            "fear_weight": 1.0,
            "distrust_weight": 1.0,
            "response_rate": 0.3,
        },
        "boundary_decision": {"build_threshold": 0.75},
        "infrastructure_adaptation": {"adaptation_rate": 0.1},
    }


def build_episode_zero_world() -> World:
    """Build the four-district proof world, before any scar exists."""
    rng = DeterministicRNG(20260808)
    for _ in range(5):
        rng.random()
    world = World(rng=rng, tick=EPISODE_ZERO_TICK, episode=0)
    for (
        district_id,
        population,
        production,
        consumption,
        food,
        materials,
        energy,
        scarcity,
        fear,
        trust,
        pressure,
        housing,
    ) in DISTRICTS:
        world.add_district(
            District(
                id=district_id,
                created_tick=0,
                population=population,
                resources=ResourcePool(
                    stock={
                        ResourceType.FOOD: food,
                        ResourceType.MATERIALS: materials,
                        ResourceType.ENERGY: energy,
                    }
                ),
                production_rate=production,
                consumption_rate=consumption,
                scarcity=scarcity,
                fear=fear,
                trust=trust,
                institutional_pressure=pressure,
                housing_capacity=housing,
                isolation_state=IsolationState.OPEN,
            )
        )
    for boundary_id, district_a_id, district_b_id in BOUNDARIES:
        world.add_boundary(
            Boundary(
                id=boundary_id,
                created_tick=0,
                district_a_id=district_a_id,
                district_b_id=district_b_id,
            )
        )
    world.add_law(
        Law(
            id=MOVEMENT_LAW_ID,
            created_tick=0,
            name="movement_resource_sharing",
            active=True,
            previous_value=None,
            current_value=True,
            changed_episode=0,
            restored_tick=None,
        )
    )
    for infrastructure_id, boundary_id, kind in INFRASTRUCTURE:
        world.add_infrastructure(
            Infrastructure(
                id=infrastructure_id,
                created_tick=0,
                boundary_id=boundary_id,
                infrastructure_type=kind,
                capacity=100.0,
                dependency_score=0.0,
                degraded=False,
            )
        )
    return world


def continuation_plan(
    *, parent_episode: int, ticks: int, kind: str, tick: int
) -> dict[str, object]:
    """Return one continuation plan document for the proof chain."""
    intervention: dict[str, object] = {"kind": kind, "tick": tick, "law_id": MOVEMENT_LAW_ID}
    if kind == "change":
        intervention["new_value"] = False
        intervention["active"] = False
    return {
        "parent_episode": parent_episode,
        "ticks": ticks,
        "intervention": intervention,
        "systems": systems_section(),
    }


def generate(workspace: Path) -> dict[str, object]:
    """Run the real three-episode story and export before/after documents."""
    workspace.mkdir(parents=True, exist_ok=True)
    save_root = workspace / "saves"
    if save_root.exists():
        raise FileExistsError(
            f"proof workspace {save_root} already holds a save chain; use a fresh "
            "workspace rather than mixing runs"
        )

    world_zero = build_episode_zero_world()
    log_zero = EventLog()
    memory_zero = MemorySignificance().distill_episode(
        world=world_zero, event_log=log_zero, previous_memory=WorldMemory.empty()
    )
    SaveManager(save_root).save_episode(world_zero, log_zero, world_memory=memory_zero)

    # Episode 1: the rule turns sharing off two ticks in; the annex starves
    # behind its single boundary and the engine raises the wall itself.
    plan_one = continuation_plan(
        parent_episode=0, ticks=14, kind="change", tick=EPISODE_ZERO_TICK + 1
    )
    run_continuation(
        save_root=save_root,
        plan=parse_episode_plan(json.dumps(plan_one).encode("utf-8")),
    )

    # Episode 2: the rule is restored two ticks in; the wall remains.
    plan_two = continuation_plan(
        parent_episode=1, ticks=8, kind="restore", tick=EPISODE_ZERO_TICK + 16
    )
    run_continuation(
        save_root=save_root,
        plan=parse_episode_plan(json.dumps(plan_two).encode("utf-8")),
    )

    before_path = workspace / "render_export_before.json"
    after_path = workspace / "render_export_after.json"
    before_bytes = write_render_export(save_root, 0, before_path)
    after_bytes = write_render_export(save_root, 2, after_path)

    before = json.loads(before_bytes)
    after = json.loads(after_bytes)
    summary: dict[str, object] = {
        "before_episode": before["source"]["episode"],
        "before_tick": before["source"]["tick"],
        "before_walls": [entry["id"] for entry in before["world"]["walls"]],
        "after_episode": after["source"]["episode"],
        "after_tick": after["source"]["tick"],
        "after_walls": [
            {
                "id": entry["id"],
                "boundary_id": entry["boundary_id"],
                "permanent": entry["permanent"],
                "active": entry["active"],
                "built_tick": entry["built_tick"],
                "dependency_score": entry["dependency_score"],
            }
            for entry in after["world"]["walls"]
        ],
        "after_law": next(
            {
                "active": entry["active"],
                "current_value": entry["current_value"],
                "changed_episode": entry["changed_episode"],
                "restored_tick": entry["restored_tick"],
            }
            for entry in after["world"]["laws"]
            if entry["id"] == MOVEMENT_LAW_ID
        ),
        "after_memory_fact_types": [entry["fact_type"] for entry in after["memory"]["facts"]],
        "after_infrastructure": [
            {
                "id": entry["id"],
                "boundary_id": entry["boundary_id"],
                "dependency_score": entry["dependency_score"],
                "degraded": entry["degraded"],
            }
            for entry in after["world"]["infrastructure"]
        ],
    }

    manifest = {
        "before_export": {
            "path": before_path.name,
            "sha256": sha256_hex(before_bytes),
            "episode": before["source"]["episode"],
            "state_hash": before["source"]["state_hash"],
        },
        "after_export": {
            "path": after_path.name,
            "sha256": sha256_hex(after_bytes),
            "episode": after["source"]["episode"],
            "state_hash": after["source"]["state_hash"],
        },
        "save_chain": {
            str(entry.relative_to(save_root)).replace("\\", "/"): sha256_hex(entry.read_bytes())
            for entry in sorted(save_root.rglob("*"))
            if entry.is_file()
        },
        "story": summary,
    }
    manifest_path = workspace / "proof_inputs_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    """Generate the proof inputs and print the story summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="fresh output directory")
    arguments = parser.parse_args(None if argv is None else list(argv))
    if not arguments.workspace.strip():
        print("proof generation failed: --workspace must not be empty", file=sys.stderr)
        return 1
    summary = generate(Path(arguments.workspace))
    print(json.dumps(summary, indent=2, sort_keys=True))
    walls = summary["after_walls"]
    if not isinstance(walls, list) or len(walls) != 1:
        print("proof generation failed: expected exactly one engine-built wall", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
