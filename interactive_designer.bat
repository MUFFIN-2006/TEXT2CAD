@echo off
title SolidWorks CAD Designer
cd /d "%~dp0"
".venv\Scripts\python.exe" -m solidworks_mcp.agent.designer %*
pause
