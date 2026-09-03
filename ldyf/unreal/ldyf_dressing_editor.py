"""Spawn the ``dressing_v1`` document into the level (editor side).

Runs inside the Unreal editor over remote execution. Everything it places is
addressed by a label prefix so it can be cleared and rebuilt idempotently, and
every placement height follows the Phase 2 contact law — a prop's Z comes from
the mesh's own bounding box, never from a typed offset:

    root_z = surface_z + (root_z_local - bounds_bottom_local) - bury_cm

Road paint is drawn with deferred decals, which is how paint is done in a real
production: the marking projects onto whatever road surface is beneath it, so a
line cannot drift off the asphalt the way a separately-placed quad can. The
decal material is generated here from Unreal's own material graph API, so no
engine blockout mesh (``/Engine/BasicShapes/*``) is used anywhere.

Props are placed as ``InstancedStaticMeshComponent`` instances grouped by mesh,
one grouping actor per family, so 1,000+ pieces of street furniture cost a
handful of actors and draw calls.
"""
import json
from pathlib import Path

import unreal  # type: ignore[import-not-found]

MAT_DIR = "/Game/LD/Materials"
PAINT_MASTER = MAT_DIR + "/M_LD_Paint"
PAINT_WHITE = MAT_DIR + "/MI_LD_Paint_White"
PAINT_YELLOW = MAT_DIR + "/MI_LD_Paint_Yellow"

MARK_PREFIX = "LD_Mark"
CROSSWALK_PREFIX = "LD_Crosswalk"
SIGNAL_PREFIX = "LD_Signal"
TREE_PREFIX = "LD_Tree"
FURNITURE_PREFIX = "LD_Furniture"
CLOSURE_PREFIX = "LD_ClosureProp"

DRESSING_PREFIXES = (MARK_PREFIX, CROSSWALK_PREFIX, SIGNAL_PREFIX,
                     TREE_PREFIX, FURNITURE_PREFIX, CLOSURE_PREFIX)

PAINT_COLOURS = {
    "white": (0.92, 0.92, 0.90),
    "yellow": (0.86, 0.66, 0.08),
}

# Meshes chosen from `prop_probe.json`: only meshes whose material slots all
# resolve (the StopLight A/C/D/E variants each have one null slot and are
# excluded), and, for trees, only the street-scale variants — the 12.8 m
# Alder_B canopy and the 1.96 m root flare of Maple_Red_A are park trees.
SIGNAL_MESH = {
    "traffic_light": "/Game/Prop/Kit_StreetLamp_A/Mesh/SM_StreetLamp_A_StopLight_B",
    "stop_sign": "/Game/Prop/Kit_StopSign_A/Mesh/SM_StopSign_A",
}
TREE_MESHES = [
    "/Game/Prop/Kit_Tree_Birch/Mesh/SM_Tree_Birch_f",
    "/Game/Prop/Kit_Tree_Birch/Mesh/SM_Tree_Birch_g",
    "/Game/Prop/Kit_Tree_Birch/Mesh/SM_Tree_Birch_h",
    "/Game/Prop/Kit_Tree_Maple_Sugar/Mesh/Tree_Maple_A",
]
TREE_BASE_MESH = "/Game/Prop/Kit_TreeBase_A/Mesh/SM_TreeBase_Circle_A"
FURNITURE_MESH = {
    "lamp": ["/Game/Prop/Kit_StreetLamp_A/Mesh/SM_StreetLamp_A_Pole_Large"],
    "bin": ["/Game/Prop/Kit_Trashcan_A/Mesh/SM_Trashcan_A_01"],
    "sign": ["/Game/Prop/Kit_bench_RR/mesh/SM_street_bench",
             "/Game/Prop/Kit_bench_RR/mesh/SM_park_bench_N01"],
}
CLOSURE_MESH = {
    "barricade": "/Game/Prop/Kit_Barricade_A/Mesh/SM_Barricade_A",
    "cone": "/Game/Prop/Kit_ConstructionCone_RR/Mesh/SM_ConstCone_a_N1",
}

