"""Self-contained audit of a published media assembly against its own manifest.

This is the independent half of Phase 33. The publisher writes the copies and the
manifest; this function re-reads every byte in the directory and decides whether the
manifest told the truth. It trusts nothing the publisher recorded: every bound document's
digest is re-hashed from the copy beside this one; the D-chain (Phase 27 presentation ->
Phase 25 delivery -> Phase 22 shots <- Phase 23 render) is re-proven entirely from the four
published documents, with no upstream path required; the Phase 27 presentation mapping is
independently re-derived from the copied plan and compared, position by position, against
every published frame record -- the render record a frame must match is selected by that
re-derived semantic frame, never by the frame record's own declaration; and every
Phase 33-owned regular file -- the four documents, both provenance witnesses, the carried
WAV, and every presentation frame -- is proven to be an independent physical copy with
exactly one directory entry, never a hardlink.

It is self-contained: it reads only the entries inside the directory it is handed, and
succeeds after every upstream source location -- the render directory, the composition
directory, the presentation plan, the delivery plan, the shot plan -- has disappeared.

Every governed entry is refused as a problem if it is a symlink or Windows junction, before
its content or metadata is ever trusted. No expected condition (``OSError``, ``TypeError``,
``ValueError`` or ``MediaAssemblyDirectoryRefused``) escapes this function: it always
returns, it never raises for a governed filesystem or data problem. It writes nothing,
repairs nothing, and imports no synthesis or rendering engine.

The copied presentation plan is validated through the profile dispatcher
(:func:`living_diorama.presentation.presentation_schema_v2.validate_presentation_plan`), so
an assembly of a V2 plan -- whose held positions show the plan's own pure-bounce motion
windows -- audits exactly like one of a V1 plan: the mapping re-proof compares every
published frame record against the re-derived semantic frame, whichever profile the plan
carries.

The copied shot plan witness is validated through the V1/V2 auto-detecting dispatcher
:func:`living_diorama.cinematic.validate_shot_direction_plan_v2`, which delegates a V1
document byte-for-byte to the unchanged V1 validator and only governs the additive
``camera_movement`` blocks a V2 shot plan carries. The copied render manifest is validated
under the ``camera_profile`` detected from its own ``source`` block (``"v2"`` exactly when
``movement_catalogue_sha256`` is present), the same auto-detection idiom the render
verifier itself uses -- so a genuine V2 render audits without the caller ever choosing.
"""

from pathlib import Path
from typing import cast

from living_diorama.audio_composition.audio_composition_schema_v1 import (
    validate_episode_audio_composition_manifest,
)
from living_diorama.cinematic import validate_shot_direction_plan_v2
from living_diorama.media_assembly.media_assembly_binding import (
    require_assembly_matches_sources,
    require_assembly_sources_join,
    require_episode_audio_bytes,
    require_render_frame_bytes,
)
from living_diorama.media_assembly.media_assembly_mapping import (
    presentation_frame_map,
    require_clock_closure,
    require_playback_lookup,
    require_witness_frame_excluded,
)
from living_diorama.media_assembly.media_assembly_schema_v1 import (
    JsonValue,
    validate_episode_media_assembly_manifest,
)
from living_diorama.media_assembly.media_assembly_spec import (
    AUDIO_COMPOSITION_MANIFEST_COPY_FILENAME,
    AUDIO_DIRECTORY,
    DELIVERY_PLAN_COPY_FILENAME,
    EPISODE_AUDIO_FILENAME,
    MEDIA_ASSEMBLY_MANIFEST_FILENAME,
    PRESENTATION_DIRECTORY,
    PRESENTATION_PLAN_COPY_FILENAME,
    PROVENANCE_DIRECTORY,
    RENDER_MANIFEST_COPY_FILENAME,
    SHOT_PLAN_COPY_FILENAME,
    classify_media_assembly_directory_entry,
    classify_provenance_directory_entry,
    is_presentation_frame_filename,
    presentation_frame_filename,
)
from living_diorama.media_assembly.media_assembly_staging import (
    _is_path_indirection,
    _regular_file_link_count,
)
from living_diorama.narration_delivery.delivery_schema_v1 import (
    validate_episode_narration_delivery_plan,
)
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.presentation.presentation_schema_v2 import validate_presentation_plan
from living_diorama.render_execution.render_execution_schema_v1 import (
    validate_episode_render_manifest,
)


