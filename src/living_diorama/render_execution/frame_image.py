"""Read a rendered frame's pixels, using the standard library alone.

The independent audit says it trusts nothing the renderer recorded, and that
has to include the renderer's own measurement of how far the boundary witness
sits from the final playback frame. Recomputing that measurement means
decoding the frames, and the audit cannot ask the Blender-side executor to do
it: that module imports ``bpy`` and this one may not.

So the decoder exists twice, deliberately, on either side of a boundary
neither may cross -- and a test drives both implementations over the same
images, through every PNG filter type, and requires identical samples and an
identical difference. Two copies that are proven to agree are honest; one copy
reached across a boundary would not be.

Only what Phase 23 writes is understood: eight-bit, non-interlaced RGB.
Anything else is refused rather than half-decoded, because a comparison of two
images this decoder only partly understood would be worse than no comparison.
"""

import hashlib
import zlib
from pathlib import Path
from typing import Final

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
"""The eight bytes every PNG begins with."""

EXPECTED_BIT_DEPTH: Final = 8
EXPECTED_COLOUR_TYPE: Final = 2
EXPECTED_COMPRESSION_METHOD: Final = 0
EXPECTED_FILTER_METHOD: Final = 0
EXPECTED_INTERLACE_METHOD: Final = 0
"""The exact image profile Phase 23 writes: eight-bit, non-interlaced RGB.

Named individually rather than compared as a tuple so a refusal can say which
of the five a file got wrong -- a greyscale frame, a sixteen-bit frame and an
Adam7-interlaced frame are three different mistakes with three different causes.
"""

VALID_FILTER_TYPES: Final = frozenset({0, 1, 2, 3, 4})
"""Every per-scanline filter PNG defines. A sixth value is a corrupt file."""

IHDR_LENGTH: Final = 13
"""An image header is exactly this long; a shorter one cannot be read at all."""

MAXIMUM_FRAME_EDGE: Final = 16384
"""No frame this phase writes is larger than this on either edge.

Restated from the executor so both readers refuse an implausible header for the
same reason. Without it the engine still refused such a file, but only later and
incidentally, when its scanline arithmetic failed to add up.
"""

KNOWN_CRITICAL_CHUNKS: Final = frozenset({b"IHDR", b"PLTE", b"IDAT", b"IEND"})
"""The only critical chunks PNG defines.

A chunk is *critical* when the fifth bit of its first byte is clear -- an
uppercase first letter. PNG's own rule is that a decoder which does not
understand a critical chunk must not proceed, because a critical chunk can
change what the image data means. So an unrecognised critical chunk is refused
rather than skipped: a file carrying one is not a picture this phase can claim
to have read.

Ancillary chunks (lowercase first letter) are skipped safely by design, and
Phase 23's frames carry several -- Blender writes ``tEXt``, ``pHYs``, ``oFFs``
and ``eXIf``. Those are metadata and may vary without the picture changing,
which is exactly why ``image_sha256`` covers the image stream and not the file.
"""


class FrameImageProblem(ValueError):
    """A file that is not a frame this phase wrote.

    Every way of being unreadable arrives here: a bad signature, a corrupt CRC,
    a truncated chunk, a header too short to parse, a stream zlib cannot
    inflate, a scanline count that does not match the declared size.

    It exists because the audit has to *report* a malformed frame, not die on
    one. ``zlib.decompress`` raises ``zlib.error``, slicing a short header
    raises ``IndexError``, and neither is a ``ValueError`` -- so a single
    corrupt frame used to escape the audit as a traceback, which reads as the
    tool breaking rather than as the finding it actually is. A verifier that
    crashes on the first bad file also never reaches the other 192.
    """


def _inflate(payload: bytes, description: str) -> bytes:
    """Decompress the image stream, requiring it to be exactly one complete stream.

    ``zlib.decompress`` is too forgiving for this. It stops at the end of the
    first stream and returns what it found, so a valid stream followed by
    arbitrary bytes -- or by a second complete stream -- decompresses happily
    and yields correct-looking pixels. An independent reviewer built exactly
    that: legal chunk order, valid CRCs, valid scanlines, and ``JUNK`` sitting
    after the end of the compressed data. Both decoders accepted it.

    The concatenated IDAT payload of a PNG *is* one zlib stream. So the
    decompressor is driven explicitly and asked three questions afterwards:
    did the stream reach its own terminator (``eof``), is there anything after
    it (``unused_data``), and did anything go unconsumed (``unconsumed_tail``).
    A truncated stream fails the first, trailing bytes fail the second.

    The check applies to the payload of every IDAT joined together, never to
    one chunk at a time -- a real frame here carries 108 to 130 IDAT chunks and
    the stream runs across all of them.

    Raises:
        FrameImageProblem: If the payload is not exactly one complete zlib stream.
    """
    decompressor = zlib.decompressobj()
    try:
        data = decompressor.decompress(payload)
        data += decompressor.flush()
    except zlib.error as error:
        raise FrameImageProblem(
            f"{description} image data could not be decompressed: {error}"
        ) from error
    if not decompressor.eof:
        raise FrameImageProblem(
            f"{description} image data ends before its compressed stream does; the stream "
            "is truncated"
        )
    if decompressor.unused_data:
        raise FrameImageProblem(
            f"{description} carries {len(decompressor.unused_data)} bytes after the end of "
            "its compressed image stream; the image data is exactly one zlib stream and "
            "nothing follows it"
        )
    if decompressor.unconsumed_tail:
        raise FrameImageProblem(
            f"{description} left {len(decompressor.unconsumed_tail)} bytes of its image "
            "stream unconsumed"
        )
    return data


