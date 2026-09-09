"""
app/services/model3d_freecad.py — FreeCAD-based 3D window/door assembly.
"""
from __future__ import annotations

import os, json, subprocess, tempfile, logging

logger = logging.getLogger(__name__)

_FREECAD_CANDIDATES = [
    r"C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe",
    r"C:\Program Files\FreeCAD 1.0\bin\freecadcmd.exe",
    r"C:\Program Files\FreeCAD 0.21\bin\freecadcmd.exe",
    r"C:\Program Files\FreeCAD 0.20\bin\freecadcmd.exe",
    r"C:\Program Files (x86)\FreeCAD 1.0\bin\freecadcmd.exe",
    "/usr/bin/freecadcmd",
    "/usr/local/bin/freecadcmd",
]


def _find_freecad() -> str | None:
    import glob, shutil
    # 1. explicit override via environment variable
    env = os.environ.get('FREECAD_CMD') or os.environ.get('FREECADCMD')
    if env and os.path.exists(env):
        return env
    # 2. known fixed paths
    for p in _FREECAD_CANDIDATES:
        if os.path.exists(p):
            return p
    # 3. anything on PATH
    for name in ('freecadcmd', 'FreeCADCmd', 'freecadcmd.exe', 'FreeCADCmd.exe'):
        found = shutil.which(name)
        if found:
            return found
    # 4. glob any FreeCAD * install dir on common Windows drives
    for base in (r"C:\Program Files", r"C:\Program Files (x86)",
                 r"D:\Program Files", r"D:\Program Files (x86)",
                 r"C:\\", r"D:\\"):
        for exe in glob.glob(os.path.join(base, "FreeCAD*", "bin", "freecadcmd.exe")):
            if os.path.exists(exe):
                return exe
    return None


def _find_freecad_OLD() -> str | None:
    for p in _FREECAD_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


# ══════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY
# ══════════════════════════════════════════════════════════════════════

