"""People leave districts that cannot feed them for neighbours that can."""

from collections.abc import Mapping
from typing import TYPE_CHECKING

from living_diorama.entities import District, EntityId, IsolationState, ResourceType
from living_diorama.events import Event, EventBus, EventType
from living_diorama.events.event import FrozenJsonValue
from living_diorama.systems._pressure import shortfall_ratio, validate_unit_scalar
from living_diorama.systems._resource_config import FLOAT_TOLERANCE, validate_allocation
from living_diorama.systems._topology import Adjacency, boundary_between, eligible_graph
from living_diorama.systems.base_system import BaseSystem

if TYPE_CHECKING:  # pragma: no cover - import exists for typing only
    from living_diorama.simulation.world import World

type _Moves = dict[tuple[EntityId, EntityId], int]


class MigrationSystem(BaseSystem):
    """Moves aggregate population from pressured districts to better neighbours.

    Runs after resources have been produced, consumed, and shared, so the
    pressure it reads is what a district is actually left holding this tick
    rather than what it started with.

    **Permission first.** Movement is governed by the same law that governs
    resource sharing: ``movement_resource_sharing`` covers the movement of
    people as well as of goods. The law identifier is supplied at construction
    and looked up on every update, and movement happens only while the law is
    both active and set to boolean ``True``. When it is not, this system
    changes nothing and announces nothing.

    **Who leaves.** A district's pressure is the fraction of its projected
    demand its stock cannot cover -- the same measure ScarcitySystem records.
    The number of people willing to leave is that pressure times the district's
    population times a configured migration rate, floored to a whole number.
    Nobody leaves a district that is meeting its needs, and a district under
    total failure still only sheds the configured fraction, because migration
    is a trickle rather than an evacuation.

    **Where they go.** Only directly connected districts whose pressure is
    lower by more than a configured margin, and which have housing to spare.
    The margin is what stops people shuffling back and forth between two
    districts whose pressures differ by a rounding error. Movers are split
    across those destinations in proportion to how much better each one is.

    **How many the route carries.** Isolation limits throughput rather than
    preference. Each route from a source to a destination can carry at most the
    destination's isolation factor times the movers on offer, as a whole-person
    count. Expressing it as a share of attractiveness would do nothing at all
    when a district has only one destination, because normalizing one weight
    cancels any factor applied to it. People a route cannot carry are offered
    to the source's other destinations that still have room, and any who remain
    unplaced simply stay home.

    **Staged, not incremental.** Every decision comes from one snapshot taken
    before anyone moves, and all movements are applied together at the end. A
    district that receives people this tick does not become a more attractive
    destination for a second district in the same tick, and people who arrive
    cannot move on again until the next one.

    The system consumes no randomness. Everything it decides follows from
    population, stock, and topology.
    """

    __slots__ = (
        "_consumption_allocation",
        "_law_id",
        "_migration_rate",
        "_min_pressure_gap",
        "_partial_isolation_factor",
    )

    def __init__(
        self,
        law_id: EntityId,
        consumption_allocation: Mapping[ResourceType, float],
        migration_rate: float,
        min_pressure_gap: float,
        partial_isolation_factor: float,
    ) -> None:
        """Create a migration system bound to one movement law.

        Args:
            law_id: Identifier of the law that permits movement. Looked up in
                the world on every update.
            consumption_allocation: Normalized weight per resource kind, used
                to size each district's demand. Defensively copied. Must match
                what ConsumptionSystem uses, or pressure would be measured
                against a demand the district never had.
            migration_rate: The largest fraction of a district's population
                that may leave in one tick, reached only at total resource
                failure. A value in 0.0-1.0.
            min_pressure_gap: How much lower a neighbour's pressure must be
                before it counts as materially better. A value in 0.0-1.0.
            partial_isolation_factor: What share of movement a partially
                isolated district can sustain, in each direction. A value in
                0.0-1.0, where 1.0 means partial isolation impedes nothing.

        Raises:
            TypeError: If ``law_id`` is not a string, or if the allocation or
                any scalar is the wrong kind.
            ValueError: If ``law_id`` is blank, the allocation is invalid, or a
                scalar falls outside 0.0-1.0.
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
        self._migration_rate = validate_unit_scalar(migration_rate, "migration_rate")
        self._min_pressure_gap = validate_unit_scalar(min_pressure_gap, "min_pressure_gap")
        self._partial_isolation_factor = validate_unit_scalar(
            partial_isolation_factor, "partial_isolation_factor"
        )

    @property
    def law_id(self) -> EntityId:
        """Identifier of the law that gates movement."""
        return self._law_id

    @property
    def consumption_allocation(self) -> Mapping[ResourceType, float]:
        """Read-only view of the weights used to size district demand."""
        return self._consumption_allocation

    @property
    def migration_rate(self) -> float:
        """Largest fraction of a population that may leave in one tick."""
        return self._migration_rate

    @property
    def min_pressure_gap(self) -> float:
        """How much better a neighbour must be to attract anyone."""
        return self._min_pressure_gap

    @property
    def partial_isolation_factor(self) -> float:
        """What share of movement a partially isolated district sustains."""
        return self._partial_isolation_factor

    def update(self, world: "World", bus: EventBus) -> None:
        """Move population toward relief, then announce every movement.

        Args:
            world: The world whose districts may lose or gain people.
            bus: The bus on which migration events are published.

        Raises:
            KeyError: If the configured law is not present in the world.
            TypeError: If the law's current value is not a bool.
            ValueError: If a boundary references an unresolvable wall, if a
                computed value is invalid, or if the staged movements would
                fail to conserve population.
        """
        if not self._movement_permitted(world):
            return

        adjacency, pair_boundaries = eligible_graph(world)
        if not adjacency:
            return

        pressure = {
            district_id: shortfall_ratio(world.districts[district_id], self._consumption_allocation)
            for district_id in sorted(world.districts)
        }
        headroom = {
            district_id: max(
                0,
                world.districts[district_id].housing_capacity
                - world.districts[district_id].population,
            )
            for district_id in sorted(world.districts)
        }

        offered = self._offer_movers(world, adjacency, pressure, headroom)
        accepted = self._accept_within_headroom(offered, headroom)
        if not accepted:
            return

        self._apply(world, accepted, headroom)
        self._publish(bus, world.tick, accepted, pressure, pair_boundaries)

    def _movement_permitted(self, world: "World") -> bool:
        """Return whether the configured law currently permits people to move.

        The law's value is type-checked on every update even when movement
        turns out to be forbidden, so a malformed law is reported the tick it
        appears rather than the tick it first matters. Truthiness is
        deliberately not used: the integer 1 is not permission to move.

        This mirrors what ResourceFlowSystem asks of the same law. It is stated
        again here rather than borrowed, because a system may not call another
        system; a test holds the two readings to the same answer.

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

    def _offer_movers(
        self,
        world: "World",
        adjacency: Adjacency,
        pressure: Mapping[EntityId, float],
        headroom: Mapping[EntityId, int],
    ) -> _Moves:
        """Decide how many people each district offers to each better neighbour.

        Each district is considered against the same snapshot, so no district's
        offer depends on another's having been considered first.
        """
        offered: _Moves = {}

        for source_id in sorted(world.districts):
            source = world.districts[source_id]
            source_factor = self._isolation_factor(source)
            if source_factor <= 0.0:
                continue

            source_pressure = pressure[source_id]
            if source_pressure <= FLOAT_TOLERANCE:
                continue

            movers = int(
                float(source.population) * self._migration_rate * source_pressure * source_factor
            )
            movers = min(movers, source.population)
            if movers <= 0:
                continue

            weights = self._destination_weights(world, adjacency, pressure, headroom, source_id)
            if not weights:
                continue

            limits = self._route_limits(world, weights, headroom, movers)
            for destination_id, count in _allocate_whole_people(movers, weights, limits).items():
                if count > 0:
                    offered[(source_id, destination_id)] = count

        return offered

    def _destination_weights(
        self,
        world: "World",
        adjacency: Adjacency,
        pressure: Mapping[EntityId, float],
        headroom: Mapping[EntityId, int],
        source_id: EntityId,
    ) -> dict[EntityId, float]:
        """Score each reachable neighbour by how much relief it offers.

        A neighbour qualifies only if it is not isolated, has housing to spare,
        and is better by more than the configured margin. Its weight is purely
        how much better it is: isolation is not folded in here, because a
        weight is relative and would vanish the moment a district had only one
        destination to compare. Isolation limits throughput instead, in
        :meth:`_route_limits`.
        """
        weights: dict[EntityId, float] = {}
        source_pressure = pressure[source_id]

        for destination_id in sorted(adjacency.get(source_id, set())):
            if destination_id == source_id or destination_id not in world.districts:
                continue
            if headroom[destination_id] <= 0:
                continue
            if self._isolation_factor(world.districts[destination_id]) <= 0.0:
                continue

            gap = source_pressure - pressure[destination_id]
            if gap <= self._min_pressure_gap or gap <= FLOAT_TOLERANCE:
                continue

            weights[destination_id] = gap

        return weights

    def _route_limits(
        self,
        world: "World",
        weights: Mapping[EntityId, float],
        headroom: Mapping[EntityId, int],
        movers: int,
    ) -> dict[EntityId, int]:
        """Cap how many people each route can actually carry.

        Two things bound a route: the destination's spare housing, and how
        freely it can be reached. The second is the isolation factor applied to
        the whole group on offer and floored to whole people, so a partially
        isolated destination genuinely takes fewer arrivals than an open one
        would -- including when it is the only destination available, which is
        precisely the case a relative weighting cannot express.
        """
        limits: dict[EntityId, int] = {}
        for destination_id in sorted(weights):
            factor = self._isolation_factor(world.districts[destination_id])
            throughput = int(movers * factor)
            limits[destination_id] = min(headroom[destination_id], throughput)
        return limits

    def _isolation_factor(self, district: District) -> float:
        """Return how freely people may cross this district's edge of the world.

        Isolation is a property of a district rather than of a boundary, so it
        applies on top of the wall rules the topology already enforces: an
        isolated district neither sends nor receives, and a partially isolated
        one does both at a reduced rate.
        """
        if district.isolation_state is IsolationState.ISOLATED:
            return 0.0
        if district.isolation_state is IsolationState.PARTIAL:
            return self._partial_isolation_factor
        return 1.0

    @staticmethod
    def _accept_within_headroom(offered: _Moves, headroom: Mapping[EntityId, int]) -> _Moves:
        """Trim arrivals so no destination is filled past its housing.

        Each district offers movers without knowing what other districts are
        offering, so a popular destination can be over-subscribed. Where that
        happens its housing is shared out among the incoming groups in
        proportion to their size, which keeps the split independent of which
        source happens to sort first. People who cannot be housed stay home.
        """
        incoming: dict[EntityId, int] = {}
        for (_source_id, destination_id), count in sorted(offered.items()):
            incoming[destination_id] = incoming.get(destination_id, 0) + count

        accepted: _Moves = dict(offered)
        for destination_id in sorted(incoming):
            total = incoming[destination_id]
            capacity = headroom[destination_id]
            if total <= capacity:
                continue

            claims = {
                source_id: float(count)
                for (source_id, target_id), count in sorted(offered.items())
                if target_id == destination_id
            }
            shares = _allocate_whole_people(capacity, claims, None)
            for source_id, share in shares.items():
                if share > 0:
                    accepted[(source_id, destination_id)] = share
                else:
                    accepted.pop((source_id, destination_id), None)

        return {edge: count for edge, count in accepted.items() if count > 0}

    @staticmethod
    def _apply(world: "World", accepted: _Moves, headroom: Mapping[EntityId, int]) -> None:
        """Apply every movement at once, then check nobody was lost or invented.

        Housing is enforced against the headroom measured before anyone moved,
        which is the only reading that means anything under simultaneous
        application: a district cannot make room for arrivals by counting the
        people leaving it in the same tick.

        A district may legitimately end the tick above its housing capacity if
        it began the tick that way. Over-capacity is a condition a world can
        already be in, and refusing to let such a district shed anyone would
        trap it there -- the opposite of what migration is for. What is refused
        is making it worse.

        Raises:
            ValueError: If the result would leave a district with a negative
                population, admit more arrivals than there was room for, push a
                district past its capacity, or change the world's total.
        """
        departures: dict[EntityId, int] = {}
        arrivals: dict[EntityId, int] = {}
        for (source_id, destination_id), count in sorted(accepted.items()):
            departures[source_id] = departures.get(source_id, 0) + count
            arrivals[destination_id] = arrivals.get(destination_id, 0) + count

        before = sum(world.districts[district_id].population for district_id in world.districts)

        for district_id in sorted(set(departures) | set(arrivals)):
            district = world.districts[district_id]
            arriving = arrivals.get(district_id, 0)
            if arriving > headroom[district_id]:
                raise ValueError(
                    f"migration would admit {arriving} people into {district_id!r}, "
                    f"which had room for {headroom[district_id]}"
                )

            updated = district.population - departures.get(district_id, 0) + arriving
            if updated < 0:
                raise ValueError(
                    f"migration would leave {district_id!r} with a negative population: {updated}"
                )
            if updated > district.housing_capacity and updated > district.population:
                raise ValueError(
                    f"migration would worsen over-capacity in {district_id!r}: "
                    f"{district.population} -> {updated} against {district.housing_capacity}"
                )
            district.population = updated

        after = sum(world.districts[district_id].population for district_id in world.districts)
        if before != after:
            raise ValueError(
                f"migration did not conserve population: {before} before, {after} after"
            )

    @staticmethod
    def _publish(
        bus: EventBus,
        tick: int,
        accepted: _Moves,
        pressure: Mapping[EntityId, float],
        pair_boundaries: Mapping[tuple[EntityId, EntityId], EntityId],
    ) -> None:
        """Announce every movement, ordered by origin and then destination."""
        for (source_id, destination_id), count in sorted(accepted.items()):
            payload: dict[str, FrozenJsonValue] = {
                "from_district_id": source_id,
                "to_district_id": destination_id,
                "boundary_id": boundary_between(dict(pair_boundaries), source_id, destination_id),
                "population_moved": count,
                "from_pressure": pressure[source_id],
                "to_pressure": pressure[destination_id],
            }
            bus.publish(
                Event(
                    tick=tick,
                    type=EventType.POPULATION_MIGRATED,
                    payload=payload,
                    source_id=source_id,
                )
            )


