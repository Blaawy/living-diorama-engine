r"""Project one audited media assembly into its final watchable episode file.

    python media/ffmpeg/scripts/encode_episode.py \
        --assembly-dir episode_0004_baseline_assembly \
        --captions-dir episode_0004_baseline_captions \
        --output-root media/ \
        [--ffmpeg /path/to/ffmpeg] \
        [--ffprobe /path/to/ffprobe]

THE FFMPEG EXECUTOR PROJECTS LOCKED TRUTH. IT DECIDES NOTHING.

This script is the ONE approved subprocess site of the whole repository's media side:
nothing in :mod:`living_diorama.media_encode` spawns anything, and this module is the
only place that may. The one tool-spawning primitive is :func:`_default_runner`, and
``subprocess`` is imported INSIDE its body -- the deferred-import law of the Phase 29
executor -- so this module imports, and is driven by a fake runner in tests, without
ever loading the subprocess machinery. Every orchestration function takes an explicit
``runner`` callable so tests inject fakes; no function here ever calls a tool through
any other path.

Execution is offline only. No download path exists anywhere in this module, no
``urllib``/``socket``/``http`` import is permitted, and a missing tool or a missing
capability is refused -- never fetched, never substituted, never downgraded. The
selected build must report the FFmpeg 9 stable release family and must list exactly the
codecs, muxer and demuxers the reviewed profile requires.

CLASS-B HONESTY: the MP4 is an attested viewing projection whose bytes are
digest-recorded at production and re-verified on every read; cross-machine byte
identity is deliberately not claimed. The manifest and every carried byte are exact,
and the decisive audio-length closure is exact to the sample: the captured media must
decode back to precisely the locked ``audio_samples_total``.

``main`` is the one authoritative execution entrypoint. It locates and gates the two
tools, runs the upstream audits, single-captures every bound byte, verifies the joins,
runs the real-geometry preflight self-test, performs the real encode, re-verifies
stability, proves the probe and decode laws on the one captured observation, and only
then publishes the final-media directory through the staging-side publisher. A
re-run of an already-complete episode is a verified no-op: the existing directory is
re-audited, its media re-probed and re-decoded against the CURRENT authorities, and
nothing is rewritten.
"""

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final, cast

from living_diorama.caption_serialization.caption_serialization_audit import (
    audit_caption_serialization_directory,
)
from living_diorama.caption_serialization.caption_serialization_spec import (
    CAPTION_SERIALIZATION_MANIFEST_FILENAME,
)
from living_diorama.media_assembly.media_assembly_audit import audit_media_assembly_directory
from living_diorama.media_assembly.media_assembly_spec import (
    MEDIA_ASSEMBLY_MANIFEST_FILENAME,
    RENDER_MANIFEST_COPY_FILENAME,
    episode_audio_relative_path,
)
from living_diorama.media_encode import (
    MEDIA_ENCODE_MANIFEST_FILENAME,
    MediaEncodeDirectoryRefused,
    build_decode_command,
    build_episode_media_encode_manifest_bytes,
    build_media_encode_command,
    build_preflight_command,
    build_probe_command,
    media_encode_id,
    normalize_probe_document,
    parse_version_first_line,
    preflight_wav_bytes,
    require_capability,
    require_encode_sources_join,
    require_stream_facts,
    substitute_paths,
    validate_episode_media_encode_manifest,
)
from living_diorama.media_encode import media_encode_publisher as publisher
from living_diorama.media_encode.media_encode_audit import (
    _audit_media_encode_directory_with_observation,
)
from living_diorama.media_encode.media_encode_spec import (
    PREFLIGHT_AUDIO_FILENAME,
    PREFLIGHT_MEDIA_FILENAME,
    media_temp_filename,
)
from living_diorama.media_encode.media_encode_staging import (
    discard_owned_staging,
    fsync_file,
    read_file_bytes,
    remove_owned_temporary,
    write_atomically,
)
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.render_execution.render_execution_schema_v1 import (
    validate_episode_render_manifest,
)
from living_diorama.render_execution.render_execution_spec import render_profile_document

