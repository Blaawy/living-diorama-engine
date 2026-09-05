import sys, json
from pathlib import Path
WS = r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY\WORKSPACE"
sys.path.insert(0, WS)
from ldyf.unreal_remote import UnrealRemote
from ldyf.tree_mesh import TREE_VARIANTS, tree_mesh, validate_mesh
TMP = Path(r"C:\Users\BLaAw\AppData\Local\Temp\claude\trees")
TMP.mkdir(parents=True, exist_ok=True)
from ldyf.tree_mesh import TREE_VARIANT_ORDER
names = list(TREE_VARIANT_ORDER)  # index agreement with dressing.tree_slots
built = []
for i, name in enumerate(names):
    doc = tree_mesh(name, seed="ld-phase2")
    problems = validate_mesh(doc)
    if problems:
        raise SystemExit("variant %s invalid: %s" % (name, problems[:3]))
    f = TMP / ("tree_%s.json" % name)
    f.write_text(json.dumps(doc), encoding="utf-8")
    built.append({"variant": name, "index": i, "file": str(f).replace("\\", "/"),
                  "asset": "SM_LD_Tree_%s" % name.capitalize()})
SPEC = TMP / "manifest.json"
SPEC.write_text(json.dumps(built), encoding="utf-8")
CODE = r'''
import unreal, json, sys, importlib, traceback
sys.path.insert(0, r"__WS__")
import ldyf.unreal.ldyf_tree_editor as T
importlib.reload(T)
out = {"materials": T.ensure_tree_materials(), "meshes": []}
try:
    for row in json.loads(open(r"__SPEC__").read()):
        doc = json.loads(open(row["file"]).read())
        r = T.build_tree_mesh(doc, asset_name=row["asset"])
        r["variant"] = row["variant"]; r["index"] = row["index"]
        out["meshes"].append(r)
    print("TREES " + json.dumps(out, default=str)[:2000])
except Exception:
    print("FAIL " + traceback.format_exc()[-1200:])
'''.replace("__WS__", WS).replace("__SPEC__", str(SPEC).replace("\\", "/"))
with UnrealRemote(discover_timeout=300.0) as r:
    print(r.output_text(r.exec_file(CODE))[-2200:])
