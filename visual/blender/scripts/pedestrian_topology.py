"""Where a person is ALLOWED to stand in the Phase 16 city.

Pure Python by design -- no ``bpy``. This module answers one question and
refuses to answer any other: given the city the earlier phases actually
built, which ground could a standing human body occupy without violating
anything that is already there?

It does not decide how many people appear (that is authoritative population,
read by :mod:`population_presence_plan`) and it does not decide who they are
(nobody: a proxy is a representative population proxy, never an individual).
It decides GROUND.

The safety model reuses the Phase 16 occupancy truth verbatim. Every road
capsule, junction pad, wall corridor, founding building, plate, grove, quay,
water rectangle, production lot, yard row and planted green is already
expressed as an exact 2D envelope by :mod:`spatial_occupancy`; this module
loads all of it into a :class:`~spatial_occupancy.PlacementValidator` and then
tests each candidate body against every entry with its own clearance table.

Phase 18 owns a SEPARATE clearance table rather than extending the Phase 16
``POLICY`` dict, because a person is not a building and the two disagree in
both directions: a person may stand on a plaza, on paving, and on a founding
plate -- which no production building may do -- and a person must keep out of
the carriageway that a paving panel is free to meet. Extending the locked
table would have made buildings and bodies share rules neither wants.

The four approved area types are::

    frontage    the sidewalk band flanking a street's occupied envelope
    plaza       designed plazas and the civic standing ground around the Seal
    park        the landscape plan's declared park zones
    promenade   the landward walk along the harbour quay

Every candidate this module emits has already been proven clear. A caller
that places a proxy anywhere else is placing it somewhere Phase 18 never
said was safe, and the plan validator will say so.
"""

import hashlib
import json
import math

from city_ground import ground_level_at
from production_spec import FOUNDING_RING_FACTOR, PLATE_MARGIN, port_frame
from scene_spec import stable_rng
from spatial_occupancy import (
    PlacementValidator,
    circle,
    rect,
    shape_gap,
)
from urban_fabric import (
    build_occupancy,
    lot_shapes,
    plan_legacy_clearing,
    plinth_shape,
    road_occupancy,
)

ZONE_TYPES = ("frontage", "plaza", "park", "promenade")

PRESENCE_CLEARANCE: dict[str, float | None] = {
    "ROAD": 0.45,
    "JUNCTION": 0.45,
    "PAVING": None,
    "BUILDING": 0.30,
    "VEGETATION": 0.25,
    "PLAZA": None,
    "WALL": 1.20,
    "HISTORY": 0.40,
    "PLATE": None,
    "GROVE": 0.25,
    "WATER": 1.50,
}
"""Open gap a standing body must keep from each existing occupancy category.

``None`` means the body may stand ON that ground, and only three categories
earn it. ``PLAZA`` and ``PAVING`` are designed walking surfaces -- a plaza
with nobody allowed on it would be a plaza-shaped exclusion zone. ``PLATE``
is the founding district ground, which is civic floor; standing on it is
safe only because the ARCHITECTURE that rises from it is registered
separately as ``HISTORY`` and keeps its own 0.40 clearance, exactly the
reasoning the Phase 16 vegetation policy documents for the same pair.

Everything else is a refusal distance. ``ROAD`` and ``JUNCTION`` carry the
largest ordinary margin because a proxy in a carriageway is the single most
damaging failure this phase could ship: it would read as a person standing
in traffic. ``WATER`` is held furthest off, and ``WALL`` keeps the scar's
corridor clear so the historical boundary is never dressed with bystanders.
"""

SEAL_FORECOURT_SOURCE = "golden_seal"
"""Identity of the civic standing ground around the Golden Seal.

The Seal itself is protected ``HISTORY`` out to its plaza radius; the ring
immediately outside that envelope is the civic forecourt, and it is the one
piece of plaza ground the founding world already had.
"""

FOUNDING_PLATE_RISE = 0.55
FOUNDING_RING_RISE = 0.06
FOUNDING_CORE_BASE = 0.60
FOUNDING_CORE_RISE = 0.08
FOUNDING_CORE_FACTOR = 0.62
"""The founding district plate and the two discs stacked on it.

Phase 15 builds each district as a plate, a ring-road disc, and a raised
civic core -- three solid cylinders, each with its own top. Phase 16's ground
model describes the ground the PRODUCTION city designed and knows nothing
about them, so a body placed by that model alone stands at terrain height
while the real floor beneath it is up to half a metre higher. The first
Phase 18 build buried twelve of eighty proxies to the knee that way, and a
test that re-derived z from the same function that produced it could not see
it. These constants are pinned against the real objects by the structural
suite, and the burial itself is now measured against Blender's own geometry.
"""

