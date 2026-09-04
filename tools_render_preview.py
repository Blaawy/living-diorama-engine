import json, sys
from pathlib import Path
YF = Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
sys.path.insert(0, str(YF / "WORKSPACE"))
from ldyf.unreal_remote import UnrealRemote
EV = YF / "EVIDENCE" / "PHASE_02"
OUTDIR = EV / "preview_mrq"
ws = str(YF / "WORKSPACE")
shots = json.loads((EV / "shot_camera_args.json").read_text(encoding="utf-8"))
for f in OUTDIR.glob("*.png"):
    f.unlink()
CAM = r'''
import unreal, json, sys, importlib
sys.path.insert(0, r"%s")
import ldyf.unreal.ldyf_preview as P
importlib.reload(P)
r = P.add_cameras(json.loads(r"""%s"""), fps=24)
unreal.EditorAssetLibrary.save_loaded_asset(unreal.EditorAssetLibrary.load_asset(P.SEQ_PATH))
print("CAMS " + json.dumps(r, default=str))
''' % (ws, json.dumps(shots))
REN = r'''
import unreal, json, sys, importlib
sys.path.insert(0, r"%s")
import ldyf.unreal.ldyf_preview as P
importlib.reload(P)
r = P.render_mrq(r"%s", fps=24, width=1920, height=1080)
print("RENDER " + json.dumps(r, default=str)[:400])
''' % (ws, str(OUTDIR))
with UnrealRemote(discover_timeout=180.0) as r:
    print(r.output_text(r.exec_file(CAM))[-900:])
    print(r.output_text(r.exec_file(REN))[-400:])
