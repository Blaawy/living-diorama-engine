"""The Phase 35 boundary guard -- mechanisms E1-E4, plus structural assertions.

E1 walks the AST of the production modules for forbidden *defined* vocabulary
(a name this phase must never bring into being: burn-in, rasterization, font
layout, styling, overlays, caption serialization writers -- caption
serialization is Phase 34's, display is nobody's -- and the engine-external
execution stacks torch/kokoro/blender). E2 walks the same modules for
forbidden *usage* (subprocess/time/datetime/random/uuid, hardlink-creating and
symlink-creating APIs, ``Path.resolve``, the shutil copy family) and gives the
executor its own laws: subprocess deferred into exactly one function body, no
network import anywhere, and a frozen top-level import set. E3 is raw-byte
hygiene over every candidate file. E4 is the matcher's own self-test.

The executor (``media/ffmpeg/scripts/encode_episode.py``) may not exist yet in
a given clone -- it is authored by the execution task -- so every test that
reads its source skips with a clear message when it is absent; every tuple
still LISTs it, and the 31-file inventory is the merged-tree contract.
"""

import ast
import re
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src" / "living_diorama"
TESTS_DIR = Path(__file__).parent

PACKAGE_DIR = SRC / "media_encode"
CLI_DIR = SRC / "cli"
EXECUTOR_DIR = REPO_ROOT / "media" / "ffmpeg" / "scripts"

PHASE35_MODULES: Final[tuple[Path, ...]] = (
    PACKAGE_DIR / "__init__.py",
    PACKAGE_DIR / "media_encode_audit.py",
    PACKAGE_DIR / "media_encode_command.py",
    PACKAGE_DIR / "media_encode_manifest.py",
    PACKAGE_DIR / "media_encode_probe.py",
    PACKAGE_DIR / "media_encode_publisher.py",
    PACKAGE_DIR / "media_encode_schema_v1.py",
    PACKAGE_DIR / "media_encode_spec.py",
    PACKAGE_DIR / "media_encode_staging.py",
    PACKAGE_DIR / "media_encode_version.py",
    CLI_DIR / "verify_media_encode.py",
    EXECUTOR_DIR / "encode_episode.py",
)
"""The ten package modules, the verifying CLI, and the one tool-bearing executor.

The executor is folded in exactly as Phase 29 folds in its kokoro executor: it
is listed, scanned and counted here, even though it lives outside
``src/living_diorama``.
"""

PACKAGE_MODULES: Final = PHASE35_MODULES[:10]
"""The ten canonical package modules -- the E2 dimension and prefix laws' scope."""

EXECUTOR_MODULES: Final = (PHASE35_MODULES[-1],)
"""The one tool-touching subprocess site of the whole repository's media side."""

DOCS_FILE: Final = REPO_ROOT / "docs" / "episode_media_encode.md"

PHASE35_TEST_FILES: Final[tuple[Path, ...]] = tuple(
    sorted(p for p in TESTS_DIR.glob("*.py"))
) + tuple(sorted(TESTS_DIR.glob("fixtures/*.json")))

PHASE35_FILES: Final[tuple[Path, ...]] = PHASE35_MODULES + (DOCS_FILE,) + PHASE35_TEST_FILES
"""Every one of the 31 candidate files -- production, docs and tests -- for E3."""


@pytest.fixture(scope="module")
def module_sources() -> dict[Path, str]:
    """Every EXISTING production module's source text, keyed by path.

    The executor may not exist in this clone yet; absent files are simply not
    scanned here, and the executor-specific tests skip on absence explicitly.
    """
    return {path: path.read_text(encoding="utf-8") for path in PHASE35_MODULES if path.exists()}


@pytest.fixture(scope="module")
def module_trees(module_sources: dict[Path, str]) -> dict[Path, ast.Module]:
    """Every existing production module's parsed AST, keyed by path."""
    return {path: ast.parse(source) for path, source in module_sources.items()}


# ---------------------------------------------------------------------------
# E1 -- forbidden defined vocabulary
# ---------------------------------------------------------------------------

