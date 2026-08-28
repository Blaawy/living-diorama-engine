"""Self-contained audit of a composed audio directory against its own manifest.

This is the independent half of Phase 31. The publisher writes the track and
the manifest; this function re-reads every byte in the directory and decides
whether the manifest told the truth. It trusts nothing the publisher
recorded: the copied witness's raw digest is checked against the sealed
plan's binding *before* the witness is ever parsed; the composed track is
re-hashed and re-parsed; every placed span's PCM is re-extracted and
reconstructed into a canonical unit WAV, whose bytes and digest must equal
the ones the audited Phase 29 witness recorded; and every sample outside
every placed span must be zero.

It is self-contained: it reads only the four entries inside the directory it
is handed, and succeeds after the original Phase 29 voice directory the
composition was built from is no longer available. It writes nothing,
repairs nothing, and imports no synthesis engine.

Every governed entry -- the composition directory itself, the copied plan,
the copied witness, the composition manifest, ``audio/`` and its one WAV --
is refused as a problem if it is a symlink or Windows junction, before its
content or metadata is ever trusted. No expected condition (``OSError``,
``TypeError``, ``ValueError`` or ``SpeechAudioProblem``) escapes this
function: it always returns ``list[str]``, never raises for a governed
filesystem or data problem.
"""

from pathlib import Path
from typing import cast

from living_diorama.audio_composition.audio_composer import (
    pcm_payload_of,
    require_placement_geometry,
    require_silence_complement,
    span_pcm,
)
from living_diorama.audio_composition.audio_composition_binding import (
    require_composition_matches_plan_and_witness,
    require_voice_manifest_bytes,
)
from living_diorama.audio_composition.audio_composition_schema_v1 import (
    JsonValue,
    validate_episode_audio_composition_manifest,
)
from living_diorama.audio_composition.audio_composition_spec import (
    AUDIO_COMPOSITION_MANIFEST_FILENAME,
    AUDIO_DIRECTORY,
    AUDIO_TRACK_PLAN_FILENAME,
    COMPOSITION_DIRECTORY_ENTRIES,
    EPISODE_AUDIO_FILENAME,
    VOICE_MANIFEST_FILENAME,
    classify_audio_composition_directory_entry,
)
from living_diorama.audio_composition.audio_composition_staging import _is_path_indirection
from living_diorama.audio_track.audio_track_schema_v1 import validate_episode_audio_track_plan
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.voice_execution.speech_audio import (
    SpeechAudioProblem,
    canonical_wav_bytes,
    read_wav_facts,
)


def audit_audio_composition_directory(composition_dir: Path) -> list[str]:
    """Return every problem found in one composed audio directory.

    An empty list means: the audio track plan validates; the copied voice
    manifest witness's raw bytes are digest-bound to the plan (checked
    before parsing) and validate on their own contract; the composition
    manifest validates and agrees with the plan and witness beside it about
    everything it copied; the composed track exists with exactly the bytes,
    digest, sample count, rate and channel count the manifest recorded;
    every placed span's PCM reconstructs, wrapped in a canonical WAV, to
    exactly the byte length and digest the audited Phase 29 witness recorded
    for that unit; every sample outside every placed span is zero; the
    manifest's own accounting is measured from the records present; and no
    unaccounted entry is present anywhere in the directory.

    Every governed path is refused as a problem, never followed, if it is a
    symlink or Windows junction. An expected filesystem or data condition
    (``OSError``, ``TypeError``, ``ValueError`` or ``SpeechAudioProblem``)
    from any governed read, stat or directory listing becomes a problem
    entry here rather than escaping -- this function always returns, it
    never raises for a governed condition.

    Args:
        composition_dir: The directory one composition owns.

    Returns:
        Human-readable problems, in the order they were found.
    """
    try:
        return _audit_governed_directory(composition_dir)
    except OSError as error:
        return [f"{composition_dir} could not be fully read: {error}"]


