# The Episode Caption Serialization (V1)

> Phase 34. The caption plan's one missing thing: a target file format.
> Deterministic byte-sealed SRT and WebVTT sidecars under one pinned integer
> timestamp law. **No timing decisions, no wording, no styling, no display.**

## 1. Why this layer exists

The Episode Caption Plan closed the legibility question -- exactly which
locked sentence is shown on exactly which presentation window -- and named
this layer directly: "a future serialization layer, which alone requires a
target file format, does that." Phase 34 is that layer: it serializes the
locked plan's cues into two byte-sealed sidecar artifacts on the wall-clock
representation those formats require. Nothing here decides what a viewer
sees or when -- every span restates frames the plan already froze.

## 2. Ownership

**THE CAPTION SERIALIZATION MAKES A LOCKED PLAN LEGIBLE TO A TARGET FILE
FORMAT. IT DECIDES NO TIMING AND NO WORDING.**

It owns: the caption timestamp policy `caption_timestamp_policy_v1`; the two
frozen grammars (SRT and WebVTT) as exact byte laws; verbatim carriage of
every locked sentence or the whole refusal; the published directory of four
owned regular files; the manifest that binds the plan's digest; and the
self-contained audit that re-reads the directory and decides whether the
manifest told the truth.

It does **not** own wording, wrapping, styling, display, burn, encode or
mux: the viewer's actual display surface belongs to the player that reads
the sidecars, and to no phase of this project.

## 3. Inputs

One document is bound: the Episode Caption Plan, whose exact bytes become
the copied plan and the bound `caption_plan_sha256` -- parse, gate, digest
and copy all share that one observation. Seven more documents are
verification-only, arguments to the reused, unweakened Phase 32 gate
`validate_episode_caption_plan_against_sources` (which itself reruns the
locked Phase 27, 25 and 26 gates): the Episode Language Realization Plan,
the Episode Presentation Plan, the Episode Narration Delivery Plan, the
Episode Narration Plan, the Shot Direction Plan, the Episode Story Plan and
the CURRENT Render Export. None of the seven is bound in the serialization
manifest.

## 4. The caption timestamp policy

`caption_timestamp_policy_v1`, whole: a presentation boundary offset `n` on
a clock of `fps` frames per second derives the millisecond `n * 1000 // fps`
-- floor, never rounding, never a float. A cue legible on the 1-based
inclusive frames `[start, end]` occupies the half-open wall-clock interval
`[boundary_ms(start - 1), boundary_ms(end))`. Consecutive tight cues
therefore SHARE one boundary instant exactly: the next cue's start offset is
the previous cue's end offset, the same integer fed to the same function.
EP1's goldens at 24 fps are the shared instants `1000` (cue 1 opens),
`7000` (cue 1 closes / cue 2 opens), `22000` (cue 2 closes / cue 3 opens)
and `28000` (cue 3 closes) ms.

The derivation is total over its declared domain: `boundary_ms` never
refuses. The formatting rail is a different law -- the serializer's own
representation limit, two-digit hours: a derived timestamp at or beyond the
100-hour `MAX_TIMESTAMP_MS` rail is refused because the frozen `HH:MM:SS`
widths cannot carry it. That rail is reachable only from forged standalone
plans at fps 1 or 2 under `MAX_CAPTION_FRAME`; the canonical chain's pinned
24 fps tops out near 11.6 hours.

## 5. The SRT grammar

