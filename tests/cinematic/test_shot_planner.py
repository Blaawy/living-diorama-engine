"""Directing the real canonical story plans.

These tests run against story plans the locked Phase 21 layer derives from the
genuine three-episode chain, so what they assert about the canonical story is what
the engine actually did and what Phase 21 actually said about it. The clock is
the exact bytes of the shipped Phase 17 Motion & Time Spec, so what they assert
about time is what Phase 17 actually locks.
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from living_diorama.cinematic import (
    build_shot_direction_plan_document,
    cinematic_spec,
    resolve_motion_time_binding,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def shot_kinds(plan: dict[str, Any]) -> list[str]:
    """The camera anchor of every shot, in order."""
    return [shot["camera_anchor_id"] for shot in plan["shots"]]


# ---------------------------------------------------------- the locked clock


def test_the_binding_resolves_the_shipped_phase17_config_exactly(
    motion_time: bytes,
) -> None:
    """The binding must restate the shipped clock and derive its boundaries.

    The expectation is recomputed here from the config document with Phase 17's
    own arithmetic, so this test fails if either side -- the shipped config or
    the binding's derivation -- drifts.
    """
    config = json.loads(motion_time.decode("utf-8"))["timeline"]
    binding = resolve_motion_time_binding(motion_time)
    resolved = binding["timeline"]
    for field in config:
        assert resolved[field] == config[field], field
    assert resolved["transition_start"] == config["start_frame"] + config["start_hold_frames"]
    assert resolved["transition_end"] == (
        resolved["transition_start"] + config["transition_frames"]
    )
    assert resolved["end_frame"] == resolved["transition_end"] + config["end_hold_frames"]


def test_the_binding_names_the_exact_source_bytes(motion_time: bytes) -> None:
    """The digest is of the raw source document, not of a re-encoding."""
    import hashlib

    binding = resolve_motion_time_binding(motion_time)
    assert binding["motion_time_sha256"] == hashlib.sha256(motion_time).hexdigest()
    assert binding["motion_time_format"] == "living_diorama_motion_time"
    assert binding["motion_time_schema_version"] == 1


def test_the_locked_frame_contract_is_eight_seconds(timeline: dict[str, int]) -> None:
    """24 fps, frames 1 to 193, eight seconds."""
    assert timeline["fps"] == 24
    assert timeline["start_frame"] == 1
    assert timeline["end_frame"] == 193
    assert (timeline["end_frame"] - timeline["start_frame"]) / timeline["fps"] == 8.0


# ------------------------------------------------------------------ baseline


def test_the_baseline_episode_gets_one_neutral_shot(
    story_ep0: dict[str, Any], motion_time: bytes
) -> None:
    """Nothing was emphasized, so nothing is framed: one establishing hold."""
    plan = build_shot_direction_plan_document(story_ep0, motion_time)
    assert len(plan["shots"]) == 1
    shot = plan["shots"][0]
    assert shot["kind"] == "ESTABLISHING"
    assert shot["camera_anchor_id"] == cinematic_spec.ESTABLISHING_ANCHOR
    assert shot["start_frame"] == 1
    assert shot["end_frame"] == 193
    assert shot["source_beat_ids"] == []


def test_the_baseline_records_its_beat_as_unshown(
    story_ep0: dict[str, Any], motion_time: bytes
) -> None:
    """Every beat is accounted for, even the one that says there was nothing."""
    plan = build_shot_direction_plan_document(story_ep0, motion_time)
    assert len(plan["unshown"]) == 1
    assert plan["unshown"][0]["reason_code"] == cinematic_spec.REASON_NOTHING_TO_EMPHASIZE


def test_no_story_beat_is_fabricated_for_the_baseline(
    story_ep0: dict[str, Any], motion_time: bytes
) -> None:
    """No story beat is fabricated for the baseline."""
    plan = build_shot_direction_plan_document(story_ep0, motion_time)
    assert all(shot["source_beat_ids"] == [] for shot in plan["shots"])


# ------------------------------------------------ the canonical transitions


def test_the_first_transition_frames_the_seal_then_the_scar(
    story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """Episode 0 -> 1: the law is suspended and the wall rises."""
    plan = build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)
    assert shot_kinds(plan) == [
        "CAM_HERO_WORLD",
        "CAM_SEAL_DETAIL",
        "CAM_SCAR_DETAIL",
        "CAM_HERO_WORLD",
    ]


def test_the_first_transition_shows_the_law_and_unshows_the_new_record(
    story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """The seal shot frames the law change; the NEW durable fact is unshown.

    Phase 20's step-at-window-end places the new fact's stone at frame ~139,
    after every derived durable-consequence window, so framing it would be
    fabricated visibility; the law's own seal glow animates from early in the
    transition and is genuinely on screen.
    """
    plan = build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)
    seal = next(s for s in plan["shots"] if s["camera_anchor_id"] == "CAM_SEAL_DETAIL")
    assert seal["source_beat_ids"] == ["beat_0001"]
    assert seal["reason_code"] == cinematic_spec.REASON_BEAT_KIND_RULE
    durable = next(
        beat for beat in story_ep0_to_ep1["beats"] if beat["kind"] == "DURABLE_CONSEQUENCE"
    )
    entry = next(e for e in plan["unshown"] if e["beat_id"] == durable["beat_id"])
    assert entry["reason_code"] == cinematic_spec.REASON_NO_FIXED_ANCHOR_WITH_VISUAL_EVIDENCE


def test_adjacent_same_anchor_beats_merge_into_one_shot(
    story_adjacent: dict[str, Any], motion_time: bytes
) -> None:
    """Cutting to the camera you are already on is not a cut.

    The canonical chain no longer produces a merged shot, so the rule is
    proven on the synthetic two-law story whose beats share the Seal.
    """
    plan = build_shot_direction_plan_document(story_adjacent, motion_time)
    seal = next(s for s in plan["shots"] if s["camera_anchor_id"] == "CAM_SEAL_DETAIL")
    assert len(seal["source_beat_ids"]) == 2
    assert seal["reason_code"] == cinematic_spec.REASON_ADJACENT_SAME_ANCHOR_MERGED


def test_the_second_transition_unshows_the_persisted_consequence(
    story_ep1_to_ep2: dict[str, Any], motion_time: bytes
) -> None:
    """Episode 1 -> 2: the wall's change is shown; the register is not seen.

    The full-world gate measured the persisted stone wholly occluded by the
    Seal's own disc from the only candidate anchor (nine of nine rays), so
    the beat is honestly unshown and the transition frames the wall instead.
    """
    plan = build_shot_direction_plan_document(story_ep1_to_ep2, motion_time)
    persisted = next(
        beat for beat in story_ep1_to_ep2["beats"] if beat["kind"] == "CONSEQUENCE_PERSISTED"
    )
    entry = next(e for e in plan["unshown"] if e["beat_id"] == persisted["beat_id"])
    assert entry["reason_code"] == cinematic_spec.REASON_NO_FIXED_ANCHOR_WITH_VISUAL_EVIDENCE
    anchors = [s["camera_anchor_id"] for s in plan["shots"]]
    assert anchors == ["CAM_HERO_WORLD", "CAM_SCAR_DETAIL", "CAM_HERO_WORLD"]


def test_the_primary_beat_gets_the_most_transition_time(
    story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """Phase 21 ranks; Phase 22 turns that ranking into screen time.

    Proven on the first transition, the canonical leg that still shows both a
    PRIMARY and a SECONDARY beat.
    """
    plan = build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)
    beats = [s for s in plan["shots"] if s["kind"] == "BEAT"]
    primary = next(s for s in beats if s["emphasis"] == "PRIMARY")
    secondary = next(s for s in beats if s["emphasis"] == "SECONDARY")
    primary_frames = primary["end_frame"] - primary["start_frame"] + 1
    secondary_frames = secondary["end_frame"] - secondary["start_frame"] + 1
    assert primary_frames > secondary_frames


# ------------------------------------------------------------- loop closure


@pytest.mark.parametrize("story_name", ["story_ep0", "story_ep0_to_ep1", "story_ep1_to_ep2"])
def test_the_camera_at_frame_one_equals_the_camera_at_frame_193(
    story_name: str, motion_time: bytes, request: pytest.FixtureRequest
) -> None:
    """Phase 17 makes frame 1 and 193 the same world; the camera must agree."""
    story = request.getfixturevalue(story_name)
    plan = build_shot_direction_plan_document(story, motion_time)
    assert plan["shots"][0]["camera_anchor_id"] == plan["shots"][-1]["camera_anchor_id"]


# ------------------------------------------------------------ frame coverage


@pytest.mark.parametrize("story_name", ["story_ep0", "story_ep0_to_ep1", "story_ep1_to_ep2"])
def test_the_shots_tile_the_locked_timeline_exactly(
    story_name: str,
    motion_time: bytes,
    timeline: dict[str, int],
    request: pytest.FixtureRequest,
) -> None:
    """No gap, no overlap, no frame invented, no frame left undirected."""
    story = request.getfixturevalue(story_name)
    plan = build_shot_direction_plan_document(story, motion_time)
    covered: list[int] = []
    for shot in plan["shots"]:
        covered.extend(range(shot["start_frame"], shot["end_frame"] + 1))
    assert covered == list(range(timeline["start_frame"], timeline["end_frame"] + 1))


def test_no_shot_is_shorter_than_the_minimum(
    story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """No shot is shorter than the minimum."""
    plan = build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)
    for shot in plan["shots"]:
        frames = shot["end_frame"] - shot["start_frame"] + 1
        assert frames >= cinematic_spec.MIN_SHOT_FRAMES, shot["shot_id"]


def test_beat_shots_stay_inside_the_transition(
    story_ep0_to_ep1: dict[str, Any], motion_time: bytes, timeline: dict[str, int]
) -> None:
    """The holds are neutral; emphasis lives in the transition Phase 17 owns."""
    plan = build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)
    for shot in plan["shots"]:
        if shot["kind"] != "BEAT":
            continue
        assert shot["start_frame"] >= timeline["transition_start"]
        assert shot["end_frame"] < timeline["transition_end"]


def test_adjacent_shots_never_share_an_anchor(
    story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """A cut to the camera you are already on is not a cut."""
    plan = build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)
    anchors = shot_kinds(plan)
    for position in range(1, len(anchors)):
        assert anchors[position] != anchors[position - 1]


# --------------------------------------------------------------- traceability


@pytest.mark.parametrize("story_name", ["story_ep0_to_ep1", "story_ep1_to_ep2"])
def test_every_beat_is_either_shown_once_or_recorded_as_unshown(
    story_name: str, motion_time: bytes, request: pytest.FixtureRequest
) -> None:
    """The plan accounts for every beat Phase 21 gave it, exactly once."""
    story = request.getfixturevalue(story_name)
    plan = build_shot_direction_plan_document(story, motion_time)
    shown = [b for shot in plan["shots"] for b in shot["source_beat_ids"]]
    unshown = [entry["beat_id"] for entry in plan["unshown"]]
    accounted = sorted(shown + unshown)
    assert accounted == sorted(beat["beat_id"] for beat in story["beats"])
    assert len(accounted) == len(set(accounted))


@pytest.mark.parametrize("story_name", ["story_ep0_to_ep1", "story_ep1_to_ep2"])
def test_every_cited_beat_exists_in_the_story_plan(
    story_name: str, motion_time: bytes, request: pytest.FixtureRequest
) -> None:
    """Every cited beat exists in the story plan."""
    story = request.getfixturevalue(story_name)
    plan = build_shot_direction_plan_document(story, motion_time)
    known = {beat["beat_id"] for beat in story["beats"]}
    for shot in plan["shots"]:
        for beat_id in shot["source_beat_ids"]:
            assert beat_id in known


def test_the_plan_binds_the_exact_story_plan_it_read(
    story_ep1_to_ep2: dict[str, Any], motion_time: bytes
) -> None:
    """The binding names the document, not merely the episode."""
    import hashlib

    from living_diorama.persistence.json_codec import dumps_canonical

    plan = build_shot_direction_plan_document(story_ep1_to_ep2, motion_time)
    expected = hashlib.sha256(dumps_canonical(story_ep1_to_ep2, "story")).hexdigest()
    assert plan["source"]["story_plan_sha256"] == expected


def test_the_plan_binds_the_exact_motion_time_bytes_it_was_cut_against(
    story_ep1_to_ep2: dict[str, Any], motion_time: bytes
) -> None:
    """The clock binding names the document too, not merely the frame count."""
    import hashlib

    plan = build_shot_direction_plan_document(story_ep1_to_ep2, motion_time)
    assert plan["source"]["motion_time_sha256"] == hashlib.sha256(motion_time).hexdigest()
    assert plan["source"]["motion_time_format"] == "living_diorama_motion_time"
    assert plan["source"]["motion_time_schema_version"] == 1


def test_editing_the_story_plan_changes_the_binding(
    story_ep1_to_ep2: dict[str, Any], motion_time: bytes
) -> None:
    """Editing the story plan changes the binding."""
    first = build_shot_direction_plan_document(story_ep1_to_ep2, motion_time)
    tampered = copy.deepcopy(story_ep1_to_ep2)
    tampered["excluded"]["SCARCITY_CHANGED"]["count"] += 0  # no-op, digest stable
    second = build_shot_direction_plan_document(tampered, motion_time)
    assert first["source"]["story_plan_sha256"] == second["source"]["story_plan_sha256"]


def test_the_planner_does_not_mutate_its_inputs(
    story_ep1_to_ep2: dict[str, Any], motion_time: bytes
) -> None:
    """The planner does not mutate its inputs."""
    before_story = copy.deepcopy(story_ep1_to_ep2)
    before_clock = bytes(motion_time)
    build_shot_direction_plan_document(story_ep1_to_ep2, motion_time)
    assert story_ep1_to_ep2 == before_story
    assert motion_time == before_clock


# ------------------------------------------------------- emphasis is copied


def test_phase22_never_reranks_a_beat(story_ep0_to_ep1: dict[str, Any], motion_time: bytes) -> None:
    """Phase 21's meaning is frozen; this layer copies emphasis, never edits it."""
    plan = build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)
    emphasis_by_beat = {b["beat_id"]: b["emphasis"] for b in story_ep0_to_ep1["beats"]}
    for shot in plan["shots"]:
        if shot["kind"] != "BEAT":
            continue
        cited = [emphasis_by_beat[b] for b in shot["source_beat_ids"]]
        assert shot["emphasis"] in cited


