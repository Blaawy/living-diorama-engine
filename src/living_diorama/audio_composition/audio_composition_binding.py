"""Prove a copied source witness, and a composed manifest, tell the truth.

Three relationship claims are checked here, and each answers a different
question standalone validation cannot:

* :func:`require_voice_manifest_bytes` -- the copied witness inside a
  composition directory is the exact Phase 29 manifest the bound Phase 30
  plan names, by raw bytes, checked **before** the witness is ever parsed.
* :func:`require_voice_unit_bytes` -- the exact byte string about to supply
  one unit's composed PCM is the artifact identity the digest-bound witness
  records. This closes the time gap between "the directory was audited" and
  "these are the exact bytes Phase 31 is now consuming".
* :func:`require_composition_matches_plan_and_witness` -- the composition
  manifest contradicts neither the plan it composed nor the witness it
  consumed, while still being free to record what only a finished
  composition knows.

**Why a separate module.** Standalone validation and relationship validation
answer different questions and must not stand in for one another. Binding a
digest proves two documents were paired, never that the pairing was honest
about what it copied.
"""

from typing import cast

from living_diorama.audio_composition.audio_composition_schema_v1 import (
    JsonValue,
    validate_episode_audio_composition_manifest,
)
from living_diorama.audio_track.audio_track_schema_v1 import validate_episode_audio_track_plan
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.voice_execution.voice_execution_schema_v1 import validate_episode_voice_manifest


def _document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    return cast(dict[str, JsonValue], value)


def require_voice_manifest_bytes(
    audio_track_plan: object, voice_manifest_bytes: bytes
) -> dict[str, JsonValue]:
    """Refuse unless these exact bytes are the voice manifest the sealed plan binds.

    THE BOUND RAW-BYTE IDENTITY IS PROVED BEFORE THE WITNESS DOCUMENT IS
    PARSED. A witness whose raw SHA-256 does not equal the digest already
    bound by the verified Audio Track Plan is refused before its bytes
    reach the JSON parser. A byte string carrying the correct bound digest
    is then parsed, checked for canonical form -- which is what makes this
    raw-byte digest and the plan's own canonical-serialization digest the
    same number -- and validated under Phase 29's own contract.

    ``Path.resolve()`` and no re-serialization occur anywhere in this
    function: the digest is over the bytes as they are, not over a
    re-serialization of what they parse to, so a re-formatted or
    re-ordered copy of the same data is a different source.

    Args:
        audio_track_plan: The parsed, standalone-valid Episode Audio Track
            Plan V1 whose ``source.voice_manifest_sha256`` this witness must
            equal.
        voice_manifest_bytes: The copied witness file's exact bytes.

    Returns:
        The validated voice manifest.

    Raises:
        TypeError: If the bytes are not ``bytes``, or a value is of the
            wrong exact type.
        ValueError: If the raw-byte digest does not equal the plan's bound
            digest, if the bytes are not canonical form, or if they are not
            a valid Phase 29 document.
    """
    if type(voice_manifest_bytes) is not bytes:
        raise TypeError(
            f"voice manifest bytes must be bytes, got {type(voice_manifest_bytes).__name__}"
        )
    plan = validate_episode_audio_track_plan(audio_track_plan)
    source = _document(plan["source"], "audio track plan source")
    bound = source["voice_manifest_sha256"]

    # ---- no parsing has occurred up to this point ----
    observed = sha256_hex(voice_manifest_bytes)
    if observed != bound:
        raise ValueError(
            f"the copied voice manifest witness hashes to {observed!r}, but the sealed audio "
            f"track plan binds {bound!r}; the binding is over the file's exact bytes, so a "
            "re-formatted or re-ordered copy of the same data is a different source"
        )

    parsed = loads_canonical(voice_manifest_bytes, "episode voice manifest")
    canonical_form = dumps_canonical(parsed, "episode voice manifest")
    if voice_manifest_bytes != canonical_form:
        raise ValueError(
            "the copied voice manifest witness is not canonical bytes; the audio composition "
            "binds the digest of the documents it reads, so each file must be exactly what its "
            "writer emitted"
        )
    return validate_episode_voice_manifest(parsed)


def require_voice_unit_bytes(voice_unit: object, wav_bytes: bytes, description: str) -> bytes:
    """Refuse unless these exact bytes are the artifact the witness records.

    Whole-artifact provenance binding. It does not replace the Phase 29
    directory audit; it closes the time gap between "the directory was
    audited" and "these are the exact bytes Phase 31 is now consuming" by
    rebinding the exact byte string that will supply the composed PCM to
    the digest-bound witness record, at the read that produces it.

    Args:
        voice_unit: One ``voice_units`` record from the digest-bound,
            standalone-validated Phase 29 witness.
        wav_bytes: The source WAV file's exact bytes, as captured by the
            single read that will also supply the composed payload.
        description: What is being bound, used in error messages.

    Returns:
        ``wav_bytes``, unchanged and unnormalised -- the same value the
        caller passed, so the caller composes from what was proven.

    Raises:
        TypeError: If ``voice_unit`` is not a dict, or ``wav_bytes`` is not
            exactly ``bytes``.
        ValueError: If the byte length or the SHA-256 does not equal the
            witness record's own ``bytes`` / ``sha256``.
    """
    unit = _document(voice_unit, description)
    if type(wav_bytes) is not bytes:
        raise TypeError(f"{description} bytes must be bytes, got {type(wav_bytes).__name__}")

    expected_length = unit["bytes"]
    if len(wav_bytes) != expected_length:
        raise ValueError(
            f"{description} is {len(wav_bytes)} bytes, but the digest-bound voice manifest "
            f"records {expected_length}"
        )
    observed = sha256_hex(wav_bytes)
    expected_sha256 = unit["sha256"]
    if observed != expected_sha256:
        raise ValueError(
            f"{description} hashes to {observed!r}, but the digest-bound voice manifest records "
            f"{expected_sha256!r}"
        )
    return wav_bytes


