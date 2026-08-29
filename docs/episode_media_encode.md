# The Final Episode Media (V1)

> Phase 35. **MORE EXECUTION, NOT NEW TRUTH.** The audited pre-encode
> assembly and the serialized captions, projected through one pinned FFmpeg
> profile into exactly one watchable episode file beside byte-exact caption
> sidecars and two provenance manifest copies -- digest-recorded at
> production and re-verified on every read.

## 1. Why this layer exists

Phase 33 closed the pre-encode assembly question: a locked presentation
realized onto locked pixels, in one self-contained directory. Phase 34 closed
the caption question: the locked captions serialized into byte-sealed SRT and
WebVTT sidecars. Neither produces anything a viewer can press play on. This
layer is that join: it projects the locked frames and the locked samples --
and the serialized captions -- through one reviewed FFmpeg execution profile
into one watchable MP4, published beside byte-exact caption sidecars, two
provenance manifest copies, and its own manifest, in one self-contained
final-media directory.

Phase 33's own doc said it plainly: *"No caption serialization, no encode, no
mux, no container, no packaging. Explicitly downstream and explicitly unowned
by any locked phase."* Phase 35 is that explicitly-downstream layer, owning it
as execution only: it decides nothing the locked phases did not already
determine.

## 2. Ownership

**PHASE 35 PROJECTS LOCKED TRUTH INTO ONE WATCHABLE FILE. IT CREATES NO TRUTH.**

It owns: the projection (one pinned FFmpeg profile over the locked frames and
the captured audio snapshot); the adapter (the audited Phase 34 sidecars
carried byte-exact into the final directory); the provenance (exact-byte
copies of the two consumed manifests, digest-bound in its own manifest); the
tool gates (version and capability laws); and the self-contained, tool-free
audit that re-reads the final directory and decides whether the manifest told
the truth.

It does **not** own: which pixels a frame holds (Phase 23), what the episode
sounds like (Phase 31), narration wording or cue timing (Phases 26/32), or
caption display. There is no burn-in, no rasterized text, no styled overlay,
no muxed caption track: the MP4 carries exactly **1 video stream and 1 audio
stream**, nothing else. The sidecars are separate files, byte-exact,
same-basename as the episode file; a player auto-loading them is a viewer
convenience, never a contract. Nothing in the package spawns a tool -- the
one tool-touching entry point of the repository's media side lives outside
it, in `media/ffmpeg/scripts/encode_episode.py`.

## 3. Inputs

Two audited directories are consumed, and both are audited again, whole,
before anything else happens: the Phase 33 assembly directory (via
`audit_media_assembly_directory`) and the Phase 34 caption serialization
directory (via `audit_caption_serialization_directory`). Reusing the upstream
audits whole is the artifact-truth precedent Phase 30 set: this phase never
re-implements an upstream audit, it *runs* it.

The render dimensions are not read from any document's self-declared field:
the manifest's `render` block is proven against the in-code render profile
document the digest chain names (`render_profile_sha256`), so a dimension is
derived, never invented. Only after both upstream audits pass does the run
begin its own staging.

## 4. `media_encode_profile_v1`

The one reviewed projection profile, built by `build_media_encode_command` as
an exact tuple from authoritative integers alone. The logical argv, with the
two placeholder tokens being the only path material:

```
ffmpeg -nostdin -hide_banner -loglevel error
  -f image2 -framerate <fps> -start_number 1
  -i {ASSEMBLY_DIR}/presentation/frame_%07d.png
  -i {STAGING}/source_audio.wav.encoding
  -map 0:v:0 -map 1:a:0
  -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p
  -threads:v 0 -frames:v <presentation_frames_total> -fps_mode:v passthrough
  -c:a aac -b:a 128k -ar <audio_sample_rate_hz> -ac <audio_channels>
  -map_metadata -1 -fflags +bitexact -flags:v +bitexact -flags:a +bitexact
  -movflags +faststart -f mp4 {STAGING}/<id>.mp4.encoding
```

