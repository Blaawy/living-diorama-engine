"""Phase 33 media assembly policy: naming, directory shape and structural rails.

An episode media assembly turns an accepted Phase 23 render, an accepted Phase 27
presentation plan and an accepted Phase 31 audio composition into one self-contained,
provenance-bound, pre-encode directory: a physical presentation-rate PNG sequence, the
unchanged episode WAV, byte copies of every document it bound, and its own assembly
manifest. Nothing here decides anything -- this module holds only the deterministic
vocabulary every other Phase 33 module shares: the format identity of the manifest, the
exact names an assembly directory and its files carry, and the frame-filename grammar.

PHASE 33 REALIZES A LOCKED PRESENTATION ONTO LOCKED RENDERED ASSETS. IT DECIDES NOTHING --
the assembler only copies bytes a locked Phase 27 plan and a locked Phase 23 manifest
already determined, and carries the Phase 31 track unchanged; this module only names what
it copies.
"""

from typing import Final

from living_diorama.render_execution.render_execution_spec import render_id

MEDIA_ASSEMBLY_MANIFEST_FORMAT: Final = "living_diorama_episode_media_assembly_manifest"
"""The format tag every episode media assembly manifest declares."""

MEDIA_ASSEMBLY_MANIFEST_SCHEMA_VERSION: Final = 1
"""The media assembly manifest schema version this build reads and writes."""

RENDER_MANIFEST_COPY_FILENAME: Final = "episode_render_manifest.json"
"""The exact-byte copy filename of the bound Phase 23 manifest inside an assembly."""

PRESENTATION_PLAN_COPY_FILENAME: Final = "episode_presentation_plan.json"
"""The exact-byte copy filename of the bound Phase 27 plan inside an assembly."""

AUDIO_COMPOSITION_MANIFEST_COPY_FILENAME: Final = "episode_audio_composition_manifest.json"
"""The exact-byte copy filename of the bound Phase 31 manifest inside an assembly."""

MEDIA_ASSEMBLY_MANIFEST_FILENAME: Final = "episode_media_assembly_manifest.json"
"""The assembly manifest filename inside an assembly directory."""

PROVENANCE_DIRECTORY: Final = "provenance"
"""Where the two verification witnesses are written, relative to the assembly directory.

These two documents are read for nothing but a digest field; they govern no output byte.
The directory carries that distinction structurally, separate from the four top-level
documents Phase 33 reads decision-bearing content from.
"""

DELIVERY_PLAN_COPY_FILENAME: Final = "episode_narration_delivery_plan.json"
"""The exact-byte copy filename of the bound Phase 25 witness, inside ``provenance/``.

Declared independently of ``living_diorama.narration_delivery`` rather than imported from
it: the witness's name inside a Phase 33 directory is this phase's own contract, restated,
and a dedicated test asserts the two string values still agree so drift fails loudly.
"""

SHOT_PLAN_COPY_FILENAME: Final = "shot_direction_plan.json"
"""The exact-byte copy filename of the bound Phase 22 witness, inside ``provenance/``."""

PRESENTATION_DIRECTORY: Final = "presentation"
"""Where the realized presentation-rate PNG sequence is written."""

AUDIO_DIRECTORY: Final = "audio"
"""Where the carried episode WAV is written, relative to the assembly directory."""

EPISODE_AUDIO_FILENAME: Final = "episode_audio.wav"
"""The one carried episode-length WAV's filename, inside ``AUDIO_DIRECTORY``."""

PRESENTATION_FRAME_NAME_TEMPLATE: Final = "frame_%07d.png"
"""Deterministic, sortable, presentation-coordinate frame naming.

Seven digits, because Phase 27's own ``MAX_PRESENTATION_FRAME`` is 1,000,000 inclusive and
six digits cannot represent it. Lexical ordering equals numeric ordering for the whole
domain, because the width is fixed and every character is an ASCII digit.
"""

PRESENTATION_FRAME_DIGITS: Final = 7
"""The exact digit width the frame-filename grammar requires."""

MAX_ASSEMBLY_PRESENTATION_FRAME: Final = 1_000_000
"""This layer's own structural rail on a presentation-frame coordinate.

Restated from ``presentation_spec.MAX_PRESENTATION_FRAME`` rather than imported, for the
same reason every phase in this chain restates rather than imports a sibling's rail: this
contract's shape belongs to this schema version, and a drift test asserts the two values
still agree.
"""

