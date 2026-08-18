"""Render the Phase 20 state-response proof pack.

Runs inside Blender. Builds the canonical world, applies each authoritative
episode, layers Phase 20's visible world condition over it, animates the two
canonical transitions, and renders the stills a reviewer needs in order to
judge -- not to take on trust -- whether the world's condition is legible and
whether the world remembers.

    THE PROOF MUST MAKE THE DEFECTS FINDABLE.

For Phase 20 that resolves into one discipline above all others:

    A BEFORE AND AN AFTER MUST BE THE SAME CAMERA.

The claim of this phase is that the WORLD changed, and the only way a reviewer
can see that is to compare two frames in which nothing else did. A camera nudged
between them makes every difference in the frame ambiguous -- the haze could be
thicker, or the lens could be longer -- and, unlike a missing file, it leaves no
trace at all in the delivered package. So the whole-city pair and the
district-scale pair are each ONE camera photographed at two episodes, the
pairing is declared in :mod:`state_response_proof_package`, and both this
producer and the gate check it.

Existing cameras are preferred for exactly that reason: ``CAM_HERO_WORLD`` is the
established before/after comparison anchor and ``CAM_SEAL_DETAIL`` is where the
record stones are legible at all. Only the district-scale pair needs a camera
nobody had a reason to build before, because which district is stressed is a
property of the world rather than of the scene; it is derived from the
authoritative readings, owned by Phase 20 under a ``CAM_P20_`` name, and built
here rather than in any locked builder.

There is NO VIDEO in V1. The still-frame visual language has to be accepted
before this phase spends a render budget on animation it may have to throw away.
The transition is still proven -- the endpoint-equivalence verdict is measured
off the real F-curves, by the same function the structural suite asserts on --
and one mid-transition still shows what the middle of it looks like.
"""

import argparse
import json
import math
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply_render_export  # noqa: E402
import apply_state_response as state_response  # noqa: E402
import apply_state_response_motion as state_motion  # noqa: E402
import build_master_scene  # noqa: E402
import build_production_world  # noqa: E402
import state_response_motion_plan as motion_plan  # noqa: E402
import state_response_plan as response_plan  # noqa: E402
from blender_runtime import link_only, look_at_rotation  # noqa: E402
from manifest_io import write_manifest_json  # noqa: E402
from mathutils import Vector  # noqa: E402
from motion_time_spec import load_motion_time_spec  # noqa: E402
from proof_package import ProofPackageError  # noqa: E402
from render_visual_proof import (  # noqa: E402
    configure_cycles_device,
    configure_sampling,
    render_frame,
)
from scene_spec import load_master_scene_spec, load_render_export  # noqa: E402
from state_response_proof_package import (  # noqa: E402
    require_identical_comparison_cameras,
    require_rendered_stills,
)
from state_response_spec import (  # noqa: E402
    frame_at,
    load_state_response_spec,
    resolve_state_response_timeline,
)

MANIFEST_NAME = "phase20_state_response_manifest.json"
MANIFEST_ARTIFACT = "living_diorama_phase20_state_response"
MANIFEST_SCHEMA_VERSION = 1
PLANS_NAME = "phase20_state_response_plans.json"
MOTION_PLANS_NAME = "phase20_state_response_motion_plans.json"
PROOF_STYLE = "dna"

WORLD_CAMERA = "CAM_HERO_WORLD"
"""The established before/after comparison anchor, used unchanged for BOTH ends.

Phase 15 built it, Phase 15's own proof compares two episodes on it, and Phase 20
adds nothing to it. A new hero camera would have been a second variable in the
one comparison this phase exists to make."""

SEAL_CAMERA = "CAM_SEAL_DETAIL"
"""The locked Phase 15 framing of the Seal artifact itself.

Kept as the reference for what the artifact looks like, but it is aimed at the
artifact, not at the record: a blind reviewer given this framing described the
Seal's own compass rose and never saw the stones at all."""

