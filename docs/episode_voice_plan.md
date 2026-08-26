# The Episode Voice Plan (V1)

> Phase 28. Deterministic narrator-request identity and integer audio
> capacity over a finished realization and presentation. **No synthesis, no
> measurement, no audio, no prose.**

## 1. Why this layer exists

Phase 27 closed the timing side of the voice gap it inherited from Phase 25:
every narration unit now owns a presentation window sized from structure
alone, so that a real voice has somewhere to fit before anyone measures
whether it does. Phase 27 named the next question directly: "whether a
synthesized voice fits it is a later layer's measured question." This layer
answers the half of that question that is still deterministic planning, not
measurement: **which reviewed narrator speaks, and exactly how much room
does its window offer, in audio samples?**

Whether real speech from that narrator actually fits is deliberately not
this layer's claim. An earlier design bound a measured sample count into
this plan directly, and could not prove that count came from real
synthesis: every check available to a document that only reads itself is
either about a different document or about the record's own internal
consistency, and none of those proves a Kokoro sample count true. The
correct fix is not a stronger check but a narrower claim: this layer plans
the request and the budget; a later Voice Execution phase synthesizes
exactly once, recomputes its own sample count from the audio it actually
produced, and proves that count fits.

## 2. Ownership

Phase 28 owns exactly one question: **given a finished realization and a
finished presentation, which one reviewed narrator request speaks each
sentence, and how many audio samples does its window hold?**

THE VOICE PLAN DEFINES REVIEWED SPEECH AND REVIEWED CAPACITY. IT MEASURES
NOTHING.

It does **not** own wording, presentation timing, world truth, story truth,
speech synthesis, measured speech duration, waveform bytes, PCM encoding,
audio files, an audio manifest, captions, subtitles, mixing, music, physical
frame repetition, or any runtime voice model.

## 3. Inputs

Two documents are **bound** — restated by digest in this plan's own
`source` block and consumed by its derivation:

| Input | Contributes |
| --- | --- |
| **Episode Language Realization Plan V1** | each unit's exact sentence identity — `realization_id` — this plan's voice units name |
| **Episode Presentation Plan V1** | each unit's presentation window, whose length in frames this plan converts to an audio-sample capacity |

Five more are **verification-only** — arguments to one locked upstream gate,
never bound in this plan's own `source` block, never touched by this plan's
own derivation:

| Input | Used by |
| --- | --- |
| **Episode Narration Delivery Plan V1** | the reused Phase 27 gate, itself reusing the Phase 25 gate |
| **Episode Narration Plan V1** | the reused Phase 27 gate, itself reusing the Phase 25 gate |
| **Shot Direction Plan V1** | the reused Phase 27 gate, itself reusing the Phase 25 gate |
| **Episode Story Plan V1** | the reused Phase 27 gate, itself reusing the Phase 26 gate |
| **CURRENT Render Export V1** | the reused Phase 27 gate, itself reusing the Phase 26 gate |

There is deliberately **no measurement record and no audio input of any
kind**. A voice plan is narrator-request identity and integer capacity,
settled before a single sample of audio is ever produced.

## 4. Why seven inputs, and why only two are bound

A voice unit's `capacity_samples` is only proven true of the actual
presentation window by the locked Phase 27 source-verification gate,
because only it holds the actual delivery plan, narration plan, shot plan,
story plan and render export. Since this layer's whole claim is capacity
over a real window, skipping that gate would let a forged window — internally
consistent, individually plausible — silently inflate or shrink a budget
this plan then treats as authoritative. That gate, in turn, already reruns
the Phase 25 and Phase 26 gates in full, so a single reused call closes every
provenance question this layer would otherwise have had to re-derive by
hand.

The five verification-only documents are never bound in this plan's `source`
block for the opposite reason: this plan makes no claim about them that the
reused gate does not already prove. Restating their digests here would be a
copy, not proof — the exact reasoning Phase 27 itself gave for the same
question one layer up.

## 5. Output

One document, `living_diorama_episode_voice_plan`, schema version 1.

```json
{
  "accounting": {"capacity_samples_total": 648000, "voice_units_total": 3},
  "format": "living_diorama_episode_voice_plan",
  "policy": "voice_policy_v1",
  "schema_version": 1,
  "source": {
    "episode": 1,
    "mode": "transition",
    "previous_episode": 0,
    "presentation_plan_sha256": "…",
    "presentation_schema_version": 1,
    "realization_plan_sha256": "…",
    "realization_schema_version": 1
  },
  "voice": {
    "channels": 1,
    "engine": "kokoro",
    "engine_version": "0.9.4",
    "g2p": "misaki",
    "g2p_version": "0.9.4",
    "lang_code": "a",
    "model_config_sha256": "5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f",
    "model_repository": "hexgrad/Kokoro-82M",
    "model_revision": "f3ff3571791e39611d31c381e3a41a3af07b4987",
    "model_weights_sha256": "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4",
    "sample_rate_hz": 24000,
    "seed": 0,
    "speed_percent": 100,
    "voice": "af_heart",
    "voice_pack_sha256": "0ab5709b8ffab19bfd849cd11d98f75b60af7733253ad0d67b12382a102cb4ff"
  },
  "voice_units": [
    {"capacity_samples": 144000, "realization_id": "realization_0001", "unit_id": "unit_0001", "voice_unit_id": "voice_unit_0001", "window_id": "window_0001"},
    {"capacity_samples": 360000, "realization_id": "realization_0002", "unit_id": "unit_0002", "voice_unit_id": "voice_unit_0002", "window_id": "window_0002"},
    {"capacity_samples": 144000, "realization_id": "realization_0003", "unit_id": "unit_0003", "voice_unit_id": "voice_unit_0003", "window_id": "window_0003"}
  ]
}
```

