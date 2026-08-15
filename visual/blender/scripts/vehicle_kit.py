"""The Phase 19 vehicle kit: five procedurally generated semi-stylized cars.

WHAT THIS IS
------------
A deterministic generator for five vehicle ARCHETYPES -- compact, sedan, SUV,
van and sports coupe -- built to sit in a premium miniature diorama. The design
target is:

    A NORMAL VIEWER IMMEDIATELY RECOGNISES A WELL-DESIGNED CAR.

Not photorealism. Not a box that moves. A car whose hood, cabin and tail read
as a car; whose windows are windows; whose doors are findable; whose lights
look like lights; and whose wheels sit inside real arches and visibly turn.

    hull        the lower body, lofted through chamfered cross-sections
    arch        the wheel opening cut into the hull, plus its fender lip
    hood        the bonnet volume ahead of the cabin
    greenhouse  the cabin above the beltline, with its own roofline profile
    deck        the boot volume behind the cabin (three-box archetypes only)
    glazing     windscreen, SPLIT side lights and rear screen as inset panels
    door        readable door seams and sills
    mirror      left and right door mirrors
    lamp        the front light treatment
    tail        the rear light treatment
    wheel       a faceted tyre, emitted in its OWN local frame so it can spin
    hub         the wheel face, in body colour, with an asymmetric witness

    LOCAL +X IS THE DIRECTION THE VEHICLE FACES.

The object's Z rotation turns that into a world heading, exactly as a Phase 18
body's does, so a vehicle's bonnet always points along its lane.

Material slots, in order:

    0  paint      the body colour family
    1  glass      glazing
    2  trim       tyres, bumpers, sills, mirrors, seams -- the dark furniture
    3  lamp       front lights, warm
    4  tail       rear lights, red

THE ENVELOPE IS NOT NEGOTIABLE
------------------------------
The lane network already sized every lane, headway and turning fillet from the
envelope this kit reported BEFORE the visual redesign, and Phase 19's routes,
lane feasibility and canonical fourteen vehicles all descend from those
numbers. :data:`RESERVED_PLANNING_ENVELOPE` pins them. Geometry may be reshaped as
aggressively as it likes INSIDE that box; it may never grow out of it, because
growing out of it would silently invalidate a plan nobody re-ran.

That constraint is also why the wheels are not simply pushed outboard to make
them visible. They stay inside the planned width; the HULL retreats around
them instead, which is what a wheel arch is.

WHAT THIS IS NOT
----------------
A vehicle is a REPRESENTATIVE AMBIENT MOBILITY PROP. It has no driver, no
owner, no passenger, no destination, no cargo and no history; the simulation
does not know it exists. It is also nobody's product: there is no manufacturer,
no model, no badge, no logo and no copied body panel anywhere in this file. An
archetype is a set of numbers and the geometry is generated from them, so a
coupe may read as "an exotic supercar" and must never read as one firm's car.
"""

import math

ARCHETYPES = ("compact", "sedan", "suv", "van", "coupe")

PAINT, GLASS, TRIM, LAMP, TAIL = 0, 1, 2, 3, 4
MATERIAL_SLOTS = ("paint", "glass", "trim", "lamp", "tail")

PAINT_FAMILIES = ("graphite", "bone", "olive", "oxide", "steel", "navy")
"""Muted paint families, chosen to sit inside the city's existing material
range. A diorama of saturated cars would read as scattered sweets against a
charcoal and bone city.

The ORDER is load-bearing: the planner picks a vehicle's colour by indexing
this tuple with its own deterministic generator, so reordering it would repaint
the city's traffic."""

HULL_SIDES = 8
"""Facets around one hull cross-section.

An eight-gon is a rectangle with all four corners chamfered, which is exactly
what a car body section is: flat sides, a flat roof or deck, and a radius at
each corner."""

WHEEL_SIDES = 20
"""Facets around a tyre. Twenty reads as round at diorama distance and keeps a
wheel affordable at four per vehicle."""

GLASS_PROUD = 0.012
"""How far glazing stands off the surface it sits in.

Glass and body must not be coplanar or they z-fight, and a window that floats
too far proud reads as a sticker rather than a screen."""

RESERVED_PLANNING_ENVELOPE = {
    "compact": {"length": 3.82, "width": 1.7648, "height": 1.49},
    "sedan": {"length": 4.66, "width": 1.8830, "height": 1.44},
    "suv": {"length": 4.70, "width": 1.9618, "height": 1.76},
    "van": {"length": 5.16, "width": 2.0012, "height": 2.28},
    "coupe": {"length": 4.46, "width": 1.9815, "height": 1.24},
}
"""The envelope the lane network planned against, measured off the PREVIOUS kit.

Load-bearing. :func:`vehicle_dimensions` is what the planners read, and lane
widths, headways and fillet radii were all derived from these exact numbers
before this file was reshaped. New geometry must measure less than or equal to
them on every axis; the test suite proves it per archetype."""

PROPORTIONS = {
    "compact": {
        "length": 3.78,
        "width": 1.74,
        "height": 1.47,
        "wheelbase": 2.42,
        "track": 1.42,
        "wheel_radius": 0.300,
        "wheel_width": 0.195,
        "ground": 0.145,
        "sill": 0.2,
        "belt": 0.58,
        "cabin_front": 0.14,
        "cabin_rear": -0.48,
        "roof_w": 0.9,
        "shoulder": 1.00,
        "nose_taper": 0.80,
        "tail_taper": 0.88,
        "hood": 0.03,
        "deck": 0.0,
        "windscreen_rake": 0.30,
        "backlight_rake": 0.14,
        "arch_rise": 2.2,
        "arch_flare": 1.00,
    },
    "sedan": {
        "length": 4.62,
        "width": 1.86,
        "height": 1.42,
        "wheelbase": 2.74,
        "track": 1.54,
        "wheel_radius": 0.325,
        "wheel_width": 0.205,
        "ground": 0.150,
        "sill": 0.2,
        "belt": 0.56,
        "cabin_front": 0.06,
        "cabin_rear": -0.44,
        "roof_w": 0.88,
        "shoulder": 1.00,
        "nose_taper": 0.80,
        "tail_taper": 0.84,
        "hood": 0.03,
        "deck": 0.052,
        "windscreen_rake": 0.34,
        "backlight_rake": 0.30,
        "arch_rise": 2.15,
        "arch_flare": 1.00,
    },
    "suv": {
        "length": 4.66,
        "width": 1.94,
        "height": 1.74,
        "wheelbase": 2.78,
        "track": 1.62,
        "wheel_radius": 0.372,
        "wheel_width": 0.235,
        "ground": 0.205,
        "sill": 0.24,
        "belt": 0.53,
        "cabin_front": 0.16,
        "cabin_rear": -0.52,
        "roof_w": 0.92,
        "shoulder": 1.00,
        "nose_taper": 0.88,
        "tail_taper": 0.94,
        "hood": 0.04,
        "deck": 0.0,
        "windscreen_rake": 0.24,
        "backlight_rake": 0.08,
        "arch_rise": 2.2,
        "arch_flare": 1.00,
    },
    "van": {
        "length": 5.10,
        "width": 1.98,
        "height": 2.26,
        "wheelbase": 3.16,
        "track": 1.66,
        "wheel_radius": 0.352,
        "wheel_width": 0.225,
        "ground": 0.190,
        "sill": 0.19,
        "belt": 0.4,
        "cabin_front": 0.32,
        "cabin_rear": -0.5,
        "roof_w": 0.95,
        "shoulder": 1.00,
        "nose_taper": 0.90,
        "tail_taper": 0.98,
        "hood": 0.02,
        "deck": 0.0,
        "windscreen_rake": 0.22,
        "backlight_rake": 0.03,
        "arch_rise": 2.2,
        "arch_flare": 1.00,
    },
    "coupe": {
        "length": 4.42,
        "width": 1.96,
        "height": 1.08,
        "wheelbase": 2.60,
        "track": 1.66,
        "wheel_radius": 0.335,
        "wheel_width": 0.250,
        "ground": 0.105,
        "sill": 0.155741,
        "belt": 0.708889,
        # The cabin fractions are the coupe's OWN canopy run, so that
        # cabin_frame reports the volume the coupe actually builds: a compact,
        # cab-forward cell from 1.42 m ahead of centre to 0.50 m behind it.
        "cabin_front": 0.321267,
        "cabin_rear": -0.113122,
        "roof_w": 0.74,
        "shoulder": 1.00,
        "nose_taper": 0.82,
        "tail_taper": 0.90,
        "hood": 0.045,
        "deck": 0.082,
        "windscreen_rake": 0.55,
        "backlight_rake": 0.42,
        "arch_rise": 2.05,
        "arch_flare": 1.00,
    },
}
"""Vehicle proportions, in metres except where a fraction is named.

``sill`` and ``belt`` are fractions of total height: the bottom of the visible
body side, and the line where the body stops and the glass starts. ``hood`` and
``deck`` are fractions of height for the bonnet and boot decks -- ``deck`` of
zero means a two-box archetype whose cabin runs to the tail, which is what
makes the compact a hatch, the SUV an estate and the van a van. ``cabin_front``
and ``cabin_rear`` are fractions of length measured from the CENTRE, so the
cabin can be pushed back (coupe) or pulled forward over the front axle (van).
``roof_w`` is the roof's share of body width -- the tumblehome. ``*_rake`` are
the horizontal run of the windscreen and backlight as a fraction of height, so
a bigger number is a more steeply laid-back screen. ``arch_rise`` is how far
above the wheel centre the arch is cut, in wheel radii.

The five sets are what makes the archetypes survive silhouette inspection: the
coupe is the lowest (1.08 m) and among the widest with the most rearward cabin
and the hardest raked screens; the van is the tallest (2.26 m) with a cab
pushed right forward and a near-vertical tail; the SUV is tall, upright and
rides highest; the sedan carries a real boot deck the compact does not have.

These are DESIGN numbers, and nobody plans against them. What the planners
read is :func:`vehicle_dimensions`, which reports the RESERVATION; what the
geometry is measured to occupy is :func:`measured_visual_bounds`; and
:func:`envelope_contract` states both, side by side, with the proof that the
second fits inside the first."""


class VehicleKitError(ValueError):
    """A vehicle kit contract violation. Always a refusal, never a repair."""


def _require_archetype(name: str) -> dict:
    """Return one archetype's proportions, refusing anything unknown."""
    if name not in PROPORTIONS:
        raise VehicleKitError(f"unknown vehicle archetype {name!r}; expected one of {ARCHETYPES}")
    return PROPORTIONS[name]


# ---------------------------------------------------------------------------
# Primitive assembly
# ---------------------------------------------------------------------------


def _primitive(name: str, kind: str, material: int, vertices: list, faces: list) -> dict:
    """One named lump of geometry, in its own local frame."""
    return {
        "name": name,
        "kind": kind,
        "material": material,
        "vertices": [(float(x), float(y), float(z)) for x, y, z in vertices],
        "faces": [tuple(int(index) for index in face) for face in faces],
    }


def _section(x: float, half_width: float, low: float, high: float, chamfer: float) -> list:
    """One chamfered rectangular cross-section at station ``x``.

    Eight points around the section. The chamfer is clamped so a section can
    never turn itself inside out when a roof is narrower than its own corner
    radius, and a minimum span keeps a collapsed section from emitting a
    zero-area face.
    """
    span = max(high - low, 1.0e-4)
    high = low + span
    half_width = max(half_width, 1.0e-3)
    cut = max(0.0, min(chamfer, half_width * 0.45, span * 0.45))
    return [
        (x, half_width, low + cut),
        (x, half_width - cut, low),
        (x, -half_width + cut, low),
        (x, -half_width, low + cut),
        (x, -half_width, high - cut),
        (x, -half_width + cut, high),
        (x, half_width - cut, high),
        (x, half_width, high - cut),
    ]


def _loft(name: str, kind: str, material: int, sections: list) -> dict:
    """Skin a run of equal-sized sections, capped at both ends."""
    sides = len(sections[0])
    vertices: list = []
    for section in sections:
        if len(section) != sides:
            raise VehicleKitError(f"{name} lofts sections of different sizes")
        vertices.extend(section)
    faces: list = []
    for band in range(len(sections) - 1):
        base = band * sides
        for index in range(sides):
            nxt = (index + 1) % sides
            faces.append((base + index, base + nxt, base + sides + nxt, base + sides + index))
    for index in range(1, sides - 1):
        faces.append((0, index + 1, index))
    tail = (len(sections) - 1) * sides
    for index in range(1, sides - 1):
        faces.append((tail, tail + index, tail + index + 1))
    return _primitive(name, kind, material, vertices, faces)


