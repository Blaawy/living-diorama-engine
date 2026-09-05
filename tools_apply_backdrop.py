import sys, json
from pathlib import Path
WS = r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY\WORKSPACE"
sys.path.insert(0, WS)
from ldyf.unreal_remote import UnrealRemote
from ldyf.backdrop import build_backdrop
spec = json.load(open(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY\CACHE\master_stage_p2\evidence\proof\road_spec.json"))
# Defaults put the first ring ~565 m out at 198 m tall, so the "distant"
# skyline loomed over the city as black walls. Real distant massing is far
# away and LOW in the frame: push the rings out and cut the heights, and
# widen the skirt so it still reaches past the outermost ring.
doc = build_backdrop(
    spec,
    outer_radius_cm=30.0 * 43614.346,   # ~13 km: far past where fog has
    segments=96,                        # already faded the ground to sky
    rings=4,
    per_ring=26,
    min_h_cm=0.05 * 43614.346,
    max_h_cm=0.17 * 43614.346,
    ring_gap_cm=1.6 * 43614.346,
    inner_margin_cm=2.6 * 43614.346,
)
F = Path(r"C:\Users\BLaAw\AppData\Local\Temp\claude\backdrop.json")
F.parent.mkdir(parents=True, exist_ok=True)
F.write_text(json.dumps(doc), encoding="utf-8")
print("PLAN", json.dumps(doc["counts"]))
CODE = r'''
import unreal, json, sys, importlib, traceback
sys.path.insert(0, r"__WS__")
import ldyf.unreal.ldyf_backdrop_editor as B
importlib.reload(B)
doc = json.loads(open(r"__F__").read())
try:
    r = B.build_backdrop(doc, ground_z_cm=0.0)
    unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()
    print("BACKDROP " + json.dumps(r, default=str)[:1500])
except Exception:
    print("FAIL " + traceback.format_exc()[-1500:])
'''.replace("__WS__", WS).replace("__F__", str(F).replace("\\", "/"))
with UnrealRemote(discover_timeout=300.0) as r:
    print(r.output_text(r.exec_file(CODE))[-1800:])
