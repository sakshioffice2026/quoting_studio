"""
app/services/model3d_assembly.py
VERSION: 3.1 - deterministic frame alignment

Coordinate contract:
    local section = (u, v), extrusion = w
    horizontal: (u, v, w) -> (w, u, v)
    vertical:   (u, v, w) -> (-u, w, v)

All placement is performed from deterministic member anchors. No transformed
bounding-box centre is used to decide a member centreline.
"""
from __future__ import annotations

import os
import logging
import tempfile
import multiprocessing

logger = logging.getLogger(__name__)

_GLASS_RGBA = (140, 190, 205, 110)
_MIN_DEPTH = 20.0

# Pure rotations; the vertical mapping preserves handedness.
_PERM_H = (
    (0.0, 0.0, 1.0, 0.0),
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)
_PERM_V = (
    (-1.0, 0.0, 0.0, 0.0),
    ( 0.0, 0.0, 1.0, 0.0),
    ( 0.0, 1.0, 0.0, 0.0),
    ( 0.0, 0.0, 0.0, 1.0),
)


def generate_3d_assembly(window, panes, tenant_id=None, fmt="glb", z_up=False) -> bytes:
    fmt = fmt.lower()
    from .frame_assembly import build_members, resolve_profiles

    profiles = resolve_profiles(
        tenant_id,
        getattr(window, "material", "Aluminium"),
        window=window,
    )
    _apply_window_overrides(profiles, window, tenant_id)

    asm = build_members(window, panes, profiles)
    if not asm.members:
        raise RuntimeError("member graph: no members")

    _normalise_assembly_geometry(window, asm)
    real = prepare_sections(asm, profiles)
    logger.info(
        "3D assembly: %d/%d members have real DXF sections",
        real, len(asm.members),
    )

    if fmt == "step":
        return _build_step_isolated(window, asm, z_up=z_up)
    return _build_trimesh(window, asm, fmt)


def _normalise_assembly_geometry(window, asm):
    """
    Last geometry guard before export.

    Frame graph coordinates remain authoritative. This function only corrects
    centreline/boundary invariants and extends an explicit cill symmetrically
    when horn metadata is available.
    """
    W = float(window.width_mm)

    vertical = [
        m for m in asm.members
        if abs(float(m.x2) - float(m.x1)) < 0.5
    ]

    # Centre any mullion exactly on the two-pane frame centre when the member
    # graph contains a single central mullion.
    mullions = [m for m in vertical if getattr(m, "role", "") == "mullion"]
    if len(mullions) == 1:
        m = mullions[0]
        m.x1 = m.x2 = W / 2.0

    # Cill horns: use explicit metadata if supplied by the geometry/profile
    # pipeline. Never invent an arbitrary horn length.
    for m in asm.members:
        if getattr(m, "role", "") != "cill":
            continue
        horn = (
            getattr(m, "horn_length", None)
            or getattr(m, "_horn_length", None)
            or getattr(window, "horn_length_mm", None)
            or 0.0
        )
        try:
            horn = max(0.0, float(horn))
        except (TypeError, ValueError):
            horn = 0.0
        if horn > 0:
            left = min(float(m.x1), float(m.x2))
            right = max(float(m.x1), float(m.x2))
            m.x1 = left - horn
            m.x2 = right + horn
            try:
                m.length = abs(m.x2 - m.x1)
            except Exception:
                pass


def prepare_sections(asm, profiles) -> int:
    real = 0
    cache = {}

    for m in asm.members:
        prof = profiles.get(m.role)
        loops = prof.get("loops")
        key = (
            f"{m.profile_code or m.role}:"
            f"{float(m.bar_width):.4f}x{float(m.depth):.4f}:"
            f"{'L' if loops else 'R'}"
        )

        if key not in cache:
            rings, sec_bar, sec_dep = _section_rings(
                loops, float(m.bar_width), float(m.depth)
            )
            if 0 < sec_dep < _MIN_DEPTH:
                scale = _MIN_DEPTH / sec_dep
                rings = [[(u, v * scale) for u, v in ring] for ring in rings]
                sec_dep = _MIN_DEPTH
            cache[key] = (rings, sec_bar, sec_dep)

        m._rings, m._sec_bar, m._sec_dep = cache[key]
        m._has_dxf = bool(loops)
        m.depth = m._sec_dep
        if loops:
            real += 1

    return real


