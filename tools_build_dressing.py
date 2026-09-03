"""Generate dressing_v1 from the SUMO spec and build it in the editor."""
from __future__ import annotations
import json, sys, time
from pathlib import Path

YF = Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
sys.path.insert(0, str(YF / "WORKSPACE"))
from ldyf.unreal_remote import UnrealRemote          # noqa: E402
from ldyf.dressing import build_dressing, write_dressing   # noqa: E402

EV = YF / "EVIDENCE" / "PHASE_02"
SPEC = YF / "PHASE_02" / "proof" / "road_spec.json"
RULE = YF / "PHASE_01" / "proof" / "sumo" / "closure_v2" / "rule_manifest.json"
SURFACE_Z = 20.0

CODE = r'''
import unreal, json, sys
sys.path.insert(0, r"__WS__")
import importlib
import ldyf.unreal.ldyf_dressing_editor as D
importlib.reload(D)
res = {}
res["materials"] = D.ensure_paint_materials()
res["cleared"] = D.clear_dressing()
res["markings"] = D.build_markings(r"__DRESS__", z_cm=__SURF__ + 20.0)
res["crosswalks"] = D.build_crosswalks(r"__DRESS__", z_cm=__SURF__ + 20.0)
res["signals"] = D.build_signals(r"__DRESS__", surface_z_cm=__SURF__)
res["trees"] = D.build_trees(r"__DRESS__", surface_z_cm=__SURF__)
res["furniture"] = D.build_furniture(r"__LAYOUT__", surface_z_cm=__SURF__)
res["closure"] = D.build_closure_props(r"__DRESS__", surface_z_cm=__SURF__)
res["summary"] = D.dressing_summary()
unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()
open(r"__OUT__", "w").write(json.dumps(res, indent=1, default=str))
print("DRESSING " + json.dumps(res["summary"], default=str))
print("COUNTS " + json.dumps({k: (v.get("placed") or v.get("decals") or v.get("stripes"))
                              for k, v in res.items() if isinstance(v, dict)}, default=str))
'''


def main() -> int:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    rule = json.loads(RULE.read_text(encoding="utf-8"))
    closed = list(rule["change"]["close_edges"]["edge_ids"])
    doc = build_dressing(spec, closed_edge_ids=closed)
    dress = EV / "dressing.json"
    write_dressing(doc, dress)
    print("DRESSING DOC", json.dumps(doc["counts"]))
    code = (CODE.replace("__WS__", str(YF / "WORKSPACE"))
                .replace("__DRESS__", str(dress))
                .replace("__LAYOUT__", str(EV / "city_layout.json"))
                .replace("__SURF__", repr(SURFACE_Z))
                .replace("__OUT__", str(EV / "dressing_build.json")))
    t0 = time.time()
    with UnrealRemote(discover_timeout=90.0) as r:
        print(r.output_text(r.exec_file(code))[-3000:])
    print("elapsed", round(time.time() - t0, 1), "s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
