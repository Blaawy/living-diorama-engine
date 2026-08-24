"""Source identity: the render must use the exact documents its plan names.

A render plan that named its story and its cameras but let the world be
composed from whatever configs were on the command line would be open at the
bottom: the same plan, pointed at a Motion Time document with the same clock
and a different channel window, produces different footage under the same
identity. These tests hold every material input to its exact bytes.

"Exact bytes" is meant literally. A pretty-printed copy of the same JSON is a
different file, and the digests these are checked against are digests of
files -- so re-serialising before comparing would accept a document nobody
reviewed.
"""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.render_execution.render_execution_spec import (
    APPROVED_COMPOSITION_SOURCES,
    COMPOSITION_SOURCE_FILES,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / "visual" / "blender" / "config"
SCRIPT = REPO_ROOT / "visual" / "blender" / "scripts" / "render_episode.py"


def _load_executor() -> Any:
    """Import the production executor without Blender present."""
    spec = importlib.util.spec_from_file_location("render_episode_sources", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


executor = _load_executor()


def _raw(path: Path) -> str:
    """The digest of a file exactly as it sits on disk."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------- the pinned bundle


def test_every_composition_source_is_pinned_to_the_shipped_file() -> None:
    """The pins are digests of this repository's own configs, re-hashed here.

    If a locked config is ever revised, this fails immediately rather than
    letting Phase 23 keep vouching for a world that no longer exists.
    """
    for key, filename in sorted(COMPOSITION_SOURCE_FILES.items()):
        assert _raw(CONFIG / filename) == APPROVED_COMPOSITION_SOURCES[key], filename


def test_the_bundle_covers_every_config_the_composer_reads() -> None:
    """Six documents build the world; six digests bind it.

    Checked against the composer's own signature rather than a list kept by
    hand, so a seventh input could not be added without this failing.
    """
    import inspect

    sys.path.insert(0, str(REPO_ROOT / "visual" / "blender" / "scripts"))
    import episode_scene  # noqa: PLC0415

    parameters = set(inspect.signature(episode_scene.compose_episode_world).parameters)
    config_parameters = {name for name in parameters if name.endswith("_path")} - {
        "before_path",
        "after_path",
    }
    assert len(config_parameters) == len(COMPOSITION_SOURCE_FILES) == 6


def test_the_render_plan_carries_the_approved_bundle(render_plan: dict[str, Any]) -> None:
    """A plan binds the world it was built for."""
    assert render_plan["composition_sources"] == dict(APPROVED_COMPOSITION_SOURCES)


# ------------------------------------------- exact bytes, not equivalent data


@pytest.mark.parametrize("filename", sorted(COMPOSITION_SOURCE_FILES.values()))
def test_a_reformatted_config_has_a_different_identity(filename: str) -> None:
    """The attack this closes: same data, different file, same plan.

    A pretty-printed config parses identically and means the same thing, and it
    is still not the document that was reviewed. Its digest must differ, or the
    binding would be a binding to "some JSON like this".
    """
    original = (CONFIG / filename).read_bytes()
    pretty = json.dumps(json.loads(original), indent=2).encode("utf-8")
    assert pretty != original
    assert hashlib.sha256(pretty).hexdigest() != hashlib.sha256(original).hexdigest()


def test_a_motion_time_with_the_same_clock_but_a_changed_channel_differs() -> None:
    """The specific hazard the review named.

    The clock digest alone would not notice this: the timeline is untouched, so
    every Phase 17 and Phase 22 check still passes, and only the motion inside
    the transition changes. The composition binding is what refuses it.
    """
    original = (CONFIG / "motion_time_v1.json").read_bytes()
    document = json.loads(original)
    document["channels"][0]["window"] = [0.05, 0.60]
    altered = json.dumps(document).encode("utf-8")
    assert document["timeline"] == json.loads(original)["timeline"]
    assert hashlib.sha256(altered).hexdigest() != APPROVED_COMPOSITION_SOURCES["motion_time_sha256"]


def test_an_export_reserialised_is_not_the_export_that_was_bound(
    story_leg1: dict[str, Any],
) -> None:
    """Why the executor hashes raw bytes rather than canonicalising first.

    Canonicalising would map the pretty-printed copy back onto the bound digest
    and accept it. The shipped exports are already canonical, so the raw-byte
    rule costs nothing and closes that door.
    """
    export = REPO_ROOT / "tests" / "story" / "fixtures" / "render_export_ep1.json"
    raw = export.read_bytes()
    bound = story_leg1["source"]["current"]["document_sha256"]
    assert hashlib.sha256(raw).hexdigest() == bound

    pretty = json.dumps(json.loads(raw), indent=2).encode("utf-8")
    reordered = json.dumps(dict(reversed(list(json.loads(raw).items())))).encode("utf-8")
    trailing = raw + b"\n"
    for variant in (pretty, reordered, trailing):
        assert hashlib.sha256(variant).hexdigest() != bound
        # ...while the canonicalising algorithm V1 used would have accepted two
        # of the three, which is precisely why it was replaced.
    assert hashlib.sha256(dumps_canonical(json.loads(pretty), "x")).hexdigest() == bound


# -------------------------------------------------------------- baseline mode


def test_a_baseline_plan_binds_one_world(baseline_render_plan: dict[str, Any]) -> None:
    """A baseline holds one state, so it names one export and no second world."""
    source = baseline_render_plan["source"]
    assert source["mode"] == "baseline"
    assert source["before_export_sha256"] is None
    assert source["after_export_sha256"] is not None
    assert source["previous_episode"] is None


def test_the_executor_accepts_a_baseline_plan(baseline_render_plan: dict[str, Any]) -> None:
    """The production validator understands both episode shapes."""
    assert executor.require_valid_render_plan(baseline_render_plan) is not None


def test_a_baseline_that_smuggles_a_before_export_is_refused(
    baseline_render_plan: dict[str, Any],
) -> None:
    """The binding itself refuses a second world, before any path is read."""
    import copy

    broken = copy.deepcopy(baseline_render_plan)
    broken["source"]["before_export_sha256"] = "a" * 64
    with pytest.raises(executor.PlanRefused, match="baseline render plan binds a before export"):
        executor.require_valid_render_plan(broken)


def test_the_baseline_render_id_is_its_own(baseline_render_plan: dict[str, Any]) -> None:
    """A baseline never shares a directory with the transition that follows it."""
    assert baseline_render_plan["destination"]["render_id"] == "episode_0000_baseline"


def test_the_production_parser_makes_before_optional() -> None:
    """``--before`` is required for a transition and refused for a baseline.

    Leaving it mandatory is what let V1's baseline take an unverified world:
    the flag had to be supplied, and nothing checked it.
    """
    parser = executor._build_parser()
    actions = {action.dest: action for action in parser._actions}
    assert actions["before"].required is False
    assert actions["after"].required is True
