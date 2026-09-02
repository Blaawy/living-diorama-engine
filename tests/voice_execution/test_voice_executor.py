"""Executor orchestration, driven by a fake Kokoro/Torch/NumPy/spaCy stack.

The executor is imported via ``importlib.util.spec_from_file_location``,
exactly as Phase 23's own executor is imported without Blender, so importing
this module never requires kokoro, torch, misaki, numpy or spacy to be
installed. Every third-party name the executor would import is registered
into ``sys.modules`` by the ``fake_stack`` fixture before any executor
function that needs it is called, and removed again afterward by
``monkeypatch``.
"""

import ast
import importlib.metadata
import importlib.util
import math
import os
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from living_diorama.persistence.json_codec import dumps_canonical

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "audio" / "kokoro" / "scripts" / "synthesize_episode.py"


def _load_executor() -> Any:
    spec = importlib.util.spec_from_file_location("synthesize_episode_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


executor = _load_executor()

FLOAT32 = object()
"""A stable sentinel identity for numpy.float32, compared with `is`."""

FLOAT64 = object()
"""A stable sentinel identity for the dtype np.asarray widens a Python list to."""


class FakeNdArray:
    """A minimal stand-in for numpy.ndarray, holding only what the bridge touches."""

    def __init__(self, values: list[float], *, dtype: object = FLOAT32, ndim: int = 1) -> None:
        """Hold the sample values plus the dtype/ndim the bridge inspects."""
        self.values = values
        self.dtype = dtype
        self.ndim = ndim
        self.size = len(values)

    def tolist(self) -> list[float]:
        """Return the samples as a fresh Python list, exactly as ndarray.tolist does."""
        return list(self.values)


class FakeIsFiniteResult:
    """A minimal stand-in for the boolean ndarray numpy.isfinite returns."""

    def __init__(self, all_finite: bool) -> None:
        """Record whether every sample was finite."""
        self._all_finite = all_finite

    def all(self) -> bool:
        """Return whether every sample was finite."""
        return self._all_finite


class Control:
    """Records what the fake stack observed, and arms misbehaviour per test."""

    def __init__(self) -> None:
        """Initialise empty call logs and default-matching version/asset state."""
        self.manual_seed_calls: list[tuple[int, int]] = []
        self.pipeline_calls: list[dict[str, Any]] = []
        self.grad_enabled_calls: list[bool] = []
        self.pipeline_constructions: list[dict[str, Any]] = []
        self.kmodel_constructions: list[dict[str, Any]] = []
        self.kmodel_calls: list[dict[str, Any]] = []
        self.kmodel_instances: list[Any] = []
        self.chunks_at_unit: dict[int, int] = {}
        self.dtype_at_unit: dict[int, object] = {}
        self.dims_at_unit: dict[int, int] = {}
        self.nan_at_unit: set[int] = set()
        self.empty_at_unit: set[int] = set()
        self.fail_at_unit: set[int] = set()
        self.unit_counter = 0
        self.call_order = 0
        self.spacy_model_installed = True
        self.num2words_installed = True
        self.installed_kokoro_version = "0.9.4"
        self.installed_misaki_version = "0.9.4"

    def next_order(self) -> int:
        """Return the next monotonically increasing call-order marker."""
        self.call_order += 1
        return self.call_order


@pytest.fixture
def fake_stack(monkeypatch: pytest.MonkeyPatch) -> Control:
    """Install a fake torch/numpy/kokoro/spacy stack into sys.modules for one test."""
    control = Control()

    fake_torch = types.ModuleType("torch")
    fake_torch.__version__ = "2.13.0+cpu"  # type: ignore[attr-defined]

    def _set_grad_enabled(flag: bool) -> None:
        control.grad_enabled_calls.append(flag)

    def _manual_seed(seed: int) -> None:
        control.manual_seed_calls.append((seed, control.next_order()))

    fake_torch.set_grad_enabled = _set_grad_enabled  # type: ignore[attr-defined]
    fake_torch.manual_seed = _manual_seed  # type: ignore[attr-defined]

    fake_numpy = types.ModuleType("numpy")
    fake_numpy.float32 = FLOAT32  # type: ignore[attr-defined]

    def _asarray(audio: object) -> object:
        if isinstance(audio, FakeNdArray):
            return audio
        if isinstance(audio, list):
            # Mirrors np.asarray on a Python list: a non-float32 dtype that
            # the bridge must refuse.
            return FakeNdArray(audio, dtype=FLOAT64)
        raise TypeError(f"asarray of {type(audio).__name__}")

    def _isfinite(array: object) -> FakeIsFiniteResult:
        if not isinstance(array, FakeNdArray):
            raise TypeError(f"isfinite of {type(array).__name__}")
        finite = all(math.isfinite(v) for v in array.values) if array.values else True
        return FakeIsFiniteResult(finite)

    fake_numpy.asarray = _asarray  # type: ignore[attr-defined]
    fake_numpy.isfinite = _isfinite  # type: ignore[attr-defined]

    class FakeKModel:
        """A stand-in for kokoro.model.KModel, recording construction and chained calls."""

        def __init__(
            self,
            *,
            repo_id: str,
            config: str,
            model: str,
        ) -> None:
            control.kmodel_instances.append(self)
            control.kmodel_constructions.append(
                {
                    "repo_id": repo_id,
                    "config": config,
                    "model": model,
                    "order": control.next_order(),
                }
            )

        def to(self, device: str) -> "FakeKModel":
            control.kmodel_calls.append(
                {"method": "to", "device": device, "order": control.next_order()}
            )
            return self

        def eval(self) -> "FakeKModel":
            control.kmodel_calls.append({"method": "eval", "order": control.next_order()})
            return self

    class FakeKPipeline:
        def __init__(
            self,
            *,
            lang_code: str,
            repo_id: str,
            model: FakeKModel,
            device: str,
        ) -> None:
            control.pipeline_constructions.append(
                {
                    "lang_code": lang_code,
                    "repo_id": repo_id,
                    "model": model,
                    "device": device,
                    "order": control.next_order(),
                }
            )

        def __call__(
            self, text: str, *, voice: str, speed: float
        ) -> list[tuple[str, str, FakeNdArray]]:
            control.unit_counter += 1
            unit = control.unit_counter
            control.pipeline_calls.append(
                {
                    "unit": unit,
                    "text": text,
                    "voice": voice,
                    "speed": speed,
                    "order": control.next_order(),
                }
            )
            if unit in control.fail_at_unit:
                raise RuntimeError("synthesis failed")
            chunk_count = control.chunks_at_unit.get(unit, 1)
            values: list[float] = [] if unit in control.empty_at_unit else [0.1, -0.1, 0.2]
            if unit in control.nan_at_unit:
                values = [math.nan, *values]
            dtype = control.dtype_at_unit.get(unit, FLOAT32)
            ndim = control.dims_at_unit.get(unit, 1)
            audio = FakeNdArray(values, dtype=dtype, ndim=ndim)
            return [("graphemes", "phonemes", audio) for _ in range(chunk_count)]

    fake_kokoro = types.ModuleType("kokoro")
    fake_kokoro.KPipeline = FakeKPipeline  # type: ignore[attr-defined]

    fake_kokoro_model = types.ModuleType("kokoro.model")
    fake_kokoro_model.KModel = FakeKModel  # type: ignore[attr-defined]
    fake_kokoro.model = fake_kokoro_model  # type: ignore[attr-defined]

    fake_spacy = types.ModuleType("spacy")
    fake_spacy_util = types.ModuleType("spacy.util")

    def _is_package(name: str) -> bool:
        return control.spacy_model_installed

    fake_spacy_util.is_package = _is_package  # type: ignore[attr-defined]
    fake_spacy.util = fake_spacy_util  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "numpy", fake_numpy)
    monkeypatch.setitem(sys.modules, "kokoro", fake_kokoro)
    monkeypatch.setitem(sys.modules, "kokoro.model", fake_kokoro_model)
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)
    monkeypatch.setitem(sys.modules, "spacy.util", fake_spacy_util)

    real_version = importlib.metadata.version

    def _fake_version(name: str) -> str:
        if name == "kokoro":
            return control.installed_kokoro_version
        if name == "misaki":
            return control.installed_misaki_version
        if name == "num2words":
            if not control.num2words_installed:
                raise importlib.metadata.PackageNotFoundError(name)
            return "0.5.14"
        if name in {"spacy", "en_core_web_sm"}:
            return "3.8.16" if name == "spacy" else "3.8.0"
        return real_version(name)

    monkeypatch.setattr(importlib.metadata, "version", _fake_version)
    return control


