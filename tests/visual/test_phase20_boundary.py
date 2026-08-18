"""Import-boundary and scope guards for the Phase 20 state-response layer.

Phases 15 to 19 each own their own boundaries; these tests own Phase 20's:

* the spec, the plan and the motion plan stay PURE, so a state response can be
  derived, hashed and DISPROVED on a machine with no Blender at all;
* no Phase 20 file imports the engine, in either direction of the split;
* Phase 20 consumes earlier phases through their PUBLIC surface and never
  monkey-patches one;
* Phase 20 borrows the Phase 17 clock as DATA and never reaches into Phase 17's
  channel registry;
* Phase 20 reads simulation state and never writes it;
* Phase 20 declares none of the individual identity Phase 19 was told not to
  build, and neither does its config;
* and the Phase 20 structural runner executes every earlier suite before its
  own, so a state response can never be made to pass by weakening what it
  stands on.

WHAT MAKES PHASE 20's SCOPE GUARD DIFFERENT
-------------------------------------------
Phase 19's suite forbids its own modules from so much as naming ``fear`` or
``scarcity``, because a mobility layer that responded to world state would have
been stealing this phase. Phase 20 is the phase those names were reserved for,
so re-running that name scan here would forbid the phase from doing the one
thing it exists to do.

What replaces it is a scan for the DIRECTION OF FLOW. Phase 20 may read every
authoritative field it likes; what it may never do is write one back. A name
scan cannot tell those apart. An AST scan for an assignment through an
export-rooted subscript, and for a mutating method call on an export-derived
object, can -- and that is the guard this file carries.

Every scanner here is also made to fail on purpose, against synthetic files, in
``test_every_scope_guard_would_actually_bite``. A guard nobody has seen fail is
a guard nobody has tested.
"""

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "visual" / "blender" / "scripts"
RUNNER = REPO_ROOT / "visual" / "blender" / "tests" / "run_blender_tests_p20.py"
CONFIG = REPO_ROOT / "visual" / "blender" / "config" / "state_response_v1.json"

PURE_MODULES = (
    "state_response_spec.py",
    "state_response_plan.py",
    "state_response_motion_plan.py",
)

BLENDER_MODULES = (
    "apply_state_response.py",
    "apply_state_response_motion.py",
)

PHASE20_MODULES = PURE_MODULES + BLENDER_MODULES
"""Every file Phase 20 owns, named rather than globbed.

Hard-coded on purpose, exactly as the earlier phases do it: a glob would quietly
stop guarding a module somebody renamed, and would quietly start guarding
somebody else's. A list that has to be edited is a list somebody has to think
about.
"""

PRIOR_PHASE_MODULES = frozenset(
    {
        # Phase 15
        "scene_spec",
        "blender_runtime",
        "manifest_io",
        "proof_package",
        # Phase 16
        "road_graph",
        "urban_fabric",
        "city_ground",
        "production_spec",
        "style_profiles",
        "spatial_occupancy",
        # Phase 17
        "motion_time_spec",
        "motion_plan",
        # Phase 18
        "figure_kit",
        "population_presence_spec",
        "pedestrian_topology",
        "population_presence_plan",
        "population_proof_package",
        # Phase 19
        "mobility_spec",
        "vehicle_kit",
        "vehicle_lane_network",
        "pedestrian_mobility",
        "mobility_plan",
        "mobility_proof_package",
    }
)
"""Every earlier-phase module, by import name.

Phase 20 may import their PUBLIC names freely -- it is supposed to; a plan is
derived against ``scene_spec``'s own export loader. What it may not do is import
a private name or assign into one of these, which is the difference between
consuming a contract and reaching past it.

Not a claim that these files are frozen. Several have been rewritten by their
own owners under the remediation, and that is their business; these guards care
only about how Phase 20 reaches them.
"""


