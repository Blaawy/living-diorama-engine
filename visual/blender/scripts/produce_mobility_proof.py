"""Render the Phase 19 daily-life mobility proof pack.

Runs inside Blender. Builds the canonical world, stands the LOCKED Phase 18
population in it, applies the Phase 19 mobility layer, and renders the frames
and clips a reviewer needs in order to judge -- not to take on trust -- whether
the city moves.

    THE PROOF MUST MAKE THE DEFECTS FINDABLE.

That shapes every camera here. The gait clip stands close enough to a walking
route that a body sliding with frozen legs would be unmissable. The traffic clip
sits at wheel height and square to the lane, so a vehicle crabbing, sliding
sideways or snapping its heading could not hide.

It also proves the wheels TURN, which an earlier cut of this phase could not.
The bodies then hung lower and wider than their own hubs, so the only visible
part of a wheel was the tyre's lower arc -- rotationally symmetric, and
therefore identical whether the wheel span or was welded solid. The kit now
cuts real arches into the hull and carries a two-sector witness on BOTH faces
of every wheel, so the mark is in shot whichever flank a camera happens to
watch. The arithmetic is still checked independently -- turns x 2*pi*r against
route length, and the structural suite's ``test_a_wheel_turns_forward`` -- but
a reviewer no longer has to take it on trust.

The validity frame looks straight down, where a body in a carriageway or a
vehicle on a pavement is impossible to miss. And the city frame deliberately
shows the WHOLE diorama including the quarters with no traffic at all, because
the honest limitation of this phase -- that only part of the road network can
carry a legal closed route -- must be visible rather than framed out.
"""

import argparse
import json
import math
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply_mobility as mobility  # noqa: E402
import apply_population_presence as population  # noqa: E402
import mobility_plan as mp  # noqa: E402
import pedestrian_topology as topo  # noqa: E402
import population_presence_plan as pres  # noqa: E402
import production_spec  # noqa: E402
import road_graph  # noqa: E402
import scene_spec  # noqa: E402
import urban_fabric  # noqa: E402
import vehicle_kit  # noqa: E402
from blender_runtime import link_only  # noqa: E402
from build_master_scene import build_master_scene  # noqa: E402
from build_production_world import add_production_world  # noqa: E402
from manifest_io import write_manifest_json  # noqa: E402
from mobility_proof_package import (  # noqa: E402
    clear_clip_outputs,
    finalize_clip_output,
    require_contact_sheet_frames,
)
from mobility_spec import (  # noqa: E402
    load_daily_life_mobility_spec,
    resolve_mobility_timeline,
)
from motion_time_spec import load_motion_time_spec  # noqa: E402
from population_presence_spec import load_population_presence_spec  # noqa: E402
from proof_package import ProofPackageError  # noqa: E402
from render_visual_proof import (  # noqa: E402
    configure_cycles_device,
    configure_sampling,
    render_frame,
)

MANIFEST_NAME = "phase19_mobility_manifest.json"
CONTACT_SHEET = "phase19_contact_sheet.png"
PROOF_STYLE = "dna"

STILLS = (
    ("CAM_P19_DAILY_LIFE", "phase19_start.png", "start"),
    ("CAM_P19_DAILY_LIFE", "phase19_mid.png", "mid"),
    ("CAM_P19_DAILY_LIFE", "phase19_end.png", "end"),
    ("CAM_P19_CITY", "phase19_city_context.png", "mid"),
    ("CAM_P19_VALIDITY", "phase19_route_validity.png", "mid"),
    ("CAM_P19_GAIT", "phase19_gait_context.png", "mid"),
    ("CAM_P19_TRAFFIC", "phase19_traffic_context.png", "mid"),
)
"""The stills, and which point of the cycle each is taken at.

``start`` and ``end`` are the SAME camera on the two loop endpoints, so the
seamlessness of the cycle is something a reviewer can check by comparing two
pictures rather than by reading a number."""

CLIPS = (
    ("CAM_P19_DAILY_LIFE", "phase19_daily_life_cycle.mp4"),
    ("CAM_P19_GAIT", "phase19_pedestrian_gait_verify.mp4"),
    ("CAM_P19_TRAFFIC", "phase19_vehicle_motion_verify.mp4"),
)

SHEET_FRAMES = (
    "phase19_start.png",
    "phase19_mid.png",
    "phase19_end.png",
    "phase19_city_context.png",
    "phase19_route_validity.png",
    "phase19_gait_context.png",
)


