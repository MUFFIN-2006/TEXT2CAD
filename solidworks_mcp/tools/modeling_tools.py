"""SolidWorks Parametric Feature and Modeling Tools."""

from __future__ import annotations

from typing import Any, Dict, Optional
from fastmcp import FastMCP
from ..com_adapter.base import BaseSolidWorksAdapter


def register_modeling_tools(mcp: FastMCP, adapter: BaseSolidWorksAdapter) -> None:
    """Register parametric 3D modeling and feature tools."""

    @mcp.tool(
        name="solidworks_connect",
        description="Connects to a running SolidWorks instance or launches a new one on Windows.",
    )
    def solidworks_connect() -> Dict[str, Any]:
        res = adapter.connect()
        return {"status": "success" if res.success else "error", "message": res.message, "data": res.data}

    @mcp.tool(
        name="new_part",
        description="Creates a separate brand new empty SolidWorks Part document (.SLDPRT). Call only when the user explicitly asks for a new part/document; do not call for edits or additions to the active part.",
    )
    def new_part_tool() -> Dict[str, Any]:
        res = adapter.new_part()
        return {"status": "success" if res.success else "error", "message": res.message, "data": res.data}

    @mcp.tool(
        name="set_dimension",
        description=(
            "Changes an existing named dimension in the active part and rebuilds it. "
            "Use this to edit the current model; it does not create a new document. "
            "Dimension names commonly include a name and feature suffix, such as D1@Sketch1."
        ),
    )
    def set_dimension_tool(dimension_name: str, value_mm: float) -> Dict[str, Any]:
        res = adapter.set_dimension(dimension_name=dimension_name, value_mm=value_mm)
        return {"status": "success" if res.success else "error", "message": res.message, "data": res.data}

    @mcp.tool(
        name="add_hole_to_part",
        description=(
            "Adds a circular cut hole to the currently active part document, preserving and modifying that part. "
            "Use for follow-up requests such as adding holes; do not call new_part first."
        ),
    )
    def add_hole_to_part_tool(
        diameter: float,
        xc: float = 0.0,
        yc: float = 0.0,
        depth: float = 0.0,
        through_all: bool = True,
        plane_or_face: str = "Front Plane",
    ) -> Dict[str, Any]:
        res = adapter.add_hole(
            diameter=diameter, xc=xc, yc=yc, depth=depth,
            through_all=through_all, plane_or_face=plane_or_face,
        )
        return {"status": "success" if res.success else "error", "message": res.message, "data": res.data}

    @mcp.tool(
        name="add_boss_to_part",
        description=(
            "Adds an extruded circular or rectangular boss to the currently active part, modifying that same document. "
            "Use for follow-up additions; do not call new_part first. Dimensions and depth are in mm."
        ),
    )
    def add_boss_to_part_tool(
        shape: str = "circle",
        dim1: float = 20.0,
        dim2: float = 20.0,
        xc: float = 0.0,
        yc: float = 0.0,
        depth: float = 10.0,
        plane_or_face: str = "Front Plane",
    ) -> Dict[str, Any]:
        res = adapter.add_boss_feature(
            shape=shape, dim1=dim1, dim2=dim2, xc=xc, yc=yc,
            depth=depth, plane_or_face=plane_or_face,
        )
        return {"status": "success" if res.success else "error", "message": res.message, "data": res.data}

    @mcp.tool(
        name="add_pocket_to_part",
        description=(
            "Cuts a circular or rectangular blind pocket into the currently active part, modifying that same document. "
            "Use for follow-up cut requests; do not call new_part first. Dimensions and depth are in mm."
        ),
    )
    def add_pocket_to_part_tool(
        shape: str = "rectangle",
        width: float = 20.0,
        height: float = 20.0,
        depth: float = 5.0,
        xc: float = 0.0,
        yc: float = 0.0,
        plane_or_face: str = "Front Plane",
    ) -> Dict[str, Any]:
        res = adapter.add_cut_pocket(
            shape=shape, width=width, height=height, depth=depth,
            xc=xc, yc=yc, plane_or_face=plane_or_face,
        )
        return {"status": "success" if res.success else "error", "message": res.message, "data": res.data}

    @mcp.tool(
        name="new_assembly",
        description="Creates a new SolidWorks Assembly document (.SLDASM).",
    )
    def new_assembly_tool() -> Dict[str, Any]:
        res = adapter.new_assembly()
        return {"status": "success" if res.success else "error", "message": res.message, "data": res.data}

    @mcp.tool(name="insert_assembly_component")
    def insert_assembly_component(file_path: str, x: float, y: float, z: float) -> Dict[str, Any]:
        """Insert a saved part or subassembly at the given origin (mm), aligned to assembly axes. Returns its instance name."""
        res = adapter.connect()
        if res.success:
            res = adapter.insert_component(file_path, x, y, z)
        return {"status": "success" if res.success else "error", "message": res.message, "data": res.data}

    @mcp.tool(name="mate_component_planes")
    def mate_component_planes(first: str, second: str) -> Dict[str, Any]:
        """Mate two component planes coincident. Use Plane@Instance for each reference, for example Front Plane@Frame-1."""
        res = adapter.connect()
        if res.success:
            res = adapter.mate_planes(first, second)
        return {"status": "success" if res.success else "error", "message": res.message}

    @mcp.tool(
        name="save_model",
        description="Saves the active SolidWorks document to a specified path.",
    )
    def save_model_tool(file_path: str) -> Dict[str, Any]:
        res = adapter.save_model(file_path)
        return {"status": "success" if res.success else "error", "message": res.message, "data": res.data}

    @mcp.tool(
        name="close_model",
        description="Closes the active document in SolidWorks.",
    )
    def close_model_tool() -> Dict[str, Any]:
        res = adapter.close_model()
        return {"status": "success" if res.success else "error", "message": res.message}

    @mcp.tool(
        name="feature_extrude_boss",
        description="Extrudes the currently open or selected 2D sketch into a 3D solid feature (depth in mm).",
    )
    def feature_extrude_boss_tool(
        depth: float,
        mid_plane: bool = False,
        draft_angle: float = 0.0,
    ) -> Dict[str, Any]:
        res = adapter.feature_extrude_boss(depth=depth, mid_plane=mid_plane, draft_angle=draft_angle)
        return {"status": "success" if res.success else "error", "message": res.message, "feature": res.feature_name}

    @mcp.tool(
        name="feature_extrude_cut",
        description="Cuts through the 3D solid model using the active or selected sketch (depth in mm).",
    )
    def feature_extrude_cut_tool(
        depth: float,
        through_all: bool = False,
        flip_dir: bool = False,
    ) -> Dict[str, Any]:
        res = adapter.feature_extrude_cut(depth=depth, through_all=through_all, flip_dir=flip_dir)
        return {"status": "success" if res.success else "error", "message": res.message, "feature": res.feature_name}

    @mcp.tool(
        name="feature_revolve_boss",
        description="Revolves a 2D sketch profile around its centerline to create a rotational solid (e.g. shaft, cylinder, sphere).",
    )
    def feature_revolve_boss_tool(angle_degrees: float = 360.0) -> Dict[str, Any]:
        res = adapter.feature_revolve_boss(angle_degrees=angle_degrees)
        return {"status": "success" if res.success else "error", "message": res.message, "feature": res.feature_name}

    @mcp.tool(
        name="feature_revolve_cut",
        description="Cuts material from the solid body by revolving a sketch profile around a centerline axis.",
    )
    def feature_revolve_cut_tool(angle_degrees: float = 360.0) -> Dict[str, Any]:
        res = adapter.feature_revolve_cut(angle_degrees=angle_degrees)
        return {"status": "success" if res.success else "error", "message": res.message, "feature": res.feature_name}

    @mcp.tool(
        name="feature_fillet",
        description="Rounds edges of the solid body with a constant-radius fillet (radius in mm).",
    )
    def feature_fillet_tool(radius: float) -> Dict[str, Any]:
        res = adapter.feature_fillet(radius=radius)
        return {"status": "success" if res.success else "error", "message": res.message, "feature": res.feature_name}

    @mcp.tool(
        name="feature_chamfer",
        description="Bevels edges of the solid body with a chamfer (distance in mm, angle in degrees, default 45°).",
    )
    def feature_chamfer_tool(distance: float, angle_degrees: float = 45.0) -> Dict[str, Any]:
        res = adapter.feature_chamfer(distance=distance, angle_degrees=angle_degrees)
        return {"status": "success" if res.success else "error", "message": res.message, "feature": res.feature_name}

    @mcp.tool(
        name="feature_shell",
        description="Hollows out the solid body leaving a specified wall thickness (in mm).",
    )
    def feature_shell_tool(thickness: float) -> Dict[str, Any]:
        res = adapter.feature_shell(thickness=thickness)
        return {"status": "success" if res.success else "error", "message": res.message, "feature": res.feature_name}

    @mcp.tool(
        name="feature_circular_pattern",
        description="Patterns features circularly around the central axis (e.g. bolt holes, gear teeth, spokes).",
    )
    def feature_circular_pattern_tool(count: int, total_angle: float = 360.0) -> Dict[str, Any]:
        res = adapter.feature_circular_pattern(count=count, total_angle=total_angle)
        return {"status": "success" if res.success else "error", "message": res.message, "feature": res.feature_name}

    @mcp.tool(
        name="rebuild_model",
        description="Regenerates and rebuilds the active SolidWorks model (EditRebuild3).",
    )
    def rebuild_model_tool() -> Dict[str, Any]:
        res = adapter.rebuild()
        return {"status": "success" if res.success else "error", "message": res.message}
