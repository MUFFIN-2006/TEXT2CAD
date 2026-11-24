"""Parametric Rotational CAD Generators (Flanges, Shafts, Bushings)."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple
from ..com_adapter.base import BaseSolidWorksAdapter, CADResult


def generate_flange(
    adapter: BaseSolidWorksAdapter,
    outer_diameter: float = 100.0,
    thickness: float = 12.0,
    center_bore_diameter: float = 40.0,
    bolt_circle_diameter: float = 75.0,
    bolt_hole_count: int = 4,
    bolt_hole_diameter: float = 8.5,
    hub_diameter: Optional[float] = None,
    hub_length: Optional[float] = None,
    new_document: bool = True,
) -> CADResult:
    """Generate a standard circular pipe/shaft mounting flange.

    Args:
        adapter: SolidWorks adapter.
        outer_diameter: Flange OD in mm.
        thickness: Flange plate thickness in mm.
        center_bore_diameter: Center through-bore in mm.
        bolt_circle_diameter: Pitch Circle Diameter (PCD) in mm.
        bolt_hole_count: Number of radial bolt holes.
        bolt_hole_diameter: Diameter of bolt holes in mm.
        hub_diameter: Optional raised collar / hub OD in mm.
        hub_length: Optional raised hub length in mm.
        new_document: Whether to create a brand new part document.
    """
    if new_document or not adapter.has_active_document():
        adapter.new_part()

    # Step 1: Flange disc
    adapter.create_sketch("Front Plane")
    adapter.sketch_circle(0.0, 0.0, outer_diameter / 2.0)
    adapter.feature_extrude_boss(depth=thickness)

    # Step 2: Center bore hole
    if center_bore_diameter > 0.0:
        adapter.create_sketch("Front Plane")
        adapter.sketch_circle(0.0, 0.0, center_bore_diameter / 2.0)
        adapter.feature_extrude_cut(depth=thickness + (hub_length or 0.0), through_all=True)

    # Step 3: Optional raised hub
    if hub_diameter and hub_length and hub_diameter < outer_diameter:
        adapter.create_sketch("Front Plane")
        adapter.sketch_circle(0.0, 0.0, hub_diameter / 2.0)
        adapter.feature_extrude_boss(depth=thickness + hub_length)

    # Step 4: Bolt circle pattern holes
    if bolt_hole_count > 0 and bolt_hole_diameter > 0.0 and bolt_circle_diameter > 0.0:
        adapter.create_sketch("Front Plane")
        pcd_r = bolt_circle_diameter / 2.0
        hole_r = bolt_hole_diameter / 2.0
        angle_step = 2.0 * math.pi / bolt_hole_count

        for i in range(bolt_hole_count):
            ang = i * angle_step
            hx = pcd_r * math.cos(ang)
            hy = pcd_r * math.sin(ang)
            adapter.sketch_circle(hx, hy, hole_r)

        adapter.feature_extrude_cut(depth=thickness, through_all=True)

    adapter.rebuild()
    return CADResult(
        success=True,
        message=f"Generated Flange: Ø{outer_diameter}mm OD, Ø{center_bore_diameter}mm Bore, {thickness}mm Thick with {bolt_hole_count}x Ø{bolt_hole_diameter}mm holes at Ø{bolt_circle_diameter}mm PCD.",
        data={
            "outer_diameter": outer_diameter,
            "center_bore": center_bore_diameter,
            "thickness": thickness,
            "bolt_circle": bolt_circle_diameter,
            "bolt_count": bolt_hole_count,
        },
    )


def generate_stepped_shaft(
    adapter: BaseSolidWorksAdapter,
    segments: List[Tuple[float, float]],
    chamfer_ends: float = 1.0,
    center_bore_dia: float = 0.0,
    new_document: bool = True,
) -> CADResult:
    """Generate a multi-diameter transmission stepped shaft using rotational revolve.

    Args:
        adapter: SolidWorks adapter.
        segments: List of tuples [(length_mm, diameter_mm), ...] from left to right.
        chamfer_ends: Chamfer size in mm for shaft end edges.
        center_bore_dia: Optional hollow center bore diameter in mm.
        new_document: Whether to create a brand new part document.
    """
    if not segments:
        return CADResult(success=False, message="No shaft segments specified.")

    if new_document or not adapter.has_active_document():
        adapter.new_part()
    total_length = sum(s[0] for s in segments)

    # Revolve profile on Front Plane around centerline on X-axis
    adapter.create_sketch("Front Plane")

    # Centerline on axis
    adapter.sketch_line(0.0, 0.0, total_length, 0.0, is_centerline=True)

    # Outer profile
    current_x = 0.0
    for length, dia in segments:
        radius = dia / 2.0
        # Vertical step up/down
        # First segment starts from centerline
        if current_x == 0.0:
            adapter.sketch_line(0.0, center_bore_dia / 2.0, 0.0, radius)
        else:
            prev_radius = segments[segments.index((length, dia)) - 1][1] / 2.0
            adapter.sketch_line(current_x, prev_radius, current_x, radius)

        # Horizontal segment
        adapter.sketch_line(current_x, radius, current_x + length, radius)
        current_x += length

    # End vertical face closing down to centerline
    last_radius = segments[-1][1] / 2.0
    adapter.sketch_line(total_length, last_radius, total_length, center_bore_dia / 2.0)
    if center_bore_dia > 0.0:
        adapter.sketch_line(total_length, center_bore_dia / 2.0, 0.0, center_bore_dia / 2.0)

    # Revolve 360°
    adapter.feature_revolve_boss(angle_degrees=360.0)

    if chamfer_ends > 0.0:
        adapter.feature_chamfer(distance=chamfer_ends, angle_degrees=45.0)

    adapter.rebuild()
    return CADResult(
        success=True,
        message=f"Generated Stepped Shaft: {len(segments)} sections, total length {total_length} mm, max Ø{max(s[1] for s in segments)} mm.",
        data={"total_length": total_length, "segments": segments},
    )


def generate_bushing(
    adapter: BaseSolidWorksAdapter,
    outer_diameter: float = 30.0,
    inner_diameter: float = 20.0,
    length: float = 35.0,
    flange_diameter: float = 0.0,
    flange_thickness: float = 0.0,
    chamfer: float = 1.0,
    new_document: bool = True,
) -> CADResult:
    """Generate a precision cylindrical sleeve bushing / bearing or flanged bushing."""
    if outer_diameter <= inner_diameter:
        return CADResult(success=False, message="outer_diameter must be greater than inner_diameter.")
    if length <= 0:
        return CADResult(success=False, message="length must be positive.")

    if new_document or not adapter.has_active_document():
        adapter.new_part()

    # Step 1: Main outer cylinder
    adapter.create_sketch("Front Plane")
    adapter.sketch_circle(0.0, 0.0, outer_diameter / 2.0)
    adapter.feature_extrude_boss(depth=length)

    # Step 2: Optional flange collar
    if flange_diameter > outer_diameter and flange_thickness > 0.0:
        adapter.create_sketch("Front Plane")
        adapter.sketch_circle(0.0, 0.0, flange_diameter / 2.0)
        adapter.feature_extrude_boss(depth=flange_thickness)

    # Step 3: Through bore
    total_depth = max(length, flange_thickness)
    adapter.create_sketch("Front Plane")
    adapter.sketch_circle(0.0, 0.0, inner_diameter / 2.0)
    adapter.feature_extrude_cut(depth=total_depth + 5.0, through_all=True)

    # Step 4: Chamfer
    if chamfer > 0.0:
        adapter.feature_chamfer(distance=chamfer, angle_degrees=45.0)

    adapter.rebuild()
    kind = "Flanged Bushing" if flange_diameter > outer_diameter else "Sleeve Bushing"
    return CADResult(
        success=True,
        message=f"Generated {kind}: OD={outer_diameter}mm, ID={inner_diameter}mm, Length={length}mm.",
        data={"outer_diameter": outer_diameter, "inner_diameter": inner_diameter, "length": length,
              "flange_diameter": flange_diameter, "flange_thickness": flange_thickness},
    )


def generate_dowel_pin(
    adapter: BaseSolidWorksAdapter,
    diameter: float = 10.0,
    length: float = 40.0,
    chamfer: float = 1.0,
    new_document: bool = True,
) -> CADResult:
    """Generate a precision dowel pin or locating pin with chamfered ends."""
    if diameter <= 0 or length <= 0:
        return CADResult(success=False, message="Diameter and length must be positive.")

    if new_document or not adapter.has_active_document():
        adapter.new_part()

    adapter.create_sketch("Front Plane")
    adapter.sketch_circle(0.0, 0.0, diameter / 2.0)
    adapter.feature_extrude_boss(depth=length)

    if chamfer > 0.0:
        adapter.feature_chamfer(distance=chamfer, angle_degrees=45.0)

    adapter.rebuild()
    return CADResult(
        success=True,
        message=f"Generated Dowel Pin: Ø{diameter}mm x {length}mm length.",
        data={"diameter": diameter, "length": length, "chamfer": chamfer},
    )
