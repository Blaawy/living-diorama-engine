"""The Phase 23 render contract: what is emitted, how it is named, how it looks.

Three things live here and nothing else: the **frame emission contract** that
decides which of Phase 17's semantic frames become playback assets, the
**render profile** that fixes the presentation settings a production render
runs under, and the **naming and destination** rules that make a render
identifiable on disk.

RENDER EXECUTION REALIZES A DIRECTED EPISODE. IT DIRECTS NOTHING.

Every frame's camera comes from the locked Phase 22 Shot Direction Plan, every
frame number comes from the locked Phase 17 clock, and this module invents
neither. It owns exactly one new decision -- how many of those frames are
photographed as playback -- and it owns it explicitly, with the arithmetic
written down, because the alternative is an episode whose runtime quietly
disagrees with the timeline it was cut against.

This module imports only the standard library. It never imports ``bpy``: the
profile is data that a Blender executor is handed and must verify, exactly as
Phase 22 hands its camera catalogue across the same boundary.
"""

import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, cast

RENDER_PLAN_FORMAT: Final = "living_diorama_episode_render_plan"
"""The format tag every episode render plan declares."""

RENDER_MANIFEST_FORMAT: Final = "living_diorama_episode_render_manifest"
"""The format tag every episode render manifest declares."""

RENDER_PLAN_SCHEMA_VERSION: Final = 1
"""The render plan schema version this build reads and writes."""

RENDER_MANIFEST_SCHEMA_VERSION: Final = 1
"""The render manifest schema version this build reads and writes.

Independent of the plan version: a manifest records what a render produced and
may need to grow fields a plan never has.
"""

SUPPORTED_SHOT_PLAN_SCHEMA_VERSION: Final = 1
"""The Phase 22 shot plan schema version this layer knows how to render."""

CANONICAL_MOTION_TIME_SHA256: Final = (
    "bfcbfcfd8d2b33f0ca8a0bc51655a1028babc601a73cdd42ca3c8caf3f9da673"
)
"""The locked Phase 17 Motion & Time Spec every render is timed against.

Restated here rather than imported from Phase 22 so the Blender executor -- which
may not import the engine -- pins the identical constant, and so the timeline pin
below has its source digest sitting beside it.
"""

DIRECTOR_V4_MOTION_TIME_SHA256: Final = (
    "a821049b648c0d37a9bc5c6cbc74142cffb0c21a817ad3e2b10764dfeaa4079c"
)
"""The reviewed Director V4 Motion & Time Spec, restated beside the canonical one.

The exact bytes of ``visual/blender/config/motion_time_director_v4.json`` in the
locked tree this build was reviewed against; a repository test re-hashes the
shipped file against this constant, so it cannot drift silently.
"""

CANONICAL_RESOLVED_TIMELINE: Final[Mapping[str, int]] = MappingProxyType(
    {
        "end_frame": 193,
        "end_hold_frames": 48,
        "fps": 24,
        "start_frame": 1,
        "start_hold_frames": 24,
        "transition_end": 145,
        "transition_frames": 120,
        "transition_start": 25,
    }
)
"""The resolved Phase 17 clock, pinned beside the source digest that produces it.

A timeline that closes on its own arithmetic is not thereby the locked clock.
``1 + 25 + 119 + 48`` also closes on frame 193, emits the same 192 playback
frames and runs the same 8.0 seconds -- so a render plan could restate an
alternate clock, keep the canonical Motion & Time digest it never re-derives,
and every self-consistency rule in this contract would hold while the document
claimed a timeline its own provenance did not come from. The plan would say one
thing and its digest chain another.

This closes that, and it is not a new idea: Phase 22's Blender applier already
pins the identical dict for exactly this reason. Phase 23 restates it rather
than importing it, because the executor across the Blender boundary can import
neither Phase 22 nor this module. A repository test re-derives these values from
the shipped ``motion_time_v1.json`` under Phase 17's own arithmetic and proves
all three copies agree, so the pin cannot drift away from its source without
failing loudly.
"""

