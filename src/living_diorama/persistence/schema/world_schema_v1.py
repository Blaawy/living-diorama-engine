"""Schema version 1: constants, field validation, and the episode manifest.

Everything a save promises about its own shape lives here. The field validators
are shared by every serializer so that a rule -- an identifier may not carry
surrounding whitespace, a tick is an exact ``int`` and never a ``bool`` -- is
written once and applied identically on the way out and on the way back in.

Entities stay mutable after construction, so the constructors that validated
them once cannot speak for their state now. A save is a permanent record: it
has to refuse corrupt state rather than write it down.
"""

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from living_diorama.events.event import JsonValue
from living_diorama.persistence.json_codec import require_document, require_json_value
from living_diorama.persistence.schema.state_hash import require_hash_hex

SCHEMA_VERSION: Final = 1
"""The only schema version this build reads or writes."""

EPISODE_FORMAT: Final = "living_diorama_episode"
"""Marker identifying a directory as an episode save of this engine."""

MANIFEST_FILE: Final = "manifest.json"
"""Name of the metadata file, which is not hashed by itself."""

WORLD_STATE_FILE: Final = "world_state.json"
"""Name of the world-state payload, whose hash is the canonical state hash."""

EVENT_LOG_FILE: Final = "event_log.json"
"""Name of the episode-scoped event history payload."""

WORLD_MEMORY_FILE: Final = "world_memory.json"
"""Name of the opaque world-memory payload reserved for a later phase."""

PAYLOAD_FILES: Final = (EVENT_LOG_FILE, WORLD_MEMORY_FILE, WORLD_STATE_FILE)
"""The three hashed payload files, in sorted order."""

EPISODE_FILES: Final = (EVENT_LOG_FILE, MANIFEST_FILE, WORLD_MEMORY_FILE, WORLD_STATE_FILE)
"""Every file a completed episode directory may contain, in sorted order."""

ENTITY_COUNT_KEYS: Final = ("boundaries", "districts", "infrastructure", "laws", "walls")
"""Registry names counted in the manifest, in sorted order."""

_MANIFEST_KEYS: Final = frozenset(
    {
        "engine_version",
        "entity_counts",
        "episode",
        "event_count",
        "files",
        "format",
        "parent_state_hash",
        "python_version",
        "schema_version",
        "state_hash",
        "tick",
    }
)
"""Exactly the keys a version 1 manifest carries -- no more, no fewer."""

_FILE_METADATA_KEYS: Final = frozenset({"bytes", "sha256"})
"""Exactly the keys each file-metadata entry carries."""


def episode_directory_name(episode: int) -> str:
    """Return the directory name for an episode number.

    Args:
        episode: The episode number.

    Returns:
        A zero-padded name such as ``episode_007``. Numbers past three digits
        simply grow, so ``episode_1000`` is well formed.

    Raises:
        TypeError: If the episode is not an exact ``int``.
        ValueError: If it is negative.
    """
    return f"episode_{require_exact_int(episode, 'episode'):03d}"


def require_exact_int(value: object, description: str) -> int:
    """Return the value if it is an exact non-negative ``int``, else raise.

    ``bool`` is refused because it subclasses ``int``: a stored ``True`` would
    otherwise persist as ``1`` and load back as an integer, quietly changing
    what the world says about itself.

    Raises:
        TypeError: If the value is not an exact ``int``.
        ValueError: If it is negative.
    """
    if type(value) is not int:
        raise TypeError(f"{description} must be an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{description} must be >= 0, got {value}")
    return value


def require_real(value: object, description: str) -> float:
    """Return a finite real number as a ``float``, else raise.

    Raises:
        TypeError: If the value is not an ``int`` or ``float``, or is a ``bool``.
        ValueError: If it is not finite.
    """
    if type(value) is int:
        number = float(value)
    elif type(value) is float:
        number = value
    else:
        raise TypeError(f"{description} must be a real number, got {type(value).__name__}")
    if not math.isfinite(number):
        raise ValueError(f"{description} must be finite, got {value!r}")
    return number


