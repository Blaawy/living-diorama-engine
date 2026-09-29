"""Spawn `street_life_placement_v1` rows as instanced static meshes.

`ldyf/street_life.py` decides where storefront treatment, signs, rooftop props
and parked cars go; `ldyf/street_life_placement.py` decides which mesh each one
wears. This turns those rows into actual instances, one
``InstancedStaticMeshComponent`` per distinct mesh so a few hundred props cost a
handful of draw calls rather than a few hundred actors.

Two lessons from earlier drivers in this project are baked in:

* ``add_material``/``add_instance`` style APIs **append**. Any actor this
  creates is destroyed and rebuilt from scratch, so running it twice gives the
  same world rather than two overlapping copies of the street.
* a row whose mesh fails to load is **reported**, never skipped silently. A
  quietly dropped prop is indistinguishable from a placement bug, and this
  project has already lost a day to a material that failed quietly.
"""
from __future__ import annotations

import unreal  # type: ignore[import-not-found]

PREFIX = "LD_StreetLife"


def _clear(prefix: str) -> int:
    EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    n = 0
    for a in list(EAS.get_all_level_actors()):
        if a is not None and str(a.get_actor_label()).startswith(prefix):
            EAS.destroy_actor(a)
            n += 1
    return n


def _ism_actor(label: str, mesh):
    """One actor carrying one InstancedStaticMeshComponent for `mesh`."""
    EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actor = EAS.spawn_actor_from_class(unreal.Actor, unreal.Vector(0, 0, 0),
                                       unreal.Rotator(0, 0, 0))
    actor.set_actor_label(label)
    actor.set_editor_property("tags", ["ld_street_life"])
    sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    root = sub.k2_gather_subobject_data_for_instance(actor)[0]
    handle, _fail = sub.add_new_subobject(
        unreal.AddNewSubobjectParams(parent_handle=root,
                                     new_class=unreal.InstancedStaticMeshComponent,
                                     blueprint_context=None))
    ism = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(
        sub.k2_find_subobject_data_from_handle(handle))
    ism.set_static_mesh(mesh)
    return actor, ism


def spawn_placement(doc: dict, *, by_mesh: dict) -> dict:
    """Spawn every row. `by_mesh` is `street_life_placement.group_by_mesh` output."""
    eal = unreal.EditorAssetLibrary
    removed = _clear(PREFIX)
    out = {"removed_previous": removed, "components": [], "problems": [],
           "instances": 0, "rows_expected": len(doc.get("rows") or [])}

    for i, mesh_path in enumerate(sorted(by_mesh)):
        rows = by_mesh[mesh_path]
        mesh = eal.load_asset(mesh_path)
        if mesh is None:
            # named, not dropped: a missing mesh is a content problem the
            # reviewer must see, not a silently thinner street
            out["problems"].append("mesh missing, %d rows not spawned: %s"
                                   % (len(rows), mesh_path))
            continue
        label = "%s_%02d_%s" % (PREFIX, i, mesh_path.rsplit("/", 1)[-1])
        _actor, ism = _ism_actor(label, mesh)
        placed = 0
        for r in sorted(rows, key=lambda x: str(x.get("id"))):
            scale = float(r.get("scale", 1.0) or 1.0)
            t = unreal.Transform(
                unreal.Vector(float(r["x"]), float(r["y"]), float(r.get("z_cm", 0.0))),
                unreal.Rotator(0.0, 0.0, float(r.get("yaw_deg", 0.0))),
                unreal.Vector(scale, scale, scale))
            ism.add_instance(t)
            placed += 1
        out["components"].append({"mesh": mesh_path, "label": label,
                                  "instances": placed})
        out["instances"] += placed

    out["rows_unplaced"] = out["rows_expected"] - out["instances"]
    return out
