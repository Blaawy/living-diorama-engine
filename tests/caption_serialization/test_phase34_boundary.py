"""The Phase 34 boundary guard -- four mechanisms (E1-E4), plus structural assertions.

E1 walks the AST of the production modules for forbidden *defined* vocabulary
(a name this phase brings into being). E2 walks the same modules for
forbidden *usage* (a call or import this phase makes). E3 is raw-byte hygiene
over every candidate file. E4 is the matcher's own self-test, verified
against the exact name families the architecture froze.
"""

import ast
import re
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src" / "living_diorama"
TESTS_DIR = Path(__file__).parent

PACKAGE_DIR = SRC / "caption_serialization"
CLI_DIR = SRC / "cli"

PHASE34_MODULES: Final[tuple[Path, ...]] = (
    PACKAGE_DIR / "__init__.py",
    PACKAGE_DIR / "caption_serialization_audit.py",
    PACKAGE_DIR / "caption_serialization_manifest.py",
    PACKAGE_DIR / "caption_serialization_publisher.py",
    PACKAGE_DIR / "caption_serialization_schema_v1.py",
    PACKAGE_DIR / "caption_serialization_spec.py",
    PACKAGE_DIR / "caption_serialization_staging.py",
    PACKAGE_DIR / "caption_timestamp.py",
    PACKAGE_DIR / "srt_writer.py",
    PACKAGE_DIR / "vtt_writer.py",
    CLI_DIR / "serialize_episode_captions.py",
    CLI_DIR / "verify_caption_serialization.py",
)
"""The ten package modules and the two CLI modules -- production code only."""

DOCS_FILE: Final = REPO_ROOT / "docs" / "episode_caption_serialization.md"

PHASE34_TEST_FILES: Final[tuple[Path, ...]] = tuple(
    sorted(p for p in TESTS_DIR.glob("*.py"))
) + tuple(sorted(TESTS_DIR.glob("fixtures/*.json")))

PHASE34_FILES: Final[tuple[Path, ...]] = PHASE34_MODULES + (DOCS_FILE,) + PHASE34_TEST_FILES
"""Every one of the 31 candidate files -- production, docs and tests -- for E3."""


@pytest.fixture(scope="module")
def module_sources() -> dict[Path, str]:
    """Every production module's source text, keyed by path."""
    return {path: path.read_text(encoding="utf-8") for path in PHASE34_MODULES}


@pytest.fixture(scope="module")
def module_trees(module_sources: dict[Path, str]) -> dict[Path, ast.Module]:
    """Every production module's parsed AST, keyed by path."""
    return {path: ast.parse(source) for path, source in module_sources.items()}


def parse(path: Path) -> ast.Module:
    """Parse one file."""
    return ast.parse(path.read_text(encoding="utf-8"))


def imported_modules(tree: ast.Module) -> set[str]:
    """The module names a tree imports."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


# ---------------------------------------------------------------------------
# E1 -- forbidden defined vocabulary
# ---------------------------------------------------------------------------

FORBIDDEN_IDENTIFIERS = re.compile(
    r"(?i).*("
    r"ffmpeg|\bmux\b|\bencode\b|\bcodec\b|bitrate|container|\bmp4\b|\bmkv\b|"
    r"\bh264\b|\byuv\b|pixel|burn|rasteri|\bfont\b|typeface|\bwrap\b|overlay|"
    r"\bsample\b|\bpcm\b|waveform|\baudio\b"
    r").*"
)

OFFENDER_NAMES: Final = (
    "burn_in",
    "ffmpeg_args",
    "mux_streams",
    "font_metrics",
    "wrap_columns",
    "pixel_format",
)
assert len(OFFENDER_NAMES) == 6

PHASE34_NAMES: Final = (
    "serialize_srt_bytes",
    "boundary_ms",
    "format_timestamp",
    "sidecar_filename",
    "derive_cue_spans",
)
assert len(PHASE34_NAMES) == 5


def defined_names(tree: ast.Module) -> set[str]:
    """Names the file brings into being, ignoring prose and read-only access."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.isidentifier()
        ):
            names.add(node.value)
    return names


def forbidden_hit(name: str) -> bool:
    """Whole name and each underscore segment."""
    if FORBIDDEN_IDENTIFIERS.match(name):
        return True
    parts = [part for part in name.split("_") if part]
    return any(FORBIDDEN_IDENTIFIERS.match(part) for part in parts)


