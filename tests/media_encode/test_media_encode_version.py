"""Phase 35 version-line and capability-listing gates, pinned to the frozen laws.

V15-V22: only the first line is ever read, its version token must be a stable
major-9 release token, no path separator may appear, and a capability is present
exactly when its name is a whitespace-delimited token of some line.
"""

import pytest

from living_diorama.media_encode import media_encode_version as ver
from living_diorama.media_encode.media_encode_spec import MediaEncodeRefused

COPYRIGHT_TAIL = "Copyright (c) 2000 the FFmpeg developers"


@pytest.mark.parametrize(
    ("output", "tool"),
    [
        (f"ffmpeg version 9.0 {COPYRIGHT_TAIL}", "ffmpeg"),
        (f"ffmpeg version 9.0.1 {COPYRIGHT_TAIL}", "ffmpeg"),
        (f"ffmpeg version 9 {COPYRIGHT_TAIL}", "ffmpeg"),
        (
            f"ffmpeg version 9.0.1-full_build-www.gyan.dev {COPYRIGHT_TAIL}",
            "ffmpeg",
        ),
        (f"ffprobe version 9.0 {COPYRIGHT_TAIL}", "ffprobe"),
    ],
)
def test_parse_version_first_line_accepts_stable_major_nine_lines(output: str, tool: str) -> None:
    """Accepted vectors return the full first line verbatim."""
    assert ver.parse_version_first_line(output, tool) == output


def test_parse_version_first_line_returns_only_the_first_line() -> None:
    """Correction L: the FIRST line is the only line ever read or recorded."""
    output = (
        f"ffmpeg version 9.0 {COPYRIGHT_TAIL}\n"
        "built with gcc 13.2.0 (Ubuntu)\n"
        "configuration: --enable-libx264"
    )
    assert ver.parse_version_first_line(output, "ffmpeg") == f"ffmpeg version 9.0 {COPYRIGHT_TAIL}"


@pytest.mark.parametrize(
    "token",
    ["8.1.2", "10.0", "90.0", "09.0", "9x", "n9.0-static", "N-123456-g..."],
)
def test_parse_version_first_line_refuses_non_stable_major_nine_tokens(token: str) -> None:
    """Other majors, snapshots and degenerate spellings refuse, never fall back."""
    output = f"ffmpeg version {token} {COPYRIGHT_TAIL}"
    with pytest.raises(MediaEncodeRefused, match="cannot satisfy the reviewed request"):
        ver.parse_version_first_line(output, "ffmpeg")


def test_parse_version_first_line_refuses_garbage_token() -> None:
    """A non-version word in the version slot refuses."""
    with pytest.raises(MediaEncodeRefused, match="cannot satisfy the reviewed request"):
        ver.parse_version_first_line("ffmpeg version garbage stuff", "ffmpeg")


def test_parse_version_first_line_refuses_empty_output() -> None:
    """No output at all cannot satisfy the reviewed request."""
    with pytest.raises(MediaEncodeRefused, match="cannot satisfy the reviewed request"):
        ver.parse_version_first_line("", "ffmpeg")


def test_parse_version_first_line_refuses_a_missing_version_token() -> None:
    """A bare prefix with no token refuses."""
    with pytest.raises(MediaEncodeRefused, match="cannot satisfy the reviewed request"):
        ver.parse_version_first_line("ffmpeg version ", "ffmpeg")


def test_parse_version_first_line_refuses_the_wrong_tool_prefix() -> None:
    """The located tool's own name must open the line."""
    with pytest.raises(MediaEncodeRefused, match="cannot satisfy the reviewed request"):
        ver.parse_version_first_line("ffprobe version 9.0", "ffmpeg")


@pytest.mark.parametrize(
    "line",
    [
        "ffmpeg version 9.0 built /usr/local/bin/ffmpeg",
        "ffmpeg version 9.0 built with C:\\ffmpeg\\bin",
    ],
)
def test_parse_version_first_line_refuses_a_path_separator(line: str) -> None:
    """A canonical record never carries a host path."""
    with pytest.raises(MediaEncodeRefused, match="path separator"):
        ver.parse_version_first_line(line, "ffmpeg")


# ----------------------------------------------------------- capability gate


def test_require_capability_passes_when_the_name_is_its_own_token() -> None:
    """The -encoders listing's libx264 token satisfies the gate."""
    listing = " V..... libx264  H.264 (lossy codec)"
    ver.require_capability(listing, "libx264", "encoder listing")


def test_require_capability_refuses_a_substring_of_a_longer_name() -> None:
    """Token law: 'libx264x' does not satisfy 'libx264'."""
    with pytest.raises(MediaEncodeRefused, match="refuses without it"):
        ver.require_capability("libx264x", "libx264", "encoder listing")


def test_require_capability_refuses_when_the_capability_is_missing() -> None:
    """Missing capability refuses outright; there is no fallback codec."""
    with pytest.raises(MediaEncodeRefused, match="refuses without it"):
        ver.require_capability("", "libx264", "encoder listing")


def test_require_capability_refuses_a_non_str_listing() -> None:
    """The listing is a str, exactly."""
    with pytest.raises(TypeError):
        ver.require_capability(123, "libx264", "encoder listing")
