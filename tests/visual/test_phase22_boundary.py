"""Phase 22 scope guard: the layer selects cameras and owns nothing else.

Phase 22 owns one responsibility -- which already-existing camera anchor should be
active over which stretch of the already-locked Phase 17 timeline. Everything a
reader might expect it to grow into is somebody else's phase: narration and prose;
audio and subtitles; editing beyond ordered fixed-camera cuts; encoding and
packaging; and any camera *movement* at all.

These are reach rules, not a claim that these files are frozen. Each guard is
exercised against a deliberately bad synthetic file as well as the real ones,
because a guard nobody has seen fail is a guard nobody has tested.
"""

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CINEMATIC = REPO_ROOT / "src" / "living_diorama" / "cinematic"
CLI = REPO_ROOT / "src" / "living_diorama" / "cli"
SCRIPTS = REPO_ROOT / "visual" / "blender" / "scripts"

PURE_MODULES = (
    CINEMATIC / "__init__.py",
    CINEMATIC / "cinematic_cross_check.py",
    CINEMATIC / "cinematic_schema_v1.py",
    CINEMATIC / "cinematic_spec.py",
    CINEMATIC / "shot_planner.py",
    CLI / "build_shot_plan.py",
)
"""Every pure file Phase 22 adds, named one by one.

A glob would quietly stop guarding a module somebody renamed, and would quietly
start guarding somebody else's.
"""

BLENDER_MODULES = (SCRIPTS / "apply_cinematic_direction.py",)
"""The Blender-side realization. Allowed to import ``bpy``; nothing else is."""

PHASE22_MODULES = PURE_MODULES + BLENDER_MODULES

ALLOWED_ENGINE_MODULES = frozenset(
    {
        "living_diorama.cinematic",
        "living_diorama.cinematic.camera_direction_v4",
        "living_diorama.cinematic.camera_direction_v5",
        "living_diorama.cinematic.camera_movement_planner",
        "living_diorama.cinematic.cinematic_cross_check",
        "living_diorama.cinematic.cinematic_schema_v1",
        "living_diorama.cinematic.cinematic_schema_v2",
        "living_diorama.cinematic.cinematic_spec",
        "living_diorama.cinematic.shot_planner",
        "living_diorama.persistence.json_codec",
        "living_diorama.persistence.schema.state_hash",
        "living_diorama.persistence.schema.world_schema_v1",
        "living_diorama.story",
    }
)
"""The only engine modules the cinematic layer may reach.

It consumes a verified story plan through ``living_diorama.story`` and validates
with the persistence vocabulary. It may not reach past those into live simulation,
and it may not reach into ``living_diorama.render`` either -- Phase 21 already
read the export, and this layer takes Phase 21's word for what mattered.

``camera_movement_planner`` and ``cinematic_schema_v2`` are the V2 edit layer the
CLI and the cross-check thread through: they assign and validate the optional
``camera_movement`` blocks, purely and deterministically, over the locked V1
document.
"""

FORBIDDEN_ENGINE_ROOTS = frozenset(
    {"entities", "events", "memory", "simulation", "systems", "render"}
)
"""Engine subpackages Phase 22 must never import."""

NETWORK_MODULES = frozenset(
    {"http", "httpx", "openai", "requests", "socket", "ssl", "urllib", "urllib3", "anthropic"}
)
"""No runtime model call, and no network of any kind, ever."""

FORBIDDEN_IDENTIFIERS = re.compile(
    r"(?i).*("
    # Phase 23+: narration and prose
    r"narrat|voiceover|subtitle|caption|prose|sentence|paragraph|summar"
    r"|prompt|llm|gpt|embedding"
    # Phase 23+: audio, encoding, packaging
    r"|audio|music|soundtrack|encode_video|render_video|thumbnail|publish|package_episode"
    # camera MOTION is forbidden in V1 -- selection only
    r"|dolly|pan_speed|orbit|zoom|truck|crane|camera_path|camera_anim|interpolate_camera"
    r"|crossfade|dissolve"
    # citizen-level simulation
    r"|citizen|biograph|relationship|schedule|commute|workplace|household"
    r").*"
)
"""Names Phase 22 must not define.

Matched against *defined* names only -- functions, classes, arguments, assigned
names, and identifier-shaped string keys -- so that a docstring explaining what
this phase refuses cannot trip the guard.
"""

