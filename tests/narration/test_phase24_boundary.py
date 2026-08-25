"""Phase 24 scope guard: the layer restates selected truth and owns nothing else.

Phase 24 owns one responsibility -- saying, in one deterministic sentence each,
what the story layer emphasised and whether the direction framed it. Everything
a reader might reasonably expect it to grow into is somebody else's phase:
caption and subtitle files; voice, speech and audio; editing, encoding,
packaging and publishing; any re-direction of the cameras Phase 22 chose; and
any runtime language model at all.

These are reach rules, not a claim that these files are frozen. The guard proves
what the narration modules may *touch*: what they import, whether they write,
and what vocabulary they define. Each guard is exercised against a deliberately
bad synthetic file as well as the real ones, because a guard nobody has seen
fail is a guard nobody has tested.
"""

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NARRATION = REPO_ROOT / "src" / "living_diorama" / "narration"
CLI = REPO_ROOT / "src" / "living_diorama" / "cli"
TESTS = Path(__file__).parent

PURE_MODULES = (
    NARRATION / "__init__.py",
    NARRATION / "narration_cross_check.py",
    NARRATION / "narration_facts.py",
    NARRATION / "narration_planner.py",
    NARRATION / "narration_schema_v1.py",
    NARRATION / "narration_spec.py",
)
"""Every engine module Phase 24 adds, named one by one.

A glob would quietly stop guarding a module somebody renamed, and would quietly
start guarding somebody else's.
"""

CLI_MODULES = (CLI / "build_narration_plan.py",)
"""The one command this phase adds."""

PHASE24_MODULES = (*PURE_MODULES, *CLI_MODULES)

PHASE24_TEST_FILES = (
    TESTS / "__init__.py",
    TESTS / "conftest.py",
    TESTS / "test_narration_cli.py",
    TESTS / "test_narration_cross_check.py",
    TESTS / "test_narration_determinism.py",
    TESTS / "test_narration_facts.py",
    TESTS / "test_narration_planner.py",
    TESTS / "test_narration_schema.py",
    TESTS / "test_narration_spec.py",
    TESTS / "test_phase24_boundary.py",
)
"""Every test module this phase adds, including this one.

Phase 23's guard learned to list its own suite: a scope guard that does not
guard the files asserting the scope is guarding half a phase.
"""

PHASE24_FIXTURES = (
    TESTS / "fixtures" / "render_export_ep0.json",
    TESTS / "fixtures" / "render_export_ep1.json",
    TESTS / "fixtures" / "render_export_ep2.json",
)
"""Every fixture document this phase ships, named one by one.

These are real Render Export V1 documents the suite reads, not code -- but they
are still repository files the candidate ships, and an inventory that only
counts ``.py`` files is not an inventory of the candidate.
"""

PHASE24_DOCS = (REPO_ROOT / "docs" / "episode_narration_plan.md",)

PHASE24_FILES = (*PHASE24_MODULES, *PHASE24_TEST_FILES, *PHASE24_FIXTURES, *PHASE24_DOCS)

ALLOWED_ENGINE_MODULES = frozenset(
    {
        "living_diorama.cinematic",
        "living_diorama.narration",
        "living_diorama.narration.narration_cross_check",
        "living_diorama.narration.narration_facts",
        "living_diorama.narration.narration_planner",
        "living_diorama.narration.narration_schema_v1",
        "living_diorama.narration.narration_spec",
        "living_diorama.persistence.json_codec",
        "living_diorama.persistence.schema.state_hash",
        "living_diorama.persistence.schema.world_schema_v1",
        "living_diorama.render.render_schema_v1",
        "living_diorama.story",
        "living_diorama.story.story_facts",
    }
)
"""The only engine modules the narration layer may reach.

Phase 21's and Phase 22's contracts, the render contract the story plan was
derived from, and the shared validation vocabulary. A narration plan is derived
from finished documents; nothing here needs the live world.
"""

FORBIDDEN_ENGINE_ROOTS = frozenset(
    {"entities", "events", "memory", "render_execution", "simulation", "systems", "cli"}
)
"""Engine subpackages the narration layer must never import.

``memory`` is on the list deliberately, and it is the one that matters most
here. This layer carries memory's own sentences, which makes reaching for the
live model tempting and wrong: it reads facts *as exported*, through the render
contract the story plan bound by digest, exactly as the story layer does.
Importing ``living_diorama.memory`` would give narration a second opinion about
what durable memory is, and a second opinion is a second authority.

``render_execution`` is here because Phase 23's frames and manifest belong to the
later realization layer, not to authoring.
"""

NETWORK_MODULES = frozenset(
    {"http", "httpx", "openai", "requests", "socket", "ssl", "urllib", "urllib3", "anthropic"}
)
"""No runtime model call, and no network of any kind, ever."""

