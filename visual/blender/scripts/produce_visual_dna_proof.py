"""Produce the Phase 15 Visual DNA proof pack: one unified identity.

The Visual DNA is the synthesis of the bake-off: the world reads as an
extraordinary living civilization exhibit from macro views (C's backbone,
brightened and clarified with B's value discipline), and turns cinematic and
consequential at ground level (A's grammar). One Blender session builds the
persistent world under the ``dna`` style, applies the BEFORE export for the
comparison baseline, then the AFTER export for every identity frame, renders
the camera grammar (world/exhibit, system/structure, consequence/ground,
return/memory, seal, topology), composes the small-screen diagnostic sheet,
and saves the packed ``.blend``.

Usage::

    blender --background --factory-startup --python produce_visual_dna_proof.py \
        -- --spec S --before B.json --after A.json --outdir DIR --blend M.blend \
        [--preview]
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import bpy
import numpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply_render_export  # noqa: E402
import build_master_scene  # noqa: E402
import render_visual_proof  # noqa: E402
from blender_runtime import link_only, look_at_rotation, replace_object  # noqa: E402
from manifest_io import write_manifest_json  # noqa: E402
from style_profiles import resolve_style  # noqa: E402

DNA_STYLE = "dna"
COMPARISON_CAMERA = "CAM_HERO_WORLD"

DNA_CAMERAS: dict[str, dict] = {
    "CAM_DNA_WORLD_HERO": {
        "location": (118.0, -97.0, 67.0),
        "look_at": (-8.0, 4.0, -3.0),
        "lens_mm": 34.0,
        "f_stop": 5.6,
        "focus": (10.0, 0.0, 6.0),
    },
    "CAM_DNA_SYSTEM": {
        "location": (70.0, -70.0, 85.0),
        "look_at": (-6.0, 2.0, 0.0),
        "lens_mm": 40.0,
        "f_stop": 8.0,
        "focus": (0.0, 0.0, 2.0),
    },
    "CAM_DNA_RETURN": {
        "location": (-70.0, 40.0, 45.0),
        "look_at": (8.0, 0.0, 2.0),
        "lens_mm": 40.0,
        "f_stop": 8.0,
        "focus": (0.0, 4.0, 4.0),
    },
}

FRAMES_AFTER: list[tuple[str, str]] = [
    ("phase15_dna_after.png", COMPARISON_CAMERA),
    ("phase15_dna_world_hero.png", "CAM_DNA_WORLD_HERO"),
    ("phase15_dna_system_view.png", "CAM_DNA_SYSTEM"),
    ("phase15_dna_scar_detail.png", "CAM_HERO_SCAR"),
    ("phase15_dna_return_memory_view.png", "CAM_DNA_RETURN"),
    ("phase15_dna_golden_seal.png", "CAM_SEAL_DETAIL"),
    ("phase15_dna_topology_verify.png", "CAM_VERIFY_TOPOLOGY"),
]

SHEET_FRAMES = (
    "phase15_dna_world_hero.png",
    "phase15_dna_system_view.png",
    "phase15_dna_scar_detail.png",
    "phase15_dna_after.png",
)


def build_dna_cameras() -> None:
    """Create the DNA grammar cameras (persistent anchors stay untouched)."""
    collection = bpy.data.collections["LD_CAMERAS"]
    for name, definition in DNA_CAMERAS.items():
        replace_object(name)
        camera_data = bpy.data.cameras.get(name)
        if camera_data is None:
            camera_data = bpy.data.cameras.new(name)
        camera_data.lens = definition["lens_mm"]
        camera_data.clip_end = 1200.0
        location = Vector(definition["location"])
        focus = Vector(definition["focus"])
        camera_data.dof.use_dof = True
        camera_data.dof.focus_distance = (focus - location).length
        camera_data.dof.aperture_fstop = definition["f_stop"]
        camera = bpy.data.objects.new(name, camera_data)
        camera.location = location
        camera.rotation_euler = look_at_rotation(location, Vector(definition["look_at"]))
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


def compose_small_screen_sheet(outdir: Path) -> None:
    """640x360 and 426x240 rows of the identity frames, one PNG."""
    tiles = [load_rgb(outdir / name) for name in SHEET_FRAMES]
    rows = []
    for width, height in ((640, 360), (426, 240)):
        scaled = [resize(tile, width, height) for tile in tiles]
        pad = 8
        row_height = height + pad
        row = numpy.zeros((row_height, (width + pad) * len(scaled), 3), numpy.float32)
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
    image = bpy.data.images.new("dna_sheet", width=width, height=height, alpha=False)
    rgba = numpy.concatenate([sheet[::-1], numpy.ones((height, width, 1), numpy.float32)], axis=2)
    image.pixels = rgba.ravel().tolist()
    image.filepath_raw = str(outdir / "phase15_dna_small_screen_sheet.png")
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)


def sha256_of(path: Path) -> str:
    """SHA-256 hex digest of one file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_dna_manifest(
    arguments: argparse.Namespace,
    outdir: Path,
    blend_path: Path,
    frames: list[dict[str, object]],
) -> Path:
    """Assemble and write the proof manifest as plain UTF-8 JSON (no BOM).

    The manifest is produced by this pipeline itself -- cameras from the
    master spec and the DNA grammar, settings from the active profile, and
    SHA-256 of every produced artifact -- so external tooling never rewrites
    (or re-encodes) it after the fact.
    """
    spec = json.loads(Path(arguments.spec).read_text(encoding="utf-8"))
    settings = resolve_style(DNA_STYLE)["settings"]
    cameras: dict[str, dict] = {}
    for name, definition in spec["cameras"].items():
        cameras[name] = {
            "location": definition["location"],
            "look_at": definition["look_at"],
            "lens_mm": definition["lens_mm"],
            "f_stop": definition.get("f_stop"),
        }
    for name, definition in DNA_CAMERAS.items():
        cameras[name] = {
            "location": list(definition["location"]),
            "look_at": list(definition["look_at"]),
            "lens_mm": definition["lens_mm"],
            "f_stop": definition["f_stop"],
        }
    document: dict[str, object] = {
        "artifact": "living_diorama_phase15_visual_dna_proof",
        "version": 1,
        "identity": "Living Diorama - Macro-to-Monumental Visual DNA V1",
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
        "comparison_camera": {
            "name": COMPARISON_CAMERA,
            "note": "identical for phase15_dna_before and phase15_dna_after",
        },
        "cameras": cameras,
        "render_export": {
            "before": {
                "file": Path(arguments.before).name,
                "sha256": sha256_of(Path(arguments.before)),
            },
            "after": {
                "file": Path(arguments.after).name,
                "sha256": sha256_of(Path(arguments.after)),
            },
        },
        "render_times_seconds": frames,
        "file_sha256": {
            entry.name: sha256_of(entry)
            for entry in sorted(outdir.iterdir())
            if entry.suffix == ".png"
        },
    }
    if blend_path.exists():
        file_hashes = document["file_sha256"]
        assert isinstance(file_hashes, dict)
        file_hashes[blend_path.name] = sha256_of(blend_path)
    if arguments.baselines:
        baselines = json.loads(Path(arguments.baselines).read_text(encoding="utf-8"))
        document.update(baselines)
    manifest_path = outdir / "phase15_visual_dna_manifest.json"
    write_manifest_json(manifest_path, document)
    return manifest_path


