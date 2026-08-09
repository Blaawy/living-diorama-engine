"""Produce the Phase 17 motion proof pack in one Blender session.

This is the MOTION FOUNDATION's evidence, not a finished film. It builds the
persistent city, animates one real state transition, renders the declared
sample frames from a single fixed camera, assembles a contact sheet so the
transition can be judged as a sequence, renders a semantic verification frame,
and writes a manifest of measured facts.

One camera, deliberately. Phase 17 owns TIME, not shot grammar: every sample
frame comes from the same existing Phase 16 anchor, so any difference between
two frames is the world changing rather than the camera moving.

Usage::

    blender --background --factory-startup --python produce_motion_proof.py -- \
        --spec S --production P --motion M --before A.json --after B.json \
        --outdir DIR --blend OUT.blend [--profile transition|persistence] \
        [--label phase17] [--base-sha SHA] [--preview]

Both profiles save their animated ``.blend`` INTO the proof directory: a
manifest that records a hash for an artifact the package does not carry is a
dangling reference, and the package inventory refuses it.
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

import apply_motion_plan as motion  # noqa: E402
import render_visual_proof  # noqa: E402
from manifest_io import write_manifest_json  # noqa: E402
from motion_plan import canonical_plan_bytes, plan_hash  # noqa: E402

PROOF_STYLE = "dna"

PROFILES = {
    "transition": {
        "camera": "CAM_P16_SCAR_CONTEXT",
        "world_camera": "CAM_P16_WORLD_HERO",
        "contact_sheet": True,
        "semantic_verify": True,
        "manifest": "motion_manifest.json",
    },
    "persistence": {
        "camera": "CAM_SEAL_DETAIL",
        "world_camera": "",
        "contact_sheet": False,
        "semantic_verify": False,
        "manifest": "motion_persistence_manifest.json",
    },
}
"""Two ways to look at one motion system.

``transition`` watches the scar in its city, close enough to read the wall
rising and the conduits anchoring into it, wide enough to prove the city
around them never moves. ``persistence`` watches the Golden Seal alone while
the law returns, which is the frame where THE WORLD REMEMBERS is either true
or it is not: the law's indication comes back, and the wall does not leave."""

SHEET_COLUMNS = 3
SHEET_SINGLE_ROW_LIMIT = 6
"""Up to six samples read best as one left-to-right film strip, which is what
a transition actually is; beyond that the sheet wraps into rows."""

VERIFY_EXPOSURE_STOPS = 3.0
"""The semantic verification frame hides the entire lit city, so the bounce
light that normally shapes these materials is gone with it. The frame is a
DIAGNOSTIC, not a look: it is exposed up so the animated objects are legible,
and the manifest records by how much."""


def sha256_of(path: Path) -> str:
    """SHA-256 of one file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_rgb(path: Path) -> numpy.ndarray:
    """Load an image as HxWx3 float RGB (top row first)."""
    image = bpy.data.images.load(str(path))
    width, height = image.size
    pixels = numpy.array(image.pixels[:], dtype=numpy.float32).reshape(height, width, 4)
    bpy.data.images.remove(image)
    return pixels[::-1, :, :3]


def resize(rgb: numpy.ndarray, width: int, height: int) -> numpy.ndarray:
    """Nearest-neighbour downscale (adequate for a contact sheet)."""
    source_height, source_width, _ = rgb.shape
    ys = (numpy.arange(height) * source_height // height).clip(0, source_height - 1)
    xs = (numpy.arange(width) * source_width // width).clip(0, source_width - 1)
    return rgb[ys][:, xs]


def save_rgb(path: Path, rgb: numpy.ndarray) -> None:
    """Write one float RGB array as an 8-bit PNG."""
    height, width, _ = rgb.shape
    image = bpy.data.images.new(path.stem, width=width, height=height, alpha=False)
    rgba = numpy.dstack([rgb[::-1, :, :], numpy.ones((height, width, 1), dtype=numpy.float32)])
    image.pixels = rgba.ravel()
    image.file_format = "PNG"
    image.filepath_raw = str(path)
    image.save()
    bpy.data.images.remove(image)


def compose_contact_sheet(outdir: Path, frames: list[str], target: Path) -> None:
    """Lay every sample frame out in reading order, one PNG.

    The sheet is the point of the proof pack: five stills of the same camera,
    in time order, is the shortest honest way to show that a transition exists
    and that only the intended things travelled through it.
    """
    tiles = [resize(load_rgb(outdir / name), 640, 360) for name in frames]
    columns = len(tiles) if len(tiles) <= SHEET_SINGLE_ROW_LIMIT else SHEET_COLUMNS
    while len(tiles) % columns:
        tiles.append(numpy.zeros_like(tiles[0]))
    rows = [numpy.hstack(tiles[index : index + columns]) for index in range(0, len(tiles), columns)]
    save_rgb(target, numpy.vstack(rows))


def render_semantic_verification(report: dict, outdir: Path, camera: str, preview: bool) -> dict:
    """Render the mid-transition frame with the STATIC city hidden.

    Everything the plan did not authorise disappears, so the remaining image
    is exactly the set of objects Phase 17 is animating, caught halfway. If
    anything unauthorised were moving, it would not be in this frame at all.
    """
    authorised = set(report["metrics"]["animated_object_names"])
    hidden = []
    for obj in bpy.data.objects:
        if obj.type == "CAMERA" or obj.name in authorised:
            continue
        if not obj.name.startswith(("LD_", "CAM_")) or obj.hide_render:
            continue
        obj.hide_render = True
        hidden.append(obj)
    timeline = report["plan"]["timeline"]
    frame = (timeline["transition_start"] + timeline["transition_end"]) // 2
    scene = bpy.context.scene
    scene.frame_set(frame)
    exposure = scene.view_settings.exposure
    scene.view_settings.exposure = exposure + VERIFY_EXPOSURE_STOPS
    try:
        started = time.perf_counter()
        backend = render_visual_proof.render_frame(
            camera, outdir / "phase17_semantic_motion_verify.png", preview=preview
        )
        return {
            "file": "phase17_semantic_motion_verify.png",
            "camera": camera,
            "frame": frame,
            "animated_objects_shown": len(authorised),
            "exposure_stops_added": VERIFY_EXPOSURE_STOPS,
            "backend": backend,
            "seconds": round(time.perf_counter() - started, 1),
        }
    finally:
        scene.view_settings.exposure = exposure
        for obj in hidden:
            obj.hide_render = False


def scene_complexity() -> dict:
    """Object and triangle counts of the animated scene, as built."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    triangles = 0
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.hide_render:
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        triangles += len(mesh.loop_triangles)
        evaluated.to_mesh_clear()
    return {
        "objects": len(bpy.data.objects),
        "mesh_objects": len([o for o in bpy.data.objects if o.type == "MESH"]),
        "lights": len([o for o in bpy.data.objects if o.type == "LIGHT"]),
        "cameras": len([o for o in bpy.data.objects if o.type == "CAMERA"]),
        "ld_materials": len([m for m in bpy.data.materials if m.name.startswith("LD_MAT__")]),
        "triangles": triangles,
    }


