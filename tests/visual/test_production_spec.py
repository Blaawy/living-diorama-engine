"""Production World Spec V1 contract (pure Python).

The spec may only EXTEND the founding world: every reference must resolve
to an authoritative district, geometry may never contradict the founding
plates or the harbor, and the neighborhood count stays in the production
band. Every rule here is a refusal, proven by tampering with a copy of the
canonical document.
"""

import copy
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = REPO_ROOT / "visual" / "blender" / "config" / "production_world_v1.json"


def test_canonical_spec_loads_and_agrees(production_spec, master_document, production_document):
    """The shipped config is valid and agrees with the master scene."""
    production_spec.require_production_agreement(master_document, production_document)
    assert production_document["format"] == "living_diorama_blender_production_world"
    assert production_document["schema_version"] == 3


def test_config_is_plain_utf8_json_without_bom():
    """The candidate config honors the locked manifest-encoding contract."""
    data = CONFIG.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf"), "production config carries a UTF-8 BOM"
    json.loads(data.decode("utf-8"))


def test_wrong_format_is_refused(production_spec, tmp_path):
    """A document claiming another format never loads."""
    document = json.loads(CONFIG.read_text(encoding="utf-8"))
    document["format"] = "living_diorama_blender_master_scene"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(production_spec.ProductionContractError, match="format"):
        production_spec.load_production_world_spec(path)


def test_wrong_schema_version_is_refused(production_spec, tmp_path):
    """Another schema version is refused, never guessed at."""
    document = json.loads(CONFIG.read_text(encoding="utf-8"))
    document["schema_version"] = 2
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(production_spec.ProductionContractError, match="schema_version"):
        production_spec.load_production_world_spec(path)


def test_unknown_profile_is_refused(production_spec, tmp_path):
    """A quarter profile outside the fixed vocabulary is refused."""
    document = json.loads(CONFIG.read_text(encoding="utf-8"))
    first = next(iter(document["neighborhoods"].values()))
    first["profile"] = "arcology"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(production_spec.ProductionContractError, match="profile"):
        production_spec.load_production_world_spec(path)


def test_street_missing_class_is_refused(production_spec, tmp_path):
    """Every designed street declares its hierarchy class."""
    document = json.loads(CONFIG.read_text(encoding="utf-8"))
    document["streets"]["orbital"]["class"] = "boulevard"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(production_spec.ProductionContractError, match="class"):
        production_spec.load_production_world_spec(path)


