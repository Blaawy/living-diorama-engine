"""Give the crowd visible skin and clothes.

Why the crowd renders as silhouettes
------------------------------------
Every person's body slot carries ``M_BodySynthesized``, a child of City Sample's
``M_Crowd_BodySkin``. That material expects textures the crowd system
*synthesizes* at runtime for each agent. These people are spawned as ordinary
actors driven by a Level Sequence, not through the crowd system, so nothing ever
binds those textures and the body has no albedo to show. It is the same class of
fault as the ground that rendered as speckle for a whole work session: a
material whose inputs are missing does not fail loudly, it just renders wrong.

The fix that worked there works here: **own the material.** Two small masters are
authored from the material graph API, and the City Sample clothing instances --
whose parameter names this project has never verified -- are replaced outright
rather than driven blind. An unverified parameter name that silently does
nothing is precisely how the defect survived a whole revision.

Asset economy: one material instance per *skin tone* and per *garment colour*,
not one per person. 65 people over 8 tones is 8 instances, not 65.
"""
from __future__ import annotations

import unreal  # type: ignore[import-not-found]

MAT_DIR = "/Game/LD/Materials"
SKIN_MASTER = MAT_DIR + "/M_LD_Skin"
CLOTH_MASTER = MAT_DIR + "/M_LD_Cloth"

# Which garment colour drives which clothing slot. The slot is identified by the
# name of the material already on it, because slot indices differ between the
# male and female bodies and an index-based mapping would dress people wrongly
# on one of them.
SLOT_COLOUR = {
    "shirt": "shirt_rgb",
    "jacket": "shirt_rgb",
    "pants": "trousers_rgb",
    "trouser": "trousers_rgb",
    "boots": "shoes_rgb",
    "shoe": "shoes_rgb",
    "gloves": "skin_rgb",
    "belt": "shoes_rgb",
    "hair": "hair_rgb",
    # City Sample also ships outfit_top/outfit_bottom on some bodies; without
    # these two the corresponding people keep an undriveable City Sample
    # material and stay grey while everyone around them is dressed.
    "outfit_bottom": "trousers_rgb",
    "outfit_top": "shirt_rgb",
    "outfit": "shirt_rgb",
}


def _linear(rgb):
    return unreal.LinearColor(float(rgb[0]), float(rgb[1]), float(rgb[2]), 1.0)


def ensure_masters() -> dict:
    """Create the skin and cloth masters if absent. Idempotent."""
    eal = unreal.EditorAssetLibrary
    at = unreal.AssetToolsHelpers.get_asset_tools()
    mel = unreal.MaterialEditingLibrary
    out = {}

    skin = eal.load_asset(SKIN_MASTER)
    if skin is None:
        skin = at.create_asset("M_LD_Skin", MAT_DIR, unreal.Material,
                               unreal.MaterialFactoryNew())
        # Skin with no subsurface term reads as plastic, or as a silhouette at
        # the distances this crowd is seen from.
        skin.set_editor_property("shading_model",
                                 unreal.MaterialShadingModel.MSM_SUBSURFACE)
        for name, default, prop in (
                ("SkinColor", (0.42, 0.28, 0.21), "MP_BASE_COLOR"),
                ("SkinSubsurface", (0.60, 0.20, 0.16), "MP_SUBSURFACE_COLOR")):
            n = mel.create_material_expression(
                skin, unreal.MaterialExpressionVectorParameter, -700,
                -150 if prop == "MP_BASE_COLOR" else 60)
            n.set_editor_property("parameter_name", name)
            n.set_editor_property("default_value", _linear(default))
            mel.connect_material_property(n, "", getattr(unreal.MaterialProperty, prop))
        for name, default, prop in (("SkinOpacity", 0.35, "MP_OPACITY"),
                                    ("SkinRoughness", 0.55, "MP_ROUGHNESS"),
                                    ("SkinSpecular", 0.35, "MP_SPECULAR")):
            n = mel.create_material_expression(
                skin, unreal.MaterialExpressionScalarParameter, -700, 270)
            n.set_editor_property("parameter_name", name)
            n.set_editor_property("default_value", float(default))
            mel.connect_material_property(n, "", getattr(unreal.MaterialProperty, prop))
        mel.recompile_material(skin)
        eal.save_loaded_asset(skin, False)
    out["skin_master"] = SKIN_MASTER

    cloth = eal.load_asset(CLOTH_MASTER)
    if cloth is None:
        cloth = at.create_asset("M_LD_Cloth", MAT_DIR, unreal.Material,
                                unreal.MaterialFactoryNew())
        c = mel.create_material_expression(
            cloth, unreal.MaterialExpressionVectorParameter, -700, -100)
        c.set_editor_property("parameter_name", "ClothColor")
        c.set_editor_property("default_value", _linear((0.3, 0.3, 0.34)))
        mel.connect_material_property(c, "", unreal.MaterialProperty.MP_BASE_COLOR)
        r = mel.create_material_expression(
            cloth, unreal.MaterialExpressionScalarParameter, -700, 120)
        r.set_editor_property("parameter_name", "ClothRoughness")
        r.set_editor_property("default_value", 0.78)
        mel.connect_material_property(r, "", unreal.MaterialProperty.MP_ROUGHNESS)
        s = mel.create_material_expression(
            cloth, unreal.MaterialExpressionScalarParameter, -700, 220)
        s.set_editor_property("parameter_name", "ClothSpecular")
        s.set_editor_property("default_value", 0.18)
        mel.connect_material_property(s, "", unreal.MaterialProperty.MP_SPECULAR)
        mel.recompile_material(cloth)
        eal.save_loaded_asset(cloth, False)
    out["cloth_master"] = CLOTH_MASTER
    return out


