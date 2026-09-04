"""Proof that actor-dump classification is exact and testable (world_inventory_v1).

Every scenario in the lane plan has its own hand-written dump: blockout cube,
spline road, sidewalk ISM, building with a kit, vehicles with 4 / 3 wheels,
pedestrians with / without animation, light, camera, volume, unknown actor,
empty dump, determinism, role_reason coverage and pass/fail composition. Each
test fails if its feature is removed.

Phase-2 L7 additions: dumps shaped exactly like ``ldyf_playback.dump_actors``
writes them -- v2 vehicles are ``Actor`` + ``PoseableMeshComponent`` under
``/Game/Vehicle/`` carrying ``wheel_bones`` / ``steer_bones``, and persons are
a mannequin ``SkeletalMeshComponent`` on TutorialTPP carrying the current
sequence path under the extra ``"animation"`` key.
"""

from __future__ import annotations

import json

import pytest

from ldyf.world_inventory import (
    INVENTORY_VERSION,
    classify_actor,
    classify_level_actor,
    inventory,
    kit_of,
    write_inventory,
)


# --- dump builders --------------------------------------------------------


def _comp(name, cclass, asset=None, *, skeleton=None, anim_class=None):
    return {
        "name": name,
        "class": cclass,
        "asset": asset,
        "instance_count": None,
        "anim_class": anim_class,
        "skeleton": skeleton,
    }


def _actor(name, cls, comps):
    return {
        "name": name,
        "class": cls,
        "label": name,
        "tags": [],
        "location": {"x": 0.0, "y": 0.0, "z": 0.0},
        "rotation": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0},
        "components": comps,
    }


def _dump(actors, level="/Game/Riverside"):
    return {
        "schema_version": "actor_dump_v1",
        "level": level,
        "captured_utc": "2026-09-03T00:00:00Z",
        "actors": actors,
    }


def _pedestrian(name="Ped_01", *, animated=True):
    return _actor(
        name,
        "SkeletalMeshActor",
        [
            _comp(
                "Mesh",
                "SkeletalMeshComponent",
                "/Game/Mannequin/Character/Mesh/SK_Mannequin.SK_Mannequin",
                skeleton="/Game/Mannequin/Character/Mesh/SK_Mannequin.SK_Mannequin",
                anim_class=(
                    "/Game/Mannequin/Animations/ABP_Mannequin.ABP_Mannequin_C"
                    if animated
                    else None
                ),
            )
        ],
    )


def _vehicle(name="Veh_01", *, wheels=4):
    comps = [
        _comp(
            "Mesh",
            "SkeletalMeshComponent",
            "/Game/Vehicle/Car/Meshes/SK_Car.SK_Car",
            skeleton="/Game/Vehicle/Car/Meshes/SK_Car.SK_Car",
            anim_class="/Game/Vehicle/Car/ABP_Car.ABP_Car_C",
        )
    ]
    for i in range(wheels):
        comps.append(
            _comp(
                f"Wheel_{i}",
                "StaticMeshComponent",
                "/Game/Vehicle/Wheels/SM_Wheel.SM_Wheel",
            )
        )
    return _actor(name, "SkeletalMeshActor", comps)


def _full_world_dump():
    actors = [
        _actor(
            "Building_A",
            "StaticMeshActor",
            [_comp("Mesh", "StaticMeshComponent", "/Game/Building/CH/SM_Bldg_A.SM_Bldg_A")],
        ),
        _actor(
            "Building_B",
            "StaticMeshActor",
            [_comp("Mesh", "StaticMeshComponent", "/Game/Building/DT/SM_Bldg_B.SM_Bldg_B")],
        ),
        _actor(
            "Building_C",
            "StaticMeshActor",
            [_comp("Mesh", "StaticMeshComponent", "/Game/Building/MG/SM_Facade_C.SM_Facade_C")],
        ),
        _actor(
            "Main_Road",
            "SplineMeshActor",
            [_comp("Spline", "SplineMeshComponent", "/Game/Roads/SM_Road_Straight.SM_Road_Straight")],
        ),
        _vehicle("Car_01", wheels=4),
        _pedestrian("Ped_01"),
    ]
    return _dump(actors)


