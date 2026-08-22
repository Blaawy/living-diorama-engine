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

from living_diorama.cinematic import resolve_motion_time_binding
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
