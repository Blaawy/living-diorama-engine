"""Render the Phase 18 human-style plate: the whole figure vocabulary, side by side.

A STYLE PLATE, not a view of the city. It builds one figure per visual
archetype on a plain ground in an empty scene, so the question the Director
asked -- are these actually different people? -- can be answered by looking
rather than by reading object names. Nothing here is part of the world: no
plate figure exists in any city build, none is derived from population, and
the plate is never packaged as evidence of what the city contains.

The lineup is deliberately exhaustive where the city can only be
representative. A natural grouping shows whoever happens to be standing
there; this shows a child beside an elder beside a broad adult beside a slim
one, which is the comparison the correction directive asks a reviewer to make.

Run headless::

    blender --background --factory-startup --python \
        produce_population_style_plate.py -- --presence population_presence_v1.json \
        --output plate.png [--preview]
"""

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply_population_presence as population  # noqa: E402
import figure_kit  # noqa: E402
from blender_runtime import (  # noqa: E402
    link_only,
    look_at_rotation,
    make_box,
    remove_factory_defaults,
)
from population_presence_spec import load_population_presence_spec  # noqa: E402
from render_visual_proof import render_frame  # noqa: E402

PLATE_SPACING = 1.02
"""Metres between figures. Close enough to compare, far enough not to touch."""

LINEUP = (
    (
        "child",
        "unspecified",
        "short",
        "average",
        "short",
        "none",
        "a",
        "short_sleeve",
        "sand",
        "c2",
        "h1",
        "idle",
    ),
    (
        "child",
        "feminine",
        "average",
        "slim",
        "long",
        "none",
        "c",
        "dress",
        "teal",
        "c4",
        "h2",
        "observe",
    ),
    (
        "teen",
        "masculine",
        "tall",
        "slim",
        "medium",
        "none",
        "b",
        "shirt",
        "moss",
        "c1",
        "h3",
        "stroll",
    ),
    (
        "adult",
        "feminine",
        "short",
        "average",
        "tied",
        "none",
        "d",
        "dress",
        "rust",
        "c3",
        "h2",
        "idle",
    ),
    (
        "adult",
        "masculine",
        "average",
        "athletic",
        "short",
        "beard",
        "b",
        "jacket",
        "slate",
        "c5",
        "h1",
        "rest",
    ),
    (
        "adult",
        "feminine",
        "tall",
        "slim",
        "long",
        "none",
        "a",
        "formal",
        "indigo",
        "c2",
        "h4",
        "idle",
    ),
    (
        "adult",
        "masculine",
        "tall",
        "broad",
        "bald",
        "moustache",
        "c",
        "shirt",
        "clay",
        "c4",
        "h1",
        "observe",
    ),
    (
        "adult",
        "unspecified",
        "average",
        "average",
        "cap",
        "none",
        "d",
        "short_sleeve",
        "ochre",
        "c1",
        "h3",
        "stroll",
    ),
    (
        "elder",
        "feminine",
        "short",
        "average",
        "tied",
        "none",
        "a",
        "coat",
        "slate",
        "c3",
        "h5",
        "idle",
    ),
    (
        "elder",
        "masculine",
        "average",
        "broad",
        "bald",
        "beard",
        "b",
        "coat",
        "sand",
        "c5",
        "h4",
        "rest",
    ),
)
"""One figure per archetype the directive named, in a readable order.

Two children (so a child can be compared with a child), a teen, five adults
spanning slim to broad and short to tall, and two elders. Every hair variant,
every clothing silhouette, both facial-hair options, all four faces, all four
poses and all five complexions appear at least once.
"""

AXES = (
    "age_presentation",
    "presentation",
    "stature",
    "build",
    "hair",
    "facial_hair",
    "face",
    "clothing",
    "palette",
    "complexion",
    "hair_tone",
    "pose",
)


def lineup_identities() -> list[dict]:
    """The plate's figures, as visual identities."""
    return [dict(zip(AXES, entry, strict=True)) for entry in LINEUP]


