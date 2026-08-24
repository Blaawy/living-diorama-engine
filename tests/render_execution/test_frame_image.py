"""The two PNG readers, and the proof that they agree.

Phase 23 decodes rendered frames on both sides of a boundary neither may
cross: the Blender executor measures the frames it just made, and the engine's
audit re-measures them without importing anything from Blender. Two decoders
are only honest if they are shown to agree, so this file drives both over
images built with every PNG scanline filter and requires identical samples and
an identical difference.

The fixtures write real PNGs with real CRCs and deliberately chosen filters --
a decoder tested only against filter 0 would pass while being wrong about the
four filters a real encoder actually uses.
"""

import importlib.util
import struct
import sys
import zlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from living_diorama.render_execution.frame_image import (
    FrameImageProblem,
    image_stream_digest,
    mean_abs_difference,
    read_rgb_samples,
    verify_frame_image,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "visual" / "blender" / "scripts" / "render_episode.py"


def _load_executor() -> Any:
    """Import the production executor without Blender present."""
    spec = importlib.util.spec_from_file_location("render_episode_frame_image", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


executor = _load_executor()


def _chunk(kind: bytes, body: bytes) -> bytes:
    """One PNG chunk with a correct CRC."""
    return (
        struct.pack(">I", len(body))
        + kind
        + body
        + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    )


def write_png(
    path: Path,
    *,
    width: int,
    height: int,
    filter_type: int | None = None,
    filters: Sequence[int] | None = None,
    seed: int = 0,
) -> bytearray:
    """Write a real PNG and return its true samples.

    The samples are computed first and then encoded through the chosen filters,
    so the expected answer is known independently of either decoder.

    Either one filter for the whole image, or one per row. Per-row is what
    Blender actually emits -- a real frame here mixes Paeth on 505 rows, Up on
    202 and Sub on 13 -- and it is the only form that exercises a filter's
    effect on the row that follows it.
    """
    samples = bytearray()
    for y in range(height):
        for x in range(width):
            samples += bytes(
                (
                    (x * 7 + y * 13 + seed) % 256,
                    (x * 31 + y * 5 + seed * 3) % 256,
                    (x * 3 + y * 29 + seed * 7) % 256,
                )
            )

    if (filter_type is None) == (filters is None):
        raise AssertionError("write_png takes exactly one of filter_type or filters")
    per_row = list(filters) if filters is not None else [filter_type] * height
    if len(per_row) != height:
        raise AssertionError("one filter per row is required")

    stride = width * 3
    raw = bytearray()
    previous = bytearray(stride)
    for y in range(height):
        filter_type = per_row[y]
        line = samples[y * stride : (y + 1) * stride]
        encoded = bytearray()
        for index in range(stride):
            left = line[index - 3] if index >= 3 else 0
            up = previous[index]
            corner = previous[index - 3] if index >= 3 else 0
            value = line[index]
            if filter_type == 0:
                encoded.append(value)
            elif filter_type == 1:
                encoded.append((value - left) & 0xFF)
            elif filter_type == 2:
                encoded.append((value - up) & 0xFF)
            elif filter_type == 3:
                encoded.append((value - ((left + up) >> 1)) & 0xFF)
            elif filter_type == 4:
                estimate = left + up - corner
                distance_left = abs(estimate - left)
                distance_up = abs(estimate - up)
                distance_corner = abs(estimate - corner)
                if distance_left <= distance_up and distance_left <= distance_corner:
                    predictor = left
                elif distance_up <= distance_corner:
                    predictor = up
                else:
                    predictor = corner
                encoded.append((value - predictor) & 0xFF)
            else:  # pragma: no cover - the parametrisation covers 0..4
                raise AssertionError(filter_type)
        raw += bytes([filter_type]) + encoded
        previous = bytearray(line)

    payload = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(bytes(raw)))
        + _chunk(b"IEND", b"")
    )
    path.write_bytes(payload)
    return samples


@pytest.mark.parametrize("filter_type", [0, 1, 2, 3, 4])
def test_the_decoder_recovers_the_true_samples(tmp_path: Path, filter_type: int) -> None:
    """Every PNG scanline filter, decoded back to the pixels that went in."""
    path = tmp_path / "frame.png"
    expected = write_png(path, width=9, height=7, filter_type=filter_type)
    width, height, samples = read_rgb_samples(path)
    assert (width, height) == (9, 7)
    assert samples == expected


