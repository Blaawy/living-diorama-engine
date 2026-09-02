"""Phase 32 stays inside its boundary, proven by parsing the sources.

Phase 32 owns one responsibility -- projecting each locked Phase 26 sentence
onto its Phase 27 presentation window as one caption cue. It never measures
speech, never reads a sample, never imports Phase 29/30/31 or its paired
sibling ``living_diorama.audio_composition``, and carries prose under a
narrow, AST-counted exemption rather than a blanket ban: ``realized_text``
and ``caption_text`` are each read in exactly two scoped functions, and
exactly one identity comparison exists, proving a downstream restatement
equals its bound upstream authority -- never semantic branching on content.
"""

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "src" / "living_diorama" / "caption"
CLI = REPO_ROOT / "src" / "living_diorama" / "cli"
TESTS = Path(__file__).parent

PURE_MODULES = (
    PACKAGE / "__init__.py",
    PACKAGE / "caption_spec.py",
    PACKAGE / "caption_schema_v1.py",
    PACKAGE / "caption_planner.py",
    PACKAGE / "caption_cross_check.py",
)
CLI_MODULES = (CLI / "build_caption_plan.py",)
PHASE32_MODULES = PURE_MODULES + CLI_MODULES

PHASE32_TEST_FILES = (
    TESTS / "__init__.py",
    TESTS / "conftest.py",
    TESTS / "test_phase32_boundary.py",
    TESTS / "test_caption_spec.py",
    TESTS / "test_caption_schema.py",
    TESTS / "test_caption_planner.py",
    TESTS / "test_caption_cross_check.py",
    TESTS / "test_caption_cli.py",
    TESTS / "test_caption_determinism.py",
)

PHASE32_FIXTURES = (
    TESTS / "fixtures" / "render_export_ep0.json",
    TESTS / "fixtures" / "render_export_ep1.json",
    TESTS / "fixtures" / "render_export_ep2.json",
)

PHASE32_DOCS = (REPO_ROOT / "docs" / "episode_caption_plan.md",)

PHASE32_FILES = (*PHASE32_MODULES, *PHASE32_TEST_FILES, *PHASE32_FIXTURES, *PHASE32_DOCS)

ALLOWED_ENGINE_MODULES = frozenset(
    {
        "living_diorama.caption",
        "living_diorama.caption.caption_cross_check",
        "living_diorama.caption.caption_planner",
        "living_diorama.caption.caption_schema_v1",
        "living_diorama.caption.caption_spec",
        "living_diorama.language_realization.realization_schema_v1",
        "living_diorama.language_realization.realization_spec",
        "living_diorama.narration.narration_schema_v1",
        "living_diorama.persistence.json_codec",
        "living_diorama.persistence.schema.state_hash",
        "living_diorama.persistence.schema.world_schema_v1",
        "living_diorama.presentation.presentation_cross_check",
        "living_diorama.presentation.presentation_schema_v1",
        "living_diorama.presentation.presentation_schema_v2",
        "living_diorama.presentation.presentation_spec",
    }
)

FORBIDDEN_ENGINE_ROOTS = frozenset(
    {
        "living_diorama.audio_composition",
        "living_diorama.audio_track",
        "living_diorama.voice",
        "living_diorama.voice_execution",
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
        "srt",
        "webvtt",
        "textwrap",
        "unicodedata",
        "re",
    }
)

NONDETERMINISM_MODULES = frozenset({"datetime", "locale", "random", "secrets", "time", "uuid"})

