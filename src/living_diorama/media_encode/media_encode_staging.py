"""Filesystem ownership, atomic writes and terminal publication for one final-media build.

The only Phase 35 module permitted to hold ``open(``, ``os.open``, ``os.replace``,
``os.fsync``, ``os.close``, ``shutil.`` or ``.lstat(`` -- confined here so no other module,
the executor script included, can ever improvise a filesystem primitive of its own.
``shutil.rmtree`` appears exactly once, inside :func:`discard_owned_staging`. ``os.replace``
appears exactly twice, inside :func:`write_atomically` and :func:`publish_owned_staging`.

``_require_direct_parent`` is called first, before any other operation, in every function
here that touches a directory beneath an ``expected_parent``; ``Path.resolve()`` is
deliberately never used anywhere in this module. Every Phase 35-owned regular file --
staged or published, the working ``.encoding`` temporaries included -- must satisfy
``lstat().st_nlink == 1``.

The staging whitelist deliberately admits every working temporary this phase can create --
the tool-written encode outputs, the executor-built preflight WAV and the audio snapshot --
so a crash at ANY point leaves a tree the next run's discard provably owns and removes;
under the narrower Phase 33 template those leftovers would refuse ownership and wedge
recovery until human cleanup.
"""

import os
import shutil
from pathlib import Path

from living_diorama.caption_serialization.caption_serialization_spec import (
    SRT_SUFFIX,
    VTT_SUFFIX,
    sidecar_filename,
)
from living_diorama.media_encode.media_encode_spec import (
    ENCODING_SUFFIX,
    MEDIA_ENCODE_MANIFEST_FILENAME,
    PREFLIGHT_AUDIO_FILENAME,
    PREFLIGHT_MEDIA_FILENAME,
    PROVENANCE_DIRECTORY,
    PROVENANCE_DIRECTORY_ENTRIES,
    SNAPSHOT_AUDIO_FILENAME,
    WRITING_SUFFIX,
    media_filename,
)


class MediaEncodeDirectoryRefused(RuntimeError):
    """The destination or staging directory's state refuses this final-media build."""


def _is_path_indirection(path: Path) -> bool:
    """Return whether this path is a symlink or a Windows junction.

    Neither is ever followed and neither is ever deleted through -- every caller of this
    helper refuses outright on ``True``.
    """
    return path.is_symlink() or path.is_junction()


def _require_direct_parent(expected_parent: Path) -> None:
    """Refuse unless the expected parent is a real directory entry, not a link.

    If the expected parent is itself a symlink or a Windows junction, every lexical
    ``os.path.abspath`` check downstream would still pass while ``mkdir``, ``iterdir``,
    ``rmtree``, ``open``, ``fsync`` and ``os.replace`` all act on whatever it points at.
    This phase never traverses, deletes or publishes through an indirection.

    Raises:
        MediaEncodeDirectoryRefused: If ``expected_parent`` is a symlink or a junction.
    """
    if _is_path_indirection(expected_parent):
        raise MediaEncodeDirectoryRefused(
            f"the expected output root {expected_parent} is a symlink or junction; this "
            "phase never traverses, deletes or publishes through an indirection"
        )


def _regular_file_link_count(path: Path) -> int:
    """Return the number of directory entries pointing at this regular file.

    ``Path.lstat()`` is used deliberately: it reads the entry's own metadata without
    following an indirection, exactly as this module never follows one anywhere else.
    ``Path.resolve()`` is never used.

    Raises:
        OSError: If the entry cannot be stat'ed.
    """
    return path.lstat().st_nlink


def _require_single_link_regular_file(path: Path, description: str) -> None:
    """Refuse unless this entry is a regular file held by exactly one directory entry.

    Called only after the caller has already refused ``path`` as a symlink or a junction.
    A hardlink is neither, and passes every content check, so this is the only mechanism
    that distinguishes an independent physical copy from a shared inode.

    Raises:
        MediaEncodeDirectoryRefused: If the entry is not a regular file, or its link
            count is not exactly one.
    """
    if not path.is_file():
        raise MediaEncodeDirectoryRefused(f"{description} is not a regular file")
    links = _regular_file_link_count(path)
    if links != 1:
        raise MediaEncodeDirectoryRefused(
            f"{description} has {links} directory entries pointing at it; a Phase 35 owned "
            "regular file must be an independent physical copy with exactly one directory "
            "entry, never a hardlink"
        )


