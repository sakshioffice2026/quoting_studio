"""
3D window/door model generator.

Builds a true 3D solid from the parametric 2D model (frame + pane cells) using
the OpenCASCADE kernel (via cadquery), then exports to:
  - STEP (.step)  — B-rep CAD standard for SolidWorks / Fusion / BricsCAD / CAM
  - STL  (.stl)   — mesh for 3D printing
  - GLB  (.glb)   — glTF binary for web 3D viewers

Construction methods (both implemented):
  - 'extrude' : each frame bar + mullion is a solid box extruded to profile depth,
                glass panels sit in the rebate. Fast, robust.
  - 'sweep'   : hollow box profile swept to give a realistic frame section with
                wall thickness (more detailed, heavier).

The 'extrude' concept: the 2D elevation (frame outline + pane grid) is projected
into 3D by giving every bar the profile depth along the Z axis. This is the same
principle as Three.js ExtrudeGeometry — a 2D shape + a depth = a 3D solid.
"""
import io
import os
import logging
import tempfile

logger = logging.getLogger(__name__)

_DEFAULT_BAR    = 40.0
_DEFAULT_WALL   = 4.0
_DEFAULT_DEPTH  = 52.0
_GLASS_THICK    = 24.0   # double glazing unit thickness


# ================================================================
#  PUBLIC ENTRY
# ================================================================

def generate_3d(window, panes, tenant_id=None, fmt='step', method='auto', z_up=False) -> bytes:
    """
    Generate a 3D model of the window.
    fmt    : 'step' | 'stl' | 'glb'
    method : 'auto' | 'profile' | 'extrude' | 'sweep'
             'auto' uses the profile-library DXF cross-section when the default
             profile has traced geometry (real extruded profile with chambers),
             otherwise falls back to 'extrude' boxes.

    Uses the cadquery (OpenCASCADE) kernel when available — required for STEP
    (true B-rep) output. Falls back to a pure-trimesh mesh builder for STL/GLB
    so the web 3D viewer works even where the OCP binary isn't installed
    (e.g. Python 3.14 with no cadquery-ocp wheels yet).
    """
    fmt = fmt.lower()

    # ── FreeCAD assembly — best quality for GLB/STL (real B-Rep) ───────
    # NOTE: FreeCAD's STEP export has been unreliable (empty 20-entity files),
    # so STEP is routed to the cadquery assembly path below instead.
    if method in ('auto', 'assembly', 'freecad') and fmt != 'step':
        try:
            from .model3d_freecad import generate_3d_freecad, _find_freecad
            if _find_freecad():
                data = generate_3d_freecad(window, panes,
                                            tenant_id=tenant_id, fmt=fmt)
                if data:
                    logger.info('FreeCAD 3D OK: fmt=%s bytes=%d', fmt, len(data))
                    return data
            else:
                logger.debug('FreeCAD not found — using trimesh assembly')
        except Exception as exc:
            logger.warning('FreeCAD build failed (%s) — trimesh fallback', exc)

    # ── Trimesh assembly — fallback (no FreeCAD needed) ─────────────────
    if method in ('auto', 'assembly'):
        try:
            from .model3d_assembly import generate_3d_assembly
            data = generate_3d_assembly(window, panes, tenant_id=tenant_id, fmt=fmt, z_up=z_up)
            if data:
                logger.info('trimesh assembly OK: fmt=%s bytes=%d', fmt, len(data))
                return data
        except Exception as exc:
            logger.warning('trimesh assembly failed (%s) — legacy fallback', exc)
            import traceback
            logger.warning('assembly traceback:\n%s', traceback.format_exc())

    prof = _get_profile(tenant_id, getattr(window, 'material', 'Aluminium'))

    if method in ('auto', 'profile'):
        # profile extrusion requires traced geometry; otherwise use boxes
        if not prof.get('loops'):
            method = 'extrude'
        elif method == 'auto':
            method = 'profile'
    if method == 'extrude':
        prof = dict(prof, loops=None)      # explicit box mode ignores geometry

    have_cq = False
    try:
        import cadquery  # noqa
        have_cq = True
    except ImportError:
        pass

    # STEP absolutely requires the CAD kernel
    if fmt == 'step':
        if not have_cq:
            logger.error('STEP export needs cadquery — not installed')
            raise RuntimeError('STEP export requires cadquery. Run: pip install cadquery --break-system-packages')
        try:
            assembly = _build_assembly(window, panes, prof, method)
            return _export(assembly, 'step')
        except Exception as exc:
            logger.exception('STEP generation failed: %s', exc)
            raise

    # STL / GLB: prefer cadquery (cleaner solids), else trimesh fallback
    if have_cq:
        try:
            assembly = _build_assembly(window, panes, prof, method)
            return _export(assembly, fmt)
        except Exception as exc:
            logger.warning('cadquery %s failed (%s) — trying trimesh fallback', fmt, exc)

    try:
        return _trimesh_build(window, panes, prof, fmt)
    except Exception as exc:
        logger.exception('trimesh 3D fallback failed: %s', exc)
        raise


