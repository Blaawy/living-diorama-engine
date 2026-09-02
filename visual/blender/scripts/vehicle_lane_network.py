"""Where a vehicle is ALLOWED to drive in the Phase 16 city.

Pure Python by design -- no ``bpy``. This module answers one question and
refuses to answer any other: given the streets the LOCKED Phase 16 road graph
declares, which lane could a vehicle of the declared envelope occupy without
leaving the carriageway?

It reads :mod:`road_graph` STRICTLY READ-ONLY. No street is bent, widened,
trimmed or invented here, and no path is hand-drawn to look like a road: a lane
is an offset of an authored carriageway or it does not exist.

    THE CARRIAGEWAY DECIDES, NOT THE OCCUPANCY ENVELOPE.

Phase 16 publishes two widths per street. ``ROAD_CLASS_WIDTHS`` is the
CARRIAGEWAY -- the surface a vehicle may use. ``road_occupancy`` is the wider
envelope of everything the street physically occupies, sidewalks and lamp
verges included, and a vehicle driving to that edge would be driving on the
pavement. Every lane here is measured against the carriageway, which is also
what makes vehicles and Phase 18 pedestrians structurally separate: a body
stands at ``occupancy + offset`` and a vehicle never reaches ``occupancy``.

LANE POLICY
-----------
A carriageway either fits two vehicle lanes, one, or none::

    dual      half >= half_lane + vehicle_half + margin, on both sides of the
              centreline; the street carries a lane in each direction and
              right-hand traffic puts each one on its own side
    single    the carriageway holds ONE centred lane; the run is then usable by
              exactly one circuit in exactly one direction, and the network
              records it as such rather than squeezing two lanes into a width
              that cannot hold them
    refused   not even one lane fits; the run carries no traffic at all

That middle case is a refusal, not a compromise: it refuses the two-lane split
the width cannot support. A run it produces is claimed once and never shared.

THE LOOP CONTRACT SIZES THE CIRCUITS
------------------------------------
A vehicle has to be in the same place on the first and last frame, so it drives
a CLOSED circuit an exact whole number of times. Its speed is therefore its
circuit's length divided by the cycle duration, and the declared speed band
turns directly into a band of admissible circuit lengths. A circuit outside
that band is refused -- never driven too fast, never left half-driven.
"""

import math

from mobility_spec import vehicle_route_length_bounds
from road_graph import ROAD_CLASS_WIDTHS, junction_pads
from spatial_occupancy import capsule as capsule_shape
from spatial_occupancy import founding_building_footprints, rect, shape_gap
from urban_fabric import ring_occupancy_paths


def vehicle_kit_longest() -> float:
    """The RESERVED length of the longest vehicle the kit can build.

    A reservation, not a measurement. Circuit compatibility is derived from it,
    so it is deliberately frozen against restyling: if this reported the body
    the kit currently emits, reshaping a car would silently change which
    streets the city's traffic drives down.
    """
    import vehicle_kit

    return vehicle_kit.longest_vehicle()


def _rect_gap(first: dict, second: dict) -> float:
    """The gap between two oriented vehicle rectangles."""
    return shape_gap(
        rect(first["x"], first["y"], first["half_w"], first["half_d"], first["rot"]),
        rect(second["x"], second["y"], second["half_w"], second["half_d"], second["rot"]),
    )


MIN_RUN_LENGTH = 0.6
"""A run shorter than this is a junction artefact, not a piece of street."""

RING_LIVE_TOLERANCE = 0.35
"""How close a founding ring point must lie to surviving ring pavement.

The final Phase 16 composition BURIES the founding ring sectors the city no
longer uses under the urban table, so a ring road's polyline is not its
pavement. Driving a vehicle along a buried sector would drive it through the
ground, so every ring run is tested against the surviving occupancy paths
before it is allowed to carry traffic."""

MAX_TURN_ANGLE = math.radians(150.0)
"""The sharpest junction turn a lane may be filleted through.

Beyond this the tangent length of a fillet runs away and the manoeuvre stops
being a turn and becomes a U-turn, which no ambient traffic in this city
performs. Refused rather than approximated."""

STRAIGHT_TOLERANCE = math.radians(1.5)
"""Below this a junction is a continuation, and no fillet is inserted."""

FILLET_RUN_SHARE = 0.42
"""How much of one run each of its two junction fillets may claim.

A run is filleted at BOTH ends, and the two tangent lengths must not overlap or
the lane would fold back on itself. Half the run each is the exact bound; this
sits inside it so that even the shortest runs keep a real straight between their
two corners. Without that margin the north-west block's ten-metre runs were
consumed entirely by their own fillets and the lane became a rounded polygon
that cut twenty-three metres out of a sixty-metre block -- still on the
carriageway, and still visibly a car driving diagonally across every junction."""

ROAD_RIBBON_BASE = 0.86
ROAD_RIBBON_THICKNESS = 0.12
CLASS_DROP = {"arterial": 0.0, "collector": 0.008, "local": 0.016, "service": 0.012}
FOUNDING_SPUR_TOP = 0.96
FOUNDING_RING_RISE = 0.61
"""The heights the LOCKED builders actually draw road surfaces at.

A vehicle drives on the ROAD MESH, and the road mesh is not on the ground. Every
street in this city is a flat ribbon at a declared elevation: the production
street builder lays each class at ``ROAD_RIBBON_BASE`` minus a per-class hair
and extrudes it ``ROAD_RIBBON_THICKNESS`` upward, the founding avenues sit at
the same base, the founding spurs a centimetre lower and a millimetre thinner,
and a founding ring arc rides its district's plate at ``elevation + 0.61``.

Using the city's GROUND model here instead would have put vehicles up to forty
centimetres below their own carriageway wherever a street crosses a terrain
step -- the ground is stepped and the roads deliberately are not. These
constants are replicated from the locked builders and PINNED against the real
Blender meshes by the structural suite, exactly as the Phase 18 presence layer
pins the founding plate heights it stands people on."""


def road_surface_level(run: dict, master_spec: dict) -> float:
    """The height of the road surface one run is driven on."""
    segment = run["segment"]
    if segment.startswith("ring_"):
        district = master_spec["districts"].get(segment.removeprefix("ring_"))
        if district is None:
            raise VehicleLaneError(f"{segment} names a district the master scene does not define")
        return float(district["elevation"]) + FOUNDING_RING_RISE
    if segment.startswith("spur_"):
        return FOUNDING_SPUR_TOP
    if segment.startswith("avenue_"):
        return ROAD_RIBBON_BASE + ROAD_RIBBON_THICKNESS
    drop = CLASS_DROP.get(run["class"])
    if drop is None:
        raise VehicleLaneError(f"unknown road class {run['class']!r}")
    return ROAD_RIBBON_BASE - drop + ROAD_RIBBON_THICKNESS


class VehicleLaneError(ValueError):
    """A vehicle lane network contract violation.

    Raised when the network cannot be built coherently -- an unknown road
    class, a circuit that cannot be filleted, a lane that leaves its
    carriageway. Always a refusal, never a repair.
    """


# ---------------------------------------------------------------------------
# Pure polyline geometry
# ---------------------------------------------------------------------------


def polyline_length(path: list) -> float:
    """Total length of a polyline, measured in the ground plane.

    Deliberately 2D even for a lifted lane: a road's height changes by
    centimetres over metres, so counting the ramp would add a few millimetres
    of phantom travel to a circuit and put the vehicle's speed, its wheel
    rotation and its loop closure very slightly out of step with each other.
    """
    return math.fsum(
        math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:], strict=False)
    )


