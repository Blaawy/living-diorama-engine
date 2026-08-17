"""Add the Phase 16 production city onto the built Phase 15 master scene.

Runs inside Blender (``bpy``). The founding world must already exist --
:func:`add_production_world` refuses to run otherwise -- and is NEVER
touched: every object this module creates carries an ``LD_P16_`` prefix (or
``CAM_P16_`` for cameras) inside its own ``LD_PRODUCTION`` collection tree,
and every founding object keeps its exact name, transform, and data.

Everything placed here comes from the validated pure plan: the road graph
(:mod:`road_graph`) decides every street, the fabric plan
(:mod:`urban_fabric`) decides every pad, lot, plaza, and container row. The
builder instantiates; it does not decide. Rebuilding replaces objects by
name, so repeated builds converge instead of growing ``.001`` copies.

Run headless (after ``build_master_scene.py`` in the same session)::

    blender --background --factory-startup --python build_production_world.py \
        -- --spec master_scene_v1.json --production production_world_v1.json \
        --style dna --save world.blend
"""

import argparse
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))

from blender_runtime import (  # noqa: E402
    FacadeStyle,
    add_bevel,
    link_only,
    look_at_rotation,
    make_box,
    make_cylinder,
    make_detail_mesh,
    make_light,
    make_ribbon,
    make_windowed_mass,
    replace_object,
    require_supported_blender,
    set_practical_light_scale,
)
from build_master_scene import ROAD_LEVEL, trim_ring_disc  # noqa: E402
from city_ground import ground_level_at, kept_ring_paths  # noqa: E402
from production_spec import (  # noqa: E402
    load_production_world_spec,
    require_production_agreement,
)
from road_graph import (  # noqa: E402
    ROAD_CLASS_WIDTHS,
    build_road_graph,
    junction_pads,
)
from scene_spec import load_master_scene_spec, stable_rng  # noqa: E402
from style_profiles import resolve_style  # noqa: E402
from urban_fabric import (  # noqa: E402
    lot_extents,
    plan_urban_fabric,
    plinth_shape,
    validate_urban_fabric,
)

PRODUCTION_ROOT = "LD_PRODUCTION"
PRODUCTION_CHILDREN = ("LD_P16_STREETS", "LD_P16_FABRIC", "LD_P16_GROUND")

GROUND_MATERIALS = {
    "pavement": "pavement",
    "concrete": "concrete",
    "lawn": "terrain",
}
"""Which existing material each ground surface uses -- the composition
introduces no new material role."""

RING_ARC_WIDTH = 5.2
"""Carriageway width of a preserved founding ring arc (collector class)."""

CLASS_ELEVATION = {
    "arterial": ROAD_LEVEL,
    "collector": ROAD_LEVEL - 0.008,
    "local": ROAD_LEVEL - 0.016,
    "service": ROAD_LEVEL - 0.012,
}
"""Per-class deck heights: crossings meet under one junction pad, never
z-fighting, with the founding avenues keeping the highest deck."""

JUNCTION_PAD_TOP = ROAD_LEVEL + 0.123
LAMP_SPACING = {"arterial": 11.0, "collector": 13.0}

PROFILE_STYLES = {
    "midrise_front": FacadeStyle(
        bay_pitch=1.35,
        floor_height=2.8,
        window_frac=0.58,
        sill=0.8,
        head=0.4,
        recess=0.18,
        plinth=0.4,
        parapet=0.5,
    ),
    "business": FacadeStyle(
        bay_pitch=1.35,
        floor_height=2.9,
        window_frac=0.62,
        sill=0.75,
        head=0.4,
        recess=0.18,
        plinth=0.4,
        parapet=0.55,
        ground_floor=3.4,
        ground_window_frac=0.74,
        ground_sill=0.4,
    ),
    "grid_rows": FacadeStyle(
        bay_pitch=1.3,
        floor_height=2.7,
        window_frac=0.46,
        sill=0.85,
        head=0.45,
        recess=0.2,
        plinth=0.4,
        parapet=0.5,
    ),
    "scar_rows": FacadeStyle(
        bay_pitch=1.3,
        floor_height=2.7,
        window_frac=0.5,
        sill=0.8,
        head=0.4,
        recess=0.18,
        plinth=0.4,
        parapet=0.45,
    ),
    "garden_rows": FacadeStyle(
        bay_pitch=1.25,
        floor_height=2.55,
        window_frac=0.48,
        sill=0.8,
        head=0.4,
        recess=0.18,
        plinth=0.35,
        parapet=0.4,
    ),
    "meadow_courts": FacadeStyle(
        bay_pitch=1.25,
        floor_height=2.55,
        window_frac=0.48,
        sill=0.8,
        head=0.4,
        recess=0.18,
        plinth=0.35,
        parapet=0.4,
    ),
    "industrial": FacadeStyle(
        bay_pitch=2.2,
        floor_height=2.0,
        margin=0.7,
        window_frac=0.55,
        sill=1.1,
        head=0.25,
        recess=0.12,
        frame=0.06,
        plinth=2.6,
        parapet=0.4,
        mullion=False,
    ),
    "port_yard": FacadeStyle(
        bay_pitch=2.2,
        floor_height=2.0,
        margin=0.7,
        window_frac=0.5,
        sill=1.1,
        head=0.25,
        recess=0.12,
        frame=0.06,
        plinth=2.4,
        parapet=0.35,
        mullion=False,
    ),
}
"""Per-profile facade language, one notch finer than the founding archetypes."""