CAMERA_MUTATION_MARKERS = (
    ".location =",
    ".rotation_euler =",
    ".rotation_quaternion =",
    ".scale =",
    ".lens =",
    ".angle =",
    ".sensor_width =",
    ".sensor_height =",
    ".sensor_fit =",
    ".shift_x =",
    ".shift_y =",
    ".dof.",
    ".clip_start =",
    ".clip_end =",
    "matrix_world =",
    "keyframe_insert",
    "animation_data_create",
)
"""Source substrings that would mean a camera was moved, re-lensed, or animated."""

PHASE17_NAMES = ("motion_time_spec", "motion_plan", "apply_motion_plan")
"""Phase 17 modules. The timeline arrives as data; these are never imported."""


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


def bound_names(tree: ast.Module) -> set[str]:
    """Names the file actually binds -- no identifier-shaped string constants.

    Restating a field name in a required-keys set is not defining that field.
    The clock and emphasis guards below ask whether this layer *owns* a value,
    so they must look at real bindings only; the vocabulary guard keeps using
    :func:`defined_names`, where a string key genuinely is a declaration.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


# ------------------------------------------------------------- import reach


def test_every_guarded_module_exists() -> None:
    """A guard pointing at a missing file guards nothing."""
    for path in PHASE22_MODULES:
        assert path.exists(), f"{path} is guarded but missing"


def test_the_pure_layer_never_imports_blender() -> None:
    """The planner must be testable with Python and JSON alone."""
    for path in PURE_MODULES:
        roots = imported_roots(parse(path))
        assert "bpy" not in roots and "bmesh" not in roots, f"{path.name} imports Blender"


def test_the_pure_layer_never_imports_live_simulation() -> None:
    """The pure layer never imports live simulation."""
    for path in PURE_MODULES:
        for module in imported_modules(parse(path)):
            if not module.startswith("living_diorama"):
                continue
            parts = module.split(".")
            if len(parts) > 1 and parts[1] in FORBIDDEN_ENGINE_ROOTS:
                assert module in ALLOWED_ENGINE_MODULES, (
                    f"{path.name} imports simulation module {module}"
                )


def test_the_pure_layer_reaches_only_the_engine_modules_it_is_allowed() -> None:
    """The pure layer reaches only the engine modules it is allowed."""
    for path in PURE_MODULES:
        for module in imported_modules(parse(path)):
            if module.startswith("living_diorama"):
                assert module in ALLOWED_ENGINE_MODULES, (
                    f"{path.name} imports {module}, outside the cinematic layer's reach"
                )


def test_no_phase22_module_imports_phase17() -> None:
    """The timeline arrives as an argument, so Phase 17 cannot be reached at all.

    This is the strongest form the borrowing rule can take, and it is the rule
    Phase 19 established and Phase 20's boundary test already enforces.
    """
    for path in PHASE22_MODULES:
        roots = imported_roots(parse(path))
        for name in PHASE17_NAMES:
            assert name not in roots, f"{path.name} imports Phase 17 module {name}"


def test_the_blender_applier_imports_no_engine_package() -> None:
    """The catalogue arrives as data, so the applier stays a thin realization."""
    for path in BLENDER_MODULES:
        for module in imported_modules(parse(path)):
            assert not module.startswith("living_diorama"), f"{path.name} imports {module}"


def test_no_phase22_module_calls_a_model_or_the_network() -> None:
    """No LLM at runtime, and no API call of any kind."""
    for path in PHASE22_MODULES:
        offenders = imported_roots(parse(path)) & NETWORK_MODULES
        assert offenders == set(), f"{path.name} imports {sorted(offenders)}"


def test_no_phase22_module_imports_randomness_or_the_clock() -> None:
    """Either one would break byte-identical rebuilds."""
    for path in PHASE22_MODULES:
        roots = imported_roots(parse(path))
        for banned in ("random", "secrets", "time", "datetime", "uuid"):
            assert banned not in roots, f"{path.name} imports {banned}"


def test_only_the_command_line_entry_point_touches_the_filesystem() -> None:
    """The derivation is pure; reading a file is the CLI's job alone."""
    for path in PURE_MODULES:
        if path.parent == CLI:
            continue
        roots = imported_roots(parse(path))
        assert "pathlib" not in roots, f"{path.name} imports pathlib"
        assert "os" not in roots, f"{path.name} imports os"
        assert "open(" not in path.read_text(encoding="utf-8"), f"{path.name} opens a file"