_PREFLIGHT_VIDEO_WIDTH: Final = 64
_PREFLIGHT_VIDEO_HEIGHT: Final = 64
"""The self-test's tiny video dimensions: real geometry lives in the counts, not pixels."""


class EncodeExecutionRefused(ValueError):
    """A tool, a source, a probe fact or a decoded measurement refuses this encode.

    Subclasses ``ValueError`` so the publisher's ``HANDLED_REFUSALS`` covers it and a
    refusal discards this run's own staging before propagating.
    """


RunnerResult = tuple[int, bytes, bytes]
"""One tool invocation's result: ``(returncode, stdout, stderr)``, binary."""

Runner = Callable[[list[str], bytes | None], RunnerResult]
"""The runner seam every orchestration function accepts, so tests inject fakes."""


def _default_runner(argv: list[str], stdin_bytes: bytes | None) -> RunnerResult:
    """The one real subprocess site of the media side; ``subprocess`` is imported here.

    The deferred-import law: importing this module never imports ``subprocess``; only
    actually running a tool does. ``capture_output=True`` keeps stdout and stderr as
    binary, and ``input=stdin_bytes`` feeds the single captured observation through
    ``pipe:0`` exactly as the probe and decode commands declare.
    """
    import subprocess

    completed = subprocess.run(argv, input=stdin_bytes, capture_output=True)
    return (completed.returncode, completed.stdout, completed.stderr)


def _locate(tool: str, explicit: str | None, env_name: str, environ: Mapping[str, str]) -> str:
    """Return one tool's executable path: explicit flag, then env var, then PATH.

    A provided path that does not exist is refused, never silently skipped; a missing
    tool everywhere is refused, never downloaded.

    Raises:
        EncodeExecutionRefused: If no usable executable can be located.
    """
    if explicit is not None:
        path = Path(explicit)
        if not path.is_file():
            raise EncodeExecutionRefused(
                f"the --{tool} path {explicit!r} does not exist or is not a file"
            )
        return str(path)
    candidate = environ.get(env_name)
    if candidate:
        path = Path(candidate)
        if not path.is_file():
            raise EncodeExecutionRefused(
                f"{env_name}={candidate!r} does not exist or is not a file"
            )
        return str(path)
    import shutil  # deferred like subprocess: outside the frozen module-scope list

    on_path = shutil.which(tool)
    if on_path is not None:
        return on_path
    raise EncodeExecutionRefused(
        f"no {tool} executable found; pass --{tool}, set {env_name}, or put {tool} on "
        "PATH (FFmpeg 9.x required)"
    )


def _run_or_refuse(runner: Runner, argv: list[str], stdin_bytes: bytes | None, what: str) -> bytes:
    """Run one invocation through the runner, returning its stdout on exit 0.

    Raises:
        EncodeExecutionRefused: If the invocation exits nonzero (with the stderr tail,
            last 400 characters, decoded ``errors=replace``) or is terminated by a
            signal (negative returncode).
    """
    returncode, stdout, stderr = runner(argv, stdin_bytes)
    if returncode == 0:
        return stdout
    if returncode < 0:
        raise EncodeExecutionRefused(
            f"{what} terminated by signal {-returncode}; expected exit code 0"
        )
    tail = stderr.decode("utf-8", errors="replace")[-400:]
    raise EncodeExecutionRefused(f"{what} exited with code {returncode}, expected 0: {tail}")


def _tool_version_line(runner: Runner, tool_path: str, tool: str) -> str:
    """Run ``<tool> -version`` and return the gated first line the manifest records."""
    stdout = _run_or_refuse(runner, [tool_path, "-version"], None, f"{tool} version check")
    return parse_version_first_line(stdout.decode("utf-8", errors="replace"), tool)