def require_non_negative_real(value: object, description: str) -> float:
    """Return a finite real number that is not negative, else raise.

    Raises:
        TypeError: If the value is not a real number, or is a ``bool``.
        ValueError: If it is not finite or is negative.
    """
    number = require_real(value, description)
    if number < 0.0:
        raise ValueError(f"{description} must be >= 0, got {number}")
    return number


def require_unit_interval(value: object, description: str) -> float:
    """Return a finite real number inside 0.0-1.0, else raise.

    Raises:
        TypeError: If the value is not a real number, or is a ``bool``.
        ValueError: If it is not finite or falls outside 0.0-1.0.
    """
    number = require_real(value, description)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{description} must be within 0.0-1.0, got {number}")
    return number


def require_flag(value: object, description: str) -> bool:
    """Return the value if it is exactly a ``bool``, else raise.

    ``0`` and ``1`` are refused. A flag deciding whether a wall stands has to be
    a flag, not something merely truthy that would load back as an integer.

    Raises:
        TypeError: If the value is not exactly a ``bool``.
    """
    if type(value) is not bool:
        raise TypeError(f"{description} must be a bool, got {type(value).__name__}")
    return value


def require_identifier(value: object, description: str) -> str:
    """Return the value if it is a canonical identifier, else raise.

    Entity constructors accept an identifier with surrounding whitespace and
    silently strip it, but entities stay mutable, so a registry can end up
    holding ``"gate "`` as both its key and its ``id``. Stripping here would
    write a different identifier than the one the world is actually using, so a
    noncanonical identifier is refused rather than repaired. Internal
    whitespace is fine: ``"north gate"`` is a perfectly good name.

    Raises:
        TypeError: If the value is not a ``str``.
        ValueError: If it is empty, whitespace-only, or carries surrounding
            whitespace.
    """
    if type(value) is not str:
        raise TypeError(f"{description} must be a str, got {type(value).__name__}")
    if not value:
        raise ValueError(f"{description} must not be empty")
    if not value.strip():
        raise ValueError(f"{description} must not be only whitespace, got {value!r}")
    if value.strip() != value:
        raise ValueError(f"{description} must not carry surrounding whitespace, got {value!r}")
    return value


def require_text(value: object, description: str) -> str:
    """Return a non-blank ``str`` carrying no surrounding whitespace, else raise.

    Raises:
        TypeError: If the value is not a ``str``.
        ValueError: If it is blank or carries surrounding whitespace.
    """
    return require_identifier(value, description)


def require_exact_keys(
    document: dict[str, JsonValue], expected: frozenset[str], description: str
) -> None:
    """Verify a document carries exactly the expected keys.

    Both directions matter. A missing key means the save is incomplete; an
    unexpected one means it was written by something this build does not
    understand, and guessing what to do with it is how silent corruption gets
    in.

    Raises:
        ValueError: If any expected key is missing or any extra key is present.
    """
    present = set(document)
    missing = sorted(expected - present)
    unexpected = sorted(present - expected)
    if missing:
        raise ValueError(f"{description} is missing required keys: {missing}")
    if unexpected:
        raise ValueError(f"{description} carries unexpected keys: {unexpected}")


def require_schema_version(document: dict[str, JsonValue], description: str) -> int:
    """Verify a document declares the supported schema version.

    Raises:
        TypeError: If the declared version is not an ``int``.
        ValueError: If it is not the supported version. No migration is
            attempted, because guessing the shape of an unknown version is how
            a save becomes silently wrong rather than loudly broken.
    """
    version = require_exact_int(document.get("schema_version"), f"{description} schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"{description} declares unsupported schema version {version}; "
            f"this build reads version {SCHEMA_VERSION} only"
        )
    return version


def require_sorted_unique(values: list[str], description: str) -> None:
    """Verify identifiers appear in sorted order with no repeats.

    Serialized arrays are sorted so that the bytes depend only on the state and
    never on the order entities happened to be registered in. A file that is out
    of order was not produced by this writer.

    Raises:
        ValueError: If a value repeats or the sequence is not sorted.
    """
    if len(set(values)) != len(values):
        duplicates = sorted({value for value in values if values.count(value) > 1})
        raise ValueError(f"{description} contains duplicate ids: {duplicates}")
    if values != sorted(values):
        raise ValueError(f"{description} must be sorted by id")


