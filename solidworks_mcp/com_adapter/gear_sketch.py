"""Edit the existing SolidWorks sketch that drives a generated gear."""

from .base import CADResult
from .solidworks_com import com_value as _get
from ..parametric.gear_edit import UNRECOGNIZED, plan_resize


def _candidates(model, num_teeth, outer_diameter):
    feature = _get(model, "FirstFeature")
    while feature:
        kind = _get(feature, "GetTypeName2")
        if kind in {"Boss", "Extrusion", "ICE", "Sweep"}:
            child = _get(feature, "GetFirstSubFeature")
            while child:
                if _get(child, "GetTypeName2") == "ProfileFeature":
                    sketch = _get(child, "GetSpecificFeature2")
                    # GetLines2 returns six style values followed by two XYZ points in metres.
                    raw = sketch.GetLines2(1) or ()
                    lines = [((raw[i+6]*1000, raw[i+7]*1000), (raw[i+9]*1000, raw[i+10]*1000))
                             for i in range(0, len(raw), 12)]
                    plan = plan_resize(lines, kind == "Sweep", num_teeth, outer_diameter)
                    if plan:
                        yield feature, child, kind, plan
                child = _get(child, "GetNextSubFeature")
        feature = _get(feature, "GetNextFeature")


def resize_gear(adapter, num_teeth, outer_diameter, null_dispatch):
    import pythoncom
    from win32com.client import VARIANT

    model = adapter.current_model
    if not model or _get(model, "GetType") != 1:
        return CADResult(success=False, message="Activate the gear part in SolidWorks first.")
    manager = model.SketchManager
    if manager.ActiveSketch:
        return CADResult(success=False, message="Exit the open sketch, then repeat the gear edit.")
    candidates = list(_candidates(model, num_teeth, outer_diameter))
    if len(candidates) != 1:
        return CADResult(success=False, message=UNRECOGNIZED if not candidates else "The active part contains multiple gears.")
    feature, sketch_feature, kind, plan = candidates[0]
    ext = model.Extension
    editing = modified = False
    _get(ext, "StartRecordingUndoObject")
    try:
        if not sketch_feature.Select2(False, 0):
            raise ValueError("SolidWorks could not select the gear sketch.")
        _get(model, "EditSketch")
        sketch = manager.ActiveSketch
        if not sketch:
            raise ValueError("SolidWorks could not open the gear sketch.")
        editing = True
        contours = [c for c in (_get(sketch, "GetSketchContours") or ())
                    if _get(c, "IsClosed") and _get(c, "GetSketchSegmentsCount") == len(plan.old_edges)]
        if len(contours) != 1:
            raise ValueError("Could not isolate the closed tooth outline from the bore.")
        segments = _get(contours[0], "GetSketchSegments")
        selected = ext.MultiSelect2(VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, segments), False, null_dispatch)
        if selected != len(segments):
            raise ValueError("SolidWorks could not select the complete tooth outline.")
        if not ext.DeleteSelection2(0):
            raise ValueError("SolidWorks could not replace the tooth outline.")
        modified = True
        with adapter.sketch_batch():
            result = adapter.sketch_closed_polyline(plan.points)
        if not result.success:
            raise ValueError(result.message)
        manager.InsertSketch(True)
        editing = False
        if kind == "Sweep":
            definition = _get(feature, "GetDefinition")
            if not definition.AccessSelections(model, null_dispatch):
                raise ValueError("Could not access the helical sweep.")
            try:
                definition.SetTwistAngle(_get(definition, "GetTwistAngle") * plan.twist_ratio)
            except Exception:
                _get(definition, "ReleaseSelectionAccess")
                raise
            if not feature.ModifyDefinition(definition, model, null_dispatch):
                raise ValueError("Could not update the helical sweep.")
        if not _get(model, "EditRebuild3"):
            raise ValueError("SolidWorks could not rebuild the resized gear.")
    except Exception as exc:
        if editing and manager.ActiveSketch:
            manager.InsertSketch(True)
        recorded = ext.FinishRecordingUndoObject2("Resize gear", False)
        if modified:
            if not recorded:
                raise RuntimeError(f"{exc} Check the gear sketch; SolidWorks could not record the edit for undo.") from exc
            model.EditUndo2(1)
        raise
    ext.FinishRecordingUndoObject2("Resize gear", False)
    return plan.result()
