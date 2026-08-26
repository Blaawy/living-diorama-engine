# Episode Presentation Plan V1

**PRESENTATION MAY EXTEND HOW LONG THE VIEWER SEES LOCKED SEMANTIC TRUTH. IT
DECIDES NOTHING ELSE.**

---

## 1. Why this layer exists

Phase 25 closed with a hard limit it named itself: the canonical playback
duration is 8.0 seconds, and several real narration units cannot be spoken in
their delivery slot at any natural rate — a 19-word sentence in a 35-frame
(1.46 s) window, measured against real synthesized speech, needed 9.08
seconds. Phase 25 refused to solve this, on purpose: "whether a synthesized
voice fits [a slot] is the later voice layer's measured question." Phase 26
closed the wording side of the same gap and named this layer directly: "A
future presentation plan joins these sentences to windows on its own clock."

This layer closes the timing side. It gives every narration unit a
presentation window — a span of frames on a second, longer clock — sized from
structure alone, so that a real voice has somewhere to fit before anyone
measures whether it does.

## 2. Ownership

This layer owns one question: **given a finished delivery schedule, a
narration plan and a realized wording plan, for how many presentation frames
does the viewer see each locked semantic playback frame?**

It owns: the presentation clock itself (an image of the semantic clock, at
the same fps); one static hold per delivery slot's own onset frame, sized
from the unit's story-proven wording family; and one presentation window per
narration unit, bound to the exact realization it names.

It does **not** own wording, rephrasing, visibility, emphasis, shot
boundaries, the semantic clock, world truth, story truth, speaking rate,
speech duration, voices, TTS, audio files, captions, subtitles, physical
frame repetition, music, sound effects, mixing, editing, encoding, packaging,
publishing, or any runtime language model.

## 3. Inputs

Three documents are **bound** — restated by digest in this plan's own
`source` block and consumed by its derivation:

| Input | Contributes |
| --- | --- |
| **Episode Narration Delivery Plan V1** | the slots, the restated Phase 17 clock, and unit order |
| **Episode Narration Plan V1** | each unit's `text_source` classification, which selects its window floor |
| **Episode Language Realization Plan V1** | the exact sentence identity — `realization_id` — each window names |

Three more are **verification-only** — arguments to two locked upstream
gates, never bound in this plan's own `source` block, never touched by this
plan's own derivation:

| Input | Used by |
| --- | --- |
| **Shot Direction Plan V1** | the reused Phase 25 gate, proving the delivery plan's slots true |
| **Episode Story Plan V1** | the reused Phase 26 gate, proving the narration plan's `kind` — and therefore its `text_source` — true of the actual story |
| **CURRENT Render Export V1** | the reused Phase 26 gate, proving the realization plan's sentences true of the actual events and facts |

There is deliberately **no render plan and no render manifest input**. A
presentation window is viewer-facing timing on the semantic delivery slot's
own clock, settled before a single pixel of the presentation is assembled.

## 4. Why six inputs, and why only three are bound

A narration unit's `text_source` field is proven internally consistent with
its own `kind` by the narration plan's own standalone schema — but that
schema cannot prove the `kind` itself is true of the actual story beat. Only
the locked Phase 26 source-verification gate proves that, because only it
holds the actual story plan and render export. Since this layer's capacity
policy is keyed on `text_source`, skipping that gate would let a forged
`kind`/`text_source` pair — internally consistent, individually plausible —
silently choose the wrong window floor. Symmetrically, the delivery plan's
slots are only proven true of the actual narration and shot plans by the
locked Phase 25 gate. Both gates run, in full and unweakened, before this
plan's cross-check trusts a single slot or classification.

The shot plan, story plan and render export are never bound in this plan's
`source` block for the opposite reason: this plan makes no claim about them
that those two gates do not already prove. Restating their digests here
would be a copy, not proof.

## 5. Output

One document, `living_diorama_episode_presentation_plan`, schema version 1.

