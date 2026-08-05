"""Tests for the BaseSystem contract."""

import pytest
from living_diorama.events import EventBus
from living_diorama.simulation import DeterministicRNG, World
from living_diorama.systems import BaseSystem


class _ConcreteSystem(BaseSystem):
    """A minimal concrete system used to prove the contract is satisfiable."""

    def __init__(self) -> None:
        """Create a system that has not yet run."""
        self.ran = False

    def update(self, world: World, bus: EventBus) -> None:
        """Record that the system ran."""
        self.ran = True


class _IncompleteSystem(BaseSystem):
    """A subclass that does not implement update, which must stay abstract."""


def test_base_system_cannot_be_instantiated_directly() -> None:
    """BaseSystem is a contract, not a usable system."""
    with pytest.raises(TypeError):
        BaseSystem()  # type: ignore[abstract]


def test_subclass_without_update_cannot_be_instantiated() -> None:
    """update is abstract, so a subclass must implement it to be constructible."""
    with pytest.raises(TypeError):
        _IncompleteSystem()  # type: ignore[abstract]


def test_concrete_system_implements_the_contract() -> None:
    """A system implementing update is constructible and callable by the loop."""
    system = _ConcreteSystem()
    system.update(World(rng=DeterministicRNG(1)), EventBus())
    assert system.ran


def test_base_system_declares_update_as_abstract() -> None:
    """The abstract method set is exactly the contract, with nothing extra."""
    assert BaseSystem.__abstractmethods__ == frozenset({"update"})


def test_base_system_holds_no_state_of_its_own() -> None:
    """The base class is stateless; any state is a subclass's deliberate choice."""
    assert BaseSystem.__slots__ == ()