RECORD_ARC_CAMERA = "CAM_P20_RECORD_ARC"
"""Where the record stones are actually legible.

Record stones are a detail-band register -- they do not read at the world hero
cameras, and the Director accepted that. What they must do is read HERE, in the
frame whose whole job is to demonstrate them. Enlarging the stones to force them
into a wider shot was explicitly forbidden and would have been the wrong fix
anyway: the stones were the right size, the camera was pointed at the wrong
thing."""

RECORD_ARC_STAND_OFF_METRES = 5.6
RECORD_ARC_HEIGHT_METRES = 1.35
RECORD_ARC_LENS_MM = 48.0
RECORD_ARC_ORIGIN = (-16.0, 6.0)
"""The Seal plaza's own centre, which the record arc is struck from."""

DISTRICT_PAIR_CAMERA = "CAM_P20_DISTRICT_PAIR"
"""The one camera Phase 20 owns, built HERE and never in a locked builder.

Which district is stressed is a property of the authoritative world, not of the
scene, so this anchor cannot live in the master scene spec: it would have to be
hand-aimed at a district that the simulation, not the author, chose."""

WORLD_BEFORE = "phase20_world_before.png"
WORLD_AFTER = "phase20_world_after.png"
DISTRICT_PAIR_BEFORE = "phase20_district_pair_before.png"
DISTRICT_PAIR_AFTER = "phase20_district_pair_after.png"
SEAL_RECORDS = "phase20_seal_records.png"
TRANSITION_MID = "phase20_transition_mid.png"

DELIVERED_STILLS = (
    WORLD_BEFORE,
    WORLD_AFTER,
    DISTRICT_PAIR_BEFORE,
    DISTRICT_PAIR_AFTER,
    SEAL_RECORDS,
    TRANSITION_MID,
)

EPISODES = ("before", "mid", "after")
LEGS = (("leg1", "before", "mid"), ("leg2", "mid", "after"))

AIR_CHANNEL = "district_air"

DISTRICT_PAIR_LENS_MM = 20.0
SENSOR_WIDTH_MM = 36.0
"""Blender's default sensor width, which the master scene never changes.

The framing distance below is derived from it. Hard-coding a distance instead
would silently reframe -- and could silently crop one of the two districts out
of the comparison -- the day anybody touched the lens."""

DISTRICT_PAIR_FRAMING_MARGIN = 1.08
DISTRICT_PAIR_ELEVATION_DEGREES = 20.0
DISTRICT_PAIR_LOOK_AT_METRES = 12.0
PLATFORM_MARGIN = 0.95
"""How far out on the platform disc a Phase 20 camera may stand.

The world is a round disc. A camera parked beyond its rim looks at the world from
outside the world, and the frames come back black -- an expensive way to discover
a placement rule that is one comparison long."""

TRANSITION_MID_POSITION = 0.5


def sha256_of(path: Path) -> str:
    """SHA-256 of one delivered file."""
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def air_responses(plan: dict) -> dict[str, dict]:
    """Index one plan's district-air responses by district."""
    return {
        response["semantic_id"]: response
        for response in plan["responses"]
        if response["channel"] == AIR_CHANNEL
    }


