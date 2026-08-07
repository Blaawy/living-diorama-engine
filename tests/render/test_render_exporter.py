"""Render export projection: verified sources in, faithful bytes out.

Every test runs against real published episodes: fidelity is asserted against
the locked persistence serializers, immutability against byte snapshots of
the real save tree, and the scar proof against a chain the real Phase 13
continuation produced.
"""

import ast
from pathlib import Path

import pytest

from cli.conftest import build_parent_world, save_episode_zero
from living_diorama.persistence import (
    LoadedEpisode,
    SaveManager,
    dumps_canonical,
    loads_canonical,
    sha256_hex,
)
from living_diorama.persistence.serializers.event_serializer import serialize_event_log
from living_diorama.persistence.serializers.world_memory_serializer import (
    serialize_world_memory,
)
from living_diorama.persistence.serializers.world_serializer import serialize_world
from living_diorama.render import (
    build_render_export_bytes,
    build_render_export_document,
    write_render_export,
)
from living_diorama.render.render_exporter import _project_loaded_episode
from persistence.conftest import temporary_save_root
from render.conftest import (
    TYPED_LAW_VALUES,
    publish_calm_episode_zero,
    publish_scar_chain,
    publish_typed_laws_episode_zero,
    tree_bytes,
    tree_entries,
)

RENDER_SOURCE_FILES = (
    "render_exporter.py",
    "render_schema_v1.py",
    "export_episode.py",
    "__init__.py",
)
"""Every Phase 14 render source file, checked by the architecture test."""

ALLOWED_IMPORT_ROOTS = ("living_diorama.persistence", "living_diorama.render")
"""The only project packages render source may import from."""

STANDARD_LIBRARY_MODULES = frozenset(
    {"argparse", "collections.abc", "os", "pathlib", "re", "sys", "typing"}
)
"""Exactly the standard-library modules the render source may use.

Deliberately narrow: ``importlib`` and friends are absent, so dynamic-import
laundering cannot slip past the architecture check by being 'stdlib'.
"""


def parsed_export(root: Path, episode: int) -> dict[str, object]:
    """Export an episode and parse the canonical bytes back into a document."""
    document = loads_canonical(build_render_export_bytes(root, episode), "render export")
    assert type(document) is dict
    return document