```json
{
  "accounting": {"presentation_frames_total": 720, "segments_total": 7, "windows_total": 3},
  "format": "living_diorama_episode_presentation_plan",
  "policy": "presentation_policy_v1",
  "schema_version": 1,
  "segments": [
    {"dwell_frames": 1, "presentation_end_frame": 24, "presentation_start_frame": 1, "segment_id": "segment_0001", "semantic_end_frame": 24, "semantic_start_frame": 1},
    {"dwell_frames": 109, "presentation_end_frame": 133, "presentation_start_frame": 25, "segment_id": "segment_0002", "semantic_end_frame": 25, "semantic_start_frame": 25},
    {"dwell_frames": 1, "presentation_end_frame": 168, "presentation_start_frame": 134, "segment_id": "segment_0003", "semantic_end_frame": 60, "semantic_start_frame": 26},
    {"dwell_frames": 326, "presentation_end_frame": 494, "presentation_start_frame": 169, "segment_id": "segment_0004", "semantic_end_frame": 61, "semantic_start_frame": 61},
    {"dwell_frames": 1, "presentation_end_frame": 528, "presentation_start_frame": 495, "segment_id": "segment_0005", "semantic_end_frame": 95, "semantic_start_frame": 62},
    {"dwell_frames": 96, "presentation_end_frame": 624, "presentation_start_frame": 529, "segment_id": "segment_0006", "semantic_end_frame": 96, "semantic_start_frame": 96},
    {"dwell_frames": 1, "presentation_end_frame": 720, "presentation_start_frame": 625, "segment_id": "segment_0007", "semantic_end_frame": 192, "semantic_start_frame": 97}
  ],
  "source": {
    "delivery_plan_sha256": "…",
    "delivery_schema_version": 1,
    "episode": 1,
    "mode": "transition",
    "motion_time_sha256": "bfcbfcfd…",
    "narration_plan_sha256": "…",
    "narration_schema_version": 1,
    "previous_episode": 0,
    "realization_plan_sha256": "…",
    "realization_schema_version": 1
  },
  "timeline": {"end_frame": 193, "end_hold_frames": 48, "fps": 24, "start_frame": 1, "start_hold_frames": 24, "transition_end": 145, "transition_frames": 120, "transition_start": 25},
  "windows": [
    {"presentation_end_frame": 168, "presentation_start_frame": 25, "realization_id": "realization_0001", "unit_id": "unit_0001", "window_id": "window_0001"},
    {"presentation_end_frame": 528, "presentation_start_frame": 169, "realization_id": "realization_0002", "unit_id": "unit_0002", "window_id": "window_0002"},
    {"presentation_end_frame": 672, "presentation_start_frame": 529, "realization_id": "realization_0003", "unit_id": "unit_0003", "window_id": "window_0003"}
  ]
}
```

That is the real episode 0 → 1 plan. `unit_0002` — the `DURABLE_CONSEQUENCE`
that measured 9.08 seconds of real speech in a 1.46-second slot — now owns a
360-frame (15.0 s) window. A window record deliberately carries **no
semantic frames, no dwell, no shot citation and no sentence bytes**: its
semantic geometry is re-derivable from the bound delivery plan and this
plan's own segments, and its sentence identity is a `realization_id`, never
prose.

## 6. The clock model

Presentation fps **is** the pinned semantic fps — 24, inherited, never a new
field. A presentation frame is a single tick of that same clock; there is no
separate presentation-fps concept to drift from it.

A **segment** is one maximal run of consecutive semantic playback frames
shown at one uniform **dwell** — how many presentation frames each of those
semantic frames is shown for. Segments tile the playback domain `[1, 192]`
exactly: no gap, no overlap, and the terminal witness frame — 193 — is
**unrepresentable**, exactly as it is unschedulable in Phase 25's delivery
domain. Adjacent segments never share a dwell, because a run that could have
been one segment is not two.

A **hold** is dwell greater than 1, and it is placed on exactly **one**
semantic frame: a segment whose dwell exceeds 1 must span a single semantic
frame. Distributed dilation of several frames together — which would be
indistinguishable from uninterpolated slow motion of footage Phase 19 and
Phase 23 already rendered at its true rate — is not this layer's mechanism,
and the schema makes it structurally unrepresentable. The one frame that may
ever hold is a delivery slot's own `start_frame`: the scheduled narration
onset, which for a shown unit is the shot's own cut. The camera arrives, the
image holds while the sentence begins, and the footage then plays through at
exactly the rate it was rendered.