VOICE_BLOCK = {
    "engine": "kokoro",
    "engine_version": "0.9.4",
    "g2p": "misaki",
    "g2p_version": "0.9.4",
    "model_repository": "hexgrad/Kokoro-82M",
    "model_revision": "f3ff3571791e39611d31c381e3a41a3af07b4987",
    "model_weights_sha256": "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4",
    "model_config_sha256": "5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f",
    "voice": "af_heart",
    "voice_pack_sha256": "0ab5709b8ffab19bfd849cd11d98f75b60af7733253ad0d67b12382a102cb4ff",
    "lang_code": "a",
    "speed_percent": 100,
    "sample_rate_hz": 24000,
    "channels": 1,
    "seed": 0,
}
"""The exact locked Phase 28 narrator request -- used verbatim, never re-declared."""


# ---------------------------------------------------------------- audio bridge


def test_the_real_bridge_shape_reaches_pcm16_bytes(fake_stack: Control) -> None:
    """The real audio-array shape converts to built-in floats and reaches pcm16_bytes."""
    audio = FakeNdArray([0.1, -0.2, 0.3])
    values = executor.audio_to_float_list(audio, "x")
    assert values == [0.1, -0.2, 0.3]
    for value in values:
        assert type(value) is float
    payload = executor.pcm16_bytes(values, "x")
    assert len(payload) == len(values) * 2


def test_count_is_preserved(fake_stack: Control) -> None:
    """len(values) == size and len(pcm) == size * 2."""
    audio = FakeNdArray([0.0] * 17)
    values = executor.audio_to_float_list(audio, "x")
    assert len(values) == audio.size == 17
    assert len(executor.pcm16_bytes(values, "x")) == 34


def test_a_python_list_is_refused_on_dtype(fake_stack: Control) -> None:
    """A Python list (which np.asarray widens to float64) is refused on dtype."""
    with pytest.raises(executor.SpeechRefused, match="dtype"):
        executor.audio_to_float_list([0.1, 0.2], "x")


def test_wrong_dtype_is_refused(fake_stack: Control) -> None:
    """An array of the wrong dtype is refused before conversion."""
    audio = FakeNdArray([0.1], dtype=object())
    with pytest.raises(executor.SpeechRefused, match="dtype"):
        executor.audio_to_float_list(audio, "x")


def test_wrong_ndim_is_refused(fake_stack: Control) -> None:
    """A non-1D array is refused before conversion."""
    audio = FakeNdArray([0.1], ndim=2)
    with pytest.raises(executor.SpeechRefused, match="dimensions"):
        executor.audio_to_float_list(audio, "x")


def test_zero_size_is_refused(fake_stack: Control) -> None:
    """A zero-sample array is refused before conversion."""
    audio = FakeNdArray([])
    with pytest.raises(executor.SpeechRefused, match="zero samples"):
        executor.audio_to_float_list(audio, "x")


def test_a_non_finite_sample_is_refused(fake_stack: Control) -> None:
    """A non-finite sample is refused before conversion."""
    audio = FakeNdArray([0.1, math.nan])
    with pytest.raises(executor.SpeechRefused, match="non-finite"):
        executor.audio_to_float_list(audio, "x")


# ---------------------------------------------------------------- one call per unit, seed law


def test_synthesize_unit_makes_exactly_one_engine_call(fake_stack: Control) -> None:
    """synthesize_unit makes exactly one engine invocation."""
    pipeline = executor.build_pipeline(VOICE_BLOCK, weights_path=Path("w"), config_path=Path("c"))
    executor.synthesize_unit(
        pipeline, "hello", voice_pack_path=Path("v"), speed_percent=100, seed=0
    )
    assert len(fake_stack.pipeline_calls) == 1


def test_synthesize_unit_returns_a_non_empty_list_of_finite_floats(
    fake_stack: Control,
) -> None:
    """A real-shaped synthesis call returns a non-empty list of finite built-in floats."""
    pipeline = executor.build_pipeline(VOICE_BLOCK, weights_path=Path("w"), config_path=Path("c"))
    values = executor.synthesize_unit(
        pipeline, "hello", voice_pack_path=Path("v"), speed_percent=100, seed=0
    )
    assert len(values) >= 1
    assert all(type(value) is float for value in values)
    assert all(math.isfinite(value) for value in values)


