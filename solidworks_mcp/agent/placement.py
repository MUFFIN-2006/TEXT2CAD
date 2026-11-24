"""Choose sketch-space locations for features on a known extrusion profile, in mm."""

from math import dist, hypot


FEATURES = {"add_hole", "add_cut_pocket", "add_boss_feature"}


def _diameter(step):
    args = step.args
    if step.operation == "add_hole":
        return args.get("diameter")
    width = args.get("width", args.get("dim1"))
    if args.get("shape") == "rectangle":
        height = args.get("height", args.get("dim2"))
        return hypot(width, height) if width and height else None
    return width


def _outline(step):
    args = step.args
    if step.operation == "sketch_closed_polyline":
        return args["points"]
    if step.operation == "sketch_rectangle":
        x, y, right, top = (args[k] for k in ("x1", "y1", "x2", "y2"))
        if args.get("center_based"):
            x, y = 2 * x - right, 2 * y - top
        return [(x, y), (right, y), (right, top), (x, top)]
    return None


def _edge_clearance(point, polygon):
    """Signed distance to the nearest edge, positive inside a simple polygon."""
    x, y = point
    inside = False
    nearest = float("inf")
    for i, (ax, ay) in enumerate(polygon):
        bx, by = polygon[i - 1]
        dx, dy = bx - ax, by - ay
        if dx == dy == 0:
            continue
        if (ay > y) != (by > y) and x < ax + (y - ay) * dx / dy:
            inside = not inside
        t = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
        nearest = min(nearest, hypot(x - ax - t * dx, y - ay - t * dy))
    return nearest if inside else -nearest


def _location(profile, radius, occupied):
    outline = _outline(profile)
    if outline:
        xs, ys = zip(*outline)
        left, right, bottom, top = min(xs), max(xs), min(ys), max(ys)
        def clearance(point):
            return _edge_clearance(point, outline)
    else:
        args = profile.args
        center = (args["xc"], args["yc"])
        outer = args["radius"]
        left, right = center[0] - outer, center[0] + outer
        bottom, top = center[1] - outer, center[1] + outer
        def clearance(point):
            return outer - dist(point, center)

    middle = ((left + right) / 2, (bottom + top) / 2)
    def free_space(point):
        return min([clearance(point)] + [dist(point, used) - r for used, r in occupied])

    if free_space(middle) > radius:
        return middle
    # For concavities or occupied centers, look for a point with clearance on every side.
    candidates = ((left + i * (right-left)/32, bottom + j * (top-bottom)/32)
                  for i in range(1, 32) for j in range(1, 32))
    best = max(candidates, key=lambda p: (free_space(p), -dist(p, middle)))
    if free_space(best) <= radius:
        raise ValueError("I couldn't fit that feature inside the outline with clearance. Try a smaller size or specify its location.")
    return best


def place_features(steps, previous=None):
    """Resolve omitted placements before asking questions or issuing CAD operations."""
    profile, plane, occupied = previous or (None, None, [])
    occupied = occupied.copy()
    for i, step in enumerate(steps):
        op, args = step.operation, step.args
        if op == "feature_extrude_boss" and i >= 2 and steps[i-2].operation == "create_sketch":
            sketch = steps[i-1]
            if sketch.operation in {"sketch_closed_polyline", "sketch_rectangle", "sketch_circle"}:
                plane = steps[i-2].args["plane_or_face"]
                profile, occupied = sketch, []
            continue
        if not profile:
            continue
        if op not in FEATURES:
            profile = None
            continue
        if args.setdefault("plane_or_face", plane) != plane:
            profile = None
            continue
        if op in {"add_hole", "add_cut_pocket"}:
            # The solid extends forward from its original sketch plane; the default cut points back.
            args["flip_dir"] = True
        if op == "add_hole":
            args.setdefault("through_all", True)
        diameter = _diameter(step)
        if step.auto_place or ("xc" not in args and "yc" not in args):
            step.auto_place = True
            if diameter:
                reserved = occupied.copy()
                for following in steps[i+1:]:
                    other = following.args
                    if following.operation not in FEATURES or other.get("plane_or_face", plane) != plane:
                        break
                    if not following.auto_place and "xc" in other and "yc" in other and _diameter(following):
                        reserved.append(((other["xc"], other["yc"]), _diameter(following) / 2))
                args["xc"], args["yc"] = _location(profile, diameter / 2, reserved)
        if diameter and "xc" in args and "yc" in args:
            occupied.append(((args["xc"], args["yc"]), diameter / 2))
    if profile:
        return profile, plane, occupied
