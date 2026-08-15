"""Contract tests for the Phase 19 proof package inventory.

Pure pytest -- no Blender. Every package here is built in a temporary directory
and then tampered with on purpose, so the suite proves the REFUSALS rather than
that one good package verifies.

Five failure modes have to be decidable rather than judgement calls: a missing
member, an unenumerated extra member, a wrong hash, a wrong size, and a manifest
that points at an artifact the package does not carry.

The gate's own refusals are exercised here too, for the same reason: a proof
that cannot fail proves nothing. Each of these was once a check that could not
fail -- a rendered frame nobody required, a contact sheet that shrank in
silence, an envelope verdict nobody read, a suite that passed by running no
tests, and two inventory totals compared against the inventory that declared
them.
"""

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "visual" / "blender" / "scripts"
PRODUCER = SCRIPTS_DIR / "produce_mobility_proof.py"


def _load(name: str):
    """Import one pure visual module the same way Blender does: by sibling name."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


package = _load("mobility_proof_package")
proof_package = _load("proof_package")


@pytest.fixture(name="built")
def built_fixture(tmp_path: Path) -> Path:
    """A small but complete package: a blend, an export, a plan and a manifest."""
    (tmp_path / "living_diorama_phase19_daily_life.blend").write_bytes(b"blend-bytes")
    (tmp_path / "render_export_before.json").write_text('{"format": "x"}', encoding="utf-8")
    (tmp_path / "phase19_mobility_plan.json").write_text('{"format": "plan"}', encoding="utf-8")
    (tmp_path / "phase19_daily_life_cycle.mp4").write_bytes(b"video-bytes")
    manifest = {
        "artifact": "living_diorama_phase19_daily_life_mobility",
        "schema_version": 1,
        "blend": {
            "path": "living_diorama_phase19_daily_life.blend",
            "sha256": _digest(tmp_path / "living_diorama_phase19_daily_life.blend"),
            "bytes": 11,
        },
        "source_export": _reference(tmp_path / "render_export_before.json"),
        "mobility_plan": _reference(tmp_path / "phase19_mobility_plan.json"),
    }
    (tmp_path / "phase19_mobility_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    package.write_mobility_inventory(tmp_path)
    return tmp_path


def _digest(path: Path) -> str:
    """SHA-256 of one file."""
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reference(path: Path) -> dict[str, str | int]:
    """One complete manifest reference to a packaged file."""
    return {"path": path.name, "sha256": _digest(path), "bytes": path.stat().st_size}


def test_a_complete_package_verifies(built: Path) -> None:
    """The happy path, so the refusals below mean something."""
    report = package.verify_mobility_inventory(built)
    assert report["verified"] is True
    assert report["member_count"] == 5
    assert set(report["artifact_references"].values()) == {
        "living_diorama_phase19_daily_life.blend",
        "render_export_before.json",
        "phase19_mobility_plan.json",
    }


def test_the_inventory_names_itself_and_nothing_else_hides(built: Path) -> None:
    """Every member except the inventory is enumerated with size and hash."""
    inventory = json.loads((built / package.INVENTORY_NAME).read_text(encoding="utf-8-sig"))
    assert package.INVENTORY_NAME not in inventory["members"]
    for entry in inventory["members"].values():
        assert entry["sha256"] and entry["bytes"] > 0


def test_a_missing_member_is_refused(built: Path) -> None:
    """A package that lost a file is not the package that was inventoried."""
    (built / "phase19_daily_life_cycle.mp4").unlink()
    with pytest.raises(proof_package.ProofPackageError, match="does not carry"):
        package.verify_mobility_inventory(built)


def test_an_unenumerated_extra_member_is_refused(built: Path) -> None:
    """A file nobody hashed could have been added, altered or smuggled in."""
    (built / "extra.png").write_bytes(b"extra")
    with pytest.raises(proof_package.ProofPackageError, match="never hashed"):
        package.verify_mobility_inventory(built)


def test_a_mutated_member_is_refused(built: Path) -> None:
    """Same size, different bytes -- the hash is what catches this."""
    (built / "phase19_daily_life_cycle.mp4").write_bytes(b"VIDEO-bytes")
    with pytest.raises(proof_package.ProofPackageError, match="hashes to"):
        package.verify_mobility_inventory(built)


def test_a_resized_member_is_refused(built: Path) -> None:
    """Byte size is checked before the hash, so a truncation is named as one."""
    (built / "phase19_daily_life_cycle.mp4").write_bytes(b"short")
    with pytest.raises(proof_package.ProofPackageError, match="bytes"):
        package.verify_mobility_inventory(built)


def test_a_required_member_that_is_absent_is_refused(built: Path) -> None:
    """The gate names what a package must carry, and the verifier holds it to it."""
    with pytest.raises(proof_package.ProofPackageError, match="missing required members"):
        package.verify_mobility_inventory(built, required=("phase19_contact_sheet.png",))


def test_a_dangling_blend_reference_is_refused(tmp_path: Path) -> None:
    """A manifest may not name a world nobody can open."""
    export = tmp_path / "render_export_before.json"
    plan = tmp_path / "phase19_mobility_plan.json"
    export.write_text("{}", encoding="utf-8")
    plan.write_text("{}", encoding="utf-8")
    (tmp_path / "phase19_mobility_manifest.json").write_text(
        json.dumps(
            {
                "artifact": "living_diorama_phase19_daily_life_mobility",
                "schema_version": 1,
                "blend": {"path": "nowhere.blend", "sha256": "0" * 64, "bytes": 1},
                "source_export": _reference(export),
                "mobility_plan": _reference(plan),
            }
        ),
        encoding="utf-8",
    )
    package.write_mobility_inventory(tmp_path)
    with pytest.raises(proof_package.ProofPackageError, match="does not carry"):
        package.verify_mobility_inventory(tmp_path)


def test_a_dangling_plan_reference_is_refused(tmp_path: Path) -> None:
    """A manifest may not name a plan a reviewer cannot recompute from."""
    export = tmp_path / "render_export_before.json"
    blend = tmp_path / "living_diorama_phase19_daily_life.blend"
    export.write_text("{}", encoding="utf-8")
    blend.write_bytes(b"blend")
    (tmp_path / "phase19_mobility_manifest.json").write_text(
        json.dumps(
            {
                "artifact": "living_diorama_phase19_daily_life_mobility",
                "schema_version": 1,
                "blend": _reference(blend),
                "source_export": _reference(export),
                "mobility_plan": {
                    "path": "absent_plan.json",
                    "sha256": "0" * 64,
                    "bytes": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    package.write_mobility_inventory(tmp_path)
    with pytest.raises(proof_package.ProofPackageError, match="does not carry"):
        package.verify_mobility_inventory(tmp_path)


def test_a_forged_reference_hash_is_refused(built: Path) -> None:
    """A manifest recording a different hash than the package holds is refused."""
    manifest_path = built / "phase19_mobility_manifest.json"
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["blend"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    package.write_mobility_inventory(built)
    with pytest.raises(proof_package.ProofPackageError, match="different hash"):
        package.verify_mobility_inventory(built)


def test_a_manifest_missing_one_of_the_three_references_is_refused(built: Path) -> None:
    """Omitting a reference object may not make the obligation disappear."""
    manifest_path = built / "phase19_mobility_manifest.json"
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document.pop("source_export")
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    package.write_mobility_inventory(built)
    with pytest.raises(proof_package.ProofPackageError, match="exactly three complete"):
        package.verify_mobility_inventory(built)


def test_an_artifact_reference_without_hash_or_size_is_refused(built: Path) -> None:
    """A path alone is not evidence that the packaged bytes are the cited bytes."""
    manifest_path = built / "phase19_mobility_manifest.json"
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["mobility_plan"] = {"path": "phase19_mobility_plan.json"}
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    package.write_mobility_inventory(built)
    with pytest.raises(proof_package.ProofPackageError, match="exactly three complete"):
        package.verify_mobility_inventory(built)


def test_the_verified_package_resolves_exactly_three_complete_references(built: Path) -> None:
    """The happy path pins the cardinality as well as the target names."""
    report = package.verify_mobility_inventory(built)
    assert len(report["artifact_references"]) == package.EXPECTED_ARTIFACT_REFERENCE_COUNT == 3


def test_a_missing_inventory_is_refused(tmp_path: Path) -> None:
    """A package with no inventory has made no claim at all."""
    (tmp_path / "only.png").write_bytes(b"x")
    with pytest.raises(proof_package.ProofPackageError, match="no inventory"):
        package.verify_mobility_inventory(tmp_path)


def test_an_earlier_phases_inventory_is_refused(built: Path) -> None:
    """A Phase 19 package declaring a Phase 18 format is lying about what it is."""
    path = built / package.INVENTORY_NAME
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    document["artifact"] = "living_diorama_phase18_proof_package"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(proof_package.ProofPackageError, match="declares artifact"):
        package.verify_mobility_inventory(built)


def test_a_wrong_inventory_schema_version_is_refused(built: Path) -> None:
    """A schema this verifier does not speak may not borrow its PASS."""
    path = built / package.INVENTORY_NAME
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    document["schema_version"] = package.MOBILITY_PACKAGE_SCHEMA_VERSION + 1
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(proof_package.ProofPackageError, match="schema_version"):
        package.verify_mobility_inventory(built)


def test_an_empty_package_is_refused(tmp_path: Path) -> None:
    """There is nothing to inventory."""
    with pytest.raises(proof_package.ProofPackageError):
        package.write_mobility_inventory(tmp_path)


def test_an_earlier_phases_manifest_is_an_ordinary_member(built: Path) -> None:
    """A Phase 17 inventory inside a Phase 19 package must still be hashed.

    The borrowed helper hides its own inventory filename. If Phase 19 used it
    unchanged, a file with that name could be added or altered without ever
    being hashed -- so Phase 19 enumerates its members itself.
    """
    (built / "phase17_proof_package_manifest.json").write_text("{}", encoding="utf-8")
    names = {member.name for member in package.mobility_members(built)}
    assert "phase17_proof_package_manifest.json" in names
    with pytest.raises(proof_package.ProofPackageError, match="never hashed"):
        package.verify_mobility_inventory(built)


def _load_gate():
    """Import the gate runner by path: it lives beside the scripts, not inside them."""
    location = REPO_ROOT / "visual" / "blender" / "run_phase19_checks.py"
    spec = importlib.util.spec_from_file_location("run_phase19_checks", location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _producer_output_names(constant: str) -> list[str]:
    """Every filename one producer constant names, read out of its source.

    ``produce_mobility_proof`` imports ``bpy``, so pytest reads its constants
    with :mod:`ast` rather than importing the module.
    """
    tree = ast.parse(PRODUCER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(name, ast.Name) and name.id == constant for name in node.targets):
            continue
        return [
            value.value
            for entry in node.value.elts
            for value in (entry.elts if isinstance(entry, ast.Tuple) else [entry])
            if isinstance(value, ast.Constant) and str(value.value).endswith((".png", ".mp4"))
        ]
    raise AssertionError(f"produce_mobility_proof declares no {constant}")


def _producer_function(name: str) -> ast.FunctionDef:
    """One function of the producer, as a syntax tree."""
    tree = ast.parse(PRODUCER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"produce_mobility_proof defines no {name}")


def _ordered_calls(function: ast.FunctionDef) -> list[str]:
    """Every call in one producer function, as dotted names, in source order.

    ``ast.walk`` promises no traversal order, so the calls are sorted by their
    position in the file -- what a test about ORDERING has to stand on.
    """
    calls: list[tuple[int, int, str]] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        parts: list[str] = []
        func = node.func
        while isinstance(func, ast.Attribute):
            parts.append(func.attr)
            func = func.value
        if isinstance(func, ast.Name):
            parts.append(func.id)
            calls.append((node.lineno, node.col_offset, ".".join(reversed(parts))))
    return [name for _, _, name in sorted(calls)]


def _structural_output(counts: dict[str, int]) -> str:
    """One structural-runner transcript reporting the given per-phase pass counts."""
    lines = [
        f"LD_BLENDER_TESTS_{phase}: {passed} passed, 0 failed" for phase, passed in counts.items()
    ]
    lines.append(f"LD_BLENDER_TESTS_P19: {sum(counts.values())} passed, 0 failed")
    return "\n".join(lines) + "\n"


def test_the_package_must_carry_the_export_its_manifest_names() -> None:
    """A proof must CARRY the export it was rendered from, not merely cite it.

    The first complete gate run failed exactly here: the manifest named
    ``render_export_before.json`` as its source, the proof directory did not
    hold a copy, and the inventory refused the dangling reference. The fix
    belongs in the producer, so this pins the requirement -- dropping the export
    from the gate's required list to make the failure go away now breaks a test.
    """
    gate = _load_gate()
    assert gate.EXPORT_NAMES[0] == "render_export_before.json"
    assert gate.EXPORT_NAMES[0] in gate.REQUIRED_MEMBERS
    for clip in (
        "phase19_daily_life_cycle.mp4",
        "phase19_pedestrian_gait_verify.mp4",
        "phase19_vehicle_motion_verify.mp4",
    ):
        assert clip in gate.REQUIRED_MEMBERS, clip


# ---------------------------------------------------------------------------
# A rendered artifact nobody required
# ---------------------------------------------------------------------------


def test_the_gate_requires_every_frame_and_clip_the_producer_renders() -> None:
    """A frame the render loop produces and no list requires can go missing unnoticed.

    The gait and traffic context frames were rendered, named in the manifest,
    and absent from the gate's required members, so losing either cost nothing.
    Reading the producer's own constants means a still added later is required
    by the same act that creates it.
    """
    gate = _load_gate()
    produced = _producer_output_names("STILLS") + _producer_output_names("CLIPS")
    assert "phase19_gait_context.png" in produced
    assert "phase19_traffic_context.png" in produced
    unrequired = [name for name in produced if name not in gate.REQUIRED_MEMBERS]
    assert unrequired == [], unrequired


def test_a_package_missing_the_close_up_context_frames_is_refused(built: Path) -> None:
    """The two frames that make sliding feet and crabbing wheels findable are required.

    The small package the fixture builds carries neither, so the gate's own
    required list has to refuse it by name. Dropping either frame from that list
    to make a red run green now breaks this test.
    """
    gate = _load_gate()
    with pytest.raises(proof_package.ProofPackageError) as refusal:
        package.verify_mobility_inventory(built, required=gate.REQUIRED_MEMBERS)
    assert "phase19_gait_context.png" in str(refusal.value)
    assert "phase19_traffic_context.png" in str(refusal.value)


# ---------------------------------------------------------------------------
# A contact sheet that shrank in silence
# ---------------------------------------------------------------------------


def test_a_contact_sheet_frame_the_render_never_produced_is_refused(tmp_path: Path) -> None:
    """A sheet told to show six frames may not quietly show five."""
    (tmp_path / "phase19_start.png").write_bytes(b"png")
    with pytest.raises(proof_package.ProofPackageError, match="never produced"):
        package.require_contact_sheet_frames(
            tmp_path, ("phase19_start.png", "phase19_gait_context.png")
        )


def test_a_contact_sheet_with_no_frames_at_all_is_refused(tmp_path: Path) -> None:
    """An empty frame list is a sheet that shows nothing and refuses nothing."""
    with pytest.raises(proof_package.ProofPackageError, match="must be told"):
        package.require_contact_sheet_frames(tmp_path, ())


def test_a_directory_named_like_a_frame_is_refused(tmp_path: Path) -> None:
    """Existence is not enough: a tile has to be a file the loader can read."""
    (tmp_path / "phase19_start.png").mkdir()
    with pytest.raises(proof_package.ProofPackageError, match="never produced"):
        package.require_contact_sheet_frames(tmp_path, ("phase19_start.png",))


def test_every_present_frame_resolves_in_the_order_it_was_given(tmp_path: Path) -> None:
    """The happy path, in sheet order, so the refusals above mean something."""
    for name in ("b.png", "a.png"):
        (tmp_path / name).write_bytes(b"png")
    resolved = package.require_contact_sheet_frames(tmp_path, ("b.png", "a.png"))
    assert [path.name for path in resolved] == ["b.png", "a.png"]


# ---------------------------------------------------------------------------
# A stale numbered clip that replaced a fresh render
# ---------------------------------------------------------------------------


def test_clip_render_starts_with_a_clean_stem(tmp_path: Path) -> None:
    """An aborted numbered clip and an old canonical clip are both removed."""
    target = tmp_path / "phase19_daily_life_cycle.mp4"
    stale = tmp_path / "phase19_daily_life_cycle0001-0193.mp4"
    unrelated = tmp_path / "phase19_vehicle_motion_verify0001-0193.mp4"
    target.write_bytes(b"old canonical")
    stale.write_bytes(b"aborted")
    unrelated.write_bytes(b"other clip")

    package.clear_clip_outputs(target)

    assert not target.exists()
    assert not stale.exists()
    assert unrelated.read_bytes() == b"other clip"


def test_exactly_one_fresh_numbered_clip_is_canonicalized(tmp_path: Path) -> None:
    """The one file Blender emitted becomes the stable package member."""
    target = tmp_path / "phase19_daily_life_cycle.mp4"
    produced = tmp_path / "phase19_daily_life_cycle0001-0193.mp4"
    payload = b"video" * 300
    produced.write_bytes(payload)

    assert package.finalize_clip_output(target) == target
    assert target.read_bytes() == payload
    assert not produced.exists()


def test_ambiguous_clip_outputs_are_refused(tmp_path: Path) -> None:
    """Filename order may never choose between fresh and stale video files."""
    target = tmp_path / "phase19_daily_life_cycle.mp4"
    (tmp_path / "phase19_daily_life_cycle0001-0192.mp4").write_bytes(b"a" * 2048)
    (tmp_path / "phase19_daily_life_cycle0001-0193.mp4").write_bytes(b"b" * 2048)

    with pytest.raises(proof_package.ProofPackageError, match="produced 2 video files"):
        package.finalize_clip_output(target)


def test_a_render_that_emitted_no_video_at_all_is_refused(tmp_path: Path) -> None:
    """A render whose output never landed is refused as loudly as an ambiguous one.

    Zero candidates is what a crashed encoder or a wrong output path leaves
    behind, and precisely because the stem was cleared first, an empty result
    must stop the run rather than let the packaging step discover the hole.
    """
    target = tmp_path / "phase19_daily_life_cycle.mp4"
    with pytest.raises(proof_package.ProofPackageError, match="produced 0 video files"):
        package.finalize_clip_output(target)


def test_container_header_sized_clip_is_refused(tmp_path: Path) -> None:
    """A killed render's tiny MP4 stub is not valid proof evidence."""
    target = tmp_path / "phase19_daily_life_cycle.mp4"
    (tmp_path / "phase19_daily_life_cycle0001-0193.mp4").write_bytes(b"stub" * 12)

    with pytest.raises(proof_package.ProofPackageError, match="only 48 bytes"):
        package.finalize_clip_output(target)


