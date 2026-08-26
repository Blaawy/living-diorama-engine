"""Episode Voice Plan format V1: the reviewed narrator request and its capacity.

A voice plan is deterministic narrator-request identity bound to authoritative
document identity. It says, for every locked realized sentence of one
directed episode, which reviewed narrator request speaks it and how many
audio samples of that speech its Phase 27 presentation window has room for.
It asserts nothing about the world, nothing about wording, and nothing about
whether real speech actually fits -- those live in the documents it binds and
in a later voice execution phase, and stay there.

The document shape is exact at every level this module governs. A key that is
missing means the plan is incomplete; a key that is extra means it was
written by something this contract does not describe. Both are refused,
never repaired.

This validator is deliberately self-contained: it proves everything the plan
can prove about itself, including that its narrator request equals the one
reviewed policy field for field, that every voice unit is positional, and
that a unit's ``capacity_samples`` sits inside this layer's own plausibility
rail. It cannot prove a unit's capacity is true of an actual Phase 27 window
-- that is a fact about a second document, and standalone validity never
claims to prove a fact about a document it was not given. Whether the plan's
claims are true *of* its two bound sources -- and true of everything those
were themselves proven against -- is proven by
:func:`living_diorama.voice.voice_cross_check.validate_episode_voice_plan_against_sources`,
which takes those sources as arguments.
"""

from typing import Final, cast

from living_diorama.language_realization.realization_spec import REALIZATION_ID_FORM
from living_diorama.narration.narration_schema_v1 import (
    MODE_BASELINE,
    PLAN_MODES,
    UNIT_ID_FORM,
)
from living_diorama.persistence.schema.state_hash import require_hash_hex
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_identifier,
    require_text,
)
from living_diorama.presentation.presentation_spec import WINDOW_ID_FORM
from living_diorama.voice.voice_spec import (
    MAX_VOICE_CAPACITY_SAMPLES,
    VOICE_BLOCK,
    VOICE_PLAN_FORMAT,
    VOICE_PLAN_SCHEMA_VERSION,
    VOICE_POLICY_V1,
    VOICE_UNIT_ID_FORM,
)

SUPPORTED_REALIZATION_SCHEMA_VERSION: Final = 1
SUPPORTED_PRESENTATION_SCHEMA_VERSION: Final = 1
"""The upstream contract versions this build speaks."""

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
"""The JSON value shape this contract works in.

Declared here rather than imported from an upstream layer for the same reason
Phase 24 through Phase 27 each declare their own: a shared alias is not worth
a hole in a boundary.
"""

TOP_LEVEL_KEYS: Final = frozenset(
    {"accounting", "format", "policy", "schema_version", "source", "voice", "voice_units"}
)
"""Exactly the top-level keys an episode voice plan carries."""

SOURCE_KEYS: Final = frozenset(
    {
        "episode",
        "mode",
        "previous_episode",
        "presentation_plan_sha256",
        "presentation_schema_version",
        "realization_plan_sha256",
        "realization_schema_version",
    }
)
"""Exactly the keys binding a plan to the two documents it speaks.

Two digests, because a voice plan claims nothing that the realization plan
and the presentation plan alone would not already prove: which sentence
(named by identity, never carried), and how much capacity a window offers.
There is deliberately no motion-time digest, no narration-plan digest, no
delivery-plan digest, no shot-plan digest, no story-plan digest, no
render-export digest and no measurement-record digest -- every one of those
relationships is proven by the reused Phase 27 source-verification gate this
plan's own cross-check runs in full, and restating any of their digests here
would be a copy, not proof.
"""

VOICE_KEYS: Final = frozenset(
    {
        "engine",
        "engine_version",
        "g2p",
        "g2p_version",
        "model_repository",
        "model_revision",
        "model_weights_sha256",
        "model_config_sha256",
        "voice",
        "voice_pack_sha256",
        "lang_code",
        "speed_percent",
        "sample_rate_hz",
        "channels",
        "seed",
    }
)
"""Exactly the keys the reviewed narrator request carries.

Every field is required to equal the one pinned ``VOICE_BLOCK`` exactly --
this is identity, not a choice a plan makes for itself.
"""

VOICE_UNIT_KEYS: Final = frozenset(
    {"voice_unit_id", "unit_id", "realization_id", "window_id", "capacity_samples"}
)
"""Exactly the keys a voice-unit record carries.

Deliberately no realized text, no text hash, no measured sample count, no fit
status, no duration, no presentation frame coordinates and no speech offsets:
a voice unit names which narrator speaks which realized sentence inside which
window, and how many samples that window offers -- nothing about whether real
speech fits, which is a later, measured phase's question.
"""

