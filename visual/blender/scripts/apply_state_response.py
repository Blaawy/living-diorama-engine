"""Apply one State Response Plan's visible world condition onto the built scene.

The persistent city is geography; the episode layer is what the engine did; this
script layers what the world's authoritative condition LOOKS like: each
district's air carries that district's own scarcity, and the Seal plaza carries
one record stone for each durable fact the engine decided to remember.

The layer is deliberately isolated and deliberately REMOVABLE:

* every object lives under ``LD_STATE_RESPONSE`` with a stable ``LD_SR__`` name;
* every material Phase 20 needs it builds itself under ``LD_SR_MAT__``, because
  the shared ``LD_MAT__`` family is keyed by district CHARACTER and reused by the
  production city, so one material there could never carry one district's truth;
* every action is named ``LD_STATE_RESPONSE__`` and is cleared before rebuild;
* clearing the layer returns the scene to exactly the state it was handed.

Application is idempotent: each apply clears the layer and rebuilds it from the
plan, so applying the same plan twice yields the same scene, and applying a plan
with fewer record stones removes the extra ones rather than leaving them behind.

Nothing here reads the simulation and nothing here writes it. A response is
placed because a plan says an authoritative field said so.

Run headless, after the master scene and production world exist in the same
session::

    blender --background --factory-startup --python-exit-code 1 \
        --python visual/blender/scripts/apply_state_response.py -- \
        --plan &lt;plan.json&gt; --spec &lt;state_response_v1.json&gt;
"""

import argparse
import json
import math
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))

from blender_runtime import (  # noqa: E402
    link_only,
    make_box,
    require_supported_blender,
)
from state_response_plan import (  # noqa: E402
    AIR_DENSITY_NODE,
    AIR_MATERIAL_PREFIX,
    RECORD_OBJECT_PREFIX,
)

STATE_RESPONSE_ROOT = "LD_STATE_RESPONSE"
WORLD_ROOT = "LD_WORLD"
OBJECT_PREFIX = "LD_SR__"
MESH_PREFIX = "LD_SR_MESH__"
MATERIAL_PREFIX = "LD_SR_MAT__"
ACTION_PREFIX = "LD_STATE_RESPONSE__"
AIR_OBJECT_PREFIX = "LD_SR__air_"
RECORD_MATERIAL = "LD_SR_MAT__record"

MAX_ID_NAME_BYTES = 63
"""Blender truncates identifiers past this length, silently.

A truncated name breaks replace-by-name, which breaks idempotency, which turns a
second apply into a scene full of ``.001`` twins nobody asked for.
"""


class StateResponseApplyError(RuntimeError):
    """A Phase 20 application failure.

    Raised when the scene is not ready for this layer, when a plan names a target
    that does not exist, and when a name would be truncated. Always a refusal,
    never a repair.
    """


def _require_name(name: str) -> str:
    """Return a name Blender will store whole, or refuse."""
    if len(name.encode("utf-8")) > MAX_ID_NAME_BYTES:
        raise StateResponseApplyError(
            f"the name {name!r} is longer than Blender's {MAX_ID_NAME_BYTES}-byte identifier "
            "limit and would be truncated, which breaks replace-by-name"
        )
    return name


def ensure_state_response_collection() -> bpy.types.Collection:
    """Return the Phase 20 collection, creating and linking it under the world root."""
    root_world = bpy.data.collections.get(WORLD_ROOT)
    if root_world is None:
        raise StateResponseApplyError(
            "the master scene is not built; run build_master_scene before adding state response"
        )
    collection = bpy.data.collections.get(STATE_RESPONSE_ROOT)
    if collection is None:
        collection = bpy.data.collections.new(STATE_RESPONSE_ROOT)
    if collection.name not in {child.name for child in root_world.children}:
        root_world.children.link(collection)
    return collection


