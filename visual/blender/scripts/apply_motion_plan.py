"""Realise one MotionPlan as Blender animation on the existing world.

Blender-only runtime. It creates NO geometry of its own: every object it
touches was built by the locked Phase 15/16 builders, and every property it
drives was authorised by the pure :mod:`motion_plan`. The engine is never
imported here, and the planner never imports ``bpy``.

How an animated scene is assembled, and why in this order:

1. Build the persistent world (master scene, then the production city).
2. Apply the BEFORE export the ordinary locked way, and MEASURE it. That is
   the canonical truth for the first frame.
3. Apply the AFTER export the ordinary locked way, and MEASURE it. That is
   the canonical truth for the last frame.
4. Rebuild the before-state, then overlay the after-state WITHOUT clearing.
   The locked builders replace by name, so the result is exactly the union:
   every after-object with its canonical after-properties, plus the
   before-only objects still carrying their canonical before-properties.
5. Verify the union against both measurements, and refuse if any canonical
   difference is not covered by a directive. An animation is not allowed to
   quietly show the after-world's decoration at the before-frame.
6. Only then create F-curves, from the plan alone.

Because the union is assembled from two ordinary static applications, the
endpoints are not approximated -- they are the canonical scenes themselves,
with the objects that do not belong to a given endpoint hidden on that frame.

Application is idempotent: every action is named ``LD_MOTION__*`` and every
run clears those first, so applying the same plan twice yields the same
F-curves, the same key counts, no duplicate actions, and no ``.001`` growth.
"""

import argparse
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))

from apply_render_export import (  # noqa: E402
    apply_districts,
    apply_infrastructure,
    apply_law_state,
    apply_render_export_file,
    apply_walls,
)
from blender_runtime import (  # noqa: E402
    ensure_collections,
    require_supported_blender,
    set_practical_light_scale,
)
from motion_plan import (  # noqa: E402
    GLAZING_NODE,
    GLAZING_SOCKET,
    SEAL_GLOW_MATERIAL,
    SEAL_GLOW_NODE,
    SEAL_GLOW_SOCKET,
    keyframes,
    plan_motion,
    sampled_keyframes,
    staged_frames,
)
from motion_time_spec import load_motion_time_spec  # noqa: E402
from scene_spec import load_master_scene_spec, load_render_export  # noqa: E402
from style_profiles import resolve_style  # noqa: E402

EPISODE_COLLECTIONS = ("LD_EPISODE", "LD_WALLS", "LD_INFRASTRUCTURE")

MOTION_ACTION_PREFIX = "LD_MOTION__"

PRESENCE_PATHS = ("hide_render", "hide_viewport")
"""Both switches are driven so the saved ``.blend`` reads the same way in the
viewport as it renders. Boolean curves are always CONSTANT."""

COMPONENT_PATHS = {
    "location_x": ("location", 0),
    "location_y": ("location", 1),
    "location_z": ("location", 2),
    "rotation_z": ("rotation_euler", 2),
}

CANONICAL_EPSILON = 1.0e-9
"""Detecting a real difference BETWEEN two measured scenes. Both sides come
from Blender's own single-precision storage of the same locked computation,
so identical canonical values compare bit-equal and this can stay tight."""

PLAN_AGREEMENT_EPSILON = 1.0e-6
"""Comparing the planner's double-precision arithmetic against what Blender
actually stored. Applied relative to the magnitude of the values involved,
because a float32 metre at world scale is only accurate to about 1e-5."""

MAX_ID_NAME_BYTES = 63


def _agrees(expected: float, measured: float, scale: float) -> bool:
    """Whether a planned value matches a measured one at single precision."""
    return abs(expected - measured) <= PLAN_AGREEMENT_EPSILON * max(1.0, abs(scale))


class MotionApplyError(RuntimeError):
    """The scene and the plan disagree about what is being animated.

    Raised when a canonical difference between the two static applications is
    not covered by a directive, when a directive names something the scene
    does not hold, or when applying would collide with existing animation.
    Always a refusal: a half-applied motion plan is worse than none.
    """


