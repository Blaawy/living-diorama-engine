"""Shared fixtures for the Phase 24 narration tests.

The exports under ``fixtures/`` are the same genuine Render Export V1 documents
Phases 21 and 22 test against, produced by the real engine. Story plans are
derived from them at test time by the locked Phase 21 layer and directed by the
locked Phase 22 layer, so what these tests narrate is whatever those layers
actually say -- never a hand-authored story or a hand-authored cut.

That matters more here than anywhere upstream. The canonical chain's episode
1 -> 2 transition produces a PRIMARY ``CONSEQUENCE_PERSISTED`` beat that Phase 22
honestly leaves unshown, because no approved camera can see the memory register.
It is the case this whole layer exists for, and it is real history rather than a
fixture written to make the point.
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from living_diorama.cinematic import build_shot_direction_plan_document
from living_diorama.narration import build_episode_narration_plan_document
from living_diorama.story import build_episode_story_plan_document

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]
MOTION_CONFIG = REPO_ROOT / "visual" / "blender" / "config" / "motion_time_v1.json"


def load_export(episode: int) -> dict[str, Any]:
    """Return an independent copy of one fixture render export."""
    return json.loads((FIXTURES / f"render_export_ep{episode}.json").read_text(encoding="utf-8"))


def build_sources(episode: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return the (story, shots, export) triple for one canonical episode.

    ``episode`` 0 is the baseline; 1 and 2 are transitions from the episode
    before them. The export returned is the *current* one, which is the only
    export this layer takes.
    """
    export = load_export(episode)
    previous = load_export(episode - 1) if episode else None
    story = build_episode_story_plan_document(copy.deepcopy(export), previous)
    shots = build_shot_direction_plan_document(story, MOTION_CONFIG.read_bytes())
    return story, shots, copy.deepcopy(export)


def build_plan(episode: int) -> dict[str, Any]:
    """Return the narration plan for one canonical episode."""
    story, shots, export = build_sources(episode)
    return build_episode_narration_plan_document(story, shots, export)


@pytest.fixture(scope="session")
def motion_time() -> bytes:
    """The exact bytes of the shipped Phase 17 Motion & Time Spec."""
    return MOTION_CONFIG.read_bytes()


@pytest.fixture
def sources_ep0() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Episode 0 baseline: the story that reports nothing was emphasized."""
    return build_sources(0)


@pytest.fixture
def sources_ep1() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Episode 0 -> 1: the law is suspended, the wall rises, the fact is unshown."""
    return build_sources(1)


@pytest.fixture
def sources_ep2() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Episode 1 -> 2: the law returns, the wall remains, and nobody is shown it."""
    return build_sources(2)


@pytest.fixture
def plan_ep0() -> dict[str, Any]:
    """The narration plan for the baseline episode."""
    return build_plan(0)


@pytest.fixture
def plan_ep1() -> dict[str, Any]:
    """The narration plan for the episode the wall was built in."""
    return build_plan(1)


@pytest.fixture
def plan_ep2() -> dict[str, Any]:
    """The narration plan for the episode the consequence persisted in."""
    return build_plan(2)
