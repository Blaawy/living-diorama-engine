"""Read a sealed simulation record, after checking it is the record it says it is.

`load_record` is the factory's only door to `frames.bin`. It refuses a record
whose binary does not hash to what its manifest declares, whose byte length is
not what the manifest declares, whose frames do not parse to exactly the
declared frame and sample counts, or which names an actor index the manifest
does not have. A corrupt record is therefore a refusal at the door, never a
quietly shorter track further down the pipeline.

Tracks are held as parallel typed arrays (about 20 bytes a sample), so both
arms of a 1500 s episode fit comfortably in memory without numpy.
"""
from __future__ import annotations

import bisect
import math
import struct
from array import array
from pathlib import Path
from typing import Any, Iterable

from . import FactoryError
from .util import read_json, sha256_file

SAMPLE = struct.Struct("<Ifffff")     # actor_index, x, y, z, yaw, speed
COUNT = struct.Struct("<I")
RECORD_FORMAT = "simulation_record_v1"


class RecordError(FactoryError):
    stage = "record"


class Track:
    """One actor's samples: frame index, x, y (Unreal cm), yaw (deg), speed (m/s)."""

    __slots__ = ("uid", "kind", "frames", "x", "y", "yaw", "speed")

    def __init__(self, uid: str, kind: str) -> None:
        self.uid, self.kind = uid, kind
        self.frames = array("I")
        self.x = array("f")
        self.y = array("f")
        self.yaw = array("f")
        self.speed = array("f")

    def __len__(self) -> int:
        return len(self.frames)

    def index_at(self, frame: int) -> int:
        """Position of `frame` in this track, or -1 when the actor is absent then."""
        i = bisect.bisect_left(self.frames, frame)
        return i if i < len(self.frames) and self.frames[i] == frame else -1

    def slice(self, f0: int, f1: int) -> range:
        """Positions of the samples with f0 <= frame <= f1."""
        return range(bisect.bisect_left(self.frames, f0), bisect.bisect_right(self.frames, f1))


class Record:
    def __init__(self, record_dir: Path, manifest: dict[str, Any]) -> None:
        self.dir = record_dir
        self.manifest = manifest
        clock = manifest["clock"]
        self.step = float(clock["step_seconds"])
        self.t_begin = float(clock.get("t_begin", 0.0))
        self.frame_count = int(clock["frame_count"])
        self.frames_sha256 = manifest["binary"]["sha256"]
        self.tracks: dict[str, Track] = {}

    def time_of(self, frame: int) -> float:
        return self.t_begin + frame * self.step

    def frame_of(self, t: float) -> int:
        return int(round((t - self.t_begin) / self.step))

    def of_kind(self, kind: str) -> list[Track]:
        return [t for t in self.tracks.values() if t.kind == kind]

    def select(self, uids: Iterable[str]) -> list[Track]:
        return [self.tracks[u] for u in uids if u in self.tracks]


