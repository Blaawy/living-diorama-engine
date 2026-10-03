"""Session fixtures for the Phase 4 factory tests (see factory_support.py).

Nothing here runs unless a factory test asks for it, so the Phase 1-3 suite is
unaffected. Every fixture is computed ONCE per session from the real sealed
episode and must be treated as read-only; copy before mutating.
"""
from __future__ import annotations

import copy

import pytest

from .factory_support import BRIEF_PATH, FFMPEG, WINDOWS_TTS, clone, find_package, load


@pytest.fixture(scope="session")
def factory_pkg():
    pkg = find_package()
    if pkg is None:
        pytest.skip("no sealed factory episode package on this machine")
    return pkg


@pytest.fixture(scope="session")
def factory_brief():
    from ldyf.factory.brief import normalise_brief
    return normalise_brief(load(BRIEF_PATH))


@pytest.fixture(scope="session")
def factory_world(factory_brief):
    from ldyf.factory.world import load_world
    return load_world(factory_brief["world"])


@pytest.fixture(scope="session")
def factory_facts(factory_pkg, factory_brief, factory_world):
    from ldyf.factory.facts import extract_facts
    reps = [factory_pkg / "replicates" / str(s) for s in factory_brief["replicate_seeds"]]
    return extract_facts(factory_pkg / "sim", factory_brief, factory_world, replicate_dirs=reps)


@pytest.fixture(scope="session")
def factory_recs(factory_pkg):
    from ldyf.factory.record import load_record
    return {arm: load_record(factory_pkg / "sim" / f"record_{arm}") for arm in ("baseline", "ruled")}


@pytest.fixture(scope="session")
def factory_net(factory_world):
    import sumolib
    return sumolib.net.readNet(factory_world["_net_path"])


@pytest.fixture(scope="session")
def factory_blocks(factory_world):
    from ldyf.factory.camera import load_blocks
    from ldyf.factory.world import REPO_ROOT
    return load_blocks(REPO_ROOT / factory_world["unreal"]["city_layout"])


@pytest.fixture(scope="session")
def factory_story(factory_facts, factory_brief):
    from ldyf.factory.story import select_story
    return select_story(factory_facts, factory_brief)


@pytest.fixture(scope="session")
def factory_shots(factory_story, factory_facts, factory_recs, factory_net, factory_blocks,
                  factory_brief):
    from ldyf.factory.camera import plan_shots
    return plan_shots(factory_story, factory_facts, factory_recs, factory_net, factory_blocks,
                      factory_brief["resolution"])


@pytest.fixture(scope="session")
def factory_narration(factory_story, factory_facts, factory_shots, factory_brief):
    from ldyf.factory.narration import bind_narration
    return bind_narration(factory_story, factory_facts, factory_shots,
                          rate=factory_brief["voice_rate"])


@pytest.fixture()
def mutable(request):
    """`mutable(doc)` -> a deep copy a test may change freely."""
    return copy.deepcopy


@pytest.fixture(scope="session")
def planned_pkg(factory_pkg, tmp_path_factory):
    """The real simulations taken through the real pipeline, without Unreal."""
    if not (WINDOWS_TTS and FFMPEG):
        pytest.skip("needs the local Windows voice and ffmpeg")
    dst = tmp_path_factory.mktemp("planned") / "pkg"
    dst.mkdir()
    for part in ("sim", "replicates"):
        clone(factory_pkg / part, dst / part)
    from ldyf.factory import pipeline as P
    out = P.run_factory(BRIEF_PATH, dst, render=False, log=lambda s: None)
    assert out["outcome"] == "planned_not_rendered" and out["audit_pass"] is True
    return dst


@pytest.fixture(scope="session")
def complete_pkg(factory_pkg):
    if not (factory_pkg / "package.json").is_file():
        pytest.skip("the factory package on this machine is not a finished episode")
    return factory_pkg
