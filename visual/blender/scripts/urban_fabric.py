"""Deterministic urban-fabric layout for the Phase 16 production world.

Pure Python by design -- no ``bpy``. Given the Master Scene Spec, the
Production World Spec, and the validated road graph, this module decides
WHERE the production city's mass goes -- in the master-plan order of the
aesthetic-first redesign:

    world structure -> historical anchors -> designed streets -> clearing
        -> plazas -> building lots -> yards -> landscape (planted LAST)

The obstacle priority model (:data:`spatial_occupancy.PRIORITY_CLASSES`)
is enforced by that order. Class A truth (plates, wall lines, water, the
Seal) is registered first and never touched. The designed streets are
Class B: they are never bent by decoration -- instead the LEGACY CLEARING
pass decides, deterministically, which founding vegetation clusters the
city preserves as parks (those inside a declared park zone and genuinely
clear of the designed streets) and which are cleared for construction.
Buildings are Class C: they ladder back from their frontage or shrink
before they may ever displace city structure. Production vegetation is
Class D: planted last, into validated remaining ground, with an urban
reason for every tree -- street lines, park groups, courtyards, the quay
promenade.

Every candidate is checked against everything already standing before it
may claim its ground; a candidate that conflicts is refused with a
recorded reason. Nothing overlaps a road, nothing grows through a
building, and semantic history is never moved.

Determinism: all variation is seeded by SHA-256 over the production visual
seed and each candidate's own identity; iteration is sorted; the plan is a
pure function of its inputs.
"""

import math

from city_ground import (
    ground_level_at,
    kept_ring_paths,
    plan_city_ground,
    validate_city_ground,
)
from production_spec import PLATE_MARGIN, coast_coordinate, port_frame
from road_graph import (
    ROAD_CLASS_WIDTHS,
    distance_point_polyline,
    junction_pads,
)
from scene_spec import stable_rng
from spatial_occupancy import (
    PlacementValidator,
    capsule,
    circle,
    founding_blocked_buildings,
    founding_building_lots,
    founding_grove_clusters,
    polyline_capsules,
    rect,
    signed_gap,
)

PRODUCTION_ROAD_OCCUPANCY = {
    "arterial": 4.6,
    "collector": 3.4,
    "local": 2.1,
    "service": 2.2,
}
FOUNDING_ROAD_OCCUPANCY = {
    "arterial": 5.9,
    "collector": 2.8,
    "local": 2.1,
    "service": 2.2,
}
"""Occupied half-width per street: what physically stands there.

Founding avenues carry real sidewalk and curb meshes out to 5.9; founding
ring roads and spurs are bare carriageways. Production streets are
carriageway plus lamp verge -- their sidewalks are the per-lot frontage
strips the fabric itself provides. Buildings and trees clear THESE
envelopes plus the policy margins, not an imaginary right-of-way."""


def road_occupancy(segment: dict) -> float:
    """The physically occupied half-width of one street segment."""
    table = FOUNDING_ROAD_OCCUPANCY if segment["existing"] else PRODUCTION_ROAD_OCCUPANCY
    return table[segment["class"]]


SCAR_CORRIDOR_RADIUS = 6.0
SCAR_LOT_CLEARANCE = 10.0
"""The great wall line (the built scar) keeps its full breathing room,
measured to real footprint edges and to lot centers respectively."""

STATION_CORRIDOR_RADIUS = 2.5
STATION_LOT_CLEARANCE = 4.5
"""The short boundary station lines carry no built wall; they stay
road-clear and modestly respected as reserved alignments, but they do not
deaden whole quarters the way the scar's corridor rightly does."""

SCAR_STATION_LENGTH = 30.0
"""A wall station at least this long is the scar; shorter ones are the
reserved alignments between the western districts."""

FRONT_GAP = 0.9
"""Open gap between a street's occupied envelope and a building face."""

TREED_FRONT_GAP = 6.0
"""Building face setback on tree-lined street sides: the formal tree line
(setback + full canopy + building clearance) fits between carriageway and
facade, so boulevards read green without a single canopy touching glass."""

CORE_FALLOFF_REACH = 26.0
"""Distance over which building heights ease off away from a quarter core."""

PLINTH_MARGIN = 1.0
PLINTH_TOP = 0.30
"""Every lot stands on its own rectangular plinth: footprint hull plus
margin, top at PLINTH_TOP + quarter elevation. Ground is derived from the
lots -- blocks against streets -- so the city never reads as circular
pods."""

PLINTH_CARRIAGEWAY_CLEARANCE = 0.1
"""Open ground a lot's plinth keeps from every carriageway.

A plinth is the only part of a lot the occupancy contract never used to
see: masses are validated, the ground slab they stand on was not, and it
reaches PLINTH_MARGIN beyond them. Four production plinths therefore
stood inside carriageway plan-space -- invisible, because they sit under
the road deck, and harmless only by luck of elevation. A building's
foundation does not belong in the street whether or not anyone can see
it, so the plinth is now laddered and audited like everything else.

The bar is the CARRIAGEWAY, not the wider occupancy envelope: a plinth
legitimately underlies the frontage strip that road_occupancy covers --
that strip is the lot's own pavement -- but it may never underlie the
surface a vehicle drives on."""

PLINTH_LIP = 0.06
"""How far a plinth must rise above whatever ground it stands on.

The composition's floor is stepped, so a per-quarter constant is not the
ground: a lot standing on a plate skirt would otherwise be BUILT SUNK
into the slab beneath it. Every plinth is lifted to clear its own
ground by this lip, and every tree is planted exactly ON its ground
rather than hovering over it."""

SCAN_STEP = 2.0
"""Fine step for the adaptive frontage walk along each street."""

LOT_KINDS = {
    "row_low": {"units": (2, 3), "w": (4.6, 6.0), "d": (4.4, 5.4), "h": (4.2, 7.5)},
    "row_mid": {"units": (2, 3), "w": (5.0, 6.4), "d": (4.8, 5.8), "h": (12.0, 17.5)},
    "midrise_slab": {"units": (1, 1), "w": (9.0, 11.5), "d": (6.2, 7.2), "h": (15.0, 21.0)},
    "midrise_court": {"units": (2, 2), "w": (6.2, 7.6), "d": (5.6, 6.6), "h": (14.0, 19.0)},
    "court": {"units": (2, 2), "w": (4.8, 6.0), "d": (4.6, 5.4), "h": (7.0, 12.0)},
    "shed": {"units": (1, 1), "w": (8.0, 10.5), "d": (5.6, 6.8), "h": (5.0, 7.0)},
    "shed_pair": {"units": (2, 2), "w": (6.6, 8.4), "d": (5.4, 6.4), "h": (5.0, 7.2)},
    "office_slab": {"units": (1, 1), "w": (7.0, 9.0), "d": (5.0, 6.0), "h": (11.0, 15.0)},
    "duo_low": {"units": (2, 2), "w": (3.9, 4.9), "d": (4.0, 4.8), "h": (4.4, 7.2)},
    "duo_mid": {"units": (2, 2), "w": (4.2, 5.2), "d": (4.6, 5.4), "h": (12.0, 16.5)},
    "single_low": {"units": (1, 1), "w": (4.4, 5.6), "d": (3.6, 4.4), "h": (3.8, 6.0)},
    "midrise_point": {"units": (1, 1), "w": (4.8, 6.2), "d": (5.0, 6.0), "h": (15.5, 20.0)},
    "midrise_pair": {"units": (2, 2), "w": (4.0, 4.8), "d": (4.8, 5.6), "h": (14.5, 18.0)},
}
"""Compound massing vocabulary: footprint and height ranges per lot kind.

``midrise_slab`` and ``midrise_court`` are the city's deliberate middle
scale -- five to seven floors between the founding towers and the low
fabric -- so the skyline steps down instead of jumping.

``midrise_point`` and ``midrise_pair`` are that same middle scale in the
NARROW parcels this city actually has. The founding plates, avenues, and
wall corridors leave five- to eight-metre slots between streets; a wide
slab cannot stand there, so the final composition builds what a real
dense city builds on constrained ground -- point blocks. They carry the
urban shoulder into gaps that would otherwise hold one lonely cottage."""

PROFILE_RECIPES = {
    "midrise_front": (("midrise_pair", 3.0), ("midrise_slab", 2.0), ("row_mid", 1.5)),
    "business": (("midrise_pair", 2.5), ("office_slab", 2.0), ("midrise_slab", 2.0)),
    "grid_rows": (("duo_low", 2.5), ("row_low", 2.0), ("court", 1.5)),
    "scar_rows": (("duo_mid", 2.5), ("midrise_pair", 1.5), ("duo_low", 1.5)),
    "garden_rows": (("court", 2.0), ("duo_low", 2.0), ("duo_mid", 1.0)),
    "meadow_courts": (("duo_low", 3.0), ("court", 1.5), ("single_low", 0.5)),
    "industrial": (("shed_pair", 2.0), ("shed", 2.0), ("office_slab", 1.0)),
    "port_yard": (("shed", 2.0), ("office_slab", 1.0)),
}
"""Which lot kinds each quarter profile draws from, with weights."""

INFILL_KINDS = {
    "midrise_front": ("midrise_point", "single_low"),
    "business": ("midrise_point", "single_low"),
    "scar_rows": ("midrise_point", "single_low"),
    "grid_rows": ("single_low",),
    "garden_rows": ("single_low",),
    "meadow_courts": ("single_low",),
    "industrial": ("single_low",),
    "port_yard": ("single_low",),
}
"""What fills a leftover slot, per profile.

In the quarters that carry the city's urban shoulder a narrow slot
becomes a POINT BLOCK, not a cottage: the leftover ground of a dense
quarter builds up, not down. Garden, meadow, and working quarters keep
their small in-fill -- their character is genuinely low."""

REAR_KINDS = {
    "midrise_front": "row_mid",
    "business": "office_slab",
    "grid_rows": "court",
    "scar_rows": "single_low",
    "garden_rows": "court",
    "meadow_courts": "single_low",
    "industrial": "shed",
    "port_yard": "shed",
}
"""The companion massing behind a placed frontage lot, per profile."""

FALLBACK_KINDS = {
    "midrise_front": ("midrise_slab", "row_mid", "midrise_pair", "midrise_point", "single_low"),
    "business": ("midrise_slab", "office_slab", "midrise_pair", "midrise_point", "single_low"),
    "grid_rows": ("row_low", "duo_low", "court", "single_low"),
    "scar_rows": ("row_mid", "duo_mid", "midrise_pair", "midrise_point", "single_low"),
    "garden_rows": ("court", "duo_low", "single_low"),
    "meadow_courts": ("row_low", "duo_low", "court", "single_low"),
    "industrial": ("shed_pair", "shed", "duo_low", "single_low"),
    "port_yard": ("shed", "office_slab", "duo_low", "single_low"),
}
"""Per-profile retry chain: the walk degrades gracefully through the
profile's own vocabulary before yielding a small in-fill mass."""

