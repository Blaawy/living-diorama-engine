"""Instantiate the Phase 19 daily-life mobility layer inside Blender.

The runtime INSTANTIATES; it does not decide. Every route, every speed, every
archetype and every wheel revolution is read from the pure Daily Life Mobility
Plan, which was derived from the LOCKED Phase 16 road graph and the LOCKED
Phase 18 presence plan and proven collision free on every frame before Blender
was ever opened. A bug in this file can make the world look wrong; it cannot
make the world's claim about its movement untrue.

The layer is deliberately isolated and deliberately REMOVABLE:

* one collection, ``LD_MOBILITY``, under the existing ``LD_WORLD`` root;
* vehicles named ``LD_VEH__slot_NNN`` with four wheel children each;
* one path per pedestrian, one per vehicle circuit (V1) and one per V2
  vehicle, ``LD_MOBILITY_PATH__*``;
* every action named ``LD_MOBILITY__*``, so Phase 17's ``LD_MOTION__`` family is
  untouched and neither can be mistaken for the other;
* materials under ``LD_VEH_MAT__``, so nothing Phase 15, 16 or 18 counts as its
  own material family ever changes.

    PHASE 18 IS BORROWED, NEVER REBUILT.

A walking proxy is the SAME object Phase 18 built. Phase 19 adds three things to
it and takes all three away again: a follow-path constraint, a set of gait shape
keys, and a zeroed transform whose original is recorded in the plan. Clearing
restores the transform, drops the shape keys and removes the constraint, so the
scene returns to the exact Phase 18 population it started from -- which the
structural suite proves by comparing every transform and every mesh before and
after.

WHY PATHS AND NOT BAKED KEYS
----------------------------
A closed curve with an animated ``eval_time`` gives exact loop closure by
construction: Blender's path table is arc-length parameterised, so a vehicle
travels at a constant speed and arrives back at its own first vertex, with its
own first heading, on the last frame. Baking the same motion would have cost
roughly thirty thousand keyframes and still only closed the loop to whatever
precision the sampler happened to have.

V2 VEHICLES RIDE THEIR OWN ARC, NOT THE SHARED LAP
--------------------------------------------------
The shared curve's ``eval_time`` sweeps one full lap, which is exactly the V1
loop contract and exactly what a V2 bounded arc must NOT do. A V2 vehicle
therefore rides its OWN curve object -- a real, geometry-identical copy of the
circuit's cyclic spline (same points, same ``use_cyclic_u``; copying points is
not inventing a road) -- with ``eval_time`` keyed from its own starting phase
to ``phase + arc_fraction`` of the loop across the SAME start..end frames. It
keeps moving continuously and smoothly for the whole clip, covers strictly
less than a full lap, and never returns to a screen position it already
occupied. See ``build_vehicle_arc_path`` and ``apply_vehicle_mobility``.
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

import bmesh
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pedestrian_mobility as walking  # noqa: E402
import vehicle_kit  # noqa: E402
from blender_runtime import add_bevel, link_only, replace_object  # noqa: E402
from mobility_plan import mobility_plan_hash  # noqa: E402

MOBILITY_ROOT = "LD_MOBILITY"
VEHICLE_PREFIX = "LD_VEH__"
PATH_PREFIX = "LD_MOBILITY_PATH__"
ACTION_PREFIX = "LD_MOBILITY__"
MATERIAL_PREFIX = "LD_VEH_MAT__"
MESH_PREFIX = "LD_VEH_MESH__"
GAIT_KEY_PREFIX = "LD_GAIT__"

MAX_ID_NAME_BYTES = 63
"""Blender silently truncates identifiers past this, and a truncated name breaks
replace-by-name -- which breaks idempotency. Refused loudly instead."""

DUPLICATE_SUFFIX = re.compile(r"\.\d{3}$")
"""Blender's collision rename. Finding one anywhere in the layer means a rebuild
grew the scene instead of replacing it."""

PAINT_COLORS = {
    "graphite": (0.055, 0.058, 0.064),
    "bone": (0.412, 0.398, 0.368),
    "olive": (0.116, 0.132, 0.086),
    "oxide": (0.196, 0.086, 0.058),
    "steel": (0.148, 0.160, 0.178),
    "navy": (0.062, 0.074, 0.128),
}
"""Muted paint families, sitting inside the city's existing material range."""

