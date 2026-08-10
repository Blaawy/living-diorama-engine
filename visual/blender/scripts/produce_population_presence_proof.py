"""Produce the Phase 18 population presence proof package.

Builds the canonical city once, renders the world WITHOUT the population layer,
then applies the presence plan and renders the same camera again plus the
context frames. The before/after pair is therefore one city, one camera, one
authoritative episode -- the only thing that changes between the two frames is
whether its people are standing in it.

Run headless::

    blender --background --factory-startup --python \
        produce_population_presence_proof.py -- --spec master_scene_v1.json \
        --production production_world_v1.json --presence population_presence_v1.json \
        --export render_export_before.json --outdir proof/ --blend proof/world.blend

Every frame, the manifest, and the ``.blend`` land in one flat directory that
:mod:`population_proof_package` then inventories.
"""

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

import bpy
import numpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply_population_presence as population  # noqa: E402
import apply_render_export  # noqa: E402
import build_master_scene  # noqa: E402
import build_production_world  # noqa: E402
import pedestrian_topology as topology  # noqa: E402
import population_presence_plan as presence_plan  # noqa: E402
from blender_runtime import link_only, look_at_rotation, replace_object  # noqa: E402
from manifest_io import write_manifest_json  # noqa: E402
from population_presence_spec import (  # noqa: E402
    REQUIRED_PRESENCE_CAMERAS,
    load_population_presence_spec,
)
from production_spec import load_production_world_spec  # noqa: E402
from render_visual_proof import render_frame  # noqa: E402
from road_graph import build_road_graph  # noqa: E402
from scene_spec import load_master_scene_spec  # noqa: E402
from urban_fabric import plan_urban_fabric  # noqa: E402

MANIFEST_NAME = "population_presence_manifest.json"
CONTACT_SHEET = "phase18_population_contact_sheet.png"

PROOF_STYLE = "dna"
"""The reviewed visual identity. Phase 18 changes who is in the world, never
what the world looks like, so it renders under exactly the style Phase 15
locked and Phase 16 and Phase 17 have used since."""

COMPARISON_PAIRS = (
    (
        "phase18_world_before_population_reference.png",
        "phase18_world_with_population.png",
        "CAM_P18_WORLD",
    ),
    (
        "phase18_quarter_before_population_reference.png",
        "phase18_quarter_with_population.png",
        "CAM_P18_QUARTER",
    ),
)
"""The before/after evidence: (reference, populated, camera).

Each pair is ONE camera rendered twice -- before the population layer exists
and after it is built -- so a reviewer comparing them is comparing one
decision and not two pictures. Two scales, because they answer different
halves of the question: the world pair shows the city's identity and
geography are untouched, the quarter pair shows the difference at the scale a
person is actually legible.
"""

CONTEXT_FRAMES = (
    ("phase18_population_street_context.png", "CAM_P18_STREET"),
    ("phase18_population_plaza_context.png", "CAM_P18_PLAZA"),
    ("phase18_population_civic_context.png", "CAM_P18_CIVIC"),
    ("phase18_population_park_context.png", "CAM_P18_PARK"),
    ("phase18_population_group_context.png", "CAM_P18_GROUP"),
    ("phase18_population_validity_verify.png", "CAM_P18_VALIDITY"),
)
"""The approved area types, shown where they actually happen, plus the
overhead frame where a body standing in a carriageway would be unmissable."""

SHEET_FRAMES = (
    *(name for pair in COMPARISON_PAIRS for name in pair[:2]),
    *(name for name, _camera in CONTEXT_FRAMES),
)
"""Contact sheet order: both comparisons first, then the contexts."""


def build_presence_cameras(presence_spec: dict) -> None:
    """The Phase 18 camera anchors, replaced by name so rebuilds converge."""
    collection = bpy.data.collections["LD_CAMERAS"]
    for name, definition in sorted(presence_spec["proof"]["cameras"].items()):
        replace_object(name)
        camera_data = bpy.data.cameras.get(name)
        if camera_data is None:
            camera_data = bpy.data.cameras.new(name)
        camera_data.lens = definition["lens_mm"]
        camera_data.clip_end = 1200.0
        camera_data.dof.use_dof = False
        camera = bpy.data.objects.new(name, camera_data)
        camera.location = Vector(definition["location"])
        camera.rotation_euler = look_at_rotation(
            Vector(definition["location"]), Vector(definition["look_at"])
        )
        link_only(camera, collection)


def load_rgb(path: Path) -> numpy.ndarray:
    """Load an image as HxWx3 float RGB (top row first)."""
    image = bpy.data.images.load(str(path))
    width, height = image.size
    pixels = numpy.array(image.pixels[:], dtype=numpy.float32).reshape(height, width, 4)
    bpy.data.images.remove(image)
    return pixels[::-1, :, :3]


