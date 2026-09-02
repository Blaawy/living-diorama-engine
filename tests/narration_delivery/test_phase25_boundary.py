"""Phase 25 scope guard: the layer allocates presentation time and owns nothing else.

Phase 25 owns one responsibility -- binding each narration unit to one slot of
playback frames on the locked clock. Everything a reader might reasonably
expect it to grow into is somebody else's phase: caption and subtitle files;
voice, speech and audio; speaking rates and speech-duration prediction;
editing, encoding, packaging and publishing; any re-direction of the cameras
Phase 22 chose; any reach into Phase 23's frames or manifest; and any runtime
language model at all.

These are reach rules, not a claim that these files are frozen. The guard
proves what the delivery modules may *touch*: what they import, whether they
write, what vocabulary they define, and -- this phase's own sharpest rule --
that no module here reads a narration sentence -- with one reviewed exception,
the v4 profile's content-proportional partition, which counts the words of a
unit's finalized sentence in ``delivery_planner.py`` only. Each guard is
exercised against a deliberately bad synthetic file as well as the real ones,
because a guard nobody has seen fail is a guard nobody has tested.
"""

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DELIVERY = REPO_ROOT / "src" / "living_diorama" / "narration_delivery"
CLI = REPO_ROOT / "src" / "living_diorama" / "cli"
TESTS = Path(__file__).parent

PURE_MODULES = (
    DELIVERY / "__init__.py",
    DELIVERY / "delivery_cross_check.py",
    DELIVERY / "delivery_planner.py",
    DELIVERY / "delivery_schema_v1.py",
    DELIVERY / "delivery_spec.py",
)
"""Every engine module Phase 25 adds, named one by one.

A glob would quietly stop guarding a module somebody renamed, and would quietly
start guarding somebody else's.
"""

CLI_MODULES = (CLI / "build_narration_delivery_plan.py",)
"""The one command this phase adds."""

PHASE25_MODULES = (*PURE_MODULES, *CLI_MODULES)

PHASE25_TEST_FILES = (
    TESTS / "__init__.py",
    TESTS / "conftest.py",
    TESTS / "test_delivery_cli.py",
    TESTS / "test_delivery_cross_check.py",
    TESTS / "test_delivery_determinism.py",
    TESTS / "test_delivery_planner.py",
    TESTS / "test_delivery_schema.py",
    TESTS / "test_delivery_spec.py",
    TESTS / "test_phase25_boundary.py",
)
"""Every test module this phase adds, including this one.

Phase 23's guard learned to list its own suite; Phase 24's learned to list its
fixtures. Both lessons are structure here, not memory.
"""

PHASE25_FIXTURES = (
    TESTS / "fixtures" / "render_export_ep0.json",
    TESTS / "fixtures" / "render_export_ep1.json",
    TESTS / "fixtures" / "render_export_ep2.json",
)
"""Every fixture document this phase ships, named one by one.

Byte-identical copies of the exports the narration suite tests against, so the
two suites schedule and narrate the same recorded history.
"""

PHASE25_DOCS = (REPO_ROOT / "docs" / "episode_narration_delivery_plan.md",)

PHASE25_FILES = (*PHASE25_MODULES, *PHASE25_TEST_FILES, *PHASE25_FIXTURES, *PHASE25_DOCS)

