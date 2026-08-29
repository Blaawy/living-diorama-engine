"""SRT writer: the frozen grammar, whole, proven byte-for-byte.

``serialize_srt_bytes`` re-expresses one locked Phase 32 caption plan under
``caption_timestamp_policy_v1`` (``offset * 1000 // fps``, floor) and carries
every sentence verbatim or refuses the whole serialization. The suite builds
synthetic P32-valid plans locally -- positional ids ``caption_``/``unit_``/
``realization_``/``window_`` ``%04d``, closing accounting, baseline ep0 or
transition ep1, fps 24 -- and asserts exact bytes, the encoding rails, the
carriage law's refusals and positives, and the schema-first refusal order.
"""

import pytest

from living_diorama.caption_serialization.caption_serialization_spec import (
    CaptionSerializationRefused,
    require_carriable_caption_text,
)
from living_diorama.caption_serialization.srt_writer import serialize_srt_bytes


def _make_caption_plan(
    cues,
    *,
    mode="baseline",
    episode=0,
    previous_episode=None,
    fps=24,
    presentation_frames_total=None,
):
    """Build one P32-valid Episode Caption Plan document from (start, end, text) cues."""
    captions = []
    caption_frames_total = 0
    last_end = 0
    for position, (start, end, text) in enumerate(cues, start=1):
        captions.append(
            {
                "caption_id": f"caption_{position:04d}",
                "unit_id": f"unit_{position:04d}",
                "realization_id": f"realization_{position:04d}",
                "window_id": f"window_{position:04d}",
                "caption_text": text,
                "presentation_start_frame": start,
                "presentation_end_frame": end,
            }
        )
        caption_frames_total += end - start + 1
        last_end = end
    total = presentation_frames_total if presentation_frames_total is not None else last_end
    return {
        "format": "living_diorama_episode_caption_plan",
        "schema_version": 1,
        "policy": "caption_policy_v1",
        "source": {
            "mode": mode,
            "episode": episode,
            "previous_episode": previous_episode,
            "presentation_plan_sha256": "0" * 64,
            "realization_plan_sha256": "0" * 64,
            "presentation_schema_version": 1,
            "realization_schema_version": 1,
        },
        "clock": {"fps": fps, "presentation_frames_total": total},
        "captions": captions,
        "accounting": {
            "captions_total": len(captions),
            "caption_frames_total": caption_frames_total,
            "uncaptioned_frames_total": total - caption_frames_total,
        },
    }


def _ep1_three_cue_plan():
    """Return the tight ep1 three-cue plan over frames [25,168],[169,528],[529,672]."""
    return _make_caption_plan(
        [(25, 168, "first."), (169, 528, "second."), (529, 672, "third.")],
        mode="transition",
        episode=1,
        previous_episode=0,
        presentation_frames_total=720,
    )


def _carried_text_line(output: bytes) -> str:
    """Return the one carried text line of a single-cue serialization."""
    return output.decode("utf-8").splitlines()[-1]


def test_one_cue_exact_bytes() -> None:
    """One cue serializes to the exact frozen bytes."""
    plan = _make_caption_plan([(25, 168, "the north gate holds.")])
    output = serialize_srt_bytes(plan)
    assert output == b"1\n00:00:01,000 --> 00:00:07,000\nthe north gate holds.\n"
    assert output.endswith(b"\n")
    assert not output.endswith(b"\n\n")


def test_three_cue_ep1_exact_full_file() -> None:
    """Three tight ep1 cues serialize to the hand-assembled full file exactly."""
    output = serialize_srt_bytes(_ep1_three_cue_plan())
    expected = (
        b"1\n00:00:01,000 --> 00:00:07,000\nfirst.\n"
        b"\n"
        b"2\n00:00:07,000 --> 00:00:22,000\nsecond.\n"
        b"\n"
        b"3\n00:00:22,000 --> 00:00:28,000\nthird.\n"
    )
    assert output == expected
    assert output.count(b"\n\n") == 2  # one blank line BETWEEN blocks only
    assert output.endswith(b"\n")
    assert not output.endswith(b"\n\n")


