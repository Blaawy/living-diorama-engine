# A1 Narration Wording V2

The V2 register (`wording_profile="v2"`) is the second reviewed way a locked
narration unit may be said to a human. It composes the very same structured
atoms as V1 -- the same events, facts, and world entities, proven the same way
-- in short, active, concrete sentences, and it adds a small, deterministic
set of viewer guidance lines.

## Fact and guidance split

A V2 language realization plan carries two kinds of spoken material:

- **Fact records** (`realizations`): one record per narration unit, exactly as
  in V1, each additionally bound with `category` (`"fact"`), `fact_id` (the
  memory fact it restates, or `null`) and `event_id` (the export event index
  its beat cites, or `null` for an absence). Nothing requires one record per
  sentence -- only one record per narration unit -- so a template whose value
  is two sentences ("We built {wall_label}. It never went away.") is one
  record.
- **Viewer guidance** (`viewer_guidance`): a top-level list of
  `{guidance_text, grounding}` entries selected deterministically from a
  closed four-line pool, filtered to the lines the world export can ground
  (`"none"`, or a `"road"` with infrastructure routes present, or a `"wall"`
  with a wall present), in the fixed pool order. Guidance is a V2-only field.

The real EP1 episode selects exactly the four pool lines in order; the
baseline (no walls) drops the wall line.

## Districts are never named

The V2 register never speaks a district identifier. V1 names the wall by its
boundary's endpoints ("the wall between District A and District B") through a
mechanical capitalization rule; the V2 register instead speaks the wall
deictically, because the wall event's shot shows exactly two sides:

- the wall is **"the wall between this side and the other side"** (a fixed
  reviewed label, `V2_WALL_LABEL`, which never passes through the district
  capitalization rule);
- a district subject is **"this area"**;
- guidance points with plain visual words: **"between the two places"** and
  **"over there"**.

No new geographic name is invented: the reference is visual and spatial, and
every structural proof (entity resolution, reciprocal boundary, endpoints,
ticks) runs exactly as in V1.

## The word-count law

Every V2 sentence -- fact or guidance -- is at most 12 words, and at least 70%
of an episode's sentences are between 3 and 9 words. The real EP1 V2 script is
57 words total, inside the reviewed [55, 70] band, with all eight sentences at
most 12 words and six of them (75%) between 3 and 9 words:

1. "We changed one rule." (4)
2. "We built the wall between this side and the other side." (11)
3. "It never went away." (4)
4. "The wall between this side and the other side changed." (10)
5. "Okay, here we go." (4)
6. "Now look at the road between the two places." (9)
7. "Now look at the wall between the two places." (9)
8. "Look at the road over there." (6)

## Forbidden vocabulary

The V2 register never speaks the simulation's own analytic vocabulary. The
whole-word, case-insensitive ban (`FORBIDDEN_V2_JARGON`) applies to every V2
`realized_text` and every `guidance_text`:

`tick | resource | sharing | consequence | infrastructure | behavioral |
significantly | resulting | adaptation | boundary | permanent | state
transition`

Permanence is said as "It never went away."; the boundary is said as the wall
or the road between two places; the tick is simply not spoken. Beyond that
ban, the register never speaks a district identifier at all (see above), and
no internal identifier, `snake_case` or ALL_CAPS token may leak into speech.
World data substituted into a label (such as a law's own authoritative name)
is never censored.

## Determinism

Derivation is a pure function of its inputs: no clock, no randomness, no
iteration-order dependence. Guidance selection is a filter over the fixed pool
order -- the `seed_input` argument is accepted for signature stability and is
not read. The same three documents always produce the same bytes, and the V1
register is byte-for-byte unchanged when `wording_profile` is omitted or
`"v1"`.
