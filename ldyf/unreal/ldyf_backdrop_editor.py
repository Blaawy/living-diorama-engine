"""Build a ``backdrop_spec_v1`` document into the level.

The city sits on a finite ground plane, and in any wide shot that plane simply
runs out: the city floats on a slab against empty sky. This adds the two things
that hide the edge -- a ground skirt continuing outward past the world bbox, and
low-detail massing on concentric rings to break the horizon line.

**This is presentation only.** Nothing here is simulated, nothing here is
traffic, and nothing here is ever counted as world truth. It carries its own
``LD_BACKDROP`` label prefix so the level inventory can tell it apart from the
simulated world at a glance, and so a future check can assert that no backdrop
actor is ever read as a road, a building or an agent.

The spec's own ``atmosphere`` block is deliberately NOT applied here. Fog is
owned by ``ldyf.lighting``, which was tuned against real rendered frames; the
backdrop module derives its fog independently and in different units (its
``fog_density`` is order 1, Unreal's is order 1e-2), so applying both would be
two authorities fighting over one setting.
"""
from __future__ import annotations

import unreal  # type: ignore[import-not-found]

PREFIX = "LD_BACKDROP"
SKIRT_ACTOR = PREFIX + "_Skirt"
MASSING_ACTOR = PREFIX + "_Massing"
MESH_DIR = "/Game/LD/Meshes"
MAT_DIR = "/Game/LD/Materials"
SKIRT_MESH = MESH_DIR + "/SM_LD_BackdropSkirt"
MASS_MESH = MESH_DIR + "/SM_LD_BackdropMass"


def _clear(prefix: str) -> int:
    EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    n = 0
    for a in list(EAS.get_all_level_actors()):
        if a is not None and str(a.get_actor_label()).startswith(prefix):
            EAS.destroy_actor(a)
            n += 1
    return n


def ensure_backdrop_materials() -> dict:
    """A ground material for the skirt and a haze-grey one for distant massing."""
    eal = unreal.EditorAssetLibrary
    at = unreal.AssetToolsHelpers.get_asset_tools()
    mel = unreal.MaterialEditingLibrary
    made = {}
    for name, rgb, rough in (("MI_LD_BackdropGround", (0.055, 0.062, 0.042), 0.95),
                             ("MI_LD_BackdropMass", (0.085, 0.095, 0.115), 0.85)):
        path = "%s/%s" % (MAT_DIR, name)
        mi = eal.load_asset(path)
        if mi is None:
            master = eal.load_asset(MAT_DIR + "/M_LD_Cloth")
            if master is None:
                raise RuntimeError("M_LD_Cloth master missing; build the crowd "
                                   "materials first (it is the plain lit master)")
            mi = at.create_asset(name, MAT_DIR, unreal.MaterialInstanceConstant,
                                 unreal.MaterialInstanceConstantFactoryNew())
            mel.set_material_instance_parent(mi, master)
        mel.set_material_instance_vector_parameter_value(
            mi, "ClothColor", unreal.LinearColor(rgb[0], rgb[1], rgb[2], 1.0))
        mel.set_material_instance_scalar_parameter_value(mi, "ClothRoughness", rough)
        eal.save_loaded_asset(mi, False)
        made[name] = path
    return made


def build_skirt_mesh(skirt: list, *, z_cm: float) -> dict:
    """One StaticMesh holding every skirt quad, two triangles each."""
    eal = unreal.EditorAssetLibrary
    at = unreal.AssetToolsHelpers.get_asset_tools()
    sm = eal.load_asset(SKIRT_MESH)
    if sm is None:
        sm = at.create_asset("SM_LD_BackdropSkirt", MESH_DIR, unreal.StaticMesh, None)
    smd = sm.create_static_mesh_description()
    group = smd.create_polygon_group()
    smd.set_polygon_group_material_slot_name(group, "ground")
    tris = 0
    for q in skirt:
        c = q["corners"]
        vids = []
        for (x, y) in c:
            v = smd.create_vertex()
            smd.set_vertex_position(v, unreal.Vector(float(x), float(y), float(z_cm)))
            vids.append(v)
        ins = []
        for k, v in enumerate(vids):
            inst = smd.create_vertex_instance(v)
            u = (0.0, 1.0, 1.0, 0.0)[k]
            w = (0.0, 0.0, 1.0, 1.0)[k]
            smd.set_vertex_instance_uv(inst, unreal.Vector2D(u, w), 0)
            ins.append(inst)
        smd.create_triangle(group, [ins[0], ins[1], ins[2]])
        smd.create_triangle(group, [ins[0], ins[2], ins[3]])
        tris += 2
    sm.build_from_static_mesh_descriptions([smd], False)
    sm.add_material(eal.load_asset(MAT_DIR + "/MI_LD_BackdropGround"))
    eal.save_loaded_asset(sm, False)
    return {"asset": SKIRT_MESH, "quads": len(skirt), "triangles": tris,
            "built": sm.get_num_triangles(0)}


