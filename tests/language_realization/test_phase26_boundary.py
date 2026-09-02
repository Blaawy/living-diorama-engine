"""Phase 26 stays inside its boundary, proven by parsing the sources.

Every guard is exercised against a deliberately bad synthetic file, because a
guard nobody has seen fail is a guard nobody has tested.
"""

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "src" / "living_diorama" / "language_realization"
CLI = REPO_ROOT / "src" / "living_diorama" / "cli"
TESTS = Path(__file__).parent

PURE_MODULES = (
    PACKAGE / "__init__.py",
    PACKAGE / "realization_atoms.py",
    PACKAGE / "realization_cross_check.py",
    PACKAGE / "realization_guidance.py",
    PACKAGE / "realization_planner.py",
    PACKAGE / "realization_schema_v1.py",
    PACKAGE / "realization_spec.py",
)
"""Every engine module Phase 26 adds, named one by one.

A glob would quietly stop guarding a module somebody renamed, and would
quietly start guarding somebody else's.
"""

CLI_MODULES = (CLI / "build_language_realization_plan.py",)
PHASE26_MODULES = (*PURE_MODULES, *CLI_MODULES)

PHASE26_TEST_FILES = (
    TESTS / "__init__.py",
    TESTS / "conftest.py",
    TESTS / "test_phase26_boundary.py",
    TESTS / "test_realization_atoms.py",
    TESTS / "test_realization_cli.py",
    TESTS / "test_realization_cross_check.py",
    TESTS / "test_realization_determinism.py",
    TESTS / "test_realization_planner.py",
    TESTS / "test_realization_schema.py",
    TESTS / "test_realization_spec.py",
    TESTS / "test_realization_wording_v2.py",
)

PHASE26_FIXTURES = (
    TESTS / "fixtures" / "render_export_ep0.json",
    TESTS / "fixtures" / "render_export_ep1.json",
    TESTS / "fixtures" / "render_export_ep2.json",
)

PHASE26_DOCS = (REPO_ROOT / "docs" / "episode_language_realization_plan.md",)

PHASE26_FILES = (*PHASE26_MODULES, *PHASE26_TEST_FILES, *PHASE26_FIXTURES, *PHASE26_DOCS)

ALLOWED_ENGINE_MODULES = frozenset(
    {
        "living_diorama.language_realization",
        "living_diorama.language_realization.realization_atoms",
        "living_diorama.language_realization.realization_cross_check",
        "living_diorama.language_realization.realization_guidance",
        "living_diorama.language_realization.realization_planner",
        "living_diorama.language_realization.realization_schema_v1",
        "living_diorama.language_realization.realization_spec",
        "living_diorama.narration",
        "living_diorama.narration.narration_facts",
        "living_diorama.narration.narration_schema_v1",
        "living_diorama.narration.narration_spec",
        "living_diorama.persistence.json_codec",
        "living_diorama.persistence.schema.state_hash",
        "living_diorama.persistence.schema.world_schema_v1",
        "living_diorama.render.render_schema_v1",
        "living_diorama.story",
    }
)
"""Exactly the engine modules Phase 26 may import.

Narration, story and render are the three finished contracts this layer
proves against; the codec and shared validators are the repository's one
canonical vocabulary. Nothing else -- deliberately no cinematic, whose shot
plan is not an input here, and no delivery, whose timing this layer must not
know.
"""

FORBIDDEN_ENGINE_ROOTS = frozenset(
    {
        "living_diorama.cinematic",
        "living_diorama.engine",
        "living_diorama.entities",
        "living_diorama.events",
        "living_diorama.memory",
        "living_diorama.narration_delivery",
        "living_diorama.render_execution",
        "living_diorama.simulation",
        "living_diorama.systems",
    }
)

NETWORK_MODULES = frozenset(
    {"anthropic", "http", "httpx", "openai", "requests", "socket", "ssl", "urllib", "urllib3"}
)

NONDETERMINISM_MODULES = frozenset(
    {"datetime", "locale", "os", "platform", "random", "secrets", "time", "uuid"}
)

