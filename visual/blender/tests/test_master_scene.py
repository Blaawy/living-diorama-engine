"""Structural tests for the persistent master scene build.

Executed by ``run_blender_tests.py`` inside background Blender, against a
scene the runner has already built from the Master Scene Spec. These tests
own the PERSISTENT half of the contract: collections, cameras, districts,
boundaries, the Golden Seal, naming, and build idempotency.

They also own the RIBBON TRIM, because Phase 15 is the build that lays the
avenues, sidewalks, curbs, markings and spurs and therefore the build that
has to stop laying them through founding architecture. The pure suite
``tests/visual/test_road_trim.py`` proves the trim's arithmetic by
reconstructing the faces the builder will emit; what no pure suite can
prove is that the builder actually emits those faces. That is what
:func:`test_no_built_road_mesh_stands_in_founding_architecture` is for, and
it is the reason the pure reconstruction cannot quietly go stale.
"""

import sys
from pathlib import Path

import bpy

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_master_scene  # noqa: E402
from blender_runtime import CHILD_COLLECTIONS, ROOT_COLLECTION  # noqa: E402
from spatial_occupancy import (  # noqa: E402
    _rect_corners,
    _rect_point_distance,
    convex_polygons_intersect,
    founding_building_footprints,
)

ROAD_LAYER_PREFIXES = (
    "LD_ROAD__",
    "LD_SIDEWALK__",
    "LD_CURB__",
    "LD_MARKING__",
    "LD_SPUR__",
)
"""Every object family the ribbon trim is responsible for.

The five drawn road layers, including ``LD_MARKING__<boundary>__center``:
the centre dashes are individual boxes rather than a strip, so they are
filtered by :func:`spatial_occupancy.founding_point_is_covered` on their
CENTRE POINT alone. That filter is only safe while no dash centre lands
within half a dash of a building -- and the built mesh, not the filter, is
what this suite measures, so a dash box poking into a podium fails here
even though the point filter waved it through.
"""

RING_DISC_SEGMENTS_PINNED_PURELY = 72
"""What ``tests/visual/test_road_trim.py`` assumes the disc resolution is.

That suite cannot import :mod:`build_master_scene` -- the module needs
``bpy`` -- so it carries its own copy of the constant and reconstructs the
wedge fan from it. A copy is a thing that can drift, so the two are
compared HERE, where both are importable. This is the cheapest possible
insurance that a resolution change fails somewhere loudly instead of
silently invalidating a pure pin.
"""

SWALLOWED_SPUR = "LD_SPUR__boundary_cd__district_c"
"""The one road object whose entire run lies inside a founding building."""


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


# ---------------------------------------------------------------------------
# The ribbon trim, proved on the mesh Blender actually welded
# ---------------------------------------------------------------------------


def _founding_parts(context) -> list[dict]:
    """Every founding building part, as the rects the ribbon trim reads.

    The same source ``vehicle_lane_network`` refuses runs from and the same
    source ``_trimmed_ribbon`` trims against, so the drawn mesh, the lane
    guard and this test cannot disagree about where a building stands.
    """
    return [
        entry["shape"]
        for lot in founding_building_footprints(context["spec"])
        for entry in lot["parts"]
    ]


def _road_layer_objects() -> list:
    """Every built mesh belonging to a trimmed road family."""
    return [
        obj
        for obj in bpy.data.objects
        if obj.type == "MESH" and obj.name.startswith(ROAD_LAYER_PREFIXES)
    ]


def test_the_road_layers_were_actually_built(context) -> None:
    """The trim test below is worthless if it inspects an empty scene."""
    built = _road_layer_objects()
    assert built, "no road-layer object exists at all"
    families = {obj.name.split("__")[0] for obj in built}
    assert families == {prefix.rstrip("_") for prefix in ROAD_LAYER_PREFIXES}, (
        f"the scene is missing a road family: {sorted(families)}"
    )
    for boundary_id in context["spec"]["boundaries"]:
        assert bpy.data.objects.get(f"LD_ROAD__{boundary_id}") is not None


