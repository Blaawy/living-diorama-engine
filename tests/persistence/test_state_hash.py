"""Tests for SHA-256 hashing of exact save bytes."""

import hashlib

import pytest

from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import require_hash_hex, sha256_hex


def test_matches_a_known_fixture() -> None:
    """Pinned against the standard library so a change in either is visible."""
    assert sha256_hex(b"") == ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
    assert sha256_hex(b"abc") == hashlib.sha256(b"abc").hexdigest()


def test_output_is_sixty_four_lowercase_hex_characters() -> None:
    """One fixed textual shape, so a digest is comparable as a plain string."""
    digest = sha256_hex(b"living diorama")
    assert len(digest) == 64
    assert digest == digest.lower()
    assert set(digest) <= set("0123456789abcdef")


def test_one_changed_byte_changes_the_digest() -> None:
    """The property the whole verification chain rests on."""
    assert sha256_hex(b"episode") != sha256_hex(b"episodf")


def test_a_reformatted_payload_hashes_differently() -> None:
    """Two encodings of the same data are not interchangeable on disk."""
    canonical = dumps_canonical({"a": 1, "b": 2})
    spaced = b'{"a": 1, "b": 2}\n'
    assert sha256_hex(canonical) != sha256_hex(spaced)


def test_hashing_requires_bytes() -> None:
    """Hashing text would depend on an encoding choice made somewhere else."""
    with pytest.raises(TypeError):
        sha256_hex("abc")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "abc",
        "A" * 64,
        "g" * 64,
        "0" * 63,
        "0" * 65,
        "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855",
    ],
)
def test_malformed_digests_are_refused(bad: str) -> None:
    """Uppercase and wrong-length strings are not digests this project writes."""
    with pytest.raises(ValueError):
        require_hash_hex(bad, "digest")


@pytest.mark.parametrize("bad", [None, 1, b"0" * 64, ["a"]])
def test_non_string_digests_are_refused(bad: object) -> None:
    """A digest is recorded as text."""
    with pytest.raises(TypeError):
        require_hash_hex(bad, "digest")


def test_a_valid_digest_is_returned_unchanged() -> None:
    """Validation reports; it does not normalize."""
    digest = sha256_hex(b"x")
    assert require_hash_hex(digest, "digest") == digest