DIRECTOR_V4_RESOLVED_TIMELINE: Final[Mapping[str, int]] = MappingProxyType(
    {
        "end_frame": 319,
        "end_hold_frames": 18,
        "fps": 24,
        "start_frame": 1,
        "start_hold_frames": 24,
        "transition_end": 301,
        "transition_frames": 276,
        "transition_start": 25,
    }
)
"""The resolved Director V4 clock: 314 playback frames at 24 fps (13.0833 s).

Restated beside its source digest exactly as the canonical clock is, and proved
against the shipped ``motion_time_director_v4.json`` by the same re-hash test.
"""

REVIEWED_CLOCKS: Final[Mapping[str, Mapping[str, int]]] = MappingProxyType(
    {
        CANONICAL_MOTION_TIME_SHA256: CANONICAL_RESOLVED_TIMELINE,
        DIRECTOR_V4_MOTION_TIME_SHA256: DIRECTOR_V4_RESOLVED_TIMELINE,
    }
)
"""The closed set of reviewed clocks: reviewed digest -> the clock it resolves to.

A plan is admitted only when its bound digest is one of these AND the clock it
restates is exactly what that digest resolves to -- a document cannot claim one
clock while binding another, and any digest outside this closed set is refused
outright, however internally consistent.
"""

# ---------------------------------------------------------------------------
# Frame emission contract
# ---------------------------------------------------------------------------

ROLE_PLAYBACK: Final = "playback"
"""A frame that belongs to the episode a viewer watches."""

ROLE_WITNESS: Final = "witness"
"""The terminal boundary frame, rendered as evidence and never played back.

See :func:`derive_emission` for why exactly one frame carries this role.
"""

FRAME_ROLES: Final = frozenset({ROLE_PLAYBACK, ROLE_WITNESS})
"""Every role a rendered frame may declare."""

FRAME_NAME_TEMPLATE: Final = "frame_%04d.png"
"""Deterministic, sortable, semantic frame naming.

The number is the **semantic** Phase 17 frame, not a counter, so a file name
is traceable back to the clock without consulting anything else. Four digits
covers the locked 193-frame timeline with room to spare; a longer timeline
would widen the field and that would be a reviewed schema change, not a silent
reformat.
"""

FRAMES_DIRECTORY: Final = "frames"
"""Where playback frames are written, relative to the render directory."""

WITNESS_DIRECTORY: Final = "witness"
"""Where the boundary witness frame is written, relative to the render directory."""

PARTIAL_DIRECTORY: Final = ".partial"
"""Where a frame is written while Blender is still producing it.

A file under this name is by construction not a finished asset, so an
interrupted render leaves nothing that can be mistaken for one.
"""

RENDER_PLAN_FILENAME: Final = "episode_render_plan.json"
"""The plan copy that identifies which render a directory holds."""

RENDER_MANIFEST_FILENAME: Final = "episode_render_manifest.json"
"""Written only when every planned frame exists and verifies."""

RENDER_CHECKPOINT_FILENAME: Final = "render_checkpoint.json"
"""Resume state. Not a canonical artifact: it describes progress, not truth."""

FRAME_RESULT_FIELDS: Final = ("bytes", "sha256", "image_sha256")
"""Everything a record says about a frame file that the file itself can answer for.

Named once so every comparison -- checkpoint against manifest, either against
the file on disk -- covers the same three fields. V4 compared the checkpoint and
the manifest on ``sha256`` alone, which let a manifest carry a correct digest
beside a wrong byte count and never be contradicted.
"""

CHECKPOINT_KEYS: Final = frozenset(
    {"render_plan_sha256", "render_profile_sha256", "environment", "frames"}
)
"""Exactly the keys a render checkpoint carries."""

WRITING_SUFFIX: Final = ".writing"
"""The suffix the atomic writer gives a document while it is still being written.

Named here because two different readers have to be able to tell one of these
apart from a file nobody recognises. A ``.writing`` file is this phase's own
in-flight temporary: it means a run died between opening the file and renaming
it over the real one, which is a *recoverable* state -- the real document is
either still the previous one or not there yet, and neither is corrupt. A file
this phase does not recognise means something else has been in the directory,
and that is not recoverable by guessing.

Neither is deleted. The difference is only in what the refusal says and in
whether the directory can still be called finished.
"""

