"""Tests for canonical JSON encoding and strict decoding.

The codec is the narrow point every saved byte passes through, so a weakness
here would quietly undermine every hash in the project. Most of these tests are
about what the decoder refuses, because Python's default JSON handling accepts
several things that either cannot round-trip or silently discard data.
"""

import json
import math

import pytest

from living_diorama.persistence.json_codec import (
    dumps_canonical,
    loads_canonical,
    require_document,
    require_json_value,
)


def test_keys_are_sorted_regardless_of_insertion_order() -> None:
    """Two mappings holding the same data must encode to the same bytes.

    Without this, the state hash would describe how a dict was built rather
    than what it contains.
    """
    forward = dumps_canonical({"a": 1, "b": 2, "c": 3})
    backward = dumps_canonical({"c": 3, "b": 2, "a": 1})

    assert forward == backward
    assert forward == b'{"a":1,"b":2,"c":3}\n'


def test_nested_keys_are_sorted_too() -> None:
    """Ordering is canonical at every depth, not only at the top level."""
    assert dumps_canonical({"outer": {"z": 1, "a": 2}}) == b'{"outer":{"a":2,"z":1}}\n'


def test_separators_are_compact() -> None:
    """No incidental whitespace, so formatting cannot drift between writers."""
    assert dumps_canonical([1, 2, {"k": "v"}]) == b'[1,2,{"k":"v"}]\n'


def test_output_ends_with_exactly_one_newline() -> None:
    """One trailing newline keeps the files well behaved for text tooling."""
    encoded = dumps_canonical({"k": "v"})
    assert encoded.endswith(b"\n")
    assert not encoded.endswith(b"\n\n")
    assert encoded.count(b"\n") == 1


def test_non_ascii_text_is_written_as_utf8_not_escaped() -> None:
    """Text stays readable and byte-identical across platforms."""
    encoded = dumps_canonical({"name": "Sharjah — الشارقة"})
    assert "الشارقة" in encoded.decode("utf-8")
    assert b"\\u" not in encoded


def test_round_trip_preserves_values_and_types() -> None:
    """Encoding then decoding returns the same document."""
    document = {
        "int": 7,
        "float": 2.5,
        "str": "text",
        "true": True,
        "false": False,
        "null": None,
        "list": [1, "two", 3.0, False, None],
        "object": {"nested": {"deep": []}},
    }
    assert loads_canonical(dumps_canonical(document)) == document


def test_bool_and_int_stay_distinct_through_a_round_trip() -> None:
    """``True`` must not come back as ``1``; they mean different things."""
    decoded = loads_canonical(dumps_canonical({"flag": True, "count": 1}))
    assert decoded["flag"] is True
    assert type(decoded["count"]) is int
    assert type(decoded["flag"]) is bool


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_are_refused_on_encode(bad: float) -> None:
    """A save may not contain a value JSON cannot represent."""
    with pytest.raises(ValueError):
        dumps_canonical({"value": bad})


@pytest.mark.parametrize("text", ['{"value": NaN}', '{"value": Infinity}', '{"value": -Infinity}'])
def test_non_standard_constants_are_refused_on_decode(text: str) -> None:
    """Python accepts these by default; a save must not."""
    with pytest.raises(ValueError):
        loads_canonical(text.encode("utf-8"))


def test_an_overflowing_literal_is_refused_even_though_it_parses() -> None:
    """``1e999`` becomes infinity without touching the constant hook.

    Checking finiteness on the decoded document rather than trusting the parser
    is what catches it.
    """
    with pytest.raises(ValueError):
        loads_canonical(b'{"value":1e999}')


def test_duplicate_object_keys_are_refused() -> None:
    """Python keeps the last occurrence, silently dropping the first.

    A tampered file carrying two values for one key would otherwise load as
    whichever an attacker placed second, with nothing to indicate a loss.
    """
    with pytest.raises(ValueError):
        loads_canonical(b'{"k":1,"k":2}')