class TestSourceFidelity:
    """The export equals what the locked serializers say, nothing else."""

    def test_world_arrays_match_the_persistence_serializer(self) -> None:
        """All five entity arrays are exactly the serializer's output."""
        with temporary_save_root() as root:
            publish_scar_chain(root)
            loaded = SaveManager(root).load_episode(1)
            expected = serialize_world(loaded.world)
            document = parsed_export(root, 1)
            world = document["world"]
            assert type(world) is dict
            for kind in ("boundaries", "districts", "infrastructure", "laws", "walls"):
                assert world[kind] == expected[kind]

    def test_world_omits_only_continuation_metadata(self) -> None:
        """Episode, tick, schema version, and RNG state stay out of world."""
        with temporary_save_root() as root:
            publish_calm_episode_zero(root)
            loaded = SaveManager(root).load_episode(0)
            expected = serialize_world(loaded.world)
            document = parsed_export(root, 0)
            world = document["world"]
            assert type(world) is dict
            omitted = set(expected) - set(world)
            assert omitted == {"episode", "rng_state", "schema_version", "tick"}
            source = document["source"]
            assert type(source) is dict
            assert source["episode"] == expected["episode"]
            assert source["tick"] == expected["tick"]

    def test_events_match_the_event_serializer_in_order(self) -> None:
        """The events array is the serializer's, in exact append order."""
        with temporary_save_root() as root:
            publish_scar_chain(root)
            loaded = SaveManager(root).load_episode(1)
            expected = serialize_event_log(
                loaded.event_log, loaded.manifest.episode, loaded.manifest.tick
            )
            document = parsed_export(root, 1)
            assert document["events"] == expected["events"]

    def test_memory_facts_match_the_memory_serializer_in_order(self) -> None:
        """The facts array is the serializer's, in exact canonical order."""
        with temporary_save_root() as root:
            publish_scar_chain(root)
            loaded = SaveManager(root).load_episode(1)
            expected = serialize_world_memory(loaded.world_memory)
            document = parsed_export(root, 1)
            memory = document["memory"]
            assert type(memory) is dict
            assert memory["facts"] == expected["facts"]

    def test_source_matches_the_verified_manifest(self) -> None:
        """Provenance comes from the manifest, field for field."""
        with temporary_save_root() as root:
            publish_scar_chain(root)
            manifest = SaveManager(root).load_episode(1).manifest
            document = parsed_export(root, 1)
            source = document["source"]
            assert type(source) is dict
            assert source["engine_version"] == manifest.engine_version
            assert source["episode"] == manifest.episode
            assert source["tick"] == manifest.tick
            assert source["state_hash"] == manifest.state_hash
            assert source["parent_state_hash"] == manifest.parent_state_hash
            assert source["event_count"] == manifest.event_count
            assert source["entity_counts"] == dict(manifest.entity_counts)

    def test_boundary_endpoint_roles_are_preserved(self) -> None:
        """Stored endpoint roles survive exactly; nothing swaps A and B."""
        with temporary_save_root() as root:
            publish_typed_laws_episode_zero(root)
            document = parsed_export(root, 0)
            world = document["world"]
            assert type(world) is dict
            boundaries = {entry["id"]: entry for entry in world["boundaries"]}  # type: ignore[index, union-attr]
            assert boundaries["boundary_ab"]["district_a_id"] == "district_a"
            assert boundaries["boundary_ab"]["district_b_id"] == "district_b"
            assert boundaries["boundary_ba"]["district_a_id"] == "district_b"
            assert boundaries["boundary_ba"]["district_b_id"] == "district_a"


class TestLawTypeFidelity:
    """Law scalars keep their exact types through export and re-parse."""

    def test_law_values_survive_with_exact_types(self) -> None:
        """``True``, ``1``, ``1.0``, and ``"1"`` remain four different values."""
        with temporary_save_root() as root:
            publish_typed_laws_episode_zero(root)
            document = parsed_export(root, 0)
            world = document["world"]
            assert type(world) is dict
            laws = {entry["id"]: entry for entry in world["laws"]}  # type: ignore[index, union-attr]
            for law_id, (previous_value, current_value) in TYPED_LAW_VALUES.items():
                stored_previous = laws[law_id]["previous_value"]
                stored_current = laws[law_id]["current_value"]
                assert type(stored_previous) is type(previous_value)
                assert stored_previous == previous_value
                assert type(stored_current) is type(current_value)
                assert stored_current == current_value

    def test_laws_match_the_world_serializer_exactly(self) -> None:
        """The laws array is byte-level identical to the serializer's."""
        with temporary_save_root() as root:
            publish_typed_laws_episode_zero(root)
            loaded = SaveManager(root).load_episode(0)
            expected = serialize_world(loaded.world)["laws"]
            document = parsed_export(root, 0)
            world = document["world"]
            assert type(world) is dict
            assert world["laws"] == expected


class TestNoRngAndNoMutation:
    """Export draws nothing, changes nothing, and exports no RNG."""

    def test_rng_state_appears_nowhere_in_the_export(self) -> None:
        """Neither the key nor the state structure enters the bytes."""
        with temporary_save_root() as root:
            publish_scar_chain(root)
            data = build_render_export_bytes(root, 1)
            assert b'"rng_state"' not in data
            assert b'"random_state"' not in data
            assert b'"state_format"' not in data

    def test_projection_consumes_zero_rng_draws(self) -> None:
        """Building the projection leaves the loaded generator untouched."""
        with temporary_save_root() as root:
            publish_scar_chain(root)
            loaded = SaveManager(root).load_episode(1)
            state_before = loaded.world.rng.get_state()
            _project_loaded_episode(loaded)
            assert loaded.world.rng.get_state() == state_before

    def test_export_leaves_the_save_tree_byte_identical(self) -> None:
        """No file or directory under the save root changes or appears."""
        with temporary_save_root() as root:
            publish_scar_chain(root)
            bytes_before = tree_bytes(root)
            entries_before = tree_entries(root)
            outside = root.parent / "scar_export.json"
            try:
                write_render_export(root, 1, outside)
                assert tree_bytes(root) == bytes_before
                assert tree_entries(root) == entries_before
            finally:
                outside.unlink(missing_ok=True)

    def test_projection_does_not_modify_the_loaded_world(self) -> None:
        """Serializing before and after the projection yields equal documents."""
        with temporary_save_root() as root:
            publish_calm_episode_zero(root)
            loaded = SaveManager(root).load_episode(0)
            before = serialize_world(loaded.world)
            _project_loaded_episode(loaded)
            assert serialize_world(loaded.world) == before


