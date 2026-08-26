"""Phase 28 voice policy: the closed, reviewable narrator identity and clock law.

An episode voice plan decides two things: which one reviewed narrator request
speaks every locked realized sentence, and how many audio samples of that
narrator's speech a Phase 27 presentation window has room for. Nothing here
synthesizes, nothing here measures a waveform, and nothing here reads a
sentence -- the policy is pure identity and pure arithmetic, so the whole of
it is the pinned request below and the one clock-crossing law that turns a
window's presentation frames into a sample budget.

THE VOICE PLAN DEFINES REVIEWED SPEECH AND REVIEWED CAPACITY. IT MEASURES
NOTHING.

The narrator identity is a single Director-reviewed request, pinned at every
field a future re-synthesis must reproduce exactly: engine, model artifact
digests, voice-pack digest, language, speed, sample rate, channel count and
seed. Changing any one field is a reviewed policy version change, never a
quiet edit -- exactly as the presentation window floors are part of Phase
27's own schema version.
"""

from types import MappingProxyType
from typing import Final

VOICE_PLAN_FORMAT: Final = "living_diorama_episode_voice_plan"
"""The format tag every episode voice plan declares."""

VOICE_PLAN_SCHEMA_VERSION: Final = 1
"""The voice plan schema version this build reads and writes.

Independent from the realization and presentation schema versions. The
narrator identity and the clock law in this module are part of this version.
"""

VOICE_POLICY_V1: Final = "voice_policy_v1"
"""The one voice policy this build derives and validates.

Declared in the document rather than merely implied, so a plan written under
a revised policy -- a different narrator, a different speed, a different
sample rate -- can never be mistaken for this one. The validator requires the
field to equal this constant exactly.
"""

VOICE_UNIT_ID_FORM: Final = "voice_unit_%04d"
"""A voice-unit identifier is positional and nothing else, so it is derivable.

A record sits at the position of the narration unit -- and therefore the
presentation window and the realization -- it speaks. One index carries the
whole one-voice-unit-per-unit accounting contract.
"""

ENGINE: Final = "kokoro"
ENGINE_VERSION: Final = "0.9.4"
G2P: Final = "misaki"
G2P_VERSION: Final = "0.9.4"
MODEL_REPOSITORY: Final = "hexgrad/Kokoro-82M"
MODEL_REVISION: Final = "f3ff3571791e39611d31c381e3a41a3af07b4987"
MODEL_WEIGHTS_SHA256: Final = "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4"
MODEL_CONFIG_SHA256: Final = "5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f"
VOICE: Final = "af_heart"
VOICE_PACK_SHA256: Final = "0ab5709b8ffab19bfd849cd11d98f75b60af7733253ad0d67b12382a102cb4ff"
LANG_CODE: Final = "a"
SPEED_PERCENT: Final = 100
SAMPLE_RATE_HZ: Final = 24_000
CHANNELS: Final = 1
SEED: Final = 0
"""The pinned narrator request, field by field.

Every value is Director-reviewed evidence, not a guess: the model and
voice-pack digests were retrieved and independently re-hashed against the
published Hugging Face artifacts (``hexgrad/Kokoro-82M`` at the pinned
revision); ``seed`` is fixed because a fixed seed reproduced the same
waveform digest across independent processes on the reviewed synthesis
environment, giving a downstream execution phase a realistic path to
byte-reproducibility -- though byte-reproducibility itself is never a claim
this plan makes. ``speed_percent`` is an integer percentage, never a float,
so no float ever enters this contract for a value that is conceptually a
ratio.
"""

VOICE_BLOCK: Final = MappingProxyType(
    {
        "engine": ENGINE,
        "engine_version": ENGINE_VERSION,
        "g2p": G2P,
        "g2p_version": G2P_VERSION,
        "model_repository": MODEL_REPOSITORY,
        "model_revision": MODEL_REVISION,
        "model_weights_sha256": MODEL_WEIGHTS_SHA256,
        "model_config_sha256": MODEL_CONFIG_SHA256,
        "voice": VOICE,
        "voice_pack_sha256": VOICE_PACK_SHA256,
        "lang_code": LANG_CODE,
        "speed_percent": SPEED_PERCENT,
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "channels": CHANNELS,
        "seed": SEED,
    }
)
"""The one frozen narrator request, restated verbatim in every voice plan.

A single source of truth: the planner writes this mapping unchanged, the
standalone schema requires a plan's ``voice`` block to equal it field for
field, and the source cross-check re-asserts the same equality as part of
its own completeness report. No module holds a second copy of any of these
fifteen values.
"""

