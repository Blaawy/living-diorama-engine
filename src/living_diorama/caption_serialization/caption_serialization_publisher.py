"""Orchestrate one episode's caption serialization: gate, serialize, stage, publish.

This module owns the serialization-time orchestration only; every filesystem primitive it
uses is confined to :mod:`caption_serialization_staging`. It contains no direct ``open(``,
``os.replace``, ``os.fsync``, ``shutil.`` or ``.lstat(`` anywhere.
"""

from pathlib import Path
from typing import cast

from living_diorama.caption import validate_episode_caption_plan_against_sources
from living_diorama.caption_serialization.caption_serialization_audit import (
    _audit_caption_serialization_directory_with_observation,
    audit_caption_serialization_directory,
)
from living_diorama.caption_serialization.caption_serialization_manifest import (
    build_episode_caption_serialization_manifest_document,
)
from living_diorama.caption_serialization.caption_serialization_schema_v1 import JsonValue
from living_diorama.caption_serialization.caption_serialization_spec import (
    CAPTION_PLAN_COPY_FILENAME,
    CAPTION_SERIALIZATION_MANIFEST_FILENAME,
    PARTIAL_SUFFIX,
    SRT_SUFFIX,
    VTT_SUFFIX,
    CaptionSerializationRefused,
    caption_serialization_id,
    sidecar_filename,
)
from living_diorama.caption_serialization.caption_serialization_staging import (
    CaptionSerializationDirectoryRefused,
    _is_path_indirection,
    _require_direct_parent,
    discard_owned_staging,
    fsync_directory,
    publish_owned_staging,
    write_atomically,
)
from living_diorama.caption_serialization.srt_writer import serialize_srt_bytes
from living_diorama.caption_serialization.vtt_writer import serialize_vtt_bytes
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex


