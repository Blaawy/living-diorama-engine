"""Produce the Phase 15 visual proof pack in one Blender session.

Builds the persistent master scene, applies the BEFORE export and renders the
baseline comparison frame, then applies the AFTER export and renders the
matching after frame (same comparison camera), the dedicated cinematic hero
scar frame, the scar detail, the Golden Seal detail, and the topology
verification frame. Finally saves the generated master ``.blend`` (after
state, resources packed). Geography, cameras, and lighting are identical
across both states by construction -- only the episode layer differs.

Usage::

    blender --background --factory-startup --python produce_visual_proof.py -- \
        --spec S --before B.json --after A.json --outdir DIR --blend M.blend \
        [--preview]
"""

import argparse
import json
import sys
import time
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply_render_export  # noqa: E402
import build_master_scene  # noqa: E402
import render_visual_proof  # noqa: E402


def timed_render(camera: str, output: Path, *, preview: bool) -> dict[str, object]:
    """Render one frame and return its report entry."""
    started = time.perf_counter()
    backend = render_visual_proof.render_frame(camera, output, preview=preview)
    return {
        "camera": camera,
        "file": output.name,
        "backend": backend,
        "seconds": round(time.perf_counter() - started, 1),
    }


def main() -> int:
    """Build, apply both states, render the proof frames, save the .blend."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--blend", required=True)
    parser.add_argument("--preview", action="store_true")
    arguments = parser.parse_args(argv)
    outdir = Path(arguments.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    preview = arguments.preview

    build_master_scene.build_master_scene(arguments.spec)
    frames: list[dict[str, object]] = []

    apply_render_export.apply_render_export_file(arguments.spec, arguments.before)
    frames.append(timed_render("CAM_HERO_WORLD", outdir / "phase15_before.png", preview=preview))

    apply_render_export.apply_render_export_file(arguments.spec, arguments.after)
    frames.append(timed_render("CAM_HERO_WORLD", outdir / "phase15_after.png", preview=preview))
    frames.append(timed_render("CAM_HERO_SCAR", outdir / "phase15_hero_scar.png", preview=preview))
    frames.append(
        timed_render("CAM_SCAR_DETAIL", outdir / "phase15_scar_detail.png", preview=preview)
    )
    frames.append(
        timed_render("CAM_SEAL_DETAIL", outdir / "phase15_golden_seal_detail.png", preview=preview)
    )
    frames.append(
        timed_render("CAM_VERIFY_TOPOLOGY", outdir / "phase15_topology_verify.png", preview=preview)
    )

    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(arguments.blend).resolve()))

    (outdir / "render_report.json").write_text(
        json.dumps({"frames": frames}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("LD_VISUAL_PROOF: complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
