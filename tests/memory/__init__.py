"""Phase 11 world-memory tests.

This directory is a package so its shared builders import unambiguously as
``memory.conftest``. Without it the module would be imported under the bare name
``conftest``, which already belongs to other test directories, and whichever
loaded first would win.
"""