@pytest.mark.parametrize("filter_type", [0, 1, 2, 3, 4])
def test_both_decoders_agree_on_the_samples(tmp_path: Path, filter_type: int) -> None:
    """The engine's reader and the executor's reader must never disagree.

    They exist separately because the boundary forbids one importing the other.
    This is what keeps that separation from becoming a divergence.
    """
    path = tmp_path / "frame.png"
    write_png(path, width=11, height=6, filter_type=filter_type)
    assert read_rgb_samples(path) == executor.png_pixels(path)


@pytest.mark.parametrize("filter_type", [0, 1, 2, 3, 4])
def test_both_implementations_measure_the_same_difference(tmp_path: Path, filter_type: int) -> None:
    """The measurement the manifest records and the audit recomputes."""
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    write_png(first, width=8, height=5, filter_type=filter_type, seed=0)
    write_png(second, width=8, height=5, filter_type=filter_type, seed=3)
    assert mean_abs_difference(first, second) == executor.png_mean_abs_difference(first, second)


def test_identical_images_measure_zero(tmp_path: Path) -> None:
    """The scale's zero point."""
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    write_png(first, width=8, height=5, filter_type=4, seed=1)
    write_png(second, width=8, height=5, filter_type=4, seed=1)
    assert mean_abs_difference(first, second) == 0.0


def test_the_image_digest_ignores_metadata_but_not_pixels(tmp_path: Path) -> None:
    """What ``image_sha256`` is for: telling a re-stamp from a replacement.

    The same image with an extra text chunk keeps its image digest; a different
    image does not. That is the whole claim -- it is not a pixel identity
    across encoders, and nothing here pretends otherwise.
    """
    plain = tmp_path / "plain.png"
    stamped = tmp_path / "stamped.png"
    other = tmp_path / "other.png"
    write_png(plain, width=6, height=4, filter_type=1, seed=2)
    write_png(other, width=6, height=4, filter_type=1, seed=9)

    payload = plain.read_bytes()
    insert_at = payload.index(b"IDAT") - 4
    text = _chunk(b"tEXt", b"Date\x002026/08/23 04:00:00")
    stamped.write_bytes(payload[:insert_at] + text + payload[insert_at:])

    assert image_stream_digest(stamped) == image_stream_digest(plain)
    assert stamped.read_bytes() != plain.read_bytes()
    assert image_stream_digest(other) != image_stream_digest(plain)


def test_both_implementations_agree_on_the_image_digest(tmp_path: Path) -> None:
    """The digest the manifest records is computed the same way on both sides."""
    path = tmp_path / "frame.png"
    write_png(path, width=7, height=7, filter_type=3, seed=5)
    assert image_stream_digest(path) == executor.png_facts(path)["image_sha256"]


def test_frames_of_different_sizes_cannot_be_compared(tmp_path: Path) -> None:
    """A comparison that silently resized would report a meaningless number."""
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    write_png(first, width=8, height=5, filter_type=0)
    write_png(second, width=9, height=5, filter_type=0)
    with pytest.raises(ValueError, match="not the same size"):
        mean_abs_difference(first, second)


MIXED_FILTERS = (0, 4, 2, 1, 3, 2, 0, 2, 4, 0, 3, 1)
"""Every filter, with the two fast-pathed ones on both sides of the others.

Deliberately places 0 and 2 immediately before 1, 3 and 4, because a fast path
that failed to carry ``previous`` correctly would only be visible in the row
that reads it.
"""


@pytest.mark.parametrize("seed", [0, 5])
def test_both_decoders_agree_on_a_mixed_filter_image(tmp_path: Path, seed: int) -> None:
    """Real frames mix filters per row, and so must the case that proves the decoders.

    The fast paths for filters 0 and 2 skip the per-sample loop, which means
    they also skip the place where ``previous`` was assigned. An image written
    entirely in one filter can never catch that; this one can.
    """
    path = tmp_path / "mixed.png"
    expected = write_png(path, width=9, height=len(MIXED_FILTERS), filters=MIXED_FILTERS, seed=seed)
    width, height, samples = read_rgb_samples(path)
    assert (width, height) == (9, len(MIXED_FILTERS))
    assert samples == expected

    blender_width, blender_height, blender_samples = executor.png_pixels(path)
    assert (blender_width, blender_height) == (width, height)
    assert blender_samples == expected


def test_a_mixed_filter_image_measures_zero_against_itself(tmp_path: Path) -> None:
    """Both boundary measurements run over mixed-filter frames in production."""
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    write_png(first, width=9, height=len(MIXED_FILTERS), filters=MIXED_FILTERS)
    write_png(second, width=9, height=len(MIXED_FILTERS), filters=MIXED_FILTERS)
    assert mean_abs_difference(first, second) == 0.0
    assert executor.png_mean_abs_difference(first, second) == 0.0