DEPOT_PAD_HALF = (6.5, 8.5)
DEPOT_PAD_FACTOR = 0.62
"""Half-extents of a founding depot pad, and where it sits on its district.

Phase 16 registers the depot as a 9.0m circle, which its 13x17 pad overruns
by 1.7m at the corners. Those corner lobes are raised industrial ground: a
body standing on one is both somewhere it should not be and buried 0.94m in
it. Registered here as the exact rectangle rather than a wider circle, so the
refusal costs no legitimate pavement.
"""

PLAZA_DECK_THICKNESS = 0.14
"""Height of the plaza deck above the plaza base level.

Replicates the locked Phase 16 plaza builder, which raises each plaza on a
0.14m concrete cylinder. Without this the city's own ground model reports
the level UNDER the plaza, and a body standing on the deck would be built
sunk to the ankle in it -- which is exactly what the first Phase 18 build
did. The Blender structural suite pins this constant against the real
plaza object, so a Phase 16 change cannot silently un-fix it.
"""

SEAL_MAST_FACTOR = 1.32
SEAL_MAST_HALF = 0.18
"""Frame of the four Golden Seal lighting masts.

They stand at ``seal radius * 1.32``, which is OUTSIDE the Seal's protected
plaza envelope of ``radius + 2.0``, so nothing in the Phase 16 occupancy
model knows they are there. A civic forecourt ring drawn without them puts
somebody inside a lamp post.

The half-extent covers the WIDEST part of the assembly -- the lamp head, not
the slimmer pole a body would actually meet. Over-covering is the safe
direction for an obstacle, the same choice Phase 16 makes for founding
building envelopes, and it costs the forecourt about eight centimetres.
"""

PLAZA_MAST_FACTOR = 0.8
PLAZA_MAST_HALF = 0.13
PLAZA_CENTRE_MAST_HALF = 0.40
"""Frame of a production plaza's six perimeter masts and its centre mast.

Same problem as the Seal masts and the same answer: the plaza is registered
as walkable ground, and the things standing ON it are not registered at all
until Phase 18 puts them there. Both half-extents again cover the widest
part of each assembly.
"""


class PedestrianTopologyError(ValueError):
    """A pedestrian topology violation.

    Raised when the world cannot supply a coherent topology -- a missing
    harbour frame, an unknown zone type, a park zone with no radius. Always
    a refusal, never a repair.
    """


# ---------------------------------------------------------------------------
# Occupancy: everything a body must respect
# ---------------------------------------------------------------------------


def street_furniture(master_spec: dict, fabric_plan: dict) -> list[tuple[str, str, list[dict]]]:
    """The vertical furniture standing on ground the city calls walkable.

    Phase 16's occupancy model describes GROUND -- what a surface is -- and
    the founding plates and plazas it marks walkable are exactly the surfaces
    that carry lamp masts. Nothing else in the pipeline needed to know, so
    nothing else recorded it; a standing body is the first thing that does.

    Returns ``(id, category, shapes)`` triples ready to register. The Seal's
    masts are founding monument furniture and register as ``HISTORY``; a
    plaza's masts are production city furniture and register as ``BUILDING``.
    Both are pinned against the real Blender objects by the structural suite,
    so a drifting replica fails loudly rather than quietly letting somebody
    stand inside a lamp post.
    """
    entries: list[tuple[str, str, list[dict]]] = []
    seal = master_spec["landmarks"]["golden_seal"]
    seal_x, seal_y = float(seal["location"][0]), float(seal["location"][1])
    mast_reach = float(seal["radius"]) * SEAL_MAST_FACTOR
    for index in range(4):
        angle = math.pi / 4.0 + index * math.pi / 2.0
        entries.append(
            (
                f"seal_mast_{index}",
                "HISTORY",
                [
                    circle(
                        seal_x + math.cos(angle) * mast_reach,
                        seal_y + math.sin(angle) * mast_reach,
                        SEAL_MAST_HALF * math.sqrt(2.0),
                    )
                ],
            )
        )
    for district_id, district in sorted(master_spec["districts"].items()):
        center_x = float(district["center"][0])
        center_y = float(district["center"][1])
        reach = math.hypot(center_x, center_y) or 1.0
        pad_x = center_x + (center_x / reach) * float(district["radius"]) * DEPOT_PAD_FACTOR
        pad_y = center_y + (center_y / reach) * float(district["radius"]) * DEPOT_PAD_FACTOR
        entries.append(
            (
                f"depot_pad_{district_id}",
                "HISTORY",
                [rect(pad_x, pad_y, DEPOT_PAD_HALF[0], DEPOT_PAD_HALF[1], 0.0)],
            )
        )
    for neighborhood_id, entry in sorted(fabric_plan["neighborhoods"].items()):
        plaza = entry["plaza"]
        if plaza is None:
            continue
        center_x, center_y = float(plaza["center"][0]), float(plaza["center"][1])
        radius = float(plaza["radius"])
        shapes = [circle(center_x, center_y, PLAZA_CENTRE_MAST_HALF * math.sqrt(2.0))]
        for index in range(6):
            angle = index * math.pi / 3.0
            shapes.append(
                circle(
                    center_x + math.cos(angle) * radius * PLAZA_MAST_FACTOR,
                    center_y + math.sin(angle) * radius * PLAZA_MAST_FACTOR,
                    PLAZA_MAST_HALF * math.sqrt(2.0),
                )
            )
        entries.append((f"plaza_masts_{neighborhood_id}", "BUILDING", shapes))
    return entries


