---
name: solidworks-cad
description: Autonomous live 3D CAD modeling and design in SolidWorks using the solidworks-mcp server and pywin32 COM automation.
---

# SolidWorks Autonomous CAD Design Skill

Use this skill whenever the user requests 3D CAD modeling, mechanical part design, or automation in Dassault Systèmes SolidWorks.

## Available Workflows

### 1. High-Level Live Parametric Design ("Prompt-to-CAD")
When the user asks to create standard components:
- **Flanges**: `create_live_design(prompt="circular mounting flange", design_type="flange", dimensions={...})`
- **Spur Gears**: `create_live_design(prompt="spur gear", design_type="gear", dimensions={...})`
- **Connecting Rods**: `create_live_design(prompt="connecting rod", design_type="connecting_rod", dimensions={...})`
- **Crank Arms**: `create_live_design(prompt="crank arm", design_type="crank", dimensions={...})`
- **Mounting Brackets**: `create_live_design(prompt="mounting bracket", design_type="bracket", dimensions={...})`
- **Enclosures / Boxes**: `create_live_design(prompt="electronics enclosure", design_type="enclosure", dimensions={...})`
- **Heat Sinks**: `create_live_design(prompt="extruded heat sink", design_type="heatsink", dimensions={...})`
- **Stepped Shafts**: `create_live_design(prompt="stepped shaft", design_type="shaft", dimensions={...})`

### 2. Direct Python COM Script Execution
For custom or complex mathematical curves (airfoils, custom cam profiles, involutes):
- Use `execute_solidworks_script(python_code=...)`
- Available in scope: `swApp`, `model`, `sketch_mgr`, `feat_mgr`, `sel_mgr`, `ext`, `mm_to_m`, `m_to_mm`, `math`.

### 3. Stepwise Parametric Modeling
- `new_part()`
- `create_sketch(plane_or_face="Front Plane")`
- `sketch_rectangle(...)` or `sketch_circle(...)`
- `feature_extrude_boss(depth=...)`
- `feature_fillet(radius=...)`
- `rebuild_model()`
- `get_mass_properties()`
- `capture_viewport_preview()`
