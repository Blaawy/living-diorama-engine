"""OPEN presentation-trajectory pedestrian mobility, profile V2.

Pure Python by design -- no ``bpy``. This module is the V2, ADDITIVE mobility
profile: every visible pedestrian proxy is given a genuinely OPEN presentation
trajectory across the REAL pedestrian topology (the same offer of proven-clear
ground :func:`pedestrian_topology.plan_pedestrian_topology` publishes), from
one real walkable anchor to a DIFFERENT real walkable anchor, with no
closed-loop concept anywhere in the document.

V2 is a separate document shape with its own validator. It deliberately does
NOT satisfy V1's closed-loop validator (``validate_mobility_plan``): a V2
walker's ``points`` are an open polyline and must never return to their own
start. ``mobility_profile="v1"`` is untouched and keeps today's exact
closed-loop behaviour; nothing in this file is reachable from the V1 path.

VOCABULARY AND TRUTH
--------------------
Each V2 pedestrian document is presentation-only motion across real topology.
It claims no home, no job, no errand and no destination. ``route_start``,
``route_end`` and ``waypoints`` are real topology candidates (never invented
coordinates); ``preferred_speed`` and ``start_offset`` are seeded
presentation values; ``social_grouping_state`` is a presentation grouping of
proxies that happen to share a route region; ``micro_behavior_schedule`` is a
cheap set of deterministic presentation events (look, pause,
wait-at-crossing, turn) at seeded points along the route. This is the same
posture the codebase already takes toward proxies: decorative motion using
real geometry.

SEED LAW
--------
Every random value is drawn from ``mobility_seed(mobility_spec, "v2", ...)``
(``stable_rng`` over the REAL ``mobility_seed`` input combined with the
proxy's real stable identity -- district + slot_index, via its ``slot`` id).
Python's global ``random`` module is never used unseeded. There is no wall
clock, no PID, no hostname and no filesystem discovery anywhere in this file.
"""

import hashlib
import json
import math

from mobility_spec import mobility_seed
from pedestrian_mobility import (
    GroundProbe,
    PedestrianMobilityError,
    PresenceIndex,
    gait_cycles,
    gait_digest,
    route_violations,
    selection_order,
    walker_count,
)
from pedestrian_topology import (
    ZONE_TYPES,
    build_presence_occupancy,
    plan_pedestrian_topology,
    street_occupancy_shapes,
)
from population_presence_spec import FIGURE_AXES
from vehicle_lane_network import polyline_length, resample_polyline

MOBILITY_PLAN_V2_FORMAT = "living_diorama_daily_life_mobility_plan_v2"
MOBILITY_PLAN_V2_SCHEMA_VERSION = 1

PRESENTATION_STATEMENT_V2 = (
    "Pedestrian movement in the open-trajectory presentation profile is "
    "deterministic presentation mobility. Each visible body is the same "
    "representative population proxy Phase 18 placed, walking a genuinely open "
    "route across topology the pedestrian plan proved clear: from one real "
    "walkable anchor to a different real walkable anchor, through real "
    "intermediate candidates, with no destination, no errand, no home and no "
    "individual schedule claimed. The motion is decorative presentation using "
    "real geometry and nothing more."
)
"""The sentence every V2 manifest must carry, so the claim is never overstated."""

MAX_ROUTE_ATTEMPTS = 64
"""How many seeded candidate sets one walker tries before its route is refused.

Each attempt tries TWO real route shapes over the SAME real topology, the SAME
safety thresholds and the SAME seeded rng: a straight single hop (see
``_v2_walker_route``) and the K-nearest exploratory multi-hop construction
below. More attempts give a walker whose geometry is merely awkward more
chances to find an already-safe route; a refusal still means every seeded
attempt failed a real check, never that the search gave up on the one shape
it tried first. The attempt index feeds the seed, so the whole search is
reproducible byte-for-byte (see the metamorphic determinism test).
"""

WAYPOINT_POOL = 24
"""The nearest candidates a route may thread, so an open route stays short.

The pool is every real candidate inside the walker's own walk budget of its
start (``preferred_speed * duration``), sorted nearest-first and capped here.
Raising the cap from 16 to 24 lets a route thread, or end at, the real
candidates ranked 17th-24th nearest -- they are still real anchors inside the
walker's own budget, so a proxy whose only smooth route ends at one of them
was refused purely because the search never looked at it.
"""

MIN_ROUTE_LENGTH = 2.5
"""The shortest route that is still a walk rather than a shuffle."""

MAX_END_DISTANCE = 24.0
"""How far past its start a walker's far end may stand, so routes read as
one short walk, not a cross-town march."""

ROUTE_EXPLORE_K = 4
"""How many of the nearest not-yet-used candidates a route-construction step
draws from. A pure nearest-next pick rebuilds the identical polyline on
every retry attempt (real float distances essentially never tie), so a path
that clips an obstacle or turns too sharply on attempt 1 clips it the same
way on every later attempt. Drawing from the K nearest, weighted toward the
nearest, gives each attempt's seeded rng a real chance to explore a
genuinely different, still-short construction.

This K-nearest rule is exactly why the search ALSO tries a straight
single-hop shape first (see ``_v2_walker_route``): a hop to a farther
candidate is never among the K nearest of the current point, so without that
extra shape a two-point straight route is never constructed at all.
"""

GROUP_RADIUS = 60.0
"""Two walkers whose route starts stand within this distance share a route
region and may be presented as a small social group."""

MICRO_EVENT_TYPES = ("look", "pause", "wait_at_crossing", "turn")
"""The cheap deterministic presentation events a walker may carry."""

PAUSE_TYPES = frozenset({"pause", "wait_at_crossing"})
"""Micro events that actually stop the body; the rest are annotations."""


class PedestrianMobilityV2Error(ValueError):
    """An open-trajectory mobility contract violation.

    Raised when the city cannot carry the declared open routes. Always a
    refusal, never a repair.
    """


# ---------------------------------------------------------------------------
# Topology access
# ---------------------------------------------------------------------------


def flatten_topology(topology: dict) -> list[dict]:
    """Every real walkable candidate in one stable order, with an anchor id.

    Each candidate gets ``anchor_id = "<district>__<zone>__<index:03d>`` so a
    V2 document can name exactly which real anchor it uses. The order is the
    topology's own published order (sorted district, fixed zone order, the
    candidates themselves in their published order), so any later selection
    over this list is stable across runs, machines and ``PYTHONHASHSEED``.
    """
    flat: list[dict] = []
    for district in sorted(topology["zones"]):
        zones = topology["zones"][district]
        for zone in ZONE_TYPES:
            for index, candidate in enumerate(zones.get(zone, [])):
                entry = dict(candidate)
                entry["anchor_id"] = f"{district}__{zone}__{index:03d}"
                entry["district"] = district
                entry["zone"] = zone
                flat.append(entry)
    return flat