def founding_surfaces(master_spec: dict, fabric_plan: dict) -> list[dict]:
    """Every raised founding disc a body could end up standing on.

    The district plate, the ring-road disc where the composition kept it
    whole, and the raised civic core. Each is a solid cylinder Phase 15 built
    and Phase 16's ground model never described, so each is a floor the
    presence layer has to know about or stand inside.
    """
    plates = fabric_plan["ground"]["plates"]
    surfaces: list[dict] = []
    for district_id, district in sorted(master_spec["districts"].items()):
        center_x = float(district["center"][0])
        center_y = float(district["center"][1])
        radius = float(district["radius"])
        elevation = float(district["elevation"])
        surfaces.append(
            {
                "id": f"plate_{district_id}",
                "x": center_x,
                "y": center_y,
                "r": radius + PLATE_MARGIN,
                "top": min(0.0, elevation) + FOUNDING_PLATE_RISE + max(elevation, 0.0),
            }
        )
        if plates.get(district_id, {}).get("ring") == "full":
            surfaces.append(
                {
                    "id": f"ring_{district_id}",
                    "x": center_x,
                    "y": center_y,
                    "r": radius * FOUNDING_RING_FACTOR,
                    "top": elevation + FOUNDING_PLATE_RISE + FOUNDING_RING_RISE,
                }
            )
        surfaces.append(
            {
                "id": f"core_{district_id}",
                "x": center_x,
                "y": center_y,
                "r": radius * FOUNDING_CORE_FACTOR,
                "top": elevation + FOUNDING_CORE_BASE + FOUNDING_CORE_RISE,
            }
        )
    return surfaces


def presence_ground_level(x: float, y: float, master_spec: dict, fabric_plan: dict) -> float:
    """The height a body's feet sit at, including surfaces above the ground.

    :func:`city_ground.ground_level_at` is the authority on the ground the
    PRODUCTION city designed. It is not the authority on what stands on that
    ground: a plaza deck is built on it, and so are the founding plate, its
    ring disc and its civic core. Presence is the only layer that ever stands
    on any of them, so they are added here rather than by reopening the locked
    ground model.

    Plinths, yard rows, junction pads and depot pads are the other raised
    surfaces, and all four are registered obstacles: nobody stands on them, so
    nobody needs their height.
    """
    level = ground_level_at((x, y), fabric_plan["ground"])
    for surface in founding_surfaces(master_spec, fabric_plan):
        if math.hypot(x - surface["x"], y - surface["y"]) <= surface["r"]:
            level = max(level, surface["top"])
    for entry in fabric_plan["neighborhoods"].values():
        plaza = entry["plaza"]
        if plaza is None:
            continue
        gap = math.hypot(x - float(plaza["center"][0]), y - float(plaza["center"][1]))
        if gap <= float(plaza["radius"]):
            level = max(level, float(plaza["base"]) + PLAZA_DECK_THICKNESS)
    return level


STEP_TOLERANCE = 0.12
"""How much higher than a body's own footing the ground beside it may be.

The city's floor is deliberately stepped -- terrain, ground cells, plate
skirts, plate tables -- and a body standing right at the foot of a step is
built with the step cutting through its shins. A kerb is fine; a knee-high
edge through the body is not. Anything above this is refused.
"""

STEP_PROBES = 8
"""Directions sampled around a body when testing it against ground steps."""