That is the real episode 0 → 1 plan. A voice-unit record deliberately
carries **no realized text, no text hash, no presentation frame coordinates,
no measured sample count and no fit status**: its sentence identity is a
`realization_id`, never prose, and its window is a `window_id`, never a
repeated pair of frame numbers.

## 6. The narrator request

`voice_policy_v1`, closed and versioned, with exactly one narrator request,
fifteen pinned fields:

| Field | Value |
| --- | --- |
| `engine` / `engine_version` | `kokoro` / `0.9.4` |
| `g2p` / `g2p_version` | `misaki` / `0.9.4` |
| `model_repository` / `model_revision` | `hexgrad/Kokoro-82M` / `f3ff3571791e39611d31c381e3a41a3af07b4987` |
| `model_weights_sha256` | `496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4` |
| `model_config_sha256` | `5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f` |
| `voice` / `voice_pack_sha256` | `af_heart` / `0ab5709b8ffab19bfd849cd11d98f75b60af7733253ad0d67b12382a102cb4ff` |
| `lang_code` | `a` (American English) |
| `speed_percent` | `100` |
| `sample_rate_hz` | `24000` |
| `channels` | `1` |
| `seed` | `0` |

Every value is Director-reviewed evidence: the model and voice-pack digests
were independently re-hashed against the published Hugging Face artifacts at
the pinned revision. `speed_percent` is an integer percentage rather than a
float, so no float ever enters this contract for a conceptually rational
value. There is exactly one narrator in V1 — no per-unit voice selection, no
character voices, no emotional acting, no pitch or temperature.

## 7. The clock-crossing law

fps is read only from the proven Phase 27 presentation timeline — never a
Phase 28 constant, exactly as fps is never a Phase 27 constant either: it is
data, pinned by the Motion & Time digest.

```
samples_per_presentation_frame(fps) = SAMPLE_RATE_HZ // fps,
    refusing unless SAMPLE_RATE_HZ % fps == 0

capacity_samples(window) = window_frames × samples_per_presentation_frame(fps)
```

At the pinned canonical pairing, `24_000 // 24 == 1_000` exactly: one
presentation frame is worth exactly 1,000 audio samples. Integer arithmetic
throughout; no float, no tolerance, no rational approximation for an
incompatible pairing — V1 refuses one outright rather than guess.

## 8. The canonical geometry

| Ep | Unit | Window frames | `capacity_samples` |
| --- | --- | --- | --- |
| 0 | `unit_0001` | 192 | 192,000 |
| 1 | `unit_0001` | 144 | 144,000 |
| 1 | `unit_0002` | 360 | 360,000 |
| 1 | `unit_0003` | 144 | 144,000 |
| 2 | `unit_0001` | 360 | 360,000 |
| 2 | `unit_0002` | 144 | 144,000 |

These, and only these, are legitimate canonical test truth — re-derived from
locked Phase 27 window geometry. No measured speech duration or sample count
appears in any canonical fixture, test, or document; that evidence belongs
to architecture recovery notes, never to this contract.

## 9. Mandatory upstream verification

Before any window or realization becomes authoritative, this layer's
cross-check reuses, in full and unweakened, one locked gate:

`validate_episode_presentation_plan_against_sources(presentation, delivery,
narration, shots, realization, story, current_export)` — the Phase 27 proof
that the presentation plan's windows, and the realization plan's sentences
they name, are true of the actual delivery, narration, shot, story and
render-export chain. This gate itself reruns the Phase 25 and Phase 26 gates
in full.

Not reimplemented. A forged-but-standalone-valid presentation plan, or a
realization whose wording was forged alongside its structure to stay
internally consistent, is refused here — not because this layer re-derives
the proof, but because it delegates to the layer that owns it.

## 10. What this layer refuses to know

**No prose at all.** No module here reads a narration unit's `text`, a
realization's `realized_text`, a memory fact's `summary`, or an event's
`source_event_payload` — not carried, not counted, not compared, not even
for length. A voice unit names its sentence by `realization_id` only.

