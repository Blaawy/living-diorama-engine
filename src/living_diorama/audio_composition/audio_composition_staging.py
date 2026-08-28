"""Filesystem ownership, atomic writes and terminal publication for one composition.

The only Phase 31 module permitted to hold ``open(``, ``os.replace``,
``os.fsync`` or ``shutil.`` -- confined here so no other module, including
the CLI and the publisher, can ever improvise a filesystem primitive of its
own. ``shutil.rmtree`` appears exactly once, inside
:func:`discard_owned_staging`. ``os.replace`` appears exactly twice, inside
:func:`write_atomically` and :func:`publish_owned_staging`.

``_require_direct_parent`` is called first, before any other operation, in
every function here that touches a directory beneath an ``expected_parent``:
lexical ``os.path.abspath`` equality proves two path *strings* agree; it
cannot prove the path leads where it says. ``Path.resolve()`` is
deliberately never used anywhere in this module: resolving would follow the
very indirection this law exists to refuse.
"""

import os
import shutil
from pathlib import Path
from typing import Final

from living_diorama.audio_composition.audio_composition_spec import (
    AUDIO_COMPOSITION_MANIFEST_FILENAME,
    AUDIO_DIRECTORY,
    AUDIO_TRACK_PLAN_FILENAME,
    EPISODE_AUDIO_FILENAME,
    VOICE_MANIFEST_FILENAME,
    WRITING_SUFFIX,
)

_DOCUMENT_FILENAMES: Final = (
    AUDIO_TRACK_PLAN_FILENAME,
    VOICE_MANIFEST_FILENAME,
    AUDIO_COMPOSITION_MANIFEST_FILENAME,
)


class CompositionDirectoryRefused(RuntimeError):
    """The destination or staging directory's state refuses this composition."""


def _is_path_indirection(path: Path) -> bool:
    """Return whether this path is a symlink or a Windows junction.

    Neither is ever followed and neither is ever deleted through -- every
    caller of this helper refuses outright on ``True``.
    """
    return path.is_symlink() or path.is_junction()


def _require_direct_parent(expected_parent: Path) -> None:
    """Refuse unless the expected parent is a real directory entry, not a link.

    If the expected parent is itself a symlink or a Windows junction, every
    lexical ``os.path.abspath`` check downstream would still pass while
    ``mkdir``, ``iterdir``, ``rmtree``, ``open``, ``fsync`` and
    ``os.replace`` all act on whatever it points at. This phase never
    traverses, deletes or publishes through an indirection.

    Raises:
        CompositionDirectoryRefused: If ``expected_parent`` is a symlink or
            a junction.
    """
    if _is_path_indirection(expected_parent):
        raise CompositionDirectoryRefused(
            f"the expected output root {expected_parent} is a symlink or junction; this phase "
            "never traverses, deletes or publishes through an indirection"
        )


def require_owned_staging(
    staging_dir: Path,
    *,
    expected_parent: Path,
    expected_name: str,
) -> None:
    """Refuse unless every entry in this staging tree is positively this phase's own.

    Never deletes, never modifies, never follows an indirection. Location is
    proved lexically, via ``os.path.abspath``, which normalizes without
    traversing a symlink or junction -- ``Path.resolve()`` is never used
    here, because resolving would follow the very indirection this law
    exists to refuse.

    Raises:
        CompositionDirectoryRefused: If the expected parent, the name or the
            location does not match exactly, if the directory or any entry
            inside it (including inside ``audio/``) is a symlink or
            junction, or if any entry anywhere is not one this phase's own
            contract accounts for.
    """
    _require_direct_parent(expected_parent)
    if staging_dir.name != expected_name:
        raise CompositionDirectoryRefused(
            f"staging directory name {staging_dir.name!r} does not match the expected "
            f"{expected_name!r}"
        )
    if os.path.abspath(staging_dir.parent) != os.path.abspath(expected_parent):
        raise CompositionDirectoryRefused(
            f"staging directory {staging_dir} does not sit directly under the expected output "
            f"root {expected_parent}; ownership is proven by exact location, not name alone"
        )
    if _is_path_indirection(staging_dir):
        raise CompositionDirectoryRefused(
            f"{staging_dir} is a symlink or junction; this phase never follows an indirection "
            "and never deletes through one"
        )
    if not staging_dir.is_dir():
        raise CompositionDirectoryRefused(f"{staging_dir} is not a directory")

    permitted_top_level = {
        AUDIO_DIRECTORY,
        *_DOCUMENT_FILENAMES,
        *(name + WRITING_SUFFIX for name in _DOCUMENT_FILENAMES),
    }
    for entry in sorted(staging_dir.iterdir()):
        if _is_path_indirection(entry):
            raise CompositionDirectoryRefused(f"{entry} is a symlink or junction inside staging")
        if entry.name not in permitted_top_level:
            raise CompositionDirectoryRefused(f"{entry} is not owned by this phase's staging")
        if entry.name == AUDIO_DIRECTORY:
            if not entry.is_dir():
                raise CompositionDirectoryRefused(f"{entry} is expected to be a directory")
        elif not entry.is_file():
            raise CompositionDirectoryRefused(f"{entry} is expected to be a regular file")

    audio_dir = staging_dir / AUDIO_DIRECTORY
    if audio_dir.exists():
        if _is_path_indirection(audio_dir):
            raise CompositionDirectoryRefused(f"{audio_dir} is a symlink or junction")
        permitted_audio = {EPISODE_AUDIO_FILENAME, EPISODE_AUDIO_FILENAME + WRITING_SUFFIX}
        for entry in sorted(audio_dir.iterdir()):
            if _is_path_indirection(entry):
                raise CompositionDirectoryRefused(f"{entry} is a symlink or junction inside audio/")
            if entry.is_dir():
                raise CompositionDirectoryRefused(
                    f"{entry} is a directory inside audio/, never permitted"
                )
            if entry.name not in permitted_audio:
                raise CompositionDirectoryRefused(
                    f"{entry} is not an owned audio file for this composition"
                )