MIDRISE_THRESHOLD = 13.0
"""A mass at least this tall counts as the city's middle scale."""

INDUSTRIAL_KINDS = ("shed", "shed_pair")
"""Lot kinds counted as industrial fabric."""

HARBOR_LOT_CLEARANCE = 3.0
CONTAINER_STACK_PITCH = 6.4

STREET_TREE_ENVELOPE = 1.9
"""One street tree's canopy envelope radius (single trunk, small crown)."""

PARK_GROUP_SPREAD = (1.5, 2.2)
PARK_CANOPY_REACH = 1.8
"""A replanted park group's envelope: offsets spread plus widest canopy."""

INTERIOR_RINGS = ((0.30, 6, 0.0), (0.55, 8, 22.0), (0.78, 8, 0.0))
"""Interior block anchors per quarter: (radius factor, count, phase deg)."""


# ---------------------------------------------------------------------------
# Legacy clearing: the plan decides, the validator confirms
# ---------------------------------------------------------------------------


def plan_legacy_clearing(master_spec: dict, production_spec: dict, graph: dict) -> dict:
    """Decide which founding vegetation the redesigned city keeps.

    A founding cluster is PRESERVED exactly when the landscape plan gives it
    a park: every tree of the cluster stands inside one declared park zone
    AND genuinely clear of every designed street and junction (canopy
    envelope plus the keep margin). Everything else is CLEARED -- the city
    does not bend a single road around decoration; it re-landscapes
    deliberately after building.

    Returns ``{"kept": {...}, "removed": {...}, "removed_objects": [...]}``
    with per-cluster records; the Blender builder suppresses exactly
    ``removed_objects`` and the structural suite pins that set.
    """
    landscape = production_spec["landscape"]
    zones = landscape["park_zones"]
    margin = float(landscape["keep_margin"])
    production_segments = [
        (segment_id, segment)
        for segment_id, segment in sorted(graph["segments"].items())
        if not segment["existing"]
    ]
    pads = junction_pads(graph)
    kept: dict[int, dict] = {}
    removed: dict[int, dict] = {}
    for cluster_index, members in sorted(founding_grove_clusters(master_spec).items()):
        zone_id = None
        for candidate_zone in sorted(zones):
            zone = zones[candidate_zone]
            if all(
                math.hypot(tree["x"] - zone["center"][0], tree["y"] - zone["center"][1]) + tree["r"]
                <= zone["radius"]
                for tree in members
            ):
                zone_id = candidate_zone
                break
        clear = math.inf
        for _segment_id, segment in production_segments:
            occupancy = road_occupancy(segment)
            for tree in members:
                gap = (
                    distance_point_polyline((tree["x"], tree["y"]), segment["path"])
                    - occupancy
                    - tree["r"]
                )
                clear = min(clear, gap)
        for pad in pads:
            for tree in members:
                gap = math.hypot(tree["x"] - pad["x"], tree["y"] - pad["y"]) - pad["r"] - tree["r"]
                clear = min(clear, gap)
        record = {
            "cluster": cluster_index,
            "trees": len(members),
            "zone": zone_id,
            "street_gap": round(clear, 4),
        }
        if zone_id is not None and clear >= margin:
            kept[cluster_index] = record
        else:
            removed[cluster_index] = record
    return {
        "kept": kept,
        "removed": removed,
        "removed_objects": [f"LD_TREE__{index:02d}" for index in sorted(removed)],
    }


# ---------------------------------------------------------------------------
# Fixed truth registration
# ---------------------------------------------------------------------------


def _wall_lines(master_spec: dict) -> list[dict]:
    """Every wall-station line with its corridor and lot clearances.

    The scar (the long station) keeps its full exclusion corridor; the
    short station lines between the western districts are reserved
    alignments with a modest respect band.
    """
    walls = []
    for boundary_id, boundary in sorted(master_spec["boundaries"].items()):
        station = boundary["wall_station"]
        x, y = station["center"]
        dx, dy = station["direction"]
        length = math.hypot(dx, dy) or 1.0
        half = station["length"] / 2.0
        ux, uy = dx / length, dy / length
        is_scar = float(station["length"]) >= SCAR_STATION_LENGTH
        walls.append(
            {
                "id": boundary_id,
                "line": [(x - ux * half, y - uy * half), (x + ux * half, y + uy * half)],
                "corridor": SCAR_CORRIDOR_RADIUS if is_scar else STATION_CORRIDOR_RADIUS,
                "lot_clearance": SCAR_LOT_CLEARANCE if is_scar else STATION_LOT_CLEARANCE,
            }
        )
    return walls


def _founding_depots(master_spec: dict) -> list[tuple[float, float]]:
    """Every founding district's depot pad location (mirrors Phase 15)."""
    depots = []
    for district in master_spec["districts"].values():
        center_x, center_y = district["center"]
        length = math.hypot(center_x, center_y) or 1.0
        depots.append(
            (
                center_x + (center_x / length) * district["radius"] * 0.62,
                center_y + (center_y / length) * district["radius"] * 0.62,
            )
        )
    return depots


def ring_occupancy_paths(master_spec: dict, ground: dict, district_id: str) -> list[list[tuple]]:
    """The carriageway polylines a founding ring still contributes.

    A ring sector the final composition buries under the urban table is
    no longer a street: the production build suppresses the founding ring
    mesh and redraws the KEPT arcs, so only those arcs occupy ground. The
    plate itself stays fully protected -- burying a circle changes what
    the city looks like, never what may be built on the historic core.
    """
    return kept_ring_paths(master_spec, ground, district_id)


def build_occupancy(
    master_spec: dict, graph: dict, clearing: dict, ground: dict | None = None
) -> PlacementValidator:
    """Register everything that already exists before production planning.

    Class A first: plates (as PLATE ground -- buildings keep off, designed
    planting may stand on them), depots, the Seal plaza, the quay, water,
    and the wall corridors. Then Class B: the complete street network, its
    junction pads, and the PRESERVED founding groves (GROVE). Cleared
    clusters are not registered -- the plan removes their objects, so they
    occupy nothing.
    """
    validator = PlacementValidator()

    for district_id, district in sorted(master_spec["districts"].items()):
        validator.register(
            f"plate_{district_id}",
            "PLATE",
            [
                circle(
                    district["center"][0],
                    district["center"][1],
                    district["radius"] + PLATE_MARGIN,
                )
            ],
        )
    for index, (depot_x, depot_y) in enumerate(_founding_depots(master_spec)):
        validator.register(f"depot_{index}", "HISTORY", [circle(depot_x, depot_y, 9.0)])
    for index, building in enumerate(founding_building_lots(master_spec)):
        validator.register(
            f"founding_bldg_{index:02d}_{building['district']}",
            "HISTORY",
            [circle(building["x"], building["y"], building["r"])],
        )
    seal = master_spec["landmarks"]["golden_seal"]
    validator.register(
        "golden_seal_plaza",
        "HISTORY",
        [circle(seal["location"][0], seal["location"][1], seal["radius"] + 2.0)],
    )

    (port_x, port_y), (unit_x, unit_y), quay_distance = port_frame(master_spec)
    heading = math.atan2(unit_y, unit_x)
    water_s = quay_distance + 13.0
    validator.register(
        "harbor_water",
        "WATER",
        [
            rect(
                port_x + unit_x * water_s,
                port_y + unit_y * water_s,
                13.0,
                21.0,
                heading,
            )
        ],
    )
    validator.register(
        "harbor_quay",
        "HISTORY",
        [
            rect(
                port_x + unit_x * quay_distance,
                port_y + unit_y * quay_distance,
                2.6,
                21.5,
                heading,
            )
        ],
    )

    grove_clusters = founding_grove_clusters(master_spec)
    for cluster_index in sorted(clearing["kept"]):
        shapes = [circle(tree["x"], tree["y"], tree["r"]) for tree in grove_clusters[cluster_index]]
        validator.register(f"grove_{cluster_index:02d}", "GROVE", shapes)

    for wall in _wall_lines(master_spec):
        line = wall["line"]
        validator.register(
            f"wall_{wall['id']}",
            "WALL",
            [capsule(line[0][0], line[0][1], line[1][0], line[1][1], wall["corridor"])],
        )

    for segment_id, segment in sorted(graph["segments"].items()):
        district_id = segment_id.removeprefix("ring_")
        if ground is not None and district_id in ground.get("plates", {}):
            shapes = []
            for path in ring_occupancy_paths(master_spec, ground, district_id):
                shapes.extend(polyline_capsules(path, road_occupancy(segment)))
        else:
            shapes = polyline_capsules(segment["path"], road_occupancy(segment))
        validator.register(f"road_{segment_id}", "ROAD", shapes)
    for pad_index, pad in enumerate(junction_pads(graph)):
        validator.register(
            f"pad_{pad_index:02d}_{pad['kind']}",
            "JUNCTION",
            [circle(pad["x"], pad["y"], pad["r"])],
        )
    return validator


# ---------------------------------------------------------------------------
# Massing
# ---------------------------------------------------------------------------


def _pick_kind(profile: str, rng) -> str:
    """Deterministic weighted choice of a lot kind for one candidate."""
    recipe = PROFILE_RECIPES[profile]
    total = sum(weight for _kind, weight in recipe)
    roll = rng.random() * total
    for kind, weight in recipe:
        roll -= weight
        if roll <= 0.0:
            return kind
    return recipe[-1][0]


def _masses_for_kind(kind: str, height_scale: float, falloff: float, rng) -> list[dict]:
    """The concrete compound massing of one lot: explicit footprints."""
    spec = LOT_KINDS[kind]
    units = rng.randint(*spec["units"])
    depth = rng.uniform(*spec["d"])
    masses: list[dict] = []

    def mass(width: float, mass_depth: float, height: float, ox: float, oy: float) -> dict:
        return {
            "w": round(width, 4),
            "d": round(mass_depth, 4),
            "h": round(max(3.4, height * height_scale * falloff), 4),
            "ox": round(ox, 4),
            "oy": round(oy, 4),
        }

    if kind in (
        "row_low",
        "row_mid",
        "shed_pair",
        "court",
        "midrise_court",
        "duo_low",
        "duo_mid",
        "midrise_pair",
    ):
        widths = [rng.uniform(*spec["w"]) for _ in range(units)]
        heights = [rng.uniform(*spec["h"]) for _ in range(units)]
        total_width = sum(widths)
        cursor = -total_width / 2.0
        for width, height in zip(widths, heights, strict=True):
            masses.append(mass(width, depth, height, cursor + width / 2.0, 0.0))
            cursor += width
        if kind in ("court", "midrise_court"):
            wing_width = total_width * rng.uniform(0.5, 0.62)
            wing_height = min(heights) * rng.uniform(0.72, 0.9)
            masses.append(mass(wing_width, depth * 0.9, wing_height, 0.0, -(depth + 3.4)))
        return masses

    width = rng.uniform(*spec["w"])
    height = rng.uniform(*spec["h"])
    masses.append(mass(width, depth, height, 0.0, 0.0))
    return masses


