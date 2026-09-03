"""Driver: bake -> cast -> sequence -> cameras -> Movie Render Queue -> MP4.

Deterministic frame authority (contract C3): output frame f is presentation
second f/fps and simulation second t_begin + (f/fps)*rate. Nothing here reads a
wall clock. Usage:

    python CACHE/build_preview.py [--seconds 90] [--fps 24] [--start 110]
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

YF = Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
sys.path.insert(0, str(YF / "WORKSPACE"))
from ldyf.sequence_bake import bake_keys                    # noqa: E402
from ldyf.unreal_remote import UnrealRemote                 # noqa: E402

WS = str(YF / "WORKSPACE").replace("\\", "/")
REC = YF / "PHASE_01/proof/sumo/closure_v2/record_ruled"
EV = YF / "EVIDENCE/PHASE_02"
BAKE = EV / "sequence_bake.json"
FRAMES_DIR = EV / "preview_mrq"
ASM = str(EV / "vehicle_assembly.json").replace("\\", "/")
SURFACE_Z = 20.0     # measured strip top, EVIDENCE/PHASE_02/road_mesh_bounds.json


def run(code: str, timeout_note: str = "") -> str:
    with UnrealRemote(discover_timeout=60.0) as r:
        return r.output_text(r.exec_file(code))


def make_bake(fps: int, start_s: float, seconds: float) -> dict:
    manifest = json.loads((REC / "record_manifest.json").read_text(encoding="utf-8"))
    asm = json.loads(Path(ASM).read_text(encoding="utf-8"))
    names = sorted(asm)
    import hashlib

    def mesh_for_uid(uid: str) -> str:
        if not str(uid).startswith("vehicle:"):
            return "person"
        i = int(hashlib.sha256(uid.encode()).hexdigest()[:8], 16) % len(names)
        return names[i]

    contact = {}
    for n, rec in asm.items():
        bones = rec.get("wheel_bones") or {}
        wheels = rec.get("wheel_meshes") or {}
        radii = [w["radius_cm"] for w in wheels.values() if w.get("radius_cm")]
        if bones and radii:
            bone_z = sum(v[2] for v in bones.values()) / len(bones)
            contact[n] = -(bone_z - sum(radii) / len(radii))
        else:
            contact[n] = float(rec.get("exterior_contact_offset_cm") or 0.0)
    contact["person"] = 5.57      # measured, EVIDENCE/PHASE_02/human_probe.json
    radii_by_mesh = {n: (sum(w["radius_cm"] for w in (asm[n].get("wheel_meshes") or {}).values()) /
                         max(1, len(asm[n].get("wheel_meshes") or {}))) for n in names}
    radii_by_mesh["person"] = None
    doc = bake_keys(REC / "frames.bin", manifest, fps=fps, rate=1.0,
                    t_start_s=start_s, t_end_s=start_s + seconds,
                    surface_z_cm=SURFACE_Z, contact_offsets=contact,
                    mesh_for_uid=mesh_for_uid, wheel_radius_for_mesh=radii_by_mesh,
                    walk_ref_speed_mps=1.4)
    BAKE.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
    return doc


def shots(fps: int, seconds: float) -> list:
    """Five purposeful shots; the closure at sim t=150 s is the middle three."""
    q = seconds / 5.0
    return [
        {"name": "overview", "start_s": 0.0, "end_s": q,
         "loc": [-9000, 9000, 12000], "rot": [-28.0, -45.0, 0.0],
         "loc_end": [-3000, 3000, 9000], "rot_end": [-26.0, -45.0, 0.0]},
        {"name": "intersection", "start_s": q, "end_s": 2 * q,
         "loc": [22000, -20500, 2600], "rot": [-30.0, -120.0, 0.0],
         "loc_end": [21000, -19500, 2400], "rot_end": [-30.0, -110.0, 0.0]},
        {"name": "street", "start_s": 2 * q, "end_s": 3 * q,
         "loc": [20200, -26000, 220], "rot": [-2.0, 90.0, 0.0],
         "loc_end": [20200, -23000, 220], "rot_end": [-2.0, 90.0, 0.0]},
        {"name": "closure", "start_s": 3 * q, "end_s": 4 * q,
         "loc": [26000, -20400, 1500], "rot": [-22.0, 170.0, 0.0],
         "loc_end": [24000, -20400, 1300], "rot_end": [-20.0, 175.0, 0.0]},
        {"name": "after", "start_s": 4 * q, "end_s": seconds,
         "loc": [12000, -12000, 8000], "rot": [-30.0, -35.0, 0.0],
         "loc_end": [16000, -16000, 9000], "rot_end": [-32.0, -40.0, 0.0]},
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=90.0)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--start", type=float, default=110.0)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--skip-bake", action="store_true")
    ns = ap.parse_args()
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    for f in FRAMES_DIR.glob("*.png"):
        f.unlink()

    t0 = time.perf_counter()
    if not ns.skip_bake:
        doc = make_bake(ns.fps, ns.start, ns.seconds)
    else:
        doc = json.loads(BAKE.read_text(encoding="utf-8"))
    print("BAKE", json.dumps(doc.get("counts"), default=str), "frames", doc.get("frames"),
          "seconds", round(time.perf_counter() - t0, 1))

    src = (YF / "WORKSPACE/ldyf/unreal/ldyf_preview.py").read_text(encoding="utf-8")
    head = "import sys\nfor p in ('%s',):\n    (p in sys.path) or sys.path.insert(0, p)\n" % WS
    bake_p = str(BAKE).replace("\\", "/")
    out_p = str(FRAMES_DIR).replace("\\", "/")

    code = head + src + (
        "\nimport json as _j\n"
        "cast = spawn_cast(r'%s', r'%s', surface_z_cm=%r)\n"
        "print('CAST', _j.dumps({k: v for k, v in cast.items() if k != 'contact_offsets'}, default=str)[:500])\n"
        "seqr = build_sequence(r'%s', fps=%d, contact_offsets=cast['contact_offsets'], surface_z_cm=%r)\n"
        "print('SEQ', _j.dumps(seqr, default=str)[:400])\n"
        "cams = add_cameras(%r, fps=%d)\n"
        "print('CAMS', _j.dumps(cams, default=str)[:400])\n"
        "unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()\n"
    ) % (bake_p, ASM, SURFACE_Z, bake_p, ns.fps, SURFACE_Z, shots(ns.fps, ns.seconds), ns.fps)
    print(run(code)[-1400:])

    code2 = head + src + (
        "\nimport json as _j\n"
        "r = render_mrq(r'%s', fps=%d, width=%d, height=%d)\n"
        "print('RENDER', _j.dumps(r, default=str)[:400])\n"
    ) % (out_p, ns.fps, ns.width, ns.height)
    print(run(code2)[-500:])

    expected = int(round(ns.seconds * ns.fps))
    last = -1
    stable = 0
    for _ in range(240):
        time.sleep(10)
        n = len(list(FRAMES_DIR.glob("*.png")))
        print("frames", n, "/", expected, flush=True)
        if n >= expected:
            break
        stable = stable + 1 if n == last else 0
        last = n
        if stable >= 12:
            print("render stalled"); break

    n = len(list(FRAMES_DIR.glob("*.png")))
    mp4 = EV / "phase2_preview.mp4"
    enc = subprocess.run(["ffmpeg", "-y", "-framerate", str(ns.fps), "-i", str(FRAMES_DIR / "frame_%04d.png"),
                          "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(ns.fps), str(mp4)],
                         capture_output=True, text=True)
    probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                            "-show_entries", "stream=nb_read_frames,r_frame_rate,duration,codec_name,width,height",
                            "-of", "json", str(mp4)], capture_output=True, text=True)
    try:
        pj = json.loads(probe.stdout)["streams"][0]
    except Exception:
        pj = {"error": probe.stderr[-300:]}
    rec = {"fps": ns.fps, "seconds_requested": ns.seconds, "frames_rendered": n, "frames_expected": expected,
           "start_sim_s": ns.start, "resolution": [ns.width, ns.height],
           "frame_to_presentation_rule": "presentation_s = frame / fps", "wall_clock_used": False,
           "mp4": str(mp4), "mp4_bytes": mp4.stat().st_size if mp4.exists() else 0,
           "ffmpeg_rc": enc.returncode, "ffprobe": pj, "bake_counts": doc.get("counts"),
           "shots": [s["name"] for s in shots(ns.fps, ns.seconds)]}
    (EV / "mrq_render.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
    print("RENDER RECORD", json.dumps({k: rec[k] for k in ("frames_rendered", "frames_expected", "mp4_bytes", "ffprobe")}, default=str)[:500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