FORBIDDEN_IDENTIFIERS = re.compile(
    r"(?i).*("
    # captions and subtitles stay a sibling layer's vocabulary
    r"caption|subtitle|\bsrt\b|\bvtt\b|webvtt|cue_?list"
    # voice and audio realization stays downstream
    r"|audio|music|soundtrack|\bsound\b|speech|\btts\b|\bvoice\b|voiceover|voice_line"
    r"|dialogue|phoneme|mixdown|\bwav\b|waveform|spoken|utterance"
    # assembly, encoding, packaging, publishing stay further downstream
    r"|ffmpeg|mux|encode_video|render_video|transcode|codec|bitrate|thumbnail"
    r"|publish|package_episode|edit_list|crossfade|dissolve|\bmp4\b"
    # a runtime model is the whole point of the boundary
    r"|\bllm\b|\bgpt\b|prompt|embedding|completion|inference|generate_text|rephrase"
    # re-direction of Phase 22's decisions, or Phase 23's execution
    r"|choose_camera|select_camera|reframe|dolly|pan_speed|orbit|camera_path"
    r"|camera_anim|shot_rank|re_?rank|emphasis_weight|render_frame|frame_image"
    r"|render_manifest"
    # delivery timing this layer must never know
    r"|narration_delivery|\bdelivery\b|placement|allocated|\bslot\b|\bwindow\b"
    # non-frame, non-tick time and rate vocabulary
    r"|speaking_rate|\bwpm\b|words_per|chars_per|syllable|\bpace\b|\btempo\b|cadence"
    r"|timecode|timestamp|millisecond|\bms\b|\bseconds?\b|\bclock\b|elapsed|duration"
    r"|\bsamples?\b|sample_rate"
    # citizen-level simulation
    r"|citizen|biograph|relationship|commute|workplace|household"
    r").*"
)
"""Vocabulary belonging to other layers, banned from Phase 26 definitions.

The bare word ``rate`` is deliberately not banned on its own -- no Phase 26
name carries it -- while every speech-rate compound is. ``tick`` is the
engine's own time unit and stays legal everywhere.
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
    "waveform",
    "mixdown",
    "ffmpeg",
    "encode_video",
    "codec",
    "bitrate",
    "thumbnail",
    "mp4",
    "publish",
    "package_episode",
    "edit_list",
    "llm",
    "prompt",
    "embedding",
    "inference",
    "rephrase",
    "render_manifest",
    "delivery",
    "placement",
    "slot",
    "speaking_rate",
    "wpm",
    "syllable",
    "timecode",
    "timestamp",
    "seconds",
    "clock",
    "elapsed",
    "duration",
    "samples",
    "sample_rate",
)

PHASE26_NAMES = (
    "realization_id",
    "realized_text",
    "district_label",
    "law_label",
    "boundary_phrase",
    "wall_phrase",
    "resolve_event",
    "resolve_law",
    "resolve_boundary",
    "realized_text_for_beat",
    "fact_for_beat",
    "language_realization",
    "tick",
    "built_tick",
    "restored_tick",
)

WRITE_MARKERS = ("write_text(", "write_bytes(", "open(", ".mkdir(", "shutil.")

PROSE_BRANCH_MARKERS = (".startswith(", ".split(", ".lower()", ".strip()", "in text")

WHOLESALE_COPY_MARKERS = ("**unit", "**beat", "**record", "**fact", ".items()", ".values()")

READ_BANNED_KEYS = ("source_event_payload", "summary", "text")
"""Keys no Phase 26 module may read, by subscript or ``.get``.

``text`` is the narration plan's sentence, ``summary`` the memory fact's, and
``source_event_payload`` the event internals no presentation contract proves.
The plan's own field is named ``realized_text`` precisely so this ban can be
total.
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
    """Return every name a module defines, plus identifier-shaped constants.

    Function and class names, argument names, assignment targets, and string
    constants that look like identifiers -- so a banned concept smuggled in as
    a JSON key still counts as a definition. Docstrings are naturally exempt:
    prose with spaces is not identifier-shaped.
    """
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
    r"""Return whether one defined name reaches another layer's vocabulary.

    The whole name is tested, and so is each underscore-separated segment,
    because ``\btts\b`` does not match ``tts_track`` -- a regex word boundary
    does not fall on either side of an underscore.
    """
    if FORBIDDEN_IDENTIFIERS.fullmatch(name):
        return True
    return any(FORBIDDEN_IDENTIFIERS.fullmatch(segment) for segment in name.split("_"))


