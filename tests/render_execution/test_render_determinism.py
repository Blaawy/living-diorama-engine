"""Determinism of the Phase 23 documents.

The render plan and the manifest are canonical artifacts, so their bytes must
depend on their inputs and nothing else -- not on hash seeds, not on the order
a mapping was built in, not on when or where the build ran.

Pixel bytes are a separate question and are deliberately not claimed here; see
the manifest's environment block and the phase documentation.
"""

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from living_diorama.render_execution import (
    build_episode_render_manifest_bytes,
    build_episode_render_plan_bytes,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

_BUILD_SCRIPT = """
import copy, hashlib, json, sys
sys.path.insert(0, {src!r})
sys.path.insert(0, {tests!r})
from pathlib import Path
from living_diorama.cinematic import build_shot_direction_plan_document
from living_diorama.story import build_episode_story_plan_document
from living_diorama.render_execution import build_episode_render_plan_bytes

motion = Path({motion!r}).read_bytes()
fixtures = Path({fixtures!r})
raw = {{
    episode: json.loads((fixtures / f"render_export_ep{{episode}}.json").read_bytes())
    for episode in (0, 1)
}}
story = build_episode_story_plan_document(copy.deepcopy(raw[1]), copy.deepcopy(raw[0]))
shot = build_shot_direction_plan_document(story, motion)
print(hashlib.sha256(build_episode_render_plan_bytes(shot, story)).hexdigest())
"""


def _digest_in_subprocess(seed: str) -> str:
    """Build a render plan in a fresh interpreter under one hash seed."""
    script = _BUILD_SCRIPT.format(
        src=str(REPO_ROOT / "src"),
        tests=str(REPO_ROOT / "tests"),
        motion=str(REPO_ROOT / "visual" / "blender" / "config" / "motion_time_v1.json"),
        fixtures=str(REPO_ROOT / "tests" / "cinematic" / "fixtures"),
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONHASHSEED": seed, "SYSTEMROOT": "C:\\Windows", "PATH": ""},
    )
    return completed.stdout.strip()


def test_the_plan_is_identical_under_different_hash_seeds() -> None:
    """The one test that catches an accidental set or dict iteration."""
    digests = {_digest_in_subprocess(seed) for seed in ("0", "1", "42", "123456")}
    assert len(digests) == 1, f"hash seed changed the output: {sorted(digests)}"


def test_two_builds_in_one_process_are_byte_identical(
    shot_plan_leg1: dict[str, Any], story_leg1: dict[str, Any]
) -> None:
    """Nothing accumulates between builds."""
    first = build_episode_render_plan_bytes(
        copy.deepcopy(shot_plan_leg1), copy.deepcopy(story_leg1)
    )
    second = build_episode_render_plan_bytes(
        copy.deepcopy(shot_plan_leg1), copy.deepcopy(story_leg1)
    )
    assert first == second


def test_key_insertion_order_does_not_change_the_output(
    shot_plan_leg1: dict[str, Any], story_leg1: dict[str, Any]
) -> None:
    """The same document built in a different order is the same document."""
    reversed_shot = {key: shot_plan_leg1[key] for key in reversed(list(shot_plan_leg1))}
    reversed_story = {key: story_leg1[key] for key in reversed(list(story_leg1))}
    assert build_episode_render_plan_bytes(
        reversed_shot, reversed_story
    ) == build_episode_render_plan_bytes(shot_plan_leg1, story_leg1)


def test_the_encoding_is_canonical(
    render_plan: dict[str, Any], shot_plan_leg1: Any, story_leg1: Any
) -> None:
    """Sorted keys, compact separators, one trailing newline, UTF-8."""
    payload = build_episode_render_plan_bytes(shot_plan_leg1, story_leg1)
    assert payload.endswith(b"\n")
    assert b", " not in payload and b'": ' not in payload
    assert json.loads(payload.decode("utf-8")) == render_plan


def test_the_plan_carries_no_timestamp_path_or_host_metadata(
    render_plan: dict[str, Any],
) -> None:
    """A canonical document must not record when or where it was built."""
    text = json.dumps(render_plan)
    for forbidden in ("timestamp", "created", "generated_at", "hostname", "user", "C:\\", "/home/"):
        assert forbidden not in text, forbidden


def test_the_manifest_serialization_is_deterministic(render_plan: dict[str, Any]) -> None:
    """Given identical recorded results, the manifest bytes are identical."""
    results = {
        entry["frame"]: {
            "bytes": 100 + index,
            "sha256": f"{index:064x}",
            "image_sha256": f"{index + 500:064x}",
        }
        for index, entry in enumerate(render_plan["frames"])
    }
    environment = {"blender_version": "4.5.12", "engine": "CYCLES", "device": "OPTIX"}
    first = build_episode_render_manifest_bytes(
        render_plan=render_plan,
        results=results,
        environment=environment,
        witness_difference=0.0142,
    )
    second = build_episode_render_manifest_bytes(
        render_plan=copy.deepcopy(render_plan),
        results=dict(reversed(list(results.items()))),
        environment=dict(reversed(list(environment.items()))),
        witness_difference=0.0142,
    )
    assert first == second


@pytest.mark.parametrize("episode", ["baseline_render_plan", "render_plan"])
def test_every_canonical_plan_is_stable(episode: str, request: pytest.FixtureRequest) -> None:
    """Both canonical shapes, not just the transition."""
    plan = request.getfixturevalue(episode)
    from living_diorama.persistence.json_codec import dumps_canonical

    assert dumps_canonical(plan, "plan") == dumps_canonical(copy.deepcopy(plan), "plan")
