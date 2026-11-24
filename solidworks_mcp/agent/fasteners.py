"""Modeled metric coarse-thread fastener pairs. All dimensions are in mm."""

import math
from pathlib import Path
import re


# ISO 4017 head width and nominal height, ISO 4032 nut height.
HEX = {3: (5.5, 2, 2.4), 4: (7, 2.8, 3.2), 5: (8, 3.5, 4.7), 6: (10, 4, 5.2),
       8: (13, 5.3, 6.8), 10: (16, 6.4, 8.4), 12: (18, 7.5, 10.8), 16: (24, 10, 14.8)}
SIZE = r"\bM\s*(\d+)(?:\s*[x×]\s*(\d+(?:\.\d+)?)\s*(?:mm)?)?\b"
COARSE_PITCH = {3: 0.5, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25, 10: 1.5, 12: 1.75, 16: 2.0}
INSTANCE = re.compile(r"M(\d+)x(\d+(?:\.\d+)?)(?:-\d+)?-(Bolt|Nut)(?:\^[^/]+)?-\d+", re.I)
PLACEMENT_ACTIONS = {"move_fastener", "screw_mate_fasteners"}


def placement_request(text):
    p = text.lower().strip().rstrip(".!?").replace("’", "'")
    turn = re.fullmatch(r"(?:please )?(turn|rotate|tighten|loosen) (?:the )?(bolt|nut|it)"
                        r"(?: (?:on|along) (?:the )?bolt)?(?: (?:by )?"
                        r"([+-]?(?:\d+(?:\.\d+)?|\.\d+)|1/2|1/4|3/4|half|a half|quarter|a quarter|one quarter|one) "
                        r"(?:a )?(turns?|revolutions?|degrees?))?(?: (clockwise|counterclockwise|anticlockwise))?", p)
    if turn and (turn[3] or turn[1] in {"tighten", "loosen"}):
        verb, role, amount, unit, direction = turn.groups()
        fractions = {"1/2": .5, "1/4": .25, "3/4": .75, "half": .5, "a half": .5,
                     "quarter": .25, "a quarter": .25, "one quarter": .25, "one": 1.}
        turns = fractions[amount] if amount in fractions else float(amount or 1)
        if unit and unit.startswith("degree"):
            turns /= 360
        if verb in {"tighten", "loosen"} and (turns < 0 or (direction and (direction == "clockwise") != (verb == "tighten"))):
            raise ValueError("Give the tightening or loosening amount as a positive number of turns.")
        if verb == "loosen" or direction in {"counterclockwise", "anticlockwise"}:
            turns = -turns
        if not math.isfinite(turns):
            raise ValueError("Enter a finite number of turns.")
        return "screw_mate_fasteners", ({"turns": turns} if role == "it" else {"moving": role, "turns": turns})
    if re.fullmatch(r"(?:please )?(?:(?:i want |make |let )?(?:the )?nut (?:to |should )?(?:slide|rotate|turn|spin)"
                    r"|(?:slide|rotate|turn|spin) (?:the )?nut) (?:on|along) (?:the )?bolt(?:'s|s)?(?: threads?)?"
                    r"(?: like (?:we are )?(?:tightening|tighting) (?:or|and) (?:loosening|lousing)(?: the nutbolt)?)?", p):
        return "screw_mate_fasteners", {"moving": "nut"}
    if re.fullmatch(r"(?:please )?(?:add|create|apply) (?:a |the )?screw mate(?: (?:to|between|for) (?:the )?bolt and (?:the )?nut)?", p):
        return "screw_mate_fasteners", {"moving": "bolt"}
    screw = re.fullmatch(r"(?:please )?(?:(?:it|(?:the )?bolt) (?:should |must |can )?"
                         r"(?:rotate|turn|spin)|(?:rotate|turn|spin) (?:it|(?:the )?bolt)|"
                         r"make (?:it|(?:the )?bolt) (?:rotate|turn|spin)) "
                         r"(?:on|along|in) (?:the )?nut(?:'s|s|s')? threads?", p)
    if screw:
        return "screw_mate_fasteners", {"moving": "bolt"}
    p = re.sub(r"^make (?:the )?(bolt|nut) move\b", r"move \1", p)
    if moving := move_request(p):
        return "move_fastener", {"moving": moving}


def turned_pose(rotation, origin_mm, turns, pitch):
    angle = math.tau * (turns % 1)
    c, s = math.cos(angle), math.sin(angle)
    x, y, z = rotation[:3], rotation[3:6], rotation[6:9]
    orientation = [c*a + s*b for a, b in zip(x, y)] + [c*b - s*a for a, b in zip(x, y)] + list(z)
    return orientation, [p + turns*pitch*axis for p, axis in zip(origin_mm, z)]


