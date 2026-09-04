"""dressing_check.py tests: the pure checker is exact on synthetic data.

Every fixture is built inline -- no disk reads, no Unreal import.  Rows mimic
the actual ``dressing_v1`` document produced by ``ldyf.dressing`` (lane_markings
carry ``centre_x/centre_y/width_cm/length_cm/colour``, crosswalk_stripes carry
``size_across_cm/size_along_cm``, signals/trees/props carry ``x/y/kind``) and
the ``dressing_snapshot_v1`` schema of the settled design (decals with
``size_x/size_y/size_z/material``, instances with ``mesh/scale_*``).  Mesh and
material paths follow ``ldyf.unreal.ldyf_dressing_editor``.
"""

from __future__ import annotations

from ldyf.dressing_check import (
    DRESSING_CHECK_VERSION,
    build_report,
    check_ground_contact,
    match_crosswalks,
    match_markings,
    match_props,
)

# --- asset paths (editor constants, see ldyf/unreal/ldyf_dressing_editor.py)
WHITE_MAT = "/Game/LD/Materials/MI_LD_Paint_White"
YELLOW_MAT = "/Game/LD/Materials/MI_LD_Paint_Yellow"
WHITE_MAT_SUFFIXED = WHITE_MAT + "." + WHITE_MAT.rsplit("/", 1)[-1]

SIGNAL_MESH = "/Game/Prop/Kit_StreetLamp_A/Mesh/SM_StreetLamp_A_StopLight_B"
STOP_SIGN_MESH = "/Game/Prop/Kit_StopSign_A/Mesh/SM_StopSign_A"
TREE_MESH_A = "/Game/Prop/Kit_Tree_Maple_Sugar/Mesh/Tree_Maple_A"
TREE_MESH_B = "/Game/Prop/Kit_Tree_Maple_Sugar/Mesh/Tree_Maple_B"
CONE_MESH = "/Game/Prop/Kit_ConstructionCone_RR/Mesh/SM_ConstCone_a_N1"
BARRICADE_MESH = "/Game/Prop/Kit_Barricade_A/Mesh/SM_Barricade_A"

SURFACE_Z_CM = 20.0

# --- inline fixtures --------------------------------------------------------


def snap(decals=(), instances=()):
    return {
        "schema_version": "dressing_snapshot_v1",
        "decals": list(decals),
        "instances": list(instances),
    }


def decal(actor="LD_Mark_E1", x=0.0, y=0.0, z=SURFACE_Z_CM, yaw=0.0,
          size_x=60.0, size_y=6.0, size_z=150.0, material=WHITE_MAT_SUFFIXED):
    return {"actor": actor, "component": "Decal0", "x": x, "y": y, "z": z,
            "yaw": yaw, "size_x": size_x, "size_y": size_y, "size_z": size_z,
            "material": material}


def inst(actor="LD_Signal", mesh=SIGNAL_MESH, x=0.0, y=0.0, z=0.0, yaw=0.0,
         scale_x=1.0, scale_y=1.0, scale_z=1.0):
    return {"actor": actor, "component": "ISM0", "mesh": mesh,
            "x": x, "y": y, "z": z, "yaw": yaw,
            "scale_x": scale_x, "scale_y": scale_y, "scale_z": scale_z}


def mark_row(rid, cx=0.0, cy=0.0, width=12.0, length=300.0, yaw=0.0,
             colour="white"):
    return {"id": rid, "kind": "edge_line", "colour": colour, "edge_id": "E1",
            "centre_x": cx, "centre_y": cy, "length_cm": length,
            "width_cm": width, "yaw": yaw}


def cross_row(rid, x=0.0, y=0.0, yaw=90.0, along=45.0, across=400.0):
    return {"id": rid, "edge_id": "X1", "lane_id": "X1_0", "x": x, "y": y,
            "yaw": yaw, "size_along_cm": along, "size_across_cm": across}


def signal_row(rid, kind="traffic_light", x=0.0, y=0.0, yaw=180.0):
    return {"id": rid, "junction_id": "J0", "edge_id": "E1", "kind": kind,
            "x": x, "y": y, "yaw": yaw}


def tree_row(rid, x=0.0, y=0.0, yaw=0.0):
    return {"id": rid, "lane_id": "W1", "edge_id": "E1", "distance_cm": 0.0,
            "x": x, "y": y, "yaw": yaw}


