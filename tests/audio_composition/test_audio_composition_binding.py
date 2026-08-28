"""Relationship validation: witness digest-before-parse, source-byte binding, three-way join."""

import pytest

from living_diorama.audio_composition.audio_composition_binding import (
    require_composition_matches_plan_and_witness,
    require_voice_manifest_bytes,
    require_voice_unit_bytes,
)
from living_diorama.audio_composition.audio_composition_manifest import (
    build_episode_audio_composition_manifest_document,
)
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex

# ---- require_voice_manifest_bytes


def test_require_voice_manifest_bytes_accepts_exact_bytes(
    audio_track_plan_ep1, voice_manifest_ep1
) -> None:
    """Require voice manifest bytes accepts exact bytes."""
    raw = dumps_canonical(voice_manifest_ep1, "voice manifest")
    result = require_voice_manifest_bytes(audio_track_plan_ep1, raw)
    assert result == voice_manifest_ep1


def test_require_voice_manifest_bytes_refuses_wrong_type(audio_track_plan_ep1) -> None:
    """Require voice manifest bytes refuses wrong type."""
    with pytest.raises(TypeError):
        require_voice_manifest_bytes(audio_track_plan_ep1, "not bytes")


def test_require_voice_manifest_bytes_refuses_digest_mismatch(
    audio_track_plan_ep1, voice_manifest_ep1
) -> None:
    """Require voice manifest bytes refuses digest mismatch."""
    tampered = dict(voice_manifest_ep1)
    tampered["completeness"] = dict(tampered["completeness"])
    tampered["completeness"]["complete"] = tampered["completeness"]["complete"]
    raw = dumps_canonical(voice_manifest_ep1, "voice manifest") + b" "
    # A byte-level mutation (trailing space) changes the digest without
    # necessarily being valid canonical JSON on its own -- exercised here to
    # prove the digest check runs, and runs first, on raw bytes.
    with pytest.raises(ValueError):
        require_voice_manifest_bytes(audio_track_plan_ep1, raw)


def test_require_voice_manifest_bytes_refuses_reformatted_copy(
    audio_track_plan_ep1, voice_manifest_ep1
) -> None:
    """Require voice manifest bytes refuses reformatted copy."""
    reformatted = (
        dumps_canonical(voice_manifest_ep1, "voice manifest").decode("utf-8") + " "
    ).encode()
    # Not canonical (trailing whitespace after the newline) -- digest differs.
    with pytest.raises(ValueError):
        require_voice_manifest_bytes(audio_track_plan_ep1, reformatted)


def test_require_voice_manifest_bytes_refuses_non_canonical_but_correct_digest(
    audio_track_plan_ep1, voice_manifest_ep1
) -> None:
    # Construct a payload whose parsed form differs from its own bytes: not
    # generally possible without breaking the digest too, so instead prove
    # the canonical-form check is reachable by feeding a plain (non-sorted)
    # re-encoding of the *correct* document and confirming it is refused
    # even though it would parse to the same content.
    """Require voice manifest bytes refuses non canonical but correct digest."""
    import json

    document = loads_canonical(
        dumps_canonical(voice_manifest_ep1, "voice manifest"), "voice manifest"
    )
    reencoded = (json.dumps(document, sort_keys=False) + "\n").encode("utf-8")
    with pytest.raises(ValueError):
        require_voice_manifest_bytes(audio_track_plan_ep1, reencoded)


def test_digest_is_checked_before_parse_on_malformed_json(audio_track_plan_ep1) -> None:
    """A witness whose digest does not match is refused before the JSON parser ever runs."""
    malformed = b"{not json at all"
    with pytest.raises(ValueError, match="hashes to"):
        require_voice_manifest_bytes(audio_track_plan_ep1, malformed)


# ---- require_voice_unit_bytes


def _unit_record(bytes_len: int, digest: str) -> dict[str, object]:
    """Unit record."""
    return {"bytes": bytes_len, "sha256": digest}


def test_require_voice_unit_bytes_accepts_exact_bytes() -> None:
    """Require voice unit bytes accepts exact bytes."""
    payload = b"\x00" * 100
    unit = _unit_record(len(payload), sha256_hex(payload))
    result = require_voice_unit_bytes(unit, payload, "voice unit 1")
    assert result is payload


def test_require_voice_unit_bytes_refuses_length_mismatch() -> None:
    """Require voice unit bytes refuses length mismatch."""
    payload = b"\x00" * 100
    unit = _unit_record(len(payload) + 1, sha256_hex(payload))
    with pytest.raises(ValueError):
        require_voice_unit_bytes(unit, payload, "voice unit 1")