ALLOWED_ENGINE_MODULES = frozenset(
    {
        "living_diorama.cinematic",
        "living_diorama.cinematic.cinematic_schema_v1",
        "living_diorama.narration",
        "living_diorama.narration.narration_schema_v1",
        "living_diorama.narration.narration_spec",
        "living_diorama.narration_delivery",
        "living_diorama.narration_delivery.delivery_cross_check",
        "living_diorama.narration_delivery.delivery_planner",
        "living_diorama.narration_delivery.delivery_schema_v1",
        "living_diorama.narration_delivery.delivery_spec",
        "living_diorama.persistence.json_codec",
        "living_diorama.persistence.schema.state_hash",
        "living_diorama.persistence.schema.world_schema_v1",
    }
)
"""The only engine modules the delivery layer may reach.

Phase 24's contracts, Phase 22's contracts, the shared codec and the shared
validation vocabulary -- and deliberately narrower than Phase 24's own list:
``living_diorama.story`` and ``living_diorama.render`` drop off it entirely,
because this layer's whole window onto the story is the narration plan. A
delivery layer that read the story plan or the export for itself would be a
second opinion about what is narrated, and a second opinion is a second
authority.
"""

FORBIDDEN_ENGINE_ROOTS = frozenset(
    {
        "cli",
        "entities",
        "events",
        "memory",
        "render",
        "render_execution",
        "simulation",
        "story",
        "systems",
    }
)
"""Engine subpackages the delivery layer must never import.

``render_execution`` is the one that matters most here: Phase 23's frames and
manifest belong to the layers that join presentation to executed pixels, and a
delivery plan that could see them would stop surviving the re-render of an
unchanged episode. ``story`` and ``render`` are new entries relative to Phase
24 -- upstream truth arrives here already narrated, and is read no other way.
"""

NETWORK_MODULES = frozenset(
    {"http", "httpx", "openai", "requests", "socket", "ssl", "urllib", "urllib3", "anthropic"}
)
"""No runtime model call, and no network of any kind, ever."""

NONDETERMINISM_MODULES = frozenset({"random", "secrets", "time", "datetime", "uuid", "os"})
"""Sources of an answer that could differ between two runs of the same inputs."""

FORBIDDEN_IDENTIFIERS = re.compile(
    r"(?i).*("
    # Phase 26+: caption and subtitle realization
    r"caption|subtitle|\bsrt\b|\bvtt\b|webvtt|cue_?list"
    # Phase 26+: voice and audio realization
    r"|audio|music|soundtrack|\bsound\b|speech|\btts\b|\bvoice\b|voiceover|voice_line"
    r"|dialogue|phoneme|mixdown|\bwav\b|waveform|spoken|utterance"
    # Phase 27+: assembly, encoding, packaging, publishing
    r"|ffmpeg|mux|encode_video|render_video|transcode|codec|bitrate|thumbnail"
    r"|publish|package_episode|edit_list|crossfade|dissolve|\bmp4\b"
    # a runtime model stays out, one layer further down
    r"|\bllm\b|\bgpt\b|prompt|embedding|completion|inference|generate_text|rephrase"
    # re-direction of Phase 22's decisions, or Phase 23's execution
    r"|choose_camera|select_camera|reframe|dolly|pan_speed|orbit|camera_path"
    r"|camera_anim|shot_rank|re_?rank|emphasis_weight|render_frame|frame_image"
    r"|render_manifest"
    # speech-rate vocabulary this layer must never own
    r"|speaking_rate|\bwpm\b|words_per|chars_per|syllable|\brate\b|\bpace\b|\btempo\b|cadence"
    # non-frame time authority
    r"|timecode|timestamp|millisecond|\bms\b|\bseconds?\b|\bclock\b|elapsed"
    r").*"
)
"""Names Phase 25 must not define.

Matched against *defined* names only -- functions, classes, arguments, assigned
names, and identifier-shaped string keys -- so that a docstring explaining what
this phase does not do cannot trip the guard. The last two bands are this
phase's own additions: a delivery layer that named a speaking rate would be a
voice-synthesis configuration phase in disguise, and one that named a
timestamp or a seconds field would be growing a second clock beside the one
Phase 17 owns.
"""

