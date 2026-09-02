"""QA metrics for the Director Revision's camera grammar.

These tests drive the pure camera QA metrics over (a) the genuine V1 shot plan
the repo's own planner produces from the real render export and the canonical
Phase 17 clock, (b) the real camera anchors of ``cinematic_spec.CAMERA_ANCHORS``,
and (c) the real wall-station geometry of ``master_scene_v1.json`` and the real
neighborhood geometry of ``production_world_v1.json``. The only synthetic input
is an EP1-scale shot plan mirroring the repo's own ``synthetic_720_shot_plan``
(test_camera_movement_planner.py) and the positive-framing camera poses, each
clearly labelled as such -- no dict with invented key names is used anywhere.
"""

import copy
import json
from pathlib import Path

import pytest

from living_diorama.cinematic import (
    build_shot_direction_plan_document,
    catalogue_document,
)
from living_diorama.cinematic.camera_movement_planner import (
    plan_camera_movements,
)
from living_diorama.cinematic.camera_qa_metrics import (
    camera_geometry_clearance,
    context_visibility_score,
    event_object_fully_readable,
    no_animated_lens_zoom,
    no_push_pull_oscillation,
    shot_grammar_coverage,
)
from living_diorama.cinematic.cinematic_spec import catalogue_sha256

REPO_ROOT = Path(__file__).resolve().parents[2]
MASTER_SCENE = json.loads(
    (REPO_ROOT / "visual" / "blender" / "config" / "master_scene_v1.json").read_text(
        encoding="utf-8"
    )
)
PRODUCTION_WORLD = json.loads(
    (REPO_ROOT / "visual" / "blender" / "config" / "production_world_v1.json").read_text(
        encoding="utf-8"
    )
)

# The real event object: the wall station of boundary_ab, verbatim from
# master_scene_v1.json lines 75-85.
REAL_WALL_STATION = {
    "center": [17.0, -1.0],
    "direction": [-0.22, 1.0],
    "length": 44.0,
}

REAL_ANCHOR_CAM_SCAR_DETAIL = catalogue_document()["CAM_SCAR_DETAIL"]
REAL_ANCHOR_CAM_HERO_WORLD = catalogue_document()["CAM_HERO_WORLD"]


def real_context_objects() -> list[dict[str, object]]:
    """The real named context objects of the two shipped world configs.

    Categories are the real document sections: districts, boundary wall
    stations and the golden-seal landmark (master_scene_v1.json) plus
    neighborhoods (production_world_v1.json) and the platform (world block).
    """
    objects: list[dict[str, object]] = []
    for name, district in MASTER_SCENE["districts"].items():
        objects.append(
            {
                "name": name,
                "category": "district",
                "location": [district["center"][0], district["center"][1], district["elevation"]],
            }
        )
    for name, boundary in MASTER_SCENE["boundaries"].items():
        station = boundary["wall_station"]
        objects.append(
            {
                "name": f"{name}_wall_station",
                "category": "wall_station",
                "location": [station["center"][0], station["center"][1], 0.0],
            }
        )
    seal = MASTER_SCENE["landmarks"]["golden_seal"]
    objects.append(
        {
            "name": "golden_seal",
            "category": "landmark",
            "location": [seal["location"][0], seal["location"][1], 0.0],
        }
    )
    platform = MASTER_SCENE["world"]
    objects.append(
        {
            "name": "platform",
            "category": "platform",
            "location": [0.0, 0.0, -platform["platform_thickness"] / 2.0],
        }
    )
    for name, neighborhood in PRODUCTION_WORLD["neighborhoods"].items():
        objects.append(
            {
                "name": name,
                "category": "neighborhood",
                "location": [neighborhood["center"][0], neighborhood["center"][1], 0.0],
            }
        )
    return objects