def _audit_governed_directory(composition_dir: Path) -> list[str]:
    """The real audit body, wrapped by the public function's OSError boundary."""
    problems: list[str] = []
    plan_path = composition_dir / AUDIO_TRACK_PLAN_FILENAME
    witness_path = composition_dir / VOICE_MANIFEST_FILENAME
    manifest_path = composition_dir / AUDIO_COMPOSITION_MANIFEST_FILENAME
    audio_dir = composition_dir / AUDIO_DIRECTORY
    track_path = audio_dir / EPISODE_AUDIO_FILENAME

    if _is_path_indirection(composition_dir):
        return [f"{composition_dir} is a symlink or junction; this phase never audits through one"]
    for governed_path in (plan_path, witness_path, manifest_path, audio_dir, track_path):
        if _is_path_indirection(governed_path):
            return [
                f"{governed_path} is a symlink or junction; this phase never trusts a governed "
                "entry reached through an indirection"
            ]

    if not plan_path.is_file():
        return [f"{plan_path} is missing; the composition directory does not say what it composes"]
    if not witness_path.is_file():
        return [f"{witness_path} is missing; the source witness was never published"]
    if not manifest_path.is_file():
        return [f"{manifest_path} is missing; this composition never completed"]
    if not track_path.is_file():
        return [f"{track_path} is missing; this composition never completed"]

    # ---- the Audio Track Plan first: it supplies the expected witness digest ----
    plan_raw = plan_path.read_bytes()
    try:
        plan = validate_episode_audio_track_plan(loads_canonical(plan_raw, "audio track plan"))
    except (TypeError, ValueError) as error:
        return [f"audio track plan is invalid: {error}"]
    if plan_raw != dumps_canonical(plan, "audio track plan"):
        return [f"{plan_path} is not canonical bytes"]

    # ---- witness: raw digest BEFORE parse, then parse / canonical-form / validate ----
    witness_raw = witness_path.read_bytes()
    try:
        witness = require_voice_manifest_bytes(plan, witness_raw)
    except (TypeError, ValueError) as error:
        return [f"voice manifest witness is invalid: {error}"]

    manifest_raw = manifest_path.read_bytes()
    try:
        manifest = validate_episode_audio_composition_manifest(
            loads_canonical(manifest_raw, "audio composition manifest")
        )
    except (TypeError, ValueError) as error:
        return [f"audio composition manifest is invalid: {error}"]
    if manifest_raw != dumps_canonical(manifest, "audio composition manifest"):
        return [f"{manifest_path} is not canonical bytes"]

    try:
        manifest = require_composition_matches_plan_and_witness(manifest, plan, witness)
    except (TypeError, ValueError) as error:
        problems.append(f"the manifest contradicts the plan or witness beside it: {error}")

    audio = cast(dict[str, JsonValue], manifest.get("audio", {}))

    try:
        rate, channels, total_samples = read_wav_facts(track_path)
    except SpeechAudioProblem as error:
        return problems + [f"composed track could not be measured: {error}"]

    size = track_path.stat().st_size
    track_bytes = track_path.read_bytes()
    digest = sha256_hex(track_bytes)
    if size != audio.get("bytes") or digest != audio.get("sha256"):
        problems.append(
            f"composed track on disk is {size} bytes / {digest}, but the manifest records "
            f"{audio.get('bytes')} bytes / {audio.get('sha256')}"
        )
    if total_samples != audio.get("audio_samples"):
        problems.append(
            f"composed track measures {total_samples} samples, but the manifest records "
            f"{audio.get('audio_samples')}"
        )
    if rate != audio.get("sample_rate_hz") or channels != audio.get("channels"):
        problems.append(
            f"composed track is {rate} Hz / {channels} channel(s), but the manifest records "
            f"{audio.get('sample_rate_hz')} Hz / {audio.get('channels')} channel(s)"
        )

    try:
        placements = require_placement_geometry(plan)
    except (TypeError, ValueError) as error:
        problems.append(f"the plan's own placement geometry is unsound: {error}")
        placements = ()

    try:
        track_pcm = pcm_payload_of(track_bytes, expected_samples=total_samples)
    except (TypeError, ValueError) as error:
        problems.append(f"composed track payload could not be extracted: {error}")
        track_pcm = b""

    spans = cast(list[dict[str, JsonValue]], manifest.get("spans", []))
    voice_units = cast(list[dict[str, JsonValue]], witness.get("voice_units", []))

    if placements and track_pcm and len(spans) == len(voice_units) == len(placements):
        for position, (span, unit, (start, count)) in enumerate(
            zip(spans, voice_units, placements, strict=True), start=1
        ):
            try:
                slice_pcm = span_pcm(track_pcm, start_sample=start, speech_samples=count)
            except (TypeError, ValueError) as error:
                problems.append(f"span {position} could not be extracted: {error}")
                continue
            observed_pcm_sha256 = sha256_hex(slice_pcm)
            if observed_pcm_sha256 != span.get("pcm_sha256"):
                problems.append(
                    f"span {position} measured pcm_sha256 {observed_pcm_sha256}, but the "
                    f"manifest records {span.get('pcm_sha256')}"
                )
            unit_wav = canonical_wav_bytes(slice_pcm, sample_rate_hz=rate, channels=channels)
            if len(unit_wav) != unit.get("bytes") or sha256_hex(unit_wav) != unit.get("sha256"):
                problems.append(
                    f"span {position} reconstructs to {len(unit_wav)} bytes / "
                    f"{sha256_hex(unit_wav)}, but the bound Phase 29 witness records "
                    f"{unit.get('bytes')} bytes / {unit.get('sha256')} for this unit"
                )
            if span.get("speech_samples") != unit.get("speech_samples"):
                problems.append(f"span {position} speech_samples disagrees with the witness")

        try:
            require_silence_complement(track_pcm, placements)
        except (TypeError, ValueError) as error:
            problems.append(f"silence complement violated: {error}")

        # ---- optional whole-track internal-consistency recomposition ----
        # Self-referential: the spliced payloads are extracted from track_pcm
        # itself, so this proves internal consistency only -- never the
        # source-identity proof, which is the reconstructed-unit-WAV check above.
        recomposed = bytearray(len(track_pcm))
        for start, count in placements:
            slice_pcm = span_pcm(track_pcm, start_sample=start, speech_samples=count)
            at = start * 2
            recomposed[at : at + len(slice_pcm)] = slice_pcm
        if bytes(recomposed) != track_pcm:
            problems.append(
                "the composed track does not equal its own re-composition from the extracted "
                "payloads and zero elsewhere; internal-consistency check only"
            )
    elif len(spans) != len(voice_units):
        problems.append(
            f"the manifest carries {len(spans)} spans for a witness executing {len(voice_units)} "
            "units; every unit is placed exactly once"
        )

    completeness = cast(dict[str, JsonValue], manifest.get("completeness", {}))
    speech_samples_total = sum(cast(int, span.get("speech_samples", 0)) for span in spans)
    if completeness.get("speech_spans_composed") != len(spans):
        problems.append("completeness speech_spans_composed disagrees with the records present")
    expected_silence = total_samples - speech_samples_total
    if completeness.get("silence_samples_total") != expected_silence:
        problems.append("completeness silence_samples_total disagrees with the records present")
    if not completeness.get("complete", False):
        problems.append("the manifest does not claim a complete composition")

    for found in sorted(composition_dir.iterdir()):
        if _is_path_indirection(found):
            problems.append(f"{found} is a symlink or junction; no directory entry may be one")
            continue
        kind = classify_audio_composition_directory_entry(found.name, is_directory=found.is_dir())
        if kind == "partial":
            problems.append(
                f"{found} is this phase's own working file, left behind by a run that did not "
                "finish; a directory holding one is not a finished composition"
            )
        elif kind == "foreign":
            problems.append(
                f"{found} is present but a finished composition directory holds only "
                f"{sorted(COMPOSITION_DIRECTORY_ENTRIES)}"
            )
    if audio_dir.is_dir():
        for found in sorted(audio_dir.iterdir()):
            if _is_path_indirection(found):
                problems.append(f"{found} is a symlink or junction; no audio/ entry may be one")
                continue
            if found.name != EPISODE_AUDIO_FILENAME:
                problems.append(f"{found} is present but no audio record accounts for it")

    return problems


__all__ = ["audit_audio_composition_directory"]
