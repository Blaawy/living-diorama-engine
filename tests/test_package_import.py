"""Smoke test proving the installed package imports successfully.

This is the only test in Phase 0 -- there is no simulation logic yet to
test. Its purpose is to prove the src-layout package installs and imports
cleanly, which is the actual exit criterion for this phase.
"""

import living_diorama


def test_package_imports_and_exposes_a_version() -> None:
    """The top-level package must import without error and expose a version."""
    assert isinstance(living_diorama.__version__, str)
    assert living_diorama.__version__