MAX_VOICE_CAPACITY_SAMPLES: Final = 1_000_000_000
"""This layer's own structural rail on a voice unit's ``capacity_samples``.

Deliberately an independent literal, never computed at import time. The
reason is not that a source-derived maximum would require hard-coding fps:
the source cross-check genuinely has a real, gate-proven fps in hand and
already derives exact capacity from it, with no Python literal for 24
anywhere. The reason this rail is independent is narrower and structural --
*standalone* validation of a voice plan document never opens a second
document, so at that point in the chain there is no proven fps to compute
with at all, and no rail can be derived from a value that is not available.
This rail exists on the same reasoning ``presentation_spec.MAX_PRESENTATION_FRAME``
gave for its own independence from Phase 17's ``MAX_TIMELINE_FRAME``: a third
clock introduces its own plausible range. Its magnitude is worth comparing
by hand to ``MAX_PRESENTATION_FRAME`` (1,000,000 frames) times the canonical
1,000-samples-per-frame pairing this policy pins at 24,000 Hz -- both read as
roughly 11.6 hours of audio -- but that comparison is documentation only,
never an equality this module asserts or depends on.

This is a **plausibility ceiling only**. It is never timing authority: the
one authoritative capacity for a real voice unit is recomputed, in the
source cross-check, from the actual verified Phase 27 window and the actual
verified presentation fps -- never read out of, or bounded merely by, this
constant.
"""


def samples_per_presentation_frame(fps: int) -> int:
    """Return how many audio samples one presentation frame is worth, at ``fps``.

    The pinned voice sample rate and the proven presentation fps are two
    independent clocks; this is the one law that crosses them, and it refuses
    rather than approximate when they do not cross exactly.

    Args:
        fps: The proven Phase 27 presentation timeline's frames-per-second.
            Never a Phase 28 constant -- fps is data pinned by the Motion &
            Time digest, not a Python literal this module may assume.

    Returns:
        ``SAMPLE_RATE_HZ // fps``, exact.

    Raises:
        TypeError: If ``fps`` is not an exact ``int`` (``bool`` is refused
            because it subclasses ``int``: an unchecked ``True`` would
            silently behave as ``1``).
        ValueError: If ``fps`` is not positive, or if ``SAMPLE_RATE_HZ`` is
            not evenly divisible by it, so the audio and presentation clocks
            do not cross exactly.
    """
    if type(fps) is not int:
        raise TypeError(f"fps must be an int, got {type(fps).__name__}")
    if fps < 1:
        raise ValueError(f"fps must be >= 1, got {fps}")
    if SAMPLE_RATE_HZ % fps != 0:
        raise ValueError(
            f"the pinned voice sample rate {SAMPLE_RATE_HZ} Hz is not evenly divisible by "
            f"the proven presentation fps {fps}; the audio and presentation clocks do not "
            "cross exactly, and this policy refuses rather than approximate"
        )
    return SAMPLE_RATE_HZ // fps


def capacity_samples_for_window(window_frames: int, fps: int) -> int:
    """Return the exact integer sample capacity of a presentation window.

    Args:
        window_frames: The window's own length in presentation frames
            (``presentation_end_frame - presentation_start_frame + 1``).
        fps: The proven Phase 27 presentation timeline's frames-per-second.

    Returns:
        ``window_frames * samples_per_presentation_frame(fps)``.

    Raises:
        TypeError: If ``window_frames`` is not an exact ``int`` (``bool``
            refused for the same reason as :func:`samples_per_presentation_frame`).
        ValueError: If ``window_frames`` is not positive, or if the sample
            rate and fps do not cross exactly (see
            :func:`samples_per_presentation_frame`).
    """
    if type(window_frames) is not int:
        raise TypeError(f"window_frames must be an int, got {type(window_frames).__name__}")
    if window_frames < 1:
        raise ValueError(f"window_frames must be >= 1, got {window_frames}")
    return window_frames * samples_per_presentation_frame(fps)