def lot_extents(masses: list[dict]) -> tuple[float, float, float]:
    """(half width, front extent, back extent) of a compound lot."""
    half_w = max(abs(m["ox"]) + m["w"] / 2.0 for m in masses)
    front = max(m["oy"] + m["d"] / 2.0 for m in masses)
    back = max(-(m["oy"] - m["d"] / 2.0) for m in masses)
    return (half_w, front, back)


def lot_shapes(lot: dict) -> list[dict]:
    """World-space footprint rectangles for every mass of one lot."""
    cos_r, sin_r = math.cos(lot["rotation"]), math.sin(lot["rotation"])
    shapes = []
    for m in lot["masses"]:
        world_x = lot["x"] + m["ox"] * cos_r - m["oy"] * sin_r
        world_y = lot["y"] + m["ox"] * sin_r + m["oy"] * cos_r
        shapes.append(rect(world_x, world_y, m["w"] / 2.0, m["d"] / 2.0, lot["rotation"]))
    return shapes


def plinth_shape(lot: dict) -> dict:
    """The lot's ground plinth: footprint hull plus its skirt.

    The skirt is :data:`PLINTH_MARGIN` unless the lot carries a narrower
    ``plinth_margin`` of its own, which :func:`_fit_plinth_skirts` gives
    the handful of lots whose full skirt would otherwise reach into a
    carriageway. Trimming a slab's overhang is the cheapest honest way to
    keep a building out of the street: the mass does not move, the lot is
    not lost, and the ground under the road stops being claimed.
    """
    half_w, front, back = lot_extents(lot["masses"])
    center_off = (front - back) / 2.0
    cos_r, sin_r = math.cos(lot["rotation"]), math.sin(lot["rotation"])
    margin = float(lot.get("plinth_margin", PLINTH_MARGIN))
    return rect(
        lot["x"] - sin_r * center_off,
        lot["y"] + cos_r * center_off,
        half_w + margin,
        (front + back) / 2.0 + margin,
        lot["rotation"],
    )


PLINTH_MARGIN_FLOOR = 0.2
PLINTH_MARGIN_STEP = 0.05
"""How far a plinth skirt may be trimmed, and in what increments.

A skirt narrower than the floor stops reading as a base and starts
reading as a building with no footing, so a lot that would need less than
this keeps its full skirt and its overlap is published instead. The step
keeps the result a short, deterministic ladder rather than a solved
equation with a floating-point tail."""


def _fit_plinth_skirts(quarter_lots: dict[str, list[dict]], carriageways: list[dict]) -> int:
    """Narrow the few plinth skirts that would otherwise reach into a street.

    Runs after placement, because it is a property of where the lot ended
    up, and it changes nothing else about the lot: the masses, the
    rotation and the frontage are already decided and stay exactly as the
    ladder placed them. Only the slab's overhang shrinks, and only on lots
    that need it.

    Returns how many lots were trimmed.
    """
    trimmed = 0
    for neighborhood_id in sorted(quarter_lots):
        for lot in quarter_lots[neighborhood_id]:
            if plinth_carriageway_clearance(lot, carriageways) >= PLINTH_CARRIAGEWAY_CLEARANCE:
                continue
            margin = PLINTH_MARGIN
            while margin - PLINTH_MARGIN_STEP >= PLINTH_MARGIN_FLOOR:
                margin = round(margin - PLINTH_MARGIN_STEP, 4)
                candidate = {**lot, "plinth_margin": margin}
                if (
                    plinth_carriageway_clearance(candidate, carriageways)
                    >= PLINTH_CARRIAGEWAY_CLEARANCE
                ):
                    lot["plinth_margin"] = margin
                    trimmed += 1
                    break
    return trimmed


def carriageway_envelopes(master_spec: dict, graph: dict, ground: dict | None) -> list[dict]:
    """Every driveable surface in the city, with the clearance it demands.

    The CARRIAGEWAY half-widths (:data:`road_graph.ROAD_CLASS_WIDTHS`),
    not the wider occupancy envelope, plus every junction pad and
    turnaround bulb the network implies. Buried founding ring sectors are
    excluded exactly as the occupancy contract excludes them: a sector the
    final composition put under the urban table is no longer a street.

    Returns ``[{"shape", "kind"}]``; ``kind`` is ``"carriageway"`` for the
    surfaces a plinth is laddered away from and ``"pad"`` for the junction
    aprons it is only measured against (see :func:`plinth_pad_lap`).
    """
    envelopes: list[dict] = []
    for segment_id, segment in sorted(graph["segments"].items()):
        half = ROAD_CLASS_WIDTHS[segment["class"]] / 2.0
        district_id = segment_id.removeprefix("ring_")
        if ground is not None and district_id in ground.get("plates", {}):
            paths = ring_occupancy_paths(master_spec, ground, district_id)
        else:
            paths = [segment["path"]]
        for path in paths:
            envelopes.extend(
                {"shape": shape, "kind": "carriageway"} for shape in polyline_capsules(path, half)
            )
    for pad in junction_pads(graph):
        envelopes.append({"shape": circle(pad["x"], pad["y"], pad["r"]), "kind": "pad"})
    return envelopes


def plinth_carriageway_clearance(lot: dict, envelopes: list[dict]) -> float:
    """How far a lot's ground slab misses the nearest carriageway.

    Negative means the slab stands in the surface a vehicle drives on.
    """
    shape = plinth_shape(lot)
    return min(
        (
            signed_gap(shape, envelope["shape"])
            for envelope in envelopes
            if envelope["kind"] == "carriageway"
        ),
        default=math.inf,
    )


def plinth_pad_lap(lot: dict, envelopes: list[dict]) -> float:
    """How deep a lot's ground slab reaches into a junction apron, or 0.0.

    Junction-pad laps are MEASURED and published, never refused. A pad is
    an apron of ``carriageway/2 + 1.0`` drawn around a node, so its outer
    metre is margin rather than road, and a slab may lap into that margin
    without ever reaching a surface a vehicle drives on. Refusing them was
    tried and measured: it costs the composition an AUTHORED mid-rise
    block (``wallside_row``, three units) and takes the city's mid-rise
    shoulder from nine masses to five, because a block's position is a
    design decision with no set-back ladder to retreat along. Deleting
    real buildings to buy a slab's last 0.3m under an apron nobody can see
    is a bad trade, so :func:`audit_plan` publishes the laps and leaves
    the judgment visible instead of paying for it silently.
    """
    shape = plinth_shape(lot)
    deepest = max(
        (
            -signed_gap(shape, envelope["shape"])
            for envelope in envelopes
            if envelope["kind"] == "pad"
        ),
        default=0.0,
    )
    return max(0.0, deepest)


def plinth_is_clear(lot: dict, envelopes: list[dict]) -> bool:
    """True when a lot's ground slab stays out of every carriageway."""
    return plinth_carriageway_clearance(lot, envelopes) >= PLINTH_CARRIAGEWAY_CLEARANCE


def _plinth_first(rungs):
    """Walk a placement ladder twice: plinth-clear rungs first, then all.

    The plinth rule is a PREFERENCE, never a veto. Run as a veto it did
    not push the four offending lots back a rung as intended -- it deleted
    them, taking the city from eighteen lots to fourteen, because the
    ground behind each of them was claimed by something else. Trading four
    real buildings for an invisible sub-deck overlap is not a fix, so the
    ladder now takes the best rung whose slab is clear and, only if no
    rung offers one, takes the rung it would have taken anyway. A lot can
    therefore move to satisfy the rule but can never be lost to it, and
    the overlaps that survive are published by :func:`audit_plan` instead
    of being paid for in architecture.
    """
    ordered = list(rungs)
    for rung in ordered:
        yield True, rung
    for rung in ordered:
        yield False, rung


# ---------------------------------------------------------------------------
# Streets and stations
# ---------------------------------------------------------------------------


def _fine_stations(
    path: list[tuple[float, float]], step: float
) -> list[tuple[float, float, float, float]]:
    """(along, x, y, heading) stations at a fine fixed step (pure)."""
    stations: list[tuple[float, float, float, float]] = []
    carried = 0.0
    along = 0.0
    for (x0, y0), (x1, y1) in zip(path, path[1:], strict=False):
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length == 0.0:
            continue
        heading = math.atan2(dy, dx)
        distance = carried
        while distance <= length:
            t = distance / length
            stations.append((along + distance, x0 + dx * t, y0 + dy * t, heading))
            distance += step
        carried = distance - length
        along += length
    return stations


def _nearest_quarter(contexts: dict[str, dict], x: float, y: float) -> tuple[str, float]:
    """The quarter whose center is closest to a point (sorted tie-break)."""
    best_id = ""
    best_gap = math.inf
    for neighborhood_id in sorted(contexts):
        center = contexts[neighborhood_id]["center"]
        gap = math.hypot(x - center[0], y - center[1])
        if gap < best_gap:
            best_gap = gap
            best_id = neighborhood_id
    return best_id, best_gap


# ---------------------------------------------------------------------------
# Planning passes
# ---------------------------------------------------------------------------


def _segments_cross_2d(a, b, c, d) -> bool:
    """Proper interior crossing of two segments."""

    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    o1, o2 = orient(a, b, c), orient(a, b, d)
    o3, o4 = orient(c, d, a), orient(c, d, b)
    return o1 * o2 < 0 and o3 * o4 < 0


def _ray_clear(
    graph: dict,
    walls: list[dict],
    face: tuple[float, float],
    normal: tuple[float, float],
    center: tuple[float, float],
    own_id: str,
) -> bool:
    """True when nothing but open ground lies between street and lot.

    The ray from the frontage station to the lot center may cross no
    other street's centerline and no wall-station line -- fabric never
    tunnels into back pockets.
    """
    start = (face[0] + normal[0] * 1.0, face[1] + normal[1] * 1.0)
    for other_id, other in sorted(graph["segments"].items()):
        if other_id == own_id:
            continue
        path = other["path"]
        for leg_a, leg_b in zip(path, path[1:], strict=False):
            if _segments_cross_2d(start, center, leg_a, leg_b):
                return False
    for wall in walls:
        if _segments_cross_2d(start, center, wall["line"][0], wall["line"][1]):
            return False
    return True


