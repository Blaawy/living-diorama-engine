"""How an existing Phase 18 proxy walks, and what walking does to its body.

Pure Python by design -- no ``bpy``. Two questions, and this module refuses to
answer any other:

    WHERE   which closed route a moving proxy walks, proven clear of the city
            by the same Phase 18 occupancy that proved it could stand there
    HOW     what its limbs do while it walks, as a deterministic deformation of
            the LOCKED Phase 18 body

    NO NEW PEOPLE ARE CREATED HERE.

Every walker is an EXISTING representative population proxy, chosen from the
Phase 18 plan by a stable draw. The population, the slots, the identities and
the anchors are Phase 18's and are never touched: this module adds a route and
a gait to a body that was already standing there, and a proxy that is not
selected keeps standing exactly where Phase 18 put it.

    A MOVING PROXY IS STILL A REPRESENTATIVE PROXY.

It has no destination, no home, no errand and no schedule, and there is nowhere
in a route such a thing could be recorded. A route is a closed loop around the
proxy's own anchor: it goes nowhere, on purpose, because going somewhere would
be a claim about a person the simulation does not model.

THE LOOP CONTRACT
-----------------
A route is a CLOSED loop and a walker travels it exactly once per cycle, so the
walker is back at its own anchor, with the heading it started with, on the last
frame. Nothing is corrected at the end; the shape of the route is what closes
it. The loop is a racetrack around a corridor -- out along one side, round a
half-turn, back along the other, round again -- so the heading is continuous
everywhere and a turnaround is an arc a body could really walk, never a
one-frame reversal.

GAIT IS TIED TO TRAVEL, NOT CHOSEN
----------------------------------
The number of gait cycles is the route length divided by the body's own stride,
rounded to a whole number so the walk closes with the loop; the leg swing is
then DERIVED from that effective stride and the body's real leg length, by
``stride = 4 * leg * sin(swing)``. A walker therefore cannot skate: the swing
that would make its feet cycle faster than it travels is not a setting anyone
can choose, it is a number the arithmetic refuses to produce.
"""

import hashlib
import json
import math

import figure_kit
from city_ground import ground_level_at
from mobility_spec import mobility_seed
from pedestrian_topology import (
    PLAZA_DECK_THICKNESS,
    PRESENCE_CLEARANCE,
    STEP_PROBES,
    STEP_TOLERANCE,
    founding_surfaces,
)
from production_spec import port_frame
from spatial_occupancy import circle, shape_gap
from vehicle_lane_network import (
    offset_polyline,
    polyline_length,
    resample_polyline,
)

PEDESTRIAN_MOBILITY_FORMAT = "living_diorama_pedestrian_mobility"

RING_SAMPLE_STEP = 0.25
"""How finely a plaza or park ring is sampled into a corridor polyline.

Fine enough that the polyline's chord error stays under a millimetre on the
tightest ring the city offers, so a walker on a small plaza ring is walking a
circle rather than a visible polygon."""

LATERAL_ORDER = ("inward", "outward")
"""Which side a route's return leg is tried on, in order.

Inward first: the ladder walks the side NEARER the carriageway -- and, on the
Golden Seal's forecourt, nearer the protected monument -- before the far one,
because that is the side every shipped route has always been built and
validated on; an earlier label called that side "outward" while the sign it
drove pointed inward. Outward is the fallback, and it is still validated
against the whole occupancy before it is accepted -- it is a second candidate,
not a relaxation. Preferring the genuinely outward side first would be a
deliberate route change across the whole city, reserved for a future
decision."""

TURN_RATE_MARGIN = 0.92
"""How much of the declared turn-rate ceiling a turnaround is designed to.

Sizing a half-turn to EXACTLY the ceiling puts the built arc on the boundary,
where the discrete measurement of the same arc lands a degree either side of it
and the route is refused by the very rule it was designed to satisfy. Eight per
cent of headroom is the difference between a policy and a coin toss."""

MIN_CORRIDOR_MARGIN = 0.5
"""How much corridor a route needs beyond its own excursion.

A route that used a corridor right to its last centimetre would be a route
whose turnaround sits on the end of the world. Refused instead."""


class PedestrianMobilityError(ValueError):
    """A pedestrian mobility contract violation.

    Raised when a route cannot be built or proven, when a walker's body cannot
    produce the stride its route needs, and when the plan and the Phase 18 plan
    disagree about who exists. Always a refusal, never a repair.
    """


# ---------------------------------------------------------------------------
# Corridors: the safe ground a route is drawn on
# ---------------------------------------------------------------------------


def _signed_offset(path: list[tuple[float, float]], x: float, y: float) -> tuple[float, float]:
    """How far, and on which side, a point sits from a polyline.

    Returns ``(offset, station)`` where a POSITIVE offset is to the polyline's
    right. The sign is what lets a frontage route know which pavement its
    walker is standing on, and therefore which way "away from the road" is.
    """
    best = (math.inf, 0.0, 0.0)
    travelled = 0.0
    for a, b in zip(path, path[1:], strict=False):
        dx, dy = b[0] - a[0], b[1] - a[1]
        span = math.hypot(dx, dy)
        if span <= 1.0e-12:
            continue
        t = max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / (span * span)))
        px, py = a[0] + dx * t, a[1] + dy * t
        gap = math.hypot(x - px, y - py)
        if gap < best[0]:
            # Positive is to the polyline's RIGHT, matching offset_polyline's
            # own convention. The cross product d x (P-A) is positive when P is
            # to the LEFT, so the sign is taken from its negation -- and getting
            # this backwards offsets a corridor to the far side of its own
            # street, which puts a walker's route twice its own distance away
            # from the anchor it is supposed to run through.
            side = (x - a[0]) * dy - (y - a[1]) * dx
            best = (gap, math.copysign(gap, side), travelled + span * t)
        travelled += span
    if not math.isfinite(best[0]):
        raise PedestrianMobilityError("a corridor polyline has no measurable geometry")
    return best[1], best[2]


