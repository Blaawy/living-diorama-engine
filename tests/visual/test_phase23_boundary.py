"""Phase 23 scope guard: the layer photographs a directed episode and owns nothing else.

Phase 23 owns one responsibility -- turning an already-directed episode into
image files, and proving which files exist. Everything a reader might expect it
to grow into belongs to somebody else: narration and prose; voice and audio;
final editing, encoding and packaging; publishing; and any re-direction of the
cameras Phase 22 already chose.

This phase legitimately writes files and legitimately imports ``bpy`` on its
Blender side, which is exactly why the guards below are split: the pure layer
is held to the same reach rules Phase 22's pure layer is held to, while the
executor is allowed the two things it exists to do and nothing more.

These are reach rules, not a claim that these files are frozen. Each guard is
exercised against a deliberately bad synthetic file as well as the real ones,
because a guard nobody has seen fail is a guard nobody has tested.
"""

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RENDER_EXECUTION = REPO_ROOT / "src" / "living_diorama" / "render_execution"
CLI = REPO_ROOT / "src" / "living_diorama" / "cli"
SCRIPTS = REPO_ROOT / "visual" / "blender" / "scripts"

PURE_MODULES = (
    RENDER_EXECUTION / "__init__.py",
    RENDER_EXECUTION / "frame_image.py",
    RENDER_EXECUTION / "render_execution_schema_v1.py",
    RENDER_EXECUTION / "render_execution_spec.py",
    RENDER_EXECUTION / "render_binding.py",
    RENDER_EXECUTION / "render_manifest.py",
    RENDER_EXECUTION / "render_planner.py",
    CLI / "build_render_plan.py",
    CLI / "verify_render.py",
)
"""Every pure file Phase 23 adds, named one by one.

A glob would quietly stop guarding a module somebody renamed, and would quietly
start guarding somebody else's.
"""

BLENDER_MODULES = (SCRIPTS / "episode_scene.py", SCRIPTS / "render_episode.py")
"""The Blender-side realization. Allowed to import ``bpy``; nothing else is."""

PHASE23_MODULES = PURE_MODULES + BLENDER_MODULES

TESTS_RENDER_EXECUTION = REPO_ROOT / "tests" / "render_execution"
BLENDER_TESTS = REPO_ROOT / "visual" / "blender" / "tests"

PHASE23_TEST_FILES = (
    TESTS_RENDER_EXECUTION / "__init__.py",
    TESTS_RENDER_EXECUTION / "conftest.py",
    TESTS_RENDER_EXECUTION / "test_frame_image.py",
    TESTS_RENDER_EXECUTION / "test_production_boundary.py",
    TESTS_RENDER_EXECUTION / "test_render_binding.py",
    TESTS_RENDER_EXECUTION / "test_render_cli.py",
    TESTS_RENDER_EXECUTION / "test_render_determinism.py",
    TESTS_RENDER_EXECUTION / "test_render_execution_spec.py",
    TESTS_RENDER_EXECUTION / "test_render_executor.py",
    TESTS_RENDER_EXECUTION / "test_render_manifest.py",
    TESTS_RENDER_EXECUTION / "test_render_planner.py",
    TESTS_RENDER_EXECUTION / "test_render_schema.py",
    TESTS_RENDER_EXECUTION / "test_source_binding.py",
    Path(__file__).resolve(),
    BLENDER_TESTS / "run_blender_tests_p23.py",
    BLENDER_TESTS / "test_episode_render.py",
)
"""Every test file Phase 23 adds, including this one.

``Path(__file__)`` is in the list deliberately. The eight ASCII backspace bytes
that turned four forbidden terms off lived in *this* file, and the first version
of the scan below walked only ``PHASE23_MODULES`` -- the eleven source modules.
It would not have caught the defect it was written for. A guard that exempts
itself is the shape of the bug it is guarding against.
"""

PHASE23_DOCS = (REPO_ROOT / "docs" / "episode_render_execution.md",)
"""The phase documentation, which ships in the candidate and is scanned too."""

PHASE23_FILES = PHASE23_MODULES + PHASE23_TEST_FILES + PHASE23_DOCS
"""Every file the candidate adds -- source, tests and documentation alike."""

