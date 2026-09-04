"""Aim the five preview cameras from the RECORD instead of from typed coordinates.

Two of the five Phase 2 shots framed mostly empty asphalt because their
positions were guessed. `ldyf.shot_planner` bins actual actor positions from the
sealed record and puts each camera where the traffic really is; the two shots
that must show a specific place (the closed edge) stay `fixed`, because for
those the interesting location comes from the rule manifest, not from density.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
YF = Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
sys.path.insert(0, str(YF / "WORKSPACE"))
from ldyf.shot_planner import plan_shots, choose_bearing   # noqa: E402
from ldyf.dressing import closure_props             # noqa: E402

EV = YF / "EVIDENCE" / "PHASE_02"
REC = YF / "PHASE_01/proof/sumo/closure_v2/record_ruled"
SPEC = YF / "PHASE_02/proof/road_spec.json"
RULE = YF / "PHASE_01/proof/sumo/closure_v2/rule_manifest.json"

SIM_START, SIM_END, FPS = 110.0, 200.0, 24


def main() -> int:
    manifest = json.loads((REC / "record_manifest.json").read_text(encoding="utf-8"))
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    rule = json.loads(RULE.read_text(encoding="utf-8"))
    closed = list(rule["change"]["close_edges"]["edge_ids"])

    # the closure's own location, taken from the barricade the rule produced
    props = closure_props(spec, closed)
    bar = sorted((p for p in props if p["kind"] == "barricade"),
                 key=lambda r: r["id"])
    # ONE barricade, not the mean of both: the two barricades sit at opposite
    # ends of the closed link about 170 m apart, so their midpoint is a stretch
    # of empty road with the actual obstruction 85 m away in each direction --
    # exactly the "shot of nothing" this planner exists to prevent.
    cx, cy = bar[0]["x"], bar[0]["y"]

    # city extent from the network itself, for the overview FOV fit
    xs, ys = [], []
    for e in spec["edges"]:
        for ln in e["lanes"]:
            for p in ln["polyline"]:
                xs.append(float(p["x"])); ys.append(float(p["y"]))
    bbox = (max(xs) - min(xs), max(ys) - min(ys))

    reqs = [
        # a living city, wide
        {"name": "overview", "kind": "overview", "start_s": 110.0, "end_s": 128.0,
         "distance_cm": 0.0, "height_cm": 14000.0, "bearing_deg": 135.0},
        # wherever the traffic actually is in this window
        {"name": "intersection", "kind": "hotspot", "start_s": 128.0, "end_s": 144.0,
         "distance_cm": 5200.0, "height_cm": 2200.0, "bearing_deg": 40.0},
        # street level at the closure, spanning the moment the rule applies (150 s)
        {"name": "street", "kind": "fixed", "start_s": 144.0, "end_s": 158.0,
         "x": cx, "y": cy, "distance_cm": 2600.0, "height_cm": 380.0,
         "bearing_deg": 200.0},
        # the blocked carriageway and the traffic reacting to it
        {"name": "closure", "kind": "fixed", "start_s": 158.0, "end_s": 178.0,
         "x": cx, "y": cy, "distance_cm": 4200.0, "height_cm": 2000.0,
         "bearing_deg": 155.0},
        # post-change: where the traffic went instead
        {"name": "after", "kind": "hotspot", "start_s": 178.0, "end_s": 200.0,
         "distance_cm": 9000.0, "height_cm": 5200.0, "bearing_deg": 60.0},
    ]

    # Buildings ring every block, so a camera standing inside a block polygon
    # (or looking through one) sees a wall. One preview shot really did render
    # half a frame of black building because its bearing was typed rather than
    # checked. Every bearing is now validated against the block polygons and
    # rotated to the nearest one that can actually see its target.
    layout = json.loads((EV / "city_layout.json").read_text(encoding="utf-8"))
    obstacles = [b["polygon"] for b in layout["blocks"]]
    bearing_log = []
    for r in reqs:
        if r["kind"] == "overview":
            continue                      # framed from above the whole city
        tx, ty = (r.get("x"), r.get("y"))
        if tx is None:
            continue                      # hotspot target is resolved inside plan_shots
        b, tried, blocked = choose_bearing(tx, ty, distance_cm=r["distance_cm"],
                                           preferred_deg=r["bearing_deg"],
                                           obstacles=obstacles)
        bearing_log.append({"shot": r["name"], "preferred": r["bearing_deg"],
                            "chosen": b, "was_blocked": blocked,
                            "bearings_tried": len(tried)})
        r["bearing_deg"] = b

    plan = plan_shots(REC / "frames.bin", manifest, fps=FPS, shots=reqs,
                      cell_cm=2000.0, fov_deg=70.0, fit_bbox_cm=bbox,
                      view_radius_cm=9000.0)
    # hotspot targets are only known after the first pass, so re-check those
    # bearings against the same obstacles and re-plan if any had to move
    moved = False
    for r, s_ in zip(reqs, plan["shots"]):
        if r["kind"] != "hotspot":
            continue
        b, tried, blocked = choose_bearing(s_["target"]["x"], s_["target"]["y"],
                                           distance_cm=r["distance_cm"],
                                           preferred_deg=r["bearing_deg"],
                                           obstacles=obstacles)
        bearing_log.append({"shot": r["name"], "preferred": r["bearing_deg"],
                            "chosen": b, "was_blocked": blocked,
                            "bearings_tried": len(tried), "pass": 2})
        if b != r["bearing_deg"]:
            r["bearing_deg"] = b
            moved = True
    if moved:
        plan = plan_shots(REC / "frames.bin", manifest, fps=FPS, shots=reqs,
                          cell_cm=2000.0, fov_deg=70.0, fit_bbox_cm=bbox,
                          view_radius_cm=9000.0)
    plan["bearing_selection"] = bearing_log
    plan["occlusion_test"] = {
        "obstacles": "city_layout_v1 block polygons (%d)" % len(obstacles),
        "method": "camera point-in-polygon plus a 24-sample sight line to the target",
        "limitation": "sampled, so a sliver thinner than the sample spacing can be missed",
    }
    plan["closure_target"] = {"x": cx, "y": cy, "edges": closed}
    plan["sim_window"] = [SIM_START, SIM_END]
    (EV / "shot_plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True),
                                       encoding="utf-8")

    # convert to the add_cameras shape; presentation time = sim - SIM_START
    shots = []
    for s in plan["shots"]:
        cam = s["camera"]
        shots.append({
            "name": s["name"],
            "start_s": round(s["start_s"] - SIM_START, 4),
            "end_s": round(s["end_s"] - SIM_START, 4),
            "loc": [cam["location"]["x"], cam["location"]["y"], cam["location"]["z"]],
            "rot": [cam["rotation"]["pitch"], cam["rotation"]["yaw"], cam["rotation"]["roll"]],
            # the FOV the planner sized this shot for; the editor derives the
            # focal length from it rather than leaving the CineCamera default,
            # which is 37.5 degrees and would render every shot twice as tight
            "fov_deg": plan["params"]["fov_deg"],
        })
    (EV / "shot_camera_args.json").write_text(json.dumps(shots, indent=2), encoding="utf-8")
    for s, p in zip(shots, plan["shots"]):
        print("%-12s pres %6.1f-%6.1f  target(%9.0f,%9.0f)  actors_in_view=%s" %
              (s["name"], s["start_s"], s["end_s"],
               p["target"]["x"], p["target"]["y"], p.get("actors_in_view_estimate")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
