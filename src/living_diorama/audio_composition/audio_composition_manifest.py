"""Turn a completed composition's measured facts into an Episode Audio Composition Manifest.

This module is pure and knows nothing about the filesystem. It is handed
what a composition measured -- an artifact's own facts, plus a per-span
digest -- and turns that into the document that proves what exists. Keeping
it here means the manifest's rules can be attacked in ordinary tests, and
means the publisher cannot quietly invent a completeness claim while
holding a partial result.

The plan's own ``source.voice_manifest_sha256`` is restated here, never
independently recomputed: the plan is already the proven tie between itself
and the audited Phase 29 witness, by the time this module is ever called,
and restating a digest it does not itself check would be a copy, not proof.
"""

from typing import cast

from living_diorama.audio_composition.audio_composition_schema_v1 import (
    JsonValue,
    validate_episode_audio_composition_manifest,
)
from living_diorama.audio_composition.audio_composition_spec import (
    AUDIO_COMPOSITION_MANIFEST_FORMAT,
    AUDIO_COMPOSITION_MANIFEST_SCHEMA_VERSION,
    AUDIO_RESULT_FIELDS,
    SPAN_RESULT_FIELDS,
    episode_audio_relative_path,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex


def _document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    return cast(dict[str, JsonValue], value)


def build_episode_audio_composition_manifest_document(
    *,
    audio_track_plan: object,
    audio: dict[str, object],
    spans: dict[int, dict[str, object]],
) -> dict[str, JsonValue]:
    """Return the manifest for one completed audio composition.

    Args:
        audio_track_plan: The parsed, gate-verified Phase 30 audio track
            plan this composition places. Its own digest is bound into the
            manifest, and its own ``source.voice_manifest_sha256`` is
            restated -- never independently recomputed here -- because the
            plan is already the proven tie between itself and the audited
            Phase 29 witness.
        audio: What the composition measured about the produced track.
            Exactly the five ``AUDIO_RESULT_FIELDS``.
        spans: What the composition measured about each placed span, keyed
            by 1-based plan position. Each entry carries exactly the one
            ``SPAN_RESULT_FIELDS`` field, ``pcm_sha256``.

    Returns:
        The complete, validated manifest document.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If a placed span has no result, a result names a
            position the plan never placed, a result's keys are not
            exactly the expected fields, or the plan itself is invalid.
    """
    plan = _document(audio_track_plan, "audio track plan")
    plan_source = _document(plan["source"], "audio track plan source")
    plan_digest = sha256_hex(dumps_canonical(plan, "audio track plan"))

    if type(audio) is not dict:
        raise TypeError(f"audio result must be a dict, got {type(audio).__name__}")
    audio_keys = set(audio.keys())
    expected_audio_keys = set(AUDIO_RESULT_FIELDS)
    if audio_keys != expected_audio_keys:
        missing = sorted(expected_audio_keys - audio_keys)
        unexpected = sorted(audio_keys - expected_audio_keys)
        raise ValueError(
            f"audio result must carry exactly {sorted(expected_audio_keys)}, missing {missing}, "
            f"unexpected {unexpected}"
        )

    if type(spans) is not dict:
        raise TypeError(f"span results must be a dict, got {type(spans).__name__}")

    plan_speech = cast(list[dict[str, JsonValue]], plan["speech"])
    expected_positions = set(range(1, len(plan_speech) + 1))
    extra = sorted(set(spans) - expected_positions)
    if extra:
        raise ValueError(
            f"span results name positions {extra} that this plan never placed; a composition "
            "manifest describes the placement it composed and nothing found lying beside it"
        )

    speech_spans: list[JsonValue] = []
    speech_samples_total = 0
    for position, plan_span in enumerate(plan_speech, start=1):
        result = spans.get(position)
        if result is None:
            raise ValueError(
                f"speech span at position {position} was placed but has no composition result; "
                "a manifest is written only for a composition that finished every span, never "
                "to record how far one got"
            )
        if type(result) is not dict:
            raise TypeError(f"span {position} result must be a dict, got {type(result).__name__}")
        result_keys = set(result.keys())
        expected_span_keys = set(SPAN_RESULT_FIELDS)
        if result_keys != expected_span_keys:
            missing = sorted(expected_span_keys - result_keys)
            unexpected = sorted(result_keys - expected_span_keys)
            raise ValueError(
                f"span {position} result must carry exactly {sorted(expected_span_keys)}, "
                f"missing {missing}, unexpected {unexpected}"
            )
        pcm_sha256 = result.get("pcm_sha256")
        if type(pcm_sha256) is not str:
            raise TypeError(f"span {position} result pcm_sha256 must be a str, got {pcm_sha256!r}")

        speech_samples = cast(int, plan_span["speech_samples"])
        speech_samples_total += speech_samples
        speech_spans.append(
            {
                "pcm_sha256": pcm_sha256,
                "speech_id": plan_span["speech_id"],
                "speech_samples": speech_samples,
                "start_sample": plan_span["start_sample"],
                "voice_unit_id": plan_span["voice_unit_id"],
            }
        )

    source: dict[str, JsonValue] = {
        "audio_track_plan_sha256": plan_digest,
        "episode": plan_source["episode"],
        "mode": plan_source["mode"],
        "presentation_plan_sha256": plan_source["presentation_plan_sha256"],
        "presentation_schema_version": plan_source["presentation_schema_version"],
        "previous_episode": plan_source["previous_episode"],
        "voice_manifest_sha256": plan_source["voice_manifest_sha256"],
        "voice_manifest_schema_version": plan_source["voice_manifest_schema_version"],
    }

    audio_document: dict[str, JsonValue] = {
        **cast(dict[str, JsonValue], audio),
        "file": episode_audio_relative_path(),
    }

    document: dict[str, JsonValue] = {
        "audio": audio_document,
        "completeness": {
            "complete": len(speech_spans) == len(plan_speech),
            "silence_samples_total": cast(int, audio["audio_samples"]) - speech_samples_total,
            "speech_spans_composed": len(speech_spans),
            "speech_spans_expected": len(plan_speech),
        },
        "format": AUDIO_COMPOSITION_MANIFEST_FORMAT,
        "schema_version": AUDIO_COMPOSITION_MANIFEST_SCHEMA_VERSION,
        "source": source,
        "spans": speech_spans,
    }
    return validate_episode_audio_composition_manifest(document)


def build_episode_audio_composition_manifest_bytes(
    *,
    audio_track_plan: object,
    audio: dict[str, object],
    spans: dict[int, dict[str, object]],
) -> bytes:
    """Return the canonical bytes of one episode audio composition manifest."""
    return dumps_canonical(
        build_episode_audio_composition_manifest_document(
            audio_track_plan=audio_track_plan, audio=audio, spans=spans
        ),
        "episode audio composition manifest",
    )


__all__ = [
    "build_episode_audio_composition_manifest_bytes",
    "build_episode_audio_composition_manifest_document",
]
