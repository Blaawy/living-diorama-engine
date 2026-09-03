"""Deterministic preview: cast, baked Level Sequence, cameras, Movie Render Queue.

Render authority is the FRAME, never the wall clock (contract C3): output frame f
is presentation second f/fps and simulation second t_begin + (f/fps)*rate. The
sequence carries baked transform keys computed by `ldyf.sequence_bake` from the
sealed record, so a slow render cannot produce slow motion.

Cast assembly (measured, EVIDENCE/PHASE_02/vehicle_assembly.json + human_probe.json):
  vehicle = SKM_Exterior_<name> body (painted material slots) + four SM_Wheel_*
            static meshes at the measured wheel-bone offsets; contact plane is the
            wheel bottom (bone_z - wheel radius), never the body bounds.
  person  = City Sample SKM_PlayerMale / SKM_PlayerFemale_Body on SK_Base with
            FP_Walk_F / FP_IdleBase, animation phase offset per uid so the crowd
            never marches in step.
Runs inside the editor over remote execution.
"""
import hashlib
import json
import math
import time
from pathlib import Path

import unreal  # type: ignore[import-not-found]

CAST_PREFIX = "LD_CAST"
CAM_PREFIX = "LD_CAM"
SEQ_PATH = "/Game/LD/LS_Preview"

# Neutral car colours (a deliberate module table; the choice per vehicle is a
# sha256 of the uid, so it never changes between replays).
PAINT_COLOURS = [(0.62, 0.63, 0.65), (0.05, 0.05, 0.06), (0.72, 0.10, 0.10),
                 (0.10, 0.22, 0.45), (0.90, 0.90, 0.88), (0.20, 0.32, 0.25),
                 (0.55, 0.45, 0.20), (0.35, 0.36, 0.40)]
PAINT_PARAMS = ("Color", "BaseColor", "Paint Color", "Tint")

_SKIN_BODY = "/Game/Crowd/Character/Shared/Materials/MetaHuman/M_BodySynthesized"
_SKIN_HEAD = "/Game/Character/Player/Female/Materials/M_Head_Player"
PERSON_VARIANTS = [
    {"mesh": "/Game/Character/Player/Male/Meshes/SKM_PlayerMale",
     "materials": {"M_Body": _SKIN_BODY, "M_Head": _SKIN_HEAD}},
    {"mesh": "/Game/Character/Player/Female/Meshes/SKM_PlayerFemale_Body",
     "materials": {"M_Body": _SKIN_BODY}},
]
WALK_ANIM = "/Game/Character/Player/Female/Anims/Locomotion/FP_Walk_F"
IDLE_ANIM = "/Game/Character/Player/Female/Anims/Locomotion/FP_IdleBase"


def _digest(key: str, n: int) -> int:
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % max(1, n)


def _EAS():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def _clear(prefix: str) -> int:
    n = 0
    for a in _EAS().get_all_level_actors():
        if a is not None and str(a.get_actor_label()).startswith(prefix):
            a.destroy_actor()
            n += 1
    return n


def _add_component(actor, cls):
    sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    handles = sub.k2_gather_subobject_data_for_instance(actor)
    params = unreal.AddNewSubobjectParams(parent_handle=handles[0], new_class=cls, blueprint_context=None)
    handle, fail = sub.add_new_subobject(params)
    obj = unreal.SubobjectDataBlueprintFunctionLibrary.get_associated_object(
        sub.k2_find_subobject_data_from_handle(handle))
    if obj is None:
        raise RuntimeError(f"add_new_subobject({cls}) gave no object: {fail}")
    return obj


