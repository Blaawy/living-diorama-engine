"""Render the Phase 19 vehicle QA plates: five cars, three views, no city.

WHY THIS FILE EXISTS
--------------------
The Director rejected the previous traffic as "a generic low-poly box that
moves". Judging the replacement must not cost a three-hour city render, because
a review loop whose unit of feedback is three hours is a review loop nobody
runs twice.

    A REVIEWER MUST BE ABLE TO REJECT A CAR WITHOUT RENDERING A CITY.

So this file builds nothing but cars. It stands them on a seamless studio
backdrop in an otherwise empty scene and takes three deliberately different
views:

    phase19_vehicle_style_verify.png       all five, three-quarter, one row
    phase19_vehicle_side_verify.png        sedan, SUV, coupe, near profile, close
    phase19_vehicle_silhouette_verify.png  all five, ONE flat colour, in profile

THE PLATE MAY NOT FLATTER THE CAR
---------------------------------
Which is why the bevel and every paint, glass, trim, lamp and tail colour come
from :mod:`apply_mobility` itself rather than being chosen here. A plate that
lit a car better than the city lights it, or softened an edge the city leaves
hard, would be evidence about the plate.

The three views also disagree on purpose. The style plate is shot from each
car's RIGHT and the side plate from its LEFT, so both flanks of every archetype
appear somewhere in the pack. Anything the kit emits on one side only then
shows up as a difference between two pictures instead of as nothing at all.

THE EXOTIC QA VIEWS
-------------------
The Codex-era coupe QA was produced by a throwaway derivative of this file that
no longer exists, which made that QA unreproducible: four pictures nobody could
take again are four pictures nobody can compare against. ``--exotic-qa`` folds
the recovered run back into the file it was derived from. It stages the coupe
ALONE in the same studio rig and takes the four views at the bearings and
elevations recovered from the run log -- front three-quarter, side, rear
three-quarter and silhouette -- under their original output names. Only the
camera parameters were recovered; everything else the views need, they inherit
from the plates above, so the coupe is photographed the way this file already
photographs it rather than the way a lost script might have.

WHAT THIS IS NOT
----------------
Not a proof, not a manifest, not evidence of what the city contains. No plate
vehicle exists in any city build, no plate reads a mobility plan, and nothing
here is packaged. It is a look at the kit, and only that.

Run headless::

    blender --background --factory-startup --python \
        produce_vehicle_style_plate.py -- --outdir <dir> [--preview]

or, for the four recovered coupe QA views (the originals were 48 samples at
1280x720, which is what ``--preview`` means here)::

    blender --background --factory-startup --python \
        produce_vehicle_style_plate.py -- --exotic-qa --outdir <dir> --preview
"""

import argparse
import math
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NamedTuple

import bmesh
import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vehicle_kit  # noqa: E402
from apply_mobility import (  # noqa: E402
    GLASS_COLOR,
    LAMP_COLOR,
    PAINT_COLORS,
    TAIL_COLOR,
    TRIM_COLOR,
    VEHICLE_BEVEL,
)
from blender_runtime import (  # noqa: E402
    add_bevel,
    link_only,
    look_at_rotation,
    require_supported_blender,
)
from render_visual_proof import configure_cycles_device  # noqa: E402

PLATE_PREFIX = "LD_VEH_PLATE__"
MATERIAL_PREFIX = "LD_VEH_PLATE_MAT__"

STYLE_PLATE = "phase19_vehicle_style_verify.png"
SIDE_PLATE = "phase19_vehicle_side_verify.png"
SILHOUETTE_PLATE = "phase19_vehicle_silhouette_verify.png"

EXOTIC_ARCHETYPE = "coupe"
"""The one archetype the exotic QA stages. The coupe carries the split glazing
variant nothing else uses, which is why it was the car the Codex-era QA singled
out and why the reproduction stages nothing else."""