def _png_with_header(path: Path, header: bytes, raw: bytes) -> None:
    """Write a structurally valid PNG carrying an arbitrary image header."""
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )


@pytest.mark.parametrize(
    ("label", "depth", "colour", "compression", "filtering", "interlace", "message"),
    [
        ("greyscale", 8, 0, 0, 0, 0, "colour type 0"),
        ("rgba", 8, 6, 0, 0, 0, "colour type 6"),
        ("sixteen bit", 16, 2, 0, 0, 0, "bit depth 16"),
        ("interlaced", 8, 2, 0, 0, 1, "interlace method 1"),
        ("unknown compression", 8, 2, 1, 0, 0, "compression method 1"),
        ("unknown filter method", 8, 2, 0, 1, 0, "filter method 1"),
    ],
)
def test_every_profile_field_is_refused_on_its_own(
    tmp_path: Path,
    label: str,
    depth: int,
    colour: int,
    compression: int,
    filtering: int,
    interlace: int,
    message: str,
) -> None:
    """Only what Phase 23 writes is understood, and the refusal says which field.

    Each of these is a genuinely different file with a genuinely different
    cause, so each earns its own refusal rather than one blanket message about
    the whole profile.
    """
    path = tmp_path / f"{label.replace(' ', '_')}.png"
    header = struct.pack(">IIBBBBB", 4, 2, depth, colour, compression, filtering, interlace)
    _png_with_header(path, header, b"".join(b"\x00" + bytes([7, 7, 7, 7]) for _ in range(2)))
    with pytest.raises(FrameImageProblem, match=message):
        read_rgb_samples(path)


def test_a_short_image_header_is_refused_rather_than_sliced(tmp_path: Path) -> None:
    """Nine bytes of header cannot say what the picture is; unpacking it would raise."""
    path = tmp_path / "short.png"
    _png_with_header(path, struct.pack(">IIB", 4, 2, 8), b"\x00\x00")
    with pytest.raises(FrameImageProblem, match="image header"):
        read_rgb_samples(path)


def test_two_image_headers_are_refused(tmp_path: Path) -> None:
    """A second header is a second claim about the same picture."""
    path = tmp_path / "double.png"
    header = struct.pack(">IIBBBBB", 4, 2, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes([1, 2, 3] * 4) for _ in range(2))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )
    with pytest.raises(FrameImageProblem, match="image headers"):
        read_rgb_samples(path)


def test_a_scanline_short_stream_is_refused(tmp_path: Path) -> None:
    """One byte short of a full scanline set is a truncated picture."""
    path = tmp_path / "short_rows.png"
    header = struct.pack(">IIBBBBB", 4, 2, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes([1, 2, 3] * 4) for _ in range(2))
    _png_with_header(path, header, raw[:-1])
    with pytest.raises(FrameImageProblem, match="scanline data"):
        read_rgb_samples(path)


def test_undecompressable_image_data_refuses_rather_than_raising_zlib(
    tmp_path: Path,
) -> None:
    """``zlib.error`` is not a ``ValueError``, and used to escape as a traceback.

    The audit reports on 193 files. A corrupt one has to become a finding, not
    an exception that stops the other 192 from ever being looked at.
    """
    path = tmp_path / "corrupt.png"
    header = struct.pack(">IIBBBBB", 4, 2, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", b"not a zlib stream at all")
        + _chunk(b"IEND", b"")
    )
    for read in (read_rgb_samples, image_stream_digest):
        with pytest.raises(FrameImageProblem, match="could not be decompressed"):
            read(path)


def test_a_sound_frame_of_the_right_size_reports_no_problems(tmp_path: Path) -> None:
    """The control: the audit's per-frame check passes what the renderer writes."""
    path = tmp_path / "frame.png"
    write_png(path, width=8, height=5, filter_type=4)
    assert verify_frame_image(path, expected_width=8, expected_height=5) == []


def test_a_frame_of_the_wrong_size_is_reported_not_raised(tmp_path: Path) -> None:
    """The whole point of Blocker C: a valid picture is still the wrong frame.

    An attacker who swaps an interior frame for a real, well-formed image of a
    different size and rewrites all three of the manifest's digests to match has
    produced a directory whose every hash agrees. Only decoding the image and
    comparing it to the render profile catches it.
    """
    path = tmp_path / "frame.png"
    write_png(path, width=4, height=3, filter_type=0)
    problems = verify_frame_image(path, expected_width=8, expected_height=5)
    assert len(problems) == 1
    assert "4x3" in problems[0] and "8x5" in problems[0]


