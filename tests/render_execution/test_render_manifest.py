"""Building and attacking the Episode Render Manifest.

A manifest is the only thing that stands between a directory of images and a
claim that an episode was rendered. These tests make sure it cannot be talked
into that claim: not by omitting a frame, not by asserting completeness, and
not by reaching a boundary verdict its own measured difference denies.
"""

import copy
from typing import Any

import pytest

from living_diorama.render_execution import (
    build_episode_render_manifest_document,
    validate_episode_render_manifest,
)

ENVIRONMENT = {"blender_version": "4.5.12", "engine": "CYCLES", "device": "OPTIX"}


def _results(plan: dict[str, Any]) -> dict[int, dict[str, object]]:
    """Fabricate one plausible render result per planned frame.

    Two digests each, as a real render records: the file, and the image data
    alone. They differ per frame here so that a test which loses or duplicates
    a record cannot pass by coincidence.
    """
    results: dict[int, dict[str, object]] = {}
    for index, entry in enumerate(plan["frames"]):
        results[entry["frame"]] = {
            "bytes": 1000 + index,
            "sha256": f"{index:064x}",
            "image_sha256": f"{index + 500:064x}",
        }
    return results


def test_a_complete_render_produces_a_complete_manifest(render_plan: dict[str, Any]) -> None:
    """The control: every planned frame recorded, completeness claimed once."""
    manifest = build_episode_render_manifest_document(
        render_plan=render_plan,
        results=_results(render_plan),
        environment=ENVIRONMENT,
        witness_difference=0.0142,
    )
    completeness = manifest["completeness"]
    assert completeness["complete"] is True
    assert completeness["playback_frames_expected"] == 192
    assert completeness["playback_frames_rendered"] == 192
    assert completeness["witness_frames_rendered"] == 1
    assert completeness["witness_mean_abs_difference"] == 0.0142
    assert completeness["witness_within_tolerance"] is True


def test_the_manifest_binds_the_plan_it_was_rendered_from(
    render_plan: dict[str, Any],
) -> None:
    """A manifest can never float free of its plan."""
    manifest = build_episode_render_manifest_document(
        render_plan=render_plan,
        results=_results(render_plan),
        environment=ENVIRONMENT,
        witness_difference=0.0142,
    )
    from living_diorama.persistence.json_codec import dumps_canonical
    from living_diorama.persistence.schema.state_hash import sha256_hex

    expected = sha256_hex(dumps_canonical(render_plan, "episode render plan"))
    assert manifest["source"]["render_plan_sha256"] == expected
    assert manifest["source"]["shot_plan_sha256"] == render_plan["source"]["shot_plan_sha256"]


def test_the_manifest_records_the_environment_that_made_the_pixels(
    render_plan: dict[str, Any],
) -> None:
    """The honest half of determinism: say what produced these bytes."""
    manifest = build_episode_render_manifest_document(
        render_plan=render_plan,
        results=_results(render_plan),
        environment=ENVIRONMENT,
        witness_difference=0.0142,
    )
    assert manifest["environment"] == ENVIRONMENT


def test_a_manifest_cannot_be_built_while_a_frame_is_missing(
    render_plan: dict[str, Any],
) -> None:
    """A manifest is written for a finished render, never to record progress."""
    results = _results(render_plan)
    del results[87]
    with pytest.raises(ValueError, match="no render result"):
        build_episode_render_manifest_document(
            render_plan=render_plan,
            results=results,
            environment=ENVIRONMENT,
            witness_difference=0.0142,
        )


def test_a_result_for_a_frame_nobody_planned_is_refused(
    render_plan: dict[str, Any],
) -> None:
    """A stray file's digest cannot be smuggled into a manifest."""
    results = _results(render_plan)
    results[900] = {"bytes": 10, "sha256": "0" * 64}
    with pytest.raises(ValueError, match="never asked for"):
        build_episode_render_manifest_document(
            render_plan=render_plan,
            results=results,
            environment=ENVIRONMENT,
            witness_difference=0.0142,
        )


def test_the_witness_verdict_is_computed_from_the_measurement(
    render_plan: dict[str, Any],
) -> None:
    """A boundary frame that drifted far from the last playback frame says so.

    Nine and a half levels is far outside what the canonical leg measures, so
    the manifest must report that the episode did not end where the contract
    expects rather than quietly rounding the claim in its favour.
    """
    manifest = build_episode_render_manifest_document(
        render_plan=render_plan,
        results=_results(render_plan),
        environment=ENVIRONMENT,
        witness_difference=9.5,
    )
    completeness = manifest["completeness"]
    assert completeness["witness_mean_abs_difference"] == 9.5
    assert completeness["witness_within_tolerance"] is False


def test_a_manifest_whose_verdict_contradicts_its_measurement_is_refused(
    render_plan: dict[str, Any],
) -> None:
    """The verdict is computed from the measurement, never asserted beside it."""
    manifest = build_episode_render_manifest_document(
        render_plan=render_plan,
        results=_results(render_plan),
        environment=ENVIRONMENT,
        witness_difference=9.5,
    )
    manifest["completeness"]["witness_within_tolerance"] = True
    with pytest.raises(ValueError, match="opposite verdict"):
        validate_episode_render_manifest(manifest)