MIDRISE_STYLE = FacadeStyle(
    bay_pitch=1.35,
    floor_height=2.9,
    window_frac=0.6,
    sill=0.75,
    head=0.4,
    recess=0.18,
    plinth=0.45,
    parapet=0.55,
    ground_floor=3.4,
    ground_window_frac=0.7,
    ground_sill=0.4,
)
"""The middle scale reads as real floors: taller storeys, generous glass."""

MIDRISE_KINDS = (
    "midrise_slab",
    "midrise_court",
    "midrise_point",
    "midrise_pair",
    "row_mid",
    "duo_mid",
    "office_slab",
)

CHARACTER_MATERIAL_KEYS = {
    "civic": ("facade_civic", "frame_metal", "glass_civic", "roof_dark", "interior_glow"),
    "port": ("facade_port", "frame_metal", "glass_port", "roof_dark", "interior_glow"),
    "residential": (
        "facade_residential",
        "frame_metal",
        "glass_residential",
        "roof_dark",
        "interior_glow",
    ),
    "terrace": ("facade_terrace", "frame_metal", "glass_terrace", "roof_dark", "interior_glow"),
}


def ensure_production_collections() -> dict:
    """Create (or fetch) the Phase 16 collection tree under LD_WORLD."""
    root_world = bpy.data.collections.get("LD_WORLD")
    if root_world is None:
        raise RuntimeError(
            "the master scene is not built; run build_master_scene before "
            "adding the production world"
        )
    production = bpy.data.collections.get(PRODUCTION_ROOT)
    if production is None:
        production = bpy.data.collections.new(PRODUCTION_ROOT)
    if production.name not in {child.name for child in root_world.children}:
        root_world.children.link(production)
    collections = {PRODUCTION_ROOT: production}
    for name in PRODUCTION_CHILDREN:
        child = bpy.data.collections.get(name)
        if child is None:
            child = bpy.data.collections.new(name)
        if child.name not in {existing.name for existing in production.children}:
            production.children.link(child)
        collections[name] = child
    return collections


def _scene_materials() -> dict:
    """The already-built LD material family, keyed by role."""
    materials = {
        name.removeprefix("LD_MAT__"): material
        for name, material in ((entry.name, entry) for entry in bpy.data.materials)
        if name.startswith("LD_MAT__")
    }
    if "pavement" not in materials:
        raise RuntimeError("the master scene material family is missing; build it first")
    return materials


def _emit_prism(
    builder: bmesh.types.BMesh,
    points: list,
    top: float,
    material_index: int,
    base: float = 0.02,
) -> None:
    """Add one flat polygonal slab (a ground panel) to a bmesh."""
    verts = [builder.verts.new((float(x), float(y), top)) for x, y in points]
    try:
        face = builder.faces.new(verts)
    except ValueError:
        return
    face.material_index = material_index
    result = bmesh.ops.extrude_face_region(builder, geom=[face])
    moved = [item for item in result["geom"] if isinstance(item, bmesh.types.BMVert)]
    bmesh.ops.translate(builder, verts=moved, vec=Vector((0.0, 0.0, base - top)))
    for element in result["geom"]:
        if isinstance(element, bmesh.types.BMFace):
            element.material_index = material_index


def _finish_ground_mesh(name: str, builder: bmesh.types.BMesh, collection, materials: list) -> None:
    """Turn a ground bmesh into one replaced, beveled scene object."""
    if not builder.faces:
        builder.free()
        return
    bmesh.ops.recalc_face_normals(builder, faces=list(builder.faces))
    replace_object(name)
    mesh = bpy.data.meshes.new(name)
    builder.to_mesh(mesh)
    builder.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = (0.0, 0.0, 0.0)
    for material in materials:
        obj.data.materials.append(material)
    add_bevel(obj, width=0.04)
    link_only(obj, collection)


