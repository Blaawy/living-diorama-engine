"""Tests that the events and simulation packages expose their intended public APIs."""

import living_diorama.events as events
import living_diorama.simulation as simulation

EXPECTED_EVENT_EXPORTS = {
    "Event",
    "EventBus",
    "EventHandler",
    "EventLog",
    "EventType",
    "JsonValue",
    "SubscriptionToken",
}


def test_events_all_matches_the_intended_public_api() -> None:
    """__all__ is the deliberate contract, not an accident of import order."""
    assert set(events.__all__) == EXPECTED_EVENT_EXPORTS


def test_every_exported_event_name_is_importable() -> None:
    """Everything promised by __all__ must actually resolve on the package."""
    for name in events.__all__:
        assert hasattr(events, name), f"{name} is exported but missing"


def test_simulation_exports_the_rng() -> None:
    """DeterministicRNG is part of the simulation package's public API.

    Membership rather than an exact set: the simulation package grows each
    phase, and the authoritative exact-set assertion for its ``__all__`` lives
    with the simulation layer's own boundary tests.
    """
    assert "DeterministicRNG" in simulation.__all__
    assert hasattr(simulation, "DeterministicRNG")
