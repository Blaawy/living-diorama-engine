"""The Phase 16 urban ground plan: one continuous city instead of pods.

Pure Python by design -- no ``bpy``. The founding presentation gave every
district a circular plate: a paved rim, a wide ring-road annulus, and a
raised core disc, all standing on open terrain. Useful during the visual
proof, those nested circles read as DISTRICT PODS at production scale.
This module computes the FINAL URBAN COMPOSITION ground: the meaning of
every district (identity, state, topology, history) is untouched, while
the arbitrary circular floor presentation is reinterpreted into designed,
block-aligned city ground -- the Phase 16 rule made geometry: LOCK
MEANING, NOT ARBITRARY PRESENTATION GEOMETRY.

Two systems together remove the pod effect:

TABLES AND SKIRTS reshape each plate. Per district the plan emits two
terraced tiers of ground panels, sector by sector. The TABLE tier rises
just above the ring-road annulus: in BURIED ring sectors (ring arcs that
serve no street landing) it sweeps from inside the historic core edge out
over the annulus and rim, erasing the circle; in KEPT sectors it starts
at the annulus outer edge, so the founding ring stays a real sunken
boulevard between the core plinth and the new shoulder. The SKIRT tier
steps the table down toward the surrounding city with an authored
polygonal edge -- block geometry, not a disc. Which arcs are kept is
computed from the road graph: every gap between ring landings wider than
the bury threshold is buried; the civic district keeps its full
ceremonial Ring around the Golden Seal by declaration.

GROUND CELLS carpet the production quarters: authored polygons (paved
block ground, civic concrete, park lawns) welding streets, plinths, and
parks into one continuous fabric, exactly as the streets themselves are
authored polylines.

History keeps its ground unconditionally: every panel vertex is clamped
radially against the wall-station corridors, the harbor water, and the
diorama extent, so the original founding edge remains visible precisely
inside the scar corridor -- the city grows around history, it does not
erase it. The Seal, depots, plates, and architecture are never moved;
panels are presentation ground UNDER the world, like the lot plinths.

Determinism: the ground plan is a pure function of the master scene, the
production spec, and the road graph. Iteration is sorted; there is no
randomness anywhere in this module.
"""

import math

from production_spec import PLATE_MARGIN, coast_coordinate, port_frame

GROUND_SURFACES = ("pavement", "concrete", "lawn")
"""Every surface a ground cell may declare (lawn renders as terrain)."""

DEFAULT_BURY_GAP_DEG = 130.0
"""A ring gap between landings wider than this is buried by default."""

LANDING_KEEP_DEG = 10.0
"""Carriageway kept either side of every street landing.

A landing is where a road actually meets the ring; burying the ring right
up to it would leave a founding spur ending on bare paving. Every landing
therefore keeps a short forecourt of real carriageway, and only the empty
sweep between them disappears."""

MIN_BURIED_SPAN_DEG = 20.0
"""A gap that would bury less than this after both landing forecourts are
kept is simply kept whole -- a two-degree hole in a ring is not a
composition, it is a defect."""

AZ_STEP_DEG = 4.0
"""Arc sampling step for sector boundaries (fine enough to hug curbs)."""

MAX_SECTOR_SPAN_DEG = 170.0
"""Sectors wider than this are split so every polygon stays simple."""

TABLE_LIFT = 0.625
"""Table tier top over district elevation: above the ring-road annulus
(+0.61), below the historic core disc (+0.68) -- the core keeps a modest
plinth step, the annulus circle disappears."""

TABLE_OVERHANG = 2.0
"""How far the table tier reaches past the plate rim."""

SKIRT_TUCK = 0.5
"""How far the skirt tier slides in under the plate rim, so the lower
terrace meets the founding plate with no seam of bare terrain."""

RING_ARC_HALF_WIDTH = 2.6
RING_ARC_KEEP = 0.3
"""A redrawn ring arc is a real carriageway of its own width; in a KEPT
sector the shoulder starts beyond it, so the composition never buries the
very street it chose to preserve. A district keeping its whole ring
(the civic Ring) has no redrawn arc, and its shoulder starts at the ring
surface edge -- the Ring stays, its blank outer rim does not."""

SKIRT_BASE_LEVEL = 0.40
SKIRT_ELEVATION_FACTOR = 0.4
"""Skirt tier top: 0.40 + 0.4 * district elevation -- always beneath the
street decks, stepping the plate down toward the quarter carpets."""

