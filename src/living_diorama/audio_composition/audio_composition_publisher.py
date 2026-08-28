"""Orchestrate one episode's audio composition: geometry, source binding, splice, publish.

This module owns the composition-time orchestration only; every filesystem
primitive it uses is confined to :mod:`audio_composition_staging`. It
contains no direct ``open(``, ``os.replace``, ``os.fsync`` or ``shutil.``
anywhere.
"""

from pathlib import Path
from typing import cast

from living_diorama.audio_composition.audio_composer import (
    CompositionRefused,
    compose_episode_audio_bytes,
    pcm_payload_of,
    require_placement_geometry,
    require_silence_complement,
    span_pcm,
)
from living_diorama.audio_composition.audio_composition_audit import (
    audit_audio_composition_directory,
)
from living_diorama.audio_composition.audio_composition_binding import (
    require_composition_matches_plan_and_witness,
    require_voice_unit_bytes,
)
from living_diorama.audio_composition.audio_composition_manifest import (
    build_episode_audio_composition_manifest_document,
)
from living_diorama.audio_composition.audio_composition_schema_v1 import JsonValue
from living_diorama.audio_composition.audio_composition_spec import (
    AUDIO_COMPOSITION_MANIFEST_FILENAME,
    AUDIO_DIRECTORY,
    AUDIO_TRACK_PLAN_FILENAME,
    EPISODE_AUDIO_FILENAME,
    PARTIAL_SUFFIX,
    VOICE_MANIFEST_FILENAME,
    audio_composition_id,
)
from living_diorama.audio_composition.audio_composition_staging import (
    CompositionDirectoryRefused,
    _is_path_indirection,
    _require_direct_parent,
    discard_owned_staging,
    fsync_directory,
    publish_owned_staging,
    write_atomically,
)
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.voice_execution.speech_audio import read_wav_facts, verify_speech_audio


