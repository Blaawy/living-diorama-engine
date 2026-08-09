"""Production World Spec V2: loading, validation, and master-scene agreement.

Pure Python by design -- this module never imports ``bpy``, so the Phase 16
production-world contract can be validated and tested without Blender. The
Blender production builder imports it; nothing here imports Blender modules.

The Production World Spec is PRESENTATION SCALE only. It declares how far
each authoritative district's visual territory extends, the visual quarters
nested inside those districts, the DESIGNED street network (every polyline is
authored city planning, not generated avoidance), the landscape plan (park
zones that preserve founding groves, street tree lines, plaza gardens, the
quay promenade), and the Phase 16 camera anchors. It never defines simulation
entities: every quarter must belong to one of the master scene's
authoritative districts, and any reference to a district or boundary the
master scene does not know is refused outright.

Schema V2 carries the aesthetic-first redesign: the street network is
explicit and complete (no auto-generated quarter streets), and the landscape
section declares which founding presentation vegetation the production city
preserves as parks -- everything else is cleared and the city is deliberately
re-landscaped afterwards.
"""

import json
import math
from pathlib import Path

PRODUCTION_WORLD_FORMAT = "living_diorama_blender_production_world"
PRODUCTION_WORLD_SCHEMA_VERSION = 3

QUARTER_PROFILES = (
    "midrise_front",
    "business",
    "grid_rows",
    "scar_rows",
    "garden_rows",
    "meadow_courts",
    "industrial",
    "port_yard",
)
"""Every massing profile a visual quarter may take.

Profiles select massing language only -- which building forms appear, how
tall, how dense. They never introduce new simulation semantics.
"""

QUARTER_ANCHORS = ("none", "plaza")

MIN_NEIGHBORHOODS = 8
MAX_NEIGHBORHOODS = 12

STREET_CLASSES = ("arterial", "collector", "local", "service")

STREET_TERMINATIONS = (
    "cul_de_sac",
    "district_edge",
    "world_edge",
    "service_destination",
    "port_quay",
    "plaza_approach",
    "infrastructure_access",
    "wall_break",
)

TREE_LINE_SIDES = ("left", "right", "both")

GROUND_RING_MODES = ("full", "arcs")
"""How a district's founding ring road survives the final composition:
``full`` keeps the whole circle as a designed form (the civic Ring),
``arcs`` keeps only the arcs that serve street landings and buries the
empty sectors under the urban ground."""

GROUND_CELL_SURFACES = ("pavement", "concrete", "lawn")

PLATE_MARGIN = 1.5
"""How far a founding district plate extends beyond its spec radius."""

FOUNDING_RING_FACTOR = 0.985
"""The founding plate ring road sits at this fraction of the district radius."""

QUAY_OFFSET = 10.0
"""The harbor quay line sits this far beyond the port district's radius."""

REQUIRED_PRODUCTION_CAMERAS = (
    "CAM_P16_WORLD_HERO",
    "CAM_P16_SYSTEM",
    "CAM_P16_CORE_CONTEXT",
    "CAM_P16_SCAR_CONTEXT",
    "CAM_P16_ROADS",
    "CAM_P16_DENSITY",
    "CAM_P16_VALIDITY",
    "CAM_P16_URBAN",
    "CAM_P16_COMPOSITION",
)


class ProductionContractError(ValueError):
    """A production-world contract violation.

    Raised for malformed specs, unknown district references, geometry that
    would contradict the founding world, and every other Phase 16 refusal.
    Always a refusal, never a repair.
    """


def _require_object(value: object, description: str) -> dict:
    """Return the value if it is a JSON object, else refuse."""
    if not isinstance(value, dict):
        raise ProductionContractError(
            f"{description} must be a JSON object, got {type(value).__name__}"
        )
    return value


