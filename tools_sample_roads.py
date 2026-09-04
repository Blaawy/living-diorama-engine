"""Sample the REAL rendered road geometry from spawned components (contract C4)."""
import json, sys
from pathlib import Path
sys.path.insert(0, r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY\WORKSPACE")
from ldyf.unreal_remote import UnrealRemote
YF = Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
OUT = str(YF / "EVIDENCE/PHASE_02/road_component_snapshot.json").replace("\\", "/")
CODE = r'''
import unreal, json
EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
def v3(v): return {"x": round(float(v.x), 3), "y": round(float(v.y), 3), "z": round(float(v.z), 3)}
snap = {"strips": [], "slabs": [], "ground": None}
for a in EAS.get_all_level_actors():
    if not str(a.get_actor_label()).startswith("LD_RoadsPCG"): continue
    for c in a.get_components_by_class(unreal.SplineMeshComponent):
        sp, ep = c.get_start_position(), c.get_end_position()
        ss, es = c.get_start_scale(), c.get_end_scale()
        tf = c.get_world_transform()   # verified API (probe: SplineMeshComponent.get_world_transform)
        m = c.get_editor_property("static_mesh"); bb = m.get_bounding_box() if m else None
        o, e, r = unreal.SystemLibrary.get_component_bounds(c)
        snap["strips"].append({"mesh": str(m.get_path_name()) if m else None,
            "mesh_width_cm": round(float(bb.max.y - bb.min.y), 3) if bb else None,
            "mesh_len_cm": round(float(bb.max.x - bb.min.x), 3) if bb else None,
            "start": v3(tf.transform_location(sp)), "end": v3(tf.transform_location(ep)),
            "start_scale_y": round(float(ss.y), 4), "end_scale_y": round(float(es.y), 4),
            "measured_width_cm": round(float(e.y * 2), 2),
            "top_z": round(float(o.z + e.z), 3), "tags": [str(x) for x in c.component_tags]})
    for c in a.get_components_by_class(unreal.DynamicMeshComponent):
        # A junction slab is a ROAD SURFACE, identified by the material it
        # wears -- not by being any dynamic mesh on the PCG actor. Since the
        # buildings became PCG extrusions they are dynamic meshes too, and
        # taking every one of them made the junction height check compare a
        # junction against a 58 m building roof.
        _m = c.get_material(0)
        _mp = str(_m.get_path_name()).lower() if _m else ""
        if "facade" in _mp:
            continue
        o, e, r = unreal.SystemLibrary.get_component_bounds(c)
        snap["slabs"].append({"id": str(c.get_name()), "material": (str(_m.get_path_name()) if _m else None),
            "bounds_min": v3(unreal.Vector(o.x-e.x, o.y-e.y, o.z-e.z)),
            "bounds_max": v3(unreal.Vector(o.x+e.x, o.y+e.y, o.z+e.z)), "top_z": round(float(o.z + e.z), 3)})
if snap["slabs"]:
    big = max(snap["slabs"], key=lambda s: (s["bounds_max"]["x"]-s["bounds_min"]["x"]) * (s["bounds_max"]["y"]-s["bounds_min"]["y"]))
    snap["ground"] = big; snap["slabs"] = [s for s in snap["slabs"] if s is not big]
open(r"__OUT__", "w").write(json.dumps(snap, indent=2, default=str))
print("SNAP strips", len(snap["strips"]), "slabs", len(snap["slabs"]), "ground_top", (snap["ground"] or {}).get("top_z"),
      "slab_tops", sorted({s["top_z"] for s in snap["slabs"]}), "scales", sorted({s["start_scale_y"] for s in snap["strips"]}),
      "widths", sorted({s["measured_width_cm"] for s in snap["strips"]})[:6])
'''.replace("__OUT__", OUT)
if __name__ == "__main__":
    with UnrealRemote(discover_timeout=60.0) as r:
        print(r.output_text(r.exec_file(CODE))[-900:])
