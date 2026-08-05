"""Tests for the ResourcePool value object.

ResourcePool is the only value object in the entity layer, and its immutability
is load-bearing: districts hand pools around, and a pool that could be edited in
place would let a resource quantity change without any system having authored
that change. These tests pin that property down at the level it actually has to
hold -- the mapping itself -- not just at the level of field rebinding.
"""

from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest
from living_diorama.entities import ResourcePool, ResourceType


def test_constructs_with_all_resource_types() -> None:
    """A fully specified pool keeps every quantity it was given."""
    pool = ResourcePool(
        stock={
            ResourceType.FOOD: 10.0,
            ResourceType.MATERIALS: 5.0,
            ResourceType.ENERGY: 2.5,
        }
    )
    assert pool.amount_of(ResourceType.FOOD) == 10.0
    assert pool.amount_of(ResourceType.MATERIALS) == 5.0
    assert pool.amount_of(ResourceType.ENERGY) == 2.5


def test_normalizes_missing_resource_types_to_zero() -> None:
    """A pool always answers for every resource kind, so callers need no guards."""
    pool = ResourcePool(stock={ResourceType.FOOD: 10.0})
    assert pool.amount_of(ResourceType.MATERIALS) == 0.0
    assert pool.amount_of(ResourceType.ENERGY) == 0.0
    assert set(pool.stock) == set(ResourceType)


def test_empty_stock_normalizes_to_all_zeros() -> None:
    """An empty pool is a valid pool holding nothing, not an invalid one."""
    pool = ResourcePool(stock={})
    assert all(pool.amount_of(resource) == 0.0 for resource in ResourceType)


def test_rejects_negative_stock() -> None:
    """A district cannot hold a negative quantity of anything."""
    with pytest.raises(ValueError):
        ResourcePool(stock={ResourceType.FOOD: -1.0})


def test_rejects_unknown_resource_keys() -> None:
    """A key outside ResourceType is malformed data, caught at construction."""
    with pytest.raises(ValueError):
        ResourcePool(stock={"FOOD": 1.0})  # type: ignore[dict-item]


def test_stock_is_exposed_as_a_read_only_mapping() -> None:
    """The externally visible mapping is a proxy, not a dict handed straight out."""
    pool = ResourcePool(stock={ResourceType.FOOD: 10.0})
    assert isinstance(pool.stock, MappingProxyType)


def test_direct_item_assignment_raises_type_error() -> None:
    """The core immutability guarantee: quantities cannot be edited in place."""
    pool = ResourcePool(stock={ResourceType.FOOD: 10.0})
    with pytest.raises(TypeError):
        pool.stock[ResourceType.FOOD] = 999.0  # type: ignore[index]
    assert pool.amount_of(ResourceType.FOOD) == 10.0


def test_direct_item_deletion_raises_type_error() -> None:
    """Deletion is blocked too, so a pool cannot lose a resource kind."""
    pool = ResourcePool(stock={ResourceType.FOOD: 10.0})
    with pytest.raises(TypeError):
        del pool.stock[ResourceType.FOOD]  # type: ignore[attr-defined]
    assert set(pool.stock) == set(ResourceType)


def test_field_cannot_be_rebound() -> None:
    """The pool is frozen: it is replaced wholesale, never edited in place."""
    pool = ResourcePool(stock={ResourceType.FOOD: 10.0})
    with pytest.raises(FrozenInstanceError):
        pool.stock = {}  # type: ignore[misc]


def test_callers_original_dict_cannot_affect_the_pool() -> None:
    """A mapping proxy is a live view, so the pool must proxy its own private copy.

    If construction proxied the caller's dict instead of a defensive copy, this
    mutation would reach straight through the proxy and change the pool.
    """
    source = {ResourceType.FOOD: 10.0}
    pool = ResourcePool(stock=source)
    source[ResourceType.FOOD] = 999.0
    source[ResourceType.ENERGY] = 42.0
    assert pool.amount_of(ResourceType.FOOD) == 10.0
    assert pool.amount_of(ResourceType.ENERGY) == 0.0


def test_as_dict_returns_a_mutable_independent_copy() -> None:
    """as_dict is the sanctioned escape hatch, and it hands out a detached copy."""
    pool = ResourcePool(stock={ResourceType.FOOD: 10.0})
    snapshot = pool.as_dict()
    assert isinstance(snapshot, dict)

    snapshot[ResourceType.FOOD] = 999.0
    assert pool.amount_of(ResourceType.FOOD) == 10.0

    assert pool.as_dict() is not pool.as_dict()


def test_equality_is_value_based_across_mapping_proxies() -> None:
    """Proxy-wrapped stocks still compare by quantity, which is asserted not assumed.

    Equality now compares two mappingproxy objects rather than two dicts. That
    it still compares by content is a property of mappingproxy worth pinning
    down explicitly, since the whole value-object contract rests on it.
    """
    sparse = ResourcePool(stock={ResourceType.FOOD: 10.0})
    explicit = ResourcePool(
        stock={
            ResourceType.FOOD: 10.0,
            ResourceType.MATERIALS: 0.0,
            ResourceType.ENERGY: 0.0,
        }
    )
    assert sparse == explicit
    assert sparse.stock == explicit.stock


def test_pools_with_different_quantities_are_not_equal() -> None:
    """Value equality must still discriminate: same shape, different numbers."""
    assert ResourcePool(stock={ResourceType.FOOD: 10.0}) != ResourcePool(
        stock={ResourceType.FOOD: 11.0}
    )


def test_pool_is_unhashable() -> None:
    """Pools are compared by value and never used as keys, so hashing stays blocked.

    Hashing a frozen dataclass hashes its fields, and the underlying mapping is
    unhashable. This is deliberate rather than an oversight: no safe hash is
    implemented because nothing needs one.
    """
    pool = ResourcePool(stock={ResourceType.FOOD: 10.0})
    with pytest.raises(TypeError):
        hash(pool)