RENDER_DIRECTORY_ENTRIES: Final = frozenset(
    {
        RENDER_PLAN_FILENAME,
        RENDER_MANIFEST_FILENAME,
        RENDER_CHECKPOINT_FILENAME,
        FRAMES_DIRECTORY,
        WITNESS_DIRECTORY,
    }
)
"""Everything a finished render directory may contain, at its top level.

Exactly five names: the plan that says what this render is, the manifest that
says what it produced, the resume state, and the two frame directories. A
finished render owns nothing else -- notably not ``.partial``, which the
executor removes as each frame is published, so one surviving here means a
render died mid-frame and the directory is not the finished thing it appears
to be.
"""

RENDER_NOISE_TOLERANCE: Final = 0.5
"""How far two renders of the SAME frame may differ, in levels out of 255.

Cycles on a GPU is stochastic: adaptive sampling and denoising do not reduce to
the same floating-point result twice, so an unchanged scene rendered twice
measures about 0.023 levels apart here. Pinning the sampling seed narrows that
band but does not close it. This tolerance is the band the renderer is allowed
to wander in; anything wider means the scene changed, not the sampler.
"""

WITNESS_DIFFERENCE_TOLERANCE: Final = 1.0
"""How far the boundary witness may differ from the last playback frame.

Mean absolute difference per colour sample, in levels out of 255, measured
between the two rendered images. The number is calibrated, not guessed: on
the canonical leg the measured difference is 0.08 -- one frame of residual
pedestrian motion, because Phase 19's movers keep walking through the end
hold that Phase 17 holds still, plus the renderer's own 0.02 of noise --
while two genuinely different frames of the same episode measure 47.5. A
tolerance of one level sits an order of magnitude above both sources of
residue and more than an order below a real cut, so it separates "the episode
ended where it should" from "the episode was cut off mid-action" without
pretending the two frames are the same picture.
"""


def classify_render_directory_entry(name: str, *, is_directory: bool = False) -> str:
    """Say what a top-level entry in a render directory is.

    Three answers, and the difference between the last two decides whether a
    human should go looking for an intruder:

    * ``"owned"`` -- one of the five entries a finished render owns.
    * ``"partial"`` -- this phase's own litter from an interrupted run: the
      ``.partial`` scratch *directory*, or a ``.writing`` temporary of one of
      the documents this phase writes atomically. Recoverable, and not evidence
      of anything hostile, but proof the directory is not finished.
    * ``"foreign"`` -- anything else.

    The name alone is not enough to tell those apart. A file called
    ``evil.writing`` is not this phase's debris, and neither is a *directory*
    called ``x.writing``; both were classified as owned litter when this matched
    on the suffix by itself. So a ``.writing`` entry counts as ours only when it
    is a file whose remaining name is a document this phase actually writes, and
    ``.partial`` counts only when it is a directory.

    Nothing is deleted on the strength of this. It decides what the refusal says.
    """
    if name in RENDER_DIRECTORY_ENTRIES:
        return "owned"
    if name == PARTIAL_DIRECTORY:
        return "partial" if is_directory else "foreign"
    if not is_directory and name.endswith(WRITING_SUFFIX):
        written = name[: -len(WRITING_SUFFIX)]
        if written in {RENDER_PLAN_FILENAME, RENDER_MANIFEST_FILENAME, RENDER_CHECKPOINT_FILENAME}:
            return "partial"
    return "foreign"


