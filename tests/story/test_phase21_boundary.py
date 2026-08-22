"""Phase 21 scope guard: the story layer decides emphasis and nothing else.

Phase 21 owns one responsibility -- saying which authoritative records
downstream presentation should attend to. Everything a reader might reasonably
expect it to grow into is somebody else's phase: camera direction, shot
selection and cut grammar; narration and prose; editing and packaging; and any
citizen-level semantics at all.

These are reach rules, not a claim that these files are frozen. The guard proves
what the story modules may *touch*: what they import, whether they write, and
what vocabulary they define. Each guard is exercised against a deliberately bad
synthetic file as well as the real ones, because a guard nobody has seen fail is
a guard nobody has tested.
"""

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STORY = REPO_ROOT / "src" / "living_diorama" / "story"
CLI = REPO_ROOT / "src" / "living_diorama" / "cli"

PHASE21_MODULES = (
    STORY / "__init__.py",
    STORY / "story_facts.py",
    STORY / "story_lineage.py",
    STORY / "story_planner.py",
    STORY / "story_schema_v1.py",
    STORY / "story_spec.py",
    CLI / "build_story_plan.py",
)
"""Every file Phase 21 adds, named one by one.

A glob would quietly stop guarding a module somebody renamed, and would quietly
start guarding somebody else's.
"""

ALLOWED_ENGINE_MODULES = frozenset(
    {
        "living_diorama.persistence.json_codec",
        "living_diorama.persistence.schema.state_hash",
        "living_diorama.persistence.schema.world_schema_v1",
        "living_diorama.render.render_schema_v1",
        "living_diorama.story",
        "living_diorama.story.story_facts",
        "living_diorama.story.story_lineage",
        "living_diorama.story.story_planner",
        "living_diorama.story.story_schema_v1",
        "living_diorama.story.story_spec",
    }
)
"""The only engine modules the story layer may reach.

Story consumes a verified render export through the render contract, and
validates with the persistence vocabulary, exactly as ``render`` itself does. It
may not reach past those into live simulation.
"""

FORBIDDEN_ENGINE_ROOTS = frozenset({"entities", "events", "memory", "simulation", "systems", "cli"})
"""Engine subpackages the story layer must never import.

``memory`` is on the list deliberately: story reads memory *facts as exported*,
through the render contract, and must not acquire a second opinion about what
durable memory is by importing the live model.
"""

NETWORK_MODULES = frozenset(
    {
        "http",
        "httpx",
        "openai",
        "requests",
        "socket",
        "ssl",
        "urllib",
        "urllib3",
        "anthropic",
    }
)
"""No runtime model call, and no network of any kind, ever."""

FORBIDDEN_IDENTIFIERS = re.compile(
    r"(?i).*("
    # Phase 22+: cinematic direction
    r"camera|shot|cut_grammar|lens|framing|dolly|pan_speed|edit_list|timeline_edit"
    # Phase 22+: narration and prose
    r"|narrat|voiceover|subtitle|caption|prose|sentence|paragraph|summar"
    r"|prompt|llm|gpt|embedding"
    # packaging
    r"|thumbnail|publish|encode_video|render_video|audio_track"
    # citizen-level simulation
    r"|citizen|biograph|relationship|schedule|commute|workplace|household"
    r").*"
)
"""Names Phase 21 must not define.

Matched against *defined* names only -- functions, classes, arguments, assigned
names, and identifier-shaped string keys -- so that a docstring explaining what
this phase does not do cannot trip the guard.
"""

MUTATORS = frozenset(
    {
        "append",
        "clear",
        "extend",
        "insert",
        "pop",
        "popitem",
        "remove",
        "setdefault",
        "update",
        "sort",
        "reverse",
    }
)
PASS_THROUGH_CALLS = frozenset({"enumerate", "iter", "list", "reversed", "sorted", "tuple", "zip"})
PASS_THROUGH_METHODS = frozenset({"get", "items", "keys", "values"})
INPUT_ROOTS = frozenset(
    {"current_export", "previous_export", "export", "current", "previous", "value"}
)
"""Names that hold a caller's document. Taint spreads from these."""


# ---------------------------------------------------------------- primitives


def parse(path: Path) -> ast.Module:
    """Parse a guarded file, failing loudly if it has gone missing."""
    assert path.exists(), f"{path.name} is guarded but missing"
    return ast.parse(path.read_text(encoding="utf-8"))