class TestVerifiedPersistenceGate:
    """Only what the real loader verifies can be exported."""

    def test_corrupted_episode_refuses_export(self) -> None:
        """A byte-flipped source episode is not exportable."""
        with temporary_save_root() as root:
            publish_calm_episode_zero(root)
            state_path = root / "episode_000" / "world_state.json"
            state_path.write_bytes(state_path.read_bytes().replace(b"1", b"2", 1))
            with pytest.raises(ValueError):
                build_render_export_bytes(root, 0)

    def test_corrupted_ancestor_refuses_export(self) -> None:
        """A broken episode 0 makes episode 1 unexportable too."""
        with temporary_save_root() as root:
            publish_scar_chain(root)
            state_path = root / "episode_000" / "world_state.json"
            state_path.write_bytes(state_path.read_bytes().replace(b"1", b"2", 1))
            outside = root.parent / "never_written.json"
            with pytest.raises(ValueError):
                write_render_export(root, 1, outside)
            assert not outside.exists()

    def test_missing_episode_refuses_export(self) -> None:
        """An absent episode refuses continuation through the real loader."""
        with temporary_save_root() as root, pytest.raises(FileNotFoundError):
            build_render_export_bytes(root, 0)

    def test_blank_save_root_is_refused(self) -> None:
        """An empty save root is refused, never normalized to the cwd."""
        with pytest.raises(ValueError, match="save_root must not be empty"):
            build_render_export_bytes("", 0)
        with pytest.raises(ValueError, match="save_root must not be empty"):
            build_render_export_bytes("   ", 0)

    def test_whitespace_path_save_root_is_refused(self) -> None:
        """A whitespace-only Path is refused the same as a whitespace str."""
        with pytest.raises(ValueError, match="save_root must not be empty"):
            build_render_export_bytes(Path("   "), 0)

    def test_whitespace_path_output_is_refused(self, tmp_path: Path) -> None:
        """A whitespace-only Path destination is refused, not written."""
        root = tmp_path / "saves"
        publish_calm_episode_zero(root)
        with pytest.raises(ValueError, match="output_path must not be empty"):
            write_render_export(root, 0, Path("   "))

    def test_loaded_argument_must_be_exactly_a_loaded_episode(self) -> None:
        """The private projection takes the loader's product, nothing else."""
        with pytest.raises(TypeError, match="must be a LoadedEpisode"):
            _project_loaded_episode({"world": {}})  # type: ignore[arg-type]

        class ShiftyLoaded(LoadedEpisode):
            """A subclass that could answer differently on later reads."""

        with temporary_save_root() as root:
            publish_calm_episode_zero(root)
            loaded = SaveManager(root).load_episode(0)
            shifty = ShiftyLoaded(
                world=loaded.world,
                event_log=loaded.event_log,
                world_memory=loaded.world_memory,
                manifest=loaded.manifest,
            )
            with pytest.raises(TypeError, match="must be a LoadedEpisode"):
                _project_loaded_episode(shifty)