def thread_engaged(bolt_axis, nut_axis, offset_mm, spec, advance_mm=0):
    axial = sum(v*z for v, z in zip(offset_mm, nut_axis))
    head = HEX[spec["diameter"]][1]
    return (all(abs(x-y) < 1e-6 for x, y in zip(bolt_axis, nut_axis))
            and all(abs(v-axial*z) < .001 for v, z in zip(offset_mm, nut_axis))
            and -head-spec["length"]-1e-6 <= axial+advance_mm <= -head+1e-6)


def move_request(text):
    match = re.fullmatch(
        r"(?:(?:can|could) you\s+)?(?:please\s+)?(?:move|place|put|position|align|slide)\s+"
        r"(?:(?:the|my)\s+)?(bolt|nut)\s+(?:on top of|on\s+to|onto|on|into|in|to|with|over|through)\s+"
        r"(?:(?:the|my|matching)\s+)*(nut|bolt)(?:\s+in (?:the |this )?(?:current |existing )?assembly)?",
        text.strip().rstrip(".!?"), re.I)
    if match and match[1].lower() != match[2].lower():
        return match[1].lower()


def placement_candidates(names, bolt=None, nut=None):
    candidates = {"bolt": {}, "nut": {}}
    for name in sorted(names):
        match = INSTANCE.fullmatch(name)
        if match:
            candidates[match[3].lower()][name] = _dimensions(match[1], match[2])
    for role, selected in (("bolt", bolt), ("nut", nut)):
        options = candidates[role]
        if selected and selected not in options:
            raise ValueError(f"The selected {role} '{selected}' is no longer available in this assembly.")
        if selected:
            candidates[role] = {selected: options[selected]}
        if not options:
            raise ValueError(f"Could not identify an existing {role} from the agent's metric fastener pairs in this assembly.")
    sizes = {spec["diameter"] for spec in candidates["bolt"].values()} & {
        spec["diameter"] for spec in candidates["nut"].values()}
    if not sizes:
        raise ValueError("The bolt and nut have different nominal thread diameters.")
    return {role: {name: spec for name, spec in options.items() if spec["diameter"] in sizes}
            for role, options in candidates.items()}


def bolt_to_nut_offset(diameter, length):
    _, head, nut_height = HEX[diameter]
    return head + length - nut_height


def thread_args(diameter, length, role):
    head, thickness = HEX[diameter][1:]
    internal = role.lower() == "nut"
    return dict(diameter=diameter, pitch=COARSE_PITCH[diameter], internal=internal,
                depth=thickness if internal else length, tip=thickness if internal else head + length)


def component_threads(names, target):
    """Resolve only an unambiguous set of the agent's named fasteners in the active assembly."""
    roles = ("Bolt", "Nut") if target == "both" else (target.title(),)
    found = {}
    for name in names:
        match = INSTANCE.fullmatch(name)
        if match and match[3].title() in roles:
            role = match[3].title()
            if role in found:
                raise ValueError(f"Multiple {role.lower()} instances match. Open the assembly containing just the intended pair.")
            spec = _dimensions(match[1], match[2])
            found[role] = (name, spec)
    if set(found) != set(roles):
        if found:
            missing = ", ".join(role.lower() for role in roles if role not in found)
            raise ValueError(f"The active assembly is missing the matching {missing}. Select the assembly containing the pair, "
                             "or specify just the component you want to thread.")
        raise ValueError("Activate the assembly containing the agent's metric nut and bolt.")
    if len(roles) == 2 and found["Bolt"][1] != found["Nut"][1]:
        raise ValueError("The nut and bolt names do not identify a matching pair.")
    return [(found[r][0], thread_args(**found[r][1], role=r)) for r in roles]


def _dimensions(diameter, length=None):
    d = int(diameter)
    if d != float(diameter) or d not in HEX:
        raise ValueError("Choose a supported metric size: " + ", ".join(f"M{size}" for size in HEX) + ".")
    values = {"diameter": d}
    if length is not None:
        length = float(length)
        if not math.isfinite(length) or length < HEX[d][2]:
            raise ValueError(f"Choose an under-head bolt length of at least {HEX[d][2]:g} mm so the nut fits.")
        values["length"] = length
    return values


def apply_dimensions(spec, supplied):
    values = dict(spec)
    aliases = {"bolt_length": "length", "nominal_diameter": "diameter"}
    for name, value in supplied.items():
        key = aliases.get(name, name)
        if key not in {"diameter", "length"}:
            raise ValueError(f"Unknown hex fastener dimension '{name}'. Use diameter and length in mm.")
        values[key] = value
    if "diameter" in values:
        values = _dimensions(values["diameter"], values.get("length"))
    elif "length" in values and (not math.isfinite(values["length"]) or values["length"] <= 0):
        raise ValueError("Give a positive under-head length in mm.")
    spec.update(values)