def test_a_malformed_frame_is_reported_not_raised(tmp_path: Path) -> None:
    """A decode failure arrives as a problem, in the same list as every other."""
    path = tmp_path / "frame.png"
    write_png(path, width=6, height=4, filter_type=2)
    path.write_bytes(path.read_bytes()[:-9])
    problems = verify_frame_image(path, expected_width=6, expected_height=4)
    assert len(problems) == 1


def test_a_truncated_frame_is_refused(tmp_path: Path) -> None:
    """The same structural refusal the executor applies before publishing."""
    path = tmp_path / "frame.png"
    write_png(path, width=6, height=4, filter_type=2)
    path.write_bytes(path.read_bytes()[:-9])
    with pytest.raises(ValueError):
        read_rgb_samples(path)


def test_an_unknown_filter_is_refused(tmp_path: Path) -> None:
    """A filter this decoder does not know would silently produce wrong pixels."""
    path = tmp_path / "frame.png"
    raw = b"".join(bytes([9]) + bytes([1, 2, 3] * 4) for _ in range(3))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 3, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )
    with pytest.raises(ValueError, match="unknown filter"):
        read_rgb_samples(path)


# --------------------------------------------------------------------------
# The chunk state machine
# --------------------------------------------------------------------------
#
# PNG defines an order, not just a set of chunk types. An independent reviewer
# walked three files past V3 that carried valid CRCs and decodable pixels and
# were still not PNGs: a duplicated IEND, an IHDR sitting after the image data,
# and an unknown critical chunk. Every reader on both sides of the Blender
# boundary is driven over the same corpus below, because a boundary where the
# two sides disagree about what a valid frame is has no meaning.


def _rgb_header(width: int = 4, height: int = 2) -> bytes:
    """A well-formed 8-bit RGB image header."""
    return struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)


def _rgb_rows(width: int = 4, height: int = 2) -> bytes:
    """Scanlines of a flat picture, filter zero."""
    return b"".join(b"\x00" + bytes([9] * width * 3) for _ in range(height))


def _assemble(*chunks: bytes) -> bytes:
    """A PNG signature followed by exactly these chunks."""
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


def _idat() -> bytes:
    """One IDAT chunk carrying a complete flat picture."""
    return _chunk(b"IDAT", zlib.compress(_rgb_rows()))


def _sound_png() -> bytes:
    """The control: a legal PNG the whole corpus is measured against."""
    return _assemble(_chunk(b"IHDR", _rgb_header()), _idat(), _chunk(b"IEND", b""))


def _duplicate_iend() -> bytes:
    """IHDR IDAT IEND IEND -- the reviewer's case A."""
    return _assemble(
        _chunk(b"IHDR", _rgb_header()), _idat(), _chunk(b"IEND", b""), _chunk(b"IEND", b"")
    )


def _header_not_first() -> bytes:
    """IDAT IHDR IEND -- the reviewer's case B."""
    return _assemble(_idat(), _chunk(b"IHDR", _rgb_header()), _chunk(b"IEND", b""))


def _unknown_critical() -> bytes:
    """IHDR bAAD IDAT IEND -- the reviewer's case C.

    ``BAAD`` has an uppercase first letter, so PNG calls it critical, and a
    decoder that does not understand a critical chunk must not proceed. The
    lowercase spelling would be *ancillary* and legal to skip -- the case
    distinction is the whole rule.
    """
    return _assemble(
        _chunk(b"IHDR", _rgb_header()),
        _chunk(b"BAAD", b"\x00\x01\x02"),
        _idat(),
        _chunk(b"IEND", b""),
    )


def _duplicate_header() -> bytes:
    """Two image headers are two claims about one picture."""
    return _assemble(
        _chunk(b"IHDR", _rgb_header()),
        _chunk(b"IHDR", _rgb_header()),
        _idat(),
        _chunk(b"IEND", b""),
    )


def _missing_header() -> bytes:
    """A picture with no header describes nothing."""
    return _assemble(_chunk(b"pHYs", b"\x00" * 9), _idat(), _chunk(b"IEND", b""))


def _missing_iend() -> bytes:
    """A file that simply stops is a file still being written."""
    return _assemble(_chunk(b"IHDR", _rgb_header()), _idat())


def _iend_not_last() -> bytes:
    """A chunk after the end marker is data no reader agrees about."""
    return _assemble(
        _chunk(b"IHDR", _rgb_header()),
        _idat(),
        _chunk(b"IEND", b""),
        _chunk(b"tEXt", b"after"),
    )