class TestProvenanceGate:
    """A render export can never claim provenance its content disproves."""

    def test_mutated_loaded_world_is_refused(self) -> None:
        """A world changed after verification cannot export under its old hash.

        This is the false-provenance regression: before the correction, this
        exact sequence produced an export whose ``source.state_hash`` named
        the persisted state while the world section carried the mutated one.
        The captured-snapshot hash gate must now refuse it.
        """
        with temporary_save_root() as root:
            publish_calm_episode_zero(root)
            loaded = SaveManager(root).load_episode(0)
            original_hash = loaded.manifest.state_hash
            loaded.world.districts["district_a"].population += 1
            mutated_hash = sha256_hex(
                dumps_canonical(serialize_world(loaded.world), "mutated world")
            )
            assert mutated_hash != original_hash
            with pytest.raises(ValueError, match="no longer agrees with its persisted provenance"):
                _project_loaded_episode(loaded)

    def test_untouched_loaded_world_passes_the_gate(self) -> None:
        """The gate refuses drift, not legitimate loads."""
        with temporary_save_root() as root:
            publish_calm_episode_zero(root)
            loaded = SaveManager(root).load_episode(0)
            document = _project_loaded_episode(loaded)
            source = document["source"]
            assert type(source) is dict
            assert source["state_hash"] == loaded.manifest.state_hash


class TestPublicSurface:
    """Every public build path begins at save_root + episode."""

    def test_public_surface_is_exactly_the_approved_api(self) -> None:
        """``__all__`` names the approved Phase 14 API and nothing more."""
        import living_diorama.render as render

        assert render.__all__ == [
            "RENDER_EXPORT_FORMAT",
            "RENDER_SCHEMA_VERSION",
            "build_render_export_bytes",
            "build_render_export_document",
            "validate_render_export",
            "write_render_export",
        ]

    def test_no_public_function_accepts_a_loaded_episode(self) -> None:
        """No exported callable takes a caller-supplied loaded episode."""
        import inspect

        import living_diorama.render as render

        for name in render.__all__:
            member = getattr(render, name)
            if not inspect.isfunction(member):
                continue
            signature = inspect.signature(member)
            for parameter in signature.parameters.values():
                assert "LoadedEpisode" not in str(parameter.annotation), (
                    f"{name} exposes a LoadedEpisode parameter"
                )
            first = next(iter(signature.parameters))
            assert first in ("save_root", "value"), (
                f"{name} does not begin its trust boundary at save_root"
            )

    def test_hand_built_loaded_episode_cannot_enter_public_paths(self) -> None:
        """A caller-supplied LoadedEpisode is outside the public boundary."""
        with temporary_save_root() as root:
            publish_calm_episode_zero(root)
            loaded = SaveManager(root).load_episode(0)
            with pytest.raises(TypeError, match="save_root must be a str or Path"):
                build_render_export_bytes(loaded, 0)  # type: ignore[arg-type]
            with pytest.raises(TypeError, match="save_root must be a str or Path"):
                build_render_export_document(loaded, 0)  # type: ignore[arg-type]
            with pytest.raises(TypeError, match="save_root must be a str or Path"):
                write_render_export(loaded, 0, root.parent / "never.json")  # type: ignore[arg-type]