def choose_comparison_districts(plan: dict) -> tuple[str, str]:
    """Return the most stressed district and the calm one to photograph BESIDE it.

    Chosen from the authoritative readings rather than named in this file: which
    district is starving is the simulation's decision, and a hard-coded district
    id here would keep pointing at the same place the day the world changed.

    The calm half is the lowest reading, and ties are broken by DISTANCE rather
    than by name. "Beside" is meant literally: the further apart the pair, the
    further back the camera has to stand to hold both, and a camera far enough
    back to bracket two opposite rims of the world ends up parked over some third
    district, photographing its stratum in the near field of a frame that is
    supposed to be about two others.

    Args:
        plan: The state response plan of the episode being compared.

    Returns:
        The stressed district id and the calm district id.

    Raises:
        ProofPackageError: If fewer than two districts carry air, or every
            district reads the same -- there is then no contrast to photograph,
            and a frame claiming one would be a lie about a flat world.
    """
    responses = air_responses(plan)
    if len(responses) < 2:
        raise ProofPackageError(
            f"a district comparison needs two districts; the plan carries {len(responses)}"
        )
    ordered = sorted(responses.items(), key=lambda item: (-item[1]["source_value"], item[0]))
    stressed = ordered[0]
    quietest = ordered[-1][1]["source_value"]
    if stressed[1]["source_value"] == quietest:
        raise ProofPackageError(
            f"every district reads {quietest!r}; there is no stressed district to photograph "
            "beside a calm one, and a frame implying otherwise would be a claim the "
            "simulation never made"
        )
    anchor = stressed[1]["field"]["centre"]
    calm = min(
        (entry for entry in ordered[1:] if entry[1]["source_value"] == quietest),
        key=lambda entry: (
            round(
                math.hypot(
                    entry[1]["field"]["centre"][0] - anchor[0],
                    entry[1]["field"]["centre"][1] - anchor[1],
                ),
                6,
            ),
            entry[0],
        ),
    )
    return stressed[0], calm[0]


def _inside_air_volume(location: tuple[float, float, float], plan: dict) -> str:
    """Return the district whose air volume swallows this point, or an empty string.

    A camera standing inside a scatter volume renders a milky rectangle instead
    of a district. The stratum is the subject of this frame, so being inside one
    is not a near miss.
    """
    x, y, z = location
    for district, response in sorted(air_responses(plan).items()):
        field = response["field"]
        centre = field["centre"]
        radius = field["radius"]
        if (
            abs(x - centre[0]) <= radius
            and abs(y - centre[1]) <= radius
            and field["floor"] <= z <= field["ceiling"]
        ):
            return district
    return ""


def district_pair_placement(master_spec: dict, plan: dict) -> dict:
    """Derive where a camera must stand to hold two districts in one frame.

    The distance is computed from the lens, the sensor and the extent that has
    to fit, so the framing is a consequence of the geometry rather than a number
    somebody once eyeballed. Both perpendicular stand-off points are considered
    and the one with the most clearance from the OTHER districts wins, because a
    camera dropped on top of a third district photographs that one instead.

    Args:
        master_spec: The master scene spec, for the platform radius.
        plan: The state response plan whose readings choose the two districts.

    Returns:
        The placement: the two districts, the location, the look-at, the lens,
        and the measurements the choice was made from.

    Raises:
        ProofPackageError: If neither stand-off point is usable.
    """
    stressed, calm = choose_comparison_districts(plan)
    responses = air_responses(plan)
    first = responses[stressed]["field"]
    second = responses[calm]["field"]
    origin_x = (first["centre"][0] + second["centre"][0]) / 2.0
    origin_y = (first["centre"][1] + second["centre"][1]) / 2.0
    span_x = second["centre"][0] - first["centre"][0]
    span_y = second["centre"][1] - first["centre"][1]
    separation = math.hypot(span_x, span_y)
    if separation <= 0.0:
        raise ProofPackageError(
            f"districts {stressed!r} and {calm!r} share one centre; they cannot be "
            "photographed beside each other"
        )
    half_extent = separation / 2.0 + max(first["radius"], second["radius"])
    distance = half_extent * DISTRICT_PAIR_LENS_MM / (SENSOR_WIDTH_MM / 2.0)
    distance *= DISTRICT_PAIR_FRAMING_MARGIN
    elevation = math.radians(DISTRICT_PAIR_ELEVATION_DEGREES)
    reach = distance * math.cos(elevation)
    height = DISTRICT_PAIR_LOOK_AT_METRES + distance * math.sin(elevation)
    normal = (-span_y / separation, span_x / separation)

    platform = float(master_spec["world"]["platform_radius"]) * PLATFORM_MARGIN
    others = {
        district: responses[district]["field"]["centre"]
        for district in responses
        if district not in (stressed, calm)
    }
    refusals: list[str] = []
    usable: list[tuple[float, tuple[float, float], tuple[float, float, float]]] = []
    for sign in (1.0, -1.0):
        location = (
            round(origin_x + sign * normal[0] * reach, 6),
            round(origin_y + sign * normal[1] * reach, 6),
            round(height, 6),
        )
        if math.hypot(location[0], location[1]) > platform:
            refusals.append(f"{location} stands off the platform disc (radius {platform:.3f})")
            continue
        swallowed = _inside_air_volume(location, plan)
        if swallowed:
            refusals.append(f"{location} stands inside {swallowed}'s own air volume")
            continue
        clearance = min(
            (math.hypot(location[0] - x, location[1] - y) for x, y in others.values()),
            default=math.inf,
        )
        usable.append((clearance, (location[0], location[1]), location))
    if not usable:
        raise ProofPackageError(
            f"no usable stand-off point for {stressed!r} beside {calm!r}: {refusals}"
        )
    usable.sort(key=lambda item: (-item[0], item[1]))
    location = usable[0][2]
    return {
        "calm_district": calm,
        "clearance_metres": round(usable[0][0], 6) if others else None,
        "half_extent_metres": round(half_extent, 6),
        "lens_mm": DISTRICT_PAIR_LENS_MM,
        "location": list(location),
        "look_at": [round(origin_x, 6), round(origin_y, 6), DISTRICT_PAIR_LOOK_AT_METRES],
        "rejected": sorted(refusals),
        "separation_metres": round(separation, 6),
        "stand_off_metres": round(distance, 6),
        "stressed_district": stressed,
    }


