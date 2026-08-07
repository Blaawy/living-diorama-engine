"""Safe runtime-type checks for serializer validation.

When its fast path fails, ``isinstance`` may consult a caller-controlled
``__class__`` attribute, executing code owned by the very object under
validation -- and a hostile override could then replace a serializer's
documented refusal with its own exception. ``issubclass`` on ``type(value)``
answers the same question, legitimate subclasses and ABC registrations
included, without touching the instance.

Private to the serializer package. Nothing here is exported, and nothing here
may import from :mod:`living_diorama.memory`: persistence depends on memory in
exactly one direction already, and this module must not add another edge.
"""

from collections.abc import Mapping
from typing import TypeIs


def is_runtime_instance[ExpectedT](
    value: object, expected_type: type[ExpectedT]
) -> TypeIs[ExpectedT]:
    """Report whether the value's true runtime type is an ``expected`` subclass.

    ``expected_type`` must be a concrete class; the abstract ``Mapping``
    boundary goes through :func:`has_mapping_type` instead.
    """
    return issubclass(type(value), expected_type)


def has_mapping_type(value: object) -> bool:
    """Report whether the value's true runtime type is a ``Mapping`` subclass."""
    return issubclass(type(value), Mapping)