# ------------------------------------------------------- camera immutability


def test_no_phase22_module_moves_relenses_or_animates_a_camera() -> None:
    """V1 selects among fixed anchors. The camera object is never touched."""
    for path in PHASE22_MODULES:
        source = path.read_text(encoding="utf-8")
        for marker in CAMERA_MUTATION_MARKERS:
            assert marker not in source, f"{path.name} contains {marker!r}"


def test_no_phase22_module_creates_a_camera() -> None:
    """Phase 22 never invents a viewpoint."""
    for path in PHASE22_MODULES:
        source = path.read_text(encoding="utf-8")
        for marker in ("cameras.new(", "bpy.data.cameras", "objects.new("):
            assert marker not in source, f"{path.name} creates a camera: {marker}"


def test_the_applier_touches_no_geometry_or_material() -> None:
    """The applier touches no geometry or material."""
    for path in BLENDER_MODULES:
        source = path.read_text(encoding="utf-8")
        for marker in ("bpy.data.meshes", "bpy.data.materials", "bpy.ops.mesh", "modifier"):
            assert marker not in source, f"{path.name} touches {marker}"


def test_the_applier_removes_only_markers_it_owns() -> None:
    """Somebody else's timeline state is left exactly as found."""
    source = (SCRIPTS / "apply_cinematic_direction.py").read_text(encoding="utf-8")
    assert "startswith(MARKER_PREFIX)" in source
    assert "timeline_markers.clear()" not in source


# ---------------------------------------------------------------- vocabulary


def test_no_phase22_module_defines_downstream_or_citizen_vocabulary() -> None:
    """No phase22 module defines downstream or citizen vocabulary."""
    for path in PHASE22_MODULES:
        for name in defined_names(parse(path)):
            assert not FORBIDDEN_IDENTIFIERS.fullmatch(name), (
                f"{path.name} defines {name!r}, which belongs to a later phase"
            )


def test_the_scope_guard_tolerates_the_words_phase22_owns() -> None:
    """A guard that blocks the phase's own vocabulary is useless."""
    for name in (
        "shot",
        "shot_id",
        "camera_anchor_id",
        "cut",
        "start_frame",
        "end_frame",
        "timeline",
        "establishing",
        "anchor",
        "emphasis",
        "reason_code",
        "marker",
    ):
        assert not FORBIDDEN_IDENTIFIERS.fullmatch(name), name


def test_no_phase22_module_redefines_the_phase17_clock() -> None:
    """Phase 17 owns time; this layer may reference it, never redefine it."""
    for path in PHASE22_MODULES:
        for name in bound_names(parse(path)):
            for banned in ("fps", "frame_rate", "start_hold_frames", "transition_frames"):
                assert name != banned, f"{path.name} defines {name!r}"


def test_no_phase22_module_redefines_story_emphasis() -> None:
    """Phase 21's meaning is frozen; this layer copies it, never recomputes it."""
    for path in PHASE22_MODULES:
        for name in bound_names(parse(path)):
            for banned in ("BEAT_KINDS", "EMPHASIS_LEVELS", "classify_fact", "classify_event"):
                assert name != banned, f"{path.name} defines {name!r}"


# ------------------------------------------- the guards actually bite


def test_the_blender_import_guard_catches_an_offender(tmp_path: Path) -> None:
    """The blender import guard catches an offender."""
    offender = tmp_path / "offender.py"
    offender.write_text("import bpy\n", encoding="utf-8")
    assert "bpy" in imported_roots(parse(offender))


def test_the_phase17_guard_catches_an_offender(tmp_path: Path) -> None:
    """The phase17 guard catches an offender."""
    offender = tmp_path / "offender.py"
    offender.write_text("import motion_time_spec\n", encoding="utf-8")
    assert "motion_time_spec" in imported_roots(parse(offender))