# --- dump_actors-shaped builders (ldyf_playback.dump_actors, lane L7) -----


def _dump_vehicle(name="LD_vehicle_12", *, wheel_bones=None, steer_bones=None,
                  anim_class=None, animation=None):
    """A v2 spawned vehicle: Actor + PoseableMeshComponent on /Game/Vehicle/."""
    comp = {
        "name": "PoseableMesh0",
        "class": "PoseableMeshComponent",
        "asset": "/Game/Vehicle/vehCar_vehicle02/Mesh/SKM_vehCar_vehicle02",
        "instance_count": None,
        "anim_class": anim_class,
        "skeleton": None,
    }
    comp["wheel_bones"] = (
        ["wheel_front_l", "wheel_front_r", "wheel_rear_l", "wheel_rear_r"]
        if wheel_bones is None else list(wheel_bones)
    )
    comp["steer_bones"] = (
        ["wheel_front_turn_l", "wheel_front_turn_r"]
        if steer_bones is None else list(steer_bones)
    )
    if animation is not None:
        comp["animation"] = animation
    return _actor(name, "Actor", [comp])


def _dump_person(name="LD_person_1", *, with_animation=True,
                 animation="/Engine/Tutorial/SubEditors/TutorialAssets/Character/Tutorial_Walk_Fwd"):
    """A L7 person: mannequin SkeletalMeshComponent + current sequence path."""
    comp = {
        "name": "SkeletalMeshComponent0",
        "class": "SkeletalMeshComponent",
        "asset": "/Engine/Tutorial/SubEditors/TutorialAssets/Character/TutorialTPP",
        "instance_count": None,
        "anim_class": None,
        "skeleton": None,
    }
    if with_animation:
        comp["animation"] = animation
    return _actor(name, "SkeletalMeshActor", [comp])


# --- kit_of ---------------------------------------------------------------


def test_kit_of_returns_innermost_folder():
    assert kit_of("/Game/Building/CH/SM_x.SM_x") == "CH"


def test_kit_of_returns_none_when_no_subfolder():
    assert kit_of("/Game/SM_x.SM_x") is None
    assert kit_of("") is None


# --- classify_actor -------------------------------------------------------


def test_basicshapes_cube_is_blockout():
    a = _actor("Cube", "StaticMeshActor", [_comp("Mesh", "StaticMeshComponent", "/Engine/BasicShapes/Cube.Cube")])
    c = classify_actor(a)
    assert c["blockout"] is True
    assert c["role_reason"]


def test_spline_road_is_road():
    a = _actor("Road", "SplineMeshActor", [_comp("Spline", "SplineMeshComponent", "/Game/Roads/SM_Road.SM_Road")])
    c = classify_actor(a)
    assert c["role"] == "road"
    assert "road" in c["role_reason"].lower()


def test_sidewalk_ism_is_sidewalk():
    a = _actor("Sidewalk", "InstancedStaticMeshActor", [_comp("ISM", "InstancedStaticMeshComponent", "/Game/Sidewalk/SM_Sidewalk.SM_Sidewalk")])
    c = classify_actor(a)
    assert c["role"] == "sidewalk"
    assert c["assets"] == ["/Game/Sidewalk/SM_Sidewalk.SM_Sidewalk"]


def test_building_with_kit_ch():
    a = _actor("Office", "StaticMeshActor", [_comp("Mesh", "StaticMeshComponent", "/Game/Building/CH/SM_Bldg_A.SM_Bldg_A")])
    c = classify_actor(a)
    assert c["role"] == "building"
    assert c["kit"] == "CH"


def test_vehicle_with_4_wheels_and_abp():
    a = _vehicle("Car_01", wheels=4)
    c = classify_actor(a)
    assert c["role"] == "vehicle"
    assert c["skeletal"] is True
    assert c["animated"] is True
    assert c["wheels"] == 4
    assert not c["blockout"]