def test_street_end_must_be_single_purpose(production_spec, tmp_path):
    """A street end declares exactly one of landing / avenue / termination."""
    document = json.loads(CONFIG.read_text(encoding="utf-8"))
    document["streets"]["gate_port_north"]["end_b"] = {
        "lands_on": "district_b",
        "termination": "cul_de_sac",
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(production_spec.ProductionContractError, match="exactly one"):
        production_spec.load_production_world_spec(path)


def test_orbital_must_stay_a_smooth_curve(production_spec, tmp_path):
    """The orbital boulevard is a sampled curve, not a coarse polygon."""
    document = json.loads(CONFIG.read_text(encoding="utf-8"))
    document["streets"]["orbital"]["path"] = document["streets"]["orbital"]["path"][:8]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(production_spec.ProductionContractError, match="smooth"):
        production_spec.load_production_world_spec(path)


def test_front_run_shape_is_validated(production_spec, tmp_path):
    """Designed street-wall runs carry side, range, kind, and count."""
    document = json.loads(CONFIG.read_text(encoding="utf-8"))
    document["streets"]["orbital"]["front_runs"] = [{"side": "north"}]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(production_spec.ProductionContractError, match="side"):
        production_spec.load_production_world_spec(path)


def test_park_zones_are_required(production_spec, tmp_path):
    """The landscape plan must declare where the city preserves groves."""
    document = json.loads(CONFIG.read_text(encoding="utf-8"))
    document["landscape"]["park_zones"] = {}
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(production_spec.ProductionContractError, match="park zones"):
        production_spec.load_production_world_spec(path)


def test_keep_margin_must_cover_road_clearance(production_spec, tmp_path):
    """A keep margin below the vegetation road clearance is refused."""
    document = json.loads(CONFIG.read_text(encoding="utf-8"))
    document["landscape"]["keep_margin"] = 0.1
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(production_spec.ProductionContractError, match="keep_margin"):
        production_spec.load_production_world_spec(path)


def test_yard_street_must_exist(production_spec, master_document, production_document):
    """A quarter's yard lane must be a declared street."""
    tampered = copy.deepcopy(production_document)
    tampered["neighborhoods"]["harborworks"]["yard_street"] = "ghost_lane"
    with pytest.raises(production_spec.ProductionContractError, match="ghost_lane"):
        production_spec.require_production_agreement(master_document, tampered)


def test_unknown_district_reference_is_refused(
    production_spec, master_document, production_document
):
    """Visual neighborhoods must nest inside authoritative districts.

    A neighborhood claiming a district the simulation does not know would
    invent simulation semantics; it is refused by name.
    """
    tampered = copy.deepcopy(production_document)
    first = next(iter(tampered["neighborhoods"].values()))
    first["district"] = "district_x"
    with pytest.raises(production_spec.ProductionContractError, match="district_x"):
        production_spec.require_production_agreement(master_document, tampered)


def test_invented_district_expansion_is_refused(
    production_spec, master_document, production_document
):
    """An expansion entry for a nonexistent district is refused."""
    tampered = copy.deepcopy(production_document)
    tampered["districts"]["district_new"] = {"expansion_radius": 30.0}
    with pytest.raises(production_spec.ProductionContractError, match="district_new"):
        production_spec.require_production_agreement(master_document, tampered)


def test_missing_district_expansion_is_refused(
    production_spec, master_document, production_document
):
    """Every authoritative district must declare its presentation territory."""
    tampered = copy.deepcopy(production_document)
    del tampered["districts"]["district_a"]
    with pytest.raises(production_spec.ProductionContractError, match="district_a"):
        production_spec.require_production_agreement(master_document, tampered)


def test_neighborhood_on_a_founding_plate_is_refused(
    production_spec, master_document, production_document
):
    """The historic core is never built over."""
    tampered = copy.deepcopy(production_document)
    first = next(iter(tampered["neighborhoods"].values()))
    first["center"] = list(master_document["districts"]["district_a"]["center"])
    with pytest.raises(production_spec.ProductionContractError, match="founding plate"):
        production_spec.require_production_agreement(master_document, tampered)


def test_overlapping_neighborhoods_are_refused(
    production_spec, master_document, production_document
):
    """Two quarters may not claim the same ground."""
    tampered = copy.deepcopy(production_document)
    ids = sorted(tampered["neighborhoods"])
    tampered["neighborhoods"][ids[1]]["center"] = list(tampered["neighborhoods"][ids[0]]["center"])
    with pytest.raises(production_spec.ProductionContractError, match="overlap"):
        production_spec.require_production_agreement(master_document, tampered)


def test_neighborhood_in_the_harbor_is_refused(
    production_spec, master_document, production_document
):
    """Fabric never stands in the water."""
    tampered = copy.deepcopy(production_document)
    port = next(
        entry for entry in master_document["districts"].values() if entry["character"] == "port"
    )
    center_x, center_y = port["center"]
    length = (center_x**2 + center_y**2) ** 0.5
    reach = length + port["radius"] + 12.0
    first_id = sorted(tampered["neighborhoods"])[0]
    tampered["neighborhoods"][first_id]["center"] = [
        center_x / length * reach,
        center_y / length * reach,
    ]
    tampered["neighborhoods"][first_id]["district"] = "district_b"
    with pytest.raises(production_spec.ProductionContractError, match="harbor"):
        production_spec.require_production_agreement(master_document, tampered)


def test_neighborhood_count_band_is_enforced(production_spec, master_document, production_document):
    """The world targets 8-12 recognizable quarters; outside is refused."""
    too_few = copy.deepcopy(production_document)
    first_id = sorted(too_few["neighborhoods"])[0]
    del too_few["neighborhoods"][first_id]
    with pytest.raises(production_spec.ProductionContractError, match="8-12"):
        production_spec.require_production_agreement(master_document, too_few)


def test_shrinking_expansion_is_refused(production_spec, master_document, production_document):
    """Territory only grows: an expansion below the plate is refused."""
    tampered = copy.deepcopy(production_document)
    tampered["districts"]["district_a"]["expansion_radius"] = 5.0
    with pytest.raises(production_spec.ProductionContractError, match="shrink"):
        production_spec.require_production_agreement(master_document, tampered)


def test_port_frame_matches_the_founding_harbor(production_spec, master_document):
    """The quay line sits exactly where the Phase 15 harbor builder put it."""
    (port_x, port_y), (unit_x, unit_y), quay = production_spec.port_frame(master_document)
    port = next(
        entry for entry in master_document["districts"].values() if entry["character"] == "port"
    )
    assert (port_x, port_y) == tuple(port["center"])
    assert quay == port["radius"] + 10.0
    assert abs(unit_x**2 + unit_y**2 - 1.0) < 1.0e-9
    on_axis = production_spec.coast_coordinate(
        (port_x + unit_x * 7.0, port_y + unit_y * 7.0), master_document
    )
    assert abs(on_axis - 7.0) < 1.0e-9
