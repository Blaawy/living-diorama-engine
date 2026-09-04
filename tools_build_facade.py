"""Build the facade master + kit instances, then point the PCG building
extrusion nodes at them (replacing the City Sample facade that renders as noise)."""
from __future__ import annotations
import json, sys, time
from pathlib import Path
YF = Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
sys.path.insert(0, str(YF / "WORKSPACE"))
from ldyf.unreal_remote import UnrealRemote
from ldyf.facade import facade_graph, kit_parameters, validate_graph
EV = YF / "EVIDENCE" / "PHASE_02"
OUT = str(EV / "facade_build.json").replace("\\", "/")

KITS = ("CHA", "NYA", "SFA")

CODE = r'''
import unreal, json, sys, importlib
sys.path.insert(0, r"__WS__")
import ldyf.unreal.ldyf_facade_editor as F
importlib.reload(F)
graph = json.loads(r"""__GRAPH__""")
kits = json.loads(r"""__KITS__""")
out = {}
out["master"] = F.build_facade_material(graph)
out["instances"] = F.build_kit_instances(kits)
out["verify"] = F.verify_instances(kits)
open(r"__OUT__", "w").write(json.dumps(out, indent=1, default=str))
print("FACADE " + json.dumps(out, default=str)[:2500])
'''


def main() -> int:
    graph = facade_graph(spacing_h_cm=350.0, spacing_v_cm=400.0, window_w=0.30,
                         window_h=0.34, edge_sharpness=40.0, ground_floor_cm=450.0)
    problems = validate_graph(graph)
    if problems:
        raise SystemExit("facade graph invalid: %s" % problems)
    kits = {k: kit_parameters(k) for k in KITS}
    (EV / "facade_graph.json").write_text(json.dumps(
        {"graph": graph, "kits": kits}, indent=2, sort_keys=True), encoding="utf-8")
    code = (CODE.replace("__WS__", str(YF / "WORKSPACE"))
                .replace("__GRAPH__", json.dumps(graph))
                .replace("__KITS__", json.dumps(kits))
                .replace("__OUT__", OUT))
    with UnrealRemote(discover_timeout=120.0) as r:
        print(r.output_text(r.exec_file(code))[-3000:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
