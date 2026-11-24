"""Collect dimensions before a modeling plan is sent to SolidWorks."""

import inspect
import math
import re

from .fasteners import PLACEMENT_ACTIONS


MISSING = inspect.Parameter.empty
COUNTS = {"num_teeth", "bolt_hole_count", "fin_count"}
FLAGS = {"add_screw_bosses", "through_all"}
EDIT_FIELDS = {
    "add_hole": {"diameter": MISSING, "through_all": True, "depth": MISSING},
    "add_boss_feature": {"shape": MISSING, "dim1": MISSING, "dim2": MISSING, "depth": MISSING},
    "add_cut_pocket": {"shape": MISSING, "width": MISSING, "height": MISSING, "depth": MISSING},
    "feature_fillet": {"radius": MISSING}, "feature_shell": {"thickness": MISSING},
    "feature_chamfer": {"distance": MISSING, "angle_degrees": 45},
    "set_dimension": {"dimension_name": MISSING, "value_mm": MISSING},
}
LABELS = {"num_teeth": "tooth count", "xc": "center X", "yc": "center Y", "plane_or_face": "sketch plane",
          "through_all": "through hole (yes/no)", "segments": "shaft sections (length x diameter, separated by /)",
          "dim1": "diameter or width", "dim2": "rectangle height", "helix_angle": "helix angle (signed degrees)",
          "shape": "shape (circle or rectangle)", "dimension_name": "SolidWorks dimension name",
          "value_mm": "new dimension value", "pressure_angle": "pressure angle (degrees)"}
ZERO_OK = {"bore_diameter", "center_bore_dia", "center_bore_diameter", "corner_fillet", "corner_radius",
           "keyway_width", "keyway_depth", "hub_diameter", "hub_length", "hole_diameter",
           "chamfer_ends", "bolt_hole_count", "boss_hole_diameter"}
NUMBER = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?"


def label(key):
    return LABELS.get(key, key.replace("_", " "))


def fields(step, parts):
    args = step.args
    if step.operation in PLACEMENT_ACTIONS and "pick" in args:
        return {"instance": MISSING}
    if step.operation == "metric_washer":
        return {"nominal_size": MISSING}
    if step.operation == "codex_question":
        return {"clarification": MISSING}
    if step.operation == "choose_design":
        return {"design_type": MISSING}
    if step.operation == "custom_design":
        if "fastener" in step.args:
            spec = step.args["fastener"]
            return {next((k for k in ("diameter", "length") if k not in spec), "layout_and_folder"): MISSING}
        return {"geometry_or_components": MISSING}
    if step.operation == "create_standard_part":
        generator = parts[args["name"]]
        values = {k: p.default for k, p in inspect.signature(generator).parameters.items()
                  if k not in {"adapter", "new_document"}}
        if generator.__name__ == "generate_l_bracket":
            values.pop("hole_diameter")  # The current L-bracket generator does not use it.
        if args["name"] == "helical gear":
            values["face_width"] = args["outer_diameter"] / 3 if "outer_diameter" in args else MISSING
        elif args["name"] in {"gear", "spur gear"} and "outer_diameter" in args:
            values.pop("module")
        if values.get("hub_diameter", MISSING) is None and not args.get("hub_length"):
            values.pop("hub_diameter", None)
        if values.get("hub_length", MISSING) is None and not args.get("hub_diameter"):
            values.pop("hub_length", None)
        if args.get("hub_diameter") == 0:
            values.pop("hub_length", None)
        if args.get("bore_diameter") == 0:
            values.pop("keyway_width", None)
            values.pop("keyway_depth", None)
        if args.get("keyway_width") == 0:
            values.pop("keyway_depth", None)
        if args.get("hole_diameter") == 0:
            values.pop("hole_margin", None)
        if args.get("bolt_hole_count") == 0:
            values.pop("bolt_circle_diameter", None)
            values.pop("bolt_hole_diameter", None)
        if args.get("add_screw_bosses") is False:
            values.pop("boss_diameter", None)
            values.pop("boss_hole_diameter", None)
        return values
    values = EDIT_FIELDS.get(step.operation, {}).copy()
    if step.operation in {"add_hole", "add_boss_feature", "add_cut_pocket"}:
        values.update(xc=0.0, yc=0.0, plane_or_face="Front Plane")
    if args.get("shape") == "circle":
        for key in ("dim2", "height"):
            values.pop(key, None)
    if step.operation == "add_hole" and args.get("through_all") is not False:
        values.pop("depth", None)
    return values


def missing_fields(step, parts):
    missing = {key: default for key, default in fields(step, parts).items() if key not in step.args}
    if step.auto_place and "xc" not in step.args and "yc" not in step.args:
        missing.pop("xc", None)
        missing.pop("yc", None)
    return missing


