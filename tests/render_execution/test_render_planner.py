"""Deriving a render plan from a directed episode.

The planner copies; it does not decide. These tests hold it to that: every
camera in a render plan must be the camera Phase 22 put on that frame, every
frame must come from Phase 17's clock, and nothing may appear that neither
upstream document accounts for.
"""

import copy
from typing import Any

import pytest

from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.render_execution import (
    build_episode_render_plan_bytes,
    build_episode_render_plan_document,
    load_episode_render_plan,
    render_profile_sha256,
)


def _frames(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """The plan's frame records."""
    return list(plan["frames"])


def test_the_plan_accounts_for_every_emitted_frame_and_the_witness(
    render_plan: dict[str, Any],
) -> None:
    """192 playback frames plus one witness, in frame order, none repeated."""
    frames = _frames(render_plan)
    assert len(frames) == 193
    assert [entry["frame"] for entry in frames] == list(range(1, 194))
    assert [entry["role"] for entry in frames[:-1]] == ["playback"] * 192
    assert frames[-1]["role"] == "witness"


def test_every_frame_carries_the_camera_phase_twenty_two_directed(
    render_plan: dict[str, Any], shot_plan_leg1: dict[str, Any]
) -> None:
    """The planner copies direction; it never chooses a camera.

    Checked frame by frame against the shot windows rather than shot by shot,
    so an off-by-one at a cut boundary cannot hide.
    """
    directed: dict[int, tuple[str, str]] = {}
    for shot in shot_plan_leg1["shots"]:
        for frame in range(shot["start_frame"], shot["end_frame"] + 1):
            directed[frame] = (shot["camera_anchor_id"], shot["shot_id"])
    for entry in _frames(render_plan):
        expected_camera, expected_shot = directed[entry["frame"]]
        assert entry["camera_anchor_id"] == expected_camera, entry["frame"]
        assert entry["shot_id"] == expected_shot, entry["frame"]


def test_the_witness_frame_belongs_to_the_closing_shot(
    render_plan: dict[str, Any],
) -> None:
    """Why the witness proves anything: it is the same shot as the last frame.

    Same shot means same camera, so the boundary frame differs from the last
    playback frame only by whatever kept moving -- Phase 19's walkers -- plus
    the renderer's noise. That residue is measured against tolerance in the
    real-Blender suite; this test establishes the shared-shot half of it.
    """
    frames = _frames(render_plan)
    final_playback, witness = frames[-2], frames[-1]
    assert witness["shot_id"] == final_playback["shot_id"]
    assert witness["camera_anchor_id"] == final_playback["camera_anchor_id"]


def test_the_plan_binds_the_exact_shot_plan_it_read(
    render_plan: dict[str, Any], shot_plan_leg1: dict[str, Any]
) -> None:
    """A render plan names the direction it was derived from, by digest."""
    expected = sha256_hex(dumps_canonical(shot_plan_leg1, "shot direction plan"))
    assert render_plan["source"]["shot_plan_sha256"] == expected


def test_the_plan_carries_the_whole_upstream_provenance_chain(
    render_plan: dict[str, Any], shot_plan_leg1: dict[str, Any]
) -> None:
    """Story, clock and catalogue digests are copied, never re-derived."""
    source = render_plan["source"]
    upstream = shot_plan_leg1["source"]
    assert source["story_plan_sha256"] == upstream["story_plan_sha256"]
    assert source["motion_time_sha256"] == upstream["motion_time_sha256"]
    assert source["catalogue_sha256"] == upstream["catalogue_sha256"]
    assert source["episode"] == upstream["episode"]
    assert source["previous_episode"] == upstream["previous_episode"]
    assert source["mode"] == upstream["mode"]
    assert source["render_profile_sha256"] == render_profile_sha256()


def test_the_plan_copies_the_clock_verbatim(
    render_plan: dict[str, Any], shot_plan_leg1: dict[str, Any]
) -> None:
    """Phase 23 invents no frame and no boundary."""
    assert render_plan["timeline"] == shot_plan_leg1["timeline"]


def test_a_baseline_episode_plans_its_own_directory(
    baseline_render_plan: dict[str, Any],
) -> None:
    """The baseline is a render like any other, in a directory of its own."""
    assert baseline_render_plan["destination"]["render_id"] == "episode_0000_baseline"
    assert baseline_render_plan["source"]["mode"] == "baseline"
    assert baseline_render_plan["source"]["previous_episode"] is None
    assert len(baseline_render_plan["frames"]) == 193


def test_an_unshown_beat_gets_no_frame_of_its_own(
    render_plan: dict[str, Any], shot_plan_leg1: dict[str, Any]
) -> None:
    """Phase 22's honest silence survives into the render.

    The durable-memory beats are deliberately unshown; nothing in the render
    plan may cite them, because rendering a frame for a beat no camera shows
    would be exactly the fabricated visibility Phase 22 refused.
    """
    unshown = {entry["beat_id"] for entry in shot_plan_leg1["unshown"]}
    assert unshown
    cited = {beat for entry in _frames(render_plan) for beat in entry["source_beat_ids"]}
    assert not (cited & unshown)


def test_two_builds_of_the_same_directed_episode_are_byte_identical(
    shot_plan_leg1: dict[str, Any], story_leg1: dict[str, Any]
) -> None:
    """Determinism at the document level."""
    first = build_episode_render_plan_bytes(
        copy.deepcopy(shot_plan_leg1), copy.deepcopy(story_leg1)
    )
    second = build_episode_render_plan_bytes(
        copy.deepcopy(shot_plan_leg1), copy.deepcopy(story_leg1)
    )
    assert first == second


def test_the_plan_round_trips_through_its_own_loader(
    shot_plan_leg1: dict[str, Any], story_leg1: dict[str, Any]
) -> None:
    """What is written is what is read back, and it validates on the way in."""
    payload = build_episode_render_plan_bytes(shot_plan_leg1, story_leg1)
    assert load_episode_render_plan(payload) == build_episode_render_plan_document(
        shot_plan_leg1, story_leg1
    )


def test_a_plan_derived_from_an_invalid_shot_plan_is_refused(
    shot_plan_leg1: dict[str, Any], story_leg1: dict[str, Any]
) -> None:
    """Binding an invalid direction would be planning to photograph a fiction."""
    broken = copy.deepcopy(shot_plan_leg1)
    broken["shots"][1]["camera_anchor_id"] = "CAM_INVENTED"
    with pytest.raises(ValueError):
        build_episode_render_plan_document(broken, story_leg1)


def test_a_plan_whose_shots_leave_a_frame_undirected_is_refused(
    shot_plan_leg1: dict[str, Any], story_leg1: dict[str, Any]
) -> None:
    """Phase 23 renders no frame nobody directed."""
    broken = copy.deepcopy(shot_plan_leg1)
    broken["shots"][0]["end_frame"] -= 1
    with pytest.raises(ValueError):
        build_episode_render_plan_document(broken, story_leg1)


def test_a_story_plan_from_another_episode_is_refused(
    shot_plan_leg1: dict[str, Any], story_baseline: dict[str, Any]
) -> None:
    """A render plan binds one episode's documents, never a mixed pair."""
    with pytest.raises(ValueError, match="never a mixed pair"):
        build_episode_render_plan_document(shot_plan_leg1, story_baseline)


def test_the_plan_binds_the_exports_the_world_is_composed_from(
    render_plan: dict[str, Any], story_leg1: dict[str, Any]
) -> None:
    """The binding that stops a correct plan being pointed at the wrong world."""
    source = render_plan["source"]
    assert source["after_export_sha256"] == story_leg1["source"]["current"]["document_sha256"]
    assert source["before_export_sha256"] == story_leg1["source"]["previous"]["document_sha256"]


def test_a_baseline_binds_no_before_export(baseline_render_plan: dict[str, Any]) -> None:
    """A baseline holds one state and has nothing to transition from."""
    assert baseline_render_plan["source"]["before_export_sha256"] is None
    assert baseline_render_plan["source"]["after_export_sha256"] is not None


def test_the_planner_reads_bytes_only_as_bytes() -> None:
    """A str is not a document; refusing early keeps the digest claim honest."""
    with pytest.raises(TypeError):
        load_episode_render_plan("{}")  # type: ignore[arg-type]
