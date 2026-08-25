"""Shared fixtures for the Phase 26 language realization tests.

The exports under ``fixtures/`` are the same genuine Render Export V1
documents Phases 21, 22, 24 and 25 test against, produced by the real engine.
Story plans are derived from them at test time by the locked Phase 21 layer,
directed by the locked Phase 22 layer, and narrated by the locked Phase 24
layer, so what these tests realize is whatever those layers actually say --
never a hand-authored story, cut or sentence.

The shot plan appears here only as scaffolding: the locked narration planner
requires it. The realization layer itself never sees it, which is exactly the
point -- a realization is derivable, and provable, from narration, story and
export alone.
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from living_diorama.cinematic import build_shot_direction_plan_document
from living_diorama.language_realization import (
    build_episode_language_realization_plan_document,
)
from living_diorama.narration import build_episode_narration_plan_document
from living_diorama.story import build_episode_story_plan_document

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]
MOTION_CONFIG = REPO_ROOT / "visual" / "blender" / "config" / "motion_time_v1.json"


def load_export(episode: int) -> dict[str, Any]:
    """Return an independent copy of one fixture render export."""
    return json.loads((FIXTURES / f"render_export_ep{episode}.json").read_text(encoding="utf-8"))


def build_realization_sources(
    episode: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return the (narration, story, export) triple for one canonical episode.

    ``episode`` 0 is the baseline; 1 and 2 are transitions from the episode
    before them. All documents come out of the locked upstream planners, so
    they are exactly what the realization layer will meet in production.
    """
    export = load_export(episode)
    previous = load_export(episode - 1) if episode else None
    story = build_episode_story_plan_document(copy.deepcopy(export), previous)
    shots = build_shot_direction_plan_document(story, MOTION_CONFIG.read_bytes())
    narration = build_episode_narration_plan_document(story, shots, copy.deepcopy(export))
    return narration, story, export


def build_plan(episode: int) -> dict[str, Any]:
    """Return the language realization plan for one canonical episode."""
    narration, story, export = build_realization_sources(episode)
    return build_episode_language_realization_plan_document(narration, story, export)


@pytest.fixture
def sources_ep0() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Episode 0 baseline: one absence unit, no facts, no events."""
    return build_realization_sources(0)


@pytest.fixture
def sources_ep1() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Episode 0 -> 1: a law change, the wall fact, and a wall state change."""
    return build_realization_sources(1)


@pytest.fixture
def sources_ep2() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Episode 1 -> 2: the persisted consequence and a wall state change."""
    return build_realization_sources(2)


@pytest.fixture
def plan_ep0() -> dict[str, Any]:
    """The realization plan for the baseline episode."""
    return build_plan(0)


@pytest.fixture
def plan_ep1() -> dict[str, Any]:
    """The realization plan for the episode the wall was built in."""
    return build_plan(1)


@pytest.fixture
def plan_ep2() -> dict[str, Any]:
    """The realization plan for the episode the consequence persisted in."""
    return build_plan(2)
