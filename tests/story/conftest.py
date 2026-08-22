"""Shared fixtures for the Phase 21 story tests.

The three exports under ``fixtures/`` are genuine Render Export V1 documents
produced by the real engine through ``tools/phase15_proof/generate_proof_exports``
and ``living_diorama.render.write_render_export``. Nothing in them is
hand-authored: the wall in episode 1 exists because the engine's own causal
pipeline built it, and the persistence fact in episode 2 exists because the law
came back and the wall did not.

    episode 0   four districts, movement law in force, no wall
    episode 1   the law is suspended; the eastern annex starves; a wall rises
    episode 2   the law is restored -- and the wall remains

Tests deep-copy them, so a test that mutates its input cannot leak into another.
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _load(episode: int) -> dict[str, Any]:
    path = FIXTURES / f"render_export_ep{episode}.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def _raw_exports() -> dict[int, dict[str, Any]]:
    return {episode: _load(episode) for episode in (0, 1, 2)}


@pytest.fixture
def export_ep0(_raw_exports: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Episode 0: the baseline world, no events, no durable memory."""
    return copy.deepcopy(_raw_exports[0])


@pytest.fixture
def export_ep1(_raw_exports: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Episode 1: the law is suspended and the wall rises."""
    return copy.deepcopy(_raw_exports[1])


@pytest.fixture
def export_ep2(_raw_exports: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Episode 2: the law returns and the wall remains."""
    return copy.deepcopy(_raw_exports[2])
