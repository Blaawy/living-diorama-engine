"""Render a handful of still frames of the live world through Movie Render Queue.

The editor's ``HighResShot`` console command is accepted but silently writes
nothing when the editor is launched without an interactive, rendering viewport,
which is exactly how this session drives it. MRQ does not depend on the viewport
and is the same path the deliverable preview uses, so every visual check in this
campaign goes through here.

Usage::

    py tools_look.py <views.json> <out_subdir>

``views.json`` is a list of ``{"name", "loc": [x,y,z], "to": [x,y,z]}`` (pitch
and yaw are derived by looking from ``loc`` at ``to``) or an explicit
``{"name", "loc", "rot": [pitch, yaw, roll]}``. One frame is rendered per view.
"""
from __future__ import annotations

import json
import math
import shutil
import sys
import time
from pathlib import Path

YF = Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
sys.path.insert(0, str(YF / "WORKSPACE"))
from ldyf.unreal_remote import UnrealRemote  # noqa: E402

EV = YF / "EVIDENCE" / "PHASE_02"
RAW = EV / "look_raw"
SEQ = "/Game/LD/LS_Look"
FPS = 24
# One frame per view would leave MRQ no warm-up at all; a short hold per view
# also lets temporal effects settle before the frame we keep.
HOLD_FRAMES = 4


def look_rot(frm, to):
    dx, dy, dz = to[0] - frm[0], to[1] - frm[1], to[2] - frm[2]
    pitch = math.degrees(math.atan2(dz, math.hypot(dx, dy)))
    yaw = math.degrees(math.atan2(dy, dx))
    return [round(pitch, 3), round(yaw, 3), 0.0]


def build_shots(views):
    shots = []
    for i, v in enumerate(views):
        rot = v.get("rot") or look_rot(v["loc"], v["to"])
        f0 = i * HOLD_FRAMES
        shots.append({"name": v["name"], "start_s": f0 / FPS,
                      "end_s": (f0 + HOLD_FRAMES) / FPS,
                      "loc": [float(c) for c in v["loc"]],
                      "rot": [float(c) for c in rot],
                      "fov_deg": float(v.get("fov_deg", 70.0))})
    return shots


ENSURE = r'''
import unreal, json
eal = unreal.EditorAssetLibrary
at = unreal.AssetToolsHelpers.get_asset_tools()
seq = eal.load_asset("%(seq)s")
if seq is None:
    seq = at.create_asset("LS_Look", "/Game/LD", unreal.LevelSequence,
                          unreal.LevelSequenceFactoryNew())
unreal.MovieSceneSequenceExtensions.set_display_rate(seq, unreal.FrameRate(%(fps)d, 1))
unreal.MovieSceneSequenceExtensions.set_playback_start(seq, 0)
unreal.MovieSceneSequenceExtensions.set_playback_end(seq, %(end)d)
eal.save_loaded_asset(seq)
print("SEQ " + json.dumps({"ok": seq is not None, "end": %(end)d}))
'''

CAM = r'''
import unreal, json, sys, importlib
sys.path.insert(0, r"%(ws)s")
import ldyf.unreal.ldyf_preview as P
importlib.reload(P)
r = P.add_cameras(json.loads(r"""%(shots)s"""), fps=%(fps)d, seq_path="%(seq)s",
                 cam_prefix="LD_LOOKCAM")
unreal.EditorAssetLibrary.save_loaded_asset(unreal.EditorAssetLibrary.load_asset("%(seq)s"))
print("CAMS " + json.dumps(r, default=str))
'''

REN = r'''
import unreal, json
sub = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
q = sub.get_queue()
for j in list(q.get_jobs()):
    q.delete_job(j)
job = q.allocate_new_job(unreal.MoviePipelineExecutorJob)
job.sequence = unreal.SoftObjectPath("%(seq)s")
job.map = unreal.SoftObjectPath("/Game/LD/L_LivingDiorama")
job.job_name = "LD_Look"
cfg = job.get_configuration()
cfg.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
cfg.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_PNG)
o = cfg.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
o.output_directory = unreal.DirectoryPath(r"%(out)s")
o.file_name_format = "frame_{frame_number}"
o.output_resolution = unreal.IntPoint(1920, 1080)
o.use_custom_frame_rate = True
o.output_frame_rate = unreal.FrameRate(%(fps)d, 1)
o.override_existing_output = True
ex = sub.render_queue_with_executor(unreal.MoviePipelinePIEExecutor)
print("RENDER " + json.dumps({"started": ex is not None}))
'''


def main():
    views = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    dest = EV / sys.argv[2]
    shots = build_shots(views)
    end = len(views) * HOLD_FRAMES
    RAW.mkdir(parents=True, exist_ok=True)
    for f in RAW.glob("*.png"):
        f.unlink()
    ws = str(YF / "WORKSPACE")
    with UnrealRemote(discover_timeout=300.0) as r:
        print(r.output_text(r.exec_file(
            ENSURE % {"seq": SEQ, "fps": FPS, "end": end}))[-300:])
        print(r.output_text(r.exec_file(
            CAM % {"ws": ws, "shots": json.dumps(shots), "fps": FPS, "seq": SEQ}))[-400:])
        print(r.output_text(r.exec_file(
            REN % {"seq": SEQ, "out": str(RAW), "fps": FPS}))[-200:])

    want = end
    for _ in range(600):
        time.sleep(2.0)
        got = sorted(RAW.glob("*.png"))
        if len(got) >= want and got[-1].stat().st_size > 0:
            time.sleep(3.0)
            break
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    got = sorted(RAW.glob("*.png"))
    for i, v in enumerate(views):
        # keep the LAST frame of each view's hold, so anything that settles has
        # settled by the frame a human looks at
        idx = i * HOLD_FRAMES + HOLD_FRAMES - 1
        if idx < len(got):
            tgt = dest / ("%s.png" % v["name"])
            shutil.copy2(got[idx], tgt)
            out.append({"view": v["name"], "src": got[idx].name,
                        "bytes": tgt.stat().st_size})
        else:
            out.append({"view": v["name"], "src": None, "bytes": None})
    print("LOOK " + json.dumps({"rendered": len(got), "expected": want,
                                "views": out}, default=str))


if __name__ == "__main__":
    main()