def _nonzero_iend() -> bytes:
    """IEND is empty by definition."""
    return _assemble(_chunk(b"IHDR", _rgb_header()), _idat(), _chunk(b"IEND", b"junk"))


def _split_idat() -> bytes:
    """PNG requires every IDAT to be consecutive."""
    payload = zlib.compress(_rgb_rows())
    half = len(payload) // 2
    return _assemble(
        _chunk(b"IHDR", _rgb_header()),
        _chunk(b"IDAT", payload[:half]),
        _chunk(b"tEXt", b"wedge"),
        _chunk(b"IDAT", payload[half:]),
        _chunk(b"IEND", b""),
    )


def _no_idat() -> bytes:
    """A well-framed file carrying no image at all."""
    return _assemble(_chunk(b"IHDR", _rgb_header()), _chunk(b"IEND", b""))


def _short_header_body() -> bytes:
    """Nine bytes of header cannot say what the picture is."""
    return _assemble(_chunk(b"IHDR", struct.pack(">IIB", 4, 2, 8)), _idat(), _chunk(b"IEND", b""))


def _corrupt_crc() -> bytes:
    """A CRC that disagrees with its body."""
    sound = bytearray(_sound_png())
    sound[-5] ^= 0xFF
    return bytes(sound)


def _truncated() -> bytes:
    """A file that ends inside a chunk."""
    return _sound_png()[:-9]


def _overrunning_length() -> bytes:
    """A chunk that declares more bytes than the file holds."""
    sound = bytearray(_sound_png())
    sound[8:12] = (0x00FFFFFF).to_bytes(4, "big")
    return bytes(sound)


def _bad_decompression() -> bytes:
    """Correct structure, correct CRCs, image data zlib cannot read."""
    return _assemble(
        _chunk(b"IHDR", _rgb_header()), _chunk(b"IDAT", b"not a zlib stream"), _chunk(b"IEND", b"")
    )


def _wrong_colour_type() -> bytes:
    """Greyscale is not what this phase writes."""
    header = struct.pack(">IIBBBBB", 4, 2, 8, 0, 0, 0, 0)
    rows = b"".join(b"\x00" + bytes([9] * 4) for _ in range(2))
    return _assemble(
        _chunk(b"IHDR", header), _chunk(b"IDAT", zlib.compress(rows)), _chunk(b"IEND", b"")
    )


def _bad_row_filter() -> bytes:
    """A filter byte PNG does not define."""
    rows = b"".join(b"\x05" + bytes([9] * 12) for _ in range(2))
    return _assemble(
        _chunk(b"IHDR", _rgb_header()), _chunk(b"IDAT", zlib.compress(rows)), _chunk(b"IEND", b"")
    )


def _short_scanlines() -> bytes:
    """One byte short of the scanlines the header promises."""
    return _assemble(
        _chunk(b"IHDR", _rgb_header()),
        _chunk(b"IDAT", zlib.compress(_rgb_rows()[:-1])),
        _chunk(b"IEND", b""),
    )


def _palette_after_data() -> bytes:
    """A palette the decoder reaches after the picture it was meant to colour."""
    return _assemble(
        _chunk(b"IHDR", _rgb_header()),
        _idat(),
        _chunk(b"PLTE", b"\x00" * 3),
        _chunk(b"IEND", b""),
    )


def _non_alphabetic_chunk_type() -> bytes:
    """PNG chunk names are four ASCII letters and nothing else."""
    return _assemble(
        _chunk(b"IHDR", _rgb_header()),
        _chunk(b"iT\x01T", b"x"),
        _idat(),
        _chunk(b"IEND", b""),
    )


def _reserved_bit_set() -> bytes:
    """A lowercase third letter sets PNG's reserved bit.

    ``tEqt`` rather than ``tEXt``: the difference is one bit in one byte, and it
    means the file is using something this decoder has never been told about.
    """
    return _assemble(
        _chunk(b"IHDR", _rgb_header()), _chunk(b"tEqt", b"xy"), _idat(), _chunk(b"IEND", b"")
    )


STRUCTURAL_PNGS = {
    "palette after image data": _palette_after_data,
    "non-alphabetic chunk type": _non_alphabetic_chunk_type,
    "reserved bit set in a chunk type": _reserved_bit_set,
    "duplicate IEND": _duplicate_iend,
    "IHDR after IDAT": _header_not_first,
    "unknown critical chunk": _unknown_critical,
    "duplicate IHDR": _duplicate_header,
    "missing IHDR": _missing_header,
    "missing IEND": _missing_iend,
    "chunk after IEND": _iend_not_last,
    "non-zero IEND body": _nonzero_iend,
    "IDAT split by another chunk": _split_idat,
    "no IDAT at all": _no_idat,
    "short IHDR body": _short_header_body,
    "corrupt CRC": _corrupt_crc,
    "truncated file": _truncated,
    "chunk length overrunning the file": _overrunning_length,
    "undecompressable image data": _bad_decompression,
}
"""Chunk-level damage. **Every** reader on both sides must refuse these.

The first three are the reviewer's cases, accepted by every V3 reader: a
duplicated IEND, an IHDR after the image data, and an unknown critical chunk.
"""