def _require_tool_capabilities(runner: Runner, tool_path: str) -> None:
    """Refuse unless the located ffmpeg lists every reviewed capability as its own token."""
    encoders = _run_or_refuse(runner, [tool_path, "-encoders"], None, "encoder listing").decode(
        "utf-8", errors="replace"
    )
    require_capability(encoders, "libx264", "encoders")
    require_capability(encoders, "aac", "encoders")
    muxers = _run_or_refuse(runner, [tool_path, "-muxers"], None, "muxer listing").decode(
        "utf-8", errors="replace"
    )
    require_capability(muxers, "mp4", "muxers")
    demuxers = _run_or_refuse(runner, [tool_path, "-demuxers"], None, "demuxer listing").decode(
        "utf-8", errors="replace"
    )
    require_capability(demuxers, "image2", "demuxers")
    require_capability(demuxers, "wav", "demuxers")
    require_capability(demuxers, "lavfi", "demuxers")


def _capture_canonical(path: Path, description: str) -> tuple[bytes, dict[str, object]]:
    """Read one canonical document ONCE, returning ``(bytes, parsed document)``.

    The bytes are the single captured observation and the only authority thereafter;
    the digest-bound manifest builders require exactly this canonical byte form, so
    the round-trip check runs at capture time for a clear refusal.
    """
    raw = read_file_bytes(path)
    document = loads_canonical(raw, description)
    if raw != dumps_canonical(document, description):
        raise ValueError(
            f"{description} at {path} is not canonical bytes. This execution binds the "
            "digest of every document it reads, so each file must be exactly what its "
            "writer emitted -- sorted keys, no spacing, one trailing newline."
        )
    return raw, cast(dict[str, object], document)


