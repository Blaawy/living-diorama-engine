"""Episode Language Realization Plan format V1: the human-wording contract.

A language realization plan is human-facing presentation wording bound to
authoritative document identity. It says, for every unit of one Episode
Narration Plan, the one reviewed sentence a human may be told, and binds the
exact narration plan, story plan and render export the wording was proven
against. It asserts nothing about the world, nothing about visibility, and
nothing about time -- those live in the documents it binds, and stay there.

The document shape is exact at every level this module governs. A key that is
missing means the plan is incomplete; a key that is extra means it was written
by something this contract does not describe. Both are refused, never repaired.

This validator is deliberately self-contained: it proves everything the plan
can prove about itself, the wording bans included. Whether the plan's claims
are true *of* its sources is proven by
:func:`living_diorama.language_realization.realization_cross_check.validate_language_realization_plan_against_sources`,
which takes those sources as arguments.
"""

from typing import Final, cast

from living_diorama.language_realization.realization_spec import (
    REALIZATION_ID_FORM,
    REALIZATION_PLAN_FORMAT,
    REALIZATION_POLICY_V1,
    REALIZATION_SCHEMA_VERSION,
)
from living_diorama.narration.narration_schema_v1 import (
    MODE_BASELINE,
    PLAN_MODES,
    UNIT_ID_FORM,
)
from living_diorama.narration.narration_spec import forbidden_wording_hit
from living_diorama.persistence.schema.state_hash import require_hash_hex
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_identifier,
    require_text,
)

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
"""The JSON value shape this contract works in.

Declared here rather than imported from the narration layer for the same reason
Phase 24 and Phase 25 declare their own: a shared alias is not worth a hole in
a boundary.
"""

SUPPORTED_NARRATION_SCHEMA_VERSION: Final = 1
SUPPORTED_STORY_SCHEMA_VERSION: Final = 1
"""The upstream contract versions this build realizes."""

TOP_LEVEL_KEYS: Final = frozenset(
    {"accounting", "format", "policy", "realizations", "schema_version", "source"}
)
"""Exactly the top-level keys an episode language realization plan carries."""

SOURCE_KEYS: Final = frozenset(
    {
        "current_export_sha256",
        "episode",
        "mode",
        "narration_plan_sha256",
        "narration_schema_version",
        "previous_episode",
        "story_plan_sha256",
        "story_schema_version",
    }
)
"""Exactly the keys binding a plan to the documents it realizes.

Three digests, because realization proves its wording against three documents:
the narration plan whose units it realizes, the story plan whose structured
evidence licenses every atom, and the render export whose facts and world
entities every label resolves through. The narration plan already binds the
shot plan it reported visibility from, so that chain is inherited rather than
restated -- realization owns no visibility claim and no timing claim, and a
digest it does not check would be a copy, not proof.
"""

REALIZATION_KEYS: Final = frozenset({"realization_id", "realized_text", "unit_id"})
"""Exactly the keys a realization record carries.

Deliberately no timing, no shot citation, no visibility, no audio
configuration, and no copy of the source sentence: wording history stays
authoritative in the narration plan the record's ``unit_id`` names, and the
only new claim a record makes is its one reviewed human-facing sentence. The
field is named ``realized_text`` rather than ``text`` so the boundary guard
can ban every read of an upstream ``text`` key outright.
"""

ACCOUNTING_KEYS: Final = frozenset({"fact_backed", "realizations_total", "template_backed"})
"""Exactly the keys the accounting block carries.

``realizations_total`` is measured from the records present. The
template/fact split restates the narration plan's own text-source
classification, which no realization record carries alone -- the cross-check
proves the split against the sources, and the schema proves the three numbers
close on themselves.
"""


def _require_document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    for key in value:
        if type(key) is not str:
            raise TypeError(f"{description} keys must be str, got {type(key).__name__}")
    return cast(dict[str, JsonValue], value)


def _require_list(value: object, description: str) -> list[JsonValue]:
    if type(value) is not list:
        raise TypeError(f"{description} must be a list, got {type(value).__name__}")
    return cast(list[JsonValue], value)


def _require_member(value: object, allowed: tuple[str, ...], description: str) -> str:
    text = require_text(value, description)
    if text not in allowed:
        raise ValueError(f"{description} is {text!r}; expected one of {list(allowed)}")
    return text


def _require_null(value: object, description: str, because: str) -> None:
    if value is not None:
        raise ValueError(f"{description} is {value!r}, but {because}")


def _validate_realized_text(value: object, description: str) -> str:
    """Verify one realized sentence is present and safe to say, and return it.

    The Phase 24 wording authority is reused rather than copied: a realized
    sentence must clear exactly the causal and deictic bans the narration
    layer's own sentences clear. Two stricter rules are this layer's own --
    no underscore and no straight quotation mark -- because realized wording
    names entities by reviewed label, never by internal identifier.
    """
    sentence = require_text(value, description)
    hit = forbidden_wording_hit(sentence)
    if hit is not None:
        raise ValueError(
            f"{description} uses {hit!r}; realized wording never makes a causal or "
            "visual claim the sources cannot prove"
        )
    if "_" in sentence:
        raise ValueError(
            f"{description} carries an underscore; an internal identifier never leaks "
            "into human-facing wording"
        )
    if '"' in sentence:
        raise ValueError(
            f"{description} carries a straight quotation mark; realized wording names "
            "entities by reviewed label, never by quoted identifier"
        )
    return sentence