def _nearest_candidate(candidates: list[dict], x: float, y: float) -> dict | None:
    """The real topology candidate closest to a 2D point, or None if none."""
    best: tuple[float, dict] | None = None
    for candidate in candidates:
        gap = math.hypot(candidate["x"] - x, candidate["y"] - y)
        if best is None or gap < best[0]:
            best = (gap, candidate)
    return None if best is None else best[1]


def _candidate_distance(first: dict, second: dict) -> float:
    return math.hypot(first["x"] - second["x"], first["y"] - second["y"])


# ---------------------------------------------------------------------------
# Per-walker trajectory
# ---------------------------------------------------------------------------


def open_path_turn_violations(
    loop: list[tuple[float, float]], natural_speed: float, mobility_spec: dict
) -> list[str]:
    """Every place an OPEN route turns faster than a body could turn.

    The V2 sibling of :func:`pedestrian_mobility.turn_rate_violations` with
    the closed-loop assumption removed. The V1 function is written for a
    CLOSED loop: at its first resampled point the "previous" point it
    compares against is the loop's OWN END, and at its last resampled point
    the "next" point it wraps to is the loop's OWN START -- a phantom closing
    chord neither loop-shaped V1 nor open-shaped V2 bodies ever actually
    walk. For an open polyline that phantom chord reverses direction almost
    180 degrees at the seam, so the V1 check reports an inherent turn rate of
    1700+ deg/s against the declared limit for EVERY open route of any real
    length. This function measures turn rate ONLY between real consecutive
    resampled points: a path of N points has N-1 segments and N-2 interior
    turns, and no turn is measured at the very first or very last point of
    the open path, because there is no incoming direction before the first
    point and no outgoing direction after the last. The resampling step, the
    speed-to-turn-rate arithmetic and the violation-message format are
    identical to the V1 function; only the two wrap-around comparisons are
    gone.
    """
    limit = math.radians(mobility_spec["pedestrians"]["route"]["max_turn_rate_deg_s"])
    step = mobility_spec["pedestrians"]["route"]["sample_step"]
    points = resample_polyline(loop, step)
    errors: list[str] = []
    for point_index in range(1, len(points) - 1):
        a, b, c = points[point_index - 1], points[point_index], points[point_index + 1]
        first = math.atan2(b[1] - a[1], b[0] - a[0])
        second = math.atan2(c[1] - b[1], c[0] - b[0])
        turn = abs(math.atan2(math.sin(second - first), math.cos(second - first)))
        travelled = math.hypot(b[0] - a[0], b[1] - a[1])
        if travelled <= 1.0e-9:
            continue
        rate = turn * natural_speed / travelled
        if rate > limit:
            errors.append(
                f"({b[0]:.2f}, {b[1]:.2f}) turns at {math.degrees(rate):.0f} deg/s, above the "
                f"declared {mobility_spec['pedestrians']['route']['max_turn_rate_deg_s']}"
            )
            break
    return errors


def gait_cycle_violation(route_length: float, proxy: dict, mobility_spec: dict) -> str | None:
    """The gait refusal for one candidate route length, or None when compatible.

    The plan resolves every accepted walker's gait with the SAME real function
    the V1 path uses (``pedestrian_mobility.gait_cycles``), and that function
    refuses a route whose real length cannot close on a WHOLE number of
    strides within the declared ``stride_tolerance``, and whose effective
    stride is beyond the body's real leg reach or swing ceiling. The route
    search must validate against that check BEFORE accepting a candidate --
    otherwise a length that only trips at gait/animation resolution crashes
    the whole plan AFTER the search has already committed to it (the real EP1
    regression: "closing this loop on 2 whole strides needs a 1.635m stride
    against a natural 1.328m, 23.1% off the declared 20% tolerance"). This
    helper runs the exact downstream function with the exact identity the plan
    will pass (the proxy's published figure axes plus its height), so the
    refusal message is the SAME real, categorized reason the plan would have
    raised -- just raised here, at search time, so the search tries its next
    candidate instead of crashing.

    Returns the refusal message, or ``None`` when the route length is
    gait-compatible.
    """
    identity = {
        **{axis: proxy[axis] for axis in FIGURE_AXES},
        "height": float(proxy["height"]),
    }
    try:
        gait_cycles(route_length, identity, mobility_spec)
    except PedestrianMobilityError as error:
        return str(error)
    return None


