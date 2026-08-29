"""Phase 34 caption serialization policy: naming, directory shape and the carriage law.

A caption serialization gives the locked Phase 32 caption plan the one thing it
deliberately lacks -- a target file format -- by serializing its cues into two
byte-sealed sidecar artifacts on the wall-clock representation those formats
require. Nothing here rewords, wraps, styles, measures or encodes anything: this
module holds only the deterministic vocabulary every other Phase 34 module
shares -- the format identity of the manifest, the exact names a captions
directory and its files carry, and the one carriage-compatibility law.

THE CAPTION SERIALIZATION MAKES A LOCKED PLAN LEGIBLE TO A TARGET FILE FORMAT.
IT DECIDES NO TIMING AND NO WORDING -- the serializer only re-expresses spans a
locked Phase 32 plan already determined, under one pinned integer timestamp law,
and carries every sentence verbatim or not at all.
"""

from typing import Final

from living_diorama.render_execution.render_execution_spec import render_id

CAPTION_SERIALIZATION_MANIFEST_FORMAT: Final = (
    "living_diorama_episode_caption_serialization_manifest"
)
"""The format tag every episode caption serialization manifest declares."""

CAPTION_SERIALIZATION_SCHEMA_VERSION: Final = 1
"""The caption serialization manifest schema version this build reads and writes."""

CAPTION_TIMESTAMP_POLICY_V1: Final = "caption_timestamp_policy_v1"
"""The one timestamp derivation policy this build derives and validates.

Declared in the document rather than merely implied, so an artifact serialized
under a revised derivation law can never be mistaken for this one.
"""

CAPTION_SERIALIZATION_MANIFEST_FILENAME: Final = "episode_caption_serialization_manifest.json"
"""The manifest filename inside a captions directory."""

CAPTION_PLAN_COPY_FILENAME: Final = "episode_caption_plan.json"
"""The exact-byte copy filename of the bound Phase 32 plan inside a captions directory."""

SRT_SUFFIX: Final = ".srt"
"""The SRT sidecar's filename suffix, appended to the episode id."""

VTT_SUFFIX: Final = ".vtt"
"""The WebVTT sidecar's filename suffix, appended to the episode id."""

SRT_FORMAT_NAME: Final = "srt"
"""The format literal the manifest's SRT sidecar record declares."""

VTT_FORMAT_NAME: Final = "webvtt"
"""The format literal the manifest's WebVTT sidecar record declares."""

MAX_TIMESTAMP_MS: Final = 360_000_000
"""The frozen target-format representation rail: two-digit hours, exclusive.

A derived boundary at or beyond 100 hours cannot be carried by the frozen
``HH:MM:SS`` widths, so the serializer refuses it. This is a representation
limit of the target file formats -- the same refusal class as the
carriage-compatibility law below -- never a re-validation of upstream truth:
it is reachable only from standalone plans at fps 1 or 2 under
``MAX_CAPTION_FRAME``, and the canonical chain's pinned 24 fps tops out near
11.6 hours.
"""

PARTIAL_SUFFIX: Final = ".partial"
"""Appended to a captions directory id to name its sibling staging directory."""

WRITING_SUFFIX: Final = ".writing"
"""Appended to an owned filename while it is being written atomically."""

_FORBIDDEN_TEXT_SUBSTRING: Final = "-->"
"""The cue-timing arrow; inside cue text it is structurally ambiguous in both grammars."""

_LINE_SEPARATORS: Final = ("\u2028", "\u2029")
"""Unicode line and paragraph separators; a one-physical-line law admits neither."""


class CaptionSerializationRefused(ValueError):
    """The plan, a sentence, or a derived value refuses this serialization."""


def caption_serialization_id(*, mode: str, episode: int, previous_episode: int | None) -> str:
    """Return the deterministic directory name for one episode's caption serialization.

    Delegates whole to :func:`living_diorama.render_execution.render_execution_spec.render_id`
    rather than re-implementing the naming law: one owner for the episode-directory naming
    law, exactly as ``media_assembly_id`` and ``audio_composition_id`` delegate theirs.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If the mode is unknown, an episode is negative, or the episode pair is
            not a direct succession.
    """
    return render_id(mode=mode, episode=episode, previous_episode=previous_episode)


