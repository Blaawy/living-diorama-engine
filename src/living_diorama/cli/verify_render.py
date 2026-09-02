r"""Audit a rendered episode against its own manifest, frame by frame.

    python -m living_diorama.cli.verify_render --render-dir renders/episode_0000_to_0001

This is the independent half of Phase 23. The executor writes the frames and
the manifest; this command re-reads every byte on disk and decides whether the
manifest told the truth. It trusts nothing the renderer recorded: each file is
re-hashed and decoded, each planned frame is required to be present, any file
anywhere in the render directory that nothing accounts for is a refusal rather
than a shrug,
and the boundary measurement is **recomputed from the two images** rather than
read out of the document that is being checked.

That last point is what makes the audit worth running. A verifier that
re-hashed every frame and then believed the renderer's own number about how
those frames compare would be checking the easy half.

It renders nothing, imports no Blender, and repairs nothing.
"""

import argparse
import hashlib
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from living_diorama.persistence.json_codec import loads_canonical
from living_diorama.render_execution import (
    validate_episode_render_manifest,
    validate_episode_render_plan,
)
from living_diorama.render_execution.frame_image import (
    FrameImageProblem,
    image_stream_digest,
    mean_abs_difference,
    verify_frame_image,
)
from living_diorama.render_execution.render_binding import (
    require_checkpoint_matches_manifest,
    require_manifest_matches_plan,
    validate_render_checkpoint,
)
from living_diorama.render_execution.render_execution_spec import (
    FRAMES_DIRECTORY,
    RENDER_CHECKPOINT_FILENAME,
    RENDER_DIRECTORY_ENTRIES,
    RENDER_MANIFEST_FILENAME,
    RENDER_PLAN_FILENAME,
    ROLE_WITNESS,
    WITNESS_DIFFERENCE_TOLERANCE,
    WITNESS_DIRECTORY,
    classify_render_directory_entry,
    render_profile_dimensions,
)


def _by_frame(document: Mapping[str, object]) -> dict[int, dict[str, object]]:
    """Index one document's frame records by their semantic frame number."""
    entries = cast(list[dict[str, object]], document["frames"])
    return {cast(int, entry["frame"]): entry for entry in entries}


def _audit_frame_file(path: Path, entry: Mapping[str, object], frame: int) -> list[str]:
    """Return every way one frame file fails to be what the manifest says it is.

    Three separate questions, and all three are asked of every one of the 193
    files rather than of the two the boundary measurement happens to open.

    *Are these the recorded bytes?* The file's length and SHA-256 must be what
    the manifest recorded. *Is this the recorded picture?* The image digest
    covers the decompressed image stream, so it separates a frame whose picture
    changed from one Blender merely re-stamped with a new render date. *Is this
    a frame at all?* The image is fully decoded and checked against the render
    profile.

    That third question is the one V2 asked of two files out of 193, and it is
    the one digests cannot answer. Re-hashing proves a file is the one recorded;
    it cannot notice that the recorded file is a 640x360 greyscale picture. An
    attacker who replaces an interior frame and rewrites all three digests to
    match produces a directory in which every hash agrees -- and only decoding
    the image says otherwise.

    Problems are returned rather than raised, so one bad frame becomes a finding
    instead of an exception that stops the other 192 from being looked at.
    """
    problems: list[str] = []
    payload = path.read_bytes()
    size = len(payload)
    digest = hashlib.sha256(payload).hexdigest()
    if size != entry["bytes"] or digest != entry["sha256"]:
        problems.append(
            f"frame {frame} on disk is {size} bytes / {digest}, but the manifest records "
            f"{entry['bytes']} bytes / {entry['sha256']}"
        )
    else:
        try:
            image_digest = image_stream_digest(path)
        except FrameImageProblem as problem:
            problems.append(f"frame {frame} could not be read as an image: {problem}")
        else:
            if image_digest != entry["image_sha256"]:
                problems.append(
                    f"frame {frame} carries image data {image_digest}, but the manifest records "
                    f"{entry['image_sha256']}"
                )
    width, height = render_profile_dimensions()
    problems.extend(
        f"frame {frame}: {problem}"
        for problem in verify_frame_image(path, expected_width=width, expected_height=height)
    )
    return problems