ACCOUNTING_KEYS: Final = frozenset({"voice_units_total", "capacity_samples_total"})
"""Exactly the keys the accounting block carries.

The aggregate verdict, stated in a way a truncated plan cannot fake. There is
no measured total here: nothing in this document is ever measured.
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


def _validate_voice_block(value: object) -> dict[str, JsonValue]:
    """Verify the narrator request equals the one reviewed policy, field for field."""
    description = "voice plan voice"
    voice = _require_document(value, description)
    require_exact_keys(voice, VOICE_KEYS, description)
    for field in ("engine", "g2p", "model_repository", "voice", "lang_code"):
        text = require_text(voice.get(field), f"{description} {field}")
        expected_text = cast(str, VOICE_BLOCK[field])
        if text != expected_text:
            raise ValueError(
                f"{description} {field} is {text!r}; this build derives and validates "
                f"{expected_text!r} only"
            )
    for field in ("engine_version", "g2p_version", "model_revision"):
        text = require_identifier(voice.get(field), f"{description} {field}")
        expected_text = cast(str, VOICE_BLOCK[field])
        if text != expected_text:
            raise ValueError(
                f"{description} {field} is {text!r}; this build derives and validates "
                f"{expected_text!r} only"
            )
    for field in ("model_weights_sha256", "model_config_sha256", "voice_pack_sha256"):
        digest = require_hash_hex(voice.get(field), f"{description} {field}")
        expected_digest = cast(str, VOICE_BLOCK[field])
        if digest != expected_digest:
            raise ValueError(
                f"{description} {field} is {digest!r}; this build derives and validates "
                f"{expected_digest!r} only"
            )
    for field in ("speed_percent", "sample_rate_hz", "channels", "seed"):
        number = require_exact_int(voice.get(field), f"{description} {field}")
        expected_number = cast(int, VOICE_BLOCK[field])
        if number != expected_number:
            raise ValueError(
                f"{description} {field} is {number}; this build derives and validates "
                f"{expected_number} only"
            )
    return voice


def _validate_voice_unit(value: object, description: str, position: int) -> int:
    """Verify one voice-unit record, and return its ``capacity_samples``."""
    record = _require_document(value, description)
    require_exact_keys(record, VOICE_UNIT_KEYS, description)

    voice_unit_id = require_identifier(record.get("voice_unit_id"), f"{description} voice_unit_id")
    expected_voice_unit = VOICE_UNIT_ID_FORM % position
    if voice_unit_id != expected_voice_unit:
        raise ValueError(
            f"{description} declares voice_unit_id {voice_unit_id!r} but sits at position "
            f"{position}, where the identifier is {expected_voice_unit!r}; a voice-unit id "
            "is positional, not a free label"
        )
    unit_id = require_identifier(record.get("unit_id"), f"{description} unit_id")
    expected_unit = UNIT_ID_FORM % position
    if unit_id != expected_unit:
        raise ValueError(
            f"{description} speaks unit {unit_id!r} but sits at position {position}, where "
            f"the narration plan's unit is {expected_unit!r}; a voice unit follows the "
            "narration plan's own order"
        )
    realization_id = require_identifier(
        record.get("realization_id"), f"{description} realization_id"
    )
    expected_realization = REALIZATION_ID_FORM % position
    if realization_id != expected_realization:
        raise ValueError(
            f"{description} names realization {realization_id!r} but sits at position "
            f"{position}, where the realization plan's record is "
            f"{expected_realization!r}; a voice unit follows the realization plan's own "
            "order"
        )
    window_id = require_identifier(record.get("window_id"), f"{description} window_id")
    expected_window = WINDOW_ID_FORM % position
    if window_id != expected_window:
        raise ValueError(
            f"{description} names window {window_id!r} but sits at position {position}, "
            f"where the presentation plan's window is {expected_window!r}; a voice unit "
            "follows the presentation plan's own order"
        )

    capacity = require_exact_int(record.get("capacity_samples"), f"{description} capacity_samples")
    if not 1 <= capacity <= MAX_VOICE_CAPACITY_SAMPLES:
        raise ValueError(
            f"{description} capacity_samples must be within [1, {MAX_VOICE_CAPACITY_SAMPLES}], "
            f"got {capacity}"
        )
    return capacity


def validate_episode_voice_plan(value: object) -> dict[str, JsonValue]:
    """Verify a document's Episode Voice Plan V1 envelope, and return it.

    Checks the exact key sets at every governed level, the format tag, schema
    version and policy identity, the source binding (episode, mode, the two
    digest fields, and the two schema-version fields against the versions
    this build supports, and the rule that only a baseline has no previous
    episode), that the narrator request equals the one reviewed policy field
    for field, and every voice-unit record's own positional identity and
    plausibility rail. Whole-document accounting is enforced too: every
    voice-unit total is measured from the records present, never asserted
    beside them.

    This validator is deliberately self-contained: it proves everything the
    plan can prove about itself, and nothing that needs the two bound
    sources. In particular, it cannot and does not prove that any unit's
    ``capacity_samples`` is true of an actual Phase 27 window -- that fact
    about a second document is proven only by
    :func:`living_diorama.voice.voice_cross_check.validate_episode_voice_plan_against_sources`.

    Raises:
        TypeError: If any value has the wrong exact type.
        ValueError: If any key set, vocabulary member, ordering, bound or
            internal agreement is violated.
    """
    document = _require_document(value, "voice plan")
    require_exact_keys(document, TOP_LEVEL_KEYS, "voice plan")

    tag = require_text(document.get("format"), "voice plan format")
    if tag != VOICE_PLAN_FORMAT:
        raise ValueError(
            f"voice plan declares format {tag!r}; this build reads {VOICE_PLAN_FORMAT!r} only"
        )
    version = require_exact_int(document.get("schema_version"), "voice plan schema_version")
    if version != VOICE_PLAN_SCHEMA_VERSION:
        raise ValueError(
            f"voice plan declares unsupported schema version {version}; this build reads "
            f"version {VOICE_PLAN_SCHEMA_VERSION} only"
        )
    policy = require_text(document.get("policy"), "voice plan policy")
    if policy != VOICE_POLICY_V1:
        raise ValueError(
            f"voice plan declares policy {policy!r}; this build derives and validates "
            f"{VOICE_POLICY_V1!r} only, and a plan cut under another policy must never be "
            "mistaken for one of these"
        )

    source = _require_document(document.get("source"), "voice plan source")
    require_exact_keys(source, SOURCE_KEYS, "voice plan source")
    mode = _require_member(source.get("mode"), PLAN_MODES, "voice plan source mode")
    episode = require_exact_int(source.get("episode"), "voice plan source episode")
    presentation_version = require_exact_int(
        source.get("presentation_schema_version"), "voice plan source presentation_schema_version"
    )
    if presentation_version != SUPPORTED_PRESENTATION_SCHEMA_VERSION:
        raise ValueError(
            f"voice plan was derived from presentation schema version "
            f"{presentation_version}; this build speaks version "
            f"{SUPPORTED_PRESENTATION_SCHEMA_VERSION} only"
        )
    realization_version = require_exact_int(
        source.get("realization_schema_version"), "voice plan source realization_schema_version"
    )
    if realization_version != SUPPORTED_REALIZATION_SCHEMA_VERSION:
        raise ValueError(
            f"voice plan was derived from realization schema version "
            f"{realization_version}; this build speaks version "
            f"{SUPPORTED_REALIZATION_SCHEMA_VERSION} only"
        )
    for field in ("presentation_plan_sha256", "realization_plan_sha256"):
        require_hash_hex(source.get(field), f"voice plan source {field}")

    previous = source.get("previous_episode")
    if mode == MODE_BASELINE:
        _require_null(
            previous,
            "voice plan source previous_episode",
            "a baseline speaks one export's narration and follows no episode",
        )
        if episode != 0:
            raise ValueError(
                f"voice plan is baseline mode but describes episode {episode}; a baseline "
                "describes episode 0 only"
            )
    else:
        previous_episode = require_exact_int(previous, "voice plan source previous_episode")
        if episode != previous_episode + 1:
            raise ValueError(
                f"voice plan binds episode {previous_episode} then episode {episode}; a "
                "transition joins consecutive episodes"
            )

    _validate_voice_block(document.get("voice"))

    voice_units = _require_list(document.get("voice_units"), "voice plan voice_units")
    if not voice_units:
        raise ValueError(
            "voice plan carries no voice units; every narration plan holds at least one "
            "unit, and every unit is spoken exactly once"
        )
    capacities: list[int] = []
    for position, record in enumerate(voice_units, start=1):
        description = f"voice plan voice_units[{position - 1}]"
        capacities.append(_validate_voice_unit(record, description, position))

    accounting = _require_document(document.get("accounting"), "voice plan accounting")
    require_exact_keys(accounting, ACCOUNTING_KEYS, "voice plan accounting")
    declared_units = require_exact_int(
        accounting.get("voice_units_total"), "voice plan accounting voice_units_total"
    )
    if declared_units != len(voice_units):
        raise ValueError(
            f"voice plan declares {declared_units} voice units but carries "
            f"{len(voice_units)}; the total is measured from the records present"
        )
    declared_capacity = require_exact_int(
        accounting.get("capacity_samples_total"), "voice plan accounting capacity_samples_total"
    )
    if declared_capacity != sum(capacities):
        raise ValueError(
            f"voice plan declares {declared_capacity} total capacity samples, but its own "
            f"voice units close on {sum(capacities)}; the total is measured from the records "
            "present rather than asserted beside them"
        )

    return document