def require_composition_matches_plan_and_witness(
    composition_manifest: object, audio_track_plan: object, voice_manifest: object
) -> dict[str, JsonValue]:
    """Refuse unless the composition manifest tells the truth about the plan and witness.

    A composition manifest binds its plan and its witness by digest, and
    standalone validation checks each binding is well-formed. But the
    manifest also *copies* most of the plan's source block, and restates
    every span's identity positionally -- a copy that was never compared to
    its original is an unchecked assertion.

    Args:
        composition_manifest: The parsed Episode Audio Composition Manifest.
        audio_track_plan: The parsed Episode Audio Track Plan it composed.
        voice_manifest: The parsed Episode Voice Manifest witness it
            consumed.

    Returns:
        The validated composition manifest.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: On any contradiction between the three documents.
    """
    manifest = validate_episode_audio_composition_manifest(composition_manifest)
    plan = validate_episode_audio_track_plan(audio_track_plan)
    witness = validate_episode_voice_manifest(voice_manifest)

    plan_source = _document(plan["source"], "audio track plan source")
    manifest_source = _document(manifest["source"], "audio composition manifest source")

    plan_digest = sha256_hex(dumps_canonical(plan, "audio track plan"))
    if manifest_source["audio_track_plan_sha256"] != plan_digest:
        raise ValueError(
            f"the composition manifest binds audio track plan "
            f"{manifest_source['audio_track_plan_sha256']!r}, but the offered plan hashes to "
            f"{plan_digest!r}; the manifest does not compose that document"
        )

    witness_digest = sha256_hex(dumps_canonical(witness, "voice manifest"))
    if manifest_source["voice_manifest_sha256"] != witness_digest:
        raise ValueError(
            f"the composition manifest binds voice manifest "
            f"{manifest_source['voice_manifest_sha256']!r}, but the offered witness hashes to "
            f"{witness_digest!r}; the manifest does not consume that document"
        )
    if plan_source["voice_manifest_sha256"] != witness_digest:
        raise ValueError(
            f"the audio track plan binds voice manifest {plan_source['voice_manifest_sha256']!r}"
            f", but the offered witness hashes to {witness_digest!r}; the plan and the witness "
            "are not the same execution's"
        )

    for field in (
        "episode",
        "mode",
        "previous_episode",
        "presentation_plan_sha256",
        "presentation_schema_version",
        "voice_manifest_schema_version",
    ):
        if manifest_source[field] != plan_source[field]:
            raise ValueError(
                f"the composition manifest declares {field} {manifest_source[field]!r}, but the "
                f"audio track plan it composes declares {plan_source[field]!r}"
            )

    speech = cast(list[dict[str, JsonValue]], plan["speech"])
    voice_units = cast(list[dict[str, JsonValue]], witness["voice_units"])
    spans = cast(list[dict[str, JsonValue]], manifest["spans"])
    if not (len(speech) == len(voice_units) == len(spans)):
        raise ValueError(
            f"the composition manifest carries {len(spans)} spans for a plan placing "
            f"{len(speech)} and a witness executing {len(voice_units)}; every unit is placed "
            "exactly once"
        )

    for position, (plan_span, unit, span) in enumerate(
        zip(speech, voice_units, spans, strict=True)
    ):
        label = f"composition manifest spans[{position}]"
        if span["speech_id"] != plan_span["speech_id"]:
            raise ValueError(
                f"{label} names speech {span['speech_id']!r}, but the audio track plan holds "
                f"{plan_span['speech_id']!r} at that position"
            )
        if span["voice_unit_id"] != plan_span["voice_unit_id"]:
            raise ValueError(
                f"{label} names voice unit {span['voice_unit_id']!r}, but the audio track plan "
                f"holds {plan_span['voice_unit_id']!r} at that position"
            )
        if span["voice_unit_id"] != unit["voice_unit_id"]:
            raise ValueError(
                f"{label} names voice unit {span['voice_unit_id']!r}, but the witness executes "
                f"{unit['voice_unit_id']!r} at that position"
            )
        if span["start_sample"] != plan_span["start_sample"]:
            raise ValueError(
                f"{label} declares start_sample {span['start_sample']!r}, but the audio track "
                f"plan's actual onset resolves to {plan_span['start_sample']!r}"
            )
        if span["speech_samples"] != plan_span["speech_samples"]:
            raise ValueError(
                f"{label} declares speech_samples {span['speech_samples']!r}, but the audio "
                f"track plan holds {plan_span['speech_samples']!r} at that position"
            )
        if span["speech_samples"] != unit["speech_samples"]:
            raise ValueError(
                f"{label} declares speech_samples {span['speech_samples']!r}, but the witness "
                f"measured {unit['speech_samples']!r} for that unit"
            )

    audio = _document(manifest["audio"], "audio composition manifest audio")
    clock = _document(plan["clock"], "audio track plan clock")
    if audio["audio_samples"] != clock["audio_samples_total"]:
        raise ValueError(
            f"the composed track measures {audio['audio_samples']!r} samples, but the sealed "
            f"audio track plan's audio_samples_total is {clock['audio_samples_total']!r}"
        )

    return manifest


__all__ = [
    "require_composition_matches_plan_and_witness",
    "require_voice_manifest_bytes",
    "require_voice_unit_bytes",
]