def _ring_path(
    centre: tuple[float, float], radius: float, start_angle: float
) -> list[tuple[float, float]]:
    """A closed circle sampled into a corridor polyline, starting at an angle."""
    count = max(16, int(math.ceil(2.0 * math.pi * radius / RING_SAMPLE_STEP)))
    points = [
        (
            centre[0] + radius * math.cos(start_angle + 2.0 * math.pi * index / count),
            centre[1] + radius * math.sin(start_angle + 2.0 * math.pi * index / count),
        )
        for index in range(count)
    ]
    points.append(points[0])
    return points


def _plaza_centres(master_spec: dict, fabric_plan: dict) -> dict[str, tuple[float, float]]:
    """The centre every plaza-zone source rings around."""
    seal = master_spec["landmarks"]["golden_seal"]
    centres = {"golden_seal": (float(seal["location"][0]), float(seal["location"][1]))}
    for neighborhood_id, entry in sorted(fabric_plan["neighborhoods"].items()):
        plaza = entry["plaza"]
        if plaza is not None:
            centres[f"plaza_{neighborhood_id}"] = (
                float(plaza["center"][0]),
                float(plaza["center"][1]),
            )
    return centres


def route_corridor(
    proxy: dict, master_spec: dict, production_spec: dict, graph: dict, fabric_plan: dict
) -> dict:
    """The band of safe ground one proxy's route is allowed to be drawn on.

    Derived from the SAME geometry the Phase 18 topology sampled its standing
    candidates from -- a street's own polyline, a plaza's own centre, a park
    zone's own centre, the harbour's own quay line -- so a route can only ever
    run along ground the presence layer already understood. Nothing is
    hand-drawn to look like a pavement.

    Returns ``{"family", "path", "station", "closed", "lateral"}``: the corridor
    polyline through the proxy's anchor, the arc length at which the anchor
    sits, whether the corridor wraps, and a function-free description of which
    way "outward" points.
    """
    zone, source = proxy["zone"], proxy["source"]
    if zone == "frontage":
        segment = graph["segments"].get(source)
        if segment is None:
            raise PedestrianMobilityError(f"frontage proxy cites unknown street {source!r}")
        path = [(float(x), float(y)) for x, y in segment["path"]]
        if segment["closed"] and path[0] != path[-1]:
            path = [*path, path[0]]
        offset, station = _signed_offset(path, proxy["x"], proxy["y"])
        corridor = offset_polyline(path, offset)
        _offset, station = _signed_offset(corridor, proxy["x"], proxy["y"])
        return {
            "family": "corridor_loop",
            "path": corridor,
            "station": station,
            "closed": bool(segment["closed"]),
            "lateral": math.copysign(1.0, offset) if offset else 1.0,
            "anchor_offset": abs(offset),
        }
    if zone == "promenade":
        (port_x, port_y), (unit_x, unit_y), quay = port_frame(master_spec)
        reach = (proxy["x"] - port_x) * unit_x + (proxy["y"] - port_y) * unit_y
        base = (port_x + unit_x * reach, port_y + unit_y * reach)
        along = (-unit_y, unit_x)
        half = 40.0
        path = [
            (base[0] - along[0] * half, base[1] - along[1] * half),
            (base[0] + along[0] * half, base[1] + along[1] * half),
        ]
        _offset, station = _signed_offset(path, proxy["x"], proxy["y"])
        # The corridor runs along the quay, so its right-hand side is whichever
        # of landward and seaward the walk direction puts there. Outward for a
        # promenade must mean LANDWARD, away from the water, so the sign is
        # taken from the quay frame rather than from the polyline's handedness.
        seaward = along[0] * unit_y - along[1] * unit_x
        return {
            "family": "corridor_loop",
            "path": path,
            "station": station,
            "closed": False,
            "lateral": math.copysign(1.0, seaward) if seaward else 1.0,
            "anchor_offset": quay - reach,
        }
    if zone in ("plaza", "park"):
        if zone == "plaza":
            centre = _plaza_centres(master_spec, fabric_plan).get(source)
        else:
            park = production_spec.get("landscape", {}).get("park_zones", {}).get(source)
            centre = (
                (float(park["center"][0]), float(park["center"][1])) if park is not None else None
            )
        if centre is None:
            raise PedestrianMobilityError(f"{zone} proxy cites unknown source {source!r}")
        radius = math.hypot(proxy["x"] - centre[0], proxy["y"] - centre[1])
        if radius < MIN_CORRIDOR_MARGIN:
            raise PedestrianMobilityError(
                f"{proxy['slot']} stands {radius:.2f} from its {zone} centre, too close to "
                "ring around it"
            )
        start = math.atan2(proxy["y"] - centre[1], proxy["x"] - centre[0])
        path = _ring_path(centre, radius, start)
        return {
            "family": "ring_loop",
            "path": path,
            "station": 0.0,
            "closed": True,
            # A ring's right-hand side, walked anticlockwise, points at the
            # centre; outward is therefore the polyline's LEFT.
            "lateral": -1.0,
            "anchor_offset": radius,
            "centre": centre,
        }
    raise PedestrianMobilityError(f"proxy {proxy['slot']} is in unknown zone {proxy['zone']!r}")