BLOCK_UNIT_GAP = 0.3
"""Reveal between the units of one designed block: a terrace joint, not a
gap -- the block reads as a continuous street wall.

A block is ONE lot carrying several attached masses, exactly as the row
vocabulary already works, so its own units never fight each other for
clearance; the block competes with the CITY, not with itself."""

BLOCK_WING_SETBACK = 2.8
"""Open courtyard depth between a court block's front range and its wing."""

DEFAULT_BLOCK_PRIORITY = 50
"""Placement rank of an unranked block; lower is placed first.

The master plan says what matters most: the crescent that fronts the
orbital and the business axis claim their ground before an infill mews
does, so adding a minor block can never quietly displace a major one."""


def _plan_designed_blocks(
    master_spec: dict,
    production_spec: dict,
    graph: dict,
    contexts: dict[str, dict],
    quarter_lots: dict[str, list[dict]],
    validator: PlacementValidator,
    seed: str,
    fabric_limit: float,
    carriageways: list[dict],
) -> dict:
    """Place the AUTHORED urban blocks: the city's designed street walls.

    A block is city planning drawn by hand, exactly as every production
    street is: a frontage line, a depth, a unit count, and a height. This
    pass runs FIRST, before any sampled frontage, so the composition's
    deliberate rows, courts, corners, and mid-rise shoulder claim their
    ground before opportunistic fabric fills around them.

    Each unit is still an ordinary Class C candidate: the validator
    proves it, and a unit that conflicts is DROPPED and reported rather
    than nudged -- the planner designs, the validator confirms. The block
    record carries the placed and dropped counts so a design that does
    not fit is visible instead of silently thinned.
    """
    walls = _wall_lines(master_spec)
    quay_limit = port_frame(master_spec)[2] - HARBOR_LOT_CLEARANCE - 0.2
    tree_sides = _tree_lined_sides(production_spec)
    records: dict[str, dict] = {}
    ordered_blocks = sorted(
        production_spec["blocks"].items(),
        key=lambda item: (int(item[1].get("priority", DEFAULT_BLOCK_PRIORITY)), item[0]),
    )
    for block_id, block in ordered_blocks:
        street_id = block["street"]
        segment = graph["segments"][street_id]
        stations = _fine_stations(segment["path"], 0.5)
        side_label = block["side"]
        side = 1.0 if side_label == "i" else -1.0
        depth = float(block["depth"])
        units = int(block["units"])
        base_height = float(block["height"])
        step = float(block.get("step", 0.0))
        form = block["form"]
        front_gap = TREED_FRONT_GAP if side_label in tree_sides.get(street_id, set()) else FRONT_GAP
        setback = road_occupancy(segment) + front_gap + depth / 2.0
        span_from = float(block["from"])
        span_to = float(block["to"])
        run = span_to - span_from
        unit_run = run / units

        def station_at(along: float, path=stations) -> tuple[float, float, float, float]:
            return min(path, key=lambda entry: abs(entry[0] - along))

        placed = 0
        quarter_id = block.get("quarter")
        for prefer_clear_plinth, attempt_units in _plinth_first(range(units, 0, -1)):
            attempt_run = (span_to - span_from) * attempt_units / units
            attempt_to = span_from + attempt_run
            unit_run = attempt_run / attempt_units
            _sa, start_x, start_y, _sh = station_at(span_from)
            _ea, end_x, end_y, _eh = station_at(attempt_to)
            chord = (end_x - start_x, end_y - start_y)
            chord_length = math.hypot(*chord) or 1.0
            axis = (chord[0] / chord_length, chord[1] / chord_length)
            _ma, mid_x, mid_y, mid_heading = station_at((span_from + attempt_to) / 2.0)
            normal = (-math.sin(mid_heading) * side, math.cos(mid_heading) * side)
            rotation = math.atan2(normal[0], -normal[1])
            local_axis = (math.cos(rotation), math.sin(rotation))
            forward = 1.0 if (axis[0] * local_axis[0] + axis[1] * local_axis[1]) >= 0.0 else -1.0
            center = (mid_x + normal[0] * setback, mid_y + normal[1] * setback)
            width = max(2.0, unit_run - BLOCK_UNIT_GAP)
            masses = []
            for index in range(attempt_units):
                offset = (index + 0.5 - attempt_units / 2.0) * unit_run * forward
                rng = stable_rng(seed, "block", block_id, str(index))
                height = max(3.4, base_height + step * index + rng.uniform(-0.45, 0.45))
                masses.append(
                    {
                        "w": round(width, 4),
                        "d": round(depth, 4),
                        "h": round(height, 4),
                        "ox": round(offset, 4),
                        "oy": 0.0,
                    }
                )
                if form == "court" and index in (0, attempt_units - 1):
                    wing_depth = round(depth * 0.72, 4)
                    masses.append(
                        {
                            "w": round(width * 0.7, 4),
                            "d": wing_depth,
                            "h": round(max(3.4, height * 0.7), 4),
                            "ox": round(offset, 4),
                            "oy": round(-(depth / 2.0 + BLOCK_WING_SETBACK + wing_depth / 2.0), 4),
                        }
                    )
            if quarter_id is None:
                quarter_id = _nearest_quarter(contexts, center[0], center[1])[0]
            name_rng = stable_rng(seed, "blocklot", block_id)
            lot = {
                "name": f"{quarter_id}__blk_{block_id}",
                "kind": block["kind"],
                "x": round(center[0], 6),
                "y": round(center[1], 6),
                "rotation": round(rotation, 6),
                "face": (round(mid_x, 6), round(mid_y, 6)),
                "street_class": segment["class"],
                "masses": masses,
                "on_pad": True,
                "lit_salt": round(name_rng.random(), 6),
            }
            half_w, _front, _back = lot_extents(masses)
            if math.hypot(lot["x"], lot["y"]) + half_w > fabric_limit:
                continue
            if coast_coordinate((lot["x"], lot["y"]), master_spec) > quay_limit:
                continue
            if any(
                distance_point_polyline((lot["x"], lot["y"]), wall["line"]) < wall["lot_clearance"]
                for wall in walls
            ):
                continue
            if prefer_clear_plinth and not plinth_is_clear(lot, carriageways):
                continue
            if validator.place(f"lot_{lot['name']}", "BUILDING", lot_shapes(lot)):
                continue
            quarter_lots[quarter_id].append(lot)
            placed = attempt_units
            break
        if quarter_id is None:
            _ma, mid_x, mid_y, _mh = station_at((span_from + span_to) / 2.0)
            quarter_id = _nearest_quarter(contexts, mid_x, mid_y)[0]
        records[block_id] = {
            "quarter": quarter_id,
            "street": street_id,
            "side": side_label,
            "form": form,
            "kind": block["kind"],
            "units": units,
            "placed": placed,
            "dropped": units - placed,
            "height": round(base_height, 4),
        }
    return records


def _plan_front_runs(
    master_spec: dict,
    production_spec: dict,
    graph: dict,
    contexts: dict[str, dict],
    quarter_lots: dict[str, list[dict]],
    validator: PlacementValidator,
    seed: str,
    fabric_limit: float,
    carriageways: list[dict],
) -> None:
    """Designed street walls: continuous rows on declared frontage runs.

    The master plan names the runs where the city's middle scale stands
    -- the westfront crescent on the orbital, the business axis, the
    civic approach -- and this pass places that row deterministically,
    slab by slab, before the general walk fills anything else. This is
    massing as design, not as sampling: the street wall is a decision.
    """
    walls = _wall_lines(master_spec)
    quay_limit = port_frame(master_spec)[2] - HARBOR_LOT_CLEARANCE - 0.2
    for street_id, street in sorted(production_spec["streets"].items()):
        runs = street.get("front_runs")
        if not runs:
            continue
        segment = graph["segments"][street_id]
        occupancy = road_occupancy(segment)
        stations = _fine_stations(segment["path"], 1.0)
        tree_sides = _tree_lined_sides(production_spec).get(street_id, set())
        street_token = street_id
        for quarter_id in sorted(production_spec["neighborhoods"]):
            street_token = street_token.replace(f"_{quarter_id}", "")
        for run_index, run in enumerate(runs):
            side_label = run["side"]
            side = 1.0 if side_label == "i" else -1.0
            front_gap = TREED_FRONT_GAP if side_label in tree_sides else FRONT_GAP
            kind = run["kind"]
            cursor = float(run["range"][0])
            placed_count = 0
            slot = 0
            while cursor <= float(run["range"][1]) and placed_count < int(run["count"]):
                station = min(stations, key=lambda s: abs(s[0] - cursor))
                _along, x, y, heading = station
                normal = (-math.sin(heading) * side, math.cos(heading) * side)
                rotation = math.atan2(normal[0], -normal[1])
                neighborhood_id, station_reach = _nearest_quarter(contexts, x, y)
                neighborhood = production_spec["neighborhoods"][neighborhood_id]
                height_scale = float(neighborhood["height_scale"])
                radius = contexts[neighborhood_id]["radius"]
                falloff = 1.0 - 0.2 * min(1.0, station_reach / (radius + CORE_FALLOFF_REACH))
                advance = 3.0
                for prefer_clear_plinth, push in _plinth_first((0.0, 1.2, 2.6)):
                    rng = stable_rng(
                        seed,
                        "frontrun",
                        street_id,
                        side_label,
                        str(run_index),
                        str(slot),
                        str(push),
                    )
                    masses = _masses_for_kind(kind, height_scale, falloff, rng)
                    half_w, front, _back = lot_extents(masses)
                    offset = occupancy + front_gap + push + front
                    lot_x = x + normal[0] * offset
                    lot_y = y + normal[1] * offset
                    if math.hypot(lot_x, lot_y) + half_w > fabric_limit:
                        continue
                    if coast_coordinate((lot_x, lot_y), master_spec) > quay_limit:
                        continue
                    if any(
                        distance_point_polyline((lot_x, lot_y), wall["line"])
                        < wall["lot_clearance"]
                        for wall in walls
                    ):
                        continue
                    if not _ray_clear(graph, walls, (x, y), normal, (lot_x, lot_y), street_id):
                        break
                    lot = {
                        "name": (
                            f"{neighborhood_id}__fr_{street_token}"
                            f"{run_index}_{side_label}{slot:02d}"
                        ),
                        "kind": kind,
                        "x": round(lot_x, 6),
                        "y": round(lot_y, 6),
                        "rotation": round(rotation, 6),
                        "face": (round(x, 6), round(y, 6)),
                        "street_class": segment["class"],
                        "masses": masses,
                        "on_pad": station_reach <= radius,
                        "lit_salt": round(rng.random(), 6),
                    }
                    if prefer_clear_plinth and not plinth_is_clear(lot, carriageways):
                        continue
                    if validator.place(f"lot_{lot['name']}", "BUILDING", lot_shapes(lot)):
                        continue
                    quarter_lots[neighborhood_id].append(lot)
                    placed_count += 1
                    advance = 2.0 * half_w + 2.4
                    break
                cursor += advance
                slot += 1