def _point_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Shortest distance from a point to one finite segment."""
    dx, dy = bx - ax, by - ay
    span = dx * dx + dy * dy
    if span <= 0.0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / span))
    return math.hypot(px - (ax + dx * t), py - (ay + dy * t))


def distance_to_polyline(x: float, y: float, path: list[tuple[float, float]]) -> float:
    """Shortest distance from a point to a polyline."""
    best = math.inf
    for a, b in zip(path, path[1:], strict=False):
        best = min(best, _point_segment(x, y, a[0], a[1], b[0], b[1]))
    return best


def _unit(ax: float, ay: float, bx: float, by: float) -> tuple[float, float]:
    """The unit direction from one point to another."""
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length <= 1.0e-12:
        raise VehicleLaneError("a zero-length leg has no direction")
    return dx / length, dy / length


def _wrap_angle(angle: float) -> float:
    """Normalise an angle into (-pi, pi] so headings compare exactly."""
    wrapped = math.fmod(angle + math.pi, 2.0 * math.pi)
    if wrapped <= 0.0:
        wrapped += 2.0 * math.pi
    return wrapped - math.pi


def offset_polyline(path: list[tuple[float, float]], offset: float) -> list[tuple[float, float]]:
    """Offset an open polyline to its RIGHT by a fixed distance.

    Right of travel, so a right-hand-traffic lane is a positive offset. Interior
    vertices use a mitre along the bisector, scaled by ``1 / cos(half-angle)``
    so the offset distance is held exactly on both legs rather than pinching at
    every bend. The scale is clamped, because a hairpin's mitre is unbounded and
    a lane is not allowed to shoot off into a building because a polyline
    doubled back on itself.
    """
    if offset == 0.0:
        return [(float(x), float(y)) for x, y in path]
    directions = [
        _unit(a[0], a[1], b[0], b[1]) for a, b in zip(path, path[1:], strict=False) if a != b
    ]
    if not directions:
        raise VehicleLaneError("cannot offset a degenerate polyline")
    points: list[tuple[float, float]] = []
    for index, (x, y) in enumerate(path):
        before = directions[max(0, min(index - 1, len(directions) - 1))]
        after = directions[max(0, min(index, len(directions) - 1))]
        bisector_x, bisector_y = before[0] + after[0], before[1] + after[1]
        span = math.hypot(bisector_x, bisector_y)
        if span <= 1.0e-9:
            normal = (after[1], -after[0])
            scale = 1.0
        else:
            bisector = (bisector_x / span, bisector_y / span)
            normal = (bisector[1], -bisector[0])
            cosine = before[0] * bisector[0] + before[1] * bisector[1]
            scale = 1.0 / max(0.35, abs(cosine))
        points.append((x + normal[0] * offset * scale, y + normal[1] * offset * scale))
    return points


def resample_polyline(path: list, step: float) -> list:
    """Walk a polyline at a fixed ground-plane step, keeping the final point.

    Dimension-agnostic on purpose: a lifted lane carries a height, and a
    resampler that dropped it would hand the applier a flat curve for a road
    that is not flat. Every component is interpolated; only x and y are
    measured.
    """
    if step <= 0.0:
        raise VehicleLaneError("resample step must be positive")
    out: list = [tuple(path[0])]
    carried = 0.0
    for a, b in zip(path, path[1:], strict=False):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if length <= 1.0e-12:
            continue
        travelled = step - carried
        while travelled < length:
            t = travelled / length
            out.append(tuple(low + (high - low) * t for low, high in zip(a, b, strict=True)))
            travelled += step
        carried = length - (travelled - step)
    if math.hypot(out[-1][0] - path[-1][0], out[-1][1] - path[-1][1]) > 1.0e-9:
        out.append(tuple(path[-1]))
    return out


def _line_intersection(
    p1: tuple[float, float],
    d1: tuple[float, float],
    p2: tuple[float, float],
    d2: tuple[float, float],
) -> tuple[float, float] | None:
    """Where two infinite lines meet, or ``None`` when they are parallel."""
    denominator = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(denominator) < 1.0e-9:
        return None
    t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / denominator
    return (p1[0] + d1[0] * t, p1[1] + d1[1] * t)


def _trim_end(path: list[tuple[float, float]], distance: float) -> list[tuple[float, float]]:
    """Shorten a polyline from its END by an arc length."""
    remaining = distance
    trimmed = list(path)
    while len(trimmed) >= 2 and remaining > 0.0:
        a, b = trimmed[-2], trimmed[-1]
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if length > remaining + 1.0e-9:
            t = (length - remaining) / length
            trimmed[-1] = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            return trimmed
        remaining -= length
        trimmed.pop()
    if len(trimmed) < 2:
        raise VehicleLaneError("a lane was trimmed away entirely")
    return trimmed


def _trim_start(path: list[tuple[float, float]], distance: float) -> list[tuple[float, float]]:
    """Shorten a polyline from its START by an arc length."""
    return list(reversed(_trim_end(list(reversed(path)), distance)))


def _arc(
    centre: tuple[float, float],
    radius: float,
    start_angle: float,
    sweep: float,
    step: float,
) -> list[tuple[float, float]]:
    """Sample a circular arc, excluding both endpoints."""
    count = max(2, int(math.ceil(abs(sweep) * radius / max(step, 1.0e-6))))
    return [
        (
            centre[0] + radius * math.cos(start_angle + sweep * index / count),
            centre[1] + radius * math.sin(start_angle + sweep * index / count),
        )
        for index in range(1, count)
    ]


# ---------------------------------------------------------------------------
# Lane policy
# ---------------------------------------------------------------------------


def carriageway_half_width(road_class: str) -> float:
    """Half the driveable carriageway of one road class."""
    width = ROAD_CLASS_WIDTHS.get(road_class)
    if width is None:
        raise VehicleLaneError(f"unknown road class {road_class!r}")
    return float(width) / 2.0


def lane_policy(road_class: str, mobility_spec: dict, vehicle_half_width: float) -> dict:
    """How many lanes one road class can carry, and at what offset.

    Returns ``{"policy", "offset", "reason"}``. The offset is measured from the
    carriageway centreline towards the driving side; a single lane sits on the
    centreline, because a centred vehicle is the only one a narrow street can
    hold without overhanging its own kerb.
    """
    lane = mobility_spec["vehicles"]["lane"]
    half = carriageway_half_width(road_class)
    need = vehicle_half_width + max(lane["edge_margin"], lane["centreline_margin"])
    if half / 2.0 >= need:
        return {
            "policy": "dual",
            "offset": half / 2.0,
            "reason": f"carriageway half {half:.2f} carries two {need:.2f} lanes",
        }
    if half >= vehicle_half_width + lane["edge_margin"]:
        return {
            "policy": "single",
            "offset": 0.0,
            "reason": (
                f"carriageway half {half:.2f} cannot hold two {need:.2f} lanes; "
                "the two-lane split is refused and one centred lane is offered"
            ),
        }
    return {
        "policy": "refused",
        "offset": 0.0,
        "reason": (
            f"carriageway half {half:.2f} cannot hold one "
            f"{vehicle_half_width + lane['edge_margin']:.2f} lane"
        ),
    }


def driving_sign(mobility_spec: dict) -> float:
    """+1 when the declared convention puts a lane on the travel-right side."""
    return 1.0 if mobility_spec["vehicles"]["driving_side"] == "right" else -1.0


# ---------------------------------------------------------------------------
# Runs: the street network cut at its own junctions
# ---------------------------------------------------------------------------


def _segment_node_ids(segment: dict) -> list[str]:
    """Every node id one segment references (endpoints then vias)."""
    ids = list(segment["via"])
    for end in (segment["end_a"], segment["end_b"]):
        if end is not None and "node" in end:
            ids.append(end["node"])
    return ids


def _station_of(node: dict, path: list[tuple[float, float]]) -> float:
    """The arc length at which a node sits on a polyline."""
    best_gap = math.inf
    best_station = 0.0
    travelled = 0.0
    for a, b in zip(path, path[1:], strict=False):
        dx, dy = b[0] - a[0], b[1] - a[1]
        span = dx * dx + dy * dy
        if span > 0.0:
            t = max(0.0, min(1.0, ((node["x"] - a[0]) * dx + (node["y"] - a[1]) * dy) / span))
            gap = math.hypot(node["x"] - (a[0] + dx * t), node["y"] - (a[1] + dy * t))
            if gap < best_gap:
                best_gap = gap
                best_station = travelled + math.sqrt(span) * t
        travelled += math.sqrt(span)
    return best_station


def _sample_at(path: list[tuple[float, float]], station: float) -> tuple[float, float]:
    """The point at one arc length along a polyline."""
    travelled = 0.0
    for a, b in zip(path, path[1:], strict=False):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if travelled + length >= station:
            t = (station - travelled) / length if length else 0.0
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        travelled += length
    return path[-1]


def _slice(path: list[tuple[float, float]], low: float, high: float) -> list[tuple[float, float]]:
    """The piece of a polyline between two arc lengths."""
    out = [_sample_at(path, low)]
    travelled = 0.0
    for a, b in zip(path, path[1:], strict=False):
        if low < travelled < high:
            out.append(a)
        travelled += math.hypot(b[0] - a[0], b[1] - a[1])
    if low < travelled < high:
        out.append(path[-1])
    out.append(_sample_at(path, high))
    cleaned = [out[0]]
    for point in out[1:]:
        if math.hypot(point[0] - cleaned[-1][0], point[1] - cleaned[-1][1]) > 1.0e-9:
            cleaned.append(point)
    return cleaned


def _ring_is_live(district_id: str, path: list, master_spec: dict, ground: dict) -> bool:
    """True when every point of a founding ring run still has pavement."""
    alive = ring_occupancy_paths(master_spec, ground, district_id)
    for x, y in path:
        if not any(distance_to_polyline(x, y, entry) <= RING_LIVE_TOLERANCE for entry in alive):
            return False
    return True


def build_runs(master_spec: dict, graph: dict, ground: dict) -> list[dict]:
    """Cut every street into RUNS between the junctions it already declares.

    A run is the atom of vehicle routing: a piece of one carriageway with a
    junction node at each end and nothing in between. Splitting here rather
    than routing over whole segments is what lets a circuit turn off a street
    at the junction Phase 16 actually built instead of at an invented point.

    Founding ring runs whose pavement the final composition buried are dropped;
    everything else keeps the class, and therefore the width, its segment
    declares.
    """
    runs: list[dict] = []
    for segment_id in sorted(graph["segments"]):
        segment = graph["segments"][segment_id]
        path = [(float(x), float(y)) for x, y in segment["path"]]
        total = polyline_length(path)
        marks = sorted(
            (_station_of(graph["nodes"][node_id], path), node_id)
            for node_id in sorted(set(_segment_node_ids(segment)))
        )
        pieces: list[tuple[str, str, list]] = []
        if segment["closed"]:
            if len(marks) < 2:
                continue
            for index in range(len(marks)):
                low, node_a = marks[index]
                high, node_b = marks[(index + 1) % len(marks)]
                if index == len(marks) - 1:
                    piece = _slice(path, low, total)
                    piece = piece + _slice(path, 0.0, marks[0][0])[1:]
                else:
                    piece = _slice(path, low, high)
                pieces.append((node_a, node_b, piece))
        else:
            stations: list[tuple[float, str | None]] = [(0.0, None), *marks, (total, None)]
            ordered: list[tuple[float, str | None]] = []
            for station, node_id in stations:
                if ordered and abs(ordered[-1][0] - station) < 0.2:
                    if node_id is not None:
                        ordered[-1] = (station, node_id)
                    continue
                ordered.append((station, node_id))
            # A street that ENDS somewhere still has a last stretch of road, and
            # that stretch is exactly the one an out-and-back route needs: the
            # turning bulb is at the far end of it. Naming the loose end after
            # its own termination keeps the run in the network with a node of
            # degree one, so a cycle can never walk through it and a shuttle can
            # still turn round on it. Dropping these was why the network offered
            # no turnarounds at all.
            terminal = {
                0: (
                    segment["end_a"]["node"]
                    if segment["end_a"] and "node" in segment["end_a"]
                    else f"T__{segment_id}__a"
                ),
                len(ordered) - 1: (
                    segment["end_b"]["node"]
                    if segment["end_b"] and "node" in segment["end_b"]
                    else f"T__{segment_id}__b"
                ),
            }
            for index in range(len(ordered) - 1):
                low, node_a = ordered[index]
                high, node_b = ordered[index + 1]
                node_a = node_a or terminal.get(index)
                node_b = node_b or terminal.get(index + 1)
                if node_a is None or node_b is None:
                    continue
                pieces.append((node_a, node_b, _slice(path, low, high)))
        district_id = segment_id[5:] if segment_id.startswith("ring_") else ""
        for index, (node_a, node_b, piece) in enumerate(pieces):
            if node_a == node_b or len(piece) < 2 or polyline_length(piece) < MIN_RUN_LENGTH:
                continue
            live = True
            if district_id:
                live = _ring_is_live(district_id, piece, master_spec, ground)
            runs.append(
                {
                    "run": f"{segment_id}#{index}",
                    "segment": segment_id,
                    "class": segment["class"],
                    "node_a": node_a,
                    "node_b": node_b,
                    "path": piece,
                    "length": round(polyline_length(piece), 6),
                    "paved": live,
                }
            )
    return runs


# ---------------------------------------------------------------------------
# The lane network
# ---------------------------------------------------------------------------


def _founding_obstruction(run: dict, footprints: list[dict]) -> str | None:
    """The founding building a run's carriageway passes through, if any.

    The test is the replayed FOOTPRINT rectangles against the run's own
    carriageway capsule -- the same authoritative shapes the Phase 15
    sampler is held to -- rather than the conservative obstacle discs of
    ``founding_building_lots``, which over-cover by design and would
    condemn runs whose pavement never touches a wall.
    """
    half = carriageway_half_width(run["class"])
    for lot in footprints:
        for entry in lot["parts"]:
            for a, b in zip(run["path"], run["path"][1:], strict=False):
                if shape_gap(entry["shape"], capsule_shape(a[0], a[1], b[0], b[1], half)) <= 0.0:
                    return lot["name"]
    return None


def build_lane_network(
    master_spec: dict, graph: dict, ground: dict, mobility_spec: dict, vehicle_half_width: float
) -> dict:
    """Every run the declared vehicle envelope may legally drive, and how.

    Returns ``{"runs": {...}, "refused": {...}, "summary": {...}}``. Each
    surviving run carries its policy, its lane offset, and the two junction
    nodes it connects; every refusal carries the reason it was refused, so a
    street that cannot take traffic says why rather than quietly vanishing.

    A run whose carriageway passes through founding architecture is refused
    outright. The placement contract is supposed to make that impossible;
    this guard is the lane network refusing to TRUST that it did, so a
    regression in the Phase 15 sampler can cost a street its traffic but
    can never route a vehicle through a building.
    """
    refused: dict[str, str] = {}
    lanes: dict[str, dict] = {}
    footprints = founding_building_footprints(master_spec)
    for run in build_runs(master_spec, graph, ground):
        if not run["paved"]:
            refused[run["run"]] = (
                "the founding ring sector here was buried by the final composition"
            )
            continue
        obstruction = _founding_obstruction(run, footprints)
        if obstruction is not None:
            refused[run["run"]] = (
                f"the carriageway here passes through founding architecture ({obstruction})"
            )
            continue
        policy = lane_policy(run["class"], mobility_spec, vehicle_half_width)
        if policy["policy"] == "refused":
            refused[run["run"]] = policy["reason"]
            continue
        lanes[run["run"]] = {**run, "policy": policy["policy"], "offset": policy["offset"]}
    by_policy: dict[str, int] = {}
    by_class: dict[str, int] = {}
    for entry in lanes.values():
        by_policy[entry["policy"]] = by_policy.get(entry["policy"], 0) + 1
        by_class[entry["class"]] = by_class.get(entry["class"], 0) + 1
    return {
        "runs": dict(sorted(lanes.items())),
        "refused": dict(sorted(refused.items())),
        "summary": {
            "runs_offered": len(lanes),
            "runs_refused": len(refused),
            "by_policy": dict(sorted(by_policy.items())),
            "by_class": dict(sorted(by_class.items())),
            "driving_side": mobility_spec["vehicles"]["driving_side"],
            "vehicle_half_width": round(vehicle_half_width, 6),
        },
    }


def run_lane(entry: dict, forward: bool, mobility_spec: dict) -> list[tuple[float, float]]:
    """The lane centreline of one run, travelled in one direction.

    The run's own polyline, reversed when the travel direction is, then offset
    towards the driving side. A dual run therefore produces two lanes on
    opposite sides of the carriageway and a single run produces the same
    centred line whichever way it is driven.
    """
    path = list(entry["path"]) if forward else list(reversed(entry["path"]))
    return offset_polyline(path, entry["offset"] * driving_sign(mobility_spec))


def lane_key(entry: dict, forward: bool) -> tuple[str, str]:
    """What a circuit CLAIMS when it drives one run.

    A dual run has two independent lanes, so the claim is per direction and two
    circuits may share the street in opposite directions -- ordinary traffic. A
    single run is the whole carriageway, so the claim ignores direction and the
    second circuit that wants it is refused.
    """
    if entry["policy"] == "single":
        return (entry["run"], "single")
    return (entry["run"], "forward" if forward else "reverse")


# ---------------------------------------------------------------------------
# Circuits
# ---------------------------------------------------------------------------


def enumerate_circuits(network: dict, max_road_length: float) -> list[dict]:
    """Every simple closed chain of runs shorter than a bound, deterministically.

    A depth-first walk from each node in sorted order, visiting runs in sorted
    order, admitting a cycle only when it returns to the node it started from
    and only from the smallest node id it contains. That last rule is what makes
    the enumeration a SET of cycles rather than one entry per rotation, and it
    is why the same network always produces the same circuits in the same order
    under any ``PYTHONHASHSEED``.

    This is deterministic route planning, not autonomous decision-making:
    nothing here chooses a destination, and the walk has no state beyond the
    chain it is currently extending.
    """
    adjacency: dict[str, list[dict]] = {}
    for entry in network["runs"].values():
        adjacency.setdefault(entry["node_a"], []).append(entry)
        adjacency.setdefault(entry["node_b"], []).append(entry)
    found: dict[tuple[str, ...], dict] = {}

    def walk(start: str, node: str, seen: frozenset, used: frozenset, chain: list, length: float):
        if length > max_road_length:
            return
        for entry in sorted(adjacency.get(node, ()), key=lambda item: item["run"]):
            if entry["run"] in used:
                continue
            other = entry["node_b"] if entry["node_a"] == node else entry["node_a"]
            total = length + entry["length"]
            if other == start and chain:
                key = tuple(sorted(item["run"] for item in [*chain, entry]))
                if key not in found or found[key]["road_length"] > total:
                    found[key] = {
                        "runs": [*chain, entry],
                        "road_length": total,
                        "start": start,
                    }
                continue
            if other in seen or other < start or total > max_road_length:
                continue
            walk(start, other, seen | {other}, used | {entry["run"]}, [*chain, entry], total)

    for node in sorted(adjacency):
        walk(node, node, frozenset({node}), frozenset(), [], 0.0)
    return [found[key] for key in sorted(found, key=lambda key: (found[key]["road_length"], key))]


def enumerate_out_and_back(
    network: dict, turnarounds: list[dict], max_chain_length: float
) -> list[dict]:
    """Every deterministic out-and-back the network could offer.

    A vehicle drives out along one lane, turns round where the city declares a
    street ENDS, comes back on the opposite lane, and turns round again where it
    started. That needs a TURNAROUND AT BOTH ENDS, which is the whole reason the
    family is rare: a junction is not a turnaround, so the chain has to run
    between two declared terminations that both carry two lanes.

    Only dual-lane runs are walked. A single-lane run cannot host this family at
    all -- coming back would send a vehicle against the direction the network
    declared for that lane, and there is no second lane to come back on.
    """
    adjacency: dict[str, list[dict]] = {}
    for entry in network["runs"].values():
        if entry["policy"] != "dual":
            continue
        adjacency.setdefault(entry["node_a"], []).append(entry)
        adjacency.setdefault(entry["node_b"], []).append(entry)
    ends = {entry["node"]: entry for entry in turnarounds}
    found: dict[tuple[str, ...], dict] = {}

    def walk(start: str, node: str, seen: frozenset, chain: list, length: float) -> None:
        if length > max_chain_length:
            return
        if node in ends and node != start and chain:
            key = tuple(item["run"] for item in chain)
            if key not in found or found[key]["chain_length"] > length:
                found[key] = {
                    "runs": list(chain),
                    "chain_length": length,
                    "from": start,
                    "to": node,
                }
        for entry in sorted(adjacency.get(node, ()), key=lambda item: item["run"]):
            if any(item["run"] == entry["run"] for item in chain):
                continue
            other = entry["node_b"] if entry["node_a"] == node else entry["node_a"]
            if other in seen:
                continue
            walk(start, other, seen | {other}, [*chain, entry], length + entry["length"])

    for node in sorted(ends):
        walk(node, node, frozenset({node}), [], 0.0)
    return [found[key] for key in sorted(found, key=lambda key: (found[key]["chain_length"], key))]


def out_and_back_line(
    ordered: list[tuple[dict, bool]],
    mobility_spec: dict,
    master_spec: dict,
    near: dict,
    far: dict,
    radius_target: float,
) -> list[tuple[float, float, float]]:
    """The whole closed path of one out-and-back route.

    Out along the chain, round at the far termination, back along the chain's
    OPPOSITE lanes, round again at the near one. Both turnarounds are real half
    circles at the declared radius rather than a lane-width pivot, and each one
    finishes outside the lane it is rejoining, so a tangent-continuous merge
    carries the vehicle back in over the first stretch of the return leg -- the
    manoeuvre a driver actually performs leaving a cul-de-sac.

    The result is still a CLOSED loop, which is what keeps the seamless cycle
    intact: an out-and-back is a different SHAPE of loop, never a weaker one.
    """
    step = mobility_spec["vehicles"]["lane"]["sample_step"]
    merge = max(3.0, radius_target * 2.2)
    outbound = circuit_line_3d(ordered, mobility_spec, master_spec, radius_target, closed=False)
    reverse = [(entry, not forward) for entry, forward in reversed(ordered)]
    inbound = circuit_line_3d(reverse, mobility_spec, master_spec, radius_target, closed=False)
    if polyline_length(outbound) <= 2.5 * merge:
        raise VehicleLaneError(
            "the chain is too short to merge out of its own turnarounds at this radius"
        )
    outbound = _trim_start(outbound, merge)
    inbound = _trim_start(inbound, merge)
    line: list[tuple[float, float, float]] = list(outbound)
    for marker, rejoin in ((far, inbound), (near, outbound)):
        heading = _unit(line[-2][0], line[-2][1], line[-1][0], line[-1][1])
        level = line[-1][2]
        turn = turnaround_lane(
            (marker["x"], marker["y"]), heading, marker["offset"], radius_target, step
        )
        for x, y in turn[:-1]:
            line.append((x, y, level))
        target = rejoin[0]
        outward = _unit(rejoin[0][0], rejoin[0][1], rejoin[1][0], rejoin[1][1])
        for x, y in _bezier(
            turn[-1], (-heading[0], -heading[1]), (target[0], target[1]), outward, merge * 0.6, step
        ):
            line.append((x, y, level))
        if rejoin is inbound:
            line.extend(inbound)
    if math.hypot(line[0][0] - line[-1][0], line[0][1] - line[-1][1]) > 1.0e-7:
        line.append(line[0])
    else:
        line[-1] = line[0]
    return line


def _orient_open(chain: list[dict], start: str) -> list[tuple[dict, bool]]:
    """Order an OPEN chain of runs head-to-tail from one of its ends."""
    remaining = list(chain)
    node = start
    ordered: list[tuple[dict, bool]] = []
    while remaining:
        for index, entry in enumerate(remaining):
            if entry["node_a"] == node:
                ordered.append((entry, True))
                node = entry["node_b"]
                remaining.pop(index)
                break
            if entry["node_b"] == node:
                ordered.append((entry, False))
                node = entry["node_a"]
                remaining.pop(index)
                break
        else:
            raise VehicleLaneError("an out-and-back chain is not connected end to end")
    return ordered


def _orient(chain: list[dict], start: str) -> list[tuple[dict, bool]]:
    """Order a closed chain of runs head-to-tail from one node."""
    remaining = list(chain)
    node = start
    ordered: list[tuple[dict, bool]] = []
    while remaining:
        for index, entry in enumerate(remaining):
            if entry["node_a"] == node:
                ordered.append((entry, True))
                node = entry["node_b"]
                remaining.pop(index)
                break
            if entry["node_b"] == node:
                ordered.append((entry, False))
                node = entry["node_a"]
                remaining.pop(index)
                break
        else:
            raise VehicleLaneError("a circuit chain does not close")
    if node != start:
        raise VehicleLaneError("a circuit chain does not return to its start")
    return ordered


def _retarget(
    path: list[tuple[float, float]], point: tuple[float, float], at_end: bool
) -> list[tuple[float, float]]:
    """Move one end of a polyline onto a point that lies along its own tangent.

    A fillet's tangent point can fall either SHORT of a lane's end (trim) or
    BEYOND it (extend, because the two lanes only meet where their lines cross,
    which may be past the last vertex either of them owns). Handling only the
    first case is how a corner ends up joined at a point nobody drove through.
    """
    working = list(path) if at_end else list(reversed(path))
    direction = _unit(working[-2][0], working[-2][1], working[-1][0], working[-1][1])
    reach = (point[0] - working[-1][0]) * direction[0] + (point[1] - working[-1][1]) * direction[1]
    if reach > 1.0e-9:
        working.append(point)
    elif reach < -1.0e-9:
        working = _trim_end(working, -reach)
        working[-1] = point
    else:
        working[-1] = point
    return working if at_end else list(reversed(working))


def _bezier(
    start: tuple[float, float],
    start_direction: tuple[float, float],
    end: tuple[float, float],
    end_direction: tuple[float, float],
    reach: float,
    step: float,
) -> list[tuple[float, float]]:
    """A tangent-continuous cubic connector between two lane ends."""
    control_a = (start[0] + start_direction[0] * reach, start[1] + start_direction[1] * reach)
    control_b = (end[0] - end_direction[0] * reach, end[1] - end_direction[1] * reach)
    span = math.hypot(end[0] - start[0], end[1] - start[1]) + reach
    count = max(3, int(math.ceil(span / step)))
    points: list[tuple[float, float]] = []
    for index in range(1, count):
        t = index / count
        u = 1.0 - t
        points.append(
            (
                u * u * u * start[0]
                + 3 * u * u * t * control_a[0]
                + 3 * u * t * t * control_b[0]
                + t * t * t * end[0],
                u * u * u * start[1]
                + 3 * u * u * t * control_a[1]
                + 3 * u * t * t * control_b[1]
                + t * t * t * end[1],
            )
        )
    return points


def circuit_lane(
    ordered: list[tuple[dict, bool]],
    mobility_spec: dict,
    radius_target: float | None = None,
    closed: bool = True,
) -> list[tuple[float, float]]:
    """The closed driven line of one circuit, joined at every junction.

    Each run contributes its own offset lane; where two lanes meet, a TANGENT
    FILLET ARC of the declared radius joins them. A fillet is tangent to both
    lanes, so the heading is continuous through the turn and a vehicle never
    rotates on the spot; it lies inside the wedge between the two lanes, so a
    turn cannot throw the lane outside the junction it is turning in; and its
    radius is a real turning circle rather than whatever a corner-cutting curve
    happened to produce.

    Where the two lanes run on ordinary the same bearing there is no corner to
    fillet, but there can still be a STEP: two road classes carry their lanes at
    different offsets, so an arterial lane meeting a collector lane is offset
    sideways even though neither turns. That step is joined by a
    tangent-continuous cubic -- a lane merge -- because leaving it unjoined
    would be a teleport of up to half a metre at every class change.

    Where the tangent length will not fit on a short run the radius is reduced,
    down to the declared floor. Below that the circuit is refused: a vehicle
    that cannot round a corner does not get to pretend it did.
    """
    lane = mobility_spec["vehicles"]["lane"]
    floor, step = lane["corner_radius_min"], lane["sample_step"]
    target = lane["corner_radius"] if radius_target is None else radius_target
    count = len(ordered)
    joined = [run_lane(entry, forward, mobility_spec) for entry, forward in ordered]
    connectors: list[list[tuple[float, float]]] = [[] for _ in range(count)]
    # An OPEN chain has one fewer junction than it has runs: its two loose ends
    # are somebody else's problem -- a turnaround's, for an out-and-back route.
    for index in range(count if closed else count - 1):
        first, second = joined[index], joined[(index + 1) % count]
        direction_in = _unit(first[-2][0], first[-2][1], first[-1][0], first[-1][1])
        direction_out = _unit(second[0][0], second[0][1], second[1][0], second[1][1])
        turn = _wrap_angle(
            math.atan2(direction_out[1], direction_out[0])
            - math.atan2(direction_in[1], direction_in[0])
        )
        gap = math.hypot(second[0][0] - first[-1][0], second[0][1] - first[-1][1])
        if abs(turn) < STRAIGHT_TOLERANCE:
            if gap > 1.0e-6:
                connectors[index] = _bezier(
                    first[-1], direction_in, second[0], direction_out, max(1.6, gap * 2.2), step
                )
            continue
        if abs(turn) > MAX_TURN_ANGLE:
            raise VehicleLaneError(
                f"a junction turns {math.degrees(abs(turn)):.0f} degrees, beyond the "
                f"{math.degrees(MAX_TURN_ANGLE):.0f} a lane may be filleted through"
            )
        corner = _line_intersection(first[-1], direction_in, second[0], direction_out)
        if corner is None:
            raise VehicleLaneError("two turning lanes have no intersection to fillet about")
        reach_in = (corner[0] - first[0][0]) * direction_in[0] + (
            corner[1] - first[0][1]
        ) * direction_in[1]
        reach_out = (second[-1][0] - corner[0]) * direction_out[0] + (
            second[-1][1] - corner[1]
        ) * direction_out[1]
        half_turn = math.tan(abs(turn) / 2.0)
        allowance_in = min(reach_in, polyline_length(first) * FILLET_RUN_SHARE)
        allowance_out = min(reach_out, polyline_length(second) * FILLET_RUN_SHARE)
        if allowance_in <= 0.0 or allowance_out <= 0.0:
            raise VehicleLaneError("a junction turn has no room on one of its lanes")
        radius = min(target, allowance_in / half_turn, allowance_out / half_turn)
        if radius < floor:
            raise VehicleLaneError(
                f"a junction fillet needs radius {radius:.2f}, below the declared "
                f"floor {floor}; the streets meeting here are too short to turn between"
            )
        tangent = radius * half_turn
        entry_point = (corner[0] - direction_in[0] * tangent, corner[1] - direction_in[1] * tangent)
        exit_point = (
            corner[0] + direction_out[0] * tangent,
            corner[1] + direction_out[1] * tangent,
        )
        side = 1.0 if turn > 0.0 else -1.0
        centre = (
            entry_point[0] - direction_in[1] * radius * side,
            entry_point[1] + direction_in[0] * radius * side,
        )
        start_angle = math.atan2(entry_point[1] - centre[1], entry_point[0] - centre[0])
        joined[index] = _retarget(first, entry_point, at_end=True)
        joined[(index + 1) % count] = _retarget(second, exit_point, at_end=False)
        connectors[index] = [*_arc(centre, radius, start_angle, turn, step)]
    line: list[tuple[float, float]] = []
    source: list[tuple[int, float]] = []
    for index in range(count):
        for point in joined[index]:
            if not line or math.hypot(point[0] - line[-1][0], point[1] - line[-1][1]) > 1.0e-7:
                line.append(point)
                source.append((index, 0.0))
        span = len(connectors[index]) + 1
        for position, point in enumerate(connectors[index], start=1):
            if not line or math.hypot(point[0] - line[-1][0], point[1] - line[-1][1]) > 1.0e-7:
                line.append(point)
                source.append((index, position / span))
    if closed:
        if math.hypot(line[0][0] - line[-1][0], line[0][1] - line[-1][1]) > 1.0e-7:
            line.append(line[0])
            source.append(source[0])
        else:
            line[-1] = line[0]
            source[-1] = source[0]
    return line, source


def corner_radius_ladder(mobility_spec: dict) -> tuple[float, ...]:
    """Every turning radius a circuit is allowed to try, widest first.

    A wide turn is the nicer manoeuvre and is tried first; a tighter one is what
    keeps a vehicle ON its carriageway where a wide turn would cut the corner
    off the road. Trying the ladder is not a relaxation -- every rung is still
    checked against the carriageway and against the loop contract, and a circuit
    that fails all of them is refused. Fixing one radius for the whole city
    instead simply moved the failures around: at one value the north-west block
    lost a direction, at another the meadow loop cut a corner into a verge.
    """
    lane = mobility_spec["vehicles"]["lane"]
    top, floor = lane["corner_radius"], lane["corner_radius_min"]
    steps = 7
    return tuple(round(top + (floor - top) * index / (steps - 1), 6) for index in range(steps))


def circuit_line_3d(
    ordered: list[tuple[dict, bool]],
    mobility_spec: dict,
    master_spec: dict,
    radius_target: float | None = None,
    closed: bool = True,
) -> list[tuple[float, float, float]]:
    """The driven line, lifted onto the road surfaces it actually crosses.

    Each run's points ride that run's own carriageway height; a junction
    connector RAMPS between the two, which is what keeps a vehicle leaving a
    founding ring arc for a production street from stepping seven centimetres
    into the air in one frame. The ramp is the only place the height changes,
    and it changes over metres rather than at a vertex.
    """
    line, source = circuit_lane(ordered, mobility_spec, radius_target, closed)
    levels = [road_surface_level(entry, master_spec) for entry, _forward in ordered]
    count = len(levels)
    return [
        (
            point[0],
            point[1],
            levels[index] + (levels[(index + 1) % count] - levels[index]) * blend,
        )
        for point, (index, blend) in zip(line, source, strict=True)
    ]


def _polyline_separation(first: list, second: list) -> float:
    """The closest two lanes ever come to each other, in the ground plane."""
    best = math.inf
    for point in first:
        for a, b in zip(second, second[1:], strict=False):
            best = min(best, _point_segment(point[0], point[1], a[0], a[1], b[0], b[1]))
    for point in second:
        for a, b in zip(first, first[1:], strict=False):
            best = min(best, _point_segment(point[0], point[1], a[0], a[1], b[0], b[1]))
    return best


def worst_body_gap(
    first: list[dict], second: list[dict], half_length: float, half_width: float
) -> float:
    """The closest two vehicle BODIES on two lanes could ever come, at any time.

    Centreline separation is not body separation. Two lanes two and a half
    metres apart look safe until both of them turn, because a turning vehicle
    presents its diagonal rather than its side; the corners of the north-west
    block brought two passing vans within six centimetres while their
    centrelines stayed comfortably apart.

    This places the LARGEST vehicle at every station of both lanes, oriented by
    each lane's own tangent, and reports the worst gap over every pairing. It is
    a claim about geometry alone -- no timing, no phase, no schedule -- so a pair
    of circuits that passes cannot collide however their traffic is arranged.
    """
    worst = math.inf
    boxes = [
        [
            {
                "kind": "rect",
                "x": station["x"],
                "y": station["y"],
                "half_w": half_length,
                "half_d": half_width,
                "rot": station["heading"],
            }
            for station in lane
        ]
        for lane in (first, second)
    ]
    reach = math.hypot(half_length, half_width) * 2.0
    for here in boxes[0]:
        for there in boxes[1]:
            if math.hypot(here["x"] - there["x"], here["y"] - there["y"]) > reach + 2.0:
                continue
            worst = min(worst, _rect_gap(here, there))
            if worst <= 0.0:
                return 0.0
    return worst


TURNAROUND_TERMINATIONS = (
    "cul_de_sac",
    "port_quay",
    "service_destination",
    "plaza_approach",
    "district_edge",
    "world_edge",
    "infrastructure_access",
)
"""Where a vehicle may believably turn around.

