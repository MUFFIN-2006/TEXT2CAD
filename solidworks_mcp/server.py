"""Main FastMCP Server entrypoint for SolidWorks MCP."""

from __future__ import annotations

import argparse
import os
import sys
from fastmcp import FastMCP

from .config import config
from .com_adapter import get_adapter
from .agent.standards import MEASUREMENT_POLICY
from .tools import register_all_tools

SERVER_INSTRUCTIONS = """
Use offline_standards to search the local manufacturer guides by topic and report the actual local path and PDF page.
The active design is the default target. Send "move bolt on the nut" to cad_agent to reposition the existing pair.
For threaded nut motion use cad_agent with "tighten the nut" or "loosen the nut half a turn". Keep the bolt stationary.
Ask which instance to use only if the assembly has multiple candidates. Only start a separate design when requested.
Use lookup_standard_dimensions for machine-readable rows; select a named library when the design requires ISO, DIN or another system.
You are an expert mechanical design and CAD automation engineer connected live to Dassault Systèmes SolidWorks.
You have direct access to parametric modeling tools, generative design primitives, and real-time viewport feedback.

Document and follow-up rules:
1. Treat the active SolidWorks document as the user's current part. For requests to add or change a feature or dimension, edit that same document. Never call `new_part` or a full-part generator for a follow-up edit.
2. Use cad_agent for design requests. When it returns needs_input, present its question and wait for the user's answer. Pass the answer and conversation_id to cad_agent. Only accept suggested values when the user chooses them. For custom designs and manual tool sequences, ask for missing geometry and feature placement before modifying any document.
3. For edits, inspect the current model with `get_feature_tree` when needed, then use `set_dimension`, `add_hole_to_part`, `add_boss_to_part`, `add_pocket_to_part`, or the sequential sketch and feature tools. These modify the active document.
4. Use `modify_live_design` or granular feature tools (`add_hole_to_part`, `add_boss_to_part`, `add_pocket_to_part`, `set_dimension`, `feature_fillet`, etc.) for follow-up additions and edits to the active model. Use `create_live_design` or a `design_*` generator when creating a part from scratch. Use `new_part` only when the user explicitly asks for a separate new empty part/document. Never create a new document just to add or change geometry in the current part.
5. For custom or novel geometry, use sequential CAD tools (`create_sketch`, `sketch_rectangle`/`sketch_circle`, `feature_extrude_boss`, `feature_fillet`, etc.) or `execute_solidworks_script`, keeping the current document active for edits.
6. Generate new geometry in the open SolidWorks session. Use cad_agent for new virtual assembly components. Save or export files and capture viewport images only when requested. Rebuild and inspect the model as needed.
7. Ensure dimensions are realistic and adhere to sound mechanical engineering practices (clearance for bolts, stress relief fillets, standard sizes).
8. For native desktop tools, search find_solidworks_commands and invoke the exact requested command with start_solidworks_command. Preserve the active document for edits. An invoked interactive command may still require user selections in the PropertyManager.
9. For a machine, identify its working purpose, envelope, load or motion requirements, components, interfaces and purchased parts. Carry forward specifications already given. Ask only for information needed for the requested level of detail. Propose a component breakdown when the user does not have one. Translate the agreed requirements into part features, placements and mates. A custom design_brief from cad_agent can also be implemented with the granular tools. Use insert_assembly_component for saved parts or subassemblies and mate_component_planes for coincident plane constraints. Use the native mate tools for other constraints. Report outstanding design or verification work accurately.
10. For a planning-only request, keep all work in the conversation or the cad_agent plan command. Do not connect to SolidWorks, run scripts, start native commands, create documents or generate previews.
11. When this chat is the planner, translate free-form descriptions into CAD operations here. Use cad_agent with "find part <name or standard>" for reference data from the user's mechanical catalog. Preserve supplied dimensions and ask for missing requirements.
12. Before sizing a standard component, call lookup_standard_dimensions. Select the matching family, measurement system, nominal size and relevant options, and retrieve the exact rows. For assemblies, check each standard component separately. Use the source dimensions in the CAD operations and identify the sheet used. Inch lengths convert to mm by 25.4; pitch in threads per inch converts by 25.4/TPI. Angles, counts, ratios and thread classes have their own units. Preserve explicit user specifications and ask about conflicts. Toolbox entries can be customized or historical. A publisher link identifies a publication; an edition-specific claim needs the applicable dimensional sheet. If a family, size, tolerance or edition is missing, flag the gap and request the sheet or the required dimensions before using a default. Retain other governing standards such as AGMA or ISO when applicable.
"""


SERVER_INSTRUCTIONS += "\n" + MEASUREMENT_POLICY


def create_server(mock_mode: bool = False, headless: bool = False) -> FastMCP:
    """Instantiate and configure the FastMCP SolidWorks server."""
    if mock_mode:
        config.mock_mode = True
    if headless:
        config.headless = True

    mcp = FastMCP(
        config.server_name,
        instructions=SERVER_INSTRUCTIONS,
    )

    adapter = get_adapter()
    register_all_tools(mcp, adapter)

    @mcp.prompt("cad_designer")
    def cad_designer_prompt(prompt_request: str) -> str:
        return (f"User design request: '{prompt_request}'. Ask for any missing requirements and wait for "
                "the user's answers before creating or editing the model in SolidWorks.")

    return mcp


def main():
    """Command-line runner for the MCP server."""
    parser = argparse.ArgumentParser(description="SolidWorks Autonomous CAD MCP Server")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "sse", "stream"], help="MCP transport protocol")
    parser.add_argument("--port", type=int, default=8000, help="Port for SSE transport")
    parser.add_argument("--mock", action="store_true", help="Run in mock/simulation mode without live SolidWorks")
    parser.add_argument("--headless", action="store_true", help="Run SolidWorks hidden in background")

    args = parser.parse_args()

    mcp = create_server(mock_mode=args.mock, headless=args.headless)

    if args.transport == "sse":
        print(f"Starting SolidWorks MCP SSE Server on http://127.0.0.1:{args.port}...")
        mcp.run(transport="sse", port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
