"""Local command planning and execution shared by the terminal and MCP tools."""

import inspect
import math
import re
from pathlib import Path
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock
from uuid import uuid4

from ..com_adapter.base import BaseSolidWorksAdapter, CADResult, COMPONENT_OPERATIONS
from ..native_commands import find_commands, start_command
from ..parametric.enclosures import generate_enclosure_box
from ..parametric.gears import generate_spur_gear, generate_helical_gear
from .gear_request import gear_changes, helical_request
from . import fasteners
from .codex_planner import CodexPlanner
from .catalog import lookup
from .standards import DESIGNATION, design_reference, format_reference, lookup_dimensions, offline_inventory
from .placement import place_features
from .custom_design import TRIPLE, assembly_answer, operations as custom_operations, validate_plan
from .requirements import fields, missing_fields, named_values, parse_value, question, read_answer, read_named_values
from ..parametric.mechanisms import generate_connecting_rod, generate_crank_arm
from ..parametric.prismatic import generate_l_bracket, generate_mounting_bracket, generate_structural_tube
from ..parametric.rotational import generate_flange, generate_stepped_shaft, generate_bushing, generate_dowel_pin
from ..parametric.thermal import generate_heat_sink


PARTS = {
    "mounting bracket": generate_mounting_bracket, "bracket": generate_mounting_bracket,
    "mounting plate": generate_mounting_bracket, "plate": generate_mounting_bracket,
    "l-bracket": generate_l_bracket, "l bracket": generate_l_bracket,
    "flange": generate_flange, "mounting flange": generate_flange,
    "gear": generate_spur_gear, "spur gear": generate_spur_gear,
    "helical gear": generate_helical_gear,
    "connecting rod": generate_connecting_rod, "crank": generate_crank_arm,
    "crank arm": generate_crank_arm, "enclosure": generate_enclosure_box,
    "box": generate_enclosure_box, "heat sink": generate_heat_sink,
    "stepped shaft": generate_stepped_shaft, "shaft": generate_stepped_shaft,
    "bushing": generate_bushing, "sleeve bushing": generate_bushing, "bearing bushing": generate_bushing,
    "dowel pin": generate_dowel_pin, "pin": generate_dowel_pin,
    "structural tube": generate_structural_tube, "tube": generate_structural_tube, "pipe": generate_structural_tube,
}
INSPECT = {"inspect": "get_feature_tree", "inspect model": "get_feature_tree",
           "show features": "get_feature_tree", "mass properties": "get_mass_properties",
           "preview": "capture_viewport_image", "rebuild": "rebuild"}
N = r"(?:\d+(?:\.\d+)?|\.\d+)"
MM = r"(?:\s*mm)?"
SIZE = rf"({N}){MM}"
REPEAT = {"add_hole", "add_cut_pocket", "add_boss_feature"}
HELP = ("Try 'make a new bracket 100 x 60 x 10', 'add a 6 mm hole at (20, 10)', "
        "'add a 12 x 8 mm pocket 3 mm deep', 'set D1@Boss-Extrude1 to 12 mm', "
        "'make a helical gear with 15 mm OD and 10 mm bore', 'show features', or 'preview'. Join steps with 'then'. Lengths are in mm. "
        "Answer any missing design questions, say 'use defaults' for the suggested values, or 'cancel' to discard the request. "
        "Type a topic such as 'roller chain' to search the local reference guides. "
        "Start with 'plan' to review a custom part or machine assembly without opening SolidWorks. "
        "Start with 'codex' for Codex planning, or type 'model status'. "
        "Use 'find command loft' to search SolidWorks and 'run command LoftedBossBase' to open a native tool.")


@dataclass
class Step:
    operation: str
    args: dict = field(default_factory=dict)
    separate: bool = False
    auto_place: bool = False
    placement_revision: tuple | None = None
    dimension_source: dict | None = None


@dataclass
class Plan:
    steps: list[Step]
    preview: bool


def _guide_search(reply, query, *, matches_only=False):
    data = offline_inventory(query)
    if matches_only and not (data["total"] or data["page_matches"]):
        return None
    message = (f"{data['families']} Toolbox families available offline. "
               f"Found {data['total']} matching filenames and returned {len(data['page_matches'])} guide pages."
               if data["status"] == "success" else data["message"])
    return dict(reply, status=data["status"], message=message, data=data)


def _is_reference_topic(prompt):
    # Only consider a short topic after the CAD command parser has declined it.
    return (re.fullmatch(r"[\w./-]+(?:\s+[\w./-]+){0,5}", prompt) is not None
            and not re.search(r"\b(?:then|please|make|create|design|build|model|add|change|edit|set|"
                              r"move|rotate|cut|remove|delete|replace|draw|insert|extrude|resize|"
                              r"can|could|would|want|need|use)\b", prompt, re.I))


def _new_design_requested(prompt):
    return bool(re.search(r"^(?:please\s+)?(?:(?:plan|make|create|design|build|model|start)\s+)*(?:me\s+)?"
                          r"(?:an?\s+)?(?:new|another|separate)\b|\b(?:in|as)\s+(?:an?\s+)?"
                          r"(?:new|separate)\s+(?:part|document|assembly|model)\b", prompt.strip(), re.I))


