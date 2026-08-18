# Phase 20 — State Response

## Purpose

Phase 19 made the city physically alive. Phase 20 makes the world's authoritative
condition **visibly legible**, so that a viewer looking at the persistent city can
perceive that something happened here — and that the world remembers it.

The engine has always known that district B was starving. Until this phase,
nothing in any frame said so.

## The contract

```
AUTHORITATIVE SIMULATION STATE
        |  read only
        v
STATE RESPONSE PLAN            (pure, deterministic, source-traceable)
        |
        +--------------------> PHASE 20 STATIC APPLICATION
        |
        v
BEFORE PLAN + AFTER PLAN
        |
        v
STATE RESPONSE MOTION PLAN     (borrows the Phase 17 timeline as a clock only)
        |
        v
PHASE 20 BLENDER APPLIER
        |
        v
VISIBLE WORLD RESPONSE
```

Never the other way. Presentation may **represent** authoritative state; it may
never create it, modify it, or feed it back. Phase 20 is a consumer of Render
Export V1 and adds no field to any entity, save, or schema.

## Semantic boundary

Phase 20 does **not** create citizen identity, jobs, homes, households,
schedules, destinations, journeys, traffic demand, AI drivers, or behaviour
trees. A district's air is that district's aggregate condition as the simulation
recorded it. A record stone is one durable fact the engine itself decided to
remember. Neither describes a person.

The engine deliberately refuses to store the mean of fear and trust, because
"a stored average would be a third thing that could fall out of step with them".
Phase 20 honours that same refusal one storey down: **every channel maps exactly
one authoritative field**, and carries the dotted path and raw reading it came
from. There is no composite condition index, because the simulation never
computed one.

## Signal eligibility

Eight concepts were reserved for this phase by the Phase 19 boundary test. A
reserved concept is not a signal, and the audit that opened this phase found that
most of them are not fields at all.

| Concept | Authoritative source | Verdict |
|---|---|---|
| `scarcity` | `District.scarcity`, unit interval, written by `ScarcitySystem` | **Implemented.** The only exogenous signal of the four district scalars, the largest mover in the canonical chain, and read by no existing visual layer. |
| memory facts | `memory.facts[].fact_type` / `fact_id` | **Implemented.** Structured identifiers the engine assigns. |
| `fear` | `District.fear` | Eligible, unused in V1. Correlates +0.994 with institutional pressure; its only distinct content is lag. |
| `institutional_pressure` | `District.institutional_pressure` | Eligible, unused in V1. Also collinear. Note its true meaning: authorities **under strain**, not authority being exerted. It must never be drawn as police, checkpoints, or crackdown. |
| `trust` | `District.trust` | **Dropped.** Converges to exactly `1 - fear`. |
| `social_stability` | none — computed on demand, deliberately not stored | **Refused as a field.** Legal only as a mirrored derivation, which V1 does not need. |
| `resource_shortage` | none under that name | **Refused as a duplicate** of `scarcity` — `shortfall_ratio` *is* resource shortage, and it is stored as `scarcity`. |
| `migration_pressure` | none under that name | **Refused as a duplicate.** Verified numerically identical to `scarcity`: both systems receive the same consumption allocation and call the same `shortfall_ratio`. |

Mapping all four district scalars would have shown one underlying variable four
times. Every pair of them correlates above 0.94 across the canonical episodes.

## Channels

### `district_air` — condition

Each district carries a volume of air whose scatter density is driven by that
district's own `scarcity`. The response is linear and total: the field's whole
domain maps to the declared range, because a threshold or a band would be a
judgement the simulation never made.

The stratum is deliberately **near-achromatic** and its tint is fixed, never
signal-driven; the spec refuses a tint whose channel spread exceeds 0.18. A
hue-coded district is a heatmap, and a heatmap is not this project. Only the
density moves, so a viewer never has to decide which of two variables changed.

It compounds with the locked lit-window mapping rather than competing with it:
haze sits between the camera and the district while lit windows sit on the
surface, so a hazy district's windows bloom — which reads as *seen through
smoke*, not as *brighter*.

Phase 20 builds its own `LD_SR_MAT__air_<district>` materials. It could not use
the shared `LD_MAT__` family even if it wanted to: those materials are keyed by
district **character** and reused by the production city, so one of them can
never carry one district's truth.

### `memory_record` — memory

The Golden Seal plaza carries one cut stone per durable memory fact, on a
deterministic arc, in the order the engine remembered them. Slots are stable, so
a fact keeps its stone across episodes.

