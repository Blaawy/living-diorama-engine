"""Lane L3 tests: the no-scripted-loops law, measured on synthetic records.

Records are written straight to disk with SAMPLE_STRUCT / COUNT_STRUCT plus a
hand-written manifest (layout documented in ldyf/sumo_record.py: per frame a
uint32 sample_count followed by sample_count * <Ifffff>; manifest clock /
binary / actors tables). Positions are Unreal centimetres, so cell index is
floor(pos / cell_cm); a helper maps cell (cx, cy) to unreal
((cx + 0.5) * 100, (cy + 0.5) * 100) so the stored cell equals (cx, cy).
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import pytest

from ldyf.loop_audit import (
    LOOP_AUDIT_VERSION,
    audit_record,
    quantise,
    sampled_tracks,
    window_repeats,
    write_audit,
)
from ldyf.sumo_record import COUNT_STRUCT, SAMPLE_STRUCT


# --- helpers --------------------------------------------------------------

CELL_CM = 100.0


def cell_xy(cx: float, cy: float) -> tuple[float, float]:
    """Unreal cm for a cell: floor(axis / 100) == (cx, cy) for non-negative."""
    return ((cx + 0.5) * CELL_CM, (cy + 0.5) * CELL_CM)


def row(uid, cell, t=0.0):
    """One frame containing one actor sample (ignores t; frames carry time)."""
    x, y = cell_xy(*cell)
    return [(uid, x, y, 0.0)]


def write_record(
    dir_path,
    frames,
    actors,
    *,
    step_seconds: float = 1.0,
    t_begin: float = 0.0,
    kind: str = "vehicle",
):
    """frames: list of frames, each a list of (uid, x_cm, y_cm, z_cm)."""
    d = Path(dir_path)
    d.mkdir(parents=True, exist_ok=True)
    idx = {a["uid"]: i for i, a in enumerate(actors)}
    buf = bytearray()
    for rows in frames:
        ordered = sorted(rows, key=lambda r: idx[r[0]])
        buf += COUNT_STRUCT.pack(len(ordered))
        for uid, x, y, z in ordered:
            buf += SAMPLE_STRUCT.pack(idx[uid], x, y, z, 0.0, 0.0)
    (d / "frames.bin").write_bytes(bytes(buf))
    sha = hashlib.sha256(bytes(buf)).hexdigest()
    t_end = t_begin + (len(frames) - 1) * step_seconds if frames else t_begin
    manifest = {
        "format": "simulation_record_v1",
        "clock": {
            "step_seconds": step_seconds,
            "frame_count": len(frames),
            "t_begin": t_begin,
            "t_end": t_end,
            "frame_time_rule": "t(i) = t_begin + i * step_seconds",
        },
        "binary": {"file": "frames.bin", "sha256": sha},
        "actors": [
            {
                "uid": a["uid"],
                "id": a["uid"].split(":", 1)[1],
                "kind": a.get("kind", kind),
                "first_seen_time": a.get("first_seen_time", t_begin),
                "last_seen_time": a.get("last_seen_time", t_end),
            }
            for a in actors
        ],
    }
    (d / "record_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return d


def stationary(uid, cell, frames_n: int):
    """`frames_n` frames of one actor parked on `cell`."""
    return [row(uid, cell) for _ in range(frames_n)]


# 4x4 m square perimeter walked at 1 cell/s: 16 distinct cells per lap.
SQUARE_LAP = [
    (0, 0), (1, 0), (2, 0), (3, 0), (4, 0),
    (4, 1), (4, 2), (4, 3), (4, 4),
    (3, 4), (2, 4), (1, 4), (0, 4),
    (0, 3), (0, 2), (0, 1),
]


def lap_frames(uid, cell_path):
    """One frame per second, actor one cell further along `cell_path`."""
    return [row(uid, c) for c in cell_path]


def audit(dir_path, **params) -> dict:
    d = Path(dir_path)
    man = json.loads((d / "record_manifest.json").read_text(encoding="utf-8"))
    return audit_record(d / "frames.bin", man, **params)


def spawn_record(dir_path, spawn_times):
    """Record spanning t=0..199 s; spawn times come from the manifest only.

    200 one-row frames make t_end == 199 so the spawn bin series has exactly
    200 bins at rate_hz == 1 (bins 0..199), regardless of actor count.
    """
    actors = [{"uid": f"vehicle:{i}", "first_seen_time": t}
              for i, t in enumerate(spawn_times)]
    frames = [row("vehicle:0", (0, 0)) for _ in range(200)]
    return write_record(dir_path, frames, actors)


# --- pure functions -------------------------------------------------------

def test_quantise_maps_unreal_cm_to_cells():
    track = [(0.0, 50.0, 50.0, 0.0), (1.0, 250.0, 350.0, 0.0), (2.0, -50.0, 50.0, 0.0)]
    assert quantise(track, cell_cm=100.0) == [(0, 0), (2, 3), (-1, 0)]


def test_window_repeats_detects_identical_windows():
    cells = [0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 2, 3, 4, 5, 6, 7]
    events = window_repeats(cells, window=8, horizon=120)
    assert events == [{"start_a": 0, "start_b": 8, "window": list(range(8))}]


def test_window_repeats_respects_horizon():
    cells = list(range(8)) + [99] * 120 + list(range(8))
    assert window_repeats(cells, window=8, horizon=8) == []      # too far apart
    assert window_repeats(cells, window=8, horizon=200) != []    # inside one horizon


def test_sampled_tracks_decimates_to_rate_hz(tmp_path):
    frames = [row("vehicle:a", (0, 0)) for _ in range(10)]       # 10 frames @ 1 s
    rec = write_record(tmp_path / "r", frames, [{"uid": "vehicle:a"}], step_seconds=1.0)
    man = json.loads((rec / "record_manifest.json").read_text())
    t = sampled_tracks(rec / "frames.bin", man, rate_hz=1.0)
    assert [s[0] for s in t["vehicle:a"]] == [0.0, 1.0, 2.0, 3.0, 4.0,
                                              5.0, 6.0, 7.0, 8.0, 9.0]


# --- law measurements on synthetic records --------------------------------

def test_square_lap_twice_is_a_repeat_and_worst_names_the_actor(tmp_path):
    cells = SQUARE_LAP + SQUARE_LAP                       # two identical laps
    rec = write_record(tmp_path / "r", lap_frames("vehicle:loop", cells),
                       [{"uid": "vehicle:loop"}])
    res = audit(rec)
    wr = res["window_repeats"]
    assert wr["pass"] is False
    assert wr["actors_with_repeats"] == ["vehicle:loop"]
    assert wr["repeat_count"] > 0
    assert wr["worst"]["uid"] == "vehicle:loop"
    assert res["pass"] is False
    assert wr["stationary_windows_exempted"] == 0


def test_second_lap_shifted_beyond_cell_size_is_not_a_repeat(tmp_path):
    shifted = [(x + 5, y) for (x, y) in SQUARE_LAP]       # 5 cells > cell_cm
    cells = SQUARE_LAP + shifted
    rec = write_record(tmp_path / "r", lap_frames("vehicle:jit", cells),
                       [{"uid": "vehicle:jit"}])
    res = audit(rec)
    assert res["window_repeats"]["pass"] is True
    assert res["window_repeats"]["repeat_count"] == 0
    assert res["pass"] is True


def test_stationary_actor_is_exempt_not_a_failure(tmp_path):
    rec = write_record(tmp_path / "r",
                       stationary("vehicle:parked", (3, 3), 40),
                       [{"uid": "vehicle:parked"}])
    res = audit(rec)
    assert res["window_repeats"]["pass"] is True
    assert res["window_repeats"]["repeat_count"] == 0
    assert res["window_repeats"]["stationary_windows_exempted"] == 33
    assert res["pass"] is True


def test_three_destinations_among_ten_actors_fails(tmp_path):
    ends = [0, 1, 2] + [2] * 7                            # unique = 3 -> ratio 0.3
    frames = []
    actors = []
    for i, c in enumerate(ends):
        uid = f"vehicle:{i}"
        actors.append({"uid": uid})
        frames += stationary(uid, (c, 0), 1)
    rec = write_record(tmp_path / "r", frames, actors)
    res = audit(rec)
    assert res["destinations"]["by_kind"]["vehicle"]["ratio"] == 0.3
    assert res["destinations"]["pass"] is False
    assert res["pass"] is False


def test_seven_destinations_among_ten_actors_passes(tmp_path):
    frames = []
    actors = []
    for i in range(10):
        uid = f"vehicle:{i}"
        actors.append({"uid": uid})
        frames += stationary(uid, (i % 7, 0), 1)          # unique = 7 -> 0.7
    rec = write_record(tmp_path / "r", frames, actors)
    res = audit(rec)
    assert res["destinations"]["by_kind"]["vehicle"]["ratio"] == 0.7
    assert res["destinations"]["pass"] is True
    assert res["pass"] is True


def test_spawns_every_5s_have_peak_period_5s_and_high_score(tmp_path):
    # 40 spawns at 0,5,...,195 over 200 bins: peak k=40 -> period 200/40 = 5 s.
    rec = spawn_record(tmp_path / "p", [5 * j for j in range(40)])
    v = audit(rec)["spawn_periodicity"]["by_kind"]["vehicle"]
    assert v["bins"] == 200
    assert v["peak_period_s"] == 5.0
    assert v["score"] > 0.2


def test_randomish_spawns_have_lower_score_than_periodic(tmp_path):
    # Provable ordering: for ANY 24 distinct spawn bins in 200, the score is
    # at most 24/176 < 0.25 (Parseval + triangle-inequality bound), while the
    # 24-spawn-every-5s arm scores exactly 0.25.
    rng = random.Random(20260903)
    times = sorted(rng.sample(range(200), 24))
    score_r = audit(spawn_record(tmp_path / "r", times))[
        "spawn_periodicity"]["by_kind"]["vehicle"]["score"]
    score_p = audit(spawn_record(tmp_path / "p", [5 * j for j in range(24)]))[
        "spawn_periodicity"]["by_kind"]["vehicle"]["score"]
    assert score_p > score_r


def test_spawn_threshold_is_null_and_ignored_by_pass(tmp_path):
    rec = spawn_record(tmp_path / "p", [5 * j for j in range(40)])
    sp = audit(rec)["spawn_periodicity"]
    assert sp["threshold"] is None
    assert audit(rec)["pass"] is True          # spawn periodicity alone passes


def test_params_are_echoed(tmp_path):
    rec = write_record(tmp_path / "r",
                       stationary("vehicle:p", (0, 0), 12),
                       [{"uid": "vehicle:p"}])
    params = dict(window_s=4.0, horizon_s=30.0, cell_cm=50.0,
                  rate_hz=1.0, dest_ratio_min=0.5)
    res = audit(rec, **params)
    assert res["params"] == params


def test_schema_version_and_record_counts(tmp_path):
    rec = write_record(tmp_path / "r",
                       stationary("vehicle:p", (0, 0), 5),
                       [{"uid": "vehicle:p"}])
    res = audit(rec)
    assert res["schema_version"] == LOOP_AUDIT_VERSION
    assert res["record"]["frames"] == 5
    assert res["record"]["step_seconds"] == 1.0


# --- output document ------------------------------------------------------

def test_manifest_sha256_binds_audit_to_record(tmp_path):
    rec = write_record(tmp_path / "r",
                       stationary("vehicle:p", (0, 0), 5),
                       [{"uid": "vehicle:p"}])
    man = json.loads((rec / "record_manifest.json").read_text())
    assert audit(rec)["record"]["frames_bin_sha256"] == man["binary"]["sha256"]
    # independently of the manifest echo
    raw = (rec / "frames.bin").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == man["binary"]["sha256"]


def test_write_audit_is_byte_deterministic(tmp_path):
    rec = write_record(tmp_path / "r",
                       stationary("vehicle:p", (0, 0), 5),
                       [{"uid": "vehicle:p"}])
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    write_audit(rec, a)
    write_audit(rec, b)
    assert a.read_bytes() == b.read_bytes()
    doc = json.loads(a.read_text())
    assert doc["schema_version"] == LOOP_AUDIT_VERSION


# --- real proof record (skipped when absent, like test_closure.py) --------

def _find_record_dir() -> Path:
    import os

    candidates = []
    env = os.environ.get("LDYF_PROOF_DIR")
    if env:
        candidates.append(Path(env) / "closure_v2" / "record_ruled")
    here = Path(__file__).resolve()
    candidates.append(here.parents[3] / "evidence" / "simulation"
                      / "closure_v2" / "record_ruled")
    candidates.append(
        Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
        / "PHASE_01" / "proof" / "sumo" / "closure_v2" / "record_ruled"
    )
    return next((c for c in candidates if (c / "record_manifest.json").exists()),
                candidates[-1])


RECORD_RULED = _find_record_dir()
needs_record = pytest.mark.skipif(
    not (RECORD_RULED / "record_manifest.json").exists(),
    reason="real proof record not present",
)


@needs_record
def test_real_proof_record_audits_and_reports_counts(tmp_path):
    """Run the audit over the real record; assert only that it runs/reports.

    Deliberately asserts no pass/fail: real values are unknown to us and the
    Director sets the spawn threshold after seeing them.
    """
    man = json.loads((RECORD_RULED / "record_manifest.json").read_text())
    res = audit_record(RECORD_RULED / "frames.bin", man)
    assert res["schema_version"] == LOOP_AUDIT_VERSION
    assert res["record"]["frames_bin_sha256"] == man["binary"]["sha256"]
    assert isinstance(res["window_repeats"]["repeat_count"], int)
    assert isinstance(res["record"]["frames"], int)
    assert res["spawn_periodicity"]["threshold"] is None
    out = tmp_path / "audit.json"
    write_audit(RECORD_RULED, out)
    assert json.loads(out.read_text())["record"]["frames"] == man["clock"]["frame_count"]