def resize(rgb: numpy.ndarray, width: int, height: int) -> numpy.ndarray:
    """Nearest-neighbour downscale (adequate for a readability diagnostic)."""
    source_height, source_width, _ = rgb.shape
    ys = (numpy.arange(height) * source_height // height).clip(0, source_height - 1)
    xs = (numpy.arange(width) * source_width // width).clip(0, source_width - 1)
    return rgb[ys][:, xs]


def compose_contact_sheet(outdir: Path) -> None:
    """Every proof frame on one page, before/after first."""
    tiles = [load_rgb(outdir / name) for name in SHEET_FRAMES if (outdir / name).exists()]
    if not tiles:
        return
    width, height, pad = 640, 360, 8
    columns = 2
    rows = (len(tiles) + columns - 1) // columns
    sheet = numpy.zeros(((height + pad) * rows, (width + pad) * columns, 3), numpy.float32)
    for index, tile in enumerate(tiles):
        row, column = divmod(index, columns)
        top, left = row * (height + pad), column * (width + pad)
        sheet[top : top + height, left : left + width] = resize(tile, width, height)
    total_height, total_width, _ = sheet.shape
    image = bpy.data.images.new("p18_sheet", width=total_width, height=total_height, alpha=False)
    rgba = numpy.concatenate(
        [sheet[::-1], numpy.ones((total_height, total_width, 1), numpy.float32)], axis=2
    )
    image.pixels = rgba.ravel().tolist()
    image.filepath_raw = str(outdir / CONTACT_SHEET)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)


def figure_diversity(plan: dict) -> dict:
    """What the population actually looks like, counted from the plan.

    Published so the Director's question -- are these different people? -- has
    a numeric answer beside the picture, and so a future regression that
    collapsed the crowd back onto one body would show up in the manifest
    rather than only in somebody's eye.
    """
    proxies = plan["proxies"]
    counts = {}
    for axis in (
        "age_presentation",
        "presentation",
        "stature",
        "build",
        "hair",
        "facial_hair",
        "clothing",
        "complexion",
        "pose",
    ):
        table: dict[str, int] = {}
        for proxy in proxies:
            table[proxy[axis]] = table.get(proxy[axis], 0) + 1
        counts[axis] = dict(sorted(table.items()))
    heights = sorted(float(proxy["height"]) for proxy in proxies)
    return {
        "by_axis": counts,
        "distinct_bodies": len({proxy["geometry_key"] for proxy in proxies}),
        "shortest": round(heights[0], 4) if heights else 0.0,
        "tallest": round(heights[-1], 4) if heights else 0.0,
        "representation_note": (
            "Visual presentation archetypes only. No proxy carries a demographic "
            "fact, and no relationship of any kind is recorded between any two of them."
        ),
    }


def sha256_of(path: Path) -> str:
    """SHA-256 hex digest of one file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scene_complexity() -> dict:
    """Object, material, and raw-triangle counts for the built scene."""
    triangles = 0
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        mesh = obj.data
        mesh.calc_loop_triangles()
        triangles += len(mesh.loop_triangles)
    return {
        "objects": len(bpy.data.objects),
        "ld_materials": sum(1 for m in bpy.data.materials if m.name.startswith("LD_MAT__")),
        "population_materials": sum(
            1 for m in bpy.data.materials if m.name.startswith(population.MATERIAL_PREFIX)
        ),
        "mesh_triangles_pre_modifier": triangles,
    }


def write_presence_manifest(
    outdir: Path,
    *,
    plan: dict,
    topology_plan: dict,
    metrics: dict,
    summary: dict,
    renders: list[dict],
    export_path: Path,
    blend_path: Path,
    base_sha: str,
    preview: bool,
) -> Path:
    """Write the one manifest describing this proof run.

    Deliberately carries no member list: it is written while the contact sheet
    is still being composed, so any list it produced would describe a package
    that was still being assembled. The package inventory records the package;
    this records the run.
    """
    document = {
        "artifact": "living_diorama_phase18_population_presence_proof",
        "schema_version": 1,
        "base_commit": base_sha,
        "preview": preview,
        "representation": plan["representation"],
        "source_export": {
            "path": export_path.name,
            "sha256": sha256_of(outdir / export_path.name),
            "bytes": (outdir / export_path.name).stat().st_size,
        },
        "plan_hash": presence_plan.plan_hash(plan),
        "density": plan["density"],
        "districts": plan["districts"],
        "presence_summary": plan["summary"],
        "topology": {
            "hash": topology.topology_hash(topology_plan),
            "candidates_by_zone": topology_plan["summary"]["candidates_by_zone"],
            "candidates_by_district": topology_plan["summary"]["candidates_by_district"],
            "candidates_tested": topology_plan["summary"]["candidates_tested"],
            "candidates_refused": topology_plan["summary"]["candidates_refused"],
            "refusals_by_reason": topology_plan["refused"],
        },
        "build_metrics": metrics,
        "scene_population": summary,
        "scene_complexity": scene_complexity(),
        "figure_diversity": figure_diversity(plan),
        "renders": renders,
        "blend": {
            "path": blend_path.name,
            "sha256": sha256_of(blend_path),
            "bytes": blend_path.stat().st_size,
        },
    }
    target = outdir / MANIFEST_NAME
    write_manifest_json(target, document)
    return target


def main() -> int:
    """Build the city, render before, populate it, render after, and report."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--production", required=True)
    parser.add_argument("--presence", required=True)
    parser.add_argument("--export", required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--blend", required=True)
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--preview", action="store_true")
    arguments = parser.parse_args(argv)

    outdir = Path(arguments.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    export_path = Path(arguments.export)
    blend_path = Path(arguments.blend)

    master_spec = load_master_scene_spec(arguments.spec)
    production = load_production_world_spec(arguments.production)
    presence_spec = load_population_presence_spec(arguments.presence)

    build_master_scene.build_master_scene(arguments.spec, style=PROOF_STYLE)
    apply_render_export.apply_render_export_file(
        arguments.spec, str(export_path), style=PROOF_STYLE
    )
    build_production_world.add_production_world(
        arguments.spec, arguments.production, style=PROOF_STYLE
    )
    build_presence_cameras(presence_spec)
    missing = [name for name in REQUIRED_PRESENCE_CAMERAS if bpy.data.objects.get(name) is None]
    if missing:
        raise RuntimeError(f"the proof cameras were not built: {missing}")

    graph = build_road_graph(master_spec, production)
    fabric = plan_urban_fabric(master_spec, production, graph)
    topology_plan = topology.plan_pedestrian_topology(
        master_spec, production, graph, fabric, presence_spec
    )
    errors = topology.validate_pedestrian_topology(
        topology_plan, master_spec, production, graph, fabric
    )
    if errors:
        raise RuntimeError("the pedestrian topology is invalid:\n- " + "\n- ".join(errors))

    export = json.loads(export_path.read_text(encoding="utf-8"))
    plan = presence_plan.plan_population_presence(export, master_spec, presence_spec, topology_plan)
    plan_errors = presence_plan.validate_population_presence_plan(
        plan, export, master_spec, presence_spec, topology_plan
    )
    if plan_errors:
        raise RuntimeError("the presence plan is invalid:\n- " + "\n- ".join(plan_errors))

    renders: list[dict] = []
    for reference_name, _populated_name, camera in COMPARISON_PAIRS:
        started = time.perf_counter()
        backend = render_frame(camera, outdir / reference_name, preview=arguments.preview)
        renders.append(
            {
                "file": reference_name,
                "camera": camera,
                "population": False,
                "backend": backend,
                "seconds": round(time.perf_counter() - started, 1),
            }
        )

    metrics = population.apply_population_presence(plan, presence_spec)
    summary = population.population_summary()
    if summary["duplicate_named_objects"]:
        raise RuntimeError("the population layer produced duplicate-named datablocks")
    if summary["proxy_objects"] != plan["summary"]["active_proxies"]:
        raise RuntimeError(
            f"the scene holds {summary['proxy_objects']} proxies but the plan declares "
            f"{plan['summary']['active_proxies']}"
        )

    populated = [
        (populated_name, camera) for _reference, populated_name, camera in COMPARISON_PAIRS
    ]
    for name, camera in (*populated, *CONTEXT_FRAMES):
        started = time.perf_counter()
        backend = render_frame(camera, outdir / name, preview=arguments.preview)
        renders.append(
            {
                "file": name,
                "camera": camera,
                "population": True,
                "backend": backend,
                "seconds": round(time.perf_counter() - started, 1),
            }
        )

    # The export goes INTO the package. It is the authoritative input the
    # whole population claim rests on, so a reviewer has to be able to
    # recompute the plan from what was delivered rather than take the
    # manifest's word for a file that lives somewhere else.
    shutil.copyfile(export_path, outdir / export_path.name)
    blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path.resolve()))
    compose_contact_sheet(outdir)
    write_presence_manifest(
        outdir,
        plan=plan,
        topology_plan=topology_plan,
        metrics=metrics,
        summary=summary,
        renders=renders,
        export_path=export_path,
        blend_path=blend_path,
        base_sha=arguments.base_sha,
        preview=arguments.preview,
    )
    print(f"LD_P18_PROXIES: {summary['proxy_objects']}")
    print(f"LD_P18_MESHES: {summary['distinct_body_meshes']}")
    print(
        f"LD_P18_MESH_REUSE: {summary['reused_body_mesh_instances']} {summary['mesh_reuse_ratio']}"
    )
    print(f"LD_P18_TRIANGLES: {summary['population_triangles']}")
    print(f"LD_P18_PLAN_HASH: {metrics['plan_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