PROFILE_PNGS = {
    "wrong colour type": _wrong_colour_type,
    "undefined row filter": _bad_row_filter,
    "scanlines one byte short": _short_scanlines,
}
"""Legal chunk structure, wrong picture.

These are refused by the readers that *decode* -- and deliberately not by
``image_stream_digest``, whose whole job is to say whether a frame's image data
was replaced. A greyscale PNG has a perfectly valid IDAT stream, and a digest
function that refused it would be answering a question nobody asked it.
"""

MALFORMED_PNGS = {**STRUCTURAL_PNGS, **PROFILE_PNGS}
"""The whole corpus, for the readers that must refuse all of it."""

DECODING_READERS = (read_rgb_samples,)
"""Engine readers that decode a picture, and so judge the profile too."""

ENGINE_READERS = (read_rgb_samples, image_stream_digest)
"""The engine's two entry points into a frame's bytes."""


@pytest.mark.parametrize("name", sorted(STRUCTURAL_PNGS))
def test_every_reader_refuses_structurally_illegal_chunks(tmp_path: Path, name: str) -> None:
    """Chunk damage is refused by all four readers, on both sides of the boundary."""
    path = tmp_path / "frame.png"
    path.write_bytes(STRUCTURAL_PNGS[name]())
    for reader in ENGINE_READERS:
        with pytest.raises(FrameImageProblem):
            reader(path)
    for reader in (executor.png_facts, executor.png_pixels):
        with pytest.raises(executor.FrameRefused):
            reader(path)


@pytest.mark.parametrize("name", sorted(MALFORMED_PNGS))
def test_the_decoders_refuse_the_whole_corpus(tmp_path: Path, name: str) -> None:
    """Structure and profile alike, through the readers that decode a picture.

    ``png_pixels`` used to check no CRC and no chunk bound at all -- it was a
    second parser with a second idea of validity. It now shares the executor's
    one closed parser, so asking it and ``read_rgb_samples`` the same question
    must give the same answer.
    """
    path = tmp_path / "frame.png"
    path.write_bytes(MALFORMED_PNGS[name]())
    for reader in DECODING_READERS:
        with pytest.raises(FrameImageProblem):
            reader(path)
    with pytest.raises(executor.FrameRefused):
        executor.png_pixels(path)


@pytest.mark.parametrize("name", sorted(MALFORMED_PNGS))
def test_the_publication_gate_refuses_the_whole_corpus(tmp_path: Path, name: str) -> None:
    """Nothing in the corpus can reach its final filename.

    This is the gate a freshly rendered frame passes before ``os.replace``, and
    the same gate the resume path uses to re-verify a frame it is about to
    reuse, so both entry points into "this file is a frame" agree.
    """
    path = tmp_path / "frame.png"
    path.write_bytes(MALFORMED_PNGS[name]())
    profile = {"owned": {"resolution_x": 4, "resolution_y": 2}}
    with pytest.raises(executor.FrameRefused):
        executor.require_verified_frame(path, profile)


@pytest.mark.parametrize("name", sorted(MALFORMED_PNGS))
def test_no_malformed_png_escapes_as_an_unexpected_exception(tmp_path: Path, name: str) -> None:
    """`zlib.error`, `IndexError` and `struct.error` are not control flow.

    Both refusal types subclass ``ValueError``, so this asserts the corpus
    arrives as a refusal rather than as whatever the parser happened to trip on.
    A reader is allowed to *accept* a file outside its remit -- a digest
    function has no opinion on colour type -- but it may never crash on one.
    """
    path = tmp_path / "frame.png"
    path.write_bytes(MALFORMED_PNGS[name]())
    for reader in (read_rgb_samples, image_stream_digest, executor.png_facts, executor.png_pixels):
        try:
            reader(path)
        except ValueError:
            continue
        except BaseException as error:  # noqa: BLE001 - the escaping type is the point
            raise AssertionError(
                f"{name} escaped {reader.__name__} as {type(error).__name__}"
            ) from error