def build_city_ground(plan: dict, collections: dict, materials: dict) -> None:
    """The final urban composition's ground: plate tables, skirts, cells.

    Each district becomes ONE merged object carrying its terraced table
    and skirt panels, so the founding circle is replaced by designed,
    block-aligned city floor without multiplying objects. The authored
    ground cells become a second merged object per surface, welding
    streets, plinths, parks, and quarters into one continuous fabric.
    """
    collection = collections["LD_P16_GROUND"]
    ground = plan["ground"]
    for district_id, plate in sorted(ground["plates"].items()):
        builder = bmesh.new()
        for piece in plate["pieces"]:
            _emit_prism(builder, piece["points"], float(piece["level"]), 0)
        _finish_ground_mesh(
            f"LD_P16_GROUND__{district_id}", builder, collection, [materials["pavement"]]
        )
    by_surface: dict[str, list] = {}
    for cell_id, cell in sorted(ground["cells"].items()):
        by_surface.setdefault(cell["surface"], []).append((cell_id, cell))
    for surface, entries in sorted(by_surface.items()):
        builder = bmesh.new()
        for _cell_id, cell in entries:
            _emit_prism(builder, cell["points"], float(cell["level"]), 0)
        _finish_ground_mesh(
            f"LD_P16_GROUND__cells_{surface}",
            builder,
            collection,
            [materials[GROUND_MATERIALS[surface]]],
        )


def trim_kept_ring_discs(plan: dict, master_spec: dict, materials: dict) -> dict[str, int]:
    """Cut the founding towers' footings out of the ring discs the city keeps.

    A district whose circle survives whole still draws its Phase 15 asphalt
    disc, and on the civic plate that disc runs straight under two founding
    towers. The lane network already refuses those sectors; this stops
    drawing them, from the same footprints, so the picture agrees with the
    traffic. The object keeps its name -- the composition still asks a
    ``full`` ring for its founding disc -- and districts whose ring is
    buried are untouched here, because their disc is suppressed outright.
    """
    trimmed: dict[str, int] = {}
    collection = bpy.data.collections.get("LD_DISTRICTS")
    if collection is None:
        return trimmed
    for district_id, plate in sorted(plan["ground"]["plates"].items()):
        if plate["ring"] != "full":
            continue
        sectors = trim_ring_disc(master_spec, district_id, collection, materials["asphalt"])
        if sectors:
            trimmed[district_id] = sectors
    return trimmed


def build_ring_arcs(plan: dict, master_spec: dict, collections: dict, materials: dict) -> None:
    """Redraw the founding ring arcs the composition keeps as real streets.

    Where a district's ring survives only in part, the founding ring disc
    is suppressed and the KEPT arcs are rebuilt here as proper
    carriageways: the sectors that carried no traffic disappear under the
    urban table, and the ones that serve street landings stay visible as
    the streets they always were. A district whose ring is kept whole
    (the civic Ring around the Seal) is never touched.
    """
    collection = collections["LD_P16_STREETS"]
    for district_id, plate in sorted(plan["ground"]["plates"].items()):
        if plate["ring"] == "full":
            continue
        elevation = float(master_spec["districts"][district_id]["elevation"])
        for index, path in enumerate(kept_ring_paths(master_spec, plan["ground"], district_id)):
            make_ribbon(
                f"LD_P16_RING__{district_id}__{index:02d}",
                [(float(x), float(y)) for x, y in path],
                RING_ARC_WIDTH,
                0.06,
                elevation + 0.55,
                collection,
                materials["asphalt"],
            )


def build_plinths(plan: dict, collections: dict, materials: dict) -> None:
    """Per-lot plinths and frontage strips: ground derived from the lots.

    No circular quarter pads: every lot stands on its own rectangular
    plinth (footprint hull plus margin), and lots close to their street
    get a paved frontage strip welding the block to the carriageway --
    blocks against streets, never pods against roads.
    """
    collection = collections["LD_P16_FABRIC"]
    for _neighborhood_id, entry in sorted(plan["neighborhoods"].items()):
        for lot in entry["lots"]:
            top = lot["plinth_top"]
            shape = plinth_shape(lot)
            make_box(
                f"LD_P16_BLDG__{lot['name']}__plinth",
                (shape["hw"] * 2.0, shape["hd"] * 2.0, top - 0.02),
                (shape["x"], shape["y"], 0.02),
                collection,
                materials["pavement"],
                rotation_z=shape["rot"],
                bevel=0.06,
            )
            face_x, face_y = lot["face"]
            gap = math.hypot(face_x - lot["x"], face_y - lot["y"])
            half_w, front, _back = lot_extents(lot["masses"])
            strip_len = gap - front - 0.4
            if 0.8 < strip_len < 7.0:
                direction = ((face_x - lot["x"]) / gap, (face_y - lot["y"]) / gap)
                mid = (
                    lot["x"] + direction[0] * (front + strip_len / 2.0),
                    lot["y"] + direction[1] * (front + strip_len / 2.0),
                )
                make_box(
                    f"LD_P16_BLDG__{lot['name']}__walk",
                    (min(6.0, half_w * 2.0), strip_len, 0.14),
                    (mid[0], mid[1], 0.05),
                    collection,
                    materials["pavement"],
                    rotation_z=lot["rotation"],
                    bevel=0.03,
                )


