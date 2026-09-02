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


# ---------------------------------------------------------------------------
# Director-revision lighting lane (lighting_profile="dna_daylight")
# ---------------------------------------------------------------------------


def test_default_lighting_lane_is_the_identity_lane(profiles) -> None:
    """The default lane adds nothing: today's dna lighting, byte-for-byte.

    A render that omits the new parameter must be provably identical to today's,
    so the default lighting_profile="dna" has to resolve to the very same dict
    the plain resolve_style("dna") always returned.
    """
    plain = profiles.resolve_style(profiles.DNA_STYLE)
    defaulted = profiles.resolve_style(profiles.DNA_STYLE, lighting_profile="dna")
    assert defaulted == plain
    assert defaulted["lighting"] == plain["lighting"]


def test_dna_daylight_lane_is_genuine_late_morning(profiles) -> None:
    """The lane reads as real late-morning daylight, not a renamed twilight.

    Values pinned with the reasoning each one was chosen for -- all eight were
    tuned against REAL renders (not reasoned about in the abstract), because
    the first cut (elevation 50.0 with dna's twilight-tuned key/fill energies
    and background_strength=0.85 left untouched) blew the frame out to solid
    white. At -3.0 degrees elevation the Nishita sky's direct-sun contribution
    is negligible, so dna's large key_energy (110000) and fill_energy (15500)
    area lights carry nearly all the illumination; at 50.0 degrees the
    physically modeled sun itself is enormously brighter, and stacking the old
    area-light energies on top of it double-counts the light source:

    - sun_elevation_deg 50.0: late morning ~10:30-11:00 at ~40N near the
      equinox gives a solar elevation of roughly 45-60 degrees; 50.0 sits
      mid-band and is clearly above the horizon (today's dna is -3.0).
    - sun_intensity 0.05: cut from dna's 1.0 -- at this elevation the
      physical sun is bright enough on its own; 1.0 blew the frame to white.
      (Lowered once more from an intermediate 0.08 while investigating the
      render's witness-closure tolerance; that investigation later proved the
      tolerance failure was a real camera-settle timing issue, not lighting
      noise -- see camera_movement_planner.py -- but 0.05 was independently
      confirmed by a real render to still look bright, clean daylight.)
    - key_color (1.0, 0.96, 0.90): neutral daylight white with a trace of
      morning warmth; the orange dominance of dna's (1.0, 0.70, 0.42) is gone
      (the single biggest lever against the "golden" complaint).
    - key_energy 8000.0 / fill_energy 3000.0: cut from dna's 110000/15500 --
      those area lights were compensating for the near-zero twilight sky and
      are now largely redundant; left unchanged they compounded the blowout.
      Measurement on real frames confirms they are nearly inert: +1000 W of
      key_energy (fill scaled alongside) moves the ground only +0.113 luma,
      so nobody should reach for key_energy expecting it to rescue exposure.
    - key_size 160.0 / fill_size 220.0: enlarged from dna's 55.0/130.0 to
      soften the area lights' shadows/highlights -- a real render confirmed
      this still reads as clean bright daylight, not hazy or flat.
    - background_strength 0.23: LOWER than dna's own 0.30, not higher --
      counterintuitive, but the underlying Nishita sky radiance at 50 degrees
      is already far brighter than at -3 degrees for the same multiplier, so
      a smaller multiplier on a much brighter sky still reads brighter overall
      than a larger multiplier on a twilight sky (confirmed by rendering both
      and comparing, not assumed from the numbers alone). Cut once more from
      0.25 to 0.20 for the wall-side glare: the Director reported harsh white
      glare around the wall side; the measured sky/horizon band at the top of
      frame read 207-229 luma against 115-170 on the ground. This knob
      multiplies the whole sky Background, and since the sky is the scene's
      dominant ambient source the ground falls FASTER than the sky: -3.098 vs
      -2.005 luma per 0.01, measured on real frames. 0.20 is a balance --
      overall brightness down about 5%, bright pixels (>=215) down about 11%,
      ground still 133 luma; 0.12 was measured and rejected (ground 108 =
      gloom). The wall is dark-albedo (~0.045-0.052), so the bright band is
      sky, not wall -- the glare is sky-borne, not wall-borne.
    - dust_density 0.05: cut hard from dna's 2.0 haze -- haze was the
      dominant flattening/graying factor once the blowout was fixed; the
      Director explicitly rejects heavy haze.
    - air_density 0.9 / ozone_density 1.0: cut from dna's 1.35/1.8 -- those
      values were tuned for a twilight scene and, combined with a midday sun,
      produced excess Rayleigh/ozone scattering that kept the sky pale and
      washed out rather than reading as a normal clear-day sky.

    volume_density/volume_anisotropy (the atmosphere fog) were tried at lower
    values here during the witness-closure investigation and reverted at the
    time: measured witness difference got WORSE, not better, as fog density
    went down (0.0011 -> 1.147628, 0.00015 -> 1.620709, 0.0 -> 1.735422),
    proving the fog was masking a real structural difference rather than
    causing noise. That difference was the closing camera still moving, and it
    was fixed elsewhere. SUPERSEDED: volume_density is now deliberately set to
    0.0 for the Director's clear-air presentation (the V5 camera never moves,
    so nothing is left for fog to mask); volume_anisotropy is still inherited
    -- see the "untouched" test below.
    """
    dna = profiles.resolve_style(profiles.DNA_STYLE)
    day = profiles.resolve_style(profiles.DNA_STYLE, lighting_profile="dna_daylight")
    lighting = day["lighting"]

    assert lighting["sun_elevation_deg"] == 50.0
    assert lighting["sun_elevation_deg"] > 0.0, "sun must be above the horizon"

    assert lighting["sun_intensity"] == 0.05
    assert lighting["sun_intensity"] < dna["lighting"]["sun_intensity"], (
        "the physically-modeled sun is far brighter at this elevation; the old "
        "twilight sun_intensity would blow the frame out (confirmed by render)"
    )

    red, green, blue = lighting["key_color"]
    assert (red, green, blue) == (1.0, 0.96, 0.90)
    assert green > 0.9 and blue > 0.85, "no strong orange cast may remain"
    assert green - dna["lighting"]["key_color"][1] > 0.2, (
        "the key must be meaningfully less orange than today's (1.0, 0.70, 0.42)"
    )

    assert lighting["key_energy"] == 8000.0
    assert lighting["key_energy"] < dna["lighting"]["key_energy"] / 5, (
        "the key area light was compensating for a near-zero twilight sky; "
        "left at dna's 110000 it double-counts the now-real sun and blows out"
    )
    assert lighting["fill_energy"] == 3000.0
    assert lighting["fill_energy"] < dna["lighting"]["fill_energy"] / 2

    assert lighting["key_size"] == 160.0
    assert lighting["key_size"] > dna["lighting"]["key_size"], (
        "a larger area light softens shadows/highlights under the brighter sun"
    )
    assert lighting["fill_size"] == 220.0
    assert lighting["fill_size"] > dna["lighting"]["fill_size"]

    assert lighting["background_strength"] == 0.23
    assert lighting["background_strength"] < dna["lighting"]["background_strength"], (
        "counterintuitively lower than dna's 0.30 -- the underlying Nishita "
        "sky is already far brighter at 50 degrees elevation than at -3, so a "
        "smaller multiplier here still reads brighter overall (confirmed by "
        "rendering both, not assumed from the numbers alone)"
    )

    assert lighting["dust_density"] == 0.05
    assert lighting["dust_density"] < dna["lighting"]["dust_density"] - 1.5, (
        "the air must be meaningfully cleaner than today's 2.0 haze"
    )

    assert lighting["air_density"] == 0.9
    assert lighting["air_density"] < dna["lighting"]["air_density"]
    assert lighting["ozone_density"] == 1.0
    assert lighting["ozone_density"] < dna["lighting"]["ozone_density"]


