# The Episode Audio Track Plan (V1)

> Phase 30. Deterministic placement over an executed voice manifest. **No
> audio, no synthesis, no measurement, no prose.**

## 1. Why this layer exists

Phase 29 closed the measurement question: for a reviewed narrator request,
what does each unit's real speech actually sound like, how many samples
does it hold, and does it fit its Phase 28 capacity? This layer answers the
question that only becomes askable once that measurement exists: **where,
exactly, does each unit's speech begin on the episode's single audio-sample
clock -- and therefore, what is silence?**

## 2. Ownership

**THE AUDIO TRACK PLAN PLACES MEASURED SPEECH ON THE PRESENTATION CLOCK. IT
PRODUCES NO AUDIO.**

It owns: the onset derivation (`start_sample`) for every voice unit; the
episode's audio-sample clock total; and the accounting that states exactly
how much of the track is speech and how much is silence.

It does **not** own synthesis, measurement, wording, capacity, narrator
identity, the composed episode-length audio stream, captions, subtitles,
mixing, assembly, encoding or publishing. It never opens a WAV file: all
artifact truth is proven upstream, by the reused Phase 29 directory audit,
run once by the CLI before this layer's own gate is ever called.

## 3. Inputs

Two documents are bound, restated by digest in this plan's own `source`
block: the **Episode Voice Manifest V1** (each unit's measured
`speech_samples`) and the **Episode Presentation Plan V1** (each unit's
window, and the proven `fps`/`presentation_frames_total`).

Seven more are verification-only, arguments to the reused Phase 28 gate and
the reused Phase 29 relationship gate: the Episode Voice Plan, the Episode
Language Realization Plan, the Episode Narration Delivery Plan, the Episode
Narration Plan, the Shot Direction Plan, the Episode Story Plan, and the
CURRENT Render Export.

## 4. The onset law

Phase 25 and Phase 27 own the onset **policy** -- a unit's speech begins at
its slot's, and its window's, first frame. This layer owns the one new
**stored fact** that policy implies:

```
start_sample(window) = (window.presentation_start_frame - 1)
                        * samples_per_presentation_frame(fps)
```

`samples_per_presentation_frame` is imported from
`living_diorama.voice.voice_spec` and re-exported, never re-implemented --
one owner for the crossing law, at 24,000 Hz / 24 fps resolving to exactly
1,000 samples per frame.

## 5. Output

One document, `living_diorama_episode_audio_track_plan`, schema version 1.
Top level: `format`, `policy`, `schema_version`, `source` (seven keys),
`clock` (`audio_samples_total`, `fps`, `presentation_frames_total`,
`samples_per_presentation_frame` -- all restated and gate-verified against
the presentation plan's own proven values), `speech` (one record per unit:
`speech_id`, `voice_unit_id`, `unit_id`, `realization_id`, `window_id`,
`start_sample`, `speech_samples`), and `accounting` (`speech_total`,
`speech_samples_total`, `silence_samples_total` -- silence is never a
record of its own, only the structural complement of speech).

## 6. Placement laws

Every onset sits on a presentation-frame boundary
(`start_sample % samples_per_presentation_frame == 0`). Spans never
overlap and always follow narration order. A span never escapes its own
window's sample image: `start_sample + speech_samples <=
presentation_end_frame * samples_per_presentation_frame`. Mid-frame speech
ends are legal and expected -- measured counts are sample-quantized, not
frame-quantized.

## 7. Mandatory upstream verification

Before any window or measurement becomes authoritative, this layer's
cross-check reuses, in full and unweakened, two proofs:

1. `validate_episode_voice_plan_against_sources` -- the locked Phase 28
   gate, proving the presentation plan's windows and the whole upstream
   chain true of the actual delivery, narration, shot, story and
   render-export chain.
2. `require_manifest_matches_plan` -- the Phase 29 relationship gate,
   proving the voice manifest genuinely executes the gate-verified voice
   plan.

Neither is reimplemented. Artifact truth -- that the manifest is true of the
actual WAV bytes -- is proven separately: the CLI runs the reused Phase 29
directory audit as a precondition before this gate is ever called.

## 8. The seal

`build_episode_audio_track_plan_bytes(voice_manifest, presentation_plan)`
must equal the offered document's canonical bytes exactly. The contract is
a deterministic single-output function of its two bound sources, so the one
valid plan is the plan the planner derives.

## 9. Command

```
python -m living_diorama.cli.build_audio_track_plan \
    --voice-dir voice/episode_0000_to_0001 \
    --presentation episode_presentation_plan_v1.json \
    --realization episode_language_realization_plan_v1.json \
    --delivery episode_narration_delivery_plan_v1.json \
    --narration episode_narration_plan_v1.json \
    --shots shot_direction_plan_v1.json \
    --story episode_story_plan_v1.json \
    --export render_export_ep1.json \
    --output episode_audio_track_plan_v1.json
```

There is no flag accepting a detached, unaudited manifest file: `--voice-dir`
names a Phase 29 execution directory, and the audit is the first thing the
command does with it, before any document is parsed.

## 10. Known limitations

- **No composition.** This plan places speech; it never assembles an
  episode-length audio stream, generates silence bytes, or joins anything
  to rendered frames. A future composition layer does that, from this
  plan's own placements plus the audited Phase 29 artifacts.
- **No captions.** Caption projection's data dependency is the realization
  plan's own sentences, not this plan's placements; it remains a sibling
  layer, not a consumer of this one.
- **One episode.** As every layer upstream.