def step_conflict(x: float, y: float, radius: float, master_spec: dict, fabric_plan: dict) -> float:
    """How far the ground rises into a body standing here; 0.0 when clear.

    Probes a ring at the body's own radius and compares each footing with the
    body's. Pure, and it reuses the city's own ground model rather than
    replicating any geometry, so it cannot drift from what Blender builds.
    """
    footing = presence_ground_level(x, y, master_spec, fabric_plan)
    worst = 0.0
    for index in range(STEP_PROBES):
        angle = 2.0 * math.pi * index / STEP_PROBES
        beside = presence_ground_level(
            x + math.cos(angle) * radius,
            y + math.sin(angle) * radius,
            master_spec,
            fabric_plan,
        )
        worst = max(worst, beside - footing)
    return worst if worst > STEP_TOLERANCE else 0.0


def build_presence_occupancy(
    master_spec: dict, production_spec: dict, graph: dict, fabric_plan: dict
) -> PlacementValidator:
    """Load the Phase 16 fixed truth AND every placed Phase 16 object.

    :func:`urban_fabric.build_occupancy` registers what existed before the
    production fabric was planned; the fabric itself -- plazas, lots, yard
    rows, greens -- is registered here from the finished plan, exactly as
    :func:`urban_fabric.validate_urban_fabric` does when it re-proves the
    spatial contract from scratch.

    Lot PLINTHS are registered too, as ``BUILDING``. Phase 16 does not
    register them (nothing it places would ever want to sit on one), but a
    plinth is a raised base 0.30m or more above the pavement: a body standing
    on that footprint at ground height would be visibly sunk into it. Keeping
    bodies off plinth footprints is what makes ``ground_level_at`` the whole
    truth about a proxy's feet.
    """
    clearing = plan_legacy_clearing(master_spec, production_spec, graph)
    validator = build_occupancy(master_spec, graph, clearing, fabric_plan.get("ground"))
    for neighborhood_id, entry in sorted(fabric_plan["neighborhoods"].items()):
        plaza = entry["plaza"]
        if plaza is not None:
            validator.register(
                f"plaza_{neighborhood_id}",
                "PLAZA",
                [circle(plaza["center"][0], plaza["center"][1], plaza["radius"])],
            )
        for lot in entry["lots"]:
            validator.register(f"lot_{lot['name']}", "BUILDING", lot_shapes(lot))
            validator.register(f"plinth_{lot['name']}", "BUILDING", [plinth_shape(lot)])
        for row in entry["yard_rows"]:
            validator.register(
                f"stack_{row['name']}",
                "BUILDING",
                [rect(row["x"], row["y"], row["length"] / 2.0 + 0.3, 1.35, row["heading"])],
            )
        for green in entry["greens"]:
            validator.register(
                f"green_{green['name'].split('__', 1)[-1]}",
                "VEGETATION",
                [circle(green["x"], green["y"], green["envelope"])],
            )
    for entry_id, category, shapes in street_furniture(master_spec, fabric_plan):
        validator.register(entry_id, category, shapes)
    return validator


def presence_conflicts(validator: PlacementValidator, body: dict) -> list[dict]:
    """Every occupancy entry one standing body would violate, with reasons.

    Mirrors :meth:`PlacementValidator.conflicts` -- same envelope maths, same
    diagnosable record -- but against the Phase 18 clearance table, which the
    locked Phase 16 ``POLICY`` cannot express because presence is not a
    building.
    """
    radius = body["r"]
    low_x, low_y = body["x"] - radius, body["y"] - radius
    high_x, high_y = body["x"] + radius, body["y"] + radius
    found: list[dict] = []
    for entry in validator.entries:
        clearance = PRESENCE_CLEARANCE.get(entry["category"])
        if clearance is None:
            continue
        bounds = entry["bounds"]
        if (
            low_x > bounds[2] + clearance
            or high_x < bounds[0] - clearance
            or low_y > bounds[3] + clearance
            or high_y < bounds[1] - clearance
        ):
            continue
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


# ---------------------------------------------------------------------------
# Candidate ground, per approved area type
# ---------------------------------------------------------------------------


def _stations(path: list[tuple[float, float]], step: float) -> list[tuple[float, float, float]]:
    """(x, y, heading) samples walked at a fixed step along a polyline."""
    samples: list[tuple[float, float, float]] = []
    carried = 0.0
    for (x0, y0), (x1, y1) in zip(path, path[1:], strict=False):
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length <= 1.0e-9:
            continue
        heading = math.atan2(dy, dx)
        distance = carried
        while distance <= length:
            t = distance / length
            samples.append((x0 + dx * t, y0 + dy * t, heading))
            distance += step
        carried = distance - length
    return samples