**No speech synthesis, no measurement.** Nothing here calls a voice model,
counts samples, or measures a waveform. `capacity_samples` is arithmetic
over structure — a window's frame count and the proven fps — never a
prediction about real speech.

**No audio authority.** This plan is never bound to an audio file, a
waveform, or a measurement record, and must survive a semantically identical
re-render unchanged.

One deliberate asymmetry from Phase 26 and Phase 27's own text bans: this
layer **does** canonically serialize and hash the entire offered realization
document, to bind `realization_plan_sha256`. That is a key-blind, opaque
transform over bytes — never a semantic read of `realized_text` or any other
field inside the document — and it is required, not merely permitted.

## 11. Accounting

Fail-closed, and provable from the document alone: `voice_units_total ==
len(voice_units)`; `capacity_samples_total` is the sum of the records
present; every voice unit is positional, so a reorder, an omission and a
duplicate are all unrepresentable.

## 12. Determinism

Same two bound documents, same pinned narrator request, same bytes. Reads
and writes go through the repository's canonical codec. Identifiers are
positional. The policy is a compile-time rule set with fifteen reviewed
constants. No clock, no randomness, no uuid, no environment, no filesystem
outside the CLI, no network, no model call — enforced structurally by the
boundary guard and asserted behaviourally across `PYTHONHASHSEED` 0, 1, 42
and 123456 in subprocesses.

## 13. Source binding

| Document | Bound as |
| --- | --- |
| realization plan | `realization_plan_sha256` over its canonical bytes |
| presentation plan | `presentation_plan_sha256` over its canonical bytes |

The delivery plan, narration plan, shot plan, story plan and render export
are bound to **nothing** in this document; they exist only as arguments to
the gate in §9.

Schema validity and relationship validity are kept in separate modules
exactly as every locked phase keeps them. The schema proves everything the
plan can prove about itself — its narrator request's exact equality to the
one reviewed policy, and every voice unit's own positional identity and
plausibility rail. The cross-check proves the plan's claims are true of its
sources: the reused upstream gate, the plan's own digest bindings, that
every voice unit speaks its positional unit and names its positional
realization and window, that every `capacity_samples` equals the exact
capacity of the real window it claims, and — finally — the re-derivation
seal: the plan is re-derived from its two bound sources and must equal it
byte for byte. **Refuse, never repair.**

## 14. Boundaries, enforced structurally

`tests/voice/test_phase28_boundary.py` proves, by parsing the sources rather
than by reading them:

- the layer imports only Phase 26's and Phase 27's contracts and gates, the
  narration mode/ID vocabulary Phase 27 itself already imports from
  `living_diorama.narration.narration_schema_v1`, and the shared codec and
  validation vocabulary — deliberately no `living_diorama.story`, no
  `living_diorama.render`, no `living_diorama.render_execution`, no
  `living_diorama.memory`, and no `kokoro`, `misaki`, `torch` or `numpy`
- no module reads `text`, `realized_text`, `summary` or
  `source_event_payload` by subscript, `.get` or `.pop` — an empty
  allow-list, with whole-document canonical serialization explicitly
  permitted as the one structural exception
- no pure module touches the filesystem; only the CLI reads or writes
- no module defines a name belonging to captions, audio, waveform, PCM,
  WAV, containers, mixing, gain, normalization, trimming, VAD, assembly,
  encoding, publishing, camera re-direction, a runtime model, or any
  non-frame unit of time
- the cross-check both imports and actually calls the locked upstream gate
- every guard is exercised against a deliberately bad synthetic file

## 15. Command

```
python -m living_diorama.cli.build_voice_plan \
    --realization episode_language_realization_plan_v1.json \
    --presentation episode_presentation_plan_v1.json \
    --delivery episode_narration_delivery_plan_v1.json \
    --narration episode_narration_plan_v1.json \
    --shots shot_direction_plan_v1.json \
    --story episode_story_plan_v1.json \
    --export render_export_ep2.json \
    --output episode_voice_plan_v1.json
```

All seven inputs must be canonical bytes. The output is never overwritten.
The reused upstream gate and the full cross-check run before the file is
written, so a voice plan can never exist without every one of its bindings
having been proven. Exit 0 on success, 1 on refusal, with a message rather
than a traceback.

## 16. Known limitations

- **One episode.** A plan speaks one baseline or one transition, as every
  layer upstream does.
- **One narrator.** V1 pins a single reviewed request for every unit; a
  future per-unit or per-role voice would be a reviewed schema version,
  never a quiet edit.
- **Capacity is not a fit proof.** This plan proves how many samples a
  window holds, never that any given synthesized sentence is short enough
  to fit inside it. Whether real speech fits is the later voice execution
  layer's measured question, answered against real audio and refused when
  it fails.
- **No audio, no waveform, no manifest.** This plan is never bound to a
  measurement record or an audio file of any kind; a later execution layer
  alone owns synthesis, the produced audio, and the manifest that proves
  what was actually produced.