def derive_emission(timeline: Mapping[str, object]) -> dict[str, object]:
    """Return which frames this episode emits, derived from Phase 17's own clock.

    **The contract, and why.** Phase 17 declares a timeline as a start frame
    plus three phase lengths, and refuses itself unless
    ``start + start_hold + transition + end_hold == end_frame``. On the locked
    clock that is ``1 + 24 + 120 + 48 == 193``. Those phase lengths are frame
    counts, and they only add up if each phase owns a half-open frame range:

    * start hold ``[1, 25)`` -- frames 1..24, exactly ``start_hold_frames``
    * transition ``[25, 145)`` -- frames 25..144, exactly ``transition_frames``
    * end hold ``[145, 193)`` -- frames 145..192, exactly ``end_hold_frames``

    Their sum is 192 frames, and Phase 17 computes the episode's duration the
    same way -- ``(end_frame - start_frame) / fps`` -- which is where the
    documented 8.0 seconds comes from. Frame ``end_frame`` is the terminal
    boundary those ranges close against: the 193rd frame number, not a 193rd
    frame of content.

    So the episode emits 192 playback frames and runs for exactly the duration
    Phase 17 declares. Emitting 193 would make the episode 8.0416 seconds long
    while every upstream document still said 8.0, and it would end on the loop
    seam: ``end_frame`` is the state the next leg opens on, so a run of
    episodes would show that picture twice at every join.

    The boundary frame is still **rendered**, once, as a witness: it is the
    frame at which Phase 17 proves endpoint equivalence and Phase 22 proves
    loop closure. It is not a duplicate of the final playback frame, and the
    contract does not pretend otherwise -- Phase 17's end hold is still, but
    Phase 19's movers walk through it, so the two frames measure 0.06 to 0.08
    levels apart. A render that shows its boundary frame differing from its
    last playback frame by only that measured residue, inside the tolerance,
    has proved the emission contract rather than asserted it.

    Args:
        timeline: The Phase 22 plan's timeline block, already validated.

    Returns:
        The emission block: first and final playback frame, playback frame
        count, the witness frame, the playback fps and the exact duration.

    Raises:
        TypeError: If a timeline value is of the wrong exact type.
        ValueError: If the timeline's phase lengths do not close on its own
            end frame, or the emitted span is empty.
    """
    values: dict[str, int] = {}
    for key in (
        "start_frame",
        "end_frame",
        "fps",
        "start_hold_frames",
        "transition_frames",
        "end_hold_frames",
    ):
        value = timeline.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"timeline {key} must be an int, got {value!r}")
        values[key] = value

    start = values["start_frame"]
    end = values["end_frame"]
    phases = values["start_hold_frames"] + values["transition_frames"] + values["end_hold_frames"]
    if start + phases != end:
        raise ValueError(
            f"timeline phases {values['start_hold_frames']} + {values['transition_frames']} + "
            f"{values['end_hold_frames']} do not close on end_frame {end} from start_frame "
            f"{start}; the emission contract is derived from that arithmetic and cannot be "
            "guessed"
        )
    if phases < 1:
        raise ValueError(f"a timeline emitting {phases} frames has no episode in it")
    fps = values["fps"]
    if fps < 1:
        raise ValueError(f"playback fps must be at least 1, got {fps}")

    return {
        "first_frame": start,
        "final_frame": end - 1,
        "frame_count": phases,
        "witness_frame": end,
        "playback_fps": fps,
        "playback_seconds": round(phases / fps, 6),
    }


def frame_filename(frame: int) -> str:
    """Return the deterministic file name for one semantic frame.

    Raises:
        TypeError: If the frame is not an int.
        ValueError: If the frame is not positive or would not fit the field.
    """
    if isinstance(frame, bool) or not isinstance(frame, int):
        raise TypeError(f"frame must be an int, got {frame!r}")
    if frame < 1:
        raise ValueError(f"frame must be positive, got {frame}")
    if frame > 9999:
        raise ValueError(
            f"frame {frame} does not fit the four-digit naming field; widening it is a "
            "reviewed schema change"
        )
    return FRAME_NAME_TEMPLATE % frame


def render_id(*, mode: str, episode: int, previous_episode: int | None) -> str:
    """Return the deterministic directory name for one episode's render.

    Two different legs can never collide, and the same leg always lands in the
    same place -- so a re-run resumes its own render instead of scattering
    copies, and a different leg cannot be mistaken for this one by name alone.
    Identity is still proved by digest inside the directory; this is the
    human-legible half.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If the mode is unknown, an episode is negative, or the
            episode pair is not a direct succession.
    """
    if type(mode) is not str:
        raise TypeError(f"mode must be a str, got {type(mode).__name__}")
    if isinstance(episode, bool) or not isinstance(episode, int):
        raise TypeError(f"episode must be an int, got {episode!r}")
    if episode < 0:
        raise ValueError(f"episode must not be negative, got {episode}")
    if mode == "baseline":
        if previous_episode is not None:
            raise ValueError("a baseline render has no previous episode")
        return f"episode_{episode:04d}_baseline"
    if mode == "transition":
        if isinstance(previous_episode, bool) or not isinstance(previous_episode, int):
            raise TypeError(f"previous_episode must be an int, got {previous_episode!r}")
        if previous_episode < 0:
            raise ValueError(f"previous_episode must not be negative, got {previous_episode}")
        if episode != previous_episode + 1:
            raise ValueError(
                f"episode {episode} does not directly follow {previous_episode}; Phase 23 "
                "renders the transition Phase 22 directed and derives no other pairing"
            )
        return f"episode_{previous_episode:04d}_to_{episode:04d}"
    raise ValueError(f"unknown episode mode {mode!r}")


