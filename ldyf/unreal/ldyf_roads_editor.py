"""road_spec_v1 lane spline actors + 5 cm read-back. Runs INSIDE the UE editor
Python (unreal, file I/O), source-loaded over remote exec like ldyf_playback.py
(ldyf/unreal_remote.py, IN_ENGINE_PLAYBACK_PROOF.md): no top-level side
effects, JSON-able dict returns, absolute paths, unreal.log progress.
Polylines are ALREADY Unreal cm (ldyf.coords was applied when the spec was
written, ldyf/roads.py) -- never re-transform; only z_cm is added. Only
label_prefix (LD_Lane) actors and our own PCG label are ours; nothing else is
moved. Idempotency = CLEAR FIRST: build/place destroy their own label actors,
then respawn, so two runs converge. Splines LINEAR (SUMO polylines are
piecewise linear; linear spline == polyline, so the 5 cm centreline law
measures real geometry; CURVE_CUSTOM_TANGENT would deviate between vertices).
closed=False. width_cm null (roads.py law 3: absence -> null, never a guessed
default) tags as width_cm:None: explicit absence, not an invented number.

Authored by DeepSeek analyst (run yf_p2_analysts/spline_actors) from the dumps
and proven Phase 1 conventions; API names it flagged as unverified are marked
"Believed" in comments and are verified by the first in-editor run.
"""
import json
import math
from pathlib import Path

import unreal  # type: ignore[import-not-found]


def _prefix(prefix):
    return [a for a in unreal.EditorLevelLibrary.get_all_level_actors()
            if a is not None and str(a.get_actor_label() or "").startswith(prefix)]


def _spec(spec_path):
    s = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    if not isinstance(s.get("edges"), list):
        raise ValueError(f"{spec_path}: not road_spec_v1 (no edges list)")
    return s


def add_component(actor, cls):
    """Add a component to a level actor (verified UE 5.8 route, editor_api_probe.json):
    AActor has no add_component_by_class in Python; the Subobject Data Subsystem
    creates the subobject and get_associated_object resolves the instance."""
    sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    handles = sub.k2_gather_subobject_data_for_instance(actor)
    params = unreal.AddNewSubobjectParams(parent_handle=handles[0], new_class=cls, blueprint_context=None)
    handle, fail = sub.add_new_subobject(params)
    data = sub.k2_find_subobject_data_from_handle(handle)
    obj = unreal.SubobjectDataBlueprintFunctionLibrary.get_associated_object(data)
    if obj is None:
        raise RuntimeError(f"add_new_subobject({cls}) gave no object: {fail}")
    return obj


def _add_spline(actor):
    return add_component(actor, unreal.SplineComponent)


# Cross-section reference widths of the meshes the road graph stretches along
# the splines (measured in-editor: EVIDENCE/PHASE_02/road_mesh_bounds.json).
MESH_WIDTH_CM = {"road": 400.0, "sidewalk": 200.0}


def lane_kind(lane):
    """A SUMO lane whose allow list is exactly pedestrians is a sidewalk."""
    allow = lane.get("allow") or []
    return "sidewalk" if allow == ["pedestrian"] else "road"


def _fill(comp, polyline, z_cm, scale_y=1.0):
    pts = [unreal.Vector(float(p["x"]), float(p["y"]), float(z_cm)) for p in polyline]
    comp.set_spline_points(pts, unreal.SplineCoordinateSpace.WORLD, False)
    for i in range(len(pts)):                       # verified API: per-point type
        comp.set_spline_point_type(i, unreal.SplinePointType.LINEAR, False)
        # cross-section scale: the spline mesh's start/end scale is computed from
        # the control-point scale, so width_cm_effective / mesh width lands here
        comp.set_scale_at_spline_point(i, unreal.Vector(1.0, float(scale_y), 1.0), False)
    comp.set_closed_loop(False, False)
    comp.update_spline()