ALLOWED_ENGINE_MODULES = frozenset(
    {
        "living_diorama.cinematic",
        "living_diorama.cinematic.cinematic_schema_v1",
        "living_diorama.cinematic.cinematic_spec",
        "living_diorama.persistence.json_codec",
        "living_diorama.persistence.schema.state_hash",
        "living_diorama.persistence.schema.world_schema_v1",
        "living_diorama.render_execution",
        "living_diorama.render_execution.frame_image",
        "living_diorama.render_execution.render_binding",
        "living_diorama.render_execution.render_execution_schema_v1",
        "living_diorama.render_execution.render_execution_spec",
        "living_diorama.render_execution.render_manifest",
        "living_diorama.render_execution.render_planner",
        "living_diorama.story",
    }
)
"""The only engine modules the pure layer may reach for.

Phase 21's and Phase 22's contracts, the shared validation vocabulary, and
this package. A render plan is derived from finished documents; nothing
here needs the live world.
"""

FORBIDDEN_ENGINE_ROOTS = frozenset({"entities", "events", "memory", "simulation", "systems"})
"""Live-world packages Phase 23 must never touch.

``render`` is absent from this set only because it is not reached either: the
guard below asserts the exact allowed set, so no engine module outside
``ALLOWED_ENGINE_MODULES`` is importable regardless of which root it sits in.
"""

NETWORK_MODULES = frozenset(
    {"http", "httpx", "openai", "requests", "socket", "ssl", "urllib", "urllib3", "anthropic"}
)
"""No runtime model call, and no network of any kind, ever."""

FORBIDDEN_IDENTIFIERS = re.compile(
    r"(?i).*("
    # Phase 24+: narration and prose
    r"narrat|voiceover|subtitle|caption|prose|sentence|paragraph|summar"
    r"|prompt|llm|gpt|embedding"
    # Phase 24+: audio and voice
    r"|audio|music|soundtrack|speech|\btts\b"
    # Phase 24+: final assembly, encoding, packaging, publishing
    r"|ffmpeg|mux|encode_video|render_video|transcode|codec|bitrate|thumbnail"
    r"|publish|package_episode|edit_list|crossfade|dissolve|mixdown"
    r"|\bwav\b|\bmp4\b|\bsrt\b|\bvtt\b|dialogue|voice_line"
    # re-direction of Phase 22's decisions
    r"|choose_camera|select_camera|reframe|dolly|pan_speed|orbit|camera_path"
    r"|camera_anim|interpolate_camera|shot_rank|re_?rank|emphasis_weight"
    # citizen-level simulation
    r"|citizen|biograph|relationship|commute|workplace|household"
    r").*"
)
"""Names Phase 23 must not define.

Matched against *defined* names only -- functions, classes, arguments, assigned
names, and identifier-shaped string keys -- so that a docstring explaining what
this phase does not do cannot trip the guard.
"""

CAMERA_MUTATION_MARKERS = (
    ".location =",
    ".rotation_euler =",
    ".rotation_quaternion =",
    ".delta_location =",
    ".lens =",
    ".sensor_width =",
    ".focus_distance =",
    ".keyframe_insert",
    ".animation_data_create",
    "cameras.new",
    "bpy.data.cameras",
)
"""Source substrings that would mean this phase moved or made a camera."""

SCENE_MUTATION_MARKERS = (
    "timeline_markers.new",
    "timeline_markers.remove",
    ".marker.camera",
    "bpy.data.objects.remove",
    "bpy.data.meshes.remove",
    "bpy.data.materials.new",
)
"""Substrings that would mean this phase re-directed or rebuilt the world.

Phase 23 calls Phase 22's applier to bind markers; it never binds one itself,
and it never edits the world it was handed.
"""

PHASE_DOCUMENT_OWNERS = ("story_planner", "shot_planner", "cinematic_cross_check")
"""Upstream planners. Their output arrives as data; they are never re-run here."""


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


# ------------------------------------------------------------- import reach


def test_the_pure_layer_never_imports_blender() -> None:
    """A render plan is derived from documents; it needs no renderer."""
    for path in PURE_MODULES:
        assert "bpy" not in imported_roots(parse(path)), path.name


def test_the_blender_layer_never_imports_the_engine() -> None:
    """The plan and the catalogue cross the boundary as data, not as imports."""
    for path in BLENDER_MODULES:
        assert "living_diorama" not in imported_roots(parse(path)), path.name


