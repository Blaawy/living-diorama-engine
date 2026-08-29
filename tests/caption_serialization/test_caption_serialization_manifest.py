"""Pure document construction: turning one locked plan and two sidecars into a manifest.

No frozen test-matrix section names this module explicitly; its own docstring
states its contract exactly -- pure, filesystem-free construction. The builder
is handed the validated plan, its exact captured bytes and the two serialized
sidecar artifacts, and these tests prove the document restates exactly those
facts: the plan's seven source values, its clock and accounting byte-for-byte,
and the two records measured from the artifacts actually given.
"""

from typing import Any

import pytest

from living_diorama.caption_serialization.caption_serialization_manifest import (
    build_episode_caption_serialization_manifest_bytes,
    build_episode_caption_serialization_manifest_document,
)
from living_diorama.caption_serialization.caption_serialization_schema_v1 import TOP_LEVEL_KEYS
from living_diorama.caption_serialization.caption_serialization_spec import (
    CAPTION_SERIALIZATION_SCHEMA_VERSION,
    CAPTION_TIMESTAMP_POLICY_V1,
    SRT_FORMAT_NAME,
    SRT_SUFFIX,
    VTT_FORMAT_NAME,
    VTT_SUFFIX,
)
from living_diorama.caption_serialization.srt_writer import serialize_srt_bytes
from living_diorama.caption_serialization.vtt_writer import serialize_vtt_bytes
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex


def _build_caption_plan(*, mode: str, episode: int, previous_episode: int | None) -> dict[str, Any]:
    """Build one synthetic valid Phase 32 caption plan (three cues, fps 24)."""
    total_frames = 130
    captions: list[dict[str, Any]] = []
    for position, (start, end) in enumerate(((1, 40), (41, 80), (81, 120)), start=1):
        captions.append(
            {
                "caption_id": f"caption_{position:04d}",
                "caption_text": f"Sentence number {position}.",
                "presentation_end_frame": end,
                "presentation_start_frame": start,
                "realization_id": f"realization_{position:04d}",
                "unit_id": f"unit_{position:04d}",
                "window_id": f"window_{position:04d}",
            }
        )
    return {
        "accounting": {
            "caption_frames_total": 120,
            "captions_total": 3,
            "uncaptioned_frames_total": total_frames - 120,
        },
        "captions": captions,
        "clock": {"fps": 24, "presentation_frames_total": total_frames},
        "format": "living_diorama_episode_caption_plan",
        "policy": "caption_policy_v1",
        "schema_version": 1,
        "source": {
            "episode": episode,
            "mode": mode,
            "previous_episode": previous_episode,
            "presentation_plan_sha256": "a" * 64,
            "presentation_schema_version": 1,
            "realization_plan_sha256": "b" * 64,
            "realization_schema_version": 1,
        },
    }


def _build_inputs(
    *, mode: str = "baseline", episode: int = 0, previous_episode: int | None = None
) -> tuple[dict[str, Any], bytes, bytes, bytes]:
    """Return (plan, caption_plan_bytes, srt_bytes, vtt_bytes) for one variant."""
    plan = _build_caption_plan(mode=mode, episode=episode, previous_episode=previous_episode)
    return (
        plan,
        dumps_canonical(plan, "p"),
        serialize_srt_bytes(plan),
        serialize_vtt_bytes(plan),
    )


def _build_document(
    *, mode: str = "baseline", episode: int = 0, previous_episode: int | None = None
) -> dict[str, Any]:
    """Build one valid Episode Caption Serialization Manifest document."""
    plan, caption_plan_bytes, srt_bytes, vtt_bytes = _build_inputs(
        mode=mode, episode=episode, previous_episode=previous_episode
    )
    return build_episode_caption_serialization_manifest_document(
        caption_plan=plan,
        caption_plan_bytes=caption_plan_bytes,
        srt_bytes=srt_bytes,
        vtt_bytes=vtt_bytes,
    )


VARIANTS = [
    ("baseline", 0, None, "episode_0000_baseline"),
    ("transition", 1, 0, "episode_0000_to_0001"),
]


@pytest.mark.parametrize(
    ("mode", "episode", "previous", "episode_id"),
    VARIANTS,
    ids=["baseline-ep0", "transition-ep1"],
)
def test_built_manifest_has_exactly_the_top_level_keys(
    mode: str, episode: int, previous: int | None, episode_id: str
) -> None:
    """Built manifest has exactly the top level keys."""
    document = _build_document(mode=mode, episode=episode, previous_episode=previous)
    assert set(document.keys()) == set(TOP_LEVEL_KEYS)


