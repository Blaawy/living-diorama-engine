"""Style-profile contract for the Phase 15 visual bake-off (pure Python).

Style ``a`` must be the identity profile -- the reviewed benchmark look with
zero overrides -- and styles ``b``/``c`` must be real, distinct treatments
whose material overrides stay inside the family's known roles. Geography can
never live in a profile; these tests pin all of that without Blender.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROFILES_PATH = REPO_ROOT / "visual" / "blender" / "scripts" / "style_profiles.py"


def load_profiles():
    """Import the pure style-profile module from its file path."""
    spec = importlib.util.spec_from_file_location("style_profiles_under_test", PROFILES_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["style_profiles_under_test"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules["style_profiles_under_test"]
    return module


@pytest.fixture(name="profiles")
def profiles_fixture():
    """The style-profiles module under test."""
    return load_profiles()


def test_module_never_imports_bpy(profiles) -> None:
    """The profile layer stays pure so ordinary pytest can own it."""
    source = PROFILES_PATH.read_text(encoding="utf-8")
    assert "import bpy" not in source and "import bmesh" not in source


def test_three_styles_exist(profiles) -> None:
    """Exactly the bake-off styles a, b, and c resolve."""
    assert profiles.STYLE_NAMES == ("a", "b", "c")
    for name in profiles.STYLE_NAMES:
        assert profiles.resolve_style(name)["name"] == name


def test_unknown_style_is_refused(profiles) -> None:
    """A typo'd style fails loudly instead of silently rendering style a."""
    with pytest.raises(ValueError, match="unknown style"):
        profiles.resolve_style("d")


def test_style_a_is_the_identity_profile(profiles) -> None:
    """Style a carries zero overrides: the benchmark look is untouched."""
    profile = profiles.resolve_style("a")
    assert profile["materials"] == {}
    assert profile["practical_scale"] == 1.0
    assert profile["lighting"]["sun_elevation_deg"] == -0.8
    assert profile["settings"]["exposure"] == 1.5


def test_styles_b_and_c_are_distinct_treatments(profiles) -> None:
    """The experiment fails if the styles are near-identical; pin divergence."""
    a = profiles.resolve_style("a")
    b = profiles.resolve_style("b")
    c = profiles.resolve_style("c")
    assert b["materials"] and c["materials"], "b and c must restyle materials"
    assert b["lighting"]["sun_elevation_deg"] > 5.0, "style b is a bright readable diorama"
    assert c["lighting"]["background_strength"] < a["lighting"]["background_strength"], (
        "style c surrounds the world-exhibit with darkness"
    )
    assert b["lighting"]["volume_density"] < a["lighting"]["volume_density"]
    assert c["lighting"]["volume_density"] > a["lighting"]["volume_density"]
    assert b["practical_scale"] < 1.0 < c["practical_scale"]


def test_material_overrides_stay_inside_known_roles(profiles) -> None:
    """Profiles may restyle known roles only -- never invent or drop roles."""
    roles = set(profiles.MATERIAL_ROLES)
    for name in (*profiles.STYLE_NAMES, profiles.DNA_STYLE):
        overrides = profiles.resolve_style(name)["materials"]
        unknown = set(overrides) - roles
        assert not unknown, f"style {name} overrides unknown roles: {sorted(unknown)}"


def test_profiles_carry_no_geography(profiles) -> None:
    """No profile smuggles world-space placement into a visual treatment."""
    forbidden = ("center", "location", "path", "radius_", "look_at", "district", "boundary")
    for name in (*profiles.STYLE_NAMES, profiles.DNA_STYLE):
        profile = profiles.resolve_style(name)
        for key in profile["materials"]:
            for marker in forbidden:
                assert marker not in key, f"geography-like key in style {name}: {key}"


def test_dna_profile_synthesizes_the_bakeoff(profiles) -> None:
    """The Visual DNA sits between the bake-off extremes by construction.

    C's exhibit separation with B's legibility: the surround is darker than
    the benchmark but far brighter than C; exposure sits between B's bright
    model grade and the benchmark's cinematic grade; the scar override is a
    dark charcoal family; window life stays on (practicals above B's).
    """
    a = profiles.resolve_style("a")
    b = profiles.resolve_style("b")
    c = profiles.resolve_style("c")
    dna = profiles.resolve_style(profiles.DNA_STYLE)
    assert dna["name"] == "dna"
    background = dna["lighting"]["background_strength"]
    assert c["lighting"]["background_strength"] < background < a["lighting"]["background_strength"]
    exposure = dna["settings"]["exposure"]
    assert b["settings"]["exposure"] < exposure < a["settings"]["exposure"]
    scar = dna["materials"]["scar_concrete"]["color"]
    assert max(scar) < 0.08, "the DNA scar stays in the dark charcoal family"
    assert dna["practical_scale"] > b["practical_scale"], "window life stays on in the DNA"
