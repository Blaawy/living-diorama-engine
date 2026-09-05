"""Tests for ``road_surface_v1`` â€” dry asphalt must read as dry asphalt.

The rendered carriageway read as wet under a clear midday sun (broad specular
sheets, mirror highlights).  These tests guard the authored dry values, the
hard roughness floor / specular ceiling that refuse the wet band, and the
marking-brightness rule that keeps the paint legible while the sheen is
killed.
"""

from __future__ import annotations

import json

import pytest

from ldyf.road_surface import (
    DRY_ASPHALT_ROUGHNESS,
    DRY_ASPHALT_ROUGHNESS_FLOOR,
    MARKING_BRIGHTNESS_FLOOR,
    P_ROUGH,
    P_SPEC,
    P_TINT,
    SPECULAR_CEILING,
    SURFACE_PRESETS,
    surface_parameters,
    validate_surface,
)


def test_surface_parameters_are_deterministic():
    a = surface_parameters("dry_asphalt")
    b = surface_parameters("dry_asphalt")
    assert a == b
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    # no -0.0 / float dust between calls
    assert all(repr(v) != "-0.0" for v in a.values()
               for v in (v if isinstance(v, list) else [v]))


def test_every_preset_validates_clean():
    """Each authored row must pass its own rules (damp included, because it
    is the one row that declares itself below the *dry* floor)."""
    for preset in SURFACE_PRESETS:
        problems = validate_surface(surface_parameters(preset))
        assert problems == [], "%s: %s" % (preset, problems)


def test_validate_rejects_too_glossy_roughness():
    """A roughness below the dry-asphalt floor is the wet-sheen defect."""
    params = surface_parameters("dry_asphalt")
    params[P_ROUGH] = 0.4
    problems = validate_surface(params)
    assert any("below the dry-asphalt floor" in p for p in problems)
    assert any(str(DRY_ASPHALT_ROUGHNESS_FLOOR) in p for p in problems)


def test_validate_rejects_too_high_specular():
    params = surface_parameters("concrete_sidewalk")
    params[P_SPEC] = 0.4
    problems = validate_surface(params)
    assert any("above the ceiling" in p for p in problems)
    assert any(str(SPECULAR_CEILING) in p for p in problems)


def test_validate_rejects_out_of_range_value():
    params = surface_parameters("dry_asphalt")
    params[P_TINT] = [1.0, 1.0, 1.3]
    problems = validate_surface(params)
    assert any("out of range [0, 1]" in p for p in problems)
    params = surface_parameters("dry_asphalt")
    params[P_ROUGH] = -0.1
    assert any("out of range [0, 1]" in p for p in validate_surface(params))


def test_validate_rejects_dulled_marking():
    """Killing the sheen must not dull the paint."""
    params = surface_parameters("painted_marking")
    params[P_TINT] = [0.2, 0.2, 0.2]
    problems = validate_surface(params)
    assert any("brightness floor" in p for p in problems)
    assert any(str(MARKING_BRIGHTNESS_FLOOR) in p for p in problems)


def test_wheel_polish_lowers_roughness_but_stays_above_floor():
    dry = surface_parameters("dry_asphalt")
    polished = surface_parameters("dry_asphalt", wheel_polish=True)
    assert polished[P_ROUGH] < dry[P_ROUGH]
    assert polished[P_ROUGH] == pytest.approx(DRY_ASPHALT_ROUGHNESS - 0.04)
    assert polished[P_ROUGH] >= DRY_ASPHALT_ROUGHNESS_FLOOR
    assert validate_surface(polished) == []
    # polish sheens in the tracks only; the rest of the slab keeps 0.90
    assert dry[P_ROUGH] == pytest.approx(DRY_ASPHALT_ROUGHNESS)


def test_unknown_preset_raises_value_error():
    with pytest.raises(ValueError):
        surface_parameters("polished_ice")
    with pytest.raises(ValueError):
        surface_parameters("painted_marking", wheel_polish=True)