def _episode_names() -> list[str]:
    """Every object currently in the episode-scoped collections, sorted."""
    names: set[str] = set()
    for collection_name in EPISODE_COLLECTIONS:
        collection = bpy.data.collections.get(collection_name)
        if collection is None:
            continue
        names.update(obj.name for obj in collection.objects)
    return sorted(names)


def _object_state(obj: bpy.types.Object) -> tuple:
    """The transform of one object, rounded to a stable comparison grid."""
    return (
        tuple(round(value, 9) for value in obj.location),
        tuple(round(value, 9) for value in obj.rotation_euler),
        tuple(round(value, 9) for value in obj.scale),
    )


def capture_episode() -> dict[str, tuple]:
    """Measure every episode object's canonical transform."""
    return {name: _object_state(bpy.data.objects[name]) for name in _episode_names()}


def _socket_of(material_name: str, node_name: str, socket: str):
    """Resolve one material node socket to (node_tree, data_path).

    Raises:
        MotionApplyError: If the material, the node, or the socket is absent.
    """
    material = bpy.data.materials.get(material_name)
    if material is None or material.node_tree is None:
        raise MotionApplyError(f"material {material_name!r} is not in the scene")
    node = material.node_tree.nodes.get(node_name)
    if node is None:
        raise MotionApplyError(f"material {material_name!r} has no node {node_name!r}")
    side, _, key = socket.partition(":")
    if side not in ("input", "output"):
        raise MotionApplyError(f"socket {socket!r} must be 'input:NAME' or 'output:INDEX'")
    collection = node.inputs if side == "input" else node.outputs
    entry = collection[int(key)] if key.isdigit() else collection.get(key)
    if entry is None:
        raise MotionApplyError(f"node {node_name!r} has no {side} socket {key!r}")
    return material.node_tree, entry.path_from_id("default_value")


def _material_channels(master_spec: dict) -> tuple[tuple[str, str, str], ...]:
    """Every material value the Phase 15 state mapping is allowed to drive."""
    channels = [(SEAL_GLOW_MATERIAL, SEAL_GLOW_NODE, SEAL_GLOW_SOCKET)]
    for character in sorted(
        {district["character"] for district in master_spec["districts"].values()}
    ):
        channels.append((f"LD_MAT__glass_{character}", GLAZING_NODE, GLAZING_SOCKET))
    return tuple(channels)


def capture_material_values(master_spec: dict) -> dict[tuple[str, str, str], float]:
    """Measure every state-driven material value currently in the scene."""
    measured: dict[tuple[str, str, str], float] = {}
    for channel in _material_channels(master_spec):
        node_tree, data_path = _socket_of(*channel)
        measured[channel] = round(float(node_tree.path_resolve(data_path)), 9)
    return measured


def geography_snapshot() -> list[tuple]:
    """Identity and transform of every object OUTSIDE the episode layer.

    The persistent city: plates, ground, streets, blocks, founding
    architecture, harbour, the Golden Seal, the vegetation that survived the
    clearing, and every camera. Phase 17 may never move any of it.
    """
    episode = set(_episode_names())
    entries = []
    for obj in bpy.data.objects:
        if not obj.name.startswith(("LD_", "CAM_")) or obj.name in episode:
            continue
        entries.append((obj.name, *_object_state(obj)))
    return sorted(entries)


def curve_of(holder, data_path: str, index: int = 0):
    """The F-curve driving one property, or None if nothing drives it."""
    animation = holder.animation_data
    if animation is None or animation.action is None:
        return None
    return animation.action.fcurves.find(data_path, index=index)


def object_state_at(obj: bpy.types.Object, frame: int) -> tuple | None:
    """One object's transform at a frame, or None if it is not there yet.

    Read from the F-curves themselves rather than from a depsgraph
    evaluation, so a comparison is exact, repeatable, and independent of
    whatever frame the scene happens to be sitting on.
    """
    hide = curve_of(obj, "hide_render")
    hidden = hide.evaluate(frame) >= 0.5 if hide is not None else obj.hide_render
    if hidden:
        return None
    values = []
    for attribute, current in (("location", obj.location), ("rotation_euler", obj.rotation_euler)):
        channel = []
        for index in range(3):
            curve = curve_of(obj, attribute, index)
            channel.append(round(curve.evaluate(frame) if curve is not None else current[index], 9))
        values.append(tuple(channel))
    values.append(tuple(round(value, 9) for value in obj.scale))
    return tuple(values)


