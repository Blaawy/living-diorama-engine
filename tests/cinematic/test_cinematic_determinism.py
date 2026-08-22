"""The same story plan and clock always produce byte-identical direction.

A shot plan that varied between runs would poison every downstream layer that
consumed it, and would make the Blender applier non-reproducible. These tests
prove stability within a process, across processes, and across hash seeds.
"""

import copy
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

from living_diorama.cinematic import (
    build_shot_direction_plan_bytes,
    build_shot_direction_plan_document,
)

FIXTURES = Path(__file__).parent / "fixtures"

RUNNER = textwrap.dedent(
    """
    import hashlib, json, sys
    sys.path.insert(0, sys.argv[1])
    from living_diorama.story import build_episode_story_plan_document
    from living_diorama.cinematic import (
        build_shot_direction_plan_bytes,
        validate_shot_direction_plan_against_story,
    )
    previous = json.loads(open(sys.argv[2], encoding="utf-8").read())
    current = json.loads(open(sys.argv[3], encoding="utf-8").read())
    motion_time = open(sys.argv[4], "rb").read()
    story = build_episode_story_plan_document(current, previous)
    payload = build_shot_direction_plan_bytes(story, motion_time)
    validate_shot_direction_plan_against_story(
        json.loads(payload.decode("utf-8")), story, motion_time
    )
    sys.stdout.write(hashlib.sha256(payload).hexdigest())
    """
)
"""The subprocess covers the whole pipeline: derive, cross-validate, digest.

Running the cross-validator under every hash seed proves the source-binding
layer -- re-derivation seal included -- accepts deterministically, not only
that the planner emits stable bytes.
"""


def _src_root() -> str:
    return str(Path(__file__).resolve().parents[2] / "src")


def _motion_config_path() -> str:
    root = Path(__file__).resolve().parents[2]
    return str(root / "visual" / "blender" / "config" / "motion_time_v1.json")


def _digest_in_subprocess(hash_seed: str) -> str:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = hash_seed
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            RUNNER,
            _src_root(),
            str(FIXTURES / "render_export_ep1.json"),
            str(FIXTURES / "render_export_ep2.json"),
            _motion_config_path(),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout.strip()


# -------------------------------------------------------------- within a run


def test_two_builds_of_the_same_inputs_are_byte_identical(
    story_ep1_to_ep2: dict[str, Any], motion_time: bytes
) -> None:
    """Two builds of the same inputs are byte identical."""
    first = build_shot_direction_plan_bytes(story_ep1_to_ep2, motion_time)
    second = build_shot_direction_plan_bytes(copy.deepcopy(story_ep1_to_ep2), bytes(motion_time))
    assert first == second


def test_a_baseline_plan_is_also_byte_stable(story_ep0: dict[str, Any], motion_time: bytes) -> None:
    """A baseline plan is also byte stable."""
    first = build_shot_direction_plan_bytes(story_ep0, motion_time)
    second = build_shot_direction_plan_bytes(copy.deepcopy(story_ep0), bytes(motion_time))
    assert first == second


def test_key_insertion_order_does_not_change_the_output(
    story_ep1_to_ep2: dict[str, Any], motion_time: bytes
) -> None:
    """A dict built in a different order is the same document."""

    def shuffle(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: shuffle(value[key]) for key in sorted(value, reverse=True)}
        if isinstance(value, list):
            return [shuffle(entry) for entry in value]
        return value

    straight = build_shot_direction_plan_bytes(story_ep1_to_ep2, motion_time)
    reordered = build_shot_direction_plan_bytes(shuffle(story_ep1_to_ep2), motion_time)
    assert straight == reordered


# ------------------------------------------------------------ canonical form


def test_the_encoding_is_canonical(story_ep1_to_ep2: dict[str, Any], motion_time: bytes) -> None:
    """Sorted keys, tight separators, one trailing newline, no NaN."""
    payload = build_shot_direction_plan_bytes(story_ep1_to_ep2, motion_time)
    assert payload.endswith(b"\n")
    assert not payload[:-1].endswith(b"\n")
    text = payload.decode("utf-8")
    assert ", " not in text
    assert '": ' not in text
    assert "NaN" not in text and "Infinity" not in text
    document = json.loads(text)
    assert list(document) == sorted(document)


def test_the_plan_carries_no_timestamp_path_or_host_metadata(
    story_ep1_to_ep2: dict[str, Any], motion_time: bytes
) -> None:
    """Anything host-specific would make two machines disagree."""
    text = build_shot_direction_plan_bytes(story_ep1_to_ep2, motion_time).decode("utf-8")
    lowered = text.lower()
    for token in ("timestamp", "generated_at", "created_at", "hostname", "blend"):
        assert token not in lowered, token
    for token in (".json", "c:\\\\", "/users/"):
        assert token not in lowered, token


def test_the_plan_round_trips_through_json(
    story_ep1_to_ep2: dict[str, Any], motion_time: bytes
) -> None:
    """The plan round trips through JSON."""
    payload = build_shot_direction_plan_bytes(story_ep1_to_ep2, motion_time)
    document = build_shot_direction_plan_document(story_ep1_to_ep2, motion_time)
    assert json.loads(payload.decode("utf-8")) == document


# ---------------------------------------------------------------- hash seeds


def test_the_plan_is_identical_under_different_hash_seeds() -> None:
    """The one test that catches an accidental set or dict iteration."""
    digests = {_digest_in_subprocess(seed) for seed in ("0", "1", "42", "123456")}
    assert len(digests) == 1, f"hash seed changed the output: {sorted(digests)}"


def test_the_subprocess_build_agrees_with_the_in_process_build(
    story_ep1_to_ep2: dict[str, Any], motion_time: bytes
) -> None:
    """The subprocess build agrees with the in process build."""
    import hashlib

    expected = hashlib.sha256(
        build_shot_direction_plan_bytes(story_ep1_to_ep2, motion_time)
    ).hexdigest()
    assert _digest_in_subprocess("0") == expected


def test_frame_allocation_is_stable_across_runs(
    story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """Largest-remainder allocation must not depend on iteration order."""
    runs = [
        [
            (shot["shot_id"], shot["start_frame"], shot["end_frame"])
            for shot in build_shot_direction_plan_document(
                copy.deepcopy(story_ep0_to_ep1), motion_time
            )["shots"]
        ]
        for _ in range(5)
    ]
    assert all(run == runs[0] for run in runs)
