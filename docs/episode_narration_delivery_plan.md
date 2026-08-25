# Episode Narration Delivery Plan V1

**NARRATION DELIVERY ALLOCATES PRESENTATION TIME. IT DECIDES NOTHING ELSE.**

---

## 1. Why this layer exists

Phase 24 closed with every emphasized beat restated in one truthful sentence,
each marked shown or unshown — and with a deliberate hole it named itself:

> Where a beat that nobody shows should land on a future audio timeline is a
> *pacing* decision belonging to realization. Inventing one here would be this
> layer manufacturing presentation truth.

So the canonical chain's most important sentences have no time. In episode
1 → 2, the `PRIMARY` unit restating the persisted consequence — the wall that
stayed — carries `shot_id null, start_frame null, end_frame null`, and no
document anywhere in the pipeline says when a viewer would ever hear it. The
shown units are no better off than they look: a copied shot span is a *visual*
span, and when Phase 22 merges beats into one shot, several units share one
span with no say over who speaks when.

This layer closes exactly that gap. It binds every narration unit — shown and
unshown alike — to one inclusive span of playback frames on the locked Phase 17
clock, from structure alone. It is the pipeline's timing authority for
narration: the later voice, caption and assembly layers consume these slots and
never re-decide them.

## 2. Ownership

This layer owns one question: **given a finished narration plan and the
direction it reports, when may each unit be delivered?**

It owns: one delivery slot per narration unit, in the narration plan's own
order; the placement class saying how each slot was derived; and the binding
proving all of it came from two specific documents on one specific clock.

It does **not** own wording, rephrasing, visibility, emphasis, shot boundaries,
the clock, speaking rate, speech duration, voices, TTS, audio files, captions,
subtitles, music, sound effects, mixing, editing, encoding, packaging,
publishing, or any runtime language model. Those are upstream decisions already
made, or later concerns.

If Phase 25 disagrees with a valid upstream decision, it schedules it.

## 3. Inputs

Two documents, both read as canonical bytes:

| Input | Contributes |
| --- | --- |
| **Episode Narration Plan V1** | the units, their order, their visibility, and each shown unit's citing shot |
| **Shot Direction Plan V1** | the shot segments that host the slots, and the resolved Phase 17 clock |

There is deliberately **no story plan and no render export input**. The
narration plan already binds both by digest and inherits their truth; a
delivery layer that re-bound them would be duplicating a chain the cross-check
can walk, not proving anything new.

There is deliberately **no render plan and no render manifest input**, for the
reason Phase 24 already wrote down: a manifest is *execution proof*, whose
per-frame identities may legitimately differ between two renders of the same
directed episode. A delivery slot is semantic presentation time, settled before
a single pixel exists, and this plan must survive a semantically identical
re-render unchanged. Joining slots and sentences to the frames a render
actually produced is the later realization layers' work.

## 4. Output

One document, `living_diorama_episode_narration_delivery_plan`, schema
version 1.

```json
{
  "accounting": {"allocated_unshown": 1, "deliveries_total": 3, "shot_anchored": 2},
  "deliveries": [
    {
      "delivery_id": "delivery_0001",
      "end_frame": 60,
      "placement": "SHOT_ANCHORED",
      "start_frame": 25,
      "unit_id": "unit_0001"
    },
    {
      "delivery_id": "delivery_0002",
      "end_frame": 95,
      "placement": "ALLOCATED_UNSHOWN",
      "start_frame": 61,
      "unit_id": "unit_0002"
    },
    {
      "delivery_id": "delivery_0003",
      "end_frame": 144,
      "placement": "SHOT_ANCHORED",
      "start_frame": 96,
      "unit_id": "unit_0003"
    }
  ],
  "format": "living_diorama_episode_narration_delivery_plan",
  "policy": "narration_delivery_policy_v1",
  "schema_version": 1,
  "source": {
    "episode": 1,
    "mode": "transition",
    "motion_time_sha256": "bfcbfcfd…",
    "narration_plan_sha256": "b688ba5f…",
    "narration_schema_version": 1,
    "previous_episode": 0,
    "shot_plan_sha256": "1cfe0dfc…",
    "shot_schema_version": 1
  },
  "timeline": {
    "end_frame": 193,
    "end_hold_frames": 48,
    "fps": 24,
    "start_frame": 1,
    "start_hold_frames": 24,
    "transition_end": 145,
    "transition_frames": 120,
    "transition_start": 25
  }
}
```

