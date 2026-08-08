"""Structural tests for episode-state application and scar continuity.

Executed by ``run_blender_tests.py`` after the master-scene tests, in the
same background Blender session. These tests own the EPISODE half of the
contract: wall creation and removal, idempotent re-application, topology
refusals, continuity of geography across before/after, and headless render
output.
"""

import json
import sys
from pathlib import Path

import bpy

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import apply_render_export  # noqa: E402
import render_visual_proof  # noqa: E402
from blender_runtime import distance_to_polyline  # noqa: E402
from scene_spec import SceneContractError  # noqa: E402


def objects_with_prefix(prefix: str) -> list:
    """Every scene object whose name begins with the prefix."""
    return [obj for obj in bpy.data.objects if obj.name.startswith(prefix)]


def transforms_of(prefixes: tuple[str, ...]) -> list[tuple]:
    """A comparable transform capture of every object under the prefixes."""
    entries = []
    for obj in bpy.data.objects:
        if not obj.name.startswith(prefixes):
            continue
        entries.append(
            (
                obj.name,
                tuple(round(value, 5) for value in obj.location),
                tuple(round(value, 5) for value in obj.rotation_euler),
            )
        )
    return sorted(entries)


PERSISTENT_PREFIXES = (
    "LD_DISTRICT__",
    "LD_BLDG__",
    "LD_SEAL",
    "CAM_",
    "LD_ROAD__",
    "LD_PLATFORM",
    "LD_TERRAIN",
    "LD_TREE__",
    "LD_HARBOR",
    "LD_CRANE__",
    "LD_MARKING__",
    "LD_SPUR__",
    "LD_STREETLIGHT__",
    "LD_DEPOT__",
    "LD_SIDEWALK__",
    "LD_CURB__",
)


def test_wall_application_creates_the_wall_exactly_once(context) -> None:
    """The engine-built wall appears with its exact identity, once."""
    apply_render_export.apply_render_export_file(context["spec_path"], context["after_path"])
    foundations = objects_with_prefix("LD_WALL__wall_boundary_ab__foundation")
    assert len(foundations) == 1, "expected exactly one wall foundation"
    assert objects_with_prefix("LD_WALL__wall_boundary_ab__seg"), "wall segments missing"


def test_wall_gate_complex_exists(context) -> None:
    """The wall carries its controlled gate: towers, door, and floodlights."""
    for suffix in ("gate_tower_a", "gate_tower_b", "gate_door", "gate_lintel", "flood_a"):
        name = f"LD_WALL__wall_boundary_ab__{suffix}"
        assert bpy.data.objects.get(name) is not None, f"{name} is missing"


def test_occupancy_drives_the_glass_lit_fraction(context) -> None:
    """Population maps deterministically onto each district's glazing.

    For every exported district, the LD_LitFraction value node of its
    character's glass material must equal 0.12 + 0.55 x occupancy exactly.
    """
    export = json.loads(context["after_path"].read_text(encoding="utf-8"))
    for district in export["world"]["districts"]:
        definition = context["spec"]["districts"][district["id"]]
        capacity = district["housing_capacity"]
        occupancy = 0.0
        if capacity > 0:
            occupancy = max(0.0, min(1.0, district["population"] / capacity))
        material = bpy.data.materials.get(f"LD_MAT__glass_{definition['character']}")
        assert material is not None, f"glass material for {district['id']} is missing"
        node = material.node_tree.nodes.get("LD_LitFraction")
        assert node is not None, "LD_LitFraction node missing from glass material"
        expected = 0.12 + 0.55 * occupancy
        actual = node.outputs[0].default_value
        assert abs(actual - expected) < 1.0e-6, (
            f"{district['id']}: lit fraction {actual} != expected {expected}"
        )


def test_reapplication_does_not_duplicate(context) -> None:
    """Applying the same export twice converges to the same episode layer."""
    before_names = sorted(obj.name for obj in bpy.data.objects)
    apply_render_export.apply_render_export_file(context["spec_path"], context["after_path"])
    after_names = sorted(obj.name for obj in bpy.data.objects)
    assert before_names == after_names, "re-application changed the object set"
    assert not any(name.endswith(".001") for name in after_names), (
        "re-application produced .001 duplicates"
    )


def test_same_inputs_produce_equivalent_semantic_state(context) -> None:
    """Same spec + same export yield the same semantic scene state."""
    first = transforms_of(("LD_",))
    apply_render_export.apply_render_export_file(context["spec_path"], context["after_path"])
    second = transforms_of(("LD_",))
    assert first == second, "identical inputs produced different scene state"


def test_infrastructure_resolves_to_its_boundary(context) -> None:
    """Infrastructure conduits follow the boundary they serve."""
    export = json.loads(context["after_path"].read_text(encoding="utf-8"))
    boundary_paths = {
        boundary_id: [tuple(point) for point in entry["path"]]
        for boundary_id, entry in context["spec"]["boundaries"].items()
    }
    for infrastructure in export["world"]["infrastructure"]:
        pipes = objects_with_prefix(f"LD_INFRA__{infrastructure['id']}__pipe")
        assert pipes, f"conduit for {infrastructure['id']} is missing"
        path = boundary_paths[infrastructure["boundary_id"]]
        for pipe in pipes:
            distance = distance_to_polyline(pipe.location.x, pipe.location.y, path)
            assert distance < 8.0, (
                f"{pipe.name} sits {distance:.1f}m from boundary {infrastructure['boundary_id']}"
            )


