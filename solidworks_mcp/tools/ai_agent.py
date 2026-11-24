"""Expose the local design agent through MCP."""

from fastmcp import FastMCP

from ..agent.local_agent import LocalCADAgent
from ..agent.standards import lookup_dimensions, offline_inventory
from ..com_adapter.base import BaseSolidWorksAdapter
from ..native_commands import find_commands


def register_ai_agent_tool(mcp: FastMCP, adapter: BaseSolidWorksAdapter, agent: LocalCADAgent) -> None:

    @mcp.tool(name="lookup_standard_dimensions")
    def standard_dimensions(query: str = "", family_id: str = "", filters: dict[str, str] | None = None,
                            option: str = "", offset: int = 0, library: str = "") -> dict:
        """Search ANSI Inch/Metric Toolbox families, then read their source dimensions by family_id and exact field filters.
        A blank query browses families. Page with offset. Select an option for related length/pitch/configuration tables.
        Length units apply to dimensional lengths only. Edition and tolerances require the applicable publisher sheet."""
        return lookup_dimensions(query, family_id, filters, option, offset, library)

    @mcp.tool(name="offline_standards")
    def offline_standards_tool(query: str = "", offset: int = 0) -> dict:
        """Search local public guide pages or list offline libraries and reference filenames. Page results with offset.
        Pass a library name (or 'all') to lookup_standard_dimensions to search beyond the default ANSI systems."""
        return offline_inventory(query, offset)

    @mcp.tool(name="find_solidworks_commands")
    def find_solidworks_commands(query: str = "", offset: int = 0, limit: int = 20) -> dict:
        """Search the installed desktop command names. Page with offset and limit."""
        result = find_commands(query, offset, limit)
        return {"status": "success" if result.success else "error", "message": result.message, "data": result.data}

    @mcp.tool(name="start_solidworks_command")
    def start_solidworks_command(name: str) -> dict:
        """Invoke an exact native command requested by the user. Interactive features may need selections in SolidWorks."""
        result = agent.invoke_native(name)
        return {"status": "success" if result.success else "error", "message": result.message, "data": result.data}

    @mcp.tool(name="cad_agent")
    def cad_agent_tool(prompt: str, conversation_id: str | None = None) -> dict:
        """Run CAD commands. On needs_input, ask the user and send their answer with the returned conversation_id."""
        return agent.run(prompt, conversation_id)

    @mcp.tool(name="ai_design")
    def ai_design_tool(prompt: str, conversation_id: str | None = None) -> dict:
        """Design a part or continue a pending design with the user's reply and conversation_id."""
        return agent.run(prompt, conversation_id)
