"""Level-WIDE actor dump (contract C5) — every actor in the level, not only the
ones the player spawned. Runs inside the editor over remote execution.

Writes `level_dump_v1`:
    {"schema_version","level","captured_utc","counts",
     "actors":[{"name","class","label","folder","tags","location":{x,y,z},
                "rotation":{roll,pitch,yaw},
                "components":[{"name","class","asset","asset_lower",
                               "instance_count","anim_class","animation","skeleton"}]}]}
Asset paths are preserved with their original case AND lower-cased, so the
classifier's blockout rule can be case-insensitive without guessing.
"""
import json
import time
from pathlib import Path

import unreal  # type: ignore[import-not-found]

_MESH_PROPS = ("static_mesh", "skeletal_mesh", "skinned_asset")


def _asset_of(comp):
    """The asset a component renders, whatever component class it is."""
    for prop in _MESH_PROPS:
        try:
            a = comp.get_editor_property(prop)
        except Exception:
            continue
        if a is not None:
            return str(a.get_path_name())
    try:
        if isinstance(comp, unreal.SkinnedMeshComponent):
            a = comp.get_skinned_asset()
            if a is not None:
                return str(a.get_path_name())
    except Exception:
        pass
    return None


def _instance_count(comp):
    try:
        if isinstance(comp, unreal.InstancedStaticMeshComponent):
            return int(comp.get_instance_count())
    except Exception:
        pass
    return None


def _anim_of(comp):
    anim_class = animation = skeleton = None
    try:
        ac = comp.get_editor_property("anim_class")
        anim_class = str(ac.get_path_name()) if ac else None
    except Exception:
        pass
    try:
        seq = comp.get_editor_property("animation_data").anim_to_play
        animation = str(seq.get_path_name()) if seq else None
    except Exception:
        pass
    try:
        sk = comp.get_editor_property("skeletal_mesh") or comp.get_editor_property("skinned_asset")
        s = sk.get_editor_property("skeleton") if sk else None
        skeleton = str(s.get_path_name()) if s else None
    except Exception:
        pass
    return anim_class, animation, skeleton


def dump_level(out_path, *, include_components=True, max_components_per_actor=64) -> dict:
    EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    UES = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    world = UES.get_editor_world()
    actors = EAS.get_all_level_actors()
    rows = []
    comp_total = 0
    for a in actors:
        if a is None:
            continue
        loc = a.get_actor_location()
        rot = a.get_actor_rotation()
        rec = {
            "name": str(a.get_name()),
            "class": str(a.get_class().get_name()),
            "label": str(a.get_actor_label()),
            "folder": str(a.get_folder_path()) if hasattr(a, "get_folder_path") else None,
            "tags": [str(t) for t in a.get_editor_property("tags")],
            "location": {"x": round(float(loc.x), 2), "y": round(float(loc.y), 2), "z": round(float(loc.z), 2)},
            "rotation": {"roll": round(float(rot.roll), 3), "pitch": round(float(rot.pitch), 3), "yaw": round(float(rot.yaw), 3)},
            "components": [],
        }
        if include_components:
            comps = a.get_components_by_class(unreal.ActorComponent)
            for c in comps[:max_components_per_actor]:
                asset = _asset_of(c)
                anim_class, animation, skeleton = _anim_of(c)
                rec["components"].append({
                    "name": str(c.get_name()),
                    "class": str(c.get_class().get_name()),
                    "asset": asset,
                    "asset_lower": asset.lower() if asset else None,
                    "instance_count": _instance_count(c),
                    "anim_class": anim_class,
                    "animation": animation,
                    "skeleton": skeleton,
                })
            rec["components_total"] = len(comps)
            comp_total += len(comps)
        rows.append(rec)
    doc = {
        "schema_version": "level_dump_v1",
        "level": str(world.get_path_name()) if world else None,
        "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "counts": {"actors": len(rows), "components": comp_total},
        "actors": rows,
    }
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    return {"actors": len(rows), "components": comp_total, "path": str(p), "level": doc["level"]}
