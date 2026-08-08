"""Phase 15 visual-tooling tests (pure Python, no Blender required).

This directory is a package so its modules import unambiguously alongside the
other test packages. Everything here runs under ordinary pytest: these tests
exercise the plain-Python half of the Phase 15 gate (executable resolution,
directory ownership, runtime import boundaries) and never import ``bpy``.
"""
