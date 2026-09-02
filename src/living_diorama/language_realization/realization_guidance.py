"""Viewer guidance lines for the V2 narration register.

A V2 language realization plan carries, beside its factual realization
records, a short list of spoken directions that point the viewer at what to
look at. Each direction is one of a small closed pool of reviewed sentences,
each carrying a grounding tag that says which world entity type the sentence
presupposes: none at all, a road (an infrastructure route), or a wall.

Grounding is checked against the real world export before a line may be
spoken. A line whose presupposed entity type is absent from the export --
zero walls or zero infrastructure routes -- is refused by
:func:`validate_guidance_grounding` and filtered out by
:func:`select_viewer_guidance`. Selection is a pure filter that preserves the
pool's fixed order; there is no sorting, no shuffling and no randomness, so
the same world export always selects the same lines. The ``seed_input``
argument exists for signature stability only and is not read, because there is
no randomness to seed.

No prose branch is taken anywhere in this module: sentences are selected,
never inspected, and no string is ever lowercased, split or stripped. No
guidance line names a district: the V2 register points the viewer with plain
visual words ("the two places", "over there"), never with a district
identifier.
"""

from typing import Final, cast

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
"""The JSON value shape this contract works in."""

VIEWER_GUIDANCE_GROUNDING_NONE: Final = "none"
VIEWER_GUIDANCE_GROUNDING_ROAD: Final = "road"
VIEWER_GUIDANCE_GROUNDING_WALL: Final = "wall"
"""The three reviewed grounding tags a guidance entry may carry."""

VIEWER_GUIDANCE_POOL: Final[tuple[dict[str, str], ...]] = (
    {
        "guidance_text": "Okay, here we go.",
        "grounding": VIEWER_GUIDANCE_GROUNDING_NONE,
    },
    {
        "guidance_text": "Now look at the road between the two places.",
        "grounding": VIEWER_GUIDANCE_GROUNDING_ROAD,
    },
    {
        "guidance_text": "Now look at the wall between the two places.",
        "grounding": VIEWER_GUIDANCE_GROUNDING_WALL,
    },
    {
        "guidance_text": "Look at the road over there.",
        "grounding": VIEWER_GUIDANCE_GROUNDING_ROAD,
    },
)
"""The closed viewer guidance pool, in the exact order it is spoken.

The real EP1 episode selects exactly these four lines in exactly this order.
Each entry is a dict with the two reviewed fields ``guidance_text`` and
``grounding``. The fourth line is a deictic variant of the second ("over
there" instead of "between the two places"); it adds variety without ever
naming a district.
"""

_GROUNDING_WORLD_COLLECTIONS: Final[dict[str, str]] = {
    VIEWER_GUIDANCE_GROUNDING_ROAD: "infrastructure",
    VIEWER_GUIDANCE_GROUNDING_WALL: "walls",
}
"""Which world collection a grounding tag presupposes, by exact lowercase tag.

The tags are already-lowercase reviewed literals, so comparison needs no
case folding: a tag is looked up in this dict as written.
"""

__all__ = [
    "VIEWER_GUIDANCE_GROUNDING_NONE",
    "VIEWER_GUIDANCE_GROUNDING_ROAD",
    "VIEWER_GUIDANCE_GROUNDING_WALL",
    "VIEWER_GUIDANCE_POOL",
    "select_viewer_guidance",
    "validate_guidance_grounding",
]


def validate_guidance_grounding(
    entry: dict[str, str],
    world_export: dict[str, JsonValue],
) -> None:
    """Raise if the world export cannot satisfy a guidance entry's grounding.

    Args:
        entry: One guidance entry carrying ``guidance_text`` and ``grounding``.
        world_export: The validated render export whose world section is the
            ground truth for what exists.

    Raises:
        ValueError: If the grounding tag is unreviewed, or if the tag
            presupposes a road or a wall and the export's world section
            carries zero infrastructure routes or zero walls.
    """
    grounding = entry["grounding"]
    if grounding == VIEWER_GUIDANCE_GROUNDING_NONE:
        return
    collection = _GROUNDING_WORLD_COLLECTIONS.get(grounding)
    if collection is None:
        raise ValueError(
            f"guidance grounding {grounding!r} is not reviewed; a guidance line is "
            "grounded in exactly one of none, a road or a wall"
        )
    world = cast(dict[str, JsonValue], world_export["world"])
    entries = world[collection]
    if not entries:
        raise ValueError(
            f"guidance line {entry['guidance_text']!r} is grounded in {collection}, but "
            f"the world export carries none; a direction is never spoken at something "
            "the world cannot show"
        )


def select_viewer_guidance(
    world_export: dict[str, JsonValue],
    seed_input: object,
) -> list[dict[str, str]]:
    """Return the guidance pool filtered to entries the world export grounds.

    The selection is a pure filter over the fixed pool order: an entry whose
    grounding tag the export cannot satisfy is dropped, every other entry is
    returned in pool order, and each returned entry is an independent copy so
    the caller can never mutate the pool. The same world export always
    returns the same lines, for any ``seed_input``.

    Args:
        world_export: The validated render export whose world section is the
            ground truth for what exists.
        seed_input: Accepted for signature stability; unused, because this
            selection draws no randomness to seed.

    Returns:
        The grounded entries of :data:`VIEWER_GUIDANCE_POOL`, in pool order.
    """
    selected: list[dict[str, str]] = []
    for entry in VIEWER_GUIDANCE_POOL:
        try:
            validate_guidance_grounding(entry, world_export)
        except ValueError:
            continue
        selected.append(dict(entry))
    return selected