def _wrap_angle(angle: float) -> float:
    """Normalise an angle into (-pi, pi] so headings compare exactly."""
    wrapped = math.fmod(angle + math.pi, 2.0 * math.pi)
    if wrapped <= 0.0:
        wrapped += 2.0 * math.pi
    return wrapped - math.pi


def frontage_candidates(graph: dict, zone: dict) -> list[dict]:
    """Sidewalk stations flanking every street's occupied envelope.

    Both sides of every segment, at each declared lateral offset beyond what
    the street physically occupies. The offsets are metres OUTWARD from the
    carriageway edge, so the near lane hugs the kerb and the far lane stands
    back against the building line; whichever of them the real geometry
    allows is what survives validation.
    """
    candidates: list[dict] = []
    for segment_id, segment in sorted(graph["segments"].items()):
        half_width = road_occupancy(segment)
        path = list(segment["path"])
        if segment["closed"] and len(path) > 1 and path[0] != path[-1]:
            path = path + [path[0]]
        for x, y, heading in _stations(path, float(zone["spacing"])):
            normal_x, normal_y = -math.sin(heading), math.cos(heading)
            for side, side_label in ((1.0, "l"), (-1.0, "r")):
                for offset in zone["offsets"]:
                    reach = half_width + float(offset)
                    candidates.append(
                        {
                            "zone": "frontage",
                            "source": segment_id,
                            "side": side_label,
                            "x": x + normal_x * side * reach,
                            "y": y + normal_y * side * reach,
                            "street_heading": heading,
                            "inward": (-normal_x * side, -normal_y * side),
                        }
                    )
    return candidates


def plaza_sources(master_spec: dict, fabric_plan: dict) -> list[dict]:
    """Every designed plaza plus the civic forecourt around the Golden Seal.

    A planned plaza is standing ground from its own centre outward. The Seal
    is the opposite shape: its monument and apron are protected history, so
    its standing ground is the ring immediately OUTSIDE that envelope, which
    is why each source declares the base radius its rings start from.
    """
    seal = master_spec["landmarks"]["golden_seal"]
    sources = [
        {
            "id": SEAL_FORECOURT_SOURCE,
            "x": float(seal["location"][0]),
            "y": float(seal["location"][1]),
            "base": float(seal["radius"]) + 2.0,
        }
    ]
    for neighborhood_id, entry in sorted(fabric_plan["neighborhoods"].items()):
        plaza = entry["plaza"]
        if plaza is None:
            continue
        sources.append(
            {
                "id": f"plaza_{neighborhood_id}",
                "x": float(plaza["center"][0]),
                "y": float(plaza["center"][1]),
                "base": 0.0,
            }
        )
    return sources


