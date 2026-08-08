"""Render one proof frame from a named persistent camera anchor.

Owns only render mechanics: camera selection, Cycles device/backend fallback
(OptiX, then CUDA, then CPU -- the scene never requires a specific GPU),
sampling, denoising, and output. The look itself (AgX, exposure) is scene
state established by the master build.

Run headless, after build + apply in the same session or on a saved scene::

    blender --background --factory-startup --python render_visual_proof.py -- \
        --camera CAM_HERO_WORLD --output frame.png [--preview]
"""

import argparse
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))

from blender_runtime import require_supported_blender  # noqa: E402


def configure_cycles_device() -> str:
    """Prefer OptiX, then CUDA, then CPU; report what was chosen."""
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    preferences = bpy.context.preferences.addons["cycles"].preferences
    for backend in ("OPTIX", "CUDA"):
        try:
            preferences.compute_device_type = backend
        except TypeError:
            continue
        preferences.get_devices()
        matching = [device for device in preferences.devices if device.type == backend]
        if matching:
            for device in preferences.devices:
                device.use = device.type in (backend, "CPU")
            scene.cycles.device = "GPU"
            return backend
    preferences.compute_device_type = "NONE"
    scene.cycles.device = "CPU"
    return "CPU"


def configure_sampling(*, preview: bool) -> None:
    """Adaptive sampling and denoising tuned for clean architectural frames."""
    cycles = bpy.context.scene.cycles
    cycles.use_adaptive_sampling = True
    if preview:
        cycles.samples = 96
        cycles.adaptive_threshold = 0.08
    else:
        cycles.samples = 1024
        cycles.adaptive_threshold = 0.015
    cycles.use_denoising = True
    cycles.denoiser = "OPENIMAGEDENOISE"
    cycles.denoising_input_passes = "RGB_ALBEDO_NORMAL"
    cycles.max_bounces = 8
    cycles.volume_bounces = 1
    cycles.transparent_max_bounces = 12


def render_frame(camera_name: str, output_path: str | Path, *, preview: bool) -> str:
    """Render one frame from a named LD camera and return the backend used."""
    require_supported_blender()
    camera = bpy.data.objects.get(camera_name)
    if camera is None or camera.type != "CAMERA":
        raise RuntimeError(f"camera {camera_name!r} does not exist in the scene")
    scene = bpy.context.scene
    scene.camera = camera
    backend = configure_cycles_device()
    configure_sampling(preview=preview)
    if preview:
        scene.render.resolution_x = 1280
        scene.render.resolution_y = 720
    else:
        scene.render.resolution_x = 2560
        scene.render.resolution_y = 1440
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_depth = "8"
    scene.render.filepath = str(Path(output_path).resolve())
    bpy.ops.render.render(write_still=True)
    return backend


def main() -> None:
    """Command-line entry: render one proof frame."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--preview", action="store_true")
    arguments = parser.parse_args(argv)
    backend = render_frame(arguments.camera, arguments.output, preview=arguments.preview)
    print(f"LD_RENDER_BACKEND: {backend}")


if __name__ == "__main__":
    main()