# ---------------------------------------------------------------------------
# Composition sources
# ---------------------------------------------------------------------------

COMPOSITION_SOURCE_KEYS: Final = (
    "master_scene_sha256",
    "production_world_sha256",
    "motion_time_sha256",
    "population_presence_sha256",
    "daily_life_mobility_sha256",
    "state_response_sha256",
)
"""Every locked config the composed world is built from, in phase order.

A render plan that named only its story and its exports would still be open at
the bottom: the same plan, pointed at a Motion Time document with the same
clock but a different channel window, or a mobility spec with the same vehicle
count and different speeds, produces different footage under the same identity.
These six are the complete set the production composer reads -- Phase 15's
master scene, Phase 16's production world, Phase 17's clock, Phase 18's
presence, Phase 19's mobility and Phase 20's state response.
"""

APPROVED_COMPOSITION_SOURCES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "master_scene_sha256": ("cb840ac0243582f2ef28c55c4f36f7368f2241b205835fccd5fc9048b4a7ea91"),
        "production_world_sha256": (
            "6906b8cbaa385d0df86eec9586b92ebc2990a2a2ca168e31ba7d98049e88e246"
        ),
        "motion_time_sha256": ("bfcbfcfd8d2b33f0ca8a0bc51655a1028babc601a73cdd42ca3c8caf3f9da673"),
        "population_presence_sha256": (
            "55bb06c794587d1a8bfb7238b6dc540f0071c916a9f0f95642c0d381b4cd4e75"
        ),
        "daily_life_mobility_sha256": (
            "9ca56cc6fe3c1f10b497d90e1b283e91bc64a5d4f989db8e4346b6aea0e92364"
        ),
        "state_response_sha256": (
            "89b561472ead2c2c7704e0b506ea242c4e92f9afd8f90374a164c3362230ce78"
        ),
    }
)
"""The reviewed raw-byte identity of each locked composition source.

Pinned absolutely, exactly as Phase 22 pins its clock and its camera
catalogue, and for the same reason: a plan cannot vouch for the world it was
built from if the only check is that the plan and the files agree with each
other. A repository test re-hashes the shipped files against these constants,
so the pins cannot drift away from what is on disk without failing loudly, and
the executor re-hashes the bytes it is actually handed before composing
anything.

These are digests of the files exactly as Phase 15 through Phase 20 ship them.
A document that parses, validates and means something slightly different is
still refused -- which is the point.
"""

COMPOSITION_SOURCE_FILES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "master_scene_sha256": "master_scene_v1.json",
        "production_world_sha256": "production_world_v1.json",
        "motion_time_sha256": "motion_time_v1.json",
        "population_presence_sha256": "population_presence_v1.json",
        "daily_life_mobility_sha256": "daily_life_mobility_v1.json",
        "state_response_sha256": "state_response_v1.json",
    }
)
"""Which shipped file each binding is the digest of, for the re-hash test."""

APPROVED_COMPOSITION_SOURCES_V4: Final[Mapping[str, str]] = MappingProxyType(
    {**APPROVED_COMPOSITION_SOURCES, "motion_time_sha256": DIRECTOR_V4_MOTION_TIME_SHA256}
)
"""The same locked world, composed against the reviewed Director V4 clock.

Every world source is byte-identical to the canonical bundle -- the master
scene, production world, presence, mobility and state-response documents are
untouched. Only the Motion & Time binding differs, because the V4 lane is a
longer clock over the same world, not a different world. Deriving it from the
canonical mapping rather than restating six digests keeps the two bundles from
drifting apart.
"""

APPROVED_COMPOSITION_SOURCE_SETS: Final = (
    APPROVED_COMPOSITION_SOURCES,
    APPROVED_COMPOSITION_SOURCES_V4,
)
"""The closed set of reviewed composition bundles a render plan may name."""