def test_both_sides_accept_the_sound_control(tmp_path: Path) -> None:
    """Without this, every refusal above could be a reader that refuses everything."""
    path = tmp_path / "frame.png"
    path.write_bytes(_sound_png())
    assert read_rgb_samples(path)[:2] == (4, 2)
    assert image_stream_digest(path)
    assert executor.png_facts(path)["width"] == 4
    assert executor.png_pixels(path)[:2] == (4, 2)


@pytest.mark.parametrize("kind", [b"tEXt", b"pHYs", b"oFFs", b"eXIf", b"PLTE"])
def test_the_chunks_real_frames_carry_are_still_legal(tmp_path: Path, kind: bytes) -> None:
    """The chunk-name rules must not refuse what Blender actually writes.

    All four ancillary types here appear in every frame of the canonical render.
    ``PLTE`` is included as the one critical chunk that is legal but unused: it
    is allowed before the image data and refused after it.
    """
    path = tmp_path / "frame.png"
    body = b"\x00" * 3 if kind == b"PLTE" else b"xy"
    path.write_bytes(
        _assemble(_chunk(b"IHDR", _rgb_header()), _chunk(kind, body), _idat(), _chunk(b"IEND", b""))
    )
    assert read_rgb_samples(path)[:2] == (4, 2)
    assert executor.png_facts(path)["width"] == 4


def test_ancillary_metadata_is_still_allowed(tmp_path: Path) -> None:
    """Blender writes tEXt, pHYs, oFFs and eXIf, and those are not errors.

    Ancillary chunks are skippable by design, which is exactly why
    ``image_sha256`` covers the image stream rather than the file: Blender
    stamps the render date into ``tEXt`` and the picture has not changed.
    """
    path = tmp_path / "frame.png"
    path.write_bytes(
        _assemble(
            _chunk(b"IHDR", _rgb_header()),
            _chunk(b"pHYs", b"\x00" * 9),
            _chunk(b"tEXt", b"Software\x00Blender"),
            _idat(),
            _chunk(b"IEND", b""),
        )
    )
    assert read_rgb_samples(path)[:2] == (4, 2)
    assert executor.png_facts(path)["height"] == 2


# --------------------------------------------------------------------------
# The IDAT payload is exactly one zlib stream
# --------------------------------------------------------------------------
#
# `zlib.decompress` stops at the end of the first stream and returns what it
# found, so a valid stream followed by anything at all decompresses happily and
# yields correct pixels. An independent reviewer built a PNG with legal chunk
# order, valid CRCs, valid scanlines and `JUNK` after the compressed data, and
# both decoders accepted it. Nothing downstream looks past the first stream, so
# neither `image_sha256` nor the decoded picture notices.


def _png_with_stream(payload: bytes) -> bytes:
    """A structurally perfect PNG whose IDAT carries exactly these bytes."""
    return _assemble(_chunk(b"IHDR", _rgb_header()), _chunk(b"IDAT", payload), _chunk(b"IEND", b""))


def _sound_stream() -> bytes:
    """One ordinary complete zlib stream of a flat picture."""
    return zlib.compress(_rgb_rows())


def _truncated_stream() -> bytes:
    """A stream cut short: it yields output, then simply stops."""
    return zlib.compress(_rgb_rows(), 0)[:-6]


def _bad_checksum_stream() -> bytes:
    """A complete stream whose trailing Adler-32 disagrees with its data."""
    stream = bytearray(_sound_stream())
    stream[-1] ^= 0xFF
    return bytes(stream)


def _raw_deflate_stream() -> bytes:
    """Deflate with no zlib header at all."""
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    return compressor.compress(_rgb_rows()) + compressor.flush()


STREAM_ATTACKS = {
    "one trailing NUL": lambda: _sound_stream() + b"\x00",
    "trailing arbitrary bytes": lambda: _sound_stream() + b"JUNK",
    "a second complete stream": lambda: _sound_stream() + zlib.compress(b"second"),
    "a truncated stream": _truncated_stream,
    "a corrupt Adler-32": _bad_checksum_stream,
    "an empty payload": lambda: b"",
    "raw deflate with no zlib header": _raw_deflate_stream,
}
"""Every compressed payload that is not exactly one complete zlib stream."""

STREAM_CONTROLS = {
    "default compression": _sound_stream,
    "no compression": lambda: zlib.compress(_rgb_rows(), 0),
    "maximum compression": lambda: zlib.compress(_rgb_rows(), 9),
}
"""Legal streams that must keep passing, whatever level produced them."""