def build_lane_actors(spec_path, *, include_internal=False, kinds=("road",),
                      z_cm=0.0, label_prefix="LD_Lane"):
    unreal.log(f"[ldyf_roads_editor] build_lane_actors {spec_path}")
    s = _spec(spec_path)
    cleared = 0
    for a in _prefix(label_prefix):          # clear first; ours by label
        a.destroy_actor()
        cleared += 1
    n = skipped_internal = skipped_other = skipped_degenerate = 0
    labels = []
    for e in s["edges"]:
        edge_id = str(e.get("id"))
        fn = e.get("function") or "normal"
        if fn == "normal":
            build = True
        elif fn == "internal":
            build = include_internal
            if not include_internal:
                skipped_internal += len(e.get("lanes") or [])
        else:                                # connector/crossing/walkingarea
            build = False
            skipped_other += len(e.get("lanes") or [])
        if not build:
            continue
        for ln in e.get("lanes") or []:
            poly = ln.get("polyline") or []
            if len(poly) < 2:
                skipped_degenerate += 1
                continue
            lane_id = str(ln["id"])
            actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
                unreal.Actor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
            if actor is None:
                raise RuntimeError("spawn_actor_from_class returned None")
            label = f"{label_prefix}_{lane_id}"
            actor.set_actor_label(label)
            comp = _add_spline(actor)
            kind = lane_kind(ln)
            w_eff = ln.get("width_cm_effective")
            scale_y = (float(w_eff) / MESH_WIDTH_CM[kind]) if w_eff else 1.0
            _fill(comp, poly, z_cm, scale_y)
            try:
                comp.rename(new_name=f"lane_{lane_id}")
            except Exception:  # noqa: BLE001 - name is a convenience, the label carries the id
                pass
            w = ln.get("width_cm")            # None -> "width_cm:None" (absence)
            actor.set_editor_property("tags", ["ld_lane", f"ld_{kind}", f"lane_id:{lane_id}",
                                               f"edge_id:{edge_id}", f"width_cm:{w}",
                                               f"width_cm_effective:{w_eff}", f"width_source:{ln.get('width_source')}",
                                               f"kind:{kind}"])
            n += 1
            if len(labels) < 5:
                labels.append(label)
    unreal.log(f"[ldyf_roads_editor] built {n}")
    return {"actors": n, "lanes": n, "skipped_internal": skipped_internal,
            "skipped_other": skipped_other, "skipped_degenerate": skipped_degenerate,
            "labels": labels, "cleared": cleared}


def build_junction_actors(spec_path, *, z_cm=0.0, label_prefix="LD_Junction"):
    """One CLOSED linear spline actor per SUMO junction polygon, tagged
    `ld_junction`; the road graph fills them as slabs. Clear-first, like lanes."""
    s = _spec(spec_path)
    cleared = 0
    for a in _prefix(label_prefix):
        a.destroy_actor()
        cleared += 1
    n = skipped = 0
    for j in s.get("junctions") or []:
        poly = j.get("polygon") or []
        if len(poly) < 3:
            skipped += 1
            continue
        jid = str(j["id"])
        actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.Actor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
        actor.set_actor_label(f"{label_prefix}_{jid}")
        comp = _add_spline(actor)
        pts = [unreal.Vector(float(p["x"]), float(p["y"]), float(z_cm)) for p in poly]
        comp.set_spline_points(pts, unreal.SplineCoordinateSpace.WORLD, False)
        for i in range(len(pts)):
            comp.set_spline_point_type(i, unreal.SplinePointType.LINEAR, False)
        comp.set_closed_loop(True, False)
        comp.update_spline()
        actor.set_editor_property("tags", ["ld_junction", f"junction_id:{jid}", f"type:{j.get('type')}",
                                           f"incoming:{','.join(j.get('incoming_edge_ids') or [])}"])
        n += 1
    unreal.log(f"[ldyf_roads_editor] junctions built {n}")
    return {"actors": n, "skipped_no_polygon": skipped, "cleared": cleared}


def clear_lane_actors(label_prefix="LD_Lane"):
    n = 0
    for a in _prefix(label_prefix):
        a.destroy_actor()
        n += 1
    return {"destroyed": n}


def _at(comp, d):
    v = comp.get_location_at_distance_along_spline(d, unreal.SplineCoordinateSpace.WORLD)
    return {"x": round(float(v.x), 3) + 0.0,
            "y": round(float(v.y), 3) + 0.0,
            "z": round(float(v.z), 3) + 0.0}


