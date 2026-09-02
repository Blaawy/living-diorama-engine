"""Instantiate the V2 open-trajectory pedestrian mobility layer inside Blender.

Like the V1 applier, this file INSTANTIATES; it does not decide. Every route,
speed, start offset and micro event is read from the pure V2 plan, which was
derived from the real pedestrian topology and proven clear before Blender was
ever opened.

The V2 layer borrows the same Phase 18 proxies and the same removability
contract as V1: ``clear_mobility_layer`` and ``restore_population_transforms``
are reused verbatim, so the scene returns to the exact Phase 18 population
when the layer is removed. The difference is the trajectory shape: each walker
rides an OPEN path (``use_cyclic_u = False``), keyed from its own seeded start
offset and honoring pause-style micro events as flat segments, so a body
genuinely walks from its route start toward its route end and never loops.
"""

import sys
from pathlib import Path

import bmesh  # noqa: F401  (imported for parity with the runtime harness)
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pedestrian_mobility as walking  # noqa: E402
from apply_mobility import (  # noqa: E402
    GAIT_KEY_PREFIX,
    PATH_PREFIX,
    MobilityApplyError,
    _key_curve,
    attach_to_path,
    clear_mobility_layer,
    ensure_mobility_collection,
    restore_population_transforms,
)
from blender_runtime import link_only, replace_object  # noqa: E402
from mobility_plan import mobility_plan_hash  # noqa: E402


def _distance_profile(route_length, speed, fps, start_offset, events, start_frame):
    """(frame, distance) keyframes for one open walk, pauses included.

    The walker is idle until its seeded start offset, walks at its preferred
    speed, stops for the declared duration of each pause-style micro event,
    and finishes at the route end. Blender holds the last value past the final
    key, so a walker that reaches its route end stays there.
    """
    keys = [(float(start_frame), 0.0), (float(start_frame) + start_offset * fps, 0.0)]
    distance = 0.0
    frame = float(start_frame) + start_offset * fps
    metres_per_frame = speed / fps
    for event in sorted(events, key=lambda entry: entry["s"]):
        duration = int(event.get("duration_frames", 0))
        if duration <= 0:
            continue
        target = min(float(event["s"]), route_length)
        if target < distance:
            continue
        frame += (target - distance) / metres_per_frame
        keys.append((frame, target))
        distance = target
        frame += duration
        keys.append((frame, distance))
    frame += (route_length - distance) / metres_per_frame
    keys.append((frame, route_length))
    return keys


def build_open_path(name, points, timeline, collection, profile) -> bpy.types.Object:
    """One open, arc-length-parameterised path with the walker's own timing.

    ``eval_time`` is keyed from the distance profile: zero until the walker's
    start offset, then linear at its preferred speed (with flats for pauses),
    then held. The path is NOT cyclic, so the loop contract never applies.
    """
    replace_object(name)
    existing = bpy.data.curves.get(name)
    if existing is not None:
        bpy.data.curves.remove(existing, do_unlink=True)
    curve = bpy.data.curves.new(name, type="CURVE")
    curve.dimensions = "3D"
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, (x, y, z) in zip(spline.points, points, strict=True):
        point.co = (float(x), float(y), float(z), 1.0)
    spline.use_cyclic_u = False
    curve.use_path = True
    curve.path_duration = int(timeline["frame_span"])
    curve.eval_time = 0.0
    obj = bpy.data.objects.new(name, curve)
    obj.location = (0.0, 0.0, 0.0)
    link_only(obj, collection)

    def _set_eval(value: float) -> None:
        curve.eval_time = value

    frame_span = float(timeline["frame_span"])
    route_length = max(1.0e-9, float(points and _polyline_length(points)))
    keys = [(frame, frame_span * min(1.0, distance / route_length)) for frame, distance in profile]
    _key_curve(
        curve,
        "eval_time",
        keys,
        f"v2_path__{name.removeprefix(PATH_PREFIX)}",
        _set_eval,
    )
    return obj


def _polyline_length(points) -> float:
    total = 0.0
    for index in range(len(points) - 1):
        first, second = points[index], points[index + 1]
        total += ((second[0] - first[0]) ** 2 + (second[1] - first[1]) ** 2) ** 0.5
    return total