def _tree_lined_sides(production_spec: dict) -> dict[str, set[str]]:
    """Which walk sides of which streets carry a formal tree line."""
    sides: dict[str, set[str]] = {}
    for street_id, street in production_spec["streets"].items():
        declared = street.get("trees")
        if declared == "both":
            sides[street_id] = {"i", "o"}
        elif declared == "left":
            sides[street_id] = {"i"}
        elif declared == "right":
            sides[street_id] = {"o"}
    return sides


def _yard_streets(production_spec: dict) -> set[str]:
    """Service lanes whose flanks belong to container rows, not lots."""
    return {
        neighborhood["yard_street"]
        for neighborhood in production_spec["neighborhoods"].values()
        if neighborhood.get("yard_street")
    }


def _plan_all_lots(
    master_spec: dict,
    production_spec: dict,
    graph: dict,
    contexts: dict[str, dict],
    quarter_lots: dict[str, list[dict]],
    validator: PlacementValidator,
    seed: str,
    fabric_limit: float,
    carriageways: list[dict],
) -> None:
    """Street-fronting compound lots along EVERY production street.

    The city hugs its streets: each production segment is walked on both
    sides along its whole length, and every station belongs to its nearest
    quarter -- which supplies the massing profile, the height scale, and
    the ownership. Quarters are fields of influence, not fences, so
    corridors between them carry continuous fabric instead of empty
    causeway.

    The walk is CITYWIDE compound-first: every street's compound sweep
    (with its second-row companions) runs before any street receives
    small in-fill, so the big masses claim the prime frontage and the
    singles genuinely fill gaps. Within each sweep, quarter cores fill
    before corridor halos. A candidate that conflicts steps back from the
    street in a deterministic ladder, then falls back through its
    profile's own vocabulary, then yields the ground. Tree-lined sides
    push the facade back so the formal tree line fits; yard lanes keep
    their flanks for the container rows; and the ray between a lot and
    its frontage station may cross no other street and no wall alignment
    -- fabric never tunnels into back pockets.
    """
    tree_sides = _tree_lined_sides(production_spec)
    yard_streets = _yard_streets(production_spec)
    walls = _wall_lines(master_spec)
    quay_limit = port_frame(master_spec)[2] - HARBOR_LOT_CLEARANCE - 0.2
    all_streets = sorted(graph["segments"].items())

    def _segments_cross(a, b, c, d) -> bool:
        def orient(p, q, r):
            return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

        o1, o2 = orient(a, b, c), orient(a, b, d)
        o3, o4 = orient(c, d, a), orient(c, d, b)
        return o1 * o2 < 0 and o3 * o4 < 0

    def fronts_own_street(
        face: tuple[float, float],
        normal: tuple[float, float],
        center: tuple[float, float],
        own_id: str,
    ) -> bool:
        """True when nothing but open ground lies between street and lot."""
        start = (face[0] + normal[0] * 1.0, face[1] + normal[1] * 1.0)
        for other_id, other in all_streets:
            if other_id == own_id:
                continue
            path = other["path"]
            for leg_a, leg_b in zip(path, path[1:], strict=False):
                if _segments_cross(start, center, leg_a, leg_b):
                    return False
        for wall in walls:
            if _segments_cross(start, center, wall["line"][0], wall["line"][1]):
                return False
        return True

    def try_lot(
        sweep: str,
        segment_id: str,
        segment: dict,
        side_label: str,
        station_index: int,
        station: tuple[float, float, float, float],
        kinds: list[str],
        front_gap: float,
    ) -> tuple[dict, float, float] | None:
        """Run the push-back ladder for one station; place at most one lot.

        The lot id carries the SWEEP as well as the station, because both
        sweeps walk the same stations: without it the in-fill pass could
        offer a lot under an id the compound pass already placed, and the
        validator's self-exemption would hide the overlap.
        """
        _along, x, y, heading = station
        side = 1.0 if side_label == "i" else -1.0
        neighborhood_id, station_reach = _nearest_quarter(contexts, x, y)
        neighborhood = production_spec["neighborhoods"][neighborhood_id]
        height_scale = float(neighborhood["height_scale"])
        radius = contexts[neighborhood_id]["radius"]
        falloff = 1.0 - 0.25 * min(1.0, station_reach / (radius + CORE_FALLOFF_REACH))
        normal = (-math.sin(heading) * side, math.cos(heading) * side)
        rotation = math.atan2(normal[0], -normal[1])
        street_token = segment_id
        for quarter_id in sorted(contexts):
            street_token = street_token.replace(f"_{quarter_id}", "")
        for prefer_clear_plinth in (True, False):
            for kind in kinds:
                for push_index, push in enumerate((0.0, 1.2, 2.6, 4.2, 6.2, 8.4)):
                    attempt_rng = stable_rng(
                        seed,
                        neighborhood_id,
                        "mass",
                        segment_id,
                        side_label,
                        str(station_index),
                        kind,
                        str(push_index),
                    )
                    masses = _masses_for_kind(kind, height_scale, falloff, attempt_rng)
                    half_w, front, _back = lot_extents(masses)
                    offset = road_occupancy(segment) + front_gap + push + front
                    lot_x = x + normal[0] * offset
                    lot_y = y + normal[1] * offset
                    if math.hypot(lot_x, lot_y) + half_w > fabric_limit:
                        continue
                    if coast_coordinate((lot_x, lot_y), master_spec) > quay_limit:
                        continue
                    if any(
                        distance_point_polyline((lot_x, lot_y), wall["line"])
                        < wall["lot_clearance"]
                        for wall in walls
                    ):
                        continue
                    if not fronts_own_street((x, y), normal, (lot_x, lot_y), segment_id):
                        break
                    lot = {
                        "name": (
                            f"{neighborhood_id}__{street_token}__"
                            f"{sweep[0]}{side_label}{station_index:03d}"
                        ),
                        "kind": kind,
                        "x": round(lot_x, 6),
                        "y": round(lot_y, 6),
                        "rotation": round(rotation, 6),
                        "face": (round(x, 6), round(y, 6)),
                        "street_class": segment["class"],
                        "masses": masses,
                        "on_pad": station_reach <= radius,
                        "lit_salt": 0.0,
                    }
                    if prefer_clear_plinth and not plinth_is_clear(lot, carriageways):
                        continue
                    if validator.place(f"lot_{lot['name']}", "BUILDING", lot_shapes(lot)):
                        continue
                    return (lot, half_w, falloff)
        return None

    def try_rear(
        lot: dict,
        segment_id: str,
        segment: dict,
        side_label: str,
        station_index: int,
        profile: str,
        height_scale: float,
        falloff: float,
        normal: tuple[float, float],
    ) -> dict | None:
        """A second-row companion behind a placed frontage lot."""
        neighborhood_id = lot["name"].split("__", 1)[0]
        rear_pick_rng = stable_rng(
            seed, neighborhood_id, "rearpick", segment_id, side_label, str(station_index)
        )
        rear_kinds = [_pick_kind(profile, rear_pick_rng)]
        for rear_fallback in (REAR_KINDS[profile], "single_low"):
            if rear_fallback not in rear_kinds:
                rear_kinds.append(rear_fallback)
        _lw, _lf, lot_back = lot_extents(lot["masses"])
        for prefer_clear_plinth, rear_kind in _plinth_first(rear_kinds):
            rear_rng = stable_rng(
                seed,
                neighborhood_id,
                "rear",
                segment_id,
                side_label,
                str(station_index),
                rear_kind,
            )
            rear_masses = _masses_for_kind(rear_kind, height_scale, falloff * 0.92, rear_rng)
            _rw, rear_front, _rb = lot_extents(rear_masses)
            rear_offset = lot_back + 2.6 + rear_front
            rear = {
                "name": lot["name"] + "r",
                "kind": rear_kind,
                "x": round(lot["x"] + normal[0] * rear_offset, 6),
                "y": round(lot["y"] + normal[1] * rear_offset, 6),
                "rotation": lot["rotation"],
                "face": lot["face"],
                "street_class": segment["class"],
                "masses": rear_masses,
                "on_pad": lot["on_pad"],
                "lit_salt": round(rear_rng.random(), 6),
            }
            rear_clear = (
                math.hypot(rear["x"], rear["y"]) <= fabric_limit
                and coast_coordinate((rear["x"], rear["y"]), master_spec) <= quay_limit
                and all(
                    distance_point_polyline((rear["x"], rear["y"]), wall["line"])
                    >= wall["lot_clearance"]
                    for wall in walls
                )
                and fronts_own_street(lot["face"], normal, (rear["x"], rear["y"]), segment_id)
                and (not prefer_clear_plinth or plinth_is_clear(rear, carriageways))
            )
            if rear_clear and not (
                validator.place(f"lot_{rear['name']}", "BUILDING", lot_shapes(rear))
            ):
                return rear
        return None

    for sweep in ("compound", "infill"):
        for band in ("core", "corridor"):
            for segment_id, segment in sorted(graph["segments"].items()):
                if segment["existing"] or segment_id in yard_streets:
                    continue
                stations = _fine_stations(segment["path"], SCAN_STEP)
                for side_label in ("i", "o"):
                    front_gap = (
                        TREED_FRONT_GAP
                        if side_label in tree_sides.get(segment_id, set())
                        else FRONT_GAP
                    )
                    next_at = 2.0
                    for station_index, station in enumerate(stations):
                        along, x, y, heading = station
                        if along < next_at:
                            continue
                        neighborhood_id, station_reach = _nearest_quarter(contexts, x, y)
                        context = contexts[neighborhood_id]
                        radius = context["radius"]
                        if band == "core":
                            if station_reach > radius:
                                continue
                        elif station_reach <= radius:
                            continue
                        lots = quarter_lots[neighborhood_id]
                        if sum(len(lot["masses"]) for lot in lots) >= context["mass_cap"]:
                            continue
                        neighborhood = production_spec["neighborhoods"][neighborhood_id]
                        profile = neighborhood["profile"]
                        height_scale = float(neighborhood["height_scale"])
                        rng = stable_rng(
                            seed,
                            neighborhood_id,
                            "lot",
                            segment_id,
                            side_label,
                            str(station_index),
                        )
                        primary_kind = _pick_kind(profile, rng)
                        lit_salt = round(rng.random(), 6)
                        gap_after = rng.uniform(1.0, 1.9)
                        if sweep == "compound":
                            kinds = [primary_kind]
                            for fallback in FALLBACK_KINDS[profile]:
                                if fallback not in kinds and fallback != "single_low":
                                    kinds.append(fallback)
                            kinds = [kind for kind in kinds if kind != "single_low"]
                            if not kinds:
                                continue
                        else:
                            kinds = list(INFILL_KINDS[profile])
                        placed = try_lot(
                            sweep,
                            segment_id,
                            segment,
                            side_label,
                            station_index,
                            station,
                            kinds,
                            front_gap,
                        )
                        if placed is None:
                            continue
                        lot, half_w, falloff = placed
                        lot["lit_salt"] = lit_salt
                        lots.append(lot)
                        next_at = along + 2.0 * half_w + gap_after
                        if sweep == "infill":
                            continue
                        side = 1.0 if side_label == "i" else -1.0
                        normal = (-math.sin(heading) * side, math.cos(heading) * side)
                        rear = try_rear(
                            lot,
                            segment_id,
                            segment,
                            side_label,
                            station_index,
                            profile,
                            height_scale,
                            falloff,
                            normal,
                        )
                        if rear is not None:
                            lots.append(rear)


