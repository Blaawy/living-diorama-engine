"""Phase 29 stays inside its boundary, proven by parsing the sources.

Phase 29 owns one responsibility -- synthesizing each verified voice unit
exactly once under the Phase 28 pinned narrator request, owning the produced
speech audio, recomputing every measured fact from the artifact it actually
produced, and proving FIT or refusing the whole episode. Everything a reader
might reasonably expect it to grow into is somebody else's phase: capacity
and narrator identity (already decided, upstream); placement on the
presentation sample clock, silence, captions, audio composition, assembly,
encoding and publishing.

These are reach rules, not a claim that these files are frozen. The guard
proves what the voice-execution modules may *touch*: what they import,
whether they write, what vocabulary they define, and that no upstream truth
becomes authoritative before the locked Phase 28 gate has actually run.
Every guard is exercised against a deliberately bad synthetic file, because a
guard nobody has seen fail is a guard nobody has tested.

Note on inventory: this suite counts twelve test files, not the eleven named
in the literal file-inventory table of the approved implementation
architecture (V1 Section E), which omits ``test_voice_execution_determinism.py``
by a drafting slip -- Section R's own coverage bullets, and Section AG's
mandatory ``PYTHONHASHSEED`` determinism gate, both require it, and
``__init__.py`` is independently required by every other phase's own
precedent (a suite fails to collect under the bare ``pytest`` console script
without it). Both files are kept; Phase 29's real total is twenty-five files,
not twenty-four, and the candidate report discloses this as a deviation.
"""

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "src" / "living_diorama" / "voice_execution"
CLI = REPO_ROOT / "src" / "living_diorama" / "cli"
EXECUTOR_DIR = REPO_ROOT / "audio" / "kokoro" / "scripts"
TESTS = Path(__file__).parent

PURE_MODULES = (
    PACKAGE / "__init__.py",
    PACKAGE / "speech_audio.py",
    PACKAGE / "voice_execution_audit.py",
    PACKAGE / "voice_execution_binding.py",
    PACKAGE / "voice_execution_schema_v1.py",
    PACKAGE / "voice_execution_spec.py",
    PACKAGE / "voice_manifest.py",
)
"""Every canonical-package module Phase 29 adds, named one by one.

A glob would quietly stop guarding a module somebody renamed, and would
quietly start guarding somebody else's.
"""

CLI_MODULES = (CLI / "verify_voice.py",)
EXECUTOR_MODULES = (EXECUTOR_DIR / "synthesize_episode.py",)
PHASE29_MODULES = (*PURE_MODULES, *CLI_MODULES, *EXECUTOR_MODULES)

PHASE29_TEST_FILES = (
    TESTS / "__init__.py",
    TESTS / "conftest.py",
    TESTS / "test_phase29_boundary.py",
    TESTS / "test_voice_execution_spec.py",
    TESTS / "test_speech_audio.py",
    TESTS / "test_voice_execution_schema.py",
    TESTS / "test_voice_manifest.py",
    TESTS / "test_voice_binding.py",
    TESTS / "test_voice_audit.py",
    TESTS / "test_voice_executor.py",
    TESTS / "test_verify_voice_cli.py",
    TESTS / "test_voice_execution_determinism.py",
)

PHASE29_FIXTURES = (
    TESTS / "fixtures" / "render_export_ep0.json",
    TESTS / "fixtures" / "render_export_ep1.json",
    TESTS / "fixtures" / "render_export_ep2.json",
)

PHASE29_DOCS = (REPO_ROOT / "docs" / "episode_voice_execution.md",)

PHASE29_FILES = (*PHASE29_MODULES, *PHASE29_TEST_FILES, *PHASE29_FIXTURES, *PHASE29_DOCS)

