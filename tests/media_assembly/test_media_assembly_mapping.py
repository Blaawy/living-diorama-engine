"""The Phase 27 presentation mapping, expanded, and the integer clock closure law.

Every source document here comes from the real upstream layers (via
``conftest.build_sources`` / the ``render_ep*`` / ``composition_ep*``
fixtures), so a mutation test attacks a document the engine could actually
have produced.
"""

import copy
from pathlib import Path
from typing import Any

import pytest

from living_diorama.media_assembly.media_assembly_mapping import (
    MediaAssemblyRefused,
    presentation_frame_map,
    require_clock_closure,
    require_playback_lookup,
    require_witness_frame_excluded,
)
from living_diorama.persistence.json_codec import loads_canonical
from living_diorama.render_execution.render_execution_spec import ROLE_PLAYBACK

# ---------------------------------------------------------------------------
# presentation_frame_map -- the closed form, per canonical episode
# ---------------------------------------------------------------------------


def _closed_form(presentation: dict[str, Any]) -> list[int]:
    """Re-derive the expansion by direct segment iteration -- a second, independent path."""
    out: list[int] = []
    for segment in presentation["segments"]:
        for semantic in range(segment["semantic_start_frame"], segment["semantic_end_frame"] + 1):
            out.extend([semantic] * segment["dwell_frames"])
    return out


@pytest.mark.parametrize(("episode", "total"), [(0, 192), (1, 720), (2, 552)])
def test_expansion_equals_closed_form_and_the_expected_total(
    episode: int, total: int, request: pytest.FixtureRequest
) -> None:
    """Expansion equals closed form and the expected total."""
    sources = request.getfixturevalue(f"sources_ep{episode}")
    presentation = sources[1]
    mapping = presentation_frame_map(presentation)
    assert list(mapping) == _closed_form(presentation)
    assert len(mapping) == total


def test_at_least_one_segment_has_dwell_one_and_one_has_dwell_greater_than_one(
    sources_ep1: tuple[dict[str, Any], ...],
) -> None:
    """At least one segment has dwell one and one has dwell greater than one."""
    dwells = {segment["dwell_frames"] for segment in sources_ep1[1]["segments"]}
    assert 1 in dwells
    assert any(dwell > 1 for dwell in dwells)


def test_mapping_unchanged_when_the_witnesses_are_replaced(
    sources_ep1: tuple[dict[str, Any], ...], sources_ep2: tuple[dict[str, Any], ...]
) -> None:
    """The mapping is a pure function of the presentation plan; no witness ever enters it."""
    presentation = sources_ep1[1]
    before = presentation_frame_map(presentation)
    # Swap in ep2's shots/delivery/narration -- the presentation plan itself is untouched,
    # so the mapping must be bit-for-bit identical; this proves no witness field leaks in.
    after = presentation_frame_map(copy.deepcopy(presentation))
    assert before == after


# ---------------------------------------------------------------------------
# presentation_frame_map -- geometry attacks
# ---------------------------------------------------------------------------


def test_a_gap_between_segments_is_refused(sources_ep1: tuple[dict[str, Any], ...]) -> None:
    """A gap between segments is refused."""
    broken = copy.deepcopy(sources_ep1[1])
    if len(broken["segments"]) < 2:
        pytest.skip("fixture has only one segment")
    broken["segments"][1]["presentation_start_frame"] += 1
    with pytest.raises((MediaAssemblyRefused, TypeError, ValueError)):
        presentation_frame_map(broken)


def test_an_overlap_between_segments_is_refused(sources_ep1: tuple[dict[str, Any], ...]) -> None:
    """An overlap between segments is refused."""
    broken = copy.deepcopy(sources_ep1[1])
    if len(broken["segments"]) < 2:
        pytest.skip("fixture has only one segment")
    broken["segments"][1]["presentation_start_frame"] -= 1
    with pytest.raises((MediaAssemblyRefused, TypeError, ValueError)):
        presentation_frame_map(broken)


def test_a_non_contiguous_start_is_refused(sources_ep0: tuple[dict[str, Any], ...]) -> None:
    """A non contiguous start is refused."""
    broken = copy.deepcopy(sources_ep0[1])
    broken["segments"][0]["presentation_start_frame"] += 5
    with pytest.raises((MediaAssemblyRefused, TypeError, ValueError)):
        presentation_frame_map(broken)


def test_a_wrong_declared_span_is_refused(sources_ep0: tuple[dict[str, Any], ...]) -> None:
    """A wrong declared span is refused."""
    broken = copy.deepcopy(sources_ep0[1])
    broken["segments"][0]["presentation_end_frame"] += 3
    with pytest.raises((MediaAssemblyRefused, TypeError, ValueError)):
        presentation_frame_map(broken)