def synthetic_ep1_scale_plan() -> dict[str, object]:
    """A synthetic-but-structurally-identical 720-frame EP1-scale plan.

    The same shape as the repo's own ``synthetic_720_shot_plan`` in
    test_camera_movement_planner.py: same V1 eight-key shots, same closed
    vocabularies, same tiling/adjacency/loop rules, on a 720-frame clock whose
    digest is synthetic. Used where a plan richer than the genuine four-shot
    episode is needed (STATIC + TRACK + PULL_OUT coverage, oscillation
    detection); it is labelled synthetic everywhere it is used.
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
            "motion_time_sha256": "ab" * 32,  # synthetic clock digest, stated
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
def plan_ep1(story_ep0_to_ep1: dict[str, object], motion_time: bytes) -> dict[str, object]:
    """The genuine episode 0 -> 1 shot plan, cut on the canonical clock."""
    return build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)


@pytest.fixture
def planned_ep1(plan_ep1: dict[str, object]) -> dict[str, object]:
    """The genuine plan with the real movement planner's assignment."""
    return plan_camera_movements(plan_ep1)


@pytest.fixture
def planned_ep1_scale() -> dict[str, object]:
    """The synthetic EP1-scale plan with the real movement planner's assignment."""
    return plan_camera_movements(synthetic_ep1_scale_plan())


# ------------------------------------------------------------------ lens zoom


def test_no_animated_lens_zoom_passes_on_the_real_ep1_plan(planned_ep1: dict[str, object]) -> None:
    """The genuine plan never re-lenses: every sampled movement pose keeps its lens."""
    result = no_animated_lens_zoom(planned_ep1)
    assert result["passes"] is True
    assert result["violating_shot_ids"] == []
    assert result["sampled_shots"] >= 1


def test_no_animated_lens_zoom_passes_on_the_ep1_scale_plan(
    planned_ep1_scale: dict[str, object],
) -> None:
    """The EP1-scale plan carries no animated lens zoom on any sampled shot."""
    result = no_animated_lens_zoom(planned_ep1_scale)
    assert result["passes"] is True
    assert result["sampled_shots"] >= 5


def test_no_animated_lens_zoom_catches_an_animated_lens(
    planned_ep1_scale: dict[str, object],
) -> None:
    """A grammar that re-lensed mid-shot is caught, not assumed away (synthetic)."""
    mutated = copy.deepcopy(planned_ep1_scale)
    mutated["shots"][1]["camera_movement"]["end_transform"]["lens_mm"] = 60.0
    result = no_animated_lens_zoom(mutated)
    assert result["passes"] is False
    assert result["violating_shot_ids"] == ["shot_0002"]


def test_no_animated_lens_zoom_is_deterministic(planned_ep1: dict[str, object]) -> None:
    """Two independent runs over equal (but distinct) plans agree exactly."""
    assert no_animated_lens_zoom(planned_ep1) == no_animated_lens_zoom(copy.deepcopy(planned_ep1))


# ------------------------------------------------------- push/pull oscillation


def test_no_push_pull_oscillation_flags_the_real_ep1_closing_cut(
    planned_ep1: dict[str, object],
) -> None:
    """The genuine plan PUSHes in on the scar, then PULLs out to the closing wide.

    The planner's own assignment on the real four-shot plan is REVEAL, PUSH_IN,
    PUSH_IN, PULL_OUT -- so the PUSH_IN on CAM_SCAR_DETAIL (shot_0003) is
    immediately followed by the closing PULL_OUT (shot_0004) with no
    non-radial movement between them. That reads as pumping, and the metric
    exists exactly to report it to the acceptance gate.
    """
    result = no_push_pull_oscillation(planned_ep1)
    assert result["oscillation_count"] == 1
    assert result["pairs"][0]["shot_ids"] == ("shot_0003", "shot_0004")
    assert result["pairs"][0]["movement_types"] == ("PUSH_IN", "PULL_OUT")


def test_no_push_pull_oscillation_is_zero_on_the_ep1_scale_plan(
    planned_ep1_scale: dict[str, object],
) -> None:
    """Two push-ins in a row are a ramp, not pumping."""
    result = no_push_pull_oscillation(planned_ep1_scale)
    assert result["oscillation_count"] == 0
    assert result["pairs"] == []


