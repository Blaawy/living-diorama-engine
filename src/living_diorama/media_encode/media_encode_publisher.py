"""Staging-side orchestration for one final-media build: writes, gates, publication.

This module is the pure half of the Phase 35 execution seam: it takes the encode's and
the probe's RESULTS as arguments -- captured bytes, measured integers, validated
documents -- and never invokes anything. Every filesystem primitive it uses is confined
to :mod:`media_encode_staging`; it contains no direct ``open(``, ``os.replace``,
``os.fsync``, ``shutil.`` or ``.lstat(`` anywhere, and no subprocess exists anywhere in
this package.

The executor (``media/ffmpeg/scripts/encode_episode.py``) owns the tool spawns and calls
these functions in the frozen order; keeping them here means every write, every gate and
the terminal publication can be attacked in ordinary tests through the fake-runner seam.
"""

from pathlib import Path
from typing import cast

from living_diorama.caption_serialization.caption_serialization_spec import (
    SRT_SUFFIX,
    VTT_SUFFIX,
    sidecar_filename,
)
from living_diorama.media_encode.media_encode_audit import audit_media_encode_directory
from living_diorama.media_encode.media_encode_schema_v1 import JsonValue
from living_diorama.media_encode.media_encode_spec import (
    ASSEMBLY_MANIFEST_COPY_FILENAME,
    CAPTIONS_MANIFEST_COPY_FILENAME,
    MEDIA_ENCODE_MANIFEST_FILENAME,
    PARTIAL_SUFFIX,
    PROVENANCE_DIRECTORY,
    SNAPSHOT_AUDIO_FILENAME,
    MediaEncodeRefused,
    media_filename,
)
from living_diorama.media_encode.media_encode_staging import (
    MediaEncodeDirectoryRefused,
    _is_path_indirection,
    _require_direct_parent,
    discard_owned_staging,
    fsync_directory,
    publish_owned_staging,
    read_file_bytes,
    write_atomically,
)
from living_diorama.persistence.schema.state_hash import sha256_hex

HANDLED_REFUSALS = (OSError, TypeError, ValueError, MediaEncodeDirectoryRefused)
"""The handled-refusal classes whose staging is discarded, never preserved.

``MediaEncodeRefused`` subclasses ``ValueError`` and the executor's own refusal class is
required to as well, so every reviewed refusal lands here; an exception of any other
class is a genuine crash and its ``.partial`` tree survives as evidence.
"""


def begin_media_encode_staging(output_root: Path, episode_id: str) -> tuple[Path, Path, str]:
    """Prepare this run's staging: refuse indirections, discard stale, create fresh.

    Returns:
        ``(staging_dir, final_dir, staging_name)`` for the frozen episode id.

    Raises:
        MediaEncodeDirectoryRefused: If the output root or the final path is an
            indirection, or a stale staging tree cannot be proven this phase's own.
        OSError: If creation itself fails.
    """
    _require_direct_parent(output_root)
    final_dir = output_root / episode_id
    staging_name = f"{episode_id}{PARTIAL_SUFFIX}"
    staging_dir = output_root / staging_name

    if _is_path_indirection(final_dir):
        raise MediaEncodeDirectoryRefused(
            f"{final_dir} is a symlink or junction; this phase never follows an indirection "
            "to decide whether a build already exists"
        )
    # ---- stale staging from a PRIOR run, cleaned before this run's own exists ----
    discard_owned_staging(
        staging_dir,
        expected_parent=output_root,
        expected_name=staging_name,
        episode_id=episode_id,
    )
    staging_dir.mkdir(parents=True)
    (staging_dir / PROVENANCE_DIRECTORY).mkdir()
    return staging_dir, final_dir, staging_name


def write_audio_snapshot(staging_dir: Path, wav_bytes: bytes) -> Path:
    """Write the captured, digest-verified P33 WAV bytes as this run's snapshot temp.

    The encoder consumes this snapshot rather than reopening the assembly's WAV path, so
    the audio-input TOCTOU closes outright.
    """
    if type(wav_bytes) is not bytes:
        raise TypeError(f"wav_bytes must be bytes, got {type(wav_bytes).__name__}")
    snapshot_path = staging_dir / SNAPSHOT_AUDIO_FILENAME
    write_atomically(snapshot_path, wav_bytes)
    return snapshot_path


def write_final_media(staging_dir: Path, episode_id: str, mp4_bytes: bytes) -> str:
    """Write the final episode file FROM the captured bytes, re-read it, prove equality.

    Correction D's terminal steps: the staged copy is written from the one captured
    observation, then RE-READ, and its digest must equal the captured digest exactly --
    the published bytes therefore equal the captured, probed, decoded bytes.

    Returns:
        The captured observation's SHA-256, now proven to be the staged file's own.

    Raises:
        MediaEncodeRefused: If the re-read staged bytes do not equal the capture.
    """
    if type(mp4_bytes) is not bytes:
        raise TypeError(f"mp4_bytes must be bytes, got {type(mp4_bytes).__name__}")
    if not mp4_bytes:
        raise MediaEncodeRefused(
            "the captured media is empty; a truthful encode leaves exactly one non-empty "
            "observation"
        )
    captured_sha256 = sha256_hex(mp4_bytes)
    media_path = staging_dir / media_filename(episode_id)
    write_atomically(media_path, mp4_bytes)
    staged_bytes = read_file_bytes(media_path)
    staged_sha256 = sha256_hex(staged_bytes)
    if staged_sha256 != captured_sha256:
        raise MediaEncodeRefused(
            f"the staged episode file hashes to {staged_sha256!r}, but the captured "
            f"observation is {captured_sha256!r}; the published bytes must equal the "
            "captured bytes exactly"
        )
    return captured_sha256


