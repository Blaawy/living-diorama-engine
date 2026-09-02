"""Turn a completed assembly's measured facts into an Episode Media Assembly Manifest.

This module is pure and knows nothing about the filesystem. It is handed the four bound
documents this assembly read, the shot plan's own captured digest, the resolved integer
clock, and what the assembly measured about the frames and the audio it copied, and turns
that into the document that proves what exists. Keeping it here means the manifest's rules
can be attacked in ordinary tests, and means the publisher cannot quietly invent a
completeness claim while holding a partial result.

``shot_plan_sha256`` is restated here, never independently recomputed: the shot plan
document is never parsed by Phase 33 anywhere, so there is no document to hash it from --
only the digest already captured, and already proven by
:func:`living_diorama.media_assembly.media_assembly_binding.require_assembly_sources_join`.

The presentation plan is validated through the profile dispatcher
(:func:`living_diorama.presentation.presentation_schema_v2.validate_presentation_plan`), so
a V2 plan binds into a manifest exactly as a V1 plan does; the manifest records the plan's
own (unchanged) ``schema_version`` either way.

The render manifest is validated through the same keyword-only ``camera_profile`` the
render phase itself uses: the caller decides the profile (V1 default, or ``"v2"`` for a
render produced with ``camera_profile="v2"`` carrying ``movement_catalogue_sha256``) and
passes it explicitly -- this module never inspects the document to guess.
"""

from typing import cast

