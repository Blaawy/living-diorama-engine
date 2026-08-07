"""Phase 13 continuation runner: one verified episode into the next.

Everything here runs against real engine components -- the real save manager,
serializers, systems, loop, and memory distillation. Episode 0 fixtures are
published through the real persistence layer, continuations run the real
pipeline, and every claim of success is checked against what the real loader
reproduces from disk.
"""

import dataclasses
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from cli.conftest import (
    BOUNDARY_ID,
    INFRASTRUCTURE_ID,
    MOVEMENT_LAW_ID,
    PARENT_TICK,
    SCAR_PARENT_TICK,
    WALL_BUILT_TICK,
    WALL_ID,
    build_parent_world,
    build_scar_world,
    change_plan_document,
    plan_bytes,
    restore_plan_document,
    save_episode_zero,
    scar_event_log,
    tree_bytes,
    write_plan,
)
from living_diorama.cli.episode_plan import SystemsConfiguration, parse_episode_plan
from living_diorama.cli.run_episode import (
    ContinuationResult,
    build_causal_systems,
    build_pipeline,
    derive_child_world,
    main,
    run_continuation,
)
from living_diorama.entities import ResourceType
from living_diorama.events import EventBus, EventType
from living_diorama.memory import MemoryFactType, MemorySignificance
from living_diorama.persistence import (
    EVENT_LOG_FILE,
    MANIFEST_FILE,
    WORLD_MEMORY_FILE,
    WORLD_STATE_FILE,
    SaveManager,
    dumps_canonical,
    loads_canonical,
    sha256_hex,
)
from living_diorama.persistence.serializers.world_serializer import serialize_world
from living_diorama.simulation import SimulationLoop
from living_diorama.systems import (
    BoundaryDecisionSystem,
    ConsumptionSystem,
    InfrastructureAdaptationSystem,
    InstitutionalPressureSystem,
    MigrationSystem,
    ProductionSystem,
    ResourceFlowSystem,
    RuleSystem,
    ScarcitySystem,
    SocialStabilitySystem,
)
from persistence.conftest import temporary_save_root
from persistence.test_save_manager import require_symlink_support

CANONICAL_PIPELINE_TYPES = (
    RuleSystem,
    ProductionSystem,
    ConsumptionSystem,
    ResourceFlowSystem,
    MigrationSystem,
    ScarcitySystem,
    SocialStabilitySystem,
    InstitutionalPressureSystem,
    BoundaryDecisionSystem,
    InfrastructureAdaptationSystem,
)
"""The canonical runtime order, RuleSystem first."""


def continue_with(root: Path, document: dict[str, Any]) -> ContinuationResult:
    """Parse a plan document and run one continuation against a save root."""
    return run_continuation(save_root=root, plan=parse_episode_plan(plan_bytes(document)))


def manifest_document(root: Path, episode: int) -> dict[str, Any]:
    """Read one episode's manifest document straight from disk."""
    directory = root / f"episode_{episode:03d}"
    document = loads_canonical((directory / MANIFEST_FILE).read_bytes())
    assert type(document) is dict
    return document