# ================================================================
#  PROFILE
# ================================================================

def _get_profile(tenant_id, material):
    prof = {'bar': _DEFAULT_BAR, 'wall': _DEFAULT_WALL,
            'depth': _DEFAULT_DEPTH, 'name': 'PWQ-3645', 'loops': None}
    if not tenant_id:
        return prof
    try:
        from ..models.cad_profile import CadProfile
        p = (CadProfile.query
             .filter_by(tenant_id=tenant_id, material=material,
                         is_active=True, is_default=True).first()
             or CadProfile.query.filter_by(tenant_id=tenant_id, is_active=True).first())
        if p:
            prof.update(bar=float(p.bar_width_mm), wall=float(p.wall_thickness_mm),
                        depth=float(p.depth_mm), name=p.name)
            # DXF-traced cross-section: list of loops of [x,y] (mm). When present,
            # the frame is built by extruding this real profile shape.
            if p.geometry_json:
                import json as _json
                try:
                    loops = _json.loads(p.geometry_json)
                    if loops and isinstance(loops, list):
                        prof['loops'] = loops
                except Exception:
                    pass
    except Exception as exc:
        logger.warning('Profile lookup failed: %s', exc)
    return prof


def _profile_polygon(loops):
    """Build a shapely polygon (with holes) from DXF loops, normalised so the
    bbox starts at (0,0). u axis = across the bar, v axis = through the depth.
    Returns (polygon, bar_width, depth) or (None, None, None)."""
    try:
        from shapely.geometry import Polygon  # type: ignore[import]
        rings = []
        for lp in loops:
            pts = [(float(x), float(y)) for x, y in lp]
            if len(pts) >= 3:
                rings.append(pts)
        if not rings:
            return None, None, None
        def ring_area(r):
            s = 0.0
            for i in range(len(r)):
                x1, y1 = r[i]; x2, y2 = r[(i+1) % len(r)]
                s += x1*y2 - x2*y1
            return abs(s) / 2.0
        rings.sort(key=ring_area, reverse=True)
        outer, holes = rings[0], rings[1:]
        poly = Polygon(outer, holes=holes if holes else None)
        if not poly.is_valid:
            poly = poly.buffer(0)          # heal self-intersections
        if poly.is_empty:
            return None, None, None
        minx, miny, maxx, maxy = poly.bounds
        from shapely.affinity import translate  # type: ignore[import]
        poly = translate(poly, -minx, -miny)
        return poly, (maxx - minx), (maxy - miny)
    except Exception as exc:
        logger.warning('Profile polygon build failed: %s', exc)
        return None, None, None


# ================================================================
#  MATERIAL COLOURS
# ================================================================

def _frame_rgb(hex_colour):
    """Convert #RRGGBB to (r,g,b) floats 0-1 for cadquery Color."""
    try:
        h = (hex_colour or '#6a6a6c').lstrip('#')
        return (int(h[0:2],16)/255, int(h[2:4],16)/255, int(h[4:6],16)/255)
    except Exception:
        return (0.62, 0.62, 0.64)


# ================================================================
#  ASSEMBLY BUILDER
# ================================================================

