"""``_set_and_verify`` must COMPARE the read-back, not merely perform it.

The driver reads every property back for one reason, stated in its own module
docstring: an Unreal property name that does not exist fails silently, so a
write the engine ignored has to be caught.  Setting a property, reading it back
and returning the value without comparing it to what was requested defeats the
whole mechanism -- a silently ignored property produced no entry in ``problems``.

``ldyf_lighting_editor`` imports ``unreal`` and cannot run here, so this test
stubs ``unreal`` out and loads the module by file path.  Nothing in the module
touches ``unreal`` at import time (only inside the functions), so the stub only
has to exist.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

if "unreal" not in sys.modules:
    sys.modules["unreal"] = types.ModuleType("unreal")

_MODULE_PATH = (Path(__file__).resolve().parents[1]
                / "unreal" / "ldyf_lighting_editor.py")
_spec = importlib.util.spec_from_file_location("ldyf_lighting_editor_under_test",
                                               _MODULE_PATH)
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)


class _Ignores:
    """set_editor_property that quietly does nothing (the silent no-op)."""

    def __init__(self, stored):
        self.stored = dict(stored)

    def set_editor_property(self, key, value):
        pass

    def get_editor_property(self, key):
        return self.stored[key]


class _Obeys:
    def __init__(self, stored):
        self.stored = dict(stored)

    def set_editor_property(self, key, value):
        self.stored[key] = value

    def get_editor_property(self, key):
        return self.stored[key]


class _Rejects:
    def set_editor_property(self, key, value):
        raise RuntimeError("no such editor property")

    def get_editor_property(self, key):
        return None


def test_silently_ignored_numeric_write_is_recorded_as_a_problem():
    problems = []
    got = L._set_and_verify(_Ignores({"fog_density": 7.0}), "fog_density", 12.5,
                            problems, label="fog")
    assert got == 7.0
    assert len(problems) == 1
    assert "fog_density" in problems[0]
    assert "12.5" in problems[0] and "7.0" in problems[0]


def test_a_write_the_engine_took_is_not_a_problem():
    problems = []
    assert L._set_and_verify(_Obeys({}), "intensity", 12.5, problems,
                             label="sun") == 12.5
    assert problems == []


def test_numeric_float_noise_is_within_tolerance():
    problems = []
    L._set_and_verify(_Ignores({"intensity": 12.5 + 1e-6}), "intensity", 12.5,
                      problems, label="sun")
    assert problems == []


def test_booleans_compare_by_equality():
    problems = []
    L._set_and_verify(_Ignores({"use_temperature": False}), "use_temperature",
                      True, problems, label="sun")
    assert len(problems) == 1
    assert "use_temperature" in problems[0]
    L._set_and_verify(_Obeys({}), "real_time_capture", True, problems,
                      label="sky")
    assert len(problems) == 1


def test_enums_compare_after_string_normalisation():
    problems = []
    # The spec writes AEM_Manual; the binding exposes AEM_MANUAL (see _enum).
    L._set_and_verify(_Ignores({"auto_exposure_method": "AEM_MANUAL"}),
                      "auto_exposure_method", "aem_manual", problems,
                      label="exposure")
    assert problems == []


def test_a_rejected_write_is_still_reported_and_returns_none():
    """The existing exception path is untouched."""
    problems = []
    assert L._set_and_verify(_Rejects(), "intensity", 1.0, problems,
                             label="ppv") is None
    assert len(problems) == 1 and "rejected" in problems[0]