GLASS_COLOR = (0.052, 0.062, 0.072)
TRIM_COLOR = (0.028, 0.028, 0.030)
LAMP_COLOR = (0.640, 0.600, 0.580)
TAIL_COLOR = (0.420, 0.045, 0.040)
"""Rear lights are their own family, not the headlight family tinted. A car
whose front and rear lights read the same is a car whose direction of travel a
viewer has to infer from its motion."""

VEHICLE_BEVEL = 0.010
"""Edge softening on a vehicle body. A car's panel edges are radiused and its
glass is flush; ten millimetres reads as both at diorama distance."""


class MobilityApplyError(RuntimeError):
    """A Phase 19 runtime contract violation. Always a refusal, never a repair."""


# ---------------------------------------------------------------------------
# Collections, materials, naming
# ---------------------------------------------------------------------------


def ensure_mobility_collection() -> bpy.types.Collection:
    """Create (or fetch) ``LD_MOBILITY`` under the master scene root."""
    root = bpy.data.collections.get("LD_WORLD")
    if root is None:
        raise MobilityApplyError(
            "the master scene is not built; run build_master_scene before adding mobility"
        )
    collection = bpy.data.collections.get(MOBILITY_ROOT)
    if collection is None:
        collection = bpy.data.collections.new(MOBILITY_ROOT)
    if collection.name not in {child.name for child in root.children}:
        root.children.link(collection)
    return collection


def _require_name(name: str) -> str:
    """Refuse a datablock name Blender would silently truncate."""
    if len(name.encode("utf-8")) > MAX_ID_NAME_BYTES:
        raise MobilityApplyError(
            f"name {name!r} exceeds Blender's {MAX_ID_NAME_BYTES}-byte identifier limit"
        )
    return name


def _flat_material(name: str, color: tuple, roughness: float, metallic: float):
    """One matte or semi-gloss surface, reused when it already exists."""
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(_require_name(name))
    material.use_nodes = True
    principled = material.node_tree.nodes["Principled BSDF"]
    principled.inputs["Base Color"].default_value = (*color, 1.0)
    principled.inputs["Roughness"].default_value = roughness
    principled.inputs["Metallic"].default_value = metallic
    return material


def build_vehicle_materials() -> dict:
    """The Phase 19 vehicle material set, under its own prefix."""
    materials = {
        f"paint_{name}": _flat_material(f"{MATERIAL_PREFIX}paint_{name}", color, 0.38, 0.15)
        for name, color in sorted(PAINT_COLORS.items())
    }
    materials["glass"] = _flat_material(f"{MATERIAL_PREFIX}glass", GLASS_COLOR, 0.08, 0.0)
    materials["trim"] = _flat_material(f"{MATERIAL_PREFIX}trim", TRIM_COLOR, 0.82, 0.0)
    materials["lamp"] = _flat_material(f"{MATERIAL_PREFIX}lamp", LAMP_COLOR, 0.30, 0.0)
    materials["tail"] = _flat_material(f"{MATERIAL_PREFIX}tail", TAIL_COLOR, 0.34, 0.0)
    return materials


# ---------------------------------------------------------------------------
# Clearing: the Phase 18 recovery contract
# ---------------------------------------------------------------------------


