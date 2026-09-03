"""Deterministic Level-Sequence key baking (Phase-2 closure lane S, contract C3).

Pure, unit-tested Python that turns the sealed Simulation Record into the key
set an in-editor Level Sequence needs (``ldyf/unreal/ldyf_sequence.py``). The
render path contains no wall clock: frame authority is C3's

    presentation_time = frame / fps
    sim_time          = t_begin + presentation_time x rate

and every pose is ``record_interp.pose_at`` semantics evaluated on the record
held in memory -- the same in-memory semantics the in-editor playback module
runs (``ldyf.unreal.ldyf_playback._interp_poses`` = playback_core).

Authorities (reused, never re-derived)
-------------------------------------
* pose semantics -- ``playback_core.interpolated_poses``, which is pose_at
  semantics on in-memory frames (actor must be present in BOTH bounding record
  frames; never extrapolated across an absence).
* wheel spin     -- ``vehicle_kinematics.wheel_angle_deg``.
* persons        -- ``playback_core.person_anim_state`` / ``person_play_rate``.
* z law (C1)     -- key z = record_z + surface_z_cm + contact_offsets[mesh].
* mesh           -- the caller's ``mesh_for_uid(uid)``, i.e. exactly what the
  playback module computes at spawn (_pick_mesh over the vehicle list for
  vehicles, the fixed Tutorial person mesh for persons).
* coords         -- record samples are ALREADY Unreal cm / deg (SAMPLE_STRUCT
  "<Ifffff": x_cm, y_cm, z_cm, yaw_deg, speed_mps; see ldyf.sumo_record), so
  x/y/yaw pass through untouched -- the same passthrough playback performs.

Output schema ``sequence_bake_v1``
----------------------------------
{"schema_version","fps","rate","t_begin","frames":[first,last],
 "actors": {uid: {"kind","mesh",
                  "keys":      [{"f","x","y","z","yaw"}, ...],
                  "presence":  [[f_on,f_off], ...],
                  "wheel_angle_deg": [{"f","deg"}, ...],   # vehicles only
                  "anim":      [{"f_on","f_off","state","rate"}, ...]}},  # persons
 "counts": {"actors","keys"},
 "missing_contact_offsets": [uid, ...]}

Design decisions (each one line, so a reviewer can argue with a single one):
  D1. The output-frame window is the presentation window of the requested SIM
      slice: f in [ceil((t_start_s-t_begin)/rate*fps), ceil((t_end_s-t_begin)/
      rate*fps)-1]. Keys' "f" are those absolute presentation-frame numbers
      (MP4 frame N = presentation second N/fps, C3); the in-editor consumer
      sets the sequence playback range to [first,last].
  D2. An actor is emitted only when it has >= 1 keyed frame in the window.
      Present-but-unplaceable actors (no contact offset for their mesh) go to
      missing_contact_offsets, NOT to actors: a visibility section without a
      transform track would park the actor at the origin.
  D3. Presence segments are maximal runs of CONSECUTIVE keyed frames,
      [f_on, f_off] inclusive (spawn/despawn frames) -- mirrors the playback
      spawn-at-first-present / despawn-at-first-absent rule.
  D4. Wheel angle starts at 0.0 at the first frame of each presence run (the
      playback module destroys and re-spawns on absence, resetting spin), then
      accumulates with wheel_angle_deg using the destination frame's pose speed
      and dt = (f - prev_f)/fps x rate (sim seconds between keyed frames).
      No wheel entries while the mesh radius is unmeasured (None) -- spin is
      skipped and the list is empty, like playback's wheels_unspun counter.
  D5. Person anim segments are maximal same-state runs; state from
      person_anim_state(speed, walk_ref) (idle_below is not an argument here;
      a caller wanting it must thread it through later). A segment's "rate" is
      person_play_rate evaluated at the segment's FIRST frame: the in-editor
      player re-sets play rate every tick, but a sequence section carries one
      rate, so the bake fixes it per segment (documented approximation).
  D6. Determinism: actor dict ordered by uid, keys ordered by f; every float is
      pure arithmetic (coords.normalise_deg already kills -0.0), so repeated
      bakes are byte-identical under json.dumps(sort_keys=True).

No `unreal` import anywhere; no wall clock; all tolerances are arguments.
"""

