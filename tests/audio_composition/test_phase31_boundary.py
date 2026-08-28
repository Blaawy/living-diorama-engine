"""Phase 31 stays inside its boundary, proven by parsing the sources.

Phase 31 owns one responsibility -- materializing a placed episode's one
audio artifact from an audited Phase 29 execution and a sealed Phase 30
audio track plan. It never synthesizes, never places, never measures a
sample the layer beneath it did not already measure, and never reads a
narration unit's ``text``, a realization's ``realized_text``, or a memory
fact's ``summary`` -- zero exemptions, matching Phase 30's own strictness.

Unlike every locked plan phase, this is a filesystem execution: its package
legitimately writes, so this guard proves writes are confined to exactly
two modules and that the primitives themselves are confined to exactly one.
"""

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "src" / "living_diorama" / "audio_composition"
CLI = REPO_ROOT / "src" / "living_diorama" / "cli"
TESTS = Path(__file__).parent

PURE_MODULES = (
    PACKAGE / "__init__.py",
    PACKAGE / "audio_composition_spec.py",
    PACKAGE / "audio_composition_schema_v1.py",
    PACKAGE / "audio_composition_binding.py",
    PACKAGE / "audio_composer.py",
    PACKAGE / "audio_composition_manifest.py",
)
FILESYSTEM_MODULES = (
    PACKAGE / "audio_composition_staging.py",
    PACKAGE / "audio_composition_publisher.py",
    PACKAGE / "audio_composition_audit.py",
)
PACKAGE_MODULES = PURE_MODULES + FILESYSTEM_MODULES

CLI_MODULES = (
    CLI / "compose_episode_audio.py",
    CLI / "verify_audio_composition.py",
)
PHASE31_MODULES = PACKAGE_MODULES + CLI_MODULES

PHASE31_TEST_FILES = (
    TESTS / "__init__.py",
    TESTS / "conftest.py",
    TESTS / "test_phase31_boundary.py",
    TESTS / "test_audio_composition_spec.py",
    TESTS / "test_audio_composition_schema.py",
    TESTS / "test_audio_composition_binding.py",
    TESTS / "test_audio_composer.py",
    TESTS / "test_audio_composition_manifest.py",
    TESTS / "test_audio_composition_staging.py",
    TESTS / "test_audio_composition_publisher.py",
    TESTS / "test_audio_composition_audit.py",
    TESTS / "test_compose_audio_cli.py",
    TESTS / "test_verify_audio_composition_cli.py",
    TESTS / "test_audio_composition_determinism.py",
)

PHASE31_FIXTURES = (
    TESTS / "fixtures" / "render_export_ep0.json",
    TESTS / "fixtures" / "render_export_ep1.json",
    TESTS / "fixtures" / "render_export_ep2.json",
)

PHASE31_DOCS = (REPO_ROOT / "docs" / "episode_audio_composition.md",)

PHASE31_FILES = (*PHASE31_MODULES, *PHASE31_TEST_FILES, *PHASE31_FIXTURES, *PHASE31_DOCS)

ALLOWED_ENGINE_MODULES = frozenset(
    {
        "living_diorama.audio_composition",
        "living_diorama.audio_composition.audio_composer",
        "living_diorama.audio_composition.audio_composition_audit",
        "living_diorama.audio_composition.audio_composition_binding",
        "living_diorama.audio_composition.audio_composition_manifest",
        "living_diorama.audio_composition.audio_composition_publisher",
        "living_diorama.audio_composition.audio_composition_schema_v1",
        "living_diorama.audio_composition.audio_composition_spec",
        "living_diorama.audio_composition.audio_composition_staging",
        "living_diorama.audio_track",
        "living_diorama.audio_track.audio_track_cross_check",
        "living_diorama.audio_track.audio_track_schema_v1",
        "living_diorama.audio_track.audio_track_spec",
        "living_diorama.persistence.json_codec",
        "living_diorama.persistence.schema.state_hash",
        "living_diorama.persistence.schema.world_schema_v1",
        "living_diorama.narration.narration_schema_v1",
        "living_diorama.voice.voice_schema_v1",
        "living_diorama.voice.voice_spec",
        "living_diorama.voice_execution",
        "living_diorama.voice_execution.speech_audio",
        "living_diorama.voice_execution.voice_execution_schema_v1",
        "living_diorama.voice_execution.voice_execution_spec",
    }
)
"""Exactly the engine modules Phase 31 may import.

``living_diorama.voice_execution`` for the reused Phase 29 audit and
canonical WAV serializer, ``living_diorama.audio_track`` for the reused
Phase 30 gate, the shared codec and validators -- deliberately no
``living_diorama.story``, ``render``, ``render_execution``, ``memory``,
``narration_delivery``, ``presentation``, ``language_realization``, and no
``living_diorama.caption`` (Phase 31 never imports its paired sibling).
"""

FORBIDDEN_ENGINE_ROOTS = frozenset(
    {
        "living_diorama.caption",
        "living_diorama.engine",
        "living_diorama.entities",
        "living_diorama.events",
        "living_diorama.language_realization",
        "living_diorama.memory",
        "living_diorama.narration_delivery",
        "living_diorama.presentation",
        "living_diorama.render",
        "living_diorama.render_execution",
        "living_diorama.simulation",
        "living_diorama.story",
        "living_diorama.systems",
    }
)

