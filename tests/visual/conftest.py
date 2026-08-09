"""Shared fixtures for the pure visual-layer tests.

The Phase 16 pure modules (``production_spec``, ``road_graph``,
``urban_fabric``) live beside the Blender scripts and import each other by
plain sibling name, exactly as they do inside Blender. The loader here makes
them importable under ordinary pytest by exposing the scripts directory on
``sys.path`` just long enough to import, then caching the module objects for
the whole session. None of them imports ``bpy`` -- the boundary tests pin
that -- so pytest never needs Blender.
"""

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "visual" / "blender" / "scripts"

_CACHE: dict[str, object] = {}


def load_visual_module(name: str):
    """Import one pure visual/blender scripts module, cached per session."""
    if name in _CACHE:
        return _CACHE[name]
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        module = importlib.import_module(name)
    finally:
        sys.path.remove(str(SCRIPTS_DIR))
    _CACHE[name] = module
    return module


@pytest.fixture(scope="session", name="scene_spec")
def scene_spec_fixture():
    """The Phase 15 pure contract module."""
    return load_visual_module("scene_spec")


@pytest.fixture(scope="session", name="production_spec")
def production_spec_fixture():
    """The Phase 16 production spec contract module."""
    return load_visual_module("production_spec")


@pytest.fixture(scope="session", name="road_graph")
def road_graph_fixture():
    """The Phase 16 street network module."""
    return load_visual_module("road_graph")


@pytest.fixture(scope="session", name="urban_fabric")
def urban_fabric_fixture():
    """The Phase 16 fabric layout module."""
    return load_visual_module("urban_fabric")


@pytest.fixture(scope="session", name="master_document")
def master_document_fixture(scene_spec):
    """The canonical Master Scene Spec V1, loaded and validated."""
    return scene_spec.load_master_scene_spec(
        REPO_ROOT / "visual" / "blender" / "config" / "master_scene_v1.json"
    )


@pytest.fixture(scope="session", name="production_document")
def production_document_fixture(production_spec):
    """The canonical Production World Spec V1, loaded and validated."""
    return production_spec.load_production_world_spec(
        REPO_ROOT / "visual" / "blender" / "config" / "production_world_v1.json"
    )


@pytest.fixture(scope="session", name="canonical_graph")
def canonical_graph_fixture(road_graph, master_document, production_document):
    """The canonical street network, built and fully validated once."""
    return road_graph.build_road_graph(master_document, production_document)


@pytest.fixture(scope="session", name="canonical_plan")
def canonical_plan_fixture(urban_fabric, master_document, production_document, canonical_graph):
    """The canonical fabric plan, computed once."""
    return urban_fabric.plan_urban_fabric(master_document, production_document, canonical_graph)


@pytest.fixture(scope="session", name="city_ground")
def city_ground_fixture():
    """The Phase 16 urban-ground composition module."""
    return load_visual_module("city_ground")


@pytest.fixture(scope="session", name="canonical_ground")
def canonical_ground_fixture(city_ground, master_document, production_document, canonical_graph):
    """The canonical urban ground plan, computed once."""
    return city_ground.plan_city_ground(master_document, production_document, canonical_graph)


@pytest.fixture(scope="session", name="spatial_occupancy")
def spatial_occupancy_fixture():
    """The Phase 16 spatial validity module."""
    return load_visual_module("spatial_occupancy")


@pytest.fixture(scope="session", name="spatial_module_trees")
def spatial_module_trees_fixture(spatial_occupancy, master_document):
    """Every founding tree, re-derived purely from the locked algorithm."""
    return spatial_occupancy.founding_trees(master_document)