def load_record(record_dir: str | Path) -> Record:
    record_dir = Path(record_dir)
    man = read_json(record_dir / "record_manifest.json", "record manifest", error=RecordError)
    try:
        if not isinstance(man, dict):
            raise TypeError("the manifest is not a JSON object")
        if man.get("format") != RECORD_FORMAT:
            raise RecordError("bad_format", f"record declares format {man.get('format')!r}")
        binary = man["binary"]
        declared_sha, declared_bytes = binary["sha256"], int(binary["bytes"])
        if binary.get("sample_struct") != "<Ifffff" or binary.get("frame_header_struct") != "<I":
            raise RecordError("bad_format", "record declares an unknown binary layout")
        actors = man["actors"]
        frame_count = int(man["clock"]["frame_count"])
        declared_samples = int(man["counts"]["samples"])
        float(man["clock"]["step_seconds"])
        if not isinstance(actors, list):
            raise TypeError("actors is not a list")
        for a in actors:
            if not isinstance(a["uid"], str) or a["kind"] not in ("vehicle", "person"):
                raise ValueError(f"bad actor entry {a!r}")
        name = binary.get("file", "frames.bin")
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("the binary must be a plain file name beside the manifest")
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise RecordError("corrupt", f"record manifest is malformed: {e!r}")
    frames_path = record_dir / binary.get("file", "frames.bin")
    if not frames_path.is_file():
        raise RecordError("missing", f"record binary is missing: {frames_path}")
    if frames_path.stat().st_size != declared_bytes:
        raise RecordError("corrupt", f"frames.bin is {frames_path.stat().st_size} bytes, "
                                     f"the manifest declares {declared_bytes}")
    have = sha256_file(frames_path)
    if have != declared_sha:
        raise RecordError("corrupt", f"frames.bin hashes to {have[:16]}.., the manifest "
                                     f"declares {declared_sha[:16]}..")

    rec = Record(record_dir, man)
    by_index: list[Track] = []
    for a in actors:
        t = Track(str(a["uid"]), str(a["kind"]))
        by_index.append(t)
        rec.tracks[t.uid] = t
    if len(rec.tracks) != len(actors):
        raise RecordError("corrupt", "record manifest names a uid twice")

    data = frames_path.read_bytes()
    off, frame, samples, n_actors = 0, 0, 0, len(by_index)
    size = len(data)
    while off < size:
        if off + COUNT.size > size:
            raise RecordError("corrupt", f"frames.bin is cut inside frame {frame}'s header")
        (count,) = COUNT.unpack_from(data, off)
        off += COUNT.size
        end = off + count * SAMPLE.size
        if end > size:
            raise RecordError("corrupt", f"frames.bin is cut inside frame {frame}")
        for ai, x, y, _z, yaw, speed in SAMPLE.iter_unpack(data[off:end]):
            if ai >= n_actors:
                raise RecordError("corrupt", f"frame {frame} names actor index {ai}, "
                                             f"the manifest has {n_actors} actors")
            if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(yaw)
                    and math.isfinite(speed)):
                raise RecordError("corrupt", f"frame {frame} carries a non-finite sample")
            t = by_index[ai]
            t.frames.append(frame)
            t.x.append(x)
            t.y.append(y)
            t.yaw.append(yaw)
            t.speed.append(speed)
        samples += count
        off = end
        frame += 1
    if frame != frame_count:
        raise RecordError("corrupt", f"frames.bin holds {frame} frames, the manifest declares {frame_count}")
    if samples != declared_samples:
        raise RecordError("corrupt", f"frames.bin holds {samples} samples, the manifest declares {declared_samples}")
    return rec


# --- geometry shared by the fact extractor and the camera planner ----------

Segment = tuple[float, float, float, float]


def edge_segments(net: Any, edge_id: str) -> list[Segment]:
    """An edge's own geometry in Unreal cm (ldyf.coords is the only transform)."""
    from ..coords import SumoPose, sumo_to_unreal
    pts = []
    for x, y in net.getEdge(edge_id).getShape():
        up = sumo_to_unreal(SumoPose(x=x, y=y, z=0.0, angle=0.0))
        pts.append((up.x, up.y))
    return [(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]) for i in range(len(pts) - 1)]


def edge_half_width_cm(net: Any, edge_id: str) -> float:
    return sum(float(ln.getWidth()) for ln in net.getEdge(edge_id).getLanes()) * 100.0 / 2.0


def trim_segments(segs: list[Segment], trim_cm: float) -> list[Segment]:
    """The same polyline with `trim_cm` cut off each end (the junction zones)."""
    lens = [math.hypot(bx - ax, by - ay) for ax, ay, bx, by in segs]
    lo, hi = trim_cm, sum(lens) - trim_cm
    out, run = [], 0.0
    for (ax, ay, bx, by), ln in zip(segs, lens):
        a, b = max(lo, run), min(hi, run + ln)
        if ln > 0 and b > a:
            fa, fb = (a - run) / ln, (b - run) / ln
            out.append((ax + fa * (bx - ax), ay + fa * (by - ay),
                        ax + fb * (bx - ax), ay + fb * (by - ay)))
        run += ln
    return out


def dist_to_segments(x: float, y: float, segs: list[Segment]) -> float:
    best = float("inf")
    for ax, ay, bx, by in segs:
        dx, dy = bx - ax, by - ay
        den = dx * dx + dy * dy
        t = 0.0 if den == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / den))
        d = math.hypot(x - (ax + t * dx), y - (ay + t * dy))
        if d < best:
            best = d
    return best