def _apply_window_overrides(profiles, window, tenant_id):
    import json

    try:
        design = json.loads(getattr(window, "design_json", None) or "{}")
        overrides = design.get("profileRoles", {})
        if not overrides or not tenant_id:
            return

        from ..models.cad_profile import CadProfile

        for role, profile_code in overrides.items():
            if not profile_code:
                continue

            profile = CadProfile.query.filter_by(
                tenant_id=tenant_id,
                code=profile_code,
                is_active=True,
            ).first()
            if not profile:
                continue

            loops = None
            if profile.geometry_json:
                try:
                    loops = json.loads(profile.geometry_json)
                except Exception:
                    loops = None

            profiles.by_role[role] = {
                "code": profile.code,
                "bar": float(profile.bar_width_mm),
                "depth": float(profile.depth_mm),
                "glass_rebate": float(profile.glass_rebate_mm or 20.0),
                "loops": loops,
            }
    except Exception as exc:
        logger.debug("_apply_window_overrides skipped: %s", exc)


def _ring_area(ring):
    total = 0.0
    for i, (x1, y1) in enumerate(ring):
        x2, y2 = ring[(i + 1) % len(ring)]
        total += x1 * y2 - x2 * y1
    return abs(total) * 0.5


def _section_rings(loops, bar, depth):
    rect = (
        [[(0.0, 0.0), (bar, 0.0), (bar, depth), (0.0, depth)]],
        float(bar),
        float(depth),
    )
    if not loops:
        return rect

    rings = []
    for loop in loops:
        points = [(float(x), float(y)) for x, y in loop]
        if len(points) >= 2 and points[0] == points[-1]:
            points.pop()
        if len(points) >= 3:
            rings.append(points)

    if not rings:
        return rect

    rings.sort(key=_ring_area, reverse=True)

    xs = [x for x, _ in rings[0]]
    ys = [y for _, y in rings[0]]
    w = max(xs) - min(xs)
    h = max(ys) - min(ys)

    rotate = (
        abs(w - bar) + abs(h - depth)
        > abs(h - bar) + abs(w - depth)
    )

    if rotate:
        rings = [[(y, x) for x, y in ring] for ring in rings]

    xs = [x for ring in rings for x, _ in ring]
    ys = [y for ring in rings for _, y in ring]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)

    rings = [
        [(x - minx, y - miny) for x, y in ring]
        for ring in rings
    ]
    return rings, float(maxx - minx), float(maxy - miny)


def _prism(trimesh, np, rings, length):
    try:
        import mapbox_earcut as earcut
    except Exception:
        earcut = None

    if earcut is not None:
        try:
            valid = [
                np.asarray(ring, dtype=np.float64)
                for ring in rings if len(ring) >= 3
            ]
            verts2d = np.concatenate(valid, axis=0)
            ends = np.cumsum([len(r) for r in valid]).astype(np.uint32)
            triangles = earcut.triangulate_float64(
                verts2d, ends
            ).reshape(-1, 3)

            n = len(verts2d)
            vertices = np.vstack((
                np.column_stack((verts2d, np.zeros(n))),
                np.column_stack((verts2d, np.full(n, length))),
            ))

            faces = []
            for tri in triangles:
                faces.append((tri[0], tri[2], tri[1]))
                faces.append((tri[0] + n, tri[1] + n, tri[2] + n))

            base = 0
            for ring in valid:
                count = len(ring)
                for i in range(count):
                    a = base + i
                    b = base + (i + 1) % count
                    faces.append((a, b, b + n))
                    faces.append((a, b + n, a + n))
                base += count

            return trimesh.Trimesh(
                vertices=vertices,
                faces=np.asarray(faces),
                process=True,
            )
        except Exception as exc:
            logger.debug("earcut prism failed: %s", exc)

    xs = [x for ring in rings for x, _ in ring]
    ys = [y for ring in rings for _, y in ring]
    bx, by = max(xs) - min(xs), max(ys) - min(ys)
    solid = trimesh.creation.box(extents=(bx, by, length))
    solid.apply_translation((
        min(xs) + bx / 2.0,
        min(ys) + by / 2.0,
        length / 2.0,
    ))
    return solid