Flag by flag: `-threads:v 0` is output-scoped automatic threading -- no
thread-count determinism is claimed anywhere, because the projection is
class B; `-fps_mode:v passthrough` keeps the input rate authority;
`-map_metadata -1` and the bitexact trio strip host and build metadata;
`-frames:v` pins the exact frame count.

Deliberately absent, each absence decision-bearing: `-r` (the input
`-framerate` is the sole rate authority), `-vsync` (removed in modern
FFmpeg; it would hard-error), `-shortest` (both streams are exactly
`presentation_frames_total / fps` seconds by upstream law), any trimming,
scaling or filter (no pixel mutation), `-y` (a fresh staging temp never
pre-exists), and any pre-input thread option (FFmpeg option scoping is
file-sensitive). `-f mp4` is explicit *everywhere* the container matters,
including the preflight and the decode, because container inference from a
filename is never relied on. `+faststart` is load-bearing: it moves the
`moov` atom to the front so the single-capture pipe probe can read the file
as a stream without seeking.

## 5. The audio snapshot

The encoder never reopens the assembly's WAV path. At run start the track is
read exactly once, digest-verified against the Phase 33 manifest, and written
into staging as `source_audio.wav.encoding` -- the single captured observation
the encoder consumes. A WAV swapped during the encode can no longer reach the
encoder at all: the audio-input TOCTOU closes outright. The snapshot is
re-hashed after the encode, deleted before the terminal staged audit, and
NEVER appears in a published final directory.

## 6. The real-geometry preflight

Before any real encode, the run proves the exact encode code path on the
selected build: a tiny `testsrc2` video is encoded under a byte-identical
output-side profile (same codecs, preset, CRF, pixel format, threading,
bitexact trio, faststart, explicit `-f mp4`) against a self-built canonical
WAV -- a 44-byte-header PCM16 silence built by `preflight_wav_bytes` to the
locked clock's own geometry, exactly `audio_samples_total` zero samples at the
clock's rate and channel count (720,000 samples, 24 kHz mono, for real EP1),
whose AAC remainder geometry is
`703 x 1024 + 128`: 703 complete AAC frames of 1024 samples plus a 128-sample
tail, the worst realistic remainder the priming window must absorb. If the
preflight cannot satisfy the exact video-duration law on the known geometry,
the build is refused before any real encode -- the refuse-the-build law.

## 7. The single-observation MP4

The tool-written encode temporary is fsynced, then captured exactly once.
Everything downstream consumes that one captured byte string and never
reopens the path: the probe receives it through `pipe:0`, the decode receives
the same bytes through `pipe:0`, and the published episode file is written
from the captured bytes, then re-read, and its digest must equal the captured
digest exactly. Reopening a path is exactly the TOCTOU seam the single-capture
law exists to close.

Residual windows are stated honestly: the window between the tool writing the
temporary and this phase fsyncing and capturing it is protected against
accident, not against an adversary.

## 8. The decisive decode closure

Length is the closure, and it is exact to the sample: the captured bytes must
decode back to precisely the locked `audio_samples_total` -- 720,000 samples
on the canonical clock -- as `len(pcm) // (2 * channels)` under the locked
PCM16 law, with no tolerance and no fallback. One missing or surplus sample,
and a fortiori one presentation frame's worth, refuses the build.

The 2048-sample AAC priming window (encoder delay 1024 plus final-frame
padding) is deliberately demoted to a **descriptive** observation: a
container-metadata plausibility check on `duration_ts` and stream start,
wider than one presentation frame of samples, so it closes nothing. Length,
not content: the closure proves the episode's length survived the projection,
and says nothing about the picture -- the MP4's pixel content is class B,
attested at production and re-verified as bytes on every read.

## 9. Post-encode source stability

