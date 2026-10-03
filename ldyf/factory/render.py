"""Stage 9: render. Every shot through the Phase 2 production path, bound to the record.

For each beat of the timeline:

    sealed record --ldyf.sequence_bake--> keys          (pure Python, byte-identical)
    keys --ldyf_preview.spawn_cast/build_sequence--> Level Sequence in the locked city
    Sequencer --evaluate + read back--> the ENGINE's poses, compared with the keys
    lens --line trace--> is each expected subject's sight line clear in the engine?
    Movie Render Queue --> one PNG per frame --> one H.264 segment per shot

This is the path Phase 2 was accepted on and Phase 3 played its agent episode
through. `ldyf/unreal/ldyf_preview.py` is run as it stands. The level is never
saved: the map file's sha256 is taken before and after.

WHAT THE ENGINE CHECK ADDS. The camera planner measured, from the record, which
subjects each shot holds. Here that measurement is REPEATED on the positions the
engine itself reports, and a subject whose sight line a tree, a pole or a
building corner blocks is not counted. A shot whose requirement no longer holds
is refused (`event_not_visible_in_engine`); the episode is not assembled around
a claim the picture does not carry.

RESUME. A shot is finished when its sealed `shot_render.json` exists, names the
same inputs (shot, record, bake, code) and its segment still hashes to what was
sealed. A finished shot is not rendered again; anything else is rendered from
scratch. A shot the renderer did not complete leaves no `shot_render.json`, so
an interrupted render can never be mistaken for a finished one.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from . import FactoryError
from . import camera as C
from .record import Record
from .util import canonical_bytes, read_json, seal, sha256_bytes, sha256_file, verify_seal, write_json
from .world import REPO_ROOT

SHOT_SCHEMA = "episode_shot_render_v1"
RENDER_SCHEMA = "episode_render_v1"
CAST, CAM = "LD_P4CAST", "LD_P4CAM"
SEQ_DIR = "/Game/LD"
ENGINE_SAMPLE_SECONDS = 1.0
POSE_TOLERANCE_CM = 1.0
STILLS = 3


class RenderError(FactoryError):
    stage = "render"


def _unreal_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "unreal"


def code_hash() -> str:
    """Identity of the code that draws a shot. A change here invalidates finished shots."""
    h = hashlib.sha256()
    for p in (_unreal_dir() / "ldyf_preview.py", _unreal_dir() / "ldyf_factory.py",
              Path(__file__).resolve(), Path(__file__).resolve().parents[1] / "sequence_bake.py",
              Path(__file__).resolve().with_name("camera.py")):
        h.update(p.read_bytes())
    return h.hexdigest()


def run_editor(code: str) -> str:
    from ..unreal_remote import UnrealRemote, UnrealRemoteError
    try:
        with UnrealRemote(discover_timeout=60.0) as r:
            return r.output_text(r.exec_file(code))
    except UnrealRemoteError as e:
        code = "editor_failed" if "reported failure" in str(e) else "editor_unreachable"
        raise RenderError(code, str(e)[:900])


def _editor_source() -> str:
    # utf-8-sig: ldyf_preview.py carries a BOM, a syntax error once a line is prepended
    head = "import sys\nfor p in (%r,):\n    (p in sys.path) or sys.path.insert(0, p)\n" % \
           str(REPO_ROOT).replace("\\", "/")
    return (head + (_unreal_dir() / "ldyf_preview.py").read_text(encoding="utf-8-sig") + "\n"
            + (_unreal_dir() / "ldyf_factory.py").read_text(encoding="utf-8-sig") + "\n")


def _editor_call(body: str, result_path: Path) -> dict[str, Any]:
    result_path.unlink(missing_ok=True)
    out = run_editor(_editor_source() + body)
    if not result_path.is_file():
        raise RenderError("editor_failed", f"the editor produced no result: {out[-600:]}")
    return json.loads(result_path.read_text(encoding="utf-8"))


# --- bake ----------------------------------------------------------------------------

def bake_shot(record_dir: Path, sim_start: float, seconds: float, fps: int,
              world: dict[str, Any]) -> dict[str, Any]:
    """The Phase 2 bake, pointed at one shot's window of one sealed record."""
    from ..sequence_bake import bake_keys
    u = world["unreal"]
    asm = json.loads((REPO_ROOT / u["vehicle_assembly"]).read_text(encoding="utf-8"))
    names = sorted(asm)

    def mesh_for_uid(uid: str) -> str:
        if not str(uid).startswith("vehicle:"):
            return "person"
        return names[int(hashlib.sha256(uid.encode()).hexdigest()[:8], 16) % len(names)]

    contact: dict[str, float] = {}
    for n, rec in asm.items():
        bones = rec.get("wheel_bones") or {}
        radii = [w["radius_cm"] for w in (rec.get("wheel_meshes") or {}).values() if w.get("radius_cm")]
        if bones and radii:
            contact[n] = -(sum(v[2] for v in bones.values()) / len(bones) - sum(radii) / len(radii))
        else:
            contact[n] = float(rec.get("exterior_contact_offset_cm") or 0.0)
    contact["person"] = float(u["person_contact_offset_cm"])
    radii_by_mesh: dict[str, Any] = {
        n: (sum(w["radius_cm"] for w in (asm[n].get("wheel_meshes") or {}).values())
            / max(1, len(asm[n].get("wheel_meshes") or {}))) for n in names}
    radii_by_mesh["person"] = None
    manifest = json.loads((record_dir / "record_manifest.json").read_text(encoding="utf-8"))
    return bake_keys(record_dir / "frames.bin", manifest, fps=fps, rate=1.0,
                     t_start_s=sim_start, t_end_s=sim_start + seconds,
                     surface_z_cm=float(u["surface_z_cm"]), contact_offsets=contact,
                     mesh_for_uid=mesh_for_uid, wheel_radius_for_mesh=radii_by_mesh,
                     walk_ref_speed_mps=float(u["walk_ref_speed_mps"]))