FUTURE_LAYER_NAMES = (
    "caption",
    "subtitle",
    "srt",
    "vtt",
    "audio",
    "tts",
    "voice",
    "voiceover",
    "speech",
    "spoken",
    "utterance",
    "sound",
    "waveform",
    "mixdown",
    "ffmpeg",
    "encode_video",
    "codec",
    "bitrate",
    "thumbnail",
    "crossfade",
    "dissolve",
    "mp4",
    "publish",
    "package_episode",
    "edit_list",
    "llm",
    "prompt",
    "embedding",
    "completion",
    "inference",
    "generate_text",
    "rephrase",
    "render_manifest",
    "choose_camera",
    "select_camera",
    "camera_path",
    "render_frame",
    "frame_image",
    "speaking_rate",
    "wpm",
    "words_per",
    "chars_per",
    "syllable",
    "rate",
    "pace",
    "tempo",
    "cadence",
    "timecode",
    "timestamp",
    "millisecond",
    "seconds",
    "clock",
    "elapsed",
    "duration_seconds",
    "playback_seconds",
)
"""Names belonging to other phases, each of which the guard must catch.

Wider than Phase 24's list on purpose: the guard's regex holds sixty-odd
literals, and a banned term nobody has ever seen fire is a typo away from
being no ban at all. Every band contributes entries here.
"""