def clear_mobility_layer() -> dict:
    """Remove every trace of Phase 19, restoring the Phase 18 scene exactly.

    Four things come off, in an order that matters: the actions first (so no
    curve is left driving a property that is about to vanish), then the gait
    shape keys and the follow-path constraints from the BORROWED Phase 18
    proxies, then the vehicles and their meshes, then the paths and the
    collection itself.

    An empty ``LD_MOBILITY`` hanging under ``LD_WORLD`` is a trace, so the
    collection goes too. "Fully removable" has to mean the file carries no sign
    the layer was ever there.
    """
    removed = {"actions": 0, "vehicles": 0, "paths": 0, "shape_keys": 0, "constraints": 0}
    holders = [*bpy.data.objects, *bpy.data.curves, *(key for key in bpy.data.shape_keys)]
    for holder in holders:
        animation = getattr(holder, "animation_data", None)
        if animation is None or animation.action is None:
            continue
        if animation.action.name.startswith(ACTION_PREFIX):
            holder.animation_data_clear()
    for action in list(bpy.data.actions):
        if action.name.startswith(ACTION_PREFIX):
            bpy.data.actions.remove(action)
            removed["actions"] += 1
    for obj in list(bpy.data.objects):
        if obj.name.startswith(VEHICLE_PREFIX):
            bpy.data.objects.remove(obj, do_unlink=True)
            removed["vehicles"] += 1
            continue
        if not obj.name.startswith("LD_POP__"):
            continue
        for constraint in list(obj.constraints):
            if constraint.name.startswith(ACTION_PREFIX):
                obj.constraints.remove(constraint)
                removed["constraints"] += 1
        if obj.type == "MESH" and obj.data.shape_keys is not None:
            removed["shape_keys"] += len(obj.data.shape_keys.key_blocks)
            obj.shape_key_clear()
    for mesh in list(bpy.data.meshes):
        if mesh.name.startswith(MESH_PREFIX):
            bpy.data.meshes.remove(mesh, do_unlink=True)
    for obj in list(bpy.data.objects):
        if obj.name.startswith(PATH_PREFIX):
            bpy.data.objects.remove(obj, do_unlink=True)
            removed["paths"] += 1
    for curve in list(bpy.data.curves):
        if curve.name.startswith(PATH_PREFIX):
            bpy.data.curves.remove(curve, do_unlink=True)
    collection = bpy.data.collections.get(MOBILITY_ROOT)
    if collection is not None:
        bpy.data.collections.remove(collection)
    return removed


def restore_population_transforms(plan: dict) -> int:
    """Put every borrowed Phase 18 proxy back on its own anchor.

    A walking proxy is driven by a path, so its own transform is zeroed while
    Phase 19 is applied. The anchor it came from is recorded in the plan, which
    is what makes the restoration exact rather than approximate: the number put
    back is the number Phase 18 published, not one measured off a scene that
    Phase 19 had already touched.
    """
    restored = 0
    for walker in plan["pedestrians"]["walkers"]:
        obj = bpy.data.objects.get(f"LD_POP__{walker['slot']}")
        if obj is None:
            continue
        anchor = walker["anchor"]
        obj.location = (float(anchor["x"]), float(anchor["y"]), float(anchor["z"]))
        obj.rotation_euler = (0.0, 0.0, float(anchor["heading"]))
        restored += 1
    return restored


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _key_curve(holder, data_path: str, keys: list, label: str, apply_value, index: int = -1) -> int:
    """Write one F-curve with exactly these keys and LINEAR interpolation.

    Through ``keyframe_insert`` so Blender's own slotted-action machinery stays
    authoritative, then every keyframe's interpolation is overwritten -- the
    Bezier default never survives, exactly as Phase 17 established. The value is
    written by an explicit callable rather than by parsing the data path, since
    a shape key's path carries its own name in brackets and no parser should
    have to tell that apart from an array index.
    """
    for frame, value in keys:
        apply_value(value)
        if index >= 0:
            holder.keyframe_insert(data_path, index=index, frame=frame)
        else:
            holder.keyframe_insert(data_path, frame=frame)
    action = holder.animation_data.action
    wanted = _require_name(f"{ACTION_PREFIX}{label}")
    if action.name != wanted:
        action.name = wanted
        if action.name != wanted:
            raise MobilityApplyError(f"action {wanted!r} collides with an existing datablock")
    curve = action.fcurves.find(data_path, index=max(index, 0))
    if curve is None:
        raise MobilityApplyError(f"{label}: {data_path} produced no F-curve")
    if len(curve.keyframe_points) != len(keys):
        raise MobilityApplyError(
            f"{label}: {data_path} holds {len(curve.keyframe_points)} keys, the plan asked "
            f"for {len(keys)}"
        )
    for keyframe in curve.keyframe_points:
        keyframe.interpolation = "LINEAR"
        keyframe.easing = "AUTO"
    curve.update()
    return len(curve.keyframe_points)