def test_manual_seed_is_called_once_per_unit_immediately_before_synthesis(
    fake_stack: Control,
) -> None:
    """manual_seed is called once per unit, immediately before that unit's synthesis."""
    pipeline = executor.build_pipeline(VOICE_BLOCK, weights_path=Path("w"), config_path=Path("c"))
    for text in ("one", "two", "three"):
        executor.synthesize_unit(
            pipeline, text, voice_pack_path=Path("v"), speed_percent=100, seed=0
        )
    assert len(fake_stack.manual_seed_calls) == 3
    assert all(seed == 0 for seed, _order in fake_stack.manual_seed_calls)
    seed_orders = [order for _seed, order in fake_stack.manual_seed_calls]
    call_orders = [call["order"] for call in fake_stack.pipeline_calls]
    for seed_order, call_order in zip(seed_orders, call_orders, strict=True):
        assert seed_order == call_order - 1


def test_pipeline_construction_precedes_the_first_seed_call(fake_stack: Control) -> None:
    """Pipeline construction happens strictly before the first manual_seed call."""
    pipeline = executor.build_pipeline(VOICE_BLOCK, weights_path=Path("w"), config_path=Path("c"))
    executor.synthesize_unit(
        pipeline, "hello", voice_pack_path=Path("v"), speed_percent=100, seed=0
    )
    construction_order = fake_stack.pipeline_constructions[0]["order"]
    first_seed_order = fake_stack.manual_seed_calls[0][1]
    assert construction_order < first_seed_order


def test_grad_is_disabled_once_at_construction(fake_stack: Control) -> None:
    """torch.set_grad_enabled(False) is called once, in build_pipeline."""
    executor.build_pipeline(VOICE_BLOCK, weights_path=Path("w"), config_path=Path("c"))
    assert fake_stack.grad_enabled_calls == [False]


def test_the_pipeline_is_built_from_local_paths_and_the_voice_block(
    fake_stack: Control,
) -> None:
    """build_pipeline builds a KModel from local paths, then a KPipeline around that model."""
    executor.build_pipeline(VOICE_BLOCK, weights_path=Path("w"), config_path=Path("c"))
    kmodel = fake_stack.kmodel_constructions[0]
    assert kmodel["repo_id"] == VOICE_BLOCK["model_repository"]
    assert kmodel["config"] == "c"
    assert kmodel["model"] == "w"
    kmodel_calls = fake_stack.kmodel_calls
    assert [call["method"] for call in kmodel_calls] == ["to", "eval"]
    assert kmodel_calls[0]["device"] == "cpu"
    construction = fake_stack.pipeline_constructions[0]
    assert construction["lang_code"] == VOICE_BLOCK["lang_code"]
    assert construction["repo_id"] == VOICE_BLOCK["model_repository"]
    assert construction["model"] is fake_stack.kmodel_instances[0]
    assert construction["device"] == "cpu"
    assert kmodel_calls[0]["order"] < kmodel_calls[1]["order"] < construction["order"]
    assert set(construction) == {"lang_code", "repo_id", "model", "device", "order"}


def test_lang_code_comes_from_the_voice_block_not_a_literal(fake_stack: Control) -> None:
    """lang_code is read from the verified voice block, never from a duplicate literal."""
    block = dict(VOICE_BLOCK, lang_code="x")
    executor.build_pipeline(block, weights_path=Path("w"), config_path=Path("c"))
    assert fake_stack.pipeline_constructions[0]["lang_code"] == "x"


@pytest.mark.parametrize(
    ("knob", "value", "match"),
    [
        ("chunks_at_unit", {1: 2}, "chunks"),
        ("dtype_at_unit", {1: object()}, "dtype"),
        ("dims_at_unit", {1: 2}, "dimensions"),
        ("nan_at_unit", {1}, "non-finite"),
        ("empty_at_unit", {1}, "zero samples"),
    ],
)
def test_every_output_law_refuses(
    fake_stack: Control, knob: str, value: object, match: str
) -> None:
    """Every output law -- chunk count, dtype, ndim, non-finite, zero samples -- refuses."""
    if knob in {"nan_at_unit", "empty_at_unit"}:
        getattr(fake_stack, knob).update(value)
    else:
        getattr(fake_stack, knob).update(value)
    pipeline = executor.build_pipeline(VOICE_BLOCK, weights_path=Path("w"), config_path=Path("c"))
    with pytest.raises(executor.SpeechRefused, match=match):
        executor.synthesize_unit(
            pipeline, "hello", voice_pack_path=Path("v"), speed_percent=100, seed=0
        )


def test_a_failed_synthesis_call_propagates(fake_stack: Control) -> None:
    """A synthesis-time failure propagates rather than being swallowed."""
    fake_stack.fail_at_unit.add(1)
    pipeline = executor.build_pipeline(VOICE_BLOCK, weights_path=Path("w"), config_path=Path("c"))
    with pytest.raises(RuntimeError, match="synthesis failed"):
        executor.synthesize_unit(
            pipeline, "hello", voice_pack_path=Path("v"), speed_percent=100, seed=0
        )


# ---------------------------------------------------------------- preflights


def test_require_engine_versions_accepts_the_matching_pins(fake_stack: Control) -> None:
    """require_engine_versions accepts installed versions matching the plan's pins."""
    executor.require_engine_versions(VOICE_BLOCK)


def test_require_engine_versions_refuses_a_wrong_kokoro_version(fake_stack: Control) -> None:
    """require_engine_versions refuses a wrong installed kokoro version."""
    fake_stack.installed_kokoro_version = "0.9.3"
    with pytest.raises(executor.VoicePlanRefused, match="engine_version"):
        executor.require_engine_versions(VOICE_BLOCK)


def test_require_engine_versions_refuses_a_wrong_misaki_version(fake_stack: Control) -> None:
    """require_engine_versions refuses a wrong installed misaki version."""
    fake_stack.installed_misaki_version = "0.9.3"
    with pytest.raises(executor.VoicePlanRefused, match="g2p_version"):
        executor.require_engine_versions(VOICE_BLOCK)


