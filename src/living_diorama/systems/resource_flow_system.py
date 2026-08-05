"""Districts share existing resources across open boundaries.

This system moves quantity that already exists. It never creates or destroys
resources: whatever leaves one district arrives in another, and the totals are
checked before anything is committed.
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING

from living_diorama.entities import EntityId, ResourceType
from living_diorama.events import Event, EventBus, EventType, JsonValue
from living_diorama.systems._flow_allocation import allocate
from living_diorama.systems._resource_config import (
    FLOAT_TOLERANCE,
    RESOURCE_ORDER,
    build_pool,
    clamp_near_zero,
    fsum_ordered,
    require_finite,
    stock_snapshot,
    validate_allocation,
    validate_reserve_ticks,
)
from living_diorama.systems.base_system import BaseSystem

if TYPE_CHECKING:  # pragma: no cover - import exists for typing only
    from living_diorama.simulation.world import World

type _Snapshot = dict[EntityId, dict[ResourceType, float]]
type _Adjacency = dict[EntityId, set[EntityId]]
type _PairBoundary = dict[tuple[EntityId, EntityId], EntityId]
type _StagedTransfers = dict[tuple[ResourceType, EntityId, EntityId], float]


def _total_of(stocks: _Snapshot, resource: ResourceType) -> float:
    """Sum one resource across every district, in sorted district order."""
    return fsum_ordered(stocks[district_id][resource] for district_id in sorted(stocks))


class ResourceFlowSystem(BaseSystem):
    """Moves surplus resources to connected districts that are short of them.

    **Gated by a law.** Sharing happens only while the configured law is both
    active and set to boolean ``True``. The law identifier is supplied at
    construction rather than discovered by name at runtime, so the binding
    between this system and the rule it obeys is explicit and reviewable.

    **Staged, not incremental.** Every decision is computed from a single
    snapshot of stock taken before anything moves, and all deltas are applied
    at once at the end. Mutating districts while traversing boundaries would
    make outcomes depend on traversal order and would let resources cascade
    several hops in one tick.

    **Fair on both sides, and blind to names.** Within a resource, allocation is
    delegated to :func:`living_diorama.systems._flow_allocation.allocate`, which
    divides a donor's surplus across its receivers in proportion to their need,
    divides a receiver's capacity across its donors in proportion to their
    surplus, recovers any throughput that fair split would have stranded, and
    then settles on the unique fair point of the maximum-flow set. District
    identifiers order traversal and event output; they never decide which
    district gives up more.

    **Reserve model.** A district holds back ``reserve_ticks`` worth of its own
    consumption before any stock counts as shareable. The same consumption
    allocation ConsumptionSystem uses is supplied here separately and copied
    defensively -- reaching into another system instance for its configuration
    would couple the two together, which the architecture forbids.

    The system is stateless between ticks: it holds only its configuration, and
    no snapshot, graph, or staged transfer survives ``update``.
    """

    __slots__ = ("_consumption_allocation", "_law_id", "_reserve_ticks")

    def __init__(
        self,
        law_id: EntityId,
        consumption_allocation: Mapping[ResourceType, float],
        reserve_ticks: float,
    ) -> None:
        """Create a flow system bound to one sharing law.

        Args:
            law_id: Identifier of the law that permits sharing. Looked up in
                the world on every update.
            consumption_allocation: Normalized weight per resource kind, used
                to size each district's reserve. Defensively copied.
            reserve_ticks: How many ticks of its own consumption a district
                holds back before its stock counts as surplus.

        Raises:
            TypeError: If ``law_id`` is not a string, or if the allocation or
                reserve horizon is the wrong kind.
            ValueError: If ``law_id`` is blank, or the allocation or reserve
                horizon holds an invalid value.
        """
        if not isinstance(law_id, str):
            raise TypeError(f"law_id must be a str, got {type(law_id).__name__}")
        stripped = law_id.strip()
        if not stripped:
            raise ValueError("law_id must be a non-empty string")

        self._law_id = stripped
        self._consumption_allocation = validate_allocation(
            consumption_allocation, "consumption allocation"
        )
        self._reserve_ticks = validate_reserve_ticks(reserve_ticks)

    @property
    def law_id(self) -> EntityId:
        """Identifier of the law that gates sharing."""
        return self._law_id

    @property
    def consumption_allocation(self) -> Mapping[ResourceType, float]:
        """Read-only view of the weights used to size district reserves."""
        return self._consumption_allocation

    @property
    def reserve_ticks(self) -> float:
        """How many ticks of consumption a district holds back before sharing."""
        return self._reserve_ticks

    def update(self, world: "World", bus: EventBus) -> None:
        """Stage, validate, apply, and announce this tick's resource transfers.

        Args:
            world: The world whose districts share resources.
            bus: The bus on which transfer events are published.

        Raises:
            KeyError: If the configured law is not present in the world.
            TypeError: If the law's current value is not a bool.
            ValueError: If a boundary references an unresolvable wall, if a
                computed value is invalid, or if resources are not conserved.
        """
        if not self._sharing_enabled(world):
            return

        snapshot = self._snapshot_stocks(world)
        adjacency, pair_boundaries = self._eligible_graph(world)
        if not adjacency:
            return

        staged = self._stage_transfers(world, snapshot, adjacency)
        if not staged:
            return

        new_stocks = self._apply_deltas(snapshot, staged)
        self._verify_conservation(snapshot, new_stocks)
        self._commit(world, snapshot, new_stocks)
        self._publish(bus, world.tick, staged, pair_boundaries)

    def _sharing_enabled(self, world: "World") -> bool:
        """Return whether the configured law currently permits sharing.

        The law's value is type-checked on every update even when sharing turns
        out to be disabled, so a malformed law is reported the tick it appears
        rather than the tick it first matters. Truthiness is deliberately not
        used: the integer 1 is not permission to share.

        Raises:
            KeyError: If the configured law is absent from the world.
            TypeError: If the law's current value is not a bool.
        """
        law = world.get_law(self._law_id)
        if type(law.current_value) is not bool:
            raise TypeError(
                f"law {self._law_id!r} must carry a bool current_value, "
                f"got {type(law.current_value).__name__}"
            )
        return law.active is True and law.current_value is True

    @staticmethod
    def _snapshot_stocks(world: "World") -> _Snapshot:
        """Read every district's stock once, before anything moves."""
        return {
            district_id: stock_snapshot(world.districts[district_id].resources)
            for district_id in sorted(world.districts)
        }

    @staticmethod
    def _eligible_graph(world: "World") -> tuple[_Adjacency, _PairBoundary]:
        """Build the undirected graph of boundaries resources may cross.

        A boundary is eligible unless an active wall stands on it. An inactive
        wall -- including a permanent one that has been deactivated -- remains
        part of the world's history but does not obstruct resources.

        When several eligible boundaries connect the same two districts, the
        smallest boundary identifier is kept for that pair. The pair is a single
        connection regardless of how many boundaries describe it, so capacity is
        never multiplied by duplicating edges.

        Raises:
            ValueError: If a boundary names a wall that cannot be resolved.
        """
        adjacency: _Adjacency = {}
        pair_boundaries: _PairBoundary = {}

        for boundary_id in sorted(world.boundaries):
            boundary = world.boundaries[boundary_id]
            if boundary.wall_id is not None:
                wall = world.walls.get(boundary.wall_id)
                if wall is None:
                    raise ValueError(
                        f"boundary {boundary_id!r} references unresolvable wall "
                        f"{boundary.wall_id!r}"
                    )
                if wall.active:
                    continue

            first, second = sorted((boundary.district_a_id, boundary.district_b_id))
            adjacency.setdefault(first, set()).add(second)
            adjacency.setdefault(second, set()).add(first)
            pair_boundaries.setdefault((first, second), boundary_id)

        return adjacency, pair_boundaries

    def _reserve_target(
        self, world: "World", district_id: EntityId, resource: ResourceType
    ) -> float:
        """Compute how much of one resource a district holds back from sharing."""
        district = world.districts[district_id]
        return require_finite(
            float(district.population)
            * float(district.consumption_rate)
            * self._consumption_allocation[resource]
            * self._reserve_ticks,
            f"reserve target of {resource.value} in {district_id!r}",
        )

    def _stage_transfers(
        self, world: "World", snapshot: _Snapshot, adjacency: _Adjacency
    ) -> _StagedTransfers:
        """Decide every transfer without touching the world.

        Roles are fixed from the snapshot: for a given resource a district is a
        donor if it began the update with surplus, a receiver if it began with
        unmet need, and neither if it sat exactly on its reserve. Because roles
        never change mid-update, a district cannot pass along stock it received
        during this same tick, and multi-hop movement can only happen across
        successive ticks.

        The per-resource arithmetic is delegated to the allocation module, which
        works purely in quantities and identifiers and never sees the world.
        """
        staged: _StagedTransfers = {}

        for resource in RESOURCE_ORDER:
            surplus: dict[EntityId, float] = {}
            need: dict[EntityId, float] = {}

            for district_id in snapshot:
                stock = snapshot[district_id][resource]
                target = self._reserve_target(world, district_id, resource)
                if stock - target > FLOAT_TOLERANCE:
                    surplus[district_id] = stock - target
                elif target - stock > FLOAT_TOLERANCE:
                    need[district_id] = target - stock

            if not surplus or not need:
                continue

            for (donor_id, receiver_id), amount in allocate(surplus, need, adjacency).items():
                staged[(resource, donor_id, receiver_id)] = amount

        return staged

    @staticmethod
    def _apply_deltas(snapshot: _Snapshot, staged: _StagedTransfers) -> _Snapshot:
        """Compute every district's post-transfer stock from the snapshot.

        Outgoing and incoming amounts are summed per district first and applied
        in one step, so no intermediate half-applied state exists.
        """
        outgoing: dict[tuple[EntityId, ResourceType], float] = {}
        incoming: dict[tuple[EntityId, ResourceType], float] = {}

        for (resource, donor_id, receiver_id), amount in staged.items():
            out_key = (donor_id, resource)
            in_key = (receiver_id, resource)
            outgoing[out_key] = outgoing.get(out_key, 0.0) + amount
            incoming[in_key] = incoming.get(in_key, 0.0) + amount

        new_stocks: _Snapshot = {}
        for district_id in sorted(snapshot):
            amounts: dict[ResourceType, float] = {}
            for resource in RESOURCE_ORDER:
                key = (district_id, resource)
                value = (
                    snapshot[district_id][resource]
                    - outgoing.get(key, 0.0)
                    + incoming.get(key, 0.0)
                )
                amounts[resource] = clamp_near_zero(
                    value, f"post-transfer stock of {resource.value} in {district_id!r}"
                )
            new_stocks[district_id] = amounts
        return new_stocks

    @staticmethod
    def _verify_conservation(snapshot: _Snapshot, new_stocks: _Snapshot) -> None:
        """Confirm each resource's world total is unchanged, before committing.

        Checked per resource rather than in aggregate, so a transfer that
        somehow moved quantity between resource kinds could not cancel out.

        Raises:
            ValueError: If any resource total moved by more than the tolerance.
        """
        for resource in RESOURCE_ORDER:
            before = _total_of(snapshot, resource)
            after = _total_of(new_stocks, resource)
            if abs(before - after) > FLOAT_TOLERANCE:
                raise ValueError(
                    f"resource flow did not conserve {resource.value}: "
                    f"{before} before, {after} after"
                )

    @staticmethod
    def _commit(world: "World", snapshot: _Snapshot, new_stocks: _Snapshot) -> None:
        """Replace the resource pool of every district whose stock changed.

        Districts with no staged transfer keep their existing pool object, which
        makes "was this district involved" observable by identity.
        """
        for district_id in sorted(new_stocks):
            amounts = new_stocks[district_id]
            unchanged = all(
                abs(amounts[resource] - snapshot[district_id][resource]) <= FLOAT_TOLERANCE
                for resource in RESOURCE_ORDER
            )
            if unchanged:
                continue
            world.districts[district_id].resources = build_pool(amounts)

    @staticmethod
    def _publish(
        bus: EventBus,
        tick: int,
        staged: _StagedTransfers,
        pair_boundaries: _PairBoundary,
    ) -> None:
        """Announce every applied transfer in a fixed, reproducible order.

        Sorted by explicit resource order first, then donor identifier, then
        receiver identifier. The boundary identifier is the smallest eligible
        one for that pair, so duplicate boundaries never produce duplicate or
        ambiguous events.
        """
        resource_rank = {resource: index for index, resource in enumerate(RESOURCE_ORDER)}
        ordered = sorted(
            staged.items(),
            key=lambda item: (resource_rank[item[0][0]], item[0][1], item[0][2]),
        )

        for (resource, donor_id, receiver_id), amount in ordered:
            if amount <= FLOAT_TOLERANCE:
                continue
            pair = (donor_id, receiver_id) if donor_id < receiver_id else (receiver_id, donor_id)
            payload: dict[str, JsonValue] = {
                "from_district_id": donor_id,
                "to_district_id": receiver_id,
                "boundary_id": pair_boundaries[pair],
                "resource_type": resource.value,
                "amount": amount,
            }
            bus.publish(
                Event(
                    tick=tick,
                    type=EventType.RESOURCE_TRANSFERRED,
                    payload=payload,
                    source_id=donor_id,
                )
            )

