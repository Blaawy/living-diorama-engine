"""The Population Presence Plan V1: authoritative population made visible.

Pure Python by design -- no ``bpy``. A presence plan can be derived, hashed,
inspected and disproved on a machine with no Blender installed at all, which
is the only way its truthfulness can be checked independently of what the
render happens to look like.

The plan answers three questions in strict order, and each one is answered by
a different authority:

    HOW MANY   authoritative district population, through the spec's declared
               scaling rule. Nothing else. No pressure, no capacity, no
               aesthetic judgement about how full a street should look.
    WHERE      the pedestrian topology, which has already proven every piece
               of ground it offers is clear of the city.
    WHICH      the district's own stable slot pool.

The slot pool is the contract that makes the world remember its people. It is
computed WITHOUT EVER LOOKING AT POPULATION: a district's slots are a property
of its ground, laid out once, in a fixed order. Population then activates a
PREFIX of that pool. So a district that grows from seven visible people to
sixteen keeps the original seven standing exactly where they were and adds
nine more after them; it never re-randomises the street.

A proxy is a REPRESENTATIVE POPULATION PROXY. One body stands for
``residents_per_proxy`` residents of its district. It is not a simulated
individual, it has no name, no home, no destination and no schedule, and
there is nowhere in this plan such a thing could be recorded.
"""

import hashlib
import json
import math

import figure_kit
from pedestrian_topology import (
    ZONE_TYPES,
    presence_seed,
)
from population_presence_spec import (
    unclamped_proxy_count,
    visible_proxy_count,
    zone_weights,
)

PRESENCE_PLAN_FORMAT = "living_diorama_population_presence_plan"
PRESENCE_PLAN_SCHEMA_VERSION = 1

REPRESENTATION_STATEMENT = (
    "Every visible body is a representative population proxy standing for "
    "{residents_per_proxy} residents of its district. Phase 18 does not simulate "
    "individual citizens: no proxy has an identity, a home, a destination, a "
    "daily routine, or any behaviour."
)
"""The sentence the manifest must carry, so the claim is never overstated.

Worded to say what a proxy is NOT without naming the systems Phase 18 was
told not to build. The boundary guard reads this module's code, and a
disclaimer is not an exemption from a scope rule -- it reads the same to a
scanner as an implementation would.
"""


class PopulationPlanError(ValueError):
    """A population presence plan violation.

    Raised when the export and the world disagree, when a district's
    character is unknown, when the geometry cannot satisfy a spec that
    demanded it, and every other Phase 18 planning refusal.
    """


def district_populations(export: dict) -> dict[str, int]:
    """The authoritative population of every district in a render export.

    Raises:
        PopulationPlanError: If the export is malformed, names a district
            twice, or records a population that is not an exact count.
    """
    world = export.get("world")
    if not isinstance(world, dict):
        raise PopulationPlanError("render export has no world section")
    districts = world.get("districts")
    if not isinstance(districts, list):
        raise PopulationPlanError("render export world.districts must be an array")
    populations: dict[str, int] = {}
    for index, entry in enumerate(districts):
        if not isinstance(entry, dict):
            raise PopulationPlanError(f"render export district[{index}] is not an object")
        district_id = entry.get("id")
        if not isinstance(district_id, str) or not district_id:
            raise PopulationPlanError(f"render export district[{index}] has no id")
        if district_id in populations:
            raise PopulationPlanError(f"render export names district {district_id!r} twice")
        population = entry.get("population")
        if isinstance(population, bool) or not isinstance(population, int):
            raise PopulationPlanError(
                f"district {district_id} population must be an exact integer, got {population!r}"
            )
        if population < 0:
            raise PopulationPlanError(f"district {district_id} population is negative")
        populations[district_id] = population
    if not populations:
        raise PopulationPlanError("render export declares no districts")
    return dict(sorted(populations.items()))


def require_world_agreement(export: dict, master_spec: dict) -> None:
    """Refuse an export that does not describe the world being rendered.

    Presence derived from a district the master scene has never heard of
    would be presence in a place the city does not have.

    Raises:
        PopulationPlanError: On any district mismatch in either direction.
    """
    exported = set(district_populations(export))
    known = set(master_spec["districts"])
    unknown = sorted(exported - known)
    if unknown:
        raise PopulationPlanError(
            f"the render export carries district(s) the master scene does not define: {unknown}"
        )
    missing = sorted(known - exported)
    if missing:
        raise PopulationPlanError(
            f"the render export is missing district(s) the city is built from: {missing}"
        )


