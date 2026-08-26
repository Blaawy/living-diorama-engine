"""Source cross-validation of an Episode Voice Plan against its actual sources.

Every forgery here is standalone-valid-but-source-false, exercised against
the reused Phase 27 gate (which itself reruns Phase 25 and Phase 26), this
layer's own bindings, its per-unit joins, its capacity recomputation, and its
final byte seal -- named check by named check, one at a time.
"""

import copy
from typing import Any

import pytest

from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.voice.voice_cross_check import validate_episode_voice_plan_against_sources


@pytest.mark.parametrize("episode", [0, 1, 2])
def test_every_canonical_plan_is_source_verified(
    episode: int, request: pytest.FixtureRequest
) -> None:
    """Every canonical plan is source verified."""
    plan = request.getfixturevalue(f"plan_ep{episode}")
    sources = request.getfixturevalue(f"sources_ep{episode}")
    assert validate_episode_voice_plan_against_sources(plan, *sources) == plan


def test_the_locked_upstream_gate_is_imported() -> None:
    """The locked upstream gate is imported."""
    import ast

    module = ast.parse(
        (
            __import__("pathlib").Path(__file__).resolve().parents[2]
            / "src"
            / "living_diorama"
            / "voice"
            / "voice_cross_check.py"
        ).read_text(encoding="utf-8")
    )
    imported = {
        alias.name
        for node in ast.walk(module)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "validate_episode_presentation_plan_against_sources" in imported


def test_the_cross_check_actually_calls_the_reused_gate(
    plan_ep1: dict[str, Any], sources_ep1: tuple[Any, ...]
) -> None:
    """The cross check actually calls the reused gate."""
    _realization, _presentation, delivery, narration, shots, story, export = sources_ep1
    forged_delivery = copy.deepcopy(delivery)
    forged_delivery["deliveries"][0]["start_frame"] = 999_999
    with pytest.raises(ValueError):
        validate_episode_voice_plan_against_sources(
            plan_ep1,
            sources_ep1[0],
            sources_ep1[1],
            forged_delivery,
            narration,
            shots,
            story,
            export,
        )


# ---- forged bound digests -------------------------------------------------


def test_a_forged_realization_digest_is_refused(
    plan_ep1: dict[str, Any], sources_ep1: tuple[Any, ...]
) -> None:
    """A forged realization digest is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["source"]["realization_plan_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="does not speak that document"):
        validate_episode_voice_plan_against_sources(broken, *sources_ep1)


def test_a_forged_presentation_digest_is_refused(
    plan_ep1: dict[str, Any], sources_ep1: tuple[Any, ...]
) -> None:
    """A forged presentation digest is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["source"]["presentation_plan_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="does not speak that document"):
        validate_episode_voice_plan_against_sources(broken, *sources_ep1)


# ---- wrong schema versions / lineage --------------------------------------


def test_a_wrong_realization_schema_version_is_refused(
    plan_ep1: dict[str, Any], sources_ep1: tuple[Any, ...]
) -> None:
    """A wrong realization schema version is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["source"]["realization_schema_version"] = 999
    with pytest.raises(ValueError, match="realization schema version"):
        validate_episode_voice_plan_against_sources(broken, *sources_ep1)


def test_a_wrong_presentation_schema_version_is_refused(
    plan_ep1: dict[str, Any], sources_ep1: tuple[Any, ...]
) -> None:
    """A wrong presentation schema version is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["source"]["presentation_schema_version"] = 999
    with pytest.raises(ValueError, match="presentation schema version"):
        validate_episode_voice_plan_against_sources(broken, *sources_ep1)


@pytest.mark.parametrize("field", ["episode", "mode", "previous_episode"])
def test_a_wrong_lineage_field_disagreeing_with_the_presentation_plan_is_refused(
    plan_ep1: dict[str, Any], sources_ep1: tuple[Any, ...], field: str
) -> None:
    """A wrong lineage field disagreeing with the presentation plan is refused."""
    broken = copy.deepcopy(plan_ep1)
    if field == "mode":
        broken["source"][field] = "baseline"
    else:
        broken["source"][field] = 999
    with pytest.raises(ValueError):
        validate_episode_voice_plan_against_sources(broken, *sources_ep1)


# ---- forged narrator request, each of the fifteen fields ------------------


@pytest.mark.parametrize(
    ("field", "forged"),
    [
        ("engine", "piper"),
        ("engine_version", "0.9.5"),
        ("g2p", "espeak"),
        ("g2p_version", "0.9.5"),
        ("model_repository", "hexgrad/Kokoro-100M"),
        ("model_revision", "0" * 40),
        ("model_weights_sha256", "0" * 64),
        ("model_config_sha256", "0" * 64),
        ("voice", "af_bella"),
        ("voice_pack_sha256", "0" * 64),
        ("lang_code", "b"),
        ("speed_percent", 150),
        ("sample_rate_hz", 22_050),
        ("channels", 2),
        ("seed", 1),
    ],
)
def test_each_voice_field_forged_individually_is_refused_by_the_cross_check(
    plan_ep1: dict[str, Any], sources_ep1: tuple[Any, ...], field: str, forged: Any
) -> None:
    """Each voice field forged individually is refused by the cross check."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice"][field] = forged
    with pytest.raises(ValueError):
        validate_episode_voice_plan_against_sources(broken, *sources_ep1)


# ---- capacity truth: recomputed from the real window, not merely plausible


def test_capacity_one_frame_too_small_is_refused(
    plan_ep1: dict[str, Any], sources_ep1: tuple[Any, ...]
) -> None:
    """Capacity one frame too small is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"][0]["capacity_samples"] -= 1_000
    broken["accounting"]["capacity_samples_total"] -= 1_000
    with pytest.raises(ValueError, match="proven true of the real window"):
        validate_episode_voice_plan_against_sources(broken, *sources_ep1)


def test_capacity_one_frame_too_large_is_refused(
    plan_ep1: dict[str, Any], sources_ep1: tuple[Any, ...]
) -> None:
    """Capacity one frame too large is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"][0]["capacity_samples"] += 1_000
    broken["accounting"]["capacity_samples_total"] += 1_000
    with pytest.raises(ValueError, match="proven true of the real window"):
        validate_episode_voice_plan_against_sources(broken, *sources_ep1)


def test_an_arbitrary_forged_capacity_is_refused(
    plan_ep1: dict[str, Any], sources_ep1: tuple[Any, ...]
) -> None:
    """An arbitrary forged capacity is refused."""
    from living_diorama.voice.voice_spec import MAX_VOICE_CAPACITY_SAMPLES

    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"][0]["capacity_samples"] = MAX_VOICE_CAPACITY_SAMPLES
    broken["accounting"]["capacity_samples_total"] += (
        MAX_VOICE_CAPACITY_SAMPLES - plan_ep1["voice_units"][0]["capacity_samples"]
    )
    # Standalone-valid (inside the plausibility rail); the cross-check alone
    # proves it false of the real window.
    with pytest.raises(ValueError, match="proven true of the real window"):
        validate_episode_voice_plan_against_sources(broken, *sources_ep1)


def test_a_forged_measured_samples_of_one_has_no_field_to_forge() -> None:
    """The structural closure of the V1 provenance blocker.

    There is no ``measured_samples`` field anywhere in the frozen key sets
    (see ``voice_schema_v1.VOICE_UNIT_KEYS``), so the exact V1 attack --
    replacing a real sample count with 1 and recomputing every digest -- has
    no field to act on. This test asserts the absence directly rather than
    exercising a refusal, because there is no forgery to construct.
    """
    from living_diorama.voice.voice_schema_v1 import VOICE_UNIT_KEYS

    assert "measured_samples" not in VOICE_UNIT_KEYS
    assert "measured_speech_samples" not in VOICE_UNIT_KEYS
    assert "fit_status" not in VOICE_UNIT_KEYS


# ---- reordered / duplicated / omitted / wrong-id voice units --------------


def test_reordered_voice_units_are_refused(
    plan_ep1: dict[str, Any], sources_ep1: tuple[Any, ...]
) -> None:
    """Reordered voice units are refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"][0], broken["voice_units"][1] = (
        broken["voice_units"][1],
        broken["voice_units"][0],
    )
    with pytest.raises(ValueError):
        validate_episode_voice_plan_against_sources(broken, *sources_ep1)


def test_a_wrong_unit_id_at_a_position_is_refused(
    plan_ep1: dict[str, Any], sources_ep1: tuple[Any, ...]
) -> None:
    """A wrong unit id at a position is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"][0]["unit_id"] = "unit_9999"
    with pytest.raises(ValueError):
        validate_episode_voice_plan_against_sources(broken, *sources_ep1)


def test_a_wrong_realization_id_at_a_position_is_refused(
    plan_ep1: dict[str, Any], sources_ep1: tuple[Any, ...]
) -> None:
    """A wrong realization id at a position is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"][0]["realization_id"] = "realization_9999"
    with pytest.raises(ValueError):
        validate_episode_voice_plan_against_sources(broken, *sources_ep1)


def test_a_wrong_window_id_at_a_position_is_refused(
    plan_ep1: dict[str, Any], sources_ep1: tuple[Any, ...]
) -> None:
    """A wrong window id at a position is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["voice_units"][0]["window_id"] = "window_9999"
    with pytest.raises(ValueError):
        validate_episode_voice_plan_against_sources(broken, *sources_ep1)


def test_wrong_accounting_is_refused(
    plan_ep1: dict[str, Any], sources_ep1: tuple[Any, ...]
) -> None:
    """Wrong accounting is refused."""
    broken = copy.deepcopy(plan_ep1)
    broken["accounting"]["voice_units_total"] = len(broken["voice_units"])
    broken["voice_units"].append(copy.deepcopy(broken["voice_units"][-1]))
    with pytest.raises(ValueError):
        validate_episode_voice_plan_against_sources(broken, *sources_ep1)


# ---- the final deterministic seal ------------------------------------------
#
# Unlike Phase 27 -- whose seal alone closes residual degrees of freedom such
# as hold placement and window geometry that no single named check enumerates
# field by field -- every degree of freedom in a voice plan (the narrator
# request, every voice unit's four identifiers, and every capacity_samples
# value) is already covered by an explicit named check above. A forgery this
# design's own named checks would let through, but the seal alone would
# catch, is therefore not constructible from a document alone: any document
# edit that survives every named check above IS the plan the planner would
# derive, by exhaustion of the fields those checks cover. The seal is still
# load-bearing structurally, and its failure branch is exercised directly
# below via a monkeypatched derivation, rather than by a document forgery
# that (as an earlier draft of this test mistakenly claimed) does not in
# fact reach it.


def test_a_re_parsed_but_byte_equal_plan_still_passes_the_seal(
    plan_ep1: dict[str, Any], sources_ep1: tuple[Any, ...]
) -> None:
    """A re parsed but byte equal plan still passes the seal."""
    import json

    reparsed = json.loads(json.dumps(plan_ep1))  # an independent copy, not the planner's object
    # Dict key order is irrelevant to canonical serialization (the codec
    # sorts keys), so this is not a forgery -- it proves the seal compares
    # real re-derived bytes against a document that was never the literal
    # Python object the planner produced, not merely `is`-identical dicts.
    assert validate_episode_voice_plan_against_sources(reparsed, *sources_ep1) == reparsed


def test_a_duplicated_voice_unit_is_refused_by_an_earlier_named_check(
    plan_ep1: dict[str, Any], sources_ep1: tuple[Any, ...]
) -> None:
    """A duplicated voice unit is refused by an earlier named check."""
    broken = copy.deepcopy(plan_ep1)
    # Refused by the per-position id-agreement check (§N.9): the duplicate's
    # unit_id/realization_id/window_id no longer agree with the position it
    # now sits at. This never reaches the seal -- named here honestly as an
    # earlier-check refusal, not a seal-only forgery.
    broken["voice_units"][1] = copy.deepcopy(broken["voice_units"][0])
    broken["voice_units"][1]["voice_unit_id"] = "voice_unit_0002"
    with pytest.raises(ValueError):
        validate_episode_voice_plan_against_sources(broken, *sources_ep1)
    assert dumps_canonical(broken, "voice plan") != dumps_canonical(plan_ep1, "voice plan")


def test_the_final_seal_refuses_a_derivation_byte_disagreement(
    plan_ep1: dict[str, Any],
    sources_ep1: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The final seal refuses a derivation byte disagreement.

    Every named check above is proven, individually, to let a fully valid
    canonical source chain through (``test_every_canonical_plan_is_source_verified``
    and the tests above). What has not yet been proven directly is that the
    seal itself is reached and actually enforced -- since no document
    forgery survives every earlier check while still disagreeing with the
    derivation (see the module comment above). This test proves the seal's
    own failure branch by making the derivation itself disagree: the
    cross-check's own bound reference to ``build_episode_voice_plan_bytes``
    is monkeypatched to return deterministic bytes that differ from the
    offered, otherwise-completely-valid plan. Every named check upstream of
    the seal still passes (the offered plan is genuinely valid), so a
    refusal here can only come from the seal comparison itself.
    """
    fake_bytes = b'{"not": "the real derivation"}\n'

    def fake_derivation(realization: object, presentation: object) -> bytes:
        return fake_bytes

    monkeypatch.setattr(
        "living_diorama.voice.voice_cross_check.build_episode_voice_plan_bytes",
        fake_derivation,
    )
    with pytest.raises(
        ValueError,
        match="does not equal the deterministic derivation",
    ):
        validate_episode_voice_plan_against_sources(plan_ep1, *sources_ep1)


# ---- standalone-valid-but-source-forged realization / presentation -------


def test_a_standalone_valid_but_source_forged_realization_is_refused(
    plan_ep1: dict[str, Any], sources_ep1: tuple[Any, ...]
) -> None:
    """A standalone valid but source forged realization is refused."""
    realization, presentation, delivery, narration, shots, story, export = sources_ep1
    forged_realization = copy.deepcopy(realization)
    forged_realization["realizations"][0]["realized_text"] = (
        "At tick 999, an entirely fabricated event occurred."
    )
    with pytest.raises(ValueError):
        validate_episode_voice_plan_against_sources(
            plan_ep1, forged_realization, presentation, delivery, narration, shots, story, export
        )


def test_a_standalone_valid_but_source_forged_presentation_is_refused(
    plan_ep1: dict[str, Any], sources_ep1: tuple[Any, ...]
) -> None:
    """A standalone valid but source forged presentation is refused."""
    realization, presentation, delivery, narration, shots, story, export = sources_ep1
    forged_presentation = copy.deepcopy(presentation)
    forged_presentation["windows"][0]["presentation_end_frame"] += 1_000
    forged_presentation["segments"][-1]["presentation_end_frame"] += 1_000
    forged_presentation["segments"][-1]["dwell_frames"] += 1
    forged_presentation["accounting"]["presentation_frames_total"] += 1_000
    with pytest.raises(ValueError):
        validate_episode_voice_plan_against_sources(
            plan_ep1, realization, forged_presentation, delivery, narration, shots, story, export
        )


# ---- wrong verification-only inputs ---------------------------------------


@pytest.mark.parametrize("field_index", [2, 3, 4, 5, 6])  # delivery/narration/shots/story/export
def test_a_verification_only_input_from_a_different_episode_is_refused(
    plan_ep1: dict[str, Any],
    sources_ep1: tuple[Any, ...],
    sources_ep2: tuple[Any, ...],
    field_index: int,
) -> None:
    """A verification only input from a different episode is refused."""
    args = list(sources_ep1)
    args[field_index] = sources_ep2[field_index]
    with pytest.raises(ValueError):
        validate_episode_voice_plan_against_sources(plan_ep1, *args)


# ---- the positive canonical divisibility path only ------------------------


def test_the_canonical_source_verified_fps_derives_the_correct_capacity(
    plan_ep1: dict[str, Any], sources_ep1: tuple[Any, ...]
) -> None:
    """The canonical source verified fps derives the correct capacity."""
    verified = validate_episode_voice_plan_against_sources(plan_ep1, *sources_ep1)
    _realization, presentation, *_ = sources_ep1
    assert presentation["timeline"]["fps"] == 24
    for unit in verified["voice_units"]:
        assert unit["capacity_samples"] % 1_000 == 0
