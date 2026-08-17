"""The Phase 16 fabric-placement contract (pure Python).

The canonical plan must validate with ZERO spatial collisions and be
reproducible bit for bit; every placement policy must DETECT its violation
when a tampered plan is presented: a lot on a founding plate, a lot against
a wall line, a lot in the harbor, colliding lots, and quarters claiming
lots that are not theirs.
"""

import copy
import math


def _first_lot(plan):
    """The first lot of the first quarter that has one."""
    for _neighborhood_id, entry in sorted(plan["neighborhoods"].items()):
        if entry["lots"]:
            return entry["lots"][0]
    raise AssertionError("the canonical plan has no lots at all")


def test_canonical_plan_validates_clean(
    urban_fabric, canonical_plan, master_document, production_document, canonical_graph
):
    """The shipped fabric plan passes every placement rule."""
    errors = urban_fabric.validate_urban_fabric(
        canonical_plan, master_document, production_document, canonical_graph
    )
    assert errors == []


PUBLISHED_NOT_GATED = (
    "audited_objects",
    "rejected_candidates",
    "rejections_by_pair",
    "plinth_pad_laps",
    "worst_plinth_pad_lap",
)
"""The spatial keys that are MEASUREMENTS rather than violations.

Mirrors the exemption list inside ``validate_urban_fabric`` exactly, and has
to keep mirroring it: the first three are bookkeeping, and the last two are a
trade the composition made on purpose. A plinth may lap a junction apron,
because the apron's outer metre is margin rather than carriageway and
refusing the lap was measured to cost an AUTHORED mid-rise block -- deleting
real buildings to buy a slab's last 0.3m under an apron nobody can see is a
bad trade. So the number is published and left visible instead of being
quietly zeroed, and this test admits it as a measurement while still pinning
its value.
"""

PUBLISHED_PAD_LAPS = 2
WORST_PAD_LAP = 0.8839
"""The pad laps the canonical composition actually accepts, and the deepest.

Pinned, because "published rather than gated" must not decay into
"unwatched". A third lap appearing, or the worst one deepening, is a real
change in the trade and has to be argued for rather than absorbed.
"""


def test_spatial_metrics_are_zero(canonical_plan):
    """The plan's own audit reports zero collisions of every class.

    These are the numbers the manifest publishes; they come from re-checking
    the final plan against full occupancy, not from trusting the generator.

    Every published key is gated to zero EXCEPT the handful the validator
    itself exempts, and the gated set is derived from the audit rather than
    listed here. That is the point: a future audit that starts reporting a
    new collision class is gated the moment it exists, instead of being
    silently unwatched until somebody remembers to extend a list. That is
    exactly what happened to the plinth-versus-carriageway guard -- it landed
    reporting zero, and a hardcoded list would never have looked at it.
    """
    spatial = canonical_plan["spatial"]
    gated = sorted(set(spatial) - set(PUBLISHED_NOT_GATED))
    assert gated, "the audit published nothing it is willing to be judged on"
    for key in gated:
        assert spatial[key] == 0, f"{key} = {spatial[key]}"
    assert "plinth_carriageway_collisions" in gated, (
        "the plinth-versus-carriageway guard is no longer being gated"
    )
    assert spatial["audited_objects"] > 0
    assert spatial["rejected_candidates"] > 0, (
        "a plan that never refused anything never tested its rules"
    )


def test_the_published_pad_laps_are_a_measurement_not_a_silence(canonical_plan):
    """The one spatial number the composition accepts above zero, pinned.

    A plinth lapping a junction apron is reported rather than refused, and a
    reported number that nobody checks is the same as no number at all. Both
    the count and the worst depth are frozen here so the accepted trade stays
    the size it was argued for.
    """
    spatial = canonical_plan["spatial"]
    assert spatial["plinth_pad_laps"] == PUBLISHED_PAD_LAPS, (
        f"the composition accepts {spatial['plinth_pad_laps']} pad laps, "
        f"the argued trade was {PUBLISHED_PAD_LAPS}"
    )
    assert abs(spatial["worst_plinth_pad_lap"] - WORST_PAD_LAP) < 1.0e-4, (
        f"the worst pad lap is {spatial['worst_plinth_pad_lap']}, pinned at {WORST_PAD_LAP}"
    )
    assert spatial["worst_plinth_pad_lap"] > 0.0, (
        "a lap of exactly zero would mean the measurement stopped measuring"
    )


