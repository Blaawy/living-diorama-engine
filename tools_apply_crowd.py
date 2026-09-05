import sys, json
from pathlib import Path
WS = r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY\WORKSPACE"
sys.path.insert(0, WS)
from ldyf.unreal_remote import UnrealRemote
from ldyf.crowd_spec import crowd_plan
uids = ["person_%d" % i for i in range(80)]  # more than exist; extras are inert
plan = crowd_plan(uids)
SPEC = Path(r"C:\Users\BLaAw\AppData\Local\Temp\claude\crowd_plan.json")
SPEC.parent.mkdir(parents=True, exist_ok=True)
SPEC.write_text(json.dumps(plan), encoding="utf-8")
CODE = r'''
import unreal, json, sys, importlib, traceback
sys.path.insert(0, r"__WS__")
import ldyf.unreal.ldyf_crowd_editor as C
importlib.reload(C)
plan = json.loads(open(r"__SPEC__").read())
try:
    r = C.apply_crowd(plan)
    unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()
    print("CROWD " + json.dumps(r, default=str)[:2000])
except Exception:
    print("FAIL " + traceback.format_exc()[-1200:])
'''.replace("__WS__", WS).replace("__SPEC__", str(SPEC).replace("\\", "/"))
with UnrealRemote(discover_timeout=300.0) as r:
    print(r.output_text(r.exec_file(CODE))[-2200:])
