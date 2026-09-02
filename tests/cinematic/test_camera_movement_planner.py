r"""The camera movement planner: purposeful, deterministic, comfortable.

These tests drive the planner over (a) the genuine V1 plans the repo's own
planner produces and (b) a synthetic-but-structurally-identical 720-frame
EP1-scale plan, because the task's real 720-frame gate plan at
``_LIVING_DIORAMA_TOOLS\phase23_candidate\gate\shot_direction_plan_ep0_to_ep1.json``
does not exist in this workspace (``tools/`` holds only phase15_proof and
phase17_motion). The synthetic plan is explicitly labelled as such everywhere
it is used.
"""

import copy
import json
from typing import Any

import pytest

from living_diorama.cinematic import (
    build_shot_direction_plan_document,
    validate_shot_direction_plan,
)
from living_diorama.cinematic.camera_movement_planner import (
    MAX_TARGET_MOVEMENTS,
    MIN_TARGET_MOVEMENTS,
    movement_metrics,
    per_frame_delta_bound,
    plan_camera_movements,
    sample_movement_path,
)
from living_diorama.cinematic.cinematic_schema_v2 import (
    reason_for_move_is_bound,
    validate_shot_direction_plan_v2,
)
from living_diorama.cinematic.cinematic_spec import catalogue_sha256

# --------------------------------------------------------------------------
# Synthetic 720-frame EP1-scale plan (structurally identical to a V1 plan)
# --------------------------------------------------------------------------


def synthetic_720_shot_plan() -> dict[str, Any]:
    """A synthetic-but-structurally-identical 720-frame transition shot plan.

    Same top-level shape, same eight-key shots, same closed vocabularies, same
    tiling/adjacency/loop-closure rules as a genuine V1 plan -- but on a
    720-frame clock whose digest is synthetic, so the repo's validator (which
    pins the canonical 193-frame clock) refuses it only at the source-digest
    step. That is the one deliberate deviation, and it is stated here.
    """

    def beat(shot_id, anchor, start, end, beats, reason, emphasis):
        return {
            "camera_anchor_id": anchor,
            "emphasis": emphasis,
            "end_frame": end,
            "kind": "BEAT",
            "reason_code": reason,
            "shot_id": shot_id,
            "source_beat_ids": beats,
            "start_frame": start,
        }

    shots = [
        {
            "camera_anchor_id": "CAM_HERO_WORLD",
            "emphasis": None,
            "end_frame": 24,
            "kind": "ESTABLISHING",
            "reason_code": "NEUTRAL_ESTABLISHING",
            "shot_id": "shot_0001",
            "source_beat_ids": [],
            "start_frame": 1,
        },
        beat("shot_0002", "CAM_SEAL_DETAIL", 25, 120, ["beat_0001"], "BEAT_KIND_RULE", "PRIMARY"),
        beat(
            "shot_0003", "CAM_SCAR_DETAIL", 121, 192, ["beat_0002"], "BEAT_KIND_RULE", "SECONDARY"
        ),
        beat("shot_0004", "CAM_HERO_SCAR", 193, 288, ["beat_0003"], "BEAT_KIND_RULE", "PRIMARY"),
        beat("shot_0005", "CAM_P16_URBAN", 289, 384, ["beat_0004"], "BEAT_KIND_RULE", "PRIMARY"),
        beat(
            "shot_0006", "CAM_HERO_WORLD", 385, 456, ["beat_0005"], "UNKNOWN_BEAT_KIND", "SECONDARY"
        ),
        beat(
            "shot_0007",
            "CAM_SEAL_DETAIL",
            457,
            552,
            ["beat_0006", "beat_0007"],
            "ADJACENT_SAME_ANCHOR_MERGED",
            "PRIMARY",
        ),
        beat("shot_0008", "CAM_P16_URBAN", 553, 600, ["beat_0008"], "BEAT_KIND_RULE", "SECONDARY"),
        beat(
            "shot_0009",
            "CAM_P16_SCAR_CONTEXT",
            601,
            648,
            ["beat_0009"],
            "BEAT_KIND_RULE",
            "PRIMARY",
        ),
        {
            "camera_anchor_id": "CAM_HERO_WORLD",
            "emphasis": None,
            "end_frame": 720,
            "kind": "ESTABLISHING",
            "reason_code": "NEUTRAL_ESTABLISHING",
            "shot_id": "shot_0010",
            "source_beat_ids": [],
            "start_frame": 649,
        },
    ]
    return {
        "format": "living_diorama_shot_direction_plan",
        "schema_version": 1,
        "shots": shots,
        "source": {
            "catalogue_sha256": catalogue_sha256(),
            "episode": 1,
            "mode": "transition",
            "motion_time_format": "living_diorama_motion_time",
            "motion_time_schema_version": 1,
            # Synthetic clock digest: the 720-frame timeline is not the repo's
            # canonical 193-frame Phase 17 clock, so its digest cannot be the
            # pinned canonical one. Stated, never hidden.
            "motion_time_sha256": "ab" * 32,
            "previous_episode": 0,
            "story_plan_sha256": "cd" * 32,
            "story_schema_version": 1,
        },
        "timeline": {
            "end_frame": 720,
            "end_hold_frames": 47,
            "fps": 24,
            "start_frame": 1,
            "start_hold_frames": 24,
            "transition_end": 673,
            "transition_frames": 648,
            "transition_start": 25,
        },
        "unshown": [],
    }


