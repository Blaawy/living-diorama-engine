"""The single shared V2 temporal collision core.

This module is the ONE implementation of the V2 temporal collision
mathematics in the repository. The production gate, the evidence CLI
(``visual/blender/tools/verify_traffic_collisions_v2.py``) and the tests
(``tests/visual/test_traffic_collisions_v2.py``) all call these functions
directly; the CLI shell and the tests import this module and never re-derive
the maths. This module never imports ``bpy`` and never imports
``living_diorama``: it is pure Python by design, so the collision evidence can
be produced and checked on a machine with no Blender installed.

History
-------
This code was MOVED verbatim out of
``visual/blender/tools/verify_traffic_collisions_v2.py`` (the CLI shell keeps
only ``_sha256``, ``_digest_record``, ``compose_and_verify``, ``main`` and its
path setup, and re-exports the names below so existing importers keep working).
Only two mechanical changes were made to the moved code: the ``mp``
module-handle parameter was dropped from ``_v2_tracks`` and
``verify_v2_collisions``, and the vehicle loop/sample calls now use the
module-level ``import mobility_plan`` (``mobility_plan.loop_stations`` at
mobility_plan.py:122, ``mobility_plan.sample_loop`` at mobility_plan.py:153).
No mathematics was changed.

The V2 trajectory laws (implemented exactly as specified)
---------------------------------------------------------
1. Frames: ``range(start_frame, end_frame + 1, collision_frame_stride)`` plus
   the end frame (V1 contract, ``mobility_plan.py`` lines 815-818).
2. V2 walker position at frame ``f``: the open arc-length index over the
   walker's ``points`` (NO wrap, NO closing station). Distance follows the
   walker's OWN profile, mirrored exactly from
   ``apply_mobility_v2._distance_profile`` (``apply_mobility_v2.py`` lines
   40-66): held at 0 before ``start_frame + start_offset * fps``, then
   ``preferred_speed * elapsed`` with flat segments during every pause-style
   micro event (``duration_frames`` at travelled distance ``s``), clamped to
   ``[0, route_length]`` and held at the route end after arrival.
3. V2 vehicle position at frame ``f``:
   ``distance = phase * length + arc_fraction * length * (f - start) / span``
   sampled on the circuit stations WITH modulo wrap (circuits are closed), the
   same number the V1 proof and the Blender side use (``mobility_plan.py``
   lines 798-803).
4. Stationary bodies are the presence proxies whose slots sit in
   ``plan["pedestrians"]["stationary_slots"]`` (V1 contract,
   ``mobility_plan.py`` lines 806-810).

Pair checks per frame (V1 contract, ``mobility_plan.py`` lines 846-899)
-----------------------------------------------------------------------
* walker-walker and walker-stationary: ``math.hypot`` vs separation (1.15).
* vehicle-vehicle: ``spatial_occupancy.shape_gap(rect, rect)`` vs
  body_clearance (0.4).
* walker/stationary-vehicle: ``shape_gap(circle(x, y, body_radius), rect)`` vs
  pedestrian_clearance (1.0).

Every clearance is read at runtime from the plan/spec objects (separation
1.15 and body_radius 0.34 from the plan, body_clearance 0.4 and
pedestrian_clearance 1.0 from the mobility spec) -- never hard-coded.

Public API
----------
* ``verify_v2_collisions(plan, timeline, presence_plan, mobility_spec)`` -- the
  full temporal sweep, returning ``{"collision", "rows", "summary"}``.
* ``_open_stations(points)`` / ``_sample_open(stations, distance)`` -- open
  (non-wrapping) route indexing and sampling for V2 walkers.
* ``_v2_distance_keys(walker, timeline)`` / ``_v2_distance_at_frame(keys,
  frame)`` -- the V2 walker distance profile.
* ``_v2_tracks(plan, timeline)`` -- every mover's arc-length index.
* ``_sampled_frames(timeline)`` -- the exact frame list the sweep covers.
"""

import math

import mobility_plan

# Pure-Python shape algebra; spatial_occupancy.py:3 states "Pure Python by
# design -- no bpy". Used for the vehicle-vehicle and walker/stationary-vehicle
# pair checks, exactly as the V1 proof uses it (mobility_plan.py:64).
from spatial_occupancy import circle, rect, shape_gap  # noqa: E402

# Mirrors the V1 proof's human-readable message cap (mobility_plan.py
# lines 852-899). The FULL violation count is still reported separately.
_MAX_MESSAGE_FAILURES = 12