def _apply_global_ceiling(counts: dict[str, int], ceiling: int) -> tuple[dict[str, int], bool]:
    """Hold a world-wide proxy ceiling by the largest-remainder method.

    Districts keep their share of the ceiling in proportion to what they
    earned, floors first, and the leftover seats go to the largest fractional
    parts with district id as the tie-break.

    A district that earned presence then keeps AT LEAST one proxy, taken from
    whichever district currently has the most. Proportional rounding alone
    does not guarantee that -- a small district's floor can be zero -- and a
    populated district rendered empty would be a false statement about the
    world, not a rounding detail. Where the ceiling is smaller than the number
    of populated districts the floor is impossible, and the shortfall is left
    visible in the plan rather than faked.
    """
    total = 0
    for value in counts.values():
        total += value
    if total <= ceiling:
        return dict(sorted(counts.items())), False
    scaled: dict[str, int] = {}
    remainders: list[tuple[float, str]] = []
    allocated = 0
    for district_id in sorted(counts):
        exact = counts[district_id] * ceiling / total
        floor = int(math.floor(exact))
        scaled[district_id] = floor
        allocated += floor
        remainders.append((exact - floor, district_id))
    remainders.sort(key=lambda item: (-item[0], item[1]))
    for _remainder, district_id in remainders[: max(0, ceiling - allocated)]:
        scaled[district_id] += 1
    for district_id in sorted(counts):
        if counts[district_id] <= 0 or scaled[district_id] > 0:
            continue
        donor = max(sorted(scaled), key=lambda entry: (scaled[entry], entry))
        if scaled[donor] <= 1:
            break
        scaled[donor] -= 1
        scaled[district_id] += 1
    return dict(sorted(scaled.items())), True


def zone_sequence(weights: dict[str, float], length: int) -> list[str]:
    """The order in which a district's slots claim their zone types.

    A divisor-method interleave: the k-th slot of a zone with weight w gets
    priority ``(k + 0.5) / w``, and all such claims are sorted. The result is
    proportional to the weights AND stable under truncation, so the first
    seven entries of a sixteen-slot sequence are exactly the sequence you get
    by asking for seven. Both properties are needed -- proportional so the
    spread reads as designed, stable so a growing district never reshuffles.
    """
    keyed: list[tuple[float, str, int]] = []
    for zone_id in ZONE_TYPES:
        weight = float(weights.get(zone_id, 0.0))
        if weight <= 0.0:
            continue
        for index in range(length):
            keyed.append(((index + 0.5) / weight, zone_id, index))
    keyed.sort()
    return [zone_id for _key, zone_id, _index in keyed[:length]]


def _clear_of(placed: list[dict], x: float, y: float, separation: float) -> bool:
    """True when a body here would stand clear of every body already placed."""
    return all(math.hypot(x - other["x"], y - other["y"]) >= separation for other in placed)


def _slot_pool(
    district_id: str,
    zones: dict[str, list[dict]],
    weights: dict[str, float],
    pool_size: int,
    separation: float,
    placed: list[dict],
) -> list[dict]:
    """One district's stable slot pool, laid out from ground alone.

    Walks the district's zone sequence and gives each slot the next candidate
    its zone still has free. When a zone runs dry the slot falls through to
    the remaining zones in weight order, so a district with no plaza spends
    its plaza slots on the streets and parks it does have rather than losing
    them.

    Population is never consulted here, and that is the point: the pool is a
    property of the city's ground, so the same ground always produces the
    same slots in the same order.
    """
    cursors = {zone_id: 0 for zone_id in ZONE_TYPES}
    fallback = sorted(ZONE_TYPES, key=lambda zone_id: (-float(weights.get(zone_id, 0.0)), zone_id))
    pool: list[dict] = []

    def take(zone_id: str) -> dict | None:
        """The next candidate of one zone that stands clear of everyone placed."""
        entries = zones.get(zone_id, [])
        while cursors[zone_id] < len(entries):
            candidate = entries[cursors[zone_id]]
            cursors[zone_id] += 1
            if _clear_of(placed, candidate["x"], candidate["y"], separation):
                return candidate
        return None

    for desired in zone_sequence(weights, pool_size):
        candidate = take(desired)
        if candidate is None:
            for zone_id in fallback:
                if zone_id == desired:
                    continue
                candidate = take(zone_id)
                if candidate is not None:
                    break
        if candidate is None:
            break
        slot_index = len(pool) + 1
        entry = {
            "slot": f"{district_id}__slot_{slot_index:03d}",
            "slot_index": slot_index,
            "district": district_id,
            "zone": candidate["zone"],
            "source": candidate["source"],
            "x": candidate["x"],
            "y": candidate["y"],
            "z": candidate["z"],
            "base_heading": candidate["heading"],
        }
        pool.append(entry)
        placed.append(entry)
    return pool