def render_samples(
    report: dict, outdir: Path, prefix: str, camera: str, preview: bool
) -> list[dict]:
    """Render every declared proof sample from the one fixed camera."""
    rendered = []
    for sample in report["motion_spec"]["proof_samples"]:
        bpy.context.scene.frame_set(sample["frame"])
        name = f"{prefix}_{sample['name']}.png"
        started = time.perf_counter()
        backend = render_visual_proof.render_frame(camera, outdir / name, preview=preview)
        rendered.append(
            {
                "file": name,
                "camera": camera,
                "frame": sample["frame"],
                "position": sample["position"],
                "backend": backend,
                "seconds": round(time.perf_counter() - started, 1),
            }
        )
    return rendered


def render_world_pair(
    report: dict, outdir: Path, prefix: str, camera: str, preview: bool
) -> list[dict]:
    """Render the two endpoints at city scale, for context."""
    timeline = report["plan"]["timeline"]
    rendered = []
    endpoints = (("world_start", timeline["start_frame"]), ("world_end", timeline["end_frame"]))
    for label, frame in endpoints:
        bpy.context.scene.frame_set(frame)
        name = f"{prefix}_{label}.png"
        started = time.perf_counter()
        backend = render_visual_proof.render_frame(camera, outdir / name, preview=preview)
        rendered.append(
            {
                "file": name,
                "camera": camera,
                "frame": frame,
                "backend": backend,
                "seconds": round(time.perf_counter() - started, 1),
            }
        )
    return rendered


def endpoint_equivalence(report: dict) -> dict:
    """Re-prove both endpoints at manifest time, geometry AND materials.

    Delegates to the one shared implementation in :mod:`apply_motion_plan`, so
    the verdict recorded in the manifest is produced by exactly the same code
    the structural tests assert on.
    """
    return motion.endpoint_equivalence(
        report["scene"],
        report["geography"],
        report["scene"]["master_spec"],
        report["plan"]["timeline"],
    )


def geography_invariance(report: dict) -> dict:
    """Re-prove the persistent city is fixed on every declared sample frame."""
    pinned = {name: state for name, *state in report["geography"]}
    frames = [sample["frame"] for sample in report["motion_spec"]["proof_samples"]]
    moved = []
    for frame in frames:
        current = {name: state for name, *state in motion.scene_state_at(frame)}
        moved.extend(name for name, state in pinned.items() if current.get(name) != state)
    return {
        "pinned_objects": len(pinned),
        "frames_checked": frames,
        "objects_that_moved": sorted(set(moved)),
        "invariant": not moved,
    }


