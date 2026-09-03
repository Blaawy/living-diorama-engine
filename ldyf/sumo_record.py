"""Simulation Record V1 -- the frozen, replayable truth of one SUMO run.

Why this layer exists
---------------------
SUMO is mobility truth (Director's law). Unreal is presentation. Truth must
therefore be captured once, hashed, and then replayed as many times as the
edit needs -- at any camera, any quality, any frame rate -- without ever
re-running the simulation and without the renderer being able to influence
what happened.

This module converts SUMO's FCD output into that record. It is the only
writer of the record format.

Structure
---------
    record_manifest.json   provenance, actor table, hashes, coordinate system
    frames.bin            fixed-width little-endian binary samples

`frames.bin` layout, little-endian throughout:

    per frame:  uint32 sample_count
                sample_count x SAMPLE:
                    uint32  actor_index      index into manifest["actors"]
                    float32 x                Unreal centimetres
                    float32 y                Unreal centimetres
                    float32 z                Unreal centimetres
                    float32 yaw              Unreal degrees
                    float32 speed            metres/second (SUMO units, unconverted)

Frames are written in ascending simulation-time order with no gaps; frame i
is at time `t0 + i * step_seconds`. A frame with zero actors is still written,
so frame index is always a pure function of time.

Determinism
-----------
The record is written from a bit-deterministic SUMO payload (proven in
PHASE_01/proof). `frames.bin` is a pure function of that payload, so the
record's own hash is stable across runs. The manifest records both.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .coords import METRES_TO_UNREAL_UNITS, SumoPose, sumo_to_unreal

class RecordError(RuntimeError):
    """Raised when a record cannot be built faithfully."""


# float32 has 24 significant bits: below 2**23 cm (~83.9 km) the spacing is
# under 1 cm, so SUMO's 1 cm output grid survives exactly. Beyond it, it does
# not, and a net offset must be applied before recording (round-3 finding 6).
FLOAT32_EXACT_CM_EXTENT = 2 ** 23

SAMPLE_STRUCT = struct.Struct("<Ifffff")
COUNT_STRUCT = struct.Struct("<I")
RECORD_FORMAT_VERSION = "simulation_record_v1"


@dataclass
class RecordStats:
    frames: int = 0
    samples: int = 0
    actors: int = 0
    t_begin: float | None = None
    t_end: float | None = None
    peak_concurrent: int = 0
    actor_kinds: dict[str, int] = field(default_factory=dict)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_LEADING_COMMENT = re.compile(rb"\A\s*(?:<\?xml[^>]*\?>\s*)?<!--.*?-->", re.S)


def payload_span(data: bytes) -> tuple[int, str]:
    """Where the hashed payload starts, and which rule chose it.

    SUMO stamps a generation timestamp and output filename into ONE leading
    XML comment. That comment is located structurally -- it must open at the
    start of the document (after the optional XML declaration) -- rather than by
    searching for the first `-->` anywhere, which a payload could contain
    (round-3 finding 7). If no leading comment exists the whole file is hashed
    and the mode says so, so the law is never silently downgraded.
    """
    m = _LEADING_COMMENT.match(data)
    if m:
        return m.end(), "after_leading_comment"
    return 0, "whole_file"


def _sha256_payload(path: Path) -> str:
    """Hash a SUMO XML file excluding its provenance header comment."""
    data = path.read_bytes()
    start, _mode = payload_span(data)
    return hashlib.sha256(data[start:]).hexdigest()


def payload_hash_mode(path: Path) -> str:
    return payload_span(path.read_bytes())[1]


def build_record(
    fcd_path: str | Path,
    out_dir: str | Path,
    *,
    step_seconds: float,
    net_path: str | Path | None = None,
    seed: int | None = None,
    sumo_version: str | None = None,
) -> RecordStats:
    """Convert an FCD XML file into a Simulation Record V1 directory."""
    fcd_path = Path(fcd_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    actor_index: dict[str, int] = {}
    actors: list[dict[str, object]] = []
    stats = RecordStats()

    frames_path = out_dir / "frames.bin"

    with frames_path.open("wb") as out:
        # iterparse keeps memory flat; the 128 MB FCD file is never fully resident.
        for _event, elem in ET.iterparse(str(fcd_path), events=("end",)):
            if elem.tag != "timestep":
                continue

            t = float(elem.get("time", "0"))
            if stats.t_begin is None:
                stats.t_begin = t
            stats.t_end = t

            rows: list[tuple[int, float, float, float, float, float]] = []
            for child in elem:
                if child.tag == "vehicle":
                    kind = "vehicle"
                elif child.tag == "person":
                    kind = "person"
                else:
                    continue

                aid = child.get("id")
                if aid is None:
                    continue

                # SUMO ids are only unique *within* a namespace: a run can
                # contain both `vehicle id="0"` and `person id="0"`. Keying the
                # actor table on the bare id silently merges them and writes
                # pedestrian positions as vehicle samples. Measured on the
                # Phase 1 proof run: 200 of 500 vehicle ids collided.
                key = f"{kind}:{aid}"
                if key not in actor_index:
                    actor_index[key] = len(actors)
                    actors.append(
                        {
                            "uid": key,
                            "id": aid,
                            "kind": kind,
                            "type": child.get("type", ""),
                            "first_seen_time": t,
                            "last_seen_time": t,
                        }
                    )
                    stats.actor_kinds[kind] = stats.actor_kinds.get(kind, 0) + 1
                actors[actor_index[key]]["last_seen_time"] = t

                sx, sy = float(child.get("x", "0")), float(child.get("y", "0"))
                if max(abs(sx), abs(sy)) * METRES_TO_UNREAL_UNITS >= FLOAT32_EXACT_CM_EXTENT:
                    raise RecordError(
                        f"coordinate {sx:.2f},{sy:.2f} m exceeds the float32 exact-centimetre "
                        f"extent ({FLOAT32_EXACT_CM_EXTENT} cm); apply a net offset before recording"
                    )

                pose = sumo_to_unreal(
                    SumoPose(
                        x=float(child.get("x", "0")),
                        y=float(child.get("y", "0")),
                        z=float(child.get("z", "0")),
                        angle=float(child.get("angle", "0")),
                    )
                )
                rows.append(
                    (
                        actor_index[key],
                        pose.x,
                        pose.y,
                        pose.z,
                        pose.yaw,
                        float(child.get("speed", "0")),
                    )
                )

            # Deterministic ordering inside a frame: by actor index, always.
            rows.sort(key=lambda r: r[0])

            out.write(COUNT_STRUCT.pack(len(rows)))
            for r in rows:
                out.write(SAMPLE_STRUCT.pack(*r))

            stats.frames += 1
            stats.samples += len(rows)
            stats.peak_concurrent = max(stats.peak_concurrent, len(rows))

            elem.clear()

    stats.actors = len(actors)

    manifest = {
        "format": RECORD_FORMAT_VERSION,
        "coordinate_system": {
            "target": "unreal",
            "linear_units": "centimetres",
            "float32_exact_cm_extent": FLOAT32_EXACT_CM_EXTENT,
            "angular_units": "degrees",
            "axes": "X=east, Y=south, Z=up (left-handed)",
            "yaw_zero": "+X",
            "speed_units": "metres_per_second",
            "transform_authority": "ldyf.coords",
        },
        "clock": {
            "step_seconds": step_seconds,
            "frame_count": stats.frames,
            "t_begin": stats.t_begin,
            "t_end": stats.t_end,
            "frame_time_rule": "t(i) = t_begin + i * step_seconds",
        },
        "counts": {
            "actors": stats.actors,
            "samples": stats.samples,
            "peak_concurrent_actors": stats.peak_concurrent,
            "by_kind": stats.actor_kinds,
        },
        "source": {
            "fcd_file": fcd_path.name,
            "fcd_payload_sha256": _sha256_payload(fcd_path),
            "fcd_payload_hash_mode": payload_hash_mode(fcd_path),
            "net_file": Path(net_path).name if net_path else None,
            "net_sha256": _sha256_payload(Path(net_path)) if net_path else None,
            "seed": seed,
            "sumo_version": sumo_version,
        },
        "binary": {
            "file": "frames.bin",
            "sample_struct": "<Ifffff",
            "sample_bytes": SAMPLE_STRUCT.size,
            "frame_header_struct": "<I",
            "fields": ["actor_index", "x", "y", "z", "yaw", "speed"],
            "sha256": _sha256_file(frames_path),
            "bytes": frames_path.stat().st_size,
        },
        "actors": actors,
    }

    (out_dir / "record_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return stats


# --- reader ---------------------------------------------------------------


def read_frame(frames_path: str | Path, manifest: dict, frame_index: int) -> list[dict]:
    """Read one frame. Deliberately simple; the Unreal side mirrors this."""
    path = Path(frames_path)
    with path.open("rb") as f:
        for i in range(frame_index + 1):
            raw = f.read(COUNT_STRUCT.size)
            if len(raw) < COUNT_STRUCT.size:
                raise IndexError(f"frame {frame_index} beyond end of record")
            (n,) = COUNT_STRUCT.unpack(raw)
            payload = f.read(n * SAMPLE_STRUCT.size)
            if i != frame_index:
                continue
            out = []
            for k in range(n):
                idx, x, y, z, yaw, speed = SAMPLE_STRUCT.unpack_from(
                    payload, k * SAMPLE_STRUCT.size
                )
                out.append(
                    {
                        "actor_index": idx,
                        "actor_id": manifest["actors"][idx]["id"],
                        "kind": manifest["actors"][idx]["kind"],
                        "x": x,
                        "y": y,
                        "z": z,
                        "yaw": yaw,
                        "speed": speed,
                    }
                )
            return out
    raise IndexError(f"frame {frame_index} beyond end of record")


def iter_actor_track(frames_path: str | Path, manifest: dict, actor_id: str):
    """Yield (frame_index, sample) for every frame in which one actor appears."""
    target = None
    for i, a in enumerate(manifest["actors"]):
        # Accept the namespaced uid ("vehicle:12") or, when unambiguous, a bare id.
        if a["uid"] == actor_id or a["id"] == actor_id:
            target = i
            break
    if target is None:
        raise KeyError(f"actor {actor_id!r} not in record")

    path = Path(frames_path)
    with path.open("rb") as f:
        frame = 0
        while True:
            raw = f.read(COUNT_STRUCT.size)
            if len(raw) < COUNT_STRUCT.size:
                return
            (n,) = COUNT_STRUCT.unpack(raw)
            payload = f.read(n * SAMPLE_STRUCT.size)
            for k in range(n):
                idx, x, y, z, yaw, speed = SAMPLE_STRUCT.unpack_from(
                    payload, k * SAMPLE_STRUCT.size
                )
                if idx == target:
                    yield frame, {
                        "x": x, "y": y, "z": z, "yaw": yaw, "speed": speed,
                    }
                    break
            frame += 1
