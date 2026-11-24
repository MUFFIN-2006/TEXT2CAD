"""Recognize the generator's tooth outline, including in parts saved by older versions."""

from dataclasses import dataclass
import math

from .gears import tooth_outline
from ..com_adapter.base import CADResult


UNRECOGNIZED = "Open a spur or helical gear made by this agent to edit its tooth count or outer diameter."


def edge_key(start, end):
    return tuple(sorted((tuple(round(v, 6) for v in point) for point in (start, end))))


@dataclass
class GearEdit:
    old_edges: set
    points: list
    teeth: int
    diameter: float
    root_radius: float
    twist_ratio: float

    def result(self):
        return CADResult(success=True, message=f"Updated the active gear to {self.teeth} teeth and {self.diameter:g} mm outer diameter.",
                         data={"teeth": self.teeth, "outer_diameter": self.diameter})


def plan_resize(lines, helical, num_teeth, outer_diameter):
    """Recover the pitch and pressure angle and verify every original tooth edge before editing."""
    if len(lines) < 6 * 16:
        return None
    vertices = {point for edge in lines for point in edge}
    tip = max(math.hypot(*p) for p in vertices)
    tips = [p for p in vertices if math.isclose(math.hypot(*p), tip, abs_tol=1e-7)]
    # The generator puts three vertices on each tip and a root vertex midway between teeth.
    teeth, remainder = divmod(len(tips), 3)
    if remainder or not 6 <= teeth <= 1000:
        return None
    sector = math.pi / teeth
    roots = [math.hypot(x, y) for x, y in vertices if abs(math.atan2(y, x) - sector) < 1e-8]
    if not roots:
        return None
    normal_module = (tip - max(roots)) / 2.25
    pitch = tip - normal_module
    if not 0 < normal_module < pitch:
        return None
    cosine = teeth * normal_module / (2 * pitch)
    if not 0 < cosine <= 1.0000001 or (not helical and abs(cosine - 1) > 1e-7):
        return None
    # Invert the involute at the measured tip to recover the transverse pressure angle.
    tip_half_angle = max((math.atan2(y, x) for x, y in tips if x > 0 and abs(math.atan2(y, x)) < sector), default=0)
    low, high = 0.0, math.pi / 2
    for _ in range(55):
        angle = (low + high) / 2
        at_tip = math.acos(pitch * math.cos(angle) / tip)
        half_angle = sector / 2 + math.tan(angle) - angle - (math.tan(at_tip) - at_tip)
        if half_angle > tip_half_angle:
            low = angle
        else:
            high = angle
    pressure = math.degrees((low + high) / 2)
    try:
        old = tooth_outline(teeth, 2 * pitch / teeth, pressure, normal_module=normal_module)
    except ValueError:
        return None
    edges = {edge_key(old[i - 1], end) for i, end in enumerate(old)}
    actual = {edge_key(*edge) for edge in lines}
    if not edges.issubset(actual):
        return None

    count = teeth if num_teeth is None else num_teeth
    # A count-only edit retains module. A diameter-only edit retains tooth count.
    module = 2 * pitch / teeth if outer_diameter is None else outer_diameter / (count + 2 * cosine)
    new_pitch = count * module / 2
    normal = module * cosine
    root = new_pitch - 1.25 * normal
    if any(math.hypot(*point) >= root for edge in actual - edges for point in edge):
        raise ValueError("The resized tooth roots would intersect another contour in the gear sketch.")
    points = tooth_outline(count, module, pressure, normal_module=normal)
    return GearEdit(edges, points, count, 2 * (new_pitch + normal), root, pitch / new_pitch)