def test_e1_no_production_module_defines_forbidden_vocabulary(
    module_trees: dict[Path, ast.Module],
) -> None:
    """E1 no production module defines forbidden vocabulary."""
    violations: list[str] = []
    for path, tree in module_trees.items():
        for name in defined_names(tree):
            if forbidden_hit(name):
                violations.append(f"{path.name}: {name}")
    assert violations == []


def test_e1_docstrings_and_comments_are_not_scanned() -> None:
    """E1 docstrings and comments are not scanned."""
    tree = ast.parse(
        '"""This docstring mentions audio and sample and font on purpose."""\n'
        "def real_function():\n"
        "    pass\n"
    )
    names = defined_names(tree)
    assert "real_function" in names
    assert not any(forbidden_hit(name) for name in names)


# ---------------------------------------------------------------------------
# E4 -- matcher self-tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", OFFENDER_NAMES)
def test_e4_every_offender_name_hits(name: str) -> None:
    """E4 every offender name hits."""
    assert forbidden_hit(name) is True


@pytest.mark.parametrize("name", PHASE34_NAMES)
def test_e4_every_phase34_name_does_not_hit(name: str) -> None:
    """E4 every phase34 name does not hit."""
    assert forbidden_hit(name) is False


def test_e4_offenders_and_own_names_have_zero_overlap() -> None:
    """E4 the two name families have zero overlap."""
    assert not (set(OFFENDER_NAMES) & set(PHASE34_NAMES))


# ---------------------------------------------------------------------------
# E2 -- forbidden usage (production modules only)
# ---------------------------------------------------------------------------

FORBIDDEN_ATTRIBUTE_CALLS: Final = frozenset(
    {
        "os.link",
        "os.symlink",
        "os.system",
        "Path.resolve",
        "Path.hardlink_to",
        "shutil.copy",
        "shutil.copy2",
        "shutil.copytree",
    }
)

FORBIDDEN_MODULE_PREFIXES: Final = frozenset({"subprocess", "time", "datetime", "random", "uuid"})

FORBIDDEN_IMPORT_NAMES: Final = frozenset({"link", "symlink"})
FORBIDDEN_IMPORT_MODULES: Final = frozenset({"os"})
"""``from os import link`` is banned; plain ``import os`` plus ``os.replace`` stays legal."""

_HARDLINK_METHOD_NAMES: Final = frozenset({"hardlink_to", "link_to"})
_SYMLINK_METHOD_NAMES: Final = frozenset({"symlink_to"})
_RESOLVE_METHOD_NAME: Final = "resolve"


def _attribute_chain(node: ast.expr) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _scan_forbidden_usage(tree: ast.Module) -> list[str]:
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr in _HARDLINK_METHOD_NAMES:
                problems.append(f"hardlink-creating attribute access: .{node.attr}(")
            elif node.attr in _SYMLINK_METHOD_NAMES:
                problems.append(f"symlink-creating attribute access: .{node.attr}(")
            elif node.attr == _RESOLVE_METHOD_NAME:
                problems.append("Path.resolve() is forbidden anywhere in Phase 34")
            chain = _attribute_chain(node)
            if chain is not None:
                for forbidden in FORBIDDEN_ATTRIBUTE_CALLS:
                    if chain == forbidden or chain.endswith("." + forbidden.split(".")[-1]):
                        if forbidden.split(".")[0] in {"os", "shutil"} and not chain.startswith(
                            forbidden.split(".")[0]
                        ):
                            continue
                        problems.append(f"forbidden reference: {chain}")
                if chain.split(".")[0] in FORBIDDEN_MODULE_PREFIXES:
                    problems.append(f"forbidden module usage: {chain}")
        elif isinstance(node, ast.ImportFrom):
            if node.module in FORBIDDEN_IMPORT_MODULES:
                for alias in node.names:
                    if alias.name in FORBIDDEN_IMPORT_NAMES:
                        problems.append(
                            f"forbidden bare import: from {node.module} import {alias.name}"
                        )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_MODULE_PREFIXES:
                    problems.append(f"forbidden module import: {alias.name}")
    return problems


def test_e2_no_production_module_creates_a_hardlink_or_symlink(
    module_trees: dict[Path, ast.Module],
) -> None:
    """E2 no production module creates a hardlink or symlink."""
    violations: dict[str, list[str]] = {}
    for path, tree in module_trees.items():
        problems = [
            p
            for p in _scan_forbidden_usage(tree)
            if "hardlink" in p or "symlink-creating" in p or "from os import" in p
        ]
        if problems:
            violations[path.name] = problems
    assert violations == {}