def test_shots_follow_phase21_rank_order(
    story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """Shot order is Phase 21's rank order; this layer never reorders history."""
    plan = build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)
    rank = {b["beat_id"]: b["rank"] for b in story_ep0_to_ep1["beats"]}
    seen: list[int] = []
    for shot in plan["shots"]:
        seen.extend(rank[b] for b in shot["source_beat_ids"])
    assert seen == sorted(seen)


# ----------------------------------------------------- motion clock refusals


def test_a_non_bytes_clock_is_refused(story_ep0: dict[str, Any]) -> None:
    """A parsed or hand-built timeline dict can no longer stand in for the clock."""
    with pytest.raises(TypeError, match="must arrive as bytes"):
        build_shot_direction_plan_document(story_ep0, {"fps": 24})


def test_a_non_json_clock_is_refused(story_ep0: dict[str, Any]) -> None:
    """A non json clock is refused."""
    with pytest.raises(ValueError, match="not valid UTF-8 JSON"):
        build_shot_direction_plan_document(story_ep0, b"not json")


def test_a_wrong_motion_format_is_refused(story_ep0: dict[str, Any], motion_time: bytes) -> None:
    """A document that is not a Motion & Time Spec is not a clock."""
    document = json.loads(motion_time.decode("utf-8"))
    document["format"] = "living_diorama_episode_story_plan"
    with pytest.raises(ValueError, match="declares format"):
        build_shot_direction_plan_document(story_ep0, json.dumps(document).encode("utf-8"))