def scene_state_at(frame: int) -> list[tuple]:
    """Every LD object VISIBLE at one frame, with its transform there.

    An object hidden on a frame is absent from that frame's world, which is
    exactly what makes it comparable with a static application that never
    built it at all.
    """
    entries = []
    for obj in bpy.data.objects:
        if not obj.name.startswith(("LD_", "CAM_")):
            continue
        state = object_state_at(obj, frame)
        if state is not None:
            entries.append((obj.name, *state))
    return sorted(entries)


def canonical_state(scene: dict, geography: list[tuple], which: str) -> list[tuple]:
    """The full visible world the ordinary static application of one endpoint gives.

    The persistent city plus exactly that endpoint's episode layer -- which is
    what :func:`scene_state_at` must reproduce at the first and last frames.
    """
    if which not in ("before", "after"):
        raise MotionApplyError(f"endpoint must be 'before' or 'after', got {which!r}")
    entries = list(geography)
    entries.extend((name, *state) for name, state in scene[f"static_{which}"].items())
    return sorted(entries)


def material_state_at(master_spec: dict, frame: int) -> dict[tuple[str, str, str], float]:
    """Every state-driven material value AS ANIMATED at one frame.

    The counterpart of :func:`scene_state_at` for the half of the world that
    is not geometry. A material channel Phase 17 animates is read from the
    F-curve that was actually applied to its node tree; a channel nothing
    animates keeps the value the canonical static application left on it.

    Reading the curve rather than the live socket is deliberate: it makes the
    comparison exact and independent of whichever frame the scene is sitting
    on when the check runs.
    """
    measured: dict[tuple[str, str, str], float] = {}
    for channel in _material_channels(master_spec):
        node_tree, data_path = _socket_of(*channel)
        curve = curve_of(node_tree, data_path)
        value = (
            curve.evaluate(frame) if curve is not None else float(node_tree.path_resolve(data_path))
        )
        measured[channel] = round(float(value), 9)
    return measured


def compare_endpoint(
    scene: dict, geography: list[tuple], master_spec: dict, timeline: dict, which: str
) -> dict:
    """Prove ONE endpoint is the ordinary static world, geometry AND materials.

    Object equivalence alone is not the Phase 17 contract: the Golden Seal's
    law indication and the district glazing are state channels too, and an
    animation that lands the geometry perfectly while leaving a material on
    the wrong value has still produced a false frame. Both halves are checked,
    and ``equivalent`` is true only when both are.
    """
    frame = timeline["start_frame" if which == "before" else "end_frame"]
    animated_objects = scene_state_at(frame)
    static_objects = canonical_state(scene, geography, which)
    animated_materials = material_state_at(master_spec, frame)
    static_materials = scene[f"materials_{which}"]

    mismatches = []
    for channel, expected in sorted(static_materials.items()):
        measured = animated_materials.get(channel)
        if measured is None or not _agrees(expected, measured, expected):
            mismatches.append(
                {
                    "material": channel[0],
                    "node": channel[1],
                    "socket": channel[2],
                    "animated": measured,
                    "static": expected,
                }
            )
    objects_equivalent = animated_objects == static_objects
    materials_equivalent = not mismatches
    return {
        "frame": frame,
        "objects_equivalent": objects_equivalent,
        "materials_equivalent": materials_equivalent,
        "equivalent": objects_equivalent and materials_equivalent,
        "visible_objects": len(animated_objects),
        "static_objects": len(static_objects),
        "material_channels": len(static_materials),
        "animated_material_channels": sorted(
            f"{material}/{node}/{socket}"
            for material, node, socket in static_materials
            if curve_of(*_socket_of(material, node, socket)) is not None
        ),
        "material_mismatches": mismatches,
    }


def endpoint_equivalence(
    scene: dict, geography: list[tuple], master_spec: dict, timeline: dict
) -> dict:
    """Prove BOTH endpoints are the ordinary static worlds they claim to be."""
    return {
        which: compare_endpoint(scene, geography, master_spec, timeline, which)
        for which in ("before", "after")
    }


