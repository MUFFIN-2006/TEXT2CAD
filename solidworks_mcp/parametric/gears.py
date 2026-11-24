"""Spur gears with a closed, sampled involute tooth outline."""

from __future__ import annotations

import math
from typing import Optional

from ..com_adapter.base import BaseSolidWorksAdapter, CADResult


def tooth_outline(teeth, module, pressure_angle, *, normal_module=None):
    """Return one CCW loop in mm. Each flank is sampled from the base-circle involute."""
    pitch = module * teeth / 2
    tooth_height_module = normal_module if normal_module is not None else module
    root, tip = pitch - 1.25 * tooth_height_module, pitch + tooth_height_module
    alpha = math.radians(pressure_angle)
    base = pitch * math.cos(alpha)
    start = max(root, base)
    half_angle = math.pi / (2 * teeth) + math.tan(alpha) - alpha
    flank = []
    for i in range(7):
        radius = start + (tip - start) * i / 6
        t = math.sqrt(max(0, (radius / base) ** 2 - 1))
        flank.append((radius, half_angle - (t - math.atan(t))))
    if flank[-1][1] <= 0 or flank[0][1] >= math.pi / teeth:
        raise ValueError("These dimensions produce overlapping tooth flanks.")
    if root < start - 1e-9:
        flank.insert(0, (root, flank[0][1]))

    sector = [(r, -a) for r, a in flank] + [(tip, 0)] + list(reversed(flank))
    sector.append((root, math.pi / teeth))
    points = []
    for i in range(teeth):
        centre = math.tau * i / teeth
        points.extend((r * math.cos(centre + a), r * math.sin(centre + a)) for r, a in sector)
    return points


def _require(result, stage):
    if not result.success:
        raise ValueError(f"{stage}: {result.error or result.message}")


def generate_helical_gear(adapter, outer_diameter, bore_diameter, num_teeth=20,
                          face_width=None, helix_angle=20.0, pressure_angle=20.0,
                          new_document: bool = True):
    """Build an external, normal-system helical gear; lengths in mm, angles in degrees."""
    try:
        width = outer_diameter / 3 if face_width is None else face_width
        if not all(math.isfinite(n) for n in (outer_diameter, bore_diameter, width, helix_angle, pressure_angle)):
            raise ValueError("Gear dimensions must be finite.")
        if min(outer_diameter, width) <= 0 or bore_diameter < 0:
            raise ValueError("Specify positive OD and width, and a nonnegative bore.")
        if type(num_teeth) is not int or not 6 <= num_teeth <= 1000:
            raise ValueError("Specify a whole tooth count from 6 to 1000.")
        if not 0 < abs(helix_angle) < 90 or not 0 < pressure_angle < 90:
            raise ValueError("Helix angle magnitude and pressure angle must be between 0 and 90 degrees.")
        beta = math.radians(helix_angle)
        normal = outer_diameter / (num_teeth / math.cos(beta) + 2)
        transverse = normal / math.cos(beta)
        pitch = num_teeth * transverse
        root = pitch - 2.5 * normal
        if bore_diameter >= root:
            raise ValueError(f"The bore must be smaller than the tooth root diameter ({root:.3f} mm).")
        twist = 2 * width * math.tan(beta) / pitch
        alpha_t = math.degrees(math.atan(math.tan(math.radians(pressure_angle)) / math.cos(beta)))
        profile = tooth_outline(num_teeth, transverse, alpha_t, normal_module=normal)
        if new_document or not adapter.has_active_document():
            _require(adapter.new_part(), "Create helical gear document")
        _require(adapter.create_sketch("Front Plane"), "Start tooth sketch")
        with adapter.sketch_batch():
            _require(adapter.sketch_closed_polyline(profile), "Sketch helical gear profile")
        _require(adapter.sweep_twisted_profile(width, twist), "Sweep helical teeth")
        if bore_diameter:
            _require(adapter.create_sketch("Front Plane"), "Start bore sketch")
            _require(adapter.sketch_circle(0, 0, bore_diameter / 2), "Sketch bore")
            _require(adapter.feature_extrude_cut(depth=width, through_all=True, flip_dir=True), "Cut center bore")
        _require(adapter.rebuild(), "Rebuild helical gear")
    except (ValueError, RuntimeError) as exc:
        return CADResult(success=False, message=str(exc))
    return CADResult(success=True,
                     message=f"Created a {num_teeth}-tooth helical gear with {outer_diameter:g} mm OD, "
                             f"{bore_diameter:g} mm bore, {width:g} mm face width and {helix_angle:g} degree helix.",
                     data=dict(teeth=num_teeth, outer_diameter=outer_diameter, bore_diameter=bore_diameter,
                               face_width=width, helix_angle=helix_angle, pressure_angle=pressure_angle,
                               normal_module=normal, pitch_diameter=pitch, twist_degrees=math.degrees(twist)))


