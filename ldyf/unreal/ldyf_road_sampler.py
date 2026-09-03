"""DRAFT in-editor road-geometry sampler (C4) -- ldyf/road_geometry_check.py input.

Runs INSIDE the UE editor Python like ldyf_roads_editor.py / ldyf_playback.py:
no top-level side effects, JSON-able dict returns. It reads the SPAWNED road
components of the PCG volume actor labelled ``LD_RoadsPCG`` (CitySample road
graph) and returns the component snapshot schema that ``ldyf.road_geometry_check``
compares against ``road_spec_v1`` (the independent SUMO input). Nothing here is
the authoring spline: start/end and scale come from the spawned
SplineMeshComponent instances, width/top from mesh/component bounds.

API-verification status
-----------------------
Names marked ``Believed`` are UNVERIFIED against UE 5.8 Python -- the same
convention ldyf_roads_editor.py uses for names its author flagged. Each is
probed on the first in-editor run; a failed read is caught and reported in
``_sampler_notes`` rather than silently dropping the component:
  * PCGSplineMeshComponent derives from SplineMeshComponent, so
    ``get_components_by_class(unreal.SplineMeshComponent)`` on the PCG actor
    returns them (Believed; if the graph spawns separate managed actors
    instead of components on the volume actor, probe for the generated
    actors' owner == the PCG actor and enumerate their components).
  * ``get_start_position()/get_end_position()`` return the spline-mesh control
    points in COMPONENT space; world = ``get_component_transform().transform_position``
    (Believed start/end are expressed in the component frame, so one
    transform is enough -- probe with a strip under a rotated/offset parent).
  * ``get_start_scale()/get_end_scale()``: Vector; the cross-section scale is
    the Y component (the editor writes scale.y = width_effective / mesh width,
    ldyf_roads_editor.py:75,119).
  * StaticMesh width: mesh local Y is the cross-section axis
    (EVIDENCE_road_mesh_bounds.json: SM_Lane_Car_400_500 size = 500 (along
    spline) x 400 (cross-section) x 20). Asset bounds via
    ``mesh.get_bounds().box_extent`` (Believed valid for StaticMesh, unlike the
    degenerate SkeletalMesh case recorded in EVIDENCE_editor_api_probe.json
    lines 115-124; probe against the measured 400/200 values above).
  * top_z is read from the SPAWNED component world bounds
    (``unreal.SystemLibrary.get_component_bounds`` -> origin.z + extent.z),
    matching C1/C4 ("measured from the SPAWNED components, never from the
    authoring splines").
  * ``component_tags``: PCG metadata tags surface as component tags only if
    the graph propagates them (Believed). lane_id / kind are parsed from tags
    ``lane_id:<id>`` / ``kind:<road|sidewalk>`` (the tag vocabulary
    ldyf_roads_editor.py:126-129 writes on LD_Lane proof actors, and the PCG
    graph is expected to mirror it); when absent lane_id stays None and the
    pure checker re-derives attribution by midpoint matching.
  * DynamicMeshComponent bounds (origin, extent) via
    ``unreal.SystemLibrary.get_component_bounds`` (1-argument helper style of
    ldyf_playback.py:487); junction slabs vs ground are told apart by size:
    the largest dynamic mesh whose bbox contains every strip endpoint is the
    ground, the rest are junction slabs (Believed heuristic -- probe the
    material assignment / actor label as the discriminator).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import unreal  # type: ignore[import-not-found]


def _by_label(label: str):
    for a in unreal.EditorLevelLibrary.get_all_level_actors():
        if a is not None and str(a.get_actor_label() or "") == label:
            return a
    return None


def _vec3(v) -> dict:
    return {"x": round(float(v.x), 3) + 0.0,
            "y": round(float(v.y), 3) + 0.0,
            "z": round(float(v.z), 3) + 0.0}


def _bounds_of(comp) -> tuple[dict, dict]:
    """World bbox {min,max} + top_z of a component from its spawned bounds."""
    origin, extent = unreal.SystemLibrary.get_component_bounds(comp)  # Believed 2-tuple
    bmin = {"x": float(origin.x) - float(extent.x),
            "y": float(origin.y) - float(extent.y),
            "z": float(origin.z) - float(extent.z)}
    bmax = {"x": float(origin.x) + float(extent.x),
            "y": float(origin.y) + float(extent.y),
            "z": float(origin.z) + float(extent.z)}
    return {"bounds_min": bmin, "bounds_max": bmax, "top_z": float(origin.z) + float(extent.z)}


def _tags_of(comp) -> list[str]:
    """component_tags if PCG propagated them, else actor tags (Believed API)."""
    for attr in ("component_tags",):
        try:
            t = getattr(comp, attr, None)
            if t is not None:
                return [str(x) for x in t]
        except Exception:
            pass
    try:
        return [str(x) for x in comp.get_owner().get_actor_tags()]
    except Exception:
        return []


def _parse_tags(tags: list[str]) -> tuple[str | None, str | None]:
    lane_id = None
    kind = None
    for t in tags:
        if t.startswith("lane_id:"):
            lane_id = t[len("lane_id:"):] or None
        elif t.startswith("kind:"):
            k = t[len("kind:"):]
            kind = k if k in ("road", "sidewalk") else None
    return lane_id, kind


def _spline_strip(comp, notes: list[str], idx: int) -> dict | None:
    try:
        t = comp.get_component_transform()  # Believed USceneComponent API
        sl = comp.get_start_position()      # Believed: component space
        el = comp.get_end_position()
        start = _vec3(t.transform_position(sl))   # Believed: local -> world
        end = _vec3(t.transform_position(el))
        ss = comp.get_start_scale()               # Believed: Vector(x, y, z)
        es = comp.get_end_scale()
        mesh = None
        try:
            mesh = comp.get_editor_property("static_mesh")  # Believed property name
        except Exception:
            mesh = getattr(comp, "static_mesh", None)
        if mesh is None:
            raise RuntimeError("no static mesh on spline mesh component")
        path = str(mesh.get_path_name())
        mb = mesh.get_bounds()  # Believed BoxSphereBounds; probe .box_extent
        # Cross-section = mesh local Y (EVIDENCE_road_mesh_bounds.json). The
        # mesh X (500 for SM_Lane_Car_400_500) runs along the spline.
        mesh_width_cm = 2.0 * float(mb.box_extent.y)
        bb = _bounds_of(comp)
        lane_id, kind = _parse_tags(_tags_of(comp))
        return {
            "lane_id": lane_id,
            "kind": kind,
            "mesh": path,
            "mesh_width_cm": round(mesh_width_cm, 3) + 0.0,
            "start": start,
            "end": end,
            "start_scale_y": round(float(ss.y), 6) + 0.0,
            "end_scale_y": round(float(es.y), 6) + 0.0,
            "top_z": round(float(bb["top_z"]), 3) + 0.0,
        }
    except Exception as ex:  # noqa: BLE001 - a failed read must not kill the dump
        notes.append(f"spline strip {idx} ({str(comp.get_name())}) unreadable: {ex}")
        return None


def sample_components(pcg_actor_label: str = "LD_RoadsPCG") -> dict:
    """Snapshot of the PCG actor's spawned road geometry: {strips, slabs, ground}.

    Ground heuristic (Believed): among the DynamicMeshComponents on the PCG
    actor, the one whose bbox contains every strip endpoint (2-D) is the
    ground surface; the others are junction slabs. When nothing qualifies,
    ``ground`` is None and the pure checker reports the ground row as failing
    -- a truthful signal to fix the classification, not a hidden pass.
    """
    notes: list[str] = []
    actor = _by_label(pcg_actor_label)
    if actor is None:
        raise ValueError(f"no actor labelled {pcg_actor_label!r} in the level")

    strips: list[dict] = []
    i = 0
    for comp in actor.get_components_by_class(unreal.SplineMeshComponent):
        # PCGSplineMeshComponent derives from SplineMeshComponent (Believed),
        # so one query returns every road strip the graph spawned.
        s = _spline_strip(comp, notes, i)
        if s is not None:
            strips.append(s)
        i += 1

    dyn = list(actor.get_components_by_class(unreal.DynamicMeshComponent))
    meshes = []
    for j, comp in enumerate(dyn):
        try:
            meshes.append({"comp": comp, **_bounds_of(comp)})
        except Exception as ex:  # noqa: BLE001
            notes.append(f"dynamic mesh {j} unreadable: {ex}")

    # Ground = largest dynamic mesh containing every strip endpoint (2-D).
    endpoints = [p for s in strips for p in (s["start"], s["end"])]
    ground = None
    slabs: list[dict] = []
    for m in sorted(meshes, key=lambda m: m["bounds_max"]["x"] - m["bounds_min"]["x"], reverse=True):
        b = m["bounds_min"], m["bounds_max"]
        inside = all(
            b[0]["x"] - 1e-6 <= p["x"] <= b[1]["x"] + 1e-6
            and b[0]["y"] - 1e-6 <= p["y"] <= b[1]["y"] + 1e-6
            for p in endpoints
        ) if endpoints else False
        rec = {"id": str(m["comp"].get_name()),
               "bounds_min": {k: round(v, 3) + 0.0 for k, v in m["bounds_min"].items()},
               "bounds_max": {k: round(v, 3) + 0.0 for k, v in m["bounds_max"].items()},
               "top_z": round(m["top_z"], 3) + 0.0}
        if ground is None and inside:
            ground = rec
        else:
            slabs.append(rec)
    if not dyn:
        notes.append("no DynamicMeshComponent found on the PCG actor "
                     "(junction slabs/ground not sampled)")
    if ground is None:
        notes.append("no dynamic mesh contains all strip endpoints: ground "
                     "classifier (Believed) needs a probe")

    snapshot = {"strips": strips, "slabs": slabs, "ground": ground}
    if notes:
        snapshot["_sampler_notes"] = notes
    return snapshot


def sample_to_file(out_path: str, pcg_actor_label: str = "LD_RoadsPCG") -> dict:
    """Write the snapshot as sorted JSON and return {path, strips, slabs, ground}."""
    snap = sample_components(pcg_actor_label)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, indent=2, sort_keys=True), encoding="utf-8")
    return {"path": str(out), "strips": len(snap["strips"]),
            "slabs": len(snap["slabs"]),
            "ground": snap["ground"] is not None}
