"""The Daily Life Mobility Plan V1: one document the whole moving city obeys.

Pure Python by design -- no ``bpy``. A mobility plan can be derived, hashed,
inspected and DISPROVED on a machine with no Blender installed, which is the
only way its safety can be checked independently of what the render happens to
look like.

The plan answers four questions in strict order, each by a different authority:

    WHO WALKS   a stable draw over the EXISTING Phase 18 proxies. Nobody new.
    WHERE       a closed route proven clear by the Phase 18 occupancy contract.
    WHAT DRIVES the vehicle lane network's circuits, filled to a stable prefix
                of their own slots.
    IS IT SAFE  every pair of moving things, on every frame of the canonical
                timeline -- not at the start, not at a sample, on every frame.

    THIS IS PRESENTATION MOBILITY.

Pedestrian movement and vehicle traffic in Phase 19 are deterministic
presentation mobility. They are not individual citizen schedules, authoritative
destinations, or simulated traffic demand. The engine is not consulted about
either, is not told about either, and holds nothing that could correspond to
one. A walker walks a loop around its own anchor; a vehicle drives a circuit
that returns to where it began. Neither goes anywhere, and that is deliberate:
going somewhere would be a claim about a person or a journey this world does
not model.

WHY THE COLLISION PROOF IS REBUILT FROM SCRATCH
-----------------------------------------------
A validator that asked the generator whether the generator was right would
prove only that the code is self-consistent. The checks below rebuild every
envelope from the plan's PUBLISHED numbers -- a body is a circle of the
published radius at the published position, a vehicle is a rectangle of the
published length and width at the published heading -- and compare them with
plain geometry. Nothing in this section calls the planner.

Those vehicle numbers are the RESERVED planning envelope, the frozen box the
lane network sized every lane and headway against, and not the body the kit
emits -- which the kit proves, per component, fits inside that reservation.
Sweeping the reservation is therefore conservative on purpose: every clearance
reported below is a lower bound on the real one, so this proof can refuse
traffic the emitted bodywork would have cleared, and can never pass traffic
that bodywork would not.
"""

import hashlib
import json
import math

import pedestrian_mobility as walking
import vehicle_kit
from mobility_spec import mobility_seed, pedestrian_route_length
from pedestrian_topology import build_presence_occupancy, street_occupancy_shapes
from population_presence_spec import FIGURE_AXES
from spatial_occupancy import circle, rect, shape_gap
from vehicle_lane_network import (
    distance_to_polyline,
    plan_vehicle_lanes,
    polyline_length,
    resample_polyline,
)

MOBILITY_PLAN_FORMAT = "living_diorama_daily_life_mobility_plan"
MOBILITY_PLAN_SCHEMA_VERSION = 1

PRESENTATION_STATEMENT = (
    "Pedestrian movement and vehicle traffic in Phase 19 are deterministic "
    "presentation mobility. They are not individual citizen schedules, "
    "authoritative destinations, or simulated traffic demand. A moving body is "
    "the same representative population proxy Phase 18 placed, walking a closed "
    "loop around its own anchor; a vehicle is an ambient mobility prop with no "
    "driver, owner, passenger, cargo or history."
)
"""The sentence every manifest must carry, so the claim is never overstated."""


class MobilityPlanError(ValueError):
    """A daily-life mobility plan violation.

    Raised when the city cannot carry the declared traffic, when a route cannot
    be proven safe, and when the plan and its own inputs disagree. Always a
    refusal, never a repair.
    """


# ---------------------------------------------------------------------------
# Walking a closed loop
# ---------------------------------------------------------------------------


def loop_stations(points: list) -> list[dict]:
    """Index one closed route by arc length, with a heading at every vertex.

    The heading is the direction to the NEXT vertex, so it is the direction of
    travel and nothing else. A moving body faces where it is going; the
    stationary heading Phase 18 gave it was the direction it was looking while
    standing still, and a person who walks does not keep looking sideways.
    """
    stations: list[dict] = []
    travelled = 0.0
    for index in range(len(points) - 1):
        here, following = points[index], points[index + 1]
        span = math.hypot(following[0] - here[0], following[1] - here[1])
        if span <= 1.0e-12:
            continue
        stations.append(
            {
                "s": travelled,
                "x": here[0],
                "y": here[1],
                "z": here[2] if len(here) > 2 else 0.0,
                "heading": math.atan2(following[1] - here[1], following[0] - here[0]),
            }
        )
        travelled += span
    if not stations:
        raise MobilityPlanError("a route collapsed to a single point")
    stations.append({**stations[0], "s": travelled})
    return stations


def sample_loop(stations: list[dict], distance: float) -> dict:
    """Where one closed route puts a body after travelling a distance.

    Wrapped, so travelling exactly one whole loop returns EXACTLY the first
    station rather than something a rounding error away from it. That exactness
    is the loop contract: the last frame and the first frame are the same
    number, not two numbers that agree to six places.
    """
    total = stations[-1]["s"]
    if total <= 0.0:
        raise MobilityPlanError("a route has no length to travel along")
    wrapped = math.fmod(distance, total)
    if wrapped < 0.0:
        wrapped += total
    low, high = 0, len(stations) - 1
    while low + 1 < high:
        middle = (low + high) // 2
        if stations[middle]["s"] <= wrapped:
            low = middle
        else:
            high = middle
    here, following = stations[low], stations[low + 1]
    span = following["s"] - here["s"]
    t = 0.0 if span <= 0.0 else (wrapped - here["s"]) / span
    turn = math.atan2(
        math.sin(following["heading"] - here["heading"]),
        math.cos(following["heading"] - here["heading"]),
    )
    return {
        "x": here["x"] + (following["x"] - here["x"]) * t,
        "y": here["y"] + (following["y"] - here["y"]) * t,
        "z": here["z"] + (following["z"] - here["z"]) * t,
        "heading": here["heading"] + turn * t,
    }


