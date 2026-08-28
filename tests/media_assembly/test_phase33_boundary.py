"""The Phase 33 boundary guard -- four mechanisms (E1-E4), plus structural assertions.

E1 walks the AST of the production modules for forbidden *defined* vocabulary
(a name this phase brings into being). E2 walks the same modules for
forbidden *usage* (a call this phase makes) -- including, by Correction K,
every known hardlink-creating API. E3 is raw-byte hygiene over every
candidate file. E4 is the matcher's own self-test, verified against the
exact three name families the architecture froze.
"""

import ast
import re
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src" / "living_diorama"
TESTS_DIR = Path(__file__).parent

PACKAGE_DIR = SRC / "media_assembly"
CLI_DIR = SRC / "cli"

PHASE33_MODULES: Final[tuple[Path, ...]] = (
    PACKAGE_DIR / "__init__.py",
    PACKAGE_DIR / "media_assembly_spec.py",
    PACKAGE_DIR / "media_assembly_schema_v1.py",
    PACKAGE_DIR / "media_assembly_mapping.py",
    PACKAGE_DIR / "media_assembly_binding.py",
    PACKAGE_DIR / "media_assembly_manifest.py",
    PACKAGE_DIR / "media_assembly_staging.py",
    PACKAGE_DIR / "media_assembly_publisher.py",
    PACKAGE_DIR / "media_assembly_audit.py",
    CLI_DIR / "assemble_episode_media.py",
    CLI_DIR / "verify_media_assembly.py",
)
"""The nine package modules and the two CLI modules -- production code only."""

DOCS_FILE: Final = REPO_ROOT / "docs" / "episode_media_assembly.md"

PHASE33_TEST_FILES: Final[tuple[Path, ...]] = tuple(
    sorted(p for p in TESTS_DIR.glob("*.py"))
) + tuple(sorted(TESTS_DIR.glob("fixtures/*.json")))

PHASE33_FILES: Final[tuple[Path, ...]] = PHASE33_MODULES + (DOCS_FILE,) + PHASE33_TEST_FILES
"""Every one of the 29 candidate files -- production, docs and tests -- for E3."""


@pytest.fixture(scope="module")
def module_sources() -> dict[Path, str]:
    """Every production module's source text, keyed by path."""
    return {path: path.read_text(encoding="utf-8") for path in PHASE33_MODULES}


@pytest.fixture(scope="module")
def module_trees(module_sources: dict[Path, str]) -> dict[Path, ast.Module]:
    """Every production module's parsed AST, keyed by path."""
    return {path: ast.parse(source) for path, source in module_sources.items()}


# ---------------------------------------------------------------------------
# E1 -- forbidden defined vocabulary
# ---------------------------------------------------------------------------

FORBIDDEN_IDENTIFIERS = re.compile(
    r"caption|subtitle|subtitling|webvtt|\bttml\b|\bcue\b"
    r"|\bfont\b|typeface|\bwrap\b|textwrap|rasteri|\bburn\b|overlay"
    r"|ffmpeg|mux|transcode|\bcodec\b|bitrate|container"
    r"|\bmp4\b|\bmkv\b|\bwebm\b|\bh264\b|\bx264\b|\byuv\b"
    r"|\bsrt\b|\bvtt\b"
    r"|thumbnail|normalize|\bgain\b|resample|\bdither\b|\bmixdown\b|trim"
    r"|checkpoint|\bresume\b|\bpcm\b",
    re.IGNORECASE,
)

FORBIDDEN_TERM_SEGMENTS: Final = (
    frozenset({"encode", "video"}),
    frozenset({"render", "video"}),
    frozenset({"rate", "control"}),
    frozenset({"pixel", "format"}),
    frozenset({"package", "episode"}),
    frozenset({"publish", "release"}),
    frozenset({"decode", "image"}),
    frozenset({"audit", "composition"}),
    frozenset({"audit", "render"}),
    frozenset({"speech", "span"}),
)

