"""Self-contained audit of a published caption serialization against its own manifest.

This is the independent half of Phase 34. The publisher writes the plan copy, the two
sidecars and the manifest; this function re-reads every byte in the directory and decides
whether the manifest told the truth. It trusts nothing the publisher recorded: the plan
copy is re-hashed and re-validated under the locked Phase 32 schema; every restated source,
clock and accounting value is compared against the copy; the frame-authoritative accounting
is re-derived from the copy's own cue records; every derived span is re-derived under
``caption_timestamp_policy_v1``; and BOTH sidecars are re-serialized from the copy and
required to equal the published bytes exactly -- byte for byte, never merely by digest.

One law here has no Phase 33 precedent and is deliberately stronger: the directory's own
name must equal the id re-derived from the copied plan's source triple, so a renamed but
internally consistent directory is refused rather than trusted.

It is self-contained: it reads only the entries inside the directory it is handed, and
succeeds after every upstream source location has disappeared. Every governed entry is
refused as a problem if it is a symlink or Windows junction, before its content or metadata
is ever trusted. No expected condition (``OSError``, ``TypeError``, ``ValueError`` or
``CaptionSerializationDirectoryRefused``) escapes this function: it always returns, it
never raises for a governed filesystem or data problem. It writes nothing, repairs nothing,
and imports no synthesis, rendering or encoding engine.
"""

from pathlib import Path
from typing import cast

from living_diorama.caption.caption_schema_v1 import validate_episode_caption_plan
from living_diorama.caption_serialization.caption_serialization_schema_v1 import (
    JsonValue,
    validate_episode_caption_serialization_manifest,
)
from living_diorama.caption_serialization.caption_serialization_spec import (
    CAPTION_PLAN_COPY_FILENAME,
    CAPTION_SERIALIZATION_MANIFEST_FILENAME,
    SRT_SUFFIX,
    VTT_SUFFIX,
    WRITING_SUFFIX,
    caption_serialization_id,
    sidecar_filename,
)
from living_diorama.caption_serialization.caption_serialization_staging import (
    _is_path_indirection,
    _regular_file_link_count,
)
from living_diorama.caption_serialization.caption_timestamp import derive_cue_spans
from living_diorama.caption_serialization.srt_writer import serialize_srt_bytes
from living_diorama.caption_serialization.vtt_writer import serialize_vtt_bytes
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex


def _audit_caption_serialization_directory_with_observation(
    caption_dir: Path,
) -> tuple[list[str], bytes | None, dict[str, JsonValue] | None]:
    """Audit one captions directory, returning the ONE manifest observation used.

    The manifest at ``caption_dir / CAPTION_SERIALIZATION_MANIFEST_FILENAME`` is read
    exactly once, from that directory and nowhere else. The returned bytes and document are
    that same observation, so a caller deciding existing-final identity never performs a
    second read and never supplies an authority of its own.

    Returns:
        ``(problems, manifest_bytes, manifest_document)``. The second and third members are
        ``None`` exactly when the manifest could not be captured, parsed, checked for
        canonical form and validated -- in which case ``problems`` is non-empty. A missing
        manifest is always a problem.
    """
    try:
        return _audit_governed_directory(caption_dir)
    except OSError as error:
        return [f"{caption_dir} could not be fully read: {error}"], None, None


def audit_caption_serialization_directory(caption_dir: Path) -> list[str]:
    """Return every problem found in one published caption serialization directory.

    The public, self-contained audit. It captures its own manifest exactly once from the
    directory it is handed and accepts no external manifest authority: there is no
    parameter through which a caller may supply manifest bytes of its own.

    Args:
        caption_dir: The directory one caption serialization owns.

    Returns:
        Human-readable problems, in the order they were found. An empty list means the
        serialization is complete and truthful.
    """
    problems, _manifest_bytes, _manifest = _audit_caption_serialization_directory_with_observation(
        caption_dir
    )
    return problems