def test_require_engine_versions_hard_refuses_the_real_substitute_engine_without_the_opt_in(
    fake_stack: Control,
) -> None:
    """The real installed kokoro==0.2.2/misaki==0.7.4 build is still a hard refusal by default."""
    fake_stack.installed_kokoro_version = "0.2.2"
    fake_stack.installed_misaki_version = "0.7.4"
    with pytest.raises(executor.VoicePlanRefused, match="engine_version"):
        executor.require_engine_versions(VOICE_BLOCK)


def test_require_engine_versions_accepts_the_substitute_engine_with_the_explicit_opt_in(
    fake_stack: Control, capsys: pytest.CaptureFixture[str]
) -> None:
    """allow_provisional_engine=True accepts the substitute build and warns honestly on stderr."""
    fake_stack.installed_kokoro_version = "0.2.2"
    fake_stack.installed_misaki_version = "0.7.4"
    executor.require_engine_versions(VOICE_BLOCK, allow_provisional_engine=True)
    captured = capsys.readouterr()
    assert "PREVIEW-ONLY" in captured.err
    assert "0.2.2" in captured.err
    assert "no claim is made that the pinned engine executed" in captured.err
    assert captured.out == ""


def test_require_engine_versions_prints_no_warning_for_the_exact_pins(
    fake_stack: Control, capsys: pytest.CaptureFixture[str]
) -> None:
    """An exact pin match is the reviewed build: no provisional warning is printed."""
    executor.require_engine_versions(VOICE_BLOCK, allow_provisional_engine=True)
    captured = capsys.readouterr()
    assert captured.err == ""


def test_require_local_g2p_assets_accepts_the_installed_stack(fake_stack: Control) -> None:
    """require_local_g2p_assets accepts a locally installed spaCy model and num2words."""
    executor.require_local_g2p_assets()


def test_require_local_g2p_assets_refuses_a_missing_spacy_model(fake_stack: Control) -> None:
    """require_local_g2p_assets refuses a missing local spaCy model."""
    fake_stack.spacy_model_installed = False
    with pytest.raises(executor.VoicePlanRefused, match="en_core_web_sm"):
        executor.require_local_g2p_assets()


def test_require_local_g2p_assets_refuses_a_missing_num2words(fake_stack: Control) -> None:
    """require_local_g2p_assets refuses a missing local num2words."""
    fake_stack.num2words_installed = False
    with pytest.raises(executor.VoicePlanRefused, match="num2words"):
        executor.require_local_g2p_assets()


def test_require_local_model_assets_accepts_matching_digests(tmp_path: Path) -> None:
    """require_local_model_assets accepts local files matching the plan's pinned digests."""
    from living_diorama.persistence.schema.state_hash import sha256_hex

    weights = tmp_path / "weights.pth"
    config = tmp_path / "config.json"
    pack = tmp_path / "voice.pt"
    weights.write_bytes(b"weights-payload")
    config.write_bytes(b"config-payload")
    pack.write_bytes(b"pack-payload")
    block = {
        "model_weights_sha256": sha256_hex(weights.read_bytes()),
        "model_config_sha256": sha256_hex(config.read_bytes()),
        "voice_pack_sha256": sha256_hex(pack.read_bytes()),
    }
    executor.require_local_model_assets(
        block, weights_path=weights, config_path=config, voice_pack_path=pack
    )


def test_require_local_model_assets_refuses_a_nonexistent_path(tmp_path: Path) -> None:
    """require_local_model_assets refuses a nonexistent local asset path."""
    block = {
        "model_weights_sha256": "0" * 64,
        "model_config_sha256": "0" * 64,
        "voice_pack_sha256": "0" * 64,
    }
    with pytest.raises(executor.VoicePlanRefused, match="does not exist"):
        executor.require_local_model_assets(
            block,
            weights_path=tmp_path / "missing.pth",
            config_path=tmp_path / "missing.json",
            voice_pack_path=tmp_path / "missing.pt",
        )


def test_require_local_model_assets_refuses_a_wrong_digest(tmp_path: Path) -> None:
    """require_local_model_assets refuses a local file whose digest disagrees with the plan."""
    weights = tmp_path / "weights.pth"
    weights.write_bytes(b"weights-payload")
    block = {"model_weights_sha256": "0" * 64}
    with pytest.raises(executor.VoicePlanRefused, match="hashes to"):
        executor.require_local_model_assets(
            block, weights_path=weights, config_path=weights, voice_pack_path=weights
        )


# ---------------------------------------------------------------- offline environment


def test_offline_environment_variables_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """The offline-environment variables are set exactly, before any third-party import."""
    for key in executor._OFFLINE_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(key, raising=False)
    executor._require_offline_environment()
    for key, value in executor._OFFLINE_ENVIRONMENT_VARIABLES.items():
        assert os.environ[key] == value


# ---------------------------------------------------------------- CLI flags


def test_the_executor_accepts_exactly_twelve_required_flags_plus_the_optional_profile() -> None:
    """The executor's CLI accepts exactly twelve required flags plus the optional profile."""
    argv = [
        "--voice-plan",
        "a",
        "--realization",
        "b",
        "--presentation",
        "c",
        "--delivery",
        "d",
        "--narration",
        "e",
        "--shots",
        "f",
        "--story",
        "g",
        "--export",
        "h",
        "--model-weights",
        "i",
        "--model-config",
        "j",
        "--voice-pack",
        "k",
        "--output-root",
        "l",
    ]
    namespace = executor.parse_arguments(argv)
    destinations = set(vars(namespace))
    assert destinations == {
        "voice_plan",
        "realization",
        "presentation",
        "delivery",
        "narration",
        "shots",
        "story",
        "export",
        "model_weights",
        "model_config",
        "voice_pack",
        "output_root",
        "presentation_profile",
    }
    assert len(destinations) == 13
    # Omitting the flag preserves today's exact behavior: the default is None,
    # so the gate keeps its motion_windows-driven V2/V1 inference.
    assert namespace.presentation_profile is None