EXOTIC_QA_VIEWS = (
    ("phase19_exotic_front_threequarter_verify.png", -52.0, 14.0, False),
    ("phase19_exotic_side_verify.png", 90.0, 3.0, False),
    ("phase19_exotic_rear_threequarter_verify.png", 132.0, 13.0, False),
    ("phase19_exotic_silhouette_verify.png", 90.0, 2.5, True),
)
"""Filename, bearing, elevation and the silhouette treatment, one row per view.

The bearings and elevations are the ones recovered from the Codex run log, kept
as data rather than folded into build functions so the whole recovered camera
set can be read in one place and compared against that log. The final view is
the silhouette treatment -- one flat material on the bright field -- because
that is what its name has always claimed it to be."""

STYLE_ORDER = vehicle_kit.ARCHETYPES
"""The lineup order, which is also the label: compact, sedan, SUV, van, coupe.

There is no text on any plate. Text would have to be modelled, lit and kept
legible at three framings, and it would tell a reviewer what to see. The order
is fixed and printed on the console instead, so the plate says nothing about
the cars that the cars do not say themselves."""

SIDE_ORDER = ("sedan", "suv", "coupe")
"""The three archetypes whose detail has to survive close inspection.

The sedan is the only three-box car, the SUV is the tallest thing with a
conventional roofline, and the coupe carries the split glazing variant nothing
else uses. If door seams, B pillars, mirrors and arches read on these three,
they read."""

PLATE_PAINT = {
    "compact": "oxide",
    "sedan": "steel",
    "suv": "olive",
    "van": "bone",
    "coupe": "navy",
}
"""One CITY paint family per archetype, chosen so neighbours contrast.

The values are the applier's own, not brighter ones invented for a photograph.
``graphite`` is the one family left out: at 0.055 it is darker than the trim it
sits against, so a graphite car shows nothing but its lamps -- which is a fact
about the palette, reported here rather than hidden by a plate that quietly
declined to use it."""

CITY_SURFACE = {
    "paint": (0.38, 0.15),
    "glass": (0.08, 0.00),
    "trim": (0.82, 0.00),
    "lamp": (0.30, 0.00),
    "tail": (0.34, 0.00),
}
"""(roughness, metallic) per material slot, matching ``build_vehicle_materials``.

Quoted rather than imported because the applier builds its materials into the
``LD_VEH_MAT__`` family that a city scene owns; a plate reaching into that
family would be sharing datablocks with a scene that is not here. The colours
ARE imported, since those are what a reviewer is actually judging."""

NEUTRAL_PAINT = (0.042, 0.042, 0.044)
NEUTRAL_BACKDROP = (0.780, 0.780, 0.770)
STUDIO_BACKDROP = (0.160, 0.160, 0.158)

SENSOR_WIDTH = 36.0
"""Blender's default sensor. The lens is derived from it, never guessed."""

FRAME_MARGIN = math.radians(1.8)
"""Breathing room added to every fitted lens, so a lineup can never touch the
frame edge on a machine whose sensor fit resolves differently."""

WHEEL_POSE = (0.00, 0.62, 1.24, 1.86)
"""A fixed rotation per corner, in radians, about each wheel's own axle.

Nothing on a plate animates. Four wheels frozen at the same angle would leave
the hub witness at the same clock position on all four, which is precisely the
symmetry the witness exists to break; four fixed but different angles show that
the mark is real geometry attached to a wheel."""

STRIP_IRRADIANCE = 3.2
"""Watts per square metre delivered by the overhead strip.

The strip is sized to the lineup, so its POWER has to scale with its area or a
wider plate would be a dimmer one. Fixing the irradiance instead means all
three plates are exposed the same way."""


def _plate_name(name: str) -> str:
    """One plate datablock name, under the plate's own prefix."""
    return f"{PLATE_PREFIX}{name}"


# ---------------------------------------------------------------------------
# Scene, materials, backdrop, light
# ---------------------------------------------------------------------------


