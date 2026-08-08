"""Master Scene Spec V1: loading, validation, and topology agreement.

Pure Python by design -- this module never imports ``bpy``, so the contract
between the Master Scene Spec, the Render Export, and the Blender build can be
validated and tested without Blender installed. The Blender runtime imports it;
nothing here imports the Blender runtime.

The Master Scene Spec is presentation geography only: where districts sit,
where boundary corridors run, where a wall would stand if an episode builds
one, where the Golden Seal lives, and where the persistent cameras are. It
carries no simulation state and no episode state; those arrive separately in
the Render Export, and the two must AGREE on topology or the build refuses.
"""

import hashlib
import json
import math
import random
from pathlib import Path

MASTER_SCENE_FORMAT = "living_diorama_blender_master_scene"
MASTER_SCENE_SCHEMA_VERSION = 1

RENDER_EXPORT_FORMAT = "living_diorama_render_export"
RENDER_EXPORT_SCHEMA_VERSION = 1

REQUIRED_CAMERAS = (
    "CAM_HERO_WORLD",
    "CAM_HERO_SCAR",
    "CAM_SCAR_DETAIL",
    "CAM_SEAL_DETAIL",
    "CAM_VERIFY_TOPOLOGY",
)

SUPPORTED_BLENDER_MAJOR_MINOR = (4, 5)


class SceneContractError(ValueError):
    """A master-scene or render-export contract violation.

    Raised for malformed specs, malformed exports, unknown districts or
    boundaries, and topology disagreements. Always a refusal, never a repair.
    """


def stable_rng(*parts: str) -> random.Random:
    """Return a deterministic generator owned by an explicit identity.

    Seeded from SHA-256 over the joined parts, so the same master visual seed
    and the same entity identity always produce the same variation -- across
    runs, machines, and ``PYTHONHASHSEED`` values. Python's builtin ``hash()``
    is never involved.
    """
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _require_object(value: object, description: str) -> dict:
    """Return the value if it is a JSON object, else refuse."""
    if not isinstance(value, dict):
        raise SceneContractError(f"{description} must be a JSON object, got {type(value).__name__}")
    return value


def _require_pair(value: object, description: str) -> tuple[float, float]:
    """Return a 2D coordinate pair, else refuse."""
    if not isinstance(value, list) or len(value) != 2:
        raise SceneContractError(f"{description} must be a [x, y] pair")
    x, y = value
    if isinstance(x, bool) or isinstance(y, bool):
        raise SceneContractError(f"{description} must hold numbers, not booleans")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        raise SceneContractError(f"{description} must hold numbers")
    return (float(x), float(y))