TREE_BURY_CM = 10.0        # a street tree's root flare sits just below grade
DECAL_DEPTH_CM = 60.0      # projection depth; deep enough for the kerb camber


# --------------------------------------------------------------------------- helpers

def _eas():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def _add_component(actor, cls):
    sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    handles = sub.k2_gather_subobject_data_for_instance(actor)
    params = unreal.AddNewSubobjectParams(parent_handle=handles[0], new_class=cls,
                                          blueprint_context=None)
    handle, fail = sub.add_new_subobject(params)
    obj = unreal.SubobjectDataBlueprintFunctionLibrary.get_associated_object(
        sub.k2_find_subobject_data_from_handle(handle))
    if obj is None:
        raise RuntimeError("add_new_subobject(%s) gave no object: %s" % (cls, fail))
    return obj


def _spawn(label, tags=()):
    a = _eas().spawn_actor_from_class(unreal.Actor, unreal.Vector(0, 0, 0),
                                      unreal.Rotator(0, 0, 0))
    a.set_actor_label(label)
    if tags:
        a.set_editor_property("tags", [unreal.Name(t) for t in tags])
    return a


def clear_dressing(prefixes=DRESSING_PREFIXES) -> dict:
    """Delete every actor this module owns, so a rebuild is idempotent."""
    eas = _eas()
    removed = 0
    for a in list(eas.get_all_level_actors()):
        if a is None:
            continue
        lab = str(a.get_actor_label())
        if any(lab.startswith(p) for p in prefixes):
            eas.destroy_actor(a)
            removed += 1
    return {"removed": removed, "prefixes": list(prefixes)}


def contact_offset_cm(mesh) -> float:
    """``root_z - bounds_bottom_z`` for a static mesh, in its own local space.

    This is the same law the people and vehicles use. It is measured from the
    asset, so a mesh authored with its origin at the centre and one authored
    with its origin at the base both land on the ground.
    """
    bb = mesh.get_bounding_box()
    return -float(bb.min.z)


# --------------------------------------------------------------------------- materials

def ensure_paint_materials() -> dict:
    """Create (once) the deferred-decal paint master and its colour instances."""
    at = unreal.AssetToolsHelpers.get_asset_tools()
    mel = unreal.MaterialEditingLibrary
    eal = unreal.EditorAssetLibrary
    made = []
    m = eal.load_asset(PAINT_MASTER)
    if m is None:
        m = at.create_asset("M_LD_Paint", MAT_DIR, unreal.Material, unreal.MaterialFactoryNew())
        m.set_editor_property("material_domain", unreal.MaterialDomain.MD_DEFERRED_DECAL)
        m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
        c = mel.create_material_expression(m, unreal.MaterialExpressionVectorParameter, -400, 0)
        c.set_editor_property("parameter_name", "PaintColor")
        c.set_editor_property("default_value", unreal.LinearColor(0.92, 0.92, 0.90, 1.0))
        mel.connect_material_property(c, "", unreal.MaterialProperty.MP_BASE_COLOR)
        o = mel.create_material_expression(m, unreal.MaterialExpressionScalarParameter, -400, 200)
        o.set_editor_property("parameter_name", "PaintOpacity")
        o.set_editor_property("default_value", 1.0)
        mel.connect_material_property(o, "", unreal.MaterialProperty.MP_OPACITY)
        r = mel.create_material_expression(m, unreal.MaterialExpressionScalarParameter, -400, 400)
        r.set_editor_property("parameter_name", "PaintRoughness")
        r.set_editor_property("default_value", 0.55)
        mel.connect_material_property(r, "", unreal.MaterialProperty.MP_ROUGHNESS)
        mel.recompile_material(m)
        eal.save_loaded_asset(m, False)
        made.append(PAINT_MASTER)
    for path, colour in ((PAINT_WHITE, "white"), (PAINT_YELLOW, "yellow")):
        mi = eal.load_asset(path)
        if mi is None:
            name = path.rsplit("/", 1)[1]
            mi = at.create_asset(name, MAT_DIR, unreal.MaterialInstanceConstant,
                                 unreal.MaterialInstanceConstantFactoryNew())
            made.append(path)
        mel.set_material_instance_parent(mi, m)
        r, g, b = PAINT_COLOURS[colour]
        mel.set_material_instance_vector_parameter_value(
            mi, "PaintColor", unreal.LinearColor(r, g, b, 1.0))
        eal.save_loaded_asset(mi, False)
    return {"master": PAINT_MASTER, "instances": [PAINT_WHITE, PAINT_YELLOW], "created": made}