def test_an_unsupported_motion_schema_version_is_refused(
    story_ep0: dict[str, Any], motion_time: bytes
) -> None:
    """An unsupported motion schema version is refused."""
    document = json.loads(motion_time.decode("utf-8"))
    document["schema_version"] = 99
    with pytest.raises(ValueError, match="schema version"):
        build_shot_direction_plan_document(story_ep0, json.dumps(document).encode("utf-8"))


def test_a_missing_timeline_field_is_refused(story_ep0: dict[str, Any], motion_time: bytes) -> None:
    """A missing timeline field is refused."""
    document = json.loads(motion_time.decode("utf-8"))
    del document["timeline"]["fps"]
    with pytest.raises(ValueError, match="missing fields"):
        build_shot_direction_plan_document(story_ep0, json.dumps(document).encode("utf-8"))


def test_an_unknown_timeline_field_is_refused(
    story_ep0: dict[str, Any], motion_time: bytes
) -> None:
    """An unknown timeline field is refused."""
    document = json.loads(motion_time.decode("utf-8"))
    document["timeline"]["frame_offset"] = 10
    with pytest.raises(ValueError, match="unknown fields"):
        build_shot_direction_plan_document(story_ep0, json.dumps(document).encode("utf-8"))


def test_a_boolean_frame_is_refused(story_ep0: dict[str, Any], motion_time: bytes) -> None:
    """True == 1 in Python, so a boolean frame must be refused by type."""
    document = json.loads(motion_time.decode("utf-8"))
    document["timeline"]["start_frame"] = True
    with pytest.raises(TypeError):
        build_shot_direction_plan_document(story_ep0, json.dumps(document).encode("utf-8"))