def imported_modules(tree: ast.Module) -> set[str]:
    """Every module name the file imports, dotted and whole."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            names.add(node.module)
    return names


def imported_roots(tree: ast.Module) -> set[str]:
    """The top-level package of every import in the file."""
    return {name.split(".")[0] for name in imported_modules(tree)}


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


def mutation_sites(tree: ast.Module) -> list[str]:
    """Report writes into anything derived from a caller's document."""
    tainted = set(INPUT_ROOTS)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(
            node.value, (ast.Name, ast.Call, ast.Subscript)
        ):
            source = node.value
            root = None
            if isinstance(source, ast.Name):
                root = source.id
            elif isinstance(source, ast.Subscript) and isinstance(source.value, ast.Name):
                root = source.value.id
            elif isinstance(source, ast.Call):
                func = source.func
                if isinstance(func, ast.Name) and func.id in PASS_THROUGH_CALLS:
                    for arg in source.args:
                        if isinstance(arg, ast.Name) and arg.id in tainted:
                            root = arg.id
                elif (
                    isinstance(func, ast.Attribute)
                    and func.attr in PASS_THROUGH_METHODS
                    and isinstance(func.value, ast.Name)
                    and func.value.id in tainted
                ):
                    root = func.value.id
            if root in tainted:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        tainted.add(target.id)

    writes: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id in tainted
                ):
                    writes.append(f"line {node.lineno}: writes into {target.value.id}")
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id in tainted
                ):
                    writes.append(f"line {node.lineno}: sets attribute on {target.value.id}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in MUTATORS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in tainted
        ):
            writes.append(f"line {node.lineno}: calls {node.func.attr}() on {node.func.value.id}")
    return writes


# -------------------------------------------------------------- import reach


def test_every_guarded_module_exists() -> None:
    """A guard pointing at a missing file guards nothing."""
    for path in PHASE21_MODULES:
        assert path.exists(), f"{path} is guarded but missing"


def test_the_story_layer_never_imports_blender() -> None:
    """Phase 21 must be testable with Python and JSON alone."""
    for path in PHASE21_MODULES:
        roots = imported_roots(parse(path))
        assert "bpy" not in roots and "bmesh" not in roots, f"{path.name} imports Blender"


def test_the_story_layer_never_imports_live_simulation() -> None:
    """The story layer never imports live simulation."""
    for path in PHASE21_MODULES:
        for module in imported_modules(parse(path)):
            if not module.startswith("living_diorama"):
                continue
            parts = module.split(".")
            if len(parts) > 1 and parts[1] in FORBIDDEN_ENGINE_ROOTS:
                if module in ALLOWED_ENGINE_MODULES:
                    continue
                raise AssertionError(f"{path.name} imports simulation module {module}")


def test_the_story_layer_reaches_only_the_engine_modules_it_is_allowed() -> None:
    """The story layer reaches only the engine modules it is allowed."""
    for path in PHASE21_MODULES:
        for module in imported_modules(parse(path)):
            if module.startswith("living_diorama"):
                assert module in ALLOWED_ENGINE_MODULES, (
                    f"{path.name} imports {module}, which is outside the story layer's reach"
                )