def clear_state_response_layer() -> int:
    """Remove every Phase 20 object, mesh, material and action, and the collection.

    The order matters. Actions come off first so no curve is left driving a
    property that is about to vanish; meshes and materials follow their objects,
    because a datablock left under its template name collides with the next
    build's rename and Blender silently hands back a ``.001`` twin; and the
    collection goes last, because an empty ``LD_STATE_RESPONSE`` hanging under
    ``LD_WORLD`` is a trace of a layer that claims to have been removed.

    Returns:
        How many objects were removed.
    """
    removed = 0
    for obj in list(bpy.data.objects):
        if obj.name.startswith(OBJECT_PREFIX):
            obj.animation_data_clear()
    for material in list(bpy.data.materials):
        if material.name.startswith(MATERIAL_PREFIX) and material.node_tree is not None:
            material.node_tree.animation_data_clear()
    for action in list(bpy.data.actions):
        if action.name.startswith(ACTION_PREFIX):
            bpy.data.actions.remove(action)
    for obj in list(bpy.data.objects):
        if obj.name.startswith(OBJECT_PREFIX):
            bpy.data.objects.remove(obj, do_unlink=True)
            removed += 1
    for mesh in list(bpy.data.meshes):
        if mesh.name.startswith(MESH_PREFIX):
            bpy.data.meshes.remove(mesh)
    for material in list(bpy.data.materials):
        if material.name.startswith(MATERIAL_PREFIX):
            bpy.data.materials.remove(material)
    collection = bpy.data.collections.get(STATE_RESPONSE_ROOT)
    if collection is not None:
        bpy.data.collections.remove(collection)
    return removed


def build_air_material(district_id: str, response: dict, air: dict) -> bpy.types.Material:
    """Build one district's air material, with its density on a named, keyable node.

    The density socket is the only thing authoritative state drives. Everything
    else -- the tint, the soft rim, the height falloff -- is fixed shape, so the
    stratum reads as weather rather than as a status colour, and so a viewer
    never has to decide which of two variables moved.

    Args:
        district_id: The district this air belongs to.
        response: That district's air response from the plan.
        air: The spec's air field constants.

    Returns:
        The material, carrying a value node named :data:`AIR_DENSITY_NODE`.
    """
    name = _require_name(f"{AIR_MATERIAL_PREFIX}{district_id}")
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()

    output = tree.nodes.new("ShaderNodeOutputMaterial")
    output.location = (620.0, 0.0)
    scatter = tree.nodes.new("ShaderNodeVolumeScatter")
    scatter.location = (420.0, -40.0)
    scatter.inputs["Color"].default_value = (*air["tint"], 1.0)
    scatter.inputs["Anisotropy"].default_value = air["anisotropy"]

    density = tree.nodes.new("ShaderNodeValue")
    density.name = AIR_DENSITY_NODE
    density.label = AIR_DENSITY_NODE
    density.location = (-620.0, -180.0)
    density.outputs[0].default_value = response["value"]

    coordinates = tree.nodes.new("ShaderNodeTexCoord")
    coordinates.location = (-940.0, 220.0)
    separate = tree.nodes.new("ShaderNodeSeparateXYZ")
    separate.location = (-760.0, 220.0)
    tree.links.new(coordinates.outputs["Generated"], separate.inputs["Vector"])

    # Generated coordinates run 0..1 across the volume's own bounds whatever its
    # object scale, so the rim and the ceiling are expressed as fractions of the
    # box rather than as metres that a rescale could silently invalidate.
    centred = tree.nodes.new("ShaderNodeCombineXYZ")
    centred.location = (-580.0, 260.0)
    for axis, socket in (("X", "X"), ("Y", "Y")):
        offset = tree.nodes.new("ShaderNodeMath")
        offset.operation = "SUBTRACT"
        offset.location = (-700.0, 380.0 if axis == "X" else 300.0)
        tree.links.new(separate.outputs[socket], offset.inputs[0])
        offset.inputs[1].default_value = 0.5
        tree.links.new(offset.outputs[0], centred.inputs[axis])
    centred.inputs["Z"].default_value = 0.0

    radius = tree.nodes.new("ShaderNodeVectorMath")
    radius.operation = "LENGTH"
    radius.location = (-420.0, 260.0)
    tree.links.new(centred.outputs["Vector"], radius.inputs[0])

    rim = tree.nodes.new("ShaderNodeMapRange")
    rim.location = (-240.0, 260.0)
    rim.clamp = True
    rim.inputs["From Min"].default_value = max(0.0, 0.5 - response["field"]["rim_fraction"])
    rim.inputs["From Max"].default_value = 0.5
    rim.inputs["To Min"].default_value = 1.0
    rim.inputs["To Max"].default_value = 0.0
    tree.links.new(radius.outputs["Value"], rim.inputs["Value"])

    ceiling = tree.nodes.new("ShaderNodeMapRange")
    ceiling.location = (-240.0, 20.0)
    ceiling.clamp = True
    ceiling.inputs["From Min"].default_value = 0.0
    ceiling.inputs["From Max"].default_value = 1.0
    ceiling.inputs["To Min"].default_value = 1.0
    ceiling.inputs["To Max"].default_value = air["floor_density_fraction"]
    tree.links.new(separate.outputs["Z"], ceiling.inputs["Value"])

    shape = tree.nodes.new("ShaderNodeMath")
    shape.operation = "MULTIPLY"
    shape.location = (-40.0, 160.0)
    tree.links.new(rim.outputs["Result"], shape.inputs[0])
    tree.links.new(ceiling.outputs["Result"], shape.inputs[1])

    scaled = tree.nodes.new("ShaderNodeMath")
    scaled.operation = "MULTIPLY"
    scaled.location = (180.0, 60.0)
    tree.links.new(shape.outputs[0], scaled.inputs[0])
    tree.links.new(density.outputs[0], scaled.inputs[1])
    tree.links.new(scaled.outputs[0], scatter.inputs["Density"])
    tree.links.new(scatter.outputs["Volume"], output.inputs["Volume"])
    return material


