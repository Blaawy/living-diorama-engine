"""Shared fixtures for the Phase 27 presentation tests.

The exports under ``fixtures/`` are the same genuine Render Export V1
documents Phases 21, 22, 24, 25 and 26 test against, produced by the real
engine. Story plans, shot plans, narration plans, delivery plans and
realization plans are all derived from them at test time by the locked
upstream layers, so what these tests present is whatever those layers
actually say -- never a hand-authored story, cut, sentence or slot.

The story plan, shot plan and render export are supplied here because the
Phase 27 cross-check needs them to run the two locked upstream
source-verification gates. Presentation itself never reads them for anything
but that: no presentation fixture, planner call or assertion in this suite
ever inspects a story beat or an export event directly.
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from living_diorama.cinematic import build_shot_direction_plan_document
from living_diorama.language_realization import build_episode_language_realization_plan_document
from living_diorama.narration import build_episode_narration_plan_document
from living_diorama.narration_delivery import build_episode_narration_delivery_plan_document
from living_diorama.presentation import build_episode_presentation_plan_document
from living_diorama.story import build_episode_story_plan_document

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]
MOTION_CONFIG = REPO_ROOT / "visual" / "blender" / "config" / "motion_time_v1.json"


def load_export(episode: int) -> dict[str, Any]:
    """Return an independent copy of one fixture render export."""
    return json.loads((FIXTURES / f"render_export_ep{episode}.json").read_text(encoding="utf-8"))


def build_presentation_sources(
    episode: int,
) -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    """Return the (delivery, narration, shots, realization, story, export) six-tuple.

    ``episode`` 0 is the baseline; 1 and 2 are transitions from the episode
    before them. Every document comes out of the locked upstream planners, so
    this is exactly what the presentation layer will meet in production.
    """
    export = load_export(episode)
    previous = load_export(episode - 1) if episode else None
    story = build_episode_story_plan_document(copy.deepcopy(export), previous)
    shots = build_shot_direction_plan_document(story, MOTION_CONFIG.read_bytes())
    narration = build_episode_narration_plan_document(story, shots, copy.deepcopy(export))
    delivery = build_episode_narration_delivery_plan_document(narration, shots)
    realization = build_episode_language_realization_plan_document(
        narration, story, copy.deepcopy(export)
    )
    return delivery, narration, shots, realization, story, export


def build_plan(episode: int) -> dict[str, Any]:
    """Return the presentation plan for one canonical episode."""
    delivery, narration, _shots, realization, _story, _export = build_presentation_sources(episode)
    return build_episode_presentation_plan_document(delivery, narration, realization)


@pytest.fixture(scope="session")
def motion_time() -> bytes:
    """The exact bytes of the shipped Phase 17 Motion & Time Spec."""
    return MOTION_CONFIG.read_bytes()


@pytest.fixture
def sources_ep0() -> tuple[dict[str, Any], ...]:
    """Episode 0 baseline: one whole-domain template unit, no hold."""
    return build_presentation_sources(0)


@pytest.fixture
def sources_ep1() -> tuple[dict[str, Any], ...]:
    """Episode 0 -> 1: two template units and one fact-backed, all three held."""
    return build_presentation_sources(1)


@pytest.fixture
def sources_ep2() -> tuple[dict[str, Any], ...]:
    """Episode 1 -> 2: a fact-backed unit leading, then a template unit."""
    return build_presentation_sources(2)


@pytest.fixture
def plan_ep0() -> dict[str, Any]:
    """The presentation plan for the baseline episode."""
    return build_plan(0)


@pytest.fixture
def plan_ep1() -> dict[str, Any]:
    """The presentation plan for the episode the wall was built in."""
    return build_plan(1)


@pytest.fixture
def plan_ep2() -> dict[str, Any]:
    """The presentation plan for the episode the consequence persisted in."""
    return build_plan(2)
