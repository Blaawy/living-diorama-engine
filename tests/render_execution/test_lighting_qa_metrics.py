"""QA metrics for the Director Revision's lighting rewrite.

The PNG frames these tests decode are SYNTHETIC, clearly labelled as such:
no committed render frames exist anywhere in this repo's test fixtures (the
``tests/*/fixtures`` directories ship JSON render exports only, and the repo's
own suites generate PNG bytes at test time via the same stdlib ``struct`` +
``zlib`` chunk writer used here -- see ``tests/render_execution/conftest.py``
and ``tests/media_assembly/conftest.py``). What is NOT synthetic is the decode
path: every byte string here is decoded by the repo's real strict PNG decoder
(``render_execution.frame_image.read_rgb_samples_bytes``), the same one the
Phase 23 audit uses on real renders, so the luminance numbers are exactly what
that decoder would produce from a real frame of the same pixels. The structural
check, by contrast, runs against the REAL applier scripts in
``visual/blender/scripts``.
"""

import struct
import zlib
from pathlib import Path

import pytest

from living_diorama.render_execution import lighting_qa_metrics as metrics
from living_diorama.render_execution.frame_image import FrameImageProblem

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "visual" / "blender" / "scripts"


def solid_png(*, width: int = 8, height: int = 8, rgb: tuple[int, int, int]) -> bytes:
    """A minimal, structurally complete 8-bit RGB PNG of one solid colour.

    SYNTHETIC TEST IMAGE, mirroring the repo's own PNG writer
    (``tests/render_execution/conftest.py::png_bytes``): same chunk layout,
    correct CRCs, filter type 0 per row. It is a genuine PNG that the real
    decoder accepts, not a stand-in.
    """

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def gradient_png(*, width: int = 32, height: int = 8) -> bytes:
    """A minimal PNG whose luma ramps from black (left) to white (right).

    SYNTHETIC TEST IMAGE (see module docstring); used to exercise the
    threshold fractions with real per-pixel variation.
    """

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = bytearray()
    for _ in range(height):
        rows.append(0)  # filter: None
        for column in range(width):
            value = round(255 * column / (width - 1))
            rows += bytes((value, value, value))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows)))
        + chunk(b"IEND", b"")
    )


# ---------------------------------------------------------- luminance stats


def test_frame_luminance_stats_on_a_mid_gray_frame() -> None:
    """Rec. 601 luma of (128, 128, 128) is exactly 128.0."""
    result = metrics.frame_luminance_stats(solid_png(rgb=(128, 128, 128)))
    assert result["width"] == 8
    assert result["height"] == 8
    assert result["mean_luminance"] == 128.0
    assert result["median_luminance"] == 128.0
    assert result["dark_pixel_fraction"] == 0.0
    assert result["shadow_crush_fraction"] == 0.0
    assert result["highlight_clipping_fraction"] == 0.0


def test_frame_luminance_stats_on_black_and_white_frames() -> None:
    """A solid black frame and a solid white frame land at opposite extremes."""
    black = metrics.frame_luminance_stats(solid_png(rgb=(0, 0, 0)))
    assert black["mean_luminance"] == 0.0
    assert black["dark_pixel_fraction"] == 1.0
    assert black["shadow_crush_fraction"] == 1.0
    assert black["highlight_clipping_fraction"] == 0.0

    white = metrics.frame_luminance_stats(solid_png(rgb=(255, 255, 255)))
    assert white["mean_luminance"] == 255.0
    assert white["highlight_clipping_fraction"] == 1.0  # 255 >= the 250 threshold
    assert white["dark_pixel_fraction"] == 0.0


def test_frame_luminance_stats_on_a_gradient_frame() -> None:
    """A black-to-white ramp yields intermediate fractions, not endpoints."""
    result = metrics.frame_luminance_stats(gradient_png())
    assert 0.0 < result["mean_luminance"] < 255.0
    assert 0.0 < result["dark_pixel_fraction"] < 1.0
    assert 0.0 < result["highlight_clipping_fraction"] < 1.0
    assert result["shadow_crush_fraction"] < result["dark_pixel_fraction"]


