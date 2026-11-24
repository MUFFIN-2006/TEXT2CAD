"""High-level design tools share the local agent's requirements conversation."""

from typing import Any, Dict, Optional
from fastmcp import FastMCP
from ..agent.local_agent import LocalCADAgent
from ..com_adapter.base import BaseSolidWorksAdapter


def register_live_design_tools(mcp: FastMCP, adapter: BaseSolidWorksAdapter, agent: LocalCADAgent) -> None:
    def build(prompt, conversation_id, kind, dimensions):
        supplied = {key: value for key, value in dimensions.items() if value is not None}
        return agent.run(prompt, conversation_id, design_type=kind, dimensions=supplied, design_tool=True)

    @mcp.tool(
        name="modify_live_design",
        description=(
            "Modifies, edits, or adds features (holes, cuts, pockets, bosses, fillets, chamfers, shells, or dimension changes) "
            "to the currently active SolidWorks part document. Always modifies the same active part without creating a new document. "
            "Examples: 'add a 10mm hole in the center', 'fillet edges to 3mm', 'cut a 20x20 pocket 5mm deep', 'change thickness to 15mm'."
        ),
    )
    def modify_live_design(
        prompt: str,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Modify or add features to the active part in SolidWorks."""
        return agent.run(prompt, conversation_id, separate=False)

    @mcp.tool(name="create_live_design")
    def create_live_design(prompt: str, design_type: Optional[str] = None,
                           dimensions: Optional[Dict[str, float]] = None,
                           conversation_id: Optional[str] = None) -> Dict[str, Any]:
        """Work in the active design. Request a new document explicitly. Continue questions with the same conversation_id."""
        kind = design_type.lower().replace("_", " ") if design_type else None
        kind = {"rod": "connecting rod", "heatsink": "heat sink"}.get(kind, kind)
        aliases = {"od": "outer_diameter", "pcd": "bolt_circle_diameter", "bolt_circle": "bolt_circle_diameter",
                   "holes": "bolt_hole_count", "bolt_count": "bolt_hole_count", "hole_dia": "bolt_hole_diameter",
                   "teeth": "num_teeth", "fins": "fin_count", "leg1": "leg1_length", "leg2": "leg2_length",
                   "bore": "bore_diameter", "id": "bore_diameter", "center_bore": "center_bore_diameter"}
        target = kind or prompt.lower()
        if "flange" in target:
            aliases["bore"] = "center_bore_diameter"
        if "gear" in target:
            aliases["thickness"] = "face_width"
        if "heat" in target:
            aliases.update(length="base_length", width="base_width")
        if "crank" in target:
            aliases["radius"] = "crank_radius"
        if "rod" in target:
            aliases["length"] = "center_distance"
        supplied = {aliases.get(k, k): v for k, v in (dimensions or {}).items()}
        return build(prompt, conversation_id, kind, supplied)

    @mcp.tool(
        name="design_mounting_bracket",
        description="Creates a parametric rectangular mounting plate/bracket with 4 corner mounting holes and edge fillets in SolidWorks.",
    )
    def design_mounting_bracket_tool(
        length: Optional[float] = None,
        width: Optional[float] = None,
        thickness: Optional[float] = None,
        corner_fillet: Optional[float] = None,
        hole_diameter: Optional[float] = None,
        hole_margin: Optional[float] = None,
    ) -> Dict[str, Any]:
        return build("mounting bracket", None, "mounting bracket", {
            "length": length, "width": width, "thickness": thickness, "corner_fillet": corner_fillet,
            "hole_diameter": hole_diameter, "hole_margin": hole_margin,
        })

    @mcp.tool(
        name="design_flange",
        description="Creates a precision circular pipe or shaft mounting flange with center bore and PCD radial bolt holes in SolidWorks.",
    )
    def design_flange_tool(
        outer_diameter: Optional[float] = None,
        thickness: Optional[float] = None,
        center_bore_diameter: Optional[float] = None,
        bolt_circle_diameter: Optional[float] = None,
        bolt_hole_count: Optional[int] = None,
        bolt_hole_diameter: Optional[float] = None,
        hub_diameter: Optional[float] = None,
        hub_length: Optional[float] = None,
    ) -> Dict[str, Any]:
        return build("flange", None, "flange", {
            "outer_diameter": outer_diameter, "thickness": thickness, "center_bore_diameter": center_bore_diameter,
            "bolt_circle_diameter": bolt_circle_diameter, "bolt_hole_count": bolt_hole_count,
            "bolt_hole_diameter": bolt_hole_diameter, "hub_diameter": hub_diameter, "hub_length": hub_length,
        })

    @mcp.tool(
        name="design_spur_gear",
        description="Creates an involute spur gear with tooth profile, pitch diameter, center bore, and keyway in SolidWorks.",
    )
    def design_spur_gear_tool(
        num_teeth: Optional[int] = None,
        module: Optional[float] = None,
        pressure_angle: Optional[float] = None,
        face_width: Optional[float] = None,
        bore_diameter: Optional[float] = None,
        keyway_width: Optional[float] = None,
        keyway_depth: Optional[float] = None,
    ) -> Dict[str, Any]:
        return build("spur gear", None, "spur gear", {
            "num_teeth": num_teeth, "module": module, "pressure_angle": pressure_angle, "face_width": face_width,
            "bore_diameter": bore_diameter, "keyway_width": keyway_width, "keyway_depth": keyway_depth,
        })

    @mcp.tool(
        name="design_connecting_rod",
        description="Creates a mechanical connecting rod link for slider-crank mechanisms / engines with big-end and small-end bearing bores.",
    )
    def design_connecting_rod_tool(
        center_distance: Optional[float] = None,
        big_end_bore: Optional[float] = None,
        big_end_od: Optional[float] = None,
        small_end_bore: Optional[float] = None,
        small_end_od: Optional[float] = None,
        beam_width: Optional[float] = None,
        beam_thickness: Optional[float] = None,
    ) -> Dict[str, Any]:
        return build("connecting rod", None, "connecting rod", {
            "center_distance": center_distance, "big_end_bore": big_end_bore, "big_end_od": big_end_od,
            "small_end_bore": small_end_bore, "small_end_od": small_end_od,
            "beam_width": beam_width, "beam_thickness": beam_thickness,
        })

    @mcp.tool(
        name="design_bushing",
        description="Creates a precision cylindrical sleeve bushing / bearing or flanged bushing in SolidWorks.",
    )
    def design_bushing_tool(
        outer_diameter: Optional[float] = None,
        inner_diameter: Optional[float] = None,
        length: Optional[float] = None,
        flange_diameter: Optional[float] = None,
        flange_thickness: Optional[float] = None,
        chamfer: Optional[float] = None,
    ) -> Dict[str, Any]:
        return build("bushing", None, "bushing", {
            "outer_diameter": outer_diameter, "inner_diameter": inner_diameter, "length": length,
            "flange_diameter": flange_diameter, "flange_thickness": flange_thickness, "chamfer": chamfer,
        })

    @mcp.tool(
        name="design_dowel_pin",
        description="Creates a precision cylindrical dowel pin or locating pin with chamfered ends in SolidWorks.",
    )
    def design_dowel_pin_tool(
        diameter: Optional[float] = None,
        length: Optional[float] = None,
        chamfer: Optional[float] = None,
    ) -> Dict[str, Any]:
        return build("dowel pin", None, "dowel pin", {
            "diameter": diameter, "length": length, "chamfer": chamfer,
        })

    @mcp.tool(
        name="design_structural_tube",
        description="Creates a hollow structural profile tube (round tube / pipe or square box section SHS) in SolidWorks.",
    )
    def design_structural_tube_tool(
        outer_size: Optional[float] = None,
        wall_thickness: Optional[float] = None,
        length: Optional[float] = None,
        shape: Optional[str] = "square",
    ) -> Dict[str, Any]:
        return build("structural tube", None, "structural tube", {
            "outer_size": outer_size, "wall_thickness": wall_thickness, "length": length, "shape": shape,
        })
