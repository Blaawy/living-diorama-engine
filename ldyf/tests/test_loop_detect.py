"""Proof that the loop detector fires on a planted cycle, stays quiet on a
record that genuinely progresses, reports an exact 0.0 when a record is
compared with itself, and refuses records it cannot read.

Both fixtures are built here: nothing in this file needs a real recording.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from ldyf.evidence import sha256_file
from ldyf.loop_detect import (
    LoopDetectError,
    actor_progress,
    detect_state_cycles,
    load_record,
    position_divergence,
)

COUNT = struct.Struct("<I")
SAMPLE = struct.Struct("<Ifffff")

CELL_CM = 100.0
NET = "aa" * 32
SEED = 20260903


def cell_xy(cx: float, cy: float) -> tuple[float, float]:
    """Unreal cm whose floor(pos / 100) is (cx, cy)."""
    return ((cx + 0.5) * CELL_CM, (cy + 0.5) * CELL_CM)


def write_record(
    directory,
    frames,
    actors,
    *,
    step_seconds: float = 1.0,
    t_begin: float = 0.0,
    net_sha256: str = NET,
    seed: int = SEED,
) -> Path:
    """`frames`: list of frames, each a list of (uid, x_cm, y_cm).
    `actors`: list of (uid, kind)."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    index = {uid: i for i, (uid, _kind) in enumerate(actors)}
    blob = bytearray()
    for rows in frames:
        ordered = sorted(rows, key=lambda r: index[r[0]])
        blob += COUNT.pack(len(ordered))
        for uid, x, y in ordered:
            blob += SAMPLE.pack(index[uid], x, y, 0.0, 0.0, 0.0)
    frames_path = d / "frames.bin"
    frames_path.write_bytes(bytes(blob))
    t_end = t_begin + max(0, len(frames) - 1) * step_seconds
    manifest = {
        "format": "simulation_record_v1",
        "clock": {
            "step_seconds": step_seconds,
            "frame_count": len(frames),
            "t_begin": t_begin,
            "t_end": t_end,
            "frame_time_rule": "t(i) = t_begin + i * step_seconds",
        },
        "binary": {"file": "frames.bin", "sha256": sha256_file(frames_path), "bytes": len(blob)},
        "source": {"net_file": "net.net.xml", "net_sha256": net_sha256, "seed": seed},
        "actors": [
            {"uid": uid, "id": uid.split(":")[-1], "kind": kind,
             "first_seen_time": t_begin, "last_seen_time": t_end}
            for uid, kind in actors
        ],
    }
    (d / "record_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return d


# --- the two fixtures the law demands -------------------------------------


def planted_cycle_record(directory, *, frames_n: int = 40) -> Path:
    """One actor pacing between two cells, 1 s per frame, forever."""
    frames = []
    for f in range(frames_n):
        cell = (0, 0) if f % 2 == 0 else (1, 0)
        x, y = cell_xy(*cell)
        frames.append([("vehicle:pacer", x, y)])
    return write_record(directory, frames, [("vehicle:pacer", "vehicle")])


def progressing_record(directory, *, frames_n: int = 40) -> Path:
    """Two actors, each visiting a new cell every frame: no cell is ever
    revisited, so nothing repeats and nothing can cycle."""
    frames = []
    for f in range(frames_n):
        x, y = cell_xy(f, 0)
        x2, y2 = cell_xy(0, f)
        frames.append([("vehicle:runner", x, y), ("person:walker", x2, y2)])
    return write_record(
        directory,
        frames,
        [("vehicle:runner", "vehicle"), ("person:walker", "person")],
    )


# ==========================================================================
# detect_state_cycles
# ==========================================================================


def test_detect_state_cycles_fires_on_a_planted_cycle(tmp_path):
    record = planted_cycle_record(tmp_path / "cycle")
    doc = detect_state_cycles(record, 60.0, 3)
    assert doc["fires"] is True
    assert doc["cycle_count"] > 0
    assert doc["actors_in_cycle"] == ["vehicle:pacer"]
    cells = {tuple(c["cell"]) for c in doc["cycles"]}
    assert cells == {(0, 0), (1, 0)}
    for cycle in doc["cycles"]:
        assert cycle["uid"] == "vehicle:pacer"
        assert cycle["occurrences"] >= 3
        assert cycle["span_s"] <= 60.0
    assert doc["schema_version"] == "state_cycles_v1"


def test_detect_state_cycles_does_not_fire_on_a_record_that_progresses(tmp_path):
    record = progressing_record(tmp_path / "progress")
    doc = detect_state_cycles(record, 60.0, 3)
    assert doc["fires"] is False
    assert doc["cycle_count"] == 0
    assert doc["cycles"] == []
    assert doc["actors_in_cycle"] == []


def test_detect_state_cycles_does_not_fire_on_a_parked_actor(tmp_path):
    """Never leaving a cell is parking, not cycling."""
    frames = [[("vehicle:parked", *cell_xy(3, 3))] for _ in range(40)]
    record = write_record(tmp_path / "parked", frames, [("vehicle:parked", "vehicle")])
    doc = detect_state_cycles(record, 600.0, 2)
    assert doc["fires"] is False
    assert doc["cycles"] == []


def test_detect_state_cycles_obeys_the_window(tmp_path):
    """Three returns inside 5 s is not the same claim as twenty inside 60 s."""
    record = planted_cycle_record(tmp_path / "cycle")
    assert detect_state_cycles(record, 5.0, 4)["fires"] is False
    assert detect_state_cycles(record, 60.0, 4)["fires"] is True


def test_detect_state_cycles_echoes_its_parameters(tmp_path):
    record = planted_cycle_record(tmp_path / "cycle")
    doc = detect_state_cycles(record, 30.0, 3, cell_cm=200.0)
    assert doc["params"] == {"window_s": 30.0, "min_repeats": 3, "cell_cm": 200.0}
    assert doc["record"]["frames"] == 40
    assert doc["record"]["step_seconds"] == 1.0
    # a 200 cm cell holds both paced positions, so the actor is parked inside one
    assert doc["fires"] is False


def test_detect_state_cycles_accepts_a_manifest_and_frames_handle(tmp_path):
    record = planted_cycle_record(tmp_path / "cycle")
    manifest, frames_path = load_record(record)
    doc = detect_state_cycles((manifest, frames_path), 60.0, 3)
    assert doc["fires"] is True


def test_a_single_frame_record_does_not_fire(tmp_path):
    record = write_record(
        tmp_path / "single", [[("vehicle:only", *cell_xy(1, 1))]], [("vehicle:only", "vehicle")]
    )
    doc = detect_state_cycles(record, 60.0, 2)
    assert doc["fires"] is False
    assert doc["cycle_count"] == 0
    assert doc["record"]["frames"] == 1


def test_an_empty_record_is_refused(tmp_path):
    record = plant_empty_record(tmp_path / "empty")
    with pytest.raises(LoopDetectError, match="empty record"):
        detect_state_cycles(record, 60.0, 2)


def test_a_truncated_record_is_refused(tmp_path):
    record = planted_cycle_record(tmp_path / "cycle")
    frames = record / "frames.bin"
    frames.write_bytes(frames.read_bytes()[:-7])
    with pytest.raises(LoopDetectError, match="truncated"):
        detect_state_cycles(record, 60.0, 2)


def test_detect_state_cycles_rejects_impossible_parameters(tmp_path):
    record = planted_cycle_record(tmp_path / "cycle")
    with pytest.raises(ValueError, match="window_s"):
        detect_state_cycles(record, 0.0, 3)
    with pytest.raises(ValueError, match="min_repeats"):
        detect_state_cycles(record, 60.0, 1)
    with pytest.raises(ValueError, match="cell_cm"):
        detect_state_cycles(record, 60.0, 3, cell_cm=0.0)


def plant_empty_record(directory) -> Path:
    """A record directory whose frames.bin exists and is 0 bytes."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    (d / "frames.bin").write_bytes(b"")
    (d / "record_manifest.json").write_text(
        json.dumps(
            {
                "format": "simulation_record_v1",
                "clock": {"step_seconds": 1.0, "frame_count": 0, "t_begin": 0.0, "t_end": 0.0},
                "binary": {"file": "frames.bin", "sha256": sha256_file(d / "frames.bin")},
                "actors": [{"uid": "vehicle:none", "id": "none", "kind": "vehicle"}],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return d


# ==========================================================================
# position_divergence
# ==========================================================================


def test_position_divergence_is_exactly_zero_for_a_record_compared_with_itself(tmp_path):
    record = progressing_record(tmp_path / "progress")
    divergence = position_divergence(record, record)
    assert divergence == 0.0
    assert repr(divergence) == "0.0"            # positive zero, not -0.0


def test_position_divergence_is_exactly_zero_for_two_copies_of_one_record(tmp_path):
    a = progressing_record(tmp_path / "a")
    b = progressing_record(tmp_path / "b")
    assert position_divergence(a, b) == 0.0


def test_position_divergence_measures_a_known_offset(tmp_path):
    a = write_record(
        tmp_path / "a", [[("vehicle:v", 100.0, 100.0)]], [("vehicle:v", "vehicle")]
    )
    b = write_record(
        tmp_path / "b", [[("vehicle:v", 400.0, 500.0)]], [("vehicle:v", "vehicle")]
    )
    assert position_divergence(a, b) == 500.0   # 3-4-5 triangle scaled by 100


def test_position_divergence_matches_actors_by_uid_not_by_index(tmp_path):
    """The same trajectories, with the actor tables in the opposite order."""
    a = write_record(
        tmp_path / "a",
        [[("vehicle:x", 100.0, 100.0), ("vehicle:y", 900.0, 100.0)]],
        [("vehicle:x", "vehicle"), ("vehicle:y", "vehicle")],
    )
    b = write_record(
        tmp_path / "b",
        [[("vehicle:x", 100.0, 100.0), ("vehicle:y", 900.0, 100.0)]],
        [("vehicle:y", "vehicle"), ("vehicle:x", "vehicle")],
    )
    assert position_divergence(a, b) == 0.0


def test_position_divergence_compares_the_common_frame_prefix(tmp_path):
    long_record = progressing_record(tmp_path / "long", frames_n=6)
    short_record = progressing_record(tmp_path / "short", frames_n=3)
    assert position_divergence(long_record, short_record) == 0.0


def test_position_divergence_refuses_records_with_nothing_in_common(tmp_path):
    a = write_record(tmp_path / "a", [[("vehicle:a", 1.0, 1.0)]], [("vehicle:a", "vehicle")])
    b = write_record(tmp_path / "b", [[("vehicle:b", 1.0, 1.0)]], [("vehicle:b", "vehicle")])
    with pytest.raises(LoopDetectError, match="share no actor"):
        position_divergence(a, b)


def test_position_divergence_refuses_an_empty_record(tmp_path):
    record = plant_empty_record(tmp_path / "empty")
    with pytest.raises(LoopDetectError, match="empty record"):
        position_divergence(record, record)


# ==========================================================================
# actor_progress
# ==========================================================================


def test_actor_progress_measures_a_straight_run(tmp_path):
    frames = [[("vehicle:v", 100.0 + 200.0 * f, 50.0)] for f in range(5)]
    record = write_record(tmp_path / "run", frames, [("vehicle:v", "vehicle")])
    doc = actor_progress(record)
    row = next(r for r in doc["actors"] if r["uid"] == "vehicle:v")
    assert row["distance_cm"] == 800.0
    assert row["displacement_cm"] == 800.0
    assert row["efficiency"] == 1.0
    assert row["duration_s"] == 4.0
    assert row["progress_rate_cm_s"] == 200.0
    assert row["stalled_s"] == 0.0
    assert row["zero_progress"] is False
    assert doc["zero_progress_actors"] == []
    assert doc["progressing_actors"] == ["vehicle:v"]


def test_actor_progress_flags_a_shuttle_and_a_parked_actor(tmp_path):
    frames = []
    for f in range(5):
        shuttle_x = 100.0 if f % 2 == 0 else 900.0
        frames.append([("vehicle:shuttle", shuttle_x, 50.0), ("vehicle:parked", 400.0, 400.0)])
    record = write_record(
        tmp_path / "mixed",
        frames,
        [("vehicle:shuttle", "vehicle"), ("vehicle:parked", "vehicle")],
    )
    doc = actor_progress(record)
    rows = {r["uid"]: r for r in doc["actors"]}
    shuttle = rows["vehicle:shuttle"]
    parked = rows["vehicle:parked"]
    assert shuttle["distance_cm"] == 3200.0        # 4 legs of 800 cm
    assert shuttle["displacement_cm"] == 0.0       # back where it started
    assert shuttle["efficiency"] == 0.0
    assert shuttle["zero_progress"] is True
    assert parked["distance_cm"] == 0.0
    assert parked["stalled_s"] == 4.0
    assert parked["stalled_fraction"] == 1.0
    assert doc["zero_progress_actors"] == ["vehicle:parked", "vehicle:shuttle"]
    assert doc["by_kind"]["vehicle"]["zero_progress_actors"] == 2
    assert doc["by_kind"]["vehicle"]["mean_distance_cm"] == 1600.0


def test_load_record_refuses_something_that_is_not_a_record(tmp_path):
    with pytest.raises(LoopDetectError, match="not a directory"):
        load_record(tmp_path / "nowhere")
    with pytest.raises(LoopDetectError, match="record handle"):
        load_record(42)