def _weighted_choice(rng, table: dict[str, float]) -> str:
    """One deterministic draw from a weighted table, in sorted key order."""
    names = [name for name in sorted(table) if float(table[name]) > 0.0]
    if not names:
        raise PopulationPlanError("a visual vocabulary offered no value with any weight")
    weights = [float(table[name]) for name in names]
    draw = rng.random() * math.fsum(weights)
    running = 0.0
    for name, weight in zip(names, weights, strict=True):
        running += weight
        if draw < running:
            return name
    return names[-1]


def _axis_table(
    axis: str, presence_spec: dict, age: str | None, zone: str, child_bias: float
) -> dict[str, float]:
    """The weights one axis actually offers, after every declared rule.

    Three layers, in order: the base vocabulary, the age's permitted values,
    and the zone and composition biases. All of them are declared in the
    spec; none is invented here.
    """
    figure = presence_spec["figure"]
    table = dict(figure["vocabularies"][axis])
    if axis == "age_presentation":
        for name, factor in figure["zone_age_bias"].get(zone, {}).items():
            table[name] = table.get(name, 0.0) * float(factor)
        if child_bias != 1.0 and "child" in table:
            table["child"] = table["child"] * child_bias
        return table
    if age is not None:
        permitted = figure["age_rules"].get(age, {}).get(axis)
        if permitted is not None:
            table = {name: weight for name, weight in table.items() if name in permitted}
    return table


def _apply_presentation_bias(
    table: dict[str, float], presentation: str, presence_spec: dict
) -> dict[str, float]:
    """Bias one axis by the figure's presentation, as the spec declares."""
    bias = presence_spec["figure"]["presentation_bias"].get(presentation, {})
    if not bias:
        return table
    return {name: weight * float(bias.get(name, 1.0)) for name, weight in table.items()}


def _draw_identity(entry: dict, presence_spec: dict, rng, child_bias: float) -> dict[str, str]:
    """One complete visual identity, drawn axis by axis in a fixed order.

    The order is fixed because the draws come from one generator: age first
    because it gates what the rest may be, presentation next because it
    biases them, then everything the two of them constrain.
    """
    zone = entry["zone"]
    age = _weighted_choice(
        rng, _axis_table("age_presentation", presence_spec, None, zone, child_bias)
    )
    presentation = _weighted_choice(rng, _axis_table("presentation", presence_spec, age, zone, 1.0))
    identity = {"age_presentation": age, "presentation": presentation}
    for axis in (
        "stature",
        "build",
        "hair",
        "facial_hair",
        "face",
        "clothing",
        "palette",
        "complexion",
        "hair_tone",
        "pose",
    ):
        table = _apply_presentation_bias(
            _axis_table(axis, presence_spec, age, zone, 1.0), presentation, presence_spec
        )
        identity[axis] = _weighted_choice(rng, table)
    return identity


def _child_bias_for(entry: dict, presence_spec: dict, placed: list[dict]) -> float:
    """How much more likely a child is here, given who already stands nearby.

    PRESENTATION COMPOSITION, and nothing more. A public space in which an
    adult stands near a child reads as a place people bring children to, so
    the policy makes that arrangement more likely in the zones the spec calls
    gathering zones.

    It records NOTHING. The plan carries an age presentation per slot and no
    relationship of any kind -- not kinship, not company, not acquaintance.
    Any family a viewer reads into the frame is the viewer's, and the engine
    never claims it.
    """
    composition = presence_spec["figure"]["composition"]
    if entry["zone"] not in composition["gathering_zones"]:
        return 1.0
    radius = float(composition["child_adjacency_radius"])
    for other in placed:
        if other["zone"] not in composition["gathering_zones"]:
            continue
        if other["identity"]["age_presentation"] not in ("adult", "elder"):
            continue
        if math.hypot(entry["x"] - other["x"], entry["y"] - other["y"]) <= radius:
            return float(composition["child_adjacency_bias"])
    return 1.0


