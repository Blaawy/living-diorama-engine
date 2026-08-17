"""Instantiate the Phase 18 population layer inside Blender.

The builder INSTANTIATES; it does not decide. Every position, heading, body
variant and pose is read from the pure Population Presence Plan, which was
derived from authoritative district population and proven against the Phase
16 occupancy contract before Blender was ever opened. Nothing here consults
population, geometry, or the city; a bug in this file can make the world look
wrong, but it cannot make the world's claim about its people untrue.

The layer is deliberately isolated:

* one collection, ``LD_POPULATION``, under the existing ``LD_WORLD`` root;
* one object per proxy, named ``LD_POP__<district>__slot_<NNN>``;
* materials under their own ``LD_POP_MAT__`` prefix, so nothing Phase 15 or
  Phase 16 counts as its ``LD_MAT__`` family ever changes;
* a full clear of both objects and meshes before every build, so rebuilding
  the same plan converges on the same scene instead of growing ``.001``
  copies.

The bodies are semi-stylised on purpose. A proxy is a readable human
silhouette -- feet, tapered legs with knees, a lofted torso that narrows at
the waist, segmented arms with elbows, a neck and a faceted skull carrying a
face -- welded into one mesh. There is no rig, no animation and no crowd
system.

Every vertex of that body comes from the pure figure kit. This file owns the
weld and nothing else: it turns ``figure_mesh`` into a ``bmesh``, assigns the
per-face material slot the kit already chose, and links the object. It cannot
make a body a different shape, which is the point of keeping the geometry
pure.
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

import figure_kit  # noqa: E402
from blender_runtime import (  # noqa: E402
    add_bevel,
    link_only,
    replace_object,
)
from population_presence_plan import (  # noqa: E402
    plan_hash,
)

POPULATION_ROOT = "LD_POPULATION"
"""The one collection the Phase 18 layer is allowed to touch."""

PROXY_PREFIX = "LD_POP__"
MESH_PREFIX = "LD_POP_MESH__"
MATERIAL_PREFIX = "LD_POP_MAT__"

PALETTE_COLORS = {
    "slate": (0.126, 0.140, 0.166),
    "sand": (0.335, 0.283, 0.208),
    "moss": (0.135, 0.176, 0.122),
    "rust": (0.268, 0.126, 0.088),
    "indigo": (0.104, 0.122, 0.213),
    "clay": (0.232, 0.150, 0.118),
    "teal": (0.088, 0.170, 0.168),
    "ochre": (0.310, 0.226, 0.104),
}
"""Muted clothing families, chosen to sit inside the city's material range.

Deliberately desaturated and dark: at civil twilight a crowd of saturated
colours would read as scattered confetti against a charcoal and bone city,
and presence should read as people.
"""

COMPLEXION_COLORS = {
    "c1": (0.451, 0.318, 0.243),
    "c2": (0.372, 0.251, 0.184),
    "c3": (0.286, 0.181, 0.126),
    "c4": (0.196, 0.118, 0.081),
    "c5": (0.128, 0.076, 0.052),
}
"""Five complexions, named by index rather than by any word for a people.

A city contains people who do not all look alike, and a diorama that showed
one complexion would be making a claim about its world that its world does
not contain. Presentation only: nothing reads these back, and the simulation
holds nothing they could correspond to."""

HAIR_COLORS = {
    "h1": (0.052, 0.040, 0.034),
    "h2": (0.116, 0.074, 0.044),
    "h3": (0.196, 0.132, 0.066),
    "h4": (0.232, 0.222, 0.210),
    "h5": (0.352, 0.346, 0.338),
}
"""Hair tones, likewise by index; ``h4`` and ``h5`` are the greyed pair."""

ACCENT_COLOR = (0.036, 0.030, 0.028)
"""Eyes, brow and dark garment detail. One near-black for all of them: a face
must be PRESENT, never rendered."""

PROXY_BEVEL = 0.0022
"""Edge softening every body carries.

Applied to EVERY proxy, not just the first of each reused mesh. A bevel is an
object modifier rather than mesh data, so bodies that share a datablock do not
share it: the first version of this builder gave it to twenty proxies and left
the other sixty rendering as hard-edged, which made "the same variant and pose
is the same body" false in the only place it is visible.