def test_dna_daylight_lane_background_strength_is_exactly_0_23(profiles) -> None:
    """The daylight lane's sky multiplier: 0.23, paired with the clear-air lane.

    0.25 -> 0.20 was the wall-side glare fix. 0.20 -> 0.23 restores the ground
    brightness the district-air haze had been contributing once that haze stopped
    being drawn: measured on identical-camera frames, clear air at 0.20 put the
    ground at 122.65 (below the pre-fog-work 130.5); at 0.23 it is 129.39 with the
    sky at 214.88 and the full contrast win kept.
    """
    day = profiles.resolve_style(profiles.DNA_STYLE, lighting_profile="dna_daylight")
    assert day["lighting"]["background_strength"] == 0.23


def test_dna_daylight_lane_never_leaks_pinned_grade_keys(profiles) -> None:
    """Exposure / view_transform / look never leak into the free lighting lane.

    Those three are pinned by the render-profile digest
    (render_execution_spec._VERIFIED_INHERITED) and must stay out of the free
    lighting lane, where a future edit could silently change the grade.
    """
    day = profiles.resolve_style(profiles.DNA_STYLE, lighting_profile="dna_daylight")
    for key in ("exposure", "view_transform", "look"):
        assert key not in day["lighting"], f"lane leaked pinned grade key {key}"


