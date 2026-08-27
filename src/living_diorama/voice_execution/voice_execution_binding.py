"""Prove an executed voice manifest and its plan copy are the same execution.

Two documents describe one voice execution, and each validates on its own.
That is not enough. A manifest that is internally coherent has proved only
that nobody typed a contradiction into it; it has not proved that the fields
it copied out of the bound Phase 28 voice plan are the values that plan
actually holds.

Those are relationship claims, and this module is where they are checked.

* :func:`require_voice_plan_bytes` -- the plan the caller holds is the exact
  file the manifest was executed from, by raw bytes.
* :func:`require_manifest_matches_plan` -- the manifest contradicts its plan
  nowhere, while still being free to record what only a finished execution
  knows.

**Why a separate module.** Standalone validation and relationship validation
answer different questions and must not be able to stand in for one another.
A manifest read off disk with no plan beside it can still be checked
completely against its own contract, and callers that only have the one
document keep that. What they no longer get is the *impression* of
provenance: binding a digest proves two documents were paired, never that the
pairing was honest about what it copied.
"""

from typing import Final, cast

from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.voice.voice_schema_v1 import validate_episode_voice_plan
from living_diorama.voice_execution.voice_execution_schema_v1 import (
    JsonValue,
    validate_episode_voice_manifest,
)

MANIFEST_EXCLUSIVE_SOURCE_KEYS: Final = frozenset({"voice_plan_sha256"})
"""Source keys only a finished execution's manifest may carry.

Everything else in the manifest's source block must equal the plan's own
source block, key for key.
"""

MANIFEST_EXCLUSIVE_UNIT_KEYS: Final = frozenset({"file", "bytes", "sha256", "speech_samples"})
"""Per-unit keys only a finished execution's manifest may carry.

Everything else in a voice-unit record -- the plan's own five fields -- must
equal the plan it was executed from, key for key, position for position.
"""


def require_manifest_matches_plan(manifest: object, voice_plan: object) -> dict[str, JsonValue]:
    """Refuse unless the manifest tells the truth about the plan it executes.

    A manifest binds its plan by digest, and standalone validation checks
    that binding is well-formed. But the manifest also *copies* most of the
    plan into itself -- the whole source block, and five fields of every
    voice-unit record -- and a copy that was never compared to its original
    is an unchecked assertion. A manifest could keep ``voice_plan_sha256``
    untouched, name a different episode, a different capacity on a unit, and
    validate perfectly against its own contract.

    So every copied field is compared. The manifest keeps exactly the
    freedom it needs: it may say what a finished execution measured -- a
    file, a byte count, a digest, a sample count -- because the plan could
    not have known those. It may not disagree about anything the plan
    already said.

    Args:
        manifest: The parsed Episode Voice Manifest.
        voice_plan: The parsed Episode Voice Plan it claims to execute.

    Returns:
        The validated manifest.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: On any contradiction between the two documents.
    """
    record = validate_episode_voice_manifest(manifest)
    plan = validate_episode_voice_plan(voice_plan)

    plan_digest = sha256_hex(dumps_canonical(plan, "episode voice plan"))
    manifest_source = dict(cast(dict[str, JsonValue], record["source"]))
    exclusive = {key: manifest_source.pop(key) for key in MANIFEST_EXCLUSIVE_SOURCE_KEYS}
    bound = exclusive["voice_plan_sha256"]
    if bound != plan_digest:
        raise ValueError(
            f"the manifest binds voice plan {bound!r}, but the plan supplied beside it is "
            f"{plan_digest!r}"
        )

    plan_source = dict(cast(dict[str, JsonValue], plan["source"]))
    if manifest_source != plan_source:
        differing = sorted(
            key
            for key in set(manifest_source) | set(plan_source)
            if manifest_source.get(key) != plan_source.get(key)
        )
        raise ValueError(
            f"the manifest's source disagrees with its own voice plan on {differing}; a "
            "manifest records what an execution produced and restates the identity it was "
            "produced under, never a different one"
        )

    planned = cast(list[JsonValue], plan["voice_units"])
    executed = cast(list[JsonValue], record["voice_units"])
    if len(executed) != len(planned):
        raise ValueError(
            f"the manifest records {len(executed)} voice units but its plan accounts for "
            f"{len(planned)}"
        )
    for position, (actual_raw, expected_raw) in enumerate(zip(executed, planned, strict=True)):
        actual = cast(dict[str, JsonValue], actual_raw)
        expected = cast(dict[str, JsonValue], expected_raw)
        for key in sorted(set(expected) - MANIFEST_EXCLUSIVE_UNIT_KEYS):
            if actual[key] != expected[key]:
                raise ValueError(
                    f"manifest voice_units[{position}] records {key} {actual[key]!r}, but the "
                    f"plan it was executed from says {expected[key]!r}"
                )
    return record


def require_voice_plan_bytes(manifest: object, voice_plan_bytes: bytes) -> dict[str, JsonValue]:
    """Refuse unless these exact bytes are the voice plan the manifest was executed from.

    The digest is taken over the bytes as they are, not over a
    re-serialization of what they parse to. Those are different claims:
    canonicalising first would accept a pretty-printed copy, a copy with
    reordered keys, a copy with trailing whitespace -- the same data written
    differently, and therefore a file whose own digest is not the one the
    manifest bound.

    The bytes are then parsed and validated under Phase 28's own contract
    before anything is derived from them, and the full relationship check
    runs on the result -- so this one call is sufficient to accept a plan
    copy for audit.

    Args:
        manifest: The parsed Episode Voice Manifest.
        voice_plan_bytes: The voice plan file's exact bytes.

    Returns:
        The validated manifest.

    Raises:
        TypeError: If the bytes are not bytes, or a value is of the wrong
            exact type.
        ValueError: If the bytes are not the bound voice plan, are not a
            valid Phase 28 document, or disagree with the manifest.
    """
    if type(voice_plan_bytes) is not bytes:
        raise TypeError(f"voice plan bytes must be bytes, got {type(voice_plan_bytes).__name__}")
    record = validate_episode_voice_manifest(manifest)
    bound = cast(dict[str, JsonValue], record["source"])["voice_plan_sha256"]
    observed = sha256_hex(voice_plan_bytes)
    if observed != bound:
        raise ValueError(
            f"the supplied voice plan file hashes to {observed!r}, but the manifest was "
            f"executed from {bound!r}; the binding is over the file's exact bytes, so a "
            "re-formatted or re-ordered copy of the same data is a different source"
        )
    # Parsed only after the bytes are proved to be the bound file, so a
    # hostile document never reaches Phase 28's parser on this path at all.
    plan = loads_canonical(voice_plan_bytes, "episode voice plan")
    return require_manifest_matches_plan(record, plan)
