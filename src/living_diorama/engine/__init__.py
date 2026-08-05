"""Engine-level orchestration primitives.

Owns configuration and the deterministic tick clock. This package knows
nothing about *what* a world contains (see ``living_diorama.entities``) or
*how* it changes (see ``living_diorama.systems``) -- only the mechanics of
advancing time forward in a reproducible way.
"""
