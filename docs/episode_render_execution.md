# Phase 23 — Episode Render Execution

*Deterministic documents; measured pixels.*

**RENDER EXECUTION REALIZES A DIRECTED EPISODE. IT DIRECTS NOTHING.**

Phase 21 decided what mattered. Phase 22 decided where the viewer looks and
when the camera cuts. Phase 23 takes that directed episode and produces the
actual frame assets, plus a manifest that proves exactly what was produced.

---

## 1. Position in the pipeline

```
ENGINE → WORLD STATE → EVENT LOG / WORLD MEMORY → RENDER EXPORT V1
                                                        ↓
                                                 EPISODE STORY PLAN
                                                        ↓
                                                 SHOT DIRECTION PLAN
                                                        ↓
                                              EPISODE RENDER PLAN
                                                        ↓
                                          rendered frames + RENDER MANIFEST
```

Everything above this layer is locked. Phase 23 reads those documents, composes
the world their layers build, and photographs it.

---

## 2. What this layer owns, and what it does not

It owns: which frames become playback assets, what those files are called,
where a render lands, the presentation profile a production render runs under,
and the record of what actually exists on disk.

It does **not** own narration, prose, subtitles, voiceover, audio, music, final
editing, video encoding, thumbnails, packaging, publishing, or any re-direction
of the cameras Phase 22 chose. It never creates, moves or re-lenses a camera,
never edits the world it was handed, never re-runs an upstream planner, and
never touches the live simulation. A beat Phase 22 honestly left unshown stays
unshown: no frame is rendered to make up for it, and no frame record cites it.

If Phase 23 disagrees with a valid upstream decision, it renders it.

---

## 3. The frame emission contract

This is the one new decision the phase makes, so it is written out in full.

Phase 17 declares its timeline as a start frame plus three phase lengths, and
refuses itself unless they close on the declared end frame:

```
start_frame 1 + start_hold 24 + transition 120 + end_hold 48 = end_frame 193
```

Those phase lengths are **frame counts**, and they only add up if each phase
owns a half-open range:

| phase | range | frames | declared |
| --- | --- | --- | --- |
| start hold | `[1, 25)` | 1 … 24 | `start_hold_frames` = 24 |
| transition | `[25, 145)` | 25 … 144 | `transition_frames` = 120 |
| end hold | `[145, 193)` | 145 … 192 | `end_hold_frames` = 48 |
| **total** | | **192** | |

