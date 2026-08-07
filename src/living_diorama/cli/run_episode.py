"""Continue one verified episode into the next: the Phase 13 composition root.

This module wires already-approved engine components together and owns no
simulation logic, no persistence logic, and no memory logic of its own. One
invocation performs exactly one continuation step::

    python -m living_diorama.cli.run_episode --save-root <path> --plan <plan.json>

The operational story, in order:

1.  The parent episode named by the plan is loaded through
    :meth:`SaveManager.load_episode`, which verifies the complete ancestry from
    episode 0 -- hashes, canonical bytes, lineage, semantic reconstruction, and
    memory history. A chain that fails anywhere refuses continuation before
    anything else happens.
2.  Only then is the child runtime configured: exactly one
    :class:`RuleSystem` action -- the plan's single intervention -- is placed
    FIRST in the canonical pipeline, so every downstream system reacts to the
    changed rule during the same tick it lands, and the intervention's
    ABSOLUTE tick is checked against the verified parent's final tick:
    strictly after it, and no later than the last tick of this run.
3.  The child world is derived by serializing the verified parent world,
    replacing only the episode number in a detached copy of that document, and
    reconstructing it. ``World.episode`` stays read-only, no private field is
    touched, the parent world is never mutated, and the transition draws
    nothing from the RNG: the child continues the parent's exact saved
    sequence. There is no seed anywhere in a continuation.
4.  A fresh :class:`EventBus` and :class:`EventLog` are created for the child
    episode. The parent's log is historical evidence only; its events are
    never appended to, copied into, or replayed through the child's log.
5.  :class:`SimulationLoop` runs the configured number of ticks. A failure
    anywhere stops everything; nothing is saved from a failed run.
6.  After the final tick, :class:`MemorySignificance` distills the episode
    exactly once, extending the parent's cumulative memory with whatever this
    episode's own events justify -- the CLI authors no facts.
7.  :meth:`SaveManager.save_episode` publishes the child atomically. Published
    episodes are immutable: there is no force, no overwrite, no replace, and
    every older episode directory remains byte-for-byte untouched.
8.  The freshly published child is reloaded through the real loader before
    success is reported, proving the whole chain -- including the new episode
    -- verifies from disk.

Repeating the same invocation against the resulting save root continues
``N+1 -> N+2``, and so on: multi-episode history is this one deterministic
step, applied again.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from living_diorama.cli.episode_plan import (
    EpisodePlan,
    SystemsConfiguration,
    parse_episode_plan,
)
from living_diorama.events import EventBus, EventLog
from living_diorama.memory import MemorySignificance
from living_diorama.persistence import SaveManager
from living_diorama.persistence.schema.state_hash import require_hash_hex
from living_diorama.persistence.schema.world_schema_v1 import require_exact_int
from living_diorama.persistence.serializers.world_serializer import (
    deserialize_world,
    serialize_world,
)
from living_diorama.simulation import SimulationLoop
from living_diorama.simulation.world import World
from living_diorama.systems import (
    BaseSystem,
    BoundaryDecisionSystem,
    ConsumptionSystem,
    InfrastructureAdaptationSystem,
    InstitutionalPressureSystem,
    MigrationSystem,
    ProductionSystem,
    ResourceFlowSystem,
    RuleSystem,
    ScarcitySystem,
    ScheduledLawChange,
    ScheduledLawRestore,
    SocialStabilitySystem,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ContinuationResult:
    """What one successful continuation produced, read from the verified child.

    Every field comes from the child episode as reloaded through the real
    loader after publication, not from in-memory state the save was hoped to
    match.

    Attributes:
        parent_episode: The episode the continuation started from.
        child_episode: The episode the continuation created.
        final_tick: The child world's absolute tick after the run.
        event_count: How many events the child episode recorded.
        state_hash: The child's verified world-state hash.
        parent_state_hash: The parent hash the child's manifest records.
    """

    parent_episode: int
    child_episode: int
    final_tick: int
    event_count: int
    state_hash: str
    parent_state_hash: str

    def __post_init__(self) -> None:
        """Validate every field exactly as supplied.

        The internal path always fills this from loader-verified data, but the
        constructor is public, so it holds the same exact-type line as every
        other Phase 13 dataclass: ``True`` is not episode 1, and a blank
        string is not a hash.

        Raises:
            TypeError: If a field is of the wrong exact type.
            ValueError: If a number is negative, a hash is not a hex digest,
                or the child is not the parent's direct successor.
        """
        require_exact_int(self.parent_episode, "parent_episode")
        require_exact_int(self.child_episode, "child_episode")
        require_exact_int(self.final_tick, "final_tick")
        require_exact_int(self.event_count, "event_count")
        if self.child_episode != self.parent_episode + 1:
            raise ValueError(
                f"child_episode must be parent_episode + 1, got {self.child_episode} "
                f"after {self.parent_episode}"
            )
        require_hash_hex(self.state_hash, "state_hash")
        require_hash_hex(self.parent_state_hash, "parent_state_hash")


def derive_child_world(parent_world: World, child_episode: int) -> World:
    """Return a new world continuing the parent's exact state as the next episode.

    ``World.episode`` is deliberately read-only, so the transition goes through
    the hardened serialization path instead of any setter or private field: the
    parent is serialized, the episode number is replaced in a detached
    top-level copy of that document, and the copy is reconstructed through
    public constructors. Everything else -- tick, districts, resources,
    boundaries, walls, laws, infrastructure, entity ids, topology, permanent
    scars, and the exact RNG state -- carries over unchanged, and the
    reconstruction draws no random numbers, so the child continues the
    parent's saved sequence rather than restarting it.

    The parent world is never mutated; it is read exactly once, by
    :func:`serialize_world`.

    Args:
        parent_world: The verified world the continuation starts from.
        child_episode: The derived episode number the child belongs to.

    Returns:
        A distinct, fully reconstructed world for the child episode.

    Raises:
        TypeError: If the world or a stored value is of the wrong type.
        ValueError: If the world cannot be serialized or reconstructed.
    """
    document = serialize_world(parent_world)
    child_document = dict(document)
    child_document["episode"] = child_episode
    return deserialize_world(child_document)


def build_causal_systems(config: SystemsConfiguration) -> tuple[BaseSystem, ...]:
    """Construct the nine causal systems, in canonical order, from the plan.

    Every parameter comes from the frozen configuration; nothing is defaulted
    here. The configuration must be exactly a :class:`SystemsConfiguration`
    and each of its fields is read exactly once, so a stateful subclass cannot
    answer one system's construction differently from another's -- the four
    consumers of the consumption allocation and the two consumers of the
    movement law must agree, and they agree because they are handed the same
    single capture. The constructors themselves enforce their numeric domain
    contracts, so an invalid configuration is refused at construction --
    before anything is simulated or written.

    Raises:
        TypeError: If ``config`` is not exactly a ``SystemsConfiguration``, or
            a configured value is of a type a constructor refuses.
        ValueError: If a configured value violates a constructor's contract.
    """
    if type(config) is not SystemsConfiguration:
        raise TypeError(
            f"config must be exactly a SystemsConfiguration, got {type(config).__name__}"
        )

    # One read per semantic field; every system below sees only these captures.
    production_allocation = config.production_allocation
    consumption_allocation = config.consumption_allocation
    movement_law_id = config.movement_law_id
    reserve_ticks = config.reserve_ticks
    migration_rate = config.migration_rate
    min_pressure_gap = config.min_pressure_gap
    partial_isolation_factor = config.partial_isolation_factor
    social_scarcity_weight = config.social_scarcity_weight
    housing_pressure_weight = config.housing_pressure_weight
    social_response_rate = config.social_response_rate
    institutional_scarcity_weight = config.institutional_scarcity_weight
    fear_weight = config.fear_weight
    distrust_weight = config.distrust_weight
    institutional_response_rate = config.institutional_response_rate
    build_threshold = config.build_threshold
    adaptation_rate = config.adaptation_rate

    return (
        ProductionSystem(allocation=production_allocation),
        ConsumptionSystem(allocation=consumption_allocation),
        ResourceFlowSystem(
            law_id=movement_law_id,
            consumption_allocation=consumption_allocation,
            reserve_ticks=reserve_ticks,
        ),
        MigrationSystem(
            law_id=movement_law_id,
            consumption_allocation=consumption_allocation,
            migration_rate=migration_rate,
            min_pressure_gap=min_pressure_gap,
            partial_isolation_factor=partial_isolation_factor,
        ),
        ScarcitySystem(consumption_allocation=consumption_allocation),
        SocialStabilitySystem(
            scarcity_weight=social_scarcity_weight,
            housing_pressure_weight=housing_pressure_weight,
            response_rate=social_response_rate,
        ),
        InstitutionalPressureSystem(
            scarcity_weight=institutional_scarcity_weight,
            fear_weight=fear_weight,
            distrust_weight=distrust_weight,
            response_rate=institutional_response_rate,
        ),
        BoundaryDecisionSystem(build_threshold=build_threshold),
        InfrastructureAdaptationSystem(adaptation_rate=adaptation_rate),
    )


def build_pipeline(
    action: ScheduledLawChange | ScheduledLawRestore, config: SystemsConfiguration
) -> tuple[BaseSystem, ...]:
    """Construct the complete canonical runtime pipeline for one episode.

    :class:`RuleSystem` holds exactly the one scheduled action and runs FIRST,
    so the intervention is visible to every downstream system during the tick
    it lands. The order is fixed here, in one reviewable place; nothing is
    sorted, discovered, or deduplicated.

    Raises:
        TypeError: If the action or a configured value is of the wrong type.
        ValueError: If a configured value violates a constructor's contract.
    """
    return (RuleSystem((action,)), *build_causal_systems(config))


def run_continuation(*, save_root: str | Path, plan: EpisodePlan) -> ContinuationResult:
    """Perform one verified continuation step: episode N into episode N+1.

    The steps and their order are the whole contract of this function; see the
    module docstring. Nothing is written unless every step before the save
    succeeded, and success is not reported unless the published child reloads
    through the real loader.

    Args:
        save_root: Directory holding the episode chain.
        plan: The validated, frozen run plan.

    Returns:
        The verified result, read from the reloaded child episode.

    Raises:
        TypeError: If ``plan`` is not an :class:`EpisodePlan`, or a value
            anywhere in the chain is of the wrong type.
        ValueError: If the ancestry fails verification, the intervention tick
            falls outside the run window, a system rejects its configuration
            or its world, or distillation refuses the episode.
        KeyError: If a system's law is absent from the world.
        FileNotFoundError: If an episode in the chain is missing.
        FileExistsError: If the child episode already exists; published
            episodes are never replaced.
    """
    if type(plan) is not EpisodePlan:
        raise TypeError(f"plan must be an EpisodePlan, got {type(plan).__name__}")

    manager = SaveManager(save_root)
    # Verified history comes first: the parent and its complete ancestry are
    # loaded and proven before anything about the child run is even
    # configured. A continuation that cannot stand on verified history has
    # nothing to configure, so a broken chain is reported as exactly that --
    # never as a configuration problem discovered while the chain was still
    # unproven.
    parent = manager.load_episode(plan.parent_episode)

    pipeline = build_pipeline(plan.action, plan.systems)
    start_tick = parent.world.tick
    end_tick = start_tick + plan.ticks
    action_tick = plan.action.tick
    # The loop advances the tick before running systems, so a tick at or
    # before the parent's final tick has already been missed, and one after
    # the run window would never fire. Either plan is refused before any
    # simulation begins.
    if action_tick <= start_tick:
        raise ValueError(
            f"the intervention is scheduled for absolute tick {action_tick}, but the "
            f"parent episode already reached tick {start_tick}; it must be scheduled "
            f"strictly after {start_tick}"
        )
    if action_tick > end_tick:
        raise ValueError(
            f"the intervention is scheduled for absolute tick {action_tick}, but this "
            f"run ends at tick {end_tick}; an intervention must fire during its own "
            "episode"
        )

    child_world = derive_child_world(parent.world, plan.child_episode)

    # A fresh bus and log: the child episode records only its own history.
    bus = EventBus()
    event_log = EventLog()
    bus.subscribe(event_log.append)

    SimulationLoop(pipeline, bus).run(child_world, plan.ticks)

    # Exactly once, after every configured tick has finished.
    new_memory = MemorySignificance().distill_episode(
        world=child_world,
        event_log=event_log,
        previous_memory=parent.world_memory,
    )
    manager.save_episode(child_world, event_log, world_memory=new_memory)

    # Success is what the loader proves, not what the save hoped.
    reloaded = manager.load_episode(plan.child_episode)
    manifest = reloaded.manifest
    if manifest.parent_state_hash is None:  # pragma: no cover - child episodes link
        raise ValueError(f"episode {manifest.episode} records no parent state hash")
    return ContinuationResult(
        parent_episode=plan.parent_episode,
        child_episode=plan.child_episode,
        final_tick=reloaded.world.tick,
        event_count=manifest.event_count,
        state_hash=manifest.state_hash,
        parent_state_hash=manifest.parent_state_hash,
    )


def _build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for the continuation entry point."""
    parser = argparse.ArgumentParser(
        prog="python -m living_diorama.cli.run_episode",
        description=(
            "Continue one verified Living Diorama episode into the next, applying "
            "exactly one scheduled rule intervention from a JSON run plan."
        ),
    )
    parser.add_argument(
        "--save-root",
        required=True,
        help="directory holding the episode chain to continue",
    )
    parser.add_argument(
        "--plan",
        required=True,
        help="path to the JSON run plan for the new episode",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one continuation from the command line and report the outcome.

    Args:
        argv: Argument list to parse, or ``None`` for ``sys.argv``.

    Returns:
        0 on verified success, 1 on any refused or failed continuation.
    """
    arguments = _build_parser().parse_args(None if argv is None else list(argv))
    # ``Path("")`` silently normalizes to the current directory, which would
    # aim an unset shell variable at whatever chain the operator is standing
    # in. An empty argument is refused, never repaired.
    if not arguments.save_root.strip():
        print("continuation failed: --save-root must not be empty", file=sys.stderr)
        return 1
    if not arguments.plan.strip():
        print("continuation failed: --plan must not be empty", file=sys.stderr)
        return 1
    plan_path = Path(arguments.plan)
    try:
        plan_bytes = plan_path.read_bytes()
    except OSError as error:
        print(f"cannot read plan {plan_path}: {error}", file=sys.stderr)
        return 1

    try:
        plan = parse_episode_plan(plan_bytes)
        result = run_continuation(save_root=Path(arguments.save_root), plan=plan)
    except (KeyError, OSError, TypeError, ValueError) as error:
        # ``str`` of a KeyError is the repr of its argument, which would wrap
        # the engine's message in an extra layer of quotes.
        detail = error.args[0] if type(error) is KeyError and error.args else error
        print(f"continuation failed: {detail}", file=sys.stderr)
        return 1

    print("continuation verified")
    print(f"parent episode: {result.parent_episode}")
    print(f"new episode: {result.child_episode}")
    print(f"final tick: {result.final_tick}")
    print(f"event count: {result.event_count}")
    print(f"state hash: {result.state_hash}")
    print(f"parent state hash: {result.parent_state_hash}")
    return 0


if __name__ == "__main__":  # pragma: no cover - module execution entry
    raise SystemExit(main())