def _v2_walker_route(
    proxy: dict,
    district_candidates: list[dict],
    mobility_spec: dict,
    timeline: dict,
    preferred_speed: float,
    index: PresenceIndex,
    roads: list[dict],
    probe: GroundProbe,
    body_radius: float,
    occupied_anchors: list[dict] = (),
    separation: float | None = None,
) -> tuple[dict | None, str]:
    """One walker's open trajectory, or a refusal explaining why it has none.

    ``route_start`` is the real topology candidate nearest the proxy's own
    Phase 18 anchor -- the body begins exactly where it was standing. The
    waypoints and the ``route_end`` are further REAL candidates drawn from the
    same district's offer of proven-clear ground; the polyline threading them
    is proven clear along its whole length with the same ground validation the
    V1 planner already performs (``route_violations``) plus the OPEN-path turn
    check ``open_path_turn_violations`` -- the closed-loop
    ``turn_rate_violations`` is never used for an open route, because its
    wrap-around seam would reject every real open polyline. Nothing here ever
    invents a coordinate.

    ``preferred_speed`` is the walker's own assigned speed, fixed BEFORE any
    routing: the route-length bound is that speed times the episode, so the
    planner only ever offers a route the walker can physically finish and the
    V2 validator's per-walker speed check is satisfied by construction.

    Each seeded attempt tries TWO real shapes, both ending in the SAME safety
    gatekeeper ``_accept`` below:

    1. A STRAIGHT SINGLE HOP from the start to one pool candidate drawn with
       the attempt's own seeded rng, weighted toward the farther candidates.
       This shape is new: the multi-hop construction below only ever steps to
       one of the ``ROUTE_EXPLORE_K`` NEAREST candidates of its current
       point, so a two-point polyline (start, far end) with NO interior
       vertices was previously only reachable by accident when the pool or
       the budget exhausted after one hop. A two-point route has zero
       interior turns and therefore can never fail the open-path turn check
       -- exactly the category that dominates the real EP1 refusals. The hop
       is still a REAL anchor inside the walker's own budget and still has to
       pass every real check below.
    2. The K-nearest exploratory multi-hop construction, unchanged from the
       original search (its random stream is untouched, because the hop draw
       uses its own seed part), so every route the previous search could
       accept is still constructed and still accepted.

    The gatekeeper's checks end with the walker's own GAIT contract
    (``gait_cycle_violation``, the same ``gait_cycles`` the plan runs at gait
    resolution), so a route the search accepts can never crash the plan later
    on a whole-stride mismatch.

    ``occupied_anchors`` (real anchor coordinates of bodies already standing:
    every proxy's own anchor, plus the ends and starts other walkers already
    claimed) and ``separation`` (the plan's own pedestrian-pedestrian
    clearance) gate the route's FAR END: a route whose end stands within
    ``separation`` of an occupied anchor is refused here,
    exactly the measure the V2 collision verifier applies, and the search
    takes the next candidate in its existing deterministic order. With no
    occupied anchors the gate is inert and the search is byte-for-byte
    today's.
    """
    start = _nearest_candidate(district_candidates, float(proxy["x"]), float(proxy["y"]))
    if start is None:
        return None, "its district offers no walkable candidate"
    duration = float(timeline["duration_seconds"])
    # ``timeline["duration_seconds"]`` is the WHOLE episode -- (end_frame -
    # start_frame) / fps of the canonical timeline (8.0s for the locked
    # motion_time_v1.json), not a per-slot presentation duration -- so
    # ``speed * duration_seconds`` is the distance a body can cover across the
    # AVAILABLE PRESENTATION TIME. The bound is THIS walker's own assigned
    # preferred_speed times the episode, sized per walker instead of one
    # global value: the fastest walker (band max 1.55m/s) may attempt a
    # 12.4m route while a slow walker (band min 1.0m/s) is only offered
    # candidates it can actually finish in time. The V2 validator re-checks
    # every route against the walker's own assigned speed (route_length <=
    # preferred_speed * duration), so a route accepted under this bound can
    # never fail that check. (A single global speed_band["min"] * duration
    # bound was tried and is too conservative: it refuses real, achievable
    # routes such as the 9.09m and 9.46m open walks the real EP1 topology
    # produces.)
    max_length = preferred_speed * duration
    # Real topology candidates are tightly clustered (frontage 5.6m, plaza
    # 1.8m, park 3.0m, promenade 2.0m spacing in population_presence_v1.json),
    # so a short open walk threads candidates inside the walkable disc. The 16
    # NEAREST district-wide candidates are NOT a short walk: along a real
    # street they span 70-90m, which is why every real proxy was refused.
    #
    # The pool below is a RADIUS filter: every entry sits within ``max_length``
    # of the START point. A radius filter around the start does NOT bound the
    # LENGTH OF A MULTI-WAYPOINT POLYLINE through several of those candidates:
    # 2-3 waypoints each individually within ``max_length`` of the start but
    # scattered in different directions can zigzag to 30-40m of actual travel
    # and the sharp direction changes between scattered picks also produce
    # impossible turn rates (e.g. 747 deg/s against a 165 deg/s limit). The
    # construction below therefore threads the pool GREEDILY, checking the
    # real cumulative polyline length at every step, so the route is within
    # budget by construction.
    pool = [
        entry
        for entry in district_candidates
        if entry["anchor_id"] != start["anchor_id"]
        and _candidate_distance(entry, start) <= max_length
    ]
    pool.sort(key=lambda entry: _candidate_distance(entry, start))
    pool = pool[:WAYPOINT_POOL]
    last_reason = "no route candidate was available"

    def _accept(path: list[dict]) -> dict | None:
        """Run every real safety check on one candidate polyline.

        BOTH route shapes hand their finished polyline to this single
        gatekeeper, so a route accepted through either shape passes the exact
        same real checks, in the same order, with the same messages: distinct
        anchors, far end within ``MAX_END_DISTANCE``, length inside
        [MIN_ROUTE_LENGTH, max_length], proven-clear ground
        (``route_violations``), the open-path turn check at the walker's
        own ``preferred_speed``, and the walker's own GAIT contract
        (``gait_cycle_violation`` -- the same ``gait_cycles`` the plan runs
        at gait/animation resolution, so an accepted route can never crash
        the plan later on a whole-stride mismatch). ``last_reason`` records
        the specific failing check so a refusal still names a real geometric
        reason.
        """
        nonlocal last_reason
        route_end = path[-1]
        waypoints = path[1:-1]
        ids = [entry["anchor_id"] for entry in path]
        if len(set(ids)) < 2:
            return None
        if _candidate_distance(start, route_end) > MAX_END_DISTANCE:
            last_reason = "its far end stands too far from its start"
            return None
        # The route-end occupancy gate: a far end standing within the plan's
        # own pedestrian separation of an anchor a body occupies -- every
        # proxy's own anchor (stationary bodies hold theirs all episode,
        # movers until their own start offset), or an end or start another
        # walker already claimed -- would hold that 0.0m gap from arrival to
        # the final frame, the exact violation the V2 collision verifier
        # reports. Refuse it; the search takes the next candidate in order.
        if separation is not None and occupied_anchors:
            for occupied in occupied_anchors:
                if _candidate_distance(route_end, occupied) < separation:
                    last_reason = f"its far end stands within {separation}m of an occupied anchor"
                    return None
        loop_2d = [(entry["x"], entry["y"]) for entry in path]
        length = sum(
            math.hypot(loop_2d[i + 1][0] - loop_2d[i][0], loop_2d[i + 1][1] - loop_2d[i][1])
            for i in range(len(loop_2d) - 1)
        )
        # Final assertion/safety net: the greedy construction keeps cumulative
        # length within ``max_length`` by construction, so this check should
        # rarely if ever fire -- keep it anyway.
        if length < MIN_ROUTE_LENGTH or length > max_length:
            last_reason = (
                f"route length {length:.2f}m outside [{MIN_ROUTE_LENGTH}, {max_length:.2f}]"
            )
            return None
        violations = route_violations(
            loop_2d, proxy, index, roads, probe, mobility_spec, body_radius
        )
        if violations:
            last_reason = violations[0]
            return None
        turning = open_path_turn_violations(loop_2d, preferred_speed, mobility_spec)
        if turning:
            last_reason = turning[0]
            return None
        # Gait compatibility -- the plan's OWN downstream check. ``gait_cycles``
        # (pedestrian_mobility.py) refuses a route whose length cannot close on
        # a whole number of strides within the declared ``stride_tolerance``
        # (and whose effective stride is beyond the body's leg reach or swing
        # ceiling). That check used to run only AFTER the search had committed,
        # so a length the search never validated against crashed the whole plan
        # at gait resolution (the real EP1 regression: "closing this loop on 2
        # whole strides needs a 1.635m stride against a natural 1.328m, 23.1%
        # off the declared 20% tolerance"). Run it here with the SAME rounded
        # length (``round(length, 6)`` is exactly the ``route_length`` the plan
        # will pass to ``gait_cycles``) and the SAME identity the plan will use
        # (the proxy's published figure axes plus its height), so an
        # incompatible candidate is refused by the SEARCH with a real,
        # categorized reason and the next candidate is tried.
        gait_reason = gait_cycle_violation(round(length, 6), proxy, mobility_spec)
        if gait_reason is not None:
            last_reason = gait_reason
            return None
        points = [
            [round(entry["x"], 6), round(entry["y"], 6), round(float(proxy["z"]), 6)]
            for entry in path
        ]
        return {
            "slot": proxy["slot"],
            "district": proxy["district"],
            "slot_index": proxy["slot_index"],
            "zone": proxy["zone"],
            "source": proxy["source"],
            "anchor": {
                "x": float(proxy["x"]),
                "y": float(proxy["y"]),
                "z": float(proxy["z"]),
                "heading": float(proxy["heading"]),
            },
            "geometry_key": proxy["geometry_key"],
            "height": proxy["height"],
            **{axis: proxy[axis] for axis in FIGURE_AXES},
            "route_start": {
                "anchor_id": start["anchor_id"],
                "zone": start["zone"],
                "district": start["district"],
                "x": start["x"],
                "y": start["y"],
                "z": start["z"],
                "heading": start["heading"],
            },
            "route_end": {
                "anchor_id": route_end["anchor_id"],
                "zone": route_end["zone"],
                "district": route_end["district"],
                "x": route_end["x"],
                "y": route_end["y"],
                "z": route_end["z"],
                "heading": route_end["heading"],
            },
            "waypoints": [
                {
                    "anchor_id": entry["anchor_id"],
                    "zone": entry["zone"],
                    "x": entry["x"],
                    "y": entry["y"],
                    "z": entry["z"],
                }
                for entry in waypoints
            ],
            "points": points,
            "route_length": round(length, 6),
            "preferred_speed": preferred_speed,
        }

    for attempt in range(MAX_ROUTE_ATTEMPTS):
        # SHAPE 1 -- the straight single hop (new candidate space). Its draw
        # uses its OWN seed part ("hop"), so it never perturbs the multi-hop
        # construction's random stream below: every polyline the previous
        # search could build at this attempt is still built, byte for byte,
        # and this shape is purely ADDITIVE coverage on top of it.
        hop_rng = mobility_seed(mobility_spec, "v2", "route", proxy["slot"], str(attempt), "hop")
        if pool:
            # Seeded weighted draw over the whole pool, favoring the farther
            # candidates: a longer straight walk reads as a walk, not a
            # shuffle, and the farther anchors are exactly the ones the
            # K-nearest construction never first-picks.
            distances = [_candidate_distance(entry, start) for entry in pool]
            total = sum(distances)
            draw = hop_rng.random() * total
            cumulative = 0.0
            chosen = pool[-1]
            for entry, gap in zip(pool, distances, strict=True):
                cumulative += gap
                if draw < cumulative:
                    chosen = entry
                    break
            route = _accept([start, chosen])
            if route is not None:
                return route, ""
        # SHAPE 2 -- the K-nearest exploratory multi-hop construction
        # (unchanged construction; its polyline now passes through ``_accept``,
        # which runs the identical checks the inline block used to run).
        rng = mobility_seed(mobility_spec, "v2", "route", proxy["slot"], str(attempt))
        # K-nearest exploratory construction: each step ranks the not-yet-used
        # candidates by distance from the CURRENT last point (not the original
        # start), takes the K nearest, and lets THIS attempt's seeded rng pick
        # one of them with a weight that favors the nearest but leaves real
        # probability on the 2nd and 3rd nearest. A pure nearest-next pick
        # would rebuild the IDENTICAL polyline on every one of the attempts
        # -- real float distances essentially never tie -- and a path that
        # clipped an obstacle or turned too sharply on attempt 1 would clip it
        # the same way on attempts 2..N. The weighted draw makes each attempt
        # a genuinely different construction, while staying deterministic: the
        # same walker and attempt number always draw the same values,
        # so the whole plan is still reproducible byte-for-byte.
        # ``remaining_budget`` tracks the real remaining travel distance, so
        # the cumulative polyline length can never exceed the walker's own
        # bound: a candidate whose step would overshoot the budget is
        # rejected and the next-ranked candidate of the K is tried; when NO
        # candidate of the K fits, we stop exactly as the plain greedy
        # construction did.
        path = [start]
        used_ids = {start["anchor_id"]}
        remaining_budget = max_length
        used_segments: set[tuple] = set()
        while len(path) - 1 < WAYPOINT_POOL:
            current = path[-1]
            ranked = [
                (entry, _candidate_distance(entry, current))
                for entry in pool
                if entry["anchor_id"] not in used_ids
            ]
            ranked.sort(key=lambda pair: (pair[1], pair[0]["anchor_id"]))
            if not ranked:
                break  # every candidate in the pool is already threaded
            candidates = ranked[: min(ROUTE_EXPLORE_K, len(ranked))]
            # Weighted draw over the K nearest: the nearest carries weight K,
            # the next K-1, and so on, so the nearest stays the favourite but
            # the 2nd and 3rd nearest are genuinely reachable on other attempts.
            weights = [float(len(candidates) - rank) for rank in range(len(candidates))]
            draw = rng.random() * sum(weights)
            cumulative = 0.0
            chosen_index = 0
            for rank, weight in enumerate(weights):
                cumulative += weight
                if draw < cumulative:
                    chosen_index = rank
                    break
            chosen = candidates[chosen_index]
            # Accept the chosen candidate if its step fits the budget; otherwise
            # try the rest of the K nearest in ranked (nearest-first) order.
            order = [chosen] + [
                pair for pair in candidates if pair[0]["anchor_id"] != chosen[0]["anchor_id"]
            ]
            picked = None
            for entry, gap in order:
                if gap > remaining_budget:
                    continue
                # Reject a step whose exact directed vector (rounded) repeats
                # an earlier segment of THIS SAME path -- matches the
                # NO_VISIBLE_PEDESTRIAN_LOOP guard's own definition of a
                # "repeated directed sub-path" (mobility_metrics_v2's
                # ``_repeats_subpath``), so an accepted route never trips it.
                # Real topology candidates often sit on a regular grid, so two
                # consecutive hops of the same spacing in the same direction
                # are a real, otherwise-plausible risk without this check.
                segment_vector = (
                    round(float(entry["x"]) - float(current["x"]), 4),
                    round(float(entry["y"]) - float(current["y"]), 4),
                )
                if segment_vector in used_segments:
                    continue
                picked = (entry, gap, segment_vector)
                break
            if picked is None:
                break  # no candidate in the K nearest fits the remaining budget
            entry, gap, segment_vector = picked
            path.append(entry)
            used_ids.add(entry["anchor_id"])
            used_segments.add(segment_vector)
            remaining_budget -= gap
        if len(path) < 2:
            last_reason = "its district offers no second candidate within its walk budget"
            continue
        route = _accept(path)
        if route is not None:
            return route, ""
    return None, last_reason