def _probe_and_decode(
    runner: Runner, media_bytes: bytes, channels: int, description: str
) -> tuple[dict[str, object], int]:
    """Pipe-probe and pipe-decode one captured MP4 observation; return streams + count.

    The probe and the decode both consume the SAME captured bytes through stdin; the
    decode-count law ``len(pcm) % (2 * channels) == 0`` runs before the normalized
    streams block is built.
    """
    probe_stdout = _run_or_refuse(
        runner, list(build_probe_command()), media_bytes, f"{description} probe"
    )
    try:
        probe = json.loads(probe_stdout)
    except ValueError as error:
        raise EncodeExecutionRefused(
            f"the {description} probe output is empty or not JSON: {error}"
        ) from error
    pcm = _run_or_refuse(runner, list(build_decode_command()), media_bytes, f"{description} decode")
    if len(pcm) % (2 * channels) != 0:
        raise EncodeExecutionRefused(
            f"the {description} decodes to {len(pcm)} PCM bytes, which is not divisible "
            f"by 2*{channels}; the PCM16 interleave law does not close"
        )
    decoded = len(pcm) // (2 * channels)
    streams = normalize_probe_document(probe, audio_samples_decoded=decoded)
    return streams, decoded


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the three required and two optional flags this executor accepts."""
    parser = argparse.ArgumentParser(
        prog="python media/ffmpeg/scripts/encode_episode.py",
        description=(
            "Project one audited media assembly and its caption serialization through the "
            "pinned media_encode_profile_v1 FFmpeg execution and publish the audited result."
        ),
    )
    parser.add_argument(
        "--assembly-dir", required=True, help="the audited Phase 33 media assembly directory"
    )
    parser.add_argument(
        "--captions-dir",
        required=True,
        help="the audited Phase 34 caption serialization directory",
    )
    parser.add_argument(
        "--output-root",
        required=True,
        help="the directory under which one final-media directory is published",
    )
    parser.add_argument(
        "--ffmpeg",
        help="path to an FFmpeg 9.x executable (else $FFMPEG_EXECUTABLE, else PATH)",
    )
    parser.add_argument(
        "--ffprobe",
        help="path to an FFprobe 9.x executable (else $FFPROBE_EXECUTABLE, else PATH)",
    )
    return parser.parse_args(None if argv is None else list(argv))


def _verify_existing_noop(
    final_dir: Path,
    runner: Runner,
    *,
    assembly_manifest_bytes: bytes,
    captions_manifest_bytes: bytes,
    fps: int,
    presentation_frames_total: int,
    rate: int,
    channels: int,
    audio_samples_total: int,
    width: int,
    height: int,
) -> int:
    """Re-verify an existing final directory as a truthful no-op, and report it.

    The existing directory is re-audited tool-free, its bound source digests are
    re-hashed against the CURRENT captured manifests, its media is captured once,
    probed and decoded, and every stream law is re-proven against the CURRENT
    authorities. Nothing is rewritten.
    """
    problems, _manifest_bytes, manifest = _audit_media_encode_directory_with_observation(final_dir)
    if problems:
        raise EncodeExecutionRefused(
            f"{final_dir} already exists and is not a truthful, complete execution: {problems}"
        )
    existing = cast(dict[str, object], manifest)
    existing_source = cast(dict[str, object], existing["source"])
    if existing_source["media_assembly_manifest_sha256"] != sha256_hex(assembly_manifest_bytes):
        raise EncodeExecutionRefused(
            f"{final_dir} already exists and assembles a different media assembly than this "
            "execution captured; nothing is deleted to make room"
        )
    if existing_source["caption_serialization_manifest_sha256"] != sha256_hex(
        captions_manifest_bytes
    ):
        raise EncodeExecutionRefused(
            f"{final_dir} already exists and assembles a different caption serialization "
            "than this execution captured; nothing is deleted to make room"
        )
    video = cast(dict[str, object], existing["video"])
    mp4_path = final_dir / cast(str, video["file"])
    mp4_bytes = read_file_bytes(mp4_path)
    if len(mp4_bytes) != video["bytes"]:
        raise EncodeExecutionRefused(
            f"{mp4_path} is {len(mp4_bytes)} bytes, but the published manifest records "
            f"{video['bytes']!r}"
        )
    if sha256_hex(mp4_bytes) != video["sha256"]:
        raise EncodeExecutionRefused(
            f"{mp4_path} hashes to {sha256_hex(mp4_bytes)!r}, but the published manifest "
            f"records {video['sha256']!r}"
        )
    streams, decoded = _probe_and_decode(runner, mp4_bytes, channels, "existing episode")
    require_stream_facts(
        streams,
        fps=fps,
        presentation_frames_total=presentation_frames_total,
        audio_sample_rate_hz=rate,
        audio_channels=channels,
        audio_samples_total=audio_samples_total,
        width=width,
        height=height,
    )
    print("VERIFIED NO-OP")
    print("re-probe: captured bytes")
    print(f"re-decode: {decoded} samples")
    return 0


def run_encode(args: argparse.Namespace, runner: Runner) -> int:
    """Execute one final-media build in the frozen order, returning the exit code."""
    # 1-4: locate the two tools, then pass the version and capability gates.
    ffmpeg_path = _locate("ffmpeg", args.ffmpeg, "FFMPEG_EXECUTABLE", os.environ)
    ffprobe_path = _locate("ffprobe", args.ffprobe, "FFPROBE_EXECUTABLE", os.environ)
    ffmpeg_version = _tool_version_line(runner, ffmpeg_path, "ffmpeg")
    ffprobe_version = _tool_version_line(runner, ffprobe_path, "ffprobe")
    _require_tool_capabilities(runner, ffmpeg_path)

    assembly_dir = Path(args.assembly_dir)
    captions_dir = Path(args.captions_dir)
    output_root = Path(args.output_root)

    # 5: the output-root direct-parent check is publisher.begin_media_encode_staging's
    # own first act, run before any staging exists.

    # 6-7: the upstream self-contained audits, before any byte is captured.
    assembly_problems = audit_media_assembly_directory(assembly_dir)
    if assembly_problems:
        raise EncodeExecutionRefused(
            f"the assembly directory refuses this encode: {assembly_problems}"
        )
    captions_problems = audit_caption_serialization_directory(captions_dir)
    if captions_problems:
        raise EncodeExecutionRefused(
            f"the caption serialization directory refuses this encode: {captions_problems}"
        )

    # 8: the single-capture -- each bound byte is read exactly ONCE.
    assembly_manifest_bytes, assembly = _capture_canonical(
        assembly_dir / MEDIA_ASSEMBLY_MANIFEST_FILENAME, "media assembly manifest"
    )
    render_manifest_bytes, render_manifest = _capture_canonical(
        assembly_dir / RENDER_MANIFEST_COPY_FILENAME, "render manifest copy"
    )
    captions_manifest_bytes, captions = _capture_canonical(
        captions_dir / CAPTION_SERIALIZATION_MANIFEST_FILENAME,
        "caption serialization manifest",
    )
    captions_sidecars = cast(dict[str, object], captions["sidecars"])
    srt_record = cast(dict[str, object], captions_sidecars["srt"])
    vtt_record = cast(dict[str, object], captions_sidecars["vtt"])
    srt_bytes = read_file_bytes(captions_dir / cast(str, srt_record["file"]))
    vtt_bytes = read_file_bytes(captions_dir / cast(str, vtt_record["file"]))
    wav_bytes = read_file_bytes(assembly_dir / episode_audio_relative_path())

    # 9: the joins -- identity, clock, lineage, render copy, and the WAV digest.
    assembly_validated, captions_validated = require_encode_sources_join(assembly, captions)
    if sha256_hex(render_manifest_bytes) != assembly["source"]["render_manifest_sha256"]:
        raise EncodeExecutionRefused(
            "the render manifest copy in the assembly does not hash to the assembly's "
            "bound render_manifest_sha256; this execution binds the one captured observation"
        )
    validate_episode_render_manifest(render_manifest)
    audio = cast(dict[str, object], assembly["audio"])
    if sha256_hex(wav_bytes) != audio["sha256"]:
        raise EncodeExecutionRefused(
            "the captured episode WAV does not hash to the assembly's bound audio sha256"
        )
    if len(wav_bytes) != audio["bytes"]:
        raise EncodeExecutionRefused(
            f"the captured episode WAV is {len(wav_bytes)} bytes, but the assembly records "
            f"{audio['bytes']!r}"
        )

    # 10: derive every authority from the captured documents, never from a duplicate.
    source = cast(dict[str, object], assembly["source"])
    clock = cast(dict[str, object], assembly["clock"])
    mode = cast(str, source["mode"])
    episode = cast(int, source["episode"])
    previous_episode = cast("int | None", source["previous_episode"])
    episode_id = media_encode_id(mode=mode, episode=episode, previous_episode=previous_episode)
    fps = cast(int, clock["fps"])
    presentation_frames_total = cast(int, clock["presentation_frames_total"])
    rate = cast(int, audio["sample_rate_hz"])
    channels = cast(int, audio["channels"])
    audio_samples_total = cast(int, audio["audio_samples"])
    profile_owned = cast(dict[str, object], render_profile_document()["owned"])
    width = cast(int, profile_owned["resolution_x"])
    height = cast(int, profile_owned["resolution_y"])

    final_dir = output_root / episode_id
    if final_dir.exists():
        return _verify_existing_noop(
            final_dir,
            runner,
            assembly_manifest_bytes=assembly_manifest_bytes,
            captions_manifest_bytes=captions_manifest_bytes,
            fps=fps,
            presentation_frames_total=presentation_frames_total,
            rate=rate,
            channels=channels,
            audio_samples_total=audio_samples_total,
            width=width,
            height=height,
        )

    # 11-12: fresh staging and the digest-verified audio snapshot the encoder consumes.
    staging_dir, final_dir, staging_name = publisher.begin_media_encode_staging(
        output_root, episode_id
    )
    snapshot_path = publisher.write_audio_snapshot(staging_dir, wav_bytes)

    try:
        # 13: the real-geometry preflight self-test over tiny video.
        preflight_audio = staging_dir / PREFLIGHT_AUDIO_FILENAME
        write_atomically(preflight_audio, preflight_wav_bytes(rate, channels, audio_samples_total))
        preflight_argv = substitute_paths(
            build_preflight_command(
                fps=fps,
                presentation_frames_total=presentation_frames_total,
                audio_sample_rate_hz=rate,
                audio_channels=channels,
            ),
            assembly_dir=str(assembly_dir),
            staging_dir=str(staging_dir),
        )
        _run_or_refuse(runner, preflight_argv, None, "preflight encode")
        preflight_path = staging_dir / PREFLIGHT_MEDIA_FILENAME
        fsync_file(preflight_path)
        preflight_mp4 = read_file_bytes(preflight_path)
        remove_owned_temporary(preflight_path, staging_dir=staging_dir)
        preflight_streams, preflight_decoded = _probe_and_decode(
            runner, preflight_mp4, channels, "preflight"
        )
        if preflight_decoded != audio_samples_total:
            raise EncodeExecutionRefused(
                f"the preflight media decodes to {preflight_decoded} audio samples, but the "
                f"locked total is {audio_samples_total}; the selected build fails the "
                "preflight self-test"
            )
        require_stream_facts(
            preflight_streams,
            fps=fps,
            presentation_frames_total=presentation_frames_total,
            audio_sample_rate_hz=rate,
            audio_channels=channels,
            audio_samples_total=audio_samples_total,
            width=_PREFLIGHT_VIDEO_WIDTH,
            height=_PREFLIGHT_VIDEO_HEIGHT,
        )
        remove_owned_temporary(preflight_audio, staging_dir=staging_dir)

        # 14: the REAL encode, with the resolved tool path at argv[0].
        temp_name = media_temp_filename(episode_id)
        encode_argv = substitute_paths(
            build_media_encode_command(
                fps=fps,
                presentation_frames_total=presentation_frames_total,
                audio_sample_rate_hz=rate,
                audio_channels=channels,
                media_temp_filename=temp_name,
            ),
            assembly_dir=str(assembly_dir),
            staging_dir=str(staging_dir),
        )
        spawn_argv = [str(ffmpeg_path)] + encode_argv[1:]
        _run_or_refuse(runner, spawn_argv, None, "media encode")

        # 15: post-encode stability -- the encoder consumed the snapshot, so the
        # snapshot is re-hashed and deleted only now, AFTER the encode finished.
        post_problems = audit_media_assembly_directory(assembly_dir)
        if post_problems:
            raise EncodeExecutionRefused(
                f"the assembly directory changed during the encode: {post_problems}"
            )
        reassembled_bytes = read_file_bytes(assembly_dir / MEDIA_ASSEMBLY_MANIFEST_FILENAME)
        if sha256_hex(reassembled_bytes) != sha256_hex(assembly_manifest_bytes):
            raise EncodeExecutionRefused(
                "the assembly manifest changed during the encode; the captured observation "
                "is no longer authoritative"
            )
        snapshot_now = read_file_bytes(snapshot_path)
        if sha256_hex(snapshot_now) != sha256_hex(wav_bytes):
            raise EncodeExecutionRefused(
                "the staged audio snapshot no longer matches the captured WAV digest"
            )
        remove_owned_temporary(snapshot_path, staging_dir=staging_dir)

        # 16: fsync the tool-written temporary, capture its bytes ONCE, discard it.
        temp_path = staging_dir / temp_name
        fsync_file(temp_path)
        mp4_bytes = read_file_bytes(temp_path)
        remove_owned_temporary(temp_path, staging_dir=staging_dir)
        if not mp4_bytes:
            raise EncodeExecutionRefused(
                "the encoded media temporary is empty; a truthful encode leaves exactly "
                "one non-empty observation"
            )

        # 17-20: digest, probe, decode, and every frozen stream law on the capture.
        mp4_sha256 = sha256_hex(mp4_bytes)
        streams, decoded = _probe_and_decode(runner, mp4_bytes, channels, "episode")
        require_stream_facts(
            streams,
            fps=fps,
            presentation_frames_total=presentation_frames_total,
            audio_sample_rate_hz=rate,
            audio_channels=channels,
            audio_samples_total=audio_samples_total,
            width=width,
            height=height,
        )

        # 21-25: write every carried byte and the manifest, then publish atomically.
        publisher.write_final_media(staging_dir, episode_id, mp4_bytes)
        publisher.write_sidecar_copies(
            staging_dir,
            episode_id,
            captions_manifest=captions_validated,
            srt_bytes=srt_bytes,
            vtt_bytes=vtt_bytes,
        )
        publisher.write_provenance_copies(
            staging_dir,
            assembly_manifest_bytes=assembly_manifest_bytes,
            captions_manifest_bytes=captions_manifest_bytes,
        )
        manifest_bytes = build_episode_media_encode_manifest_bytes(
            assembly_manifest=assembly_validated,
            assembly_manifest_bytes=assembly_manifest_bytes,
            captions_manifest=captions_validated,
            captions_manifest_bytes=captions_manifest_bytes,
            video_bytes=len(mp4_bytes),
            video_sha256=mp4_sha256,
            streams=streams,
            ffmpeg_version=ffmpeg_version,
            ffprobe_version=ffprobe_version,
        )
        publisher.write_media_encode_manifest(
            staging_dir,
            manifest_bytes,
            runtime_roots=(
                str(assembly_dir),
                str(captions_dir),
                str(output_root),
                str(staging_dir),
            ),
        )
        publisher.publish_media_encode(
            staging_dir,
            final_dir,
            output_root=output_root,
            staging_name=staging_name,
            final_name=episode_id,
        )
    except publisher.HANDLED_REFUSALS:
        # A handled refusal (EncodeExecutionRefused included, as a ValueError
        # subclass) discards this run's own staging so it never litters the
        # output root; an exception of any other class survives as crash evidence.
        discard_owned_staging(
            staging_dir,
            expected_parent=output_root,
            expected_name=staging_name,
            episode_id=episode_id,
        )
        raise

    # 26: summary -- re-read the published manifest and derive the report from it.
    published_bytes = read_file_bytes(final_dir / MEDIA_ENCODE_MANIFEST_FILENAME)
    published = cast(
        dict[str, object],
        validate_episode_media_encode_manifest(
            loads_canonical(published_bytes, "episode media encode manifest")
        ),
    )
    published_source = cast(dict[str, object], published["source"])
    published_streams = cast(dict[str, object], published["streams"])
    published_video = cast(dict[str, object], published["video"])
    summary = {
        "final_dir": str(final_dir),
        "video_sha256": published_video["sha256"],
        "audio_samples_decoded": published_streams["audio_samples_decoded"],
        "video_frames_counted": published_streams["video_frames_counted"],
        "episode": published_source["episode"],
        "mode": published_source["mode"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None, *, runner: Runner | None = None) -> int:
    """Parse arguments, execute the build, and report what was published.

    Returns:
        0 on success or on a verified no-op re-run; 1 on refusal.
    """
    arguments = parse_arguments(argv)
    try:
        return run_encode(arguments, _default_runner if runner is None else runner)
    except (OSError, TypeError, ValueError, MediaEncodeDirectoryRefused) as error:
        # OSError covers the deliberate FileNotFoundError/FileExistsError refusals as
        # well as generic filesystem failures; EncodeExecutionRefused and the upstream
        # MediaEncodeRefused both subclass ValueError.
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