def _plate_scene() -> bpy.types.Collection:
    """An empty file: nothing survives from a previous plate.

    Three plates are built in one Blender process, and a lineup that inherited
    the previous lineup's lights, backdrop or paint would be a picture of two
    plates at once.
    """
    for block in (
        bpy.data.objects,
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.lights,
        bpy.data.cameras,
        bpy.data.worlds,
    ):
        for item in list(block):
            block.remove(item)
    return bpy.context.scene.collection


def _matte(name: str, color: tuple, roughness: float, metallic: float) -> bpy.types.Material:
    """One Principled surface, built the way the applier builds its own."""
    material = bpy.data.materials.new(f"{MATERIAL_PREFIX}{name}")
    material.use_nodes = True
    principled = material.node_tree.nodes["Principled BSDF"]
    principled.inputs["Base Color"].default_value = (*color, 1.0)
    principled.inputs["Roughness"].default_value = roughness
    principled.inputs["Metallic"].default_value = metallic
    return material


def _city_slots(archetype: str) -> list[bpy.types.Material]:
    """The five city material slots, in kit order: paint, glass, trim, lamp, tail."""
    paint = PLATE_PAINT[archetype]
    colors = {
        "paint": PAINT_COLORS[paint],
        "glass": GLASS_COLOR,
        "trim": TRIM_COLOR,
        "lamp": LAMP_COLOR,
        "tail": TAIL_COLOR,
    }
    return [
        _matte(f"{archetype}_{role}", colors[role], *CITY_SURFACE[role])
        for role in vehicle_kit.MATERIAL_SLOTS
    ]


def _cyclorama(name: str, collection: bpy.types.Collection, material: bpy.types.Material) -> None:
    """A horizon-less backdrop: floor, cove and wall in one swept sheet.

    A flat floor meeting a flat wall draws a hard line straight across the
    frame, and at a glance a reviewer reads that line as part of the car it
    passes behind. The cove is a quarter-round sweep instead, so the background
    carries a gradient and no edge at all.
    """
    front, back, fillet, height, half_width = 120.0, 44.0, 16.0, 34.0, 110.0
    profile: list[tuple[float, float]] = [(front, 0.0), (-back, 0.0)]
    steps = 12
    for step in range(1, steps + 1):
        angle = -math.pi / 2.0 - (math.pi / 2.0) * step / steps
        profile.append((-back + fillet * math.cos(angle), fillet + fillet * math.sin(angle)))
    profile.append((-back - fillet, height))

    builder = bmesh.new()
    rails = [[builder.verts.new((x, y, z)) for x, z in profile] for y in (-half_width, half_width)]
    for index in range(len(profile) - 1):
        builder.faces.new(
            (rails[0][index], rails[0][index + 1], rails[1][index + 1], rails[1][index])
        )
    bmesh.ops.recalc_face_normals(builder, faces=list(builder.faces))
    mesh = bpy.data.meshes.new(_plate_name(name))
    builder.to_mesh(mesh)
    builder.free()
    mesh.materials.append(material)
    obj = bpy.data.objects.new(_plate_name(name), mesh)
    link_only(obj, collection)


def _sun(
    name: str,
    collection: bpy.types.Collection,
    offset: tuple,
    target: tuple,
    energy: float,
    color: tuple,
    angle: float,
) -> None:
    """One directional key, fill or rim.

    Suns rather than area panels for the shaping lights: a lineup is up to
    twenty-six metres wide, and a panel close enough to be soft on the middle
    car falls off visibly by the end of the row. A reviewer would read that
    falloff as one archetype being darker than another.
    """
    light = bpy.data.lights.new(_plate_name(name), "SUN")
    light.energy = energy
    light.color = color
    light.angle = angle
    holder = bpy.data.objects.new(_plate_name(name), light)
    holder.location = (target[0] + offset[0], target[1] + offset[1], target[2] + offset[2])
    holder.rotation_euler = look_at_rotation(Vector(holder.location), Vector(target))
    holder.visible_camera = False
    link_only(holder, collection)