PHASE25_NAMES = (
    "build_episode_narration_delivery_plan_document",
    "build_episode_narration_delivery_plan_bytes",
    "validate_episode_narration_delivery_plan",
    "validate_narration_delivery_plan_against_sources",
    "resolve_delivery_slots",
    "partition_equally",
    "playback_domain",
    "delivery_id",
    "unit_id",
    "start_frame",
    "end_frame",
    "placement",
    "shot_anchored",
    "allocated_unshown",
    "deliveries_total",
    "narration_plan_sha256",
    "shot_plan_sha256",
    "motion_time_sha256",
    "transition_frames",
    "playback_final",
    "min_slot_frames",
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
    r"""Return whether one defined name reaches another layer's vocabulary.

    The whole name is tested, and so is each underscore-separated segment of
    it. Segments matter because several terms are pinned with word boundaries
    -- ``\btts\b`` and the like, so that ``attest`` is not a hit -- and a regex
    word boundary does not fall either side of an underscore. Without the
    split, ``tts_track`` and ``mp4_writer`` would name an audio and an encoding
    responsibility while passing a guard that catches the bare words.
    """
    candidates = [name, *name.split("_")]
    return any(FORBIDDEN_IDENTIFIERS.fullmatch(candidate) for candidate in candidates)


def key_reads(tree: ast.Module, key: str) -> list[str]:
    """Return every place a module reads one key of anything.

    Two shapes are caught: a subscript ``something["key"]`` and a call
    ``something.get("key", ...)``. Docstrings and comments are naturally
    exempt, because neither shape is prose.
    """
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            index = node.slice
            if isinstance(index, ast.Constant) and index.value == key:
                hits.append(f"subscript at line {node.lineno}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("get", "__getitem__") and node.args:
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
    """A guard naming a file that is not there is guarding nothing."""
    for path in PHASE25_FILES:
        assert path.is_file(), path


def test_the_guard_covers_every_module_in_the_package() -> None:
    """A module added to the package without being guarded fails here."""
    on_disk = {path for path in DELIVERY.glob("*.py")}
    assert on_disk == set(PURE_MODULES)


def test_the_guard_covers_every_test_in_this_suite() -> None:
    """A test module added without being inventoried fails here."""
    on_disk = {path for path in TESTS.glob("*.py")}
    assert on_disk == set(PHASE25_TEST_FILES)


def test_the_guard_covers_every_fixture_this_phase_ships() -> None:
    """The fixture directory holds exactly the three declared documents.

    A glob is used only to compare against the explicit tuple above -- never to
    define the expected set itself, which is the same discipline every other
    inventory in this guard follows.
    """
    on_disk = {path for path in (TESTS / "fixtures").glob("*.json")}
    assert on_disk == set(PHASE25_FIXTURES)


def test_the_fixtures_are_byte_identical_to_the_narration_suites() -> None:
    """One recorded history, narrated and scheduled from the same bytes."""
    for path in PHASE25_FIXTURES:
        sibling = REPO_ROOT / "tests" / "narration" / "fixtures" / path.name
        assert path.read_bytes() == sibling.read_bytes(), path.name


def test_the_file_count_is_exact() -> None:
    """An inventory that grows silently is not an inventory."""
    assert len(PHASE25_FILES) == 19


def test_the_suite_is_a_real_package() -> None:
    """The Phase 23 CI lesson, asserted rather than remembered.

    Without this file the suite collects under ``python -m pytest`` and fails
    under the bare ``pytest`` console script CI invokes.
    """
    assert (TESTS / "__init__.py").is_file()


def test_no_test_module_imports_the_suite_by_absolute_path() -> None:
    """An absolute import of this suite resolves only under ``python -m pytest``.

    Checked over the parsed import statements rather than the file text, so a
    docstring or comment naming the broken form is prose about the rule and not
    a violation of it.
    """
    for path in PHASE25_TEST_FILES:
        for module in imported_modules(parse(path)):
            assert not module.startswith("tests"), f"{path.name} imports {module}"


# ---- import reach


def test_no_phase25_module_reaches_outside_its_allowed_engine_modules() -> None:
    """The reach is an exact allow-list, not an absence of known offenders."""
    for path in PHASE25_MODULES:
        for module in imported_modules(parse(path)):
            if not module.startswith("living_diorama"):
                continue
            assert module in ALLOWED_ENGINE_MODULES, f"{path.name} imports {module}"


def test_no_phase25_module_imports_a_forbidden_engine_root() -> None:
    """Simulation, memory, story, render and render execution are out of reach."""
    for path in PHASE25_MODULES:
        for module in imported_modules(parse(path)):
            parts = module.split(".")
            if len(parts) > 1 and parts[0] == "living_diorama":
                assert parts[1] not in FORBIDDEN_ENGINE_ROOTS or module in ALLOWED_ENGINE_MODULES, (
                    f"{path.name} imports {module}"
                )


def test_the_delivery_layer_never_imports_render_execution() -> None:
    """The single most consequential boundary in this phase, asserted on its own.

    Phase 23's frames and manifest are execution proof; a delivery plan that
    could see them would stop surviving a re-render of an unchanged episode.
    """
    for path in PHASE25_MODULES:
        source = path.read_text(encoding="utf-8")
        cleaned = source.replace("``living_diorama.render_execution``", "")
        assert "living_diorama.render_execution" not in cleaned, path.name


def test_the_delivery_layer_never_imports_live_memory_or_the_story() -> None:
    """Upstream truth arrives already narrated, and is read no other way."""
    for path in PHASE25_MODULES:
        for module in imported_modules(parse(path)):
            assert not module.startswith("living_diorama.memory"), path.name
            assert not module.startswith("living_diorama.story"), path.name


def test_memory_and_the_story_are_absent_from_the_source_text_too() -> None:
    """The raw-text backstop Phase 24 gave its own riskiest boundary.

    An AST walk cannot see ``importlib.import_module("living_diorama.story")``;
    a text scan can. Double-backtick-quoted docstring mentions are stripped
    first, so prose about the rule is not a violation of it.
    """
    for path in PHASE25_MODULES:
        source = path.read_text(encoding="utf-8")
        for banned in ("living_diorama.memory", "living_diorama.story"):
            cleaned = source.replace(f"``{banned}``", "")
            assert banned not in cleaned, path.name


def test_no_module_imports_relatively() -> None:
    """Every import is fully qualified, so every import guard actually sees it.

    The AST guards read absolute imports only; a relative ``from ..x import y``
    would be invisible to all of them. Nothing here needs one, so none is
    allowed.
    """
    for path in PHASE25_MODULES:
        for node in ast.walk(parse(path)):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"{path.name} imports relatively"


def test_no_phase25_module_reaches_the_network() -> None:
    """No runtime model call, and no network of any kind, ever."""
    for path in PHASE25_MODULES:
        assert not imported_roots(parse(path)) & NETWORK_MODULES, path.name


def test_no_phase25_module_imports_a_source_of_nondeterminism() -> None:
    """No clock, no randomness, no uuid, no environment."""
    for path in PHASE25_MODULES:
        offenders = imported_roots(parse(path)) & NONDETERMINISM_MODULES
        assert not offenders, f"{path.name} imports {sorted(offenders)}"


def test_no_phase25_module_imports_blender() -> None:
    """This phase is pure, and touches no visual runtime at all."""
    for path in PHASE25_MODULES:
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


def test_no_phase25_module_defines_another_layers_vocabulary() -> None:
    """Captions, audio, rates, timestamps, encoding, a model: none start here."""
    for path in PHASE25_MODULES:
        for name in defined_names(parse(path)):
            assert not forbidden_hit(name), f"{path.name} defines {name!r}"


@pytest.mark.parametrize("name", FUTURE_LAYER_NAMES)
def test_the_guard_catches_every_term_it_claims_to(name: str) -> None:
    """Each forbidden term, asserted on its own rather than trusted in bulk."""
    assert forbidden_hit(name)
    assert forbidden_hit(f"{name}_track")
    assert forbidden_hit(f"build_{name}")


@pytest.mark.parametrize("name", PHASE25_NAMES)
def test_the_scope_guard_tolerates_the_words_this_phase_owns(name: str) -> None:
    """The guard must not fire on the vocabulary this layer legitimately defines."""
    assert not forbidden_hit(name)


def test_the_vocabulary_guard_ignores_prose_in_a_docstring() -> None:
    """This layer's docstrings must be free to say what it does not own."""
    module = ast.parse(
        '"""This layer emits no audio, no captions, and knows no speaking rate."""\n'
        "def schedule_unit(unit_id: str) -> str:\n"
        '    """It never publishes a subtitle, a timestamp or a waveform."""\n'
        "    return unit_id\n"
    )
    for name in defined_names(module):
        assert not forbidden_hit(name)


def test_the_vocabulary_guard_catches_an_offender(tmp_path: Path) -> None:
    """A guard nobody has seen fail is a guard nobody has tested."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "def estimate_speaking_rate(wpm: int) -> float:\n    return wpm / 60\n",
        encoding="utf-8",
    )
    hits = {name for name in defined_names(parse(offender)) if forbidden_hit(name)}
    assert hits


def test_the_vocabulary_guard_catches_an_identifier_shaped_string_key(tmp_path: Path) -> None:
    """A document key is a definition too."""
    offender = tmp_path / "offender.py"
    offender.write_text('SLOT = {"duration_seconds": 1.5}\n', encoding="utf-8")
    assert any(forbidden_hit(name) for name in defined_names(parse(offender)))


def test_the_import_guard_catches_an_offender(tmp_path: Path) -> None:
    """Reaching for the manifest is the temptation this layer must not have."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "from living_diorama.render_execution import render_manifest\n", encoding="utf-8"
    )
    modules = imported_modules(parse(offender))
    assert not modules <= ALLOWED_ENGINE_MODULES


def test_the_network_guard_catches_an_offender(tmp_path: Path) -> None:
    """Importing a model client is caught by name."""
    offender = tmp_path / "offender.py"
    offender.write_text("import anthropic\n", encoding="utf-8")
    assert imported_roots(parse(offender)) & NETWORK_MODULES


def test_the_nondeterminism_guard_catches_an_offender(tmp_path: Path) -> None:
    """A source of an answer that could differ between runs is caught by name."""
    offender = tmp_path / "offender.py"
    offender.write_text("import random\nimport datetime\n", encoding="utf-8")
    assert imported_roots(parse(offender)) & NONDETERMINISM_MODULES


def test_the_write_guard_catches_an_offender(tmp_path: Path) -> None:
    """A pure module that wrote a file would be caught by its own marker."""
    offender = tmp_path / "offender.py"
    offender.write_text("def save(path):\n    path.write_bytes(b'x')\n", encoding="utf-8")
    source = offender.read_text(encoding="utf-8")
    assert any(marker in source for marker in WRITE_MARKERS)


# ---- prose is not even carried


def test_no_module_reads_a_narration_sentence() -> None:
    """The rule Phase 24 held -- carried, never branched on -- goes further here.

    A delivery slot is structure, so this layer does not read the ``text``
    field: not to carry it, not to compare it, and never under the v1 profile,
    which is the default and the historical output. One reviewed exception: the
    v4 profile's content-proportional partition counts the words of each unit's
    finalized sentence in ``delivery_planner.py`` only -- the sole prose read
    in Phase 25, mandated by the Director's content-proportional rule. Every
    other module and every other key stays banned.
    """
    for path in PHASE25_MODULES:
        if path.name == "delivery_planner.py":
            continue
        assert key_reads(parse(path), "text") == [], path.name


def test_the_text_guard_catches_a_subscript_offender(tmp_path: Path) -> None:
    """Reading ``unit["text"]`` is caught."""
    offender = tmp_path / "offender.py"
    offender.write_text('def words(unit):\n    return len(unit["text"])\n', encoding="utf-8")
    assert key_reads(parse(offender), "text")


def test_the_text_guard_catches_a_get_offender(tmp_path: Path) -> None:
    """And so is ``unit.get("text")``."""
    offender = tmp_path / "offender.py"
    offender.write_text('def words(unit):\n    return unit.get("text", "")\n', encoding="utf-8")
    assert key_reads(parse(offender), "text")


def test_no_module_branches_on_wording_shape() -> None:
    """No module branches on wording shape -- except the one reviewed v4 exception.

    ``delivery_planner.py`` hosts the sole prose read in Phase 25: the v4
    profile's content-proportional partition counts the words of each unit's
    finalized sentence with ``str.split()``. That one marker in that one module
    is exempted; every other module and every other marker stays banned.
    """
    for path in PHASE25_MODULES:
        for line in _code_lines(path):
            for marker in (".startswith(", ".split(", ".lower()", ".strip()", "in text"):
                if marker == ".split(" and path.name == "delivery_planner.py":
                    continue
                assert marker not in line, f"{path.name}: {line.strip()}"


def test_no_pure_module_copies_a_record_wholesale() -> None:
    """A unit is read field by field, never spread or iterated into an output.

    ``{**unit}``, ``.items()`` and ``.values()`` would carry every field of a
    narration unit -- its sentence included -- without the ``text`` key ever
    appearing in the source, which is exactly the shape the AST text-guard
    cannot see. Explicit named keys are the only way anything crosses.
    """
    for path in PURE_MODULES:
        source = path.read_text(encoding="utf-8")
        for marker in ("**unit", "**record", ".items()", ".values()"):
            assert marker not in source, f"{path.name} contains {marker}"


# ---- this phase changes nothing upstream


def test_phase25_adds_no_blender_file() -> None:
    """The scope claim, asserted over the file inventory itself."""
    for path in PHASE25_FILES:
        assert "visual" not in path.parts, path


def test_phase25_touches_no_render_execution_module() -> None:
    """Phase 23's frames and manifest stay exactly where they are."""
    for path in PHASE25_FILES:
        assert "render_execution" not in path.parts, path


def test_phase25_touches_no_narration_module() -> None:
    """Phase 24 is consumed, never edited: every file lives in this phase's own homes."""
    for path in PHASE25_FILES:
        assert "narration" not in path.parts or "narration_delivery" in path.parts, path
