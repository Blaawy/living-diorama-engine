# The Episode Caption Plan (V1)

> Phase 32. Deterministic legibility over a finished realization and a
> finished presentation. **No audio, no measurement, no rewording, no file
> format.**

## 1. Why this layer exists

Phase 26 closed the wording question and named this layer directly: "A
future presentation plan joins these sentences to windows on its own
clock... nothing downstream may turn an unshown beat into something the
viewer was shown." Phase 30 closed the placement question and, in the same
breath, named this layer as a *sibling*, not a consumer: "Caption
projection's data dependency is the realization plan's own sentences, not
this plan's placements; it remains a sibling layer, not a consumer of this
one." This layer is that sibling.

## 2. Ownership

**THE CAPTION PLAN MAKES LOCKED WORDING LEGIBLE ON THE PRESENTATION CLOCK.
IT REWORDS NOTHING.**

It owns: the caption cue; `caption_policy_v1` -- a cue is legible for
exactly its unit's presentation window; the verbatim carriage of the locked
realized sentence; cue order and identity; and the accounting of captioned
versus uncaptioned presentation frames.

It does **not** own wording, window geometry, the semantic clock, holds,
speech, measured duration, placement on the audio sample clock, audio
bytes, line wrapping, font, styling, position, SRT, VTT, WebVTT,
timestamps, media assembly or encode.

**It consumes nothing from Phase 29, Phase 30 or Phase 31.** Neither
package imports the other, and both boundary guards prove it -- the two
new phases are parallel siblings, not a chain.

## 3. Inputs

Two documents are bound: the Episode Language Realization Plan and the
Episode Presentation Plan. Five more are verification-only, arguments to
the reused Phase 27 gate: the Episode Narration Delivery Plan, the Episode
Narration Plan, the Shot Direction Plan, the Episode Story Plan and the
CURRENT Render Export.

## 4. The caption policy

`caption_policy_v1`: under V1, a cue is legible for exactly its unit's
presentation window, copied whole, never re-derived from a slot, a
`text_source` floor or a hold. Caption timing derives from the Phase 27
window and **never** from measured speech -- letting a caption's span
depend on a synthesized waveform's duration would make measured speech a
presentation authority, the exact inversion every layer from Phase 25
onward exists to prevent.

No seconds. No milliseconds. No sample positions. No words-per-minute. No
forced alignment. No automatic speech recognition. No heuristic timing of
any kind.

## 5. The carried sentence

`caption_text == realized_text`, as exact Unicode string-value equality.
The planner performs exactly one prose operation: one keyed read of
`realized_text`, then a direct assignment to `caption_text`. No
normalization, no case change, no punctuation change, no whitespace
change, no splitting, no wrapping, no styling.

"Prose may be carried, never branched on" means no derived behaviour may
depend on the lexical or semantic content of the prose. It does not
prohibit the one identity comparison the cross-check performs -- an exact
equality check whose only purpose is proving a downstream restatement
equals its bound upstream authority, the same shape every locked
cross-check already uses to compare a restated digest or integer against
its source.

There is deliberately no `MAX_CAPTION_TEXT_BYTES`: Phase 26 owns realized
wording validity and defines no downstream byte-length restriction, and a
rail here would let this layer reject a sentence Phase 26 itself considers
valid. `MAX_CAPTION_FRAME` remains, as a frame plausibility rail only,
never timing authority.

## 6. Output

One document, `living_diorama_episode_caption_plan`, schema version 1,
policy `caption_policy_v1`. Top level: `format`, `schema_version`,
`policy`, `source` (seven keys, byte-for-byte Phase 28's own), `clock`
(`fps`, `presentation_frames_total`), `captions` (one cue record per unit:
`caption_id`, `unit_id`, `realization_id`, `window_id`,
`presentation_start_frame`, `presentation_end_frame`, `caption_text`), and
`accounting` (`captions_total`, `caption_frames_total`,
`uncaptioned_frames_total` -- the structural mirror of Phase 30's own
three, `uncaptioned_frames_total` never a record of its own, only the
complement of the frames that are captioned).

One cue per narration unit, positional. Splitting one realization into
multiple display cues is not V1's mechanism: doing so would require
deciding *where* to split, which requires reading the sentence's content --
exactly what "carried, never branched on" forbids.

### The canonical geometry

| Ep | Cues | `caption_frames_total` | `uncaptioned_frames_total` |
| --- | --- | --- | --- |
| 0 | 1 -- `[1, 192]` | 192 | 0 |
| 1 | 3 -- `[25,168]`, `[169,528]`, `[529,672]` | 648 | 72 |
| 2 | 2 -- `[1,360]`, `[361,504]` | 504 | 48 |

## 7. Mandatory upstream verification

Before any window or realization becomes authoritative, this layer's
cross-check reuses, in full and unweakened, the locked Phase 27 gate --
`validate_episode_presentation_plan_against_sources` -- which itself
reruns the locked Phase 25 and Phase 26 gates. Neither is reimplemented.

## 8. The seal

`build_episode_caption_plan_bytes(realization_plan, presentation_plan)`
must equal the offered document's canonical bytes exactly. The contract is
a deterministic single-output function of its two bound sources, so the
one valid plan is the plan the planner derives.

## 9. Boundaries, enforced structurally

The layer imports only the Phase 26 and Phase 27 contracts and the reused
Phase 27 gate, plus the shared codec and validation vocabulary --
deliberately no `living_diorama.voice`, `living_diorama.voice_execution`,
`living_diorama.audio_track` or `living_diorama.audio_composition`. No
pure module touches the filesystem; only the CLI reads or writes. No
module defines a name belonging to audio, waveform, PCM, samples,
assembly, encoding, publishing, SRT, VTT, WebVTT, timecode, timestamp,
seconds or duration. `realized_text` and `caption_text` are each read in
exactly two scoped functions; the one identity comparison lives in exactly
one function, counted by AST.

## 10. Command

```
python -m living_diorama.cli.build_caption_plan \
    --realization episode_language_realization_plan_v1.json \
    --presentation episode_presentation_plan_v1.json \
    --delivery episode_narration_delivery_plan_v1.json \
    --narration episode_narration_plan_v1.json \
    --shots shot_direction_plan_v1.json \
    --story episode_story_plan_v1.json \
    --export render_export_ep1.json \
    --output episode_caption_plan_v1.json
```

All seven inputs must be canonical bytes. The output is never overwritten.
The gate and the full cross-check run before the file is written. Exit 0
on success, 1 on refusal, with a message rather than a traceback.

## 11. Known limitations

- **One episode.** As every layer upstream.
- **No caption serialization.** This plan is never SRT, VTT or WebVTT, and
  never emits a timestamp -- a future serialization layer, which alone
  requires a target file format, does that.
- **No line wrapping, no styling.** A future layer owning the viewer's
  actual display surface performs that.
- **Uniform per-unit span.** V1 sizes a cue from its window alone; a future
  policy splitting one realization into multiple cues would be a reviewed
  schema version, never a quiet edit.