from __future__ import annotations

import math
from pathlib import Path

from .playback_core import (
    interpolated_poses,
    person_anim_state,
    person_play_rate,
)
from .sumo_record import COUNT_STRUCT, SAMPLE_STRUCT
from .vehicle_kinematics import wheel_angle_deg

SCHEMA_VERSION = "sequence_bake_v1"

__all__ = [
    "SCHEMA_VERSION",
    "presentation_time_s",
    "sim_time_s",
    "bake_keys",
]


# --- frame <-> time (C3) --------------------------------------------------


def presentation_time_s(frame: int, fps: float) -> float:
    """Presentation seconds of one output frame: frame / fps (C3)."""
    return frame / fps


def sim_time_s(frame: int, fps: float, t_begin: float, rate: float = 1.0) -> float:
    """Simulation seconds: t_begin + presentation_time x rate (C3)."""
    return t_begin + (frame * rate) / fps


# --- private helpers -------------------------------------------------------


def _snap(x: float) -> float:
    """Kill float noise at integer boundaries (same trick as record_interp)."""
    r = round(x)
    return float(r) if abs(x - r) < 1e-9 else x


def _load_frames(frames_path: str | Path) -> list[list[tuple]]:
    """Read every frame into memory once (playback-module _load_frames shape)."""
    data = Path(frames_path).read_bytes()
    out: list[list[tuple]] = []
    off = 0
    while off + COUNT_STRUCT.size <= len(data):
        (n,) = COUNT_STRUCT.unpack_from(data, off)
        off += COUNT_STRUCT.size
        rows = []
        for _ in range(n):
            rows.append(SAMPLE_STRUCT.unpack_from(data, off))
            off += SAMPLE_STRUCT.size
        out.append(rows)
    if not out:
        raise ValueError("frames.bin contains no frames")
    return out


def _output_frame_range(
    fps: float, rate: float, t_begin: float, t_start_s: float, t_end_s: float
) -> tuple[int, int]:
    """(first, last) inclusive presentation frames of the requested SIM slice."""
    p0 = (t_start_s - t_begin) / rate
    p1 = (t_end_s - t_begin) / rate
    first = int(math.ceil(_snap(p0 * fps)))
    last = int(math.ceil(_snap(p1 * fps))) - 1
    return first, last


def _runs(fs: list[int]) -> list[list[int]]:
    """Maximal runs of consecutive frames, each an inclusive [start, end]."""
    runs: list[list[int]] = []
    for f in fs:
        if runs and f == runs[-1][1] + 1:
            runs[-1][1] = f
        else:
            runs.append([f, f])
    return runs


def _wheel_keys(
    entries: list[tuple[int, dict, float]],
    fps: float,
    rate: float,
    radius: float | None,
) -> list[dict]:
    """Per-keyed-frame accumulated wheel angle (D4), or [] while unmeasured."""
    if radius is None or radius <= 0.0:
        return []
    out: list[dict] = []
    angle = 0.0
    prev_f: int | None = None
    for f, pose, _z in entries:
        if prev_f is None or f > prev_f + 1:
            angle = 0.0  # presence run start == respawn in playback (spin reset)
            out.append({"f": f, "deg": 0.0})
        else:
            dt = (f - prev_f) * rate / fps
            angle = wheel_angle_deg(angle, pose["speed"], radius, dt)
            out.append({"f": f, "deg": angle})
        prev_f = f
    return out


def _anim_segments(
    entries: list[tuple[int, dict, float]],
    walk_ref_speed_mps: float | None,
) -> list[dict]:
    """Maximal same-state runs; segment rate fixed at the first frame (D5)."""
    segs: list[dict] = []
    for f, pose, _z in entries:
        state = person_anim_state(pose["speed"], walk_ref_speed_mps, None)
        if segs and segs[-1]["state"] == state and f == segs[-1]["f_off"] + 1:
            segs[-1]["f_off"] = f
        else:
            rate = person_play_rate(
                pose["speed"] if state == "walk" else 0.0, walk_ref_speed_mps
            )
            segs.append({"f_on": f, "f_off": f, "state": state, "rate": rate})
    return segs


