"""Phase 4 factory: the findings of red-team round 2 (variants of round 1), now refusals.

Round 2 re-attacked the round-1 fixes (EVIDENCE/PHASE_04/redteam/REDTEAM_R2.md).
Its lesson: an insider who re-seals can keep each trip inside its tolerance, or
re-encode a copied run so its hashes look new. So the means are bound to the
record, a teleport mark must be a real standstill, a repeat must BEHAVE like
another run, and -- the only complete answer -- `verify --resimulate` runs the
locked world again.
"""
from __future__ import annotations

import hashlib
import math
import re
import shutil
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ldyf.factory import pipeline as P
from ldyf.factory.facts import (ROUTE_OFFSET_DELTA_M, FactsError, extract_facts)
from ldyf.factory.record import load_record

from .factory_support import clone, copy_sim, dump, load, reseal_simulation
from .test_factory_package import _sumo


def _rewrite_trips(path: Path, fn) -> None:
    """Apply fn(attrs) -> attrs to every <tripinfo .../> line, keeping the rest byte for byte."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        if line.lstrip().startswith("<tripinfo "):
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', line))
            attrs = fn(attrs)
            indent = line[:len(line) - len(line.lstrip())]
            line = indent + "<tripinfo " + " ".join(f'{k}="{v}"' for k, v in attrs.items()) + "/>\n"
        out.append(line)
    path.write_text("".join(out), encoding="utf-8")


def test_n1_marking_ordinary_trips_teleported_does_not_escape_the_check(
        factory_pkg, factory_brief, factory_world, tmp_path):
    """N-1: every arrived trip marked teleported, 59 s added to arrival and duration, route
    tripled. A teleport mark must be a real standstill of the whole limit."""
    sim = copy_sim(factory_pkg, tmp_path)

    def lie(a):
        if a.get("vaporized") != "teleport":
            a["vaporized"] = "teleport"
            a["arrival"] = "%.2f" % (float(a["arrival"]) + 59)
            a["duration"] = "%.2f" % (float(a["duration"]) + 59)
            a["routeLength"] = "%.2f" % (float(a["routeLength"]) * 3)
        return a
    _rewrite_trips(sim / "ruled.tripinfo.xml", lie)
    reseal_simulation(sim)
    with pytest.raises(FactsError) as err:
        extract_facts(sim, factory_brief, factory_world)
    assert err.value.code == "conflicting_consequence"
    assert "teleport" in err.value.message


def test_n2_a_systematic_lie_inside_every_trips_tolerance_is_refused(
        factory_pkg, factory_brief, factory_world, tmp_path):
    """N-2: every ruled route pushed 25 m up (inside its own 30 m + 3 % band): the narrated
    route change would read about 25 m longer. The mean is bound to the record."""
    sim = copy_sim(factory_pkg, tmp_path)

    def lie(a):
        if a.get("vaporized") != "teleport":
            a["routeLength"] = "%.2f" % (float(a["routeLength"]) + 25.0)
        return a
    _rewrite_trips(sim / "ruled.tripinfo.xml", lie)
    reseal_simulation(sim)
    with pytest.raises(FactsError) as err:
        extract_facts(sim, factory_brief, factory_world)
    assert err.value.code == "conflicting_consequence" and "mean route length" in err.value.message
    assert ROUTE_OFFSET_DELTA_M <= 1.0


def _reencode_record(record_dir: Path, dz: float) -> None:
    """Change one sample's z (unused by every measurement) and re-declare the sha256:
    the record's hash is new, its content is the same run."""
    frames = record_dir / "frames.bin"
    data = bytearray(frames.read_bytes())
    count = struct.unpack_from("<I", data, 0)[0]
    assert count > 0
    off = 4 + 4 + 4 + 4                       # header, actor index, x, y -> z
    z = struct.unpack_from("<f", data, off)[0]
    struct.pack_into("<f", data, off, z + dz)
    frames.write_bytes(bytes(data))
    man = load(record_dir / "record_manifest.json")
    man["binary"]["sha256"] = hashlib.sha256(bytes(data)).hexdigest()
    dump(record_dir / "record_manifest.json", man)


