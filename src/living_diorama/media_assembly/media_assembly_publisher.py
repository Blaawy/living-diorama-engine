"""Orchestrate one episode's media assembly: geometry, source binding, copy, publish.

This module owns the assembly-time orchestration only; every filesystem primitive it uses
is confined to :mod:`media_assembly_staging`. It contains no direct ``open(``,
``os.replace``, ``os.fsync``, ``shutil.`` or ``.lstat(`` anywhere.

The render manifest this phase binds is validated under the profile its own source block
declares -- ``"v2"`` exactly when ``movement_catalogue_sha256`` is present, else the V1
default -- the same auto-detection idiom the render verifier itself uses. The detected
profile is threaded into every downstream validator and relationship check below, so a
genuine V2 render assembles end to end without any caller choosing.
"""

from pathlib import Path
from typing import cast

from living_diorama.media_assembly.media_assembly_audit import (
    _audit_media_assembly_directory_with_observation,
    audit_media_assembly_directory,
)
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
    MediaAssemblyRefused,
    presentation_frame_map,
    require_clock_closure,
    require_playback_lookup,
    require_witness_frame_excluded,
)
from living_diorama.media_assembly.media_assembly_schema_v1 import JsonValue
from living_diorama.media_assembly.media_assembly_spec import (
    AUDIO_COMPOSITION_MANIFEST_COPY_FILENAME,
    AUDIO_DIRECTORY,
    DELIVERY_PLAN_COPY_FILENAME,
    EPISODE_AUDIO_FILENAME,
    MEDIA_ASSEMBLY_MANIFEST_FILENAME,
    PARTIAL_SUFFIX,
    PRESENTATION_DIRECTORY,
    PRESENTATION_PLAN_COPY_FILENAME,
    PROVENANCE_DIRECTORY,
    RENDER_MANIFEST_COPY_FILENAME,
    SHOT_PLAN_COPY_FILENAME,
    episode_audio_relative_path,
    media_assembly_id,
    presentation_frame_filename,
    presentation_frame_relative_path,
)
from living_diorama.media_assembly.media_assembly_staging import (
    MediaAssemblyDirectoryRefused,
    _is_path_indirection,
    _require_direct_parent,
    discard_owned_staging,
    fsync_directory,
    publish_owned_staging,
    write_atomically,
    write_frame_exclusively,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.render_execution.render_execution_spec import FRAMES_DIRECTORY


def publish_episode_media_assembly(
    *,
    render_manifest: dict[str, JsonValue],
    render_manifest_bytes: bytes,
    presentation_plan: dict[str, JsonValue],
    presentation_plan_bytes: bytes,
    audio_composition_manifest: dict[str, JsonValue],
    audio_composition_manifest_bytes: bytes,
    delivery_plan: dict[str, JsonValue],
    delivery_plan_bytes: bytes,
    shot_plan_bytes: bytes,
    wav_bytes: bytes,
    render_dir: Path,
    output_root: Path,
) -> Path:
    """Assemble, stage, publish and return one episode's media assembly directory.

    Internal post-gate helper. Its precondition, binding on every caller: the supplied
    ``render_manifest``, ``presentation_plan`` and ``audio_composition_manifest`` (and their
    exact captured bytes), the ``delivery_plan`` witness (and its bytes), the
    ``shot_plan_bytes`` witness capture, and ``wav_bytes`` all originate from the current
    invocation, after the locked Phase 27 source-verification gate has already passed
    against the four verification-only documents.

    Every cross-branch join, the integer clock, the presentation mapping and the
    witness-frame exclusion are proven here, before any byte of staging exists. The
    voice-count-style precondition -- every semantic frame the presentation plan requires
    has a playback record -- refuses before fresh staging exists, at which point this
    invocation has created nothing, so there is nothing to clean. The handled-refusal
    ``try`` begins at fresh staging creation and covers every handled failure from that
    point through terminal publication: once this run's own staging tree exists, a handled
    refusal (``OSError``, ``TypeError``, ``ValueError`` -- including ``MediaAssemblyRefused``
    -- or ``MediaAssemblyDirectoryRefused``) discards that owned staging before propagating,
    so a refusal never litters the output root. An exception of any other class is never
    caught here: it propagates with the staging tree intact, as crash evidence for the next
    reviewed cleanup.

    The render manifest profile is detected here, once, from the raw document's own
    ``source`` block (``"v2"`` exactly when ``movement_catalogue_sha256`` is present) and
    threaded into every downstream render-manifest validator and relationship check.

    Raises:
        MediaAssemblyRefused: If the geometry is unsound, a source payload is wrong, or the
            assembled artifact fails its own measurement.
        MediaAssemblyDirectoryRefused: If the output root is an indirection, a final
            directory of this name already exists and is not a truthful, complete assembly
            of this exact source set, or staging ownership cannot be proven.
    """
    _require_direct_parent(output_root)

    render_manifest_sha256 = sha256_hex(render_manifest_bytes)
    presentation_plan_sha256 = sha256_hex(presentation_plan_bytes)
    audio_composition_manifest_sha256 = sha256_hex(audio_composition_manifest_bytes)
    delivery_plan_sha256 = sha256_hex(delivery_plan_bytes)
    shot_plan_sha256 = sha256_hex(shot_plan_bytes)

    # ---- THE ONE PROFILE DETECTION for this assembly: the raw render manifest's own source ----
    render_manifest_source = render_manifest.get("source")
    render_camera_profile = (
        "v2"
        if isinstance(render_manifest_source, dict)
        and "movement_catalogue_sha256" in render_manifest_source
        else "v1"
    )

    require_assembly_sources_join(
        render_manifest,
        presentation_plan,
        audio_composition_manifest,
        delivery_plan,
        render_manifest_sha256=render_manifest_sha256,
        presentation_plan_sha256=presentation_plan_sha256,
        audio_composition_manifest_sha256=audio_composition_manifest_sha256,
        delivery_plan_sha256=delivery_plan_sha256,
        shot_plan_sha256=shot_plan_sha256,
        camera_profile=render_camera_profile,
    )

    clock = require_clock_closure(
        presentation_plan,
        render_manifest,
        audio_composition_manifest,
        camera_profile=render_camera_profile,
    )
    mapping = presentation_frame_map(presentation_plan)
    lookup = require_playback_lookup(render_manifest, camera_profile=render_camera_profile)
    require_witness_frame_excluded(mapping, clock)

    missing_semantics = sorted(set(mapping) - set(lookup))
    if missing_semantics:
        raise MediaAssemblyRefused(
            f"the presentation plan requires semantic frames {missing_semantics} that the "
            "render manifest names no playback record for"
        )

    require_episode_audio_bytes(audio_composition_manifest, wav_bytes)

    source = cast(dict[str, JsonValue], render_manifest["source"])
    mode = cast(str, source["mode"])
    episode = cast(int, source["episode"])
    previous_episode = cast("int | None", source["previous_episode"])

    final_name = media_assembly_id(mode=mode, episode=episode, previous_episode=previous_episode)
    final_dir = output_root / final_name
    staging_name = f"{final_name}{PARTIAL_SUFFIX}"
    staging_dir = output_root / staging_name

    # ---- final_dir is never queried before its own indirection is refused ----
    if _is_path_indirection(final_dir):
        raise MediaAssemblyDirectoryRefused(
            f"{final_dir} is a symlink or junction; this phase never follows an indirection "
            "to decide whether an assembly already exists"
        )

    if final_dir.exists():
        problems, _existing_bytes, existing = _audit_media_assembly_directory_with_observation(
            final_dir
        )
        if problems:
            raise MediaAssemblyDirectoryRefused(
                f"{final_dir} already exists and is not a truthful, complete assembly: {problems}"
            )
        existing_source = cast(dict[str, JsonValue], cast(dict[str, JsonValue], existing)["source"])
        for field, captured in (
            ("render_manifest_sha256", render_manifest_sha256),
            ("presentation_plan_sha256", presentation_plan_sha256),
            ("audio_composition_manifest_sha256", audio_composition_manifest_sha256),
            ("delivery_plan_sha256", delivery_plan_sha256),
            ("shot_plan_sha256", shot_plan_sha256),
        ):
            if existing_source[field] != captured:
                raise MediaAssemblyDirectoryRefused(
                    f"{final_dir} already exists and assembles a different {field} "
                    f"({existing_source[field]!r} != {captured!r}); nothing is deleted to "
                    "make room"
                )
        return final_dir

    # ---- stale staging from a PRIOR run, cleaned before this run's own exists ----
    discard_owned_staging(staging_dir, expected_parent=output_root, expected_name=staging_name)

    try:
        staging_dir.mkdir(parents=True)
        (staging_dir / PRESENTATION_DIRECTORY).mkdir()
        (staging_dir / AUDIO_DIRECTORY).mkdir()
        (staging_dir / PROVENANCE_DIRECTORY).mkdir()

        write_atomically(staging_dir / RENDER_MANIFEST_COPY_FILENAME, render_manifest_bytes)
        write_atomically(staging_dir / PRESENTATION_PLAN_COPY_FILENAME, presentation_plan_bytes)
        write_atomically(
            staging_dir / AUDIO_COMPOSITION_MANIFEST_COPY_FILENAME,
            audio_composition_manifest_bytes,
        )
        write_atomically(
            staging_dir / PROVENANCE_DIRECTORY / DELIVERY_PLAN_COPY_FILENAME, delivery_plan_bytes
        )
        write_atomically(
            staging_dir / PROVENANCE_DIRECTORY / SHOT_PLAN_COPY_FILENAME, shot_plan_bytes
        )

        positions_of: dict[int, list[int]] = {}
        for position, semantic in enumerate(mapping, start=1):
            positions_of.setdefault(semantic, []).append(position)

        frame_records: list[dict[str, object]] = [{} for _ in mapping]
        frames_directory = render_dir / FRAMES_DIRECTORY
        for semantic in sorted(positions_of):
            record = lookup.get(semantic)
            if record is None:  # pragma: no cover - closed by the pre-staging check above
                raise MediaAssemblyRefused(
                    f"the presentation plan requires semantic frame {semantic}, but the "
                    "render manifest names no playback record for it"
                )
            source_path = frames_directory / cast(str, record["file"])
            payload = source_path.read_bytes()  # <-- THE ONE READ
            payload = require_render_frame_bytes(record, payload, f"render frame {semantic}")
            digest = sha256_hex(payload)
            byte_length = len(payload)
            for position in positions_of[semantic]:
                destination = (
                    staging_dir / PRESENTATION_DIRECTORY / presentation_frame_filename(position)
                )
                write_frame_exclusively(destination, payload)
                frame_records[position - 1] = {
                    "bytes": byte_length,
                    "file": presentation_frame_relative_path(position),
                    "presentation_frame": position,
                    "semantic_frame": semantic,
                    "sha256": digest,
                }

        write_atomically(staging_dir / AUDIO_DIRECTORY / EPISODE_AUDIO_FILENAME, wav_bytes)

        composition_audio = cast(dict[str, JsonValue], audio_composition_manifest["audio"])
        audio_result: dict[str, object] = {
            "audio_samples": composition_audio["audio_samples"],
            "bytes": composition_audio["bytes"],
            "channels": composition_audio["channels"],
            "file": episode_audio_relative_path(),
            "sample_rate_hz": composition_audio["sample_rate_hz"],
            "sha256": composition_audio["sha256"],
        }

        manifest_document = build_episode_media_assembly_manifest_document(
            render_manifest=render_manifest,
            presentation_plan=presentation_plan,
            audio_composition_manifest=audio_composition_manifest,
            delivery_plan=delivery_plan,
            shot_plan_sha256=shot_plan_sha256,
            clock=clock,
            frames=tuple(frame_records),
            audio=audio_result,
            camera_profile=render_camera_profile,
        )
        require_assembly_matches_sources(
            manifest_document,
            render_manifest,
            presentation_plan,
            audio_composition_manifest,
            delivery_plan,
            camera_profile=render_camera_profile,
        )
        manifest_bytes = dumps_canonical(manifest_document, "episode media assembly manifest")
        write_atomically(staging_dir / MEDIA_ASSEMBLY_MANIFEST_FILENAME, manifest_bytes)

        # ---- TERMINAL PUBLICATION GATE: the full independent audit, on the staged tree ----
        problems = audit_media_assembly_directory(staging_dir)
        if problems:
            raise MediaAssemblyRefused(
                f"staged media assembly failed its own independent audit: {problems}"
            )

        fsync_directory(staging_dir / PRESENTATION_DIRECTORY)
        fsync_directory(staging_dir / AUDIO_DIRECTORY)
        fsync_directory(staging_dir / PROVENANCE_DIRECTORY)
        fsync_directory(staging_dir)
        publish_owned_staging(
            staging_dir,
            final_dir,
            expected_parent=output_root,
            expected_staging_name=staging_name,
            expected_final_name=final_name,
        )
        return final_dir
    except (OSError, TypeError, ValueError, MediaAssemblyDirectoryRefused):
        # A handled refusal: this run's own freshly created staging is discarded so it
        # never litters the output root as if it were crash evidence. An unrecognized
        # exception class -- a genuine crash -- is never caught here, so its `.partial`
        # tree survives untouched for the next reviewed cleanup.
        discard_owned_staging(staging_dir, expected_parent=output_root, expected_name=staging_name)
        raise


__all__ = ["publish_episode_media_assembly"]
