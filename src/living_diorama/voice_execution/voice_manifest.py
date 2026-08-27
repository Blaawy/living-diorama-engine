"""Turn recorded voice execution results into an Episode Voice Manifest.

This module is pure and knows nothing about Kokoro, Torch, spaCy, or files.
It is handed what an execution observed -- a file, a byte count, a digest and
a measured sample count per unit, plus the environment that produced them --
and turns that into the document that proves what exists. Keeping it here
means the manifest's rules can be attacked in ordinary tests, and means the
executor cannot quietly invent a completeness claim while holding a partial
result.

The manifest is never built at all for an episode holding a unit whose
measured ``speech_samples`` overflows its own ``capacity_samples``: FIT is
proven here, once, before any document exists that could otherwise assert an
episode complete while a unit inside it overflowed. ``complete`` means all of
it: every planned unit synthesized, every one present in the records.
"""

from typing import cast

from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.voice.voice_schema_v1 import validate_episode_voice_plan
from living_diorama.voice_execution.voice_execution_schema_v1 import (
    JsonValue,
    validate_episode_voice_manifest,
)
from living_diorama.voice_execution.voice_execution_spec import (
    SPEECH_DIRECTORY,
    UNIT_RESULT_FIELDS,
    VOICE_MANIFEST_FORMAT,
    VOICE_MANIFEST_SCHEMA_VERSION,
    unit_audio_filename,
)


def build_episode_voice_manifest_document(
    *,
    voice_plan: object,
    results: dict[int, dict[str, object]],
    environment: dict[str, str],
) -> dict[str, JsonValue]:
    """Return the manifest for a completed voice execution.

    Args:
        voice_plan: The parsed Phase 28 voice plan the execution was run
            from. It is re-validated here and its canonical digest is bound
            into the manifest, so a manifest can never float free of its
            plan.
        results: What the execution observed, keyed by 1-based unit
            position. Each entry carries exactly the three
            ``UNIT_RESULT_FIELDS``: ``bytes``, ``sha256``, ``speech_samples``.
        environment: The execution environment's seven reported strings.

    Returns:
        The complete, validated manifest document.

    Raises:
        TypeError: If a value is of the wrong exact type, including a
            per-unit result that is not itself a dict.
        ValueError: If a planned unit has no result, a result names a
            position the plan never planned, a result's keys are not
            exactly ``UNIT_RESULT_FIELDS``, any unit's measured speech
            overflows its own capacity, or the plan itself is invalid.
    """
    plan = validate_episode_voice_plan(voice_plan)
    plan_digest = sha256_hex(dumps_canonical(plan, "episode voice plan"))
    planned = cast(list[dict[str, JsonValue]], plan["voice_units"])

    if type(results) is not dict:
        raise TypeError(f"voice execution results must be a dict, got {type(results).__name__}")
    if type(environment) is not dict:
        raise TypeError(
            f"voice execution environment must be a dict, got {type(environment).__name__}"
        )

    expected_positions = set(range(1, len(planned) + 1))
    extra = sorted(set(results) - expected_positions)
    if extra:
        raise ValueError(
            f"voice execution results name positions {extra} that this plan never planned; a "
            "manifest describes the execution it planned and nothing found lying beside it"
        )

    voice_units: list[JsonValue] = []
    speech_samples_total = 0
    for position, entry in enumerate(planned, start=1):
        result = results.get(position)
        if result is None:
            raise ValueError(
                f"voice unit at position {position} was planned but has no execution result; a "
                "manifest is written only for an execution that finished every unit, never to "
                "record how far one got"
            )
        if type(result) is not dict:
            raise TypeError(
                f"voice unit {position} result must be a dict, got {type(result).__name__}"
            )
        result_keys = set(result.keys())
        expected_keys = set(UNIT_RESULT_FIELDS)
        if result_keys != expected_keys:
            missing = sorted(expected_keys - result_keys)
            unexpected = sorted(result_keys - expected_keys)
            raise ValueError(
                f"voice unit {position} result must carry exactly {sorted(expected_keys)}, "
                f"missing {missing}, unexpected {unexpected}"
            )
        size = result.get("bytes")
        digest = result.get("sha256")
        speech_samples = result.get("speech_samples")
        if isinstance(size, bool) or not isinstance(size, int):
            raise TypeError(f"unit {position} result bytes must be an int, got {size!r}")
        if type(digest) is not str:
            raise TypeError(f"unit {position} result sha256 must be a str, got {digest!r}")
        if isinstance(speech_samples, bool) or not isinstance(speech_samples, int):
            raise TypeError(
                f"unit {position} result speech_samples must be an int, got {speech_samples!r}"
            )
        capacity = cast(int, entry["capacity_samples"])
        if speech_samples > capacity:
            raise ValueError(
                f"unit {position} measured {speech_samples} samples, beyond its own "
                f"{capacity}-sample capacity; a manifest is never written for an episode "
                "holding an unfit unit"
            )
        speech_samples_total += speech_samples
        voice_units.append(
            {
                **entry,
                "file": f"{SPEECH_DIRECTORY}/{unit_audio_filename(position)}",
                "bytes": size,
                "sha256": digest,
                "speech_samples": speech_samples,
            }
        )

    source = dict(cast(dict[str, JsonValue], plan["source"]))
    source["voice_plan_sha256"] = plan_digest

    document: dict[str, JsonValue] = {
        "format": VOICE_MANIFEST_FORMAT,
        "schema_version": VOICE_MANIFEST_SCHEMA_VERSION,
        "source": source,
        "environment": {key: str(value) for key, value in sorted(environment.items())},
        "voice_units": voice_units,
        "completeness": {
            "voice_units_expected": len(planned),
            "voice_units_synthesized": len(voice_units),
            "speech_samples_total": speech_samples_total,
            "complete": len(voice_units) == len(planned),
        },
    }
    return validate_episode_voice_manifest(document)


def build_episode_voice_manifest_bytes(
    *,
    voice_plan: object,
    results: dict[int, dict[str, object]],
    environment: dict[str, str],
) -> bytes:
    """Return the canonical bytes of one episode voice manifest."""
    return dumps_canonical(
        build_episode_voice_manifest_document(
            voice_plan=voice_plan, results=results, environment=environment
        ),
        "episode voice manifest",
    )
