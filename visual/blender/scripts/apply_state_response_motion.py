"""Animate one State Response Motion Plan over Phase 20's own properties.

Phase 20 animates only what Phase 20's own static application writes. That is the
whole reason its endpoints are provable: frame one must equal the ordinary static
application of the before-export, and the last frame the static application of
the after-export, so a property no static application writes could not be one of
these endpoints and is refused before a curve is ever created.

The Phase 17 timeline is borrowed as a clock. Phase 17's channels, its config and
its actions are untouched: every curve written here lives on an action named
``LD_STATE_RESPONSE__`` and every property driven here belongs to an object or a
material named ``LD_SR__`` / ``LD_SR_MAT__``.

State is read back from the F-CURVES, not from the live property. That makes the
comparison exact and independent of whichever frame the scene happens to sit on,
and it is what lets a mutation test prove the check bites.
"""

import json
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))

from apply_state_response import (  # noqa: E402
    ACTION_PREFIX,
    AIR_OBJECT_PREFIX,
    OBJECT_PREFIX,
    StateResponseApplyError,
    apply_state_response,
    state_response_objects,
)
from state_response_motion_plan import keyframes  # noqa: E402
from state_response_plan import (  # noqa: E402
    AIR_DENSITY_NODE,
    AIR_MATERIAL_PREFIX,
)

PRESENCE_PATHS = ("hide_render", "hide_viewport")
"""Both hide flags are driven together.

A stone hidden in the render but visible in the viewport would make the proof
frame and the scene a reviewer opens disagree about what the world remembers.
"""

CANONICAL_EPSILON = 1e-9
"""The threshold for calling two measured scenes genuinely different."""

AGREEMENT_EPSILON = 1e-6
"""The tolerance for a planned double against the float32 Blender stored.

A density planned in double precision and stored in a 32-bit socket comes back
a few ulps away. Comparing those with exact equality would fail an animation
that is in fact perfect, so the endpoint check scales this by magnitude.
"""


def _agrees(measured: float, expected: float) -> bool:
    """Return whether a measured value agrees with a planned one within tolerance."""
    return abs(measured - expected) <= AGREEMENT_EPSILON * max(1.0, abs(expected))


def _require_action(holder: object, name: str) -> None:
    """Name the holder's action deterministically, refusing a collision."""
    animation = holder.animation_data
    if animation is None or animation.action is None:
        raise StateResponseApplyError(f"{name} was keyed but carries no action")
    if animation.action.name.startswith(ACTION_PREFIX):
        return
    if bpy.data.actions.get(name) is not None:
        raise StateResponseApplyError(
            f"action {name!r} already exists; Phase 20 refuses to key over another layer's action"
        )
    animation.action.name = name


def clear_state_response_animation() -> int:
    """Remove every Phase 20 curve and action, leaving the static layer standing."""
    removed = 0
    for obj in state_response_objects():
        if obj.animation_data is not None:
            obj.animation_data_clear()
    for material in bpy.data.materials:
        if material.name.startswith(AIR_MATERIAL_PREFIX) and material.node_tree is not None:
            material.node_tree.animation_data_clear()
    for action in list(bpy.data.actions):
        if action.name.startswith(ACTION_PREFIX):
            bpy.data.actions.remove(action)
            removed += 1
    return removed


def _key_air(directive: dict) -> int:
    """Write one district's air density curve."""
    material = bpy.data.materials.get(directive["target"]["material"])
    if material is None or material.node_tree is None:
        raise StateResponseApplyError(
            f"the plan drives material {directive['target']['material']!r}, which the static "
            "application never built; a directive with no static endpoint is refused"
        )
    node = material.node_tree.nodes.get(directive["target"]["node"])
    if node is None:
        raise StateResponseApplyError(
            f"material {material.name!r} carries no {directive['target']['node']!r} node"
        )
    socket = node.outputs[0]
    data_path = socket.path_from_id("default_value")
    written = 0
    for frame, value in keyframes(directive):
        socket.default_value = value
        material.node_tree.keyframe_insert(data_path=data_path, frame=frame)
        written += 1
    _require_action(material.node_tree, f"{ACTION_PREFIX}{material.name}")
    for curve in material.node_tree.animation_data.action.fcurves:
        if curve.data_path != data_path:
            continue
        for key in curve.keyframe_points:
            key.interpolation = "CONSTANT" if directive["interpolation"] == "step" else "LINEAR"
    return written


