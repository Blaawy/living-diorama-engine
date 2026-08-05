"""Living Diorama Engine.

A deterministic, persistent-world simulation engine that generates one
controlled system experiment per episode for a YouTube series. Each
episode changes exactly one rule; the world evolves, consequences become
permanent, and the next episode resumes from the previously saved world
state. The world never resets.

This package contains only the simulation core: entities, systems, events,
memory, simulation orchestration, and persistence. Rendering (Godot),
cinematics (Blender), and narration (LLM-based) are separate, strictly
downstream, read-only consumers of this package's persisted output --
never dependencies of it, and never part of the simulation loop.

See docs/architecture.md for the full architecture document.
"""

__version__ = "0.0.1"