def _part(prompt):
    fastener = fasteners.request(prompt)
    if fastener is not None:
        return Step("custom_design", {"brief": "nut and bolt", "fastener": fastener}, _new_design_requested(prompt))
    helical = helical_request(prompt)
    if helical:
        separate, args = helical
        return Step("create_standard_part", {"name": "helical gear", **args}, separate)
    # Normalize both "24-tooth spur gear" and "spur gear with 24 teeth".
    prompt = re.sub(r"\b(\d+)[ -]+(?:tooth|teeth)\s+((?:spur )?gear)\b(?:\s+with\b)?",
                    lambda m: f"{m[2]} with {m[1]} teeth" + (", " if m[0].endswith("with") else ""), prompt)
    prompt = re.sub(rf"\b{SIZE}\s+(?:diameter|od)\s+((?:mounting )?flange)\b(?:\s+with\b)?",
                    lambda m: f"{m[2]} with outer diameter={m[1]}" + (", " if m[0].endswith("with") else ""), prompt)
    names = "|".join(re.escape(name) for name in sorted(PARTS, key=len, reverse=True))
    match = re.fullmatch(
        rf"(?:(?:make|create|design|build|model|start)\s+)?(?:an?\s+)?"
        rf"(?:(new|another|separate)\s+)?(?:a\s+)?({names}|(?:empty )?part)(?:\s+(.*))?",
        prompt,
    )
    if not match:
        return None
    separate, name, details = match.groups()
    if name.endswith("part"):
        if not details:
            return Step("new_part", separate=bool(separate))
        return None
    generator = PARTS[name]
    step = Step("create_standard_part", {"name": name}, bool(separate))
    if details:
        details = re.sub(r"^(?:with|of|measuring)\s+", "", details)
        triple = re.fullmatch(rf"{SIZE}\s*[x×]\s*{SIZE}\s*[x×]\s*{SIZE}", details)
        if triple and generator in {generate_mounting_bracket, generate_enclosure_box}:
            last = "height" if generator == generate_enclosure_box else "thickness"
            step.args.update(zip(("length", "width", last), map(float, triple.groups())))
        else:
            read_named_values(step, PARTS, details)
    return step