def _segment_lamps(
    segment_id: str,
    segment: dict,
    elevation: float,
    collections: dict,
    materials: dict,
) -> None:
    """One merged lamp run for a production arterial or collector."""
    spacing = LAMP_SPACING.get(segment["class"])
    if spacing is None:
        return
    boxes = []
    path = segment["path"]
    carried = spacing * 0.5
    index = 0
    for (x0, y0), (x1, y1) in zip(path, path[1:], strict=False):
        leg = math.hypot(x1 - x0, y1 - y0)
        if leg == 0.0:
            continue
        heading = math.atan2(y1 - y0, x1 - x0)
        distance = carried
        while distance <= leg:
            t = distance / leg
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t
            side = 1.0 if index % 2 == 0 else -1.0
            unit_nx, unit_ny = -math.sin(heading) * side, math.cos(heading) * side
            reach = ROAD_CLASS_WIDTHS[segment["class"]] / 2.0 + 0.65
            pole_x, pole_y = x + unit_nx * reach, y + unit_ny * reach
            boxes.append(((0.13, 0.13, 4.6), (pole_x, pole_y, 0.0), 0, heading))
            boxes.append(
                (
                    (0.10, 1.5, 0.09),
                    (pole_x - unit_nx * 0.75, pole_y - unit_ny * 0.75, 4.6),
                    0,
                    heading,
                )
            )
            boxes.append(
                (
                    (0.34, 0.6, 0.1),
                    (pole_x - unit_nx * 1.35, pole_y - unit_ny * 1.35, 4.54),
                    0,
                    heading,
                )
            )
            boxes.append(
                (
                    (0.26, 0.48, 0.05),
                    (pole_x - unit_nx * 1.35, pole_y - unit_ny * 1.35, 4.5),
                    1,
                    heading,
                )
            )
            index += 1
            distance += spacing
        carried = distance - leg
    if not boxes:
        return
    first = boxes[0][1]
    make_detail_mesh(
        f"LD_P16_STREET__{segment_id}__lamps",
        [
            (size, (ox - first[0], oy - first[1], oz), material, rot)
            for size, (ox, oy, oz), material, rot in boxes
        ],
        (first[0], first[1], elevation + 0.1),
        collections["LD_P16_STREETS"],
        [materials["metal_dark"], materials["warm_light"]],
    )


def build_streets(graph: dict, collections: dict, materials: dict) -> None:
    """Every production street the graph declares, plus markings and lamps."""
    collection = collections["LD_P16_STREETS"]
    for segment_id, segment in sorted(graph["segments"].items()):
        if segment["existing"]:
            continue
        elevation = CLASS_ELEVATION[segment["class"]]
        width = ROAD_CLASS_WIDTHS[segment["class"]]
        make_ribbon(
            f"LD_P16_STREET__{segment_id}",
            segment["path"],
            width,
            0.12,
            elevation,
            collection,
            materials["asphalt"],
        )
        if segment["class"] == "arterial":
            dashes = []
            carried = 4.2 * 0.5
            for (x0, y0), (x1, y1) in zip(segment["path"], segment["path"][1:], strict=False):
                leg = math.hypot(x1 - x0, y1 - y0)
                if leg == 0.0:
                    continue
                heading = math.atan2(y1 - y0, x1 - x0)
                distance = carried
                while distance <= leg:
                    t = distance / leg
                    dashes.append(
                        (
                            (1.7, 0.15, 0.01),
                            (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, 0.0),
                            0,
                            heading,
                        )
                    )
                    distance += 4.2
                carried = distance - leg
            if dashes:
                first = dashes[0][1]
                make_detail_mesh(
                    f"LD_P16_STREET__{segment_id}__marks",
                    [
                        (size, (ox - first[0], oy - first[1], oz), material, rot)
                        for size, (ox, oy, oz), material, rot in dashes
                    ],
                    (first[0], first[1], elevation + 0.121),
                    collection,
                    [materials["road_marking"]],
                    bevel=0.0,
                )
        _segment_lamps(segment_id, segment, elevation, collections, materials)


