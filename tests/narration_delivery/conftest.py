"""Shared fixtures for the Phase 25 narration delivery tests.

The exports under ``fixtures/`` are the same genuine Render Export V1 documents
Phases 21, 22 and 24 test against, produced by the real engine. Story plans are
derived from them at test time by the locked Phase 21 layer, directed by the
locked Phase 22 layer, and narrated by the locked Phase 24 layer, so what these
tests schedule is whatever those layers actually say -- never a hand-authored
story, cut or sentence.

That matters more here than anywhere upstream. The canonical episode 0 -> 1
transition puts a PRIMARY ``DURABLE_CONSEQUENCE`` unit between two shown units
whose beat shots are frame-adjacent -- zero free frames -- which is the exact
case the backward fold exists for. It is real history, not a fixture written to
make the point.
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from living_diorama.cinematic import build_shot_direction_plan_document
from living_diorama.narration import build_episode_narration_plan_document
from living_diorama.narration_delivery import build_episode_narration_delivery_plan_document
from living_diorama.story import build_episode_story_plan_document

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]
MOTION_CONFIG = REPO_ROOT / "visual" / "blender" / "config" / "motion_time_v1.json"


def load_export(episode: int) -> dict[str, Any]:
    """Return an independent copy of one fixture render export."""
    return json.loads((FIXTURES / f"render_export_ep{episode}.json").read_text(encoding="utf-8"))


def build_delivery_sources(episode: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the (narration, shots) pair for one canonical episode.

    ``episode`` 0 is the baseline; 1 and 2 are transitions from the episode
    before them. Both documents come out of the locked upstream planners, so
    they are exactly what the delivery layer will meet in production.
    """
    export = load_export(episode)
    previous = load_export(episode - 1) if episode else None
    story = build_episode_story_plan_document(copy.deepcopy(export), previous)
    shots = build_shot_direction_plan_document(story, MOTION_CONFIG.read_bytes())
    narration = build_episode_narration_plan_document(story, shots, copy.deepcopy(export))
    return narration, shots


def build_plan(episode: int) -> dict[str, Any]:
    """Return the narration delivery plan for one canonical episode."""
    narration, shots = build_delivery_sources(episode)
    return build_episode_narration_delivery_plan_document(narration, shots)


@pytest.fixture(scope="session")
def motion_time() -> bytes:
    """The exact bytes of the shipped Phase 17 Motion & Time Spec."""
    return MOTION_CONFIG.read_bytes()


@pytest.fixture
def sources_ep0() -> tuple[dict[str, Any], dict[str, Any]]:
    """Episode 0 baseline: one unshown unit, one establishing shot, no anchor."""
    return build_delivery_sources(0)


@pytest.fixture
def sources_ep1() -> tuple[dict[str, Any], dict[str, Any]]:
    """Episode 0 -> 1: the trapped PRIMARY consequence and the backward fold."""
    return build_delivery_sources(1)


@pytest.fixture
def sources_ep2() -> tuple[dict[str, Any], dict[str, Any]]:
    """Episode 1 -> 2: the persisted consequence leading the episode, unshown."""
    return build_delivery_sources(2)


@pytest.fixture
def plan_ep0() -> dict[str, Any]:
    """The delivery plan for the baseline episode."""
    return build_plan(0)


@pytest.fixture
def plan_ep1() -> dict[str, Any]:
    """The delivery plan for the episode the wall was built in."""
    return build_plan(1)


@pytest.fixture
def plan_ep2() -> dict[str, Any]:
    """The delivery plan for the episode the consequence persisted in."""
    return build_plan(2)