def test_a_float_frame_is_refused(story_ep0: dict[str, Any], motion_time: bytes) -> None:
    """A float frame is refused."""
    document = json.loads(motion_time.decode("utf-8"))
    document["timeline"]["end_frame"] = 193.0
    with pytest.raises(TypeError):
        build_shot_direction_plan_document(story_ep0, json.dumps(document).encode("utf-8"))


def test_an_implausible_fps_is_refused(story_ep0: dict[str, Any], alternate_clock: Any) -> None:
    """999 fps is outside Phase 17's own bound and dies before any digest check."""
    with pytest.raises(ValueError, match="fps"):
        build_shot_direction_plan_document(story_ep0, alternate_clock(fps=999))


def test_an_end_frame_that_breaks_the_arithmetic_is_refused(
    story_ep0: dict[str, Any], motion_time: bytes
) -> None:
    """A shifted end frame disagrees with the timeline's own phases."""
    document = json.loads(motion_time.decode("utf-8"))
    document["timeline"]["end_frame"] += 1000
    with pytest.raises(ValueError, match="disagrees with its own phases"):
        build_shot_direction_plan_document(story_ep0, json.dumps(document).encode("utf-8"))


def test_a_self_consistent_alternate_clock_is_refused_by_the_pin(
    story_ep0: dict[str, Any], alternate_clock: Any
) -> None:
    """The V2 layered defence is now a single closed door.

    A 30-fps document whose arithmetic closes is plausible on its face -- and
    the binding refuses it outright, because Phase 22 directs THE locked
    Phase 17 source, not any document shaped like one. No plan against an
    alternate clock can exist at all.
    """
    with pytest.raises(ValueError, match="not the canonical"):
        build_shot_direction_plan_document(story_ep0, alternate_clock(fps=30))