def imported_roots(path: Path) -> set[str]:
    """Top-level package names imported anywhere in one Python file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def phase20_paths() -> list[Path]:
    """Every guarded Phase 20 file, proved present before it is read."""
    paths = []
    for name in PHASE20_MODULES:
        path = SCRIPTS / name
        assert path.exists(), f"{name} is guarded but missing"
        paths.append(path)
    return paths


# ---------------------------------------------------------------------------
# Purity
# ---------------------------------------------------------------------------


def test_the_state_response_planning_layer_never_imports_blender() -> None:
    """A state response must be provable without Blender installed."""
    for name in PURE_MODULES:
        roots = imported_roots(SCRIPTS / name)
        assert "bpy" not in roots and "bmesh" not in roots, f"{name} imports Blender"


def test_no_phase20_module_imports_the_engine() -> None:
    """Presentation is downstream of the simulation and never inside it.

    Both halves are checked, not only the pure ones: the repo-wide rule at
    ``test_visual_runtime_boundary`` is that nothing under ``visual/blender``
    imports ``living_diorama``, and the Blender-side appliers are the files most
    tempted to ask the world a question directly.
    """
    for path in phase20_paths():
        assert "living_diorama" not in imported_roots(path), f"{path.name} imports the engine"


def test_the_runtime_consumes_the_pure_plan_rather_than_planning() -> None:
    """The applier instantiates. Deciding anything there would be deciding twice."""
    assert "state_response_plan" in imported_roots(SCRIPTS / "apply_state_response.py")
    motion_roots = imported_roots(SCRIPTS / "apply_state_response_motion.py")
    assert "state_response_motion_plan" in motion_roots


# ---------------------------------------------------------------------------
# Prior-phase boundary protection
# ---------------------------------------------------------------------------


def private_prior_phase_imports(path: Path) -> list[str]:
    """Every private name this file imports from an earlier phase's module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in PRIOR_PHASE_MODULES:
            found.extend(
                f"{node.module}.{alias.name}" for alias in node.names if alias.name.startswith("_")
            )
    return found


def prior_phase_assignments(path: Path) -> list[str]:
    """Every attribute this file assigns onto an earlier phase's module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id in PRIOR_PHASE_MODULES
            ):
                found.append(f"{target.value.id}.{target.attr}")
    return found


def test_phase20_never_imports_a_prior_phase_private_name() -> None:
    """Reaching into another phase's privates is reaching past its contract."""
    for path in phase20_paths():
        assert private_prior_phase_imports(path) == [], f"{path.name} imports a private name"


def test_phase20_never_assigns_into_a_prior_phase_module() -> None:
    """Monkey-patching an earlier phase edits it from outside its own tests.

    The objection is not that the module is unchangeable -- several have been
    changed, by their owners. It is that an assignment from HERE changes
    behaviour the owning phase's own suite would never see, so the two phases
    stop agreeing about what the earlier one does.
    """
    for path in phase20_paths():
        assert prior_phase_assignments(path) == [], f"{path.name} assigns into a prior phase"


def test_phase20_borrows_the_phase17_clock_as_data_and_never_imports_it() -> None:
    """The timeline arrives as an argument, so Phase 17 cannot be reached at all.

    This is the strongest form the borrowing rule can take. Phase 20 resolves
    its windows against the object ``motion_time_spec.resolve_timeline``
    returns, but never imports that module, so there is no name through which it
    could read Phase 17's channel registry, extend it, or come to depend on a
    detail Phase 17 is still free to change.
    """
    for path in phase20_paths():
        assert "motion_time_spec" not in imported_roots(path), f"{path.name} imports Phase 17"


def test_phase20_never_names_the_phase17_channel_registry() -> None:
    """Phase 17's channel list is Phase 17's, and Phase 20 has its own.

    One honest exception, and it is checked rather than waved through: Phase 20's
    own spec declares a constant of that name for its own two channels. Every
    other Phase 20 file must be silent about it, and since none of them imports
    ``motion_time_spec`` at all, no occurrence anywhere here can be Phase 17's.

    Phase 19's suite pins the same rule with a flat "never appears" scan, which
    is available to it because Phase 19 has no channel registry of its own.
    """
    naming = [
        path.name
        for path in phase20_paths()
        if "SUPPORTED_CHANNELS" in path.read_text(encoding="utf-8")
    ]
    assert naming == ["state_response_spec.py"], f"unexpected channel registry in {naming}"


