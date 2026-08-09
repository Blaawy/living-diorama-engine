"""Produce the Phase 16 production-world proof pack in one Blender session.

Sequence: build the persistent founding world under the accepted Visual DNA
profile, create the Phase 16 camera anchors, apply the REAL persistent
episode state (the after-export: wall standing, law restored), render the
before-expansion reference from the production hero camera, then add the
production city and render every required proof frame from the same
anchors. The before frame is a PRESENTATION-SCALE comparison -- the same
authoritative world state at founding resolution -- never a fabricated
simulation event.

Usage::

    blender --background --factory-startup --python \
        produce_production_world_proof.py -- --spec S --production P \
        --export AFTER.json --outdir DIR --blend OUT.blend [--preview] \
        [--baselines BASELINES.json]
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import bpy
import numpy

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply_render_export  # noqa: E402
import build_master_scene  # noqa: E402
import build_production_world  # noqa: E402
import render_visual_proof  # noqa: E402
from manifest_io import write_manifest_json  # noqa: E402
from production_spec import load_production_world_spec  # noqa: E402
from road_graph import build_road_graph, graph_summary  # noqa: E402
from scene_spec import load_master_scene_spec  # noqa: E402
from style_profiles import resolve_style  # noqa: E402
from urban_fabric import fabric_totals, plan_urban_fabric  # noqa: E402

PROOF_STYLE = "dna"
HERO_CAMERA = "CAM_P16_WORLD_HERO"

FRAMES: tuple[tuple[str, str], ...] = (
    ("phase16_world_hero.png", HERO_CAMERA),
    ("phase16_system_view.png", "CAM_P16_SYSTEM"),
    ("phase16_city_composition_verify.png", "CAM_P16_COMPOSITION"),
    ("phase16_historic_core_context.png", "CAM_P16_CORE_CONTEXT"),
    ("phase16_scar_context.png", "CAM_P16_SCAR_CONTEXT"),
    ("phase16_road_network_verify.png", "CAM_P16_ROADS"),
    ("phase16_density_verify.png", "CAM_P16_DENSITY"),
    ("phase16_spatial_validity_verify.png", "CAM_P16_VALIDITY"),
    ("phase16_urbanization_verify.png", "CAM_P16_URBAN"),
)

COMPOSITION_CAMERA = "CAM_P16_COMPOSITION"

COMPARISON_FRAMES = (
    ("phase16_before_composition_reference.png", "phase16_city_composition_verify.png"),
)
"""Left/right pairs of the composition comparison sheet: the SAME camera
on the pre-composition world and on the final one."""

SHEET_FRAMES = (
    "phase16_world_hero.png",
    "phase16_city_composition_verify.png",
    "phase16_clean_roads_verify.png",
    "phase16_scar_context.png",
)

CLEAN_ROADS_HIDDEN_PREFIXES = (
    "LD_BLDG__",
    "LD_TREE__",
    "LD_P16_BLDG__",
    "LD_P16_GREEN__",
    "LD_P16_YARD__",
    "LD_P16_FLOOD__",
    "LD_P16_PLAZA__",
    "LD_P16_GROUND__",
)
"""Hidden for the clean-roads frame: all buildings and landscaping, so the
street network itself can be judged as a plan -- the road beauty test."""


def render_clean_roads(outdir: Path, preview: bool) -> dict[str, object]:
    """Render the street network alone from the top-down verify camera."""
    hidden: list[bpy.types.Object] = []
    for obj in bpy.data.objects:
        if obj.name.startswith(CLEAN_ROADS_HIDDEN_PREFIXES) and not obj.hide_render:
            obj.hide_render = True
            hidden.append(obj)
    try:
        started = time.perf_counter()
        backend = render_visual_proof.render_frame(
            "CAM_P16_ROADS", outdir / "phase16_clean_roads_verify.png", preview=preview
        )
        return {
            "file": "phase16_clean_roads_verify.png",
            "camera": "CAM_P16_ROADS",
            "backend": backend,
            "seconds": round(time.perf_counter() - started, 1),
        }
    finally:
        for obj in hidden:
            obj.hide_render = False


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


def compose_small_screen_sheet(outdir: Path) -> None:
    """640x360 and 426x240 rows of the identity frames, one PNG."""
    tiles = [load_rgb(outdir / name) for name in SHEET_FRAMES]
    rows = []
    for width, height in ((640, 360), (426, 240)):
        scaled = [resize(tile, width, height) for tile in tiles]
        pad = 8
        row = numpy.zeros((height + pad, (width + pad) * len(scaled), 3), numpy.float32)
        for index, tile in enumerate(scaled):
            row[:height, index * (width + pad) : index * (width + pad) + width] = tile
        rows.append(row)
    width = max(row.shape[1] for row in rows)
    padded = []
    for row in rows:
        canvas = numpy.zeros((row.shape[0], width, 3), numpy.float32)
        canvas[:, : row.shape[1]] = row
        padded.append(canvas)
    sheet = numpy.concatenate(padded, axis=0)
    height, width, _ = sheet.shape
    image = bpy.data.images.new("p16_sheet", width=width, height=height, alpha=False)
    rgba = numpy.concatenate([sheet[::-1], numpy.ones((height, width, 1), numpy.float32)], axis=2)
    image.pixels = rgba.ravel().tolist()
    image.filepath_raw = str(outdir / "phase16_small_screen_sheet.png")
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)


def compose_comparison_sheet(outdir: Path) -> None:
    """A side-by-side sheet: pre-composition world vs final composition.

    Presentation quality only -- both halves are the SAME authoritative
    episode state from the SAME camera. What differs is the urban
    composition: the circular district plates, the western arc, the
    mid-rise shoulder, and the continuity of the city floor.
    """
    rows = []
    for before_name, after_name in COMPARISON_FRAMES:
        before_path = outdir / before_name
        after_path = outdir / after_name
        if not before_path.exists() or not after_path.exists():
            continue
        tiles = [resize(load_rgb(path), 960, 540) for path in (before_path, after_path)]
        pad = 10
        row = numpy.zeros((540 + pad, (960 + pad) * 2, 3), numpy.float32)
        for index, tile in enumerate(tiles):
            row[:540, index * (960 + pad) : index * (960 + pad) + 960] = tile
        rows.append(row)
    if not rows:
        return
    sheet = numpy.concatenate(rows, axis=0)
    height, width, _ = sheet.shape
    image = bpy.data.images.new("p16_comparison", width=width, height=height, alpha=False)
    rgba = numpy.concatenate([sheet[::-1], numpy.ones((height, width, 1), numpy.float32)], axis=2)
    image.pixels = rgba.ravel().tolist()
    image.filepath_raw = str(outdir / "phase16_composition_comparison.png")
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)


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
        "mesh_triangles_pre_modifier": triangles,
    }


def write_p16_manifest(
    arguments: argparse.Namespace,
    outdir: Path,
    blend_path: Path,
    frames: list[dict[str, object]],
    street_stats: dict,
    fabric_stats: dict,
    spatial_stats: dict,
    ground_stats: dict,
) -> Path:
    """Assemble and write the proof manifest as plain UTF-8 JSON (no BOM)."""
    master_spec = json.loads(Path(arguments.spec).read_text(encoding="utf-8"))
    production_spec = json.loads(Path(arguments.production).read_text(encoding="utf-8"))
    settings = resolve_style(PROOF_STYLE)["settings"]
    cameras: dict[str, dict] = {}
    for source in (master_spec["cameras"], production_spec["cameras"]):
        for name, definition in source.items():
            cameras[name] = {
                "location": list(definition["location"]),
                "look_at": list(definition["look_at"]),
                "lens_mm": definition["lens_mm"],
                "f_stop": definition.get("f_stop"),
            }
    document: dict[str, object] = {
        "artifact": "living_diorama_phase16_production_world_proof",
        "version": 1,
        "identity": "Living Diorama - Production World Scale & Urban Fabric Foundation",
        "style_profile": "dna (visual/blender/scripts/style_profiles.py)",
        "blender_version": f"Blender {bpy.app.version_string}",
        "render_engine": "CYCLES",
        "backend": str(frames[0]["backend"]) if frames else "UNKNOWN",
        "resolution": "1280x720 preview" if arguments.preview else "2560x1440",
        "sampling": {
            "max_samples": 96 if arguments.preview else 1024,
            "adaptive_threshold": 0.08 if arguments.preview else 0.015,
            "denoiser": "OPENIMAGEDENOISE",
        },
        "color_management": {
            "view_transform": "AgX",
            "look": settings["look"],
            "exposure": settings["exposure"],
        },
        "comparison": {
            "camera": HERO_CAMERA,
            "note": (
                "phase16_before_expansion_reference and phase16_world_hero share "
                "this camera; both show the SAME authoritative episode state -- "
                "the difference is presentation resolution, not simulation history"
            ),
        },
        "cameras": cameras,
        "render_export": {
            "after": {
                "file": Path(arguments.export).name,
                "sha256": sha256_of(Path(arguments.export)),
            }
        },
        "street_network": street_stats,
        "urban_fabric": fabric_stats,
        "spatial_validity": spatial_stats,
        "city_composition": ground_stats,
        "urbanization": {
            "legacy_clusters_removed": fabric_stats["legacy_clusters_removed"],
            "legacy_clusters_preserved": fabric_stats["legacy_clusters_kept"],
            "legacy_trees_removed": fabric_stats["legacy_trees_removed"],
            "legacy_trees_preserved": fabric_stats["legacy_trees_kept"],
            "legacy_buildings_suppressed": 0,
            "new_production_trees": fabric_stats["production_trees"],
            "street_trees": fabric_stats["street_trees"],
            "park_groups": fabric_stats["park_groups"],
            "promenade_trees": fabric_stats["promenade_trees"],
            "total_masses": fabric_stats["masses"],
            "midrise_masses": fabric_stats["midrise_masses"],
            "lowrise_masses": fabric_stats["lowrise_masses"],
            "industrial_masses": fabric_stats["industrial_masses"],
            "production_street_length": street_stats["production_street_length"],
            "intersections": street_stats["intersections"],
            "park_zones": len(production_spec["landscape"]["park_zones"]),
        },
        "scene_complexity": scene_complexity(),
        "render_times_seconds": frames,
        "file_sha256": {
            entry.name: sha256_of(entry)
            for entry in sorted(outdir.iterdir())
            if entry.suffix == ".png"
        },
    }
    if blend_path.exists():
        hashes = document["file_sha256"]
        assert isinstance(hashes, dict)
        hashes[blend_path.name] = sha256_of(blend_path)
    if arguments.baselines:
        baselines = json.loads(Path(arguments.baselines).read_text(encoding="utf-8"))
        document.update(baselines)
    manifest_path = outdir / "phase16_production_world_manifest.json"
    write_manifest_json(manifest_path, document)
    return manifest_path


def main() -> int:
    """Build the production world, render the proof pack, save the .blend."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--production", required=True)
    parser.add_argument("--export", required=True, help="the persistent after-state export")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--blend", required=True)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument(
        "--baselines",
        default="",
        help="optional JSON file of external baseline identifiers merged into the manifest",
    )
    arguments = parser.parse_args(argv)
    outdir = Path(arguments.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    preview = arguments.preview

    build_master_scene.build_master_scene(arguments.spec, style=PROOF_STYLE)
    production_spec = load_production_world_spec(arguments.production)
    build_production_world.build_production_cameras(production_spec)
    apply_render_export.apply_render_export_file(
        arguments.spec, arguments.export, style=PROOF_STYLE
    )

    frames: list[dict[str, object]] = []
    for filename, camera in (
        ("phase16_before_expansion_reference.png", HERO_CAMERA),
        ("phase16_before_composition_reference.png", COMPOSITION_CAMERA),
    ):
        started = time.perf_counter()
        backend = render_visual_proof.render_frame(camera, outdir / filename, preview=preview)
        frames.append(
            {
                "file": filename,
                "camera": camera,
                "backend": backend,
                "seconds": round(time.perf_counter() - started, 1),
            }
        )

    build_production_world.add_production_world(
        arguments.spec, arguments.production, style=PROOF_STYLE
    )
    for filename, camera in FRAMES:
        started = time.perf_counter()
        backend = render_visual_proof.render_frame(camera, outdir / filename, preview=preview)
        frames.append(
            {
                "file": filename,
                "camera": camera,
                "backend": backend,
                "seconds": round(time.perf_counter() - started, 1),
            }
        )
    frames.append(render_clean_roads(outdir, preview))

    compose_small_screen_sheet(outdir)
    compose_comparison_sheet(outdir)

    blend_path = Path(arguments.blend).resolve()
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    master_spec = load_master_scene_spec(arguments.spec)
    graph = build_road_graph(master_spec, production_spec)
    plan = plan_urban_fabric(master_spec, production_spec, graph)
    (outdir / "p16_render_report.json").write_text(
        json.dumps({"frames": frames}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest_path = write_p16_manifest(
        arguments,
        outdir,
        blend_path,
        frames,
        graph_summary(graph),
        fabric_totals(plan),
        plan["spatial"],
        {
            **plan["ground"]["summary"],
            "blocks": plan["blocks"],
            "plates": {
                district_id: {
                    "ring": plate["ring"],
                    "rim_exposure_deg": plate["rim_exposure_deg"],
                    "kept_arcs": len(plate["kept_arcs"]),
                    "buried_arcs": len(plate["buried_arcs"]),
                    "panels": len(plate["pieces"]),
                }
                for district_id, plate in sorted(plan["ground"]["plates"].items())
            },
        },
    )
    print(f"LD_P16_MANIFEST: {manifest_path}")
    print("LD_P16_PROOF: complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