CORE_INSET_FACTOR = 0.58
"""Fill sectors start this fraction of the district radius from center,
tucked under the historic core disc edge (at 0.62) so no seam shows."""

RING_OUTER_FACTOR = 0.985
"""The founding ring-road annulus outer radius factor (Phase 15 truth)."""

PANEL_BASE_Z = 0.05
"""Every ground panel extrudes down to this world height."""

SCAR_STATION_LENGTH = 30.0
SCAR_PANEL_CLEARANCE = 6.5
STATION_PANEL_CLEARANCE = 3.0
"""Ground panels keep the wall corridors open: the scar's full exclusion
band and the reserved short-station alignments (mirrors the fabric
constants; panels are ground, so they respect the corridor itself)."""

WATER_PANEL_CLEARANCE = 1.0
"""Panels stop this far before the harbor quay line."""

SEAL_PANEL_CLEARANCE = 2.2
"""The Golden Seal's plaza keeps its own ground: no production panel may
reach inside the monument's tiered apron."""

EXTENT_LIMIT = 74.5
"""No panel vertex leaves this radius (the fabric limit plus curb room)."""

MIN_PANEL_DEPTH = 0.2
"""A clamped sector thinner than this is dropped instead of emitted."""

CLAMP_MARGIN = 0.2
"""Extra ground released beyond every clamped edge, so the straight
polygon chords between samples never nick a protected zone."""

PLANNING_MARGIN = 0.3
"""The ground plan builds to a STRICTER clearance than the contract it is
later judged against, so a panel can never land exactly on the limit and
fail its own audit on a differently-placed sample."""

EDGE_SAMPLE_STEP = 0.2
"""Edge sampling step while relaxing panels -- finer than the audit's, so
the planner always sees a violation before the validator does."""

CLAMP_SCAN_STEP = 0.5
"""Radial scan step when searching for the first blocked point."""

FOREIGN_RING_KEEP = 0.4
"""Panels stay this far outside another district's ring-road annulus."""

ANNULUS_BASE_LIFT = 0.55
"""A panel at or above ``elevation + 0.55`` could cover a ring-road
surface; lower panels pass beneath it as terraces."""


class CityGroundError(ValueError):
    """A ground-plan contract violation: always a refusal, never a repair."""


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _wall_lines(master_spec: dict) -> list[dict]:
    """Every wall-station line with the clearance ground must keep."""
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
                "a": (x - ux * half, y - uy * half),
                "b": (x + ux * half, y + uy * half),
                "clearance": SCAR_PANEL_CLEARANCE if is_scar else STATION_PANEL_CLEARANCE,
            }
        )
    return walls