NONDETERMINISM_MODULES = frozenset({"random", "secrets", "time", "datetime", "uuid", "os"})
"""Sources of an answer that could differ between two runs of the same inputs."""

FORBIDDEN_IDENTIFIERS = re.compile(
    r"(?i).*("
    # Phase 25+: caption and subtitle realization
    r"caption|subtitle|\bsrt\b|\bvtt\b|webvtt|cue_?list|timecode"
    # Phase 26+: voice and audio realization
    r"|audio|music|soundtrack|speech|\btts\b|voiceover|voice_line|dialogue|phoneme"
    r"|mixdown|\bwav\b|waveform_render"
    # Phase 27+: assembly, encoding, packaging, publishing
    r"|ffmpeg|mux|encode_video|render_video|transcode|codec|bitrate|thumbnail"
    r"|publish|package_episode|edit_list|crossfade|dissolve|\bmp4\b"
    # a runtime model is the whole point of the boundary
    r"|\bllm\b|\bgpt\b|prompt|embedding|completion|inference|generate_text|rephrase"
    # re-direction of Phase 22's decisions, or Phase 23's execution
    r"|choose_camera|select_camera|reframe|dolly|pan_speed|orbit|camera_path"
    r"|camera_anim|shot_rank|re_?rank|emphasis_weight|render_frame|frame_image"
    # citizen-level simulation
    r"|citizen|biograph|relationship|commute|workplace|household"
    r").*"
)
"""Names Phase 24 must not define.

Matched against *defined* names only -- functions, classes, arguments, assigned
names, and identifier-shaped string keys -- so that a docstring explaining what
this phase does not do cannot trip the guard. That exemption is load-bearing
here: this layer's whole job is to talk about what it does not own.
"""

FUTURE_LAYER_NAMES = (
    "caption",
    "subtitle",
    "srt",
    "vtt",
    "timecode",
    "audio",
    "tts",
    "voiceover",
    "speech",
    "mixdown",
    "ffmpeg",
    "encode_video",
    "mp4",
    "publish",
    "package_episode",
    "edit_list",
    "llm",
    "prompt",
    "embedding",
    "rephrase",
)
"""Names belonging to phases after this one, each of which the guard must catch."""

PHASE24_NAMES = (
    "build_episode_narration_plan_document",
    "validate_episode_narration_plan",
    "validate_narration_plan_against_sources",
    "fact_summary_for_evidence",
    "render_narration_text",
    "forbidden_wording_hit",
    "text_source_for_kind",
    "unshown_reason",
    "visibility",
    "beat_id",
    "shot_id",
    "start_frame",
    "end_frame",
    "text_source",
    "story_plan_sha256",
    "subject_ids",
)
"""This phase's own vocabulary, which the guard must tolerate."""

WRITE_MARKERS = (
    "open(",
    ".write_text",
    ".write_bytes",
    ".mkdir",
    ".unlink",
    "shutil.",
)
"""Substrings that would mean a pure module touched the filesystem.

Only the CLI may read or write a file. A planner that could open a path could
also be handed one by a document.
"""


def parse(path: Path) -> ast.Module:
    """Parse one guarded file into a syntax tree."""
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imported_modules(tree: ast.Module) -> set[str]:
    """Return every module a file imports by name."""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            modules.add(node.module)
    return modules


def imported_roots(tree: ast.Module) -> set[str]:
    """Return the top-level package of every import."""
    return {module.split(".")[0] for module in imported_modules(tree)}


