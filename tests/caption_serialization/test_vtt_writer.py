"""WebVTT writer tests: the frozen ``serialize_vtt_bytes`` grammar (matrix S25-S29).

Proves the exact bytes of the baseline single-cue and transition three-cue
artifacts, the shared representation laws (period milliseconds, long-form
two-digit hours, no cue identifiers, no BOM, LF only, UTF-8, the header law)
and the shared carriage laws (refusals and verbatim carry) of the Phase 34
caption serialization.
"""

import re

import pytest

from living_diorama.caption_serialization.caption_serialization_spec import (
    CaptionSerializationRefused,
)
from living_diorama.caption_serialization.vtt_writer import serialize_vtt_bytes

_LONG_FORM_TIMING = re.compile(r"\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}")


def _build_plan(
    cues: list[tuple[int, int, str]],
    *,
    mode: str,
    episode: int,
    previous_episode: int | None,
    fps: int = 24,
) -> dict:
    """Return a Phase 32 valid caption plan document carrying the given cues."""
    captions = []
    caption_frames_total = 0
    for position, (start_frame, end_frame, text) in enumerate(cues, start=1):
        captions.append(
            {
                "caption_id": f"caption_{position:04d}",
                "unit_id": f"unit_{position:04d}",
                "realization_id": f"realization_{position:04d}",
                "window_id": f"window_{position:04d}",
                "presentation_start_frame": start_frame,
                "presentation_end_frame": end_frame,
                "caption_text": text,
            }
        )
        caption_frames_total += end_frame - start_frame + 1
    presentation_frames_total = cues[-1][1]
    return {
        "format": "living_diorama_episode_caption_plan",
        "schema_version": 1,
        "policy": "caption_policy_v1",
        "source": {
            "mode": mode,
            "episode": episode,
            "previous_episode": previous_episode,
            "presentation_schema_version": 1,
            "realization_schema_version": 1,
            "presentation_plan_sha256": "0" * 64,
            "realization_plan_sha256": "0" * 64,
        },
        "clock": {"fps": fps, "presentation_frames_total": presentation_frames_total},
        "captions": captions,
        "accounting": {
            "captions_total": len(cues),
            "caption_frames_total": caption_frames_total,
            "uncaptioned_frames_total": presentation_frames_total - caption_frames_total,
        },
    }


def _ep0_single_cue_plan(text: str = "the north gate holds.") -> dict:
    """Return a baseline episode 0 plan with one cue over window [25, 168]."""
    return _build_plan([(25, 168, text)], mode="baseline", episode=0, previous_episode=None)


def _ep1_three_cue_plan() -> dict:
    """Return a transition episode 1 plan with three tight cues."""
    return _build_plan(
        [(25, 168, "<t1>"), (169, 528, "<t2>"), (529, 672, "<t3>")],
        mode="transition",
        episode=1,
        previous_episode=0,
    )


def _serialize_ep0() -> bytes:
    """Serialize the baseline single cue plan."""
    return serialize_vtt_bytes(_ep0_single_cue_plan())


def _serialize_ep1() -> bytes:
    """Serialize the transition three cue plan."""
    return serialize_vtt_bytes(_ep1_three_cue_plan())


def _timing_lines(output: bytes) -> list[str]:
    """Return the serialized timing lines, one per cue, in plan order."""
    return [line for line in output.decode("utf-8").splitlines() if "-->" in line]


def _to_ms(timestamp: str) -> int:
    """Return the millisecond count of one ``HH:MM:SS.mmm`` timestamp."""
    hours, minutes, seconds = timestamp.split(":")
    seconds, millis = seconds.split(".")
    return int(hours) * 3_600_000 + int(minutes) * 60_000 + int(seconds) * 1_000 + int(millis)


def test_serialize_vtt_bytes_returns_bytes() -> None:
    """Serialize VTT bytes returns bytes."""
    assert type(_serialize_ep0()) is bytes


def test_single_cue_plan_exact_bytes() -> None:
    """Single cue plan serializes to the exact frozen bytes."""
    assert _serialize_ep0() == (b"WEBVTT\n\n00:00:01.000 --> 00:00:07.000\nthe north gate holds.\n")


def test_single_cue_plan_single_terminal_lf() -> None:
    """Single cue plan carries exactly one terminal LF and no LF LF tail."""
    output = _serialize_ep0()
    assert output.endswith(b"\n")
    assert not output.endswith(b"\n\n")
    assert output == output.rstrip(b"\n") + b"\n"


def test_three_cue_plan_exact_bytes() -> None:
    """Three cue plan serializes to the exact full file bytes."""
    assert _serialize_ep1() == (
        b"WEBVTT\n\n"
        b"00:00:01.000 --> 00:00:07.000\n<t1>\n"
        b"\n"
        b"00:00:07.000 --> 00:00:22.000\n<t2>\n"
        b"\n"
        b"00:00:22.000 --> 00:00:28.000\n<t3>\n"
    )


