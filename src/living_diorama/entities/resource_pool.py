"""Resource quantities held by a district.

``ResourcePool`` is a value object, not a top-level entity: it has no identity
of its own and is meaningful only as part of the district that owns it.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


class ResourceType(Enum):
    """The resource kinds tracked by the district-level MVP.

    Values are stable uppercase strings so that later persistence work can
    serialize them by name without an extra mapping table.
    """

    FOOD = "FOOD"
    MATERIALS = "MATERIALS"
    ENERGY = "ENERGY"


@dataclass(frozen=True, slots=True)
class ResourcePool:
    """An immutable snapshot of one district's resource stock.

    A pool is a value object: two pools holding the same quantities are the
    same pool, and nothing may change a quantity behind the owning district's
    back. Systems in later phases produce a *new* pool rather than editing an
    existing one, which keeps every resource change an explicit, auditable
    assignment.

    Immutability is enforced at two levels, deliberately:

    * ``frozen=True`` stops the ``stock`` field being rebound, and
    * ``stock`` is exposed as a :class:`types.MappingProxyType`, so item
      assignment and deletion raise :class:`TypeError` rather than silently
      succeeding.

    The proxy wraps a private dict built during construction that no caller
    holds a reference to. That detail matters: a mapping proxy is a *live view*
    of its backing dict, so proxying the caller's own dict would leave the pool
    mutable through the caller's reference. The defensive copy is what closes
    that hole, not the proxy alone.

    On construction the input mapping is normalized so every member of
    :class:`ResourceType` is present, defaulting to 0.0. A pool therefore always
    answers for every resource kind and callers never guard against missing keys.

    Note:
        A pool is not hashable: hashing a frozen dataclass hashes its fields,
        and the underlying mapping is unhashable. Pools are compared by value
        and are never used as dict keys or set members.

    Attributes:
        stock: Read-only quantity per resource kind. Always contains every
            :class:`ResourceType` member after construction.
    """

    stock: Mapping[ResourceType, float]

    def __post_init__(self) -> None:
        """Validate the input, then store a normalized read-only copy of it.

        Raises:
            ValueError: If any quantity is negative, or if the mapping contains
                a key that is not a :class:`ResourceType`.
        """
        unknown = set(self.stock) - set(ResourceType)
        if unknown:
            raise ValueError(f"stock contains unknown resource keys: {sorted(map(str, unknown))}")

        normalized: dict[ResourceType, float] = {}
        for resource in ResourceType:
            amount = float(self.stock.get(resource, 0.0))
            if amount < 0:
                raise ValueError(f"stock[{resource.value}] must be >= 0, got {amount}")
            normalized[resource] = amount

        object.__setattr__(self, "stock", MappingProxyType(normalized))

    def amount_of(self, resource: ResourceType) -> float:
        """Return the quantity held of a single resource kind.

        Args:
            resource: The resource kind to read.

        Returns:
            The quantity held, which is always defined after construction.
        """
        return self.stock[resource]

    def as_dict(self) -> dict[ResourceType, float]:
        """Return an independent, mutable copy of the stock mapping.

        Returns:
            A new dict. Mutating it cannot affect this pool, which is why this
            is the only accessor that hands out a mutable mapping.
        """
        return dict(self.stock)
