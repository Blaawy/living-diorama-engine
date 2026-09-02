"""Phase 30 stays inside its boundary, proven by parsing the sources.

Phase 30 owns one responsibility -- deriving where each unit's already
measured speech begins on the episode's single audio-sample clock, from an
audited Phase 29 execution and the Phase 27 presentation plan its windows
come from. It never synthesizes, never opens an audio file, never measures
a sample, and never reads a narration unit's ``text``, a realization's
``realized_text``, or a memory fact's ``summary`` -- zero carve-outs,
stricter than Phase 29's own single exemption, because Phase 30 has no
structural reason to touch prose or audio bytes at all.
"""

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "src" / "living_diorama" / "audio_track"
CLI = REPO_ROOT / "src" / "living_diorama" / "cli"
TESTS = Path(__file__).parent

PURE_MODULES = (
    PACKAGE / "__init__.py",
    PACKAGE / "audio_track_cross_check.py",
    PACKAGE / "audio_track_planner.py",
    PACKAGE / "audio_track_schema_v1.py",
    PACKAGE / "audio_track_spec.py",
)

CLI_MODULES = (CLI / "build_audio_track_plan.py",)
PHASE30_MODULES = (*PURE_MODULES, *CLI_MODULES)

PHASE30_TEST_FILES = (
    TESTS / "__init__.py",
    TESTS / "conftest.py",
    TESTS / "test_phase30_boundary.py",
    TESTS / "test_audio_track_spec.py",
    TESTS / "test_audio_track_schema.py",
    TESTS / "test_audio_track_planner.py",
    TESTS / "test_audio_track_cross_check.py",
    TESTS / "test_audio_track_cli.py",
    TESTS / "test_audio_track_determinism.py",
)

PHASE30_FIXTURES = (
    TESTS / "fixtures" / "render_export_ep0.json",
    TESTS / "fixtures" / "render_export_ep1.json",
    TESTS / "fixtures" / "render_export_ep2.json",
)

PHASE30_DOCS = (REPO_ROOT / "docs" / "episode_audio_track_plan.md",)

PHASE30_FILES = (*PHASE30_MODULES, *PHASE30_TEST_FILES, *PHASE30_FIXTURES, *PHASE30_DOCS)

ALLOWED_ENGINE_MODULES = frozenset(
    {
        "living_diorama.audio_track",
        "living_diorama.audio_track.audio_track_cross_check",
        "living_diorama.audio_track.audio_track_planner",
        "living_diorama.audio_track.audio_track_schema_v1",
        "living_diorama.audio_track.audio_track_spec",
        "living_diorama.language_realization.realization_spec",
        "living_diorama.narration.narration_schema_v1",
        "living_diorama.persistence.json_codec",
        "living_diorama.persistence.schema.state_hash",
        "living_diorama.persistence.schema.world_schema_v1",
        "living_diorama.presentation.presentation_schema_v1",
        "living_diorama.presentation.presentation_schema_v2",
        "living_diorama.presentation.presentation_spec",
        "living_diorama.voice.voice_cross_check",
        "living_diorama.voice.voice_spec",
        "living_diorama.voice_execution",
        "living_diorama.voice_execution.voice_execution_binding",
        "living_diorama.voice_execution.voice_execution_schema_v1",
        "living_diorama.voice_execution.voice_execution_spec",
    }
)
"""Exactly the engine modules Phase 30 may import.

``living_diorama.voice_execution`` for the reused Phase 29 audit and
relationship gate, ``living_diorama.voice`` for the reused Phase 28 gate and
its crossing law, the presentation and realization contracts, the shared
codec and validators, and this package's own modules -- deliberately no
``living_diorama.story``, ``render``, ``render_execution``, ``memory``,
``narration_delivery``, and no ``living_diorama.voice_execution.speech_audio``
(Phase 30 never opens an audio file itself).
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

FORBIDDEN_SYNTHESIS_ROOTS = frozenset(
    {"kokoro", "misaki", "torch", "numpy", "scipy", "spacy", "num2words", "soundfile", "wave"}
)

FORBIDDEN_IDENTIFIERS = re.compile(
    r"(?i).*("
    r"\bwav\b|\bpcm\b|waveform|synthesize|synthesis|kokoro|misaki"
    r"|caption|subtitle|\bsrt\b|\bvtt\b|webvtt"
    r"|\bmix\b|\bgain\b|normalize|\btrim\b|\bvad\b|\bcodec\b|bitrate"
    r"|ffmpeg|\bmux\b|\bencode\b|\bassembly\b|\bpublish\b|thumbnail|\bmp4\b"
    r"|\bllm\b|\bgpt\b|\bprompt\b|inference|rephrase"
    r"|\bwpm\b|\bsyllable\b|speaking_rate|\btimecode\b|\btimestamp\b|\bseconds?\b|\belapsed\b"
    r").*"
)
"""Vocabulary belonging to other layers, banned from Phase 30 definitions.