def _require_number(value: object, description: str) -> float:
    """Return a finite number, else refuse."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProductionContractError(f"{description} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ProductionContractError(f"{description} must be finite")
    return number


def _require_pair(value: object, description: str) -> tuple[float, float]:
    """Return a 2D coordinate pair, else refuse."""
    if not isinstance(value, list) or len(value) != 2:
        raise ProductionContractError(f"{description} must be a [x, y] pair")
    return (
        _require_number(value[0], f"{description}[0]"),
        _require_number(value[1], f"{description}[1]"),
    )


def _require_path(value: object, description: str, minimum: int = 2) -> list[tuple[float, float]]:
    """Return a polyline of at least ``minimum`` points, else refuse."""
    if not isinstance(value, list) or len(value) < minimum:
        raise ProductionContractError(f"{description} must hold at least {minimum} point(s)")
    return [_require_pair(point, f"{description}[{index}]") for index, point in enumerate(value)]


def _validate_districts(document: dict) -> None:
    """Shape-check the per-district expansion declarations."""
    districts = _require_object(document.get("districts"), "production districts")
    if not districts:
        raise ProductionContractError("production spec must declare district expansions")
    for district_id, entry in districts.items():
        district = _require_object(entry, f"production district {district_id}")
        _require_number(district.get("expansion_radius"), f"{district_id} expansion_radius")


def _validate_neighborhoods(document: dict) -> None:
    """Shape-check every visual quarter declaration."""
    neighborhoods = _require_object(document.get("neighborhoods"), "production neighborhoods")
    for neighborhood_id, entry in neighborhoods.items():
        neighborhood = _require_object(entry, f"neighborhood {neighborhood_id}")
        district = neighborhood.get("district")
        if not isinstance(district, str) or not district:
            raise ProductionContractError(
                f"neighborhood {neighborhood_id} must name its authoritative district"
            )
        _require_pair(neighborhood.get("center"), f"neighborhood {neighborhood_id} center")
        _require_number(neighborhood.get("radius"), f"neighborhood {neighborhood_id} radius")
        _require_number(neighborhood.get("elevation"), f"neighborhood {neighborhood_id} elevation")
        _require_number(neighborhood.get("pitch"), f"neighborhood {neighborhood_id} pitch")
        _require_number(
            neighborhood.get("height_scale"), f"neighborhood {neighborhood_id} height_scale"
        )
        if neighborhood.get("profile") not in QUARTER_PROFILES:
            raise ProductionContractError(
                f"neighborhood {neighborhood_id} profile must be one of "
                f"{QUARTER_PROFILES}, got {neighborhood.get('profile')!r}"
            )
        if neighborhood.get("anchor", "none") not in QUARTER_ANCHORS:
            raise ProductionContractError(
                f"neighborhood {neighborhood_id} anchor must be one of "
                f"{QUARTER_ANCHORS}, got {neighborhood.get('anchor')!r}"
            )
        if neighborhood.get("anchor") == "plaza":
            anchor = neighborhood.get("plaza_anchor")
            if not isinstance(anchor, list) or len(anchor) != 3:
                raise ProductionContractError(
                    f"neighborhood {neighborhood_id} plaza_anchor must be [x, y, radius]"
                )
            for index, value in enumerate(anchor):
                _require_number(value, f"neighborhood {neighborhood_id} plaza_anchor[{index}]")
        yard_street = neighborhood.get("yard_street")
        if yard_street is not None and (not isinstance(yard_street, str) or not yard_street):
            raise ProductionContractError(
                f"neighborhood {neighborhood_id} yard_street must name a street"
            )


def _validate_street_end(street_id: str, end_name: str, value: object) -> None:
    """Shape-check one declared street end."""
    end = _require_object(value, f"street {street_id} {end_name}")
    keys = {"termination", "lands_on", "avenue", "end"}
    unknown = set(end) - keys
    if unknown:
        raise ProductionContractError(
            f"street {street_id} {end_name} has unknown keys {sorted(unknown)}"
        )
    kinds = [key for key in ("termination", "lands_on", "avenue") if key in end]
    if len(kinds) != 1:
        raise ProductionContractError(
            f"street {street_id} {end_name} must declare exactly one of "
            "termination / lands_on / avenue"
        )
    if "termination" in end and end["termination"] not in STREET_TERMINATIONS:
        raise ProductionContractError(
            f"street {street_id} {end_name} termination must be one of "
            f"{STREET_TERMINATIONS}, got {end['termination']!r}"
        )
    if "lands_on" in end and (not isinstance(end["lands_on"], str) or not end["lands_on"]):
        raise ProductionContractError(
            f"street {street_id} {end_name} lands_on must name a district"
        )
    if "avenue" in end:
        if not isinstance(end["avenue"], str) or not end["avenue"]:
            raise ProductionContractError(
                f"street {street_id} {end_name} avenue must name a boundary"
            )
        if end.get("end") not in ("a", "b"):
            raise ProductionContractError(
                f"street {street_id} {end_name} avenue end must be 'a' or 'b'"
            )


def _validate_streets(document: dict) -> None:
    """Shape-check the designed street network.

    Every street is an authored polyline with a hierarchy class; ends may
    declare a ring landing, an avenue continuation, or a termination from the
    fixed taxonomy. Everything else must resolve to a real junction, which
    the road graph proves geometrically.
    """
    streets = _require_object(document.get("streets"), "production streets")
    if not streets:
        raise ProductionContractError("production spec must declare its designed streets")
    for street_id, entry in streets.items():
        street = _require_object(entry, f"street {street_id}")
        if street.get("class") not in STREET_CLASSES:
            raise ProductionContractError(
                f"street {street_id} class must be one of {STREET_CLASSES}, "
                f"got {street.get('class')!r}"
            )
        minimum = 2
        if "end_a" in street or "end_b" in street:
            minimum = 1
        _require_path(street.get("path"), f"street {street_id} path", minimum=minimum)
        for end_name in ("end_a", "end_b"):
            if end_name in street:
                _validate_street_end(street_id, end_name, street[end_name])
        if "trees" in street and street["trees"] not in TREE_LINE_SIDES:
            raise ProductionContractError(
                f"street {street_id} trees must be one of {TREE_LINE_SIDES}, "
                f"got {street['trees']!r}"
            )
        runs = street.get("front_runs", [])
        if not isinstance(runs, list):
            raise ProductionContractError(f"street {street_id} front_runs must be a list")
        for run_index, run_entry in enumerate(runs):
            run = _require_object(run_entry, f"street {street_id} front_runs[{run_index}]")
            if run.get("side") not in ("i", "o"):
                raise ProductionContractError(
                    f"street {street_id} front_runs[{run_index}] side must be 'i' or 'o'"
                )
            span = run.get("range")
            if not isinstance(span, list) or len(span) != 2:
                raise ProductionContractError(
                    f"street {street_id} front_runs[{run_index}] range must be [from, to]"
                )
            for edge_index, edge in enumerate(span):
                _require_number(
                    edge, f"street {street_id} front_runs[{run_index}] range[{edge_index}]"
                )
            if not isinstance(run.get("kind"), str) or not run["kind"]:
                raise ProductionContractError(
                    f"street {street_id} front_runs[{run_index}] must name its massing kind"
                )
            count = run.get("count")
            if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 6:
                raise ProductionContractError(
                    f"street {street_id} front_runs[{run_index}] count must be 1-6"
                )
    orbital = streets.get("orbital")
    if orbital is None or len(orbital.get("path", [])) < 24:
        raise ProductionContractError(
            "the designed network must carry the orbital boulevard as a smooth "
            "sampled curve (at least 24 vertices)"
        )


def _validate_landscape(document: dict) -> None:
    """Shape-check the landscape plan."""
    landscape = _require_object(document.get("landscape"), "landscape plan")
    zones = _require_object(landscape.get("park_zones"), "landscape park_zones")
    if not zones:
        raise ProductionContractError("the landscape plan must declare its park zones")
    for zone_id, entry in zones.items():
        zone = _require_object(entry, f"park zone {zone_id}")
        _require_pair(zone.get("center"), f"park zone {zone_id} center")
        _require_number(zone.get("radius"), f"park zone {zone_id} radius")
    margin = _require_number(landscape.get("keep_margin"), "landscape keep_margin")
    if margin < 0.3:
        raise ProductionContractError(
            "landscape keep_margin must cover the vegetation road clearance (>= 0.3)"
        )
    replant = _require_object(landscape.get("park_replants"), "landscape park_replants")
    _require_number(replant.get("groups_per_zone"), "park_replants groups_per_zone")
    _require_number(replant.get("min_trees"), "park_replants min_trees")
    _require_number(replant.get("max_trees"), "park_replants max_trees")
    street_trees = _require_object(landscape.get("street_trees"), "landscape street_trees")
    _require_number(street_trees.get("spacing"), "street_trees spacing")
    _require_number(street_trees.get("setback"), "street_trees setback")
    gardens = _require_object(landscape.get("plaza_gardens"), "landscape plaza_gardens")
    for district_id, entry in gardens.items():
        garden = _require_object(entry, f"plaza garden {district_id}")
        _require_number(garden.get("count"), f"plaza garden {district_id} count")
        _require_number(garden.get("band"), f"plaza garden {district_id} band")
    promenade = _require_object(landscape.get("promenade"), "landscape promenade")
    _require_number(promenade.get("count"), "promenade count")
    _require_number(promenade.get("setback"), "promenade setback")


BLOCK_FORMS = ("row", "court")

BLOCK_KINDS = (
    "row_low",
    "row_mid",
    "midrise_slab",
    "midrise_court",
    "midrise_point",
    "midrise_pair",
    "court",
    "shed",
    "shed_pair",
    "office_slab",
    "duo_low",
    "duo_mid",
    "single_low",
)
"""Massing vocabulary an authored block may build with (the fabric's own
lot kinds, so blocks and sampled fabric share one material language)."""


def _validate_blocks(document: dict) -> None:
    """Shape-check the authored urban blocks (Schema V3).

    A block is a hand-drawn street wall: the frontage line it stands on,
    which side the street is, how deep, how many units, how tall.
    """
    blocks = _require_object(document.get("blocks"), "designed blocks")
    if not blocks:
        raise ProductionContractError(
            "the final composition must author its urban blocks; a city of "
            "sampled singles is not a designed city"
        )
    for block_id, entry in blocks.items():
        block = _require_object(entry, f"block {block_id}")
        quarter = block.get("quarter")
        if quarter is not None and (not isinstance(quarter, str) or not quarter):
            raise ProductionContractError(f"block {block_id} quarter must name a quarter")
        street = block.get("street")
        if not isinstance(street, str) or not street:
            raise ProductionContractError(f"block {block_id} must name the street it fronts")
        if block.get("side") not in ("i", "o"):
            raise ProductionContractError(f"block {block_id} side must be 'i' or 'o'")
        if block.get("form") not in BLOCK_FORMS:
            raise ProductionContractError(
                f"block {block_id} form must be one of {BLOCK_FORMS}, got {block.get('form')!r}"
            )
        if block.get("kind") not in BLOCK_KINDS:
            raise ProductionContractError(
                f"block {block_id} kind must be one of {BLOCK_KINDS}, got {block.get('kind')!r}"
            )
        span_from = _require_number(block.get("from"), f"block {block_id} from")
        span_to = _require_number(block.get("to"), f"block {block_id} to")
        if span_to - span_from < 4.0:
            raise ProductionContractError(f"block {block_id} frontage is shorter than 4.0")
        depth = _require_number(block.get("depth"), f"block {block_id} depth")
        if not 3.0 <= depth <= 12.0:
            raise ProductionContractError(f"block {block_id} depth must be 3.0-12.0")
        units = block.get("units")
        if isinstance(units, bool) or not isinstance(units, int) or not 1 <= units <= 8:
            raise ProductionContractError(f"block {block_id} units must be 1-8")
        height = _require_number(block.get("height"), f"block {block_id} height")
        if not 3.4 <= height <= 26.0:
            raise ProductionContractError(f"block {block_id} height must be 3.4-26.0")
        if "step" in block:
            step = _require_number(block["step"], f"block {block_id} step")
            if abs(step) > 3.0:
                raise ProductionContractError(f"block {block_id} step must be within +/-3.0")
        if "priority" in block:
            priority = block["priority"]
            if isinstance(priority, bool) or not isinstance(priority, int):
                raise ProductionContractError(f"block {block_id} priority must be an integer")
            if not 0 <= priority <= 99:
                raise ProductionContractError(f"block {block_id} priority must be 0-99")


def _validate_ground(document: dict) -> None:
    """Shape-check the urban ground plan (Schema V3).

    The final composition declares, per district, how its founding ring
    survives (``full`` or ``arcs``) and the authored polygonal skirt
    profile stepping the plate down into the city; plus the authored
    ground cells that carpet the quarters. Geometry-level rules (wall
    corridors, water, burial completeness) belong to ``city_ground``.
    """
    ground = _require_object(document.get("ground"), "urban ground plan")
    plates = _require_object(ground.get("plates"), "ground plates")
    if not plates:
        raise ProductionContractError("the ground plan must reshape the district plates")
    for district_id, entry in plates.items():
        plate = _require_object(entry, f"ground plate {district_id}")
        if plate.get("ring") not in GROUND_RING_MODES:
            raise ProductionContractError(
                f"ground plate {district_id} ring must be one of {GROUND_RING_MODES}, "
                f"got {plate.get('ring')!r}"
            )
        skirt = plate.get("skirt")
        if not isinstance(skirt, list) or len(skirt) < 4:
            raise ProductionContractError(
                f"ground plate {district_id} skirt must hold at least 4 control points"
            )
        for index, control in enumerate(skirt):
            if not isinstance(control, list) or len(control) != 2:
                raise ProductionContractError(
                    f"ground plate {district_id} skirt[{index}] must be [azimuth, reach]"
                )
            azimuth = _require_number(control[0], f"{district_id} skirt[{index}] azimuth")
            reach = _require_number(control[1], f"{district_id} skirt[{index}] reach")
            if not 0.0 <= azimuth <= 360.0:
                raise ProductionContractError(
                    f"ground plate {district_id} skirt[{index}] azimuth must be 0-360"
                )
            if not 0.0 <= reach <= 20.0:
                raise ProductionContractError(
                    f"ground plate {district_id} skirt[{index}] reach must be 0-20"
                )
    if "bury_gap_deg" in ground:
        gap = _require_number(ground["bury_gap_deg"], "ground bury_gap_deg")
        if not 60.0 <= gap <= 180.0:
            raise ProductionContractError("ground bury_gap_deg must be 60-180")
    cells = _require_object(ground.get("cells"), "ground cells")
    if not cells:
        raise ProductionContractError("the ground plan must declare its city ground cells")
    for cell_id, entry in cells.items():
        cell = _require_object(entry, f"ground cell {cell_id}")
        _require_path(cell.get("points"), f"ground cell {cell_id} points", minimum=3)
        level = _require_number(cell.get("level"), f"ground cell {cell_id} level")
        if not 0.05 <= level <= 0.8:
            raise ProductionContractError(
                f"ground cell {cell_id} level must stay in the ground band (0.05-0.8)"
            )
        if cell.get("surface") not in GROUND_CELL_SURFACES:
            raise ProductionContractError(
                f"ground cell {cell_id} surface must be one of {GROUND_CELL_SURFACES}, "
                f"got {cell.get('surface')!r}"
            )


def _validate_cameras(document: dict) -> None:
    """Shape-check the Phase 16 camera anchors."""
    cameras = _require_object(document.get("cameras"), "production cameras")
    for name in REQUIRED_PRODUCTION_CAMERAS:
        camera = _require_object(cameras.get(name), f"camera {name}")
        for key in ("location", "look_at"):
            value = camera.get(key)
            if not isinstance(value, list) or len(value) != 3:
                raise ProductionContractError(f"camera {name} {key} must be [x, y, z]")
            for index, coordinate in enumerate(value):
                _require_number(coordinate, f"camera {name} {key}[{index}]")
        _require_number(camera.get("lens_mm"), f"camera {name} lens_mm")


def load_production_world_spec(path: str | Path) -> dict:
    """Load and shape-validate the Production World Spec V2.

    Raises:
        ProductionContractError: If the document is not a well-formed spec.
    """
    document = _require_object(
        json.loads(Path(path).read_text(encoding="utf-8")), "production world spec"
    )
    if document.get("format") != PRODUCTION_WORLD_FORMAT:
        raise ProductionContractError(
            f"production spec format must be {PRODUCTION_WORLD_FORMAT!r}, "
            f"got {document.get('format')!r}"
        )
    version = document.get("schema_version")
    if isinstance(version, bool) or version != PRODUCTION_WORLD_SCHEMA_VERSION:
        raise ProductionContractError(
            f"production spec schema_version must be {PRODUCTION_WORLD_SCHEMA_VERSION}, "
            f"got {version!r}"
        )
    seed = document.get("visual_seed")
    if not isinstance(seed, str) or not seed.strip():
        raise ProductionContractError("production spec visual_seed must be a non-empty string")
    _require_number(document.get("fabric_limit_radius"), "fabric_limit_radius")
    _validate_districts(document)
    _validate_neighborhoods(document)
    _validate_streets(document)
    _validate_landscape(document)
    _validate_blocks(document)
    _validate_ground(document)
    _validate_cameras(document)
    return document


def port_frame(master_spec: dict) -> tuple[tuple[float, float], tuple[float, float], float]:
    """Return the harbor frame: (port center, coast unit vector, quay distance).

    The coast direction points from the world origin through the port district
    center; the quay line crosses it ``QUAY_OFFSET`` beyond the port radius,
    exactly where the Phase 15 harbor builder placed the quay.
    """
    port = next(
        (entry for entry in master_spec["districts"].values() if entry["character"] == "port"),
        None,
    )
    if port is None:
        raise ProductionContractError("master scene defines no port district")
    center_x, center_y = port["center"]
    length = math.hypot(center_x, center_y) or 1.0
    return (
        (float(center_x), float(center_y)),
        (center_x / length, center_y / length),
        float(port["radius"]) + QUAY_OFFSET,
    )


def coast_coordinate(point: tuple[float, float], master_spec: dict) -> float:
    """Return the along-coast coordinate of a point, measured from port center.

    Values at or beyond the quay distance are open water; production fabric
    must stay on the land side.
    """
    (port_x, port_y), (unit_x, unit_y), _distance = port_frame(master_spec)
    return (point[0] - port_x) * unit_x + (point[1] - port_y) * unit_y


def require_production_agreement(master_spec: dict, production_spec: dict) -> None:
    """Refuse any disagreement between production geography and the master scene.

    The production spec may only EXTEND the founding world: every district
    expansion must reference an authoritative district and reach at least as
    far as its founding plate; every quarter must nest inside its parent
    district's expansion territory, stay off every founding plate, stay out of
    the harbor water, stay inside the fabric limit, and never overlap another
    quarter. Street ends and landscape references must name real founding
    entities. Violations are collected and reported together.

    Raises:
        ProductionContractError: Listing every violated rule.
    """
    errors: list[str] = []
    master_districts = master_spec["districts"]
    expansions = production_spec["districts"]

    for district_id in expansions:
        if district_id not in master_districts:
            errors.append(
                f"district expansion {district_id!r} has no master scene definition; "
                "production may never invent simulation districts"
            )
    for district_id, district in master_districts.items():
        entry = expansions.get(district_id)
        if entry is None:
            errors.append(f"district {district_id} is missing its expansion declaration")
            continue
        expansion = entry["expansion_radius"]
        if expansion < district["radius"] + PLATE_MARGIN:
            errors.append(
                f"district {district_id} expansion_radius {expansion} would shrink "
                f"territory below its founding plate ({district['radius'] + PLATE_MARGIN})"
            )

    neighborhoods = production_spec["neighborhoods"]
    count = len(neighborhoods)
    if not MIN_NEIGHBORHOODS <= count <= MAX_NEIGHBORHOODS:
        errors.append(
            f"production world declares {count} neighborhoods; the target band is "
            f"{MIN_NEIGHBORHOODS}-{MAX_NEIGHBORHOODS}"
        )

    limit = production_spec["fabric_limit_radius"]
    quay_distance = None
    try:
        _center, _unit, quay_distance = port_frame(master_spec)
    except ProductionContractError as error:
        errors.append(str(error))

    for neighborhood_id, neighborhood in neighborhoods.items():
        district_id = neighborhood["district"]
        center = neighborhood["center"]
        radius = neighborhood["radius"]
        if district_id not in master_districts:
            errors.append(
                f"neighborhood {neighborhood_id} claims unknown district {district_id!r}; "
                "visual neighborhoods must nest inside authoritative districts"
            )
            continue
        district = master_districts[district_id]
        expansion_entry = expansions.get(district_id)
        if expansion_entry is not None:
            reach = (
                math.hypot(center[0] - district["center"][0], center[1] - district["center"][1])
                + radius
            )
            if reach > expansion_entry["expansion_radius"] + 1.0e-6:
                errors.append(
                    f"neighborhood {neighborhood_id} reaches {reach:.2f} from "
                    f"{district_id}, beyond its expansion territory "
                    f"({expansion_entry['expansion_radius']})"
                )
        for other_id, other in master_districts.items():
            plate = other["radius"] + PLATE_MARGIN
            gap = math.hypot(center[0] - other["center"][0], center[1] - other["center"][1])
            if gap < plate + radius - 1.0e-6:
                errors.append(
                    f"neighborhood {neighborhood_id} overlaps the founding plate of "
                    f"{other_id} (distance {gap:.2f} < {plate + radius:.2f}); the "
                    "historic core is never built over"
                )
        if math.hypot(center[0], center[1]) + radius > limit + 1.0e-6:
            errors.append(f"neighborhood {neighborhood_id} exceeds the fabric limit radius {limit}")
        if quay_distance is not None:
            far_edge = coast_coordinate(center, master_spec) + radius
            if far_edge > quay_distance - 1.2:
                errors.append(
                    f"neighborhood {neighborhood_id} reaches coast coordinate "
                    f"{far_edge:.2f}, into the harbor water (quay at {quay_distance:.2f})"
                )

    ordered = sorted(neighborhoods.items())
    for index, (first_id, first) in enumerate(ordered):
        for second_id, second in ordered[index + 1 :]:
            gap = math.hypot(
                first["center"][0] - second["center"][0],
                first["center"][1] - second["center"][1],
            )
            if gap < first["radius"] + second["radius"] - 1.0e-6:
                errors.append(
                    f"neighborhoods {first_id} and {second_id} overlap "
                    f"(distance {gap:.2f} < {first['radius'] + second['radius']:.2f})"
                )

    for street_id, street in sorted(production_spec["streets"].items()):
        for end_name in ("end_a", "end_b"):
            end = street.get(end_name)
            if not isinstance(end, dict):
                continue
            if "lands_on" in end and end["lands_on"] not in master_districts:
                errors.append(
                    f"street {street_id} {end_name} lands on unknown district {end['lands_on']!r}"
                )
            if "avenue" in end and end["avenue"] not in master_spec["boundaries"]:
                errors.append(
                    f"street {street_id} {end_name} continues unknown avenue {end['avenue']!r}"
                )

    for district_id in production_spec["landscape"]["plaza_gardens"]:
        if district_id not in master_districts:
            errors.append(f"plaza garden references unknown district {district_id!r}")

    for block_id, block in sorted(production_spec["blocks"].items()):
        quarter = block.get("quarter")
        if quarter is not None and quarter not in neighborhoods:
            errors.append(
                f"block {block_id} belongs to unknown quarter {quarter!r}; "
                "designed blocks build inside declared quarters"
            )
        if block["street"] not in production_spec["streets"]:
            errors.append(
                f"block {block_id} fronts {block['street']!r}, which is not a designed street"
            )

    ground_plates = production_spec["ground"]["plates"]
    for district_id in ground_plates:
        if district_id not in master_districts:
            errors.append(
                f"ground plate {district_id!r} has no master scene definition; "
                "the ground plan reshapes real districts only"
            )
    for district_id in master_districts:
        if district_id not in ground_plates:
            errors.append(
                f"district {district_id} is missing its ground plate declaration; "
                "every founding plate joins the final composition"
            )

    for neighborhood_id, neighborhood in sorted(neighborhoods.items()):
        yard_street = neighborhood.get("yard_street")
        if yard_street is not None and yard_street not in production_spec["streets"]:
            errors.append(
                f"neighborhood {neighborhood_id} yard_street {yard_street!r} "
                "is not a declared street"
            )

    if errors:
        raise ProductionContractError(
            "production world disagrees with the master scene:\n- " + "\n- ".join(errors)
        )