def test_no_built_road_mesh_stands_in_founding_architecture(context) -> None:
    """The assertion the pure reconstruction cannot make for itself.

    Every road-layer mesh in the file is measured against the founding
    footprints in WORLD space: every vertex, every edge midpoint and every
    face centre must lie outside every building. Sampling all three matters
    because a face can straddle a footprint without any of its corners being
    inside it, and the projected-face check below closes even that gap.

    This is the test that fails loudly if a builder's offset or width ever
    diverges from the ``BOUNDARY_LAYERS`` table the pure suite reconstructs
    from. A pure suite pinned to a reconstruction can pass forever against a
    model that no longer describes the builder; this one reads the mesh.
    """
    bpy.context.view_layer.update()
    parts = _founding_parts(context)
    assert parts, "the founding layer reported no building parts to avoid"
    offenders: list[str] = []
    for obj in _road_layer_objects():
        mesh = obj.data
        matrix = obj.matrix_world
        world = [matrix @ vertex.co for vertex in mesh.vertices]
        samples: list[tuple[str, float, float]] = [
            (f"vertex {index}", point.x, point.y) for index, point in enumerate(world)
        ]
        for edge in mesh.edges:
            near, far = world[edge.vertices[0]], world[edge.vertices[1]]
            samples.append(
                (f"edge {edge.index} midpoint", (near.x + far.x) / 2.0, (near.y + far.y) / 2.0)
            )
        for polygon in mesh.polygons:
            centre = matrix @ polygon.center
            samples.append((f"face {polygon.index} centre", centre.x, centre.y))
        for label, x, y in samples:
            inside = next(
                (shape for shape in parts if _rect_point_distance(shape, x, y) <= 0.0), None
            )
            if inside is not None:
                offenders.append(f"{obj.name} {label} at ({x:.2f}, {y:.2f})")
                break
    assert not offenders, "road geometry inside founding architecture: " + "; ".join(offenders[:6])


def test_no_built_road_face_straddles_founding_architecture(context) -> None:
    """A face can cross a building without putting a single point inside it.

    The point samples above would miss a long thin face spanning a small
    footprint, so every horizontal face is also tested AS A POLYGON, with the
    same separating-axis routine the trim itself is gated on. Faces that
    project to a line -- the vertical sides an extrusion produces -- carry no
    area in plan and are skipped rather than fed to a convex test that has no
    meaningful answer for them.
    """
    bpy.context.view_layer.update()
    parts = _founding_parts(context)
    offenders: list[str] = []
    for obj in _road_layer_objects():
        mesh = obj.data
        matrix = obj.matrix_world
        for polygon in mesh.polygons:
            corners = [matrix @ mesh.vertices[index].co for index in polygon.vertices]
            flat = {(round(point.x, 6), round(point.y, 6)) for point in corners}
            if len(flat) < 3:
                continue
            hit = next(
                (
                    shape
                    for shape in parts
                    if convex_polygons_intersect(
                        [(point.x, point.y) for point in corners], _rect_corners(shape)
                    )
                ),
                None,
            )
            if hit is not None:
                offenders.append(f"{obj.name} face {polygon.index}")
                break
    assert not offenders, "road faces crossing founding architecture: " + "; ".join(offenders[:6])


def test_the_pure_suites_ring_disc_resolution_is_still_correct(context) -> None:
    """The duplicated constant is compared where both copies are importable.

    ``tests/visual/test_road_trim.py`` reconstructs the ring-disc wedge fan
    from its own copy of this number, because importing the builder would
    pull in ``bpy``. If the builder ever changes resolution, that pure pin
    silently starts describing a disc nobody draws -- unless this fails
    first, which is the whole job of this test.
    """
    assert build_master_scene.RING_DISC_SEGMENTS == RING_DISC_SEGMENTS_PINNED_PURELY


def test_a_road_swallowed_by_a_building_survives_as_an_empty_object(context) -> None:
    """A road the city cannot draw keeps its name and draws nothing.

    ``LD_SPUR__boundary_cd__district_c`` runs entirely inside
    ``LD_BLDG__district_c__001``, so every span of it is trimmed away. The
    contract is that it still EXISTS: an empty object is honest about a road
    the city cannot show, and nothing that looks the name up is left holding
    a reference to something that vanished. A test asserting that every road
    object carries faces would be wrong, and this is the object that proves
    it -- so the emptiness is pinned here rather than left to be "fixed".
    """
    obj = bpy.data.objects.get(SWALLOWED_SPUR)
    assert obj is not None, f"{SWALLOWED_SPUR} was deleted rather than emptied"
    assert obj.type == "MESH"
    assert len(obj.data.polygons) == 0, (
        f"{SWALLOWED_SPUR} drew {len(obj.data.polygons)} face(s); its whole run is inside a "
        "founding building"
    )
    assert len(obj.data.vertices) == 0
    # Every OTHER spur still draws something, or the trim has eaten the city.
    drawing = [
        other
        for other in bpy.data.objects
        if other.type == "MESH"
        and other.name.startswith("LD_SPUR__")
        and other.name != SWALLOWED_SPUR
        and len(other.data.polygons)
    ]
    assert len(drawing) >= 6, f"only {len(drawing)} spurs still draw geometry"