Every one of these is a place the LOCKED road graph already declares a street
ENDS -- a turning bulb, a quay apron, a plaza forecourt, a yard. Nothing here is
invented: a turnaround is offered only where Phase 16 built somewhere to turn.
A junction is deliberately absent from the list, because reversing in the middle
of a crossroads is not a manoeuvre, it is a hazard."""

TURNAROUND_PAD_RADIUS = {
    "cul_de_sac": 1.6,
    "port_quay": 0.8,
}
"""Extra radius beyond half the carriageway that each termination's pad carries.

Replicated from :func:`road_graph.junction_pads`, which is the one place the
city decides how big a turning bulb is. Terminations with no pad of their own
get none, and have to turn inside the carriageway or not at all."""


def legal_turnarounds(graph: dict, network: dict) -> list[dict]:
    """Every place the network could turn a vehicle round, with its room.

    A turnaround is offered only where a run that CARRIES TRAFFIC ends at a
    declared termination. A single-lane run is excluded on purpose: turning
    round on it would send a vehicle back along a centred lane whose direction
    the network has already declared, and there is no second lane to come back
    on.
    """
    offered: list[dict] = []
    for run_id in sorted(network["runs"]):
        entry = network["runs"][run_id]
        if entry["policy"] != "dual":
            continue
        segment = graph["segments"][entry["segment"]]
        for label, end, point in (
            ("end_a", segment["end_a"], segment["path"][0]),
            ("end_b", segment["end_b"], segment["path"][-1]),
        ):
            if end is None or "termination" not in end:
                continue
            if end["termination"] not in TURNAROUND_TERMINATIONS:
                continue
            own = entry["path"][0] if label == "end_a" else entry["path"][-1]
            if math.hypot(own[0] - point[0], own[1] - point[1]) > 1.0e-6:
                continue
            node = entry["node_a"] if label == "end_a" else entry["node_b"]
            offered.append(
                {
                    "run": run_id,
                    "node": node,
                    "end": label,
                    "termination": end["termination"],
                    "x": float(point[0]),
                    "y": float(point[1]),
                    "pad": carriageway_half_width(entry["class"])
                    + TURNAROUND_PAD_RADIUS.get(end["termination"], 0.0),
                    "class": entry["class"],
                    "offset": entry["offset"],
                }
            )
    return offered


def turnaround_lane(
    point: tuple[float, float],
    arriving: tuple[float, float],
    offset: float,
    radius: float,
    step: float,
) -> list[tuple[float, float]]:
    """The half circle a vehicle traces to reverse direction at a street's end.

    A HALF CIRCLE is the only single arc that reverses a heading, and it
    displaces the vehicle sideways by exactly twice its own radius -- so a turn
    wide enough to be believable inevitably finishes WIDER than the lane it is
    rejoining, out in the turning bulb the city built for it. Rejoining is the
    caller's job.

    Turning at the lane's own offset instead would close the arithmetic with a
    1.3m turning circle, which is mechanically absurd.
    """
    right = (arriving[1], -arriving[0])
    entry = (point[0] + right[0] * offset, point[1] + right[1] * offset)
    centre = (entry[0] - right[0] * radius, entry[1] - right[1] * radius)
    start_angle = math.atan2(entry[1] - centre[1], entry[0] - centre[0])
    sweep = -math.pi if offset >= 0.0 else math.pi
    exit_point = (
        entry[0] - right[0] * 2.0 * radius,
        entry[1] - right[1] * 2.0 * radius,
    )
    return [entry, *_arc(centre, radius, start_angle, sweep, step), exit_point]


def drivable_envelope(graph: dict) -> dict:
    """Every piece of ground a vehicle body is allowed to stand on.

    The union of every carriageway in the city and every junction pad the road
    network implies. Deliberately the WHOLE network rather than the circuit's
    own runs: a lane rounding a corner legitimately reaches across the street
    it is turning into, and a validator that only knew about the circuit would
    report that as leaving the road.
    """
    capsules = [
        {
            "path": [(float(x), float(y)) for x, y in segment["path"]],
            "half": carriageway_half_width(segment["class"]),
        }
        for segment in graph["segments"].values()
    ]
    pads = [
        {"x": float(pad["x"]), "y": float(pad["y"]), "r": float(pad["r"])}
        for pad in junction_pads(graph)
    ]
    return {"capsules": capsules, "pads": pads}


def on_carriageway(x: float, y: float, envelope: dict) -> bool:
    """True when a point stands on carriageway or on a junction pad."""
    for capsule in envelope["capsules"]:
        if distance_to_polyline(x, y, capsule["path"]) <= capsule["half"]:
            return True
    return any(math.hypot(x - pad["x"], y - pad["y"]) <= pad["r"] for pad in envelope["pads"])


def lane_stations(line: list, step: float) -> list[dict]:
    """Walk a closed lane at a fixed step, publishing position and heading.

    The heading is the lane's own tangent, so a vehicle placed on a station is
    oriented by the road rather than by anything it decided.
    """
    resampled = resample_polyline(line, step)
    stations: list[dict] = []
    travelled = 0.0
    for index, point in enumerate(resampled):
        following = resampled[(index + 1) % len(resampled)]
        previous = resampled[index - 1]
        if math.hypot(following[0] - point[0], following[1] - point[1]) > 1.0e-9:
            heading = math.atan2(following[1] - point[1], following[0] - point[0])
        else:
            heading = math.atan2(point[1] - previous[1], point[0] - previous[0])
        stations.append(
            {
                "s": travelled,
                "x": point[0],
                "y": point[1],
                "z": point[2] if len(point) > 2 else 0.0,
                "heading": heading,
            }
        )
        travelled += math.hypot(following[0] - point[0], following[1] - point[1])
    return stations


REGION_BOUNDS = (("west", -80.0, -20.0), ("centre", -20.0, 20.0), ("east", 20.0, 80.0))
REGION_ROWS = (("south", -80.0, -20.0), ("middle", -20.0, 20.0), ("north", 20.0, 80.0))
"""A coarse nine-box grid over the diorama, for reporting WHERE traffic is.