@dataclass(frozen=True, slots=True)
class FileMetadata:
    """The size and digest of one payload file as written.

    Attributes:
        sha256: Digest of the exact bytes on disk.
        bytes: Length of those bytes.
    """

    sha256: str
    bytes: int

    def __post_init__(self) -> None:
        """Validate the recorded digest and length.

        Raises:
            TypeError: If either field is of the wrong type.
            ValueError: If the digest is malformed or the length is negative.
        """
        require_hash_hex(self.sha256, "sha256")
        require_exact_int(self.bytes, "bytes")

    def to_document(self) -> dict[str, JsonValue]:
        """Return this metadata as a JSON object."""
        return {"bytes": self.bytes, "sha256": self.sha256}

    @classmethod
    def from_document(cls, value: JsonValue, description: str) -> "FileMetadata":
        """Rebuild metadata from a JSON object.

        Raises:
            TypeError: If the value is not a JSON object or a field is mistyped.
            ValueError: If keys are missing or extra, or a field is invalid.
        """
        document = require_document(value, description)
        require_exact_keys(document, _FILE_METADATA_KEYS, description)
        return cls(
            sha256=require_hash_hex(document["sha256"], f"{description} sha256"),
            bytes=require_exact_int(document["bytes"], f"{description} bytes"),
        )