# ---------------------------------------------------------------------------
# Distinct presentation values (speeds and start offsets)
# ---------------------------------------------------------------------------


def _assign_proxy_speeds(proxies: list[dict], mobility_spec: dict) -> dict[str, float]:
    """Give every proxy a distinct preferred speed inside the declared band.

    Assigned BEFORE any routing, so route-length bounds can be sized per
    walker from the walker's own actual assigned speed. Each proxy draws ONE
    number from a generator seeded by its own slot id; ranking those draws and
    spreading the band across the ranks guarantees distinct values for any
    crowd of two or more, deterministically. A fast walker may therefore
    attempt a longer open route and a slow walker is only offered a short one
    -- exactly the correlation the V2 validator enforces (route_length <=
    preferred_speed * duration).
    """
    band = mobility_spec["pedestrians"]["speed"]
    low, high = float(band["min"]), float(band["max"])
    if len(proxies) <= 1:
        return {proxy["slot"]: round(low, 4) for proxy in proxies}
    draws = {
        proxy["slot"]: mobility_seed(mobility_spec, "v2", "speed", proxy["slot"]).random()
        for proxy in proxies
    }
    ranked = sorted(proxies, key=lambda proxy: (draws[proxy["slot"]], proxy["slot"]))
    speeds: dict[str, float] = {}
    for rank, proxy in enumerate(ranked):
        share = rank / (len(ranked) - 1)
        speeds[proxy["slot"]] = round(low + (high - low) * share, 4)
    return speeds


