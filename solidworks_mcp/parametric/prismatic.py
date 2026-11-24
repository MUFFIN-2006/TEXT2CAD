"""Parametric Prismatic CAD Generators (Plates, Brackets, Blocks)."""

from __future__ import annotations

from typing import Any, Dict, Optional
from ..com_adapter.base import BaseSolidWorksAdapter, CADResult


def generate_mounting_bracket(
    adapter: BaseSolidWorksAdapter,
    length: float = 100.0,
    width: float = 60.0,
    thickness: float = 10.0,
    corner_fillet: float = 5.0,
    hole_diameter: float = 6.5,
    hole_margin: float = 12.0,
    new_document: bool = True,
) -> CADResult:
    """Generate a precision mounting bracket with 4 corner mounting holes and edge fillets.

    Args:
        adapter: SolidWorks adapter.
        length: Length in mm (X axis).
        width: Width in mm (Y axis).
        thickness: Thickness in mm (Z extrusion).
        corner_fillet: Fillet radius in mm.
        hole_diameter: Mounting hole diameter in mm (M6 clearance = 6.5mm).
        hole_margin: Distance from outer edge to hole center in mm.
        new_document: Whether to create a brand new part document.
    """
    if new_document or not adapter.has_active_document():
        adapter.new_part()

    # Step 1: Base rectangle
    adapter.create_sketch("Front Plane")
    adapter.sketch_rectangle(0.0, 0.0, length / 2.0, width / 2.0, center_based=True)
    adapter.feature_extrude_boss(depth=thickness)

    # Step 2: 4 corner mounting holes
    if hole_diameter > 0.0 and hole_margin > 0.0:
        adapter.create_sketch("Front Plane")
        hx = (length / 2.0) - hole_margin
        hy = (width / 2.0) - hole_margin
        r = hole_diameter / 2.0

        adapter.sketch_circle(hx, hy, r)
        adapter.sketch_circle(-hx, hy, r)
        adapter.sketch_circle(-hx, -hy, r)
        adapter.sketch_circle(hx, -hy, r)

        adapter.feature_extrude_cut(depth=thickness, through_all=True)

    # Step 3: Corner fillets
    if corner_fillet > 0.0:
        adapter.feature_fillet(radius=corner_fillet)

    adapter.rebuild()
    return CADResult(
        success=True,
        message=f"Generated Mounting Bracket ({length}x{width}x{thickness} mm) with 4x Ø{hole_diameter}mm holes and {corner_fillet}mm fillets.",
        data={"length": length, "width": width, "thickness": thickness, "holes": 4},
    )


def generate_l_bracket(
    adapter: BaseSolidWorksAdapter,
    leg1_length: float = 60.0,
    leg2_length: float = 60.0,
    width: float = 40.0,
    thickness: float = 6.0,
    hole_diameter: float = 6.5,
    new_document: bool = True,
) -> CADResult:
    """Generate an L-shaped structural angle bracket.

    Args:
        adapter: SolidWorks adapter.
        leg1_length: Length of base leg in mm.
        leg2_length: Length of vertical leg in mm.
        width: Width of the bracket in mm.
        thickness: Material thickness in mm.
        hole_diameter: Mounting hole diameter in mm.
        new_document: Whether to create a brand new part document.
    """
    if new_document or not adapter.has_active_document():
        adapter.new_part()

    # Sketch L profile on Right Plane (YZ plane)
    adapter.create_sketch("Right Plane")
    # Draw outer and inner L profile
    adapter.sketch_line(0.0, 0.0, leg1_length, 0.0)
    adapter.sketch_line(leg1_length, 0.0, leg1_length, thickness)
    adapter.sketch_line(leg1_length, thickness, thickness, thickness)
    adapter.sketch_line(thickness, thickness, thickness, leg2_length)
    adapter.sketch_line(thickness, leg2_length, 0.0, leg2_length)
    adapter.sketch_line(0.0, leg2_length, 0.0, 0.0)

    # Extrude along width (mid-plane for symmetry)
    adapter.feature_extrude_boss(depth=width, mid_plane=True)

    # Inner fillet for stress relief
    if thickness > 2.0:
        adapter.feature_fillet(radius=thickness / 2.0)

    adapter.rebuild()
    return CADResult(
        success=True,
        message=f"Generated L-Bracket ({leg1_length}x{leg2_length}x{width} mm, {thickness}mm thickness).",
        data={"leg1": leg1_length, "leg2": leg2_length, "width": width, "thickness": thickness},
    )


def generate_structural_tube(
    adapter: BaseSolidWorksAdapter,
    outer_size: float = 50.0,
    wall_thickness: float = 3.0,
    length: float = 200.0,
    shape: str = "square",
    new_document: bool = True,
) -> CADResult:
    """Generate a hollow structural profile tube (round tube / pipe or square box section)."""
    if outer_size <= 2 * wall_thickness:
        return CADResult(success=False, message="outer_size must be greater than 2 * wall_thickness.")
    if length <= 0:
        return CADResult(success=False, message="length must be positive.")

    if new_document or not adapter.has_active_document():
        adapter.new_part()

    is_round = "round" in shape.lower() or "pipe" in shape.lower() or "circle" in shape.lower()
    adapter.create_sketch("Front Plane")
    if is_round:
        adapter.sketch_circle(0.0, 0.0, outer_size / 2.0)
    else:
        adapter.sketch_rectangle(0.0, 0.0, outer_size / 2.0, outer_size / 2.0, center_based=True)
    adapter.feature_extrude_boss(depth=length)

    # Cut hollow interior
    adapter.create_sketch("Front Plane")
    inner_size = outer_size - 2 * wall_thickness
    if is_round:
        adapter.sketch_circle(0.0, 0.0, inner_size / 2.0)
    else:
        adapter.sketch_rectangle(0.0, 0.0, inner_size / 2.0, inner_size / 2.0, center_based=True)
    adapter.feature_extrude_cut(depth=length, through_all=True)

    adapter.rebuild()
    kind = "Round Structural Tube" if is_round else "Square Hollow Structural Section (SHS)"
    return CADResult(
        success=True,
        message=f"Generated {kind}: Size={outer_size}mm, Wall={wall_thickness}mm, Length={length}mm.",
        data={"outer_size": outer_size, "wall_thickness": wall_thickness, "length": length, "shape": shape},
    )