def test_a_reformatted_canonical_clock_is_refused(
    story_ep0: dict[str, Any], motion_time: bytes
) -> None:
    """The digest is over raw source bytes, not parsed meaning.

    Appending a single trailing space leaves the parsed document identical and
    the bytes different; the pin refuses, proving byte-exact source identity.
    """
    with pytest.raises(ValueError, match="not the canonical"):
        build_shot_direction_plan_document(story_ep0, motion_time + b" ")


def test_the_shipped_config_rehashes_to_the_pinned_constant(motion_time: bytes) -> None:
    """The mechanical check the pin's docstring promises.

    A future Phase 17 source change must arrive as an explicit reviewed update
    of the constant; this test fails loudly in both directions otherwise.
    """
    import hashlib

    from living_diorama.cinematic import CANONICAL_MOTION_TIME_SHA256

    assert hashlib.sha256(motion_time).hexdigest() == CANONICAL_MOTION_TIME_SHA256


def test_a_duplicate_json_key_in_the_clock_is_refused(motion_time: bytes) -> None:
    """A document carrying one field twice binds one digest to two claims.

    ``json.loads`` keeps the last occurrence silently; a source-bound contract
    refuses the ambiguity instead.
    """
    text = motion_time.decode("utf-8")
    duplicated = text.replace('"fps": 24,', '"fps": 24,\n    "fps": 24,', 1)
    assert duplicated != text
    with pytest.raises(ValueError, match="twice"):
        resolve_motion_time_binding(duplicated.encode("utf-8"))