@pytest.fixture
def plan_ep1(story_ep0_to_ep1: dict[str, Any], motion_time: bytes) -> dict[str, Any]:
    """The genuine four-shot episode 0 -> 1 plan, cut on the canonical clock."""
    return build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)


@pytest.fixture
def synthetic_720() -> dict[str, Any]:
    """The synthetic-but-structurally-identical 720-frame EP1-scale plan."""
    return synthetic_720_shot_plan()


# ---------------------------------------------------------- synthetic shape


def test_the_synthetic_plan_is_structurally_v1_except_its_digest(
    synthetic_720: dict[str, Any],
) -> None:
    """The synthetic plan passes every V1 rule up to the pinned source digest."""
    with pytest.raises(ValueError, match="not the canonical Phase 17 source"):
        validate_shot_direction_plan(synthetic_720)


# --------------------------------------------------- never-moves/always-moves


def test_at_least_one_shot_moves_and_at_least_one_is_static(
    synthetic_720: dict[str, Any],
) -> None:
    """CAMERA_ALWAYS_MOVES and CAMERA_NEVER_MOVES both hold on the EP1 scale."""
    planned = plan_camera_movements(synthetic_720)
    metrics = movement_metrics(planned)
    assert metrics["moving_shot_count"] >= 1
    assert metrics["static_shot_count"] >= 1


def test_the_real_ep1_plan_also_mixes_movement_and_static(
    plan_ep1: dict[str, Any],
) -> None:
    """The genuine plan is not forced: it moves what its beats motivate."""
    planned = plan_camera_movements(plan_ep1)
    metrics = movement_metrics(planned)
    assert metrics["moving_shot_count"] >= 1
    assert 0 <= metrics["static_shot_count"] <= metrics["shot_count"]


# ------------------------------------------------------------ role diversity


def test_the_required_roles_are_all_present(synthetic_720: dict[str, Any]) -> None:
    """Establishing view, attention guide, hold, consequence push, closing wide."""
    planned = plan_camera_movements(synthetic_720)
    by_id = {shot["shot_id"]: shot for shot in planned["shots"]}
    assert by_id["shot_0001"]["camera_movement"]["movement_type"] == "REVEAL"
    assert by_id["shot_0002"]["camera_movement"]["movement_type"] == "PUSH_IN"
    assert by_id["shot_0005"]["camera_movement"]["movement_type"] == "TRACK"
    assert by_id["shot_0007"]["camera_movement"]["movement_type"] == "STATIC"
    assert by_id["shot_0010"]["camera_movement"]["movement_type"] == "PULL_OUT"
    # The wall consequence push lands on the first wall-anchored beat shot.
    assert by_id["shot_0003"]["camera_movement"]["movement_type"] == "PUSH_IN"
    # Shots the beat structure does not motivate stay exactly as V1 wrote them.
    assert "camera_movement" not in by_id["shot_0004"]
    assert "camera_movement" not in by_id["shot_0006"]
    assert "camera_movement" not in by_id["shot_0008"]
    assert "camera_movement" not in by_id["shot_0009"]


def test_the_movement_count_stays_in_the_target_range(synthetic_720: dict[str, Any]) -> None:
    """Roughly five to seven movement blocks, not one per shot."""
    planned = plan_camera_movements(synthetic_720)
    blocks = [s for s in planned["shots"] if s.get("camera_movement") is not None]
    assert MIN_TARGET_MOVEMENTS <= len(blocks) <= MAX_TARGET_MOVEMENTS


def test_the_planned_document_keeps_v1_identity_for_unmoved_shots(
    synthetic_720: dict[str, Any],
) -> None:
    """Unmoved shots carry exactly the eight V1 keys, nothing added."""
    from living_diorama.cinematic.cinematic_schema_v1 import SHOT_KEYS

    planned = plan_camera_movements(synthetic_720)
    for shot in planned["shots"]:
        if "camera_movement" not in shot:
            assert set(shot) == set(SHOT_KEYS), shot["shot_id"]


# ------------------------------------------------------- purpose derivation


def test_every_reason_for_move_is_mechanically_bound(synthetic_720: dict[str, Any]) -> None:
    """No movement exists whose reason names neither cause nor subject."""
    planned = plan_camera_movements(synthetic_720)
    for shot in planned["shots"]:
        movement = shot.get("camera_movement")
        if movement is None:
            continue
        assert reason_for_move_is_bound(movement["reason_for_move"], shot), shot["shot_id"]


