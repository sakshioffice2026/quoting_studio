"""
Run from project root:
    python threshold_jamb_assembly_test.py [width_mm] [height_mm]

Standalone check ONLY — NOT wired into frame_assembly.py / model3d.py /
model3d_freecad.py.

Builds threshold + left_jamb + right_jamb + head in ONE shared
coordinate space (world X=width, Y=exterior<->interior depth,
Z=floor-up height). Both jambs snap their bottom face onto the
threshold's Z-max, flush at X=0.0 (left) / X=W (right), rear edge
flush with the threshold's rear upstand, then boolean-cut against
the threshold to notch out any overlap. The head spans the full
width and rests on top of both jambs. All four grouped into a
single FreeCAD Part.makeCompound() (OpenCASCADE TopoDS_Compound)
and exported as ONE combined STEP file.

NOT included yet (separate item): inward-facing jamb rotation.

Output: output/threshold_jamb_assembly.step
"""
import sys
import os
import json
import subprocess
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.threshold_geometry import (
    get_profile_points_normalised as threshold_pts,
)
from app.services.jamb_geometry import (
    get_profile_points_normalised as jamb_pts,
)

# ---------------------------------------------------------------------------
# Head-profile extraction — reads coordinates directly from the DXF file.
# Replaces the hardcoded HEAD_PROFILE_POINTS array for _build_head().
# ---------------------------------------------------------------------------
_HEAD_DXF = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "app", "cad_sections", "cad_sections", "head.dxf",
)