def _slice_forward(
    path: list[tuple[float, float]], station: float, distance: float, closed: bool
) -> list[tuple[float, float]]:
    """Walk a corridor forward from an arc length, wrapping if it is closed."""
    total = polyline_length(path)
    if not closed and station + distance > total - 1.0e-9:
        raise PedestrianMobilityError("the corridor runs out before the excursion ends")
    if distance > total - 1.0e-9:
        raise PedestrianMobilityError("the excursion is longer than the whole corridor")
    points: list[tuple[float, float]] = []
    travelled = 0.0
    wanted_low, wanted_high = station, station + distance
    doubled = list(path) + (list(path[1:]) if closed else [])
    for a, b in zip(doubled, doubled[1:], strict=False):
        span = math.hypot(b[0] - a[0], b[1] - a[1])
        if span <= 1.0e-12:
            continue
        low, high = travelled, travelled + span
        if high >= wanted_low and low <= wanted_high:
            start = max(0.0, (wanted_low - low) / span)
            stop = min(1.0, (wanted_high - low) / span)
            for t in (start, stop):
                point = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                if (
                    not points
                    or math.hypot(point[0] - points[-1][0], point[1] - points[-1][1]) > 1.0e-9
                ):
                    points.append(point)
            if low <= wanted_high <= high:
                break
        travelled = high
    if len(points) < 2:
        raise PedestrianMobilityError("a corridor slice collapsed to a point")
    return points


def _semicircle(
    start: tuple[float, float],
    end: tuple[float, float],
    direction: tuple[float, float],
    step: float,
) -> list[tuple[float, float]]:
    """The half-turn joining two parallel legs, excluding both endpoints.

    A semicircle whose diameter is the gap between the legs is tangent to BOTH
    of them, which is the whole reason a turnaround is drawn this way: the
    heading rotates smoothly through 180 degrees and there is no frame on which
    a walker reverses.
    """
    centre = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
    radius = math.hypot(end[0] - start[0], end[1] - start[1]) / 2.0
    if radius <= 1.0e-9:
        return []
    begin = math.atan2(start[1] - centre[1], start[0] - centre[0])
    cross = direction[0] * (end[1] - start[1]) - direction[1] * (end[0] - start[0])
    sweep = math.pi if cross > 0.0 else -math.pi
    count = max(4, int(math.ceil(math.pi * radius / max(step, 1.0e-6))))
    return [
        (
            centre[0] + radius * math.cos(begin + sweep * index / count),
            centre[1] + radius * math.sin(begin + sweep * index / count),
        )
        for index in range(1, count)
    ]


