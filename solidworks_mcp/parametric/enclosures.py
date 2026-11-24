"""Parametric Enclosure and Housing CAD Generators."""

from __future__ import annotations

from typing import Any, Dict, Optional
from ..com_adapter.base import BaseSolidWorksAdapter, CADResult


def generate_enclosure_box(
    adapter: BaseSolidWorksAdapter,
    length: float = 120.0,
    width: float = 80.0,
    height: float = 40.0,
    wall_thickness: float = 2.5,
    corner_radius: float = 4.0,
    add_screw_bosses: bool = True,
    boss_diameter: float = 8.0,
    boss_hole_diameter: float = 3.2,  # M3 thread pilot
    new_document: bool = True,
) -> CADResult:
    """Generate an electronic enclosure box with rounded corners, hollow cavity, and screw mounting posts.

    Args:
        adapter: SolidWorks adapter.
        length: Outer length in mm.
        width: Outer width in mm.
        height: Outer height in mm.
        wall_thickness: Wall thickness in mm.
        corner_radius: External corner fillet radius in mm.
        add_screw_bosses: Whether to add 4 internal corner screw posts.
        boss_diameter: Screw post outer diameter in mm.
        boss_hole_diameter: Screw post pilot hole in mm.
        new_document: Whether to create a brand new part document.
    """
    if new_document or not adapter.has_active_document():
        adapter.new_part()

    # Step 1: Base block
    adapter.create_sketch("Top Plane")
    adapter.sketch_rectangle(0.0, 0.0, length / 2.0, width / 2.0, center_based=True)
    adapter.feature_extrude_boss(depth=height)

    # Step 2: Outside vertical corner fillets
    if corner_radius > 0.0:
        adapter.feature_fillet(radius=corner_radius)

    # Step 3: Shell feature to create hollow cavity
    adapter.feature_shell(thickness=wall_thickness)

    # Step 4: Corner screw bosses
    if add_screw_bosses:
        margin_x = (length / 2.0) - wall_thickness - (boss_diameter / 2.0)
        margin_y = (width / 2.0) - wall_thickness - (boss_diameter / 2.0)
        boss_h = height - wall_thickness

        # Boss solid cylinders
        adapter.create_sketch("Top Plane")
        for sx in [1, -1]:
            for sy in [1, -1]:
                adapter.sketch_circle(sx * margin_x, sy * margin_y, boss_diameter / 2.0)
        adapter.feature_extrude_boss(depth=boss_h)

        # Pilot screw holes
        if boss_hole_diameter > 0.0:
            adapter.create_sketch("Top Plane")
            for sx in [1, -1]:
                for sy in [1, -1]:
                    adapter.sketch_circle(sx * margin_x, sy * margin_y, boss_hole_diameter / 2.0)
            adapter.feature_extrude_cut(depth=boss_h - 2.0)

    adapter.rebuild()
    return CADResult(
        success=True,
        message=f"Generated Enclosure Box: {length}x{width}x{height} mm with {wall_thickness}mm wall thickness and 4 corner bosses.",
        data={"length": length, "width": width, "height": height, "wall_thickness": wall_thickness},
    )
