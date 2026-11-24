"""SolidWorks 2D Parametric Sketching Tools."""

from __future__ import annotations

from typing import Any, Dict
from fastmcp import FastMCP
from ..com_adapter.base import BaseSolidWorksAdapter


def register_sketch_tools(mcp: FastMCP, adapter: BaseSolidWorksAdapter) -> None:
    """Register 2D sketching tools."""

    @mcp.tool(
        name="create_sketch",
        description="Starts a new 2D sketch on a standard plane ('Front Plane', 'Top Plane', 'Right Plane') or planar face.",
    )
    def create_sketch_tool(plane_or_face: str = "Front Plane") -> Dict[str, Any]:
        res = adapter.create_sketch(plane_or_face=plane_or_face)
        return {"status": "success" if res.success else "error", "message": res.message, "data": res.data}

    @mcp.tool(
        name="exit_sketch",
        description="Closes and exits the active 2D sketch.",
    )
    def exit_sketch_tool() -> Dict[str, Any]:
        res = adapter.exit_sketch()
        return {"status": "success" if res.success else "error", "message": res.message}

    @mcp.tool(
        name="sketch_rectangle",
        description="Draws a rectangle in the active sketch (dimensions in mm). center_based=True uses (x1, y1) as center and (x2, y2) as corner.",
    )
    def sketch_rectangle_tool(
        x1: float, y1: float, x2: float, y2: float, center_based: bool = True
    ) -> Dict[str, Any]:
        res = adapter.sketch_rectangle(x1, y1, x2, y2, center_based=center_based)
        return {"status": "success" if res.success else "error", "message": res.message}

    @mcp.tool(
        name="sketch_circle",
        description="Draws a circle in the active sketch at center (xc, yc) with radius in mm.",
    )
    def sketch_circle_tool(xc: float, yc: float, radius: float) -> Dict[str, Any]:
        res = adapter.sketch_circle(xc, yc, radius)
        return {"status": "success" if res.success else "error", "message": res.message}

    @mcp.tool(
        name="sketch_line",
        description="Draws a line segment between (x1, y1) and (x2, y2) in mm. Set is_centerline=True for construction / axis of revolution.",
    )
    def sketch_line_tool(
        x1: float, y1: float, x2: float, y2: float, is_centerline: bool = False
    ) -> Dict[str, Any]:
        res = adapter.sketch_line(x1, y1, x2, y2, is_centerline=is_centerline)
        return {"status": "success" if res.success else "error", "message": res.message}

    @mcp.tool(
        name="sketch_polygon",
        description="Draws a regular polygon (e.g. hexagon, pentagon) with N sides centered at (xc, yc) with radius in mm.",
    )
    def sketch_polygon_tool(
        xc: float, yc: float, radius: float, sides: int = 6, inscribed: bool = True
    ) -> Dict[str, Any]:
        res = adapter.sketch_polygon(xc, yc, radius, sides=sides, inscribed=inscribed)
        return {"status": "success" if res.success else "error", "message": res.message}

    @mcp.tool(
        name="sketch_slot",
        description="Draws a straight slot between two center points (x1, y1) and (x2, y2) with slot width in mm.",
    )
    def sketch_slot_tool(x1: float, y1: float, x2: float, y2: float, width: float) -> Dict[str, Any]:
        res = adapter.sketch_slot(x1, y1, x2, y2, width=width)
        return {"status": "success" if res.success else "error", "message": res.message}