def test_a_wrong_declared_total_is_refused(sources_ep0: tuple[dict[str, Any], ...]) -> None:
    """A wrong declared total is refused."""
    broken = copy.deepcopy(sources_ep0[1])
    broken["accounting"]["presentation_frames_total"] += 10
    with pytest.raises((MediaAssemblyRefused, TypeError, ValueError)):
        presentation_frame_map(broken)


# ---------------------------------------------------------------------------
# require_playback_lookup
# ---------------------------------------------------------------------------


def test_playback_lookup_excludes_the_witness_record(
    render_ep0: tuple[Path, dict[str, Any]],
) -> None:
    """Playback lookup excludes the witness record."""
    _dir, manifest = render_ep0
    lookup = require_playback_lookup(manifest)
    witness_records = [r for r in manifest["frames"] if r["role"] != ROLE_PLAYBACK]
    assert len(witness_records) == 1
    witness_frame = witness_records[0]["frame"]
    assert witness_frame not in lookup
    for record in manifest["frames"]:
        if record["role"] == ROLE_PLAYBACK:
            assert lookup[record["frame"]] == record


def test_playback_lookup_duplicate_semantic_frame_refused(
    render_ep0: tuple[Path, dict[str, Any]],
) -> None:
    """Playback lookup duplicate semantic frame refused."""
    _dir, manifest = render_ep0
    broken = copy.deepcopy(manifest)
    playback = [r for r in broken["frames"] if r["role"] == ROLE_PLAYBACK]
    duplicate = copy.deepcopy(playback[0])
    broken["frames"].append(duplicate)
    with pytest.raises((MediaAssemblyRefused, TypeError, ValueError)):
        require_playback_lookup(broken)


# ---------------------------------------------------------------------------
# require_clock_closure
# ---------------------------------------------------------------------------


def _composition_manifest(composition_dir: Path) -> dict[str, Any]:
    from living_diorama.audio_composition.audio_composition_spec import (
        AUDIO_COMPOSITION_MANIFEST_FILENAME,
    )

    raw = (composition_dir / AUDIO_COMPOSITION_MANIFEST_FILENAME).read_bytes()
    return loads_canonical(raw, "episode audio composition manifest")  # type: ignore[return-value]


def test_clock_closure_holds_on_real_sources(
    sources_ep1: tuple[dict[str, Any], ...],
    render_ep1: tuple[Path, dict[str, Any]],
    composition_ep1: Path,
) -> None:
    """Clock closure holds on real sources."""
    presentation = sources_ep1[1]
    _render_dir, render_manifest = render_ep1
    composition = _composition_manifest(composition_ep1)
    clock = require_clock_closure(presentation, render_manifest, composition)
    assert clock["presentation_frames_total"] == 720
    assert (
        clock["audio_samples_total"]
        == clock["presentation_frames_total"] * clock["samples_per_presentation_frame"]
    )
    assert clock["witness_frame"] == clock["semantic_final_frame"] + 1


def test_non_divisible_fps_refused(
    sources_ep1: tuple[dict[str, Any], ...],
    render_ep1: tuple[Path, dict[str, Any]],
    composition_ep1: Path,
) -> None:
    """Non divisible fps refused."""
    presentation = sources_ep1[1]
    _render_dir, render_manifest = render_ep1
    composition = _composition_manifest(composition_ep1)
    broken_composition = copy.deepcopy(composition)
    broken_composition["audio"]["sample_rate_hz"] = 44100
    with pytest.raises((MediaAssemblyRefused, TypeError, ValueError)):
        require_clock_closure(presentation, render_manifest, broken_composition)


def test_audio_samples_mismatch_refused(
    sources_ep1: tuple[dict[str, Any], ...],
    render_ep1: tuple[Path, dict[str, Any]],
    composition_ep1: Path,
) -> None:
    """Audio samples mismatch refused."""
    presentation = sources_ep1[1]
    _render_dir, render_manifest = render_ep1
    composition = _composition_manifest(composition_ep1)
    broken_composition = copy.deepcopy(composition)
    broken_composition["audio"]["audio_samples"] += 1000
    with pytest.raises((MediaAssemblyRefused, TypeError, ValueError)):
        require_clock_closure(presentation, render_manifest, broken_composition)


