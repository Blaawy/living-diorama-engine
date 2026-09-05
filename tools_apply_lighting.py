import sys, json
from pathlib import Path
WS = r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY\WORKSPACE"
sys.path.insert(0, WS)
from ldyf.unreal_remote import UnrealRemote
from ldyf.lighting import build_lighting
bias = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
spec = build_lighting()
spec.pop("rationale", None)
for k in ("auto_exposure_bias", "auto_exposure_min_brightness", "auto_exposure_max_brightness"):
    spec["exposure"][k] = bias
SPEC = Path(r"C:\Users\BLaAw\AppData\Local\Temp\claude\lighting_spec.json")
SPEC.parent.mkdir(parents=True, exist_ok=True)
SPEC.write_text(json.dumps(spec), encoding="utf-8")
CODE = r'''
import unreal, json, sys, importlib, traceback
sys.path.insert(0, r"__WS__")
import ldyf.unreal.ldyf_lighting_editor as L
importlib.reload(L)
spec = json.loads(open(r"__SPEC__").read())
try:
    r = L.apply_lighting(spec)
    unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()
    print("LIGHT " + json.dumps(r, default=str)[:2500])
except Exception:
    print("FAIL " + traceback.format_exc()[-1200:])
'''.replace("__WS__", WS).replace("__SPEC__", str(SPEC).replace("\\", "/"))
with UnrealRemote(discover_timeout=300.0) as r:
    print(r.output_text(r.exec_file(CODE))[-2500:])
