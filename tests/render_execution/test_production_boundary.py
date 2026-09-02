"""The production boundary: what the Blender executor refuses, and why it agrees.

Phase 23 validates its render plan twice, in two implementations that may not
import each other -- the engine owns the contract, and the Blender executor
restates it in the standard library because a production boundary that trusts
a document for having "probably been built by the planner" is not a boundary.

Two implementations are only safe if they are proven to agree, so the heart of
this file is a mutation table driven through BOTH validators, requiring both to
refuse the same documents. The two reproductions an independent reviewer used
to break V1 are the first two rows.

Every refusal must also happen before anything is written: a malformed plan
must not create so much as a directory.
"""

import copy
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import pytest

from living_diorama.render_execution import validate_episode_render_plan
from living_diorama.story import build_episode_story_plan_document

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "visual" / "blender" / "scripts" / "render_episode.py"


def _load_executor() -> Any:
    """Import the production executor without Blender present."""
    spec = importlib.util.spec_from_file_location("render_episode_boundary", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


executor = _load_executor()

CINEMATIC_APPLIER = REPO_ROOT / "visual" / "blender" / "scripts" / "apply_cinematic_direction.py"
CAMERA_MOVEMENT_APPLIER = REPO_ROOT / "visual" / "blender" / "scripts" / "apply_camera_movement.py"
EPISODE_SCENE = REPO_ROOT / "visual" / "blender" / "scripts" / "episode_scene.py"
MOTION_CONFIG = REPO_ROOT / "visual" / "blender" / "config" / "motion_time_v1.json"
DIRECTOR_V4_CONFIG = REPO_ROOT / "visual" / "blender" / "config" / "motion_time_director_v4.json"
CINEMATIC_FIXTURES = REPO_ROOT / "tests" / "cinematic" / "fixtures"


def _load_module(name: str, path: Path) -> Any:
    """Import one Blender-side script without Blender present."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _shot_moves(shot: dict[str, Any]) -> bool:
    """The V2 movement-shot signal, as the engine and both appliers define it."""
    movement = shot.get("camera_movement")
    return movement is not None and movement["movement_type"] != "STATIC"


def _v2_shot_plan(shot_plan: dict[str, Any]) -> dict[str, Any]:
    """The genuine V2 shot plan: the engine assigns camera movement to the plan."""
    from living_diorama.cinematic.camera_movement_planner import plan_camera_movements

    return plan_camera_movements(copy.deepcopy(shot_plan))


def _v2_render_plan(shot_plan: dict[str, Any], story_plan: dict[str, Any]) -> dict[str, Any]:
    """The genuine V2 render plan, built by the engine planner under V2."""
    from living_diorama.render_execution import build_episode_render_plan_document

    return build_episode_render_plan_document(shot_plan, story_plan, camera_profile="v2")


def _drop_frame(plan: dict[str, Any]) -> None:
    """The reviewer's first reproduction: lose a frame, adjust the count to match."""
    del plan["frames"][86]
    plan["emission"]["frame_count"] -= 1


def _escape_filename(plan: dict[str, Any]) -> None:
    """The reviewer's second reproduction: a frame name that climbs out."""
    plan["frames"][0]["file"] = "../../owned.png"


MUTATIONS: tuple[tuple[str, Any], ...] = (
    ("a missing interior frame with the count adjusted", _drop_frame),
    ("a frame name that escapes the render directory", _escape_filename),
    ("a duplicated frame", lambda p: p["frames"].__setitem__(5, copy.deepcopy(p["frames"][4]))),
    (
        "two frames sharing one file name",
        lambda p: p["frames"][5].__setitem__("file", p["frames"][4]["file"]),
    ),
    ("frames out of order", lambda p: p["frames"].insert(3, p["frames"].pop(9))),
    (
        "a playback frame claiming the witness role",
        lambda p: p["frames"][0].__setitem__("role", "witness"),
    ),
    (
        "the witness claiming to be playback",
        lambda p: p["frames"][-1].__setitem__("role", "playback"),
    ),
    ("an unknown role", lambda p: p["frames"][0].__setitem__("role", "bonus")),
    ("a non-canonical frame name", lambda p: p["frames"][0].__setitem__("file", "frame_1.png")),
    (
        "a Windows separator in a frame name",
        lambda p: p["frames"][0].__setitem__("file", "a\\b.png"),
    ),
    (
        "a forward separator in a frame name",
        lambda p: p["frames"][0].__setitem__("file", "a/b.png"),
    ),
    (
        "a drive-qualified frame name",
        lambda p: p["frames"][0].__setitem__("file", "C:frame_0001.png"),
    ),
    ("an absolute frame name", lambda p: p["frames"][0].__setitem__("file", "/frame_0001.png")),
    ("a hidden frame name", lambda p: p["frames"][0].__setitem__("file", ".frame_0001.png")),
    ("an empty frame name", lambda p: p["frames"][0].__setitem__("file", "")),
    ("a non-string frame name", lambda p: p["frames"][0].__setitem__("file", 7)),
    ("a frame number that is a bool", lambda p: p["frames"][0].__setitem__("frame", True)),
    ("a blank shot id", lambda p: p["frames"][0].__setitem__("shot_id", "")),
    ("beats that are not a list", lambda p: p["frames"][0].__setitem__("source_beat_ids", "b1")),
    ("a non-string beat", lambda p: p["frames"][0]["source_beat_ids"].append(7)),
    ("an extra key on a frame record", lambda p: p["frames"][0].__setitem__("note", "x")),
    ("a missing key on a frame record", lambda p: p["frames"][0].pop("shot_id")),
    ("a wrong format tag", lambda p: p.__setitem__("format", "living_diorama_shot_direction_plan")),
    ("an unsupported schema version", lambda p: p.__setitem__("schema_version", 2)),
    ("an extra top-level key", lambda p: p.__setitem__("notes", "rendered on the good machine")),
    ("a missing top-level key", lambda p: p.pop("emission")),
    ("a missing source key", lambda p: p["source"].pop("catalogue_sha256")),
    ("an extra source key", lambda p: p["source"].__setitem__("operator", "someone")),
    ("a foreign shot plan format", lambda p: p["source"].__setitem__("shot_plan_format", "other")),
    (
        "an unsupported shot plan schema",
        lambda p: p["source"].__setitem__("shot_plan_schema_version", 2),
    ),
    ("a malformed digest", lambda p: p["source"].__setitem__("shot_plan_sha256", "NOTAHASH")),
    ("an uppercase digest", lambda p: p["source"].__setitem__("story_plan_sha256", "A" * 64)),
    ("an episode that skips its predecessor", lambda p: p["source"].__setitem__("episode", 5)),
    ("an unknown mode", lambda p: p["source"].__setitem__("mode", "montage")),
    (
        "a foreign render profile digest",
        lambda p: p["source"].__setitem__("render_profile_sha256", "0" * 64),
    ),
    ("an edited profile body", lambda p: p["profile"]["owned"].__setitem__("cycles_samples", 2048)),
    (
        "a foreign composition source",
        lambda p: p["composition_sources"].__setitem__("master_scene_sha256", "0" * 64),
    ),
    (
        "a missing composition source",
        lambda p: p["composition_sources"].pop("state_response_sha256"),
    ),
    (
        "a timeline that disagrees with itself",
        lambda p: p["timeline"].__setitem__("transition_end", 150),
    ),
    ("a missing timeline key", lambda p: p["timeline"].pop("fps")),
    (
        "an emission claiming 193 playback frames",
        lambda p: p["emission"].update({"frame_count": 193, "final_frame": 193}),
    ),
    (
        "an emission claiming the wrong duration",
        lambda p: p["emission"].__setitem__("playback_seconds", 8.041667),
    ),
    ("an integer duration", lambda p: p["emission"].__setitem__("playback_seconds", 8)),
    (
        "a witness that is not the next frame",
        lambda p: p["emission"].__setitem__("witness_frame", 200),
    ),
    ("a destination that escapes", lambda p: p["destination"].__setitem__("frames_dir", "../out")),
    (
        "a destination naming another episode",
        lambda p: p["destination"].__setitem__("render_id", "episode_0007_to_0008"),
    ),
    ("a missing destination key", lambda p: p["destination"].pop("witness_dir")),
    # ----------------------------------------------------------------------
    # Asymmetries an independent parity audit of V2 found. Each of these was
    # refused by exactly ONE of the two validators, which is the same thing as
    # the production boundary not existing: the plan the engine refuses is the
    # plan Blender would have rendered, or the reverse. They are listed with
    # which side was lenient, because that is the fact worth keeping.
    # ----------------------------------------------------------------------
    (
        "an unapproved camera anchor (Blender was lenient)",
        lambda p: p["frames"][0].__setitem__("camera_anchor_id", "BANANA"),
    ),
    (
        "a negative previous episode (Blender was lenient)",
        lambda p: (
            p["source"].update(episode=0, previous_episode=-1),
            p["destination"].__setitem__("render_id", "episode_-001_to_0000"),
        ),
    ),
    (
        "a negative episode (Blender was lenient)",
        lambda p: (
            p["source"].update(
                mode="baseline", episode=-1, previous_episode=None, before_export_sha256=None
            ),
            p["destination"].__setitem__("render_id", "episode_-001_baseline"),
        ),
    ),
    (
        "a self-consistent alternate clock (Blender was lenient)",
        lambda p: p["timeline"].update(
            start_hold_frames=25, transition_frames=119, transition_start=26
        ),
    ),
    (
        "a whitespace beat id (Blender was lenient)",
        lambda p: p["frames"][30]["source_beat_ids"].append(" x"),
    ),
    (
        "a repeated beat id on one frame (both were lenient)",
        lambda p: p["frames"][30].__setitem__(
            "source_beat_ids", p["frames"][30]["source_beat_ids"] * 2
        ),
    ),
    (
        "a profile value that only deep-equals (the engine was lenient)",
        lambda p: p["profile"]["owned"].__setitem__("pixel_aspect_x", 1),
    ),
    (
        "a parent reference inside a destination name (the engine was lenient)",
        lambda p: p["destination"].__setitem__("frames_dir", "a..b"),
    ),
)


@pytest.mark.parametrize("label,mutate", MUTATIONS, ids=[label for label, _ in MUTATIONS])
def test_both_validators_refuse_the_same_broken_plan(
    render_plan: dict[str, Any], label: str, mutate: Any
) -> None:
    """The mutation table, driven through the engine and the executor alike.

    Neither implementation is allowed to be the lenient one. If this ever fails
    on only one side, the two contracts have started to drift and the
    production boundary is no longer the boundary the engine describes.
    """
    broken = copy.deepcopy(render_plan)
    mutate(broken)

    with pytest.raises((TypeError, ValueError)):
        validate_episode_render_plan(copy.deepcopy(broken))
    with pytest.raises(executor.PlanRefused):
        executor.require_valid_render_plan(copy.deepcopy(broken))


def test_the_approved_anchor_set_is_restated_exactly(render_plan: dict[str, Any]) -> None:
    """The executor cannot import the engine, so its anchor set must be proved equal.

    A restated constant that drifts is worse than no constant: the two sides
    would each be enforcing a rule, and a different one.
    """
    del render_plan
    from living_diorama.cinematic import cinematic_spec

    approved = frozenset(cinematic_spec.ANCHOR_NAMES)
    assert approved == executor.APPROVED_CAMERA_ANCHORS


def test_the_resolved_clock_is_restated_exactly_on_both_sides() -> None:
    """Every copy of every reviewed clock agrees: engine, both appliers, executor.

    The canonical (V1) clock is still asserted against the executor's own
    restated constants byte for byte, and the reviewed V4 clock is asserted
    against every module that restates it -- the engine spec, the direction
    applier and the movement applier -- so a drift in any copy fails loudly.
    """
    from living_diorama.render_execution.render_execution_spec import (
        CANONICAL_MOTION_TIME_SHA256,
        CANONICAL_RESOLVED_TIMELINE,
        DIRECTOR_V4_MOTION_TIME_SHA256,
        DIRECTOR_V4_RESOLVED_TIMELINE,
    )

    reviewed = {
        CANONICAL_MOTION_TIME_SHA256: dict(CANONICAL_RESOLVED_TIMELINE),
        DIRECTOR_V4_MOTION_TIME_SHA256: dict(DIRECTOR_V4_RESOLVED_TIMELINE),
    }

    applier = _load_module("apply_cinematic_direction_pins", CINEMATIC_APPLIER)
    movement = _load_module("apply_camera_movement_pins", CAMERA_MOVEMENT_APPLIER)

    # The closed reviewed mapping agrees across every module that restates it.
    assert set(reviewed) == set(applier.REVIEWED_CLOCKS)
    assert set(reviewed) == set(movement.REVIEWED_CLOCKS)
    for digest, clock in reviewed.items():
        assert clock == dict(applier.REVIEWED_CLOCKS[digest])
        assert clock == dict(movement.REVIEWED_CLOCKS[digest])

    # V1, restated byte for byte on the executor side as well.
    assert dict(CANONICAL_RESOLVED_TIMELINE) == executor.CANONICAL_RESOLVED_TIMELINE
    assert CANONICAL_MOTION_TIME_SHA256 == executor.CANONICAL_MOTION_TIME_SHA256

    # V1 and V4, restated exactly in the direction applier.
    assert dict(CANONICAL_RESOLVED_TIMELINE) == applier.CANONICAL_TIMELINE
    assert CANONICAL_MOTION_TIME_SHA256 == applier.CANONICAL_MOTION_TIME_SHA256
    assert dict(DIRECTOR_V4_RESOLVED_TIMELINE) == applier.DIRECTOR_V4_TIMELINE
    assert DIRECTOR_V4_MOTION_TIME_SHA256 == applier.DIRECTOR_V4_MOTION_TIME_SHA256

    # V1 and V4, restated exactly in the movement applier.
    assert dict(CANONICAL_RESOLVED_TIMELINE) == movement.CANONICAL_TIMELINE
    assert CANONICAL_MOTION_TIME_SHA256 == movement.CANONICAL_MOTION_TIME_SHA256
    assert dict(DIRECTOR_V4_RESOLVED_TIMELINE) == movement.DIRECTOR_V4_TIMELINE
    assert DIRECTOR_V4_MOTION_TIME_SHA256 == movement.DIRECTOR_V4_MOTION_TIME_SHA256


def test_the_pinned_clock_is_what_the_shipped_motion_spec_resolves_to() -> None:
    """Both pins are checked against their sources, not merely against their copies.

    Every copy agreeing proves only that they were typed consistently. This
    re-derives each clock from the bytes Phase 17 ships, under Phase 17's own
    arithmetic, so neither pin can quietly stop describing the document it
    claims to be a reading of.
    """
    from living_diorama.cinematic.shot_planner import build_shot_direction_plan_document
    from living_diorama.render_execution.render_execution_spec import (
        CANONICAL_MOTION_TIME_SHA256,
        CANONICAL_RESOLVED_TIMELINE,
        DIRECTOR_V4_MOTION_TIME_SHA256,
        DIRECTOR_V4_RESOLVED_TIMELINE,
    )

    exports = json.loads((CINEMATIC_FIXTURES / "render_export_ep0.json").read_bytes())
    story = build_episode_story_plan_document(exports)

    motion = MOTION_CONFIG.read_bytes()
    assert hashlib.sha256(motion).hexdigest() == CANONICAL_MOTION_TIME_SHA256
    resolved = build_shot_direction_plan_document(story, motion)["timeline"]
    assert resolved == dict(CANONICAL_RESOLVED_TIMELINE)

    v4 = DIRECTOR_V4_CONFIG.read_bytes()
    assert hashlib.sha256(v4).hexdigest() == DIRECTOR_V4_MOTION_TIME_SHA256
    resolved = build_shot_direction_plan_document(story, v4)["timeline"]
    assert resolved == dict(DIRECTOR_V4_RESOLVED_TIMELINE)


def test_a_v4_bound_shot_plan_builds_and_resolves_to_the_director_clock(
    story_leg1: dict[str, Any],
) -> None:
    """The reviewed V4 document builds a plan on its own resolved clock.

    The plan binds the real V4 digest and restates exactly the clock that
    digest resolves to: transition 25..301 on frame 1..319, i.e. 318 playback
    frames at 24 fps.
    """
    from living_diorama.cinematic.shot_planner import build_shot_direction_plan_document
    from living_diorama.render_execution.render_execution_spec import (
        DIRECTOR_V4_MOTION_TIME_SHA256,
        DIRECTOR_V4_RESOLVED_TIMELINE,
    )

    plan = build_shot_direction_plan_document(story_leg1, DIRECTOR_V4_CONFIG.read_bytes())
    assert plan["source"]["motion_time_sha256"] == DIRECTOR_V4_MOTION_TIME_SHA256
    timeline = plan["timeline"]
    assert timeline["transition_start"] == 25
    assert timeline["transition_end"] == 301
    assert timeline["end_frame"] == 319
    assert timeline == dict(DIRECTOR_V4_RESOLVED_TIMELINE)
    assert timeline["end_frame"] - timeline["start_frame"] == 318


def test_an_unreviewed_v4_derivative_clock_is_still_refused(story_leg1: dict[str, Any]) -> None:
    """The gate admits exactly the two reviewed clocks, never a derivative.

    The V4 document with one phase altered is self-consistent, plausible and
    close to the reviewed source -- and the binding still refuses it, because
    the reviewed set is closed, not a shape test.
    """
    from living_diorama.cinematic.shot_planner import build_shot_direction_plan_document

    document = json.loads(DIRECTOR_V4_CONFIG.read_bytes())
    timeline = document["timeline"]
    timeline["transition_frames"] = 271
    timeline["end_frame"] = (
        timeline["start_frame"]
        + timeline["start_hold_frames"]
        + timeline["transition_frames"]
        + timeline["end_hold_frames"]
    )
    tampered = json.dumps(document, sort_keys=True).encode("utf-8")
    assert tampered != DIRECTOR_V4_CONFIG.read_bytes()
    with pytest.raises(ValueError, match="not the canonical"):
        build_shot_direction_plan_document(story_leg1, tampered)


def test_the_beat_mutations_act_on_a_frame_that_has_beats(render_plan: dict[str, Any]) -> None:
    """A guard on the table above, not a rule about the contract.

    Phase 22's establishing shots legitimately carry no beats, so a mutation
    that appends to or doubles ``source_beat_ids`` on such a frame is a silent
    no-op and its table row would pass without testing anything.
    """
    assert render_plan["frames"][30]["source_beat_ids"]


def test_both_validators_accept_the_canonical_plan(render_plan: dict[str, Any]) -> None:
    """The control: neither side refuses a plan the planner actually produced."""
    assert validate_episode_render_plan(copy.deepcopy(render_plan)) is not None
    assert executor.require_valid_render_plan(copy.deepcopy(render_plan)) is not None


def test_the_reviewers_missing_frame_reproduction_is_refused(
    render_plan: dict[str, Any],
) -> None:
    """Reproduction 1, named explicitly so it can never quietly stop being tested."""
    broken = copy.deepcopy(render_plan)
    del broken["frames"][86]
    broken["emission"]["frame_count"] -= 1
    with pytest.raises(executor.PlanRefused) as refusal:
        executor.require_valid_render_plan(broken)
    assert "emission" in str(refusal.value) or "frames" in str(refusal.value)


def test_the_reviewers_traversal_reproduction_is_refused(
    render_plan: dict[str, Any],
) -> None:
    """Reproduction 2: the frame name that pointed outside the render directory."""
    broken = copy.deepcopy(render_plan)
    broken["frames"][0]["file"] = "../../owned.png"
    with pytest.raises(executor.PlanRefused, match="parent directory|path separator"):
        executor.require_valid_render_plan(broken)


def test_no_directory_is_created_when_a_plan_is_refused(
    render_plan: dict[str, Any], tmp_path: Path
) -> None:
    """A refusal must cost nothing on disk, not even an empty directory."""
    broken = copy.deepcopy(render_plan)
    broken["frames"][0]["file"] = "../../owned.png"
    render_dir = tmp_path / "render"
    with pytest.raises(executor.PlanRefused):
        executor.require_valid_render_plan(broken)
    assert not render_dir.exists()
    assert list(tmp_path.iterdir()) == []


def test_a_frame_table_that_contradicts_the_direction_is_refused(
    render_plan: dict[str, Any], shot_plan_leg1: dict[str, Any]
) -> None:
    """Binding the shot plan proves the pair belongs together, not that it was obeyed."""
    broken = copy.deepcopy(render_plan)
    broken["frames"][60]["camera_anchor_id"] = "CAM_P16_URBAN"
    with pytest.raises(executor.PlanRefused, match="the direction says"):
        executor.require_plan_matches_direction(broken, shot_plan_leg1)


def test_the_canonical_plan_matches_its_direction(
    render_plan: dict[str, Any], shot_plan_leg1: dict[str, Any]
) -> None:
    """The control for the direction cross-check."""
    assert executor.require_plan_matches_direction(render_plan, shot_plan_leg1) is not None


def test_the_executor_pins_the_same_composition_sources_as_the_engine() -> None:
    """Two restatements of one approved bundle; drift here would be silent."""
    from living_diorama.render_execution.render_execution_spec import (
        APPROVED_COMPOSITION_SOURCES,
    )

    assert dict(APPROVED_COMPOSITION_SOURCES) == executor.APPROVED_COMPOSITION_SOURCES


def test_the_executor_pins_the_same_profile_as_the_engine() -> None:
    """The absolute profile pin, restated on the far side of the boundary."""
    from living_diorama.render_execution import render_profile_sha256

    assert render_profile_sha256() == executor.RENDER_PROFILE_SHA256


def test_the_pinned_composition_digests_are_the_shipped_files() -> None:
    """The pins must be digests of what this repository actually ships.

    Without this the constants could drift away from the configs and every
    later check would be comparing a render against a world nobody has.
    """
    import hashlib

    from living_diorama.render_execution.render_execution_spec import (
        APPROVED_COMPOSITION_SOURCES,
        COMPOSITION_SOURCE_FILES,
    )

    config = REPO_ROOT / "visual" / "blender" / "config"
    for key, filename in sorted(COMPOSITION_SOURCE_FILES.items()):
        digest = hashlib.sha256((config / filename).read_bytes()).hexdigest()
        assert digest == APPROVED_COMPOSITION_SOURCES[key], filename


def test_the_plan_binds_the_composition_sources(render_plan: dict[str, Any]) -> None:
    """Every document the world is built from is named in the plan."""
    from living_diorama.render_execution.render_execution_spec import COMPOSITION_SOURCE_KEYS

    assert set(render_plan["composition_sources"]) == set(COMPOSITION_SOURCE_KEYS)
    assert (
        render_plan["composition_sources"]["motion_time_sha256"]
        == render_plan["source"]["motion_time_sha256"]
    )


def test_a_plan_binding_two_different_clocks_is_refused(render_plan: dict[str, Any]) -> None:
    """The clock arrives through two paths; they must be the same document."""
    broken = copy.deepcopy(render_plan)
    broken["source"]["motion_time_sha256"] = "b" * 64
    with pytest.raises(ValueError):
        validate_episode_render_plan(broken)
    with pytest.raises(executor.PlanRefused):
        executor.require_valid_render_plan(copy.deepcopy(broken))


def test_the_executors_refusals_are_all_one_type(render_plan: dict[str, Any]) -> None:
    """Every production refusal is catchable as one thing, and says what was wrong."""
    broken = copy.deepcopy(render_plan)
    broken["format"] = "nonsense"
    with pytest.raises(executor.PlanRefused) as refusal:
        executor.require_valid_render_plan(broken)
    assert "nonsense" in str(refusal.value)
    assert isinstance(refusal.value, ValueError)


def test_the_canonical_plan_round_trips_through_json(render_plan: dict[str, Any]) -> None:
    """The executor reads a parsed document; parsing must not change the verdict."""
    reparsed = json.loads(json.dumps(render_plan))
    assert executor.require_valid_render_plan(reparsed) is not None


# ---------------------------------------------------------------------------
# V2 camera integration: pinned derivations, the executor closure, and the
# Blender-side acceptance of a movement shot, end to end.
# ---------------------------------------------------------------------------


def test_the_movement_camera_name_is_restated_exactly_on_every_side() -> None:
    """Four restatements of one identity; drift would render a wrong camera."""
    from living_diorama.cinematic.cinematic_spec import movement_camera_name as engine_name

    movement = _load_module("apply_camera_movement_pins", CAMERA_MOVEMENT_APPLIER)
    direction = _load_module("apply_cinematic_direction_pins_v2", CINEMATIC_APPLIER)
    for shot_id in ("shot_0001", "shot_0002", "shot_0041"):
        assert (
            engine_name(shot_id)
            == executor._movement_camera_name(shot_id)
            == movement.movement_camera_name(shot_id)
            == direction._movement_camera_name(shot_id)
        )
    assert executor.CAMERA_PREFIX == movement.CAMERA_PREFIX
    assert direction.CAMERA_MOVEMENT_PREFIX == movement.CAMERA_PREFIX
    assert direction.MOVEMENT_MARKER_PREFIX == movement.MARKER_PREFIX


def test_the_movement_catalogue_digest_is_derived_exactly(
    shot_plan_leg1: dict[str, Any], story_leg1: dict[str, Any]
) -> None:
    """The executor recomputes the engine's movement catalogue digest, unchanged."""
    from living_diorama.cinematic.cinematic_spec import movement_catalogue_sha256

    v2 = _v2_shot_plan(shot_plan_leg1)
    plan = _v2_render_plan(v2, story_leg1)
    expected = movement_catalogue_sha256(v2)
    assert plan["source"][executor.MOVEMENT_CATALOGUE_SOURCE_KEY] == expected
    assert executor.require_approved_movement_catalogue(plan, v2) == expected


def test_a_v2_movement_plan_is_accepted_end_to_end_under_v2(
    shot_plan_leg1: dict[str, Any], story_leg1: dict[str, Any]
) -> None:
    """The hard closure: the executor accepts the V2 planner's own output."""
    v2 = _v2_shot_plan(shot_plan_leg1)
    plan = _v2_render_plan(v2, story_leg1)
    assert executor.require_valid_render_plan(copy.deepcopy(plan), camera_profile="v2") is not None
    assert (
        executor.require_plan_matches_shot_plan(copy.deepcopy(plan), v2, camera_profile="v2")
        is not None
    )
    movement_ids = {shot["shot_id"] for shot in v2["shots"] if _shot_moves(shot)}
    assert movement_ids, "the canonical EP1 V2 plan must contain a movement shot"
    for entry in plan["frames"]:
        if entry["shot_id"] in movement_ids:
            assert entry["camera_anchor_id"] == executor._movement_camera_name(entry["shot_id"])
        else:
            shot = next(s for s in v2["shots"] if s["shot_id"] == entry["shot_id"])
            assert entry["camera_anchor_id"] == shot["camera_anchor_id"]


def test_a_v2_movement_plan_is_refused_under_v1(
    shot_plan_leg1: dict[str, Any], story_leg1: dict[str, Any]
) -> None:
    """Movement identities are a V2-only extension: V1 refuses them unchanged."""
    v2 = _v2_shot_plan(shot_plan_leg1)
    plan = _v2_render_plan(v2, story_leg1)
    with pytest.raises(executor.PlanRefused):
        executor.require_valid_render_plan(copy.deepcopy(plan), camera_profile="v1")
    with pytest.raises(executor.PlanRefused):
        executor.require_plan_matches_shot_plan(copy.deepcopy(plan), v2, camera_profile="v1")


def test_a_forged_movement_identity_is_refused_under_v2(
    shot_plan_leg1: dict[str, Any], story_leg1: dict[str, Any]
) -> None:
    """An identity that does not derive from the frame's own shot id is forged."""
    v2 = _v2_shot_plan(shot_plan_leg1)
    plan = _v2_render_plan(v2, story_leg1)
    forged = copy.deepcopy(plan)
    forged["frames"][0]["camera_anchor_id"] = executor._movement_camera_name("shot_9999")
    with pytest.raises(ValueError):
        validate_episode_render_plan(copy.deepcopy(forged), camera_profile="v2")
    with pytest.raises(executor.PlanRefused):
        executor.require_valid_render_plan(copy.deepcopy(forged), camera_profile="v2")
    with pytest.raises(executor.PlanRefused):
        executor.require_plan_matches_shot_plan(copy.deepcopy(forged), v2, camera_profile="v2")


def test_a_forged_movement_catalogue_binding_is_refused(
    shot_plan_leg1: dict[str, Any], story_leg1: dict[str, Any]
) -> None:
    """A plan binding the wrong movement catalogue digest is refused as a preflight."""
    v2 = _v2_shot_plan(shot_plan_leg1)
    plan = _v2_render_plan(v2, story_leg1)
    forged = copy.deepcopy(plan)
    forged["source"][executor.MOVEMENT_CATALOGUE_SOURCE_KEY] = "0" * 64
    with pytest.raises(executor.PlanRefused, match="movement camera catalogue"):
        executor.require_approved_movement_catalogue(forged, v2)


def test_a_v2_profile_accepts_a_plan_without_movement(
    render_plan: dict[str, Any], shot_plan_leg1: dict[str, Any]
) -> None:
    """V2 is additive: a plan with no movement shots validates identically."""
    assert (
        executor.require_valid_render_plan(copy.deepcopy(render_plan), camera_profile="v2")
        is not None
    )
    assert (
        executor.require_plan_matches_shot_plan(
            copy.deepcopy(render_plan), shot_plan_leg1, camera_profile="v2"
        )
        is not None
    )


# ---------------------------------------------------------------------------
# V2 applier glue: a faithful-enough fake bpy for the Blender-side closure
# ---------------------------------------------------------------------------


def _euler_for_view(location: tuple, look_at: tuple) -> tuple:
    """The XYZ euler a look-at camera stores, derived independently."""
    direction = tuple(a - b for a, b in zip(look_at, location, strict=True))
    length = math.sqrt(sum(component**2 for component in direction))
    forward = tuple(component / length for component in direction)
    projected = (
        -forward[2] * forward[0],
        -forward[2] * forward[1],
        1.0 - forward[2] * forward[2],
    )
    magnitude = math.sqrt(sum(component**2 for component in projected))
    up = (0.0, 1.0, 0.0) if magnitude < 1e-6 else tuple(c / magnitude for c in projected)
    z_axis = tuple(-component for component in forward)
    x_axis = (
        up[1] * z_axis[2] - up[2] * z_axis[1],
        up[2] * z_axis[0] - up[0] * z_axis[2],
        up[0] * z_axis[1] - up[1] * z_axis[0],
    )
    rotation = (
        (x_axis[0], up[0], z_axis[0]),
        (x_axis[1], up[1], z_axis[1]),
        (x_axis[2], up[2], z_axis[2]),
    )
    ey = math.asin(max(-1.0, min(1.0, -rotation[2][0])))
    ex = math.atan2(rotation[2][1], rotation[2][2])
    ez = math.atan2(rotation[1][0], rotation[0][0])
    return (ex, ey, ez)


def _rows_from_location_euler(location: tuple, euler: tuple) -> tuple:
    """The 4x4 world-matrix rows of an unparented, unconstrained object."""
    ex, ey, ez = euler
    cx, sx = math.cos(ex), math.sin(ex)
    cy, sy = math.cos(ey), math.sin(ey)
    cz, sz = math.cos(ez), math.sin(ez)
    rotation = (
        (cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx),
        (sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx),
        (-sy, cy * sx, cy * cx),
    )
    return (
        (*rotation[0], location[0]),
        (*rotation[1], location[1]),
        (*rotation[2], location[2]),
        (0.0, 0.0, 0.0, 1.0),
    )


class _FakeDof:
    """The depth-of-field block, reduced to the fields the applier proves."""

    def __init__(self, use_dof: bool, focus_distance: float, aperture_fstop: float) -> None:
        self.use_dof = use_dof
        self.focus_distance = focus_distance
        self.aperture_fstop = aperture_fstop
        self.aperture_ratio = 1.0
        self.aperture_blades = 0
        self.aperture_rotation = 0.0
        self.focus_object = None


class _FakeCameraData:
    """A camera datablock serving both appliers: lensed identity and keyframe log."""

    def __init__(self, lens: float, clip_end: float, dof: _FakeDof, name: str = "") -> None:
        self.name = name
        self.lens = lens
        self.clip_start = 0.1
        self.clip_end = clip_end
        self.type = "PERSP"
        self.sensor_width = 36.0
        self.sensor_height = 24.0
        self.sensor_fit = "AUTO"
        self.shift_x = 0.0
        self.shift_y = 0.0
        self.dof = dof
        self.animation_data = None


class _FakeFCurve:
    """One F-curve record: data path, frame, extrapolation mode."""

    def __init__(self, data_path: str, frame: int) -> None:
        self.data_path = data_path
        self.frame = frame
        self.extrapolation = "CONSTANT"  # Blender's real default for a new curve


class _FakeAction:
    """The action an object earns once it holds F-curves."""

    def __init__(self) -> None:
        self.fcurves: list[_FakeFCurve] = []


class _FakeAnimationData:
    """The animation-data block Blender creates at the first ``keyframe_insert``."""

    def __init__(self) -> None:
        self.action = _FakeAction()


class _FakeObject:
    """A scene object: name, type, transform, and a keyframe log."""

    def __init__(
        self,
        name: str,
        data: _FakeCameraData | None = None,
        location: tuple = (0.0, 0.0, 0.0),
        rotation_euler: tuple = (0.0, 0.0, 0.0),
    ) -> None:
        self.name = name
        self.type = "CAMERA" if data is not None else "EMPTY"
        self.data = data
        self.location = location
        self.rotation_euler = rotation_euler
        self.rotation_mode = "XYZ"
        self.scale = (1.0, 1.0, 1.0)
        self.animation_data = None
        self.parent = None
        self.constraints = []
        self.delta_location = (0.0, 0.0, 0.0)
        self.delta_rotation_euler = (0.0, 0.0, 0.0)
        self.delta_rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        self.delta_scale = (1.0, 1.0, 1.0)
        self.keyframes: list = []

    @property
    def matrix_world(self) -> tuple:
        """The evaluated matrix of the unparented, delta-free case."""
        return _rows_from_location_euler(self.location, self.rotation_euler)

    def keyframe_insert(self, field: str, frame: int | None = None) -> None:
        """Record one keyframe insertion, exactly as real Blender's side effects do.

        The first call creates ``animation_data``/its action; every call
        (first or not) appends one F-curve record, mirroring
        ``tests/cinematic/test_apply_camera_movement.py``'s fake so both
        harnesses agree on what a keyframed object looks like afterward.
        """
        self.keyframes.append((field, frame))
        if self.animation_data is None:
            self.animation_data = _FakeAnimationData()
        self.animation_data.action.fcurves.append(_FakeFCurve(field, frame))


def _fake_anchor(name: str, record: dict) -> _FakeObject:
    """Build one fake anchor exactly as the world builders would."""
    focus_distance = math.sqrt(
        sum((a - b) ** 2 for a, b in zip(record["focus"], record["location"], strict=True))
    )
    dof = _FakeDof(bool(record["dof"]), focus_distance, float(record["f_stop"]))
    data = _FakeCameraData(float(record["lens_mm"]), float(record["clip_end"]), dof)
    return _FakeObject(
        name,
        data,
        location=tuple(record["location"]),
        rotation_euler=_euler_for_view(record["location"], record["look_at"]),
    )


class _FakeMarker:
    """A timeline marker binding a frame to a camera."""

    def __init__(self, name: str, frame: int) -> None:
        self.name = name
        self.frame = frame
        self.camera: _FakeObject | None = None


class _FakeMarkers:
    """The marker factory: appendable, removable, iterable, countable."""

    def __init__(self) -> None:
        self._markers: list[_FakeMarker] = []

    def new(self, name: str, frame: int) -> _FakeMarker:
        marker = _FakeMarker(name, frame)
        self._markers.append(marker)
        return marker

    def remove(self, marker: _FakeMarker) -> None:
        self._markers.remove(marker)

    def __iter__(self):
        return iter(list(self._markers))

    def __len__(self) -> int:
        return len(self._markers)


class _FakeRender:
    """The render settings the direction applier's execution-clock gate reads."""

    def __init__(self) -> None:
        self.fps = 24
        self.fps_base = 1.0
        self.frame_map_old = 100
        self.frame_map_new = 100
        self.use_sequencer = True
        self.use_multiview = False
        self.pixel_aspect_x = 1.0
        self.pixel_aspect_y = 1.0


class _FakeViewLayer:
    """The view layer, reduced to the update call both appliers make."""

    def update(self) -> None:
        pass


class _FakeScene:
    """A scene with the locked EP1 frame range, markers and an active camera."""

    def __init__(self) -> None:
        self.frame_start = 1
        self.frame_end = 193
        self.frame_step = 1
        self.render = _FakeRender()
        self.sequence_editor = None
        self.timeline_markers = _FakeMarkers()
        self.camera: _FakeObject | None = None


class _FakeCameras:
    """The camera datablock factory: ``bpy.data.cameras``."""

    def __init__(self, owner: "_FakeData") -> None:
        self.owner = owner

    def new(self, name: str) -> _FakeCameraData:
        data = _FakeCameraData(0.0, 0.0, _FakeDof(False, 0.0, 0.0), name=name)
        self.owner.camera_data.append(data)
        return data


class _FakeObjects:
    """The scene-object factory: ``bpy.data.objects``, linkable and iterable."""

    def __init__(self, owner: "_FakeData") -> None:
        self.owner = owner

    def new(self, name: str, data: _FakeCameraData | None) -> _FakeObject:
        obj = _FakeObject(name, data)
        self.owner.objects_flat.append(obj)
        return obj

    def __iter__(self):
        return iter(self.owner.objects_flat)


class _FakeCollectionObjects:
    """The linkable object set: ``collection.objects``."""

    def __init__(self) -> None:
        self.linked: list[_FakeObject] = []

    def link(self, obj: _FakeObject) -> None:
        self.linked.append(obj)


class _FakeCollection:
    """The active collection new objects are linked into."""

    def __init__(self) -> None:
        self.objects = _FakeCollectionObjects()


class _FakeContext:
    """``bpy.context``, reduced to what both appliers touch."""

    def __init__(self, scene: _FakeScene) -> None:
        self.scene = scene
        self.collection = _FakeCollection()
        self.view_layer = _FakeViewLayer()


class _FakeData:
    """``bpy.data``, reduced to what both appliers touch."""

    def __init__(self) -> None:
        self.objects = _FakeObjects(self)
        self.cameras = _FakeCameras(self)
        self.camera_data: list[_FakeCameraData] = []
        self.objects_flat: list[_FakeObject] = []


class _FakeBpy:
    """The parts of ``bpy`` both appliers touch, wired together."""

    def __init__(self, objects: list[_FakeObject], scene: _FakeScene) -> None:
        self.data = _FakeData()
        self.data.objects_flat = list(objects)
        self.context = _FakeContext(scene)


def _v2_fake_bpy() -> tuple[_FakeBpy, _FakeScene]:
    """A fake Blender holding every fixed anchor at its locked pose."""
    from living_diorama.cinematic.cinematic_spec import CAMERA_ANCHORS

    scene = _FakeScene()
    objects = [_fake_anchor(name, dict(record)) for name, record in CAMERA_ANCHORS.items()]
    return _FakeBpy(objects, scene), scene


def test_v2_direction_end_to_end_over_a_fake_blender(
    shot_plan_leg1: dict[str, Any], story_leg1: dict[str, Any]
) -> None:
    """Movement cameras are created before direction, and direction honours them."""
    from living_diorama.cinematic.cinematic_spec import catalogue_document

    v2 = _v2_shot_plan(shot_plan_leg1)
    bpy, scene = _v2_fake_bpy()
    episode_scene = _load_module("episode_scene_v2_pins", EPISODE_SCENE)
    report = episode_scene.direct_episode_world(bpy, v2, catalogue_document(), camera_profile="v2")

    movement_shots = [shot for shot in v2["shots"] if _shot_moves(shot)]
    fixed_shots = [shot for shot in v2["shots"] if not _shot_moves(shot)]
    assert movement_shots, "the canonical EP1 V2 plan must contain a movement shot"

    # Exactly the non-movement shots earn a Phase 22 P22_SHOT_ marker.
    assert report["markers_bound"] == len(fixed_shots)
    shot_markers = [m for m in scene.timeline_markers if m.name.startswith("P22_SHOT_")]
    assert len(shot_markers) == len(fixed_shots)

    # Every movement shot earned one new camera and one P22_MOVE_ marker.
    movement_names = {executor._movement_camera_name(s["shot_id"]) for s in movement_shots}
    assert movement_names <= {obj.name for obj in bpy.data.objects}
    move_markers = [m for m in scene.timeline_markers if m.name.startswith("P22_MOVE_")]
    assert {m.camera.name for m in move_markers} == movement_names

    # No two markers compete for one frame.
    frames = [m.frame for m in scene.timeline_markers]
    assert len(frames) == len(set(frames))

    # The scene's active camera is the opening movement camera.
    assert scene.camera is not None
    assert scene.camera.name == report["opening_camera"]
    assert scene.camera.name == executor._movement_camera_name(v2["shots"][0]["shot_id"])

    # The same scene, with the movement cameras removed, is REFUSED under V1:
    # its P22_MOVE_ markers are foreign there, exactly as the phase boundary
    # intends -- the carve-out is V2-only.
    v1_objects = [obj for obj in bpy.data.objects if not obj.name.startswith("CAM_MOVEMENT_")]
    direction = _load_module("apply_cinematic_direction_v1_recheck", CINEMATIC_APPLIER)
    v1_bpy = _FakeBpy(v1_objects, scene)
    with pytest.raises(direction.CinematicApplyError, match="foreign camera-bound"):
        direction.apply_shot_direction_plan(v1_bpy, v2, catalogue_document())


def test_a_movement_marker_is_foreign_under_v1(shot_plan_leg1: dict[str, Any]) -> None:
    """The P22_MOVE_ carve-out is V2-only: under V1 a movement marker is foreign."""
    from living_diorama.cinematic.cinematic_spec import catalogue_document

    direction = _load_module("apply_cinematic_direction_pins_v1", CINEMATIC_APPLIER)
    bpy, scene = _v2_fake_bpy()
    marker = scene.timeline_markers.new("P22_MOVE_shot_0001", frame=25)
    marker.camera = next(obj for obj in bpy.data.objects if obj.name == "CAM_HERO_SCAR")
    with pytest.raises(direction.CinematicApplyError, match="foreign camera-bound"):
        direction.apply_shot_direction_plan(bpy, shot_plan_leg1, catalogue_document())