def _instance(name: str, master, params_vec: dict, params_scalar: dict):
    """Create-or-reuse one material instance and set its parameters."""
    eal = unreal.EditorAssetLibrary
    at = unreal.AssetToolsHelpers.get_asset_tools()
    mel = unreal.MaterialEditingLibrary
    path = "%s/%s" % (MAT_DIR, name)
    mi = eal.load_asset(path)
    if mi is None:
        mi = at.create_asset(name, MAT_DIR, unreal.MaterialInstanceConstant,
                             unreal.MaterialInstanceConstantFactoryNew())
    mel.set_material_instance_parent(mi, master)
    for k, v in sorted(params_vec.items()):
        mel.set_material_instance_vector_parameter_value(mi, k, _linear(v))
    for k, v in sorted(params_scalar.items()):
        mel.set_material_instance_scalar_parameter_value(mi, k, float(v))
    eal.save_loaded_asset(mi, False)
    return mi


def _key(rgb):
    return "%03d%03d%03d" % (int(round(rgb[0] * 255)), int(round(rgb[1] * 255)),
                             int(round(rgb[2] * 255)))


def apply_crowd(plan: dict, *, label_prefix: str = "LD_CAST") -> dict:
    """Dress every person in the plan. Returns a per-slot account of what stuck."""
    ensure_masters()
    eal = unreal.EditorAssetLibrary
    skin_master = eal.load_asset(SKIN_MASTER)
    cloth_master = eal.load_asset(CLOTH_MASTER)
    EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

    # the spec module calls the list "persons"; accept either rather than
    # silently dressing nobody if that name is ever revised
    people = plan.get("persons") or plan.get("people") or []
    by_uid = {v["uid"]: v for v in people}
    if not by_uid:
        raise ValueError("crowd plan carries no persons; keys were %s" % sorted(plan))
    skin_cache: dict = {}
    cloth_cache: dict = {}
    problems: list = []
    dressed, slots_set, slots_skipped, already_ours = 0, 0, 0, 0
    unmatched_slot_names: set = set()

    for a in EAS.get_all_level_actors():
        if a is None:
            continue
        label = str(a.get_actor_label())
        if not label.startswith(label_prefix):
            continue
        uid = label[len(label_prefix):].lstrip("_")
        v = by_uid.get(uid)
        if v is None:
            problems.append("no plan entry for %s (uid %r)" % (label, uid))
            continue
        comps = a.get_components_by_class(unreal.SkeletalMeshComponent)
        if not comps:
            continue
        comp = comps[0]
        try:
            mats = comp.get_materials()
        except Exception as exc:                               # noqa: BLE001
            problems.append("%s: get_materials failed: %s" % (label, exc))
            continue

        tone_key = v["skin_tone"]
        if tone_key not in skin_cache:
            skin_cache[tone_key] = _instance(
                "MI_LD_Skin_%s" % tone_key, skin_master,
                {"SkinColor": v["skin_rgb"],
                 # transmitted light through skin is redder than its albedo
                 "SkinSubsurface": [min(1.0, v["skin_rgb"][0] * 1.6 + 0.15),
                                    v["skin_rgb"][1] * 0.7,
                                    v["skin_rgb"][2] * 0.6]},
                {"SkinRoughness": v["roughness"], "SkinSpecular": 0.35,
                 "SkinOpacity": v["subsurface"]})
        skin_mi = skin_cache[tone_key]

        for i, m in enumerate(mats):
            name = str(m.get_name()).lower() if m is not None else ""
            if "body" in name or "skin" in name or "head" in name or "face" in name:
                comp.set_material(i, skin_mi)
                slots_set += 1
                continue
            if name.startswith("mi_ld_cloth"):
                # Already wearing one of ours from an earlier application. The
                # original City Sample slot name is gone, so the garment kind
                # can no longer be inferred and the slot is left alone rather
                # than mis-coloured. NOTE: this driver is therefore NOT
                # idempotent in the strong sense -- a second run cannot re-dress
                # a body it already dressed. To change the palette, restore the
                # level's crowd materials first.
                already_ours += 1
                continue
            colour_key = None
            for token, field in SLOT_COLOUR.items():
                if token in name:
                    colour_key = field
                    break
            if colour_key is None:
                slots_skipped += 1
                if name:
                    unmatched_slot_names.add(name)
                continue
            rgb = v[colour_key]
            ck = _key(rgb)
            if ck not in cloth_cache:
                cloth_cache[ck] = _instance(
                    "MI_LD_Cloth_%s" % ck, cloth_master,
                    {"ClothColor": rgb}, {"ClothRoughness": 0.78})
            comp.set_material(i, cloth_cache[ck])
            slots_set += 1
        dressed += 1

    return {"dressed": dressed, "slots_set": slots_set,
            "slots_skipped": slots_skipped, "already_ours": already_ours,
            # Named rather than counted: a slot this driver did not recognise is
            # a person still wearing a City Sample material we cannot drive, and
            # that is exactly the failure mode being fixed.
            "unmatched_slot_names": sorted(unmatched_slot_names),
            "skin_instances": sorted(skin_cache),
            "cloth_instances": len(cloth_cache),
            "problems": problems}
