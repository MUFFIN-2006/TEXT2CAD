"""Build native metric Thread features on the axial rims of agent-generated fasteners."""

from math import ceil, isclose

from .base import CADResult
from .solidworks_com import _set_fixed, com_value


def _rim(model, radius, z, max_radius=None):
    bodies = model.GetBodies2(0, False) or ()
    if len(bodies) != 1:
        raise ValueError("The fastener must contain one solid body.")
    for edge in com_value(bodies[0], "GetEdges") or ():
        curve = com_value(edge, "GetCurve")
        if curve and com_value(curve, "IsCircle"):
            x, y, cz, _, _, nz, r = curve.CircleParams
            if (max(abs(x), abs(y), abs(cz - z/1000)) < 1e-7
                    and radius - 0.0001 <= r * 1000 <= (max_radius or radius) + 0.0001
                    and isclose(abs(nz), 1, abs_tol=1e-7)):
                return edge
    return None


def _volume(model):
    bodies = model.GetBodies2(0, False) or ()
    if len(bodies) != 1:
        raise ValueError("Expected a single solid fastener after rebuilding.")
    return bodies[0].GetMassProperties(1.0)[3]


def _cylindrical_face(component, radius_mm):
    model = com_value(component, "GetModelDoc2")
    faces = []
    for body in (model.GetBodies2(0, False) or ()) if model else ():
        for face in com_value(body, "GetFaces") or ():
            surface = com_value(face, "GetSurface")
            if com_value(surface, "IsCylinder"):
                x, y, _, _, _, nz, r = surface.CylinderParams
                if max(abs(x), abs(y)) < 1e-7 and isclose(abs(nz), 1, abs_tol=1e-7) and abs(r*1000-radius_mm) < .01:
                    faces.append(face)
    if faces:
        entity = component.GetCorrespondingEntity(max(faces, key=lambda face: com_value(face, "GetArea")))
        if entity:
            return entity
    raise ValueError(f"Could not resolve the thread's cylindrical face on {component.Name2}.")


def _existing_screw(assembly, names):
    group = com_value(assembly, "FirstFeature")
    while group and com_value(group, "GetTypeName2") != "MateGroup":
        group = com_value(group, "GetNextFeature")
    feature = com_value(group, "GetFirstSubFeature") if group else None
    while feature:
        if com_value(feature, "GetTypeName2") == "MateScrew":
            mate = com_value(feature, "GetSpecificFeature2")
            instances = {mate.MateEntity(i).ReferenceComponent.Name2 for i in range(com_value(mate, "GetMateEntityCount"))}
            if instances == names:
                return feature
        feature = com_value(feature, "GetNextSubFeature")


def _engaged(bolt_pose, nut_pose, spec, advance_mm=0):
    from ..agent.fasteners import thread_engaged
    delta = [1000*(b-n) for b, n in zip(bolt_pose[9:12], nut_pose[9:12])]
    return thread_engaged(bolt_pose[6:9], nut_pose[6:9], delta, spec, advance_mm)


