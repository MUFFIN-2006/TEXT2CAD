---
description: Best practices and engineering rules for SolidWorks CAD automation.
trigger: always_on
---

# SolidWorks Automation Rules

1. **Units**: SolidWorks internal COM API represents lengths in **meters**. Always use the converter helpers `mm_to_m(val)` and `m_to_mm(val)` so all user inputs and outputs remain in millimeters.
2. **Rebuilds**: Call `EditRebuild3()` / `rebuild_model` after adding or modifying features to ensure the geometry updates properly.
3. **Modal Dialog Suppression**: Ensure automated operations do not trigger blocking UI dialogs by keeping user preferences set to automation-friendly modes.
4. **Isometric Previews**: After creating or altering a model, always capture an updated isometric viewport snapshot using `capture_viewport_preview` so the user and AI can inspect the result visually.