class TestDeterminism:
    """Same verified source, same bytes; different state, different bytes."""

    def test_repeated_export_is_byte_identical(self) -> None:
        """Two exports of the same episode agree on every byte."""
        with temporary_save_root() as root:
            publish_scar_chain(root)
            first = build_render_export_bytes(root, 1)
            second = build_render_export_bytes(root, 1)
            assert first == second
            assert sha256_hex(first) == sha256_hex(second)

    def test_different_semantic_state_changes_the_bytes(self) -> None:
        """A visible state difference must be visible in the export."""
        with temporary_save_root() as root_a, temporary_save_root() as root_b:
            publish_calm_episode_zero(root_a)
            publish_typed_laws_episode_zero(root_b)
            assert build_render_export_bytes(root_a, 0) != build_render_export_bytes(root_b, 0)

    def test_rng_only_differences_leave_visible_sections_identical(self) -> None:
        """Worlds differing only in RNG agree on every visible section.

        This is the documented subtlety, asserted precisely: the world,
        events, and memory sections are RNG-invariant, while the provenance
        state hash still differs because the persisted world-state bytes it
        describes include continuation state.
        """
        with temporary_save_root() as root_a, temporary_save_root() as root_b:
            save_episode_zero(root_a, build_parent_world())
            save_episode_zero(root_b, build_parent_world(seed=987654321))
            manifests = (
                SaveManager(root_a).load_episode(0).manifest,
                SaveManager(root_b).load_episode(0).manifest,
            )
            assert manifests[0].state_hash != manifests[1].state_hash
            parsed_a = loads_canonical(build_render_export_bytes(root_a, 0), "a")
            parsed_b = loads_canonical(build_render_export_bytes(root_b, 0), "b")
            assert type(parsed_a) is dict
            assert type(parsed_b) is dict
            assert parsed_a["world"] == parsed_b["world"]
            assert parsed_a["events"] == parsed_b["events"]
            assert parsed_a["memory"] == parsed_b["memory"]


class TestScarExport:
    """The world remembers, and the export shows it."""

    def test_the_scar_is_visible_in_one_export(self) -> None:
        """Restored law, standing wall, linked infrastructure, and memory."""
        with temporary_save_root() as root:
            publish_scar_chain(root)
            document = parsed_export(root, 1)
            world = document["world"]
            assert type(world) is dict

            laws = {entry["id"]: entry for entry in world["laws"]}  # type: ignore[index, union-attr]
            movement = laws["law_movement_sharing"]
            assert movement["active"] is True
            assert movement["current_value"] is True
            assert movement["changed_episode"] == 1
            assert type(movement["restored_tick"]) is int

            walls = world["walls"]
            assert type(walls) is list
            assert len(walls) == 1
            wall = walls[0]
            assert type(wall) is dict
            assert wall["id"] == "wall_boundary_ab"
            assert wall["permanent"] is True
            assert wall["boundary_id"] == "boundary_ab"
            assert type(wall["dependency_score"]) in (int, float)

            boundaries = {entry["id"]: entry for entry in world["boundaries"]}  # type: ignore[index, union-attr]
            assert boundaries["boundary_ab"]["wall_id"] == "wall_boundary_ab"

            infrastructure = world["infrastructure"]
            assert type(infrastructure) is list
            assert any(
                entry["boundary_id"] == "boundary_ab"  # type: ignore[index]
                for entry in infrastructure
            )

            memory = document["memory"]
            assert type(memory) is dict
            facts = memory["facts"]
            assert type(facts) is list
            fact_types = [entry["fact_type"] for entry in facts]  # type: ignore[index]
            assert fact_types == ["WALL_BUILT", "LAW_RESTORED_WALL_PERSISTED"]

            events = document["events"]
            assert type(events) is list
            assert any(entry["type"] == "LAW_RESTORED" for entry in events)  # type: ignore[index]


class TestArchitecture:
    """Render is a read-only consumer of verified persistence."""

    def test_render_source_imports_only_allowed_layers(self) -> None:
        """Every import is absolute and names stdlib, persistence, or render.

        Relative imports are refused outright: ``from .. import simulation``
        carries no module name in the AST and would otherwise slip past a
        module-name allowlist. Dynamic import via ``__import__`` is refused
        for the same reason.
        """
        source_root = Path(__file__).resolve().parents[2] / "src" / "living_diorama" / "render"
        for name in RENDER_SOURCE_FILES:
            tree = ast.parse((source_root / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    assert node.level == 0, (
                        f"{name} uses a relative import; render imports must be absolute"
                    )
                    assert node.module is not None
                    modules = [node.module]
                elif isinstance(node, ast.Name):
                    assert node.id != "__import__", f"{name} uses dynamic import"
                for module in modules:
                    if module in STANDARD_LIBRARY_MODULES:
                        continue
                    assert any(
                        module == allowed or module.startswith(allowed + ".")
                        for allowed in ALLOWED_IMPORT_ROOTS
                    ), f"{name} imports disallowed module {module}"