def request(text):
    size = re.search(SIZE, text, re.I)
    words = re.sub(SIZE, " ", text, flags=re.I).strip(" .!?")
    words = re.sub(r"[,&/\-]", " ", words)
    words = re.sub(r"\b(?:please|make|create|design|build|model|plan|a|an|new|hex|metric|and|with|matching|pair|assembly|of|threads?|threaded)\b", " ", words, flags=re.I)
    if words.lower().split() not in (["nut", "bolt"], ["bolt", "nut"]):
        return None
    return _dimensions(*size.groups()) if size else {}


def question(spec):
    if "diameter" not in spec:
        if "length" in spec:
            return f"What metric size should the {spec['length']:g} mm bolt and nut be? For example, M8."
        return "What size nut and bolt do you want? For example, M8 x 30 means an M8 bolt 30 mm long under the head."
    if "length" not in spec:
        return f"How long should the M{spec['diameter']} bolt be under the head, in mm?"
    return (f"M{spec['diameter']} x {spec['length']:g} mm hex bolt and matching nut\n"
            f"Both parts get modeled right-hand threads at {COARSE_PITCH[spec['diameter']]:g} mm pitch. "
            "The nut sits flush with the bolt tip.\n"
            "Reply 'yes' to build both components.")


def answer(spec, text):
    """Confirm the layout, retaining an external destination only when explicitly supplied."""
    text = text.strip()
    size = re.fullmatch(SIZE, text, re.I)
    if size:
        spec.update(_dimensions(size[1], size[2] or spec.get("length")))
        return None
    length = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:mm)?", text, re.I)
    if length and "diameter" in spec:
        spec.update(_dimensions(spec["diameter"], length[1]))
        return None
    if "diameter" not in spec or "length" not in spec:
        raise ValueError("Enter a metric designation like M8, or give size and length together as M8 x 30.")
    if text.lower() in {"use defaults", "defaults", "yes", "ok"}:
        return True
    folder = Path(text.strip('"')).expanduser()
    if not folder.is_absolute() or not folder.is_dir():
        raise ValueError("Choose an existing folder, or reply 'use defaults'.")
    spec["folder"] = folder
    return True


def layout(spec, exists):
    d, length = spec["diameter"], spec["length"]
    flats, head, thickness = HEX[d]
    stem = f"M{d}x{length:g}"
    radius = flats / math.sqrt(3)
    hexagon = [(radius * math.cos(i * math.pi / 3), radius * math.sin(i * math.pi / 3)) for i in range(6)]
    sketch = ("create_sketch", {"plane_or_face": "Front Plane"})
    profile = ("sketch_closed_polyline", {"points": hexagon})
    circle = ("sketch_circle", {"xc": 0, "yc": 0, "radius": d / 2})
    pilot = ("sketch_circle", {"xc": 0, "yc": 0, "radius": (d - COARSE_PITCH[d]) / 2})
    bolt_features = [sketch, profile, ("feature_extrude_boss", {"depth": head}),
                     sketch, circle, ("feature_extrude_boss", {"depth": head + length}),
                     ("add_metric_thread", thread_args(d, length, "Bolt"))]
    nut_features = [sketch, profile, pilot, ("feature_extrude_boss", {"depth": thickness}),
                    ("add_metric_thread", thread_args(d, length, "Nut"))]
    folder = spec.get("folder")
    if folder is None:
        components = [("new_assembly", {})]
        for name, z, ops in (("Bolt", 0, bolt_features), ("Nut", bolt_to_nut_offset(d, length), nut_features)):
            components.append(("create_virtual_component", dict(name=f"{stem}-{name}", origin=[0, 0, z],
                               features=[{"operation": op, "arguments": args} for op, args in ops])))
        return components
    suffix = ""
    counter = 1
    while True:
        bolt, nut, assembly = [str(folder / (stem + suffix + name)) for name in
                               ("-Bolt.SLDPRT", "-Nut.SLDPRT", "-Assembly.SLDASM")]
        if not any(exists(path) or Path(path).exists() for path in (bolt, nut, assembly)):
            break
        counter += 1
        suffix = f"-{counter}"

    return [("new_part", {}), *bolt_features,
            ("save_model", {"file_path": bolt}),
            ("new_part", {}), *nut_features,
            ("save_model", {"file_path": nut}), ("new_assembly", {}),
            ("insert_component", dict(file_path=bolt, x=0, y=0, z=0)),
            ("insert_component", dict(file_path=nut, x=0, y=0, z=bolt_to_nut_offset(d, length))),
            ("save_model", {"file_path": assembly})]
