"""Phase 10 persistence tests.

This directory is a package so its shared builders import unambiguously as
``persistence.conftest``. Without it the module would be imported under the
bare name ``conftest``, which already belongs to the entity tests' own
conftest, and whichever loaded first would win.
"""
