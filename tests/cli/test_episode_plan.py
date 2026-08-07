"""Phase 13 run-plan parsing: strict JSON in, frozen validated plan out.

Every rejection here is a rejection, never a repair: a malformed plan must
fail loudly before anything is loaded or simulated, and a plan that parsed
must be impossible to alter afterwards.
"""

import dataclasses
import json
from types import MappingProxyType

import pytest

from cli.conftest import (
    MOVEMENT_LAW_ID,
    change_plan_document,
    plan_bytes,
    restore_plan_document,
)
from living_diorama.cli.episode_plan import (
    EpisodePlan,
    SystemsConfiguration,
    parse_episode_plan,
)
from living_diorama.entities import ResourceType
from living_diorama.systems import ScheduledLawChange, ScheduledLawRestore


def parsed_change_plan() -> EpisodePlan:
    """Parse the canonical valid change plan."""
    return parse_episode_plan(plan_bytes(change_plan_document()))


def valid_systems_configuration() -> SystemsConfiguration:
    """Build a valid configuration directly, without going through JSON.

    Values mirror :func:`cli.conftest.systems_section`: pairwise distinct so
    a cross-wired parameter cannot hide behind an equal neighbor.
    """
    return SystemsConfiguration(
        production_allocation={
            ResourceType.FOOD: 0.6,
            ResourceType.MATERIALS: 0.3,
            ResourceType.ENERGY: 0.1,
        },
        consumption_allocation={
            ResourceType.FOOD: 0.5,
            ResourceType.MATERIALS: 0.3,
            ResourceType.ENERGY: 0.2,
        },
        movement_law_id=MOVEMENT_LAW_ID,
        reserve_ticks=1.5,
        migration_rate=0.2,
        min_pressure_gap=0.05,
        partial_isolation_factor=0.45,
        social_scarcity_weight=1.1,
        housing_pressure_weight=0.9,
        social_response_rate=0.25,
        institutional_scarcity_weight=1.2,
        fear_weight=0.8,
        distrust_weight=0.7,
        institutional_response_rate=0.15,
        build_threshold=0.95,
        adaptation_rate=0.1,
    )


class TestValidPlans:
    """Well-formed plans parse into exactly what they said."""

    def test_valid_change_plan_parses(self) -> None:
        """A change plan yields a frozen plan carrying one derived change."""
        plan = parsed_change_plan()
        assert plan.parent_episode == 0
        assert plan.ticks == 6
        assert plan.child_episode == 1
        assert type(plan.action) is ScheduledLawChange
        assert plan.action.episode == 1
        assert plan.action.tick == 7
        assert plan.action.law_id == MOVEMENT_LAW_ID
        assert plan.action.new_value is False
        assert plan.action.active is False

    def test_valid_restore_plan_parses(self) -> None:
        """A restore plan yields a frozen plan carrying one derived restore."""
        plan = parse_episode_plan(plan_bytes(restore_plan_document()))
        assert plan.parent_episode == 0
        assert plan.child_episode == 1
        assert type(plan.action) is ScheduledLawRestore
        assert plan.action.episode == 1
        assert plan.action.tick == 11
        assert plan.action.law_id == MOVEMENT_LAW_ID

    def test_systems_section_is_captured_exactly(self) -> None:
        """Every configured value survives parsing with its exact identity."""
        systems = parsed_change_plan().systems
        assert systems.production_allocation == {
            ResourceType.FOOD: 0.6,
            ResourceType.MATERIALS: 0.3,
            ResourceType.ENERGY: 0.1,
        }
        assert systems.consumption_allocation == {
            ResourceType.FOOD: 0.5,
            ResourceType.MATERIALS: 0.3,
            ResourceType.ENERGY: 0.2,
        }
        assert systems.movement_law_id == MOVEMENT_LAW_ID
        assert systems.reserve_ticks == 1.5
        assert systems.migration_rate == 0.2
        assert systems.min_pressure_gap == 0.05
        assert systems.partial_isolation_factor == 0.45
        assert systems.social_scarcity_weight == 1.1
        assert systems.housing_pressure_weight == 0.9
        assert systems.social_response_rate == 0.25
        assert systems.institutional_scarcity_weight == 1.2
        assert systems.fear_weight == 0.8
        assert systems.distrust_weight == 0.7
        assert systems.institutional_response_rate == 0.15
        assert systems.build_threshold == 0.95
        assert systems.adaptation_rate == 0.1

    def test_integer_settings_keep_their_exact_type(self) -> None:
        """A JSON integer setting stays an int; nothing converts it early."""
        document = change_plan_document()
        document["systems"]["resource_flow"]["reserve_ticks"] = 2
        systems = parse_episode_plan(plan_bytes(document)).systems
        assert type(systems.reserve_ticks) is int
        assert systems.reserve_ticks == 2


