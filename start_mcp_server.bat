@echo off
title SolidWorks MCP Server (stdio)
cd /d "%~dp0"
".venv\Scripts\python.exe" -m solidworks_mcp.server