def test_e2_no_production_module_uses_path_resolve(
    module_trees: dict[Path, ast.Module],
) -> None:
    """E2 no production module uses path resolve."""
    violations: dict[str, list[str]] = {}
    for path, tree in module_trees.items():
        problems = [p for p in _scan_forbidden_usage(tree) if "resolve()" in p]
        if problems:
            violations[path.name] = problems
    assert violations == {}


def test_e2_no_forbidden_shutil_copy_family_in_production(
    module_trees: dict[Path, ast.Module],
) -> None:
    """E2 no forbidden shutil copy family in production."""
    forbidden_shutil_attrs = {"copy", "copy2", "copytree"}
    for path, tree in module_trees.items():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "shutil"
                and node.attr in forbidden_shutil_attrs
            ):
                pytest.fail(f"{path.name} uses forbidden shutil.{node.attr}")


# ---------------------------------------------------------------------------
# E2 -- import walls
# ---------------------------------------------------------------------------

ALLOWED_ENGINE_MODULES = frozenset(
    {
        "living_diorama.caption",
        "living_diorama.caption.caption_schema_v1",
        "living_diorama.caption.caption_spec",
        "living_diorama.caption_serialization",
        "living_diorama.caption_serialization.caption_serialization_audit",
        "living_diorama.caption_serialization.caption_serialization_manifest",
        "living_diorama.caption_serialization.caption_serialization_publisher",
        "living_diorama.caption_serialization.caption_serialization_schema_v1",
        "living_diorama.caption_serialization.caption_serialization_spec",
        "living_diorama.caption_serialization.caption_serialization_staging",
        "living_diorama.caption_serialization.caption_timestamp",
        "living_diorama.caption_serialization.srt_writer",
        "living_diorama.caption_serialization.vtt_writer",
        "living_diorama.persistence.json_codec",
        "living_diorama.persistence.schema.state_hash",
        "living_diorama.persistence.schema.world_schema_v1",
        "living_diorama.narration.narration_schema_v1",
        "living_diorama.render_execution.render_execution_spec",
    }
)

FORBIDDEN_ENGINE_ROOTS = frozenset(
    {
        "living_diorama.media_encode",
        "living_diorama.media_assembly",
        "living_diorama.voice",
        "living_diorama.voice_execution",
        "living_diorama.audio_track",
        "living_diorama.audio_composition",
        "living_diorama.story",
        "living_diorama.presentation",
        "living_diorama.language_realization",
    }
)
"""``presentation`` and ``language_realization`` are banned on purpose: digests are
restated, never re-derived."""


@pytest.mark.parametrize("path", PHASE34_MODULES)
def test_no_module_reaches_outside_its_allowed_engine_modules(path: Path) -> None:
    """No module reaches outside its allowed engine modules."""
    tree = parse(path)
    for module_name in imported_modules(tree):
        if not module_name.startswith("living_diorama"):
            continue
        assert module_name in ALLOWED_ENGINE_MODULES, (path, module_name)


@pytest.mark.parametrize("path", PHASE34_MODULES)
def test_no_module_imports_a_forbidden_engine_root(path: Path) -> None:
    """No module imports a forbidden engine root."""
    tree = parse(path)
    for module_name in imported_modules(tree):
        for forbidden in FORBIDDEN_ENGINE_ROOTS:
            assert not module_name.startswith(forbidden), (path, module_name)