A **window** is the presentation-clock image of one narration unit's
delivery slot: `[presentation_start_of(slot.start), presentation_end_of(slot.end)]`.
Presentation duration may exceed — and, for any unit needing a hold, does
exceed — the semantic 8.0-second episode; nothing about the semantic
duration, the shot boundaries, or the rendered motion changes.

## 7. The capacity policy

`presentation_policy_v1`, closed and versioned, with exactly two tunable
constants:

| Wording family (`text_source`) | Window floor | Seconds at 24 fps |
| --- | --- | --- |
| `NARRATION_TEMPLATE` | 144 frames | 6.0 s |
| `MEMORY_FACT_SUMMARY` | 360 frames | 15.0 s |

For a delivery slot `[s, e]` of length `L = e − s + 1`:

```
window_frames = max(L, floor(text_source))
hold_frames   = window_frames − L        # placed entirely on frame s
```

Both constants are Director-reviewed pacing judgments, sanity-checked
against — never derived from — measured Kokoro voice duration: no runtime
speech measurement chooses a window here, and the voice layer downstream
still **fits or refuses** against whatever window this layer assigns.
`text_source` is a closed, two-member, story-proven classification Phase 24
already totals over every beat kind; it has never been spent on a timing
decision by any layer before this one, and emphasis is deliberately not a
weight, exactly as Phase 25 refused to weight it a second time.

## 8. The canonical geometry

| Ep | Unit | Kind family | Slot | Window | Hold @ |
| --- | --- | --- | --- | --- | --- |
| 0 | `unit_0001` | TEMPLATE | `[1, 192]` | 192 | none (already ≥ floor) |
| 1 | `unit_0001` | TEMPLATE | `[25, 60]` | 144 | 108 @ 25 |
| 1 | `unit_0002` | FACT | `[61, 95]` | 360 | 325 @ 61 |
| 1 | `unit_0003` | TEMPLATE | `[96, 144]` | 144 | 95 @ 96 |
| 2 | `unit_0001` | FACT | `[1, 24]` | 360 | 336 @ 1 |
| 2 | `unit_0002` | TEMPLATE | `[25, 144]` | 144 | 24 @ 25 |

Totals: episode 0 presents at 192 frames (8.0 s, unchanged — its one unit's
slot already meets the floor); episode 1 at 720 frames (30.0 s); episode 2 at
552 frames (23.0 s).

## 9. Mandatory upstream verification

Before any delivery slot or `text_source` classification becomes
authoritative, this layer's cross-check reuses, in full and unweakened, two
locked gates:

1. `validate_narration_delivery_plan_against_sources(delivery, narration, shots)`
   — the Phase 25 proof that the delivery plan's slots, placements and clock
   are true of the actual narration and shot plans.
2. `validate_language_realization_plan_against_sources(realization, narration, story, current_export)`
   — the Phase 26 proof that the realization plan's sentences, and the
   narration plan's `kind`/`text_source` classification, are true of the
   actual story plan and render export.

Neither gate is reimplemented. A forged-but-standalone-valid delivery plan,
or a narration unit whose `kind` was forged alongside its `text_source` to
stay internally consistent, is refused here — not because this layer
re-derives the proof, but because it delegates to the layer that owns it.

## 10. What this layer refuses to know

**No prose at all.** No module here reads a narration unit's `text`, a
realization's `realized_text`, a memory fact's `summary`, or an event's
`source_event_payload` — not carried, not counted, not compared. A window
names its sentence by `realization_id` only.

**No speech measurement.** Nothing here counts words, characters, syllables
or punctuation, and nothing here calls a voice model. The two window floors
are reviewed constants, not predictions.

**No render authority.** This plan is never bound to a render plan, a render
manifest, or a rendered pixel, and must survive a semantically identical
re-render unchanged.

## 11. Accounting

