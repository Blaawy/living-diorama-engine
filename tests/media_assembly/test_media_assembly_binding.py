"""Relationship proofs: the twelve named cross-branch provenance joins and byte bindings.

The twelve joins are A, B1, B2, C1, C2, D1, D2, D3, D4, E, F and G, plus the two
whole-artifact byte bindings. Every source document is real, produced by the actual
upstream layers via the shared fixtures. Each join is attacked independently, one field
at a time, so a passing suite proves no join is vacuously satisfied by another.
"""

import copy
from typing import Any

import pytest

from living_diorama.media_assembly.media_assembly_binding import (
    require_assembly_matches_sources,
    require_assembly_sources_join,
    require_episode_audio_bytes,
    require_render_frame_bytes,
)
from living_diorama.media_assembly.media_assembly_manifest import (
    build_episode_media_assembly_manifest_document,
)
from living_diorama.media_assembly.media_assembly_mapping import (
    presentation_frame_map,
    require_clock_closure,
    require_playback_lookup,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex


def _join_kwargs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Return the positional documents and the five keyword digests, from real inputs."""
    return {
        "render_manifest": inputs["render_manifest"],
        "presentation_plan": inputs["presentation_plan"],
        "audio_composition_manifest": inputs["audio_composition_manifest"],
        "delivery_plan": inputs["delivery_plan"],
        "render_manifest_sha256": sha256_hex(inputs["render_manifest_bytes"]),
        "presentation_plan_sha256": sha256_hex(inputs["presentation_plan_bytes"]),
        "audio_composition_manifest_sha256": sha256_hex(inputs["audio_composition_manifest_bytes"]),
        "delivery_plan_sha256": sha256_hex(inputs["delivery_plan_bytes"]),
        "shot_plan_sha256": sha256_hex(inputs["shot_plan_bytes"]),
    }


def test_all_joins_pass_on_real_sources(assembly_inputs_ep1: dict[str, Any]) -> None:
    """All joins pass on real sources."""
    require_assembly_sources_join(
        assembly_inputs_ep1["render_manifest"],
        assembly_inputs_ep1["presentation_plan"],
        assembly_inputs_ep1["audio_composition_manifest"],
        assembly_inputs_ep1["delivery_plan"],
        **{k: v for k, v in _join_kwargs(assembly_inputs_ep1).items() if k.endswith("sha256")},
    )


def _call(kwargs: dict[str, Any]) -> None:
    require_assembly_sources_join(
        kwargs["render_manifest"],
        kwargs["presentation_plan"],
        kwargs["audio_composition_manifest"],
        kwargs["delivery_plan"],
        render_manifest_sha256=kwargs["render_manifest_sha256"],
        presentation_plan_sha256=kwargs["presentation_plan_sha256"],
        audio_composition_manifest_sha256=kwargs["audio_composition_manifest_sha256"],
        delivery_plan_sha256=kwargs["delivery_plan_sha256"],
        shot_plan_sha256=kwargs["shot_plan_sha256"],
    )


def test_join_a_presentation_digest_mismatch_refused(assembly_inputs_ep1: dict[str, Any]) -> None:
    """Join a presentation digest mismatch refused."""
    kwargs = _join_kwargs(assembly_inputs_ep1)
    kwargs["presentation_plan_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        _call(kwargs)


def test_join_b1_render_digest_mismatch_refused(assembly_inputs_ep1: dict[str, Any]) -> None:
    """Join B1 render digest mismatch refused."""
    kwargs = _join_kwargs(assembly_inputs_ep1)
    kwargs["render_manifest_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        _call(kwargs)


def test_join_c1_composition_digest_mismatch_refused(assembly_inputs_ep1: dict[str, Any]) -> None:
    """Join C1 composition digest mismatch refused."""
    kwargs = _join_kwargs(assembly_inputs_ep1)
    kwargs["audio_composition_manifest_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        _call(kwargs)


def test_join_d1_shot_plan_digest_mismatch_refused(assembly_inputs_ep1: dict[str, Any]) -> None:
    """Join D1 shot plan digest mismatch refused."""
    kwargs = _join_kwargs(assembly_inputs_ep1)
    kwargs["shot_plan_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        _call(kwargs)


def test_join_d2_render_manifest_from_a_different_shot_plan_refused(
    assembly_inputs_ep0: dict[str, Any], assembly_inputs_ep1: dict[str, Any]
) -> None:
    """Join D2 render manifest from a different shot plan refused.

    A render manifest whose bound shot_plan_sha256 names a different, valid shot plan --
    same episode/mode/previous_episode/motion_time -- must still be refused.
    """
    kwargs = _join_kwargs(assembly_inputs_ep1)
    broken_render = copy.deepcopy(kwargs["render_manifest"])
    other_shot_digest = sha256_hex(assembly_inputs_ep0["shot_plan_bytes"])
    assert other_shot_digest != broken_render["source"]["shot_plan_sha256"]
    broken_render["source"]["shot_plan_sha256"] = other_shot_digest
    kwargs["render_manifest"] = broken_render
    kwargs["render_manifest_sha256"] = sha256_hex(
        dumps_canonical(broken_render, "episode render manifest")
    )
    with pytest.raises(ValueError):
        _call(kwargs)


def test_join_d3_delivery_witness_unbound_refused(assembly_inputs_ep1: dict[str, Any]) -> None:
    """Join D3 delivery witness unbound refused."""
    kwargs = _join_kwargs(assembly_inputs_ep1)
    kwargs["delivery_plan_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        _call(kwargs)


def test_join_d4_shot_witness_unbound_from_delivery_refused(
    assembly_inputs_ep0: dict[str, Any], assembly_inputs_ep1: dict[str, Any]
) -> None:
    """Join D4 shot witness unbound from delivery refused."""
    kwargs = _join_kwargs(assembly_inputs_ep1)
    other_shot_digest = sha256_hex(assembly_inputs_ep0["shot_plan_bytes"])
    kwargs["shot_plan_sha256"] = other_shot_digest
    # keep D1 satisfied by also forging the render manifest's own bound digest so only D4 trips
    broken_render = copy.deepcopy(kwargs["render_manifest"])
    broken_render["source"]["shot_plan_sha256"] = other_shot_digest
    kwargs["render_manifest"] = broken_render
    kwargs["render_manifest_sha256"] = sha256_hex(
        dumps_canonical(broken_render, "episode render manifest")
    )
    with pytest.raises(ValueError):
        _call(kwargs)


def test_join_e_composition_names_a_different_presentation_plan_refused(
    assembly_inputs_ep0: dict[str, Any], assembly_inputs_ep1: dict[str, Any]
) -> None:
    """Join e composition names a different presentation plan refused."""
    kwargs = _join_kwargs(assembly_inputs_ep1)
    broken_composition = copy.deepcopy(kwargs["audio_composition_manifest"])
    broken_composition["source"]["presentation_plan_sha256"] = sha256_hex(
        assembly_inputs_ep0["presentation_plan_bytes"]
    )
    kwargs["audio_composition_manifest"] = broken_composition
    kwargs["audio_composition_manifest_sha256"] = sha256_hex(
        dumps_canonical(broken_composition, "episode audio composition manifest")
    )
    with pytest.raises(ValueError):
        _call(kwargs)


def test_join_f_identity_triple_disagreement_refused(assembly_inputs_ep1: dict[str, Any]) -> None:
    """Join f identity triple disagreement refused."""
    kwargs = _join_kwargs(assembly_inputs_ep1)
    broken_presentation = copy.deepcopy(kwargs["presentation_plan"])
    broken_presentation["source"]["episode"] += 100
    kwargs["presentation_plan"] = broken_presentation
    kwargs["presentation_plan_sha256"] = sha256_hex(
        dumps_canonical(broken_presentation, "episode presentation plan")
    )
    with pytest.raises((ValueError, KeyError)):
        _call(kwargs)


def test_join_g_motion_time_mismatch_refused(assembly_inputs_ep1: dict[str, Any]) -> None:
    """Join g motion time mismatch refused."""
    kwargs = _join_kwargs(assembly_inputs_ep1)
    broken_render = copy.deepcopy(kwargs["render_manifest"])
    broken_render["source"]["motion_time_sha256"] = "1" * 64
    kwargs["render_manifest"] = broken_render
    kwargs["render_manifest_sha256"] = sha256_hex(
        dumps_canonical(broken_render, "episode render manifest")
    )
    with pytest.raises(ValueError):
        _call(kwargs)


def test_delivery_schema_version_disagreement_refused(assembly_inputs_ep1: dict[str, Any]) -> None:
    """Delivery schema version disagreement refused."""
    kwargs = _join_kwargs(assembly_inputs_ep1)
    broken_delivery = copy.deepcopy(kwargs["delivery_plan"])
    broken_delivery["schema_version"] = 999
    kwargs["delivery_plan"] = broken_delivery
    kwargs["delivery_plan_sha256"] = sha256_hex(
        dumps_canonical(broken_delivery, "episode narration delivery plan")
    )
    with pytest.raises(ValueError):
        _call(kwargs)


# ---------------------------------------------------------------------------
# require_render_frame_bytes -- B2, the whole-artifact frame binding
# ---------------------------------------------------------------------------


def _one_frame_record_and_bytes(inputs: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    from living_diorama.render_execution.render_execution_spec import FRAMES_DIRECTORY

    lookup = require_playback_lookup(inputs["render_manifest"])
    mapping = presentation_frame_map(inputs["presentation_plan"])
    semantic = mapping[0]
    record = lookup[semantic]
    payload = (inputs["render_dir"] / FRAMES_DIRECTORY / record["file"]).read_bytes()
    return record, payload


def test_require_render_frame_bytes_returns_the_identical_object(
    assembly_inputs_ep1: dict[str, Any],
) -> None:
    """Require render frame bytes returns the identical object."""
    record, payload = _one_frame_record_and_bytes(assembly_inputs_ep1)
    result = require_render_frame_bytes(record, payload, "test frame")
    assert result is payload


def test_require_render_frame_bytes_refuses_wrong_length(
    assembly_inputs_ep1: dict[str, Any],
) -> None:
    """Require render frame bytes refuses wrong length."""
    record, payload = _one_frame_record_and_bytes(assembly_inputs_ep1)
    with pytest.raises(ValueError):
        require_render_frame_bytes(record, payload + b"\x00", "test frame")


def test_require_render_frame_bytes_refuses_wrong_digest(
    assembly_inputs_ep1: dict[str, Any],
) -> None:
    """Require render frame bytes refuses wrong digest."""
    record, payload = _one_frame_record_and_bytes(assembly_inputs_ep1)
    mutated = bytearray(payload)
    mutated[-1] ^= 0xFF
    with pytest.raises(ValueError):
        require_render_frame_bytes(record, bytes(mutated), "test frame")


def test_require_render_frame_bytes_refuses_non_bytes(assembly_inputs_ep1: dict[str, Any]) -> None:
    """Require render frame bytes refuses non bytes."""
    record, _payload = _one_frame_record_and_bytes(assembly_inputs_ep1)
    with pytest.raises(TypeError):
        require_render_frame_bytes(record, "not bytes", "test frame")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# require_episode_audio_bytes -- C2, the whole-artifact WAV binding
# ---------------------------------------------------------------------------


def test_require_episode_audio_bytes_returns_the_identical_object(
    assembly_inputs_ep1: dict[str, Any],
) -> None:
    """Require episode audio bytes returns the identical object."""
    result = require_episode_audio_bytes(
        assembly_inputs_ep1["audio_composition_manifest"], assembly_inputs_ep1["wav_bytes"]
    )
    assert result is assembly_inputs_ep1["wav_bytes"]


def test_require_episode_audio_bytes_refuses_wrong_length(
    assembly_inputs_ep1: dict[str, Any],
) -> None:
    """Require episode audio bytes refuses wrong length."""
    with pytest.raises(ValueError):
        require_episode_audio_bytes(
            assembly_inputs_ep1["audio_composition_manifest"],
            assembly_inputs_ep1["wav_bytes"] + b"\x00",
        )


def test_require_episode_audio_bytes_refuses_wrong_digest(
    assembly_inputs_ep1: dict[str, Any],
) -> None:
    """Require episode audio bytes refuses wrong digest."""
    mutated = bytearray(assembly_inputs_ep1["wav_bytes"])
    mutated[-1] ^= 0xFF
    with pytest.raises(ValueError):
        require_episode_audio_bytes(
            assembly_inputs_ep1["audio_composition_manifest"], bytes(mutated)
        )


def test_require_episode_audio_bytes_refuses_non_bytes(assembly_inputs_ep1: dict[str, Any]) -> None:
    """Require episode audio bytes refuses non bytes."""
    with pytest.raises(TypeError):
        require_episode_audio_bytes(
            assembly_inputs_ep1["audio_composition_manifest"],
            "not bytes",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# require_assembly_matches_sources
# ---------------------------------------------------------------------------


def _real_manifest_document(inputs: dict[str, Any]) -> dict[str, Any]:
    from living_diorama.render_execution.render_execution_spec import FRAMES_DIRECTORY

    clock = require_clock_closure(
        inputs["presentation_plan"], inputs["render_manifest"], inputs["audio_composition_manifest"]
    )
    mapping = presentation_frame_map(inputs["presentation_plan"])
    lookup = require_playback_lookup(inputs["render_manifest"])
    frames = []
    for position, semantic in enumerate(mapping, start=1):
        record = lookup[semantic]
        payload = (inputs["render_dir"] / FRAMES_DIRECTORY / record["file"]).read_bytes()
        from living_diorama.media_assembly.media_assembly_spec import (
            presentation_frame_relative_path,
        )

        frames.append(
            {
                "bytes": len(payload),
                "file": presentation_frame_relative_path(position),
                "presentation_frame": position,
                "semantic_frame": semantic,
                "sha256": sha256_hex(payload),
            }
        )
    composition_audio = inputs["audio_composition_manifest"]["audio"]
    audio = {
        "audio_samples": composition_audio["audio_samples"],
        "bytes": composition_audio["bytes"],
        "channels": composition_audio["channels"],
        "file": "audio/episode_audio.wav",
        "sample_rate_hz": composition_audio["sample_rate_hz"],
        "sha256": composition_audio["sha256"],
    }
    return build_episode_media_assembly_manifest_document(
        render_manifest=inputs["render_manifest"],
        presentation_plan=inputs["presentation_plan"],
        audio_composition_manifest=inputs["audio_composition_manifest"],
        delivery_plan=inputs["delivery_plan"],
        shot_plan_sha256=sha256_hex(inputs["shot_plan_bytes"]),
        clock=clock,
        frames=tuple(frames),
        audio=audio,
    )


def test_require_assembly_matches_sources_passes_on_real_documents(
    assembly_inputs_ep1: dict[str, Any],
) -> None:
    """Require assembly matches sources passes on real documents."""
    manifest = _real_manifest_document(assembly_inputs_ep1)
    result = require_assembly_matches_sources(
        manifest,
        assembly_inputs_ep1["render_manifest"],
        assembly_inputs_ep1["presentation_plan"],
        assembly_inputs_ep1["audio_composition_manifest"],
        assembly_inputs_ep1["delivery_plan"],
    )
    assert result == manifest


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("render_manifest_sha256", "0" * 64),
        ("presentation_plan_sha256", "0" * 64),
        ("audio_composition_manifest_sha256", "0" * 64),
        ("delivery_plan_sha256", "0" * 64),
        ("shot_plan_sha256", "0" * 64),
        ("motion_time_sha256", "0" * 64),
        ("episode", 999),
        ("mode", "baseline"),
    ],
)
def test_require_assembly_matches_sources_detects_every_source_contradiction(
    assembly_inputs_ep1: dict[str, Any], field: str, value: Any
) -> None:
    """Require assembly matches sources detects every source contradiction."""
    manifest = _real_manifest_document(assembly_inputs_ep1)
    broken = copy.deepcopy(manifest)
    broken["source"][field] = value
    with pytest.raises(ValueError):
        require_assembly_matches_sources(
            broken,
            assembly_inputs_ep1["render_manifest"],
            assembly_inputs_ep1["presentation_plan"],
            assembly_inputs_ep1["audio_composition_manifest"],
            assembly_inputs_ep1["delivery_plan"],
        )


def test_require_assembly_matches_sources_detects_audio_block_contradiction(
    assembly_inputs_ep1: dict[str, Any],
) -> None:
    """Require assembly matches sources detects audio block contradiction."""
    manifest = _real_manifest_document(assembly_inputs_ep1)
    broken = copy.deepcopy(manifest)
    broken["audio"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        require_assembly_matches_sources(
            broken,
            assembly_inputs_ep1["render_manifest"],
            assembly_inputs_ep1["presentation_plan"],
            assembly_inputs_ep1["audio_composition_manifest"],
            assembly_inputs_ep1["delivery_plan"],
        )


# ---------------------------------------------------------------------------
# E2 / E5 -- join C2, the whole-artifact WAV binding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["sha256", "bytes"])
def test_e2_the_composition_manifests_audio_field_altered(
    assembly_inputs_ep1: dict[str, Any], field: str
) -> None:
    """E2 composition manifest audio.sha256 or audio.bytes altered."""
    forged = copy.deepcopy(assembly_inputs_ep1["audio_composition_manifest"])
    if field == "sha256":
        forged["audio"]["sha256"] = "0" * 64
    else:
        forged["audio"]["bytes"] = forged["audio"]["bytes"] + 1
    with pytest.raises((TypeError, ValueError)):
        require_episode_audio_bytes(forged, assembly_inputs_ep1["wav_bytes"])


def test_e5_a_wav_from_a_different_episode_substituted(
    assembly_inputs_ep0: dict[str, Any], assembly_inputs_ep1: dict[str, Any]
) -> None:
    """E5 a WAV from a different episode substituted.

    ep0's track is a real, structurally valid canonical WAV -- it is simply not the
    artifact this composition manifest names.
    """
    foreign = assembly_inputs_ep0["wav_bytes"]
    assert foreign != assembly_inputs_ep1["wav_bytes"]
    with pytest.raises(ValueError):
        require_episode_audio_bytes(assembly_inputs_ep1["audio_composition_manifest"], foreign)