def _build_assembly(window, panes, prof, method):
    import cadquery as cq

    W     = float(window.width_mm)
    H     = float(window.height_mm)
    bar   = prof['bar']
    wall  = prof['wall']
    depth = prof['depth']
    r,g,b = _frame_rgb(getattr(window, 'frame_colour_hex', '#6a6a6c'))

    asm = cq.Assembly()

    # ---- FRAME ----
    if method == 'profile' and prof.get('loops'):
        frame = _frame_profile_cq(cq, W, H, prof)
        if frame is None:
            frame = _frame_extrude(cq, W, H, bar, depth)
        else:
            poly, gb, gd = _profile_polygon(prof['loops'])
            if gb and gd:
                bar, depth = gb, gd        # keep glass insets consistent
    elif method == 'sweep':
        frame = _frame_sweep(cq, W, H, bar, wall, depth)
    else:
        frame = _frame_extrude(cq, W, H, bar, depth)

    # ---- MULLIONS (between panes) ----
    mullions = _mullions(cq, W, H, bar, depth, panes)
    if mullions is not None:
        frame = frame.union(mullions)

    asm.add(frame, name="frame", color=cq.Color(r, g, b))

    # ---- GLASS PANELS / SOLID PANELS ----
    for i, pane in enumerate(panes):
        infill_el = _glass_panel(cq, W, H, bar, depth, pane)
        if infill_el is not None:
            if getattr(pane, 'infill', 'glass') == 'panel':
                # solid door panel — frame colour, opaque
                asm.add(infill_el, name=f"panel_{i+1}", color=cq.Color(r, g, b))
            else:
                asm.add(infill_el, name=f"glass_{i+1}",
                        color=cq.Color(0.55, 0.75, 0.80, 0.35))

    # ---- GLAZING BARS (Georgian) from design_json ----
    bars = _glazing_bars_from_design(cq, window, W, H, bar, depth)
    if bars is not None:
        asm.add(bars, name="glazing_bars", color=cq.Color(r, g, b))

    return asm


def _glazing_bars_from_design(cq, window, W, H, bar, depth):
    """Parse design_json for glazing bars and build thin 3D bar solids."""
    import json
    dj = getattr(window, 'design_json', None)
    if not dj:
        return None
    try:
        design = json.loads(dj) if isinstance(dj, str) else dj
    except Exception:
        return None
    result = None
    bar_z = depth * 0.5
    for pane in design.get('panes', []):
        gbars = pane.get('glazingBars', []) or []
        if not gbars:
            continue
        px = pane.get('x', 0)*W + bar
        py = pane.get('y', 0)*H + bar
        pw = pane.get('w', 1)*W - 2*bar
        ph = pane.get('h', 1)*H - 2*bar
        for gb in gbars:
            t = float(gb.get('thickness', 18))
            if gb.get('type') == 'vertical':
                gx = px + pw*float(gb.get('pos', 0.5)) - W/2
                cy = py + ph/2 - H/2
                solid = cq.Workplane("XY").box(t, ph, depth*0.7).translate((gx, cy, bar_z))
            else:
                gy = py + ph*float(gb.get('pos', 0.5)) - H/2
                cx = px + pw/2 - W/2
                solid = cq.Workplane("XY").box(pw, t, depth*0.7).translate((cx, gy, bar_z))
            result = solid if result is None else result.union(solid)
    return result


def _frame_profile_cq(cq, W, H, prof):
    """Frame from the profile library's traced DXF cross-section (cadquery).
    Each member is the real polygon (outer + hole loops) extruded to length,
    rotated into place — same orientation scheme as the trimesh builder.
    Returns a Workplane solid, or None on any failure (caller falls back)."""
    try:
        poly, gb, gd = _profile_polygon(prof['loops'])
        if poly is None:
            return None
        bar = gb

        def _wp_from_poly(length):
            outer = list(poly.exterior.coords)[:-1]
            solid = cq.Workplane('XY').polyline(outer).close().extrude(length)
            # holes must be CUT, not co-extruded (co-extrusion makes them solid)
            for ring in poly.interiors:
                pts = list(ring.coords)[:-1]
                hole = cq.Workplane('XY').polyline(pts).close().extrude(length)
                solid = solid.cut(hole)
            return solid

        import math
        def _place(solid, rots, target_min):
            for axis, deg in rots:
                solid = solid.rotate((0,0,0), axis, deg)
            bb = solid.val().BoundingBox()
            solid = solid.translate((target_min[0]-bb.xmin,
                                     target_min[1]-bb.ymin,
                                     target_min[2]-bb.zmin))
            return solid

        bot = _place(_wp_from_poly(W), [((0,1,0),90), ((1,0,0),90)],
                     (-W/2, -H/2, 0))
        # top = bottom rotated 180° in the window plane
        topb = bot.rotate((0,0,0), (0,0,1), 180)
        left = _place(_wp_from_poly(H-2*bar), [((1,0,0),-90)],
                      (-W/2, -H/2+bar, 0))
        rightb = left.rotate((0,0,0), (0,0,1), 180)

        return bot.union(topb).union(left).union(rightb)
    except Exception as exc:
        logger.warning('cadquery profile frame failed: %s', exc)
        return None