def clear_motion_animation() -> int:
    """Remove every Phase 17 action, leaving the scene structurally untouched.

    Returns the number of actions removed. This is what makes re-application
    idempotent instead of additive.
    """
    holders = [
        *bpy.data.objects,
        *(material.node_tree for material in bpy.data.materials if material.node_tree),
    ]
    for holder in holders:
        animation = holder.animation_data
        if animation is None:
            continue
        action = animation.action
        if action is not None and action.name.startswith(MOTION_ACTION_PREFIX):
            holder.animation_data_clear()
    removed = 0
    for action in list(bpy.data.actions):
        if action.name.startswith(MOTION_ACTION_PREFIX):
            bpy.data.actions.remove(action)
            removed += 1
    return removed


def _episode_materials() -> dict:
    """The LD material family, keyed the way the locked episode pass expects."""
    return {
        name.removeprefix("LD_MAT__"): material
        for name, material in ((m.name, m) for m in bpy.data.materials)
        if name.startswith("LD_MAT__")
    }


def _overlay_export(export: dict, spec: dict) -> None:
    """Add one export's episode layer on top of another WITHOUT clearing.

    The locked builders replace by name, so overlaying the after-export on the
    before-state yields exactly the union of both object sets, with the
    after-state winning wherever both define the same object.
    """
    collections = ensure_collections()
    materials = _episode_materials()
    apply_walls(export, spec, collections, materials)
    apply_infrastructure(export, spec, collections, materials)
    apply_districts(export, spec, collections, materials)
    apply_law_state(export, spec, collections, materials)


def build_union_scene(
    spec_path: str | Path, before_path: str | Path, after_path: str | Path, style: str
) -> dict:
    """Measure both canonical endpoints and leave the union scene standing.

    Returns the measurements the verification and the animation both need:
    the canonical before-state, the canonical after-state, and the union that
    now stands in the scene.
    """
    require_supported_blender()
    master_spec = load_master_scene_spec(spec_path)

    apply_render_export_file(spec_path, before_path, style=style)
    static_before = capture_episode()
    materials_before = capture_material_values(master_spec)

    apply_render_export_file(spec_path, after_path, style=style)
    static_after = capture_episode()
    materials_after = capture_material_values(master_spec)

    apply_render_export_file(spec_path, before_path, style=style)
    set_practical_light_scale(resolve_style(style)["practical_scale"])
    _overlay_export(load_render_export(after_path), master_spec)

    return {
        "master_spec": master_spec,
        "static_before": static_before,
        "static_after": static_after,
        "materials_before": materials_before,
        "materials_after": materials_after,
        "union": capture_episode(),
        "union_materials": capture_material_values(master_spec),
    }


def _canonical_differences(scene: dict) -> dict[tuple[str, str], tuple[float, float]]:
    """Transform components a shared object holds differently at each endpoint.

    Every one of these MUST be covered by a ``canonical_offset`` directive; an
    uncovered difference would mean the first frame silently shows the
    after-world's placement.
    """
    animatable = {
        (0 if attribute == "location" else 1, index): component
        for component, (attribute, index) in COMPONENT_PATHS.items()
    }
    differences: dict[tuple[str, str], tuple[float, float]] = {}
    shared = set(scene["static_before"]) & set(scene["static_after"])
    for name in sorted(shared):
        before, after = scene["static_before"][name], scene["static_after"][name]
        for slot, label in ((0, "location"), (1, "rotation_euler"), (2, "scale")):
            for index in range(3):
                value_before, value_after = before[slot][index], after[slot][index]
                if abs(value_before - value_after) <= CANONICAL_EPSILON:
                    continue
                component = animatable.get((slot, index))
                if component is None:
                    raise MotionApplyError(
                        f"{name} changes {label}[{index}] between the two canonical "
                        f"applications ({value_before} -> {value_after}); V1 has no "
                        "channel for that component and refuses to guess one"
                    )
                differences[(name, component)] = (value_before, value_after)
    return differences


