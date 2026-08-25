"""Determinism: same three documents, same bytes, under every hash seed.

``PYTHONHASHSEED`` is fixed at interpreter start, so the cross-seed proof
spawns subprocesses -- one per seed -- and requires every seed to agree with
the in-process build and with every other seed.
"""

import random
import subprocess
import sys
import time
from pathlib import Path

from living_diorama.language_realization import (
    build_episode_language_realization_plan_bytes,
)
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical

from .conftest import build_realization_sources

HASH_SEEDS = ("0", "1", "42", "123456")

_SUBPROCESS_SCRIPT = """
import copy, hashlib, json, sys
from pathlib import Path

sys.path.insert(0, r"{src}")

from living_diorama.cinematic import build_shot_direction_plan_document
from living_diorama.language_realization import (
    build_episode_language_realization_plan_bytes,
)
from living_diorama.narration import build_episode_narration_plan_document
from living_diorama.story import build_episode_story_plan_document

fixtures = Path(r"{fixtures}")
motion = Path(r"{motion}")

def load(episode):
    path = fixtures / f"render_export_ep{{episode}}.json"
    return json.loads(path.read_text(encoding="utf-8"))

digests = []
for episode in (0, 1, 2):
    export = load(episode)
    previous = load(episode - 1) if episode else None
    story = build_episode_story_plan_document(copy.deepcopy(export), previous)
    shots = build_shot_direction_plan_document(story, motion.read_bytes())
    narration = build_episode_narration_plan_document(story, shots, copy.deepcopy(export))
    payload = build_episode_language_realization_plan_bytes(narration, story, export)
    digests.append(hashlib.sha256(payload).hexdigest())
print(" ".join(digests))
"""


def _in_process_digests() -> list[str]:
    import hashlib

    digests = []
    for episode in (0, 1, 2):
        narration, story, export = build_realization_sources(episode)
        payload = build_episode_language_realization_plan_bytes(narration, story, export)
        digests.append(hashlib.sha256(payload).hexdigest())
    return digests


def _seed_digests(seed: str) -> list[str]:
    fixtures = Path(__file__).parent / "fixtures"
    repo_root = Path(__file__).resolve().parents[2]
    script = _SUBPROCESS_SCRIPT.format(
        src=repo_root / "src",
        fixtures=fixtures,
        motion=repo_root / "visual" / "blender" / "config" / "motion_time_v1.json",
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={"PYTHONHASHSEED": seed, "SYSTEMROOT": "C:\\Windows"},
        check=True,
    )
    return completed.stdout.split()


def test_two_builds_are_byte_identical() -> None:
    """The derivation is repeatable within one interpreter."""
    narration, story, export = build_realization_sources(1)
    first = build_episode_language_realization_plan_bytes(narration, story, export)
    narration2, story2, export2 = build_realization_sources(1)
    second = build_episode_language_realization_plan_bytes(narration2, story2, export2)
    assert first == second


def test_the_bytes_round_trip_canonically() -> None:
    """Decoding and re-encoding the plan reproduces its own bytes."""
    narration, story, export = build_realization_sources(2)
    payload = build_episode_language_realization_plan_bytes(narration, story, export)
    document = loads_canonical(payload, "plan")
    assert dumps_canonical(document, "plan") == payload


def test_the_encoding_is_canonical_in_shape() -> None:
    """Sorted keys and exactly one trailing newline, proven on the real bytes."""
    narration, story, export = build_realization_sources(0)
    payload = build_episode_language_realization_plan_bytes(narration, story, export)
    assert payload.endswith(b"\n")
    assert not payload.endswith(b"\n\n")
    text = payload.decode("utf-8")
    assert text.index('"accounting"') < text.index('"format"') < text.index('"policy"')
    assert text.index('"policy"') < text.index('"realizations"') < text.index('"source"')


def test_every_hash_seed_agrees_with_the_in_process_build() -> None:
    """All four seeds reproduce the in-process digests exactly."""
    expected = _in_process_digests()
    for seed in HASH_SEEDS:
        assert _seed_digests(seed) == expected, seed


def test_no_clock_or_randomness_shapes_the_bytes() -> None:
    """Seeding the RNG and sleeping between builds changes nothing."""
    narration, story, export = build_realization_sources(1)
    random.seed(1234)
    first = build_episode_language_realization_plan_bytes(narration, story, export)
    random.seed(9876)
    time.sleep(0.05)
    second = build_episode_language_realization_plan_bytes(narration, story, export)
    assert first == second