The frozen grammar, whole: for cues `i = 1..N` in plan order, one block is
`f"{i}\n{start} --> {end}\n{text}\n"` with comma-millisecond fixed-width
timestamps, and the file is the blocks joined by one `"\n"` -- a single
blank line BETWEEN blocks, never before the first and never after the last
-- encoded UTF-8 with no BOM, LF only, exactly one terminal LF (the final
block's own). Cue numbers are 1-based and sequential. Cue text is carried
verbatim on exactly one physical line, or the whole serialization is
refused.

## 6. The WebVTT grammar

The frozen grammar, whole: the header is exactly `"WEBVTT\n\n"` -- no BOM,
no header text, no NOTE, STYLE or REGION block -- followed by cue blocks
`f"{start} --> {end}\n{text}\n"` with period-millisecond fixed-width
timestamps, joined by one `"\n"`. There are deliberately NO cue identifiers:
each block is one timing line plus one verbatim text line, and the SRT
artifact carries the numeric restatement of order. Always the long
timestamp form with two-digit hours -- never the short `MM:SS.mmm`
abbreviation. UTF-8, LF only, exactly one terminal LF.

## 7. Verbatim carriage and the refusal set

Wording is Phase 26's and is never rewritten here: a sentence is carried
byte-for-byte or the whole serialization is refused. Refused exactly when
the text contains a C0 control character (CR, LF, NUL, TAB and the rest), a
Unicode line or paragraph separator (U+2028, U+2029), or the cue-timing
arrow `-->` (a structural parse hazard in both grammars, and forbidden
inside WebVTT cue text outright). Everything else -- a mid-text U+FEFF,
astral-plane characters, combining sequences -- is carried verbatim.

## 8. The published directory

A caption serialization is a FLAT directory of exactly four owned regular
files: the manifest `episode_caption_serialization_manifest.json`, the
exact-byte plan copy `episode_caption_plan.json`, and the two sidecars whose
basenames equal the directory id (`<episode_id>.srt` and
`<episode_id>.vtt`) -- the same-basename convention a downstream viewer
relies on when manually enabling them. No subdirectory, no foreign entry;
every owned regular file is an independent physical copy with exactly one
directory entry: never a symlink, a junction, or a hardlink.

## 9. The manifest

The Episode Caption Serialization Manifest binds `caption_plan_sha256`,
restates the plan's own source facts, clock and frame-authoritative
accounting (`caption_frames_total`, `captions_total`,
`uncaptioned_frames_total`) -- copied from the validated plan, never
recomputed, and never milliseconds: the only wall-clock representation of
the plan is the sidecar bytes themselves -- and records both sidecars'
exact `bytes`, `sha256`, `file` and `format` (`srt`, `webvtt`). The
document declares format
`living_diorama_episode_caption_serialization_manifest`, schema version 1,
policy `caption_timestamp_policy_v1`.

## 10. The self-contained audit

`audit_caption_serialization_directory` re-reads every byte on disk,
re-validates the copied plan under the locked Phase 32 schema, re-derives
the frame-authoritative accounting and every timestamp, re-serializes BOTH
sidecars from the copied plan and requires exact byte equality (never
merely by digest), re-hashes every owned file, and refuses any unaccounted
entry. It accepts no external manifest authority and needs no upstream
document. One law has no Phase 33 precedent and is deliberately stronger:
the directory's own name must equal the id re-derived from the copied
plan's source triple, so a renamed but internally consistent directory is
refused rather than trusted.

## 11. Command

```
python -m living_diorama.cli.serialize_episode_captions \
    --caption-plan episode_caption_plan_v1.json \
    --realization episode_language_realization_plan_v1.json \
    --presentation episode_presentation_plan_v1.json \
    --delivery episode_narration_delivery_plan_v1.json \
    --narration episode_narration_plan_v1.json \
    --shots shot_direction_plan_v1.json \
    --story episode_story_plan_v1.json \
    --export render_export_ep1.json \
    --output-root captions/
```

All eight inputs must be canonical bytes, each read exactly once. Exit 0 on
success, 1 on refusal, with a message rather than a traceback. Rerunning
the same inputs is a no-op.

```
python -m living_diorama.cli.verify_caption_serialization \
    --caption-dir captions/episode_0000_to_0001
```

The independent half of Phase 34: exactly one argument, one directory, no
upstream document flag of any kind.

## 12. Known limitations

- **One episode.** As every layer upstream.
- **No styling ever.** A sidecar is one verbatim text line per cue; the
  player owns the viewer's display surface, and no phase of this project
  will ever wrap, style or position a sentence.
- **Class A determinism.** The same accepted plan bytes produce
  byte-identical manifest, SRT and VTT on any machine -- floor integer
  arithmetic, frozen grammars, no float, no locale, no wall clock, no
  host-dependent rounding anywhere.