def _quad(name: str, kind: str, material: int, corners: list) -> dict:
    """One flat quad -- a screen, a side light, a seam, a plate."""
    return _primitive(name, kind, material, corners, [(0, 1, 2, 3)])


def _slab(name: str, kind: str, material: int, low: tuple, high: tuple) -> dict:
    """One axis-aligned box between two opposite corners."""
    x0, y0, z0 = low
    x1, y1, z1 = high
    vertices = [
        (x0, y0, z0),
        (x1, y0, z0),
        (x1, y1, z0),
        (x0, y1, z0),
        (x0, y0, z1),
        (x1, y0, z1),
        (x1, y1, z1),
        (x0, y1, z1),
    ]
    faces = [
        (3, 2, 1, 0),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    return _primitive(name, kind, material, vertices, faces)


def _disc_ring(radius: float, y: float, sides: int, phase: float = 0.0) -> list:
    """One circle of a wheel, in the wheel's own frame (axle along Y)."""
    step = math.pi / sides + phase
    return [
        (
            radius * math.cos(2.0 * math.pi * index / sides + step),
            y,
            radius * math.sin(2.0 * math.pi * index / sides + step),
        )
        for index in range(sides)
    ]


# ---------------------------------------------------------------------------
# The shape of one archetype
# ---------------------------------------------------------------------------


def cabin_frame(archetype: str) -> dict:
    """Where the cabin starts, stops, and how high it stands."""
    p = _require_archetype(archetype)
    length, height = float(p["length"]), float(p["height"])
    belt = height * float(p["belt"])
    return {
        "front": length * float(p["cabin_front"]),
        "rear": length * float(p["cabin_rear"]),
        "roof": height,
        "belt": belt,
        "roof_drop": round(height - belt, 6),
        "sill": height * float(p["sill"]),
        "hood": belt + height * float(p["hood"]),
        "deck": belt + height * float(p["deck"]) if float(p["deck"]) else belt,
        "three_box": float(p["deck"]) > 0.0,
    }


def _axle_x(archetype: str) -> tuple:
    """Front and rear axle stations."""
    p = _require_archetype(archetype)
    half = float(p["wheelbase"]) / 2.0
    return half, -half


def _hull_stations(archetype: str) -> list:
    """The longitudinal stations of the lower body, nose to tail.

    Each station carries a half width and the height band the body occupies
    there. The band's FLOOR is what carves the wheel arches: over an axle it
    lifts to just above the wheel centre, so the opening is a real recess in
    the silhouette rather than a slab with a tyre poking out from under it.
    """
    p = _require_archetype(archetype)
    length, height = float(p["length"]), float(p["height"])
    half_w = float(p["width"]) / 2.0
    front_axle, rear_axle = _axle_x(archetype)
    radius = float(p["wheel_radius"])
    sill = height * float(p["sill"])
    belt = height * float(p["belt"])
    nose, tail = length / 2.0, -length / 2.0
    shoulder = half_w * float(p["shoulder"])
    # The shoulder LINE -- the height of the body side along the car. Holding it
    # flat from nose to tail is what makes a generated body read as a slab; a
    # wedge that falls towards the nose is most of what separates an exotic from
    # a low saloon. Defaults reproduce the flat line.
    nose_line = belt * float(p.get("nose_line", 0.90))
    nose_shoulder = belt * float(p.get("nose_shoulder", 0.98))
    tail_line = belt * float(p.get("tail_line", 0.94))

    def arch_floor(offset: float) -> float:
        """The opening height a distance ``offset`` along the body from an axle.

        FOLLOWS THE WHEEL. A straight V-notch between two stations leaves the
        tyre buried in the fender everywhere except directly under the apex --
        measured at up to 52 per cent of the tyre on the coupe -- because a
        wheel is a circle and a two-station cut is a triangle. This traces the
        circle and adds the clearance ``arch_rise`` asks for at the apex.
        """
        span = radius * radius - offset * offset
        if span <= 0.0:
            return sill
        return max(sill, radius + math.sqrt(span) + radius * (float(p["arch_rise"]) - 2.0))

    def wheel_stations(axle: float) -> list:
        cuts = (-1.15, -0.90, -0.70, -0.40, 0.0, 0.40, 0.70, 0.90, 1.15)
        return [(axle + radius * step, shoulder, arch_floor(radius * step), belt) for step in cuts]

    plan = [
        (tail, half_w * float(p["tail_taper"]), sill + 0.03, tail_line),
        (tail + length * 0.045, half_w * 0.97, sill, belt),
        *wheel_stations(rear_axle),
        (rear_axle * 0.30, half_w * 0.985, sill, belt),
        (front_axle * 0.30, half_w * 0.985, sill, belt),
        *wheel_stations(front_axle),
        (nose - length * 0.045, half_w * 0.97, sill, nose_shoulder),
        (nose, half_w * float(p["nose_taper"]), sill + 0.03, nose_line),
    ]
    return [{"x": x, "half": hw, "low": low, "high": high} for x, hw, low, high in plan]


def _hull_half_at(archetype: str, x: float) -> float:
    """The hull's own half width at station ``x``, interpolated between stations.

    Door furniture positioned from a flat fraction of body width floats off a
    body that tapers and chamfers -- measured at up to 211 mm of standoff, which
    is a dark stripe hanging in the air beside the car. Anything that must lie ON
    the flank asks here instead.
    """
    stations = _hull_stations(archetype)
    if x <= stations[0]["x"]:
        return stations[0]["half"]
    if x >= stations[-1]["x"]:
        return stations[-1]["half"]
    for first, second in zip(stations, stations[1:], strict=False):
        if first["x"] <= x <= second["x"]:
            reach = second["x"] - first["x"]
            fraction = 0.0 if reach <= 0.0 else (x - first["x"]) / reach
            return first["half"] + fraction * (second["half"] - first["half"])
    return stations[-1]["half"]


def _hull_flank_band(archetype: str, x: float) -> tuple:
    """The z range over which a shared hull's flat flank exists at station ``x``.

    The flank is only flat between the chamfered corners, and over a wheel the
    section floor lifts to carve the arch, so the band both rises and shrinks
    there. Interpolated between stations the way the loft's own chords run,
    because the answer that matters is where the emitted triangles are, not
    where the design curve is. Anything drawn on the side has to stay inside
    it: the sedan's rear door seam once ran 317 mm below this band, a trim
    strip hanging in open air across the wheel opening.
    """
    p = _require_archetype(archetype)
    chamfer = float(p["width"]) * 0.055
    stations = _hull_stations(archetype)

    def corners(entry: dict) -> tuple:
        span = max(entry["high"] - entry["low"], 1.0e-4)
        cut = max(0.0, min(chamfer, entry["half"] * 0.45, span * 0.45))
        return entry["low"] + cut, entry["low"] + span - cut

    if x <= stations[0]["x"]:
        return corners(stations[0])
    if x >= stations[-1]["x"]:
        return corners(stations[-1])
    for first, second in zip(stations, stations[1:], strict=False):
        if first["x"] <= x <= second["x"]:
            reach = second["x"] - first["x"]
            fraction = 0.0 if reach <= 0.0 else (x - first["x"]) / reach
            a, b = corners(first), corners(second)
            return a[0] + fraction * (b[0] - a[0]), a[1] + fraction * (b[1] - a[1])
    return corners(stations[-1])


def _hull(archetype: str) -> dict:
    """The lower body: one lofted solid carrying its own wheel arches."""
    p = _require_archetype(archetype)
    chamfer = float(p["width"]) * 0.055
    sections = [
        _section(entry["x"], entry["half"], entry["low"], entry["high"], chamfer)
        for entry in _hull_stations(archetype)
    ]
    return _loft("hull", "hull", PAINT, sections)


def _hood(archetype: str) -> dict | None:
    """The bonnet volume between the cabin and the nose."""
    p = _require_archetype(archetype)
    length = float(p["length"])
    half_w = float(p["width"]) / 2.0
    frame = cabin_frame(archetype)
    nose = length / 2.0
    front = frame["front"]
    if nose - front < 0.25:
        return None
    chamfer = half_w * 0.10
    # A bonnet that stays level while the shoulder line dives leaves a slab
    # floating over the drop. It follows the wedge down instead.
    fall = frame["belt"] * float(p.get("hood_fall", 0.0))
    sections = [
        _section(front, half_w * 0.94, frame["belt"], frame["hood"], chamfer),
        _section(
            front + (nose - front) * 0.55, half_w * 0.92, frame["belt"], frame["hood"], chamfer
        ),
        _section(
            nose - length * 0.02,
            half_w * 0.84,
            frame["belt"] - fall,
            frame["hood"] * 0.96 - fall,
            chamfer,
        ),
    ]
    return _loft("hood", "hood", PAINT, sections)


def _deck(archetype: str) -> dict | None:
    """The boot volume behind the cabin -- what makes a three-box car."""
    p = _require_archetype(archetype)
    if not float(p["deck"]):
        return None
    length = float(p["length"])
    half_w = float(p["width"]) / 2.0
    frame = cabin_frame(archetype)
    tail = -length / 2.0
    rear = frame["rear"]
    if rear - tail < 0.15:
        return None
    chamfer = half_w * 0.10
    sections = [
        _section(tail + length * 0.02, half_w * 0.84, frame["belt"], frame["deck"] * 0.96, chamfer),
        _section(tail + (rear - tail) * 0.5, half_w * 0.92, frame["belt"], frame["deck"], chamfer),
        _section(rear, half_w * 0.94, frame["belt"], frame["deck"], chamfer),
    ]
    return _loft("deck", "deck", PAINT, sections)


def _greenhouse_stations(archetype: str) -> list:
    """The cabin's own longitudinal stations, from screen base to backlight."""
    p = _require_archetype(archetype)
    height = float(p["height"])
    half_w = float(p["width"]) / 2.0
    roof_half = half_w * float(p["roof_w"])
    frame = cabin_frame(archetype)
    belt, roof = frame["belt"], frame["roof"]
    front, rear = frame["front"], frame["rear"]
    if not frame["three_box"]:
        # A hatch, an estate and a van have no boot: the cabin runs to the tail.
        # Stopping it at the cabin station instead would leave a flat deck
        # behind every one of them, and three of the five archetypes would read
        # as saloons.
        rear = -float(p["length"]) / 2.0 + float(p["length"]) * 0.045
    rake = height * float(p["windscreen_rake"])
    fall = height * float(p["backlight_rake"])

    roof_front = front - rake
    roof_rear = rear + fall
    if roof_front <= roof_rear:
        middle = (front + rear) / 2.0
        roof_front, roof_rear = middle + 0.10, middle - 0.10
    return [
        {"x": front, "half": roof_half * 0.90, "low": belt, "high": belt + (roof - belt) * 0.12},
        {"x": roof_front, "half": roof_half, "low": belt, "high": roof},
        {"x": (roof_front + roof_rear) / 2.0, "half": roof_half, "low": belt, "high": roof},
        {"x": roof_rear, "half": roof_half, "low": belt, "high": roof * 0.995},
        {"x": rear, "half": roof_half * 0.92, "low": belt, "high": belt + (roof - belt) * 0.16},
    ]


def _greenhouse(archetype: str) -> dict:
    """The cabin: raked screen, roof, falling backlight, tumblehome sides."""
    p = _require_archetype(archetype)
    chamfer = float(p["width"]) * 0.05
    sections = [
        _section(entry["x"], entry["half"], entry["low"], entry["high"], chamfer)
        for entry in _greenhouse_stations(archetype)
    ]
    return _loft("greenhouse", "greenhouse", PAINT, sections)


# ---------------------------------------------------------------------------
# Glazing -- windscreen, SPLIT side lights, rear screen
# ---------------------------------------------------------------------------


SCREEN_PROUD = 0.004
"""How far a windscreen or backlight stands off the roofline.

Much smaller than :data:`GLASS_PROUD`, which is a flank measurement. A screen
sits on the car's SILHOUETTE, so a centimetre of lift would show as a lip along
the roof; four millimetres is enough to beat z-fighting and invisible from
any distance a reviewer will ever watch this city from."""


def _outset(x0: float, z0: float, x1: float, z1: float) -> tuple:
    """How far to lift a screen off the cabin plane it lies on.

    A screen drawn ON the roofline is coplanar with the paint and renders as
    z-fighting speckle at best and as nothing at all at worst -- which is
    exactly what buried glazing did to the first cut of this kit. The offset
    runs along the plane's own outward normal, so a raked screen lifts forward
    AND up rather than simply upward.
    """
    run, rise = x1 - x0, z1 - z0
    length = math.hypot(run, rise)
    if length < 1.0e-9:
        return 0.0, SCREEN_PROUD
    return SCREEN_PROUD * rise / length, -SCREEN_PROUD * run / length


def _glazing(archetype: str) -> list:
    """Every window, standing PROUD of the cabin it belongs to.

    Side glazing is SPLIT: a front light and a rear light with a readable B
    pillar between them, because one long black slab down the side is the exact
    thing that makes a generated car read as a box.

    Four archetypes come through here. The coupe does not: it builds its own
    glazing against its own canopy, in :func:`_coupe_glazing`.
    """
    p = _require_archetype(archetype)
    height = float(p["height"])
    stations = _greenhouse_stations(archetype)
    frame = cabin_frame(archetype)
    belt, roof = frame["belt"], frame["roof"]
    cowl, screen_top, roof_rear, backlight = stations[0], stations[1], stations[3], stations[4]
    glass_low = belt + (roof - belt) * 0.10
    pieces = []

    # Windscreen: cowl top to roof front, standing OUTSIDE the cabin skin.
    screen_half = min(cowl["half"], screen_top["half"]) * 0.94
    lift_x, lift_z = _outset(cowl["x"], cowl["high"], screen_top["x"], screen_top["high"])
    pieces.append(
        _quad(
            "windscreen",
            "glazing",
            GLASS,
            [
                (cowl["x"] + lift_x, screen_half, cowl["high"] + lift_z),
                (cowl["x"] + lift_x, -screen_half, cowl["high"] + lift_z),
                (screen_top["x"] + lift_x, -screen_half * 0.96, screen_top["high"] + lift_z),
                (screen_top["x"] + lift_x, screen_half * 0.96, screen_top["high"] + lift_z),
            ],
        )
    )

    # Rear screen: roof rear down to the backlight base.
    rear_half = min(roof_rear["half"], backlight["half"]) * 0.94
    fall_x, fall_z = _outset(roof_rear["x"], roof_rear["high"], backlight["x"], backlight["high"])
    pieces.append(
        _quad(
            "rear_screen",
            "glazing",
            GLASS,
            [
                (roof_rear["x"] + fall_x, -rear_half * 0.96, roof_rear["high"] + fall_z),
                (roof_rear["x"] + fall_x, rear_half * 0.96, roof_rear["high"] + fall_z),
                (backlight["x"] + fall_x, rear_half, backlight["high"] + fall_z),
                (backlight["x"] + fall_x, -rear_half, backlight["high"] + fall_z),
            ],
        )
    )

    # Side lights. The pillar gap is real geometry: the panes stop short of it.
    door_front = screen_top["x"] - height * 0.02
    door_rear = roof_rear["x"] + height * 0.02
    span = door_front - door_rear
    pillar = max(span * 0.055, 0.055)
    glass_high = roof - (roof - belt) * 0.14

    for side, sign in (("l", 1.0), ("r", -1.0)):
        half = min(screen_top["half"], roof_rear["half"]) + GLASS_PROUD
        split = door_rear + span * 0.52
        pieces.append(
            _quad(
                f"side_glass_front_{side}",
                "glazing",
                GLASS,
                [
                    (door_front, sign * half, glass_low),
                    (split, sign * half, glass_low),
                    (split, sign * half, glass_high),
                    (door_front, sign * half, glass_high * 0.94),
                ],
            )
        )
        pieces.append(
            _quad(
                f"side_glass_rear_{side}",
                "glazing",
                GLASS,
                [
                    (split - pillar, sign * half, glass_low),
                    (door_rear, sign * half, glass_low),
                    (door_rear, sign * half, glass_high * 0.92),
                    (split - pillar, sign * half, glass_high),
                ],
            )
        )
    return pieces


# ---------------------------------------------------------------------------
# Doors, sills, mirrors
# ---------------------------------------------------------------------------


def _doors(archetype: str) -> list:
    """Door seams and sills: where a viewer reads 'this opens'.

    Seams are thin proud strips in trim rather than cuts in the hull, because a
    boolean cut would cost far more geometry than the read is worth and would
    fight the bevel the applier puts on every panel edge.
    """
    p = _require_archetype(archetype)
    height = float(p["height"])
    half_w = float(p["width"]) / 2.0
    frame = cabin_frame(archetype)
    stations = _greenhouse_stations(archetype)
    belt, sill = frame["belt"], frame["sill"]
    door_front = stations[1]["x"] - height * 0.02
    door_rear = stations[3]["x"] + height * 0.02
    span = door_front - door_rear
    seams = [door_front, door_rear + span * 0.52, door_rear]
    thickness = 0.014

    # Door furniture must stop clear of the wheel openings. On a low car the
    # sill line falls BELOW the axle, so a strip drawn the full length of the
    # cabin reaches across the arch and hides the very hub the traffic proof
    # exists to show.
    front_axle, rear_axle = _axle_x(archetype)
    clear = float(p["wheel_radius"]) * 1.15
    sill_front = min(door_front, front_axle - clear)
    sill_rear = max(door_rear, rear_axle + clear)
    if sill_front <= sill_rear:
        sill_front, sill_rear = door_front, door_rear
    # Keep the furniture off the chamfered corners: the flank is only flat
    # between them, and a strip drawn across a corner lifts away from the paint.
    cut = max(0.0, min(float(p["width"]) * 0.055, half_w * 0.45, (belt - sill) * 0.45))
    low, high = sill + cut, belt - cut
    proud = 0.003
    pieces = []
    for side, sign in (("l", 1.0), ("r", -1.0)):
        for index, x in enumerate(seams):
            # Each seam is bounded by the flank IT is drawn on, not by the
            # car's overall sill and beltline. On a long saloon the rear cut
            # lands where the fender has already lifted away for the wheel, so
            # a seam given the body's lowest sill height hangs in open air over
            # the tyre -- measured at 317 mm on the sedan. Bounded over the
            # seam's OWN width, because the strip is 28 mm across and the flank
            # it lies on climbs steeply over a wheel. A seam whose band has
            # shrunk to a stub is not drawn at all: a 20 mm scratch beside a
            # wheel opening reads as damage, not as a door.
            edges = [
                _hull_flank_band(archetype, x - thickness),
                _hull_flank_band(archetype, x + thickness),
            ]
            seam_low = max(low, max(edge[0] for edge in edges))
            seam_high = min(high, min(edge[1] for edge in edges))
            if seam_high - seam_low < 0.05:
                continue
            face = sign * (_hull_half_at(archetype, x) + proud)
            pieces.append(
                _quad(
                    f"door_seam_{index}_{side}",
                    "door",
                    TRIM,
                    [
                        (x - thickness, face, seam_low),
                        (x + thickness, face, seam_low),
                        (x + thickness, face, seam_high),
                        (x - thickness, face, seam_high),
                    ],
                )
            )
        rear_face = sign * (_hull_half_at(archetype, sill_rear) + proud)
        front_face = sign * (_hull_half_at(archetype, sill_front) + proud)
        pieces.append(
            _quad(
                f"door_sill_{side}",
                "door",
                TRIM,
                [
                    (sill_rear, rear_face, low),
                    (sill_front, front_face, low),
                    (sill_front, front_face, low + height * 0.035),
                    (sill_rear, rear_face, low + height * 0.035),
                ],
            )
        )
        handle_x = door_rear + span * 0.62
        handle_face = _hull_half_at(archetype, handle_x)
        lo, hi = sorted((sign * handle_face, sign * (handle_face + 0.010)))
        pieces.append(
            _slab(
                f"door_handle_{side}",
                "door",
                TRIM,
                (handle_x - 0.07, lo, high - height * 0.055),
                (handle_x + 0.07, hi, high - height * 0.025),
            )
        )
    return pieces


def _mirrors(archetype: str) -> list:
    """Door mirrors at the A pillar, inside the planned width."""
    p = _require_archetype(archetype)
    height = float(p["height"])
    half_w = float(p["width"]) / 2.0
    frame = cabin_frame(archetype)
    stations = _greenhouse_stations(archetype)
    x = stations[1]["x"] - height * 0.03
    z = frame["belt"] + (frame["roof"] - frame["belt"]) * 0.16
    depth = 0.085 if archetype in ("van", "suv") else 0.070
    pieces = []
    for side, sign in (("l", 1.0), ("r", -1.0)):
        # Start at the CABIN's own flank, not at a fraction of body width. The
        # cabin is narrower than the body, so anchoring to the body left the
        # coupe's mirrors hanging 117 mm out in open air with no arm.
        cabin_half = stations[1]["half"]
        inner = sign * cabin_half * 0.98
        # The arm grows to suit the cabin. A mirror sits near a car's widest
        # point whatever the cockpit is doing, and the exotic's cabin is far
        # narrower than its rear haunches, so a fixed stub would leave its
        # mirrors tucked inside the bodywork where a driver could not use them.
        reach = max(depth, half_w * 0.94 - cabin_half)
        outer = sign * min(half_w * 0.995, cabin_half + reach)
        low, high = sorted((inner, outer))
        pieces.append(
            _slab(
                f"mirror_{side}",
                "mirror",
                TRIM,
                (x - 0.055, low, z),
                (x + 0.055, high, z + height * 0.055),
            )
        )
    return pieces


# ---------------------------------------------------------------------------
# Lights and fascias
# ---------------------------------------------------------------------------


def _lights(archetype: str) -> list:
    """Front and rear light treatments, and the dark fascias they sit in.

    The two families are deliberately different shapes as well as different
    materials: a headlight is a wide shallow lens set into the nose, a tail
    light is a taller blade at the corner of the tail. No real signature is
    copied; these are original rectangular-family forms.
    """
    p = _require_archetype(archetype)
    length, height = float(p["length"]), float(p["height"])
    half_w = float(p["width"]) / 2.0
    frame = cabin_frame(archetype)
    nose, tail = length / 2.0, -length / 2.0
    belt = frame["belt"]
    # Lights sit in the painted hull band, which runs sill-to-belt. Taking a
    # fraction of the beltline alone put the van's lamps 295 mm below any
    # bodywork, floating in front of the vehicle; the lens heights below are
    # fractions of the band the nose and tail caps actually span.
    # A lens must stand PROUD of the end cap it sits in. Set 5 mm behind it, as
    # these were, a light is inside the paint and renders as nothing at all --
    # measured at zero visible lens area on eight of the ten light families. The
    # lens is also sized from the hull's OWN section at the nose and tail, so it
    # cannot be wider than the bodywork it is let into.
    nose_half = half_w * float(p["nose_taper"])
    tail_half = half_w * float(p["tail_taper"])
    nose_low, nose_high = frame["sill"] + 0.03, belt * 0.90
    tail_low, tail_high = frame["sill"] + 0.03, belt * 0.94
    lamp_z = nose_low + (nose_high - nose_low) * 0.62
    tail_z = tail_low + (tail_high - tail_low) * 0.60
    lamp_half = (nose_high - nose_low) * 0.17
    tail_half_z = (tail_high - tail_low) * 0.19
    pieces = []

    for side, sign in (("l", 1.0), ("r", -1.0)):
        lo, hi = sorted((sign * nose_half * 0.32, sign * nose_half * 0.84))
        pieces.append(
            _slab(
                f"headlight_{side}",
                "lamp",
                LAMP,
                (nose - 0.11, lo, lamp_z - lamp_half),
                (nose + SCREEN_PROUD, hi, lamp_z + lamp_half),
            )
        )
        lo, hi = sorted((sign * tail_half * 0.30, sign * tail_half * 0.86))
        pieces.append(
            _slab(
                f"taillight_{side}",
                "tail",
                TAIL,
                (tail - SCREEN_PROUD, lo, tail_z - tail_half_z),
                (tail + 0.11, hi, tail_z + tail_half_z),
            )
        )

    pieces.append(
        _slab(
            "front_fascia",
            "fascia",
            TRIM,
            (nose - 0.14, -half_w * 0.66, frame["sill"] * 0.72),
            (nose - 0.01, half_w * 0.66, lamp_z - height * 0.055),
        )
    )
    pieces.append(
        _slab(
            "rear_fascia",
            "fascia",
            TRIM,
            (tail + 0.01, -half_w * 0.62, frame["sill"] * 0.72),
            (tail + 0.14, half_w * 0.62, tail_z - height * 0.065),
        )
    )
    pieces.append(
        _quad(
            "plate_recess",
            "fascia",
            TRIM,
            [
                (tail + 0.008, -half_w * 0.22, frame["sill"] * 0.92),
                (tail + 0.008, half_w * 0.22, frame["sill"] * 0.92),
                (tail + 0.008, half_w * 0.22, frame["sill"] * 0.92 + height * 0.07),
                (tail + 0.008, -half_w * 0.22, frame["sill"] * 0.92 + height * 0.07),
            ],
        )
    )
    return pieces


def _arches(archetype: str) -> list:
    """The fender lip around each wheel opening.

    The opening itself is carved by :func:`_hull_stations`; this is the raised
    rim that makes it read as an arch rather than as a hole. It follows the top
    half of the wheel and stays inside the planned width.
    """
    p = _require_archetype(archetype)
    half_w = float(p["width"]) / 2.0
    radius = float(p["wheel_radius"])
    track = float(p["track"]) / 2.0
    width = float(p["wheel_width"])
    front_axle, rear_axle = _axle_x(archetype)
    # The lip rims the OPENING, so its radius is the opening's own radius.
    # Scaling it down vertically made an ellipse flatter than the wheel: the
    # apex then sat below the hull cut it was meant to trace and 29-35 mm INSIDE
    # the rubber, which is a paint-coloured bar drawn across the tyre.
    lip = radius * (float(p["arch_rise"]) - 1.0)
    outer = min(half_w * 0.999, track + width / 2.0 + 0.030)
    inner = max(0.0, outer - 0.075)
    steps = 9
    pieces = []
    for axle_name, axle in (("f", front_axle), ("r", rear_axle)):
        for side, sign in (("l", 1.0), ("r", -1.0)):
            ring_in, ring_out = [], []
            for index in range(steps):
                angle = math.pi * index / (steps - 1)
                x = axle + lip * math.cos(angle)
                z = radius + lip * math.sin(angle)
                ring_in.append((x, sign * inner, z))
                ring_out.append((x, sign * outer, z))
            vertices = ring_in + ring_out
            faces = [
                (i, i + 1, steps + i + 1, steps + i)
                if sign > 0
                else (steps + i, steps + i + 1, i + 1, i)
                for i in range(steps - 1)
            ]
            pieces.append(_primitive(f"arch_{axle_name}{side}", "arch", PAINT, vertices, faces))
    return pieces


# ---------------------------------------------------------------------------
# The exotic coupe, on a hull of its own
# ---------------------------------------------------------------------------
#
# WHY THE COUPE LEFT THE SHARED PIPELINE
# --------------------------------------
# Every other archetype is a lower body with a cabin standing on it, and that
# construction is honest for a hatch, an estate, a saloon and a van. It cannot
# produce an exotic. Measured on the shared builder, the coupe's shoulder line
# was flat to within 15 mm over 95 per cent of its length, its cabin was inset
# 255 mm per side from a constant-width slab, and the hull's top and the
# cabin's floor met as two coincident flat planes at every station along the
# car. That is a greenhouse dropped onto a board, and no amount of tuning the
# shared dials moves it, because the dials cannot vary a width along the body.
#
# So the coupe gets its own longitudinal profile. The volumes below are still
# separate primitives -- the suite recovers a hull, a cabin and a boot by
# measuring them, and it is right to -- but they are cut so the SILHOUETTE is
# continuous:
#
#     low nose -> rising shoulder -> windscreen -> compact canopy ->
#     buttress -> wide rear haunch -> tail
#
# The two things that make it read as one form are that the hull's top FALLS
# away ahead of the cowl instead of running flat to the nose, and that the
# body's half width VARIES along the car -- waisted at the door, swollen over
# the rear axle. The cabin then sits in a body that is visibly wider than it
# is, which is what a mid-engined car looks like from any angle.


COUPE_ARCH_CUTS = (
    -1.035,
    -1.020,
    -1.000,
    -0.970,
    -0.920,
    -0.820,
    -0.620,
    -0.340,
    0.000,
    0.340,
    0.620,
    0.820,
    0.920,
    0.970,
    1.000,
    1.020,
    1.035,
)
"""Where the coupe cuts a hull section near a wheel, in wheel radii from the axle.

A wheel is a circle and a loft is a run of chords, so a coarse cut buries the
tyre wherever the chord falls inside the arc -- which is how the shared builder
left 6.25 per cent of this car's tyre outline inside its own fender. The cuts
crowd towards the tangent because that is where an arc departs fastest from its
chord. Worst sag over this run is 7 mm, against 16.75 mm of arch clearance."""

COUPE_FRONT_ARCH_RISE = 2.05
COUPE_REAR_ARCH_RISE = 2.12
"""How far above the wheel centre each arch is cut, in wheel radii.

The rear is cut higher than the front deliberately: it leaves more fender over
the rear tyre, and a mid-engined car carries its visual mass at the back."""

COUPE_HULL_PROFILE = (
    {"x": -2.2100, "rocker": 0.730, "shoulder": 0.755, "top": 0.640, "lift": 0.025},
    {"x": -2.0300, "rocker": 0.860, "shoulder": 0.885, "top": 0.710, "lift": 0.000},
    {"x": -1.7000, "rocker": 0.948, "shoulder": 0.970, "top": 0.765, "lift": 0.000},
    {"x": -1.3000, "rocker": 0.962, "shoulder": 0.980, "top": 0.815, "lift": 0.000},
    {"x": -1.0000, "rocker": 0.950, "shoulder": 0.970, "top": 0.790, "lift": 0.000},
    {"x": -0.7000, "rocker": 0.915, "shoulder": 0.935, "top": 0.750, "lift": 0.000},
    {"x": -0.4000, "rocker": 0.878, "shoulder": 0.900, "top": 0.715, "lift": 0.000},
    {"x": 0.1000, "rocker": 0.870, "shoulder": 0.895, "top": 0.700, "lift": 0.000},
    {"x": 0.5500, "rocker": 0.882, "shoulder": 0.907, "top": 0.705, "lift": 0.000},
    {"x": 0.9000, "rocker": 0.905, "shoulder": 0.930, "top": 0.720, "lift": 0.000},
    {"x": 1.1800, "rocker": 0.928, "shoulder": 0.952, "top": 0.730, "lift": 0.000},
    {"x": 1.3000, "rocker": 0.940, "shoulder": 0.958, "top": 0.725, "lift": 0.000},
    {"x": 1.7000, "rocker": 0.895, "shoulder": 0.920, "top": 0.635, "lift": 0.000},
    {"x": 2.0300, "rocker": 0.785, "shoulder": 0.815, "top": 0.520, "lift": 0.000},
    {"x": 2.2100, "rocker": 0.610, "shoulder": 0.650, "top": 0.450, "lift": 0.025},
)
"""The coupe's lower body, nose to tail, in metres.

``rocker`` is the half width at the bottom of the section and ``shoulder`` the
half width at the top, so the flank leans outward as it rises, the way a car
side does. ``top`` is the shoulder LINE -- the height of the body side. It
holds at the beltline from the tail forward to the cowl and then falls away to
the nose, which is the wedge; it may never rise above the beltline, because the
cabin's floor is the beltline and a hull that poked above it would leave the
canopy hanging off a step.

The width numbers are the haunch. 0.980 over the rear axle against 0.902 at the
door is a 78 mm per-side swell, and the rear peak stands 22 mm per side wider
than the front -- so the car is visibly widest at its back wheels.

The gap between ``rocker`` and ``shoulder`` -- the tuck -- is held near 18 mm
the whole way along on purpose, and that is a constraint rather than a
preference. A fender lip has to be drawn between two FLAT planes to be
recognisable as an arch rather than as an extra volume, so it cannot follow a
flank that leans; with a 56 mm tuck the lips stood up to 89 mm proud of the
paint, four paint-coloured flanges hovering beside the bodywork with an air
slot behind them. Varying the tuck between neighbouring stations also twists
every flank quad -- measured at 11.4 mm out of plane, where the four
constant-width archetypes measure zero -- and Blender triangulates the twist
into a visible crease down the side of the car."""

COUPE_CANOPY_PROFILE = (
    {"x": 1.4200, "half": 0.905, "top": 0.740},
    {"x": 1.1600, "half": 0.855, "top": 0.851},
    {"x": 0.9200, "half": 0.795, "top": 0.953},
    {"x": 0.6800, "half": 0.765, "top": 1.055},
    {"x": 0.4000, "half": 0.760, "top": 1.080},
    {"x": 0.1200, "half": 0.760, "top": 1.055},
    {"x": -0.1000, "half": 0.770, "top": 1.010},
    {"x": -0.3000, "half": 0.790, "top": 0.980},
    {"x": -0.5000, "half": 0.820, "top": 0.955},
)
"""Two of these numbers are not free.

The windscreen is ONE FLAT QUAD lying on the cowl-to-roof run, so every canopy
station between its ends must sit on the straight line joining them or the
paint rises through the glass. 0.90349 and 0.99444 are that line, evaluated;
the first cut of this body used round numbers and buried 7 mm of its own
windscreen inside the roof.

The half width VARIES -- waisted at the doors, swelling again toward the
buttresses -- and the side glazing follows it: each pane reads the local half
width at its own stations and stands GLASS_PROUD off that, not off the widest
station over its run, which once left the quarter light hanging 43 mm clear of
the paint at its leading edge. What the glazed runs DO demand of these numbers
is convexity: a pane is one flat quad, so between its stations it travels on a
chord, and a canopy that bulged above its own chords would push the paint
through the glass.

The cowl is nearly as wide as the hull's shoulder beneath it -- 36 mm of ledge
rather than the 255 mm the shared builder left -- so the windscreen grows out
of the body instead of being planted on it."""

COUPE_CANOPY_TAPER = 0.110
"""How much narrower the roof is than the beltline, per side.

The canopy's tumblehome, and the only tumblehome it gets: the suite measures
the skin a window must stand outside of as the cabin's widest point at that
station, with no regard for height, so a canopy that narrowed sharply would
force its own glazing out to the base width and leave it floating clear of the
roof. 75 mm leans the roof in without taking the glass off the body."""

COUPE_DECK_PROFILE = (
    {"x": -0.5000, "half": 0.820, "top": 0.955, "taper": 0.110, "band": 0.80},
    {"x": -0.7200, "half": 0.890, "top": 0.960, "taper": 0.150, "band": 0.55},
    {"x": -1.0000, "half": 0.940, "top": 0.965, "taper": 0.190, "band": 0.42},
    {"x": -1.3000, "half": 0.965, "top": 0.960, "taper": 0.220, "band": 0.34},
    {"x": -1.5500, "half": 0.945, "top": 0.925, "taper": 0.200, "band": 0.35},
    {"x": -1.8000, "half": 0.895, "top": 0.860, "taper": 0.170, "band": 0.45},
    {"x": -2.0200, "half": 0.825, "top": 0.765, "taper": 0.140, "band": 0.60},
)
"""The deck STOPS at -2.00, 210 mm short of the tail.

That is the ducktail. Behind it the hull's own shoulder line drops away to a
cut-off tail, so the car finishes on a step rather than tapering politely to
the bumper -- 196 mm of fall from the crown over the rear axle to the tail
panel. A rear deck carried flat all the way to the end of the car is the
single thing that made the first cut of this body read as a long saloon.

It starts at the canopy's own rear station, at the same half width and the
same height, so the buttress runs into it without a seam; from there it swells
to stand 100 mm per side wider than the canopy above it. That is the whole
point: a reviewer looking at the back of this car sees shoulders, not a boot
lid."""

COUPE_DECK_TAPER = COUPE_CANOPY_TAPER
"""How much narrower the deck's top is than its shoulder, per side.

Equal to :data:`COUPE_CANOPY_TAPER`, and the deck is lofted with the canopy's
band and chamfer too, so that the two volumes present the SAME outline at the
station they share. Given them different section parameters and the caps still
meet in x, in height and in width while their outlines diverge -- a 44.8 mm
ledge around a junction whose whole job is to be invisible."""

COUPE_GLASS_BAND = 0.80
"""The fraction of the canopy's height that stays vertical before the roof leans in.

Every side light must fit inside this band, because a pane is vertical and
anything above the band is leaning away from it."""


def _coupe_loft(name: str, kind: str, material: int, sections: list) -> dict:
    """Skin a run of sections with TRIANGLES rather than quads.

    The shared :func:`_loft` emits quads, which is free of consequence for a
    body whose sections differ only in width: those quads are planar. The
    coupe's sections differ in width, in floor AND in ceiling all at once, so
    the same quads come out twisted -- up to 36 mm out of plane where the
    fender closes around a wheel. Blender triangulates a twisted n-gon
    whichever way it likes and shades the result as a crease down the side of
    the car.

    Triangulating here costs nothing: a quad already counts as two triangles,
    so the budget is identical and the surface is planar by construction.
    """
    sides = len(sections[0])
    vertices: list = []
    for section in sections:
        if len(section) != sides:
            raise VehicleKitError(f"{name} lofts sections of different sizes")
        vertices.extend(section)
    faces: list = []
    for band in range(len(sections) - 1):
        base = band * sides
        for index in range(sides):
            nxt = (index + 1) % sides
            faces.append((base + index, base + nxt, base + sides + nxt))
            faces.append((base + index, base + sides + nxt, base + sides + index))
    for index in range(1, sides - 1):
        faces.append((0, index + 1, index))
    tail = (len(sections) - 1) * sides
    for index in range(1, sides - 1):
        faces.append((tail, tail + index, tail + index + 1))
    return _primitive(name, kind, material, vertices, faces)


def _coupe_at(profile: tuple, key: str, x: float) -> float:
    """One profile value at station ``x``, interpolated between control points."""
    if x <= profile[0]["x"]:
        return float(profile[0][key])
    if x >= profile[-1]["x"]:
        return float(profile[-1][key])
    for first, second in zip(profile, profile[1:], strict=False):
        if first["x"] <= x <= second["x"]:
            reach = second["x"] - first["x"]
            fraction = 0.0 if reach <= 0.0 else (x - first["x"]) / reach
            return float(first[key]) + fraction * (float(second[key]) - float(first[key]))
    return float(profile[-1][key])


def _coupe_ordered(profile: tuple) -> tuple:
    """A profile sorted nose-last, whichever order it was written in."""
    return tuple(sorted(profile, key=lambda entry: entry["x"]))


def _coupe_lower_section(
    x: float, rocker: float, shoulder: float, low: float, high: float, chamfer: float
) -> list:
    """One lower-body cross-section: rounded underneath, CRISP along the top.

    Six points, and the asymmetry is the point. The bottom corners are
    chamfered because that is where a car tucks under towards its floor. The
    top is left as a hard edge, because that edge IS the shoulder line -- the
    crease a car is read along -- and because the canopy and the deck land on
    it. Chamfering it too would inset the hull's top face by the chamfer and
    leave every volume above the beltline overhanging its own foundation.
    """
    span = max(high - low, 1.0e-4)
    high = low + span
    rocker = max(rocker, 1.0e-3)
    shoulder = max(shoulder, 1.0e-3)
    cut = max(0.0, min(chamfer, rocker * 0.45, span * 0.45))
    return [
        (x, rocker, low + cut),
        (x, rocker - cut, low),
        (x, -rocker + cut, low),
        (x, -rocker, low + cut),
        (x, -shoulder, high),
        (x, shoulder, high),
    ]


def _coupe_upper_section(
    x: float, half: float, taper: float, low: float, high: float, chamfer: float, band: float
) -> list:
    """One upper-body cross-section: crisp at the beltline, UPRIGHT, then rolled in.

    The mirror of :func:`_coupe_lower_section`, landing on that section's hard
    top edge without a step. The subtlety is ``band``: the side stays VERTICAL
    from the beltline up to that fraction of the section's height, and only
    then leans into the roof.

    That vertical band is not styling, it is what makes the windows sit on the
    car. A side light has to be vertical to read as one pane of glass, so it
    cannot follow a leaning surface: put the tumblehome through the glazed
    band and the pane stands off the paint by tens of millimetres at its top
    edge and reads as a dark slab stuck to the cabin. Measured at 56 mm on the
    first cut of this body. Above the glass, the roof may lean as far as it
    likes -- and does.
    """
    span = max(high - low, 1.0e-4)
    high = low + span
    half = max(half, 1.0e-3)
    top_half = max(half - taper, 1.0e-3)
    shoulder = low + span * min(max(band, 0.0), 0.98)
    cut = max(0.0, min(chamfer, top_half * 0.45, (high - shoulder) * 0.45))
    return [
        (x, half, low),
        (x, -half, low),
        (x, -half, shoulder),
        (x, -top_half, high - cut),
        (x, -top_half + cut, high),
        (x, top_half - cut, high),
        (x, top_half, high - cut),
        (x, half, shoulder),
    ]


COUPE_ARCH_OPENING_MARGIN = 0.012
"""How much wider than the tyre the arch OPENING is cut, in metres.

The opening traces a circle 12 mm larger than the wheel, and the two extra cuts
past the tyre's tangent exist so that the loft's last chord closes the opening
somewhere the tyre is not.

Without it the arc and the chord meet exactly at the tangent, where a chord
departs from its circle fastest, and the fender closes across the rubber: the
wheel is fine parked, because the built pose puts a facet corner in the gap,
and fouls once it turns -- 200 of 360 whole-degree rotations drove a tyre
vertex into the bodywork. A wheel that only clips while moving is the worst
kind of defect this kit can ship, because every still frame of it is clean."""


def _coupe_arch_floor(offset: float, radius: float, rise: float, sill: float) -> float:
    """The opening height ``offset`` metres along the body from one axle."""
    opening = radius + COUPE_ARCH_OPENING_MARGIN
    span = opening * opening - offset * offset
    if span <= 0.0:
        return sill
    return max(sill, radius + math.sqrt(span) + radius * (rise - 2.0))


def _coupe_floor(x: float) -> float:
    """The bottom of the coupe's body side at station ``x``.

    The sill everywhere except over a wheel, where it traces the tyre and adds
    the clearance that axle's arch rise asks for.
    """
    p = PROPORTIONS["coupe"]
    radius = float(p["wheel_radius"])
    sill = float(p["height"]) * float(p["sill"])
    front_axle, rear_axle = _axle_x("coupe")
    floor = sill
    # The reach of the OPENING, not of the tyre. Testing against the bare
    # radius leaves the three stations between the tyre's tangent and the
    # opening's edge falling back to the sill, which closes the fender across
    # the top of the wheel exactly where the margin was added to open it.
    reach = radius + COUPE_ARCH_OPENING_MARGIN
    for axle, rise in (
        (front_axle, COUPE_FRONT_ARCH_RISE),
        (rear_axle, COUPE_REAR_ARCH_RISE),
    ):
        offset = x - axle
        if abs(offset) <= reach:
            floor = max(floor, _coupe_arch_floor(offset, radius, rise, sill))
    return floor


def _coupe_hull_stations() -> list:
    """Every station of the coupe's lower body, tail to nose.

    The union of the design profile's own control points and the cuts each
    wheel needs, so the arches are traced finely without paying for that
    density along the whole car.
    """
    radius = float(PROPORTIONS["coupe"]["wheel_radius"])
    front_axle, rear_axle = _axle_x("coupe")
    profile = _coupe_ordered(COUPE_HULL_PROFILE)
    stations = {round(float(entry["x"]), 9) for entry in profile}
    for axle in (front_axle, rear_axle):
        for cut in COUPE_ARCH_CUTS:
            stations.add(round(axle + radius * cut, 9))
    return [
        {
            "x": x,
            "rocker": _coupe_at(profile, "rocker", x),
            "shoulder": _coupe_at(profile, "shoulder", x),
            "low": _coupe_floor(x) + _coupe_at(profile, "lift", x),
            "high": _coupe_at(profile, "top", x),
        }
        for x in sorted(stations)
    ]


def _coupe_hull() -> dict:
    """The coupe's lower body: one lofted solid, waisted and haunched."""
    chamfer = float(PROPORTIONS["coupe"]["width"]) * 0.055
    sections = [
        _coupe_lower_section(
            entry["x"], entry["rocker"], entry["shoulder"], entry["low"], entry["high"], chamfer
        )
        for entry in _coupe_hull_stations()
    ]
    return _coupe_loft("hull", "hull", PAINT, sections)


def _coupe_hull_top_at(x: float) -> float:
    """The shoulder path that the canopy and rear haunch grow from."""
    return _coupe_at(_coupe_ordered(COUPE_HULL_PROFILE), "top", x)


def _coupe_flank_at(x: float) -> tuple:
    """The flank's two corner points at station ``x``, AS THE MESH BUILDS THEM.

    This is the whole difference between furniture that lies on the paint and
    furniture that hangs in the wheel well. A loft is a run of CHORDS: between
    two stations the surface is the straight line joining corresponding
    vertices, and it does not follow the curve those stations were sampled
    from. Reading the arch curve analytically instead -- which this once did --
    puts the body up to 175 mm away from where the triangles actually are,
    everywhere the two disagree, which is exactly where a fender closes around
    a wheel.

    So interpolate the STATIONS, vertex by vertex, the way :func:`_coupe_loft`
    does. Returns ``(y_low, z_low, y_high, z_high)``: the bottom of the flank
    where the rocker chamfer ends, and the top where the shoulder line runs.
    """
    stations = _coupe_hull_stations()
    chamfer = float(PROPORTIONS["coupe"]["width"]) * 0.055

    def corners(entry: dict) -> tuple:
        span = max(entry["high"] - entry["low"], 1.0e-4)
        cut = max(0.0, min(chamfer, entry["rocker"] * 0.45, span * 0.45))
        return (entry["rocker"], entry["low"] + cut, entry["shoulder"], entry["low"] + span)

    if x <= stations[0]["x"]:
        return corners(stations[0])
    if x >= stations[-1]["x"]:
        return corners(stations[-1])
    for first, second in zip(stations, stations[1:], strict=False):
        if first["x"] <= x <= second["x"]:
            reach = second["x"] - first["x"]
            fraction = 0.0 if reach <= 0.0 else (x - first["x"]) / reach
            a, b = corners(first), corners(second)
            return tuple(a[i] + fraction * (b[i] - a[i]) for i in range(4))
    return corners(stations[-1])


def _coupe_side_y(x: float, z: float) -> float:
    """The half width of the coupe's flank at a point on it.

    Door furniture that asks for a flat fraction of body width floats off a
    body that leans and chamfers. Anything that must lie ON the side asks
    here, and gets the answer the emitted triangles would give.
    """
    y_low, z_low, y_high, z_high = _coupe_flank_at(x)
    if z_high <= z_low:
        return max(y_low, y_high)
    if z <= z_low:
        return y_low
    if z >= z_high:
        return y_high
    return y_low + (z - z_low) / (z_high - z_low) * (y_high - y_low)


def _coupe_flank_band(x: float) -> tuple:
    """The z range over which the coupe's flank actually exists at ``x``.

    Anything drawn on the side has to stay inside it. The sill once ran 112 mm
    past the point where the fender lifts away for the front wheel, so its
    leading edge hung in open air over the tyre.
    """
    _, z_low, _, z_high = _coupe_flank_at(x)
    return z_low, z_high


def _coupe_canopy() -> dict:
    """The cabin: one compact canopy flowing out of the cowl and into the deck."""
    chamfer = float(PROPORTIONS["coupe"]["width"]) * 0.075
    sections = [
        _coupe_upper_section(
            entry["x"],
            float(entry["half"]),
            COUPE_CANOPY_TAPER,
            _coupe_hull_top_at(float(entry["x"])),
            float(entry["top"]),
            chamfer,
            COUPE_GLASS_BAND,
        )
        for entry in _coupe_ordered(COUPE_CANOPY_PROFILE)
    ]
    return _coupe_loft("greenhouse", "greenhouse", PAINT, sections)


def _coupe_deck() -> dict:
    """The rear haunch: the boot volume, crowned and shouldered.

    Lofted with the canopy's own taper, band and chamfer, so the buttress runs
    into it without a ledge at the station the two volumes share.
    """
    chamfer = float(PROPORTIONS["coupe"]["width"]) * 0.075
    sections = [
        _coupe_upper_section(
            entry["x"],
            float(entry["half"]),
            float(entry.get("taper", COUPE_DECK_TAPER)),
            _coupe_hull_top_at(float(entry["x"])),
            float(entry["top"]),
            chamfer,
            float(entry.get("band", COUPE_GLASS_BAND)),
        )
        for entry in _coupe_ordered(COUPE_DECK_PROFILE)
    ]
    return _coupe_loft("deck", "deck", PAINT, sections)


def _coupe_canopy_half_at(x: float) -> float:
    """The canopy's half width at ``x``, the way an inspector recovers it.

    Interpolated between the canopy's own stations, which is exactly how the
    suite reads the skin a window has to stand outside of. Glazing asks here so
    that "outside the cabin" is a measured fact rather than a hope.
    """
    return _coupe_at(_coupe_ordered(COUPE_CANOPY_PROFILE), "half", x)


COUPE_SCREEN_STATIONS = ((1.4200, 0.7400), (0.6800, 1.0550))
COUPE_BACKLIGHT_STATIONS = ((0.1200, 1.0550), (-0.3800, 0.9700))
COUPE_DOOR_GLASS = (0.7000, 0.0800)
COUPE_QUARTER_GLASS = (0.0200, -0.3400)
"""The glazing run, in canopy stations.

The windscreen lies on the cowl-to-roof plane, a 0.68 m run against a 0.345 m
rise -- 27 degrees off the horizontal, which is most of why this car reads as
low. The side glass stops well short of the cowl flare so that the pane never
has to stand outside the canopy's widest station to be visible."""


def _coupe_glazing() -> list:
    """The coupe's windows: a raked screen, a long door light, a quarter light."""
    pieces = []
    for name, (front, rear) in (
        ("windscreen", (COUPE_SCREEN_STATIONS[0], COUPE_SCREEN_STATIONS[1])),
        ("rear_screen", (COUPE_BACKLIGHT_STATIONS[0], COUPE_BACKLIGHT_STATIONS[1])),
    ):
        (x0, z0), (x1, z1) = front, rear
        half = min(_coupe_canopy_half_at(x0), _coupe_canopy_half_at(x1)) * 0.90
        lift_x, lift_z = _outset(x0, z0, x1, z1)
        pieces.append(
            _quad(
                name,
                "glazing",
                GLASS,
                [
                    (x0 + lift_x, half, z0 + lift_z),
                    (x0 + lift_x, -half, z0 + lift_z),
                    (x1 + lift_x, -half * 0.94, z1 + lift_z),
                    (x1 + lift_x, half * 0.94, z1 + lift_z),
                ],
            )
        )

    canopy = _coupe_ordered(COUPE_CANOPY_PROFILE)

    def header(x: float, share: float) -> float:
        """The top edge of a side light, tracking the roofline above it."""
        base = _coupe_hull_top_at(x)
        return base + (_coupe_at(canopy, "top", x) - base) * share

    for label, (front, rear), share in (
        ("side_glass_front", COUPE_DOOR_GLASS, 0.78),
        ("quarter_glass", COUPE_QUARTER_GLASS, 0.72),
    ):
        # The pane stands GLASS_PROUD off the canopy's OWN half width at each
        # of its stations. Standing it off the widest station over the whole
        # run, as this once did, left the quarter light 43 mm clear of a
        # canopy that widens beneath it -- a dark sheet hanging beside the
        # cabin. Between the stations the pane travels on a chord, and the
        # profile is convex under both glazed runs, so the chord never dips
        # inside the paint; the suite bounds the worst standoff to prove it.
        reach_front = _coupe_canopy_half_at(front) + GLASS_PROUD
        reach_rear = _coupe_canopy_half_at(rear) + GLASS_PROUD
        low_front = _coupe_hull_top_at(front) + 0.028
        low_rear = _coupe_hull_top_at(rear) + 0.028
        for side, sign in (("l", 1.0), ("r", -1.0)):
            pieces.append(
                _quad(
                    f"{label}_{side}",
                    "glazing",
                    GLASS,
                    [
                        (front, sign * reach_front, low_front),
                        (rear, sign * reach_rear, low_rear),
                        (rear, sign * reach_rear, header(rear, share)),
                        (front, sign * reach_front, header(front, share)),
                    ],
                )
            )
    return pieces


def _coupe_doors() -> list:
    """The door cut, following the coupe's own leaning flank.

    A seam has to lie in ONE plane to read as a cut rather than a shadow, but
    this body's side leans out as it rises, so a single full-height bar would
    stand off the paint at one end or sink into it at the other. The cut is
    therefore SEGMENTED: each piece is flat in Y at the width the flank
    actually has over its own band, and the run of them traces the lean.
    """
    p = PROPORTIONS["coupe"]
    height = float(p["height"])
    belt = height * float(p["belt"])
    sill = height * float(p["sill"])
    chamfer = float(p["width"]) * 0.055
    cut = max(0.0, min(chamfer, (belt - sill) * 0.45))
    low, high = sill + cut, belt - cut
    seams = ((0.5600, 0.7200), (-0.2400, -0.4000))
    thickness = 0.004
    proud = 0.003
    segments = 2
    pieces = []
    for side, sign in (("l", 1.0), ("r", -1.0)):
        for index, (bottom_x, top_x) in enumerate(seams):
            # Each cut is bounded by the flank IT is drawn on, not by the
            # car's overall sill and beltline. The front cut stands where the
            # fender has already begun lifting for the wheel, so a seam given
            # the body's lowest sill height starts below the bodywork.
            # Bounded over the seam's OWN width, not at its centreline: the
            # strip is 28 mm across and the flank it lies on is climbing over
            # a wheel, so its two edges do not share a band.
            bottom_edges = [
                _coupe_flank_band(bottom_x - thickness),
                _coupe_flank_band(bottom_x + thickness),
            ]
            top_edges = [
                _coupe_flank_band(top_x - thickness),
                _coupe_flank_band(top_x + thickness),
            ]
            seam_low = max(low, max(edge[0] for edge in bottom_edges))
            seam_high = min(high, min(edge[1] for edge in top_edges))
            for step in range(segments):
                z0 = seam_low + (seam_high - seam_low) * step / segments
                z1 = seam_low + (seam_high - seam_low) * (step + 1) / segments
                share0 = 0.0 if seam_high <= seam_low else (z0 - seam_low) / (seam_high - seam_low)
                share1 = 0.0 if seam_high <= seam_low else (z1 - seam_low) / (seam_high - seam_low)
                x0 = bottom_x + (top_x - bottom_x) * share0
                x1 = bottom_x + (top_x - bottom_x) * share1
                pieces.append(
                    _quad(
                        f"door_seam_{index}{step}_{side}",
                        "door",
                        TRIM,
                        [
                            (
                                x0 - thickness,
                                sign * (_coupe_side_y(x0 - thickness, z0) + proud),
                                z0,
                            ),
                            (
                                x0 + thickness,
                                sign * (_coupe_side_y(x0 + thickness, z0) + proud),
                                z0,
                            ),
                            (
                                x1 + thickness,
                                sign * (_coupe_side_y(x1 + thickness, z1) + proud),
                                z1,
                            ),
                            (
                                x1 - thickness,
                                sign * (_coupe_side_y(x1 - thickness, z1) + proud),
                                z1,
                            ),
                        ],
                    )
                )
        # The rocker runs the WHOLE way between the arches, deliberately past
        # both door cuts. Stopping it at the seams closes a four-sided box on
        # the flank, and a rectangle outlined on a panel reads as a door
        # drawn on rather than a door cut in -- which is exactly how the first
        # cut of this body failed. It still stops clear of both openings, so it
        # can never draw itself across the wheel the traffic proof exists to
        # show turning.
        clear = float(p["wheel_radius"]) * 1.15
        front_axle, rear_axle = _axle_x("coupe")
        sill_front = front_axle - clear
        sill_rear = rear_axle + clear
        # The rocker sits ON the bottom of the flank at each of its own ends,
        # not at one height chosen for the middle. Toward the arches the flank
        # lifts away for the wheel, so a strip held at the door's own sill
        # height runs off the bottom of the car and hangs over the tyre --
        # measured at 112 mm of open air on the first cut of this body.
        rise = height * 0.030
        sill_stations = (sill_rear, -0.4200, 0.1000, 0.6200, sill_front)
        for index, (x0, x1) in enumerate(zip(sill_stations[:-1], sill_stations[1:], strict=True)):
            z0 = _coupe_flank_band(x0)[0]
            z1 = _coupe_flank_band(x1)[0]
            pieces.append(
                _quad(
                    f"door_sill_{index}_{side}",
                    "door",
                    TRIM,
                    [
                        (x0, sign * (_coupe_side_y(x0, z0) + proud), z0),
                        (x1, sign * (_coupe_side_y(x1, z1) + proud), z1),
                        (x1, sign * (_coupe_side_y(x1, z1 + rise) + proud), z1 + rise),
                        (x0, sign * (_coupe_side_y(x0, z0 + rise) + proud), z0 + rise),
                    ],
                )
            )
        handle_x = 0.1400
        handle_z = high - height * 0.052
        handle_face = _coupe_side_y(handle_x, handle_z)
        lo, hi = sorted((sign * handle_face, sign * (handle_face + 0.010)))
        pieces.append(
            _slab(
                f"door_handle_{side}",
                "door",
                TRIM,
                (handle_x - 0.075, lo, handle_z),
                (handle_x + 0.075, hi, handle_z + height * 0.028),
            )
        )
    return pieces


def _coupe_intake() -> list:
    """The side recess ahead of the rear arch.

    A mid-engined car has to breathe, and the dark scoop that says so is also
    the single cheapest way to stop a long flank reading as a board. It is a
    real recess -- an outer mouth on the flank and a smaller face set 70 mm
    inboard of it -- rather than a dark shape painted on the side.
    """
    pieces = []
    front, rear = -0.5600, -0.9600
    # Clamped to the flank the scoop is cut into. Held at fixed heights it ran
    # 98 mm below the bodywork at its rear edge, where the fender has already
    # lifted away for the wheel.
    low_front, high_front = _coupe_flank_band(front)
    low_rear, high_rear = _coupe_flank_band(rear)
    front_bottom = low_front + (high_front - low_front) * 0.40
    front_top = low_front + (high_front - low_front) * 0.68
    rear_bottom = low_rear + (high_rear - low_rear) * 0.24
    rear_top = low_rear + (high_rear - low_rear) * 0.84
    for side, sign in (("l", 1.0), ("r", -1.0)):
        # The mouth stands PROUD of the flank. Set even two millimetres behind
        # it, as this was, the whole scoop is inside a closed opaque solid and
        # renders as nothing at all -- 0.27 square metres of surface and not
        # one visible pixel. Exactly the failure that once hid this kit's
        # glazing, and the reason a recess has to be measured, not assumed.
        mouth = [
            (front, sign * (_coupe_side_y(front, front_bottom) + 0.012), front_bottom),
            (rear, sign * (_coupe_side_y(rear, rear_bottom) + 0.012), rear_bottom),
            (rear, sign * (_coupe_side_y(rear, rear_top) + 0.012), rear_top),
            (front, sign * (_coupe_side_y(front, front_top) + 0.012), front_top),
        ]
        inner = [
            (
                front - 0.035,
                sign * (_coupe_side_y(front, front_bottom) - 0.035),
                front_bottom + 0.025,
            ),
            (
                rear + 0.025,
                sign * (_coupe_side_y(rear, rear_bottom) - 0.035),
                rear_bottom + 0.035,
            ),
            (
                rear + 0.025,
                sign * (_coupe_side_y(rear, rear_top) - 0.035),
                rear_top - 0.035,
            ),
            (
                front - 0.035,
                sign * (_coupe_side_y(front, front_top) - 0.035),
                front_top - 0.025,
            ),
        ]
        pieces.append(_coupe_loft(f"side_intake_{side}", "intake", TRIM, [mouth, inner]))
    return pieces


def _coupe_lights() -> list:
    """Slim swept lamps let into the nose and the haunch.

    Neither family is an axis-aligned block. Each is a blade lofted between two
    rings, and BOTH rings stand proud of the surface they sit in -- the first
    of the nose or tail cap, the second of the flank the lamp wraps into. Only
    the proud faces are ever seen: the blade's flanks are inside a closed
    opaque solid, so a ring set even four millimetres behind the paint
    contributes nothing but triangles. The rear is a taller, more upright blade
    than the front, because two light families that differ only in colour read
    as the same part fitted twice.
    """
    p = PROPORTIONS["coupe"]
    length = float(p["length"])
    half_w = float(p["width"]) / 2.0
    sill = float(p["height"]) * float(p["sill"])
    nose, tail = length / 2.0, -length / 2.0
    pieces = []

    for side, sign in (("l", 1.0), ("r", -1.0)):
        # Both rings carry a vertex AT the hull profile's crease, x = 1.70 --
        # which is nose - 0.510. Each ring's long inboard chord crosses that
        # crease, and the hull top is convex there, so a straight chord strung
        # between lifted endpoints sagged 2 mm INTO the bonnet mid-span: a
        # lamp edge swallowed by the paint, the exact failure family the lens
        # rule above exists to prevent. The crease vertex LEADS each ring so
        # the cap fan pivots on it and no fan diagonal re-crosses the crease
        # unlifted.
        blade = [
            (nose - 0.510, sign * 0.394, _coupe_hull_top_at(nose - 0.510) + 0.010),
            (nose - 0.120, sign * 0.300, _coupe_hull_top_at(nose - 0.120) + 0.010),
            (nose - 0.140, sign * 0.580, _coupe_hull_top_at(nose - 0.140) + 0.010),
            (nose - 0.520, sign * 0.730, _coupe_hull_top_at(nose - 0.520) + 0.010),
            (nose - 0.620, sign * 0.420, _coupe_hull_top_at(nose - 0.620) + 0.010),
        ]
        inset = [
            (nose - 0.510, sign * 0.438, _coupe_hull_top_at(nose - 0.510) + 0.003),
            (nose - 0.170, sign * 0.340, _coupe_hull_top_at(nose - 0.170) + 0.003),
            (nose - 0.190, sign * 0.550, _coupe_hull_top_at(nose - 0.190) + 0.003),
            (nose - 0.510, sign * 0.680, _coupe_hull_top_at(nose - 0.510) + 0.003),
            (nose - 0.550, sign * 0.450, _coupe_hull_top_at(nose - 0.550) + 0.003),
        ]
        pieces.append(_coupe_loft(f"headlight_{side}", "lamp", LAMP, [blade, inset]))

        rear_face = [
            (tail - SCREEN_PROUD, sign * 0.300, 0.485),
            (tail - SCREEN_PROUD, sign * 0.720, 0.450),
            (tail - SCREEN_PROUD, sign * 0.760, 0.565),
            (tail - SCREEN_PROUD, sign * 0.330, 0.540),
        ]
        rear_inset = [
            (tail + 0.025, sign * 0.335, 0.492),
            (tail + 0.025, sign * 0.690, 0.466),
            (tail + 0.025, sign * 0.720, 0.548),
            (tail + 0.025, sign * 0.360, 0.530),
        ]
        pieces.append(_coupe_loft(f"taillight_{side}", "tail", TAIL, [rear_face, rear_inset]))

    pieces.append(
        _slab(
            "front_fascia",
            "fascia",
            TRIM,
            (nose - 0.170, -0.640, sill * 0.72),
            (nose - 0.010, 0.640, 0.372),
        )
    )
    pieces.append(
        _slab(
            "rear_fascia",
            "fascia",
            TRIM,
            (tail + 0.010, -0.700, sill * 0.72),
            (tail + 0.190, 0.700, 0.410),
        )
    )
    # Behind the tail cap and clear of the hull's own floor. Drawn 8 mm INSIDE
    # the tail, as this was, half of it is swallowed by the bodywork it is
    # supposed to be mounted on.
    plate_low = 0.2400
    pieces.append(
        _quad(
            "plate_recess",
            "fascia",
            TRIM,
            [
                (tail - SCREEN_PROUD, -half_w * 0.22, plate_low),
                (tail - SCREEN_PROUD, half_w * 0.22, plate_low),
                (tail - SCREEN_PROUD, half_w * 0.22, plate_low + 0.082),
                (tail - SCREEN_PROUD, -half_w * 0.22, plate_low + 0.082),
            ],
        )
    )
    return pieces


def _coupe_arches() -> list:
    """The fender lip around each of the coupe's wheel openings.

    The opening itself is carved by the hull's own floor; this is the rim that
    makes it read as an arch. Each lip is set at the half width the hull
    actually has over that axle, so it finishes the fender flush instead of
    standing proud of it as a ring, and the rear lip is both wider and taller
    than the front because the rear fender is the bigger form.
    """
    p = PROPORTIONS["coupe"]
    radius = float(p["wheel_radius"])
    reserved_half = RESERVED_PLANNING_ENVELOPE["coupe"]["width"] / 2.0
    front_axle, rear_axle = _axle_x("coupe")
    steps = 15
    pieces = []
    for axle_name, axle, rise in (
        ("f", front_axle, COUPE_FRONT_ARCH_RISE),
        ("r", rear_axle, COUPE_REAR_ARCH_RISE),
    ):
        opening = radius + COUPE_ARCH_OPENING_MARGIN
        outer_radius = opening + (0.018 if axle_name == "f" else 0.028)
        angles = [math.pi * index / (steps - 1) for index in range(steps)]
        for side, sign in (("l", 1.0), ("r", -1.0)):
            ring_in, ring_out = [], []
            for angle in angles:
                x_in = axle + opening * math.cos(angle)
                z_in = radius + opening * math.sin(angle) + radius * (rise - 2.0)
                x_out = axle + outer_radius * math.cos(angle)
                z_out = radius + outer_radius * math.sin(angle) + radius * (rise - 2.0)
                y_in = min(reserved_half - 0.001, _coupe_side_y(x_in, z_in) + 0.002)
                y_out = min(reserved_half - 0.001, _coupe_side_y(x_out, z_out) + 0.002)
                ring_in.append((x_in, sign * y_in, z_in))
                ring_out.append((x_out, sign * y_out, z_out))
            vertices = ring_in + ring_out
            faces = [
                (i, i + 1, steps + i + 1, steps + i)
                if sign > 0
                else (steps + i, steps + i + 1, i + 1, i)
                for i in range(steps - 1)
            ]
            pieces.append(_primitive(f"arch_{axle_name}{side}", "arch", PAINT, vertices, faces))
    return pieces


def _coupe_mirrors() -> list:
    """Door mirrors at the base of the windscreen pillar.

    Set LOW, just above the beltline, and kept shallow. Carried up on the
    canopy's shoulder they stand clear of the roofline in profile and read as
    two blocks strapped to the cabin rather than as mirrors, which is what the
    first cut of this body did.
    """
    p = PROPORTIONS["coupe"]
    half_w = float(p["width"]) / 2.0
    belt = float(p["height"]) * float(p["belt"])
    x = 0.8400
    z = belt + 0.045
    pieces = []
    for side, sign in (("l", 1.0), ("r", -1.0)):
        cabin = _coupe_canopy_half_at(x)
        inner = sign * cabin * 0.98
        outer = sign * min(half_w * 0.985, cabin + 0.095)
        low, high = sorted((inner, outer))
        pieces.append(
            _slab(
                f"mirror_{side}",
                "mirror",
                TRIM,
                (x - 0.045, low, z),
                (x + 0.045, high, z + 0.036),
            )
        )
    return pieces


def _coupe_geometry() -> list:
    """One exotic coupe, as named primitives in vehicle space."""
    parts = [_coupe_hull(), _coupe_canopy(), _coupe_deck()]
    parts.extend(_coupe_glazing())
    parts.extend(_coupe_doors())
    parts.extend(_coupe_intake())
    parts.extend(_coupe_mirrors())
    parts.extend(_coupe_lights())
    parts.extend(_coupe_arches())
    parts.extend(_well_liners("coupe"))
    return parts


# ---------------------------------------------------------------------------
# Wheel wells
# ---------------------------------------------------------------------------


def _well_liners(archetype: str) -> list:
    """A dark plate closing each wheel well against see-through.

    The arch is cut wider than the tyre so a TURNING wheel never fouls the
    fender, and the price of that clearance is a crescent of open air over the
    rubber. Both flanks cut the same opening at the same height, so a side-on
    camera looks through the near crescent, across the empty hull, and out the
    far one: a bright wedge of background punched clean through the body,
    13 by 8 pixels of daylight at proof resolution. The liner parks a trim
    plate inboard of each tyre so every sight line into a well ends on dark
    furniture instead of sky, whatever angle the camera takes.

    Its top edge follows the hull's OWN arch stations, plus a small overlap
    into the fender. The cut is an arc and both surfaces are runs of chords,
    so sampling the liner on any other stations would leave slivers where the
    two families of chords disagree -- and on the coupe's front fender there
    is no room to buy the slivers back with overlap, because the bonnet crest
    passes 20 mm over the cut. Same stations, same chords, no slivers.

    Two faces, plate and backing, 140 mm apart. The gap is not styling: door
    furniture is recovered by the suite as THIN trim on a flank, and a liner
    slim enough to match that description would be held to the door contract
    and fail it.
    """
    p = _require_archetype(archetype)
    radius = float(p["wheel_radius"])
    sill = float(p["height"]) * float(p["sill"])
    outer = float(p["track"]) / 2.0 - float(p["wheel_width"]) / 2.0 - 0.006
    if archetype == "coupe":
        stations = _coupe_hull_stations()
        reach = (radius + COUPE_ARCH_OPENING_MARGIN) * 1.035
        overlap = 0.012
    else:
        stations = _hull_stations(archetype)
        reach = radius * 1.15
        overlap = 0.020
    pieces = []
    for axle_name, axle in zip(("f", "r"), _axle_x(archetype), strict=True):
        span = [entry for entry in stations if abs(entry["x"] - axle) <= reach + 1.0e-9]
        ring = [(span[-1]["x"], sill), (span[0]["x"], sill)]
        ring.extend((entry["x"], entry["low"] + overlap) for entry in span)
        count = len(ring)
        for side, sign in (("l", 1.0), ("r", -1.0)):
            vertices = [(x, sign * outer, z) for x, z in ring] + [
                (x, sign * (outer - 0.140), z) for x, z in ring
            ]
            plate = tuple(range(count))
            backing = tuple(range(count, 2 * count))
            faces = (
                [plate, tuple(reversed(backing))] if sign > 0 else [tuple(reversed(plate)), backing]
            )
            pieces.append(
                _primitive(f"well_liner_{axle_name}{side}", "well", TRIM, vertices, faces)
            )
    return pieces


# ---------------------------------------------------------------------------
# Wheels
# ---------------------------------------------------------------------------


def wheel_geometry(archetype: str) -> list:
    """One wheel, in ITS OWN local frame with the origin at the axle.

    Emitted separately from the body because a wheel has to TURN: the applier
    makes each of the four a child object and rotates it about its own axle.

    The outer face carries a hub in body colour AND an asymmetric witness --
    one contrasting sector at a single angular position. That witness is the
    whole reason rotation is visible: a plain disc is rotationally symmetric,
    so a spinning wheel and a frozen one render identically. It is part of the
    wheel mesh, so it turns with the real wheel and cannot drift out of step
    with the distance the car has travelled.
    """
    p = _require_archetype(archetype)
    radius = float(p["wheel_radius"])
    half = float(p["wheel_width"]) / 2.0
    hub = radius * 0.52
    inner = _disc_ring(radius, -half, WHEEL_SIDES)
    outer = _disc_ring(radius, half, WHEEL_SIDES)
    pieces = [_loft("tyre", "wheel", TRIM, [inner, outer])]
    for sign in (1.0, -1.0):
        pieces.extend(_wheel_face(sign, half, hub))
    return pieces


def _wheel_face(sign: float, half: float, hub: float) -> list:
    """One outward face of a wheel: hub, rim and the rotation witnesses.

    BOTH faces are built. A wheel is a child object placed at a positive or a
    negative Y offset and is never mirrored, so a single-faced wheel shows its
    hub on the vehicle's left flank and a blank tyre cap on its right -- and the
    traffic camera happens to watch the right flank of every car that passes it,
    which would have made the wheel proof prove nothing at all.

    The witness is what makes rotation visible: a plain disc is rotationally
    symmetric, so a spinning wheel and a frozen one render identically. There
    are TWO sectors, opposite each other and in different material families,
    because one alone would be a paint-dependent gamble -- a lamp-coloured mark
    on a bone hub is barely a contrast at all, while the same mark on graphite
    is obvious. One of the pair always reads.
    """
    side = "l" if sign > 0 else "r"
    face_y = sign * (half + 0.004)
    ring_y = sign * (half + 0.002)
    mark_y = sign * (half + 0.006)

    def wind(indices: tuple) -> tuple:
        """Faces on the -Y cap wind the other way, so both normals point out."""
        return indices if sign > 0 else tuple(reversed(indices))

    pieces = [
        _primitive(
            f"hub_{side}",
            "hub",
            PAINT,
            _disc_ring(hub, face_y, WHEEL_SIDES),
            [wind(tuple(range(WHEEL_SIDES)))],
        )
    ]
    rim = _disc_ring(hub * 1.34, ring_y, WHEEL_SIDES)
    hub_ring = _disc_ring(hub, ring_y, WHEEL_SIDES)
    pieces.append(
        _primitive(
            f"rim_{side}",
            "hub",
            TRIM,
            rim + hub_ring,
            [
                wind(
                    (i, (i + 1) % WHEEL_SIDES, WHEEL_SIDES + (i + 1) % WHEEL_SIDES, WHEEL_SIDES + i)
                )
                for i in range(WHEEL_SIDES)
            ],
        )
    )
    sector = 3
    for label, material, start in (("lamp", LAMP, 0), ("dark", TRIM, WHEEL_SIDES // 2)):
        witness = [(0.0, mark_y, 0.0)]
        witness.extend(
            (
                hub * 0.94 * math.cos(2.0 * math.pi * (start + index) / WHEEL_SIDES),
                mark_y,
                hub * 0.94 * math.sin(2.0 * math.pi * (start + index) / WHEEL_SIDES),
            )
            for index in range(sector + 1)
        )
        pieces.append(
            _primitive(
                f"hub_witness_{label}_{side}",
                "hub",
                material,
                witness,
                [wind(tuple(range(len(witness))))],
            )
        )
    return pieces


def wheel_offsets(archetype: str) -> dict:
    """Where the four axles sit in the vehicle's own frame.

    Keyed by the corner names the applier uses for object suffixes, in a fixed
    order so the same vehicle always builds the same four children.
    """
    p = _require_archetype(archetype)
    front, rear = _axle_x(archetype)
    half_track = float(p["track"]) / 2.0
    radius = float(p["wheel_radius"])
    return {
        "fl": (front, half_track, radius),
        "fr": (front, -half_track, radius),
        "rl": (rear, half_track, radius),
        "rr": (rear, -half_track, radius),
    }


# ---------------------------------------------------------------------------
# The whole vehicle
# ---------------------------------------------------------------------------


def vehicle_geometry(archetype: str) -> list:
    """One complete vehicle body, as named primitives in vehicle space.

    THE entry point. The four wheels are NOT here: they are separate objects
    with their own frames so they can rotate, and :func:`wheel_geometry` builds
    them.

    The coupe branches to its own builder. Four archetypes are a lower body
    with a cabin standing on it; an exotic is not, and the shared builder has
    no dial that can vary a body's width along its length.
    """
    _require_archetype(archetype)
    if archetype == "coupe":
        return _coupe_geometry()
    parts = [_hull(archetype)]
    hood = _hood(archetype)
    if hood is not None:
        parts.append(hood)
    deck = _deck(archetype)
    if deck is not None:
        parts.append(deck)
    parts.append(_greenhouse(archetype))
    parts.extend(_glazing(archetype))
    parts.extend(_doors(archetype))
    parts.extend(_mirrors(archetype))
    parts.extend(_lights(archetype))
    parts.extend(_arches(archetype))
    parts.extend(_well_liners(archetype))
    return parts


def _mesh(primitives: list) -> dict:
    """Weld a run of primitives into one indexed mesh."""
    vertices: list = []
    faces: list = []
    materials: list = []
    for primitive in primitives:
        offset = len(vertices)
        vertices.extend(primitive["vertices"])
        for face in primitive["faces"]:
            faces.append(tuple(index + offset for index in face))
            materials.append(primitive["material"])
    return {"vertices": vertices, "faces": faces, "materials": materials}


def vehicle_mesh(archetype: str) -> dict:
    """One vehicle body welded into a single indexed mesh, ready for Blender."""
    return _mesh(vehicle_geometry(archetype))


def wheel_mesh(archetype: str) -> dict:
    """One wheel welded into a single indexed mesh, in its own axle frame."""
    return _mesh(wheel_geometry(archetype))


def triangle_count(primitive: dict) -> int:
    """The triangle cost of one primitive, counted the way Blender counts it."""
    return sum(max(0, len(face) - 2) for face in primitive["faces"])


def vehicle_triangles(archetype: str) -> int:
    """The whole triangle cost of one vehicle, four wheels included."""
    body = sum(triangle_count(entry) for entry in vehicle_geometry(archetype))
    wheel = sum(triangle_count(entry) for entry in wheel_geometry(archetype))
    return body + wheel * 4


def measured_visual_bounds(archetype: str) -> dict:
    """What the emitted geometry ACTUALLY occupies, wheels included.

    Wheels count: arches now expose them, and a wheel is part of what a kerb
    would hit. This is the number the test suite holds against
    :data:`RESERVED_PLANNING_ENVELOPE`.
    """
    primitives = vehicle_geometry(archetype)
    wheel = wheel_geometry(archetype)
    xs = [vertex[0] for entry in primitives for vertex in entry["vertices"]]
    ys = [vertex[1] for entry in primitives for vertex in entry["vertices"]]
    zs = [vertex[2] for entry in primitives for vertex in entry["vertices"]]
    for offset in wheel_offsets(archetype).values():
        for entry in wheel:
            for vertex in entry["vertices"]:
                xs.append(offset[0] + vertex[0])
                ys.append(offset[1] + vertex[1])
                zs.append(offset[2] + vertex[2])
    return {
        "length": round(max(xs) - min(xs), 6),
        "width": round(max(ys) - min(ys), 6),
        "height": round(max(zs), 6),
    }


def vehicle_dimensions(archetype: str) -> dict:
    """The envelope the PLANNERS reserve for one archetype.

    This deliberately reports :data:`RESERVED_PLANNING_ENVELOPE`, not the measured
    geometry. The lane network sized every lane, headway and turning fillet
    from these exact numbers, and Phase 19's routes, lane feasibility and
    canonical fourteen vehicles all descend from them. Reporting the measured
    body instead would mean that RESHAPING a car -- even shrinking it --
    silently re-planned the city's traffic, and a redesign that quietly changed
    which streets carry cars would be a far worse bug than a slab-sided bonnet.

    So the envelope is a RESERVATION. The kit must build inside it, which
    :func:`measured_visual_bounds` reports and the test suite enforces per
    archetype; the planners keep planning against the box, not the sculpture.
    """
    p = _require_archetype(archetype)
    planned = RESERVED_PLANNING_ENVELOPE[archetype]
    measured = measured_visual_bounds(archetype)
    return {
        "archetype": archetype,
        "length": planned["length"],
        "width": planned["width"],
        "height": planned["height"],
        "measured_length": measured["length"],
        "measured_width": measured["width"],
        "measured_height": measured["height"],
        "body_length": float(p["length"]),
        "body_width": float(p["width"]),
        "wheelbase": float(p["wheelbase"]),
        "track": float(p["track"]),
        "wheel_radius": float(p["wheel_radius"]),
        "ground_clearance": float(p["ground"]),
    }


def widest_vehicle() -> float:
    """The RESERVED width of the widest archetype the kit can build.

    Lane counts and lane offsets are derived from this, so it reports the
    reservation rather than the sculpture. See :func:`envelope_contract`.
    """
    return max(vehicle_dimensions(name)["width"] for name in ARCHETYPES)


def longest_vehicle() -> float:
    """The RESERVED length of the longest archetype the kit can build.

    Headways, slot pitch and circuit compatibility are derived from this, so it
    reports the reservation rather than the sculpture. See
    :func:`envelope_contract`.
    """
    return max(vehicle_dimensions(name)["length"] for name in ARCHETYPES)


def envelope_headroom(archetype: str) -> dict:
    """How much of the reserved envelope this archetype leaves unused.

    Negative on any axis means the redesign grew out of the box the lane
    network planned against, which is a refusal rather than a warning.
    """
    planned = RESERVED_PLANNING_ENVELOPE[archetype]
    built = measured_visual_bounds(archetype)
    return {axis: round(planned[axis] - built[axis], 6) for axis in ("length", "width", "height")}


def _component_bounds(archetype: str) -> list:
    """Every emitted lump of one vehicle, wheels included, in vehicle space.

    The wheels are built in their own axle frames so they can turn, so they are
    moved to the four corners they are actually fitted at before being
    measured. A containment claim that quietly skipped them would be a claim
    about a car with no wheels.
    """
    entries = [
        (part["name"], part["kind"], part["vertices"]) for part in vehicle_geometry(archetype)
    ]
    wheel = wheel_geometry(archetype)
    for corner, offset in wheel_offsets(archetype).items():
        for part in wheel:
            entries.append(
                (
                    f"{part['name']}_{corner}",
                    part["kind"],
                    [
                        (offset[0] + vertex[0], offset[1] + vertex[1], offset[2] + vertex[2])
                        for vertex in part["vertices"]
                    ],
                )
            )
    return entries


def component_containment(archetype: str) -> list:
    """Whether EVERY component sits inside the reservation, one lump at a time.

    The whole-vehicle bounds can pass while a single mirror, lamp or fender lip
    pokes out of the box the lane network planned against, because a bounding
    box over the whole car is dominated by the body. This reports the slack of
    each component on each axis, so a containment claim is a per-part fact
    rather than an average.

    Slack is signed: negative on any axis is a planning-contract failure.
    """
    reserved = RESERVED_PLANNING_ENVELOPE[archetype]
    half_length = reserved["length"] / 2.0
    half_width = reserved["width"] / 2.0
    report = []
    for name, kind, vertices in _component_bounds(archetype):
        xs = [vertex[0] for vertex in vertices]
        ys = [vertex[1] for vertex in vertices]
        zs = [vertex[2] for vertex in vertices]
        slack = {
            "length": round(min(half_length - max(xs), min(xs) + half_length), 6),
            "width": round(half_width - max(abs(min(ys)), abs(max(ys))), 6),
            "height": round(min(reserved["height"] - max(zs), min(zs)), 6),
        }
        report.append(
            {
                "component": name,
                "kind": kind,
                "slack": slack,
                "contained": all(value >= -1.0e-9 for value in slack.values()),
            }
        )
    return report


def envelope_contract(archetype: str) -> dict:
    """The reservation, the measurement, and whether one fits in the other.

    Two DIFFERENT numbers, reported side by side and named for what they are.

    ``reserved_planning_envelope`` is a RESERVATION. The lane network sized
    every lane, headway and turning fillet from it before this kit was
    reshaped, and Phase 19's routes and canonical fourteen vehicles descend
    from those numbers, so it is deliberately frozen: reporting the sculpture
    instead would mean that restyling a car silently re-planned the city's
    traffic.

    ``measured_visual_bounds`` is a MEASUREMENT, read off the vertices the kit
    actually emits.

    Calling the first one "measured vehicle dimensions", as this module once
    did in three separate docstrings, is the kind of untruth that survives
    every test and misleads every reader.
    """
    components = component_containment(archetype)
    return {
        "archetype": archetype,
        "reserved_planning_envelope": dict(RESERVED_PLANNING_ENVELOPE[archetype]),
        "measured_visual_bounds": measured_visual_bounds(archetype),
        "headroom": envelope_headroom(archetype),
        "contained": all(entry["contained"] for entry in components),
        "components": len(components),
        "escaped": [entry["component"] for entry in components if not entry["contained"]],
    }


def envelope_contracts() -> dict:
    """Every archetype's envelope contract, for manifests and reports."""
    return {name: envelope_contract(name) for name in ARCHETYPES}


def silhouette_profile(archetype: str) -> dict:
    """The measured outline of one archetype, for silhouette inspection.

    Read off the EMITTED geometry rather than off the proportions table, so a
    test that says "the coupe is lower than the sedan" is measuring what the
    kit actually builds. A proportions table can be edited without the body
    following it; vertices cannot.
    """
    primitives = vehicle_geometry(archetype)
    xs = [vertex[0] for entry in primitives for vertex in entry["vertices"]]
    ys = [vertex[1] for entry in primitives for vertex in entry["vertices"]]
    zs = [vertex[2] for entry in primitives for vertex in entry["vertices"]]
    frame = cabin_frame(archetype)
    p = PROPORTIONS[archetype]
    body_span = max(xs) - min(xs)
    names = {entry["name"] for entry in primitives}
    return {
        "length": round(body_span, 4),
        "width": round(max(ys) - min(ys), 4),
        "height": round(max(zs), 4),
        "roof_height": round(frame["roof"], 4),
        "belt_height": round(frame["belt"], 4),
        "cabin_length": round(frame["front"] - frame["rear"], 4),
        "cabin_share": round((frame["front"] - frame["rear"]) / body_span, 4),
        "cabin_centre": round((frame["front"] + frame["rear"]) / 2.0, 4),
        "roof_fall": round(frame["roof_drop"], 4),
        "wheel_radius": round(float(p["wheel_radius"]), 4),
        "height_over_width": round(max(zs) / (max(ys) - min(ys)), 4),
        "roof_over_length": round(frame["roof"] / body_span, 4),
        "three_box": "deck" in names,
        "side_lights": sum(1 for name in names if name.startswith(("side_glass", "quarter_glass"))),
        "triangles": vehicle_triangles(archetype),
    }


def kit_summary() -> dict:
    """Every archetype's measured profile, for manifests and reports."""
    return {name: silhouette_profile(name) for name in ARCHETYPES}
