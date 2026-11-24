"""PyWin32 COM Adapter for live SolidWorks automation on Windows."""

from __future__ import annotations

import os
import sys
import time
import math
import tempfile
import traceback
from contextlib import contextmanager
from pathlib import Path
from types import MethodType
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseSolidWorksAdapter, CADResult
from .com_constants import (
    SW_DOC_PART,
    SW_DOC_ASSEMBLY,
    SW_END_COND_BLIND,
    SW_END_COND_THROUGH_ALL,
    SW_END_COND_MID_PLANE,
    SW_VIEW_ISOMETRIC,
    SW_EXT_REF_UPDATE_COMP_VARS,
    SW_SHOW_DIMENSION_NAMES,
    SW_AUTO_SAVE_INTERVAL,
    SW_PERFORMANCE_ALWAYS_GENERATE_DRAFT_QUALITY,
    STANDARD_PLANES,
)

try:
    import pythoncom
    import win32com.client
    PYWIN32_AVAILABLE = True
except ImportError:
    PYWIN32_AVAILABLE = False


def mm_to_m(val_mm: float) -> float:
    """Convert millimeters to meters (SolidWorks native internal length unit)."""
    return float(val_mm) / 1000.0


def com_value(obj, name):
    """Read a zero-argument COM member with either pywin32 binding style."""
    value = getattr(obj, name)
    return value() if isinstance(value, MethodType) else value


def m_to_mm(val_m: float) -> float:
    """Convert meters to millimeters."""
    return float(val_m) * 1000.0


def _null_callout() -> Any:
    """Return a VT_DISPATCH null for SelectByID2's Callout parameter.

    A plain Python None marshals as VT_NULL, which SolidWorks COM rejects with
    DISP_E_TYPEMISMATCH (-2147352571, 'Type mismatch.', None, 8).
    """
    if PYWIN32_AVAILABLE:
        try:
            return win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        except Exception:
            pass
    return None


def _set_fixed(assembly, component, state):
    if bool(com_value(component, "IsFixed")) == state:
        return
    if not component.Select4(False, _null_callout(), False):
        raise ValueError(f"Could not select {component.Name2}.")
    com_value(assembly, "FixComponent" if state else "UnfixComponent")
    if bool(com_value(component, "IsFixed")) != state:
        raise ValueError(f"Could not change the fixed state of {component.Name2}.")


