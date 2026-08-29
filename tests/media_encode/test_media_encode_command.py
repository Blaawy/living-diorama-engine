"""Phase 35 command construction and the preflight WAV law, pinned token by token.

The exact-tuple tests transcribe the frozen argv from the implementation; the
ordering-law tests then re-derive the same facts from index arithmetic so a single
transcription mistake cannot silently pass twice.
"""

import struct

import pytest

from living_diorama.media_encode import media_encode_command as cmd

ENCODE_KWARGS = {
    "fps": 24,
    "presentation_frames_total": 720,
    "audio_sample_rate_hz": 24000,
    "audio_channels": 1,
    "media_temp_filename": "episode_0000_to_0001.mp4.encoding",
}

PREFLIGHT_KWARGS = {
    "fps": 24,
    "presentation_frames_total": 720,
    "audio_sample_rate_hz": 24000,
    "audio_channels": 1,
}

FORBIDDEN_OPTIONS = ("-r", "-vsync", "-shortest", "-t", "-ss", "-y")


def _assert_output_side_laws(argv: tuple[str, ...], output_name: str) -> None:
    """Assert the frozen output-side laws shared by the encode and preflight argv."""
    assert argv[0] == "ffmpeg"
    assert argv.count("-i") == 2
    last_input_index = len(argv) - 1 - argv[::-1].index("-i")
    assert not any(token.startswith("-threads") for token in argv[:last_input_index])
    threads_index = argv.index("-threads:v")
    assert argv[threads_index + 1] == "0"
    assert argv.index("yuv420p") < threads_index < argv.index("-frames:v")
    assert argv[-3] == "-f"
    assert argv[-2] == "mp4"
    assert argv[-1] == "{STAGING}/" + output_name
    assert argv[argv.index("-frames:v") + 1] == "720"
    assert argv[argv.index("-ar") + 1] == "24000"
    assert argv[argv.index("-ac") + 1] == "1"
    assert not any(token in FORBIDDEN_OPTIONS for token in argv)


# -------------------------------------------------- build_media_encode_command


def test_build_media_encode_command_is_the_exact_frozen_tuple() -> None:
    """The whole real-encode argv, transcribed from the module's frozen order."""
    argv = cmd.build_media_encode_command(**ENCODE_KWARGS)
    assert argv == (
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "image2",
        "-framerate",
        "24",
        "-start_number",
        "1",
        "-i",
        "{ASSEMBLY_DIR}/presentation/frame_%07d.png",
        "-i",
        "{STAGING}/source_audio.wav.encoding",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-threads:v",
        "0",
        "-frames:v",
        "720",
        "-fps_mode:v",
        "passthrough",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "24000",
        "-ac",
        "1",
        "-map_metadata",
        "-1",
        "-fflags",
        "+bitexact",
        "-flags:v",
        "+bitexact",
        "-flags:a",
        "+bitexact",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        "{STAGING}/episode_0000_to_0001.mp4.encoding",
    )


def test_encode_argv_starts_with_ffmpeg() -> None:
    """The executable is the first token."""
    assert cmd.build_media_encode_command(**ENCODE_KWARGS)[0] == "ffmpeg"


def test_encode_argv_has_exactly_two_input_flags() -> None:
    """Exactly one video input and one audio input; nothing else is read."""
    argv = cmd.build_media_encode_command(**ENCODE_KWARGS)
    assert argv.count("-i") == 2


def test_no_thread_option_before_the_last_input_flag() -> None:
    """V61: FFmpeg option scoping is file-sensitive; no -threads* precedes the last -i."""
    argv = cmd.build_media_encode_command(**ENCODE_KWARGS)
    last_input_index = len(argv) - 1 - argv[::-1].index("-i")
    assert not any(token.startswith("-threads") for token in argv[:last_input_index])


def test_the_one_threads_option_is_output_scoped() -> None:
    """Exactly one -threads:v 0, after yuv420p and before -frames:v."""
    argv = cmd.build_media_encode_command(**ENCODE_KWARGS)
    assert argv.count("-threads:v") == 1
    threads_index = argv.index("-threads:v")
    assert argv[threads_index + 1] == "0"
    assert argv.index("yuv420p") < threads_index < argv.index("-frames:v")


