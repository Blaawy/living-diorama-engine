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
Two top-level fields are optional rather than required: ``wording_profile``,
which records which reviewed register the sentences were written under, and
``viewer_guidance``, the spoken directions a ``v2`` plan carries. A document
without ``wording_profile`` is read as ``v1`` and validates exactly as it did
before the field existed; a document that declares it must name one of the
reviewed profiles, and only a ``v2`` document may carry viewer guidance.

This validator is deliberately self-contained: it proves everything the plan
can prove about itself, the wording bans included. Whether the plan's claims
are true *of* its sources is proven by
:func:`living_diorama.language_realization.realization_cross_check.validate_language_realization_plan_against_sources`,
which takes those sources as arguments.
"""

from typing import Final, cast

from living_diorama.language_realization.realization_guidance import (
    VIEWER_GUIDANCE_GROUNDING_NONE,
    VIEWER_GUIDANCE_GROUNDING_ROAD,
    VIEWER_GUIDANCE_GROUNDING_WALL,
)
from living_diorama.language_realization.realization_spec import (
    FORBIDDEN_V2_JARGON,
    REALIZATION_ID_FORM,
    REALIZATION_PLAN_FORMAT,
    REALIZATION_POLICY_V1,
    REALIZATION_SCHEMA_VERSION,
    WORDING_PROFILE_V2,
    WORDING_PROFILES,
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
"""Exactly the required top-level keys an episode language realization plan carries.

``wording_profile`` and ``viewer_guidance`` are the two optional top-level
keys: absent, the former is read as ``v1``, and the latter is simply not
carried. Both key sets -- with and without the optional fields -- are exact;
anything else is refused.
"""

OPTIONAL_TOP_LEVEL_KEYS: Final = frozenset({"wording_profile", "viewer_guidance"})
"""The top-level keys a plan may carry but is never required to.

The wording register a plan was written under, and the viewer guidance lines a
``v2`` plan carries. The V1 derivation omits both, so today's documents
validate unchanged; a V2 derivation declares itself and its guidance. A plan
that carries ``viewer_guidance`` without declaring the ``v2`` register is
refused: guidance is a V2-only field.
"""

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
"""Exactly the keys a V1 realization record carries.

Deliberately no timing, no shot citation, no visibility, no audio
configuration, and no copy of the source sentence: wording history stays
authoritative in the narration plan the record's ``unit_id`` names, and the
only new claim a record makes is its one reviewed human-facing sentence. The
field is named ``realized_text`` rather than ``text`` so the boundary guard
can ban every read of an upstream ``text`` key outright.
"""

REALIZATION_KEYS_V2: Final = frozenset(
    {"category", "event_id", "fact_id", "realization_id", "realized_text", "unit_id"}
)
"""Exactly the keys a V2 realization record carries: the V1 keys plus the binding.

Every V2 record binds the sentence to what it restates: ``category`` (a
narration record is always a fact, guidance living at the top level),
``fact_id`` (the memory fact a fact-backed record restates, or ``null``), and
``event_id`` (the export event index the record's beat cites, or ``null`` for
an absence). A V1 record carries none of these, so today's documents validate
unchanged.
"""

V2_RECORD_CATEGORIES: Final = ("fact", "guidance")
"""The two reviewed record categories a V2 plan may declare.

Every realization record in this build realizes a narration unit, so the
planner always writes ``"fact"``; ``"guidance"`` is reserved for a future
record class that this build does not produce.
"""

GUIDANCE_KEYS: Final = frozenset({"guidance_text", "grounding"})
"""Exactly the keys one viewer guidance entry carries."""

GUIDANCE_GROUNDINGS: Final = (
    VIEWER_GUIDANCE_GROUNDING_NONE,
    VIEWER_GUIDANCE_GROUNDING_ROAD,
    VIEWER_GUIDANCE_GROUNDING_WALL,
)
"""The reviewed grounding tags a guidance entry may carry."""

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


def _require_top_level_keys(document: dict[str, JsonValue], description: str) -> None:
    """Verify the document carries exactly the required keys plus the optional ones.

    Both directions matter, as they do for every governed level: a missing key
    means the plan is incomplete, and an unexpected key means it was written by
    something this contract does not describe. The two optional fields,
    ``wording_profile`` and ``viewer_guidance``, are the only extra keys this
    build will read.

    Raises:
        ValueError: If any required key is missing or any key other than the
            optional fields is present.
    """
    present = set(document)
    missing = sorted(set(TOP_LEVEL_KEYS) - present)
    unexpected = sorted(present - set(TOP_LEVEL_KEYS) - set(OPTIONAL_TOP_LEVEL_KEYS))
    if missing:
        raise ValueError(f"{description} is missing required keys: {missing}")
    if unexpected:
        raise ValueError(f"{description} carries unexpected keys: {unexpected}")


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


def _validate_v2_vocabulary(text: str, description: str) -> None:
    """Verify a V2 spoken string avoids the register's analytic vocabulary."""
    hit = FORBIDDEN_V2_JARGON.search(text)
    if hit is not None:
        raise ValueError(
            f"{description} uses {hit.group(0)!r}; the v2 register never speaks the "
            "simulation's analytic vocabulary"
        )