def test_frame_luminance_stats_is_deterministic() -> None:
    """Two independent runs over the same real frame agree exactly."""
    frame = solid_png(rgb=(90, 140, 200))
    assert metrics.frame_luminance_stats(frame) == metrics.frame_luminance_stats(frame)


def test_frame_luminance_stats_refuses_non_png_bytes() -> None:
    """Garbage must raise the decoder's own error, not produce numbers."""
    with pytest.raises(FrameImageProblem):
        metrics.frame_luminance_stats(b"this is not a png")


# --------------------------------------------------- white balance consistency


def test_white_balance_consistency_is_zero_variance_for_identical_frames() -> None:
    """A static rig over identical frames must show near-zero ratio variance."""
    warm = solid_png(rgb=(255, 200, 150))
    result = metrics.white_balance_consistency([warm, warm, warm])
    assert result["ratio_spread"] == 0.0
    assert result["ratio_stddev"] == 0.0
    assert result["held_constant"] is True
    assert [entry["r_over_b"] for entry in result["per_frame"]] == [1.7, 1.7, 1.7]


def test_white_balance_consistency_detects_a_different_white_point() -> None:
    """A warm frame and a cool frame are not the same lighting, even at equal luma."""
    warm = solid_png(rgb=(255, 200, 150))
    cool = solid_png(rgb=(150, 200, 255))
    result = metrics.white_balance_consistency([warm, cool])
    assert result["ratio_spread"] == pytest.approx(1.7 - 150.0 / 255.0, abs=0.01)
    assert result["held_constant"] is False  # spread far above the 0.05 tolerance


def test_white_balance_consistency_is_deterministic() -> None:
    """Two independent runs over the same real frames agree exactly."""
    frames = [solid_png(rgb=(255, 200, 150)), solid_png(rgb=(240, 210, 160))]
    assert metrics.white_balance_consistency(frames) == metrics.white_balance_consistency(frames)


# ------------------------------------------------ exposure / sun animation


def test_no_exposure_or_sun_animation_passes_on_the_real_applier_path() -> None:
    """Every real applier keyframe is a camera, mobility or material keyframe.

    The movement applier legally keyframes ``camera`` objects; nothing in the
    real path keyframes a light, world, sky or exposure object.
    """
    result = metrics.no_exposure_or_sun_animation(metrics.applier_script_paths(SCRIPTS))
    assert result["passes"] is True
    assert result["evidence"] == []
    assert set(result["scanned"]) == set(metrics.APPLIER_SCRIPT_NAMES)


def test_no_exposure_or_sun_animation_catches_an_offender(tmp_path: Path) -> None:
    """A guard nobody has seen fail is a guard nobody has tested.

    Synthetic offender file mirroring the boundary tests' pattern: a real
    applier script that keyframes the sun must be reported with evidence.
    """
    offender = tmp_path / "apply_lighting.py"
    offender.write_text(
        "sky.sun_intensity = 2.0\nsky.keyframe_insert('sun_intensity', frame=1)\n",
        encoding="utf-8",
    )
    result = metrics.no_exposure_or_sun_animation([offender])
    assert result["passes"] is False
    assert len(result["evidence"]) == 1
    assert result["evidence"][0]["file"] == "apply_lighting.py"
    assert "keyframe_insert" in result["evidence"][0]["snippet"]


def test_applier_script_paths_refuses_a_missing_script(tmp_path: Path) -> None:
    """A script name that does not exist on disk is refused, not skipped."""
    with pytest.raises(FileNotFoundError):
        metrics.applier_script_paths(tmp_path)


# ------------------------------------------------------------- purity boundary


def test_lighting_qa_metrics_never_imports_blender() -> None:
    """The metrics module is pure: no bpy import anywhere in its source."""
    source = Path(metrics.__file__).read_text(encoding="utf-8")
    assert "import bpy" not in source
    assert "from bpy" not in source