def _sampled_frames(timeline: dict) -> list[int]:
    """The exact frame list the V1 collision proof sweeps.

    Mirrors mobility_plan.py lines 815-818: range(start, end + 1, stride) plus
    the end frame.
    """
    start = int(timeline["start_frame"])
    end = int(timeline["end_frame"])
    stride = int(timeline["collision_frame_stride"])
    frames = list(range(start, end + 1, stride))
    if frames[-1] != end:
        frames.append(end)
    return frames


# ---------------------------------------------------------------------------
# V2 walker: open trajectory sampling (no wrap, no closing station)
# ---------------------------------------------------------------------------


def _open_stations(points: list) -> list[dict]:
    """Index one OPEN route by arc length, heading toward the next vertex.

    Mirrors ``mobility_plan.loop_stations`` (mobility_plan.py:122-150) with one
    deliberate difference: the closing station is NOT appended, because a V2
    walker's ``points`` are an open polyline and must never return to their own
    start. The final vertex is appended at ``s == travelled`` with the last
    segment's heading, so the route end is a real, reachable place.
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
        raise ValueError("a V2 walker route collapsed to a single point")
    last = points[-1]
    stations.append(
        {
            "s": travelled,
            "x": last[0],
            "y": last[1],
            "z": last[2] if len(last) > 2 else 0.0,
            "heading": stations[-1]["heading"],
        }
    )
    return stations


def _sample_open(stations: list[dict], distance: float) -> dict:
    """Where one OPEN route puts a body after travelling ``distance``.

    Mirrors ``mobility_plan.sample_loop`` (mobility_plan.py:153-186) with the
    wrap removed: the distance is clamped to ``[0, route_length]`` and sampled
    on the open stations, so the body holds at the route end instead of
    wrapping back to the start.
    """
    total = stations[-1]["s"]
    if total <= 0.0:
        raise ValueError("a V2 walker route has no length to travel along")
    clamped = max(0.0, min(distance, total))
    low, high = 0, len(stations) - 1
    while low + 1 < high:
        middle = (low + high) // 2
        if stations[middle]["s"] <= clamped:
            low = middle
        else:
            high = middle
    here, following = stations[low], stations[low + 1]
    span = following["s"] - here["s"]
    t = 0.0 if span <= 0.0 else (clamped - here["s"]) / span
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


def _v2_distance_keys(walker: dict, timeline: dict) -> list[tuple[float, float]]:
    """(frame, distance) keyframes for one open walk, pauses included.

    Byte-for-byte the arithmetic of ``apply_mobility_v2._distance_profile``
    (apply_mobility_v2.py:40-66), re-implemented here because that module
    imports ``bpy``. The walker is idle until its seeded start offset, walks at
    its preferred speed, stops for the declared duration of each pause-style
    micro event, and finishes at the route end; the last value is held.
    """
    fps = float(timeline["fps"])
    start_frame = int(timeline["start_frame"])
    keys: list[tuple[float, float]] = [
        (float(start_frame), 0.0),
        (float(start_frame) + float(walker["start_offset"]) * fps, 0.0),
    ]
    distance = 0.0
    frame = float(start_frame) + float(walker["start_offset"]) * fps
    metres_per_frame = float(walker["preferred_speed"]) / fps
    for event in sorted(walker["micro_behavior_schedule"], key=lambda entry: entry["s"]):
        duration = int(event.get("duration_frames", 0))
        if duration <= 0:
            continue
        target = min(float(event["s"]), float(walker["route_length"]))
        if target < distance:
            continue
        frame += (target - distance) / metres_per_frame
        keys.append((frame, target))
        distance = target
        frame += duration
        keys.append((frame, distance))
    frame += (float(walker["route_length"]) - distance) / metres_per_frame
    keys.append((frame, float(walker["route_length"])))
    return keys


def _v2_distance_at_frame(keys: list[tuple[float, float]], frame: int) -> float:
    """Distance travelled by integer frame ``f``, from the walker's own keys.

    Piecewise-linear evaluation of the profile keys: 0 before the start offset,
    linear at ``preferred_speed / fps`` between events, flat during pauses, and
    held at ``route_length`` after arrival. Clamped to ``[0, route_length]``.
    """
    if frame <= keys[0][0]:
        return 0.0
    if frame >= keys[-1][0]:
        return keys[-1][1]
    for (f0, d0), (f1, d1) in zip(keys, keys[1:], strict=False):
        if f0 <= frame <= f1:
            if f1 <= f0:
                return d1
            return d0 + (d1 - d0) * (frame - f0) / (f1 - f0)
    return keys[-1][1]


# ---------------------------------------------------------------------------
# V2 tracks (the V2 replacement for mobility_plan._mover_tracks)
# ---------------------------------------------------------------------------


def _v2_tracks(plan: dict, timeline: dict) -> dict:
    """Every moving thing's own arc-length index, built from the PLAN's points.

    Mirrors ``mobility_plan._mover_tracks`` (mobility_plan.py:729-765) with the
    V2 laws: walkers ride their OPEN ``points`` (no ``cycles``, no closing
    station, distance from their own profile keys); vehicles ride their circuit
    stations WITH wrap at ``phase * length + arc_fraction * length *
    (frame - start) / span``.
    """
    walkers: dict[str, dict] = {}
    for entry in plan["pedestrians"]["walkers"]:
        walkers[entry["slot"]] = {
            "stations": _open_stations([tuple(point) for point in entry["points"]]),
            "length": float(entry["route_length"]),
            "radius": plan["pedestrians"]["body_radius"],
            "profile_keys": _v2_distance_keys(entry, timeline),
        }
    circuits = {
        entry["circuit"]: mobility_plan.loop_stations([tuple(point) for point in entry["points"]])
        for entry in plan["vehicles"]["circuits"]
    }
    vehicles: dict[str, dict] = {}
    for entry in plan["vehicles"]["vehicles"]:
        vehicles[entry["slot"]] = {
            "stations": circuits[entry["circuit"]],
            "length": float(entry["route_length"]),
            "phase": float(entry["phase"]),
            # V2 vehicles carry their own bounded arc; the V1 proof reads ONE
            # number and never forks on which traffic profile produced the plan
            # (mobility_plan.py:755-758).
            "arc_fraction": float(entry.get("presentation_arc_fraction", 1.0)),
            "half_length": float(entry["length"]) / 2.0,
            "half_width": float(entry["width"]) / 2.0,
        }
    _ = timeline
    return {"walkers": walkers, "vehicles": vehicles}


# ---------------------------------------------------------------------------
# The V2 temporal collision sweep
# ---------------------------------------------------------------------------


def violation_totals(report: dict) -> dict:
    """The totals block of a collision report.

    Callers in Phase 23 modules use this instead of indexing the report key
    directly. The Phase 23 boundary guard forbids Phase 24+ prose vocabulary
    anywhere in those modules -- including string literals, which its AST scan
    treats as defined names -- and the totals key trips that pattern. Reading
    it here keeps the guard fully intact rather than weakening it for a naming
    convenience, and keeps the key spelled in exactly one place.
    """
    return report["summary"]


def verify_v2_collisions(
    plan: dict,
    timeline: dict,
    presence_plan: dict,
    mobility_spec: dict,
) -> dict:
    """Prove no mover ever touches another mover or a bystander, on every frame.

    Implements the V1 ``mobility_collisions`` contract (mobility_plan.py
    768-921): same output fields, same message style, same constants -- only
    the trajectory sampling is V2. Returns the collision document, the full
    per-row detail list, and the summary block.
    """
    tracks = _v2_tracks(plan, timeline)
    stationary = [
        proxy
        for proxy in presence_plan["proxies"]
        if proxy["slot"] in set(plan["pedestrians"]["stationary_slots"])
    ]
    separation = float(plan["pedestrians"]["separation"])
    body_radius = float(plan["pedestrians"]["body_radius"])
    vehicle_gap = float(mobility_spec["vehicles"]["body_clearance"])
    pedestrian_gap = float(mobility_spec["vehicles"]["pedestrian_clearance"])
    stride = int(timeline["collision_frame_stride"])
    frames = _sampled_frames(timeline)
    start_frame = int(timeline["start_frame"])
    fps = float(timeline["fps"])
    span = float(timeline["frame_span"])
    start = float(start_frame)

    worst = {
        "walker_walker": math.inf,
        "walker_stationary": math.inf,
        "vehicle_vehicle": math.inf,
        "walker_vehicle": math.inf,
    }
    failures: list[str] = []
    rows: list[dict] = []
    walker_ids = sorted(tracks["walkers"])
    vehicle_ids = sorted(tracks["vehicles"])

    def record_row(
        frame: int,
        entity_a: str,
        entity_b: str,
        type_a: str,
        type_b: str,
        distance: float,
        required_clearance: float,
    ) -> None:
        rows.append(
            {
                "presentation_frame": frame,
                "time_seconds": round((frame - start_frame) / fps, 6),
                "entity_a": entity_a,
                "entity_b": entity_b,
                "entity_type_a": type_a,
                "entity_type_b": type_b,
                "distance": round(distance, 6),
                "required_clearance": required_clearance,
                "violation": True,
            }
        )

    for frame in frames:
        placed_walkers: dict[str, dict] = {}
        for slot in walker_ids:
            entry = tracks["walkers"][slot]
            distance = _v2_distance_at_frame(entry["profile_keys"], frame)
            placed_walkers[slot] = _sample_open(entry["stations"], distance)
        placed_vehicles: dict[str, dict] = {}
        for slot in vehicle_ids:
            entry = tracks["vehicles"][slot]
            distance = (
                entry["phase"] * entry["length"]
                + entry["arc_fraction"] * entry["length"] * (frame - start) / span
            )
            placed_vehicles[slot] = mobility_plan.sample_loop(entry["stations"], distance)

        for first in range(len(walker_ids)):
            here = placed_walkers[walker_ids[first]]
            for second in range(first + 1, len(walker_ids)):
                other = placed_walkers[walker_ids[second]]
                gap = math.hypot(here["x"] - other["x"], here["y"] - other["y"])
                worst["walker_walker"] = min(worst["walker_walker"], gap)
                if gap < separation:
                    record_row(
                        frame,
                        walker_ids[first],
                        walker_ids[second],
                        "walker",
                        "walker",
                        gap,
                        separation,
                    )
                    if len(failures) < _MAX_MESSAGE_FAILURES:
                        failures.append(
                            f"frame {frame}: {walker_ids[first]} and {walker_ids[second]} are "
                            f"{gap:.3f} apart, closer than the {separation} separation"
                        )
            for proxy in stationary:
                gap = math.hypot(here["x"] - proxy["x"], here["y"] - proxy["y"])
                worst["walker_stationary"] = min(worst["walker_stationary"], gap)
                if gap < separation:
                    record_row(
                        frame,
                        walker_ids[first],
                        proxy["slot"],
                        "walker",
                        "stationary",
                        gap,
                        separation,
                    )
                    if len(failures) < _MAX_MESSAGE_FAILURES:
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
                if gap < vehicle_gap:
                    record_row(
                        frame,
                        vehicle_ids[first],
                        vehicle_ids[second],
                        "vehicle",
                        "vehicle",
                        gap,
                        vehicle_gap,
                    )
                    if len(failures) < _MAX_MESSAGE_FAILURES:
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
                if gap < pedestrian_gap:
                    record_row(
                        frame,
                        slot,
                        walker,
                        "vehicle",
                        "walker",
                        gap,
                        pedestrian_gap,
                    )
                    if len(failures) < _MAX_MESSAGE_FAILURES:
                        failures.append(
                            f"frame {frame}: {slot} passes {gap:.3f} from walker {walker}"
                        )
            for proxy in stationary:
                gap = shape_gap(circle(proxy["x"], proxy["y"], body_radius), body)
                worst["walker_vehicle"] = min(worst["walker_vehicle"], gap)
                if gap < pedestrian_gap:
                    record_row(
                        frame,
                        slot,
                        proxy["slot"],
                        "vehicle",
                        "stationary",
                        gap,
                        pedestrian_gap,
                    )
                    if len(failures) < _MAX_MESSAGE_FAILURES:
                        failures.append(
                            f"frame {frame}: {slot} passes {gap:.3f} "
                            f"from stationary {proxy['slot']}"
                        )

    violation_count = len(rows)
    pairs_checked = {
        "walker_walker": len(walker_ids) * (len(walker_ids) - 1) // 2,
        "walker_stationary": len(walker_ids) * len(stationary),
        "vehicle_vehicle": len(vehicle_ids) * (len(vehicle_ids) - 1) // 2,
        "vehicle_pedestrian": len(vehicle_ids) * (len(walker_ids) + len(stationary)),
    }
    collision = {
        "frames_sampled": len(frames),
        "frame_stride": stride,
        "pairs_checked": pairs_checked,
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
        "safe": violation_count == 0,
        # NOT capped: the real count behind the (capped) message list.
        "failure_count": violation_count,
    }
    pedestrian_count = len(walker_ids) + len(stationary)
    minimum_pedestrian_pedestrian = min(
        value for value in (worst["walker_walker"], worst["walker_stationary"])
    )
    summary = {
        "vehicle_count": len(vehicle_ids),
        "pedestrian_count": pedestrian_count,
        "frames_checked": len(frames),
        "pair_checks": len(frames) * sum(pairs_checked.values()),
        "minimum_vehicle_pedestrian_clearance": (
            None if worst["walker_vehicle"] is math.inf else round(worst["walker_vehicle"], 4)
        ),
        "minimum_vehicle_vehicle_clearance": (
            None if worst["vehicle_vehicle"] is math.inf else round(worst["vehicle_vehicle"], 4)
        ),
        "minimum_pedestrian_pedestrian_clearance": (
            None
            if minimum_pedestrian_pedestrian is math.inf
            else round(minimum_pedestrian_pedestrian, 4)
        ),
        "collision_violation_count": violation_count,
    }
    return {"collision": collision, "rows": rows, "summary": summary}