def _plan_interior_lots(
    master_spec: dict,
    production_spec: dict,
    graph: dict,
    contexts: dict[str, dict],
    quarter_lots: dict[str, list[dict]],
    validator: PlacementValidator,
    seed: str,
    fabric_limit: float,
    carriageways: list[dict],
) -> None:
    """Interior block fabric on deterministic anchors, validator-proven."""
    walls = _wall_lines(master_spec)
    quay_limit = port_frame(master_spec)[2] - HARBOR_LOT_CLEARANCE - 0.2
    production_segments = [
        (segment_id, segment)
        for segment_id, segment in sorted(graph["segments"].items())
        if not segment["existing"]
    ]
    for neighborhood_id, neighborhood in sorted(production_spec["neighborhoods"].items()):
        context = contexts[neighborhood_id]
        center = context["center"]
        radius = context["radius"]
        lots = quarter_lots[neighborhood_id]
        profile = neighborhood["profile"]
        height_scale = float(neighborhood["height_scale"])
        for ring_index, (factor, count, phase_deg) in enumerate(INTERIOR_RINGS):
            for slot in range(count):
                if sum(len(lot["masses"]) for lot in lots) >= context["mass_cap"]:
                    break
                angle = math.radians(phase_deg) + 2.0 * math.pi * slot / count
                anchor_x = center[0] + factor * radius * math.cos(angle)
                anchor_y = center[1] + factor * radius * math.sin(angle)
                best_gap = math.inf
                best_foot = (anchor_x, anchor_y)
                for _segment_id, segment in production_segments:
                    for (ax, ay), (bx, by) in zip(
                        segment["path"], segment["path"][1:], strict=False
                    ):
                        dx, dy = bx - ax, by - ay
                        length_squared = dx * dx + dy * dy
                        if length_squared == 0.0:
                            continue
                        t = max(
                            0.0,
                            min(
                                1.0,
                                ((anchor_x - ax) * dx + (anchor_y - ay) * dy) / length_squared,
                            ),
                        )
                        foot = (ax + dx * t, ay + dy * t)
                        gap = math.hypot(anchor_x - foot[0], anchor_y - foot[1])
                        if gap < best_gap:
                            best_gap, best_foot = gap, foot
                toward = (best_foot[0] - anchor_x, best_foot[1] - anchor_y)
                length = math.hypot(*toward) or 1.0
                facing = (toward[0] / length, toward[1] / length)
                rotation = math.atan2(-facing[0], facing[1])
                rng = stable_rng(seed, neighborhood_id, "interior", str(ring_index), str(slot))
                primary_kind = _pick_kind(profile, rng)
                lit_salt = round(rng.random(), 6)
                falloff = 1.0 - 0.25 * factor
                kinds = [primary_kind]
                if primary_kind != "single_low":
                    kinds.append("single_low")
                for prefer_clear_plinth, kind in _plinth_first(kinds):
                    attempt_rng = stable_rng(
                        seed,
                        neighborhood_id,
                        "interior_mass",
                        str(ring_index),
                        str(slot),
                        kind,
                    )
                    masses = _masses_for_kind(kind, height_scale, falloff, attempt_rng)
                    half_w, _front, _back = lot_extents(masses)
                    if math.hypot(anchor_x, anchor_y) + half_w > fabric_limit:
                        continue
                    if coast_coordinate((anchor_x, anchor_y), master_spec) > quay_limit:
                        continue
                    if any(
                        distance_point_polyline((anchor_x, anchor_y), wall["line"])
                        < wall["lot_clearance"]
                        for wall in walls
                    ):
                        continue
                    lot = {
                        "name": f"{neighborhood_id}__blk_r{ring_index}s{slot:02d}",
                        "kind": kind,
                        "x": round(anchor_x, 6),
                        "y": round(anchor_y, 6),
                        "rotation": round(rotation, 6),
                        "face": (round(best_foot[0], 6), round(best_foot[1], 6)),
                        "street_class": "interior",
                        "masses": masses,
                        "on_pad": True,
                        "lit_salt": lit_salt,
                    }
                    if prefer_clear_plinth and not plinth_is_clear(lot, carriageways):
                        continue
                    if validator.place(f"lot_{lot['name']}", "BUILDING", lot_shapes(lot)):
                        continue
                    lots.append(lot)
                    break


def _plan_yard_rows(
    neighborhood_id: str,
    neighborhood: dict,
    graph: dict,
    context: dict,
    validator: PlacementValidator,
    seed: str,
) -> list[dict]:
    """Container stack rows along a yard quarter's declared service lane."""
    street_id = neighborhood.get("yard_street")
    segment = graph["segments"].get(street_id) if street_id else None
    if segment is None:
        return []
    occupancy = road_occupancy(segment)
    rows: list[dict] = []
    stations = _fine_stations(segment["path"], 5.6)
    for side_label, side in (("i", 1.0), ("o", -1.0)):
        for station_index, (_along, x, y, heading) in enumerate(stations):
            normal = (-math.sin(heading) * side, math.cos(heading) * side)
            offset = occupancy + 1.4 + 1.35
            row_x = x + normal[0] * offset
            row_y = y + normal[1] * offset
            if math.hypot(row_x, row_y) > context["fabric_limit"] - 3.0:
                continue
            rng = stable_rng(
                seed, neighborhood_id, "stack", street_id, side_label, str(station_index)
            )
            row = {
                "name": f"{neighborhood_id}__stack_{side_label}{station_index:02d}",
                "x": round(row_x, 6),
                "y": round(row_y, 6),
                "heading": round(heading, 6),
                "tiers": rng.randint(1, 3),
                "length": round(rng.uniform(3.4, 4.6), 6),
            }
            shape = rect(row_x, row_y, row["length"] / 2.0 + 0.3, 1.35, heading)
            if validator.place(f"stack_{row['name']}", "BUILDING", [shape]):
                continue
            rows.append(row)
    return rows


def _plan_plaza(
    neighborhood_id: str,
    neighborhood: dict,
    validator: PlacementValidator,
) -> dict | None:
    """One civic plaza per anchored quarter, at its DESIGNED anchor point."""
    if neighborhood.get("anchor", "none") != "plaza":
        return None
    anchor = neighborhood.get("plaza_anchor")
    if anchor is None:
        return None
    plaza_center = (float(anchor[0]), float(anchor[1]))
    for factor in (1.0, 0.82):
        plaza_radius = round(float(anchor[2]) * factor, 6)
        shape = circle(plaza_center[0], plaza_center[1], plaza_radius)
        if not validator.place(f"plaza_{neighborhood_id}", "PLAZA", [shape]):
            return {
                "center": (round(plaza_center[0], 6), round(plaza_center[1], 6)),
                "radius": plaza_radius,
            }
    return None


# ---------------------------------------------------------------------------
# Landscape: planted last, with an urban reason for every tree
# ---------------------------------------------------------------------------


def _place_green(
    greens: list[dict],
    validator: PlacementValidator,
    contexts: dict[str, dict],
    name: str,
    role: str,
    x: float,
    y: float,
    trees: int,
    spread: float,
    envelope: float,
) -> None:
    """Validate one planting; on success, file it under its nearest quarter."""
    if validator.place(f"green_{name}", "VEGETATION", [circle(x, y, envelope)]):
        return
    neighborhood_id, _reach = _nearest_quarter(contexts, x, y)
    greens.append(
        {
            "name": f"{neighborhood_id}__{name}",
            "quarter": neighborhood_id,
            "role": role,
            "x": round(x, 6),
            "y": round(y, 6),
            "trees": trees,
            "spread": round(spread, 4),
            "envelope": round(envelope, 4),
        }
    )


def _plan_street_trees(
    production_spec: dict,
    graph: dict,
    contexts: dict[str, dict],
    greens: list[dict],
    validator: PlacementValidator,
    seed: str,
    fabric_limit: float,
) -> None:
    """Formal street tree lines along the boulevards the design declares.

    Deterministic near-regular spacing with a small jitter -- landscaping,
    not a random scatter. Each tree is one validated envelope; stations the
    city has already claimed are simply not planted.
    """
    settings = production_spec["landscape"]["street_trees"]
    spacing = float(settings["spacing"])
    setback = float(settings["setback"])
    for street_id, street in sorted(production_spec["streets"].items()):
        sides_key = street.get("trees")
        if sides_key is None:
            continue
        segment = graph["segments"].get(street_id)
        if segment is None:
            continue
        occupancy = road_occupancy(segment)
        sides = (1.0, -1.0) if sides_key == "both" else ((1.0,) if sides_key == "left" else (-1.0,))
        stations = _fine_stations(segment["path"], spacing)
        for side in sides:
            side_label = "l" if side > 0 else "r"
            for station_index, (_along, x, y, heading) in enumerate(stations):
                rng = stable_rng(seed, "streettree", street_id, side_label, str(station_index))
                jitter = rng.uniform(-0.9, 0.9)
                normal = (-math.sin(heading) * side, math.cos(heading) * side)
                tangent = (math.cos(heading), math.sin(heading))
                offset = occupancy + setback + STREET_TREE_ENVELOPE
                tree_x = x + normal[0] * offset + tangent[0] * jitter
                tree_y = y + normal[1] * offset + tangent[1] * jitter
                if math.hypot(tree_x, tree_y) > fabric_limit + 1.0:
                    continue
                _place_green(
                    greens,
                    validator,
                    contexts,
                    f"st_{street_id}_{side_label}{station_index:03d}",
                    "street",
                    tree_x,
                    tree_y,
                    1,
                    0.0,
                    STREET_TREE_ENVELOPE,
                )