def _step(command):
    p = re.sub(r"\s+", " ", command.strip().rstrip(".!?")).lower()
    p = re.sub(r"^please ", "", p)
    search = re.fullmatch(r"find commands?(?: (.*?))?(?: page ([1-9]\d*))?", p)
    if search:
        return Step("find_native_commands", {"query": search[1] or "", "offset": (int(search[2] or 1) - 1) * 20})
    if p.startswith("run command "):
        return Step("start_native_command", {"name": p.removeprefix("run command ").strip()})
    if p in INSPECT:
        return Step(INSPECT[p])
    if placement := fasteners.placement_request(p):
        return Step(*placement)
    thread = re.fullmatch(r"(?:(?:can|could) you (?:please )?)?(?:add(?: modeled| real)? thread(?:s|ing)?(?: to)?|thread)"
                          r"(?: (?:the |my )?(both parts|both|both of them|them|nut and (?:the )?bolt|bolt and (?:the )?nut|nut|bolt))?", p)
    if thread:
        target = thread[1]
        return Step("thread_fasteners", {"target": target if target in {"bolt", "nut"} else "both"})
    changes = gear_changes(p)
    if changes:
        return Step("resize_gear", changes)
    if re.fullmatch(r"(?:make|create|design|build|model)(?: (?:a |an )?(?:design|model|something))?", p):
        return Step("choose_design")
    part = _part(p)
    if part:
        return part

    # Dimension changes: "set thickness to 12 mm", "change width to 80", "set D1@Boss-Extrude1 to 10"
    dim_match = re.fullmatch(
        rf"(?:(?:can|could) you (?:please )?)?(?:set|change|modify)\s+(?:the\s+)?(?:dimension\s+)?([\w.@-]+)\s+(?:to|=)\s+{SIZE}",
        command.strip(), re.I,
    )
    if dim_match:
        dim_name = dim_match[1]
        val_mm = float(dim_match[2])
        aliases = {
            "thickness": "D1@Boss-Extrude1",
            "depth": "D1@Boss-Extrude1",
            "height": "D1@Boss-Extrude1",
            "length": "D1@Sketch1",
            "width": "D2@Sketch1",
            "diameter": "D1@Sketch1",
            "radius": "D1@Fillet1",
            "fillet": "D1@Fillet1",
            "chamfer": "D1@Chamfer1",
        }
        resolved = aliases.get(dim_name.lower(), dim_name)
        return Step("set_dimension", {"dimension_name": resolved, "value_mm": val_mm})

    # Strip phrases like "in the same part", "on the active part", "to it"
    p = re.sub(r"\b(?:in|on|to)\s+(?:the\s+)?(?:active|same|current|this)?\s*(?:part|model|body)\b", "", p).strip()
    p = re.sub(r"^(?:in|on)\s+(?:the\s+)?(?:active|same|current|this)\s*part[,:\s]+", "", p).strip()
    p = re.sub(r"\s+(?:to|in|on)\s+(?:it|them)$", "", p).strip()

    placement = {}
    # Extract Plane: e.g. "on front plane", "on top plane", "front plane"
    plane_match = re.search(r"\b(?:on\s+(?:the\s+)?)?(front|top|right)\s+plane\b", p)
    if plane_match:
        placement["plane_or_face"] = plane_match[1].title() + " Plane"
        p = (p[:plane_match.start()] + " " + p[plane_match.end():]).strip()

    # Extract Center: "in the center", "at center", "centered", "at the center", "in middle"
    center_match = re.search(r"\b(?:at|in)?\s*(?:the\s+)?(?:center|middle)\b|\bcentered\b", p)
    if center_match:
        placement["xc"] = 0.0
        placement["yc"] = 0.0
        p = (p[:center_match.start()] + " " + p[center_match.end():]).strip()

    # Extract Coordinates: "at (10, 20)", "at (10, -5)", "at x=10, y=20"
    loc_match = re.search(rf"\bat\s*\(\s*(-?{N})\s*,\s*(-?{N})\s*\)", p)
    if loc_match:
        placement["xc"] = float(loc_match[1])
        placement["yc"] = float(loc_match[2])
        p = (p[:loc_match.start()] + " " + p[loc_match.end():]).strip()
    else:
        loc_xy = re.search(rf"\bat\s*x\s*=\s*(-?{N})\s*[,;]?\s*y\s*=\s*(-?{N})", p)
        if loc_xy:
            placement["xc"] = float(loc_xy[1])
            placement["yc"] = float(loc_xy[2])
            p = (p[:loc_xy.start()] + " " + p[loc_xy.end():]).strip()

    p = re.sub(r"\s+", " ", p).strip()
    if p in {"repeat", "repeat it", "add another one"}:
        return Step("repeat", placement)
    p = re.sub(r"^(?:(?:can|could) you (?:please )?)?(?:add|drill|cut|apply|make|create|put)\s+(?:an?\s+)?", "", p).strip()

    # Holes: "10mm hole", "10mm through hole", "10mm blind hole 5mm deep", "hole 10mm", "hole of 10mm"
    if re.search(r"\bhole\b", p):
        args = placement.copy()
        is_through = bool(re.search(r"\b(through|thru)\b", p))
        is_blind = bool(re.search(r"\bblind\b", p))
        depth_match = re.search(rf"(?:depth\s*(?:=|:|\s)?\s*|deep\s+){SIZE}|{SIZE}\s+deep", p)
        if depth_match:
            d_val = next(v for v in depth_match.groups() if v is not None)
            args["depth"] = float(d_val)
            args["through_all"] = False
        elif is_through:
            args["through_all"] = True
        elif is_blind:
            args["through_all"] = False
        else:
            args.setdefault("through_all", True)

        dia_match = (
            re.search(rf"{SIZE}\s*(?:diameter|dia)?\s*(?:through|blind)?\s*hole", p) or
            re.search(rf"hole\s*(?:with\s+|of\s+)?(?:diameter\s+|dia\s+)?(?:=|:|\s)?\s*{SIZE}", p) or
            re.search(rf"(?:diameter|dia|Ø)\s*(?:=|:|\s)?\s*{SIZE}", p) or
            re.search(rf"^{SIZE}$", p)
        )
        if dia_match:
            d_val = next(v for v in dia_match.groups() if v is not None)
            args["diameter"] = float(d_val)

        return Step("add_hole", args)

    # Fillet: "fillet 3mm", "fillet edges to 3mm", "fillet all edges 3mm", "3mm fillet", "fillet with radius 3mm"
    if re.search(r"\bfillet\b", p):
        r_match = re.search(rf"(?:radius\s*(?:=|:|\s)?\s*|to\s+|by\s+|of\s+|with\s+)?{SIZE}(?:\s*radius)?", p)
        if not r_match or not r_match.group(1):
            r_match = re.search(rf"{SIZE}\s+fillet", p)
        args = {}
        if r_match and r_match.group(1):
            args["radius"] = float(r_match.group(1))
        return Step("feature_fillet", args)

    # Chamfer: "chamfer 2mm", "chamfer edges by 2mm", "2mm chamfer", "chamfer 2mm at 45 deg"
    if re.search(r"\bchamfer\b", p):
        d_match = re.search(rf"(?:distance\s*(?:=|:|\s)?\s*|to\s+|by\s+|of\s+|with\s+)?{SIZE}", p)
        if not d_match or not d_match.group(1):
            d_match = re.search(rf"{SIZE}\s+chamfer", p)
        ang_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:deg|degree|degrees)", p)
        args = {"angle_degrees": float(ang_match[1]) if ang_match else 45.0}
        if d_match and d_match.group(1):
            args["distance"] = float(d_match.group(1))
        return Step("feature_chamfer", args)

    # Shell: "shell 2.5mm", "shell with 2.5mm thickness", "shell thickness 2.5mm", "2.5mm shell"
    if re.search(r"\bshell\b", p):
        t_match = re.search(rf"(?:thickness\s*(?:=|:|\s)?\s*|to\s+|by\s+|of\s+|with\s+)?{SIZE}", p)
        if not t_match or not t_match.group(1):
            t_match = re.search(rf"{SIZE}\s+shell", p)
        args = {}
        if t_match and t_match.group(1):
            args["thickness"] = float(t_match.group(1))
        return Step("feature_shell", args)

    # Pocket or Boss: "add a 20x20 pocket 5mm deep", "cut pocket 15x15 3mm deep", "add a 20mm boss 10mm high"
    if re.search(r"\b(pocket|boss)\b", p):
        is_boss = "boss" in p
        args = placement.copy()
        dh_match = re.search(rf"(?:depth|deep|height|high|tall)\s*(?:=|:|\s)?\s*{SIZE}|{SIZE}\s+(?:deep|depth|high|tall)", p)
        if dh_match:
            d_val = next(v for v in dh_match.groups() if v is not None)
            args["depth"] = float(d_val)
        dim2_match = re.search(rf"{SIZE}\s*[x\u00d7]\s*{SIZE}", p)
        if dim2_match:
            args["shape"] = "rectangle"
            if is_boss:
                args["dim1"] = float(dim2_match[1])
                args["dim2"] = float(dim2_match[2])
            else:
                args["width"] = float(dim2_match[1])
                args["height"] = float(dim2_match[2])
        else:
            dim1_match = re.search(rf"(?:diameter\s+|width\s+|size\s+)?{SIZE}\s*(?:diameter|dia)?", p)
            if dim1_match and dim1_match.group(1):
                d_val = float(dim1_match.group(1))
                if "circle" in p or "circular" in p or "round" in p:
                    args["shape"] = "circle"
                    if is_boss:
                        args["dim1"] = d_val
                    else:
                        args["width"] = d_val
                else:
                    args["shape"] = "rectangle"
                    if is_boss:
                        args["dim1"] = d_val
                        args["dim2"] = d_val
                    else:
                        args["width"] = d_val
                        args["height"] = d_val
        if "depth" not in args:
            args["depth"] = 5.0 if not is_boss else 10.0
        return Step("add_boss_feature" if is_boss else "add_cut_pocket", args)

    dimension = re.fullmatch(r"(?:set|change)\s+(?:dimension\s*)?([\w.-]+@[\w.@-]+)?", command.strip(), re.I)
    if dimension:
        return Step("set_dimension", {"dimension_name": dimension[1]} if dimension[1] else {})
    raise ValueError("I couldn't map that command to a CAD operation. " + HELP)


WASHER_FIELDS = {"inner_diameter": "INSID_DIA", "outer_diameter": "OUTSID_DIA", "thickness": "THICKNESS"}