def test_format_mp4_is_immediately_before_the_final_token() -> None:
    """Container is declared explicitly, never inferred from the temp's name."""
    argv = cmd.build_media_encode_command(**ENCODE_KWARGS)
    assert argv[-3] == "-f"
    assert argv[-2] == "mp4"


def test_encode_final_token_is_the_staging_temp() -> None:
    """The output temporary lives under the staging root, by token."""
    argv = cmd.build_media_encode_command(**ENCODE_KWARGS)
    assert argv[-1] == "{STAGING}/episode_0000_to_0001.mp4.encoding"


def test_encode_frames_input_token() -> None:
    """The frames input is the assembly root's presentation glob, by token."""
    argv = cmd.build_media_encode_command(**ENCODE_KWARGS)
    assert argv[argv.index("-i") + 1] == "{ASSEMBLY_DIR}/presentation/frame_%07d.png"


def test_encode_audio_input_token() -> None:
    """The audio snapshot input lives under the staging root, by token."""
    argv = cmd.build_media_encode_command(**ENCODE_KWARGS)
    inputs = [i for i, token in enumerate(argv) if token == "-i"]
    assert argv[inputs[1] + 1] == "{STAGING}/source_audio.wav.encoding"


def test_encode_argv_never_carries_the_absent_options() -> None:
    """-r, -vsync, -shortest, -t, -ss and -y are decision-bearing absences."""
    argv = cmd.build_media_encode_command(**ENCODE_KWARGS)
    assert not any(token in FORBIDDEN_OPTIONS for token in argv)


def test_encode_derived_integers_are_rendered_at_the_right_flags() -> None:
    """Every authoritative integer appears as its exact decimal string."""
    argv = cmd.build_media_encode_command(**ENCODE_KWARGS)
    assert argv[argv.index("-framerate") + 1] == "24"
    assert argv[argv.index("-frames:v") + 1] == "720"
    assert argv[argv.index("-ar") + 1] == "24000"
    assert argv[argv.index("-ac") + 1] == "1"


def test_encode_refuses_zero_fps() -> None:
    """A zero fps is not a projection."""
    with pytest.raises(ValueError):
        cmd.build_media_encode_command(**{**ENCODE_KWARGS, "fps": 0})


def test_encode_refuses_a_bool_fps() -> None:
    """Bool is not an int for the geometry."""
    with pytest.raises(TypeError):
        cmd.build_media_encode_command(**{**ENCODE_KWARGS, "fps": True})


def test_encode_refuses_an_empty_temp_filename() -> None:
    """The output temporary's name must not be empty."""
    with pytest.raises(ValueError):
        cmd.build_media_encode_command(**{**ENCODE_KWARGS, "media_temp_filename": ""})


# ------------------------------------------------------ build_preflight_command


def test_build_preflight_command_obeys_the_output_side_laws() -> None:
    """Preflight shares the byte-identical output profile of the real encode."""
    argv = cmd.build_preflight_command(**PREFLIGHT_KWARGS)
    _assert_output_side_laws(argv, "preflight.mp4.encoding")


def test_preflight_video_input_is_the_lavfi_testsrc2() -> None:
    """Tiny real-geometry video: the counts, not pixels, carry the geometry."""
    argv = cmd.build_preflight_command(**PREFLIGHT_KWARGS)
    assert argv[argv.index("-i") + 1] == "testsrc2=size=64x64:rate=24"


def test_preflight_audio_input_is_the_staging_preflight_wav() -> None:
    """The executor-built preflight WAV is read from staging, by token."""
    argv = cmd.build_preflight_command(**PREFLIGHT_KWARGS)
    inputs = [i for i, token in enumerate(argv) if token == "-i"]
    assert argv[inputs[1] + 1] == "{STAGING}/preflight_audio.wav.encoding"


def test_preflight_output_is_staging_preflight_mp4_with_explicit_format() -> None:
    """'-f mp4' sits immediately before the preflight output temporary."""
    argv = cmd.build_preflight_command(**PREFLIGHT_KWARGS)
    assert argv[-1] == "{STAGING}/preflight.mp4.encoding"
    assert argv[-3] == "-f"
    assert argv[-2] == "mp4"
    assert argv[argv.index("-frames:v") + 1] == "720"


