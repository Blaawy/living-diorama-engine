from __future__ import annotations
import json, math, shutil, sys, time
from pathlib import Path
YF = Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
sys.path.insert(0, str(YF / "WORKSPACE"))
from ldyf.unreal_remote import UnrealRemote
EV = YF / "EVIDENCE" / "PHASE_02"
SHOTS_DIR = YF / "WORKSPACE" / "LivingDioramaYF" / "Saved" / "Screenshots" / "WindowsEditor"

def look(frm, to):
    dx, dy, dz = to[0]-frm[0], to[1]-frm[1], to[2]-frm[2]
    return [round(math.degrees(math.atan2(dz, math.hypot(dx,dy))),3),
            round(math.degrees(math.atan2(dy,dx)),3)]

VIEWS = {
    "street_markings": ([1500.0,-6000.0,350.0],[300.0,-12000.0,120.0]),
    "junction_b1":     ([37000.0,-17500.0,1600.0],[39000.0,-20000.0,0.0]),
    "closure":         ([38560.0,-16500.0,500.0],[38560.0,-20500.0,100.0]),
    "sidewalk_trees":  ([2400.0,-9000.0,300.0],[900.0,-13000.0,250.0]),
    "overview":        ([-9000.0,-9000.0,24000.0],[30000.0,-32000.0,0.0]),
}
ONE = r'''
import unreal
ULS = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
LES = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
try: LES.editor_set_game_view(True)
except Exception: pass
ULS.set_level_viewport_camera_info(unreal.Vector(__LOC__), unreal.Rotator(0.0, __P__, __Y__))
unreal.SystemLibrary.execute_console_command(None, "HighResShot 1920x1080 filename=LDVIEW___N__")
print("SHOT __N__")
'''

def main():
    if SHOTS_DIR.exists():
        for f in SHOTS_DIR.glob("LDVIEW_*.png"):
            f.unlink()
    dest = EV / "views"; dest.mkdir(parents=True, exist_ok=True)
    got = []
    with UnrealRemote(discover_timeout=90.0) as r:
        for name, (loc, to) in VIEWS.items():
            p, y = look(loc, to)
            code = (ONE.replace("__LOC__", ", ".join(repr(v) for v in loc))
                       .replace("__P__", repr(p)).replace("__Y__", repr(y))
                       .replace("__N__", name))
            r.output_text(r.exec_file(code))
            for _ in range(30):
                time.sleep(1.0)
                hit = sorted(SHOTS_DIR.glob("LDVIEW_%s*.png" % name)) if SHOTS_DIR.exists() else []
                if hit and hit[-1].stat().st_size > 0:
                    time.sleep(1.0)
                    d = dest / ("LDVIEW_%s.png" % name)
                    shutil.copy2(hit[-1], d)
                    got.append({"view": name, "bytes": d.stat().st_size})
                    break
            else:
                got.append({"view": name, "bytes": None})
    print("CAPTURED " + json.dumps(got))
    return 0

raise SystemExit(main())