def _assign_start_offsets(walkers: list[dict], mobility_spec: dict, timeline: dict) -> None:
    """Give every walker a distinct start offset inside the episode.

    Each walker draws one number from its own seeded generator, then lands in
    its own disjoint slot of the episode duration: walker ``rank`` starts in
    ``[rank/n, (rank+1)/n)`` of the span, so no two walkers share an offset and
    the crowd never begins moving as one.
    """
    duration = float(timeline["duration_seconds"])
    count = len(walkers)
    ordered = sorted(walkers, key=lambda walker: walker["slot"])
    for rank, walker in enumerate(ordered):
        draw = mobility_seed(mobility_spec, "v2", "offset", walker["slot"]).random()
        walker["start_offset"] = round((rank + draw) * duration / count, 3)


# ---------------------------------------------------------------------------
# Presentation grouping
# ---------------------------------------------------------------------------


def _assign_groups(walkers: list[dict]) -> None:
    """Group walkers whose route starts share a region; the rest stay solo.

    Deterministic and geometry-driven (no randomness): walkers are paired in
    slot order when their route starts stand within ``GROUP_RADIUS`` of each
    other in the same district, optionally extended to three or four members.
    Group members are NEVER perfectly synchronized: the per-member distinct
    speeds and distinct start offsets already guarantee small per-member
    offsets. Solo walkers are guaranteed whenever there are more walkers than
    the groups absorb.
    """
    grouped: set[int] = set()
    group_id_counter = 0
    for left in range(len(walkers)):
        if left in grouped:
            continue
        best: tuple[float, int] | None = None
        for right in range(left + 1, len(walkers)):
            if right in grouped:
                continue
            if walkers[left]["district"] != walkers[right]["district"]:
                continue
            gap = _candidate_distance(walkers[left]["route_start"], walkers[right]["route_start"])
            if gap <= GROUP_RADIUS and (best is None or gap < best[0]):
                best = (gap, right)
        if best is None:
            continue
        members = [left, best[1]]
        grouped.update(members)
        while len(members) < 4:
            candidates = [
                other
                for other in range(len(walkers))
                if other not in grouped
                and walkers[other]["district"] == walkers[left]["district"]
                and _candidate_distance(
                    walkers[other]["route_start"], walkers[members[0]]["route_start"]
                )
                <= GROUP_RADIUS
            ]
            if not candidates:
                break
            centroid_x = sum(walkers[m]["route_start"]["x"] for m in members) / len(members)
            centroid_y = sum(walkers[m]["route_start"]["y"] for m in members) / len(members)
            nearest = min(
                candidates,
                key=lambda other: math.hypot(
                    walkers[other]["route_start"]["x"] - centroid_x,
                    walkers[other]["route_start"]["y"] - centroid_y,
                ),
            )
            members.append(nearest)
            grouped.add(nearest)
        group_id_counter += 1
        group_id = f"v2_group_{group_id_counter:02d}"
        for member_index, member in enumerate(members):
            walkers[member]["social_grouping_state"] = {
                "group": group_id,
                "members": len(members),
                "role": "lead" if member_index == 0 else "member",
                "member_index": member_index,
            }
    for walker in walkers:
        walker.setdefault("social_grouping_state", {"group": None})


# ---------------------------------------------------------------------------
# Micro behaviour events
# ---------------------------------------------------------------------------


def _assign_micro_behavior(walkers: list[dict], mobility_spec: dict, timeline: dict) -> None:
    """Give each walker 0-3 cheap deterministic presentation events.

    Every event is a seeded draw on the walker's own generator: a position
    along the route (as travelled distance), the frame it falls on, and a
    duration. Pause-like events carry a frame count the applier honors by
    holding the body; look and turn events are annotations on the route.
    """
    fps = float(timeline["fps"])
    start_frame = int(timeline["start_frame"])
    end_frame = int(timeline["end_frame"])
    for walker in walkers:
        rng = mobility_seed(mobility_spec, "v2", "micro", walker["slot"])
        count = int(rng.random() * 4)  # zero to three events
        events: list[dict] = []
        length = walker["route_length"]
        speed = walker["preferred_speed"]
        for _index in range(count):
            event_type = MICRO_EVENT_TYPES[int(rng.random() * len(MICRO_EVENT_TYPES))]
            at = rng.uniform(0.12, 0.88) * length
            frame = start_frame + walker["start_offset"] * fps + at / speed * fps
            duration = 0
            if event_type in PAUSE_TYPES:
                duration = int(12 + rng.random() * 28)
            events.append(
                {
                    "type": event_type,
                    "s": round(at, 4),
                    "frame": max(start_frame, min(end_frame, int(round(frame)))),
                    "duration_frames": duration,
                }
            )
        events.sort(key=lambda entry: entry["s"])
        walker["micro_behavior_schedule"] = events


# ---------------------------------------------------------------------------
# The V2 plan
# ---------------------------------------------------------------------------