def test_no_push_pull_oscillation_detects_a_push_pull_pair(
    planned_ep1_scale: dict[str, object],
) -> None:
    """PUSH_IN then PULL_OUT with no intervening non-radial move is flagged.

    The mutated movement type is synthetic (a PULL_OUT whose endpoints still
    describe the original push); the detector reads the ordered movement
    sequence only, which is exactly the contract it checks.
    """
    mutated = copy.deepcopy(planned_ep1_scale)
    mutated["shots"][2]["camera_movement"]["movement_type"] = "PULL_OUT"
    result = no_push_pull_oscillation(mutated)
    assert result["oscillation_count"] == 1
    assert result["pairs"][0]["shot_ids"] == ("shot_0002", "shot_0003")
    assert result["pairs"][0]["movement_types"] == ("PUSH_IN", "PULL_OUT")


def test_no_push_pull_oscillation_is_deterministic(
    planned_ep1_scale: dict[str, object],
) -> None:
    """Two independent runs over equal (but distinct) plans agree exactly."""
    assert no_push_pull_oscillation(planned_ep1_scale) == no_push_pull_oscillation(
        copy.deepcopy(planned_ep1_scale)
    )


# ------------------------------------------------- event object readability


def test_event_object_fully_readable_with_a_real_anchor_and_real_wall() -> None:
    """CAM_SCAR_DETAIL stands ~20 units from a 44-unit wall: it fills the frame.

    Hand-checkable: the far wall end projects off the view axis far beyond the
    half-FOV, so the slab is clipped and the metric must refuse readability.
    """
    result = event_object_fully_readable(REAL_ANCHOR_CAM_SCAR_DETAIL, REAL_WALL_STATION)
    assert result["fully_readable"] is False
    assert result["in_frustum"] is False
    assert result["frame_fill_fraction"] == 1.0
    assert result["reasons"]


def test_event_object_fully_readable_at_a_comfortable_distance() -> None:
    """A camera on the wall's normal 60 units out reads the full slab.

    Synthetic pose, real wall geometry: the largest projected corner extent is
    about 0.72 of the frame (hand-computed from the 22-unit half-length at 60
    units against the 35 mm lens), comfortably inside the 0.9 bound.
    """
    pose = {
        "location": [75.6, 11.89, 10.0],
        "look_at": [17.0, -1.0, 8.0],
        "lens_mm": 35.0,
    }
    result = event_object_fully_readable(pose, REAL_WALL_STATION)
    assert result["fully_readable"] is True
    assert result["in_frustum"] is True
    assert 0.6 < result["frame_fill_fraction"] < 0.8
    assert result["distance_to_center"] == pytest.approx(60.03, abs=0.5)


def test_event_object_fully_readable_is_deterministic() -> None:
    """Two independent runs over equal (but distinct) inputs agree exactly."""
    assert event_object_fully_readable(
        REAL_ANCHOR_CAM_SCAR_DETAIL, REAL_WALL_STATION
    ) == event_object_fully_readable(REAL_ANCHOR_CAM_SCAR_DETAIL, copy.deepcopy(REAL_WALL_STATION))


# ------------------------------------------------------ context visibility


def test_context_visibility_score_with_the_real_world() -> None:
    """CAM_HERO_WORLD sees the civic districts, the wall and the seal.

    Hand-checkable: district_a's center sits almost on the look-at point, the
    boundary_ab wall station is ~6 degrees off axis, and the golden seal shares
    district_a's center -- all inside the 42 mm lens frustum.
    """
    result = context_visibility_score(REAL_ANCHOR_CAM_HERO_WORLD, real_context_objects())
    assert result["visible_category_count"] >= 3
    assert {"district", "wall_station", "landmark"}.issubset(result["visible_categories"])
    assert result["visible_categories"] == sorted(result["visible_categories"])


def test_context_visibility_score_is_deterministic() -> None:
    """Two independent runs over the same real inputs agree exactly."""
    first = context_visibility_score(REAL_ANCHOR_CAM_HERO_WORLD, real_context_objects())
    second = context_visibility_score(REAL_ANCHOR_CAM_HERO_WORLD, real_context_objects())
    assert first == second


# --------------------------------------------------------------- clearance


