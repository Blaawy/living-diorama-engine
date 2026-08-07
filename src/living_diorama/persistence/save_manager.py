"""Atomic, verified, episode-scoped saves on the local filesystem."""

import ctypes
import errno
import os
import platform
import shutil
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from living_diorama import __version__ as ENGINE_VERSION
from living_diorama.events import EventLog
from living_diorama.events.event import JsonValue
from living_diorama.memory import WorldMemory
from living_diorama.memory._integrity import (
    snapshot_event_log,
    snapshot_world_memory,
    validate_memory_transition_events,
)
from living_diorama.memory.world_memory import _is_runtime_instance
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.persistence.schema.world_schema_v1 import (
    EPISODE_FILES,
    EPISODE_FORMAT,
    EVENT_LOG_FILE,
    MANIFEST_FILE,
    PAYLOAD_FILES,
    SCHEMA_VERSION,
    WORLD_MEMORY_FILE,
    WORLD_STATE_FILE,
    EpisodeManifest,
    FileMetadata,
    episode_directory_name,
    require_exact_int,
)
from living_diorama.persistence.serializers.event_serializer import (
    deserialize_event_log,
    serialize_event_log,
)
from living_diorama.persistence.serializers.world_memory_serializer import (
    deserialize_world_memory,
    serialize_world_memory,
)
from living_diorama.persistence.serializers.world_serializer import (
    deserialize_world,
    entity_counts,
    require_entity_counts,
    serialize_world,
)
from living_diorama.simulation.world import World

_TEMPORARY_PREFIX = ".episode_staging_"
"""Prefix for the staging directory, created beside its final destination."""

_AT_FDCWD = -100
"""Resolve relative paths against the current directory, as ``renameat2`` expects."""

_RENAME_NOREPLACE = 1 << 0
"""Linux flag making a rename fail rather than replace an existing destination."""

_RENAME_EXCL = 1 << 2
"""The macOS equivalent of ``RENAME_NOREPLACE``."""

_LINUX_RENAMEAT2_SYSCALLS = {
    "x86_64": 316,
    "aarch64": 276,
    "armv7l": 382,
    "armv8l": 382,
    "i386": 353,
    "i686": 353,
    "ppc64le": 357,
    "s390x": 347,
}
"""Syscall numbers for ``renameat2`` where glibc predates the wrapper."""


def _rename_no_replace(source: Path, destination: Path) -> None:
    """Rename a directory into place, failing if the destination already exists.

    ``os.rename`` is not usable here. On POSIX it will silently replace an empty
    destination directory, so a rival episode appearing between the existence
    check and the rename would be overwritten -- exactly the race this phase
    forbids. A plain check-then-rename cannot close that window, so the
    no-replace guarantee is taken from the operating system instead.

    Windows already has these semantics natively. Linux and macOS expose them
    through ``renameat2`` and ``renamex_np``. Anywhere else this fails loudly
    rather than quietly falling back to a replacing rename: a save that might
    silently destroy a published episode is worse than a save that refuses.

    Raises:
        FileExistsError: If the destination exists.
        OSError: If the platform cannot guarantee no-replace publication, or the
            rename fails for any other reason.
    """
    if sys.platform == "win32":  # pragma: no cover - platform specific
        # MoveFileExW without MOVEFILE_REPLACE_EXISTING; already no-replace.
        os.rename(source, destination)
        return

    libc = ctypes.CDLL(None, use_errno=True)
    encoded_source = os.fsencode(source)
    encoded_destination = os.fsencode(destination)

    result: int

    if sys.platform == "linux":
        result = _linux_renameat2(libc, encoded_source, encoded_destination)
    elif sys.platform == "darwin":  # pragma: no cover - platform specific
        rename_exclusive = getattr(libc, "renamex_np", None)
        if rename_exclusive is None:
            raise OSError(
                "atomic no-replace publication is unavailable: this macOS build has no renamex_np"
            )
        rename_exclusive.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename_exclusive.restype = ctypes.c_int
        result = rename_exclusive(encoded_source, encoded_destination, _RENAME_EXCL)
    else:  # pragma: no cover - platform specific
        raise OSError(
            f"atomic no-replace directory publication is not available on {sys.platform!r}; "
            "refusing to publish with a rename that could replace an existing episode"
        )

    if result == 0:
        return
    code = ctypes.get_errno()
    if code in (errno.EEXIST, errno.ENOTEMPTY):
        raise FileExistsError(code, os.strerror(code), str(destination))
    if code in (errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP):
        raise OSError(
            code,
            "the filesystem or kernel does not support atomic no-replace rename; "
            "refusing to publish without it",
            str(destination),
        )
    raise OSError(code, os.strerror(code), str(destination))