def _frame_extrude(cq, W, H, bar, depth):
    """Four frame bars as boxes, extruded to depth (fast method)."""
    cx, cy = 0, 0
    bottom = cq.Workplane("XY").box(W, bar, depth).translate((cx, -H/2+bar/2, depth/2))
    top    = cq.Workplane("XY").box(W, bar, depth).translate((cx,  H/2-bar/2, depth/2))
    left   = cq.Workplane("XY").box(bar, H-2*bar, depth).translate((-W/2+bar/2, cy, depth/2))
    right  = cq.Workplane("XY").box(bar, H-2*bar, depth).translate(( W/2-bar/2, cy, depth/2))
    return bottom.union(top).union(left).union(right)


def _frame_sweep(cq, W, H, bar, wall, depth):
    """
    Hollow box profile — outer frame minus inner void, giving a realistic
    section with wall thickness. Built by boolean subtraction.
    """
    solid = _frame_extrude(cq, W, H, bar, depth)
    # carve a hollow chamber in each bar (inner void)
    inner_d = depth - 2*wall
    # bottom void
    voids = []
    voids.append(cq.Workplane("XY").box(W-2*wall, bar-2*wall, inner_d)
                 .translate((0, -H/2+bar/2, depth/2)))
    voids.append(cq.Workplane("XY").box(W-2*wall, bar-2*wall, inner_d)
                 .translate((0,  H/2-bar/2, depth/2)))
    voids.append(cq.Workplane("XY").box(bar-2*wall, H-2*bar-2*wall, inner_d)
                 .translate((-W/2+bar/2, 0, depth/2)))
    voids.append(cq.Workplane("XY").box(bar-2*wall, H-2*bar-2*wall, inner_d)
                 .translate(( W/2-bar/2, 0, depth/2)))
    for v in voids:
        try:
            solid = solid.cut(v)
        except Exception:
            pass
    return solid


def _mullions(cq, W, H, bar, depth, panes):
    """Vertical/horizontal divider bars at pane split boundaries."""
    ib = bar * 0.6
    result = None
    seen_x, seen_y = set(), set()

    for pane in panes:
        rx = (pane.x_norm + pane.w_norm) * W
        if bar+1 < rx < W-bar-1 and round(rx) not in seen_x:
            seen_x.add(round(rx))
            mx = rx - W/2          # centre-relative X
            m = cq.Workplane("XY").box(ib, H-2*bar, depth).translate((mx, 0, depth/2))
            result = m if result is None else result.union(m)
        ty = (pane.y_norm + pane.h_norm) * H
        if bar+1 < ty < H-bar-1 and round(ty) not in seen_y:
            seen_y.add(round(ty))
            my = ty - H/2
            m = cq.Workplane("XY").box(W-2*bar, ib, depth).translate((0, my, depth/2))
            result = m if result is None else result.union(m)
    return result


def _glass_panel(cq, W, H, bar, depth, pane):
    """Glass/panel infill sitting in the rebate, centred in profile depth.
    Per-edge insets: outer edges tuck into the frame rebate; internal (shared)
    edges meet the mullion face exactly — so there's no gap to the divider.
    Solid door panels ('infill'=='panel') are returned as a thick opaque board."""
    ib   = bar * 0.6           # mullion width (must match _mullions)
    half = ib / 2              # internal-edge inset → meets mullion face
    edge = bar * 0.5           # outer-edge inset → sits in frame rebate
    eps  = 0.001

    insL = edge if pane.x_norm <= eps                 else half
    insT = edge if pane.y_norm <= eps                 else half
    insR = edge if pane.x_norm + pane.w_norm >= 1-eps else half
    insB = edge if pane.y_norm + pane.h_norm >= 1-eps else half

    pw = pane.w_norm * W - insL - insR
    ph = pane.h_norm * H - insT - insB
    if pw <= 0 or ph <= 0:
        return None

    # centre-relative position, accounting for asymmetric insets
    left   = pane.x_norm * W + insL
    bottom = pane.y_norm * H + insT
    cx = left   + pw/2 - W/2
    cy = bottom + ph/2 - H/2

    infill = getattr(pane, 'infill', 'glass')
    if infill == 'panel':
        # solid door panel — full-depth board, opaque
        return cq.Workplane("XY").box(pw, ph, depth*0.6).translate((cx, cy, depth*0.5))
    # glass — thin sheet centred in profile depth
    cz = depth * 0.45
    return cq.Workplane("XY").box(pw, ph, _GLASS_THICK*0.4).translate((cx, cy, cz))