def test_the_producer_composes_its_sheet_through_the_refusal() -> None:
    """A refusal the producer never calls is a refusal that can never fire.

    Also checks that no ``continue`` survives in the composer, which is how the
    frame was skipped in the first place.
    """
    function = _producer_function("compose_contact_sheet")
    called = {
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "require_contact_sheet_frames" in called
    assert not [node for node in ast.walk(function) if isinstance(node, ast.Continue)]


def test_the_clip_renderer_clears_before_rendering_and_finalizes_after() -> None:
    """The clear-then-finalize pairing IS the stale-clip defense, so it is pinned.

    ``clear_clip_outputs`` before the render is what stops an aborted numbered
    stub from surviving beside a fresh clip, and ``finalize_clip_output`` after
    it is what refuses an ambiguous or missing result. Either call dropped, or
    the order reversed, and a stale video can ride filename order into the
    package while the inventory hashes it faithfully -- so this test reads the
    producer's own source, the way the contact-sheet refusal above is pinned.
    """
    calls = _ordered_calls(_producer_function("render_clip"))
    assert "clear_clip_outputs" in calls
    assert "bpy.ops.render.render" in calls
    assert "finalize_clip_output" in calls
    assert calls.index("clear_clip_outputs") < calls.index("bpy.ops.render.render")
    assert calls.index("bpy.ops.render.render") < calls.index("finalize_clip_output")


# ---------------------------------------------------------------------------
# An envelope verdict nobody read
# ---------------------------------------------------------------------------


def _contained_contracts(gate) -> dict[str, dict]:
    """A complete five-archetype envelope block for gate-level tests."""
    return {name: {"contained": True, "escaped": []} for name in sorted(gate.VEHICLE_ARCHETYPES)}


def test_an_escaped_vehicle_component_is_refused() -> None:
    """A component outside the reservation the city's lanes were planned from."""
    gate = _load_gate()
    contracts = _contained_contracts(gate)
    contracts["van"] = {
        "contained": False,
        "escaped": ["mirror_left", "wheel_front_right"],
    }
    manifest = {"vehicles": {"envelope_contracts": contracts}}
    with pytest.raises(RuntimeError, match="escape their reserved planning envelope"):
        gate._require_contained_envelopes(manifest)


def test_an_escape_list_that_contradicts_its_own_verdict_is_refused() -> None:
    """``contained: true`` beside a non-empty ``escaped`` is not a passing verdict."""
    gate = _load_gate()
    contracts = _contained_contracts(gate)
    contracts["coupe"] = {"contained": True, "escaped": ["arch_rear_left"]}
    manifest = {"vehicles": {"envelope_contracts": contracts}}
    with pytest.raises(RuntimeError, match="escape their reserved planning envelope"):
        gate._require_contained_envelopes(manifest)


def test_a_manifest_with_no_envelope_contracts_is_refused() -> None:
    """A check with nothing to read passes everything, which is the same defect."""
    gate = _load_gate()
    with pytest.raises(RuntimeError, match="no vehicle envelope contracts"):
        gate._require_contained_envelopes({"vehicles": {"envelope_contracts": {}}})
    with pytest.raises(RuntimeError, match="no vehicle envelope contracts"):
        gate._require_contained_envelopes({"vehicles": {}})


def test_a_malformed_envelope_contract_is_refused() -> None:
    """A contract that is not a verdict cannot be read as one."""
    gate = _load_gate()
    contracts = _contained_contracts(gate)
    contracts["sedan"] = "fine"
    with pytest.raises(RuntimeError, match="malformed"):
        gate._require_contained_envelopes({"vehicles": {"envelope_contracts": contracts}})


def test_a_subset_or_unknown_vehicle_envelope_contract_is_refused() -> None:
    """All and only compact, sedan, SUV, van and coupe must be proven contained."""
    gate = _load_gate()
    subset = _contained_contracts(gate)
    subset.pop("coupe")
    with pytest.raises(RuntimeError, match="exactly the five archetypes"):
        gate._require_contained_envelopes({"vehicles": {"envelope_contracts": subset}})

    complete_plus_bus = _contained_contracts(gate)
    complete_plus_bus["bus"] = {"contained": True, "escaped": []}
    with pytest.raises(RuntimeError, match=r"unexpected \['bus'\]"):
        gate._require_contained_envelopes({"vehicles": {"envelope_contracts": complete_plus_bus}})


def test_contained_archetypes_are_accepted() -> None:
    """The happy path: every archetype inside its envelope, and the block returned."""
    gate = _load_gate()
    contracts = _contained_contracts(gate)
    assert gate._require_contained_envelopes({"vehicles": {"envelope_contracts": contracts}}) == (
        contracts
    )


def test_the_gate_requires_the_exact_mobility_artifact_and_schema() -> None:
    """A different phase, artifact or schema may not borrow this gate's PASS."""
    gate = _load_gate()
    valid = {
        "artifact": gate.MOBILITY_MANIFEST_ARTIFACT,
        "schema_version": gate.MOBILITY_MANIFEST_SCHEMA_VERSION,
    }
    assert gate._require_manifest_identity(valid) is None

    wrong_artifact = dict(valid, artifact="living_diorama_phase19_other_artifact")
    with pytest.raises(RuntimeError, match="declares artifact"):
        gate._require_manifest_identity(wrong_artifact)

    wrong_schema = dict(valid, schema_version=2)
    with pytest.raises(RuntimeError, match="schema_version"):
        gate._require_manifest_identity(wrong_schema)


def test_manifest_semantics_are_checked_against_an_independent_statement() -> None:
    """Two mutually copied manifest fields may not certify each other."""
    gate = _load_gate()
    manifest = {
        "semantics": {
            "statement": "wrong",
            "expected_statement": "wrong",
        }
    }
    with pytest.raises(RuntimeError, match="presentation-mobility statement"):
        gate._require_presentation_statement(manifest, "independently derived")


def test_the_independently_matching_presentation_statement_is_accepted() -> None:
    """The happy path returns the rendered statement the pure plan supplied."""
    gate = _load_gate()
    manifest = {"semantics": {"statement": "presentation only"}}
    assert (
        gate._require_presentation_statement(manifest, "presentation only") == "presentation only"
    )


# ---------------------------------------------------------------------------
# A structural phase that passed by running nothing
# ---------------------------------------------------------------------------


def test_a_structural_phase_that_executed_no_tests_is_refused() -> None:
    """``0 passed, 0 failed`` is what a suite that failed to collect reports.

    Every phase reporting zero used to satisfy the gate completely: nothing
    failed, and the total cross-check compared zero against zero.
    """
    gate = _load_gate()
    empty = dict.fromkeys(gate.STRUCTURAL_PHASES, 0)
    with pytest.raises(RuntimeError, match="executed 0 structural tests"):
        gate._structural_summary(_structural_output(empty))


def test_a_single_collapsed_structural_suite_is_refused() -> None:
    """One phase running nothing is enough, and the refusal names that phase."""
    gate = _load_gate()
    counts = {phase: gate.MINIMUM_STRUCTURAL_TESTS[phase] for phase in gate.STRUCTURAL_PHASES}
    counts["PHASE18"] = 0
    with pytest.raises(RuntimeError, match="PHASE18 executed 0 structural tests"):
        gate._structural_summary(_structural_output(counts))


def test_a_shrunken_structural_suite_is_refused() -> None:
    """Deleting tests until a locked suite is smaller than it was is a refusal."""
    gate = _load_gate()
    counts = {phase: gate.MINIMUM_STRUCTURAL_TESTS[phase] for phase in gate.STRUCTURAL_PHASES}
    counts["PHASE15"] -= 1
    with pytest.raises(RuntimeError, match="fewer than the 23"):
        gate._structural_summary(_structural_output(counts))


def test_the_canonical_structural_counts_are_accepted() -> None:
    """The floors are the counts the suites carry, and a grown suite still passes."""
    gate = _load_gate()
    counts = {phase: gate.MINIMUM_STRUCTURAL_TESTS[phase] for phase in gate.STRUCTURAL_PHASES}
    summary = gate._structural_summary(_structural_output(counts))
    assert summary["P19"]["passed"] == 123
    counts["PHASE19"] += 4
    grown = gate._structural_summary(_structural_output(counts))
    assert grown["P19"]["passed"] == 127


def test_the_total_floor_is_the_sum_of_the_phase_floors() -> None:
    """A floor raised in one place and not the other would let the total sag."""
    gate = _load_gate()
    floors = gate.MINIMUM_STRUCTURAL_TESTS
    assert floors["P19"] == sum(floors[phase] for phase in gate.STRUCTURAL_PHASES)


# ---------------------------------------------------------------------------
# Inventory totals checked against the inventory that declared them
# ---------------------------------------------------------------------------


def _rewrite_inventory(built: Path, **changes) -> None:
    """Tamper with the inventory's own summary fields, leaving the members alone."""
    path = built / package.INVENTORY_NAME
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    document.update(changes)
    path.write_text(json.dumps(document), encoding="utf-8")


def test_a_forged_total_bytes_is_refused(built: Path) -> None:
    """``total_bytes`` was returned verbatim, so any number at all verified."""
    _rewrite_inventory(built, total_bytes=999999)
    with pytest.raises(proof_package.ProofPackageError, match="total bytes"):
        package.verify_mobility_inventory(built)


def test_a_total_bytes_of_the_wrong_type_is_refused(built: Path) -> None:
    """A string where a byte count belongs is not a byte count."""
    _rewrite_inventory(built, total_bytes="lots")
    with pytest.raises(proof_package.ProofPackageError, match="total bytes"):
        package.verify_mobility_inventory(built)


def test_the_verified_total_is_the_measured_one(built: Path) -> None:
    """The report hands back what was weighed, not what was claimed."""
    report = package.verify_mobility_inventory(built)
    measured = sum(member.stat().st_size for member in package.mobility_members(built))
    assert report["total_bytes"] == measured


def test_a_forged_inventory_filename_is_refused(built: Path) -> None:
    """The inventory may not claim that some other file is authoritative."""
    _rewrite_inventory(built, inventory_file="other_inventory.json")
    with pytest.raises(proof_package.ProofPackageError, match="inventory_file"):
        package.verify_mobility_inventory(built)


def test_a_forged_member_count_is_refused(built: Path) -> None:
    """The count is recomputed from the inventory's actual member table."""
    _rewrite_inventory(built, member_count=999)
    with pytest.raises(proof_package.ProofPackageError, match="member_count"):
        package.verify_mobility_inventory(built)


def test_forged_artifact_references_are_refused(built: Path) -> None:
    """The rich reference table is recomputed, not trusted from the inventory."""
    _rewrite_inventory(built, artifact_references={})
    with pytest.raises(proof_package.ProofPackageError, match="artifact_references disagree"):
        package.verify_mobility_inventory(built)


def test_exact_required_members_accept_the_complete_set(built: Path) -> None:
    """The authoritative mode accepts a package containing exactly its contract."""
    required = tuple(member.name for member in package.mobility_members(built))
    report = package.verify_mobility_inventory(built, required, exact_required=True)
    assert report["member_count"] == len(required)


def test_exact_required_members_refuse_an_inventoried_extra(built: Path) -> None:
    """Hashing an unrelated stale artifact does not make it authoritative proof."""
    required = tuple(member.name for member in package.mobility_members(built))
    (built / "stale_preview.mp4").write_bytes(b"old but inventoried")
    package.write_mobility_inventory(built)
    with pytest.raises(proof_package.ProofPackageError, match="unexpected members"):
        package.verify_mobility_inventory(built, required, exact_required=True)


def test_a_forged_manifest_list_is_refused(built: Path) -> None:
    """The manifest list was copied out of the artifact it was meant to describe."""
    _rewrite_inventory(built, manifests=[])
    with pytest.raises(proof_package.ProofPackageError, match="records manifests"):
        package.verify_mobility_inventory(built)


def test_an_invented_manifest_entry_is_refused(built: Path) -> None:
    """An inventory may not name a manifest reference its members never made."""
    _rewrite_inventory(built, manifests=["phase19_mobility_manifest.json#blend", "invented#blend"])
    with pytest.raises(proof_package.ProofPackageError, match="records manifests"):
        package.verify_mobility_inventory(built)


def test_the_verified_manifest_list_is_recomputed(built: Path) -> None:
    """What the report returns is derived from the package, like its sibling."""
    report = package.verify_mobility_inventory(built)
    assert report["manifests"] == sorted(report["artifact_references"])
    assert report["manifests"] == [
        "phase19_mobility_manifest.json#blend",
        "phase19_mobility_manifest.json#mobility_plan",
        "phase19_mobility_manifest.json#source_export",
    ]