def test_the_phase20_runner_runs_every_earlier_suite_first() -> None:
    """A state response cannot be made to pass by weakening what came before it.

    Ordering, not immutability: the earlier suites grow as their own phases are
    corrected, and that is fine. What must never happen is Phase 20 reporting
    green having skipped them.
    """
    if not RUNNER.exists():
        pytest.skip(f"{RUNNER.name} does not exist yet; the ordering rule has nothing to read")
    source = RUNNER.read_text(encoding="utf-8")
    order = [source.index(f'"phase{number}"') for number in range(15, 21)]
    assert order == sorted(order), "the structural suites are not in phase order"


# ---------------------------------------------------------------------------
# Direction of flow: Phase 20 reads the world and never writes it
# ---------------------------------------------------------------------------

EXPORT_ROOTS = frozenset({"export", "render_export", "before_export", "after_export"})
"""The names by which an authoritative Render Export document enters Phase 20.

The scan is seeded from these and follows the data, rather than listing the
fields nobody may touch. Listing fields would be the Phase 19 mistake in a new
costume: ``scarcity`` is exactly what Phase 20 is for.
"""

PASS_THROUGH_CALLS = frozenset({"enumerate", "iter", "list", "reversed", "sorted", "tuple", "zip"})
PASS_THROUGH_METHODS = frozenset({"get", "items", "keys", "values"})
"""Calls that hand back the same data under another name, so taint survives them.

Without these, ``for entry in enumerate(export["world"]["districts"])`` would
launder the export in one line and the guard would see nothing.
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
        "reverse",
        "setdefault",
        "sort",
        "update",
    }
)
"""Methods that change the object they are called on rather than returning a new one."""


def _flows_from_export(node: ast.expr, tainted: set[str]) -> bool:
    """Whether this expression is the export document, or a piece of it."""
    if isinstance(node, ast.Name):
        return node.id in tainted
    if isinstance(node, (ast.Subscript, ast.Attribute)):
        return _flows_from_export(node.value, tainted)
    if isinstance(node, ast.Starred):
        return _flows_from_export(node.value, tainted)
    if isinstance(node, (ast.Tuple, ast.List)):
        return any(_flows_from_export(element, tainted) for element in node.elts)
    if isinstance(node, ast.Call):
        function = node.func
        if isinstance(function, ast.Name) and function.id in PASS_THROUGH_CALLS:
            return any(_flows_from_export(argument, tainted) for argument in node.args)
        if isinstance(function, ast.Attribute) and function.attr in PASS_THROUGH_METHODS:
            return _flows_from_export(function.value, tainted)
    return False


def _bound_names(target: ast.expr) -> set[str]:
    """Every plain name one assignment or loop target binds."""
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return {name for element in target.elts for name in _bound_names(element)}
    if isinstance(target, ast.Starred):
        return _bound_names(target.value)
    return set()


def export_derived_names(tree: ast.AST) -> set[str]:
    """Every name in this file that holds the export document or a piece of it.

    Iterated to a fixed point rather than walked once, because the AST is not
    execution order: ``entries = world["districts"]`` can be visited before the
    line that made ``world`` the export's own.
    """
    tainted = set(EXPORT_ROOTS)
    for _ in range(8):
        before = set(tainted)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                source, targets = node.value, list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                source, targets = node.value, [node.target]
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
                source, targets = node.iter, [node.target]
            else:
                continue
            if source is not None and _flows_from_export(source, tainted):
                for target in targets:
                    tainted |= _bound_names(target)
        if tainted == before:
            break
    return tainted


def simulation_writes(source: str) -> list[str]:
    """Every place this source writes back into the export document.

    Two shapes, because there are two ways to do it: assigning through a
    subscript of an export-derived object, and calling a mutating method on one.
    """
    tree = ast.parse(source)
    tainted = export_derived_names(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        elif isinstance(node, ast.Delete):
            targets = list(node.targets)
        for target in targets:
            if isinstance(target, ast.Subscript) and _flows_from_export(target.value, tainted):
                found.append(f"line {node.lineno}: writes through an export-rooted subscript")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in MUTATORS
            and _flows_from_export(node.func.value, tainted)
        ):
            found.append(f"line {node.lineno}: calls {node.func.attr}() on export-derived data")
    return found


def test_phase20_never_writes_the_simulation_state_it_reads() -> None:
    """Presentation reads. A layer that wrote back would be authoring the world.

    The scan follows the export document through subscripts, attributes and the
    calls that hand it back unchanged, then reports any assignment or mutating
    call that lands on it. Reading ``fear`` or ``scarcity`` is not merely
    allowed here, it is the phase's subject -- so this is a test of the
    direction of flow, and a name scan would have been the wrong instrument.
    """
    for path in phase20_paths():
        writes = simulation_writes(path.read_text(encoding="utf-8"))
        assert writes == [], f"{path.name} writes simulation state: {writes}"


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------

FORBIDDEN_IDENTIFIERS = re.compile(
    r"\b("
    r"citizen_name|resident_name|person_name|full_name|given_name|surname|"
    r"family_id|household|kinship|parent_of|child_of|spouse|relative|"
    r"workplace|employer|job_title|occupation|commute|errand|"
    r"schedule|timetable|itinerary|daily_routine|appointment|"
    r"behaviour_tree|behavior_tree|decision_tree|utility_ai|steering_agent|"
    r"npc|agent_brain|blackboard|"
    r"passenger|driver_name|vehicle_owner|licence_plate|license_plate|registration_number"
    r")\b",
    re.IGNORECASE,
)
"""Names Phase 20 must not DEFINE, copied verbatim from Phase 19's guard.