def write_motion_manifest(
    arguments: argparse.Namespace,
    profile: dict,
    report: dict,
    outdir: Path,
    renders: list[dict],
    verification: dict,
    blend_path: Path,
    elapsed: float,
) -> Path:
    """Write the Phase 17 manifest: measured facts only, never claims."""
    plan = report["plan"]
    metrics = report["metrics"]
    manifest = {
        "artifact": "living_diorama_phase17_motion_time_proof",
        "label": arguments.label,
        "profile": arguments.profile,
        "cameras": {
            "sample": profile["camera"],
            "world": profile["world_camera"] or None,
        },
        "blender_version": bpy.app.version_string,
        "style_profile": PROOF_STYLE,
        "canonical_base_sha": arguments.base_sha,
        "motion_spec": {
            "path": Path(arguments.motion).name,
            "sha256": sha256_of(Path(arguments.motion)),
            "schema_version": plan["schema_version"],
            "timeline": plan["timeline"],
            "channels_declared": sorted(report["motion_spec"]["channels"]),
            "proof_samples": [dict(sample) for sample in report["motion_spec"]["proof_samples"]],
        },
        "exports": {
            "before": {
                "path": Path(arguments.before).name,
                "sha256": sha256_of(Path(arguments.before)),
                **plan["before"],
            },
            "after": {
                "path": Path(arguments.after).name,
                "sha256": sha256_of(Path(arguments.after)),
                **plan["after"],
            },
        },
        "motion_plan": {
            "sha256": plan_hash(plan),
            "bytes": len(canonical_plan_bytes(plan)),
            "directive_count": plan["summary"]["directive_count"],
            "directives_by_channel": plan["summary"]["by_channel"],
            "animated_channels": plan["summary"]["animated_channels"],
            "animated_semantic_ids": plan["summary"]["animated_semantic_ids"],
        },
        "union_scene": report["union"],
        "motion_metrics": {
            "animated_objects": metrics["animated_objects"],
            "animated_materials": metrics["animated_materials"],
            "fcurves": metrics["fcurves"],
            "keyframes": metrics["keyframes"],
            "actions": metrics["actions"],
            "animated_object_names": metrics["animated_object_names"],
        },
        "endpoint_equivalence": endpoint_equivalence(report),
        "static_geography_invariance": geography_invariance(report),
        "production_world": report["production"],
        "scene": scene_complexity(),
        "renders": renders,
        "semantic_verification": verification,
        "blend": {
            "path": blend_path.name,
            "sha256": sha256_of(blend_path),
            "bytes": blend_path.stat().st_size,
        },
        "total_seconds": round(elapsed, 1),
    }
    target = outdir / profile["manifest"]
    write_manifest_json(target, manifest)
    return target


def main() -> int:
    """Build the animated world, render the proof, and write the manifest."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--production", required=True)
    parser.add_argument("--motion", required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--blend", required=True)
    parser.add_argument("--label", default="phase17")
    parser.add_argument("--profile", default="transition", choices=sorted(PROFILES))
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--preview", action="store_true")
    arguments = parser.parse_args(argv)

    started = time.perf_counter()
    profile = PROFILES[arguments.profile]
    outdir = Path(arguments.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    report = motion.build_motion_scene(
        arguments.spec,
        arguments.production,
        arguments.before,
        arguments.after,
        arguments.motion,
        style=PROOF_STYLE,
    )
    if not report["plan"]["directives"]:
        print("motion proof failed: the two exports describe no visual change", file=sys.stderr)
        return 1

    blend_path = Path(arguments.blend)
    blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.frame_set(report["plan"]["timeline"]["start_frame"])
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path.resolve()))

    renders = render_samples(report, outdir, arguments.label, profile["camera"], arguments.preview)
    if profile["world_camera"]:
        renders.extend(
            render_world_pair(
                report, outdir, arguments.label, profile["world_camera"], arguments.preview
            )
        )
    if profile["contact_sheet"]:
        compose_contact_sheet(
            outdir,
            [
                f"{arguments.label}_{sample['name']}.png"
                for sample in report["motion_spec"]["proof_samples"]
            ],
            outdir / "phase17_motion_contact_sheet.png",
        )
    verification = (
        render_semantic_verification(report, outdir, profile["camera"], arguments.preview)
        if profile["semantic_verify"]
        else {}
    )

    manifest = write_motion_manifest(
        arguments,
        profile,
        report,
        outdir,
        renders,
        verification,
        blend_path,
        time.perf_counter() - started,
    )
    document = json.loads(manifest.read_text(encoding="utf-8"))
    for which, endpoint in sorted(document["endpoint_equivalence"].items()):
        if not (
            endpoint["objects_equivalent"]
            and endpoint["materials_equivalent"]
            and endpoint["equivalent"]
        ):
            print(
                f"motion proof failed: the {which} endpoint is not the static world "
                f"(objects={endpoint['objects_equivalent']}, "
                f"materials={endpoint['materials_equivalent']}, "
                f"mismatches={endpoint['material_mismatches']})",
                file=sys.stderr,
            )
            return 1
    if not document["static_geography_invariance"]["invariant"]:
        print("motion proof failed: the persistent city moved", file=sys.stderr)
        return 1
    print(
        f"LD_MOTION_PROOF: {document['motion_plan']['directive_count']} directives, "
        f"{document['motion_metrics']['fcurves']} F-curves, "
        f"{document['motion_metrics']['keyframes']} keyframes, "
        f"materials equivalent at both endpoints"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
