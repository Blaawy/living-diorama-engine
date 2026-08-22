"""The direction policy is a closed, finite, reviewable table.

These tests guard the property that makes Phase 22 auditable: every camera it can
choose is one the world builders already created, every beat kind it knows maps to
exactly one of them, and the catalogue cannot drift away from the configs that
define those cameras.
"""

import json
from pathlib import Path
from typing import Any

from living_diorama.cinematic import cinematic_spec
from living_diorama.story import story_spec

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "visual" / "blender" / "config"


def _config_cameras(name: str) -> dict[str, Any]:
    document = json.loads((CONFIG_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return document["cameras"]


# ------------------------------------------------- the catalogue is the truth


def test_the_catalogue_is_exactly_the_cameras_the_world_builders_create() -> None:
    """The single most important guard: no invented viewpoints, ever."""
    built = set(_config_cameras("master_scene_v1")) | set(_config_cameras("production_world_v1"))
    assert set(cinematic_spec.CAMERA_ANCHORS) == built


def test_every_catalogue_record_matches_the_locked_config() -> None:
    """A restated catalogue that drifts is worse than no catalogue.

    Every field of an anchor's visual identity is mechanically cross-checked
    against the config the builder reads: location, look-at, lens, aperture,
    and the depth-of-field focus point (which Phase 15 always takes from the
    look-at, and Phase 16 takes from an explicit ``focus`` with the look-at as
    its fallback -- the builders' own defaulting, replicated exactly).
    """
    configs = {
        cinematic_spec.ANCHOR_PHASE15: _config_cameras("master_scene_v1"),
        cinematic_spec.ANCHOR_PHASE16: _config_cameras("production_world_v1"),
    }
    for anchor, record in cinematic_spec.CAMERA_ANCHORS.items():
        locked = configs[record["source"]][anchor]
        assert record["lens_mm"] == locked["lens_mm"], anchor
        assert record["f_stop"] == locked["f_stop"], anchor
        assert list(record["location"]) == locked["location"], anchor
        assert list(record["look_at"]) == locked["look_at"], anchor
        expected_focus = locked.get("focus", locked["look_at"])
        assert list(record["focus"]) == expected_focus, anchor


def test_every_catalogue_record_is_complete_and_immutable() -> None:
    """Each record carries the anchor's whole locked identity, frozen."""
    expected_keys = {
        "source",
        "location",
        "look_at",
        "focus",
        "lens_mm",
        "f_stop",
        "dof",
        "clip_end",
        "clip_start",
        "projection",
        "sensor_width_mm",
        "sensor_height_mm",
        "sensor_fit",
        "shift_x",
        "shift_y",
        "aperture_ratio",
        "aperture_blades",
        "aperture_rotation",
    }
    for anchor, record in cinematic_spec.CAMERA_ANCHORS.items():
        assert set(record) == expected_keys, anchor
        assert type(record).__name__ == "mappingproxy", anchor
        for field in ("location", "look_at", "focus"):
            vector = record[field]
            assert isinstance(vector, tuple) and len(vector) == 3, (anchor, field)
            assert all(isinstance(component, float) for component in vector), (anchor, field)
        assert isinstance(record["dof"], bool), anchor
        assert record["clip_end"] == cinematic_spec.ANCHOR_CLIP_END, anchor
        assert record["clip_start"] == cinematic_spec.ANCHOR_CLIP_START, anchor
        assert record["projection"] == cinematic_spec.ANCHOR_PROJECTION, anchor
        assert record["sensor_width_mm"] == cinematic_spec.ANCHOR_SENSOR_WIDTH, anchor
        assert record["sensor_height_mm"] == cinematic_spec.ANCHOR_SENSOR_HEIGHT, anchor
        assert record["sensor_fit"] == cinematic_spec.ANCHOR_SENSOR_FIT, anchor
        assert record["shift_x"] == cinematic_spec.ANCHOR_SHIFT, anchor
        assert record["shift_y"] == cinematic_spec.ANCHOR_SHIFT, anchor
        assert record["aperture_ratio"] == cinematic_spec.ANCHOR_APERTURE_RATIO, anchor
        assert record["aperture_blades"] == cinematic_spec.ANCHOR_APERTURE_BLADES, anchor
        assert record["aperture_rotation"] == cinematic_spec.ANCHOR_APERTURE_ROTATION, anchor


def test_depth_of_field_is_disabled_exactly_where_the_builders_disable_it() -> None:
    """The builders disable depth of field on the three survey anchors only.

    ``build_master_scene.build_cameras`` turns it off for CAM_VERIFY_TOPOLOGY,
    and ``build_production_world.build_production_cameras`` for CAM_P16_ROADS
    and CAM_P16_VALIDITY; every other anchor gets a focused, apertured lens. The
    catalogue must say the same, because the applier proves the scene against
    whichever claim it makes.
    """
    disabled = {
        anchor for anchor, record in cinematic_spec.CAMERA_ANCHORS.items() if not record["dof"]
    }
    assert disabled == {"CAM_VERIFY_TOPOLOGY", "CAM_P16_ROADS", "CAM_P16_VALIDITY"}


def test_phase15_anchors_focus_on_their_look_at_point() -> None:
    """Phase 15's builder always focuses a depth-of-field camera on its target."""
    for anchor, record in cinematic_spec.CAMERA_ANCHORS.items():
        if record["source"] == cinematic_spec.ANCHOR_PHASE15:
            assert record["focus"] == record["look_at"], anchor


def test_the_catalogue_digest_is_deterministic_and_value_sensitive() -> None:
    """The catalogue's identity is its values, computed the same way twice."""
    first = cinematic_spec.catalogue_sha256()
    second = cinematic_spec.catalogue_sha256()
    assert first == second
    assert len(first) == 64


def test_the_catalogue_document_is_json_ready() -> None:
    """Vectors become lists so any JSON round-trip digests identically."""
    import json

    document = cinematic_spec.catalogue_document()
    for record in document.values():
        for value in record.values():
            assert not isinstance(value, tuple)
    round_tripped = json.loads(json.dumps(document))
    assert round_tripped == document


def test_the_catalogue_excludes_proof_only_cameras() -> None:
    """P18 and P19 cameras are built by proof producers, not by the world."""
    for anchor in cinematic_spec.CAMERA_ANCHORS:
        assert not anchor.startswith("CAM_P18_"), anchor
        assert not anchor.startswith("CAM_P19_"), anchor


def test_the_catalogue_has_fourteen_anchors() -> None:
    """Five from Phase 15, nine from Phase 16."""
    sources = [record["source"] for record in cinematic_spec.CAMERA_ANCHORS.values()]
    assert sources.count(cinematic_spec.ANCHOR_PHASE15) == 5
    assert sources.count(cinematic_spec.ANCHOR_PHASE16) == 9
    assert len(cinematic_spec.CAMERA_ANCHORS) == 14


def test_anchor_names_are_sorted_and_unique() -> None:
    """Anchor names are sorted and unique."""
    names = cinematic_spec.ANCHOR_NAMES
    assert list(names) == sorted(set(names))


def test_the_establishing_anchor_is_in_the_catalogue() -> None:
    """The establishing anchor is in the catalogue."""
    assert cinematic_spec.ESTABLISHING_ANCHOR in cinematic_spec.CAMERA_ANCHORS


# ------------------------------------------------------- the rule table binds


def test_every_beat_kind_rule_names_a_catalogued_anchor() -> None:
    """Every beat kind rule names a catalogued anchor."""
    for kind, anchor in cinematic_spec.BEAT_ANCHORS.items():
        assert anchor in cinematic_spec.CAMERA_ANCHORS, kind


def test_the_policy_has_an_opinion_about_every_phase21_beat_kind() -> None:
    """Every kind gets an anchor OR a stated reason there is none -- never silence."""
    covered = set(cinematic_spec.BEAT_ANCHORS) | set(cinematic_spec.UNSHOWN_BEAT_KINDS)
    missing = set(story_spec.BEAT_KINDS) - covered
    assert missing == set(), f"no policy for: {sorted(missing)}"
    overlap = set(cinematic_spec.BEAT_ANCHORS) & set(cinematic_spec.UNSHOWN_BEAT_KINDS)
    assert overlap == set(), f"kinds both anchored and unshown: {sorted(overlap)}"


def test_every_deliberate_unshown_reason_is_in_the_unshown_vocabulary() -> None:
    """Every deliberate unshown reason is in the unshown vocabulary."""
    for kind, reason in cinematic_spec.UNSHOWN_BEAT_KINDS.items():
        assert reason in cinematic_spec.UNSHOWN_REASONS, kind


def test_the_table_names_no_beat_kind_phase21_cannot_emit() -> None:
    """A rule for a kind that never arrives is dead policy."""
    extra = set(cinematic_spec.BEAT_ANCHORS) - set(story_spec.BEAT_KINDS)
    assert extra == set(), f"rules for unknown kinds: {sorted(extra)}"


def test_every_phase21_emphasis_level_has_a_weight() -> None:
    """Every Phase 21 emphasis level has a weight."""
    assert set(cinematic_spec.EMPHASIS_WEIGHTS) == set(story_spec.EMPHASIS_LEVELS)


def test_stronger_emphasis_never_earns_less_screen_time() -> None:
    """Stronger emphasis never earns less screen time."""
    weights = [cinematic_spec.weight_for_emphasis(level) for level in story_spec.EMPHASIS_LEVELS]
    assert weights == sorted(weights, reverse=True)


def test_the_empty_result_kind_matches_phase21() -> None:
    """The empty result kind matches Phase 21."""
    assert cinematic_spec.EMPTY_RESULT_BEAT_KIND == story_spec.BEAT_NO_EMPHASIZED_BEATS


def test_the_tables_are_read_only() -> None:
    """A mutable policy table is a policy that can drift at runtime."""
    for table in (
        cinematic_spec.CAMERA_ANCHORS,
        cinematic_spec.BEAT_ANCHORS,
        cinematic_spec.EMPHASIS_WEIGHTS,
    ):
        assert type(table).__name__ == "mappingproxy"


def test_reason_codes_are_unique() -> None:
    """Reason codes are unique."""
    assert len(set(cinematic_spec.REASON_CODES)) == len(cinematic_spec.REASON_CODES)


def test_the_reason_vocabularies_partition_by_shape() -> None:
    """A beat shot, an unshown entry and a neutral shot never share a reason.

    Every closed sub-vocabulary is drawn from the master list, and no code is
    legal in two shapes -- so a reason on the wrong shape is always a contract
    violation, never an ambiguity.
    """
    beat = set(cinematic_spec.BEAT_SHOT_REASONS)
    unshown = set(cinematic_spec.UNSHOWN_REASONS)
    neutral = {cinematic_spec.REASON_NEUTRAL_ESTABLISHING}
    assert beat | unshown | neutral == set(cinematic_spec.REASON_CODES)
    assert beat & unshown == set()
    assert beat & neutral == set()
    assert unshown & neutral == set()


# ----------------------------------------------------------- classification


def test_a_known_beat_kind_resolves_by_rule() -> None:
    """A known beat kind resolves by rule."""
    anchor, reason = cinematic_spec.anchor_for_beat("LAW_CHANGE")
    assert anchor == "CAM_SEAL_DETAIL"
    assert reason == cinematic_spec.REASON_BEAT_KIND_RULE


def test_both_durable_memory_beats_are_deliberately_unshown() -> None:
    """No approved fixed anchor shows the register; the policy says so plainly.

    Two independent measurements on the full composed world decided this. A
    NEW fact's stone appears only at Phase 20's step-at-window-end, frame
    25 + round(0.95 * 120) = 139 on the canonical clock -- after every derived
    durable shot window -- so framing the empty register would fake the
    response. And a PERSISTED fact's standing stone is wholly occluded from
    CAM_SEAL_DETAIL by the monument's own raised disc: nine of nine sample
    rays from the lens terminate on LD_SEAL__disc, matching Phase 20's
    blind-review record and the reason its proof needed the proof-only
    CAM_P20_RECORD_ARC. V1 creates and promotes no cameras, so both beats are
    honestly unshown; the Story Plan remains authoritative.
    """
    for kind in ("DURABLE_CONSEQUENCE", "CONSEQUENCE_PERSISTED"):
        assert kind not in cinematic_spec.BEAT_ANCHORS, kind
        assert (
            cinematic_spec.UNSHOWN_BEAT_KINDS[kind]
            == cinematic_spec.REASON_NO_FIXED_ANCHOR_WITH_VISUAL_EVIDENCE
        ), kind


def test_an_unknown_beat_kind_degrades_to_the_neutral_anchor() -> None:
    """A future Phase 21 kind gets an honest flat plan, not a guessed viewpoint."""
    anchor, reason = cinematic_spec.anchor_for_beat("FUTURE_UNKNOWN_BEAT")
    assert anchor == cinematic_spec.ESTABLISHING_ANCHOR
    assert reason == cinematic_spec.REASON_UNKNOWN_BEAT_KIND


def test_an_unknown_emphasis_weighs_least() -> None:
    """An unknown emphasis weighs least."""
    assert cinematic_spec.weight_for_emphasis("FUTURE_LEVEL") == 1


def test_the_minimum_shot_is_at_least_a_quarter_second() -> None:
    """A cut the viewer cannot register is flicker, not direction."""
    assert cinematic_spec.MIN_SHOT_FRAMES >= 6
