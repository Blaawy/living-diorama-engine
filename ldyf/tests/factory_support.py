"""Shared helpers for the Phase 4 factory tests.

The factory tests run against a REAL sealed episode: the package the factory
built from `ldyf/factory/briefs/close_baker_avenue.json`. It is looked for, in
order, at

    $LDYF_FACTORY_PACKAGE
    <repo>/../PHASE_04/episodes/close_baker_avenue      (the workspace layout)
    <repo>/../evidence/episode/close_baker_avenue       (a MASTER extraction)

The package is READ-ONLY to the tests. A test that needs to damage evidence
copies what it needs into its own tmp_path first (`copy_sim`).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from ldyf.evidence import artifact_sha256, seal_simulation_result
from ldyf.factory.world import REPO_ROOT

BRIEF_PATH = REPO_ROOT / "ldyf" / "factory" / "briefs" / "close_baker_avenue.json"
WINDOWS_TTS = sys.platform == "win32" and shutil.which("powershell") is not None
FFMPEG = shutil.which("ffmpeg") is not None


def find_package() -> Path | None:
    cands = []
    if os.environ.get("LDYF_FACTORY_PACKAGE"):
        cands.append(Path(os.environ["LDYF_FACTORY_PACKAGE"]))
    cands.append(REPO_ROOT.parent / "PHASE_04" / "episodes" / "close_baker_avenue")
    cands.append(REPO_ROOT.parent / "evidence" / "episode" / "close_baker_avenue")
    for c in cands:
        if (c / "sim" / "simulation.json").is_file() and (c / "sim" / "record_ruled" / "frames.bin").is_file():
            return c
    return None


def copy_sim(pkg: Path, dst: Path) -> Path:
    """A private, writable copy of the package's sealed simulation directory."""
    out = dst / "sim"
    shutil.copytree(pkg / "sim", out)
    return out


def load(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump(path: Path, doc) -> None:
    Path(path).write_text(json.dumps(doc, sort_keys=True, indent=1), encoding="utf-8")


def reseal_simulation(sim_dir: Path) -> None:
    """Make a doctored simulation directory hash-consistent again.

    This is what an INSIDER with write access could do: after changing an
    artefact, recompute its sha256 in the sealed result, re-seal the result and
    point simulation.json at the new seal. Every hash then verifies. The tests
    use it to show that the factory's CROSS-CHECKS, not only its hashes, catch a
    consequence that the record does not support.
    """
    result = load(sim_dir / "simulation_result.json")
    for name, row in result["artifacts"].items():
        row["sha256"] = artifact_sha256(sim_dir / row["file"])
    result["result_hash"] = ""
    result = seal_simulation_result(result)
    dump(sim_dir / "simulation_result.json", result)
    sim = load(sim_dir / "simulation.json")
    sim["simulation_result_hash"] = result["result_hash"]
    dump(sim_dir / "simulation.json", sim)


#: Files at least this large are hard-linked by `clone`; smaller ones are copied.
LINK_FROM_BYTES = 1 << 20


def clone(src: Path, dst: Path, *, skip: tuple[str, ...] = ()) -> Path:
    """Copy a package. Documents are copied; only large media (records, segments,
    waves, the episode) are hard-linked, which is safe as long as a test REPLACES
    such a file (unlink, then write) instead of editing it in place.

    The documents are real copies because a hard link is the same file: while a
    test holds a linked `truth_audit.json`, Windows refuses the factory's own
    atomic replace of the sealed one, and one in-place write would damage it.
    """
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if any(rel.as_posix().startswith(s) for s in skip):
            continue
        out = dst / rel
        if p.is_dir():
            out.mkdir(parents=True, exist_ok=True)
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            if p.stat().st_size < LINK_FROM_BYTES:
                shutil.copy2(p, out)
                continue
            try:
                os.link(p, out)
            except OSError:
                shutil.copy2(p, out)
    return dst