def apply_gait_windowed(obj, walker, mobility_spec, timeline, start_frame, end_frame) -> dict:
    """Give one borrowed body its stride over the OPEN walk window only.

    V1's gait repeats with a CYCLES modifier because its route loops; an open
    walk must not march in place after the walker stops, so the same phase
    keyframes are spread over the walk window without the modifier.
    """
    mesh = obj.data
    if mesh.shape_keys is not None:
        raise MobilityApplyError(f"{obj.name} already carries shape keys before V2 mobility")
    if mesh.users != 1:
        raise MobilityApplyError(
            f"{obj.name} shares its mesh with {mesh.users - 1} other object(s)"
        )
    cycle = walker["gait"]
    shapes = walking.gait_shapes(walker, cycle, mobility_spec)
    if any(len(shape) != len(mesh.vertices) for shape in shapes):
        raise MobilityApplyError(
            f"{obj.name} has {len(mesh.vertices)} vertices, the gait supplies {len(shapes[0])}"
        )
    obj.shape_key_add(name=f"{GAIT_KEY_PREFIX}basis", from_mix=False)
    blocks = []
    for index, shape in enumerate(shapes):
        block = obj.shape_key_add(name=f"{GAIT_KEY_PREFIX}p{index:02d}", from_mix=False)
        block.slider_min = 0.0
        block.slider_max = 1.0
        for vertex, position in zip(block.data, shape, strict=True):
            vertex.co = position
        blocks.append(block)
    phases = len(shapes)
    span = (float(end_frame) - float(start_frame)) / int(cycle["cycles"])
    keyframes = 0
    for index, block in enumerate(blocks):
        keys = []
        for step in range(phases + 1):
            frame = start_frame + span * step / phases
            keys.append((frame, 1.0 if step % phases == index else 0.0))
        keyframes += _key_curve(
            mesh.shape_keys,
            f'key_blocks["{block.name}"].value',
            keys,
            f"v2_gait__{walker['slot']}",
            lambda value, target=block: setattr(target, "value", value),
        )
    return {"shape_keys": len(blocks) + 1, "keyframes": keyframes, "gait_cycles": cycle["cycles"]}


def apply_mobility_v2(plan: dict, mobility_spec: dict) -> dict:
    """Build the whole V2 open-trajectory pedestrian layer from one V2 plan."""
    clear_mobility_layer()
    restore_population_transforms(plan)
    # ``clear_mobility_layer`` above removes the ``LD_MOBILITY`` collection
    # itself (full removability means no trace), so the collection is
    # re-created here, exactly as the V1 applier re-creates it after its own
    # clear -- otherwise the V2 applier could never run on a fresh scene.
    collection = ensure_mobility_collection()
    timeline = plan["timeline"]
    fps = float(timeline["fps"])
    metrics = {"paths": 0, "shape_keys": 0, "keyframes": 0, "walkers": 0}
    for walker in sorted(plan["pedestrians"]["walkers"], key=lambda entry: entry["slot"]):
        obj = bpy.data.objects.get(f"LD_POP__{walker['slot']}")
        if obj is None:
            raise MobilityApplyError(
                f"the plan walks {walker['slot']}, which the Phase 18 population layer did "
                "not build; V2 mobility never creates a person"
            )
        profile = _distance_profile(
            walker["route_length"],
            float(walker["preferred_speed"]),
            fps,
            float(walker["start_offset"]),
            walker["micro_behavior_schedule"],
            int(timeline["start_frame"]),
        )
        path = build_open_path(
            f"{PATH_PREFIX}v2ped__{walker['slot']}",
            walker["points"],
            timeline,
            collection,
            profile,
        )
        attach_to_path(obj, path, 0.0, timeline, f"v2ped__{walker['slot']}")
        walk_start = profile[1][0]
        walk_end = min(float(timeline["end_frame"]), profile[-1][0])
        gait = apply_gait_windowed(obj, walker, mobility_spec, timeline, walk_start, walk_end)
        metrics["shape_keys"] += gait["shape_keys"]
        metrics["keyframes"] += gait["keyframes"]
        metrics["paths"] += 1
        metrics["walkers"] += 1
    return {**metrics, "plan_hash": mobility_plan_hash(plan)}
