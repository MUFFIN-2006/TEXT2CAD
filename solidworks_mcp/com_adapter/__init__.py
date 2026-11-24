"""Adapter factory for SolidWorks COM or Mock."""

from __future__ import annotations

import os
from .base import BaseSolidWorksAdapter, CADResult
from .mock_adapter import MockSolidWorksAdapter
from ..config import config


def get_adapter() -> BaseSolidWorksAdapter:
    """Return the active CAD adapter based on configuration and platform."""
    if config.mock_mode:
        return MockSolidWorksAdapter()

    try:
        from .solidworks_com import SolidWorksCOMAdapter, PYWIN32_AVAILABLE
        if PYWIN32_AVAILABLE:
            return SolidWorksCOMAdapter(headless=config.headless, settle_seconds=config.settle_seconds)
    except Exception:
        pass

    # Fallback to MockAdapter if on non-Windows or COM unavailable
    return MockSolidWorksAdapter()


__all__ = ["BaseSolidWorksAdapter", "CADResult", "get_adapter", "MockSolidWorksAdapter"]