FORBIDDEN_IDENTIFIERS = re.compile(
    r"(?i).*("
    r"\bwav\b|\bpcm\b|waveform|\bsamples?\b|sample_rate|start_sample"
    r"|\bspeech\b|synthesize|synthesis|kokoro|misaki|\bvoice\b|narrator|\bsilence\b"
    r"|\bsrt\b|\bvtt\b|webvtt|\bttml\b|sub_?rip|cue_?file"
    r"|\bwrap\b|line_?break|\bfont\b|\bstyle\b|colour|\bcolor\b"
    r"|\bmix\b|\bgain\b|\bcodec\b|bitrate|ffmpeg|\bmux\b|\bencode\b"
    r"|\bassembly\b|\bcompose\b|composition|thumbnail|\bmp4\b|\bpublish\b"
    r"|\bllm\b|\bgpt\b|\bprompt\b|inference|rephrase|normali[sz]"
    r"|\bwpm\b|\bsyllable\b|speaking_rate|\btimecode\b|\btimestamp\b"
    r"|\bseconds?\b|millisecond|\belapsed\b|\bduration\b"
    r"|word_count|char_count|byte_count"
    r").*"
)
"""Vocabulary belonging to other layers, banned from Phase 32 definitions.

Deliberately does **not** ban ``caption``, ``caption_id``, ``caption_text``,
``cue``, ``legible``, ``window``, ``frame``, ``presentation``,
``realization``, ``accounting`` or ``uncaptioned``.
"""

READ_BANNED_KEYS = ("source_event_payload", "summary", "text")
"""``realized_text`` is NOT here -- it is governed by the exemption table
below, not by an outright ban."""

PROSE_BRANCH_MARKERS = (
    ".startswith(",
    ".endswith(",
    ".split(",
    ".rsplit(",
    ".splitlines(",
    ".lower()",
    ".upper()",
    ".casefold()",
    ".strip()",
    ".lstrip()",
    ".rstrip()",
    ".replace(",
    ".join(",
    ".find(",
    ".index(",
    ".count(",
    ".encode(",
    ".decode(",
    ".format(",
    "in text",
    "in caption_text",
    "in realized_text",
    "len(caption_text",
    "len(realized_text",
)

WHOLESALE_COPY_MARKERS = (
    "**window",
    "**record",
    "**realization",
    "**caption",
    ".items()",
    ".values()",
)

# ---- the frozen exemption table ----

REALIZED_TEXT_EXEMPTIONS = (
    (PACKAGE / "caption_planner.py", "caption_texts"),
    (PACKAGE / "caption_cross_check.py", "_require_carried_text"),
)
CAPTION_TEXT_EXEMPTIONS = (
    (PACKAGE / "caption_schema_v1.py", "_validate_caption"),
    (PACKAGE / "caption_cross_check.py", "_require_carried_text"),
)
IDENTITY_COMPARISON_EXEMPTION = (PACKAGE / "caption_cross_check.py", "_require_carried_text")

EXPECTED_REALIZED_TEXT_READS = 2
EXPECTED_CAPTION_TEXT_READS = 2
EXPECTED_IDENTITY_COMPARES = 1


def parse(path: Path) -> ast.Module:
    """Parse."""
    return ast.parse(path.read_text(encoding="utf-8"))


def imported_modules(tree: ast.Module) -> set[str]:
    """Imported modules."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def defined_names(tree: ast.Module) -> set[str]:
    """Defined names."""
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
    """Forbidden hit."""
    if FORBIDDEN_IDENTIFIERS.fullmatch(name):
        return True
    return any(FORBIDDEN_IDENTIFIERS.fullmatch(segment) for segment in name.split("_"))


def key_read_lines(tree: ast.Module, key: str) -> list[int]:
    """Key read lines."""
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


def key_reads(tree: ast.Module, key: str) -> list[str]:
    """Key reads."""
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


def function_line_range(tree: ast.Module, name: str) -> tuple[int, int] | None:
    """Function line range."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            end = node.end_lineno if node.end_lineno is not None else node.lineno
            return node.lineno, end
    return None


def _name_mentions(node: ast.expr, key: str) -> bool:
    """Return whether an expression's rendered source mentions the given local name."""
    return any(isinstance(sub, ast.Name) and sub.id == key for sub in ast.walk(node))


