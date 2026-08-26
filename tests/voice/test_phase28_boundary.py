"""Phase 28 stays inside its boundary, proven by parsing the sources.

Phase 28 owns one responsibility -- binding each locked realized sentence and
presentation window to the one reviewed narrator request, and deriving the
exact integer audio capacity that request has to fit inside. Everything a
reader might reasonably expect it to grow into is somebody else's phase:
real speech synthesis and measurement; produced audio bytes, waveform
storage, PCM or container encoding; captions and subtitles; mixing,
mastering, editing, packaging and publishing; any re-direction of the
cameras Phase 22 chose; any reach into Phase 23's frames or manifest; and any
runtime language model at all. It also never becomes a second wording
authority: it binds the exact Language Realization Plan its voice units name,
but it never reads a realized sentence, a narration sentence, or a memory
fact's summary -- with **zero carve-outs**, stricter than every phase before
it, because Phase 28 has no structural reason to touch prose at all (unlike
Phase 26 and Phase 27, which each granted themselves exactly one explicit
exemption for ``text_source`` or an evidence check).

These are reach rules, not a claim that these files are frozen. The guard
proves what the voice modules may *touch*: what they import, whether they
write, what vocabulary they define, and -- this phase's own sharpest new rule
-- that no upstream window or realization truth becomes authoritative before
the one locked upstream source-verification gate has actually run, and that
no ``measured_samples`` field exists anywhere for a future forgery to act on.
Every guard is exercised against a deliberately bad synthetic file, because a
guard nobody has seen fail is a guard nobody has tested.
"""

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "src" / "living_diorama" / "voice"
CLI = REPO_ROOT / "src" / "living_diorama" / "cli"
TESTS = Path(__file__).parent

PURE_MODULES = (
    PACKAGE / "__init__.py",
    PACKAGE / "voice_cross_check.py",
    PACKAGE / "voice_planner.py",
    PACKAGE / "voice_schema_v1.py",
    PACKAGE / "voice_spec.py",
)
"""Every engine module Phase 28 adds, named one by one.

A glob would quietly stop guarding a module somebody renamed, and would
quietly start guarding somebody else's.
"""

CLI_MODULES = (CLI / "build_voice_plan.py",)
PHASE28_MODULES = (*PURE_MODULES, *CLI_MODULES)

PHASE28_TEST_FILES = (
    TESTS / "__init__.py",
    TESTS / "conftest.py",
    TESTS / "test_phase28_boundary.py",
    TESTS / "test_voice_cli.py",
    TESTS / "test_voice_cross_check.py",
    TESTS / "test_voice_determinism.py",
    TESTS / "test_voice_planner.py",
    TESTS / "test_voice_schema.py",
    TESTS / "test_voice_spec.py",
)

PHASE28_FIXTURES = (
    TESTS / "fixtures" / "render_export_ep0.json",
    TESTS / "fixtures" / "render_export_ep1.json",
    TESTS / "fixtures" / "render_export_ep2.json",
)

PHASE28_DOCS = (REPO_ROOT / "docs" / "episode_voice_plan.md",)

PHASE28_FILES = (*PHASE28_MODULES, *PHASE28_TEST_FILES, *PHASE28_FIXTURES, *PHASE28_DOCS)

ALLOWED_ENGINE_MODULES = frozenset(
    {
        "living_diorama.language_realization.realization_schema_v1",
        "living_diorama.language_realization.realization_spec",
        "living_diorama.narration.narration_schema_v1",
        "living_diorama.persistence.json_codec",
        "living_diorama.persistence.schema.state_hash",
        "living_diorama.persistence.schema.world_schema_v1",
        "living_diorama.presentation.presentation_cross_check",
        "living_diorama.presentation.presentation_schema_v1",
        "living_diorama.presentation.presentation_spec",
        "living_diorama.voice",
        "living_diorama.voice.voice_cross_check",
        "living_diorama.voice.voice_planner",
        "living_diorama.voice.voice_schema_v1",
        "living_diorama.voice.voice_spec",
    }
)
"""Exactly the engine modules Phase 28 may import.

The realization plan's own contract (for its structure, never its
``realized_text``), the narration mode/ID vocabulary Phase 27 itself already
imports from ``living_diorama.narration.narration_schema_v1``, the
presentation plan's own contract and the one reused Phase 27
source-verification gate (which itself reruns Phase 25's and Phase 26's), and
the shared codec and validators -- and deliberately no
``living_diorama.story``, no ``living_diorama.render``, no
``living_diorama.render_execution``, no ``living_diorama.memory``, and no
``living_diorama.narration_delivery`` beyond what the reused gate itself
needs transitively (this layer never imports it directly): this layer never
proves a story beat, an export event, a delivery slot or a shot true of
itself, it only supplies the five verification-only documents, opaque, to
the one locked gate that already owns that proof.
"""