def cone_row(rid, x=0.0, y=0.0, yaw=0.0):
    return {"id": rid, "edge_id": "E2", "kind": "cone", "x": x, "y": y,
            "yaw": yaw, "span_cm": 320.0}


def empty_report():
    empty = snap()
    return build_report(
        match_markings([], empty, xy_tol_cm=5.0, yaw_tol_deg=5.0,
                       size_tol_cm=5.0),
        match_crosswalks([], empty, xy_tol_cm=5.0, yaw_tol_deg=5.0,
                         size_tol_cm=5.0),
        {"signals": match_props([], empty, {}, xy_tol_cm=5.0, prefix="LD_Signal"),
         "trees": match_props([], empty, {}, xy_tol_cm=5.0, prefix="LD_Tree"),
         "props": match_props([], empty, {}, xy_tol_cm=5.0, prefix="LD_ClosureProp")},
        check_ground_contact(empty, surface_z_cm=SURFACE_Z_CM, mesh_bounds={},
                             tol_cm=5.0),
        tolerances={"xy_tol_cm": 5.0, "yaw_tol_deg": 5.0, "size_tol_cm": 5.0,
                    "tol_cm": 5.0, "match_max_cm": 50.0},
    )


# --- markings ---------------------------------------------------------------


def test_exact_marking_match_passes():
    res = match_markings([mark_row("m1")], snap([decal()]),
                         xy_tol_cm=5.0, yaw_tol_deg=5.0, size_tol_cm=5.0)
    assert res["pass"] is True
    assert res["compared"] == 1 and res["matched"] == 1


def test_marking_6cm_displacement_fails_at_5cm_tolerance():
    res = match_markings([mark_row("m1")], snap([decal(x=6.0)]),
                         xy_tol_cm=5.0, yaw_tol_deg=5.0, size_tol_cm=5.0)
    assert res["pass"] is False
    assert res["mismatches"][0]["reasons"] == ["position"]


def test_marking_flipped_180_passes():
    # paint is symmetric: a 180-degree flip is the same painted line
    res = match_markings([mark_row("m1", yaw=0.0)], snap([decal(yaw=180.0)]),
                         xy_tol_cm=5.0, yaw_tol_deg=5.0, size_tol_cm=5.0)
    assert res["pass"] is True


def test_marking_rotated_90_fails():
    res = match_markings([mark_row("m1", yaw=0.0)], snap([decal(yaw=90.0)]),
                         xy_tol_cm=5.0, yaw_tol_deg=5.0, size_tol_cm=5.0)
    assert res["pass"] is False
    assert "yaw" in res["mismatches"][0]["reasons"]


def test_marking_wrong_material_colour_fails():
    # plan says yellow, snapshot decal wears the white paint material
    res = match_markings([mark_row("m1", colour="yellow")], snap([decal()]),
                         xy_tol_cm=5.0, yaw_tol_deg=5.0, size_tol_cm=5.0)
    assert res["pass"] is False
    assert "material" in res["mismatches"][0]["reasons"]


def test_marking_correct_colour_material_passes():
    res = match_markings([mark_row("m1", colour="white")], snap([decal()]),
                         xy_tol_cm=5.0, yaw_tol_deg=5.0, size_tol_cm=5.0)
    assert res["pass"] is True


def test_marking_size_mismatch_fails():
    # planned 12 cm wide / 300 cm long; decal is 20 cm wide (size_y 10)
    res = match_markings([mark_row("m1")], snap([decal(size_y=10.0)]),
                         xy_tol_cm=5.0, yaw_tol_deg=5.0, size_tol_cm=5.0)
    assert res["pass"] is False
    assert "size_y" in res["mismatches"][0]["reasons"]


def test_marking_missing_planned_row_fails():
    res = match_markings([mark_row("m1"), mark_row("m2", cx=9000.0)],
                         snap([decal()]),
                         xy_tol_cm=5.0, yaw_tol_deg=5.0, size_tol_cm=5.0)
    assert res["pass"] is False
    assert res["unmatched_planned_count"] == 1
    assert res["unmatched_planned"][0]["id"] == "m2"