def publish_episode_caption_serialization(
    *,
    caption_plan: object,
    caption_plan_bytes: bytes,
    realization_plan: object,
    presentation_plan: object,
    delivery_plan: object,
    narration_plan: object,
    shot_plan: object,
    story_plan: object,
    current_export: object,
    output_root: Path,
) -> Path:
    """Serialize, stage, publish and return one episode's captions directory.

    The full, unweakened Phase 32 source-verification gate runs FIRST, against all seven
    verification documents, before a single span is derived -- a caption serialization can
    never exist without every one of its plan's bindings having been proven against the
    actual sources in this invocation. The supplied ``caption_plan_bytes`` must be the exact
    captured observation ``caption_plan`` was parsed from; they become the copied plan and
    the bound ``caption_plan_sha256``, so parse, gate, digest and copy all share one
    observation -- the single-capture law.

    The handled-refusal ``try`` begins at fresh staging creation and covers every handled
    failure from that point through terminal publication: once this run's own staging tree
    exists, a handled refusal (``OSError``, ``TypeError``, ``ValueError`` -- including
    ``CaptionSerializationRefused`` -- or ``CaptionSerializationDirectoryRefused``) discards
    that owned staging before propagating, so a refusal never litters the output root. An
    exception of any other class is never caught here: it propagates with the staging tree
    intact, as crash evidence for the next reviewed cleanup.

    Raises:
        CaptionSerializationRefused: If a sentence cannot be carried verbatim or a derived
            value violates a target-format rail.
        CaptionSerializationDirectoryRefused: If the output root is an indirection, a final
            directory of this name already exists and is not a truthful serialization of
            this exact plan, or staging ownership cannot be proven.
        TypeError: If a document carries a wrongly typed value.
        ValueError: If a document is invalid or the captured bytes are not canonical.
    """
    _require_direct_parent(output_root)

    plan = validate_episode_caption_plan_against_sources(
        caption_plan,
        realization_plan,
        presentation_plan,
        delivery_plan,
        narration_plan,
        shot_plan,
        story_plan,
        current_export,
    )
    if type(caption_plan_bytes) is not bytes:
        raise TypeError(
            f"caption_plan_bytes must be bytes, got {type(caption_plan_bytes).__name__}"
        )
    if caption_plan_bytes != dumps_canonical(plan, "caption plan"):
        raise ValueError(
            "caption_plan_bytes are not the canonical encoding of the gate-verified caption "
            "plan; the copied plan and the bound digest come from the one captured "
            "observation, never a second serialization of it"
        )
    caption_plan_sha256 = sha256_hex(caption_plan_bytes)

    srt_bytes = serialize_srt_bytes(plan)
    vtt_bytes = serialize_vtt_bytes(plan)
    manifest_document = build_episode_caption_serialization_manifest_document(
        caption_plan=plan,
        caption_plan_bytes=caption_plan_bytes,
        srt_bytes=srt_bytes,
        vtt_bytes=vtt_bytes,
    )
    manifest_bytes = dumps_canonical(manifest_document, "episode caption serialization manifest")

    plan_source = cast(dict[str, JsonValue], plan["source"])
    final_name = caption_serialization_id(
        mode=cast(str, plan_source["mode"]),
        episode=cast(int, plan_source["episode"]),
        previous_episode=cast("int | None", plan_source["previous_episode"]),
    )
    final_dir = output_root / final_name
    staging_name = f"{final_name}{PARTIAL_SUFFIX}"
    staging_dir = output_root / staging_name

    # ---- final_dir is never queried before its own indirection is refused ----
    if _is_path_indirection(final_dir):
        raise CaptionSerializationDirectoryRefused(
            f"{final_dir} is a symlink or junction; this phase never follows an indirection "
            "to decide whether a serialization already exists"
        )

    if final_dir.exists():
        problems, _existing_bytes, existing = (
            _audit_caption_serialization_directory_with_observation(final_dir)
        )
        if problems:
            raise CaptionSerializationDirectoryRefused(
                f"{final_dir} already exists and is not a truthful, complete caption "
                f"serialization: {problems}"
            )
        existing_source = cast(dict[str, JsonValue], cast(dict[str, JsonValue], existing)["source"])
        if existing_source["caption_plan_sha256"] != caption_plan_sha256:
            raise CaptionSerializationDirectoryRefused(
                f"{final_dir} already exists and serializes a different caption plan "
                f"({existing_source['caption_plan_sha256']!r} != {caption_plan_sha256!r}); "
                "nothing is deleted to make room"
            )
        return final_dir

    # ---- stale staging from a PRIOR run, cleaned before this run's own exists ----
    discard_owned_staging(
        staging_dir,
        expected_parent=output_root,
        expected_name=staging_name,
        episode_id=final_name,
    )

    try:
        staging_dir.mkdir(parents=True)

        write_atomically(staging_dir / CAPTION_PLAN_COPY_FILENAME, caption_plan_bytes)
        write_atomically(staging_dir / sidecar_filename(final_name, SRT_SUFFIX), srt_bytes)
        write_atomically(staging_dir / sidecar_filename(final_name, VTT_SUFFIX), vtt_bytes)
        write_atomically(staging_dir / CAPTION_SERIALIZATION_MANIFEST_FILENAME, manifest_bytes)

        # ---- TERMINAL PUBLICATION GATE: the full independent audit, on the staged tree --
        # The audit's directory-name law reads the FINAL id, so it runs against the staged
        # tree through the one seam the law allows: the staging name is the final name plus
        # ``.partial``, and the audit is handed the tree only after that suffix law held.
        problems = _staged_serialization_problems(staging_dir, expected_final_name=final_name)
        if problems:
            raise CaptionSerializationRefused(
                f"staged caption serialization failed its own independent audit: {problems}"
            )

        fsync_directory(staging_dir)
        publish_owned_staging(
            staging_dir,
            final_dir,
            expected_parent=output_root,
            expected_staging_name=staging_name,
            expected_final_name=final_name,
            episode_id=final_name,
        )
        return final_dir
    except (OSError, TypeError, ValueError, CaptionSerializationDirectoryRefused):
        # A handled refusal: this run's own freshly created staging is discarded so it
        # never litters the output root as if it were crash evidence. An unrecognized
        # exception class -- a genuine crash -- is never caught here, so its `.partial`
        # tree survives untouched for the next reviewed cleanup.
        discard_owned_staging(
            staging_dir,
            expected_parent=output_root,
            expected_name=staging_name,
            episode_id=final_name,
        )
        raise


def _staged_serialization_problems(staging_dir: Path, *, expected_final_name: str) -> list[str]:
    """Return the full audit's problems for a staged tree, netting the staging-name seam.

    The self-contained audit re-derives the directory name from the copied plan and would
    truthfully flag the ``.partial`` staging name; that one finding -- and only that one --
    is the seam the staging law itself creates, so it is filtered by its exact expected
    text. Every other problem the audit can raise survives untouched.
    """
    expected_seam = (
        f"the directory is named {staging_dir.name!r}, but the copied plan's own source "
        f"triple derives {expected_final_name!r}; a caption serialization is never trusted "
        "under a name its plan does not derive"
    )
    return [
        problem
        for problem in audit_caption_serialization_directory(staging_dir)
        if problem != expected_seam
    ]


__all__ = ["publish_episode_caption_serialization"]
