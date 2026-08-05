"""Law: a single world rule, and the record of how it was last changed."""

from dataclasses import dataclass

from living_diorama.entities.base_entity import BaseEntity, Tick, require_non_negative

type LawValue = str | int | float | bool | None
"""The value a law may hold.

Deliberately narrowed to JSON-compatible scalars rather than ``Any``. The MVP's
laws are switches and thresholds -- active/inactive, a rate, a limit -- so
scalars cover every case the district-level slice needs, while keeping
serialization total and equality well-defined. Widening this alias to admit
nested containers would be a schema change and should be treated as one.
"""


@dataclass(slots=True)
class Law(BaseEntity):
    """One world rule, together with the provenance of its last change.

    A law is inert data. It records what it is now, what it was before, and
    when it changed -- but it never changes itself. RuleSystem owns all law
    mutation, and by architectural invariant RuleSystem may mutate law state
    *only*, which is what makes a restored law incapable of erasing a permanent
    wall.

    Attributes:
        name: Human-readable rule name. Stored stripped, never blank.
        active: Whether the law is currently in force.
        previous_value: The value held before the most recent change.
        current_value: The value in force now.
        changed_episode: Episode number in which this law last changed.
        restored_tick: Tick at which the law was restored to its previous
            value, or ``None`` if it has not been restored.
    """

    name: str
    active: bool
    previous_value: LawValue
    current_value: LawValue
    changed_episode: int
    restored_tick: Tick | None

    def __post_init__(self) -> None:
        """Validate the law's stored state.

        Raises:
            ValueError: If ``name`` is blank, if ``changed_episode`` is
                negative, or if ``restored_tick`` is present and negative.
        """
        BaseEntity.__post_init__(self)
        stripped_name = self.name.strip()
        if not stripped_name:
            raise ValueError("name must be a non-empty string")
        self.name = stripped_name
        require_non_negative(self.changed_episode, "changed_episode")
        if self.restored_tick is not None:
            require_non_negative(self.restored_tick, "restored_tick")