def _overhead_strip(
    collection: bpy.types.Collection, centre: tuple, span: float, height: float
) -> None:
    """The long softbox every car photograph is actually built on.

    A car's shoulder, roof and door surfaces are read almost entirely from the
    highlight that runs along them. Suns alone give a car two flat tones and a
    shadow, which is exactly how a well-shaped body ends up looking like a box.

    It is hidden from camera rays. On the near-level plates the panel sits
    inside the frame, and a photograph of a softbox is not a photograph of a
    car; hiding it from the lens costs the lighting nothing.
    """
    depth, length = 8.0, span + 18.0
    light = bpy.data.lights.new(_plate_name("strip"), "AREA")
    light.shape = "RECTANGLE"
    light.size = depth
    light.size_y = length
    light.energy = STRIP_IRRADIANCE * depth * length
    light.color = (1.0, 0.98, 0.95)
    holder = bpy.data.objects.new(_plate_name("strip"), light)
    holder.location = (centre[0], centre[1], height)
    holder.rotation_euler = (0.0, 0.0, 0.0)
    holder.visible_camera = False
    link_only(holder, collection)


def _world(color: tuple, strength: float) -> None:
    """The ambient the whole plate floats on."""
    world = bpy.data.worlds.new(_plate_name("world"))
    world.use_nodes = True
    background = world.node_tree.nodes["Background"]
    background.inputs[0].default_value = (*color, 1.0)
    background.inputs[1].default_value = strength
    bpy.context.scene.world = world


def _plate_camera(
    name: str, collection: bpy.types.Collection, location: tuple, target: tuple, lens: float
) -> None:
    """One camera: no depth of field, no motion blur, nothing to blur a flaw."""
    camera_data = bpy.data.cameras.new(name)
    camera_data.lens = lens
    camera_data.sensor_width = SENSOR_WIDTH
    camera_data.clip_end = 600.0
    camera_data.dof.use_dof = False
    camera = bpy.data.objects.new(name, camera_data)
    camera.location = location
    camera.rotation_euler = look_at_rotation(Vector(location), Vector(target))
    link_only(camera, collection)
    bpy.context.scene.camera = camera


# ---------------------------------------------------------------------------
# Where the cars stand, and which way they face
# ---------------------------------------------------------------------------


class _Lineup(NamedTuple):
    """Where a lineup's vehicles stand, and where the lens stands to see them."""

    stations: tuple[tuple[float, float], ...]
    yaws: tuple[float, ...]
    camera: tuple[float, float, float]
    target: tuple[float, float, float]
    lens: float
    span: float


def _yaw_for_bearing(station: tuple, camera: tuple, bearing: float) -> float:
    """The Z rotation that shows this vehicle the lens at a chosen bearing.

    Bearing is measured in the VEHICLE's frame, from its own bonnet: zero is
    head on, ninety is dead abeam on its left, minus ninety abeam on its right.
    Solving it per vehicle is the whole point of the helper -- give a whole row
    one shared yaw and the end cars turn away from the lens while the middle
    one faces it, so a reviewer comparing the ends is comparing camera angles
    rather than cars.
    """
    to_camera = math.atan2(camera[1] - station[1], camera[0] - station[0])
    return to_camera - math.radians(bearing)


