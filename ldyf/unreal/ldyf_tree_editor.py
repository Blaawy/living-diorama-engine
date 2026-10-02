"""Build a ``tree_mesh_v1`` document into a real Unreal StaticMesh.

Why the trees are authored rather than imported
-----------------------------------------------
Four separate attempts to make imported foliage render leaves were eliminated:
the City Sample prop kits are branch skeletons with no leaf cards at all, and
the Megascans plants' leaf sections render nothing under the shipped material,
with Nanite on, with Nanite off, and under a purpose-authored masked two-sided
material with its texture verified bound. The Director closed that path.

Authoring both halves works, and was proven on a single tree before any
integration: a card crown built through ``StaticMeshDescription`` and carrying
an ``MSM_TWO_SIDED_FOLIAGE`` material renders real, green, lit foliage.

Two engine details cost time and are recorded so they are not rediscovered:

* there is **no** ``unreal.StaticMeshFactoryNew``; create the asset with
  ``create_asset(name, pkg, unreal.StaticMesh, None)`` and take the description
  from ``sm.create_static_mesh_description()``;
* ``create_polygon`` takes only the polygon group in the Python binding (it
  returns the vertex-instance array as an out-parameter), so triangles go in
  through ``create_triangle(group, [i, j, k])``.

And the one that actually decides whether the tree looks like a tree: a leaf
card under the default lit shading model renders as a **black silhouette** when
backlit. It needs ``MSM_TWO_SIDED_FOLIAGE`` and a subsurface colour, or the
crown reads as a hole in the sky.
"""
from __future__ import annotations

import unreal  # type: ignore[import-not-found]

MESH_DIR = "/Game/LD/Meshes"
MAT_DIR = "/Game/LD/Materials"
LEAF_MASTER = MAT_DIR + "/M_LD_Leaf"
LEAF_INSTANCE = MAT_DIR + "/MI_LD_Leaf_Maple"
BARK_INSTANCE = MAT_DIR + "/MI_LD_Bark"

LEAF_COLOR_TEX = "/Game/Prop/Kit_Tree_Maple_Red/Texture/Cap"
LEAF_OPACITY_TEX = "/Game/Prop/Kit_Tree_Maple_Red/Texture/Cap_Opacity"
BARK_TEX = "/Game/Prop/Kit_Tree_Maple_Red/Texture/Bark"


def _linear(rgb):
    return unreal.LinearColor(float(rgb[0]), float(rgb[1]), float(rgb[2]), 1.0)


#: Leaf colour, tuned on rendered frames rather than picked on a colour wheel.
#:
#: The first values (0.46, 0.60, 0.22) / (0.32, 0.50, 0.12) read as fluorescent
#: lime: a bright yellow-green multiplying an already bright cap texture. The
#: Director rejected them as synthetic. Dropping both in proportion
#: (0.24, 0.35, 0.15) over-corrected to a washed-out mint, because the
#: subsurface term then dominated the darker base colour. These values are the
#: third render: green-dominant rather than yellow-dominant, and the subsurface
#: lowered FURTHER than the tint so the lit side carries the colour and the
#: shaded side stays readable without glowing. The Director still read that
#: third version as too bright, so the shipped values are a fourth: about 60%
#: of it again, which is where the canopies finally carry internal shadow and
#: read as foliage rather than as a bright green shape.
#:
#: Vegetation architecture is untouched -- same authored meshes, same
#: MSM_TWO_SIDED_FOLIAGE, and the SkyLight stays MOVABLE, which is what keeps
#: shadowed foliage from rendering black at all.
def ensure_tree_materials(*, leaf_tint=(0.095, 0.205, 0.070),
                          leaf_subsurface=(0.055, 0.130, 0.038)) -> dict:
    """Create the leaf master and the leaf/bark instances if absent."""
    eal = unreal.EditorAssetLibrary
    at = unreal.AssetToolsHelpers.get_asset_tools()
    mel = unreal.MaterialEditingLibrary
    problems: list = []

    mat = eal.load_asset(LEAF_MASTER)
    if mat is None:
        mat = at.create_asset("M_LD_Leaf", MAT_DIR, unreal.Material,
                              unreal.MaterialFactoryNew())
        mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
        mat.set_editor_property("shading_model",
                                unreal.MaterialShadingModel.MSM_TWO_SIDED_FOLIAGE)
        mat.set_editor_property("two_sided", True)
        mat.set_editor_property("opacity_mask_clip_value", 0.33)

        col = mel.create_material_expression(
            mat, unreal.MaterialExpressionTextureSampleParameter2D, -900, -200)
        col.set_editor_property("parameter_name", "LeafColor")
        tint = mel.create_material_expression(
            mat, unreal.MaterialExpressionVectorParameter, -900, 40)
        tint.set_editor_property("parameter_name", "LeafTint")
        tint.set_editor_property("default_value", _linear(leaf_tint))
        mul = mel.create_material_expression(
            mat, unreal.MaterialExpressionMultiply, -620, -120)
        mel.connect_material_expressions(col, "RGB", mul, "A")
        mel.connect_material_expressions(tint, "", mul, "B")

        sss = mel.create_material_expression(
            mat, unreal.MaterialExpressionVectorParameter, -900, 260)
        sss.set_editor_property("parameter_name", "LeafSubsurface")
        sss.set_editor_property("default_value", _linear(leaf_subsurface))

        opa = mel.create_material_expression(
            mat, unreal.MaterialExpressionTextureSampleParameter2D, -900, 470)
        opa.set_editor_property("parameter_name", "LeafOpacity")
        rgh = mel.create_material_expression(
            mat, unreal.MaterialExpressionScalarParameter, -900, 700)
        rgh.set_editor_property("parameter_name", "LeafRoughness")
        rgh.set_editor_property("default_value", 0.62)
        spc = mel.create_material_expression(
            mat, unreal.MaterialExpressionScalarParameter, -900, 800)
        spc.set_editor_property("parameter_name", "LeafSpecular")
        spc.set_editor_property("default_value", 0.22)

        for node, pin, prop in ((mul, "", "MP_BASE_COLOR"),
                                (sss, "", "MP_SUBSURFACE_COLOR"),
                                (opa, "R", "MP_OPACITY_MASK"),
                                (rgh, "", "MP_ROUGHNESS"),
                                (spc, "", "MP_SPECULAR")):
            if not mel.connect_material_property(
                    node, pin, getattr(unreal.MaterialProperty, prop)):
                problems.append("leaf %s not wired" % prop)
        mel.recompile_material(mat)
        eal.save_loaded_asset(mat, False)

    mi = eal.load_asset(LEAF_INSTANCE)
    if mi is None:
        mi = at.create_asset("MI_LD_Leaf_Maple", MAT_DIR,
                             unreal.MaterialInstanceConstant,
                             unreal.MaterialInstanceConstantFactoryNew())
    mel.set_material_instance_parent(mi, mat)
    for pname, tpath in (("LeafColor", LEAF_COLOR_TEX),
                         ("LeafOpacity", LEAF_OPACITY_TEX)):
        t = eal.load_asset(tpath)
        if t is None:
            problems.append("missing texture %s" % tpath)
            continue
        mel.set_material_instance_texture_parameter_value(mi, pname, t)
        got = mel.get_material_instance_texture_parameter_value(mi, pname)
        if got is None or tpath.split("/")[-1] not in str(got.get_path_name()):
            problems.append("%s did not take %s" % (pname, tpath))
    eal.save_loaded_asset(mi, False)

    bark = eal.load_asset(BARK_INSTANCE)
    if bark is None:
        bark = at.create_asset("MI_LD_Bark", MAT_DIR,
                               unreal.MaterialInstanceConstant,
                               unreal.MaterialInstanceConstantFactoryNew())
        surf = eal.load_asset(MAT_DIR + "/M_LD_Surface")
        if surf is not None:
            mel.set_material_instance_parent(bark, surf)
        bt = eal.load_asset(BARK_TEX)
        if bt is not None:
            mel.set_material_instance_texture_parameter_value(bark, "Albedo", bt)
        mel.set_material_instance_scalar_parameter_value(bark, "SurfaceTilingCm", 120.0)
        eal.save_loaded_asset(bark, False)

    return {"leaf_master": LEAF_MASTER, "leaf_instance": LEAF_INSTANCE,
            "bark_instance": BARK_INSTANCE, "problems": problems}



