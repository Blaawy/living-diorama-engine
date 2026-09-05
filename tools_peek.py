"""Render a few frames of the REAL preview sequence, so people and traffic exist.

``tools_look.py`` drives its own ``LS_Look`` sequence, which carries cameras and
nothing else. The cast and vehicle actors are possessed by ``LS_Preview`` and,
when it is not playing, they sit parked at z = -100000 -- off-stage. So every
look frame shows an empty city, and any judgement about crowds, vehicles or
occupancy made from those frames would be wrong.

This renders a short window of ``LS_Preview`` itself through MRQ's custom
playback range, which is the only way to see the world as the deliverable
actually shows it.

Usage::

    py tools_peek.py <start_frame> <count> <out_subdir>
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

YF = Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
sys.path.insert(0, str(YF / "WORKSPACE"))
from ldyf.unreal_remote import UnrealRemote  # noqa: E402

EV = YF / "EVIDENCE" / "PHASE_02"
RAW = EV / "peek_raw"
SEQ = "/Game/LD/LS_Preview"

REN = r'''
import unreal, json
sub = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
q = sub.get_queue()
for j in list(q.get_jobs()):
    q.delete_job(j)
job = q.allocate_new_job(unreal.MoviePipelineExecutorJob)
job.sequence = unreal.SoftObjectPath("%(seq)s")
job.map = unreal.SoftObjectPath("/Game/LD/L_LivingDiorama")
job.job_name = "LD_Peek"
cfg = job.get_configuration()
cfg.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
cfg.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_PNG)
o = cfg.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
o.output_directory = unreal.DirectoryPath(r"%(out)s")
o.file_name_format = "frame_{frame_number}"
o.output_resolution = unreal.IntPoint(1920, 1080)
o.use_custom_frame_rate = True
o.output_frame_rate = unreal.FrameRate(24, 1)
o.override_existing_output = True
# render only the requested window, not all 2160 frames
o.use_custom_playback_range = True
o.custom_start_frame = %(start)d
o.custom_end_frame = %(end)d
ex = sub.render_queue_with_executor(unreal.MoviePipelinePIEExecutor)
print("PEEK " + json.dumps({"started": ex is not None,
                            "range": [%(start)d, %(end)d]}))
'''


def main():
    start = int(sys.argv[1])
    count = int(sys.argv[2])
    dest = EV / sys.argv[3]
    RAW.mkdir(parents=True, exist_ok=True)
    for f in RAW.glob("*.png"):
        f.unlink()
    with UnrealRemote(discover_timeout=300.0) as r:
        print(r.output_text(r.exec_file(
            REN % {"seq": SEQ, "out": str(RAW), "start": start,
                   "end": start + count}))[-300:])
    for _ in range(900):
        time.sleep(2.0)
        got = sorted(RAW.glob("*.png"))
        if len(got) >= count and got[-1].stat().st_size > 0:
            time.sleep(3.0)
            break
    dest.mkdir(parents=True, exist_ok=True)
    got = sorted(RAW.glob("*.png"))
    out = []
    for p in got:
        t = dest / p.name
        shutil.copy2(p, t)
        out.append({"frame": p.name, "bytes": t.stat().st_size})
    print("PEEKED " + json.dumps({"count": len(out), "frames": out[:12]}))


if __name__ == "__main__":
    main()
