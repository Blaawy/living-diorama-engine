"""Add level-wide inventory (C5) and the strengthened loop audit (C6).

Both are appended to the existing modules; every v1 symbol keeps working.
"""
from pathlib import Path

W = Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY\WORKSPACE\ldyf")

INV = '''

# --- level-wide inventory (contract C5) -------------------------------------

LEVEL_INVENTORY_VERSION = "level_inventory_v1"

#: Any of these substrings in a LOWER-CASED asset path means a blockout mesh.
BLOCKOUT_MARKERS = ("/engine/basicshapes/", "basicshapes", "/engine/enginemeshes/",
                    "/engine/editormeshes/")
#: Engine primitive names that are blockout wherever they are mounted from /Engine.
BLOCKOUT_ENGINE_NAMES = ("cube", "sphere", "cylinder", "cone", "plane")


def _lower_assets(actor: dict) -> list:
    out = []
    for c in actor.get("components") or []:
        a = c.get("asset_lower") or (c.get("asset") or "").lower() or None
        if a:
            out.append(a)
    return out


def is_blockout_asset(asset_lower: str | None) -> bool:
    """Case-insensitive, mount-agnostic blockout test."""
    if not asset_lower:
        return False
    a = asset_lower
    if any(m in a for m in BLOCKOUT_MARKERS):
        return True
    if a.startswith("/engine/"):
        name = a.rsplit("/", 1)[-1].split(".")[0]
        if name in BLOCKOUT_ENGINE_NAMES:
            return True
    return False


def _comp_classes(actor: dict) -> set:
    return {str(c.get("class") or "").lower() for c in actor.get("components") or []}


def classify_level_actor(actor: dict) -> dict:
    """Role of one `level_dump_v1` actor. Rules are data, evaluated in order."""
    cls = str(actor.get("class") or "")
    lcls = cls.lower()
    comps = _comp_classes(actor)
    assets = _lower_assets(actor)
    tags = [str(t).lower() for t in (actor.get("tags") or [])]
    label = str(actor.get("label") or "").lower()
    blockout = [a for a in assets if is_blockout_asset(a)]
    has_mesh = any(k in comps for k in ("staticmeshcomponent", "instancedstaticmeshcomponent",
                                        "skeletalmeshcomponent", "poseablemeshcomponent",
                                        "splinemeshcomponent", "dynamicmeshcomponent"))
    role, reason = "unknown", "no rule matched"
    if "pcgcomponent" in comps:
        role, reason = "pcg_volume", "actor carries a PCGComponent"
    elif not has_mesh and "splinecomponent" in comps:
        role, reason = "authoring", "spline-only actor (authoring input, renders nothing)"
    elif any(k in lcls for k in ("directionallight", "skylight", "pointlight", "spotlight", "rectlight")):
        role, reason = "light", f"actor class {cls}"
    elif "skyatmosphere" in lcls or "exponentialheightfog" in lcls or "volumetriccloud" in lcls:
        role, reason = "sky", f"actor class {cls}"
    elif "camera" in lcls:
        role, reason = "camera", f"actor class {cls}"
    elif "volume" in lcls:
        role, reason = "volume", f"actor class {cls}"
    elif any("ld_vehicle" == t or t.startswith("mesh:veh") for t in tags) or any("/game/vehicle/" in a for a in assets):
        role, reason = "vehicle", "vehicle asset path or ld_vehicle tag"
    elif "ld_person" in tags or any("/game/character/" in a for a in assets):
        role, reason = "pedestrian", "character asset path or ld_person tag"
    elif any("meshes/roads/" in a for a in assets) or "splinemeshcomponent" in comps:
        sidewalk = any("_200_200" in a for a in assets) or "sidewalk" in label or "ld_sidewalk" in tags
        role = "sidewalk" if sidewalk else "road"
        reason = "spline-mesh strip from the road mesh set"
    elif "dynamicmeshcomponent" in comps:
        role, reason = "pcg_surface", "PCG-generated dynamic mesh (ground / junction / building mass)"
    elif any("/building/" in a or "bldg" in a for a in assets):
        role, reason = "building", "building asset path"
    elif has_mesh:
        role, reason = "prop", "mesh actor with no more specific rule"
    return {"role": role, "role_reason": reason, "blockout": bool(blockout),
            "blockout_assets": sorted(set(blockout))[:4], "assets": sorted(set(assets))[:6],
            "components": sorted(comps)}


def level_inventory(dump: dict, *, min_building_kits: int = 3, min_vehicle_wheels: int = 4) -> dict:
    """Inventory of an entire level (`level_dump_v1`), not just spawned actors."""
    roles = {}
    blockout_actors = []
    unknown_actors = []
    kits = set()
    vehicles = wheels_ok = 0
    persons = persons_animated = 0
    pcg_surfaces = 0
    for a in dump.get("actors") or []:
        c = classify_level_actor(a)
        roles[c["role"]] = roles.get(c["role"], 0) + 1
        if c["blockout"]:
            blockout_actors.append({"label": a.get("label"), "assets": c["blockout_assets"]})
        if c["role"] == "unknown":
            unknown_actors.append(a.get("label"))
        if c["role"] == "pcg_surface":
            pcg_surfaces += 1
        if c["role"] == "vehicle":
            vehicles += 1
            n = 0
            for comp in a.get("components") or []:
                nm = f"{comp.get('name','')} {comp.get('class','')}".lower()
                if "wheel" in nm:
                    n += 1
            if n >= min_vehicle_wheels:
                wheels_ok += 1
        if c["role"] == "pedestrian":
            persons += 1
            if any(comp.get("animation") or comp.get("anim_class") for comp in a.get("components") or []):
                persons_animated += 1
        for asset in c["assets"]:
            if "/building/" in asset:
                seg = asset.split("/building/", 1)[1].split("/")[0]
                kits.add(seg)
    for t in ("kit:",):
        for a in dump.get("actors") or []:
            for tag in a.get("tags") or []:
                if str(tag).startswith(t):
                    kits.add(str(tag).split(":", 1)[1])
    building_kits = sorted(kits)
    out = {
        "schema_version": LEVEL_INVENTORY_VERSION,
        "level": dump.get("level"),
        "counts_by_role": dict(sorted(roles.items())),
        "actors": len(dump.get("actors") or []),
        "blockout_actors": blockout_actors,
        "blockout_count": len(blockout_actors),
        "building_kits": {"kits": building_kits, "count": len(building_kits),
                          "pass": len(building_kits) >= min_building_kits},
        "vehicles": {"count": vehicles, "with_min_wheels": wheels_ok,
                     "pass": wheels_ok == vehicles},
        "pedestrians": {"count": persons, "animated": persons_animated,
                        "pass": persons_animated == persons},
        "pcg_surfaces": pcg_surfaces,
        "unknown_actors": sorted(unknown_actors)[:20],
        "params": {"min_building_kits": min_building_kits, "min_vehicle_wheels": min_vehicle_wheels},
    }
    out["pass"] = (out["blockout_count"] == 0 and out["building_kits"]["pass"]
                   and out["vehicles"]["pass"] and out["pedestrians"]["pass"])
    return out


def write_level_inventory(dump_path, out_path, **params) -> dict:
    import json as _json
    from pathlib import Path as _Path
    dump = _json.loads(_Path(dump_path).read_text(encoding="utf-8"))
    rep = level_inventory(dump, **params)
    _Path(out_path).write_text(_json.dumps(rep, indent=2, sort_keys=True), encoding="utf-8")
    return rep
'''