def test_the_pure_layer_reaches_only_the_modules_it_is_allowed() -> None:
    """The exact allowed set, so a new reach has to be argued for in this file."""
    for path in PURE_MODULES:
        reached = {
            name for name in imported_modules(parse(path)) if name.startswith("living_diorama")
        }
        assert reached <= ALLOWED_ENGINE_MODULES, (path.name, sorted(reached))


def test_no_phase_twenty_three_module_reaches_the_live_world() -> None:
    """Rendering reads finished documents; it never touches the simulation."""
    for path in PHASE23_MODULES:
        reached = {
            name.split(".")[1]
            for name in imported_modules(parse(path))
            if name.startswith("living_diorama.") and len(name.split(".")) > 1
        }
        assert not (reached & FORBIDDEN_ENGINE_ROOTS), (path.name, sorted(reached))


def test_no_phase_twenty_three_module_reaches_the_network() -> None:
    """No runtime model call, no upload, no fetch."""
    for path in PHASE23_MODULES:
        assert not (imported_roots(parse(path)) & NETWORK_MODULES), path.name


def test_no_phase_twenty_three_module_re_runs_an_upstream_planner() -> None:
    """Story and direction arrive as documents; re-deriving them here would fork them."""
    for path in PHASE23_MODULES:
        imported = imported_modules(parse(path))
        for owner in PHASE_DOCUMENT_OWNERS:
            assert not any(owner in name for name in imported), (path.name, owner)


# ------------------------------------------------------------------ vocabulary


FORBIDDEN_TERM_SEGMENTS = tuple(
    frozenset(term.split("_"))
    for term in (
        "encode_video",
        "render_video",
        "package_episode",
        "edit_list",
        "voice_line",
        "camera_path",
        "camera_anim",
        "interpolate_camera",
        "shot_rank",
        "emphasis_weight",
        "choose_camera",
        "select_camera",
        "pan_speed",
    )
)
"""Every multi-word forbidden term, as a set of its words.

Matched as a subset of a name's own words, so word order cannot defeat the
term. ``render_video`` and ``video_render`` are the same intent and the guard
now says so. Single-word terms are not here -- the pattern already catches those
wherever they appear.
"""


def forbidden_hit(name: str) -> bool:
    r"""Return whether one defined name reaches a future layer's vocabulary.

    The pattern is matched against the whole name *and* against each
    underscore-separated segment of it. That second half matters more than it
    looks. Four of the forbidden terms are short enough to need a word boundary
    -- ``wav``, ``mp4``, ``srt``, ``vtt`` -- or they would fire on ``wavelength``
    and every ``srtd`` typo. But ``_`` is a word character, so ``\bwav\b``
    never matches inside ``wav_track``: the boundary the term needs is exactly
    the boundary Python identifiers do not have.

    Splitting on ``_`` gives those terms the segment boundary they were written
    for, so ``wav_track``, ``write_wav`` and ``srt_index`` are all caught while
    ``wavelength`` still is not.
    """
    if FORBIDDEN_IDENTIFIERS.match(name):
        return True
    parts = [part for part in name.split("_") if part]
    if any(FORBIDDEN_IDENTIFIERS.match(part) for part in parts):
        return True
    # Multi-word terms were order-dependent: `encode_video` was caught and
    # `video_encode` was not, which is a rename away from no guard at all. A
    # name whose segments contain every segment of a forbidden term is the same
    # name with the words shuffled.
    segments = set(parts)
    return any(term_parts <= segments for term_parts in FORBIDDEN_TERM_SEGMENTS)


def test_no_phase_twenty_three_module_defines_a_future_layers_vocabulary() -> None:
    """Narration, audio, encoding, packaging, publishing: none of them start here."""
    for path in PHASE23_MODULES:
        for name in sorted(defined_names(parse(path))):
            assert not forbidden_hit(name), f"{path.name} defines {name!r}"


