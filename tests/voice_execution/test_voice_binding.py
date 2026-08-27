"""Relationship validation: manifest <-> plan and the plan-copy exact-byte binding."""

import copy
from typing import Any

import pytest

from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.voice_execution import require_manifest_matches_plan, require_voice_plan_bytes


def test_a_truthful_manifest_matches_its_plan(
    plan_ep1: dict[str, Any], manifest_ep1: dict[str, Any]
) -> None:
    """A truthful manifest matches its plan."""
    assert require_manifest_matches_plan(manifest_ep1, plan_ep1) == manifest_ep1


def test_require_voice_plan_bytes_accepts_the_exact_bytes(
    plan_ep1: dict[str, Any], manifest_ep1: dict[str, Any]
) -> None:
    """require_voice_plan_bytes accepts the exact canonical bytes it was bound from."""
    payload = dumps_canonical(plan_ep1, "voice plan")
    assert require_voice_plan_bytes(manifest_ep1, payload) == manifest_ep1


def test_require_voice_plan_bytes_refuses_a_reserialized_copy(
    plan_ep1: dict[str, Any], manifest_ep1: dict[str, Any]
) -> None:
    """A byte-different re-serialization of the same content is refused."""
    import json

    pretty = json.dumps(plan_ep1, indent=2).encode("utf-8")
    with pytest.raises(ValueError, match="exact bytes|hashes to"):
        require_voice_plan_bytes(manifest_ep1, pretty)


def test_require_voice_plan_bytes_refuses_non_bytes(manifest_ep1: dict[str, Any]) -> None:
    """require_voice_plan_bytes refuses a non-bytes argument."""
    with pytest.raises(TypeError):
        require_voice_plan_bytes(manifest_ep1, "not bytes")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field",
    ["episode", "mode", "previous_episode", "presentation_plan_sha256", "realization_plan_sha256"],
)
def test_each_copied_source_field_forged_individually_is_refused(
    plan_ep1: dict[str, Any], manifest_ep1: dict[str, Any], field: str
) -> None:
    """Each copied source field, forged individually in the manifest, is refused."""
    source = dict(manifest_ep1["source"])
    if field == "previous_episode":
        source[field] = (source[field] or 0) + 1
    elif field.endswith("_sha256"):
        source[field] = "0" * 64
    elif field == "episode":
        source[field] = source[field] + 100
    else:
        source[field] = "baseline" if source[field] == "transition" else "transition"
    manifest = {**manifest_ep1, "source": source}
    with pytest.raises(ValueError):
        require_manifest_matches_plan(manifest, plan_ep1)


def test_a_unit_count_mismatch_is_refused(
    plan_ep1: dict[str, Any], manifest_ep1: dict[str, Any]
) -> None:
    """A unit count mismatch is refused."""
    voice_units = list(manifest_ep1["voice_units"])[:-1]
    manifest = {**manifest_ep1, "voice_units": voice_units}
    # Standalone validation runs first inside require_manifest_matches_plan
    # and refuses an empty/short list under its own accounting law, or the
    # relationship check refuses the count directly -- either is correct.
    with pytest.raises(ValueError):
        require_manifest_matches_plan(manifest, plan_ep1)


@pytest.mark.parametrize(
    "field", ["unit_id", "realization_id", "window_id", "voice_unit_id", "capacity_samples"]
)
def test_each_plan_side_unit_field_forged_per_position_is_refused(
    plan_ep1: dict[str, Any], manifest_ep1: dict[str, Any], field: str
) -> None:
    """Each of the five plan-side unit fields, forged per position, is refused."""
    voice_units = copy.deepcopy(manifest_ep1["voice_units"])
    if field == "capacity_samples":
        voice_units[0][field] = voice_units[0][field] + 1
    else:
        voice_units[0][field] = voice_units[0][field] + "_forged"
    manifest = {**manifest_ep1, "voice_units": voice_units}
    with pytest.raises(ValueError):
        require_manifest_matches_plan(manifest, plan_ep1)


def test_a_forged_voice_plan_sha256_binding_is_refused(
    plan_ep1: dict[str, Any], manifest_ep1: dict[str, Any]
) -> None:
    """A forged voice_plan_sha256 binding is refused."""
    source = {**manifest_ep1["source"], "voice_plan_sha256": "0" * 64}
    manifest = {**manifest_ep1, "source": source}
    with pytest.raises(ValueError, match="binds voice plan"):
        require_manifest_matches_plan(manifest, plan_ep1)