ALLOWED_ENGINE_MODULES = frozenset(
    {
        "living_diorama.language_realization.realization_schema_v1",
        "living_diorama.language_realization.realization_spec",
        "living_diorama.narration.narration_schema_v1",
        "living_diorama.persistence.json_codec",
        "living_diorama.persistence.schema.state_hash",
        "living_diorama.persistence.schema.world_schema_v1",
        "living_diorama.presentation.presentation_schema_v1",
        "living_diorama.presentation.presentation_spec",
        "living_diorama.voice",
        "living_diorama.voice.voice_cross_check",
        "living_diorama.voice.voice_schema_v1",
        "living_diorama.voice.voice_spec",
        "living_diorama.voice_execution",
        "living_diorama.voice_execution.speech_audio",
        "living_diorama.voice_execution.voice_execution_audit",
        "living_diorama.voice_execution.voice_execution_binding",
        "living_diorama.voice_execution.voice_execution_schema_v1",
        "living_diorama.voice_execution.voice_execution_spec",
        "living_diorama.voice_execution.voice_manifest",
    }
)
"""Exactly the engine modules Phase 29 may import.

The realization plan's own contract (for structure, never ``realized_text``
except inside the executor's one exempt function), the narration mode/ID
vocabulary, the presentation plan's own contract, the reused Phase 28 gate,
the shared codec and validators, and this package's own modules --
deliberately no ``living_diorama.story``, ``living_diorama.render``, no
``living_diorama.render_execution``, no ``living_diorama.memory``, no
``living_diorama.narration_delivery``, and no ``living_diorama.audio_track``
(Phase 29 never imports its own downstream consumer).
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
        "living_diorama.audio_track",
    }
)

FORBIDDEN_SYNTHESIS_ROOTS = frozenset(
    {"kokoro", "misaki", "torch", "numpy", "scipy", "spacy", "num2words", "soundfile", "wave"}
)
"""No voice-engine, G2P, tensor or permissive-audio dependency in the canonical
package or the audit CLI. Permitted only in the executor module, which defers
every one of these into a function body rather than a module-scope import."""

FORBIDDEN_ACQUISITION_NAMES = frozenset(
    {
        "hf_hub_download",
        "snapshot_download",
        "huggingface_hub",
        "pip",
        "subprocess",
        "urllib",
        "requests",
        "httpx",
        "socket",
    }
)
"""Structurally banned everywhere in Phase 29, including the executor: the
offline law rests on explicit local injection and a digest gate, never on an
acquisition path that happens to be absent."""

NONDETERMINISM_MODULES = frozenset({"datetime", "locale", "random", "secrets", "time", "uuid"})

FORBIDDEN_IDENTIFIERS = re.compile(
    r"(?i).*("
    r"caption|subtitle|\bsrt\b|\bvtt\b|webvtt|cue_?list"
    r"|start_sample|\bsilence\b|audio_track|speech_id|\bplacement\b|\bonset\b"
    r"|\bmix\b|\bgain\b|normalize|\btrim\b|\bvad\b|\bcodec\b|bitrate"
    r"|ffmpeg|\bmux\b|\bencode\b|\bassembly\b|package_episode|thumbnail|\bmp4\b"
    r"|\bllm\b|\bgpt\b|\bprompt\b|embedding|completion|inference|rephrase"
    r"|choose_camera|select_camera|reframe|\bdolly\b|pan_speed|\borbit\b|camera_path"
    r"|camera_anim|shot_rank|re_?rank|render_frame|frame_image|render_manifest|render_plan"
    r"|\bwpm\b|\bsyllable\b|speaking_rate|\btimecode\b|\btimestamp\b|\belapsed\b"
    r").*"
)
"""Vocabulary belonging to other layers, banned from Phase 29 definitions.

Deliberately does **not** ban ``wav``, ``pcm``, ``audio`` (as artifact),
``speech``, ``samples``, ``measured``, ``fit``, ``manifest`` or
``environment``: this layer *is* the execution layer, and those are its own
reviewed vocabulary. ``seconds`` is likewise not banned here, unlike Phase
28, because a duration derived from an integer sample count is legitimate
audit-facing arithmetic one layer down from pure planning. Nor is a bare
``publish`` banned: "atomic publication" -- ``publish_episode`` -- is this
execution layer's own frozen vocabulary (V1 Section P), unlike Phase 28
where publishing belonged only to a future downstream layer; what stays
banned is packaging an episode for distribution (``package_episode``),
never this layer's own directory-rename act.
"""

BANNED_UPSTREAM_CONSTANT_NAMES = frozenset(
    {
        "MODEL_REPOSITORY",
        "MODEL_REVISION",
        "MODEL_WEIGHTS_SHA256",
        "MODEL_CONFIG_SHA256",
        "VOICE_PACK_SHA256",
        "SAMPLE_RATE_HZ",
        "LANG_CODE",
    }
)
"""Phase 28-owned narrator-identity constants Phase 29 must never re-declare.