def _chunks(data: bytes, description: str) -> list[tuple[bytes, bytes]]:
    """Return every (kind, body) chunk of a structurally legal PNG.

    Not merely "every chunk type this phase needs appeared somewhere". PNG
    defines an *order*, and a file that carries the right chunks in the wrong
    arrangement is not a PNG that happens to be unusual -- it is a file two
    decoders will disagree about. An independent reviewer walked three such
    files past the V3 reader: a second ``IEND``, an ``IHDR`` sitting after the
    image data, and an unknown critical chunk. All three had valid CRCs and
    decodable pixels, and all three were accepted.

    So the arrangement is checked as a state machine:

    * the signature, then chunks with valid lengths and CRCs
    * ``IHDR`` exactly once, and first, with a body of exactly 13 bytes
    * ``IEND`` exactly once, and last, with an empty body, ending at end of file
    * at least one ``IDAT``, all of them consecutive, after ``IHDR`` and before
      ``IEND``
    * no unrecognised critical chunk anywhere

    Raises:
        FrameImageProblem: If the file is not a structurally legal PNG.
    """
    if not data.startswith(PNG_SIGNATURE):
        raise FrameImageProblem(f"{description} does not begin with the PNG signature")
    offset = len(PNG_SIGNATURE)
    found: list[tuple[bytes, bytes]] = []
    end_offset: int | None = None
    while offset < len(data):
        if end_offset is not None:
            raise FrameImageProblem(f"{description} carries a chunk after its IEND")
        if offset + 8 > len(data):
            raise FrameImageProblem(
                f"{description} ends inside a chunk header; the file is truncated"
            )
        length = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8]
        body_start = offset + 8
        body_end = body_start + length
        if body_end + 4 > len(data):
            raise FrameImageProblem(
                f"{description} ends inside a {kind!r} chunk; the file is truncated"
            )
        body = data[body_start:body_end]
        stored = int.from_bytes(data[body_end : body_end + 4], "big")
        if zlib.crc32(kind + body) & 0xFFFFFFFF != stored:
            raise FrameImageProblem(f"{description} has a corrupt {kind!r} chunk")
        if len(kind) != 4 or not kind.isalpha() or not kind.isascii():
            raise FrameImageProblem(
                f"{description} carries a chunk type {kind!r} that is not four ASCII "
                "letters; PNG chunk names are letters and nothing else"
            )
        if kind[2] & 0x20:
            raise FrameImageProblem(
                f"{description} carries chunk {kind!r} with its reserved bit set; PNG "
                "reserves that bit and a file using it means something this decoder does not "
                "know"
            )
        critical = not kind[0] & 0x20
        if critical and kind not in KNOWN_CRITICAL_CHUNKS:
            raise FrameImageProblem(
                f"{description} carries the unknown critical chunk {kind!r}; a critical chunk "
                "can change what the image data means, so a reader that does not understand "
                "one must not claim to have read the picture"
            )
        if not found and kind != b"IHDR":
            raise FrameImageProblem(
                f"{description} opens with {kind!r}; a PNG begins with its image header"
            )
        if kind == b"IEND":
            end_offset = body_end + 4
        found.append((kind, body))
        offset = body_end + 4

    kinds = [kind for kind, _ in found]
    headers = kinds.count(b"IHDR")
    if headers != 1:
        raise FrameImageProblem(
            f"{description} declares {headers} image headers; exactly one is expected"
        )
    if len(found[0][1]) != IHDR_LENGTH:
        raise FrameImageProblem(
            f"{description} has a {len(found[0][1])}-byte image header; exactly {IHDR_LENGTH} "
            "are required before any of it can be believed"
        )
    if end_offset is None:
        raise FrameImageProblem(f"{description} carries no IEND chunk")
    if kinds.count(b"IEND") != 1:
        raise FrameImageProblem(f"{description} carries {kinds.count(b'IEND')} IEND chunks")
    if kinds[-1] != b"IEND":
        raise FrameImageProblem(f"{description} does not end with its IEND chunk")
    if found[-1][1]:
        raise FrameImageProblem(
            f"{description} carries {len(found[-1][1])} bytes inside its IEND, which is empty "
            "by definition"
        )
    if end_offset != len(data):
        raise FrameImageProblem(f"{description} carries data after its IEND chunk")
    if b"IDAT" not in kinds:
        raise FrameImageProblem(f"{description} carries no image data")
    palettes = kinds.count(b"PLTE")
    if palettes > 1:
        raise FrameImageProblem(f"{description} carries {palettes} palettes; PNG allows one")
    if palettes and kinds.index(b"PLTE") > kinds.index(b"IDAT"):
        raise FrameImageProblem(
            f"{description} places its palette after its image data; a palette the decoder "
            "reaches too late is a palette the picture was not drawn with"
        )
    first = kinds.index(b"IDAT")
    last = len(kinds) - 1 - kinds[::-1].index(b"IDAT")
    if kinds[first : last + 1] != [b"IDAT"] * (last - first + 1):
        raise FrameImageProblem(
            f"{description} splits its image data around another chunk; PNG requires every "
            "IDAT to be consecutive"
        )
    return found


