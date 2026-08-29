"""Phase 35 final-media policy: naming, directory shape, profile constants and rails.

A final episode media directory turns the audited Phase 33 assembly and the audited
Phase 34 caption serialization into one watchable, self-described episode file beside
byte-exact caption sidecars and a provenance manifest. Nothing here decides any
simulation, story, timing, audio or caption truth -- this module holds only the
deterministic vocabulary every other Phase 35 module shares: the format identity of the
manifest, the exact names a final-media directory and its files carry, the reviewed
``media_encode_profile_v1`` constants, and the two path-placeholder tokens.

MORE EXECUTION, NOT NEW TRUTH: the encoder only projects bytes locked phases already
determined, and this module only names what it projects.
"""

from typing import Final

from living_diorama.caption_serialization.caption_serialization_spec import (
    SRT_SUFFIX,
    VTT_SUFFIX,
    sidecar_filename,
)
from living_diorama.render_execution.render_execution_spec import render_id

MEDIA_ENCODE_MANIFEST_FORMAT: Final = "living_diorama_episode_media_encode_manifest"
"""The format tag every episode media encode manifest declares."""

MEDIA_ENCODE_SCHEMA_VERSION: Final = 1
"""The media encode manifest schema version this build reads and writes."""

MEDIA_ENCODE_PROFILE_V1: Final = "media_encode_profile_v1"
"""The one reviewed viewing-projection profile this build constructs and validates."""

MEDIA_ENCODE_MANIFEST_FILENAME: Final = "episode_media_encode_manifest.json"
"""The manifest filename inside a final-media directory."""

PROVENANCE_DIRECTORY: Final = "provenance"
"""Where the two bound manifest copies are written, relative to the final directory."""

ASSEMBLY_MANIFEST_COPY_FILENAME: Final = "episode_media_assembly_manifest.json"
"""The exact-byte copy filename of the bound Phase 33 manifest, inside ``provenance/``.

Declared independently of ``living_diorama.media_assembly`` rather than imported from it:
the copy's name inside a Phase 35 directory is this phase's own contract, restated, and a
dedicated test asserts the two string values still agree so drift fails loudly.
"""

CAPTIONS_MANIFEST_COPY_FILENAME: Final = "episode_caption_serialization_manifest.json"
"""The exact-byte copy filename of the bound Phase 34 manifest, inside ``provenance/``."""

MP4_SUFFIX: Final = ".mp4"
"""The final episode file's suffix, appended to the episode id."""

PARTIAL_SUFFIX: Final = ".partial"
"""Appended to a final-media id to name its sibling staging directory."""

WRITING_SUFFIX: Final = ".writing"
"""Appended to an owned filename while it is being written atomically."""

ENCODING_SUFFIX: Final = ".encoding"
"""Appended to a working temporary of the encode step.

Both the tool-written output temporaries and the executor-written input temporaries carry
this suffix, so every conceivable leftover classifies as this phase's own working file --
``"partial"`` -- and a crash at any point leaves a tree the next run's discard provably
owns. Under the narrower Phase 33 template law these names would classify foreign and
wedge recovery; the extension buys the truthful label, never extra permissiveness.
"""

PREFLIGHT_MEDIA_FILENAME: Final = "preflight.mp4" + ENCODING_SUFFIX
"""The real-geometry self-test's tool-written output temporary, inside staging."""

PREFLIGHT_AUDIO_FILENAME: Final = "preflight_audio.wav" + ENCODING_SUFFIX
"""The real-geometry self-test's executor-built source WAV temporary, inside staging."""

SNAPSHOT_AUDIO_FILENAME: Final = "source_audio.wav" + ENCODING_SUFFIX
"""The captured, digest-verified Phase 33 WAV snapshot the encoder consumes.

Written from the single captured observation of the assembly's own track, so the audio
input TOCTOU closes outright: a WAV swapped during the encode can no longer reach the
encoder at all. It is re-hashed post-encode, deleted before the terminal staged audit, and
NEVER appears in a published final directory.
"""

VIDEO_CODEC: Final = "libx264"
"""The reviewed video encoder."""

AUDIO_CODEC: Final = "aac"
"""The reviewed audio encoder."""

PIX_FMT: Final = "yuv420p"
"""The reviewed pixel-format projection -- an explicit, recorded choice, never identity."""

X264_PRESET: Final = "medium"
"""The reviewed x264 preset."""

X264_CRF: Final = 18
"""The reviewed constant-quality rate-control value."""

AAC_BITRATE: Final = "128k"
"""The reviewed AAC bitrate request."""

VIDEO_THREADS: Final = 0
"""The reviewed video threading policy: automatic (``-threads:v 0``, output-scoped).

No thread-count determinism is claimed anywhere: the projection is class B, and
same-machine byte identity remains evidence, never a contract.
"""

FFMPEG_MAJOR: Final = 9
"""The one FFmpeg release family the version gate accepts, for both tools."""

ASSEMBLY_DIR_TOKEN: Final = "{ASSEMBLY_DIR}"
"""The one canonical placeholder for the audited assembly root -- frames input only."""

STAGING_TOKEN: Final = "{STAGING}"
"""The one canonical placeholder for this run's proven-owned staging root.

The audio snapshot input and the output temporary live under it; the two tokens are the
ONLY non-literal path prefixes canonical output may carry, and the executor substitutes
real roots only in the spawned argv, which lives in runtime logs, never in canonical bytes.
"""