def add_screw_mate(adapter, bolt, nut, spec, pitch, moving):
    from ..agent.fasteners import bolt_to_nut_offset
    assembly = adapter.current_model
    diameter = spec["diameter"]
    lead = pitch / 1000
    source, anchor = (bolt, nut) if moving == "bolt" else (nut, bolt)
    existing = _existing_screw(assembly, {bolt.Name2, nut.Name2})
    if existing:
        definition = com_value(existing, "GetDefinition")
        if com_value(existing, "IsSuppressed") or definition.RevolutionType != 1 or not isclose(definition.RevolutionVal, lead):
            raise ValueError(f"Inspect {existing.Name}. Its pitch or suppression prevents the requested motion.")
        if com_value(anchor, "IsFixed") and not com_value(source, "IsFixed"):
            return False
    components = (nut, bolt)
    fixed = [bool(com_value(c, "IsFixed")) for c in components]
    poses = [c.Transform2 for c in components]
    feature = None
    try:
        if not existing and not _engaged(poses[1].ArrayData, poses[0].ArrayData, spec):
            offset = bolt_to_nut_offset(**spec)
            adapter._place_fastener(source, anchor, -offset if moving == "bolt" else offset)
        _set_fixed(assembly, source, False)
        if len(com_value(anchor, "GetMates") or ()) <= (1 if existing else 0):
            _set_fixed(assembly, anchor, True)
        if existing:
            if not com_value(assembly, "EditRebuild3") or any(
                max(abs(x-y) for x, y in zip(c.Transform2.ArrayData[:13], p.ArrayData[:13])) > 1e-7
                for c, p in zip(components, poses)
            ):
                raise ValueError("The solver could not switch the moving component at its current position.")
            return False
        faces = [_cylindrical_face(nut, (diameter-pitch)/2), _cylindrical_face(bolt, diameter/2)]
        assembly.ClearSelection2(True)
        selection = com_value(assembly.SelectionManager, "CreateSelectData")
        selection.Mark = 1
        for i, face in enumerate(faces):
            if not face.Select4(bool(i), selection):
                raise ValueError("Could not select both thread cylinders for the screw mate.")
        data = assembly.CreateMateData(17)  # swMateSCREW
        data.RevolutionType = 1  # swDistancePerRevolution
        data.RevolutionVal = lead
        data.MateAlignment = 2  # swMateAlignCLOSEST
        data.Reverse = False
        feature = assembly.CreateMate(data)
        if not feature or not com_value(assembly, "EditRebuild3"):
            raise ValueError("SolidWorks could not solve the screw mate with the assembly's current constraints.")
        saved = com_value(feature, "GetDefinition")
        if com_value(feature, "GetTypeName2") != "MateScrew" or saved.RevolutionType != 1:
            raise ValueError("SolidWorks did not create a distance-per-revolution screw mate.")
        if not isclose(saved.RevolutionVal, lead):
            # Some releases initialize the created feature at the document's default lead.
            dimension = com_value(feature, "GetFirstDisplayDimension").GetDimension2(0)
            dimension.SystemValue = lead
            if not com_value(assembly, "EditRebuild3"):
                raise ValueError("SolidWorks could not rebuild the screw mate at the requested lead.")
            saved = com_value(feature, "GetDefinition")
        if not isclose(saved.RevolutionVal, lead):
            raise ValueError("SolidWorks did not retain the requested screw mate and pitch.")
    except Exception as error:
        try:
            if feature and not (feature.Select2(False, 0) and assembly.Extension.DeleteSelection2(0)):
                raise ValueError("Could not remove the incomplete mate.")
            for component, was_fixed, pose in zip(components, fixed, poses):
                if any(abs(x-y) > 1e-8 for x, y in zip(component.Transform2.ArrayData[:13], pose.ArrayData[:13])):
                    _set_fixed(assembly, component, False)
                    if not component.SetTransformAndSolve2(pose):
                        raise ValueError(f"Could not restore {component.Name2}.")
                _set_fixed(assembly, component, was_fixed)
        except Exception as rollback:
            raise ValueError(f"{error} Check the assembly before retrying. {rollback}") from error
        raise
    finally:
        assembly.ClearSelection2(True)
    return True