def frame_distance(frame: int, timeline: dict, length: float, cycles: int) -> float:
    """How far a mover has travelled by one frame of the canonical timeline."""
    span = timeline["frame_span"]
    return length * cycles * (frame - timeline["start_frame"]) / span


# ---------------------------------------------------------------------------
# Pedestrians
# ---------------------------------------------------------------------------


def _walker_route(
    proxy: dict,
    mobility_spec: dict,
    timeline: dict,
    master_spec: dict,
    production_spec: dict,
    graph: dict,
    fabric_plan: dict,
    index,
    roads: list[dict],
    probe,
    body_radius: float,
) -> dict:
    """One walker's whole route, or a refusal explaining why it has none.

    The speed comes first, because the loop contract turns it straight into a
    route length; the excursion is then SOLVED so the loop is exactly that
    long. Both lateral sides are tried, outward first, and each candidate is
    proven clear along its whole length before it is accepted -- so a route
    that survives has been checked, not merely constructed.
    """
    route_spec = mobility_spec["pedestrians"]["route"]
    natural = walking.walking_speed(float(proxy["height"]), mobility_spec)
    band = mobility_spec["pedestrians"]["speed"]
    corridor = walking.route_corridor(proxy, master_spec, production_spec, graph, fabric_plan)
    bounds = (route_spec["excursion_min"], route_spec["excursion_max"])
    anchor_point = (float(proxy["x"]), float(proxy["y"]))
    cycle_seconds = float(timeline["pedestrian_cycle_seconds"])
    reasons: list[str] = []

    def accept(loop, speed, excursion, lateral, side, family):
        """Prove one candidate route, or say why it fails."""
        drift = math.dist(tuple(loop[0]), anchor_point)
        if drift > route_spec["anchor_tolerance"]:
            return None, (
                f"the route starts {drift:.3f} from the anchor, beyond the declared "
                f"{route_spec['anchor_tolerance']} tolerance"
            )
        violations = walking.route_violations(
            loop, proxy, index, roads, probe, mobility_spec, body_radius
        )
        if violations:
            return None, violations[0]
        turning = walking.turn_rate_violations(loop, speed, mobility_spec)
        if turning:
            return None, turning[0]
        return (loop, speed, excursion, lateral, side, family), None

    candidates: list = []
    # A ring the walker can simply stroll all the way round is the best route
    # this phase can offer, so it is tried before any racetrack: a full circle
    # has no turnaround to justify at all.
    circumference = walking.ring_circumference(corridor)
    ring_band = (band["min"] * cycle_seconds, band["max"] * cycle_seconds)
    if circumference and ring_band[0] <= circumference <= ring_band[1]:
        candidates.append(("full_ring", circumference / cycle_seconds, None, None, None))
    for factor in route_spec["speed_ladder"]:
        speed = min(max(natural * float(factor), band["min"]), band["max"])
        lateral = walking.turn_lateral(speed, mobility_spec)
        for share in route_spec["anchor_positions"]:
            for side in walking.LATERAL_ORDER:
                candidates.append(("corridor", speed, lateral, share, side))
    # A corridor can be walked either way. On a street that is the difference
    # between using the pavement north of a walker and the pavement south of it;
    # on a ring it is the difference between strolling clockwise and
    # anticlockwise past a completely different set of neighbours.
    reversed_corridor = walking.reversed_corridor(corridor)

    accepted = None
    for candidate in candidates:
        if candidate[0] == "full_ring":
            speed = candidate[1]
            loop = walking.rotate_loop_to(walking.full_ring_loop(corridor), anchor_point)
            accepted, reason = accept(loop, speed, 0.0, 0.0, "ring", "full_ring")
        else:
            _kind, speed, lateral, share, side = candidate
            target = pedestrian_route_length(speed, timeline)
            accepted, reason = None, ""
            for heading, base in (("along", corridor), ("against", reversed_corridor)):
                try:
                    excursion, loop = walking.solve_excursion(
                        base,
                        target,
                        lateral,
                        side,
                        route_spec["sample_step"],
                        bounds,
                        share,
                    )
                except walking.PedestrianMobilityError as error:
                    reason = f"{side}/{heading}@{share}x{speed:.2f}: {error}"
                    continue
                loop = walking.rotate_loop_to(loop, anchor_point)
                accepted, reason = accept(loop, speed, excursion, lateral, side, base["family"])
                if accepted is not None:
                    break
        if accepted is not None:
            break
        reasons.append(f"{candidate[0]}: {reason}")
    if accepted is None:
        raise MobilityPlanError("; ".join(reasons[:4]) or "no route candidate was available")

    loop, speed, excursion, lateral, side, family = accepted
    cycle = walking.gait_cycles(polyline_length(loop), proxy, mobility_spec)
    return {
        "slot": proxy["slot"],
        "district": proxy["district"],
        "zone": proxy["zone"],
        "source": proxy["source"],
        "anchor": {
            "x": proxy["x"],
            "y": proxy["y"],
            "z": proxy["z"],
            "heading": proxy["heading"],
        },
        "geometry_key": proxy["geometry_key"],
        "height": proxy["height"],
        # The whole Phase 18 visual identity travels with the walker. The gait
        # is a deformation of THAT body, and the applier has to be able to
        # rebuild it from the plan alone -- a walker record carrying only a
        # geometry key would make the render depend on a presence plan the
        # mobility layer is not given.
        **{axis: proxy[axis] for axis in FIGURE_AXES},
        "route_family": family,
        "route_side": side,
        "excursion": round(excursion, 6),
        "lateral_offset": round(lateral, 6),
        "route_length": round(polyline_length(loop), 6),
        "speed": round(speed, 6),
        "natural_speed": round(natural, 6),
        "cycles": mobility_spec["cycle"]["pedestrian_cycles"],
        "gait": cycle,
        "gait_digest": walking.gait_digest(proxy, cycle, mobility_spec),
        "points": [[round(x, 6), round(y, 6), round(float(proxy["z"]), 6)] for x, y in loop],
    }


