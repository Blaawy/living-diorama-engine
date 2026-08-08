"""Render the Phase 15 visual style bake-off: styles A, B, and C.

One Blender session, one world, one authoritative Render Export. For each
style the persistent master scene is rebuilt under that style's profile, the
SAME after-state export is applied, and a fixed frame set renders:

* a CONTROL frame from the shared comparison camera (identical transform,
  lens, and aperture across styles -- comparing style alone),
* a NATIVE HERO frame using that style's strongest camera grammar,
* a SCAR DETAIL frame on comparable subject matter, and
* a GOLDEN SEAL frame for brand-object compatibility.

Geography, topology, wall placement, and the Seal are identical across all
three styles by construction; only materials, lighting, grading, practical
intensity, and camera grammar differ.

Usage::

    blender --background --factory-startup --python produce_style_bakeoff.py \
        -- --spec S --export AFTER.json --outdir DIR
"""

import argparse
import json
import sys
import time
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply_render_export  # noqa: E402
import build_master_scene  # noqa: E402
import render_visual_proof  # noqa: E402
from blender_runtime import link_only, look_at_rotation, replace_object  # noqa: E402
from style_profiles import STYLE_NAMES  # noqa: E402

CONTROL_CAMERA = "CAM_HERO_WORLD"

BAKEOFF_CAMERAS: dict[str, dict] = {
    "CAM_BAKEOFF_B_HERO": {
        "location": (78.0, -78.0, 58.0),
        "look_at": (-10.0, 3.0, 0.0),
        "lens_mm": 48.0,
        "f_stop": 1.2,
        "focus": (17.0, -1.0, 8.0),
    },
    "CAM_BAKEOFF_B_SCAR": {
        "location": (40.0, -22.0, 17.0),
        "look_at": (15.5, -0.5, 7.0),
        "lens_mm": 70.0,
        "f_stop": 1.4,
        "focus": (17.0, -1.0, 8.0),
    },
    "CAM_BAKEOFF_B_SEAL": {
        "location": (-16.0, -2.0, 17.0),
        "look_at": (-16.0, 6.0, 2.5),
        "lens_mm": 50.0,
        "f_stop": 2.0,
        "focus": (-16.0, 6.0, 3.6),
    },
    "CAM_BAKEOFF_C_HERO": {
        "location": (125.0, -102.0, 80.0),
        "look_at": (-8.0, 6.0, -4.0),
        "lens_mm": 32.0,
        "f_stop": 5.6,
        "focus": (0.0, 0.0, 4.0),
    },
    "CAM_BAKEOFF_C_SCAR": {
        "location": (72.0, -15.0, 6.5),
        "look_at": (14.0, 0.5, 8.5),
        "lens_mm": 35.0,
        "f_stop": 4.0,
        "focus": (17.0, -1.0, 8.0),
    },
    "CAM_BAKEOFF_C_SEAL": {
        "location": (-4.5, 9.5, 3.0),
        "look_at": (-17.0, 3.6, 5.6),
        "lens_mm": 32.0,
        "f_stop": 2.8,
        "focus": (-16.0, 6.0, 5.0),
    },
}

STYLE_FRAMES: dict[str, list[tuple[str, str]]] = {
    "a": [
        ("style_a_control.png", CONTROL_CAMERA),
        ("style_a_hero.png", "CAM_HERO_SCAR"),
        ("style_a_scar_detail.png", "CAM_SCAR_DETAIL"),
        ("style_a_seal.png", "CAM_SEAL_DETAIL"),
    ],
    "b": [
        ("style_b_control.png", CONTROL_CAMERA),
        ("style_b_hero.png", "CAM_BAKEOFF_B_HERO"),
        ("style_b_scar_detail.png", "CAM_BAKEOFF_B_SCAR"),
        ("style_b_seal.png", "CAM_BAKEOFF_B_SEAL"),
    ],
    "c": [
        ("style_c_control.png", CONTROL_CAMERA),
        ("style_c_hero.png", "CAM_BAKEOFF_C_HERO"),
        ("style_c_scar_detail.png", "CAM_BAKEOFF_C_SCAR"),
        ("style_c_seal.png", "CAM_BAKEOFF_C_SEAL"),
    ],
}


def build_bakeoff_cameras() -> None:
    """Create the style-native cameras (persistent anchors stay untouched)."""
    collection = bpy.data.collections["LD_CAMERAS"]
    for name, definition in BAKEOFF_CAMERAS.items():
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


def main() -> int:
    """Build each style over the same world and render its frame set."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--export", required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--styles", default=",".join(STYLE_NAMES))
    arguments = parser.parse_args(argv)
    outdir = Path(arguments.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    frames: list[dict[str, object]] = []
    for style in arguments.styles.split(","):
        build_master_scene.build_master_scene(arguments.spec, style=style)
        apply_render_export.apply_render_export_file(arguments.spec, arguments.export, style=style)
        build_bakeoff_cameras()
        for filename, camera in STYLE_FRAMES[style]:
            started = time.perf_counter()
            backend = render_visual_proof.render_frame(
                camera, outdir / filename, preview=arguments.preview
            )
            frames.append(
                {
                    "style": style,
                    "file": filename,
                    "camera": camera,
                    "backend": backend,
                    "seconds": round(time.perf_counter() - started, 1),
                }
            )
    (outdir / "bakeoff_render_report.json").write_text(
        json.dumps({"frames": frames}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("LD_STYLE_BAKEOFF: complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