def _extrude_polygon_pts(trimesh, np, pts2d, thickness):
    """Extrude a simple closed 2D polygon (list of (x, y) points, no holes)
    into a solid Trimesh of the given thickness, centred on z=0.

    Uses mapbox-earcut directly (already a project dependency) instead of
    trimesh.creation.extrude_polygon, which requires shapely — not
    installed in this project's requirements.txt.
    """
    import mapbox_earcut as earcut

    pts = np.asarray(pts2d, dtype=np.float64)
    if len(pts) >= 2 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    n = len(pts)

    rings = np.array([n], dtype=np.uint32)
    tri_idx = earcut.triangulate_float64(pts, rings).reshape(-1, 3)

    half = thickness / 2.0
    top = np.column_stack([pts, np.full(n, half)])
    bot = np.column_stack([pts, np.full(n, -half)])
    vertices = np.vstack([top, bot])

    faces = []
    for a, b, c in tri_idx:
        faces.append([a, b, c])                       # top (CCW, +Z)
        faces.append([n + c, n + b, n + a])            # bottom (reversed)
    for i in range(n):
        j = (i + 1) % n
        # side wall quad -> 2 triangles, outward-facing
        faces.append([i, j, n + j])
        faces.append([i, n + j, n + i])

    mesh = trimesh.Trimesh(vertices=vertices, faces=np.array(faces), process=True)
    if mesh.volume < 0:
        mesh.invert()
    return mesh


def _build_trimesh(window, asm, fmt):
    import numpy as np
    import trimesh

    W = float(window.width_mm)
    H = float(window.height_mm)
    cx, cy = W / 2.0, H / 2.0

    fr, fg, fb = _frame_rgb(
        getattr(window, "frame_colour_hex", "#6a6a6c")
    )
    frame_colour = [
        int(fr * 255), int(fg * 255), int(fb * 255), 255
    ]

    frame_meshes = []
    for m in asm.members:
        mesh = _member_mesh(
            trimesh, np, m,
            m._rings, m._sec_bar, m._sec_dep,
            cx, cy,
        )
        if mesh is not None and len(mesh.faces):
            frame_meshes.append(mesh)

    if not frame_meshes:
        raise RuntimeError("no frame meshes built")

    frame = trimesh.util.concatenate(frame_meshes)
    frame.visual.face_colors = frame_colour
    meshes = [frame]

    frame_ref = max(
        (
            float(m.depth)
            for m in asm.members
            if m.role in (
                "head", "jamb", "mullion", "transom",
                "sash", "outer_frame",
            )
        ),
        default=_MIN_DEPTH,
    )
    glass_z = max(frame_ref - 24.0, frame_ref * 0.35)

    for glass in asm.glass:
        gx = float(glass.x) + float(glass.w) / 2.0 - cx
        gy = float(glass.y) + float(glass.h) / 2.0 - cy

        # Same fix as _build_step(): a circular/arched/gothic frame already
        # has this pane's polygon clipped to the ring's inner ellipse/arc
        # in glass.clip_path — this box path was ignoring it and always
        # extruding the full rectangular glass.w x glass.h box, which is
        # the rectangle poking out past the round frame in the 3D viewer
        # (GLB). Build the clipped polygon when available; only fall back
        # to a plain box when there's no clip_path (genuinely rectangular
        # pane).
        clip_pts = getattr(glass, 'clip_path', None)

        if glass.infill == "panel":
            thickness = float(glass.thickness)
            z_pos = frame_ref * 0.5
            colour = frame_colour
        else:
            thickness = 8.0
            z_pos = glass_z
            colour = list(_GLASS_RGBA)

        if clip_pts and len(clip_pts) >= 3:
            pts2d = [(float(px) - cx, float(py) - cy) for px, py in clip_pts]
            mesh = _extrude_polygon_pts(trimesh, np, pts2d, thickness)
            mesh.apply_translation((0, 0, z_pos - thickness / 2.0))
        else:
            mesh = trimesh.creation.box(
                extents=(
                    max(float(glass.w), 1.0),
                    max(float(glass.h), 1.0),
                    thickness,
                )
            )
            mesh.apply_translation((gx, gy, z_pos))

        mesh.visual.face_colors = colour
        meshes.append(mesh)

    if fmt == "glb":
        return trimesh.Scene(meshes).export(file_type="glb")
    if fmt == "stl":
        return trimesh.util.concatenate(meshes).export(file_type="stl")
    raise ValueError(f"unsupported fmt: {fmt}")