class TestContinuationPreparation:
    """The N to N+1 transition: exact inheritance, nothing else."""

    def test_parent_is_loaded_through_real_save_manager(self) -> None:
        """An empty save root refuses continuation through the real loader."""
        with temporary_save_root() as root:
            with pytest.raises(FileNotFoundError, match="episode 0 does not exist"):
                continue_with(root, change_plan_document())
            assert list(root.iterdir()) == []

    def test_parent_verification_precedes_system_configuration(self) -> None:
        """When the chain and the configuration are both invalid, ancestry wins.

        The canonical order is load-and-verify first, configure second. With a
        corrupted parent AND an unbuildable system configuration in the same
        plan, the refusal must name the broken chain -- a configuration error
        surfacing first would prove the runner configured a child before its
        history was verified.
        """
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            state_path = root / "episode_000" / WORLD_STATE_FILE
            state_path.write_bytes(state_path.read_bytes().replace(b"1", b"2", 1))
            document = change_plan_document()
            document["systems"]["production_allocation"]["FOOD"] = 0.1
            with pytest.raises(ValueError) as refusal:
                continue_with(root, document)
            message = str(refusal.value)
            assert "sum to 1.0" not in message
            assert "hashes to" in message
            assert not (root / "episode_001").exists()

    def test_child_episode_is_exactly_parent_plus_one(self) -> None:
        """The child is always the parent's direct successor."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            result = continue_with(root, change_plan_document())
            assert result.parent_episode == 0
            assert result.child_episode == 1
            assert manifest_document(root, 1)["episode"] == 1

    def test_parent_tick_is_preserved_before_run(self) -> None:
        """The transition never resets the clock; the world owns its tick."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            parent = SaveManager(root).load_episode(0)
            child = derive_child_world(parent.world, 1)
            assert child.tick == PARENT_TICK

    def test_child_rng_state_is_identical_before_first_tick(self) -> None:
        """The child continues the parent's exact saved sequence."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            parent = SaveManager(root).load_episode(0)
            child = derive_child_world(parent.world, 1)
            assert child.rng.get_state() == parent.world.rng.get_state()

    def test_parent_world_is_not_modified_by_transition(self) -> None:
        """Deriving a child reads the parent; it never writes it."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            parent = SaveManager(root).load_episode(0)
            before = serialize_world(parent.world)
            derive_child_world(parent.world, 1)
            assert serialize_world(parent.world) == before

    def test_transition_consumes_no_rng(self) -> None:
        """Reconstruction draws nothing: both generators sit where they were."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            parent = SaveManager(root).load_episode(0)
            state_before = parent.world.rng.get_state()
            child = derive_child_world(parent.world, 1)
            assert parent.world.rng.get_state() == state_before
            assert child.rng.get_state() == state_before

    def test_child_world_is_a_distinct_object(self) -> None:
        """The child shares nothing with the parent aggregate."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            parent = SaveManager(root).load_episode(0)
            child = derive_child_world(parent.world, 1)
            assert child is not parent.world
            assert child.districts["district_a"] is not parent.world.districts["district_a"]
            assert child.laws[MOVEMENT_LAW_ID] is not parent.world.laws[MOVEMENT_LAW_ID]

    def test_transition_changes_only_the_episode(self) -> None:
        """Every semantic field except the episode number carries over exactly."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_scar_world(), scar_event_log())
            parent = SaveManager(root).load_episode(0)
            parent_document = serialize_world(parent.world)
            child = derive_child_world(parent.world, 1)
            expected = dict(parent_document)
            expected["episode"] = 1
            assert serialize_world(child) == expected

    def test_transition_produces_no_events(self) -> None:
        """Every recorded child event comes from the run, never the transition."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            continue_with(root, change_plan_document())
            child = SaveManager(root).load_episode(1)
            events = child.event_log.events()
            assert events
            assert all(event.tick > PARENT_TICK for event in events)

    def test_action_episode_agrees_with_derived_child(self) -> None:
        """The parsed action always carries the derived child episode."""
        plan = parse_episode_plan(plan_bytes(change_plan_document()))
        assert plan.action.episode == plan.child_episode

    def test_action_tick_at_parent_tick_is_rejected(self) -> None:
        """An action at the parent's final tick has already been missed."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            with pytest.raises(ValueError, match="strictly after"):
                continue_with(root, change_plan_document(tick=PARENT_TICK))

    def test_action_tick_before_parent_tick_is_rejected(self) -> None:
        """An action in the parent's past can never fire."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            with pytest.raises(ValueError, match="strictly after"):
                continue_with(root, change_plan_document(tick=PARENT_TICK - 1))

    def test_action_tick_after_run_window_is_rejected(self) -> None:
        """An action after the last configured tick would never fire."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            with pytest.raises(ValueError, match="an intervention must fire during its own"):
                continue_with(root, change_plan_document(ticks=6, tick=PARENT_TICK + 7))

    def test_action_tick_at_final_run_tick_is_accepted(self) -> None:
        """The last tick of the run is inside the window, inclusively."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            result = continue_with(root, change_plan_document(ticks=6, tick=PARENT_TICK + 6))
            assert result.final_tick == PARENT_TICK + 6
            child = SaveManager(root).load_episode(1)
            changed = child.event_log.query(event_type=EventType.LAW_CHANGED)
            assert len(changed) == 1
            assert changed[0].tick == PARENT_TICK + 6

    def test_plan_must_be_an_episode_plan(self) -> None:
        """The runner refuses anything but the frozen plan type."""
        with (
            temporary_save_root() as root,
            pytest.raises(TypeError, match="plan must be an EpisodePlan"),
        ):
            run_continuation(save_root=root, plan={"parent_episode": 0})  # type: ignore[arg-type]


class TestPipeline:
    """The canonical runtime pipeline, constructed in one reviewable place."""

    def test_pipeline_is_exactly_the_canonical_order(self) -> None:
        """Ten systems, exactly typed, RuleSystem first and only once."""
        plan = parse_episode_plan(plan_bytes(change_plan_document()))
        pipeline = build_pipeline(plan.action, plan.systems)
        assert len(pipeline) == 10
        assert tuple(type(system) for system in pipeline) == CANONICAL_PIPELINE_TYPES
        assert type(pipeline[0]) is RuleSystem
        assert sum(1 for system in pipeline if type(system) is RuleSystem) == 1

    def test_configuration_subclass_is_rejected(self) -> None:
        """A stateful configuration subclass cannot wire disagreeing systems.

        The attack: a property whose setter swallows the frozen-dataclass
        re-capture and whose getter could answer each system's construction
        differently. The exact-type gate refuses the object before any system
        is built.
        """
        good = parse_episode_plan(plan_bytes(change_plan_document())).systems

        class ShiftyConfiguration(SystemsConfiguration):
            """A subclass that could answer differently on later reads."""

            @property
            def consumption_allocation(self) -> dict[ResourceType, float]:
                """Answer with a fresh mapping on every read."""
                return {
                    ResourceType.FOOD: 0.5,
                    ResourceType.MATERIALS: 0.3,
                    ResourceType.ENERGY: 0.2,
                }

            @consumption_allocation.setter
            def consumption_allocation(self, value: object) -> None:
                """Swallow the re-capture silently."""

        shifty = ShiftyConfiguration(
            **{
                field.name: getattr(good, field.name)
                for field in dataclasses.fields(SystemsConfiguration)
            }
        )
        with pytest.raises(TypeError, match="must be exactly a SystemsConfiguration"):
            build_causal_systems(shifty)
        with pytest.raises(TypeError, match="must be exactly a SystemsConfiguration"):
            build_pipeline(parse_episode_plan(plan_bytes(change_plan_document())).action, shifty)

    def test_rule_system_holds_exactly_the_plan_action(self) -> None:
        """The rule system's schedule is the plan's one derived action."""
        plan = parse_episode_plan(plan_bytes(change_plan_document()))
        pipeline = build_pipeline(plan.action, plan.systems)
        rule = pipeline[0]
        assert type(rule) is RuleSystem
        assert rule.schedule == (plan.action,)

    def test_causal_systems_receive_the_plan_configuration(self) -> None:
        """Every configured value lands on the system that owns it."""
        plan = parse_episode_plan(plan_bytes(change_plan_document()))
        (
            production,
            consumption,
            flow,
            migration,
            scarcity,
            social,
            institutional,
            boundary,
            adaptation,
        ) = build_causal_systems(plan.systems)
        consumption_allocation = {
            ResourceType.FOOD: 0.5,
            ResourceType.MATERIALS: 0.3,
            ResourceType.ENERGY: 0.2,
        }
        assert type(production) is ProductionSystem
        assert dict(production.allocation) == {
            ResourceType.FOOD: 0.6,
            ResourceType.MATERIALS: 0.3,
            ResourceType.ENERGY: 0.1,
        }
        assert type(consumption) is ConsumptionSystem
        assert dict(consumption.allocation) == consumption_allocation
        assert type(flow) is ResourceFlowSystem
        assert flow.law_id == MOVEMENT_LAW_ID
        assert dict(flow.consumption_allocation) == consumption_allocation
        assert flow.reserve_ticks == 1.5
        assert type(migration) is MigrationSystem
        assert migration.law_id == MOVEMENT_LAW_ID
        assert dict(migration.consumption_allocation) == consumption_allocation
        assert migration.migration_rate == 0.2
        assert migration.min_pressure_gap == 0.05
        assert migration.partial_isolation_factor == 0.45
        assert type(scarcity) is ScarcitySystem
        assert dict(scarcity.consumption_allocation) == consumption_allocation
        assert type(social) is SocialStabilitySystem
        assert social.scarcity_weight == 1.1
        assert social.housing_pressure_weight == 0.9
        assert social.response_rate == 0.25
        assert type(institutional) is InstitutionalPressureSystem
        assert institutional.scarcity_weight == 1.2
        assert institutional.fear_weight == 0.8
        assert institutional.distrust_weight == 0.7
        assert institutional.response_rate == 0.15
        assert type(boundary) is BoundaryDecisionSystem
        assert boundary.build_threshold == 0.95
        assert type(adaptation) is InfrastructureAdaptationSystem
        assert adaptation.adaptation_rate == 0.1