FORBIDDEN_ENGINE_ROOTS = frozenset(
    {
        "living_diorama.engine",
        "living_diorama.entities",
        "living_diorama.events",
        "living_diorama.memory",
        "living_diorama.narration_delivery",
        "living_diorama.render",
        "living_diorama.render_execution",
        "living_diorama.simulation",
        "living_diorama.story",
        "living_diorama.systems",
    }
)
"""Engine subpackages Phase 28 must never import.

``render_execution`` matters most: Phase 23's frames and manifest belong to
the layers that join presentation to executed pixels, and a voice plan that
could see them would stop surviving the re-render of an unchanged episode.
``story`` and ``render`` matter almost as much: this layer supplies both,
transitively, to the reused Phase 27 gate as opaque arguments, and must never
import either package to inspect them a second time. ``narration_delivery``
is banned outright -- unlike Phase 27, this layer never even needs the
delivery plan's own helper functions; it passes the document through to the
reused gate untouched.
"""

FORBIDDEN_SYNTHESIS_ROOTS = frozenset({"kokoro", "misaki", "torch", "numpy", "scipy"})
"""No voice-engine dependency may ever be imported by the canonical package.

Phase 28 plans a synthesis request; it never issues one. A later Voice
Execution phase alone may import a synthesis engine.
"""

NETWORK_MODULES = frozenset(
    {"anthropic", "http", "httpx", "openai", "requests", "socket", "ssl", "urllib", "urllib3"}
)

NONDETERMINISM_MODULES = frozenset(
    {"datetime", "locale", "os", "platform", "random", "secrets", "time", "uuid"}
)

FORBIDDEN_IDENTIFIERS = re.compile(
    r"(?i).*("
    # captions and subtitles are a sibling layer's vocabulary
    r"caption|subtitle|\bsrt\b|\bvtt\b|webvtt|cue_?list"
    # produced audio bytes, waveform storage, PCM/container encoding and
    # mixing are all a later, measured execution phase's vocabulary --
    # Phase 28 plans a request and a budget, it never touches a sample of
    # actual sound
    r"|\bwav\b|\bflac\b|\bpcm\b|waveform|mixdown|\bmix\b|\bgain\b|normalize"
    r"|\btrim\b|\bvad\b|\bcodec\b|\bcontainer\b|bitrate|thumbnail"
    r"|audio_filename|soundtrack|\bmusic\b|\baudio\b"
    # assembly, encoding, packaging, publishing stay further downstream
    r"|ffmpeg|mux|encode_video|render_video|transcode|\bencode\b|\bassembly\b"
    r"|publish|package_episode|edit_list|crossfade|dissolve|\bmp4\b"
    # a runtime model is the whole point of the boundary
    r"|\bllm\b|\bgpt\b|\bprompt\b|embedding|completion|inference|generate_text|rephrase"
    # measured/fit vocabulary belongs to Phase 29 alone -- this is the exact
    # closure of the V1 provenance blocker: there is no field for a forged
    # measurement to act on, because no module may even define its name
    r"|measured|\bfits\b|fit_status|refuse_status|audio_manifest"
    # re-direction of Phase 22's decisions, or Phase 23's execution
    r"|choose_camera|select_camera|reframe|dolly|pan_speed|orbit|camera_path"
    r"|camera_anim|shot_rank|re_?rank|emphasis_weight|render_frame|frame_image"
    r"|render_manifest|render_plan"
    # non-sample, non-frame time vocabulary this layer must never own
    r"|speaking_rate|\bwpm\b|words_per|chars_per|syllable|\bpace\b|\btempo\b|cadence"
    r"|timecode|timestamp|millisecond|\bms\b|\bseconds?\b|elapsed"
    ").*"
)
"""Vocabulary belonging to other layers, banned from Phase 28 definitions.

Deliberately does **not** ban ``voice``, ``sample``, ``samples``,
``sample_rate``, ``engine``, ``speed``, ``channel`` or ``seed``: this layer
*is* the voice layer, and those are its own reviewed vocabulary, restated
from ``voice_spec`` rather than invented. ``capacity`` and ``frame`` are
likewise this layer's own arithmetic, never banned. What stays banned is
audio *execution* vocabulary (bytes, files, containers, mixing), every
downstream layer's vocabulary, a runtime model, and -- new to this phase --
the measured/fit vocabulary that made the deleted V1 measurement record
possible to forge.
"""

