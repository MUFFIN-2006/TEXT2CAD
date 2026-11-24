"""Configuration settings for SolidWorks MCP."""

from __future__ import annotations

import os
from pathlib import Path
from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    """Configuration options for the server and COM adapter."""

    server_name: str = "SolidWorks-CAD-MCP"
    version: str = "1.0.0"
    mock_mode: bool = Field(
        default_factory=lambda: os.getenv("SOLIDWORKS_MOCK_MODE", "0").lower() in ("1", "true", "yes")
    )
    headless: bool = Field(
        default_factory=lambda: os.getenv("SOLIDWORKS_HEADLESS", "0").lower() in ("1", "true", "yes")
    )
    default_units: str = "mm"  # SolidWorks internal units are meters, user inputs in mm
    default_plane: str = "Front Plane"
    screenshot_dir: Path = Field(
        default_factory=lambda: Path(os.getenv("TEMP", ".")) / "solidworks_previews"
    )
    rebuild_on_change: bool = True
    settle_seconds: float = 0.25


config = ServerConfig()