def test_duplicate_keys_are_refused_when_nested() -> None:
    """The check applies at every depth."""
    with pytest.raises(ValueError):
        loads_canonical(b'{"outer":{"k":1,"k":2}}')


@pytest.mark.parametrize(
    "data", [b'{"k":1} trailing', b"{}{}", b"[1,2]junk", b'{"k":1}\n{"k":2}\n']
)
def test_trailing_content_is_refused(data: bytes) -> None:
    """A file holding a second document is not a save this writer produced."""
    with pytest.raises(ValueError):
        loads_canonical(data)


@pytest.mark.parametrize("data", [b"", b"{", b"not json", b'{"k":}', b"[1,]"])
def test_malformed_json_is_refused(data: bytes) -> None:
    """Parse failures surface as a clear error rather than a partial document."""
    with pytest.raises(ValueError):
        loads_canonical(data)


def test_invalid_utf8_is_refused() -> None:
    """A truncated multi-byte sequence is corruption, not text."""
    with pytest.raises(ValueError):
        loads_canonical(b'{"k":"\xff\xfe"}')


def test_decoding_requires_bytes() -> None:
    """Hashes are over bytes, so decoding starts from bytes too."""
    with pytest.raises(TypeError):
        loads_canonical('{"k":1}')  # type: ignore[arg-type]


def test_non_string_object_keys_are_refused() -> None:
    """``json.dumps`` would coerce an int key to a string and lose its type."""
    with pytest.raises(TypeError):
        dumps_canonical({1: "one"})


@pytest.mark.parametrize("bad", [(1, 2), {1, 2}, frozenset({1}), object(), b"bytes", 1j])
def test_types_a_save_may_not_contain_are_refused(bad: object) -> None:
    """A tuple would silently encode as a list and load back as a different type."""
    with pytest.raises(TypeError):
        dumps_canonical({"value": bad})


def test_int_and_str_subclasses_are_refused() -> None:
    """``IntEnum`` and ``StrEnum`` members pass ``isinstance`` but do not round-trip."""
    import enum  # noqa: PLC0415

    class Number(enum.IntEnum):
        """An int subclass that would otherwise pass an isinstance check."""

        ONE = 1

    class Label(enum.StrEnum):
        """A str subclass with the same problem."""

        NAME = "name"

    with pytest.raises(TypeError):
        dumps_canonical({"value": Number.ONE})
    with pytest.raises(TypeError):
        dumps_canonical({"value": Label.NAME})


def test_require_json_value_returns_an_independent_copy() -> None:
    """Validation must not hand back a reference the caller can still edit."""
    original = {"list": [1, 2], "nested": {"k": "v"}}
    checked = require_json_value(original, "document")

    assert checked == original
    checked["list"].append(3)  # type: ignore[union-attr,index]
    assert original["list"] == [1, 2]


def test_require_document_rejects_a_non_object_top_level() -> None:
    """Every save file is a JSON object; an array is a different format."""
    with pytest.raises(TypeError):
        require_document(loads_canonical(b"[1,2,3]"), "document")


def test_a_reformatted_document_decodes_the_same_but_hashes_differently() -> None:
    """Semantic equality is not byte equality, which is the point of hashing."""
    canonical = dumps_canonical({"b": 2, "a": 1})
    reformatted = json.dumps({"a": 1, "b": 2}, indent=2).encode("utf-8") + b"\n"

    assert loads_canonical(canonical) == loads_canonical(reformatted)
    assert canonical != reformatted


def test_negative_zero_survives_a_round_trip() -> None:
    """JSON keeps the sign, and so must the codec."""
    decoded = loads_canonical(dumps_canonical({"value": -0.0}))
    assert math.copysign(1.0, decoded["value"]) == -1.0  # type: ignore[index,arg-type]


def test_large_finite_values_are_accepted() -> None:
    """Extreme but representable numbers are valid state, not corruption."""
    document = {"big": 1e308, "small": 5e-324, "negative": -1e308, "huge_int": 2**80}
    assert loads_canonical(dumps_canonical(document)) == document