def _ring_points(
    center_x: float, center_y: float, radius: float, spacing: float
) -> list[tuple[float, float]]:
    """Evenly spaced points on one ring, starting due east, going anticlockwise."""
    if radius <= 1.0e-9:
        return [(center_x, center_y)]
    count = max(1, int((2.0 * math.pi * radius) // spacing))
    return [
        (
            center_x + radius * math.cos(2.0 * math.pi * index / count),
            center_y + radius * math.sin(2.0 * math.pi * index / count),
        )
        for index in range(count)
    ]


def plaza_candidates(master_spec: dict, fabric_plan: dict, zone: dict) -> list[dict]:
    """Standing ground on plazas and civic forecourts, ring by ring."""
    candidates: list[dict] = []
    for source in plaza_sources(master_spec, fabric_plan):
        for offset in zone["offsets"]:
            radius = source["base"] + float(offset)
            for x, y in _ring_points(source["x"], source["y"], radius, float(zone["spacing"])):
                candidates.append(
                    {
                        "zone": "plaza",
                        "source": source["id"],
                        "side": "",
                        "x": x,
                        "y": y,
                        "center": (source["x"], source["y"]),
                    }
                )
    return candidates


def park_candidates(production_spec: dict, zone: dict) -> list[dict]:
    """Standing ground inside the landscape plan's declared park zones.

    The offsets are FRACTIONS of each zone's own radius, so one policy suits
    a 5.5m pocket and an 11m grove alike. Trees are registered occupancy, so
    the ones that fall under a canopy are refused rather than hidden.
    """
    landscape = production_spec.get("landscape", {})
    park_zones = landscape.get("park_zones", {})
    candidates: list[dict] = []
    for zone_id, park in sorted(park_zones.items()):
        center_x, center_y = float(park["center"][0]), float(park["center"][1])
        park_radius = float(park["radius"])
        if park_radius <= 0.0:
            raise PedestrianTopologyError(f"park zone {zone_id} has no radius")
        for fraction in zone["offsets"]:
            radius = park_radius * float(fraction)
            for x, y in _ring_points(center_x, center_y, radius, float(zone["spacing"])):
                candidates.append(
                    {
                        "zone": "park",
                        "source": zone_id,
                        "side": "",
                        "x": x,
                        "y": y,
                        "center": (center_x, center_y),
                    }
                )
    return candidates


PROMENADE_HALF_LENGTH = 21.5
"""Half the quay's run, matching the Phase 16 harbour quay envelope.

The promenade is the walk beside that quay, so it is exactly as long as the
quay is; a promenade that ran past the end of the harbour would be a walk
along nothing.
"""


def promenade_candidates(master_spec: dict, zone: dict) -> list[dict]:
    """The landward waterfront walk, sampled along the quay.

    The offsets are metres LANDWARD from the quay centre line, so a proxy on
    the near lane stands at the water's edge with the harbour in front of it
    and the city behind.
    """
    (port_x, port_y), (unit_x, unit_y), quay_distance = port_frame(master_spec)
    along_x, along_y = -unit_y, unit_x
    candidates: list[dict] = []
    for offset in zone["offsets"]:
        reach = quay_distance - float(offset)
        base_x = port_x + unit_x * reach
        base_y = port_y + unit_y * reach
        steps = int((2.0 * PROMENADE_HALF_LENGTH) // float(zone["spacing"]))
        for index in range(steps + 1):
            along = -PROMENADE_HALF_LENGTH + index * float(zone["spacing"])
            candidates.append(
                {
                    "zone": "promenade",
                    "source": "harbor_quay",
                    "side": "",
                    "x": base_x + along_x * along,
                    "y": base_y + along_y * along,
                    "water": (unit_x, unit_y),
                }
            )
    return candidates


# ---------------------------------------------------------------------------
# Ownership, orientation, ordering
# ---------------------------------------------------------------------------


def district_territories(master_spec: dict, production_spec: dict) -> dict[str, list[tuple]]:
    """Every anchor point that speaks for a district's visual territory.

    A district is present in the world twice over: as its founding plate, and
    as the production quarters the Phase 16 spec nests inside it. Ownership of
    a piece of ground is decided by whichever of those anchors is nearest, so
    a proxy always belongs to the district whose city it is actually standing
    in.
    """
    territories: dict[str, list[tuple]] = {}
    for district_id, district in sorted(master_spec["districts"].items()):
        territories[district_id] = [(float(district["center"][0]), float(district["center"][1]))]
    for neighborhood_id, neighborhood in sorted(production_spec["neighborhoods"].items()):
        district_id = neighborhood["district"]
        if district_id not in territories:
            raise PedestrianTopologyError(
                f"neighborhood {neighborhood_id} claims unknown district {district_id!r}"
            )
        territories[district_id].append(
            (float(neighborhood["center"][0]), float(neighborhood["center"][1]))
        )
    return territories


def owning_district(x: float, y: float, territories: dict[str, list[tuple]]) -> tuple[str, float]:
    """The district whose nearest anchor claims a point, and that distance.

    Ties break on district id so the answer never depends on dict order.
    """
    best_id = ""
    best_gap = math.inf
    for district_id in sorted(territories):
        for anchor_x, anchor_y in territories[district_id]:
            gap = math.hypot(x - anchor_x, y - anchor_y)
            if gap < best_gap:
                best_gap = gap
                best_id = district_id
    if not best_id:
        raise PedestrianTopologyError("no district territory was declared")
    return best_id, best_gap


def candidate_heading(candidate: dict, orientation: str) -> float:
    """Which way a body at this candidate looks, from geometry alone.

    No candidate ever chooses its own heading: ``face_street`` looks at the
    carriageway it stands beside, ``along_street`` looks down the pavement
    (the two sides look opposite ways, so a street reads as two directions of
    travel), ``face_center`` looks into the plaza or park it occupies, and
    ``face_water`` looks out over the harbour.
    """
    if orientation == "along_street":
        heading = candidate["street_heading"]
        return _wrap_angle(heading if candidate["side"] == "l" else heading + math.pi)
    if orientation == "face_street":
        inward_x, inward_y = candidate["inward"]
        return _wrap_angle(math.atan2(inward_y, inward_x))
    if orientation == "face_center":
        center_x, center_y = candidate["center"]
        return _wrap_angle(math.atan2(center_y - candidate["y"], center_x - candidate["x"]))
    if orientation == "face_water":
        unit_x, unit_y = candidate["water"]
        return _wrap_angle(math.atan2(unit_y, unit_x))
    raise PedestrianTopologyError(f"unknown orientation rule {orientation!r}")


def spread_order(candidates: list[dict], anchor: tuple[float, float]) -> list[dict]:
    """Order candidates so that any PREFIX of the result is well spread.

    Greedy farthest-point selection: the first candidate is the one nearest
    the district's anchor, and each next is whichever remaining candidate
    stands furthest from everything already chosen. Ties break on the
    candidate's position in the incoming order, which is itself sorted.

    The prefix property is the whole point. A district that grows from seven
    visible people to sixteen must not rearrange the seven, and it does not:
    running this for sixteen produces the same first seven it produced for
    seven, because each step only ever appends.
    """
    remaining = list(candidates)
    if not remaining:
        return []
    first = min(
        range(len(remaining)),
        key=lambda index: (
            math.hypot(remaining[index]["x"] - anchor[0], remaining[index]["y"] - anchor[1]),
            index,
        ),
    )
    ordered = [remaining.pop(first)]
    best_gap = [
        math.hypot(entry["x"] - ordered[0]["x"], entry["y"] - ordered[0]["y"])
        for entry in remaining
    ]
    while remaining:
        pick = max(range(len(remaining)), key=lambda index: (best_gap[index], -index))
        chosen = remaining.pop(pick)
        best_gap.pop(pick)
        ordered.append(chosen)
        for index, entry in enumerate(remaining):
            gap = math.hypot(entry["x"] - chosen["x"], entry["y"] - chosen["y"])
            if gap < best_gap[index]:
                best_gap[index] = gap
    return ordered


# ---------------------------------------------------------------------------
# The topology
# ---------------------------------------------------------------------------


def plan_pedestrian_topology(
    master_spec: dict, production_spec: dict, graph: dict, fabric_plan: dict, presence_spec: dict
) -> dict:
    """Every piece of ground a standing body may legally occupy.

    Returns ``{"zones": {district_id: {zone_type: [candidate, ...]}},
    "refused": {...}, "summary": {...}}``. Each candidate carries its
    position, its proven-clear body envelope, its heading, the district that
    owns it, the geometry it came from, and the ground height its feet sit
    at. Everything returned has already been tested against the full Phase 16
    occupancy; everything refused is counted by the reason it was refused.

    This is deliberately population-blind. It is computed once for a world and
    is the same whether that world holds four residents or four hundred.
    """
    zones_spec = presence_spec["zones"]
    body_radius = float(presence_spec["proxy"]["radius"])
    validator = build_presence_occupancy(master_spec, production_spec, graph, fabric_plan)
    territories = district_territories(master_spec, production_spec)

    raw: dict[str, list[dict]] = {
        "frontage": frontage_candidates(graph, zones_spec["frontage"]),
        "plaza": plaza_candidates(master_spec, fabric_plan, zones_spec["plaza"]),
        "park": park_candidates(production_spec, zones_spec["park"]),
        "promenade": promenade_candidates(master_spec, zones_spec["promenade"]),
    }

    accepted: dict[str, dict[str, list[dict]]] = {
        district_id: {zone_id: [] for zone_id in ZONE_TYPES} for district_id in sorted(territories)
    }
    refused: dict[str, int] = {}
    for zone_id in ZONE_TYPES:
        orientation = zones_spec[zone_id]["orientation"]
        for candidate in raw[zone_id]:
            # Round FIRST, then decide. Every published coordinate must be the
            # exact coordinate that was tested: a candidate proven clear at full
            # precision and then published rounded is a candidate nobody checked,
            # and on a polygon boundary the two answers genuinely differ. Rounding
            # here also absorbs the last-ulp disagreement between one machine's
            # trigonometry and another's, so the plan hashes identically
            # everywhere.
            x = round(candidate["x"], 6)
            y = round(candidate["y"], 6)
            conflicts = presence_conflicts(validator, circle(x, y, body_radius))
            if conflicts:
                key = f"{zone_id}-{conflicts[0]['their_category'].lower()}"
                refused[key] = refused.get(key, 0) + 1
                continue
            if step_conflict(x, y, body_radius, master_spec, fabric_plan):
                key = f"{zone_id}-step"
                refused[key] = refused.get(key, 0) + 1
                continue
            district_id, _gap = owning_district(x, y, territories)
            accepted[district_id][zone_id].append(
                {
                    "zone": zone_id,
                    "source": candidate["source"],
                    "district": district_id,
                    "x": x,
                    "y": y,
                    "z": round(presence_ground_level(x, y, master_spec, fabric_plan), 4),
                    "heading": round(
                        candidate_heading({**candidate, "x": x, "y": y}, orientation), 6
                    ),
                    "radius": body_radius,
                }
            )

    for district_id in sorted(accepted):
        anchor = territories[district_id][0]
        for zone_id in ZONE_TYPES:
            accepted[district_id][zone_id] = spread_order(accepted[district_id][zone_id], anchor)

    summary = {
        "candidates_by_zone": {
            zone_id: sum(len(entry[zone_id]) for entry in accepted.values())
            for zone_id in ZONE_TYPES
        },
        "candidates_by_district": {
            district_id: sum(len(entry[zone_id]) for zone_id in ZONE_TYPES)
            for district_id, entry in sorted(accepted.items())
        },
        "candidates_tested": sum(len(entries) for entries in raw.values()),
        "candidates_refused": sum(refused.values()),
    }
    return {"zones": accepted, "refused": dict(sorted(refused.items())), "summary": summary}


def validate_pedestrian_topology(
    topology: dict, master_spec: dict, production_spec: dict, graph: dict, fabric_plan: dict
) -> list[str]:
    """Re-prove every accepted candidate against a freshly loaded occupancy.

    Nothing here trusts the generator: the validator is rebuilt from the
    specs and the finished fabric plan, and every candidate the topology
    published is audited again. A single conflict is an error.
    """
    errors: list[str] = []
    validator = build_presence_occupancy(master_spec, production_spec, graph, fabric_plan)
    territories = district_territories(master_spec, production_spec)
    for district_id, zones in sorted(topology["zones"].items()):
        if district_id not in territories:
            errors.append(f"topology invents district {district_id}")
            continue
        for zone_id in sorted(zones):
            if zone_id not in ZONE_TYPES:
                errors.append(f"topology invents zone type {zone_id}")
                continue
            for candidate in zones[zone_id]:
                body = circle(candidate["x"], candidate["y"], candidate["radius"])
                for conflict in presence_conflicts(validator, body):
                    errors.append(
                        f"{zone_id} candidate at ({candidate['x']}, {candidate['y']}) "
                        f"violates {conflict['their_category']} {conflict['conflict_with']} "
                        f"(gap {conflict['gap']} < {conflict['required_clearance']})"
                    )
                rise = step_conflict(
                    candidate["x"],
                    candidate["y"],
                    candidate["radius"],
                    master_spec,
                    fabric_plan,
                )
                if rise:
                    errors.append(
                        f"{zone_id} candidate at ({candidate['x']}, {candidate['y']}) has ground "
                        f"rising {round(rise, 4)} into it, above the {STEP_TOLERANCE} tolerance"
                    )
                expected = round(
                    presence_ground_level(candidate["x"], candidate["y"], master_spec, fabric_plan),
                    4,
                )
                if candidate["z"] != expected:
                    errors.append(
                        f"{zone_id} candidate at ({candidate['x']}, {candidate['y']}) stands at "
                        f"z={candidate['z']} but its ground is at z={expected}"
                    )
                owner, _gap = owning_district(candidate["x"], candidate["y"], territories)
                if owner != district_id:
                    errors.append(
                        f"{zone_id} candidate at ({candidate['x']}, {candidate['y']}) is filed "
                        f"under {district_id} but stands in {owner}"
                    )
    return errors


def topology_hash(topology: dict) -> str:
    """A stable digest of the WHOLE offer of ground.

    The presence plan only ever observes the candidates its slot pools walk --
    on the shipped world that is under two fifths of them -- so a plan digest
    alone leaves most of the topology uncompared between the host's Python and
    Blender's. This covers all of it.
    """
    payload = json.dumps(topology, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def presence_seed(presence_spec: dict, *parts: str):
    """A generator owned by one presence identity and nothing else.

    Every proxy draws its variant and pose from a generator seeded by its own
    slot id, so activating a ninth proxy cannot disturb the eight that were
    already standing there.
    """
    return stable_rng(presence_spec["visual_seed"], "presence", *parts)


def street_occupancy_shapes(validator: PlacementValidator) -> list[dict]:
    """Every carriageway envelope, for tests that must prove bodies stay out.

    Read back OUT of the loaded validator rather than recomputed from the
    graph. The two are not the same thing: the final composition BURIES the
    founding ring sectors it no longer uses under the urban table, so a ring
    road's polyline is not its occupancy. Recomputing here would have
    re-invented that rule, got it wrong, and reported people standing in
    streets that no longer exist -- which is exactly what the first version
    of this function did.
    """
    return [entry["shape"] for entry in validator.entries if entry["category"] == "ROAD"]