def test_wall_dependency_struts_anchor_the_conduits(context) -> None:
    """Adapted infrastructure visibly ties into the wall."""
    struts = objects_with_prefix("LD_INFRA__infra_ab_transit__wallstrut")
    assert struts, "the adapted transit conduit has no wall struts"


def test_before_state_removes_the_wall_and_keeps_geography(context) -> None:
    """A no-wall export clears the scar while the city stands unchanged."""
    persistent_before = transforms_of(PERSISTENT_PREFIXES)
    apply_render_export.apply_render_export_file(context["spec_path"], context["before_path"])
    assert not objects_with_prefix("LD_WALL__"), "the wall survived a no-wall export"
    persistent_after = transforms_of(PERSISTENT_PREFIXES)
    assert persistent_before == persistent_after, (
        "removing the episode wall disturbed persistent geography"
    )


def test_before_and_after_share_identical_geography(context) -> None:
    """District plates, buildings, seal, cameras, and avenues never move.

    This is the scar-continuity acceptance test: only the episode layer may
    differ between the before and after worlds.
    """
    apply_render_export.apply_render_export_file(context["spec_path"], context["before_path"])
    before_transforms = transforms_of(PERSISTENT_PREFIXES)
    apply_render_export.apply_render_export_file(context["spec_path"], context["after_path"])
    after_transforms = transforms_of(PERSISTENT_PREFIXES)
    assert before_transforms == after_transforms, (
        "persistent geography differs between before and after episodes"
    )
    assert objects_with_prefix("LD_WALL__wall_boundary_ab__seg"), (
        "the scar wall is missing in the after state"
    )


def test_camera_anchors_never_move(context) -> None:
    """The persistent camera anchors are identical across episode states."""
    cameras_after = transforms_of(("CAM_",))
    apply_render_export.apply_render_export_file(context["spec_path"], context["before_path"])
    cameras_before = transforms_of(("CAM_",))
    assert cameras_before == cameras_after, "camera anchors moved between episodes"
    apply_render_export.apply_render_export_file(context["spec_path"], context["after_path"])


def test_topology_disagreement_is_refused(context) -> None:
    """A boundary whose endpoints disagree with the spec is refused."""
    export = json.loads(context["after_path"].read_text(encoding="utf-8"))
    export["world"]["boundaries"][0]["district_a_id"] = "district_c"
    export["world"]["boundaries"][0]["district_b_id"] = "district_d"
    tampered = context["workdir"] / "tampered_topology.json"
    tampered.write_text(json.dumps(export), encoding="utf-8")
    try:
        apply_render_export.apply_render_export_file(context["spec_path"], tampered)
    except SceneContractError as error:
        assert "endpoints disagree" in str(error)
    else:
        raise AssertionError("swapped boundary endpoints were not refused")


def test_unknown_district_is_refused(context) -> None:
    """An exported district without a master definition is refused."""
    export = json.loads(context["after_path"].read_text(encoding="utf-8"))
    ghost = dict(export["world"]["districts"][0])
    ghost["id"] = "district_ghost"
    export["world"]["districts"].append(ghost)
    tampered = context["workdir"] / "tampered_district.json"
    tampered.write_text(json.dumps(export), encoding="utf-8")
    try:
        apply_render_export.apply_render_export_file(context["spec_path"], tampered)
    except SceneContractError as error:
        assert "district_ghost" in str(error)
    else:
        raise AssertionError("an unknown district was not refused")


def test_unknown_boundary_is_refused(context) -> None:
    """An exported boundary without a master definition is refused."""
    export = json.loads(context["after_path"].read_text(encoding="utf-8"))
    ghost = dict(export["world"]["boundaries"][0])
    ghost["id"] = "boundary_ghost"
    export["world"]["boundaries"].append(ghost)
    tampered = context["workdir"] / "tampered_boundary.json"
    tampered.write_text(json.dumps(export), encoding="utf-8")
    try:
        apply_render_export.apply_render_export_file(context["spec_path"], tampered)
    except SceneContractError as error:
        assert "boundary_ghost" in str(error)
    else:
        raise AssertionError("an unknown boundary was not refused")


def test_headless_render_produces_output(context) -> None:
    """A render can be generated headlessly from a persistent camera."""
    scene = bpy.context.scene
    output = context["workdir"] / "headless_probe.png"
    previous = (scene.cycles.samples, scene.render.resolution_x, scene.render.resolution_y)
    backend = render_visual_proof.render_frame("CAM_VERIFY_TOPOLOGY", output, preview=True)
    scene.cycles.samples, scene.render.resolution_x, scene.render.resolution_y = previous
    assert output.exists() and output.stat().st_size > 0, "headless render wrote nothing"
    assert backend in ("OPTIX", "CUDA", "CPU")