def verify_union(plan: dict, scene: dict) -> dict:
    """Refuse any union scene the plan does not fully and truthfully describe.

    Raises:
        MotionApplyError: On a missing object, a drifted canonical value, or a
            canonical difference no directive accounts for.
    """
    before_names = set(scene["static_before"])
    after_names = set(scene["static_after"])
    union_names = set(scene["union"])
    expected = before_names | after_names
    if union_names != expected:
        missing = sorted(expected - union_names)
        extra = sorted(union_names - expected)
        raise MotionApplyError(
            f"the union scene is not the union of both endpoints: missing {missing}, "
            f"unexpected {extra}"
        )
    for name in sorted(after_names):
        if scene["union"][name] != scene["static_after"][name]:
            raise MotionApplyError(
                f"{name} does not carry its canonical after-state in the union scene"
            )
    for name in sorted(before_names - after_names):
        if scene["union"][name] != scene["static_before"][name]:
            raise MotionApplyError(
                f"{name} does not carry its canonical before-state in the union scene"
            )
    if scene["union_materials"] != scene["materials_after"]:
        raise MotionApplyError("the union scene's material values are not the after-state")

    differences = _canonical_differences(scene)
    covered: dict[tuple[str, str], dict] = {}
    for directive in plan["directives"]:
        if directive["value_space"] != "canonical_offset":
            continue
        target = directive["target"]
        if target["kind"] != "object_transform":
            raise MotionApplyError(
                f"canonical_offset is only defined for object transforms, got {target}"
            )
        covered[(target["object"], target["component"])] = directive
    if set(covered) != set(differences):
        raise MotionApplyError(
            "the plan does not describe the canonical differences between the two "
            f"static worlds: uncovered {sorted(set(differences) - set(covered))}, "
            f"unwarranted {sorted(set(covered) - set(differences))}"
        )
    for key, directive in sorted(covered.items()):
        value_before, value_after = differences[key]
        scale = max(abs(value_before), abs(value_after))
        if not _agrees(directive["from_value"], value_before - value_after, scale):
            raise MotionApplyError(
                f"{key[0]}.{key[1]}: the plan says the before-state sits "
                f"{directive['from_value']} from canonical, the scene says "
                f"{value_before - value_after}"
            )

    for directive in plan["directives"]:
        target = directive["target"]
        if target["kind"] != "material_node_value":
            continue
        channel = (target["material"], target["node"], target["socket"])
        measured_before = scene["materials_before"].get(channel)
        measured_after = scene["materials_after"].get(channel)
        if measured_before is None or measured_after is None:
            raise MotionApplyError(f"the plan drives an unknown material channel {channel}")
        if not _agrees(directive["from_value"], measured_before, measured_before):
            raise MotionApplyError(
                f"{channel}: the plan says the before-value is {directive['from_value']}, "
                f"the canonical scene says {measured_before}"
            )
        if not _agrees(directive["to_value"], measured_after, measured_after):
            raise MotionApplyError(
                f"{channel}: the plan says the after-value is {directive['to_value']}, "
                f"the canonical scene says {measured_after}"
            )
    driven = {
        (d["target"]["material"], d["target"]["node"], d["target"]["socket"])
        for d in plan["directives"]
        if d["target"]["kind"] == "material_node_value"
    }
    for channel, value_before in sorted(scene["materials_before"].items()):
        if channel in driven:
            continue
        if abs(value_before - scene["materials_after"][channel]) > CANONICAL_EPSILON:
            raise MotionApplyError(
                f"material channel {channel} differs between the canonical endpoints "
                "but no directive animates it"
            )
    return {
        "before_objects": len(before_names),
        "after_objects": len(after_names),
        "union_objects": len(union_names),
        "before_only": len(before_names - after_names),
        "after_only": len(after_names - before_names),
        "reconciled_components": len(differences),
    }


def _require_action(holder, label: str) -> bpy.types.Action:
    """Name the freshly created action deterministically, or refuse."""
    action = holder.animation_data.action
    wanted = f"{MOTION_ACTION_PREFIX}{label}"
    if len(wanted.encode("utf-8")) > MAX_ID_NAME_BYTES:
        raise MotionApplyError(
            f"action name {wanted!r} exceeds Blender's {MAX_ID_NAME_BYTES}-byte "
            "identifier limit and would be silently truncated"
        )
    if action.name != wanted:
        action.name = wanted
        if action.name != wanted:
            raise MotionApplyError(f"action {wanted!r} collides with an existing datablock")
    return action