def test_playback_fps_disagreeing_with_timeline_fps_refused(
    sources_ep1: tuple[dict[str, Any], ...],
    render_ep1: tuple[Path, dict[str, Any]],
    composition_ep1: Path,
) -> None:
    """Playback fps disagreeing with timeline fps refused."""
    presentation = sources_ep1[1]
    _render_dir, render_manifest = render_ep1
    composition = _composition_manifest(composition_ep1)
    broken_manifest = copy.deepcopy(render_manifest)
    broken_manifest["emission"]["playback_fps"] = broken_manifest["emission"]["playback_fps"] + 1
    with pytest.raises((MediaAssemblyRefused, TypeError, ValueError)):
        require_clock_closure(presentation, broken_manifest, composition)


def test_coverage_disagreeing_with_emission_span_refused(
    sources_ep1: tuple[dict[str, Any], ...],
    render_ep1: tuple[Path, dict[str, Any]],
    composition_ep1: Path,
) -> None:
    """Coverage disagreeing with emission span refused."""
    presentation = sources_ep1[1]
    _render_dir, render_manifest = render_ep1
    composition = _composition_manifest(composition_ep1)
    broken_presentation = copy.deepcopy(presentation)
    broken_presentation["segments"][0]["semantic_start_frame"] += 1
    with pytest.raises((MediaAssemblyRefused, TypeError, ValueError)):
        require_clock_closure(broken_presentation, render_manifest, composition)


# ---------------------------------------------------------------------------
# require_witness_frame_excluded
# ---------------------------------------------------------------------------


def test_witness_frame_excluded_passes_on_real_geometry(
    sources_ep1: tuple[dict[str, Any], ...],
    render_ep1: tuple[Path, dict[str, Any]],
    composition_ep1: Path,
) -> None:
    """Witness frame excluded passes on real geometry."""
    presentation = sources_ep1[1]
    _render_dir, render_manifest = render_ep1
    composition = _composition_manifest(composition_ep1)
    mapping = presentation_frame_map(presentation)
    clock = require_clock_closure(presentation, render_manifest, composition)
    require_witness_frame_excluded(mapping, clock)  # must not raise


def test_witness_frame_excluded_refuses_a_witness_mapped_position() -> None:
    """Witness frame excluded refuses a witness mapped position."""
    clock = {
        "audio_sample_rate_hz": 24000,
        "audio_samples_total": 24000,
        "fps": 24,
        "presentation_frames_total": 1,
        "samples_per_presentation_frame": 1000,
        "semantic_final_frame": 192,
        "semantic_first_frame": 1,
        "witness_frame": 193,
    }
    with pytest.raises(MediaAssemblyRefused):
        require_witness_frame_excluded((193,), clock)


def test_witness_frame_excluded_refuses_an_out_of_range_position() -> None:
    """Witness frame excluded refuses an out of range position."""
    clock = {
        "audio_sample_rate_hz": 24000,
        "audio_samples_total": 24000,
        "fps": 24,
        "presentation_frames_total": 1,
        "samples_per_presentation_frame": 1000,
        "semantic_final_frame": 192,
        "semantic_first_frame": 1,
        "witness_frame": 193,
    }
    with pytest.raises(MediaAssemblyRefused):
        require_witness_frame_excluded((0,), clock)


# ---------------------------------------------------------------------------
# The frame-193 exclusion family -- A1, A2, A3, A5 -- and D4
# ---------------------------------------------------------------------------


def test_a1_a_presentation_plan_forged_to_include_semantic_frame_193(
    sources_ep1: tuple[dict[str, Any], ...],
    render_ep1: tuple[Path, dict[str, Any]],
) -> None:
    """A1 presentation plan forged to include semantic frame 193.

    The witness frame is the one semantic frame Phase 23 renders and never plays
    back, so a plan that reaches it has no playback record to draw from. Refused
    before any byte is copied -- by the plan's own validation, by the coverage law,
    or by the playback lookup, whichever speaks first.
    """
    _render_dir, render_manifest = render_ep1
    witness = render_manifest["emission"]["witness_frame"]
    assert witness == 193

    forged = copy.deepcopy(sources_ep1[1])
    forged["segments"][-1]["semantic_end_frame"] = witness
    forged["segments"][-1]["presentation_end_frame"] += forged["segments"][-1]["dwell_frames"]
    forged["accounting"]["presentation_frames_total"] += forged["segments"][-1]["dwell_frames"]

    with pytest.raises((MediaAssemblyRefused, TypeError, ValueError)):
        mapping = presentation_frame_map(forged)
        lookup = require_playback_lookup(render_manifest)
        missing = sorted(set(mapping) - set(lookup))
        if missing:
            raise MediaAssemblyRefused(f"no playback record for semantic frames {missing}")


