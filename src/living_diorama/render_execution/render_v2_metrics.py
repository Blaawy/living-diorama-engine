"""Pure render-integration metrics for a V2 movement shot plan.

This module answers one question: has a V2 movement shot plan been genuinely
integrated into the render pipeline? ``render_integration_metrics`` is pure and
side-effect free. It derives, from the shot plan and the render plan alone,
the same counts the engine's ``movement_metrics`` reports, and then decides
``render_integrated`` from three facts the render plan itself carries:

* every frame of a non-STATIC movement shot is planned on the derived movement
  camera identity (``movement_camera_name(shot_id)``), never on a forged one;
* every frame of every other shot is planned on the shot's own fixed anchor;
* the render plan binds ``movement_catalogue_sha256`` equal to the digest this
  module recomputes from the shot plan.

``render_integrated: True`` therefore means the documents the pipeline actually
validates -- the render plan and manifest -- carry the movement identities the
movement applier creates, end to end.
"""

from living_diorama.cinematic.cinematic_schema_v2 import reason_for_move_is_bound
from living_diorama.cinematic.cinematic_spec import (
    movement_camera_name,
    movement_catalogue_sha256,
)


def render_integration_metrics(shot_plan: object, render_plan: object) -> dict[str, object]:
    """Return the render-integration metrics for one shot plan / render plan pair.

    Args:
        shot_plan: A Shot Direction Plan document, V1 or V2 shape.
        render_plan: The Episode Render Plan document derived from it.

    Returns:
        A dict with ``shot_count``, ``static_shot_count``, ``moving_shot_count``,
        ``movement_type_histogram``, ``unmotivated_movement_violation_count`` and
        the boolean ``render_integrated``.

    Raises:
        TypeError: If either argument is not a document carrying the expected
            lists.
    """
    if type(shot_plan) is not dict or type(shot_plan.get("shots")) is not list:
        raise TypeError("render integration metrics require a shot direction plan document")
    if type(render_plan) is not dict or type(render_plan.get("frames")) is not list:
        raise TypeError("render integration metrics require an episode render plan document")

    shots = shot_plan["shots"]
    shot_count = len(shots)
    moving_shot_count = 0
    histogram: dict[str, int] = {}
    violations = 0
    movement_by_shot: dict[str, str] = {}
    for shot in shots:
        movement = shot.get("camera_movement")
        if movement is None:
            continue
        movement_type = movement["movement_type"]
        histogram[movement_type] = histogram.get(movement_type, 0) + 1
        if movement_type != "STATIC":
            moving_shot_count += 1
            movement_by_shot[shot["shot_id"]] = movement_camera_name(shot["shot_id"])
        if not reason_for_move_is_bound(movement.get("reason_for_move"), shot):
            violations += 1

    integrated = True
    bound_movement_digest = render_plan["source"].get("movement_catalogue_sha256")
    if movement_by_shot and bound_movement_digest != movement_catalogue_sha256(shot_plan):
        integrated = False
    shot_by_id = {shot["shot_id"]: shot for shot in shots}
    for entry in render_plan["frames"]:
        shot = shot_by_id.get(entry["shot_id"])
        if shot is None:
            integrated = False
            break
        if entry["shot_id"] in movement_by_shot:
            expected = movement_by_shot[entry["shot_id"]]
        else:
            expected = shot["camera_anchor_id"]
        if entry["camera_anchor_id"] != expected:
            integrated = False
            break

    return {
        "shot_count": shot_count,
        "static_shot_count": shot_count - moving_shot_count,
        "moving_shot_count": moving_shot_count,
        "movement_type_histogram": dict(sorted(histogram.items())),
        "unmotivated_movement_violation_count": violations,
        "render_integrated": integrated,
    }