def _audit_media_assembly_directory_with_observation(
    assembly_dir: Path,
) -> tuple[list[str], bytes | None, dict[str, JsonValue] | None]:
    """Audit one assembly directory, returning the ONE manifest observation used.

    The manifest at ``assembly_dir / MEDIA_ASSEMBLY_MANIFEST_FILENAME`` is read exactly
    once, from that directory and nowhere else. The returned bytes and document are that
    same observation, so a caller deciding existing-final identity never performs a second
    read and never supplies an authority of its own.

    Returns:
        ``(problems, manifest_bytes, manifest_document)``. The second and third members are
        ``None`` exactly when the manifest could not be captured, parsed, checked for
        canonical form and validated -- in which case ``problems`` is non-empty. A missing
        manifest is always a problem.
    """
    try:
        return _audit_governed_directory(assembly_dir)
    except OSError as error:
        return [f"{assembly_dir} could not be fully read: {error}"], None, None


def audit_media_assembly_directory(assembly_dir: Path) -> list[str]:
    """Return every problem found in one published media assembly directory.

    The public, self-contained audit. It captures its own manifest exactly once from the
    directory it is handed and accepts no external manifest authority: there is no
    parameter through which a caller may supply manifest bytes of its own.

    Args:
        assembly_dir: The directory one media assembly owns.

    Returns:
        Human-readable problems, in the order they were found. An empty list means the
        assembly is complete and truthful.
    """
    problems, _manifest_bytes, _manifest = _audit_media_assembly_directory_with_observation(
        assembly_dir
    )
    return problems