Two point two millimetres, down from twelve. The bevel used to be doing the
work of making boxes look less like boxes; the geometry does that now.

The number is small because the bevel is applied to the whole body and an eye
is only two centimetres across. At five millimetres the structural ray probe
caught it rounding an eye that stands nine millimetres proud of the cheek down
to one -- the bevel was quietly re-burying the feature the last correction
dug out. Edge softening must not be able to erase a face."""

PROXY_BEVEL_LIMIT = "NONE"
"""How a body's bevel chooses its edges, and the one place that differs.

Everything else this project builds stands still, so an angle threshold is the
right way to pick edges: only the sharp ones get softened. A body does not
stand still. Its limbs articulate, an angle threshold is a question about
geometry, and a joint sweeping its dihedral past the threshold gains or loses
the vertices a bevel would have inserted -- so the evaluated mesh changes
length between one frame of the gait and the next, and reading it by frame
zero's indices runs off the end.

Measured rather than assumed: swept over the walking vocabulary -- every age,
build, stature and pose, through every phase of the gait -- a figure's own
edges visit every angle from near zero to a hundred and twenty-eight degrees
with no gap anywhere in between, so no threshold exists that some edge does not
cross. Retreating to a higher number does not work; declining to ask the
question does. Beveling every edge makes the selected set a property of the
identity, which is the only thing a shared mesh may depend on.