def _samples(comp, step_cm):
    length = float(comp.get_spline_length())
    if length <= 0.0 or step_cm <= 0.0:
        return []
    out = []
    d = 0.0
    while d < length - 1e-6:          # interiors at k*step, as resample_polyline
        out.append(_at(comp, d))
        d += step_cm
    out.append(_at(comp, length))     # endpoint preserved exactly
    clean = []
    for p in out:                     # drop float-noise duplicates (< 1 mm)
        if clean and math.hypot(p["x"] - clean[-1]["x"], p["y"] - clean[-1]["y"]) < 1e-3:
            continue
        clean.append(p)
    return clean


def read_back_splines(label_prefix="LD_Lane", step_cm=100.0):
    lanes = {}
    for a in _prefix(label_prefix):
        lab = str(a.get_actor_label() or "")
        for comp in a.get_components_by_class(unreal.SplineComponent):
            cname = str(comp.get_name())
            if cname.startswith("lane_"):
                lid = cname[5:]
            else:
                lid = lab[len(label_prefix) + 1:] if lab.startswith(label_prefix + "_") else lab
            if lid in lanes:
                raise ValueError(f"duplicate lane id {lid!r} among {label_prefix} actors")
            lanes[lid] = _samples(comp, step_cm)
    return {"lanes": dict(sorted(lanes.items())), "count": len(lanes)}


def _roads(*hints):
    import importlib
    import sys
    try:
        return importlib.import_module("ldyf.roads")
    except ImportError:
        pass
    for hp in hints:
        p = Path(hp).resolve()
        for anc in [p, *p.parents]:
            if (anc / "ldyf" / "roads.py").is_file():
                sp = str(anc)
                if sp not in sys.path:
                    sys.path.insert(0, sp)
                return importlib.import_module("ldyf.roads")
    raise ImportError("ldyf.roads not importable: put the WORKSPACE root on "
                      "sys.path before loading, or pass an in-workspace path")


def write_read_back(spec_path, out_path, *, step_cm=100.0):
    s = _spec(spec_path)
    roads = _roads(spec_path, out_path)
    rb = read_back_splines(step_cm=step_cm)
    measured = rb["lanes"]
    raw = {str(ln["id"]): ln["polyline"]
           for e in s["edges"] for ln in e.get("lanes") or []}
    summary = roads.check_centrelines(s, measured, tolerance_cm=5.0)  # 5 cm law
    per = {lid: {"spec_points": len(raw[lid]), "measured_points": len(measured[lid]),
                 "error_cm": roads.centreline_error_cm(raw[lid], measured[lid])}
           for lid in sorted(measured)}
    result = {"schema_version": "road_readback_v1",
              "spec_path": str(Path(spec_path).resolve()), "step_cm": step_cm,
              "tolerance_cm": 5.0, "summary": summary, "lanes": per}
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return {"lanes_checked": summary["lanes_checked"],
            "worst_cm": summary["worst_cm"], "pass": summary["pass"]}


def place_pcg_volume(graph_path, extent_cm, center_cm, label="LD_RoadsPCG"):
    unreal.log(f"[ldyf_roads_editor] place_pcg_volume {graph_path}")
    for a in _prefix(label):          # actors with our label family: clear first
        a.destroy_actor()
    cx, cy, cz = (list(center_cm) + [0.0, 0.0, 0.0])[:3]
    vol = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.PCGVolume, unreal.Vector(cx, cy, cz), unreal.Rotator(0, 0, 0))
    if vol is None:
        raise RuntimeError("could not spawn unreal.PCGVolume")
    vol.set_actor_label(label)
    w, d, h = (list(extent_cm) + [2000.0, 2000.0, 2000.0])[:3]
    _, ext = unreal.SystemLibrary.get_actor_bounds(vol, False)
    s = [((w / 2.0) / float(ext.x)) if float(ext.x) > 1e-6 else 1.0,
         ((d / 2.0) / float(ext.y)) if float(ext.y) > 1e-6 else 1.0,
         ((h / 2.0) / float(ext.z)) if float(ext.z) > 1e-6 else 1.0]
    vol.set_actor_scale3d(unreal.Vector(s[0], s[1], s[2]))
    pcg = vol.get_component_by_class(unreal.PCGComponent)
    if pcg is None:
        raise RuntimeError("PCGVolume has no PCGComponent")
    graph = unreal.EditorAssetLibrary.load_asset(graph_path)
    if graph is None:
        raise ValueError(f"load_asset returned None for {graph_path}")
    pcg.set_editor_property("graph", graph)
    unreal.log(f"[ldyf_roads_editor] placed {label}")
    return {"label": label}