@pytest.mark.parametrize(
    ("mode", "episode", "previous", "episode_id"),
    VARIANTS,
    ids=["baseline-ep0", "transition-ep1"],
)
def test_source_restates_the_plans_seven_values_and_binds_the_bytes(
    mode: str, episode: int, previous: int | None, episode_id: str
) -> None:
    """Source restates the plan's seven values and binds the captured bytes."""
    plan, caption_plan_bytes, _, _ = _build_inputs(
        mode=mode, episode=episode, previous_episode=previous
    )
    document = _build_document(mode=mode, episode=episode, previous_episode=previous)
    plan_source = plan["source"]
    assert document["source"]["episode"] == plan_source["episode"]
    assert document["source"]["mode"] == plan_source["mode"]
    assert document["source"]["previous_episode"] == plan_source["previous_episode"]
    plan_presentation_sha = plan_source["presentation_plan_sha256"]
    assert document["source"]["presentation_plan_sha256"] == plan_presentation_sha
    assert (
        document["source"]["presentation_schema_version"]
        == plan_source["presentation_schema_version"]
    )
    plan_realization_sha = plan_source["realization_plan_sha256"]
    assert document["source"]["realization_plan_sha256"] == plan_realization_sha
    assert (
        document["source"]["realization_schema_version"]
        == plan_source["realization_schema_version"]
    )
    assert document["source"]["caption_plan_sha256"] == sha256_hex(caption_plan_bytes)
    assert document["source"]["caption_schema_version"] == CAPTION_SERIALIZATION_SCHEMA_VERSION


def test_accounting_and_clock_are_restated_byte_for_byte() -> None:
    """Accounting and clock blocks equal the plan's own blocks."""
    plan, _, _, _ = _build_inputs()
    document = _build_document()
    assert document["accounting"] == plan["accounting"]
    assert document["clock"] == plan["clock"]


@pytest.mark.parametrize(
    ("mode", "episode", "previous", "episode_id"),
    VARIANTS,
    ids=["baseline-ep0", "transition-ep1"],
)
def test_sidecar_records_carry_the_artifacts_lengths_digests_and_derived_names(
    mode: str, episode: int, previous: int | None, episode_id: str
) -> None:
    """Sidecar records carry len and sha256 of the artifacts and derived names."""
    _, _, srt_bytes, vtt_bytes = _build_inputs(
        mode=mode, episode=episode, previous_episode=previous
    )
    document = _build_document(mode=mode, episode=episode, previous_episode=previous)
    srt = document["sidecars"]["srt"]
    vtt = document["sidecars"]["vtt"]
    assert srt["bytes"] == len(srt_bytes)
    assert srt["sha256"] == sha256_hex(srt_bytes)
    assert srt["file"] == f"{episode_id}{SRT_SUFFIX}"
    assert srt["format"] == SRT_FORMAT_NAME
    assert vtt["bytes"] == len(vtt_bytes)
    assert vtt["sha256"] == sha256_hex(vtt_bytes)
    assert vtt["file"] == f"{episode_id}{VTT_SUFFIX}"
    assert vtt["format"] == VTT_FORMAT_NAME


def test_policy_declares_caption_timestamp_policy_v1() -> None:
    """Policy declares caption timestamp policy v1."""
    document = _build_document()
    assert document["policy"] == CAPTION_TIMESTAMP_POLICY_V1


def test_schema_version_is_one() -> None:
    """Schema version is one."""
    document = _build_document()
    assert document["schema_version"] == CAPTION_SERIALIZATION_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_non_canonical_caption_plan_bytes_refused() -> None:
    """Non canonical caption plan bytes refused."""
    plan, _, srt_bytes, vtt_bytes = _build_inputs()
    with pytest.raises(ValueError, match="canonical"):
        build_episode_caption_serialization_manifest_document(
            caption_plan=plan,
            caption_plan_bytes=b"{}",
            srt_bytes=srt_bytes,
            vtt_bytes=vtt_bytes,
        )


@pytest.mark.parametrize("field", ["caption_plan_bytes", "srt_bytes", "vtt_bytes"])
def test_bytes_fields_refuse_str(field: str) -> None:
    """Bytes fields refuse str."""
    plan, caption_plan_bytes, srt_bytes, vtt_bytes = _build_inputs()
    kwargs: dict[str, Any] = {
        "caption_plan": plan,
        "caption_plan_bytes": caption_plan_bytes,
        "srt_bytes": srt_bytes,
        "vtt_bytes": vtt_bytes,
    }
    kwargs[field] = "not-bytes"
    with pytest.raises(TypeError):
        build_episode_caption_serialization_manifest_document(**kwargs)


def test_an_invalid_caption_plan_is_refused() -> None:
    """An invalid caption plan is refused."""
    with pytest.raises(ValueError):
        build_episode_caption_serialization_manifest_document(
            caption_plan={},
            caption_plan_bytes=b"{}",
            srt_bytes=b"1\n00:00:00,000 --> 00:00:01,000\nx\n",
            vtt_bytes=b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nx\n",
        )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_building_twice_produces_equal_documents() -> None:
    """Building twice produces equal documents."""
    assert _build_document() == _build_document()


def test_build_bytes_equals_dumps_canonical_of_the_document() -> None:
    """Build bytes equals dumps canonical of the document."""
    plan, caption_plan_bytes, srt_bytes, vtt_bytes = _build_inputs()
    document = build_episode_caption_serialization_manifest_document(
        caption_plan=plan,
        caption_plan_bytes=caption_plan_bytes,
        srt_bytes=srt_bytes,
        vtt_bytes=vtt_bytes,
    )
    payload = build_episode_caption_serialization_manifest_bytes(
        caption_plan=plan,
        caption_plan_bytes=caption_plan_bytes,
        srt_bytes=srt_bytes,
        vtt_bytes=vtt_bytes,
    )
    assert payload == dumps_canonical(document, "episode caption serialization manifest")