def build_mobility_cameras(mobility_spec: dict) -> None:
    """Place the Phase 19 proof anchors from the spec, never from this file."""
    collection = bpy.data.collections.get("LD_CAMERAS") or bpy.context.scene.collection
    for name, entry in sorted(mobility_spec["proof"]["cameras"].items()):
        existing = bpy.data.objects.get(name)
        if existing is not None:
            bpy.data.objects.remove(existing, do_unlink=True)
        camera = bpy.data.cameras.new(name)
        camera.lens = float(entry["lens_mm"])
        obj = bpy.data.objects.new(name, camera)
        obj.location = tuple(entry["location"])
        target = tuple(entry["look_at"])
        direction = (
            target[0] - obj.location[0],
            target[1] - obj.location[1],
            target[2] - obj.location[2],
        )
        flat = math.hypot(direction[0], direction[1])
        # Blender applies an XYZ euler as Rz @ Ry @ Rx, so after the pitch the
        # lens points along +Y and the yaw must carry +Y onto the horizontal
        # direction: Rz(y) @ (0,1,0) = (-sin y, cos y, 0), hence atan2(-dx, dy).
        # Writing atan2(dy, dx) + pi/2 aims the camera exactly 180 degrees away
        # from its own look_at, which is a spectacular way to render a proof of
        # nothing while every number in the manifest still checks out.
        obj.rotation_euler = (
            math.atan2(flat, -direction[2]),
            0.0,
            math.atan2(-direction[0], direction[1]),
        )
        link_only(obj, collection)


def frame_for(kind: str, timeline: dict) -> int:
    """Which frame one named point of the cycle is."""
    if kind == "start":
        return timeline["start_frame"]
    if kind == "end":
        return timeline["end_frame"]
    return timeline["start_frame"] + timeline["frame_span"] // 2


def render_clip(camera: str, path: Path, timeline: dict, *, preview: bool) -> dict:
    """Render one whole mobility cycle as a video clip.

    The clip covers the WHOLE canonical span, first frame to last, because a
    seamless loop is the claim and a clip that stopped short would be showing
    something else.
    """
    clear_clip_outputs(path)
    scene = bpy.context.scene
    scene.camera = bpy.data.objects[camera]
    scene.frame_start = timeline["start_frame"]
    scene.frame_end = timeline["end_frame"]
    scene.render.fps = timeline["fps"]
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 50 if preview else 100
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "HIGH" if preview else "PERC_LOSSLESS"
    scene.render.filepath = str(path.with_suffix(""))
    try:
        bpy.ops.render.render(animation=True)
        finalize_clip_output(path)
    finally:
        scene.render.image_settings.file_format = "PNG"
    return {"file": path.name, "camera": camera, "frames": timeline["frame_span"] + 1}


def loop_closure() -> dict:
    """Measure the seamless-loop claim on the real scene, at both endpoints."""
    scene = bpy.context.scene
    scene.frame_set(scene.frame_start)
    bpy.context.view_layer.update()
    first = mobility.mobility_transforms()
    scene.frame_set(scene.frame_end)
    bpy.context.view_layer.update()
    last = mobility.mobility_transforms()
    worst_name, worst = "", 0.0
    for name in sorted(first):
        drift = max(abs(a - b) for a, b in zip(first[name], last[name], strict=True))
        if drift > worst:
            worst_name, worst = name, drift
    return {
        "compared_objects": len(first),
        "worst_drift": round(worst, 9),
        "worst_object": worst_name,
        "closed": worst < 1.0e-4,
    }