# --- one shot ------------------------------------------------------------------------

def beat_frames(beat: dict[str, Any], fps: int) -> int:
    n = int(round(float(beat["seconds"]) * fps))
    if abs(n / fps - float(beat["seconds"])) > 1e-9:
        raise RenderError("bad_length", f"beat {beat['id']!r}: {beat['seconds']} s is not a whole "
                                        "number of frames")
    return n


def scene_hashes(world: dict[str, Any]) -> dict[str, str]:
    """The files a shot is drawn from besides its record: the locked level, the
    vehicle assembly the cast is built from and the city layout the planner and
    the engine check count occlusion against. A change in any of them makes every
    finished shot stale."""
    u = world["unreal"]
    return {"level_file": sha256_file(REPO_ROOT / u["level_file"]),
            "vehicle_assembly": sha256_file(REPO_ROOT / u["vehicle_assembly"]),
            "city_layout": sha256_file(REPO_ROOT / u["city_layout"])}


def shot_inputs(beat: dict[str, Any], shot: dict[str, Any], record_sha: str, fps: int,
                res: list[int], scene: dict[str, str]) -> dict[str, Any]:
    return {"beat": beat["id"], "shot_sha256": sha256_bytes(canonical_bytes(shot)),
            "record_frames_sha256": record_sha, "fps": fps, "resolution": list(res),
            "frames": beat_frames(beat, fps), "code_sha256": code_hash(), "scene_sha256": scene}


def _label(uid: str) -> str:
    return CAST + "_" + uid.replace(":", "_")