def load_assembly(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def vehicle_contact_offset_cm(rec: dict) -> float:
    """Contact plane of an assembled vehicle = the bottom of its wheels."""
    bones = rec.get("wheel_bones") or {}
    wheels = rec.get("wheel_meshes") or {}
    radii = [w["radius_cm"] for w in wheels.values() if w.get("radius_cm")]
    if not bones or not radii:
        return float(rec.get("exterior_contact_offset_cm") or 0.0)
    bone_z = sum(v[2] for v in bones.values()) / len(bones)
    return -(bone_z - (sum(radii) / len(radii)))


def spawn_cast(bake_path: str, assembly_path: str, *, surface_z_cm: float,
               label_prefix: str = CAST_PREFIX) -> dict:
    """One persistent actor per record uid (Sequencer possessables need identity)."""
    bake = json.loads(Path(bake_path).read_text(encoding="utf-8"))
    asm = load_assembly(assembly_path)
    names = sorted(asm.keys())
    cleared = _clear(label_prefix)
    EAL = unreal.EditorAssetLibrary
    made = {"vehicle": 0, "person": 0}
    paint_param_used = None
    missing = []
    applied = []
    contact = {}
    for uid, rec in sorted(bake["actors"].items()):
        kind = rec.get("kind")
        safe = uid.replace(":", "_")
        if kind == "vehicle":
            name = names[_digest(uid, len(names))]
            arec = asm[name]
            body_path = f"/Game/Vehicle/{name}/Mesh/SKM_Exterior_{name}"
            mesh = EAL.load_asset(body_path)
            if mesh is None:
                missing.append(body_path)
                continue
            a = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.Actor, unreal.Vector(0, 0, -100000.0), unreal.Rotator(0, 0, 0))
            a.set_actor_label(f"{label_prefix}_{safe}")
            body = _add_component(a, unreal.PoseableMeshComponent)
            body.set_skinned_asset_and_update(mesh)
            slots = arec.get("paint_slots") or []
            if slots:
                try:
                    mid = body.create_dynamic_material_instance(int(slots[0]))
                    if mid is not None:
                        r, g, b = PAINT_COLOURS[_digest(uid + "|paint", len(PAINT_COLOURS))]
                        for p in PAINT_PARAMS:
                            try:
                                mid.set_vector_parameter_value(p, unreal.LinearColor(r, g, b, 1.0))
                                paint_param_used = paint_param_used or p
                                break
                            except Exception:
                                continue
                except Exception:
                    pass
            # Wheel meshes are authored IN VEHICLE SPACE (measured: SM_Wheel_Front_L
            # bounding-box centre is the wheel position, not the origin). So each
            # wheel gets a pivot SceneComponent AT the wheel centre and the mesh is
            # offset back by -centre; rotating the pivot spins the wheel about its
            # own axle instead of orbiting the vehicle origin.
            for wname, wrec in sorted((arec.get("wheel_meshes") or {}).items()):
                wm = EAL.load_asset(wrec["path"])
                if wm is None:
                    continue
                bb = wm.get_bounding_box()
                cx = (bb.min.x + bb.max.x) / 2.0
                cy = (bb.min.y + bb.max.y) / 2.0
                cz = (bb.min.z + bb.max.z) / 2.0
                pivot = _add_component(a, unreal.SceneComponent)
                pivot.set_relative_location(unreal.Vector(cx, cy, cz), False, False)
                wc = _add_component(a, unreal.StaticMeshComponent)
                wc.set_static_mesh(wm)
                wc.attach_to_component(pivot, "", unreal.AttachmentRule.KEEP_RELATIVE,
                                       unreal.AttachmentRule.KEEP_RELATIVE,
                                       unreal.AttachmentRule.KEEP_RELATIVE, False)
                wc.set_relative_location(unreal.Vector(-cx, -cy, -cz), False, False)
            a.set_editor_property("tags", ["ld_cast", "ld_vehicle", f"uid:{uid}", f"mesh:{name}"])
            contact[uid] = vehicle_contact_offset_cm(arec)
            made["vehicle"] += 1
        elif kind == "person":
            v = PERSON_VARIANTS[_digest(uid + "|person", len(PERSON_VARIANTS))]
            mesh = EAL.load_asset(v["mesh"])
            if mesh is None:
                missing.append(v["mesh"])
                continue
            a = unreal.EditorLevelLibrary.spawn_actor_from_object(mesh, unreal.Vector(0, 0, -100000.0))
            a.set_actor_label(f"{label_prefix}_{safe}")
            comp = a.skeletal_mesh_component
            slot_names = [str(s.material_slot_name) for s in mesh.get_editor_property("materials")]
            for slot_name, mat_path in (v.get("materials") or {}).items():
                mat = EAL.load_asset(mat_path)
                if mat is None:
                    if mat_path not in missing:
                        missing.append(mat_path)
                    continue
                if slot_name in slot_names:
                    comp.set_material(slot_names.index(slot_name), mat)
                    applied.append(f"{slot_name}<-{mat_path.rsplit('/', 1)[1]}")
            walk = EAL.load_asset(WALK_ANIM)
            if walk is not None:
                comp.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
                comp.play_animation(walk, True)
                length = float(walk.get_editor_property("sequence_length"))
                comp.set_position(length * (_digest(uid + "|phase", 1000) / 1000.0), False)
            o, e, _ = unreal.SystemLibrary.get_component_bounds(comp)
            contact[uid] = -100000.0 - (o.z - e.z)
            a.set_editor_property("tags", ["ld_cast", "ld_person", f"uid:{uid}"])
            made["person"] += 1
    return {"spawned": made, "cleared": cleared, "missing_assets": missing[:10], "materials_applied": sorted(set(applied))[:6],
            "paint_param": paint_param_used, "contact_offsets_sample": dict(list(contact.items())[:4]),
            "surface_z_cm": surface_z_cm, "contact_offsets": contact}