def _plan_park_replants(
    production_spec: dict,
    contexts: dict[str, dict],
    greens: list[dict],
    validator: PlacementValidator,
    seed: str,
    fabric_limit: float,
) -> None:
    """Deliberate new groups inside every declared park zone.

    Preserved founding groves anchor the parks; these replants fill them
    out so cleared land reads as designed parkland, not leftover ground.
    """
    landscape = production_spec["landscape"]
    replant = landscape["park_replants"]
    groups = int(replant["groups_per_zone"])
    min_trees = int(replant["min_trees"])
    max_trees = int(replant["max_trees"])
    for zone_id, zone in sorted(landscape["park_zones"].items()):
        center = zone["center"]
        radius = float(zone["radius"])
        for group_index in range(groups):
            rng = stable_rng(seed, "parkgroup", zone_id, str(group_index))
            angle = rng.uniform(0.0, 2.0 * math.pi)
            reach = math.sqrt(rng.uniform(0.05, 0.8)) * max(radius - 2.4, 1.0)
            x = center[0] + reach * math.cos(angle)
            y = center[1] + reach * math.sin(angle)
            spread = rng.uniform(*PARK_GROUP_SPREAD)
            envelope = spread + PARK_CANOPY_REACH
            if math.hypot(x, y) + envelope > fabric_limit:
                continue
            _place_green(
                greens,
                validator,
                contexts,
                f"park_{zone_id}_{group_index}",
                "park",
                x,
                y,
                rng.randint(min_trees, max_trees),
                spread,
                envelope,
            )


def _plan_courtyard_trees(
    contexts: dict[str, dict],
    quarter_lots: dict[str, list[dict]],
    greens: list[dict],
    validator: PlacementValidator,
    seed: str,
) -> None:
    """One tree in every courtyard gap that validates."""
    for neighborhood_id in sorted(quarter_lots):
        for lot in quarter_lots[neighborhood_id]:
            if lot["kind"] not in ("court", "midrise_court"):
                continue
            depth = lot["masses"][0]["d"]
            court_y = -(depth / 2.0 + 1.7)
            cos_r, sin_r = math.cos(lot["rotation"]), math.sin(lot["rotation"])
            x = lot["x"] - court_y * sin_r
            y = lot["y"] + court_y * cos_r
            rng = stable_rng(seed, "courttree", lot["name"])
            _place_green(
                greens,
                validator,
                contexts,
                f"court_{lot['name'][-10:]}",
                "courtyard",
                x,
                y,
                1,
                0.0,
                rng.uniform(1.5, 1.8),
            )


def _plan_promenade(
    master_spec: dict,
    production_spec: dict,
    contexts: dict[str, dict],
    greens: list[dict],
    validator: PlacementValidator,
    seed: str,
) -> None:
    """A waterfront tree line on the land side of the quay."""
    promenade = production_spec["landscape"]["promenade"]
    count = int(promenade["count"])
    setback = float(promenade["setback"])
    (port_x, port_y), (unit_x, unit_y), quay_distance = port_frame(master_spec)
    lateral = (-unit_y, unit_x)
    along = quay_distance - setback
    base = (port_x + unit_x * along, port_y + unit_y * along)
    span = 19.0
    for slot in range(count):
        t = -span + (2.0 * span) * slot / max(count - 1, 1)
        rng = stable_rng(seed, "promenade", str(slot))
        jitter = rng.uniform(-0.7, 0.7)
        x = base[0] + lateral[0] * (t + jitter)
        y = base[1] + lateral[1] * (t + jitter)
        _place_green(
            greens,
            validator,
            contexts,
            f"prom_{slot:02d}",
            "promenade",
            x,
            y,
            1,
            0.0,
            STREET_TREE_ENVELOPE,
        )


def _plan_plaza_trees(
    contexts: dict[str, dict],
    plazas: dict[str, dict | None],
    greens: list[dict],
    validator: PlacementValidator,
    seed: str,
) -> None:
    """A formal square of trees around each production plaza."""
    for neighborhood_id in sorted(plazas):
        plaza = plazas[neighborhood_id]
        if plaza is None:
            continue
        for slot in range(4):
            angle = math.pi / 4.0 + slot * math.pi / 2.0
            reach = plaza["radius"] + 2.6
            x = plaza["center"][0] + reach * math.cos(angle)
            y = plaza["center"][1] + reach * math.sin(angle)
            rng = stable_rng(seed, "plazatree", neighborhood_id, str(slot))
            _place_green(
                greens,
                validator,
                contexts,
                f"plaza_{neighborhood_id}_{slot}",
                "plaza",
                x,
                y,
                1,
                0.0,
                rng.uniform(1.5, 1.8),
            )


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def plan_urban_fabric(master_spec: dict, production_spec: dict, graph: dict) -> dict:
    """Compute the full production fabric plan against the occupancy contract.

    Returns ``{"neighborhoods": {...}, "legacy": {...}, "spatial": {...},
    "summary": {...}}``; the ``legacy`` block is the deterministic clearing
    decision (which founding groves the city preserves), and the
    ``spatial`` block carries the validator's audit counts and refusal
    diagnostics -- the numbers the manifest reports come from here.
    """
    seed = production_spec["visual_seed"]
    clearing = plan_legacy_clearing(master_spec, production_spec, graph)
    ground = plan_city_ground(master_spec, production_spec, graph)
    validator = build_occupancy(master_spec, graph, clearing, ground)
    plan: dict = {"neighborhoods": {}, "legacy": clearing, "ground": ground}

    contexts: dict[str, dict] = {}
    quarter_lots: dict[str, list[dict]] = {}
    plazas: dict[str, dict | None] = {}
    ordered = sorted(production_spec["neighborhoods"].items())
    for neighborhood_id, neighborhood in ordered:
        radius = float(neighborhood["radius"])
        contexts[neighborhood_id] = {
            "center": (float(neighborhood["center"][0]), float(neighborhood["center"][1])),
            "radius": radius,
            "mass_cap": int(radius * 3.2) + 10,
            "fabric_limit": float(production_spec["fabric_limit_radius"]),
        }
        quarter_lots[neighborhood_id] = []
    for neighborhood_id, neighborhood in ordered:
        plazas[neighborhood_id] = _plan_plaza(neighborhood_id, neighborhood, validator)
    fabric_limit = float(production_spec["fabric_limit_radius"])
    carriageways = carriageway_envelopes(master_spec, graph, ground)
    blocks = _plan_designed_blocks(
        master_spec,
        production_spec,
        graph,
        contexts,
        quarter_lots,
        validator,
        seed,
        fabric_limit,
        carriageways,
    )
    _plan_front_runs(
        master_spec,
        production_spec,
        graph,
        contexts,
        quarter_lots,
        validator,
        seed,
        fabric_limit,
        carriageways,
    )
    _plan_all_lots(
        master_spec,
        production_spec,
        graph,
        contexts,
        quarter_lots,
        validator,
        seed,
        fabric_limit,
        carriageways,
    )
    _plan_interior_lots(
        master_spec,
        production_spec,
        graph,
        contexts,
        quarter_lots,
        validator,
        seed,
        fabric_limit,
        carriageways,
    )
    _fit_plinth_skirts(quarter_lots, carriageways)
    yard_rows: dict[str, list[dict]] = {}
    for neighborhood_id, neighborhood in ordered:
        yard_rows[neighborhood_id] = _plan_yard_rows(
            neighborhood_id,
            neighborhood,
            graph,
            contexts[neighborhood_id],
            validator,
            seed,
        )

    greens: list[dict] = []
    _plan_street_trees(production_spec, graph, contexts, greens, validator, seed, fabric_limit)
    _plan_park_replants(production_spec, contexts, greens, validator, seed, fabric_limit)
    _plan_courtyard_trees(contexts, quarter_lots, greens, validator, seed)
    _plan_promenade(master_spec, production_spec, contexts, greens, validator, seed)
    _plan_plaza_trees(contexts, plazas, greens, validator, seed)

    for neighborhood_id, neighborhood in ordered:
        entry_greens = [green for green in greens if green["quarter"] == neighborhood_id]
        elevation = float(neighborhood["elevation"])
        quarter_top = round(PLINTH_TOP + elevation, 4)
        for lot in quarter_lots[neighborhood_id]:
            beneath = ground_level_at((lot["x"], lot["y"]), ground)
            lot["plinth_top"] = round(max(quarter_top, beneath + PLINTH_LIP), 4)
        for green in entry_greens:
            green["base"] = round(ground_level_at((green["x"], green["y"]), ground), 4)
        for row in yard_rows[neighborhood_id]:
            beneath = ground_level_at((row["x"], row["y"]), ground)
            row["base"] = round(max(quarter_top, beneath + PLINTH_LIP), 4)
        plaza = plazas[neighborhood_id]
        if plaza is not None:
            beneath = ground_level_at(plaza["center"], ground)
            plaza["base"] = round(max(quarter_top, beneath + PLINTH_LIP), 4)
        plan["neighborhoods"][neighborhood_id] = {
            "district": neighborhood["district"],
            "profile": neighborhood["profile"],
            "elevation": elevation,
            "plinth_top": quarter_top,
            "lots": quarter_lots[neighborhood_id],
            "plaza": plaza,
            "yard_rows": yard_rows[neighborhood_id],
            "greens": entry_greens,
        }

    plan["blocks"] = blocks
    plan["founding_blocked"] = founding_blocked_buildings(master_spec)
    plan["spatial"] = audit_plan(plan, master_spec, graph, validator)
    plan["summary"] = fabric_totals(plan)
    return plan