def generate_3d_freecad(window, panes, tenant_id=None, fmt='glb') -> bytes:
    """
    Build window/door using FreeCAD. Raises RuntimeError if FreeCAD is not
    found so caller falls through to the trimesh builder.
    """
    freecad = _find_freecad()
    if not freecad:
        raise RuntimeError('FreeCAD not found — tried all known paths')

    fmt = fmt.lower()
    from .frame_assembly import build_members, resolve_profiles
    from .model3d_assembly import (_apply_window_overrides, _MIN_DEPTH,
                                    prepare_sections)

    profiles = resolve_profiles(tenant_id,
                                 getattr(window, 'material', 'Aluminium'),
                                 window=window)
    _apply_window_overrides(profiles, window, tenant_id)
    asm = build_members(window, panes, profiles)
    if not asm.members:
        raise RuntimeError('member graph produced no members')

    # SAME normalised sections as trimesh/cadquery — one geometry truth.
    prepare_sections(asm, profiles)

    asm_data = _serialise(window, asm)

    # Use a fast local drive for temp files, but never the bare drive root —
    # writes to X:\ root can be silently blocked/truncated by Windows
    # Controlled Folder Access or drive permissions with no Python exception,
    # producing a header-only file. Use a dedicated subfolder instead.
    tmp_dir = None
    for d in ('E:\\', 'D:\\', 'C:\\'):
        if os.path.isdir(d):
            candidate = os.path.join(d, 'qs_freecad_tmp')
            try:
                os.makedirs(candidate, exist_ok=True)
                testfile = os.path.join(candidate, '.wtest')
                with open(testfile, 'wb') as tf:
                    tf.write(b'x')
                os.remove(testfile)
                tmp_dir = candidate
                break
            except Exception:
                continue
    if tmp_dir is None:
        tmp_dir = tempfile.gettempdir()
    wid = getattr(window, 'id', 0)

    json_path     = os.path.join(tmp_dir, f'qs_asm_{wid}.json')
    script_path   = os.path.join(tmp_dir, f'qs_fc_{wid}.py')
    step_path     = os.path.join(tmp_dir, f'qs_out_{wid}.step')
    stl_path      = os.path.join(tmp_dir, f'qs_out_{wid}.stl')
    glass_path    = os.path.join(tmp_dir, f'qs_glass_{wid}.stl')
    fcstd_path    = os.path.join(tmp_dir, f'qs_model_{wid}.FCStd')
    techdraw_path = os.path.join(tmp_dir, f'qs_techdraw_{wid}.FCStd')

    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(asm_data, f)
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write("# -*- coding: utf-8 -*-\n")
            f.write(_build_script(json_path, step_path, stl_path, glass_path,
                                   fcstd_path, techdraw_path, fmt))

        env = os.environ.copy()
        env['LIBGL_ALWAYS_SOFTWARE'] = '1'
        r = subprocess.run([freecad, script_path],
                            capture_output=True, text=True,
                            timeout=180, env=env)
        logger.debug('FreeCAD stdout: %s', (r.stdout or '')[-4000:])
        if r.stderr:
            logger.warning('FreeCAD stderr: %s', r.stderr[-300:])

        if 'FREECAD_DONE' not in (r.stdout or ''):
            raise RuntimeError(
                f'FreeCAD script did not complete. '
                f'stdout: {(r.stdout or "")[-2000:]}')

        if fmt == 'fcstd':
            data = _read(fcstd_path)
            if len(data) < 200:
                raise RuntimeError(
                    'FreeCAD produced an empty .FCStd document '
                    f'({len(data)} bytes). stdout tail:\n{(r.stdout or "")[-2000:]}')
            return data

        if fmt == 'techdraw':
            data = _read(techdraw_path)
            if len(data) < 200:
                raise RuntimeError(
                    'FreeCAD produced an empty TechDraw .FCStd document '
                    f'({len(data)} bytes). stdout tail:\n{(r.stdout or "")[-2000:]}')
            return data

        if fmt == 'step':
            data = _read(step_path)
            # A STEP header alone is ~300-500 bytes with no geometry. Require
            # actual solid entities so we never hand back a blank file.
            txt = data[:200000].decode('latin-1', errors='ignore')
            if ('MANIFOLD_SOLID_BREP' not in txt
                    and 'ADVANCED_BREP_SHAPE_REPRESENTATION' not in txt
                    and 'CLOSED_SHELL' not in txt):
                raise RuntimeError(
                    'FreeCAD produced a STEP with no solid geometry '
                    f'({len(data)} bytes). stdout tail:\n{(r.stdout or "")[-2000:]}')
            return data

        stl_data = _read(stl_path)
        if fmt == 'stl':
            # Merge glass into the STL so a standalone download is complete
            # (STL carries no material, so a single combined mesh is correct).
            try:
                if os.path.exists(glass_path) and os.path.getsize(glass_path) > 100:
                    import trimesh, io
                    fm = trimesh.load(io.BytesIO(stl_data), file_type='stl')
                    with open(glass_path, 'rb') as gf:
                        gm = trimesh.load(io.BytesIO(gf.read()), file_type='stl')
                    return trimesh.util.concatenate([fm, gm]).export(file_type='stl')
            except Exception as exc:
                logger.debug('STL glass merge skipped: %s', exc)
            return stl_data

        glass_data = None
        try:
            if os.path.exists(glass_path) and os.path.getsize(glass_path) > 100:
                with open(glass_path, 'rb') as gf:
                    glass_data = gf.read()
        except Exception:
            glass_data = None
        return _stl_to_glb(stl_data, window, glass_data)

    finally:
        for p in (json_path, script_path, step_path, stl_path, glass_path,
                  fcstd_path, techdraw_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════
# SERIALISE → JSON
# ══════════════════════════════════════════════════════════════════════

def _serialise(window, asm) -> dict:
    r, g, b = 0.42, 0.42, 0.44
    try:
        h = (getattr(window, 'frame_colour_hex', None) or '#6a6a6c').lstrip('#')
        r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    except Exception:
        pass

    members = []
    for m in asm.members:
        members.append({
            'id':          m.id,
            'role':        m.role,
            'orientation': m.orientation,   # 'horizontal' | 'vertical'
            'x1': m.x1, 'y1': m.y1,
            'x2': m.x2, 'y2': m.y2,
            'bar':    float(getattr(m, '_sec_bar', m.bar_width)),
            'depth':  float(getattr(m, '_sec_dep', m.depth)),
            'length': float(m.length),
            # NORMALISED rings from prepare_sections: rings[0] outer,
            # rings[1:] holes; u = across bar (0..bar), v = depth (0..depth).
            'rings':  [[[float(u), float(v)] for u, v in ring]
                       for ring in getattr(m, '_rings', [])],
            # Curved member (arched/gothic head, full circular ring):
            # authoritative polyline — mirrors model3d.py's path handling
            # (_member_mesh_path / _member_solid_cq_path). Without this the
            # FreeCAD builder fell back to treating the ring as a single
            # straight x1/y1->x2/y2 bar, which doesn't reach the real
            # ellipse touch-points the adjoining mullions/transoms/beads
            # are trimmed to — the visible gap.
            'path':   ([[float(px), float(py)] for px, py in m.path]
                       if getattr(m, 'path', None) else None),
            'closed': bool(getattr(m, 'closed', False)),
        })

    # Glass placement (PWQ): IGU centred at the SASH mid-depth, datum Z=0
    # at the external face. Reference the FRAME depth (head/jamb/sash), not the
    # deep sill, so the glass beds in the frame rebate instead of behind it.
    frame_ref = max((m.depth for m in asm.members
                      if m.role in ('head', 'jamb', 'mullion', 'transom',
                                    'sash', 'outer_frame')), default=65.0)
    dep_max = max((m.depth for m in asm.members), default=65.0)
    glass_z = max(frame_ref - 24.0, frame_ref * 0.35)   # rebate pocket

    glass = []
    for gc in asm.glass:
        glass.append({
            'x': gc.x, 'y': gc.y, 'w': gc.w, 'h': gc.h,
            'infill':    gc.infill,
            'thickness': float(gc.thickness),
            # Circular/arched/gothic frames clip this pane's polygon to the
            # ring's inner ellipse/arc in frame_assembly.py (GlassCell.
            # clip_path). Without forwarding it here, the FreeCAD builder
            # always extruded the full rectangular glass.w x glass.h box,
            # which is the rectangle poking out past the round frame in
            # the FreeCAD-based GLB/techdraw output.
            'clip_path': ([[float(px), float(py)] for px, py in gc.clip_path]
                          if getattr(gc, 'clip_path', None) else None),
        })

    return {
        'width':     float(window.width_mm),
        'height':    float(window.height_mm),
        'frame_rgb': [r, g, b],
        'members':   members,
        'glass':     glass,
        'glass_z':   glass_z,              # rebate pocket, behind inner face
        'panel_z':   frame_ref * 0.5,      # solid panel centred in frame depth
    }


# ══════════════════════════════════════════════════════════════════════
# FREECAD SCRIPT
# ══════════════════════════════════════════════════════════════════════

def _build_script(json_path: str, step_path: str,
                   stl_path: str, glass_path: str,
                   fcstd_path: str, techdraw_path: str, fmt: str) -> str:
    jpath  = json_path.replace('\\', '/')
    spath  = step_path.replace('\\', '/')
    mpath  = stl_path.replace('\\', '/')
    gpath  = glass_path.replace('\\', '/')
    fcpath = fcstd_path.replace('\\', '/')
    tdpath = techdraw_path.replace('\\', '/')
    need_step     = 'True' if fmt in ('step', 'glb') else 'False'
    need_stl      = 'True' if fmt in ('stl', 'glb') else 'False'
    need_views    = 'True' if fmt in ('fcstd',) else 'False'
    need_techdraw = 'True' if fmt in ('techdraw',) else 'False'

    return f'''
import FreeCAD as App, Part, MeshPart, json, os, math
V = App.Vector

data = json.load(open(r"{jpath}", encoding="utf-8"))
W, H = data["width"], data["height"]
cx, cy = W / 2.0, H / 2.0

# Per-member orientation lookup, keyed by member id — used by the section
# pipeline below to tell whether a member's own extrusion axis runs
# parallel (in-plane) or perpendicular (transverse) to a given cut plane.
_member_orientation = {{m["id"]: m.get("orientation") for m in data["members"]}}

doc = App.newDocument("QS")
frame_solids = []
glass_solids = []
dep_max = max((m["depth"] for m in data["members"]), default=65.0)

# ── helper: cross-section face from loops or plain rectangle ─────────
# loops: list of point-lists where each pt is (u, v)
# u = across the bar (0 .. bar) maps to the face-perpendicular axis
# v = through-wall (0 .. depth) maps to Z in world space
# For HORIZONTAL member: u → Y (bar straddles centre line), v → Z
# For VERTICAL member: u → X (bar straddles centre line), v → Z

def _mk_face(pts_2d, plane, bar, depth):
    """
    Build a Part.Face from a list of (u,v) points in the given plane.
    plane: 'H' → YZ plane (u→Y, v→Z); 'V' → XZ plane (u→X, v→Z).
    Validates the wire; falls back to a rectangle if the outline is bad.
    """
    b2 = bar / 2.0
    def _v(u, v):
        if plane == 'H':
            return V(0.0, float(u) - b2, float(v))
        return V(float(u) - b2, 0.0, float(v))
    try:
        pts = [_v(u, v) for u, v in pts_2d]
        if len(pts) >= 3:
            pts.append(pts[0])  # close the wire
            wire = Part.makePolygon(pts)
            if wire.isClosed():
                face = Part.Face(wire)
                if face.isValid() and face.Area > 1.0:
                    return face
    except Exception as e:
        print("face build failed, using rect:", e, flush=True)
    # rectangle fallback
    if plane == 'H':
        r = [V(0,-b2,0), V(0,b2,0), V(0,b2,depth), V(0,-b2,depth), V(0,-b2,0)]
    else:
        r = [V(-b2,0,0), V(b2,0,0), V(b2,0,depth), V(-b2,0,depth), V(-b2,0,0)]
    return Part.Face(Part.makePolygon(r))

def make_face_rings(rings, plane, bar, depth):
    """Outer face from rings[0]; hole faces from rings[1:] (same plane)."""
    outer = _mk_face(rings[0] if rings else [], plane, bar, depth)
    holes = []
    for h in (rings[1:] if rings else []):
        try:
            hf = _mk_face(h, plane, bar, depth)
            if hf.isValid() and hf.Area > 1.0:
                holes.append(hf)
        except Exception as e:
            print("hole face skipped:", e, flush=True)
    return outer, holes

def make_path_solid(rings, bar, depth, path, closed):
    """Curved member (arched/gothic head, full circular ring): sweep the
    section along each straight polyline edge of path — the FreeCAD
    mirror of model3d.py::_member_mesh_path / _member_solid_cq_path, so
    all three exporters (trimesh/cadquery/FreeCAD) agree on placement."""
    n = len(path)
    count = n if closed else n - 1
    solids = []
    for i in range(count):
        p0 = path[i]
        p1 = path[(i + 1) % n] if closed else path[i + 1]
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        seg_len = math.hypot(dx, dy)
        if seg_len < 0.5:
            continue
        theta_deg = math.degrees(math.atan2(dy, dx))

        face, holes = make_face_rings(rings, 'H', bar, depth)
        seg = face.extrude(V(seg_len, 0.0, 0.0))
        for hf in holes:
            try:    seg = seg.cut(hf.extrude(V(seg_len, 0.0, 0.0)))
            except Exception as e: print("path hole cut failed:", e, flush=True)

        seg = seg.rotate(V(0, 0, 0), V(0, 0, 1), theta_deg)

        theta = math.radians(theta_deg)
        ux, uy = -math.sin(theta), math.cos(theta)
        tx = p0[0] - cx - ux * bar / 2.0
        ty = p0[1] - cy - uy * bar / 2.0
        seg.translate(V(tx, ty, 0.0))
        solids.append(seg)

    if not solids:
        return None
    result = solids[0]
    for s in solids[1:]:
        result = result.fuse(s)
    return result

# ══════════════════════════════════════════════════════════════════════
# SHARED ORTHOGRAPHIC SECTION-VIEW PIPELINE
# (used identically by Front / Side-section / Top-section — this is the
# single source of truth for coordinate mapping, cut validation, hatch
# clipping, and draw order, replacing three previously divergent
# hand-written implementations.)
# ══════════════════════════════════════════════════════════════════════
# World axes are fixed by the member-placement code above: X = width,
# Y = height, Z = depth (through-wall). Page mappings are declared once
# here so Front/Top/Side can never drift independently of each other.
#   FRONT : page = ( X,  Y)  width -> page X, height -> page Y
#   TOP   : page = ( X, -Z)  width -> page X, depth  -> page Y (flip)
#   SIDE  : page = (-Z,  Y)  depth -> page X (flip),  height -> page Y
# Height is shared on page-Y between FRONT and SIDE with no sign flip.
# Width is shared on page-X between FRONT and TOP with no sign flip.
# Depth uses exactly one sign convention (-Z) in both TOP and SIDE.

VIEW_TO_PAGE = {{
    'front': lambda p: (p.x,  p.y),    # look -Z : X->pgX, Y->pgY
    'top':   lambda p: (p.x, -p.z),    # look -Y : X->pgX, -Z->pgY (ext face at bottom)
    'side':  lambda p: (p.z,  p.y),    # look -X : Z->pgX,  Y->pgY
}}

# World-space extrusion axis for each member orientation. Used to test
# whether a member's own length axis runs parallel (in-plane) to a given
# section cut plane, versus transverse (perpendicular) to it.
# Z axis added: members extruded along Z (none currently, but guards
# against future panel/threshold members and prevents all-exclusion when
# the side section uses a Z-normal plane.
_ORIENT_AXIS = {{
    'horizontal': V(1, 0, 0),
    'vertical':   V(0, 1, 0),
    'depth':      V(0, 0, 1),
}}

def _project_edges(shape, to_page, deflection=0.2, exclude_plane=None):
    """Manual edge -> page-space wireframe. Used for all three views so
    they share one code path and one failure mode instead of relying on
    Draft.make_shape2dview's single reliable projection direction.

    exclude_plane, when given as (normal_vector, distance), skips any
    edge whose points all lie on that plane. This is used to drop the
    cap face generated by the background boolean cut at the section
    plane, which would otherwise duplicate the independently-built
    cut-profile edges (ghost/double lines)."""
    polys = []
    for e in shape.Edges:
        try:
            pts3d = e.discretize(Deflection=deflection)
            if exclude_plane is not None:
                n, d = exclude_plane
                if all(abs(n.dot(p) - d) < 1e-3 for p in pts3d):
                    continue
            pts2d = [V(*to_page(p), 0.0) for p in pts3d]
            if len(pts2d) >= 2:
                polys.append(Part.makePolygon(pts2d))
        except Exception:
            continue
    return Part.Compound(polys) if polys else None

def _clean_wire_shared(w):
    """Closure/self-intersection guard shared by all views. A wire that
    fails to rebuild closed never reaches the hatcher or the profile
    outline, which is what previously let broken/open cut-loops through
    as corrupted section geometry."""
    try:
        cw = Part.Wire(w.OrderedEdges)
        cw.fix(1e-4, 1e-4, 1e-4)
    except Exception:
        return None
    return cw if cw.isClosed() else None

def _slice_wires_to_faces(solid, plane_normal, distance, to_page):
    """Extract the exact planar section wires from one solid and preserve
    every disconnected section loop.

    The previous implementation reduced all returned OCC section wires to
    one "largest outer" polygon and classified the rest with a page-space
    point-in-polygon test. That is unsafe for profiles with multiple loops
    or touching/near-touching boundaries and can turn a valid section into
    a self-crossing polygon, which then makes the hatch clip into triangles.

    Here the containment relationship is established while the wires are
    still native FreeCAD geometry. Each valid section wire becomes a native
    planar face; its CenterOfMass is tested against the other native faces.
    The page-space polygons are only used for display after the topology has
    already been classified.

    Returns a list of (outer_pts, [hole_pts, ...]) tuples in page space.
    """
    try:
        wires = solid.slice(plane_normal, distance)
    except Exception:
        return []
    if not wires:
        return []

    loops = []
    for w in wires:
        cw = _clean_wire_shared(w)
        if cw is None:
            continue
        try:
            native_face = Part.Face(cw)
            if not native_face.isValid() or native_face.Area <= 1e-6:
                continue
        except Exception:
            continue

        pts = []
        for e in cw.OrderedEdges:
            try:
                ep = e.discretize(Deflection=0.2)
            except Exception:
                ep = []
            if len(ep) >= 2:
                for p in ep[:-1]:
                    pts.append(to_page(p))

        if len(pts) >= 3:
            loops.append({{
                'wire': cw,
                'face': native_face,
                'pts': pts,
                'area': float(native_face.Area),
                'depth': 0,
            }})

    if not loops:
        return []

    # Determine nesting from native OCC faces, not from discretised page
    # polygons. This avoids winding assumptions and avoids using a boundary
    # vertex as the containment probe.
    for i, item in enumerate(loops):
        probe = item['face'].CenterOfMass
        depth = 0
        for j, other in enumerate(loops):
            if i == j or other['area'] <= item['area']:
                continue
            try:
                if other['face'].isInside(probe, 1e-6, False):
                    depth += 1
            except Exception:
                continue
        item['depth'] = depth

    # Even nesting depth = material, odd nesting depth = void. Build one
    # section face per material island; do not collapse disconnected outers
    # into one polygon.
    result = []
    for i, outer in enumerate(loops):
        if outer['depth'] % 2 != 0:
            continue

        holes = []
        for j, candidate in enumerate(loops):
            if j == i or candidate['depth'] != outer['depth'] + 1:
                continue
            try:
                if outer['face'].isInside(candidate['face'].CenterOfMass,
                                           1e-6, False):
                    holes.append(candidate['pts'])
            except Exception:
                continue

        result.append((outer['pts'], holes))

    return result

def _face_from_loops(outer_pts, hole_pts_list):
    """Build one validated page-space section face from one material island.

    The caller has already classified the loops from native OCC section
    topology, so this function performs only the final page-space conversion
    needed by the hatch boolean.
    """
    def mk(pts):
        try:
            verts = [V(px, py, 0.0) for px, py in pts]
            if len(verts) < 3:
                return None
            verts.append(verts[0])
            w = Part.makePolygon(verts)
            if not w.isClosed():
                return None
            f = Part.Face(w)
            if not f.isValid() or f.Area <= 1e-6:
                return None
            return f
        except Exception:
            return None

    outer = mk(outer_pts)
    if outer is None:
        return None

    for hp in hole_pts_list:
        hf = mk(hp)
        if hf is None:
            continue
        try:
            cut = outer.cut(hf)
            if cut.isValid():
                outer = cut
        except Exception:
            continue

    return outer if outer.isValid() else None

def _hatch_lines(face2d, spacing, angle_deg):
    """45deg cross-hatch lines strictly clipped to face2d via boolean
    common — lines can never extend past the actual solid cut face, so
    hatching never bleeds into holes or background geometry."""
    bb = face2d.BoundBox
    diag = math.hypot(bb.XMax - bb.XMin, bb.YMax - bb.YMin) + 10.0
    ang = math.radians(angle_deg)
    dx, dy = math.cos(ang), math.sin(ang)
    step = spacing * (2 ** 0.5)
    n = int(diag / step) + 2
    ox0, oy0 = bb.XMin - 5.0, bb.YMin - 5.0
    edges = []
    for i in range(-n, n):
        ox = ox0 + i * step
        p0 = V(ox - diag * dx, oy0 - diag * dy, 0.0)
        p1 = V(ox + diag * dx, oy0 + diag * dy, 0.0)
        try:
            line = Part.LineSegment(p0, p1).toShape()
            common = line.common(face2d)
            edges.extend(common.Edges)
        except Exception:
            continue
    return edges

def _cut_frame_solids(frame_solid_list, cutter):
    """Per-solid cut, validated. Cutting each member independently (never
    a single boolean cut across the whole compound) avoids OCC merging
    touching solids' faces at shared seams into one distorted face — the
    source of the old wedge-shaped section corruption. Glass is excluded
    by the caller, so a hollow opening can never produce a cut face to
    hatch here."""
    pieces = []
    for _, solid in frame_solid_list:
        try:
            c = solid.cut(cutter)
            if c.isValid() and len(c.Solids) > 0:
                pieces.append(c)
        except Exception:
            continue
    return Part.Compound(pieces) if pieces else None

# Explicit draw-order stack: background wireframe paints first, hatch
# fills on top of it, bold cut-profile outlines paint last/on top.
_Z_BG, _Z_HATCH, _Z_PROFILE = 0.0, 0.05, 0.10

def build_ortho_view(doc, name_prefix, base_shape, view_key, frame_solid_list=None,
                      bg_cutter=None, plane_normal=None, plane_distance=None,
                      hatch_spacing=5.0, hatch_angle=45.0):
    """Single builder for Front (bg_cutter=None) and Side/Top sections.

    The BACKGROUND silhouette (what's visible beyond the cut plane) still
    comes from a half-space boolean cut (bg_cutter) — that's the only way
    to get a real retained 3D shape to project. But the CUT PROFILE and
    HATCH — the part that was actually broken — now come from
    Shape.slice() per solid via _slice_wires_to_face(), not from
    reverse-engineering a face out of the boolean cut result. Returns a
    dict of created objects, or None if nothing could be built."""
    to_page = VIEW_TO_PAGE[view_key]
    src_shape = base_shape
    if bg_cutter is not None:
        src_shape = _cut_frame_solids(frame_solid_list, bg_cutter)
        if src_shape is None:
            return None

    # Bug B fix: the boolean cut above caps the open volume with a new
    # planar face exactly at the section plane. Its boundary edges are
    # coplanar with (and duplicate) the independently-built cut-profile
    # edges below, producing ghost/double lines. Exclude edges lying on
    # that plane from the background projection.
    exclude_plane = ((plane_normal, plane_distance)
                      if plane_normal is not None else None)
    bg = _project_edges(src_shape, to_page, exclude_plane=exclude_plane)
    if bg is None or len(bg.Edges) == 0:
        return None

    bg_obj = doc.addObject("Part::Feature", f"{{name_prefix}}Background")
    bg_obj.Shape = bg
    bg_obj.Label = f"Draft_{{name_prefix}}_View"
    bg_obj.Placement = App.Placement(V(0, 0, _Z_BG), App.Rotation())
    doc.recompute()

    profile_obj = None
    hatch_obj = None

    if plane_normal is not None:
        profile_edges = []
        hatch_edges = []
        for mid, solid in frame_solid_list:
            # Bug A fix: a member whose own extrusion axis runs parallel
            # to this section's cut plane (e.g. a horizontal head/sill
            # member sliced by the Top section's Y-normal plane, or a
            # vertical jamb/mullion sliced by the Side section's X-normal
            # plane) does not produce a true transverse cross-section —
            # OCC's slice() instead returns a longitudinal cut spanning
            # the member's full length, which the old code hatched as an
            # oversized "material" face (black-fill / squeeze). Such
            # members still contribute their real silhouette via the
            # background projection above; they are only excluded from
            # the slice/hatch pass here.
            orient = _member_orientation.get(mid)
            axis = _ORIENT_AXIS.get(orient)
            _dot = axis.dot(plane_normal) if axis is not None else None
            # Exclude member when its extrusion axis IS the cut-plane normal (dot~1).
            # Side (X-normal): horizontal(X) dot=1 excluded, vertical(Y) dot=0 included.
            # Top  (Y-normal): vertical(Y)   dot=1 excluded, horizontal(X) dot=0 included.
            _included = not (axis is not None and abs(_dot) > 0.5)
            print(f"    [{{name_prefix}}] member={{mid}} orient={{orient}} "
                  f"dot={{_dot}} {{'INCLUDED' if _included else 'excluded'}}",
                  flush=True)
            if not _included:
                continue

            sections = _slice_wires_to_faces(
                solid, plane_normal, plane_distance, to_page)
            if not sections:
                continue

            for outer_pts, hole_pts in sections:
                face2d = _face_from_loops(outer_pts, hole_pts)
                if face2d is None:
                    continue

                # Each disconnected material island is drawn and hatched
                # independently. Never combine separate OCC section loops
                # into one polygon: that is what produced the wedge-shaped
                # hatch corruption in the Top section.
                verts = [V(px, py, 0.0) for px, py in outer_pts]
                verts.append(verts[0])
                try:
                    profile_edges.extend(Part.makePolygon(verts).Edges)
                except Exception:
                    pass

                for hp in hole_pts:
                    hverts = [V(px, py, 0.0) for px, py in hp]
                    hverts.append(hverts[0])
                    try:
                        profile_edges.extend(Part.makePolygon(hverts).Edges)
                    except Exception:
                        pass

                hatch_edges.extend(
                    _hatch_lines(face2d, hatch_spacing, hatch_angle))

        print(f"    [{{name_prefix}}] profile_edges={{len(profile_edges)}} "
              f"hatch_edges={{len(hatch_edges)}}", flush=True)

        if profile_edges:
            profile_obj = doc.addObject("Part::Feature", f"{{name_prefix}}Profile")
            profile_obj.Shape = Part.Compound(profile_edges)
            profile_obj.Label = f"Draft_{{name_prefix}}_Profile"
            profile_obj.Placement = App.Placement(V(0, 0, _Z_PROFILE), App.Rotation())
            if App.GuiUp:
                try:
                    profile_obj.ViewObject.LineColor = (0.0, 0.0, 0.0)
                    profile_obj.ViewObject.LineWidth = 2.5
                except Exception:
                    pass

        if hatch_edges:
            hatch_obj = doc.addObject("Part::Feature", f"{{name_prefix}}Hatch")
            hatch_obj.Shape = Part.Compound(hatch_edges)
            hatch_obj.Label = f"Draft_{{name_prefix}}_Hatch"
            hatch_obj.Placement = App.Placement(V(0, 0, _Z_HATCH), App.Rotation())

        doc.recompute()

        if App.GuiUp:
            try:
                bg_obj.ViewObject.LineColor = (0.65, 0.65, 0.65)
                bg_obj.ViewObject.LineWidth = 1.0
            except Exception:
                pass

    print(f"    [{{name_prefix}}] hatch_obj={{'created' if hatch_obj is not None else 'NONE'}} "
          f"({{len(hatch_obj.Shape.Edges) if hatch_obj is not None else 0}} edges in Shape)",
          flush=True)

    members_out = [o for o in (bg_obj, hatch_obj, profile_obj) if o is not None]
    grp = doc.addObject("App::DocumentObjectGroup", f"{{name_prefix}}Group")
    grp.Group = members_out
    return {{'group': grp, 'bg': bg_obj, 'profile': profile_obj, 'hatch': hatch_obj}}

def _shift_group(gd, dx, dy):
    for o in gd['group'].Group:
        b = o.Placement.Base
        o.Placement.Base = App.Vector(b.x + dx, b.y + dy, b.z)

# ── build each member ────────────────────────────────────────────────

for m in data["members"]:
    bar = float(m["bar"])
    depth = float(m["depth"])
    L = float(m["length"])
    rings = m.get("rings") or []
    path = m.get("path")
    closed = bool(m.get("closed"))

    # World-space position of member (centred coords)
    mx = (m["x1"] + m["x2"]) / 2.0 - cx
    my = (m["y1"] + m["y2"]) / 2.0 - cy

    try:
        if path:
            solid = make_path_solid(rings, bar, depth, path, closed)
            if solid is None:
                raise ValueError("empty path sweep")
        elif m["orientation"] == "horizontal":
            x_start = min(m["x1"], m["x2"]) - cx
            face, holes = make_face_rings(rings, 'H', bar, depth)
            solid = face.extrude(V(L, 0.0, 0.0))
            for hf in holes:
                try:    solid = solid.cut(hf.extrude(V(L, 0.0, 0.0)))
                except Exception as e: print("hole cut failed:", e, flush=True)
            solid.translate(V(x_start, my, 0.0))
        else:  # vertical
            y_start = min(m["y1"], m["y2"]) - cy
            face, holes = make_face_rings(rings, 'V', bar, depth)
            solid = face.extrude(V(0.0, L, 0.0))
            for hf in holes:
                try:    solid = solid.cut(hf.extrude(V(0.0, L, 0.0)))
                except Exception as e: print("hole cut failed:", e, flush=True)
            solid.translate(V(mx, y_start, 0.0))

        # Guard: a failed/empty extrude produces a zero-volume shape. Fall back
        # to a solid box so the member is never missing from the assembly.
        if solid is None or not solid.isValid() or solid.Volume < 1.0:
            raise ValueError("empty/invalid extrude — box fallback")

        frame_solids.append((m['id'], solid))
        print(f"  {{m['id']}} ok  (role={{m['role']}} L={{L:.0f}}mm bar={{bar:.0f}} depth={{depth:.0f}})",
              flush=True)

    except Exception as e:
        # Bulletproof fallback: a plain box the size of the member's bounding
        # section, positioned like the real member. Guarantees a non-blank STEP.
        try:
            if path:
                xs = [p[0] for p in path]; ys = [p[1] for p in path]
                bx0, by0 = min(xs) - cx, min(ys) - cy
                bw = max(max(xs) - min(xs), 1.0)
                bh = max(max(ys) - min(ys), 1.0)
                box = Part.makeBox(bw, bh, depth, V(bx0, by0, 0.0))
            elif m["orientation"] == "horizontal":
                x_start = min(m["x1"], m["x2"]) - cx
                box = Part.makeBox(L, bar, depth,
                                    V(x_start, my - bar/2.0, 0.0))
            else:
                y_start = min(m["y1"], m["y2"]) - cy
                box = Part.makeBox(bar, L, depth,
                                    V(mx - bar/2.0, y_start, 0.0))
            frame_solids.append((m['id'], box))
            print(f"  {{m['id']}} BOX-FALLBACK ({{e}})", flush=True)
        except Exception as e2:
            print(f"  {{m['id']}} FAILED entirely: {{e2}}", flush=True)

# ── glass / panel boxes ──────────────────────────────────────────────

glass_z = float(data.get("glass_z", dep_max * 0.5))
panel_z = float(data.get("panel_z", dep_max * 0.5))
for g in data["glass"]:
    gx = g["x"] + g["w"] / 2.0 - cx
    gy = g["y"] + g["h"] / 2.0 - cy
    z0 = panel_z if g["infill"] == "panel" else glass_z
    th = g["thickness"] if g["infill"] == "panel" else 8.0
    clip = g.get("clip_path")
    try:
        if clip and len(clip) >= 3:
            # Circular/arched/gothic frame: extrude the exact clipped
            # outline instead of a plain box, so the glass follows the
            # curved frame instead of poking out at the corners.
            pts = [V(px - cx, py - cy, z0 - th / 2.0) for px, py in clip]
            pts.append(pts[0])
            wire = Part.makePolygon(pts)
            face = Part.Face(wire)
            gs = face.extrude(V(0, 0, th))
        else:
            gs = Part.makeBox(g["w"], g["h"], th,
                               V(gx - g["w"]/2, gy - g["h"]/2, z0 - th/2.0))
        glass_solids.append((f"Glass{{len(glass_solids)}}", gs))
    except Exception as e:
        print(f"  glass FAILED: {{e}}", flush=True)

# ── export ────────────────────────────────────────────────────────────

all_solids = frame_solids + glass_solids
if not all_solids:
    print("ERROR: no solids built", flush=True)
else:
    total_vol = sum(s.Volume for _, s in all_solids)
    print(f"DIAG: {{len(all_solids)}} solids, total volume={{total_vol:.1f}}mm3",
          flush=True)
    # FreeCAD 1.1.3: Part.export() on raw, un-added TopoShape objects
    # silently writes a header-only STEP with no geometry. Shapes MUST
    # be assigned to real Part::Feature document objects first.
    # Each member/glass pane keeps its own labeled Part::Feature (not
    # fused/compounded) so the STEP tree (and the TechDraw projection
    # group, which also needs discrete, non-fused solids) shows a
    # discrete hierarchy (head, jamb_left, jamb_right, threshold, glass, ...).
    step_objs = []
    if {need_step} or {need_techdraw} or {need_views}:
        seen_labels = {{}}
        for label, s in all_solids:
            n = seen_labels.get(label, 0)
            seen_labels[label] = n + 1
            obj_name = label if n == 0 else f"{{label}}{{n}}"
            feat = doc.addObject("Part::Feature", obj_name)
            feat.Label = obj_name
            feat.Shape = s
            step_objs.append(feat)
        doc.recompute()

    if {need_step}:
        Part.export(step_objs, r"{spath}")
        try:
            _sz = os.path.getsize(r"{spath}")
            print(f"STEP exported ({{_sz}} bytes)", flush=True)
        except Exception as _e:
            print("STEP export check failed:", _e, flush=True)

    if {need_stl}:
        if frame_solids:
            fmesh = MeshPart.meshFromShape(
                Shape=Part.makeCompound([s for _, s in frame_solids]),
                LinearDeflection=0.5, AngularDeflection=0.3, Relative=False)
            fmesh.write(r"{mpath}")
            print("STL (frame) exported", flush=True)
        if glass_solids:
            gmesh = MeshPart.meshFromShape(
                Shape=Part.makeCompound([s for _, s in glass_solids]),
                LinearDeflection=0.5, AngularDeflection=0.3, Relative=False)
            gmesh.write(r"{gpath}")
            print("STL (glass) exported", flush=True)

    # ── Native 2D orthographic + section views kept in the document tree
    # (no DXF/STEP). Reuses the SAME solids already built above for the
    # 3D geometry — the member/glass construction code above is untouched.
    # Front/Side-section/Top-section all go through build_ortho_view(),
    # sharing one coordinate convention (VIEW_TO_PAGE), one cut/validate
    # path (_cut_frame_solids), one hatch-clip path (_hatch_lines), and
    # one explicit draw-order stack (_Z_BG < _Z_HATCH < _Z_PROFILE).
    if {need_views}:
        solid_objs = [obj for obj in doc.Objects
                      if obj.isDerivedFrom("Part::Feature") and "Draft" not in obj.TypeId]

        # Part::Compound.Links is a non-destructive *grouping* link (no
        # fused/copied geometry) — the individual solids above are
        # untouched; this object only exists to supply one combined
        # shape for projection.
        view_src = doc.addObject("Part::Compound", "ViewSource")
        view_src.Links = solid_objs
        view_src.Visibility = False
        doc.recompute()
        base_shape = view_src.Shape

        # Glass is excluded from the cut-solid list used for section
        # hatching — a hollow opening can never contribute a hatch face.
        frame_solid_list = [(o.Name, o.Shape) for o in solid_objs if "Glass" not in o.Name]

        front = build_ortho_view(doc, "Front", base_shape, 'front')
        if front is None:
            print("ERROR: Front view produced no geometry", flush=True)
        else:
            fbb = front['bg'].Shape.BoundBox
            _shift_group(front, -fbb.XMin, -fbb.YMin)
            doc.recompute()
            front_bb = front['bg'].Shape.BoundBox
            print(f"Draft_Front_View: edges={{len(front['bg'].Shape.Edges)}}", flush=True)

            spacing = 250.0  # separation gap in mm
            margin  = 200.0
            bb_base = base_shape.BoundBox

            # ── Sectional Side View ──────────────────────────────────────
            # Side section: cut X-normal through a vertical JAMB member —
            # not any vertical member. A window's centre mullion
            # (role == "mullion") commonly sits closer to the model's
            # geometric X-mid than either jamb, so a plain "nearest
            # vertical member" search locks onto the mullion instead of a
            # jamb, cutting the section at the wrong location with the
            # wrong bar width (confirmed against an uploaded window
            # .FCStd: jambs at X=-566.5/+566.5, mullion at X=0.0 — the old
            # nearest-to-center search always chose the mullion).
            # Restricting the candidate pool to role == "jamb" ensures the
            # Side Section always cuts through a real outer-frame jamb, as
            # intended, on both doors (no mullion present) and windows
            # (mullion present). Fallback to geo_xmid/67mm below is
            # unchanged for the edge case of zero jamb-role members.
            # to_page: Z->pgX, Y->pgY.
            # bg_cutter keeps left half (X < xmid).
            # Horizontal members (axis X, dot=1) → excluded.
            # Vertical members   (axis Y, dot=0) → included → hatched.
            geo_xmid = (bb_base.XMin + bb_base.XMax) / 2.0
            jamb_members = [mm for mm in data["members"]
                            if mm.get("orientation") == "vertical"
                            and mm.get("role") == "jamb"]
            jamb_centers = [(mm["x1"] + mm["x2"]) / 2.0 - cx for mm in jamb_members]
            if jamb_centers:
                nearest = min(zip(jamb_centers, jamb_members), key=lambda t: abs(t[0] - geo_xmid))
                xmid = nearest[0]
                xbar = float(nearest[1].get("bar", 67))
            else:
                xmid = geo_xmid
                xbar = 67.0
            # bg_cutter keeps left half (X < xmid); slice inside jamb at xmid - xbar/4
            xslice = xmid - xbar / 4.0
            side_cutter = Part.makeBox(
                (xmid - bb_base.XMin) + margin,
                (bb_base.YMax - bb_base.YMin) + 2 * margin,
                (bb_base.ZMax - bb_base.ZMin) + 2 * margin,
                V(bb_base.XMin - margin, bb_base.YMin - margin, bb_base.ZMin - margin))

            print(f"Side section: xmid={{xmid:.1f}} xslice={{xslice:.1f}} xbar={{xbar:.1f}}", flush=True)

            side = build_ortho_view(doc, "SideSection", base_shape, 'side',
                                     frame_solid_list=frame_solid_list,
                                     bg_cutter=side_cutter,
                                     plane_normal=V(1, 0, 0), plane_distance=xslice)
            if side is None:
                print("WARNING: side section produced no geometry", flush=True)
            else:
                sbb = side['bg'].Shape.BoundBox
                target_x = front_bb.XMin - spacing - (sbb.XMax - sbb.XMin)
                target_y = front_bb.YMin - sbb.YMin
                _shift_group(side, target_x - sbb.XMin, target_y)
                doc.recompute()
                print(f"Draft_SideSection_View: x={{target_x:.1f}} "
                      f"edges={{len(side['bg'].Shape.Edges)}}", flush=True)

            # ── Sectional Top View ───────────────────────────────────────
            # Cut plane: Y-normal at ymid (looking down, -Y direction).
            # to_page maps: page-X = X (width), page-Y = -Z (depth flipped).
            # Snap ymid to the nearest HORIZONTAL member centre so the cut
            # always passes through real frame material (head/sill/transom)
            # rather than landing in open glass area.
            # bg_cutter keeps the TOP half (Y > ymid) so the retained
            # silhouette shows the frame from above.
            # Included for hatching: horizontal members (dot of V(1,0,0)
            # with V(0,1,0) = 0 → included) AND vertical members (dot=0 →
            # included). Only members extruded along Y (none normally) are
            # excluded — so jamb, mullion, head, sill all get hatched.
            # Top section: cut Y-normal through head member centre.
            # Reveals depth (Z) profile of head/jamb/mullion looking down.
            # to_page: X->pgX, Z->pgY.
            # bg_cutter keeps top half (Y > ymid).
            # Vertical members (axis Y, dot with V(0,1,0)=1) → excluded.
            # Horizontal members (axis X, dot=0) → included → hatched cross-section.
            geo_ymid = (bb_base.YMin + bb_base.YMax) / 2.0
            horiz_members = [mm for mm in data["members"] if mm.get("orientation") == "horizontal"]
            # Snap to HEAD: the horizontal member with the highest Y centre
            if horiz_members:
                head_m = max(horiz_members, key=lambda mm: (mm["y1"] + mm["y2"]) / 2.0)
                ymid = (head_m["y1"] + head_m["y2"]) / 2.0 - cy
                ybar = float(head_m.get("bar", 35))
            else:
                ymid = geo_ymid
                ybar = 35.0
            # bg_cutter keeps top half (Y > ymid); slice inside head at ymid + ybar/4
            yslice = ymid + ybar / 4.0
            half_y = Part.makeBox(
                (bb_base.XMax - bb_base.XMin) + 2 * margin,
                (bb_base.YMax - ymid) + margin,
                (bb_base.ZMax - bb_base.ZMin) + 2 * margin,
                V(bb_base.XMin - margin, ymid, bb_base.ZMin - margin))

            print(f"Top section: ymid={{ymid:.1f}} yslice={{yslice:.1f}} ybar={{ybar:.1f}}", flush=True)

            top = build_ortho_view(doc, "TopSection", base_shape, 'top',
                                    frame_solid_list=frame_solid_list,
                                    bg_cutter=half_y,
                                    plane_normal=V(0, 1, 0), plane_distance=yslice)
            if top is None:
                print("WARNING: top section produced no geometry", flush=True)
            else:
                tbb = top['bg'].Shape.BoundBox
                dx = front_bb.XMin - tbb.XMin
                dy = front_bb.YMax + spacing - tbb.YMin
                _shift_group(top, dx, dy)
                doc.recompute()
                print(f"Draft_TopSection_View: edges={{len(top['bg'].Shape.Edges)}}",
                      flush=True)

        doc.removeObject(view_src.Name)
        doc.recompute()

        # Reset viewport camera to a strict top-down orthographic view, so
        # any GUI session opening this file isn't left on a skewed/rotated
        # camera angle. No-op under freecadcmd (headless), where GuiUp is False.
        if App.GuiUp:
            import FreeCADGui as Gui
            view = Gui.ActiveDocument.ActiveView
            view.viewTop()
            view.fitAll()

        doc.saveAs(r"{fcpath}")
        try:
            _fsz = os.path.getsize(r"{fcpath}")
            print(f"FCStd with ortho views saved ({{_fsz}} bytes)", flush=True)
        except Exception as _e:
            print("FCStd save check failed:", _e, flush=True)

    # ── TechDraw multi-view drawing page (Front/Top/Side) — no DXF/STEP ─
    # Uses the SAME individual, non-fused Part::Feature solids built
    # above (step_objs) — the member/glass construction code above this
    # block is untouched.
    if {need_techdraw}:
        import TechDraw, glob

        tmpl_dir = os.path.join(App.getResourceDir(), 'Mod', 'TechDraw', 'Templates')
        candidates = glob.glob(os.path.join(tmpl_dir, 'A4_Landscape*.svg'))
        if not candidates:
            candidates = glob.glob(os.path.join(tmpl_dir, '*Landscape*.svg'))
        if not candidates:
            raise RuntimeError(f"No A4 Landscape TechDraw template found in {{tmpl_dir}}")
        template_path = candidates[0]

        page = doc.addObject('TechDraw::DrawPage', 'Page')
        template = doc.addObject('TechDraw::DrawSVGTemplate', 'Template')
        template.Template = template_path
        page.Template = template

        dpg = doc.addObject('TechDraw::DrawProjGroup', 'ProjGroup')
        page.addView(dpg)
        dpg.Source = step_objs
        doc.recompute()

        # Front is normally auto-added as the anchor when Source is first
        # set; explicitly request all three so the drawing is complete
        # even if the anchor wasn't created automatically.
        for _view in ('Front', 'Top', 'Right'):
            try:
                dpg.addProjection(_view)
            except Exception as _e:
                print(f"addProjection {{_view}} skipped: {{_e}}", flush=True)
        doc.recompute()

        doc.saveAs(r"{tdpath}")
        try:
            _tsz = os.path.getsize(r"{tdpath}")
            print(f"TechDraw FCStd saved ({{_tsz}} bytes): page={{page.Name}} "
                  f"projgroup={{dpg.Name}}", flush=True)
        except Exception as _e:
            print("TechDraw FCStd save check failed:", _e, flush=True)

App.closeDocument(doc.Name)
print("FREECAD_DONE", flush=True)
'''


# ══════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════

def _read(path: str) -> bytes:
    if not os.path.exists(path) or os.path.getsize(path) < 100:
        raise RuntimeError(f'FreeCAD output missing or empty: {path}')
    with open(path, 'rb') as f:
        return f.read()


def _stl_to_glb(stl_data: bytes, window, glass_data: bytes = None) -> bytes:
    """Convert FreeCAD STL(s) → GLB. Frame is opaque; glass is a SEPARATE
    translucent mesh so the viewer shows real glazing, not a solid slab."""
    import trimesh, io, colorsys
    frame = trimesh.load(io.BytesIO(stl_data), file_type='stl')
    r, g, b = 0.42, 0.42, 0.44
    try:
        h = (getattr(window, 'frame_colour_hex', None) or '#6a6a6c').lstrip('#')
        r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    except Exception:
        pass
    hh, s, lv = colorsys.rgb_to_hls(r, g, b)
    if lv < 0.18:
        r, g, b = colorsys.hls_to_rgb(hh, 0.28, s)
    frame.visual.face_colors = [int(r * 255), int(g * 255), int(b * 255), 255]

    geoms = [frame]
    if glass_data:
        try:
            glass = trimesh.load(io.BytesIO(glass_data), file_type='stl')
            if len(glass.faces) > 0:
                # translucent blue-grey glazing
                glass.visual.face_colors = [140, 190, 205, 110]
                geoms.append(glass)
        except Exception as exc:
            logger.debug('glass mesh skipped: %s', exc)
    return trimesh.Scene(geoms).export(file_type='glb')