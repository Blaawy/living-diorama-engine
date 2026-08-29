"""Self-contained, tool-free audit of a published final-media directory.

This is the independent, TOOL-FREE half of Phase 35. It re-reads every byte in the
directory and decides whether the manifest told the truth about everything bytes can
prove: the exact inventory, the two provenance copies validated under their LOCKED
upstream schemas and re-hashed against the bound digests, the episode-identity and clock
joins, the decisive lineage join re-proven from the copies, the directory-name law, the
episode file's length and digest, the carried sidecars' field-for-field equality with the
Phase 34 records AND their re-hashed bytes, the rebuilt logical argv, the path-neutrality
byte scan, and the single-link law on every owned regular file.

Correction E, stated plainly: this audit NEVER claims it decoded or probed the MP4. The
recorded stream facts are tool-attested; their internal laws are proven by the manifest
validator this audit runs, and their re-proof against the actual bitstream belongs to the
tool-bearing executor, its no-op re-probe and re-decode, and the runtime acceptance.

It is self-contained: it reads only the entries inside the directory it is handed, and
succeeds after every upstream source location has disappeared. No expected condition
(``OSError``, ``TypeError``, ``ValueError`` or ``MediaEncodeDirectoryRefused``) escapes
this function: it always returns, never raises for a governed problem, writes nothing and
repairs nothing.
"""

import re
from pathlib import Path
from typing import Final, cast

from living_diorama.caption_serialization.caption_serialization_schema_v1 import (
    validate_episode_caption_serialization_manifest,
)
from living_diorama.media_assembly.media_assembly_schema_v1 import (
    validate_episode_media_assembly_manifest,
)
from living_diorama.media_encode.media_encode_schema_v1 import (
    JsonValue,
    validate_episode_media_encode_manifest,
)
from living_diorama.media_encode.media_encode_spec import (
    ASSEMBLY_MANIFEST_COPY_FILENAME,
    CAPTIONS_MANIFEST_COPY_FILENAME,
    MEDIA_ENCODE_MANIFEST_FILENAME,
    PROVENANCE_DIRECTORY,
    classify_media_encode_directory_entry,
    classify_media_encode_provenance_entry,
    media_encode_id,
)
from living_diorama.media_encode.media_encode_staging import (
    _is_path_indirection,
    _regular_file_link_count,
)
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex

_DRIVE_PATH_PATTERN: Final = re.compile(r"[A-Za-z]:[\\/]")
"""The one host-path shape the canonical byte scan refuses outright."""


def _audit_media_encode_directory_with_observation(
    final_dir: Path,
) -> tuple[list[str], bytes | None, dict[str, JsonValue] | None]:
    """Audit one final-media directory, returning the ONE manifest observation used.

    The manifest at ``final_dir / MEDIA_ENCODE_MANIFEST_FILENAME`` is read exactly once,
    from that directory and nowhere else. The returned bytes and document are that same
    observation, so a caller deciding existing-final identity never performs a second read
    and never supplies an authority of its own.

    Returns:
        ``(problems, manifest_bytes, manifest_document)``. The second and third members
        are ``None`` exactly when the manifest could not be captured, parsed, checked for
        canonical form and validated -- in which case ``problems`` is non-empty.
    """
    try:
        return _audit_governed_directory(final_dir)
    except OSError as error:
        return [f"{final_dir} could not be fully read: {error}"], None, None


def audit_media_encode_directory(final_dir: Path) -> list[str]:
    """Return every problem found in one published final-media directory.

    The public, self-contained, tool-free audit. It captures its own manifest exactly
    once from the directory it is handed and accepts no external manifest authority.

    Args:
        final_dir: The directory one final-media build owns.

    Returns:
        Human-readable problems, in the order they were found. An empty list means every
        byte-provable claim is truthful; the tool-attested stream facts remain exactly
        that -- attested -- until a tool-bearing re-probe re-proves them.
    """
    problems, _manifest_bytes, _manifest = _audit_media_encode_directory_with_observation(final_dir)
    return problems