def _owned_staging_top_level(episode_id: str) -> frozenset[str]:
    """Return every top-level name a Phase 35 staging tree may hold for this episode id."""
    media_name = media_filename(episode_id)
    owned_files = (
        MEDIA_ENCODE_MANIFEST_FILENAME,
        media_name,
        sidecar_filename(episode_id, SRT_SUFFIX),
        sidecar_filename(episode_id, VTT_SUFFIX),
    )
    return frozenset(
        {
            *owned_files,
            *(name + WRITING_SUFFIX for name in owned_files),
            media_name + ENCODING_SUFFIX,
            PREFLIGHT_MEDIA_FILENAME,
            PREFLIGHT_AUDIO_FILENAME,
            PREFLIGHT_AUDIO_FILENAME + WRITING_SUFFIX,
            SNAPSHOT_AUDIO_FILENAME,
            SNAPSHOT_AUDIO_FILENAME + WRITING_SUFFIX,
            PROVENANCE_DIRECTORY,
        }
    )


def require_owned_staging(
    staging_dir: Path,
    *,
    expected_parent: Path,
    expected_name: str,
    episode_id: str,
) -> None:
    """Refuse unless every entry in this staging tree is positively this phase's own.

    Never deletes, never modifies, never follows an indirection. Location is proved
    lexically, via ``os.path.abspath``, which normalizes without traversing a symlink or
    junction -- ``Path.resolve()`` is never used here, because resolving would follow the
    very indirection this law exists to refuse. Every owned regular file -- the manifest,
    the episode file, both sidecars, both provenance witnesses, and every working
    temporary -- must additionally satisfy ``st_nlink == 1`` before this tree is treated
    as wholly Phase 35's own.

    Raises:
        MediaEncodeDirectoryRefused: If the expected parent, the name or the location
            does not match exactly, if the directory or any entry inside it is a symlink
            or junction, if any entry anywhere is not one this phase's own contract
            accounts for, or if any owned regular file is not an independent physical
            copy.
    """
    _require_direct_parent(expected_parent)
    if staging_dir.name != expected_name:
        raise MediaEncodeDirectoryRefused(
            f"staging directory name {staging_dir.name!r} does not match the expected "
            f"{expected_name!r}"
        )
    if os.path.abspath(staging_dir.parent) != os.path.abspath(expected_parent):
        raise MediaEncodeDirectoryRefused(
            f"staging directory {staging_dir} does not sit directly under the expected "
            f"output root {expected_parent}; ownership is proven by exact location, not "
            "name alone"
        )
    if _is_path_indirection(staging_dir):
        raise MediaEncodeDirectoryRefused(
            f"{staging_dir} is a symlink or junction; this phase never follows an "
            "indirection and never deletes through one"
        )
    if not staging_dir.is_dir():
        raise MediaEncodeDirectoryRefused(f"{staging_dir} is not a directory")

    permitted_top_level = _owned_staging_top_level(episode_id)
    for entry in sorted(staging_dir.iterdir()):
        if _is_path_indirection(entry):
            raise MediaEncodeDirectoryRefused(f"{entry} is a symlink or junction inside staging")
        if entry.name not in permitted_top_level:
            raise MediaEncodeDirectoryRefused(f"{entry} is not owned by this phase's staging")
        if entry.name == PROVENANCE_DIRECTORY:
            if not entry.is_dir():
                raise MediaEncodeDirectoryRefused(f"{entry} is expected to be a directory")
        else:
            _require_single_link_regular_file(entry, f"staged file {entry}")

    provenance_dir = staging_dir / PROVENANCE_DIRECTORY
    if provenance_dir.exists():
        if _is_path_indirection(provenance_dir):
            raise MediaEncodeDirectoryRefused(f"{provenance_dir} is a symlink or junction")
        permitted_provenance = {
            *PROVENANCE_DIRECTORY_ENTRIES,
            *(name + WRITING_SUFFIX for name in PROVENANCE_DIRECTORY_ENTRIES),
        }
        for entry in sorted(provenance_dir.iterdir()):
            if _is_path_indirection(entry):
                raise MediaEncodeDirectoryRefused(
                    f"{entry} is a symlink or junction inside provenance/"
                )
            if entry.is_dir():
                raise MediaEncodeDirectoryRefused(
                    f"{entry} is a directory inside provenance/, never permitted"
                )
            if entry.name not in permitted_provenance:
                raise MediaEncodeDirectoryRefused(
                    f"{entry} is not an owned provenance file for this final-media build"
                )
            _require_single_link_regular_file(entry, f"staged provenance file {entry}")