PARTIAL_SUFFIX: Final = ".partial"
"""Appended to an assembly id to name its sibling staging directory."""

WRITING_SUFFIX: Final = ".writing"
"""Appended to a document filename while it is being written atomically."""

ROLE_PLAYBACK: Final = "playback"
"""Restated from ``render_execution_spec.ROLE_PLAYBACK``; a drift test asserts agreement.

Declared here, rather than imported and used directly, for the same reason every other
restated constant in this module is declared here: this phase's own vocabulary is its own
contract, and importing render_execution's role string directly into comparison logic
would make an upstream rename a silent Phase 33 behaviour change instead of a loud test
failure.
"""

ASSEMBLY_DIRECTORY_ENTRIES: Final = frozenset(
    {
        RENDER_MANIFEST_COPY_FILENAME,
        PRESENTATION_PLAN_COPY_FILENAME,
        AUDIO_COMPOSITION_MANIFEST_COPY_FILENAME,
        MEDIA_ASSEMBLY_MANIFEST_FILENAME,
        PRESENTATION_DIRECTORY,
        AUDIO_DIRECTORY,
        PROVENANCE_DIRECTORY,
    }
)
"""Exactly the seven top-level entries a finished assembly directory owns."""

PROVENANCE_DIRECTORY_ENTRIES: Final = frozenset(
    {DELIVERY_PLAN_COPY_FILENAME, SHOT_PLAN_COPY_FILENAME}
)
"""Exactly the two entries a finished ``provenance/`` directory owns."""

_DOCUMENT_FILENAMES: Final = (
    RENDER_MANIFEST_COPY_FILENAME,
    PRESENTATION_PLAN_COPY_FILENAME,
    AUDIO_COMPOSITION_MANIFEST_COPY_FILENAME,
    MEDIA_ASSEMBLY_MANIFEST_FILENAME,
)

_ASCII_DIGITS: Final = frozenset("0123456789")
"""The only characters a presentation-frame filename's digit field may hold.

Deliberately not ``str.isdigit()`` or ``str.isdecimal()``: both accept non-ASCII digit
characters (Arabic-Indic, fullwidth), which would let a foreign file be classified as
Phase 33's own.
"""

_FRAME_PREFIX: Final = "frame_"
_FRAME_SUFFIX: Final = ".png"


def media_assembly_id(*, mode: str, episode: int, previous_episode: int | None) -> str:
    """Return the deterministic directory name for one episode's media assembly.

    Delegates whole to :func:`living_diorama.render_execution.render_execution_spec.render_id`
    rather than re-implementing the naming law: one owner for the episode-directory naming
    law, exactly as :mod:`living_diorama.audio_composition.audio_composition_spec` delegates
    its own ``audio_composition_id`` to ``voice_execution_id``.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If the mode is unknown, an episode is negative, or the episode pair is
            not a direct succession.
    """
    return render_id(mode=mode, episode=episode, previous_episode=previous_episode)


def presentation_frame_filename(presentation_frame: int) -> str:
    """Return the deterministic file name for one presentation frame.

    Raises:
        TypeError: If ``presentation_frame`` is not an ``int`` (a ``bool`` is refused
            because it subclasses ``int``).
        ValueError: If ``presentation_frame`` is not within
            ``[1, MAX_ASSEMBLY_PRESENTATION_FRAME]``.
    """
    if isinstance(presentation_frame, bool) or not isinstance(presentation_frame, int):
        raise TypeError(f"presentation_frame must be an int, got {presentation_frame!r}")
    if presentation_frame < 1:
        raise ValueError(f"presentation_frame must be positive, got {presentation_frame}")
    if presentation_frame > MAX_ASSEMBLY_PRESENTATION_FRAME:
        raise ValueError(
            f"presentation_frame must be within [1, {MAX_ASSEMBLY_PRESENTATION_FRAME}], "
            f"got {presentation_frame}"
        )
    return PRESENTATION_FRAME_NAME_TEMPLATE % presentation_frame


def presentation_frame_relative_path(presentation_frame: int) -> str:
    """Return one presentation frame's deterministic path, relative to the assembly directory."""
    return f"{PRESENTATION_DIRECTORY}/{presentation_frame_filename(presentation_frame)}"


def episode_audio_relative_path() -> str:
    """Return the carried track's one deterministic path, relative to the assembly directory."""
    return f"{AUDIO_DIRECTORY}/{EPISODE_AUDIO_FILENAME}"