def test_purpose_is_derived_from_the_real_reason_code(
    synthetic_720: dict[str, Any],
) -> None:
    """The reason_for_move text carries the shot's own reason code, not a template."""
    planned = plan_camera_movements(synthetic_720)
    by_id = {shot["shot_id"]: shot for shot in planned["shots"]}
    assert by_id["shot_0002"]["camera_movement"]["reason_for_move"].startswith("BEAT_KIND_RULE")
    assert by_id["shot_0007"]["camera_movement"]["reason_for_move"].startswith(
        "ADJACENT_SAME_ANCHOR_MERGED"
    )
    assert by_id["shot_0001"]["camera_movement"]["reason_for_move"].startswith(
        "NEUTRAL_ESTABLISHING"
    )


# --------------------------------------------------------------- determinism


def test_the_planner_is_deterministic_and_never_mutates_its_input(
    synthetic_720: dict[str, Any],
) -> None:
    """Same input, same assignment; the input document is untouched."""
    before = json.dumps(synthetic_720, sort_keys=True)
    first = plan_camera_movements(synthetic_720)
    second = plan_camera_movements(copy.deepcopy(synthetic_720))
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert json.dumps(synthetic_720, sort_keys=True) == before
    assert "camera_movement" not in synthetic_720["shots"][0]


def test_key_insertion_order_does_not_change_the_assignment(
    synthetic_720: dict[str, Any],
) -> None:
    """A dict built in a different key order is the same assignment."""

    def shuffle(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: shuffle(value[key]) for key in sorted(value, reverse=True)}
        if isinstance(value, list):
            return [shuffle(entry) for entry in value]
        return value

    straight = plan_camera_movements(synthetic_720)
    reordered = plan_camera_movements(shuffle(copy.deepcopy(synthetic_720)))
    assert json.dumps(straight, sort_keys=True) == json.dumps(reordered, sort_keys=True)


# ----------------------------------------------------------- motion quality


def test_sampled_positions_progress_monotonically(synthetic_720: dict[str, Any]) -> None:
    """No oscillation: distance from the start pose never decreases along a move."""
    planned = plan_camera_movements(synthetic_720)
    checked = 0
    for shot in planned["shots"]:
        if shot.get("camera_movement") is None:
            continue
        path = sample_movement_path(shot)
        if not path:
            continue
        origin = path[0][1]["location"]
        distances = [
            sum((a - b) ** 2 for a, b in zip(origin, pose["location"], strict=True)) ** 0.5
            for _, pose in path
        ]
        for earlier, later in zip(distances, distances[1:], strict=False):
            assert later >= earlier - 1e-9, shot["shot_id"]
        checked += 1
    assert checked >= 1


def test_per_frame_delta_stays_under_the_defined_bound(synthetic_720: dict[str, Any]) -> None:
    """No jitter or whip-pan: every frame moves less than the easing slope bound.

    The bound is 1.6 * |end - start| / (steps): smoothstep's peak slope is 1.5
    times the chord slope, plus a 6.7% margin. A compliant camera glides.
    """
    planned = plan_camera_movements(synthetic_720)
    checked = 0
    for shot in planned["shots"]:
        if shot.get("camera_movement") is None:
            continue
        path = sample_movement_path(shot)
        bound = per_frame_delta_bound(shot)
        for (_, before), (_, after) in zip(path, path[1:], strict=False):
            delta = (
                sum(
                    (a - b) ** 2 for a, b in zip(before["location"], after["location"], strict=True)
                )
                ** 0.5
            )
            assert delta <= bound + 1e-9, (shot["shot_id"], delta, bound)
        checked += 1
    assert checked >= 1


# ------------------------------------------------------------------ metrics


def test_the_metrics_dict_is_exact_on_the_synthetic_plan(
    synthetic_720: dict[str, Any],
) -> None:
    """The pure metrics function reports exactly what was assigned."""
    planned = plan_camera_movements(synthetic_720)
    metrics = movement_metrics(planned)
    assert metrics == {
        "shot_count": 10,
        "static_shot_count": 5,
        "moving_shot_count": 5,
        "movement_type_histogram": {
            "PULL_OUT": 1,
            "PUSH_IN": 2,
            "REVEAL": 1,
            "STATIC": 1,
            "TRACK": 1,
        },
        "shots_with_valid_reason_count": 6,
        "unmotivated_movement_violation_count": 0,
    }


def test_metrics_on_a_plain_v1_plan_are_all_zero_movement(
    plan_ep1: dict[str, Any],
) -> None:
    """A V1 plan has no movement blocks and zero violations."""
    metrics = movement_metrics(plan_ep1)
    assert metrics["moving_shot_count"] == 0
    assert metrics["static_shot_count"] == metrics["shot_count"]
    assert metrics["unmotivated_movement_violation_count"] == 0


def test_the_planned_real_plan_validates_under_v2_and_has_no_violations(
    plan_ep1: dict[str, Any],
) -> None:
    """End to end on the genuine plan: plan, validate, measure."""
    planned = plan_camera_movements(plan_ep1)
    assert validate_shot_direction_plan_v2(planned) is planned
    metrics = movement_metrics(planned)
    assert metrics["unmotivated_movement_violation_count"] == 0
    assert metrics["shots_with_valid_reason_count"] == metrics["moving_shot_count"] + sum(
        1
        for shot in planned["shots"]
        if shot.get("camera_movement", {}).get("movement_type") == "STATIC"
    )
