"""Determinism of the Phase 31 canonical package: same inputs, same bytes, no dependency leak."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_SCRIPT = """
import sys
sys.path.insert(0, {src!r})
from living_diorama.audio_composition.audio_composer import (
    compose_episode_audio_bytes,
    require_placement_geometry,
)
from living_diorama.voice_execution.speech_audio import pcm16_bytes

plan = {{
    "clock": {{"audio_samples_total": 100}},
    "speech": [
        {{"start_sample": 10, "speech_samples": 5}},
        {{"start_sample": 30, "speech_samples": 5}},
    ],
}}
placements = require_placement_geometry(plan)
payloads = {{
    i + 1: pcm16_bytes([0.25] * count, "t") for i, (start, count) in enumerate(placements)
}}
wav = compose_episode_audio_bytes(
    audio_track_plan=plan, payloads=payloads, sample_rate_hz=24000, channels=1
)
import hashlib
print(hashlib.sha256(wav).hexdigest())
"""


@pytest.mark.parametrize("seed", ("0", "1", "42", "123456"))
def test_composition_is_deterministic_under_hash_seed(seed: str) -> None:
    """Composition is deterministic under hash seed."""
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = seed
    script = _SCRIPT.format(src=str(REPO_ROOT / "src"))
    first = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env, check=True
    )
    second = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env, check=True
    )
    assert first.stdout == second.stdout
    assert first.stdout.strip()


def test_two_independent_compositions_produce_the_same_digest(audio_track_plan_ep1) -> None:
    """Two independent compositions produce the same digest."""
    from living_diorama.audio_composition.audio_composer import (
        compose_episode_audio_bytes,
        require_placement_geometry,
    )
    from living_diorama.persistence.schema.state_hash import sha256_hex
    from living_diorama.voice_execution.speech_audio import pcm16_bytes

    placements = require_placement_geometry(audio_track_plan_ep1)
    payloads = {
        i + 1: pcm16_bytes([0.4] * count, "t") for i, (start, count) in enumerate(placements)
    }
    wav1 = compose_episode_audio_bytes(
        audio_track_plan=audio_track_plan_ep1, payloads=payloads, sample_rate_hz=24000, channels=1
    )
    wav2 = compose_episode_audio_bytes(
        audio_track_plan=audio_track_plan_ep1,
        payloads=dict(payloads),
        sample_rate_hz=24000,
        channels=1,
    )
    assert sha256_hex(wav1) == sha256_hex(wav2)


def test_no_third_party_import_reachable_at_module_scope() -> None:
    """Importing the package never imports a forbidden third-party dependency."""
    script = (
        "import sys; "
        f"sys.path.insert(0, {str(REPO_ROOT / 'src')!r}); "
        "import living_diorama.audio_composition; "
        "forbidden = {'kokoro', 'misaki', 'torch', 'numpy', 'scipy', 'spacy', 'num2words', "
        "'soundfile', 'wave'}; "
        "hit = forbidden & set(m.split('.')[0] for m in sys.modules); "
        "print(sorted(hit))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert completed.stdout.strip() == "[]"