def _seq_new(path: str, fps: int, end_frame: int):
    EAL = unreal.EditorAssetLibrary
    if EAL.does_asset_exist(path):
        EAL.delete_asset(path)
    name = path.rsplit("/", 1)[1]
    folder = path.rsplit("/", 1)[0]
    seq = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        name, folder, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
    seq.set_display_rate(unreal.FrameRate(fps, 1))
    seq.set_playback_start(0)
    seq.set_playback_end(end_frame)
    return seq


def build_sequence(bake_path: str, *, fps: int, contact_offsets: dict, surface_z_cm: float,
                   label_prefix: str = CAST_PREFIX, seq_path: str = SEQ_PATH) -> dict:
    """Transform + visibility tracks from the bake. Keys are the render authority."""
    bake = json.loads(Path(bake_path).read_text(encoding="utf-8"))
    first, last = bake["frames"]
    seq = _seq_new(seq_path, fps, int(last - first) + 1)
    by_label = {}
    for a in _EAS().get_all_level_actors():
        lab = str(a.get_actor_label())
        if lab.startswith(label_prefix):
            by_label[lab] = a
    keys_written = 0
    bound = 0
    t0 = time.perf_counter()
    LINEAR = unreal.MovieSceneKeyInterpolation.LINEAR
    for uid, rec in sorted(bake["actors"].items()):
        a = by_label.get(f"{label_prefix}_{uid.replace(':', '_')}")
        if a is None:
            continue
        b = seq.add_possessable(a)
        tr = b.add_track(unreal.MovieScene3DTransformTrack)
        sec = tr.add_section()
        sec.set_start_frame(0)
        sec.set_end_frame(int(last - first) + 1)
        ch = sec.get_all_channels()
        for k in rec["keys"]:
            fn = unreal.FrameNumber(int(k["f"] - first))
            ch[0].add_key(fn, float(k["x"]), interpolation=LINEAR)
            ch[1].add_key(fn, float(k["y"]), interpolation=LINEAR)
            ch[2].add_key(fn, float(k["z"]), interpolation=LINEAR)
            ch[5].add_key(fn, float(k["yaw"]), interpolation=LINEAR)
            keys_written += 4
        vis = b.add_track(unreal.MovieSceneVisibilityTrack)
        vsec = vis.add_section()
        vsec.set_start_frame(0)
        vsec.set_end_frame(int(last - first) + 1)
        vch = vsec.get_all_channels()[0]
        vch.add_key(unreal.FrameNumber(0), False)
        for on, off in rec.get("presence") or []:
            vch.add_key(unreal.FrameNumber(int(on - first)), True)
            vch.add_key(unreal.FrameNumber(int(off - first) + 1), False)
            keys_written += 2
        bound += 1
    unreal.EditorAssetLibrary.save_loaded_asset(seq)
    return {"sequence": seq_path, "bound_actors": bound, "keys": keys_written,
            "frames": [0, int(last - first) + 1], "fps": fps,
            "seconds": round(time.perf_counter() - t0, 2)}


