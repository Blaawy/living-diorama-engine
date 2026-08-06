"""SHA-256 hashing of the exact bytes written to a save."""

import hashlib
import re
from typing import Final

HASH_PATTERN: Final = re.compile(r"\A[0-9a-f]{64}\Z")
"""A SHA-256 digest as this project records it: 64 lowercase hex characters."""


def sha256_hex(payload: bytes) -> str:
    """Return the SHA-256 digest of exactly these bytes.

    Hashing the bytes rather than the parsed document is the whole point: a
    payload that has been reformatted carries the same meaning but different
    bytes, and must fail verification rather than be accepted as equivalent.

    Args:
        payload: The exact bytes written to or read from disk.

    Returns:
        The digest as 64 lowercase hexadecimal characters.

    Raises:
        TypeError: If the payload is not ``bytes``.
    """
    if type(payload) is not bytes:
        raise TypeError(f"payload must be bytes, got {type(payload).__name__}")
    return hashlib.sha256(payload).hexdigest()


def require_hash_hex(value: object, description: str) -> str:
    """Return the value if it is a well-formed digest, else raise.

    Raises:
        TypeError: If the value is not a ``str``.
        ValueError: If it is not 64 lowercase hexadecimal characters.
    """
    if type(value) is not str:
        raise TypeError(f"{description} must be a str, got {type(value).__name__}")
    if HASH_PATTERN.match(value) is None:
        raise ValueError(
            f"{description} must be 64 lowercase hexadecimal characters, got {value!r}"
        )
    return value