def caption_text_compares(tree: ast.Module) -> list[tuple[int, str]]:
    """Return (lineno, operator) for every comparison touching caption_text/realized_text."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        touches = any(
            _name_mentions(operand, "caption_text") or _name_mentions(operand, "realized_text")
            for operand in operands
        )
        if not touches:
            continue
        for op in node.ops:
            hits.append((node.lineno, type(op).__name__))
    return hits


def _code_lines(path: Path) -> list[str]:
    """Code lines."""
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
    for path in PHASE32_FILES:
        assert path.is_file(), path


def test_the_file_count_is_exact() -> None:
    """The file count is exact."""
    assert len(PHASE32_FILES) == 19


def test_the_suite_is_a_real_package() -> None:
    """The suite is a real package."""
    assert (TESTS / "__init__.py").is_file()


def test_no_test_module_imports_tests_absolutely() -> None:
    """No test module imports tests absolutely."""
    for path in PHASE32_TEST_FILES:
        if path.suffix != ".py":
            continue
        tree = parse(path)
        for module_name in imported_modules(tree):
            assert not module_name.startswith("tests."), (path, module_name)


def test_the_fixtures_are_byte_identical_to_the_phase27_suite() -> None:
    """The fixtures are byte identical to the phase27 suite."""
    phase27_fixtures = REPO_ROOT / "tests" / "presentation" / "fixtures"
    for path in PHASE32_FIXTURES:
        counterpart = phase27_fixtures / path.name
        assert counterpart.is_file()
        assert path.read_bytes() == counterpart.read_bytes()


# ---- import boundary


@pytest.mark.parametrize("path", PHASE32_MODULES)
def test_no_module_reaches_outside_its_allowed_engine_modules(path: Path) -> None:
    """No module reaches outside its allowed engine modules."""
    tree = parse(path)
    for module_name in imported_modules(tree):
        if not module_name.startswith("living_diorama"):
            continue
        assert module_name in ALLOWED_ENGINE_MODULES, (path, module_name)


@pytest.mark.parametrize("path", PHASE32_MODULES)
def test_no_module_imports_a_forbidden_engine_root(path: Path) -> None:
    """No module imports a forbidden engine root."""
    tree = parse(path)
    for module_name in imported_modules(tree):
        for forbidden in FORBIDDEN_ENGINE_ROOTS:
            assert not module_name.startswith(forbidden), (path, module_name)


def test_no_module_imports_the_paired_sibling() -> None:
    """No module imports the paired sibling."""
    for path in PHASE32_MODULES:
        tree = parse(path)
        for module_name in imported_modules(tree):
            assert not module_name.startswith("living_diorama.audio_composition"), (
                path,
                module_name,
            )


def test_no_module_imports_voice_or_audio_track_packages() -> None:
    """No module imports voice or audio track packages."""
    for path in PHASE32_MODULES:
        tree = parse(path)
        for module_name in imported_modules(tree):
            for forbidden in (
                "living_diorama.voice",
                "living_diorama.voice_execution",
                "living_diorama.audio_track",
            ):
                assert not module_name.startswith(forbidden), (path, module_name)


@pytest.mark.parametrize("path", PHASE32_MODULES)
def test_no_third_party_dependency_anywhere_in_phase32(path: Path) -> None:
    """No third party dependency anywhere in phase32."""
    tree = parse(path)
    for module_name in imported_modules(tree):
        root = module_name.split(".")[0]
        assert root not in FORBIDDEN_THIRD_PARTY_ROOTS, (path, module_name)


@pytest.mark.parametrize("path", PHASE32_MODULES)
def test_no_nondeterminism_module_anywhere_in_phase32(path: Path) -> None:
    """No nondeterminism module anywhere in phase32."""
    tree = parse(path)
    for module_name in imported_modules(tree):
        root = module_name.split(".")[0]
        assert root not in NONDETERMINISM_MODULES, (path, module_name)


@pytest.mark.parametrize("path", PHASE32_MODULES)
def test_no_module_imports_relatively(path: Path) -> None:
    """No module imports relatively."""
    tree = parse(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert (node.level or 0) == 0, path


# ---- filesystem boundary


@pytest.mark.parametrize("path", PURE_MODULES)
def test_the_planner_touches_no_filesystem(path: Path) -> None:
    """The planner touches no filesystem."""
    write_markers = ("write_text(", "write_bytes(", "open(", ".mkdir(", "shutil.")
    for line in _code_lines(path):
        for marker in write_markers:
            assert marker not in line, (path, marker, line)


def test_only_the_cli_writes_a_file() -> None:
    """Only the CLI writes a file."""
    write_markers = ("write_text(", "write_bytes(")
    for path in PURE_MODULES:
        for line in _code_lines(path):
            for marker in write_markers:
                assert marker not in line, (path, marker, line)


# ---- vocabulary guards


@pytest.mark.parametrize("path", PHASE32_MODULES)
def test_no_phase32_module_defines_another_layers_vocabulary(path: Path) -> None:
    """No phase32 module defines another layers vocabulary."""
    tree = parse(path)
    for name in defined_names(tree):
        assert not forbidden_hit(name), (path, name)


def test_the_vocabulary_guard_catches_an_offender(tmp_path: Path) -> None:
    """The vocabulary guard catches an offender."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "def build_voice_track(caption_cues: list[str]) -> None:\n    return None\n",
        encoding="utf-8",
    )
    tree = parse(offender)
    assert any(forbidden_hit(name) for name in defined_names(tree))