def discard_owned_staging(
    staging_dir: Path,
    *,
    expected_parent: Path,
    expected_name: str,
    episode_id: str,
) -> None:
    """Remove a staging tree, but only once it is proven wholly this phase's own.

    This is the single ``shutil.rmtree`` call site in all of Phase 35. The
    parent-indirection check runs first, because ``staging_dir.exists()`` below traverses
    ``expected_parent`` -- delegating that check to :func:`require_owned_staging` alone
    would be too late. ``staging_dir``'s own indirection is checked before
    ``staging_dir.exists()`` for the same reason: ``Path.exists()`` follows a symlink and
    reports based on the *target*, so a dangling staging symlink (target absent) would make
    ``exists()`` return ``False`` and this function would return having inspected nothing --
    the indirection itself must be refused before that short-circuit is ever reached.

    A staging tree containing even one hardlinked owned regular file is never deleted:
    ``require_owned_staging`` refuses to prove ownership over a shared inode, so this
    function's ``rmtree`` is never reached for that tree.
    """
    _require_direct_parent(expected_parent)
    if _is_path_indirection(staging_dir):
        raise MediaEncodeDirectoryRefused(
            f"{staging_dir} is a symlink or junction; this phase never follows an "
            "indirection and never deletes through one"
        )
    if not staging_dir.exists():
        return
    require_owned_staging(
        staging_dir,
        expected_parent=expected_parent,
        expected_name=expected_name,
        episode_id=episode_id,
    )
    shutil.rmtree(staging_dir)


