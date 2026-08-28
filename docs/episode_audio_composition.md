# The Episode Audio Composition (V1)

> Phase 31. Deterministic bytes; audited silence. **Copies exactly what was
> measured, fills exactly what was accounted, and invents no sample.**

## 1. Why this layer exists

Phase 30 closed the placement question: for a finished, audited Phase 29
voice execution and the Phase 27 presentation plan its windows come from,
exactly where does each unit's already-measured speech begin on the
episode's single audio-sample clock -- and therefore exactly what is
silence. It refused, on purpose, to place a single byte: "this plan places
speech; it never assembles an episode-length audio stream, generates
silence bytes, or joins anything to rendered frames. A future composition
layer does that, from this plan's own placements plus the audited Phase 29
artifacts." This layer is that future composition layer.

## 2. Ownership

**AUDIO COMPOSITION WRITES A PLACED EPISODE'S ONE TRACK. IT PLACES NOTHING.**

It owns: the one composed episode-length audio artifact, `episode_audio.wav`;
its `sha256`, its byte length and its recomputed sample count; silence as
actual zero-valued PCM16 bytes, not an accounting quantity; the per-span
placement evidence (`pcm_sha256`) proving each unit's payload landed
byte-for-byte at its planned offset; the composition manifest; and the
self-contained independent audit that re-reads the directory and decides
whether the manifest told the truth.

It does **not** own wording, capacity, narrator identity, synthesis,
measurement, presentation timing, onset policy, placement arithmetic, the
sample clock, captions, subtitles, mixing, gain, normalization, trimming,
resampling, music, sound effects, physical frame repetition, the visual
track, media assembly, encoding, container, mux, packaging or publishing.
It re-decides nothing Phase 30 placed and re-measures nothing Phase 29
measured -- it *re-proves* both against the bytes, which is different.

## 3. Inputs

Two documents are bound: the audited Phase 29 voice execution directory
(via its exact-byte copied manifest) and the sealed Phase 30 audio track
plan. Seven more are verification-only, arguments to the reused Phase 30
gate: the Episode Voice Plan and Episode Voice Manifest (read from inside
the audited directory), the Episode Presentation Plan, the Episode
Language Realization Plan, the Episode Narration Delivery Plan, the
Episode Narration Plan, the Shot Direction Plan, the Episode Story Plan and
the CURRENT Render Export.

There is deliberately **no flag accepting a detached, unaudited manifest**:
`--voice-dir` names a Phase 29 execution directory, and the reused directory
audit is the first thing the compose command does with it, before a single
offered document is parsed.

## 4. The artifact

One canonical WAV per episode: PCM16 little-endian, mono, the audited
execution's own sample rate, exactly forty-four canonical WAV header bytes,
no ancillary chunk, no trailing byte. The serializer is imported whole from
`living_diorama.voice_execution.speech_audio.canonical_wav_bytes`, never
reimplemented.

## 5. The composition law

```
allocate bytearray(audio_samples_total * 2)          -- all zero: silence
for each sealed speech span, in narration order:
    splice the audited unit's exact PCM payload verbatim at start_sample
wrap the result in the one locked canonical WAV serializer
```

No gain, no normalization, no trim, no VAD, no resampling, no dither, no
channel conversion, no mixing, no music, no sound effects, no time
stretching.

## 6. The geometry law

Before any payload is written, every speech span's containment and
non-overlap is proven by integer arithmetic alone, over the plan's own
records: `start >= 0`, `count >= 1`, `end = start + count <=
audio_samples_total`, and `start >= previous_end` in narration order. PCM
sample values are audio content and are **never** overlap authority. A
destination-zero check may run afterward as defence in depth, worded
"unexpected non-zero destination content" -- never described as the overlap
proof.

## 7. The source witness

An exact-byte copy of the already-audited Phase 29 `episode_voice_manifest.json`
is published inside the composition directory as source witness data -- not
a second owner. Its raw bytes are digest-bound to the sealed Phase 30 plan's
own `source.voice_manifest_sha256` **before the witness is ever parsed**:

```
read raw witness bytes
require sha256_hex(raw) == audio_track_plan["source"]["voice_manifest_sha256"]
    -- no parsing has occurred up to this point --
parse; require canonical form; validate under Phase 29's own contract
```

No `Path.resolve()` anywhere in this phase.

## 8. Output layout

```
<output root>/
  episode_0000_to_0001/
    episode_audio_track_plan.json          the exact plan bytes this directory composes
    episode_voice_manifest.json            exact-byte copy of the audited Phase 29 manifest
    audio/episode_audio.wav                the one composed track
    episode_audio_composition_manifest.json   written only on a complete composition
```

Exactly four owned top-level entries. No voice-plan copy. No second WAV. No
`speech/` directory. No `*.writing` or `.partial` litter in a finished
directory.

## 9. Atomic publication

Whole-episode staging: a sibling `<id>.partial` directory next to the final
`<id>`, both under the caller's output root. Documents are written
atomically (`.writing` temp, flush, fsync, `os.replace`), confined to one
module. `shutil.rmtree` appears at exactly one call site. `os.replace`
appears at exactly two call sites. Before terminal publication, the staged
directory must pass its own full independent audit -- the **terminal
publication gate** -- so no directory its own future verifier would reject
can ever become authoritative. `_require_direct_parent` refuses an indirect
or dangling output root at five call sites: the compose command's first
statement, the publisher's first filesystem touch, and each staging
primitive's own entry, so no filesystem query below the output root ever
precedes that proof. No-op authority exists only under a direct output
root.

## 10. The Audio Track Plan's single-capture identity