# ------------------------------------------------- probe and decode commands


def test_build_probe_command_is_the_exact_frozen_tuple() -> None:
    """The whole probe argv, stdin-captured, verbatim."""
    assert cmd.build_probe_command() == (
        "ffprobe",
        "-hide_banner",
        "-loglevel",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-count_frames",
        "-i",
        "pipe:0",
    )


def test_build_decode_command_is_the_exact_frozen_tuple() -> None:
    """The whole decode argv, verbatim."""
    assert cmd.build_decode_command() == (
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-map",
        "0:a:0",
        "-vn",
        "-c:a",
        "pcm_s16le",
        "-f",
        "s16le",
        "pipe:1",
    )


def test_decode_command_has_no_ar_no_ac_and_ends_on_stdout_pipe() -> None:
    """The stream's own rate and channel count stay authoritative; stdout is pipe:1."""
    argv = cmd.build_decode_command()
    assert "-ar" not in argv
    assert "-ac" not in argv
    assert argv[-1] == "pipe:1"


# ----------------------------------------------------------- substitute_paths


def test_substitute_paths_replaces_both_tokens_in_every_element() -> None:
    """Frames tokens resolve to the assembly root; audio and output to staging."""
    argv = cmd.build_media_encode_command(**ENCODE_KWARGS)
    resolved = cmd.substitute_paths(argv, assembly_dir="/srv/assembly", staging_dir="/srv/staging")
    assert resolved == [
        token.replace("{ASSEMBLY_DIR}", "/srv/assembly").replace("{STAGING}", "/srv/staging")
        for token in argv
    ]
    assert "/srv/assembly/presentation/frame_%07d.png" in resolved
    assert "{STAGING}" not in " ".join(resolved)


def test_substitute_paths_leaves_unknown_token_elements_untouched() -> None:
    """Elements carrying no declared token pass through byte-for-byte."""
    resolved = cmd.substitute_paths(
        ("hello", "{OTHER}/x", "ffmpeg"), assembly_dir="/a", staging_dir="/s"
    )
    assert resolved == ["hello", "{OTHER}/x", "ffmpeg"]


def test_substitute_paths_refuses_a_non_tuple_argv() -> None:
    """The canonical argv is a tuple, exactly."""
    with pytest.raises(TypeError):
        cmd.substitute_paths(["ffmpeg"], assembly_dir="/a", staging_dir="/s")


# --------------------------------------------------------- preflight_wav_bytes


def test_preflight_wav_bytes_length_and_magic() -> None:
    """44 header bytes, RIFF magic, WAVE at 8, then exactly the silence."""
    wav = cmd.preflight_wav_bytes(24000, 1, 720000)
    assert len(wav) == 44 + 1_440_000
    assert wav.startswith(b"RIFF")
    assert wav[8:12] == b"WAVE"


def test_preflight_wav_bytes_header_fields() -> None:
    """data_size, byte_rate and block_align are the locked little-endian fields."""
    wav = cmd.preflight_wav_bytes(24000, 1, 720000)
    assert struct.unpack("<I", wav[40:44])[0] == 1_440_000
    assert struct.unpack("<I", wav[28:32])[0] == 48000
    assert struct.unpack("<H", wav[32:34])[0] == 2


def test_preflight_wav_bytes_matches_the_frozen_phase_29_oracle() -> None:
    """Byte-equality with voice_execution.canonical_wav_bytes for the same silence."""
    from living_diorama import voice_execution

    silence = b"\x00" * 1_440_000
    assert cmd.preflight_wav_bytes(24000, 1, 720000) == voice_execution.canonical_wav_bytes(
        silence, sample_rate_hz=24000, channels=1
    )


def test_preflight_wav_bytes_refuses_zero_samples() -> None:
    """Zero samples is not a WAV payload."""
    with pytest.raises(ValueError):
        cmd.preflight_wav_bytes(24000, 1, 0)


def test_preflight_wav_bytes_refuses_a_bool_channel_count() -> None:
    """Bool is not an int for the geometry."""
    with pytest.raises(TypeError):
        cmd.preflight_wav_bytes(24000, True, 720000)
