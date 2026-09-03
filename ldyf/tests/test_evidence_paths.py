"""Attacker #4 (revision 6): artefact paths must be traversal-free AFTER Windows
normalisation, and verification must refuse links and anything that resolves
outside the evidence directory."""
from __future__ import annotations

import os

import pytest

from ldyf.evidence import (
    EvidenceError,
    _unsafe_relative_path,
    artifact_sha256,
    seal_simulation_result,
    verify_artifact_on_disk,
)


@pytest.mark.parametrize("rel", [
    "a/.. /.. /outside.xml",          # trailing-space component: Windows resolves '.. ' as '..' (A2a)
    "a\\.. \\outside.xml",
    "a/../outside.xml", "..", "../x.xml", "a/./x.xml", "a//x.xml",
    "/abs.xml", "\\\\server\\share\\x.xml", "C:x.xml", "c:/x.xml",
    "x.xml ", " x.xml", "trailingdot./x.xml", "a\x00b.xml", "",
])
def test_unsafe_relative_paths_are_refused(rel):
    assert _unsafe_relative_path(rel)


@pytest.mark.parametrize("rel", ["ruled.tripinfo.xml", "record_ruled/frames.bin", "a/b/c.json", "dots.in.name.xml"])
def test_plain_relative_paths_are_accepted(rel):
    assert not _unsafe_relative_path(rel)


def _doc(rel: str, path) -> dict:
    return {"schema_version": "simulation_result_v1", "run_id": "r", "episode_number": 1, "arm": "ruled",
            "seed": 1, "sumo_version": "1.27.1",
            "artifacts": {"ruled_tripinfo": {"file": rel, "sha256": artifact_sha256(path)}}}


def test_seal_refuses_trailing_space_traversal(tmp_path):
    real = tmp_path / "outside.xml"
    real.write_text("<tripinfos/>\n")
    with pytest.raises(EvidenceError, match="traversal"):
        seal_simulation_result(_doc(".. /outside.xml", real))


def test_verify_refuses_path_forged_after_sealing(tmp_path):
    real = tmp_path / "outside.xml"
    real.write_text("<tripinfos/>\n")
    ev = tmp_path / "ev"
    ev.mkdir()
    sealed = seal_simulation_result(_doc("ok.xml", real))
    sealed["artifacts"]["ruled_tripinfo"]["file"] = ".. /outside.xml"
    with pytest.raises(EvidenceError):
        verify_artifact_on_disk(sealed, "ruled_tripinfo", ev)


def test_verify_refuses_symlinked_artifact(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    real = outside / "ruled.tripinfo.xml"
    real.write_text("<tripinfos/>\n")
    ev = tmp_path / "ev"
    ev.mkdir()
    link = ev / "ruled.tripinfo.xml"
    try:
        os.symlink(real, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted for this user")
    sealed = seal_simulation_result(_doc("ruled.tripinfo.xml", real))
    with pytest.raises(EvidenceError, match="link"):
        verify_artifact_on_disk(sealed, "ruled_tripinfo", ev)


def test_verify_refuses_symlinked_directory(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "ruled.tripinfo.xml").write_text("<tripinfos/>\n")
    ev = tmp_path / "ev"
    ev.mkdir()
    try:
        os.symlink(outside, ev / "sub", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted for this user")
    sealed = seal_simulation_result(_doc("sub/ruled.tripinfo.xml", outside / "ruled.tripinfo.xml"))
    with pytest.raises(EvidenceError, match="link"):
        verify_artifact_on_disk(sealed, "ruled_tripinfo", ev)


def test_verify_accepts_regular_file_inside_evidence_dir(tmp_path):
    ev = tmp_path / "ev"
    (ev / "sub").mkdir(parents=True)
    f = ev / "sub" / "ruled.tripinfo.xml"
    f.write_text("<tripinfos/>\n")
    sealed = seal_simulation_result(_doc("sub/ruled.tripinfo.xml", f))
    assert verify_artifact_on_disk(sealed, "ruled_tripinfo", ev) == f