def _point_segment_distance(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    """Distance from a point to one finite segment."""
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    if length_squared == 0.0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
    return math.hypot(px - (ax + dx * t), py - (ay + dy * t))


def _point_allowed(
    point: tuple[float, float],
    walls: list[dict],
    master_spec: dict,
    own_district: str,
    level: float,
    margin: float = 0.0,
) -> bool:
    """True when ground of one district may stand at a point at one level.

    Refused beyond the diorama extent, in the harbor water, inside any
    wall-station corridor, and -- for panels high enough to cover a ring
    road -- over the VISIBLE ring annulus of any other district. A foreign
    annulus hidden beneath a higher founding plate is not visible, so the
    overlapping western plates may ground over each other exactly as
    their own founding stacking already does.
    """
    if math.hypot(point[0], point[1]) > EXTENT_LIMIT - margin:
        return False
    quay = port_frame(master_spec)[2]
    if coast_coordinate(point, master_spec) > quay - WATER_PANEL_CLEARANCE - margin:
        return False
    for wall in walls:
        gap = _point_segment_distance(
            point[0], point[1], wall["a"][0], wall["a"][1], wall["b"][0], wall["b"][1]
        )
        if gap < wall["clearance"] + margin:
            return False
    seal = master_spec["landmarks"]["golden_seal"]
    if (
        math.hypot(point[0] - seal["location"][0], point[1] - seal["location"][1])
        < float(seal["radius"]) + SEAL_PANEL_CLEARANCE + margin
    ):
        return False
    districts = master_spec["districts"]
    for other_id, other in districts.items():
        if other_id == own_district:
            continue
        if level < float(other["elevation"]) + ANNULUS_BASE_LIFT:
            continue
        reach = math.hypot(point[0] - other["center"][0], point[1] - other["center"][1])
        if reach >= RING_OUTER_FACTOR * float(other["radius"]) + FOREIGN_RING_KEEP + margin:
            continue
        covered = any(
            float(cover["elevation"]) > float(other["elevation"])
            and math.hypot(point[0] - cover["center"][0], point[1] - cover["center"][1])
            < float(cover["radius"])
            for cover in districts.values()
        )
        if not covered:
            return False
    return True


def _clamped_radius(
    center: tuple[float, float],
    az_deg: float,
    inner: float,
    desired: float,
    walls: list[dict],
    master_spec: dict,
    own_district: str,
    level: float,
) -> float:
    """The largest radius whose whole span from ``inner`` stays allowed.

    A deterministic outward scan finds the first blocked point past the
    inner radius, then bisection refines the boundary; the panel edge
    follows the clearance line minus a safety margin instead of covering
    protected ground. Corridors crossing the middle of a plate therefore
    notch the panel instead of being bridged.
    """
    angle = math.radians(az_deg)
    unit = (math.cos(angle), math.sin(angle))

    def allowed(radius: float) -> bool:
        return _point_allowed(
            (center[0] + unit[0] * radius, center[1] + unit[1] * radius),
            walls,
            master_spec,
            own_district,
            level,
            PLANNING_MARGIN,
        )

    if not allowed(inner):
        return inner
    good = inner
    probe = inner + CLAMP_SCAN_STEP
    while probe < desired:
        if not allowed(probe):
            break
        good = probe
        probe += CLAMP_SCAN_STEP
    else:
        if allowed(desired):
            return desired
        probe = desired
    low, high = good, probe
    for _ in range(30):
        mid = (low + high) / 2.0
        if allowed(mid):
            low = mid
        else:
            high = mid
    return max(inner, low - CLAMP_MARGIN)


def _interpolate_skirt(controls: list[tuple[float, float]], az_deg: float) -> float:
    """Linear interpolation of the authored skirt profile at one azimuth."""
    ordered = sorted((float(az) % 360.0, float(reach)) for az, reach in controls)
    if not ordered:
        return 0.0
    az = az_deg % 360.0
    previous = (ordered[-1][0] - 360.0, ordered[-1][1])
    for control_az, reach in ordered:
        if control_az >= az:
            span = control_az - previous[0]
            if span <= 0.0:
                return reach
            t = (az - previous[0]) / span
            return previous[1] + (reach - previous[1]) * t
        previous = (control_az, reach)
    first = (ordered[0][0] + 360.0, ordered[0][1])
    span = first[0] - previous[0]
    if span <= 0.0:
        return first[1]
    t = (az - previous[0]) / span
    return previous[1] + (first[1] - previous[1]) * t


def _sector_azimuths(from_deg: float, to_deg: float) -> list[float]:
    """Sample azimuths across one sector, endpoints exact, CCW order."""
    span = (to_deg - from_deg) % 360.0
    if span == 0.0:
        span = 360.0
    steps = max(2, int(math.ceil(span / AZ_STEP_DEG)))
    return [from_deg + span * index / steps for index in range(steps + 1)]


def _split_span(from_deg: float, to_deg: float) -> list[tuple[float, float]]:
    """Split one angular span into pieces no wider than the polygon limit."""
    span = (to_deg - from_deg) % 360.0
    if span == 0.0:
        span = 360.0
    pieces = max(1, int(math.ceil(span / MAX_SECTOR_SPAN_DEG)))
    edges = [from_deg + span * index / pieces for index in range(pieces + 1)]
    return list(zip(edges, edges[1:], strict=False))


def point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    """Even-odd containment test."""
    inside = False
    px, py = point
    for (ax, ay), (bx, by) in zip(polygon, polygon[1:] + polygon[:1], strict=False):
        if (ay > py) != (by > py):
            cross_x = ax + (py - ay) / (by - ay) * (bx - ax)
            if px < cross_x:
                inside = not inside
    return inside


# ---------------------------------------------------------------------------
# Ring sectors: which arcs stay visible streets
# ---------------------------------------------------------------------------


def kept_ring_paths(master_spec: dict, ground: dict, district_id: str) -> list[list[tuple]]:
    """Polylines of the arcs of one founding ring the city still drives.

    A district whose ring is buried in part keeps only these arcs as real
    carriageway: the production build draws them and the occupancy
    contract registers them, so the covered sectors are neither road nor
    obstacle. A ``full`` ring returns its whole circle.
    """
    district = master_spec["districts"][district_id]
    center = (float(district["center"][0]), float(district["center"][1]))
    radius = RING_OUTER_FACTOR * float(district["radius"])
    plate = ground["plates"][district_id]
    paths: list[list[tuple]] = []
    for arc_from, arc_to in plate["kept_arcs"]:
        span = (arc_to - arc_from) % 360.0
        if plate["ring"] == "full" or span == 0.0:
            span = 360.0
        steps = max(2, int(math.ceil(span / AZ_STEP_DEG)))
        path = []
        for index in range(steps + 1):
            angle = math.radians(arc_from + span * index / steps)
            path.append(
                (
                    round(center[0] + radius * math.cos(angle), 6),
                    round(center[1] + radius * math.sin(angle), 6),
                )
            )
        paths.append(path)
    return paths


def ring_sectors(master_spec: dict, production_spec: dict, graph: dict, district_id: str) -> dict:
    """Kept and buried arcs of one founding ring, from the road graph.

    Every junction node on the ring (spur roots and production landings)
    is an azimuth; gaps between consecutive azimuths wider than the bury
    threshold carry no city traffic and are buried. A district declaring
    ``ring: full`` keeps its complete circle -- the civic Ring around the
    Seal is a designed form, not an accident.
    """
    district = master_spec["districts"][district_id]
    center = (float(district["center"][0]), float(district["center"][1]))
    ground = production_spec["ground"]
    plate = ground["plates"][district_id]
    bury_gap = float(ground.get("bury_gap_deg", DEFAULT_BURY_GAP_DEG))
    vias = []
    segment = graph["segments"][f"ring_{district_id}"]
    for node_id in sorted(set(segment["via"])):
        node = graph["nodes"][node_id]
        azimuth = math.degrees(math.atan2(node["y"] - center[1], node["x"] - center[0])) % 360.0
        vias.append(round(azimuth, 4))
    vias.sort()
    if plate["ring"] == "full" or not vias:
        return {"vias": vias, "kept": [(0.0, 360.0)], "buried": []}
    kept: list[tuple[float, float]] = []
    buried: list[tuple[float, float]] = []
    for index, start in enumerate(vias):
        end = vias[(index + 1) % len(vias)]
        span = (end - start) % 360.0
        if span == 0.0:
            span = 360.0
        if span <= bury_gap:
            kept.append((start, start + span))
            continue
        if span <= 2.0 * LANDING_KEEP_DEG + MIN_BURIED_SPAN_DEG:
            kept.append((start, start + span))
            continue
        kept.append((start, start + LANDING_KEEP_DEG))
        buried.append((start + LANDING_KEEP_DEG, start + span - LANDING_KEEP_DEG))
        kept.append((start + span - LANDING_KEEP_DEG, start + span))
    return {"vias": vias, "kept": kept, "buried": buried}


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def _sector_polygons(
    center: tuple[float, float],
    from_deg: float,
    to_deg: float,
    inner_radius: float,
    outer_radius_at,
    walls: list[dict],
    master_spec: dict,
    own_district: str,
    level: float,
) -> list[list[tuple[float, float]]]:
    """The panel polygons of one sector, clamped against history and water.

    The outer boundary walks the sector forward, the inner boundary walks
    it back. Where a wall corridor, the water, or another district's ring
    crosses the sector, the ground is not bridged: the sector SPLITS into
    separate panels on either side, leaving the protected alignment as an
    open seam in the city floor. The outer boundary is then relaxed until
    every sampled point of every edge is legal, so a straight chord can
    never cut a corner history is keeping.
    """
    azimuths = _sector_azimuths(from_deg, to_deg)
    limits = [
        _clamped_radius(
            center,
            az,
            inner_radius,
            outer_radius_at(az),
            walls,
            master_spec,
            own_district,
            level,
        )
        for az in azimuths
    ]

    def at(az: float, radius: float) -> tuple[float, float]:
        angle = math.radians(az)
        return (center[0] + math.cos(angle) * radius, center[1] + math.sin(angle) * radius)

    def edge_clear(first: int, second: int) -> bool:
        start = at(azimuths[first], limits[first])
        end = at(azimuths[second], limits[second])
        length = math.hypot(end[0] - start[0], end[1] - start[1])
        steps = max(1, int(length / EDGE_SAMPLE_STEP))
        for index in range(steps + 1):
            t = index / steps
            point = (start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t)
            if not _point_allowed(point, walls, master_spec, own_district, level, PLANNING_MARGIN):
                return False
        return True

    def usable(index: int) -> bool:
        return limits[index] - inner_radius >= MIN_PANEL_DEPTH

    for _pass in range(80):
        dirty = False
        for index in range(len(azimuths) - 1):
            if not usable(index) or not usable(index + 1):
                continue
            if edge_clear(index, index + 1):
                continue
            reduced = max(inner_radius, min(limits[index], limits[index + 1]) - CLAMP_SCAN_STEP)
            limits[index] = min(limits[index], reduced)
            limits[index + 1] = min(limits[index + 1], reduced)
            dirty = True
        if not dirty:
            break

    polygons: list[list[tuple[float, float]]] = []
    group: list[int] = []
    for index in range(len(azimuths)):
        if usable(index):
            group.append(index)
            continue
        if len(group) >= 2:
            polygons.append(group)
        group = []
    if len(group) >= 2:
        polygons.append(group)

    shapes: list[list[tuple[float, float]]] = []
    for indices in polygons:
        outer = [at(azimuths[index], limits[index]) for index in indices]
        inner = [at(azimuths[index], inner_radius) for index in indices]
        points = outer + list(reversed(inner))
        shapes.append([(round(x, 6), round(y, 6)) for x, y in points])
    return shapes


def _tier_pieces(
    *,
    center: tuple[float, float],
    district_id: str,
    tier: str,
    spans: list[tuple[float, float]],
    inner_radius: float,
    table_outer: float,
    skirt_profile: list[tuple[float, float]] | None,
    level: float,
    walls: list[dict],
    master_spec: dict,
) -> list[dict]:
    """Every panel of one terrace tier of one plate.

    ``skirt_profile`` is the authored polygonal reach of the skirt tier;
    the table tiers reach the fixed overhang instead.
    """

    def outer_radius_at(azimuth: float) -> float:
        if skirt_profile is None:
            return table_outer
        return table_outer + max(1.5, _interpolate_skirt(skirt_profile, azimuth))

    pieces: list[dict] = []
    for span_from, span_to in spans:
        for piece_from, piece_to in _split_span(span_from, span_to):
            for polygon in _sector_polygons(
                center,
                piece_from,
                piece_to,
                inner_radius,
                outer_radius_at,
                walls,
                master_spec,
                district_id,
                level,
            ):
                pieces.append(
                    {
                        "tier": tier,
                        "from_deg": round(piece_from % 360.0, 4),
                        "to_deg": round(piece_to % 360.0, 4),
                        "level": level,
                        "points": polygon,
                    }
                )
    return pieces


def plan_city_ground(master_spec: dict, production_spec: dict, graph: dict) -> dict:
    """Compute the complete deterministic urban ground plan.

    Returns ``{"plates": {...}, "cells": {...}, "summary": {...}}``. Every
    plate carries its ring decision (vias, kept arcs, buried arcs) and its
    panel pieces (tier, sector span, polygon, level); every cell carries
    its authored polygon, level, and surface.
    """
    walls = _wall_lines(master_spec)
    ground_spec = production_spec["ground"]
    plates: dict[str, dict] = {}
    for district_id, district in sorted(master_spec["districts"].items()):
        center = (float(district["center"][0]), float(district["center"][1]))
        radius = float(district["radius"])
        elevation = float(district["elevation"])
        declaration = ground_spec["plates"][district_id]
        skirt_controls = [(float(az), float(reach)) for az, reach in declaration["skirt"]]
        sectors = ring_sectors(master_spec, production_spec, graph, district_id)
        rim = radius + PLATE_MARGIN
        table_outer = rim + TABLE_OVERHANG
        table_level = round(elevation + TABLE_LIFT, 4)
        skirt_level = round(SKIRT_BASE_LEVEL + SKIRT_ELEVATION_FACTOR * elevation, 4)
        shoulder_inner = RING_OUTER_FACTOR * radius
        if declaration["ring"] != "full":
            shoulder_inner += RING_ARC_HALF_WIDTH + RING_ARC_KEEP
        pieces: list[dict] = []
        for tier, spans, inner_radius, reach in (
            ("table_fill", sectors["buried"], CORE_INSET_FACTOR * radius, None),
            ("table_shoulder", sectors["kept"], shoulder_inner, None),
            ("skirt", [(0.0, 360.0)], rim - SKIRT_TUCK, skirt_controls),
        ):
            pieces.extend(
                _tier_pieces(
                    center=center,
                    district_id=district_id,
                    tier=tier,
                    spans=spans,
                    inner_radius=inner_radius,
                    table_outer=table_outer,
                    skirt_profile=reach,
                    level=skirt_level if tier == "skirt" else table_level,
                    walls=walls,
                    master_spec=master_spec,
                )
            )
        plates[district_id] = {
            "ring": declaration["ring"],
            "rim_exposure_deg": 0.0,
            "vias": sectors["vias"],
            "kept_arcs": [(round(a % 360.0, 4), round(b % 360.0, 4)) for a, b in sectors["kept"]],
            "buried_arcs": [
                (round(a % 360.0, 4), round(b % 360.0, 4)) for a, b in sectors["buried"]
            ],
            "table_level": table_level,
            "skirt_level": skirt_level,
            "pieces": pieces,
        }

    for district_id, plate in plates.items():
        plate["rim_exposure_deg"] = rim_exposure(plate, master_spec, district_id)

    cells: dict[str, dict] = {}
    for cell_id, declaration in sorted(ground_spec["cells"].items()):
        cells[cell_id] = {
            "surface": declaration["surface"],
            "level": round(float(declaration["level"]), 4),
            "points": [(round(float(x), 6), round(float(y), 6)) for x, y in declaration["points"]],
        }

    plan = {"plates": plates, "cells": cells}
    plan["summary"] = ground_totals(plan)
    return plan


MAX_RIM_EXPOSURE_DEG = 12.0
"""The longest run of visible plate rim any district may still show.

Burial is judged as a RUN over the WHOLE circle, not as a point and not
only over the sectors the plan chose to bury: where the scar corridor or
the harbor forbids ground, the plate edge stays visible for a few degrees
and reads as history's own seam through the city floor, but a longer run
anywhere is a surviving pod circle and is refused. The measured worst run
per plate is published in the plan and the manifest, so the number is
auditable rather than asserted."""

RIM_PROBE_STEP_DEG = 1.0
"""Angular resolution of the rim-burial measurement."""


def _in_arc(azimuth: float, arcs: list) -> bool:
    """True when an azimuth falls inside any (from, to) arc."""
    for arc_from, arc_to in arcs:
        span = (float(arc_to) - float(arc_from)) % 360.0 or 360.0
        if ((azimuth - float(arc_from)) % 360.0) <= span + 1.0e-9:
            return True
    return False


def rim_exposure(plate: dict, master_spec: dict, district_id: str) -> float:
    """The longest contiguous run of visible plate rim, over the WHOLE circle.

    Measured across all 360 degrees, never only across the arcs the plan
    itself chose to bury: a plate that buried nothing would otherwise
    score a vacuous zero while its entire founding circle survived.

    At each azimuth the rim is considered accounted for when it is covered
    by a table panel, carried by a KEPT ring arc (the arc is a real street
    the composition deliberately preserved, and its carriageway spans the
    rim), or legitimately withheld by history, water, or the diorama edge.
    Anything else is exposed circle. Returns degrees; 0.0 is a clean plate.
    """
    district = master_spec["districts"][district_id]
    center = (float(district["center"][0]), float(district["center"][1]))
    radius = float(district["radius"])
    rim_probe = radius + PLATE_MARGIN - 0.2
    walls = _wall_lines(master_spec)
    table_level = float(plate["table_level"])
    table_polygons = [
        piece["points"] for piece in plate["pieces"] if piece["tier"].startswith("table")
    ]
    arc_reach = RING_OUTER_FACTOR * radius + RING_ARC_HALF_WIDTH
    arc_carries_rim = plate["ring"] != "full" and rim_probe <= arc_reach
    kept = plate["kept_arcs"]
    steps = max(4, int(360.0 / RIM_PROBE_STEP_DEG))
    worst = 0.0
    run = 0.0
    for step in range(steps * 2):
        azimuth = (step % steps) * 360.0 / steps
        angle = math.radians(azimuth)
        probe = (
            center[0] + rim_probe * math.cos(angle),
            center[1] + rim_probe * math.sin(angle),
        )
        covered = any(point_in_polygon(probe, polygon) for polygon in table_polygons)
        if not covered and arc_carries_rim and _in_arc(azimuth, kept):
            covered = True
        withheld = not _point_allowed(
            probe,
            walls,
            master_spec,
            district_id,
            table_level,
            PLANNING_MARGIN + CLAMP_SCAN_STEP,
        )
        if covered or withheld:
            run = 0.0
            continue
        run += 360.0 / steps
        worst = max(worst, min(run, 360.0))
    return round(worst, 3)


TERRAIN_TOP = 0.16
"""Top of the founding terrain disc: the ground of last resort."""


def ground_level_at(point: tuple[float, float], ground: dict) -> float:
    """The height of the highest city ground standing under a point.

    The composition gives the world a stepped floor -- terrain, ground
    cells, plate skirts, plate tables -- so 'the ground' is no longer one
    number per quarter. Anything the city places must sit on what is
    actually beneath it, or it reads as sunk into the pavement or hovering
    above it. Order-independent by construction (a maximum), so the answer
    never depends on iteration order.
    """
    best = TERRAIN_TOP
    for plate in ground["plates"].values():
        for piece in plate["pieces"]:
            level = float(piece["level"])
            if level > best and point_in_polygon(point, piece["points"]):
                best = level
    for cell in ground["cells"].values():
        level = float(cell["level"])
        if level > best and point_in_polygon(point, cell["points"]):
            best = level
    return best


def ground_totals(plan: dict) -> dict:
    """Deterministic aggregate counts for reports and manifests."""
    pieces = [piece for plate in plan["plates"].values() for piece in plate["pieces"]]
    cells = plan["cells"]
    return {
        "plate_panels": len(pieces),
        "table_panels": sum(1 for piece in pieces if piece["tier"].startswith("table")),
        "skirt_panels": sum(1 for piece in pieces if piece["tier"] == "skirt"),
        "buried_ring_arcs": sum(len(plate["buried_arcs"]) for plate in plan["plates"].values()),
        "kept_ring_arcs": sum(len(plate["kept_arcs"]) for plate in plan["plates"].values()),
        "full_rings": sum(1 for plate in plan["plates"].values() if plate["ring"] == "full"),
        "worst_rim_exposure_deg": max(
            (plate["rim_exposure_deg"] for plate in plan["plates"].values()), default=0.0
        ),
        "ground_cells": len(cells),
        "paved_cells": sum(1 for cell in cells.values() if cell["surface"] != "lawn"),
        "lawn_cells": sum(1 for cell in cells.values() if cell["surface"] == "lawn"),
    }


# ---------------------------------------------------------------------------
# Validation: refusal, never repair
# ---------------------------------------------------------------------------


BOUNDARY_SAMPLE_STEP = 0.5
"""Edge sampling step for panel-boundary permission checks."""


def _boundary_samples(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Every vertex plus interpolated points along each closing edge."""
    samples: list[tuple[float, float]] = []
    for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1], strict=False):
        samples.append((ax, ay))
        length = math.hypot(bx - ax, by - ay)
        steps = int(length / BOUNDARY_SAMPLE_STEP)
        for index in range(1, steps):
            t = index / steps
            samples.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    return samples


def _check_polygon_clear(
    label: str,
    points: list[tuple[float, float]],
    walls: list[dict],
    master_spec: dict,
    errors: list[str],
    *,
    own_district: str = "",
    level: float = 0.0,
) -> None:
    """Every point of a panel BOUNDARY honors the ground-permission rule.

    Edges are sampled, not just corners: a straight chord between two
    legal vertices can still sweep through a wall corridor, and a ground
    panel that bridges the scar would erase exactly the history the
    composition exists to protect.
    """
    quay = port_frame(master_spec)[2]
    for x, y in _boundary_samples(points):
        if math.hypot(x, y) > EXTENT_LIMIT + 0.05:
            errors.append(f"{label} leaves the diorama at ({x:.1f}, {y:.1f})")
            break
    for x, y in _boundary_samples(points):
        if coast_coordinate((x, y), master_spec) > quay - WATER_PANEL_CLEARANCE + 0.05:
            errors.append(f"{label} enters the harbor water at ({x:.1f}, {y:.1f})")
            break
    for wall in walls:
        for x, y in _boundary_samples(points):
            gap = _point_segment_distance(
                x, y, wall["a"][0], wall["a"][1], wall["b"][0], wall["b"][1]
            )
            if gap < wall["clearance"] - 0.05:
                errors.append(
                    f"{label} covers the {wall['id']} wall corridor at ({x:.1f}, {y:.1f}) "
                    f"({gap:.2f} < {wall['clearance']}); history keeps its ground"
                )
                break
        else:
            continue
        break
    for x, y in _boundary_samples(points):
        if not _point_allowed((x, y), [], master_spec, own_district, level):
            errors.append(f"{label} covers protected founding ground at ({x:.1f}, {y:.1f})")
            break


def validate_city_ground(
    ground: dict, master_spec: dict, production_spec: dict, graph: dict
) -> list[str]:
    """Re-prove the ground contract against the emitted plan, from scratch.

    The plan must equal its deterministic recomputation; every panel must
    honor the wall corridors, the water, and the extent; every ring
    landing must sit on a kept arc or be an intentional forecourt (a
    junction pad exists there by construction); and in every buried
    sector the plate rim must actually be buried wherever history and
    water allow -- a pod circle cannot quietly survive.
    """
    errors: list[str] = []
    recomputed = plan_city_ground(master_spec, production_spec, graph)
    if recomputed != ground:
        errors.append("ground plan disagrees with its deterministic recomputation")
    walls = _wall_lines(master_spec)

    for district_id, plate in sorted(ground.get("plates", {}).items()):
        district = master_spec["districts"].get(district_id)
        if district is None:
            errors.append(f"ground plate {district_id} names no authoritative district")
            continue
        for index, piece in enumerate(plate["pieces"]):
            _check_polygon_clear(
                f"plate {district_id} piece {index} ({piece['tier']})",
                piece["points"],
                walls,
                master_spec,
                errors,
                own_district=district_id,
                level=float(piece["level"]),
            )
        seal = master_spec["landmarks"]["golden_seal"]
        seal_keep = float(seal["radius"]) + 2.0
        for index, piece in enumerate(plate["pieces"]):
            for x, y in piece["points"]:
                if math.hypot(x - seal["location"][0], y - seal["location"][1]) < seal_keep:
                    errors.append(
                        f"plate {district_id} piece {index} intrudes on the Golden Seal plaza"
                    )
                    break

        worst = rim_exposure(plate, master_spec, district_id)
        if worst > MAX_RIM_EXPOSURE_DEG + 1.0e-6:
            errors.append(
                f"plate {district_id} leaves {worst:.0f} degrees of its buried rim "
                f"visible (limit {MAX_RIM_EXPOSURE_DEG:.0f}); the pod circle must go"
            )

        if plate["ring"] != "full":
            arcs = plate["kept_arcs"] + plate["buried_arcs"]
            covered = sum((b - a) % 360.0 or 360.0 for a, b in arcs)
            if abs(covered - 360.0) > 0.01:
                errors.append(
                    f"plate {district_id} arcs cover {covered:.2f} degrees, not the whole ring"
                )
            for via in plate["vias"]:
                if not _in_arc(via, plate["kept_arcs"]):
                    errors.append(
                        f"plate {district_id} buries its ring at the {via:.1f} degree "
                        "landing; a street would end on bare paving"
                    )

    for cell_id, cell in sorted(ground.get("cells", {}).items()):
        if cell["surface"] not in GROUND_SURFACES:
            errors.append(f"cell {cell_id} surface {cell['surface']!r} is not a ground surface")
        if len(cell["points"]) < 3:
            errors.append(f"cell {cell_id} needs at least three points")
            continue
        if not 0.05 <= cell["level"] <= 0.8:
            errors.append(f"cell {cell_id} level {cell['level']} is outside the ground band")
        _check_polygon_clear(
            f"cell {cell_id}",
            cell["points"],
            walls,
            master_spec,
            errors,
            own_district="",
            level=float(cell["level"]),
        )
        area = 0.0
        points = cell["points"]
        for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1], strict=False):
            area += ax * by - bx * ay
        if abs(area) / 2.0 < 4.0:
            errors.append(f"cell {cell_id} is degenerate (area {abs(area) / 2.0:.2f})")
    return errors