def write_sidecar_copies(
    staging_dir: Path,
    episode_id: str,
    *,
    captions_manifest: dict[str, JsonValue],
    srt_bytes: bytes,
    vtt_bytes: bytes,
) -> None:
    """Write the two carried sidecars from captured bytes, digest-proven BEFORE writing.

    Each captured sidecar observation must equal the Phase 34 manifest's own record --
    length and digest -- before a byte lands in staging; the carry is byte-exact or
    nothing.

    Raises:
        MediaEncodeRefused: If a captured sidecar does not match its Phase 34 record.
    """
    sidecars = cast(dict[str, JsonValue], captions_manifest["sidecars"])
    for record_key, suffix, payload in (
        ("srt", SRT_SUFFIX, srt_bytes),
        ("vtt", VTT_SUFFIX, vtt_bytes),
    ):
        if type(payload) is not bytes:
            raise TypeError(f"{record_key} bytes must be bytes, got {type(payload).__name__}")
        record = cast(dict[str, JsonValue], sidecars[record_key])
        if len(payload) != record.get("bytes"):
            raise MediaEncodeRefused(
                f"the captured {record_key} sidecar is {len(payload)} bytes, but the "
                f"caption serialization manifest records {record.get('bytes')!r}"
            )
        observed = sha256_hex(payload)
        if observed != record.get("sha256"):
            raise MediaEncodeRefused(
                f"the captured {record_key} sidecar hashes to {observed!r}, but the caption "
                f"serialization manifest records {record.get('sha256')!r}"
            )
        write_atomically(staging_dir / sidecar_filename(episode_id, suffix), payload)


def write_provenance_copies(
    staging_dir: Path, *, assembly_manifest_bytes: bytes, captions_manifest_bytes: bytes
) -> None:
    """Write the two bound manifests' exact captured bytes into ``provenance/``."""
    write_atomically(
        staging_dir / PROVENANCE_DIRECTORY / ASSEMBLY_MANIFEST_COPY_FILENAME,
        assembly_manifest_bytes,
    )
    write_atomically(
        staging_dir / PROVENANCE_DIRECTORY / CAPTIONS_MANIFEST_COPY_FILENAME,
        captions_manifest_bytes,
    )


def write_media_encode_manifest(
    staging_dir: Path, manifest_bytes: bytes, *, runtime_roots: tuple[str, ...]
) -> None:
    """Write the canonical manifest, after the decisive path-neutrality assertion.

    The dynamic backstop of the placeholder model: no runtime root's string -- the
    assembly directory, the captions directory, the output root, the staging tree -- may
    appear anywhere in the canonical bytes, plainly or JSON-escaped, and no backslash may
    appear at all.

    Raises:
        MediaEncodeRefused: If any runtime root or a backslash reaches the canonical
            bytes.
    """
    if type(manifest_bytes) is not bytes:
        raise TypeError(f"manifest_bytes must be bytes, got {type(manifest_bytes).__name__}")
    manifest_text = manifest_bytes.decode("utf-8")
    if "\\" in manifest_text:
        raise MediaEncodeRefused(
            "the manifest's canonical bytes carry a backslash; canonical output is "
            "path-neutral and never names a host path"
        )
    for root in runtime_roots:
        if type(root) is not str:
            raise TypeError(f"runtime_roots members must be str, got {type(root).__name__}")
        for form in (root, root.replace("\\", "\\\\"), root.replace("\\", "/")):
            if form and form in manifest_text:
                raise MediaEncodeRefused(
                    f"the manifest's canonical bytes carry the runtime root {root!r}; "
                    "canonical output is path-neutral and never names a host path"
                )
    write_atomically(staging_dir / MEDIA_ENCODE_MANIFEST_FILENAME, manifest_bytes)


def publish_media_encode(
    staging_dir: Path,
    final_dir: Path,
    *,
    output_root: Path,
    staging_name: str,
    final_name: str,
) -> Path:
    """Run the terminal staged audit, then publish the tree atomically, once.

    Raises:
        MediaEncodeRefused: If the staged tree fails its own independent audit.
        MediaEncodeDirectoryRefused: If publication ownership cannot be proven or the
            destination exists.
    """
    problems = _staged_build_problems(staging_dir, expected_final_name=final_name)
    if problems:
        raise MediaEncodeRefused(
            f"staged final-media build failed its own independent audit: {problems}"
        )
    fsync_directory(staging_dir / PROVENANCE_DIRECTORY)
    fsync_directory(staging_dir)
    publish_owned_staging(
        staging_dir,
        final_dir,
        expected_parent=output_root,
        expected_staging_name=staging_name,
        expected_final_name=final_name,
        episode_id=final_name,
    )
    return final_dir


def _staged_build_problems(staging_dir: Path, *, expected_final_name: str) -> list[str]:
    """Return the full audit's problems for a staged tree, netting the staging-name seam.

    The self-contained audit re-derives the directory name from the copied assembly and
    would truthfully flag the ``.partial`` staging name; that one finding -- and only that
    one -- is the seam the staging law itself creates, so it is filtered by its exact
    expected text. Every other problem the audit can raise survives untouched.
    """
    expected_seam = (
        f"the directory is named {staging_dir.name!r}, but the copied assembly's own "
        f"source triple derives {expected_final_name!r}; a final-media build is never "
        "trusted under a name its sources do not derive"
    )
    return [
        problem for problem in audit_media_encode_directory(staging_dir) if problem != expected_seam
    ]


__all__ = [
    "HANDLED_REFUSALS",
    "begin_media_encode_staging",
    "publish_media_encode",
    "write_audio_snapshot",
    "write_final_media",
    "write_media_encode_manifest",
    "write_provenance_copies",
    "write_sidecar_copies",
]