FUTURE_LAYER_NAMES = (
    "wav",
    "mp4",
    "srt",
    "vtt",
    "tts",
    "ffmpeg",
    "encode_video",
    "audio",
    "narration",
    "publishing",
    "mixdown",
    "voiceover",
    "subtitle",
    "transcode",
    "package_episode",
)
"""Names belonging to phases after this one, each of which the guard must catch.

Every one of these is a real term from the forbidden pattern. They are listed
separately and asserted one by one because a pattern that silently stops
matching some of its own alternatives is exactly the failure this file had: four
terms -- ``wav``, ``mp4``, ``srt``, ``vtt`` -- were written with literal ASCII
backspace bytes instead of the intended ``\b`` word-boundary escapes, so the
regex looked complete while matching nothing for any of them. A guard nobody
tests against its own vocabulary is a guard that can quietly stop guarding.
"""

NEAR_MISS_NAMES = (
    "wavelength",
    "waveform_cache",
    "mp4x",
    "assert_sorted",
    "convert_srtm_tile",
    "vttl",
    "attts",
)
"""Names that merely contain a short forbidden term and must NOT be caught.

Without the word boundaries every one of these would fire, and a guard with
false positives is a guard somebody turns off. ``convert_srtm_tile`` is the
realistic one: SRTM is elevation data, and a terrain layer could legitimately
name it.
"""

PHASE23_NAMES = (
    "render_frame_file",
    "build_episode_render_plan_document",
    "require_render_plan_matches_shot_plan",
    "image_stream_digest",
    "verify_frame_image",
    "survey_render_directory",
    "witness_mean_abs_difference",
    "composition_sources",
    "camera_anchor_id",
    "source_beat_ids",
    "playback_seconds",
    "render_profile_sha256",
)
"""Real names this phase defines. None may trip the guard.

A forbidden pattern broad enough to fire on the phase's own vocabulary would be
turned off within a week, so the false-positive direction is tested too.
"""


@pytest.mark.parametrize("name", FUTURE_LAYER_NAMES)
def test_the_guard_catches_every_term_it_claims_to(name: str) -> None:
    """Each forbidden term, asserted on its own rather than trusted in bulk."""
    assert forbidden_hit(name), name


@pytest.mark.parametrize("name", PHASE23_NAMES)
def test_the_guard_does_not_fire_on_this_phases_own_vocabulary(name: str) -> None:
    """The control: a guard that cried wolf on `render_frame_file` would be disabled."""
    assert not forbidden_hit(name), name


@pytest.mark.parametrize("name", NEAR_MISS_NAMES)
def test_the_short_terms_do_not_fire_on_words_that_merely_contain_them(name: str) -> None:
    """`wavelength` is not `wav`. This is what the word boundaries are for."""
    assert not forbidden_hit(name), name


@pytest.mark.parametrize("name", FUTURE_LAYER_NAMES)
def test_a_module_defining_a_future_layer_name_is_caught(tmp_path: Path, name: str) -> None:
    r"""End to end: caught as a *defined name*, through the real AST walk.

    The name is ``<term>_track`` rather than the bare term, because that is the
    shape a real offender would have -- nobody writes a function called ``wav``
    -- and it is precisely the shape a bare ``\b`` boundary would miss.
    """
    offender = tmp_path / f"offender_{name}.py"
    offender.write_text(
        f'"""An offender."""\n\n\ndef {name}_track():\n    return None\n', encoding="utf-8"
    )
    caught = {found for found in defined_names(parse(offender)) if forbidden_hit(found)}
    assert caught == {f"{name}_track"}


def test_the_vocabulary_guard_catches_an_offender(tmp_path: Path) -> None:
    """The guard proven against a file that genuinely breaks the rule."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        '"""A module that quietly grew a narration track."""\n\n'
        "def build_narration_track(caption_text):\n"
        "    return caption_text\n",
        encoding="utf-8",
    )
    offending = {
        name for name in defined_names(parse(offender)) if FORBIDDEN_IDENTIFIERS.match(name)
    }
    assert offending == {"build_narration_track", "caption_text"}


def test_the_import_guard_catches_an_offender(tmp_path: Path) -> None:
    """A pure module that reached for Blender would be caught."""
    offender = tmp_path / "offender.py"
    offender.write_text('"""Reaches for the renderer."""\n\nimport bpy\n', encoding="utf-8")
    assert "bpy" in imported_roots(parse(offender))


def test_the_network_guard_catches_an_offender(tmp_path: Path) -> None:
    """An upload helper would be caught before it shipped."""
    offender = tmp_path / "offender.py"
    offender.write_text('"""Uploads the episode."""\n\nimport requests\n', encoding="utf-8")
    assert imported_roots(parse(offender)) & NETWORK_MODULES


# ------------------------------------------------------- direction is read-only


def test_no_phase_twenty_three_module_moves_or_creates_a_camera() -> None:
    """Phase 22 chose the cameras and the world built them; Phase 23 looks through them."""
    for path in PHASE23_MODULES:
        source = path.read_text(encoding="utf-8")
        for marker in CAMERA_MUTATION_MARKERS:
            assert marker not in source, f"{path.name} contains {marker!r}"


def test_no_phase_twenty_three_module_binds_its_own_markers_or_edits_the_world() -> None:
    """Direction is applied by calling Phase 22's applier, never re-implemented."""
    for path in PHASE23_MODULES:
        source = path.read_text(encoding="utf-8")
        for marker in SCENE_MUTATION_MARKERS:
            assert marker not in source, f"{path.name} contains {marker!r}"


