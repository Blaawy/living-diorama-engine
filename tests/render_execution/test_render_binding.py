"""Every relationship Phase 23's three documents must hold to one another.

Each of these attacks produces documents that are individually **valid**. That
is the point: an independent reviewer walked four of them past V2, which bound
the right digests and then never compared what had been copied under them. A
document that validates has proved nobody typed a contradiction into it; these
tests are about the claims it makes concerning other documents.

Every mutation here leaves the binding digest it would be caught by untouched --
``shot_plan_sha256`` for the plan attacks, ``render_plan_sha256`` for the
manifest attacks -- because catching a forgery that helpfully rewrote its own
digest would prove nothing.

The Blender-side executor restates each of these rules in the standard library,
and the parity tests at the bottom drive both implementations over the same
mutations, so the two cannot drift apart unnoticed.
"""

import copy
import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.render_execution import (
    build_episode_render_manifest_document,
    validate_episode_render_manifest,
)
from living_diorama.render_execution.render_binding import (
    MANIFEST_EXCLUSIVE_FRAME_KEYS,
    MANIFEST_EXCLUSIVE_SOURCE_KEYS,
    SHOT_PLAN_BOUND_SOURCE_KEYS,
    require_checkpoint_matches_manifest,
    require_manifest_matches_plan,
    require_render_plan_matches_shot_plan,
    require_shot_plan_bytes,
    validate_render_checkpoint,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "visual" / "blender" / "scripts" / "render_episode.py"

ENVIRONMENT = {"blender_version": "4.5.12", "engine": "CYCLES", "device": "OPTIX"}


def _load_executor() -> Any:
    """Import the production executor without Blender present."""
    spec = importlib.util.spec_from_file_location("render_episode_binding", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


executor = _load_executor()

Mutation = Callable[[dict[str, Any]], None]


# --------------------------------------------------------------------------
# Render plan versus the direction it names
# --------------------------------------------------------------------------


def _forge_playback_beats(plan: dict[str, Any]) -> None:
    """The reviewer's first reproduction: attribute a frame to a beat it has no part in."""
    plan["frames"][0]["source_beat_ids"] = ["FAKE_BEAT"]


def _forge_witness_beats(plan: dict[str, Any]) -> None:
    """The one frame nobody watches is not the one whose direction is free."""
    plan["frames"][-1]["source_beat_ids"] = ["FAKE_BEAT"]


def _forge_interior_beats(plan: dict[str, Any]) -> None:
    """A frame inside a beat shot, re-attributed to nothing at all."""
    plan["frames"][60]["source_beat_ids"] = []


def _unapproved_camera(plan: dict[str, Any]) -> None:
    """The reviewer's second reproduction, at the relationship layer."""
    plan["frames"][0]["camera_anchor_id"] = "BANANA"


def _approved_but_undirected_camera(plan: dict[str, Any]) -> None:
    """A real anchor, on a frame Phase 22 pointed a different one at.

    Harder than ``BANANA``: membership in the approved set cannot catch this,
    only the shot windows can.
    """
    plan["frames"][0]["camera_anchor_id"] = "CAM_SEAL_DETAIL"


def _forge_witness_camera(plan: dict[str, Any]) -> None:
    """The boundary frame is derived from the shot windows like any other."""
    plan["frames"][-1]["camera_anchor_id"] = "CAM_SEAL_DETAIL"


def _forge_shot_id(plan: dict[str, Any]) -> None:
    """A frame credited to a shot that does not own it."""
    plan["frames"][0]["shot_id"] = "shot_0002"


def _alternate_timeline(plan: dict[str, Any]) -> None:
    """The reviewer's fourth reproduction: a self-consistent alternate clock.

    ``1 + 25 + 119 + 48`` closes on frame 193, emits the same 192 playback
    frames and runs the same 8.0 seconds. Every arithmetic rule holds; the
    document simply is not the clock it says it came from.
    """
    plan["timeline"]["start_hold_frames"] = 25
    plan["timeline"]["transition_frames"] = 119
    plan["timeline"]["transition_start"] = 26


PLAN_RELATIONSHIP_ATTACKS: dict[str, Mutation] = {
    "forged playback beats": _forge_playback_beats,
    "forged witness beats": _forge_witness_beats,
    "emptied interior beats": _forge_interior_beats,
    "unapproved camera": _unapproved_camera,
    "approved but undirected camera": _approved_but_undirected_camera,
    "forged witness camera": _forge_witness_camera,
    "forged shot id": _forge_shot_id,
    "alternate timeline": _alternate_timeline,
}
"""Mutations of a valid render plan that contradict a valid shot plan."""


def test_the_canonical_pair_is_accepted(
    render_plan: dict[str, Any], shot_plan_leg1: dict[str, Any]
) -> None:
    """The control. Without it every refusal below could be vacuous."""
    assert require_render_plan_matches_shot_plan(render_plan, shot_plan_leg1) == render_plan


@pytest.mark.parametrize("name", sorted(PLAN_RELATIONSHIP_ATTACKS))
def test_a_render_plan_that_contradicts_its_direction_is_refused(
    name: str, render_plan: dict[str, Any], shot_plan_leg1: dict[str, Any]
) -> None:
    """Each of these documents is valid on its own, and lies about the other."""
    broken = copy.deepcopy(render_plan)
    PLAN_RELATIONSHIP_ATTACKS[name](broken)
    with pytest.raises((TypeError, ValueError)):
        require_render_plan_matches_shot_plan(broken, shot_plan_leg1)


@pytest.mark.parametrize("key", SHOT_PLAN_BOUND_SOURCE_KEYS)
def test_every_copied_source_field_is_compared(
    key: str, render_plan: dict[str, Any], shot_plan_leg1: dict[str, Any]
) -> None:
    """Not a sample of the copied fields -- all of them, one test each."""
    broken = copy.deepcopy(render_plan)
    original = broken["source"][key]
    broken["source"][key] = 0 if isinstance(original, str) else "0" * 64
    with pytest.raises((TypeError, ValueError)):
        require_render_plan_matches_shot_plan(broken, shot_plan_leg1)


def test_the_bound_source_keys_are_the_whole_intersection(
    render_plan: dict[str, Any], shot_plan_leg1: dict[str, Any]
) -> None:
    """A field the two documents share must be compared, not merely present.

    This is the test that stops the comparison list from silently falling
    behind: adding a shared field to both contracts without adding it here
    fails immediately.
    """
    shared = set(render_plan["source"]) & set(shot_plan_leg1["source"])
    assert shared == set(SHOT_PLAN_BOUND_SOURCE_KEYS)


def test_a_plan_bound_to_a_different_shot_plan_is_refused(
    render_plan: dict[str, Any], shot_plan_baseline: dict[str, Any]
) -> None:
    """The baseline's direction cannot certify the transition's plan."""
    with pytest.raises(ValueError, match="was built for shot direction plan"):
        require_render_plan_matches_shot_plan(render_plan, shot_plan_baseline)


# --------------------------------------------------------------------------
# The shot plan's exact bytes
# --------------------------------------------------------------------------


def test_the_exact_canonical_bytes_are_accepted(
    render_plan: dict[str, Any], shot_plan_leg1: dict[str, Any]
) -> None:
    """The control for the byte-identity attacks below."""
    payload = dumps_canonical(shot_plan_leg1, "shot direction plan")
    assert require_shot_plan_bytes(render_plan, payload) == render_plan


@pytest.mark.parametrize("form", ["pretty", "reordered", "trailing space", "leading newline"])
def test_the_same_data_written_differently_is_a_different_source(
    form: str, render_plan: dict[str, Any], shot_plan_leg1: dict[str, Any]
) -> None:
    """Canonicalising before hashing would accept every one of these.

    Each carries exactly the same data and is a different file. The render plan
    bound a digest of one specific reviewed file, and "the same data, differently
    written" does not have that digest.
    """
    canonical = dumps_canonical(shot_plan_leg1, "shot direction plan")
    payloads = {
        "pretty": json.dumps(shot_plan_leg1, indent=2).encode("utf-8"),
        "reordered": json.dumps(
            dict(reversed(list(shot_plan_leg1.items()))), separators=(",", ":")
        ).encode("utf-8")
        + b"\n",
        "trailing space": canonical + b" ",
        "leading newline": b"\n" + canonical,
    }
    with pytest.raises(ValueError, match="exact bytes"):
        require_shot_plan_bytes(render_plan, payloads[form])


def test_a_semantically_mutated_shot_plan_is_refused(
    render_plan: dict[str, Any], shot_plan_leg1: dict[str, Any]
) -> None:
    """Dropping the record of what was honestly left unshown changes the file."""
    mutated = copy.deepcopy(shot_plan_leg1)
    mutated["unshown"] = []
    with pytest.raises(ValueError, match="exact bytes"):
        require_shot_plan_bytes(render_plan, dumps_canonical(mutated, "shot direction plan"))


def test_shot_plan_bytes_must_be_bytes(render_plan: dict[str, Any]) -> None:
    """A str is not a file's contents, and decoding one would be a guess."""
    with pytest.raises(TypeError):
        require_shot_plan_bytes(render_plan, "{}")


# --------------------------------------------------------------------------
# Manifest versus the plan it claims to describe
# --------------------------------------------------------------------------


@pytest.fixture
def manifest(render_plan: dict[str, Any]) -> dict[str, Any]:
    """A truthful manifest for the canonical plan, with plausible results."""
    results = {
        entry["frame"]: {
            "bytes": 900_000 + index,
            "sha256": f"{index:064x}",
            "image_sha256": f"{index + 1000:064x}",
        }
        for index, entry in enumerate(render_plan["frames"])
    }
    return build_episode_render_manifest_document(
        render_plan=render_plan,
        results=results,
        environment=ENVIRONMENT,
        witness_difference=0.08,
    )


MANIFEST_CONTRADICTIONS: dict[str, Mutation] = {
    "story plan": lambda m: m["source"].update(story_plan_sha256="0" * 64),
    "motion time": lambda m: m["source"].update(motion_time_sha256="0" * 64),
    "catalogue": lambda m: m["source"].update(catalogue_sha256="0" * 64),
    "shot plan": lambda m: m["source"].update(shot_plan_sha256="0" * 64),
    "before export": lambda m: m["source"].update(before_export_sha256="0" * 64),
    "after export": lambda m: m["source"].update(after_export_sha256="0" * 64),
    "mode": lambda m: m["source"].update(
        mode="baseline", previous_episode=None, before_export_sha256=None
    ),
    "episode": lambda m: m["source"].update(episode=5, previous_episode=4),
    "emission fps": lambda m: m["emission"].update(playback_fps=48, playback_seconds=4.0),
    "frame shot id": lambda m: m["frames"][0].update(shot_id="shot_9999"),
    "frame camera": lambda m: m["frames"][0].update(camera_anchor_id="CAM_SEAL_DETAIL"),
    "frame beats": lambda m: m["frames"][0].update(source_beat_ids=["FAKE_BEAT"]),
    "witness beats": lambda m: m["frames"][-1].update(source_beat_ids=["FAKE_BEAT"]),
}
"""Manifest edits that leave ``render_plan_sha256`` alone and still lie.

Every one of these produced a manifest V2 accepted: it validated against its own
contract, it bound the right plan digest, and nothing ever compared the two.
"""


def test_a_truthful_manifest_matches_its_plan(
    manifest: dict[str, Any], render_plan: dict[str, Any]
) -> None:
    """The control."""
    assert require_manifest_matches_plan(manifest, render_plan) == manifest


SELF_CAUGHT_CONTRADICTIONS = frozenset({"motion time"})
"""The one contradiction a manifest cannot make without also failing alone.

``composition_sources.motion_time_sha256`` must equal the source block's, so
editing one of the two breaks an internal rule before any comparison happens.
Named explicitly rather than left to a conditional, because the interesting
claim is that every OTHER mutation here produces a perfectly valid manifest.
"""


@pytest.mark.parametrize("name", sorted(MANIFEST_CONTRADICTIONS))
def test_a_manifest_that_contradicts_its_plan_is_refused(
    name: str, manifest: dict[str, Any], render_plan: dict[str, Any]
) -> None:
    """Whatever else catches it, the comparison must."""
    broken = copy.deepcopy(manifest)
    MANIFEST_CONTRADICTIONS[name](broken)
    assert broken["source"]["render_plan_sha256"] == manifest["source"]["render_plan_sha256"]
    with pytest.raises((TypeError, ValueError)):
        require_manifest_matches_plan(broken, render_plan)


@pytest.mark.parametrize("name", sorted(set(MANIFEST_CONTRADICTIONS) - SELF_CAUGHT_CONTRADICTIONS))
def test_a_contradicting_manifest_is_still_a_valid_manifest(
    name: str, manifest: dict[str, Any]
) -> None:
    """This is the finding, stated as a test: validity is not truthfulness.

    Each of these documents passes the manifest contract completely. V2 checked
    exactly that, plus the plan digest, and concluded the render was sound.
    """
    broken = copy.deepcopy(manifest)
    MANIFEST_CONTRADICTIONS[name](broken)
    assert validate_episode_render_manifest(broken) == broken


def test_a_manifest_may_still_record_what_only_a_render_knows(
    manifest: dict[str, Any], render_plan: dict[str, Any]
) -> None:
    """The comparison must not turn into "the manifest may say nothing new".

    Byte lengths, digests, the environment and the completion verdict describe a
    file that did not exist when the plan was written, and the plan is not
    entitled to an opinion about them.
    """
    for key in ("bytes", "sha256", "image_sha256"):
        assert key in manifest["frames"][0]
        assert key not in render_plan["frames"][0]
    assert require_manifest_matches_plan(manifest, render_plan) == manifest


def test_the_exclusive_key_sets_are_exactly_what_the_documents_differ_by(
    manifest: dict[str, Any], render_plan: dict[str, Any]
) -> None:
    """The comparison covers everything else by construction, not by memory.

    Both exclusive sets are derived from the two contracts here rather than
    asserted, so a field added to either document without a decision about
    which side owns it fails immediately instead of quietly escaping comparison.
    """
    assert set(manifest["source"]) - set(render_plan["source"]) == MANIFEST_EXCLUSIVE_SOURCE_KEYS
    assert set(render_plan["source"]) - set(manifest["source"]) == set()

    planned_frame = render_plan["frames"][0]
    recorded_frame = manifest["frames"][0]
    assert set(recorded_frame) - set(planned_frame) == MANIFEST_EXCLUSIVE_FRAME_KEYS
    assert set(planned_frame) - set(recorded_frame) == set()


def test_a_manifest_bound_to_another_plan_is_refused(
    manifest: dict[str, Any], baseline_render_plan: dict[str, Any]
) -> None:
    """The digest binding still does its own job."""
    with pytest.raises(ValueError, match="binds render plan"):
        require_manifest_matches_plan(manifest, baseline_render_plan)


def test_the_manifest_names_the_world_it_photographed(
    manifest: dict[str, Any], render_plan: dict[str, Any]
) -> None:
    """A manifest is what downstream layers are handed; it cannot be silent here."""
    assert manifest["composition_sources"] == render_plan["composition_sources"]
    broken = copy.deepcopy(manifest)
    broken["composition_sources"]["state_response_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        require_manifest_matches_plan(broken, render_plan)


# --------------------------------------------------------------------------
# Parity: the executor restates every rule above
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(PLAN_RELATIONSHIP_ATTACKS))
def test_both_implementations_refuse_the_same_contradictions(
    name: str, render_plan: dict[str, Any], shot_plan_leg1: dict[str, Any]
) -> None:
    """One validator refusing what the other accepts is not a boundary."""
    broken = copy.deepcopy(render_plan)
    PLAN_RELATIONSHIP_ATTACKS[name](broken)
    with pytest.raises((TypeError, ValueError)):
        require_render_plan_matches_shot_plan(broken, shot_plan_leg1)
    with pytest.raises(executor.PlanRefused):
        executor.require_plan_matches_shot_plan(broken, shot_plan_leg1)


def test_both_implementations_accept_the_canonical_pair(
    render_plan: dict[str, Any], shot_plan_leg1: dict[str, Any]
) -> None:
    """Parity has to include agreeing on what is correct."""
    require_render_plan_matches_shot_plan(render_plan, shot_plan_leg1)
    executor.require_plan_matches_shot_plan(render_plan, shot_plan_leg1)


@pytest.mark.parametrize("form", ["pretty", "trailing space"])
def test_both_implementations_require_the_exact_shot_plan_bytes(
    form: str, render_plan: dict[str, Any], shot_plan_leg1: dict[str, Any]
) -> None:
    """The byte-identity rule is enforced on both sides of the boundary."""
    canonical = dumps_canonical(shot_plan_leg1, "shot direction plan")
    payload = {
        "pretty": json.dumps(shot_plan_leg1, indent=2).encode("utf-8"),
        "trailing space": canonical + b" ",
    }[form]
    with pytest.raises(ValueError):
        require_shot_plan_bytes(render_plan, payload)
    with pytest.raises(executor.PlanRefused):
        executor.require_shot_plan_bytes(render_plan, payload)
    executor.require_shot_plan_bytes(render_plan, canonical)


def test_the_historic_direction_entry_point_reaches_the_complete_check(
    render_plan: dict[str, Any], shot_plan_leg1: dict[str, Any]
) -> None:
    """No caller may land on the narrow check V2 shipped."""
    broken = copy.deepcopy(render_plan)
    _forge_playback_beats(broken)
    with pytest.raises(executor.PlanRefused):
        executor.require_plan_matches_direction(broken, shot_plan_leg1)


# --------------------------------------------------------------------------
# The checkpoint: standalone against the plan, then in relation to the manifest
# --------------------------------------------------------------------------
#
# An independent reviewer proved the independent audit was the weaker half
# here. `require_checkpoint_matches_manifest` proved a checkpoint agreed with
# the manifest beside it, but never opened the Render Plan -- so a checkpoint
# whose own `render_plan_sha256` or `render_profile_sha256` named an entirely
# different render, with every frame record otherwise truthful, passed the
# independent audit completely. Production has always checked a checkpoint
# against the actual plan; `validate_render_checkpoint` is the engine's
# equivalent, called separately and required alongside the relationship check
# rather than folded into it.


@pytest.fixture
def checkpoint(render_plan: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """A truthful checkpoint agreeing with the canonical manifest, for every frame."""
    return {
        "render_plan_sha256": manifest["source"]["render_plan_sha256"],
        "render_profile_sha256": render_plan["source"]["render_profile_sha256"],
        "environment": dict(manifest["environment"]),
        "frames": {
            str(entry["frame"]): {
                "bytes": entry["bytes"],
                "sha256": entry["sha256"],
                "image_sha256": entry["image_sha256"],
            }
            for entry in manifest["frames"]
        },
    }


def test_a_truthful_checkpoint_validates_standalone_against_the_plan(
    checkpoint: dict[str, Any], render_plan: dict[str, Any]
) -> None:
    """The control for the standalone check."""
    resolved = validate_render_checkpoint(checkpoint, render_plan)
    assert len(resolved) == len(checkpoint["frames"])


def test_a_truthful_checkpoint_matches_the_manifest(
    checkpoint: dict[str, Any], manifest: dict[str, Any]
) -> None:
    """The control for the relationship check."""
    require_checkpoint_matches_manifest(checkpoint, manifest)


CHECKPOINT_PLAN_CONTRADICTIONS: dict[str, Mutation] = {
    "wrong render_plan_sha256": lambda c: c.update(render_plan_sha256="0" * 64),
    "wrong render_profile_sha256": lambda c: c.update(render_profile_sha256="0" * 64),
    "missing environment field": lambda c: c["environment"].pop("device"),
    "extra environment field": lambda c: c["environment"].update(gpu="x"),
    "blank environment value": lambda c: c["environment"].update(device="   "),
    "non-string environment value": lambda c: c["environment"].update(device=7),
    "environment value with surrounding whitespace": lambda c: c["environment"].update(
        device=" OPTIX "
    ),
    "unknown frame": lambda c: c["frames"].update({"9999": next(iter(c["frames"].values()))}),
    "leading-zero frame key": lambda c: c["frames"].update({"01": c["frames"].pop("1")}),
    "unicode-digit frame key": lambda c: c["frames"].update({"١": c["frames"].pop("1")}),
    "wrong bytes type": lambda c: c["frames"]["1"].update(bytes="900000"),
    "zero bytes": lambda c: c["frames"]["1"].update(bytes=0),
    "malformed sha256": lambda c: c["frames"]["1"].update(sha256="not-a-digest"),
    "missing frame-result field": lambda c: c["frames"]["1"].pop("image_sha256"),
    "extra frame-result field": lambda c: c["frames"]["1"].update(extra="x"),
}
"""Checkpoints that are individually wrong about the plan they name.

Every one of these leaves the checkpoint's frame RESULTS mutually consistent
with themselves -- these are attacks on the checkpoint's own contract and its
identity, not on its agreement with a manifest, so they belong on the
standalone validator.
"""


@pytest.mark.parametrize("name", sorted(CHECKPOINT_PLAN_CONTRADICTIONS))
def test_a_checkpoint_that_contradicts_its_own_plan_is_refused(
    name: str, checkpoint: dict[str, Any], render_plan: dict[str, Any]
) -> None:
    """Standalone validation catches these without ever looking at a manifest."""
    broken = copy.deepcopy(checkpoint)
    CHECKPOINT_PLAN_CONTRADICTIONS[name](broken)
    with pytest.raises((TypeError, ValueError)):
        validate_render_checkpoint(broken, render_plan)


def test_a_second_spelling_of_one_frame_is_refused(
    checkpoint: dict[str, Any], render_plan: dict[str, Any]
) -> None:
    """`"1"` and `"01"` cannot both vouch for frame 1.

    Canonical-key enforcement refuses ``"01"`` on its own, before the
    duplicate-frame check ever runs -- there is exactly one string a valid
    JSON object key dict can hold for a given frame, so two live records for
    one frame are only reachable through two different spellings, and the
    spelling check is what closes that path. Either refusal reason -- an
    illegal spelling, or a semantic duplicate -- answers the review's
    requirement; this is the one the code actually reaches.
    """
    broken = copy.deepcopy(checkpoint)
    broken["frames"]["01"] = broken["frames"]["1"]
    with pytest.raises(ValueError, match="canonical spelling"):
        validate_render_checkpoint(broken, render_plan)


def test_an_unreasonably_long_frame_key_is_refused_not_crashed(
    checkpoint: dict[str, Any], render_plan: dict[str, Any]
) -> None:
    """A key past CPython's int/str conversion limit is still this function's refusal.

    ``int()`` itself raises ``ValueError`` once a digit string exceeds the
    interpreter's default conversion limit (4300 digits, since 3.11). That
    exception must not reach the caller unwrapped: it is exactly the
    ``ValueError`` this function already raises for every other illegal
    spelling, carrying the field's own description, not CPython's.
    """
    broken = copy.deepcopy(checkpoint)
    huge = "1" * 4301
    broken["frames"][huge] = broken["frames"].pop("1")
    with pytest.raises(ValueError, match="frame"):
        validate_render_checkpoint(broken, render_plan)


CHECKPOINT_MANIFEST_CONTRADICTIONS: dict[str, Mutation] = {
    "frame bytes": lambda c: c["frames"]["1"].update(bytes=999_999),
    # Not "0" * 64: frame 1's fixture sha256 is f"{0:064x}", which IS 64
    # zeros, so that mutation would silently be a no-op.
    "frame sha256": lambda c: c["frames"]["1"].update(sha256="a" * 64),
    "frame image_sha256": lambda c: c["frames"]["1"].update(image_sha256="a" * 64),
    "environment": lambda c: c["environment"].update(device="SOMEWHERE_ELSE"),
}
"""Checkpoints that are internally well-formed and disagree with the manifest.

Each of these would pass ``validate_render_checkpoint`` on its own -- there is
nothing wrong with the checkpoint by itself -- which is exactly why the
relationship check has to exist as a second, separate step.
"""


@pytest.mark.parametrize("name", sorted(CHECKPOINT_MANIFEST_CONTRADICTIONS))
def test_a_checkpoint_that_contradicts_the_manifest_is_refused(
    name: str, checkpoint: dict[str, Any], render_plan: dict[str, Any], manifest: dict[str, Any]
) -> None:
    """The relationship check catches what the standalone one cannot see."""
    broken = copy.deepcopy(checkpoint)
    CHECKPOINT_MANIFEST_CONTRADICTIONS[name](broken)
    # Still a well-formed checkpoint against its own plan.
    validate_render_checkpoint(broken, render_plan)
    with pytest.raises(ValueError):
        require_checkpoint_matches_manifest(broken, manifest)


def test_neither_checkpoint_check_alone_is_sufficient(
    checkpoint: dict[str, Any], render_plan: dict[str, Any], manifest: dict[str, Any]
) -> None:
    """The two independent checks are not redundant with one another.

    A checkpoint claiming the wrong plan passes the relationship check
    completely -- ``require_checkpoint_matches_manifest`` never opens the plan,
    so it has nothing to object to. A checkpoint that is a perfectly honest
    restatement of the plan but lies about one frame's result passes the
    standalone check completely, for the same reason in reverse. Calling only
    one of the two would have left exactly the hole the reviewer found.
    """
    wrong_plan = copy.deepcopy(checkpoint)
    wrong_plan["render_plan_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        validate_render_checkpoint(wrong_plan, render_plan)
    require_checkpoint_matches_manifest(wrong_plan, manifest)  # does not raise

    wrong_frame = copy.deepcopy(checkpoint)
    wrong_frame["frames"]["1"]["sha256"] = "a" * 64
    validate_render_checkpoint(wrong_frame, render_plan)  # does not raise
    with pytest.raises(ValueError):
        require_checkpoint_matches_manifest(wrong_frame, manifest)


def test_a_partial_checkpoint_is_accepted_by_both_checks(
    checkpoint: dict[str, Any], render_plan: dict[str, Any], manifest: dict[str, Any]
) -> None:
    """A checkpoint from an interrupted run legitimately knows about fewer frames.

    Holding a strict subset of the plan's frames is what resuming means, and
    neither the standalone check nor the relationship check may treat that as
    a contradiction.
    """
    partial = copy.deepcopy(checkpoint)
    partial["frames"] = {"1": partial["frames"]["1"]}
    validate_render_checkpoint(partial, render_plan)
    require_checkpoint_matches_manifest(partial, manifest)


# --------------------------------------------------------------------------
# Parity: the executor restates every one of the same rules
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(CHECKPOINT_PLAN_CONTRADICTIONS))
def test_both_sides_refuse_the_same_plan_contradiction(
    name: str, checkpoint: dict[str, Any], render_plan: dict[str, Any]
) -> None:
    """Production's single call and the engine's standalone call must agree."""
    broken = copy.deepcopy(checkpoint)
    CHECKPOINT_PLAN_CONTRADICTIONS[name](broken)
    plan_digest = sha256_hex(dumps_canonical(render_plan, "episode render plan"))
    with pytest.raises((TypeError, ValueError)):
        validate_render_checkpoint(broken, render_plan)
    with pytest.raises(executor.RenderDirectoryRefused):
        executor.require_valid_checkpoint(broken, render_plan, plan_digest)


def test_both_sides_accept_the_canonical_checkpoint(
    checkpoint: dict[str, Any], render_plan: dict[str, Any]
) -> None:
    """Parity has to include agreeing on what is correct, not only on refusals."""
    plan_digest = sha256_hex(dumps_canonical(render_plan, "episode render plan"))
    validate_render_checkpoint(checkpoint, render_plan)
    executor.require_valid_checkpoint(checkpoint, render_plan, plan_digest)