def _require_scanline_payload(raw: bytes, width: int, height: int, description: str) -> None:
    """Refuse an inflated stream that is not exactly the scanlines the header implies.

    An empty zlib stream satisfies every terminator assertion -- it is complete
    and correctly ended and contains nothing -- so this digest would otherwise
    happily hash a frame with no picture in it, and only the pixel decoder would
    object. Both paths need the same fact, so both check it.

    Raises:
        FrameImageProblem: If the payload is not ``(width * 3 + 1) * height`` bytes.
    """
    expected = (width * 3 + 1) * height
    if len(raw) != expected:
        raise FrameImageProblem(
            f"{description} decompresses to {len(raw)} bytes, but a {width}x{height} frame is "
            f"{expected} bytes of scanline data"
        )


def image_stream_digest(path: str | Path) -> str:
    """Return the digest of one frame's decompressed image stream.

    This is what the manifest records as ``image_sha256``. It is the digest of
    the inflated, still-filtered scanline data -- not of the file, which
    carries Blender's render date, and not of the decoded pixels. It answers
    one question: was this frame's image data replaced, or only its metadata.

    Raises:
        FrameImageProblem: If the file is not a structurally complete PNG.
    """
    data = Path(path).read_bytes()
    chunks = _chunks(data, str(path))
    payload = b"".join(body for kind, body in chunks if kind == b"IDAT")
    if not payload:
        raise FrameImageProblem(f"{path} carries no image data")
    raw = _inflate(payload, str(path))
    header = chunks[0][1]
    _require_scanline_payload(
        raw,
        int.from_bytes(header[0:4], "big"),
        int.from_bytes(header[4:8], "big"),
        str(path),
    )
    return hashlib.sha256(raw).hexdigest()