def engine_measure(shot: dict[str, Any], rec: Record, net: Any, blocks, res: list[int], fps: int,
                   ev: dict[str, Any], bake: dict[str, Any], sample_frames: list[int]) -> dict[str, Any]:
    """Compare the engine's evaluation with the bake, and re-measure the shot on it."""
    first = int(bake["frames"][0])
    by_frame: dict[int, dict[str, dict]] = {}
    for uid, a in bake["actors"].items():
        for k in a["keys"]:
            by_frame.setdefault(int(k["f"]) - first, {})[uid] = k
    wanted = set(sample_frames)
    worst_pos = worst_yaw = 0.0
    vis_mismatch = 0
    compared = 0
    lens = C.Lens(shot["camera"]["loc"], shot["camera"]["rot"], shot["camera"]["fov_deg"], res)
    corridor = C.shot_corridor(shot, net)
    stopped_only = bool(shot.get("counted_stopped_only"))
    subjects = [u for u in shot["subjects"]["uids"] if u in rec.tracks]
    # Which way an untraced subject counts depends on what the beat claims. For a
    # PRESENCE claim ("at least 3 are in the picture") only a traced, clear sight
    # line counts. For an ABSENCE claim ("0 of them are here") every subject the
    # engine puts inside the frame counts, traced or not: the engine may never
    # make an absence easier to meet.
    absence = "max_visible" in shot["require"]
    if int(ev.get("trace_errors", 0)):
        raise RenderError("engine_trace_failed", f"beat {shot['beat']!r}: {ev.get('trace_errors')} "
                                                 "sight-line traces failed in the engine")
    counts, blocked_by, times = [], {}, []
    untraced = 0
    for f in sample_frames:
        row = ev["poses"].get(str(f))
        if row is None:
            raise RenderError("engine_disagrees", f"the engine returned no poses for frame {f}")
        keys = by_frame.get(f, {})
        for uid in bake["actors"]:
            pose = row.get(_label(uid))
            if pose is None:
                raise RenderError("engine_disagrees", f"no cast actor for {uid} in the level")
            k = keys.get(uid)
            compared += 1
            if (k is None) != bool(pose[4]):
                vis_mismatch += 1
                continue
            if k is not None:
                worst_pos = max(worst_pos, abs(pose[0] - k["x"]), abs(pose[1] - k["y"]),
                                abs(pose[2] - k["z"]))
                worst_yaw = max(worst_yaw, abs((pose[3] - k["yaw"] + 180.0) % 360.0 - 180.0))
        t = shot["sim_start"] + f / fps
        rf = rec.frame_of(t)
        n = 0
        tr = ev["traces"].get(str(f), {})
        for uid in subjects:
            pose = row.get(_label(uid))
            if pose is None or pose[4]:
                continue
            if not C.counted(lens, rec, rec.tracks[uid], rf, pose[0], pose[1], blocks, corridor,
                             stopped_only):
                continue
            verdict = tr.get(uid, "missing")
            if absence:
                n += 1
                continue
            if verdict.startswith("blocked:"):
                blocked_by[verdict[8:]] = blocked_by.get(verdict[8:], 0) + 1
                continue
            if verdict != "clear":
                untraced += 1
                continue
            n += 1
        counts.append(n)
        times.append(t)
    if vis_mismatch or worst_pos > POSE_TOLERANCE_CM:
        raise RenderError(
            "engine_disagrees",
            f"beat {shot['beat']!r}: the engine's evaluation differs from the baked keys "
            f"(position {worst_pos:.3f} cm, {vis_mismatch} visibility mismatches of {compared})")
    met, frac = C.check_requirement(shot["require"], {"per_sample": counts}, shot["sim_start"], times)
    return {"sample_frames": sample_frames, "poses_compared": compared,
            "max_position_error_cm": round(worst_pos, 4), "max_yaw_error_deg": round(worst_yaw, 4),
            "visibility_mismatches": vis_mismatch,
            "subjects_visible_per_sample": counts,
            "subjects_visible_min": min(counts), "subjects_visible_max": max(counts),
            "subjects_visible_last": counts[-1],
            "sight_line_blocked_by": dict(sorted(blocked_by.items())),
            "trace_errors": int(ev.get("trace_errors", 0)),
            "subjects_untraced_not_counted": untraced,
            "samples_meeting_requirement": round(frac, 4), "requirement_met": bool(met)}