def _washer_steps(series, size, overrides, separate):
    if not size:
        return [Step("metric_washer", {"series": series, "overrides": overrides}, separate)]
    reference = design_reference(f"M{size} {series} flat washer B18.22M")
    if reference.get("total") != 1 or not reference.get("rows") or reference["length_unit"] != "MILLIMETER":
        raise ValueError("No unique metric washer measurement row was found. Supply the sheet or its dimensions.")
    row = reference["rows"][0]
    values = {key: float(row[column]) for key, column in WASHER_FIELDS.items()}
    changed = {key: value for key, value in overrides.items() if value != values[key]}
    values.update(overrides)
    inside, outside, thickness = values["inner_diameter"], values["outer_diameter"], values["thickness"]
    if not 0 < inside < outside or thickness <= 0 or not all(map(math.isfinite, values.values())):
        raise ValueError("The washer needs a positive thickness and a bore smaller than its outer diameter.")
    if changed:
        reference = dict(reference, custom_dimensions_mm=changed)
    return [Step("new_part", separate=separate, dimension_source=reference),
            Step("create_sketch", {"plane_or_face": "Front Plane"}),
            Step("sketch_circle", dict(xc=0., yc=0., radius=outside/2)),
            Step("sketch_circle", dict(xc=0., yc=0., radius=inside/2)),
            Step("feature_extrude_boss", {"depth": thickness})]


def _washer_overrides(overrides, dimensions):
    result = overrides.copy()
    for key, value in (dimensions or {}).items():
        key = "inner_diameter" if key == "bore_diameter" else key
        if key not in WASHER_FIELDS:
            raise ValueError(f"Unknown washer dimension '{key}'.")
        result[key] = parse_value(key, str(value))
    return result


def _metric_washer(command, dimensions=None, *, choosing=False):
    washer = re.fullmatch(r"(?:(?:make|create|build|design)\s+)?(?:an?\s+)?(?:(new)\s+)?"
                          r"(?:(?:ANSI|ASME)\s+)?(?:metric\s+)?(?:M(\d+(?:\.\d+)?)\s+)?(narrow|regular|wide)\s+"
                          r"(?:flat|plain) washer(?:\s+(?:per\s+)?(?:ASME\s+)?B18\.22M)?"
                          r"(?:(?:\s+with\s+|,\s*)(.+))?", command, re.I)
    if not washer or not (washer[2] or re.search(r"\b(?:metric|B18\.22M)\b", command, re.I)):
        return None
    if not washer[2] and not choosing and not re.match(r"(?:make|create|build|design|new)\b", command, re.I):
        return None
    overrides = named_values(WASHER_FIELDS, washer[4]) if washer[4] else {}
    return _washer_steps(washer[3], washer[2], _washer_overrides(overrides, dimensions), bool(washer[1]))


def _compile(prompt, *, dimensions=None):
    steps = []
    # Keep quoted component paths intact, including spaces and semicolons.
    chunks = re.split(r'(?:\s+(?:and\s+)?then\s+|;\s*)(?=(?:[^"]*"[^"]*")*[^"]*$)', prompt, flags=re.I)
    for command in chunks:
        command = command.strip()
        washer = _metric_washer(command, dimensions if not steps else None)
        if washer:
            steps.extend(washer)
            continue
        create_shape = re.match(r"^(?:make|create|build|design)\s+(?:a\s+)?(?:(new)\s+)?(?=(?:block|cylinder|trapezoid(?:al)?|plate)\b)", command, re.I)
        operations = custom_operations(command[create_shape.end():] if create_shape else command)
        if operations:
            if create_shape:
                steps.append(Step("new_part", separate=bool(create_shape[1])))
            steps.extend(Step(op, args, bool(re.search(r"\bnew\b", command, re.I))) for op, args in operations)
            continue
        try:
            steps.append(_step(command))
        except ValueError as exc:
            request = re.fullmatch(r"(?:please\s+)?(?:make|create|design|build|model)\s+(.+)", command, re.I)
            if not request or not str(exc).startswith(("I couldn't map", "I couldn't read", "Unrecognized helical gear detail")):
                raise
            brief = request[1]
            args = {"brief": brief}
            if re.search(r"\b(?:single|custom|machine) part\b", brief, re.I):
                args["scope"] = "part"
            elif re.search(r"\b(?:assembly|machine)\b", brief, re.I):
                args["scope"] = "assembly"
            steps.append(Step("custom_design", args, _new_design_requested(command)))
    return steps


def _custom_steps(current, answer, file_exists, translate=None):
    if "fastener" not in current.args:
        # Requests already sitting at the generic component prompt can resume here.
        spec = fasteners.request(current.args.get("brief", ""))
        if spec is not None and not current.args.get("placements"):
            current.args["fastener"] = spec
    if "fastener" in current.args:
        spec = current.args["fastener"]
        if not fasteners.answer(spec, answer):
            return [current]
        return [Step(op, args, separate=op == "new_part" or (op == "new_assembly" and (current.separate or "folder" in spec)))
                for op, args in fasteners.layout(spec, file_exists)]
    if answer.lower() in {"part", "single part", "assembly", "machine assembly"}:
        current.args["scope"] = "assembly" if "assembly" in answer.lower() else "part"
        return [current]
    if current.args.get("scope") == "assembly":
        # Validate a component's modeling instruction before advancing to the next one.
        args = dict(current.args)
        if "placements" in args:
            args["placements"] = args["placements"].copy()
        mates = assembly_answer(args, answer)
        placements = args.get("placements", [])
        if mates is None:
            if placements and placements[-1]["build"] and placements[-1]["path"] is None:
                item = placements[-1]
                _virtual_component(args["components"][len(placements)-1], item["origin"], item["build"])
            elif placements and placements[-1]["build"]:
                _component_steps(placements[-1]["build"])
            elif placements and not (file_exists(placements[-1]["path"]) or
                                     any(item["build"] and item["path"] == placements[-1]["path"] for item in placements[:-1])):
                raise ValueError("That component file was not found. Supply its path or its features and save path.")
            if "component_definition" not in args:
                current.args.pop("component_definition", None)
            current.args.update(args)
            return [current]
        parts = []
        inserts = []
        for name, item in zip(args["components"], placements):
            if item["path"] is None:
                inserts.append(_virtual_component(name, item["origin"], item["build"]))
                continue
            if item["build"]:
                parts.extend(_component_steps(item["build"]))
                parts.append(Step("save_model", {"file_path": item["path"]}))
            x, y, z = item["origin"]
            inserts.append(Step("insert_component", dict(file_path=item["path"], x=x, y=y, z=z)))
        return parts + [Step("new_assembly", separate=bool(parts) or current.separate)] + inserts + [s for mate in mates for s in _compile(mate)]
    try:
        steps = _compile(answer)
    except ValueError:
        if not translate:
            raise
        steps = []
    if translate and (not steps or any(s.operation == "custom_design" for s in steps)):
        steps = translate(answer, history=[{"role": "user", "content": current.args["brief"]},
                          {"role": "assistant", "content": "Describe the shape, sizes and features of the part."}])
        if any(s.operation == "codex_question" for s in steps):
            return steps
    if any(step.operation in {"custom_design", "choose_design"} for step in steps):
        raise ValueError("I still need the part geometry or component layout.")
    if steps[0].operation in {"create_sketch", "add_boss_feature"}:
        steps.insert(0, Step("new_part", separate=current.separate))
    elif steps[0].operation == "insert_component":
        steps.insert(0, Step("new_assembly", separate=current.separate))
    if not any(s.operation in {"feature_extrude_boss", "create_standard_part", "metric_washer", "add_boss_feature", "insert_component"} for s in steps):
        raise ValueError("Include the solid features or assembly components that define this design.")
    if steps[0].operation in {"new_part", "new_assembly", "create_standard_part", "metric_washer"}:
        steps[0].separate |= current.separate
    return steps