def plan_pedestrian_mobility(
    presence_plan: dict,
    mobility_spec: dict,
    timeline: dict,
    master_spec: dict,
    production_spec: dict,
    presence_spec: dict,
    graph: dict,
    fabric_plan: dict,
) -> dict:
    """Which of the city's existing proxies walk, and exactly where.

    The count comes from the declared fraction; the ORDER comes from each
    slot's own stable draw. A slot whose ground cannot carry a legal route is
    skipped with its reason recorded and the next eligible slot takes its
    place -- deterministic fallback, never a silent placement of an unsafe
    route and never a quietly smaller crowd. A pool that exhausts below the
    declared count is therefore a refusal carrying the recorded reasons, not
    a smaller plan.
    """
    proxies = list(presence_plan["proxies"])
    wanted = walking.walker_count(len(proxies), mobility_spec)
    validator = build_presence_occupancy(master_spec, production_spec, graph, fabric_plan)
    roads = street_occupancy_shapes(validator)
    body_radius = float(presence_spec["proxy"]["radius"])
    index = walking.PresenceIndex(validator, body_radius)
    probe = walking.GroundProbe(master_spec, fabric_plan)
    separation = float(presence_spec["proxy"]["separation"])
    anchors = {proxy["slot"]: (float(proxy["x"]), float(proxy["y"])) for proxy in proxies}
    walkers: list[dict] = []
    accepted_tracks: list[tuple[str, list[dict], float, int]] = []

    def crowding(route: dict) -> str:
        """Why this route would crowd somebody, or an empty string.

        Two checks, cheapest first. A route must clear the ANCHOR of every proxy
        that is not already walking -- conservative, because such a proxy might
        later be given a route of its own that moves it away, and being wrong in
        that direction only ever refuses a route rather than shipping an unsafe
        one. Then it must clear every ALREADY ACCEPTED walker over the whole
        timeline, which is the real check: two people on the same park ring are
        never in trouble where they start, only where they meet.
        """
        walking_now = {entry[0] for entry in accepted_tracks} | {route["slot"]}
        points = [tuple(point) for point in route["points"]]
        for slot, (x, y) in sorted(anchors.items()):
            if slot in walking_now:
                continue
            # Measured against the route's SEGMENTS, not its vertices. A body
            # travelling between two vertices passes closer to a bystander than
            # either vertex does whenever the bystander stands off to the side,
            # so a vertex test would accept a route the frame-by-frame proof
            # then rejects -- which is exactly what it did, by one millimetre.
            gap = distance_to_polyline(x, y, points)
            if gap < separation:
                return (
                    f"its route passes {gap:.3f} from stationary {slot}, inside the "
                    f"{separation} separation"
                )
        stations = loop_stations(points)
        length, cycles = route["route_length"], route["cycles"]
        stride = int(timeline["collision_frame_stride"])
        frames = list(range(timeline["start_frame"], timeline["end_frame"] + 1, stride))
        if frames[-1] != timeline["end_frame"]:
            # The end frame is forced in, exactly as the collision proof forces
            # it in. A stride that stepped over the last frame would let this
            # acceptance check and the plan's own proof sample different
            # moments, and two checks that disagree about WHEN can disagree
            # about WHETHER. Harmless at the canonical stride of one, where the
            # range already ends on the end frame.
            frames.append(timeline["end_frame"])
        for frame in frames:
            here = sample_loop(stations, frame_distance(frame, timeline, length, cycles))
            for slot, other_stations, other_length, other_cycles in accepted_tracks:
                there = sample_loop(
                    other_stations, frame_distance(frame, timeline, other_length, other_cycles)
                )
                gap = math.hypot(here["x"] - there["x"], here["y"] - there["y"])
                if gap < separation:
                    return (
                        f"on frame {frame} it passes {gap:.2f} from walker {slot}, inside the "
                        f"{separation} separation"
                    )
        return ""

    refused: dict[str, str] = {}
    for proxy in walking.selection_order(proxies, mobility_spec):
        if len(walkers) >= wanted:
            break
        try:
            route = _walker_route(
                proxy,
                mobility_spec,
                timeline,
                master_spec,
                production_spec,
                graph,
                fabric_plan,
                index,
                roads,
                probe,
                body_radius,
            )
        except (MobilityPlanError, walking.PedestrianMobilityError) as error:
            refused[proxy["slot"]] = str(error)
            continue
        crowded = crowding(route)
        if crowded:
            refused[proxy["slot"]] = crowded
            continue
        walkers.append(route)
        accepted_tracks.append(
            (
                route["slot"],
                loop_stations([tuple(point) for point in route["points"]]),
                route["route_length"],
                route["cycles"],
            )
        )
    if len(walkers) < wanted:
        recorded = "; ".join(f"{slot}: {reason}" for slot, reason in sorted(refused.items())[:4])
        raise MobilityPlanError(
            f"the declared fraction asks {wanted} of the city's {len(proxies)} proxies to "
            f"walk, and the pool exhausted at {len(walkers)}. A quietly smaller crowd would "
            f"ship a city less alive than the spec declares, so this is a refusal. "
            f"{len(refused)} slot(s) recorded refusals: {recorded or 'none'}"
        )
    walkers.sort(key=lambda entry: entry["slot"])
    moving = {entry["slot"] for entry in walkers}
    by_zone: dict[str, int] = {}
    for entry in walkers:
        by_zone[entry["zone"]] = by_zone.get(entry["zone"], 0) + 1
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
        "by_district": dict(
            sorted(
                (district, sum(1 for entry in walkers if entry["district"] == district))
                for district in {entry["district"] for entry in walkers}
            )
        ),
        "walkers": walkers,
        "refused": dict(sorted(refused.items())),
        "body_radius": body_radius,
        "separation": float(presence_spec["proxy"]["separation"]),
    }


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------