def _linux_renameat2(libc: ctypes.CDLL, source: bytes, destination: bytes) -> int:
    """Call ``renameat2`` with ``RENAME_NOREPLACE``, directly if glibc lacks it."""
    wrapper = getattr(libc, "renameat2", None)
    if wrapper is not None:
        wrapper.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        wrapper.restype = ctypes.c_int
        return int(wrapper(_AT_FDCWD, source, _AT_FDCWD, destination, _RENAME_NOREPLACE))

    number = _LINUX_RENAMEAT2_SYSCALLS.get(platform.machine())  # pragma: no cover
    if number is None:  # pragma: no cover - depends on the host architecture
        raise OSError(
            "atomic no-replace publication is unavailable: this C library has no "
            f"renameat2 and the syscall number for {platform.machine()!r} is unknown"
        )
    libc.syscall.restype = ctypes.c_long  # pragma: no cover
    return int(  # pragma: no cover
        libc.syscall(
            ctypes.c_long(number),
            ctypes.c_int(_AT_FDCWD),
            ctypes.c_char_p(source),
            ctypes.c_int(_AT_FDCWD),
            ctypes.c_char_p(destination),
            ctypes.c_uint(_RENAME_NOREPLACE),
        )
    )


@dataclass(frozen=True, slots=True)
class LoadedEpisode:
    """Everything one verified episode directory contained.

    Attributes:
        world: The reconstructed world, a new object sharing nothing with the
            world that was saved.
        event_log: The episode's history, in its original append order.
        world_memory: The cumulative durable history, checkpointed to this
            episode's verified manifest.
        manifest: The verified metadata describing the episode.
    """

    world: World
    event_log: EventLog
    world_memory: WorldMemory
    manifest: EpisodeManifest


