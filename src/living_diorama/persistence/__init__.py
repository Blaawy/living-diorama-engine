"""Conversion between in-memory World/EventLog/WorldMemory state and
versioned JSON save files.

Owns schema versioning, schema migrations, and state-hash lineage
verification between episodes. Contains no simulation logic.
"""
