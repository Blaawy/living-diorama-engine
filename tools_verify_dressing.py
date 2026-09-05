"""Prove the street dressing that was SPAWNED matches the dressing that was PLANNED.

Not circular: the snapshot is read from the spawned components' own world
transforms inside the editor (`ldyf.unreal.ldyf_dressing_editor.sample_dressing`)
and compared against the `dressing_v1` document that the SUMO network produced.
"""
# HAZARD: this script is DESTRUCTIVE. It clears the tree and pit actors and
# rebuilds them before sampling. Running it while a Movie Render Queue job is in
# flight makes actor spawning return None, so the clear succeeds, the rebuild
# fails, and the level is left with NO TREES -- while the render quietly
# continues and produces a treeless film. That happened once. Never run this
# concurrently with a render.
from __future__ import annotations
import json, sys
from pathlib import Path
YF = Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
sys.path.insert(0, str(YF / "WORKSPACE"))
from ldyf.unreal_remote import UnrealRemote                      # noqa: E402
from ldyf import dressing_check as DC                            # noqa: E402

EV = YF / "EVIDENCE" / "PHASE_02"
SNAP = EV / "dressing_snapshot.json"
SURFACE_Z = 20.0
TOL = {"xy_cm": 5.0, "yaw_deg": 1.0, "size_cm": 2.0, "match_max_cm": 50.0,
       "contact_z_cm": 2.0, "decal_z_cm": 1.0}
# the plane the editor was asked to project the paint onto
DECAL_Z = SURFACE_Z + 20.0

REBUILD = r'''
import unreal, json, sys, importlib
sys.path.insert(0, r"__WS__")
# Reload the DEPENDENCIES too, not just the editor module. The editor process
# holds ldyf.dressing_assets from whenever it first imported it, so a change to
# TREE_MESHES here reloads into nothing and the spawner keeps using the old
# table while this driver uses the new one -- which showed up as 240 trees
# compared, 78 matched, and nothing unmatched on either side.
import ldyf.dressing_assets, ldyf.dressing
importlib.reload(ldyf.dressing_assets)
importlib.reload(ldyf.dressing)
import ldyf.unreal.ldyf_dressing_editor as D
importlib.reload(D)
out = {}
# rebuild trees so the pits land on their own actor (grouping only - the
# instance transforms are unchanged, which the position check below proves)
out["cleared"] = D.clear_dressing((D.TREE_PREFIX, D.TREE_BASE_PREFIX))
out["trees"] = {k: v for k, v in D.build_trees(r"__DRESS__", surface_z_cm=__SURF__).items()
                if k != "contact_offsets"}
out["summary"] = D.dressing_summary()

out["sampled"] = D.sample_dressing(r"__SNAP__")
unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()
print("DRESSING " + json.dumps(out, default=str))
'''


def main() -> int:
    ws = str(YF / "WORKSPACE")
    code = (REBUILD.replace("__WS__", ws)
                   .replace("__DRESS__", str(EV / "dressing.json"))
                   .replace("__SNAP__", str(SNAP).replace("\\", "/"))
                   .replace("__SURF__", repr(SURFACE_Z)))
    with UnrealRemote(discover_timeout=180.0) as r:
        print(r.output_text(r.exec_file(code))[-1500:])

    planned = json.loads((EV / "dressing.json").read_text(encoding="utf-8"))
    snap = json.loads(SNAP.read_text(encoding="utf-8"))
    bounds = snap["mesh_bounds"]

    from ldyf import dressing_assets as ED  # shared tables, no unreal import

    mark = DC.match_markings(planned["lane_markings"], snap, xy_tol_cm=TOL["xy_cm"],
                             yaw_tol_deg=TOL["yaw_deg"], size_tol_cm=TOL["size_cm"],
                             match_max_cm=TOL["match_max_cm"],
                             expected_z_cm=DECAL_Z, z_tol_cm=TOL["decal_z_cm"])
    cross = DC.match_crosswalks(planned["crosswalk_stripes"], snap, xy_tol_cm=TOL["xy_cm"],
                                yaw_tol_deg=TOL["yaw_deg"], size_tol_cm=TOL["size_cm"],
                                match_max_cm=TOL["match_max_cm"],
                                expected_z_cm=DECAL_Z, z_tol_cm=TOL["decal_z_cm"])
    props = {
        "signals": DC.match_props(planned["signals"], snap, ED.SIGNAL_MESH,
                                  xy_tol_cm=TOL["xy_cm"], yaw_tol_deg=TOL["yaw_deg"],
                                  match_max_cm=TOL["match_max_cm"], prefix="LD_Signal"),
        "closure": DC.match_props(planned["closure_props"], snap, ED.CLOSURE_MESH,
                                  xy_tol_cm=TOL["xy_cm"], yaw_tol_deg=TOL["yaw_deg"],
                                  match_max_cm=TOL["match_max_cm"], prefix="LD_ClosureProp"),
        # Trees are now fully checked: the plan owns the variant, the scale
        # and the yaw, so the verifier compares mesh AND yaw instead of
        # skipping both. `kind` is synthesised here from the planned variant
        # purely to reuse match_props' kind -> mesh table.
        "trees": DC.match_props(
            [dict(r, kind="tree%d" % int(r["variant"])) for r in planned["trees"]],
            snap, {"tree%d" % i: m for i, m in enumerate(ED.TREE_MESHES)},
            xy_tol_cm=TOL["xy_cm"], yaw_tol_deg=TOL["yaw_deg"],
            match_max_cm=TOL["match_max_cm"], prefix="LD_Tree"),
    }
    # Furniture was never verified against a plan at all, which is how 336 lamp
    # posts, bins and benches came to stand in live traffic without any check
    # objecting. It is checked now.
    layout = json.loads((EV / "city_layout.json").read_text(encoding="utf-8"))
    furn, kind_mesh = [], {}
    for k, meshes in ED.FURNITURE_MESH.items():
        for i, m in enumerate(meshes):
            kind_mesh["%s#%d" % (k, i)] = m
    for r in layout["furniture_slots"]["slots"]:
        opts = ED.FURNITURE_MESH.get(r["kind"]) or []
        if not opts:
            continue
        furn.append(dict(r,
                         id="%s|%s|%s" % (r["lane_id"], r["distance_cm"], r["kind"]),
                         kind="%s#%d" % (r["kind"], int(r.get("variant", 0)) % len(opts))))
    props["furniture"] = DC.match_props(
        furn, snap, kind_mesh, xy_tol_cm=TOL["xy_cm"], yaw_tol_deg=TOL["yaw_deg"],
        match_max_cm=TOL["match_max_cm"], prefix="LD_Furniture")

    contact = DC.check_ground_contact(snap, surface_z_cm=SURFACE_Z, mesh_bounds=bounds,
                                      tol_cm=TOL["contact_z_cm"],
                                      buried={m: ED.TREE_BURY_CM for m in ED.TREE_MESHES})
    report = DC.build_report(mark, cross, props, contact, tolerances=TOL)
    DC.write_report(report, EV / "dressing_check.json")

    def brief(d):
        return {k: d.get(k) for k in ("compared", "matched", "unmatched_planned",
                                      "unmatched_snapshot", "insufficient_sample",
                                      "pass") if k in d}
    print("MARKINGS ", json.dumps(brief(mark), default=str))
    print("CROSSWALK", json.dumps(brief(cross), default=str))
    for k, v in props.items():
        print("PROPS %-8s" % k, json.dumps(brief(v), default=str))
    print("CONTACT  ", json.dumps(brief(contact), default=str))
    print("DRESSING CHECK PASS:", report.get("pass"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