def _node_uses(graph: dict) -> dict:
    """Count, per node id, how many segments reference it."""
    uses: dict[str, int] = {}
    for segment in graph["segments"].values():
        node_ids = []
        for end in (segment["end_a"], segment["end_b"]):
            if end is not None and "node" in end:
                node_ids.append(end["node"])
        node_ids.extend(segment["via"])
        for node_id in set(node_ids):
            uses[node_id] = uses.get(node_id, 0) + 1
    return uses


def build_junctions(graph: dict, collections: dict, materials: dict) -> None:
    """One merged mesh of junction discs and cul-de-sac turnarounds.

    Every shared node gets a pad wide enough for its widest street; every
    intentional cul-de-sac gets a visible turnaround disc. Broken-looking
    street ends therefore cannot exist: an end is a junction pad, a
    turnaround, or a declared destination.
    """
    builder = bmesh.new()

    def emit_disc(x: float, y: float, radius: float) -> None:
        result = bmesh.ops.create_cone(
            builder,
            cap_ends=True,
            segments=24,
            radius1=radius,
            radius2=radius,
            depth=0.118,
        )
        for vert in result["verts"]:
            vert.co.x += x
            vert.co.y += y
            vert.co.z += 0.059

    uses = _node_uses(graph)
    node_width: dict[str, float] = {}
    for segment in graph["segments"].values():
        if segment["existing"]:
            continue
        node_ids = [*segment["via"]]
        for end in (segment["end_a"], segment["end_b"]):
            if end is not None and "node" in end:
                node_ids.append(end["node"])
        for node_id in node_ids:
            width = ROAD_CLASS_WIDTHS[segment["class"]]
            node_width[node_id] = max(node_width.get(node_id, 0.0), width)
    for node_id, width in sorted(node_width.items()):
        if uses.get(node_id, 0) < 2:
            continue
        node = graph["nodes"][node_id]
        emit_disc(node["x"], node["y"], width / 2.0 + 1.0)
    for _segment_id, segment in sorted(graph["segments"].items()):
        if segment["existing"]:
            continue
        for end, point in (
            (segment["end_a"], segment["path"][0]),
            (segment["end_b"], segment["path"][-1]),
        ):
            if end is None or "termination" not in end:
                continue
            if end["termination"] == "cul_de_sac":
                emit_disc(point[0], point[1], ROAD_CLASS_WIDTHS[segment["class"]] / 2.0 + 1.6)
            elif end["termination"] == "port_quay":
                emit_disc(point[0], point[1], ROAD_CLASS_WIDTHS[segment["class"]] / 2.0 + 0.8)

    name = "LD_P16_JUNCTIONS"
    replace_object(name)
    mesh = bpy.data.meshes.new(name)
    builder.to_mesh(mesh)
    builder.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = (0.0, 0.0, JUNCTION_PAD_TOP - 0.118)
    obj.data.materials.append(materials["asphalt"])
    add_bevel(obj, width=0.03)
    link_only(obj, collections["LD_P16_STREETS"])


def _entrance_facade(rotation: float, position: tuple[float, float], face: tuple[float, float]):
    """Pick the facade index (+Y, -Y, +X, -X) facing the fronted street."""
    target = math.atan2(face[1] - position[1], face[0] - position[0])
    normals = (
        rotation + math.pi / 2.0,
        rotation - math.pi / 2.0,
        rotation,
        rotation + math.pi,
    )
    scores = [math.cos(target - normal) for normal in normals]
    return scores.index(max(scores))


def _lot_details(
    name: str,
    lot: dict,
    base_z: float,
    tallest: float,
    rng,
    collection,
    materials: dict,
) -> None:
    """Parapets, rooftop units, and (for towers) a crown and beacon."""
    boxes = []
    for mass in lot["masses"]:
        width, depth, height = mass["w"], mass["d"], mass["h"]
        rim = 0.22
        top = height
        boxes.append(((width, rim, 0.4), (mass["ox"], mass["oy"] + depth / 2 - rim / 2, top), 0))
        boxes.append(((width, rim, 0.4), (mass["ox"], mass["oy"] - depth / 2 + rim / 2, top), 0))
        for side in (1.0, -1.0):
            boxes.append(
                (
                    (rim, depth - 2 * rim, 0.4),
                    (mass["ox"] + side * (width / 2 - rim / 2), mass["oy"], top),
                    0,
                )
            )
        for _ in range(rng.randint(1, 2)):
            boxes.append(
                (
                    (rng.uniform(0.7, 1.3), rng.uniform(0.7, 1.1), rng.uniform(0.4, 0.9)),
                    (
                        mass["ox"] + rng.uniform(-width * 0.28, width * 0.28),
                        mass["oy"] + rng.uniform(-depth * 0.28, depth * 0.28),
                        top,
                    ),
                    0,
                )
            )
    if tallest >= 18.0:
        boxes.append(((1.2, 1.2, 1.6), (0.0, 0.0, tallest), 0))
        boxes.append(((0.08, 0.08, 1.8), (0.0, 0.0, tallest + 1.6), 0))
        boxes.append(((0.2, 0.2, 0.2), (0.0, 0.0, tallest + 3.4), 1))
    make_detail_mesh(
        f"{name}__detail",
        boxes,
        (lot["x"], lot["y"], base_z),
        collection,
        [materials["metal_dark"], materials["warning_red"]],
        rotation_z=lot["rotation"],
    )