def publish_episode_audio(
    *,
    audio_track_plan: dict[str, JsonValue],
    audio_track_plan_bytes: bytes,
    voice_manifest: dict[str, JsonValue],
    voice_manifest_bytes: bytes,
    voice_dir: Path,
    output_root: Path,
) -> Path:
    """Compose, stage, publish and return one episode's audio composition directory.

    Internal post-gate helper. Its precondition, binding on every caller: the
    supplied ``audio_track_plan``, ``audio_track_plan_bytes``,
    ``voice_manifest`` and ``voice_manifest_bytes`` all originate from the
    current invocation, after the whole Phase 30 source gate and the source
    witness binding have already passed.

    The voice-unit-count precondition refuses before fresh staging exists --
    at that point this invocation has created nothing, so there is nothing to
    clean. The handled-refusal ``try`` begins at fresh staging creation and
    covers every handled failure from that point through terminal
    publication: once this run's own staging tree exists, a handled refusal
    (``OSError``, ``TypeError``, ``ValueError`` -- including
    ``CompositionRefused`` -- or ``CompositionDirectoryRefused``) discards
    that owned staging before propagating, so a refusal never litters the
    output root. An exception of any other class is never caught here: it
    propagates with the staging tree intact, as crash evidence for the next
    reviewed cleanup.

    Raises:
        CompositionRefused: If the geometry is unsound, a source payload is
            wrong, or the composed track fails its own measurement.
        CompositionDirectoryRefused: If the output root is an indirection,
            a final directory of this name already exists and is not a
            truthful, complete composition of this exact plan, or staging
            ownership cannot be proven.
    """
    placements = require_placement_geometry(audio_track_plan)

    source = cast(dict[str, JsonValue], audio_track_plan["source"])
    mode = cast(str, source["mode"])
    episode = cast(int, source["episode"])
    previous_episode = cast("int | None", source["previous_episode"])

    final_name = audio_composition_id(mode=mode, episode=episode, previous_episode=previous_episode)
    final_dir = output_root / final_name
    staging_name = f"{final_name}{PARTIAL_SUFFIX}"
    staging_dir = output_root / staging_name

    # ---- THE FIRST FILESYSTEM-SAFETY GATE FOR THE OUTPUT TREE ----
    _require_direct_parent(output_root)

    # ---- final_dir is never queried before its own indirection is refused ----
    if _is_path_indirection(final_dir):
        raise CompositionDirectoryRefused(
            f"{final_dir} is a symlink or junction; this phase never follows an indirection "
            "to decide whether a composition already exists"
        )

    plan_digest = sha256_hex(audio_track_plan_bytes)

    if final_dir.exists():
        problems = audit_audio_composition_directory(final_dir)
        if problems:
            raise CompositionDirectoryRefused(
                f"{final_dir} already exists and is not a truthful, complete composition: "
                f"{problems}"
            )
        existing_manifest = cast(
            dict[str, JsonValue],
            loads_canonical(
                (final_dir / AUDIO_COMPOSITION_MANIFEST_FILENAME).read_bytes(),
                "audio composition manifest",
            ),
        )
        existing_source = cast(dict[str, JsonValue], existing_manifest["source"])
        if existing_source["audio_track_plan_sha256"] != plan_digest:
            raise CompositionDirectoryRefused(
                f"{final_dir} already exists and composes a different audio track plan "
                f"({existing_source['audio_track_plan_sha256']!r} != {plan_digest!r}); nothing "
                "is deleted to make room"
            )
        return final_dir

    # ---- pre-staging precondition: this invocation has created nothing yet ----
    voice_units = cast(list[dict[str, JsonValue]], voice_manifest["voice_units"])
    if len(voice_units) != len(placements):
        raise CompositionRefused(
            f"the voice manifest executes {len(voice_units)} units, but the audio track plan "
            f"places {len(placements)}"
        )

    # ---- stale staging from a PRIOR run, cleaned before this run's own exists ----
    discard_owned_staging(staging_dir, expected_parent=output_root, expected_name=staging_name)

    try:
        staging_dir.mkdir(parents=True)
        (staging_dir / AUDIO_DIRECTORY).mkdir()

        write_atomically(staging_dir / AUDIO_TRACK_PLAN_FILENAME, audio_track_plan_bytes)
        write_atomically(staging_dir / VOICE_MANIFEST_FILENAME, voice_manifest_bytes)

        profile_rate: int | None = None
        profile_channels: int | None = None
        payloads: dict[int, bytes] = {}
        for position, (unit, (_start, count)) in enumerate(
            zip(voice_units, placements, strict=True), start=1
        ):
            unit_path = voice_dir / cast(str, unit["file"])

            rate, channels, samples = read_wav_facts(unit_path)
            if profile_rate is None:
                profile_rate, profile_channels = rate, channels
            elif (rate, channels) != (profile_rate, profile_channels):
                raise CompositionRefused(
                    f"voice unit {position} is sampled at {rate} Hz / {channels} channel(s), "
                    f"but voice unit 1 established {profile_rate} Hz / {profile_channels} "
                    "channel(s); every unit in one audited execution shares one profile"
                )
            if samples != count:
                raise CompositionRefused(
                    f"voice unit {position} measures {samples} samples on disk, but the sealed "
                    f"audio track plan places {count}"
                )

            structural = verify_speech_audio(
                unit_path,
                expected_sample_rate_hz=profile_rate,
                expected_channels=cast(int, profile_channels),
            )
            if structural:
                raise CompositionRefused(f"voice unit {position}: {structural}")

            raw_unit_bytes = unit_path.read_bytes()  # THE ONE READ, for the payload
            raw_unit_bytes = require_voice_unit_bytes(
                unit, raw_unit_bytes, f"voice unit {position}"
            )
            payloads[position] = pcm_payload_of(raw_unit_bytes, expected_samples=count)

        if profile_rate is None or profile_channels is None:
            raise CompositionRefused("no voice unit was available to establish a source profile")

        wav = compose_episode_audio_bytes(
            audio_track_plan=audio_track_plan,
            payloads=payloads,
            sample_rate_hz=profile_rate,
            channels=profile_channels,
        )
        track_path = staging_dir / AUDIO_DIRECTORY / EPISODE_AUDIO_FILENAME
        write_atomically(track_path, wav)

        # ---- ARTIFACT MEASUREMENT GATE: recompute from the bytes that landed ----
        structural = verify_speech_audio(
            track_path, expected_sample_rate_hz=profile_rate, expected_channels=profile_channels
        )
        if structural:
            raise CompositionRefused(f"composed track failed publication: {structural}")
        rate, channels, total_samples = read_wav_facts(track_path)
        clock = cast(dict[str, JsonValue], audio_track_plan["clock"])
        expected_total = cast(int, clock["audio_samples_total"])
        if total_samples != expected_total:
            raise CompositionRefused(
                f"composed track measures {total_samples} samples, but the sealed audio track "
                f"plan's audio_samples_total is {expected_total}"
            )

        track_bytes_on_disk = track_path.read_bytes()
        track_pcm = pcm_payload_of(track_bytes_on_disk, expected_samples=total_samples)
        require_silence_complement(track_pcm, placements)

        spans: dict[int, dict[str, object]] = {}
        for position, (start, count) in enumerate(placements, start=1):
            slice_pcm = span_pcm(track_pcm, start_sample=start, speech_samples=count)
            spans[position] = {"pcm_sha256": sha256_hex(slice_pcm)}

        audio_result: dict[str, object] = {
            "audio_samples": total_samples,
            "bytes": len(track_bytes_on_disk),
            "channels": channels,
            "sample_rate_hz": rate,
            "sha256": sha256_hex(track_bytes_on_disk),
        }

        manifest_document = build_episode_audio_composition_manifest_document(
            audio_track_plan=audio_track_plan, audio=audio_result, spans=spans
        )
        require_composition_matches_plan_and_witness(
            manifest_document, audio_track_plan, voice_manifest
        )
        manifest_bytes = dumps_canonical(manifest_document, "episode audio composition manifest")
        write_atomically(staging_dir / AUDIO_COMPOSITION_MANIFEST_FILENAME, manifest_bytes)

        # ---- TERMINAL PUBLICATION GATE ----
        problems = audit_audio_composition_directory(staging_dir)
        if problems:
            raise CompositionRefused(
                f"staged audio composition failed its own independent audit: {problems}"
            )

        fsync_directory(staging_dir / AUDIO_DIRECTORY)
        fsync_directory(staging_dir)
        publish_owned_staging(
            staging_dir,
            final_dir,
            expected_parent=output_root,
            expected_staging_name=staging_name,
            expected_final_name=final_name,
        )
        return final_dir
    except (OSError, TypeError, ValueError, CompositionDirectoryRefused):
        # A handled refusal: this run's own freshly created staging is
        # discarded so it never litters the output root as if it were crash
        # evidence. An unrecognized exception class -- a genuine crash --
        # is never caught here, so its `.partial` tree survives untouched
        # for the next reviewed cleanup.
        discard_owned_staging(staging_dir, expected_parent=output_root, expected_name=staging_name)
        raise


__all__ = ["publish_episode_audio"]