def delivery_plan_relative_path() -> str:
    """Return the delivery witness's one deterministic path, relative to the assembly directory."""
    return f"{PROVENANCE_DIRECTORY}/{DELIVERY_PLAN_COPY_FILENAME}"


def shot_plan_relative_path() -> str:
    """Return the shot witness's one deterministic path, relative to the assembly directory."""
    return f"{PROVENANCE_DIRECTORY}/{SHOT_PLAN_COPY_FILENAME}"


def is_presentation_frame_filename(name: str) -> bool:
    """Return whether ``name`` is exactly one legal presentation-frame filename.

    Tests the digit field against an explicit ASCII digit set, never ``str.isdigit()`` or
    ``int()`` alone -- both accept non-ASCII digit characters, which would let a foreign
    file be classified as owned.
    """
    if not (name.startswith(_FRAME_PREFIX) and name.endswith(_FRAME_SUFFIX)):
        return False
    digits = name[len(_FRAME_PREFIX) : -len(_FRAME_SUFFIX)]
    if len(digits) != PRESENTATION_FRAME_DIGITS:
        return False
    if not all(character in _ASCII_DIGITS for character in digits):
        return False
    value = int(digits)
    return 1 <= value <= MAX_ASSEMBLY_PRESENTATION_FRAME


def classify_media_assembly_directory_entry(name: str, *, is_directory: bool = False) -> str:
    """Say what a top-level entry in an assembly directory is.

    Three answers:

    * ``"owned"`` -- one of the seven entries a finished assembly owns.
    * ``"partial"`` -- a ``.writing`` temporary of one of the four documents this phase
      writes atomically. Recoverable, and not evidence of anything hostile, but proof the
      directory is not the finished thing it presents itself as.
    * ``"foreign"`` -- anything else.

    Nothing is deleted on the strength of this. It decides what a refusal says.

    Args:
        name: The entry's own file name (not a path).
        is_directory: Whether the entry is a directory.
    """
    if name in ASSEMBLY_DIRECTORY_ENTRIES:
        return "owned"
    if not is_directory and name.endswith(WRITING_SUFFIX):
        written = name[: -len(WRITING_SUFFIX)]
        if written in _DOCUMENT_FILENAMES:
            return "partial"
    return "foreign"


def classify_provenance_directory_entry(name: str, *, is_directory: bool = False) -> str:
    """Say what a top-level entry in a ``provenance/`` directory is.

    The same three-answer contract as :func:`classify_media_assembly_directory_entry`,
    scoped to the two witness filenames.
    """
    if name in PROVENANCE_DIRECTORY_ENTRIES:
        return "owned"
    if not is_directory and name.endswith(WRITING_SUFFIX):
        written = name[: -len(WRITING_SUFFIX)]
        if written in PROVENANCE_DIRECTORY_ENTRIES:
            return "partial"
    return "foreign"


__all__ = [
    "ASSEMBLY_DIRECTORY_ENTRIES",
    "AUDIO_COMPOSITION_MANIFEST_COPY_FILENAME",
    "AUDIO_DIRECTORY",
    "DELIVERY_PLAN_COPY_FILENAME",
    "EPISODE_AUDIO_FILENAME",
    "MAX_ASSEMBLY_PRESENTATION_FRAME",
    "MEDIA_ASSEMBLY_MANIFEST_FILENAME",
    "MEDIA_ASSEMBLY_MANIFEST_FORMAT",
    "MEDIA_ASSEMBLY_MANIFEST_SCHEMA_VERSION",
    "PARTIAL_SUFFIX",
    "PRESENTATION_DIRECTORY",
    "PRESENTATION_FRAME_DIGITS",
    "PRESENTATION_FRAME_NAME_TEMPLATE",
    "PRESENTATION_PLAN_COPY_FILENAME",
    "PROVENANCE_DIRECTORY",
    "PROVENANCE_DIRECTORY_ENTRIES",
    "ROLE_PLAYBACK",
    "SHOT_PLAN_COPY_FILENAME",
    "WRITING_SUFFIX",
    "classify_media_assembly_directory_entry",
    "classify_provenance_directory_entry",
    "delivery_plan_relative_path",
    "episode_audio_relative_path",
    "is_presentation_frame_filename",
    "media_assembly_id",
    "presentation_frame_filename",
    "presentation_frame_relative_path",
    "shot_plan_relative_path",
]
