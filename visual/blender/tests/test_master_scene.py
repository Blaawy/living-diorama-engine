"""Structural tests for the persistent master scene build.

Executed by ``run_blender_tests.py`` inside background Blender, against a
scene the runner has already built from the Master Scene Spec. These tests
own the PERSISTENT half of the contract: collections, cameras, districts,
boundaries, the Golden Seal, naming, and build idempotency.
"""

import sys
from pathlib import Path

import bpy

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_master_scene  # noqa: E402
from blender_runtime import CHILD_COLLECTIONS, ROOT_COLLECTION  # noqa: E402


def scene_object_names() -> set[str]:
    """Every object name currently in the scene."""
    return {obj.name for obj in bpy.data.objects}


def semantic_snapshot() -> list[tuple]:
    """A comparable capture of every LD object's identity and transform."""
    entries = []
    for obj in bpy.data.objects:
        if not obj.name.startswith(("LD_", "CAM_")):
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


def test_required_collections_exist(context) -> None:
    """The full LD collection tree exists under the root collection."""
    root = bpy.data.collections.get(ROOT_COLLECTION)
    assert root is not None, "LD_WORLD collection is missing"
    child_names = {collection.name for collection in root.children}
    for name in CHILD_COLLECTIONS:
        assert name in child_names, f"collection {name} is missing from LD_WORLD"


def test_required_cameras_exist(context) -> None:
    """All five persistent camera anchors exist as cameras."""
    for name in (
        "CAM_HERO_WORLD",
        "CAM_HERO_SCAR",
        "CAM_SCAR_DETAIL",
        "CAM_SEAL_DETAIL",
        "CAM_VERIFY_TOPOLOGY",
    ):
        camera = bpy.data.objects.get(name)
        assert camera is not None, f"camera {name} is missing"
        assert camera.type == "CAMERA", f"{name} is not a camera"


def test_hero_camera_differs_from_comparison_camera(context) -> None:
    """The dedicated hero composition is not the comparison composition.

    Candidate V1 failed visual review because the hero frame and the after
    frame were the same camera; this pins the split permanently.
    """
    hero = bpy.data.objects.get("CAM_HERO_SCAR")
    comparison = bpy.data.objects.get("CAM_HERO_WORLD")
    assert hero is not None and comparison is not None
    hero_transform = (tuple(hero.location), tuple(hero.rotation_euler))
    comparison_transform = (tuple(comparison.location), tuple(comparison.rotation_euler))
    assert hero_transform != comparison_transform, (
        "CAM_HERO_SCAR must be a genuinely different composition from CAM_HERO_WORLD"
    )


def test_golden_seal_monument_identity(context) -> None:
    """The Seal is a civic emblem: disc, boss, gnomon blade, compass rose."""
    for name in (
        "LD_SEAL__disc",
        "LD_SEAL__boss",
        "LD_SEAL__gnomon",
        "LD_SEAL__rose",
        "LD_SEAL__plinth",
    ):
        assert bpy.data.objects.get(name) is not None, f"{name} is missing"


def test_no_factory_defaults_remain(context) -> None:
    """The startup Cube/Camera/Light never survive into the master scene."""
    for name in ("Cube", "Camera", "Light"):
        assert bpy.data.objects.get(name) is None, f"factory default {name} survived"


def test_every_district_exists_exactly_once(context) -> None:
    """Each spec district resolves to exactly one plate, with no .001 copies."""
    names = scene_object_names()
    for district_id in context["spec"]["districts"]:
        plate = f"LD_DISTRICT__{district_id}"
        assert plate in names, f"{plate} is missing"
        assert f"{plate}.001" not in names, f"{plate} was duplicated"


def test_every_boundary_exists_exactly_once(context) -> None:
    """Each spec boundary resolves to exactly one avenue, with no copies."""
    names = scene_object_names()
    for boundary_id in context["spec"]["boundaries"]:
        road = f"LD_ROAD__{boundary_id}"
        assert road in names, f"{road} is missing"
        assert f"{road}.001" not in names, f"{road} was duplicated"


def test_golden_seal_identity_exists(context) -> None:
    """The Rule Object stands at its configured plaza."""
    disc = bpy.data.objects.get("LD_SEAL__disc")
    assert disc is not None, "the Golden Seal disc is missing"
    ring = bpy.data.objects.get("LD_SEAL_RING")
    assert ring is not None, "the Golden Seal law ring is missing"
    seal = context["spec"]["landmarks"]["golden_seal"]
    assert round(disc.location.x, 4) == seal["location"][0]
    assert round(disc.location.y, 4) == seal["location"][1]


def test_rebuild_is_semantically_idempotent(context) -> None:
    """Building the master scene again converges to the same scene.

    Same names, same transforms, no ``.001`` growth. This rebuild also leaves
    the scene in exactly the state later apply-tests expect.
    """
    first = semantic_snapshot()
    context["spec"] = build_master_scene.build_master_scene(context["spec_path"])
    second = semantic_snapshot()
    assert first == second, "rebuilding the master scene changed the scene"
    assert not any(name.endswith(".001") for name in scene_object_names()), (
        "rebuild produced .001 duplicates"
    )