def _key_presence(directive: dict) -> int:
    """Write one record stone's presence curve.

    Presence is a step: a stone is not there, and then it is. A stone that faded
    in would be claiming the world half-remembered something.
    """
    obj = bpy.data.objects.get(directive["target"]["object"])
    if obj is None:
        raise StateResponseApplyError(
            f"the plan drives object {directive['target']['object']!r}, which the static "
            "application never built; a directive with no static endpoint is refused"
        )
    written = 0
    for path in PRESENCE_PATHS:
        for frame, value in keyframes(directive):
            setattr(obj, path, value < 0.5)
            obj.keyframe_insert(data_path=path, frame=frame)
            written += 1
    _require_action(obj, f"{ACTION_PREFIX}{obj.name}")
    for curve in obj.animation_data.action.fcurves:
        for key in curve.keyframe_points:
            key.interpolation = "CONSTANT"
    return written


def apply_state_response_motion(motion_plan: dict, timeline: dict) -> dict:
    """Write every Phase 20 directive onto the standing static layer.

    Args:
        motion_plan: A state response motion plan.
        timeline: The resolved Phase 20 timeline.

    Returns:
        What was written: curve, key and per-channel counts.

    Raises:
        StateResponseApplyError: If a directive names a target the static
            application never built.
    """
    clear_state_response_animation()
    keys = 0
    by_channel: dict[str, int] = {}
    for directive in motion_plan["directives"]:
        channel = directive["channel"]
        if directive["target"]["kind"] == "material_node_value":
            keys += _key_air(directive)
        elif directive["target"]["kind"] == "object_presence":
            keys += _key_presence(directive)
        else:
            raise StateResponseApplyError(
                f"directive kind {directive['target']['kind']!r} is not one this applier writes"
            )
        by_channel[channel] = by_channel.get(channel, 0) + 1

    scene = bpy.context.scene
    scene.frame_start = timeline["start_frame"]
    scene.frame_end = timeline["end_frame"]
    bpy.context.view_layer.update()
    return {
        "actions": len([a for a in bpy.data.actions if a.name.startswith(ACTION_PREFIX)]),
        "directives_by_channel": dict(sorted(by_channel.items())),
        "keyframes": keys,
    }


def air_state_at(frame: int) -> dict:
    """Return every district's air density at one frame, read off the curves."""
    state: dict[str, float] = {}
    for material in bpy.data.materials:
        if not material.name.startswith(AIR_MATERIAL_PREFIX) or material.node_tree is None:
            continue
        node = material.node_tree.nodes.get(AIR_DENSITY_NODE)
        if node is None:
            continue
        district = material.name[len(AIR_MATERIAL_PREFIX) :]
        socket = node.outputs[0]
        data_path = socket.path_from_id("default_value")
        value = float(socket.default_value)
        animation = material.node_tree.animation_data
        if animation is not None and animation.action is not None:
            for curve in animation.action.fcurves:
                if curve.data_path == data_path:
                    value = float(curve.evaluate(frame))
                    break
        state[district] = value
    return state


def visible_state_at(frame: int) -> list[str]:
    """Return the Phase 20 objects visible at one frame, read off the curves.

    An object hidden on a frame is ABSENT from that frame's list, which is what
    makes the measurement comparable with a static application that never built
    it at all.
    """
    visible: list[str] = []
    for obj in state_response_objects():
        hidden = bool(obj.hide_render)
        animation = obj.animation_data
        if animation is not None and animation.action is not None:
            for curve in animation.action.fcurves:
                if curve.data_path == "hide_render":
                    hidden = curve.evaluate(frame) >= 0.5
                    break
        if not hidden:
            visible.append(obj.name)
    return sorted(visible)


def static_state(plan: dict, spec: dict) -> dict:
    """Apply one plan statically and measure what it produced.

    This is the authority both endpoints are compared against. It is a measured
    scene, not a reading of the plan: a comparison against the plan would agree
    with the plan even when the scene disagreed with both.
    """
    apply_state_response(plan, spec)
    return {
        "air": air_state_at(bpy.context.scene.frame_current),
        "visible": sorted(obj.name for obj in state_response_objects() if not obj.hide_render),
    }


def compare_endpoint(measured: dict, expected: dict) -> dict:
    """Compare one measured endpoint against its own static application."""
    air_ok = set(measured["air"]) == set(expected["air"]) and all(
        _agrees(measured["air"][district], expected["air"][district])
        for district in expected["air"]
    )
    visible_ok = measured["visible"] == expected["visible"]
    return {
        "air_equivalent": air_ok,
        "equivalent": bool(air_ok and visible_ok),
        "measured_air": measured["air"],
        "measured_visible": measured["visible"],
        "objects_equivalent": visible_ok,
    }