def plan_record_arc_camera(plan: dict) -> dict:
    """Aim a camera at the record stones the plan actually placed.

    Derived from the stones' own published positions rather than from a
    hard-coded viewpoint, so the framing follows the arc however many stones the
    world has remembered. The camera stands outside the arc looking back toward
    the Seal, which keeps the artifact in shot behind the record without letting
    it become the subject.

    Args:
        plan: The state response plan whose stones are being photographed.

    Returns:
        The placement: location, look-at point, lens and the stones framed.

    Raises:
        ProofPackageError: If the plan placed no record stone to photograph.
    """
    stones = [response for response in plan["responses"] if response["channel"] == "memory_record"]
    if not stones:
        raise ProofPackageError(
            "the plan placed no record stone, so a record framing would photograph nothing; "
            "a proof frame that proves nothing is refused"
        )
    xs = [float(stone["field"]["x"]) for stone in stones]
    ys = [float(stone["field"]["y"]) for stone in stones]
    zs = [float(stone["field"]["z"]) for stone in stones]
    centre = (math.fsum(xs) / len(xs), math.fsum(ys) / len(ys), math.fsum(zs) / len(zs))
    origin = (RECORD_ARC_ORIGIN[0], RECORD_ARC_ORIGIN[1])
    outward_x = centre[0] - origin[0]
    outward_y = centre[1] - origin[1]
    length = math.hypot(outward_x, outward_y) or 1.0
    location = (
        round(centre[0] + (outward_x / length) * RECORD_ARC_STAND_OFF_METRES, 6),
        round(centre[1] + (outward_y / length) * RECORD_ARC_STAND_OFF_METRES, 6),
        round(centre[2] + RECORD_ARC_HEIGHT_METRES, 6),
    )
    return {
        "lens_mm": RECORD_ARC_LENS_MM,
        "location": list(location),
        "look_at": [round(centre[0], 6), round(centre[1], 6), round(centre[2], 6)],
        "stand_off_metres": RECORD_ARC_STAND_OFF_METRES,
        "stones_framed": sorted(stone["target"]["object"] for stone in stones),
    }