def test_plan_is_deterministic(
    urban_fabric, master_document, production_document, canonical_graph, canonical_plan
):
    """Same spec + same seed + same graph produce the identical plan."""
    again = urban_fabric.plan_urban_fabric(master_document, production_document, canonical_graph)
    assert again == canonical_plan


def test_plan_ignores_mapping_insertion_order(
    urban_fabric, road_graph, master_document, production_document, canonical_plan
):
    """Reordering the neighborhoods mapping never changes the plan."""
    reordered = copy.deepcopy(production_document)
    reordered["neighborhoods"] = dict(
        sorted(reordered["neighborhoods"].items(), key=lambda item: item[0], reverse=True)
    )
    graph = road_graph.build_road_graph(master_document, reordered)
    plan = urban_fabric.plan_urban_fabric(master_document, reordered, graph)
    assert plan == canonical_plan


def test_every_quarter_is_present_and_lived_in(
    canonical_plan, production_document, spatial_module_trees
):
    """Each quarter carries structures, parks, or preserved founding groves.

    Some quarters are dense; others are garden quarters whose ground is
    largely the preserved founding forest -- that is §28 made visible, not
    an empty region.
    """
    assert set(canonical_plan["neighborhoods"]) == set(production_document["neighborhoods"])
    for neighborhood_id, entry in canonical_plan["neighborhoods"].items():
        declared = production_document["neighborhoods"][neighborhood_id]
        center = declared["center"]
        radius = declared["radius"]
        founding_inside = sum(
            1
            for tree in spatial_module_trees
            if math.hypot(tree["x"] - center[0], tree["y"] - center[1]) <= radius
        )
        content = (
            len(entry["lots"]) + len(entry["greens"]) + len(entry["yard_rows"]) + founding_inside
        )
        assert content >= 1, f"{neighborhood_id} is an empty quarter"
        assert isinstance(entry["plinth_top"], float)


def test_fabric_carries_real_content(urban_fabric, canonical_plan):
    """The plan holds a real, honest fabric layer with its middle scale."""
    totals = urban_fabric.fabric_totals(canonical_plan)
    assert totals["neighborhoods"] == 8
    assert totals["lots"] >= 12
    assert totals["greens"] >= 8
    assert totals["plazas"] >= 1
    assert totals["production_trees"] >= 25, "the city is deliberately re-landscaped"
    assert totals["street_trees"] >= 10, "the boulevards carry formal tree lines"


def test_the_city_has_a_midrise_shoulder(urban_fabric, canonical_plan):
    """The skyline steps down instead of jumping.

    The final composition's acceptance requirement is a VISIBLE middle
    tier between the founding towers and the low fabric -- and one that
    reads as a shoulder rather than a scatter, so it must appear in more
    than one quarter.
    """
    totals = urban_fabric.fabric_totals(canonical_plan)
    assert totals["midrise_masses"] >= 6, "the middle scale is too weak to read"
    carrying = [
        neighborhood_id
        for neighborhood_id, entry in canonical_plan["neighborhoods"].items()
        if any(
            mass["h"] >= urban_fabric.MIDRISE_THRESHOLD
            for lot in entry["lots"]
            for mass in lot["masses"]
        )
    ]
    assert len(carrying) >= 3, f"the shoulder stands in only {carrying}"