def _weighted_choice(rng, table: dict[str, float]) -> str:
    """One deterministic draw from a weighted table, in sorted key order."""
    names = [name for name in sorted(table) if float(table[name]) > 0.0]
    if not names:
        raise MobilityPlanError("a vehicle vocabulary offered no value with any weight")
    weights = [float(table[name]) for name in names]
    draw = rng.random() * math.fsum(weights)
    running = 0.0
    for name, weight in zip(names, weights, strict=True):
        running += weight
        if draw < running:
            return name
    return names[-1]


def vehicle_route_slots(circuits: list[dict]) -> list[dict]:
    """Every route slot the network offers, in a stable global order.

    A slot is a circuit and a fixed phase along it, and a circuit's slots are
    laid out at even phases so ANY subset of them keeps at least the declared
    pitch apart. The global order INTERLEAVES circuits -- first slot of every
    circuit, then second, and so on -- so raising the vehicle count spreads the
    new traffic across the city instead of piling it onto one street, and so
    the slots already in use never move.
    """
    per_circuit = [
        [
            {
                "circuit": circuit["circuit"],
                "index": index,
                "phase": index / circuit["capacity"],
                "length": circuit["length"],
                "speed": circuit["speed"],
            }
            for index in range(circuit["capacity"])
        ]
        for circuit in circuits
    ]
    slots: list[dict] = []
    for position in range(max((len(entry) for entry in per_circuit), default=0)):
        for entry in per_circuit:
            if position < len(entry):
                slots.append(entry[position])
    for number, slot in enumerate(slots, start=1):
        slot["slot"] = f"vehicle_slot_{number:03d}"
    return slots


def plan_vehicle_mobility(
    mobility_spec: dict, timeline: dict, master_spec: dict, graph: dict, fabric_plan: dict
) -> dict:
    """The city's ambient traffic: which circuits, how many, and what they are.

    The declared target is honoured or REFUSED. If the network's circuits
    cannot carry it at the declared pitch, this raises with the capacity it
    actually found and the reason each rejected circuit was rejected; it never
    quietly ships fewer vehicles and calls the target met.
    """
    entry = mobility_spec["vehicles"]
    lanes = plan_vehicle_lanes(
        master_spec,
        graph,
        fabric_plan["ground"],
        mobility_spec,
        vehicle_kit.widest_vehicle() / 2.0,
        timeline,
    )
    slots = vehicle_route_slots(lanes["circuits"])
    target = int(entry["target_count"])
    if target > len(slots):
        raise MobilityPlanError(
            f"the canonical world offers {len(slots)} safe vehicle route slot(s) across "
            f"{len(lanes['circuits'])} circuit(s) at the declared {entry['slot_pitch']}m "
            f"pitch, and the spec asks for {target}. The binding constraint is the loop "
            f"contract: a circuit must be between {lanes['summary']['length_band'][0]} and "
            f"{lanes['summary']['length_band'][1]} metres to be driven once, at a legal "
            f"speed, inside one cycle. {lanes['summary']['circuits_rejected']} circuit(s) "
            "were rejected; their reasons are in the lane network report."
        )
    if target > int(entry["max_count"]):
        raise MobilityPlanError("the spec's own target exceeds its own maximum")

    circuits = {circuit["circuit"]: circuit for circuit in lanes["circuits"]}
    vehicles: list[dict] = []
    for slot in slots[:target]:
        rng = mobility_seed(mobility_spec, "vehicle", slot["slot"])
        archetype = _weighted_choice(rng, entry["archetypes"])
        paint = vehicle_kit.PAINT_FAMILIES[rng.randrange(len(vehicle_kit.PAINT_FAMILIES))]
        size = vehicle_kit.vehicle_dimensions(archetype)
        circuit = circuits[slot["circuit"]]
        # A wheel must be in the same state on the first and last frame MODULO
        # FULL REVOLUTIONS, so the revolution count has to be a whole number.
        # It will not be for a geometric radius: this circuit rolls a 0.372m
        # wheel 32.85 times. The answer is the distinction every tyre already
        # has -- a ROLLING radius, slightly under the geometric one because a
        # loaded tyre deflects. Rounding the revolutions and solving for the
        # rolling radius closes the loop exactly. The spec permits at most five
        # percent drift; the canonical fourteen remain under two percent.
        travelled = circuit["length"] * mobility_spec["cycle"]["vehicle_cycles"]
        exact = travelled / (2.0 * math.pi * size["wheel_radius"])
        turns = max(1, int(math.floor(exact + 0.5)))
        rolling = travelled / (2.0 * math.pi * turns)
        drift = abs(rolling / size["wheel_radius"] - 1.0)
        if drift > float(entry["rolling_radius_tolerance"]):
            raise MobilityPlanError(
                f"closing {slot['slot']}'s wheels on {turns} whole revolutions needs a "
                f"{rolling:.4f}m rolling radius against a {size['wheel_radius']}m wheel, "
                f"{drift:.1%} off the declared tolerance"
            )
        vehicles.append(
            {
                "slot": slot["slot"],
                "circuit": slot["circuit"],
                "circuit_index": slot["index"],
                "phase": round(slot["phase"], 9),
                "archetype": archetype,
                "paint": paint,
                "length": size["length"],
                "width": size["width"],
                "height": size["height"],
                "wheel_radius": size["wheel_radius"],
                "rolling_radius": round(rolling, 9),
                "rolling_radius_drift": round(drift, 9),
                "speed": circuit["speed"],
                "route_length": circuit["length"],
                "cycles": mobility_spec["cycle"]["vehicle_cycles"],
                "wheel_turns": turns,
            }
        )
    by_archetype: dict[str, int] = {}
    for vehicle in vehicles:
        by_archetype[vehicle["archetype"]] = by_archetype.get(vehicle["archetype"], 0) + 1
    return {
        "target_count": target,
        "count": len(vehicles),
        "capacity": len(slots),
        "driving_side": entry["driving_side"],
        "slot_pitch": entry["slot_pitch"],
        "by_archetype": dict(sorted(by_archetype.items())),
        "circuits": [
            {
                "circuit": circuit["circuit"],
                "direction": circuit["direction"],
                "length": circuit["length"],
                "speed": circuit["speed"],
                "capacity": circuit["capacity"],
                "runs": circuit["runs"],
                "points": [[round(x, 6), round(y, 6), round(z, 6)] for x, y, z in circuit["line"]],
            }
            for circuit in lanes["circuits"]
        ],
        "vehicles": vehicles,
        "network": lanes["network"]["summary"],
        "route_offer": lanes["summary"],
        "coverage": lanes["coverage"],
        "turnarounds": lanes["turnarounds"],
        "refused_runs": lanes["network"]["refused"],
        "rejected_circuits": lanes["rejected"],
        "triangles": {name: vehicle_kit.vehicle_triangles(name) for name in sorted(by_archetype)},
        "layer_triangles": sum(
            vehicle_kit.vehicle_triangles(vehicle["archetype"]) for vehicle in vehicles
        ),
    }