def key_reads(tree: ast.Module, key: str) -> list[str]:
    """Return every place a module reads one key of anything.

    Three shapes are caught: a subscript ``something["key"]``, a call
    ``something.get("key", ...)``, and a call ``something.pop("key", ...)``.
    A variable-indirected subscript is beyond static reach; the behavioral
    structure-wins tests are the backstop for that avenue.
    """
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


def test_every_guarded_file_exists() -> None:
    """A guard naming a file that is not there is guarding nothing."""
    for path in PHASE26_FILES:
        assert path.is_file(), path


def test_the_guard_covers_every_module_in_the_package() -> None:
    """A module added to the package without being guarded fails here."""
    on_disk = set(PACKAGE.glob("*.py"))
    assert on_disk == set(PURE_MODULES)


def test_the_guard_covers_every_test_in_this_suite() -> None:
    """A test module added without being inventoried fails here."""
    on_disk = set(TESTS.glob("*.py"))
    assert on_disk == set(PHASE26_TEST_FILES)


def test_the_guard_covers_every_fixture_this_phase_ships() -> None:
    """The fixture directory holds exactly the three declared documents."""
    on_disk = set((TESTS / "fixtures").glob("*.json"))
    assert on_disk == set(PHASE26_FIXTURES)


def test_the_file_count_is_exact() -> None:
    """An inventory that grows silently is not an inventory."""
    assert len(PHASE26_FILES) == 23


def test_the_fixtures_are_byte_identical_to_the_narration_suite() -> None:
    """Copied fixtures must be exactly the canonical bytes, never edited."""
    for path in PHASE26_FIXTURES:
        original = REPO_ROOT / "tests" / "narration" / "fixtures" / path.name
        assert path.read_bytes() == original.read_bytes(), path.name


def test_the_suite_is_a_real_package() -> None:
    """Without __init__.py the suite fails under the bare pytest CI invokes."""
    assert (TESTS / "__init__.py").is_file()


def test_no_phase26_module_reaches_outside_its_allowed_engine_modules() -> None:
    """The layer imports only its three contracts and the shared vocabulary."""
    for path in PHASE26_MODULES:
        for name in imported_modules(parse(path)):
            if name.startswith("living_diorama"):
                assert name in ALLOWED_ENGINE_MODULES, f"{path.name} imports {name}"


def test_no_phase26_module_imports_a_forbidden_engine_root() -> None:
    """Delivery, cinematic, execution and memory stay unreachable."""
    for path in PHASE26_MODULES:
        for name in imported_modules(parse(path)):
            for root in FORBIDDEN_ENGINE_ROOTS:
                assert not name.startswith(root), f"{path.name} imports {name}"


def test_phase26_touches_no_delivery_module() -> None:
    """Timing is Phase 25's and Phase 27's; wording must not know it."""
    for path in PHASE26_MODULES:
        source = path.read_text(encoding="utf-8")
        assert "narration_delivery" not in source, path.name


def test_phase26_touches_no_cinematic_module() -> None:
    """The shot plan is deliberately not an input to this layer."""
    for path in PHASE26_MODULES:
        for name in imported_modules(parse(path)):
            assert not name.startswith("living_diorama.cinematic"), path.name


def test_no_phase26_module_reaches_the_network() -> None:
    """No socket, no client, no service."""
    for path in PHASE26_MODULES:
        for name in imported_modules(parse(path)):
            root = name.split(".", 1)[0]
            assert root not in NETWORK_MODULES, f"{path.name} imports {name}"