# --------------------------------------------------------------------------- paint

def _decal(actor, mat, x, y, z, yaw, half_width_cm, half_length_cm, sort_order):
    d = _add_component(actor, unreal.DecalComponent)
    d.set_decal_material(mat)
    d.set_editor_property("decal_size",
                          unreal.Vector(DECAL_DEPTH_CM, half_width_cm, half_length_cm))
    d.set_editor_property("sort_order", int(sort_order))
    d.set_relative_location(unreal.Vector(x, y, z), False, False)
    # A decal projects along its local -X. Pitching -90 aims it at the ground;
    # the local Z axis then lies along `yaw`, which is the line's direction, and
    # the local Y axis is across it. Hence size = (depth, half width, half length).
    d.set_relative_rotation(unreal.Rotator(0.0, -90.0, float(yaw)), False, False)
    return d


def build_markings(dressing_path, *, z_cm, label_prefix=MARK_PREFIX) -> dict:
    """One actor per road edge carrying every painted line on that edge."""
    doc = json.loads(Path(dressing_path).read_text(encoding="utf-8"))
    eal = unreal.EditorAssetLibrary
    mats = {"white": eal.load_asset(PAINT_WHITE), "yellow": eal.load_asset(PAINT_YELLOW)}
    missing = [k for k, v in mats.items() if v is None]
    if missing:
        raise RuntimeError("paint material instances missing: %s" % missing)
    by_edge = {}
    for row in doc["lane_markings"]:
        by_edge.setdefault(str(row["edge_id"]), []).append(row)
    made = {"actors": 0, "decals": 0, "by_kind": {}}
    for eid in sorted(by_edge):
        a = _spawn("%s_%s" % (label_prefix, eid.replace(":", "_")),
                   tags=("ld_dressing", "ld_marking", "edge:%s" % eid))
        for i, row in enumerate(sorted(by_edge[eid], key=lambda r: r["id"])):
            _decal(a, mats[row["colour"]],
                   float(row["centre_x"]), float(row["centre_y"]), float(z_cm),
                   float(row["yaw"]),
                   float(row["width_cm"]) / 2.0,
                   float(row["length_cm"]) / 2.0,
                   sort_order=2 if row["kind"] == "centre_line" else 1)
            made["decals"] += 1
            k = row["kind"]
            made["by_kind"][k] = made["by_kind"].get(k, 0) + 1
        made["actors"] += 1
    return made


def build_crosswalks(dressing_path, *, z_cm, label_prefix=CROSSWALK_PREFIX) -> dict:
    """One actor per crossing carrying its zebra stripes."""
    doc = json.loads(Path(dressing_path).read_text(encoding="utf-8"))
    mat = unreal.EditorAssetLibrary.load_asset(PAINT_WHITE)
    if mat is None:
        raise RuntimeError("white paint instance missing")
    by_edge = {}
    for row in doc["crosswalk_stripes"]:
        by_edge.setdefault(str(row["edge_id"]), []).append(row)
    made = {"actors": 0, "stripes": 0}
    for eid in sorted(by_edge):
        a = _spawn("%s_%s" % (label_prefix, eid.replace(":", "_")),
                   tags=("ld_dressing", "ld_crosswalk", "edge:%s" % eid))
        for row in sorted(by_edge[eid], key=lambda r: r["id"]):
            # A stripe is `size_along_cm` across the crossing's span and
            # `size_across_cm` deep along the direction cars drive. `yaw` runs
            # along the span, so half length = half of the along-span size.
            _decal(a, mat, float(row["x"]), float(row["y"]), float(z_cm), float(row["yaw"]),
                   half_width_cm=float(row["size_across_cm"]) / 2.0,
                   half_length_cm=float(row["size_along_cm"]) / 2.0,
                   sort_order=3)
            made["stripes"] += 1
        made["actors"] += 1
    return made


