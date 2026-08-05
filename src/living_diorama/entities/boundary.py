"""Boundary: the edge between exactly two districts."""

from dataclasses import dataclass

from living_diorama.entities.base_entity import BaseEntity, EntityId, require_non_empty_id


@dataclass(slots=True)
class Boundary(BaseEntity):
    """The shared edge connecting exactly two distinct districts.

    A boundary is where a wall may later be built. It records which districts
    it joins and, optionally, which wall currently stands on it.

    A boundary validates only what it can see locally: that its two endpoints
    are non-empty and distinct. It deliberately does not check that the
    referenced districts exist -- referential integrity across entities is the
    World aggregate's responsibility in a later phase, and checking it here
    would require the entity layer to know about a registry it must not import.

    Attributes:
        district_a_id: Identifier of the first district.
        district_b_id: Identifier of the second district.
        wall_id: Identifier of the wall standing on this boundary, or ``None``
            if no wall stands here.
    """

    district_a_id: EntityId
    district_b_id: EntityId
    wall_id: EntityId | None = None

    def __post_init__(self) -> None:
        """Validate and normalize the boundary's endpoints.

        Raises:
            ValueError: If either endpoint is blank, if both endpoints name the
                same district, or if ``wall_id`` is present but blank.
        """
        BaseEntity.__post_init__(self)
        self.district_a_id = require_non_empty_id(self.district_a_id, "district_a_id")
        self.district_b_id = require_non_empty_id(self.district_b_id, "district_b_id")
        if self.district_a_id == self.district_b_id:
            raise ValueError("district_a_id and district_b_id must be different districts")
        if self.wall_id is not None:
            self.wall_id = require_non_empty_id(self.wall_id, "wall_id")
