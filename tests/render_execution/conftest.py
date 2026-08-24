"""Fixtures for the Phase 23 render execution suite.

Every fixture is built from the real engine: real render exports become a real
story plan, which becomes a real shot direction plan, which becomes the render
plan under test. Nothing here hand-writes a document the pipeline is supposed
to produce, so a test that passes here passes against what the pipeline
actually emits.
"""

import copy
import functools
import json
import struct
import zlib
from pathlib import Path
from typing import Any

import pytest

from living_diorama.cinematic import build_shot_direction_plan_document
from living_diorama.render_execution import build_episode_render_plan_document
from living_diorama.render_execution.render_execution_spec import render_profile_dimensions
from living_diorama.story import build_episode_story_plan_document

REPO_ROOT = Path(__file__).resolve().parents[2]
MOTION_CONFIG = REPO_ROOT / "visual" / "blender" / "config" / "motion_time_v1.json"
FIXTURES = REPO_ROOT / "tests" / "cinematic" / "fixtures"

PROFILE_WIDTH, PROFILE_HEIGHT = render_profile_dimensions()
"""The size every frame this phase writes is, taken from the profile itself."""


def _load(episode: int) -> dict[str, Any]:
    """Return one shipped render export fixture."""
    return json.loads((FIXTURES / f"render_export_ep{episode}.json").read_bytes())


@pytest.fixture(scope="session")
def motion_time() -> bytes:
    """The exact bytes of the shipped Phase 17 Motion & Time Spec."""
    return MOTION_CONFIG.read_bytes()


@pytest.fixture(scope="session")
def _raw_exports() -> dict[int, dict[str, Any]]:
    """The three shipped render exports, loaded once."""
    return {episode: _load(episode) for episode in (0, 1, 2)}


@pytest.fixture
def story_leg1(_raw_exports: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """The canonical episode 0 -> 1 story plan."""
    return build_episode_story_plan_document(
        copy.deepcopy(_raw_exports[1]), copy.deepcopy(_raw_exports[0])
    )


@pytest.fixture
def story_baseline(_raw_exports: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """The canonical episode 0 baseline story plan."""
    return build_episode_story_plan_document(copy.deepcopy(_raw_exports[0]))


@pytest.fixture
def shot_plan_leg1(story_leg1: dict[str, Any], motion_time: bytes) -> dict[str, Any]:
    """The canonical episode 0 -> 1 shot direction plan."""
    return build_shot_direction_plan_document(story_leg1, motion_time)


@pytest.fixture
def shot_plan_baseline(story_baseline: dict[str, Any], motion_time: bytes) -> dict[str, Any]:
    """The canonical episode 0 baseline shot direction plan."""
    return build_shot_direction_plan_document(story_baseline, motion_time)


@pytest.fixture
def render_plan(shot_plan_leg1: dict[str, Any], story_leg1: dict[str, Any]) -> dict[str, Any]:
    """The canonical episode 0 -> 1 render plan."""
    return build_episode_render_plan_document(shot_plan_leg1, story_leg1)


@pytest.fixture
def baseline_render_plan(
    shot_plan_baseline: dict[str, Any], story_baseline: dict[str, Any]
) -> dict[str, Any]:
    """The canonical baseline render plan."""
    return build_episode_render_plan_document(shot_plan_baseline, story_baseline)


@functools.lru_cache(maxsize=512)
def png_bytes(*, width: int = PROFILE_WIDTH, height: int = PROFILE_HEIGHT, fill: int = 0) -> bytes:
    """Return a real, structurally complete PNG with correct chunk CRCs.

    The executor validates PNG structure chunk by chunk and the audit now
    decodes every frame against the render profile, so the fakes must produce
    genuine files at the profile's own resolution: a test that fed either of
    them a placeholder would prove nothing about the checks that matter.

    Defaulting to the profile size rather than a token 4x2 is what makes the
    audit tests exercise the dimension check instead of tripping it. Cached
    because a full-episode fake render asks for the same few hundred images in
    every test that runs one, and building them is the expensive part.
    """

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes([fill, fill, fill] * width) for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