def audit_plan(plan: dict, master_spec: dict, graph: dict, validator: PlacementValidator) -> dict:
    """Re-audit every placed production object against full occupancy.

    The counts here are the manifest's spatial-validity numbers: they come
    from re-checking the final plan, not from trusting the generator.

    Lot PLINTHS are audited separately from the masses standing on them:
    they are not validator entries (their ground legitimately underlies
    the frontage strip other envelopes claim), so the one thing they must
    never touch -- the driveable surface -- is measured here directly.
    """
    metrics = {
        "building_road_collisions": 0,
        "plinth_carriageway_collisions": 0,
        "tree_road_collisions": 0,
        "tree_building_collisions": 0,
        "building_building_overlaps": 0,
        "wall_clearance_violations": 0,
        "founding_object_violations": 0,
        "water_violations": 0,
        "junction_violations": 0,
        "plaza_violations": 0,
    }
    key_by_category = {
        "ROAD": {
            "BUILDING": "building_road_collisions",
            "VEGETATION": "tree_road_collisions",
            "PLAZA": "plaza_violations",
        },
        "JUNCTION": {
            "BUILDING": "junction_violations",
            "VEGETATION": "junction_violations",
            "PLAZA": "junction_violations",
        },
        "BUILDING": {
            "BUILDING": "building_building_overlaps",
            "VEGETATION": "tree_building_collisions",
        },
        "VEGETATION": {"BUILDING": "tree_building_collisions"},
        "GROVE": {
            "BUILDING": "tree_building_collisions",
            "PLAZA": "plaza_violations",
        },
        "WALL": {
            "BUILDING": "wall_clearance_violations",
            "VEGETATION": "wall_clearance_violations",
            "PLAZA": "wall_clearance_violations",
        },
        "HISTORY": {
            "BUILDING": "founding_object_violations",
            "VEGETATION": "founding_object_violations",
            "PLAZA": "founding_object_violations",
        },
        "PLATE": {
            "BUILDING": "founding_object_violations",
            "PLAZA": "founding_object_violations",
        },
        "WATER": {
            "BUILDING": "water_violations",
            "VEGETATION": "water_violations",
            "PLAZA": "water_violations",
        },
        "PLAZA": {
            "BUILDING": "plaza_violations",
            "VEGETATION": "plaza_violations",
            "PLAZA": "plaza_violations",
        },
    }
    """Which metric each (existing category, candidate category) pair feeds.

    Every category the POLICY table lets a candidate violate must appear
    here, in both directions: a row missing its PLAZA column would let the
    validator raise a real conflict that the audit then silently dropped,
    and the manifest would publish a zero the plan had never earned."""
    audited = 0
    pad_laps = 0
    worst_pad_lap = 0.0
    carriageways = carriageway_envelopes(master_spec, graph, plan.get("ground"))
    for neighborhood_id, entry in sorted(plan["neighborhoods"].items()):
        for lot in entry["lots"]:
            if not plinth_is_clear(lot, carriageways):
                metrics["plinth_carriageway_collisions"] += 1
            lap = plinth_pad_lap(lot, carriageways)
            if lap > 0.0:
                pad_laps += 1
                worst_pad_lap = max(worst_pad_lap, lap)
        placed: list[tuple[str, str, list[dict]]] = []
        if entry["plaza"] is not None:
            plaza = entry["plaza"]
            placed.append(
                (
                    f"plaza_{neighborhood_id}",
                    "PLAZA",
                    [circle(plaza["center"][0], plaza["center"][1], plaza["radius"])],
                )
            )
        for lot in entry["lots"]:
            placed.append((f"lot_{lot['name']}", "BUILDING", lot_shapes(lot)))
        for row in entry["yard_rows"]:
            placed.append(
                (
                    f"stack_{row['name']}",
                    "BUILDING",
                    [rect(row["x"], row["y"], row["length"] / 2.0 + 0.3, 1.35, row["heading"])],
                )
            )
        for green in entry["greens"]:
            placed.append(
                (
                    f"green_{green['name'].split('__', 1)[-1]}",
                    "VEGETATION",
                    [circle(green["x"], green["y"], green["envelope"])],
                )
            )
        for entry_id, category, shapes in placed:
            audited += 1
            for conflict in validator.audit(entry_id, category, shapes):
                their = conflict["their_category"]
                if their == "VEGETATION" and category == "BUILDING":
                    metrics["tree_building_collisions"] += 1
                    continue
                key = key_by_category.get(their, {}).get(category)
                if key is not None:
                    metrics[key] += 1
    metrics["audited_objects"] = audited
    metrics["rejected_candidates"] = len(validator.rejections)
    metrics["rejections_by_pair"] = validator.rejection_summary()
    metrics["plinth_pad_laps"] = pad_laps
    metrics["worst_plinth_pad_lap"] = round(worst_pad_lap, 4)
    return metrics


def fabric_totals(plan: dict) -> dict:
    """Deterministic aggregate counts for reports and manifests.

    ``founding_blocked_buildings`` is the residual of the road-encroachment
    remediation: founding architecture that stands in legal carriageway
    space and keeps its Phase 15 ground, accepted as a permanent
    compatibility exception rather than an open defect. Four of the five
    have no legal alternative position anywhere on their own plate; the
    fifth had one off the relocation ladder and it was declined (see
    :func:`spatial_occupancy.founding_blocked_buildings`). It is published
    here so the number is pinned by the manifest and by the frozen-evidence
    baselines -- a residual nobody counts is a residual that grows.
    """
    lots = [lot for entry in plan["neighborhoods"].values() for lot in entry["lots"]]
    masses = [mass for lot in lots for mass in lot["masses"]]
    industrial = [mass for lot in lots if lot["kind"] in INDUSTRIAL_KINDS for mass in lot["masses"]]
    greens = [green for entry in plan["neighborhoods"].values() for green in entry["greens"]]
    legacy = plan.get("legacy", {"kept": {}, "removed": {}})
    ground = plan.get("ground", {"summary": {}})
    return {
        **{f"ground_{key}": value for key, value in ground.get("summary", {}).items()},
        "neighborhoods": len(plan["neighborhoods"]),
        "lots": len(lots),
        "masses": len(masses),
        "midrise_masses": sum(1 for mass in masses if mass["h"] >= MIDRISE_THRESHOLD),
        "lowrise_masses": sum(1 for mass in masses if mass["h"] < MIDRISE_THRESHOLD),
        "industrial_masses": len(industrial),
        "halo_lots": sum(1 for lot in lots if not lot["on_pad"]),
        "yard_rows": sum(len(entry["yard_rows"]) for entry in plan["neighborhoods"].values()),
        "plazas": sum(1 for entry in plan["neighborhoods"].values() if entry["plaza"] is not None),
        "greens": len(greens),
        "production_trees": sum(green["trees"] for green in greens),
        "street_trees": sum(1 for green in greens if green["role"] == "street"),
        "park_groups": sum(1 for green in greens if green["role"] == "park"),
        "promenade_trees": sum(1 for green in greens if green["role"] == "promenade"),
        "legacy_clusters_kept": len(legacy["kept"]),
        "legacy_clusters_removed": len(legacy["removed"]),
        "legacy_trees_kept": sum(record["trees"] for record in legacy["kept"].values()),
        "legacy_trees_removed": sum(record["trees"] for record in legacy["removed"].values()),
        "founding_blocked_buildings": len(plan.get("founding_blocked", ())),
    }


def validate_urban_fabric(
    plan: dict, master_spec: dict, production_spec: dict, graph: dict
) -> list[str]:
    """Re-prove the spatial contract against the emitted plan, from scratch.

    A fresh validator is loaded with fixed truth (under the INDEPENDENTLY
    recomputed clearing decision) plus every planned object, then every
    planned object is audited against everything else. Any nonzero
    collision count is an error, and a plan whose legacy block disagrees
    with the recomputed clearing is refused outright -- resurrecting a
    cleared cluster or silently dropping a preserved one cannot pass.
    """
    errors: list[str] = []
    clearing = plan_legacy_clearing(master_spec, production_spec, graph)
    declared = plan.get("legacy", {})
    if sorted(declared.get("kept", {})) != sorted(clearing["kept"]):
        errors.append("plan legacy clearing disagrees with the deterministic decision (kept)")
    if declared.get("removed_objects") != clearing["removed_objects"]:
        errors.append("plan legacy clearing disagrees with the deterministic decision (removed)")
    errors.extend(
        validate_city_ground(
            plan.get("ground", {"plates": {}, "cells": {}}),
            master_spec,
            production_spec,
            graph,
        )
    )
    validator = build_occupancy(master_spec, graph, clearing, plan.get("ground"))
    for neighborhood_id, entry in sorted(plan["neighborhoods"].items()):
        if entry["plaza"] is not None:
            plaza = entry["plaza"]
            validator.register(
                f"plaza_{neighborhood_id}",
                "PLAZA",
                [circle(plaza["center"][0], plaza["center"][1], plaza["radius"])],
            )
        for lot in entry["lots"]:
            validator.register(f"lot_{lot['name']}", "BUILDING", lot_shapes(lot))
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
    metrics = audit_plan(plan, master_spec, graph, validator)
    for key, value in metrics.items():
        # The plinth keys are MEASUREMENTS the plan publishes rather than
        # violations it forbids: a slab may lap a junction apron, and a
        # slab the ladder could not pull out of a carriageway is reported
        # rather than paid for by deleting the building standing on it
        # (see :func:`plinth_pad_lap` and :func:`_plinth_first`).
        if key in (
            "audited_objects",
            "rejected_candidates",
            "rejections_by_pair",
            "plinth_carriageway_collisions",
            "plinth_pad_laps",
            "worst_plinth_pad_lap",
        ):
            continue
        if value:
            errors.append(f"spatial contract violated: {key} = {value}")
    fabric_limit = float(production_spec["fabric_limit_radius"])
    quarter_centers = {
        neighborhood_id: (float(entry["center"][0]), float(entry["center"][1]))
        for neighborhood_id, entry in production_spec["neighborhoods"].items()
    }
    for neighborhood_id, entry in sorted(plan["neighborhoods"].items()):
        declared_quarter = production_spec["neighborhoods"].get(neighborhood_id)
        if declared_quarter is None:
            errors.append(f"plan invents neighborhood {neighborhood_id}")
            continue
        center = quarter_centers[neighborhood_id]
        for lot in entry["lots"]:
            gap = math.hypot(lot["x"] - center[0], lot["y"] - center[1])
            nearest = min(
                math.hypot(lot["x"] - cx, lot["y"] - cy) for cx, cy in quarter_centers.values()
            )
            if gap > nearest + 9.0:
                errors.append(f"lot {lot['name']} is owned by a quarter that is not its nearest")
            if math.hypot(lot["x"], lot["y"]) > fabric_limit + 2.0:
                errors.append(f"lot {lot['name']} exceeds the fabric limit")
            if (
                coast_coordinate((lot["x"], lot["y"]), master_spec)
                > port_frame(master_spec)[2] - HARBOR_LOT_CLEARANCE
            ):
                errors.append(f"lot {lot['name']} stands in the harbor approach")
            for wall in _wall_lines(master_spec):
                if (
                    distance_point_polyline((lot["x"], lot["y"]), wall["line"])
                    < wall["lot_clearance"]
                ):
                    errors.append(f"lot {lot['name']} crowds the {wall['id']} wall line")
    return errors