def test_no_phase26_module_imports_a_source_of_nondeterminism() -> None:
    """No clock, no randomness, no environment, no locale."""
    for path in PHASE26_MODULES:
        for name in imported_modules(parse(path)):
            root = name.split(".", 1)[0]
            assert root not in NONDETERMINISM_MODULES, f"{path.name} imports {name}"


def test_no_pure_module_touches_the_filesystem() -> None:
    """Only the CLI reads or writes; the engine modules never do."""
    for path in PURE_MODULES:
        for line in _code_lines(path):
            for marker in WRITE_MARKERS:
                assert marker not in line, f"{path.name}: {line.strip()}"


def test_no_phase26_module_defines_another_layers_vocabulary() -> None:
    """No definition reaches for captions, voice, assembly, timing or a model."""
    for path in PHASE26_MODULES:
        for name in defined_names(parse(path)):
            assert not forbidden_hit(name), f"{path.name} defines {name}"


def test_no_module_reads_an_upstream_prose_or_payload_key() -> None:
    """No module reads ``text``, ``summary`` or ``source_event_payload`` at all.

    The empty allow-list is the point: Phase 24 carries prose and proves it,
    Phase 26 derives wording from structure and therefore never opens the
    upstream prose fields, not even to compare.
    """
    for path in PHASE26_MODULES:
        tree = parse(path)
        for key in READ_BANNED_KEYS:
            assert key_reads(tree, key) == [], f"{path.name} reads {key!r}"


def test_no_module_branches_on_wording_shape() -> None:
    """Wording may be rendered and equality-compared, never inspected.

    No module splits a sentence, lowercases one, or asks what one starts
    with; the schema's character bans use membership on a named sentence
    variable, which is a refusal gate, not a branch on meaning.
    """
    for path in PHASE26_MODULES:
        for line in _code_lines(path):
            for marker in PROSE_BRANCH_MARKERS:
                assert marker not in line, f"{path.name}: {line.strip()}"


def test_no_module_copies_a_record_wholesale() -> None:
    """Only targeted reads are permitted, so a spread cannot smuggle a field."""
    for path in PHASE26_MODULES:
        for line in _code_lines(path):
            for marker in WHOLESALE_COPY_MARKERS:
                assert marker not in line, f"{path.name}: {line.strip()}"


def test_no_test_module_imports_tests_absolutely() -> None:
    """Shared helpers come from the package-relative conftest only."""
    for path in PHASE26_TEST_FILES:
        if path.suffix != ".py":
            continue
        for name in imported_modules(parse(path)):
            assert not name.startswith("tests"), f"{path.name} imports {name}"


@pytest.mark.parametrize("name", FUTURE_LAYER_NAMES)
def test_every_future_layer_name_fires(name: str) -> None:
    """Each banned token is caught bare, suffixed, and prefixed."""
    assert forbidden_hit(name)
    assert forbidden_hit(f"{name}_track")
    assert forbidden_hit(f"build_{name}")


@pytest.mark.parametrize("name", PHASE26_NAMES)
def test_no_phase26_name_false_positives(name: str) -> None:
    """The layer's own legitimate vocabulary never trips the guard."""
    assert not forbidden_hit(name)


def test_the_vocabulary_guard_catches_an_offender(tmp_path: Path) -> None:
    """A synthetic module defining voice vocabulary is caught."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "def build_voice_track(caption_cues: list[str]) -> None:\n    return None\n",
        encoding="utf-8",
    )
    hits = {name for name in defined_names(parse(offender)) if forbidden_hit(name)}
    assert hits


def test_the_vocabulary_guard_ignores_prose_in_a_docstring(tmp_path: Path) -> None:
    """Prose about forbidden words is not a definition of them."""
    innocent = tmp_path / "innocent.py"
    innocent.write_text(
        '"""This layer never emits captions, audio, or a voice line."""\nVALUE = 1\n',
        encoding="utf-8",
    )
    hits = {name for name in defined_names(parse(innocent)) if forbidden_hit(name)}
    assert hits == set()


def test_the_import_guard_catches_an_offender(tmp_path: Path) -> None:
    """A synthetic module importing delivery is caught."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "from living_diorama.narration_delivery import delivery_spec\n", encoding="utf-8"
    )
    names = imported_modules(parse(offender))
    assert any(name.startswith(root) for name in names for root in FORBIDDEN_ENGINE_ROOTS)