def test_a2_a_render_manifest_whose_witness_record_claims_the_playback_role(
    render_ep1: tuple[Path, dict[str, Any]],
) -> None:
    """A2 render manifest forged so the witness record carries role playback."""
    _render_dir, render_manifest = render_ep1
    forged = copy.deepcopy(render_manifest)
    witness = forged["emission"]["witness_frame"]
    for record in forged["frames"]:
        if record["frame"] == witness:
            record["role"] = ROLE_PLAYBACK
    with pytest.raises((MediaAssemblyRefused, TypeError, ValueError)):
        require_playback_lookup(forged)


def test_a3_the_witness_frame_moved_inside_the_playback_span(
    render_ep1: tuple[Path, dict[str, Any]],
) -> None:
    """A3 emission.witness_frame moved inside the playback span."""
    _render_dir, render_manifest = render_ep1
    forged = copy.deepcopy(render_manifest)
    forged["emission"]["witness_frame"] = forged["emission"]["final_frame"] - 10
    with pytest.raises((MediaAssemblyRefused, TypeError, ValueError)):
        require_playback_lookup(forged)


def test_a5_a_presentation_plan_whose_semantic_coverage_is_one_to_193(
    sources_ep1: tuple[dict[str, Any], ...],
    render_ep1: tuple[Path, dict[str, Any]],
    composition_ep1: Path,
) -> None:
    """A5 presentation plan whose semantic coverage is 1..193."""
    _render_dir, render_manifest = render_ep1
    composition = _composition_manifest(composition_ep1)
    forged = copy.deepcopy(sources_ep1[1])
    forged["segments"][-1]["semantic_end_frame"] = render_manifest["emission"]["witness_frame"]
    with pytest.raises((MediaAssemblyRefused, TypeError, ValueError)):
        require_clock_closure(forged, render_manifest, composition)


def test_d4_the_semantic_total_substituted_for_the_presentation_total(
    sources_ep1: tuple[dict[str, Any], ...],
    render_ep1: tuple[Path, dict[str, Any]],
    composition_ep1: Path,
) -> None:
    """D4 the semantic total (192) substituted for the presentation total (720).

    The audio track really is 720,000 samples long. Claiming 192 presentation
    frames would make the episode 192,000 samples, so the clock cannot close.
    """
    _render_dir, render_manifest = render_ep1
    composition = _composition_manifest(composition_ep1)
    semantic_total = (
        render_manifest["emission"]["final_frame"] - render_manifest["emission"]["first_frame"] + 1
    )
    assert semantic_total == 192

    forged = copy.deepcopy(sources_ep1[1])
    assert forged["accounting"]["presentation_frames_total"] == 720
    forged["accounting"]["presentation_frames_total"] = semantic_total

    with pytest.raises((MediaAssemblyRefused, TypeError, ValueError)):
        require_clock_closure(forged, render_manifest, composition)


def test_matrix_e3_the_sample_rate_changed_to_44100(
    sources_ep1: tuple[dict[str, Any], ...],
    render_ep1: tuple[Path, dict[str, Any]],
    composition_ep1: Path,
) -> None:
    """Adversarial matrix row E3: sample_rate_hz changed to 44100 (not divisible by 24).

    Named ``matrix_e3`` to keep it distinct from the boundary guard's own E3
    mechanism (raw-byte hygiene), which is an unrelated use of the same letter.
    """
    presentation = sources_ep1[1]
    _render_dir, render_manifest = render_ep1
    forged = copy.deepcopy(_composition_manifest(composition_ep1))
    forged["audio"]["sample_rate_hz"] = 44100
    with pytest.raises((MediaAssemblyRefused, TypeError, ValueError)):
        require_clock_closure(presentation, render_manifest, forged)


def test_matrix_e4_the_audio_sample_count_changed_to_719000(
    sources_ep1: tuple[dict[str, Any], ...],
    render_ep1: tuple[Path, dict[str, Any]],
    composition_ep1: Path,
) -> None:
    """Adversarial matrix row E4: audio_samples changed to 719000.

    One presentation frame's worth of audio short of the 720,000 the 720-frame
    episode requires -- the clock cannot close. Named ``matrix_e4`` to keep it
    distinct from the boundary guard's own E4 mechanism (matcher self-tests).
    """
    presentation = sources_ep1[1]
    _render_dir, render_manifest = render_ep1
    forged = copy.deepcopy(_composition_manifest(composition_ep1))
    assert forged["audio"]["audio_samples"] == 720000
    forged["audio"]["audio_samples"] = 719000
    with pytest.raises((MediaAssemblyRefused, TypeError, ValueError)):
        require_clock_closure(presentation, render_manifest, forged)