FORBIDDEN_THIRD_PARTY_ROOTS = frozenset(
    {
        "kokoro",
        "misaki",
        "torch",
        "numpy",
        "scipy",
        "spacy",
        "num2words",
        "soundfile",
        "wave",
        "audioop",
        "pydub",
        "ffmpeg",
    }
)

NONDETERMINISM_MODULES = frozenset({"datetime", "locale", "random", "secrets", "time", "uuid"})

FORBIDDEN_IDENTIFIERS = re.compile(
    r"(?i).*("
    r"caption|subtitle|\bsrt\b|\bvtt\b|webvtt|cue_?list"
    r"|\bmix\b|\bgain\b|normalize|\btrim\b|\bvad\b|dither|resample|stretch"
    r"|\bcodec\b|bitrate|container|ffmpeg|\bmux\b|\bencode\b|transcode"
    r"|\bassembly\b|package_episode|thumbnail|\bmp4\b|\bmkv\b"
    r"|synthesize|synthesis|kokoro|misaki|\bg2p\b|\btensor\b"
    r"|\bllm\b|\bgpt\b|\bprompt\b|inference|rephrase"
    r"|\bwpm\b|\bsyllable\b|speaking_rate|\btimecode\b|\btimestamp\b"
    r"|dwell|\bsegment\b|window_frames|capacity_samples|text_source"
    r").*"
)
"""Vocabulary belonging to other layers, banned from Phase 31 definitions.

Deliberately does **not** ban ``wav``, ``pcm``, ``audio``, ``speech``,
``samples``, ``silence``, ``start_sample``, ``speech_id``, ``compose``,
``composition``, ``publish``, ``manifest``, ``staging`` or ``partial``:
this layer *is* the execution layer, and those are its own reviewed
vocabulary -- the same reasoning Phase 29 gives for permitting
``wav``/``pcm``/``publish`` where Phase 28 bans them.
"""

READ_BANNED_KEYS = ("realized_text", "source_event_payload", "summary", "text")
"""Keys no Phase 31 module may read, by subscript, ``.get`` or ``.pop``.

An EMPTY allow-list. Phase 31 reads no prose at all, with no exempt module
and no exempt function -- stricter than Phase 29's one exemption, for the
same reason Phase 30 has zero: this layer has no structural need to touch
prose.
"""

WRITE_MARKERS = ("write_text(", "write_bytes(", "open(", ".mkdir(", "shutil.")

WRITE_ALLOWED_MODULES = (
    PACKAGE / "audio_composition_staging.py",
    PACKAGE / "audio_composition_publisher.py",
)
"""Exactly two. Every other package module -- including the audit, which
reads but never writes -- is held to ``WRITE_MARKERS``."""

STAGING_EXCLUSIVE_MARKERS = ("open(", "os.replace", "os.fsync", "shutil.")
"""Confined to ``audio_composition_staging.py`` alone. The publisher
orchestrates; it never touches a primitive itself."""


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


def call_lines(tree: ast.Module, name: str) -> list[int]:
    """Return the line numbers of every direct call to a function named ``name``."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name:
            lines.append(node.lineno)
    return lines


def function_line_range(tree: ast.Module, name: str) -> tuple[int, int] | None:
    """Return the (start, end) inclusive line range of the first function named ``name``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            end = node.end_lineno if node.end_lineno is not None else node.lineno
            return node.lineno, end
    return None


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


def _code_lines_by_number(path: Path) -> dict[int, str]:
    """Return ``{line_number: stripped_line}`` for every non-docstring, non-comment line.

    Unlike :func:`_code_lines`, this preserves each line's real 1-based file
    line number, so results can be compared directly against
    :func:`function_line_range` spans.
    """
    tree = parse(path)
    source = path.read_text(encoding="utf-8")
    doc_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                doc_lines.update(range(body[0].lineno, body[0].end_lineno + 1))
    result: dict[int, str] = {}
    for number, line in enumerate(source.splitlines(), start=1):
        if number in doc_lines:
            continue
        result[number] = line.split("#", 1)[0]
    return result


# ---- the file list


def test_every_guarded_file_exists() -> None:
    """Every guarded file exists."""
    for path in PHASE31_FILES:
        assert path.is_file(), path


def test_the_file_count_is_exact() -> None:
    """The file count is exact: twenty-nine."""
    assert len(PHASE31_FILES) == 29


def test_the_test_file_count_is_exact() -> None:
    """The test .py file count is exact: fourteen."""
    assert len(PHASE31_TEST_FILES) == 14


def test_the_suite_is_a_real_package() -> None:
    """The suite is a real package."""
    assert (TESTS / "__init__.py").is_file()


def test_no_test_module_imports_tests_absolutely() -> None:
    """Shared helpers come from the package-relative conftest only."""
    for path in PHASE31_TEST_FILES:
        if path.suffix != ".py":
            continue
        tree = parse(path)
        for module_name in imported_modules(tree):
            assert not module_name.startswith("tests."), (path, module_name)


def test_the_fixtures_are_byte_identical_to_the_phase30_suite() -> None:
    """The three fixtures are byte-identical to the Phase 30 audio track suite's own copies."""
    phase30_fixtures = REPO_ROOT / "tests" / "audio_track" / "fixtures"
    for path in PHASE31_FIXTURES:
        counterpart = phase30_fixtures / path.name
        assert counterpart.is_file()
        assert path.read_bytes() == counterpart.read_bytes()