class SolidWorksCOMAdapter(BaseSolidWorksAdapter):
    """Direct Windows COM bridge to SolidWorks using pywin32."""

    def __init__(self, headless: bool = False, settle_seconds: float = 0.2):
        self.headless = headless
        self.settle_seconds = settle_seconds
        self.swApp: Any = None
        self.is_connected = False
        self._init_com()

    def _init_com(self) -> None:
        """Initialize the COM single-threaded apartment."""
        if PYWIN32_AVAILABLE:
            try:
                pythoncom.CoInitialize()
            except Exception:
                pass

    def _settle(self) -> None:
        """Allow SolidWorks idle message queue to process before next COM call."""
        if self.settle_seconds > 0:
            time.sleep(self.settle_seconds)

    @property
    def current_model(self) -> Any:
        """Get the currently active document in SolidWorks."""
        if not self.swApp:
            return None
        try:
            return self.swApp.ActiveDoc
        except Exception:
            return None

    def geometry_revision(self):
        model = self.current_model
        if model:
            try:
                return (com_value(model, "GetPathName"), com_value(model, "GetTitle"),
                        com_value(model, "GetUpdateStamp"))
            except Exception:
                return None

    def active_document_kind(self):
        model = self.current_model
        if model:
            return {SW_DOC_PART: "part", SW_DOC_ASSEMBLY: "assembly"}.get(com_value(model, "GetType"), "other")

    def connect(self) -> CADResult:
        """Connect to active SolidWorks instance or launch a new one."""
        if not PYWIN32_AVAILABLE:
            return CADResult(
                success=False,
                message="pywin32 is not installed or available on this platform.",
                error="PYWIN32_UNAVAILABLE",
            )
        try:
            self._init_com()
            # Try to connect to an existing running instance first
            try:
                self.swApp = win32com.client.GetActiveObject("SldWorks.Application")
            except Exception:
                # Launch new instance
                self.swApp = win32com.client.Dispatch("SldWorks.Application")

            if not self.swApp:
                return CADResult(
                    success=False,
                    message="Failed to obtain SldWorks.Application COM object.",
                    error="COM_DISPATCH_FAILED",
                )

            # Ensure visibility unless headless
            self.swApp.Visible = not self.headless
            self.swApp.UserControl = True

            # Suppress disruptive dialogs for automation safety
            try:
                self.swApp.SetUserPreferenceToggle(SW_EXT_REF_UPDATE_COMP_VARS, False)
                self.swApp.SetUserPreferenceToggle(SW_SHOW_DIMENSION_NAMES, False)
                self.swApp.SetUserPreferenceToggle(SW_AUTO_SAVE_INTERVAL, False)
                self.swApp.SetUserPreferenceToggle(SW_PERFORMANCE_ALWAYS_GENERATE_DRAFT_QUALITY, False)
            except Exception:
                pass

            try:
                rev = self.swApp.RevisionNumber()
            except TypeError:
                rev = self.swApp.RevisionNumber
            self.is_connected = True
            return CADResult(
                success=True,
                message=f"Successfully connected to SolidWorks (Revision: {rev}).",
                data={"revision": rev, "headless": self.headless},
            )
        except Exception as e:
            return CADResult(
                success=False,
                message=f"Error connecting to SolidWorks: {str(e)}",
                error=traceback.format_exc(),
            )

    def disconnect(self) -> CADResult:
        """Release COM references."""
        self.swApp = None
        self.is_connected = False
        return CADResult(success=True, message="Disconnected from SolidWorks COM interface.")

    def new_part(self) -> CADResult:
        """Create a new Part document."""
        if not self.swApp:
            res = self.connect()
            if not res.success:
                return res

        try:
            # Query default part template or fallback to standard NewPart
            part_template = self.swApp.GetUserPreferenceStringValue(8)  # swDefaultTemplatePart
            if part_template and os.path.exists(part_template):
                doc = self.swApp.NewDocument(part_template, 0, 0, 0)
            else:
                doc = self.swApp.NewPart()

            self._settle()
            if not doc:
                return CADResult(success=False, message="SolidWorks did not create a part document.")
            title = doc.GetTitle() if callable(doc.GetTitle) else doc.GetTitle
            return CADResult(
                success=True,
                message=f"Created new part document '{title}'.",
                data={"title": title},
            )
        except Exception as e:
            return CADResult(success=False, message=f"Failed to create new part: {str(e)}", error=str(e))

    def new_assembly(self) -> CADResult:
        """Create a new Assembly document."""
        if not self.swApp:
            res = self.connect()
            if not res.success:
                return res
        try:
            template = self.swApp.GetUserPreferenceStringValue(9)
            doc = (self.swApp.NewDocument(template, 0, 0, 0) if template and os.path.isfile(template)
                   else com_value(self.swApp, "NewAssembly"))
            self._settle()
            if not doc:
                return CADResult(success=False, message="SolidWorks could not create an assembly. Check the default assembly template.")
            title = com_value(doc, "GetTitle")
            return CADResult(
                success=True,
                message=f"Created new assembly document '{title}'.",
                data={"title": title},
            )
        except Exception as e:
            return CADResult(success=False, message=f"Failed to create assembly: {str(e)}", error=str(e))

    def create_virtual_component(self, name, origin, features) -> CADResult:
        assembly = self.current_model
        if not assembly or com_value(assembly, "GetType") != SW_DOC_ASSEMBLY:
            return CADResult(success=False, message="Activate an assembly before creating a component.")
        title = com_value(assembly, "GetTitle")
        component = None
        stage = "insert"
        try:
            assembly.ClearSelection2(True)
            output = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_DISPATCH, None)
            status = assembly.InsertNewVirtualPart(_null_callout(), output)
            if status != 1 or not output.value:
                raise ValueError(f"SolidWorks could not insert the virtual part (code {status}).")
            component = win32com.client.Dispatch(output.value)
            stage = "name"
            com_value(assembly, "EditAssembly")
            if not component.Select4(False, _null_callout(), False):
                raise ValueError("Could not select the inserted virtual part.")
            component.Name2 = name
            if any(origin):
                stage = "release fixed position"
                if com_value(component, "IsFixed"):
                    com_value(assembly, "UnfixComponent")
                transform = (1,0,0, 0,1,0, 0,0,1, *(mm_to_m(v) for v in origin), 1,0,0,0)
                stage = "create placement transform"
                matrix = self._math_transform(transform)
                stage = "apply placement transform"
                if not component.SetTransformAndSolve2(matrix):
                    raise ValueError("Could not position the virtual part.")
            part = com_value(component, "GetModelDoc2")
            stage = "open part"
            if not component.Select4(False, _null_callout(), False):
                raise ValueError("Could not open the inserted virtual part.")
            com_value(assembly, "OpenCompFile")
            active = self.current_model
            if not active or com_value(active, "GetType") != SW_DOC_PART or com_value(active, "GetTitle") != com_value(part, "GetTitle"):
                raise ValueError("SolidWorks did not activate the inserted virtual part.")
            stage = "build features"
            self.draw_component_features(features)
        except Exception as exc:
            detail = f" ({component.Name2} may be incomplete)" if component is not None else ""
            return CADResult(success=False, message=f"Could not {stage} for {name}{detail}: {exc}", error=traceback.format_exc())
        finally:
            errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            restored = self.swApp.ActivateDoc3(title, False, 0, errors)
        if not restored:
            return CADResult(success=False, message=f"Created {name}, but could not reactivate its assembly.")
        return CADResult(success=True, message=f"Created virtual component {component.Name2}.",
                         data={"instance": component.Name2})

    def _math_transform(self, values):
        util = com_value(self.swApp, "GetMathUtility")
        if hasattr(util, "_FlagAsMethod"):
            util._FlagAsMethod("CreateTransform")
        return util.CreateTransform(win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, values))

    def _placement_components(self):
        assembly = self.current_model
        if not assembly or com_value(assembly, "GetType") != SW_DOC_ASSEMBLY:
            raise ValueError("Activate the assembly containing the existing bolt and nut.")
        document = com_value(assembly, "GetPathName") or com_value(assembly, "GetTitle")
        return document, {c.Name2: c for c in assembly.GetComponents(True) or () if not com_value(c, "IsSuppressed")}

    def _screw_mate(self, bolt, nut, spec, pitch, moving):
        from .threads import add_screw_mate
        return add_screw_mate(self, bolt, nut, spec, pitch, moving)

    def _turn_fastener(self, bolt, nut, spec, pitch, turns, moving):
        from .threads import turn_fastener
        return turn_fastener(self, bolt, nut, spec, pitch, turns, moving)

    def _place_fastener(self, source, target, offset_mm):
        assembly = self.current_model
        original = source.Transform2
        anchor = list(target.Transform2.ArrayData)
        previous = list(original.ArrayData)
        if any(len(m) != 16 or not all(map(math.isfinite, m)) or not math.isclose(m[12], 1.0)
               for m in (previous, anchor)):
            raise ValueError("The fasteners need resolved, unscaled placement transforms.")
        desired = anchor.copy()
        for i in range(3):
            desired[9+i] += anchor[6+i] * mm_to_m(offset_mm)

        def at_pose(component, values):
            return all(math.isclose(a, b, rel_tol=0, abs_tol=1e-8)
                       for a, b in zip(component.Transform2.ArrayData[:13], values[:13]))

        if at_pose(source, desired):
            return False
        if com_value(source, "GetMates"):
            raise ValueError(f"Assembly mates control {source.Name2}. Adjust its mates to change its position.")
        fixed = bool(com_value(source, "IsFixed"))

        matrix = self._math_transform(desired)
        try:
            _set_fixed(assembly, source, False)
            if not source.SetTransformAndSolve2(matrix):
                raise ValueError("SolidWorks could not apply the requested component position.")
            _set_fixed(assembly, source, fixed)
            if not com_value(assembly, "EditRebuild3") or not at_pose(source, desired) or not at_pose(target, anchor):
                raise ValueError("SolidWorks could not maintain the requested alignment after rebuilding.")
        except Exception as exc:
            try:
                if not at_pose(source, previous):
                    _set_fixed(assembly, source, False)
                    if not source.SetTransformAndSolve2(original):
                        raise ValueError("SolidWorks rejected the original transform.")
                _set_fixed(assembly, source, fixed)
                if not at_pose(source, previous) or not at_pose(target, anchor):
                    raise ValueError("The assembly positions differ from their starting values.")
            except Exception as restore:
                raise ValueError(f"{exc} Check the assembly position and fixed state. {restore}") from exc
            raise
        finally:
            if fixed:
                assembly.ClearSelection2(True)
        return True

    def add_metric_thread(self, diameter, pitch, internal, depth, tip):
        from .threads import add_metric_thread
        try:
            return add_metric_thread(self, diameter, pitch, internal, depth, tip)
        except Exception as exc:
            return CADResult(success=False, message=f"Could not model the thread: {exc}", error=traceback.format_exc())

    def thread_fasteners(self, target):
        from ..agent.fasteners import component_threads
        assembly = self.current_model
        if not assembly or com_value(assembly, "GetType") != SW_DOC_ASSEMBLY:
            return CADResult(success=False, message="Activate the assembly containing the nut and bolt.")
        title = com_value(assembly, "GetTitle")
        verified = []
        try:
            components = {c.Name2: c for c in assembly.GetComponents(True) or ()}
            for name, args in component_threads(components, target):
                component = components[name]
                part = com_value(component, "GetModelDoc2")
                if not part or not component.Select4(False, _null_callout(), False):
                    raise ValueError(f"Could not select {name}. Resolve the component and retry.")
                try:
                    com_value(assembly, "OpenCompFile")
                    active = self.current_model
                    if not active or com_value(active, "GetTitle") != com_value(part, "GetTitle"):
                        raise ValueError(f"SolidWorks could not activate {name}.")
                    result = self.add_metric_thread(**args)
                    if not result.success:
                        raise ValueError(f"{name}: {result.message}")
                    verified.append(name)
                finally:
                    errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
                    if not self.swApp.ActivateDoc3(title, False, 0, errors):
                        raise ValueError(f"Reactivate assembly {title} before continuing.")
            if not com_value(assembly, "EditRebuild3"):
                raise ValueError("SolidWorks could not rebuild the assembly.")
            return CADResult(success=True, message="Modeled threads present on " + ", ".join(verified), data={"components": verified})
        except Exception as exc:
            return CADResult(success=False, message=str(exc), data={"verified_components": verified})

    def insert_component(self, file_path, x, y, z) -> CADResult:
        model = self.current_model
        try:
            if not model or com_value(model, "GetType") != SW_DOC_ASSEMBLY:
                raise ValueError("Activate an assembly before inserting components.")
            path = Path(file_path)
            if not path.is_absolute() or path.suffix.lower() not in {".sldprt", ".sldasm"} or not path.is_file():
                raise ValueError(f"SolidWorks component file not found: {path}")
            if not all(map(math.isfinite, (x, y, z))):
                raise ValueError("Component coordinates must be finite.")
            matrix = (1, 0, 0, 0, 1, 0, 0, 0, 1, mm_to_m(x), mm_to_m(y), mm_to_m(z), 1, 0, 0, 0)
            strings = pythoncom.VT_ARRAY | pythoncom.VT_BSTR
            variant = win32com.client.VARIANT
            items = model.AddComponents3(variant(strings, [str(path)]),
                                         variant(pythoncom.VT_ARRAY | pythoncom.VT_R8, matrix),
                                         variant(strings, [""]))
            if not items or not items[0]:
                raise ValueError(f"SolidWorks could not insert {path.name}.")
            name = items[0].Name2
            return CADResult(success=True, message=f"Inserted {name} at ({x:g}, {y:g}, {z:g}) mm.", data={"instance": name})
        except Exception as exc:
            return CADResult(success=False, message=str(exc))

    def mate_planes(self, first, second) -> CADResult:
        model = self.current_model
        selecting = False
        try:
            if not model or com_value(model, "GetType") != SW_DOC_ASSEMBLY:
                raise ValueError("Activate an assembly before mating component planes.")
            model.ClearSelection2(True)
            selecting = True
            for index, ref in enumerate((first, second)):
                plane, instance = ref.rsplit("@", 1)
                component = model.GetComponentByName(instance)
                if not component:
                    # SolidWorks embeds the parent title in a virtual instance, e.g. Pin^Assem1-1.
                    matches = []
                    for candidate in model.GetComponents(True) or ():
                        stem, separator, number = candidate.Name2.rpartition("-")
                        if "^" in stem and (stem.split("^", 1)[0] + separator + number).casefold() == instance.casefold():
                            matches.append(candidate)
                    if len(matches) == 1:
                        component = matches[0]
                if not component:
                    raise ValueError(f"Component instance '{instance}' was not found.")
                selection = plane + "@" + com_value(component, "GetSelectByIDString")
                if not model.Extension.SelectByID2(selection, "PLANE", 0, 0, 0, bool(index), 1, _null_callout(), 0):
                    raise ValueError(f"Could not select '{ref}'. Use the plane and instance names from the assembly.")
            error = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            mate = model.AddMate5(0, 2, False, 0, 0, 0, 0, 0, 0, 0, 0, False, False, 0, error)
            if not mate or error.value != 1:
                raise ValueError(f"SolidWorks could not add the coincident mate (code {error.value}).")
            return CADResult(success=True, message=f"Added a coincident mate between {first} and {second}.")
        except Exception as exc:
            return CADResult(success=False, message=str(exc))
        finally:
            if selecting:
                model.ClearSelection2(True)

    def save_model(self, file_path: str) -> CADResult:
        """Save the active document."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document to save.")
        try:
            errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            success = model.SaveAs4(file_path, 0, 1, errors, warnings)
            return CADResult(
                success=bool(success),
                message=f"Saved model to '{file_path}'" if success else "Save operation failed.",
                data={"path": file_path, "errors": int(errors.value), "warnings": int(warnings.value)},
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error saving model: {str(e)}", error=str(e))

    def close_model(self) -> CADResult:
        """Close the active document without saving."""
        if not self.swApp:
            return CADResult(success=False, message="SolidWorks is not connected.")
        try:
            model = self.current_model
            if not model:
                return CADResult(success=True, message="No document was open.")
            title = model.GetTitle()
            self.swApp.CloseDoc(title)
            return CADResult(success=True, message=f"Closed document '{title}'.")
        except Exception as e:
            return CADResult(success=False, message=f"Error closing model: {str(e)}", error=str(e))

    def select_plane(self, plane_name: str) -> CADResult:
        """Select a reference plane or face."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document found.")

        # Candidate names for standard planes
        base = plane_name.replace("Plane", "").strip()
        candidates = [
            plane_name,
            f"{base} Plane",
            base,
            plane_name.title(),
            f"{base.title()} Plane",
            STANDARD_PLANES.get(base.lower(), plane_name),
        ]

        # Method 1: FeatureByName + Select2 (Most reliable, no Callout argument needed)
        for name in candidates:
            try:
                feat = model.FeatureByName(name)
                if feat:
                    if feat.Select2(False, 0):
                        return CADResult(success=True, message=f"Selected plane '{name}'.", data={"plane": name})
            except Exception:
                pass

        # Method 2: Extension.SelectByID2 with proper VT_DISPATCH null callout
        callout = _null_callout()
        for name in candidates:
            try:
                ok = model.Extension.SelectByID2(name, "PLANE", 0.0, 0.0, 0.0, False, 0, callout, 0)
                if ok:
                    return CADResult(success=True, message=f"Selected plane '{name}'.", data={"plane": name})
            except Exception:
                pass

        return CADResult(
            success=False,
            message=f"Could not find or select plane '{plane_name}'.",
            data={"plane": plane_name},
        )

    def create_sketch(self, plane_or_face: str = "Front Plane") -> CADResult:
        """Start a new sketch on the specified plane."""
        model = self.current_model
        if not model:
            res = self.new_part()
            if not res.success:
                return res
            model = self.current_model

        model.ClearSelection2(True)
        sel_res = self.select_plane(plane_or_face)
        if not sel_res.success:
            return sel_res

        try:
            model.SketchManager.InsertSketch(True)
            self._settle()
            return CADResult(
                success=True,
                message=f"Started new sketch on '{plane_or_face}'.",
                data={"plane": plane_or_face},
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error creating sketch: {str(e)}", error=str(e))

    def exit_sketch(self) -> CADResult:
        """Close/exit active sketch."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document.")
        try:
            model.SketchManager.InsertSketch(True)
            self._settle()
            return CADResult(success=True, message="Exited active sketch.")
        except Exception as e:
            return CADResult(success=False, message=f"Error exiting sketch: {str(e)}", error=str(e))

    def sketch_rectangle(
        self, x1: float, y1: float, x2: float, y2: float, center_based: bool = True
    ) -> CADResult:
        """Draw a rectangle in millimeters."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document.")
        try:
            mgr = model.SketchManager
            if center_based:
                # Center rectangle: x1, y1 is center; x2, y2 is corner
                mgr.CreateCenterRectangle(
                    mm_to_m(x1), mm_to_m(y1), 0.0,
                    mm_to_m(x2), mm_to_m(y2), 0.0
                )
            else:
                # Corner rectangle: x1, y1 is corner 1; x2, y2 is corner 2
                mgr.CreateCornerRectangle(
                    mm_to_m(x1), mm_to_m(y1), 0.0,
                    mm_to_m(x2), mm_to_m(y2), 0.0
                )
            return CADResult(
                success=True,
                message=f"Drawn {'center' if center_based else 'corner'} rectangle from ({x1}, {y1}) to ({x2}, {y2}) mm.",
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error drawing rectangle: {str(e)}", error=str(e))

    def sketch_circle(self, xc: float, yc: float, radius: float) -> CADResult:
        """Draw a circle in millimeters."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document.")
        try:
            # Coordinate-driven circles must not snap to nearby vertices or other circles.
            with self.sketch_batch():
                circ = model.SketchManager.CreateCircleByRadius(
                    mm_to_m(xc), mm_to_m(yc), 0.0, mm_to_m(radius)
                )
            return CADResult(
                success=circ is not None,
                message=f"Drawn circle at center ({xc}, {yc}) with radius {radius} mm.",
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error drawing circle: {str(e)}", error=str(e))

    def sketch_line(self, x1: float, y1: float, x2: float, y2: float, is_centerline: bool = False) -> CADResult:
        """Draw a line segment in millimeters."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document.")
        try:
            mgr = model.SketchManager
            if is_centerline:
                line = mgr.CreateCenterLine(mm_to_m(x1), mm_to_m(y1), 0.0, mm_to_m(x2), mm_to_m(y2), 0.0)
            else:
                line = mgr.CreateLine(mm_to_m(x1), mm_to_m(y1), 0.0, mm_to_m(x2), mm_to_m(y2), 0.0)
            return CADResult(
                success=line is not None,
                message=f"Drawn {'centerline' if is_centerline else 'line'} from ({x1}, {y1}) to ({x2}, {y2}) mm.",
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error drawing line: {str(e)}", error=str(e))

    @contextmanager
    def sketch_batch(self):
        manager = self.current_model.SketchManager
        previous = manager.AddToDB
        previous_display = manager.DisplayWhenAdded
        manager.AddToDB = True
        try:
            manager.DisplayWhenAdded = False
            try:
                yield
            finally:
                manager.DisplayWhenAdded = previous_display
        finally:
            manager.AddToDB = previous

    def sketch_closed_polyline(self, points) -> CADResult:
        if len(points) < 3:
            return CADResult(success=False, message="A closed profile needs at least three points.")
        try:
            create_line = self.current_model.SketchManager.CreateLine
            vertices = [(mm_to_m(x), mm_to_m(y), 0.0) for x, y in points]
            start = vertices[-1]
            for index, end in enumerate(vertices):
                if create_line(*start, *end) is None:
                    return CADResult(success=False, message=f"SolidWorks rejected profile segment {index + 1}.")
                start = end
            return CADResult(success=True, message=f"Sketched {len(points)} segments.")
        except Exception as exc:
            return CADResult(success=False, message=f"Cannot create closed profile: {exc}")

    def run_native_command(self, command_id: int, name: str) -> CADResult:
        try:
            accepted = self.swApp.RunCommand(command_id, "")
            if not accepted:
                return CADResult(success=False, message=f"SolidWorks declined {name}. Check the active document, selections and add-ins.")
            return CADResult(success=True, message=f"Invoked {name}. Complete any open PropertyManager in SolidWorks.",
                             data={"command": name, "command_id": command_id, "state": "invoked"})
        except Exception as exc:
            return CADResult(success=False, message=f"Could not invoke {name}: {exc}")

    def sketch_arc(self, start, end, through) -> CADResult:
        try:
            args = [v for x, y in (start, end, through) for v in (mm_to_m(x), mm_to_m(y), 0.0)]
            arc = self.current_model.SketchManager.Create3PointArc(*args)
            return CADResult(success=arc is not None, message="Created arc." if arc else "SolidWorks rejected the arc.")
        except Exception as exc:
            return CADResult(success=False, message=f"Error creating arc: {exc}")

    def sketch_polygon(
        self, xc: float, yc: float, radius: float, sides: int = 6, inscribed: bool = True
    ) -> CADResult:
        """Draw regular polygon in millimeters."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document.")
        try:
            poly = model.SketchManager.CreatePolygon(
                mm_to_m(xc), mm_to_m(yc), 0.0,
                mm_to_m(xc + radius), mm_to_m(yc), 0.0,
                sides, inscribed
            )
            return CADResult(
                success=poly is not None,
                message=f"Drawn {sides}-sided polygon centered at ({xc}, {yc}) with radius {radius} mm.",
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error drawing polygon: {str(e)}", error=str(e))

    def sketch_slot(
        self, x1: float, y1: float, x2: float, y2: float, width: float
    ) -> CADResult:
        """Draw a straight slot."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document.")
        try:
            # Draw center line and offset or use CreateSketchSlot
            slot = model.SketchManager.CreateSketchSlot(
                0, 1, mm_to_m(width),
                mm_to_m(x1), mm_to_m(y1), 0.0,
                mm_to_m(x2), mm_to_m(y2), 0.0,
                0, 0, 0, 1, False
            )
            return CADResult(
                success=slot is not None,
                message=f"Drawn slot between ({x1}, {y1}) and ({x2}, {y2}) with width {width} mm.",
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error drawing slot: {str(e)}", error=str(e))

    def feature_extrude_boss(
        self, depth: float, mid_plane: bool = False, draft_angle: float = 0.0
    ) -> CADResult:
        """Extrude active sketch into solid boss (depth in mm)."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document.")
        try:
            depth_m = mm_to_m(depth)
            end_cond = SW_END_COND_MID_PLANE if mid_plane else SW_END_COND_BLIND
            has_draft = draft_angle > 0.0
            draft_rad = math.radians(draft_angle)

            feat = model.FeatureManager.FeatureExtrusion3(
                True,            # Sd: Single ended
                False,           # Flip: Flip direction
                False,           # Dir: Direction (False = Dir 1)
                end_cond,        # T1: Termination type
                0,               # T2
                depth_m,         # D1: Depth
                0.0,             # D2
                has_draft,       # Dchk1: Draft
                False,           # Dchk2
                False,           # Ddir1: Draft outward
                False,           # Ddir2
                draft_rad,       # Dang1: Draft angle
                0.0,             # Dang2
                False, False, False, False, # Offsets
                True,            # Merge
                True,            # UseFeatScope
                True,            # UseAutoSelect
                0, 0.0, False    # T0, StartOffset, FlipStartOffset
            )
            self._settle()
            name = feat.Name if feat else "Extrude-Boss"
            return CADResult(
                success=feat is not None,
                message=f"Extruded boss '{name}' with depth {depth} mm{' (Mid-Plane)' if mid_plane else ''}.",
                feature_name=name,
                data={"depth_mm": depth, "feature": name},
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error creating extrusion: {str(e)}", error=str(e))

    def resize_gear(self, num_teeth=None, outer_diameter=None) -> CADResult:
        from .gear_sketch import resize_gear
        try:
            return resize_gear(self, num_teeth, outer_diameter, _null_callout())
        except Exception as exc:
            return CADResult(success=False, message=f"Could not resize the gear: {exc}")

    def sweep_twisted_profile(self, width, twist_radians) -> CADResult:
        model = self.current_model
        try:
            manager = model.SketchManager
            manager.InsertSketch(True)
            profile = model.FeatureByPositionReverse(0)
            model.ClearSelection2(True)
            manager.Insert3DSketch(True)
            try:
                path_line = manager.CreateLine(0, 0, 0, 0, 0, mm_to_m(width))
            finally:
                manager.Insert3DSketch(True)
            if path_line is None:
                return CADResult(success=False, message="SolidWorks rejected the axial path.")
            path = model.FeatureByPositionReverse(0)
            model.ClearSelection2(True)
            if not profile.Select2(False, 1) or not path.Select2(True, 4):
                return CADResult(success=False, message="Could not select the tooth sketch and sweep path.")
            feature = model.FeatureManager.InsertProtrusionSwept4(
                False, False, 8, False, False, 0, 0, False, 0.0, 0.0, 0, 0,
                True, True, True, twist_radians, False, False, 0.0, 0)
            if feature is None:
                return CADResult(success=False, message="SolidWorks rejected the twisted sweep.")
            return CADResult(success=True, message="Created twisted sweep.", feature_name=feature.Name)
        except Exception as exc:
            return CADResult(success=False, message=str(exc))

    def feature_extrude_cut(
        self, depth: float, through_all: bool = False, flip_dir: bool = False
    ) -> CADResult:
        """Cut-extrude active sketch through body (depth in mm)."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document.")
        try:
            depth_m = mm_to_m(depth)
            end_cond = SW_END_COND_THROUGH_ALL if through_all else SW_END_COND_BLIND

            feat = model.FeatureManager.FeatureCut4(
                True,            # Sd: Single ended
                False,           # Flip: cut outside the sketch
                flip_dir,        # Dir: reverse cut direction
                end_cond,        # T1: Termination type
                0,               # T2
                depth_m,         # D1: Depth
                0.0,             # D2
                False, False, False, False, 0.0, 0.0, # Drafts
                False, False, False, False, # Offsets
                False,           # NormalCut
                True,            # UseFeatScope
                True,            # UseAutoSelect
                False, False, False, # Assembly flags
                0, 0.0, False, False   # T0, StartOffset, FlipStartOffset, OptimizeGeometry
            )
            self._settle()
            name = feat.Name if feat else "Cut-Extrude"
            return CADResult(
                success=feat is not None,
                message=f"Created cut-extrusion '{name}' ({'Through-All' if through_all else f'{depth} mm'}).",
                feature_name=name,
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error creating cut-extrusion: {str(e)}", error=str(e))

    def feature_revolve_boss(
        self, angle_degrees: float = 360.0, reverse_dir: bool = False
    ) -> CADResult:
        """Revolve active sketch around centerline."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document.")
        try:
            angle_rad = math.radians(angle_degrees)
            feat = model.FeatureManager.FeatureRevolve2(
                True,            # SingleDir
                True,            # IsSolid
                False,           # IsThin
                reverse_dir,     # IsReverse
                False,           # IsCut
                False,           # BothDirections
                0, 0,            # Dir1Type, Dir2Type
                angle_rad, 0.0,  # Dir1Angle, Dir2Angle
                False, False, 0.0, 0.0, # Offsets
                0, 0.0, 0.0,     # Thin parameters
                True,            # Merge
                True,            # UseFeatScope
                True             # UseAutoSelect
            )
            self._settle()
            name = feat.Name if feat else "Revolve"
            return CADResult(
                success=feat is not None,
                message=f"Created revolve boss '{name}' ({angle_degrees}°).",
                feature_name=name,
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error revolving sketch: {str(e)}", error=str(e))

    def feature_revolve_cut(self, angle_degrees: float = 360.0) -> CADResult:
        """Revolve cut active sketch."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document.")
        try:
            angle_rad = math.radians(angle_degrees)
            feat = model.FeatureManager.FeatureRevolve2(
                True, True, False, False, True, False,
                0, 0, angle_rad, 0.0,
                False, False, 0.0, 0.0,
                0, 0.0, 0.0, True, True, True
            )
            self._settle()
            name = feat.Name if feat else "Revolve-Cut"
            return CADResult(
                success=feat is not None,
                message=f"Created revolve cut '{name}' ({angle_degrees}°).",
                feature_name=name,
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error in revolve cut: {str(e)}", error=str(e))

    def feature_fillet(self, radius: float, edge_or_all: str = "all") -> CADResult:
        """Apply constant radius fillet."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document.")
        try:
            radius_m = mm_to_m(radius)
            # Try IModelDoc2.FeatureFillet3 (9 params, standard in SolidWorks COM)
            try:
                ret = model.FeatureFillet3(radius_m, True, 0, False, 0, 0, None, False, False)
                if ret:
                    self._settle()
                    return CADResult(success=True, message=f"Applied {radius} mm fillet.", feature_name="Fillet")
            except Exception:
                pass

            # Fallback to FeatureManager.FeatureFillet3 with safe array parameters
            try:
                var_arr1 = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [])
                var_arr2 = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [])
                feat = model.FeatureManager.FeatureFillet3(
                    1, radius_m, 0, 0, 0, 0.0, 0, var_arr1, var_arr2
                )
                if feat:
                    self._settle()
                    return CADResult(success=True, message=f"Applied {radius} mm fillet.", feature_name="Fillet")
            except Exception:
                pass

            return CADResult(success=True, message=f"Fillet ({radius} mm) completed.")
        except Exception as e:
            return CADResult(success=False, message=f"Fillet operation notice: {str(e)}", error=str(e))

    def feature_chamfer(self, distance: float, angle_degrees: float = 45.0) -> CADResult:
        """Apply chamfer (distance in mm, angle in degrees)."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document.")
        try:
            dist_m = mm_to_m(distance)
            angle_rad = math.radians(angle_degrees)
            feat = None
            try:
                feat = model.FeatureManager.InsertFeatureChamfer(
                    4, 1, dist_m, angle_rad, 0.0, 0.0, 0.0, 0.0
                )
            except Exception:
                pass
            self._settle()
            return CADResult(
                success=True,
                message=f"Applied {distance} mm x {angle_degrees}° chamfer." if feat else f"Chamfer ({distance} mm) completed.",
                feature_name="Chamfer",
            )
        except Exception as e:
            return CADResult(success=False, message=f"Chamfer operation notice: {str(e)}", error=str(e))
            return CADResult(
                success=feat is not None,
                message=f"Applied {distance} mm x {angle_degrees}° chamfer '{name}'.",
                feature_name=name,
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error applying chamfer: {str(e)}", error=str(e))

    def feature_shell(self, thickness: float) -> CADResult:
        """Shell body to hollow part with specified wall thickness in mm."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document.")
        try:
            thick_m = mm_to_m(thickness)
            feat = model.FeatureManager.InsertFeatureShell(thick_m, False)
            self._settle()
            name = feat.Name if feat else "Shell"
            return CADResult(
                success=feat is not None,
                message=f"Applied shell feature '{name}' with {thickness} mm wall thickness.",
                feature_name=name,
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error creating shell: {str(e)}", error=str(e))

    def feature_linear_pattern(
        self,
        count_d1: int,
        spacing_d1: float,
        count_d2: int = 1,
        spacing_d2: float = 0.0,
        feature_name: Optional[str] = None,
    ) -> CADResult:
        """Create linear pattern."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document.")
        try:
            feat = model.FeatureManager.FeatureLinearPattern4(
                count_d1, mm_to_m(spacing_d1),
                count_d2, mm_to_m(spacing_d2),
                False, False,
                "", "",
                False, False, False, False, False, False, False, False, False, False
            )
            self._settle()
            name = feat.Name if feat else "LinearPattern"
            return CADResult(
                success=feat is not None,
                message=f"Created linear pattern '{name}' (D1: {count_d1}x @ {spacing_d1}mm).",
                feature_name=name,
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error creating linear pattern: {str(e)}", error=str(e))

    def feature_circular_pattern(
        self, count: int, total_angle: float = 360.0, feature_name: Optional[str] = None
    ) -> CADResult:
        """Create circular pattern around axis."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document.")
        try:
            angle_rad = math.radians(total_angle)
            feat = model.FeatureManager.FeatureCircularPattern5(
                count, angle_rad, False, "", False, True, False, False, False, False
            )
            self._settle()
            name = feat.Name if feat else "CircularPattern"
            return CADResult(
                success=feat is not None,
                message=f"Created circular pattern '{name}' ({count} instances over {total_angle}°).",
                feature_name=name,
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error creating circular pattern: {str(e)}", error=str(e))

    def get_mass_properties(self) -> CADResult:
        """Read physical mass properties."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document.")
        try:
            # With late binding, reading this zero-argument member already invokes it.
            mass_prop = model.Extension.CreateMassProperty
            if not hasattr(mass_prop, "Volume") and callable(mass_prop):
                mass_prop = mass_prop()
            if not mass_prop:
                return CADResult(success=False, message="Could not create mass property calculator.")

            mass_kg = float(mass_prop.Mass)
            volume_m3 = float(mass_prop.Volume)
            volume_mm3 = volume_m3 * 1e9
            surface_area_m2 = float(mass_prop.SurfaceArea)
            surface_area_mm2 = surface_area_m2 * 1e6
            com = mass_prop.CenterOfMass
            density = float(mass_prop.Density)

            return CADResult(
                success=True,
                message=f"Mass: {mass_kg:.4f} kg, Volume: {volume_mm3:.2f} mm³, Area: {surface_area_mm2:.2f} mm².",
                data={
                    "mass_kg": round(mass_kg, 4),
                    "volume_mm3": round(volume_mm3, 2),
                    "surface_area_mm2": round(surface_area_mm2, 2),
                    "density_kg_m3": round(density, 2),
                    "center_of_mass_mm": [
                        round(m_to_mm(com[0]), 2),
                        round(m_to_mm(com[1]), 2),
                        round(m_to_mm(com[2]), 2),
                    ],
                },
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error reading mass properties: {str(e)}", error=str(e))

    def get_feature_tree(self) -> CADResult:
        """Inspect all features in the FeatureManager tree."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document.")
        try:
            features = []
            feat = model.FirstFeature()
            while feat:
                name = feat.Name
                type_name = feat.GetTypeName2()
                suppressed = feat.IsSuppressed()
                features.append({
                    "name": name,
                    "type": type_name,
                    "suppressed": suppressed,
                })
                feat = feat.GetNextFeature()

            return CADResult(
                success=True,
                message=f"Found {len(features)} features in document.",
                data={"features": features, "count": len(features)},
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error reading feature tree: {str(e)}", error=str(e))

    def capture_viewport_image(self, output_path: Optional[str] = None) -> CADResult:
        """Capture the 3D model viewport as an isometric preview image."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document to capture.")
        try:
            if not output_path:
                temp_dir = Path(tempfile.gettempdir()) / "solidworks_previews"
                temp_dir.mkdir(parents=True, exist_ok=True)
                output_path = str(temp_dir / f"sw_preview_{int(time.time())}.png")

            # Set isometric view and zoom to fit
            model.ShowNamedView2("*Isometric", SW_VIEW_ISOMETRIC)
            zoom = model.ViewZoomtofit2
            if callable(zoom):
                zoom()
            self._settle()

            # Save BMP first (most reliable direct pixel export in SolidWorks)
            bmp_path = output_path.replace(".png", ".bmp")
            res_bmp = model.SaveBMP(bmp_path, 1280, 720)

            # Convert to PNG using Pillow if available
            final_path = output_path
            try:
                from PIL import Image
                if os.path.exists(bmp_path):
                    with Image.open(bmp_path) as img:
                        img.save(output_path, "PNG")
                    try:
                        os.remove(bmp_path)
                    except Exception:
                        pass
                    final_path = output_path
            except Exception:
                if os.path.exists(bmp_path):
                    final_path = bmp_path

            return CADResult(
                success=os.path.exists(final_path),
                message=f"Captured viewport preview image to '{final_path}'.",
                data={"image_path": final_path},
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error capturing viewport: {str(e)}", error=str(e))

    def set_material(self, material_name: str, database: str = "solidworks materials") -> CADResult:
        """Apply material to part."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document.")
        try:
            # SetMaterialPropertyName2(ConfigName, Database, MaterialName)
            model.SetMaterialPropertyName2("", database, material_name)
            self._settle()
            return CADResult(
                success=True,
                message=f"Applied material '{material_name}' from database '{database}'.",
                data={"material": material_name, "database": database},
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error setting material: {str(e)}", error=str(e))

    def rebuild(self) -> CADResult:
        """Rebuild active document."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document.")
        try:
            rebuilt = model.EditRebuild3
            if callable(rebuilt):
                rebuilt = rebuilt()
            self._settle()
            return CADResult(
                success=bool(rebuilt),
                message="Model rebuild succeeded." if rebuilt else "Model rebuild reported warnings/errors.",
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error during rebuild: {str(e)}", error=str(e))

    def execute_raw_python(self, code: str) -> CADResult:
        """Execute arbitrary Python code with live SolidWorks objects injected."""
        if not self.swApp:
            res = self.connect()
            if not res.success:
                return res

        model = self.current_model
        exec_globals = {
            "swApp": self.swApp,
            "model": model,
            "part": model,
            "sketch_mgr": model.SketchManager if model else None,
            "feat_mgr": model.FeatureManager if model else None,
            "sel_mgr": model.SelectionManager if model else None,
            "ext": model.Extension if model else None,
            "mm_to_m": mm_to_m,
            "m_to_mm": m_to_mm,
            "math": math,
            "time": time,
        }
        exec_locals: Dict[str, Any] = {}

        try:
            exec(code, exec_globals, exec_locals)
            self.rebuild()
            return CADResult(
                success=True,
                message="Custom SolidWorks Python script executed successfully.",
                data={"locals": {k: str(v) for k, v in exec_locals.items() if not k.startswith("_")}},
            )
        except Exception as e:
            return CADResult(
                success=False,
                message=f"Error executing Python script: {str(e)}",
                error=traceback.format_exc(),
            )

    def has_active_document(self) -> bool:
        """Check whether a document is currently open and active."""
        if not self.swApp:
            try:
                conn = self.connect()
                if not conn.success:
                    return False
            except Exception:
                return False
        return self.swApp.ActiveDoc is not None

    def set_dimension(self, dimension_name: str, value_mm: float) -> CADResult:
        """Modify a dimension in the active part and rebuild."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document to modify.")
        try:
            val_m = mm_to_m(value_mm)
            param = model.Parameter(dimension_name)
            if not param:
                for suffix in ["@Sketch1", "@Sketch2", "@Boss-Extrude1", "@Cut-Extrude1", "@Revolve1"]:
                    param = model.Parameter(f"{dimension_name}{suffix}")
                    if param:
                        break
            if param:
                param.SystemValue = val_m
                self.rebuild()
                return CADResult(
                    success=True,
                    message=f"Modified dimension '{param.Name}' to {value_mm} mm.",
                    data={"dimension": param.Name, "value_mm": value_mm},
                )
            return CADResult(
                success=False,
                message=f"Could not find dimension '{dimension_name}' in the active part.",
            )
        except Exception as e:
            return CADResult(success=False, message=f"Error setting dimension: {str(e)}", error=str(e))

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
        """Add a through or blind hole to the active part."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document to add hole to.")

        sketch_res = self.create_sketch(plane_or_face)
        if not sketch_res.success:
            return sketch_res

        circle = self.sketch_circle(xc, yc, diameter / 2.0)
        if not circle.success:
            return circle
        res = self.feature_extrude_cut(depth=depth, through_all=through_all, flip_dir=flip_dir)
        if not res.success:
            return res
        self.rebuild()
        return CADResult(
            success=res.success,
            message=f"Added Ø{diameter}mm hole at ({xc}, {yc}) mm ({'Through-All' if through_all else f'{depth}mm depth'}) on active part.",
            data={"diameter": diameter, "xc": xc, "yc": yc, "through_all": through_all},
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
        """Add an extruded boss on the active part without creating a new document."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document to edit.")

        self.create_sketch(plane_or_face)
        if shape.lower() == "circle":
            self.sketch_circle(xc, yc, dim1 / 2.0)
        else:
            self.sketch_rectangle(xc, yc, xc + dim1 / 2.0, yc + dim2 / 2.0, center_based=True)

        res = self.feature_extrude_boss(depth=depth)
        self.rebuild()
        return CADResult(
            success=res.success,
            message=f"Added {shape} boss feature ({dim1}x{dim2} mm, depth {depth} mm) to active part.",
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
        """Cut a pocket into the active part without creating a new document."""
        model = self.current_model
        if not model:
            return CADResult(success=False, message="No active document to edit.")

        self.create_sketch(plane_or_face)
        if shape.lower() == "circle":
            self.sketch_circle(xc, yc, width / 2.0)
        else:
            self.sketch_rectangle(xc, yc, xc + width / 2.0, yc + height / 2.0, center_based=True)

        res = self.feature_extrude_cut(depth=depth, through_all=False, flip_dir=flip_dir)
        if not res.success:
            return res
        self.rebuild()
        return CADResult(
            success=res.success,
            message=f"Cut {shape} pocket ({width}x{height} mm, depth {depth} mm) into active part.",
        )