def _audit_governed_directory(
    caption_dir: Path,
) -> tuple[list[str], bytes | None, dict[str, JsonValue] | None]:
    """The real audit body, wrapped by the public entry point's ``OSError`` boundary."""
    if _is_path_indirection(caption_dir):
        return (
            [f"{caption_dir} is a symlink or junction; this phase never audits through one"],
            None,
            None,
        )
    if not caption_dir.is_dir():
        return ([f"{caption_dir} is not a directory"], None, None)

    manifest_path = caption_dir / CAPTION_SERIALIZATION_MANIFEST_FILENAME
    plan_path = caption_dir / CAPTION_PLAN_COPY_FILENAME

    for governed_path in (manifest_path, plan_path):
        if _is_path_indirection(governed_path):
            return (
                [
                    f"{governed_path} is a symlink or junction; this phase never trusts a "
                    "governed entry reached through an indirection"
                ],
                None,
                None,
            )

    # ---- THE ONE READ of the caption serialization manifest: the returned observation ----
    if not manifest_path.is_file():
        return ([f"{manifest_path} is missing; this serialization never completed"], None, None)
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest_value = loads_canonical(manifest_bytes, "episode caption serialization manifest")
        manifest = validate_episode_caption_serialization_manifest(manifest_value)
    except (TypeError, ValueError) as error:
        return ([f"episode caption serialization manifest is invalid: {error}"], None, None)
    if manifest_bytes != dumps_canonical(manifest, "episode caption serialization manifest"):
        return ([f"{manifest_path} is not canonical bytes"], manifest_bytes, manifest)

    problems: list[str] = []

    if not plan_path.is_file():
        return (
            [f"{plan_path} is missing; this serialization never completed"],
            manifest_bytes,
            manifest,
        )
    plan_bytes = plan_path.read_bytes()
    try:
        plan_value = loads_canonical(plan_bytes, "caption plan")
        plan = validate_episode_caption_plan(plan_value)
    except (TypeError, ValueError) as error:
        return (
            problems + [f"copied caption plan is invalid: {error}"],
            manifest_bytes,
            manifest,
        )
    if plan_bytes != dumps_canonical(plan, "caption plan"):
        problems.append(f"{plan_path} is not canonical bytes")

    manifest_source = cast(dict[str, JsonValue], manifest["source"])
    plan_source = cast(dict[str, JsonValue], plan["source"])

    # ---- the bound plan digest, re-hashed against the copy beside the manifest ----
    plan_digest = sha256_hex(plan_bytes)
    if manifest_source.get("caption_plan_sha256") != plan_digest:
        problems.append(
            f"the manifest binds caption_plan_sha256 "
            f"{manifest_source.get('caption_plan_sha256')!r}, but the copied plan hashes to "
            f"{plan_digest!r}"
        )
    if manifest_source.get("caption_schema_version") != plan["schema_version"]:
        problems.append(
            f"the manifest restates caption_schema_version "
            f"{manifest_source.get('caption_schema_version')!r}, but the copied plan declares "
            f"{plan['schema_version']!r}"
        )

    # ---- every restated source value, compared against the copied plan's own source ----
    for field in (
        "episode",
        "mode",
        "presentation_plan_sha256",
        "presentation_schema_version",
        "previous_episode",
        "realization_plan_sha256",
        "realization_schema_version",
    ):
        if manifest_source.get(field) != plan_source.get(field):
            problems.append(
                f"the manifest's source.{field} is {manifest_source.get(field)!r}, but the "
                f"copied plan's own source.{field} is {plan_source.get(field)!r}"
            )

    # ---- A NEW LAW BEYOND PHASE 33: the directory's name is re-derived, never trusted ----
    try:
        expected_id = caption_serialization_id(
            mode=cast(str, plan_source["mode"]),
            episode=cast(int, plan_source["episode"]),
            previous_episode=cast("int | None", plan_source["previous_episode"]),
        )
    except (TypeError, ValueError) as error:
        problems.append(f"the copied plan's source triple derives no episode id: {error}")
        expected_id = None
    if expected_id is not None and caption_dir.name != expected_id:
        problems.append(
            f"the directory is named {caption_dir.name!r}, but the copied plan's own source "
            f"triple derives {expected_id!r}; a caption serialization is never trusted under "
            "a name its plan does not derive"
        )

    # ---- the restated clock and the re-derived frame-authoritative accounting ----
    manifest_clock = cast(dict[str, JsonValue], manifest["clock"])
    plan_clock = cast(dict[str, JsonValue], plan["clock"])
    for key in ("fps", "presentation_frames_total"):
        if manifest_clock.get(key) != plan_clock.get(key):
            problems.append(
                f"the manifest's clock.{key} is {manifest_clock.get(key)!r}, but the copied "
                f"plan's own clock.{key} is {plan_clock.get(key)!r}"
            )

    captions = cast(list[dict[str, JsonValue]], plan["captions"])
    derived_caption_frames = 0
    for cue in captions:
        start_frame = cast(int, cue["presentation_start_frame"])
        end_frame = cast(int, cue["presentation_end_frame"])
        derived_caption_frames += end_frame - start_frame + 1
    derived_total = cast(int, plan_clock["presentation_frames_total"])
    derived_accounting: dict[str, JsonValue] = {
        "caption_frames_total": derived_caption_frames,
        "captions_total": len(captions),
        "uncaptioned_frames_total": derived_total - derived_caption_frames,
    }
    manifest_accounting = cast(dict[str, JsonValue], manifest["accounting"])
    plan_accounting = cast(dict[str, JsonValue], plan["accounting"])
    for key, expected in derived_accounting.items():
        if manifest_accounting.get(key) != expected:
            problems.append(
                f"the manifest's accounting.{key} is {manifest_accounting.get(key)!r}, but "
                f"the copied plan's cue records re-derive {expected!r}"
            )
        if plan_accounting.get(key) != expected:
            problems.append(
                f"the copied plan's accounting.{key} is {plan_accounting.get(key)!r}, but its "
                f"own cue records re-derive {expected!r}"
            )

    # ---- the timestamp law, re-derived whole; then BOTH sidecars, re-serialized whole ----
    try:
        derive_cue_spans(plan)
    except (TypeError, ValueError) as error:
        problems.append(f"the copied plan's spans do not re-derive: {error}")

    sidecars = cast(dict[str, JsonValue], manifest["sidecars"])
    for record_key, suffix, serialize in (
        ("srt", SRT_SUFFIX, serialize_srt_bytes),
        ("vtt", VTT_SUFFIX, serialize_vtt_bytes),
    ):
        record = cast(dict[str, JsonValue], sidecars[record_key])
        expected_name = (
            sidecar_filename(expected_id, suffix)
            if expected_id is not None
            else cast(str, record["file"])
        )
        sidecar_path = caption_dir / cast(str, record["file"])
        if cast(str, record["file"]) != expected_name:
            problems.append(
                f"the manifest's sidecars.{record_key}.file is {record['file']!r}, but the "
                f"copied plan's own identity derives {expected_name!r}"
            )
        if _is_path_indirection(sidecar_path):
            problems.append(f"{sidecar_path} is a symlink or junction")
            continue
        if not sidecar_path.is_file():
            problems.append(f"{sidecar_path} is missing; this serialization never completed")
            continue
        published_bytes = sidecar_path.read_bytes()
        try:
            expected_bytes = serialize(plan)
        except (TypeError, ValueError) as error:
            problems.append(f"the copied plan does not re-serialize to {record_key}: {error}")
            continue
        if published_bytes != expected_bytes:
            problems.append(
                f"{sidecar_path} does not equal the {record_key} artifact re-serialized from "
                "the copied plan; a sidecar is re-derived byte for byte, never trusted"
            )
        if record.get("bytes") != len(published_bytes):
            problems.append(
                f"the manifest's sidecars.{record_key}.bytes is {record.get('bytes')!r}, but "
                f"the published file is {len(published_bytes)} bytes"
            )
        observed_digest = sha256_hex(published_bytes)
        if record.get("sha256") != observed_digest:
            problems.append(
                f"the manifest's sidecars.{record_key}.sha256 is {record.get('sha256')!r}, "
                f"but the published file hashes to {observed_digest!r}"
            )

    # ---- SINGLE-LINK SWEEP: all four owned regular files ----
    srt_name = cast(str, cast(dict[str, JsonValue], sidecars["srt"])["file"])
    vtt_name = cast(str, cast(dict[str, JsonValue], sidecars["vtt"])["file"])
    for description, path in (
        ("episode caption serialization manifest", manifest_path),
        ("caption plan copy", plan_path),
        ("srt sidecar", caption_dir / srt_name),
        ("vtt sidecar", caption_dir / vtt_name),
    ):
        if not path.is_file():
            continue
        links = _regular_file_link_count(path)
        if links != 1:
            problems.append(
                f"{description} at {path} has {links} directory entries pointing at it; a "
                "Phase 34 owned regular file must be an independent physical copy with "
                "exactly one, never a hardlink"
            )

    # ---- inventory sweep: no foreign or leftover entry anywhere this phase owns ----
    owned_names = {manifest_path.name, plan_path.name, srt_name, vtt_name}
    for found in sorted(caption_dir.iterdir()):
        if _is_path_indirection(found):
            problems.append(f"{found} is a symlink or junction; no directory entry may be one")
            continue
        if found.is_dir():
            problems.append(
                f"{found} is a directory inside a caption serialization, never permitted"
            )
            continue
        if found.name in owned_names:
            continue
        if found.name.endswith(WRITING_SUFFIX) and found.name[: -len(WRITING_SUFFIX)] in (
            owned_names
        ):
            problems.append(
                f"{found} is this phase's own working file, left behind by a run that did "
                "not finish; a directory holding one is not a finished serialization"
            )
        else:
            problems.append(f"{found} is present but not accounted for by this phase's contract")

    return problems, manifest_bytes, manifest


__all__ = ["audit_caption_serialization_directory"]
