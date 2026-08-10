"""Contract tests for the Population Presence Spec V1.

Pure pytest -- no Blender. The canonical spec is loaded once and then attacked:
every field is broken in turn and the loader must refuse, because a presence
spec that quietly accepts a contradiction is a spec that will quietly put the
wrong number of people in the world.

The density mapping gets the most attention, because it is the entire truth
claim of Phase 18. A visible body count that does not follow from authoritative
population by a declared rule is a decoration, not evidence.
"""

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "visual" / "blender" / "scripts"
CONFIG_PATH = REPO_ROOT / "visual" / "blender" / "config" / "population_presence_v1.json"


def _load(name: str):
    """Import one pure visual module the same way Blender does: by sibling name."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


pps = _load("population_presence_spec")


@pytest.fixture(name="canonical")
def canonical_fixture() -> dict:
    """The shipped spec document, freshly parsed for each test to mutate."""
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def write(tmp_path: Path, document: dict) -> Path:
    """Write a candidate spec and return its path."""
    target = tmp_path / "presence.json"
    target.write_text(json.dumps(document), encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# The shipped spec
# ---------------------------------------------------------------------------


def test_the_canonical_spec_loads() -> None:
    """The spec this phase ships must satisfy its own contract."""
    spec = pps.load_population_presence_spec(CONFIG_PATH)
    assert spec["format"] == pps.POPULATION_PRESENCE_FORMAT
    assert spec["schema_version"] == pps.POPULATION_PRESENCE_SCHEMA_VERSION


def test_the_canonical_spec_declares_every_zone_and_character() -> None:
    """No approved area type and no district character is left unpolicied."""
    spec = pps.load_population_presence_spec(CONFIG_PATH)
    assert set(spec["zones"]) == set(pps.ZONE_TYPES)
    assert set(spec["distribution"]) == set(pps.DISTRICT_CHARACTERS)
    assert set(spec["figure"]["vocabularies"]) == set(pps.FIGURE_AXES)
    for axis in pps.FIGURE_AXES:
        assert set(spec["figure"]["vocabularies"][axis]) == set(pps.AXIS_VALUES[axis])
    for name in pps.REQUIRED_PRESENCE_CAMERAS:
        assert name in spec["proof"]["cameras"]


def test_the_canonical_pool_can_hold_the_canonical_maximum() -> None:
    """The spec never permits more visible people than it has slots for."""
    spec = pps.load_population_presence_spec(CONFIG_PATH)
    assert spec["slots"]["pool_size"] >= spec["density"]["max_proxies_per_district"]
    assert spec["density"]["global_max_proxies"] >= spec["density"]["max_proxies_per_district"]


# ---------------------------------------------------------------------------
# The density mapping: the truth claim
# ---------------------------------------------------------------------------


def test_zero_population_is_always_zero_proxies() -> None:
    """An empty district shows nobody, whatever the rest of the policy says.

    Including under a spec deliberately built to manufacture people: zero
    residents is zero bodies before any threshold or minimum is consulted.
    """
    spec = pps.load_population_presence_spec(CONFIG_PATH)
    assert pps.visible_proxy_count(0, spec) == 0
    assert pps.unclamped_proxy_count(0, spec) == 0
    hostile = copy.deepcopy(spec)
    hostile["density"]["visibility_threshold"] = 0
    hostile["density"]["min_proxies_per_district"] = 5
    assert pps.visible_proxy_count(0, hostile) == 0
    assert pps.unclamped_proxy_count(0, hostile) == 0


def test_a_zero_threshold_with_a_minimum_is_refused(canonical, tmp_path) -> None:
    """The loader will not accept a policy that could populate an empty district."""
    canonical["density"]["visibility_threshold"] = 0
    canonical["density"]["min_proxies_per_district"] = 1
    with pytest.raises(pps.PopulationPresenceError, match="visibility_threshold"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_population_below_the_threshold_shows_nobody() -> None:
    """The visibility threshold gates the minimum, not the other way round."""
    spec = pps.load_population_presence_spec(CONFIG_PATH)
    threshold = int(spec["density"]["visibility_threshold"])
    assert spec["density"]["min_proxies_per_district"] >= 1, "this test needs a nonzero minimum"
    assert threshold >= 2, (
        "the loop below must iterate; a threshold of 0 or 1 would empty it and this "
        "test would pass without checking anything"
    )
    for population in range(threshold):
        assert pps.visible_proxy_count(population, spec) == 0, (
            f"population {population} produced people out of nothing"
        )
    assert pps.visible_proxy_count(threshold, spec) >= 1


def test_the_mapping_is_monotone_in_population() -> None:
    """More residents never means fewer visible people."""
    spec = pps.load_population_presence_spec(CONFIG_PATH)
    counts = [pps.visible_proxy_count(population, spec) for population in range(0, 900, 7)]
    assert counts == sorted(counts)


def test_the_mapping_never_exceeds_the_declared_maximum() -> None:
    """However large the population, the per-district ceiling holds."""
    spec = pps.load_population_presence_spec(CONFIG_PATH)
    maximum = int(spec["density"]["max_proxies_per_district"])
    for population in (10_000, 1_000_000):
        assert pps.visible_proxy_count(population, spec) == maximum


def test_the_directors_illustrative_mapping_reproduces_exactly(canonical, tmp_path) -> None:
    """One proxy per twenty residents gives 7 for 140 and 16 for 320.

    The scaling ratio is a spec value, not a constant, and this proves it: fed
    the ratio the directive used to illustrate the rule, the shipped code
    reproduces the directive's own numbers exactly.
    """
    canonical["density"]["residents_per_proxy"] = 20.0
    canonical["density"]["visibility_threshold"] = 20
    canonical["density"]["max_proxies_per_district"] = 24
    canonical["slots"]["pool_size"] = 24
    spec = pps.load_population_presence_spec(write(tmp_path, canonical))
    assert pps.visible_proxy_count(140, spec) == 7
    assert pps.visible_proxy_count(320, spec) == 16


def test_a_float_population_is_refused() -> None:
    """A population is a count; a float one means the export was not authoritative."""
    spec = pps.load_population_presence_spec(CONFIG_PATH)
    with pytest.raises(pps.PopulationPresenceError):
        pps.visible_proxy_count(140.0, spec)


def test_a_boolean_population_is_refused() -> None:
    """``True`` is an int in Python and must not be read as a population of one."""
    spec = pps.load_population_presence_spec(CONFIG_PATH)
    with pytest.raises(pps.PopulationPresenceError):
        pps.visible_proxy_count(True, spec)


def test_a_negative_population_is_refused() -> None:
    """The world has no negative districts."""
    spec = pps.load_population_presence_spec(CONFIG_PATH)
    with pytest.raises(pps.PopulationPresenceError):
        pps.visible_proxy_count(-1, spec)


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_wrong_format_is_refused(canonical, tmp_path) -> None:
    """The document must say what it is."""
    canonical["format"] = "living_diorama_something_else"
    with pytest.raises(pps.PopulationPresenceError, match="format"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_a_wrong_schema_version_is_refused(canonical, tmp_path) -> None:
    """A future schema is not silently read as this one."""
    canonical["schema_version"] = 2
    with pytest.raises(pps.PopulationPresenceError, match="schema_version"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_a_boolean_schema_version_is_refused(canonical, tmp_path) -> None:
    """``True == 1`` in Python; the loader must not accept it as version one."""
    canonical["schema_version"] = True
    with pytest.raises(pps.PopulationPresenceError):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_a_blank_visual_seed_is_refused(canonical, tmp_path) -> None:
    """Determinism starts at the seed."""
    canonical["visual_seed"] = "   "
    with pytest.raises(pps.PopulationPresenceError, match="visual_seed"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_a_zero_scaling_ratio_is_refused(canonical, tmp_path) -> None:
    """One proxy per zero residents is not a mapping."""
    canonical["density"]["residents_per_proxy"] = 0.0
    with pytest.raises(pps.PopulationPresenceError, match="residents_per_proxy"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_a_maximum_below_the_minimum_is_refused(canonical, tmp_path) -> None:
    """A range that cannot contain a value is a contradiction, not a policy."""
    canonical["density"]["min_proxies_per_district"] = 10
    canonical["density"]["max_proxies_per_district"] = 4
    with pytest.raises(pps.PopulationPresenceError, match="below"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_a_global_ceiling_below_one_district_is_refused(canonical, tmp_path) -> None:
    """A world ceiling no single district could reach is incoherent."""
    canonical["density"]["global_max_proxies"] = 4
    canonical["density"]["max_proxies_per_district"] = 24
    canonical["slots"]["pool_size"] = 24
    with pytest.raises(pps.PopulationPresenceError, match="global_max_proxies"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_a_pool_smaller_than_the_maximum_is_refused(canonical, tmp_path) -> None:
    """More visible people than stable identities would break slot stability."""
    canonical["slots"]["pool_size"] = 4
    canonical["density"]["max_proxies_per_district"] = 24
    with pytest.raises(pps.PopulationPresenceError, match="pool_size"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_an_unknown_exhaustion_policy_is_refused(canonical, tmp_path) -> None:
    """What happens when the ground runs out must be one of the declared answers."""
    canonical["slots"]["exhaustion_policy"] = "improvise"
    with pytest.raises(pps.PopulationPresenceError, match="exhaustion_policy"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_a_missing_zone_is_refused(canonical, tmp_path) -> None:
    """Every approved area type must be policied, even to zero weight."""
    del canonical["zones"]["park"]
    with pytest.raises(pps.PopulationPresenceError, match="missing"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_an_invented_zone_is_refused(canonical, tmp_path) -> None:
    """A spec cannot introduce an area type the topology cannot supply."""
    canonical["zones"]["rooftop"] = copy.deepcopy(canonical["zones"]["park"])
    with pytest.raises(pps.PopulationPresenceError, match="unknown"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_an_unknown_orientation_rule_is_refused(canonical, tmp_path) -> None:
    """Headings come from geometry, and only from the declared geometries."""
    canonical["zones"]["plaza"]["orientation"] = "face_the_music"
    with pytest.raises(pps.PopulationPresenceError, match="orientation"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_duplicate_zone_offsets_are_refused(canonical, tmp_path) -> None:
    """Two identical lanes would sample the same ground twice."""
    canonical["zones"]["frontage"]["offsets"] = [1.25, 1.25]
    with pytest.raises(pps.PopulationPresenceError, match="distinct"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_park_offsets_outside_the_unit_interval_are_refused(canonical, tmp_path) -> None:
    """Park offsets are radius FRACTIONS, and the contract says so in code."""
    canonical["zones"]["park"]["offsets"] = [0.3, 1.4]
    with pytest.raises(pps.PopulationPresenceError, match="FRACTIONS"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_a_zero_spacing_is_refused(canonical, tmp_path) -> None:
    """Zero spacing would sample one point forever."""
    canonical["zones"]["frontage"]["spacing"] = 0.0
    with pytest.raises(pps.PopulationPresenceError, match="spacing"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_a_separation_below_two_body_radii_is_refused(canonical, tmp_path) -> None:
    """Bodies that may stand closer than their own width would overlap."""
    canonical["proxy"]["radius"] = 0.5
    canonical["proxy"]["separation"] = 0.6
    with pytest.raises(pps.PopulationPresenceError, match="separation"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_an_extreme_heading_jitter_is_refused(canonical, tmp_path) -> None:
    """Jitter that can turn a body away from what its zone faces is not jitter."""
    canonical["proxy"]["heading_jitter"] = 3.0
    with pytest.raises(pps.PopulationPresenceError, match="heading_jitter"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_a_vocabulary_missing_a_value_is_refused(canonical, tmp_path) -> None:
    """Every value the kit can build must be weighted, even to zero."""
    del canonical["figure"]["vocabularies"]["build"]["broad"]
    with pytest.raises(pps.PopulationPresenceError, match="missing"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_an_unknown_palette_is_refused(canonical, tmp_path) -> None:
    """A figure may only wear a colour family the builder actually has."""
    canonical["figure"]["vocabularies"]["palette"]["neon"] = 1.0
    with pytest.raises(pps.PopulationPresenceError, match="unknown value"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_an_unknown_hair_style_is_refused(canonical, tmp_path) -> None:
    """A spec cannot offer a haircut the kit has no geometry for."""
    canonical["figure"]["vocabularies"]["hair"]["mohawk"] = 1.0
    with pytest.raises(pps.PopulationPresenceError, match="unknown value"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_an_age_rule_naming_an_unknown_axis_is_refused(canonical, tmp_path) -> None:
    """Age rules restrict declared axes and nothing else."""
    canonical["figure"]["age_rules"]["child"]["gait"] = ["skip"]
    with pytest.raises(pps.PopulationPresenceError, match="unknown axis"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_an_age_rule_permitting_only_zero_weighted_values_is_refused(canonical, tmp_path) -> None:
    """A rule that leaves an age unbuildable is a contradiction, not a policy."""
    canonical["figure"]["vocabularies"]["clothing"]["formal"] = 0.0
    canonical["figure"]["age_rules"]["child"]["clothing"] = ["formal"]
    with pytest.raises(pps.PopulationPresenceError, match="never be built"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_a_zone_age_bias_for_an_unknown_zone_is_refused(canonical, tmp_path) -> None:
    """Composition may only bias the approved area types."""
    canonical["figure"]["zone_age_bias"]["rooftop"] = {"child": 2.0}
    with pytest.raises(pps.PopulationPresenceError, match="unknown zone"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_zero_diversity_attempts_are_refused(canonical, tmp_path) -> None:
    """A body has to be drawn at least once."""
    canonical["figure"]["diversity"]["attempts"] = 0
    with pytest.raises(pps.PopulationPresenceError, match="attempts"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_a_missing_figure_axis_is_refused(canonical, tmp_path) -> None:
    """Every axis of a visual identity must be policied."""
    del canonical["figure"]["vocabularies"]["hair"]
    with pytest.raises(pps.PopulationPresenceError, match="missing"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_a_character_with_no_permitted_zone_is_refused(canonical, tmp_path) -> None:
    """People must be allowed to be somewhere."""
    canonical["distribution"]["port"] = {
        "frontage": 0.0,
        "plaza": 0.0,
        "park": 0.0,
        "promenade": 0.0,
    }
    with pytest.raises(pps.PopulationPresenceError, match="nowhere"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_a_missing_district_character_is_refused(canonical, tmp_path) -> None:
    """Every character the master scene can declare must have a policy."""
    del canonical["distribution"]["terrace"]
    with pytest.raises(pps.PopulationPresenceError, match="character"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_a_negative_distribution_weight_is_refused(canonical, tmp_path) -> None:
    """A negative preference has no meaning in a proportional interleave."""
    canonical["distribution"]["civic"]["park"] = -1.0
    with pytest.raises(pps.PopulationPresenceError, match="negative"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_an_unknown_pose_is_refused(canonical, tmp_path) -> None:
    """The pose vocabulary is closed; the builder can only build these."""
    canonical["figure"]["vocabularies"]["pose"]["dancing"] = 1.0
    with pytest.raises(pps.PopulationPresenceError, match="unknown value"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_all_zero_pose_weights_are_refused(canonical, tmp_path) -> None:
    """A body has to stand somehow."""
    canonical["figure"]["vocabularies"]["pose"] = dict.fromkeys(pps.POSE_NAMES, 0.0)
    with pytest.raises(pps.PopulationPresenceError, match="zero weight"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_the_canonical_spec_offers_every_archetype_the_kit_can_build(canonical) -> None:
    """No archetype is declared and then weighted out of existence.

    The directive asked for a visible vocabulary of human presentation; a
    value the shipped spec weights at zero is a value the city never contains,
    so every one of them carries real weight.
    """
    spec = pps.load_population_presence_spec(CONFIG_PATH)
    for axis in pps.FIGURE_AXES:
        table = spec["figure"]["vocabularies"][axis]
        unused = sorted(name for name, weight in table.items() if float(weight) <= 0.0)
        assert not unused, f"{axis} declares {unused} and then never builds them"


def test_a_missing_proof_camera_is_refused(canonical, tmp_path) -> None:
    """The proof frames are part of the contract, not an afterthought."""
    del canonical["proof"]["cameras"]["CAM_P18_VALIDITY"]
    with pytest.raises(pps.PopulationPresenceError, match="CAM_P18_VALIDITY"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_a_malformed_camera_vector_is_refused(canonical, tmp_path) -> None:
    """A camera needs three coordinates, not two."""
    canonical["proof"]["cameras"]["CAM_P18_WORLD"]["location"] = [1.0, 2.0]
    with pytest.raises(pps.PopulationPresenceError, match="location"):
        pps.load_population_presence_spec(write(tmp_path, canonical))


def test_an_infinite_number_is_refused(canonical, tmp_path) -> None:
    """Infinity parses as JSON in Python and must not survive validation."""
    target = tmp_path / "presence.json"
    target.write_text(
        json.dumps(canonical).replace('"spacing": 5.6', '"spacing": Infinity'), encoding="utf-8"
    )
    with pytest.raises(pps.PopulationPresenceError, match="finite"):
        pps.load_population_presence_spec(target)


def test_a_non_object_document_is_refused(tmp_path) -> None:
    """A JSON array is not a spec."""
    target = tmp_path / "presence.json"
    target.write_text("[]", encoding="utf-8")
    with pytest.raises(pps.PopulationPresenceError):
        pps.load_population_presence_spec(target)


# ---------------------------------------------------------------------------
# Derived policy
# ---------------------------------------------------------------------------


def test_zone_weights_cover_every_zone_for_every_character() -> None:
    """A character's policy answers for all four area types, present or not."""
    spec = pps.load_population_presence_spec(CONFIG_PATH)
    for character in pps.DISTRICT_CHARACTERS:
        weights = pps.zone_weights(character, spec)
        assert set(weights) == set(pps.ZONE_TYPES)
        assert all(value >= 0.0 for value in weights.values())
        assert any(value > 0.0 for value in weights.values())


def test_zone_weights_refuse_an_unknown_character() -> None:
    """A district character the spec never policied is a refusal."""
    spec = pps.load_population_presence_spec(CONFIG_PATH)
    with pytest.raises(pps.PopulationPresenceError, match="character"):
        pps.zone_weights("submarine", spec)


def test_the_port_policy_sends_people_to_the_water() -> None:
    """The spread policy states an urban intention, and this is one of them."""
    spec = pps.load_population_presence_spec(CONFIG_PATH)
    assert pps.zone_weights("port", spec)["promenade"] > 0.0
    assert pps.zone_weights("residential", spec)["promenade"] == 0.0
