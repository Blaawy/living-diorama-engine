"""Tests for DeterministicRNG.

Determinism is the property the whole engine rests on: an episode that cannot
be replayed cannot be debugged, diffed, or resumed. These tests pin down both
halves of that -- identical sequences from identical seeds, and exact
continuation after a state round trip.
"""

import json

import pytest

from living_diorama.simulation import DeterministicRNG


def test_same_seed_produces_identical_sequences() -> None:
    """The core determinism guarantee: same seed, same call order, same output."""
    first = DeterministicRNG(seed=12345)
    second = DeterministicRNG(seed=12345)
    assert [first.random() for _ in range(20)] == [second.random() for _ in range(20)]


def test_different_seeds_produce_different_sequences() -> None:
    """Different seeds must actually diverge, or seeding is doing nothing."""
    first = DeterministicRNG(seed=1)
    second = DeterministicRNG(seed=2)
    assert [first.random() for _ in range(20)] != [second.random() for _ in range(20)]


def test_state_round_trip_resumes_the_exact_sequence() -> None:
    """Restoring state must continue the sequence, not merely reseed it."""
    rng = DeterministicRNG(seed=99)
    rng.random()
    saved = rng.get_state()
    expected = [rng.random() for _ in range(10)]

    rng.set_state(saved)
    assert [rng.random() for _ in range(10)] == expected


def test_state_survives_a_json_round_trip() -> None:
    """Exported state must go into a save file and come back out unchanged."""
    rng = DeterministicRNG(seed=7)
    rng.random()
    saved = rng.get_state()
    expected = [rng.random() for _ in range(5)]

    restored = DeterministicRNG(seed=0)
    restored.set_state(json.loads(json.dumps(saved)))
    assert [restored.random() for _ in range(5)] == expected


def test_state_is_json_serializable() -> None:
    """get_state must produce something json.dumps accepts outright."""
    assert isinstance(json.dumps(DeterministicRNG(seed=3).get_state()), str)


def test_set_state_rejects_missing_keys() -> None:
    """A malformed state structure fails loudly rather than half-restoring."""
    with pytest.raises(ValueError):
        DeterministicRNG(seed=1).set_state({})


def test_set_state_rejects_unknown_state_format() -> None:
    """A future or corrupted state format is a migration problem, not a silent one."""
    rng = DeterministicRNG(seed=1)
    state = rng.get_state()
    state["state_format"] = 999
    with pytest.raises(ValueError):
        rng.set_state(state)


def test_randint_respects_inclusive_boundaries() -> None:
    """Randint must stay within its bounds and be able to reach both of them."""
    rng = DeterministicRNG(seed=5)
    values = [rng.randint(1, 6) for _ in range(500)]
    assert all(1 <= value <= 6 for value in values)
    assert min(values) == 1
    assert max(values) == 6


def test_randint_with_equal_bounds_returns_that_value() -> None:
    """A degenerate range is valid and returns its single value."""
    assert DeterministicRNG(seed=5).randint(4, 4) == 4


def test_uniform_produces_values_inside_the_range() -> None:
    """Uniform must stay between its bounds."""
    rng = DeterministicRNG(seed=11)
    assert all(2.0 <= rng.uniform(2.0, 3.0) <= 3.0 for _ in range(200))


def test_choice_returns_an_element_of_the_sequence() -> None:
    """Choice must return something actually present in the input."""
    rng = DeterministicRNG(seed=13)
    options = ["north", "east", "south"]
    assert all(rng.choice(options) in options for _ in range(50))


def test_choice_rejects_an_empty_sequence() -> None:
    """Choosing from nothing is a caller error and must say so clearly."""
    with pytest.raises(ValueError):
        DeterministicRNG(seed=1).choice([])


def test_shuffle_is_deterministic_for_the_same_seed() -> None:
    """Two generators at the same seed must shuffle identically."""
    first_list = [1, 2, 3, 4, 5, 6, 7, 8]
    second_list = list(first_list)
    DeterministicRNG(seed=77).shuffle(first_list)
    DeterministicRNG(seed=77).shuffle(second_list)
    assert first_list == second_list


def test_shuffle_reorders_in_place_without_losing_elements() -> None:
    """Shuffling changes order only; membership must be preserved."""
    values = [1, 2, 3, 4, 5, 6, 7, 8]
    DeterministicRNG(seed=77).shuffle(values)
    assert sorted(values) == [1, 2, 3, 4, 5, 6, 7, 8]


def test_chance_rejects_probabilities_outside_the_unit_interval() -> None:
    """A probability outside 0.0-1.0 is meaningless and is refused."""
    rng = DeterministicRNG(seed=1)
    with pytest.raises(ValueError):
        rng.chance(-0.1)
    with pytest.raises(ValueError):
        rng.chance(1.1)


def test_chance_boundaries_are_absolute() -> None:
    """0.0 never happens and 1.0 always happens, with no exceptions."""
    rng = DeterministicRNG(seed=1)
    assert not any(rng.chance(0.0) for _ in range(500))
    assert all(rng.chance(1.0) for _ in range(500))


def test_chance_is_deterministic_for_the_same_seed() -> None:
    """Probabilistic decisions must replay identically, or episodes cannot."""
    first = DeterministicRNG(seed=404)
    second = DeterministicRNG(seed=404)
    assert [first.chance(0.5) for _ in range(50)] == [second.chance(0.5) for _ in range(50)]


def test_internal_generator_is_not_publicly_exposed() -> None:
    """All randomness must flow through this wrapper's methods, not around it."""
    rng = DeterministicRNG(seed=1)
    public_names = [name for name in dir(rng) if not name.startswith("_")]
    assert "random_instance" not in public_names
    assert not hasattr(rng, "__dict__")