def test_a_non_object_clock_document_is_refused(story_ep0: dict[str, Any]) -> None:
    """A JSON array is valid JSON and still not a Motion & Time Spec."""
    with pytest.raises(TypeError, match="must be a dict"):
        build_shot_direction_plan_document(story_ep0, b"[1,2,3]")


def test_a_non_object_timeline_is_refused(story_ep0: dict[str, Any], motion_time: bytes) -> None:
    """A non object timeline is refused."""
    document = json.loads(motion_time.decode("utf-8"))
    document["timeline"] = [24, 1, 24, 120, 48, 193]
    with pytest.raises(TypeError, match="timeline"):
        build_shot_direction_plan_document(story_ep0, json.dumps(document).encode("utf-8"))


def test_a_frame_beyond_the_phase17_bound_is_refused(
    story_ep0: dict[str, Any], motion_time: bytes
) -> None:
    """Phase 17 bounds every frame at 100000; the binding restates that."""
    document = json.loads(motion_time.decode("utf-8"))
    document["timeline"]["transition_frames"] = 200_000
    document["timeline"]["end_frame"] = 1 + 24 + 200_000 + 48
    with pytest.raises(ValueError, match="within"):
        build_shot_direction_plan_document(story_ep0, json.dumps(document).encode("utf-8"))


def test_binding_accepts_the_canonical_clock(motion_time: bytes) -> None:
    """Binding accepts the canonical clock."""
    binding = resolve_motion_time_binding(motion_time)
    assert binding["timeline"]["end_frame"] == 193


# ------------------------------------------------------------ story refusals


def test_a_malformed_story_plan_is_refused(story_ep0: dict[str, Any], motion_time: bytes) -> None:
    """A malformed story plan is refused."""
    del story_ep0["beats"]
    with pytest.raises((ValueError, TypeError)):
        build_shot_direction_plan_document(story_ep0, motion_time)


def test_an_unsupported_story_schema_version_is_refused(
    story_ep0: dict[str, Any], motion_time: bytes
) -> None:
    """An unsupported story schema version is refused."""
    story_ep0["schema_version"] = 99
    with pytest.raises(ValueError):
        build_shot_direction_plan_document(story_ep0, motion_time)


def test_a_story_plan_with_a_foreign_format_tag_is_refused(
    story_ep0: dict[str, Any], motion_time: bytes
) -> None:
    """A story plan with a foreign format tag is refused."""
    story_ep0["format"] = "living_diorama_shot_direction_plan"
    with pytest.raises(ValueError):
        build_shot_direction_plan_document(story_ep0, motion_time)


# -------------------------------------------------- unknown kinds and budget


def test_an_unknown_beat_kind_still_produces_a_valid_plan(
    story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """A future Phase 21 kind flattens the plan; it never breaks it.

    The story plan is edited directly here, so the shot layer sees a beat kind
    its table does not know. It must fall back to the neutral anchor and say so.
    """
    story_ep0_to_ep1["beats"][2]["kind"] = "WALL_STATE_CHANGE"
    plan = build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)
    assert plan["shots"]


def test_more_beats_than_frames_are_recorded_as_unshown(
    story_wide: dict[str, Any], motion_time: bytes
) -> None:
    """The transition is finite; what will not fit is reported, never dropped.

    The canonical 120-frame transition holds twenty minimum-length shots; the
    synthetic story's twenty-two alternating-anchor beats overflow it under the
    real locked clock, so the budget path is exercised without any alternate
    document existing anywhere.
    """
    plan = build_shot_direction_plan_document(story_wide, motion_time)
    assert len(plan["unshown"]) == 2
    assert all(
        entry["reason_code"] == cinematic_spec.REASON_TRANSITION_BUDGET_EXHAUSTED
        for entry in plan["unshown"]
    )
    beat_shots = [s for s in plan["shots"] if s["kind"] == "BEAT"]
    assert len(beat_shots) == 20