def test_camera_geometry_clearance_against_the_real_wall() -> None:
    """CAM_SCAR_DETAIL's distance to the boundary_ab slab, hand-computed.

    The camera projects onto the wall plane at (13.70, 14.01, 3.2), an interior
    point of the slab, so the exact distance is the off-plane component:
    sqrt(127.71 + 6.18) = 11.573 world units.
    """
    result = camera_geometry_clearance(REAL_ANCHOR_CAM_SCAR_DETAIL, REAL_WALL_STATION)
    assert result["min_distance"] == pytest.approx(11.573, abs=0.01)
    assert "passes" not in result  # no threshold invented by the function


def test_camera_geometry_clearance_threshold_is_supplied_by_the_caller() -> None:
    """The same measurement, compared against the caller's own thresholds."""
    result = camera_geometry_clearance(
        REAL_ANCHOR_CAM_SCAR_DETAIL, REAL_WALL_STATION, min_clearance=5.0
    )
    assert result["passes"] is True
    assert result["required_clearance"] == 5.0
    tight = camera_geometry_clearance(
        REAL_ANCHOR_CAM_SCAR_DETAIL, REAL_WALL_STATION, min_clearance=20.0
    )
    assert tight["passes"] is False


def test_camera_geometry_clearance_accepts_a_list_of_real_stations() -> None:
    """A list of stations reports the minimum distance across all of them."""
    stations = [boundary["wall_station"] for boundary in MASTER_SCENE["boundaries"].values()]
    result = camera_geometry_clearance(REAL_ANCHOR_CAM_SCAR_DETAIL, stations)
    assert result["min_distance"] > 0.0
    assert (
        result["min_distance"]
        <= camera_geometry_clearance(REAL_ANCHOR_CAM_SCAR_DETAIL, REAL_WALL_STATION)["min_distance"]
    )


# --------------------------------------------------------- grammar coverage


def test_shot_grammar_coverage_on_the_ep1_scale_plan(
    planned_ep1_scale: dict[str, object],
) -> None:
    """The EP1-scale grammar meets all three required elements and reports time.

    Wide/medium-wide frames are the two ESTABLISHING shots (24 + 72 frames of
    720), so the fraction is exactly 96/720 = 0.133333.
    """
    result = shot_grammar_coverage(planned_ep1_scale)
    assert result["shot_count"] == 10
    assert result["establishing_wide_present"] is True
    assert result["static_hold_present"] is True
    assert result["spatial_travel_present"] is True
    assert result["movement_type_histogram"] == {
        "PULL_OUT": 1,
        "PUSH_IN": 2,
        "REVEAL": 1,
        "STATIC": 1,
        "TRACK": 1,
    }
    assert result["total_frames"] == 720
    assert result["wide_medium_wide_frames"] == 96
    assert result["wide_medium_wide_fraction"] == round(96 / 720, 6)


def test_shot_grammar_coverage_on_the_real_ep1_plan(planned_ep1: dict[str, object]) -> None:
    """The genuine plan opens on an establishing wide; the fraction is derived.

    This is a reporting function: it presents the facts and the time fraction,
    and never invents a pass/fail threshold.
    """
    result = shot_grammar_coverage(planned_ep1)
    assert result["shot_count"] >= 2
    assert result["establishing_wide_present"] is True
    assert 0.0 <= result["wide_medium_wide_fraction"] <= 1.0
    assert result["wide_medium_wide_fraction"] == round(
        result["wide_medium_wide_frames"] / result["total_frames"], 6
    )


def test_shot_grammar_coverage_is_deterministic(planned_ep1: dict[str, object]) -> None:
    """Two independent runs over equal (but distinct) plans agree exactly."""
    assert shot_grammar_coverage(planned_ep1) == shot_grammar_coverage(copy.deepcopy(planned_ep1))


# ------------------------------------------------------------ purity boundary


def test_camera_qa_metrics_never_imports_blender() -> None:
    """The metrics module is pure: no bpy import anywhere in its source."""
    import living_diorama.cinematic.camera_qa_metrics as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "import bpy" not in source
    assert "from bpy" not in source