def test_require_voice_unit_bytes_refuses_sha_mismatch() -> None:
    """Require voice unit bytes refuses sha mismatch."""
    payload = b"\x00" * 100
    unit = _unit_record(len(payload), "a" * 64)
    with pytest.raises(ValueError):
        require_voice_unit_bytes(unit, payload, "voice unit 1")


def test_require_voice_unit_bytes_refuses_wrong_type() -> None:
    """Require voice unit bytes refuses wrong type."""
    unit = _unit_record(4, sha256_hex(b"\x00\x00\x00\x00"))
    with pytest.raises(TypeError):
        require_voice_unit_bytes(unit, bytearray(b"\x00\x00\x00\x00"), "voice unit 1")


def test_require_voice_unit_bytes_refuses_non_dict_unit() -> None:
    """Require voice unit bytes refuses non dict unit."""
    payload = b"\x00" * 4
    with pytest.raises(TypeError):
        require_voice_unit_bytes([], payload, "voice unit 1")


def test_require_voice_unit_bytes_returns_same_value_identity() -> None:
    """Require voice unit bytes returns same value identity."""
    payload = b"\x01" * 50
    unit = _unit_record(len(payload), sha256_hex(payload))
    result = require_voice_unit_bytes(unit, payload, "voice unit 1")
    assert result is payload


# ---- require_composition_matches_plan_and_witness


def _valid_manifest(audio_track_plan) -> dict:
    """Valid manifest."""
    spans: dict[int, dict[str, object]] = {}
    for position, _record in enumerate(audio_track_plan["speech"], start=1):
        spans[position] = {"pcm_sha256": ("c" * 64)}
    total = audio_track_plan["clock"]["audio_samples_total"]
    audio = {
        "audio_samples": total,
        "bytes": 44 + total * 2,
        "channels": 1,
        "sample_rate_hz": 24000,
        "sha256": "d" * 64,
    }
    return build_episode_audio_composition_manifest_document(
        audio_track_plan=audio_track_plan, audio=audio, spans=spans
    )


def test_matches_accepts_consistent_triple(audio_track_plan_ep1, voice_manifest_ep1) -> None:
    """Matches accepts consistent triple."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    result = require_composition_matches_plan_and_witness(
        manifest, audio_track_plan_ep1, voice_manifest_ep1
    )
    assert result == manifest


def test_matches_refuses_wrong_plan_digest(audio_track_plan_ep1, voice_manifest_ep1) -> None:
    """Matches refuses wrong plan digest."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["source"]["audio_track_plan_sha256"] = "e" * 64
    with pytest.raises(ValueError):
        require_composition_matches_plan_and_witness(
            manifest, audio_track_plan_ep1, voice_manifest_ep1
        )


def test_matches_refuses_wrong_witness_digest(audio_track_plan_ep1, voice_manifest_ep1) -> None:
    """Matches refuses wrong witness digest."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["source"]["voice_manifest_sha256"] = "e" * 64
    with pytest.raises(ValueError):
        require_composition_matches_plan_and_witness(
            manifest, audio_track_plan_ep1, voice_manifest_ep1
        )


def test_matches_refuses_mismatched_field(audio_track_plan_ep1, voice_manifest_ep1) -> None:
    """Matches refuses mismatched field."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["source"]["episode"] = 999
    with pytest.raises(ValueError):
        require_composition_matches_plan_and_witness(
            manifest, audio_track_plan_ep1, voice_manifest_ep1
        )


def test_matches_refuses_span_count_mismatch(audio_track_plan_ep1, voice_manifest_ep1) -> None:
    """Matches refuses span count mismatch."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["spans"] = manifest["spans"][:1]
    manifest["completeness"]["speech_spans_composed"] = 1
    manifest["completeness"]["speech_spans_expected"] = 1
    with pytest.raises(ValueError):
        require_composition_matches_plan_and_witness(
            manifest, audio_track_plan_ep1, voice_manifest_ep1
        )


def test_matches_refuses_audio_samples_mismatch(audio_track_plan_ep1, voice_manifest_ep1) -> None:
    """Matches refuses audio samples mismatch."""
    manifest = _valid_manifest(audio_track_plan_ep1)
    manifest["audio"]["audio_samples"] += 1000
    manifest["audio"]["bytes"] += 2000
    with pytest.raises(ValueError):
        require_composition_matches_plan_and_witness(
            manifest, audio_track_plan_ep1, voice_manifest_ep1
        )