def test_presentation_profile_flag_accepts_only_the_reviewed_choices_and_defaults_to_none() -> None:
    """--presentation-profile accepts v1/v2/v3, refuses anything else, and defaults to None."""
    argv = [
        "--voice-plan",
        "a",
        "--realization",
        "b",
        "--presentation",
        "c",
        "--delivery",
        "d",
        "--narration",
        "e",
        "--shots",
        "f",
        "--story",
        "g",
        "--export",
        "h",
        "--model-weights",
        "i",
        "--model-config",
        "j",
        "--voice-pack",
        "k",
        "--output-root",
        "l",
    ]
    assert executor.parse_arguments(argv).presentation_profile is None
    for choice in ("v1", "v2", "v3", "v4"):
        parsed = executor.parse_arguments(argv + ["--presentation-profile", choice])
        assert parsed.presentation_profile == choice
    with pytest.raises(SystemExit):
        executor.parse_arguments(argv + ["--presentation-profile", "v9"])


def test_a_missing_required_flag_is_refused() -> None:
    """A missing required flag is refused by argparse."""
    with pytest.raises(SystemExit):
        executor.parse_arguments(["--voice-plan", "a"])


def test_presentation_profile_threads_through_to_the_source_gate(
    fake_stack: Control,
    sources_ep0: tuple,
    plan_ep0: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """--presentation-profile reaches the source gate as a keyword; omission passes None."""
    seen: list[dict[str, object]] = []

    def _recording_gate(*args: object, **kwargs: object) -> object:
        seen.append(dict(kwargs))
        return None

    monkeypatch.setattr(executor, "validate_episode_voice_plan_against_sources", _recording_gate)
    monkeypatch.setattr(executor, "require_local_model_assets", lambda *a, **k: None)

    paths = _write_documents(tmp_path, sources_ep0, plan_ep0)
    argv = [
        "--voice-plan",
        str(paths["voice_plan"]),
        "--realization",
        str(paths["realization"]),
        "--presentation",
        str(paths["presentation"]),
        "--delivery",
        str(paths["delivery"]),
        "--narration",
        str(paths["narration"]),
        "--shots",
        str(paths["shots"]),
        "--story",
        str(paths["story"]),
        "--export",
        str(paths["export"]),
        "--model-weights",
        str(tmp_path / "w"),
        "--model-config",
        str(tmp_path / "c"),
        "--voice-pack",
        str(tmp_path / "v"),
    ]

    # Omitted: today's exact behavior -- the gate sees presentation_profile=None.
    exit_code = executor.main(argv + ["--output-root", str(tmp_path / "voice")])
    assert exit_code == 0
    assert seen[0]["presentation_profile"] is None

    # Explicit v3 threads through as the keyword argument.
    exit_code = executor.main(
        argv + ["--presentation-profile", "v3", "--output-root", str(tmp_path / "voice_v3")]
    )
    assert exit_code == 0
    assert seen[1]["presentation_profile"] == "v3"


# ---------------------------------------------------------------- staging ownership


def test_a_truthful_staging_tree_is_accepted_and_discarded(tmp_path: Path) -> None:
    """A truthful, wholly-owned staging tree is accepted, then discarded."""
    from living_diorama.voice_execution.voice_execution_spec import (
        SPEECH_DIRECTORY,
        VOICE_PLAN_FILENAME,
        unit_audio_filename,
    )

    staging = tmp_path / "episode_0000_baseline.partial"
    (staging / SPEECH_DIRECTORY).mkdir(parents=True)
    (staging / VOICE_PLAN_FILENAME).write_bytes(b"{}")
    (staging / SPEECH_DIRECTORY / unit_audio_filename(1)).write_bytes(b"\x00")
    executor.require_owned_staging(
        staging,
        expected_parent=tmp_path,
        expected_name="episode_0000_baseline.partial",
        unit_count=1,
    )
    executor.discard_owned_staging(
        staging,
        expected_parent=tmp_path,
        expected_name="episode_0000_baseline.partial",
        unit_count=1,
    )
    assert not staging.exists()


def test_discard_owned_staging_is_a_no_op_when_absent(tmp_path: Path) -> None:
    """discard_owned_staging is a no-op when the staging directory does not exist."""
    executor.discard_owned_staging(
        tmp_path / "does_not_exist.partial",
        expected_parent=tmp_path,
        expected_name="does_not_exist.partial",
        unit_count=1,
    )


def test_a_wrong_expected_parent_refuses_and_leaves_the_tree_untouched(tmp_path: Path) -> None:
    """A correct name under the wrong expected parent refuses, tree untouched."""
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    staging = real_parent / "episode_0000_baseline.partial"
    staging.mkdir()
    other_parent = tmp_path / "other"
    other_parent.mkdir()
    with pytest.raises(executor.VoiceDirectoryRefused, match="output root"):
        executor.require_owned_staging(
            staging,
            expected_parent=other_parent,
            expected_name="episode_0000_baseline.partial",
            unit_count=0,
        )
    assert staging.exists()


def test_a_wrong_name_refuses(tmp_path: Path) -> None:
    """A staging directory with the wrong name refuses."""
    staging = tmp_path / "wrong_name.partial"
    staging.mkdir()
    with pytest.raises(executor.VoiceDirectoryRefused, match="name"):
        executor.require_owned_staging(
            staging,
            expected_parent=tmp_path,
            expected_name="episode_0000_baseline.partial",
            unit_count=0,
        )


def test_a_foreign_top_level_entry_refuses(tmp_path: Path) -> None:
    """A foreign top-level entry inside staging refuses; nothing is deleted."""
    staging = tmp_path / "episode_0000_baseline.partial"
    staging.mkdir()
    (staging / "intruder.txt").write_bytes(b"x")
    with pytest.raises(executor.VoiceDirectoryRefused, match="not owned"):
        executor.require_owned_staging(
            staging,
            expected_parent=tmp_path,
            expected_name="episode_0000_baseline.partial",
            unit_count=0,
        )
    assert (staging / "intruder.txt").exists()


def test_a_foreign_file_inside_speech_refuses(tmp_path: Path) -> None:
    """A foreign file inside speech/ refuses."""
    from living_diorama.voice_execution.voice_execution_spec import SPEECH_DIRECTORY

    staging = tmp_path / "episode_0000_baseline.partial"
    (staging / SPEECH_DIRECTORY).mkdir(parents=True)
    (staging / SPEECH_DIRECTORY / "not_a_unit.wav").write_bytes(b"x")
    with pytest.raises(executor.VoiceDirectoryRefused, match="not an owned speech file"):
        executor.require_owned_staging(
            staging,
            expected_parent=tmp_path,
            expected_name="episode_0000_baseline.partial",
            unit_count=1,
        )


def test_a_nested_directory_inside_speech_refuses(tmp_path: Path) -> None:
    """A nested directory inside speech/ refuses -- never permitted."""
    from living_diorama.voice_execution.voice_execution_spec import SPEECH_DIRECTORY

    staging = tmp_path / "episode_0000_baseline.partial"
    (staging / SPEECH_DIRECTORY / "nested").mkdir(parents=True)
    with pytest.raises(executor.VoiceDirectoryRefused, match="directory inside speech"):
        executor.require_owned_staging(
            staging,
            expected_parent=tmp_path,
            expected_name="episode_0000_baseline.partial",
            unit_count=1,
        )


def test_a_unit_number_beyond_unit_count_refuses(tmp_path: Path) -> None:
    """A speech file naming a unit beyond unit_count refuses."""
    from living_diorama.voice_execution.voice_execution_spec import (
        SPEECH_DIRECTORY,
        unit_audio_filename,
    )

    staging = tmp_path / "episode_0000_baseline.partial"
    (staging / SPEECH_DIRECTORY).mkdir(parents=True)
    (staging / SPEECH_DIRECTORY / unit_audio_filename(9)).write_bytes(b"x")
    with pytest.raises(executor.VoiceDirectoryRefused, match="not an owned speech file"):
        executor.require_owned_staging(
            staging,
            expected_parent=tmp_path,
            expected_name="episode_0000_baseline.partial",
            unit_count=1,
        )


def test_a_junction_staging_directory_refuses_without_being_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A junction (simulated via monkeypatch) refuses without being followed or removed."""
    staging = tmp_path / "episode_0000_baseline.partial"
    staging.mkdir()
    monkeypatch.setattr(Path, "is_junction", lambda self: self == staging)
    with pytest.raises(executor.VoiceDirectoryRefused, match="symlink or junction"):
        executor.require_owned_staging(
            staging,
            expected_parent=tmp_path,
            expected_name="episode_0000_baseline.partial",
            unit_count=0,
        )
    assert staging.exists()


def test_indirection_helper_checks_both_predicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_is_path_indirection returns the disjunction of is_symlink and is_junction."""
    plain = tmp_path / "plain"
    plain.mkdir()
    assert executor._is_path_indirection(plain) is False
    monkeypatch.setattr(Path, "is_junction", lambda self: self == plain)
    assert executor._is_path_indirection(plain) is True


# ---------------------------------------------------------------- publish_episode / main


def _write_documents(tmp_path: Path, sources: tuple, plan: dict) -> dict[str, Path]:
    realization, presentation, delivery, narration, shots, story, export = sources
    paths = {}
    for name, document in (
        ("voice_plan", plan),
        ("realization", realization),
        ("presentation", presentation),
        ("delivery", delivery),
        ("narration", narration),
        ("shots", shots),
        ("story", story),
        ("export", export),
    ):
        path = tmp_path / f"{name}.json"
        path.write_bytes(dumps_canonical(document, name))
        paths[name] = path
    return paths


def test_publish_episode_writes_a_truthful_directory(
    fake_stack: Control,
    sources_ep0: tuple,
    plan_ep0: dict,
    voice_environment: dict,
    tmp_path: Path,
) -> None:
    """publish_episode writes a truthful, complete, auditable directory."""
    from living_diorama.persistence.json_codec import dumps_canonical as dc
    from living_diorama.voice_execution import audit_voice_directory

    realization = sources_ep0[0]
    pipeline = executor.build_pipeline(VOICE_BLOCK, weights_path=Path("w"), config_path=Path("c"))
    plan_bytes = dc(plan_ep0, "voice plan")
    output_root = tmp_path / "voice"
    final_dir = executor.publish_episode(
        voice_plan=plan_ep0,
        voice_plan_bytes=plan_bytes,
        realization_plan=realization,
        pipeline=pipeline,
        voice_pack_path=Path("v"),
        environment=voice_environment,
        output_root=output_root,
    )
    assert final_dir.exists()
    assert audit_voice_directory(final_dir) == []
    # No litter survives a clean publish.
    assert not (output_root / f"{final_dir.name}.partial").exists()


def test_a_crash_mid_episode_leaves_no_final_directory_or_manifest(
    fake_stack: Control,
    sources_ep1: tuple,
    plan_ep1: dict,
    voice_environment: dict,
    tmp_path: Path,
) -> None:
    """A crash partway through leaves no final directory and no manifest."""
    from living_diorama.persistence.json_codec import dumps_canonical as dc

    realization = sources_ep1[0]
    fake_stack.fail_at_unit.add(2)
    pipeline = executor.build_pipeline(VOICE_BLOCK, weights_path=Path("w"), config_path=Path("c"))
    plan_bytes = dc(plan_ep1, "voice plan")
    output_root = tmp_path / "voice"
    with pytest.raises(RuntimeError, match="synthesis failed"):
        executor.publish_episode(
            voice_plan=plan_ep1,
            voice_plan_bytes=plan_bytes,
            realization_plan=realization,
            pipeline=pipeline,
            voice_pack_path=Path("v"),
            environment=voice_environment,
            output_root=output_root,
        )
    assert not any(output_root.glob("episode_*")) or all(
        p.name.endswith(".partial") for p in output_root.glob("episode_*")
    )
    for candidate in output_root.glob("episode_*"):
        assert candidate.name.endswith(".partial")
        assert not (candidate / "episode_voice_manifest.json").exists()


def test_an_existing_verified_final_directory_is_a_no_op(
    fake_stack: Control,
    sources_ep0: tuple,
    plan_ep0: dict,
    voice_environment: dict,
    tmp_path: Path,
) -> None:
    """A pre-existing, verified, complete final directory is a no-op re-run."""
    from living_diorama.persistence.json_codec import dumps_canonical as dc

    realization = sources_ep0[0]
    pipeline = executor.build_pipeline(VOICE_BLOCK, weights_path=Path("w"), config_path=Path("c"))
    plan_bytes = dc(plan_ep0, "voice plan")
    output_root = tmp_path / "voice"

    first = executor.publish_episode(
        voice_plan=plan_ep0,
        voice_plan_bytes=plan_bytes,
        realization_plan=realization,
        pipeline=pipeline,
        voice_pack_path=Path("v"),
        environment=voice_environment,
        output_root=output_root,
    )
    manifest_before = (first / "episode_voice_manifest.json").read_bytes()
    calls_before = len(fake_stack.pipeline_calls)

    second = executor.publish_episode(
        voice_plan=plan_ep0,
        voice_plan_bytes=plan_bytes,
        realization_plan=realization,
        pipeline=pipeline,
        voice_pack_path=Path("v"),
        environment=voice_environment,
        output_root=output_root,
    )
    assert second == first
    assert (second / "episode_voice_manifest.json").read_bytes() == manifest_before
    assert len(fake_stack.pipeline_calls) == calls_before  # no re-synthesis


def test_an_existing_mismatched_final_directory_is_refused_and_untouched(
    fake_stack: Control,
    sources_ep0: tuple,
    plan_ep0: dict,
    voice_environment: dict,
    tmp_path: Path,
) -> None:
    """A pre-existing final directory executing a different plan is refused; nothing deleted."""
    from living_diorama.persistence.json_codec import dumps_canonical as dc

    realization = sources_ep0[0]
    pipeline = executor.build_pipeline(VOICE_BLOCK, weights_path=Path("w"), config_path=Path("c"))
    plan_bytes = dc(plan_ep0, "voice plan")
    output_root = tmp_path / "voice"
    final_dir = executor.publish_episode(
        voice_plan=plan_ep0,
        voice_plan_bytes=plan_bytes,
        realization_plan=realization,
        pipeline=pipeline,
        voice_pack_path=Path("v"),
        environment=voice_environment,
        output_root=output_root,
    )
    before = {p: p.read_bytes() for p in final_dir.rglob("*") if p.is_file()}

    # Same plan content, but a byte-different encoding forces a distinct
    # digest -- publish_episode must refuse rather than overwrite the
    # already-published, differently-bound directory.
    with pytest.raises(executor.VoiceDirectoryRefused, match="different voice plan|already exists"):
        executor.publish_episode(
            voice_plan=plan_ep0,
            voice_plan_bytes=plan_bytes + b" ",
            realization_plan=realization,
            pipeline=pipeline,
            voice_pack_path=Path("v"),
            environment=voice_environment,
            output_root=output_root,
        )
    after = {p: p.read_bytes() for p in final_dir.rglob("*") if p.is_file()}
    assert before == after


def test_a_foreign_entry_inside_staging_refuses_the_publish(
    fake_stack: Control,
    sources_ep0: tuple,
    plan_ep0: dict,
    voice_environment: dict,
    tmp_path: Path,
) -> None:
    """A foreign entry surviving inside staging refuses the publish rather than being emptied."""
    from living_diorama.persistence.json_codec import dumps_canonical as dc
    from living_diorama.voice_execution.voice_execution_spec import voice_execution_id

    realization = sources_ep0[0]
    pipeline = executor.build_pipeline(VOICE_BLOCK, weights_path=Path("w"), config_path=Path("c"))
    plan_bytes = dc(plan_ep0, "voice plan")
    output_root = tmp_path / "voice"
    output_root.mkdir()
    source = plan_ep0["source"]
    final_name = voice_execution_id(
        mode=source["mode"], episode=source["episode"], previous_episode=source["previous_episode"]
    )
    staging = output_root / f"{final_name}.partial"
    staging.mkdir()
    (staging / "intruder.txt").write_bytes(b"x")

    with pytest.raises(executor.VoiceDirectoryRefused):
        executor.publish_episode(
            voice_plan=plan_ep0,
            voice_plan_bytes=plan_bytes,
            realization_plan=realization,
            pipeline=pipeline,
            voice_pack_path=Path("v"),
            environment=voice_environment,
            output_root=output_root,
        )
    assert (staging / "intruder.txt").exists()


def test_a_handled_speech_refusal_after_staging_cleans_owned_staging(
    fake_stack: Control,
    sources_ep0: tuple,
    plan_ep0: dict,
    voice_environment: dict,
    tmp_path: Path,
) -> None:
    """A handled SpeechRefused raised after staging exists discards this run's owned staging."""
    from living_diorama.persistence.json_codec import dumps_canonical as dc
    from living_diorama.voice_execution.voice_execution_spec import voice_execution_id

    realization = sources_ep0[0]
    fake_stack.nan_at_unit.add(1)
    pipeline = executor.build_pipeline(VOICE_BLOCK, weights_path=Path("w"), config_path=Path("c"))
    plan_bytes = dc(plan_ep0, "voice plan")
    output_root = tmp_path / "voice"
    source = plan_ep0["source"]
    final_name = voice_execution_id(
        mode=source["mode"], episode=source["episode"], previous_episode=source["previous_episode"]
    )

    with pytest.raises(executor.SpeechRefused, match="non-finite"):
        executor.publish_episode(
            voice_plan=plan_ep0,
            voice_plan_bytes=plan_bytes,
            realization_plan=realization,
            pipeline=pipeline,
            voice_pack_path=Path("v"),
            environment=voice_environment,
            output_root=output_root,
        )
    assert not (output_root / final_name).exists()
    assert not (output_root / f"{final_name}.partial").exists()


def test_a_handled_voice_plan_refusal_after_staging_cleans_owned_staging(
    fake_stack: Control,
    sources_ep1: tuple,
    plan_ep1: dict,
    voice_environment: dict,
    tmp_path: Path,
) -> None:
    """A handled VoicePlanRefused raised after staging exists discards owned staging."""
    import copy

    from living_diorama.persistence.json_codec import dumps_canonical as dc
    from living_diorama.voice_execution.voice_execution_spec import voice_execution_id

    realization = copy.deepcopy(sources_ep1[0])
    realization["realizations"] = realization["realizations"][:-1]
    pipeline = executor.build_pipeline(VOICE_BLOCK, weights_path=Path("w"), config_path=Path("c"))
    plan_bytes = dc(plan_ep1, "voice plan")
    output_root = tmp_path / "voice"
    source = plan_ep1["source"]
    final_name = voice_execution_id(
        mode=source["mode"], episode=source["episode"], previous_episode=source["previous_episode"]
    )

    with pytest.raises(executor.VoicePlanRefused, match="realizes"):
        executor.publish_episode(
            voice_plan=plan_ep1,
            voice_plan_bytes=plan_bytes,
            realization_plan=realization,
            pipeline=pipeline,
            voice_pack_path=Path("v"),
            environment=voice_environment,
            output_root=output_root,
        )
    assert not (output_root / final_name).exists()
    assert not (output_root / f"{final_name}.partial").exists()


def test_exactly_one_shutil_rmtree_call_site_in_the_executor_script() -> None:
    """shutil.rmtree appears exactly once in the executor script, inside discard_owned_staging."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    call_sites: list[int] = []
    enclosing_by_line: dict[int, str | None] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "rmtree"
                    and isinstance(inner.func.value, ast.Name)
                    and inner.func.value.id == "shutil"
                ):
                    call_sites.append(inner.lineno)
                    enclosing_by_line[inner.lineno] = node.name
    assert len(call_sites) == 1
    assert enclosing_by_line[call_sites[0]] == "discard_owned_staging"


# ---------------------------------------------------------------- main() orchestration


def test_main_calls_the_gate_before_build_pipeline_before_publish(
    fake_stack: Control,
    sources_ep0: tuple,
    plan_ep0: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """main() runs the full Phase 28 gate, then build_pipeline, then publish_episode, in order."""
    calls: list[str] = []

    real_gate = executor.validate_episode_voice_plan_against_sources

    def _tracking_gate(*args: object, **kwargs: object) -> object:
        calls.append("gate")
        return real_gate(*args, **kwargs)

    real_build_pipeline = executor.build_pipeline

    def _tracking_build_pipeline(*args: object, **kwargs: object) -> object:
        calls.append("build_pipeline")
        return real_build_pipeline(*args, **kwargs)

    real_publish = executor.publish_episode

    def _tracking_publish(*args: object, **kwargs: object) -> object:
        calls.append("publish_episode")
        return real_publish(*args, **kwargs)

    monkeypatch.setattr(executor, "validate_episode_voice_plan_against_sources", _tracking_gate)
    monkeypatch.setattr(executor, "build_pipeline", _tracking_build_pipeline)
    monkeypatch.setattr(executor, "publish_episode", _tracking_publish)
    monkeypatch.setattr(executor, "require_local_model_assets", lambda *a, **k: None)

    paths = _write_documents(tmp_path, sources_ep0, plan_ep0)
    output_root = tmp_path / "voice"
    argv = [
        "--voice-plan",
        str(paths["voice_plan"]),
        "--realization",
        str(paths["realization"]),
        "--presentation",
        str(paths["presentation"]),
        "--delivery",
        str(paths["delivery"]),
        "--narration",
        str(paths["narration"]),
        "--shots",
        str(paths["shots"]),
        "--story",
        str(paths["story"]),
        "--export",
        str(paths["export"]),
        "--model-weights",
        str(tmp_path / "w"),
        "--model-config",
        str(tmp_path / "c"),
        "--voice-pack",
        str(tmp_path / "v"),
        "--output-root",
        str(output_root),
    ]
    exit_code = executor.main(argv)
    assert exit_code == 0
    assert calls == ["gate", "build_pipeline", "publish_episode"]


def test_main_threads_the_provisional_opt_in_to_the_engine_gate(
    fake_stack: Control,
    sources_ep0: tuple,
    plan_ep0: dict,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """A preview caller can pass allow_provisional_engine=True through main."""
    fake_stack.installed_kokoro_version = "0.2.2"
    fake_stack.installed_misaki_version = "0.7.4"
    monkeypatch.setattr(executor, "require_local_model_assets", lambda *a, **k: None)
    paths = _write_documents(tmp_path, sources_ep0, plan_ep0)
    argv = [
        "--voice-plan",
        str(paths["voice_plan"]),
        "--realization",
        str(paths["realization"]),
        "--presentation",
        str(paths["presentation"]),
        "--delivery",
        str(paths["delivery"]),
        "--narration",
        str(paths["narration"]),
        "--shots",
        str(paths["shots"]),
        "--story",
        str(paths["story"]),
        "--export",
        str(paths["export"]),
        "--model-weights",
        str(tmp_path / "w"),
        "--model-config",
        str(tmp_path / "c"),
        "--voice-pack",
        str(tmp_path / "v"),
        "--output-root",
        str(tmp_path / "voice"),
    ]
    exit_code = executor.main(argv, allow_provisional_engine=True)
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "PREVIEW-ONLY" in captured.err


def test_main_refuses_the_substitute_engine_without_the_opt_in(
    fake_stack: Control,
    sources_ep0: tuple,
    plan_ep0: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Without the opt-in, main hard-refuses the substitute engine before any synthesis."""
    fake_stack.installed_kokoro_version = "0.2.2"
    fake_stack.installed_misaki_version = "0.7.4"
    monkeypatch.setattr(executor, "require_local_model_assets", lambda *a, **k: None)
    paths = _write_documents(tmp_path, sources_ep0, plan_ep0)
    argv = [
        "--voice-plan",
        str(paths["voice_plan"]),
        "--realization",
        str(paths["realization"]),
        "--presentation",
        str(paths["presentation"]),
        "--delivery",
        str(paths["delivery"]),
        "--narration",
        str(paths["narration"]),
        "--shots",
        str(paths["shots"]),
        "--story",
        str(paths["story"]),
        "--export",
        str(paths["export"]),
        "--model-weights",
        str(tmp_path / "w"),
        "--model-config",
        str(tmp_path / "c"),
        "--voice-pack",
        str(tmp_path / "v"),
        "--output-root",
        str(tmp_path / "voice"),
    ]
    exit_code = executor.main(argv)
    assert exit_code == 1
    assert not any((tmp_path / "voice").glob("episode_*"))


def test_publish_episode_has_exactly_one_call_site_inside_main() -> None:
    """publish_episode has exactly one call site in the module, and it lies inside main."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    call_sites: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id == "publish_episode"
                ):
                    call_sites.append((inner.lineno, node.name))
    assert len(call_sites) == 1
    assert call_sites[0][1] == "main"


def test_publish_episode_is_not_re_exported_by_any_canonical_package() -> None:
    """publish_episode is not re-exported by any canonical package __init__."""
    for init_file in (REPO_ROOT / "src" / "living_diorama").rglob("__init__.py"):
        tree = ast.parse(init_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id == "__all__"
                        and isinstance(node.value, ast.List)
                    ):
                        for element in node.value.elts:
                            if isinstance(element, ast.Constant):
                                assert element.value != "publish_episode", init_file