FUTURE_LAYER_NAMES = (
    "caption",
    "subtitle",
    "srt",
    "vtt",
    "wav",
    "flac",
    "pcm",
    "waveform",
    "mixdown",
    "mix",
    "gain",
    "trim",
    "vad",
    "codec",
    "container",
    "bitrate",
    "thumbnail",
    "audio",
    "music",
    "ffmpeg",
    "encode",
    "assembly",
    "publish",
    "package_episode",
    "edit_list",
    "llm",
    "prompt",
    "embedding",
    "inference",
    "rephrase",
    "render_manifest",
    "render_plan",
    "measured",
    "fits",
    "fit_status",
    "audio_manifest",
    "speaking_rate",
    "wpm",
    "syllable",
    "timecode",
    "timestamp",
    "seconds",
    "elapsed",
)

PHASE28_NAMES = (
    "voice_unit_id",
    "unit_id",
    "realization_id",
    "window_id",
    "realization_plan_sha256",
    "realization_schema_version",
    "presentation_plan_sha256",
    "presentation_schema_version",
    "capacity_samples",
    "capacity_samples_total",
    "voice_units_total",
    "voice_units",
    "samples_per_presentation_frame",
    "capacity_samples_for_window",
    "sample_rate_hz",
    "speed_percent",
    "lang_code",
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
    "channels",
    "seed",
    "fps",
    "window_frames",
    "text_source",
    "presentation_start_frame",
    "presentation_end_frame",
)
"""This phase's own vocabulary, and the neighbours' fields it legitimately
restates or joins against, which the guard must tolerate."""

WRITE_MARKERS = ("write_text(", "write_bytes(", "open(", ".mkdir(", "shutil.")

PROSE_BRANCH_MARKERS = (".startswith(", ".split(", ".lower()", ".strip()", "in text")

WHOLESALE_COPY_MARKERS = (
    "**unit",
    "**record",
    "**realization",
    "**presentation",
    "**window",
    ".items()",
    ".values()",
)

READ_BANNED_KEYS = ("realized_text", "source_event_payload", "summary", "text")
"""Keys no Phase 28 module may read, by subscript, ``.get`` or ``.pop``.

``text`` is the narration plan's sentence, ``realized_text`` is the
realization plan's, ``summary`` is the memory fact's, and
``source_event_payload`` is the event internals no downstream contract
proves. Voice binds identity and position only -- ``unit_id``,
``realization_id`` and ``window_id`` -- never a byte of wording. Whole
-document canonical serialization of the offered realization plan (to bind
``realization_plan_sha256``) is explicitly **not** a hit here: it is a
key-blind transform over the entire document's bytes, never a subscript,
``.get`` or ``.pop`` of any one field inside it.
"""


def parse(path: Path) -> ast.Module:
    """Parse one source file."""
    return ast.parse(path.read_text(encoding="utf-8"))