def turn_fastener(adapter, bolt, nut, spec, pitch, turns, moving):
    from ..agent.fasteners import turned_pose
    assembly = adapter.current_model
    source, held = (bolt, nut) if moving == "bolt" else (nut, bolt)
    original = source.Transform2
    held_pose = held.Transform2
    start, anchor = original.ArrayData, held_pose.ArrayData
    if not _engaged(bolt.Transform2.ArrayData, nut.Transform2.ArrayData, spec, turns*pitch):
        raise ValueError(f"That turn would place the {moving} outside its usable thread travel.")
    axis_turns = turns if moving == "bolt" else -turns
    steps = max(1, min(72, ceil(abs(turns)*12)))
    try:
        for i in range(1, steps+1):
            rotation, origin = turned_pose(start[:9], [v*1000 for v in start[9:12]], axis_turns*i/steps, pitch)
            pose = rotation + [v/1000 for v in origin] + list(start[12:])
            if not source.SetTransformAndSolve2(adapter._math_transform(pose)):
                raise ValueError(f"SolidWorks could not solve the {moving}'s threaded movement.")
            com_value(assembly, "GraphicsRedraw2")
        if (not com_value(assembly, "EditRebuild3")
                or max(abs(x-y) for x, y in zip(source.Transform2.ArrayData[:13], pose[:13])) > 1e-7
                or max(abs(x-y) for x, y in zip(held.Transform2.ArrayData[:13], anchor[:13])) > 1e-7):
            raise ValueError("The assembly solver did not retain the requested rotation and axial travel.")
    except Exception as error:
        if max(abs(x-y) for x, y in zip(held.Transform2.ArrayData[:13], anchor[:13])) > 1e-7:
            held.SetTransformAndSolve2(held_pose)
        if (not source.SetTransformAndSolve2(original) or not com_value(assembly, "EditRebuild3")
                or max(abs(x-y) for x, y in zip(source.Transform2.ArrayData[:13], start[:13])) > 1e-7
                or max(abs(x-y) for x, y in zip(held.Transform2.ArrayData[:13], anchor[:13])) > 1e-7):
            raise ValueError(f"{error} Check the fastener positions before retrying.") from error
        raise


def add_metric_thread(adapter, diameter, pitch, internal, depth, tip):
    model = adapter.current_model
    if not model or com_value(model, "GetType") != 1:
        raise ValueError("Activate the fastener part before threading it.")
    size = f"M{diameter:g}x{float(pitch)}"
    role = "Internal" if internal else "External"
    name = f"{size} {role} Thread"
    existing = model.FeatureByName(name)
    if existing:
        if com_value(existing, "GetTypeName2") != "SweepThread" or com_value(existing, "IsSuppressed"):
            raise ValueError(f"Inspect the existing feature named {name} before retrying.")
        return CADResult(success=True, message=f"{name} already exists.", feature_name=name)
    radius = (diameter - pitch if internal else diameter) / 2
    edge = _rim(model, radius, tip)
    if edge is None and internal and _rim(model, radius, tip, diameter / 2) is not None:
        # Legacy bores can snap to nearby hex vertices. Fill down to the tap-drill size.
        adapter.draw_component_features([
            {"operation": "create_sketch", "arguments": {"plane_or_face": "Front Plane"}},
            {"operation": "sketch_circle", "arguments": dict(xc=0, yc=0, radius=(diameter + pitch/4)/2)},
            {"operation": "sketch_circle", "arguments": dict(xc=0, yc=0, radius=radius)},
            {"operation": "feature_extrude_boss", "arguments": {"depth": depth}}])
        edge = _rim(model, radius, tip)
    if edge is None:
        raise ValueError(f"Could not identify the circular rim for {name} on this part.")
    before = _volume(model)
    manager = model.FeatureManager
    data = manager.CreateDefinition(87)  # swFmSweepThread
    com_value(data, "InitializeThreadData")
    data.Type = "Metric Tap" if internal else "Metric Die"
    data.Size = size
    data.ThreadMethod = 0  # swThreadMethod_Cut
    data.Edge = edge
    data.RightHanded = True
    data.EndCondition = 0  # swThreadEndCondition_Blind
    data.BlindDepth = depth / 1000
    data.TrimStartFace = True
    data.TrimEndFace = True
    feature = manager.CreateFeature(data)
    if not feature:
        raise ValueError(f"SolidWorks could not build {name}. Check the Metric Tap and Metric Die thread profiles.")
    if not com_value(model, "EditRebuild3") or _volume(model) >= before:
        raise ValueError(f"SolidWorks did not confirm a material-removing cut for {name}. Inspect the new feature.")
    feature.Name = name
    return CADResult(success=True, message=f"Modeled {name}.", feature_name=name, data={"pitch_mm": pitch})
