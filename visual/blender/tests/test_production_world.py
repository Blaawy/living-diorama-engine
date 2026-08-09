"""Structural tests for the Phase 16 production world.

Executed by ``run_blender_tests_p16.py`` inside background Blender, after
every Phase 15 structural test has passed against the freshly rebuilt
founding scene. These tests own the PRODUCTION half of the redesign
contract: semantic history is never touched (plates, architecture, wall
stations, Seal, harbor, depots, avenues), the deterministic legacy
clearing removes EXACTLY the planned vegetation clusters and nothing
else, the Phase 15 legacy build still reproduces every cluster, the
fabric converges on rebuild, every street the graph declares exists, the
material family gains nothing, and episode application keeps working
over the redesigned city.
"""

import sys
from pathlib import Path

import bpy

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import apply_render_export  # noqa: E402
import build_master_scene  # noqa: E402
import build_production_world  # noqa: E402
from production_spec import load_production_world_spec  # noqa: E402
from road_graph import build_road_graph  # noqa: E402
from scene_spec import load_master_scene_spec  # noqa: E402
from urban_fabric import plan_legacy_clearing, plan_urban_fabric  # noqa: E402

PRODUCTION_PREFIXES = ("LD_P16_", "CAM_P16_")

FOUNDING_TREE_PREFIX = "LD_TREE__"

RING_ROAD_SUFFIX = "__ring_road"


def anchor_snapshot() -> list[tuple]:
    """Identity and transform of every SEMANTIC founding object.

    Everything Phase 15 built except the two PRESENTATION sets the final
    composition is authorised to replace -- the decorative vegetation
    clusters and the district ring discs. Plates, architecture, depots,
    wall stations, the Seal, the harbor, avenues, spurs, lamps, and
    cameras are semantic: the redesign may never move any of them.
    """
    entries = []
    for obj in bpy.data.objects:
        if not obj.name.startswith(("LD_", "CAM_")):
            continue
        if obj.name.startswith(PRODUCTION_PREFIXES):
            continue
        if obj.name.startswith(FOUNDING_TREE_PREFIX):
            continue
        if obj.name.endswith(RING_ROAD_SUFFIX):
            continue
        entries.append(
            (
                obj.name,
                tuple(round(value, 5) for value in obj.location),
                tuple(round(value, 5) for value in obj.rotation_euler),
                tuple(round(value, 5) for value in obj.scale),
            )
        )
    return sorted(entries)


def founding_tree_names() -> set[str]:
    """Every founding vegetation cluster object currently in the scene."""
    return {obj.name for obj in bpy.data.objects if obj.name.startswith(FOUNDING_TREE_PREFIX)}


def founding_ring_names() -> set[str]:
    """Every founding district ring disc currently in the scene."""
    return {obj.name for obj in bpy.data.objects if obj.name.endswith(RING_ROAD_SUFFIX)}


def _plan(context) -> dict:
    """The deterministic production plan for the loaded specs."""
    master_spec = load_master_scene_spec(context["spec_path"])
    production_spec = load_production_world_spec(context["production_path"])
    graph = build_road_graph(master_spec, production_spec)
    return plan_urban_fabric(master_spec, production_spec, graph)


def production_snapshot() -> list[tuple]:
    """Identity and transform of every production object."""
    entries = []
    for obj in bpy.data.objects:
        if not obj.name.startswith(PRODUCTION_PREFIXES):
            continue
        entries.append(
            (
                obj.name,
                tuple(round(value, 5) for value in obj.location),
                tuple(round(value, 5) for value in obj.rotation_euler),
            )
        )
    return sorted(entries)


def ld_material_names() -> set[str]:
    """Every LD material name currently in the file."""
    return {m.name for m in bpy.data.materials if m.name.startswith("LD_MAT__")}