def _expectation(shot: dict[str, Any], rec: Record, net: Any, blocks, res: list[int], fps: int,
                 sample_frames: list[int]) -> dict[str, list[str]]:
    """Per sampled frame, the subjects the RECORD puts in the picture (to be traced)."""
    lens = C.Lens(shot["camera"]["loc"], shot["camera"]["rot"], shot["camera"]["fov_deg"], res)
    corridor = C.shot_corridor(shot, net)
    out = {}
    for f in sample_frames:
        rf = rec.frame_of(shot["sim_start"] + f / fps)
        seen = []
        for uid in shot["subjects"]["uids"]:
            tr = rec.tracks.get(uid)
            i = tr.index_at(rf) if tr is not None else -1
            if i >= 0 and C.counted(lens, rec, tr, rf, tr.x[i], tr.y[i], blocks, corridor,
                                    bool(shot.get("counted_stopped_only"))):
                seen.append(uid)
        out[str(f)] = seen
    return out


def _ffprobe_frames(path: Path) -> int:
    run = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                          "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True)
    try:
        return int(run.stdout.strip().split(",")[0])
    except ValueError:
        return -1


def _longest_freeze(path: Path) -> float:
    """Longest stretch ffmpeg's freezedetect calls frozen (seconds). Evidence, not a gate
    by itself: a fixed camera on a still street is allowed to be still."""
    run = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(path), "-vf",
                          "freezedetect=n=-60dB:d=0.25", "-map", "0:v:0", "-f", "null", "-"],
                         capture_output=True, text=True)
    durs = [float(x) for x in re.findall(r"freeze_duration:\s*([0-9.]+)", run.stderr)]
    return max(durs, default=0.0)