def _member_mesh(trimesh, np, m, rings, sec_bar, sec_dep, cx, cy):
    """
    Deterministic placement.

    Horizontal:
        member boundary starts at min(x1, x2)
        member centreline is y1
        profile u=0 starts at centreline-sec_bar/2

    Vertical:
        member centreline is x1
        member boundary starts at min(y1, y2)
        transformed u=0 is explicitly mapped to centreline+sec_bar/2
        because X=-u under _PERM_V.
    """
    length = float(m.length)
    if length < 1.0:
        return None

    solid = _prism(trimesh, np, rings, length)
    if solid is None:
        return None

    horizontal = abs(float(m.y2) - float(m.y1)) < 0.5

    if horizontal:
        solid.apply_transform(np.asarray(_PERM_H))
        x_start = min(float(m.x1), float(m.x2)) - cx
        y_start = float(m.y1) - cy - sec_bar / 2.0
        # After _PERM_H, local u maps to world Y and local v to world Z.
        solid.apply_translation((x_start, y_start, 0.0))
    else:
        solid.apply_transform(np.asarray(_PERM_V))
        x_centre = float(m.x1) - cx
        y_start = min(float(m.y1), float(m.y2)) - cy
        # Local u=0 maps to X=0 before translation; therefore place it at
        # centreline + sec_bar/2 so u in [0,bar] spans centreline symmetrically.
        solid.apply_translation((
            x_centre + sec_bar / 2.0,
            y_start,
            0.0,
        ))

    return solid


class _StepWindow:
    """Minimal picklable stand-in for the ORM `window` object, carrying only
    the scalar fields `_build_step` actually reads. Passing the real
    SQLAlchemy `window` across a process boundary risks pickling failures
    and detached-session errors when the child touches a lazy-loaded
    attribute; this avoids both."""
    __slots__ = ("width_mm", "height_mm", "frame_colour_hex")

    def __init__(self, window):
        self.width_mm = float(window.width_mm)
        self.height_mm = float(window.height_mm)
        self.frame_colour_hex = getattr(window, "frame_colour_hex", "#6a6a6c")


def _step_worker(window, asm, z_up, conn):
    """Runs in a child process (spawned via multiprocessing, which works on
    Windows unlike os.fork). Isolates cadquery/OCP's native CAD-kernel
    calls — long, GIL-holding C calls for the boolean cuts/extrudes behind
    circular-window clipping — so they can never stall the Flask worker's
    own event loop/thread pool while running."""
    try:
        data = _build_step(window, asm, z_up=z_up)
        conn.send((True, data))
    except Exception as exc:  # pragma: no cover - defensive, re-raised in parent
        conn.send((False, f"{type(exc).__name__}: {exc}"))
    finally:
        conn.close()