def audit_render_directory(render_dir: Path) -> list[str]:
    """Return every problem found in one rendered episode directory.

    An empty list means: the manifest is a valid manifest; it agrees with the
    plan beside it about every field it copied from it; every frame it names
    exists with exactly the bytes it recorded; every one of those files decodes
    as an image of this render's profile; no unaccounted file is present; and
    the boundary verdict matches a difference this command measured for itself
    from the two images.

    Args:
        render_dir: The directory one render owns.

    Returns:
        Human-readable problems, in the order they were found.
    """
    problems: list[str] = []
    plan_path = render_dir / RENDER_PLAN_FILENAME
    manifest_path = render_dir / RENDER_MANIFEST_FILENAME
    if not plan_path.is_file():
        return [f"{plan_path} is missing; the render directory does not say what it renders"]
    if not manifest_path.is_file():
        return [f"{manifest_path} is missing; this render never completed"]

    raw_plan = loads_canonical(plan_path.read_bytes(), "render plan")
    plan_source = raw_plan.get("source") if isinstance(raw_plan, dict) else None
    plan_camera_profile = (
        "v2"
        if isinstance(plan_source, dict) and "movement_catalogue_sha256" in plan_source
        else "v1"
    )
    try:
        plan = validate_episode_render_plan(raw_plan, camera_profile=plan_camera_profile)
    except (TypeError, ValueError) as error:
        return [f"render plan is invalid: {error}"]
    raw_manifest = loads_canonical(manifest_path.read_bytes(), "render manifest")
    manifest_source = raw_manifest.get("source") if isinstance(raw_manifest, dict) else None
    manifest_camera_profile = (
        "v2"
        if isinstance(manifest_source, dict) and "movement_catalogue_sha256" in manifest_source
        else "v1"
    )
    try:
        manifest = validate_episode_render_manifest(
            raw_manifest, camera_profile=manifest_camera_profile
        )
    except (TypeError, ValueError) as error:
        return [f"render manifest is invalid: {error}"]

    # The relationship checks re-validate both documents under one profile.
    # V2 is strictly additive -- a V1 document is a valid V2 document -- so
    # "v2 if EITHER document is v2" never turns a valid pair invalid. A pair
    # that disagrees about whether the movement catalogue is present is caught
    # by the source-block comparison inside the check below, the same
    # comparison that catches every other copied-field disagreement, rather
    # than silently picked one way.
    pair_camera_profile = (
        "v2" if plan_camera_profile == "v2" or manifest_camera_profile == "v2" else "v1"
    )

    # Binding the plan by digest proves the two documents were paired. It does
    # not prove the manifest was honest about what it copied out of that plan --
    # the whole source block, the emission contract, the world it was composed
    # from, and six fields of every frame record. Each of those could be edited
    # while the plan digest stayed untouched, and the document would still
    # validate against its own contract. So the comparison is done in full.
    try:
        require_manifest_matches_plan(manifest, plan, camera_profile=pair_camera_profile)
    except (TypeError, ValueError) as error:
        problems.append(f"the manifest contradicts the render plan beside it: {error}")

    # The checkpoint, if one is here. It is not a canonical artifact -- it
    # records progress, not truth -- but a directory whose records disagree
    # about a file has no truthful reading, and an independent audit that never
    # opened it could not say so.
    #
    # Two separate checks, deliberately. Proving the checkpoint agrees with the
    # manifest beside it says nothing about whether either of them is honest
    # about the plan they both claim to be for -- a checkpoint whose own
    # `render_plan_sha256` names a different render, with every frame record
    # otherwise truthful, would pass a relationship check that never opens the
    # plan. So the checkpoint is validated standalone against the actual Render
    # Plan first, and only then checked against the manifest.
    checkpoint_path = render_dir / RENDER_CHECKPOINT_FILENAME
    if checkpoint_path.is_file():
        try:
            checkpoint_document = loads_canonical(checkpoint_path.read_bytes(), "render checkpoint")
        except (TypeError, ValueError) as error:
            problems.append(f"render checkpoint is invalid: {error}")
        else:
            try:
                validate_render_checkpoint(
                    checkpoint_document, plan, camera_profile=plan_camera_profile
                )
            except (TypeError, ValueError) as error:
                problems.append(
                    f"the render checkpoint does not match its own render plan: {error}"
                )
            try:
                require_checkpoint_matches_manifest(
                    checkpoint_document, manifest, camera_profile=manifest_camera_profile
                )
            except (TypeError, ValueError) as error:
                problems.append(
                    f"the render checkpoint contradicts the manifest beside it: {error}"
                )

    planned = _by_frame(plan)
    recorded = _by_frame(manifest)
    if set(planned) != set(recorded):
        problems.append(
            f"the manifest records frames {sorted(recorded)} but the plan accounts for "
            f"{sorted(planned)}"
        )

    expected_paths: set[Path] = set()
    for frame, entry in sorted(recorded.items()):
        folder = WITNESS_DIRECTORY if entry["role"] == ROLE_WITNESS else FRAMES_DIRECTORY
        path = render_dir / folder / cast(str, entry["file"])
        expected_paths.add(path)
        if not path.is_file():
            problems.append(f"frame {frame} is missing from disk ({path})")
            continue
        problems.extend(_audit_frame_file(path, entry, frame))

    for folder in (FRAMES_DIRECTORY, WITNESS_DIRECTORY):
        directory = render_dir / folder
        if not directory.is_dir():
            problems.append(f"{directory} is missing")
            continue
        for found in sorted(directory.iterdir()):
            if found not in expected_paths:
                problems.append(f"{found} is present but no frame record accounts for it")

    # The top level too, which this command claimed to check and did not. A
    # surviving `.partial` is the interesting case: the executor removes it as
    # each frame is published, so one here means a render died mid-frame and
    # this directory is not the finished thing it presents itself as.
    for found in sorted(render_dir.iterdir()):
        kind = classify_render_directory_entry(found.name, is_directory=found.is_dir())
        if kind == "partial":
            problems.append(
                f"{found} is this phase's own working file, left behind by a run that did not "
                "finish; a directory holding one is not a finished render"
            )
        elif kind == "foreign":
            problems.append(
                f"{found} is present but a finished render directory holds only "
                f"{sorted(RENDER_DIRECTORY_ENTRIES)}"
            )

    completeness = cast(dict[str, object], manifest["completeness"])
    if not completeness["complete"]:
        problems.append("the manifest does not claim a complete render")

    # The boundary measurement is recomputed here from the two images. Reading
    # it out of the manifest would be asking the renderer to mark its own work.
    playback = [entry for entry in recorded.values() if entry["role"] != ROLE_WITNESS]
    witnesses = [entry for entry in recorded.values() if entry["role"] == ROLE_WITNESS]
    if len(witnesses) != 1 or not playback:
        problems.append("the manifest does not record exactly one witness and a playback set")
        return problems
    final_entry = max(playback, key=lambda entry: cast(int, entry["frame"]))
    final_path = render_dir / FRAMES_DIRECTORY / cast(str, final_entry["file"])
    witness_path = render_dir / WITNESS_DIRECTORY / cast(str, witnesses[0]["file"])
    if not final_path.is_file() or not witness_path.is_file():
        problems.append("the boundary measurement cannot be recomputed; a frame is missing")
        return problems

    try:
        measured = mean_abs_difference(final_path, witness_path)
    except (FrameImageProblem, ValueError) as error:
        problems.append(f"the boundary frames could not be compared: {error}")
        return problems
    recorded_difference = completeness["witness_mean_abs_difference"]
    if measured != recorded_difference:
        problems.append(
            f"the manifest records a boundary difference of {recorded_difference}, but the "
            f"frames on disk measure {measured}"
        )
    if completeness["witness_within_tolerance"] != (measured <= WITNESS_DIFFERENCE_TOLERANCE):
        problems.append(
            f"the manifest's boundary verdict does not follow from the measured difference "
            f"{measured} against the {WITNESS_DIFFERENCE_TOLERANCE} tolerance"
        )
    if measured > WITNESS_DIFFERENCE_TOLERANCE:
        problems.append(
            f"the boundary witness differs from the final playback frame by {measured} levels, "
            "beyond the tolerance the emission contract allows; this episode may have been cut "
            "off mid-action"
        )
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """Audit one render directory and report the outcome.

    Returns:
        0 when the render is complete and truthful, 1 otherwise.
    """
    parser = argparse.ArgumentParser(
        prog="python -m living_diorama.cli.verify_render",
        description="Audit a rendered episode against its own manifest.",
    )
    parser.add_argument("--render-dir", required=True, help="the directory one render owns")
    arguments = parser.parse_args(None if argv is None else list(argv))

    render_dir = Path(arguments.render_dir)
    if not render_dir.is_dir():
        print(f"render audit refused: {render_dir} is not a directory", file=sys.stderr)
        return 1
    problems = audit_render_directory(render_dir)
    if problems:
        for problem in problems:
            print(f"  PROBLEM {problem}", file=sys.stderr)
        print(f"render audit failed: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(f"render audit passed: {render_dir}")
    return 0


if __name__ == "__main__":  # pragma: no cover - module execution entry
    raise SystemExit(main())