def build_record_arc_camera(placement: dict) -> None:
    """Build the Phase-20-owned record-arc camera, replacing any earlier twin."""
    existing = bpy.data.objects.get(RECORD_ARC_CAMERA)
    if existing is not None:
        bpy.data.objects.remove(existing, do_unlink=True)
    data = bpy.data.cameras.get(RECORD_ARC_CAMERA)
    if data is None:
        data = bpy.data.cameras.new(RECORD_ARC_CAMERA)
    data.lens = float(placement["lens_mm"])
    data.clip_end = 1200.0
    data.dof.use_dof = False
    camera = bpy.data.objects.new(RECORD_ARC_CAMERA, data)
    camera.location = tuple(placement["location"])
    camera.rotation_euler = look_at_rotation(
        Vector(placement["location"]), Vector(placement["look_at"])
    )
    collection = bpy.data.collections.get("LD_CAMERAS") or bpy.context.scene.collection
    link_only(camera, collection)


def build_district_pair_camera(placement: dict) -> None:
    """Build the one Phase-20-owned camera, replacing any earlier twin by name.

    Depth of field is deliberately OFF. This is a comparison frame carrying two
    subjects at two different distances, and blurring one of them would decide
    for the reviewer which district the picture is about.
    """
    existing = bpy.data.objects.get(DISTRICT_PAIR_CAMERA)
    if existing is not None:
        bpy.data.objects.remove(existing, do_unlink=True)
    data = bpy.data.cameras.get(DISTRICT_PAIR_CAMERA)
    if data is None:
        data = bpy.data.cameras.new(DISTRICT_PAIR_CAMERA)
    data.lens = float(placement["lens_mm"])
    data.clip_end = 1200.0
    data.dof.use_dof = False
    camera = bpy.data.objects.new(DISTRICT_PAIR_CAMERA, data)
    camera.location = tuple(placement["location"])
    camera.rotation_euler = look_at_rotation(
        Vector(placement["location"]), Vector(placement["look_at"])
    )
    collection = bpy.data.collections.get("LD_CAMERAS") or bpy.context.scene.collection
    link_only(camera, collection)


def require_cameras() -> None:
    """Refuse if any camera this proof photographs from is absent.

    Raises:
        ProofPackageError: If a named camera does not exist, or is not a camera.
    """
    missing = [
        name
        for name in (WORLD_CAMERA, SEAL_CAMERA, DISTRICT_PAIR_CAMERA, RECORD_ARC_CAMERA)
        if getattr(bpy.data.objects.get(name), "type", None) != "CAMERA"
    ]
    if missing:
        raise ProofPackageError(f"the proof cameras were not built: {missing}")


def render_still(
    camera: str, outdir: Path, name: str, frame: int, point: str, episode: str, *, preview: bool
) -> dict:
    """Render one still and return the render-table entry that describes it."""
    scene = bpy.context.scene
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    render_frame(camera, outdir / name, preview=preview)
    return {"camera": camera, "episode": episode, "file": name, "frame": frame, "point": point}


def signal_readings(plans: dict[str, dict]) -> dict:
    """Every authoritative reading this proof rests on, per signal, district and episode.

    Published so the manifest can be checked against the exports it names rather
    than believed. Each entry carries the dotted path it was read from, so a
    reviewer can open the export and look.

    Args:
        plans: The state response plan of each episode, keyed by episode label.

    Returns:
        ``{signal: {district: {episode: reading}}}``, sorted throughout.
    """
    readings: dict[str, dict[str, dict[str, dict]]] = {}
    for label in EPISODES:
        plan = plans[label]
        for district, response in sorted(air_responses(plan).items()):
            field = response["source_field"]
            readings.setdefault(field, {}).setdefault(district, {})[label] = {
                "episode": plan["source"]["episode"],
                "reading": response["source_value"],
                "response_scale": response["response_scale"],
                "source_path": response["source_path"],
                "value": response["value"],
            }
    return {
        signal: {
            district: dict(sorted(episodes.items()))
            for district, episodes in sorted(districts.items())
        }
        for signal, districts in sorted(readings.items())
    }