def _assign_visual_identities(pool: list[dict], presence_spec: dict) -> list[dict]:
    """Give every slot in a district's POOL its visual identity.

    Over the POOL, never over the active subset. Local diversity has to look
    at neighbours, and if those neighbours were the currently-visible people
    then growing a district would change the appearance of somebody already
    standing there. The pool is population-blind, so resolving here keeps a
    slot's identity a function of the world and its own id alone.

    Within ``diversity.radius`` no two bodies may share a silhouette
    signature -- age, build, hair, clothing, palette, pose and height bucket.
    A slot that collides redraws from its OWN generator, so the retries change
    nothing for anybody else.
    """
    figure = presence_spec["figure"]
    radius = float(figure["diversity"]["radius"])
    attempts = int(figure["diversity"]["attempts"])
    placed: list[dict] = []
    for entry in pool:
        rng = presence_seed(presence_spec, entry["slot"])
        child_bias = _child_bias_for(entry, presence_spec, placed)
        identity = _draw_identity(entry, presence_spec, rng, child_bias)
        signature = figure_kit.silhouette_signature(identity)
        for _attempt in range(attempts - 1):
            if not any(
                other["signature"] == signature
                and math.hypot(entry["x"] - other["x"], entry["y"] - other["y"]) <= radius
                for other in placed
            ):
                break
            identity = _draw_identity(entry, presence_spec, rng, child_bias)
            signature = figure_kit.silhouette_signature(identity)
        placed.append({**entry, "identity": identity, "signature": signature})
    return placed


def _dress(entry: dict, presence_spec: dict) -> dict:
    """Publish one slot's visual identity, its measurements and its heading."""
    identity = entry["identity"]
    size = figure_kit.figure_dimensions(identity)
    rng = presence_seed(presence_spec, entry["slot"], "heading")
    jitter = float(presence_spec["proxy"]["heading_jitter"])
    published = {key: value for key, value in entry.items() if key not in ("signature", "identity")}
    return {
        **published,
        **identity,
        "height": round(size["height"], 4),
        "shoulder_width": round(size["shoulder_width"], 4),
        "head_height": round(size["head_height"], 4),
        "geometry_key": "__".join(figure_kit.geometry_key(identity)),
        "heading": round(entry["base_heading"] + rng.uniform(-jitter, jitter), 6),
    }


