"""SolidWorks Inspection and Material Properties Tools."""

from __future__ import annotations

from typing import Any, Dict
from fastmcp import FastMCP
from ..com_adapter.base import BaseSolidWorksAdapter


def register_inspection_tools(mcp: FastMCP, adapter: BaseSolidWorksAdapter) -> None:
    """Register physical property inspection and material assignment tools."""

    @mcp.tool(
        name="get_mass_properties",
        description="Calculates mass (kg), volume (mm³), surface area (mm²), center of mass, and density of the active SolidWorks part.",
    )
    def get_mass_properties_tool() -> Dict[str, Any]:
        res = adapter.get_mass_properties()
        return {"status": "success" if res.success else "error", "message": res.message, "data": res.data}

    @mcp.tool(
        name="get_feature_tree",
        description="Inspects and lists all features in the FeatureManager design tree with their names, types, and suppression status.",
    )
    def get_feature_tree_tool() -> Dict[str, Any]:
        res = adapter.get_feature_tree()
        return {"status": "success" if res.success else "error", "message": res.message, "data": res.data}

    @mcp.tool(
        name="set_material",
        description="Assigns an engineering material to the active part (e.g., '6061 Alloy', 'Plain Carbon Steel', 'AISI 304', 'Brass', 'ABS').",
    )
    def set_material_tool(material_name: str, database: str = "solidworks materials") -> Dict[str, Any]:
        res = adapter.set_material(material_name=material_name, database=database)
        return {"status": "success" if res.success else "error", "message": res.message, "data": res.data}