def rotate_loop_to(loop: list, anchor: tuple[float, float]) -> list:
    """Re-enter a closed loop at the anchor, so a walk STARTS where it stands.

    Shifting the excursion back to use the pavement behind a walker moves the
    loop's first vertex off the anchor, but the anchor is still ON the loop --
    a closed track has no privileged beginning. Rotating the vertex list to
    start there restores the contract the directive asks for: a walker leaves
    its own Phase 18 anchor, walks, and arrives back at it.
    """
    points = [tuple(point) for point in loop]
    if math.dist(points[0], points[-1]) <= 1.0e-9:
        points = points[:-1]
    best_index, best_gap, best_point = 0, math.inf, points[0]
    for index in range(len(points)):
        a, b = points[index], points[(index + 1) % len(points)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        span = dx * dx + dy * dy
        t = (
            0.0
            if span <= 0.0
            else max(0.0, min(1.0, ((anchor[0] - a[0]) * dx + (anchor[1] - a[1]) * dy) / span))
        )
        point = (a[0] + dx * t, a[1] + dy * t)
        gap = math.dist(point, anchor)
        if gap < best_gap:
            best_index, best_gap, best_point = index, gap, point
    # Re-entered at the loop's OWN closest point to the anchor, never at the
    # anchor itself. A corridor is a mitred offset of a street, so it runs a few
    # centimetres wide of the anchor at a bend; splicing the anchor in as a
    # vertex would put a real kink in the walk there, and the turn-rate check
    # would refuse the route for a corner the geometry never had.
    rotated = [best_point, *points[best_index + 1 :], *points[: best_index + 1]]
    cleaned = [rotated[0]]
    for point in rotated[1:]:
        if math.dist(point, cleaned[-1]) > 1.0e-9:
            cleaned.append(point)
    if math.dist(cleaned[-1], best_point) > 1.0e-9:
        cleaned.append(best_point)
    else:
        cleaned[-1] = best_point
    return cleaned


def build_route_loop(
    corridor: dict,
    excursion: float,
    lateral: float,
    side: str,
    step: float,
    share: float = 0.0,
) -> list[tuple[float, float]]:
    """The closed racetrack one walker travels, starting at its own anchor.

    Out along the corridor for ``excursion``, a half-turn, back along the
    corridor offset sideways by ``lateral``, and a second half-turn onto the
    anchor. The anchor is a point ON the loop and the loop ends exactly there,
    which is the loop contract discharged by construction.
    """
    placed = shifted_corridor(corridor, excursion, share)
    outbound = _slice_forward(placed["path"], placed["station"], excursion, placed["closed"])
    # The corridor publishes ``lateral`` as the sign whose positive multiple
    # moves OUTWARD -- further from a street's carriageway, landward on the
    # promenade, away from a ring's centre -- so "outward" keeps that sign and
    # "inward" negates it.
    sign = placed["lateral"] * (1.0 if side == "outward" else -1.0)
    returning = list(reversed(offset_polyline(outbound, lateral * sign)))
    direction = (
        outbound[-1][0] - outbound[-2][0],
        outbound[-1][1] - outbound[-2][1],
    )
    far_turn = _semicircle(outbound[-1], returning[0], direction, step)
    back = (returning[-1][0] - returning[-2][0], returning[-1][1] - returning[-2][1])
    home_turn = _semicircle(returning[-1], outbound[0], back, step)
    loop = [*outbound, *far_turn, *returning, *home_turn, outbound[0]]
    cleaned = [loop[0]]
    for point in loop[1:]:
        if math.hypot(point[0] - cleaned[-1][0], point[1] - cleaned[-1][1]) > 1.0e-9:
            cleaned.append(point)
    if math.hypot(cleaned[0][0] - cleaned[-1][0], cleaned[0][1] - cleaned[-1][1]) > 1.0e-9:
        cleaned.append(cleaned[0])
    else:
        cleaned[-1] = cleaned[0]
    return cleaned


def solve_excursion(
    corridor: dict,
    target_length: float,
    lateral: float,
    side: str,
    step: float,
    bounds: tuple,
    share: float = 0.0,
) -> tuple[float, list[tuple[float, float]]]:
    """Find the excursion whose loop is exactly the length the speed demands.

    Loop length grows monotonically with excursion, so a bisection lands on the
    one excursion that closes the loop at the walker's own speed. Solving rather
    than choosing is what keeps speed, route length and gait one consistent set
    of numbers instead of three independent settings that happen to look right.
    """
    low, high = bounds
    if build_length(corridor, low, lateral, side, step, share) > target_length:
        raise PedestrianMobilityError(
            f"even the shortest permitted excursion ({low}) makes a loop longer than the "
            f"{target_length:.2f} this walker's speed can close"
        )
    if build_length(corridor, high, lateral, side, step, share) < target_length:
        raise PedestrianMobilityError(
            f"even the longest permitted excursion ({high}) makes a loop shorter than the "
            f"{target_length:.2f} this walker's speed needs"
        )
    for _step in range(60):
        middle = (low + high) / 2.0
        if build_length(corridor, middle, lateral, side, step, share) < target_length:
            low = middle
        else:
            high = middle
    excursion = (low + high) / 2.0
    return excursion, build_route_loop(corridor, excursion, lateral, side, step, share)


def build_length(
    corridor: dict, excursion: float, lateral: float, side: str, step: float, share: float = 0.0
) -> float:
    """The length of the loop one excursion would produce."""
    return polyline_length(build_route_loop(corridor, excursion, lateral, side, step, share))


def reversed_corridor(corridor: dict) -> dict:
    """The same corridor walked the other way.

    Reversing the polyline flips both the direction of travel and the meaning
    of "right", so the lateral sign flips with it and "outward" keeps pointing
    at the same side of the world. The anchor's station is measured again from
    the new start rather than subtracted, so a rounding error cannot creep in
    at the one point the loop has to close on.
    """
    path = list(reversed(corridor["path"]))
    total = polyline_length(path)
    return {
        **corridor,
        "path": path,
        "station": total - corridor["station"],
        "lateral": -corridor["lateral"],
    }


def shifted_corridor(corridor: dict, excursion: float, share: float) -> dict:
    """The same corridor with the anchor moved along the excursion.

    A racetrack that always started AT the anchor could only ever use the
    corridor AHEAD of a walker, so a proxy standing with open pavement behind it
    and a building in front had no route at all. This slides the outbound leg
    back by a share of its own length, which puts the anchor at the start, the
    middle or the far end of the walk. The anchor stays ON the loop in every
    case -- it is the same closed track, entered at a different point.

    A closed corridor wraps; an open one is clamped, so a shift can never ask
    for pavement before the start of a street.
    """
    if share <= 0.0:
        return corridor
    total = polyline_length(corridor["path"])
    station = corridor["station"] - excursion * share
    if corridor["closed"]:
        station = math.fmod(station, total)
        if station < 0.0:
            station += total
    else:
        station = min(max(station, 0.0), max(0.0, total - excursion - MIN_CORRIDOR_MARGIN))
    return {**corridor, "station": station}


def turn_lateral(speed: float, mobility_spec: dict) -> float:
    """How wide a turnaround this walking speed is allowed to be turned in.

    A half-turn around a track of width ``w`` is a circle of radius ``w / 2``,
    so a body travelling at ``speed`` rotates at ``2 * speed / w``. Inverting
    that against the declared ceiling gives the NARROWEST legal turnaround for
    a given pace -- and therefore the narrowest strip of pavement a walk of that
    pace can be laid on. A faster walker needs a wider turn; that is not a
    setting, it is the geometry of turning around.
    """
    route = mobility_spec["pedestrians"]["route"]
    needed = 2.0 * speed / (math.radians(route["max_turn_rate_deg_s"]) * TURN_RATE_MARGIN)
    return min(float(route["lateral_offset"]), needed)


def ring_circumference(corridor: dict) -> float:
    """The whole way round a ring corridor, or zero when it is not a ring."""
    if corridor["family"] != "ring_loop":
        return 0.0
    return polyline_length(corridor["path"])


def full_ring_loop(corridor: dict) -> list[tuple[float, float]]:
    """The entire ring, walked once, with no turnaround at all.

    The nicest route this phase can offer, and the city offers only a few: when
    a plaza or park ring is exactly as long as one cycle of walking, a body can
    simply stroll all the way round it. There is no half-turn to justify, the
    heading never reverses, and the loop closes because the ring does.
    """
    points = [tuple(point) for point in corridor["path"]]
    if math.dist(points[0], points[-1]) > 1.0e-9:
        points.append(points[0])
    else:
        points[-1] = points[0]
    return points


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


class PresenceIndex:
    """A grid index over the Phase 18 occupancy, for walking a whole route.

    Phase 18 tested one standing point per proxy; Phase 19 tests every
    centimetre of every candidate route for every proxy, which is four orders
    of magnitude more work against the same few hundred entries. The index
    buckets entries by the cell their envelope covers, so a sample only meets
    the handful of things near it.

    It is a SPEED optimisation and nothing else. Every bucket is grown by the
    largest clearance the table declares plus the body's own radius, so an entry
    that could possibly conflict is always in the cell that asks about it -- and
    the structural suite proves the index and the locked
    :func:`presence_conflicts` agree everywhere, because an index that quietly
    dropped an obstacle would be a walker walking through a building.
    """

    CELL = 4.0

    def __init__(self, validator, body_radius: float) -> None:
        """Bucket every clearance-bearing occupancy entry into the grid."""
        self.entries = list(validator.entries)
        reach = body_radius + max(
            value for value in PRESENCE_CLEARANCE.values() if value is not None
        )
        self.buckets: dict[tuple[int, int], list[dict]] = {}
        for entry in self.entries:
            if PRESENCE_CLEARANCE.get(entry["category"]) is None:
                continue
            low_x, low_y, high_x, high_y = entry["bounds"]
            for cell_x in range(
                int(math.floor((low_x - reach) / self.CELL)),
                int(math.floor((high_x + reach) / self.CELL)) + 1,
            ):
                for cell_y in range(
                    int(math.floor((low_y - reach) / self.CELL)),
                    int(math.floor((high_y + reach) / self.CELL)) + 1,
                ):
                    self.buckets.setdefault((cell_x, cell_y), []).append(entry)

    def conflicts(self, body: dict) -> list[dict]:
        """Every occupancy entry one body would violate, with reasons."""
        cell = (
            int(math.floor(body["x"] / self.CELL)),
            int(math.floor(body["y"] / self.CELL)),
        )
        found: list[dict] = []
        for entry in self.buckets.get(cell, ()):
            clearance = PRESENCE_CLEARANCE[entry["category"]]
            gap = shape_gap(body, entry["shape"])
            if gap < clearance or (clearance == 0.0 and gap <= 0.0):
                found.append(
                    {
                        "conflict_with": entry["id"],
                        "their_category": entry["category"],
                        "required_clearance": clearance,
                        "gap": round(gap, 4),
                    }
                )
        return found


class GroundProbe:
    """The Phase 18 ground model with its inputs resolved once.

    :func:`pedestrian_topology.presence_ground_level` rebuilds the founding
    surface list on every call, and a step test calls it nine times per sample.
    This holds the same surfaces and the same plaza decks and computes the same
    number; the structural suite proves the two agree, so the cache can never
    become a second, kinder opinion about where the ground is.
    """

    def __init__(self, master_spec: dict, fabric_plan: dict) -> None:
        """Resolve the founding surfaces and plaza decks once."""
        self.surfaces = founding_surfaces(master_spec, fabric_plan)
        self.ground = fabric_plan["ground"]
        self.plazas = [
            (
                float(entry["plaza"]["center"][0]),
                float(entry["plaza"]["center"][1]),
                float(entry["plaza"]["radius"]),
                float(entry["plaza"]["base"]) + PLAZA_DECK_THICKNESS,
            )
            for entry in fabric_plan["neighborhoods"].values()
            if entry["plaza"] is not None
        ]

    def level(self, x: float, y: float) -> float:
        """The height a body's feet sit at, surfaces above the ground included."""
        level = ground_level_at((x, y), self.ground)
        for surface in self.surfaces:
            if math.hypot(x - surface["x"], y - surface["y"]) <= surface["r"]:
                level = max(level, surface["top"])
        for centre_x, centre_y, radius, top in self.plazas:
            if math.hypot(x - centre_x, y - centre_y) <= radius:
                level = max(level, top)
        return level

    def step(self, x: float, y: float, radius: float) -> float:
        """How far the ground rises into a body standing here; 0.0 when clear."""
        footing = self.level(x, y)
        worst = 0.0
        for index in range(STEP_PROBES):
            angle = 2.0 * math.pi * index / STEP_PROBES
            worst = max(
                worst,
                self.level(x + math.cos(angle) * radius, y + math.sin(angle) * radius) - footing,
            )
        return worst if worst > STEP_TOLERANCE else 0.0


def route_violations(
    loop: list[tuple[float, float]],
    proxy: dict,
    index: PresenceIndex,
    roads: list[dict],
    probe: GroundProbe,
    mobility_spec: dict,
    body_radius: float,
) -> list[str]:
    """Every reason one route would be unsafe, or an empty list.

    Sampled along its whole length, not merely at its corners, and tested with
    the SAME Phase 18 clearance table that proved a body could stand at the
    anchor. Three independent things are checked: the body's envelope against
    every occupancy entry the city holds, the ground rising into the body, and
    an explicit refusal to enter any carriageway -- the last one redundant with
    the first by design, because a pedestrian in traffic is the single most
    damaging thing this phase could ship.
    """
    route = mobility_spec["pedestrians"]["route"]
    radius = body_radius + route["clearance"]
    anchor_z = float(proxy["z"])
    errors: list[str] = []
    for x, y in resample_polyline(loop, route["sample_step"]):
        body = circle(round(x, 6), round(y, 6), radius)
        conflicts = index.conflicts(body)
        if conflicts:
            first = conflicts[0]
            errors.append(
                f"({x:.2f}, {y:.2f}) violates {first['their_category']} "
                f"{first['conflict_with']} (gap {first['gap']} < {first['required_clearance']})"
            )
            break
        if probe.step(round(x, 6), round(y, 6), body_radius):
            errors.append(f"({x:.2f}, {y:.2f}) has ground stepping into the body")
            break
        level = probe.level(x, y)
        if abs(level - anchor_z) > route["ground_tolerance"]:
            errors.append(
                f"({x:.2f}, {y:.2f}) stands at z={level:.3f}, {abs(level - anchor_z):.3f} from "
                f"the anchor's z={anchor_z:.3f}"
            )
            break
        for shape in roads:
            if shape_gap(body, shape) <= 0.0:
                errors.append(f"({x:.2f}, {y:.2f}) enters a carriageway")
                break
        if errors:
            break
    return errors


def turn_rate_violations(
    loop: list[tuple[float, float]], speed: float, mobility_spec: dict
) -> list[str]:
    """Every place a route turns faster than a body could turn.

    Measured on the RESAMPLED loop at the walking speed the route implies, so a
    turnaround that reads as a pivot on the spot is caught as a number rather
    than left for a reviewer to notice in a video.
    """
    limit = math.radians(mobility_spec["pedestrians"]["route"]["max_turn_rate_deg_s"])
    step = mobility_spec["pedestrians"]["route"]["sample_step"]
    points = resample_polyline(loop, step)
    errors: list[str] = []
    for index in range(len(points) - 1):
        a, b, c = points[index - 1], points[index], points[(index + 1) % (len(points) - 1)]
        first = math.atan2(b[1] - a[1], b[0] - a[0])
        second = math.atan2(c[1] - b[1], c[0] - b[0])
        turn = abs(math.atan2(math.sin(second - first), math.cos(second - first)))
        travelled = math.hypot(b[0] - a[0], b[1] - a[1])
        if travelled <= 1.0e-9:
            continue
        rate = turn * speed / travelled
        if rate > limit:
            errors.append(
                f"({b[0]:.2f}, {b[1]:.2f}) turns at {math.degrees(rate):.0f} deg/s, above the "
                f"declared {mobility_spec['pedestrians']['route']['max_turn_rate_deg_s']}"
            )
            break
    return errors


# ---------------------------------------------------------------------------
# Gait: what walking does to a Phase 18 body
# ---------------------------------------------------------------------------


def _swing(
    point: tuple[float, float, float], pivot: tuple[float, float, float], angle: float
) -> tuple[float, float, float]:
    """Rotate a point about a lateral axis through a joint; +angle is forward.

    The body faces local +X, so a limb swings in the XZ plane. A positive angle
    carries a point below the pivot forwards, which is what a leg reaching for
    the next step does.
    """
    dx, dz = point[0] - pivot[0], point[2] - pivot[2]
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    return (
        pivot[0] + dx * cos_a - dz * sin_a,
        point[1],
        pivot[2] + dx * sin_a + dz * cos_a,
    )


def _centroid(vertices) -> tuple[float, float, float]:
    """The mean of a ring of vertices."""
    count = len(vertices)
    return (
        math.fsum(vertex[0] for vertex in vertices) / count,
        math.fsum(vertex[1] for vertex in vertices) / count,
        math.fsum(vertex[2] for vertex in vertices) / count,
    )


def _rings(vertices: list, sides: int, name: str) -> list[list[tuple[float, float, float]]]:
    """Cut a lofted limb back into the rings it was built from."""
    if len(vertices) % sides:
        raise PedestrianMobilityError(
            f"{name} holds {len(vertices)} vertices, not a whole number of {sides}-sided rings"
        )
    return [list(vertices[start : start + sides]) for start in range(0, len(vertices), sides)]


def body_chains(identity: dict, primitives: dict | None = None) -> dict:
    """Recover the four limb chains from a LOCKED Phase 18 body.

    Read off the emitted primitives, never re-derived from the proportions
    table -- and, since the chain contract v2, never re-derived from a private
    opinion about limb structure either. ``figure_kit.CHAIN_SPEC`` is the one
    published description of what a limb is made of: which primitives form
    each chain, how many lofted rings each holds, which articulation level
    every ring rides at, and which member's rings the three JOINTS -- root,
    middle, tip -- are measured from. This function only reads that table
    against the built vertices. If the kit gives a leg five rings and a calf,
    or hangs a hand off the wrist, the walk follows without this file
    changing again: that is the entire point of the amendment.

    Joints are still ring CENTROIDS of built geometry, and seam rings are
    still the same circle of vertices in both members -- the sleeve's elbow
    and the forearm's elbow move together, so no articulation can open a
    seam. A body whose primitives do not match the published spec is refused,
    never repaired.
    """
    built = primitives or {
        entry["name"]: list(entry["vertices"]) for entry in figure_kit.figure_geometry(identity)
    }
    chains: dict[str, dict] = {}
    for side in ("left", "right"):
        for chain_name, spec in figure_kit.CHAIN_SPEC.items():
            ringed: dict[str, list] = {}
            members: dict[str, tuple] = {}
            for member, levels in spec["members"].items():
                name = f"{side}_{member}"
                if name not in built:
                    raise PedestrianMobilityError(
                        f"a Phase 18 body has no {name}, which the chain contract requires"
                    )
                rings = _rings(built[name], spec["sides"], name)
                if len(rings) != len(levels):
                    raise PedestrianMobilityError(
                        f"{name} holds {len(rings)} rings where the chain contract "
                        f"declares {len(levels)}"
                    )
                ringed[member] = rings
                members[name] = tuple(levels)
            foot = spec["foot"]
            if foot is not None and f"{side}_{foot}" not in built:
                raise PedestrianMobilityError(f"a Phase 18 body has no {side} {foot} to walk on")
            chains[f"{side}_{chain_name}"] = {
                "sides": spec["sides"],
                "joints": [_centroid(ringed[member][ring]) for member, ring in spec["joints"]],
                "members": members,
                "foot": f"{side}_{foot}" if foot is not None else None,
            }
    return chains


def _articulate(
    rings: list, levels: tuple, joints: list, root_angle: float, middle_angle: float
) -> list:
    """Swing one limb primitive's rings about the chain they hang from.

    Three levels, and each is a rigid transform of a real cross-section rather
    than a translation: the ring at the root does not move, the ring at the
    middle joint rotates about the root, and the ring at the tip rotates about
    the middle joint and then about the root with it. Segment lengths are
    therefore preserved exactly -- a thigh cannot stretch, and a knee cannot
    come apart from the shin that meets it.
    """
    root, middle, _tip = joints
    placed: list[list[tuple[float, float, float]]] = []
    for ring, level in zip(rings, levels, strict=True):
        if level == 0:
            placed.append(list(ring))
        elif level == 1:
            placed.append([_swing(vertex, root, root_angle) for vertex in ring])
        else:
            placed.append(
                [_swing(_swing(vertex, middle, middle_angle), root, root_angle) for vertex in ring]
            )
    return [vertex for ring in placed for vertex in ring]


def leg_length(identity: dict) -> float:
    """The straight hip-to-ankle reach of one body, measured from its geometry.

    The stride arithmetic needs a real pendulum length, and a body's legs are
    not a fixed fraction of its height once build and age presentation have had
    their say. Measured from the left leg, which the kit builds symmetrically.
    """
    joints = body_chains(identity)["left_leg"]["joints"]
    return math.dist(joints[0], joints[2])


def gait_cycles(route_length: float, identity: dict, mobility_spec: dict) -> dict:
    """How many strides a route holds, and what that does to the stride itself.

    A loop must close on a WHOLE number of gait cycles or the walk would jump
    at the seam, so the nominal stride is rounded to the nearest whole count and
    the EFFECTIVE stride is whatever that count makes it. The difference is
    reported, and a difference beyond the declared tolerance is refused rather
    than absorbed: past that point the walker really would be over- or
    under-striding for its speed.
    """
    gait = mobility_spec["pedestrians"]["gait"]
    height = float(figure_kit.figure_dimensions(identity)["height"])
    nominal = float(gait["stride_factor"]) * height
    if nominal <= 0.0:
        raise PedestrianMobilityError("a body with no height cannot have a stride")
    cycles = max(1, int(math.floor(route_length / nominal + 0.5)))
    effective = route_length / cycles
    drift = abs(effective / nominal - 1.0)
    if drift > float(gait["stride_tolerance"]):
        raise PedestrianMobilityError(
            f"closing this loop on {cycles} whole strides needs a {effective:.3f}m stride "
            f"against a natural {nominal:.3f}m, {drift:.1%} off the declared "
            f"{gait['stride_tolerance']:.0%} tolerance"
        )
    reach = leg_length(identity)
    ratio = effective / (4.0 * reach)
    if ratio >= 1.0:
        raise PedestrianMobilityError(
            f"a {effective:.3f}m stride is beyond the reach of a {reach:.3f}m leg"
        )
    swing = math.asin(ratio)
    ceiling = math.radians(float(gait["leg_swing_max_deg"]))
    if swing > ceiling:
        raise PedestrianMobilityError(
            f"a {effective:.3f}m stride needs a {math.degrees(swing):.0f} degree leg swing, "
            f"beyond the declared {gait['leg_swing_max_deg']}"
        )
    return {
        "cycles": cycles,
        "nominal_stride": round(nominal, 6),
        "effective_stride": round(effective, 6),
        "stride_drift": round(drift, 6),
        "leg_length": round(reach, 6),
        "leg_swing": round(swing, 9),
        "leg_swing_deg": round(math.degrees(swing), 4),
        "arm_swing": round(swing * float(gait["arm_swing_ratio"]), 9),
        "knee_bend": round(math.radians(float(gait["knee_bend_deg"])), 9),
    }


def gait_angles(phase: float, cycle: dict) -> dict:
    """Every joint angle of one body at one point in its stride.

    ``phase`` runs 0 to 1 over a whole gait cycle. The hips are a sine in
    antiphase, the knee flexes only while its own leg is swinging through, and
    each arm is locked in antiphase to the leg on the SAME side -- which is the
    opposite-arm-and-leg swing a viewer reads as walking rather than marching.
    """
    turn = 2.0 * math.pi * phase
    swing, arm, bend = cycle["leg_swing"], cycle["arm_swing"], cycle["knee_bend"]
    angles: dict[str, float] = {}
    for side, offset in (("left", 0.0), ("right", math.pi)):
        hip = swing * math.sin(turn + offset)
        angles[f"{side}_hip"] = hip
        angles[f"{side}_knee"] = -bend * max(0.0, math.cos(turn + offset))
        angles[f"{side}_ankle"] = -(hip + angles[f"{side}_knee"]) * 0.5
        angles[f"{side}_shoulder"] = -arm * math.sin(turn + offset)
        angles[f"{side}_elbow"] = -abs(arm) * (0.35 + 0.35 * math.sin(turn + offset))
    return angles


def gait_primitives(identity: dict, phase: float, cycle: dict, mobility_spec: dict) -> list[dict]:
    """One LOCKED Phase 18 body, articulated into one moment of its stride.

    Additive by construction: the primitives are the ones ``figure_kit`` emits,
    in the order it emits them, and only the limb and foot vertices move. The
    torso, the neck, the head, the face, the hair and every garment are carried
    through untouched, so a body walking is unmistakably the same body standing.

    The whole figure is then lifted so that its LOWEST foot vertex rests exactly
    on the ground. That is not a cosmetic correction -- it is what makes the
    pelvis rise and fall over the stance leg, which is the vertical bob a viewer
    reads as weight. A figure held at a constant height while its legs swing
    would float, and one that ignored the ground would sink into it.
    """
    angles = gait_angles(phase, cycle)
    emitted = figure_kit.figure_geometry(identity)
    built = {entry["name"]: list(entry["vertices"]) for entry in emitted}
    chains = body_chains(identity, built)
    moved: dict[str, list[tuple[float, float, float]]] = {}
    for side in ("left", "right"):
        for limb, root_key, middle_key in (
            (f"{side}_leg", f"{side}_hip", f"{side}_knee"),
            (f"{side}_arm", f"{side}_shoulder", f"{side}_elbow"),
        ):
            chain = chains[limb]
            root_angle, middle_angle = angles[root_key], angles[middle_key]
            for name, levels in sorted(chain["members"].items()):
                moved[name] = _articulate(
                    _rings(built[name], chain["sides"], name),
                    levels,
                    chain["joints"],
                    root_angle,
                    middle_angle,
                )
        leg = chains[f"{side}_leg"]
        hip, knee, ankle = leg["joints"]
        placed_ankle = _swing(
            _swing(ankle, knee, angles[f"{side}_knee"]), hip, angles[f"{side}_hip"]
        )
        # The foot is a solid, not a chain: it rides its own ankle rigidly, then
        # counter-rotates by half the leg's total swing so it stays nearer the
        # ground plane than the shin does. A foot that simply inherited the shin
        # angle would point at the sky at the top of every step.
        shift = (placed_ankle[0] - ankle[0], 0.0, placed_ankle[2] - ankle[2])
        moved[f"{side}_foot"] = [
            (turned[0] + shift[0], turned[1] + shift[1], turned[2] + shift[2])
            for turned in (
                _swing(vertex, ankle, angles[f"{side}_ankle"]) for vertex in built[f"{side}_foot"]
            )
        ]
    primitives = [
        {**primitive, "vertices": tuple(moved[primitive["name"]])}
        if primitive["name"] in moved
        else dict(primitive)
        for primitive in emitted
    ]
    lift = -min(
        vertex[2]
        for primitive in primitives
        if primitive["name"].endswith("_foot")
        for vertex in primitive["vertices"]
    )
    lift += float(mobility_spec["pedestrians"]["gait"]["bob_metres"]) * (
        0.5 - 0.5 * math.cos(4.0 * math.pi * phase)
    )
    if lift:
        primitives = [
            {
                **primitive,
                "vertices": tuple(
                    (vertex[0], vertex[1], vertex[2] + lift) for vertex in primitive["vertices"]
                ),
            }
            for primitive in primitives
        ]
    return primitives


def gait_mesh(identity: dict, phase: float, cycle: dict, mobility_spec: dict) -> list:
    """One articulated body as a flat vertex list in ``figure_mesh`` order.

    The order matters absolutely: these become SHAPE KEYS on the mesh the
    Phase 18 builder already welded, and a shape key whose vertices are in a
    different order than the mesh is a body turned inside out.
    """
    return [
        vertex
        for primitive in gait_primitives(identity, phase, cycle, mobility_spec)
        for vertex in primitive["vertices"]
    ]


def gait_shapes(identity: dict, cycle: dict, mobility_spec: dict) -> list[list]:
    """Every phase of one walker's stride, as whole-body vertex positions."""
    phases = int(mobility_spec["pedestrians"]["gait"]["phases"])
    return [gait_mesh(identity, index / phases, cycle, mobility_spec) for index in range(phases)]


def gait_travel(identity: dict, cycle: dict, mobility_spec: dict) -> dict:
    """How far each part of a body actually moves over a whole stride.

    The measurement that makes a sliding mannequin impossible to ship. It is
    taken from the GENERATED shape positions rather than from the angles that
    produced them, so a gait whose numbers look like a walk but whose vertices
    never move is caught here rather than in a video.
    """
    base = figure_kit.figure_mesh(identity)["vertices"]
    shapes = gait_shapes(identity, cycle, mobility_spec)
    offsets = [0]
    names: list[str] = []
    for primitive in figure_kit.figure_geometry(identity):
        names.append(primitive["name"])
        offsets.append(offsets[-1] + len(primitive["vertices"]))
    travel: dict[str, float] = {}
    for index, name in enumerate(names):
        low, high = offsets[index], offsets[index + 1]
        worst = 0.0
        for shape in shapes:
            for position in range(low, high):
                worst = max(
                    worst,
                    math.dist(shape[position], base[position]),
                )
        travel[name] = round(worst, 6)
    return travel


def gait_digest(identity: dict, cycle: dict, mobility_spec: dict) -> str:
    """A stable digest of one walker's whole articulated stride.

    Carried in the plan so the host's Python and Blender's can be proven to have
    built the same walk, exactly as the Phase 18 plan hash proves they built the
    same people.
    """
    payload = json.dumps(
        [
            [[round(value, 7) for value in vertex] for vertex in shape]
            for shape in gait_shapes(identity, cycle, mobility_spec)
        ],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def walker_count(total: int, mobility_spec: dict) -> int:
    """How many of the city's proxies walk, from the declared fraction alone.

    Half-up rounding on an exact integer count, then clamped to the declared
    floor and ceiling, so the answer never depends on float formatting and a
    world with more people never produces fewer walkers.
    """
    entry = mobility_spec["pedestrians"]
    wanted = int(math.floor(total * float(entry["moving_fraction"]) + 0.5))
    return max(min(wanted, int(entry["max_moving"]), total), min(int(entry["min_moving"]), total))


def selection_order(proxies: list[dict], mobility_spec: dict) -> list[dict]:
    """The order proxies are offered a route, stable under everything.

    Each proxy draws ONE number from a generator seeded by its own slot id and
    nothing else, so the order is a property of the slot rather than of the
    population, the count, the dict order or the hash seed. A city that grows
    keeps every walker it had; a city that walks more takes the next name off
    the same list.
    """
    keyed = [
        (mobility_seed(mobility_spec, "walker", proxy["slot"]).random(), proxy["slot"], proxy)
        for proxy in proxies
    ]
    keyed.sort(key=lambda item: (item[0], item[1]))
    return [proxy for _draw, _slot, proxy in keyed]


def walking_speed(identity_height: float, mobility_spec: dict) -> float:
    """How fast one body walks, from its own size and nothing else.

    Pendulum scaling on height: a longer leg swings more slowly and covers more
    ground per step, and the two together make a taller body walk a little
    faster. This is MECHANICS. Nothing here reads an age presentation, and
    nothing may: a child walks more slowly in this city because a child's legs
    are shorter, which is a measurement, not an assumption about children.
    """
    speed = mobility_spec["pedestrians"]["speed"]
    scaled = float(speed["base_speed"]) * math.sqrt(
        max(1.0e-6, identity_height / float(speed["reference_height"]))
    )
    return min(max(scaled, float(speed["min"])), float(speed["max"]))