class TestTopLevelContract:
    """The plan's top level carries exactly its four keys, exactly typed."""

    def test_parent_episode_bool_is_rejected(self) -> None:
        """``True`` is not episode 1; bool is refused outright."""
        document = change_plan_document()
        document["parent_episode"] = True
        with pytest.raises(TypeError, match="parent_episode must be an int, got bool"):
            parse_episode_plan(plan_bytes(document))

    def test_negative_parent_episode_is_rejected(self) -> None:
        """Episode numbers start at zero."""
        document = change_plan_document()
        document["parent_episode"] = -1
        with pytest.raises(ValueError, match="parent_episode must be >= 0"):
            parse_episode_plan(plan_bytes(document))

    def test_ticks_bool_is_rejected(self) -> None:
        """``True`` is not one tick; bool is refused outright."""
        document = change_plan_document()
        document["ticks"] = True
        with pytest.raises(TypeError, match="ticks must be an int, got bool"):
            parse_episode_plan(plan_bytes(document))

    def test_zero_ticks_is_rejected(self) -> None:
        """A continuation must run: zero ticks could not hold an intervention."""
        document = change_plan_document()
        document["ticks"] = 0
        with pytest.raises(ValueError, match="ticks must be > 0"):
            parse_episode_plan(plan_bytes(document))

    def test_negative_ticks_is_rejected(self) -> None:
        """Time does not run backwards."""
        document = change_plan_document()
        document["ticks"] = -3
        with pytest.raises(ValueError, match="ticks must be >= 0"):
            parse_episode_plan(plan_bytes(document))

    def test_unknown_top_level_key_is_rejected(self) -> None:
        """An unknown key means the plan was written for something else."""
        document = change_plan_document()
        document["seed"] = 42
        with pytest.raises(ValueError, match=r"unexpected keys: \['seed'\]"):
            parse_episode_plan(plan_bytes(document))

    def test_missing_top_level_key_is_rejected(self) -> None:
        """Every semantic section is required; nothing is defaulted."""
        document = change_plan_document()
        del document["systems"]
        with pytest.raises(ValueError, match=r"missing required keys: \['systems'\]"):
            parse_episode_plan(plan_bytes(document))

    def test_top_level_must_be_an_object(self) -> None:
        """A plan is a JSON object, not an array or scalar."""
        with pytest.raises(TypeError, match="episode plan must be a JSON object"):
            parse_episode_plan(b"[1, 2, 3]")


class TestJsonHardening:
    """The byte layer refuses what strict JSON refuses, and more."""

    def test_duplicate_json_key_is_rejected(self) -> None:
        """A repeated key would silently drop data; it is refused instead."""
        with pytest.raises(ValueError, match="duplicate JSON object key 'parent_episode'"):
            parse_episode_plan(b'{"parent_episode": 0, "parent_episode": 1}')

    def test_duplicate_nested_json_key_is_rejected(self) -> None:
        """Duplicate keys are refused at every depth, not just the top."""
        text = json.dumps(change_plan_document())
        corrupted = text.replace('"kind": "change"', '"kind": "change", "kind": "change"', 1)
        with pytest.raises(ValueError, match="duplicate JSON object key 'kind'"):
            parse_episode_plan(corrupted.encode("utf-8"))

    def test_malformed_json_is_rejected(self) -> None:
        """Broken syntax is refused, never guessed at."""
        with pytest.raises(ValueError, match="episode plan is not valid JSON"):
            parse_episode_plan(b'{"parent_episode": ')

    def test_nan_is_rejected(self) -> None:
        """``NaN`` is not standard JSON and can never be a setting."""
        with pytest.raises(ValueError, match="non-standard JSON constant 'NaN'"):
            parse_episode_plan(b'{"parent_episode": NaN}')

    def test_infinity_is_rejected(self) -> None:
        """``Infinity`` is not standard JSON and can never be a setting."""
        with pytest.raises(ValueError, match="non-standard JSON constant 'Infinity'"):
            parse_episode_plan(b'{"ticks": Infinity}')

    def test_negative_infinity_is_rejected(self) -> None:
        """``-Infinity`` is not standard JSON and can never be a setting."""
        with pytest.raises(ValueError, match="non-standard JSON constant '-Infinity'"):
            parse_episode_plan(b'{"ticks": -Infinity}')

    def test_overflowing_literal_is_rejected(self) -> None:
        """A literal that parses to infinity is refused like infinity itself."""
        text = json.dumps(change_plan_document()).replace(
            '"reserve_ticks": 1.5', '"reserve_ticks": 1e999'
        )
        with pytest.raises(ValueError, match="must be a finite number"):
            parse_episode_plan(text.encode("utf-8"))

    def test_non_bytes_input_is_rejected(self) -> None:
        """The parser takes the file's exact bytes, nothing else."""
        with pytest.raises(TypeError, match="episode plan must be bytes"):
            parse_episode_plan(json.dumps(change_plan_document()))  # type: ignore[arg-type]