def test_a_manifest_carrying_a_negative_difference_is_refused(
    render_plan: dict[str, Any],
) -> None:
    """A distance below zero is not a measurement."""
    manifest = build_episode_render_manifest_document(
        render_plan=render_plan,
        results=_results(render_plan),
        environment=ENVIRONMENT,
        witness_difference=0.0142,
    )
    manifest["completeness"]["witness_mean_abs_difference"] = -1.0
    with pytest.raises(ValueError, match="negative difference"):
        validate_episode_render_manifest(manifest)


def test_a_frame_record_missing_its_image_digest_is_refused(
    render_plan: dict[str, Any],
) -> None:
    """Both digests are required: the file, and the image-content digest."""
    manifest = build_episode_render_manifest_document(
        render_plan=render_plan,
        results=_results(render_plan),
        environment=ENVIRONMENT,
        witness_difference=0.0142,
    )
    del manifest["frames"][0]["image_sha256"]
    with pytest.raises(ValueError):
        validate_episode_render_manifest(manifest)


def test_a_manifest_claiming_completeness_while_short_a_frame_is_refused(
    render_plan: dict[str, Any],
) -> None:
    """The claim a partial render would most like to make."""
    manifest = build_episode_render_manifest_document(
        render_plan=render_plan,
        results=_results(render_plan),
        environment=ENVIRONMENT,
        witness_difference=0.0142,
    )
    del manifest["frames"][86]
    with pytest.raises(ValueError):
        validate_episode_render_manifest(manifest)


def test_a_manifest_whose_counts_disagree_with_its_records_is_refused(
    render_plan: dict[str, Any],
) -> None:
    """Counting is not a separate opinion from the records."""
    manifest = build_episode_render_manifest_document(
        render_plan=render_plan,
        results=_results(render_plan),
        environment=ENVIRONMENT,
        witness_difference=0.0142,
    )
    manifest["completeness"]["playback_frames_rendered"] = 191
    with pytest.raises(ValueError, match="playback frames rendered"):
        validate_episode_render_manifest(manifest)


def test_a_zero_byte_frame_is_refused(render_plan: dict[str, Any]) -> None:
    """An empty file is not a frame, whatever its digest says."""
    manifest = build_episode_render_manifest_document(
        render_plan=render_plan,
        results=_results(render_plan),
        environment=ENVIRONMENT,
        witness_difference=0.0142,
    )
    manifest["frames"][0]["bytes"] = 0
    with pytest.raises(ValueError, match="not a frame"):
        validate_episode_render_manifest(manifest)


def test_a_manifest_missing_its_environment_is_refused(render_plan: dict[str, Any]) -> None:
    """Pixels without a stated environment cannot be interpreted."""
    manifest = build_episode_render_manifest_document(
        render_plan=render_plan,
        results=_results(render_plan),
        environment=ENVIRONMENT,
        witness_difference=0.0142,
    )
    del manifest["environment"]["device"]
    with pytest.raises(ValueError):
        validate_episode_render_manifest(manifest)


def test_an_emission_whose_span_disagrees_with_its_count_is_refused(
    render_plan: dict[str, Any],
) -> None:
    """A manifest is checked against its own arithmetic, not only its plan's."""
    manifest = build_episode_render_manifest_document(
        render_plan=render_plan,
        results=_results(render_plan),
        environment=ENVIRONMENT,
        witness_difference=0.0142,
    )
    manifest["emission"]["final_frame"] = 191
    with pytest.raises(ValueError):
        validate_episode_render_manifest(manifest)


def test_a_manifest_built_from_a_broken_plan_is_refused(
    render_plan: dict[str, Any],
) -> None:
    """The plan is re-validated on the way in; a bad plan cannot be recorded."""
    broken = copy.deepcopy(render_plan)
    broken["emission"]["frame_count"] = 193
    with pytest.raises(ValueError):
        build_episode_render_manifest_document(
            render_plan=broken,
            results=_results(render_plan),
            environment=ENVIRONMENT,
            witness_difference=0.0142,
        )


def test_the_manifest_frame_records_keep_their_direction(
    render_plan: dict[str, Any],
) -> None:
    """Story beat to shot to camera to frame to file, in one document."""
    manifest = build_episode_render_manifest_document(
        render_plan=render_plan,
        results=_results(render_plan),
        environment=ENVIRONMENT,
        witness_difference=0.0142,
    )
    for planned, recorded in zip(render_plan["frames"], manifest["frames"], strict=True):
        assert recorded["frame"] == planned["frame"]
        assert recorded["shot_id"] == planned["shot_id"]
        assert recorded["camera_anchor_id"] == planned["camera_anchor_id"]
        assert recorded["source_beat_ids"] == planned["source_beat_ids"]
        assert recorded["file"] == planned["file"]
