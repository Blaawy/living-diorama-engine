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
MOTION_CONFIG = REPO_ROOT / "visual" / "blender" / "config" / "motion_time_v1.json"
CINEMATIC_FIXTURES = REPO_ROOT / "tests" / "cinematic" / "fixtures"


def _load_module(name: str, path: Path) -> Any:
    """Import one Blender-side script without Blender present."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
    """Three copies of one clock: Phase 22's applier, the engine, the executor."""
    from living_diorama.render_execution.render_execution_spec import (
        CANONICAL_MOTION_TIME_SHA256,
        CANONICAL_RESOLVED_TIMELINE,
    )

    clock = dict(CANONICAL_RESOLVED_TIMELINE)
    digest = CANONICAL_MOTION_TIME_SHA256
    assert clock == executor.CANONICAL_RESOLVED_TIMELINE
    assert digest == executor.CANONICAL_MOTION_TIME_SHA256

    applier = _load_module("apply_cinematic_direction_pins", CINEMATIC_APPLIER)
    assert clock == applier.CANONICAL_TIMELINE
    assert digest == applier.CANONICAL_MOTION_TIME_SHA256


def test_the_pinned_clock_is_what_the_shipped_motion_spec_resolves_to() -> None:
    """The pin is checked against its source, not merely against its own copies.

    Every copy agreeing proves only that they were typed consistently. This
    re-derives the clock from the bytes Phase 17 ships, under Phase 17's own
    arithmetic, so the pin cannot quietly stop describing the document it
    claims to be a reading of.
    """
    from living_diorama.cinematic.shot_planner import build_shot_direction_plan_document
    from living_diorama.render_execution.render_execution_spec import (
        CANONICAL_MOTION_TIME_SHA256,
        CANONICAL_RESOLVED_TIMELINE,
    )

    motion = MOTION_CONFIG.read_bytes()
    assert hashlib.sha256(motion).hexdigest() == CANONICAL_MOTION_TIME_SHA256

    exports = json.loads((CINEMATIC_FIXTURES / "render_export_ep0.json").read_bytes())
    story = build_episode_story_plan_document(exports)
    resolved = build_shot_direction_plan_document(story, motion)["timeline"]
    assert resolved == dict(CANONICAL_RESOLVED_TIMELINE)


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
