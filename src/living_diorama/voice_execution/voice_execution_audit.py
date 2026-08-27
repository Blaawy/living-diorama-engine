"""Audit an executed voice directory against its own manifest, unit by unit.

This is the independent half of Phase 29. The executor writes the speech and
the manifest; this function re-reads every byte on disk and decides whether
the manifest told the truth. It trusts nothing the executor recorded: each
unit's file is re-hashed and re-parsed, the recomputed sample count is
compared against the recorded one, every planned unit is required to be
present, and any file anywhere in the directory that nothing accounts for is
a refusal rather than a shrug.

The manifest is never measurement authority; the WAV is. That is what makes
this function worth calling: a verifier that re-hashed every file and then
believed the executor's own claim about how many samples it produced would
be checking the easy half.

It writes nothing, repairs nothing, synthesizes nothing, downloads nothing,
and imports no Kokoro or Torch stack.
"""

import hashlib
from pathlib import Path
from typing import cast

from living_diorama.persistence.json_codec import loads_canonical
from living_diorama.voice.voice_schema_v1 import JsonValue, validate_episode_voice_plan
from living_diorama.voice_execution.speech_audio import (
    SpeechAudioProblem,
    speech_sample_count,
    verify_speech_audio,
)
from living_diorama.voice_execution.voice_execution_binding import (
    require_manifest_matches_plan,
    require_voice_plan_bytes,
)
from living_diorama.voice_execution.voice_execution_schema_v1 import (
    validate_episode_voice_manifest,
)
from living_diorama.voice_execution.voice_execution_spec import (
    SPEECH_DIRECTORY,
    VOICE_DIRECTORY_ENTRIES,
    VOICE_MANIFEST_FILENAME,
    VOICE_PLAN_FILENAME,
    classify_voice_directory_entry,
)


def audit_voice_directory(voice_dir: Path) -> list[str]:
    """Return every problem found in one executed voice directory.

    An empty list means: the plan copy validates; the manifest validates and
    agrees with the plan beside it about everything it copied; every unit it
    names exists with exactly the bytes and digest it recorded; every one of
    those files parses as canonical speech of the plan's own pinned request;
    every unit's recomputed sample count agrees with the manifest and sits at
    or under its own capacity; no unaccounted file is present anywhere in the
    directory; and the manifest claims a complete execution.

    Args:
        voice_dir: The directory one execution owns.

    Returns:
        Human-readable problems, in the order they were found.
    """
    problems: list[str] = []
    plan_path = voice_dir / VOICE_PLAN_FILENAME
    manifest_path = voice_dir / VOICE_MANIFEST_FILENAME
    if not plan_path.is_file():
        return [f"{plan_path} is missing; the voice directory does not say what it executes"]
    if not manifest_path.is_file():
        return [f"{manifest_path} is missing; this execution never completed"]

    try:
        plan = validate_episode_voice_plan(loads_canonical(plan_path.read_bytes(), "voice plan"))
    except (TypeError, ValueError) as error:
        return [f"voice plan is invalid: {error}"]
    try:
        manifest = validate_episode_voice_manifest(
            loads_canonical(manifest_path.read_bytes(), "voice manifest")
        )
    except (TypeError, ValueError) as error:
        return [f"voice manifest is invalid: {error}"]

    # Binding the plan by digest proves the two documents were paired. It
    # does not prove the manifest was honest about what it copied out of
    # that plan -- the whole source block, and five fields of every
    # voice-unit record. Each of those could be edited while the plan digest
    # stayed untouched, and the document would still validate against its
    # own contract. So the comparison is done in full, on both axes.
    try:
        require_voice_plan_bytes(manifest, plan_path.read_bytes())
    except (TypeError, ValueError) as error:
        problems.append(f"the manifest does not bind the exact plan bytes beside it: {error}")
    try:
        require_manifest_matches_plan(manifest, plan)
    except (TypeError, ValueError) as error:
        problems.append(f"the manifest contradicts the voice plan beside it: {error}")

    voice_block = cast(dict[str, JsonValue], plan["voice"])
    expected_rate = cast(int, voice_block["sample_rate_hz"])
    expected_channels = cast(int, voice_block["channels"])

    recorded_units = cast(list[dict[str, JsonValue]], manifest["voice_units"])
    expected_paths: set[Path] = set()
    for position, entry in enumerate(recorded_units, start=1):
        path = voice_dir / cast(str, entry["file"])
        expected_paths.add(path)
        if not path.is_file():
            problems.append(f"unit {position} is missing from disk ({path})")
            continue

        payload = path.read_bytes()
        size = len(payload)
        digest = hashlib.sha256(payload).hexdigest()
        if size != entry["bytes"] or digest != entry["sha256"]:
            problems.append(
                f"unit {position} on disk is {size} bytes / {digest}, but the manifest "
                f"records {entry['bytes']} bytes / {entry['sha256']}"
            )
            continue

        structural = verify_speech_audio(
            path, expected_sample_rate_hz=expected_rate, expected_channels=expected_channels
        )
        if structural:
            problems.extend(f"unit {position}: {problem}" for problem in structural)
            continue

        try:
            recomputed = speech_sample_count(path)
        except SpeechAudioProblem as problem:
            problems.append(f"unit {position} could not be measured: {problem}")
            continue
        if recomputed != entry["speech_samples"]:
            problems.append(
                f"unit {position} measures {recomputed} samples on disk, but the manifest "
                f"records {entry['speech_samples']}"
            )
        capacity = cast(int, entry["capacity_samples"])
        if recomputed > capacity:
            problems.append(
                f"unit {position} measures {recomputed} samples, beyond its own "
                f"{capacity}-sample capacity, regardless of what the manifest claims"
            )

    speech_directory = voice_dir / SPEECH_DIRECTORY
    if not speech_directory.is_dir():
        problems.append(f"{speech_directory} is missing")
    else:
        for found in sorted(speech_directory.iterdir()):
            if found not in expected_paths:
                problems.append(f"{found} is present but no voice-unit record accounts for it")

    for found in sorted(voice_dir.iterdir()):
        kind = classify_voice_directory_entry(found.name, is_directory=found.is_dir())
        if kind == "partial":
            problems.append(
                f"{found} is this phase's own working file, left behind by a run that did not "
                "finish; a directory holding one is not a finished execution"
            )
        elif kind == "foreign":
            problems.append(
                f"{found} is present but a finished voice directory holds only "
                f"{sorted(VOICE_DIRECTORY_ENTRIES)}"
            )

    completeness = cast(dict[str, JsonValue], manifest["completeness"])
    if not completeness["complete"]:
        problems.append("the manifest does not claim a complete execution")

    return problems