def test_marking_extra_snapshot_row_fails():
    res = match_markings([mark_row("m1")], snap([decal(), decal(x=5000.0)]),
                         xy_tol_cm=5.0, yaw_tol_deg=5.0, size_tol_cm=5.0)
    assert res["pass"] is False
    assert res["unmatched_snapshot_count"] == 1


def test_marking_beyond_match_max_is_unmatched_planned():
    # 60 cm away with match_max_cm=50: not a mismatch, an unmatched plan row
    res = match_markings([mark_row("m1")], snap([decal(x=60.0)]),
                         xy_tol_cm=5.0, yaw_tol_deg=5.0, size_tol_cm=5.0,
                         match_max_cm=50.0)
    assert res["pass"] is False
    assert res["mismatches"] == []
    assert res["unmatched_planned_count"] == 1


# --- crosswalks -------------------------------------------------------------


def test_crosswalk_exact_match_passes():
    res = match_crosswalks([cross_row("x1")], snap([decal(
        actor="LD_Crosswalk_X1", yaw=90.0, size_y=200.0, size_z=22.5)]),
        xy_tol_cm=5.0, yaw_tol_deg=5.0, size_tol_cm=5.0)
    assert res["pass"] is True


def test_crosswalk_flipped_180_passes():
    # stripes are paint: flipped 180 the zebra reads the same
    res = match_crosswalks([cross_row("x1", yaw=90.0)], snap([decal(
        actor="LD_Crosswalk_X1", yaw=270.0, size_y=200.0, size_z=22.5)]),
        xy_tol_cm=5.0, yaw_tol_deg=5.0, size_tol_cm=5.0)
    assert res["pass"] is True


def test_crosswalk_size_mismatch_fails():
    # planned size_along_cm 45 (half 22.5); decal half length 30
    res = match_crosswalks([cross_row("x1")], snap([decal(
        actor="LD_Crosswalk_X1", yaw=90.0, size_y=200.0, size_z=30.0)]),
        xy_tol_cm=5.0, yaw_tol_deg=5.0, size_tol_cm=5.0)
    assert res["pass"] is False
    assert "size_z" in res["mismatches"][0]["reasons"]


# --- props: signals ---------------------------------------------------------


def test_signal_exact_match_passes():
    res = match_props([signal_row("s1")], snap(instances=[inst(
        yaw=180.0)]), {"traffic_light": SIGNAL_MESH, "stop_sign": STOP_SIGN_MESH},
        xy_tol_cm=5.0, yaw_tol_deg=5.0, prefix="LD_Signal")
    assert res["pass"] is True


def test_signal_flipped_180_fails():
    # a signal faces back down the approach; a flip faces away and must fail
    res = match_props([signal_row("s1", yaw=180.0)], snap(instances=[inst(
        yaw=0.0)]), {"traffic_light": SIGNAL_MESH, "stop_sign": STOP_SIGN_MESH},
        xy_tol_cm=5.0, yaw_tol_deg=5.0, prefix="LD_Signal")
    assert res["pass"] is False
    assert "yaw" in res["mismatches"][0]["reasons"]


def test_signal_wearing_tree_mesh_fails():
    res = match_props([signal_row("s1")], snap(instances=[inst(mesh=TREE_MESH_A,
        yaw=180.0)]), {"traffic_light": SIGNAL_MESH, "stop_sign": STOP_SIGN_MESH},
        xy_tol_cm=5.0, yaw_tol_deg=5.0, prefix="LD_Signal")
    assert res["pass"] is False
    assert "mesh" in res["mismatches"][0]["reasons"]


def test_signal_unknown_kind_fails():
    res = match_props([signal_row("s1", kind="bus_shelter")], snap(instances=[
        inst(yaw=180.0)]), {"traffic_light": SIGNAL_MESH, "stop_sign": STOP_SIGN_MESH},
        xy_tol_cm=5.0, yaw_tol_deg=5.0, prefix="LD_Signal")
    assert res["pass"] is False
    assert "mesh" in res["mismatches"][0]["reasons"]


def test_prop_cone_exact_match_passes():
    res = match_props([cone_row("c1")], snap(instances=[inst(
        actor="LD_ClosureProp", mesh=CONE_MESH)]),
        {"barricade": BARRICADE_MESH, "cone": CONE_MESH},
        xy_tol_cm=5.0, yaw_tol_deg=5.0, prefix="LD_ClosureProp")
    assert res["pass"] is True