def imported_modules(tree: ast.Module) -> set[str]:
    """Return every module name a source file imports."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def defined_names(tree: ast.Module) -> set[str]:
    """Return every name a module defines, plus identifier-shaped constants."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                for argument in [
                    *node.args.args,
                    *node.args.posonlyargs,
                    *node.args.kwonlyargs,
                ]:
                    names.add(argument.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.isidentifier():
                names.add(node.value)
    return names


def forbidden_hit(name: str) -> bool:
    r"""Return whether one defined name reaches another layer's vocabulary."""
    if FORBIDDEN_IDENTIFIERS.fullmatch(name):
        return True
    return any(FORBIDDEN_IDENTIFIERS.fullmatch(segment) for segment in name.split("_"))


def key_reads(tree: ast.Module, key: str) -> list[str]:
    """Return every place a module reads one key of anything."""
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            index = node.slice
            if isinstance(index, ast.Constant) and index.value == key:
                hits.append(f"subscript at line {node.lineno}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("get", "pop", "__getitem__") and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and first.value == key:
                    hits.append(f".{node.func.attr} at line {node.lineno}")
    return hits


def _code_lines(path: Path) -> list[str]:
    """Return the file's source lines with docstrings and comments removed."""
    tree = parse(path)
    source = path.read_text(encoding="utf-8")
    doc_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                doc_lines.update(range(body[0].lineno, body[0].end_lineno + 1))
    lines = []
    for number, line in enumerate(source.splitlines(), start=1):
        if number in doc_lines:
            continue
        lines.append(line.split("#", 1)[0])
    return lines


# ---- the file list


def test_every_guarded_file_exists() -> None:
    """Every guarded file exists."""
    for path in PHASE28_FILES:
        assert path.is_file(), path


def test_the_guard_covers_every_module_in_the_package() -> None:
    """The guard covers every module in the package."""
    on_disk = set(PACKAGE.glob("*.py"))
    assert on_disk == set(PURE_MODULES)


def test_the_guard_covers_every_test_in_this_suite() -> None:
    """The guard covers every test in this suite."""
    on_disk = set(TESTS.glob("*.py"))
    assert on_disk == set(PHASE28_TEST_FILES)


def test_the_guard_covers_every_fixture_this_phase_ships() -> None:
    """The guard covers every fixture this phase ships."""
    on_disk = set((TESTS / "fixtures").glob("*.json"))
    assert on_disk == set(PHASE28_FIXTURES)


def test_the_fixtures_are_byte_identical_to_the_presentation_suite() -> None:
    """The fixtures are byte identical to the presentation suite."""
    for path in PHASE28_FIXTURES:
        original = REPO_ROOT / "tests" / "presentation" / "fixtures" / path.name
        assert path.read_bytes() == original.read_bytes(), path.name


def test_the_file_count_is_exact() -> None:
    """The file count is exact."""
    assert len(PHASE28_FILES) == 19


def test_the_suite_is_a_real_package() -> None:
    """The suite is a real package."""
    assert (TESTS / "__init__.py").is_file()


def test_no_test_module_imports_tests_absolutely() -> None:
    """Shared helpers come from the package-relative conftest only.

    An absolute ``tests.voice`` import resolves only under
    ``python -m pytest`` and fails under the bare ``pytest`` console script
    CI invokes -- exactly the defect this guard exists to catch, with zero
    exceptions.
    """
    for path in PHASE28_TEST_FILES:
        if path.suffix != ".py":
            continue
        for name in imported_modules(parse(path)):
            assert not name.startswith("tests"), f"{path.name} imports {name}"


# ---- import reach


def test_no_phase28_module_reaches_outside_its_allowed_engine_modules() -> None:
    """No phase28 module reaches outside its allowed engine modules."""
    for path in PHASE28_MODULES:
        for name in imported_modules(parse(path)):
            if name.startswith("living_diorama"):
                assert name in ALLOWED_ENGINE_MODULES, f"{path.name} imports {name}"


def test_no_phase28_module_imports_a_forbidden_engine_root() -> None:
    """No phase28 module imports a forbidden engine root."""
    for path in PHASE28_MODULES:
        for name in imported_modules(parse(path)):
            for root in FORBIDDEN_ENGINE_ROOTS:
                assert not name.startswith(root), f"{path.name} imports {name}"


def test_phase28_never_imports_story_or_render() -> None:
    """The five verification-only documents travel through as opaque arguments."""
    for path in PHASE28_MODULES:
        for name in imported_modules(parse(path)):
            assert not name.startswith("living_diorama.story"), path.name
            assert not name.startswith("living_diorama.render"), path.name


def test_phase28_never_imports_render_execution() -> None:
    """Phase 23's frames and manifest belong to a downstream assembly layer."""
    for path in PHASE28_MODULES:
        for name in imported_modules(parse(path)):
            assert not name.startswith("living_diorama.render_execution"), path.name


def test_phase28_never_imports_narration_delivery_directly() -> None:
    """The delivery plan travels through, opaque, to the reused Phase 27 gate."""
    for path in PHASE28_MODULES:
        for name in imported_modules(parse(path)):
            assert not name.startswith("living_diorama.narration_delivery"), path.name


def test_no_phase28_module_imports_a_synthesis_engine() -> None:
    """No canonical Phase 28 module imports Kokoro, misaki, torch or numpy."""
    for path in PHASE28_MODULES:
        for name in imported_modules(parse(path)):
            assert name.split(".", 1)[0] not in FORBIDDEN_SYNTHESIS_ROOTS, (
                f"{path.name} imports {name}"
            )


def test_no_phase28_module_reaches_the_network() -> None:
    """No phase28 module reaches the network."""
    for path in PHASE28_MODULES:
        for name in imported_modules(parse(path)):
            assert name.split(".", 1)[0] not in NETWORK_MODULES, f"{path.name} imports {name}"


def test_no_phase28_module_imports_a_source_of_nondeterminism() -> None:
    """No phase28 module imports a source of nondeterminism."""
    for path in PHASE28_MODULES:
        for name in imported_modules(parse(path)):
            assert name.split(".", 1)[0] not in NONDETERMINISM_MODULES, (
                f"{path.name} imports {name}"
            )


def test_no_phase28_module_imports_blender() -> None:
    """No phase28 module imports blender."""
    for path in PHASE28_MODULES:
        for name in imported_modules(parse(path)):
            assert name.split(".", 1)[0] not in {"bpy", "mathutils"}, path.name


def test_no_module_imports_relatively() -> None:
    """No module imports relatively."""
    for path in PHASE28_MODULES:
        for node in ast.walk(parse(path)):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"{path.name} imports relatively"


# ---- writing


def test_no_pure_module_touches_the_filesystem() -> None:
    """No pure module touches the filesystem."""
    for path in PURE_MODULES:
        for line in _code_lines(path):
            for marker in WRITE_MARKERS:
                assert marker not in line, f"{path.name}: {line.strip()}"


def test_the_cli_is_the_only_module_importing_pathlib() -> None:
    """The cli is the only module importing pathlib."""
    for path in PURE_MODULES:
        assert "pathlib" not in imported_modules(parse(path)), path.name


# ---- the one locked upstream gate is actually reused


def test_the_locked_upstream_gate_is_imported() -> None:
    """The cross-check reuses, never reimplements, the Phase 27 proof."""
    tree = parse(PACKAGE / "voice_cross_check.py")
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_names.update(alias.name for alias in node.names)
    assert "validate_episode_presentation_plan_against_sources" in imported_names


def test_the_cross_check_calls_the_gate() -> None:
    """A guard against silently importing the gate and never calling it."""
    source = (PACKAGE / "voice_cross_check.py").read_text(encoding="utf-8")
    assert "validate_episode_presentation_plan_against_sources(" in source


def test_no_phase28_module_reimplements_the_reused_gate(tmp_path: Path) -> None:
    """The reused gate name is reserved for the import, never a local def."""
    for path in PHASE28_MODULES:
        tree = parse(path)
        defined_functions = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        }
        assert "validate_episode_presentation_plan_against_sources" not in defined_functions


# ---- no measured field exists anywhere -- the closure of the V1 blocker


def test_no_module_defines_a_measured_or_fit_field() -> None:
    """The structural closure of the V1 provenance blocker.

    No module may define ``measured_samples``, ``measured_speech_samples``,
    ``fit_status``, or any name the vocabulary guard classifies as
    measured/fit vocabulary. There is therefore no field anywhere a forged
    measurement could act on.
    """
    for path in PHASE28_MODULES:
        for name in defined_names(parse(path)):
            assert "measured" not in name.lower(), f"{path.name} defines {name}"
            assert "fit_status" not in name.lower(), f"{path.name} defines {name}"


# ---- vocabulary


def test_no_phase28_module_defines_another_layers_vocabulary() -> None:
    """No phase28 module defines another layers vocabulary."""
    for path in PHASE28_MODULES:
        for name in defined_names(parse(path)):
            assert not forbidden_hit(name), f"{path.name} defines {name}"


@pytest.mark.parametrize("name", FUTURE_LAYER_NAMES)
def test_every_future_layer_name_fires(name: str) -> None:
    """Every future layer name fires."""
    assert forbidden_hit(name)
    assert forbidden_hit(f"{name}_track")
    assert forbidden_hit(f"build_{name}")


@pytest.mark.parametrize("name", PHASE28_NAMES)
def test_no_phase28_name_false_positives(name: str) -> None:
    """No phase28 name false positives."""
    assert not forbidden_hit(name)


def test_the_vocabulary_guard_ignores_prose_in_a_docstring() -> None:
    """The vocabulary guard ignores prose in a docstring."""
    module = ast.parse(
        '"""This layer never speaks audio, a caption, or produces a waveform."""\n'
        "def speak_unit(unit_id: str) -> str:\n"
        '    """It never publishes a subtitle, mixes a track, or measures fit."""\n'
        "    return unit_id\n"
    )
    for name in defined_names(module):
        assert not forbidden_hit(name)


def test_the_vocabulary_guard_catches_an_offender(tmp_path: Path) -> None:
    """The vocabulary guard catches an offender."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "def build_audio_manifest(measured_samples: int) -> None:\n    return None\n",
        encoding="utf-8",
    )
    hits = {name for name in defined_names(parse(offender)) if forbidden_hit(name)}
    assert hits


def test_the_import_guard_catches_an_offender(tmp_path: Path) -> None:
    """The import guard catches an offender."""
    offender = tmp_path / "offender.py"
    offender.write_text("from living_diorama.story import story_facts\n", encoding="utf-8")
    names = imported_modules(parse(offender))
    assert any(name.startswith(root) for name in names for root in FORBIDDEN_ENGINE_ROOTS)


def test_the_allow_list_guard_catches_an_offender(tmp_path: Path) -> None:
    """A real engine module off the allow-list, under no forbidden root."""
    offender = tmp_path / "offender.py"
    offender.write_text("import living_diorama.cinematic.shot_planner\n", encoding="utf-8")
    engine = [
        name for name in imported_modules(parse(offender)) if name.startswith("living_diorama")
    ]
    assert engine
    assert any(name not in ALLOWED_ENGINE_MODULES for name in engine)
    assert not any(name.startswith(root) for name in engine for root in FORBIDDEN_ENGINE_ROOTS)


def test_the_render_execution_guard_catches_an_offender(tmp_path: Path) -> None:
    """The render execution guard catches an offender."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "from living_diorama.render_execution import render_manifest\n", encoding="utf-8"
    )
    names = imported_modules(parse(offender))
    assert any(name.startswith("living_diorama.render_execution") for name in names)


