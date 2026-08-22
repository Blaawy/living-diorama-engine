"""The same authoritative inputs always produce byte-identical plans.

Determinism is the property the whole pipeline is built on, and a plan that
varied between runs would poison every downstream layer that consumed it. These
tests prove it holds within a process, across processes, and across hash seeds.
"""

import copy
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

from living_diorama.story import (
    build_episode_story_plan_bytes,
    build_episode_story_plan_document,
)

FIXTURES = Path(__file__).parent / "fixtures"

RUNNER = textwrap.dedent(
    """
    import hashlib, json, sys
    sys.path.insert(0, sys.argv[1])
    from living_diorama.story import build_episode_story_plan_bytes
    previous = json.loads(open(sys.argv[2], encoding="utf-8").read())
    current = json.loads(open(sys.argv[3], encoding="utf-8").read())
    payload = build_episode_story_plan_bytes(current, previous)
    sys.stdout.write(hashlib.sha256(payload).hexdigest())
    """
)


def _src_root() -> str:
    return str(Path(__file__).resolve().parents[2] / "src")


def _digest_in_subprocess(hash_seed: str) -> str:
    """Build the plan in a fresh interpreter under a chosen hash seed."""
    env_seed = {"PYTHONHASHSEED": hash_seed}
    import os

    env = dict(os.environ)
    env.update(env_seed)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            RUNNER,
            _src_root(),
            str(FIXTURES / "render_export_ep1.json"),
            str(FIXTURES / "render_export_ep2.json"),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout.strip()


# ------------------------------------------------------------- within a run


def test_two_builds_of_the_same_inputs_are_byte_identical(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Two builds of the same inputs are byte identical."""
    first = build_episode_story_plan_bytes(export_ep2, export_ep1)
    second = build_episode_story_plan_bytes(
        copy.deepcopy(export_ep2), copy.deepcopy(export_ep1)
    )
    assert first == second


def test_a_baseline_plan_is_also_byte_stable(export_ep0: dict[str, Any]) -> None:
    """A baseline plan is also byte stable."""
    first = build_episode_story_plan_bytes(export_ep0)
    second = build_episode_story_plan_bytes(copy.deepcopy(export_ep0))
    assert first == second


def test_key_insertion_order_in_the_input_does_not_change_the_output(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """A dict that was built in a different order is the same document."""

    def shuffle(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: shuffle(value[key]) for key in sorted(value, reverse=True)}
        if isinstance(value, list):
            return [shuffle(entry) for entry in value]
        return value

    straight = build_episode_story_plan_bytes(export_ep2, export_ep1)
    reordered = build_episode_story_plan_bytes(shuffle(export_ep2), shuffle(export_ep1))
    assert straight == reordered


# ------------------------------------------------------------ canonical form


def test_the_encoding_is_canonical(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Sorted keys, tight separators, one trailing newline, no NaN."""
    payload = build_episode_story_plan_bytes(export_ep2, export_ep1)
    assert payload.endswith(b"\n")
    assert not payload[:-1].endswith(b"\n")
    text = payload.decode("utf-8")
    assert ", " not in text
    assert '": ' not in text
    assert "NaN" not in text and "Infinity" not in text
    document = json.loads(text)
    assert list(document) == sorted(document)


def test_the_plan_carries_no_timestamp_path_or_host_metadata(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Anything host-specific would make two machines disagree."""
    text = build_episode_story_plan_bytes(export_ep2, export_ep1).decode("utf-8")
    lowered = text.lower()
    for token in ("timestamp", "generated_at", "created_at", "hostname", "user"):
        assert token not in lowered, token
    for token in (".json", "c:\\\\", "/users/", "\\\\users\\\\"):
        assert token not in lowered, token


def test_the_plan_is_json_round_trip_stable(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """The plan is JSON round trip stable."""
    payload = build_episode_story_plan_bytes(export_ep2, export_ep1)
    document = build_episode_story_plan_document(export_ep2, export_ep1)
    assert json.loads(payload.decode("utf-8")) == document


# ---------------------------------------------------------------- hash seeds


def test_the_plan_is_identical_under_different_hash_seeds() -> None:
    """The one test that catches an accidental set or dict iteration.

    Each build runs in its own interpreter so the seed genuinely differs.
    """
    digests = {_digest_in_subprocess(seed) for seed in ("0", "1", "42", "123456")}
    assert len(digests) == 1, f"hash seed changed the output: {sorted(digests)}"


def test_repeated_subprocess_runs_agree_with_the_in_process_build(
    export_ep1: dict[str, Any], export_ep2: dict[str, Any]
) -> None:
    """Repeated subprocess runs agree with the in process build."""
    import hashlib

    expected = hashlib.sha256(
        build_episode_story_plan_bytes(export_ep2, export_ep1)
    ).hexdigest()
    assert _digest_in_subprocess("0") == expected
