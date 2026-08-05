"""Durable, cumulative world history distilled from events.

WorldMemory carries the complete significant-fact history forward across
episodes, so that every episode's save is self-contained and reloadable
without requiring earlier episode folders. See ``docs/architecture.md``
section 13 for the (not-yet-implemented) Post-MVP compaction decision.
"""