def _lineup(
    names: Sequence[str],
    *,
    bearing: float,
    radius: float,
    elevation: float,
    target_z: float,
    gap: float,
) -> _Lineup:
    """Stand a lineup on an arc centred under the lens, then fit the lens to it.

    An arc rather than a straight line because on a line the end cars are
    further from the camera than the middle one: they render smaller, from a
    steeper angle, with more of the frame's perspective distortion on them. On
    an arc every archetype is the same distance away and, with the yaw solved
    per vehicle, at the same angle -- which is the only arrangement in which
    "the van looks bulkier than the sedan" is a statement about the van.

    The pitch is the widest CIRCUMSCRIBED vehicle plus a gap, so no two cars
    can overlap at any yaw, and the lens is then derived from the geometry
    rather than chosen: a plate cannot be mis-framed by editing a number here.
    """
    sizes = [vehicle_kit.vehicle_dimensions(name) for name in names]
    reach = max(math.hypot(size["length"], size["width"]) for size in sizes) / 2.0
    pitch = 2.0 * reach + gap
    step = pitch / radius
    stations = tuple(
        (
            radius - radius * math.cos((index - (len(names) - 1) / 2.0) * step),
            radius * math.sin((index - (len(names) - 1) / 2.0) * step),
        )
        for index in range(len(names))
    )
    camera = (radius, 0.0, target_z + radius * math.tan(elevation))
    half_angle = (len(names) - 1) * step / 2.0 + math.asin(min(reach / radius, 0.9)) + FRAME_MARGIN
    return _Lineup(
        stations=stations,
        yaws=tuple(_yaw_for_bearing(station, camera, bearing) for station in stations),
        camera=camera,
        target=(0.0, 0.0, target_z),
        lens=SENSOR_WIDTH / (2.0 * math.tan(half_angle)),
        span=(len(names) - 1) * pitch,
    )


# ---------------------------------------------------------------------------
# The cars themselves
# ---------------------------------------------------------------------------


def _weld(name: str, mesh_data: dict, materials: list) -> bpy.types.Mesh:
    """Turn one pure kit mesh into a Blender mesh, exactly as the applier does.

    Same bmesh, same per-face material index, same normal recalculation. A
    plate that welded differently could show a car the city will never build.
    """
    builder = bmesh.new()
    vertices = [builder.verts.new(vertex) for vertex in mesh_data["vertices"]]
    builder.verts.ensure_lookup_table()
    for corners, material_index in zip(mesh_data["faces"], mesh_data["materials"], strict=True):
        face = builder.faces.new([vertices[index] for index in corners])
        face.material_index = material_index
    bmesh.ops.recalc_face_normals(builder, faces=list(builder.faces))
    mesh = bpy.data.meshes.new(_plate_name(name))
    builder.to_mesh(mesh)
    builder.free()
    for material in materials:
        mesh.materials.append(material)
    return mesh


def _place_vehicle(
    label: str,
    archetype: str,
    slots: list,
    station: tuple,
    yaw: float,
    collection: bpy.types.Collection,
) -> int:
    """One vehicle body and its four wheels, built the way the city builds them.

    Wheels are children with their origins on their own axles, and only the
    BODY is bevelled -- both because that is what ``build_vehicle`` does, and a
    plate is worth nothing if the thing it photographs is not the thing that
    ships.
    """
    body_mesh = _weld(f"{label}__body", vehicle_kit.vehicle_mesh(archetype), slots)
    body = bpy.data.objects.new(_plate_name(f"{label}__body"), body_mesh)
    body.location = (station[0], station[1], 0.0)
    body.rotation_euler = (0.0, 0.0, yaw)
    add_bevel(body, width=VEHICLE_BEVEL)
    link_only(body, collection)

    wheel_mesh = _weld(f"{label}__wheel", vehicle_kit.wheel_mesh(archetype), slots)
    for index, (corner, offset) in enumerate(sorted(vehicle_kit.wheel_offsets(archetype).items())):
        wheel = bpy.data.objects.new(_plate_name(f"{label}__wheel_{corner}"), wheel_mesh)
        wheel.parent = body
        wheel.location = offset
        wheel.rotation_euler = (0.0, WHEEL_POSE[index % len(WHEEL_POSE)], 0.0)
        link_only(wheel, collection)
    return vehicle_kit.vehicle_triangles(archetype)