def test_vehicle_with_3_wheels_counts_3():
    a = _vehicle("Car_02", wheels=3)
    c = classify_actor(a)
    assert c["role"] == "vehicle"
    assert c["wheels"] == 3


def test_pedestrian_with_anim():
    c = classify_actor(_pedestrian(animated=True))
    assert c["role"] == "pedestrian"
    assert c["skeletal"] is True
    assert c["animated"] is True


def test_pedestrian_without_anim_not_animated():
    c = classify_actor(_pedestrian(animated=False))
    assert c["role"] == "pedestrian"
    assert c["skeletal"] is True
    assert c["animated"] is False


def test_light_classified():
    c = classify_actor(_actor("StreetLight", "PointLight", []))
    assert c["role"] == "light"


def test_camera_classified():
    c = classify_actor(_actor("MainCam", "CineCameraActor", []))
    assert c["role"] == "camera"


def test_volume_classified():
    c = classify_actor(_actor("SpawnVol", "TriggerVolume", []))
    assert c["role"] == "volume"


def test_plain_static_mesh_is_prop():
    c = classify_actor(_actor("Tree", "StaticMeshActor", [_comp("Mesh", "StaticMeshComponent", "/Game/Nature/SM_Tree.SM_Tree")]))
    assert c["role"] == "prop"


def test_unknown_actor():
    c = classify_actor(_actor("Mystery", "Actor", []))
    assert c["role"] == "unknown"
    assert c["role_reason"]


def test_role_reason_present_for_every_actor():
    actors = [
        _actor("Cube", "StaticMeshActor", [_comp("Mesh", "StaticMeshComponent", "/Engine/BasicShapes/Cube.Cube")]),
        _actor("Road", "SplineMeshActor", [_comp("Spline", "SplineMeshComponent", "/Game/Roads/SM_Road.SM_Road")]),
        _actor("Office", "StaticMeshActor", [_comp("Mesh", "StaticMeshComponent", "/Game/Building/CH/SM_Bldg.SM_Bldg")]),
        _vehicle("Car", wheels=4),
        _pedestrian("Ped"),
        _actor("Lamp", "PointLight", []),
        _actor("Cam", "CineCameraActor", []),
        _actor("Mystery", "Actor", []),
    ]
    for a in actors:
        c = classify_actor(a)
        assert isinstance(c["role_reason"], str) and c["role_reason"]


# --- classify_actor: dump_actors shape (lane L7) --------------------------


def test_poseablemesh_vehicle_is_skeletal_vehicle():
    c = classify_actor(_dump_vehicle())
    assert c["role"] == "vehicle"
    assert c["skeletal"] is True
    assert c["wheels"] == 4
    assert not c["blockout"]


def test_vehicle_wheels_come_from_wheel_bones_length():
    assert classify_actor(_dump_vehicle(wheel_bones=["wl", "wr"]))["wheels"] == 2
    assert classify_actor(_dump_vehicle(wheel_bones=[]))["wheels"] == 0


def test_poseablemesh_vehicle_animated_only_with_animation_or_anim_class():
    assert classify_actor(_dump_vehicle())["animated"] is False
    assert classify_actor(_dump_vehicle(
        animation="/Game/Vehicle/vehCar_vehicle02/Anim/SKM_vehCar_vehicle02_Anim"))["animated"] is True
    assert classify_actor(_dump_vehicle(
        anim_class="/Game/Vehicle/vehCar_vehicle02/ABP.ABP_C"))["animated"] is True


def test_dump_person_is_skeletal_animated_pedestrian():
    c = classify_actor(_dump_person())
    assert c["role"] == "pedestrian"
    assert c["skeletal"] is True
    assert c["animated"] is True
    assert not c["blockout"]


def test_dump_person_without_animation_sequence_is_not_animated():
    c = classify_actor(_dump_person(with_animation=False))
    assert c["role"] == "pedestrian"
    assert c["skeletal"] is True
    assert c["animated"] is False