def build_path(
    name: str, points: list, timeline: dict, collection: bpy.types.Collection
) -> bpy.types.Object:
    """One closed, arc-length-parameterised path through world coordinates.

    A POLY spline sampled finely enough that its tangent IS the route's tangent.
    Blender interpolates a path's orientation between control points, so a
    coarse curve reports a heading averaged across a whole straight -- a car
    crabbing down its own lane. The plan's points are already at the declared
    sample step for exactly this reason.

    The curve object is left at the origin with an identity transform, so the
    world coordinates baked into the spline are the world coordinates a rider
    lands on.
    """
    replace_object(name)
    existing = bpy.data.curves.get(name)
    if existing is not None:
        bpy.data.curves.remove(existing, do_unlink=True)
    curve = bpy.data.curves.new(_require_name(name), type="CURVE")
    curve.dimensions = "3D"
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, (x, y, z) in zip(spline.points, points, strict=True):
        point.co = (float(x), float(y), float(z), 1.0)
    spline.use_cyclic_u = True
    curve.use_path = True
    curve.path_duration = int(timeline["frame_span"])
    curve.eval_time = 0.0
    obj = bpy.data.objects.new(name, curve)
    obj.location = (0.0, 0.0, 0.0)
    link_only(obj, collection)

    def _set_eval(value: float) -> None:
        curve.eval_time = value

    _key_curve(
        curve,
        "eval_time",
        [
            (timeline["start_frame"], 0.0),
            (timeline["end_frame"], float(timeline["frame_span"])),
        ],
        f"path__{name.removeprefix(PATH_PREFIX)}",
        _set_eval,
    )
    return obj


def build_vehicle_arc_path(
    name: str,
    points: list,
    timeline: dict,
    collection: bpy.types.Collection,
    start_fraction: float,
    end_fraction: float,
) -> bpy.types.Object:
    """One V2 vehicle's OWN cyclic curve, riding a bounded arc of a circuit.

    A V2 vehicle never drives a full lap, so it cannot ride the circuit's
    shared full-lap ``eval_time`` sweep the way V1 does -- ``eval_time`` is a
    property of the shared curve datablock, so giving a vehicle its own arc
    requires giving it its own curve OBJECT. This builds a real,
    geometry-identical COPY of the circuit's cyclic spline: same points, same
    ``use_cyclic_u = True`` (the curve is still the circuit's real closed road
    geometry; copying its points is not inventing a road). ``eval_time`` is
    keyed from ``start_fraction * frame_span`` to ``end_fraction * frame_span``
    linearly across the SAME ``start_frame..end_frame`` range, so the vehicle
    moves continuously and smoothly for the entire clip -- no freeze, no stop,
    no despawn -- while covering strictly less than one full lap.

    With ``start_fraction`` = the vehicle's slot phase and ``end_fraction`` =
    phase + arc_fraction (< phase + 1 because arc_fraction < 1), the vehicle
    starts at its real position on the loop (preserved from V1) and never
    returns to a position it has already occupied on screen within the clip:
    the curve's cyclic wrap can only engage past one full loop, which the arc
    never reaches. The follow-path constraint is attached with a ZERO offset,
    so the evaluated position is exactly ``eval_time`` -- the same number the
    plan's collision proof samples (``phase * length + arc_fraction * length *
    (frame - start) / span``), keeping the two in exact agreement.
    """
    replace_object(name)
    existing = bpy.data.curves.get(name)
    if existing is not None:
        bpy.data.curves.remove(existing, do_unlink=True)
    curve = bpy.data.curves.new(_require_name(name), type="CURVE")
    curve.dimensions = "3D"
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, (x, y, z) in zip(spline.points, points, strict=True):
        point.co = (float(x), float(y), float(z), 1.0)
    spline.use_cyclic_u = True
    curve.use_path = True
    curve.path_duration = int(timeline["frame_span"])
    curve.eval_time = 0.0
    obj = bpy.data.objects.new(name, curve)
    obj.location = (0.0, 0.0, 0.0)
    link_only(obj, collection)

    def _set_eval(value: float) -> None:
        curve.eval_time = value

    span = float(timeline["frame_span"])
    _key_curve(
        curve,
        "eval_time",
        [
            (timeline["start_frame"], start_fraction * span),
            (timeline["end_frame"], end_fraction * span),
        ],
        f"path__{name.removeprefix(PATH_PREFIX)}",
        _set_eval,
    )
    return obj