def test_the_vocabulary_guard_permits_this_layers_own_names() -> None:
    """The vocabulary guard permits this layers own names."""
    for name in (
        "caption",
        "caption_id",
        "caption_text",
        "cue",
        "window",
        "frame",
        "presentation",
        "realization",
        "accounting",
        "uncaptioned",
        "captions_total",
    ):
        assert not forbidden_hit(name), name


# ---- prose bans


@pytest.mark.parametrize("path", PHASE32_MODULES)
def test_no_module_reads_a_banned_prose_or_payload_key(path: Path) -> None:
    """No module reads a banned prose or payload key."""
    tree = parse(path)
    for key in READ_BANNED_KEYS:
        assert key_reads(tree, key) == [], (path, key)


def test_the_key_read_guard_catches_every_shape(tmp_path: Path) -> None:
    """The key read guard catches every shape."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "def f(d):\n"
        "    a = d['summary']\n"
        "    b = d.get('summary')\n"
        "    c = d.pop('summary')\n"
        "    return a, b, c\n",
        encoding="utf-8",
    )
    tree = parse(offender)
    assert len(key_reads(tree, "summary")) == 3


@pytest.mark.parametrize("path", PHASE32_MODULES)
def test_no_prose_branch_marker_anywhere(path: Path) -> None:
    """No prose branch marker anywhere."""
    for line in _code_lines(path):
        for marker in PROSE_BRANCH_MARKERS:
            assert marker not in line, (path, marker, line)


@pytest.mark.parametrize("path", PURE_MODULES)
def test_no_wholesale_copy_marker_anywhere(path: Path) -> None:
    """No wholesale copy marker anywhere."""
    for line in _code_lines(path):
        for marker in WHOLESALE_COPY_MARKERS:
            assert marker not in line, (path, marker, line)


# ---- the exemption tables


def test_realized_text_reads_total_exactly_two_in_the_two_exempt_functions() -> None:
    """Realized text reads total exactly two in the two exempt functions."""
    total_hits = 0
    for path in PHASE32_MODULES:
        tree = parse(path)
        lines = key_read_lines(tree, "realized_text")
        if not lines:
            continue
        exempt_files = {exempt_path for exempt_path, _ in REALIZED_TEXT_EXEMPTIONS}
        assert path in exempt_files, path
        exempt_function = next(
            name for exempt_path, name in REALIZED_TEXT_EXEMPTIONS if exempt_path == path
        )
        span = function_line_range(tree, exempt_function)
        assert span is not None
        for line in lines:
            assert span[0] <= line <= span[1], (path, line, span)
        total_hits += len(lines)
    assert total_hits == EXPECTED_REALIZED_TEXT_READS


def test_caption_text_reads_total_exactly_two_in_the_two_exempt_functions() -> None:
    """Caption text reads total exactly two in the two exempt functions."""
    total_hits = 0
    for path in PHASE32_MODULES:
        tree = parse(path)
        lines = key_read_lines(tree, "caption_text")
        if not lines:
            continue
        exempt_files = {exempt_path for exempt_path, _ in CAPTION_TEXT_EXEMPTIONS}
        assert path in exempt_files, path
        exempt_function = next(
            name for exempt_path, name in CAPTION_TEXT_EXEMPTIONS if exempt_path == path
        )
        span = function_line_range(tree, exempt_function)
        assert span is not None
        for line in lines:
            assert span[0] <= line <= span[1], (path, line, span)
        total_hits += len(lines)
    assert total_hits == EXPECTED_CAPTION_TEXT_READS


def test_identity_comparisons_total_exactly_one_eq_or_noteq() -> None:
    """Identity comparisons total exactly one eq or noteq."""
    total_hits = 0
    exempt_path, exempt_function = IDENTITY_COMPARISON_EXEMPTION
    for path in PHASE32_MODULES:
        tree = parse(path)
        hits = caption_text_compares(tree)
        if not hits:
            continue
        assert path == exempt_path, path
        span = function_line_range(tree, exempt_function)
        assert span is not None
        for line, operator in hits:
            assert span[0] <= line <= span[1], (path, line, span)
            assert operator in ("Eq", "NotEq"), (path, line, operator)
        total_hits += len(hits)
    assert total_hits == EXPECTED_IDENTITY_COMPARES


def test_the_comparison_guard_catches_a_synthetic_offender(tmp_path: Path) -> None:
    """The comparison guard catches a synthetic offender."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "def f(caption_text, realized_text):\n"
        "    if caption_text < realized_text:\n"
        "        return 1\n"
        "    if 'wall' in caption_text:\n"
        "        return 2\n"
        "    return 0\n",
        encoding="utf-8",
    )
    tree = parse(offender)
    hits = caption_text_compares(tree)
    assert len(hits) >= 1
    assert any(operator == "Lt" for _line, operator in hits)