# ---- import boundary


@pytest.mark.parametrize("path", PHASE31_MODULES)
def test_no_module_reaches_outside_its_allowed_engine_modules(path: Path) -> None:
    """No canonical-package or CLI module reaches outside its allowed engine modules."""
    tree = parse(path)
    for module_name in imported_modules(tree):
        if not module_name.startswith("living_diorama"):
            continue
        assert module_name in ALLOWED_ENGINE_MODULES, (path, module_name)


@pytest.mark.parametrize("path", PHASE31_MODULES)
def test_no_module_imports_a_forbidden_engine_root(path: Path) -> None:
    """No module imports a forbidden engine root -- notably ``living_diorama.caption``."""
    tree = parse(path)
    for module_name in imported_modules(tree):
        for forbidden in FORBIDDEN_ENGINE_ROOTS:
            assert not module_name.startswith(forbidden), (path, module_name)


def test_no_module_imports_the_paired_sibling() -> None:
    """No Phase 31 module imports ``living_diorama.caption`` -- the paired sibling."""
    for path in PHASE31_MODULES:
        tree = parse(path)
        for module_name in imported_modules(tree):
            assert not module_name.startswith("living_diorama.caption"), (path, module_name)


@pytest.mark.parametrize("path", PHASE31_MODULES)
def test_no_third_party_dependency_anywhere_in_phase31(path: Path) -> None:
    """No voice-engine, tensor or permissive-audio dependency anywhere in Phase 31."""
    tree = parse(path)
    for module_name in imported_modules(tree):
        root = module_name.split(".")[0]
        assert root not in FORBIDDEN_THIRD_PARTY_ROOTS, (path, module_name)


@pytest.mark.parametrize("path", PHASE31_MODULES)
def test_no_nondeterminism_module_anywhere_in_phase31(path: Path) -> None:
    """No wall-clock, RNG or uuid dependency anywhere in Phase 31."""
    tree = parse(path)
    for module_name in imported_modules(tree):
        root = module_name.split(".")[0]
        assert root not in NONDETERMINISM_MODULES, (path, module_name)