def build_fabric(
    plan: dict, master_spec: dict, production_spec: dict, collections: dict, materials: dict
) -> None:
    """Every lot, plaza, and container row the fabric plan declares."""
    seed = production_spec["visual_seed"]
    collection = collections["LD_P16_FABRIC"]
    for neighborhood_id, entry in sorted(plan["neighborhoods"].items()):
        district = master_spec["districts"][entry["district"]]
        character = district["character"]
        material_keys = CHARACTER_MATERIAL_KEYS[character]
        profile_style = PROFILE_STYLES.get(entry["profile"], PROFILE_STYLES["grid_rows"])
        for lot in entry["lots"]:
            style = MIDRISE_STYLE if lot["kind"] in MIDRISE_KINDS else profile_style
            name = f"LD_P16_BLDG__{lot['name']}"
            base_z = lot["plinth_top"]
            rng = stable_rng(seed, "detail", lot["name"])
            entrance = _entrance_facade(lot["rotation"], (lot["x"], lot["y"]), lot["face"])
            tallest = 0.0
            cos_r, sin_r = math.cos(lot["rotation"]), math.sin(lot["rotation"])
            for mass_index, mass in enumerate(lot["masses"]):
                offset_x = mass["ox"] * cos_r - mass["oy"] * sin_r
                offset_y = mass["ox"] * sin_r + mass["oy"] * cos_r
                tallest = max(tallest, mass["h"])
                make_windowed_mass(
                    f"{name}__m{mass_index}",
                    (mass["w"], mass["d"], mass["h"]),
                    (lot["x"] + offset_x, lot["y"] + offset_y, base_z),
                    collection,
                    materials,
                    style,
                    rotation_z=lot["rotation"],
                    entrance_facade=entrance if mass_index == 0 else None,
                    material_keys=material_keys,
                )
            _lot_details(name, lot, base_z, tallest, rng, collection, materials)

        plaza = entry["plaza"]
        if plaza is not None:
            pad_top = plaza["base"]
            make_cylinder(
                f"LD_P16_PLAZA__{neighborhood_id}",
                plaza["radius"],
                0.14,
                (plaza["center"][0], plaza["center"][1], pad_top),
                collection,
                materials["concrete"],
                segments=48,
                bevel=0.05,
            )
            masts = []
            for index in range(6):
                angle = index * math.pi / 3.0
                px = math.cos(angle) * plaza["radius"] * 0.8
                py = math.sin(angle) * plaza["radius"] * 0.8
                masts.append(((0.16, 0.16, 3.4), (px, py, 0.14), 0))
                masts.append(((0.26, 0.26, 0.12), (px, py, 3.54), 1))
            masts.append(((0.8, 0.8, 5.6), (0.0, 0.0, 0.14), 0))
            masts.append(((0.5, 0.5, 0.4), (0.0, 0.0, 5.74), 1))
            make_detail_mesh(
                f"LD_P16_PLAZA__{neighborhood_id}__masts",
                masts,
                (plaza["center"][0], plaza["center"][1], pad_top),
                collection,
                [materials["metal_civic"], materials["warm_light"]],
            )

        for green in entry["greens"]:
            _build_green(green, green["base"], collection, materials, seed)

        for row in entry["yard_rows"]:
            rng = stable_rng(seed, "stack", row["name"])
            boxes = []
            palette = ("container_a", "container_b", "container_c")
            for tier in range(row["tiers"]):
                boxes.append(
                    (
                        (row["length"], 2.3, 2.15),
                        (rng.uniform(-0.2, 0.2), rng.uniform(-0.15, 0.15), tier * 2.15),
                        rng.randint(0, 2),
                    )
                )
            make_detail_mesh(
                f"LD_P16_YARD__{row['name']}",
                boxes,
                (row["x"], row["y"], row["base"]),
                collection,
                [materials[key] for key in palette],
                rotation_z=row["heading"],
            )


