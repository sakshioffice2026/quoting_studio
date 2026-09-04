"""
app/services/model3d_freecad.py — FreeCAD-based 3D window/door assembly.

Correct approach (mirrors Image 1 engineering drawing):
  1. For each member, the cross-section polygon is built DIRECTLY in the
     correct plane (YZ for horizontal, XZ for vertical members).
  2. Extrude along the member's axis direction (V(L,0,0) or V(0,L,0)).
  3. Translate to member world position.
  NO rotation matrices. NO mitre cuts (aluminium = butt joints).

Subprocess pattern follows SCAPI generator.py exactly.
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
#  PUBLIC ENTRY
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
    wid     = getattr(window, 'id', 0)

    json_path   = os.path.join(tmp_dir, f'qs_asm_{wid}.json')
    script_path = os.path.join(tmp_dir, f'qs_fc_{wid}.py')
    step_path   = os.path.join(tmp_dir, f'qs_out_{wid}.step')
    stl_path    = os.path.join(tmp_dir, f'qs_out_{wid}.stl')
    glass_path  = os.path.join(tmp_dir, f'qs_glass_{wid}.stl')

    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(asm_data, f)
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write("# -*- coding: utf-8 -*-\n")
            f.write(_build_script(json_path, step_path, stl_path, glass_path, fmt))

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
        for p in (json_path, script_path, step_path, stl_path, glass_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════
#  SERIALISE → JSON
# ══════════════════════════════════════════════════════════════════════
def _serialise(window, asm) -> dict:
    r, g, b = 0.42, 0.42, 0.44
    try:
        h = (getattr(window, 'frame_colour_hex', None) or '#6a6a6c').lstrip('#')
        r, g, b = int(h[0:2],16)/255, int(h[2:4],16)/255, int(h[4:6],16)/255
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
            'rings':  [[[float(u), float(v)] for u, v in r]
                       for r in getattr(m, '_rings', [])],
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
    dep_max    = max((m.depth for m in asm.members), default=65.0)
    glass_z    = max(frame_ref - 24.0, frame_ref * 0.35)   # rebate pocket

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
        'glass_z':   glass_z,             # rebate pocket, behind inner face
        'panel_z':   frame_ref * 0.5,      # solid panel centred in frame depth
    }


# ══════════════════════════════════════════════════════════════════════
#  FREECAD SCRIPT
# ══════════════════════════════════════════════════════════════════════
def _build_script(json_path: str, step_path: str,
                  stl_path: str, glass_path: str, fmt: str) -> str:
    jpath = json_path.replace('\\', '/')
    spath = step_path.replace('\\', '/')
    mpath = stl_path.replace('\\', '/')
    gpath = glass_path.replace('\\', '/')
    need_step = 'True' if fmt in ('step', 'glb') else 'False'
    need_stl  = 'True' if fmt in ('stl',  'glb') else 'False'

    return f'''
import FreeCAD as App, Part, MeshPart, json, os, math
V = App.Vector

data   = json.load(open(r"{jpath}", encoding="utf-8"))
W, H   = data["width"], data["height"]
cx, cy = W / 2.0, H / 2.0

doc           = App.newDocument("QS")
frame_solids  = []
glass_solids  = []
dep_max       = max((m["depth"] for m in data["members"]), default=65.0)

# ── helper: cross-section face from loops or plain rectangle ─────────
# loops: list of point-lists where each pt is (u, v)
#   u = across the bar  (0 .. bar)  maps to the face-perpendicular axis
#   v = through-wall    (0 .. depth) maps to Z in world space
# For HORIZONTAL member: u → Y (bar straddles centre line), v → Z
# For VERTICAL   member: u → X (bar straddles centre line), v → Z

def _mk_face(pts_2d, plane, bar, depth):
    """
    Build a Part.Face from a list of (u,v) points in the given plane.
    plane: 'H' → YZ plane (u→Y, v→Z);  'V' → XZ plane (u→X, v→Z).
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
            pts.append(pts[0])                     # close the wire
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
    section along each straight polyline edge of `path` — the FreeCAD
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

# ── build each member ────────────────────────────────────────────────
for m in data["members"]:
    bar    = float(m["bar"])
    depth  = float(m["depth"])
    L      = float(m["length"])
    rings  = m.get("rings") or []
    path   = m.get("path")
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
    if {need_step}:
        # FreeCAD 1.1.3: Part.export() on raw, un-added TopoShape objects
        # silently writes a header-only STEP with no geometry. Shapes MUST
        # be assigned to real Part::Feature document objects first.
        # Each member/glass pane keeps its own labeled Part::Feature (not
        # fused/compounded) so the STEP tree shows a discrete hierarchy
        # (head, jamb_left, jamb_right, threshold, glass, ...).
        step_objs = []
        seen_labels = {{}}
        for label, s in all_solids:
            n = seen_labels.get(label, 0)
            seen_labels[label] = n + 1
            obj_name = label if n == 0 else f"{{label}}_{{n}}"
            feat = doc.addObject("Part::Feature", obj_name)
            feat.Label = obj_name
            feat.Shape = s
            step_objs.append(feat)
        doc.recompute()
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

App.closeDocument(doc.Name)
print("FREECAD_DONE", flush=True)
'''


# ══════════════════════════════════════════════════════════════════════
#  HELPERS
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
        r, g, b = int(h[0:2],16)/255, int(h[2:4],16)/255, int(h[4:6],16)/255
    except Exception:
        pass
    hh, s, lv = colorsys.rgb_to_hls(r, g, b)
    if lv < 0.18:
        r, g, b = colorsys.hls_to_rgb(hh, 0.28, s)
    frame.visual.face_colors = [int(r*255), int(g*255), int(b*255), 255]

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