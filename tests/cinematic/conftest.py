"""Shared fixtures for the Phase 22 cinematic tests.

The exports under ``fixtures/`` are the same genuine Render Export V1 documents
Phase 21 tests against, produced by the real engine. Story plans are derived from
them at test time by the locked Phase 21 layer, so what these tests direct is
whatever Phase 21 actually says -- never a hand-authored story.

The clock is the real Phase 17 Motion & Time Spec: the tests read the exact
bytes of the shipped ``motion_time_v1.json`` and hand them to the layer, which
is precisely the contract the CLI and the Blender gate exercise. Tests that need
an *illegitimate* clock build alternate documents explicitly, so every deviation
from the canonical clock in this suite is deliberate and visible.
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from living_diorama.cinematic import build_shot_direction_plan_document, resolve_motion_time_binding
from living_diorama.cinematic.cinematic_spec import catalogue_sha256
from living_diorama.story import build_episode_story_plan_document

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]
MOTION_CONFIG = REPO_ROOT / "visual" / "blender" / "config" / "motion_time_v1.json"


def _load(episode: int) -> dict[str, Any]:
    return json.loads((FIXTURES / f"render_export_ep{episode}.json").read_text(encoding="utf-8"))


def alternate_motion_time(**overrides: int) -> bytes:
    """Return a self-consistent Motion & Time Spec with a noncanonical timeline.

    Starts from the shipped document, applies the given timeline field
    overrides, and recomputes ``end_frame`` so the result passes Phase 17's own
    arithmetic -- plausible on its face, wrong only because it is not the locked
    clock. Since V3 pins the canonical source digest, every document this
    builder returns is REFUSED by the binding; the tests use it to prove
    exactly that.
    """
    document = json.loads(MOTION_CONFIG.read_bytes().decode("utf-8"))
    timeline = document["timeline"]
    timeline.update(overrides)
    timeline["end_frame"] = (
        timeline["start_frame"]
        + timeline["start_hold_frames"]
        + timeline["transition_frames"]
        + timeline["end_hold_frames"]
    )
    return json.dumps(document, sort_keys=True).encode("utf-8")


def synthetic_wide_story(beat_count: int = 22) -> dict[str, Any]:
    """Return a valid transition story with more beat groups than fit.

    The canonical transition holds 120 frames -- capacity for twenty
    minimum-length shots -- and the real three-episode chain never exceeds two
    groups, so the budget-exhausted path needs a story wider than history has
    yet produced. This builds one that passes Phase 21's own validator: kinds
    alternate between LAW_CHANGE and WALL_RAISED (whose anchors differ, so no
    two adjacent beats merge), every beat is PRIMARY (the only emphasis those
    kinds permit, and constant emphasis satisfies strongest-first ordering),
    each cites one distinct event of the matching type, and the source binding
    accounts for exactly those events. Structural hashes are synthetic -- the
    story validator checks their shape, and Phase 22 binds whatever story it
    is offered by digest.
    """
    beats = []
    for position in range(beat_count):
        law = position % 2 == 0
        kind = "LAW_CHANGE" if law else "WALL_RAISED"
        beats.append(
            {
                "beat_id": f"beat_{position + 1:04d}",
                "emphasis": "PRIMARY",
                "evidence": [
                    {
                        "index": position,
                        "kind": "event",
                        "source_id": "law_movement" if law else "wall_boundary_ab",
                        "tick": position + 1,
                        "type": "LAW_CHANGED" if law else "WALL_BUILT",
                    }
                ],
                "kind": kind,
                "rank": position + 1,
                "reason_code": "EVENT_TYPE_RULE",
                "subject_ids": ["law_movement" if law else "wall_boundary_ab"],
            }
        )
    return {
        "beats": beats,
        "excluded": {},
        "format": "living_diorama_episode_story_plan",
        "schema_version": 1,
        "source": {
            "current": {
                "document_sha256": "c" * 64,
                "episode": 1,
                "event_count": beat_count,
                "parent_state_hash": "b" * 64,
                "state_hash": "a" * 64,
                "tick": beat_count + 10,
            },
            "mode": "transition",
            "previous": {
                "document_sha256": "d" * 64,
                "episode": 0,
                "event_count": 0,
                "parent_state_hash": None,
                "state_hash": "b" * 64,
                "tick": 5,
            },
            "render_schema_version": 1,
        },
        "unclassified": [],
    }


@pytest.fixture
def story_wide() -> dict[str, Any]:
    """A valid 22-beat transition story that overflows the canonical budget."""
    return synthetic_wide_story()


@pytest.fixture
def story_adjacent() -> dict[str, Any]:
    """A valid story whose two beats share one anchor and merge into one shot.

    LAW_CHANGE then LAW_RESTORATION -- both PRIMARY, both framed at the Seal --
    so the planner's adjacent-anchor merge produces a genuine two-beat shot.
    The canonical chain no longer yields one (the durable-consequence beat is
    deliberately unshown), so merged-shot rules are exercised here.
    """
    story = synthetic_wide_story(beat_count=2)
    second = story["beats"][1]
    second["kind"] = "LAW_RESTORATION"
    second["evidence"][0]["type"] = "LAW_RESTORED"
    second["evidence"][0]["source_id"] = "law_movement"
    second["subject_ids"] = ["law_movement"]
    return story


@pytest.fixture
def alternate_clock() -> Any:
    """The alternate-document builder, exposed as a fixture.

    A fixture rather than a bare import because ``tests/story`` and
    ``tests/cinematic`` each carry a ``conftest`` and rootdir-style test runs
    put both directories on ``sys.path``, where a plain ``import conftest``
    would be ambiguous.
    """
    return alternate_motion_time


@pytest.fixture(scope="session")
def _raw_exports() -> dict[int, dict[str, Any]]:
    return {episode: _load(episode) for episode in (0, 1, 2)}


@pytest.fixture(scope="session")
def motion_time() -> bytes:
    """The exact bytes of the shipped Phase 17 Motion & Time Spec."""
    return MOTION_CONFIG.read_bytes()


@pytest.fixture
def timeline(motion_time: bytes) -> dict[str, int]:
    """The resolved canonical clock, for asserting frame arithmetic against."""
    binding = resolve_motion_time_binding(motion_time)
    return dict(binding["timeline"])  # type: ignore[arg-type]


@pytest.fixture
def story_ep0(_raw_exports: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Episode 0 baseline: the story plan that reports nothing was emphasized."""
    return build_episode_story_plan_document(copy.deepcopy(_raw_exports[0]))


@pytest.fixture
def story_ep0_to_ep1(_raw_exports: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Episode 0 -> 1: the law is suspended and the wall rises."""
    return build_episode_story_plan_document(
        copy.deepcopy(_raw_exports[1]), copy.deepcopy(_raw_exports[0])
    )


@pytest.fixture
def story_ep1_to_ep2(_raw_exports: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Episode 1 -> 2: the law returns and the wall remains."""
    return build_episode_story_plan_document(
        copy.deepcopy(_raw_exports[2]), copy.deepcopy(_raw_exports[1])
    )


@pytest.fixture
def plan_ep1(story_ep0_to_ep1: dict[str, Any], motion_time: bytes) -> dict[str, Any]:
    """The genuine four-shot episode 0 -> 1 shot direction plan."""
    return build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)


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
def synthetic_720() -> dict[str, Any]:
    """The synthetic-but-structurally-identical 720-frame EP1-scale plan."""
    return synthetic_720_shot_plan()
