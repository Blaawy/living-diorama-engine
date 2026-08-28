"""Determinism of the Phase 32 canonical package: same inputs, same bytes, no dependency leak."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"

_SCRIPT = """
import copy, json, sys
sys.path.insert(0, {src!r})
from pathlib import Path
from living_diorama.caption import build_episode_caption_plan_bytes
from living_diorama.cinematic import build_shot_direction_plan_document
from living_diorama.language_realization import build_episode_language_realization_plan_document
from living_diorama.narration import build_episode_narration_plan_document
from living_diorama.narration_delivery import build_episode_narration_delivery_plan_document
from living_diorama.presentation import build_episode_presentation_plan_document
from living_diorama.story import build_episode_story_plan_document

export = json.loads(Path({export!r}).read_text(encoding="utf-8"))
story = build_episode_story_plan_document(copy.deepcopy(export), None)
motion_config = Path({motion!r}).read_bytes()
shots = build_shot_direction_plan_document(story, motion_config)
narration = build_episode_narration_plan_document(story, shots, copy.deepcopy(export))
delivery = build_episode_narration_delivery_plan_document(narration, shots)
realization = build_episode_language_realization_plan_document(
    narration, story, copy.deepcopy(export)
)
presentation = build_episode_presentation_plan_document(delivery, narration, realization)
payload = build_episode_caption_plan_bytes(realization, presentation)
import hashlib
print(hashlib.sha256(payload).hexdigest())
"""


@pytest.mark.parametrize("seed", ("0", "1", "42", "123456"))
def test_caption_plan_is_deterministic_under_hash_seed(seed: str) -> None:
    """Caption plan is deterministic under hash seed."""
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = seed
    script = _SCRIPT.format(
        src=str(REPO_ROOT / "src"),
        export=str(FIXTURES / "render_export_ep0.json"),
        motion=str(REPO_ROOT / "visual" / "blender" / "config" / "motion_time_v1.json"),
    )
    first = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env, check=True
    )
    second = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env, check=True
    )
    assert first.stdout == second.stdout
    assert first.stdout.strip()


def test_canonical_round_trip(realization_ep1, presentation_ep1) -> None:
    """Canonical round trip."""
    from living_diorama.caption import build_episode_caption_plan_bytes
    from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical

    payload = build_episode_caption_plan_bytes(realization_ep1, presentation_ep1)
    document = loads_canonical(payload, "caption plan")
    assert dumps_canonical(document, "caption plan") == payload


def test_no_third_party_import_reachable_at_module_scope() -> None:
    """No third party import reachable at module scope."""
    script = (
        "import sys; "
        f"sys.path.insert(0, {str(REPO_ROOT / 'src')!r}); "
        "import living_diorama.caption; "
        "forbidden = {'kokoro', 'misaki', 'torch', 'numpy', 'scipy', 'spacy', 'num2words', "
        "'soundfile', 'wave', 'srt', 'webvtt'}; "
        "hit = forbidden & set(m.split('.')[0] for m in sys.modules); "
        "print(sorted(hit))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert completed.stdout.strip() == "[]"