def _require_number(value: object, description: str) -> float:
    """Return a finite number, else refuse."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SceneContractError(f"{description} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise SceneContractError(f"{description} must be finite")
    return number


def load_master_scene_spec(path: str | Path) -> dict:
    """Load and validate the Master Scene Spec V1.

    Raises:
        SceneContractError: If the document is not a well-formed spec.
    """
    document = _require_object(
        json.loads(Path(path).read_text(encoding="utf-8")), "master scene spec"
    )
    if document.get("format") != MASTER_SCENE_FORMAT:
        raise SceneContractError(
            f"master scene spec format must be {MASTER_SCENE_FORMAT!r}, "
            f"got {document.get('format')!r}"
        )
    version = document.get("schema_version")
    if isinstance(version, bool) or version != MASTER_SCENE_SCHEMA_VERSION:
        raise SceneContractError(
            f"master scene spec schema_version must be {MASTER_SCENE_SCHEMA_VERSION}, "
            f"got {version!r}"
        )
    seed = document.get("visual_seed")
    if not isinstance(seed, str) or not seed.strip():
        raise SceneContractError("master scene spec visual_seed must be a non-empty string")

    districts = _require_object(document.get("districts"), "spec districts")
    if not districts:
        raise SceneContractError("master scene spec must define at least one district")
    for district_id, entry in districts.items():
        district = _require_object(entry, f"spec district {district_id}")
        _require_pair(district.get("center"), f"district {district_id} center")
        _require_number(district.get("radius"), f"district {district_id} radius")
        _require_number(district.get("elevation"), f"district {district_id} elevation")
        _require_number(district.get("depot_capacity"), f"district {district_id} depot_capacity")
        if district.get("character") not in ("civic", "port", "residential", "terrace"):
            raise SceneContractError(
                f"district {district_id} character must be one of civic/port/"
                f"residential/terrace, got {district.get('character')!r}"
            )

    boundaries = _require_object(document.get("boundaries"), "spec boundaries")
    for boundary_id, entry in boundaries.items():
        boundary = _require_object(entry, f"spec boundary {boundary_id}")
        endpoints = boundary.get("districts")
        if (
            not isinstance(endpoints, list)
            or len(endpoints) != 2
            or not all(isinstance(endpoint, str) for endpoint in endpoints)
        ):
            raise SceneContractError(
                f"boundary {boundary_id} must declare exactly two district endpoints"
            )
        for endpoint in endpoints:
            if endpoint not in districts:
                raise SceneContractError(
                    f"boundary {boundary_id} references unknown district {endpoint!r}"
                )
        path_points = boundary.get("path")
        if not isinstance(path_points, list) or len(path_points) < 2:
            raise SceneContractError(f"boundary {boundary_id} path must hold at least two points")
        for index, point in enumerate(path_points):
            _require_pair(point, f"boundary {boundary_id} path[{index}]")
        wall_station = _require_object(
            boundary.get("wall_station"), f"boundary {boundary_id} wall_station"
        )
        _require_pair(wall_station.get("center"), f"boundary {boundary_id} wall center")
        _require_pair(wall_station.get("direction"), f"boundary {boundary_id} wall direction")
        _require_number(wall_station.get("length"), f"boundary {boundary_id} wall length")

    landmarks = _require_object(document.get("landmarks"), "spec landmarks")
    seal = _require_object(landmarks.get("golden_seal"), "landmark golden_seal")
    _require_pair(seal.get("location"), "golden_seal location")
    _require_number(seal.get("radius"), "golden_seal radius")

    cameras = _require_object(document.get("cameras"), "spec cameras")
    for name in REQUIRED_CAMERAS:
        camera = _require_object(cameras.get(name), f"camera {name}")
        location = camera.get("location")
        if not isinstance(location, list) or len(location) != 3:
            raise SceneContractError(f"camera {name} location must be [x, y, z]")
        look_at = camera.get("look_at")
        if not isinstance(look_at, list) or len(look_at) != 3:
            raise SceneContractError(f"camera {name} look_at must be [x, y, z]")
        _require_number(camera.get("lens_mm"), f"camera {name} lens_mm")

    return document


def load_render_export(path: str | Path) -> dict:
    """Load a Render Export V1 document for visual consumption.

    Structural trust lives with the Phase 14 exporter; the Blender layer still
    refuses documents that do not declare the expected format, because a wrong
    file here would silently build the wrong world.

    Raises:
        SceneContractError: If the document is not a render export V1.
    """
    document = _require_object(json.loads(Path(path).read_text(encoding="utf-8")), "render export")
    if document.get("format") != RENDER_EXPORT_FORMAT:
        raise SceneContractError(
            f"render export format must be {RENDER_EXPORT_FORMAT!r}, got {document.get('format')!r}"
        )
    version = document.get("schema_version")
    if isinstance(version, bool) or version != RENDER_EXPORT_SCHEMA_VERSION:
        raise SceneContractError(
            f"render export schema_version must be {RENDER_EXPORT_SCHEMA_VERSION}, got {version!r}"
        )
    _require_object(document.get("world"), "render export world")
    return document


def require_topology_agreement(spec: dict, export: dict) -> None:
    """Refuse any disagreement between spec geography and export topology.

    Every exported district must resolve to exactly one spec district; every
    exported boundary must exist in the spec with exactly the same endpoint
    roles; every exported wall must stand on a boundary the spec knows.
    Nothing is silently placed, swapped, or redrawn.

    Raises:
        SceneContractError: On any unknown entity or endpoint disagreement.
    """
    world = export["world"]
    spec_districts = spec["districts"]
    spec_boundaries = spec["boundaries"]

    for district in world["districts"]:
        if district["id"] not in spec_districts:
            raise SceneContractError(
                f"render export district {district['id']!r} has no master scene "
                "definition; unknown districts are refused, never placed at origin"
            )
    for boundary in world["boundaries"]:
        entry = spec_boundaries.get(boundary["id"])
        if entry is None:
            raise SceneContractError(
                f"render export boundary {boundary['id']!r} has no master scene definition"
            )
        declared = entry["districts"]
        if [boundary["district_a_id"], boundary["district_b_id"]] != declared:
            raise SceneContractError(
                f"boundary {boundary['id']!r} endpoints disagree: master scene "
                f"declares {declared}, render export says "
                f"[{boundary['district_a_id']!r}, {boundary['district_b_id']!r}]; "
                "topology is never silently redrawn"
            )
    known_boundaries = {boundary["id"] for boundary in world["boundaries"]}
    for wall in world["walls"]:
        if wall["boundary_id"] not in spec_boundaries:
            raise SceneContractError(
                f"wall {wall['id']!r} stands on boundary {wall['boundary_id']!r}, "
                "which has no master scene definition"
            )
        if wall["boundary_id"] not in known_boundaries:
            raise SceneContractError(
                f"wall {wall['id']!r} references boundary {wall['boundary_id']!r} "
                "absent from its own export"
            )


def occupancy_fraction(district: dict) -> float:
    """Window-lit fraction for a district: population over housing capacity."""
    capacity = district["housing_capacity"]
    if capacity <= 0:
        return 0.0
    return max(0.0, min(1.0, district["population"] / capacity))


def depot_fill_fraction(district: dict, depot_capacity: float) -> float:
    """Visible storage fill for a district: total stock over depot capacity."""
    total = sum(district["resources"].values())
    if depot_capacity <= 0:
        return 0.0
    return max(0.0, min(1.0, total / depot_capacity))
