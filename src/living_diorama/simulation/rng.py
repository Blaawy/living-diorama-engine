"""Deterministic random number generation for the simulation.

Every stochastic decision in the engine must flow through a single seeded
wrapper. That is what makes an episode reproducible: given the same seed and
the same sequence of calls, the same numbers come out, so a run can be replayed,
diffed, or resumed exactly.

This module depends on the standard library only. It deliberately knows nothing
about entities, events, or the world -- randomness is a primitive, not a domain
concept.
"""

import random
from collections.abc import MutableSequence, Sequence

type RngStateValue = (
    None | bool | int | float | str | list[RngStateValue] | dict[str, RngStateValue]
)
"""A JSON-compatible value, used for exported RNG state.

Declared locally rather than shared with the event layer: this module may not
import other project packages, and introducing a shared types module would add a
file the approved architecture does not define.
"""

_STATE_FORMAT = 1
_STATE_FORMAT_KEY = "state_format"
_RANDOM_STATE_KEY = "random_state"


def _to_json(value: object) -> RngStateValue:
    """Recursively convert a random-state structure into JSON-compatible values.

    ``random.Random.getstate`` returns nested tuples, which JSON has no notion
    of. This converts tuples to lists so the result survives a JSON round trip.

    Args:
        value: A value drawn from the random module's state structure.

    Returns:
        The same value with every tuple replaced by a list.

    Raises:
        TypeError: If the structure contains a type that cannot be represented.
    """
    if value is None or type(value) in (bool, int, float, str):
        return value  # type: ignore[return-value]
    if isinstance(value, tuple | list):
        return [_to_json(item) for item in value]
    raise TypeError(f"cannot represent RNG state element of type {type(value).__name__}")


def _from_json(value: RngStateValue) -> object:
    """Recursively rebuild a random-state structure from JSON-compatible values.

    Args:
        value: A previously exported state element.

    Returns:
        The same value with every list restored to a tuple, which is the shape
        ``random.Random.setstate`` requires.
    """
    if isinstance(value, list):
        return tuple(_from_json(item) for item in value)
    return value


class DeterministicRNG:
    """A seeded wrapper around ``random.Random`` with exportable state.

    The wrapped generator is never exposed. Callers reach randomness only
    through the methods here, which keeps the set of ways a simulation can
    consume entropy small enough to reason about -- and therefore small enough
    to keep deterministic.

    Note:
        Exported state is the Mersenne Twister state produced by
        ``random.Random.getstate``. Its layout is a property of the CPython
        version in use. It is stable across the supported Python version line
        but is not guaranteed portable across major Python upgrades. A saved
        episode should therefore record the engine and Python version it was
        produced under, and a major Python upgrade should be treated as a
        migration, not a transparent change.
    """

    __slots__ = ("_random",)

    def __init__(self, seed: int) -> None:
        """Create a generator seeded to a known starting point.

        Args:
            seed: The seed for this run. The same seed always yields the same
                sequence for the same sequence of calls.
        """
        self._random = random.Random(seed)

    def random(self) -> float:
        """Return the next float in the half-open range [0.0, 1.0)."""
        return self._random.random()

    def randint(self, a: int, b: int) -> int:
        """Return a random integer in the inclusive range [a, b].

        Args:
            a: Lower bound, inclusive.
            b: Upper bound, inclusive.

        Returns:
            An integer N such that a <= N <= b.
        """
        return self._random.randint(a, b)

    def uniform(self, a: float, b: float) -> float:
        """Return a random float between the two bounds.

        Args:
            a: One bound.
            b: The other bound.

        Returns:
            A float between a and b.
        """
        return self._random.uniform(a, b)

    def choice[T](self, sequence: Sequence[T]) -> T:
        """Return one element chosen at random from a non-empty sequence.

        Args:
            sequence: The sequence to choose from.

        Returns:
            One element of the sequence.

        Raises:
            ValueError: If the sequence is empty.
        """
        if not sequence:
            raise ValueError("choice() requires a non-empty sequence")
        return self._random.choice(sequence)

    def shuffle[T](self, mutable_sequence: MutableSequence[T]) -> None:
        """Shuffle a sequence in place.

        Args:
            mutable_sequence: The sequence to reorder. Modified in place.
        """
        self._random.shuffle(mutable_sequence)

    def chance(self, probability: float) -> bool:
        """Return whether an event of the given probability occurs.

        Implemented as ``random() < probability``, which makes the boundary
        cases exact rather than special-cased: ``random()`` returns a value in
        [0.0, 1.0), so 0.0 can never be exceeded and 1.0 can never be reached.
        One value is drawn on every call including the boundary cases, so the
        consumption pattern stays uniform and call-order determinism holds.

        Args:
            probability: Probability of the event, from 0.0 to 1.0 inclusive.

        Returns:
            True if the event occurs. Always False at 0.0, always True at 1.0.

        Raises:
            ValueError: If the probability falls outside 0.0-1.0 inclusive.
        """
        if not 0.0 <= probability <= 1.0:
            raise ValueError(f"probability must be within 0.0-1.0, got {probability}")
        return self._random.random() < probability

    def get_state(self) -> dict[str, RngStateValue]:
        """Export the generator's state as a JSON-compatible structure.

        Returns:
            A dict safe to pass to ``json.dumps``, carrying a format version so
            a future change to this representation can be migrated rather than
            guessed at.
        """
        return {
            _STATE_FORMAT_KEY: _STATE_FORMAT,
            _RANDOM_STATE_KEY: _to_json(self._random.getstate()),
        }

    def set_state(self, state: dict[str, RngStateValue]) -> None:
        """Restore a previously exported state, resuming the exact sequence.

        Args:
            state: A structure previously returned by :meth:`get_state`,
                optionally after a JSON round trip.

        Raises:
            ValueError: If the structure is missing keys or carries an
                unrecognized state format.
        """
        if _STATE_FORMAT_KEY not in state or _RANDOM_STATE_KEY not in state:
            raise ValueError(f"state must contain {_STATE_FORMAT_KEY!r} and {_RANDOM_STATE_KEY!r}")
        state_format = state[_STATE_FORMAT_KEY]
        if state_format != _STATE_FORMAT:
            raise ValueError(f"unsupported RNG state format: {state_format!r}")
        self._random.setstate(_from_json(state[_RANDOM_STATE_KEY]))  # type: ignore[arg-type]
