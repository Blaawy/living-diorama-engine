# The Episode Voice Execution (V1)

> Phase 29. Deterministic documents; audited real speech. **Synthesizes
> once, measures from the artifact it produced, and refuses whatever
> overflows.**

## 1. Why this layer exists

Phase 28 closed the planning side of the voice question it opened: which
reviewed narrator request speaks each locked realized sentence, and how
many audio samples its Phase 27 window has room for. It refused, on
purpose, to synthesize anything -- "a later Voice Execution phase
synthesizes exactly once under this plan's pinned request, owns the
resulting audio, recomputes its own sample count from the bytes it actually
produced -- never trusting a count some document merely asserts -- and
proves that count fits this plan's `capacity_samples` or refuses." This
layer is that later phase.

## 2. Ownership

**VOICE EXECUTION SPEAKS A PLANNED EPISODE. IT PLANS NOTHING.**

It owns: the one authoritative synthesis call per voice unit; the produced
speech artifact, in one reviewed canonical format; the recomputed sample
count, recomputed from that artifact's own bytes; the FIT verdict, per unit
and for the whole episode; the manifest that proves what was actually
produced; and the independent audit that re-reads the directory and decides
whether the manifest told the truth.

It does **not** own wording, capacity, narrator identity, presentation
timing, placement on any clock, silence, captions, subtitles, audio
composition, mixing, assembly, encoding, or publishing.

## 3. Inputs

Two documents are consumed directly by execution: the **Episode Voice Plan
V1** (which unit speaks which realization, under which pinned request, at
what capacity) and the **Episode Language Realization Plan V1** (the exact
sentence each unit speaks -- the only place in this phase `realized_text`
is ever read, inside the executor's `unit_texts` function, and nowhere
else).

Five more documents are verification-only, supplied so the locked Phase 28
source-verification gate --
`validate_episode_voice_plan_against_sources` -- can prove the voice plan
and everything upstream of it true before a single sample is synthesized:
the Episode Presentation Plan, the Episode Narration Delivery Plan, the
Episode Narration Plan, the Shot Direction Plan, the Episode Story Plan, and
the CURRENT Render Export.

## 4. The artifact

One canonical WAV per voice unit: **PCM16 little-endian, mono, the pinned
request's own sample rate, exactly forty-four header bytes, no ancillary
chunk, no trailing byte.** The serialization is total, so `sha256` over the
whole file is the one authoritative artifact digest -- there is deliberately
no second stream digest.

The PCM law: `clamp(round_half_even(x * 32767.0), -32768, 32767)`, applied
to exact built-in Python `float` samples. The executor's tensor bridge
(`tensor_to_float_list`) validates a synthesized `torch.float32` tensor,
then converts it to built-in floats with `.tolist()` -- never `.numpy()`,
never `numpy.astype`. Historical acquisition PCM bytes are not canonical
authority; the only law that governs is the one above.

## 5. Output

One document, `living_diorama_episode_voice_manifest`, schema version 1.
Top level: `format`, `schema_version`, `source` (eight keys, the plan's own
seven plus `voice_plan_sha256`), `environment` (seven keys: `device`,
`python_version`, `torch_version`, `spacy_version`, `spacy_model`,
`spacy_model_version`, `num2words_version` -- `device` and `spacy_model` are
exact-value laws, the rest are executor-reported attestation, never
independently proven), `voice_units` (the plan's five fields restated per
unit, plus `file`, `bytes`, `sha256`, `speech_samples`), and `completeness`
(`voice_units_expected`, `voice_units_synthesized`, `speech_samples_total`,
`complete` -- no separate aggregate fit flag).

A voice-unit record carries no realized text, no text hash, no presentation
frame coordinates, and no fit margin: identity is positional, and
`capacity_samples - speech_samples` is always derivable, never stored twice.

## 6. FIT

```
FIT  iff  speech_samples (recomputed from the actual WAV) <= capacity_samples
```

Inclusive: exactly equal is FIT. One sample over is REFUSE, for the whole
episode -- no manifest is ever written for an episode holding an unfit unit.
No retry, no probe, no second synthesis, no trimming, no time-stretching, no
wording change ever repairs an overflow.

## 7. One synthesis, per-unit seed reset

Exactly one engine invocation per voice unit, in plan order.
`torch.manual_seed(seed)` is called once, immediately before that one
invocation -- the exact semantics the reviewed acquisition evidence used.
Model and pipeline construction happen strictly before the first seed call.
Because the seed is reset before every unit, unit order never affects RNG
progression.

## 8. Offline execution

The executor is offline only. Three model assets -- weights, config, voice
pack -- are explicit local files, digest-verified against the plan's pins
**before** they are ever opened. The local spaCy model (`en_core_web_sm`)
and `num2words` must already be installed; `misaki.en.G2P.__init__` itself
calls `spacy.cli.download` when the model is absent, so this preflight is
what makes that acquisition path unreachable. A missing local resource is
refused, never downloaded. `KPipeline`'s default `EspeakFallback` is
explicitly replaced with `fallback=None` after construction, since the
constructor does not accept `None` directly for an English pipeline.

## 9. Atomic publication

Whole-episode staging: a sibling `<id>.partial` directory next to the final
`<id>` directory, both under the caller's output root. Every unit is
synthesized, written, re-opened from disk and re-verified (the publication
gate) before the manifest is even assembled. The manifest and plan copy are
written atomically (`.writing` temp, fsync, `os.replace`), and the whole
staging directory is published with a single `os.replace` onto the final
name. An existing, verified, matching final directory is a no-op; an
existing directory executing a different plan is refused, with nothing
deleted. Staging ownership -- including refusing to follow or delete
through a symlink or a Windows junction -- is proven before any cleanup, at
both the exact name and the exact parent location.

## 10. The independent audit

`audit_voice_directory` trusts nothing the executor recorded: it re-hashes
every file, re-parses every WAV through the closed canonical reader,
recomputes every sample count from the bytes on disk, and refuses any
unaccounted entry. The manifest is never measurement authority; the WAV is.

## 11. Command

```
python audio/kokoro/scripts/synthesize_episode.py \
    --voice-plan episode_voice_plan_v1.json \
    --realization episode_language_realization_plan_v1.json \
    --presentation episode_presentation_plan_v1.json \
    --delivery episode_narration_delivery_plan_v1.json \
    --narration episode_narration_plan_v1.json \
    --shots shot_direction_plan_v1.json \
    --story episode_story_plan_v1.json \
    --export render_export_ep1.json \
    --model-weights /path/to/kokoro-v1_0.pth \
    --model-config /path/to/config.json \
    --voice-pack /path/to/af_heart.pt \
    --output-root voice/

python -m living_diorama.cli.verify_voice --voice-dir voice/episode_0000_to_0001
```

## 12. Known limitations

- **One episode, one narrator.** As every layer upstream.
- **No resume.** Whole-episode staging costs seconds to redo on failure; a
  per-frame checkpoint mechanism was judged unnecessary surface area for
  this economics.
- **Environment attestation, not proof.** The manifest records what the
  executor reports about its own Python, Torch and spaCy versions; the
  audit never independently reconstructs that environment.
- **Cross-environment byte reproducibility is not claimed.** A fixed seed
  reproduced identical waveform digests across independent processes on the
  reviewed CPU environment during acquisition; this is evidence, never a
  contract this layer asserts.
