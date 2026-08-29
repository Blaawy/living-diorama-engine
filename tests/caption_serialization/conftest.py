"""Shared fixtures for the Phase 34 caption serialization tests.

The exports under ``fixtures/`` are byte-identical copies of the Phase 27
suite's own render exports. Story, shot, narration, delivery, realization
and presentation plans are all derived from them at test time by the real
locked upstream builders, exactly as the Phase 27 and Phase 31 suites
already do; the Episode Caption Plan is built by the real Phase 32 planner
from those sources. Nothing here hand-writes a document one of those layers
is supposed to produce.
"""

import copy
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from living_diorama.caption import build_episode_caption_plan_document
from living_diorama.caption_serialization import publish_episode_caption_serialization
from living_diorama.cinematic import build_shot_direction_plan_document
from living_diorama.language_realization import build_episode_language_realization_plan_document
from living_diorama.narration import build_episode_narration_plan_document
from living_diorama.narration_delivery import build_episode_narration_delivery_plan_document
from living_diorama.persistence.json_codec import dumps_canonical
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


def build_caption_plan_document(
    realization: dict[str, Any], presentation: dict[str, Any]
) -> dict[str, Any]:
    """Return the Episode Caption Plan via the real Phase 32 planner."""
    return build_episode_caption_plan_document(realization, presentation)


@pytest.fixture(scope="session")
def sources_ep0() -> tuple[dict[str, Any], ...]:
    """Sources ep0. Session-scoped: pure, expensive to rebuild, never mutated in place."""
    return build_sources(0)


@pytest.fixture(scope="session")
def sources_ep1() -> tuple[dict[str, Any], ...]:
    """Sources ep1. Session-scoped: pure, expensive to rebuild, never mutated in place."""
    return build_sources(1)


@pytest.fixture(scope="session")
def sources_ep2() -> tuple[dict[str, Any], ...]:
    """Sources ep2. Session-scoped: pure, expensive to rebuild, never mutated in place."""
    return build_sources(2)


@pytest.fixture(scope="session")
def caption_plan_ep0(sources_ep0: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], bytes]:
    """Caption plan document + its canonical bytes, ep0."""
    realization, presentation, *_rest = sources_ep0
    document = build_caption_plan_document(realization, presentation)
    return document, dumps_canonical(document, "caption plan")


@pytest.fixture(scope="session")
def caption_plan_ep1(sources_ep1: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], bytes]:
    """Caption plan document + its canonical bytes, ep1."""
    realization, presentation, *_rest = sources_ep1
    document = build_caption_plan_document(realization, presentation)
    return document, dumps_canonical(document, "caption plan")


@pytest.fixture(scope="session")
def caption_plan_ep2(sources_ep2: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], bytes]:
    """Caption plan document + its canonical bytes, ep2."""
    realization, presentation, *_rest = sources_ep2
    document = build_caption_plan_document(realization, presentation)
    return document, dumps_canonical(document, "caption plan")


def serialize_into(output_root: Path, episode_sources: tuple[dict[str, Any], ...]) -> Path:
    """Publish one episode's caption serialization via the real publisher, and return the dir.

    Every verification document is the real in-memory object the locked upstream
    chain built; the caption plan is built here from the realization and
    presentation sources, and its bytes are the one canonical observation handed
    to the publisher -- parse, gate, digest and copy all share it.
    """
    realization, presentation, delivery, narration, shots, story, export = episode_sources
    caption_plan = build_caption_plan_document(realization, presentation)
    caption_plan_bytes = dumps_canonical(caption_plan, "caption plan")
    output_root.mkdir(parents=True, exist_ok=True)
    return publish_episode_caption_serialization(
        caption_plan=caption_plan,
        caption_plan_bytes=caption_plan_bytes,
        realization_plan=realization,
        presentation_plan=presentation,
        delivery_plan=delivery,
        narration_plan=narration,
        shot_plan=shots,
        story_plan=story,
        current_export=export,
        output_root=output_root,
    )


@pytest.fixture(scope="session")
def captions_dir_ep1(
    tmp_path_factory: pytest.TempPathFactory, sources_ep1: tuple[dict[str, Any], ...]
) -> Path:
    """A real, published Phase 34 captions directory for ep1, session-scoped.

    A shared, read-only publication: any test that needs to attack the
    published *files* must copy this tree into its own ``tmp_path`` first, via
    ``shutil.copytree``, and mutate the copy -- never this directory itself.
    """
    return serialize_into(tmp_path_factory.mktemp("captions_ep1") / "out", sources_ep1)


@pytest.fixture
def captions_dir_ep1_copy(tmp_path: Path, captions_dir_ep1: Path) -> Path:
    """A fresh, function-scoped, writable copy of the published ep1 captions directory.

    For tests that must tamper with published *files* on disk -- a tamper, a
    hardlink, a foreign entry -- without disturbing the session-shared original
    every other test relies on.
    """
    destination = tmp_path / captions_dir_ep1.name
    shutil.copytree(captions_dir_ep1, destination)
    return destination


@pytest.fixture
def cli_inputs_ep1(
    tmp_path: Path,
    sources_ep1: tuple[dict[str, Any], ...],
    caption_plan_ep1: tuple[dict[str, Any], bytes],
) -> dict[str, Path]:
    """Write every real file the ``serialize_episode_captions`` CLI takes as a flag, to disk.

    Returns a dict keyed by argparse destination name (``caption_plan`` ...
    ``output_root``), ready to build an argv list from; ``output_root`` is a
    fresh, existing directory.
    """
    realization, presentation, delivery, narration, shots, story, export = sources_ep1
    caption_plan, _caption_plan_bytes = caption_plan_ep1
    paths: dict[str, Path] = {}
    for name, document, description in (
        ("caption_plan", caption_plan, "caption plan"),
        ("realization", realization, "episode language realization plan"),
        ("presentation", presentation, "episode presentation plan"),
        ("delivery", delivery, "episode narration delivery plan"),
        ("narration", narration, "episode narration plan"),
        ("shots", shots, "shot direction plan"),
        ("story", story, "episode story plan"),
        ("export", export, "render export"),
    ):
        path = tmp_path / f"{name}.json"
        path.write_bytes(dumps_canonical(document, description))
        paths[name] = path
    output_root = tmp_path / "captions"
    output_root.mkdir()
    paths["output_root"] = output_root
    return paths
