"""Phase 35: the final episode media -- one watchable projection of locked truth.

The audited Phase 33 assembly holds the locked pixels and the locked samples; the audited
Phase 34 serialization holds the locked captions in target formats. This package owns the
one join no layer owned: projecting them, through a pinned FFmpeg execution profile
(``media_encode_profile_v1``: MP4, libx264 at CRF 18 / preset medium / yuv420p with
automatic output-scoped video threading, AAC at a 128k request), into one watchable
episode file published beside byte-exact caption sidecars, two provenance manifest
copies, and its own manifest.

MORE EXECUTION, NOT NEW TRUTH. No simulation, story, timing, audio or caption truth is
created here: every pixel identity remains Phase 23's, every sample identity Phase 31's,
every wording and cue identity Phase 26/32/34's. The MP4 is CLASS B -- an attested
viewing projection whose bytes are digest-recorded at production and re-verified on every
read, with cross-machine byte identity deliberately not claimed -- while the manifest and
every carried byte are exact. The decisive audio-length closure is exact to the sample:
the captured media must DECODE back to precisely the locked ``audio_samples_total``.

The one tool-touching entry point lives outside this package, in
``media/ffmpeg/scripts/encode_episode.py`` -- the one approved subprocess site of the
whole repository's media side; nothing in this package spawns anything, and the boundary
guard proves it. This package owns the pure halves: the exact command profiles, the
version and capability gates' laws, the probe normalization and every stream law, the
manifest, the staging ownership, and the tool-free self-contained audit.
"""

from living_diorama.media_encode.media_encode_audit import audit_media_encode_directory
from living_diorama.media_encode.media_encode_command import (
    build_decode_command,
    build_media_encode_command,
    build_preflight_command,
    build_probe_command,
    preflight_wav_bytes,
    substitute_paths,
)
from living_diorama.media_encode.media_encode_manifest import (
    build_episode_media_encode_manifest_bytes,
    build_episode_media_encode_manifest_document,
    require_encode_sources_join,
)
from living_diorama.media_encode.media_encode_probe import (
    normalize_probe_document,
    require_stream_facts,
)
from living_diorama.media_encode.media_encode_schema_v1 import (
    validate_episode_media_encode_manifest,
)
from living_diorama.media_encode.media_encode_spec import (
    MEDIA_ENCODE_MANIFEST_FILENAME,
    MEDIA_ENCODE_MANIFEST_FORMAT,
    MEDIA_ENCODE_PROFILE_V1,
    MEDIA_ENCODE_SCHEMA_VERSION,
    MediaEncodeRefused,
    media_encode_id,
    media_filename,
)
from living_diorama.media_encode.media_encode_staging import MediaEncodeDirectoryRefused
from living_diorama.media_encode.media_encode_version import (
    parse_version_first_line,
    require_capability,
)

__all__ = [
    "MEDIA_ENCODE_MANIFEST_FILENAME",
    "MEDIA_ENCODE_MANIFEST_FORMAT",
    "MEDIA_ENCODE_PROFILE_V1",
    "MEDIA_ENCODE_SCHEMA_VERSION",
    "MediaEncodeDirectoryRefused",
    "MediaEncodeRefused",
    "audit_media_encode_directory",
    "build_decode_command",
    "build_episode_media_encode_manifest_bytes",
    "build_episode_media_encode_manifest_document",
    "build_media_encode_command",
    "build_preflight_command",
    "build_probe_command",
    "media_encode_id",
    "media_filename",
    "normalize_probe_document",
    "parse_version_first_line",
    "preflight_wav_bytes",
    "require_capability",
    "require_encode_sources_join",
    "require_stream_facts",
    "substitute_paths",
    "validate_episode_media_encode_manifest",
]