def test_encoding_rails_no_bom_lf_only_utf8() -> None:
    """Output carries no BOM, LF only, and decodes as UTF-8."""
    output = serialize_srt_bytes(_ep1_three_cue_plan())
    assert not output.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in output
    assert output.decode("utf-8")


@pytest.mark.parametrize(
    "text",
    [
        "line one\nline two",
        "line one\rline two",
        "line one\r\nline two",
        "nul\x00byte",
        "tab\there",
        "line\u2028separator",
        "line\u2029separator",
    ],
)
def test_refuses_text_the_grammar_cannot_carry(text: str) -> None:
    """Text with a control byte or Unicode line separator refuses the whole plan."""
    plan = _make_caption_plan([(25, 168, text)])
    with pytest.raises(CaptionSerializationRefused, match="cannot be carried verbatim"):
        serialize_srt_bytes(plan)


def test_refuses_timing_like_text_for_arrow() -> None:
    """Text that looks like a timing line is refused only for its arrow."""
    plan = _make_caption_plan([(25, 168, "00:00:01,000 --> 00:00:02,000")])
    with pytest.raises(CaptionSerializationRefused, match="cannot be carried verbatim"):
        serialize_srt_bytes(plan)


@pytest.mark.parametrize(
    "text",
    [
        "north\ufeffgate",
        "\U0001f30d",
        "שלום",
        "e\u0301",
        "<tag> & entity",
    ],
)
def test_carries_text_verbatim(text: str) -> None:
    """Carried text appears byte-for-byte inside the output."""
    output = serialize_srt_bytes(_make_caption_plan([(25, 168, text)]))
    assert _carried_text_line(output) == text
    assert text.encode("utf-8") in output


def test_carries_index_looking_text() -> None:
    """Text that looks like a cue number is carried verbatim."""
    output = serialize_srt_bytes(_make_caption_plan([(25, 168, "42")]))
    assert _carried_text_line(output) == "42"


def test_carries_timestamp_without_arrow() -> None:
    """A timestamp-like string without the arrow is carried verbatim."""
    output = serialize_srt_bytes(_make_caption_plan([(25, 168, "00:00:01,000")]))
    assert _carried_text_line(output) == "00:00:01,000"


def test_require_carriable_refuses_empty_text_directly() -> None:
    """The defensive carriage law refuses empty text on its own."""
    with pytest.raises(CaptionSerializationRefused, match="cannot be carried verbatim"):
        require_carriable_caption_text("", "caption 1 text")


def test_empty_text_plan_fails_schema_before_writer_law() -> None:
    """A plan with empty text fails the P32 schema before the writer's law."""
    plan = _make_caption_plan([(25, 168, "")])
    with pytest.raises(ValueError, match="must not be empty"):
        serialize_srt_bytes(plan)


def test_serialize_refuses_non_plan_document() -> None:
    """Serializing a non-plan document raises through the P32 schema."""
    with pytest.raises((TypeError, ValueError)):
        serialize_srt_bytes({})


def test_forged_non_canonical_cue_order_refuses_at_schema() -> None:
    """A forged plan whose cues do not follow narration order refuses at the schema."""
    plan = _make_caption_plan([(25, 168, "first."), (169, 528, "second.")])
    plan["captions"] = [plan["captions"][1], plan["captions"][0]]
    for position, cue in enumerate(plan["captions"], start=1):
        cue["caption_id"] = f"caption_{position:04d}"
        cue["realization_id"] = f"realization_{position:04d}"
        cue["unit_id"] = f"unit_{position:04d}"
        cue["window_id"] = f"window_{position:04d}"
    with pytest.raises(ValueError, match="does not follow the previous cue's end frame"):
        serialize_srt_bytes(plan)


def test_serializing_twice_is_byte_identical() -> None:
    """Serializing the same plan twice yields identical bytes."""
    plan = _ep1_three_cue_plan()
    assert serialize_srt_bytes(plan) == serialize_srt_bytes(plan)