def write_plan_documents(
    outdir: Path, plans: dict[str, dict], motions: dict[str, dict]
) -> tuple[Path, Path]:
    """Write the two plan documents the manifest's every number is derived from.

    Both are packaged and both are hashed by the inventory. A manifest naming a
    reading, a response or a frame window that a reviewer cannot recompute is a
    claim rather than evidence.
    """
    plans_path = outdir / PLANS_NAME
    plans_path.write_text(
        json.dumps(
            {
                "format": "living_diorama_phase20_state_response_plans",
                "schema_version": 1,
                "plan_hashes": {label: response_plan.plan_hash(plans[label]) for label in EPISODES},
                "plans": {label: plans[label] for label in EPISODES},
            },
            indent=1,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    motion_path = outdir / MOTION_PLANS_NAME
    motion_path.write_text(
        json.dumps(
            {
                "format": "living_diorama_phase20_state_response_motion_plans",
                "schema_version": 1,
                "plan_hashes": {leg: motion_plan.plan_hash(motions[leg]) for leg, _, _ in LEGS},
                "plans": {leg: motions[leg] for leg, _, _ in LEGS},
            },
            indent=1,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return plans_path, motion_path


def _reference(path: Path) -> dict:
    """One packaged artifact, named with the hash and size the package must hold."""
    return {"path": path.name, "sha256": sha256_of(path), "bytes": path.stat().st_size}


def write_state_response_manifest(
    outdir: Path,
    *,
    spec: dict,
    timeline: dict,
    plans: dict[str, dict],
    motions: dict[str, dict],
    verdicts: dict[str, dict],
    static_scene: dict,
    motion_scene: dict[str, dict],
    placement: dict,
    renders: list[dict],
    exports: dict[str, Path],
    plans_path: Path,
    motion_path: Path,
    blend_path: Path,
    base_sha: str,
) -> Path:
    """Write the one manifest that states what this proof shows, and what it does not."""
    animated = sorted(
        {channel for verdict in verdicts.values() for channel in verdict["animated_channels"]}
    )
    document = {
        "artifact": MANIFEST_ARTIFACT,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "base_sha": base_sha,
        "blend": _reference(blend_path),
        "blend_contents": (
            "the episode 2 world with the Phase 20 static layer applied and leg 2 animated "
            "over it, so a reviewer can scrub the leg on which the air does not move and "
            "watch the world remember anyway"
        ),
        "comparison": {
            "calm_district": placement["calm_district"],
            "camera": placement,
            # Re-derived from the render table this manifest is about to publish,
            # so the discipline is checked against what was actually rendered
            # rather than against what this producer intended to render.
            "identical_cameras": require_identical_comparison_cameras(renders),
            "stressed_district": placement["stressed_district"],
        },
        # Straight from apply_state_response_motion.endpoint_equivalence, which is
        # the same function the structural suite asserts on. A verdict rewritten
        # here would be a second opinion nobody tested.
        "endpoint_equivalence": {
            "animated_channels": animated,
            "equivalent": bool(all(verdict["equivalent"] for verdict in verdicts.values())),
            "legs": dict(sorted(verdicts.items())),
        },
        "plan_hashes": {
            **{label: response_plan.plan_hash(plans[label]) for label in EPISODES},
            **{leg: motion_plan.plan_hash(motions[leg]) for leg, _, _ in LEGS},
        },
        "plans": {
            "episodes": {
                label: {
                    "source": plans[label]["source"],
                    "summary": plans[label]["summary"],
                }
                for label in EPISODES
            },
            "legs": {
                leg: {
                    "from": earlier,
                    "summary": motions[leg]["summary"],
                    "to": later,
                }
                for leg, earlier, later in LEGS
            },
        },
        "renders": renders,
        "scene": {"motion": dict(sorted(motion_scene.items())), "static": static_scene},
        "signal_readings": signal_readings(plans),
        "source_export_after": _reference(exports["after"]),
        "source_export_before": _reference(exports["before"]),
        "source_export_mid": _reference(exports["mid"]),
        "state_response_motion_plans": _reference(motion_path),
        "state_response_plans": _reference(plans_path),
        "timeline": dict(sorted(timeline.items())),
        "semantics": {
            "statement": response_plan.REPRESENTATION_STATEMENT,
            "spec_statement": spec["statement"],
            "authoritative": [
                "each district's scarcity, from the render export",
                "the engine's own durable memory facts",
                "the Phase 15 master scene geography and camera anchors",
                "the Phase 17 canonical timeline, borrowed as a clock",
            ],
            "presentation_policy": [
                "how dense a district's air is at a given reading",
                "the fixed, near-achromatic tint of the stratum",
                "where on the Seal plaza arc a record stone stands",
                "which cameras this proof photographs the comparison from",
            ],
            "not_shown": [
                "no video: the still-frame visual language is accepted first",
                "the record stones are a detail-band register and do not read "
                "at the world hero cameras",
                "between episodes 1 and 2 no district's scarcity moves, so that "
                "leg carries no air directive at all -- that is the result, not a gap",
            ],
        },
    }
    target = outdir / MANIFEST_NAME
    write_manifest_json(target, document)
    return target


def main() -> int:
    """Blender entry point: build the responsive world and render its proof."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--production", required=True)
    parser.add_argument("--state-response", required=True)
    parser.add_argument("--motion", required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--mid", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--blend", required=True)
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--preview", action="store_true")
    arguments = parser.parse_args(argv)

    outdir = Path(arguments.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    # The manifest is the LAST file this producer writes, so one already on disk
    # means a completed earlier run's proof pack occupies this directory.
    # Rendering over it would let a crash partway through leave the predecessor's
    # artifacts standing as this run's evidence.
    if (outdir / MANIFEST_NAME).exists():
        raise ProofPackageError(
            f"{outdir} already holds {MANIFEST_NAME} from a completed earlier run; "
            "render this proof into a fresh workspace"
        )

    export_paths = {
        "before": Path(arguments.before),
        "mid": Path(arguments.mid),
        "after": Path(arguments.after),
    }
    master = load_master_scene_spec(arguments.spec)
    spec = load_state_response_spec(arguments.state_response)
    timeline = resolve_state_response_timeline(
        spec, load_motion_time_spec(arguments.motion)["timeline"]
    )

    plans = {
        label: response_plan.plan_state_response(load_render_export(path), master, spec)
        for label, path in export_paths.items()
    }
    for label in EPISODES:
        problems = response_plan.validate_state_response_plan(plans[label])
        if problems:
            raise ProofPackageError(
                f"the {label} state response plan is invalid:\n- " + "\n- ".join(problems[:10])
            )
    motions = {
        leg: motion_plan.plan_state_response_motion(plans[earlier], plans[later], spec, timeline)
        for leg, earlier, later in LEGS
    }
    for leg, _, _ in LEGS:
        problems = motion_plan.validate_state_response_motion_plan(motions[leg])
        if problems:
            raise ProofPackageError(
                f"the {leg} transition plan is invalid:\n- " + "\n- ".join(problems[:10])
            )
    if not motions["leg1"]["directives"]:
        raise ProofPackageError(
            "leg 1 carries no directive; the proof would then be showing a world that "
            "never changed, which is not the world the canonical chain holds"
        )

    build_master_scene.build_master_scene(arguments.spec, style=PROOF_STYLE)
    build_production_world.add_production_world(
        arguments.spec, arguments.production, style=PROOF_STYLE
    )

    placement = district_pair_placement(master, plans["after"])
    build_district_pair_camera(placement)
    record_placement = plan_record_arc_camera(plans["after"])
    build_record_arc_camera(record_placement)
    require_cameras()

    configure_cycles_device()
    configure_sampling(preview=arguments.preview)
    scene = bpy.context.scene
    scene.render.resolution_x = 1280 if arguments.preview else 2560
    scene.render.resolution_y = 720 if arguments.preview else 1440

    renders: list[dict] = []

    # Episode 0: the world before anything happened, on the established anchor.
    apply_render_export.apply_render_export_file(
        arguments.spec, str(export_paths["before"]), style=PROOF_STYLE
    )
    state_response.apply_state_response(plans["before"], spec)
    for camera, name in (
        (WORLD_CAMERA, WORLD_BEFORE),
        (DISTRICT_PAIR_CAMERA, DISTRICT_PAIR_BEFORE),
    ):
        renders.append(
            render_still(
                camera,
                outdir,
                name,
                timeline["start_frame"],
                "episode_0_static",
                "before",
                preview=arguments.preview,
            )
        )

    # Leg 1 leaves its own animated scene standing over the episode 0 world, which
    # is exactly the world that leg opens on, so the mid-transition still is a
    # frame of that transition rather than a composite of two different episodes.
    verdicts: dict[str, dict] = {}
    motion_scene: dict[str, dict] = {}
    verdicts["leg1"] = state_motion.endpoint_equivalence(
        plans["before"], plans["mid"], motions["leg1"], spec, timeline
    )
    state_motion.require_no_stray_animation()
    motion_scene["leg1"] = state_motion.motion_summary()
    renders.append(
        render_still(
            WORLD_CAMERA,
            outdir,
            TRANSITION_MID,
            frame_at(timeline, TRANSITION_MID_POSITION),
            "leg1_transition_mid",
            "before_to_mid",
            preview=arguments.preview,
        )
    )

    verdicts["leg2"] = state_motion.endpoint_equivalence(
        plans["mid"], plans["after"], motions["leg2"], spec, timeline
    )
    state_motion.require_no_stray_animation()
    motion_scene["leg2"] = state_motion.motion_summary()

    # Episode 2: the same two cameras, moved by nothing, over the world the chain
    # ends on. This pair IS the phase's claim.
    apply_render_export.apply_render_export_file(
        arguments.spec, str(export_paths["after"]), style=PROOF_STYLE
    )
    state_response.apply_state_response(plans["after"], spec)
    static_scene = state_response.state_response_summary()
    for camera, name in (
        (WORLD_CAMERA, WORLD_AFTER),
        (DISTRICT_PAIR_CAMERA, DISTRICT_PAIR_AFTER),
        (RECORD_ARC_CAMERA, SEAL_RECORDS),
    ):
        renders.append(
            render_still(
                camera,
                outdir,
                name,
                timeline["end_frame"],
                "episode_2_static",
                "after",
                preview=arguments.preview,
            )
        )

    require_rendered_stills(outdir, DELIVERED_STILLS)

    # The delivered .blend carries leg 2 -- the leg on which the air does not move
    # and a stone appears anyway -- so opening the file and scrubbing shows the
    # result this phase exists for.
    state_motion.apply_state_response_motion(motions["leg2"], timeline)
    state_motion.require_no_stray_animation()

    plans_path, motion_path = write_plan_documents(outdir, plans, motions)
    for label, source in sorted(export_paths.items()):
        carried = outdir / source.name
        if carried.resolve() != source.resolve():
            carried.write_bytes(source.read_bytes())
        export_paths[label] = carried

    blend_path = Path(arguments.blend)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), compress=True)
    write_state_response_manifest(
        outdir,
        spec=spec,
        timeline=timeline,
        plans=plans,
        motions=motions,
        verdicts=verdicts,
        static_scene=static_scene,
        motion_scene=motion_scene,
        placement=placement,
        renders=renders,
        exports=export_paths,
        plans_path=plans_path,
        motion_path=motion_path,
        blend_path=blend_path,
        base_sha=arguments.base_sha,
    )
    print(f"phase 20 proof written to {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