def test_the_narration_delivery_guard_catches_an_offender(tmp_path: Path) -> None:
    """The narration delivery guard catches an offender."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "from living_diorama.narration_delivery import delivery_spec\n", encoding="utf-8"
    )
    names = imported_modules(parse(offender))
    assert any(name.startswith("living_diorama.narration_delivery") for name in names)


def test_the_synthesis_guard_catches_an_offender(tmp_path: Path) -> None:
    """The synthesis guard catches an offender."""
    offender = tmp_path / "offender.py"
    offender.write_text("import kokoro\nimport torch\n", encoding="utf-8")
    names = imported_modules(parse(offender))
    assert any(name.split(".", 1)[0] in FORBIDDEN_SYNTHESIS_ROOTS for name in names)


def test_the_network_guard_catches_an_offender(tmp_path: Path) -> None:
    """The network guard catches an offender."""
    offender = tmp_path / "offender.py"
    offender.write_text("import requests\n", encoding="utf-8")
    names = imported_modules(parse(offender))
    assert any(name.split(".", 1)[0] in NETWORK_MODULES for name in names)


def test_the_nondeterminism_guard_catches_an_offender(tmp_path: Path) -> None:
    """The nondeterminism guard catches an offender."""
    offender = tmp_path / "offender.py"
    offender.write_text("import random\nimport time\n", encoding="utf-8")
    names = imported_modules(parse(offender))
    assert any(name.split(".", 1)[0] in NONDETERMINISM_MODULES for name in names)


def test_the_write_guard_catches_an_offender(tmp_path: Path) -> None:
    """The write guard catches an offender."""
    offender = tmp_path / "offender.py"
    offender.write_text("def leak(path):\n    path.write_text('x')\n", encoding="utf-8")
    hits = [line for line in _code_lines(offender) for marker in WRITE_MARKERS if marker in line]
    assert hits


def test_the_key_read_guard_catches_every_shape(tmp_path: Path) -> None:
    """The key read guard catches every shape."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "def leak(unit, realization, fact, event):\n"
        "    return (\n"
        '        unit["text"],\n'
        '        realization.get("realized_text"),\n'
        '        fact.get("summary"),\n'
        '        event.pop("source_event_payload"),\n'
        "    )\n",
        encoding="utf-8",
    )
    tree = parse(offender)
    for key in READ_BANNED_KEYS:
        assert key_reads(tree, key), key


