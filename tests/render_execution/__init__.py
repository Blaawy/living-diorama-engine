"""Phase 23 render execution tests.

This directory is a package so its shared builders import unambiguously as
``render_execution.conftest``. Without it the module would be imported under
the bare name ``conftest``, which already belongs to other test directories,
and whichever loaded first would win.
"""