Deliberately does **not** ban this layer's own reviewed vocabulary:
``start_sample``, ``speech_samples``, ``silence_samples_total``,
``audio_samples_total``, ``samples_per_presentation_frame``, ``speech_id``,
``clock``.
"""

READ_BANNED_KEYS = ("realized_text", "source_event_payload", "summary", "text")
"""Phase 30 reads no prose at all, with an empty allow-list -- unlike Phase
29 it has no exempt module or function."""

WRITE_MARKERS = ("write_text(", "write_bytes(", "open(", ".mkdir(")


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
                for argument in [*node.args.args, *node.args.posonlyargs, *node.args.kwonlyargs]:
                    names.add(argument.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.isidentifier():
                names.add(node.value)
    return names


def forbidden_hit(name: str) -> bool:
    """Return whether one defined name reaches another layer's vocabulary."""
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
    for path in PHASE30_FILES:
        assert path.is_file(), path


def test_the_file_count_is_exact() -> None:
    """The file count is exact: nineteen."""
    assert len(PHASE30_FILES) == 19


def test_the_suite_is_a_real_package() -> None:
    """The suite is a real package."""
    assert (TESTS / "__init__.py").is_file()


def test_no_test_module_imports_tests_absolutely() -> None:
    """Shared helpers come from the package-relative conftest only."""
    for path in PHASE30_TEST_FILES:
        if path.suffix != ".py":
            continue
        tree = parse(path)
        for module_name in imported_modules(tree):
            assert not module_name.startswith("tests."), (path, module_name)


def test_the_fixtures_are_byte_identical_to_the_phase28_suite() -> None:
    """The three fixtures are byte-identical to the Phase 28 voice suite's own copies."""
    phase28_fixtures = REPO_ROOT / "tests" / "voice" / "fixtures"
    for path in PHASE30_FIXTURES:
        counterpart = phase28_fixtures / path.name
        assert counterpart.is_file()
        assert path.read_bytes() == counterpart.read_bytes()


# ---- import boundary


@pytest.mark.parametrize("path", PHASE30_MODULES)
def test_no_module_reaches_outside_its_allowed_engine_modules(path: Path) -> None:
    """No Phase 30 module reaches outside its allowed engine modules."""
    tree = parse(path)
    for module_name in imported_modules(tree):
        if not module_name.startswith("living_diorama"):
            continue
        assert module_name in ALLOWED_ENGINE_MODULES, (path, module_name)


@pytest.mark.parametrize("path", PHASE30_MODULES)
def test_no_phase30_module_imports_a_forbidden_engine_root(path: Path) -> None:
    """No Phase 30 module imports a forbidden engine root."""
    tree = parse(path)
    for module_name in imported_modules(tree):
        for forbidden in FORBIDDEN_ENGINE_ROOTS:
            assert not (module_name == forbidden or module_name.startswith(forbidden + ".")), (
                path,
                module_name,
            )


@pytest.mark.parametrize("path", PHASE30_MODULES)
def test_no_synthesis_dependency_anywhere_in_phase30(path: Path) -> None:
    """No synthesis, G2P, tensor or permissive-audio dependency anywhere in Phase 30."""
    tree = parse(path)
    for module_name in imported_modules(tree):
        root = module_name.split(".")[0]
        assert root not in FORBIDDEN_SYNTHESIS_ROOTS, (path, module_name)


def test_no_module_opens_a_wav_file() -> None:
    """No Phase 30 module ever imports speech_audio -- it never opens a WAV file."""
    for path in PHASE30_MODULES:
        tree = parse(path)
        assert "living_diorama.voice_execution.speech_audio" not in imported_modules(tree), path