def main() -> int:
    """Build the DNA world, render the identity frames, save the .blend."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
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

    build_master_scene.build_master_scene(arguments.spec, style=DNA_STYLE)
    build_dna_cameras()
    frames: list[dict[str, object]] = []

    apply_render_export.apply_render_export_file(arguments.spec, arguments.before, style=DNA_STYLE)
    started = time.perf_counter()
    backend = render_visual_proof.render_frame(
        COMPARISON_CAMERA, outdir / "phase15_dna_before.png", preview=preview
    )
    frames.append(
        {
            "file": "phase15_dna_before.png",
            "camera": COMPARISON_CAMERA,
            "backend": backend,
            "seconds": round(time.perf_counter() - started, 1),
        }
    )

    apply_render_export.apply_render_export_file(arguments.spec, arguments.after, style=DNA_STYLE)
    for filename, camera in FRAMES_AFTER:
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

    compose_small_screen_sheet(outdir)

    blend_path = Path(arguments.blend).resolve()
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    (outdir / "dna_render_report.json").write_text(
        json.dumps({"frames": frames}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest_path = write_dna_manifest(arguments, outdir, blend_path, frames)
    print(f"LD_VISUAL_DNA_MANIFEST: {manifest_path}")
    print("LD_VISUAL_DNA: complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