The compose command reads `--audio-track`'s content exactly once:
`audio_track_path.read_bytes()`, one call. Those same captured bytes -- and
no second, independent observation of the path -- govern everything
downstream: they are parsed into the document the whole Phase 30 source gate
verifies, they are the copied plan witness written into the composition
directory, their SHA-256 is the digest the existing-final verified no-op
compares against, and they are what `publish_episode_audio` receives as
`audio_track_plan_bytes`. An external mutation of the file between two
independent reads could once have let a document that passes the gate
diverge from the bytes that authorize a no-op; with one capture, there is no
second read for such a mutation to land between.

## 11. Handled-refusal ordering

A voice-unit-count mismatch between the audited witness and the sealed plan
is a **pre-staging** precondition: it is checked, and refuses if it fails,
before this invocation creates any fresh staging tree at all -- at that
point there is nothing on disk yet for a refusal to leave behind. Only after
that check passes does composition proceed to discard a *prior* run's stale
staging (if any) and then enter the handled-refusal `try`, which begins at
this run's own `staging_dir.mkdir()` and covers every statement from there
through terminal publication: the inner `audio/` mkdir, every per-unit write
and source-byte binding, the composed-track write and its re-measurement
gate, the manifest write, the terminal self-audit, both directory fsyncs and
the terminal publication call. Once that staging tree exists, a handled
refusal (`OSError`, `TypeError`, `ValueError` -- including
`CompositionRefused` -- or `CompositionDirectoryRefused`) discards it before
propagating, so a refusal never litters the output root; an exception of any
other class is never caught there, so its `.partial` tree survives untouched
as crash evidence for the next reviewed cleanup.

Every owned path this phase queries is refused as an indirection *before*
any query that would follow it, never after: the publisher refuses
`final_dir`'s own indirection before its first `.exists()` check;
`discard_owned_staging` refuses `staging_dir`'s indirection before the
`.exists()` short-circuit that would otherwise treat a **dangling** staging
symlink as simply absent (`Path.exists()` follows a link and reports based
on the target, so a dangling link needs its own, earlier check);
`publish_owned_staging` refuses the destination's indirection before its own
`.exists()` check, dangling or not; and the verify command refuses an
indirect `--composition-dir` before its `.is_dir()` preflight ever runs.
Every one of these checks reuses the one already-reviewed
`_is_path_indirection` helper -- no ancestor-chain resolution is introduced,
and `Path.resolve()` remains categorically unused anywhere in this phase.

## 12. The independent audit

`audit_audio_composition_directory` is self-contained: it reads only the
four entries inside the directory it is handed, and succeeds after the
original Phase 29 voice directory is no longer available. It trusts nothing
the composer recorded -- the track is re-hashed and re-parsed, every placed
span's PCM is re-extracted and reconstructed into a canonical unit WAV whose
bytes and digest must equal the audited Phase 29 witness's own recorded
values, and every sample outside every placed span must be zero.

Every governed entry -- the composition directory itself, the copied plan,
the copied witness, the composition manifest, `audio/` and its one WAV, and
any other discovered top-level or `audio/`-level entry -- is refused as a
problem if it is a symlink or Windows junction, before its content or
metadata is ever trusted. This holds even when the link's target would
otherwise audit perfectly clean: the refusal is about the indirection
itself, never about whether what it points to happens to be truthful.

The function's contract is that it never raises for an expected condition:
an `OSError`, `TypeError`, `ValueError` or `SpeechAudioProblem` arising from
any governed read, stat, parse or directory listing becomes a problem entry
in the returned list rather than escaping as an exception. A genuinely good
directory still returns `[]`; nothing outside that frozen expected-error
family is ever silently suppressed, and `BaseException` is never caught.

## 13. Source-payload identity

For each placed span, the exact PCM slice is extracted from the composed
track and reconstructed into a canonical unit WAV using the audited
profile. Under the repository's SHA-256 artifact-identity contract, that
reconstruction is accepted as the exact Phase 29 artifact identity when its
byte length equals the digest-bound witness record's `bytes` and its
SHA-256 equals that record's `sha256`. This is the same cryptographic
identity doctrine used throughout the locked pipeline; no stronger claim of
mathematical hash injectivity is made.

The optional whole-track re-composition the audit also performs is an
**internal-consistency check only** -- its payloads are drawn from the very
track it compares against, so it is self-referential and is never the
source-identity proof above.

## 14. Commands

```
python -m living_diorama.cli.compose_episode_audio \
    --audio-track episode_audio_track_plan_v1.json \
    --voice-dir voice/episode_0000_to_0001 \
    --presentation episode_presentation_plan_v1.json \
    --realization episode_language_realization_plan_v1.json \
    --delivery episode_narration_delivery_plan_v1.json \
    --narration episode_narration_plan_v1.json \
    --shots shot_direction_plan_v1.json \
    --story episode_story_plan_v1.json \
    --export render_export_ep1.json \
    --output-root audio_tracks/

python -m living_diorama.cli.verify_audio_composition \
    --composition-dir audio_tracks/episode_0000_to_0001
```

There is no `--voice-dir` on the verifier: it is self-contained by design.

## 15. Known limitations

- **One episode, one narrator.** As every layer upstream.
- **No resume.** A composition is milliseconds of work; a checkpoint
  mechanism was judged unnecessary surface area for this economics.
- **No media assembly.** This phase never joins the composed track to
  rendered frames or physical frame repetition; that is a still-deferred
  downstream layer.
- **No caption serialization, no encode, no mux.** Explicitly downstream and
  explicitly unowned by any locked phase.
- **Cross-environment byte reproducibility.** This phase's own output is
  byte-for-byte deterministic given the same sealed plan and the same
  audited payload bytes -- a stronger claim than Phases 23 and 29 make of
  their own artifacts, because this phase copies rather than generates.