That is the real episode 0 → 1 plan. `unit_0002` is the `PRIMARY`
`DURABLE_CONSEQUENCE` nobody could film; it now has 35 frames of presentation
time it never had before, carved without touching a single shot. A record
deliberately carries **no text, no visibility, no emphasis, no shot id and no
seconds**: wording and visibility stay authoritative in the narration plan the
record's `unit_id` names, the hosting shot is re-derivable from the sources,
and frames are the only time unit this layer speaks.

## 5. The playback domain

Shot Direction spans are inclusive and tile every frame of the timeline —
including the terminal boundary frame, which Phase 23 renders once as a
**closure witness** and never plays back. Presentation time is playback time,
so every slot lives in `[start_frame, end_frame − 1]` — canonically `[1, 192]`
— and the witness frame can never carry narration. A shot's **playback
segment** is its span clamped to that domain; the clamp is exercised by every
canonical episode, because the final hold's shot always ends on the boundary.
This is a derivation of the presentation domain, not a repair of any input.

## 6. The allocation policy

`narration_delivery_policy_v1`, closed and versioned, with **zero tunable
constants**. Everything below is derived from unit order, visibility, shot
segments and the clock — never from a sentence, an emphasis, or a guess about
speech.

**Shown units.** A shown unit is hosted by its citing shot's playback segment.
Its slot lies entirely inside that segment: narration about a beat is
scheduled only while that beat's own footage is on screen.

**Unshown runs.** Each maximal run of consecutive unshown units looks for the
**free interval** between its shown neighbours' segments — the frames of the
establishing shots, which cite no beats and so carry no anchored narration.
The run before any shown unit takes the frames before the first anchored
segment; the run after the last takes the frames after it; an episode with no
shown units at all takes the whole playback domain. A nonempty free interval
hosts the whole run.

**The fold.** When the free interval is empty — the shown neighbours' segments
are frame-adjacent — the run **folds backward** into the preceding segment,
taking its place in unit order among that segment's claimants. A run at the
very start of the document with no preceding shown unit folds forward instead,
the only remaining direction. Folding backward is not taste: it keeps every
segment's first slot starting on its own cut, so a shown unit's narration
onset always lands with its footage, and the unshown fact is spoken over the
tail of the shot the viewer just watched.

**Partition.** Every host interval with more than one claimant is partitioned
**equally** among its claimants in unit order: at least one frame each, floor
division, the remainder one frame at a time to the earliest claimants. This is
the shape of Phase 22's own largest-remainder allocation with equal weights.
Emphasis is deliberately not a weight: Phase 22 already spent emphasis on shot
duration, and spending it again here would double-count significance in a
layer forbidden to re-rank anything. The slices tile the host exactly, in
order, with no overlap.

**Order is never traded away.** Unit order is beat order is rank order is
timeline order — upstream spent three phases making those agree, and a
delivery plan never reorders presentation to find a roomier slot.

## 7. The canonical fold

Episode 0 → 1 is why the fold exists, and it is real history rather than a
fixture written to make the point. Its narration order is `LAW_CHANGE`
(shown, `[25, 95]`), `DURABLE_CONSEQUENCE` (`PRIMARY`, unshown), then
`WALL_STATE_CHANGE` (shown, `[96, 144]`) — and the two beat shots are
frame-adjacent, so the free interval between them is empty. A gap-only policy
would refuse the canonical chain's own first transition. Instead the run folds
backward: the seal shot's 71 frames are split 36/35 in unit order, the law's
narration keeps its onset on the cut at frame 25, and the consequence is
spoken over the tail of the shot that just showed the law changing — while its
unit stays `UNSHOWN`, exactly as Phase 22 decided and Phase 24 reported.