def _build_lineup(
    names: Sequence[str],
    layout: _Lineup,
    slots_for: Callable[[str], list],
    collection: bpy.types.Collection,
) -> int:
    """Place every vehicle in one lineup and report its triangle cost."""
    triangles = 0
    for index, name in enumerate(names):
        triangles += _place_vehicle(
            f"{index:02d}_{name}",
            name,
            slots_for(name),
            layout.stations[index],
            layout.yaws[index],
            collection,
        )
    return triangles


# ---------------------------------------------------------------------------
# The three plates
# ---------------------------------------------------------------------------


def build_style_plate() -> dict:
    """The lineup: all five archetypes, front three-quarter, in city paint.

    Fifteen degrees of elevation, because a car's identity lives in its plan as
    much as its profile -- the width of a van's shoulders, the setback of a
    coupe's cabin, the length of a bonnet -- and a level camera hides all
    three. It also buys back frame: five cars in one row is an eleven-to-one
    subject dropped into a sixteen-to-nine frame, and looking down turns some
    of each car's LENGTH into height on the sensor. Shot from each car's RIGHT,
    which is the flank the side plate does not show.
    """
    collection = _plate_scene()
    layout = _lineup(
        STYLE_ORDER,
        bearing=-50.0,
        radius=70.0,
        elevation=math.radians(15.0),
        target_z=1.15,
        gap=1.0,
    )
    _cyclorama("backdrop", collection, _matte("studio", STUDIO_BACKDROP, 0.78, 0.0))
    triangles = _build_lineup(STYLE_ORDER, layout, _city_slots, collection)

    _world((0.260, 0.272, 0.300), 1.0)
    _sun("key", collection, (26.0, -20.0, 30.0), layout.target, 3.2, (1.0, 0.96, 0.90), 0.08)
    _sun("fill", collection, (16.0, 26.0, 14.0), layout.target, 1.0, (0.86, 0.91, 1.0), 0.45)
    _sun("rim", collection, (-24.0, 10.0, 16.0), layout.target, 0.8, (0.94, 0.96, 1.0), 0.30)
    _overhead_strip(collection, (0.9, 0.0), layout.span, 13.0)
    _plate_camera("CAM_P19_VEHICLE_STYLE", collection, layout.camera, layout.target, layout.lens)

    view = bpy.context.scene.view_settings
    view.view_transform = "AgX"
    view.look = "AgX - Base Contrast"
    view.exposure = 0.35
    return {"vehicles": len(STYLE_ORDER), "triangles": triangles, "lens": round(layout.lens, 1)}


def build_side_plate() -> dict:
    """The detail row: sedan, SUV and coupe, near profile, close and level.

    Sixteen degrees off pure profile so a sliver of the nose reads and the
    picture is a car rather than an elevation drawing, and a camera barely
    above the beltline so the wheel arches are seen into rather than down on.
    Shot from each car's LEFT: this is the flank that carries the hub, the
    witness and the mirror the kit emits at positive Y.
    """
    collection = _plate_scene()
    layout = _lineup(
        SIDE_ORDER, bearing=74.0, radius=30.0, elevation=math.radians(2.5), target_z=0.95, gap=0.7
    )
    _cyclorama("backdrop", collection, _matte("studio", STUDIO_BACKDROP, 0.78, 0.0))
    triangles = _build_lineup(SIDE_ORDER, layout, _city_slots, collection)

    _world((0.245, 0.256, 0.284), 1.0)
    _sun("key", collection, (18.0, -14.0, 20.0), layout.target, 3.0, (1.0, 0.96, 0.90), 0.07)
    _sun("fill", collection, (12.0, 18.0, 9.0), layout.target, 1.1, (0.86, 0.91, 1.0), 0.45)
    _sun("rim", collection, (-16.0, 7.0, 11.0), layout.target, 0.9, (0.94, 0.96, 1.0), 0.30)
    _overhead_strip(collection, (0.6, 0.0), layout.span, 8.0)
    _plate_camera("CAM_P19_VEHICLE_SIDE", collection, layout.camera, layout.target, layout.lens)

    view = bpy.context.scene.view_settings
    view.view_transform = "AgX"
    view.look = "AgX - Base Contrast"
    view.exposure = 0.45
    return {"vehicles": len(SIDE_ORDER), "triangles": triangles, "lens": round(layout.lens, 1)}


