"""Pure QA metrics for the Director Revision's lighting rewrite.

The lighting task moves the build from its dark/golden civil-twilight rig to
bright, clean, late-morning daylight. This module is the commander's
mechanical acceptance signal for that change -- three independent checks:

* ``frame_luminance_stats`` decodes real rendered PNG bytes with the repo's own
  strict decoder (``render_execution.frame_image``) and reports luminance
  statistics: mean, median, dark fraction, highlight-clipping fraction and
  shadow-crush fraction. These are signals the acceptance gate can compare
  against the pre-rewrite renders.
* ``white_balance_consistency`` reports how constant the per-frame average
  colour is across a clip, as a signal for "is lighting held constant".
* ``no_exposure_or_sun_animation`` is a STRUCTURAL check, not a pixel check: it
  scans the real applier code path for any ``keyframe_insert`` that touches a
  light, world, sky or exposure object, mirroring the boundary-test pattern the
  codebase already uses (``tests/visual/test_phaseNN_boundary.py`` scans real
  source text for banned constructs).

Every function is deterministic. The pixel functions are pure (bytes in,
numbers out); the structural check reads the source files it is handed, so its
output is deterministic for given file bytes. None of them import ``bpy``.

Luminance weighting: Rec. 601 (``Y = 0.299 R + 0.587 G + 0.114 B``), the
standard-definition luma weighting, stated here so the numbers are
reproducible.
"""

import re
import statistics
from pathlib import Path
from typing import Final

from living_diorama.render_execution.frame_image import (
    FrameImageProblem,
    read_rgb_samples_bytes,
)

# Rec. 601 luma weights, in the same order as the RGB sample triplets.
LUMINANCE_R: Final = 0.299
LUMINANCE_G: Final = 0.587
LUMINANCE_B: Final = 0.114

# Default QA thresholds, in 8-bit levels out of 255. All are parameters, so the
# acceptance gate can tighten or loosen them without touching the function.
DEFAULT_DARK_THRESHOLD: Final = 12.75  # 5% of full range
DEFAULT_CRUSH_THRESHOLD: Final = 2.55  # 1% of full range
DEFAULT_CLIP_THRESHOLD: Final = 250.0

# Real applier code path scanned by the structural check: the world builders
# that own the lighting rig and the exposure (build_master_scene,
# build_production_world), the episode render applier and scene composer
# (render_episode, episode_scene), the camera-movement applier, and the three
# appliers that write animation into the composed world (motion plan, mobility,
# state response). Together these are every file that could legally place a
# ``keyframe_insert`` in an episode render. Relative to
# ``visual/blender/scripts``.
APPLIER_SCRIPT_NAMES: Final = (
    "build_master_scene.py",
    "build_production_world.py",
    "episode_scene.py",
    "render_episode.py",
    "apply_camera_movement.py",
    "apply_motion_plan.py",
    "apply_mobility.py",
    "apply_state_response_motion.py",
)

# Identifier fragments that make a ``keyframe_insert`` a lighting/world/
# exposure animation rather than a camera, mobility or material animation.
LIGHTING_KEYFRAME_CONTEXT: Final = (
    "world",
    "light",
    "sun",
    "sky",
    "exposure",
    "view_settings",
    "Background",
    "ShaderNodeTexSky",
)


def _luminance(sample: bytearray, pixel: int) -> float:
    """Return the Rec. 601 luma of one RGB pixel (sample offset ``pixel * 3``)."""
    offset = pixel * 3
    return (
        LUMINANCE_R * sample[offset]
        + LUMINANCE_G * sample[offset + 1]
        + LUMINANCE_B * sample[offset + 2]
    )