def defined_names(tree: ast.Module) -> set[str]:
    """Every name this module brings into being.

    Identifier-shaped string constants are included because a document key is a
    definition too: a module that never wrote ``audio_track = ...`` but emitted
    ``{"audio_track": ...}`` would own the field just the same.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                arguments = node.args
                for argument in (
                    *arguments.posonlyargs,
                    *arguments.args,
                    *arguments.kwonlyargs,
                ):
                    names.add(argument.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.isidentifier():
                names.add(node.value)
    return names


def forbidden_hit(name: str) -> bool:
    r"""Return whether one defined name reaches a future layer's vocabulary.

    The whole name is tested, and so is each underscore-separated segment of it.
    Segments matter because several terms are pinned with word boundaries --
    ``\btts\b`` and the like, so that ``attest`` is not a hit -- and a regex word
    boundary does not fall either side of an underscore. Without the split,
    ``tts_track`` and ``mp4_writer`` would name an audio and an encoding
    responsibility while passing a guard that catches the bare words.
    """
    candidates = [name, *name.split("_")]
    return any(FORBIDDEN_IDENTIFIERS.fullmatch(candidate) for candidate in candidates)


# ---- the file list


def test_every_guarded_file_exists() -> None:
    """A guard naming a file that is not there is guarding nothing."""
    for path in PHASE24_FILES:
        assert path.is_file(), path


def test_the_guard_covers_every_module_in_the_package() -> None:
    """A module added to the package without being guarded fails here."""
    on_disk = {path for path in NARRATION.glob("*.py")}
    assert on_disk == set(PURE_MODULES)


def test_the_guard_covers_every_test_in_this_suite() -> None:
    """A test module added without being inventoried fails here."""
    on_disk = {path for path in TESTS.glob("*.py")}
    assert on_disk == set(PHASE24_TEST_FILES)


def test_the_guard_covers_every_fixture_this_phase_ships() -> None:
    """The fixture directory holds exactly the three declared documents.

    A glob is used only to compare against the explicit tuple above -- never to
    define the expected set itself, which is the same discipline every other
    inventory in this guard follows.
    """
    on_disk = {path for path in (TESTS / "fixtures").glob("*.json")}
    assert on_disk == set(PHASE24_FIXTURES)


def test_the_file_count_is_exact() -> None:
    """An inventory that grows silently is not an inventory."""
    assert len(PHASE24_FILES) == 21


def test_the_suite_is_a_real_package() -> None:
    """The Phase 23 CI lesson, asserted rather than remembered.

    Without this file the suite collects under ``python -m pytest`` and fails
    under the bare ``pytest`` console script CI invokes.
    """
    assert (TESTS / "__init__.py").is_file()


def test_no_test_module_imports_the_suite_by_absolute_path() -> None:
    """An absolute import of this suite resolves only under ``python -m pytest``.

    Checked over the parsed import statements rather than the file text, so a
    docstring or comment naming the broken form -- as several here deliberately
    do -- is prose about the rule and not a violation of it.
    """
    for path in PHASE24_TEST_FILES:
        for module in imported_modules(parse(path)):
            assert not module.startswith("tests"), f"{path.name} imports {module}"


# ---- import reach


def test_no_phase24_module_reaches_outside_its_allowed_engine_modules() -> None:
    """The reach is an exact allow-list, not an absence of known offenders."""
    for path in PHASE24_MODULES:
        for module in imported_modules(parse(path)):
            if not module.startswith("living_diorama"):
                continue
            assert module in ALLOWED_ENGINE_MODULES, f"{path.name} imports {module}"


def test_no_phase24_module_imports_a_forbidden_engine_root() -> None:
    """Live simulation, events, memory and render execution are all out of reach."""
    for path in PHASE24_MODULES:
        for module in imported_modules(parse(path)):
            parts = module.split(".")
            if len(parts) > 1 and parts[0] == "living_diorama":
                assert parts[1] not in FORBIDDEN_ENGINE_ROOTS or module in ALLOWED_ENGINE_MODULES, (
                    f"{path.name} imports {module}"
                )


def test_the_narration_layer_never_imports_live_memory() -> None:
    """The single most tempting boundary in this phase, asserted on its own."""
    for path in PHASE24_MODULES:
        source = path.read_text(encoding="utf-8")
        assert "living_diorama.memory" not in source.replace("``living_diorama.memory``", ""), (
            path.name
        )


def test_no_phase24_module_reaches_the_network() -> None:
    """No runtime model call, and no network of any kind, ever."""
    for path in PHASE24_MODULES:
        assert not imported_roots(parse(path)) & NETWORK_MODULES, path.name


def test_no_phase24_module_imports_a_source_of_nondeterminism() -> None:
    """No clock, no randomness, no uuid, no environment."""
    for path in PHASE24_MODULES:
        offenders = imported_roots(parse(path)) & NONDETERMINISM_MODULES
        assert not offenders, f"{path.name} imports {sorted(offenders)}"


def test_no_phase24_module_imports_blender() -> None:
    """This phase is pure, and touches no visual runtime at all."""
    for path in PHASE24_MODULES:
        roots = imported_roots(parse(path))
        assert "bpy" not in roots and "mathutils" not in roots, path.name


# ---- writing


def test_no_pure_module_touches_the_filesystem() -> None:
    """Only the CLI reads or writes a file."""
    for path in PURE_MODULES:
        source = path.read_text(encoding="utf-8")
        for marker in WRITE_MARKERS:
            assert marker not in source, f"{path.name} contains {marker}"


def test_the_cli_is_the_only_module_importing_pathlib() -> None:
    """A planner that could open a path could also be handed one by a document."""
    for path in PURE_MODULES:
        assert "pathlib" not in imported_roots(parse(path)), path.name


# ---- vocabulary


def test_no_phase24_module_defines_a_future_layers_vocabulary() -> None:
    """Captions, audio, encoding, packaging, publishing, a model: none start here."""
    for path in PHASE24_MODULES:
        for name in defined_names(parse(path)):
            assert not forbidden_hit(name), f"{path.name} defines {name!r}"


@pytest.mark.parametrize("name", FUTURE_LAYER_NAMES)
def test_the_guard_catches_every_term_it_claims_to(name: str) -> None:
    """Each forbidden term, asserted on its own rather than trusted in bulk."""
    assert forbidden_hit(name)
    assert forbidden_hit(f"{name}_track")
    assert forbidden_hit(f"build_{name}")


@pytest.mark.parametrize("name", PHASE24_NAMES)
def test_the_scope_guard_tolerates_the_words_this_phase_owns(name: str) -> None:
    """The guard must not fire on the vocabulary this layer legitimately defines."""
    assert not forbidden_hit(name)


def test_the_vocabulary_guard_ignores_prose_in_a_docstring() -> None:
    """This layer's docstrings must be free to say what it does not own."""
    module = ast.parse(
        '"""This layer emits no audio, no captions, no mp4, and calls no llm."""\n'
        "def restate_beat(beat_id: str) -> str:\n"
        '    """It never publishes a subtitle or a voiceover."""\n'
        "    return beat_id\n"
    )
    for name in defined_names(module):
        assert not forbidden_hit(name)