def build_silhouette_plate() -> dict:
    """The shape test: all five in ONE flat material, dead abeam, on a bright field.

    Every slot -- paint, glass, trim, lamp, tail -- gets the SAME matte
    material, so nothing can be told apart by colour and the archetypes have to
    survive on geometry alone. The backdrop is bright and the cars are dark, so
    the outline is unambiguous; the key is kept on rather than cut, so the
    flank still carries enough shading to answer whether a shoulder, an arch
    and a roofline were modelled at all, and not only whether the outline
    differs.
    """
    collection = _plate_scene()
    layout = _lineup(
        STYLE_ORDER, bearing=90.0, radius=62.0, elevation=math.radians(2.5), target_z=0.95, gap=0.9
    )
    _cyclorama("backdrop", collection, _matte("field", NEUTRAL_BACKDROP, 0.85, 0.0))
    neutral = _matte("neutral", NEUTRAL_PAINT, 0.68, 0.0)
    triangles = _build_lineup(STYLE_ORDER, layout, lambda _name: [neutral] * 5, collection)

    _world((0.550, 0.552, 0.560), 1.6)
    _sun("key", collection, (22.0, -16.0, 24.0), layout.target, 2.2, (1.0, 0.98, 0.95), 0.10)
    _sun("fill", collection, (14.0, 20.0, 10.0), layout.target, 0.8, (0.95, 0.97, 1.0), 0.50)
    _overhead_strip(collection, (0.8, 0.0), layout.span, 11.0)
    _plate_camera(
        "CAM_P19_VEHICLE_SILHOUETTE", collection, layout.camera, layout.target, layout.lens
    )

    view = bpy.context.scene.view_settings
    view.view_transform = "AgX"
    view.look = "AgX - Base Contrast"
    view.exposure = -0.15
    return {"vehicles": len(STYLE_ORDER), "triangles": triangles, "lens": round(layout.lens, 1)}