def plan_pedestrian_mobility_v2(
    presence_plan: dict,
    presence_spec: dict,
    mobility_spec: dict,
    timeline: dict,
    master_spec: dict,
    production_spec: dict,
    graph: dict,
    fabric_plan: dict,
) -> dict:
    """Which of the city's proxies walk open presentation routes, and exactly where.

    The moving set is the SAME real crowd V1 derives (same declared fraction,
    same per-slot selection order); only the trajectory shape is new. The
    topology is planned from the real specs, never invented. Every proxy's
    preferred_speed is assigned deterministically BEFORE routing, so each
    walker's route-length bound is sized from its own speed. A slot whose
    ground cannot carry an open route is skipped with its reason recorded and
    the next eligible slot takes its place -- deterministic fallback, never a
    silent unsafe route. A pool that exhausts below the declared count is
    reported honestly rather than forced: ``moving`` may be below
    ``requested_moving`` when the real topology genuinely cannot carry an
    open route for every declared proxy, and every unreached slot's real
    geometric reason is recorded in ``refused`` -- never a silent shortfall
    and never a fabricated route.

    Route ENDS additionally respect the plan's own pedestrian separation: the
    placement pass refuses any route end that stands within ``separation``
    of an anchor a body occupies -- every proxy's own anchor (a stationary
    body holds it for the whole episode, a mover until its own start offset
    elapses), or an end or start another walker already claimed. Refusing a
    candidate end simply takes the next one in the same seeded order.
    """
    proxies = list(presence_plan["proxies"])
    wanted = walker_count(len(proxies), mobility_spec)
    speeds = _assign_proxy_speeds(proxies, mobility_spec)
    topology = plan_pedestrian_topology(
        master_spec, production_spec, graph, fabric_plan, presence_spec
    )
    candidates_by_district: dict[str, list[dict]] = {}
    for entry in flatten_topology(topology):
        candidates_by_district.setdefault(entry["district"], []).append(entry)
    validator = build_presence_occupancy(master_spec, production_spec, graph, fabric_plan)
    roads = street_occupancy_shapes(validator)
    body_radius = float(presence_spec["proxy"]["radius"])
    index = PresenceIndex(validator, body_radius)
    probe = GroundProbe(master_spec, fabric_plan)

    # The plan's OWN pedestrian-pedestrian clearance, read from the spec and
    # published on the finished plan -- never a hard-coded number. (The body
    # radius above is the physical envelope; separation >= 2 * radius is
    # spec-validated in population_presence_spec, so separation alone is the
    # centre-to-centre clearance the V2 collision verifier enforces.)
    separation = float(presence_spec["proxy"]["separation"])

    def _route(
        occupied_anchors: list[dict], separation: float | None
    ) -> tuple[list[dict], dict[str, str]]:
        """One full routing pass in selection order under one occupancy gate.

        ``occupied_anchors`` holds the real coordinates of anchors bodies
        already occupy: every proxy's own anchor plus every route end and
        start a walker accepts during this pass, so no two walkers ever
        claim the same end or start. ``separation`` is the plan's own
        pedestrian-pedestrian clearance; when it is None the gate is inert
        and the pass is byte-for-byte today's routing.
        """
        walkers: list[dict] = []
        refused: dict[str, str] = {}
        occupied = list(occupied_anchors)
        for proxy in selection_order(proxies, mobility_spec):
            if len(walkers) >= wanted:
                break
            district_candidates = candidates_by_district.get(proxy["district"], [])
            if not district_candidates:
                refused[proxy["slot"]] = "its district offers no walkable candidate"
                continue
            route, reason = _v2_walker_route(
                proxy,
                district_candidates,
                mobility_spec,
                timeline,
                speeds[proxy["slot"]],
                index,
                roads,
                probe,
                body_radius,
                occupied_anchors=occupied,
                separation=separation,
            )
            if route is None:
                refused[proxy["slot"]] = reason
                continue
            walkers.append(route)
            occupied.append(route["route_end"])
            # A walker also holds its START anchor until its own
            # ``start_offset`` elapses, so later ends keep the same clearance.
            occupied.append(route["route_start"])
        return walkers, refused

    # Pass 1 -- the partition: today's EXACT routing, no occupancy gate, fixes
    # which proxies move and which stand still, exactly as the shipped world
    # derives them. (Its stationary set is deliberately NOT the pass-2 gate:
    # the placement pass below can leave a DIFFERENT proxy standing than this
    # partition predicted, leaving those anchors unprotected -- the real EP2
    # stationary regression.)
    walkers, _refused_partition = _route([], None)
    # Pass 2 -- the placement: the SAME seeded order, now refusing any route
    # end within ``separation`` of an anchor a body occupies. EVERY proxy's
    # anchor is gated, not only the pass-1 stationary ones: every body holds
    # its own anchor at the start of the episode (a mover until its own
    # ``start_offset`` elapses, a stationary body for the whole episode), so
    # a route end may never stand within ``separation`` of ANY proxy anchor,
    # whether that proxy finally moves or stands still. Matching is by
    # COORDINATE (``_candidate_distance`` against the plan's own
    # ``separation``), never by slot identity -- two slot ids can name the
    # same point. A refused end makes the search take the next candidate in
    # its existing deterministic order; a walker with no safe end anywhere
    # is refused with its real reason and the honest achieved count is
    # reported below.
    anchor_gate = [
        {
            "x": proxy["x"],
            "y": proxy["y"],
            "anchor_id": f"{proxy['slot']} (proxy anchor)",
        }
        for proxy in proxies
    ]
    walkers, refused = _route(anchor_gate, separation)
    # A shortfall is reported honestly, not forced: every slot that did not
    # reach `wanted` is either a moving walker or a `refused` entry carrying
    # its real geometric reason (checked independently below by
    # ``validate_mobility_plan_v2``) -- never a silent drop and never a
    # fabricated route. ``moving`` reflects the real achieved count.
    walkers.sort(key=lambda entry: entry["slot"])
    _assign_start_offsets(walkers, mobility_spec, timeline)
    _assign_groups(walkers)
    _assign_micro_behavior(walkers, mobility_spec, timeline)
    for walker in walkers:
        cycle = gait_cycles(walker["route_length"], walker, mobility_spec)
        walker["gait"] = cycle
        walker["gait_digest"] = gait_digest(walker, cycle, mobility_spec)

    moving = {entry["slot"] for entry in walkers}
    by_zone: dict[str, int] = {}
    by_district: dict[str, int] = {}
    for entry in walkers:
        by_zone[entry["zone"]] = by_zone.get(entry["zone"], 0) + 1
        by_district[entry["district"]] = by_district.get(entry["district"], 0) + 1
    return {
        "total_proxies": len(proxies),
        "requested_moving": wanted,
        "moving": len(walkers),
        "stationary": len(proxies) - len(walkers),
        "moving_slots": sorted(moving),
        "stationary_slots": sorted(
            proxy["slot"] for proxy in proxies if proxy["slot"] not in moving
        ),
        "by_zone": dict(sorted(by_zone.items())),
        "by_district": dict(sorted(by_district.items())),
        "walkers": walkers,
        "refused": dict(sorted(refused.items())),
        "body_radius": body_radius,
        "separation": float(presence_spec["proxy"]["separation"]),
    }