def _allocate_whole_people(
    total: int,
    weights: Mapping[EntityId, float],
    limits: Mapping[EntityId, int] | None,
) -> dict[EntityId, int]:
    """Split a whole number of people across weighted destinations.

    People are indivisible, so a proportional split almost never lands on whole
    numbers. The fractional parts are settled by the largest-remainder rule:
    everyone gets their whole share first, and the few people left over go to
    the destinations with the largest unfilled fractions.

    When a destination reaches its limit, the people it could not take are
    offered again to the destinations that still have room, so a constrained
    route does not strand movers who had somewhere else to go. Anyone still
    unplaced when every route is full simply stays home.

    Exactly one situation needs a further tie-break -- two destinations with
    identical remainders competing for a single indivisible person -- and it is
    settled by the smaller destination identifier. That is the only point in
    this system where an identifier affects an outcome, it can never move more
    than one person per destination, and it is directly tested. Everywhere else
    identifiers only order traversal.

    Args:
        total: How many people to place.
        weights: Relative attractiveness per destination. Non-positive weights
            are ignored.
        limits: Optional cap per destination, covering both spare housing and
            route throughput.

    Returns:
        Whole people per destination, summing to at most ``total``.
    """
    usable = {key: value for key, value in sorted(weights.items()) if value > FLOAT_TOLERANCE}
    if total <= 0 or not usable:
        return {}

    placed: dict[EntityId, int] = {}
    remaining = total
    capacity = dict(limits) if limits is not None else None

    for _ in range(len(usable) + 1):
        candidates = {
            key: value
            for key, value in usable.items()
            if capacity is None or capacity.get(key, 0) - placed.get(key, 0) > 0
        }
        if remaining <= 0 or not candidates:
            break

        round_shares = _largest_remainder(remaining, candidates)
        moved_this_round = 0
        for key in sorted(round_shares):
            share = round_shares[key]
            if capacity is not None:
                share = min(share, capacity.get(key, 0) - placed.get(key, 0))
            if share <= 0:
                continue
            placed[key] = placed.get(key, 0) + share
            remaining -= share
            moved_this_round += share

        if moved_this_round == 0:
            break

    return placed


def _largest_remainder(total: int, weights: Mapping[EntityId, float]) -> dict[EntityId, int]:
    """Distribute a whole number in proportion to weights, largest remainder first."""
    weight_total = sum(weights[key] for key in sorted(weights))
    if weight_total <= FLOAT_TOLERANCE:
        return {}

    exact = {key: total * weights[key] / weight_total for key in sorted(weights)}
    shares = {key: int(value) for key, value in exact.items()}
    leftover = total - sum(shares.values())

    if leftover > 0:
        ranked = sorted(exact, key=lambda key: (-(exact[key] - int(exact[key])), key))
        for key in ranked[:leftover]:
            shares[key] += 1

    return shares