def _component_steps(description):
    steps = _compile(description)
    if steps[0].operation == "create_sketch":
        steps.insert(0, Step("new_part", separate=True))
    if (steps[0].operation not in {"new_part", "create_standard_part"} or
            any(s.operation in {"choose_design", "custom_design", "insert_component", "save_model",
                                "new_assembly", "start_native_command"} for s in steps) or
            not any(s.operation in {"feature_extrude_boss", "add_boss_feature", "create_standard_part"} for s in steps)):
        raise ValueError("Give the base geometry for this component, followed by its features.")
    steps[0].separate = True
    return steps


def _virtual_component(name, origin, description):
    """Compile component geometry without granting nested document or file operations."""
    if not re.fullmatch(r"[\w][\w .-]{0,63}", name) or not all(math.isfinite(v) for v in origin):
        raise ValueError("Give a component name and finite origin coordinates.")
    features = _component_steps(description)[1:]
    place_features(features)
    if not features or any(s.operation not in COMPONENT_OPERATIONS or missing_fields(s, PARTS) for s in features):
        raise ValueError(f"Specify complete sketch and extrusion features for {name}, including placement for holes and pockets.")
    return Step("create_virtual_component", {"name": name, "origin": list(origin),
                "features": [{"operation": s.operation, "arguments": s.args} for s in features]})