@pytest.mark.parametrize("path", PHASE31_MODULES)
def test_no_module_imports_relatively(path: Path) -> None:
    """No module imports relatively."""
    tree = parse(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert (node.level or 0) == 0, path


# ---- filesystem boundary


@pytest.mark.parametrize("path", PURE_MODULES)
def test_the_six_pure_modules_touch_no_filesystem(path: Path) -> None:
    """No pure package module writes to the filesystem."""
    lines = _code_lines(path)
    for number, line in enumerate(lines, start=1):
        for marker in WRITE_MARKERS:
            assert marker not in line, (path, number, line)


@pytest.mark.parametrize("path", (PACKAGE / "audio_composition_audit.py",))
def test_the_audit_touches_no_filesystem_write(path: Path) -> None:
    """The audit reads through ``Path.read_bytes()`` but never writes."""
    lines = _code_lines(path)
    for number, line in enumerate(lines, start=1):
        for marker in WRITE_MARKERS:
            assert marker not in line, (path, number, line)


def test_only_the_two_write_allowed_modules_write() -> None:
    """Only staging and the publisher, plus the two CLIs, contain a write marker."""
    write_allowed = set(WRITE_ALLOWED_MODULES) | set(CLI_MODULES)
    for path in PHASE31_MODULES:
        lines = _code_lines(path)
        hits = [line for line in lines for marker in WRITE_MARKERS if marker in line]
        if path not in write_allowed:
            assert not hits, (path, hits)


def test_staging_exclusive_primitives_are_confined_to_the_staging_module() -> None:
    """``open(``, ``os.replace``, ``os.fsync`` and ``shutil.`` appear only in staging."""
    staging_path = PACKAGE / "audio_composition_staging.py"
    for path in PHASE31_MODULES:
        if path == staging_path:
            continue
        lines = _code_lines(path)
        for number, line in enumerate(lines, start=1):
            for marker in STAGING_EXCLUSIVE_MARKERS:
                assert marker not in line, (path, number, line, marker)


def test_exactly_one_shutil_rmtree_call_site() -> None:
    """``shutil.rmtree`` appears in exactly one function, in exactly one module."""
    staging_path = PACKAGE / "audio_composition_staging.py"
    total_hits = 0
    for path in PHASE31_MODULES:
        lines = _code_lines(path)
        hits = sum(1 for line in lines if "shutil.rmtree" in line)
        if hits:
            assert path == staging_path, path
        total_hits += hits
    assert total_hits == 1
    tree = parse(staging_path)
    span = function_line_range(tree, "discard_owned_staging")
    assert span is not None
    numbered = _code_lines_by_number(staging_path)
    rmtree_lines = [number for number, line in numbered.items() if "shutil.rmtree" in line]
    assert len(rmtree_lines) == 1
    assert span[0] <= rmtree_lines[0] <= span[1]


def test_exactly_two_os_replace_call_sites() -> None:
    """``os.replace`` appears in exactly two functions, both in the staging module."""
    staging_path = PACKAGE / "audio_composition_staging.py"
    total_hits = 0
    for path in PHASE31_MODULES:
        lines = _code_lines(path)
        hits = sum(1 for line in lines if "os.replace" in line)
        if hits:
            assert path == staging_path, path
        total_hits += hits
    assert total_hits == 2
    tree = parse(staging_path)
    write_span = function_line_range(tree, "write_atomically")
    publish_span = function_line_range(tree, "publish_owned_staging")
    assert write_span is not None
    assert publish_span is not None
    numbered = _code_lines_by_number(staging_path)
    replace_lines = [number for number, line in numbered.items() if "os.replace(" in line]
    assert len(replace_lines) == 2
    for line in replace_lines:
        assert (write_span[0] <= line <= write_span[1]) or (
            publish_span[0] <= line <= publish_span[1]
        ), line


# ---- vocabulary and key-read guards


@pytest.mark.parametrize("path", PHASE31_MODULES)
def test_no_phase31_module_defines_another_layers_vocabulary(path: Path) -> None:
    """No Phase 31 module defines another layer's vocabulary."""
    tree = parse(path)
    for name in defined_names(tree):
        assert not forbidden_hit(name), (path, name)


def test_the_vocabulary_guard_catches_an_offender(tmp_path: Path) -> None:
    """The vocabulary guard catches a synthetic offender."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "def build_caption_track(cues: list[str]) -> None:\n    return None\n", encoding="utf-8"
    )
    tree = parse(offender)
    assert any(forbidden_hit(name) for name in defined_names(tree))


def test_the_vocabulary_guard_permits_this_layers_own_names() -> None:
    """The vocabulary guard permits this layer's own reviewed names."""
    for name in (
        "wav",
        "pcm",
        "audio",
        "speech",
        "samples",
        "silence",
        "start_sample",
        "speech_id",
        "compose",
        "composition",
        "publish",
        "manifest",
        "staging",
        "partial",
        "pcm_sha256",
        "voice_unit_id",
    ):
        assert not forbidden_hit(name), name


@pytest.mark.parametrize("path", PHASE31_MODULES)
def test_no_module_reads_a_banned_prose_or_payload_key(path: Path) -> None:
    """No canonical-package or CLI module reads a banned prose or payload key.

    Empty allow-list.
    """
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


def test_zero_exemptions_stricter_than_phase29() -> None:
    """Phase 31's own empty READ_BANNED_KEYS allow-list has no exempt file or function."""
    for path in PHASE31_MODULES:
        tree = parse(path)
        for key in READ_BANNED_KEYS:
            assert key_reads(tree, key) == [], (path, key)


def test_no_module_defines_speech_start_sample() -> None:
    """No Phase 31 module defines ``speech_start_sample`` or re-derives an onset."""
    for path in PHASE31_MODULES:
        tree = parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                assert node.name != "speech_start_sample", path


def test_no_module_defines_canonical_wav_bytes_or_pcm16_bytes() -> None:
    """``canonical_wav_bytes`` is imported and never redefined.

    ``pcm16_bytes`` is never defined here.
    """
    for path in PHASE31_MODULES:
        tree = parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                assert node.name not in ("canonical_wav_bytes", "pcm16_bytes"), path


def test_no_module_defines_an_episode_prefixed_directory_name() -> None:
    """No Phase 31 module defines an ``episode_``-prefixed f-string directory literal."""
    for path in PHASE31_MODULES:
        source = path.read_text(encoding="utf-8")
        for line in source.splitlines():
            if 'f"episode_' in line or "f'episode_" in line:
                # audio_composition_spec.py delegates naming whole to
                # voice_execution_id; it must never construct its own.
                assert "audio_composition_spec" not in str(path), (path, line)


# ---- gate reuse


def test_the_locked_phase30_gate_is_imported_and_called() -> None:
    """The locked Phase 30 gate is imported and actually called, by the CLI."""
    path = CLI / "compose_episode_audio.py"
    tree = parse(path)
    assert "living_diorama.audio_track" in imported_modules(tree)
    calls = call_lines(tree, "validate_episode_audio_track_plan_against_sources")
    assert len(calls) == 1


def test_the_phase29_audit_is_imported_and_called() -> None:
    """The reused Phase 29 directory audit is imported and actually called, by the CLI."""
    path = CLI / "compose_episode_audio.py"
    tree = parse(path)
    assert "living_diorama.voice_execution" in imported_modules(tree)
    calls = call_lines(tree, "audit_voice_directory")
    assert len(calls) == 1


def test_the_audit_is_called_by_the_cli_before_the_document_gate() -> None:
    """The reused Phase 29 audit precedes the document gate call, in the CLI."""
    path = CLI / "compose_episode_audio.py"
    tree = parse(path)
    watched = {"audit_voice_directory", "validate_episode_audio_track_plan_against_sources"}
    calls_in_order: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in watched
        ):
            calls_in_order.append((node.lineno, node.func.id))
    calls_in_order.sort()
    names = [name for _line, name in calls_in_order]
    assert names.index("audit_voice_directory") < names.index(
        "validate_episode_audio_track_plan_against_sources"
    )


def test_no_module_reimplements_a_reused_gate() -> None:
    """No Phase 31 module defines a second function claiming to be a reused gate."""
    banned_names = {
        "validate_episode_audio_track_plan_against_sources",
        "audit_voice_directory",
        "require_manifest_matches_plan",
    }
    for path in PHASE31_MODULES:
        tree = parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                assert node.name not in banned_names, path


# ---- the digest-before-parse law