def render_shot(beat: dict[str, Any], shot: dict[str, Any], rec: Record, record_dir: Path,
                world: dict[str, Any], net: Any, blocks, out_dir: Path, *, fps: int, res: list[int],
                log: Callable[[str], None] = print, frame_timeout_s: float = 240.0) -> dict[str, Any]:
    """Bake, build, check in the engine, render and encode ONE shot."""
    bid = beat["id"]
    out_dir = out_dir.resolve()      # the editor has its own working directory
    record_dir = record_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "shot_render.json").unlink(missing_ok=True)
    frames_dir = out_dir / "frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir()
    t0 = time.perf_counter()
    n = beat_frames(beat, fps)
    seq = f"{SEQ_DIR}/LS_P4_{bid}"

    bake = bake_shot(record_dir, shot["sim_start"], shot["seconds"], fps, world)
    first, last = bake["frames"]
    if last - first + 1 != n:
        raise RenderError("bad_bake", f"beat {bid!r}: the bake holds {last - first + 1} frames, the "
                                      f"timeline {n}")
    if bake.get("missing_contact_offsets"):
        raise RenderError("bad_bake", f"beat {bid!r}: actors without a contact offset "
                                      f"{bake['missing_contact_offsets'][:4]}")
    bake_path = out_dir / "sequence_bake.json"
    bake_bytes = json.dumps(bake, indent=1, sort_keys=True).encode("utf-8")
    bake_path.write_bytes(bake_bytes)
    bake_sha = sha256_bytes(bake_bytes)
    t_bake = time.perf_counter() - t0

    step = int(round(ENGINE_SAMPLE_SECONDS * fps))
    sample_frames = list(range(0, n, step))
    expect = _expectation(shot, rec, net, blocks, res, fps, sample_frames)
    cam = [{"name": bid, "start_s": 0.0, "end_s": float(shot["seconds"]), "loc": shot["camera"]["loc"],
            "rot": shot["camera"]["rot"], "fov_deg": shot["camera"]["fov_deg"]}]
    u = world["unreal"]
    asm = str(REPO_ROOT / u["vehicle_assembly"]).replace("\\", "/")
    bp = str(bake_path).replace("\\", "/")
    result_path = out_dir / "engine_build.json"
    marks = [{"name": name, "uids": m["uids"], "colour": m["colour"], "z_cm": m["z_cm"],
              "scale": m["scale"]} for name, m in sorted((shot.get("marks") or {}).items())]
    # the sight line is traced to the MARK of a marked subject (what a viewer looks
    # for), and to the body of an unmarked one
    aim: dict[str, float] = {"person": 90.0, "vehicle": 75.0}
    for m in marks:
        for uid in m["uids"]:
            aim[uid] = float(m["z_cm"])
    body = (
        "res = {}\n"
        f"res['level'] = level_state()\n"
        f"res['hidden'] = set_hidden({list(u['foreign_actor_prefixes'])!r}, True)\n"
        f"cast = spawn_cast({bp!r}, {asm!r}, surface_z_cm={float(u['surface_z_cm'])!r}, label_prefix={CAST!r})\n"
        "res['cast'] = {k: v for k, v in cast.items() if k not in ('contact_offsets', 'contact_offsets_sample')}\n"
        f"res['marks'] = mark_cast({marks!r}, label_prefix={CAST!r})\n"
        f"res['sequence'] = build_sequence({bp!r}, fps={fps}, contact_offsets=cast['contact_offsets'], "
        f"surface_z_cm={float(u['surface_z_cm'])!r}, label_prefix={CAST!r}, seq_path={seq!r})\n"
        f"res['cameras'] = add_cameras({cam!r}, fps={fps}, seq_path={seq!r}, cam_prefix={CAM!r})\n"
        f"res['animation'] = add_person_animation({bp!r}, fps={fps}, label_prefix={CAST!r}, seq_path={seq!r})\n"
        f"res['evaluate'] = evaluate_shot({sample_frames!r}, {expect!r}, {shot['camera']['loc']!r}, "
        f"{aim!r}, label_prefix={CAST!r}, seq_path={seq!r})\n"
        f"dump({str(result_path).replace(chr(92), '/')!r}, res)\n")
    built = _editor_call(body, result_path)
    if str(built["level"]["path"]).split(".", 1)[0] != u["level"]:
        raise RenderError("wrong_level", f"the editor has {built['level']['path']} open, not {u['level']}")
    if built["cast"].get("missing_assets"):
        raise RenderError("missing_assets", f"cast assets are missing: {built['cast']['missing_assets']}")
    if not built["animation"].get("ok") or not built["evaluate"].get("ok"):
        raise RenderError("editor_failed", f"beat {bid!r}: {built['animation']} / "
                                           f"{built['evaluate'].get('error')}")
    if not built["marks"].get("ok"):
        raise RenderError("editor_failed", f"beat {bid!r}: markers: {built['marks'].get('error')}")
    marked = {}
    for m in marks:
        present = sum(1 for u in m["uids"] if u in bake["actors"])
        got = built["marks"]["attached"].get(m["name"])
        if got != present or built["marks"]["coloured"].get(m["name"]) != present:
            raise RenderError("engine_disagrees", f"beat {bid!r}: {present} actors should carry the "
                                                  f"{m['name']} mark, the engine attached {got}")
        marked[m["name"]] = present
    if built["sequence"]["bound_actors"] != len(bake["actors"]):
        raise RenderError("engine_disagrees", f"beat {bid!r}: {built['sequence']['bound_actors']} actors "
                                              f"bound, the bake has {len(bake['actors'])}")
    engine = engine_measure(shot, rec, net, blocks, res, fps, built["evaluate"], bake, sample_frames)
    t_build = time.perf_counter() - t0 - t_bake
    if not engine["requirement_met"]:
        raise RenderError(
            "event_not_visible_in_engine",
            f"beat {bid!r}: in the engine the camera holds {engine['subjects_visible_min']}.."
            f"{engine['subjects_visible_max']} subjects; the beat requires {shot['require']}. "
            f"Sight lines blocked by {engine['sight_line_blocked_by']}")

    fd = str(frames_dir).replace("\\", "/")
    result2 = out_dir / "engine_render.json"
    started = _editor_call(
        f"dump({str(result2).replace(chr(92), '/')!r}, render_mrq({fd!r}, fps={fps}, width={res[0]}, "
        f"height={res[1]}, seq_path={seq!r}, level={u['level']!r}))\n", result2)
    if not started.get("started"):
        raise RenderError("render_not_started", f"beat {bid!r}: Movie Render Queue did not start")
    last_n, last_change = -1, time.perf_counter()
    while True:
        time.sleep(4)
        have = len(list(frames_dir.glob("frame_*.png")))
        if have != last_n:
            last_n, last_change = have, time.perf_counter()
        if have >= n:
            time.sleep(6)                       # let the last frame finish writing
            break
        if time.perf_counter() - last_change > frame_timeout_s:
            raise RenderError("render_incomplete",
                              f"beat {bid!r}: the renderer stopped at {have} of {n} frames")
    pngs = sorted(frames_dir.glob("frame_*.png"))
    if len(pngs) != n:
        raise RenderError("render_incomplete", f"beat {bid!r}: {len(pngs)} frames on disk, {n} expected")
    t_render = time.perf_counter() - t0 - t_bake - t_build
    digest = hashlib.sha256()
    hashes = []
    for p in pngs:
        h = sha256_file(p)
        hashes.append(h)
        digest.update(h.encode())
    segment = out_dir / "segment.mp4"
    enc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-framerate", str(fps), "-start_number", "0",
         "-i", str(frames_dir / "frame_%04d.png"), "-c:v", "libx264", "-preset", "medium",
         "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(fps), "-an", str(segment)],
        capture_output=True, text=True)
    if enc.returncode != 0:
        raise RenderError("encode_failed", f"beat {bid!r}: {enc.stderr[-400:]}")
    if _ffprobe_frames(segment) != n:
        raise RenderError("render_incomplete", f"beat {bid!r}: the segment holds "
                                               f"{_ffprobe_frames(segment)} frames, {n} expected")
    stills = []
    for j in range(STILLS):
        idx = min(n - 1, int(round((j + 0.5) * n / STILLS)))
        dst = out_dir / f"still_{j + 1}.jpg"
        subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(pngs[idx]),
                        "-vf", "scale=960:-1", "-q:v", "3", str(dst)], capture_output=True)
        if not dst.is_file():
            raise RenderError("encode_failed", f"beat {bid!r}: still {dst.name} was not written")
        stills.append({"file": dst.name, "frame": idx, "sha256": sha256_file(dst),
                       "sim_second": round(shot["sim_start"] + idx / fps, 3)})
    freeze = _longest_freeze(segment)
    asset = REPO_ROOT / "LivingDioramaYF" / "Content" / "LD" / f"LS_P4_{bid}.uasset"
    asset_sha = sha256_file(asset) if asset.is_file() else None
    result3 = out_dir / "engine_cleanup.json"
    _editor_call(f"dump({str(result3).replace(chr(92), '/')!r}, "
                 f"remove_shot({[CAST + '_', CAM + '_']!r}, {[seq]!r}))\n", result3)
    shutil.rmtree(frames_dir)
    bake_path.unlink()
    for tmp in ("engine_build.json", "engine_render.json", "engine_cleanup.json"):
        (out_dir / tmp).unlink(missing_ok=True)
    doc = {
        "schema_version": SHOT_SCHEMA,
        "inputs": shot_inputs(beat, shot, rec.frames_sha256, fps, res, scene_hashes(world)),
        "arm": shot["arm"], "sim_start": shot["sim_start"], "sim_end": shot["sim_end"],
        "sequence_bake_sha256": bake_sha, "bake_actors": len(bake["actors"]),
        "bake_keys": bake["counts"]["keys"],
        "level_sequence": seq, "level_sequence_asset_sha256": asset_sha,
        "cast": built["cast"].get("spawned"), "animation": {
            k: built["animation"].get(k) for k in ("persons", "sections", "person_frames_by_state")},
        "engine": engine, "marks_attached": marked,
        "frames_expected": n, "frames_rendered": len(pngs),
        "unique_frames": len(set(hashes)), "frames_digest_sha256": digest.hexdigest(),
        "segment": {"file": "segment.mp4", "sha256": sha256_file(segment),
                    "bytes": segment.stat().st_size, "frames": n, "codec": "libx264 crf 18 yuv420p"},
        "longest_freeze_seconds": round(freeze, 3),
        "stills": stills,
        "pipeline": ["ldyf.sequence_bake.bake_keys", "ldyf_preview.spawn_cast",
                     "ldyf_preview.build_sequence", "ldyf_preview.add_cameras",
                     "ldyf_preview.add_person_animation", "ldyf_factory.evaluate_shot",
                     "ldyf_preview.render_mrq", "ffmpeg libx264"],
        "shot_render_hash": "",
    }
    doc = seal(doc, "shot_render_hash")
    write_json(out_dir / "shot_render.json", doc)
    write_json(out_dir / "timing.json", {"bake_s": round(t_bake, 1), "build_s": round(t_build, 1),
                                         "render_s": round(t_render, 1),
                                         "total_s": round(time.perf_counter() - t0, 1)})
    log(f"    {bid}: {n} frames, engine holds {engine['subjects_visible_min']}.."
        f"{engine['subjects_visible_max']}, pose error {engine['max_position_error_cm']} cm, "
        f"{time.perf_counter() - t0:.0f} s")
    return doc