def add_cameras(shots: list, *, fps: int, seq_path: str = SEQ_PATH) -> dict:
    """One CineCameraActor per shot plus a camera-cut track. `shots` items:
    {"name","start_s","end_s","loc":[x,y,z],"rot":[pitch,yaw,roll],
     "loc_end":[...] optional, "rot_end":[...] optional, "fov" optional}."""
    seq = unreal.EditorAssetLibrary.load_asset(seq_path)
    _clear(CAM_PREFIX)
    cut = seq.add_track(unreal.MovieSceneCameraCutTrack)
    LINEAR = unreal.MovieSceneKeyInterpolation.LINEAR
    made = []
    for s in shots:
        loc = s["loc"]
        rot = s["rot"]
        cam = unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.CineCameraActor, unreal.Vector(*loc), unreal.Rotator(rot[2], rot[0], rot[1]))
        cam.set_actor_label(f"{CAM_PREFIX}_{s['name']}")
        cam.set_editor_property("tags", ["ld_camera", f"shot:{s['name']}"])
        if s.get("fov"):
            cc = cam.camera_component
            cc.set_editor_property("current_focal_length", float(s["fov"]))
        b = seq.add_possessable(cam)
        tr = b.add_track(unreal.MovieScene3DTransformTrack)
        sec = tr.add_section()
        f0, f1 = int(round(s["start_s"] * fps)), int(round(s["end_s"] * fps))
        sec.set_start_frame(f0)
        sec.set_end_frame(f1)
        ch = sec.get_all_channels()
        le = s.get("loc_end") or loc
        re_ = s.get("rot_end") or rot
        for fr, L, R in ((f0, loc, rot), (f1, le, re_)):
            ch[0].add_key(unreal.FrameNumber(fr), float(L[0]), interpolation=LINEAR)
            ch[1].add_key(unreal.FrameNumber(fr), float(L[1]), interpolation=LINEAR)
            ch[2].add_key(unreal.FrameNumber(fr), float(L[2]), interpolation=LINEAR)
            ch[3].add_key(unreal.FrameNumber(fr), float(R[2]), interpolation=LINEAR)
            ch[4].add_key(unreal.FrameNumber(fr), float(R[0]), interpolation=LINEAR)
            ch[5].add_key(unreal.FrameNumber(fr), float(R[1]), interpolation=LINEAR)
        cs = cut.add_section()
        cs.set_start_frame(f0)
        cs.set_end_frame(f1)
        cs.set_camera_binding_id(unreal.MovieSceneSequenceExtensions.get_binding_id(seq, b))
        made.append({"name": s["name"], "frames": [f0, f1]})
    unreal.EditorAssetLibrary.save_loaded_asset(seq)
    return {"cameras": made, "count": len(made)}


def render_mrq(out_dir: str, *, fps: int, width: int = 1920, height: int = 1080,
               seq_path: str = SEQ_PATH, level: str = "/Game/LD/L_LivingDiorama") -> dict:
    sub = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
    q = sub.get_queue()
    for j in list(q.get_jobs()):
        q.delete_job(j)
    job = q.allocate_new_job(unreal.MoviePipelineExecutorJob)
    job.sequence = unreal.SoftObjectPath(seq_path)
    job.map = unreal.SoftObjectPath(level)
    job.job_name = "LD_Phase2_Preview"
    cfg = job.get_configuration()
    cfg.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
    cfg.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_PNG)
    o = cfg.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    o.output_directory = unreal.DirectoryPath(out_dir)
    o.file_name_format = "frame_{frame_number}"
    o.output_resolution = unreal.IntPoint(width, height)
    o.use_custom_frame_rate = True
    o.output_frame_rate = unreal.FrameRate(fps, 1)
    o.override_existing_output = True
    ex = sub.render_queue_with_executor(unreal.MoviePipelinePIEExecutor)
    return {"started": ex is not None, "out_dir": out_dir, "fps": fps,
            "resolution": [width, height], "sequence": seq_path,
            "settings": [str(s.get_class().get_name()) for s in cfg.get_all_settings()]}
