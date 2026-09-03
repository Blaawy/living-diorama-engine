"""Proof that the Simulation Record faithfully carries SUMO truth."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from ldyf.coords import UnrealPose, unreal_to_sumo
from ldyf.sumo_record import (
    SAMPLE_STRUCT,
    build_record,
    iter_actor_track,
    read_frame,
)

FCD_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n\n'
    "<!-- generated on 2026-09-03T00:00:00+00:00 by Eclipse SUMO sumo 1.27.1\n"
    "<sumoConfiguration>irrelevant provenance</sumoConfiguration>\n-->\n\n"
    '<fcd-export>\n'
)


def write_fcd(path: Path, timesteps: list[tuple[float, list[tuple[str, str, float, float, float, float]]]]) -> None:
    """timesteps: [(time, [(tag, id, x, y, angle, speed), ...]), ...]"""
    parts = [FCD_HEADER]
    for t, rows in timesteps:
        parts.append(f'    <timestep time="{t:.2f}">\n')
        for tag, aid, x, y, ang, spd in rows:
            parts.append(
                f'        <{tag} id="{aid}" x="{x:.2f}" y="{y:.2f}" angle="{ang:.2f}" '
                f'type="T" speed="{spd:.2f}" pos="0.00" slope="0.00"/>\n'
            )
        parts.append("    </timestep>\n")
    parts.append("</fcd-export>\n")
    path.write_text("".join(parts), encoding="utf-8")


# --- the regression that matters -----------------------------------------

def test_vehicle_and_person_sharing_an_id_stay_separate(tmp_path):
    """Regression: SUMO ids are unique only within a namespace.

    A real proof run contained both `vehicle id="0"` and `person id="0"`.
    Keying the actor table on the bare id merged them, and 200 of 500 vehicle
    ids silently collided -- pedestrian positions were written as vehicle
    samples. This test fails on that bug.
    """
    fcd = tmp_path / "t.fcd.xml"
    write_fcd(fcd, [
        (0.0, [("vehicle", "0", 10.0, 20.0, 90.0, 5.0),
               ("person",  "0", 30.0, 40.0,  0.0, 1.2)]),
    ])
    out = tmp_path / "rec"
    stats = build_record(fcd, out, step_seconds=0.1)

    assert stats.actors == 2, "vehicle 0 and person 0 must be two distinct actors"
    assert stats.actor_kinds == {"vehicle": 1, "person": 1}

    man = json.loads((out / "record_manifest.json").read_text())
    uids = sorted(a["uid"] for a in man["actors"])
    assert uids == ["person:0", "vehicle:0"]

    frame = read_frame(out / "frames.bin", man, 0)
    by_uid = {man["actors"][s["actor_index"]]["uid"]: s for s in frame}
    assert len(by_uid) == 2
    # the vehicle kept its own position, not the pedestrian's
    v = unreal_to_sumo(UnrealPose(by_uid["vehicle:0"]["x"], by_uid["vehicle:0"]["y"], 0, by_uid["vehicle:0"]["yaw"]))
    p = unreal_to_sumo(UnrealPose(by_uid["person:0"]["x"], by_uid["person:0"]["y"], 0, by_uid["person:0"]["yaw"]))
    assert (round(v.x, 3), round(v.y, 3)) == (10.0, 20.0)
    assert (round(p.x, 3), round(p.y, 3)) == (30.0, 40.0)


# --- fidelity -------------------------------------------------------------

def test_positions_round_trip_back_to_sumo(tmp_path):
    fcd = tmp_path / "t.fcd.xml"
    rows = [("vehicle", str(i), i * 3.5, 100.0 - i, (i * 37) % 360, i * 0.5) for i in range(20)]
    write_fcd(fcd, [(0.0, rows)])
    out = tmp_path / "rec"
    build_record(fcd, out, step_seconds=0.1)
    man = json.loads((out / "record_manifest.json").read_text())

    frame = read_frame(out / "frames.bin", man, 0)
    assert len(frame) == 20
    for s in frame:
        i = int(man["actors"][s["actor_index"]]["id"])
        back = unreal_to_sumo(UnrealPose(s["x"], s["y"], s["z"], s["yaw"]))
        assert back.x == pytest.approx(i * 3.5, abs=1e-3)
        assert back.y == pytest.approx(100.0 - i, abs=1e-3)
        assert back.angle % 360 == pytest.approx((i * 37) % 360, abs=1e-3)
        assert s["speed"] == pytest.approx(i * 0.5, abs=1e-3)


def test_frame_index_is_a_pure_function_of_time(tmp_path):
    """Empty frames are still written, so index never drifts from time."""
    fcd = tmp_path / "t.fcd.xml"
    write_fcd(fcd, [
        (0.0, [("vehicle", "a", 1.0, 1.0, 0.0, 1.0)]),
        (0.1, []),                                        # nobody present
        (0.2, [("vehicle", "a", 2.0, 2.0, 0.0, 1.0)]),
    ])
    out = tmp_path / "rec"
    stats = build_record(fcd, out, step_seconds=0.1)
    assert stats.frames == 3
    man = json.loads((out / "record_manifest.json").read_text())
    assert read_frame(out / "frames.bin", man, 1) == []
    assert len(read_frame(out / "frames.bin", man, 2)) == 1
    assert man["clock"]["frame_time_rule"] == "t(i) = t_begin + i * step_seconds"


def test_samples_are_ordered_by_actor_index(tmp_path):
    """Deterministic in-frame ordering, regardless of XML order."""
    fcd = tmp_path / "t.fcd.xml"
    write_fcd(fcd, [
        (0.0, [("vehicle", "a", 0, 0, 0, 0), ("vehicle", "b", 1, 1, 0, 0)]),
        (0.1, [("vehicle", "b", 2, 2, 0, 0), ("vehicle", "a", 3, 3, 0, 0)]),  # reversed
    ])
    out = tmp_path / "rec"
    build_record(fcd, out, step_seconds=0.1)
    man = json.loads((out / "record_manifest.json").read_text())
    for i in (0, 1):
        idx = [s["actor_index"] for s in read_frame(out / "frames.bin", man, i)]
        assert idx == sorted(idx)


# --- determinism ----------------------------------------------------------

def test_record_is_a_pure_function_of_the_fcd(tmp_path):
    fcd = tmp_path / "t.fcd.xml"
    write_fcd(fcd, [(0.0, [("vehicle", str(i), i, i, i % 360, 1.0) for i in range(30)])])
    a, b = tmp_path / "a", tmp_path / "b"
    build_record(fcd, a, step_seconds=0.1)
    build_record(fcd, b, step_seconds=0.1)
    assert (a / "frames.bin").read_bytes() == (b / "frames.bin").read_bytes()
    ma = json.loads((a / "record_manifest.json").read_text())
    mb = json.loads((b / "record_manifest.json").read_text())
    assert ma["binary"]["sha256"] == mb["binary"]["sha256"]


def test_provenance_header_does_not_affect_the_payload_hash(tmp_path):
    """Two FCD files differing only in SUMO's header comment must agree.

    This is the measured behaviour: two identical runs differed in exactly 10
    bytes, all inside that comment.
    """
    body = [(0.0, [("vehicle", "a", 1.0, 2.0, 30.0, 4.0)])]
    f1, f2 = tmp_path / "1.xml", tmp_path / "2.xml"
    write_fcd(f1, body)
    write_fcd(f2, body)
    f2.write_text(
        f2.read_text().replace("2026-09-03T00:00:00+00:00", "2099-12-31T23:59:59+00:00"),
        encoding="utf-8",
    )
    assert f1.read_bytes() != f2.read_bytes(), "the files must actually differ"

    o1, o2 = tmp_path / "o1", tmp_path / "o2"
    build_record(f1, o1, step_seconds=0.1)
    build_record(f2, o2, step_seconds=0.1)
    m1 = json.loads((o1 / "record_manifest.json").read_text())
    m2 = json.loads((o2 / "record_manifest.json").read_text())
    assert m1["source"]["fcd_payload_sha256"] == m2["source"]["fcd_payload_sha256"]


# --- format ---------------------------------------------------------------

def test_binary_layout_matches_the_manifest(tmp_path):
    fcd = tmp_path / "t.fcd.xml"
    write_fcd(fcd, [(0.0, [("vehicle", "a", 1.0, 2.0, 0.0, 3.0)])])
    out = tmp_path / "rec"
    build_record(fcd, out, step_seconds=0.1)
    man = json.loads((out / "record_manifest.json").read_text())
    assert man["binary"]["sample_bytes"] == SAMPLE_STRUCT.size == 24
    raw = (out / "frames.bin").read_bytes()
    (count,) = struct.unpack_from("<I", raw, 0)
    assert count == 1
    assert len(raw) == 4 + 24


def test_manifest_declares_the_coordinate_system(tmp_path):
    fcd = tmp_path / "t.fcd.xml"
    write_fcd(fcd, [(0.0, [("vehicle", "a", 1.0, 2.0, 0.0, 3.0)])])
    out = tmp_path / "rec"
    build_record(fcd, out, step_seconds=0.1)
    cs = json.loads((out / "record_manifest.json").read_text())["coordinate_system"]
    assert cs["linear_units"] == "centimetres"
    assert cs["transform_authority"] == "ldyf.coords"
    assert "left-handed" in cs["axes"]


def test_reading_past_the_end_raises(tmp_path):
    fcd = tmp_path / "t.fcd.xml"
    write_fcd(fcd, [(0.0, [("vehicle", "a", 1.0, 2.0, 0.0, 3.0)])])
    out = tmp_path / "rec"
    build_record(fcd, out, step_seconds=0.1)
    man = json.loads((out / "record_manifest.json").read_text())
    with pytest.raises(IndexError):
        read_frame(out / "frames.bin", man, 99)


def test_actor_track_follows_one_actor(tmp_path):
    fcd = tmp_path / "t.fcd.xml"
    write_fcd(fcd, [
        (0.0, [("vehicle", "a", 0.0, 0.0, 0.0, 0.0), ("vehicle", "b", 9.0, 9.0, 0.0, 0.0)]),
        (0.1, [("vehicle", "b", 9.0, 9.0, 0.0, 0.0)]),
        (0.2, [("vehicle", "a", 5.0, 0.0, 0.0, 0.0)]),
    ])
    out = tmp_path / "rec"
    build_record(fcd, out, step_seconds=0.1)
    man = json.loads((out / "record_manifest.json").read_text())
    track = list(iter_actor_track(out / "frames.bin", man, "vehicle:a"))
    assert [f for f, _ in track] == [0, 2]
    assert track[1][1]["x"] == pytest.approx(500.0)


def test_unknown_actor_raises(tmp_path):
    fcd = tmp_path / "t.fcd.xml"
    write_fcd(fcd, [(0.0, [("vehicle", "a", 1.0, 2.0, 0.0, 3.0)])])
    out = tmp_path / "rec"
    build_record(fcd, out, step_seconds=0.1)
    man = json.loads((out / "record_manifest.json").read_text())
    with pytest.raises(KeyError):
        list(iter_actor_track(out / "frames.bin", man, "vehicle:nope"))