def build_exotic_view(bearing: float, elevation: float, *, silhouette: bool) -> dict:
    """One coupe, alone, at a camera recovered from the Codex run log.

    Only the bearing and the elevation are recovered facts, so only they vary
    here. Everything else -- the arc radius, the target height, the backdrop,
    the lights and the exposure -- is inherited from the side plate, whose rig
    is the close single-row look the lost script derived from, or from the
    silhouette plate when the view is the silhouette treatment. The lens is
    still fitted to the car by :func:`_lineup`, so a recovered camera cannot be
    mis-framed by a number chosen in this function.
    """
    collection = _plate_scene()
    layout = _lineup(
        (EXOTIC_ARCHETYPE,),
        bearing=bearing,
        radius=30.0,
        elevation=math.radians(elevation),
        target_z=0.95,
        gap=0.7,
    )
    if silhouette:
        _cyclorama("backdrop", collection, _matte("field", NEUTRAL_BACKDROP, 0.85, 0.0))
        neutral = _matte("neutral", NEUTRAL_PAINT, 0.68, 0.0)
        triangles = _build_lineup(
            (EXOTIC_ARCHETYPE,), layout, lambda _name: [neutral] * 5, collection
        )
        _world((0.550, 0.552, 0.560), 1.6)
        _sun("key", collection, (22.0, -16.0, 24.0), layout.target, 2.2, (1.0, 0.98, 0.95), 0.10)
        _sun("fill", collection, (14.0, 20.0, 10.0), layout.target, 0.8, (0.95, 0.97, 1.0), 0.50)
        _overhead_strip(collection, (0.8, 0.0), layout.span, 11.0)
        exposure = -0.15
    else:
        _cyclorama("backdrop", collection, _matte("studio", STUDIO_BACKDROP, 0.78, 0.0))
        triangles = _build_lineup((EXOTIC_ARCHETYPE,), layout, _city_slots, collection)
        _world((0.245, 0.256, 0.284), 1.0)
        _sun("key", collection, (18.0, -14.0, 20.0), layout.target, 3.0, (1.0, 0.96, 0.90), 0.07)
        _sun("fill", collection, (12.0, 18.0, 9.0), layout.target, 1.1, (0.86, 0.91, 1.0), 0.45)
        _sun("rim", collection, (-16.0, 7.0, 11.0), layout.target, 0.9, (0.94, 0.96, 1.0), 0.30)
        _overhead_strip(collection, (0.6, 0.0), layout.span, 8.0)
        exposure = 0.45
    _plate_camera("CAM_P19_EXOTIC_QA", collection, layout.camera, layout.target, layout.lens)

    view = bpy.context.scene.view_settings
    view.view_transform = "AgX"
    view.look = "AgX - Base Contrast"
    view.exposure = exposure
    return {"triangles": triangles}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_plate(camera: str, path: Path, *, preview: bool) -> None:
    """Render one plate at the plate resolution and sample count.

    Cheaper than a proof frame on purpose. A style plate is a shape and
    material judgement over a handful of objects on a plain backdrop, and
    nothing in that judgement changes between two hundred and a thousand
    samples -- whereas the review loop it belongs to changes completely.
    """
    require_supported_blender()
    configure_cycles_device()
    scene = bpy.context.scene
    cycles = scene.cycles
    cycles.use_adaptive_sampling = True
    cycles.samples = 48 if preview else 256
    cycles.adaptive_threshold = 0.06 if preview else 0.012
    cycles.use_denoising = True
    cycles.denoiser = "OPENIMAGEDENOISE"
    cycles.denoising_input_passes = "RGB_ALBEDO_NORMAL"
    cycles.max_bounces = 6
    scene.camera = bpy.data.objects[camera]
    scene.render.resolution_x = 1280 if preview else 2560
    scene.render.resolution_y = 720 if preview else 1440
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_depth = "8"
    scene.render.filepath = str(path.resolve())
    bpy.ops.render.render(write_still=True)


def main() -> int:
    """Blender entry point: build the three vehicle plates and render them."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", required=True, help="directory the three plates are written to")
    parser.add_argument("--preview", action="store_true", help="48 samples at 1280x720")
    parser.add_argument(
        "--exotic-qa",
        action="store_true",
        help="render the four recovered Codex-era coupe QA views instead of the three plates",
    )
    arguments = parser.parse_args(argv)
    outdir = Path(arguments.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if arguments.exotic_qa:
        for filename, bearing, elevation, silhouette in EXOTIC_QA_VIEWS:
            metrics = build_exotic_view(bearing, elevation, silhouette=silhouette)
            render_plate("CAM_P19_EXOTIC_QA", outdir / filename, preview=arguments.preview)
            print(
                f"LD_P19_EXOTIC_QA: {filename} "
                f"bearing={bearing} elevation={elevation} "
                f"triangles={metrics['triangles']}"
            )
        return 0

    plates = (
        (STYLE_PLATE, "CAM_P19_VEHICLE_STYLE", build_style_plate, STYLE_ORDER),
        (SIDE_PLATE, "CAM_P19_VEHICLE_SIDE", build_side_plate, SIDE_ORDER),
        (SILHOUETTE_PLATE, "CAM_P19_VEHICLE_SILHOUETTE", build_silhouette_plate, STYLE_ORDER),
    )
    for filename, camera, build, order in plates:
        metrics = build()
        render_plate(camera, outdir / filename, preview=arguments.preview)
        print(
            f"LD_P19_VEHICLE_PLATE: {filename} "
            f"order={','.join(order)} "
            f"vehicles={metrics['vehicles']} "
            f"triangles={metrics['triangles']} "
            f"lens={metrics['lens']}mm"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