def shot_is_finished(shot_dir: Path, inputs: dict[str, Any]) -> dict[str, Any] | None:
    """The sealed render of this shot, if it is finished AND still current."""
    p = shot_dir / "shot_render.json"
    if not p.is_file():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        verify_seal(doc, "shot_render_hash", "shot_render.json")
    except Exception:  # noqa: BLE001 - an unreadable or altered document is simply not finished
        return None
    if doc.get("schema_version") != SHOT_SCHEMA or doc.get("inputs") != inputs:
        return None
    seg = shot_dir / doc["segment"]["file"]
    if not seg.is_file() or sha256_file(seg) != doc["segment"]["sha256"]:
        return None
    if doc["frames_rendered"] != doc["frames_expected"] or not doc["engine"]["requirement_met"]:
        return None
    return doc


def render_episode(story: dict[str, Any], shots: dict[str, Any], recs: dict[str, Record],
                   sim_dir: Path, world: dict[str, Any], net: Any, blocks, render_dir: Path, *,
                   fps: int, res: list[int], resume: bool = True, only: list[str] | None = None,
                   log: Callable[[str], None] = print) -> dict[str, Any]:
    """Render every shot that is not already finished. Returns what was done."""
    if shots.get("story_hash") != story.get("story_hash"):
        raise RenderError("stale_lineage", "the shots were planned for a different story")
    fps, res = int(fps), list(res)
    render_dir = render_dir.resolve()
    render_dir.mkdir(parents=True, exist_ok=True)
    level = REPO_ROOT / world["unreal"]["level_file"]
    level_before = sha256_file(level)
    rendered, reused = [], []
    try:
        for beat in story["beats"]:
            bid = beat["id"]
            if only is not None and bid not in only:
                continue
            shot = shots["shots"][bid]
            rec = recs[shot["arm"]]
            inputs = shot_inputs(beat, shot, rec.frames_sha256, fps, res, scene_hashes(world))
            if resume and shot_is_finished(render_dir / bid, inputs) is not None:
                reused.append(bid)
                log(f"    {bid}: finished, not rendered again")
                continue
            render_shot(beat, shot, rec, sim_dir / f"record_{shot['arm']}", world, net, blocks,
                        render_dir / bid, fps=fps, res=res, log=log)
            rendered.append(bid)
    finally:
        # whatever happened, leave the editor as it was found
        try:
            tmp = render_dir / "engine_restore.json"
            restore = [p for p in world["unreal"]["foreign_actor_prefixes"]
                       if p in ("LD_CAST_", "LD_ClosureProp")]
            _editor_call(
                f"r = remove_shot({[CAST + '_', CAM + '_']!r}, "
                f"{[SEQ_DIR + '/LS_P4_' + b['id'] for b in story['beats']]!r})\n"
                f"r['shown'] = set_hidden({restore!r}, False)\n"
                f"dump({str(tmp).replace(chr(92), '/')!r}, r)\n", tmp)
            tmp.unlink(missing_ok=True)
        except RenderError as e:
            log(f"    (editor not restored: {e.message[:200]})")
    level_after = sha256_file(level)
    if level_after != level_before:
        raise RenderError("level_changed", "the level file changed during the render; the locked "
                                           "city must not be saved by the factory")
    return {"rendered": rendered, "reused": reused, "level_file_sha256": level_after}


