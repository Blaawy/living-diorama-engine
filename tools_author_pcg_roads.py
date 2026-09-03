"""Author /Game/PCG/PCG_LD_Roads over MCP: tagged lane splines -> spline meshes.
Native-node route (Get Spline Data by actor tag -> Spawn Spline Mesh) chosen
because its schemas are fully known (answers_round2.json); the City Sample
grammar route stays an enhancement. Writes EVIDENCE/PHASE_02/pcg_roads_authoring.json."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY\WORKSPACE")
from ldyf.unreal_mcp import UnrealMCP
EV = Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY\EVIDENCE\PHASE_02")
GRAPH = "/Game/PCG/PCG_LD_Roads"; G = {"refPath": f"{GRAPH}.PCG_LD_Roads"}
N = lambda n: {"refPath": f"{GRAPH}.PCG_LD_Roads:{n}"}
m = UnrealMCP(timeout=600); m.connect(); pcg = "PCGToolset.PCGToolset"; log = {"steps": []}
def call(tool, args, ts=pcg):
    r = m.call_tool("call_tool", {"toolset_name": ts, "tool_name": tool, "arguments": args}); t = m.text_of(r)
    ok = not r.get("isError")
    log["steps"].append({"tool": tool, "args": args, "ok": ok, "reply": t[:600]})
    print(("OK " if ok else "ERR") + " " + tool + " -> " + t[:220].replace("\n", " "))
    if not ok: return {"__error__": t}
    try: return json.loads(t).get("returnValue", t)
    except Exception: return t
exists = call("GetGraphStructure", {"graph": G})
if isinstance(exists, dict) and "nodes" in exists:
    print("graph exists with", len(exists["nodes"]), "nodes; removing non-default nodes for a clean rebuild")
    for n in exists["nodes"]:
        if n.get("nodeType") not in ("Input Node", "Output Node"):
            call("RemoveNode", {"node": {"refPath": n["path"]}})
else:
    call("CreateGraph", {"name": "PCG_LD_Roads", "path": "/Game/PCG"})
def selector(tag):
    return {"actorSelector": {"actorFilter": "AllWorldActors", "actorSelection": "ByTag", "actorSelectionTag": tag, "bSelectMultiple": True, "bMustOverlapSelf": False, "bIncludeChildren": False}, "mode": "ParseActorComponents", "bAlwaysRequeryActors": True}
def spline_mesh(mesh):
    return {"splineMeshDescriptor": {"staticMesh": {"refPath": mesh}, "mobility": "Static", "bCastShadow": True}, "splineMeshParams": {"forwardAxis": "X", "splineUpDir": {"x": 0.0, "y": 0.0, "z": 1.0}}}
nodes = [("GetRoadSplines", "Get Spline Data", selector("ld_road")), ("GetSidewalkSplines", "Get Spline Data", selector("ld_sidewalk")),
         ("SpawnRoad", "Spawn Spline Mesh", spline_mesh("/CitySamplePCG/Meshes/Roads/SM_Lane_Car_400_500.SM_Lane_Car_400_500")),
         ("SpawnSidewalk", "Spawn Spline Mesh", spline_mesh("/CitySamplePCG/Meshes/Roads/SM_Lane_Car_200_200_A.SM_Lane_Car_200_200_A"))]
for i, (name, ntype, params) in enumerate(nodes):
    r = call("AddNode", {"graph": G, "nativeNodeType": ntype, "nodeName": name, "nodeTitle": name, "nodeComment": "", "position": {"x": (i % 2) * 400, "y": (i // 2) * 300}, "jsonParams": json.dumps(params)})
    if isinstance(r, dict) and r.get("__error__"):
        r = call("AddNode", {"graph": G, "nativeNodeType": ntype, "nodeName": name, "nodeTitle": name, "nodeComment": "", "positionX": (i % 2) * 400, "positionY": (i // 2) * 300, "jsonParams": json.dumps(params)})
for a, b in (("GetRoadSplines", "SpawnRoad"), ("GetSidewalkSplines", "SpawnSidewalk")):
    call("ConnectNodePins", {"fromNode": N(a), "fromPinLabel": "Out", "toNode": N(b), "toPinLabel": "In"})
for b in ("SpawnRoad", "SpawnSidewalk"):
    call("ConnectNodePins", {"fromNode": N(b), "fromPinLabel": "Out", "toNode": N("DefaultOutputNode"), "toPinLabel": "Out"})
st = call("GetGraphStructure", {"graph": G})
if isinstance(st, dict): print("graph nodes:", [(n.get("name"), n.get("nodeType")) for n in st.get("nodes", [])], "edges:", len(st.get("edges", [])))
call("SaveSection", {"containerName": "x"}, ts="ConfigSettingsToolset.ConfigSettingsToolset") if False else None
inst = call("ListGraphInstances", {})
mine = [x for x in inst if "LD_RoadsPCG" in str(x)] if isinstance(inst, list) else []
if not mine:
    T = {"rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}, "translation": {"x": 30000.0, "y": -30000.0, "z": 0.0}, "scale3D": {"x": 1.0, "y": 1.0, "z": 1.0}}
    sp = call("SpawnGraphInstance", {"graph": G, "name": "LD_RoadsPCG", "transform": T, "jsonParams": "{}"})
    if isinstance(sp, dict) and sp.get("__error__"):
        sp = call("SpawnGraphInstance", {"graph": G, "name": "LD_RoadsPCG", "transform": {"translation": T["translation"], "rotation": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}, "scale3D": T["scale3D"]}, "jsonParams": "{}"})
    inst = call("ListGraphInstances", {}); mine = [x for x in inst if "PCG_LD_Roads" in str(x) or "LD_Roads" in str(x)] if isinstance(inst, list) else []
actor = (mine[-1]["actor"] if mine and isinstance(mine[-1], dict) and "actor" in mine[-1] else (inst[-1]["actor"] if isinstance(inst, list) and inst else None))
print("instance actor:", actor)
if actor:
    ex = call("ExecuteGraphInstance", {"pCGVolume": actor}); time.sleep(5)
    for nn in ("GetRoadSplines", "SpawnRoad", "GetSidewalkSplines", "SpawnSidewalk"):
        dv = call("GetNodeDataView", {"pCGVolume": actor, "node": N(nn), "pinLabel": "Out", "attributeName": "", "startIndex": 0, "endIndex": 1})
        try:
            raw = dv if isinstance(dv, str) else json.dumps(dv); parsed = json.loads(raw) if isinstance(raw, str) and raw.strip().startswith("{") else None
            print(nn, "totalElements:", parsed.get("totalElements") if parsed else str(dv)[:200])
        except Exception as e:
            print(nn, "view parse failed", str(e)[:80])
log["graph"] = GRAPH; log["instance_actor"] = actor
(EV / "pcg_roads_authoring.json").write_text(json.dumps(log, indent=2, default=str), encoding="utf-8"); print("written pcg_roads_authoring.json")