class TestInterventionContract:
    """Exactly one intervention, exactly shaped, episode always derived."""

    def test_unknown_intervention_kind_is_rejected(self) -> None:
        """Only change and restore exist."""
        document = change_plan_document()
        document["intervention"]["kind"] = "decree"
        with pytest.raises(ValueError, match="intervention kind must be 'change' or 'restore'"):
            parse_episode_plan(plan_bytes(document))

    def test_non_string_intervention_kind_is_rejected(self) -> None:
        """A kind that is not a string is a type error, not a guess."""
        document = change_plan_document()
        document["intervention"]["kind"] = True
        with pytest.raises(TypeError, match="intervention kind must be a str, got bool"):
            parse_episode_plan(plan_bytes(document))

    def test_missing_intervention_kind_is_rejected(self) -> None:
        """An intervention must say what it is."""
        document = change_plan_document()
        del document["intervention"]["kind"]
        with pytest.raises(TypeError, match="intervention kind must be a str, got NoneType"):
            parse_episode_plan(plan_bytes(document))

    def test_change_missing_required_field_is_rejected(self) -> None:
        """A change without its active flag is incomplete, not defaulted."""
        document = change_plan_document()
        del document["intervention"]["active"]
        with pytest.raises(ValueError, match=r"missing required keys: \['active'\]"):
            parse_episode_plan(plan_bytes(document))

    def test_restore_carrying_change_fields_is_rejected(self) -> None:
        """A restore never carries a new value; the law's own history rules."""
        document = restore_plan_document()
        document["intervention"]["new_value"] = 5
        document["intervention"]["active"] = True
        with pytest.raises(ValueError, match=r"unexpected keys: \['active', 'new_value'\]"):
            parse_episode_plan(plan_bytes(document))

    def test_intervention_episode_field_is_rejected(self) -> None:
        """The episode is always derived; a plan may not choose it."""
        document = change_plan_document()
        document["intervention"]["episode"] = 1
        with pytest.raises(ValueError, match="must not carry an 'episode' field"):
            parse_episode_plan(plan_bytes(document))

    def test_surrounding_whitespace_law_id_is_rejected(self) -> None:
        """A padded identifier targets a different law; it is refused as found."""
        document = change_plan_document(law_id=" law_movement_sharing ")
        with pytest.raises(ValueError, match="must not carry surrounding whitespace"):
            parse_episode_plan(plan_bytes(document))

    def test_blank_law_id_is_rejected(self) -> None:
        """A whitespace-only identifier names nothing."""
        document = change_plan_document(law_id="   ")
        with pytest.raises(ValueError, match="must not be only whitespace"):
            parse_episode_plan(plan_bytes(document))

    def test_empty_law_id_is_rejected(self) -> None:
        """An empty identifier names nothing."""
        document = restore_plan_document(law_id="")
        with pytest.raises(ValueError, match="must not be empty"):
            parse_episode_plan(plan_bytes(document))

    def test_intervention_tick_bool_is_rejected(self) -> None:
        """``True`` is not tick 1; bool is refused outright."""
        document = change_plan_document()
        document["intervention"]["tick"] = True
        with pytest.raises(TypeError, match="tick must be an int, got bool"):
            parse_episode_plan(plan_bytes(document))

    def test_change_active_int_is_rejected(self) -> None:
        """``1`` is not ``True``; the active flag must be exactly bool."""
        document = change_plan_document()
        document["intervention"]["active"] = 1
        with pytest.raises(TypeError, match="active must be a bool, got int"):
            parse_episode_plan(plan_bytes(document))

    def test_change_new_value_container_is_rejected(self) -> None:
        """A law's value is a scalar; containers are refused."""
        document = change_plan_document()
        document["intervention"]["new_value"] = {"value": 1}
        with pytest.raises(TypeError, match="new_value must be null, a bool"):
            parse_episode_plan(plan_bytes(document))

    def test_change_new_value_null_is_accepted(self) -> None:
        """``null`` is a legitimate law value and survives exactly."""
        document = change_plan_document(new_value=None, active=True)
        plan = parse_episode_plan(plan_bytes(document))
        assert type(plan.action) is ScheduledLawChange
        assert plan.action.new_value is None


