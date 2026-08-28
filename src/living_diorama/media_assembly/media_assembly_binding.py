"""Prove a captured artifact, and a produced assembly manifest, tell the truth.

Four relationship claims are checked here, and each answers a different question standalone
validation cannot:

* :func:`require_render_frame_bytes` -- the exact byte string about to become one physical
  presentation frame is the artifact identity the digest-bound render manifest record
  names.
* :func:`require_episode_audio_bytes` -- the exact byte string about to be carried as the
  episode's one audio track is the artifact identity the digest-bound composition manifest
  names.
* :func:`require_assembly_sources_join` -- the four bound documents this assembly reads --
  the render manifest, the presentation plan, the audio composition manifest and the
  delivery witness -- name each other correctly: the presentation plan the composition was
  built from, the shot plan the render was directed by and the shot plan the delivery
  schedule was timed against are the same document, and the pinned motion-time digest
  agrees between the render manifest and the presentation plan.
* :func:`require_assembly_matches_sources` -- the produced assembly manifest contradicts
  none of the four documents it was built from, while still being free to record what only
  a finished assembly knows.

**Why a separate module.** Standalone validation and relationship validation answer
different questions and must not stand in for one another. Binding a digest proves two
documents were paired, never that the pairing was honest about what it copied.
"""

from typing import cast