def test_reading_unit_id_never_trips_the_text_ban(tmp_path: Path) -> None:
    """``unit_id`` is a distinct, legitimate structured field.

    ``key_reads(tree, "text")`` matches the exact string ``"text"`` only, so a
    module reading ``unit["unit_id"]`` must never be caught by the ban on
    ``"text"`` -- the two are different keys, not a prefix relationship.
    """
    offender = tmp_path / "innocent.py"
    offender.write_text('def identify(unit):\n    return unit["unit_id"]\n', encoding="utf-8")
    tree = parse(offender)
    assert key_reads(tree, "text") == []
    assert key_reads(tree, "unit_id") == ["subscript at line 2"]


def test_no_module_reads_an_upstream_prose_or_payload_key() -> None:
    """The empty allow-list is the point: voice never opens a prose field."""
    for path in PHASE28_MODULES:
        tree = parse(path)
        for key in READ_BANNED_KEYS:
            assert key_reads(tree, key) == [], f"{path.name} reads {key!r}"


def test_whole_document_canonical_serialization_is_present_and_is_not_a_key_read() -> None:
    """Opaque whole-document hashing is required, and is never mistaken for prose access.

    The planner and the cross-check must both call the shared canonical
    serialization helper over the entire offered realization document, to
    bind ``realization_plan_sha256``. That call is not a subscript, ``.get``
    or ``.pop`` of any one field -- ``key_reads`` proves it is never counted
    as one, which is the whole point of the distinction between opaque
    whole-document binding (required) and keyed semantic access (banned).
    """
    for name in ("voice_planner.py", "voice_cross_check.py"):
        source = (PACKAGE / name).read_text(encoding="utf-8")
        assert "dumps_canonical(realization" in source
        tree = parse(PACKAGE / name)
        for key in READ_BANNED_KEYS:
            assert key_reads(tree, key) == [], f"{name} reads {key!r}"