class SaveManager:
    """Writes and reads immutable episode directories under one save root.

    An episode directory is published by renaming a fully written staging
    directory into place, so a reader never sees a partial episode: either the
    directory is absent, or it is complete and internally verified.

    Once published, an episode is never touched again. Saving over one raises
    rather than merging, repairing, or overwriting -- a later episode's whole
    claim to legitimacy is that its parent still hashes to what it said it did.
    """

    __slots__ = ("_save_root",)

    def __init__(self, save_root: str | Path) -> None:
        """Create a manager rooted at a save directory.

        Args:
            save_root: Directory holding episode directories. It is created if
                absent.

        Raises:
            TypeError: If ``save_root`` is not a ``str`` or ``Path``.
        """
        if not (_is_runtime_instance(save_root, str) or _is_runtime_instance(save_root, Path)):
            raise TypeError(f"save_root must be a str or Path, got {type(save_root).__name__}")
        self._save_root = Path(save_root)

    @property
    def save_root(self) -> Path:
        """Directory holding this manager's episode directories."""
        return self._save_root

    def episode_directory(self, episode: int) -> Path:
        """Return the directory path for an episode number.

        Raises:
            TypeError: If the episode is not an exact ``int``.
            ValueError: If it is negative.
        """
        return self._save_root / episode_directory_name(episode)

    def save_episode(
        self,
        world: World,
        event_log: EventLog,
        *,
        world_memory: WorldMemory,
    ) -> EpisodeManifest:
        """Write one episode directory atomically and return its manifest.

        Everything is staged and hashed in memory first, so a world that fails
        validation leaves no directory behind at all. The episode number comes
        from the world itself rather than the caller, because a save that
        disagreed with the state it contains would be indistinguishable from a
        correct one until the next episode failed to link to it.

        The caller-owned world is consulted exactly once, at the top: it is
        serialized into one world-state document, and that document is strictly
        reconstructed into an exact base :class:`World`. Every later step --
        the episode number, the destination directory, parent lookup, memory
        checkpoint matching, memory-transition validation, entity counts, and
        the manifest -- reads the reconstructed world, and ``world_state.json``
        is the exact captured document. A ``World`` or entity subclass that
        answers differently on a later read therefore cannot say one thing to
        validation and another to disk: whatever single snapshot the serializer
        captured is the whole truth the save is judged by, and a snapshot the
        loader would refuse is refused here, before publication.

        Args:
            world: The world to persist. Not modified, and never read again
                after the authoritative world-state document has been captured.
            event_log: The episode's event history. Read exactly once and not
                modified.
            world_memory: The cumulative durable history for this episode. Its
                checkpoint must match the captured world, so an episode and
                its memory can never describe different moments.

        Returns:
            The manifest describing the episode just written.

        Raises:
            TypeError: If an argument is of the wrong type or a stored value is
                mistyped.
            ValueError: If the world is inconsistent, its captured document does
                not reconstruct, or a value is invalid.
            FileExistsError: If the episode directory already exists.
            FileNotFoundError: If a previous episode is required and absent.
        """
        if not _is_runtime_instance(world, World):
            raise TypeError(f"world must be a World, got {type(world).__name__}")
        if not _is_runtime_instance(event_log, EventLog):
            raise TypeError(f"event_log must be an EventLog, got {type(event_log).__name__}")

        # The authoritative snapshot. ``serialize_world`` validates the
        # aggregate and builds the one document this save may write, but its
        # internal reads are still reads of a live object -- a stateful subclass
        # can change between them. Reconstructing the document proves that the
        # actual bytes headed for disk describe a world this implementation
        # would load, and yields the exact base World every remaining phase
        # reads. When reconstruction fails, no save is published. The
        # caller-owned world is never consulted again after this line.
        world_document = serialize_world(world)
        world_snapshot = deserialize_world(world_document)

        episode = world_snapshot.episode
        tick = world_snapshot.tick

        # Both remaining caller-owned inputs are normalized into exact
        # base-domain objects before anything is validated or written. Freezing
        # which objects are involved is not enough: a subclass can report one
        # value to validation and another to serialization, and the save that
        # results is one this implementation cannot reload. Everything below
        # reads only the snapshots, so what is validated is exactly what is
        # published.
        events = snapshot_event_log(event_log)
        memory = snapshot_world_memory(world_memory, "world_memory")
        self._require_matching_memory(memory, world_snapshot)

        snapshot_log = EventLog()
        for event in events:
            snapshot_log.append(event)

        destination = self.episode_directory(episode)
        # ``lexists`` rather than ``exists``: a broken symlink is an existing
        # directory entry that ``exists`` reports as absent, and publishing over
        # it would either clobber it or leak an unrelated filesystem error.
        if os.path.lexists(destination):
            raise FileExistsError(
                f"episode {episode} already exists at {destination}; published episodes "
                "are immutable and are never overwritten"
            )

        # The parent is loaded once and used for both jobs it is needed for: the
        # verified state hash, and the history this episode must continue from.
        parent = None if episode == 0 else self._load_parent(episode)
        parent_state_hash = None if parent is None else parent.manifest.state_hash
        validate_memory_transition_events(
            previous_memory=None if parent is None else parent.world_memory,
            current_memory=memory,
            world=world_snapshot,
            events=events,
        )

        # ``world_state.json`` is the exact captured document that passed
        # reconstruction -- not a second serialization of anything live.
        payloads = {
            WORLD_STATE_FILE: dumps_canonical(world_document, WORLD_STATE_FILE),
            EVENT_LOG_FILE: dumps_canonical(
                serialize_event_log(snapshot_log, episode, tick), EVENT_LOG_FILE
            ),
            WORLD_MEMORY_FILE: dumps_canonical(serialize_world_memory(memory), WORLD_MEMORY_FILE),
        }
        files = {
            name: FileMetadata(sha256=sha256_hex(data), bytes=len(data))
            for name, data in payloads.items()
        }
        manifest = EpisodeManifest(
            format=EPISODE_FORMAT,
            schema_version=SCHEMA_VERSION,
            engine_version=ENGINE_VERSION,
            python_version=platform.python_version(),
            episode=episode,
            tick=tick,
            state_hash=files[WORLD_STATE_FILE].sha256,
            parent_state_hash=parent_state_hash,
            event_count=len(events),
            entity_counts=MappingProxyType(entity_counts(world_snapshot)),
            files=MappingProxyType(files),
        )
        documents = dict(payloads)
        documents[MANIFEST_FILE] = dumps_canonical(manifest.to_document(), MANIFEST_FILE)

        self._publish(destination, documents)
        return manifest

    @staticmethod
    def _require_matching_memory(world_memory: object, world: World) -> None:
        """Verify the memory describes the same moment as the world being saved.

        Checked before anything touches the filesystem, and checked against the
        reconstructed world snapshot rather than the caller's live object -- the
        checkpoint that matters is the one the captured world-state document
        actually records, because that is the tick and episode the loader will
        rebuild the memory against. A memory checkpointed to a different episode
        or tick is not this episode's history, and writing it would produce a
        save whose two halves quietly disagree -- with no hash or lineage check
        able to notice, because both files would be internally valid.

        Raises:
            TypeError: If the argument is not a ``WorldMemory``.
            ValueError: If it has not been processed, or its checkpoint does not
                match the world.
        """
        if not _is_runtime_instance(world_memory, WorldMemory):
            raise TypeError(
                f"world_memory must be a WorldMemory, got {type(world_memory).__name__}"
            )
        if world_memory.through_episode is None or world_memory.through_tick is None:
            raise ValueError(
                "world_memory has not been processed for any episode; distil the episode "
                "before saving it"
            )
        if world_memory.through_episode != world.episode:
            raise ValueError(
                f"world_memory was processed through episode {world_memory.through_episode} "
                f"but the world records episode {world.episode}"
            )
        if world_memory.through_tick != world.tick:
            raise ValueError(
                f"world_memory was processed through tick {world_memory.through_tick} but "
                f"the world records tick {world.tick}"
            )

    def _load_parent(self, episode: int) -> LoadedEpisode:
        """Load and fully verify the episode this one continues from.

        Loaded rather than trusted, and loaded exactly once: the same verified
        parent supplies both the state hash copied into the new manifest and the
        history the new memory must begin with. Reconstructing it twice would
        cost a second full ancestry walk and invite the two answers to differ.

        Raises:
            FileNotFoundError: If the previous episode does not exist.
            ValueError: If it fails verification.
        """
        parent_number = episode - 1
        if not os.path.lexists(self.episode_directory(parent_number)):
            raise FileNotFoundError(
                f"episode {episode} cannot be saved because its parent episode "
                f"{parent_number} does not exist at {self.episode_directory(parent_number)}"
            )
        return self.load_episode(parent_number)

    def _publish(self, destination: Path, documents: Mapping[str, bytes]) -> None:
        """Write documents to a staging directory and rename it into place.

        The staging directory is a sibling of the destination so the rename
        stays within one filesystem and is therefore atomic. Every file is
        flushed to disk before publication, and the staging directory is
        removed on any failure so a broken attempt leaves nothing behind.

        Publication uses an operating-system no-replace rename, so a destination
        appearing after the earlier existence check cannot be replaced. There is
        no window between checking and renaming to lose.

        Raises:
            FileExistsError: If the destination exists or appeared while staging.
            OSError: If the filesystem refuses the write, or the platform cannot
                guarantee no-replace publication.
        """
        self._save_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=_TEMPORARY_PREFIX, dir=self._save_root))
        try:
            for name, data in documents.items():
                path = staging / name
                with open(path, "xb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
            self._verify_staged(staging, documents)

            try:
                _rename_no_replace(staging, destination)
            except FileExistsError as error:
                raise FileExistsError(
                    f"episode directory {destination} appeared while it was being written; "
                    "refusing to overwrite it"
                ) from error
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    @staticmethod
    def _verify_staged(staging: Path, documents: Mapping[str, bytes]) -> None:
        """Read the staged files back and confirm they are byte-exact.

        Raises:
            ValueError: If a staged file does not match what was written.
        """
        for name, data in documents.items():
            written = (staging / name).read_bytes()
            if written != data:
                raise ValueError(f"staged file {name} does not match the bytes that were written")

    def load_episode(self, episode: int) -> LoadedEpisode:
        """Read, verify, and reconstruct one episode and its whole ancestry.

        Every episode from zero up to the requested one is verified in order:
        directory shape, canonical bytes, lengths, digests, manifest schema, and
        then full semantic reconstruction of the world, the event log, and the
        memory document -- with both links to the episode before it compared as
        the walk goes: the world-state hash, and the inherited history.

        The ancestry is walked in full because a shorter check does not mean
        what it appears to. Verifying only the direct parent's files establishes
        that the parent's envelope is intact, not that the parent is a loadable
        episode: its world could fail topology validation, its log could belong
        to another episode, and a child would still load. And a parent whose own
        parent link is broken is itself unloadable, so a child descending from it
        descends from nothing this save root can account for.

        An episode is therefore loadable only when the entire chain behind it is.

        Args:
            episode: The episode number to load.

        Returns:
            The reconstructed target episode. Ancestors are verified and
            discarded; only the requested episode is returned.

        Raises:
            TypeError: If the episode is not an exact ``int``, or a persisted
                value is of the wrong type.
            ValueError: If the episode is negative, or anything about any
                episode in the chain fails verification.
            FileNotFoundError: If any episode in the chain, or a file it
                requires, is absent.
        """
        return self._load_verified_chain(require_exact_int(episode, "episode"))

    def _load_verified_chain(self, target: int) -> LoadedEpisode:
        """Verify every episode from zero to the target, and return the target.

        Iterative rather than recursive, so a save root holding more episodes
        than Python's recursion limit stays architecturally sound. Each ancestor
        is verified exactly once, in ascending order, and released as soon as its
        link has been checked -- only the requested episode is kept.

        Raises:
            TypeError: If a persisted value is of the wrong type.
            ValueError: If any episode fails verification or any link is wrong.
            FileNotFoundError: If any episode in the chain is absent.
        """
        previous: EpisodeManifest | None = None
        previous_memory: WorldMemory | None = None
        target_episode: LoadedEpisode | None = None

        for number in range(target + 1):
            manifest, documents = self._verified_documents(number)
            # Reconstructed in full even for an ancestor: the semantic checks
            # live here, and skipping them is exactly what let a child inherit
            # a parent whose world or log could never have been loaded.
            loaded = self._reconstruct(manifest, documents)
            self._verify_lineage_edge(manifest, previous)
            # State lineage says this episode descends from its parent's world.
            # It says nothing about the parent's history, so the memory edge is
            # checked separately -- otherwise a child could quietly forget or
            # rewrite everything the world had remembered.
            validate_memory_transition_events(
                previous_memory=previous_memory,
                current_memory=loaded.world_memory,
                world=loaded.world,
                events=tuple(loaded.event_log.events()),
            )

            previous = manifest
            previous_memory = loaded.world_memory
            if number == target:
                target_episode = loaded

        if target_episode is None:  # pragma: no cover - range always reaches target
            raise ValueError(f"episode {target} was not reached while verifying the chain")
        return target_episode

    @staticmethod
    def _verify_lineage_edge(manifest: EpisodeManifest, previous: EpisodeManifest | None) -> None:
        """Verify one episode's recorded parent against the episode before it.

        The comparison is against a manifest that has already been verified
        during this same walk, so the hash being matched is one this loader
        established rather than one a file asserted about itself.

        Raises:
            ValueError: If episode zero records a parent, a later episode records
                none, or a recorded hash disagrees with the verified parent.
        """
        if manifest.episode == 0:
            if manifest.parent_state_hash is not None:
                raise ValueError("episode 0 must record no parent_state_hash")
            return

        if previous is None:  # pragma: no cover - the walk always supplies one
            raise ValueError(f"episode {manifest.episode} has no verified predecessor to link to")
        if manifest.parent_state_hash is None:
            raise ValueError(
                f"episode {manifest.episode} records no parent_state_hash; only episode 0 "
                "begins a lineage"
            )
        if manifest.parent_state_hash != previous.state_hash:
            raise ValueError(
                f"episode {manifest.episode} records parent state hash "
                f"{manifest.parent_state_hash} but episode {previous.episode} hashes to "
                f"{previous.state_hash}"
            )

    def _verified_documents(self, episode: int) -> tuple[EpisodeManifest, dict[str, JsonValue]]:
        """Verify one episode's files and return its manifest and parsed payloads.

        Stops short of building domain objects, so lineage can be settled before
        anything is reconstructed and a child is never partially trusted.

        Raises:
            TypeError: If a persisted value is of the wrong type.
            ValueError: If the directory, hashes, encoding, or metadata fail.
            FileNotFoundError: If the directory or a required file is absent.
        """
        directory = self.episode_directory(episode)
        self._verify_directory(directory, episode)

        manifest_bytes = (directory / MANIFEST_FILE).read_bytes()
        manifest_document = loads_canonical(manifest_bytes, MANIFEST_FILE)
        self._require_canonical_bytes(manifest_bytes, manifest_document, MANIFEST_FILE)
        manifest = EpisodeManifest.from_document(manifest_document, MANIFEST_FILE)
        if manifest.episode != episode:
            raise ValueError(
                f"{directory} holds episode {manifest.episode} but was loaded as {episode}"
            )

        documents: dict[str, JsonValue] = {}
        for name in PAYLOAD_FILES:
            data = (directory / name).read_bytes()
            metadata = manifest.files[name]
            if len(data) != metadata.bytes:
                raise ValueError(
                    f"{name} is {len(data)} bytes but the manifest records {metadata.bytes}"
                )
            digest = sha256_hex(data)
            if digest != metadata.sha256:
                raise ValueError(
                    f"{name} hashes to {digest} but the manifest records {metadata.sha256}"
                )
            document = loads_canonical(data, name)
            self._require_canonical_bytes(data, document, name)
            documents[name] = document

        state_digest = sha256_hex((directory / WORLD_STATE_FILE).read_bytes())
        if state_digest != manifest.state_hash:
            raise ValueError(
                f"state_hash is {manifest.state_hash} but {WORLD_STATE_FILE} hashes to "
                f"{state_digest}"
            )
        return manifest, documents

    @staticmethod
    def _require_canonical_bytes(data: bytes, document: JsonValue, name: str) -> None:
        """Verify a file is written in the one canonical encoding.

        Hashes alone are not enough. They catch a payload that was reformatted
        and left with its old digest, but not one that was reformatted and had
        the manifest updated to match -- and the manifest is not itself
        authenticated by anything. Re-encoding the parsed document and demanding
        the same bytes closes that: a save has exactly one representation, and
        anything else was written by something other than this codec.

        Raises:
            ValueError: If the bytes are not the canonical encoding of their own
                content.
        """
        if dumps_canonical(document, name) != data:
            raise ValueError(
                f"{name} is not in canonical form; a save file must be exactly the "
                "canonical encoding of its own content"
            )

    @staticmethod
    def _reconstruct(
        manifest: EpisodeManifest, documents: Mapping[str, JsonValue]
    ) -> LoadedEpisode:
        """Build the domain objects from already verified payloads.

        Raises:
            TypeError: If a persisted value is of the wrong type.
            ValueError: If the payloads disagree with the manifest or each other.
        """
        world = deserialize_world(documents[WORLD_STATE_FILE])
        if world.episode != manifest.episode:
            raise ValueError(
                f"manifest records episode {manifest.episode} but the world state records "
                f"{world.episode}"
            )
        if world.tick != manifest.tick:
            raise ValueError(
                f"manifest records tick {manifest.tick} but the world state records {world.tick}"
            )
        require_entity_counts(world, manifest.entity_counts)

        event_log = deserialize_event_log(documents[EVENT_LOG_FILE], world.tick, world.episode)
        loaded_events = tuple(event_log.events())
        if len(loaded_events) != manifest.event_count:
            raise ValueError(
                f"manifest records {manifest.event_count} events but the log holds "
                f"{len(loaded_events)}"
            )

        world_memory = deserialize_world_memory(
            documents[WORLD_MEMORY_FILE],
            WORLD_MEMORY_FILE,
            through_episode=manifest.episode,
            through_tick=manifest.tick,
        )
        return LoadedEpisode(
            world=world, event_log=event_log, world_memory=world_memory, manifest=manifest
        )

    @staticmethod
    def _verify_directory(directory: Path, episode: int) -> None:
        """Verify an episode directory holds exactly the expected regular files.

        Raises:
            FileNotFoundError: If the directory or a required file is absent.
            ValueError: If the path is a symlink or not a directory, or the
                directory holds unexpected entries, subdirectories, symlinked
                files, or non-regular files.
        """
        if directory.is_symlink():
            raise ValueError(f"episode path {directory} is a symbolic link")
        if not directory.exists():
            raise FileNotFoundError(f"episode {episode} does not exist at {directory}")
        if not directory.is_dir():
            raise ValueError(f"episode path {directory} is not a directory")

        present = sorted(entry.name for entry in directory.iterdir())
        expected = list(EPISODE_FILES)
        missing = sorted(set(expected) - set(present))
        if missing:
            raise FileNotFoundError(f"{directory} is missing required files: {missing}")
        unexpected = sorted(set(present) - set(expected))
        if unexpected:
            raise ValueError(f"{directory} holds unexpected entries: {unexpected}")

        for name in expected:
            path = directory / name
            if path.is_symlink():
                raise ValueError(f"{path} is a symbolic link")
            if not path.is_file():
                raise ValueError(f"{path} is not a regular file")

    def verify_lineage(self, parent_episode: int, child_episode: int) -> None:
        """Verify a child episode descends from the given parent.

        Both episodes are loaded and fully verified independently, so lineage
        cannot be established from metadata alone. Nothing on disk is modified,
        including when the check fails.

        Args:
            parent_episode: The earlier episode number.
            child_episode: The later episode number, which must follow directly.

        Raises:
            TypeError: If either episode is not an exact ``int``.
            ValueError: If the numbers are not consecutive, if the child records
                no parent, or if the recorded parent hash does not match the
                parent's verified state hash.
            FileNotFoundError: If either episode is absent.
        """
        parent_number = require_exact_int(parent_episode, "parent_episode")
        child_number = require_exact_int(child_episode, "child_episode")
        if child_number != parent_number + 1:
            raise ValueError(
                f"episode {child_number} does not directly follow episode {parent_number}"
            )

        parent = self.load_episode(parent_number)
        child = self.load_episode(child_number)
        if child.manifest.parent_state_hash is None:
            raise ValueError(f"episode {child_number} records no parent state hash")
        if child.manifest.parent_state_hash != parent.manifest.state_hash:
            raise ValueError(
                f"episode {child_number} records parent state hash "
                f"{child.manifest.parent_state_hash} but episode {parent_number} hashes to "
                f"{parent.manifest.state_hash}"
            )
