"""Replace the PCG-extruded blockout masses with real authored building geometry.

Until now a building was a closed spline tagged for PCG, which extruded it into
a single box wearing one facade material. `ldyf/building_kits.py` has described
six facade families, height banding, setbacks, ground-floor entrances, roof
materials and a civic landmark for a while, and none of it reached the world
because nothing turned that description into geometry. `ldyf/building_geometry.py`
does, and this executes it.

One StaticMesh per BLOCK, not per building. 252 separate mesh assets and 252
actors would be a lot of bookkeeping for no gain; a block's buildings never move
relative to one another, so they are welded into one mesh with shared material
slots. That keeps the actor count near where it already was and lets a whole
block draw in a handful of calls.

Material slots follow `building_geometry`'s constant order:
``0 = wall, 1 = roof, 2 = ground floor, 3 = parapet``. The wall slot takes the
building's assigned facade family, so neighbouring blocks differ; the roof slot
takes a real roof material. Getting slot 1 wrong is how the roof-banding defect
happened before, so the driver asserts the slot count it received rather than
trusting it.
"""
from __future__ import annotations

import unreal  # type: ignore[import-not-found]

MESH_DIR = "/Game/LD/Meshes"
MAT_DIR = "/Game/LD/Materials"
PREFIX = "LD_BldgMesh"
SLOT_WALL, SLOT_ROOF, SLOT_GROUND, SLOT_PARAPET = 0, 1, 2, 3
SLOT_COUNT = 4


def _clear(prefix: str) -> int:
    EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    n = 0
    for a in list(EAS.get_all_level_actors()):
        if a is not None and str(a.get_actor_label()).startswith(prefix):
            EAS.destroy_actor(a)
            n += 1
    return n


def hide_pcg_buildings(prefix: str = "LD_Bldg") -> dict:
    """Remove the footprint splines so PCG stops extruding blockout masses.

    Only the ones whose label is exactly the spline prefix -- ``LD_BldgMesh``
    starts with ``LD_Bldg`` too, and destroying the thing we just built would be
    a memorable way to fail.
    """
    EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    removed = []
    for a in list(EAS.get_all_level_actors()):
        if a is None:
            continue
        label = str(a.get_actor_label())
        if label.startswith(prefix) and not label.startswith(PREFIX):
            removed.append(label)
            EAS.destroy_actor(a)
    return {"removed": len(removed), "sample": sorted(removed)[:5]}


def _material_for_slot(slot: int, family_path: str, roof_path: str,
                       ground_path: str, parapet_path: str):
    eal = unreal.EditorAssetLibrary
    return eal.load_asset({SLOT_WALL: family_path, SLOT_ROOF: roof_path,
                           SLOT_GROUND: ground_path,
                           SLOT_PARAPET: parapet_path}[slot])


def build_block_mesh(block_id: str, buildings: list, *,
                     roof_path: str, ground_path: str, parapet_path: str,
                     family_paths: dict) -> dict:
    """Weld one block's building meshes into a single StaticMesh.

    ``buildings`` is a list of ``{"id", "family", "geometry"}`` where geometry is
    a ``building_geometry_v1`` document.
    """
    eal = unreal.EditorAssetLibrary
    at = unreal.AssetToolsHelpers.get_asset_tools()
    name = "SM_LD_Block_%s" % block_id.replace("/", "_")
    path = "%s/%s" % (MESH_DIR, name)
    sm = eal.load_asset(path)
    if sm is None:
        # no StaticMeshFactoryNew exists in this build; None is the factory
        sm = at.create_asset(name, MESH_DIR, unreal.StaticMesh, None)
    smd = sm.create_static_mesh_description()

    # One polygon group per (slot, family) pair, because the wall slot's
    # material differs per building while roof/ground/parapet are shared.
    groups: dict = {}
    order: list = []

    def group_for(slot: int, family: str):
        key = (slot, family if slot == SLOT_WALL else "")
        if key not in groups:
            g = smd.create_polygon_group()
            smd.set_polygon_group_material_slot_name(
                g, "s%d_%s" % (slot, key[1] or "shared"))
            groups[key] = g
            order.append(key)
        return groups[key]

    tris = 0
    problems: list = []
    for b in buildings:
        doc = b["geometry"]
        slots = doc["material_slot_per_triangle"]
        verts = doc["vertices"]
        uvs = doc.get("uvs") or []
        if len(slots) != len(doc["triangles"]):
            problems.append("%s: %d slots for %d triangles"
                            % (b["id"], len(slots), len(doc["triangles"])))
            continue
        bad = [s for s in slots if int(s) not in (0, 1, 2, 3)]
        if bad:
            problems.append("%s: slot ids outside 0-3: %s" % (b["id"], sorted(set(bad))[:4]))
            continue
        vids = []
        for v in verts:
            vid = smd.create_vertex()
            smd.set_vertex_position(vid, unreal.Vector(float(v[0]), float(v[1]), float(v[2])))
            vids.append(vid)
        for tri, slot in zip(doc["triangles"], slots):
            ins = []
            for vi in tri:
                inst = smd.create_vertex_instance(vids[int(vi)])
                if int(vi) < len(uvs):
                    uv = uvs[int(vi)]
                    smd.set_vertex_instance_uv(
                        inst, unreal.Vector2D(float(uv[0]), float(uv[1])), 0)
                ins.append(inst)
            smd.create_triangle(group_for(int(slot), b["family"]), ins)
            tris += 1

    sm.build_from_static_mesh_descriptions([smd], False)
    for slot, family in order:
        fam_path = family_paths.get(family) or next(iter(family_paths.values()))
        sm.add_material(_material_for_slot(slot, fam_path, roof_path,
                                           ground_path, parapet_path))
    eal.save_loaded_asset(sm, False)
    return {"asset": path, "block": block_id, "buildings": len(buildings),
            "triangles": tris, "built": sm.get_num_triangles(0),
            "sections": sm.get_num_sections(0), "slot_groups": len(order),
            "problems": problems}


def build_buildings(blocks: dict, *, roof_path: str, ground_path: str,
                    parapet_path: str, family_paths: dict,
                    z_cm: float = 0.0, replace_pcg: bool = True) -> dict:
    """Build every block's mesh and spawn it; optionally drop the PCG splines."""
    EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    eal = unreal.EditorAssetLibrary
    removed_meshes = _clear(PREFIX)
    out = {"removed_previous": removed_meshes, "blocks": [], "problems": []}

    for block_id in sorted(blocks):
        info = build_block_mesh(block_id, blocks[block_id], roof_path=roof_path,
                                ground_path=ground_path, parapet_path=parapet_path,
                                family_paths=family_paths)
        out["problems"] += ["%s: %s" % (block_id, p) for p in info.pop("problems")]
        sm = eal.load_asset(info["asset"])
        actor = EAS.spawn_actor_from_object(sm, unreal.Vector(0, 0, z_cm),
                                            unreal.Rotator(0, 0, 0))
        actor.set_actor_label("%s_%s" % (PREFIX, block_id))
        actor.set_editor_property("tags", ["ld_building", "block:%s" % block_id])
        out["blocks"].append(info)

    if replace_pcg:
        out["pcg_splines"] = hide_pcg_buildings()
    out["total_triangles"] = sum(b["triangles"] for b in out["blocks"])
    out["total_buildings"] = sum(b["buildings"] for b in out["blocks"])
    return out