def frame_luminance_stats(
    png_bytes: bytes,
    *,
    dark_threshold: float = DEFAULT_DARK_THRESHOLD,
    crush_threshold: float = DEFAULT_CRUSH_THRESHOLD,
    clip_threshold: float = DEFAULT_CLIP_THRESHOLD,
) -> dict[str, object]:
    """Return luminance statistics for one rendered frame's PNG bytes.

    Decodes the bytes with the repo's real strict decoder
    (``frame_image.read_rgb_samples_bytes``), so any frame this phase would
    refuse to read is refused here too -- a malformed or non-RGB PNG raises
    ``FrameImageProblem`` rather than producing numbers from a half-decoded
    picture. Luminance is Rec. 601 weighted per pixel.

    Args:
        png_bytes: The exact bytes of an eight-bit, non-interlaced RGB PNG.
        dark_threshold: Luma below this (8-bit levels) counts as dark
            (default 12.75, 5% of range).
        crush_threshold: Luma at or below this counts as shadow-crushed
            (default 2.55, 1% of range).
        clip_threshold: Luma at or above this counts as highlight clipping
            (default 250.0).

    Returns:
        A dict with ``width``, ``height``, ``mean_luminance``, ``median_luminance``
        and the fractions ``dark_pixel_fraction``, ``shadow_crush_fraction``,
        ``highlight_clipping_fraction`` (each rounded to six decimals).

    Raises:
        FrameImageProblem: If the bytes are not a frame this phase writes.
    """
    width, height, samples = read_rgb_samples_bytes(png_bytes)
    pixel_count = width * height
    total = 0.0
    dark = 0
    crushed = 0
    clipped = 0
    values: list[float] = []
    for pixel in range(pixel_count):
        luma = _luminance(samples, pixel)
        total += luma
        values.append(luma)
        if luma < dark_threshold:
            dark += 1
        if luma <= crush_threshold:
            crushed += 1
        if luma >= clip_threshold:
            clipped += 1
    mean = total / pixel_count if pixel_count else 0.0
    median = statistics.median(values) if values else 0.0
    return {
        "width": width,
        "height": height,
        "mean_luminance": round(mean, 6),
        "median_luminance": round(median, 6),
        "dark_pixel_fraction": round(dark / pixel_count, 6) if pixel_count else 0.0,
        "shadow_crush_fraction": round(crushed / pixel_count, 6) if pixel_count else 0.0,
        "highlight_clipping_fraction": round(clipped / pixel_count, 6) if pixel_count else 0.0,
    }


def _mean_rgb(png_bytes: bytes) -> tuple[float, float, float]:
    """Return the per-pixel mean (R, G, B) of one frame, each in 0..255."""
    _, _, samples = read_rgb_samples_bytes(png_bytes)
    pixel_count = len(samples) // 3
    if pixel_count == 0:
        raise FrameImageProblem("frame carries no pixels")
    totals = [0.0, 0.0, 0.0]
    for pixel in range(pixel_count):
        offset = pixel * 3
        for channel in range(3):
            totals[channel] += samples[offset + channel]
    return (
        round(totals[0] / pixel_count, 6),
        round(totals[1] / pixel_count, 6),
        round(totals[2] / pixel_count, 6),
    )


def white_balance_consistency(frames: list[bytes], *, tolerance: float = 0.05) -> dict[str, object]:
    """Report how constant the average colour is across a clip's sampled frames.

    QA SIGNAL, NOT A PROOF: for each frame the mean R/G/B is computed, and the
    red/blue mean ratio is used as a simple colour-temperature-like signal. The
    spread (max minus min) and population standard deviation of those ratios
    across the clip are reported, with ``held_constant`` True when the spread
    is within the parameterized ``tolerance``. A truly static lighting rig with
    a no-animation guarantee should yield a near-zero spread; content changes
    between frames also move the means, so this is a signal for the acceptance
    gate, not a verdict on its own.

    Args:
        frames: The exact PNG bytes of several sampled frames of one clip.
        tolerance: Maximum ratio spread (``max - min``) accepted as "held
            constant" (default 0.05).

    Returns:
        A dict with ``per_frame`` (list of ``{"frame": index, "mean_r",
        "mean_g", "mean_b", "r_over_b"}``), ``ratio_spread``, ``ratio_stddev``
        and ``held_constant`` (bool).
    """
    per_frame: list[dict[str, object]] = []
    ratios: list[float] = []
    for index, frame in enumerate(frames):
        mean_r, mean_g, mean_b = _mean_rgb(frame)
        ratio = (mean_r / mean_b) if mean_b > 0.0 else float("inf")
        per_frame.append(
            {
                "frame": index,
                "mean_r": mean_r,
                "mean_g": mean_g,
                "mean_b": mean_b,
                "r_over_b": round(ratio, 6),
            }
        )
        if mean_b > 0.0:
            ratios.append(ratio)
    spread = (max(ratios) - min(ratios)) if ratios else 0.0
    stddev = statistics.pstdev(ratios) if len(ratios) > 1 else 0.0
    return {
        "per_frame": per_frame,
        "ratio_spread": round(spread, 6),
        "ratio_stddev": round(stddev, 6),
        "held_constant": spread <= tolerance,
    }