def parse_value(key, text):
    text = text.strip()
    if key in FLAGS:
        if text.lower() in {"yes", "true", "through", "through all"}:
            return True
        if text.lower() in {"no", "false", "blind"}:
            return False
        raise ValueError("Answer yes or no.")
    if key == "segments":
        sections = []
        for section in text.split("/"):
            m = re.fullmatch(rf"\s*({NUMBER})\s*[x×]\s*({NUMBER})\s*(?:mm)?\s*", section, re.I)
            if not m or not all(math.isfinite(float(n)) and float(n) > 0 for n in m.groups()):
                raise ValueError("Give each shaft section as length x diameter, e.g. 35x25 / 50x35 / 35x20.")
            sections.append(tuple(map(float, m.groups())))
        return sections
    if key == "shape":
        if text.lower() not in {"circle", "rectangle"}:
            raise ValueError("Choose circle or rectangle.")
        return text.lower()
    if key == "plane_or_face":
        if not re.fullmatch(r"(front|top|right)( plane)?", text, re.I):
            raise ValueError("Choose Front Plane, Top Plane or Right Plane.")
        return text.lower().split()[0].title() + " Plane"
    if key == "dimension_name":
        if not re.fullmatch(r"[\w.-]+@[\w.@-]+", text):
            raise ValueError("Use a SolidWorks dimension name such as D1@Boss-Extrude1.")
        return text
    unit = "" if key in COUNTS else r"(?:°|deg(?:rees?)?)?" if "angle" in key else "(?:mm)?"
    m = re.fullmatch(rf"({NUMBER})\s*{unit}", text, re.I)
    if not m:
        raise ValueError(f"Give a number for {label(key)}.")
    value = float(m[1])
    if not math.isfinite(value) or (key not in {"xc", "yc", "helix_angle"} and
            (value < 0 or (value == 0 and key not in ZERO_OK))):
        raise ValueError(f"Invalid value for {label(key)}.")
    if key in COUNTS:
        minimum = {"num_teeth": 6, "fin_count": 2, "bolt_hole_count": 0}[key]
        if not value.is_integer() or value > 1000 or value < minimum:
            raise ValueError(f"Invalid count for {label(key)}.")
        return int(value)
    if key in {"helix_angle", "pressure_angle"} and not 0 < abs(value) < 90:
        raise ValueError(f"Specify {label(key)} with magnitude between 0 and 90.")
    return value


def read_answer(step, parts, answer):
    if step.operation in PLACEMENT_ACTIONS:
        pick = step.args["pick"]
        for number, name in enumerate(pick["choices"], 1):
            if answer.casefold() in {str(number), name.casefold()}:
                step.args[pick["role"]] = name
                del step.args["pick"]
                return
        raise ValueError("Enter the instance name or its list number.")
    missing = missing_fields(step, parts)
    if answer.lower() in {"use defaults", "use the defaults", "defaults"}:
        # Recompute after each choice (e.g. through-all removes the blind depth).
        for key, default in missing.items():
            if key in missing_fields(step, parts) and default not in (None, MISSING):
                step.args[key] = default
        return
    first = next(iter(missing))
    try:
        value = parse_value(first, answer)
    except ValueError:
        pass
    else:
        step.args[first] = value
        return
    read_named_values(step, parts, answer)


def read_named_values(step, parts, answer):
    if step.operation == "create_standard_part":
        known = set(inspect.signature(parts[step.args["name"]]).parameters) - {"adapter", "new_document"}
    else:
        known = set(EDIT_FIELDS.get(step.operation, {})).union(fields(step, parts))
    updates = named_values(known, answer)
    if step.operation == "add_hole" and "depth" in updates:
        if updates.get("through_all", step.args.get("through_all")):
            raise ValueError("Specify a blind hole for a hole with a depth.")
        updates["through_all"] = False
    if "xc" in updates or "yc" in updates:
        step.auto_place = False
    step.args.update(updates)


