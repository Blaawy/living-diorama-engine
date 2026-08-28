# The Episode Media Assembly (V1)

> Phase 33. Deterministic bytes; a locked presentation realized onto locked
> pixels. **Decides nothing, drops nothing, and every published frame is an
> independent physical copy.**

## 1. Why this layer exists

Phase 27 closed the presentation question: for a sealed delivery, narration
and realization, exactly which semantic frame is shown at each presentation
coordinate, and for how long. Phase 23 closed the render question: exactly
which pixels a directed episode's shots photographed. Phase 31 closed the
audio question: exactly which composed track carries an episode's sound.
None of the three joins the others to a physical sequence of files a viewer
could actually watch. This layer is that join: it turns a locked
presentation mapping, a locked render manifest and a locked audio track into
one self-contained, provenance-bound, pre-encode media assembly directory.

## 2. Ownership

**PHASE 33 REALIZES A LOCKED PRESENTATION ONTO LOCKED RENDERED ASSETS. IT
DECIDES NOTHING.**

It owns: the physical presentation-rate PNG sequence, realized as one
independent byte copy per presentation frame from the accepted Phase 23
playback frames, per the accepted Phase 27 segment expansion; the unchanged
Phase 31 episode WAV, carried forward without modification; byte copies of
every document it bound, including the two Phase 25 / Phase 22 verification
witnesses that make the render-to-timing join re-provable from the published
directory alone; the Episode Media Assembly Manifest; and the self-contained
independent audit that re-reads the directory and decides whether the
manifest told the truth.

It does **not** own: which semantic frame is shown when (Phase 27), which
pixels a frame holds (Phase 23), what the episode sounds like (Phase 31),
narration wording, camera direction, speech placement, world truth, story
truth, or simulation time. It never decodes, re-renders, scales,
colour-manages or transforms a pixel; never synthesizes, mixes, normalizes
or re-encodes audio; never reads, serializes, styles or burns a caption;
never encodes a video stream, creates a container, or muxes. Every realized
frame is an independent physical byte copy -- never a symlink, a Windows
junction, or a hardlink -- and every Phase 33-owned regular file is proven,
by its own self-contained audit, to hold exactly one directory entry.

## 3. Inputs

Three documents are bound as primaries, each read and digest-captured
exactly once: the Phase 23 Episode Render Manifest (and its playback PNGs,
read from the render directory), the Phase 27 Episode Presentation Plan, and
the Phase 31 Episode Audio Composition Manifest (and its carried WAV). Two
more are bound as digest-only provenance witnesses, never sources of
placement or pixel authority: the Phase 25 Episode Narration Delivery Plan
and the Phase 22 Shot Direction Plan. Four more are verification-only,
arguments to the reused, unweakened Phase 27 source-verification gate: the
Episode Narration Plan, the Episode Language Realization Plan, the Episode
Story Plan, and the render export the story and realization were derived
from.

There is deliberately **no flag accepting a detached, unaudited media
assembly manifest**, and no upstream directory audit -- neither Phase 23's
nor Phase 31's -- is ever imported or called. Each upstream phase owns the
correctness of its own artifacts; this phase consumes each one's published,
digest-bound interface.

## 4. The artifact

One physical PNG file per presentation frame, byte-identical to the Phase 23
playback frame it realizes -- never decoded, never re-encoded, never
resized. One carried WAV, byte-identical to the Phase 31 composed track. No
pixel is ever opened as an image; every frame is proven by length and
SHA-256 alone, exactly as every other byte-identity claim in this project is
proven.

## 5. The mapping law

```
for each presentation position p in the Phase 27 segment expansion:
    semantic = the semantic frame p maps to
    render_record = the Phase 23 playback record for that semantic frame
                     (selected by the semantic frame the mapping computed,
                      never by any record's own self-declared field)
    copy render_record's exact bytes to presentation/frame_{p:07d}.png
```

The expansion is re-derived independently by this phase from the copied
Phase 27 plan's own segments -- belt-and-braces, agreeing with the plan's own
standalone validator rather than trusting it alone. The witness frame (the
terminal boundary frame Phase 23 rendered as evidence) is proven, by
integer arithmetic over the resolved clock, to appear at no presentation
position.

## 6. The integer clock closure law