FORBIDDEN_IDENTIFIERS = re.compile(
    r"(?i).*(burn|rasteri|\bfont\b|typeface|wrap_|\bstyle\b|overlay"
    r"|srt_writer|vtt_cue|webvtt_output|caption_text"
    r"|torch|kokoro|blender|\bbpy\b).*"
)
"""Caption serialization is Phase 34-owned; display is nobody's. None of the
vocabulary this phase may define may even name a burn-in, a rasterizer, a font,
a style, an overlay or a caption writer, and no engine-external execution stack
(torch/kokoro/blender/bpy) may be named either."""


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
    """Whole name and each underscore segment, against the E1 vocabulary."""
    if FORBIDDEN_IDENTIFIERS.match(name):
        return True
    return any(FORBIDDEN_IDENTIFIERS.match(part) for part in name.split("_") if part)


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
    """E1 docstrings and comments are not scanned.

    A defined name is what is scanned, never raw file text -- so a docstring
    naming a forbidden term (as several Phase 35 docstrings legitimately do, to
    state what the phase never does) can never self-fail the guard.
    """
    tree = ast.parse(
        '"""This docstring mentions burn-in, font metrics and rasterize on purpose."""\n'
        "def build_decode_command():\n"
        "    pass\n"
    )
    names = defined_names(tree)
    assert "build_decode_command" in names
    assert not any(forbidden_hit(name) for name in names)


# ---------------------------------------------------------------------------
# E4 -- matcher self-tests
# ---------------------------------------------------------------------------

E4_OFFENDERS: Final = ("burn_in", "srt_writer", "font_metrics", "rasterize_text")
E4_OWN_NAMES: Final = (
    "build_decode_command",
    "media_encode_id",
    "normalize_probe_document",
    "require_stream_facts",
    "preflight_wav_bytes",
)


@pytest.mark.parametrize("name", E4_OFFENDERS)
def test_e4_every_offender_name_hits(name: str) -> None:
    """E4 every offender name hits."""
    assert forbidden_hit(name) is True


@pytest.mark.parametrize("name", E4_OWN_NAMES)
def test_e4_every_phase35_name_does_not_hit(name: str) -> None:
    """E4 every phase35 name does not hit."""
    assert forbidden_hit(name) is False


def test_e4_families_have_zero_overlap() -> None:
    """E4 families have zero overlap."""
    assert not (set(E4_OFFENDERS) & set(E4_OWN_NAMES))


# ---------------------------------------------------------------------------
# E2 -- forbidden usage (production modules only)
# ---------------------------------------------------------------------------

FORBIDDEN_ATTRIBUTE_CALLS: Final = frozenset(
    {
        "os.link",
        "os.symlink",
        "Path.hardlink_to",
        "Path.link_to",
        "Path.symlink_to",
        "shutil.copy",
        "shutil.copyfile",
        "shutil.copy2",
        "shutil.copyfileobj",
        "shutil.copytree",
        "Path.resolve",
        "os.system",
    }
)

FORBIDDEN_MODULE_PREFIXES: Final = frozenset({"subprocess", "time", "datetime", "random", "uuid"})
"""The 11 package+CLI modules may never import or use any of these."""

FORBIDDEN_IMPORT_NAMES: Final = frozenset({"link", "symlink"})
FORBIDDEN_IMPORT_MODULES: Final = frozenset({"os"})

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
                problems.append("Path.resolve() is forbidden anywhere in Phase 35")
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
    forbidden_shutil_attrs = {"copy", "copyfile", "copy2", "copyfileobj"}
    for path, tree in module_trees.items():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "shutil"
                and node.attr in forbidden_shutil_attrs
            ):
                pytest.fail(f"{path.name} uses forbidden shutil.{node.attr}")