def _bore(adapter, radius, width, depth):
    if radius == 0:
        return
    if width == 0 or depth == 0:
        _require(adapter.sketch_circle(0, 0, radius), "Sketch bore")
        return
    # One continuous inner contour. The arc ends meet the sides of the keyway.
    x = width / 2
    y = math.sqrt(radius * radius - x * x)
    top = radius + depth
    _require(adapter.sketch_arc((-x, y), (x, y), (0, -radius)), "Sketch bore arc")
    for start, end in [((x, y), (x, top)), ((x, top), (-x, top)), ((-x, top), (-x, y))]:
        _require(adapter.sketch_line(*start, *end), "Sketch keyway")


def generate_spur_gear(
    adapter: BaseSolidWorksAdapter,
    num_teeth: int = 20,
    module: float = 2.5,
    pressure_angle: float = 20.0,
    face_width: float = 20.0,
    bore_diameter: float = 20.0,
    hub_diameter: Optional[float] = 35.0,
    hub_length: Optional[float] = 10.0,
    keyway_width: float = 6.0,
    keyway_depth: float = 2.8,
    new_document: bool = True,
) -> CADResult:
    """Extrude all teeth together. The optional hub shares the same keyed opening."""
    try:
        if type(num_teeth) is not int or not 6 <= num_teeth <= 1000:
            raise ValueError("Specify a whole tooth count from 6 to 1000.")
        sizes = (module, face_width, bore_diameter, keyway_width, keyway_depth,
                 hub_diameter or 0, hub_length or 0)
        if not all(math.isfinite(v) and v >= 0 for v in sizes) or min(module, face_width) <= 0:
            raise ValueError("Module and face width must be positive; all sizes must be finite and nonnegative.")
        if not 0 < pressure_angle < 90:
            raise ValueError("Specify a pressure angle between 0 and 90 degrees.")
        pitch = module * num_teeth
        root = pitch - 2.5 * module
        tip = pitch + 2 * module
        hub = bool(hub_diameter and hub_length and hub_diameter < root)
        bore = bore_diameter / 2
        clearance = bore
        if bore and keyway_width and keyway_depth:
            if keyway_width >= bore_diameter:
                raise ValueError("Keyway width must be smaller than the bore diameter.")
            clearance = math.hypot(keyway_width / 2, bore + keyway_depth)
        if clearance >= (hub_diameter if hub else root) / 2:
            raise ValueError("Bore or keyway reaches the tooth roots or hub wall. Use a smaller bore/keyway.")
        points = tooth_outline(num_teeth, module, pressure_angle)

        if new_document or not adapter.has_active_document():
            _require(adapter.new_part(), "Create gear document")
        _require(adapter.create_sketch("Front Plane"), "Start tooth sketch")
        with adapter.sketch_batch():
            _require(adapter.sketch_closed_polyline(points), "Sketch tooth outline")
            _bore(adapter, bore, keyway_width, keyway_depth)
        _require(adapter.feature_extrude_boss(depth=face_width), "Extrude teeth")
        if hub:
            _require(adapter.create_sketch("Front Plane"), "Start hub sketch")
            with adapter.sketch_batch():
                _require(adapter.sketch_circle(0, 0, hub_diameter / 2), "Sketch hub")
                _bore(adapter, bore, keyway_width, keyway_depth)
            _require(adapter.feature_extrude_boss(depth=face_width + hub_length), "Extrude hub")
        _require(adapter.rebuild(), "Rebuild gear")
        material = adapter.set_material("Cast Carbon Steel")
    except (ValueError, RuntimeError) as exc:
        return CADResult(success=False, message=str(exc))

    return CADResult(
        success=True,
        message=f"Generated Spur Gear with {num_teeth} teeth, {module:g} mm module and {pitch:g} mm pitch diameter.",
        data={"teeth": num_teeth, "module": module, "pressure_angle": pressure_angle,
              "pitch_diameter": pitch, "tip_diameter": tip, "root_diameter": root,
              "face_width": face_width, "bore_diameter": bore_diameter,
              "material_assigned": material.success},
    )