def plan_daily_life_mobility_v2(
    presence_plan: dict,
    presence_spec: dict,
    mobility_spec: dict,
    timeline: dict,
    master_spec: dict,
    production_spec: dict,
    graph: dict,
    fabric_plan: dict,
) -> dict:
    """The whole open-trajectory mobility document, as one self-explaining plan.

    A V2 plan is pedestrians only: it is the ADDITIVE open-trajectory schema
    for presentation pedestrian motion and deliberately ships no closed-loop
    machinery (no vehicle circuits, no loop collision proof). Its ``summary``
    carries the pure metrics so a reviewer can audit the crowd's dispersion,
    distinctness and loop resistance without re-deriving anything.
    """
    pedestrians = plan_pedestrian_mobility_v2(
        presence_plan,
        presence_spec,
        mobility_spec,
        timeline,
        master_spec,
        production_spec,
        graph,
        fabric_plan,
    )
    plan = {
        "format": MOBILITY_PLAN_V2_FORMAT,
        "schema_version": MOBILITY_PLAN_V2_SCHEMA_VERSION,
        "mobility_profile": "v2",
        "statement": PRESENTATION_STATEMENT_V2,
        "timeline": dict(sorted(timeline.items())),
        "pedestrians": pedestrians,
    }
    plan["summary"] = {
        "total_population_proxies": pedestrians["total_proxies"],
        "moving_pedestrians": pedestrians["moving"],
        "stationary_pedestrians": pedestrians["stationary"],
        "open_routes": len(pedestrians["walkers"]),
        "metrics": mobility_metrics_v2(plan),
    }
    return plan


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _repeats_subpath(points: list) -> bool:
    """Whether an open trajectory repeats any exact directed sub-path.

    NO_VISIBLE_PEDESTRIAN_LOOP is satisfied by construction for a genuinely
    open trajectory; this is the mechanical guard against a degenerate
    document that coincidentally revisits itself. A directed segment is the
    rounded vector between two consecutive vertices; repeating the exact same
    directed segment means the walker retraces its own step, which is a
    repeating pattern, not a coincidental proximity. The whole trajectory must
    also not return to its own start point.
    """
    if len(points) < 2:
        return False
    segments: set[tuple] = set()
    for index in range(len(points) - 1):
        here = points[index]
        following = points[index + 1]
        segment = (
            round(float(following[0]) - float(here[0]), 4),
            round(float(following[1]) - float(here[1]), 4),
        )
        if segment in segments:
            return True
        segments.add(segment)
    first, last = points[0], points[-1]
    return math.hypot(float(last[0]) - float(first[0]), float(last[1]) - float(first[1])) < 1.0e-3


def mobility_metrics_v2(plan: dict) -> dict:
    """The pure, mechanically testable metrics of one V2 mobility plan.

    ``freeze_violation_count`` counts walkers whose motion depends on
    narration/caption timing -- V2 derives everything from the canonical
    timeline alone, so this is always zero. ``loop_violation_count`` counts
    walkers whose trajectory repeats a sub-path or returns to its start, which
    a genuinely open trajectory never does.
    """
    walkers = plan["pedestrians"]["walkers"]
    visible = len(walkers)
    starts = {walker["route_start"]["anchor_id"] for walker in walkers}
    ends = {walker["route_end"]["anchor_id"] for walker in walkers}
    grouped = sum(
        1 for walker in walkers if walker["social_grouping_state"].get("group") is not None
    )
    return {
        "visible_agent_count": visible,
        "distinct_route_start_count": len(starts),
        "distinct_route_end_count": len(ends),
        "group_participation_fraction": round(grouped / visible, 4) if visible else 0.0,
        "distinct_speed_count": len({walker["preferred_speed"] for walker in walkers}),
        "distinct_start_offset_count": len({walker["start_offset"] for walker in walkers}),
        "freeze_violation_count": 0,
        "loop_violation_count": sum(1 for walker in walkers if _repeats_subpath(walker["points"])),
    }


# ---------------------------------------------------------------------------
# The V2 validator
# ---------------------------------------------------------------------------