def test_whole_document_canonical_serialization_is_not_a_key_read() -> None:
    """Whole document canonical serialization is not a key read."""
    tree = parse(PACKAGE / "caption_planner.py")
    for key in ("realized_text", "caption_text", *READ_BANNED_KEYS):
        for hit_line in key_reads(tree, key):
            assert "dumps_canonical" not in hit_line


def test_max_caption_text_bytes_is_defined_nowhere() -> None:
    """The symbol ``MAX_CAPTION_TEXT_BYTES`` is never *defined* in Phase 32 code.

    Proven by parsing the sources (``defined_names``), never by a raw
    substring scan: an attribute-docstring explaining the constant's
    deliberate absence -- ordinary convention throughout this codebase --
    legitimately mentions the name in prose without defining it.
    """
    for path in PHASE32_MODULES:
        tree = parse(path)
        assert "MAX_CAPTION_TEXT_BYTES" not in defined_names(tree), path
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "MAX_CAPTION_TEXT_BYTES":
                pytest.fail(f"{path}:{node.lineno} references MAX_CAPTION_TEXT_BYTES")


# ---- gate reuse


def test_the_locked_phase27_gate_is_imported_and_called() -> None:
    """The locked phase27 gate is imported and called."""
    path = PACKAGE / "caption_cross_check.py"
    tree = parse(path)
    assert "living_diorama.presentation.presentation_cross_check" in imported_modules(tree)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "validate_episode_presentation_plan_against_sources"
    ]
    assert len(calls) == 1


def test_no_module_reimplements_a_reused_gate() -> None:
    """No module reimplements a reused gate."""
    banned_names = {
        "validate_episode_presentation_plan_against_sources",
        "validate_narration_delivery_plan_against_sources",
        "validate_language_realization_plan_against_sources",
    }
    for path in PHASE32_MODULES:
        tree = parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                assert node.name not in banned_names, path
