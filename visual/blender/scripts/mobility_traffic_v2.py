"""V2 vehicle traffic: bounded-arc presentation on V1's real closed circuits.

Phase 19 V1 already owns the traffic safety machinery and the doctrine that
goes with it: ``plan_vehicle_lanes`` refuses any two routes that share a lane
claim, gates every remaining pair on ``worst_body_gap`` -- a time-independent
geometric guarantee, "no timing, no phase, no schedule" -- and then runs an
exact search over mutually compatible route sets. ``mobility_collisions`` then
sweeps every pair of vehicles on every sampled frame of the canonical timeline
and refuses the finished plan unless it reports ``safe``.

V2 invents no new collision mechanism and no new road shape. The locked EP1
world's only two legal turnarounds lie in DISCONNECTED components of the
dual-lane subgraph, so ``enumerate_out_and_back`` returns zero genuinely open
out-and-back routes at any length -- ``summary.legal_turnarounds == 2``,
``summary.candidates_offered.out_and_back == 0``. That structural finding
stands and is reported, never fabricated into a route. The V2 presentation fix
is therefore entirely in HOW MUCH of a closed circuit's real geometry a
vehicle SHOWS moving: every V2 vehicle drives a bounded arc
(``presentation_arc_fraction`` of its circuit) instead of V1's full lap, so it
never returns to a screen position it has already occupied and reads as
"enters, drives, exits" rather than circling a block.

The lane-selection call below passes ``prefer_open_routes=True`` exactly as
before; on the locked EP1 network the preference is inert (zero open
candidates), so the real circuit selection is identical with or without it and
V1 -- which never passes the flag -- keeps its byte-for-byte selection. The
arc itself is planned in :mod:`mobility_plan` (``plan_vehicle_mobility`` with
``traffic_profile="v2"``): the wheel-closure contract is bypassed for V2 (an
arc that never returns to its start needs no closure), the real wheel radius
rolls continuously over the arc's real distance, and the collision proof
reads the same arc distance, so the plan, the proof and the Blender-side
per-vehicle curve keyframing all agree on one number.

This module is pure Python (no ``bpy``). It widens the candidate set the gate
is asked to carry, adds the V2-only selection preference, and reports the
traffic metrics the V2 campaign must emit.
"""

import math

from vehicle_lane_network import plan_vehicle_lanes


def plan_vehicle_traffic_v2(
    master_spec: dict,
    graph: dict,
    ground: dict,
    mobility_spec: dict,
    vehicle_half_width: float,
    timeline: dict,
) -> dict:
    """The V2 lane plan, fed through V1's existing structural gate.

    The candidate set is deliberately the union of BOTH route families the lane
    network can enumerate, and the whole set is passed to the EXISTING
    ``plan_vehicle_lanes`` gate, which performs candidate generation, the
    corner-radius ladder with length-band and ``on_carriageway`` filtering, the
    ``lane_key`` claims, the shared-claim plus ``worst_body_gap`` pairwise gate,
    and the exact-search selection described in the module docstring.

    The one V2-only difference is the selection preference: this call passes
    ``prefer_open_routes=True`` so the exact search prefers a set containing an
    open out-and-back route among sets that reach the same capacity. On the
    locked EP1 network the open family is structurally empty (see the module
    docstring), so the preference is a no-op there and this call returns the
    same closed circuits V1 would; V1 never passes the flag, so V1's pairwise
    gate and selection are otherwise unchanged.

    The returned document has exactly the shape ``plan_vehicle_lanes`` returns,
    so the rest of the mobility pipeline -- the even-phase slot grid
    (``vehicle_route_slots``), the per-slot ``mobility_seed`` RNG draws, and
    the ``mobility_collisions`` frame sweep -- consumes it unchanged. The
    bounded-arc presentation itself (``presentation_arc_fraction``) is applied
    downstream, in ``mobility_plan.plan_vehicle_mobility`` with
    ``traffic_profile="v2"``, which is what gives every V2 vehicle its own
    non-repeating travelled distance; this call only selects the circuits.
    """
    return plan_vehicle_lanes(
        master_spec,
        graph,
        ground,
        mobility_spec,
        vehicle_half_width,
        timeline,
        prefer_open_routes=True,
    )