def test_n3_a_repeat_that_is_the_episode_re_encoded_is_refused(
        factory_pkg, factory_brief, factory_world, tmp_path):
    """N-3: both repeats are the episode's own run, the seed replaced EVERYWHERE (JSON,
    sealed result, agent logs, SUMO's tripinfo header) and each record re-encoded so its
    hash is new. Its trips still end at the same seconds: it is the same run."""
    reps = []
    for k, seed in enumerate(factory_brief["replicate_seeds"]):
        d = tmp_path / "reps" / str(seed)
        shutil.copytree(factory_pkg / "sim", d)
        old = str(factory_brief["seed"])
        for name in ("simulation.json", "agents_baseline.json", "agents_ruled.json",
                     "baseline.tripinfo.xml", "ruled.tripinfo.xml"):
            p = d / name
            p.write_text(p.read_text(encoding="utf-8").replace(old, str(seed)), encoding="utf-8")
        res = load(d / "simulation_result.json")
        res["seed"] = seed
        for arm in ("baseline", "ruled"):
            res["run_report"][arm]["seed"] = seed
            _reencode_record(d / f"record_{arm}", 0.25 * (k + 1))
        dump(d / "simulation_result.json", res)
        reseal_simulation(d)
        load_record(d / "record_ruled")          # the re-encoded record is a valid record
        reps.append(d)
    with pytest.raises(FactsError) as err:
        extract_facts(factory_pkg / "sim", factory_brief, factory_world, replicate_dirs=reps)
    assert err.value.code == "conflicting_consequence", err.value.message
    assert "share of trips ending at another second" in err.value.message


def test_n6_a_console_log_name_outside_the_simulation_folders_is_not_exempt(complete_pkg, tmp_path):
    """N-6: only SUMO's own console logs, in sim/ and replicates/<seed>/, are unlisted."""
    for extra in ("episode_uncensored.sumo.log", "render/hook/alt_cut.sumo.log"):
        pkg = clone(complete_pkg, tmp_path / extra.replace("/", "_"))
        (pkg / extra).write_bytes(b"smuggled")
        with pytest.raises(P.PipelineError) as err:
            P.verify_package(pkg)
        assert err.value.code == "package_changed" and "not in the manifest" in err.value.message


def test_the_refusal_never_recommends_deleting_a_finished_package(complete_pkg, tmp_path):
    pkg = clone(complete_pkg, tmp_path / "pkg")
    with pytest.raises(P.PipelineError) as err:
        P.run_factory(P.Path(__file__).resolve().parents[1] / "factory" / "briefs" /
                      "close_baker_avenue.json", pkg, render=False, log=lambda s: None)
    assert err.value.code == "package_is_finished" and "no-resume" not in err.value.message


@pytest.mark.skipif(_sumo() is None, reason="needs SUMO")
def test_resimulation_refuses_a_resealed_edit_that_passes_every_cross_check(
        factory_pkg, factory_brief, factory_world, tmp_path):
    """The complete answer to an insider: run the locked world again. One ruled trip's
    waiting time moved by 1 s (inside every tolerance, every hash re-sealed) is caught."""
    pkg = tmp_path / "pkg"
    sim = copy_sim(factory_pkg, pkg)
    done = []

    def lie(a):
        if not done and a.get("vaporized") != "teleport" and float(a["waitingTime"]) > 5:
            a["waitingTime"] = "%.2f" % (float(a["waitingTime"]) + 1.0)
            done.append(a["id"])
        return a
    _rewrite_trips(sim / "ruled.tripinfo.xml", lie)
    reseal_simulation(sim)
    extract_facts(sim, factory_brief, factory_world)          # every cross-check still agrees
    with pytest.raises(P.PipelineError) as err:
        P.resimulate(pkg, factory_brief, factory_world, tmp_path / "scratch", ports=(56011, 56012),
                     repeats=False)
    assert err.value.code == "simulation_not_reproduced" and "ruled tripinfo" in err.value.message


_ = (math, ET)