def test_asset_path_objectname_suffix_normalised():
    # /Game/X/SM_Y.SM_Y equals /Game/X/SM_Y
    res = match_props([signal_row("s1")], snap(instances=[inst(
        mesh=SIGNAL_MESH + "." + SIGNAL_MESH.rsplit("/", 1)[-1], yaw=180.0)]),
        {"traffic_light": SIGNAL_MESH, "stop_sign": STOP_SIGN_MESH},
        xy_tol_cm=5.0, yaw_tol_deg=5.0, prefix="LD_Signal")
    assert res["pass"] is True


# --- props: trees -----------------------------------------------------------


def test_tree_position_exact_passes():
    res = match_props([tree_row("t1")], snap(instances=[inst(
        actor="LD_Tree", mesh=TREE_MESH_A)]), {},
        xy_tol_cm=5.0, prefix="LD_Tree")
    assert res["pass"] is True


def test_tree_yaw_is_ignored():
    # the editor assigns a digest-derived rotation the plan never specifies
    res = match_props([tree_row("t1", yaw=0.0)], snap(instances=[inst(
        actor="LD_Tree", mesh=TREE_MESH_A, yaw=123.0)]), {},
        xy_tol_cm=5.0, prefix="LD_Tree")
    assert res["pass"] is True


def test_tree_mesh_variant_is_not_compared():
    # kind-less tree rows are mesh-agnostic: any street-tree mesh may be worn
    res = match_props([tree_row("t1")], snap(instances=[inst(
        actor="LD_Tree", mesh=TREE_MESH_B)]), {},
        xy_tol_cm=5.0, prefix="LD_Tree")
    assert res["pass"] is True


# --- ground contact ---------------------------------------------------------

TREE_BOUNDS = {TREE_MESH_A: {"min_z": -100.0}}
SIGNAL_BOUNDS = {SIGNAL_MESH: {"min_z": -200.0}}
CONE_BOUNDS = {CONE_MESH: {"min_z": 0.0}}
ALL_BOUNDS = dict(TREE_BOUNDS, **SIGNAL_BOUNDS, **CONE_BOUNDS)
TREE_BURIED = {TREE_MESH_A: 10.0}


def test_ground_contact_exact_pass():
    # z + min_z*scale_z == surface: z = surface - min_z = 20 + 200
    res = check_ground_contact(snap(instances=[inst(z=220.0)]),
                               surface_z_cm=SURFACE_Z_CM,
                               mesh_bounds=SIGNAL_BOUNDS, tol_cm=5.0)
    assert res["pass"] is True
    assert res["checked"][0]["diff_cm"] == 0.0


def test_prop_floating_40cm_fails():
    # cone min_z 0 so z must equal surface; z = 60 floats 40 cm up
    res = check_ground_contact(snap(instances=[inst(mesh=CONE_MESH, z=60.0)]),
                               surface_z_cm=SURFACE_Z_CM,
                               mesh_bounds=CONE_BOUNDS, tol_cm=5.0)
    assert res["pass"] is False
    assert res["checked"][0]["diff_cm"] == 40.0


def test_tree_buried_10cm_passes():
    # z = surface - bury - min_z = 20 - 10 + 100 = 110
    res = check_ground_contact(snap(instances=[inst(actor="LD_Tree",
                                                    mesh=TREE_MESH_A, z=110.0)]),
                               surface_z_cm=SURFACE_Z_CM,
                               mesh_bounds=TREE_BOUNDS, tol_cm=5.0,
                               buried=TREE_BURIED)
    assert res["pass"] is True


def test_tree_buried_20cm_fails():
    # tree sits 10 cm under grade but 20 cm was allowed: expectation shifted
    # down to surface-20, i.e. contact z 0; actual base is at 10
    res = check_ground_contact(snap(instances=[inst(actor="LD_Tree",
                                                    mesh=TREE_MESH_A, z=110.0)]),
                               surface_z_cm=SURFACE_Z_CM,
                               mesh_bounds=TREE_BOUNDS, tol_cm=5.0,
                               buried={TREE_MESH_A: 20.0})
    assert res["pass"] is False
    assert res["checked"][0]["diff_cm"] == 10.0