from living_diorama.audio_composition.audio_composition_schema_v1 import (
    validate_episode_audio_composition_manifest,
)
from living_diorama.media_assembly.media_assembly_schema_v1 import (
    JsonValue,
    validate_episode_media_assembly_manifest,
)
from living_diorama.narration_delivery.delivery_schema_v1 import (
    validate_episode_narration_delivery_plan,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.presentation.presentation_schema_v1 import validate_episode_presentation_plan
from living_diorama.render_execution.render_execution_schema_v1 import (
    validate_episode_render_manifest,
)


def _document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    return cast(dict[str, JsonValue], value)


def require_render_frame_bytes(frame_record: object, png_bytes: bytes, description: str) -> bytes:
    """Refuse unless these exact bytes are the render frame the digest-bound record names.

    Whole-artifact provenance binding. It closes the time gap between "the render manifest
    was validated" and "these are the exact bytes this assembly is now copying" by
    rebinding the exact byte string that will supply every presentation-position copy to
    the digest-bound manifest record, at the single read that produces it.

    Args:
        frame_record: One ``frames`` record from the digest-bound, standalone-validated
            Phase 23 render manifest.
        png_bytes: The source PNG file's exact bytes, as captured by the single read that
            will also supply every presentation-position copy.
        description: What is being bound, used in error messages.

    Returns:
        ``png_bytes``, unchanged and unnormalised -- the same value the caller passed, so
        the caller writes what was proven.

    Raises:
        TypeError: If ``frame_record`` is not a dict, or ``png_bytes`` is not exactly
            ``bytes``.
        ValueError: If the byte length or the SHA-256 does not equal the record's own
            ``bytes`` / ``sha256``.
    """
    record = _document(frame_record, description)
    if type(png_bytes) is not bytes:
        raise TypeError(f"{description} bytes must be bytes, got {type(png_bytes).__name__}")

    expected_length = record["bytes"]
    if len(png_bytes) != expected_length:
        raise ValueError(
            f"{description} is {len(png_bytes)} bytes, but the digest-bound render manifest "
            f"records {expected_length}"
        )
    observed = sha256_hex(png_bytes)
    expected_sha256 = record["sha256"]
    if observed != expected_sha256:
        raise ValueError(
            f"{description} hashes to {observed!r}, but the digest-bound render manifest "
            f"records {expected_sha256!r}"
        )
    return png_bytes


def require_episode_audio_bytes(audio_composition_manifest: object, wav_bytes: bytes) -> bytes:
    """Refuse unless these exact bytes are the WAV the digest-bound composition names.

    Args:
        audio_composition_manifest: The parsed, standalone-valid Episode Audio Composition
            Manifest V1 whose ``audio.bytes`` / ``audio.sha256`` this WAV must equal.
        wav_bytes: The composed track's exact bytes, as captured by the single read that
            will also supply the carried copy.

    Returns:
        ``wav_bytes``, unchanged and unnormalised.

    Raises:
        TypeError: If the bytes are not ``bytes``, or a value is of the wrong exact type.
        ValueError: If the byte length or the SHA-256 does not equal the manifest's bound
            values.
    """
    manifest = validate_episode_audio_composition_manifest(audio_composition_manifest)
    audio = _document(manifest["audio"], "audio composition manifest audio")
    if type(wav_bytes) is not bytes:
        raise TypeError(f"episode audio bytes must be bytes, got {type(wav_bytes).__name__}")

    expected_length = audio["bytes"]
    if len(wav_bytes) != expected_length:
        raise ValueError(
            f"episode audio is {len(wav_bytes)} bytes, but the audio composition manifest "
            f"records {expected_length}"
        )
    observed = sha256_hex(wav_bytes)
    expected_sha256 = audio["sha256"]
    if observed != expected_sha256:
        raise ValueError(
            f"episode audio hashes to {observed!r}, but the audio composition manifest "
            f"records {expected_sha256!r}"
        )
    return wav_bytes


def require_assembly_sources_join(
    render_manifest: object,
    presentation_plan: object,
    audio_composition_manifest: object,
    delivery_plan: object,
    *,
    render_manifest_sha256: str,
    presentation_plan_sha256: str,
    audio_composition_manifest_sha256: str,
    delivery_plan_sha256: str,
    shot_plan_sha256: str,
) -> None:
    """Refuse unless the four bound documents, and their five captured digests, join exactly.

    The shot plan is offered only as a digest -- ``shot_plan_sha256`` -- because Phase 33
    reads no field from it at all; every fact this function proves about the shot plan
    comes from the two other documents that independently bind its digest.

    Named checks, in order: each captured digest equals its own document's canonical-bytes
    digest; the shot plan digest equals the one the render manifest was directed by; the
    delivery plan schedules against that same shot plan; the delivery witness digest equals
    the one the presentation plan binds; the shot plan digest equals the one the delivery
    plan binds; the audio composition manifest binds the exact presentation plan offered;
    the (episode, mode, previous_episode) identity triple agrees across all three primaries;
    the pinned motion-time digest agrees between the render manifest and the presentation
    plan; and the delivery plan's own schema version agrees with what the presentation plan
    declares.

    Args:
        render_manifest: The parsed, standalone-valid Episode Render Manifest V1.
        presentation_plan: The parsed, standalone-valid Episode Presentation Plan V1.
        audio_composition_manifest: The parsed, standalone-valid Episode Audio Composition
            Manifest V1.
        delivery_plan: The parsed, standalone-valid Episode Narration Delivery Plan V1
            witness.
        render_manifest_sha256: The digest captured from the render manifest's own bytes.
        presentation_plan_sha256: The digest captured from the presentation plan's own
            bytes.
        audio_composition_manifest_sha256: The digest captured from the composition
            manifest's own bytes.
        delivery_plan_sha256: The digest captured from the delivery witness's own bytes.
        shot_plan_sha256: The digest captured from the shot witness's own bytes.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: On any contradiction between the four documents and the five digests.
    """
    manifest = validate_episode_render_manifest(render_manifest)
    presentation = validate_episode_presentation_plan(presentation_plan)
    composition = validate_episode_audio_composition_manifest(audio_composition_manifest)
    delivery = validate_episode_narration_delivery_plan(delivery_plan)

    manifest_source = _document(manifest["source"], "render manifest source")
    presentation_source = _document(presentation["source"], "presentation plan source")
    composition_source = _document(composition["source"], "audio composition manifest source")
    delivery_source = _document(delivery["source"], "delivery plan source")

    computed_presentation_digest = sha256_hex(dumps_canonical(presentation, "presentation plan"))
    if computed_presentation_digest != presentation_plan_sha256:
        raise ValueError(
            f"the captured presentation plan digest {presentation_plan_sha256!r} does not "
            f"equal the offered document's own canonical digest {computed_presentation_digest!r}"
        )

    computed_render_digest = sha256_hex(dumps_canonical(manifest, "render manifest"))
    if computed_render_digest != render_manifest_sha256:
        raise ValueError(
            f"the captured render manifest digest {render_manifest_sha256!r} does not equal "
            f"the offered document's own canonical digest {computed_render_digest!r}"
        )

    computed_composition_digest = sha256_hex(
        dumps_canonical(composition, "audio composition manifest")
    )
    if computed_composition_digest != audio_composition_manifest_sha256:
        raise ValueError(
            "the captured audio composition manifest digest "
            f"{audio_composition_manifest_sha256!r} does not equal the offered document's "
            f"own canonical digest {computed_composition_digest!r}"
        )

    computed_delivery_digest = sha256_hex(dumps_canonical(delivery, "narration delivery plan"))
    if computed_delivery_digest != delivery_plan_sha256:
        raise ValueError(
            f"the captured delivery plan digest {delivery_plan_sha256!r} does not equal the "
            f"offered document's own canonical digest {computed_delivery_digest!r}"
        )

    manifest_shot_plan_sha256 = manifest_source["shot_plan_sha256"]
    if shot_plan_sha256 != manifest_shot_plan_sha256:
        raise ValueError(
            f"the captured shot plan digest {shot_plan_sha256!r} does not equal the render "
            f"manifest's own bound shot_plan_sha256 {manifest_shot_plan_sha256!r}; the render "
            "was not directed by this shot plan"
        )

    delivery_shot_plan_sha256 = delivery_source["shot_plan_sha256"]
    if delivery_shot_plan_sha256 != manifest_shot_plan_sha256:
        raise ValueError(
            "the delivery plan schedules a narration timed against shot plan "
            f"{delivery_shot_plan_sha256!r}, but the render manifest was directed by shot "
            f"plan {manifest_shot_plan_sha256!r}; the timing and the render are not the same "
            "shot plan's"
        )

    presentation_delivery_sha256 = presentation_source["delivery_plan_sha256"]
    if delivery_plan_sha256 != presentation_delivery_sha256:
        raise ValueError(
            f"the captured delivery plan digest {delivery_plan_sha256!r} does not equal the "
            "presentation plan's own bound delivery_plan_sha256 "
            f"{presentation_delivery_sha256!r}"
        )

    if shot_plan_sha256 != delivery_shot_plan_sha256:
        raise ValueError(
            f"the captured shot plan digest {shot_plan_sha256!r} does not equal the delivery "
            f"plan's own bound shot_plan_sha256 {delivery_shot_plan_sha256!r}"
        )

    composition_presentation_sha256 = composition_source["presentation_plan_sha256"]
    if presentation_plan_sha256 != composition_presentation_sha256:
        raise ValueError(
            f"the captured presentation plan digest {presentation_plan_sha256!r} does not "
            "equal the audio composition manifest's own bound presentation_plan_sha256 "
            f"{composition_presentation_sha256!r}"
        )

    identity = (
        manifest_source["episode"],
        manifest_source["mode"],
        manifest_source["previous_episode"],
    )
    for label, source in (
        ("presentation plan", presentation_source),
        ("audio composition manifest", composition_source),
    ):
        candidate = (source["episode"], source["mode"], source["previous_episode"])
        if candidate != identity:
            raise ValueError(
                f"{label} declares (episode, mode, previous_episode) {candidate!r}, but the "
                f"render manifest declares {identity!r}"
            )

    render_motion = manifest_source["motion_time_sha256"]
    presentation_motion = presentation_source["motion_time_sha256"]
    if render_motion != presentation_motion:
        raise ValueError(
            f"render manifest binds motion_time_sha256 {render_motion!r}, but the "
            f"presentation plan binds {presentation_motion!r}; the pixels and the timing are "
            "not the same clock's"
        )

    delivery_schema_version = presentation_source["delivery_schema_version"]
    if delivery["schema_version"] != delivery_schema_version:
        raise ValueError(
            f"delivery plan schema_version {delivery['schema_version']!r} does not equal the "
            f"presentation plan's own bound delivery_schema_version {delivery_schema_version!r}"
        )


def require_assembly_matches_sources(
    media_assembly_manifest: object,
    render_manifest: object,
    presentation_plan: object,
    audio_composition_manifest: object,
    delivery_plan: object,
) -> dict[str, JsonValue]:
    """Refuse unless the media assembly manifest tells the truth about the four documents.

    A media assembly manifest binds four documents by digest, and standalone validation
    checks each binding is well-formed. But the manifest also *copies* the composition's
    own carried-audio measurement, and restates every source identity field -- a copy that
    was never compared to its original is an unchecked assertion.

    Args:
        media_assembly_manifest: The parsed Episode Media Assembly Manifest.
        render_manifest: The parsed Episode Render Manifest V1 it bound.
        presentation_plan: The parsed Episode Presentation Plan V1 it bound.
        audio_composition_manifest: The parsed Episode Audio Composition Manifest V1 it
            bound.
        delivery_plan: The parsed Episode Narration Delivery Plan V1 witness it bound.

    Returns:
        The validated media assembly manifest.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: On any contradiction between the five documents.
    """
    manifest = validate_episode_media_assembly_manifest(media_assembly_manifest)
    render = validate_episode_render_manifest(render_manifest)
    presentation = validate_episode_presentation_plan(presentation_plan)
    composition = validate_episode_audio_composition_manifest(audio_composition_manifest)
    delivery = validate_episode_narration_delivery_plan(delivery_plan)

    source = _document(manifest["source"], "episode media assembly manifest source")
    render_source = _document(render["source"], "render manifest source")
    presentation_source = _document(presentation["source"], "presentation plan source")
    composition_source = _document(composition["source"], "audio composition manifest source")

    render_digest = sha256_hex(dumps_canonical(render, "render manifest"))
    if source["render_manifest_sha256"] != render_digest:
        raise ValueError(
            f"the assembly manifest binds render manifest {source['render_manifest_sha256']!r}"
            f", but the offered manifest hashes to {render_digest!r}"
        )
    presentation_digest = sha256_hex(dumps_canonical(presentation, "presentation plan"))
    if source["presentation_plan_sha256"] != presentation_digest:
        raise ValueError(
            "the assembly manifest binds presentation plan "
            f"{source['presentation_plan_sha256']!r}, but the offered plan hashes to "
            f"{presentation_digest!r}"
        )
    composition_digest = sha256_hex(dumps_canonical(composition, "audio composition manifest"))
    if source["audio_composition_manifest_sha256"] != composition_digest:
        raise ValueError(
            "the assembly manifest binds audio composition manifest "
            f"{source['audio_composition_manifest_sha256']!r}, but the offered manifest "
            f"hashes to {composition_digest!r}"
        )
    delivery_digest = sha256_hex(dumps_canonical(delivery, "narration delivery plan"))
    if source["delivery_plan_sha256"] != delivery_digest:
        raise ValueError(
            f"the assembly manifest binds delivery plan {source['delivery_plan_sha256']!r}, "
            f"but the offered plan hashes to {delivery_digest!r}"
        )

    if source["shot_plan_sha256"] != render_source["shot_plan_sha256"]:
        raise ValueError(
            f"the assembly manifest binds shot plan {source['shot_plan_sha256']!r}, but the "
            f"render manifest was directed by {render_source['shot_plan_sha256']!r}"
        )
    delivery_source = _document(delivery["source"], "delivery plan source")
    if source["shot_plan_sha256"] != delivery_source["shot_plan_sha256"]:
        raise ValueError(
            f"the assembly manifest binds shot plan {source['shot_plan_sha256']!r}, but the "
            "delivery plan schedules a narration timed against "
            f"{delivery_source['shot_plan_sha256']!r}"
        )

    for field in ("episode", "mode", "previous_episode"):
        if source[field] != render_source[field]:
            raise ValueError(
                f"the assembly manifest declares {field} {source[field]!r}, but the render "
                f"manifest declares {render_source[field]!r}"
            )
        if presentation_source[field] != render_source[field]:
            raise ValueError(
                f"the presentation plan declares {field} {presentation_source[field]!r}, but "
                f"the render manifest declares {render_source[field]!r}"
            )
        if composition_source[field] != render_source[field]:
            raise ValueError(
                "the audio composition manifest declares "
                f"{field} {composition_source[field]!r}, but the render manifest declares "
                f"{render_source[field]!r}"
            )

    if source["motion_time_sha256"] != render_source["motion_time_sha256"]:
        raise ValueError(
            f"the assembly manifest binds motion_time_sha256 {source['motion_time_sha256']!r}"
            f", but the render manifest binds {render_source['motion_time_sha256']!r}"
        )
    if source["motion_time_sha256"] != presentation_source["motion_time_sha256"]:
        raise ValueError(
            f"the assembly manifest binds motion_time_sha256 {source['motion_time_sha256']!r}"
            f", but the presentation plan binds {presentation_source['motion_time_sha256']!r}"
        )

    if source["presentation_schema_version"] != presentation["schema_version"]:
        raise ValueError(
            "the assembly manifest records presentation_schema_version "
            f"{source['presentation_schema_version']!r}, but the offered plan declares "
            f"{presentation['schema_version']!r}"
        )
    if source["render_manifest_schema_version"] != render["schema_version"]:
        raise ValueError(
            "the assembly manifest records render_manifest_schema_version "
            f"{source['render_manifest_schema_version']!r}, but the offered manifest "
            f"declares {render['schema_version']!r}"
        )
    if source["audio_composition_schema_version"] != composition["schema_version"]:
        raise ValueError(
            "the assembly manifest records audio_composition_schema_version "
            f"{source['audio_composition_schema_version']!r}, but the offered manifest "
            f"declares {composition['schema_version']!r}"
        )

    if composition_source["presentation_plan_sha256"] != presentation_digest:
        raise ValueError(
            "the audio composition manifest binds presentation plan "
            f"{composition_source['presentation_plan_sha256']!r}, but the offered plan "
            f"hashes to {presentation_digest!r}"
        )
    if presentation_source["delivery_plan_sha256"] != delivery_digest:
        raise ValueError(
            "the presentation plan binds delivery plan "
            f"{presentation_source['delivery_plan_sha256']!r}, but the offered plan hashes "
            f"to {delivery_digest!r}"
        )

    audio = _document(manifest["audio"], "episode media assembly manifest audio")
    composition_audio = _document(composition["audio"], "audio composition manifest audio")
    for field in ("bytes", "sha256", "audio_samples", "sample_rate_hz", "channels"):
        if audio[field] != composition_audio[field]:
            raise ValueError(
                f"the assembly manifest's audio.{field} is {audio[field]!r}, but the audio "
                f"composition manifest's own audio.{field} is {composition_audio[field]!r}"
            )

    return manifest


__all__ = [
    "require_assembly_matches_sources",
    "require_assembly_sources_join",
    "require_episode_audio_bytes",
    "require_render_frame_bytes",
]