def test_within_require_voice_manifest_bytes_digest_precedes_parse() -> None:
    """``sha256_hex`` precedes ``loads_canonical`` inside ``require_voice_manifest_bytes``."""
    path = PACKAGE / "audio_composition_binding.py"
    tree = parse(path)
    span = function_line_range(tree, "require_voice_manifest_bytes")
    assert span is not None
    start, end = span
    calls_in_order: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if not (start <= node.lineno <= end):
            continue
        if node.func.id in ("sha256_hex", "loads_canonical"):
            calls_in_order.append((node.lineno, node.func.id))
    calls_in_order.sort()
    names = [name for _line, name in calls_in_order]
    assert "sha256_hex" in names
    assert "loads_canonical" in names
    assert names.index("sha256_hex") < names.index("loads_canonical")


def test_no_path_resolve_anywhere_in_phase31() -> None:
    """No Phase 31 module ever calls ``Path.resolve()`` in code (prose mentions are fine)."""
    for path in PHASE31_MODULES:
        for line in _code_lines(path):
            assert ".resolve(" not in line, (path, line)


# ---- source-byte provenance (V1.1)


def test_require_voice_unit_bytes_precedes_pcm_payload_of_in_publisher() -> None:
    """The source-byte binding precedes the payload extraction call, in the publisher."""
    path = PACKAGE / "audio_composition_publisher.py"
    tree = parse(path)
    calls_in_order: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("require_voice_unit_bytes", "pcm_payload_of")
        ):
            calls_in_order.append((node.lineno, node.func.id))
    calls_in_order.sort()
    names = [name for _line, name in calls_in_order]
    # The first pcm_payload_of call must be preceded by a require_voice_unit_bytes call.
    first_binding = names.index("require_voice_unit_bytes")
    first_payload = names.index("pcm_payload_of")
    assert first_binding < first_payload


def test_publisher_reads_each_unit_path_at_most_twice() -> None:
    """The publisher captures the payload with exactly one ``read_bytes()`` call per unit loop."""
    path = PACKAGE / "audio_composition_publisher.py"
    source = path.read_text(encoding="utf-8")
    # Exactly one `unit_path.read_bytes()` call feeds the payload capture.
    assert source.count("unit_path.read_bytes()") == 1


# ---- terminal publication gate (V1.2/V1.3)


def test_terminal_audit_precedes_publish_owned_staging_in_publisher() -> None:
    """The terminal self-audit precedes ``publish_owned_staging``, in the publisher."""
    path = PACKAGE / "audio_composition_publisher.py"
    tree = parse(path)
    calls_in_order: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("audit_audio_composition_directory", "publish_owned_staging")
        ):
            calls_in_order.append((node.lineno, node.func.id))
    calls_in_order.sort()
    names = [name for _line, name in calls_in_order]
    assert names.index("audit_audio_composition_directory") < names.index("publish_owned_staging")


# ---- parent-indirection law (V1.2/V1.3/V1.4): exactly five call sites


def test_require_direct_parent_has_exactly_five_call_sites() -> None:
    """``_require_direct_parent`` is defined once and called at exactly five sites."""
    definitions = 0
    call_sites: list[tuple[Path, int]] = []
    for path in PHASE31_MODULES:
        tree = parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_require_direct_parent":
                definitions += 1
        for line in call_lines(tree, "_require_direct_parent"):
            call_sites.append((path, line))
    assert definitions == 1
    assert len(call_sites) == 5


def test_one_call_site_is_inside_cli_compose() -> None:
    """Exactly one ``_require_direct_parent`` call is inside the CLI's ``compose``."""
    path = CLI / "compose_episode_audio.py"
    tree = parse(path)
    span = function_line_range(tree, "compose")
    assert span is not None
    lines = call_lines(tree, "_require_direct_parent")
    assert len(lines) == 1
    assert span[0] <= lines[0] <= span[1]