def test_e2_no_forbidden_module_prefix_in_any_package_or_cli_module(
    module_trees: dict[Path, ast.Module],
) -> None:
    """E2 the 11 package+CLI modules never import or use a forbidden prefix."""
    for path, tree in module_trees.items():
        problems = [p for p in _scan_forbidden_usage(tree) if "forbidden module" in p]
        if path.name == "encode_episode.py":
            # the executor's ONE lawful deferred subprocess site: _default_runner's
            # in-body import and its single subprocess.run call, nothing more.
            assert sorted(problems) == [
                "forbidden module import: subprocess",
                "forbidden module usage: subprocess.run",
            ], f"{path.name}: {problems}"
        else:
            assert problems == [], f"{path.name}: {problems}"


def test_e2_test_modules_are_not_scanned() -> None:
    """E2 test modules are not scanned.

    The determinism suite legitimately imports ``subprocess`` -- proving the
    scan is scoped to PHASE35_MODULES (production) and never runs over the
    test files themselves.
    """
    determinism_test = TESTS_DIR / "test_media_encode_determinism.py"
    source = determinism_test.read_text(encoding="utf-8")
    assert "import subprocess" in source
    assert determinism_test not in PHASE35_MODULES


# ---------------------------------------------------------------------------
# Executor laws (the one tool-touching site; skipped while absent)
# ---------------------------------------------------------------------------


def _executor_tree() -> ast.Module:
    executor = EXECUTOR_MODULES[0]
    if not executor.exists():
        pytest.skip("media/ffmpeg/scripts/encode_episode.py is authored by the execution task")
    return ast.parse(executor.read_text(encoding="utf-8"))


def test_executor_defers_subprocess_import_into_a_function_body() -> None:
    """The executor imports ``subprocess`` exactly once, inside a function body.

    No top-level ``import subprocess``: the deferred-into-function law keeps the
    module import side-effect-free, and the one subprocess import is found
    inside a ``FunctionDef`` and exists there exactly once.
    """
    tree = _executor_tree()
    for node in tree.body:
        if isinstance(node, ast.Import):
            assert not any(alias.name.split(".")[0] == "subprocess" for alias in node.names), (
                "subprocess is imported at executor top level"
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] != "subprocess", (
                "subprocess is imported at executor top level"
            )
    in_function_sites: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Import)
                and any(alias.name.split(".")[0] == "subprocess" for alias in inner.names)
                or (
                    isinstance(inner, ast.ImportFrom)
                    and inner.module
                    and inner.module.split(".")[0] == "subprocess"
                )
            ):
                in_function_sites.append(inner.lineno)
    assert len(in_function_sites) == 1, (
        f"expected exactly one in-function subprocess import, got {in_function_sites}"
    )


