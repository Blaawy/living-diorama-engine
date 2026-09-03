"""Finalise the professional road system and prove it against SUMO.

1. Ensure PCG_LD_Roads has all six nodes (road / sidewalk / junction / ground).
2. Regenerate the instance.
3. Post-pass IN THE EDITOR: set every spline-mesh strip's cross-section scale from
   the SUMO lane width (PCG's Spawn Spline Mesh ignores the spline point scale, measured).
4. Re-sample the REAL components and re-run ldyf.road_geometry_check.

Run with: python CACHE/finalize_roads.py   (WORKSPACE on PYTHONPATH)
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

YF = Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
sys.path.insert(0, str(YF / "WORKSPACE"))
from ldyf.unreal_mcp import UnrealMCP          # noqa: E402
from ldyf.unreal_remote import UnrealRemote    # noqa: E402
from ldyf.road_geometry_check import build_report, write_report  # noqa: E402

GRAPH = "/Game/PCG/PCG_LD_Roads"
G = {"refPath": f"{GRAPH}.PCG_LD_Roads"}
N = lambda n: {"refPath": f"{GRAPH}.PCG_LD_Roads:{n}"}
SPEC = str(YF / "PHASE_02/proof/road_spec.json").replace("\\", "/")
SNAP = str(YF / "EVIDENCE/PHASE_02/road_component_snapshot.json").replace("\\", "/")
WS = str(YF / "WORKSPACE").replace("\\", "/")
ROAD_MESH = "/CitySamplePCG/Meshes/Roads/SM_Lane_Car_400_500.SM_Lane_Car_400_500"
WALK_MESH = "/CitySamplePCG/Meshes/Roads/SM_Lane_Car_200_200_A.SM_Lane_Car_200_200_A"
ASPHALT = "/Game/Road/Material/MI/MI_FreewayAsphalt_RoadDark.MI_FreewayAsphalt_RoadDark"
SIDEWALK_MI = "/Game/LD/Materials/MI_LD_Sidewalk.MI_LD_Sidewalk"


def graph_nodes(call) -> dict:
    st = call("GetGraphStructure", {"graph": G})
    return {n["name"]: n for n in st.get("nodes", [])} if isinstance(st, dict) else {}


def ensure_graph() -> dict:
    m = UnrealMCP(timeout=600); m.connect(); pcg = "PCGToolset.PCGToolset"
    log = []

    def call(tool, args, ts=pcg):
        r = m.call_tool("call_tool", {"toolset_name": ts, "tool_name": tool, "arguments": args})
        t = m.text_of(r)
        log.append({"tool": tool, "node": args.get("nodeName") or str(args.get("node", ""))[:70], "ok": not r.get("isError"), "reply": t[:160]})
        if r.get("isError"):
            return {"__error__": t[:200]}
        try:
            return json.loads(t).get("returnValue", t)
        except Exception:
            return t

    def selector(tag):
        return {"actorSelector": {"actorFilter": "AllWorldActors", "actorSelection": "ByTag", "actorSelectionTag": tag,
                                  "bSelectMultiple": True, "bMustOverlapSelf": False, "bIncludeChildren": False},
                "mode": "ParseActorComponents", "bAlwaysRequeryActors": True}

    def spawn(mesh, mats=None):
        d = {"splineMeshDescriptor": {"staticMesh": {"refPath": mesh}, "mobility": "Static", "bCastShadow": True},
             "splineMeshParams": {"forwardAxis": "X", "splineUpDir": {"x": 0.0, "y": 0.0, "z": 1.0}}}
        if mats:
            d["splineMeshDescriptor"]["overrideMaterials"] = [{"refPath": x} for x in mats]
        return json.dumps(d)

    have = graph_nodes(call)
    wanted = [("GetRoadSplines", "Get Spline Data", json.dumps(selector("ld_road")), 0, 0),
              ("GetSidewalkSplines", "Get Spline Data", json.dumps(selector("ld_sidewalk")), 0, 1),
              ("GetJunctionSplines", "Get Spline Data", json.dumps(selector("ld_junction")), 0, 2),
              ("GetGroundSpline", "Get Spline Data", json.dumps(selector("ld_ground")), 0, 3),
              ("SpawnRoad", "Spawn Spline Mesh", spawn(ROAD_MESH, [ASPHALT]), 1, 0),
              ("SpawnSidewalk", "Spawn Spline Mesh", spawn(WALK_MESH, [SIDEWALK_MI]), 1, 1)]
    for name, ntype, params, x, y in wanted:
        if name in have:
            call("UpdateNode", {"node": N(name), "jsonParams": params, "nodeTitle": name})
        else:
            call("AddNode", {"graph": G, "nativeNodeType": ntype, "nodeName": name, "nodeTitle": name,
                             "nodeComment": "", "jsonParams": params, "xPositionIdx": x, "yPositionIdx": y})
    for name, sub, params, x, y in (("FillJunctions", "/PCGPrimitives/Primitives/Create/Create_Mesh_Planar.Create_Mesh_Planar",
                                     json.dumps({"material": {"refPath": ASPHALT}}), 1, 2),
                                    ("FillGround", "/PCGPrimitives/Primitives/Create/Create_Mesh_Planar.Create_Mesh_Planar",
                                     json.dumps({"material": {"refPath": "/Game/LD/Materials/MI_LD_Ground.MI_LD_Ground"}}), 1, 3)):
        if name in have:
            call("UpdateNode", {"node": N(name), "jsonParams": params, "nodeTitle": name})
        else:
            call("AddSubgraphNode", {"graph": G, "subGraphForNode": {"refPath": sub}, "nodeName": name, "nodeTitle": name,
                                     "nodeComment": "", "jsonParams": params, "xPositionIdx": x, "yPositionIdx": y})
    have = graph_nodes(call)
    edges = {(e["srcNode"], e["destNode"]) for e in (call("GetGraphStructure", {"graph": G}) or {}).get("edges", [])}
    for a, b, pin_in in (("GetRoadSplines", "SpawnRoad", "In"), ("GetSidewalkSplines", "SpawnSidewalk", "In"),
                         ("GetJunctionSplines", "FillJunctions", "PrimaryInput"), ("GetGroundSpline", "FillGround", "PrimaryInput")):
        if (a, b) not in edges:
            call("ConnectNodePins", {"fromNode": N(a), "fromPinLabel": "Out", "toNode": N(b), "toPinLabel": pin_in})
    for b in ("SpawnRoad", "SpawnSidewalk", "FillJunctions", "FillGround"):
        if (b, "DefaultOutputNode") not in edges:
            call("ConnectNodePins", {"fromNode": N(b), "fromPinLabel": "Out", "toNode": N("DefaultOutputNode"), "toPinLabel": "Out"})
    call("save_assets", {"asset_paths": [GRAPH]}, ts="editor_toolset.toolsets.asset.AssetTools")
    st = call("GetGraphStructure", {"graph": G})
    return {"nodes": sorted(n["name"] for n in st.get("nodes", [])), "edges": len(st.get("edges", [])), "log": log[-8:]}


REGEN_AND_WIDTHS = r'''
import unreal, json, sys, math
for p in ("__WS__",):
    (p in sys.path) or sys.path.insert(0, p)
from ldyf.roads import centreline_error_cm
spec = json.loads(open(r"__SPEC__").read())
lanes = {}
for e in spec["edges"]:
    if (e.get("function") or "normal") != "normal":
        continue
    for ln in e["lanes"]:
        lanes[ln["id"]] = ln
EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
out = {"regenerated": False, "scaled": 0, "unmatched": 0, "by_width": {}}
for a in EAS.get_all_level_actors():
    if not str(a.get_actor_label()).startswith("LD_RoadsPCG"):
        continue
    pcg = a.get_component_by_class(unreal.PCGComponent)
    pcg.generate_local(True); out["regenerated"] = True
    for c in a.get_components_by_class(unreal.SplineMeshComponent):
        tf = c.get_world_transform()
        s = tf.transform_location(c.get_start_position()); e2 = tf.transform_location(c.get_end_position())
        mid = {"x": (s.x + e2.x) / 2.0, "y": (s.y + e2.y) / 2.0, "z": 0.0}
        best_id, best_d = None, None
        for lid, ln in lanes.items():
            d = centreline_error_cm(ln["polyline"], [mid])["max_cm"]
            if best_d is None or d < best_d:
                best_d, best_id = d, lid
        if best_id is None or best_d > 50.0:
            out["unmatched"] += 1; continue
        m = c.get_editor_property("static_mesh"); bb = m.get_bounding_box()
        mesh_w = float(bb.max.y - bb.min.y)
        w = lanes[best_id].get("width_cm_effective") or lanes[best_id].get("width_cm")
        if not w or mesh_w <= 0:
            continue
        sy = float(w) / mesh_w
        c.set_start_scale(unreal.Vector2D(1.0, sy), True); c.set_end_scale(unreal.Vector2D(1.0, sy), True)
        out["scaled"] += 1; key = str(round(float(w), 1)); out["by_width"][key] = out["by_width"].get(key, 0) + 1
LES = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem); out["saved"] = bool(LES.save_current_level())
print("WIDTHS", json.dumps(out, default=str)[:400])
'''.replace("__WS__", WS).replace("__SPEC__", SPEC)

SAMPLE = r'''
import unreal, json
EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
def v3(v): return {"x": round(float(v.x), 3), "y": round(float(v.y), 3), "z": round(float(v.z), 3)}
snap = {"strips": [], "slabs": [], "ground": None}
for a in EAS.get_all_level_actors():
    if not str(a.get_actor_label()).startswith("LD_RoadsPCG"):
        continue
    for c in a.get_components_by_class(unreal.SplineMeshComponent):
        tf = c.get_world_transform()
        m = c.get_editor_property("static_mesh"); bb = m.get_bounding_box() if m else None
        o, e, r = unreal.SystemLibrary.get_component_bounds(c)
        snap["strips"].append({"mesh": str(m.get_path_name()) if m else None,
            "mesh_width_cm": round(float(bb.max.y - bb.min.y), 3) if bb else None,
            "mesh_len_cm": round(float(bb.max.x - bb.min.x), 3) if bb else None,
            "start": v3(tf.transform_location(c.get_start_position())), "end": v3(tf.transform_location(c.get_end_position())),
            "start_scale_y": round(float(c.get_start_scale().y), 4), "end_scale_y": round(float(c.get_end_scale().y), 4),
            "top_z": round(float(o.z + e.z), 3), "tags": [str(x) for x in c.component_tags]})
    for c in a.get_components_by_class(unreal.DynamicMeshComponent):
        o, e, r = unreal.SystemLibrary.get_component_bounds(c)
        snap["slabs"].append({"id": str(c.get_name()), "bounds_min": v3(unreal.Vector(o.x-e.x, o.y-e.y, o.z-e.z)),
                              "bounds_max": v3(unreal.Vector(o.x+e.x, o.y+e.y, o.z+e.z)), "top_z": round(float(o.z + e.z), 3)})
if snap["slabs"]:
    big = max(snap["slabs"], key=lambda s: (s["bounds_max"]["x"]-s["bounds_min"]["x"]) * (s["bounds_max"]["y"]-s["bounds_min"]["y"]))
    snap["ground"] = big; snap["slabs"] = [s for s in snap["slabs"] if s is not big]
open(r"__SNAP__", "w").write(json.dumps(snap, indent=2, default=str))
print("SNAP strips", len(snap["strips"]), "slabs", len(snap["slabs"]), "scales", sorted({s["start_scale_y"] for s in snap["strips"]})[:6],
      "slab_tops", sorted({s["top_z"] for s in snap["slabs"]})[:4], "ground_top", (snap["ground"] or {}).get("top_z"))
'''.replace("__SNAP__", SNAP)

if __name__ == "__main__":
    g = ensure_graph()
    print("GRAPH", g["nodes"], "edges", g["edges"])
    with UnrealRemote(discover_timeout=60.0) as r:
        print(r.output_text(r.exec_file(REGEN_AND_WIDTHS))[-500:])
        print(r.output_text(r.exec_file(SAMPLE))[-500:])
    snap = json.loads(Path(SNAP).read_text(encoding="utf-8"))
    spec = json.loads(Path(SPEC).read_text(encoding="utf-8"))
    rep = build_report(snap, spec, tol_cm=5.0)
    write_report(rep, YF / "EVIDENCE/PHASE_02/road_geometry.json")
    print("totals:", json.dumps(rep["totals"], default=str))
    print("worst:", json.dumps(rep["worst"], default=str))
    print("ROAD GEOMETRY PASS:", rep["pass"])