def sidecar_filename(episode_id: str, suffix: str) -> str:
    """Return one sidecar's deterministic filename for this episode id.

    The basename equals the directory id, so the two sidecars sit beside the
    final episode file under the same-basename convention a downstream viewer
    relies on when manually enabling them.

    Raises:
        TypeError: If either value is not a ``str``.
        ValueError: If the suffix is not one of the two frozen sidecar suffixes.
    """
    if type(episode_id) is not str:
        raise TypeError(f"episode_id must be a str, got {type(episode_id).__name__}")
    if type(suffix) is not str:
        raise TypeError(f"suffix must be a str, got {type(suffix).__name__}")
    if suffix not in (SRT_SUFFIX, VTT_SUFFIX):
        raise ValueError(f"suffix must be {SRT_SUFFIX!r} or {VTT_SUFFIX!r}, got {suffix!r}")
    return f"{episode_id}{suffix}"


def require_carriable_caption_text(text: str, description: str) -> str:
    """Return the text if the frozen grammars can carry it verbatim, else refuse.

    The wording is Phase 26's and is never rewritten here: a sentence is carried
    byte-for-byte or refused. Refused exactly when the text contains a C0
    control character (CR, LF, NUL, TAB and the rest -- the one-physical-line
    and LF-only-structure laws admit no control byte inside carried text), a
    Unicode line or paragraph separator (U+2028, U+2029 -- a sentence holding
    one cannot honestly be one line), or the cue-timing arrow ``-->`` (a
    structural parse hazard in both grammars, and forbidden inside WebVTT cue
    text outright). Everything else -- including a mid-text U+FEFF, astral-plane
    characters and combining sequences -- is carried verbatim.

    Raises:
        TypeError: If the text is not a ``str``.
        CaptionSerializationRefused: If the text is empty or cannot be carried
            verbatim under the frozen grammars.
    """
    if type(text) is not str:
        raise TypeError(f"{description} must be a str, got {type(text).__name__}")
    if not text:
        raise CaptionSerializationRefused(
            f"{description} cannot be carried verbatim under the frozen grammars: it is "
            "empty, and an empty text line would terminate a cue block; the wording is "
            "Phase 26's and is never rewritten here"
        )
    for character in text:
        if ord(character) < 0x20:
            raise CaptionSerializationRefused(
                f"{description} cannot be carried verbatim under the frozen grammars: it "
                f"contains the control character {character!r}; the wording is Phase 26's "
                "and is never rewritten here"
            )
        if character in _LINE_SEPARATORS:
            raise CaptionSerializationRefused(
                f"{description} cannot be carried verbatim under the frozen grammars: it "
                f"contains the Unicode line separator {character!r}, so it cannot honestly "
                "be one physical line; the wording is Phase 26's and is never rewritten here"
            )
    if _FORBIDDEN_TEXT_SUBSTRING in text:
        raise CaptionSerializationRefused(
            f"{description} cannot be carried verbatim under the frozen grammars: it "
            f"contains the cue-timing arrow {_FORBIDDEN_TEXT_SUBSTRING!r}; the wording is "
            "Phase 26's and is never rewritten here"
        )
    return text


__all__ = [
    "CAPTION_PLAN_COPY_FILENAME",
    "CAPTION_SERIALIZATION_MANIFEST_FILENAME",
    "CAPTION_SERIALIZATION_MANIFEST_FORMAT",
    "CAPTION_SERIALIZATION_SCHEMA_VERSION",
    "CAPTION_TIMESTAMP_POLICY_V1",
    "CaptionSerializationRefused",
    "MAX_TIMESTAMP_MS",
    "PARTIAL_SUFFIX",
    "SRT_FORMAT_NAME",
    "SRT_SUFFIX",
    "VTT_FORMAT_NAME",
    "VTT_SUFFIX",
    "WRITING_SUFFIX",
    "caption_serialization_id",
    "require_carriable_caption_text",
    "sidecar_filename",
]