def test_v2_dump_vehicles_and_persons_pass_inventory():
    r = inventory(_dump([_dump_vehicle(), _dump_person()]))
    assert r["vehicles"] == {"count": 1, "with_min_wheels": 1, "pass": True}
    assert r["pedestrians"] == {"count": 1, "skeletal_animated": 1, "pass": True}
    assert r["counts_by_role"]["vehicle"] == 1
    assert r["counts_by_role"]["pedestrian"] == 1
    assert r["counts_by_role"]["prop"] == 0
    assert r["blockout_count"] == 0
    # No buildings in this v2 dump, so building_kits.pass is False and the
    # overall pass is False; the vehicle/pedestrian passes prove the L7 rules.
    assert r["pass"] is False


def test_v2_person_without_animation_fails_pedestrians_pass():
    r = inventory(_dump([_dump_person(with_animation=False)]))
    assert r["pedestrians"] == {"count": 1, "skeletal_animated": 0, "pass": False}
    assert r["pass"] is False


# --- inventory ------------------------------------------------------------


def test_empty_dump_classifies_zero_and_fails():
    r = inventory(_dump([]))
    assert r["schema_version"] == INVENTORY_VERSION
    assert r["level"] == "/Game/Riverside"
    assert all(v == 0 for v in r["counts_by_role"].values())
    assert r["blockout_count"] == 0
    assert r["building_kits"] == {"kits": [], "count": 0, "pass": False}
    assert r["pass"] is False


def test_vehicle_under_min_wheels_fails():
    r = inventory(_dump([_vehicle("Car", wheels=3)]))
    assert r["vehicles"] == {"count": 1, "with_min_wheels": 0, "pass": False}
    assert r["pass"] is False


def test_pedestrian_without_anim_fails_pedestrians():
    r = inventory(_dump([_pedestrian(animated=False)]))
    assert r["pedestrians"] == {"count": 1, "skeletal_animated": 0, "pass": False}
    assert r["pass"] is False


def test_building_kits_threshold_is_parameterised():
    dump = _dump(
        [
            _actor("A", "StaticMeshActor", [_comp("Mesh", "StaticMeshComponent", "/Game/Building/CH/SM_A.SM_A")]),
            _actor("B", "StaticMeshActor", [_comp("Mesh", "StaticMeshComponent", "/Game/Building/DT/SM_B.SM_B")]),
        ]
    )
    assert inventory(dump)["building_kits"]["pass"] is False       # 2 < default 3
    assert inventory(dump, min_building_kits=2)["building_kits"]["pass"] is True


def test_full_world_passes():
    r = inventory(_full_world_dump())
    assert r["blockout_count"] == 0
    assert r["building_kits"]["count"] == 3 and r["building_kits"]["pass"] is True
    assert r["vehicles"]["pass"] is True
    assert r["pedestrians"]["pass"] is True
    assert r["pass"] is True
    assert r["counts_by_role"]["building"] == 3
    assert r["counts_by_role"]["road"] == 1
    assert r["counts_by_role"]["vehicle"] == 1
    assert r["counts_by_role"]["pedestrian"] == 1


def test_single_blockout_actor_fails_overall():
    dump = _full_world_dump()
    dump["actors"].append(
        _actor("BlockoutCube", "StaticMeshActor", [_comp("Mesh", "StaticMeshComponent", "/Engine/BasicShapes/Cube.Cube")])
    )
    r = inventory(dump)
    assert r["blockout_actors"] == ["BlockoutCube"]
    assert r["blockout_count"] == 1
    assert r["pass"] is False


def test_unknown_actors_are_listed():
    dump = _full_world_dump()
    dump["actors"].append(_actor("Mystery", "Actor", []))
    r = inventory(dump)
    assert r["unknown_actors"] == ["Mystery"]
    assert r["counts_by_role"]["unknown"] == 1


