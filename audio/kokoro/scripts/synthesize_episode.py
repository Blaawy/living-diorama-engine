r"""Synthesize a reviewed Episode Voice Plan into real, audited speech.

    python audio/kokoro/scripts/synthesize_episode.py \
        --voice-plan episode_voice_plan_v1.json \
        --realization episode_language_realization_plan_v1.json \
        --presentation episode_presentation_plan_v1.json \
        --delivery episode_narration_delivery_plan_v1.json \
        --narration episode_narration_plan_v1.json \
        --shots shot_direction_plan_v1.json \
        --story episode_story_plan_v1.json \
        --export render_export_ep1.json \
        --model-weights /path/to/kokoro-v1_0.pth \
        --model-config /path/to/config.json \
        --voice-pack /path/to/af_heart.pt \
        --output-root voice/

VOICE EXECUTION SPEAKS A PLANNED EPISODE. IT PLANS NOTHING.

This script is the one place in the project that legitimately imports a
synthesis engine, a G2P library, or ``torch``. Every such import is deferred
into a function body, never placed at module scope, so this module can be
imported and driven by a fake engine in tests, and so importing it never
loads a model.

``main`` is the one authoritative execution entrypoint. It establishes an
offline environment, reads and source-verifies all eight canonical
documents through the reused, unweakened Phase 28 gate, proves the engine
versions and local G2P and model assets are exactly what the plan pins,
constructs the reviewed pipeline, and only then reaches ``publish_episode``
-- an internal post-gate helper that is never itself a standalone,
provenance-valid entry point, is not exported by any canonical package, and
has exactly one call site: inside ``main``.

Execution is offline only. No acquisition path exists anywhere in this
module: the three model assets are explicit local files, digest-verified
against the plan's pins before they are ever opened, and the local spaCy
model and num2words package must already be installed. A missing local
resource is refused, never downloaded.
"""

import argparse
import json
import os
import shutil
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, cast

from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.voice import validate_episode_voice_plan_against_sources
from living_diorama.voice_execution import (
    audit_voice_directory,
    build_episode_voice_manifest_document,
    canonical_wav_bytes,
    pcm16_bytes,
    require_manifest_matches_plan,
    speech_sample_count,
    unit_audio_filename,
    validate_episode_voice_manifest,
    verify_speech_audio,
    voice_execution_id,
)
from living_diorama.voice_execution.voice_execution_spec import (
    DEVICE_CPU,
    PARTIAL_SUFFIX,
    SPACY_MODEL,
    SPEECH_DIRECTORY,
    VOICE_MANIFEST_FILENAME,
    VOICE_PLAN_FILENAME,
    WRITING_SUFFIX,
)


class VoicePlanRefused(ValueError):
    """The plan, its inputs, its assets, its versions or its environment refuse execution."""


class SpeechRefused(ValueError):
    """One unit's synthesis or artifact refuses to be spoken or recorded."""


class VoiceDirectoryRefused(RuntimeError):
    """The destination directory's state refuses this execution."""


_OFFLINE_ENVIRONMENT_VARIABLES: Final = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
}
"""Defence in depth only.

The guarantee that this execution never reaches the network is explicit
local asset injection plus the digest gate in
:func:`require_local_model_assets` -- never these variables. They exist so
an ambient acquisition path that ignores explicit local injection still
finds the network disabled.
"""


def _require_offline_environment() -> None:
    """Set the offline environment variables, before the first third-party import."""
    for key, value in _OFFLINE_ENVIRONMENT_VARIABLES.items():
        os.environ[key] = value