# --------------------------------------------------------------------------- props

def _digest(key: str, n: int) -> int:
    import hashlib
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % max(1, n)


def _ism_group(label, tags, mesh_paths):
    """A grouping actor with one InstancedStaticMeshComponent per mesh."""
    eal = unreal.EditorAssetLibrary
    a = _spawn(label, tags=tags)
    comps = {}
    offsets = {}
    for p in mesh_paths:
        m = eal.load_asset(p)
        if m is None:
            continue
        c = _add_component(a, unreal.InstancedStaticMeshComponent)
        c.set_static_mesh(m)
        c.set_editor_property("mobility", unreal.ComponentMobility.STATIC)
        comps[p] = c
        offsets[p] = contact_offset_cm(m)
    return a, comps, offsets


def _add_instance(comp, x, y, z, yaw, scale=1.0):
    t = unreal.Transform(unreal.Vector(float(x), float(y), float(z)),
                         unreal.Rotator(0.0, 0.0, float(yaw)),
                         unreal.Vector(scale, scale, scale))
    comp.add_instance(t, True)


def build_signals(dressing_path, *, surface_z_cm, label_prefix=SIGNAL_PREFIX) -> dict:
    doc = json.loads(Path(dressing_path).read_text(encoding="utf-8"))
    rows = doc["signals"]
    a, comps, offsets = _ism_group(label_prefix, ("ld_dressing", "ld_signal"),
                                   [SIGNAL_MESH[k] for k in sorted(SIGNAL_MESH)])
    made = {"placed": 0, "by_kind": {}, "missing_mesh": [], "contact_offsets": {}}
    for row in sorted(rows, key=lambda r: r["id"]):
        path = SIGNAL_MESH.get(row["kind"])
        c = comps.get(path)
        if c is None:
            made["missing_mesh"].append(row["kind"])
            continue
        _add_instance(c, row["x"], row["y"], surface_z_cm + offsets[path], row["yaw"])
        made["placed"] += 1
        made["by_kind"][row["kind"]] = made["by_kind"].get(row["kind"], 0) + 1
    made["contact_offsets"] = {k: round(v, 3) for k, v in offsets.items()}
    made["actor"] = str(a.get_actor_label())
    return made


def build_trees(dressing_path, *, surface_z_cm, label_prefix=TREE_PREFIX,
                bury_cm=TREE_BURY_CM) -> dict:
    doc = json.loads(Path(dressing_path).read_text(encoding="utf-8"))
    rows = doc["trees"]
    a, comps, offsets = _ism_group(label_prefix, ("ld_dressing", "ld_tree"),
                                   TREE_MESHES + [TREE_BASE_MESH])
    made = {"placed": 0, "bases": 0, "variants": {}, "contact_offsets": {}}
    for row in sorted(rows, key=lambda r: r["id"]):
        pick = TREE_MESHES[_digest(row["id"] + "|tree", len(TREE_MESHES))]
        c = comps.get(pick)
        if c is None:
            continue
        # deterministic size variation so a street is not a row of clones
        scale = 0.85 + 0.30 * (_digest(row["id"] + "|scale", 7) / 6.0)
        yaw = float(_digest(row["id"] + "|yaw", 360))
        _add_instance(c, row["x"], row["y"],
                      surface_z_cm + offsets[pick] - bury_cm, yaw, scale)
        made["placed"] += 1
        made["variants"][pick] = made["variants"].get(pick, 0) + 1
        base = comps.get(TREE_BASE_MESH)
        if base is not None:
            _add_instance(base, row["x"], row["y"],
                          surface_z_cm + offsets[TREE_BASE_MESH], yaw)
            made["bases"] += 1
    made["contact_offsets"] = {k: round(v, 3) for k, v in offsets.items()}
    made["actor"] = str(a.get_actor_label())
    made["bury_cm"] = bury_cm
    return made


