"""Phase 33 mapping, metrics and publisher under the V2 presentation profile.

The real EP1 geometry is the one pinned across this suite: 7 segments, 720 presentation
frames, three holds -- semantic 25 across presentation positions 25..133, semantic 61
across 169..494, semantic 96 across 529..624 -- and the three real slots ``[25, 60]``,
``[61, 95]``, ``[96, 144]`` (delivery plan table in ``docs/episode_narration_delivery_plan.md``).
"""

import copy
from pathlib import Path
from typing import Any

from living_diorama.media_assembly.media_assembly_audit import audit_media_assembly_directory
from living_diorama.media_assembly.media_assembly_mapping import (
    presentation_frame_map,
    presentation_motion_metrics,
    require_clock_closure,
    require_witness_frame_excluded,
)
from living_diorama.media_assembly.media_assembly_publisher import publish_episode_media_assembly
from living_diorama.media_assembly.media_assembly_spec import (
    PRESENTATION_DIRECTORY,
    presentation_frame_filename,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.presentation import build_episode_presentation_plan_document

# Real hold spans: (presentation start, presentation end, onset, slot_end, dwell).
HOLDS_EP1 = [(25, 133, 25, 60, 109), (169, 494, 61, 95, 326), (529, 624, 96, 144, 96)]


def _v2_plan(sources_ep1: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Build the real EP1 presentation plan under the V2 profile."""
    realization, _presentation, delivery, narration, *_rest = sources_ep1
    return build_episode_presentation_plan_document(
        delivery, narration, realization, presentation_profile="v2"
    )


def test_v1_regression_golden_mapping(sources_ep1: tuple[dict[str, Any], ...]) -> None:
    """The captured V1 golden: the real EP1 dwell sequence, untouched by the V2 path."""
    presentation = sources_ep1[1]
    mapping = presentation_frame_map(presentation)
    assert len(mapping) == 720
    assert mapping[24:133] == (25,) * 109
    assert mapping.count(25) == 109
    assert mapping.count(61) == 326
    assert mapping.count(96) == 96
    assert mapping[168:494] == (61,) * 326
    assert mapping[528:624] == (96,) * 96


def test_v2_mapping_is_a_bounce_within_the_safe_range_of_exact_length(
    sources_ep1: tuple[dict[str, Any], ...],
) -> None:
    """Each V2 hold's positions form a genuine in-slot bounce of the required length."""
    mapping = presentation_frame_map(_v2_plan(sources_ep1))
    assert len(mapping) == 720
    for start, end, onset, slot_end, dwell in HOLDS_EP1:
        frames = mapping[start - 1 : end]
        assert len(frames) == dwell
        assert len(set(frames)) > 1, "a genuine bounce, never constant"
        assert all(abs(frames[i] - frames[i - 1]) == 1 for i in range(1, len(frames)))
        assert frames[0] == onset, "entry continuity at the boundary into the hold"
        assert min(frames) == onset
        assert max(frames) <= slot_end, "never borrows a frame outside the unit's own slot"
        assert abs(frames[-1] - onset) <= 1, "exit lands within one frame of the onset"


def test_v2_mapping_differs_from_v1_only_inside_holds(
    sources_ep1: tuple[dict[str, Any], ...],
) -> None:
    """Outside the holds the two profiles agree position for position."""
    v1 = presentation_frame_map(sources_ep1[1])
    v2 = presentation_frame_map(_v2_plan(sources_ep1))
    assert v2 != v1
    held = set()
    for start, end, _onset, _slot_end, _dwell in HOLDS_EP1:
        held.update(range(start, end + 1))
    for position in range(1, len(v1) + 1):
        if position not in held:
            assert v2[position - 1] == v1[position - 1]


def test_clock_closure_holds_for_the_v2_plan(
    sources_ep1: tuple[dict[str, Any], ...],
    render_ep1: tuple[Path, dict[str, Any]],
    composition_ep1: Path,
) -> None:
    """The integer clock closes for the V2 plan exactly as for the V1 plan."""
    from living_diorama.media_assembly.media_assembly_mapping import require_clock_closure as clock

    composition = _composition(composition_ep1)
    _render_dir, render_manifest = render_ep1
    v1_clock = clock(sources_ep1[1], render_manifest, composition)
    v2_clock = clock(_v2_plan(sources_ep1), render_manifest, composition)
    assert v2_clock == v1_clock
    assert v2_clock["presentation_frames_total"] == 720


def test_witness_frame_exclusion_holds_for_the_v2_mapping(
    sources_ep1: tuple[dict[str, Any], ...],
    render_ep1: tuple[Path, dict[str, Any]],
    composition_ep1: Path,
) -> None:
    """The V2 mapping never reaches the witness frame."""
    mapping = presentation_frame_map(_v2_plan(sources_ep1))
    clock = require_clock_closure(
        _v2_plan(sources_ep1), render_ep1[1], _composition(composition_ep1)
    )
    require_witness_frame_excluded(mapping, clock)  # must not raise
    assert clock["witness_frame"] not in mapping


def test_motion_metrics_v1_freeze_versus_v2_motion(
    sources_ep1: tuple[dict[str, Any], ...],
) -> None:
    """V1 froze 528 of 720 positions; V2 freezes two, in one-frame runs."""
    v1 = presentation_motion_metrics(sources_ep1[1])
    v2 = presentation_motion_metrics(_v2_plan(sources_ep1))
    assert v1 == {
        "total_frames": 720,
        "frozen_frame_count": 528,
        "longest_freeze_run_frames": 325,
        "distinct_png_count_used": 192,
    }
    assert v2 == {
        "total_frames": 720,
        "frozen_frame_count": 2,
        "longest_freeze_run_frames": 1,
        "distinct_png_count_used": 192,
    }


def test_v1_hold_png_bytes_are_all_identical(assembly_dir_ep1: Path) -> None:
    """V1 publishes identical PNG bytes across each hold's positions."""
    for start, end, _onset, _slot_end, _dwell in HOLDS_EP1:
        payloads = {
            (
                assembly_dir_ep1 / PRESENTATION_DIRECTORY / presentation_frame_filename(p)
            ).read_bytes()
            for p in range(start, end + 1)
        }
        assert len(payloads) == 1


def test_publisher_v2_hold_png_bytes_are_not_all_identical(
    sources_ep1: tuple[dict[str, Any], ...],
    assembly_inputs_ep1: dict[str, Any],
    tmp_path: Path,
) -> None:
    """The Phase 33 publisher realises a V2 hold as distinct PNG bytes per position.

    The audio composition manifest is re-bound to the V2 plan's own digest -- the one
    document that names the presentation plan -- and everything else is the real EP1
    bundle, so the fresh publish exercises the true publisher, manifest builder and audit.
    """
    plan = _v2_plan(sources_ep1)
    plan_bytes = dumps_canonical(plan, "episode presentation plan")
    inputs = copy.deepcopy(assembly_inputs_ep1)
    inputs["presentation_plan"] = plan
    inputs["presentation_plan_bytes"] = plan_bytes
    composition = copy.deepcopy(inputs["audio_composition_manifest"])
    composition["source"]["presentation_plan_sha256"] = sha256_hex(plan_bytes)
    inputs["audio_composition_manifest"] = composition
    inputs["audio_composition_manifest_bytes"] = dumps_canonical(
        composition, "episode audio composition manifest"
    )

    final_dir = publish_episode_media_assembly(output_root=tmp_path, **inputs)
    assert audit_media_assembly_directory(final_dir) == []

    presentation_dir = final_dir / PRESENTATION_DIRECTORY
    for start, end, _onset, _slot_end, _dwell in HOLDS_EP1:
        payloads = {
            (presentation_dir / presentation_frame_filename(p)).read_bytes()
            for p in range(start, end + 1)
        }
        assert len(payloads) > 1, "a V2 hold must not publish one repeated PNG"


def _composition(composition_dir: Path) -> dict[str, Any]:
    from living_diorama.audio_composition.audio_composition_spec import (
        AUDIO_COMPOSITION_MANIFEST_FILENAME,
    )
    from living_diorama.persistence.json_codec import loads_canonical

    raw = (composition_dir / AUDIO_COMPOSITION_MANIFEST_FILENAME).read_bytes()
    return loads_canonical(raw, "episode audio composition manifest")  # type: ignore[return-value]