def build_plate(presence_spec: dict) -> dict:
    """Build the lineup on a plain ground in an empty scene."""
    remove_factory_defaults()
    for block in (bpy.data.objects, bpy.data.meshes, bpy.data.materials):
        for item in list(block):
            block.remove(item)
    collection = bpy.context.scene.collection
    materials = population.build_population_materials()
    ground = population._flat_material("LD_POP_MAT__plate_ground", (0.212, 0.204, 0.192))
    identities = lineup_identities()
    span = PLATE_SPACING * (len(identities) - 1)
    make_box(
        "LD_POP_PLATE__ground",
        (span + 4.0, 5.0, 0.2),
        (0.0, 0.0, -0.2),
        collection,
        ground,
        bevel=0.0,
    )
    tallest = 0.0
    for index, identity in enumerate(identities):
        offset = -span / 2.0 + index * PLATE_SPACING
        obj = population.build_figure_object(
            f"LD_POP_PLATE__{index:02d}_{identity['age_presentation']}",
            figure_kit.figure_mesh(identity),
            (0.0, offset, 0.0),
            collection,
            [
                materials[identity["palette"]],
                materials[f"skin_{identity['complexion']}"],
                materials[f"hair_{identity['hair_tone']}"],
                materials["accent"],
            ],
            rotation_z=0.0,
            bevel=population.PROXY_BEVEL,
        )
        link_only(obj, collection)
        tallest = max(tallest, figure_kit.figure_dimensions(identity)["height"])

    world = bpy.data.worlds.new("LD_POP_PLATE__world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.055, 0.056, 0.060, 1.0)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.85
    bpy.context.scene.world = world

    key = bpy.data.lights.new("LD_POP_PLATE__key", "AREA")
    key.energy = 2400.0
    key.size = 8.0
    key.color = (1.0, 0.94, 0.86)
    key_object = bpy.data.objects.new("LD_POP_PLATE__key", key)
    key_object.location = (7.0, -3.0, 6.5)
    key_object.rotation_euler = look_at_rotation(
        Vector(key_object.location), Vector((0.0, 0.0, 1.0))
    )
    collection.objects.link(key_object)

    fill = bpy.data.lights.new("LD_POP_PLATE__fill", "AREA")
    fill.energy = 700.0
    fill.size = 10.0
    fill.color = (0.80, 0.86, 1.0)
    fill_object = bpy.data.objects.new("LD_POP_PLATE__fill", fill)
    fill_object.location = (6.0, 7.0, 4.0)
    fill_object.rotation_euler = look_at_rotation(
        Vector(fill_object.location), Vector((0.0, 0.0, 1.0))
    )
    collection.objects.link(fill_object)

    camera_data = bpy.data.cameras.new("CAM_P18_STYLE_PLATE")
    camera_data.lens = 42.0
    camera_data.clip_end = 200.0
    camera = bpy.data.objects.new("CAM_P18_STYLE_PLATE", camera_data)
    camera.location = (13.0, 0.0, 1.30)
    camera.rotation_euler = look_at_rotation(Vector(camera.location), Vector((0.0, 0.0, 0.95)))
    collection.objects.link(camera)
    bpy.context.scene.camera = camera

    view = bpy.context.scene.view_settings
    view.view_transform = "AgX"
    view.look = "AgX - Medium High Contrast"
    view.exposure = 0.4
    return {
        "figures": len(identities),
        "tallest": round(tallest, 4),
        "shortest": round(
            min(figure_kit.figure_dimensions(entry)["height"] for entry in identities), 4
        ),
    }


FACE_LINEUP = (
    (
        "child",
        "unspecified",
        "average",
        "average",
        "short",
        "none",
        "a",
        "shirt",
        "sand",
        "c2",
        "h1",
        "idle",
    ),
    (
        "teen",
        "feminine",
        "average",
        "slim",
        "long",
        "none",
        "c",
        "shirt",
        "teal",
        "c4",
        "h2",
        "idle",
    ),
    (
        "adult",
        "masculine",
        "average",
        "athletic",
        "bald",
        "beard",
        "b",
        "shirt",
        "slate",
        "c5",
        "h1",
        "idle",
    ),
    (
        "adult",
        "feminine",
        "average",
        "average",
        "tied",
        "none",
        "d",
        "shirt",
        "rust",
        "c3",
        "h2",
        "idle",
    ),
    (
        "adult",
        "masculine",
        "average",
        "average",
        "cap",
        "moustache",
        "c",
        "shirt",
        "moss",
        "c1",
        "h3",
        "idle",
    ),
    (
        "adult",
        "unspecified",
        "average",
        "average",
        "medium",
        "none",
        "a",
        "shirt",
        "ochre",
        "c4",
        "h3",
        "idle",
    ),
    (
        "elder",
        "feminine",
        "average",
        "average",
        "short",
        "none",
        "b",
        "shirt",
        "indigo",
        "c2",
        "h5",
        "idle",
    ),
    (
        "elder",
        "masculine",
        "average",
        "broad",
        "bald",
        "moustache",
        "d",
        "shirt",
        "clay",
        "c5",
        "h4",
        "idle",
    ),
)
"""The QA row: one head per case the face contract has to hold for.

Every age band, both presentations plus unspecified, every hair variant that
touches the face, both facial-hair options and all four face variants. Poses
are held at ``idle`` on purpose -- this plate answers whether a face is built
correctly, so nothing about it should be turned away from the camera.
"""

FACE_PLATE_EYE_LEVEL = 1.52
"""Height every head is raised to.

The figures stand on individual risers so that a child's face and an elder's
face arrive at the lens at the same height and the same size. That is a QA
convention, not a claim about the world: in the city they stand on the ground
and a child is plainly shorter, which the style plate and the group frame both
show.
"""

FACE_PLATE_SPACING = 0.62


def build_face_plate(presence_spec: dict) -> dict:
    """Build the face QA row: heads aligned, lit flat, nothing hidden."""
    remove_factory_defaults()
    for block in (bpy.data.objects, bpy.data.meshes, bpy.data.materials):
        for item in list(block):
            block.remove(item)
    collection = bpy.context.scene.collection
    materials = population.build_population_materials()
    riser_material = population._flat_material("LD_POP_MAT__plate_ground", (0.206, 0.200, 0.192))
    identities = [dict(zip(AXES, entry, strict=True)) for entry in FACE_LINEUP]
    span = FACE_PLATE_SPACING * (len(identities) - 1)
    for index, identity in enumerate(identities):
        offset = -span / 2.0 + index * FACE_PLATE_SPACING
        size = figure_kit.figure_dimensions(identity)
        eye_z = size["neck_top"] + size["head_height"] * figure_kit.FACE_LEVELS["eye"]
        riser = FACE_PLATE_EYE_LEVEL - eye_z
        make_box(
            f"LD_POP_FACE__riser_{index:02d}",
            (0.5, FACE_PLATE_SPACING * 0.92, max(riser, 0.02)),
            (0.0, offset, 0.0),
            collection,
            riser_material,
            bevel=0.0,
        )
        obj = population.build_figure_object(
            f"LD_POP_FACE__{index:02d}_{identity['age_presentation']}",
            figure_kit.figure_mesh(identity),
            (0.0, offset, max(riser, 0.02)),
            collection,
            [
                materials[identity["palette"]],
                materials[f"skin_{identity['complexion']}"],
                materials[f"hair_{identity['hair_tone']}"],
                materials["accent"],
            ],
            rotation_z=0.0,
            bevel=population.PROXY_BEVEL,
        )
        link_only(obj, collection)

    world = bpy.data.worlds.new("LD_POP_FACE__world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.28, 0.29, 0.31, 1.0)
    world.node_tree.nodes["Background"].inputs[1].default_value = 1.6
    bpy.context.scene.world = world

    for name, location, energy, color in (
        ("key", (5.0, -1.6, 2.6), 900.0, (1.0, 0.97, 0.93)),
        ("fill", (4.4, 2.4, 2.0), 520.0, (0.92, 0.95, 1.0)),
    ):
        light = bpy.data.lights.new(f"LD_POP_FACE__{name}", "AREA")
        light.energy = energy
        light.size = 5.0
        light.color = color
        holder = bpy.data.objects.new(f"LD_POP_FACE__{name}", light)
        holder.location = location
        holder.rotation_euler = look_at_rotation(
            Vector(location), Vector((0.0, 0.0, FACE_PLATE_EYE_LEVEL))
        )
        collection.objects.link(holder)

    camera_data = bpy.data.cameras.new("CAM_P18_FACE_PLATE")
    camera_data.lens = 58.0
    camera_data.clip_end = 200.0
    camera_data.dof.use_dof = False
    camera = bpy.data.objects.new("CAM_P18_FACE_PLATE", camera_data)
    camera.location = (8.4, -1.30, FACE_PLATE_EYE_LEVEL + 0.12)
    camera.rotation_euler = look_at_rotation(
        Vector(camera.location), Vector((0.0, 0.0, FACE_PLATE_EYE_LEVEL - 0.015))
    )
    collection.objects.link(camera)
    bpy.context.scene.camera = camera

    view = bpy.context.scene.view_settings
    view.view_transform = "AgX"
    view.look = "AgX - Base Contrast"
    view.exposure = 1.05
    return {"faces": len(identities), "eye_level": FACE_PLATE_EYE_LEVEL}


BODY_LINEUP = (
    (
        "child",
        "unspecified",
        "short",
        "average",
        "short",
        "none",
        "a",
        "shirt",
        "sand",
        "c2",
        "h1",
        "idle",
    ),
    (
        "child",
        "feminine",
        "average",
        "slim",
        "long",
        "none",
        "c",
        "dress",
        "teal",
        "c4",
        "h2",
        "stroll",
    ),
    (
        "teen",
        "masculine",
        "tall",
        "slim",
        "medium",
        "none",
        "b",
        "short_sleeve",
        "moss",
        "c1",
        "h3",
        "observe",
    ),
    (
        "adult",
        "feminine",
        "short",
        "average",
        "tied",
        "none",
        "d",
        "shirt",
        "rust",
        "c3",
        "h2",
        "idle",
    ),
    (
        "adult",
        "masculine",
        "average",
        "athletic",
        "short",
        "beard",
        "b",
        "short_sleeve",
        "slate",
        "c5",
        "h1",
        "stroll",
    ),
    (
        "adult",
        "unspecified",
        "tall",
        "slim",
        "bald",
        "none",
        "a",
        "shirt",
        "indigo",
        "c2",
        "h4",
        "rest",
    ),
    (
        "adult",
        "masculine",
        "tall",
        "broad",
        "cap",
        "moustache",
        "c",
        "jacket",
        "clay",
        "c4",
        "h1",
        "idle",
    ),
    (
        "adult",
        "feminine",
        "average",
        "average",
        "long",
        "none",
        "d",
        "dress",
        "ochre",
        "c1",
        "h3",
        "observe",
    ),
    (
        "elder",
        "feminine",
        "short",
        "slim",
        "tied",
        "none",
        "a",
        "coat",
        "slate",
        "c3",
        "h5",
        "rest",
    ),
    (
        "elder",
        "masculine",
        "average",
        "broad",
        "bald",
        "beard",
        "b",
        "coat",
        "sand",
        "c5",
        "h4",
        "stroll",
    ),
)
"""The body QA row: one figure per anatomy question the correction asked.

Every age band, the extremes of stature and build, both presentations plus
unspecified, and all four poses -- chosen so that a reviewer comparing
neighbours can answer "is that a child or a short adult", "is that one
actually broader or just bigger", and "do these two stand differently"
without reading a single object name.
"""

BODY_PLATE_SPACING = 0.95


def _plate_scene() -> bpy.types.Collection:
    """An empty scene with nothing left over from a previous plate."""
    remove_factory_defaults()
    for block in (bpy.data.objects, bpy.data.meshes, bpy.data.materials):
        for item in list(block):
            block.remove(item)
    return bpy.context.scene.collection


def _plate_lighting(collection: bpy.types.Collection, target: float, lights: tuple) -> None:
    """Flat, even light. Nothing here may hide a defect in a shadow."""
    for name, location, energy, color, size in lights:
        light = bpy.data.lights.new(f"LD_POP_BODY__{name}", "AREA")
        light.energy = energy
        light.size = size
        light.color = color
        holder = bpy.data.objects.new(f"LD_POP_BODY__{name}", light)
        holder.location = location
        holder.rotation_euler = look_at_rotation(Vector(location), Vector((0.0, 0.0, target)))
        collection.objects.link(holder)


def _plate_camera(
    name: str, collection: bpy.types.Collection, location: tuple, target: tuple, lens: float
) -> None:
    """One camera, no depth of field, no motion blur, nothing to blur a flaw."""
    camera_data = bpy.data.cameras.new(name)
    camera_data.lens = lens
    camera_data.clip_end = 200.0
    camera_data.dof.use_dof = False
    camera = bpy.data.objects.new(name, camera_data)
    camera.location = location
    camera.rotation_euler = look_at_rotation(Vector(location), Vector(target))
    collection.objects.link(camera)
    bpy.context.scene.camera = camera


def build_body_plate(presence_spec: dict) -> dict:
    """Build the body-geometry QA row: whole figures, flat light, feet visible.

    The plate the Director's body checklist is answered against. The camera is
    square on and low enough to see an ankle, so a cube skull, a peg neck, a
    slab torso, a stick arm, a column leg or a missing foot would all be
    visible rather than inferred.
    """
    collection = _plate_scene()
    materials = population.build_population_materials()
    ground = population._flat_material("LD_POP_MAT__body_ground", (0.238, 0.232, 0.222))
    identities = [dict(zip(AXES, entry, strict=True)) for entry in BODY_LINEUP]
    span = BODY_PLATE_SPACING * (len(identities) - 1)
    make_box(
        "LD_POP_BODY__ground",
        (16.0, span + 4.0, 0.2),
        (5.0, 0.0, -0.2),
        collection,
        ground,
        bevel=0.0,
    )
    triangles = 0
    for index, identity in enumerate(identities):
        offset = -span / 2.0 + index * BODY_PLATE_SPACING
        obj = population.build_figure_object(
            f"LD_POP_BODY__{index:02d}_{identity['age_presentation']}",
            figure_kit.figure_mesh(identity),
            (0.0, offset, 0.0),
            collection,
            [
                materials[identity["palette"]],
                materials[f"skin_{identity['complexion']}"],
                materials[f"hair_{identity['hair_tone']}"],
                materials["accent"],
            ],
            rotation_z=0.0,
            bevel=population.PROXY_BEVEL,
        )
        link_only(obj, collection)
        triangles += figure_kit.figure_triangles(identity)

    world = bpy.data.worlds.new("LD_POP_BODY__world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.20, 0.21, 0.23, 1.0)
    world.node_tree.nodes["Background"].inputs[1].default_value = 1.1
    bpy.context.scene.world = world
    _plate_lighting(
        collection,
        1.0,
        (
            ("key", (9.0, -3.0, 4.6), 1500.0, (1.0, 0.97, 0.93), 9.0),
            ("fill", (7.0, 5.0, 3.0), 620.0, (0.92, 0.95, 1.0), 11.0),
        ),
    )
    _plate_camera("CAM_P18_BODY_PLATE", collection, (11.4, -0.9, 1.00), (0.0, 0.0, 0.94), 44.0)
    view = bpy.context.scene.view_settings
    view.view_transform = "AgX"
    view.look = "AgX - Base Contrast"
    view.exposure = 0.10
    return {"figures": len(identities), "triangles": triangles}


def build_silhouette_plate(presence_spec: dict) -> dict:
    """Build the silhouette QA row: one neutral material, contrasting ground.

    THE test the correction directive set, and the one the previous candidate
    would have failed. Strip the palette, the complexion, the hair tone and the
    accent -- give every figure the same flat dark surface against a bright
    field -- and the only thing left to judge is the shape.

    If a viewer cannot tell these are people from the outline alone, no amount
    of colour would have saved them.
    """
    collection = _plate_scene()
    neutral = population._flat_material("LD_POP_MAT__silhouette", (0.016, 0.016, 0.018))
    backdrop = population._flat_material("LD_POP_MAT__silhouette_ground", (0.84, 0.84, 0.82))
    identities = [dict(zip(AXES, entry, strict=True)) for entry in BODY_LINEUP]
    span = BODY_PLATE_SPACING * (len(identities) - 1)
    make_box(
        "LD_POP_SIL__ground",
        (16.0, span + 6.0, 0.2),
        (5.0, 0.0, -0.2),
        collection,
        backdrop,
        bevel=0.0,
    )
    make_box(
        "LD_POP_SIL__backdrop",
        (0.3, span + 8.0, 8.0),
        (-2.6, 0.0, 0.0),
        collection,
        backdrop,
        bevel=0.0,
    )
    for index, identity in enumerate(identities):
        offset = -span / 2.0 + index * BODY_PLATE_SPACING
        obj = population.build_figure_object(
            f"LD_POP_SIL__{index:02d}_{identity['age_presentation']}",
            figure_kit.figure_mesh(identity),
            (0.0, offset, 0.0),
            collection,
            [neutral, neutral, neutral, neutral],
            rotation_z=0.0,
            bevel=population.PROXY_BEVEL,
        )
        link_only(obj, collection)

    world = bpy.data.worlds.new("LD_POP_SIL__world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.90, 0.90, 0.88, 1.0)
    world.node_tree.nodes["Background"].inputs[1].default_value = 2.6
    bpy.context.scene.world = world
    _plate_camera("CAM_P18_SILHOUETTE", collection, (11.4, 0.0, 1.00), (0.0, 0.0, 0.94), 44.0)
    view = bpy.context.scene.view_settings
    view.view_transform = "AgX"
    view.look = "AgX - Base Contrast"
    view.exposure = 0.55
    return {"figures": len(identities)}


def main() -> int:
    """Blender entry point: build the plate and render it."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--presence", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--face-output", default="")
    parser.add_argument("--body-output", default="")
    parser.add_argument("--silhouette-output", default="")
    parser.add_argument("--preview", action="store_true")
    arguments = parser.parse_args(argv)
    presence_spec = load_population_presence_spec(arguments.presence)
    metrics = build_plate(presence_spec)
    render_frame("CAM_P18_STYLE_PLATE", arguments.output, preview=arguments.preview)
    print(f"LD_P18_PLATE_FIGURES: {metrics['figures']}")
    print(f"LD_P18_PLATE_RANGE: {metrics['shortest']} to {metrics['tallest']}")
    if arguments.face_output.strip():
        face = build_face_plate(presence_spec)
        render_frame("CAM_P18_FACE_PLATE", arguments.face_output, preview=arguments.preview)
        print(f"LD_P18_FACE_PLATE_FACES: {face['faces']}")
    if arguments.body_output.strip():
        body = build_body_plate(presence_spec)
        render_frame("CAM_P18_BODY_PLATE", arguments.body_output, preview=arguments.preview)
        print(f"LD_P18_BODY_PLATE_FIGURES: {body['figures']}")
        print(f"LD_P18_BODY_PLATE_TRIANGLES: {body['triangles']}")
    if arguments.silhouette_output.strip():
        shape = build_silhouette_plate(presence_spec)
        render_frame("CAM_P18_SILHOUETTE", arguments.silhouette_output, preview=arguments.preview)
        print(f"LD_P18_SILHOUETTE_FIGURES: {shape['figures']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
