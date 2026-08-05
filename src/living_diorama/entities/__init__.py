"""Pure data definitions for the district-level MVP world model.

Contains District, Boundary, Wall, Law, ResourcePool, and Infrastructure. This
package holds no behavior beyond local field validation and no I/O -- see
``living_diorama.systems`` for what changes these entities, and
``living_diorama.persistence`` for how they are saved and loaded. This is the
innermost layer of the architecture: nothing in this package may depend on any
other package in ``living_diorama``.
"""

from living_diorama.entities.base_entity import BaseEntity, EntityId, Tick
from living_diorama.entities.boundary import Boundary
from living_diorama.entities.district import District, IsolationState
from living_diorama.entities.infrastructure import Infrastructure, InfrastructureType
from living_diorama.entities.law import Law, LawValue
from living_diorama.entities.resource_pool import ResourcePool, ResourceType
from living_diorama.entities.wall import Wall

__all__ = [
    "BaseEntity",
    "Boundary",
    "District",
    "EntityId",
    "Infrastructure",
    "InfrastructureType",
    "IsolationState",
    "Law",
    "LawValue",
    "ResourcePool",
    "ResourceType",
    "Tick",
    "Wall",
]
