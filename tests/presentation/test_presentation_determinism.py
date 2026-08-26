"""Same three documents, same bytes -- whatever the interpreter feels like today.

Determinism here is not a nice property, it is the contract: a presentation
plan is identified by the digest of its canonical bytes, and the voice,
caption and assembly layers downstream will bind that digest. If the same
delivery, narration and realization plans could produce two different
presentations, none of those bindings would mean anything.

The hash-seed tests run in subprocesses, because ``PYTHONHASHSEED`` is fixed at
interpreter start and cannot be changed from inside a running one. Anything
depending on set or dict iteration order would move between them.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.presentation import build_episode_presentation_plan_bytes

from .conftest import build_presentation_sources

HASH_SEEDS = ("0", "1", "42", "123456")
"""The seeds every deterministic layer in this repository is proven across."""

DIGEST_SCRIPT = """
import copy, json
from pathlib import Path
from living_diorama.cinematic import build_shot_direction_plan_document
from living_diorama.language_realization import build_episode_language_realization_plan_document
from living_diorama.narration import build_episode_narration_plan_document
from living_diorama.narration_delivery import build_episode_narration_delivery_plan_document
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.presentation import build_episode_presentation_plan_bytes
from living_diorama.story import build_episode_story_plan_document

fixtures = Path({fixtures!r})
motion = Path({motion!r}).read_bytes()


def load(episode):
    return json.loads((fixtures / f"render_export_ep{{episode}}.json").read_text(encoding="utf-8"))


digests = []
for episode in (0, 1, 2):
    export = load(episode)
    previous = load(episode - 1) if episode else None
    story = build_episode_story_plan_document(copy.deepcopy(export), previous)
    shots = build_shot_direction_plan_document(story, motion)
    narration = build_episode_narration_plan_document(story, shots, copy.deepcopy(export))
    delivery = build_episode_narration_delivery_plan_document(narration, shots)
    realization = build_episode_language_realization_plan_document(
        narration, story, copy.deepcopy(export)
    )
    digests.append(
        sha256_hex(build_episode_presentation_plan_bytes(delivery, narration, realization))
    )
print(json.dumps(digests))
"""


def _digests_under_seed(seed: str) -> list[str]:
    """Return the three canonical presentation digests, computed under one hash seed."""
    repo_root = Path(__file__).resolve().parents[2]
    script = DIGEST_SCRIPT.format(
        fixtures=str(Path(__file__).parent / "fixtures"),
        motion=str(repo_root / "visual" / "blender" / "config" / "motion_time_v1.json"),
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONHASHSEED": seed, "PATH": ""},
    )
    return list(json.loads(completed.stdout))


def _canonical_digests() -> list[str]:
    digests = []
    for episode in (0, 1, 2):
        delivery, narration, _shots, realization, _story, _export = build_presentation_sources(
            episode
        )
        digests.append(
            sha256_hex(build_episode_presentation_plan_bytes(delivery, narration, realization))
        )
    return digests


# ---- repeatability


@pytest.mark.parametrize("episode", [0, 1, 2])
def test_the_plan_survives_a_canonical_round_trip(episode: int) -> None:
    """Decoding and re-encoding the plan reproduces the file exactly."""
    delivery, narration, _shots, realization, _story, _export = build_presentation_sources(episode)
    payload = build_episode_presentation_plan_bytes(delivery, narration, realization)
    document = loads_canonical(payload, "presentation plan")
    assert dumps_canonical(document, "presentation plan") == payload


def test_the_encoding_is_canonical() -> None:
    """Sorted keys, tight separators, one trailing newline, and nothing else."""
    delivery, narration, _shots, realization, _story, _export = build_presentation_sources(1)
    payload = build_episode_presentation_plan_bytes(delivery, narration, realization)
    text = payload.decode("utf-8")
    assert text.endswith("}\n")
    assert text.count("\n") == 1
    document = json.loads(text)
    assert json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n" == text


def test_building_the_same_sources_twice_produces_identical_bytes() -> None:
    """Building the same sources twice produces identical bytes."""
    delivery, narration, _shots, realization, _story, _export = build_presentation_sources(1)
    first = build_episode_presentation_plan_bytes(delivery, narration, realization)
    second = build_episode_presentation_plan_bytes(delivery, narration, realization)
    assert first == second


# ---- hash-seed independence


@pytest.mark.parametrize("seed", HASH_SEEDS)
def test_the_digests_do_not_move_with_the_hash_seed(seed: str) -> None:
    """Anything reading a set or dict iteration order would drift between these."""
    assert _digests_under_seed(seed) == _canonical_digests()


def test_every_seed_agrees_with_every_other() -> None:
    """All four seeds produce one set of digests, not four."""
    results = {seed: _digests_under_seed(seed) for seed in HASH_SEEDS}
    assert len({tuple(digests) for digests in results.values()}) == 1


# ---- refusals a canonical codec owes us


def test_a_plan_carrying_a_non_finite_float_cannot_be_written() -> None:
    """The writer refuses too, so a bad value cannot reach a file."""
    from living_diorama.presentation import build_episode_presentation_plan_document

    delivery, narration, _shots, realization, _story, _export = build_presentation_sources(1)
    plan = build_episode_presentation_plan_document(delivery, narration, realization)
    plan["accounting"]["presentation_frames_total"] = float("nan")
    with pytest.raises((ValueError, TypeError)):
        dumps_canonical(plan, "presentation plan")


# ---- no environment in the output


def test_the_layer_reads_no_clock_or_randomness() -> None:
    """Proven structurally by the boundary guard; asserted here as behaviour.

    Two builds separated by real time and by a reseeded global random state
    produce the same bytes.
    """
    import random
    import time

    delivery, narration, _shots, realization, _story, _export = build_presentation_sources(1)
    first = build_episode_presentation_plan_bytes(delivery, narration, realization)
    random.seed(7)
    time.sleep(0.01)
    random.seed(99)
    second = build_episode_presentation_plan_bytes(delivery, narration, realization)
    assert first == second
