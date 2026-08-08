"""Apply one Render Export's episode state onto the built master scene.

The master scene is persistent geography; this script layers the EPISODE onto
it: walls the engine built, storage yard fill, window occupancy, isolation
gates, infrastructure condition, and the Golden Seal's law state. Applying a
different export replaces exactly this episode layer -- geography, cameras,
landmarks, and architecture never move.

Application is idempotent: every episode object lives under ``LD_EPISODE``,
``LD_WALLS``, or ``LD_INFRASTRUCTURE`` with a stable name, and each apply
clears those layers before rebuilding them from the export. Applying the same
export twice yields the same scene; applying a no-wall export after a walled
one removes the wall.

Run headless (after ``build_master_scene.py`` in the same session, or on an
opened master ``.blend``)::

    blender --background --factory-startup --python build_and_apply.py -- ...
"""

import argparse
import math
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))

from blender_runtime import (  # noqa: E402
    ensure_collections,
    make_box,
    make_detail_mesh,
    make_light,
    polyline_stations,
    require_supported_blender,
    set_practical_light_scale,
    stable_rng,
)
from build_master_scene import ROAD_LEVEL  # noqa: E402
from scene_spec import (  # noqa: E402
    depot_fill_fraction,
    load_master_scene_spec,
    load_render_export,
    occupancy_fraction,
    require_topology_agreement,
)
from style_profiles import resolve_style  # noqa: E402

WALL_HEIGHT = 16.0
WALL_THICKNESS = 2.8
SEGMENT_LENGTH = 5.2
JOINT_GAP = 0.16


def clear_episode_layer(collections: dict) -> None:
    """Remove every episode-scoped object so re-application stays idempotent."""
    for name in ("LD_EPISODE", "LD_WALLS", "LD_INFRASTRUCTURE"):
        for obj in list(collections[name].objects):
            bpy.data.objects.remove(obj, do_unlink=True)


def _wall_frame(station: dict) -> tuple[float, float, float, float]:
    """Return (x, y, heading, length) for a wall station."""
    x, y = station["center"]
    dx, dy = station["direction"]
    length = math.hypot(dx, dy) or 1.0
    return x, y, math.atan2(dy / length, dx / length), station["length"]


