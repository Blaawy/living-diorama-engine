"""The clearance module's restated geometry is pinned to its locked sources.

``camera_clearance.py`` restates the EP1 wall geometry from
``visual/blender/config/master_scene_v1.json`` and the builders' constants,
exactly as ``cinematic_spec`` restates the anchor catalogue -- the planner is
pure and touches no filesystem, so the values are frozen here and a test
proves they still agree with the configs field for field, so the two cannot
drift.
"""

import json
from pathlib import Path

from living_diorama.cinematic.camera_clearance import (
    DISTRICT_RECORDS,
    ROAD_WIDTH,
    WALL_CENTER,
    WALL_DIRECTION,
    WALL_HEIGHT,
    WALL_LENGTH,
    WALL_THICKNESS,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MASTER_SCENE = json.loads(
    (REPO_ROOT / "visual" / "blender" / "config" / "master_scene_v1.json").read_text(
        encoding="utf-8"
    )
)


def test_wall_station_restatement_agrees_with_master_scene_v1_json() -> None:
    """boundary_ab's wall station is exactly the restated constants."""
    station = MASTER_SCENE["boundaries"]["boundary_ab"]["wall_station"]
    assert list(WALL_CENTER) == station["center"] == [17.0, -1.0]
    assert list(WALL_DIRECTION) == station["direction"] == [-0.22, 1.0]
    assert WALL_LENGTH == station["length"] == 44.0


def test_wall_dimensions_agree_with_the_builders() -> None:
    """apply_render_export.py's WALL_HEIGHT/WALL_THICKNESS are restated."""
    assert WALL_HEIGHT == 16.0
    assert WALL_THICKNESS == 2.8
    assert ROAD_WIDTH == 7.0


def test_district_restatement_agrees_with_master_scene_v1_json() -> None:
    """The four district discs are exactly the config's four districts."""
    expected = {
        name: (tuple(district["center"]), district["radius"])
        for name, district in MASTER_SCENE["districts"].items()
    }
    restated = {name: (center, radius) for name, center, radius in DISTRICT_RECORDS}
    assert restated == expected