def test_tree_not_buried_when_bury_not_allowed_fails():
    # buried map empty: the same z puts the base 10 cm below surface -> fail
    res = check_ground_contact(snap(instances=[inst(actor="LD_Tree",
                                                    mesh=TREE_MESH_A, z=110.0)]),
                               surface_z_cm=SURFACE_Z_CM,
                               mesh_bounds=TREE_BOUNDS, tol_cm=5.0)
    assert res["pass"] is False


def test_ground_contact_missing_bounds_fails():
    res = check_ground_contact(snap(instances=[inst(mesh=TREE_MESH_A, z=110.0)]),
                               surface_z_cm=SURFACE_Z_CM, mesh_bounds={},
                               tol_cm=5.0)
    assert res["pass"] is False
    assert res["failures"][0]["reason"] == "no_bounds"


def test_ground_contact_missing_scale_z_defaults_to_one():
    row = inst(actor="LD_Tree", mesh=TREE_MESH_A, z=110.0)
    del row["scale_z"]
    res = check_ground_contact(snap(instances=[row]),
                               surface_z_cm=SURFACE_Z_CM,
                               mesh_bounds=TREE_BOUNDS, tol_cm=5.0,
                               buried=TREE_BURIED)
    assert res["pass"] is True


# --- empty is never a pass --------------------------------------------------


def test_empty_markings_insufficient_and_no_pass():
    res = match_markings([], snap(), xy_tol_cm=5.0, yaw_tol_deg=5.0,
                         size_tol_cm=5.0)
    assert res["insufficient_sample"] is True
    assert res["pass"] is False


def test_empty_crosswalks_insufficient_and_no_pass():
    res = match_crosswalks([], snap(), xy_tol_cm=5.0, yaw_tol_deg=5.0,
                           size_tol_cm=5.0)
    assert res["insufficient_sample"] is True
    assert res["pass"] is False


def test_empty_props_insufficient_and_no_pass():
    res = match_props([], snap(), {}, xy_tol_cm=5.0, prefix="LD_Signal")
    assert res["insufficient_sample"] is True
    assert res["pass"] is False


def test_empty_ground_contact_insufficient_and_no_pass():
    res = check_ground_contact(snap(), surface_z_cm=SURFACE_Z_CM,
                               mesh_bounds={}, tol_cm=5.0)
    assert res["insufficient_sample"] is True
    assert res["pass"] is False


def test_empty_overall_report_does_not_pass():
    report = empty_report()
    assert report["pass"] is False
    assert report["insufficient_sample"] is True
    assert report["schema_version"] == DRESSING_CHECK_VERSION


def test_report_pass_requires_every_category_compared():
    good = snap(decals=[decal()], instances=[inst(yaw=180.0, z=220.0)])
    marking_res = match_markings([mark_row("m1")], good, xy_tol_cm=5.0,
                                 yaw_tol_deg=5.0, size_tol_cm=5.0)
    cross_res = match_crosswalks([cross_row("x1")], good, xy_tol_cm=5.0,
                                 yaw_tol_deg=5.0, size_tol_cm=5.0)
    # trees category is empty: it must veto the overall pass
    report = build_report(
        marking_res, cross_res,
        {"signals": match_props([signal_row("s1")], good,
                                {"traffic_light": SIGNAL_MESH,
                                 "stop_sign": STOP_SIGN_MESH},
                                xy_tol_cm=5.0, yaw_tol_deg=5.0,
                                prefix="LD_Signal"),
         "trees": match_props([], good, {}, xy_tol_cm=5.0, prefix="LD_Tree")},
        check_ground_contact(good, surface_z_cm=SURFACE_Z_CM,
                             mesh_bounds=SIGNAL_BOUNDS, tol_cm=5.0),
        tolerances={"xy_tol_cm": 5.0})
    assert report["pass"] is False
    assert report["insufficient_sample"] is True