class TestSystemsContract:
    """The systems section is explicit, exact, and complete."""

    def test_invalid_resource_name_is_rejected(self) -> None:
        """An unknown resource name is refused, never skipped."""
        document = change_plan_document()
        allocation = document["systems"]["production_allocation"]
        allocation["GOLD"] = allocation.pop("ENERGY")
        with pytest.raises(
            ValueError, match=r"production_allocation names unknown resources: \['GOLD'\]"
        ):
            parse_episode_plan(plan_bytes(document))

    def test_allocation_missing_a_resource_is_rejected(self) -> None:
        """Every current resource must be allocated explicitly."""
        document = change_plan_document()
        del document["systems"]["consumption_allocation"]["ENERGY"]
        with pytest.raises(
            ValueError, match=r"consumption_allocation is missing resources: \['ENERGY'\]"
        ):
            parse_episode_plan(plan_bytes(document))

    def test_allocation_extra_key_is_rejected(self) -> None:
        """A fourth resource name means the plan disagrees with the engine."""
        document = change_plan_document()
        document["systems"]["consumption_allocation"]["WATER"] = 0.0
        with pytest.raises(
            ValueError, match=r"consumption_allocation names unknown resources: \['WATER'\]"
        ):
            parse_episode_plan(plan_bytes(document))

    def test_allocation_bool_weight_is_rejected(self) -> None:
        """``true`` is not a weight of 1."""
        document = change_plan_document()
        document["systems"]["production_allocation"]["FOOD"] = True
        with pytest.raises(
            TypeError, match=r"production_allocation\[FOOD\] must be a real number, got bool"
        ):
            parse_episode_plan(plan_bytes(document))

    def test_unknown_systems_key_is_rejected(self) -> None:
        """A system this engine does not run cannot be configured."""
        document = change_plan_document()
        document["systems"]["weather"] = {"rain": 0.5}
        with pytest.raises(ValueError, match=r"systems carries unexpected keys: \['weather'\]"):
            parse_episode_plan(plan_bytes(document))

    def test_missing_systems_key_is_rejected(self) -> None:
        """Every canonical system's configuration is required."""
        document = change_plan_document()
        del document["systems"]["migration"]
        with pytest.raises(ValueError, match=r"systems is missing required keys: \['migration'\]"):
            parse_episode_plan(plan_bytes(document))

    def test_unknown_subsection_key_is_rejected(self) -> None:
        """A subsection carries exactly its constructor's parameters."""
        document = change_plan_document()
        document["systems"]["migration"]["speed"] = 2.0
        with pytest.raises(ValueError, match=r"migration carries unexpected keys: \['speed'\]"):
            parse_episode_plan(plan_bytes(document))

    def test_missing_subsection_key_is_rejected(self) -> None:
        """A subsection may not omit a parameter; nothing is defaulted."""
        document = change_plan_document()
        del document["systems"]["social_stability"]["response_rate"]
        with pytest.raises(
            ValueError, match=r"social_stability is missing required keys: \['response_rate'\]"
        ):
            parse_episode_plan(plan_bytes(document))

    def test_bool_scalar_setting_is_rejected(self) -> None:
        """``true`` is not a rate of 1; bool is refused for every scalar."""
        document = change_plan_document()
        document["systems"]["resource_flow"]["reserve_ticks"] = True
        with pytest.raises(TypeError, match="reserve_ticks must be a real number, got bool"):
            parse_episode_plan(plan_bytes(document))

    def test_string_scalar_setting_is_rejected(self) -> None:
        """A numeric setting spelled as a string is refused, not coerced."""
        document = change_plan_document()
        document["systems"]["boundary_decision"]["build_threshold"] = "0.75"
        with pytest.raises(TypeError, match="build_threshold must be a real number, got str"):
            parse_episode_plan(plan_bytes(document))

    def test_whitespace_movement_law_id_is_rejected(self) -> None:
        """The movement law identifier is refused as found, never stripped."""
        document = change_plan_document()
        document["systems"]["movement_law_id"] = " law_movement_sharing"
        with pytest.raises(ValueError, match="must not carry surrounding whitespace"):
            parse_episode_plan(plan_bytes(document))