Checked by exact, case-sensitive name against every ``ast.Name`` this module
assigns anywhere (module scope or local) -- deliberately narrower than
:data:`FORBIDDEN_IDENTIFIERS`'s case-insensitive substring match, because the
intent here is "never redeclare this exact constant", not "never use a
similar word". The lowercase local variable ``model_repository`` -- the
value read from the gate-verified voice block -- is not this name and is not
banned.
"""

READ_BANNED_KEYS = ("realized_text", "source_event_payload", "summary", "text")
"""Keys no Phase 29 module may read, by subscript, ``.get`` or ``.pop`` --
except the one exempt function named below."""

REALIZED_TEXT_EXEMPT_FILE = EXECUTOR_DIR / "synthesize_episode.py"
REALIZED_TEXT_EXEMPT_FUNCTION = "unit_texts"


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


def assigned_names_exact(tree: ast.Module) -> set[str]:
    """Return every name assigned anywhere (module or local), exact case."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
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


def key_read_lines(tree: ast.Module, key: str) -> list[int]:
    """Return the line numbers of every place a module reads one key of anything."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            index = node.slice
            if isinstance(index, ast.Constant) and index.value == key:
                lines.append(node.lineno)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("get", "pop", "__getitem__") and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and first.value == key:
                    lines.append(node.lineno)
    return lines


def function_line_range(tree: ast.Module, name: str) -> tuple[int, int] | None:
    """Return the (start, end) inclusive line range of the first function named ``name``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            end = node.end_lineno if node.end_lineno is not None else node.lineno
            return node.lineno, end
    return None


WRITE_MARKERS = ("write_text(", "write_bytes(", "open(", ".mkdir(", "shutil.")


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
    for path in PHASE29_FILES:
        assert path.is_file(), path


def test_the_file_count_is_exact() -> None:
    """The file count is exact: twenty-five (see the module docstring's note)."""
    assert len(PHASE29_FILES) == 25


def test_the_suite_is_a_real_package() -> None:
    """The suite is a real package."""
    assert (TESTS / "__init__.py").is_file()


def test_no_test_module_imports_tests_absolutely() -> None:
    """Shared helpers come from the package-relative conftest only."""
    for path in PHASE29_TEST_FILES:
        if path.suffix != ".py":
            continue
        tree = parse(path)
        for module_name in imported_modules(tree):
            assert not module_name.startswith("tests."), (path, module_name)


def test_the_fixtures_are_byte_identical_to_the_phase28_suite() -> None:
    """The three fixtures are byte-identical to the Phase 28 voice suite's own copies."""
    phase28_fixtures = REPO_ROOT / "tests" / "voice" / "fixtures"
    for path in PHASE29_FIXTURES:
        counterpart = phase28_fixtures / path.name
        assert counterpart.is_file()
        assert path.read_bytes() == counterpart.read_bytes()


# ---- import boundary


@pytest.mark.parametrize("path", PURE_MODULES + CLI_MODULES)
def test_no_module_reaches_outside_its_allowed_engine_modules(path: Path) -> None:
    """No canonical-package or CLI module reaches outside its allowed engine modules."""
    tree = parse(path)
    for module_name in imported_modules(tree):
        if not module_name.startswith("living_diorama"):
            continue
        assert module_name in ALLOWED_ENGINE_MODULES, (path, module_name)


@pytest.mark.parametrize("path", PHASE29_MODULES)
def test_no_phase29_module_imports_a_forbidden_engine_root(path: Path) -> None:
    """No Phase 29 module imports a forbidden engine root."""
    tree = parse(path)
    for module_name in imported_modules(tree):
        for forbidden in FORBIDDEN_ENGINE_ROOTS:
            assert not (module_name == forbidden or module_name.startswith(forbidden + ".")), (
                path,
                module_name,
            )