def _validate_realization(value: object, description: str, position: int) -> None:
    """Verify one realization record at its position."""
    record = _require_document(value, description)
    require_exact_keys(record, REALIZATION_KEYS, description)

    realization_id = require_identifier(
        record.get("realization_id"), f"{description} realization_id"
    )
    expected_realization = REALIZATION_ID_FORM % position
    if realization_id != expected_realization:
        raise ValueError(
            f"{description} declares realization_id {realization_id!r} but sits at "
            f"position {position}, where the identifier is {expected_realization!r}; a "
            "realization id is positional, not a free label"
        )
    unit_id = require_identifier(record.get("unit_id"), f"{description} unit_id")
    expected_unit = UNIT_ID_FORM % position
    if unit_id != expected_unit:
        raise ValueError(
            f"{description} realizes unit {unit_id!r} but sits at position {position}, "
            f"where the narration plan's unit is {expected_unit!r}; realization follows "
            "the narration plan's own order, one record per unit"
        )
    _validate_realized_text(record.get("realized_text"), f"{description} realized_text")


def validate_episode_language_realization_plan(value: object) -> dict[str, JsonValue]:
    """Verify a document's Episode Language Realization Plan V1 envelope.

    Checks the exact key sets at every governed level, the format tag, schema
    version and policy identity, the source binding (episode, mode, the digest
    fields, and the rule that only a baseline has no previous episode), and
    every realization record: that its identifiers agree with its position and
    that its sentence clears the wording bans. The accounting block must agree
    with the records actually present and close on its own arithmetic.

    Raises:
        TypeError: If any value has the wrong Python type.
        ValueError: If any key set, vocabulary member, identity, bound,
            ordering or internal agreement is violated.
    """
    document = _require_document(value, "language realization plan")
    require_exact_keys(document, TOP_LEVEL_KEYS, "language realization plan")

    tag = require_text(document.get("format"), "language realization plan format")
    if tag != REALIZATION_PLAN_FORMAT:
        raise ValueError(
            f"language realization plan declares format {tag!r}; this build reads "
            f"{REALIZATION_PLAN_FORMAT!r} only"
        )
    version = require_exact_int(
        document.get("schema_version"), "language realization plan schema_version"
    )
    if version != REALIZATION_SCHEMA_VERSION:
        raise ValueError(
            f"language realization plan declares unsupported schema version {version}; "
            f"this build reads version {REALIZATION_SCHEMA_VERSION} only"
        )
    policy = require_text(document.get("policy"), "language realization plan policy")
    if policy != REALIZATION_POLICY_V1:
        raise ValueError(
            f"language realization plan declares policy {policy!r}; this build derives "
            f"and validates {REALIZATION_POLICY_V1!r} only, and wording written under "
            "another policy must never be mistaken for this one"
        )

    source = _require_document(document.get("source"), "language realization plan source")
    require_exact_keys(source, SOURCE_KEYS, "language realization plan source")
    mode = _require_member(source.get("mode"), PLAN_MODES, "language realization plan source mode")
    episode = require_exact_int(source.get("episode"), "language realization plan source episode")
    narration_version = require_exact_int(
        source.get("narration_schema_version"),
        "language realization plan source narration_schema_version",
    )
    if narration_version != SUPPORTED_NARRATION_SCHEMA_VERSION:
        raise ValueError(
            f"language realization plan was derived from narration schema version "
            f"{narration_version}; this build realizes version "
            f"{SUPPORTED_NARRATION_SCHEMA_VERSION} only"
        )
    story_version = require_exact_int(
        source.get("story_schema_version"),
        "language realization plan source story_schema_version",
    )
    if story_version != SUPPORTED_STORY_SCHEMA_VERSION:
        raise ValueError(
            f"language realization plan was derived from story schema version "
            f"{story_version}; this build realizes version "
            f"{SUPPORTED_STORY_SCHEMA_VERSION} only"
        )
    for field in ("current_export_sha256", "narration_plan_sha256", "story_plan_sha256"):
        require_hash_hex(source.get(field), f"language realization plan source {field}")

    previous = source.get("previous_episode")
    if mode == MODE_BASELINE:
        _require_null(
            previous,
            "language realization plan source previous_episode",
            "a baseline realizes one export's narration and follows no episode",
        )
        if episode != 0:
            raise ValueError(
                f"language realization plan is baseline mode but describes episode "
                f"{episode}; a baseline describes episode 0 only"
            )
    else:
        previous_episode = require_exact_int(
            previous, "language realization plan source previous_episode"
        )
        if episode != previous_episode + 1:
            raise ValueError(
                f"language realization plan binds episode {previous_episode} then episode "
                f"{episode}; a transition joins consecutive episodes"
            )

    realizations = _require_list(
        document.get("realizations"), "language realization plan realizations"
    )
    if not realizations:
        raise ValueError(
            "language realization plan carries no realizations; every narration plan "
            "holds at least one unit, and every unit is realized exactly once"
        )
    for position, record in enumerate(realizations, start=1):
        _validate_realization(
            record, f"language realization plan realizations[{position - 1}]", position
        )

    accounting = _require_document(
        document.get("accounting"), "language realization plan accounting"
    )
    require_exact_keys(accounting, ACCOUNTING_KEYS, "language realization plan accounting")
    declared = {
        field: require_exact_int(
            accounting.get(field), f"language realization plan accounting {field}"
        )
        for field in sorted(ACCOUNTING_KEYS)
    }
    if declared["realizations_total"] != len(realizations):
        raise ValueError(
            f"language realization plan declares {declared['realizations_total']} "
            f"realizations but carries {len(realizations)}; the total is measured from "
            "the records present rather than asserted beside them"
        )
    if declared["template_backed"] + declared["fact_backed"] != declared["realizations_total"]:
        raise ValueError(
            f"language realization plan accounts for {declared['template_backed']} "
            f"template-backed and {declared['fact_backed']} fact-backed records against "
            f"{declared['realizations_total']} realizations; every record is in exactly "
            "one class"
        )

    return document
