"""Filesystem ownership, atomic writes and terminal publication for one caption serialization.

The only Phase 34 module permitted to hold ``open(``, ``os.open``, ``os.replace``,
``os.fsync``, ``os.close``, ``shutil.`` or ``.lstat(`` -- confined here so no other module,
including the CLI and the publisher, can ever improvise a filesystem primitive of its own.
``shutil.rmtree`` appears exactly once, inside :func:`discard_owned_staging`. ``os.replace``
appears exactly twice, inside :func:`write_atomically` and :func:`publish_owned_staging`.

``_require_direct_parent`` is called first, before any other operation, in every function
here that touches a directory beneath an ``expected_parent``: lexical ``os.path.abspath``
equality proves two path *strings* agree; it cannot prove the path leads where it says.
``Path.resolve()`` is deliberately never used anywhere in this module: resolving would
follow the very indirection this law exists to refuse.

Every Phase 34-owned regular file -- staged or published -- must satisfy
``lstat().st_nlink == 1``: a hardlink is neither a symlink nor a junction, passes every
content and digest check, and is the one thing this module's indirection checks alone
cannot catch. ``_require_single_link_regular_file`` is called on every owned regular file
inside :func:`require_owned_staging`, so cleanup and publication authority are never
granted over a directory containing a shared inode.

A caption serialization tree is deliberately FLAT: exactly four owned regular files and no
subdirectory of any kind -- a directory entry inside staging is refused outright.
"""

import os
import shutil
from pathlib import Path

from living_diorama.caption_serialization.caption_serialization_spec import (
    CAPTION_PLAN_COPY_FILENAME,
    CAPTION_SERIALIZATION_MANIFEST_FILENAME,
    SRT_SUFFIX,
    VTT_SUFFIX,
    WRITING_SUFFIX,
)


class CaptionSerializationDirectoryRefused(RuntimeError):
    """The destination or staging directory's state refuses this serialization."""


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
        CaptionSerializationDirectoryRefused: If ``expected_parent`` is a symlink or a
            junction.
    """
    if _is_path_indirection(expected_parent):
        raise CaptionSerializationDirectoryRefused(
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
        CaptionSerializationDirectoryRefused: If the entry is not a regular file, or its
            link count is not exactly one.
    """
    if not path.is_file():
        raise CaptionSerializationDirectoryRefused(f"{description} is not a regular file")
    links = _regular_file_link_count(path)
    if links != 1:
        raise CaptionSerializationDirectoryRefused(
            f"{description} has {links} directory entries pointing at it; a Phase 34 owned "
            "regular file must be an independent physical copy with exactly one directory "
            "entry, never a hardlink"
        )