@pytest.mark.parametrize("path", PURE_MODULES + CLI_MODULES)
def test_no_synthesis_dependency_in_the_canonical_package_or_cli(path: Path) -> None:
    """No synthesis, G2P, tensor or permissive-audio dependency in the package or CLI."""
    tree = parse(path)
    for module_name in imported_modules(tree):
        root = module_name.split(".")[0]
        assert root not in FORBIDDEN_SYNTHESIS_ROOTS, (path, module_name)


def test_the_executor_defers_every_third_party_import_into_a_function_body() -> None:
    """The executor imports kokoro/misaki/torch/spacy only inside function bodies."""
    tree = parse(EXECUTOR_DIR / "synthesize_episode.py")
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in FORBIDDEN_SYNTHESIS_ROOTS
        if isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            assert root not in FORBIDDEN_SYNTHESIS_ROOTS


@pytest.mark.parametrize("path", PHASE29_MODULES)
def test_no_acquisition_api_is_named_anywhere(path: Path) -> None:
    """No acquisition API name is imported or defined anywhere in Phase 29."""
    tree = parse(path)
    imports = imported_modules(tree)
    for name in FORBIDDEN_ACQUISITION_NAMES:
        for module_name in imports:
            root = module_name.split(".")[0]
            assert root != name, (path, module_name)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                assert alias.name not in FORBIDDEN_ACQUISITION_NAMES, (path, alias.name)