def composition_sources_document(*, motion_time_sha256: str | None = None) -> dict[str, str]:
    """Return the approved composition source bundle as a plain document.

    ``motion_time_sha256`` selects which reviewed bundle to return; omitting it
    returns the canonical one, so every existing caller is unchanged.
    """
    if motion_time_sha256 == DIRECTOR_V4_MOTION_TIME_SHA256:
        return dict(APPROVED_COMPOSITION_SOURCES_V4)
    return dict(APPROVED_COMPOSITION_SOURCES)


# ---------------------------------------------------------------------------
# Render profile
# ---------------------------------------------------------------------------

_OWNED_OUTPUT: Final = MappingProxyType(
    {
        "engine": "CYCLES",
        "resolution_x": 1280,
        "resolution_y": 720,
        "resolution_percentage": 100,
        "pixel_aspect_x": 1.0,
        "pixel_aspect_y": 1.0,
        "file_format": "PNG",
        "color_mode": "RGB",
        "color_depth": "8",
        "compression": 15,
        "film_transparent": False,
        "use_motion_blur": False,
        "cycles_samples": 96,
        "cycles_adaptive_sampling": True,
        "cycles_adaptive_threshold": 0.08,
        "cycles_use_denoising": True,
        "cycles_denoiser": "OPENIMAGEDENOISE",
        "cycles_denoising_input_passes": "RGB_ALBEDO_NORMAL",
        "cycles_max_bounces": 8,
        "cycles_volume_bounces": 1,
        "cycles_transparent_max_bounces": 12,
        "cycles_seed": 0,
        "cycles_use_animated_seed": False,
    }
)
"""Settings Phase 23 SETS on the scene before rendering.

Every value is either the Phase 15 baseline or the reviewed proof tier the
repository already renders at (1280x720, 96 adaptive samples at threshold
0.08, OpenImageDenoise, the locked bounce budget), chosen so a full episode
finishes in a practical wall clock rather than to look expensive. Raising the
tier is a profile version change, which changes the profile digest, which the
plan binds -- so a higher-quality render can never be confused with this one.

Two of these are load-bearing beyond looks. ``cycles_seed`` is pinned with
animated seed off to narrow the renderer's noise band as far as it can be
narrowed -- it does not close it, because Cycles on a GPU is stochastic, and
the witness verdict is a measured difference against a tolerance rather than a
claim that two frames sampled identically. ``use_motion_blur`` is off because a
blurred frame is a frame whose content depends on its neighbours, and every
claim this phase makes is per-frame.
"""

_VERIFIED_INHERITED: Final = MappingProxyType(
    {
        "view_transform": "AgX",
        "look": "AgX - Medium High Contrast",
        "exposure": 1.25,
        "fps": 24,
        "fps_base": 1.0,
    }
)
"""Settings Phase 23 REFUSES to set, and refuses to render without.

Colour management belongs to the Phase 15 world build and its style profile;
the clock belongs to Phase 17. Phase 23 photographs that world on that clock,
so it checks these and fails closed on disagreement rather than overriding a
locked layer's presentation from inside a render command. A mismatch means the
scene is not the reviewed world, and the honest response to that is to stop.
"""

RENDER_PROFILE_VERSION: Final = 1
"""Bumped whenever any profile value changes. The digest moves with it."""


def render_profile_document() -> dict[str, object]:
    """Return the render profile as a plain JSON document.

    Returns:
        A fresh, mutable copy: the caller may embed it in a plan without
        risking the module-level source of truth.
    """
    return {
        "profile_version": RENDER_PROFILE_VERSION,
        "owned": dict(_OWNED_OUTPUT),
        "verified": dict(_VERIFIED_INHERITED),
    }


def render_profile_dimensions() -> tuple[int, int]:
    """Return the exact pixel size every frame rendered under this profile has.

    The independent audit decodes each frame's own image header and compares it
    against these, so a picture of the wrong size is refused as a frame even
    when the manifest's digests were rewritten to match it.
    """
    return (
        cast(int, _OWNED_OUTPUT["resolution_x"]),
        cast(int, _OWNED_OUTPUT["resolution_y"]),
    )


def render_profile_sha256() -> str:
    """Return the digest of the render profile, over its canonical bytes.

    The digest is computed here rather than imported from the persistence
    package so the Blender executor -- which may not import the engine -- can
    reproduce it with the standard library alone.
    """
    import hashlib

    payload = (
        json.dumps(
            render_profile_document(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )
    return hashlib.sha256(payload).hexdigest()
