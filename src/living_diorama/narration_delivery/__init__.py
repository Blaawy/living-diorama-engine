"""Deterministic delivery scheduling over a finished narration plan and direction.

This package owns one question: when may each narration unit be delivered, as
an inclusive span of playback frames on the locked Phase 17 clock -- including
the units whose beats no approved camera framed? It answers structurally, from
unit order, visibility, the citing shots' spans and the clock the shot plan
restates, and binds every answer back to the exact documents it read.

NARRATION DELIVERY ALLOCATES PRESENTATION TIME. IT DECIDES NOTHING ELSE.

It never writes or rewords a sentence, never re-ranks a beat, never moves a
shot boundary, never changes a unit's visibility, and never touches render
execution. Phase 17 owns the clock, Phase 22 owns what the viewer looks at,
Phase 24 owns what is said and whether it was shown; this layer says when the
saying may happen. A slot is frames on the shared clock and nothing else: no
seconds, no timestamps, no speaking rate, and no prediction of how long a
voice will need -- whether synthesized speech fits a slot is a later layer's
measured question, answered against real audio and refused when it fails, never
guessed here from the text.

One reviewed exception: the v4 delivery profile's content-proportional
partition counts the words of each unit's finalized sentence -- the sole prose
read in this phase, the Director-mandated price of content-proportional
partitioning. The v1 profile (the default) reads no wording at all, and the
word count never leaves this package: the sentence itself is not carried,
compared or emitted.

Delivery is a read-only consumer of finished documents: an Episode Narration
Plan and the Shot Direction Plan it reports visibility from. It must never
reach into live simulation, never import ``living_diorama.render_execution`` --
Phase 23's frames and manifest belong to the layers that join presentation to
executed pixels -- never read a unit's sentence under the default profile,
never mutate its inputs, and never call a model or a network service at
runtime. The allocation policy is fixed at review time, in ``delivery_spec``,
and is part of this contract's schema version.

Downstream layers (caption and subtitle realization, voice and audio
realization, editing, encoding, packaging) consume the plan this package
produces and are not part of it. A future voice realization binds this plan's
digest, begins each unit's audio at its slot's first frame, and must fit the
slot or refuse; a future caption projection joins the slots to the narration
plan's own sentences. Neither may move a slot, and nothing downstream may turn
an unshown beat into something the viewer was shown.
"""

from living_diorama.narration_delivery.delivery_cross_check import (
    validate_narration_delivery_plan_against_sources,
)
from living_diorama.narration_delivery.delivery_planner import (
    build_episode_narration_delivery_plan_bytes,
    build_episode_narration_delivery_plan_document,
    resolve_delivery_slots,
)
from living_diorama.narration_delivery.delivery_schema_v1 import (
    DELIVERY_TIMELINE_KEYS,
    SUPPORTED_NARRATION_SCHEMA_VERSION,
    SUPPORTED_SHOT_SCHEMA_VERSION,
    validate_episode_narration_delivery_plan,
)
from living_diorama.narration_delivery.delivery_spec import (
    DELIVERY_ID_FORM,
    DELIVERY_PLAN_FORMAT,
    DELIVERY_POLICY_V1,
    DELIVERY_POLICY_V4,
    DELIVERY_SCHEMA_VERSION,
    MIN_SLOT_FRAMES,
    PLACEMENT_ALLOCATED_UNSHOWN,
    PLACEMENT_CLASSES,
    PLACEMENT_SHOT_ANCHORED,
    V4_REQUIRED_FRAMES_BASE,
    V4_REQUIRED_FRAMES_PER_WORD,
    partition_equally,
    partition_proportionally,
    playback_domain,
    required_frames_for_word_count,
)

__all__ = [
    "DELIVERY_ID_FORM",
    "DELIVERY_PLAN_FORMAT",
    "DELIVERY_POLICY_V1",
    "DELIVERY_POLICY_V4",
    "DELIVERY_SCHEMA_VERSION",
    "DELIVERY_TIMELINE_KEYS",
    "MIN_SLOT_FRAMES",
    "PLACEMENT_ALLOCATED_UNSHOWN",
    "PLACEMENT_CLASSES",
    "PLACEMENT_SHOT_ANCHORED",
    "SUPPORTED_NARRATION_SCHEMA_VERSION",
    "SUPPORTED_SHOT_SCHEMA_VERSION",
    "V4_REQUIRED_FRAMES_BASE",
    "V4_REQUIRED_FRAMES_PER_WORD",
    "build_episode_narration_delivery_plan_bytes",
    "build_episode_narration_delivery_plan_document",
    "partition_equally",
    "partition_proportionally",
    "playback_domain",
    "required_frames_for_word_count",
    "resolve_delivery_slots",
    "validate_episode_narration_delivery_plan",
    "validate_narration_delivery_plan_against_sources",
]