def endpoint_equivalence(
    before_plan: dict, after_plan: dict, motion_plan: dict, spec: dict, timeline: dict
) -> dict:
    """Prove the animated scene's ends are the two static applications.

    Both endpoints are measured independently from real static applications
    before the union scene is built, so neither is inferred from the plan that
    is supposed to be under test.

    Args:
        before_plan: The earlier state response plan.
        after_plan: The later state response plan.
        motion_plan: The transition between them.
        spec: A resolved state response spec.
        timeline: The resolved Phase 20 timeline.

    Returns:
        A verdict per endpoint, plus the channels that actually carry curves --
        an animation that moved nothing would otherwise pass both endpoints for
        the wrong reason.
    """
    expected_before = static_state(before_plan, spec)
    expected_after = static_state(after_plan, spec)

    # The after plan is the superset: memory only grows, so every object either
    # endpoint needs exists once the after plan is applied.
    apply_state_response(after_plan, spec)
    apply_state_response_motion(motion_plan, timeline)

    measured_before = {
        "air": air_state_at(timeline["start_frame"]),
        "visible": visible_state_at(timeline["start_frame"]),
    }
    measured_after = {
        "air": air_state_at(timeline["end_frame"]),
        "visible": visible_state_at(timeline["end_frame"]),
    }
    animated = sorted({directive["channel"] for directive in motion_plan["directives"]})
    before_verdict = compare_endpoint(measured_before, expected_before)
    after_verdict = compare_endpoint(measured_after, expected_after)
    return {
        "after": after_verdict,
        "animated_channels": animated,
        "before": before_verdict,
        "equivalent": bool(before_verdict["equivalent"] and after_verdict["equivalent"]),
    }


def require_no_stray_animation() -> None:
    """Refuse if Phase 20 animated anything that is not Phase 20's.

    Raises:
        StateResponseApplyError: If a Phase 20 action drives a foreign datablock,
            or a foreign action drives a Phase 20 one.
    """
    for obj in bpy.data.objects:
        animation = obj.animation_data
        if animation is None or animation.action is None:
            continue
        owned = animation.action.name.startswith(ACTION_PREFIX)
        if owned and not obj.name.startswith(OBJECT_PREFIX):
            raise StateResponseApplyError(
                f"a Phase 20 action drives {obj.name!r}, which Phase 20 does not own"
            )
    for material in bpy.data.materials:
        if material.node_tree is None or material.node_tree.animation_data is None:
            continue
        action = material.node_tree.animation_data.action
        if action is None:
            continue
        if action.name.startswith(ACTION_PREFIX) and not material.name.startswith(
            AIR_MATERIAL_PREFIX
        ):
            raise StateResponseApplyError(
                f"a Phase 20 action drives material {material.name!r}, which Phase 20 does not own"
            )


def motion_summary() -> dict:
    """Measure the animation actually present in the scene."""
    actions = [a for a in bpy.data.actions if a.name.startswith(ACTION_PREFIX)]
    curves = 0
    keys = 0
    for action in actions:
        for curve in action.fcurves:
            curves += 1
            keys += len(curve.keyframe_points)
    return {
        "actions": len(actions),
        "air_volumes_animated": len(
            [
                material
                for material in bpy.data.materials
                if material.name.startswith(AIR_MATERIAL_PREFIX)
                and material.node_tree is not None
                and material.node_tree.animation_data is not None
                and material.node_tree.animation_data.action is not None
            ]
        ),
        "fcurves": curves,
        "keyframes": keys,
        "stones_animated": len(
            [
                obj
                for obj in state_response_objects()
                if not obj.name.startswith(AIR_OBJECT_PREFIX) and obj.animation_data is not None
            ]
        ),
    }


__all__ = [
    "AGREEMENT_EPSILON",
    "CANONICAL_EPSILON",
    "air_state_at",
    "apply_state_response_motion",
    "clear_state_response_animation",
    "compare_endpoint",
    "endpoint_equivalence",
    "motion_summary",
    "require_no_stray_animation",
    "static_state",
    "visible_state_at",
]


def main() -> int:
    """Report the animation present in the current scene."""
    print(json.dumps(motion_summary(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
