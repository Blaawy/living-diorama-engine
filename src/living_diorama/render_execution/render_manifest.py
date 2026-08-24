"""Turn recorded render results into an Episode Render Manifest.

This module is pure and knows nothing about Blender, files, or rendering. It
is handed what a render observed -- a digest and a byte count per frame, plus
the environment that produced them -- and turns that into the document that
proves what exists. Keeping it here means the manifest's rules can be attacked
in ordinary tests, and means the executor cannot quietly invent a completeness
claim while holding a partial result.

The manifest never asserts the boundary verdict. It records the measured
mean absolute difference between the witness frame and the final playback
frame and derives the within-tolerance verdict from that number, so a document
can never claim the episode ended cleanly while the measurement beside it says
otherwise. complete means all of it: every playback frame present, one
witness, and that witness inside tolerance.
"""

from typing import cast

from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.render_execution.render_execution_schema_v1 import (
    JsonValue,
    validate_episode_render_manifest,
    validate_episode_render_plan,
)
from living_diorama.render_execution.render_execution_spec import (
    RENDER_MANIFEST_FORMAT,
    RENDER_MANIFEST_SCHEMA_VERSION,
    ROLE_PLAYBACK,
    ROLE_WITNESS,
    WITNESS_DIFFERENCE_TOLERANCE,
)


def build_episode_render_manifest_document(
    *,
    render_plan: object,
    results: dict[int, dict[str, object]],
    environment: dict[str, str],
    witness_difference: float,
) -> dict[str, JsonValue]:
    """Return the manifest for a completed render.

    Args:
        render_plan: The parsed render plan the render was executed from. It is
            re-validated here and its canonical digest is bound into the
            manifest, so a manifest can never float free of its plan.
        results: What the render observed, keyed by semantic frame number. Each
            entry carries ``bytes`` and ``sha256`` for the file that landed.
        environment: The Blender version, engine and device that produced the
            frames -- the facts a reader needs to know what these pixels are.
        witness_difference: The measured mean absolute difference between the
            witness frame and the final playback frame, in levels. Measured
            by whoever held both images; the verdict about it is computed
            here rather than supplied.

    Returns:
        The complete, validated manifest document.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If a planned frame has no result, a result names a frame
            the plan does not, or the plan itself is invalid.
    """
    plan = validate_episode_render_plan(render_plan)
    plan_digest = sha256_hex(dumps_canonical(plan, "episode render plan"))
    planned = [cast(dict[str, JsonValue], entry) for entry in cast(list[JsonValue], plan["frames"])]

    if type(results) is not dict:
        raise TypeError(f"render results must be a dict, got {type(results).__name__}")
    if type(environment) is not dict:
        raise TypeError(f"render environment must be a dict, got {type(environment).__name__}")

    planned_frames = {cast(int, entry["frame"]) for entry in planned}
    extra = sorted(set(results) - planned_frames)
    if extra:
        raise ValueError(
            f"render results name frames {extra} that this plan never asked for; a manifest "
            "describes the render it planned and nothing found lying beside it"
        )

    frames: list[JsonValue] = []
    for entry in planned:
        frame = cast(int, entry["frame"])
        result = results.get(frame)
        if result is None:
            raise ValueError(
                f"frame {frame} was planned but has no render result; a manifest is written "
                "only for a render that finished, never to record how far one got"
            )
        size = result.get("bytes")
        digest = result.get("sha256")
        image_digest = result.get("image_sha256")
        if isinstance(size, bool) or not isinstance(size, int):
            raise TypeError(f"frame {frame} result bytes must be an int, got {size!r}")
        if type(digest) is not str:
            raise TypeError(f"frame {frame} result sha256 must be a str, got {digest!r}")
        if type(image_digest) is not str:
            raise TypeError(
                f"frame {frame} result image_sha256 must be a str, got {image_digest!r}"
            )
        frames.append({**entry, "bytes": size, "sha256": digest, "image_sha256": image_digest})

    playback = [
        record for record in frames if cast(dict[str, JsonValue], record)["role"] == ROLE_PLAYBACK
    ]
    witness = [
        record for record in frames if cast(dict[str, JsonValue], record)["role"] == ROLE_WITNESS
    ]
    emission = cast(dict[str, JsonValue], plan["emission"])
    if type(witness_difference) is not float:
        raise TypeError(f"witness_difference must be a float, got {witness_difference!r}")

    source = dict(cast(dict[str, JsonValue], plan["source"]))
    source["render_plan_sha256"] = plan_digest

    document: dict[str, JsonValue] = {
        "format": RENDER_MANIFEST_FORMAT,
        "schema_version": RENDER_MANIFEST_SCHEMA_VERSION,
        "source": source,
        "composition_sources": dict(cast(dict[str, JsonValue], plan["composition_sources"])),
        "emission": dict(emission),
        "environment": {key: str(value) for key, value in sorted(environment.items())},
        "frames": frames,
        "completeness": {
            "playback_frames_expected": emission["frame_count"],
            "playback_frames_rendered": len(playback),
            "witness_frames_rendered": len(witness),
            "witness_mean_abs_difference": witness_difference,
            "witness_within_tolerance": witness_difference <= WITNESS_DIFFERENCE_TOLERANCE,
            "complete": (
                len(playback) == emission["frame_count"]
                and len(witness) == 1
                and witness_difference <= WITNESS_DIFFERENCE_TOLERANCE
            ),
        },
    }
    return validate_episode_render_manifest(document)


def build_episode_render_manifest_bytes(
    *,
    render_plan: object,
    results: dict[int, dict[str, object]],
    environment: dict[str, str],
    witness_difference: float,
) -> bytes:
    """Return the canonical bytes of one episode render manifest."""
    return dumps_canonical(
        build_episode_render_manifest_document(
            render_plan=render_plan,
            results=results,
            environment=environment,
            witness_difference=witness_difference,
        ),
        "episode render manifest",
    )