Phase 17 computes the episode's duration the same way — `(end_frame -
start_frame) / fps` = 192 / 24 = **8.0 seconds** — which is the duration every
upstream document states.

**Therefore:**

- **First emitted frame:** 1
- **Final emitted frame:** 192
- **Emitted frame count:** 192
- **Playback duration at 24 fps:** exactly 8.0 seconds
- **Frame 193:** the terminal boundary — the 193rd frame *number*, not a 193rd
  frame of content. It is rendered once as a **closure witness** and is not
  part of the playback sequence.

Emitting 193 frames would produce an 8.0417-second episode while every upstream
document still said 8.0, and it would end on the loop seam: frame 193 is the
state the next leg opens on, so a run of episodes would show that picture twice
at every join.

**Why frame 193 is still rendered, and what it actually proves.** It is the
loop seam: the frame at which Phase 17 proves endpoint equivalence and Phase 22
proves loop closure. Rendering it turns the argument above into evidence, and
the real-Blender suite checks three things about it on the composed world:

1. it is on the **same camera** as the last playback frame, so the boundary is
   not a cut;
2. Phase 19's movers have **returned to their frame-1 positions** — that
   layer's own locked contract — so the boundary frame is the seam the next
   leg's frame 1 shows again, and emitting it would show that seam twice;
3. the picture at 193 differs from the picture at 192 by only the residue of
   one frame of motion, **measured** and required to be inside tolerance.

Point 3 is a measurement, not an identity claim, and the difference is real.
The end hold holds Phase 17's world still, but Phase 19's pedestrians keep
walking through it, so 94 of the world's objects stand in slightly different
places at 193 than at 192. On the canonical leg the measured difference is
**0.08 levels** out of 255 — one frame of motion, on top of the renderer's own
0.02 of noise (§7) — while two genuinely different frames of the same episode
measure **47.5**. The manifest records the measurement and computes its verdict
from it, so a render that ended mid-action cannot describe itself as one that
ended cleanly.

**A note on precedent.** Phase 19's mobility proof clip renders all 193 frames.
That is proof tooling whose purpose is to show both endpoints of a loop, not a
playback contract — and this layer's own duration authority is Phase 17's
`duration_seconds`, which is span arithmetic. The two do not conflict; they
answer different questions.

---

## 4. The render profile

Phase 23 owns a presentation profile, pinned by digest and bound into every
render plan. It has two halves, kept deliberately separate.

**Owned — set on the scene before rendering:**

| setting | value | why |
| --- | --- | --- |
| engine | `CYCLES` | the reviewed renderer for every canonical image |
| resolution | 1280 × 720 at 100% | the resolution the repository already renders and reviews at, chosen so a full 192-frame episode finishes in a practical wall clock |
| pixel aspect | 1.0 / 1.0 | square pixels; anything else silently reshapes the frame |
| format | PNG, RGB, 8-bit, compression 15 | lossless and independently hashable; the image digest is taken on the decompressed stream because the compressor's bytes are not stable |
| film transparent | off | an episode has a sky |
| motion blur | off | every claim this phase makes is per-frame; a blurred frame depends on its neighbours |
| samples | 96 adaptive, threshold 0.08 | the repository's established fast tier |
| denoising | OpenImageDenoise, RGB+albedo+normal | as the locked proof renderer |
| bounces | 8 / volume 1 / transparent 12 | the locked budget |
| **cycles seed** | **0, animated seed off** | narrows the renderer's noise band as far as it can be narrowed, so the boundary measurement in §3 reads motion rather than sampling. It does not make a render reproducible; see §7 |

**Verified — checked, never written:**

| setting | value | why not owned |
| --- | --- | --- |
| view transform | `AgX` | colour management belongs to the Phase 15 world build |
| look | `AgX - Medium High Contrast` | same |
| exposure | 1.25 | same, from the reviewed style profile |
| fps / fps_base | 24 / 1.0 | the clock belongs to Phase 17 |

A scene that disagrees with the verified half is **refused**. Overriding a
locked layer's presentation from inside a render command would hide the fact
that the scene is not the reviewed world.

Raising the quality tier changes the profile digest, which changes every plan
binding — so a higher-quality render can never be mistaken for this one.

---

## 5. Output layout

```
<output root>/
  episode_0000_to_0001/
    episode_render_plan.json        the plan this directory renders
    frames/frame_0001.png … frame_0192.png
    witness/frame_0193.png
    render_checkpoint.json          resume state (not a canonical artifact)
    episode_render_manifest.json    written only on a complete render