def test_executor_imports_no_network_root_anywhere() -> None:
    """No import of any network root anywhere in the executor."""
    tree = _executor_tree()
    network_roots = {"urllib", "socket", "http", "ftplib", "requests", "pip"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots = [node.module.split(".")[0]]
        else:
            continue
        for root in roots:
            assert root not in network_roots, (node.lineno, root)


def test_executor_top_level_imports_are_limited() -> None:
    """The executor's top-level imports stay inside the frozen stdlib set.

    Beyond that set only ``living_diorama.*`` may appear at module scope;
    everything heavier is deferred into function bodies.
    """
    tree = _executor_tree()
    allowed_roots = {"argparse", "json", "os", "sys", "shutil", "collections", "pathlib", "typing"}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root in allowed_roots, (node.lineno, alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            assert root in allowed_roots or root == "living_diorama", (node.lineno, node.module)


def test_executor_audits_both_upstream_directories_before_staging_begins() -> None:
    """Both upstream audits' first call sites precede the first staging call site."""
    tree = _executor_tree()
    watched = {
        "audit_media_assembly_directory",
        "audit_caption_serialization_directory",
        "begin_media_encode_staging",
    }
    calls_in_order: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in watched:
            calls_in_order.append((node.lineno, node.func.id))
        elif isinstance(node.func, ast.Attribute) and node.func.attr in watched:
            calls_in_order.append((node.lineno, node.func.attr))
    calls_in_order.sort()
    names = [name for _line, name in calls_in_order]
    first_staging = names.index("begin_media_encode_staging")
    assert names.index("audit_media_assembly_directory") < first_staging
    assert names.index("audit_caption_serialization_directory") < first_staging


def test_executor_builds_commands_through_the_builders_and_never_inlines_argv() -> None:
    """The executor builds argv only through the frozen builders, never inline."""
    tree = _executor_tree()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called.add(node.func.id)
    assert "build_media_encode_command" in called
    assert "build_decode_command" in called
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            for element in node.elts:
                if (
                    isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                    and "ffmpeg" in element.value
                ):
                    pytest.fail(
                        f"inline ffmpeg argv literal at line {node.lineno}; commands must "
                        "come from the builders"
                    )


# ---------------------------------------------------------------------------
# Import walls
# ---------------------------------------------------------------------------

ALLOWED_ENGINE_MODULES = frozenset(
    {
        "living_diorama.caption_serialization",
        "living_diorama.caption_serialization.caption_serialization_schema_v1",
        "living_diorama.caption_serialization.caption_serialization_spec",
        "living_diorama.caption_serialization.caption_serialization_audit",
        "living_diorama.media_assembly",
        "living_diorama.media_assembly.media_assembly_audit",
        "living_diorama.media_assembly.media_assembly_schema_v1",
        "living_diorama.media_assembly.media_assembly_spec",
        "living_diorama.media_encode",
        "living_diorama.media_encode.media_encode_audit",
        "living_diorama.media_encode.media_encode_command",
        "living_diorama.media_encode.media_encode_manifest",
        "living_diorama.media_encode.media_encode_probe",
        "living_diorama.media_encode.media_encode_publisher",
        "living_diorama.media_encode.media_encode_schema_v1",
        "living_diorama.media_encode.media_encode_spec",
        "living_diorama.media_encode.media_encode_staging",
        "living_diorama.media_encode.media_encode_version",
        "living_diorama.narration.narration_schema_v1",
        "living_diorama.persistence.json_codec",
        "living_diorama.persistence.schema.state_hash",
        "living_diorama.persistence.schema.world_schema_v1",
        "living_diorama.render_execution.render_execution_schema_v1",
        "living_diorama.render_execution.render_execution_spec",
    }
)
"""Exactly the engine modules Phase 35 may import -- frozen from the actual
imports of the 11+1 modules: the caption serialization spec/schema pair, the
media assembly schema (both consumed manifests' locked contracts), the
persistence trio, the narration mode/plan vocabulary, the render profile
authority, and this package's own modules. ``render_execution.render_execution_spec``
is the one render-family module admitted; ``living_diorama.render`` is not."""

FORBIDDEN_ENGINE_ROOTS = frozenset(
    {
        "living_diorama.caption",
        "living_diorama.voice",
        "living_diorama.voice_execution",
        "living_diorama.audio_track",
        "living_diorama.audio_composition",
        "living_diorama.story",
        "living_diorama.presentation",
        "living_diorama.language_realization",
        "living_diorama.render",
    }
)


def imported_modules(tree: ast.Module) -> list[str]:
    """Every module name a tree imports, absolutely."""
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


@pytest.mark.parametrize("path", PHASE35_MODULES)
def test_no_module_reaches_outside_its_allowed_engine_modules(path: Path) -> None:
    """No canonical-package, CLI or executor module imports outside the frozen set."""
    if not path.exists():
        pytest.skip(f"{path} is not present in this clone yet")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for module_name in imported_modules(tree):
        if not module_name.startswith("living_diorama"):
            continue
        assert module_name in ALLOWED_ENGINE_MODULES, (path, module_name)


@pytest.mark.parametrize("path", PHASE35_MODULES)
def test_no_module_imports_a_forbidden_engine_root(path: Path) -> None:
    """No Phase 35 module imports a forbidden engine root.

    Exact-segment matching: ``living_diorama.render`` is refused while
    ``living_diorama.render_execution`` stays allowed, and
    ``living_diorama.caption`` is refused while
    ``living_diorama.caption_serialization`` stays allowed.
    """
    if not path.exists():
        pytest.skip(f"{path} is not present in this clone yet")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for module_name in imported_modules(tree):
        for forbidden in FORBIDDEN_ENGINE_ROOTS:
            assert not (module_name == forbidden or module_name.startswith(forbidden + ".")), (
                path,
                module_name,
            )


# ---------------------------------------------------------------------------
# NO-DIMENSION-LITERAL law
# ---------------------------------------------------------------------------


def test_no_dimension_literal_in_any_package_module(
    module_trees: dict[Path, ast.Module],
) -> None:
    """No integer literal 1280 or 720 appears in any package module's AST.

    The render dimensions live in the Phase 23 render profile document; this
    phase derives them through the digest chain and never restates them as
    literals. 720/1280 in tests is fine -- only the package files are scanned,
    and they genuinely contain neither.
    """
    for path, tree in module_trees.items():
        if path not in PACKAGE_MODULES:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, int):
                assert node.value not in (1280, 720), (
                    f"{path.name} carries the dimension literal {node.value} at line {node.lineno}"
                )


# ---------------------------------------------------------------------------
# E3 -- raw-byte hygiene, all 31 candidate files
# ---------------------------------------------------------------------------

_ALLOWED_CONTROL_BYTES: Final = frozenset({0x09, 0x0A})


def test_e3_no_forbidden_control_byte_in_any_candidate_file() -> None:
    """E3 no forbidden control byte in any candidate file."""
    missing = [str(p) for p in PHASE35_FILES if not p.exists()]
    if missing:
        pytest.skip(f"candidate files not yet present in this clone: {missing}")
    violations: list[str] = []
    for path in PHASE35_FILES:
        payload = path.read_bytes()
        for byte in payload:
            if byte < 0x20 and byte not in _ALLOWED_CONTROL_BYTES:
                violations.append(f"{path}: control byte 0x{byte:02x}")
                break
    assert violations == []


def test_e3_the_boundary_test_file_itself_is_in_the_scanned_tuple() -> None:
    """E3 the boundary test file itself is in the scanned tuple."""
    assert Path(__file__) in PHASE35_FILES


def test_e3_all_31_candidate_files_are_present() -> None:
    """E3 all 31 candidate files are present.

    12 scanned modules (the executor included) + 1 doc + 15 test py + 3
    fixtures.
    """
    assert len(PHASE35_FILES) == 31


# ---------------------------------------------------------------------------
# Structural boundary assertions
# ---------------------------------------------------------------------------


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
        "re",
        "struct",
        "math",
    }
    for path, tree in module_trees.items():
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    message = f"{path.name} imports third-party {alias.name}"
                    assert root in stdlib_or_project, message
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                message = f"{path.name} imports third-party {node.module}"
                assert root in stdlib_or_project, message