class TestEventScope:
    """Each episode's raw history is its own, and the rule event leads it."""

    def test_child_log_contains_only_child_events(self) -> None:
        """No parent event is copied or replayed into the child's history."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_scar_world(), scar_event_log())
            continue_with(root, restore_plan_document())
            child = SaveManager(root).load_episode(1)
            events = child.event_log.events()
            assert events
            assert all(event.tick > SCAR_PARENT_TICK for event in events)
            assert all(event.type is not EventType.WALL_BUILT for event in events)

    def test_parent_log_is_not_reused(self) -> None:
        """The parent's history still holds exactly what it held before."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_scar_world(), scar_event_log())
            continue_with(root, restore_plan_document())
            parent = SaveManager(root).load_episode(0)
            events = parent.event_log.events()
            assert len(events) == 1
            assert events[0].type is EventType.WALL_BUILT
            assert events[0].tick == WALL_BUILT_TICK

    def test_law_event_fires_at_its_scheduled_absolute_tick(self) -> None:
        """The one LAW_CHANGED event lands exactly where the plan said."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            continue_with(root, change_plan_document(tick=PARENT_TICK + 3))
            child = SaveManager(root).load_episode(1)
            changed = child.event_log.query(event_type=EventType.LAW_CHANGED)
            assert len(changed) == 1
            assert changed[0].tick == PARENT_TICK + 3
            assert changed[0].source_id == MOVEMENT_LAW_ID

    def test_law_event_precedes_downstream_events_that_tick(self) -> None:
        """RuleSystem runs first, so its event opens its tick's history."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            continue_with(root, change_plan_document(tick=PARENT_TICK + 3))
            child = SaveManager(root).load_episode(1)
            events_that_tick = [
                event for event in child.event_log.events() if event.tick == PARENT_TICK + 3
            ]
            assert len(events_that_tick) > 1
            assert events_that_tick[0].type is EventType.LAW_CHANGED

    def test_exactly_one_intervention_event_for_a_change(self) -> None:
        """One scheduled change produces exactly one law event."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            continue_with(root, change_plan_document())
            child = SaveManager(root).load_episode(1)
            law_events = [
                event
                for event in child.event_log.events()
                if event.type in (EventType.LAW_CHANGED, EventType.LAW_RESTORED)
            ]
            assert len(law_events) == 1
            assert law_events[0].type is EventType.LAW_CHANGED

    def test_exactly_one_intervention_event_for_a_restore(self) -> None:
        """One scheduled restoration produces exactly one law event."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_scar_world(), scar_event_log())
            continue_with(root, restore_plan_document())
            child = SaveManager(root).load_episode(1)
            law_events = [
                event
                for event in child.event_log.events()
                if event.type in (EventType.LAW_CHANGED, EventType.LAW_RESTORED)
            ]
            assert len(law_events) == 1
            assert law_events[0].type is EventType.LAW_RESTORED
            assert law_events[0].tick == SCAR_PARENT_TICK + 3