def test_full_report_exact_match_passes():
    decals = [decal(actor="LD_Mark_E1"),
              decal(actor="LD_Crosswalk_X1", yaw=90.0, size_y=200.0,
                    size_z=22.5)]
    instances = [
        inst(actor="LD_Signal", mesh=SIGNAL_MESH, yaw=180.0, z=220.0),
        inst(actor="LD_Tree", mesh=TREE_MESH_A, z=110.0),
        inst(actor="LD_ClosureProp", mesh=CONE_MESH, z=20.0),
    ]
    good = snap(decals=decals, instances=instances)
    report = build_report(
        match_markings([mark_row("m1")], good, xy_tol_cm=5.0, yaw_tol_deg=5.0,
                       size_tol_cm=5.0),
        match_crosswalks([cross_row("x1")], good, xy_tol_cm=5.0,
                         yaw_tol_deg=5.0, size_tol_cm=5.0),
        {"signals": match_props([signal_row("s1")], good,
                                {"traffic_light": SIGNAL_MESH,
                                 "stop_sign": STOP_SIGN_MESH},
                                xy_tol_cm=5.0, yaw_tol_deg=5.0,
                                prefix="LD_Signal"),
         "trees": match_props([tree_row("t1")], good, {}, xy_tol_cm=5.0,
                              prefix="LD_Tree"),
         "props": match_props([cone_row("c1")], good,
                              {"barricade": BARRICADE_MESH, "cone": CONE_MESH},
                              xy_tol_cm=5.0, yaw_tol_deg=5.0,
                              prefix="LD_ClosureProp")},
        check_ground_contact(good, surface_z_cm=SURFACE_Z_CM,
                             mesh_bounds=ALL_BOUNDS, tol_cm=5.0,
                             buried=TREE_BURIED),
        tolerances={"xy_tol_cm": 5.0, "yaw_tol_deg": 5.0, "size_tol_cm": 5.0,
                    "tol_cm": 5.0, "match_max_cm": 50.0},
    )
    assert report["pass"] is True
    assert report["insufficient_sample"] is False
    assert report["checks"]["markings"]["pass"] is True
    assert report["checks"]["crosswalks"]["pass"] is True
    assert report["checks"]["signals"]["pass"] is True
    assert report["checks"]["trees"]["pass"] is True
    assert report["checks"]["props"]["pass"] is True
    assert report["checks"]["ground_contact"]["pass"] is True
    assert report["tolerances"]["match_max_cm"] == 50.0


def test_report_ands_all_checks():
    # one failing sub-check must veto the overall pass
    good = snap(decals=[decal()], instances=[inst(yaw=180.0, z=220.0)])
    bad = match_markings([mark_row("m1", cx=100.0)], good, xy_tol_cm=5.0,
                         yaw_tol_deg=5.0, size_tol_cm=5.0)
    assert bad["pass"] is False
    report = build_report(
        bad,
        match_crosswalks([cross_row("x1")], good, xy_tol_cm=5.0,
                         yaw_tol_deg=5.0, size_tol_cm=5.0),
        {"signals": match_props([signal_row("s1")], good,
                                {"traffic_light": SIGNAL_MESH,
                                 "stop_sign": STOP_SIGN_MESH},
                                xy_tol_cm=5.0, yaw_tol_deg=5.0,
                                prefix="LD_Signal"),
         "trees": match_props([tree_row("t1")], good, {}, xy_tol_cm=5.0,
                              prefix="LD_Tree")},
        check_ground_contact(good, surface_z_cm=SURFACE_Z_CM,
                             mesh_bounds=SIGNAL_BOUNDS, tol_cm=5.0),
        tolerances={"xy_tol_cm": 5.0})
    assert report["pass"] is False


def test_determinism_same_inputs_identical_report():
    report = empty_report()
    assert report == empty_report()


def test_determinism_planned_row_order_does_not_matter():
    planned = [mark_row("m1", cx=0.0), mark_row("m2", cx=1000.0),
               mark_row("m3", cx=2000.0)]
    rows = [decal(x=0.0), decal(x=1000.0), decal(x=2000.0)]
    r1 = match_markings(planned, snap(rows), xy_tol_cm=5.0, yaw_tol_deg=5.0,
                        size_tol_cm=5.0)
    r2 = match_markings(list(reversed(planned)), snap(list(reversed(rows))),
                        xy_tol_cm=5.0, yaw_tol_deg=5.0, size_tol_cm=5.0)
    assert r1 == r2
    assert r1["pass"] is True


def test_unmatched_counts_appear_in_report():
    report = empty_report()
    # both unmatched counts are present on every pairing category result
    for name, res in report["checks"].items():
        if name == "ground_contact":
            continue  # ground contact is not a pairing check
        assert "unmatched_planned_count" in res
        assert "unmatched_snapshot_count" in res