def read_rgb_samples_bytes(data: bytes, description: str = "frame") -> tuple[int, int, bytearray]:
    """Return width, height and unfiltered RGB samples from in-memory PNG bytes.

    The bytes-based twin of :func:`read_rgb_samples`, added so pure consumers
    (the lighting QA metrics) can decode frames they already hold as bytes
    without touching the filesystem. The decoding path is shared: this function
    contains the one implementation, and the path-based reader delegates to it,
    so a picture read from disk and the same picture read from memory cannot
    drift apart.

    Args:
        data: The exact bytes of an eight-bit, non-interlaced RGB PNG.
        description: What the bytes are, for error messages (default ``"frame"``).

    Returns:
        A ``(width, height, samples)`` triple where ``samples`` holds one byte
        per RGB channel in row-major order.

    Raises:
        FrameImageProblem: If the bytes are not an eight-bit non-interlaced RGB
            PNG, or use a scanline filter this decoder does not know.
    """
    chunks = _chunks(data, description)
    # Exactly one IHDR, first, and thirteen bytes long: the parser proved all
    # three, so this is the header.
    header = chunks[0][1]
    width = int.from_bytes(header[0:4], "big")
    height = int.from_bytes(header[4:8], "big")
    depth, colour, compression, filtering, interlace = header[8:13]
    for label, actual, expected in (
        ("bit depth", depth, EXPECTED_BIT_DEPTH),
        ("colour type", colour, EXPECTED_COLOUR_TYPE),
        ("compression method", compression, EXPECTED_COMPRESSION_METHOD),
        ("filter method", filtering, EXPECTED_FILTER_METHOD),
        ("interlace method", interlace, EXPECTED_INTERLACE_METHOD),
    ):
        if actual != expected:
            raise FrameImageProblem(
                f"{description} declares {label} {actual}, but Phase 23 writes {expected}; this "
                "decoder reads only what this phase writes, and half-decoding the rest would "
                "be worse than refusing it"
            )
    if not 1 <= width <= MAXIMUM_FRAME_EDGE or not 1 <= height <= MAXIMUM_FRAME_EDGE:
        raise FrameImageProblem(
            f"{description} declares implausible dimensions {width}x{height}; a header beyond "
            f"{MAXIMUM_FRAME_EDGE} on an edge is corrupt or hostile, not a very large picture"
        )

    payload = b"".join(body for kind, body in chunks if kind == b"IDAT")
    if not payload:
        raise FrameImageProblem(f"{description} carries no image data")
    raw = _inflate(payload, description)
    _require_scanline_payload(raw, width, height, description)
    stride = width * 3

    out = bytearray(stride * height)
    previous = bytearray(stride)
    position = 0
    for row in range(height):
        filter_type = raw[position]
        position += 1
        line = bytearray(raw[position : position + stride])
        position += stride
        if filter_type not in VALID_FILTER_TYPES:
            raise FrameImageProblem(f"{description} row {row} uses unknown filter {filter_type}")
        if filter_type == 0:
            # None: the scanline already holds its samples.
            out[row * stride : (row + 1) * stride] = line
            previous = line
            continue
        if filter_type == 2:
            # Up: every sample depends only on the one above it, so the row is a
            # whole-row addition rather than a walk with carried state.
            line = bytearray((a + b) & 0xFF for a, b in zip(line, previous, strict=True))
            out[row * stride : (row + 1) * stride] = line
            previous = line
            continue
        for index in range(stride):
            left = line[index - 3] if index >= 3 else 0
            up = previous[index]
            corner = previous[index - 3] if index >= 3 else 0
            if filter_type == 1:
                line[index] = (line[index] + left) & 0xFF
            elif filter_type == 2:
                line[index] = (line[index] + up) & 0xFF
            elif filter_type == 3:
                line[index] = (line[index] + ((left + up) >> 1)) & 0xFF
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
                line[index] = (line[index] + predictor) & 0xFF
        out[row * stride : (row + 1) * stride] = line
        previous = line
    return width, height, out


def read_rgb_samples(path: str | Path) -> tuple[int, int, bytearray]:
    """Return one frame's width, height and unfiltered RGB samples.

    Raises:
        FrameImageProblem: If the file is not an eight-bit non-interlaced RGB
            PNG, or uses a scanline filter this decoder does not know.
    """
    return read_rgb_samples_bytes(Path(path).read_bytes(), str(path))


def verify_frame_image(path: str | Path, *, expected_width: int, expected_height: int) -> list[str]:
    """Return every way this file fails to be a frame of the declared profile.

    An empty list means the file was decoded completely -- signature, chunk
    structure, every CRC, exactly one well-formed header, the declared profile,
    a stream that inflates to exactly the scanlines the header implies, a valid
    filter byte on every row, and a successful unfilter of all of them -- and
    that the picture is the size the render profile requires.

    That last clause is the one a digest cannot supply. Re-hashing a frame
    proves it is the file the manifest recorded; it says nothing about whether
    that file is a frame. An attacker who replaces frame 100 with a valid
    640x360 picture and rewrites the manifest's three digests to match has
    produced a directory that is internally consistent and visibly wrong, and
    only decoding the image catches it.

    Problems are returned rather than raised because the audit reports on 193
    files and a bad one must not stop it reaching the rest.

    Args:
        path: The frame file to decode.
        expected_width: The render profile's horizontal resolution.
        expected_height: The render profile's vertical resolution.

    Returns:
        Human-readable problems, empty when the frame is sound.
    """
    try:
        width, height, _ = read_rgb_samples(path)
    except FrameImageProblem as problem:
        return [str(problem)]
    if (width, height) != (expected_width, expected_height):
        return [
            f"{path} is a {width}x{height} image, but this render's profile requires "
            f"{expected_width}x{expected_height}"
        ]
    return []


def mean_abs_difference(first: str | Path, second: str | Path) -> float:
    """Return the mean absolute per-sample difference between two frames.

    Zero means pixel-identical. Small means the two frames differ only by
    sampling noise or a frame of motion. The unit is levels out of 255, which
    is what the render profile's tolerances are expressed in.

    Raises:
        FrameImageProblem: If either file is not a frame this phase wrote.
        ValueError: If the two frames differ in size.
    """
    width_a, height_a, samples_a = read_rgb_samples(first)
    width_b, height_b, samples_b = read_rgb_samples(second)
    if (width_a, height_a) != (width_b, height_b):
        raise ValueError(
            f"cannot compare {width_a}x{height_a} with {width_b}x{height_b}; the frames are not "
            "the same size"
        )
    total = sum(abs(a - b) for a, b in zip(samples_a, samples_b, strict=True))
    return round(total / len(samples_a), 6)