def test_the_simulation_guard_catches_an_offender(tmp_path: Path) -> None:
    """The simulation guard catches an offender."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "from living_diorama.systems.scarcity_system import ScarcitySystem\n",
        encoding="utf-8",
    )
    modules = imported_modules(parse(offender))
    assert not modules <= ALLOWED_ENGINE_MODULES


def test_the_network_guard_catches_an_offender(tmp_path: Path) -> None:
    """The network guard catches an offender."""
    offender = tmp_path / "offender.py"
    offender.write_text("import requests\n", encoding="utf-8")
    assert imported_roots(parse(offender)) & NETWORK_MODULES


def test_the_camera_mutation_guard_catches_a_move(tmp_path: Path) -> None:
    """The camera mutation guard catches a move."""
    offender = tmp_path / "offender.py"
    offender.write_text("cam.location = (1, 2, 3)\n", encoding="utf-8")
    source = offender.read_text(encoding="utf-8")
    assert any(marker in source for marker in CAMERA_MUTATION_MARKERS)


def test_the_camera_mutation_guard_catches_an_animation(tmp_path: Path) -> None:
    """The camera mutation guard catches an animation."""
    offender = tmp_path / "offender.py"
    offender.write_text("cam.keyframe_insert(data_path='location')\n", encoding="utf-8")
    source = offender.read_text(encoding="utf-8")
    assert any(marker in source for marker in CAMERA_MUTATION_MARKERS)


def test_the_camera_mutation_guard_leaves_a_pure_reader_alone(tmp_path: Path) -> None:
    """A guard that fires on innocent code would be turned off within a week."""
    innocent = tmp_path / "innocent.py"
    innocent.write_text(
        "def pick(cam):\n    return cam.name, cam.type, cam.data.lens\n",
        encoding="utf-8",
    )
    source = innocent.read_text(encoding="utf-8")
    assert not any(marker in source for marker in CAMERA_MUTATION_MARKERS)


def test_the_camera_creation_guard_catches_an_offender(tmp_path: Path) -> None:
    """The camera creation guard catches an offender."""
    offender = tmp_path / "offender.py"
    offender.write_text("data = bpy.data.cameras.new('CAM_NEW')\n", encoding="utf-8")
    source = offender.read_text(encoding="utf-8")
    assert "bpy.data.cameras" in source


def test_the_vocabulary_guard_catches_downstream_names(tmp_path: Path) -> None:
    """The vocabulary guard catches downstream names."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "def build_narration():\n    pass\n"
        "def crossfade():\n    pass\n"
        "audio_track = []\n"
        "citizen_id = 1\n"
        "def orbit_camera():\n    pass\n",
        encoding="utf-8",
    )
    caught = {
        name for name in defined_names(parse(offender)) if FORBIDDEN_IDENTIFIERS.fullmatch(name)
    }
    assert {"build_narration", "crossfade", "audio_track", "citizen_id", "orbit_camera"} <= caught


def test_the_vocabulary_guard_ignores_prose_in_a_docstring(tmp_path: Path) -> None:
    """The phase must be able to document what it refuses to become."""
    innocent = tmp_path / "innocent.py"
    innocent.write_text(
        '"""This layer writes no narration, no audio, and never orbits a camera."""\n'
        "def choose_anchor():\n    pass\n",
        encoding="utf-8",
    )
    caught = {
        name for name in defined_names(parse(innocent)) if FORBIDDEN_IDENTIFIERS.fullmatch(name)
    }
    assert caught == set()


def test_the_clock_guard_still_catches_a_real_definition(tmp_path: Path) -> None:
    """Refining the guard must not have defanged it."""
    offender = tmp_path / "offender.py"
    offender.write_text("fps = 30\n", encoding="utf-8")
    assert "fps" in bound_names(parse(offender))


def test_the_clock_guard_ignores_a_restated_field_name(tmp_path: Path) -> None:
    """Naming a field you copy is not owning it."""
    innocent = tmp_path / "innocent.py"
    innocent.write_text('KEYS = frozenset({"fps", "end_frame"})\n', encoding="utf-8")
    assert "fps" not in bound_names(parse(innocent))