def build_record_material() -> bpy.types.Material:
    """Build the record stone material: cut stone with a warm inlay."""
    material = bpy.data.materials.new(_require_name(RECORD_MATERIAL))
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled is not None:
        principled.inputs["Base Color"].default_value = (0.052, 0.049, 0.045, 1.0)
        principled.inputs["Roughness"].default_value = 0.36
        principled.inputs["Metallic"].default_value = 0.0
        principled.inputs["Emission Color"].default_value = (1.0, 0.74, 0.42, 1.0)
        principled.inputs["Emission Strength"].default_value = 1.6
    return material


def _air_volume(
    response: dict, material: bpy.types.Material, collection: bpy.types.Collection
) -> bpy.types.Object:
    """Build one district's air volume box."""
    field = response["field"]
    radius = field["radius"]
    height = field["ceiling"] - field["floor"]
    # make_box origins at the BASE centre, not the centre: a half-height offset
    # here would lift the whole stratum off the ground it is the air of, and
    # would map the shader's floor-to-ceiling falloff over the wrong band.
    obj = make_box(
        _require_name(f"{AIR_OBJECT_PREFIX}{response['semantic_id']}"),
        (radius * 2.0, radius * 2.0, height),
        (field["centre"][0], field["centre"][1], field["floor"]),
        collection,
        material,
    )
    if obj.data is not None:
        obj.data.name = _require_name(f"{MESH_PREFIX}air_{response['semantic_id']}")
    obj.display_type = "WIRE"
    return obj


def _record_stone(
    response: dict, size: tuple, material: bpy.types.Material, collection: bpy.types.Collection
) -> bpy.types.Object:
    """Build one record stone on the Seal plaza arc."""
    field = response["field"]
    obj = make_box(
        _require_name(f"{RECORD_OBJECT_PREFIX}{field['slot']:03d}"),
        size,
        (field["x"], field["y"], field["z"]),
        collection,
        material,
        rotation_z=field["heading"] + math.pi / 2.0,
        bevel=0.012,
    )
    if obj.data is not None:
        obj.data.name = _require_name(f"{MESH_PREFIX}record_{field['slot']:03d}")
    return obj