def _build_step_isolated(window, asm, z_up=False, timeout=180):
    """
    Runs `_build_step` in a separate OS process instead of the Flask
    worker's own process/thread.

    Why: cadquery/OCP's native CAD-kernel calls (boolean cuts/extrudes,
    heaviest for circular-window mullion/glass clipping) are long CPU-bound
    C calls that hold the GIL for their duration. Running them in-process
    means one heavy STEP build stalls every other in-flight request on the
    same server (visible as requests stuck "Pending"). A child process has
    its own interpreter/GIL, so the parent (and every other request it is
    serving) stays responsive while this runs. Uses multiprocessing's
    'spawn' start method, which — unlike os.fork() — works on Windows.
    """
    step_window = _StepWindow(window)
    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_step_worker,
        args=(step_window, asm, z_up, child_conn),
        daemon=True,
    )
    proc.start()
    child_conn.close()
    try:
        if not parent_conn.poll(timeout):
            proc.terminate()
            proc.join(5)
            raise RuntimeError(
                f"STEP build timed out after {timeout}s (child process killed)"
            )
        ok, payload = parent_conn.recv()
    finally:
        parent_conn.close()
        proc.join(5)

    if not ok:
        raise RuntimeError(f"STEP build failed in child process: {payload}")
    return payload


def _build_step(window, asm, z_up=False):
    try:
        import cadquery as cq
    except ImportError:
        raise RuntimeError("STEP requires cadquery (OCP kernel).")

    W = float(window.width_mm)
    H = float(window.height_mm)
    cx, cy = W / 2.0, H / 2.0
    r, g, b = _frame_rgb(
        getattr(window, "frame_colour_hex", "#6a6a6c")
    )

    assembly = cq.Assembly()
    count = 0

    def zup(solid):
        if not z_up:
            return solid
        return solid.rotate((0, 0, 0), (1, 0, 0), 90)

    for m in asm.members:
        try:
            solid = _member_solid_cq(
                cq, m, m._rings, m._sec_bar, m._sec_dep, cx, cy
            )
        except Exception as exc:
            logger.warning(
                "cq member %s failed: %s",
                getattr(m, "id", "?"), exc,
            )
            solid = None

        if solid is not None:
            count += 1
            assembly.add(
                zup(solid),
                name=f"{m.role}_{m.id}",
                color=cq.Color(r, g, b),
            )

    if count == 0:
        raise RuntimeError("no frame solids built")

    frame_ref = max(
        (
            float(m.depth)
            for m in asm.members
            if m.role in (
                "head", "jamb", "mullion", "transom",
                "sash", "outer_frame",
            )
        ),
        default=_MIN_DEPTH,
    )
    glass_z = max(frame_ref - 24.0, frame_ref * 0.35)

    for i, glass in enumerate(asm.glass):
        gx = float(glass.x) + float(glass.w) / 2.0 - cx
        gy = float(glass.y) + float(glass.h) / 2.0 - cy

        # For a circular/arched/gothic frame, frame_assembly.py already
        # clips this pane's polygon to the ring's inner ellipse/arc
        # (asm's GlassCell.clip_path) so it never pokes out past the round
        # frame. This box-extrusion path was ignoring clip_path entirely
        # and always building a plain rectangular box from glass.w/glass.h
        # instead — which is exactly the flat rectangular plate visible
        # sticking out past the ring in the STEP/DXF output. Build the
        # clipped polygon when one is available; only fall back to the
        # plain box when there's no clip_path (rectangular/arched-free
        # frames, where the pane genuinely is a rectangle).
        clip_pts = getattr(glass, 'clip_path', None)

        if glass.infill == "panel":
            thickness = float(glass.thickness)
            z_pos = frame_ref * 0.5
            colour = cq.Color(r, g, b)
        else:
            thickness = 8.0
            z_pos = glass_z + 4.0
            colour = cq.Color(0.55, 0.75, 0.80, 0.35)

        if clip_pts and len(clip_pts) >= 3:
            pts = [(float(px) - cx, float(py) - cy) for px, py in clip_pts]
            solid = (
                cq.Workplane("XY")
                .polyline(pts)
                .close()
                .extrude(thickness)
                .translate((0, 0, z_pos - thickness / 2.0))
            )
        elif glass.infill == "panel":
            solid = (
                cq.Workplane("XY")
                .box(float(glass.w), float(glass.h), thickness)
                .translate((gx, gy, z_pos))
            )
        else:
            solid = (
                cq.Workplane("XY")
                .box(float(glass.w), float(glass.h), thickness)
                .translate((gx, gy, z_pos))
            )

        assembly.add(zup(solid), name=f"glass_{i + 1}", color=colour)

    with tempfile.NamedTemporaryFile(
        suffix=".step", delete=False
    ) as handle:
        path = handle.name

    try:
        assembly.export(path)
        with open(path, "rb") as handle:
            return handle.read()
    finally:
        _rm(path)