Fail-closed, and provable from the document alone: segments tile the
playback domain exactly and never include the witness frame; a dwell above 1
is always a single semantic frame; windows appear in narration order, never
overlapping; `windows_total == len(windows) == deliveries_total == units_total`;
every count is measured from the records present, never asserted beside them.

## 12. Determinism

Same three bound documents, same bytes. Reads and writes go through the
repository's canonical codec. Identifiers are positional. The policy is a
compile-time rule set with two reviewed constants. No clock, no randomness,
no uuid, no environment, no filesystem outside the CLI, no network, no model
call — enforced structurally by the boundary guard and asserted behaviourally
across `PYTHONHASHSEED` 0, 1, 42 and 123456 in subprocesses.

## 13. Source binding

| Document | Bound as |
| --- | --- |
| delivery plan | `delivery_plan_sha256` over its canonical bytes |
| narration plan | `narration_plan_sha256` over its canonical bytes |
| realization plan | `realization_plan_sha256` over its canonical bytes |
| Motion & Time source | `motion_time_sha256`, restated from the delivery plan and pinned canonical |

The shot plan, story plan and render export are bound to **nothing** in this
document; they exist only as arguments to the two gates in §9.

Schema validity and relationship validity are kept in separate modules
exactly as every locked phase keeps them. The schema proves everything the
plan can prove about itself — its restated clock's arithmetic, its segment
tiling, that no dwell above one ever spans more than one semantic frame, and
its own presentation cursor's arithmetic. The cross-check proves the plan's
claims are true of its sources: both upstream gates, the plan's own digest
bindings, that every window presents its positional unit and names its
positional realization, and — finally — the re-derivation seal: the plan is
re-derived from its three bound sources and must equal it byte for byte.
**Refuse, never repair.**

## 14. Boundaries, enforced structurally

`tests/presentation/test_phase27_boundary.py` proves, by parsing the sources
rather than by reading them:

- the layer imports only Phase 25's and Phase 26's contracts and gates, one
  pinned cinematic constant, and the shared codec and validation vocabulary
  — deliberately no `living_diorama.story`, no `living_diorama.render`, and
  no `living_diorama.render_execution`
- no module reads `text`, `realized_text`, `summary` or
  `source_event_payload`, by subscript, `.get` or `.pop` — an empty
  allow-list, with `text_source` explicitly permitted as a structured field
- no pure module touches the filesystem; only the CLI reads or writes
- no module defines a name belonging to captions, voice, audio, assembly,
  encoding, publishing, camera re-direction, a runtime model, or any
  non-frame unit of time
- the cross-check both imports and actually calls both locked upstream gates
- every guard is exercised against a deliberately bad synthetic file

## 15. Command

```
python -m living_diorama.cli.build_presentation_plan \
    --delivery episode_narration_delivery_plan_v1.json \
    --narration episode_narration_plan_v1.json \
    --shots shot_direction_plan_v1.json \
    --realization episode_language_realization_plan_v1.json \
    --story episode_story_plan_v1.json \
    --export render_export_ep2.json \
    --output episode_presentation_plan_v1.json
```

All six inputs must be canonical bytes. The output is never overwritten. Both
upstream gates and the full cross-check run before the file is written, so a
presentation plan can never exist without every one of its bindings — and
both source-verification gates — having been proven. Exit 0 on success, 1 on
refusal, with a message rather than a traceback.

## 16. Known limitations

- **One episode.** A plan presents one baseline or one transition, as every
  layer upstream does.
- **Uniform per-unit capacity.** V1 sizes a window from `text_source` alone;
  a future policy weighing anything else — emphasis, event kind, a reviewed
  per-beat table — would be a reviewed schema version, never a quiet edit.
- **Physical frame repetition is not performed here.** This plan only plans
  the hold; a future media-assembly layer, which alone requires the Render
  Manifest and actual rendered assets, executes it.
- **The two window floors are reviewed pacing judgments**, not measured
  guarantees that any given voice will fit. Whether a synthesized sentence
  fits its window is the later voice layer's measured question, answered
  against real audio and refused when it fails.
