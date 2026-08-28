"""Shared fixtures for the Phase 32 caption tests.

The exports under ``fixtures/`` are byte-identical copies of the Phase 27
suite's own render exports. Story, shot, narration, delivery, realization
and presentation plans are all derived from them at test time by the real
locked upstream builders. No audio artifact of any kind appears in this
suite.
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


def build_sources(
    episode: int,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    """Return the (realization, presentation, delivery, narration, shots, story, export) tuple."""
    export = load_export(episode)
    previous = load_export(episode - 1) if episode else None
    story = build_episode_story_plan_document(copy.deepcopy(export), previous)
    shots = build_shot_direction_plan_document(story, MOTION_CONFIG.read_bytes())
    narration = build_episode_narration_plan_document(story, shots, copy.deepcopy(export))
    delivery = build_episode_narration_delivery_plan_document(narration, shots)
    realization = build_episode_language_realization_plan_document(
        narration, story, copy.deepcopy(export)
    )
    presentation = build_episode_presentation_plan_document(delivery, narration, realization)
    return realization, presentation, delivery, narration, shots, story, export


@pytest.fixture
def sources_ep0() -> tuple[dict[str, Any], ...]:
    """Sources ep0."""
    return build_sources(0)


@pytest.fixture
def sources_ep1() -> tuple[dict[str, Any], ...]:
    """Sources ep1."""
    return build_sources(1)


@pytest.fixture
def sources_ep2() -> tuple[dict[str, Any], ...]:
    """Sources ep2."""
    return build_sources(2)


@pytest.fixture
def realization_ep0(sources_ep0: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Realization ep0."""
    return sources_ep0[0]


@pytest.fixture
def realization_ep1(sources_ep1: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Realization ep1."""
    return sources_ep1[0]


@pytest.fixture
def realization_ep2(sources_ep2: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Realization ep2."""
    return sources_ep2[0]


@pytest.fixture
def presentation_ep0(sources_ep0: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Presentation ep0."""
    return sources_ep0[1]


@pytest.fixture
def presentation_ep1(sources_ep1: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Presentation ep1."""
    return sources_ep1[1]


@pytest.fixture
def presentation_ep2(sources_ep2: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Presentation ep2."""
    return sources_ep2[1]