def build_mass_mesh() -> dict:
    """A unit box authored here, NOT ``/Engine/BasicShapes/Cube``.

    The level inventory's blockout rule exists to catch engine placeholder
    geometry standing in for real content, and it is right to fire on the
    engine cube -- it did, and it failed the gate. Weakening that rule to let
    the backdrop through would be exactly the kind of green-by-exemption this
    project refuses. Authoring the box instead means the backdrop ships its own
    asset with its own material and the rule keeps its teeth untouched.

    One cubic metre centred on its base, so an instance's scale is its size in
    metres and its origin sits on the ground.
    """
    eal = unreal.EditorAssetLibrary
    at = unreal.AssetToolsHelpers.get_asset_tools()
    sm = eal.load_asset(MASS_MESH)
    if sm is None:
        sm = at.create_asset("SM_LD_BackdropMass", MESH_DIR, unreal.StaticMesh, None)
    smd = sm.create_static_mesh_description()
    g = smd.create_polygon_group()
    smd.set_polygon_group_material_slot_name(g, "mass")
    h = 50.0
    corners = [(-h, -h, 0.0), (h, -h, 0.0), (h, h, 0.0), (-h, h, 0.0),
               (-h, -h, 100.0), (h, -h, 100.0), (h, h, 100.0), (-h, h, 100.0)]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    tris = 0
    for face in faces:
        ins = []
        for k, ci in enumerate(face):
            v = smd.create_vertex()
            smd.set_vertex_position(v, unreal.Vector(*corners[ci]))
            inst = smd.create_vertex_instance(v)
            u, w = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))[k]
            smd.set_vertex_instance_uv(inst, unreal.Vector2D(u, w), 0)
            ins.append(inst)
        smd.create_triangle(g, [ins[0], ins[1], ins[2]])
        smd.create_triangle(g, [ins[0], ins[2], ins[3]])
        tris += 2
    sm.build_from_static_mesh_descriptions([smd], False)
    sm.add_material(eal.load_asset(MAT_DIR + "/MI_LD_BackdropMass"))
    eal.save_loaded_asset(sm, False)
    return {"asset": MASS_MESH, "triangles": tris, "built": sm.get_num_triangles(0)}


def build_backdrop(doc: dict, *, ground_z_cm: float = 0.0) -> dict:
    """Spawn the skirt and the distant massing. Replaces any previous backdrop."""
    eal = unreal.EditorAssetLibrary
    EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    removed = _clear(PREFIX)
    mats = ensure_backdrop_materials()
    skirt_info = build_skirt_mesh(doc["skirt"], z_cm=ground_z_cm)

    sm = eal.load_asset(SKIRT_MESH)
    skirt_actor = EAS.spawn_actor_from_object(sm, unreal.Vector(0, 0, 0),
                                              unreal.Rotator(0, 0, 0))
    skirt_actor.set_actor_label(SKIRT_ACTOR)

    mass_info = build_mass_mesh()
    cube = eal.load_asset(MASS_MESH)
    mass_mat = eal.load_asset(MAT_DIR + "/MI_LD_BackdropMass")
    massing_actor = EAS.spawn_actor_from_class(
        unreal.Actor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
    massing_actor.set_actor_label(MASSING_ACTOR)
    sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    root_handle = sub.k2_gather_subobject_data_for_instance(massing_actor)[0]
    handle, _fail = sub.add_new_subobject(
        unreal.AddNewSubobjectParams(parent_handle=root_handle,
                                     new_class=unreal.InstancedStaticMeshComponent,
                                     blueprint_context=None))
    ism = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(
        sub.k2_find_subobject_data_from_handle(handle))
    ism.set_static_mesh(cube)
    ism.set_material(0, mass_mat)
    # the authored box is 100 cm on a side with its origin on its base, so
    # scale is the size in metres and z is the ground, not the centre
    placed = 0
    for m in sorted(doc["massing"], key=lambda r: r["id"]):
        t = unreal.Transform(
            unreal.Vector(float(m["x"]), float(m["y"]), ground_z_cm),
            unreal.Rotator(0.0, 0.0, float(m["yaw_deg"])),
            unreal.Vector(float(m["w_cm"]) / 100.0, float(m["d_cm"]) / 100.0,
                          float(m["h_cm"]) / 100.0))
        ism.add_instance(t)
        placed += 1

    return {"removed_previous": removed, "materials": mats, "skirt": skirt_info,
            "mass_mesh": mass_info,
            "massing_placed": placed,
            "massing_expected": len(doc["massing"]),
            "labels": [SKIRT_ACTOR, MASSING_ACTOR]}