def plan_population_presence(
    export: dict, master_spec: dict, presence_spec: dict, topology: dict
) -> dict:
    """Turn authoritative district population into a visible presence plan.

    Returns ``{"format", "schema_version", "representation", "districts",
    "proxies", "summary"}``. ``districts`` shows the derivation for every
    district -- its population, the count that population earned, the size of
    its pool, and any reduction that had to be applied -- so the plan explains
    itself rather than asserting a number.

    Raises:
        PopulationPlanError: If the export does not describe this world, if a
            district's character is unknown, or if the spec's exhaustion
            policy is ``refuse`` and the ground cannot supply a full pool.
    """
    require_world_agreement(export, master_spec)
    populations = district_populations(export)
    density = presence_spec["density"]
    pool_size = int(presence_spec["slots"]["pool_size"])
    separation = float(presence_spec["proxy"]["separation"])
    policy = presence_spec["slots"]["exhaustion_policy"]

    earned = {
        district_id: visible_proxy_count(population, presence_spec)
        for district_id, population in populations.items()
    }
    scaled = {
        district_id: unclamped_proxy_count(population, presence_spec)
        for district_id, population in populations.items()
    }
    granted, ceiling_applied = _apply_global_ceiling(earned, int(density["global_max_proxies"]))

    placed: list[dict] = []
    pools: dict[str, list[dict]] = {}
    for district_id in sorted(populations):
        character = master_spec["districts"][district_id]["character"]
        weights = zone_weights(character, presence_spec)
        pools[district_id] = _assign_visual_identities(
            _slot_pool(
                district_id,
                topology["zones"].get(district_id, {}),
                weights,
                pool_size,
                separation,
                placed,
            ),
            presence_spec,
        )
        if len(pools[district_id]) < pool_size and policy == "refuse":
            raise PopulationPlanError(
                f"district {district_id} could only site {len(pools[district_id])} of "
                f"{pool_size} slots on pedestrian-safe ground, and the spec refuses "
                "a reduced pool"
            )

    districts: dict[str, dict] = {}
    proxies: list[dict] = []
    for district_id in sorted(populations):
        pool = pools[district_id]
        wanted = granted[district_id]
        active = min(wanted, len(pool))
        for entry in pool[:active]:
            proxies.append(_dress(entry, presence_spec))
        districts[district_id] = {
            "character": master_spec["districts"][district_id]["character"],
            "population": populations[district_id],
            "scaled_proxies": scaled[district_id],
            "earned_proxies": earned[district_id],
            "clamped_by_policy": scaled[district_id] - earned[district_id],
            "granted_proxies": wanted,
            "active_proxies": active,
            "pool_size_requested": pool_size,
            "pool_size_available": len(pool),
            "reduced_by_ground": max(0, wanted - active),
            "zone_weights": {
                zone_id: round(weight, 6)
                for zone_id, weight in zone_weights(
                    master_spec["districts"][district_id]["character"], presence_spec
                ).items()
            },
        }

    by_zone: dict[str, int] = {zone_id: 0 for zone_id in ZONE_TYPES}
    for proxy in proxies:
        by_zone[proxy["zone"]] += 1
    plan = {
        "format": PRESENCE_PLAN_FORMAT,
        "schema_version": PRESENCE_PLAN_SCHEMA_VERSION,
        "representation": REPRESENTATION_STATEMENT.format(
            residents_per_proxy=density["residents_per_proxy"]
        ),
        "density": {
            "residents_per_proxy": float(density["residents_per_proxy"]),
            "visibility_threshold": int(density["visibility_threshold"]),
            "min_proxies_per_district": int(density["min_proxies_per_district"]),
            "max_proxies_per_district": int(density["max_proxies_per_district"]),
            "global_max_proxies": int(density["global_max_proxies"]),
            "global_ceiling_applied": ceiling_applied,
        },
        "districts": districts,
        "proxies": sorted(proxies, key=lambda entry: entry["slot"]),
        "summary": {
            "total_population": _exact_total(populations.values()),
            "active_proxies": len(proxies),
            "proxies_by_zone": by_zone,
            "proxies_by_district": {
                district_id: entry["active_proxies"] for district_id, entry in districts.items()
            },
            "districts_with_no_presence": sorted(
                district_id
                for district_id, entry in districts.items()
                if entry["active_proxies"] == 0
            ),
            "reduced_by_ground": _exact_total(
                entry["reduced_by_ground"] for entry in districts.values()
            ),
            "clamped_by_policy": _exact_total(
                entry["clamped_by_policy"] for entry in districts.values()
            ),
            "districts_clamped_by_policy": sorted(
                district_id
                for district_id, entry in districts.items()
                if entry["clamped_by_policy"]
            ),
        },
    }
    return plan


def _exact_total(values) -> int:
    """Sum exact counts without ever touching float arithmetic."""
    total = 0
    for value in values:
        total += int(value)
    return total