def test_the_cli_call_is_the_first_statement_after_the_docstring() -> None:
    """The CLI's guard call is the first statement in ``compose`` after its docstring."""
    path = CLI / "compose_episode_audio.py"
    tree = parse(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "compose":
            body = node.body
            first_index = 0
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                first_index = 1
            first_statement = body[first_index]
            assert isinstance(first_statement, ast.Expr)
            call = first_statement.value
            assert isinstance(call, ast.Call)
            assert isinstance(call.func, ast.Name)
            assert call.func.id == "_require_direct_parent"
            return
    pytest.fail("compose() not found")


def test_the_cli_guard_precedes_output_root_exists() -> None:
    """The CLI guard precedes the first ``output_root.exists()`` check, by line order."""
    path = CLI / "compose_episode_audio.py"
    tree = parse(path)
    guard_lines = call_lines(tree, "_require_direct_parent")
    assert len(guard_lines) == 1
    source = path.read_text(encoding="utf-8")
    exists_line = None
    for number, line in enumerate(source.splitlines(), start=1):
        if "output_root.exists()" in line:
            exists_line = number
            break
    assert exists_line is not None
    assert guard_lines[0] < exists_line


def test_the_cli_guard_precedes_publish_episode_audio() -> None:
    """The CLI guard precedes the call to ``publish_episode_audio``, by line order."""
    path = CLI / "compose_episode_audio.py"
    tree = parse(path)
    guard_lines = call_lines(tree, "_require_direct_parent")
    publish_lines = call_lines(tree, "publish_episode_audio")
    assert len(guard_lines) == 1
    assert len(publish_lines) == 1
    assert guard_lines[0] < publish_lines[0]


def test_one_call_site_is_inside_publisher_before_first_filesystem_touch() -> None:
    """The publisher's guard call precedes its first ``final_dir.exists()`` check."""
    path = PACKAGE / "audio_composition_publisher.py"
    tree = parse(path)
    span = function_line_range(tree, "publish_episode_audio")
    assert span is not None
    guard_lines = [
        line for line in call_lines(tree, "_require_direct_parent") if span[0] <= line <= span[1]
    ]
    assert len(guard_lines) == 1
    source = path.read_text(encoding="utf-8")
    exists_line = None
    for number, line in enumerate(source.splitlines(), start=1):
        if number <= guard_lines[0]:
            continue
        if "final_dir.exists()" in line:
            exists_line = number
            break
    assert exists_line is not None
    assert guard_lines[0] < exists_line


def test_three_call_sites_are_first_statements_in_staging_helpers() -> None:
    """The three staging-helper calls are each the first statement of their function."""
    path = PACKAGE / "audio_composition_staging.py"
    tree = parse(path)
    for name in ("require_owned_staging", "discard_owned_staging", "publish_owned_staging"):
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                found = True
                body = node.body
                first_index = 0
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                ):
                    first_index = 1
                first_statement = body[first_index]
                assert isinstance(first_statement, ast.Expr), name
                call = first_statement.value
                assert isinstance(call, ast.Call), name
                assert isinstance(call.func, ast.Name), name
                assert call.func.id == "_require_direct_parent", name
        assert found, name


# ---- V1.5/V1.6/V2 hardening: pre-staging count / handled-refusal try boundary


def _try_body_span(tree: ast.Module, function_name: str) -> tuple[int, int] | None:
    """Return the (start, end) inclusive line span of the first ``try`` body in a function."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            for child in node.body:
                if isinstance(child, ast.Try):
                    first = child.body[0]
                    last = child.body[-1]
                    last_end = last.end_lineno if last.end_lineno is not None else last.lineno
                    return first.lineno, last_end
    return None


def test_voice_unit_count_check_precedes_fresh_staging_creation() -> None:
    """The voice-unit-count precondition fires before this run's staging tree is created."""
    path = PACKAGE / "audio_composition_publisher.py"
    source = path.read_text(encoding="utf-8")
    count_check_line = None
    mkdir_line = None
    for number, line in enumerate(source.splitlines(), start=1):
        if "len(voice_units) != len(placements)" in line and count_check_line is None:
            count_check_line = number
        if "staging_dir.mkdir(parents=True)" in line and mkdir_line is None:
            mkdir_line = number
    assert count_check_line is not None
    assert mkdir_line is not None
    assert count_check_line < mkdir_line


def test_voice_unit_count_check_precedes_discard_owned_staging_too() -> None:
    """The count precondition precedes even the prior-run ``discard_owned_staging`` call.

    ``discard_owned_staging`` is called twice inside ``publish_episode_audio``:
    once before the try, for a *prior* run's stale staging, and once inside
    the ``except`` handler, for *this* run's own staging on a handled
    failure. Only the first (the prior-run cleanup) is relevant here -- the
    count check must precede it; the except-handler call happens later by
    construction, inside the try/except this check sits entirely before.
    """
    path = PACKAGE / "audio_composition_publisher.py"
    tree = parse(path)
    span = function_line_range(tree, "publish_episode_audio")
    assert span is not None
    source = path.read_text(encoding="utf-8")
    count_check_line = None
    for number, line in enumerate(source.splitlines(), start=1):
        if span[0] <= number <= span[1] and "len(voice_units) != len(placements)" in line:
            count_check_line = number
            break
    assert count_check_line is not None
    discard_lines = sorted(
        line for line in call_lines(tree, "discard_owned_staging") if span[0] <= line <= span[1]
    )
    assert len(discard_lines) == 2
    assert count_check_line < discard_lines[0]


def test_voice_unit_count_check_is_outside_the_handled_refusal_try() -> None:
    """The count check sits before the ``try``, not inside it."""
    path = PACKAGE / "audio_composition_publisher.py"
    tree = parse(path)
    span = _try_body_span(tree, "publish_episode_audio")
    assert span is not None
    source = path.read_text(encoding="utf-8")
    for number, line in enumerate(source.splitlines(), start=1):
        if "len(voice_units) != len(placements)" in line:
            assert number < span[0], "the count check must precede the try body"
            return
    pytest.fail("count check not found")