def named_values(known, answer):
    aliases = {k: {k, k.replace("_", " "), label(k).split(" (")[0].lower()} for k in known}
    synonyms = {
        "num_teeth": ["teeth"], "face_width": ["thickness", "width", "thick"],
        "thickness": ["thick"],
        "bore_diameter": ["bore", "id", "inter", "bore diameter", "inner diameter"],
        "inner_diameter": ["bore", "id", "inner dia", "inner diameter", "inside diameter"],
        "center_bore_diameter": ["center bore", "bore", "id", "bore diameter", "inner diameter", "hole diameter"],
        "outer_diameter": ["od", "outer dia", "outer diameter", "diameter", "dia"],
        "outer_size": ["size", "od", "width", "outer size"],
        "bolt_circle_diameter": ["pcd", "bolt circle", "bolt circle diameter", "bcd"],
        "bolt_hole_count": ["bolt holes", "holes", "bolt count", "number of holes"],
        "bolt_hole_diameter": ["bolt hole dia", "bolt hole diameter", "hole size", "hole diameter"],
        "center_distance": ["length", "center distance", "centers", "distance"],
        "fin_count": ["fins", "fin count", "number of fins"],
        "wall_thickness": ["wall", "wall thickness"],
        "corner_fillet": ["fillet", "corner fillet", "radius"],
        "corner_radius": ["radius", "fillet", "corner radius"],
        "flange_diameter": ["flange od", "collar diameter", "flange diameter"],
        "flange_thickness": ["flange thickness", "collar thickness"],
        "xc": ["x"], "yc": ["y"], "plane_or_face": ["plane"],
    }
    updates = {}
    for piece in re.split(r"\s*(?:,\s*(?:and\s+)?|&|\band\b)\s*", answer.strip(), flags=re.I):
        piece = re.sub(r"^(?:(?:please|use|set|change|the|a|custom)\s+)+", "", piece, flags=re.I)
        for key, names in aliases.items():
            names = sorted(names.union(synonyms.get(key, [])), key=len, reverse=True)
            name = "(?:" + "|".join(map(re.escape, names)) + ")"
            match = (re.fullmatch(rf"{name}(?:\s*[=:]\s*|\s+(?:(?:to|of|is)\s+)?)(.+)", piece, re.I) or
                     re.fullmatch(rf"(.+?)\s+{name}", piece, re.I))
            if match:
                updates[key] = parse_value(key, match[1])
                break
        else:
            raise ValueError(f"I couldn't read '{piece}'. Use a named value such as 'width=5 mm'.")
    return updates


def question(step, missing, error=None):
    if step.operation in PLACEMENT_ACTIONS:
        pick = step.args["pick"]
        choices = "\n".join(f"{i}. {name}" for i, name in enumerate(pick["choices"], 1))
        message = f"Which {pick['role']} should I use?\n{choices}"
        return dict(status="needs_input", message=(error + "\n" if error else "") + message,
                    missing_fields=list(missing), suggested_values={})
    if step.operation == "metric_washer":
        message = f"What nominal size is the {step.args['series']} metric flat washer? For example, M8."
        return dict(status="needs_input", message=(error + "\n" if error else "") + message,
                    missing_fields=list(missing), suggested_values={})
    if step.operation == "codex_question":
        return {"status": "needs_input", "message": (error + "\n" if error else "") + step.args["question"],
                "missing_fields": list(missing), "suggested_values": {}}
    if step.operation == "custom_design":
        if "fastener" in step.args:
            from .fasteners import question as fastener_question
            return {"status": "needs_input", "message": (error + "\n\n" if error else "") + fastener_question(step.args["fastener"]),
                    "missing_fields": list(missing), "suggested_values": {}}
        from .custom_design import custom_question
        brief = step.args["brief"]
        details = step.args.get("dimensions")
        message = f"Design request: {brief}"
        if details:
            message += "\nSupplied dimensions: " + ", ".join(f"{k}={v}" for k, v in details.items())
        return {"status": "needs_input", "message": (error + "\n\n" if error else "") + message + "\n\n" + custom_question(step.args),
                "missing_fields": list(missing), "suggested_values": {}, "design_brief": step.args.copy()}
    if step.operation == "choose_design":
        return {"status": "needs_input", "message": (error + "\n\n" if error else "") +
                "What part would you like to make? For example, say 'helical gear', 'bracket' or 'stepped shaft' and include any dimensions you know.",
                "missing_fields": ["design_type"], "suggested_values": {}}
    first = next(iter(missing))
    feature_names = {"add_hole": "hole", "add_boss_feature": "boss", "add_cut_pocket": "pocket",
                     "set_dimension": "dimension change"}
    target = step.args.get("name", feature_names.get(step.operation, step.operation.removeprefix("feature_")))
    suggestions = {k: v for k, v in missing.items() if v not in (None, MISSING)}
    rows = [("Detail", "Suggested value")]
    for key in missing:
        name = label(key)
        if key == "angle_degrees":
            name = "chamfer angle (degrees)"
        elif key == "segments":
            name = "shaft sections (length x diameter in mm, separated by /)"
        elif key not in COUNTS | FLAGS | {"shape", "plane_or_face", "dimension_name"} and "angle" not in key:
            name += " (mm)"
        value = suggestions.get(key)
        if value is None:
            display = "Enter a value"
        elif isinstance(value, bool):
            display = "Yes" if value else "No"
        elif isinstance(value, (float, int)):
            display = f"{value:g}"
        else:
            display = str(value)
        rows.append((name[0].upper() + name[1:], display))

    width = max(len(name) for name, _ in rows)
    lines = [target.capitalize() + " details", ""]
    lines.extend(f"  {name:<{width}}  {value}" for name, value in rows)
    lines.extend(["", f"Enter the {label(first)}, or reply with named values."])
    if suggestions:
        lines.append("Type 'use defaults' to accept the suggested values.")
    if error:
        lines = [error, ""] + lines
    return {"status": "needs_input", "message": "\n".join(lines),
            "missing_fields": list(missing), "suggested_values": suggestions}