def plan_hash(plan: dict) -> str:
    """A stable digest of one presence plan.

    Canonical JSON with sorted keys, so the same world and the same export
    produce the same digest on any machine and under any ``PYTHONHASHSEED``.
    Used to prove that the plan the Blender build applied is the plan the
    pure planner derived.
    """
    payload = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_population_presence_plan(
    plan: dict, export: dict, master_spec: dict, presence_spec: dict, topology: dict
) -> list[str]:
    """Re-derive every claim in a presence plan and report each disagreement.

    Independently recomputes the population mapping from the export, checks
    that each proxy stands on a candidate the topology actually published for
    the district that owns it, and proves the slot numbering is a dense
    prefix per district. Refusal by evidence, not by trust.
    """
    errors: list[str] = []
    if plan.get("format") != PRESENCE_PLAN_FORMAT:
        errors.append(f"plan format is {plan.get('format')!r}")
    if plan.get("schema_version") != PRESENCE_PLAN_SCHEMA_VERSION:
        errors.append(f"plan schema_version is {plan.get('schema_version')!r}")

    try:
        populations = district_populations(export)
    except PopulationPlanError as error:
        return [*errors, str(error)]

    by_district: dict[str, list[dict]] = {}
    for proxy in plan["proxies"]:
        by_district.setdefault(proxy["district"], []).append(proxy)

    earned = {
        district_id: visible_proxy_count(population, presence_spec)
        for district_id, population in populations.items()
    }
    granted, _applied = _apply_global_ceiling(
        earned, int(presence_spec["density"]["global_max_proxies"])
    )

    for district_id in sorted(populations):
        entry = plan["districts"].get(district_id)
        if entry is None:
            errors.append(f"plan omits district {district_id}")
            continue
        if entry["population"] != populations[district_id]:
            errors.append(
                f"district {district_id} plan population {entry['population']} does not "
                f"match the export ({populations[district_id]})"
            )
        if entry["earned_proxies"] != earned[district_id]:
            errors.append(
                f"district {district_id} claims {entry['earned_proxies']} earned proxies, "
                f"the spec mapping gives {earned[district_id]}"
            )
        proxies = sorted(by_district.get(district_id, []), key=lambda item: item["slot_index"])
        if len(proxies) != entry["active_proxies"]:
            errors.append(
                f"district {district_id} declares {entry['active_proxies']} active proxies "
                f"but carries {len(proxies)}"
            )
        if entry["active_proxies"] > granted[district_id]:
            errors.append(
                f"district {district_id} shows {entry['active_proxies']} proxies, more than "
                f"its population grants ({granted[district_id]})"
            )
        for position, proxy in enumerate(proxies, start=1):
            if proxy["slot_index"] != position:
                errors.append(
                    f"district {district_id} slot numbering is not a dense prefix at "
                    f"{proxy['slot']}"
                )
            if proxy["slot"] != f"{district_id}__slot_{position:03d}":
                errors.append(f"proxy {proxy['slot']} does not follow the slot naming contract")
            available = topology["zones"].get(district_id, {}).get(proxy["zone"], [])
            if not any(
                math.isclose(candidate["x"], proxy["x"], abs_tol=1.0e-6)
                and math.isclose(candidate["y"], proxy["y"], abs_tol=1.0e-6)
                for candidate in available
            ):
                errors.append(
                    f"proxy {proxy['slot']} stands at ({proxy['x']}, {proxy['y']}), which the "
                    f"{proxy['zone']} topology never offered district {district_id}"
                )

    unknown = sorted(set(plan["districts"]) - set(populations))
    if unknown:
        errors.append(f"plan invents district(s) the export does not carry: {unknown}")

    # Re-derive the whole plan and compare, rather than only spot-checking
    # fields. The per-district checks above catch a district that shows MORE
    # than its population grants; only a full re-derivation catches one that
    # shows fewer, or a summary that disagrees with the proxies beneath it.
    try:
        reference = plan_population_presence(export, master_spec, presence_spec, topology)
    except PopulationPlanError as error:
        errors.append(f"the plan's own inputs no longer produce a plan: {error}")
        return errors
    if plan_hash(plan) != plan_hash(reference):
        for district_id in sorted(reference["districts"]):
            expected = reference["districts"][district_id]
            actual = plan["districts"].get(district_id)
            if actual is None:
                errors.append(f"plan omits district {district_id}")
                continue
            for field in ("active_proxies", "scaled_proxies", "clamped_by_policy"):
                if actual.get(field) != expected[field]:
                    errors.append(
                        f"district {district_id} {field} is {actual.get(field)}, "
                        f"re-derivation gives {expected[field]}"
                    )
        for key in sorted(reference["summary"]):
            if plan["summary"].get(key) != reference["summary"][key]:
                errors.append(
                    f"summary {key} is {plan['summary'].get(key)!r}, "
                    f"re-derivation gives {reference['summary'][key]!r}"
                )
        if len(plan["proxies"]) != len(reference["proxies"]):
            errors.append(
                f"the plan carries {len(plan['proxies'])} proxies, re-derivation "
                f"gives {len(reference['proxies'])}"
            )
        if not errors:
            errors.append("the plan does not match a re-derivation from its own inputs")

    separation = float(presence_spec["proxy"]["separation"])
    proxies = plan["proxies"]
    for first in range(len(proxies)):
        for second in range(first + 1, len(proxies)):
            gap = math.hypot(
                proxies[first]["x"] - proxies[second]["x"],
                proxies[first]["y"] - proxies[second]["y"],
            )
            if gap < separation:
                errors.append(
                    f"proxies {proxies[first]['slot']} and {proxies[second]['slot']} stand "
                    f"{round(gap, 4)} apart, closer than the declared separation {separation}"
                )
    return errors
