"""Custom part features and assembly operations that do not require a part template."""

import math
from pathlib import Path
import re

from .requirements import NUMBER


TRIPLE = rf"\(\s*({NUMBER})\s*,\s*({NUMBER})\s*,\s*({NUMBER})\s*\)"
PAIR = rf"\(\s*({NUMBER})\s*,\s*({NUMBER})\s*\)"
SIZE = rf"({NUMBER})(?:\s*mm)?"
PLANE = r"(front|right|top) plane"


def assembly_answer(args, answer):
    """Collect a component list and one placement per instance before compiling the assembly."""
    if "components" not in args:
        names = re.split(r"\s*(?:,|\band\b)\s*", re.sub(r"^components?\s*[:=]\s*", "", answer, flags=re.I))
        if not all(re.fullmatch(r"[\w][\w ()-]{0,64}", name) for name in names):
            raise ValueError("Give component names separated by commas.")
        args["components"] = names
        args["placements"] = []
        return None
    if len(args["placements"]) == len(args["components"]):
        if answer.lower() in {"placement only", "no mates"}:
            return []
        mates = re.split(r"\s+then\s+", answer, flags=re.I)
        if not all((ops := operations(command)) and ops[0][0] == "mate_planes" for command in mates):
            raise ValueError('Use placement only, or mate "Plane@Component-1" to "Plane@Component-2".')
        return mates
    if "component_definition" in args:
        if re.fullmatch(rf"(?:at\s*)?(?:{TRIPLE}|(?:the )?origin)", answer, re.I):
            answer = args["component_definition"] + " at " + re.sub(r"^at\s*", "", answer, flags=re.I)
    answer = re.sub(r"\s+at (?:the )?origin$", " at (0,0,0)", answer, flags=re.I)
    pos = re.fullmatch(rf'(.+?)\s+at\s*{TRIPLE}', answer, re.I)
    if not pos:
        args["component_definition"] = answer
        return None
    definition = pos[1].strip()
    file = re.fullmatch(r'(?:insert\s+)?"([^"]+)"', definition, re.I)
    build = ""
    if not file:
        file = re.fullmatch(r'(.+)\s+then\s+save as\s+"([^"]+)"', definition, re.I)
        build = file[1] if file else definition
    path = _path(file.groups()[-1], saving=bool(build)) if file else None
    args["placements"].append(dict(path=path, build=build, origin=_numbers(pos.groups()[1:])))
    args.pop("component_definition", None)
    return None


def custom_question(args):
    scope = args.get("scope")
    if scope == "assembly":
        if "components" not in args:
            return f"Which components make up {args['brief']}? List the names, separated by commas."
        index = len(args["placements"])
        if index < len(args["components"]):
            name = args["components"][index]
            if "component_definition" in args:
                return f"Where should I place {name}? Type origin for (0,0,0), or enter (x,y,z) in mm."
            return (f"What shape and dimensions should {name} have? I can build it inside the assembly. "
                    "To reuse an existing component, enter its full path in quotes.")
        return ('How should the components be constrained? Reply with placement only, or use '
                'mate "Front Plane@Frame-1" to "Front Plane@Motor-1". Join mates with then.')
    if scope == "part":
        return ("Describe the outline and its dimensions, then any holes or other features. "
                "For example, a trapezoidal plate, 50 mm across the bottom, 40 mm across the top, "
                "20 mm tall and 8 mm thick, with the left edge vertical, then add a 6 mm hole.")
    return "Is this a single part or an assembly? Reply with part, assembly, or the modeling steps."


def _numbers(values):
    values = tuple(map(float, values))
    if not all(map(math.isfinite, values)):
        raise ValueError("Give finite coordinates and dimensions.")
    return values


def _dimension(values):
    values = _numbers(values)
    if min(values) <= 0:
        raise ValueError("All base dimensions must be positive.")
    return values


def _path(text, *, saving=False):
    path = Path(text)
    if not path.is_absolute() or path.suffix.lower() not in {".sldprt", ".sldasm"}:
        raise ValueError("Use a full .SLDPRT or .SLDASM file path.")
    if saving and (path.exists() or not path.parent.is_dir()):
        raise ValueError("Choose an unused filename in an existing folder.")
    return str(path)