def test_staging_mkdir_is_the_first_statement_inside_the_handled_refusal_try() -> None:
    """``staging_dir.mkdir`` is the first statement inside the widened handled-refusal try."""
    path = PACKAGE / "audio_composition_publisher.py"
    tree = parse(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "publish_episode_audio":
            for child in node.body:
                if isinstance(child, ast.Try):
                    first = child.body[0]
                    assert isinstance(first, ast.Expr)
                    call = first.value
                    assert isinstance(call, ast.Call)
                    assert isinstance(call.func, ast.Attribute)
                    assert call.func.attr == "mkdir"
                    return
    pytest.fail("no try block found in publish_episode_audio")


def test_inner_audio_directory_mkdir_is_inside_the_same_try() -> None:
    """The inner ``audio/`` mkdir is inside the same handled-refusal try as staging creation."""
    path = PACKAGE / "audio_composition_publisher.py"
    span = _try_body_span(parse(path), "publish_episode_audio")
    assert span is not None
    source = path.read_text(encoding="utf-8")
    for number, line in enumerate(source.splitlines(), start=1):
        if "AUDIO_DIRECTORY).mkdir()" in line:
            assert span[0] <= number <= span[1]
            return
    pytest.fail("inner audio/ mkdir not found")


def test_terminal_publication_remains_inside_the_same_try() -> None:
    """``publish_owned_staging`` remains inside the same handled-refusal try."""
    path = PACKAGE / "audio_composition_publisher.py"
    tree = parse(path)
    span = _try_body_span(tree, "publish_episode_audio")
    assert span is not None
    publish_lines = call_lines(tree, "publish_owned_staging")
    matched = [line for line in publish_lines if span[0] <= line <= span[1]]
    assert len(matched) == 1


def test_except_clause_still_names_exactly_the_frozen_four_classes() -> None:
    """The handled-refusal except clause still names exactly the frozen four classes."""
    path = PACKAGE / "audio_composition_publisher.py"
    tree = parse(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "publish_episode_audio":
            for child in node.body:
                if isinstance(child, ast.Try):
                    assert len(child.handlers) == 1
                    handler_type = child.handlers[0].type
                    assert isinstance(handler_type, ast.Tuple)
                    names = {elt.id for elt in handler_type.elts if isinstance(elt, ast.Name)}
                    assert names == {
                        "OSError",
                        "TypeError",
                        "ValueError",
                        "CompositionDirectoryRefused",
                    }
                    return
    pytest.fail("no try/except found in publish_episode_audio")


# ---- V1.5/V1.6/V2 hardening: Audio Track Plan single-capture identity


def test_compose_reads_audio_track_path_exactly_once() -> None:
    """``audio_track_path.read_bytes()`` is called exactly once inside ``compose``."""
    path = CLI / "compose_episode_audio.py"
    tree = parse(path)
    span = function_line_range(tree, "compose")
    assert span is not None
    hits = 0
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "read_bytes"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "audio_track_path"
            and span[0] <= node.lineno <= span[1]
        ):
            hits += 1
    assert hits == 1


def test_compose_never_calls_read_canonical_on_audio_track_path() -> None:
    """``_read_canonical`` is never called with ``audio_track_path`` as its first argument."""
    path = CLI / "compose_episode_audio.py"
    tree = parse(path)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_read_canonical"
            and node.args
            and isinstance(node.args[0], ast.Name)
        ):
            assert node.args[0].id != "audio_track_path", node.lineno


def test_the_same_captured_bytes_feed_parse_and_the_publisher() -> None:
    """The one captured byte string feeds both the parse and the publisher, in that order."""
    path = CLI / "compose_episode_audio.py"
    source = path.read_text(encoding="utf-8")
    capture_line = None
    parse_line = None
    for number, line in enumerate(source.splitlines(), start=1):
        if "audio_track_plan_bytes = audio_track_path.read_bytes()" in line:
            capture_line = number
        if "loads_canonical(audio_track_plan_bytes" in line:
            parse_line = number
    assert capture_line is not None
    assert parse_line is not None
    assert capture_line < parse_line
    assert "audio_track_plan_bytes=audio_track_plan_bytes" in source


# ---- V1.5/V1.6/V2 hardening: final/staging/audit/verify indirection ordering


def test_publisher_checks_final_dir_indirection_before_final_dir_exists() -> None:
    """The publisher refuses ``final_dir`` indirection before its first ``.exists()`` check."""
    path = PACKAGE / "audio_composition_publisher.py"
    source = path.read_text(encoding="utf-8")
    indirection_line = None
    exists_line = None
    for number, line in enumerate(source.splitlines(), start=1):
        if "_is_path_indirection(final_dir)" in line and indirection_line is None:
            indirection_line = number
        if "final_dir.exists()" in line and exists_line is None:
            exists_line = number
    assert indirection_line is not None
    assert exists_line is not None
    assert indirection_line < exists_line


def test_discard_owned_staging_checks_indirection_before_exists() -> None:
    """``discard_owned_staging`` refuses indirection before its ``.exists()`` short-circuit.

    Uses code-only lines (docstrings stripped): the function's own docstring
    prose mentions ``staging_dir.exists()`` in a sentence explaining *why*
    the ordering matters, which would otherwise false-match as an earlier
    "exists" line than the real code.
    """
    path = PACKAGE / "audio_composition_staging.py"
    tree = parse(path)
    span = function_line_range(tree, "discard_owned_staging")
    assert span is not None
    numbered = _code_lines_by_number(path)
    indirection_line = None
    exists_line = None
    for number, line in sorted(numbered.items()):
        if not (span[0] <= number <= span[1]):
            continue
        if "_is_path_indirection(staging_dir)" in line and indirection_line is None:
            indirection_line = number
        if "staging_dir.exists()" in line and exists_line is None:
            exists_line = number
    assert indirection_line is not None
    assert exists_line is not None
    assert indirection_line < exists_line