def test_designed_blocks_are_really_built(canonical_plan):
    """The authored street walls exist, and losses are reported honestly.

    A block that does not fit must show up as dropped units rather than
    silently thinning the design; most authored blocks must actually
    stand, or the composition is a drawing rather than a city. The
    reported unit counts are checked against the lots the plan ACTUALLY
    carries, not merely against themselves.
    """
    blocks = canonical_plan["blocks"]
    assert len(blocks) >= 8, "the composition must author real urban blocks"
    lots_by_name = {
        lot["name"]: lot
        for entry in canonical_plan["neighborhoods"].values()
        for lot in entry["lots"]
    }
    for block_id, record in blocks.items():
        assert record["placed"] + record["dropped"] == record["units"], block_id
        lot = lots_by_name.get(f"{record['quarter']}__blk_{block_id}")
        if record["placed"] == 0:
            assert lot is None, f"{block_id} reports nothing placed but a lot exists"
            continue
        assert lot is not None, f"{block_id} reports {record['placed']} placed but has no lot"
        fronts = [mass for mass in lot["masses"] if mass["oy"] == 0.0]
        assert len(fronts) == record["placed"], (
            f"{block_id} reports {record['placed']} units but its lot carries {len(fronts)}"
        )
    fully_placed = [record for record in blocks.values() if record["dropped"] == 0]
    assert len(fully_placed) >= len(blocks) * 0.6, (
        "most authored blocks must stand as drawn; the design does not fit the ground"
    )
    assert sum(record["placed"] for record in blocks.values()) >= 12


def test_no_two_placements_share_an_id(canonical_plan):
    """Every placed object has a unique id.

    The validator exempts a candidate's own id so an entry can be
    re-audited against everything else. That exemption is only safe while
    ids are unique: a second placement under a live id is checked against
    every obstacle EXCEPT its namesake, so two buildings can occupy the
    same ground while the audit reports a clean zero. This test pins the
    invariant that makes the whole spatial contract meaningful.
    """
    names: list[str] = []
    for entry in canonical_plan["neighborhoods"].values():
        names.extend(lot["name"] for lot in entry["lots"])
        names.extend(row["name"] for row in entry["yard_rows"])
        names.extend(green["name"] for green in entry["greens"])
    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert not duplicates, f"placement ids are not unique: {duplicates}"


def test_no_two_buildings_occupy_the_same_ground(urban_fabric, spatial_occupancy, canonical_plan):
    """Independent geometric proof that no two masses interpenetrate.

    Deliberately does NOT use the PlacementValidator: it compares every
    placed footprint against every other directly, so a blind spot in the
    validator cannot make this pass. This is the test that catches an
    overlap the audit's own bookkeeping would hide.
    """
    footprints: list[tuple[str, dict]] = []
    for entry in canonical_plan["neighborhoods"].values():
        for lot in entry["lots"]:
            for index, shape in enumerate(urban_fabric.lot_shapes(lot)):
                footprints.append((f"{lot['name']}#{index}", shape))
    overlaps = []
    for first in range(len(footprints)):
        name_a, shape_a = footprints[first]
        for second in range(first + 1, len(footprints)):
            name_b, shape_b = footprints[second]
            if name_a.split("#")[0] == name_b.split("#")[0]:
                continue
            if spatial_occupancy.shape_gap(shape_a, shape_b) <= 0.0:
                overlaps.append((name_a, name_b))
    assert not overlaps, f"buildings interpenetrate: {overlaps[:5]}"


def test_legacy_clearing_is_deterministic_and_partitioned(
    urban_fabric, canonical_plan, master_document, production_document, canonical_graph
):
    """The clearing decision is a pure function and covers all 40 clusters."""
    again = urban_fabric.plan_legacy_clearing(master_document, production_document, canonical_graph)
    assert again == canonical_plan["legacy"]
    kept = set(canonical_plan["legacy"]["kept"])
    removed = set(canonical_plan["legacy"]["removed"])
    assert kept | removed == set(range(40))
    assert not (kept & removed)
    assert len(kept) >= 6, "the parks preserve a real share of the founding forest"
    for record in canonical_plan["legacy"]["kept"].values():
        assert record["zone"] is not None, "every preserved grove belongs to a park"
        assert record["street_gap"] >= float(production_document["landscape"]["keep_margin"])


