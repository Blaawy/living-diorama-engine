"""In-editor construction of the Living Diorama world from `city_layout_v1`.

Footprint splines (one closed rectangle per building slot, tagged by kit) and
street-furniture actors. The PCG graph turns the footprints into extruded
buildings with City Sample facade materials, exactly as City Sample's own
PCG_3_3_1_Buildings does (Create_Mesh_Extrude with a height range).

Runs INSIDE the editor over remote execution. No wall clock, no randomness that
changes between runs: every choice is a sha256 digest of (slot id, seed).
"""
import hashlib
import json
import math
from pathlib import Path

import unreal  # type: ignore[import-not-found]

KIT_TAGS = {0: "ld_bldg_a", 1: "ld_bldg_b", 2: "ld_bldg_c"}


def _digest_index(key: str, seed: int, n: int) -> int:
    h = hashlib.sha256(f"{key}|{seed}".encode("utf-8")).hexdigest()
    return int(h[:8], 16) % max(1, n)


def _actors():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()


def _clear(prefix: str) -> int:
    n = 0
    for a in _actors():
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


def _closed_spline(actor, points, z_cm):
    comp = _add_component(actor, unreal.SplineComponent)
    pts = [unreal.Vector(float(p["x"]), float(p["y"]), float(z_cm)) for p in points]
    comp.set_spline_points(pts, unreal.SplineCoordinateSpace.WORLD, False)
    for i in range(len(pts)):
        comp.set_spline_point_type(i, unreal.SplinePointType.LINEAR, False)
    comp.set_closed_loop(True, False)
    comp.update_spline()
    return comp


def build_building_footprints(layout_path, *, z_cm=0.0, label_prefix="LD_Bldg", seed=20260904,
                              kits=("CHA", "NYA", "SFA")):
    """One closed footprint spline per building slot, tagged by kit.

    The slot gives a frontage point, an outward yaw and a width/depth; the
    footprint is the rectangle behind the frontage line (away from the road).
    """
    layout = json.loads(Path(layout_path).read_text(encoding="utf-8"))
    slots = (layout.get("building_slots") or {}).get("slots") or layout.get("slots") or []
    cleared = _clear(label_prefix)
    built = 0
    by_kit = {}
    for s in slots:
        w = float(s.get("width_cm") or 0.0)
        d = float(s.get("depth_cm") or 0.0)
        if w <= 0 or d <= 0:
            continue
        yaw = math.radians(float(s.get("yaw") or 0.0))
        # outward normal (towards the road) and the along-frontage direction
        nx, ny = math.cos(yaw), math.sin(yaw)
        tx, ty = -ny, nx
        cx, cy = float(s["x"]), float(s["y"])
        # rectangle: frontage line at the slot, extending BACK (-normal) by depth
        corners = [
            {"x": cx + tx * (w / 2.0), "y": cy + ty * (w / 2.0)},
            {"x": cx - tx * (w / 2.0), "y": cy - ty * (w / 2.0)},
            {"x": cx - tx * (w / 2.0) - nx * d, "y": cy - ty * (w / 2.0) - ny * d},
            {"x": cx + tx * (w / 2.0) - nx * d, "y": cy + ty * (w / 2.0) - ny * d},
        ]
        kit = str(s.get("kit") or kits[0])
        ki = kits.index(kit) if kit in kits else _digest_index(str(s.get("slot_id")), seed, len(kits))
        a = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.Actor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
        a.set_actor_label(f"{label_prefix}_{s.get('slot_id')}")
        _closed_spline(a, corners, z_cm)
        a.set_editor_property("tags", ["ld_building", KIT_TAGS.get(ki, "ld_bldg_a"),
                                       f"kit:{kit}", f"slot:{s.get('slot_id')}", f"block:{s.get('block_id')}"])
        built += 1
        by_kit[kit] = by_kit.get(kit, 0) + 1
    return {"footprints": built, "cleared": cleared, "by_kit": by_kit, "z_cm": z_cm}


def build_street_furniture(layout_path, *, meshes, z_cm=20.0, label_prefix="LD_Prop", seed=20260904,
                           max_items=None):
    """Static-mesh props along the road edges from `furniture_slots`.

    `meshes` maps kind -> asset path. Kind order and placement come from the
    layout (deterministic); nothing is random here.
    """
    layout = json.loads(Path(layout_path).read_text(encoding="utf-8"))
    slots = (layout.get("furniture") or layout.get("furniture_slots") or {}).get("slots") or []
    cleared = _clear(label_prefix)
    placed = 0
    by_kind = {}
    missing = []
    for i, s in enumerate(slots):
        if max_items is not None and placed >= max_items:
            break
        kind = str(s.get("kind"))
        path = meshes.get(kind)
        if not path:
            continue
        mesh = unreal.EditorAssetLibrary.load_asset(path)
        if mesh is None:
            if path not in missing:
                missing.append(path)
            continue
        a = unreal.EditorLevelLibrary.spawn_actor_from_object(
            mesh, unreal.Vector(float(s["x"]), float(s["y"]), float(z_cm)),
            unreal.Rotator(0.0, 0.0, float(s.get("yaw") or 0.0)))
        a.set_actor_label(f"{label_prefix}_{kind}_{i}")
        a.set_editor_property("tags", ["ld_furniture", f"kind:{kind}"])
        placed += 1
        by_kind[kind] = by_kind.get(kind, 0) + 1
    return {"placed": placed, "cleared": cleared, "by_kind": by_kind, "missing_assets": missing}


def clear_city(prefixes=("LD_Bldg", "LD_Prop")) -> dict:
    return {p: _clear(p) for p in prefixes}


def city_summary() -> dict:
    counts = {}
    for a in _actors():
        lab = str(a.get_actor_label())
        key = "_".join(lab.split("_")[:2])
        counts[key] = counts.get(key, 0) + 1
    return {"actors": len(_actors()), "by_prefix": counts}