def test_dna_daylight_lane_keeps_the_ground_lights_undimmed(profiles) -> None:
    """key_energy/fill_energy stay 8000.0/3000.0 -- pinned reviewed constants.

    These energies are pinned because they are reviewed constants, not because
    dimming them would gloom the ground: measurement on real frames shows they
    are nearly inert (a 37.5% key increase moved the ground 0.34 luma), so a
    future editor must not expect them to compensate for a sky change.
    """
    day = profiles.resolve_style(profiles.DNA_STYLE, lighting_profile="dna_daylight")
    assert day["lighting"]["key_energy"] == 8000.0
    assert day["lighting"]["fill_energy"] == 3000.0


def test_dna_daylight_lane_leaves_pinned_grade_and_other_knobs_untouched(profiles) -> None:
    """The lane never touches the pinned digest set, nor the knobs left alone.

    exposure, view transform and look are pinned in the render-profile digest
    (render_execution_spec._VERIFIED_INHERITED), so the lane must not move
    them. Everything the daylight target genuinely does not need -- light
    positions, fill color, volume scattering -- stays exactly as dna has it
    today; sun_intensity/air_density/ozone_density/key_energy/fill_energy/
    key_size/fill_size are NOT in this list because the daylight lane
    deliberately overrides all seven (see
    test_dna_daylight_lane_is_genuine_late_morning).
    """
    dna = profiles.resolve_style(profiles.DNA_STYLE)
    day = profiles.resolve_style(profiles.DNA_STYLE, lighting_profile="dna_daylight")
    assert day["settings"] == dna["settings"]
    assert day["settings"] == {"exposure": 1.25, "look": "AgX - Medium High Contrast"}
    for key in (
        "key_location",
        "fill_location",
        "fill_color",
        "volume_anisotropy",
    ):
        assert day["lighting"][key] == dna["lighting"][key], f"lane moved {key}"
    # volume_density is NO LONGER inherited: the lane deliberately zeroes the
    # LD_ATMOSPHERE fog for the Director's clear-air presentation. The dusk dna
    # lane keeps its own 0.0011, and volume_anisotropy above is still inherited,
    # so only the density moved.
    assert dna["lighting"]["volume_density"] == 0.0011
    assert day["lighting"]["volume_density"] == 0.0


def test_dna_daylight_lane_has_no_atmospheric_fog(profiles) -> None:
    """The clear-air law: the daylight lane carries no participating media.

    The Director rejected the milky/washed-out look. Measured on
    identical-camera frames, zeroing this volume lifted city-band local
    contrast 4.874 -> 7.125, widened the tonal spread 144 -> 185 and dropped the
    darkest percentile 69 -> 16 -- the veil had been holding blacks 53 levels
    off the floor -- while the sky moved only 0.65 luma. Pinned so a future edit
    cannot quietly reintroduce the haze.
    """
    day = profiles.resolve_style(profiles.DNA_STYLE, lighting_profile="dna_daylight")
    assert day["lighting"]["volume_density"] == 0.0


def test_dna_daylight_lane_is_lighting_only(profiles) -> None:
    """The lane restyles lighting only; materials and practical scale are dna's."""
    dna = profiles.resolve_style(profiles.DNA_STYLE)
    day = profiles.resolve_style(profiles.DNA_STYLE, lighting_profile="dna_daylight")
    assert day["materials"] == dna["materials"]
    assert day["practical_scale"] == dna["practical_scale"] == 1.15


def test_unknown_lighting_profile_is_refused(profiles) -> None:
    """A typo'd lighting lane fails loudly instead of silently rendering dna."""
    with pytest.raises(ValueError, match="lighting_profile"):
        profiles.resolve_style(profiles.DNA_STYLE, lighting_profile="dna_night")


def test_daylight_lane_adds_no_animation(profiles) -> None:
    """The lane is pure data: no animation machinery lives in the profiles.

    Regression guard for the no-animation constraint: the real applier that
    could animate lights/world/exposure (apply_motion_plan) is driven only by
    motion directives and never by a style lane, and this module -- which the
    lane is pure data in -- must contain none of that machinery at all.
    """
    source = PROFILES_PATH.read_text(encoding="utf-8")
    assert "keyframe_insert" not in source
    assert "keyframes" not in source