def test_resurrecting_a_cleared_cluster_is_detected(
    urban_fabric, canonical_plan, master_document, production_document, canonical_graph
):
    """Hand-editing the clearing decision cannot pass validation."""
    tampered = copy.deepcopy(canonical_plan)
    removed_ids = sorted(tampered["legacy"]["removed"])
    resurrected = removed_ids[0]
    record = tampered["legacy"]["removed"].pop(resurrected)
    tampered["legacy"]["kept"][resurrected] = record
    tampered["legacy"]["removed_objects"] = [
        f"LD_TREE__{index:02d}" for index in sorted(tampered["legacy"]["removed"])
    ]
    errors = urban_fabric.validate_urban_fabric(
        tampered, master_document, production_document, canonical_graph
    )
    assert any("clearing disagrees" in error for error in errors)


def test_lot_footprints_are_concrete(canonical_plan):
    """Every lot carries explicit positive masses -- no surprise geometry."""
    for entry in canonical_plan["neighborhoods"].values():
        for lot in entry["lots"]:
            assert lot["masses"], f"lot {lot['name']} has no masses"
            for mass in lot["masses"]:
                assert mass["w"] > 0 and mass["d"] > 0 and mass["h"] >= 3.4
            assert 0.0 <= lot["lit_salt"] <= 1.0


def test_plinth_shapes_are_positive(urban_fabric, canonical_plan):
    """Every lot's ground plinth hull is well-formed."""
    for entry in canonical_plan["neighborhoods"].values():
        for lot in entry["lots"]:
            shape = urban_fabric.plinth_shape(lot)
            assert shape["hw"] > 0 and shape["hd"] > 0


def test_lot_on_a_founding_plate_is_detected(
    urban_fabric, canonical_plan, master_document, production_document, canonical_graph
):
    """A tampered lot standing on the historic core is named."""
    tampered = copy.deepcopy(canonical_plan)
    lot = _first_lot(tampered)
    lot["x"], lot["y"] = master_document["districts"]["district_a"]["center"]
    errors = urban_fabric.validate_urban_fabric(
        tampered, master_document, production_document, canonical_graph
    )
    assert any("founding_object_violations" in error for error in errors)


def test_lot_in_a_road_is_detected(
    urban_fabric, canonical_plan, master_document, production_document, canonical_graph
):
    """A tampered building inside a carriageway is a hard failure."""
    tampered = copy.deepcopy(canonical_plan)
    lot = _first_lot(tampered)
    loop_path = canonical_graph["segments"]["orbital"]["path"]
    midpoint_index = len(loop_path) // 2
    lot["x"], lot["y"] = loop_path[midpoint_index]
    errors = urban_fabric.validate_urban_fabric(
        tampered, master_document, production_document, canonical_graph
    )
    assert any("building_road_collisions" in error for error in errors)