```

The directory name is derived from the episode identity
(`episode_<previous>_to_<episode>`, or `episode_<n>_baseline`), so the same leg
always resumes its own render and two legs can never collide. Identity is
proved by digest inside the directory, not by the name alone: a directory
holding a plan with a different digest is **refused**, never reused and never
cleared.

Frame files are named by their **semantic** frame number, zero-padded, so a
file name is traceable to the clock and an ordinary directory listing sorts in
playback order.

Those five entries are the whole of it, and **both** the production executor and
the independent audit enforce that — a phase with two definitions of a valid
render directory has none. A top-level name is one of three things:

* **owned** — one of the five entries above.
* **partial** — `.partial`, or a `*.writing` temporary from the atomic writer.
  This phase's own litter from an interrupted run. It is recoverable and says
  nothing hostile, but a directory holding one is not finished.
* **foreign** — anything else. Something that is not this phase has written
  here, and no verdict about the render can be trusted while that is true.

Nothing is deleted on the strength of that classification. It decides what the
refusal says. The audit additionally refuses anything else found — a stray file beside the manifest, or a `.partial`
surviving from a render that died mid-frame, which the executor removes as each
frame is published and which therefore contradicts a manifest sitting next
to it.

---

## 6. The two documents

**Episode Render Plan V1** (`living_diorama_episode_render_plan`) binds the
whole provenance chain — shot plan format, version and digest; the story plan,
Motion & Time and camera catalogue digests copied from it; the render profile
digest; the episode identity — then states the timeline, the emission
contract, the profile, the destination and one record per frame (number, role,
file, shot, camera, source beats).

**Episode Render Manifest V1** (`living_diorama_episode_render_manifest`) binds
everything the plan bound plus the plan's own digest, and adds the environment
(Blender version, engine, device), a per-frame byte count with **two** digests
— the file, and the decompressed image stream, which is an image-content
digest and not a reproducibility claim — and an aggregate completeness block
carrying the measured witness difference. It cannot claim completeness
while missing a frame, and its witness verdict is computed from the measurement
beside it rather than asserted.

Together they make it impossible to hold a directory of images and be unsure
which episode it is, whether it is finished, or whether it is the one the plan
asked for.

### 6.1 Validity is not truthfulness

Each of the three documents — shot plan, render plan, manifest — validates on
its own. That proves nobody typed a contradiction into it. It does **not**
prove that the fields it copied out of an upstream document are the values that
document actually holds, and almost everything in a render plan is a copy: the
story, clock and catalogue it was cut against, the episode identity, the whole
timeline, and three fields of every one of the 193 frame records.

Binding a digest proves two documents were *paired*. It says nothing about
whether the pairing was honest about what it copied under that digest. So the
two kinds of check are separate, and both are required:

| Check | What it proves |
| --- | --- |
| **Standalone validation** | the document obeys its own contract |
| **Relationship validation** | the document tells the truth about another one |

`living_diorama.render_execution.render_binding` owns the second kind:

* `require_render_plan_matches_shot_plan` — every source field the plan copied
  still holds that value; the timeline is the same timeline, key for key; and
  every planned frame, **playback and witness alike**, names the shot, the
  camera and the `source_beat_ids` the shot windows actually put there. The
  witness is derived from the windows exactly as a playback frame is, so the
  one frame nobody watches is not the one whose direction can be written freely.
* `require_shot_plan_bytes` — the digest is taken over the shot plan file's
  bytes **as they are**, never over a re-serialization of what they parse to.
  Those are different claims: canonicalizing first would accept a
  pretty-printed copy, a copy with reordered keys, a copy with trailing
  whitespace — the same data written differently, and therefore a file whose
  own digest is not the one the render plan bound.
* `require_manifest_matches_plan` — the manifest may record what only a
  finished render knows (a file's length, its two digests, the environment, the
  completion verdict), and may contradict its plan nowhere.

The manifest also carries `composition_sources`, because it is the document
downstream layers are handed. Without that block a manifest could name its
episode, its direction and every file it produced while saying nothing about
which world was photographed.

The Blender executor restates all of these in the standard library, on its own
side of a boundary neither may cross, and a pure test drives both
implementations over the same mutations.

### 6.2 The timeline is provenance, not arithmetic

A clock that closes on its own arithmetic has proved only that it is *a* clock.
`1 + 25 + 119 + 48` closes on frame 193 exactly as the locked `1 + 24 + 120 +
48` does, emits the same 192 playback frames, and runs the same 8.0 seconds —
so a render plan could restate an alternate timeline, keep the canonical Motion
& Time digest it never re-derives, and satisfy every self-consistency rule in
this contract while claiming a clock its own provenance did not come from.

Both validators therefore pin the resolved clock beside the digest that
produces it, as Phase 22's applier already did. A repository test re-derives
those values from the shipped `motion_time_v1.json` under Phase 17's own
arithmetic, so the pin cannot drift away from its source without failing
loudly.

---

### 6.3 A frame file is a PNG, in the order PNG defines

A picture whose chunks carry the right types is not thereby a PNG. The format
defines an *order*, and a file that ignores it is one two decoders will disagree
about. Both readers — the engine's and the executor's — enforce the arrangement:

* the signature, then chunks with valid declared lengths and correct CRCs
* `IHDR` exactly once, **first**, with a body of exactly 13 bytes
* `IEND` exactly once, **last**, with an empty body, ending at end of file
* at least one `IDAT`, all of them consecutive, between the two
* no unrecognised **critical** chunk anywhere — a critical chunk can change what
  the image data means, so a reader that does not understand one must not claim
  to have read the picture

Ancillary chunks stay welcome: Blender writes `tEXt`, `pHYs`, `oFFs` and `eXIf`,
and those may vary without the picture changing. That is exactly why
`image_sha256` covers the decompressed image stream rather than the file.

The executor used to carry two parsers with two different ideas of validity —
one checked CRCs and lengths, the other checked neither — so the answer to "is
this a valid frame" depended on which function was asked. There is now one
closed parser per side, and a single corpus of malformed files is driven through
every reader on both sides.

---

### 6.4 Three records of one frame, and they must all agree

A finished render directory holds three accounts of what each frame is: the
checkpoint, the manifest, and the file itself. Each records the same three
facts — `bytes`, `sha256`, `image_sha256` — and there is no reading of a
directory in which two of them disagree and both are true.

So all three are compared, on every field:

* where the checkpoint and the manifest both speak about a frame, they must say
  the same thing about it;
* every record that exists is compared against the **file**, independently. One
  record may not stand in for another.

V4 compared the checkpoint and the manifest on `sha256` alone, and then let the
checkpoint's entry answer for the manifest's. A manifest could therefore carry
the correct digest beside a wrong byte count or a wrong image digest, be used to
declare the render finished, and never once be compared to the frame it
described. That is what "validated completely" has to exclude.

A checkpoint from an interrupted run legitimately knows about fewer frames than
a finished manifest — that is what resuming means. Holding fewer is not a
contradiction; disagreeing about a shared one is.

### 6.5 The image data is exactly one compressed stream

A PNG's `IDAT` chunks concatenate to one zlib stream. `zlib.decompress` stops at
the end of the first stream and returns what it found, so a valid stream
followed by arbitrary bytes — or by a second complete stream — decompresses
happily and yields a correct-looking picture.

Both decoders now drive the decompressor explicitly and ask it three questions
afterwards: did the stream reach its own terminator, is there anything after it,
and was anything left unconsumed. Truncation fails the first; trailing bytes
fail the second.

The check applies to the **joined** payload of every `IDAT`, never one chunk at
a time — a real frame here carries 108 to 130 of them and the stream runs across
all of them. Applied per chunk it would refuse every frame this phase has ever
produced.

`image_sha256` could not have caught this: it covers the *inflated* stream, and
inflation stops at the same place, so a frame with trailing bytes hashes
identically to one without them. Only the decompressor's own state knows where
the stream ended.

---

## 7. Determinism — precisely what is and is not claimed

**Claimed, and proven.** The render plan's bytes are deterministic: identical
inputs in, identical bytes out, under any hash seed. The manifest's
serialization is deterministic given identical recorded results. Frame naming,
frame order and the destination identity are deterministic. Everything this
layer *decides* is reproducible; what it *photographs* is measured instead.

**Measured, and therefore stated rather than assumed.** Rendered *frames* do
not reproduce byte for byte, even on the same machine in the same session, for
two separate reasons. Blender stamps the render's wall-clock date and duration
into the PNG's text chunks, so the files always differ. And Cycles on a GPU is
stochastic — adaptive sampling and denoising do not reduce to the same
floating-point result twice — so the pixels differ slightly too: the suite
measures **0.023 levels** of mean difference between two renders of one
unchanged frame, and the profile documents a 0.5-level noise band around that.
Pinning the sampling seed narrows the band; it does not close it.

Each frame therefore carries two digests, and neither is a reproducibility
claim: `sha256` identifies the file that exists, and `image_sha256` covers the
decompressed image stream so an auditor can tell a replaced frame from one
that was merely re-stamped. Knowing the noise band is what makes the boundary
measurement meaningful — a 0.08-level difference at the loop seam is one frame
of motion above the noise, not an artefact of it.

**Not claimed.** Cross-hardware or cross-version reproducibility. A different
GPU, driver, denoiser build or Blender version may produce different images for
the same scene, and nothing here has tested that. The manifest records the
Blender version, engine and device precisely so a reader can tell what these
pixels are: it proves *these* assets were produced by *that* environment, and
promises nothing about another.

---

## 8. Refusals

| Condition | Response |
| --- | --- |
| Plan carrying a profile that is not the approved one | refused, absolutely, before anything is applied |
| Plan built for a different shot direction plan than the one supplied | refused |
| Shot plan file whose **exact bytes** are not the ones the plan bound | refused, before it is parsed |
| Plan whose copied source, timeline, shot, camera or beat fields disagree with its direction | refused |
| Plan restating a timeline the bound Motion & Time source does not resolve to | refused |
| Plan naming a camera anchor outside the approved set | refused by both validators |
| Plan whose episode or previous episode is negative | refused by both validators |
| Camera catalogue that is not the one this render was planned for | refused before the world is composed |
| Manifest contradicting the plan it binds, in any copied field | refused by the audit |
| A frame file that is not an image of this render's profile | refused, whatever its digests say |
| A PNG whose chunks are in an illegal arrangement | refused by both readers on both sides |
| A freshly rendered frame that does not fully decode | refused **before** it is published under its final name |
| A partial render resumed under a different Blender, engine or device | refused; one directory holds one environment |
| A complete render re-run under a different environment | verified and reported; its manifest is never re-attributed |
| A checkpoint or manifest that is stale, malformed or contradictory | refused, never repaired |
| A checkpoint and a manifest that disagree about any frame result field | refused by both halves |
| A record that disagrees with the frame file it describes | refused, whichever record it is |
| Any unrecognised entry at the render directory's top level | refused by both halves |
| This phase's own `.partial` or `*.writing` litter | refused as a finished render, named as an interrupted run |
| Image data carrying anything after the end of its compressed stream | refused by both decoders |
| A malformed image | reported as a problem, never raised as a traceback |
| Any file anywhere in the render directory that nothing accounts for | refused |
| Scene whose colour management or clock differs from the profile | refused, never overridden |
| Scene missing a prior layer, or the wrong size | refused; a half-built world is never photographed |
| Active camera at a frame is not the directed one | refused |
| Render directory holding a plan with a different digest | refused; nothing deleted to make room |
| An existing frame whose bytes no longer match the checkpoint | refused, never re-rendered over |
| A rendered file that is not a complete PNG | refused before publication |
| More than one file produced for one frame | refused |
| Any planned frame missing | no manifest is written |

Nothing is repaired.

---

## 9. Atomicity and resume

Each frame is rendered into a `.partial` directory this phase owns and empties
first, so Blender's own filename suffixing cannot leave a numbered stub that is
later mistaken for the real file. Exactly one file must appear; it must parse
as a complete PNG with every chunk CRC intact — which is what catches a file
that was still being written when a render died — and only then is it moved
into place under its canonical name with an atomic replace.

After each published frame the checkpoint is rewritten atomically (temp file,
flush, fsync, rename), recording the plan digest, the profile digest, the
environment and every completed frame's size and digest.

On resume, a frame is skipped **only** when the checkpoint recorded it under
this plan and profile *and* the file on disk still hashes to what was recorded.
Existence is never treated as evidence of completeness. A crash after 120
frames costs 0 verified frames; a tampered or truncated frame costs the run,
loudly.

A directory holding a complete, matching manifest is verified and reported, not
re-rendered.

---

### 9.1 One render directory, one execution environment

The manifest names a single Blender version, a single engine and a single
device for the whole render. That sentence is only true if every frame in the
directory came from that one environment — so the environment is part of what a
resume has to agree with, exactly as the plan digest and the profile digest are.

* A **partial** render is resumable only by the environment that began it.
  Resuming under a different Blender or a different device would reuse the first
  machine's frames, render the rest here, and then sign the whole episode with
  this machine's name. There is no honest manifest for that directory, so the
  resume is refused and the render starts in a fresh one.
* A **complete** render is different: nothing is reused because nothing is
  rendered. Re-running the command verifies the directory and reports it. The
  existing manifest is not reassembled, not re-timestamped, and above all not
  re-attributed to whichever machine happened to run the check. A verification
  run is a no-op on authoritative records.

### 9.2 Resume evidence is validated before it is believed

Two files can let a resume skip work: the checkpoint, which says a frame was
already published, and the manifest, which says the render already finished.
Both are now validated in full before either is allowed to vouch for anything.

The checkpoint is held to an exact contract — its keys, its plan and profile
digests, its environment, and per frame a byte count and two well-formed digests
for a frame number this plan actually contains. The manifest is validated
against the plan beside it, field by field, including its completeness
arithmetic.

A stale, malformed or contradictory record is a **refusal**, never a repair. A
manifest naming a different story plan is not corrected into naming the right
one; the directory is refused and left exactly as it was found. And a reused
frame is re-verified through the same complete gate a freshly rendered frame
passes on its way to publication.

---

## 10. Running it

```
python -m living_diorama.cli.build_render_plan \
    --shot-plan shot_direction_plan_v1.json \
    --story-plan episode_story_plan_v1.json \
    --output episode_render_plan.json