def _set_boolean(holder, data_path: str, _index: int, value: float) -> None:
    """Write one animatable boolean before it is keyed."""
    setattr(holder, data_path, bool(round(value)))


def _set_component(holder, data_path: str, index: int, value: float) -> None:
    """Write one component of an animatable vector before it is keyed."""
    getattr(holder, data_path)[index] = value


def _set_socket(holder, data_path: str, _index: int, value: float) -> None:
    """Write one node socket's default value before it is keyed."""
    holder.path_resolve(data_path.rsplit(".", 1)[0]).default_value = value


def _write_curve(
    holder, label: str, data_path: str, index: int, keys, interpolation: str, setter
) -> int:
    """Create exactly one F-curve carrying exactly these keys.

    The keys are written through ``keyframe_insert`` so Blender's own slotted
    action machinery stays authoritative, then every keyframe's interpolation
    is overwritten explicitly -- a step channel becomes CONSTANT and a sampled
    channel becomes LINEAR between samples the project computed itself. The
    Bezier default never survives.

    Raises:
        MotionApplyError: If a curve already exists on this property, which
            would mean the plan drives one property twice.
    """
    slot = max(index, 0)
    animation = holder.animation_data
    existing = (
        None
        if animation is None or animation.action is None
        else (animation.action.fcurves.find(data_path, index=slot))
    )
    if existing is not None:
        raise MotionApplyError(f"{label}: {data_path}[{slot}] already carries animation")
    for frame, value in keys:
        setter(holder, data_path, index, value)
        if index < 0:
            holder.keyframe_insert(data_path, frame=frame)
        else:
            holder.keyframe_insert(data_path, index=index, frame=frame)
    action = _require_action(holder, label)
    curve = action.fcurves.find(data_path, index=slot)
    if curve is None:
        raise MotionApplyError(f"{label}: {data_path}[{slot}] produced no F-curve")
    if len(curve.keyframe_points) != len(keys):
        raise MotionApplyError(
            f"{label}: {data_path}[{slot}] holds {len(curve.keyframe_points)} keys, "
            f"the plan asked for {len(keys)}"
        )
    blender_interpolation = "CONSTANT" if interpolation == "step" else "LINEAR"
    for keyframe in curve.keyframe_points:
        keyframe.interpolation = blender_interpolation
        keyframe.easing = "AUTO"
    curve.update()
    return len(curve.keyframe_points)


def _presence_keys(
    timeline: dict, appears: bool, member_start: int, member_end: int
) -> list[tuple[int, float]]:
    """Boolean hide keys for one appearing or vanishing object.

    An object that appears must exist for the whole of its own reveal, so it
    is unhidden at the START of its window. An object that vanishes must
    survive until its conceal completes, so it is hidden at the END of its
    window. Both are constant steps; nothing fades.
    """
    if appears:
        return [(timeline["start_frame"], 1.0), (member_start, 0.0)]
    return [(timeline["start_frame"], 0.0), (member_end, 1.0)]


def _group_members(prefix: str) -> list[str]:
    """Every object belonging to one semantic group, in stable name order."""
    return sorted(obj.name for obj in bpy.data.objects if obj.name.startswith(f"{prefix}__"))


def _animate_presence(
    directive: dict, names: list[str], timeline: dict, canonical: dict[str, tuple]
) -> dict:
    """Hide/reveal a set of objects, optionally lifting each into place."""
    appears = directive["to_value"] > directive["from_value"]
    rise = directive["rise_metres"] if appears else 0.0
    span = directive.get("member_span_frames")
    curves = 0
    keys = 0
    for index, name in enumerate(names):
        obj = bpy.data.objects.get(name)
        if obj is None:
            raise MotionApplyError(f"the plan animates {name!r}, which the scene does not hold")
        if span is None:
            member_start, member_end = directive["start_frame"], directive["end_frame"]
        else:
            member_start, member_end = staged_frames(
                (directive["start_frame"], directive["end_frame"]),
                span,
                index,
                len(names),
                staged=directive["strategy"] == "staged",
            )
        for data_path in PRESENCE_PATHS:
            curves += 1
            keys += _write_curve(
                obj,
                obj.name,
                data_path,
                -1,
                _presence_keys(timeline, appears, member_start, member_end),
                "step",
                _set_boolean,
            )
        if rise > 0.0:
            canonical_z = canonical[name][0][2]
            curves += 1
            keys += _write_curve(
                obj,
                obj.name,
                "location",
                2,
                [
                    (frame, canonical_z + offset)
                    for frame, offset in keyframes(
                        directive["interpolation"],
                        directive["samples"],
                        -rise,
                        0.0,
                        member_start,
                        member_end,
                    )
                ],
                directive["interpolation"],
                _set_component,
            )
    return {"curves": curves, "keys": keys, "objects": len(names)}