# ================================================================
#  EXPORT
# ================================================================

def _export(assembly, fmt: str) -> bytes:
    import cadquery as cq
    from cadquery import exporters

    fmt = fmt.lower()

    if fmt == 'step':
        with tempfile.NamedTemporaryFile(suffix='.step', delete=False) as tf:
            path = tf.name
        try:
            assembly.export(path)
            with open(path, 'rb') as f:
                data = f.read()
            return data
        finally:
            _rm(path)

    # For STL / GLB we need a single combined solid mesh
    combined = None
    for child in assembly.children:
        shp = child.obj
        combined = shp if combined is None else combined.union(shp)

    if fmt == 'stl':
        with tempfile.NamedTemporaryFile(suffix='.stl', delete=False) as tf:
            path = tf.name
        try:
            exporters.export(combined, path)
            with open(path, 'rb') as f:
                return f.read()
        finally:
            _rm(path)

    if fmt == 'glb':
        # export to STL first, convert to GLB via trimesh (keeps it dependency-light)
        with tempfile.NamedTemporaryFile(suffix='.stl', delete=False) as tf:
            stl_path = tf.name
        glb_path = stl_path.replace('.stl', '.glb')
        try:
            exporters.export(combined, stl_path)
            import trimesh
            mesh = trimesh.load(stl_path)
            mesh.export(glb_path)
            with open(glb_path, 'rb') as f:
                return f.read()
        finally:
            _rm(stl_path); _rm(glb_path)

    raise ValueError(f'Unsupported 3D format: {fmt}')