def _read_canonical(path: Path, description: str) -> object:
    """Load a document, refusing any file that is not canonical bytes.

    Raises:
        FileNotFoundError: If the file is absent.
        TypeError: If the decoded document contains a value a canonical
            document may not carry.
        ValueError: If the bytes are not valid UTF-8, are not valid JSON,
            repeat an object key, contain a non-standard JSON constant or a
            non-finite number, or are not the canonical encoding of the
            document they contain.
    """
    if not path.is_file():
        raise FileNotFoundError(f"{description} not found: {path}")
    raw = path.read_bytes()
    document = loads_canonical(raw, description)
    if raw != dumps_canonical(document, description):
        raise ValueError(
            f"{description} at {path} is not canonical bytes. This execution binds the digest "
            "of every document it reads, so each file must be exactly what its writer emitted "
            "-- sorted keys, no spacing, one trailing newline. Rebuild it rather than "
            "reformatting it."
        )
    return document


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the twelve required flags this executor accepts, and nothing else."""
    parser = argparse.ArgumentParser(
        prog="python audio/kokoro/scripts/synthesize_episode.py",
        description=(
            "Synthesize each unit of a reviewed Episode Voice Plan exactly once, under the "
            "pinned narrator request, and publish the audited result."
        ),
    )
    parser.add_argument("--voice-plan", required=True, help="the Episode Voice Plan V1")
    parser.add_argument(
        "--realization", required=True, help="the Episode Language Realization Plan"
    )
    parser.add_argument("--presentation", required=True, help="the Episode Presentation Plan")
    parser.add_argument("--delivery", required=True, help="the Episode Narration Delivery Plan")
    parser.add_argument("--narration", required=True, help="the Episode Narration Plan")
    parser.add_argument("--shots", required=True, help="the Shot Direction Plan")
    parser.add_argument("--story", required=True, help="the Episode Story Plan")
    parser.add_argument(
        "--export",
        required=True,
        help="the render export the story and realization were derived from",
    )
    parser.add_argument(
        "--model-weights",
        required=True,
        help="local path to the digest-verified Kokoro model weights file",
    )
    parser.add_argument(
        "--model-config",
        required=True,
        help="local path to the digest-verified Kokoro model config file",
    )
    parser.add_argument(
        "--voice-pack", required=True, help="local path to the digest-verified voice pack file"
    )
    parser.add_argument(
        "--output-root",
        required=True,
        help="the directory under which one voice execution directory is published",
    )
    return parser.parse_args(None if argv is None else list(argv))


def require_engine_versions(voice_block: Mapping[str, object]) -> None:
    """Refuse unless the installed engine and G2P equal the plan's pinned versions.

    Raises:
        VoicePlanRefused: If the installed ``kokoro`` or ``misaki`` version
            does not equal the plan's pinned ``engine_version`` or
            ``g2p_version``.
    """
    import importlib.metadata

    engine_version = cast(str, voice_block["engine_version"])
    g2p_version = cast(str, voice_block["g2p_version"])

    installed_engine = importlib.metadata.version("kokoro")
    if installed_engine != engine_version:
        raise VoicePlanRefused(
            f"the plan pins engine_version {engine_version!r}, but the installed kokoro is "
            f"{installed_engine!r}; this environment cannot satisfy the reviewed request"
        )
    installed_g2p = importlib.metadata.version("misaki")
    if installed_g2p != g2p_version:
        raise VoicePlanRefused(
            f"the plan pins g2p_version {g2p_version!r}, but the installed misaki is "
            f"{installed_g2p!r}; this environment cannot satisfy the reviewed request"
        )


def require_local_g2p_assets() -> None:
    """Refuse unless the local G2P stack is already present.

    Checked before any pipeline construction, because
    ``misaki.en.G2P.__init__`` itself calls ``spacy.cli.download`` when the
    pinned model is absent -- this check is what makes that acquisition path
    unreachable.

    Raises:
        VoicePlanRefused: If the local spaCy model or ``num2words`` is not
            installed.
    """
    import importlib.metadata

    import spacy.util

    if not spacy.util.is_package(SPACY_MODEL):
        raise VoicePlanRefused(
            f"the local spaCy model {SPACY_MODEL!r} is not installed; this execution never "
            "downloads it"
        )
    try:
        importlib.metadata.version("num2words")
    except importlib.metadata.PackageNotFoundError as error:
        raise VoicePlanRefused(
            "num2words is not installed locally; this execution never downloads it"
        ) from error


def require_local_model_assets(
    voice_block: Mapping[str, object],
    *,
    weights_path: Path,
    config_path: Path,
    voice_pack_path: Path,
) -> None:
    """Refuse unless the three local model assets exist and digest to the plan's pins.

    Raises:
        VoicePlanRefused: If any of the three files is absent, or its
            SHA-256 disagrees with the plan's pinned digest.
    """
    for path, key, label in (
        (weights_path, "model_weights_sha256", "model weights"),
        (config_path, "model_config_sha256", "model config"),
        (voice_pack_path, "voice_pack_sha256", "voice pack"),
    ):
        if not path.is_file():
            raise VoicePlanRefused(f"the local {label} file does not exist: {path}")
        observed = sha256_hex(path.read_bytes())
        expected = cast(str, voice_block[key])
        if observed != expected:
            raise VoicePlanRefused(
                f"the local {label} file {path} hashes to {observed!r}, but the plan pins "
                f"{expected!r}; this execution never loads an asset it cannot verify"
            )


def resolve_execution_environment() -> dict[str, str]:
    """Return exactly the seven execution environment strings this build reports.

    Attestation, not proof: the manifest records this metadata, and no check
    anywhere in this phase claims to independently prove which Python, Torch
    or spaCy environment actually produced a given WAV.
    """
    import importlib.metadata
    import platform

    import torch

    return {
        "device": DEVICE_CPU,
        "python_version": platform.python_version(),
        "torch_version": torch.__version__,
        "spacy_version": importlib.metadata.version("spacy"),
        "spacy_model": SPACY_MODEL,
        "spacy_model_version": importlib.metadata.version(SPACY_MODEL),
        "num2words_version": importlib.metadata.version("num2words"),
    }


def build_pipeline(
    voice_block: Mapping[str, object],
    *,
    weights_path: Path,
    config_path: Path,
) -> object:
    """Construct the reviewed pipeline, with its G2P fallback explicitly disabled.

    ``KPipeline.__init__`` for an English ``lang_code`` constructs an
    ``EspeakFallback`` by default and only leaves it unset when that
    construction itself raises -- so the reviewed ``fallback = None`` policy
    is not reachable by argument. It is achieved here by explicit
    post-construction replacement, which is identical whether or not espeak
    happens to be installed: no ambient fallback substitution.

    ``model_repository`` and ``lang_code`` are read from the already
    gate-verified voice block, never from a second, duplicate literal --
    Phase 28 owns the narrator request.
    """
    import torch
    from kokoro import KModel, KPipeline
    from misaki import en as misaki_en

    torch.set_grad_enabled(False)

    model_repository = voice_block["model_repository"]
    model = (
        KModel(
            repo_id=cast(str, model_repository),
            config=str(config_path),
            model=str(weights_path),
        )
        .to(DEVICE_CPU)
        .eval()
    )
    pipeline = KPipeline(
        lang_code=cast(str, voice_block["lang_code"]),
        repo_id=cast(str, model_repository),
        model=model,
        device=DEVICE_CPU,
        trf=False,
    )
    pipeline.g2p = misaki_en.G2P(trf=False, british=False, fallback=None, unk="")
    return pipeline


def unit_texts(realization_plan: Mapping[str, object]) -> list[str]:
    """Return each unit's exact verified realized sentence, in plan order.

    The only Phase 29 keyed read of ``realized_text`` anywhere in this
    phase. It speaks the exact bytes a gate-verified realization plan
    proved: no normalization, no punctuation rewrite, no case change.
    """
    realizations = cast(list[Mapping[str, object]], realization_plan["realizations"])
    return [cast(str, realization["realized_text"]) for realization in realizations]


def tensor_to_float_list(audio: object, description: str) -> list[float]:
    """Validate a synthesized tensor and return its samples as built-in floats.

    Widening a float32 value into Python's built-in ``float`` (IEEE double)
    is exact and lossless, so this preserves every source sample's value and
    the sample count exactly. It does not, and need not, claim that the
    canonical PCM law reproduces any historical NumPy conversion's bytes --
    see :mod:`living_diorama.voice_execution.speech_audio` for the law
    itself, which is the only authority.

    Raises:
        SpeechRefused: If ``audio`` is not a ``torch.Tensor`` of dtype
            ``float32``, is not one-dimensional, carries no samples, carries
            a non-finite sample, or its ``tolist()`` disagrees with its own
            ``numel()`` in count or in element type.
    """
    import torch

    if not isinstance(audio, torch.Tensor):
        raise SpeechRefused(f"{description} is not a torch.Tensor, got {type(audio).__name__}")
    if audio.dtype is not torch.float32:
        raise SpeechRefused(f"{description} has dtype {audio.dtype}, expected torch.float32")
    if audio.ndim != 1:
        raise SpeechRefused(f"{description} has {audio.ndim} dimensions, expected 1")
    if audio.numel() < 1:
        raise SpeechRefused(f"{description} carries zero samples")
    if not bool(torch.isfinite(audio).all()):
        raise SpeechRefused(f"{description} carries a non-finite sample")

    expected = audio.numel()
    values = audio.detach().cpu().tolist()
    if type(values) is not list:
        raise SpeechRefused(f"{description}.tolist() did not return a list")
    if len(values) != expected:
        raise SpeechRefused(
            f"{description}.tolist() returned {len(values)} values, but the tensor holds {expected}"
        )
    for index, value in enumerate(values):
        if type(value) is not float:
            raise SpeechRefused(
                f"{description}[{index}] is not an exact float, got {type(value).__name__}"
            )
    return cast(list[float], values)


def synthesize_unit(
    pipeline: object,
    text: str,
    *,
    voice_pack_path: Path,
    speed_percent: int,
    seed: int,
) -> list[float]:
    """Synthesize exactly one unit's speech, once, and return validated samples.

    ``torch.manual_seed`` is called here, exactly once, immediately before
    the one pipeline invocation this function ever makes -- the exact
    semantics the reviewed acquisition evidence used (``smoke.py:186-188``):
    reset per unit, with model and pipeline construction strictly earlier.

    Raises:
        SpeechRefused: If synthesis yields anything other than exactly one
            output chunk, or the resulting tensor fails
            :func:`tensor_to_float_list`.
    """
    import torch

    torch.manual_seed(seed)
    outputs = list(cast(Any, pipeline)(text, voice=str(voice_pack_path), speed=speed_percent / 100))
    if len(outputs) != 1:
        raise SpeechRefused(
            f"synthesis produced {len(outputs)} chunks for one unit; exactly one is required"
        )
    return tensor_to_float_list(outputs[0].audio, "synthesized audio")


def _is_path_indirection(path: Path) -> bool:
    """Return whether this path is a symlink or a Windows junction.

    Neither is ever followed and neither is ever deleted through -- every
    caller of this helper refuses outright on ``True``.
    """
    return path.is_symlink() or path.is_junction()


def require_owned_staging(
    staging_dir: Path,
    *,
    expected_parent: Path,
    expected_name: str,
    unit_count: int,
) -> None:
    """Refuse unless every entry in this staging tree is positively this phase's own.

    Never deletes, never modifies, never follows an indirection. Location is
    proved lexically, via ``os.path.abspath``, which normalizes without
    traversing a symlink or junction -- ``Path.resolve()`` is never used
    here, because resolving would follow the very indirection this law
    exists to refuse.

    Raises:
        VoiceDirectoryRefused: If the name or location does not match
            exactly, if the directory or any entry inside it (including
            inside ``speech/``) is a symlink or junction, or if any entry
            anywhere is not one this phase's own contract accounts for.
    """
    if staging_dir.name != expected_name:
        raise VoiceDirectoryRefused(
            f"staging directory name {staging_dir.name!r} does not match the expected "
            f"{expected_name!r}"
        )
    if os.path.abspath(staging_dir.parent) != os.path.abspath(expected_parent):
        raise VoiceDirectoryRefused(
            f"staging directory {staging_dir} does not sit directly under the expected output "
            f"root {expected_parent}; ownership is proven by exact location, not name alone"
        )
    if _is_path_indirection(staging_dir):
        raise VoiceDirectoryRefused(
            f"{staging_dir} is a symlink or junction; this phase never follows an indirection "
            "and never deletes through one"
        )
    if not staging_dir.is_dir():
        raise VoiceDirectoryRefused(f"{staging_dir} is not a directory")

    permitted_top_level = {
        VOICE_PLAN_FILENAME,
        VOICE_MANIFEST_FILENAME,
        SPEECH_DIRECTORY,
        VOICE_PLAN_FILENAME + WRITING_SUFFIX,
        VOICE_MANIFEST_FILENAME + WRITING_SUFFIX,
    }
    for entry in sorted(staging_dir.iterdir()):
        if _is_path_indirection(entry):
            raise VoiceDirectoryRefused(f"{entry} is a symlink or junction inside staging")
        if entry.name not in permitted_top_level:
            raise VoiceDirectoryRefused(f"{entry} is not owned by this phase's staging")
        if entry.name == SPEECH_DIRECTORY:
            if not entry.is_dir():
                raise VoiceDirectoryRefused(f"{entry} is expected to be a directory")
        elif not entry.is_file():
            raise VoiceDirectoryRefused(f"{entry} is expected to be a regular file")

    speech_dir = staging_dir / SPEECH_DIRECTORY
    if speech_dir.exists():
        if _is_path_indirection(speech_dir):
            raise VoiceDirectoryRefused(f"{speech_dir} is a symlink or junction")
        owned_names = {unit_audio_filename(position) for position in range(1, unit_count + 1)}
        permitted_speech = owned_names | {name + WRITING_SUFFIX for name in owned_names}
        for entry in sorted(speech_dir.iterdir()):
            if _is_path_indirection(entry):
                raise VoiceDirectoryRefused(f"{entry} is a symlink or junction inside speech/")
            if entry.is_dir():
                raise VoiceDirectoryRefused(
                    f"{entry} is a directory inside speech/, never permitted"
                )
            if entry.name not in permitted_speech:
                raise VoiceDirectoryRefused(f"{entry} is not an owned speech file for this plan")


def discard_owned_staging(
    staging_dir: Path,
    *,
    expected_parent: Path,
    expected_name: str,
    unit_count: int,
) -> None:
    """Remove a staging tree, but only once it is proven wholly this phase's own.

    This is the single ``shutil.rmtree`` call site in all of Phase 29.
    """
    if not staging_dir.exists():
        return
    require_owned_staging(
        staging_dir,
        expected_parent=expected_parent,
        expected_name=expected_name,
        unit_count=unit_count,
    )
    shutil.rmtree(staging_dir)


def _write_atomically(path: Path, payload: bytes) -> None:
    """Write bytes atomically: a ``.writing`` temp, flush, fsync, then ``os.replace``."""
    temporary = path.with_name(path.name + WRITING_SUFFIX)
    with open(temporary, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _fsync_directory(path: Path) -> None:
    """Best-effort fsync of a directory's own entry, for durability only.

    Not every platform supports fsyncing a directory descriptor; when it is
    unsupported the attempt is skipped rather than treated as a failure --
    the atomicity of the terminal ``os.replace`` never depends on it.
    """
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def publish_episode(
    *,
    voice_plan: Mapping[str, object],
    voice_plan_bytes: bytes,
    realization_plan: Mapping[str, object],
    pipeline: object,
    voice_pack_path: Path,
    environment: dict[str, str],
    output_root: Path,
) -> Path:
    """Stage, synthesize, publish and return one episode's voice execution directory.

    Internal post-gate helper. Its precondition, binding on every caller: the
    supplied ``voice_plan``, ``voice_plan_bytes``, ``realization_plan`` and
    ``pipeline`` all originate from the current ``main`` invocation, after
    the full Phase 28 source gate and the complete asset/version preflight
    sequence have already passed. This function is never exported by any
    canonical package and is never itself a standalone, provenance-valid
    execution API -- it has exactly one call site, inside ``main``, and does
    not re-run the Phase 28 gate after the model is loaded.

    Once this run's own staging tree exists, a handled refusal (``OSError``,
    ``TypeError``, ``ValueError`` -- including ``VoicePlanRefused`` and
    ``SpeechRefused`` -- or ``VoiceDirectoryRefused``) discards that owned
    staging before propagating, so a refusal never litters the output root.
    An exception of any other class is never caught here: it propagates
    with the staging tree intact, as crash evidence for the next reviewed
    cleanup.

    Raises:
        VoicePlanRefused: If the realization plan does not realize as many
            units as the voice plan speaks.
        SpeechRefused: If any unit's synthesis, artifact or FIT fails.
        VoiceDirectoryRefused: If a final directory of this name already
            exists and is not a truthful, complete execution of this exact
            plan.
    """
    source = cast(Mapping[str, object], voice_plan["source"])
    voice_block = cast(Mapping[str, object], voice_plan["voice"])
    mode = cast(str, source["mode"])
    episode = cast(int, source["episode"])
    previous_episode = cast("int | None", source["previous_episode"])

    final_name = voice_execution_id(mode=mode, episode=episode, previous_episode=previous_episode)
    final_dir = output_root / final_name
    staging_name = f"{final_name}{PARTIAL_SUFFIX}"
    staging_dir = output_root / staging_name

    voice_units = cast(list[Mapping[str, object]], voice_plan["voice_units"])
    plan_digest = sha256_hex(voice_plan_bytes)

    if final_dir.exists():
        problems = audit_voice_directory(final_dir)
        if problems:
            raise VoiceDirectoryRefused(
                f"{final_dir} already exists and is not a truthful, complete execution of this "
                f"plan: {problems}"
            )
        existing_manifest = cast(
            dict[str, object],
            loads_canonical((final_dir / VOICE_MANIFEST_FILENAME).read_bytes(), "voice manifest"),
        )
        existing_source = cast(dict[str, object], existing_manifest["source"])
        if existing_source["voice_plan_sha256"] != plan_digest:
            raise VoiceDirectoryRefused(
                f"{final_dir} already exists and executes a different voice plan "
                f"({existing_source['voice_plan_sha256']!r} != {plan_digest!r}); nothing is "
                "deleted to make room"
            )
        return final_dir

    discard_owned_staging(
        staging_dir,
        expected_parent=output_root,
        expected_name=staging_name,
        unit_count=len(voice_units),
    )
    staging_dir.mkdir(parents=True)
    speech_dir = staging_dir / SPEECH_DIRECTORY
    speech_dir.mkdir()

    try:
        _write_atomically(staging_dir / VOICE_PLAN_FILENAME, voice_plan_bytes)

        texts = unit_texts(realization_plan)
        if len(texts) != len(voice_units):
            raise VoicePlanRefused(
                f"the realization plan realizes {len(texts)} units, but the voice plan speaks "
                f"{len(voice_units)}"
            )

        speed_percent = cast(int, voice_block["speed_percent"])
        seed = cast(int, voice_block["seed"])
        sample_rate_hz = cast(int, voice_block["sample_rate_hz"])
        channels = cast(int, voice_block["channels"])

        results: dict[int, dict[str, object]] = {}
        for position, (unit, text) in enumerate(zip(voice_units, texts, strict=True), start=1):
            samples = synthesize_unit(
                pipeline,
                text,
                voice_pack_path=voice_pack_path,
                speed_percent=speed_percent,
                seed=seed,
            )
            pcm = pcm16_bytes(samples, f"voice unit {position}")
            wav = canonical_wav_bytes(pcm, sample_rate_hz=sample_rate_hz, channels=channels)

            unit_path = speech_dir / unit_audio_filename(position)
            _write_atomically(unit_path, wav)

            # The publication gate: a file that does not fully re-parse from
            # disk never counts, and its sample count is recomputed from the
            # bytes that actually landed, never from the waveform still held
            # in memory.
            structural = verify_speech_audio(
                unit_path, expected_sample_rate_hz=sample_rate_hz, expected_channels=channels
            )
            if structural:
                raise SpeechRefused(f"voice unit {position} failed publication: {structural}")
            measured = speech_sample_count(unit_path)
            capacity = cast(int, unit["capacity_samples"])
            if measured > capacity:
                raise SpeechRefused(
                    f"voice unit {position} measured {measured} samples, beyond its "
                    f"{capacity}-sample capacity; the whole episode refuses rather than publish "
                    "an overflowing unit"
                )
            results[position] = {
                "bytes": unit_path.stat().st_size,
                "sha256": sha256_hex(unit_path.read_bytes()),
                "speech_samples": measured,
            }

        manifest_document = build_episode_voice_manifest_document(
            voice_plan=voice_plan, results=results, environment=environment
        )
        require_manifest_matches_plan(manifest_document, voice_plan)
        manifest_bytes = dumps_canonical(manifest_document, "episode voice manifest")
        _write_atomically(staging_dir / VOICE_MANIFEST_FILENAME, manifest_bytes)

        _fsync_directory(speech_dir)
        _fsync_directory(staging_dir)
        os.replace(staging_dir, final_dir)
        return final_dir
    except (OSError, TypeError, ValueError, VoiceDirectoryRefused):
        # A handled refusal: this run's own freshly created staging is
        # discarded so it never litters the output root as if it were crash
        # evidence. An unrecognized exception class -- a genuine crash, such
        # as the reviewed RuntimeError synthesis-failure scenario -- is never
        # caught here, so its `.partial` tree survives untouched for the
        # next reviewed cleanup.
        discard_owned_staging(
            staging_dir,
            expected_parent=output_root,
            expected_name=staging_name,
            unit_count=len(voice_units),
        )
        raise


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, execute the plan, and report what was spoken.

    Returns:
        0 on success, or on a verified no-op re-run of an already-complete
        execution; 1 on refusal.
    """
    _require_offline_environment()
    arguments = parse_arguments(argv)

    try:
        voice_plan_path = Path(arguments.voice_plan)
        voice_plan_bytes = voice_plan_path.read_bytes()
        voice_plan = cast(dict[str, object], _read_canonical(voice_plan_path, "voice plan"))
        realization = cast(
            dict[str, object],
            _read_canonical(Path(arguments.realization), "language realization plan"),
        )
        presentation = _read_canonical(Path(arguments.presentation), "presentation plan")
        delivery = _read_canonical(Path(arguments.delivery), "narration delivery plan")
        narration = _read_canonical(Path(arguments.narration), "episode narration plan")
        shots = _read_canonical(Path(arguments.shots), "shot direction plan")
        story = _read_canonical(Path(arguments.story), "episode story plan")
        export = _read_canonical(Path(arguments.export), "render export")

        # No presentation window, and no realization plan's identity, becomes
        # authoritative before the one document that proves them both true of
        # their own sources has been verified in full -- and before any
        # preflight or model load.
        validate_episode_voice_plan_against_sources(
            voice_plan, realization, presentation, delivery, narration, shots, story, export
        )

        voice_block = cast(Mapping[str, object], voice_plan["voice"])
        require_engine_versions(voice_block)
        require_local_g2p_assets()
        weights_path = Path(arguments.model_weights)
        config_path = Path(arguments.model_config)
        voice_pack_path = Path(arguments.voice_pack)
        require_local_model_assets(
            voice_block,
            weights_path=weights_path,
            config_path=config_path,
            voice_pack_path=voice_pack_path,
        )

        pipeline = build_pipeline(voice_block, weights_path=weights_path, config_path=config_path)
        environment = resolve_execution_environment()

        final_voice_dir = publish_episode(
            voice_plan=voice_plan,
            voice_plan_bytes=voice_plan_bytes,
            realization_plan=realization,
            pipeline=pipeline,
            voice_pack_path=voice_pack_path,
            environment=environment,
            output_root=Path(arguments.output_root),
        )
    except (OSError, TypeError, ValueError) as error:
        # OSError covers the deliberate FileExistsError/FileNotFoundError
        # refusals as well as generic filesystem failures; VoicePlanRefused
        # and SpeechRefused both subclass ValueError.
        print(f"error: {error}", file=sys.stderr)
        return 1
    except VoiceDirectoryRefused as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    # Reporting only: re-read what was actually published, validate it, and
    # derive the summary from that -- this creates no new authority and
    # performs no synthesis.
    manifest = validate_episode_voice_manifest(
        cast(
            dict[str, object],
            _read_canonical(final_voice_dir / VOICE_MANIFEST_FILENAME, "voice manifest"),
        )
    )
    source = cast(dict[str, object], manifest["source"])
    completeness = cast(dict[str, object], manifest["completeness"])
    counts = {
        "episode": source["episode"],
        "mode": source["mode"],
        "voice_units_total": completeness["voice_units_synthesized"],
        "speech_samples_total": completeness["speech_samples_total"],
        "voice_dir": str(final_voice_dir),
    }
    print(json.dumps(counts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