def _build_green(green: dict, pad_top: float, collection, materials: dict, seed: str) -> None:
    """One pocket park: a small deterministic tree cluster on the pad."""
    name = f"LD_P16_GREEN__{green['name']}"
    replace_object(name)
    rng = stable_rng(seed, "green", green["name"])
    spread = green.get("spread", 2.2)
    builder = bmesh.new()
    for _ in range(green["trees"]):
        ox = rng.uniform(-spread, spread)
        oy = rng.uniform(-spread, spread)
        trunk_height = rng.uniform(0.7, 1.2)
        canopy_radius = rng.uniform(0.8, 1.5)
        result = bmesh.ops.create_icosphere(builder, subdivisions=2, radius=canopy_radius)
        canopy_faces = {face for vert in result["verts"] for face in vert.link_faces}
        for face in canopy_faces:
            face.material_index = 0
            face.smooth = True
        for vert in result["verts"]:
            wobble = 1.0 + rng.uniform(-0.09, 0.09)
            vert.co.x = vert.co.x * 1.05 * wobble + ox
            vert.co.y = vert.co.y * 1.05 * wobble + oy
            vert.co.z = vert.co.z * 0.8 * wobble + trunk_height + canopy_radius * 0.7
        trunk = bmesh.ops.create_cone(
            builder,
            cap_ends=True,
            segments=6,
            radius1=0.11,
            radius2=0.08,
            depth=trunk_height + canopy_radius,
        )
        trunk_faces = {face for vert in trunk["verts"] for face in vert.link_faces}
        for face in trunk_faces:
            face.material_index = 1
        for vert in trunk["verts"]:
            vert.co.x += ox
            vert.co.y += oy
            vert.co.z += (trunk_height + canopy_radius) / 2.0
    mesh = bpy.data.meshes.new(name)
    builder.to_mesh(mesh)
    builder.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = (green["x"], green["y"], pad_top)
    obj.data.materials.append(materials["foliage"])
    obj.data.materials.append(materials["bark"])
    link_only(obj, collection)


def build_port_lights(
    plan: dict,
    production_spec: dict,
    master_spec: dict,
    graph: dict,
    collections: dict,
    materials: dict,
) -> None:
    """Working light for the port quarters: yard floods and quay lamps.

    The industrial city must survive civil twilight: each port-character
    quarter gets two flood masts with real lights, and each quay apron one
    lamp -- practical fixtures scaled by the active style profile, no
    global lighting change, no new materials.
    """
    from production_spec import port_frame

    _center, (unit_x, unit_y), _quay = port_frame(master_spec)
    lateral = (-unit_y, unit_x)
    flood_positions: list[tuple[str, float, float, float]] = []
    for neighborhood_id, entry in sorted(plan["neighborhoods"].items()):
        district = master_spec["districts"][entry["district"]]
        if district["character"] != "port":
            continue
        neighborhood = production_spec["neighborhoods"][neighborhood_id]
        center = (float(neighborhood["center"][0]), float(neighborhood["center"][1]))
        radius = float(neighborhood["radius"])
        for sign, tag in ((1.0, "a"), (-1.0, "b")):
            mast_x = center[0] + lateral[0] * sign * 0.45 * radius
            mast_y = center[1] + lateral[1] * sign * 0.45 * radius
            flood_positions.append(
                (
                    f"{neighborhood_id}_{tag}",
                    mast_x,
                    mast_y,
                    max(
                        entry["plinth_top"],
                        ground_level_at((mast_x, mast_y), plan["ground"]),
                    ),
                )
            )
    for label, x, y, base in flood_positions:
        make_detail_mesh(
            f"LD_P16_FLOOD__{label}",
            [
                ((0.28, 0.28, 7.4), (0.0, 0.0, 0.0), 0),
                ((1.5, 0.34, 0.3), (0.0, 0.0, 7.4), 0),
                ((0.42, 0.3, 0.16), (-0.5, 0.0, 7.32), 1),
                ((0.42, 0.3, 0.16), (0.5, 0.0, 7.32), 1),
            ],
            (x, y, base),
            collections["LD_P16_FABRIC"],
            [materials["metal_civic"], materials["cool_light"]],
        )
        make_light(
            f"LD_P16_FLOOD__{label}__light",
            "POINT",
            (x, y, base + 7.1),
            collections["LD_P16_STREETS"],
            energy=340.0,
            color=(0.93, 0.93, 0.88),
            size=0.6,
        )
    for pad_index, pad in enumerate(junction_pads(graph)):
        if pad["kind"] != "quay_apron":
            continue
        make_light(
            f"LD_P16_QUAYLAMP__{pad_index:02d}",
            "POINT",
            (pad["x"], pad["y"], ROAD_LEVEL + 5.4),
            collections["LD_P16_STREETS"],
            energy=180.0,
            color=(1.0, 0.72, 0.4),
            size=0.4,
        )


