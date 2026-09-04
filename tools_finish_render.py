"""Wait for the MRQ frames to settle, then encode and write the render record."""
from __future__ import annotations
import json, subprocess, time
from pathlib import Path
YF = Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
EV = YF / "EVIDENCE" / "PHASE_02"
OUTDIR = EV / "preview_mrq"
FPS, SECONDS, W, H = 24, 90.0, 1920, 1080
expected = int(round(SECONDS * FPS))

last, stable = -1, 0
for _ in range(360):
    n = len(list(OUTDIR.glob("*.png")))
    if n == last:
        stable += 1
        if n >= expected and stable >= 3:
            break
        if stable >= 18:
            break
    else:
        stable = 0
    last = n
    print("frames %d / %d" % (n, expected), flush=True)
    time.sleep(10)

n = len(list(OUTDIR.glob("*.png")))
mp4 = EV / "phase2_preview.mp4"
if mp4.exists():
    mp4.unlink()
enc = subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-start_number", "0",
                      "-i", str(OUTDIR / "frame_%04d.png"), "-c:v", "libx264", "-crf", "18",
                      "-preset", "medium", "-pix_fmt", "yuv420p", str(mp4)],
                     capture_output=True, text=True)
probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                        "-show_entries",
                        "stream=codec_name,width,height,r_frame_rate,duration,nb_read_frames",
                        "-of", "json", str(mp4)], capture_output=True, text=True)
pj = json.loads(probe.stdout)["streams"][0] if probe.returncode == 0 else {}
plan = json.loads((EV / "shot_plan.json").read_text(encoding="utf-8"))
rec = {"fps": FPS, "seconds_requested": SECONDS, "frames_rendered": n,
       "frames_expected": expected, "start_sim_s": plan["sim_window"][0],
       "resolution": [W, H],
       "frame_to_presentation_rule": "presentation_s = frame / fps",
       "wall_clock_used": False, "mp4": str(mp4),
       "mp4_bytes": mp4.stat().st_size if mp4.exists() else 0,
       "ffmpeg_rc": enc.returncode, "ffprobe": pj,
       "shots": [{"name": s["name"], "kind": s["kind"], "target": s["target"],
                  "actors_in_view_estimate": s.get("actors_in_view_estimate"),
                  "frames": [s["start_frame"], s["end_frame"]]} for s in plan["shots"]],
       "camera_source": "ldyf.shot_planner over the sealed record"}
(EV / "mrq_render.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
print("RENDER RECORD " + json.dumps({k: rec[k] for k in
      ("frames_rendered", "frames_expected", "mp4_bytes", "ffmpeg_rc", "ffprobe")}, default=str))
