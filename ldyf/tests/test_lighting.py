"""Tests for the deterministic lighting spec.

The level has a DirectionalLight, a SkyLight and a SkyAtmosphere but zero
PostProcessVolumes, so nothing pinned exposure and Movie Render Queue's auto
meter crushed block interiors and blew the carriageway. These tests guard the
properties that make the replacement deterministic: a Manual exposure with a
zero-width metering range, a paired override_ flag for every setting key
(Unreal ignores a post-process setting whose override boolean is not set), and
a validator that refuses the failure modes.
"""

from __future__ import annotations

import json

import pytest

from ldyf.lighting import (
    LIGHTING_SPEC_VERSION,
    build_lighting,
    exposure_settings,
    fog_settings,
    sky_settings,
    sun_settings,
    validate_lighting,
)

SETTINGS_SECTIONS = ("exposure", "sun", "sky", "fog")


def test_schema_version_and_top_level_keys():
    spec = build_lighting()
    assert spec["schema_version"] == LIGHTING_SPEC_VERSION
    assert set(spec) == {"schema_version", "exposure", "sun", "sky", "fog",
                         "rationale"}


def test_determinism():
    assert json.dumps(build_lighting(), sort_keys=True) == \
        json.dumps(build_lighting(), sort_keys=True)


def test_every_override_flag_present_and_true():
    spec = build_lighting()
    for section in SETTINGS_SECTIONS:
        block = spec[section]
        assert block, section
        for key, value in block.items():
            if key.startswith("override_"):
                assert value is True, (section, key)
            else:
                assert block.get("override_" + key) is True, (section, key)


def test_min_equals_max_brightness():
    exp = build_lighting()["exposure"]
    assert exp["auto_exposure_method"] == "AEM_Manual"
    assert exp["auto_exposure_min_brightness"] == \
        exp["auto_exposure_max_brightness"]
    assert exp["override_auto_exposure_min_brightness"] is True
    assert exp["override_auto_exposure_max_brightness"] is True


def test_manual_mode_also_pins_bias():
    exp = exposure_settings(ev100=13.0)
    assert exp["auto_exposure_bias"] == 13.0
    assert exp["auto_exposure_min_brightness"] == 13.0
    assert exp["auto_exposure_max_brightness"] == 13.0


def test_validate_clean_spec_returns_empty():
    assert validate_lighting(build_lighting()) == []


def test_validate_refuses_auto_exposure_enabled():
    spec = build_lighting()
    spec["exposure"]["auto_exposure_method"] = "AEM_Histogram"
    problems = validate_lighting(spec)
    assert any("auto exposure left enabled" in p for p in problems)


def test_validate_refuses_min_neq_max_brightness():
    spec = build_lighting()
    spec["exposure"]["auto_exposure_max_brightness"] = \
        spec["exposure"]["auto_exposure_min_brightness"] + 1.0
    problems = validate_lighting(spec)
    assert any("must equal" in p and "max" in p for p in problems)


def test_validate_refuses_missing_override():
    spec = build_lighting()
    del spec["exposure"]["override_auto_exposure_bias"]
    problems = validate_lighting(spec)
    assert any("override flag" in p for p in problems)


def test_validate_refuses_false_override():
    spec = build_lighting()
    spec["fog"]["override_density"] = False
    problems = validate_lighting(spec)
    assert any("override flag" in p and "density" in p for p in problems)


def test_validate_refuses_non_positive_intensity():
    spec = build_lighting()
    spec["sun"]["intensity_lux"] = 0.0
    problems = validate_lighting(spec)
    assert any("intensity_lux must be > 0" in p for p in problems)
    spec2 = build_lighting()
    spec2["sky"]["intensity"] = -1.0
    assert any("sky: intensity must be > 0" in p
               for p in validate_lighting(spec2))


def test_validate_refuses_elevation_out_of_range():
    for bad in (0.0, 90.0, -10.0, 120.0):
        spec = build_lighting()
        spec["sun"]["elevation_deg"] = bad
        assert any("elevation_deg must be in (0, 90)" in p
                   for p in validate_lighting(spec))


def test_exposure_valueerror_paths():
    for bad in (None, "x", float("nan"), float("inf")):
        with pytest.raises(ValueError):
            exposure_settings(ev100=bad)


def test_sun_valueerror_paths():
    for bad in (0.0, 90.0, -5.0, 95.0):
        with pytest.raises(ValueError):
            sun_settings(elevation_deg=bad)
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError):
            sun_settings(intensity_lux=bad)
    with pytest.raises(ValueError):
        sun_settings(azimuth_deg=360.0)
    with pytest.raises(ValueError):
        sun_settings(azimuth_deg=-1.0)
    with pytest.raises(ValueError):
        sun_settings(temperature_k=0.0)


def test_sky_and_fog_valueerror_paths():
    for bad in (0.0, -2.0):
        with pytest.raises(ValueError):
            sky_settings(intensity=bad)
    for fn, kw in ((fog_settings, {"density": -1e-6}),
                   (fog_settings, {"height_falloff": -1e-6}),
                   (fog_settings, {"start_distance_cm": -1.0})):
        with pytest.raises(ValueError):
            fn(**kw)


def test_build_lighting_forwards_keywords_and_blocks():
    spec = build_lighting(ev100=14.0, elevation_deg=30.0)
    assert spec["exposure"]["auto_exposure_bias"] == 14.0
    assert spec["sun"]["elevation_deg"] == 30.0
    custom = build_lighting(sun={"elevation_deg": 25.0,
                                 "override_elevation_deg": True})
    assert custom["sun"]["elevation_deg"] == 25.0
    with pytest.raises(TypeError):
        build_lighting(not_a_setting=1)


def test_validate_refuses_missing_settings_block():
    spec = build_lighting()
    del spec["fog"]
    assert any("fog: settings block is missing" in p
               for p in validate_lighting(spec))


def test_defaults_are_bright_clear_daylight():
    sun = build_lighting()["sun"]
    assert sun["elevation_deg"] == 40.0
    assert sun["intensity_lux"] == 100000.0
    assert sun["temperature_k"] == 5800.0
    sky = build_lighting()["sky"]
    assert sky["real_time_capture"] is False