Copied rather than imported, so that Phase 19's suite and this one can be edited
independently without one silently relaxing the other. Every name here would be
a claim about an individual, a relationship, a job, a plan or an autonomous
decision -- none of which the simulation holds. A record stone is one durable
fact the ENGINE decided to remember, and a district's air is that district's
aggregate condition; neither is a person, and the code cannot say otherwise.
"""


def defined_names(source: str) -> set[str]:
    """Every name this source DEFINES: functions, classes, assignments, arguments.

    Definitions rather than every token, so a docstring explaining that Phase 20
    holds no schedules does not read to the scanner exactly like a schedule.
    """
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        # String KEYS are how a JSON-shaped plan names its own fields, so a
        # forbidden field name has to be caught here too -- but only where it is a
        # plain identifier-shaped literal, never inside prose.
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and re.fullmatch(r"[a-z][a-z0-9_]{2,}", node.value)
        ):
            names.add(node.value)
    return names


def test_phase20_defines_no_individual_identity() -> None:
    """A reading of aggregate state is not a claim about a person.

    Phase 19's ban is re-asserted over Phase 20's own files rather than assumed
    to have carried over: this is the phase that finally connects the simulation
    to what the city looks like, which makes it the phase most able to invent a
    resident to explain a number.
    """
    for path in phase20_paths():
        for defined in sorted(defined_names(path.read_text(encoding="utf-8"))):
            assert not FORBIDDEN_IDENTIFIERS.fullmatch(defined), f"{path.name} defines {defined!r}"


def test_the_scope_guard_tolerates_the_words_phase20_owns() -> None:
    """Fear, scarcity and memory are Phase 20's subject, not its scope creep.

    The mirror image of the guard above, and the reason Phase 19's simulation
    variable scan is NOT repeated here: every one of these would be a violation
    one phase ago and is the whole point of this one.
    """
    for word in (
        "fear",
        "trust",
        "scarcity",
        "institutional_pressure",
        "district_air",
        "memory_record",
        "fact_type",
        "response_value",
        "source_value",
        "record_stone",
    ):
        assert not FORBIDDEN_IDENTIFIERS.fullmatch(word), word


def test_the_config_declares_no_forbidden_policy() -> None:
    """The spec has nowhere to put a citizen, and this proves it has not grown one.

    Raw text, not parsed JSON: a forbidden name would be just as much a policy
    sitting in a comment, a statement string or a key nobody reads yet.
    """
    source = CONFIG.read_text(encoding="utf-8")
    for match in FORBIDDEN_IDENTIFIERS.finditer(source):
        raise AssertionError(f"the state response spec names {match.group(0)!r}")


# ---------------------------------------------------------------------------
# The guards, made to fail on purpose
# ---------------------------------------------------------------------------


def test_every_scope_guard_would_actually_bite(tmp_path: Path) -> None:
    """A guard nobody has seen fail is a guard nobody has tested.

    Four synthetic offenders, one per scanner. Without this, every guard above
    would pass just as happily if its pattern had been mistyped, its module list
    emptied, or its taint analysis silently stopped propagating -- which is the
    ordinary way a boundary test rots into decoration.
    """
    identity = tmp_path / "identity.py"
    identity.write_text(
        "def household(npc):\n    schedule = {'commute': 1}\n    return schedule\n",
        encoding="utf-8",
    )
    caught = {
        name
        for name in defined_names(identity.read_text(encoding="utf-8"))
        if FORBIDDEN_IDENTIFIERS.fullmatch(name)
    }
    assert {"household", "npc", "schedule", "commute"} <= caught

    writer = tmp_path / "writer.py"
    writer.write_text(
        "def calm(export):\n"
        "    world = export['world']\n"
        "    for index, district in enumerate(world['districts']):\n"
        "        district['fear'] = 0.0\n"
        "    return index\n",
        encoding="utf-8",
    )
    writes = simulation_writes(writer.read_text(encoding="utf-8"))
    assert len(writes) == 1, writes
    assert "subscript" in writes[0]

    mutator = tmp_path / "mutator.py"
    mutator.write_text(
        "def forget(export):\n    export.get('memory').get('facts').clear()\n",
        encoding="utf-8",
    )
    assert "clear()" in "".join(simulation_writes(mutator.read_text(encoding="utf-8")))

    reader = tmp_path / "reader.py"
    reader.write_text(
        "def read(export):\n"
        "    plan = {}\n"
        "    for district in export['world']['districts']:\n"
        "        plan[district['id']] = district['scarcity']\n"
        "    return plan\n",
        encoding="utf-8",
    )
    assert simulation_writes(reader.read_text(encoding="utf-8")) == [], (
        "the write scan fired on a pure read; a guard that cannot tell reading "
        "from writing would force Phase 20 to stop doing its job"
    )


def test_the_prior_phase_guards_would_actually_bite(tmp_path: Path) -> None:
    """The import and monkey-patch scanners are made to fail too.

    Both scanners return empty lists over the real sources, which is exactly
    what a scanner looking at the wrong node type, or holding an empty module
    list, would also return.
    """
    reacher = tmp_path / "reacher.py"
    reacher.write_text(
        "import scene_spec\n"
        "from scene_spec import _require_object, load_render_export\n"
        "scene_spec.load_render_export = None\n",
        encoding="utf-8",
    )
    assert private_prior_phase_imports(reacher) == ["scene_spec._require_object"]
    assert prior_phase_assignments(reacher) == ["scene_spec.load_render_export"]

    innocent = tmp_path / "innocent.py"
    innocent.write_text(
        "from scene_spec import load_render_export\n_local = load_render_export\n",
        encoding="utf-8",
    )
    assert private_prior_phase_imports(innocent) == []
    assert prior_phase_assignments(innocent) == []