It softens more edges than a threshold would, which on a body is the flattering
direction: the extra ones are the facet seams running down a limb, and rounding
them by two millimetres reads as a limb rather than as a prism. The cost is
paid in evaluated geometry at render time, never in the mesh datablock, so the
per-figure and per-layer triangle budgets are untouched."""

DUPLICATE_SUFFIX = re.compile(r"\.\d{3}$")
"""Blender's collision rename. Finding one anywhere in the layer is a defect,
not a cosmetic detail: it means a rebuild grew the scene instead of replacing
it, and the next rebuild would grow it again."""


def ensure_population_collection() -> bpy.types.Collection:
    """Create (or fetch) ``LD_POPULATION`` under the master scene root."""
    root_world = bpy.data.collections.get("LD_WORLD")
    if root_world is None:
        raise RuntimeError(
            "the master scene is not built; run build_master_scene before adding population"
        )
    population = bpy.data.collections.get(POPULATION_ROOT)
    if population is None:
        population = bpy.data.collections.new(POPULATION_ROOT)
    if population.name not in {child.name for child in root_world.children}:
        root_world.children.link(population)
    return population


def _flat_material(name: str, color: tuple[float, float, float]) -> bpy.types.Material:
    """A matte, slightly rough surface for one figure family.

    Reused when it already exists so a rebuild does not churn datablocks or
    invent a ``.001`` twin.
    """
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
    material.use_nodes = True
    principled = material.node_tree.nodes["Principled BSDF"]
    principled.inputs["Base Color"].default_value = (*color, 1.0)
    principled.inputs["Roughness"].default_value = 0.72
    principled.inputs["Metallic"].default_value = 0.0
    return material


def build_population_materials() -> dict[str, bpy.types.Material]:
    """The Phase 18 material set, under its own prefix.

    Never touches the ``LD_MAT__`` family: the Phase 16 structural suite
    proves that family is unchanged by later work, and population must not be
    the phase that breaks it.
    """
    materials: dict[str, bpy.types.Material] = {}
    for group, colors in (
        ("", PALETTE_COLORS),
        ("skin_", COMPLEXION_COLORS),
        ("hair_", HAIR_COLORS),
    ):
        for name, color in sorted(colors.items()):
            materials[f"{group}{name}"] = _flat_material(f"{MATERIAL_PREFIX}{group}{name}", color)
    materials["accent"] = _flat_material(f"{MATERIAL_PREFIX}accent", ACCENT_COLOR)
    return materials


# ---------------------------------------------------------------------------
# The body
# ---------------------------------------------------------------------------


def clear_population_layer() -> int:
    """Remove every Phase 18 object and mesh, leaving the city untouched.

    Both prefixes are cleared, not just the objects. A mesh left behind under
    its template name would collide with the next build's rename and Blender
    would silently hand back a ``.001`` twin -- the exact failure the
    idempotency contract forbids.

    The collection goes too. "Fully removable" has to mean the file carries no
    trace of the layer, and an empty ``LD_POPULATION`` hanging under
    ``LD_WORLD`` is a trace. Callers that are about to rebuild must therefore
    clear FIRST and fetch the collection afterwards, which is what
    :func:`apply_population_presence` does.
    """
    removed = 0
    for obj in [item for item in bpy.data.objects if item.name.startswith(PROXY_PREFIX)]:
        bpy.data.objects.remove(obj, do_unlink=True)
        removed += 1
    for mesh in [item for item in bpy.data.meshes if item.name.startswith("LD_POP")]:
        bpy.data.meshes.remove(mesh, do_unlink=True)
    collection = bpy.data.collections.get(POPULATION_ROOT)
    if collection is not None:
        bpy.data.collections.remove(collection)
    return removed


def build_figure_object(
    name: str,
    geometry: dict,
    location: tuple[float, float, float],
    collection: bpy.types.Collection,
    materials: list[bpy.types.Material],
    *,
    rotation_z: float,
    bevel: float,
) -> bpy.types.Object:
    """Weld one pure body into one Blender object.

    The kit hands over vertices, faces and a material slot per face; this adds
    nothing. In particular it does NOT weld coincident vertices: a body is a
    set of interpenetrating closed solids -- a skull, a torso hull, four limb
    chains -- and merging their surfaces where they happen to touch would tear
    holes in solids that are individually watertight.

    Normals are recalculated rather than trusted. Every primitive is emitted
    with outward winding, but a recalculation costs nothing and means a future
    primitive cannot ship inside-out.
    """
    builder = bmesh.new()
    vertices = [builder.verts.new(vertex) for vertex in geometry["vertices"]]
    builder.verts.ensure_lookup_table()
    for corners, material_index in zip(geometry["faces"], geometry["materials"], strict=True):
        face = builder.faces.new([vertices[index] for index in corners])
        face.material_index = material_index
    bmesh.ops.recalc_face_normals(builder, faces=list(builder.faces))
    replace_object(name)
    mesh = bpy.data.meshes.new(name)
    builder.to_mesh(mesh)
    builder.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    obj.rotation_euler = (0.0, 0.0, rotation_z)
    for material in materials:
        obj.data.materials.append(material)
    if bevel > 0.0:
        add_bevel(obj, width=bevel, limit_method=PROXY_BEVEL_LIMIT)
    link_only(obj, collection)
    return obj


def apply_population_presence(plan: dict, presence_spec: dict) -> dict:
    """Build the visible population layer from one presence plan.

    Returns the metrics the manifest reports: how many proxies were built,
    how many meshes they share, and the plan digest they were built from.

    Raises:
        RuntimeError: If the master scene is not present, or the plan names a
            palette the material set does not carry.
    """
    clear_population_layer()
    collection = ensure_population_collection()
    materials = build_population_materials()

    shared: dict[tuple[str, ...], bpy.types.Mesh] = {}
    built = 0
    reused = 0
    for proxy in sorted(plan["proxies"], key=lambda entry: entry["slot"]):
        slots = (
            proxy["palette"],
            f"skin_{proxy['complexion']}",
            f"hair_{proxy['hair_tone']}",
            "accent",
        )
        missing = [entry for entry in slots if entry not in materials]
        if missing:
            raise RuntimeError(f"proxy {proxy['slot']} wants unknown material(s) {missing}")
        name = f"{PROXY_PREFIX}{proxy['slot']}"
        location = (float(proxy["x"]), float(proxy["y"]), float(proxy["z"]))
        heading = float(proxy["heading"])
        # The material slots belong to the MESH datablock, so two proxies may
        # only share a mesh when their palette, complexion and hair tone match
        # as well as their geometry -- otherwise reuse would silently repaint
        # somebody. This is why the key is not the geometry key alone.
        key = (proxy["geometry_key"], *slots)
        template = shared.get(key)
        if template is None:
            obj = build_figure_object(
                name,
                figure_kit.figure_mesh(proxy),
                location,
                collection,
                [materials[entry] for entry in slots],
                rotation_z=heading,
                bevel=PROXY_BEVEL,
            )
            obj.data.name = f"{MESH_PREFIX}{proxy['geometry_key']}"
            shared[key] = obj.data
        else:
            replace_object(name)
            obj = bpy.data.objects.new(name, template)
            obj.location = location
            obj.rotation_euler = (0.0, 0.0, heading)
            add_bevel(obj, width=PROXY_BEVEL, limit_method=PROXY_BEVEL_LIMIT)
            link_only(obj, collection)
            reused += 1
        built += 1
    return {
        "proxies_built": built,
        "distinct_body_meshes": len(shared),
        "reused_body_mesh_instances": reused,
        "collection": POPULATION_ROOT,
        "plan_hash": plan_hash(plan),
        "residents_per_proxy": float(presence_spec["density"]["residents_per_proxy"]),
    }


def population_objects() -> list[bpy.types.Object]:
    """Every built proxy, in stable name order."""
    return sorted(
        (item for item in bpy.data.objects if item.name.startswith(PROXY_PREFIX)),
        key=lambda item: item.name,
    )


def population_summary() -> dict:
    """What the scene actually holds, read back from Blender itself.

    Read back rather than remembered: a manifest that reported what the
    builder intended would prove nothing about what the ``.blend`` carries.

    The mesh metrics are named for what they measure. An earlier manifest
    reported ``shared_meshes: 80`` beside ``proxy_objects: 80``, which reads as
    eighty bodies sharing eighty meshes -- a sharing claim that is really a
    count of distinct meshes, and evidence of no sharing at all. It is stated
    plainly now:

    ``distinct_body_meshes``
        how many mesh datablocks the layer actually created;
    ``reused_body_mesh_instances``
        how many proxies were built by pointing at a mesh that already existed;
    ``mesh_reuse_ratio``
        reused instances over proxies -- zero when every body is unique;
    ``population_triangles``
        the triangles in the mesh DATA, which is what the declared budget is
        counted against. The bevel modifier adds render-time geometry on top of
        it and is deliberately not counted here, because a budget that moved
        with a modifier setting could not be compared between runs.

    In the canonical eighty-person scene that ratio is 0.0, and honestly so:
    the diversity system gives every visible resident a different combination
    of age, build, stature, hair, garment, face and pose, so no two bodies are
    the same mesh. The sharing path is not dead code -- it fires the moment two
    slots do land on the same body and the same colours -- but nothing here
    will claim a saving the scene did not make.
    """
    objects = population_objects()
    collection = bpy.data.collections.get(POPULATION_ROOT)
    triangles = 0
    for item in objects:
        item.data.calc_loop_triangles()
        triangles += len(item.data.loop_triangles)
    distinct = len({item.data.name for item in objects})
    return {
        "proxy_objects": len(objects),
        "duplicate_named_objects": sum(1 for item in objects if DUPLICATE_SUFFIX.search(item.name))
        + sum(
            1
            for mesh in bpy.data.meshes
            if mesh.name.startswith("LD_POP") and DUPLICATE_SUFFIX.search(mesh.name)
        ),
        "distinct_body_meshes": distinct,
        "reused_body_mesh_instances": len(objects) - distinct,
        "mesh_reuse_ratio": round((len(objects) - distinct) / len(objects), 4) if objects else 0.0,
        "population_triangles": triangles,
        "materials": sorted(
            name
            for name in (item.name for item in bpy.data.materials)
            if name.startswith(MATERIAL_PREFIX)
        ),
        "collection_present": collection is not None,
        "linked_elsewhere": sum(
            1 for item in objects if {c.name for c in item.users_collection} != {POPULATION_ROOT}
        ),
    }


def proxy_positions() -> dict[str, tuple[float, float, float, float]]:
    """Each proxy's world transform, for structural comparison across builds."""
    return {
        obj.name: (
            round(obj.location[0], 6),
            round(obj.location[1], 6),
            round(obj.location[2], 6),
            round(math.fmod(obj.rotation_euler[2], 2.0 * math.pi), 6),
        )
        for obj in population_objects()
    }


def main() -> None:
    """Blender entry point: apply one presence plan to the open scene."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, help="population presence plan JSON")
    parser.add_argument("--spec", required=True, help="population presence spec JSON")
    arguments = parser.parse_args(argv)
    plan = json.loads(Path(arguments.plan).read_text(encoding="utf-8"))
    spec = json.loads(Path(arguments.spec).read_text(encoding="utf-8"))
    metrics = apply_population_presence(plan, spec)
    print(json.dumps(metrics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