blender --background --factory-startup \
    --python visual/blender/scripts/render_episode.py -- \
    --render-plan episode_render_plan.json --shot-plan shot_direction_plan_v1.json \
    --catalogue catalogue.json --spec master_scene_v1.json \
    --production production_world_v1.json --motion motion_time_v1.json \
    --presence population_presence_v1.json --mobility daily_life_mobility_v1.json \
    --state-response state_response_v1.json \
    --before render_export_ep0.json --after render_export_ep1.json \
    --output-root renders/

python -m living_diorama.cli.verify_render --render-dir renders/episode_0000_to_0001
```

The audit is the independent half: it re-reads every byte on disk and decides
whether the manifest told the truth. It trusts nothing the renderer recorded —
it compares the manifest against the plan field by field, re-hashes every file,
**decodes all 193 images against the render profile**, refuses any entry nothing
accounts for, and recomputes the boundary measurement from the two pictures
rather than reading it out of the document being checked. Decoding the frames
is most of its two-minute runtime, and is the half a digest cannot do.

---

## 11. Known limitations

- **One quality tier.** The V1 profile is the repository's fast tier. A higher
  tier is a profile version change, which is a reviewed change.
- **No video.** The authoritative output is a lossless image sequence.
  Encoding is a later layer's responsibility, and deliberately kept out of the
  render contract so codec nondeterminism cannot contaminate it.
- **No audio, no narration, no assembly.** Explicitly downstream.
- **One transition per render.** Multi-episode presentation is not this
  layer's problem.
- **Pixel reproducibility is not claimed at all** — not across machines, and
  not across two runs on this one. §7 records what was measured.
- **Resume is per-frame, not per-sample.** A frame interrupted mid-render is
  re-rendered from the start of that frame.
- **The frame audit checks a frame's form, not its content.** Every one of the
  193 files is fully decoded and checked against the render profile, so a
  substitute of the wrong size, colour type, bit depth or interlacing is
  refused however carefully the manifest's digests were rewritten to match it.
  A substitute that is a well-formed image of *exactly* this profile at exactly
  this size is **not** caught: there is no reference for a frame's pixels to be
  compared against, because re-rendering does not reproduce them byte for byte
  (§7). The honest boundary is the frame's form.
- **`unconsumed_tail` is asserted but cannot fire.** The decompressor is driven
  without a `max_length`, so it always consumes what it is given. The assertion
  is kept because it is the third of three questions that together mean "exactly
  one stream", and a future caller that did pass a length would need it.
- **There is no decompression size cap.** A hostile IDAT could inflate far
  beyond the scanline payload. What stops it being *accepted* is the exact
  size check that follows -- the inflated stream must be precisely
  ``(width * 3 + 1) * height`` bytes -- but the memory is allocated before that
  check runs, so a deliberately crafted frame can still cost more to reject than
  it should.
- **A render cannot be moved between machines.** One directory holds one
  execution environment, so a partial render started on one machine and
  finished on another is refused rather than mixed. There is no merge path and
  deliberately so: the alternative is a manifest that names one machine for
  pixels several produced. Restarting in a fresh directory is the answer.
- **A frame is verified twice on publication.** ``require_verified_frame``
  decodes the file through ``png_facts`` and again through ``png_pixels``. That
  is a cost, not a correctness problem, and it buys the property that a frame
  reaching its final name has been fully decoded at least once.
- **Ancillary PNG chunks are accepted without being understood.** ``tEXt``,
  ``pHYs``, ``oFFs`` and ``eXIf`` pass through unread, which is what PNG intends
  and what lets Blender stamp a render date without changing the picture. A
  hostile ancillary chunk is therefore carried in the file and covered by
  ``sha256`` but not by ``image_sha256``.
- **Decoding 193 frames costs about two minutes.** The decoder is pure standard
  library, and real frames are dominated by Paeth-filtered rows, which have no
  whole-row shortcut. Filters None and Up do, and take it.
- **The render directory is protected against accident, not against an
  adversary.** Frames, checkpoint and manifest are unsigned files in one
  writable directory. The executor refuses every inconsistency it can see — a
  frame that changed, a manifest that contradicts the checkpoint, a file
  nothing accounts for — but someone able to rewrite all three consistently
  can produce a self-consistent lie. Detecting that would need signing, which
  this layer does not do.
- **Provenance is relative above the profile.** The render profile, the six
  composition sources, the resolved clock and its source digest are pinned
  absolutely, and Phase 22 pins the camera catalogue absolutely. The story plan,
  the episode identity and the export digests are bound to each other rather
  than to a reviewed registry, so a forged chain that is self-consistent
  *across every one of these documents at once* would still pass. V3 narrowed
  what "self-consistent" has to mean — a forgery must now agree with the shot
  plan's exact bytes, its copied source fields, its timeline and its per-frame
  direction — but it did not close the class. That is a property of the whole
  document pipeline, not of this layer alone.
- **Frame files are not fsynced** before the checkpoint records their digest.
  After a power loss a frame may disagree with the fsynced checkpoint; the
  resume then refuses, which is the safe direction.