class MediaEncodeRefused(ValueError):
    """The sources, the geometry, a probe fact or a decoded measurement refuses this encode."""


def media_encode_id(*, mode: str, episode: int, previous_episode: int | None) -> str:
    """Return the deterministic directory name for one episode's final media.

    Delegates whole to :func:`living_diorama.render_execution.render_execution_spec.render_id`
    rather than re-implementing the naming law: one owner for the episode-directory naming
    law, exactly as every execution phase in this chain delegates its own.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If the mode is unknown, an episode is negative, or the episode pair is
            not a direct succession.
    """
    return render_id(mode=mode, episode=episode, previous_episode=previous_episode)


def media_filename(episode_id: str) -> str:
    """Return the final episode file's deterministic filename for this episode id.

    The basename equals the directory id and the sidecar basenames -- the same-basename
    convention a viewer relies on when manually enabling the SRT beside the episode file.

    Raises:
        TypeError: If ``episode_id`` is not a ``str``.
    """
    if type(episode_id) is not str:
        raise TypeError(f"episode_id must be a str, got {type(episode_id).__name__}")
    return f"{episode_id}{MP4_SUFFIX}"


def media_temp_filename(episode_id: str) -> str:
    """Return the tool-written encode temporary's filename for this episode id."""
    return f"{media_filename(episode_id)}{ENCODING_SUFFIX}"


def final_media_directory_entries(episode_id: str) -> frozenset[str]:
    """Return exactly the five top-level entries a finished final-media directory owns."""
    return frozenset(
        {
            MEDIA_ENCODE_MANIFEST_FILENAME,
            media_filename(episode_id),
            sidecar_filename(episode_id, SRT_SUFFIX),
            sidecar_filename(episode_id, VTT_SUFFIX),
            PROVENANCE_DIRECTORY,
        }
    )


PROVENANCE_DIRECTORY_ENTRIES: Final = frozenset(
    {ASSEMBLY_MANIFEST_COPY_FILENAME, CAPTIONS_MANIFEST_COPY_FILENAME}
)
"""Exactly the two entries a finished ``provenance/`` directory owns."""


def classify_media_encode_directory_entry(
    name: str, *, episode_id: str, is_directory: bool = False
) -> str:
    """Say what a top-level entry in a final-media directory is.

    Three answers, on the Phase 33 template with this phase's own explicit extension:

    * ``"owned"`` -- one of the five entries a finished directory owns.
    * ``"partial"`` -- a ``.writing`` OR ``.encoding`` working form of this phase's own
      files (the preflight and snapshot temporaries included). Recoverable, and not
      evidence of anything hostile, but proof the directory is not the finished thing it
      presents itself as.
    * ``"foreign"`` -- anything else.

    Nothing is deleted on the strength of this. It decides what a refusal says.
    """
    owned = final_media_directory_entries(episode_id)
    if name in owned:
        return "owned"
    if is_directory:
        return "foreign"
    if name in (PREFLIGHT_MEDIA_FILENAME, PREFLIGHT_AUDIO_FILENAME, SNAPSHOT_AUDIO_FILENAME):
        return "partial"
    for suffix in (WRITING_SUFFIX, ENCODING_SUFFIX):
        if name.endswith(suffix):
            written = name[: -len(suffix)]
            if written in owned or written in (PREFLIGHT_AUDIO_FILENAME, SNAPSHOT_AUDIO_FILENAME):
                return "partial"
    return "foreign"


def classify_media_encode_provenance_entry(name: str, *, is_directory: bool = False) -> str:
    """Say what a top-level entry in a ``provenance/`` directory is.

    The same three-answer contract, scoped to the two manifest-copy filenames.
    """
    if name in PROVENANCE_DIRECTORY_ENTRIES:
        return "owned"
    if not is_directory and name.endswith(WRITING_SUFFIX):
        written = name[: -len(WRITING_SUFFIX)]
        if written in PROVENANCE_DIRECTORY_ENTRIES:
            return "partial"
    return "foreign"


__all__ = [
    "AAC_BITRATE",
    "ASSEMBLY_DIR_TOKEN",
    "ASSEMBLY_MANIFEST_COPY_FILENAME",
    "AUDIO_CODEC",
    "CAPTIONS_MANIFEST_COPY_FILENAME",
    "ENCODING_SUFFIX",
    "FFMPEG_MAJOR",
    "MEDIA_ENCODE_MANIFEST_FILENAME",
    "MEDIA_ENCODE_MANIFEST_FORMAT",
    "MEDIA_ENCODE_PROFILE_V1",
    "MEDIA_ENCODE_SCHEMA_VERSION",
    "MP4_SUFFIX",
    "MediaEncodeRefused",
    "PARTIAL_SUFFIX",
    "PIX_FMT",
    "PREFLIGHT_AUDIO_FILENAME",
    "PREFLIGHT_MEDIA_FILENAME",
    "PROVENANCE_DIRECTORY",
    "PROVENANCE_DIRECTORY_ENTRIES",
    "SNAPSHOT_AUDIO_FILENAME",
    "STAGING_TOKEN",
    "VIDEO_CODEC",
    "VIDEO_THREADS",
    "WRITING_SUFFIX",
    "X264_CRF",
    "X264_PRESET",
    "classify_media_encode_directory_entry",
    "classify_media_encode_provenance_entry",
    "final_media_directory_entries",
    "media_encode_id",
    "media_filename",
    "media_temp_filename",
]