def _clearing(context) -> dict:
    """The deterministic legacy clearing decision for the loaded specs."""
    master_spec = load_master_scene_spec(context["spec_path"])
    production_spec = load_production_world_spec(context["production_path"])
    graph = build_road_graph(master_spec, production_spec)
    return plan_legacy_clearing(master_spec, production_spec, graph)


def test_the_pure_founding_tree_replica_matches_the_real_meshes(context) -> None:
    """The pure vegetation replica IS the founding forest, not a guess.

    ``spatial_occupancy.founding_tree_clusters`` replays the locked Phase
    15 sampling algorithm so the pure planner knows where every founding
    tree stands without Blender. The clearing decision and the whole
    spatial contract rest on that replica being exact, so it is compared
    here against the transforms of the real cluster objects.

    Runs FIRST, against the pure founding scene: once the production
    world is added, the cleared clusters are gone and there would be
    nothing left to compare them with.
    """
    from spatial_occupancy import founding_tree_clusters

    master_spec = load_master_scene_spec(context["spec_path"])
    replica = founding_tree_clusters(master_spec)
    assert len(replica) == 40, "the replica must reproduce all forty clusters"
    for index, (x, y) in enumerate(replica):
        obj = bpy.data.objects.get(f"{FOUNDING_TREE_PREFIX}{index:02d}")
        assert obj is not None, f"cluster {index} is missing from the founding scene"
        assert abs(obj.location.x - x) < 1.0e-5 and abs(obj.location.y - y) < 1.0e-5, (
            f"cluster {index} replica ({x:.5f}, {y:.5f}) diverges from the built mesh "
            f"({obj.location.x:.5f}, {obj.location.y:.5f})"
        )


def test_production_build_preserves_semantic_history(context) -> None:
    """Adding the production city leaves every semantic anchor identical.

    The redesign's hard requirement: broad presentation freedom over
    decorative vegetation, ZERO freedom over semantic history. The anchor
    snapshot is byte-stable across the add, and the material family gains
    and loses nothing.
    """
    before = anchor_snapshot()
    trees_before = founding_tree_names()
    assert len(trees_before) == 40, "the founding scene must start with all 40 clusters"
    assert len(founding_ring_names()) == 4, "the founding scene must start with all 4 ring discs"
    materials_before = ld_material_names()
    context["production_summary"] = build_production_world.add_production_world(
        context["spec_path"], context["production_path"]
    )
    assert anchor_snapshot() == before, "adding the production world moved semantic history"
    assert ld_material_names() == materials_before, (
        "the production world may not invent or drop materials"
    )


def test_legacy_clearing_removes_exactly_the_planned_clusters(context) -> None:
    """The suppressed set IS the plan's removed set -- both directions.

    Every cluster the deterministic clearing keeps still stands; every
    cluster it clears is gone; nothing else was touched. Presentation
    freedom is exercised deterministically or not at all.
    """
    clearing = _clearing(context)
    expected_kept = {f"LD_TREE__{index:02d}" for index in clearing["kept"]}
    expected_removed = set(clearing["removed_objects"])
    present = founding_tree_names()
    assert present == expected_kept, (
        f"preserved clusters diverge from the plan: {sorted(present ^ expected_kept)}"
    )
    assert not (present & expected_removed), "a cleared cluster survived suppression"
    assert expected_kept | expected_removed == {f"LD_TREE__{index:02d}" for index in range(40)}, (
        "the clearing decision must partition all 40 founding clusters"
    )