from living_diorama.audio_composition.audio_composition_schema_v1 import (
    validate_episode_audio_composition_manifest,
)
from living_diorama.media_assembly.media_assembly_schema_v1 import (
    AUDIO_KEYS,
    FRAME_KEYS,
    JsonValue,
    validate_episode_media_assembly_manifest,
)
from living_diorama.media_assembly.media_assembly_spec import (
    MEDIA_ASSEMBLY_MANIFEST_FORMAT,
    MEDIA_ASSEMBLY_MANIFEST_SCHEMA_VERSION,
)
from living_diorama.narration_delivery.delivery_schema_v1 import (
    validate_episode_narration_delivery_plan,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.presentation.presentation_schema_v2 import validate_presentation_plan
from living_diorama.render_execution.render_execution_schema_v1 import (
    validate_episode_render_manifest,
)


def _document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    return cast(dict[str, JsonValue], value)


def build_episode_media_assembly_manifest_document(
    *,
    render_manifest: object,
    presentation_plan: object,
    audio_composition_manifest: object,
    delivery_plan: object,
    shot_plan_sha256: str,
    clock: dict[str, int],
    frames: tuple[dict[str, object], ...],
    audio: dict[str, object],
    camera_profile: str = "v1",
) -> dict[str, JsonValue]:
    """Return the manifest for one completed media assembly.

    Args:
        render_manifest: The parsed, gate-verified Phase 23 render manifest this assembly
            bound. Its own digest is bound into the manifest.
        presentation_plan: The parsed, gate-verified Phase 27 presentation plan (V1 or V2)
            this assembly bound.
        audio_composition_manifest: The parsed, gate-verified Phase 31 audio composition
            manifest this assembly bound.
        delivery_plan: The parsed, gate-verified Phase 25 delivery witness this assembly
            bound.
        shot_plan_sha256: The digest captured from the Phase 22 shot witness's own bytes.
        clock: The eight-key resolved clock block from
            :func:`living_diorama.media_assembly.media_assembly_mapping.require_clock_closure`.
        frames: One record per physical presentation frame, in presentation order. Each
            record must carry exactly the five ``FRAME_KEYS``.
        audio: What the assembly measured about the carried track. Exactly the six
            ``AUDIO_KEYS``.
        camera_profile: ``"v1"`` (default) or ``"v2"``, threaded into the render manifest
            validator so a V2 manifest carrying movement-camera identities and the
            movement-catalogue binding validates under the same profile it was built under.

    Returns:
        The complete, validated manifest document.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If a frame record's keys are not exactly ``FRAME_KEYS``, if the audio
            result's keys are not exactly ``AUDIO_KEYS``, or if any bound document is
            invalid.
    """
    render = validate_episode_render_manifest(render_manifest, camera_profile=camera_profile)
    presentation = validate_presentation_plan(presentation_plan)
    composition = validate_episode_audio_composition_manifest(audio_composition_manifest)
    delivery = validate_episode_narration_delivery_plan(delivery_plan)

    render_source = _document(render["source"], "render manifest source")

    render_digest = sha256_hex(dumps_canonical(render, "render manifest"))
    presentation_digest = sha256_hex(dumps_canonical(presentation, "presentation plan"))
    composition_digest = sha256_hex(dumps_canonical(composition, "audio composition manifest"))
    delivery_digest = sha256_hex(dumps_canonical(delivery, "narration delivery plan"))

    source: dict[str, JsonValue] = {
        "audio_composition_manifest_sha256": composition_digest,
        "audio_composition_schema_version": composition["schema_version"],
        "delivery_plan_sha256": delivery_digest,
        "episode": render_source["episode"],
        "mode": render_source["mode"],
        "motion_time_sha256": render_source["motion_time_sha256"],
        "presentation_plan_sha256": presentation_digest,
        "presentation_schema_version": presentation["schema_version"],
        "previous_episode": render_source["previous_episode"],
        "render_manifest_sha256": render_digest,
        "render_manifest_schema_version": render["schema_version"],
        "shot_plan_sha256": shot_plan_sha256,
    }

    if type(clock) is not dict:
        raise TypeError(f"clock must be a dict, got {type(clock).__name__}")
    clock_document: dict[str, JsonValue] = {
        key: cast(JsonValue, clock[key]) for key in sorted(clock)
    }

    if type(frames) is not tuple:
        raise TypeError(f"frames must be a tuple, got {type(frames).__name__}")
    frame_documents: list[JsonValue] = []
    for position, frame in enumerate(frames):
        if type(frame) is not dict:
            raise TypeError(f"frames[{position}] must be a dict, got {type(frame).__name__}")
        frame_keys = set(frame.keys())
        if frame_keys != FRAME_KEYS:
            missing = sorted(FRAME_KEYS - frame_keys)
            unexpected = sorted(frame_keys - FRAME_KEYS)
            raise ValueError(
                f"frames[{position}] must carry exactly {sorted(FRAME_KEYS)}, missing "
                f"{missing}, unexpected {unexpected}"
            )
        frame_documents.append(cast(JsonValue, dict(frame)))

    if type(audio) is not dict:
        raise TypeError(f"audio result must be a dict, got {type(audio).__name__}")
    audio_keys = set(audio.keys())
    if audio_keys != AUDIO_KEYS:
        missing = sorted(AUDIO_KEYS - audio_keys)
        unexpected = sorted(audio_keys - AUDIO_KEYS)
        raise ValueError(
            f"audio result must carry exactly {sorted(AUDIO_KEYS)}, missing {missing}, "
            f"unexpected {unexpected}"
        )
    audio_document: dict[str, JsonValue] = dict(cast(dict[str, JsonValue], audio))

    presentation_frames_expected = clock["presentation_frames_total"]
    unique_semantic = len({cast(int, frame["semantic_frame"]) for frame in frames})
    completeness: dict[str, JsonValue] = {
        "complete": len(frame_documents) == presentation_frames_expected,
        "presentation_frames_assembled": len(frame_documents),
        "presentation_frames_expected": presentation_frames_expected,
        "unique_semantic_frames_used": unique_semantic,
    }

    document: dict[str, JsonValue] = {
        "audio": audio_document,
        "clock": clock_document,
        "completeness": completeness,
        "format": MEDIA_ASSEMBLY_MANIFEST_FORMAT,
        "frames": frame_documents,
        "schema_version": MEDIA_ASSEMBLY_MANIFEST_SCHEMA_VERSION,
        "source": source,
    }
    return validate_episode_media_assembly_manifest(document)


def build_episode_media_assembly_manifest_bytes(
    *,
    render_manifest: object,
    presentation_plan: object,
    audio_composition_manifest: object,
    delivery_plan: object,
    shot_plan_sha256: str,
    clock: dict[str, int],
    frames: tuple[dict[str, object], ...],
    audio: dict[str, object],
    camera_profile: str = "v1",
) -> bytes:
    """Return the canonical bytes of one episode media assembly manifest."""
    return dumps_canonical(
        build_episode_media_assembly_manifest_document(
            render_manifest=render_manifest,
            presentation_plan=presentation_plan,
            audio_composition_manifest=audio_composition_manifest,
            delivery_plan=delivery_plan,
            shot_plan_sha256=shot_plan_sha256,
            clock=clock,
            frames=frames,
            audio=audio,
            camera_profile=camera_profile,
        ),
        "episode media assembly manifest",
    )


__all__ = [
    "build_episode_media_assembly_manifest_bytes",
    "build_episode_media_assembly_manifest_document",
]