def _anchor(
    directive: dict, name: str, component: str, base: float, before_state: dict | None
) -> float:
    """The exact first-key value of one reconciling transform directive.

    ``base + from_value`` is arithmetically right but is computed in double
    precision and then stored as a float32, which can land one unit in the
    last place away from the value the canonical before-application actually
    stored -- about two micrometres at city scale. Where the object exists in
    the measured before-state, its measured value is used verbatim instead, so
    the first frame is BIT-identical to the static before-world rather than
    merely indistinguishable from it. The plan still governs what moves, when,
    and how: :func:`verify_union` has already proved the two agree.
    """
    fallback = base + directive["from_value"]
    if before_state is None or name not in before_state:
        return fallback
    attribute, index = COMPONENT_PATHS[component]
    measured = before_state[name][0 if attribute == "location" else 1][index]
    if not _agrees(fallback, measured, measured):
        raise MotionApplyError(
            f"{name}.{component}: the plan's first key {fallback} disagrees with the "
            f"canonical before-state {measured}"
        )
    return measured


def apply_motion_plan(
    plan: dict, canonical: dict[str, tuple], before_state: dict | None = None
) -> dict:
    """Create every F-curve the plan authorises, and nothing else.

    ``canonical`` is the measured union scene: the applier never re-reads live
    transforms, because after the first key is written they are no longer the
    canonical values. ``before_state`` is the measured canonical before-scene,
    used only to anchor reconciling keys exactly (see :func:`_anchor`).

    Raises:
        MotionApplyError: On any target the scene cannot satisfy.
    """
    require_supported_blender()
    removed = clear_motion_animation()
    timeline = plan["timeline"]
    scene = bpy.context.scene
    scene.frame_start = timeline["start_frame"]
    scene.frame_end = timeline["end_frame"]
    scene.render.fps = timeline["fps"]

    animated_objects: set[str] = set()
    animated_materials: set[str] = set()
    curves = 0
    keys = 0
    for directive in plan["directives"]:
        target = directive["target"]
        kind = target["kind"]
        if kind == "material_node_value":
            node_tree, data_path = _socket_of(target["material"], target["node"], target["socket"])
            curves += 1
            keys += _write_curve(
                node_tree,
                f"mat__{target['material'].removeprefix('LD_MAT__')}",
                data_path,
                -1,
                sampled_keyframes(directive),
                directive["interpolation"],
                _set_socket,
            )
            animated_materials.add(target["material"])
        elif kind in ("object_presence", "object_group_presence"):
            names = (
                _group_members(target["prefix"])
                if kind == "object_group_presence"
                else [target["object"]]
            )
            if not names:
                raise MotionApplyError(
                    f"the plan animates group {target.get('prefix')!r}, which holds no objects"
                )
            report = _animate_presence(directive, names, timeline, canonical)
            curves += report["curves"]
            keys += report["keys"]
            animated_objects.update(names)
        elif kind == "object_transform":
            name = target["object"]
            obj = bpy.data.objects.get(name)
            if obj is None:
                raise MotionApplyError(f"the plan animates {name!r}, which the scene does not hold")
            attribute, index = COMPONENT_PATHS[target["component"]]
            base = canonical[name][0 if attribute == "location" else 1][index]
            sampled = sampled_keyframes(directive)
            values = [(frame, base + offset) for frame, offset in sampled]
            values[0] = (
                values[0][0],
                _anchor(directive, name, target["component"], base, before_state),
            )
            curves += 1
            keys += _write_curve(
                obj, obj.name, attribute, index, values, directive["interpolation"], _set_component
            )
            animated_objects.add(name)
        else:
            raise MotionApplyError(f"unknown directive target kind {kind!r}")

    scene.frame_set(timeline["start_frame"])
    return {
        "cleared_actions": removed,
        "animated_objects": len(animated_objects),
        "animated_materials": len(animated_materials),
        "fcurves": curves,
        "keyframes": keys,
        "actions": len(
            [action for action in bpy.data.actions if action.name.startswith(MOTION_ACTION_PREFIX)]
        ),
        "animated_object_names": sorted(animated_objects),
    }