def test_every_shipped_file_lives_in_its_own_home() -> None:
    """Every shipped file lives in its own home."""
    for path in PHASE35_FILES:
        relative = path.relative_to(REPO_ROOT)
        parts = relative.parts
        assert parts[0] in ("src", "docs", "tests", "media")
        if parts[0] == "src":
            assert parts[1] == "living_diorama"
            assert parts[2] in ("media_encode", "cli")
            if parts[2] == "cli":
                assert parts[3] == "verify_media_encode.py"
        elif parts[0] == "tests":
            assert parts[1] == "media_encode"
        elif parts[0] == "media":
            assert parts[1] == "ffmpeg"
            assert parts[2] == "scripts"
            assert parts[3] == "encode_episode.py"


def test_no_blender_file_added() -> None:
    """No blender file added."""
    for path in PHASE35_FILES:
        assert path.suffix != ".blend"


def test_fixtures_are_byte_identical_to_the_phase_presentation_suite() -> None:
    """Every Phase 35 fixture is byte-identical to its Phase 23 suite counterpart.

    Fixtures are shared, never re-authored: the same render exports the whole
    chain descends from must be the same bytes everywhere.
    """
    phase23_fixtures = REPO_ROOT / "tests" / "presentation" / "fixtures"
    for path in sorted(TESTS_DIR.glob("fixtures/*.json")):
        counterpart = phase23_fixtures / path.name
        assert counterpart.is_file(), f"no Phase 23 counterpart for {path.name}"
        assert path.read_bytes() == counterpart.read_bytes()
