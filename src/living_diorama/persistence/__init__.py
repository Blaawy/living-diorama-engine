"""Convert world, event-log, and memory state to versioned JSON saves.

Owns schema versioning, canonical encoding, state hashing, and lineage
verification between episodes. Contains no simulation logic: loading a save
runs no system, advances no tick, publishes no event, and draws no randomness.

The dependency direction is one-way. Persistence reads entities, events, and
the simulation aggregate; none of them may import persistence.
"""

from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.save_manager import LoadedEpisode, SaveManager
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.persistence.schema.world_schema_v1 import (
    EPISODE_FORMAT,
    EVENT_LOG_FILE,
    MANIFEST_FILE,
    SCHEMA_VERSION,
    WORLD_MEMORY_FILE,
    WORLD_STATE_FILE,
    EpisodeManifest,
    FileMetadata,
    episode_directory_name,
)

__all__ = [
    "EPISODE_FORMAT",
    "EVENT_LOG_FILE",
    "MANIFEST_FILE",
    "SCHEMA_VERSION",
    "WORLD_MEMORY_FILE",
    "WORLD_STATE_FILE",
    "EpisodeManifest",
    "FileMetadata",
    "LoadedEpisode",
    "SaveManager",
    "dumps_canonical",
    "episode_directory_name",
    "loads_canonical",
    "sha256_hex",
]