class TestMemory:
    """Cumulative memory: inherited whole, extended only by the rules."""

    def test_parent_memory_is_inherited_and_extended(self) -> None:
        """The child's memory begins with every fact the parent remembered."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_scar_world(), scar_event_log())
            parent_facts = SaveManager(root).load_episode(0).world_memory.facts
            assert len(parent_facts) == 1
            assert parent_facts[0].fact_type is MemoryFactType.WALL_BUILT
            continue_with(root, restore_plan_document())
            child_memory = SaveManager(root).load_episode(1).world_memory
            assert child_memory.facts[: len(parent_facts)] == parent_facts

    def test_child_memory_checkpoint_matches_episode_end(self) -> None:
        """The distilled memory is checkpointed to the child's final moment."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_scar_world(), scar_event_log())
            result = continue_with(root, restore_plan_document())
            child_memory = SaveManager(root).load_episode(1).world_memory
            assert child_memory.through_episode == 1
            assert child_memory.through_tick == result.final_tick

    def test_restoration_appends_exactly_the_justified_fact(self) -> None:
        """Phase 11's rules add one persisted-wall fact; the CLI authors none."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_scar_world(), scar_event_log())
            continue_with(root, restore_plan_document())
            facts = SaveManager(root).load_episode(1).world_memory.facts
            assert len(facts) == 2
            assert facts[0].fact_type is MemoryFactType.WALL_BUILT
            appended = facts[1]
            assert appended.fact_type is MemoryFactType.LAW_RESTORED_WALL_PERSISTED
            assert appended.episode == 1
            assert appended.tick == SCAR_PARENT_TICK + 3
            assert appended.source_event_type is EventType.LAW_RESTORED
            assert appended.source_id == MOVEMENT_LAW_ID
            assert appended.details["wall_id"] == WALL_ID
            assert appended.details["wall_built_tick"] == WALL_BUILT_TICK
            assert appended.details["wall_permanent"] is True

    def test_uneventful_episode_extends_memory_without_new_facts(self) -> None:
        """A run with no significant events advances only the checkpoint."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            result = continue_with(root, change_plan_document())
            child_memory = SaveManager(root).load_episode(1).world_memory
            assert child_memory.facts == ()
            assert child_memory.through_episode == 1
            assert child_memory.through_tick == result.final_tick

    def test_reloaded_artifacts_recompute_exactly_the_persisted_memory(self) -> None:
        """Reloaded inputs distill to exactly the memory that was persisted.

        The full-equality proof: the reloaded child world, the reloaded
        episode-local event log, and the reloaded parent memory, handed to the
        real :class:`MemorySignificance`, must reproduce the child's persisted
        cumulative memory as a whole object -- every fact, every detail, every
        checkpoint field -- not merely the spot-checked parts.
        """
        with temporary_save_root() as root:
            save_episode_zero(root, build_scar_world(), scar_event_log())
            continue_with(root, restore_plan_document())
            manager = SaveManager(root)
            reloaded_parent = manager.load_episode(0)
            reloaded_child = manager.load_episode(1)
            recomputed = MemorySignificance().distill_episode(
                world=reloaded_child.world,
                event_log=reloaded_child.event_log,
                previous_memory=reloaded_parent.world_memory,
            )
            assert recomputed == reloaded_child.world_memory

    def test_old_facts_survive_unchanged(self) -> None:
        """Nothing rewrites what the world already remembered."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_scar_world(), scar_event_log())
            before = SaveManager(root).load_episode(0).world_memory.facts[0]
            continue_with(root, restore_plan_document())
            after = SaveManager(root).load_episode(1).world_memory.facts[0]
            assert after == before


class TestLineageAndImmutability:
    """The chain stays whole, and published history stays untouched."""

    def test_manifest_links_child_to_verified_parent(self) -> None:
        """The child records exactly the parent's verified state hash."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            result = continue_with(root, change_plan_document())
            parent_manifest = manifest_document(root, 0)
            child_manifest = manifest_document(root, 1)
            assert child_manifest["parent_state_hash"] == parent_manifest["state_hash"]
            assert result.parent_state_hash == parent_manifest["state_hash"]
            assert result.state_hash == child_manifest["state_hash"]

    def test_child_state_hash_verifies_on_disk(self) -> None:
        """The recorded hash is the hash of the bytes actually published."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            result = continue_with(root, change_plan_document())
            state_bytes = (root / "episode_001" / WORLD_STATE_FILE).read_bytes()
            assert sha256_hex(state_bytes) == result.state_hash

    def test_child_reload_verifies_the_complete_chain(self) -> None:
        """The published child loads through the real loader, ancestry and all."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            continue_with(root, change_plan_document())
            manager = SaveManager(root)
            loaded = manager.load_episode(1)
            assert loaded.world.episode == 1
            manager.verify_lineage(0, 1)

    def test_corrupted_parent_refuses_continuation(self) -> None:
        """A parent that fails verification stops everything before simulation."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            state_path = root / "episode_000" / WORLD_STATE_FILE
            state_path.write_bytes(state_path.read_bytes().replace(b"1", b"2", 1))
            before = tree_bytes(root)
            with pytest.raises(ValueError):
                continue_with(root, change_plan_document())
            assert not (root / "episode_001").exists()
            assert tree_bytes(root) == before

    def test_corrupted_ancestor_refuses_continuation(self) -> None:
        """A broken episode 0 poisons the whole chain, not just its child."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            continue_with(root, change_plan_document())
            state_path = root / "episode_000" / WORLD_STATE_FILE
            state_path.write_bytes(state_path.read_bytes().replace(b"1", b"2", 1))
            before = tree_bytes(root)
            with pytest.raises(ValueError):
                continue_with(root, restore_plan_document(parent_episode=1, tick=PARENT_TICK + 9))
            assert not (root / "episode_002").exists()
            assert tree_bytes(root) == before

    def test_existing_child_directory_is_never_replaced(self) -> None:
        """A directory already at the child's place refuses the publication."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            rival = root / "episode_001"
            rival.mkdir()
            (rival / "already_here.json").write_bytes(b"{}\n")
            with pytest.raises(FileExistsError, match="never overwritten"):
                continue_with(root, change_plan_document())
            assert (rival / "already_here.json").read_bytes() == b"{}\n"

    def test_existing_child_symlink_is_never_replaced(self) -> None:
        """A symlink at the child's place is an existing entry, not a slot."""
        with temporary_save_root() as root:
            require_symlink_support(root)
            save_episode_zero(root, build_parent_world())
            rival = root / "episode_001"
            rival.symlink_to(root / "no_such_target")
            with pytest.raises(FileExistsError, match="never overwritten"):
                continue_with(root, change_plan_document())
            assert rival.is_symlink()

    def test_all_ancestor_files_remain_byte_identical(self) -> None:
        """Continuation adds a directory; it changes not one published byte."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_scar_world(), scar_event_log())
            before = tree_bytes(root)
            continue_with(root, restore_plan_document())
            after = tree_bytes(root)
            for path, data in before.items():
                assert after[path] == data
            new_files = set(after) - set(before)
            assert new_files
            assert all(path.startswith("episode_001") for path in new_files)

    def test_child_save_is_exactly_the_four_file_schema(self) -> None:
        """The child directory holds the Phase 10 schema and nothing else."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            continue_with(root, change_plan_document())
            names = sorted(entry.name for entry in (root / "episode_001").iterdir())
            assert names == sorted(
                [EVENT_LOG_FILE, MANIFEST_FILE, WORLD_MEMORY_FILE, WORLD_STATE_FILE]
            )

    def test_no_plan_or_config_enters_the_save_root(self) -> None:
        """The save root holds episode directories only; plans stay outside."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            continue_with(root, change_plan_document())
            assert sorted(entry.name for entry in root.iterdir()) == [
                "episode_000",
                "episode_001",
            ]


class TestFailureAtomicity:
    """A failed continuation writes nothing and changes nothing."""

    def assert_nothing_written(self, root: Path, before: dict[str, bytes]) -> None:
        """Verify no child appeared and every prior byte is untouched."""
        assert not (root / "episode_001").exists()
        assert tree_bytes(root) == before

    def test_invalid_action_timing_writes_nothing(self) -> None:
        """A rejected intervention window leaves the save root untouched."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            before = tree_bytes(root)
            with pytest.raises(ValueError, match="strictly after"):
                continue_with(root, change_plan_document(tick=PARENT_TICK))
            self.assert_nothing_written(root, before)

    def test_missing_target_law_writes_nothing(self) -> None:
        """An intervention naming an absent law fails mid-run and saves nothing."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            before = tree_bytes(root)
            with pytest.raises(ValueError, match="does not exist in the world"):
                continue_with(root, change_plan_document(law_id="law_ghost"))
            self.assert_nothing_written(root, before)

    def test_no_op_change_writes_nothing(self) -> None:
        """A change that would change nothing is refused by the rule system."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            before = tree_bytes(root)
            with pytest.raises(ValueError, match="would not change"):
                continue_with(root, change_plan_document(new_value=True, active=True))
            self.assert_nothing_written(root, before)

    def test_ineligible_restore_writes_nothing(self) -> None:
        """Restoring a law that is still in force is refused by the rule system."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            before = tree_bytes(root)
            with pytest.raises(ValueError, match="cannot be restored"):
                continue_with(root, restore_plan_document(tick=PARENT_TICK + 3))
            self.assert_nothing_written(root, before)

    def test_invalid_system_configuration_writes_nothing(self) -> None:
        """A configuration a constructor refuses fails before anything loads."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            before = tree_bytes(root)
            document = change_plan_document()
            document["systems"]["production_allocation"]["FOOD"] = 0.1
            with pytest.raises(ValueError, match="must sum to 1.0"):
                continue_with(root, document)
            self.assert_nothing_written(root, before)

    def test_corrupted_parent_writes_nothing(self) -> None:
        """A refused ancestry produces no child and touches no file."""
        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            state_path = root / "episode_000" / WORLD_STATE_FILE
            state_path.write_bytes(state_path.read_bytes().replace(b"1", b"2", 1))
            before = tree_bytes(root)
            with pytest.raises(ValueError):
                continue_with(root, change_plan_document())
            self.assert_nothing_written(root, before)

    def test_memory_distillation_refusal_writes_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If distillation refuses the episode, nothing reaches the disk.

        The real engine cannot produce this failure from a valid run -- which
        is the point of covering it here: the orchestration must stay atomic
        even for failures that only a defect could produce.
        """

        class RefusingSignificance:
            """A stand-in whose distillation always refuses."""

            def distill_episode(self, **_: object) -> object:
                """Refuse every episode."""
                raise ValueError("distillation refused for the atomicity test")

        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            before = tree_bytes(root)
            monkeypatch.setattr(
                "living_diorama.cli.run_episode.MemorySignificance", RefusingSignificance
            )
            with pytest.raises(ValueError, match="distillation refused"):
                continue_with(root, change_plan_document())
            self.assert_nothing_written(root, before)


class TestPostSaveVerification:
    """Success is what the loader proves, and the runner really asks it."""

    def test_success_requires_the_post_save_reload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A child the loader would refuse is never reported as success.

        The real loader cannot refuse a child the real saver just published,
        so the reload step is proven the same way the distillation-refusal
        path is: a stand-in that trips exactly there. The save has already
        happened when the trip fires -- what must not happen is a success
        report that skipped the proof.
        """

        class TrippingSaveManager(SaveManager):
            """A save manager whose child reload always refuses."""

            def load_episode(self, episode: int) -> Any:
                """Load ancestors normally; refuse the freshly published child."""
                if episode == 1:
                    raise ValueError("post-save verification tripped")
                return super().load_episode(episode)

        with temporary_save_root() as root:
            save_episode_zero(root, build_parent_world())
            monkeypatch.setattr("living_diorama.cli.run_episode.SaveManager", TrippingSaveManager)
            with pytest.raises(ValueError, match="post-save verification tripped"):
                continue_with(root, change_plan_document())
            assert (root / "episode_001").exists()