def require_no_stray_animation(authorised: set[str]) -> None:
    """Refuse if anything outside the authorised set carries Phase 17 motion.

    Raises:
        MotionApplyError: If the static city, a camera, or an unauthorised
            material gained animation data.
    """
    for obj in bpy.data.objects:
        animation = obj.animation_data
        if animation is None or animation.action is None:
            continue
        if not animation.action.name.startswith(MOTION_ACTION_PREFIX):
            continue
        if obj.name not in authorised:
            raise MotionApplyError(f"{obj.name} carries motion no directive authorised")


def build_motion_scene(
    spec_path: str | Path,
    production_path: str | Path,
    before_path: str | Path,
    after_path: str | Path,
    motion_spec_path: str | Path,
    style: str = "dna",
    *,
    lighting_profile: str = "dna",
) -> dict:
    """Build the world, plan the motion, verify it, and animate it. One call.

    ``lighting_profile`` selects an ADDITIVE lighting lane on top of the
    style's own lighting (mirroring the ``camera_profile`` precedent):
    ``"dna"`` (default) adds nothing, ``"dna_daylight"`` applies the
    Director-revision late-morning daylight lane. The lane never touches
    exposure/view transform/look, which stay pinned by the render-profile
    digest.

    Returns a report holding the plan, the union verification, the motion
    metrics, and the geography snapshot taken before any F-curve existed.
    """
    import build_master_scene
    import build_production_world

    require_supported_blender()
    build_master_scene.build_master_scene(spec_path, style=style, lighting_profile=lighting_profile)
    production = build_production_world.add_production_world(
        spec_path, production_path, style=style
    )
    scene = build_union_scene(spec_path, before_path, after_path, style)
    geography = geography_snapshot()

    motion_spec = load_motion_time_spec(motion_spec_path)
    plan = plan_motion(
        load_render_export(before_path),
        load_render_export(after_path),
        scene["master_spec"],
        motion_spec,
    )
    verification = verify_union(plan, scene)
    metrics = apply_motion_plan(plan, scene["union"], scene["static_before"])
    require_no_stray_animation(set(metrics["animated_object_names"]))
    if geography_snapshot() != geography:
        raise MotionApplyError("the persistent city moved while motion was being applied")
    return {
        "plan": plan,
        "motion_spec": motion_spec,
        "union": verification,
        "metrics": metrics,
        "geography": geography,
        "production": production,
        "scene": scene,
    }


def main() -> None:
    """Command-line entry: build one animated scene and optionally save it."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--production", required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--motion", required=True)
    parser.add_argument("--style", default="dna")
    parser.add_argument(
        "--lighting-profile",
        default="dna",
        help="lighting lane: 'dna' (default, today's exact lighting) or 'dna_daylight'",
    )
    parser.add_argument("--save", default="")
    arguments = parser.parse_args(argv)
    report = build_motion_scene(
        arguments.spec,
        arguments.production,
        arguments.before,
        arguments.after,
        arguments.motion,
        style=arguments.style,
        lighting_profile=arguments.lighting_profile,
    )
    metrics = report["metrics"]
    print(
        f"LD_MOTION: {report['plan']['summary']['directive_count']} directives, "
        f"{metrics['animated_objects']} objects, {metrics['fcurves']} F-curves, "
        f"{metrics['keyframes']} keyframes"
    )
    if arguments.save.strip():
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(arguments.save).resolve()))


if __name__ == "__main__":
    main()
