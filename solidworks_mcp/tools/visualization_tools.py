"""SolidWorks Visual Snapshot & Camera Tools."""

from __future__ import annotations

import base64
import os
from typing import Any, Dict, Optional
from fastmcp import FastMCP
from ..com_adapter.base import BaseSolidWorksAdapter


def register_visualization_tools(mcp: FastMCP, adapter: BaseSolidWorksAdapter) -> None:
    """Register viewport capture and visual rendering tools."""

    @mcp.tool(
        name="capture_viewport_preview",
        description="Captures a high-resolution isometric screenshot/rendering of the 3D model currently in the SolidWorks viewport.",
    )
    def capture_viewport_preview_tool(
        output_path: Optional[str] = None,
        include_base64: bool = False,
    ) -> Dict[str, Any]:
        res = adapter.capture_viewport_image(output_path=output_path)
        data = res.data or {}
        img_path = data.get("image_path")

        b64_data = None
        if include_base64 and img_path and os.path.exists(img_path):
            with open(img_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("utf-8")

        return {
            "status": "success" if res.success else "error",
            "message": res.message,
            "image_path": img_path,
            "base64_preview": b64_data,
        }
