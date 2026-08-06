"""Canonical JSON encoding and strict decoding for save files.

Every byte written to a save passes through :func:`dumps_canonical`, and every
byte read back passes through :func:`loads_canonical`. That single path is what
makes a state hash mean anything: two runs that agree on the state must produce
byte-identical files, and a file that has been reformatted -- even into
something semantically equivalent -- must fail verification rather than be
quietly accepted.

The decoder is deliberately stricter than ``json.loads``. Python's default
accepts ``NaN``, ``Infinity``, and duplicate object keys, all of which either
cannot round-trip or silently discard data.
"""

import json
import math
from typing import Final

from living_diorama.events.event import JsonValue

_NON_STANDARD_CONSTANTS: Final = ("NaN", "Infinity", "-Infinity")
"""JSON constants Python accepts by default that a save may never contain."""


def require_json_value(value: object, description: str) -> JsonValue:
    """Return the value if it is strictly JSON-compatible, else raise.

    Type checks are exact rather than ``isinstance`` based, which is what keeps
    ``IntEnum`` and ``StrEnum`` members out: they subclass ``int`` and ``str``
    and would otherwise encode into something that no longer round-trips as the
    same Python type. Tuples are refused for the same reason -- ``json.dumps``
    would silently write one as a list, and the save would then load back as a
    different type than it was given.

    Args:
        value: The value to check.
        description: What is being checked, used in error messages.

    Returns:
        An independent JSON-compatible copy of the value.

    Raises:
        TypeError: If the value, or anything nested inside it, is of a type a
            save may not contain, or if a mapping key is not a ``str``.
        ValueError: If a float is not finite.
    """
    if value is None or type(value) is bool or type(value) is str or type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{description} must be a finite number, got {value!r}")
        return value
    if type(value) is list:
        return [
            require_json_value(item, f"{description}[{index}]") for index, item in enumerate(value)
        ]
    if type(value) is dict:
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError(
                    f"{description} has a non-string key {key!r} of type "
                    f"{type(key).__name__}; JSON object keys must be strings"
                )
            result[key] = require_json_value(item, f"{description}[{key!r}]")
        return result
    raise TypeError(f"{description} must be JSON-compatible, got {type(value).__name__}")


def dumps_canonical(document: object, description: str = "document") -> bytes:
    """Encode a document into the one byte form this project considers canonical.

    Keys are sorted and separators are compact so the bytes depend only on the
    data, never on the order a mapping happened to be built in. The trailing
    newline makes the files behave like ordinary text files for diffing and
    line-based tooling.

    Args:
        document: The JSON-compatible document to encode.
        description: What is being encoded, used in error messages.

    Returns:
        UTF-8 bytes ending in exactly one newline.

    Raises:
        TypeError: If the document is not strictly JSON-compatible.
        ValueError: If it contains a non-finite float.
    """
    checked = require_json_value(document, description)
    text = json.dumps(
        checked,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return text.encode("utf-8") + b"\n"


def _reject_duplicate_keys(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    """Build an object, refusing a repeated key instead of keeping the last one.

    Python's default keeps the last occurrence, so a tampered file carrying two
    values for one key would load as whichever the attacker put second, with no
    indication anything was dropped.
    """
    seen: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate JSON object key {key!r}")
        seen[key] = value
    return seen


def _reject_constant(name: str) -> JsonValue:
    """Refuse the non-standard JSON constants Python accepts by default."""
    raise ValueError(f"non-standard JSON constant {name!r} is not allowed in a save")


def loads_canonical(data: bytes, description: str = "document") -> JsonValue:
    """Decode save bytes strictly, refusing anything a save may not contain.

    Args:
        data: The exact bytes read from disk.
        description: What is being decoded, used in error messages.

    Returns:
        The decoded JSON document.

    Raises:
        TypeError: If ``data`` is not ``bytes``, or the document contains a
            value of a type a save may not carry.
        ValueError: If the bytes are not valid UTF-8, are not valid JSON, carry
            trailing content, repeat an object key, or contain ``NaN``, an
            infinity, or an overflowing numeric literal.
    """
    if type(data) is not bytes:
        raise TypeError(f"{description} must be bytes, got {type(data).__name__}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{description} is not valid UTF-8: {error}") from error

    try:
        document = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as error:
        raise ValueError(f"{description} is not valid JSON: {error}") from error

    # A literal such as 1e999 parses to infinity without touching parse_constant,
    # so finiteness is checked on the decoded document rather than trusted.
    return require_json_value(document, description)


def require_document(value: JsonValue, description: str) -> dict[str, JsonValue]:
    """Return the value if it is a JSON object, else raise.

    Raises:
        TypeError: If the top-level value is not a JSON object.
    """
    if type(value) is not dict:
        raise TypeError(f"{description} must be a JSON object, got {type(value).__name__}")
    return value