def _head_pts_from_dxf(dxf_path: str = _HEAD_DXF) -> list:
    """
    Extract the 2D wire vertices from the head-profile DXF and return them
    as normalised (u, v) pairs ready for _build_head(head_pts_2d, W).

    Coordinate convention (preserved from existing assembly logic):
        u — local X in DXF (across profile, ~90 mm)  → world Z via _z(u)
        v — local Y in DXF (depth through wall, ~35 mm) → world Y via _y(v)

    The file declares $INSUNITS=1 (inches) but its coordinates are in mm —
    the same mismatch documented in head_geometry.py.  Raw coords are used
    as-is (no ×25.4 scaling) to match HEAD_PROFILE_POINTS exactly.

    Returns [] and prints a warning on any file/parse error so the caller
    can fall back gracefully.
    """
    import math

    if not dxf_path or not os.path.isfile(dxf_path):
        print(f"WARNING: head profile DXF not found: {dxf_path!r}")
        return []

    try:
        with open(dxf_path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError as exc:
        print(f"WARNING: could not read head profile DXF: {exc}")
        return []

    if not content.strip():
        print(f"WARNING: head profile DXF is empty: {dxf_path!r}")
        return []

    # --- minimal inline DXF tag reader (no Flask / app imports needed) ------
    def _tags(text):
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        i = 0
        while i < len(lines) - 1:
            raw = lines[i].strip()
            val = lines[i + 1].strip()
            i += 2
            try:
                yield int(raw), val
            except ValueError:
                pass

    def _lwpolyline_pts(tag_list):
        coords, bulges, closed = [], {}, False
        idx = -1
        for code, val in tag_list:
            try:
                if code == 10:
                    idx += 1
                    coords.append([float(val), None])
                elif code == 20 and coords and coords[-1][1] is None:
                    coords[-1][1] = float(val)
                elif code == 42:
                    bulges[idx] = float(val)
                elif code == 70:
                    closed = bool(int(float(val)) & 1)
            except ValueError:
                pass
        pts = [(c[0], c[1]) for c in coords if c[1] is not None]
        if not pts:
            return [], False

        # Expand bulge arcs so the polygon matches the real profile shape
        def _bulge_arc(p1, p2, b, n=12):
            x1, y1 = p1; x2, y2 = p2
            d = math.hypot(x2 - x1, y2 - y1)
            if d < 1e-10 or abs(b) < 1e-9:
                return [p2]
            theta = 4.0 * math.atan(abs(b))
            r = d / (2.0 * math.sin(theta / 2.0))
            dc = math.sqrt(max(0.0, r * r - (d / 2.0) ** 2))
            alpha = math.atan2(y2 - y1, x2 - x1)
            mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            sign = 1 if b > 0 else -1
            cx = mx + sign * dc * math.sin(alpha)
            cy = my - sign * dc * math.cos(alpha)
            sa = math.atan2(y1 - cy, x1 - cx)
            ea = math.atan2(y2 - cy, x2 - cx)
            if b > 0:
                if ea >= sa:
                    ea -= 2.0 * math.pi
            else:
                if ea <= sa:
                    ea += 2.0 * math.pi
            segs = max(n, int(abs(b) * 24))
            return [(cx + r * math.cos(sa + (ea - sa) * k / segs),
                     cy + r * math.sin(sa + (ea - sa) * k / segs))
                    for k in range(1, segs + 1)]

        expanded = [pts[0]]
        n = len(pts)
        last = n if closed else n - 1
        for i in range(last):
            b = bulges.get(i, 0.0)
            if abs(b) > 1e-9:
                expanded.extend(_bulge_arc(pts[i], pts[(i + 1) % n], b))
            else:
                expanded.append(pts[(i + 1) % n])
        return expanded, closed

    # --- scan entities for the first closed LWPOLYLINE on a non-annotation layer
    _EXCLUDED = ('dim', 'dimension', 'text', 'annot', 'note', 'centre',
                 'center', 'hatch', 'hidden', 'leader', 'title', 'border')

    current_type = None
    current_layer = None
    current_tags = []
    result_pts = []

    for code, val in _tags(content):
        if code == 0:
            if (current_type == "LWPOLYLINE"
                    and not any(s in (current_layer or "").lower() for s in _EXCLUDED)):
                pts, closed = _lwpolyline_pts(current_tags)
                if closed and len(pts) >= 3:
                    result_pts = pts
                    break           # first valid closed polyline is the profile
            current_type = val
            current_layer = None
            current_tags = []
        else:
            if code == 8:
                current_layer = val
            if current_type == "LWPOLYLINE":
                current_tags.append((code, val))

    if not result_pts:
        print(f"WARNING: no closed LWPOLYLINE found in head profile DXF: {dxf_path!r}")
        return []

    # Normalise to (0, 0) origin — same pattern as get_profile_points_normalised()
    xs = [p[0] for p in result_pts]
    ys = [p[1] for p in result_pts]
    min_x, min_y = min(xs), min(ys)
    return [(round(x - min_x, 3), round(y - min_y, 3)) for x, y in result_pts]


OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def _find_freecad():
    from app.services.model3d_freecad import _find_freecad as ff
    return ff()


def export_combined_step(width_mm: float, height_mm: float, step_path: str):
    freecad = _find_freecad()
    if not freecad:
        print("FreeCAD not found — skipping STEP export. "
              "Set FREECAD_CMD env var or install FreeCAD.")
        return False

    head_pts_2d = _head_pts_from_dxf()
    if not head_pts_2d:
        print("WARNING: head profile extraction failed — "
              "falling back to jamb profile for head member.")
        head_pts_2d = jamb_pts()

    params_path = os.path.join(tempfile.gettempdir(), "threshold_jamb_params.json")
    with open(params_path, "w", encoding="utf-8") as f:
        json.dump({
            "threshold_pts": threshold_pts(),
            "jamb_pts": jamb_pts(),
            "head_pts": head_pts_2d,
            "width_mm": width_mm,
            "height_mm": height_mm,
            "step_path": step_path,
        }, f)

    script = r"""
import FreeCAD as App, Part, json, traceback, sys
V = App.Vector

def _build_threshold(pts_2d, W):
    # Same pitch + drainage-orientation logic as
    # door_threshold_extrude_test.py: world-Y = local-x (ext<->int
    # footprint), world-Z = local-y (floor-up height).
    x_vals = [float(x) for x, _ in pts_2d]
    y_vals = [float(y) for _, y in pts_2d]
    x_mid = (min(x_vals) + max(x_vals)) / 2.0
    ramp_xs = [x for x in x_vals if x <= x_mid]
    dam_xs  = [x for x in x_vals if x > x_mid]
    ramp_avg = sum(ramp_xs) / len(ramp_xs) if ramp_xs else 0.0
    dam_avg  = sum(dam_xs) / len(dam_xs) if dam_xs else 0.0

    EXTERIOR_AT_Y_MIN = True
    x_extent = max(x_vals) - min(x_vals)
    currently_ramp_at_min = ramp_avg <= dam_avg
    needs_mirror = currently_ramp_at_min != EXTERIOR_AT_Y_MIN

    def _oriented_y(x):
        x0 = float(x) - min(x_vals)
        return (x_extent - x0) if needs_mirror else x0

    def _floor_up_z(y):
        return float(y) - min(y_vals)

    pts = [V(0.0, _oriented_y(x), _floor_up_z(y)) for x, y in pts_2d]
    pts.append(pts[0])
    wire = Part.makePolygon(pts)
    if not wire.isClosed():
        raise RuntimeError("threshold wire not closed")
    face = Part.Face(wire)
    if not face.isValid() or face.Area <= 1.0:
        raise RuntimeError(f"invalid threshold face, area={face.Area}")
    solid = face.extrude(V(W, 0.0, 0.0))
    if not solid.isValid() or solid.Volume <= 1.0:
        raise RuntimeError(f"invalid threshold extrude, volume={solid.Volume}")
    return solid

def _build_jamb(pts_2d, H):
    # plane='XY' (ITEM 1 fix): (u, v) -> V(u, v, 0), extrude +Z by H.
    pts = [V(float(u), float(v), 0.0) for u, v in pts_2d]
    pts.append(pts[0])
    wire = Part.makePolygon(pts)
    if not wire.isClosed():
        raise RuntimeError("jamb wire not closed")
    face = Part.Face(wire)
    if not face.isValid() or face.Area <= 1.0:
        raise RuntimeError(f"invalid jamb face, area={face.Area}")
    solid = face.extrude(V(0.0, 0.0, H))
    if not solid.isValid() or solid.Volume <= 1.0:
        raise RuntimeError(f"invalid jamb extrude, volume={solid.Volume}")
    return solid

def _build_head(head_pts_2d, W):
    # Cross-section in Y-Z plane, extruded along +X by W.
    # Local v (depth) is inverted so the channel faces downward (-Z).
    # Local u maps directly to world Z (height).
pts = [V(0.0, float(v), float(u)) for u, v in head_pts_2d]    pts.append(pts[0])
    wire = Part.makePolygon(pts)
    if not wire.isClosed():
        raise RuntimeError("head wire not closed")
    face = Part.Face(wire)
    if not face.isValid() or face.Area <= 1.0:
        raise RuntimeError(f"invalid head face, area={face.Area}")
    solid = face.extrude(V(W, 0.0, 0.0))
    if not solid.isValid() or solid.Volume <= 1.0:
        raise RuntimeError(f"invalid head extrude, volume={solid.Volume}")
    return solid

def _snap(solid, x=None, y=None, z=None):
    # Translate solid so its BoundBox satisfies the given target(s).
    # Each target is (edge, value), edge in ('min', 'max').
    bb = solid.BoundBox
    dx = dy = dz = 0.0
    if x is not None:
        edge, val = x
        cur = bb.XMin if edge == "min" else bb.XMax
        dx = val - cur
    if y is not None:
        edge, val = y
        cur = bb.YMin if edge == "min" else bb.YMax
        dy = val - cur
    if z is not None:
        edge, val = z
        cur = bb.ZMin if edge == "min" else bb.ZMax
        dz = val - cur
    solid.translate(V(dx, dy, dz))

try:
    data = json.load(open(r"__PARAMS_PATH__", encoding="utf-8"))
    threshold_pts_2d = data["threshold_pts"]
    jamb_pts_2d      = data["jamb_pts"]
    head_pts_2d      = data["head_pts"]
    W                = float(data["width_mm"])
    H                = float(data["height_mm"])
    step_path        = data["step_path"]

    threshold = _build_threshold(threshold_pts_2d, W)
    _snap(threshold, x=("min", 0.0), y=("min", 0.0), z=("min", 0.0))
    threshold_zmax = threshold.BoundBox.ZMax
    threshold_ymax = threshold.BoundBox.YMax

    def _place_jamb(x_target):
        jamb = _build_jamb(jamb_pts_2d, H)
        # Bottom face (Zmin) snaps to the threshold's highest point
        # (Zmax of the interior upstand), flush at the given X edge.
        _snap(jamb, x=x_target, z=("min", threshold_zmax))
        # Depth (Y): align the jamb's REAR edge (Ymax) flush with the
        # threshold's rear upstand edge (Ymax) instead of a front
        # (Ymin) reference.
        _snap(jamb, y=("max", threshold_ymax))
        # Boolean notch: cut threshold's volume out of the jamb
        # wherever they intersect (e.g. a jamb edge overhanging the
        # threshold's sloped ramp section). Always attempted — a
        # strict BoundBox overlap check can miss coincident/touching
        # geometry right at the joint.
        cut_result = jamb.cut(threshold)
        if cut_result.isValid() and cut_result.Volume > 1.0:
            return cut_result
        print("NOTE: jamb.cut(threshold) produced no valid change "
              "(no intersecting volume) — keeping uncut jamb.")
        return jamb

    left_jamb  = _place_jamb(("min", 0.0))
    right_jamb = _place_jamb(("max", W))
    jambs_zmax = max(left_jamb.BoundBox.ZMax, right_jamb.BoundBox.ZMax)
    jambs_ymin = min(left_jamb.BoundBox.YMin, right_jamb.BoundBox.YMin)

    head = _build_head(head_pts_2d, W)
    # X: flush at X=0 (left edge).
    _snap(head, x=("min", 0.0))
    h_bb = head.BoundBox
    # Y: head front face aligns with the jamb glazing channel plane.
    # channel_offset=9.45mm is the local-Y depth of the glass rebate
    # measured from jambs_ymin (jamb profile Y=0..9.45 is the channel).
    # Y: Align head channel depth flush with the jamb glazing channel
    # Align head YMin directly to the jamb interior reference (jambs_ymin)
    dy = jambs_ymin - h_bb.YMin

    # Z: Snap head bottom face (ZMin) directly onto the top of the jambs (jambs_zmax)
    dz = jambs_zmax - h_bb.ZMin
    head.translate(V(0.0, dy, dz))
    # Z: bottom edge of head rests directly on top of jambs, no gap.
    dz = jambs_zmax - h_bb.ZMin
    head.translate(V(0.0, dy, dz))

    doc = App.newDocument("ThresholdJambAssembly")
    o1 = doc.addObject("Part::Feature", "Threshold");  o1.Shape = threshold
    o2 = doc.addObject("Part::Feature", "LeftJamb");   o2.Shape = left_jamb
    o3 = doc.addObject("Part::Feature", "RightJamb");  o3.Shape = right_jamb
    o4 = doc.addObject("Part::Feature", "Head");       o4.Shape = head
    doc.recompute()

    compound = Part.makeCompound([threshold, left_jamb, right_jamb, head])
    compound.exportStep(step_path)

    bb = compound.BoundBox
    print(f"OK compound bbox=({bb.XLength:.2f},{bb.YLength:.2f},{bb.ZLength:.2f}) "
          f"XMin={bb.XMin:.2f} XMax={bb.XMax:.2f} "
          f"YMin={bb.YMin:.2f} YMax={bb.YMax:.2f} "
          f"ZMin={bb.ZMin:.2f} ZMax={bb.ZMax:.2f}")
    print(f"threshold volume={threshold.Volume:.1f} "
          f"left_jamb volume={left_jamb.Volume:.1f} "
          f"right_jamb volume={right_jamb.Volume:.1f} "
          f"head volume={head.Volume:.1f}")
except Exception:
    print("SCRIPT_ERROR")
    traceback.print_exc(file=sys.stdout)
"""
    script = script.replace("__PARAMS_PATH__", params_path.replace("\\", "/"))

    script_path = os.path.join(tempfile.gettempdir(), "threshold_jamb_script.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)

    env = os.environ.copy()
    env["LIBGL_ALWAYS_SOFTWARE"] = "1"
    result = subprocess.run(
        [freecad, script_path],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    print("--- FreeCAD stdout ---")
    print(result.stdout)
    if result.stderr.strip():
        print("--- FreeCAD stderr ---")
        print(result.stderr)
    if "SCRIPT_ERROR" in result.stdout or result.returncode != 0:
        return False
    return os.path.isfile(step_path)


def main():
    width_mm = float(sys.argv[1]) if len(sys.argv) > 1 else 1000.0
    height_mm = float(sys.argv[2]) if len(sys.argv) > 2 else 1200.0
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Assembly: width(X)={width_mm} mm, height(Z)={height_mm} mm")

    step_path = os.path.join(OUTPUT_DIR, "window_assembly.step")
    step_ok = export_combined_step(width_mm, height_mm, step_path)
    print(f"STEP export: {'OK -> ' + step_path if step_ok else 'FAILED'}")


if __name__ == "__main__":
    main()