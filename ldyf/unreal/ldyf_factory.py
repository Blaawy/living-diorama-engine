"""Phase 4 in-editor helpers: what the ENGINE holds for one factory shot.

Appended to `ldyf_preview.py` (unchanged) by `ldyf.factory.render` and run
inside the editor over remote execution. Nothing here places an actor: bodies
are placed only by the baked keys `ldyf_preview.build_sequence` writes.

`evaluate_shot` is the link the camera planner cannot make from the record:
it asks Sequencer to evaluate the shot's sequence at sampled frames, reads
every cast actor's transform and visibility back out of the world, and fires a
line trace from the lens to each subject the planner expects to be seen at that
frame. A subject whose sight line hits something else first is reported as
blocked, with the name of what blocked it.
"""
import json

import unreal  # type: ignore[import-not-found]


def _f_eas():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def set_hidden(prefixes, hide):
    """Hide (or show) level actors that belong to other sequences."""
    n = 0
    for a in _f_eas().get_all_level_actors():
        if a is None:
            continue
        lab = str(a.get_actor_label())
        if any(lab.startswith(p) for p in prefixes):
            a.set_actor_hidden_in_game(bool(hide))
            a.set_is_temporarily_hidden_in_editor(bool(hide))
            n += 1
    return {"touched": n, "hidden": bool(hide)}


def remove_shot(prefixes, sequences):
    """Remove a shot's cast, camera and sequence. The level itself is never saved."""
    eas = _f_eas()
    n = 0
    for a in list(eas.get_all_level_actors()):
        if a is not None and any(str(a.get_actor_label()).startswith(p) for p in prefixes):
            eas.destroy_actor(a)
            n += 1
    gone = []
    for p in sequences:
        if unreal.EditorAssetLibrary.does_asset_exist(p):
            gone.append([p, bool(unreal.EditorAssetLibrary.delete_asset(p))])
    return {"actors_removed": n, "sequences": gone}


MARK_MESH = "/Engine/BasicShapes/Sphere"
MARK_MATERIAL = "/Engine/BasicShapes/BasicShapeMaterial"


def mark_cast(marks, *, label_prefix):
    """Hang a coloured ball over named cast actors, so a viewer can tell them apart.

    SIGNALING, not simulation: the ball is a child component of the cast actor,
    so it is wherever the baked keys put that actor and hidden whenever the
    actor is. It has no collision and casts no shadow. Returns how many of each
    mark were attached -- the caller checks that against the cast.
    """
    mesh = unreal.EditorAssetLibrary.load_asset(MARK_MESH)
    mat = unreal.EditorAssetLibrary.load_asset(MARK_MATERIAL)
    if mesh is None or mat is None:
        return {"ok": False, "error": "marker mesh or material is missing"}
    by_label = {}
    for a in _f_eas().get_all_level_actors():
        if a is not None and str(a.get_actor_label()).startswith(label_prefix + "_"):
            by_label[str(a.get_actor_label())] = a
    out = {"ok": True, "attached": {}, "coloured": {}}
    for m in marks:
        n = c_ok = 0
        r, g, b = m["colour"]
        for uid in m["uids"]:
            a = by_label.get(label_prefix + "_" + uid.replace(":", "_"))
            if a is None:
                continue
            comp = _add_component(a, unreal.StaticMeshComponent)
            comp.set_static_mesh(mesh)
            comp.set_relative_location(unreal.Vector(0.0, 0.0, float(m["z_cm"])), False, False)
            s = float(m["scale"])
            comp.set_relative_scale3d(unreal.Vector(s, s, s))
            comp.set_cast_shadow(False)
            comp.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
            n += 1
            try:
                mid = comp.create_dynamic_material_instance(0, mat)
                mid.set_vector_parameter_value("Color", unreal.LinearColor(r, g, b, 1.0))
                c_ok += 1
            except Exception:
                pass
        out["attached"][m["name"]] = n
        out["coloured"][m["name"]] = c_ok
    return out


def level_state():
    w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    return {"world": str(w.get_name()), "path": str(w.get_path_name()),
            "actors": len(_f_eas().get_all_level_actors())}


def evaluate_shot(frames, expect, cam_loc, aim_height_cm, *, label_prefix, seq_path,
                  clear_within_cm=200.0):
    """Engine readback + sight-line traces at the given sequence frames.

    `expect` maps str(frame) -> [uid, ...]: the subjects the planner counted as
    visible at that frame. Returns, per frame, every cast actor's
    [x, y, z, yaw, hidden] and, per expected subject, "clear", "hidden",
    "missing" or "blocked:<actor label>".
    """
    LSE = unreal.LevelSequenceEditorBlueprintLibrary
    seq = unreal.EditorAssetLibrary.load_asset(seq_path)
    if seq is None or not LSE.open_level_sequence(seq):
        return {"ok": False, "error": "could not open the sequence"}
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    cast = {}
    for a in _f_eas().get_all_level_actors():
        if a is None:
            continue
        lab = str(a.get_actor_label())
        if lab.startswith(label_prefix + "_"):
            cast[lab] = a
    start = unreal.Vector(float(cam_loc[0]), float(cam_loc[1]), float(cam_loc[2]))
    poses, traces = {}, {}
    trace_errors = 0
    for f in frames:
        params = unreal.MovieSceneSequencePlaybackParams()
        params.set_editor_property("frame", unreal.FrameTime(unreal.FrameNumber(int(f))))
        params.set_editor_property("position_type", unreal.MovieScenePositionType.FRAME)
        LSE.set_global_position(params)
        LSE.force_update()
        row = {}
        for lab, a in cast.items():
            loc = a.get_actor_location()
            rot = a.get_actor_rotation()
            row[lab] = [round(loc.x, 3), round(loc.y, 3), round(loc.z, 3),
                        round(rot.yaw, 3), bool(a.is_hidden_ed())]
        poses[str(int(f))] = row
        seen = {}
        for uid in expect.get(str(int(f)), []):
            lab = label_prefix + "_" + uid.replace(":", "_")
            a = cast.get(lab)
            if a is None:
                seen[uid] = "missing"
                continue
            if a.is_hidden_ed():
                seen[uid] = "hidden"
                continue
            loc = a.get_actor_location()
            h = float(aim_height_cm.get(uid, aim_height_cm.get(uid.split(":", 1)[0], 90.0)))
            end = unreal.Vector(loc.x, loc.y, loc.z + h)
            verdict = "clear"
            try:
                hit = unreal.SystemLibrary.line_trace_single(
                    world, start, end, unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, False, [],
                    unreal.DrawDebugTrace.NONE, True)
                if hit is not None:
                    t = hit.to_tuple()
                    dist_to_subject = (end - start).length()
                    if t[9] is not None and t[9] != a and float(t[3]) < dist_to_subject - clear_within_cm:
                        verdict = "blocked:" + str(t[9].get_actor_label())
            except Exception:
                trace_errors += 1
                verdict = "untraced"
            seen[uid] = verdict
        traces[str(int(f))] = seen
    LSE.close_level_sequence()
    return {"ok": True, "actors": len(cast), "poses": poses, "traces": traces,
            "trace_errors": trace_errors}


def dump(path, doc):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(doc, sort_keys=True, default=str))
