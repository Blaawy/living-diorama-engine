"""Phase 31 audio composition policy: naming, directory shape and structural rails.

An episode audio composition turns a sealed Phase 30 audio track plan and an
audited Phase 29 voice execution into real bytes: one canonical episode-length
WAV, plus the manifest that proves what was actually produced. Nothing here
places anything -- this module holds only the deterministic vocabulary every
other Phase 31 module shares: the format identity of the manifest, the exact
names a composition directory and its files carry, and this layer's own
independent plausibility rail on a measured track length.

AUDIO COMPOSITION WRITES A PLACED EPISODE'S ONE TRACK. IT PLACES NOTHING --
the composer only copies what Phase 30 already sealed and Phase 29 already
measured; this module only names what it copies.
"""

from typing import Final

from living_diorama.voice_execution.voice_execution_spec import voice_execution_id

AUDIO_COMPOSITION_MANIFEST_FORMAT: Final = "living_diorama_episode_audio_composition_manifest"
"""The format tag every episode audio composition manifest declares."""

AUDIO_COMPOSITION_MANIFEST_SCHEMA_VERSION: Final = 1
"""The audio composition manifest schema version this build reads and writes."""

AUDIO_TRACK_PLAN_FILENAME: Final = "episode_audio_track_plan.json"
"""The exact-byte plan copy filename inside a composition directory."""

VOICE_MANIFEST_FILENAME: Final = "episode_voice_manifest.json"
"""The exact-byte source-witness filename inside a composition directory.

Declared independently of ``living_diorama.voice_execution.voice_execution_spec``
rather than imported from it: the witness's name inside a Phase 31 directory
is this phase's own contract, restated, and a dedicated test asserts the two
string values still agree so drift fails loudly.
"""

AUDIO_COMPOSITION_MANIFEST_FILENAME: Final = "episode_audio_composition_manifest.json"
"""The composition manifest filename inside a composition directory."""

AUDIO_DIRECTORY: Final = "audio"
"""Where the composed track is written, relative to the composition directory."""

EPISODE_AUDIO_FILENAME: Final = "episode_audio.wav"
"""The one composed episode-length WAV's filename, inside ``AUDIO_DIRECTORY``."""

COMPOSITION_DIRECTORY_ENTRIES: Final = frozenset(
    {
        AUDIO_TRACK_PLAN_FILENAME,
        VOICE_MANIFEST_FILENAME,
        AUDIO_DIRECTORY,
        AUDIO_COMPOSITION_MANIFEST_FILENAME,
    }
)
"""Exactly the four entries a finished composition directory owns."""

PARTIAL_SUFFIX: Final = ".partial"
"""Appended to a composition id to name its sibling staging directory."""

WRITING_SUFFIX: Final = ".writing"
"""Appended to a document filename while it is being written atomically."""

AUDIO_RESULT_FIELDS: Final = ("audio_samples", "bytes", "channels", "sample_rate_hz", "sha256")
"""Everything a composition says about its track that the file itself can answer for.

Deliberately no ``file``: the composed track's path is positional and
deterministic, derived by :func:`episode_audio_relative_path`, never supplied
by a caller.
"""

SPAN_RESULT_FIELDS: Final = ("pcm_sha256",)
"""The one new measured fact a placed span adds beyond what Phase 30 already sealed."""

MAX_EPISODE_AUDIO_SAMPLES: Final = 1_000_000_000
"""This layer's own structural rail on the composed track's total sample count.

Deliberately an independent literal, never computed at import time, for the
same reason ``MAX_AUDIO_TRACK_SAMPLES`` is independent: standalone validation
of a composition manifest never opens a second document, so at that point
there is no proven presentation total to compare against. This is a
plausibility ceiling only, never length authority -- the one authoritative
track length is recomputed, in the cross-check, from the actual sealed Phase
30 plan.
"""


def audio_composition_id(*, mode: str, episode: int, previous_episode: int | None) -> str:
    """Return the deterministic directory name for one episode's audio composition.

    Delegates whole to
    :func:`living_diorama.voice_execution.voice_execution_spec.voice_execution_id`
    rather than re-implementing the naming law: one owner for the
    episode-directory naming law, exactly as
    :mod:`living_diorama.audio_track.audio_track_spec` re-exports
    ``samples_per_presentation_frame`` rather than restating the crossing law.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If the mode is unknown, an episode is negative, or the
            episode pair is not a direct succession.
    """
    return voice_execution_id(mode=mode, episode=episode, previous_episode=previous_episode)


def episode_audio_relative_path() -> str:
    """Return the composed track's one deterministic path, relative to the composition directory."""
    return f"{AUDIO_DIRECTORY}/{EPISODE_AUDIO_FILENAME}"


def classify_audio_composition_directory_entry(name: str, *, is_directory: bool = False) -> str:
    """Say what a top-level entry in a composition directory is.

    Three answers:

    * ``"owned"`` -- one of the four entries a finished composition owns.
    * ``"partial"`` -- a ``.writing`` temporary of one of the three documents
      this phase writes atomically. Recoverable, and not evidence of
      anything hostile, but proof the directory is not the finished thing it
      presents itself as.
    * ``"foreign"`` -- anything else.

    Nothing is deleted on the strength of this. It decides what a refusal
    says.

    Args:
        name: The entry's own file name (not a path).
        is_directory: Whether the entry is a directory.
    """
    if name in COMPOSITION_DIRECTORY_ENTRIES:
        return "owned"
    if not is_directory and name.endswith(WRITING_SUFFIX):
        written = name[: -len(WRITING_SUFFIX)]
        if written in {
            AUDIO_TRACK_PLAN_FILENAME,
            VOICE_MANIFEST_FILENAME,
            AUDIO_COMPOSITION_MANIFEST_FILENAME,
        }:
            return "partial"
    return "foreign"


__all__ = [
    "AUDIO_COMPOSITION_MANIFEST_FILENAME",
    "AUDIO_COMPOSITION_MANIFEST_FORMAT",
    "AUDIO_COMPOSITION_MANIFEST_SCHEMA_VERSION",
    "AUDIO_DIRECTORY",
    "AUDIO_RESULT_FIELDS",
    "AUDIO_TRACK_PLAN_FILENAME",
    "COMPOSITION_DIRECTORY_ENTRIES",
    "EPISODE_AUDIO_FILENAME",
    "MAX_EPISODE_AUDIO_SAMPLES",
    "PARTIAL_SUFFIX",
    "SPAN_RESULT_FIELDS",
    "VOICE_MANIFEST_FILENAME",
    "WRITING_SUFFIX",
    "audio_composition_id",
    "classify_audio_composition_directory_entry",
    "episode_audio_relative_path",
]