def _validate_optional_identifier(value: object, description: str) -> None:
    """Verify a binding identifier is either absent or a real identifier."""
    if value is None:
        return
    require_identifier(value, description)


def _validate_optional_int(value: object, description: str) -> None:
    """Verify a binding index is either absent or a real exact integer."""
    if value is None:
        return
    require_exact_int(value, description)


def _validate_guidance_entry(value: object, description: str) -> None:
    """Verify one viewer guidance entry: exact keys, safe text, reviewed grounding."""
    entry = _require_document(value, description)
    require_exact_keys(entry, GUIDANCE_KEYS, description)
    guidance_text = _validate_realized_text(
        entry.get("guidance_text"), f"{description} guidance_text"
    )
    _validate_v2_vocabulary(guidance_text, f"{description} guidance_text")
    _require_member(entry.get("grounding"), GUIDANCE_GROUNDINGS, f"{description} grounding")


def _validate_realization(
    value: object,
    description: str,
    position: int,
    wording_profile: str | None,
) -> None:
    """Verify one realization record at its position, under its register."""
    record = _require_document(value, description)
    if wording_profile == WORDING_PROFILE_V2:
        require_exact_keys(record, REALIZATION_KEYS_V2, description)
        _require_member(record.get("category"), V2_RECORD_CATEGORIES, f"{description} category")
        _validate_optional_identifier(record.get("fact_id"), f"{description} fact_id")
        _validate_optional_int(record.get("event_id"), f"{description} event_id")
    else:
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
    sentence = _validate_realized_text(record.get("realized_text"), f"{description} realized_text")
    if wording_profile == WORDING_PROFILE_V2:
        _validate_v2_vocabulary(sentence, f"{description} realized_text")


def validate_episode_language_realization_plan(value: object) -> dict[str, JsonValue]:
    """Verify a document's Episode Language Realization Plan V1 envelope.

    Checks the exact key sets at every governed level -- with ``wording_profile``
    and ``viewer_guidance`` the two optional top-level fields, the former read
    as ``v1`` when absent and the latter refused unless the document declares
    the ``v2`` register -- the format tag, schema version and policy identity,
    the source binding (episode, mode, the digest fields, and the rule that
    only a baseline has no previous episode), every realization record: that
    its identifiers agree with its position, that its sentence clears the
    wording bans, and under ``v2`` that its category, fact and event bindings
    are well-formed and its sentence avoids the register's vocabulary, and
    every viewer guidance entry: safe text, reviewed grounding, and the
    register's vocabulary ban. The accounting block must agree with the
    records actually present and close on its own arithmetic.

    Raises:
        TypeError: If any value has the wrong Python type.
        ValueError: If any key set, vocabulary member, identity, bound,
            ordering or internal agreement is violated.
    """
    document = _require_document(value, "language realization plan")
    _require_top_level_keys(document, "language realization plan")

    raw_wording_profile = document.get("wording_profile")
    wording_profile: str | None = None
    if raw_wording_profile is not None:
        wording_profile = _require_member(
            raw_wording_profile, WORDING_PROFILES, "language realization plan wording_profile"
        )
    viewer_guidance = document.get("viewer_guidance")
    if viewer_guidance is not None and wording_profile != WORDING_PROFILE_V2:
        raise ValueError(
            "language realization plan carries viewer_guidance but declares wording "
            f"profile {wording_profile!r}; viewer guidance is a v2-only field"
        )

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
            record,
            f"language realization plan realizations[{position - 1}]",
            position,
            wording_profile,
        )

    if viewer_guidance is not None:
        guidance_list = _require_list(viewer_guidance, "language realization plan viewer_guidance")
        for index, entry in enumerate(guidance_list):
            _validate_guidance_entry(entry, f"language realization plan viewer_guidance[{index}]")

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