def test_the_vocabulary_guard_catches_an_offender(tmp_path: Path) -> None:
    """A guard nobody has seen fail is a guard nobody has tested."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "def build_caption_track(subtitle_cues: list[str]) -> None:\n    return None\n",
        encoding="utf-8",
    )
    hits = {name for name in defined_names(parse(offender)) if forbidden_hit(name)}
    assert hits


def test_the_vocabulary_guard_catches_an_identifier_shaped_string_key(tmp_path: Path) -> None:
    """A document key is a definition too."""
    offender = tmp_path / "offender.py"
    offender.write_text('UNIT = {"audio_track": None}\n', encoding="utf-8")
    assert any(forbidden_hit(name) for name in defined_names(parse(offender)))


def test_the_import_guard_catches_an_offender(tmp_path: Path) -> None:
    """Reaching for live memory is the temptation this layer must not have."""
    offender = tmp_path / "offender.py"
    offender.write_text("from living_diorama.memory import WorldMemory\n", encoding="utf-8")
    modules = imported_modules(parse(offender))
    assert not modules <= ALLOWED_ENGINE_MODULES


def test_the_network_guard_catches_an_offender(tmp_path: Path) -> None:
    """Importing a model client is caught by name."""
    offender = tmp_path / "offender.py"
    offender.write_text("import anthropic\n", encoding="utf-8")
    assert imported_roots(parse(offender)) & NETWORK_MODULES


def test_the_nondeterminism_guard_catches_an_offender(tmp_path: Path) -> None:
    """So is anything that could answer differently on a second run."""
    offender = tmp_path / "offender.py"
    offender.write_text("import random\nimport datetime\n", encoding="utf-8")
    assert imported_roots(parse(offender)) & NONDETERMINISM_MODULES


def test_the_write_guard_catches_an_offender(tmp_path: Path) -> None:
    """A pure module that wrote a file would be caught by its own marker."""
    offender = tmp_path / "offender.py"
    offender.write_text("def save(path):\n    path.write_bytes(b'x')\n", encoding="utf-8")
    source = offender.read_text(encoding="utf-8")
    assert any(marker in source for marker in WRITE_MARKERS)


# ---- prose may be carried, never branched on


def test_no_module_branches_on_a_narration_sentence() -> None:
    """The rule Phase 21 set, held one layer further down.

    Wording may be carried, compared for equality, and refused as a whole. What
    it may never do is steer a decision: no module here inspects a substring of
    a sentence, splits one, or lowercases one to see what it says. The single
    exception is the ban-list search in ``narration_spec``, which is a refusal
    gate rather than a branch, and which is confined to that module.
    """
    for path in PHASE24_MODULES:
        if path.name == "narration_spec.py":
            continue
        source = path.read_text(encoding="utf-8")
        for banned in (".startswith(", ".split(", ".lower()", ".strip()", "in text"):
            assert banned not in source, f"{path.name} inspects wording: {banned}"


def test_only_the_declared_dereference_site_reads_a_summary() -> None:
    """Exactly one module reaches for a fact's prose, and it carries it whole."""
    readers = [
        path.name
        for path in PHASE24_MODULES
        if '"summary"' in path.read_text(encoding="utf-8")
        or "['summary']" in path.read_text(encoding="utf-8")
    ]
    assert readers == ["narration_facts.py"]


# ---- this phase changes nothing upstream


def test_phase24_adds_no_blender_file() -> None:
    """The scope claim, asserted over the file inventory itself."""
    for path in PHASE24_FILES:
        assert "visual" not in path.parts, path


def test_phase24_touches_no_render_execution_module() -> None:
    """Phase 23's frames and manifest belong to the later realization layer."""
    for path in PHASE24_FILES:
        assert "render_execution" not in path.parts, path