Deliberately coarse and deliberately fixed. The point is not to classify the
city finely, it is to make a sentence like "all the traffic is in one corner"
either true or false in a way a reviewer can check."""


def region_of(x: float, y: float) -> str:
    """Which box of the nine-box grid a point falls in."""
    column = next(
        (name for name, low, high in REGION_BOUNDS if low <= x < high), "west" if x < 0 else "east"
    )
    row = next(
        (name for name, low, high in REGION_ROWS if low <= y < high), "south" if y < 0 else "north"
    )
    return f"{row}-{column}"


def route_centroid(runs: list[dict], network: dict) -> tuple[float, float]:
    """The centre of the roads one route walks, whether or not it was built.

    Taken from the RUNS rather than from a built lane, so a route rejected
    before its lane existed can still say where in the city it would have been.
    Without that, a rejection report can only say a route failed, never where.
    """
    points = [
        point
        for item in runs
        for point in network["runs"][item["run"] if isinstance(item, dict) else item]["path"]
    ]
    return (
        math.fsum(point[0] for point in points) / len(points),
        math.fsum(point[1] for point in points) / len(points),
    )


def route_coverage(
    circuits: list[dict], network: dict, candidates: list[dict], rejected: dict
) -> dict:
    """What the accepted routes actually cover, measured rather than claimed.

    Geographic spread is a PRESENTATION objective, and an objective nobody
    measures is an objective nobody meets. This reports how far traffic reaches,
    which road segments carry it and which do not, and how far apart the active
    clusters sit -- so "the city feels alive" can be argued from numbers instead
    of from a camera pointed at the busy corner.
    """
    active_runs = {item["run"] for circuit in circuits for item in circuit["runs"]}
    active_segments = sorted({network["runs"][run]["segment"] for run in active_runs})
    every_segment = sorted({entry["segment"] for entry in network["runs"].values()})
    centroids = []
    xs: list[float] = []
    ys: list[float] = []
    for circuit in circuits:
        points = circuit["line"]
        centre = (
            math.fsum(point[0] for point in points) / len(points),
            math.fsum(point[1] for point in points) / len(points),
        )
        centroids.append(
            {
                "route": circuit.get("circuit", circuit["circuit_key"]),
                "family": circuit["family"],
                "centroid": [round(centre[0], 3), round(centre[1], 3)],
            }
        )
        xs.extend(point[0] for point in points)
        ys.extend(point[1] for point in points)
    separations = [
        round(math.dist(first["centroid"], second["centroid"]), 3)
        for index, first in enumerate(centroids)
        for second in centroids[index + 1 :]
    ]
    accepted_keys = {circuit["circuit_key"] for circuit in circuits}
    regions: dict[str, dict] = {}
    for entry in candidates:
        key = region_of(*route_centroid(entry["runs"], network))
        record = regions.setdefault(key, {"offered": 0, "accepted": 0, "reasons": []})
        record["offered"] += 1
        if entry["circuit_key"] in accepted_keys:
            record["accepted"] += 1
        elif entry["circuit_key"] in rejected and len(record["reasons"]) < 3:
            record["reasons"].append(f"{entry['circuit_key']}: {rejected[entry['circuit_key']]}")
    for key in sorted(regions):
        regions[key]["reasons"] = sorted(regions[key]["reasons"])
    return {
        "routes": len(circuits),
        "centroids": centroids,
        "regions": dict(sorted(regions.items())),
        "regions_with_traffic": sorted(key for key, value in regions.items() if value["accepted"]),
        "regions_offered_but_unusable": sorted(
            key for key, value in regions.items() if value["offered"] and not value["accepted"]
        ),
        "min_centroid_separation": min(separations) if separations else 0.0,
        "max_centroid_separation": max(separations) if separations else 0.0,
        "traffic_extent_x": [round(min(xs), 2), round(max(xs), 2)] if xs else [0.0, 0.0],
        "traffic_extent_y": [round(min(ys), 2), round(max(ys), 2)] if ys else [0.0, 0.0],
        "traffic_extent_area": round((max(xs) - min(xs)) * (max(ys) - min(ys)), 2) if xs else 0.0,
        "runs_carrying_traffic": sorted(active_runs),
        "segments_carrying_traffic": active_segments,
        "segments_without_traffic": [
            segment for segment in every_segment if segment not in set(active_segments)
        ],
        "segment_coverage": round(len(active_segments) / max(1, len(every_segment)), 4),
    }


def _spread_score(chosen: list[dict]) -> tuple:
    """A deterministic, comparable measure of how spread a route set is.

    The smallest gap between any two route centroids comes first, because a set
    whose routes sit on top of each other is exactly the failure this objective
    exists to avoid; the area traffic reaches breaks the ties. Both are read off
    the ACCEPTED lanes, so a route cannot score by claiming territory it never
    drives.
    """
    if not chosen:
        return (0.0, 0.0)
    centres = []
    xs: list[float] = []
    ys: list[float] = []
    for circuit in chosen:
        points = circuit["line"]
        centres.append(
            (
                math.fsum(point[0] for point in points) / len(points),
                math.fsum(point[1] for point in points) / len(points),
            )
        )
        xs.extend(point[0] for point in points)
        ys.extend(point[1] for point in points)
    gaps = [
        math.dist(first, second)
        for index, first in enumerate(centres)
        for second in centres[index + 1 :]
    ]
    area = (max(xs) - min(xs)) * (max(ys) - min(ys))
    return (round(min(gaps), 6) if gaps else 0.0, round(area, 6))


def plan_vehicle_lanes(
    master_spec: dict,
    graph: dict,
    ground: dict,
    mobility_spec: dict,
    vehicle_half_width: float,
    timeline: dict,
    *,
    prefer_open_routes: bool = False,
) -> dict:
    """The complete vehicle lane network and the routes it can carry.

    TWO route families are offered, not one. Closed CIRCUITS come from the
    network's own cycles; OUT-AND-BACK routes run between two declared
    terminations and turn round in the bulbs the city built for turning. Both
    are measured, both are filtered by the one constraint the loop contract
    leaves -- a route must be exactly as long as a legal speed can cover in one
    cycle -- and both compete on equal terms.

    Selection is an EXACT search over sets of mutually compatible routes. It
    reaches the canonical vehicle target first, because that is a hard
    requirement; among every set that reaches it, it then maximises GEOGRAPHIC
    SPREAD, because a technically valid traffic system that animates one corner
    of the city is not a daily-life result. Ties break on route keys, so the
    answer never depends on ordering.

    ``prefer_open_routes`` is a V2-only selection preference, defaulting to
    ``False`` and a strict no-op when ``False`` -- the score tuple, and therefore
    the selected set, is byte-for-byte today's. When ``True`` the exact search
    inserts one term into the score, immediately after the capacity term, that
    prefers any set of routes containing an out-and-back (``direction ==
    "shuttle"``) among sets reaching the same capacity, so the open family can
    actually win the selection instead of always losing the spread comparison.
    The v1 call site never passes it, so v1 output is unchanged by construction.
    """
    network = build_lane_network(master_spec, graph, ground, mobility_spec, vehicle_half_width)
    longest = vehicle_kit_longest()
    low, high = vehicle_route_length_bounds(mobility_spec, timeline)
    envelope = drivable_envelope(graph)
    pitch = mobility_spec["vehicles"]["slot_pitch"]
    step = mobility_spec["vehicles"]["lane"]["sample_step"]
    target = int(mobility_spec["vehicles"]["target_count"])
    turnarounds = legal_turnarounds(graph, network)

    candidates: list[dict] = []
    attempted: list[dict] = []
    rejected: dict[str, str] = {}
    offered = {"circuit": 0, "out_and_back": 0}

    def consider(identity: str, direction: str, family: str, build, runs, claims) -> None:
        """Try one route down the corner-radius ladder and keep it if it holds."""
        label = f"{identity}/{direction}"
        offered[family] += 1
        # Recorded BEFORE the route is built, so a route that never built still
        # says where in the city it would have been. Reporting regions only for
        # routes that succeeded would report that every region works.
        attempted.append({"circuit_key": label, "family": family, "runs": runs})
        reason = "no corner radius was tried"
        for radius in corner_radius_ladder(mobility_spec):
            try:
                line = build(radius)
            except VehicleLaneError as error:
                reason = str(error)
                continue
            length = polyline_length(line)
            if not low <= length <= high:
                reason = (
                    f"lane length {length:.2f} is outside the {low:.1f}-{high:.1f} band a "
                    f"{mobility_spec['vehicles']['speed']['min']}-"
                    f"{mobility_spec['vehicles']['speed']['max']} m/s vehicle can close in "
                    "one cycle"
                )
                continue
            stations = lane_stations(line, step)
            outside = [
                station
                for station in stations
                if not on_carriageway(station["x"], station["y"], envelope)
            ]
            if outside:
                reason = (
                    f"{len(outside)} lane station(s) leave the carriageway, the first at "
                    f"({outside[0]['x']:.2f}, {outside[0]['y']:.2f})"
                )
                continue
            candidates.append(
                {
                    "identity": identity,
                    "direction": direction,
                    "family": family,
                    "circuit_key": label,
                    "corner_radius": radius,
                    "runs": runs,
                    "claims": claims,
                    "line": line,
                    "length": round(length, 6),
                    "speed": round(length / float(timeline["vehicle_cycle_seconds"]), 6),
                    "capacity": int(length // pitch),
                    "stations": stations,
                }
            )
            return
        rejected[label] = reason

    for circuit in enumerate_circuits(network, high * 1.35):
        forward_order = _orient(circuit["runs"], circuit["start"])
        identity = "+".join(sorted(entry["run"] for entry in circuit["runs"]))
        for direction, label in ((True, "cw"), (False, "ccw")):
            ordered = (
                forward_order
                if direction
                else [(entry, not forward) for entry, forward in reversed(forward_order)]
            )
            consider(
                identity,
                label,
                "circuit",
                lambda radius, chain=ordered: circuit_line_3d(
                    chain, mobility_spec, master_spec, radius
                ),
                [{"run": entry["run"], "forward": forward} for entry, forward in ordered],
                sorted(lane_key(entry, forward) for entry, forward in ordered),
            )

    by_node = {entry["node"]: entry for entry in turnarounds}
    for chain in enumerate_out_and_back(network, turnarounds, high * 0.6):
        ordered = _orient_open(chain["runs"], chain["from"])
        identity = "shuttle:" + "+".join(sorted(entry["run"] for entry in chain["runs"]))
        # An out-and-back uses BOTH lanes of every run it walks, so it claims
        # both. Nothing else may share those streets with it, which is the
        # honest cost of a route that comes back the way it went.
        claims = sorted(
            {lane_key(entry, True) for entry, _forward in ordered}
            | {lane_key(entry, False) for entry, _forward in ordered}
        )
        near, far = by_node[chain["from"]], by_node[chain["to"]]
        consider(
            identity,
            "shuttle",
            "out_and_back",
            lambda radius, path=ordered, a=near, b=far: out_and_back_line(
                path, mobility_spec, master_spec, a, b, radius
            ),
            [{"run": entry["run"], "forward": forward} for entry, forward in ordered],
            claims,
        )

    floor = mobility_spec["vehicles"]["body_clearance"]
    longest_half = longest / 2.0
    coarse = math.hypot(longest_half, vehicle_half_width) * 2.0 + floor + 2.0
    for entry in candidates:
        if entry["capacity"] < 1:
            rejected[entry["circuit_key"]] = (
                f"lane length {entry['length']:.2f} cannot hold one vehicle at the declared "
                f"slot pitch {pitch}"
            )
    viable = sorted(
        (entry for entry in candidates if entry["capacity"] >= 1),
        key=lambda entry: entry["circuit_key"],
    )

    reasons: dict[tuple[int, int], str] = {}
    compatible = [0] * len(viable)
    for first in range(len(viable)):
        for second in range(first + 1, len(viable)):
            shared = sorted(
                str(key)
                for key in {tuple(k) for k in viable[first]["claims"]}
                & {tuple(k) for k in viable[second]["claims"]}
            )
            if shared:
                reasons[(first, second)] = f"they share lane(s) {shared}"
                continue
            if _polyline_separation(viable[first]["line"], viable[second]["line"]) > coarse:
                compatible[first] |= 1 << second
                compatible[second] |= 1 << first
                continue
            gap = worst_body_gap(
                viable[first]["stations"],
                viable[second]["stations"],
                longest_half,
                vehicle_half_width,
            )
            if gap < floor:
                reasons[(first, second)] = (
                    f"the largest vehicle on each lane would pass within {gap:.3f}m, inside "
                    f"the declared {floor:.2f}m body clearance"
                )
                continue
            compatible[first] |= 1 << second
            compatible[second] |= 1 << first

    best: dict = {"score": None, "keys": None, "mask": 0, "capacity": -1}

    def search(index: int, mask: int, allowed: int, capacity: int) -> None:
        remaining = sum(
            viable[bit]["capacity"] for bit in range(index, len(viable)) if allowed >> bit & 1
        )
        if best["capacity"] >= target and capacity + remaining < target:
            return
        if index == len(viable):
            chosen = [viable[bit] for bit in range(len(viable)) if mask >> bit & 1]
            keys = tuple(entry["circuit_key"] for entry in chosen)
            if prefer_open_routes:
                # V2-only selection preference: among sets that reach the same
                # capacity, prefer one that contains an open out-and-back route.
                # The check mirrors mobility_traffic_v2.is_open_route
                # (direction == "shuttle") inline to avoid a circular import.
                score = (
                    min(capacity, target),
                    (1 if any(entry.get("direction") == "shuttle" for entry in chosen) else 0),
                    *_spread_score(chosen),
                    capacity,
                )
            else:
                score = (min(capacity, target), *_spread_score(chosen), capacity)
            if (
                best["score"] is None
                or score > best["score"]
                or (score == best["score"] and keys < best["keys"])
            ):
                best.update({"score": score, "keys": keys, "mask": mask, "capacity": capacity})
            return
        if allowed >> index & 1:
            search(
                index + 1,
                mask | (1 << index),
                (allowed & compatible[index]) | (1 << index),
                capacity + viable[index]["capacity"],
            )
        search(index + 1, mask, allowed & ~(1 << index), capacity)

    search(0, 0, (1 << len(viable)) - 1, 0)
    chosen_mask = best["mask"]
    selected = [entry for bit, entry in enumerate(viable) if chosen_mask >> bit & 1]
    for bit, entry in enumerate(viable):
        if chosen_mask >> bit & 1:
            continue
        blockers = sorted(
            reasons[(min(bit, other), max(bit, other))]
            for other in range(len(viable))
            if chosen_mask >> other & 1 and (min(bit, other), max(bit, other)) in reasons
        )
        rejected[entry["circuit_key"]] = (
            blockers[0]
            if blockers
            else "another set of routes reaches the target and spreads traffic further"
        )

    for index, candidate in enumerate(
        sorted(selected, key=lambda item: (-item["capacity"], item["circuit_key"])), start=1
    ):
        candidate["circuit"] = f"circuit_{index:02d}"
    circuits = sorted(selected, key=lambda item: item["circuit"])
    coverage = route_coverage(circuits, network, attempted, rejected)
    for entry in circuits:
        entry.pop("stations", None)
    return {
        "network": network,
        "circuits": circuits,
        "rejected": dict(sorted(rejected.items())),
        "turnarounds": turnarounds,
        "coverage": coverage,
        "summary": {
            "circuits_selected": len(circuits),
            "circuits_rejected": len(rejected),
            "candidates_offered": dict(sorted(offered.items())),
            "candidates_viable": len(viable),
            "candidates_attempted": len(attempted),
            "capacity": sum(entry["capacity"] for entry in circuits),
            "length_band": [round(low, 4), round(high, 4)],
            "slot_pitch": pitch,
            "legal_turnarounds": len(turnarounds),
            "by_family": {
                family: sum(1 for entry in circuits if entry["family"] == family)
                for family in sorted(offered)
            },
            "by_circuit": {
                entry["circuit"]: {
                    "family": entry["family"],
                    "length": entry["length"],
                    "speed": entry["speed"],
                    "capacity": entry["capacity"],
                    "direction": entry["direction"],
                    "corner_radius": entry["corner_radius"],
                    "runs": [item["run"] for item in entry["runs"]],
                }
                for entry in circuits
            },
        },
    }