Stones are keyed off `fact_type` and the fact's identity only. The `summary`
field is prose and is never parsed: a layer that read it would be authoring
meaning rather than reading it. An unrecognised fact type still gets a stone —
the mapping degrades gracefully rather than assuming a closed set.

This channel exists because the audit found the Seal expresses only the law's
*instantaneous* boolean. In the canonical chain, episode 0 (never suspended) and
episode 2 (suspended and restored) drive the Seal to the identical emission, and
the transition between them emits no law directive at all. The world's memory of
what happened was invisible in any single frame.

## Timeline ownership

Phase 17 owns cinematic time: 24 fps, frames 1–193, eight seconds, frame 1 equal
to frame 193. Phase 20 **invents no frames**. Its config declares normalized
windows only, and its pure modules take the resolved Phase 17 timeline as a
parameter — the pattern Phase 19 established — so only the gate ever reads Phase
17's config. The half-up rounding is deliberately identical, or the two layers
would place the same normalized position on adjacent frames.

`motion_time_v1.json`, `SUPPORTED_CHANNELS`, and every Phase 17 module are
untouched. Phase 20 declares its own channels in its own registry.

## Static endpoints, and why Phase 20 owns them

Phase 17 could not animate fear because Phase 15 had no static expression of it,
and a channel with no static expression cannot have provable endpoints. Phase 20
solves this the only honest way: it owns **both** endpoints.

- frame 1 must equal the ordinary static application of the before-export;
- frame 193 must equal the ordinary static application of the after-export.

Both endpoints are measured from real static applications before the animated
scene is built, so neither is inferred from the plan under test. State is read
back from the **F-curves**, not from the live property, which makes the
comparison exact and independent of the frame the scene happens to sit on.

Densities are compared with a magnitude-scaled tolerance, because a value planned
in double precision and stored in a 32-bit socket returns a few ulps away.
Visible-object sets are compared exactly: an object hidden on a frame is absent
from that frame's list, which is what makes it comparable with a static
application that never built it.

## Determinism

Plans are canonical JSON — sorted keys, compact separators, UTF-8, one trailing
newline, `allow_nan=False` — and hashed with SHA-256 over those exact bytes.
Inputs are indexed by identity and duplicates refused, so a shuffled export array
is literally the same world. Every published list carries an explicit total
order. Floats are rounded **before** they are used in any decision, never after:
a value proven correct at full precision and then published rounded is a value
nobody checked.

No builtin `sum()` over floats appears anywhere in the plan path. CPython 3.12
changed float summation, which once made a plan hash differ between the host
interpreter and Blender's bundled one — and a hash that depends on which
interpreter ran is not determinism.

## Refusals

The Render Export envelope validator is deliberately shallow: it accepts `NaN`,
values outside their declared domain, duplicate district identifiers and
unsorted arrays, because the nested documents are governed by the serializers
that produced them. A file read off disk carries none of that guarantee, so this
phase re-validates every district field it reads.

Phase 20 refuses, never repairs: an unknown or duplicated channel, a reversed
window, a non-finite bound, a source no authoritative field backs, a district
document with a missing or unexpected key, a reading outside its own domain, a
transition between two different district sets, a directive whose ends are equal,
and a memory fact that vanished between two episodes — because durable memory
only grows, and a world that forgot is not two consecutive states of one world.

`scarcity` is **read, never recomputed**. Episode 0 of the canonical chain is
hand-seeded, and a layer that recomputed the field from the same world would
disagree with the engine on the frame that opens the series.

## What Phase 20 deliberately does not do

- It does not modify Phase 19 mobility. The one additive modulation the audit
  found feasible — per-district downward scaling of `gait.arm_swing` — is
  deferred, and vehicles cannot participate at all without inventing a
  circuit-to-district association Phase 19 declined to make.
- It does not reopen the frozen human geometry.
- It does not add a second representation of the movement law; the Golden Seal
  already carries that boolean in two locked layers.
- It does not visualise `isolation_state`, which never leaves `OPEN` in the
  canonical world and therefore could demonstrate nothing.
- It does not visualise population, which is byte-identical across all three
  canonical episodes and is already read by two locked layers.

## Known limitations

- The record stones read at the Seal detail camera and are not legible at the
  world hero cameras. They are a detail-band register deliberately paired with a
  hero-band one.
- The air channel's ability to demonstrate *change* is bounded by the canonical
  world: between episodes 1 and 2 no district's scarcity moves, so that leg
  produces no air directive at all. That is the honest result — and it is the
  point. The law returns and the damage does not lift.
- Render cost is the open risk. Four additional scatter volumes with ground
  cameras inside them must be measured against the existing frame budget before
  the channel is accepted.
