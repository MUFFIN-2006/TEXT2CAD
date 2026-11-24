"""Read common workshop wording for a single external helical gear."""

import re
from .requirements import parse_value


_HEAD = re.compile(r"^(?:please\s+)?(?:(make|create|build|design|model)\s+)?(?:me\s+)?"
                   r"(?:an?\s+)?(?:(new|another|separate)\s+)?helical[\s_-]+gears?\b", re.I)
_LABELS = {
    "outer_diameter": r"(?:outer|outside|external)(?:\s+(?:diameter|dia))?|o\.?d\.?",
    "bore_diameter": r"(?:inner|inter|inside|internal|bore)(?:\s+(?:diameter|dia))?|i\.?d\.?",
    "face_width": r"(?:face\s+)?width|thickness|thick|wide",
    "num_teeth": r"(?:number\s+of\s+)?teeth|tooth\s+count",
    "helix_angle": r"helix(?:\s+angle)?",
    "pressure_angle": r"pressure\s+angle",
}
_NUMBER = r"(?P<value>[+-]?(?:\d+(?:\.\d+)?|\.\d+))"
_SEPARATOR = re.compile(r"^(?:[\s,;]+|\b(?:having|with|and|of|a|an)\b)+", re.I)


def gear_changes(prompt):
    """Read a compound edit without treating part of an unrecognized edit as valid."""
    head = re.match(r"^(?:please\s+)?(?:change|set|update)\s+(?:the\s+)?", prompt.strip(), re.I)
    if not head:
        return None
    changes = {}
    for piece in re.split(r"\s*(?:&|,|\band\b)\s*", prompt.strip()[head.end():], flags=re.I):
        for key in ("num_teeth", "outer_diameter"):
            name = _LABELS[key]
            match = re.fullmatch(rf"(?:the\s+)?(?:{name})\s*(?:to\s+|=\s*)(.+)", piece, re.I)
            if match:
                if key in changes:
                    raise ValueError(f"Give {key.replace('_', ' ')} once.")
                changes[key] = parse_value(key, match[1])
                break
        else:
            return None
    return changes


def helical_request(prompt):
    """Return (explicit creation, parameters), or None for another kind of command."""
    prompt = prompt.strip().rstrip(".!?").lower()
    head = _HEAD.match(prompt)
    if not head:
        return None
    rest = prompt[head.end():]
    args = {}
    while rest:
        rest = _SEPARATOR.sub("", rest)
        if not rest:
            break
        for key, label in _LABELS.items():
            unit = (r"(?:\s*(?:degrees?|deg|°))?" if key.endswith("angle") else
                    "" if key == "num_teeth" else r"(?:\s*mm)?")
            suffix = r"(?:\s*dia(?:meter)?\b)?" if key.endswith("diameter") else ""
            before = rf"(?P<label>{label})(?!\w)\s*(?:(?:of|is)\s+|[=:]\s*)?{_NUMBER}{unit}{suffix}"
            after = rf"{_NUMBER}{unit}\s*(?P<label>{label})(?!\w)"
            match = re.match(before, rest) or re.match(after, rest)
            if not match:
                continue
            if key in args:
                raise ValueError(f"Specify {key.replace('_', ' ')} only once.")
            value = float(match["value"])
            if key == "num_teeth" and not value.is_integer():
                raise ValueError("Tooth count must be a whole number.")
            args[key] = int(value) if key == "num_teeth" else value
            rest = rest[match.end():]
            break
        else:
            raise ValueError(f"Unrecognized helical gear detail '{rest}'. Try '15 mm OD, 10 mm bore, 20 teeth'.")
    return bool(head[2]), args