@dataclass(frozen=True, slots=True)
class EpisodeManifest:
    """Everything a reader needs to verify an episode before trusting it.

    Carries no timestamp and no random identifier: two saves of the same state
    on the same runtime describe themselves identically, which is what lets a
    reviewer compare two runs by their hashes alone.

    Attributes:
        format: Marker identifying this as an episode of this engine.
        schema_version: Schema version the episode was written against.
        engine_version: Version of the engine that wrote it.
        python_version: Interpreter version that wrote it, recorded for
            diagnosis only and never used to gate loading.
        episode: Episode number.
        tick: World tick at the moment of the save.
        state_hash: Digest of the world-state payload bytes.
        parent_state_hash: The previous episode's ``state_hash``, or ``None``
            for episode zero.
        event_count: Number of events in the episode log.
        entity_counts: Number of entities in each typed registry.
        files: Digest and length of each payload file.
    """

    format: str
    schema_version: int
    engine_version: str
    python_version: str
    episode: int
    tick: int
    state_hash: str
    parent_state_hash: str | None
    event_count: int
    entity_counts: "MappingProxyType[str, int]"
    files: "MappingProxyType[str, FileMetadata]"

    def __post_init__(self) -> None:
        """Validate every field and store the mappings read-only.

        Raises:
            TypeError: If any field is of the wrong type.
            ValueError: If any field carries an invalid value.
        """
        require_text(self.format, "format")
        if self.format != EPISODE_FORMAT:
            raise ValueError(f"format must be {EPISODE_FORMAT!r}, got {self.format!r}")
        # Checked for exact type before being compared, because ``True == 1``:
        # an equality-only check would accept a bool as the schema version and
        # then write it back out as ``true``.
        if require_exact_int(self.schema_version, "schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {SCHEMA_VERSION}, got {self.schema_version!r}"
            )
        require_text(self.engine_version, "engine_version")
        require_text(self.python_version, "python_version")
        require_exact_int(self.episode, "episode")
        require_exact_int(self.tick, "tick")
        require_hash_hex(self.state_hash, "state_hash")
        if self.parent_state_hash is not None:
            require_hash_hex(self.parent_state_hash, "parent_state_hash")
        require_exact_int(self.event_count, "event_count")

        counts = dict(self.entity_counts)
        if tuple(sorted(counts)) != ENTITY_COUNT_KEYS:
            raise ValueError(
                f"entity_counts must carry exactly {list(ENTITY_COUNT_KEYS)}, got {sorted(counts)}"
            )
        for name, count in counts.items():
            require_exact_int(count, f"entity_counts[{name!r}]")

        files = dict(self.files)
        if tuple(sorted(files)) != PAYLOAD_FILES:
            raise ValueError(f"files must carry exactly {list(PAYLOAD_FILES)}, got {sorted(files)}")
        for name, metadata in files.items():
            if not isinstance(metadata, FileMetadata):
                raise TypeError(
                    f"files[{name!r}] must be FileMetadata, got {type(metadata).__name__}"
                )
        if self.state_hash != files[WORLD_STATE_FILE].sha256:
            raise ValueError(
                "state_hash must equal the recorded digest of "
                f"{WORLD_STATE_FILE}, got {self.state_hash!r} and "
                f"{files[WORLD_STATE_FILE].sha256!r}"
            )
        if self.episode == 0:
            if self.parent_state_hash is not None:
                raise ValueError("episode 0 must have no parent_state_hash")
        elif self.parent_state_hash is None:
            raise ValueError(
                f"episode {self.episode} must record a parent_state_hash; only episode 0 "
                "begins a lineage"
            )

        object.__setattr__(self, "entity_counts", MappingProxyType(counts))
        object.__setattr__(self, "files", MappingProxyType(files))

    def to_document(self) -> dict[str, JsonValue]:
        """Return this manifest as a JSON object."""
        return {
            "engine_version": self.engine_version,
            "entity_counts": dict(self.entity_counts),
            "episode": self.episode,
            "event_count": self.event_count,
            "files": {name: metadata.to_document() for name, metadata in self.files.items()},
            "format": self.format,
            "parent_state_hash": self.parent_state_hash,
            "python_version": self.python_version,
            "schema_version": self.schema_version,
            "state_hash": self.state_hash,
            "tick": self.tick,
        }

    @classmethod
    def from_document(cls, value: JsonValue, description: str = "manifest") -> "EpisodeManifest":
        """Rebuild a manifest from a JSON object, validating it completely.

        Raises:
            TypeError: If the document or a field is of the wrong type.
            ValueError: If keys are missing or extra, or a field is invalid.
        """
        document = require_document(value, description)
        require_exact_keys(document, _MANIFEST_KEYS, description)
        require_schema_version(document, description)

        counts_document = require_document(
            document["entity_counts"], f"{description} entity_counts"
        )
        files_document = require_document(document["files"], f"{description} files")
        parent = document["parent_state_hash"]
        # Narrowed into its own variable so the validated value is what reaches
        # the constructor; discarding the result would leave the parameter typed
        # as the whole JsonValue union.
        validated_parent: str | None = (
            None if parent is None else require_hash_hex(parent, f"{description} parent_state_hash")
        )

        return cls(
            format=require_text(document["format"], f"{description} format"),
            schema_version=SCHEMA_VERSION,
            engine_version=require_text(
                document["engine_version"], f"{description} engine_version"
            ),
            python_version=require_text(
                document["python_version"], f"{description} python_version"
            ),
            episode=require_exact_int(document["episode"], f"{description} episode"),
            tick=require_exact_int(document["tick"], f"{description} tick"),
            state_hash=require_hash_hex(document["state_hash"], f"{description} state_hash"),
            parent_state_hash=validated_parent,
            event_count=require_exact_int(document["event_count"], f"{description} event_count"),
            entity_counts=MappingProxyType(
                {
                    name: require_exact_int(count, f"{description} entity_counts[{name!r}]")
                    for name, count in counts_document.items()
                }
            ),
            files=MappingProxyType(
                {
                    name: FileMetadata.from_document(entry, f"{description} files[{name!r}]")
                    for name, entry in files_document.items()
                }
            ),
        )


def require_json_document(value: object, description: str) -> dict[str, JsonValue]:
    """Return a strictly JSON-compatible object, else raise.

    Raises:
        TypeError: If the value is not a JSON object or holds a forbidden type.
        ValueError: If it holds a non-finite number.
    """
    return require_document(require_json_value(value, description), description)