def is_open_route(circuit: dict) -> bool:
    """True for a genuinely open out-and-back route, False for a closed circuit.

    The lane network publishes the family discriminator as the route's
    ``direction``: closed circuits are ``"cw"``/``"ccw"``, out-and-back routes
    are ``"shuttle"``.
    """
    return circuit.get("direction") == "shuttle"


def open_route_endpoints(circuit: dict, network: dict) -> tuple[str, str]:
    """The two network nodes an oriented route enters and exits at.

    Read from the route's own runs and the network's run table: the node where
    the first run starts and the node where the last run ends. A closed circuit
    returns the same node twice; a genuinely open out-and-back returns two
    different ones. Both are boundary nodes when the route family is open,
    because the lane network only offers an out-and-back between two declared
    terminations.
    """
    runs = network["runs"]
    ordered = circuit["runs"]
    if not ordered:
        raise ValueError("a route with no runs has no endpoints")
    first = runs[ordered[0]["run"]]
    last = runs[ordered[-1]["run"]]
    entry = first["node_a"] if ordered[0]["forward"] else first["node_b"]
    exit_node = last["node_b"] if ordered[-1]["forward"] else last["node_a"]
    return entry, exit_node


def route_chain_continuous(circuit: dict, network: dict) -> bool:
    """True when every consecutive pair of runs shares a real graph node.

    Each network run carries the two junction ids it connects
    (``node_a``/``node_b``); a chain is only connected when consecutive runs
    share one of them, so a route that teleports between roads fails here.
    """
    runs = network["runs"]
    ordered = circuit["runs"]
    if not ordered:
        return False
    for first, second in zip(ordered, ordered[1:], strict=False):
        a, b = runs[first["run"]], runs[second["run"]]
        if not ({a["node_a"], a["node_b"]} & {b["node_a"], b["node_b"]}):
            return False
    return True


def route_chain_simple(circuit: dict) -> bool:
    """True when no run is driven twice in the same direction on one route.

    A closed circuit walks each run once; an out-and-back walks each run
    forward outbound and in the opposite direction inbound, so the ``(run,
    forward)`` pairs stay distinct. A repeat of the same directional claim
    inside one route is a route-repeat violation.
    """
    seen: set = set()
    for item in circuit.get("runs", []):
        key = (item["run"], item["forward"])
        if key in seen:
            return False
        seen.add(key)
    return True


def traffic_v2_metrics(plan: dict) -> dict:
    """Every traffic metric the V2 campaign must emit, from one finished plan.

    Reads the PUBLISHED plan only -- the vehicle list, the circuit list, the
    coverage block and the collision proof -- so a reviewer can run it against
    any plan document without rebuilding anything.

    Speeds are each vehicle's REAL average speed over its presentation window
    (for V2: ``circuit_speed * presentation_arc_fraction``, the honest
    distance/time figure for a bounded arc), never a masked full-lap number.
    """
    vehicles_section = plan["vehicles"]
    vehicles = vehicles_section["vehicles"]
    circuits = vehicles_section["circuits"]
    coverage = vehicles_section["coverage"]
    speeds = [float(entry["speed"]) for entry in vehicles]
    arcs = [float(entry.get("presentation_arc_fraction", 1.0)) for entry in vehicles]
    arc_distances = [float(entry.get("arc_distance", entry["route_length"])) for entry in vehicles]
    open_routes = [entry for entry in circuits if is_open_route(entry)]
    return {
        "active_vehicle_count": len(vehicles),
        "distinct_route_count": len(circuits),
        "open_route_count": len(open_routes),
        "closed_circuit_count": len(circuits) - len(open_routes),
        "distinct_segment_count": len(coverage["segments_carrying_traffic"]),
        "speed_min": round(min(speeds), 6) if speeds else 0.0,
        "speed_max": round(max(speeds), 6) if speeds else 0.0,
        "speed_mean": round(math.fsum(speeds) / len(speeds), 6) if speeds else 0.0,
        "presentation_arc_fraction_min": round(min(arcs), 6) if arcs else 0.0,
        "presentation_arc_fraction_max": round(max(arcs), 6) if arcs else 0.0,
        "arc_distance_min": round(min(arc_distances), 6) if arc_distances else 0.0,
        "arc_distance_max": round(max(arc_distances), 6) if arc_distances else 0.0,
        "collision_violation_count": len(plan["collision"]["failures"]),
        "route_repeat_violation_count": sum(
            0 if route_chain_simple(entry) else 1 for entry in circuits
        ),
    }