def seal_render(story: dict[str, Any], shots: dict[str, Any], recs: dict[str, Record],
                render_dir: Path, *, fps: int, res: list[int], world: dict[str, Any],
                level_sha: str | None = None) -> dict[str, Any]:
    """The render manifest: every beat finished and current, or a refusal.

    It is also the PICTURE the narration is bound to: per beat, what the engine
    was measured to hold.
    """
    fps, res = int(fps), list(res)
    rows: dict[str, Any] = {}
    total = 0
    scene = scene_hashes(world)
    for beat in story["beats"]:
        bid = beat["id"]
        shot = shots["shots"][bid]
        inputs = shot_inputs(beat, shot, recs[shot["arm"]].frames_sha256, fps, res, scene)
        doc = shot_is_finished(render_dir / bid, inputs)
        if doc is None:
            raise RenderError("render_incomplete",
                              f"beat {bid!r} has no finished, current render; the episode is not "
                              "assembled around a missing shot")
        rows[bid] = ({"beat": bid, "arm": doc["arm"], "frames": doc["frames_rendered"],
                     "segment_sha256": doc["segment"]["sha256"],
                     "shot_render_hash": doc["shot_render_hash"],
                     "frames_digest_sha256": doc["frames_digest_sha256"],
                     "sequence_bake_sha256": doc["sequence_bake_sha256"],
                     "engine_subjects_visible_min": doc["engine"]["subjects_visible_min"],
                     "engine_subjects_visible_max": doc["engine"]["subjects_visible_max"],
                     "engine_subjects_visible_last": doc["engine"]["subjects_visible_last"],
                     "marks_attached": doc.get("marks_attached"),
                     "engine_max_position_error_cm": doc["engine"]["max_position_error_cm"],
                     "sight_line_blocked_by": doc["engine"]["sight_line_blocked_by"],
                     "unique_frames": doc["unique_frames"],
                     "longest_freeze_seconds": doc["longest_freeze_seconds"]})
        total += doc["frames_rendered"]
    doc = {"schema_version": RENDER_SCHEMA, "story_hash": story["story_hash"],
           "shots_hash": shots["shots_hash"], "fps": fps, "resolution": res,
           "code_sha256": code_hash(), "level_file_sha256": level_sha, "scene_sha256": scene,
           "frames_total": total, "shots": rows, "render_hash": ""}
    return seal(doc, "render_hash")


def load_render(path: str | Path) -> dict[str, Any]:
    doc = read_json(path, "render.json", error=RenderError)
    if doc.get("schema_version") != RENDER_SCHEMA:
        raise RenderError("bad_version", f"render.json declares {doc.get('schema_version')!r}")
    try:
        verify_seal(doc, "render_hash", "render.json")
    except FactoryError as e:
        raise RenderError("corrupt", e.message)
    return doc