def _crossing_along(station: dict, path: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Where the avenue crosses the wall line: (along-distance, road heading).

    Intersects the infinite wall line with each avenue segment and returns
    the crossing closest to the station center, so the gate opening always
    lands exactly on the road that passes through it.
    """
    x, y, heading, length = _wall_frame(station)
    dir_x, dir_y = math.cos(heading), math.sin(heading)
    best: tuple[float, float] | None = None
    for (ax, ay), (bx, by) in zip(path, path[1:], strict=False):
        seg_x, seg_y = bx - ax, by - ay
        denominator = dir_x * seg_y - dir_y * seg_x
        if abs(denominator) < 1.0e-9:
            continue
        t = ((ax - x) * seg_y - (ay - y) * seg_x) / denominator
        u = (dir_y * (ax - x) - dir_x * (ay - y)) / denominator
        if not 0.0 <= u <= 1.0:
            continue
        if abs(t) > length / 2.0 - SEGMENT_LENGTH / 2.0:
            continue
        if best is None or abs(t) < abs(best[0]):
            best = (t, math.atan2(seg_y, seg_x))
    return best


def apply_walls(export: dict, spec: dict, collections: dict, materials: dict) -> None:
    """Raise every engine-built wall as engineered scar architecture.

    Precast segments with real construction joints, alternating buttress
    piers, a continuous service band and upper cable tray, a guarded catwalk
    with access ladders, aviation beacons, wall-wash lighting, and a
    controlled gate complex -- towers, lit control cabs, machinery lintel,
    ribbed sliding door, bollards, and floodlights -- exactly where the
    avenue crosses. Placement comes from the master spec's wall station; the
    wall's existence and condition come only from the export.
    """
    collection = collections["LD_WALLS"]
    for wall in export["world"]["walls"]:
        boundary = spec["boundaries"][wall["boundary_id"]]
        x, y, heading, length = _wall_frame(boundary["wall_station"])
        cos_h, sin_h = math.cos(heading), math.sin(heading)
        prefix = f"LD_WALL__{wall['id']}"
        integrity = wall["integrity"]
        height = WALL_HEIGHT * (0.86 + 0.14 * integrity)
        rng = stable_rng(spec["visual_seed"], wall["id"], "segments")

        path = [tuple(point) for point in boundary["path"]]
        crossing = _crossing_along(boundary["wall_station"], path)
        count = max(3, int(length // SEGMENT_LENGTH))
        if crossing is None:
            gate_slot = count // 2
            layout_offset = 0.0
            road_heading = heading + math.pi / 2.0
        else:
            gate_slot = count // 2
            layout_offset = crossing[0] - (gate_slot - (count - 1) / 2.0) * SEGMENT_LENGTH
            road_heading = crossing[1]

        def along_point(
            along: float,
            offset: float = 0.0,
            *,
            _x: float = x,
            _y: float = y,
            _cos: float = cos_h,
            _sin: float = sin_h,
        ) -> tuple[float, float]:
            """Map (along, sideways-offset) wall coordinates to world XY."""
            return (_x + _cos * along - _sin * offset, _y + _sin * along + _cos * offset)

        foundation_length = (count + 0.6) * SEGMENT_LENGTH
        fx, fy = along_point(layout_offset)
        make_box(
            f"{prefix}__foundation",
            (foundation_length, WALL_THICKNESS + 2.8, 1.0),
            (fx, fy, 0.0),
            collection,
            materials["concrete_dark"],
            rotation_z=heading,
            bevel=0.1,
        )
        base_z = 1.0

        service_boxes = []
        catwalk_boxes = []
        for index in range(count):
            along = layout_offset + (index - (count - 1) / 2.0) * SEGMENT_LENGTH
            sx, sy = along_point(along)
            if index != gate_slot:
                segment_height = height * rng.uniform(0.985, 1.015)
                make_box(
                    f"{prefix}__seg{index:02d}",
                    (SEGMENT_LENGTH - JOINT_GAP, WALL_THICKNESS, segment_height),
                    (sx, sy, base_z),
                    collection,
                    materials["scar_concrete"],
                    rotation_z=heading,
                    bevel=0.12,
                )
                make_box(
                    f"{prefix}__cap{index:02d}",
                    (SEGMENT_LENGTH - 0.05, WALL_THICKNESS + 0.5, 0.4),
                    (sx, sy, base_z + segment_height),
                    collection,
                    materials["metal_dark"],
                    rotation_z=heading,
                    bevel=0.05,
                )
                service_boxes.append(
                    (
                        (SEGMENT_LENGTH - 0.5, 0.30, 0.30),
                        (along, -WALL_THICKNESS / 2.0 - 0.25, 4.2),
                        0,
                    )
                )
                service_boxes.append(
                    (
                        (SEGMENT_LENGTH - 0.5, 0.22, 0.22),
                        (along, -WALL_THICKNESS / 2.0 - 0.22, 4.72),
                        1,
                    )
                )
                service_boxes.append(
                    (
                        (0.18, 0.42, 0.5),
                        (along - SEGMENT_LENGTH / 2.0 + 0.6, -WALL_THICKNESS / 2.0 - 0.2, 4.1),
                        1,
                    )
                )
                service_boxes.append(
                    ((0.7, 0.3, 0.85), (along + 1.1, -WALL_THICKNESS / 2.0 - 0.26, 3.2), 1)
                )
                if index % 2 == 0:
                    service_boxes.append(
                        ((0.34, 0.3, 0.1), (along, -WALL_THICKNESS / 2.0 - 0.3, 7.6), 2)
                    )
                    service_boxes.append(
                        ((0.4, 0.14, 0.2), (along, -WALL_THICKNESS / 2.0 - 0.18, 7.75), 1)
                    )
                service_boxes.append(
                    (
                        (SEGMENT_LENGTH - 0.5, 0.5, 0.12),
                        (along, -WALL_THICKNESS / 2.0 - 0.35, height * 0.66),
                        1,
                    )
                )
                catwalk_boxes.append(
                    (
                        (SEGMENT_LENGTH - JOINT_GAP, 1.25, 0.14),
                        (along, -WALL_THICKNESS / 2.0 - 0.68, height + 0.02),
                        0,
                    )
                )
                for post in range(4):
                    post_along = along + (post - 1.5) * (SEGMENT_LENGTH / 4.0)
                    catwalk_boxes.append(
                        (
                            (0.07, 0.07, 1.05),
                            (post_along, -WALL_THICKNESS / 2.0 - 1.24, height + 0.14),
                            0,
                        )
                    )
                catwalk_boxes.append(
                    (
                        (SEGMENT_LENGTH - JOINT_GAP, 0.06, 0.07),
                        (along, -WALL_THICKNESS / 2.0 - 1.24, height + 1.12),
                        0,
                    )
                )
                catwalk_boxes.append(
                    (
                        (SEGMENT_LENGTH - JOINT_GAP, 0.05, 0.05),
                        (along, -WALL_THICKNESS / 2.0 - 1.24, height + 0.62),
                        0,
                    )
                )

            if index > 0:
                joint_along = along - SEGMENT_LENGTH / 2.0
                near_gate = index in (gate_slot, gate_slot + 1)
                if not near_gate:
                    side = 1.0 if index % 2 == 0 else -1.0
                    px, py = along_point(joint_along, side * (WALL_THICKNESS / 2.0 + 0.55))
                    pier_height = height * rng.uniform(0.52, 0.62)
                    make_box(
                        f"{prefix}__pier{index:02d}",
                        (0.9, 1.7, pier_height),
                        (px, py, base_z),
                        collection,
                        materials["concrete_dark"],
                        rotation_z=heading,
                        bevel=0.08,
                    )
                    if index % 2 == 0:
                        mast_x, mast_y = along_point(joint_along)
                        make_detail_mesh(
                            f"{prefix}__beacon{index:02d}",
                            [
                                ((0.1, 0.1, 1.6), (0.0, 0.0, 0.0), 0),
                                ((0.26, 0.26, 0.26), (0.0, 0.0, 1.6), 1),
                            ],
                            (mast_x, mast_y, base_z + height + 0.35),
                            collection,
                            [materials["metal_dark"], materials["warning_red"]],
                            rotation_z=heading,
                        )

        make_detail_mesh(
            f"{prefix}__service_band",
            service_boxes,
            (x, y, base_z),
            collection,
            [materials["metal_civic"], materials["metal_dark"], materials["warm_light"]],
            rotation_z=heading,
        )
        make_detail_mesh(
            f"{prefix}__catwalk",
            catwalk_boxes,
            (x, y, base_z),
            collection,
            [materials["metal_dark"]],
            rotation_z=heading,
        )
        ladder_boxes = []
        for rung in range(int(height // 0.42)):
            ladder_boxes.append(((0.5, 0.05, 0.05), (0.0, 0.0, 0.5 + rung * 0.42), 0))
        for side in (-0.28, 0.28):
            ladder_boxes.append(((0.06, 0.06, height + 1.0), (side, 0.0, 0.1), 0))
        ladder_along = layout_offset + (0 - (count - 1) / 2.0) * SEGMENT_LENGTH + 1.2
        lx, ly = along_point(ladder_along, -WALL_THICKNESS / 2.0 - 0.3)
        make_detail_mesh(
            f"{prefix}__ladder",
            ladder_boxes,
            (lx, ly, base_z),
            collection,
            [materials["metal_dark"]],
            rotation_z=heading,
        )

        gate_along = layout_offset + (gate_slot - (count - 1) / 2.0) * SEGMENT_LENGTH
        gate_x, gate_y = along_point(gate_along)
        opening = SEGMENT_LENGTH - JOINT_GAP
        for side, label in ((-1.0, "a"), (1.0, "b")):
            tower_x, tower_y = along_point(gate_along + side * (opening / 2.0 + 1.15))
            tower_height = height + 3.6
            make_box(
                f"{prefix}__gate_tower_{label}",
                (2.3, WALL_THICKNESS + 2.2, tower_height),
                (tower_x, tower_y, base_z),
                collection,
                materials["concrete_dark"],
                rotation_z=heading,
                bevel=0.09,
            )
            make_detail_mesh(
                f"{prefix}__gate_cab_{label}",
                [
                    ((2.5, WALL_THICKNESS + 2.6, 1.5), (0.0, 0.0, 0.0), 0),
                    ((2.55, WALL_THICKNESS + 2.65, 0.34), (0.0, 0.0, 0.55), 1),
                    ((0.12, 0.12, 1.9), (0.6, 0.4, 1.5), 2),
                    ((0.2, 0.2, 0.2), (0.6, 0.4, 3.4), 3),
                ],
                (tower_x, tower_y, base_z + tower_height - 1.5),
                collection,
                [
                    materials["metal_dark"],
                    materials["cool_light"],
                    materials["metal_dark"],
                    materials["warning_red"],
                ],
                rotation_z=heading,
            )
        make_box(
            f"{prefix}__gate_lintel",
            (opening + 2.6, WALL_THICKNESS + 1.4, 2.4),
            (gate_x, gate_y, base_z + height - 0.4),
            collection,
            materials["concrete_dark"],
            rotation_z=heading,
            bevel=0.08,
        )
        machinery = [
            ((opening + 1.6, WALL_THICKNESS + 0.8, 1.3), (0.0, 0.0, 2.0), 0),
            ((1.2, 1.2, 0.9), (-opening * 0.26, 0.0, 3.3), 0),
            ((1.2, 1.2, 0.9), (opening * 0.26, 0.0, 3.3), 0),
            ((0.08, 0.08, 2.6), (-opening * 0.26, WALL_THICKNESS / 2.0 + 0.32, -0.6), 0),
            ((0.08, 0.08, 2.6), (opening * 0.26, WALL_THICKNESS / 2.0 + 0.32, -0.6), 0),
            ((opening + 2.4, 0.3, 0.3), (0.0, WALL_THICKNESS / 2.0 + 0.4, -0.35), 0),
        ]
        make_detail_mesh(
            f"{prefix}__gate_machinery",
            machinery,
            (gate_x, gate_y, base_z + height - 0.4),
            collection,
            [materials["metal_dark"]],
            rotation_z=heading,
        )
        door_height = height - 1.6
        make_box(
            f"{prefix}__gate_door",
            (opening - 0.5, 0.6, door_height),
            (gate_x, gate_y, base_z),
            collection,
            materials["metal_gate"],
            rotation_z=heading,
            bevel=0.04,
        )
        ribs = []
        for rib in range(int(door_height // 1.5)):
            ribs.append(((opening - 0.7, 0.16, 0.22), (0.0, -0.38, 1.2 + rib * 1.5), 0))
            ribs.append(((opening - 0.7, 0.16, 0.22), (0.0, 0.38, 1.2 + rib * 1.5), 0))
        ribs.append(((opening - 0.6, 0.7, 1.1), (0.0, 0.0, 0.05), 1))
        ribs.append(((1.1, 0.16, 2.2), (-opening / 2.0 + 1.0, -0.4, 0.05), 0))
        make_detail_mesh(
            f"{prefix}__gate_door_detail",
            ribs,
            (gate_x, gate_y, base_z),
            collection,
            [materials["metal_gate"], materials["hazard"]],
            rotation_z=heading,
        )

        cos_r, sin_r = math.cos(road_heading), math.sin(road_heading)
        for side, label in ((1.0, "out"), (-1.0, "in")):
            apron_x = gate_x + cos_r * side * 5.4
            apron_y = gate_y + sin_r * side * 5.4
            make_box(
                f"{prefix}__stopbar_{label}",
                (0.6, 6.4, 0.02),
                (apron_x, apron_y, ROAD_LEVEL + 0.125),
                collection,
                materials["road_marking"],
                rotation_z=road_heading,
                bevel=0.0,
            )
            bollards = []
            for row in range(2):
                for lane in range(4):
                    bollards.append(
                        (
                            (0.24, 0.24, 0.8),
                            (row * 1.4, (lane - 1.5) * 1.9, 0.0),
                            0,
                        )
                    )
            make_detail_mesh(
                f"{prefix}__bollards_{label}",
                bollards,
                (
                    gate_x + cos_r * side * 8.2,
                    gate_y + sin_r * side * 8.2,
                    ROAD_LEVEL + 0.12,
                ),
                collection,
                [materials["metal_dark"]],
                rotation_z=road_heading,
            )
        hut_x = gate_x + cos_r * 7.0 - sin_r * 4.6
        hut_y = gate_y + sin_r * 7.0 + cos_r * 4.6
        make_detail_mesh(
            f"{prefix}__guard_hut",
            [
                ((2.2, 2.0, 2.5), (0.0, 0.0, 0.0), 0),
                ((2.4, 2.2, 0.16), (0.0, 0.0, 2.5), 1),
                ((1.7, 2.06, 0.5), (0.0, 0.0, 1.5), 2),
            ],
            (hut_x, hut_y, ROAD_LEVEL + 0.1),
            collection,
            [materials["concrete_dark"], materials["metal_dark"], materials["cool_light"]],
            rotation_z=road_heading,
        )

        for side, label in ((-1.0, "a"), (1.0, "b")):
            tower_x, tower_y = along_point(gate_along + side * (opening / 2.0 + 1.15))
            make_light(
                f"{prefix}__flood_{label}",
                "SPOT",
                (tower_x - sin_h * -2.2, tower_y + cos_h * -2.2, base_z + height + 1.6),
                collection,
                energy=2800.0,
                color=(1.0, 0.78, 0.52),
                target=(gate_x + cos_r * side * 7.0, gate_y + sin_r * side * 7.0, ROAD_LEVEL),
                size=0.35,
                spot_angle=1.15,
                spot_blend=0.55,
            )
        make_light(
            f"{prefix}__doorlight",
            "SPOT",
            (gate_x - sin_h * -1.7, gate_y + cos_h * -1.7, base_z + height - 2.2),
            collection,
            energy=520.0,
            color=(1.0, 0.72, 0.44),
            target=(gate_x, gate_y, base_z + 1.0),
            size=0.4,
            spot_angle=1.0,
            spot_blend=0.6,
        )
        wash_stations = (
            (-2.2, 1.0),
            (-1.0, 1.0),
            (1.4, 1.0),
            (2.6, 1.0),
            (-1.6, -1.0),
            (1.0, -1.0),
            (2.2, -1.0),
        )
        for wash_index, (wash_along, wash_side) in enumerate(wash_stations):
            along = layout_offset + wash_along * SEGMENT_LENGTH
            wx, wy = along_point(along, wash_side * (WALL_THICKNESS / 2.0 + 5.0))
            tx, ty = along_point(along)
            make_light(
                f"{prefix}__wash{wash_index}",
                "SPOT",
                (wx, wy, 1.4),
                collection,
                energy=1700.0,
                color=(1.0, 0.62, 0.30),
                target=(tx, ty, base_z + height * 0.75),
                size=0.5,
                spot_angle=1.2,
                spot_blend=0.6,
            )


def apply_infrastructure(export: dict, spec: dict, collections: dict, materials: dict) -> None:
    """Elevated service conduits along each boundary an infra entity serves.

    A walled boundary's conduit visibly anchors INTO the wall: strut count
    grows with the engine's dependency score, so adaptation reads as physical
    reorganization. Degraded infrastructure goes dark and loses its glow.
    """
    collection = collections["LD_INFRASTRUCTURE"]
    walls_by_boundary = {wall["boundary_id"]: wall for wall in export["world"]["walls"]}
    lane_offsets = {
        "TRANSIT_ROUTE": 6.0,
        "RESOURCE_ROUTE": -6.0,
        "HOUSING": 7.4,
        "CIVIC_SERVICE": -7.4,
    }
    for infrastructure in export["world"]["infrastructure"]:
        boundary = spec["boundaries"][infrastructure["boundary_id"]]
        path = [tuple(point) for point in boundary["path"]]
        prefix = f"LD_INFRA__{infrastructure['id']}"
        offset = lane_offsets.get(infrastructure["infrastructure_type"], 6.0)
        pipe_material = (
            materials["metal_dark"] if infrastructure["degraded"] else materials["metal_civic"]
        )
        for index, ((x0, y0), (x1, y1)) in enumerate(zip(path, path[1:], strict=False)):
            dx, dy = x1 - x0, y1 - y0
            span = math.hypot(dx, dy)
            heading = math.atan2(dy, dx)
            nx, ny = -math.sin(heading) * offset, math.cos(heading) * offset
            cx = (x0 + x1) / 2.0 + nx
            cy = (y0 + y1) / 2.0 + ny
            make_box(
                f"{prefix}__pipe{index}",
                (span + 0.6, 0.5, 0.5),
                (cx, cy, 1.55),
                collection,
                pipe_material,
                rotation_z=heading,
                bevel=0.06,
            )
            make_box(
                f"{prefix}__pipe{index}b",
                (span + 0.6, 0.32, 0.32),
                (cx, cy, 2.05),
                collection,
                materials["metal_dark"],
                rotation_z=heading,
                bevel=0.04,
            )
        posts = []
        for x, y, heading in polyline_stations(path, 6.5):
            nx, ny = -math.sin(heading) * offset, math.cos(heading) * offset
            posts.append(((0.34, 0.34, 1.5), (x + nx, y + ny, 0.0), 0))
            posts.append(((0.8, 0.44, 0.12), (x + nx, y + ny, 1.42), 0))
        first = polyline_stations(path, 6.5)[0]
        make_detail_mesh(
            f"{prefix}__posts",
            [
                (size, (ox - first[0], oy - first[1], oz), index)
                for size, (ox, oy, oz), index in posts
            ],
            (first[0], first[1], 0.0),
            collection,
            [materials["metal_dark"]],
        )

        wall = walls_by_boundary.get(infrastructure["boundary_id"])
        if wall is not None:
            station = boundary["wall_station"]
            wx, wy = station["center"]
            dependency = infrastructure["dependency_score"]
            struts = max(1, round(1 + dependency * 3.0))
            for strut in range(struts):
                along = (strut - (struts - 1) / 2.0) * 1.6
                dxn, dyn = station["direction"]
                norm = math.hypot(dxn, dyn) or 1.0
                sx = wx + (dxn / norm) * along
                sy = wy + (dyn / norm) * along
                make_box(
                    f"{prefix}__wallstrut{strut}",
                    (0.5, abs(offset) + 1.4, 0.5),
                    (
                        sx + offset * 0.5 * (dyn / norm),
                        sy - offset * 0.5 * (dxn / norm),
                        1.7,
                    ),
                    collection,
                    materials["metal_civic"],
                    rotation_z=math.atan2(dyn, dxn) + math.pi / 2.0,
                    bevel=0.04,
                )


def apply_districts(export: dict, spec: dict, collections: dict, materials: dict) -> None:
    """Occupancy, storage fill, and isolation gates per district."""
    collection = collections["LD_EPISODE"]
    for district in export["world"]["districts"]:
        district_id = district["id"]
        definition = spec["districts"][district_id]
        occupancy = occupancy_fraction(district)
        material = bpy.data.materials.get(f"LD_MAT__glass_{definition['character']}")
        if material is not None:
            node = material.node_tree.nodes.get("LD_LitFraction")
            if node is not None:
                node.outputs[0].default_value = 0.12 + 0.55 * occupancy

        center_x, center_y = definition["center"]
        length = math.hypot(center_x, center_y) or 1.0
        depot_x = center_x + (center_x / length) * definition["radius"] * 0.62
        depot_y = center_y + (center_y / length) * definition["radius"] * 0.62
        fill = depot_fill_fraction(district, definition["depot_capacity"])
        slots = 8
        visible = round(fill * slots)
        rng = stable_rng(spec["visual_seed"], district_id, "containers")
        base_z = definition["elevation"] + 0.68
        for slot in range(slots):
            row, column = divmod(slot, 4)
            if slot >= visible:
                continue
            stack = 1 + (1 if rng.random() < fill else 0)
            for level in range(stack):
                key = ("container_a", "container_b", "container_c")[(slot + level) % 3]
                make_box(
                    f"LD_EPISODE__depot_{district_id}__{slot}_{level}",
                    (5.6, 2.6, 2.5),
                    (
                        depot_x + (column - 1.5) * 3.0 * 0.98,
                        depot_y + (row - 0.5) * 6.2,
                        base_z + 0.42 + level * 2.55,
                    ),
                    collection,
                    materials[key],
                    rotation_z=rng.uniform(-0.03, 0.03),
                    bevel=0.05,
                )


def apply_law_state(export: dict, spec: dict, collections: dict, materials: dict) -> None:
    """The Golden Seal shows the standing of the movement law.

    The artifact itself never moves or redesigns; only its glow answers the
    law. In force: the plaza ring burns warm. Suspended: the ring goes dark.
    """
    laws = {law["id"]: law for law in export["world"]["laws"]}
    movement = laws.get("law_movement_sharing")
    ring = bpy.data.objects.get("LD_SEAL_RING")
    active = bool(movement is not None and movement["active"] is True)
    if ring is not None:
        glow = bpy.data.materials.get("LD_MAT__seal_glow")
        if glow is not None:
            principled = glow.node_tree.nodes.get("Principled BSDF")
            if principled is not None:
                principled.inputs["Emission Strength"].default_value = 5.0 if active else 0.0


def apply_render_export_file(
    spec_path: str | Path, export_path: str | Path, style: str = "a"
) -> dict:
    """Validate agreement and apply one export's episode state to the scene.

    ``style`` only scales the episode layer's practical lights to match the
    scene's active profile; the episode geometry and state mapping are
    identical across styles.
    """
    require_supported_blender()
    set_practical_light_scale(resolve_style(style)["practical_scale"])
    spec = load_master_scene_spec(spec_path)
    export = load_render_export(export_path)
    require_topology_agreement(spec, export)
    collections = ensure_collections()
    materials = {
        key.removeprefix("LD_MAT__"): value
        for key, value in ((m.name, m) for m in bpy.data.materials)
        if key.startswith("LD_MAT__")
    }
    clear_episode_layer(collections)
    apply_walls(export, spec, collections, materials)
    apply_infrastructure(export, spec, collections, materials)
    apply_districts(export, spec, collections, materials)
    apply_law_state(export, spec, collections, materials)
    return export


def main() -> None:
    """Command-line entry: apply one export to the current scene."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--export", required=True)
    parser.add_argument("--save", default="")
    arguments = parser.parse_args(argv)
    apply_render_export_file(arguments.spec, arguments.export)
    if arguments.save.strip():
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(arguments.save).resolve()))


if __name__ == "__main__":
    main()