def discard_owned_staging(
    staging_dir: Path,
    *,
    expected_parent: Path,
    expected_name: str,
) -> None:
    """Remove a staging tree, but only once it is proven wholly this phase's own.

    This is the single ``shutil.rmtree`` call site in all of Phase 31. The
    parent-indirection check runs first, because ``staging_dir.exists()``
    below traverses ``expected_parent`` -- delegating that check to
    :func:`require_owned_staging` alone would be too late. ``staging_dir``'s
    own indirection is checked before ``staging_dir.exists()`` for the same
    reason: ``Path.exists()`` follows a symlink and reports based on the
    *target*, so a dangling staging symlink (target absent) would make
    ``exists()`` return ``False`` and this function would return having
    inspected nothing -- the indirection itself must be refused before that
    short-circuit is ever reached.
    """
    _require_direct_parent(expected_parent)
    if _is_path_indirection(staging_dir):
        raise CompositionDirectoryRefused(
            f"{staging_dir} is a symlink or junction; this phase never follows an indirection "
            "and never deletes through one"
        )
    if not staging_dir.exists():
        return
    require_owned_staging(staging_dir, expected_parent=expected_parent, expected_name=expected_name)
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

    Not every platform supports fsyncing a directory descriptor; when it is
    unsupported the attempt is skipped rather than treated as a failure --
    the atomicity of the terminal ``os.replace`` never depends on it.
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
) -> None:
    """Publish a proven-own staging tree onto its final name, atomically, once.

    No deletion. No overwrite. No repair. ``final_dir.exists()`` alone is
    insufficient to detect a dangling destination symlink -- it follows the
    link and would report ``False`` -- so ``final_dir``'s own indirection is
    refused first, before ``final_dir.exists()`` is ever consulted: a
    destination indirection refuses without being followed, dangling or not.

    Raises:
        CompositionDirectoryRefused: If either name or either location is
            not exactly as expected, if the staging tree is not provably
            this phase's own, or if anything at all exists at the
            destination.
        OSError: If the terminal rename itself fails.
    """
    _require_direct_parent(expected_parent)
    if staging_dir.name != expected_staging_name:
        raise CompositionDirectoryRefused(
            f"staging directory name {staging_dir.name!r} does not match the expected "
            f"{expected_staging_name!r}"
        )
    if final_dir.name != expected_final_name:
        raise CompositionDirectoryRefused(
            f"final directory name {final_dir.name!r} does not match the expected "
            f"{expected_final_name!r}"
        )
    if os.path.abspath(staging_dir.parent) != os.path.abspath(expected_parent):
        raise CompositionDirectoryRefused(
            f"staging directory {staging_dir} does not sit directly under the expected output "
            f"root {expected_parent}"
        )
    if os.path.abspath(final_dir.parent) != os.path.abspath(expected_parent):
        raise CompositionDirectoryRefused(
            f"final directory {final_dir} does not sit directly under the expected output root "
            f"{expected_parent}"
        )
    if _is_path_indirection(staging_dir):
        raise CompositionDirectoryRefused(
            f"{staging_dir} is a symlink or junction; this phase never publishes through one"
        )

    require_owned_staging(
        staging_dir, expected_parent=expected_parent, expected_name=expected_staging_name
    )

    if _is_path_indirection(final_dir):
        raise CompositionDirectoryRefused(
            f"{final_dir} is a symlink or junction; this phase never publishes through an "
            "indirection, dangling or not"
        )
    if final_dir.exists():
        raise CompositionDirectoryRefused(
            f"{final_dir} already exists; nothing is deleted or overwritten to publish a "
            "composition"
        )

    os.replace(staging_dir, final_dir)


__all__ = [
    "CompositionDirectoryRefused",
    "discard_owned_staging",
    "fsync_directory",
    "publish_owned_staging",
    "require_owned_staging",
    "write_atomically",
]
