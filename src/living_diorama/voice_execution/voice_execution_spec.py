"""Phase 29 voice execution policy: naming, directory shape and structural rails.

An episode voice execution turns a reviewed Phase 28 voice plan into real
speech: one canonical WAV per voice unit, plus the manifest that proves what
was actually produced. Nothing here synthesizes anything -- this module holds
only the deterministic vocabulary every other Phase 29 module shares: the
format and schema identity of the manifest, the exact names a voice execution
directory and its files carry, and this layer's own independent plausibility
rail on a measured sample count.

THE VOICE EXECUTION MANIFEST RECORDS WHAT WAS ACTUALLY PRODUCED. IT MEASURES
NOTHING ITSELF -- the audit and the executor measure; this module only names
what they measure.
"""

from typing import Final

VOICE_MANIFEST_FORMAT: Final = "living_diorama_episode_voice_manifest"
"""The format tag every episode voice manifest declares."""

VOICE_MANIFEST_SCHEMA_VERSION: Final = 1
"""The voice manifest schema version this build reads and writes."""

SUPPORTED_VOICE_PLAN_SCHEMA_VERSION: Final = 1
"""The Phase 28 voice plan schema version this build executes."""

SPEECH_DIRECTORY: Final = "speech"
"""Where the executed speech WAVs are written, relative to the voice directory."""

UNIT_AUDIO_NAME_TEMPLATE: Final = "voice_unit_%04d.wav"
"""Deterministic, sortable, positional unit audio naming.

The number is the unit's position, not a counter, so a file name is
traceable back to the plan without consulting anything else -- the exact
naming discipline ``FRAME_NAME_TEMPLATE`` uses for a semantic frame number.
"""

VOICE_PLAN_FILENAME: Final = "episode_voice_plan.json"
"""The plan-copy filename inside a voice execution directory."""

VOICE_MANIFEST_FILENAME: Final = "episode_voice_manifest.json"
"""The manifest filename inside a voice execution directory."""

PARTIAL_SUFFIX: Final = ".partial"
"""Appended to a voice execution id to name its sibling staging directory.

Phase 29 stages a whole episode before publishing it in one atomic
directory rename, so the scratch directory is a *sibling* of the final
directory -- ``<id>.partial`` next to ``<id>`` -- never a subdirectory
inside either one.
"""

WRITING_SUFFIX: Final = ".writing"
"""Appended to a document filename while it is being written atomically."""

VOICE_DIRECTORY_ENTRIES: Final = frozenset(
    {VOICE_PLAN_FILENAME, VOICE_MANIFEST_FILENAME, SPEECH_DIRECTORY}
)
"""Exactly the three entries a finished voice execution directory owns."""

UNIT_RESULT_FIELDS: Final = ("bytes", "sha256", "speech_samples")
"""Everything a result says about a unit's WAV that the file itself can answer for.

Named once so every comparison -- the manifest builder's input contract, a
future audit's re-derivation -- covers the same three fields.
"""

MAX_SPEECH_SAMPLES: Final = 1_000_000_000
"""This layer's own structural rail on a voice unit's ``speech_samples``.

Deliberately an independent literal, never computed at import time, for the
same reason ``MAX_VOICE_CAPACITY_SAMPLES`` gives for its own independence:
standalone validation of a voice manifest document never opens a second
document, so at that point there is no proven capacity to compare against,
and no rail can be derived from a value that is not available. This is a
**plausibility ceiling only** -- it is never FIT authority. The one
authoritative FIT law compares a unit's actual, recomputed ``speech_samples``
against its actual, bound ``capacity_samples``, never against this constant.
"""

DEVICE_CPU: Final = "cpu"
"""The only device this build's execution law permits."""

SPACY_MODEL: Final = "en_core_web_sm"
"""The only spaCy model name this build's G2P policy permits, pinned local-only."""


def voice_execution_id(*, mode: str, episode: int, previous_episode: int | None) -> str:
    """Return the deterministic directory name for one episode's voice execution.

    Two different legs can never collide, and the same leg always lands in
    the same place -- so a re-run resumes its own execution instead of
    scattering copies, and a different leg cannot be mistaken for this one by
    name alone. Identity is still proved by digest inside the directory; this
    is the human-legible half. Reproduces the render-execution naming
    templates exactly, one layer down.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If the mode is unknown, an episode is negative, or the
            episode pair is not a direct succession.
    """
    if type(mode) is not str:
        raise TypeError(f"mode must be a str, got {type(mode).__name__}")
    if isinstance(episode, bool) or not isinstance(episode, int):
        raise TypeError(f"episode must be an int, got {episode!r}")
    if episode < 0:
        raise ValueError(f"episode must not be negative, got {episode}")
    if mode == "baseline":
        if previous_episode is not None:
            raise ValueError("a baseline voice execution has no previous episode")
        return f"episode_{episode:04d}_baseline"
    if mode == "transition":
        if isinstance(previous_episode, bool) or not isinstance(previous_episode, int):
            raise TypeError(f"previous_episode must be an int, got {previous_episode!r}")
        if previous_episode < 0:
            raise ValueError(f"previous_episode must not be negative, got {previous_episode}")
        if episode != previous_episode + 1:
            raise ValueError(
                f"episode {episode} does not directly follow {previous_episode}; Phase 29 "
                "executes the transition Phase 28 planned and derives no other pairing"
            )
        return f"episode_{previous_episode:04d}_to_{episode:04d}"
    raise ValueError(f"unknown episode mode {mode!r}")


def unit_audio_filename(position: int) -> str:
    """Return the deterministic file name for one voice unit's speech, by position.

    Raises:
        TypeError: If the position is not an int.
        ValueError: If the position is not positive or would not fit the field.
    """
    if isinstance(position, bool) or not isinstance(position, int):
        raise TypeError(f"position must be an int, got {position!r}")
    if position < 1:
        raise ValueError(f"position must be positive, got {position}")
    if position > 9999:
        raise ValueError(
            f"position {position} does not fit the four-digit naming field; widening it is a "
            "reviewed schema change"
        )
    return UNIT_AUDIO_NAME_TEMPLATE % position


def classify_voice_directory_entry(name: str, *, is_directory: bool = False) -> str:
    """Say what a top-level entry in a voice execution directory is.

    Three answers:

    * ``"owned"`` -- one of the three entries a finished execution owns.
    * ``"partial"`` -- a ``.writing`` temporary of one of the two documents
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
    if name in VOICE_DIRECTORY_ENTRIES:
        return "owned"
    if not is_directory and name.endswith(WRITING_SUFFIX):
        written = name[: -len(WRITING_SUFFIX)]
        if written in {VOICE_PLAN_FILENAME, VOICE_MANIFEST_FILENAME}:
            return "partial"
    return "foreign"