class TestContinuationResultContract:
    """The result dataclass holds the same exact-type line as the rest."""

    def test_bool_fields_are_rejected(self) -> None:
        """``True`` is not a tick, an episode, or an event count."""
        with pytest.raises(TypeError, match="final_tick must be an int, got bool"):
            ContinuationResult(
                parent_episode=0,
                child_episode=1,
                final_tick=True,
                event_count=3,
                state_hash="a" * 64,
                parent_state_hash="b" * 64,
            )

    def test_blank_hashes_are_rejected(self) -> None:
        """An empty or padded string is not a state hash."""
        with pytest.raises((TypeError, ValueError)):
            ContinuationResult(
                parent_episode=0,
                child_episode=1,
                final_tick=10,
                event_count=3,
                state_hash="",
                parent_state_hash="b" * 64,
            )

    def test_child_must_directly_follow_parent(self) -> None:
        """A result cannot claim a child that skipped an episode."""
        with pytest.raises(ValueError, match="child_episode must be parent_episode"):
            ContinuationResult(
                parent_episode=0,
                child_episode=2,
                final_tick=10,
                event_count=3,
                state_hash="a" * 64,
                parent_state_hash="b" * 64,
            )


class TestCliBehavior:
    """The command-line face: explicit input, verified output, honest exits."""

    def test_main_reports_the_verified_result(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A successful run prints the child's verified numbers and hashes."""
        root = tmp_path / "saves"
        save_episode_zero(root, build_parent_world())
        plan_path = write_plan(tmp_path / "plan.json", change_plan_document())
        exit_code = main(["--save-root", str(root), "--plan", str(plan_path)])
        assert exit_code == 0
        captured = capsys.readouterr()
        child_manifest = manifest_document(root, 1)
        assert "continuation verified" in captured.out
        assert "parent episode: 0" in captured.out
        assert "new episode: 1" in captured.out
        assert f"final tick: {PARENT_TICK + 6}" in captured.out
        assert f"event count: {child_manifest['event_count']}" in captured.out
        assert f"state hash: {child_manifest['state_hash']}" in captured.out
        assert f"parent state hash: {child_manifest['parent_state_hash']}" in captured.out
        assert captured.err == ""

    def test_main_returns_nonzero_when_the_plan_file_is_missing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An unreadable plan is a failure, not a default."""
        exit_code = main(
            ["--save-root", str(tmp_path / "saves"), "--plan", str(tmp_path / "absent.json")]
        )
        assert exit_code == 1
        assert "cannot read plan" in capsys.readouterr().err

    def test_main_returns_nonzero_for_a_malformed_plan(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A plan that fails validation is reported and nothing runs."""
        plan_path = tmp_path / "plan.json"
        plan_path.write_bytes(b'{"parent_episode": ')
        exit_code = main(["--save-root", str(tmp_path / "saves"), "--plan", str(plan_path)])
        assert exit_code == 1
        assert "continuation failed" in capsys.readouterr().err

    def test_main_returns_nonzero_for_a_failed_continuation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A run the engine refuses exits nonzero with the reason on stderr."""
        root = tmp_path / "saves"
        save_episode_zero(root, build_parent_world())
        plan_path = write_plan(
            tmp_path / "plan.json", change_plan_document(new_value=True, active=True)
        )
        exit_code = main(["--save-root", str(root), "--plan", str(plan_path)])
        assert exit_code == 1
        assert "continuation failed" in capsys.readouterr().err
        assert not (root / "episode_001").exists()

    def test_main_refuses_a_blank_save_root(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An empty save root is refused, not normalized to the current directory."""
        plan_path = write_plan(tmp_path / "plan.json", change_plan_document())
        for blank in ("", "   "):
            exit_code = main(["--save-root", blank, "--plan", str(plan_path)])
            assert exit_code == 1
            assert "--save-root must not be empty" in capsys.readouterr().err

    def test_main_refuses_a_blank_plan_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An empty plan path is refused before anything touches the disk."""
        exit_code = main(["--save-root", str(tmp_path / "saves"), "--plan", "   "])
        assert exit_code == 1
        assert "--plan must not be empty" in capsys.readouterr().err

    def test_main_reports_a_missing_movement_law_plainly(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A mid-run KeyError surfaces as the engine's message, not its repr."""
        root = tmp_path / "saves"
        save_episode_zero(root, build_parent_world())
        document = change_plan_document()
        document["systems"]["movement_law_id"] = "law_ghost"
        plan_path = write_plan(tmp_path / "plan.json", document)
        exit_code = main(["--save-root", str(root), "--plan", str(plan_path)])
        assert exit_code == 1
        assert "continuation failed: no law with id 'law_ghost'" in capsys.readouterr().err
        assert not (root / "episode_001").exists()

    def test_main_requires_both_arguments(self) -> None:
        """Missing required arguments exit nonzero through the parser."""
        with pytest.raises(SystemExit) as excinfo:
            main([])
        assert excinfo.value.code == 2

    def test_module_is_invocable_with_python_dash_m(self) -> None:
        """The documented entry point exists and describes its arguments."""
        completed = subprocess.run(
            [sys.executable, "-m", "living_diorama.cli.run_episode", "--help"],
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0
        assert b"--save-root" in completed.stdout
        assert b"--plan" in completed.stdout


class TestMultiEpisodeContinuation:
    """The same deterministic step, applied again: 0 to 1 to 2."""

    def run_two_step_chain(self, root: Path) -> None:
        """Continue a walled, remembering episode 0 through episodes 1 and 2.

        The parent carries a permanent wall recorded in memory, so every
        inheritance assertion downstream works against a nonempty history --
        an empty chain would make the prefix checks vacuously true.
        """
        world = build_parent_world(
            tick=SCAR_PARENT_TICK, with_wall=True, law_active=True, law_current=True
        )
        save_episode_zero(root, world, scar_event_log())
        continue_with(root, change_plan_document(ticks=6, tick=SCAR_PARENT_TICK + 3))
        continue_with(
            root, restore_plan_document(parent_episode=1, ticks=6, tick=SCAR_PARENT_TICK + 9)
        )

    def test_each_link_records_its_parent_hash(self) -> None:
        """Every manifest links to exactly its verified predecessor."""
        with temporary_save_root() as root:
            self.run_two_step_chain(root)
            manifest_0 = manifest_document(root, 0)
            manifest_1 = manifest_document(root, 1)
            manifest_2 = manifest_document(root, 2)
            assert manifest_0["parent_state_hash"] is None
            assert manifest_1["parent_state_hash"] == manifest_0["state_hash"]
            assert manifest_2["parent_state_hash"] == manifest_1["state_hash"]

    def test_the_whole_ancestry_verifies_from_the_top(self) -> None:
        """Loading episode 2 verifies episodes 0 and 1 on the way."""
        with temporary_save_root() as root:
            self.run_two_step_chain(root)
            loaded = SaveManager(root).load_episode(2)
            assert loaded.world.episode == 2
            assert loaded.world.tick == SCAR_PARENT_TICK + 12

    def test_episode_two_continues_episode_one_exactly(self) -> None:
        """Replaying the step from episode 1's save reproduces episode 2's bytes.

        This is the strongest continuation proof available: the published
        episode 2 world equals a fresh derivation from episode 1's actual
        final state run through the same pipeline -- same districts, same
        RNG continuation, same everything.
        """
        with temporary_save_root() as root:
            self.run_two_step_chain(root)
            loaded_1 = SaveManager(root).load_episode(1)
            plan_2 = parse_episode_plan(
                plan_bytes(
                    restore_plan_document(parent_episode=1, ticks=6, tick=SCAR_PARENT_TICK + 9)
                )
            )
            replayed = derive_child_world(loaded_1.world, 2)
            pipeline = build_pipeline(plan_2.action, plan_2.systems)
            SimulationLoop(pipeline, EventBus()).run(replayed, plan_2.ticks)
            published = (root / "episode_002" / WORLD_STATE_FILE).read_bytes()
            assert dumps_canonical(serialize_world(replayed), WORLD_STATE_FILE) == published

    def test_the_intervention_round_trip_lands_in_the_world(self) -> None:
        """Episode 1 turns the law off; episode 2 restores it, provenance intact."""
        with temporary_save_root() as root:
            self.run_two_step_chain(root)
            manager = SaveManager(root)
            law_after_1 = manager.load_episode(1).world.laws[MOVEMENT_LAW_ID]
            assert law_after_1.active is False
            assert law_after_1.current_value is False
            assert law_after_1.changed_episode == 1
            law_after_2 = manager.load_episode(2).world.laws[MOVEMENT_LAW_ID]
            assert law_after_2.active is True
            assert law_after_2.current_value is True
            assert law_after_2.changed_episode == 2
            assert law_after_2.restored_tick == SCAR_PARENT_TICK + 9

    def test_memory_extends_across_the_chain_with_real_history(self) -> None:
        """Every link inherits the nonempty history; only the last extends it.

        Episode 0 remembers its wall; episode 1 adds nothing significant;
        episode 2's restoration adds the persisted-wall fact. The prefix
        assertions therefore carry real content at every link.
        """
        with temporary_save_root() as root:
            self.run_two_step_chain(root)
            manager = SaveManager(root)
            memory_0 = manager.load_episode(0).world_memory
            memory_1 = manager.load_episode(1).world_memory
            memory_2 = manager.load_episode(2).world_memory
            assert [fact.fact_type for fact in memory_0.facts] == [MemoryFactType.WALL_BUILT]
            assert memory_1.facts == memory_0.facts
            assert memory_1.through_episode == 1
            assert [fact.fact_type for fact in memory_2.facts] == [
                MemoryFactType.WALL_BUILT,
                MemoryFactType.LAW_RESTORED_WALL_PERSISTED,
            ]
            assert memory_2.facts[: len(memory_1.facts)] == memory_1.facts
            assert memory_2.through_episode == 2
            assert memory_2.through_tick == SCAR_PARENT_TICK + 12


class TestSignatureScarContinuation:
    """The defining promise: a restored law cannot erase a permanent wall."""

    def continue_the_scar(self, root: Path) -> ContinuationResult:
        """Publish the scar episode 0 and run the restoration continuation."""
        save_episode_zero(root, build_scar_world(), scar_event_log())
        return continue_with(root, restore_plan_document())

    def test_the_law_is_restored(self) -> None:
        """After reload, the law is back in force with its original value."""
        with temporary_save_root() as root:
            self.continue_the_scar(root)
            law = SaveManager(root).load_episode(1).world.laws[MOVEMENT_LAW_ID]
            assert law.active is True
            assert law.current_value is True
            assert law.previous_value is False
            assert law.changed_episode == 1
            assert law.restored_tick == SCAR_PARENT_TICK + 3

    def test_the_wall_survives_the_restoration(self) -> None:
        """The permanent wall stands after reload, exactly as world law demands."""
        with temporary_save_root() as root:
            self.continue_the_scar(root)
            world = SaveManager(root).load_episode(1).world
            wall = world.walls[WALL_ID]
            assert wall.permanent is True
            assert wall.boundary_id == BOUNDARY_ID
            assert world.boundaries[BOUNDARY_ID].wall_id == WALL_ID
            assert INFRASTRUCTURE_ID in world.infrastructure

    def test_memory_records_only_what_the_rules_justify(self) -> None:
        """The scar's history: the wall's construction, then its persistence."""
        with temporary_save_root() as root:
            self.continue_the_scar(root)
            memory = SaveManager(root).load_episode(1).world_memory
            fact_types = [fact.fact_type for fact in memory.facts]
            assert fact_types == [
                MemoryFactType.WALL_BUILT,
                MemoryFactType.LAW_RESTORED_WALL_PERSISTED,
            ]
            persisted = memory.facts[1]
            assert persisted.details["law_id"] == MOVEMENT_LAW_ID
            assert persisted.details["wall_id"] == WALL_ID
            assert persisted.details["wall_permanent"] is True
            assert persisted.details["restored_tick"] == SCAR_PARENT_TICK + 3

    def test_the_scar_chain_reloads_end_to_end(self) -> None:
        """The published scar continuation verifies through the real loader."""
        with temporary_save_root() as root:
            result = self.continue_the_scar(root)
            manager = SaveManager(root)
            manager.verify_lineage(0, 1)
            loaded = manager.load_episode(1)
            assert loaded.manifest.state_hash == result.state_hash


class TestDeterministicReproduction:
    """Same parent, same plan, same engine: byte-for-byte the same child."""

    def test_identical_roots_produce_identical_children(self) -> None:
        """Two independent runs of the same continuation agree on every byte."""
        with temporary_save_root() as root_a, temporary_save_root() as root_b:
            for root in (root_a, root_b):
                save_episode_zero(root, build_scar_world(), scar_event_log())
            episode_zero_a = tree_bytes(root_a)
            episode_zero_b = tree_bytes(root_b)
            assert episode_zero_a == episode_zero_b

            result_a = continue_with(root_a, restore_plan_document())
            result_b = continue_with(root_b, restore_plan_document())
            assert result_a == result_b

            child_a = {
                name: (root_a / "episode_001" / name).read_bytes()
                for name in (EVENT_LOG_FILE, MANIFEST_FILE, WORLD_MEMORY_FILE, WORLD_STATE_FILE)
            }
            child_b = {
                name: (root_b / "episode_001" / name).read_bytes()
                for name in (EVENT_LOG_FILE, MANIFEST_FILE, WORLD_MEMORY_FILE, WORLD_STATE_FILE)
            }
            assert child_a == child_b

    def test_the_change_run_is_reproducible_too(self) -> None:
        """Determinism holds for the change intervention as well as the restore."""
        with temporary_save_root() as root_a, temporary_save_root() as root_b:
            for root in (root_a, root_b):
                save_episode_zero(root, build_parent_world())
            result_a = continue_with(root_a, change_plan_document())
            result_b = continue_with(root_b, change_plan_document())
            assert result_a == result_b
            assert tree_bytes(root_a) == tree_bytes(root_b)

    def test_reproduction_holds_across_interpreter_hash_seeds(self, tmp_path: Path) -> None:
        """Two continuations in separate interpreters with different hash seeds agree.

        The in-process determinism tests share one hash seed by construction,
        so a hash-order dependence would agree with itself there. Running the
        same continuation under two different ``PYTHONHASHSEED`` values in two
        fresh interpreters closes that blind spot byte-for-byte.
        """
        children: list[dict[str, bytes]] = []
        for seed, name in (("0", "a"), ("42", "b")):
            root = tmp_path / name
            save_episode_zero(root, build_scar_world(), scar_event_log())
            plan_path = write_plan(tmp_path / f"plan_{name}.json", restore_plan_document())
            environment = dict(os.environ)
            environment["PYTHONHASHSEED"] = seed
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "living_diorama.cli.run_episode",
                    "--save-root",
                    str(root),
                    "--plan",
                    str(plan_path),
                ],
                capture_output=True,
                env=environment,
                check=False,
            )
            assert completed.returncode == 0, completed.stderr
            children.append(
                {
                    file_name: (root / "episode_001" / file_name).read_bytes()
                    for file_name in (
                        EVENT_LOG_FILE,
                        MANIFEST_FILE,
                        WORLD_MEMORY_FILE,
                        WORLD_STATE_FILE,
                    )
                }
            )
        assert children[0] == children[1]

    def test_distinct_parents_produce_distinct_children(self) -> None:
        """The negative control: a different inherited state changes the child.

        Same-input-same-bytes alone would also pass for an engine that ignored
        the inherited state entirely; two parents differing only in their saved
        RNG state must therefore produce children that differ.
        """
        with temporary_save_root() as root_a, temporary_save_root() as root_b:
            save_episode_zero(root_a, build_parent_world())
            save_episode_zero(root_b, build_parent_world(seed=987654321))
            result_a = continue_with(root_a, change_plan_document())
            result_b = continue_with(root_b, change_plan_document())
            assert result_a.parent_state_hash != result_b.parent_state_hash
            assert result_a.state_hash != result_b.state_hash
