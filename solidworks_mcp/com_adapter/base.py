"""Base abstract adapter interface for SolidWorks automation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel


class CADResult(BaseModel):
    """Standardized response from CAD operations."""
    success: bool
    message: str
    feature_name: Optional[str] = None
    data: Dict[str, Any] = {}
    error: Optional[str] = None


COMPONENT_OPERATIONS = {"create_sketch", "sketch_circle", "sketch_rectangle", "sketch_closed_polyline",
                        "feature_extrude_boss", "feature_extrude_cut", "add_hole", "add_cut_pocket", "add_boss_feature",
                        "add_metric_thread"}


class BaseSolidWorksAdapter(ABC):
    """Abstract interface defining all CAD operations supported by the MCP server."""

    @abstractmethod
    def connect(self) -> CADResult:
        """Connect to running SolidWorks instance or launch a new one."""
        pass

    @abstractmethod
    def disconnect(self) -> CADResult:
        """Disconnect and release COM resources."""
        pass

    @abstractmethod
    def new_part(self) -> CADResult:
        """Create a new SolidWorks Part document."""
        pass

    @abstractmethod
    def new_assembly(self) -> CADResult:
        """Create a new SolidWorks Assembly document."""
        pass

    def component_file_exists(self, path):
        return Path(path).is_file()

    def add_metric_thread(self, diameter, pitch, internal, depth, tip):
        return CADResult(success=False, message="This adapter cannot build modeled threads.")

    def thread_fasteners(self, target):
        return CADResult(success=False, message="This adapter cannot edit fastener threads.")

    def screw_mate_fasteners(self, **kwargs):
        return self.move_fastener(**kwargs, screw_mate=True)

    def move_fastener(self, moving, bolt=None, nut=None, assembly_id=None, *, screw_mate=False, turns=None):
        from ..agent.fasteners import COARSE_PITCH, bolt_to_nut_offset, placement_candidates
        try:
            document, components = self._placement_components()
            if assembly_id is not None and document != assembly_id:
                raise ValueError("The active assembly changed. Request the move again in the intended assembly.")
            candidates = placement_candidates(components, bolt, nut)
            for role, options in candidates.items():
                if len(options) > 1:
                    return CADResult(success=False, message=f"Which {role} should I use?",
                                     data=dict(role=role, choices=list(options), assembly_id=document))
            bolt, spec = next(iter(candidates["bolt"].items()))
            nut = next(iter(candidates["nut"]))
            pair = dict(assembly_id=document, bolt=bolt, nut=nut, moving=moving)
            if moving not in {"bolt", "nut"}:
                raise ValueError("Choose the bolt or nut to move.")
            source, target = (bolt, nut) if moving == "bolt" else (nut, bolt)
            if screw_mate:
                diameter = spec["diameter"]
                pitch = COARSE_PITCH[diameter]
                created = self._screw_mate(components[bolt], components[nut], spec, pitch, moving)
                if turns is not None:
                    try:
                        self._turn_fastener(components[bolt], components[nut], spec, pitch, turns, moving)
                    except Exception as exc:
                        return CADResult(success=False, message=f"The screw mate is active. {exc}")
                    unit = "turn" if abs(turns) == 1 else "turns"
                    message = f"Turned {source} {turns:g} {unit} with {turns*pitch:g} mm axial travel."
                    if moving == "nut" and turns:
                        direction = "toward" if turns > 0 else "away from"
                        message = f"Turned the nut {abs(turns):g} {unit}, moving it {abs(turns*pitch):g} mm {direction} the bolt head."
                    return CADResult(success=True, message=message,
                                     data=dict(**pair, component=source, target=target, pitch_mm=pitch, turns=turns, travel_mm=turns*pitch))
                message = f"Screw mate {'added' if created else 'active'}. Travel is {pitch:g} mm per turn. Try 'turn {moving} a quarter turn'."
                return CADResult(success=True, message=message, data=dict(**pair, pitch_mm=pitch, created=created))
            offset = bolt_to_nut_offset(**spec)
            changed = self._place_fastener(components[source], components[target], -offset if moving == "bolt" else offset)
            message = (f"Moved {source} onto {target}." if changed else f"{source} is already seated on {target}.")
            return CADResult(success=True, message=message, data=dict(**pair, component=source, target=target, moved=changed))
        except Exception as exc:
            return CADResult(success=False, message=str(exc))

    def _placement_components(self):
        raise NotImplementedError("Assembly positioning is unavailable with this adapter.")

    def _screw_mate(self, bolt, nut, spec, pitch, moving):
        raise NotImplementedError("Screw mates are unavailable with this adapter.")

    def _turn_fastener(self, bolt, nut, spec, pitch, turns, moving):
        raise NotImplementedError("Threaded motion is unavailable with this adapter.")

    def _place_fastener(self, source, target, offset_mm):
        raise NotImplementedError("Assembly positioning is unavailable with this adapter.")

    def geometry_revision(self):
        """Identity and revision of the active document, if available without opening it."""
        return None

    def active_document_kind(self):
        """Return the active document type without opening or activating a document."""
        return None

    def create_virtual_component(self, name, origin, features) -> CADResult:
        return CADResult(success=False, message="This adapter cannot create virtual assembly components.")

    def draw_component_features(self, features):
        if not features or any(f["operation"] not in COMPONENT_OPERATIONS for f in features):
            raise ValueError("Unsupported virtual component geometry.")
        for feature in features:
            result = getattr(self, feature["operation"])(**feature["arguments"])
            if not result.success:
                raise ValueError(result.message)

    def insert_component(self, file_path: str, x: float, y: float, z: float) -> CADResult:
        return CADResult(success=False, message="Component insertion is unavailable with this adapter.")

    def mate_planes(self, first: str, second: str) -> CADResult:
        return CADResult(success=False, message="Assembly plane mates are unavailable with this adapter.")

    @abstractmethod
    def save_model(self, file_path: str) -> CADResult:
        """Save the active document to a specified file path."""
        pass

    @abstractmethod
    def close_model(self) -> CADResult:
        """Close the active document."""
        pass

    @abstractmethod
    def select_plane(self, plane_name: str) -> CADResult:
        """Select a standard plane ('Front Plane', 'Top Plane', 'Right Plane') or face."""
        pass

    @abstractmethod
    def create_sketch(self, plane_or_face: str = "Front Plane") -> CADResult:
        """Start a new sketch on the specified plane or planar face."""
        pass

    @abstractmethod
    def exit_sketch(self) -> CADResult:
        """Exit and finalize the active sketch."""
        pass

    @abstractmethod
    def sketch_rectangle(
        self, x1: float, y1: float, x2: float, y2: float, center_based: bool = True
    ) -> CADResult:
        """Draw a rectangle in mm."""
        pass

    @abstractmethod
    def sketch_circle(self, xc: float, yc: float, radius: float) -> CADResult:
        """Draw a circle in mm."""
        pass

    @abstractmethod
    def sketch_line(self, x1: float, y1: float, x2: float, y2: float, is_centerline: bool = False) -> CADResult:
        """Draw a 2D line segment in mm."""
        pass

    def sketch_batch(self):
        """Draw exact sketch coordinates without interactive snapping."""
        return nullcontext()

    def resize_gear(self, num_teeth=None, outer_diameter=None) -> CADResult:
        """Edit the sampled tooth profile of an existing gear in the active part."""
        return CADResult(success=False, message="Gear profile editing is unavailable with this adapter.")

    def sweep_twisted_profile(self, width, twist_radians) -> CADResult:
        """Sweep the active front-plane profile along +Z while rotating about Z."""
        return CADResult(success=False, message="This adapter does not support twisted sweeps.")

    def sketch_closed_polyline(self, points) -> CADResult:
        """Create a closed chain of straight segments in the current sketch (mm)."""
        if len(points) < 3:
            return CADResult(success=False, message="A closed profile needs at least three points.")
        for i, start in enumerate(points):
            result = self.sketch_line(*start, *points[(i + 1) % len(points)])
            if not result.success:
                return result
        return CADResult(success=True, message=f"Sketched {len(points)} segments.")

    def run_native_command(self, command_id: int, name: str) -> CADResult:
        return CADResult(success=False, message=f"{name} requires a live SolidWorks desktop.")

    @abstractmethod
    def sketch_arc(self, start, end, through) -> CADResult:
        """Draw a circular arc from start to end through a third point (mm)."""

    @abstractmethod
    def sketch_polygon(
        self, xc: float, yc: float, radius: float, sides: int = 6, inscribed: bool = True
    ) -> CADResult:
        """Draw a regular polygon in mm."""
        pass

    @abstractmethod
    def sketch_slot(
        self, x1: float, y1: float, x2: float, y2: float, width: float
    ) -> CADResult:
        """Draw a straight slot between two center points with a given width in mm."""
        pass

    @abstractmethod
    def feature_extrude_boss(
        self, depth: float, mid_plane: bool = False, draft_angle: float = 0.0
    ) -> CADResult:
        """Extrude the active sketch into a solid boss (depth in mm)."""
        pass

    @abstractmethod
    def feature_extrude_cut(
        self, depth: float, through_all: bool = False, flip_dir: bool = False
    ) -> CADResult:
        """Cut-extrude the active sketch through the body (depth in mm)."""
        pass

    @abstractmethod
    def feature_revolve_boss(
        self, angle_degrees: float = 360.0, reverse_dir: bool = False
    ) -> CADResult:
        """Revolve the active sketch around its centerline."""
        pass

    @abstractmethod
    def feature_revolve_cut(
        self, angle_degrees: float = 360.0
    ) -> CADResult:
        """Revolve-cut the active sketch around its centerline."""
        pass

    @abstractmethod
    def feature_fillet(self, radius: float, edge_or_all: str = "all") -> CADResult:
        """Apply a constant-radius fillet (radius in mm)."""
        pass

    @abstractmethod
    def feature_chamfer(self, distance: float, angle_degrees: float = 45.0) -> CADResult:
        """Apply a chamfer to edges (distance in mm)."""
        pass

    @abstractmethod
    def feature_shell(self, thickness: float) -> CADResult:
        """Shell the body to create a hollow part with specified wall thickness (in mm)."""
        pass

    @abstractmethod
    def feature_linear_pattern(
        self,
        count_d1: int,
        spacing_d1: float,
        count_d2: int = 1,
        spacing_d2: float = 0.0,
        feature_name: Optional[str] = None,
    ) -> CADResult:
        """Create a 1D or 2D linear pattern of features."""
        pass

    @abstractmethod
    def feature_circular_pattern(
        self, count: int, total_angle: float = 360.0, feature_name: Optional[str] = None
    ) -> CADResult:
        """Create a circular pattern of features."""
        pass

    @abstractmethod
    def get_mass_properties(self) -> CADResult:
        """Read mass, volume, surface area, and center of mass from SolidWorks."""
        pass

    @abstractmethod
    def get_feature_tree(self) -> CADResult:
        """List all features in the FeatureManager design tree."""
        pass

    @abstractmethod
    def capture_viewport_image(self, output_path: Optional[str] = None) -> CADResult:
        """Capture the 3D model viewport as a high-resolution PNG image."""
        pass

    @abstractmethod
    def set_material(self, material_name: str, database: str = "solidworks materials") -> CADResult:
        """Assign engineering material to the active part."""
        pass

    @abstractmethod
    def rebuild(self) -> CADResult:
        """Rebuild/regenerate the 3D model (EditRebuild3)."""
        pass

    @abstractmethod
    def execute_raw_python(self, code: str) -> CADResult:
        """Execute arbitrary Python code directly with live SolidWorks COM objects injected."""
        pass

    @abstractmethod
    def has_active_document(self) -> bool:
        """Check whether a document is currently open and active."""
        pass

    @abstractmethod
    def set_dimension(self, dimension_name: str, value_mm: float) -> CADResult:
        """Modify an existing dimension in the active model (value in mm)."""
        pass

    @abstractmethod
    def add_hole(
        self,
        diameter: float,
        xc: float = 0.0,
        yc: float = 0.0,
        depth: float = 0.0,
        through_all: bool = True,
        plane_or_face: str = "Front Plane",
        flip_dir: bool = False,
    ) -> CADResult:
        """Add a through or blind hole to the active part without creating a new document."""
        pass

    @abstractmethod
    def add_boss_feature(
        self,
        shape: str = "circle",
        dim1: float = 20.0,
        dim2: float = 20.0,
        xc: float = 0.0,
        yc: float = 0.0,
        depth: float = 10.0,
        plane_or_face: str = "Front Plane",
    ) -> CADResult:
        """Add an extruded boss on the active part without creating a new document."""
        pass

    @abstractmethod
    def add_cut_pocket(
        self,
        shape: str = "rectangle",
        width: float = 20.0,
        height: float = 20.0,
        depth: float = 5.0,
        xc: float = 0.0,
        yc: float = 0.0,
        plane_or_face: str = "Front Plane",
        flip_dir: bool = False,
    ) -> CADResult:
        """Cut a pocket into the active part without creating a new document."""
        pass