def test_the_camera_mutation_guard_catches_an_offender(tmp_path: Path) -> None:
    """Proven against a file that nudges a camera."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        '"""Nudges the hero camera."""\n\n'
        "def nudge(camera):\n"
        "    camera.location = (1.0, 2.0, 3.0)\n",
        encoding="utf-8",
    )
    source = offender.read_text(encoding="utf-8")
    assert any(marker in source for marker in CAMERA_MUTATION_MARKERS)


# ------------------------------------------------------------- the file list


ALLOWED_CONTROL_BYTES = frozenset({0x09, 0x0A})
"""Tab and newline. Every other control byte in source is a mistake.

This scan exists because of one: eight ASCII backspace bytes sat inside a regex
in this very file, turning four of its terms off. They were invisible in every
editor and every diff, and no test looked at the bytes.
"""


def test_no_candidate_file_carries_a_stray_control_character() -> None:
    """Bytes below 0x20 are not source; they are damage that reads as source."""
    offenders: list[str] = []
    for path in PHASE23_FILES:
        raw = path.read_bytes()
        for index, byte in enumerate(raw):
            if byte < 0x20 and byte not in ALLOWED_CONTROL_BYTES:
                line = raw[:index].count(b"\n") + 1
                offenders.append(f"{path.name}:{line} carries byte 0x{byte:02x}")
    assert offenders == [], offenders


def test_the_control_character_scan_catches_an_offender(tmp_path: Path) -> None:
    """Proven against a file carrying the exact damage this file used to carry."""
    offender = tmp_path / "offender.py"
    offender.write_bytes(b'PATTERN = r"|\x08wav\x08"\n')
    raw = offender.read_bytes()
    found = [byte for byte in raw if byte < 0x20 and byte not in ALLOWED_CONTROL_BYTES]
    assert found == [0x08, 0x08]


def test_the_control_scan_covers_this_file(tmp_path: Path) -> None:
    """The scan must include the file that carried the damage: this one."""
    del tmp_path
    assert Path(__file__).resolve() in {path.resolve() for path in PHASE23_FILES}


def test_the_scan_covers_every_phase_twenty_three_test_file() -> None:
    """A new test file is scanned by default, not by somebody remembering to add it."""
    on_disk = {path.resolve() for path in TESTS_RENDER_EXECUTION.glob("*.py")}
    listed = {path.resolve() for path in PHASE23_TEST_FILES}
    assert on_disk <= listed, sorted(str(path) for path in on_disk - listed)


def test_every_candidate_file_exists_and_is_counted() -> None:
    """All twenty-eight files the candidate ships are covered by the scan."""
    for path in PHASE23_FILES:
        assert path.is_file(), path
    assert len(PHASE23_FILES) == 28, len(PHASE23_FILES)


def test_every_guarded_file_exists() -> None:
    """A renamed module must be renamed here too, or the guard silently lapses."""
    for path in PHASE23_MODULES:
        assert path.exists(), path


def test_the_guard_covers_every_pure_module_in_the_package() -> None:
    """A new file in the package is guarded by default, not by remembering to."""
    on_disk = {path.name for path in RENDER_EXECUTION.glob("*.py")}
    guarded = {path.name for path in PURE_MODULES if path.parent == RENDER_EXECUTION}
    assert on_disk == guarded, sorted(on_disk ^ guarded)