Before a single frame is copied, the presentation, visual and audio clocks
are proven to close on one another, in exact integers only: the render
manifest's `playback_fps` equals the presentation plan's own `timeline.fps`;
the audio sample rate divides evenly by that fps; `audio_samples_total`
equals `presentation_frames_total * samples_per_presentation_frame`; and the
presentation plan's own semantic coverage equals the render manifest's own
emission span, exactly. No float and no wall clock is authoritative
anywhere in this law.

## 7. The source witnesses and the D-chain

The presentation plan deliberately binds no shot-plan digest of its own:
identity plus the pinned motion-time digest alone would accept a render of a
*different* valid Shot Plan of the same episode, on the same clock. The two
provenance witnesses close that gap. At assembly time, the already-proven
Phase 27 gate's own first statement (the locked Phase 25 gate) already
proves the shot plan the delivery schedule was timed against; this layer
compares that same digest against the one the Phase 23 render was directed
by. At audit time, with no upstream path available, the identical
conclusion is reconstructed entirely from bytes published inside the
directory:

```
copied presentation plan .source.delivery_plan_sha256 == SHA256(provenance/episode_narration_delivery_plan.json)
copied delivery plan     .source.shot_plan_sha256     == SHA256(provenance/shot_direction_plan.json)
copied delivery plan     .source.shot_plan_sha256     == copied render manifest.source.shot_plan_sha256

therefore:  Phase 27 presentation -> exact bound Phase 25 delivery -> exact bound Phase 22 shots <- exact Phase 23 render
```

## 8. Output layout

```
<output root>/
  episode_0000_to_0001/
    episode_render_manifest.json                   exact-byte copy of the bound Phase 23 manifest
    episode_presentation_plan.json                  exact-byte copy of the bound Phase 27 plan
    episode_audio_composition_manifest.json         exact-byte copy of the bound Phase 31 manifest
    episode_media_assembly_manifest.json            written only on a complete assembly
    presentation/frame_0000001.png .. frame_NNNNNNN.png   one PNG per presentation frame
    audio/episode_audio.wav                         the unchanged carried track
    provenance/episode_narration_delivery_plan.json exact-byte copy of the Phase 25 witness
    provenance/shot_direction_plan.json             exact-byte copy of the Phase 22 witness
```

Exactly seven owned top-level entries. No `*.writing` or `.partial` litter in
a finished directory.

## 9. Atomic publication and the single-link law (Correction K)

Whole-episode staging: a sibling `<id>.partial` directory next to the final
`<id>`, both under the caller's output root. Documents are written
atomically (`.writing` temp, flush, fsync, `os.replace`); each presentation
frame is written with `open(path, "xb")` -- creating a new, independent
directory entry that cannot itself produce a hardlink -- followed by flush
and fsync, with no `.writing` temp of its own, because a staged frame lives
inside a `.partial` tree that by construction is never a published artifact.
Every filesystem primitive is confined to one module; `shutil.rmtree`
appears at exactly one call site, `os.replace` at exactly two.

**Every Phase 33-owned regular file -- every presentation frame, the carried
WAV, all four top-level documents, and both provenance witnesses -- must
satisfy `lstat().st_nlink == 1`.** A hardlink is neither a symlink nor a
junction: it passes every content and digest check while two names silently
share one inode. `_require_single_link_regular_file` enforces this
identically at staging ownership proof, cleanup authority, publication, and
inside the terminal self-contained audit, so a hardlinked entry is refused
at every layer that could otherwise mistake it for an independent copy --
including an otherwise byte-perfect *existing* final directory, which is
refused as a candidate for a verified no-op rather than silently accepted.

Before terminal publication, the staged directory must pass its own full
independent audit -- the **terminal publication gate** -- so no directory its
own future verifier would reject can ever become authoritative.
`_require_direct_parent` refuses an indirect or dangling output root as the
first statement of both the assemble command and the publisher, so no
filesystem query below the output root ever precedes that proof. No-op
authority exists only under a direct output root.

## 10. Single-capture identity