def attach_to_path(obj, path_obj, phase: float, timeline: dict, label: str) -> None:
    """Ride one object on one path, oriented by the path's own tangent.

    The object's forward axis is +X, matching both the Phase 18 figure kit and
    the Phase 19 vehicle kit, so a body faces the way it walks and a bonnet
    points down the lane. The phase becomes a frame offset, which is how a whole
    circuit's traffic rides ONE curve at fixed spacings instead of needing a
    curve each.
    """
    constraint = obj.constraints.new("FOLLOW_PATH")
    constraint.name = _require_name(f"{ACTION_PREFIX}follow__{label}")
    constraint.target = path_obj
    constraint.use_curve_follow = True
    constraint.forward_axis = "FORWARD_X"
    constraint.up_axis = "UP_Z"
    constraint.offset = -float(phase) * float(timeline["frame_span"])
    obj.location = (0.0, 0.0, 0.0)
    obj.rotation_euler = (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Pedestrians
# ---------------------------------------------------------------------------


def apply_gait(obj, walker: dict, mobility_spec: dict, timeline: dict) -> dict:
    """Give one borrowed Phase 18 body the stride its route demands.

    The shape keys are the PURE kit's own articulated bodies, in the pure kit's
    own vertex order, so the deformation a reviewer can measure on a machine
    with no Blender is the deformation the render performs.

    Each key's value is a triangular hat that peaks at its own phase and is zero
    at every other, so the phases blend as a partition of unity and the body is
    always exactly one interpolated pose. One whole gait cycle is keyed and a
    CYCLES modifier repeats it, which is why a walk that takes forty-one strides
    costs thirty-six keyframes rather than a keyframe a frame.
    """
    mesh = obj.data
    if mesh.shape_keys is not None:
        raise MobilityApplyError(f"{obj.name} already carries shape keys before Phase 19")
    if mesh.users != 1:
        raise MobilityApplyError(
            f"{obj.name} shares its mesh with {mesh.users - 1} other object(s); giving it a "
            "gait would make them all walk"
        )
    cycle = walker["gait"]
    shapes = walking.gait_shapes(walker, cycle, mobility_spec)
    if any(len(shape) != len(mesh.vertices) for shape in shapes):
        raise MobilityApplyError(
            f"{obj.name} has {len(mesh.vertices)} vertices, the gait supplies {len(shapes[0])}"
        )
    obj.shape_key_add(name=f"{GAIT_KEY_PREFIX}basis", from_mix=False)
    blocks = []
    for index, shape in enumerate(shapes):
        block = obj.shape_key_add(name=f"{GAIT_KEY_PREFIX}p{index:02d}", from_mix=False)
        block.slider_min = 0.0
        block.slider_max = 1.0
        for vertex, position in zip(block.data, shape, strict=True):
            vertex.co = position
        blocks.append(block)

    phases = len(shapes)
    span = float(timeline["frame_span"]) / int(cycle["cycles"])
    keyframes = 0
    for index, block in enumerate(blocks):
        keys = []
        for step in range(phases + 1):
            frame = timeline["start_frame"] + span * step / phases
            keys.append((frame, 1.0 if step % phases == index else 0.0))
        keyframes += _key_curve(
            mesh.shape_keys,
            f'key_blocks["{block.name}"].value',
            keys,
            f"gait__{walker['slot']}",
            lambda value, target=block: setattr(target, "value", value),
        )
    for curve in mesh.shape_keys.animation_data.action.fcurves:
        if not any(modifier.type == "CYCLES" for modifier in curve.modifiers):
            curve.modifiers.new("CYCLES")
    return {"shape_keys": len(blocks) + 1, "keyframes": keyframes, "gait_cycles": cycle["cycles"]}


def apply_pedestrian_mobility(plan: dict, mobility_spec: dict, collection) -> dict:
    """Set every selected Phase 18 proxy walking its own closed route."""
    timeline = plan["timeline"]
    built = 0
    metrics = {"shape_keys": 0, "keyframes": 0, "paths": 0}
    for walker in sorted(plan["pedestrians"]["walkers"], key=lambda entry: entry["slot"]):
        obj = bpy.data.objects.get(f"LD_POP__{walker['slot']}")
        if obj is None:
            raise MobilityApplyError(
                f"the plan walks {walker['slot']}, which the Phase 18 population layer did "
                "not build; mobility never creates a person"
            )
        path = build_path(
            f"{PATH_PREFIX}ped__{walker['slot']}", walker["points"], timeline, collection
        )
        attach_to_path(obj, path, 0.0, timeline, f"ped__{walker['slot']}")
        gait = apply_gait(obj, walker, mobility_spec, timeline)
        metrics["shape_keys"] += gait["shape_keys"]
        metrics["keyframes"] += gait["keyframes"]
        metrics["paths"] += 1
        built += 1
    metrics["walkers"] = built
    return metrics


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------


def _weld(name: str, mesh_data: dict, materials: list) -> bpy.types.Mesh:
    """Turn one pure vehicle mesh into a Blender mesh datablock."""
    builder = bmesh.new()
    vertices = [builder.verts.new(vertex) for vertex in mesh_data["vertices"]]
    builder.verts.ensure_lookup_table()
    for corners, material_index in zip(mesh_data["faces"], mesh_data["materials"], strict=True):
        face = builder.faces.new([vertices[index] for index in corners])
        face.material_index = material_index
    bmesh.ops.recalc_face_normals(builder, faces=list(builder.faces))
    mesh = bpy.data.meshes.new(_require_name(name))
    builder.to_mesh(mesh)
    builder.free()
    for material in materials:
        mesh.materials.append(material)
    return mesh


def build_vehicle(vehicle: dict, materials: dict, collection, shared: dict) -> tuple:
    """One vehicle body and its four turning wheels.

    The wheels are CHILDREN with their own origins at their own axles, which is
    the only way a wheel can turn: a wheel welded into the body could only ever
    be a painted circle. Their rotation is keyed from the distance the vehicle
    actually travels, so a wheel cannot spin at a speed the car is not doing.

    Meshes are SHARED by archetype and paint, and genuinely so: seven compacts
    in two colours cost two body meshes, not seven. The key includes the paint
    because material slots live on the mesh datablock, so sharing across colours
    would repaint a car. Naming a mesh after its archetype without sharing it was
    worse than either -- Blender renamed the second one and the layer grew a
    ``.001`` twin every rebuild.
    """
    slots = [
        materials[f"paint_{vehicle['paint']}"],
        materials["glass"],
        materials["trim"],
        materials["lamp"],
        materials["tail"],
    ]
    archetype, paint = vehicle["archetype"], vehicle["paint"]
    body_key = ("body", archetype, paint)
    if body_key not in shared:
        shared[body_key] = _weld(
            f"{MESH_PREFIX}body__{archetype}__{paint}",
            vehicle_kit.vehicle_mesh(archetype),
            slots,
        )
    wheel_key = ("wheel", archetype, paint)
    if wheel_key not in shared:
        shared[wheel_key] = _weld(
            f"{MESH_PREFIX}wheel__{archetype}__{paint}",
            vehicle_kit.wheel_mesh(archetype),
            slots,
        )
    name = f"{VEHICLE_PREFIX}{vehicle['slot']}"
    replace_object(name)
    body = bpy.data.objects.new(name, shared[body_key])
    add_bevel(body, width=VEHICLE_BEVEL)
    link_only(body, collection)
    wheels = []
    for corner, offset in sorted(vehicle_kit.wheel_offsets(archetype).items()):
        wheel_name = f"{name}__wheel_{corner}"
        replace_object(wheel_name)
        wheel = bpy.data.objects.new(wheel_name, shared[wheel_key])
        wheel.parent = body
        wheel.location = offset
        link_only(wheel, collection)
        wheels.append(wheel)
    return body, wheels


def apply_vehicle_mobility(plan: dict, materials: dict, collection) -> dict:
    """Put the city's ambient traffic on its circuits and set it moving.

    V1 vehicles share ONE curve per circuit and ride it at fixed phase offsets,
    completing exactly one full lap per clip (loop closure by construction). A
    V2 vehicle (a plan entry carrying ``presentation_arc_fraction``) instead
    rides its OWN curve object -- a geometry-identical copy of its circuit's
    cyclic spline -- whose ``eval_time`` sweeps only the vehicle's bounded arc
    (see ``build_vehicle_arc_path``), so it travels a real, non-repeating
    slice of the road and ends at a genuinely different place than it started,
    without ever freezing, stopping or despawning. The wheel keyframing below
    is shared by both profiles: it reads each vehicle's own ``wheel_turns``,
    which the V2 plan computes over the arc at the real wheel radius (no
    rolling-radius solve), so the wheels roll forward at the speed the car is
    actually doing.
    """
    timeline = plan["timeline"]
    paths = {}
    circuit_points = {}
    for circuit in plan["vehicles"]["circuits"]:
        paths[circuit["circuit"]] = build_path(
            f"{PATH_PREFIX}veh__{circuit['circuit']}", circuit["points"], timeline, collection
        )
        circuit_points[circuit["circuit"]] = circuit["points"]
    triangles = 0
    keyframes = 0
    shared: dict = {}
    for vehicle in sorted(plan["vehicles"]["vehicles"], key=lambda entry: entry["slot"]):
        body, wheels = build_vehicle(vehicle, materials, collection, shared)
        if "presentation_arc_fraction" in vehicle:
            phase = float(vehicle["phase"])
            arc = float(vehicle["presentation_arc_fraction"])
            if not 0.0 < arc < 1.0:
                raise MobilityApplyError(
                    f"{vehicle['slot']} claims an arc fraction {arc} outside (0, 1); a bounded "
                    "arc must be strictly less than one full lap"
                )
            path = build_vehicle_arc_path(
                f"{PATH_PREFIX}veh2__{vehicle['slot']}",
                circuit_points[vehicle["circuit"]],
                timeline,
                collection,
                phase,
                phase + arc,
            )
            # Offset zero: the vehicle's own eval_time already encodes its
            # starting phase, so the evaluated position is exactly eval_time,
            # the number the collision proof samples. No shared-curve offset.
            attach_to_path(body, path, 0.0, timeline, vehicle["slot"])
        else:
            attach_to_path(
                body, paths[vehicle["circuit"]], vehicle["phase"], timeline, vehicle["slot"]
            )
        turn = 2.0 * math.pi * float(vehicle["wheel_turns"])
        # Start each wheel where its own car already is. Keying every wheel from
        # zero makes all seven compacts show the SAME mark at the same angle on
        # every frame, which reads as a fleet of clones; a car a fraction of the
        # loop ahead has rolled that fraction of the loop. Closure is untouched
        # because only the offset moves and the span is still whole revolutions
        # (V1) -- or, for a V2 arc, the span is simply the arc's own wheel
        # travel and no closure applies at all.
        start = turn * float(vehicle["phase"])
        for wheel in wheels:
            keyframes += _key_curve(
                wheel,
                "rotation_euler",
                [(timeline["start_frame"], start), (timeline["end_frame"], start + turn)],
                f"wheel__{wheel.name.removeprefix(VEHICLE_PREFIX)}",
                lambda value, target=wheel: target.rotation_euler.__setitem__(1, value),
                index=1,
            )
        triangles += vehicle_kit.vehicle_triangles(vehicle["archetype"])
    return {
        "vehicles": len(plan["vehicles"]["vehicles"]),
        "wheels": 4 * len(plan["vehicles"]["vehicles"]),
        "paths": len(paths),
        "keyframes": keyframes,
        "triangles": triangles,
        "distinct_meshes": len(shared),
    }


# ---------------------------------------------------------------------------
# The layer
# ---------------------------------------------------------------------------


def apply_mobility(plan: dict, mobility_spec: dict) -> dict:
    """Build the whole daily-life mobility layer from one mobility plan.

    Clears first and fetches the collection afterwards, so re-applying the same
    plan converges on the same scene instead of growing a second copy of it.
    """
    clear_mobility_layer()
    restore_population_transforms(plan)
    collection = ensure_mobility_collection()
    materials = build_vehicle_materials()
    pedestrians = apply_pedestrian_mobility(plan, mobility_spec, collection)
    vehicles = apply_vehicle_mobility(plan, materials, collection)
    scene = bpy.context.scene
    scene.frame_start = int(plan["timeline"]["start_frame"])
    scene.frame_end = int(plan["timeline"]["end_frame"])
    scene.render.fps = int(plan["timeline"]["fps"])
    return {
        "pedestrians": pedestrians,
        "vehicles": vehicles,
        "collection": MOBILITY_ROOT,
        "plan_hash": mobility_plan_hash(plan),
    }


def mobility_objects() -> list:
    """Every Phase 19 object, in stable name order."""
    return sorted(
        (item for item in bpy.data.objects if item.name.startswith((VEHICLE_PREFIX, PATH_PREFIX))),
        key=lambda item: item.name,
    )


def mobility_summary() -> dict:
    """What the scene actually holds, read back from Blender itself.

    Read back rather than remembered: a manifest that reported what the builder
    intended would prove nothing about what the ``.blend`` carries.
    """
    objects = mobility_objects()
    vehicles = [item for item in objects if item.name.startswith(VEHICLE_PREFIX)]
    bodies = [item for item in vehicles if "__wheel_" not in item.name]
    triangles = 0
    for item in vehicles:
        item.data.calc_loop_triangles()
        triangles += len(item.data.loop_triangles)
    actions = [action for action in bpy.data.actions if action.name.startswith(ACTION_PREFIX)]
    walkers = [
        item
        for item in bpy.data.objects
        if item.name.startswith("LD_POP__")
        and any(constraint.type == "FOLLOW_PATH" for constraint in item.constraints)
    ]
    shape_keys = sum(
        len(item.data.shape_keys.key_blocks)
        for item in walkers
        if item.type == "MESH" and item.data.shape_keys is not None
    )
    collection = bpy.data.collections.get(MOBILITY_ROOT)
    return {
        "vehicle_bodies": len(bodies),
        "vehicle_wheels": len(vehicles) - len(bodies),
        "paths": sum(1 for item in objects if item.name.startswith(PATH_PREFIX)),
        "walking_proxies": len(walkers),
        "gait_shape_keys": shape_keys,
        "actions": len(actions),
        "fcurves": sum(len(action.fcurves) for action in actions),
        "keyframes": sum(
            len(curve.keyframe_points) for action in actions for curve in action.fcurves
        ),
        "vehicle_triangles": triangles,
        "duplicate_named_objects": sum(1 for item in objects if DUPLICATE_SUFFIX.search(item.name))
        + sum(
            1
            for mesh in bpy.data.meshes
            if mesh.name.startswith(MESH_PREFIX) and DUPLICATE_SUFFIX.search(mesh.name)
        ),
        "materials": sorted(
            name
            for name in (item.name for item in bpy.data.materials)
            if name.startswith(MATERIAL_PREFIX)
        ),
        "collection_present": collection is not None,
        "linked_elsewhere": sum(
            1
            for item in objects
            if {entry.name for entry in item.users_collection} != {MOBILITY_ROOT}
        ),
    }


def mobility_transforms() -> dict:
    """Every mover's evaluated world transform, for structural comparison.

    Evaluated, because a follow-path constraint is not in an object's own
    transform: the depsgraph has to be updated before ``matrix_world`` means
    anything at all, and in background Blender it is lazy enough that a whole
    suite can pass vacuously without it.
    """
    bpy.context.view_layer.update()
    out = {}
    for obj in bpy.data.objects:
        if not obj.name.startswith((VEHICLE_PREFIX, "LD_POP__")):
            continue
        matrix = obj.matrix_world
        out[obj.name] = (
            round(matrix[0][3], 6),
            round(matrix[1][3], 6),
            round(matrix[2][3], 6),
            round(math.atan2(matrix[1][0], matrix[0][0]), 6),
        )
    return out


def main() -> None:
    """Blender entry point: apply one mobility plan to the open scene."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, help="daily life mobility plan JSON")
    parser.add_argument("--spec", required=True, help="daily life mobility spec JSON")
    arguments = parser.parse_args(argv)
    plan = json.loads(Path(arguments.plan).read_text(encoding="utf-8"))
    spec = json.loads(Path(arguments.spec).read_text(encoding="utf-8"))
    print(json.dumps(apply_mobility(plan, spec), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