@pytest.mark.parametrize("name", sorted(STREAM_ATTACKS))
def test_both_decoders_refuse_a_payload_that_is_not_one_exact_stream(
    tmp_path: Path, name: str
) -> None:
    """Truncation fails on `eof`; anything trailing fails on `unused_data`."""
    path = tmp_path / "frame.png"
    path.write_bytes(_png_with_stream(STREAM_ATTACKS[name]()))
    for reader in (read_rgb_samples, image_stream_digest):
        with pytest.raises(FrameImageProblem):
            reader(path)
    for reader in (executor.png_facts, executor.png_pixels):
        with pytest.raises(executor.FrameRefused):
            reader(path)


@pytest.mark.parametrize("name", sorted(STREAM_CONTROLS))
def test_an_ordinary_stream_still_passes_both_decoders(tmp_path: Path, name: str) -> None:
    """The control. A stricter terminator check must not refuse real output."""
    path = tmp_path / "frame.png"
    path.write_bytes(_png_with_stream(STREAM_CONTROLS[name]()))
    assert read_rgb_samples(path)[:2] == (4, 2)
    assert image_stream_digest(path)
    assert executor.png_facts(path)["width"] == 4
    assert executor.png_pixels(path)[:2] == (4, 2)


def test_a_stream_split_across_many_idat_chunks_still_passes(tmp_path: Path) -> None:
    """Real frames carry 108 to 130 IDAT chunks; the stream runs across all of them.

    The terminator check applies to the joined payload, never to one chunk at a
    time -- applied per chunk it would refuse every frame this phase has ever
    produced.
    """
    payload = _sound_stream()
    pieces = [payload[index : index + 4] for index in range(0, len(payload), 4)]
    assert len(pieces) > 3
    path = tmp_path / "frame.png"
    path.write_bytes(
        _assemble(
            _chunk(b"IHDR", _rgb_header()),
            *[_chunk(b"IDAT", piece) for piece in pieces],
            _chunk(b"IEND", b""),
        )
    )
    assert read_rgb_samples(path)[:2] == (4, 2)
    assert executor.png_pixels(path)[:2] == (4, 2)


def test_trailing_bytes_are_invisible_to_the_image_digest(tmp_path: Path) -> None:
    """Why the digest could not have caught this on its own.

    `image_sha256` covers the *inflated* stream, and inflation stops at the end
    of the first stream -- so a frame with trailing bytes hashes identically to
    the same frame without them. The digest was never going to notice; only
    asking the decompressor where the stream ended could.
    """
    clean = tmp_path / "clean.png"
    dirty = tmp_path / "dirty.png"
    clean.write_bytes(_png_with_stream(_sound_stream()))
    dirty.write_bytes(_png_with_stream(_sound_stream() + b"JUNK"))

    honest = image_stream_digest(clean)
    with pytest.raises(FrameImageProblem, match="after the end"):
        image_stream_digest(dirty)

    # The two files differ, but their inflated streams do not -- which is the
    # whole reason the refusal has to come from the decompressor's own state.
    assert clean.read_bytes() != dirty.read_bytes()
    assert zlib.decompress(_sound_stream() + b"JUNK") == zlib.decompress(_sound_stream())
    assert honest


def test_an_empty_stream_is_refused_by_the_digest_paths_too(tmp_path: Path) -> None:
    """A complete zlib stream containing nothing is still not a picture.

    ``zlib.compress(b"")`` satisfies every terminator assertion -- it ends
    properly and nothing follows it -- so the strict stream check alone let it
    through, and only the pixel decoders noticed the frame had no scanlines. The
    digest paths judge the payload size now as well, because a digest of nothing
    is a perfectly good digest of nothing.
    """
    path = tmp_path / "frame.png"
    path.write_bytes(_png_with_stream(zlib.compress(b"")))
    for reader in (read_rgb_samples, image_stream_digest):
        with pytest.raises(FrameImageProblem, match="scanline data"):
            reader(path)
    for reader in (executor.png_facts, executor.png_pixels):
        with pytest.raises(executor.FrameRefused, match="scanline data"):
            reader(path)


@pytest.mark.parametrize("short", [1, 12, 24])
def test_a_stream_of_the_wrong_length_is_refused_by_every_reader(
    tmp_path: Path, short: int
) -> None:
    """Every reader agrees on how many bytes a 4x2 frame decompresses to."""
    path = tmp_path / "frame.png"
    path.write_bytes(_png_with_stream(zlib.compress(_rgb_rows()[:-short])))
    for reader in (read_rgb_samples, image_stream_digest):
        with pytest.raises(FrameImageProblem):
            reader(path)
    for reader in (executor.png_facts, executor.png_pixels):
        with pytest.raises(executor.FrameRefused):
            reader(path)
