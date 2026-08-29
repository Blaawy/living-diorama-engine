"""Shared fixtures for the Phase 35 media encode tests.

LIGHT by design: the heavy end-to-end chain lives in the Phase 34 suite; the
Phase 35 canonical tests run on synthetic trees plus fakes -- the executor
and publisher test lanes build their own inputs. This conftest supplies only
the fixture-export boundary (``load_export``), the canned ffprobe report
(``golden_probe_json``), the normalized frozen streams block
(``golden_streams``) and the ep1 presentation clock (``ep1_clock``). No
heavy publishing fixture lives here.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from living_diorama.media_encode import normalize_probe_document

FIXTURES = Path(__file__).parent / "fixtures"


def load_export(episode: int) -> dict[str, Any]:
    """Return an independent copy of one fixture render export."""
    return json.loads((FIXTURES / f"render_export_ep{episode}.json").read_text(encoding="utf-8"))


def golden_probe_json(*, width: int = 1280, height: int = 720, frames: int = 720) -> dict[str, Any]:
    """Return the canned ffprobe report the probe-test lane normalizes.

    The exact shape a reviewed build leaves for the 720-frame, 24 fps, 24 kHz,
    one-channel episode: video at index 0 (h264, yuv420p, frame-rate rationals
    ``24/1``, time base ``1/12288``, 368640 ticks = 30 s, ``nb_read_frames``
    as a decimal string), audio at index 1 (aac, 1 channel, ``1/24000``,
    720000 ticks = 30 s), both starting at zero, and the mp4 container tag
    list ``mov,mp4,m4a,3gp,3g2,mj2``.
    """
    return {
        "streams": [
            {
                "avg_frame_rate": "24/1",
                "codec_name": "h264",
                "codec_type": "video",
                "duration_ts": 368640,
                "height": height,
                "index": 0,
                "nb_read_frames": str(frames),
                "pix_fmt": "yuv420p",
                "r_frame_rate": "24/1",
                "start_pts": 0,
                "time_base": "1/12288",
                "width": width,
            },
            {
                "channels": 1,
                "codec_name": "aac",
                "codec_type": "audio",
                "duration_ts": 720000,
                "index": 1,
                "sample_rate": "24000",
                "start_pts": 0,
                "time_base": "1/24000",
            },
        ],
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
    }


@pytest.fixture
def golden_streams() -> dict[str, Any]:
    """The normalized frozen 21-key streams block for the golden probe report."""
    return normalize_probe_document(golden_probe_json(), audio_samples_decoded=720000)


@pytest.fixture
def ep1_clock() -> dict[str, Any]:
    """The ep1 presentation clock the canonical P35 tests assert against.

    Eight keys: fps 24, 720 total presentation frames, 24 kHz rate, 1000
    samples per presentation frame, 720000 total audio samples, the semantic
    frame span ``(1, 192)`` (first, final) and the 193 witness frame directly
    after the final semantic frame.
    """
    return {
        "fps": 24,
        "total": 720,
        "rate": 24000,
        "spf": 1000,
        "samples": 720000,
        "semantic": (1, 192),
        "witness": 193,
    }