def write_atomically(path: Path, payload: bytes) -> None:
    """Write bytes atomically: a ``.writing`` temp, flush, fsync, then ``os.replace``."""
    temporary = path.with_name(path.name + WRITING_SUFFIX)
    with open(temporary, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def fsync_file(path: Path) -> None:
    """Fsync one existing regular file's own contents, for durability before capture.

    Used on the tool-written encode temporary before its single capture: the encoder's
    own buffers were flushed at exit, and this pins the bytes the capture will read.

    Raises:
        OSError: If the file cannot be opened or synced.
    """
    descriptor = os.open(path, os.O_RDWR)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read_file_bytes(path: Path) -> bytes:
    """Return one owned file's bytes -- THE one read of a single-capture observation.

    Confined here with the other primitives so every capture site is auditable in one
    module; the caller keeps the returned bytes as its only authority thereafter.

    Raises:
        OSError: If the file cannot be read.
    """
    with open(path, "rb") as handle:
        return handle.read()


def remove_owned_temporary(path: Path, *, staging_dir: Path) -> None:
    """Unlink one working temporary that provably sits inside this run's own staging.

    The narrow deletion the encode step needs -- the captured tool output and the
    verified snapshot -- scoped to a direct child of the staging tree; everything else
    still goes through :func:`discard_owned_staging`.

    Raises:
        MediaEncodeDirectoryRefused: If the path is an indirection, is not a direct child
            of the staging tree, or is not a regular file.
        OSError: If the unlink itself fails.
    """
    if _is_path_indirection(path):
        raise MediaEncodeDirectoryRefused(
            f"{path} is a symlink or junction; this phase never deletes through one"
        )
    if os.path.abspath(path.parent) != os.path.abspath(staging_dir):
        raise MediaEncodeDirectoryRefused(
            f"{path} does not sit directly inside this run's own staging {staging_dir}"
        )
    if not path.is_file():
        raise MediaEncodeDirectoryRefused(f"{path} is not a regular file")
    os.unlink(path)


def fsync_directory(path: Path) -> None:
    """Best-effort fsync of a directory's own entry, for durability only.

    Not every platform supports fsyncing a directory descriptor; when it is unsupported the
    attempt is skipped rather than treated as a failure -- the atomicity of the terminal
    ``os.replace`` never depends on it.
    """
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def publish_owned_staging(
    staging_dir: Path,
    final_dir: Path,
    *,
    expected_parent: Path,
    expected_staging_name: str,
    expected_final_name: str,
    episode_id: str,
) -> None:
    """Publish a proven-own staging tree onto its final name, atomically, once.

    No deletion. No overwrite. No repair. ``final_dir.exists()`` alone is insufficient to
    detect a dangling destination symlink -- it follows the link and would report ``False``
    -- so ``final_dir``'s own indirection is refused first, before ``final_dir.exists()`` is
    ever consulted: a destination indirection refuses without being followed, dangling or
    not.

    Immediately after the terminal rename, a best-effort ``fsync_directory(expected_parent)``
    is attempted: the rename changes an entry in ``expected_parent``, not in the staging
    tree. A failed or unsupported attempt never turns a successfully published final
    directory into a rollback attempt -- atomic publication remains the property of
    ``os.replace`` alone.

    Raises:
        MediaEncodeDirectoryRefused: If either name or either location is not exactly as
            expected, if the staging tree is not provably this phase's own, or if anything
            at all exists at the destination.
        OSError: If the terminal rename itself fails.
    """
    _require_direct_parent(expected_parent)
    if staging_dir.name != expected_staging_name:
        raise MediaEncodeDirectoryRefused(
            f"staging directory name {staging_dir.name!r} does not match the expected "
            f"{expected_staging_name!r}"
        )
    if final_dir.name != expected_final_name:
        raise MediaEncodeDirectoryRefused(
            f"final directory name {final_dir.name!r} does not match the expected "
            f"{expected_final_name!r}"
        )
    if os.path.abspath(staging_dir.parent) != os.path.abspath(expected_parent):
        raise MediaEncodeDirectoryRefused(
            f"staging directory {staging_dir} does not sit directly under the expected "
            f"output root {expected_parent}"
        )
    if os.path.abspath(final_dir.parent) != os.path.abspath(expected_parent):
        raise MediaEncodeDirectoryRefused(
            f"final directory {final_dir} does not sit directly under the expected output "
            f"root {expected_parent}"
        )
    if _is_path_indirection(staging_dir):
        raise MediaEncodeDirectoryRefused(
            f"{staging_dir} is a symlink or junction; this phase never publishes through one"
        )

    require_owned_staging(
        staging_dir,
        expected_parent=expected_parent,
        expected_name=expected_staging_name,
        episode_id=episode_id,
    )

    if _is_path_indirection(final_dir):
        raise MediaEncodeDirectoryRefused(
            f"{final_dir} is a symlink or junction; this phase never publishes through an "
            "indirection, dangling or not"
        )
    if final_dir.exists():
        raise MediaEncodeDirectoryRefused(
            f"{final_dir} already exists; nothing is deleted or overwritten to publish a "
            "final-media build"
        )

    os.replace(staging_dir, final_dir)
    fsync_directory(expected_parent)


__all__ = [
    "MediaEncodeDirectoryRefused",
    "discard_owned_staging",
    "fsync_directory",
    "fsync_file",
    "publish_owned_staging",
    "read_file_bytes",
    "remove_owned_temporary",
    "require_owned_staging",
    "write_atomically",
]