def build_furniture(layout_path, *, surface_z_cm, label_prefix=FURNITURE_PREFIX) -> dict:
    """Lamp posts, bins and benches at the ``city_layout`` furniture slots."""
    layout = json.loads(Path(layout_path).read_text(encoding="utf-8"))
    slots = layout["furniture_slots"]["slots"]
    paths = sorted({p for v in FURNITURE_MESH.values() for p in v})
    a, comps, offsets = _ism_group(label_prefix, ("ld_dressing", "ld_furniture"), paths)
    made = {"placed": 0, "by_kind": {}, "unknown_kinds": [], "contact_offsets": {}}
    for row in sorted(slots, key=lambda r: (str(r["lane_id"]), float(r["distance_cm"]))):
        kind = str(row["kind"])
        options = FURNITURE_MESH.get(kind)
        if not options:
            if kind not in made["unknown_kinds"]:
                made["unknown_kinds"].append(kind)
            continue
        key = "%s|%s|%s" % (row["lane_id"], row["distance_cm"], kind)
        pick = options[_digest(key, len(options))]
        c = comps.get(pick)
        if c is None:
            continue
        _add_instance(c, row["x"], row["y"], surface_z_cm + offsets[pick], row["yaw"])
        made["placed"] += 1
        made["by_kind"][kind] = made["by_kind"].get(kind, 0) + 1
    made["contact_offsets"] = {k: round(v, 3) for k, v in offsets.items()}
    made["actor"] = str(a.get_actor_label())
    return made


def build_closure_props(dressing_path, *, surface_z_cm, label_prefix=CLOSURE_PREFIX) -> dict:
    """Barricades and cones across the edges the sealed rule closes."""
    doc = json.loads(Path(dressing_path).read_text(encoding="utf-8"))
    rows = doc["closure_props"]
    a, comps, offsets = _ism_group(label_prefix, ("ld_dressing", "ld_closure"),
                                   [CLOSURE_MESH[k] for k in sorted(CLOSURE_MESH)])
    made = {"placed": 0, "by_kind": {}, "contact_offsets": {}, "barricade_scale": {}}
    for row in sorted(rows, key=lambda r: r["id"]):
        path = CLOSURE_MESH.get(row["kind"])
        c = comps.get(path)
        if c is None:
            continue
        scale = 1.0
        if row["kind"] == "barricade":
            # the barricade mesh is 233.8 cm wide; stretch it to the measured
            # carriageway span so the road is actually blocked, not decorated
            mesh = unreal.EditorAssetLibrary.load_asset(path)
            bb = mesh.get_bounding_box()
            width = float(bb.max.x - bb.min.x)
            scale = float(row["span_cm"]) / width if width > 0 else 1.0
            made["barricade_scale"][row["id"]] = round(scale, 4)
        t = unreal.Transform(
            unreal.Vector(float(row["x"]), float(row["y"]), surface_z_cm + offsets[path]),
            unreal.Rotator(0.0, 0.0, float(row["yaw"])),
            unreal.Vector(scale if row["kind"] == "barricade" else 1.0, 1.0, 1.0))
        c.add_instance(t, True)
        made["placed"] += 1
        made["by_kind"][row["kind"]] = made["by_kind"].get(row["kind"], 0) + 1
    made["contact_offsets"] = {k: round(v, 3) for k, v in offsets.items()}
    made["actor"] = str(a.get_actor_label())
    return made


def dressing_summary() -> dict:
    """Count what is actually in the level under this module's prefixes."""
    out = {"actors": {}, "components": {}, "instances": 0, "decals": 0}
    for a in _eas().get_all_level_actors():
        if a is None:
            continue
        lab = str(a.get_actor_label())
        pref = next((p for p in DRESSING_PREFIXES if lab.startswith(p)), None)
        if pref is None:
            continue
        out["actors"][pref] = out["actors"].get(pref, 0) + 1
        for c in a.get_components_by_class(unreal.ActorComponent):
            cn = str(c.get_class().get_name())
            out["components"][cn] = out["components"].get(cn, 0) + 1
            if isinstance(c, unreal.InstancedStaticMeshComponent):
                out["instances"] += int(c.get_instance_count())
            if isinstance(c, unreal.DecalComponent):
                out["decals"] += 1
    return out