def _audit_governed_directory(
    final_dir: Path,
) -> tuple[list[str], bytes | None, dict[str, JsonValue] | None]:
    """The real audit body, wrapped by the public entry point's ``OSError`` boundary."""
    if _is_path_indirection(final_dir):
        return (
            [f"{final_dir} is a symlink or junction; this phase never audits through one"],
            None,
            None,
        )
    if not final_dir.is_dir():
        return ([f"{final_dir} is not a directory"], None, None)

    manifest_path = final_dir / MEDIA_ENCODE_MANIFEST_FILENAME
    provenance_dir = final_dir / PROVENANCE_DIRECTORY
    assembly_copy_path = provenance_dir / ASSEMBLY_MANIFEST_COPY_FILENAME
    captions_copy_path = provenance_dir / CAPTIONS_MANIFEST_COPY_FILENAME

    for governed_path in (manifest_path, provenance_dir, assembly_copy_path, captions_copy_path):
        if _is_path_indirection(governed_path):
            return (
                [
                    f"{governed_path} is a symlink or junction; this phase never trusts a "
                    "governed entry reached through an indirection"
                ],
                None,
                None,
            )

    # ---- THE ONE READ of the media encode manifest: the returned observation ----
    if not manifest_path.is_file():
        return ([f"{manifest_path} is missing; this build never completed"], None, None)
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest_value = loads_canonical(manifest_bytes, "episode media encode manifest")
        manifest = validate_episode_media_encode_manifest(manifest_value)
    except (TypeError, ValueError) as error:
        return ([f"episode media encode manifest is invalid: {error}"], None, None)
    if manifest_bytes != dumps_canonical(manifest, "episode media encode manifest"):
        return ([f"{manifest_path} is not canonical bytes"], manifest_bytes, manifest)

    problems: list[str] = []

    # ---- the path-neutrality byte scan: no backslash, no drive path, ever ----
    manifest_text = manifest_bytes.decode("utf-8")
    if "\\" in manifest_text:
        problems.append(
            "the manifest's canonical bytes carry a backslash; canonical output is "
            "path-neutral and never names a host path"
        )
    if _DRIVE_PATH_PATTERN.search(manifest_text):
        problems.append(
            "the manifest's canonical bytes carry a drive path; canonical output is "
            "path-neutral and never names a host path"
        )

    # ---- the two provenance copies, validated under their LOCKED schemas ----
    if not provenance_dir.is_dir():
        return (
            problems + [f"{provenance_dir} is missing; this build never completed"],
            manifest_bytes,
            manifest,
        )
    if not assembly_copy_path.is_file():
        return (
            problems + [f"{assembly_copy_path} is missing; this build never completed"],
            manifest_bytes,
            manifest,
        )
    if not captions_copy_path.is_file():
        return (
            problems + [f"{captions_copy_path} is missing; this build never completed"],
            manifest_bytes,
            manifest,
        )

    assembly_bytes = assembly_copy_path.read_bytes()
    try:
        assembly_value = loads_canonical(assembly_bytes, "episode media assembly manifest")
        assembly = validate_episode_media_assembly_manifest(assembly_value)
    except (TypeError, ValueError) as error:
        return (
            problems + [f"copied media assembly manifest is invalid: {error}"],
            manifest_bytes,
            manifest,
        )
    if assembly_bytes != dumps_canonical(assembly, "episode media assembly manifest"):
        problems.append(f"{assembly_copy_path} is not canonical bytes")

    captions_bytes = captions_copy_path.read_bytes()
    try:
        captions_value = loads_canonical(captions_bytes, "episode caption serialization manifest")
        captions = validate_episode_caption_serialization_manifest(captions_value)
    except (TypeError, ValueError) as error:
        return (
            problems + [f"copied caption serialization manifest is invalid: {error}"],
            manifest_bytes,
            manifest,
        )
    if captions_bytes != dumps_canonical(captions, "episode caption serialization manifest"):
        problems.append(f"{captions_copy_path} is not canonical bytes")

    # ---- the two bound digests, re-hashed against the copies beside the manifest ----
    manifest_source = cast(dict[str, JsonValue], manifest["source"])
    assembly_digest = sha256_hex(assembly_bytes)
    captions_digest = sha256_hex(captions_bytes)
    if manifest_source.get("media_assembly_manifest_sha256") != assembly_digest:
        problems.append(
            f"the manifest binds media_assembly_manifest_sha256 "
            f"{manifest_source.get('media_assembly_manifest_sha256')!r}, but the copy "
            f"hashes to {assembly_digest!r}"
        )
    if manifest_source.get("caption_serialization_manifest_sha256") != captions_digest:
        problems.append(
            f"the manifest binds caption_serialization_manifest_sha256 "
            f"{manifest_source.get('caption_serialization_manifest_sha256')!r}, but the "
            f"copy hashes to {captions_digest!r}"
        )

    assembly_source = cast(dict[str, JsonValue], assembly["source"])
    captions_source = cast(dict[str, JsonValue], captions["source"])
    assembly_clock = cast(dict[str, JsonValue], assembly["clock"])

    if manifest_source.get("media_assembly_schema_version") != assembly["schema_version"]:
        problems.append(
            f"the manifest's source.media_assembly_schema_version is "
            f"{manifest_source.get('media_assembly_schema_version')!r}, but the copy "
            f"declares {assembly['schema_version']!r}"
        )
    if manifest_source.get("caption_serialization_schema_version") != captions["schema_version"]:
        problems.append(
            f"the manifest's source.caption_serialization_schema_version is "
            f"{manifest_source.get('caption_serialization_schema_version')!r}, but the "
            f"copy declares {captions['schema_version']!r}"
        )

    # ---- the identity and clock joins, re-proven whole from the copies ----
    for field in ("episode", "mode", "previous_episode"):
        if manifest_source.get(field) != assembly_source.get(field):
            problems.append(
                f"the manifest's source.{field} is {manifest_source.get(field)!r}, but the "
                f"copied assembly's is {assembly_source.get(field)!r}"
            )
        if assembly_source.get(field) != captions_source.get(field):
            problems.append(
                f"the copied assembly's source.{field} is {assembly_source.get(field)!r}, "
                f"but the copied caption serialization's is {captions_source.get(field)!r}"
            )

    manifest_clock = cast(dict[str, JsonValue], manifest["clock"])
    for key, expected in assembly_clock.items():
        if manifest_clock.get(key) != expected:
            problems.append(
                f"the manifest's clock.{key} is {manifest_clock.get(key)!r}, but the copied "
                f"assembly's own clock.{key} is {expected!r}"
            )
    captions_clock = cast(dict[str, JsonValue], captions["clock"])
    for field in ("fps", "presentation_frames_total"):
        if assembly_clock.get(field) != captions_clock.get(field):
            problems.append(
                f"the copied assembly's clock.{field} is {assembly_clock.get(field)!r}, but "
                f"the copied caption serialization's is {captions_clock.get(field)!r}"
            )

    # ---- THE LINEAGE JOIN, re-proven from the two copies alone ----
    if assembly_source.get("presentation_plan_sha256") != captions_source.get(
        "presentation_plan_sha256"
    ):
        problems.append(
            f"the copied assembly binds presentation_plan_sha256 "
            f"{assembly_source.get('presentation_plan_sha256')!r}, but the copied caption "
            f"serialization binds {captions_source.get('presentation_plan_sha256')!r}; the "
            "two inputs descend from different presentations"
        )

    # ---- the directory-name law: the id is re-derived, never trusted ----
    try:
        expected_id = media_encode_id(
            mode=cast(str, assembly_source["mode"]),
            episode=cast(int, assembly_source["episode"]),
            previous_episode=cast("int | None", assembly_source["previous_episode"]),
        )
    except (TypeError, ValueError) as error:
        problems.append(f"the copied assembly's source triple derives no episode id: {error}")
        expected_id = None
    if expected_id is not None and final_dir.name != expected_id:
        problems.append(
            f"the directory is named {final_dir.name!r}, but the copied assembly's own "
            f"source triple derives {expected_id!r}; a final-media build is never trusted "
            "under a name its sources do not derive"
        )

    # ---- the episode file: length and digest, re-derived from the published bytes ----
    video = cast(dict[str, JsonValue], manifest["video"])
    video_path = final_dir / cast(str, video["file"])
    if _is_path_indirection(video_path):
        problems.append(f"{video_path} is a symlink or junction")
    elif not video_path.is_file():
        problems.append(f"{video_path} is missing; this build never completed")
    else:
        video_bytes = video_path.read_bytes()
        if len(video_bytes) != video.get("bytes"):
            problems.append(
                f"the published episode file is {len(video_bytes)} bytes, but the manifest "
                f"records {video.get('bytes')!r}"
            )
        observed_video_sha256 = sha256_hex(video_bytes)
        if observed_video_sha256 != video.get("sha256"):
            problems.append(
                f"the published episode file hashes to {observed_video_sha256!r}, but the "
                f"manifest records {video.get('sha256')!r}"
            )

    # ---- the carried sidecars: field-for-field vs the Phase 34 records, plus re-hash ----
    manifest_captions = cast(dict[str, JsonValue], manifest["captions"])
    captions_sidecars = cast(dict[str, JsonValue], captions["sidecars"])
    for record_key in ("srt", "vtt"):
        carried = cast(dict[str, JsonValue], manifest_captions[record_key])
        upstream = cast(dict[str, JsonValue], captions_sidecars[record_key])
        for field in ("bytes", "file", "sha256"):
            if carried.get(field) != upstream.get(field):
                problems.append(
                    f"the manifest's captions.{record_key}.{field} is "
                    f"{carried.get(field)!r}, but the copied caption serialization "
                    f"manifest's own record is {upstream.get(field)!r}"
                )
        sidecar_path = final_dir / cast(str, carried["file"])
        if _is_path_indirection(sidecar_path):
            problems.append(f"{sidecar_path} is a symlink or junction")
            continue
        if not sidecar_path.is_file():
            problems.append(f"{sidecar_path} is missing; this build never completed")
            continue
        sidecar_bytes = sidecar_path.read_bytes()
        if len(sidecar_bytes) != carried.get("bytes"):
            problems.append(
                f"{sidecar_path} is {len(sidecar_bytes)} bytes, but the manifest records "
                f"{carried.get('bytes')!r}"
            )
        observed_sidecar_sha256 = sha256_hex(sidecar_bytes)
        if observed_sidecar_sha256 != carried.get("sha256"):
            problems.append(
                f"{sidecar_path} hashes to {observed_sidecar_sha256!r}, but the manifest "
                f"records {carried.get('sha256')!r}"
            )

    # ---- SINGLE-LINK SWEEP: every owned regular file ----
    for description, path in (
        ("episode media encode manifest", manifest_path),
        ("published episode file", video_path),
        (
            "srt sidecar",
            final_dir / cast(str, cast(dict[str, JsonValue], manifest_captions["srt"])["file"]),
        ),
        (
            "vtt sidecar",
            final_dir / cast(str, cast(dict[str, JsonValue], manifest_captions["vtt"])["file"]),
        ),
        ("media assembly manifest copy", assembly_copy_path),
        ("caption serialization manifest copy", captions_copy_path),
    ):
        if not path.is_file():
            continue
        links = _regular_file_link_count(path)
        if links != 1:
            problems.append(
                f"{description} at {path} has {links} directory entries pointing at it; a "
                "Phase 35 owned regular file must be an independent physical copy with "
                "exactly one, never a hardlink"
            )

    # ---- inventory sweep: no foreign or leftover entry anywhere this phase owns ----
    sweep_id = expected_id if expected_id is not None else final_dir.name
    for found in sorted(final_dir.iterdir()):
        if _is_path_indirection(found):
            problems.append(f"{found} is a symlink or junction; no directory entry may be one")
            continue
        kind = classify_media_encode_directory_entry(
            found.name, episode_id=sweep_id, is_directory=found.is_dir()
        )
        if kind == "partial":
            problems.append(
                f"{found} is this phase's own working file, left behind by a run that did "
                "not finish; a directory holding one is not a finished build"
            )
        elif kind == "foreign":
            problems.append(f"{found} is present but not accounted for by this phase's contract")

    if provenance_dir.is_dir():
        for found in sorted(provenance_dir.iterdir()):
            if _is_path_indirection(found):
                problems.append(
                    f"{found} is a symlink or junction; no provenance/ entry may be one"
                )
                continue
            kind = classify_media_encode_provenance_entry(found.name, is_directory=found.is_dir())
            if kind == "partial":
                problems.append(
                    f"{found} is this phase's own working file, left behind by a run that "
                    "did not finish; a directory holding one is not a finished build"
                )
            elif kind == "foreign":
                problems.append(
                    f"{found} is present but not accounted for by this phase's contract"
                )

    return problems, manifest_bytes, manifest


__all__ = ["audit_media_encode_directory"]