A new law for this phase: the run re-reads the assembly's frames **three
times per run** -- once when auditing the assembly, once when the encoder
consumes them, and once after the encode -- and the post-encode read must
still match the audited bytes. The frames are never modified; the residual
window between the encoder's last read and the post-encode re-read is stated
as what it is: a mutate-read-restore window whose honest residual is that an
attacker who swaps frames mid-encode can do so once, and the post-encode
re-read catches it.

## 10. The manifest

The Episode Media Encode Manifest is one canonical JSON document with exactly
ten blocks. Truth classes, per Correction E:

- **byte-reprovable**: `source` (both consumed manifests' digests and schema
  versions, the episode identity), `clock` (the restated Phase 33 clock,
  re-closed whole), `video` and `captions` (lengths and SHA-256 of the
  published bytes), `completeness` (counted vs expected frames);
- **code-reprovable**: `render` (proven against the digest-named render
  profile), `invocation.logical_argv` (rebuilt from the manifest's own clock,
  streams and identity through the one frozen builder and required
  byte-equal);
- **tool-attested**: `streams` (the frozen 21-key block) and the two recorded
  version lines -- internally proven by the tool-free validator, never
  re-probed by it.

The invocation is **path-neutral**: the recorded `logical_argv` carries the
`{ASSEMBLY_DIR}` and `{STAGING}` tokens verbatim, the canonical bytes carry
no backslash and no drive path, and no runtime root's string may appear
anywhere in them. There is **no environment block**: no hostname, no PID, no
wall clock. The two tokens are the only non-literal path prefixes canonical
output may carry; the executor substitutes real roots only in the spawned
argv, which lives in runtime logs, never in canonical bytes.

## 11. The pure audit vs the tool-bearing no-op

Two halves, and they never blur. The self-contained audit
(`audit_media_encode_directory`, and the `verify_media_encode` CLI around it)
is **tool-free**: it re-reads every byte on disk, re-validates both
provenance copies under their locked upstream schemas, re-hashes every bound
digest, re-proves the identity, clock and lineage joins and the
directory-name law, rebuilds the logical invocation, refuses any unaccounted
entry, and succeeds after every source location has disappeared. It never
probes and never decodes: the recorded stream facts remain tool-attested.

The tool-bearing executor no-op is Correction F's surface: an existing final
directory is re-probed and re-decoded by the real tools before it is accepted
as already-complete. Version equality is deliberately **not** a no-op gate --
two builds of the same tools on the same bytes are the honest precondition,
never the verdict; the verdict is the re-probe and the re-decode.

## 12. Commands

The executor -- the one approved subprocess site of the repository's media
side -- consumes the two audited directories and writes under an output root:

```
python media/ffmpeg/scripts/encode_episode.py \
    --assembly-dir media_assembly/episode_0000_to_0001 \
    --captions-dir caption_serialization/episode_0000_to_0001 \
    --output-root final_media/
```

The verifier is the independent, TOOL-FREE half, accepting exactly one
directory:

```
python -m living_diorama.cli.verify_media_encode \
    --final-dir final_media/episode_0000_to_0001
```

There is no `--ffprobe` flag and no `--assembly-dir` flag on the verifier: it
is self-contained by design, and it succeeds after every upstream source
location has disappeared.

## 13. Known limitations

- **One episode.** As every layer upstream.
- **MP4 bytes are class B.** Digest-recorded at production and re-verified on
  every read, but cross-machine byte identity is deliberately not claimed:
  x264 output is not pinned to one build's arithmetic, and same-machine
  identity is evidence, never a contract.
- **Color is untagged, V1 non-goal.** The `yuv420p` projection is an
  explicit, recorded choice; color management beyond it is out of scope.
- **CI runs no tool.** No CI job invokes ffmpeg or ffprobe; the tool-bearing
  half is proven by its pure laws in CI and exercised by the runtime
  acceptance where the reviewed tools exist.
- **No burn-in, no muxed caption track, no styling.** Exactly one video and
  one audio stream; caption display is nobody's phase.