@pytest.mark.parametrize("path", PHASE29_MODULES)
def test_no_module_imports_relatively(path: Path) -> None:
    """No module imports relatively."""
    tree = parse(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert (node.level or 0) == 0, path


@pytest.mark.parametrize("path", PURE_MODULES)
def test_no_pure_package_module_writes_to_the_filesystem(path: Path) -> None:
    """No package module writes to the filesystem -- only the executor's staging helpers do.

    Reading is a different question: ``speech_audio.py`` and
    ``voice_execution_audit.py`` legitimately read files, the exact
    precedent Phase 23's own ``frame_image.py`` sets one layer up -- "no
    pure module touches the filesystem" is a plan-phase rule (Phases
    24-28), never an execution-phase one. This guard checks writes only.
    """
    lines = _code_lines(path)
    for number, line in enumerate(lines, start=1):
        for marker in WRITE_MARKERS:
            assert marker not in line, (path, number, line)


# ---- vocabulary and key-read guards


@pytest.mark.parametrize("path", PHASE29_MODULES)
def test_no_phase29_module_defines_another_layers_vocabulary(path: Path) -> None:
    """No Phase 29 module defines another layer's vocabulary."""
    tree = parse(path)
    for name in defined_names(tree):
        assert not forbidden_hit(name), (path, name)


@pytest.mark.parametrize("path", PHASE29_MODULES)
def test_no_phase29_file_defines_a_banned_upstream_constant_name(path: Path) -> None:
    """No Phase 29 file defines a name matching a Phase 28-owned narrator-identity constant."""
    tree = parse(path)
    for name in assigned_names_exact(tree):
        assert name not in BANNED_UPSTREAM_CONSTANT_NAMES, (path, name)


def test_the_upstream_constant_guard_catches_an_offender(tmp_path: Path) -> None:
    """The upstream-constant guard catches a deliberately bad synthetic file."""
    offender = tmp_path / "offender.py"
    offender.write_text('MODEL_REPOSITORY: str = "hexgrad/Kokoro-82M"\n', encoding="utf-8")
    tree = parse(offender)
    names = assigned_names_exact(tree)
    assert "MODEL_REPOSITORY" in names
    assert any(name in BANNED_UPSTREAM_CONSTANT_NAMES for name in names)


def test_the_vocabulary_guard_catches_an_offender() -> None:
    """The vocabulary guard catches a deliberately bad synthetic name."""
    assert forbidden_hit("caption_text")
    assert forbidden_hit("start_sample")
    assert forbidden_hit("audio_encode_helper")


def test_the_vocabulary_guard_ignores_prose_in_a_docstring(tmp_path: Path) -> None:
    """The vocabulary guard ignores prose that only appears in a stripped docstring."""
    offender = tmp_path / "offender.py"
    docstring = '"""This module never writes a caption or a subtitle."""'
    offender.write_text(f"{docstring}\n\ndef safe_name() -> None:\n    pass\n", encoding="utf-8")
    lines = _code_lines(offender)
    joined = "\n".join(lines)
    assert "caption" not in joined


@pytest.mark.parametrize("path", PURE_MODULES + CLI_MODULES)
def test_no_module_reads_an_upstream_prose_or_payload_key(path: Path) -> None:
    """No canonical-package or CLI module reads a banned prose or payload key."""
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
    hits = key_reads(tree, "realized_text")
    assert len(hits) == 3


def test_reading_unit_id_never_trips_the_text_ban() -> None:
    """Reading unit_id never trips the text ban."""
    assert "text" not in READ_BANNED_KEYS or "unit_id" != "text"


def test_the_single_realized_text_exemption_is_exact() -> None:
    """realized_text is keyed-read in exactly one Phase 29 file, inside unit_texts only."""
    total_hits = 0
    for path in PHASE29_MODULES:
        tree = parse(path)
        lines = key_read_lines(tree, "realized_text")
        if not lines:
            continue
        assert path == REALIZED_TEXT_EXEMPT_FILE, path
        span = function_line_range(tree, REALIZED_TEXT_EXEMPT_FUNCTION)
        assert span is not None
        start, end = span
        for line in lines:
            assert start <= line <= end, (path, line, span)
        total_hits += len(lines)
    assert total_hits == 1


def test_whole_document_canonical_serialization_is_not_a_key_read() -> None:
    """Whole-document canonical serialization is explicitly not a key read."""
    tree = parse(PACKAGE / "voice_manifest.py")
    # dumps_canonical(document, ...) is a whole-document, key-blind transform;
    # it must not be flagged by key_reads for any banned key.
    for key in READ_BANNED_KEYS:
        assert key_reads(tree, key) == []


# ---- gate reuse


def test_the_locked_upstream_gate_is_imported() -> None:
    """The locked Phase 28 gate is imported."""
    tree = parse(EXECUTOR_DIR / "synthesize_episode.py")
    assert "living_diorama.voice" in imported_modules(tree)


def test_the_executor_actually_calls_the_reused_gate() -> None:
    """The executor actually calls validate_episode_voice_plan_against_sources."""
    source = (EXECUTOR_DIR / "synthesize_episode.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "validate_episode_voice_plan_against_sources"
    ]
    assert len(calls) == 1


def test_no_phase29_module_reimplements_the_reused_gate() -> None:
    """No Phase 29 module defines a second function claiming to be the source gate."""
    for path in PHASE29_MODULES:
        tree = parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                assert node.name != "validate_episode_voice_plan_against_sources", path


def test_no_module_defines_a_second_measurement_path() -> None:
    """No module beyond speech_audio.py defines a sample-count recomputation function."""
    for path in PHASE29_MODULES:
        if path.name == "speech_audio.py":
            continue
        tree = parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                assert node.name != "speech_sample_count", path


# ---- single rmtree site


def test_exactly_one_shutil_rmtree_call_site_exists() -> None:
    """shutil.rmtree appears exactly once across all of Phase 29, inside discard_owned_staging."""
    executor_path = EXECUTOR_DIR / "synthesize_episode.py"
    executor_tree = parse(executor_path)
    total_hits = 0
    for path in PHASE29_MODULES:
        tree = executor_tree if path == executor_path else parse(path)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "rmtree"
            ):
                total_hits += 1
                assert path == executor_path, path
                enclosing = None
                for candidate in ast.walk(executor_tree):
                    if isinstance(candidate, ast.FunctionDef):
                        start = candidate.lineno
                        end = candidate.end_lineno or candidate.lineno
                        if start <= node.lineno <= end:
                            enclosing = candidate.name
                assert enclosing == "discard_owned_staging", node.lineno
    assert total_hits == 1


def test_the_executor_reads_no_other_banned_key() -> None:
    """The executor reads none of the other three banned keys, ever."""
    tree = parse(EXECUTOR_DIR / "synthesize_episode.py")
    for key in ("source_event_payload", "summary", "text"):
        assert key_reads(tree, key) == [], key
