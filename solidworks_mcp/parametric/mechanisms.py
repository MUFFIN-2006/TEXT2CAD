"""Parametric Mechanical Links and Mechanisms (Connecting Rod, Crank Arm)."""

from __future__ import annotations

from typing import Any, Dict
from ..com_adapter.base import BaseSolidWorksAdapter, CADResult


def generate_connecting_rod(
    adapter: BaseSolidWorksAdapter,
    center_distance: float = 120.0,
    big_end_bore: float = 32.0,
    big_end_od: float = 48.0,
    small_end_bore: float = 16.0,
    small_end_od: float = 28.0,
    beam_width: float = 16.0,
    beam_thickness: float = 12.0,
    new_document: bool = True,
) -> CADResult:
    """Generate a precision mechanical connecting rod for slider-crank / IC engine mechanisms.

    Args:
        adapter: SolidWorks adapter.
        center_distance: Distance between big-end and small-end centers in mm.
        big_end_bore: Crankpin journal bearing bore in mm.
        big_end_od: Outer diameter of big end boss in mm.
        small_end_bore: Wristpin / gudgeon pin bore in mm.
        small_end_od: Outer diameter of small end boss in mm.
        beam_width: Width of intermediate connecting shank/beam in mm.
        beam_thickness: Axial thickness of connecting rod in mm.
        new_document: Whether to create a brand new part document.
    """
    if new_document or not adapter.has_active_document():
        adapter.new_part()

    # Step 1: Big end boss cylinder
    adapter.create_sketch("Front Plane")
    adapter.sketch_circle(0.0, 0.0, big_end_od / 2.0)
    adapter.feature_extrude_boss(depth=beam_thickness, mid_plane=True)

    # Step 2: Small end boss cylinder
    adapter.create_sketch("Front Plane")
    adapter.sketch_circle(center_distance, 0.0, small_end_od / 2.0)
    adapter.feature_extrude_boss(depth=beam_thickness, mid_plane=True)

    # Step 3: Connecting shank beam (merges automatically)
    adapter.create_sketch("Front Plane")
    half_bw = beam_width / 2.0
    adapter.sketch_line(0.0, half_bw, center_distance, half_bw)
    adapter.sketch_line(center_distance, half_bw, center_distance, -half_bw)
    adapter.sketch_line(center_distance, -half_bw, 0.0, -half_bw)
    adapter.sketch_line(0.0, -half_bw, 0.0, half_bw)
    adapter.feature_extrude_boss(depth=beam_thickness, mid_plane=True)

    # Step 4: Bore holes for crankpin and gudgeon pin
    adapter.create_sketch("Front Plane")
    adapter.sketch_circle(0.0, 0.0, big_end_bore / 2.0)
    adapter.sketch_circle(center_distance, 0.0, small_end_bore / 2.0)
    adapter.feature_extrude_cut(depth=beam_thickness, through_all=True)

    # Step 5: Transition stress relief fillets
    adapter.feature_fillet(radius=2.0)

    adapter.set_material("AISI 4340 Steel, normalized")
    adapter.rebuild()

    return CADResult(
        success=True,
        message=f"Generated Connecting Rod: {center_distance}mm Center-to-Center, Big End Ø{big_end_bore}/{big_end_od}mm, Small End Ø{small_end_bore}/{small_end_od}mm.",
        data={
            "center_distance": center_distance,
            "big_end_bore": big_end_bore,
            "small_end_bore": small_end_bore,
            "thickness": beam_thickness,
        },
    )


def generate_crank_arm(
    adapter: BaseSolidWorksAdapter,
    crank_radius: float = 40.0,
    shaft_bore_dia: float = 25.0,
    shaft_boss_od: float = 42.0,
    pin_bore_dia: float = 18.0,
    pin_boss_od: float = 30.0,
    arm_thickness: float = 14.0,
    new_document: bool = True,
) -> CADResult:
    """Generate an engine / mechanism crank arm link."""
    if new_document or not adapter.has_active_document():
        adapter.new_part()

    # Step 1: Shaft boss cylinder
    adapter.create_sketch("Front Plane")
    adapter.sketch_circle(0.0, 0.0, shaft_boss_od / 2.0)
    adapter.feature_extrude_boss(depth=arm_thickness, mid_plane=True)

    # Step 2: Crankpin boss cylinder
    adapter.create_sketch("Front Plane")
    adapter.sketch_circle(crank_radius, 0.0, pin_boss_od / 2.0)
    adapter.feature_extrude_boss(depth=arm_thickness, mid_plane=True)

    # Step 3: Connecting arm
    adapter.create_sketch("Front Plane")
    bw = 18.0
    adapter.sketch_line(0.0, bw / 2.0, crank_radius, bw / 2.0)
    adapter.sketch_line(crank_radius, bw / 2.0, crank_radius, -bw / 2.0)
    adapter.sketch_line(crank_radius, -bw / 2.0, 0.0, -bw / 2.0)
    adapter.sketch_line(0.0, -bw / 2.0, 0.0, bw / 2.0)
    adapter.feature_extrude_boss(depth=arm_thickness, mid_plane=True)

    # Step 4: Bores
    adapter.create_sketch("Front Plane")
    adapter.sketch_circle(0.0, 0.0, shaft_bore_dia / 2.0)
    adapter.sketch_circle(crank_radius, 0.0, pin_bore_dia / 2.0)
    adapter.feature_extrude_cut(depth=arm_thickness, through_all=True)

    # Step 5: Fillets
    adapter.feature_fillet(radius=2.0)
    adapter.set_material("Cast Carbon Steel")
    adapter.rebuild()

    return CADResult(
        success=True,
        message=f"Generated Crank Arm: {crank_radius}mm Crank Radius, Shaft Bore Ø{shaft_bore_dia}mm, Pin Bore Ø{pin_bore_dia}mm.",
        data={"crank_radius": crank_radius, "stroke": 2.0 * crank_radius},
    )