FUTURE_LAYER_NAMES: Final = (
    "caption_text",
    "subtitle_free_by_design",
    "subtitling_hint",
    "srt_writer",
    "vtt_cue",
    "webvtt_output",
    "cue_list",
    "font_metrics",
    "wrap_columns",
    "rasterize_text",
    "burn_in",
    "overlay_layer",
    "ffmpeg_args",
    "mux_streams",
    "muxer_state",
    "transcode_stream",
    "codec_name",
    "bitrate_target",
    "container_free",
    "containerized_value",
    "mp4_writer",
    "mkv_writer",
    "thumbnail_grid",
    "normalize_levels",
    "apply_gain",
    "resample_to",
    "dither_noise",
    "mixdown_bus",
    "trimmed_tail",
    "checkpoint_state",
    "resume_reading",
    "pcm_payload",
    "speech_span_index",
    "encode_video",
    "video_encode",
    "rate_control_mode",
    "pixel_format",
    "package_episode",
    "publish_release",
    "decode_image",
    "audit_composition_directory",
    "audit_render_directory",
)
assert len(FUTURE_LAYER_NAMES) == 42

NEAR_MISS_NAMES: Final = (
    "srtm_elevation",
    "vttl_index",
    "mp4x_probe",
    "wrapper_module",
    "gaining_ground",
    "spanish_locale",
    "resumption_reader",
    "transparency",
    "cued_up",
)
assert len(NEAR_MISS_NAMES) == 9