def apply_state_response(plan: dict, spec: dict, *, visibility_profile: str = "full") -> dict:
    """Build the visible state-response layer from one plan.

    Args:
        plan: A State Response Plan.
        spec: A resolved state response spec.
        visibility_profile: ``"full"`` (default) or ``"director_clear_air_v1"``.
            ``"full"`` reproduces today's behaviour byte-for-byte: every channel
            the plan declares is drawn. ``"director_clear_air_v1"`` declines to
            draw the per-district air haze for the Director's final EP1 profile;
            the district-air FACT is unchanged -- the plan is still computed and
            reported in full -- only its visualisation is skipped.

    Returns:
        What was built: object, material and per-channel counts.

    Raises:
        StateResponseApplyError: If the scene is not ready for this layer.
    """
    require_supported_blender()
    clear_state_response_layer()
    collection = ensure_state_response_collection()

    record_material = None
    built: dict[str, int] = {}
    for response in plan["responses"]:
        channel = response["channel"]
        if channel == "district_air":
            if visibility_profile == "director_clear_air_v1":
                # The district-air FACT is unchanged: the plan still computed it
                # and the state-response plan still reports it. This profile
                # only declines to DRAW the haze, so nothing is built for the
                # channel here, and the truthful per-channel count below
                # records zero built for it.
                continue
            material = build_air_material(response["semantic_id"], response, spec["air"])
            obj = _air_volume(response, material, collection)
        elif channel == "memory_record":
            if record_material is None:
                record_material = build_record_material()
            obj = _record_stone(
                response, tuple(spec["record"]["stone_size_metres"]), record_material, collection
            )
        else:
            raise StateResponseApplyError(
                f"the plan declares channel {channel!r}, which this applier does not build; "
                "an unknown channel is refused, never skipped"
            )
        built[channel] = built.get(channel, 0) + 1
        link_only(obj, collection)

    bpy.context.view_layer.update()
    return {
        "objects": len(state_response_objects()),
        "materials": len([m for m in bpy.data.materials if m.name.startswith(MATERIAL_PREFIX)]),
        "responses_by_channel": dict(sorted(built.items())),
    }


def state_response_objects() -> list[bpy.types.Object]:
    """Return every object this layer owns, in stable name order."""
    return sorted(
        (obj for obj in bpy.data.objects if obj.name.startswith(OBJECT_PREFIX)),
        key=lambda obj: obj.name,
    )


def air_density_of(district_id: str) -> float:
    """Return the density socket one district's air material currently carries."""
    material = bpy.data.materials.get(f"{AIR_MATERIAL_PREFIX}{district_id}")
    if material is None or material.node_tree is None:
        raise StateResponseApplyError(f"district {district_id!r} has no air material")
    node = material.node_tree.nodes.get(AIR_DENSITY_NODE)
    if node is None:
        raise StateResponseApplyError(
            f"district {district_id!r} air material carries no {AIR_DENSITY_NODE} node"
        )
    return float(node.outputs[0].default_value)


def state_response_summary() -> dict:
    """Measure what the layer actually put in the scene.

    Measured from the scene, never copied from the plan: a summary that repeated
    the plan back would agree with it even when the scene did not.
    """
    objects = state_response_objects()
    triangles = 0
    for obj in objects:
        if obj.type != "MESH" or obj.data is None:
            continue
        for polygon in obj.data.polygons:
            triangles += max(0, len(polygon.vertices) - 2)
    air = [obj for obj in objects if obj.name.startswith(AIR_OBJECT_PREFIX)]
    stones = [obj for obj in objects if obj.name.startswith(RECORD_OBJECT_PREFIX)]
    return {
        "air_volumes": len(air),
        "densities": {
            obj.name[len(AIR_OBJECT_PREFIX) :]: air_density_of(obj.name[len(AIR_OBJECT_PREFIX) :])
            for obj in air
        },
        "materials": len([m for m in bpy.data.materials if m.name.startswith(MATERIAL_PREFIX)]),
        "objects": len(objects),
        "record_stones": len(stones),
        "state_response_triangles": triangles,
    }


def apply_state_response_file(plan_path: str | Path, spec_path: str | Path) -> dict:
    """Apply one plan and one spec from disk."""
    from state_response_spec import load_state_response_spec

    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    spec = load_state_response_spec(spec_path)
    return apply_state_response(plan, spec)


def main(argv: list[str] | None = None) -> int:
    """Apply a state response plan inside Blender."""
    parser = argparse.ArgumentParser(description="apply a Phase 20 state response plan")
    parser.add_argument("--plan", required=True, help="state response plan JSON")
    parser.add_argument("--spec", required=True, help="state response spec JSON")
    arguments = argv if argv is not None else sys.argv[sys.argv.index("--") + 1 :]
    parsed = parser.parse_args(arguments)
    metrics = apply_state_response_file(parsed.plan, parsed.spec)
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