class TestSnapshotSemantics:
    """A parsed plan is a capture: nothing mutable is retained or alterable."""

    def test_mutable_configuration_input_is_not_retained(self) -> None:
        """Mutating the caller's allocation later cannot reach the capture."""
        allocation = {
            ResourceType.FOOD: 0.5,
            ResourceType.MATERIALS: 0.3,
            ResourceType.ENERGY: 0.2,
        }
        config = dataclasses.replace(
            valid_systems_configuration(),
            production_allocation=allocation,
        )
        allocation[ResourceType.FOOD] = 99.0
        assert config.production_allocation[ResourceType.FOOD] == 0.5

    def test_parsed_allocations_are_read_only_captures(self) -> None:
        """The plan's allocations are fresh read-only mappings."""
        systems = parsed_change_plan().systems
        assert type(systems.production_allocation) is MappingProxyType
        assert type(systems.consumption_allocation) is MappingProxyType
        with pytest.raises(TypeError):
            systems.production_allocation[ResourceType.FOOD] = 1.0  # type: ignore[index]

    def test_frozen_plan_cannot_be_altered(self) -> None:
        """Every field of a validated plan refuses assignment."""
        plan = parsed_change_plan()
        with pytest.raises(dataclasses.FrozenInstanceError):
            plan.ticks = 99  # type: ignore[misc]
        with pytest.raises(dataclasses.FrozenInstanceError):
            plan.parent_episode = 5  # type: ignore[misc]
        with pytest.raises(dataclasses.FrozenInstanceError):
            plan.systems.build_threshold = 0.1  # type: ignore[misc]
        with pytest.raises(dataclasses.FrozenInstanceError):
            plan.action.tick = 1  # type: ignore[misc]


class TestDirectConstruction:
    """The dataclasses revalidate even when built without JSON."""

    def test_action_episode_must_be_derived_child(self) -> None:
        """An action for any other episode cannot enter a plan."""
        with pytest.raises(ValueError, match="the child episode is always derived"):
            EpisodePlan(
                parent_episode=0,
                ticks=6,
                action=ScheduledLawChange(
                    episode=5, tick=7, law_id=MOVEMENT_LAW_ID, new_value=False, active=False
                ),
                systems=valid_systems_configuration(),
            )

    def test_action_subclass_is_rejected(self) -> None:
        """Only the exact base scheduled actions are trusted."""

        class ShiftyChange(ScheduledLawChange):
            """A subclass that could answer differently on later reads."""

        with pytest.raises(TypeError, match="must be exactly a ScheduledLawChange"):
            EpisodePlan(
                parent_episode=0,
                ticks=6,
                action=ShiftyChange(
                    episode=1, tick=7, law_id=MOVEMENT_LAW_ID, new_value=False, active=False
                ),
                systems=valid_systems_configuration(),
            )

    def test_non_finite_scalar_is_rejected(self) -> None:
        """Infinity cannot enter a configuration through direct construction."""
        with pytest.raises(ValueError, match="reserve_ticks must be finite"):
            dataclasses.replace(valid_systems_configuration(), reserve_ticks=float("inf"))

    def test_int_subclass_scalar_is_rejected(self) -> None:
        """An IntEnum pretending to be an int is refused by true type."""

        class Sneaky(int):
            """An int subclass that is not an int setting."""

        with pytest.raises(TypeError, match="migration_rate must be a real number, got Sneaky"):
            dataclasses.replace(valid_systems_configuration(), migration_rate=Sneaky(1))

    def test_string_keyed_allocation_is_rejected_when_direct(self) -> None:
        """Direct construction requires exact enum members, not names."""
        with pytest.raises(TypeError, match="keys must be ResourceType members"):
            dataclasses.replace(
                valid_systems_configuration(),
                production_allocation={"FOOD": 0.5, "MATERIALS": 0.3, "ENERGY": 0.2},  # type: ignore[dict-item]
            )

    def test_systems_must_be_exact_configuration(self) -> None:
        """A plan refuses anything but the exact configuration type."""
        with pytest.raises(TypeError, match="systems must be a SystemsConfiguration"):
            EpisodePlan(
                parent_episode=0,
                ticks=6,
                action=ScheduledLawRestore(episode=1, tick=7, law_id=MOVEMENT_LAW_ID),
                systems={"movement_law_id": MOVEMENT_LAW_ID},  # type: ignore[arg-type]
            )