def test_inventory_is_deterministic_across_two_writes(tmp_path):
    dump_path = tmp_path / "dump.json"
    dump_path.write_text(json.dumps(_full_world_dump()))
    out_a = tmp_path / "a.json"
    out_b = tmp_path / "b.json"
    write_inventory(dump_path, out_a)
    write_inventory(dump_path, out_b)
    assert out_a.read_bytes() == out_b.read_bytes()


def test_write_inventory_returns_result_and_writes_sorted_json(tmp_path):
    dump_path = tmp_path / "dump.json"
    dump_path.write_text(json.dumps(_full_world_dump()))
    out_path = tmp_path / "inv.json"
    result = write_inventory(dump_path, out_path)
    assert result["pass"] is True
    parsed = json.loads(out_path.read_text())
    assert parsed == result
    # sorted keys at every nesting level
    keys = list(parsed.keys())
    assert keys == sorted(keys)
    assert list(parsed["building_kits"].keys()) == sorted(parsed["building_kits"].keys())


def test_reject_dump_without_level_is_tolerated():
    r = inventory({"schema_version": "actor_dump_v1", "actors": []})
    assert r["level"] is None
    assert r["pass"] is False


# --------------------------------------------------------------------------- dressing roles

def _dressing_actor(label, tag, comps):
    return {"name": label, "class": "Actor", "label": label, "folder": None,
            "tags": ["ld_dressing", tag],
            "location": {"x": 0.0, "y": 0.0, "z": 0.0},
            "rotation": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0},
            "components": comps}


def test_lane_marking_actor_is_classified_not_unknown():
    """A marking actor carries only DecalComponents, so every mesh-shaped rule
    misses it. Without an explicit tag rule the 48 marking actors land in
    "unknown", which reads as an unidentified object in the world. Would break
    if the tag rule were removed or reordered below the mesh rules."""
    a = _dressing_actor("LD_Mark_A0A1", "ld_marking", [
        {"name": "Decal0", "class": "DecalComponent", "asset": None,
         "asset_lower": None, "instance_count": None, "anim_class": None,
         "animation": None, "skeleton": None}])
    r = classify_level_actor(a)
    assert r["role"] == "road_marking"
    assert r["blockout"] is False


def test_crosswalk_and_signal_and_closure_roles():
    for tag, want in (("ld_crosswalk", "crosswalk"), ("ld_signal", "traffic_signal"),
                      ("ld_closure", "closure_prop"), ("ld_furniture", "street_furniture")):
        a = _dressing_actor("LD_X", tag, [
            {"name": "ISM", "class": "InstancedStaticMeshComponent",
             "asset": "/Game/Prop/Kit/SM_Thing", "asset_lower": "/game/prop/kit/sm_thing",
             "instance_count": 3, "anim_class": None, "animation": None, "skeleton": None}])
        assert classify_level_actor(a)["role"] == want, tag


def test_tree_pit_tag_beats_tree_tag():
    """The pit actor carries both ld_tree_base and (historically) tree-ish
    labels; the pit rule must win so pits are not counted as trees."""
    a = _dressing_actor("LD_Pit", "ld_tree_base", [
        {"name": "ISM", "class": "InstancedStaticMeshComponent",
         "asset": "/Game/Prop/Kit_TreeBase_A/Mesh/SM_TreeBase_Circle_A",
         "asset_lower": "/game/prop/kit_treebase_a/mesh/sm_treebase_circle_a",
         "instance_count": 240, "anim_class": None, "animation": None, "skeleton": None}])
    assert classify_level_actor(a)["role"] == "tree_pit"
    b = _dressing_actor("LD_Tree", "ld_tree", [
        {"name": "ISM", "class": "InstancedStaticMeshComponent",
         "asset": "/Game/Prop/Kit_Tree_Maple_Sugar/Mesh/Tree_Maple_A",
         "asset_lower": "/game/prop/kit_tree_maple_sugar/mesh/tree_maple_a",
         "instance_count": 88, "anim_class": None, "animation": None, "skeleton": None}])
    assert classify_level_actor(b)["role"] == "tree"