The three canonical episodes, in full:

| Ep | Unit | Placement | Slot |
| --- | --- | --- | --- |
| 0 | `unit_0001` (`NO_EMPHASIZED_BEATS`) | `ALLOCATED_UNSHOWN` | `[1, 192]` |
| 1 | `unit_0001` (`LAW_CHANGE`) | `SHOT_ANCHORED` | `[25, 60]` |
| 1 | `unit_0002` (`DURABLE_CONSEQUENCE`) | `ALLOCATED_UNSHOWN` | `[61, 95]` |
| 1 | `unit_0003` (`WALL_STATE_CHANGE`) | `SHOT_ANCHORED` | `[96, 144]` |
| 2 | `unit_0001` (`CONSEQUENCE_PERSISTED`) | `ALLOCATED_UNSHOWN` | `[1, 24]` |
| 2 | `unit_0002` (`WALL_STATE_CHANGE`) | `SHOT_ANCHORED` | `[25, 144]` |

Frames no slot covers — the opening hold in episode 1, the closing hold in
episodes 1 and 2 — simply have no narration scheduled. This layer records no
silence, no tracks and no channels; absence of a slot is the whole statement.

## 8. Slot semantics

A slot's `start_frame` is the scheduled narration **onset**. A future realized
voice asset for a unit **begins at that frame**. It may finish before
`end_frame`; it may not begin later to center itself, drift within the slot,
extend past the slot's end, or move any other unit. Unused frames at the tail
of a slot carry no narration from that unit. This is what makes Phase 25 the
timing authority: a nondeterministic synthesis fits the slot, or is refused —
it never re-decides placement.

## 9. What this layer refuses to know

**No speech feasibility.** The canonical playback duration is 8.0 seconds, and
nothing here checks whether a sentence can be spoken in its slot at any
natural rate. That is deliberate. Counting words, characters, syllables or
punctuation to predict duration would make free prose control-flow authority
over a timing artifact — the exact thing the story layer's "prose may be
carried, never branched on" rule exists to prevent — and any threshold would
smuggle in a speaking-rate opinion this layer does not own. The slots are the
structural maximum the locked episode offers; whether a synthesized voice fits
them is the later voice layer's **measured** question, answered against real
audio and refused when it fails. The canonical windows are honestly tight — 35
frames for a nineteen-word sentence in episode 1 — and no part of this layer
pretends otherwise, silently repairs it, or extends the episode to make room.

**No prose at all.** This package never reads a unit's `text` field — not
carried, not counted, not compared. The boundary suite proves it structurally,
and a planner test proves it behaviourally: change every sentence in a
narration plan and the derived slots do not move a frame. (The complete
delivery document still changes, because `narration_plan_sha256` binds the
changed input — window invariance is not document identity.)

**No rate vocabulary.** No field, constant or identifier in this layer speaks
in seconds, milliseconds, timestamps, words per minute or phonemes. Frames on
the pinned clock are the only time unit; seconds are derivable by any consumer
from the pinned `fps`, and nothing else is authoritative.

## 10. Timing provenance

Phase 17 owns the clock. Phase 22's shot plan restates it and binds the exact
Motion & Time bytes it was cut against. This plan copies that timeline block
**key for key** and pins `motion_time_sha256` beside it, because a resolved
clock is pinned beside the digest that produces it — the same rule the render
layers follow. The schema proves the block closes on its own arithmetic; the
cross-check proves it equals the shot plan's, key for key, and that the pinned
digest is the canonical locked clock. An invented but self-consistent clock
dies twice.

## 11. Accounting

Fail-closed, and provable from the document alone:

- exactly one delivery per narration unit, at the unit's own position
- `delivery_0001` schedules `unit_0001`, and so on: positional identifiers
  make a reorder, an omission and a duplicate all unrepresentable
- slots appear in order and never overlap — one narrator, one sentence at a
  time
- `shot_anchored + allocated_unshown == deliveries_total == len(deliveries)`
- the accounting block is *measured* from the records present, never asserted
  beside them; the cross-check further requires it to equal the narration
  plan's own `beats_total` / `units_shown` / `units_unshown`