def test_the_story_layer_never_reaches_a_private_name_from_another_package() -> None:
    """The story layer never reaches a private name from another package."""
    for path in PHASE21_MODULES:
        tree = parse(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            if not node.module.startswith("living_diorama"):
                continue
            if node.module.startswith("living_diorama.story"):
                continue
            for alias in node.names:
                assert not alias.name.startswith("_"), (
                    f"{path.name} imports private name {alias.name} from {node.module}"
                )


def test_the_story_layer_never_calls_a_model_or_the_network() -> None:
    """No LLM at runtime, and no API call of any kind."""
    for path in PHASE21_MODULES:
        roots = imported_roots(parse(path))
        offenders = roots & NETWORK_MODULES
        assert offenders == set(), f"{path.name} imports {sorted(offenders)}"


def test_the_story_layer_never_imports_randomness_or_the_clock() -> None:
    """Either one would break byte-identical rebuilds."""
    for path in PHASE21_MODULES:
        roots = imported_roots(parse(path))
        for banned in ("random", "secrets", "time", "datetime", "uuid"):
            assert banned not in roots, f"{path.name} imports {banned}"


# ------------------------------------------------------------------- writing


def test_the_story_layer_never_writes_into_the_documents_it_reads() -> None:
    """Presentation reads authoritative state; it never writes it."""
    for path in PHASE21_MODULES:
        writes = mutation_sites(parse(path))
        assert writes == [], f"{path.name} mutates its input: {writes}"


def test_only_the_command_line_entry_point_touches_the_filesystem() -> None:
    """The derivation itself is pure; writing a file is the CLI's job alone."""
    for path in PHASE21_MODULES:
        if path.parent == CLI:
            continue
        roots = imported_roots(parse(path))
        assert "pathlib" not in roots, f"{path.name} imports pathlib"
        assert "os" not in roots, f"{path.name} imports os"
        source = path.read_text(encoding="utf-8")
        assert "open(" not in source, f"{path.name} opens a file"


def test_the_story_layer_never_writes_a_save() -> None:
    """The story layer never writes a save."""
    for path in PHASE21_MODULES:
        source = path.read_text(encoding="utf-8")
        for banned in ("save_root", "write_save", "SaveManager"):
            assert banned not in source, f"{path.name} references {banned}"


# ---------------------------------------------------------------- vocabulary


def test_the_story_layer_defines_no_downstream_or_citizen_vocabulary() -> None:
    """The story layer defines no downstream or citizen vocabulary."""
    for path in PHASE21_MODULES:
        for name in defined_names(parse(path)):
            assert not FORBIDDEN_IDENTIFIERS.fullmatch(name), (
                f"{path.name} defines {name!r}, which belongs to a later phase"
            )


def test_the_scope_guard_tolerates_the_words_phase21_owns() -> None:
    """A guard that blocks the phase's own vocabulary is useless."""
    for name in (
        "beat",
        "beat_id",
        "emphasis",
        "story_plan",
        "reason_code",
        "evidence",
        "rank",
        "subject_ids",
        "excluded",
        "unclassified",
        "episode",
        "transition",
    ):
        assert not FORBIDDEN_IDENTIFIERS.fullmatch(name), name


def test_the_story_layer_never_reads_a_memory_summary() -> None:
    """Prose may be carried; it may never drive a decision.

    The rule tables are keyed on type names. Nothing in the layer may subscript
    a fact by ``summary``, which is the only way its prose could reach a branch.
    """
    for path in PHASE21_MODULES:
        source = path.read_text(encoding="utf-8")
        for banned in ('["summary"]', "['summary']", '.get("summary"'):
            assert banned not in source, f"{path.name} reads a memory summary: {banned}"


def test_the_story_layer_does_not_redefine_cinematic_time() -> None:
    """Phase 17's clock is locked; Phase 21 may reference time, never redefine it."""
    for path in PHASE21_MODULES:
        for name in defined_names(parse(path)):
            for banned in ("fps", "frame_rate", "frame_count", "start_frame", "end_frame"):
                assert name != banned, f"{path.name} defines {name!r}"


# ---------------------------------------------- the guards actually bite


def test_the_simulation_import_guard_catches_an_offender(tmp_path: Path) -> None:
    """The simulation import guard catches an offender."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "from living_diorama.systems.scarcity_system import ScarcitySystem\n",
        encoding="utf-8",
    )
    modules = imported_modules(parse(offender))
    assert any(
        module.split(".")[1] in FORBIDDEN_ENGINE_ROOTS and module not in ALLOWED_ENGINE_MODULES
        for module in modules
    )


def test_the_allowed_reach_guard_catches_an_unlisted_engine_module(tmp_path: Path) -> None:
    """The allowed reach guard catches an unlisted engine module."""
    offender = tmp_path / "offender.py"
    offender.write_text("from living_diorama.render.render_exporter import x\n", encoding="utf-8")
    modules = imported_modules(parse(offender))
    assert not modules <= ALLOWED_ENGINE_MODULES


def test_the_network_guard_catches_an_offender(tmp_path: Path) -> None:
    """The network guard catches an offender."""
    offender = tmp_path / "offender.py"
    offender.write_text("import requests\nimport urllib.request\n", encoding="utf-8")
    assert imported_roots(parse(offender)) & NETWORK_MODULES


def test_the_clock_guard_catches_an_offender(tmp_path: Path) -> None:
    """The clock guard catches an offender."""
    offender = tmp_path / "offender.py"
    offender.write_text("import datetime\n", encoding="utf-8")
    assert "datetime" in imported_roots(parse(offender))


def test_the_mutation_guard_catches_a_subscript_write(tmp_path: Path) -> None:
    """The mutation guard catches a subscript write."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "def go(export):\n    export['world'] = {}\n",
        encoding="utf-8",
    )
    assert mutation_sites(parse(offender))


def test_the_mutation_guard_catches_a_mutator_call(tmp_path: Path) -> None:
    """The mutation guard catches a mutator call."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "def go(export):\n    events = export['events']\n    events.sort()\n",
        encoding="utf-8",
    )
    assert mutation_sites(parse(offender))


def test_the_mutation_guard_leaves_a_pure_reader_alone(tmp_path: Path) -> None:
    """A guard that fires on innocent code would be turned off within a week."""
    innocent = tmp_path / "innocent.py"
    innocent.write_text(
        "def go(export):\n"
        "    events = export['events']\n"
        "    out = []\n"
        "    for index, event in enumerate(events):\n"
        "        out.append({'index': index, 'type': event['type']})\n"
        "    return sorted(out, key=lambda entry: entry['index'])\n",
        encoding="utf-8",
    )
    assert mutation_sites(parse(innocent)) == []


def test_the_vocabulary_guard_catches_downstream_names(tmp_path: Path) -> None:
    """The vocabulary guard catches downstream names."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "def choose_camera():\n"
        "    pass\n"
        "def build_narration():\n"
        "    pass\n"
        "citizen_id = 1\n"
        "shot_list = []\n",
        encoding="utf-8",
    )
    caught = {
        name for name in defined_names(parse(offender)) if FORBIDDEN_IDENTIFIERS.fullmatch(name)
    }
    assert {"choose_camera", "build_narration", "citizen_id", "shot_list"} <= caught


def test_the_vocabulary_guard_ignores_prose_in_a_docstring(tmp_path: Path) -> None:
    """The phase must be able to document what it refuses to become."""
    innocent = tmp_path / "innocent.py"
    innocent.write_text(
        '"""This layer does not choose a camera, a shot, or write narration."""\n'
        "def rank_beats():\n"
        "    pass\n",
        encoding="utf-8",
    )
    caught = {
        name for name in defined_names(parse(innocent)) if FORBIDDEN_IDENTIFIERS.fullmatch(name)
    }
    assert caught == set()