# ---------------------------------------------------------------------------
# Space-time collision proof
# ---------------------------------------------------------------------------


def _mover_tracks(plan: dict, timeline: dict) -> dict:
    """Every moving thing's own arc-length index, built from the PLAN's points.

    Rebuilt from the published polylines rather than handed over by the
    planner, so a plan whose numbers do not describe the route it thinks it
    drew fails here instead of passing on trust.
    """
    walkers = {
        entry["slot"]: {
            "stations": loop_stations([tuple(point) for point in entry["points"]]),
            "length": entry["route_length"],
            "cycles": entry["cycles"],
            "radius": plan["pedestrians"]["body_radius"],
        }
        for entry in plan["pedestrians"]["walkers"]
    }
    circuits = {
        entry["circuit"]: loop_stations([tuple(point) for point in entry["points"]])
        for entry in plan["vehicles"]["circuits"]
    }
    vehicles = {
        entry["slot"]: {
            "stations": circuits[entry["circuit"]],
            "length": entry["route_length"],
            "cycles": entry["cycles"],
            "phase": entry["phase"],
            "half_length": entry["length"] / 2.0,
            "half_width": entry["width"] / 2.0,
        }
        for entry in plan["vehicles"]["vehicles"]
    }
    _ = timeline
    return {"walkers": walkers, "vehicles": vehicles}