def test_ring_discs_are_suppressed_exactly_where_the_circle_is_buried(context) -> None:
    """The pod circles go; the designed civic Ring stays -- both pinned.

    A district whose ground plan keeps its ring whole must still carry
    its founding ring disc; a district whose empty sectors are buried
    must have handed its disc to Phase 16, which redraws the kept arcs
    as real streets. Nothing else may be suppressed.
    """
    plan = _plan(context)
    plates = plan["ground"]["plates"]
    expected_present = {
        f"LD_DISTRICT__{district_id}__ring_road"
        for district_id, plate in plates.items()
        if plate["ring"] == "full"
    }
    expected_gone = {
        f"LD_DISTRICT__{district_id}__ring_road"
        for district_id, plate in plates.items()
        if plate["ring"] != "full"
    }
    assert expected_gone, "the final composition must bury at least one pod circle"
    present = founding_ring_names()
    assert present == expected_present, (
        f"ring suppression diverges from the plan: {sorted(present ^ expected_present)}"
    )
    names = {obj.name for obj in bpy.data.objects}
    for district_id, plate in sorted(plates.items()):
        if plate["ring"] == "full":
            continue
        arcs = [name for name in names if name.startswith(f"LD_P16_RING__{district_id}__")]
        assert len(arcs) == len(plate["kept_arcs"]), (
            f"{district_id} kept {len(plate['kept_arcs'])} arcs but drew {len(arcs)} streets"
        )


def test_the_buried_rim_does_not_survive_as_a_circle(context) -> None:
    """Every plate's measured rim exposure stays inside the contract.

    This is the Phase 16 acceptance test made numeric: a buried plate may
    show only the few degrees history's own corridors withhold, never a
    readable circle.
    """
    from city_ground import MAX_RIM_EXPOSURE_DEG

    plan = _plan(context)
    for district_id, plate in sorted(plan["ground"]["plates"].items()):
        assert plate["rim_exposure_deg"] <= MAX_RIM_EXPOSURE_DEG, (
            f"{district_id} still reads as a pod: {plate['rim_exposure_deg']} degrees of rim"
        )


def test_city_ground_objects_exist(context) -> None:
    """The composition's ground layer is really in the scene."""
    names = {obj.name for obj in bpy.data.objects}
    plan = _plan(context)
    for district_id in plan["ground"]["plates"]:
        assert f"LD_P16_GROUND__{district_id}" in names, (
            f"district {district_id} has no urban ground object"
        )
    surfaces = {cell["surface"] for cell in plan["ground"]["cells"].values()}
    for surface in surfaces:
        assert f"LD_P16_GROUND__cells_{surface}" in names, (
            f"the {surface} ground cells were not built"
        )


def test_phase15_legacy_build_still_reproduces_every_cluster(context) -> None:
    """The locked Phase 15 build remains fully reproducible.

    Rebuilding the master scene alone brings back all 40 vegetation
    clusters -- the redesign suppresses presentation objects only in the
    PRODUCTION build, never by rewriting canonical history. Re-adding the
    production world re-applies the same deterministic clearing, and with
    the same episode state re-applied on both sides of the cycle, every
    semantic anchor ends exactly where it started.
    """
    apply_render_export.apply_render_export_file(context["spec_path"], context["after_path"])
    anchors_before = anchor_snapshot()
    build_master_scene.build_master_scene(context["spec_path"])
    assert len(founding_tree_names()) == 40, (
        "the Phase 15 legacy build no longer reproduces its 40 clusters"
    )
    assert len(founding_ring_names()) == 4, (
        "the Phase 15 legacy build no longer reproduces its 4 ring discs"
    )
    build_production_world.add_production_world(context["spec_path"], context["production_path"])
    clearing = _clearing(context)
    assert founding_tree_names() == {f"LD_TREE__{index:02d}" for index in clearing["kept"]}, (
        "re-adding the production world did not re-apply the clearing"
    )
    apply_render_export.apply_render_export_file(context["spec_path"], context["after_path"])
    assert anchor_snapshot() == anchors_before, "the legacy rebuild cycle moved semantic history"


def test_production_rebuild_is_semantically_idempotent(context) -> None:
    """Adding the production world again converges to the same scene."""
    first = production_snapshot()
    build_production_world.add_production_world(context["spec_path"], context["production_path"])
    assert production_snapshot() == first, "re-adding the production world changed it"
    assert not any(obj.name.endswith(".001") for obj in bpy.data.objects), (
        "production rebuild produced .001 duplicates"
    )