def _simplify_ring(points, tol=1e-4, collinear_tol=1e-8):
    if len(points) < 3:
        return points

    kept = []
    for p in points:
        if not kept:
            kept.append(p)
            continue
        dx = p[0] - kept[-1][0]
        dy = p[1] - kept[-1][1]
        if dx * dx + dy * dy > tol * tol:
            kept.append(p)

    if len(kept) >= 2:
        dx = kept[0][0] - kept[-1][0]
        dy = kept[0][1] - kept[-1][1]
        if dx * dx + dy * dy <= tol * tol:
            kept.pop()

    if len(kept) < 3:
        return kept

    out = []
    n = len(kept)
    for i in range(n):
        a = kept[(i - 1) % n]
        b = kept[i]
        c = kept[(i + 1) % n]
        cross = (
            (b[0] - a[0]) * (c[1] - b[1])
            - (b[1] - a[1]) * (c[0] - b[0])
        )
        if abs(cross) > collinear_tol:
            out.append(b)

    return out if len(out) >= 3 else kept


def _member_solid_cq(cq, m, rings, sec_bar, sec_dep, cx, cy):
    """
    CadQuery implementation of the exact same anchor contract as trimesh.

    No bounding-box centre is used for horizontal or vertical placement.
    Bounding boxes are only unnecessary geometry inspection and therefore are
    deliberately absent from placement.
    """
    length = float(m.length)
    if length < 1.0:
        return None

    outer = _simplify_ring(
        [(float(x), float(y)) for x, y in rings[0]]
    )
    holes = [
        _simplify_ring([(float(x), float(y)) for x, y in ring])
        for ring in rings[1:]
    ]
    holes = [ring for ring in holes if len(ring) >= 3]

    if len(outer) < 3:
        return None

    solid = (
        cq.Workplane("XY")
        .polyline(outer)
        .close()
        .extrude(length)
    )

    for hole in holes:
        try:
            hole_solid = (
                cq.Workplane("XY")
                .polyline(hole)
                .close()
                .extrude(length)
            )
            solid = solid.cut(hole_solid)
        except Exception:
            pass

    horizontal = abs(float(m.y2) - float(m.y1)) < 0.5

    if horizontal:
        # (u,v,w) -> (w,u,v): Z(length)->X, X(u)->Y, Y(v)->Z
        solid = solid.rotate((0, 0, 0), (0, 1, 0), 90)
        solid = solid.rotate((0, 0, 0), (1, 0, 0), 90)

        x_start = min(float(m.x1), float(m.x2)) - cx
        y_start = float(m.y1) - cy - sec_bar / 2.0
        return solid.translate((x_start, y_start, 0.0))

    # (u,v,w) -> (-u,w,v):
    # first Z(length)->Y, then orient u so that the final world X=-u.
    solid = solid.rotate((0, 0, 0), (1, 0, 0), -90)

    # After the rotation above CadQuery gives X=u, Y=w, Z=-v.
    # Rotate 180° around Y to obtain X=-u and Z=v.
    solid = solid.rotate((0, 0, 0), (0, 1, 0), 180)

    x_centre = float(m.x1) - cx
    y_start = min(float(m.y1), float(m.y2)) - cy

    return solid.translate((
        x_centre + sec_bar / 2.0,
        y_start,
        0.0,
    ))


def _frame_rgb(hex_colour):
    try:
        value = (hex_colour or "#6a6a6c").lstrip("#")
        return (
            int(value[0:2], 16) / 255.0,
            int(value[2:4], 16) / 255.0,
            int(value[4:6], 16) / 255.0,
        )
    except Exception:
        return 0.42, 0.42, 0.44


def _rm(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass