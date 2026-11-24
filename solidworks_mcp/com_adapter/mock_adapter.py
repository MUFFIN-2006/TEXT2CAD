"""High-fidelity Mock SolidWorks Adapter for headless testing, CI, and simulation."""

from __future__ import annotations

import os
import math
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from PIL import Image, ImageDraw

from .base import BaseSolidWorksAdapter, CADResult
from ..parametric.gear_edit import UNRECOGNIZED, edge_key, plan_resize


class MockSolidWorksAdapter(BaseSolidWorksAdapter):
    """Simulated SolidWorks adapter that models geometry state, features, and renders preview images."""

    def __init__(self):
        self.is_connected = False
        self.active_document: Optional[str] = None
        self._part_number = 0
        self._assembly_number = 0
        self._saved_components = set()
        self._extrusion_profiles = {}
        self.features: List[Dict[str, Any]] = []
        self.current_sketch: Optional[Dict[str, Any]] = None
        self.material: str = "Plain Carbon Steel"
        self.density: float = 7800.0  # kg/m³
        self.volume_mm3: float = 0.0
        self.surface_area_mm2: float = 0.0
        self.bounding_box: List[float] = [0.0, 0.0, 0.0]  # X, Y, Z extent in mm

    def geometry_revision(self):
        if self.active_document:
            return self.active_document, len(self.features), self.volume_mm3

    def active_document_kind(self):
        extension = Path(self.active_document or "").suffix.lower()
        return {".sldprt": "part", ".sldasm": "assembly", ".slddrw": "drawing"}.get(extension)

    def connect(self) -> CADResult:
        self.is_connected = True
        return CADResult(
            success=True,
            message="Connected to SolidWorks Simulator (Mock Mode Active).",
            data={"mode": "mock", "version": "SolidWorks 2026 Simulation Bridge"},
        )

    def disconnect(self) -> CADResult:
        self.is_connected = False
        return CADResult(success=True, message="Disconnected from SolidWorks Simulator.")

    def new_part(self) -> CADResult:
        self._part_number += 1
        self.active_document = f"Part{self._part_number}.SLDPRT"
        self.current_sketch = None
        self._extrusion_profiles.clear()
        self.features = [
            {"name": "Front Plane", "type": "RefPlane", "suppressed": False},
            {"name": "Top Plane", "type": "RefPlane", "suppressed": False},
            {"name": "Right Plane", "type": "RefPlane", "suppressed": False},
            {"name": "Origin", "type": "Origin", "suppressed": False},
        ]
        self.volume_mm3 = 0.0
        self.surface_area_mm2 = 0.0
        self.bounding_box = [0.0, 0.0, 0.0]
        return CADResult(success=True, message=f"Created new simulated part '{self.active_document}'.")

    def new_assembly(self) -> CADResult:
        self._assembly_number += 1
        self.active_document = f"Assem{self._assembly_number}.SLDASM"
        self.current_sketch = None
        self._extrusion_profiles.clear()
        self.volume_mm3 = self.surface_area_mm2 = 0
        self.bounding_box = [0, 0, 0]
        self.features = []
        return CADResult(success=True, message=f"Created simulated assembly '{self.active_document}'.")

    def component_file_exists(self, path):
        return Path(path) in self._saved_components or super().component_file_exists(path)

    def add_metric_thread(self, diameter, pitch, internal, depth, tip):
        if not any(feature["type"] == "Thread" for feature in self.features):
            self.features.append(dict(type="Thread", name=f"M{diameter} Thread", pitch=pitch, internal=internal,
                                      depth=depth, tip=tip))
        return CADResult(success=True, message=f"Modeled M{diameter} x {pitch:g} thread.")

    def thread_fasteners(self, target):
        from ..agent.fasteners import component_threads
        components = {f["name"]: f for f in self.features if f["type"] == "Component"}
        edited = []
        for name, args in component_threads(components, target):
            part = MockSolidWorksAdapter()
            part.features = components[name].setdefault("features", [])
            part.add_metric_thread(**args)
            edited.append(name)
        return CADResult(success=True, message="Modeled threads present on " + ", ".join(edited), data={"components": edited})

    def _placement_components(self):
        if not (self.active_document or "").lower().endswith(".sldasm"):
            raise ValueError("Activate the assembly containing the existing bolt and nut.")
        return self.active_document, {f["name"]: f for f in self.features if f["type"] == "Component"}

    def _thread_engaged(self, bolt, nut, spec, advance_mm=0):
        from ..agent.fasteners import thread_engaged
        axes = [c.get("rotation", (1,0,0, 0,1,0, 0,0,1))[6:9] for c in (bolt, nut)]
        offset = [b-n for b, n in zip(bolt["origin"], nut["origin"])]
        return thread_engaged(*axes, offset, spec, advance_mm)

    def _screw_mate(self, bolt, nut, spec, pitch, moving):
        from ..agent.fasteners import bolt_to_nut_offset
        source, anchor = (bolt, nut) if moving == "bolt" else (nut, bolt)
        refs = [f"Thread@{c['name']}" for c in (nut, bolt)]
        for mate in self.features:
            if mate["type"] == "Mate" and mate.get("kind") == "Screw" and mate["references"] == refs:
                if mate["pitch_mm"] != pitch:
                    raise ValueError("The existing screw mate has a different pitch.")
                source["fixed"], anchor["fixed"] = False, True
                return False
        if not self._thread_engaged(bolt, nut, spec):
            offset = bolt_to_nut_offset(**spec)
            self._place_fastener(source, anchor, -offset if moving == "bolt" else offset)
        source["fixed"], anchor["fixed"] = False, True
        self.features.append(dict(type="Mate", kind="Screw", name=f"Screw{len(self.features)+1}",
                                  references=refs, pitch_mm=pitch, right_handed=True))
        return True

    def _turn_fastener(self, bolt, nut, spec, pitch, turns, moving):
        from ..agent.fasteners import turned_pose
        if not self._thread_engaged(bolt, nut, spec, turns*pitch):
            raise ValueError(f"That turn would place the {moving} outside its usable thread travel.")
        source, axis_turns = (bolt, turns) if moving == "bolt" else (nut, -turns)
        rotation = source.get("rotation", (1,0,0, 0,1,0, 0,0,1))
        rotation, origin = turned_pose(rotation, source["origin"], axis_turns, pitch)
        source.update(rotation=tuple(rotation), origin=tuple(origin))

    def _place_fastener(self, source, target, offset_mm):
        rotation = target.get("rotation", (1,0,0, 0,1,0, 0,0,1))
        origin = tuple(v + axis * offset_mm for v, axis in zip(target["origin"], rotation[6:9]))
        if (source.get("rotation", (1,0,0, 0,1,0, 0,0,1)) == rotation
                and all(math.isclose(x, y, abs_tol=1e-6) for x, y in zip(origin, source["origin"]))):
            return False
        if any(f["type"] == "Mate" and any(ref.rpartition("@")[2] == source["name"] for ref in f["references"])
               for f in self.features):
            raise ValueError(f"Assembly mates control the position of {source['name']}.")
        source.update(origin=origin, rotation=rotation)
        return True

    def create_virtual_component(self, name, origin, features):
        if not (self.active_document or "").lower().endswith(".sldasm"):
            return CADResult(success=False, message="Activate an assembly before creating a component.")
        part = MockSolidWorksAdapter()
        part.new_part()
        part.draw_component_features(features)
        instance = f"{name}-{1 + sum(f.get('source') == name for f in self.features)}"
        self.features.append(dict(type="Component", name=instance, source=name, origin=tuple(origin),
                                  virtual=True, features=part.features))
        return CADResult(success=True, message=f"Created virtual component {instance}.", data={"instance": instance})

    def insert_component(self, file_path, x, y, z):
        if not (self.active_document or "").lower().endswith(".sldasm") or not self.component_file_exists(file_path):
            return CADResult(success=False, message="Provide an active assembly and a saved component.")
        stem = Path(file_path).stem
        count = sum(f.get("source") == stem for f in self.features) + 1
        name = f"{stem}-{count}"
        self.features.append(dict(type="Component", name=name, source=stem, path=file_path, origin=(x,y,z)))
        return CADResult(success=True, message=f"Inserted {name}.", data={"instance": name})

    def mate_planes(self, first, second):
        instances = {f["name"].casefold() for f in self.features if f["type"] == "Component"}
        for ref in (first, second):
            plane, sep, name = ref.rpartition("@")
            if not sep or not plane or name.casefold() not in instances:
                return CADResult(success=False, message=f"Unknown component plane '{ref}'.")
        self.features.append(dict(type="Mate", name=f"Mate{len(self.features)+1}", references=[first, second]))
        return CADResult(success=True, message=f"Mated {first} to {second}.")

    def save_model(self, file_path: str) -> CADResult:
        if self.active_document:
            self._saved_components.add(Path(file_path))
        return CADResult(success=True, message=f"[Simulated] Saved model to '{file_path}'.")

    def close_model(self) -> CADResult:
        self.active_document = None
        self.features.clear()
        return CADResult(success=True, message="Closed active document.")

    def select_plane(self, plane_name: str) -> CADResult:
        return CADResult(success=True, message=f"Selected plane '{plane_name}'.", data={"plane": plane_name})

    def create_sketch(self, plane_or_face: str = "Front Plane") -> CADResult:
        if not self.active_document:
            self.new_part()
        sketch_name = f"Sketch{len([f for f in self.features if 'Sketch' in f['name']]) + 1}"
        self.current_sketch = {
            "name": sketch_name,
            "plane": plane_or_face,
            "entities": [],
        }
        return CADResult(success=True, message=f"Started sketch '{sketch_name}' on '{plane_or_face}'.")

    def exit_sketch(self) -> CADResult:
        if self.current_sketch:
            self.features.append({
                "name": self.current_sketch["name"],
                "type": "ProfileFeature",
                "suppressed": False,
                "entities": self.current_sketch["entities"],
            })
            self.current_sketch = None
        return CADResult(success=True, message="Exited active sketch.")

    def sketch_rectangle(
        self, x1: float, y1: float, x2: float, y2: float, center_based: bool = True
    ) -> CADResult:
        if not self.current_sketch:
            self.create_sketch()
        w = abs(x2 - x1) * 2 if center_based else abs(x2 - x1)
        h = abs(y2 - y1) * 2 if center_based else abs(y2 - y1)
        self.current_sketch["entities"].append({"type": "rectangle", "w": w, "h": h})
        self.bounding_box[0] = max(self.bounding_box[0], w)
        self.bounding_box[1] = max(self.bounding_box[1], h)
        return CADResult(success=True, message=f"Drawn rectangle ({w} x {h} mm).")

    def sketch_circle(self, xc: float, yc: float, radius: float) -> CADResult:
        if not self.current_sketch:
            self.create_sketch()
        self.current_sketch["entities"].append({"type": "circle", "xc": xc, "yc": yc, "r": radius})
        dia = radius * 2
        self.bounding_box[0] = max(self.bounding_box[0], dia)
        self.bounding_box[1] = max(self.bounding_box[1], dia)
        return CADResult(success=True, message=f"Drawn circle (Radius: {radius} mm).")

    def sketch_line(self, x1: float, y1: float, x2: float, y2: float, is_centerline: bool = False) -> CADResult:
        if not self.current_sketch:
            self.create_sketch()
        self.current_sketch["entities"].append({
            "type": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "centerline": is_centerline
        })
        return CADResult(success=True, message=f"Drawn {'centerline' if is_centerline else 'line'}.")

    def sketch_arc(self, start, end, through) -> CADResult:
        if not self.current_sketch:
            return CADResult(success=False, message="No active sketch.")
        self.current_sketch["entities"].append(dict(type="arc", start=start, end=end, through=through))
        return CADResult(success=True, message="Created three-point arc.")

    def sweep_twisted_profile(self, width, twist_radians) -> CADResult:
        if not self.current_sketch:
            return CADResult(success=False, message="No active profile.")
        self.exit_sketch()
        self.features.append(dict(name="HelicalSweep", type="Sweep", depth=width, twist_radians=twist_radians))
        self.bounding_box[2] = width
        return CADResult(success=True, message="Simulated a twisted sweep.")

    def sketch_polygon(
        self, xc: float, yc: float, radius: float, sides: int = 6, inscribed: bool = True
    ) -> CADResult:
        if not self.current_sketch:
            self.create_sketch()
        self.current_sketch["entities"].append({"type": "polygon", "sides": sides, "radius": radius})
        return CADResult(success=True, message=f"Drawn {sides}-sided polygon.")

    def sketch_slot(
        self, x1: float, y1: float, x2: float, y2: float, width: float
    ) -> CADResult:
        if not self.current_sketch:
            self.create_sketch()
        self.current_sketch["entities"].append({"type": "slot", "width": width})
        return CADResult(success=True, message=f"Drawn slot (width {width} mm).")

    def feature_extrude_boss(
        self, depth: float, mid_plane: bool = False, draft_angle: float = 0.0
    ) -> CADResult:
        feat_name = f"Boss-Extrude{len([f for f in self.features if 'Boss' in f['name']]) + 1}"
        if self.current_sketch:
            self._extrusion_profiles[feat_name] = self.current_sketch["entities"]
        self.features.append({"name": feat_name, "type": "Extrusion", "suppressed": False, "depth": depth})
        self.bounding_box[2] += depth
        self.volume_mm3 += max(100.0, self.bounding_box[0] * self.bounding_box[1] * depth)
        self.surface_area_mm2 += 2 * (self.bounding_box[0] * self.bounding_box[1] + self.bounding_box[0] * depth + self.bounding_box[1] * depth)
        return CADResult(
            success=True,
            message=f"Created extrusion '{feat_name}' with depth {depth} mm.",
            feature_name=feat_name,
        )

    def resize_gear(self, num_teeth=None, outer_diameter=None):
        candidates = []
        for i, feature in enumerate(self.features):
            sweep = feature["type"] == "Sweep"
            if sweep and i and self.features[i - 1]["type"] == "ProfileFeature":
                entities = self.features[i - 1]["entities"]
            elif feature["type"] == "Extrusion":
                entities = self._extrusion_profiles.get(feature["name"], [])
            else:
                continue
            edges = [(entity, ((entity["x1"], entity["y1"]), (entity["x2"], entity["y2"])))
                     for entity in entities if entity["type"] == "line" and not entity["centerline"]]
            plan = plan_resize([edge for _, edge in edges], sweep, num_teeth, outer_diameter)
            if plan:
                candidates.append((feature, entities, edges, plan))
        if len(candidates) != 1:
            return CADResult(success=False, message=UNRECOGNIZED if not candidates else "The active part contains multiple gears.")
        feature, entities, edges, plan = candidates[0]
        original = {id(entity) for entity, edge in edges if edge_key(*edge) in plan.old_edges}
        retained = [entity for entity in entities if id(entity) not in original]
        if any(entity["type"] == "circle" and entity["r"] >= plan.root_radius for entity in retained):
            return CADResult(success=False, message="The bore reaches the resized tooth roots.")
        profile = [dict(type="line", x1=plan.points[i-1][0], y1=plan.points[i-1][1],
                        x2=x, y2=y, centerline=False) for i, (x, y) in enumerate(plan.points)]
        entities[:] = profile + retained
        if feature["type"] == "Sweep":
            feature["twist_radians"] *= plan.twist_ratio
        self.bounding_box[:2] = [plan.diameter, plan.diameter]
        return plan.result()

    def feature_extrude_cut(
        self, depth: float, through_all: bool = False, flip_dir: bool = False
    ) -> CADResult:
        feat_name = f"Cut-Extrude{len([f for f in self.features if 'Cut' in f['name']]) + 1}"
        self.features.append({"name": feat_name, "type": "Cut", "suppressed": False, "depth": depth})
        self.volume_mm3 = max(10.0, self.volume_mm3 - 500.0)
        return CADResult(success=True, message=f"Created cut-extrusion '{feat_name}'.", feature_name=feat_name)

    def feature_revolve_boss(
        self, angle_degrees: float = 360.0, reverse_dir: bool = False
    ) -> CADResult:
        feat_name = f"Revolve{len([f for f in self.features if 'Revolve' in f['name']]) + 1}"
        self.features.append({"name": feat_name, "type": "Revolve", "suppressed": False})
        self.volume_mm3 += 5000.0
        return CADResult(success=True, message=f"Created revolve boss '{feat_name}'.", feature_name=feat_name)

    def feature_revolve_cut(self, angle_degrees: float = 360.0) -> CADResult:
        feat_name = f"Revolve-Cut{len([f for f in self.features if 'Revolve-Cut' in f['name']]) + 1}"
        self.features.append({"name": feat_name, "type": "RevolveCut", "suppressed": False})
        return CADResult(success=True, message=f"Created revolve cut '{feat_name}'.", feature_name=feat_name)

    def feature_fillet(self, radius: float, edge_or_all: str = "all") -> CADResult:
        feat_name = f"Fillet{len([f for f in self.features if 'Fillet' in f['name']]) + 1}"
        self.features.append({"name": feat_name, "type": "Fillet", "suppressed": False, "radius": radius})
        return CADResult(success=True, message=f"Applied {radius} mm fillet '{feat_name}'.", feature_name=feat_name)

    def feature_chamfer(self, distance: float, angle_degrees: float = 45.0) -> CADResult:
        feat_name = f"Chamfer{len([f for f in self.features if 'Chamfer' in f['name']]) + 1}"
        self.features.append({"name": feat_name, "type": "Chamfer", "suppressed": False, "distance": distance})
        return CADResult(success=True, message=f"Applied {distance} mm chamfer '{feat_name}'.", feature_name=feat_name)

    def feature_shell(self, thickness: float) -> CADResult:
        feat_name = f"Shell{len([f for f in self.features if 'Shell' in f['name']]) + 1}"
        self.features.append({"name": feat_name, "type": "Shell", "suppressed": False, "thickness": thickness})
        self.volume_mm3 = self.volume_mm3 * 0.35  # Hollowed out
        return CADResult(success=True, message=f"Applied shell '{feat_name}' ({thickness} mm).", feature_name=feat_name)

    def feature_linear_pattern(
        self, count_d1: int, spacing_d1: float, count_d2: int = 1, spacing_d2: float = 0.0, feature_name: Optional[str] = None
    ) -> CADResult:
        feat_name = f"LPattern{len([f for f in self.features if 'LPattern' in f['name']]) + 1}"
        self.features.append({"name": feat_name, "type": "LinearPattern", "suppressed": False})
        return CADResult(success=True, message=f"Created linear pattern '{feat_name}'.", feature_name=feat_name)

    def feature_circular_pattern(
        self, count: int, total_angle: float = 360.0, feature_name: Optional[str] = None
    ) -> CADResult:
        feat_name = f"CirPattern{len([f for f in self.features if 'CirPattern' in f['name']]) + 1}"
        self.features.append({"name": feat_name, "type": "CircularPattern", "suppressed": False})
        return CADResult(success=True, message=f"Created circular pattern '{feat_name}'.", feature_name=feat_name)

    def get_mass_properties(self) -> CADResult:
        vol_m3 = self.volume_mm3 / 1e9
        mass_kg = vol_m3 * self.density
        return CADResult(
            success=True,
            message=f"Mass: {mass_kg:.4f} kg, Volume: {self.volume_mm3:.2f} mm³, Area: {self.surface_area_mm2:.2f} mm².",
            data={
                "mass_kg": round(mass_kg, 4),
                "volume_mm3": round(self.volume_mm3, 2),
                "surface_area_mm2": round(self.surface_area_mm2, 2),
                "density_kg_m3": self.density,
                "material": self.material,
                "bounding_box_mm": [round(b, 2) for b in self.bounding_box],
            },
        )

    def get_feature_tree(self) -> CADResult:
        return CADResult(
            success=True,
            message=f"FeatureManager tree contains {len(self.features)} features.",
            data={"features": self.features, "count": len(self.features)},
        )

    def capture_viewport_image(self, output_path: Optional[str] = None) -> CADResult:
        temp_dir = Path(tempfile.gettempdir()) / "solidworks_previews"
        temp_dir.mkdir(parents=True, exist_ok=True)
        final_path = output_path or str(temp_dir / f"simulated_preview_{int(time.time())}.png")

        # Generate a neat isometric technical CAD wireframe preview rendering with Pillow
        img = Image.new("RGB", (800, 500), color=(240, 243, 246))
        draw = ImageDraw.Draw(img)

        # Draw grid
        for i in range(0, 800, 40):
            draw.line([(i, 0), (i, 500)], fill=(225, 230, 235), width=1)
        for j in range(0, 500, 40):
            draw.line([(0, j), (800, j)], fill=(225, 230, 235), width=1)

        # Draw 3D isometric bounding cube representation
        cx, cy = 400, 260
        scale = 1.8
        dx = max(30, min(150, int(self.bounding_box[0] * scale)))
        dy = max(20, min(100, int(self.bounding_box[1] * scale)))
        dz = max(20, min(90, int(self.bounding_box[2] * scale)))

        # Isometric projection points
        p_front = [
            (cx - dx, cy), (cx, cy + dy // 2), (cx + dx, cy), (cx, cy - dy // 2)
        ]
        p_top = [
            (cx - dx, cy - dz), (cx, cy + dy // 2 - dz), (cx + dx, cy - dz), (cx, cy - dy // 2 - dz)
        ]

        # Draw faces
        draw.polygon(p_top, fill=(180, 205, 230), outline=(50, 90, 140), width=2)
        draw.polygon([(cx - dx, cy), (cx, cy + dy // 2), (cx, cy + dy // 2 - dz), (cx - dx, cy - dz)],
                     fill=(140, 175, 210), outline=(50, 90, 140), width=2)
        draw.polygon([(cx, cy + dy // 2), (cx + dx, cy), (cx + dx, cy - dz), (cx, cy + dy // 2 - dz)],
                     fill=(160, 190, 220), outline=(50, 90, 140), width=2)

        # Text banner
        draw.text((20, 20), f"SOLIDWORKS SIMULATOR - ACTIVE MODEL: {self.active_document or 'Part1'}", fill=(40, 50, 60))
        draw.text((20, 40), f"Features: {len(self.features)} | Material: {self.material}", fill=(80, 90, 100))
        draw.text((20, 60), f"Size: {self.bounding_box[0]:.1f} x {self.bounding_box[1]:.1f} x {self.bounding_box[2]:.1f} mm", fill=(80, 90, 100))

        img.save(final_path, "PNG")
        return CADResult(success=True, message=f"Generated simulated viewport render to '{final_path}'.", data={"image_path": final_path})

    def set_material(self, material_name: str, database: str = "solidworks materials") -> CADResult:
        self.material = material_name
        if "aluminum" in material_name.lower():
            self.density = 2700.0
        elif "steel" in material_name.lower():
            self.density = 7850.0
        elif "brass" in material_name.lower():
            self.density = 8500.0
        return CADResult(success=True, message=f"Set material to '{material_name}'.")

    def rebuild(self) -> CADResult:
        return CADResult(success=True, message="Simulated model rebuild complete.")

    def execute_raw_python(self, code: str) -> CADResult:
        return CADResult(
            success=True,
            message="[Simulated] Python script executed cleanly in mock environment.",
            data={"simulated": True},
        )

    def has_active_document(self) -> bool:
        return self.active_document is not None

    def set_dimension(self, dimension_name: str, value_mm: float) -> CADResult:
        return CADResult(
            success=True,
            message=f"[Simulated] Set dimension '{dimension_name}' to {value_mm} mm.",
            data={"dimension": dimension_name, "value_mm": value_mm},
        )

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
        hole_name = f"Hole-Cut{len([f for f in self.features if 'Hole' in f['name']]) + 1}"
        self.features.append({"name": hole_name, "type": "HoleCut", "suppressed": False, "dia": diameter})
        self.volume_mm3 = max(10.0, self.volume_mm3 - (math.pi * (diameter / 2) ** 2 * (depth or 10.0)))
        return CADResult(
            success=True,
            message=f"[Simulated] Added Ø{diameter}mm hole '{hole_name}' at ({xc}, {yc}) mm.",
            feature_name=hole_name,
        )

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
        boss_name = f"Boss{len([f for f in self.features if 'Boss' in f['name']]) + 1}"
        self.features.append({"name": boss_name, "type": "Boss", "suppressed": False, "depth": depth})
        self.bounding_box[2] += depth
        return CADResult(
            success=True,
            message=f"[Simulated] Added {shape} boss feature '{boss_name}' ({dim1}x{dim2} mm, depth {depth} mm).",
            feature_name=boss_name,
        )

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
        pocket_name = f"Pocket{len([f for f in self.features if 'Pocket' in f['name']]) + 1}"
        self.features.append({"name": pocket_name, "type": "PocketCut", "suppressed": False, "depth": depth})
        return CADResult(
            success=True,
            message=f"[Simulated] Cut {shape} pocket '{pocket_name}' ({width}x{height} mm, depth {depth} mm).",
            feature_name=pocket_name,
        )