def no_exposure_or_sun_animation(
    applier_paths: list[Path] | tuple[Path, ...],
    *,
    context_fragments: tuple[str, ...] = LIGHTING_KEYFRAME_CONTEXT,
) -> dict[str, object]:
    """Return whether the applier code path animates light, world or exposure.

    STRUCTURAL check, mirroring the boundary-test pattern: each real applier
    source file is read as text, every line containing ``keyframe_insert`` is
    located, and the statement's context (the line itself plus the three lines
    before it, which carry the object expression and the data path) is matched
    against lighting/world/exposure identifier fragments (``world``, ``light``,
    ``sun``, ``sky``, ``exposure``, ``view_settings``, ``Background``,
    ``ShaderNodeTexSky``). A hit is reported with its file, line number and
    snippet as evidence. The movement applier keyframes a camera's own
    "location" data path, which is a camera keyframe and does not match,
    which is exactly the intended behaviour: camera animation is legal,
    light/world/exposure animation is not.

    Args:
        applier_paths: The real applier script files to scan.
        context_fragments: Identifier fragments that mark a keyframe as a
            lighting/world/exposure animation.

    Returns:
        A dict with ``passes`` (bool), ``scanned`` (list of file names),
        ``evidence`` (list of ``{"file", "line", "snippet"}`` for every
        lighting-context keyframe found) and ``rule`` (a one-line statement of
        what was checked).
    """
    evidence: list[dict[str, object]] = []
    scanned: list[str] = []
    pattern = re.compile(r"\bkeyframe_insert\b")
    for path in applier_paths:
        text = Path(path).read_text(encoding="utf-8")
        scanned.append(Path(path).name)
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if not pattern.search(line):
                continue
            start = max(0, index - 3)
            context = "\n".join(lines[start : index + 1]).lower()
            matched = [fragment for fragment in context_fragments if fragment in context]
            if matched:
                evidence.append(
                    {
                        "file": Path(path).name,
                        "line": index + 1,
                        "snippet": line.strip(),
                        "matched_fragments": matched,
                    }
                )
    return {
        "passes": not evidence,
        "scanned": scanned,
        "evidence": evidence,
        "rule": (
            "no keyframe_insert in the applier code path may touch a light, "
            "world, sky or exposure object"
        ),
    }


def applier_script_paths(scripts_dir: Path) -> tuple[Path, ...]:
    """Return the real applier script paths for a ``visual/blender/scripts`` dir.

    Convenience for tests and callers: resolves the module-level
    :data:`APPLIER_SCRIPT_NAMES` against the given scripts directory and
    raises if any of the real files is missing, so the scan cannot silently
    stop guarding a renamed file (the same discipline the boundary tests use).

    Args:
        scripts_dir: The ``visual/blender/scripts`` directory.

    Returns:
        The resolved paths, in :data:`APPLIER_SCRIPT_NAMES` order.

    Raises:
        FileNotFoundError: If any of the real applier files is absent.
    """
    resolved = tuple(scripts_dir / name for name in APPLIER_SCRIPT_NAMES)
    for path in resolved:
        if not path.is_file():
            raise FileNotFoundError(f"applier script {path} is missing; the scan cannot run")
    return resolved