# --- main bake -------------------------------------------------------------


def bake_keys(
    frames_path,
    manifest: dict,
    *,
    fps: float,
    rate: float = 1.0,
    t_start_s: float,
    t_end_s: float,
    surface_z_cm: float,
    contact_offsets: dict[str, float],
    mesh_for_uid,
    wheel_radius_for_mesh: dict[str, float | None],
    walk_ref_speed_mps: float | None,
) -> dict:
    """Bake a sequence_bake_v1 document for one record (docstring: full schema).

    ``frames_path`` is the record's frames.bin; ``manifest`` the record's
    manifest. ``contact_offsets`` keys are mesh paths (C1 measurements);
    ``wheel_radius_for_mesh`` mirrors the playback module's _WHEEL_RADIUS_CM
    (None == unmeasured, spin skipped). ``mesh_for_uid`` mirrors the playback
    spawn-time mesh choice. Deterministic (D6).
    """
    if fps <= 0.0:
        raise ValueError(f"fps must be > 0, got {fps!r}")
    if rate <= 0.0:
        raise ValueError(f"rate must be > 0, got {rate!r}")
    clock = manifest["clock"]
    t_begin = float(clock["t_begin"])
    if int(clock.get("frame_count", 0)) == 0:
        raise ValueError("record has no frames")

    actors_meta = manifest["actors"]
    unknown = sorted({a.get("kind") for a in actors_meta} - {"vehicle", "person"})
    if unknown:
        raise ValueError(
            f"record kinds not baked: {unknown} (representation table has vehicle/person)"
        )

    frames = _load_frames(frames_path)
    frames_by_index = {i: rows for i, rows in enumerate(frames)}
    first, last = _output_frame_range(fps, rate, t_begin, t_start_s, t_end_s)

    per: dict[str, dict] = {}  # uid -> {"kind","mesh","entries":[(f, pose, z)]}
    mesh_of: dict[str, str] = {}
    missing: set[str] = set()

    for f in range(first, last + 1):
        t = sim_time_s(f, fps, t_begin, rate)
        poses = interpolated_poses(frames_by_index, manifest, t)
        for idx, pose in sorted(poses.items()):
            uid = actors_meta[idx]["uid"]
            kind = actors_meta[idx]["kind"]
            mesh = mesh_of.get(uid)
            if mesh is None:
                mesh = mesh_for_uid(uid)
                mesh_of[uid] = mesh
            off = contact_offsets.get(mesh)
            if off is None:
                missing.add(uid)  # D2: present but unplaceable
                continue
            rec = per.setdefault(uid, {"kind": kind, "mesh": mesh, "entries": []})
            rec["entries"].append((f, pose, pose["z"] + surface_z_cm + off))

    out_actors: dict[str, dict] = {}
    total_keys = 0
    for uid in sorted(per):
        rec = per[uid]
        entries = sorted(rec["entries"], key=lambda e: e[0])
        key_frames = [e[0] for e in entries]
        keys = [
            {"f": e[0], "x": e[1]["x"], "y": e[1]["y"], "z": e[2], "yaw": e[1]["yaw"]}
            for e in entries
        ]
        total_keys += len(keys)
        actor: dict = {
            "kind": rec["kind"],
            "mesh": rec["mesh"],
            "keys": keys,
            "presence": _runs(key_frames),
        }
        if rec["kind"] == "vehicle":
            actor["wheel_angle_deg"] = _wheel_keys(
                entries, fps, rate, wheel_radius_for_mesh.get(rec["mesh"])
            )
        else:  # person
            actor["anim"] = _anim_segments(entries, walk_ref_speed_mps)
        out_actors[uid] = actor

    return {
        "schema_version": SCHEMA_VERSION,
        "fps": fps,
        "rate": rate,
        "t_begin": t_begin,
        "frames": [first, last],
        "actors": out_actors,
        "counts": {"actors": len(out_actors), "keys": total_keys},
        "missing_contact_offsets": sorted(missing),
    }