@pytest.mark.parametrize("path", PHASE34_MODULES)
def test_no_module_imports_relatively(path: Path) -> None:
    """No module imports relatively."""
    tree = parse(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert (node.level or 0) == 0, path


def test_no_third_party_import_at_module_scope(
    module_trees: dict[Path, ast.Module],
) -> None:
    """No third party import at module scope."""
    stdlib_or_project = {
        "living_diorama",
        "argparse",
        "json",
        "os",
        "shutil",
        "sys",
        "pathlib",
        "collections",
        "typing",
    }
    for path, tree in module_trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root in stdlib_or_project, f"{path.name} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                assert root in stdlib_or_project, f"{path.name} imports {node.module}"


# ---------------------------------------------------------------------------
# E3 -- raw-byte hygiene, all 31 candidate files
# ---------------------------------------------------------------------------

_ALLOWED_CONTROL_BYTES: Final = frozenset({0x09, 0x0A})


def test_e3_no_forbidden_control_byte_in_any_candidate_file() -> None:
    """E3 no forbidden control byte in any candidate file."""
    violations: list[str] = []
    for path in PHASE34_FILES:
        payload = path.read_bytes()
        for byte in payload:
            if byte < 0x20 and byte not in _ALLOWED_CONTROL_BYTES:
                violations.append(f"{path}: control byte 0x{byte:02x}")
                break
    assert violations == []


def test_e3_the_boundary_test_file_itself_is_in_the_scanned_tuple() -> None:
    """E3 the boundary test file itself is in the scanned tuple."""
    this_file = Path(__file__)
    assert this_file in PHASE34_FILES


# ---------------------------------------------------------------------------
# Structural boundary assertions
# ---------------------------------------------------------------------------


def test_every_guarded_file_exists() -> None:
    """Every guarded file exists."""
    for path in PHASE34_FILES:
        assert path.is_file(), path


def test_the_file_count_is_exact() -> None:
    """The file count is exact: 12 src + 1 doc + 15 test py + 3 fixtures = 31."""
    assert len(PHASE34_FILES) == 31


def test_the_suite_is_a_real_package() -> None:
    """The suite is a real package."""
    assert (TESTS_DIR / "__init__.py").is_file()


def test_no_test_module_imports_tests_absolutely() -> None:
    """No test module imports tests absolutely."""
    for path in PHASE34_TEST_FILES:
        if path.suffix != ".py":
            continue
        tree = parse(path)
        for module_name in imported_modules(tree):
            assert not module_name.startswith("tests."), (path, module_name)


def test_the_fixtures_are_byte_identical_to_the_phase27_suite() -> None:
    """The fixtures are byte identical to the phase27 suite."""
    phase27_fixtures = REPO_ROOT / "tests" / "presentation" / "fixtures"
    for path in sorted(TESTS_DIR.glob("fixtures/render_export_ep*.json")):
        counterpart = phase27_fixtures / path.name
        assert counterpart.is_file()
        assert path.read_bytes() == counterpart.read_bytes()


# ---------------------------------------------------------------------------
# Gate reuse: the locked Phase 32 gate, exactly once, before anything serializes
# ---------------------------------------------------------------------------


def test_the_locked_phase32_gate_is_imported_and_called_once() -> None:
    """The publisher imports and calls the locked Phase 32 gate exactly once."""
    path = PACKAGE_DIR / "caption_serialization_publisher.py"
    tree = parse(path)
    assert "living_diorama.caption" in imported_modules(tree)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "validate_episode_caption_plan_against_sources"
    ]
    assert len(calls) == 1


def test_the_phase32_gate_precedes_any_serialization_in_the_publisher() -> None:
    """The gate call precedes any sidecar serialization call, by line order."""
    path = PACKAGE_DIR / "caption_serialization_publisher.py"
    tree = parse(path)
    watched_names = {
        "validate_episode_caption_plan_against_sources",
        "serialize_srt_bytes",
        "serialize_vtt_bytes",
    }
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
    assert names[0] == "validate_episode_caption_plan_against_sources"
    assert names.index("validate_episode_caption_plan_against_sources") < names.index(
        "serialize_srt_bytes"
    )


def test_the_serialize_cli_calls_no_other_gate_before_the_publisher() -> None:
    """The serialize CLI's only gate-adjacent call is the publisher itself.

    The gate name appears in the publisher's call list, never in the CLI's own:
    a caption serialization is proven only through the one locked gate the
    publisher invokes, and no other gate precedes that call in the CLI source.
    """
    path = CLI_DIR / "serialize_episode_captions.py"
    tree = parse(path)
    watched_names = {
        "publish_episode_caption_serialization",
        "validate_episode_caption_plan_against_sources",
        "validate_episode_presentation_plan_against_sources",
        "validate_episode_language_realization_plan",
        "validate_episode_narration_delivery_plan_against_sources",
        "validate_episode_audio_track_plan_against_sources",
    }
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
    assert names == ["publish_episode_caption_serialization"]


def test_no_module_reimplements_a_reused_gate() -> None:
    """No Phase 34 module defines a second function claiming to be a reused gate."""
    banned_names = {
        "validate_episode_caption_plan_against_sources",
        "validate_episode_presentation_plan_against_sources",
        "validate_episode_language_realization_plan",
    }
    for path in PHASE34_MODULES:
        tree = parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                assert node.name not in banned_names, path