def test_production_cameras_exist(context) -> None:
    """All eight Phase 16 camera anchors exist as cameras."""
    for name in (
        "CAM_P16_WORLD_HERO",
        "CAM_P16_SYSTEM",
        "CAM_P16_CORE_CONTEXT",
        "CAM_P16_SCAR_CONTEXT",
        "CAM_P16_ROADS",
        "CAM_P16_DENSITY",
        "CAM_P16_VALIDITY",
        "CAM_P16_URBAN",
        "CAM_P16_COMPOSITION",
    ):
        camera = bpy.data.objects.get(name)
        assert camera is not None, f"camera {name} is missing"
        assert camera.type == "CAMERA", f"{name} is not a camera"


def test_every_declared_street_exists_exactly_once(context) -> None:
    """Each production graph segment resolves to exactly one street mesh."""
    master_spec = load_master_scene_spec(context["spec_path"])
    production_spec = load_production_world_spec(context["production_path"])
    graph = build_road_graph(master_spec, production_spec)
    names = {obj.name for obj in bpy.data.objects}
    for segment_id, segment in graph["segments"].items():
        if segment["existing"]:
            continue
        street = f"LD_P16_STREET__{segment_id}"
        assert street in names, f"{street} is missing"
        assert f"{street}.001" not in names, f"{street} was duplicated"
    assert "LD_P16_JUNCTIONS" in names, "the junction/turnaround mesh is missing"


def test_every_lot_stands_on_its_plinth(context) -> None:
    """Ground is lot-derived: every planned lot has its plinth, no pods."""
    names = {obj.name for obj in bpy.data.objects}
    lots = [name for name in names if name.startswith("LD_P16_BLDG__") and name.endswith("__m0")]
    assert lots, "the production world placed no buildings"
    for mass_name in lots:
        plinth = mass_name.removesuffix("__m0") + "__plinth"
        assert plinth in names, f"{plinth} is missing"
    assert not any(name.startswith("LD_P16_PAD__") for name in names), (
        "circular quarter pads must not exist; ground is derived from lots"
    )


def test_no_production_building_stands_on_a_founding_plate(context) -> None:
    """The historic core is never overbuilt: fabric keeps off every plate."""
    master_spec = load_master_scene_spec(context["spec_path"])
    for obj in bpy.data.objects:
        if not obj.name.startswith("LD_P16_BLDG__"):
            continue
        for district_id, district in master_spec["districts"].items():
            gap = (
                (obj.location.x - district["center"][0]) ** 2
                + (obj.location.y - district["center"][1]) ** 2
            ) ** 0.5
            assert gap > district["radius"] + 1.5, (
                f"{obj.name} stands on founding plate {district_id}"
            )


def test_apply_export_preserves_founding_and_production(context) -> None:
    """Episode application still works and never disturbs either city layer.

    The wall scar must exist after applying the after-export -- the larger
    city keeps its memory anchor -- and re-application stays idempotent.
    """
    anchors_before = anchor_snapshot()
    trees_before = founding_tree_names()
    rings_before = founding_ring_names()
    production_before = production_snapshot()
    apply_render_export.apply_render_export_file(context["spec_path"], context["before_path"])
    apply_render_export.apply_render_export_file(context["spec_path"], context["after_path"])
    assert anchor_snapshot() == anchors_before, "apply moved semantic history"
    assert founding_tree_names() == trees_before, "apply changed the preserved groves"
    assert founding_ring_names() == rings_before, "apply changed the preserved ring discs"
    assert production_snapshot() == production_before, "apply moved production objects"
    walls = [obj for obj in bpy.data.objects if obj.name.startswith("LD_WALL__")]
    assert walls, "the after-state wall is missing from the expanded city"


def test_scene_stays_production_practical(context) -> None:
    """The expanded world keeps a render- and animation-practical budget."""
    total = len(bpy.data.objects)
    assert total < 1500, f"scene object count {total} exceeds the production budget"