def _rm(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass



# ================================================================
#  PURE-TRIMESH FALLBACK  (no OpenCASCADE needed — STL / GLB only)
# ================================================================

def _trimesh_build(window, panes, prof, fmt: str) -> bytes:
    import trimesh
    import numpy as np

    W     = float(window.width_mm)
    H     = float(window.height_mm)
    bar   = prof['bar']
    depth = prof['depth']

    def box(cx, cy, cz, w, h, d):
        b = trimesh.creation.box(extents=[w, h, d])
        b.apply_translation([cx, cy, cz])
        return b

    fr, fg, fb = _frame_rgb(getattr(window, 'frame_colour_hex', '#6a6a6c'))
    frame_col = [int(fr*255), int(fg*255), int(fb*255), 255]

    parts = []

    # ---- FRAME: real profile extrusion when DXF geometry is available ----
    poly = None
    if prof.get('loops'):
        poly, gb, gd = _profile_polygon(prof['loops'])
        if poly is not None and gb and gd:
            bar, depth = gb, gd            # trust the traced geometry's true size

    if poly is not None:
        # Extrude the cross-section for each member, then rotate into place.
        # Convention: window plane = XY (X width, Y height), depth along +Z.
        # Profile local: u (poly x) across the bar, v (poly y) through depth.
        def member(length):
            return trimesh.creation.extrude_polygon(poly, length)

        def rot(mesh, axis, deg, point=(0,0,0)):
            Rm = trimesh.transformations.rotation_matrix(
                np.radians(deg), axis, point)
            mesh.apply_transform(Rm)
            return mesh

        # bottom: extrusion +Z → +X (rot -90° about Y? use mapping via two rotations)
        bot = member(W)
        # (u,v,l) → (l,u,v): rotate 90° about Z then 90° about X gives improper —
        # instead compose proper rotations: first rot +90° about Y maps z→x
        # (x,y,z)→(z,y,-x); then rot +90° about X maps (x,y,z)→(x,-z,y).
        rot(bot, (0,1,0), 90); rot(bot, (1,0,0), 90)
        # snap bounds into position: extrusion → X, u → Y, v → Z
        b0 = bot.bounds
        bot.apply_translation([-W/2 - b0[0][0], -H/2 - b0[0][1], 0 - b0[0][2]])

        top = bot.copy()
        rot(top, (0,0,1), 180)             # 180° in the window plane

        left = member(H - 2*bar)
        rot(left, (1,0,0), -90)            # extrusion +Z → +Y ; (x,y,z)→(x,z,-y)
        l0 = left.bounds
        left.apply_translation([-W/2 - l0[0][0], -H/2 + bar - l0[0][1], 0 - l0[0][2]])

        right = left.copy()
        rot(right, (0,0,1), 180)

        parts.extend([bot, top, left, right])
    else:
        # fallback: simple box frame
        parts.append(box(0, -H/2+bar/2, depth/2, W, bar, depth))
        parts.append(box(0,  H/2-bar/2, depth/2, W, bar, depth))
        parts.append(box(-W/2+bar/2, 0, depth/2, bar, H-2*bar, depth))
        parts.append(box( W/2-bar/2, 0, depth/2, bar, H-2*bar, depth))

    # mullions
    ib = bar * 0.6
    seen_x, seen_y = set(), set()
    for pane in panes:
        rx = (pane.x_norm + pane.w_norm) * W
        if bar+1 < rx < W-bar-1 and round(rx) not in seen_x:
            seen_x.add(round(rx))
            parts.append(box(rx - W/2, 0, depth/2, ib, H-2*bar, depth))
        ty = (pane.y_norm + pane.h_norm) * H
        if bar+1 < ty < H-bar-1 and round(ty) not in seen_y:
            seen_y.add(round(ty))
            parts.append(box(0, ty - H/2, depth/2, W-2*bar, ib, depth))

    frame = trimesh.util.concatenate(parts)
    frame.visual.face_colors = frame_col

    meshes = [frame]
    # glass panels / solid panels
    ib   = bar * 0.6
    half = ib / 2
    edge = bar * 0.5
    eps  = 0.001
    for pane in panes:
        insL = edge if pane.x_norm <= eps                 else half
        insT = edge if pane.y_norm <= eps                 else half
        insR = edge if pane.x_norm + pane.w_norm >= 1-eps else half
        insB = edge if pane.y_norm + pane.h_norm >= 1-eps else half
        pw = pane.w_norm * W - insL - insR
        ph = pane.h_norm * H - insT - insB
        if pw <= 0 or ph <= 0:
            continue
        left   = pane.x_norm * W + insL
        bottom = pane.y_norm * H + insT
        cx = left + pw/2 - W/2
        cy = bottom + ph/2 - H/2
        if getattr(pane, 'infill', 'glass') == 'panel':
            g = box(cx, cy, depth*0.5, pw, ph, depth*0.6)
            g.visual.face_colors = [int(fr*255), int(fg*255), int(fb*255), 255]
        else:
            g = box(cx, cy, depth*0.45, pw, ph, 8)
            g.visual.face_colors = [140, 190, 205, 120]
        meshes.append(g)

    # glazing bars from design_json
    import json as _json
    dj = getattr(window, 'design_json', None)
    if dj:
        try:
            design = _json.loads(dj) if isinstance(dj, str) else dj
            for pane in design.get('panes', []):
                gbars = pane.get('glazingBars', []) or []
                if not gbars: continue
                px = pane.get('x',0)*W + bar; py = pane.get('y',0)*H + bar
                pw = pane.get('w',1)*W - 2*bar; ph = pane.get('h',1)*H - 2*bar
                for gb in gbars:
                    t = float(gb.get('thickness',18))
                    if gb.get('type')=='vertical':
                        gx = px + pw*float(gb.get('pos',0.5))
                        b = box(gx - W/2, py+ph/2 - H/2, depth*0.5, t, ph, depth*0.7)
                    else:
                        gy = py + ph*float(gb.get('pos',0.5))
                        b = box(px+pw/2 - W/2, gy - H/2, depth*0.5, pw, t, depth*0.7)
                    b.visual.face_colors = frame_col
                    meshes.append(b)
        except Exception:
            pass

    if fmt == 'glb':
        scene = trimesh.Scene(meshes)
        return scene.export(file_type='glb')
    elif fmt == 'stl':
        combined = trimesh.util.concatenate(meshes)
        return combined.export(file_type='stl')
    raise ValueError(f'trimesh fallback cannot produce {fmt}')