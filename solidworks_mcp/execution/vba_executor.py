"""VBA Macro Executor for SolidWorks."""

from __future__ import annotations

import os
import tempfile
import traceback
from typing import Any, Optional
from ..com_adapter.base import BaseSolidWorksAdapter, CADResult


class VBAExecutor:
    """Executes SolidWorks VBA macros."""

    def __init__(self, adapter: BaseSolidWorksAdapter):
        self.adapter = adapter

    def run_macro_file(
        self, macro_path: str, module_name: str = "main", procedure_name: str = "main"
    ) -> CADResult:
        """Run an existing .swp macro file."""
        if not hasattr(self.adapter, "swApp") or not self.adapter.swApp:
            return CADResult(success=False, message="SolidWorks COM is not active.")

        try:
            app = self.adapter.swApp
            # RunMacro2(Path, ModuleName, ProcedureName, Options, Error)
            retval = app.RunMacro2(macro_path, module_name, procedure_name, 0, 0)
            return CADResult(
                success=True,
                message=f"Executed VBA macro '{macro_path}::{module_name}.{procedure_name}'.",
                data={"return_code": retval},
            )
        except Exception as e:
            return CADResult(
                success=False,
                message=f"VBA macro execution failed: {str(e)}",
                error=traceback.format_exc(),
            )