def build_production_cameras(production_spec: dict) -> None:
    """The Phase 16 camera anchors (the five founding anchors stay put)."""
    collection = bpy.data.collections["LD_CAMERAS"]
    for name, definition in sorted(production_spec["cameras"].items()):
        replace_object(name)
        camera_data = bpy.data.cameras.get(name)
        if camera_data is None:
            camera_data = bpy.data.cameras.new(name)
        camera_data.lens = definition["lens_mm"]
        camera_data.clip_end = 1200.0
        location = Vector(definition["location"])
        target = Vector(definition["look_at"])
        if name in ("CAM_P16_ROADS", "CAM_P16_VALIDITY"):
            camera_data.dof.use_dof = False
        else:
            camera_data.dof.use_dof = True
            focus = Vector(definition.get("focus", definition["look_at"]))
            camera_data.dof.focus_distance = (focus - location).length
            camera_data.dof.aperture_fstop = definition.get("f_stop", 8.0)
        camera = bpy.data.objects.new(name, camera_data)
        camera.location = location
        camera.rotation_euler = look_at_rotation(location, target)
        link_only(camera, collection)


def suppressed_ring_objects(plan: dict) -> list[str]:
    """The founding ring discs the final composition replaces.

    A district whose ring survives only as arcs hands its whole founding
    ring disc to Phase 16, which redraws the kept arcs as real streets.
    Presentation geometry only: the plate, its architecture, the depot,
    and every semantic anchor stay exactly where Phase 15 put them.
    """
    return [
        f"LD_DISTRICT__{district_id}__ring_road"
        for district_id, plate in sorted(plan["ground"]["plates"].items())
        if plate["ring"] != "full"
    ]


def suppress_legacy_presentation(plan: dict) -> int:
    """Remove exactly the founding presentation the plan replaces.

    Two deterministic sets, nothing else: the vegetation clusters the
    landscape plan cleared, and the ring discs of the districts whose
    circles the final composition buries. Semantic history is untouched --
    plates, architecture, wall, Seal, harbor, depots all stay. The
    structural suite pins both sets in both directions, and the Phase 15
    legacy build still reproduces every one of these objects: suppression
    happens only when the production world is added on top.
    """
    removed = 0
    for object_name in [*plan["legacy"]["removed_objects"], *suppressed_ring_objects(plan)]:
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            continue
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        removed += 1
    return removed


def add_production_world(
    master_spec_path: str | Path, production_spec_path: str | Path, style: str = "a"
) -> dict:
    """Validate the production plan and add it to the built master scene.

    Returns the plan summary (street and fabric counts) for reporting.

    Raises:
        RuntimeError: If the master scene has not been built in this session.
        ProductionContractError / RoadGraphError: On any contract violation.
    """
    require_supported_blender()
    set_practical_light_scale(resolve_style(style)["practical_scale"])
    master_spec = load_master_scene_spec(master_spec_path)
    production_spec = load_production_world_spec(production_spec_path)
    require_production_agreement(master_spec, production_spec)
    graph = build_road_graph(master_spec, production_spec)
    plan = plan_urban_fabric(master_spec, production_spec, graph)
    errors = validate_urban_fabric(plan, master_spec, production_spec, graph)
    if errors:
        raise RuntimeError(
            "the fabric plan violates its placement rules:\n- " + "\n- ".join(errors)
        )
    collections = ensure_production_collections()
    materials = _scene_materials()
    suppress_legacy_presentation(plan)
    trim_kept_ring_discs(plan, master_spec, materials)
    build_city_ground(plan, collections, materials)
    build_ring_arcs(plan, master_spec, collections, materials)
    build_plinths(plan, collections, materials)
    build_streets(graph, collections, materials)
    build_junctions(graph, collections, materials)
    build_fabric(plan, master_spec, production_spec, collections, materials)
    build_port_lights(plan, production_spec, master_spec, graph, collections, materials)
    build_production_cameras(production_spec)
    return plan["summary"]


def main() -> None:
    """Command-line entry: build master + production, optionally save."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--production", required=True)
    parser.add_argument("--style", default="a")
    parser.add_argument("--save", default="")
    arguments = parser.parse_args(argv)
    import build_master_scene

    build_master_scene.build_master_scene(arguments.spec, style=arguments.style)
    add_production_world(arguments.spec, arguments.production, style=arguments.style)
    if arguments.save.strip():
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(arguments.save).resolve()))


if __name__ == "__main__":
    main()