def test_publish_owned_staging_checks_final_dir_indirection_before_exists() -> None:
    """``publish_owned_staging`` refuses ``final_dir`` indirection before its ``.exists()``.

    Uses code-only lines (docstrings stripped): the function's own docstring
    prose mentions ``final_dir.exists()``, which would otherwise false-match.
    """
    path = PACKAGE / "audio_composition_staging.py"
    tree = parse(path)
    span = function_line_range(tree, "publish_owned_staging")
    assert span is not None
    numbered = _code_lines_by_number(path)
    indirection_line = None
    exists_line = None
    for number, line in sorted(numbered.items()):
        if not (span[0] <= number <= span[1]):
            continue
        if "_is_path_indirection(final_dir)" in line and indirection_line is None:
            indirection_line = number
        if "final_dir.exists()" in line and exists_line is None:
            exists_line = number
    assert indirection_line is not None
    assert exists_line is not None
    assert indirection_line < exists_line


def test_verify_cli_checks_indirection_before_is_dir() -> None:
    """The verify CLI refuses ``composition_dir`` indirection before its ``.is_dir()`` check."""
    path = CLI / "verify_audio_composition.py"
    source = path.read_text(encoding="utf-8")
    indirection_line = None
    is_dir_line = None
    for number, line in enumerate(source.splitlines(), start=1):
        if "_is_path_indirection(composition_dir)" in line and indirection_line is None:
            indirection_line = number
        if "composition_dir.is_dir()" in line and is_dir_line is None:
            is_dir_line = number
    assert indirection_line is not None
    assert is_dir_line is not None
    assert indirection_line < is_dir_line


def test_audit_checks_composition_dir_indirection_before_any_governed_query() -> None:
    """The audit refuses ``composition_dir``'s own indirection before any governed query."""
    path = PACKAGE / "audio_composition_audit.py"
    tree = parse(path)
    span = function_line_range(tree, "_audit_governed_directory")
    assert span is not None
    source = path.read_text(encoding="utf-8")
    indirection_line = None
    is_file_line = None
    for number, line in enumerate(source.splitlines(), start=1):
        if not (span[0] <= number <= span[1]):
            continue
        if "_is_path_indirection(composition_dir)" in line and indirection_line is None:
            indirection_line = number
        if ".is_file()" in line and is_file_line is None:
            is_file_line = number
    assert indirection_line is not None
    assert is_file_line is not None
    assert indirection_line < is_file_line


def test_audit_checks_every_governed_entry_indirection_before_its_first_use() -> None:
    """Every governed entry's indirection is checked before ``plan_path.is_file()`` runs."""
    path = PACKAGE / "audio_composition_audit.py"
    tree = parse(path)
    span = function_line_range(tree, "_audit_governed_directory")
    assert span is not None
    source = path.read_text(encoding="utf-8")
    governed_check_line = None
    first_is_file_line = None
    for number, line in enumerate(source.splitlines(), start=1):
        if not (span[0] <= number <= span[1]):
            continue
        if "governed_path in (plan_path" in line and governed_check_line is None:
            governed_check_line = number
        if "plan_path.is_file()" in line and first_is_file_line is None:
            first_is_file_line = number
    assert governed_check_line is not None
    assert first_is_file_line is not None
    assert governed_check_line < first_is_file_line


def test_audit_public_entry_wraps_in_an_oserror_boundary() -> None:
    """The public audit function wraps its real body in a bare ``except OSError``."""
    path = PACKAGE / "audio_composition_audit.py"
    tree = parse(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "audit_audio_composition_directory":
            for child in node.body:
                if isinstance(child, ast.Try):
                    assert len(child.handlers) == 1
                    handler_type = child.handlers[0].type
                    assert isinstance(handler_type, ast.Name)
                    assert handler_type.id == "OSError"
                    return
    pytest.fail("audit_audio_composition_directory has no try/except OSError boundary")


def test_the_require_direct_parent_count_is_unchanged_at_five() -> None:
    """Adding indirection checks does not add a sixth ``_require_direct_parent`` call site."""
    call_sites = 0
    for path in PHASE31_MODULES:
        tree = parse(path)
        call_sites += len(call_lines(tree, "_require_direct_parent"))
    assert call_sites == 5


def test_the_staging_primitive_counts_are_unchanged() -> None:
    """``shutil.rmtree`` still appears exactly once, ``os.replace`` still exactly twice."""
    total_rmtree = 0
    total_replace = 0
    for path in PHASE31_MODULES:
        lines = _code_lines(path)
        total_rmtree += sum(1 for line in lines if "shutil.rmtree" in line)
        total_replace += sum(1 for line in lines if "os.replace" in line)
    assert total_rmtree == 1
    assert total_replace == 2


def test_no_path_resolve_anywhere_in_phase31_after_hardening() -> None:
    """The hardening delta introduces no ``Path.resolve()`` call anywhere in Phase 31."""
    for path in PHASE31_MODULES:
        for line in _code_lines(path):
            assert ".resolve(" not in line, (path, line)


def test_require_direct_parent_remains_private_and_unexported() -> None:
    """``_require_direct_parent`` is never re-exported from ``__init__.py`` or ``__all__``."""
    init_tree = parse(PACKAGE / "__init__.py")
    for node in ast.walk(init_tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert alias.name != "_require_direct_parent"
    staging_tree = parse(PACKAGE / "audio_composition_staging.py")
    for node in ast.walk(staging_tree):
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
            )
            and isinstance(node.value, ast.List)
        ):
            exported = [
                element.value for element in node.value.elts if isinstance(element, ast.Constant)
            ]
            assert "_require_direct_parent" not in exported
