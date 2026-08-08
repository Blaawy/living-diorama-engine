"""Build the persistent Living Diorama master scene in Blender.

Consumes only the Master Scene Spec V1. Everything created here is the
PERSISTENT half of the world: the display platform and its terrain, the
harbor, district plates and architecture, avenues with their markings and
street lighting, the Golden Seal monument, the camera anchors, and the
cinematic lighting rig. Episode state (walls, containers, occupancy,
infrastructure condition) is applied separately by ``apply_render_export.py``
and never changes this geography.

Every object is deterministic: identical spec + identical visual seed produce
the same architecture, the same lots, the same transforms. Variation comes
from SHA-256-seeded generators owned per entity, never from process
randomness.

Run headless::

    blender --background --factory-startup --python build_master_scene.py -- \
        --spec master_scene_v1.json --save master_scene.blend
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
    build_material_family,
    distance_to_polyline,
    ensure_collections,
    link_only,
    look_at_rotation,
    make_box,
    make_cylinder,
    make_detail_mesh,
    make_light,
    make_ribbon,
    make_torus,
    make_windowed_mass,
    polyline_stations,
    remove_factory_defaults,
    replace_object,
    require_supported_blender,
    set_practical_light_scale,
    stable_rng,
    wipe_ld_collections,
)
from scene_spec import load_master_scene_spec  # noqa: E402
from style_profiles import resolve_style  # noqa: E402

ROAD_LEVEL = 0.86
"""The shared avenue deck height every road-related element keys from."""


def build_platform(spec: dict, collections: dict, materials: dict) -> None:
    """The diorama base: plinth, dark display deck, terrain, and edge ring."""
    world = spec["world"]
    radius = world["platform_radius"]
    thickness = world["platform_thickness"]
    collection = collections["LD_DISTRICTS"]
    make_cylinder(
        "LD_PLATFORM__plinth",
        radius + 2.6,
        thickness * 0.45,
        (0.0, 0.0, -thickness),
        collection,
        materials["concrete_dark"],
        segments=96,
        bevel=0.3,
    )
    make_cylinder(
        "LD_PLATFORM",
        radius,
        thickness * 0.55,
        (0.0, 0.0, -thickness * 0.55),
        collection,
        materials["platform"],
        segments=96,
        bevel=0.35,
    )
    make_cylinder(
        "LD_PLATFORM_RING",
        radius + 1.0,
        0.5,
        (0.0, 0.0, -0.62),
        collection,
        materials["metal_dark"],
        segments=96,
        bevel=0.1,
    )
    make_cylinder(
        "LD_PLATFORM__edge_glow",
        radius + 1.15,
        0.1,
        (0.0, 0.0, -0.24),
        collection,
        materials["edge_glow"],
        segments=96,
        bevel=0.0,
    )
    make_cylinder(
        "LD_TERRAIN",
        radius - 7.0,
        0.16,
        (0.0, 0.0, 0.0),
        collection,
        materials["terrain"],
        segments=96,
        bevel=0.08,
    )


def build_harbor(spec: dict, collections: dict, materials: dict) -> None:
    """The port basin east of the port district: water, quay, and cranes.

    Anchored off the single ``port``-character district, out toward the
    platform edge, so the diorama reads as a coastal city instead of an
    island of buildings on a dark tabletop.
    """
    port = next(
        (entry for entry in spec["districts"].values() if entry["character"] == "port"), None
    )
    if port is None:
        return
    center_x, center_y = port["center"]
    length = math.hypot(center_x, center_y) or 1.0
    direction = (center_x / length, center_y / length)
    heading = math.atan2(direction[1], direction[0])
    quay_distance = port["radius"] + 10.0
    quay_x = center_x + direction[0] * quay_distance
    quay_y = center_y + direction[1] * quay_distance
    collection = collections["LD_DISTRICTS"]

    make_box(
        "LD_HARBOR__water",
        (24.0, 40.0, 0.3),
        (quay_x + direction[0] * 12.6, quay_y + direction[1] * 12.6, -0.22),
        collection,
        materials["water"],
        rotation_z=heading,
        bevel=0.0,
    )
    make_box(
        "LD_HARBOR__quay",
        (2.2, 42.0, 0.72),
        (quay_x, quay_y, -0.1),
        collection,
        materials["concrete_dark"],
        rotation_z=heading,
        bevel=0.08,
    )
    bollards = []
    for index in range(9):
        along = (index - 4) * 4.6
        bollards.append(((0.34, 0.34, 0.5), (0.6, along, 0.62), 0))
    for index in range(3):
        along = (index - 1) * 13.0 + 2.0
        bollards.append(((0.18, 0.18, 6.0), (-0.4, along, 0.62), 0))
        bollards.append(((0.5, 0.5, 0.14), (-0.4, along, 6.62), 1))
    make_detail_mesh(
        "LD_HARBOR__bollards",
        bollards,
        (quay_x, quay_y, 0.0),
        collection,
        [materials["metal_dark"], materials["warm_light"]],
        rotation_z=heading,
    )
    for index in range(3):
        along = (index - 1) * 13.0 + 2.0
        lamp_x = quay_x + math.cos(heading) * -0.4 - math.sin(heading) * along
        lamp_y = quay_y + math.sin(heading) * -0.4 + math.cos(heading) * along
        make_light(
            f"LD_HARBOR__lamp{index}__light",
            "POINT",
            (lamp_x, lamp_y, 6.4),
            collections["LD_LIGHTS"],
            energy=80.0,
            color=(1.0, 0.62, 0.30),
            size=0.3,
        )
    for crane_index, along in enumerate((-11.0, 9.0)):
        boxes = [
            ((0.7, 0.7, 12.0), (-2.4, along - 3.4, 0.0), 0),
            ((0.7, 0.7, 12.0), (-2.4, along + 3.4, 0.0), 0),
            ((0.7, 0.7, 12.0), (2.4, along - 3.4, 0.0), 0),
            ((0.7, 0.7, 12.0), (2.4, along + 3.4, 0.0), 0),
            ((7.0, 1.3, 1.5), (0.0, along - 3.4, 12.0), 0),
            ((7.0, 1.3, 1.5), (0.0, along + 3.4, 12.0), 0),
            ((1.6, 9.4, 1.0), (0.0, along, 12.6), 0),
            ((22.0, 1.1, 1.3), (7.0, along, 13.2), 1),
            ((1.4, 1.4, 2.4), (-3.6, along, 13.2), 1),
            ((1.0, 1.0, 1.0), (10.0, along, 12.2), 1),
            ((0.12, 0.12, 4.6), (10.0, along, 7.6), 1),
            ((1.5, 1.2, 1.1), (10.0, along, 6.5), 2),
            ((0.3, 0.3, 0.3), (17.6, along, 14.5), 3),
        ]
        make_detail_mesh(
            f"LD_CRANE__{crane_index:02d}",
            boxes,
            (quay_x, quay_y, 0.5),
            collection,
            [
                materials["metal_civic"],
                materials["metal_dark"],
                materials["container_a"],
                materials["warning_red"],
            ],
            rotation_z=heading,
        )


def _lot_positions(
    district_id: str, district: dict, spec: dict, seed: str
) -> list[tuple[float, float]]:
    """Deterministic building lots: rings inside the district footprint.

    Lots too close to avenues, the depot pad, the Golden Seal plaza, or the
    wall station corridor are skipped, so the persistent city always leaves
    room for the world's own geography.
    """
    center_x, center_y = district["center"]
    radius = district["radius"]
    rng = stable_rng(seed, district_id, "lots")
    plaza_clearance = 0.0
    seal = spec["landmarks"]["golden_seal"]
    if district["character"] == "civic":
        plaza_clearance = seal["radius"] + 3.5

    depot_x, depot_y = _depot_location(district)
    positions: list[tuple[float, float]] = []
    road_clearance = 8.5 if district["character"] == "civic" else 10.0
    ring_step = 8.0 if plaza_clearance else 11.0
    ring_radius = max(9.0, plaza_clearance + 3.5)
    while ring_radius < radius - 3.0:
        count = max(5, int((2.0 * math.pi * ring_radius) / 11.0))
        offset = rng.uniform(0.0, 2.0 * math.pi)
        for index in range(count):
            angle = offset + (2.0 * math.pi * index) / count
            jitter = rng.uniform(-1.2, 1.2)
            x = center_x + (ring_radius + jitter) * math.cos(angle)
            y = center_y + (ring_radius + jitter) * math.sin(angle)
            if math.hypot(x - depot_x, y - depot_y) < 11.0:
                continue
            if plaza_clearance and math.hypot(x - center_x, y - center_y) < plaza_clearance:
                continue
            too_close = False
            for boundary in spec["boundaries"].values():
                if (
                    distance_to_polyline(x, y, [tuple(p) for p in boundary["path"]])
                    < road_clearance
                ):
                    too_close = True
                    break
                station = boundary["wall_station"]
                if math.hypot(x - station["center"][0], y - station["center"][1]) < 13.0:
                    too_close = True
                    break
            if too_close:
                continue
            positions.append((x, y))
        ring_radius += ring_step
    return positions


def _depot_location(district: dict) -> tuple[float, float]:
    """The district storage yard: pushed outward, away from the city core."""
    center_x, center_y = district["center"]
    length = math.hypot(center_x, center_y) or 1.0
    return (
        center_x + (center_x / length) * district["radius"] * 0.62,
        center_y + (center_y / length) * district["radius"] * 0.62,
    )


def _entrance_facade(x: float, y: float, rotation: float, center: tuple[float, float]) -> int:
    """Pick the facade (0..3 for +Y/-Y/+X/-X) facing the district center."""
    target = math.atan2(center[1] - y, center[0] - x)
    normals = (rotation + math.pi / 2.0, rotation - math.pi / 2.0, rotation, rotation + math.pi)
    scores = [math.cos(target - normal) for normal in normals]
    return scores.index(max(scores))


def _parapet_boxes(
    width: float, depth: float, top: float, *, rim: float = 0.3, height: float = 0.55
) -> list[tuple[tuple[float, float, float], tuple[float, float, float], int]]:
    """Four parapet rim strips around a flat roof."""
    return [
        ((width, rim, height), (0.0, depth / 2.0 - rim / 2.0, top), 0),
        ((width, rim, height), (0.0, -depth / 2.0 + rim / 2.0, top), 0),
        ((rim, depth - 2.0 * rim, height), (width / 2.0 - rim / 2.0, 0.0, top), 0),
        ((rim, depth - 2.0 * rim, height), (-width / 2.0 + rim / 2.0, 0.0, top), 0),
    ]


def _rooftop_boxes(
    rng, width: float, depth: float, top: float, *, penthouse: bool
) -> list[tuple[tuple[float, float, float], tuple[float, float, float], int]]:
    """Mechanical penthouse, units, and vents for one roof."""
    boxes = []
    if penthouse:
        pw = width * rng.uniform(0.30, 0.42)
        pd = depth * rng.uniform(0.30, 0.42)
        px = rng.uniform(-width * 0.16, width * 0.16)
        py = rng.uniform(-depth * 0.16, depth * 0.16)
        boxes.append(((pw, pd, rng.uniform(1.8, 2.6)), (px, py, top), 1))
        boxes.append(((pw * 0.5, pd * 0.5, 0.8), (px, py, top + 2.6), 1))
    for _ in range(rng.randint(2, 4)):
        ux = rng.uniform(-width * 0.32, width * 0.32)
        uy = rng.uniform(-depth * 0.32, depth * 0.32)
        boxes.append(
            (
                (rng.uniform(0.8, 1.6), rng.uniform(0.8, 1.4), rng.uniform(0.5, 1.0)),
                (ux, uy, top),
                1,
            )
        )
    return boxes


def _build_civic_tower(name, collection, materials, rng, x, y, z, scale, center):
    """A civic-core tower: glazed podium, panelled shaft, mechanical crown."""
    width = rng.uniform(9.0, 12.0)
    depth = rng.uniform(9.0, 12.0)
    rotation = rng.uniform(-0.10, 0.10)
    entrance = _entrance_facade(x, y, rotation, center)
    podium_height = 8.6
    podium_style = FacadeStyle(
        bay_pitch=1.8,
        floor_height=3.2,
        window_frac=0.72,
        sill=0.55,
        head=0.35,
        recess=0.26,
        ground_floor=4.4,
        ground_window_frac=0.78,
        ground_sill=0.35,
        plinth=0.5,
        parapet=0.35,
    )
    make_windowed_mass(
        name,
        (width, depth, podium_height),
        (x, y, z),
        collection,
        materials,
        podium_style,
        rotation_z=rotation,
        entrance_facade=entrance,
        material_keys=("facade_civic", "frame_metal", "glass_civic", "roof_dark", "interior_glow"),
    )
    tower_width = width * rng.uniform(0.66, 0.76)
    tower_depth = depth * rng.uniform(0.66, 0.76)
    tower_height = rng.uniform(24.0, 44.0) * max(scale, 0.7)
    tower_style = FacadeStyle(
        bay_pitch=1.65,
        floor_height=3.1,
        window_frac=0.64,
        sill=0.8,
        head=0.4,
        recess=0.2,
        plinth=0.25,
        parapet=0.6,
    )
    make_windowed_mass(
        f"{name}__tower",
        (tower_width, tower_depth, tower_height),
        (x, y, z + podium_height),
        collection,
        materials,
        tower_style,
        rotation_z=rotation,
        material_keys=("facade_civic", "frame_metal", "glass_civic", "roof_dark", "interior_glow"),
    )
    top = podium_height + tower_height
    boxes = _parapet_boxes(tower_width, tower_depth, top)
    boxes += _rooftop_boxes(rng, tower_width, tower_depth, top, penthouse=True)
    fin_count = max(2, int(tower_width // 2.4))
    for fin in range(fin_count):
        along = (fin - (fin_count - 1) / 2.0) * (tower_width / fin_count)
        boxes.append(
            (
                (0.24, 0.5, tower_height - 1.2),
                (along, tower_depth / 2.0 + 0.14, podium_height + 0.6),
                1,
            )
        )
    boxes.append(((width * 0.34, 1.5, 0.28), (0.0, 0.0, 3.9), 1))
    canopy_normals = ((0.0, 1.0), (0.0, -1.0), (1.0, 0.0), (-1.0, 0.0))
    nx, ny = canopy_normals[entrance]
    boxes.append(
        (
            (3.6 if nx == 0.0 else 1.9, 1.9 if nx == 0.0 else 3.6, 0.22),
            (nx * (width / 2.0 + 0.85), ny * (depth / 2.0 + 0.85), 3.75),
            1,
        )
    )
    if tower_height > 24.0:
        boxes.append(((0.09, 0.09, 2.2), (0.0, 0.0, top + 2.8), 1))
        boxes.append(((0.22, 0.22, 0.22), (0.0, 0.0, top + 5.0), 2))
    make_detail_mesh(
        f"{name}__detail",
        boxes,
        (x, y, z),
        collection,
        [materials["facade_civic"], materials["metal_dark"], materials["warning_red"]],
        rotation_z=rotation,
    )


def _build_port_shed(name, collection, materials, rng, x, y, z, scale, center):
    """A port warehouse: ribbed long shed, clerestory strip, roof services."""
    width = rng.uniform(13.0, 17.0)
    depth = rng.uniform(8.0, 11.0)
    height = rng.uniform(6.9, 8.3) * max(scale, 0.75)
    rotation = rng.uniform(-0.35, 0.35)
    style = FacadeStyle(
        bay_pitch=2.6,
        floor_height=2.2,
        margin=0.8,
        window_frac=0.62,
        sill=1.3,
        head=0.3,
        recess=0.14,
        frame=0.06,
        plinth=3.9,
        parapet=0.5,
        mullion=False,
    )
    make_windowed_mass(
        name,
        (width, depth, height),
        (x, y, z),
        collection,
        materials,
        style,
        rotation_z=rotation,
        material_keys=("facade_port", "frame_metal", "glass_port", "roof_dark", "interior_glow"),
    )
    boxes = _parapet_boxes(width, depth, height, rim=0.24, height=0.4)
    boxes.append(((width * 0.7, 2.0, 1.1), (0.0, 0.0, height), 1))
    door_bays = max(2, int(width // 5.0))
    for door in range(door_bays):
        door_x = (door - (door_bays - 1) / 2.0) * (width / door_bays)
        boxes.append(((3.1, 0.14, 3.1), (door_x, -depth / 2.0 - 0.02, 0.35), 2))
        boxes.append(((3.3, 0.1, 0.32), (door_x, -depth / 2.0 - 0.06, 3.45), 1))
        boxes.append(((0.5, 0.22, 0.1), (door_x, -depth / 2.0 - 0.3, 3.9), 4))
    boxes.append(((1.1, 0.16, 2.3), (width / 2.0 - 1.6, depth / 2.0 + 0.02, 0.35), 3))
    boxes.append(((0.4, 0.2, 0.09), (width / 2.0 - 1.6, depth / 2.0 + 0.3, 2.8), 4))
    for _ in range(rng.randint(2, 4)):
        vx = rng.uniform(-width * 0.32, width * 0.32)
        vy = rng.uniform(-depth * 0.28, depth * 0.28)
        boxes.append(
            (
                (rng.uniform(0.9, 1.8), rng.uniform(0.9, 1.5), rng.uniform(0.7, 1.3)),
                (vx, vy, height),
                1,
            )
        )
    boxes.append(((0.5, 0.5, height + 2.6), (width / 2.0 - 0.8, depth / 2.0 - 0.8, 0.0), 1))
    make_detail_mesh(
        f"{name}__detail",
        boxes,
        (x, y, z),
        collection,
        [
            materials["facade_port"],
            materials["metal_dark"],
            materials["metal_gate"],
            materials["hazard"],
            materials["warm_light"],
        ],
        rotation_z=rotation,
    )


def _build_residential_court(name, collection, materials, rng, x, y, z, scale, center):
    """A residential block: warm masonry mass, two wings, real balconies."""
    width = rng.uniform(10.0, 13.5)
    depth = rng.uniform(5.5, 6.5)
    height = rng.uniform(9.5, 15.5) * scale
    rotation = rng.uniform(-0.3, 0.3)
    entrance = _entrance_facade(x, y, rotation, center)
    style = FacadeStyle(
        bay_pitch=1.6,
        floor_height=2.9,
        window_frac=0.5,
        sill=0.95,
        head=0.5,
        recess=0.26,
        frame=0.08,
        plinth=0.5,
        parapet=0.6,
        ground_floor=3.6,
        ground_window_frac=0.6,
        ground_sill=0.55,
    )
    make_windowed_mass(
        name,
        (width, depth, height),
        (x, y, z),
        collection,
        materials,
        style,
        rotation_z=rotation,
        entrance_facade=entrance,
        material_keys=(
            "facade_residential",
            "frame_metal",
            "glass_residential",
            "roof_dark",
            "interior_glow",
        ),
    )
    boxes = _parapet_boxes(width, depth, height, rim=0.26, height=0.45)
    boxes += _rooftop_boxes(rng, width, depth, height, penthouse=False)
    boxes.append(((2.2, 2.6, 2.2), (rng.uniform(-width * 0.2, width * 0.2), 0.0, height), 0))
    if entrance in (0, 1):
        face_y = depth / 2.0 + 0.5 if entrance == 0 else -depth / 2.0 - 0.5
        usable = width - 2.0 * style.margin
        bays = max(1, int(usable // style.bay_pitch))
        bay_width = usable / bays
        floors = max(1, int((height - style.plinth - 3.6 - style.parapet) // style.floor_height))
        for floor in range(floors):
            slab_z = style.plinth + 3.6 + floor * style.floor_height + 0.9
            for bay in range(bays):
                if bay == bays // 2:
                    continue
                bay_x = -width / 2.0 + style.margin + (bay + 0.5) * bay_width
                boxes.append(((bay_width * 0.72, 1.05, 0.14), (bay_x, face_y, slab_z), 0))
                boxes.append(
                    ((bay_width * 0.72, 0.06, 0.75), (bay_x, face_y + 0.5, slab_z + 0.14), 1)
                )
    make_detail_mesh(
        f"{name}__detail",
        boxes,
        (x, y, z),
        collection,
        [materials["facade_residential"], materials["metal_dark"]],
        rotation_z=rotation,
    )
    wing_depth = rng.uniform(5.0, 7.0)
    for side, wing in ((-1.0, "west"), (1.0, "east")):
        local_x = side * (width / 2.0 - depth / 2.0)
        local_y = wing_depth / 2.0 + depth / 2.0
        ox = local_x * math.cos(rotation) - local_y * math.sin(rotation)
        oy = local_x * math.sin(rotation) + local_y * math.cos(rotation)
        make_windowed_mass(
            f"{name}__wing_{wing}",
            (depth, wing_depth, height * rng.uniform(0.72, 0.9)),
            (x + ox, y + oy, z),
            collection,
            materials,
            style,
            rotation_z=rotation,
            material_keys=(
                "facade_residential",
                "frame_metal",
                "glass_residential",
                "roof_dark",
                "interior_glow",
            ),
        )


def _build_terrace_slab(name, collection, materials, rng, x, y, z, scale, center):
    """A terrace-district slab: stepped glazed masses with planted roofs."""
    width = rng.uniform(11.0, 15.0)
    depth = rng.uniform(6.5, 8.0)
    rotation = rng.uniform(-0.2, 0.2)
    step_height = rng.uniform(5.6, 8.6) * scale
    steps = rng.randint(2, 3)
    style = FacadeStyle(
        bay_pitch=2.2,
        floor_height=3.0,
        window_frac=0.8,
        sill=0.65,
        head=0.35,
        recess=0.18,
        frame=0.06,
        plinth=0.45,
        parapet=0.55,
    )
    detail_boxes = []
    for step in range(steps):
        shift = step * depth * 0.62
        ox = -shift * math.sin(rotation)
        oy = shift * math.cos(rotation)
        step_width = width * (1.0 - 0.10 * step)
        height = step_height * (steps - step)
        make_windowed_mass(
            f"{name}__s{step}",
            (step_width, depth, height),
            (x + ox, y + oy, z),
            collection,
            materials,
            style,
            rotation_z=rotation,
            material_keys=(
                "facade_terrace",
                "frame_metal",
                "glass_terrace",
                "roof_dark",
                "interior_glow",
            ),
        )
        local_shift = step * depth * 0.62
        detail_boxes += [
            (
                (step_width - 0.6, 0.24, 0.5),
                (local_shift * 0.0, local_shift + depth / 2.0 - 0.2, height),
                0,
            ),
            ((step_width - 1.2, 0.9, 0.42), (0.0, local_shift + depth / 2.0 - 0.75, height), 1),
        ]
        if step == steps - 1:
            detail_boxes += _parapet_boxes(step_width, depth, height, rim=0.24, height=0.4)
            for size, offset, _index in _rooftop_boxes(
                rng, step_width, depth, height, penthouse=False
            ):
                detail_boxes.append((size, (offset[0], offset[1] + local_shift, offset[2]), 2))
    make_detail_mesh(
        f"{name}__detail",
        detail_boxes,
        (x, y, z),
        collection,
        [materials["metal_dark"], materials["foliage"], materials["metal_dark"]],
        rotation_z=rotation,
    )


_ARCHETYPES = {
    "civic": _build_civic_tower,
    "port": _build_port_shed,
    "residential": _build_residential_court,
    "terrace": _build_terrace_slab,
}


def build_districts(spec: dict, collections: dict, materials: dict) -> None:
    """District plates, block architecture, and depot pads."""
    seed = spec["visual_seed"]
    for district_id, district in spec["districts"].items():
        center_x, center_y = district["center"]
        elevation = district["elevation"]
        radius = district["radius"]
        collection = collections["LD_DISTRICTS"]
        plate_name = f"LD_DISTRICT__{district_id}"
        make_cylinder(
            plate_name,
            radius + 1.5,
            0.55 + max(elevation, 0.0),
            (center_x, center_y, min(0.0, elevation)),
            collection,
            materials["pavement"],
            segments=72,
            bevel=0.18,
        )
        make_cylinder(
            f"{plate_name}__ring_road",
            radius * 0.985,
            0.06,
            (center_x, center_y, elevation + 0.55),
            collection,
            materials["asphalt"],
            segments=72,
            bevel=0.0,
        )
        make_cylinder(
            f"{plate_name}__core",
            radius * 0.62,
            0.08,
            (center_x, center_y, elevation + 0.60),
            collection,
            materials["pavement"],
            segments=64,
            bevel=0.0,
        )

        base_z = elevation + 0.68
        builder = _ARCHETYPES[district["character"]]
        for index, (x, y) in enumerate(_lot_positions(district_id, district, spec, seed)):
            distance = math.hypot(x - center_x, y - center_y)
            falloff = 1.0 - 0.45 * (distance / radius)
            builder(
                f"LD_BLDG__{district_id}__{index:03d}",
                collection,
                materials,
                stable_rng(seed, district_id, "building", str(index)),
                x,
                y,
                base_z,
                falloff,
                (center_x, center_y),
            )

        depot_x, depot_y = _depot_location(district)
        make_box(
            f"LD_DEPOT__{district_id}",
            (13.0, 17.0, 0.5),
            (depot_x, depot_y, base_z - 0.08),
            collection,
            materials["concrete_dark"],
            bevel=0.1,
        )
        posts = []
        for sx, sy in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
            posts.append(((0.35, 0.35, 3.2), (sx * 6.0, sy * 7.9, 0.08), 0))
        for sy in (-1, 1):
            posts.append(((0.22, 0.22, 6.4), (0.0, sy * 7.6, 0.08), 0))
            posts.append(((1.1, 0.3, 0.16), (0.0, sy * 7.3, 6.5), 1))
        make_detail_mesh(
            f"LD_DEPOT__{district_id}__posts",
            posts,
            (depot_x, depot_y, base_z),
            collection,
            [materials["metal_civic"], materials["warm_light"]],
        )


def build_vegetation(spec: dict, collections: dict, materials: dict) -> None:
    """Deterministic tree clusters on the terrain between districts."""
    seed = spec["visual_seed"]
    rng = stable_rng(seed, "vegetation")
    platform_radius = spec["world"]["platform_radius"]
    port = next(
        (entry for entry in spec["districts"].values() if entry["character"] == "port"), None
    )
    clusters: list[tuple[float, float]] = []
    attempts = 0
    while len(clusters) < 40 and attempts < 500:
        attempts += 1
        angle = rng.uniform(0.0, 2.0 * math.pi)
        distance = math.sqrt(rng.uniform(0.05, 0.92)) * (platform_radius - 10.0)
        x, y = distance * math.cos(angle), distance * math.sin(angle)
        rejected = False
        for district in spec["districts"].values():
            if (
                math.hypot(x - district["center"][0], y - district["center"][1])
                < district["radius"] + 4.0
            ):
                rejected = True
                break
        if not rejected and port is not None:
            center_x, center_y = port["center"]
            length = math.hypot(center_x, center_y) or 1.0
            quay = port["radius"] + 6.0
            along = (x - center_x) * center_x / length + (y - center_y) * center_y / length
            if along > quay:
                rejected = True
        if not rejected:
            for boundary in spec["boundaries"].values():
                if distance_to_polyline(x, y, [tuple(p) for p in boundary["path"]]) < 8.0:
                    rejected = True
                    break
                station = boundary["wall_station"]
                if math.hypot(x - station["center"][0], y - station["center"][1]) < 14.0:
                    rejected = True
                    break
        if rejected:
            continue
        clusters.append((x, y))

    for cluster_index, (x, y) in enumerate(clusters):
        cluster_rng = stable_rng(seed, "vegetation", str(cluster_index))
        builder = bmesh.new()
        for _ in range(cluster_rng.randint(2, 5)):
            ox = cluster_rng.uniform(-3.4, 3.4)
            oy = cluster_rng.uniform(-3.4, 3.4)
            trunk_height = cluster_rng.uniform(0.9, 1.6)
            canopy_radius = cluster_rng.uniform(1.0, 2.0)
            result = bmesh.ops.create_icosphere(builder, subdivisions=2, radius=canopy_radius)
            canopy_faces = {face for vert in result["verts"] for face in vert.link_faces}
            for face in canopy_faces:
                face.material_index = 0
                face.smooth = True
            for vert in result["verts"]:
                wobble = 1.0 + cluster_rng.uniform(-0.09, 0.09)
                vert.co.x = vert.co.x * 1.06 * wobble + ox
                vert.co.y = vert.co.y * 1.06 * wobble + oy
                vert.co.z = vert.co.z * 0.82 * wobble + trunk_height + canopy_radius * 0.72
            trunk = bmesh.ops.create_cone(
                builder,
                cap_ends=True,
                segments=6,
                radius1=0.14,
                radius2=0.10,
                depth=trunk_height + canopy_radius,
            )
            trunk_faces = {face for vert in trunk["verts"] for face in vert.link_faces}
            for face in trunk_faces:
                face.material_index = 1
            for vert in trunk["verts"]:
                vert.co.x += ox
                vert.co.y += oy
                vert.co.z += (trunk_height + canopy_radius) / 2.0
        name = f"LD_TREE__{cluster_index:02d}"
        replace_object(name)
        mesh = bpy.data.meshes.new(name)
        builder.to_mesh(mesh)
        builder.free()
        obj = bpy.data.objects.new(name, mesh)
        obj.location = (x, y, 0.1)
        obj.data.materials.append(materials["foliage"])
        obj.data.materials.append(materials["bark"])
        link_only(obj, collections["LD_DISTRICTS"])


def build_avenues(spec: dict, collections: dict, materials: dict) -> None:
    """Boundary corridors: avenues, sidewalks, curbs, markings, lights."""
    collection = collections["LD_BOUNDARIES"]
    for boundary_id, boundary in spec["boundaries"].items():
        path = [tuple(point) for point in boundary["path"]]
        make_ribbon(
            f"LD_ROAD__{boundary_id}", path, 7.0, 0.12, ROAD_LEVEL, collection, materials["asphalt"]
        )
        for side, label in ((4.7, "north"), (-4.7, "south")):
            make_ribbon(
                f"LD_SIDEWALK__{boundary_id}__{label}",
                path,
                2.0,
                0.10,
                ROAD_LEVEL,
                collection,
                materials["pavement"],
                offset=side,
            )
            make_ribbon(
                f"LD_CURB__{boundary_id}__{label}",
                path,
                0.4,
                0.16,
                ROAD_LEVEL,
                collection,
                materials["curb"],
                offset=side * 0.775,
            )
        for offset, label in ((3.1, "edge_n"), (-3.1, "edge_s")):
            make_ribbon(
                f"LD_MARKING__{boundary_id}__{label}",
                path,
                0.14,
                0.005,
                ROAD_LEVEL + 0.121,
                collection,
                materials["road_marking"],
                offset=offset,
            )
        dashes = []
        for x, y, _heading in polyline_stations(path, 4.2):
            dashes.append(((1.7, 0.15, 0.01), (x, y, 0.0), 0))
        first_x, first_y, _ = polyline_stations(path, 4.2)[0]
        marking = make_detail_mesh(
            f"LD_MARKING__{boundary_id}__center",
            [
                (size, (ox - first_x, oy - first_y, oz), index)
                for size, (ox, oy, oz), index in dashes
            ],
            (first_x, first_y, ROAD_LEVEL + 0.121),
            collection,
            [materials["road_marking"]],
            bevel=0.0,
        )
        del marking
        for index, (x, y, heading) in enumerate(polyline_stations(path, 11.0)):
            side = 4.15 if index % 2 == 0 else -4.15
            nx = -math.sin(heading) * side
            ny = math.cos(heading) * side
            inward = -1.0 if side > 0 else 1.0
            pole = f"LD_STREETLIGHT__{boundary_id}__{index:02d}"
            arm_y = inward * 0.8
            make_detail_mesh(
                pole,
                [
                    ((0.15, 0.15, 5.3), (0.0, 0.0, 0.0), 0),
                    ((0.1, 1.7, 0.1), (0.0, arm_y, 5.3), 0),
                    ((0.34, 0.62, 0.1), (0.0, arm_y * 2.0, 5.24), 0),
                    ((0.26, 0.5, 0.05), (0.0, arm_y * 2.0, 5.2), 1),
                ],
                (x + nx, y + ny, ROAD_LEVEL + 0.1),
                collection,
                [materials["metal_dark"], materials["warm_light"]],
                rotation_z=heading,
            )
            if boundary_id == "boundary_ab":
                make_light(
                    f"{pole}__light",
                    "POINT",
                    (
                        x + nx - math.sin(heading) * inward * 1.6,
                        y + ny + math.cos(heading) * inward * 1.6,
                        ROAD_LEVEL + 5.1,
                    ),
                    collections["LD_LIGHTS"],
                    energy=170.0,
                    color=(1.0, 0.62, 0.30),
                    size=0.3,
                )


def build_spurs(spec: dict, collections: dict, materials: dict) -> None:
    """Connector roads tying each district plate onto its avenues."""
    collection = collections["LD_BOUNDARIES"]
    for boundary_id, boundary in spec["boundaries"].items():
        path = [tuple(point) for point in boundary["path"]]
        endpoints = (path[0], path[-1])
        for district_id in boundary["districts"]:
            district = spec["districts"][district_id]
            center = district["center"]
            best = min(
                endpoints,
                key=lambda point: math.hypot(point[0] - center[0], point[1] - center[1]),
            )
            dx, dy = best[0] - center[0], best[1] - center[1]
            distance = math.hypot(dx, dy) or 1.0
            edge = (
                center[0] + dx / distance * district["radius"] * 0.55,
                center[1] + dy / distance * district["radius"] * 0.55,
            )
            make_ribbon(
                f"LD_SPUR__{boundary_id}__{district_id}",
                [edge, best],
                5.0,
                0.11,
                ROAD_LEVEL - 0.01,
                collection,
                materials["asphalt"],
            )


def _build_seal_gnomon(
    x: float,
    y: float,
    base_z: float,
    facing: float,
    collection,
    materials: dict,
) -> None:
    """The Seal's gnomon: a gold blade rising from the disc, aimed at the scar.

    A right-triangle prism -- tall civic edge at the back, a long measured
    slope descending toward the first wall station -- so the monument carries
    direction and consequence in its silhouette, like a sundial that points
    at history instead of hours.
    """
    replace_object("LD_SEAL__gnomon")
    builder = bmesh.new()
    half_t = 0.15
    profile = ((-1.05, 0.0), (-1.05, 3.1), (1.95, 0.28))
    cos_f, sin_f = math.cos(facing), math.sin(facing)
    sides = []
    for sign in (-1.0, 1.0):
        verts = []
        for along, up in profile:
            verts.append(
                builder.verts.new(
                    (
                        along * cos_f - sign * half_t * sin_f,
                        along * sin_f + sign * half_t * cos_f,
                        up,
                    )
                )
            )
        sides.append(verts)
    builder.faces.new(sides[0])
    builder.faces.new(tuple(reversed(sides[1])))
    for index in range(3):
        next_index = (index + 1) % 3
        builder.faces.new(
            (
                sides[0][index],
                sides[0][next_index],
                sides[1][next_index],
                sides[1][index],
            )
        )
    bmesh.ops.recalc_face_normals(builder, faces=list(builder.faces))
    mesh = bpy.data.meshes.new("LD_SEAL__gnomon")
    builder.to_mesh(mesh)
    builder.free()
    obj = bpy.data.objects.new("LD_SEAL__gnomon", mesh)
    obj.location = (x, y, base_z)
    obj.data.materials.append(materials["gold"])
    add_bevel(obj, width=0.03)
    link_only(obj, collection)


def build_golden_seal(spec: dict, collections: dict, materials: dict) -> None:
    """The Rule Object: an engraved civic seal with gnomon and compass rose.

    A tiered plaza carries a dark plinth; on it sits the thick engraved gold
    disc with its raised boss, a gold gnomon blade rising from the disc and
    aimed permanently at the first scar's wall station, and an eight-point
    compass rose of gold fins radiating at the disc's base. The law's
    standing lights the recessed plaza ring (episode-driven); the artifact
    itself never moves.
    """
    seal = spec["landmarks"]["golden_seal"]
    x, y = seal["location"]
    radius = seal["radius"]
    collection = collections["LD_RULE_OBJECT"]
    base_z = 0.68
    for step, (r, h) in enumerate(((radius, 0.18), (radius * 0.82, 0.18), (radius * 0.64, 0.18))):
        make_cylinder(
            f"LD_SEAL__step{step}",
            r,
            h,
            (x, y, base_z + step * 0.18),
            collection,
            materials["pavement"],
            segments=64,
            bevel=0.05,
        )
    plinth_z = base_z + 0.54
    make_cylinder(
        "LD_SEAL__plinth",
        radius * 0.34,
        1.35,
        (x, y, plinth_z),
        collection,
        materials["concrete_dark"],
        segments=64,
        bevel=0.1,
        smooth_sides=True,
    )
    disc_z = plinth_z + 1.35
    make_cylinder(
        "LD_SEAL__disc",
        radius * 0.30,
        0.42,
        (x, y, disc_z),
        collection,
        materials["gold"],
        segments=96,
        bevel=0.06,
        smooth_sides=True,
    )
    make_cylinder(
        "LD_SEAL__boss",
        radius * 0.09,
        0.2,
        (x, y, disc_z + 0.42),
        collection,
        materials["gold"],
        segments=64,
        bevel=0.04,
        smooth_sides=True,
    )
    station = spec["boundaries"]["boundary_ab"]["wall_station"]["center"]
    facing = math.atan2(station[1] - y, station[0] - x)
    _build_seal_gnomon(x, y, disc_z + 0.42, facing, collection, materials)
    rose_fins = []
    for index in range(8):
        angle = facing + index * math.pi / 4.0
        length = 2.6 if index % 2 == 0 else 1.6
        distance = radius * 0.30 + length / 2.0 + 0.15
        rose_fins.append(
            (
                (length, 0.30, 0.14),
                (math.cos(angle) * distance, math.sin(angle) * distance, 0.0),
                0,
                angle,
            )
        )
        rose_fins.append(
            (
                (length * 0.55, 0.14, 0.05),
                (math.cos(angle) * distance, math.sin(angle) * distance, 0.14),
                1,
                angle,
            )
        )
    make_detail_mesh(
        "LD_SEAL__rose",
        rose_fins,
        (x, y, plinth_z + 1.35 - 0.14),
        collection,
        [materials["gold"], materials["metal_dark"]],
    )
    make_torus(
        "LD_SEAL_RING",
        radius * 0.72,
        0.07,
        (x, y, base_z + 0.56),
        collection,
        materials["seal_glow"],
    )
    masts = []
    for index in range(4):
        angle = math.pi / 4.0 + index * math.pi / 2.0
        px = math.cos(angle) * radius * 1.32
        py = math.sin(angle) * radius * 1.32
        masts.append(((0.24, 0.24, 4.2), (px, py, 0.0), 0))
        masts.append(((0.36, 0.36, 0.18), (px, py, 4.2), 1))
    make_detail_mesh(
        "LD_SEAL__masts",
        masts,
        (x, y, base_z + 0.14),
        collection,
        [materials["metal_civic"], materials["warm_light"]],
    )
    for index in range(4):
        angle = math.pi / 4.0 + index * math.pi / 2.0
        px = x + math.cos(angle) * radius * 0.62
        py = y + math.sin(angle) * radius * 0.62
        make_light(
            f"LD_SEAL_LIGHT__{index}",
            "SPOT",
            (px, py, base_z + 0.9),
            collections["LD_LIGHTS"],
            energy=110.0,
            color=(1.0, 0.68, 0.30),
            target=(x, y, disc_z + 0.4),
            size=0.25,
            spot_angle=1.0,
            spot_blend=0.5,
        )


def build_cameras(spec: dict, collections: dict) -> None:
    """The persistent named camera anchors."""
    for name, definition in spec["cameras"].items():
        replace_object(name)
        camera_data = bpy.data.cameras.get(name)
        if camera_data is None:
            camera_data = bpy.data.cameras.new(name)
        camera_data.lens = definition["lens_mm"]
        camera_data.clip_end = 1200.0
        location = Vector(definition["location"])
        target = Vector(definition["look_at"])
        if name == "CAM_VERIFY_TOPOLOGY":
            camera_data.dof.use_dof = False
        else:
            camera_data.dof.use_dof = True
            camera_data.dof.focus_distance = (target - location).length
            camera_data.dof.aperture_fstop = definition.get("f_stop", 5.6)
        camera = bpy.data.objects.new(name, camera_data)
        camera.location = location
        camera.rotation_euler = look_at_rotation(location, target)
        link_only(camera, collections["LD_CAMERAS"])


def build_lighting(spec: dict, collections: dict, materials: dict, lighting: dict) -> None:
    """The cinematic rig: twilight sky, warm afterglow key, cool fill, haze.

    Every dial comes from the active style profile's lighting section; the
    default profile reproduces the reviewed benchmark rig exactly.
    """
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("LD_World")
        bpy.context.scene.world = world
    world.name = "LD_World"
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()
    sky = nodes.new("ShaderNodeTexSky")
    sky.sky_type = "NISHITA"
    sky.sun_elevation = math.radians(lighting["sun_elevation_deg"])
    sky.sun_rotation = math.radians(lighting["sun_rotation_deg"])
    sky.sun_intensity = lighting["sun_intensity"]
    sky.sun_size = math.radians(1.2)
    sky.altitude = 60.0
    sky.air_density = lighting["air_density"]
    sky.dust_density = lighting["dust_density"]
    sky.ozone_density = lighting["ozone_density"]
    background = nodes.new("ShaderNodeBackground")
    background.inputs["Strength"].default_value = lighting["background_strength"]
    output = nodes.new("ShaderNodeOutputWorld")
    links.new(sky.outputs["Color"], background.inputs["Color"])
    links.new(background.outputs["Background"], output.inputs["Surface"])

    make_light(
        "LD_KEY_AFTERGLOW",
        "AREA",
        lighting["key_location"],
        collections["LD_LIGHTS"],
        energy=lighting["key_energy"],
        color=lighting["key_color"],
        target=(0.0, 0.0, 10.0),
        size=lighting["key_size"],
        practical=False,
    )
    make_light(
        "LD_FILL_LIGHT",
        "AREA",
        lighting["fill_location"],
        collections["LD_LIGHTS"],
        energy=lighting["fill_energy"],
        color=lighting["fill_color"],
        target=(0.0, 0.0, 0.0),
        size=lighting["fill_size"],
        practical=False,
    )

    replace_object("LD_ATMOSPHERE")
    volume_material = bpy.data.materials.get("LD_MAT__atmosphere")
    if volume_material is not None:
        bpy.data.materials.remove(volume_material)
    volume_material = bpy.data.materials.new("LD_MAT__atmosphere")
    volume_material.use_nodes = True
    volume_nodes = volume_material.node_tree.nodes
    volume_links = volume_material.node_tree.links
    volume_nodes.clear()
    coords = volume_nodes.new("ShaderNodeTexCoord")
    separate = volume_nodes.new("ShaderNodeSeparateXYZ")
    volume_links.new(coords.outputs["Object"], separate.inputs["Vector"])
    falloff = volume_nodes.new("ShaderNodeMapRange")
    falloff.inputs["From Min"].default_value = 0.0
    falloff.inputs["From Max"].default_value = 46.0
    falloff.inputs["To Min"].default_value = 1.6
    falloff.inputs["To Max"].default_value = 0.12
    volume_links.new(separate.outputs["Z"], falloff.inputs["Value"])
    density = volume_nodes.new("ShaderNodeMath")
    density.operation = "MULTIPLY"
    density.inputs[1].default_value = lighting["volume_density"]
    volume_links.new(falloff.outputs["Result"], density.inputs[0])
    scatter = volume_nodes.new("ShaderNodeVolumeScatter")
    scatter.inputs["Anisotropy"].default_value = lighting["volume_anisotropy"]
    volume_links.new(density.outputs[0], scatter.inputs["Density"])
    volume_output = volume_nodes.new("ShaderNodeOutputMaterial")
    volume_links.new(scatter.outputs["Volume"], volume_output.inputs["Volume"])
    atmosphere = make_box(
        "LD_ATMOSPHERE",
        (420.0, 420.0, 52.0),
        (0.0, 0.0, -2.0),
        collections["LD_LIGHTS"],
        volume_material,
        bevel=0.0,
    )
    atmosphere.display_type = "WIRE"
    atmosphere.visible_shadow = False


def configure_scene_settings(settings: dict) -> None:
    """Baseline scene, film, and color management for every render."""
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.render.film_transparent = False
    view = scene.view_settings
    view.view_transform = "AgX"
    view.look = settings["look"]
    view.exposure = settings["exposure"]
    scene.render.resolution_x = 2560
    scene.render.resolution_y = 1440
    scene.render.resolution_percentage = 100


def build_master_scene(spec_path: str | Path, style: str = "a") -> dict:
    """Build the whole persistent world and return the loaded spec.

    ``style`` selects a bake-off visual profile; the default ``"a"`` is the
    identity profile and reproduces the reviewed benchmark exactly. Styles
    restyle materials, lighting, and grading only -- geography, topology,
    architecture, landmarks, and camera anchors are identical across styles.
    """
    require_supported_blender()
    profile = resolve_style(style)
    set_practical_light_scale(profile["practical_scale"])
    spec = load_master_scene_spec(spec_path)
    remove_factory_defaults()
    wipe_ld_collections()
    collections = ensure_collections()
    materials = build_material_family(profile["materials"])
    build_platform(spec, collections, materials)
    build_harbor(spec, collections, materials)
    build_districts(spec, collections, materials)
    build_vegetation(spec, collections, materials)
    build_avenues(spec, collections, materials)
    build_spurs(spec, collections, materials)
    build_golden_seal(spec, collections, materials)
    build_cameras(spec, collections)
    build_lighting(spec, collections, materials, profile["lighting"])
    configure_scene_settings(profile["settings"])
    return spec


def main() -> None:
    """Command-line entry: build the master scene, optionally save a .blend."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--save", default="")
    parser.add_argument("--style", default="a")
    arguments = parser.parse_args(argv)
    build_master_scene(arguments.spec, style=arguments.style)
    if arguments.save.strip():
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(arguments.save).resolve()))


if __name__ == "__main__":
    main()