def validate_mobility_plan_v2(
    plan: dict,
    presence_plan: dict,
    topology: dict,
    mobility_spec: dict,
    timeline: dict,
    master_spec: dict,
    production_spec: dict,
    graph: dict,
    fabric_plan: dict,
) -> list[str]:
    """Audit a finished V2 plan against its own published numbers.

    Deliberately independent of the planner: every claim is recomputed from
    what the plan SAYS. Each route start, route end and waypoint must resolve
    to a REAL topology candidate; each polyline must re-prove clear on a
    freshly loaded occupancy; every speed must sit in the declared band; every
    start offset must be a distinct value inside the episode; and no trajectory
    may repeat a directed sub-path or return to its own start.
    """
    errors: list[str] = []
    if plan.get("format") != MOBILITY_PLAN_V2_FORMAT:
        errors.append(f"plan format is {plan.get('format')!r}")
    if plan.get("schema_version") != MOBILITY_PLAN_V2_SCHEMA_VERSION:
        errors.append(f"plan schema_version is {plan.get('schema_version')!r}")
    if plan.get("mobility_profile") != "v2":
        errors.append(f"plan mobility_profile is {plan.get('mobility_profile')!r}")
    if plan.get("statement") != PRESENTATION_STATEMENT_V2:
        errors.append("the plan does not carry the V2 presentation statement verbatim")

    known = {proxy["slot"]: proxy for proxy in presence_plan["proxies"]}
    pedestrians = plan["pedestrians"]
    if pedestrians["total_proxies"] != len(known):
        errors.append(
            f"the plan counts {pedestrians['total_proxies']} proxies, the presence plan "
            f"carries {len(known)}"
        )
    invented = sorted(set(pedestrians["moving_slots"]) - set(known))
    if invented:
        errors.append(f"the plan walks slot(s) Phase 18 never placed: {invented}")
    if set(pedestrians["moving_slots"]) & set(pedestrians["stationary_slots"]):
        errors.append("a slot is recorded as both moving and stationary")
    if sorted([*pedestrians["moving_slots"], *pedestrians["stationary_slots"]]) != sorted(known):
        errors.append("the moving and stationary slots do not account for every proxy")
    wanted = walker_count(len(known), mobility_spec)
    refused = pedestrians.get("refused", {})
    if pedestrians["moving"] > wanted:
        errors.append(
            f"the plan walks {pedestrians['moving']} of {len(known)} proxies, more than the "
            f"declared fraction {wanted} derives"
        )
    elif pedestrians["moving"] < wanted:
        # A shortfall is legitimate ONLY when every unreached slot is
        # explained by a real, non-empty recorded refusal -- never a silent
        # drop. This does not weaken the fraction itself: over-delivery is
        # still refused above, and an unexplained shortfall is refused below.
        shortfall = wanted - pedestrians["moving"]
        if len(refused) < shortfall:
            errors.append(
                f"the plan walks {pedestrians['moving']} of {len(known)} proxies, short of the "
                f"declared fraction {wanted}, but records only {len(refused)} refusal(s); every "
                "shortfall must be explained by a recorded refusal"
            )
        empty_reasons = sorted(slot for slot, reason in refused.items() if not reason)
        if empty_reasons:
            errors.append(f"slot(s) recorded a refusal with no real reason: {empty_reasons}")

    anchors = {entry["anchor_id"]: entry for entry in flatten_topology(topology)}
    band = mobility_spec["pedestrians"]["speed"]
    duration = float(timeline["duration_seconds"])
    start_frame = int(timeline["start_frame"])
    end_frame = int(timeline["end_frame"])
    validator = build_presence_occupancy(master_spec, production_spec, graph, fabric_plan)
    roads = street_occupancy_shapes(validator)
    body_radius = float(pedestrians["body_radius"])
    index = PresenceIndex(validator, body_radius)
    probe = GroundProbe(master_spec, fabric_plan)

    seen_offsets: set[float] = set()
    seen_speeds: set[float] = set()
    for walker in pedestrians["walkers"]:
        proxy = known.get(walker["slot"])
        if proxy is None:
            continue
        for axis in ("x", "y", "z"):
            if abs(float(walker["anchor"][axis]) - float(proxy[axis])) > 1.0e-6:
                errors.append(
                    f"{walker['slot']} claims an anchor {axis}={walker['anchor'][axis]}, "
                    f"Phase 18 placed it at {proxy[axis]}"
                )
        for label, entry in (
            ("route_start", walker["route_start"]),
            ("route_end", walker["route_end"]),
        ):
            anchor = anchors.get(entry["anchor_id"])
            if anchor is None:
                errors.append(
                    f"{walker['slot']} {label} names unknown anchor {entry['anchor_id']!r}"
                )
                continue
            for axis in ("x", "y", "z"):
                if abs(float(entry[axis]) - float(anchor[axis])) > 1.0e-4:
                    errors.append(
                        f"{walker['slot']} {label} coordinates disagree with anchor "
                        f"{entry['anchor_id']} on {axis}"
                    )
        if walker["route_end"]["anchor_id"] == walker["route_start"]["anchor_id"]:
            errors.append(f"{walker['slot']} open route ends where it starts")
        for index_, waypoint in enumerate(walker["waypoints"]):
            if waypoint["anchor_id"] not in anchors:
                errors.append(
                    f"{walker['slot']} waypoint {index_} names unknown anchor "
                    f"{waypoint['anchor_id']!r}"
                )
        points = [tuple(point) for point in walker["points"]]
        measured = polyline_length(points)
        if abs(measured - walker["route_length"]) > 1.0e-4:
            errors.append(
                f"{walker['slot']} claims a {walker['route_length']} route, its points "
                f"measure {measured:.4f}"
            )
        speed = float(walker["preferred_speed"])
        if not band["min"] <= speed <= band["max"]:
            errors.append(f"{walker['slot']} walks at {speed}m/s, outside the declared band")
        if speed in seen_speeds:
            errors.append(f"{walker['slot']} repeats another walker's preferred speed {speed}")
        seen_speeds.add(speed)
        offset = float(walker["start_offset"])
        if not 0.0 <= offset <= duration:
            errors.append(
                f"{walker['slot']} start_offset {offset}s sits outside the {duration}s episode"
            )
        if offset in seen_offsets:
            errors.append(f"{walker['slot']} repeats another walker's start_offset {offset}")
        seen_offsets.add(offset)
        if measured > speed * duration:
            errors.append(
                f"{walker['slot']} route is {measured:.2f}m, longer than {speed}m/s can "
                f"walk in the {duration}s episode"
            )
        if _repeats_subpath(points):
            errors.append(f"{walker['slot']} trajectory repeats a directed sub-path or loops")
        loop_2d = [(point[0], point[1]) for point in points]
        violations = route_violations(
            loop_2d, proxy, index, roads, probe, mobility_spec, body_radius
        )
        if violations:
            errors.append(f"{walker['slot']} route is not on proven-clear ground: {violations[0]}")
        turning = open_path_turn_violations(loop_2d, speed, mobility_spec)
        if turning:
            errors.append(f"{walker['slot']} turns too sharply: {turning[0]}")
        for event in walker["micro_behavior_schedule"]:
            if not 0.0 <= float(event["s"]) <= measured:
                errors.append(
                    f"{walker['slot']} micro event sits at s={event['s']} outside its "
                    f"{measured:.2f}m route"
                )
            if not start_frame <= int(event["frame"]) <= end_frame:
                errors.append(
                    f"{walker['slot']} micro event frame {event['frame']} sits outside "
                    f"[{start_frame}, {end_frame}]"
                )

    # Group coherence: ids well formed, sizes within 2-4, members share a district.
    groups: dict[str, list[dict]] = {}
    for walker in pedestrians["walkers"]:
        state = walker["social_grouping_state"]
        group_id = state.get("group")
        if group_id is None:
            continue
        groups.setdefault(group_id, []).append(walker)
        members = int(state.get("members", 0))
        if not 2 <= members <= 4:
            errors.append(f"{walker['slot']} declares a group of {members}; groups hold 2-4")
        if state.get("role") not in ("lead", "member"):
            errors.append(f"{walker['slot']} has unknown group role {state.get('role')!r}")
    for group_id, members in sorted(groups.items()):
        if len(members) != members[0]["social_grouping_state"]["members"]:
            errors.append(f"{group_id} member count disagrees between members")
        districts = {member["district"] for member in members}
        if len(districts) != 1:
            errors.append(f"{group_id} spans districts {sorted(districts)}")
        for member in members[1:]:
            gap = _candidate_distance(members[0]["route_start"], member["route_start"])
            if gap > GROUP_RADIUS:
                errors.append(
                    f"{group_id} member {member['slot']} starts {gap:.1f}m from its lead, "
                    f"outside the shared-region radius"
                )

    computed = mobility_metrics_v2(plan)
    published = plan["summary"].get("metrics")
    if published != computed:
        errors.append(
            f"the plan's published metrics {published} disagree with the recomputed {computed}"
        )
    return errors


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------


def mobility_plan_v2_hash(plan: dict) -> str:
    """A stable digest of one V2 mobility plan.

    Canonical JSON with sorted keys, so the same world and the same specs
    produce the same digest on any machine and under any ``PYTHONHASHSEED``.
    """
    payload = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