def _audit_governed_directory(
    assembly_dir: Path,
) -> tuple[list[str], bytes | None, dict[str, JsonValue] | None]:
    """The real audit body, wrapped by the public entry point's ``OSError`` boundary."""
    if _is_path_indirection(assembly_dir):
        return (
            [f"{assembly_dir} is a symlink or junction; this phase never audits through one"],
            None,
            None,
        )

    render_path = assembly_dir / RENDER_MANIFEST_COPY_FILENAME
    presentation_path = assembly_dir / PRESENTATION_PLAN_COPY_FILENAME
    composition_path = assembly_dir / AUDIO_COMPOSITION_MANIFEST_COPY_FILENAME
    manifest_path = assembly_dir / MEDIA_ASSEMBLY_MANIFEST_FILENAME
    presentation_dir = assembly_dir / PRESENTATION_DIRECTORY
    audio_dir = assembly_dir / AUDIO_DIRECTORY
    provenance_dir = assembly_dir / PROVENANCE_DIRECTORY
    delivery_path = provenance_dir / DELIVERY_PLAN_COPY_FILENAME
    shot_path = provenance_dir / SHOT_PLAN_COPY_FILENAME
    wav_path = audio_dir / EPISODE_AUDIO_FILENAME

    for governed_path in (
        render_path,
        presentation_path,
        composition_path,
        manifest_path,
        presentation_dir,
        audio_dir,
        provenance_dir,
        delivery_path,
        shot_path,
        wav_path,
    ):
        if _is_path_indirection(governed_path):
            return (
                [
                    f"{governed_path} is a symlink or junction; this phase never trusts a "
                    "governed entry reached through an indirection"
                ],
                None,
                None,
            )

    for description, path in (
        ("render manifest copy", render_path),
        ("presentation plan copy", presentation_path),
        ("audio composition manifest copy", composition_path),
        ("presentation/ directory", presentation_dir),
        ("audio/ directory", audio_dir),
        ("provenance/ directory", provenance_dir),
        ("delivery plan witness", delivery_path),
        ("shot plan witness", shot_path),
        ("carried episode audio", wav_path),
    ):
        is_directory_kind = path in (presentation_dir, audio_dir, provenance_dir)
        exists = path.is_dir() if is_directory_kind else path.is_file()
        if not exists:
            return (
                [f"{path} is missing; this assembly never completed ({description})"],
                None,
                None,
            )

    # ---- THE ONE READ of the media assembly manifest: the returned observation ----
    if not manifest_path.is_file():
        return ([f"{manifest_path} is missing; this assembly never completed"], None, None)
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest_value = loads_canonical(manifest_bytes, "episode media assembly manifest")
        manifest = validate_episode_media_assembly_manifest(manifest_value)
    except (TypeError, ValueError) as error:
        return (
            [f"episode media assembly manifest is invalid: {error}"],
            manifest_bytes,
            None,
        )
    if manifest_bytes != dumps_canonical(manifest, "episode media assembly manifest"):
        return ([f"{manifest_path} is not canonical bytes"], manifest_bytes, manifest)

    problems: list[str] = []

    render_bytes = render_path.read_bytes()
    try:
        render_value = loads_canonical(render_bytes, "render manifest")
        # The render manifest copy is validated under the profile its own source block
        # declares, exactly the idiom verify_render.py uses: "v2" iff the movement
        # catalogue binding is present, else the V1-only default. The profile is then
        # threaded into every downstream relationship check that re-validates this
        # document, so a genuine V2 render audits end to end.
        render_value_source = render_value.get("source") if isinstance(render_value, dict) else None
        render_camera_profile = (
            "v2"
            if isinstance(render_value_source, dict)
            and "movement_catalogue_sha256" in render_value_source
            else "v1"
        )
        render = validate_episode_render_manifest(
            render_value, camera_profile=render_camera_profile
        )
    except (TypeError, ValueError) as error:
        return (
            problems + [f"copied render manifest is invalid: {error}"],
            manifest_bytes,
            manifest,
        )
    if render_bytes != dumps_canonical(render, "render manifest"):
        problems.append(f"{render_path} is not canonical bytes")

    presentation_bytes = presentation_path.read_bytes()
    try:
        presentation_value = loads_canonical(presentation_bytes, "presentation plan")
        presentation = validate_presentation_plan(presentation_value)
    except (TypeError, ValueError) as error:
        return (
            problems + [f"copied presentation plan is invalid: {error}"],
            manifest_bytes,
            manifest,
        )
    if presentation_bytes != dumps_canonical(presentation, "presentation plan"):
        problems.append(f"{presentation_path} is not canonical bytes")

    composition_bytes = composition_path.read_bytes()
    try:
        composition_value = loads_canonical(composition_bytes, "audio composition manifest")
        composition = validate_episode_audio_composition_manifest(composition_value)
    except (TypeError, ValueError) as error:
        return (
            problems + [f"copied audio composition manifest is invalid: {error}"],
            manifest_bytes,
            manifest,
        )
    if composition_bytes != dumps_canonical(composition, "audio composition manifest"):
        problems.append(f"{composition_path} is not canonical bytes")

    delivery_bytes = delivery_path.read_bytes()
    try:
        delivery_value = loads_canonical(delivery_bytes, "narration delivery plan")
        delivery = validate_episode_narration_delivery_plan(delivery_value)
    except (TypeError, ValueError) as error:
        return (
            problems + [f"copied delivery plan witness is invalid: {error}"],
            manifest_bytes,
            manifest,
        )
    if delivery_bytes != dumps_canonical(delivery, "narration delivery plan"):
        problems.append(f"{delivery_path} is not canonical bytes")

    shot_bytes = shot_path.read_bytes()
    try:
        shot_value = loads_canonical(shot_bytes, "shot direction plan")
        shots = validate_shot_direction_plan_v2(shot_value)
    except (TypeError, ValueError) as error:
        return (
            problems + [f"copied shot plan witness is invalid: {error}"],
            manifest_bytes,
            manifest,
        )
    if shot_bytes != dumps_canonical(shots, "shot direction plan"):
        problems.append(f"{shot_path} is not canonical bytes")

    # ---- SINGLE-LINK SWEEP (Correction K): the four documents, both witnesses, the WAV ----
    for description, path in (
        ("render manifest copy", render_path),
        ("presentation plan copy", presentation_path),
        ("audio composition manifest copy", composition_path),
        ("episode media assembly manifest", manifest_path),
        ("delivery plan witness", delivery_path),
        ("shot plan witness", shot_path),
        ("carried episode audio", wav_path),
    ):
        if not path.is_file():
            problems.append(f"{description} at {path} is not a regular file")
            continue
        links = _regular_file_link_count(path)
        if links != 1:
            problems.append(
                f"{description} at {path} has {links} directory entries pointing at it; a "
                "Phase 33 owned regular file must be an independent physical copy with "
                "exactly one, never a hardlink"
            )

    # ---- the five source digests, re-hashed against the copies, plus schema versions ----
    render_digest = sha256_hex(render_bytes)
    presentation_digest = sha256_hex(presentation_bytes)
    composition_digest = sha256_hex(composition_bytes)
    delivery_digest = sha256_hex(delivery_bytes)
    shot_digest = sha256_hex(shot_bytes)

    try:
        require_assembly_sources_join(
            render,
            presentation,
            composition,
            delivery,
            render_manifest_sha256=render_digest,
            presentation_plan_sha256=presentation_digest,
            audio_composition_manifest_sha256=composition_digest,
            delivery_plan_sha256=delivery_digest,
            shot_plan_sha256=shot_digest,
            camera_profile=render_camera_profile,
        )
    except (TypeError, ValueError) as error:
        problems.append(f"the four bound documents do not join: {error}")

    delivery_source = cast(dict[str, JsonValue], delivery["source"])
    if shots["schema_version"] != delivery_source["shot_schema_version"]:
        problems.append(
            f"copied shot plan schema_version {shots['schema_version']!r} does not equal "
            f"the delivery plan's own bound shot_schema_version "
            f"{delivery_source['shot_schema_version']!r}"
        )

    try:
        require_assembly_matches_sources(
            manifest,
            render,
            presentation,
            composition,
            delivery,
            camera_profile=render_camera_profile,
        )
    except (TypeError, ValueError) as error:
        problems.append(f"the manifest contradicts a document beside it: {error}")

    # ---- clock re-derivation and closure, independent of the manifest's own claim ----
    try:
        resolved_clock = require_clock_closure(
            presentation, render, composition, camera_profile=render_camera_profile
        )
    except (TypeError, ValueError) as error:
        problems.append(f"the integer clock does not close: {error}")
        resolved_clock = None

    manifest_clock = cast(dict[str, JsonValue], manifest["clock"])
    if resolved_clock is not None:
        for key, expected in resolved_clock.items():
            if manifest_clock.get(key) != expected:
                problems.append(
                    f"the assembly manifest's clock.{key} is {manifest_clock.get(key)!r}, but "
                    f"the independently re-derived value is {expected!r}"
                )

    # ---- THE MAPPING RE-PROOF: never trust a frame record's own semantic_frame ----
    frames = cast(list[dict[str, JsonValue]], manifest["frames"])
    try:
        expected_mapping = presentation_frame_map(presentation)
    except (TypeError, ValueError) as error:
        problems.append(f"the copied presentation plan does not expand: {error}")
        expected_mapping = ()
    try:
        lookup = require_playback_lookup(render, camera_profile=render_camera_profile)
    except (TypeError, ValueError) as error:
        problems.append(f"the copied render manifest has no usable playback lookup: {error}")
        lookup = {}

    if resolved_clock is not None and expected_mapping:
        try:
            require_witness_frame_excluded(expected_mapping, resolved_clock)
        except (TypeError, ValueError) as error:
            problems.append(f"the re-derived mapping leaks the witness frame: {error}")

    if len(expected_mapping) != len(frames):
        problems.append(
            f"the copied presentation plan expands to {len(expected_mapping)} presentation "
            f"frames, but the assembly manifest carries {len(frames)}"
        )

    for position in range(1, min(len(expected_mapping), len(frames)) + 1):
        expected_semantic = expected_mapping[position - 1]
        frame_record = frames[position - 1]
        label = f"presentation frame {position}"

        if frame_record.get("presentation_frame") != position:
            problems.append(
                f"{label}: frame record presentation_frame is "
                f"{frame_record.get('presentation_frame')!r}, expected {position}"
            )
        recorded_semantic = frame_record.get("semantic_frame")
        if recorded_semantic != expected_semantic:
            problems.append(
                f"{label}: frame record semantic_frame is {recorded_semantic!r}, but the "
                f"presentation plan's own mapping requires {expected_semantic!r}"
            )

        # THE RENDER RECORD IS SELECTED BY THE P27-DERIVED SEMANTIC FRAME, NEVER BY THE
        # FRAME RECORD'S OWN DECLARATION.
        expected_render_record = lookup.get(expected_semantic)
        if expected_render_record is None:
            problems.append(
                f"{label}: no playback record for semantic frame {expected_semantic} exists "
                "in the copied render manifest"
            )
            continue

        published_path = presentation_dir / presentation_frame_filename(position)
        if _is_path_indirection(published_path):
            problems.append(f"{published_path} is a symlink or junction")
            continue
        if not published_path.is_file():
            problems.append(f"{published_path} is missing or not a regular file")
            continue
        links = _regular_file_link_count(published_path)
        if links != 1:
            problems.append(
                f"{published_path} has {links} directory entries pointing at it; a "
                "presentation frame must be an independent physical copy, never a hardlink"
            )

        published_bytes = published_path.read_bytes()
        try:
            require_render_frame_bytes(expected_render_record, published_bytes, label)
        except (TypeError, ValueError) as error:
            problems.append(f"{label}: {error}")

        expected_bytes = expected_render_record.get("bytes")
        expected_sha256 = expected_render_record.get("sha256")
        if frame_record.get("bytes") != expected_bytes:
            problems.append(
                f"{label}: frame record bytes is {frame_record.get('bytes')!r}, but the "
                f"matching render record declares {expected_bytes!r}"
            )
        if frame_record.get("sha256") != expected_sha256:
            problems.append(
                f"{label}: frame record sha256 is {frame_record.get('sha256')!r}, but the "
                f"matching render record declares {expected_sha256!r}"
            )

    # ---- the carried WAV: length and SHA-256 against the composition manifest and audio block ----
    wav_bytes = wav_path.read_bytes()
    try:
        require_episode_audio_bytes(composition, wav_bytes)
    except (TypeError, ValueError) as error:
        problems.append(
            f"carried episode audio does not match the audio composition manifest: {error}"
        )

    audio_block = cast(dict[str, JsonValue], manifest["audio"])
    composition_audio = cast(dict[str, JsonValue], composition["audio"])
    for field in ("bytes", "sha256", "audio_samples", "sample_rate_hz", "channels"):
        if audio_block.get(field) != composition_audio.get(field):
            problems.append(
                f"the assembly manifest's audio.{field} is {audio_block.get(field)!r}, but "
                f"the audio composition manifest's own audio.{field} is "
                f"{composition_audio.get(field)!r}"
            )
    if len(wav_bytes) != audio_block.get("bytes"):
        problems.append(
            f"carried episode audio on disk is {len(wav_bytes)} bytes, but the assembly "
            f"manifest records {audio_block.get('bytes')!r}"
        )
    observed_wav_sha256 = sha256_hex(wav_bytes)
    if observed_wav_sha256 != audio_block.get("sha256"):
        problems.append(
            f"carried episode audio hashes to {observed_wav_sha256!r}, but the assembly "
            f"manifest records {audio_block.get('sha256')!r}"
        )

    # ---- completeness is measured, not re-trusted (schema already proves self-consistency) ----
    completeness = cast(dict[str, JsonValue], manifest["completeness"])
    if completeness.get("presentation_frames_assembled") != len(frames):
        problems.append(
            "completeness presentation_frames_assembled disagrees with the records present"
        )
    measured_unique = len({frame.get("semantic_frame") for frame in frames})
    if completeness.get("unique_semantic_frames_used") != measured_unique:
        problems.append(
            "completeness unique_semantic_frames_used disagrees with the records present"
        )
    if resolved_clock is not None:
        expected_unique_span = (
            resolved_clock["semantic_final_frame"] - resolved_clock["semantic_first_frame"] + 1
        )
        if measured_unique != expected_unique_span:
            problems.append(
                f"unique_semantic_frames_used is {measured_unique}, but the proven semantic "
                f"span accounts for {expected_unique_span} frames; a semantic frame was "
                "silently dropped"
            )

    # ---- inventory sweep: no foreign or leftover entry anywhere this phase owns ----
    for found in sorted(assembly_dir.iterdir()):
        if _is_path_indirection(found):
            problems.append(f"{found} is a symlink or junction; no directory entry may be one")
            continue
        kind = classify_media_assembly_directory_entry(found.name, is_directory=found.is_dir())
        if kind == "partial":
            problems.append(
                f"{found} is this phase's own working file, left behind by a run that did "
                "not finish; a directory holding one is not a finished assembly"
            )
        elif kind == "foreign":
            problems.append(f"{found} is present but not accounted for by this phase's contract")

    if presentation_dir.is_dir():
        for found in sorted(presentation_dir.iterdir()):
            if _is_path_indirection(found):
                problems.append(
                    f"{found} is a symlink or junction; no presentation/ entry may be one"
                )
                continue
            if found.is_dir():
                problems.append(f"{found} is a directory inside presentation/, never permitted")
                continue
            # OWNERSHIP IS DECIDED BY THE FROZEN FILENAME GRAMMAR, NEVER BY A NUMERIC TAIL.
            # A name is this phase's own only if it is exactly ``frame_`` + seven ASCII digits
            # + ``.png`` with an in-domain coordinate. Deriving a coordinate from an arbitrary
            # underscore-separated tail would accept ``evil_0000001.png``, ``frame_1.png`` and
            # ``frame_0000001.jpg`` as owned, because each carries an in-range integer.
            if not is_presentation_frame_filename(found.name):
                problems.append(
                    f"{found} is present but is not an owned presentation frame filename; "
                    "no foreign entry may sit inside presentation/"
                )
                continue
            position = int(found.name[len("frame_") : -len(".png")])
            if not (1 <= position <= len(frames)):
                problems.append(f"{found} is present but no frame record accounts for it")

    if audio_dir.is_dir():
        for found in sorted(audio_dir.iterdir()):
            if _is_path_indirection(found):
                problems.append(f"{found} is a symlink or junction; no audio/ entry may be one")
                continue
            if found.name != EPISODE_AUDIO_FILENAME:
                problems.append(f"{found} is present but no audio record accounts for it")

    if provenance_dir.is_dir():
        for found in sorted(provenance_dir.iterdir()):
            if _is_path_indirection(found):
                problems.append(
                    f"{found} is a symlink or junction; no provenance/ entry may be one"
                )
                continue
            kind = classify_provenance_directory_entry(found.name, is_directory=found.is_dir())
            if kind != "owned":
                problems.append(
                    f"{found} is present but not accounted for by this phase's contract"
                )

    return problems, manifest_bytes, manifest


__all__ = ["audit_media_assembly_directory"]