class LocalCADAgent:
    def __init__(self, adapter: BaseSolidWorksAdapter, *, planner=None):
        self.adapter = adapter
        self.last_edit = OrderedDict()
        self.last_fasteners = OrderedDict()
        self.pending = OrderedDict()
        self.reviewed = OrderedDict()
        self.layout = None
        self.layout_revision = None
        self.lock = Lock()
        self.planner = CodexPlanner() if planner is None else planner

    def _codex_steps(self, prompt, history=(), literal=()):
        if placement := fasteners.placement_request(prompt):
            return [Step(*placement)]
        if history and re.search(r"\bthread(?:s|ing)?\b", history[0]["content"], re.I):
            if re.fullmatch(r"(?:the )?(?:nut and bolt|bolt and nut|both|nut|bolt)", prompt.strip(), re.I):
                return [_step("add threads to " + prompt.strip())]
        # Preserve literal trailing edits, including any intentionally omitted hole size or location.
        parts = re.split(r"\s+(?:and\s+)?then\s+", prompt, maxsplit=1, flags=re.I)
        if len(parts) == 2 and (not literal or any(s.operation == "custom_design" for s in literal)):
            try:
                edits = _compile(parts[1])
            except ValueError:
                edits = []
            if edits and all(s.operation in REPEAT for s in edits):
                base = literal[:-len(edits)] if literal else ()
                return self._codex_steps(parts[0], history, base) + edits
        # Fully specified grammar and template fields are authoritative. In particular,
        # a paraphrase must not add guessed dimensions or drop part of an explicit edit.
        exact = literal and all(s.operation != "custom_design" or "fastener" in s.args for s in literal)
        if exact:
            return literal
        messages = [*history, {"role": "user", "content": prompt}]
        new_design = any(_new_design_requested(m["content"]) for m in messages if m["role"] == "user")
        kind, answer = self.planner.translate(messages)
        if kind == "question":
            messages.append({"role": "assistant", "content": answer})
            return [Step("codex_question", {"question": answer, "messages": messages})]
        if kind == "assembly":
            if re.match(r"(?:please\s+)?(?:add|edit|change|modify|cut|drill|resize|move|place|position|align)\b", messages[0]["content"], re.I):
                raise ValueError("Specify the feature to edit in the active part; this proposal creates an assembly.")
            steps = [Step("new_assembly", separate=new_design)]
            for line in answer.strip().splitlines():
                item = re.fullmatch(rf"(.+?)\s+at\s*{TRIPLE}\s*:\s*(.+)", line.strip(), re.I)
                if not item:
                    raise ValueError("Codex returned an incomplete component layout. Specify each component's shape and origin.")
                steps.append(_virtual_component(item[1], list(map(float, item.groups()[1:4])), item[5]))
            return steps
        steps = _compile(answer)
        if any(s.operation in {"save_model", "insert_component", "start_native_command"} for s in steps):
            raise ValueError("Enter file or native desktop commands directly in the CAD agent.")
        if any(s.operation == "custom_design" and "fastener" not in s.args for s in steps):
            followup = "What shapes, dimensions and placements should define this design?"
            return [Step("codex_question", {"question": followup, "messages": [
                *messages, {"role": "assistant", "content": followup}]})]
        if re.match(r"(?:please\s+)?(?:add|edit|change|modify|cut|drill|resize|move|place|position|align)\b", messages[0]["content"], re.I):
            if any(s.operation in {"new_part", "new_assembly", "create_standard_part", "custom_design", "metric_washer"} or s.separate for s in steps):
                raise ValueError("The proposed design would start a separate document. Specify the feature to edit in the active part.")
        if new_design and steps[0].operation == "create_sketch":
            steps.insert(0, Step("new_part", separate=True))
        elif new_design and steps[0].operation in {"new_part", "new_assembly", "create_standard_part", "metric_washer", "custom_design"}:
            steps[0].separate = True
        elif not new_design:
            for step in steps:
                step.separate = False
        return steps

    def invoke_native(self, name):
        with self.lock:
            connection = self.adapter.connect()
            if not connection.success:
                return connection
            return start_command(self.adapter, name)

    def run(self, prompt: str, conversation_id: str | None = None, *,
            design_type=None, dimensions=None, separate=False, design_tool=False) -> dict:
        session = conversation_id or str(uuid4())
        operations = []
        reply = {"conversation_id": session, "operations": operations}
        if prompt.strip().lower() in {"help", "?"}:
            return dict(reply, status="success", message=HELP)
        if prompt.strip().lower() == "model status":
            return dict(reply, status="success", message=self.planner.status())
        inventory = re.fullmatch(r"offline standards(?:\s+(.+))?|look up\s+(.+)", prompt.strip(), re.I)
        if inventory:
            return _guide_search(reply, inventory[1] or inventory[2] or "")
        standard = re.fullmatch(r"find standards?\s+(.+)", prompt.strip(), re.I)
        sheet = re.fullmatch(r"standard sheet\s+(\S+)(?:\s+(.+))?", prompt.strip(), re.I)
        if standard or sheet:
            if standard:
                scope = re.fullmatch(r"\[([^\]]+)\]\s*(.*)", standard[1])
                reference = lookup_dimensions(scope[2], library=scope[1]) if scope else design_reference(standard[1])
            else:
                pairs = [s.strip().partition("=") for s in (sheet[2] or "").split(",") if s.strip()]
                if any(not sep or not k or not v for k, sep, v in pairs):
                    return dict(reply, status="error", message="Use field=value, for example size=8.")
                selectors = {k.strip(): v.strip() for k, _, v in pairs}
                option = selectors.pop("option", "")
                page = selectors.pop("offset", "0")
                if not page.isdecimal():
                    return dict(reply, status="error", message="Use a nonnegative offset.")
                reference = lookup_dimensions(family_id=sheet[1].upper(), filters=selectors, option=option, offset=int(page))
            return dict(reply, status="success" if reference["status"] in {"rows", "families"} else "error",
                        message=format_reference(reference), data=reference)
        search = re.fullmatch(r"find parts?\s+(.+)", prompt.strip(), re.I)
        if search:
            try:
                matches = lookup(search[1])
            except (OSError, UnicodeError, ValueError) as exc:
                return dict(reply, status="error", message=f"Could not read the parts library. {exc}")
            return dict(reply, status="success", message="\n".join(matches) or "No matching catalog entries.",
                        data={"matches": matches})
        with self.lock:
            try:
                if prompt.strip().lower() == "cancel":
                    self.pending.pop(session, None)
                    self.reviewed.pop(session, None)
                    return dict(reply, status="cancelled", message="Pending design cancelled.")
                if fasteners.placement_request(prompt):
                    self.pending.pop(session, None)
                pending = self.pending.get(session)
                error = None
                plan_summary = None
                if prompt.strip().lower() in {"build plan", "build this plan", "build the plan"}:
                    steps = self.reviewed.pop(session, None)
                    if not steps:
                        raise ValueError("There is no completed plan in this conversation.")
                    preview = False
                elif pending is not None:
                    steps, preview = pending.steps, pending.preview
                    current = next(s for s in steps if missing_fields(s, PARTS))
                    try:
                        if current.operation == "codex_question":
                            index = steps.index(current)
                            steps[index:index+1] = self._codex_steps(prompt.strip(), current.args["messages"])
                        elif current.operation == "metric_washer":
                            answer = prompt.strip().rstrip(".!?")
                            size = re.fullmatch(r"M?\s*(\d+(?:\.\d+)?)(?:(?:\s*,\s*|\s+with\s+|\s+and\s+)(.+))?", answer, re.I)
                            details = size[2] if size else answer
                            overrides = _washer_overrides(current.args["overrides"], dimensions)
                            if details:
                                overrides.update(named_values(WASHER_FIELDS, details))
                            index = steps.index(current)
                            steps[index:index+1] = _washer_steps(current.args["series"], size[1] if size else None,
                                                                 overrides, current.separate)
                        elif current.operation in {"choose_design", "custom_design"}:
                            if current.operation == "custom_design":
                                replacement = _custom_steps(current, prompt.strip(), self.adapter.component_file_exists,
                                                            self._codex_steps if self.planner.available() else None)
                                if len(steps) == 1 and "fastener" in current.args and replacement[-1].operation in {"create_virtual_component", "save_model"}:
                                    spec = current.args["fastener"]
                                    output = replacement[-1].args.get("file_path", "Two virtual assembly components")
                                    plan_summary = (f"Hex fastener layout\n"
                                                    f"  Bolt: M{spec['diameter']}, {spec['length']:g} mm under the head\n"
                                                    f"  Nut: matching hex nut, flush with the bolt tip\n"
                                                    f"  Output: {output}\n\nType 'build plan' to create it.")
                            else:
                                replacement = _metric_washer(prompt.strip(), dimensions, choosing=True)
                                if replacement is None:
                                    choice = _part(prompt.strip().lower())
                                    replacement = [choice or Step("custom_design", {"brief": prompt.strip()})]
                                replacement[0].separate |= current.separate
                            index = steps.index(current)
                            steps[index:index+1] = replacement
                        elif current.args.get("name") in {"gear", "spur gear", "helical gear"} and (changes := gear_changes(prompt)):
                            current.args.update(changes)
                        else:
                            read_answer(current, PARTS, prompt.strip())
                    except ValueError as exc:
                        error = str(exc)
                else:
                    if design_type and not prompt.strip():
                        prompt = design_type
                    hold = re.search(r"(?:[,;.\s]+)(?:do not|don['’]?t) (?:build|create|model|make|start)"
                                     r"(?: (?:making|modeling|building))?(?: (?:it|anything|yet|now))*[.!\s]*$", prompt, re.I)
                    if hold:
                        prompt = prompt[:hold.start()].strip()
                    mode = re.match(r"^\s*(?:please\s+)?plan(?:\s+only)?\s+(.+)$", prompt, re.I | re.S)
                    preview = bool(mode or hold)
                    if mode:
                        prompt = mode[1]
                    user_request = prompt
                    if re.search(r"\b(?:ANSI|ASME)\b", prompt, re.I) or DESIGNATION.search(prompt):
                        reference = design_reference(prompt)
                        if re.search(DESIGNATION.pattern + r"\s*(?:[-:]\s*|\()(?:19|20)\d{2}", prompt, re.I):
                            return dict(reply, status="error", data=reference,
                                        message="Supply the dimensional sheet for the specified edition. "
                                                "The installed Toolbox does not identify its source edition. "
                                                + reference["publisher_lookup"])
                        if reference["status"] not in {"rows", "families"}:
                            return dict(reply, status="error", data=reference, message=format_reference(reference))
                    if mode:
                        if not fasteners.placement_request(prompt) and not re.match(r"(codex|make|create|design|build|model|new|add|insert|mate|extrude|block|cylinder|change|set)\b", prompt, re.I):
                            prompt = "design " + prompt
                    model_request = re.fullmatch(r"\s*codex(?:\s*:\s*|\s+)(.+)", prompt, re.I | re.S)
                    if model_request:
                        steps = self._codex_steps(model_request[1].strip())
                        preview = True
                    else:
                        try:
                            steps = _compile(prompt, dimensions=dimensions)
                        except ValueError as exc:
                            if not str(exc).startswith("I couldn't map"):
                                raise
                            if not (preview or separate or design_type or dimensions) and _is_reference_topic(prompt.strip()):
                                reference = _guide_search(reply, prompt.strip(), matches_only=True)
                                if reference is not None:
                                    return reference
                            steps = []
                            if not (separate or design_tool) and not self.planner.available():
                                raise
                        design_request = (not steps or any(s.operation in {"create_standard_part", "custom_design"} for s in steps)
                                          or (re.match(r"(?:please\s+)?(?:make|create|design|build|model)\b", user_request, re.I)
                                              and not any(s.operation in {"add_hole", "add_cut_pocket", "add_boss_feature", "feature_fillet", "feature_chamfer", "feature_shell", "set_dimension"} for s in steps)))
                        explicit_tools = any(s.operation in {"save_model", "insert_component", "mate_planes", "start_native_command"}
                                             for s in steps)
                        if design_request and not explicit_tools and not (dimensions or design_type) and self.planner.available():
                            if not steps and not re.match(r"(?:please\s+)?(?:make|create|design|build|model|add|change|edit)\b", user_request, re.I):
                                preview = True
                            steps = self._codex_steps(user_request, literal=steps)
                        elif not steps:
                            steps = _compile("design " + prompt)
                    self.reviewed.pop(session, None)
                    if (separate or design_type or dimensions) and steps[0].operation not in fasteners.PLACEMENT_ACTIONS:
                        if steps[0].operation == "create_sketch":
                            steps.insert(0, Step("new_part", separate=separate))
                        if steps[0].operation not in {"choose_design", "custom_design", "create_standard_part", "new_part", "new_assembly", "codex_question", "metric_washer"}:
                            raise ValueError("Give a supported complete part design.")
                        step = steps[0]
                        step.separate |= separate
                        if step.operation == "choose_design" and design_type in PARTS:
                            step.operation = "create_standard_part"
                            step.args["name"] = design_type
                        if "fastener" in step.args and dimensions:
                            fasteners.apply_dimensions(step.args["fastener"], dimensions)
                        elif step.operation == "custom_design" and dimensions:
                            step.args["dimensions"] = dict(dimensions)
                        if design_type and step.operation == "create_standard_part" and PARTS.get(design_type) != PARTS.get(step.args.get("name")):
                            raise ValueError("The design type and the requested part differ.")
                        params = inspect.signature(PARTS[step.args["name"]]).parameters if "name" in step.args else {}
                        supplied = {} if step.operation in {"custom_design", "metric_washer"} or step.dimension_source else dimensions or {}
                        for key, value in supplied.items():
                            if key in {"adapter", "new_document"} or key not in params:
                                raise ValueError(f"Unsupported dimension '{key}' for {step.args['name']}.")
                            step.args[key] = parse_value(key, str(value))
                prior_layout = None
                first = steps[0]
                if first.operation in REPEAT and self.layout is not None:
                    if (self.adapter.geometry_revision() == self.layout_revision and
                            first.placement_revision in (None, self.layout_revision)):
                        prior_layout = self.layout
                        first.placement_revision = self.layout_revision
                if first.placement_revision is not None and prior_layout is None:
                    self.pending.pop(session, None)
                    raise ValueError("The active part changed. Request the feature again for the current part.")
                layout = place_features(steps, prior_layout)
                for s in steps:
                    if s.operation in REPEAT and "plane_or_face" not in s.args:
                        s.args["plane_or_face"] = "Front Plane"
                for step in steps:
                    if step.operation == "custom_design" and not step.separate and "scope" not in step.args and "fastener" not in step.args:
                        active_kind = self.adapter.active_document_kind()
                        if active_kind in {"part", "assembly"}:
                            step.args["scope"] = active_kind
                    design_fields = fields(step, PARTS)
                    for key, value in step.args.items():
                        if key in design_fields and type(value) in (float, int):
                            parse_value(key, str(value))
                    missing = missing_fields(step, PARTS)
                    if missing:
                        self.pending[session] = Plan(steps, preview)
                        self.pending.move_to_end(session)
                        if len(self.pending) > 128:
                            self.pending.popitem(last=False)
                        return dict(reply, **question(step, missing, error))
                self.pending.pop(session, None)
                if any(step.operation == "start_native_command" for step in steps[:-1]):
                    raise ValueError("Put 'run command' last so you can complete the command in SolidWorks.")
                validate_plan(steps, self.adapter.component_file_exists)
                sources = [s.dimension_source for s in steps if s.dimension_source]
                if sources:
                    reply["dimension_sources"] = sources
                    citation = "\n".join(format_reference(source) for source in sources)
                if preview:
                    self.reviewed[session] = steps
                    if len(self.reviewed) > 128:
                        self.reviewed.popitem(last=False)
                    plan = [{"operation": step.operation, "arguments": step.args.copy()} for step in steps]
                    lines = []
                    for index, step in enumerate(steps, 1):
                        if step.operation in {"new_part", "new_assembly"} and not step.separate:
                            kind = step.operation.removeprefix("new_")
                            lines.append(f"{index}. Use the active {kind}, or create one if no document is open")
                        elif step.operation == "create_virtual_component":
                            lines.append(f"{index}. Build {step.args['name']} at {tuple(step.args['origin'])} mm inside the assembly")
                        else:
                            details = ", ".join(f"{k}={v}" for k, v in step.args.items())
                            lines.append(f"{index}. {step.operation.replace('_', ' ')} {details}".rstrip())
                    summary = plan_summary or "Proposed SolidWorks operations\n" + "\n".join(lines)
                    return dict(reply, status="planned", message=summary + ("\n" + citation if sources else ""), plan=plan)
                if any(step.operation != "find_native_commands" for step in steps):
                    # MCP can dispatch successive requests on different COM apartments.
                    conn = self.adapter.connect()
                    if not conn.success:
                        raise ValueError(conn.message)
                    if first.placement_revision is not None and self.adapter.geometry_revision() != first.placement_revision:
                        raise ValueError("The active part changed. Request the feature again for the current part.")
                for index, step in enumerate(steps):
                    if step.operation == "repeat":
                        previous = self.last_edit.get(session)
                        if not previous:
                            raise ValueError("Specify a hole, boss or pocket first in this conversation.")
                        step = Step(previous.operation, previous.args | step.args)
                    if step.operation in {"find_native_commands", "start_native_command"}:
                        result = (find_commands(**step.args) if step.operation == "find_native_commands"
                                  else start_command(self.adapter, **step.args))
                        operations.append({"tool": step.operation, "result": result.model_dump()})
                        if not result.success:
                            raise ValueError(result.message)
                        continue
                    create = step.operation in {"create_standard_part", "new_part", "new_assembly"}
                    active = self.adapter.has_active_document()
                    if create and active and not step.separate:
                        kind = "assembly" if step.operation == "new_assembly" else "part"
                        if self.adapter.active_document_kind() != kind:
                            raise ValueError(f"Activate the {kind} you want to work on in SolidWorks.")
                        if step.operation != "create_standard_part":
                            result = CADResult(success=True, message=f"Using the active {kind}.")
                            operations.append({"tool": "use_active_" + kind, "result": result.model_dump()})
                            continue
                    if not active and step.operation == "create_sketch":
                        created = self.adapter.new_part()
                        if not created.success:
                            raise ValueError(created.message)
                        active = True
                    if not active and not create and step.operation not in fasteners.PLACEMENT_ACTIONS:
                        raise ValueError("Open or create a part first.")
                    if step.operation == "save_model" and Path(step.args["file_path"]).exists():
                        raise ValueError("The save path already exists. Choose a new filename.")
                    if step.operation == "create_standard_part":
                        args = step.args.copy()
                        generator = PARTS[args.pop("name")]
                        if generator is generate_spur_gear and "outer_diameter" in args:
                            args["module"] = args.pop("outer_diameter") / (args["num_teeth"] + 2)
                        result = generator(self.adapter, new_document=step.separate, **args)
                    elif step.operation == "screw_mate_fasteners":
                        args = {"moving": "bolt", **self.last_fasteners.get(session, {}), **step.args}
                        result = self.adapter.screw_mate_fasteners(**args)
                    else:
                        result = getattr(self.adapter, step.operation)(**step.args)
                    if step.operation in fasteners.PLACEMENT_ACTIONS and result.data.get("choices"):
                        step.args["assembly_id"] = result.data["assembly_id"]
                        step.args["pick"] = {"role": result.data["role"], "choices": result.data["choices"]}
                        self.pending[session] = Plan(steps[index:], False)
                        self.pending.move_to_end(session)
                        if len(self.pending) > 128:
                            self.pending.popitem(last=False)
                        return dict(reply, **question(step, missing_fields(step, PARTS)))
                    operations.append({"tool": step.operation, "result": result.model_dump()})
                    if not result.success:
                        raise ValueError(result.message)
                    if step.operation in fasteners.PLACEMENT_ACTIONS:
                        self.last_fasteners[session] = {k: result.data[k] for k in ("assembly_id", "bolt", "nut", "moving")}
                        self.last_fasteners.move_to_end(session)
                        if len(self.last_fasteners) > 128:
                            self.last_fasteners.popitem(last=False)
                    if create:
                        self.last_edit.pop(session, None)
                        self.last_fasteners.pop(session, None)
                    if step.operation in REPEAT:
                        self.last_edit[session] = step
                        self.last_edit.move_to_end(session)
                        if len(self.last_edit) > 128:
                            self.last_edit.popitem(last=False)
                if layout:
                    revision = self.adapter.geometry_revision()
                    self.layout, self.layout_revision = (layout if revision is not None else None), revision
                if (len(steps) >= 3 and steps[-2].operation == steps[-1].operation == "create_virtual_component"
                        and all(s.args["features"][-1]["operation"] == "add_metric_thread" for s in steps[-2:])):
                    names = [s.args["name"] for s in steps[-2:]]
                    pitch = steps[-1].args["features"][-1]["arguments"]["pitch"]
                    return dict(reply, status="success", message=f"Modeled {pitch:g} mm pitch threads on both "
                                + " and ".join(names) + ".", data={"components": names, "pitch_mm": pitch})
                return dict(reply, status="success", message=result.message + ("\n" + citation if sources else ""), data=result.data)
            except Exception as exc:
                if session in self.pending and not any(missing_fields(s, PARTS) for s in self.pending[session].steps):
                    self.pending.pop(session)
                return dict(reply, status="error", message=str(exc))