Every authoritative input is read exactly once: the render manifest, the
presentation plan, the composition manifest, the carried WAV, and both
provenance witnesses. Those same captured bytes -- and no second,
independent observation of the same path -- govern everything downstream:
parsing, every digest, every cross-branch join, and the published copy. Each
unique playback PNG is likewise read exactly once, at the position it is
first needed, and that same captured payload supplies every presentation
position that semantic frame is held across (a dwelled segment copies the
same captured bytes to more than one destination file, never reopening the
source). The existing-final no-op decision reuses the audit module's own
single manifest observation rather than performing a second, independent
read of its own.

## 11. Handled-refusal ordering

A missing-semantics precondition -- every semantic frame the presentation
plan requires has a playback record in the render manifest -- is checked,
and refuses if it fails, before this invocation creates any fresh staging
tree at all: at that point there is nothing on disk yet for a refusal to
leave behind. Only after that check passes does assembly proceed to discard
a *prior* run's stale staging (if any, and only once proven wholly this
phase's own) and then enter the handled-refusal `try`, which begins at this
run's own `staging_dir.mkdir()` and covers every statement from there
through terminal publication. Once that staging tree exists, a handled
refusal (`OSError`, `TypeError`, `ValueError` -- including
`MediaAssemblyRefused` -- or `MediaAssemblyDirectoryRefused`) discards it
before propagating, so a refusal never litters the output root; an exception
of any other class is never caught there, so its `.partial` tree survives
untouched as crash evidence for the next reviewed cleanup.

## 12. The independent audit and the mapping re-proof

`audit_media_assembly_directory` is self-contained: it reads only the
entries inside the directory it is handed, and succeeds after the Phase 23
render directory, the Phase 31 composition directory, and the presentation,
delivery and shot plan files this assembly was built from are no longer
available. It trusts nothing the publisher recorded: every bound document's
digest is re-hashed from the copy beside it; the D-chain is re-proven
entirely from the four published documents; and the Phase 27 presentation
mapping is independently re-derived from the copied plan and compared,
position by position, against every published frame record.

**The render record a frame must match is selected by the independently
re-derived semantic frame, never by the frame record's own declaration.** A
forged manifest that swaps two frame records' `semantic_frame` values, or
duplicates one semantic frame while dropping another, cannot pass by
agreeing with itself -- the audit never asks a record what it claims to be;
it asks the re-derived mapping what that position is *required* to be, and
compares the record against that.

Every governed entry is refused as a problem if it is a symlink or Windows
junction, before its content or metadata is ever trusted. The public
function's contract is that it never raises for an expected condition: an
`OSError`, `TypeError`, `ValueError` or `MediaAssemblyDirectoryRefused`
arising from any governed read, stat, parse or directory listing becomes a
problem entry in the returned list rather than escaping as an exception. A
genuinely good directory returns `[]`; nothing outside that frozen expected
family is ever silently suppressed. The public audit accepts exactly one
argument -- the directory -- and no parameter through which a caller may
supply manifest bytes of its own.

## 13. Commands

```
python -m living_diorama.cli.assemble_episode_media \
    --render-dir renders/episode_0000_to_0001 \
    --composition-dir audio_tracks/episode_0000_to_0001 \
    --presentation episode_presentation_plan_v1.json \
    --delivery episode_narration_delivery_plan_v1.json \
    --shots shot_direction_plan_v1.json \
    --narration episode_narration_plan_v1.json \
    --realization episode_language_realization_plan_v1.json \
    --story episode_story_plan_v1.json \
    --export render_export_ep1.json \
    --output-root media_assembly/

python -m living_diorama.cli.verify_media_assembly \
    --assembly-dir media_assembly/episode_0000_to_0001
```

There is no `--render-dir`, `--composition-dir`, `--presentation`,
`--delivery` or `--shots` flag on the verifier: it is self-contained by
design.

## 14. Known limitations

- **One episode.** As every layer upstream.
- **No resume.** An assembly is realized from bytes already on disk; a
  checkpoint mechanism was judged unnecessary surface area for this
  economics.
- **No caption serialization, no encode, no mux, no container, no
  packaging.** Explicitly downstream and explicitly unowned by any locked
  phase.
- **No pixel decoding.** Every frame identity claim is a byte-length and
  SHA-256 claim; no image codec is ever invoked, and no frame's pixel
  content is ever inspected.
- **Cross-environment byte reproducibility.** This phase's own output is
  byte-for-byte deterministic given the same bound input bytes -- a phase
  that copies rather than generates earns the strong determinism contract.