def compose_contact_sheet(outdir: Path) -> None:
    """One sheet a reviewer can scan before opening anything.

    Every frame in :data:`SHEET_FRAMES` or none at all. This function used to
    skip a frame that was not on disk and compose whatever remained, so a failed
    gait render shrank the sheet by one tile and left nothing that said so: the
    manifest still named the frame, the package still verified, and the gate
    still printed PASS. A missing tile is now a refusal, and the run that could
    not render it stops there.
    """
    try:
        import numpy
    except ImportError as error:  # Blender ships numpy; an absent one is not a smaller sheet
        raise ProofPackageError("the contact sheet cannot be composed without numpy") from error
    tiles = []
    for path in require_contact_sheet_frames(outdir, SHEET_FRAMES):
        image = bpy.data.images.load(str(path))
        width, height = image.size
        pixels = numpy.array(image.pixels[:]).reshape(height, width, 4)[:, :, :3]
        tiles.append(pixels)
        bpy.data.images.remove(image)
    height = min(tile.shape[0] for tile in tiles)
    width = min(tile.shape[1] for tile in tiles)
    scaled = [
        tile[
            (numpy.arange(height) * tile.shape[0] // height)[:, None],
            (numpy.arange(width) * tile.shape[1] // width)[None, :],
        ]
        for tile in tiles
    ]
    columns = 3
    rows = (len(scaled) + columns - 1) // columns
    sheet = numpy.zeros((rows * height, columns * width, 3), dtype=scaled[0].dtype)
    for index, tile in enumerate(scaled):
        row, column = divmod(index, columns)
        sheet[row * height : (row + 1) * height, column * width : (column + 1) * width] = tile
    output = bpy.data.images.new(CONTACT_SHEET, width=columns * width, height=rows * height)
    output.pixels = numpy.concatenate(
        [sheet, numpy.ones((*sheet.shape[:2], 1), dtype=sheet.dtype)], axis=2
    ).ravel()
    output.filepath_raw = str(outdir / CONTACT_SHEET)
    output.file_format = "PNG"
    output.save()
    bpy.data.images.remove(output)


def sha256_of(path: Path) -> str:
    """SHA-256 of one delivered file."""
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_mobility_manifest(
    outdir: Path,
    plan: dict,
    mobility_spec: dict,
    presence: dict,
    export_path: Path,
    blend_path: Path,
    plan_path: Path,
    renders: list[dict],
    clips: list[dict],
    base_sha: str,
) -> Path:
    """Write the one manifest that states what this proof shows, and what it does not."""
    scene = mobility.mobility_summary()
    document = {
        "artifact": "living_diorama_phase19_daily_life_mobility",
        "schema_version": 1,
        "base_sha": base_sha,
        "plan_hash": mp.mobility_plan_hash(plan),
        "presence_plan_hash": pres.plan_hash(presence),
        "source_export": {
            "path": export_path.name,
            "sha256": sha256_of(export_path),
            "bytes": export_path.stat().st_size,
        },
        "mobility_plan": {
            "path": plan_path.name,
            "sha256": sha256_of(plan_path),
            "bytes": plan_path.stat().st_size,
        },
        "blend": {
            "path": blend_path.name,
            "sha256": sha256_of(blend_path),
            "bytes": blend_path.stat().st_size,
        },
        "timeline": plan["timeline"],
        "population": {
            "total_population_proxies": plan["summary"]["total_population_proxies"],
            "moving_pedestrians": plan["summary"]["moving_pedestrians"],
            "stationary_pedestrians": plan["summary"]["stationary_pedestrians"],
            "moving_slots": plan["pedestrians"]["moving_slots"],
            "by_zone": plan["pedestrians"]["by_zone"],
            "by_district": plan["pedestrians"]["by_district"],
            "speed_range": plan["summary"]["pedestrian_speed_range"],
            "excursion_range": plan["summary"]["pedestrian_excursion_range"],
            "route_families": sorted(
                {entry["route_family"] for entry in plan["pedestrians"]["walkers"]}
            ),
            "gait_cycles": sorted(
                {entry["gait"]["cycles"] for entry in plan["pedestrians"]["walkers"]}
            ),
            "refused_routes": len(plan["pedestrians"]["refused"]),
        },
        "vehicles": {
            "target_count": plan["vehicles"]["target_count"],
            "moving_vehicles": plan["summary"]["moving_vehicles"],
            "capacity": plan["vehicles"]["capacity"],
            "driving_side": plan["vehicles"]["driving_side"],
            "by_archetype": plan["vehicles"]["by_archetype"],
            "speed_range": plan["summary"]["vehicle_speed_range"],
            "slot_pitch": plan["vehicles"]["slot_pitch"],
            "circuits": plan["vehicles"]["route_offer"]["by_circuit"],
            "route_offer": plan["vehicles"]["route_offer"],
            "kit": vehicle_kit.kit_summary(),
            # BOTH numbers, named for what they are. The reservation is what
            # the lane network planned against; the visual bounds are what the
            # kit actually builds; and a reader can see for themselves that the
            # second fits inside the first, per archetype and per component.
            "envelope_contracts": vehicle_kit.envelope_contracts(),
        },
        "coverage": plan["vehicles"]["coverage"],
        "collision": plan["collision"],
        "loop_closure": loop_closure(),
        "scene_mobility": scene,
        "motion_counts": {
            "total_moving_root_objects": plan["summary"]["total_moving_root_objects"],
            "total_visible_population_and_vehicles": plan["summary"][
                "total_visible_population_and_vehicles"
            ],
            "actions": scene["actions"],
            "fcurves": scene["fcurves"],
            "keyframes": scene["keyframes"],
            "gait_shape_keys": scene["gait_shape_keys"],
            "paths": scene["paths"],
            "vehicle_triangles": scene["vehicle_triangles"],
        },
        "renders": renders,
        "clips": clips,
        "semantics": {
            "statement": mp.PRESENTATION_STATEMENT,
            "expected_statement": mp.PRESENTATION_STATEMENT,
            "authoritative": [
                "district population, from the render export",
                "Phase 18 proxy slots, anchors and visual identities",
                "the Phase 16 road graph and carriageway widths",
                "the Phase 17 canonical timeline",
            ],
            "presentation_policy": [
                "which proxies move, and how fast they walk",
                "the shape and length of every walking route",
                "how many vehicles the city carries, and where they drive",
                "vehicle archetypes, paint and spacing",
            ],
        },
    }
    target = outdir / MANIFEST_NAME
    write_manifest_json(target, document)
    return target


def main() -> int:
    """Blender entry point: build the moving city and render its proof."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--production", required=True)
    parser.add_argument("--presence", required=True)
    parser.add_argument("--mobility", required=True)
    parser.add_argument("--motion", required=True)
    parser.add_argument("--export", required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--blend", required=True)
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--preview", action="store_true")
    arguments = parser.parse_args(argv)

    outdir = Path(arguments.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    # The manifest is the LAST file this producer writes, so one already on
    # disk means a completed earlier run's proof pack occupies this directory.
    # Rendering over it would let a crash partway through leave the
    # predecessor's artifacts standing as this run's evidence.
    if (outdir / MANIFEST_NAME).exists():
        raise ProofPackageError(
            f"{outdir} already holds {MANIFEST_NAME} from a completed earlier run; "
            "render this proof into a fresh workspace"
        )
    export_path = Path(arguments.export)

    master = scene_spec.load_master_scene_spec(arguments.spec)
    prod = production_spec.load_production_world_spec(arguments.production)
    presence_spec = load_population_presence_spec(arguments.presence)
    mobility_spec = load_daily_life_mobility_spec(arguments.mobility)
    timeline = resolve_mobility_timeline(
        mobility_spec, load_motion_time_spec(arguments.motion)["timeline"]
    )
    graph = road_graph.build_road_graph(master, prod)
    fabric = urban_fabric.plan_urban_fabric(master, prod, graph)
    topology = topo.plan_pedestrian_topology(master, prod, graph, fabric, presence_spec)
    export = scene_spec.load_render_export(export_path)
    presence = pres.plan_population_presence(export, master, presence_spec, topology)
    plan = mp.plan_daily_life_mobility(
        presence, presence_spec, mobility_spec, timeline, master, prod, graph, fabric
    )

    build_master_scene(arguments.spec, style=PROOF_STYLE)
    add_production_world(arguments.spec, arguments.production, style=PROOF_STYLE)
    population.apply_population_presence(presence, presence_spec)
    mobility.apply_mobility(plan, mobility_spec)
    build_mobility_cameras(mobility_spec)

    configure_cycles_device()
    configure_sampling(preview=arguments.preview)
    scene = bpy.context.scene
    scene.render.resolution_x = 2560 if not arguments.preview else 1280
    scene.render.resolution_y = 1440 if not arguments.preview else 720

    plan_path = outdir / "phase19_mobility_plan.json"
    plan_path.write_text(
        json.dumps(plan, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    # The manifest names the export this proof was rendered FROM, so the package
    # has to carry it. Naming a file the package does not hold is a dangling
    # reference, and the inventory refuses one -- rightly.
    carried_export = outdir / export_path.name
    if carried_export.resolve() != export_path.resolve():
        carried_export.write_bytes(export_path.read_bytes())

    renders: list[dict] = []
    for camera, name, when in STILLS:
        frame = frame_for(when, timeline)
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        render_frame(camera, outdir / name, preview=arguments.preview)
        renders.append({"file": name, "camera": camera, "frame": frame, "point": when})

    clips = [
        render_clip(camera, outdir / name, timeline, preview=arguments.preview)
        for camera, name in CLIPS
    ]

    compose_contact_sheet(outdir)
    blend_path = Path(arguments.blend)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), compress=True)
    write_mobility_manifest(
        outdir,
        plan,
        mobility_spec,
        presence,
        export_path,
        blend_path,
        plan_path,
        renders,
        clips,
        arguments.base_sha,
    )
    print(f"phase 19 proof written to {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