LOOP = '''

# --- loop audit v2 (contract C6) --------------------------------------------

LOOP_AUDIT_V2_VERSION = "loop_audit_v2"


def _windows_all_pairs(cells, window, horizon):
    """Every pair of identical windows (not only the first occurrence)."""
    seen = {}
    repeats = []
    stationary = 0
    for i in range(0, max(0, len(cells) - window + 1)):
        w = tuple(cells[i:i + window])
        if len(set(w)) == 1:
            stationary += 1
            continue
        for j in seen.get(w, ()):  # ALL earlier starts, not just the first
            if horizon is None or (i - j + window) <= horizon:
                repeats.append({"start_a": j, "start_b": i})
        seen.setdefault(w, []).append(i)
    return repeats, stationary


def _headings(track, quant_deg=45.0):
    import math
    out = []
    for (t0, x0, y0, _z0), (t1, x1, y1, _z1) in zip(track, track[1:]):
        dx, dy = x1 - x0, y1 - y0
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            out.append(None)
            continue
        a = math.degrees(math.atan2(dy, dx)) % 360.0
        out.append(int(round(a / quant_deg)) % int(round(360.0 / quant_deg)))
    return out


def _stops(track, cell_cm, speed_eps_cm=10.0):
    """Cells where the actor essentially stopped (consecutive samples within eps)."""
    import math
    stops = []
    for (t0, x0, y0, _z0), (t1, x1, y1, _z1) in zip(track, track[1:]):
        if math.hypot(x1 - x0, y1 - y0) < speed_eps_cm:
            c = (int(math.floor(x1 / cell_cm)), int(math.floor(y1 / cell_cm)))
            if not stops or stops[-1] != c:
                stops.append(c)
    return stops


def audit_record_v2(frames_path, manifest, *, windows_s=(6.0, 8.0, 12.0, 20.0),
                    rates_hz=(1.0, 2.0), horizons_s=(120.0, 300.0, None),
                    cell_cm=100.0, dest_ratio_min=0.6, periodicity_threshold=0.5,
                    patrol_cells=2):
    """Several independent loop tests; the honest boundary is reported, not hidden."""
    base = audit_record(frames_path, manifest, cell_cm=cell_cm, rate_hz=rates_hz[0],
                        dest_ratio_min=dest_ratio_min)
    kinds = {a["uid"]: a.get("kind") for a in manifest["actors"]}
    grid = []
    patrol_windows = 0
    patrol_actors = set()
    cross_actor = []
    route_repeats = {}
    dest_cycles = {}
    for rate in rates_hz:
        tracks = sampled_tracks(frames_path, manifest, rate_hz=rate)
        for window_s in windows_s:
            window = max(2, int(round(window_s * rate)))
            for horizon_s in horizons_s:
                horizon = None if horizon_s is None else int(round(horizon_s * rate))
                total = 0
                actors_hit = set()
                windows_seen = {}
                for uid, tr in tracks.items():
                    cells = quantise(tr, cell_cm=cell_cm)
                    reps, stat = _windows_all_pairs(cells, window, horizon)
                    if reps:
                        total += len(reps)
                        actors_hit.add(uid)
                    for i in range(0, max(0, len(cells) - window + 1)):
                        w = tuple(cells[i:i + window])
                        xs = [c[0] for c in w]
                        ys = [c[1] for c in w]
                        if len(set(w)) > 1 and (max(xs) - min(xs)) <= patrol_cells and (max(ys) - min(ys)) <= patrol_cells:
                            patrol_windows += 1
                            patrol_actors.add(uid)
                        windows_seen.setdefault(w, set()).add(uid)
                for w, uids in windows_seen.items():
                    if len(uids) > 1:
                        cross_actor.append({"window_len": len(w), "uids": sorted(uids)[:4],
                                            "rate_hz": rate, "window_s": window_s})
                grid.append({"rate_hz": rate, "window_s": window_s,
                             "horizon_s": horizon_s, "repeats": total,
                             "actors": sorted(actors_hit)[:6], "actor_count": len(actors_hit)})
    tracks = sampled_tracks(frames_path, manifest, rate_hz=rates_hz[0])
    for uid, tr in tracks.items():
        hs = [h for h in _headings(tr) if h is not None]
        for L in (6, 10):
            seen = {}
            hit = 0
            for i in range(0, max(0, len(hs) - L + 1)):
                seg = tuple(hs[i:i + L])
                if len(set(seg)) == 1:
                    continue
                if seg in seen:
                    hit += 1
                seen.setdefault(seg, i)
            if hit:
                route_repeats.setdefault(uid, {})[f"len{L}"] = hit
        st = _stops(tr, cell_cm)
        for i in range(0, max(0, len(st) - 3)):
            if st[i] == st[i + 2] and st[i + 1] == st[i + 3] and st[i] != st[i + 1]:
                dest_cycles[uid] = dest_cycles.get(uid, 0) + 1
    per = base.get("spawn_periodicity", {})
    by_kind = per.get("by_kind", {})
    periodic_fail = {k: v for k, v in by_kind.items() if (v.get("score") or 0.0) >= periodicity_threshold}
    doc = {
        "schema_version": LOOP_AUDIT_V2_VERSION,
        "record": base.get("record"),
        "params": {"windows_s": list(windows_s), "rates_hz": list(rates_hz),
                   "horizons_s": list(horizons_s), "cell_cm": cell_cm,
                   "dest_ratio_min": dest_ratio_min,
                   "periodicity_threshold": periodicity_threshold,
                   "patrol_cells": patrol_cells},
        "window_grid": grid,
        "window_repeats_total": sum(g["repeats"] for g in grid),
        "patrol": {"windows": patrol_windows, "actors": sorted(patrol_actors)[:8],
                   "actor_count": len(patrol_actors),
                   "note": "counted, never exempted: a 1-2 cell patrol is a loop a viewer can see"},
        "route_repeats": {"actors": len(route_repeats), "sample": dict(list(route_repeats.items())[:4])},
        "destination_cycles": {"actors": len(dest_cycles), "sample": dict(list(dest_cycles.items())[:4])},
        "cross_actor_windows": {"count": len(cross_actor), "sample": cross_actor[:4]},
        "destinations": base.get("destinations"),
        "spawn_periodicity": {"by_kind": by_kind, "threshold": periodicity_threshold,
                              "failing_kinds": sorted(periodic_fail)},
        "v1": {"window_repeats": base.get("window_repeats"), "pass": base.get("pass")},
        "boundary": [
            "A loop whose period exceeds the longest horizon (%s s) is only caught by the horizon=None pass." % max(h for h in horizons_s if h),
            "Motion that never crosses a %.0f cm cell boundary is invisible to the cell tests." % cell_cm,
            "Sub-second phase drift breaks exact window equality; near-repeats are not scored.",
            "Route repetition is quantised to 45 deg headings, so gentle curves may not match.",
            "Two actors alternating identical windows are reported under cross_actor_windows, not as per-actor repeats.",
            "Spawn periodicity uses a DFT peak ratio; the threshold %.2f is the Director's to set." % periodicity_threshold,
        ],
    }
    doc["pass"] = (doc["window_repeats_total"] == 0
                   and (base.get("destinations") or {}).get("pass", False)
                   and not periodic_fail
                   and doc["route_repeats"]["actors"] == 0)
    return doc


def write_audit_v2(record_dir, out_path, **params) -> dict:
    import json as _json
    from pathlib import Path as _Path
    rd = _Path(record_dir)
    manifest = _json.loads((rd / "record_manifest.json").read_text(encoding="utf-8"))
    doc = audit_record_v2(rd / "frames.bin", manifest, **params)
    _Path(out_path).write_text(_json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    return doc
'''

p = W / "world_inventory.py"
t = p.read_text(encoding="utf-8")
if "LEVEL_INVENTORY_VERSION" not in t:
    p.write_text(t.rstrip("\n") + "\n" + INV, encoding="utf-8")
    print("world_inventory.py: level_inventory added")

p = W / "loop_audit.py"
t = p.read_text(encoding="utf-8")
if "LOOP_AUDIT_V2_VERSION" not in t:
    p.write_text(t.rstrip("\n") + "\n" + LOOP, encoding="utf-8")
    print("loop_audit.py: audit_record_v2 added")