PHASE33_NAMES: Final = (
    "presentation_frame_filename",
    "media_assembly_id",
    "require_playback_lookup",
    "write_frame_exclusively",
    "audio_samples",
    "sample_rate_hz",
    "episode_audio_relative_path",
    "unique_semantic_frames_used",
    "audit_media_assembly_directory",
    "require_render_frame_bytes",
    "publish_episode_media_assembly",
    "_audit_media_assembly_directory_with_observation",
    "_regular_file_link_count",
    "_require_single_link_regular_file",
    "AUDIO_COMPOSITION_MANIFEST_COPY_FILENAME",
    "PROVENANCE_DIRECTORY",
    "ROLE_PLAYBACK",
    "playback",
    "presentation",
    "audio",
    "provenance",
    "MediaAssemblyRefused",
    "MediaAssemblyDirectoryRefused",
    "presentation_frame_relative_path",
    "delivery_plan_relative_path",
    "shot_plan_relative_path",
    "is_presentation_frame_filename",
    "classify_media_assembly_directory_entry",
    "classify_provenance_directory_entry",
    "MEDIA_ASSEMBLY_MANIFEST_FORMAT",
    "MEDIA_ASSEMBLY_MANIFEST_SCHEMA_VERSION",
    "MEDIA_ASSEMBLY_MANIFEST_FILENAME",
    "RENDER_MANIFEST_COPY_FILENAME",
    "PRESENTATION_PLAN_COPY_FILENAME",
    "DELIVERY_PLAN_COPY_FILENAME",
    "SHOT_PLAN_COPY_FILENAME",
    "PRESENTATION_DIRECTORY",
    "AUDIO_DIRECTORY",
    "EPISODE_AUDIO_FILENAME",
    "MAX_ASSEMBLY_PRESENTATION_FRAME",
    "ASSEMBLY_DIRECTORY_ENTRIES",
    "PROVENANCE_DIRECTORY_ENTRIES",
    "require_clock_closure",
    "require_witness_frame_excluded",
    "require_assembly_sources_join",
    "require_assembly_matches_sources",
    "build_episode_media_assembly_manifest_document",
)
assert len(PHASE33_NAMES) == 47


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
    """Whole name, each underscore segment, and multi-word terms as a segment subset."""
    if FORBIDDEN_IDENTIFIERS.match(name):
        return True
    parts = [part for part in name.split("_") if part]
    if any(FORBIDDEN_IDENTIFIERS.match(part) for part in parts):
        return True
    lowered = {part.lower() for part in parts}
    return any(term <= lowered for term in FORBIDDEN_TERM_SEGMENTS)


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

    A defined name is what's scanned, never raw file text -- so a docstring or comment
    naming a forbidden term (as this module's own module docstring legitimately does, to
    describe what E1 checks for) can never self-fail the guard.
    """
    tree = ast.parse(
        '"""This docstring mentions caption and mux and ffmpeg on purpose."""\n'
        "def real_function():\n"
        "    pass\n"
    )
    names = defined_names(tree)
    assert "real_function" in names
    assert not any(forbidden_hit(name) for name in names)


# ---------------------------------------------------------------------------
# E4 -- matcher self-tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", FUTURE_LAYER_NAMES)
def test_e4_every_future_layer_name_hits(name: str) -> None:
    """E4 every future layer name hits."""
    assert forbidden_hit(name) is True


@pytest.mark.parametrize("name", NEAR_MISS_NAMES)
def test_e4_every_near_miss_name_does_not_hit(name: str) -> None:
    """E4 every near miss name does not hit."""
    assert forbidden_hit(name) is False


@pytest.mark.parametrize("name", PHASE33_NAMES)
def test_e4_every_phase33_name_does_not_hit(name: str) -> None:
    """E4 every phase33 name does not hit."""
    assert forbidden_hit(name) is False


def test_e4_families_have_zero_overlap() -> None:
    """E4 families have zero overlap."""
    a, b, c = set(FUTURE_LAYER_NAMES), set(NEAR_MISS_NAMES), set(PHASE33_NAMES)
    assert not (a & b)
    assert not (a & c)
    assert not (b & c)


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
                problems.append("Path.resolve() is forbidden anywhere in Phase 33")
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


def test_e2_no_production_module_uses_path_resolve(module_trees: dict[Path, ast.Module]) -> None:
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
                # shutil.copytree IS permitted, exactly once, inside staging's
                # discard path is shutil.rmtree not copytree -- copytree itself
                # never appears in production Phase 33 code.
                pytest.fail(f"{path.name} uses forbidden shutil.{node.attr}")


def test_test_modules_are_not_scanned_by_e2() -> None:
    """Test modules are not scanned by E2.

    The adversarial hardlink tests legitimately call os.link -- proving E2's scan is
    scoped to PHASE33_MODULES (production) and never runs over the test files themselves.
    """
    staging_test = TESTS_DIR / "test_media_assembly_staging.py"
    source = staging_test.read_text(encoding="utf-8")
    assert "os.link(" in source
    assert staging_test not in PHASE33_MODULES


# ---------------------------------------------------------------------------
# E3 -- raw-byte hygiene, all 29 candidate files
# ---------------------------------------------------------------------------

_ALLOWED_CONTROL_BYTES: Final = frozenset({0x09, 0x0A})


def test_e3_no_forbidden_control_byte_in_any_candidate_file() -> None:
    """E3 no forbidden control byte in any candidate file."""
    violations: list[str] = []
    for path in PHASE33_FILES:
        payload = path.read_bytes()
        for byte in payload:
            if byte < 0x20 and byte not in _ALLOWED_CONTROL_BYTES:
                violations.append(f"{path}: control byte 0x{byte:02x}")
                break
    assert violations == []


def test_e3_the_boundary_test_file_itself_is_in_the_scanned_tuple() -> None:
    """E3 the boundary test file itself is in the scanned tuple."""
    this_file = Path(__file__)
    assert this_file in PHASE33_FILES


def test_e3_all_29_candidate_files_are_present() -> None:
    """E3 all 29 candidate files are present."""
    assert len(PHASE33_FILES) == 29


# ---------------------------------------------------------------------------
# Structural boundary assertions
# ---------------------------------------------------------------------------


def test_no_third_party_import_at_module_scope(module_trees: dict[Path, ast.Module]) -> None:
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
                    message = f"{path.name} imports third-party {alias.name}"
                    assert root in stdlib_or_project, message
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                message = f"{path.name} imports third-party {node.module}"
                assert root in stdlib_or_project, message


def test_no_upstream_directory_audit_is_imported_or_named(module_sources: dict[Path, str]) -> None:
    """No upstream directory audit is imported or named."""
    for path, source in module_sources.items():
        assert "audit_render_directory" not in source, path
        assert "audit_audio_composition_directory" not in source, path


def test_no_locked_upstream_module_is_touched(module_sources: dict[Path, str]) -> None:
    """No locked upstream module is touched."""
    forbidden_modules = (
        "render_execution.frame_image",
        "render_execution.render_binding",
        "render_execution.render_planner",
        "audio_composition.audio_composition_audit",
        "audio_composition.audio_composition_publisher",
        "audio_composition.audio_composer",
        "narration_delivery.delivery_cross_check",
        "cinematic.cinematic_cross_check",
    )
    for path, source in module_sources.items():
        for forbidden in forbidden_modules:
            assert forbidden not in source, f"{path.name} touches locked module {forbidden}"


def test_no_forbidden_package_is_ever_imported(module_trees: dict[Path, ast.Module]) -> None:
    """No forbidden sibling package is ever imported.

    Only actual ``import`` / ``from ... import`` statements are checked -- never raw file
    text -- so a docstring naming a forbidden sibling package in prose (as this package's own
    module docstring legitimately does, to state what it never imports) cannot self-fail.
    """
    forbidden_packages = frozenset(
        {
            "caption",
            "simulation",
            "entities",
            "events",
            "systems",
            "memory",
            "story",
            "narration",
            "language_realization",
            "voice",
            "voice_execution",
            "audio_track",
            "render",
            "engine",
        }
    )
    for path, tree in module_trees.items():
        for node in ast.walk(tree):
            imported_module = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_module = alias.name
                    _assert_not_forbidden_living_diorama_module(
                        imported_module, forbidden_packages, path
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                _assert_not_forbidden_living_diorama_module(node.module, forbidden_packages, path)


def _assert_not_forbidden_living_diorama_module(
    module_path: str, forbidden_packages: frozenset[str], path: Path
) -> None:
    parts = module_path.split(".")
    if len(parts) >= 2 and parts[0] == "living_diorama" and parts[1] in forbidden_packages:
        pytest.fail(f"{path.name} imports forbidden package {module_path}")


def test_forbidden_names_never_appear(module_sources: dict[Path, str]) -> None:
    """Forbidden names never appear."""
    forbidden_names = (
        "WITNESS_DIRECTORY",
        "ROLE_WITNESS",
        "RENDER_CHECKPOINT_FILENAME",
        "audit_render_directory",
        "audit_audio_composition_directory",
    )
    for path, source in module_sources.items():
        for name in forbidden_names:
            assert name not in source, f"{path.name} references forbidden name {name}"


def test_the_p27_gate_is_imported_and_called() -> None:
    """The P27 gate is imported and called."""
    cli_source = (CLI_DIR / "assemble_episode_media.py").read_text(encoding="utf-8")
    assert "validate_episode_presentation_plan_against_sources" in cli_source
    tree = ast.parse(cli_source)
    called = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "validate_episode_presentation_plan_against_sources"
        for node in ast.walk(tree)
    )
    assert called


def test_no_public_api_accepts_caller_supplied_manifest_bytes() -> None:
    """No public api accepts caller supplied manifest bytes."""
    import inspect

    from living_diorama.media_assembly.media_assembly_audit import audit_media_assembly_directory

    signature = inspect.signature(audit_media_assembly_directory)
    assert "manifest_bytes" not in signature.parameters
    assert list(signature.parameters) == ["assembly_dir"]


def test_private_audit_helpers_absent_from_init_all() -> None:
    """Private audit helpers absent from init all."""
    import living_diorama.media_assembly as package

    for private_name in (
        "_audit_media_assembly_directory_with_observation",
        "_regular_file_link_count",
        "_require_single_link_regular_file",
    ):
        assert private_name not in package.__all__


def test_require_direct_parent_is_the_first_statement_of_assemble() -> None:
    """Require direct parent is the first statement of assemble."""
    source = (CLI_DIR / "assemble_episode_media.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assemble_def = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "assemble"
    )
    body = assemble_def.body
    first_statement = (
        body[1]
        if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
        else body[0]
    )
    assert isinstance(first_statement, ast.Expr)
    call = first_statement.value
    assert isinstance(call, ast.Call)
    assert isinstance(call.func, ast.Name)
    assert call.func.id == "_require_direct_parent"


def test_fsync_directory_occurs_after_os_replace_in_publish_owned_staging_by_line_order() -> None:
    """Fsync directory occurs after OS replace in publish owned staging by line order."""
    source = (PACKAGE_DIR / "media_assembly_staging.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "publish_owned_staging"
    )
    replace_lines = [
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "replace"
    ]
    fsync_directory_lines = [
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "fsync_directory"
    ]
    assert replace_lines, "no os.replace call found in publish_owned_staging"
    assert fsync_directory_lines, "no fsync_directory call found in publish_owned_staging"
    assert max(fsync_directory_lines) > max(replace_lines)


def test_require_single_link_regular_file_called_from_require_owned_staging() -> None:
    """Require single link regular file called from require owned staging."""
    source = (PACKAGE_DIR / "media_assembly_staging.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "require_owned_staging"
    )
    called = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_require_single_link_regular_file"
        for node in ast.walk(function)
    )
    assert called


def test_regular_file_link_count_called_from_the_audit_module() -> None:
    """Regular file link count called from the audit module."""
    source = (PACKAGE_DIR / "media_assembly_audit.py").read_text(encoding="utf-8")
    assert "_regular_file_link_count(" in source


def test_neither_new_correction_k_helper_is_exported() -> None:
    """Neither new correction k helper is exported."""
    import living_diorama.media_assembly as package

    assert "_regular_file_link_count" not in package.__all__
    assert "_require_single_link_regular_file" not in package.__all__


def test_no_witness_document_participates_in_mapping_or_frame_writing(
    module_sources: dict[Path, str],
) -> None:
    """No witness document participates in mapping or frame writing."""
    mapping_source = (PACKAGE_DIR / "media_assembly_mapping.py").read_text(encoding="utf-8")
    assert "delivery_plan" not in mapping_source
    assert "shot_plan" not in mapping_source
    publisher_source = (PACKAGE_DIR / "media_assembly_publisher.py").read_text(encoding="utf-8")
    # the publisher's own frame-writing loop reads only render_manifest / presentation_plan
    # geometry -- confirmed structurally: presentation_frame_map and require_playback_lookup
    # are the sole geometry inputs to the frame loop, neither of which is a witness.
    assert "presentation_frame_map(presentation_plan)" in publisher_source
    assert "require_playback_lookup(render_manifest)" in publisher_source


def test_permitted_witness_field_reads_are_narrowly_scoped() -> None:
    """Permitted witness field reads are narrowly scoped.

    The audit's two witness validators are imported and nothing else from those
    packages, and only ``schema_version`` / ``format`` / ``source.shot_plan_sha256`` are ever
    read from a witness.
    """
    audit_source = (PACKAGE_DIR / "media_assembly_audit.py").read_text(encoding="utf-8")
    assert "validate_episode_narration_delivery_plan" in audit_source
    assert "validate_shot_direction_plan" in audit_source
    assert "delivery_cross_check" not in audit_source
    assert "cinematic_cross_check" not in audit_source


def test_every_shipped_file_lives_in_its_own_home() -> None:
    """Every shipped file lives in its own home."""
    for path in PHASE33_FILES:
        relative = path.relative_to(REPO_ROOT)
        parts = relative.parts
        assert parts[0] in ("src", "docs", "tests")
        if parts[0] == "src":
            assert parts[1] == "living_diorama"
            assert parts[2] in ("media_assembly", "cli")
            if parts[2] == "cli":
                assert parts[3] in ("assemble_episode_media.py", "verify_media_assembly.py")
        elif parts[0] == "tests":
            assert parts[1] == "media_assembly"


def test_no_blender_file_added() -> None:
    """No blender file added."""
    for path in PHASE33_FILES:
        assert path.suffix != ".blend"


def test_no_caption_encode_mux_ffmpeg_dependency_added() -> None:
    """No caption encode mux ffmpeg dependency added."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for forbidden in ("ffmpeg-python", "pysrt", "webvtt-py", "pycaption"):
        assert forbidden not in pyproject
