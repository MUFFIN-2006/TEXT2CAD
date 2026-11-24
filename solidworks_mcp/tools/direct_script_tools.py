"""Direct Script Execution Tool for CAD clients."""

from __future__ import annotations

from typing import Any, Dict
from fastmcp import FastMCP
from ..com_adapter.base import BaseSolidWorksAdapter
from ..execution.script_executor import PythonScriptExecutor


def register_direct_script_tools(mcp: FastMCP, adapter: BaseSolidWorksAdapter) -> None:
    """Register tools allowing AI agents to generate and execute direct Python COM scripts."""

    executor = PythonScriptExecutor(adapter)

    @mcp.tool(
        name="execute_solidworks_script",
        description="Executes custom Python CAD code directly against the live SolidWorks COM API. Variables available in scope: `swApp`, `model`, `part`, `sketch_mgr`, `feat_mgr`, `sel_mgr`, `ext`, `mm_to_m`, `m_to_mm`, `math`. Ideal for custom mathematical curves, airfoils, complex lofting, or specialized mechanical geometry.",
    )
    def execute_solidworks_script_tool(python_code: str) -> Dict[str, Any]:
        res = executor.execute(python_code)
        return {
            "status": "success" if res.success else "error",
            "message": res.message,
            "data": res.data,
            "error": res.error,
        }