def operations(command):
    """Return adapter operations for a complete custom feature, or None for another command."""
    p = command.strip()
    if re.fullmatch(r"(?:make |create |start )?(?:a |an )?(?:new |empty )?assembly", p, re.I):
        return [("new_assembly", {})]
    match = re.fullmatch(r'insert\s+"([^"]+)"\s+at\s*' + TRIPLE, p, re.I)
    if match:
        x, y, z = _numbers(match.groups()[1:])
        return [("insert_component", dict(file_path=_path(match[1]), x=x, y=y, z=z))]
    match = re.fullmatch(r'mate\s+"([^"]+)"\s+to\s+"([^"]+)"', p, re.I)
    if match:
        if not all(re.fullmatch(r"[^@]+@[^@]+", ref) for ref in match.groups()) or match[1].casefold() == match[2].casefold():
            raise ValueError('Give two different plane references in the form "Plane@Instance".')
        return [("mate_planes", dict(first=match[1], second=match[2]))]
    match = re.fullmatch(r'save as\s+"([^"]+)"', p, re.I)
    if match:
        return [("save_model", {"file_path": _path(match[1], saving=True)})]
    p = re.sub(r"^(?:make|create|add|extrude)\s+(?:an?\s+)?(?=(?:block|cylinder)\b)", "", p, flags=re.I)
    # A trapezoid's side lengths and alignment determine all four sketch points.
    trapezoid = re.fullmatch(
        rf"(?:trapezoid(?:al)?(?: plate)?|plate)[, ]+{SIZE}\s+(?:(?:along|across) (?:the )?)?bottom[, ]+"
        rf"{SIZE}\s+(?:(?:along|across) (?:the )?)?top[, ]+{SIZE}\s+(?:tall|high)[, ]+(?:and )?{SIZE}\s+thick"
        rf"(?:[, ]+(?:with )?(?:the )?(left edge vertical|right edge vertical|centered))?"
        rf"(?: on (?:the )?{PLANE})?[.!]?", p, re.I)
    if trapezoid:
        bottom, top, height, depth = _dimension(trapezoid.groups()[:4])
        alignment = (trapezoid[5] or "centered").lower()
        offset = {"left edge vertical": 0, "right edge vertical": bottom - top, "centered": (bottom - top)/2}[alignment]
        return [("create_sketch", {"plane_or_face": (trapezoid[6] or "front").title() + " Plane"}),
                ("sketch_closed_polyline", {"points": [(0, 0), (bottom, 0), (offset + top, height), (offset, height)]}),
                ("feature_extrude_boss", {"depth": depth})]
    match = re.fullmatch(rf"block\s+{SIZE}\s*[x×]\s*{SIZE}\s*[x×]\s*{SIZE}\s+on (?:the )?{PLANE}", p, re.I)
    if match:
        length, width, depth = _dimension(match.groups()[:3])
        profile = ("sketch_rectangle", dict(x1=0.0, y1=0.0, x2=length/2, y2=width/2, center_based=True))
    else:
        match = re.fullmatch(rf"cylinder\s+{SIZE}\s*(?:diameter|dia)\s*(?:by|x)\s*{SIZE}\s*(?:long|high)?\s*on (?:the )?{PLANE}", p, re.I)
        if match:
            diameter, depth = _dimension(match.groups()[:2])
            profile = ("sketch_circle", dict(xc=0.0, yc=0.0, radius=diameter/2))
        else:
            match = re.fullmatch(rf"extrude profile\s+((?:{PAIR}\s*)+)\s*by\s+{SIZE}\s+on (?:the )?{PLANE}", p, re.I)
            if not match:
                return None
            points = [_numbers(point) for point in re.findall(PAIR, match[1])]
            if len(points) > 1 and points[0] == points[-1]:
                points.pop()
            if len(set(points)) < 3 or len(set(points)) != len(points):
                raise ValueError("A closed outline needs at least three distinct vertices with no repeats.")
            depth, = _dimension([match[4]])
            profile = ("sketch_closed_polyline", {"points": points})
    return [("create_sketch", {"plane_or_face": match.groups()[-1].title() + " Plane"}),
            profile, ("feature_extrude_boss", {"depth": depth})]


def validate_plan(steps, exists):
    outputs = set()
    document = None
    for step in steps:
        if step.operation in {"new_part", "create_standard_part"}:
            document = ".sldprt"
        elif step.operation == "new_assembly":
            document = ".sldasm"
        elif document == ".sldprt" and step.operation in {"insert_component", "create_virtual_component", "mate_planes", "move_fastener", "screw_mate_fasteners"}:
            raise ValueError("Component placement and mates require an assembly.")
        elif document == ".sldasm" and step.operation in {"add_hole", "add_cut_pocket", "add_boss_feature",
                                                          "create_sketch", "resize_gear"}:
            raise ValueError("Put part features in their component's modeling steps before assembling it.")
        if step.operation == "save_model":
            path = Path(_path(step.args["file_path"], saving=True))
            if document and path.suffix.lower() != document:
                raise ValueError(f"The document at this step needs a {document.upper()} filename.")
            if path in outputs or exists(path):
                raise ValueError(f"The plan would overwrite {path}. Choose distinct output files.")
            outputs.add(path)
        elif step.operation == "insert_component":
            path = Path(step.args["file_path"])
            if path not in outputs and not exists(path):
                raise ValueError(f"Component file missing: {path}. Supply its path or include a step to make and save it first.")