def mobility_collisions(
    plan: dict, timeline: dict, presence_plan: dict, mobility_spec: dict
) -> dict:
    """Prove no mover ever touches another mover or a bystander, on every sampled frame.

    Four dynamic pair classes, all of them, all the way through time::

        walker / walker              two people never occupy one place
        walker / stationary proxy    a walker never walks through a bystander
        vehicle / vehicle            headway holds for the whole cycle, not
                                     merely at the start
        walker / vehicle             structurally impossible by topology, and
                                     checked anyway

    Contact with the STATIC city is a separate route-validity proof, not a fifth
    timeline pair class. This function holds nothing that could test it. It is
    proven per route and BEFORE acceptance, which is the only place a bad route
    can still be rejected cheaply: ``pedestrian_mobility.route_violations``
    samples a walker's whole loop against the Phase 18 occupancy contract and
    refuses it for entering a carriageway, and the lane network refuses a lane
    outright when any of its stations fails
    ``vehicle_lane_network.on_carriageway``. It is then proven again against the
    BUILT scene, on evaluated transforms, in
    visual/blender/tests/test_mobility.py.

    Static checks alone stopped being enough the moment anything moved: two
    routes that never overlap in SPACE are still safe, but two that cross are
    only safe if they never cross at the same TIME, and only a walk through the
    timeline can tell the difference.
    """
    tracks = _mover_tracks(plan, timeline)
    stationary = [
        proxy
        for proxy in presence_plan["proxies"]
        if proxy["slot"] in set(plan["pedestrians"]["stationary_slots"])
    ]
    separation = plan["pedestrians"]["separation"]
    body_radius = plan["pedestrians"]["body_radius"]
    vehicle_gap = float(mobility_spec["vehicles"]["body_clearance"])
    pedestrian_gap = float(mobility_spec["vehicles"]["pedestrian_clearance"])
    stride = int(timeline["collision_frame_stride"])
    frames = list(range(timeline["start_frame"], timeline["end_frame"] + 1, stride))
    if frames[-1] != timeline["end_frame"]:
        frames.append(timeline["end_frame"])

    worst = {
        "walker_walker": math.inf,
        "walker_stationary": math.inf,
        "vehicle_vehicle": math.inf,
        "walker_vehicle": math.inf,
    }
    failures: list[str] = []
    walker_ids = sorted(tracks["walkers"])
    vehicle_ids = sorted(tracks["vehicles"])
    for frame in frames:
        placed_walkers = {}
        for slot in walker_ids:
            entry = tracks["walkers"][slot]
            placed_walkers[slot] = sample_loop(
                entry["stations"],
                frame_distance(frame, timeline, entry["length"], entry["cycles"]),
            )
        placed_vehicles = {}
        for slot in vehicle_ids:
            entry = tracks["vehicles"][slot]
            distance = entry["phase"] * entry["length"] + frame_distance(
                frame, timeline, entry["length"], entry["cycles"]
            )
            placed_vehicles[slot] = sample_loop(entry["stations"], distance)

        for first in range(len(walker_ids)):
            here = placed_walkers[walker_ids[first]]
            for second in range(first + 1, len(walker_ids)):
                other = placed_walkers[walker_ids[second]]
                gap = math.hypot(here["x"] - other["x"], here["y"] - other["y"])
                worst["walker_walker"] = min(worst["walker_walker"], gap)
                if gap < separation and len(failures) < 12:
                    failures.append(
                        f"frame {frame}: {walker_ids[first]} and {walker_ids[second]} are "
                        f"{gap:.3f} apart, closer than the {separation} separation"
                    )
            for proxy in stationary:
                gap = math.hypot(here["x"] - proxy["x"], here["y"] - proxy["y"])
                worst["walker_stationary"] = min(worst["walker_stationary"], gap)
                if gap < separation and len(failures) < 12:
                    failures.append(
                        f"frame {frame}: walker {walker_ids[first]} passes {gap:.3f} from "
                        f"stationary {proxy['slot']}"
                    )

        bodies = {
            slot: rect(
                placed_vehicles[slot]["x"],
                placed_vehicles[slot]["y"],
                tracks["vehicles"][slot]["half_length"],
                tracks["vehicles"][slot]["half_width"],
                placed_vehicles[slot]["heading"],
            )
            for slot in vehicle_ids
        }
        for first in range(len(vehicle_ids)):
            for second in range(first + 1, len(vehicle_ids)):
                gap = shape_gap(bodies[vehicle_ids[first]], bodies[vehicle_ids[second]])
                worst["vehicle_vehicle"] = min(worst["vehicle_vehicle"], gap)
                if gap < vehicle_gap and len(failures) < 12:
                    failures.append(
                        f"frame {frame}: {vehicle_ids[first]} and {vehicle_ids[second]} are "
                        f"{gap:.3f} apart, closer than the {vehicle_gap} body clearance"
                    )
        for slot in vehicle_ids:
            body = bodies[slot]
            for walker in walker_ids:
                here = placed_walkers[walker]
                gap = shape_gap(circle(here["x"], here["y"], body_radius), body)
                worst["walker_vehicle"] = min(worst["walker_vehicle"], gap)
                if gap < pedestrian_gap and len(failures) < 12:
                    failures.append(f"frame {frame}: {slot} passes {gap:.3f} from walker {walker}")
            for proxy in stationary:
                gap = shape_gap(circle(proxy["x"], proxy["y"], body_radius), body)
                worst["walker_vehicle"] = min(worst["walker_vehicle"], gap)
                if gap < pedestrian_gap and len(failures) < 12:
                    failures.append(
                        f"frame {frame}: {slot} passes {gap:.3f} from stationary {proxy['slot']}"
                    )
    return {
        "frames_sampled": len(frames),
        "frame_stride": stride,
        "pairs_checked": {
            "walker_walker": len(walker_ids) * (len(walker_ids) - 1) // 2,
            "walker_stationary": len(walker_ids) * len(stationary),
            "vehicle_vehicle": len(vehicle_ids) * (len(vehicle_ids) - 1) // 2,
            "vehicle_pedestrian": len(vehicle_ids) * (len(walker_ids) + len(stationary)),
        },
        "closest": {
            key: (None if value is math.inf else round(value, 4))
            for key, value in sorted(worst.items())
        },
        "required": {
            "walker_walker": separation,
            "walker_stationary": separation,
            "vehicle_vehicle": vehicle_gap,
            "walker_vehicle": pedestrian_gap,
        },
        "failures": failures,
        "safe": not failures,
    }


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def plan_daily_life_mobility(
    presence_plan: dict,
    presence_spec: dict,
    mobility_spec: dict,
    timeline: dict,
    master_spec: dict,
    production_spec: dict,
    graph: dict,
    fabric_plan: dict,
) -> dict:
    """The whole moving city, as one document that explains itself.

    Raises:
        MobilityPlanError: If the city cannot carry the declared traffic, if a
            route cannot be proven safe, or if the finished plan's own
            collision proof fails.
    """
    pedestrians = plan_pedestrian_mobility(
        presence_plan,
        mobility_spec,
        timeline,
        master_spec,
        production_spec,
        presence_spec,
        graph,
        fabric_plan,
    )
    vehicles = plan_vehicle_mobility(mobility_spec, timeline, master_spec, graph, fabric_plan)
    plan = {
        "format": MOBILITY_PLAN_FORMAT,
        "schema_version": MOBILITY_PLAN_SCHEMA_VERSION,
        "statement": PRESENTATION_STATEMENT,
        "timeline": dict(sorted(timeline.items())),
        "pedestrians": pedestrians,
        "vehicles": vehicles,
    }
    plan["collision"] = mobility_collisions(plan, timeline, presence_plan, mobility_spec)
    if not plan["collision"]["safe"]:
        raise MobilityPlanError(
            "the mobility plan is not collision free:\n- "
            + "\n- ".join(plan["collision"]["failures"][:6])
        )
    budget = mobility_spec["vehicles"]["budget"]
    if vehicles["layer_triangles"] > int(budget["layer_triangles"]):
        raise MobilityPlanError(
            f"the vehicle layer costs {vehicles['layer_triangles']} triangles, above the "
            f"declared {budget['layer_triangles']}"
        )
    worst = max(
        (vehicle_kit.vehicle_triangles(name) for name in vehicles["by_archetype"]), default=0
    )
    if worst > int(budget["triangles_per_vehicle"]):
        raise MobilityPlanError(
            f"the heaviest vehicle costs {worst} triangles, above the declared "
            f"{budget['triangles_per_vehicle']}"
        )
    # PRECISE metric names. "Movers" is not a number this project is allowed to
    # be vague about: the mobility domain holds 80 population proxies and 14
    # vehicles, but only 24 of those proxies and all 14 vehicles actually move,
    # so the moving-root-object count is 38 and nothing else. Reporting the
    # domain size as a motion figure would overstate how much of the city is
    # alive.
    plan["summary"] = {
        "total_population_proxies": pedestrians["total_proxies"],
        "moving_pedestrians": pedestrians["moving"],
        "stationary_pedestrians": pedestrians["stationary"],
        "moving_vehicles": vehicles["count"],
        "total_visible_population_and_vehicles": pedestrians["total_proxies"] + vehicles["count"],
        "total_moving_root_objects": pedestrians["moving"] + vehicles["count"],
        "vehicle_capacity": vehicles["capacity"],
        "vehicle_target": vehicles["target_count"],
        "circuits": len(vehicles["circuits"]),
        "routes_by_family": vehicles["route_offer"]["by_family"],
        "traffic_extent_x": vehicles["coverage"]["traffic_extent_x"],
        "traffic_extent_y": vehicles["coverage"]["traffic_extent_y"],
        "traffic_regions": vehicles["coverage"]["regions_with_traffic"],
        "road_segment_coverage": vehicles["coverage"]["segment_coverage"],
        "vehicle_triangles": vehicles["layer_triangles"],
        "collision_safe": plan["collision"]["safe"],
        "frames_sampled": plan["collision"]["frames_sampled"],
        "pedestrian_speed_range": [
            round(min(entry["speed"] for entry in pedestrians["walkers"]), 4),
            round(max(entry["speed"] for entry in pedestrians["walkers"]), 4),
        ],
        "pedestrian_excursion_range": [
            round(min(entry["excursion"] for entry in pedestrians["walkers"]), 4),
            round(max(entry["excursion"] for entry in pedestrians["walkers"]), 4),
        ],
        "vehicle_speed_range": [
            round(min(entry["speed"] for entry in vehicles["vehicles"]), 4),
            round(max(entry["speed"] for entry in vehicles["vehicles"]), 4),
        ],
    }
    return plan