def test_period_millisecond_separator_everywhere() -> None:
    """Period millisecond separator everywhere: no comma in any timing line."""
    for output in (_serialize_ep0(), _serialize_ep1()):
        assert b"," not in output
        assert b"00:00:01,000" not in output
        assert b"00:00:01.000" in output


def test_long_form_two_digit_hours_timestamps() -> None:
    """Long form two digit hours timestamps: no short MM:SS.mmm line."""
    for output in (_serialize_ep0(), _serialize_ep1()):
        timing_lines = _timing_lines(output)
        assert timing_lines
        for line in timing_lines:
            assert line.startswith("00:")
            assert _LONG_FORM_TIMING.fullmatch(line)


def test_no_cue_identifier_lines() -> None:
    """No cue identifier lines: each timing line follows a blank line."""
    for output in (_serialize_ep0(), _serialize_ep1()):
        lines = output.decode("utf-8").split("\n")
        timing_indexes = [i for i, line in enumerate(lines) if "-->" in line]
        assert timing_indexes
        for index in timing_indexes:
            assert lines[index - 1] == ""


def test_no_byte_order_mark() -> None:
    """No byte order mark: artifacts open with the magic, never a BOM."""
    for output in (_serialize_ep0(), _serialize_ep1()):
        assert not output.startswith(b"\xef\xbb\xbf")


def test_lf_only_structure() -> None:
    """LF only structure: no carriage return anywhere in the bytes."""
    for output in (_serialize_ep0(), _serialize_ep1()):
        assert b"\r" not in output


def test_utf8_round_trip() -> None:
    """UTF-8 round trip: decoding and re-encoding reproduces the bytes."""
    for output in (_serialize_ep0(), _serialize_ep1()):
        assert output.decode("utf-8").encode("utf-8") == output


def test_header_exact_and_appears_once() -> None:
    """Header law: every artifact opens with WEBVTT plus one blank line, once."""
    for output in (_serialize_ep0(), _serialize_ep1()):
        assert output.startswith(b"WEBVTT\n\n")
        assert output.count(b"WEBVTT") == 1


@pytest.mark.parametrize(
    "text",
    [
        "line\nbreak",
        "line\rbreak",
        "nul\x00byte",
        "tab\there",
        "sep\u2028here",
        "sep\u2029here",
        "a --> b",
    ],
    ids=[
        "newline",
        "carriage-return",
        "nul",
        "tab",
        "line-separator",
        "paragraph-separator",
        "cue-timing-arrow",
    ],
)
def test_cue_text_refused_when_not_carriable_verbatim(text: str) -> None:
    """Cue text refused when not carriable verbatim.

    Each refusal character is embedded in otherwise plain text because a
    whitespace-only sentence is refused earlier by the Phase 32 schema
    (``require_text``); the carriage law is only reachable with surrounding
    text, and it is the carriage law under test here.
    """
    plan = _ep0_single_cue_plan(text)
    with pytest.raises(CaptionSerializationRefused, match="cannot be carried verbatim"):
        serialize_vtt_bytes(plan)


def test_html_like_text_carried_verbatim() -> None:
    """HTML like text carried verbatim: no entity escaping."""
    output = serialize_vtt_bytes(_ep0_single_cue_plan("<i>not italics</i>"))
    assert b"<i>not italics</i>" in output
    assert b"&amp;" not in output


def test_ampersand_text_carried_verbatim() -> None:
    """Ampersand text carried verbatim: AT and T stays one token."""
    output = serialize_vtt_bytes(_ep0_single_cue_plan("AT&T"))
    assert b"AT&T" in output
    assert b"&amp;" not in output


def test_internal_bom_carried_verbatim() -> None:
    """Internal BOM carried verbatim: a mid text U+FEFF is not a leading BOM."""
    output = serialize_vtt_bytes(_ep0_single_cue_plan("north\ufeffgate"))
    assert b"\xef\xbb\xbf" in output
    assert b"&amp;" not in output


def test_astral_emoji_carried_verbatim() -> None:
    """Astral emoji carried verbatim: a four byte UTF-8 sequence is unescaped."""
    output = serialize_vtt_bytes(_ep0_single_cue_plan("\U0001f600"))
    assert b"\xf0\x9f\x98\x80" in output
    assert b"&amp;" not in output


def test_timing_starts_strictly_increase_and_ends_follow() -> None:
    """Timing starts strictly increase and each end follows its start."""
    starts: list[int] = []
    ends: list[int] = []
    for line in _timing_lines(_serialize_ep1()):
        start_text, end_text = line.split(" --> ")
        starts.append(_to_ms(start_text))
        ends.append(_to_ms(end_text))
    assert len(starts) == 3
    assert all(a < b for a, b in zip(starts, starts[1:], strict=False))
    assert all(end > start for start, end in zip(starts, ends, strict=True))


def test_empty_dict_plan_refused() -> None:
    """Empty dict plan refused."""
    with pytest.raises(ValueError):
        serialize_vtt_bytes({})


def test_determinism_smoke() -> None:
    """Determinism smoke: two serializations of one plan are byte identical."""
    plan = _ep1_three_cue_plan()
    assert serialize_vtt_bytes(plan) == serialize_vtt_bytes(plan)