@pytest.mark.parametrize("path", PHASE30_MODULES)
def test_no_module_imports_relatively(path: Path) -> None:
    """No module imports relatively."""
    tree = parse(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert (node.level or 0) == 0, path


@pytest.mark.parametrize("path", PURE_MODULES)
def test_the_planner_touches_no_filesystem(path: Path) -> None:
    """No pure package module writes to, or reads from, the filesystem.

    Unlike Phase 29, Phase 30 has no artifact-reading module at all -- every
    fact it needs is already inside the two documents it is handed.
    """
    lines = _code_lines(path)
    for number, line in enumerate(lines, start=1):
        for marker in WRITE_MARKERS:
            assert marker not in line, (path, number, line)


def test_only_the_cli_writes_a_file() -> None:
    """Only the CLI module writes a file, anywhere in Phase 30."""
    for path in PURE_MODULES:
        lines = _code_lines(path)
        for line in lines:
            assert "write_bytes(" not in line, path
    cli_lines = _code_lines(CLI / "build_audio_track_plan.py")
    assert any("write_bytes(" in line for line in cli_lines)


# ---- vocabulary and key-read guards


@pytest.mark.parametrize("path", PHASE30_MODULES)
def test_no_phase30_module_defines_another_layers_vocabulary(path: Path) -> None:
    """No Phase 30 module defines another layer's vocabulary."""
    tree = parse(path)
    for name in defined_names(tree):
        assert not forbidden_hit(name), (path, name)


def test_the_vocabulary_guard_catches_an_offender() -> None:
    """The vocabulary guard catches a deliberately bad synthetic name."""
    assert forbidden_hit("caption_text")
    assert forbidden_hit("synthesize_unit")
    assert forbidden_hit("mux_streams")


def test_the_vocabulary_guard_permits_this_layers_own_names() -> None:
    """The vocabulary guard permits this layer's own reviewed vocabulary."""
    for name in (
        "start_sample",
        "speech_samples",
        "silence_samples_total",
        "audio_samples_total",
        "samples_per_presentation_frame",
        "speech_id",
        "clock",
    ):
        assert not forbidden_hit(name)


@pytest.mark.parametrize("path", PHASE30_MODULES)
def test_no_module_reads_a_banned_prose_or_payload_key(path: Path) -> None:
    """No Phase 30 module reads a banned prose or payload key -- zero exemptions."""
    tree = parse(path)
    for key in READ_BANNED_KEYS:
        assert key_reads(tree, key) == [], (path, key)


def test_the_key_read_guard_catches_every_shape(tmp_path: Path) -> None:
    """The key-read guard catches subscript, .get and .pop shapes."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "def f(d):\n"
        "    a = d['realized_text']\n"
        "    b = d.get('realized_text')\n"
        "    c = d.pop('realized_text')\n"
        "    return a, b, c\n",
        encoding="utf-8",
    )
    tree = parse(offender)
    assert len(key_reads(tree, "realized_text")) == 3


def test_zero_exemptions_unlike_phase29() -> None:
    """Phase 30's realized_text ban has zero exemptions, unlike Phase 29's one."""
    for path in PHASE30_MODULES:
        tree = parse(path)
        assert key_reads(tree, "realized_text") == [], path


# ---- gate reuse


def test_the_locked_phase28_gate_is_imported_and_called() -> None:
    """The locked Phase 28 gate is imported and actually called."""
    path = PACKAGE / "audio_track_cross_check.py"
    tree = parse(path)
    assert "living_diorama.voice.voice_cross_check" in imported_modules(tree)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "validate_episode_voice_plan_against_sources"
    ]
    assert len(calls) == 1


def test_the_phase29_relationship_gate_is_imported_and_called() -> None:
    """The reused Phase 29 relationship gate is imported and actually called."""
    path = PACKAGE / "audio_track_cross_check.py"
    tree = parse(path)
    assert "living_diorama.voice_execution.voice_execution_binding" in imported_modules(tree)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "require_manifest_matches_plan"
    ]
    assert len(calls) == 1


def test_the_audit_is_called_by_the_cli_before_the_document_gate() -> None:
    """The reused Phase 29 audit is called by the CLI, and precedes the document gate call."""
    path = CLI / "build_audio_track_plan.py"
    tree = parse(path)
    assert "living_diorama.voice_execution" in imported_modules(tree)
    watched_names = {"audit_voice_directory", "validate_episode_audio_track_plan_against_sources"}
    calls_in_order: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in watched_names
        ):
            calls_in_order.append((node.lineno, node.func.id))
    calls_in_order.sort()
    names = [name for _line, name in calls_in_order]
    assert names.index("audit_voice_directory") < names.index(
        "validate_episode_audio_track_plan_against_sources"
    )


def test_no_module_reimplements_a_reused_gate() -> None:
    """No Phase 30 module defines a second function claiming to be a reused gate."""
    banned_names = {
        "validate_episode_voice_plan_against_sources",
        "require_manifest_matches_plan",
        "audit_voice_directory",
    }
    for path in PHASE30_MODULES:
        tree = parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                assert node.name not in banned_names, path