## 12. Determinism

Same two documents, same bytes. Reads and writes go through the repository's
canonical codec, which already refuses `NaN`, infinities, overflowing
literals, duplicate object keys and non-round-tripping types, and emits sorted
keys, compact separators and exactly one trailing newline.

Identifiers are positional. Ordering is the narration plan's. The policy is a
compile-time rule set with no constants to tune. No clock, no randomness, no
uuid, no environment, no filesystem outside the CLI, no network, no model call
— enforced structurally by the boundary guard and asserted behaviourally
across `PYTHONHASHSEED` 0, 1, 42 and 123456 in subprocesses.

## 13. Source binding

| Document | Bound as |
| --- | --- |
| narration plan | `narration_plan_sha256` over its canonical bytes |
| shot plan | `shot_plan_sha256` over its canonical bytes |
| Motion & Time source | `motion_time_sha256`, copied from the shot plan and pinned canonical |

Schema validity and relationship validity are separate, and kept in separate
modules. The schema proves everything the plan can prove about itself. The
cross-check proves the plan's claims are true of its sources: that the digests
name the documents offered, that the narration plan itself reports visibility
from exactly this shot plan, that mode, episode, previous episode and schema
versions agree everywhere they are stated, that the restated clock is the shot
plan's own and canonical, that every slot schedules its positional unit under
the placement its visibility demands, that every anchored slot lies inside its
own beat's shot segment, and that the accounting matches the narration plan's.

Then the seal: the plan is re-derived from the two sources and must equal it
byte for byte. **Refuse, never repair.** Nothing here sorts an unsorted list,
fills a missing field, or trims a slot.

## 14. Boundaries, enforced structurally

`tests/narration_delivery/test_phase25_boundary.py` proves, by parsing the
sources rather than by reading them:

- the layer imports only Phase 24's contracts, Phase 22's contracts, and the
  shared codec and validation vocabulary
- it never imports `living_diorama.render_execution`, `living_diorama.memory`,
  `living_diorama.story`, `living_diorama.render`, Blender, the network, or
  any source of nondeterminism — the narration plan is its window onto the
  story, and a second reading would be a second authority
- no pure module touches the filesystem; only the CLI reads or writes
- no module defines a name belonging to captions, audio, TTS, encoding,
  packaging, publishing, camera re-direction, a runtime model, a speaking
  rate, or any non-frame unit of time
- no module reads a narration unit's `text` field, by subscript or by `get`
- every guard is exercised against a deliberately bad synthetic file, because
  a guard nobody has seen fail is a guard nobody has tested

## 15. Command

```
python -m living_diorama.cli.build_narration_delivery_plan \
    --narration episode_narration_plan_v1.json \
    --shots shot_direction_plan_v1.json \
    --output episode_narration_delivery_plan_v1.json
```

Inputs must be canonical bytes. The output is never overwritten. The plan is
cross-checked against both sources before the file is written, so a delivery
plan can never exist without its bindings having been proven. Exit 0 on
success, 1 on refusal, with a message rather than a traceback.

## 16. Known limitations

- **One episode.** A plan schedules one baseline or one transition.
  Multi-episode pacing is a different layer's problem, as it is for every
  layer upstream.
- **The canonical slots are tight for natural speech.** See §9: this layer
  emits the structural maximum and defers fit to the voice layer's measured
  validation. Making the words fit — by reviewed rephrasing under the Phase 24
  §13 contract, or by a reviewed presentation-time contract upstream — is
  future work that must not happen silently here.
- **An unshown run trapped inside one merged shot's claimants folds with
  them.** When unshown units sit between two shown units of the *same* shot,
  everyone partitions that one segment together. That is the policy's uniform
  answer, and it has occurred in no canonical episode.
- **Equal partition only.** V1 weighs claimants equally within a host. A
  future policy that weighed them differently would be a reviewed schema
  version, never a quiet edit.
- **Sentence-level slots.** One slot per unit; nothing here times words,
  syllables or pauses. Word-level timing, if it is ever wanted, is downstream
  of synthesis and never authoritative.