def test_the_delivery_guard_catches_an_offender(tmp_path: Path) -> None:
    """The raw-substring delivery guard fires on a synthetic offender.

    The guard is a plain source-containment check, so the offender proof
    exercises exactly that predicate, alongside an innocent file it passes.
    """
    offender = tmp_path / "offender.py"
    offender.write_text(
        "from living_diorama.narration_delivery import delivery_spec\n", encoding="utf-8"
    )
    innocent = tmp_path / "innocent.py"
    innocent.write_text("VALUE = 1\n", encoding="utf-8")
    assert "narration_delivery" in offender.read_text(encoding="utf-8")
    assert "narration_delivery" not in innocent.read_text(encoding="utf-8")


def test_the_allow_list_guard_catches_an_offender(tmp_path: Path) -> None:
    """A real engine module off the allow-list is caught by the allow-list alone.

    The offender sits under no forbidden root, so only the stricter
    allow-list check can refuse it.
    """
    offender = tmp_path / "offender.py"
    offender.write_text(
        "from living_diorama.story.story_facts import resolve_source_event\n", encoding="utf-8"
    )
    engine = [
        name for name in imported_modules(parse(offender)) if name.startswith("living_diorama")
    ]
    assert engine
    assert any(name not in ALLOWED_ENGINE_MODULES for name in engine)
    assert not any(name.startswith(root) for name in engine for root in FORBIDDEN_ENGINE_ROOTS)


def test_the_network_guard_catches_an_offender(tmp_path: Path) -> None:
    """A synthetic module importing a client library is caught."""
    offender = tmp_path / "offender.py"
    offender.write_text("import requests\n", encoding="utf-8")
    names = imported_modules(parse(offender))
    assert any(name.split(".", 1)[0] in NETWORK_MODULES for name in names)


def test_the_nondeterminism_guard_catches_an_offender(tmp_path: Path) -> None:
    """A synthetic module importing the clock is caught."""
    offender = tmp_path / "offender.py"
    offender.write_text("import time\n", encoding="utf-8")
    names = imported_modules(parse(offender))
    assert any(name.split(".", 1)[0] in NONDETERMINISM_MODULES for name in names)


def test_the_write_guard_catches_an_offender(tmp_path: Path) -> None:
    """A synthetic module writing a file is caught."""
    offender = tmp_path / "offender.py"
    offender.write_text("def leak(path):\n    path.write_text('x')\n", encoding="utf-8")
    hits = [line for line in _code_lines(offender) for marker in WRITE_MARKERS if marker in line]
    assert hits


def test_the_key_read_guard_catches_every_shape(tmp_path: Path) -> None:
    """A subscript, a .get and a .pop read of a banned key are all caught."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "def leak(unit, fact, event):\n"
        '    return unit["text"], fact.get("summary"), event.pop("source_event_payload")\n',
        encoding="utf-8",
    )
    tree = parse(offender)
    assert key_reads(tree, "text")
    assert key_reads(tree, "summary")
    assert key_reads(tree, "source_event_payload")


def test_the_prose_branch_guard_catches_an_offender(tmp_path: Path) -> None:
    """A synthetic module branching on wording is caught."""
    offender = tmp_path / "offender.py"
    offender.write_text("def leak(sentence):\n    return sentence.split()[0]\n", encoding="utf-8")
    hits = [
        line for line in _code_lines(offender) for marker in PROSE_BRANCH_MARKERS if marker in line
    ]
    assert hits


def test_the_wholesale_copy_guard_catches_an_offender(tmp_path: Path) -> None:
    """A synthetic module spreading a record is caught."""
    offender = tmp_path / "offender.py"
    offender.write_text("def leak(unit):\n    return dict(**unit)\n", encoding="utf-8")
    hits = [
        line
        for line in _code_lines(offender)
        for marker in WHOLESALE_COPY_MARKERS
        if marker in line
    ]
    assert hits
