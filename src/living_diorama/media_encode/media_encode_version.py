r"""The Phase 35 tool gates: version-line law and capability-listing law, pure.

Correction L, whole: the FIRST line of ``<tool> -version`` is the only line ever read or
recorded. Its version token -- the first whitespace-delimited word after the literal
``"<tool> version "`` prefix -- must match ``^9(\\.|$|-)``: the major digit string is
exactly ``9``, followed by end, a dot, or a hyphen. Stable release-family builds
(``9.0``, ``9.0.1``, ``9.0.1-full_build-www.gyan.dev``) pass; development and snapshot
naming (``n9.0-...``, ``N-123456-g...``), other majors (``8.1.2``, ``10.0``, ``90.0``)
and degenerate spellings (``9x``, ``09.0``) refuse. The identical, independent law binds
ffmpeg AND ffprobe. The first line must also carry no path separator -- configuration
lines, which may name build prefixes, are never read.

Capability listings are the tool's own ``-encoders``/``-muxers``/``-demuxers`` stdout;
a capability is present exactly when some line carries its name as a whitespace-delimited
token. Refusal, never fallback: no other codec, no downgrade, no download.
"""

import re
from typing import Final

from living_diorama.media_encode.media_encode_spec import FFMPEG_MAJOR, MediaEncodeRefused

_VERSION_TOKEN_PATTERN: Final = re.compile(rf"^{FFMPEG_MAJOR}(\.|$|-)")
"""The one frozen token law: leading decimal major exactly 9, then end, dot or hyphen."""


def parse_version_first_line(output: str, tool: str) -> str:
    """Return the recorded first line of one tool's ``-version`` output, gated.

    Args:
        output: The tool's complete ``-version`` stdout.
        tool: The tool's own name -- ``"ffmpeg"`` or ``"ffprobe"`` -- which the first
            line's literal prefix must carry.

    Returns:
        The full first line, verbatim, as the manifest records it.

    Raises:
        TypeError: If either value is not a ``str``.
        MediaEncodeRefused: If the first line does not carry the literal prefix, its
            version token is not a stable major-9 release token, or the line carries a
            path separator.
    """
    if type(output) is not str:
        raise TypeError(f"output must be a str, got {type(output).__name__}")
    if type(tool) is not str:
        raise TypeError(f"tool must be a str, got {type(tool).__name__}")
    first_line = output.split("\n", 1)[0].rstrip("\r")
    prefix = f"{tool} version "
    if not first_line.startswith(prefix):
        raise MediaEncodeRefused(
            f"the located {tool} reports {first_line!r}, which does not begin "
            f"{prefix!r}; this environment cannot satisfy the reviewed request"
        )
    remainder = first_line[len(prefix) :]
    token = remainder.split(" ", 1)[0] if remainder else ""
    if not token or _VERSION_TOKEN_PATTERN.match(token) is None:
        raise MediaEncodeRefused(
            f"the profile requires the FFmpeg {FFMPEG_MAJOR} stable release family, but the "
            f"located {tool} reports version token {token!r}; this environment cannot "
            "satisfy the reviewed request"
        )
    if "/" in first_line or ":\\" in first_line:
        raise MediaEncodeRefused(
            f"the located {tool}'s version line {first_line!r} carries a path separator; a "
            "canonical record never carries a host path"
        )
    return first_line


def require_capability(listing: str, name: str, description: str) -> None:
    """Refuse unless a capability listing names this capability as its own token.

    Args:
        listing: The tool's ``-encoders``, ``-muxers`` or ``-demuxers`` stdout.
        name: The capability's exact name, e.g. ``"libx264"``.
        description: Which listing this is, for the refusal message.

    Raises:
        TypeError: If a value is not a ``str``.
        MediaEncodeRefused: If no line carries the name as a whitespace-delimited token.
    """
    if type(listing) is not str:
        raise TypeError(f"listing must be a str, got {type(listing).__name__}")
    if type(name) is not str:
        raise TypeError(f"name must be a str, got {type(name).__name__}")
    for line in listing.splitlines():
        if name in line.split():
            return
    raise MediaEncodeRefused(
        f"the located ffmpeg lists no {name!r} in its {description}; the reviewed profile "
        "refuses without it"
    )


__all__ = ["parse_version_first_line", "require_capability"]