def _owned_staging_filenames(episode_id: str) -> frozenset[str]:
    """Return every filename a Phase 34 staging tree may hold for this episode id."""
    owned = (
        CAPTION_SERIALIZATION_MANIFEST_FILENAME,
        CAPTION_PLAN_COPY_FILENAME,
        f"{episode_id}{SRT_SUFFIX}",
        f"{episode_id}{VTT_SUFFIX}",
    )
    return frozenset({*owned, *(name + WRITING_SUFFIX for name in owned)})


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
    very indirection this law exists to refuse. Every owned regular file must additionally
    satisfy ``st_nlink == 1`` before this tree is treated as wholly Phase 34's own.

    Raises:
        CaptionSerializationDirectoryRefused: If the expected parent, the name or the
            location does not match exactly, if the directory or any entry inside it is a
            symlink or junction, if any entry is a directory or is not one this phase's own
            contract accounts for, or if any owned regular file is not an independent
            physical copy.
    """
    _require_direct_parent(expected_parent)
    if staging_dir.name != expected_name:
        raise CaptionSerializationDirectoryRefused(
            f"staging directory name {staging_dir.name!r} does not match the expected "
            f"{expected_name!r}"
        )
    if os.path.abspath(staging_dir.parent) != os.path.abspath(expected_parent):
        raise CaptionSerializationDirectoryRefused(
            f"staging directory {staging_dir} does not sit directly under the expected "
            f"output root {expected_parent}; ownership is proven by exact location, not "
            "name alone"
        )
    if _is_path_indirection(staging_dir):
        raise CaptionSerializationDirectoryRefused(
            f"{staging_dir} is a symlink or junction; this phase never follows an "
            "indirection and never deletes through one"
        )
    if not staging_dir.is_dir():
        raise CaptionSerializationDirectoryRefused(f"{staging_dir} is not a directory")

    permitted = _owned_staging_filenames(episode_id)
    for entry in sorted(staging_dir.iterdir()):
        if _is_path_indirection(entry):
            raise CaptionSerializationDirectoryRefused(
                f"{entry} is a symlink or junction inside staging"
            )
        if entry.is_dir():
            raise CaptionSerializationDirectoryRefused(
                f"{entry} is a directory inside staging; a caption serialization tree is flat"
            )
        if entry.name not in permitted:
            raise CaptionSerializationDirectoryRefused(
                f"{entry} is not owned by this phase's staging"
            )
        _require_single_link_regular_file(entry, f"staged file {entry}")


def discard_owned_staging(
    staging_dir: Path,
    *,
    expected_parent: Path,
    expected_name: str,
    episode_id: str,
) -> None:
    """Remove a staging tree, but only once it is proven wholly this phase's own.

    This is the single ``shutil.rmtree`` call site in all of Phase 34. The
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
        raise CaptionSerializationDirectoryRefused(
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
    tree, and the staged-directory fsync performed before publication says nothing about
    that entry's own durability. A failed or unsupported attempt never turns a successfully
    published final directory into a rollback attempt -- atomic publication remains the
    property of ``os.replace`` alone, and no guaranteed final-name durability is claimed on
    platforms where directory fsync is unsupported.

    Raises:
        CaptionSerializationDirectoryRefused: If either name or either location is not
            exactly as expected, if the staging tree is not provably this phase's own, or if
            anything at all exists at the destination.
        OSError: If the terminal rename itself fails.
    """
    _require_direct_parent(expected_parent)
    if staging_dir.name != expected_staging_name:
        raise CaptionSerializationDirectoryRefused(
            f"staging directory name {staging_dir.name!r} does not match the expected "
            f"{expected_staging_name!r}"
        )
    if final_dir.name != expected_final_name:
        raise CaptionSerializationDirectoryRefused(
            f"final directory name {final_dir.name!r} does not match the expected "
            f"{expected_final_name!r}"
        )
    if os.path.abspath(staging_dir.parent) != os.path.abspath(expected_parent):
        raise CaptionSerializationDirectoryRefused(
            f"staging directory {staging_dir} does not sit directly under the expected "
            f"output root {expected_parent}"
        )
    if os.path.abspath(final_dir.parent) != os.path.abspath(expected_parent):
        raise CaptionSerializationDirectoryRefused(
            f"final directory {final_dir} does not sit directly under the expected output "
            f"root {expected_parent}"
        )
    if _is_path_indirection(staging_dir):
        raise CaptionSerializationDirectoryRefused(
            f"{staging_dir} is a symlink or junction; this phase never publishes through one"
        )

    require_owned_staging(
        staging_dir,
        expected_parent=expected_parent,
        expected_name=expected_staging_name,
        episode_id=episode_id,
    )

    if _is_path_indirection(final_dir):
        raise CaptionSerializationDirectoryRefused(
            f"{final_dir} is a symlink or junction; this phase never publishes through an "
            "indirection, dangling or not"
        )
    if final_dir.exists():
        raise CaptionSerializationDirectoryRefused(
            f"{final_dir} already exists; nothing is deleted or overwritten to publish a "
            "caption serialization"
        )

    os.replace(staging_dir, final_dir)
    fsync_directory(expected_parent)


__all__ = [
    "CaptionSerializationDirectoryRefused",
    "discard_owned_staging",
    "fsync_directory",
    "publish_owned_staging",
    "require_owned_staging",
    "write_atomically",
]