def test_no_module_branches_on_wording_shape() -> None:
    """No module branches on wording shape."""
    for path in PHASE28_MODULES:
        for line in _code_lines(path):
            for marker in PROSE_BRANCH_MARKERS:
                assert marker not in line, f"{path.name}: {line.strip()}"


def test_the_prose_branch_guard_catches_an_offender(tmp_path: Path) -> None:
    """The prose branch guard catches an offender."""
    offender = tmp_path / "offender.py"
    offender.write_text("def leak(sentence):\n    return sentence.split()[0]\n", encoding="utf-8")
    hits = [
        line for line in _code_lines(offender) for marker in PROSE_BRANCH_MARKERS if marker in line
    ]
    assert hits


def test_no_module_copies_a_record_wholesale() -> None:
    """No module copies a record wholesale."""
    for path in PURE_MODULES:
        for line in _code_lines(path):
            for marker in WHOLESALE_COPY_MARKERS:
                assert marker not in line, f"{path.name}: {line.strip()}"


def test_the_wholesale_copy_guard_catches_an_offender(tmp_path: Path) -> None:
    """The wholesale copy guard catches an offender."""
    offender = tmp_path / "offender.py"
    offender.write_text("def leak(unit):\n    return dict(**unit)\n", encoding="utf-8")
    hits = [
        line
        for line in _code_lines(offender)
        for marker in WHOLESALE_COPY_MARKERS
        if marker in line
    ]
    assert hits


# ---- this phase changes nothing upstream


def test_phase28_adds_no_blender_file() -> None:
    """Phase28 adds no blender file."""
    for path in PHASE28_FILES:
        assert "visual" not in path.parts, path


def test_phase28_touches_no_render_execution_module() -> None:
    """Phase28 touches no render execution module."""
    for path in PHASE28_FILES:
        assert "render_execution" not in path.parts, path


def test_phase28_touches_no_upstream_module() -> None:
    """Every file this phase ships lives in its own homes."""
    for path in PHASE28_MODULES:
        assert "voice" in path.parts or path in CLI_MODULES, path
    for path in PHASE28_TEST_FILES:
        assert "voice" in path.parts, path