def mobility_plan_hash(plan: dict) -> str:
    """A stable digest of one mobility plan.

    Canonical JSON with sorted keys, so the same world and the same specs
    produce the same digest on any machine and under any ``PYTHONHASHSEED``.
    """
    payload = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_mobility_plan(plan: dict, presence_plan: dict, mobility_spec: dict) -> list[str]:
    """Audit a finished plan against its own published numbers.

    Deliberately independent of the planner: every claim is recomputed from
    what the plan SAYS, so a plan that is internally inconsistent fails even
    when the code that produced it is not available.
    """
    errors: list[str] = []
    if plan.get("format") != MOBILITY_PLAN_FORMAT:
        errors.append(f"plan format is {plan.get('format')!r}")
    if plan.get("schema_version") != MOBILITY_PLAN_SCHEMA_VERSION:
        errors.append(f"plan schema_version is {plan.get('schema_version')!r}")
    if plan.get("statement") != PRESENTATION_STATEMENT:
        errors.append("the plan does not carry the presentation-mobility statement verbatim")

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
    wanted = walking.walker_count(len(known), mobility_spec)
    if pedestrians["moving"] != wanted:
        errors.append(
            f"the plan walks {pedestrians['moving']} of {len(known)} proxies; the declared "
            f"fraction derives {wanted}, and a quietly smaller crowd is a shortfall, not a plan"
        )

    timeline = plan["timeline"]
    for walker in pedestrians["walkers"]:
        anchor = walker["anchor"]
        proxy = known.get(walker["slot"])
        if proxy is None:
            continue
        for axis in ("x", "y", "z"):
            if abs(float(anchor[axis]) - float(proxy[axis])) > 1.0e-6:
                errors.append(
                    f"{walker['slot']} claims an anchor {axis}={anchor[axis]}, Phase 18 "
                    f"placed it at {proxy[axis]}"
                )
        points = [tuple(point) for point in walker["points"]]
        if math.dist(points[0], points[-1]) > 1.0e-6:
            errors.append(f"{walker['slot']} route does not close")
        drift = math.hypot(points[0][0] - anchor["x"], points[0][1] - anchor["y"])
        if drift > mobility_spec["pedestrians"]["route"]["anchor_tolerance"]:
            errors.append(
                f"{walker['slot']} route starts {drift:.3f} from its own anchor, beyond the "
                "declared tolerance"
            )
        measured = polyline_length(points)
        if abs(measured - walker["route_length"]) > 1.0e-4:
            errors.append(
                f"{walker['slot']} claims a {walker['route_length']} route, its points "
                f"measure {measured:.4f}"
            )
        expected = pedestrian_route_length(walker["speed"], timeline) * walker["cycles"]
        if abs(measured - expected) > 1.0e-3:
            errors.append(
                f"{walker['slot']} travels {measured:.3f}m per cycle at {walker['speed']}m/s, "
                f"which needs {expected:.3f}m to close on this timeline"
            )
        gait = walker["gait"]
        if abs(gait["effective_stride"] * gait["cycles"] - measured) > 1.0e-3:
            errors.append(
                f"{walker['slot']} takes {gait['cycles']} strides of "
                f"{gait['effective_stride']}m over a {measured:.3f}m route"
            )
        reach = 4.0 * gait["leg_length"] * math.sin(gait["leg_swing"])
        if abs(reach - gait["effective_stride"]) > 1.0e-4:
            errors.append(
                f"{walker['slot']} swings its legs {gait['leg_swing_deg']} degrees, which "
                f"covers {reach:.3f}m against a {gait['effective_stride']}m stride -- the "
                "gait does not match the travel"
            )
        stations = loop_stations(points)
        start = sample_loop(stations, 0.0)
        end = sample_loop(
            stations, frame_distance(timeline["end_frame"], timeline, measured, walker["cycles"])
        )
        for axis in ("x", "y", "z", "heading"):
            if abs(start[axis] - end[axis]) > 1.0e-6:
                errors.append(f"{walker['slot']} does not loop: {axis} differs at the endpoints")

    vehicles = plan["vehicles"]
    if vehicles["count"] != len(vehicles["vehicles"]):
        errors.append("the vehicle count and the vehicle list disagree")
    if vehicles["count"] != vehicles["target_count"]:
        errors.append(
            f"the plan ships {vehicles['count']} vehicles against a target of "
            f"{vehicles['target_count']}"
        )
    circuits = {entry["circuit"]: entry for entry in vehicles["circuits"]}
    for entry in vehicles["circuits"]:
        points = [tuple(point) for point in entry["points"]]
        if math.dist(points[0], points[-1]) > 1.0e-6:
            errors.append(f"{entry['circuit']} does not close")
        measured = polyline_length(points)
        if abs(measured - entry["length"]) > 1.0e-4:
            errors.append(
                f"{entry['circuit']} claims {entry['length']}m, its points measure {measured:.4f}"
            )
        expected = entry["speed"] * timeline["vehicle_cycle_seconds"]
        if abs(measured - expected) > 1.0e-3:
            errors.append(
                f"{entry['circuit']} would travel {expected:.3f}m at {entry['speed']}m/s, "
                f"but is {measured:.3f}m long"
            )
        band = mobility_spec["vehicles"]["speed"]
        if not band["min"] <= entry["speed"] <= band["max"]:
            errors.append(
                f"{entry['circuit']} runs at {entry['speed']}m/s, outside the declared band"
            )
    seen_phase: dict[str, list[float]] = {}
    for vehicle in vehicles["vehicles"]:
        circuit = circuits.get(vehicle["circuit"])
        if circuit is None:
            errors.append(f"{vehicle['slot']} drives an undeclared circuit")
            continue
        size = vehicle_kit.vehicle_dimensions(vehicle["archetype"])
        for field, key in (("length", "length"), ("width", "width"), ("height", "height")):
            if abs(float(vehicle[field]) - size[key]) > 1.0e-6:
                errors.append(
                    f"{vehicle['slot']} claims {field} {vehicle[field]}, the kit builds {size[key]}"
                )
        travelled = circuit["length"] * vehicle["cycles"]
        if vehicle["wheel_turns"] != int(vehicle["wheel_turns"]):
            errors.append(
                f"{vehicle['slot']} claims {vehicle['wheel_turns']} wheel turns, which is not "
                "a whole number; its wheels would not close the loop"
            )
        rolled = 2.0 * math.pi * vehicle["rolling_radius"] * vehicle["wheel_turns"]
        if abs(rolled - travelled) > 1.0e-6:
            errors.append(
                f"{vehicle['slot']} rolls {rolled:.6f}m on {vehicle['wheel_turns']} turns of a "
                f"{vehicle['rolling_radius']}m wheel, over a {travelled:.6f}m circuit"
            )
        drift = abs(vehicle["rolling_radius"] / size["wheel_radius"] - 1.0)
        if drift > mobility_spec["vehicles"]["rolling_radius_tolerance"] + 1.0e-9:
            errors.append(
                f"{vehicle['slot']} rolling radius is {drift:.1%} from its geometric wheel"
            )
        seen_phase.setdefault(vehicle["circuit"], []).append(vehicle["phase"])
    for circuit_id, phases in sorted(seen_phase.items()):
        circuit = circuits[circuit_id]
        ordered = sorted(phases)
        for first, second in zip(ordered, ordered[1:], strict=False):
            gap = (second - first) * circuit["length"]
            if gap < mobility_spec["vehicles"]["slot_pitch"] - 1.0e-6:
                errors.append(
                    f"{circuit_id} places two vehicles {gap:.3f}m apart along the circuit, "
                    f"below the declared {mobility_spec['vehicles']['slot_pitch']} pitch"
                )
        if len(set(ordered)) != len(ordered):
            errors.append(f"{circuit_id} places two vehicles at the same phase")

    if plan["collision"]["failures"]:
        errors.extend(plan["collision"]["failures"][:6])
    return errors


def resample_route(points: list, step: float) -> list:
    """A route resampled for the applier, keeping the loop exactly closed."""
    resampled = resample_polyline(points, step)
    resampled[-1] = tuple(points[-1])
    return resampled
