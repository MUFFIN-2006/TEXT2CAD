"""Tools package for SolidWorks MCP."""

from __future__ import annotations

from fastmcp import FastMCP
from ..com_adapter.base import BaseSolidWorksAdapter
from ..agent.local_agent import LocalCADAgent

from .live_design import register_live_design_tools
from .ai_agent import register_ai_agent_tool
from .modeling_tools import register_modeling_tools
from .sketch_tools import register_sketch_tools
from .inspection_tools import register_inspection_tools
from .visualization_tools import register_visualization_tools
from .direct_script_tools import register_direct_script_tools


def register_all_tools(mcp: FastMCP, adapter: BaseSolidWorksAdapter) -> None:
    """Register all modular CAD tools with the FastMCP server."""
    agent = LocalCADAgent(adapter)
    register_live_design_tools(mcp, adapter, agent)
    register_ai_agent_tool(mcp, adapter, agent)
    register_modeling_tools(mcp, adapter)
    register_sketch_tools(mcp, adapter)
    register_inspection_tools(mcp, adapter)
    register_visualization_tools(mcp, adapter)
    register_direct_script_tools(mcp, adapter)


__all__ = ["register_all_tools"]