def _set_materials(sm, materials) -> None:
    """Replace a StaticMesh's material slots outright.

    ``StaticMesh.add_material`` APPENDS. Rebuilding an asset that already had
    slots therefore left it with bark, leaf, bark, leaf -- and grew by one pair
    on every subsequent run. Assigning ``static_materials`` replaces the list,
    so a rebuild is idempotent.
    """
    slots = []
    for m in materials:
        slot = unreal.StaticMaterial()
        slot.set_editor_property("material_interface", m)
        slots.append(slot)
    sm.set_editor_property("static_materials", slots)

def build_tree_mesh(doc: dict, *, asset_name: str) -> dict:
    """Build one ``tree_mesh_v1`` document into ``/Game/LD/Meshes/<asset_name>``."""
    eal = unreal.EditorAssetLibrary
    at = unreal.AssetToolsHelpers.get_asset_tools()
    path = "%s/%s" % (MESH_DIR, asset_name)

    verts = doc["vertices"]
    tris = doc["triangles"]
    uvs = doc.get("uvs") or []
    slots = doc["material_slot_per_triangle"]
    if len(slots) != len(tris):
        raise ValueError("material_slot_per_triangle has %d entries for %d triangles"
                         % (len(slots), len(tris)))

    sm = eal.load_asset(path)
    if sm is None:
        # no StaticMeshFactoryNew exists in this build; None is the factory
        sm = at.create_asset(asset_name, MESH_DIR, unreal.StaticMesh, None)
    smd = sm.create_static_mesh_description()

    groups = {}
    for slot in sorted(set(int(s) for s in slots)):
        g = smd.create_polygon_group()
        smd.set_polygon_group_material_slot_name(g, "slot%d" % slot)
        groups[slot] = g

    vids = []
    for v in verts:
        vid = smd.create_vertex()
        smd.set_vertex_position(vid, unreal.Vector(float(v[0]), float(v[1]), float(v[2])))
        vids.append(vid)

    made = 0
    for tri, slot in zip(tris, slots):
        ins = []
        for corner, vi in enumerate(tri):
            inst = smd.create_vertex_instance(vids[int(vi)])
            if int(vi) < len(uvs):
                uv = uvs[int(vi)]
                smd.set_vertex_instance_uv(
                    inst, unreal.Vector2D(float(uv[0]), float(uv[1])), 0)
            ins.append(inst)
        smd.create_triangle(groups[int(slot)], ins)
        made += 1

    sm.build_from_static_mesh_descriptions([smd], False)
    # set, do not append: add_material() APPENDS, so rebuilding an existing
    # asset left it with bark, leaf, bark, leaf and one more pair every run.
    _set_materials(sm, [eal.load_asset(BARK_INSTANCE), eal.load_asset(LEAF_INSTANCE)])
    eal.save_loaded_asset(sm, False)
    return {"asset": path, "vertices": len(verts), "triangles_requested": len(tris),
            "triangles_made": made, "triangles_built": sm.get_num_triangles(0),
            "sections": sm.get_num_sections(0)}