def test_tree_in_a_road_is_detected(
    urban_fabric, canonical_plan, master_document, production_document, canonical_graph
):
    """A tampered tree cluster inside a carriageway is a hard failure."""
    tampered = copy.deepcopy(canonical_plan)
    for entry in tampered["neighborhoods"].values():
        if entry["greens"]:
            green = entry["greens"][0]
            loop_path = canonical_graph["segments"]["orbital"]["path"]
            green["x"], green["y"] = loop_path[len(loop_path) // 2]
            break
    errors = urban_fabric.validate_urban_fabric(
        tampered, master_document, production_document, canonical_graph
    )
    assert any("tree_road_collisions" in error for error in errors)


def test_tree_in_a_building_is_detected(
    urban_fabric, canonical_plan, master_document, production_document, canonical_graph
):
    """A tampered tree inside a building envelope is a hard failure."""
    tampered = copy.deepcopy(canonical_plan)
    lot = _first_lot(tampered)
    for entry in tampered["neighborhoods"].values():
        if entry["greens"]:
            green = entry["greens"][0]
            green["x"], green["y"] = lot["x"], lot["y"]
            break
    errors = urban_fabric.validate_urban_fabric(
        tampered, master_document, production_document, canonical_graph
    )
    assert any("tree_building_collisions" in error for error in errors)


def test_lot_against_a_wall_line_is_detected(
    urban_fabric, canonical_plan, master_document, production_document, canonical_graph
):
    """A tampered lot crowding a wall station is named."""
    tampered = copy.deepcopy(canonical_plan)
    lot = _first_lot(tampered)
    station = master_document["boundaries"]["boundary_ab"]["wall_station"]
    lot["x"], lot["y"] = station["center"]
    errors = urban_fabric.validate_urban_fabric(
        tampered, master_document, production_document, canonical_graph
    )
    assert any("wall_clearance_violations" in error or "wall station" in error for error in errors)


def test_lot_in_the_harbor_is_detected(
    urban_fabric, canonical_plan, master_document, production_document, canonical_graph
):
    """A tampered lot in the water is named."""
    tampered = copy.deepcopy(canonical_plan)
    lot = _first_lot(tampered)
    port = next(
        entry for entry in master_document["districts"].values() if entry["character"] == "port"
    )
    center_x, center_y = port["center"]
    length = math.hypot(center_x, center_y)
    reach = length + port["radius"] + 16.0
    lot["x"] = center_x / length * reach
    lot["y"] = center_y / length * reach
    errors = urban_fabric.validate_urban_fabric(
        tampered, master_document, production_document, canonical_graph
    )
    assert any("water_violations" in error or "harbor approach" in error for error in errors)


def test_colliding_lots_are_detected(
    urban_fabric, canonical_plan, master_document, production_document, canonical_graph
):
    """Two independent lots on the same ground are named."""
    tampered = copy.deepcopy(canonical_plan)
    for entry in tampered["neighborhoods"].values():
        if entry["lots"]:
            duplicate = copy.deepcopy(entry["lots"][0])
            duplicate["name"] = duplicate["name"] + "_twin"
            duplicate["x"] += 0.4
            entry["lots"].append(duplicate)
            break
    errors = urban_fabric.validate_urban_fabric(
        tampered, master_document, production_document, canonical_graph
    )
    assert any("building_building_overlaps" in error for error in errors)


def test_foreign_ownership_is_detected(
    urban_fabric, canonical_plan, master_document, production_document, canonical_graph
):
    """A lot far from its owning quarter's field of influence is named."""
    tampered = copy.deepcopy(canonical_plan)
    lot = _first_lot(tampered)
    lot["x"], lot["y"] = 0.0, -50.0
    errors = urban_fabric.validate_urban_fabric(
        tampered, master_document, production_document, canonical_graph
    )
    assert errors, "a teleported lot must violate at least one rule"


FOUNDING_BLOCKED = (
    "LD_BLDG__district_a__000",
    "LD_BLDG__district_a__001",
    "LD_BLDG__district_a__002",
    "LD_BLDG__district_c__000",
    "LD_BLDG__district_c__001",
)
"""The founding buildings that stand in legal carriageway space and keep it.

The residual of the road-encroachment remediation, accepted as a permanent
compatibility exception. FOUR of the five are irreducible: an exhaustive
census of each one's own plate found no legal alternative position within
the authorized correction envelope. The fifth, ``LD_BLDG__district_a__002``,
DID have a legal relocation -- found off the placement ladder during the
exhaustive investigation, and reachable only by extending that ladder's
radial span and giving it a rotation axis it does not have. It would have
left roughly 15 mm of clearance on a collector, so the Director declined
it: a fragile special case for no visible benefit. It is therefore retained
as the fifth accepted residual, not as an unsolved one.

Either way the city keeps the building and the road layer stops drawing
through it.

Pinned by NAME rather than by count, because the count alone cannot tell a
building that was freed from a different one that became blocked. The module
publishing this says the point outright -- a residual nobody counts is a
residual that grows -- and until now nothing counted it.
"""


def test_the_founding_blocked_residual_is_pinned(canonical_plan):
    """The five buildings that keep their founding ground, named and counted.

    A sixth appearing means the composition has pushed more architecture
    into carriageway space; one disappearing means a building was freed and
    the trim that avoids it is now dead weight. Either is a real change and
    has to be argued for rather than absorbed.
    """
    blocked = tuple(sorted(canonical_plan["founding_blocked"]))
    assert blocked == FOUNDING_BLOCKED, (
        f"the blocked residual is {list(blocked)}, pinned at {list(FOUNDING_BLOCKED)}"
    )
    assert canonical_plan["summary"]["founding_blocked_buildings"] == len(FOUNDING_BLOCKED), (
        "the summary count disagrees with the published set"
    )
