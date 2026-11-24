"""Parametric Thermal Heat Sink CAD Generator."""

from __future__ import annotations

from typing import Any, Dict
from ..com_adapter.base import BaseSolidWorksAdapter, CADResult


def generate_heat_sink(
    adapter: BaseSolidWorksAdapter,
    base_length: float = 100.0,
    base_width: float = 60.0,
    base_thickness: float = 6.0,
    fin_count: int = 8,
    fin_height: float = 25.0,
    fin_thickness: float = 2.0,
    new_document: bool = True,
) -> CADResult:
    """Generate an extruded thermal heat sink with custom base plate and fin array.

    Args:
        adapter: SolidWorks adapter.
        base_length: Length of heat sink base in mm (direction of fins).
        base_width: Width of heat sink base in mm.
        base_thickness: Base plate thickness in mm.
        fin_count: Number of cooling fins.
        fin_height: Height of fins above base plate in mm.
        fin_thickness: Thickness of each fin in mm.
        new_document: Whether to create a brand new part document.
    """
    if fin_count < 2:
        return CADResult(success=False, message="fin_count must be at least 2.")

    if new_document or not adapter.has_active_document():
        adapter.new_part()

    # Step 1: Base plate
    adapter.create_sketch("Top Plane")
    adapter.sketch_rectangle(0.0, 0.0, base_length / 2.0, base_width / 2.0, center_based=True)
    adapter.feature_extrude_boss(depth=base_thickness)

    # Step 2: Extrude fin array
    # Pitch between fins
    pitch = (base_width - fin_thickness) / (fin_count - 1)
    start_y = -(base_width / 2.0) + (fin_thickness / 2.0)

    adapter.create_sketch("Top Plane")
    for i in range(fin_count):
        y_pos = start_y + i * pitch
        adapter.sketch_rectangle(0.0, y_pos, base_length / 2.0, y_pos + (fin_thickness / 2.0), center_based=False)
        # Draw full width fin
        adapter.sketch_rectangle(-base_length / 2.0, y_pos - (fin_thickness / 2.0),
                                 base_length / 2.0, y_pos + (fin_thickness / 2.0), center_based=False)

    adapter.feature_extrude_boss(depth=base_thickness + fin_height)
    adapter.set_material("6061-T6 (SS)")

    adapter.rebuild()
    return CADResult(
        success=True,
        message=f"Generated Heat Sink: {base_length}x{base_width}mm base ({base_thickness}mm thick) with {fin_count} cooling fins ({fin_height}mm high, {fin_thickness}mm thick).",
        data={"base_size": [base_length, base_width, base_thickness], "fins": fin_count, "fin_height": fin_height},
    )
