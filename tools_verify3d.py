"""3-D playback verification (contract C2) against the RENDER path.

The Level Sequence that Movie Render Queue renders is evaluated at three
materially different output frames (before / around / after the closure); the
placed actors are snapshotted from the live world (including the world-space
bottom of each mesh) and compared to the sealed record in X, Y, ground-contact Z
and yaw, with missing/extra actors and an interpolation check between record
frames.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

YF = Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
sys.path.insert(0, str(YF / "WORKSPACE"))
from ldyf.unreal_remote import UnrealRemote            # noqa: E402
from ldyf import playback_verify3d as V3               # noqa: E402

REC = YF / "PHASE_01/proof/sumo/closure_v2/record_ruled"
EV = YF / "EVIDENCE/PHASE_02"
SURFACE_Z = 20.0

SNAPSHOT_CODE = r'''
import unreal, json
LSB = unreal.LevelSequenceEditorBlueprintLibrary
seq = unreal.EditorAssetLibrary.load_asset("/Game/LD/LS_Preview")
LSB.open_level_sequence(seq)
EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
out = {"snapshots": []}
for fr in __FRAMES__:
    LSB.set_current_time(int(fr))
    rows = []
    for a in EAS.get_all_level_actors():
        lab = str(a.get_actor_label())
        if not lab.startswith("LD_CAST_"):
            continue
        uid = None
        for t in a.get_editor_property("tags"):
            if str(t).startswith("uid:"):
                uid = str(t)[4:]
        if uid is None:
            continue
        vis = not a.is_hidden_ed() if hasattr(a, "is_hidden_ed") else True
        loc = a.get_actor_location(); rot = a.get_actor_rotation()
        bottom = None
        # ONLY rendered meshes define the contact plane. The editor's billboard
        # sprite and arrow components have +-128 cm bounds and would otherwise
        # be measured as the actor's "bottom" (found while verifying).
        MESH_TYPES = (unreal.StaticMeshComponent, unreal.SkinnedMeshComponent,
                      unreal.DynamicMeshComponent)
        comps = [c for c in a.get_components_by_class(unreal.PrimitiveComponent)
                 if isinstance(c, MESH_TYPES)]
        zs = []
        for c in comps:
            try:
                o, e, _r = unreal.SystemLibrary.get_component_bounds(c)
                zs.append(float(o.z - e.z))
            except Exception:
                pass
        if zs:
            bottom = min(zs)
        rows.append({"label": lab, "uid": uid, "x": round(float(loc.x), 3), "y": round(float(loc.y), 3),
                     "root_z": round(float(loc.z), 3), "bottom_z": (round(bottom, 3) if bottom is not None else None),
                     "yaw": round(float(rot.yaw), 4), "present": bool(vis)})
    out["snapshots"].append({"frame": int(fr), "actors": rows})
LSB.close_level_sequence()
open(r"__OUT__", "w").write(json.dumps(out, indent=1, default=str))
print("SNAPSHOTS", json.dumps([{"frame": s["frame"], "actors": len(s["actors"])} for s in out["snapshots"]], default=str))
'''


def main() -> int:
    manifest = json.loads((REC / "record_manifest.json").read_text(encoding="utf-8"))
    bake = json.loads((EV / "sequence_bake.json").read_text(encoding="utf-8"))
    fps = bake["fps"]
    t_begin = manifest["clock"]["t_begin"]
    step = manifest["clock"]["step_seconds"]
    # bake["frames"] are ABSOLUTE output frame numbers (frame = presentation_s * fps);
    # the sequence uses local frames (absolute - first).
    first_bake_frame = bake["frames"][0]
    last_bake_frame = bake["frames"][1]
    start_sim = t_begin + (first_bake_frame / fps) * bake.get("rate", 1.0)
    end_sim = t_begin + (last_bake_frame / fps) * bake.get("rate", 1.0)
    def local_of(sim_s):
        return int(round((sim_s - start_sim) * fps / bake.get("rate", 1.0)))
    # three materially different frames: before / around / after the closure at 150 s
    wanted = [start_sim + 1.0, 150.0, min(190.0, end_sim - 1.0)]
    out_frames = sorted({local_of(s) for s in wanted if start_sim <= s <= end_sim})
    interp_sim = 150.0 + step / 2.0     # strictly between two record frames
    interp_local = local_of(interp_sim)
    out_frames = [f for f in out_frames if 0 <= f <= (last_bake_frame - first_bake_frame)]
    if 0 <= interp_local <= (last_bake_frame - first_bake_frame):
        out_frames = sorted(set(out_frames + [interp_local]))
    snap_path = str(EV / "placed_snapshots.json").replace("\\", "/")
    code = SNAPSHOT_CODE.replace("__FRAMES__", json.dumps(out_frames)).replace("__OUT__", snap_path)
    with UnrealRemote(discover_timeout=60.0) as r:
        print(r.output_text(r.exec_file(code))[-400:])
    snaps = json.loads(Path(snap_path).read_text(encoding="utf-8"))["snapshots"]
    frames_path = REC / "frames.bin"
    results = []
    interp_results = []
    for s in snaps:
        sim_t = start_sim + (s["frame"] / fps) * bake.get("rate", 1.0)
        if s["frame"] == interp_local:
            snapshot_t = {"t": sim_t, "surface_z_cm": SURFACE_Z,
                          "actors": [a for a in s["actors"] if a.get("present")]}
            interp_results.append(V3.compare_interpolated(snapshot_t, frames_path, manifest,
                                                          xy_tol_cm=1.0, yaw_tol_deg=1.0))
            continue
        rec_frame = int(round((sim_t - t_begin) / step))
        expected = V3.expected_at_frame(frames_path, manifest, rec_frame)
        snapshot = {"frame": rec_frame, "t": sim_t, "surface_z_cm": SURFACE_Z,
                    "actors": [a for a in s["actors"] if a.get("present")]}
        res = V3.compare_frame(snapshot, expected, surface_z_cm=SURFACE_Z, contact_offsets=None,
                               xy_tol_cm=1.0, z_tol_cm=5.0, yaw_tol_deg=1.0)
        res["output_frame"] = s["frame"]
        res["sim_time_s"] = round(sim_t, 3)
        results.append(res)
    report = V3.build_report(results, interp_results, record_sha256=manifest["binary"]["sha256"],
                             tolerances={"xy_cm": 1.0, "contact_z_cm": 5.0, "yaw_deg": 1.0,
                                         "min_actors": 50})
    V3.write_report(report, EV / "playback_verify3d.json")
    for r_ in results:
        print({k: r_.get(k) for k in ("output_frame", "sim_time_s", "compared", "missing", "extra",
                                      "xy", "contact_z", "yaw", "pass") if k in r_})
    for i_ in interp_results:
        print({k: i_.get(k) for k in ("t", "compared", "xy_max", "yaw_max", "pass") if k in i_})
    print("3D VERIFICATION PASS:", report.get("pass"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
