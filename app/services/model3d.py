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
import math
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



# OPTIMIZED: Cache 3D model generation
_MODEL3D_CACHE = {}

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
        clip = getattr(glass, "clip_path", None)
        is_panel = glass.infill == "panel"
        thickness = float(glass.thickness) if is_panel else 8.0
        z_center = frame_ref * 0.5 if is_panel else glass_z
        colour = frame_colour if is_panel else list(_GLASS_RGBA)

        mesh = None
        if clip and len(clip) >= 3:
            # Circular frame: glass was already clipped to the ring's
            # inner-face ellipse in frame_assembly.py — extrude that exact
            # polygon (offset into the same cx/cy-centred space as
            # everything else here) instead of a plain box, so the glass
            # follows the arc instead of poking out at the corners.
            #
            # FIX: dedupe/collinear-strip the raw clip output first (same
            # as the STEP path below) — without this, near-duplicate
            # vertices from the Sutherland-Hodgman clip make _prism() throw,
            # which was silently caught and produced the rectangular glass
            # panel sticking out behind the round frame in the 3D viewer.
            ring2d = _simplify_ring(
                [(float(px) - cx, float(py) - cy) for px, py in clip]
            )
            if len(ring2d) >= 3:
                try:
                    mesh = _prism(trimesh, np, [ring2d], thickness)
                    mesh.apply_translation((0.0, 0.0, z_center - thickness / 2.0))
                except Exception as exc:
                    logger.warning(
                        "clipped glass prism failed, falling back to "
                        "rectangular box: %s", exc
                    )
                    mesh = None

        if mesh is None:
            mesh = trimesh.creation.box(
                extents=(
                    max(float(glass.w), 1.0),
                    max(float(glass.h), 1.0),
                    thickness,
                )
            )
            mesh.apply_translation((gx, gy, z_center))

        mesh.visual.face_colors = colour
        meshes.append(mesh)

    if fmt == "glb":
        return trimesh.Scene(meshes).export(file_type="glb")
    if fmt == "stl":
        return trimesh.util.concatenate(meshes).export(file_type="stl")
    raise ValueError(f"unsupported fmt: {fmt}")


def _path_segment_transform(theta_deg, p0, sec_bar, cx, cy):
    theta = math.radians(theta_deg)
    u_dir = (-math.sin(theta), math.cos(theta))
    tx = p0[0] - cx - u_dir[0] * sec_bar / 2.0
    ty = p0[1] - cy - u_dir[1] * sec_bar / 2.0
    return tx, ty


def _member_mesh_path(trimesh, np, m, rings, sec_bar, sec_dep, cx, cy):
    """Curved member (arched/gothic/circular): sweep the section along
    m.path as a chain of straight sub-prisms, one per polyline edge, each
    using the base horizontal mapping plus an extra Z rotation for that
    segment's own angle — generalises the fixed-angle horizontal/vertical
    placement below to an arbitrary in-plane direction."""
    pts = m.path
    n = len(pts)
    count = n if m.closed else n - 1
    solids = []
    for i in range(count):
        p0 = pts[i]
        p1 = pts[(i + 1) % n] if m.closed else pts[i + 1]
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        seg_len = math.hypot(dx, dy)
        if seg_len < 0.5:
            continue
        theta_deg = math.degrees(math.atan2(dy, dx))

        solid = _prism(trimesh, np, rings, seg_len)
        if solid is None:
            continue
        solid.apply_transform(np.asarray(_PERM_H))
        solid.apply_transform(
            trimesh.transformations.rotation_matrix(
                math.radians(theta_deg), [0, 0, 1]
            )
        )
        tx, ty = _path_segment_transform(theta_deg, p0, sec_bar, cx, cy)
        solid.apply_translation((tx, ty, 0.0))
        solids.append(solid)

    if not solids:
        return None
    return trimesh.util.concatenate(solids)


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

    Curved (m.path set): see _member_mesh_path.
    """
    if getattr(m, "path", None):
        return _member_mesh_path(trimesh, np, m, rings, sec_bar, sec_dep, cx, cy)

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
    own thread pool while running."""
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

    Curved (circular/arched) members are never passed to fused.union() in
    _build_step — that native OCC call can hang forever on curved solids
    without raising, so it is skipped at the source rather than relied on
    to time out here. This 180s limit is now a genuine backstop for
    otherwise-slow builds, not the primary defence against the hang.
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
    failed_ids = []
    frame_solids = []

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

        if solid is None:
            failed_ids.append(getattr(m, "id", "?"))
        else:
            count += 1
            frame_solids.append((m, solid))

    if count == 0:
        raise RuntimeError("no frame solids built")

    if failed_ids:
        raise RuntimeError(
            f"STEP export incomplete — {len(failed_ids)} member(s) failed "
            f"to build and were dropped: {failed_ids}. Refusing to export "
            f"a silently-incomplete model; see server log for the "
            f"underlying cadquery error per member."
        )

    # ── FUSE every member into ONE continuous solid ──────────────────
    # Members used to be added to the assembly individually, each its own
    # separate BREP solid that only TOUCHES its neighbours (ring <->
    # mullion/transom, jamb <-> head, sash <-> frame, ...). Two touching-
    # but-unfused solids share a coincident boundary with no real
    # topological connection between them, so any viewer renders a visible
    # seam/sliver right at that join — this is true regardless of how
    # precisely the member coordinates line up, which is why extending the
    # mullion/transom ends past the ring's touch-point closed most, but not
    # all, of the gap. Boolean-union every member into a single watertight
    # solid so the export has no internal seams at all. Members that fail
    # to union cleanly (rare, but OCC booleans can be fragile on complex
    # profiles) are kept as separate parts rather than aborting the whole
    # export, so a single bad union never blanks the download.
    #
    # FIX HISTORY:
    # 1) fused.union(solid) called once per SEGMENT of a curved member's
    #    own path (many short adjacent segments touching face-to-face) was
    #    the actual hang — a native OCC C call that never raises, it just
    #    sits inside the kernel until the subprocess timeout kills it.
    #    That per-segment chain is fixed in _member_solid_cq_path, which
    #    now returns one Compound per curved member with zero booleans.
    # 2) Skipping ALL union for curved members (this function) was an
    #    over-correction: it stopped the ring from ever being combined
    #    with the straight mullion/transom, so they render as two
    #    disconnected, interpenetrating solids instead of one clean
    #    mitred joint — visible in STEP/DXF as the vertical member
    #    "cutting through" the ring and as bleeding hatch lines in the
    #    projected DXF.
    # A SINGLE union of [fused straight body] + [one curved compound] is a
    # cheap, ordinary boolean — nothing like the O(n) segment chain that
    # hung — so it is safe to attempt once per curved member. Only if that
    # one attempt genuinely raises does the member fall back to a loose,
    # disconnected part.
    def _is_curved(member):
        return bool(getattr(member, "path", None))

    fusable = [(m, s) for m, s in frame_solids if not _is_curved(m)]
    curved = [(m, s) for m, s in frame_solids if _is_curved(m)]
    loose_parts = []

    if fusable:
        fused = fusable[0][1]
        for m, solid in fusable[1:]:
            try:
                fused = fused.union(solid)
            except Exception as exc:
                logger.warning(
                    "frame union failed for %s, keeping as separate part: %s",
                    getattr(m, "id", "?"), exc,
                )
                loose_parts.append((m, solid))
    else:
        fused = None

    for m, solid in curved:
        if fused is None:
            fused = solid
            continue
        try:
            fused = fused.union(solid)
        except Exception as exc:
            logger.warning(
                "curved frame union failed for %s, keeping as separate "
                "part (joint will not be mitred): %s",
                getattr(m, "id", "?"), exc,
            )
            loose_parts.append((m, solid))

    assembly.add(zup(fused), name="frame", color=cq.Color(r, g, b))
    for m, solid in loose_parts:
        assembly.add(
            zup(solid), name=f"{m.role}_{m.id}", color=cq.Color(r, g, b)
        )

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
        clip = getattr(glass, "clip_path", None)
        is_panel = glass.infill == "panel"
        thickness = float(glass.thickness) if is_panel else 8.0
        z_center = frame_ref * 0.5 if is_panel else glass_z + 4.0
        colour = (
            cq.Color(r, g, b) if is_panel
            else cq.Color(0.55, 0.75, 0.80, 0.35)
        )

        solid = None
        if clip and len(clip) >= 3:
            # Circular frame: extrude the exact ellipse-clipped outline
            # (see the GLB/STL branch above) instead of a plain box, so the
            # glass follows the arc instead of poking out at the corners.
            #
            # FIX: the raw Sutherland-Hodgman clip output from
            # _clip_polygon_convex() can contain near-duplicate consecutive
            # points (zero-length edges) right at the rectangle/ellipse
            # intersection vertices. cadquery's polyline().close() throws on
            # those degenerate edges, which was being silently swallowed
            # below and made the glass fall back to a plain W x H box —
            # i.e. a visible rectangle behind the correctly-circular frame
            # ring. Run the same _simplify_ring() dedupe/collinear-strip
            # used for member cross-sections on the clip outline first so
            # the wire is always valid.
            ring2d = _simplify_ring(
                [(float(px) - cx, float(py) - cy) for px, py in clip]
            )
            if len(ring2d) >= 3:
                try:
                    solid = (
                        cq.Workplane("XY")
                        .polyline(ring2d)
                        .close()
                        .extrude(thickness)
                        .translate((0.0, 0.0, z_center - thickness / 2.0))
                    )
                except Exception as exc:
                    # Bumped from debug->warning: this failure is exactly
                    # what causes a circular window to silently ship with
                    # rectangular glass, so it needs to be visible in logs.
                    logger.warning(
                        "clipped glass cq solid failed for glass_%d, "
                        "falling back to rectangular box: %s", i + 1, exc
                    )
                    solid = None

        if solid is None:
            solid = (
                cq.Workplane("XY")
                .box(
                    max(float(glass.w), 1.0),
                    max(float(glass.h), 1.0),
                    thickness,
                )
                .translate((gx, gy, z_center))
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


def _cq_section_solid(cq, outer, holes, length):
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
    return solid


def _cq_section_solid_no_holes(cq, outer, length):
    """Outer-profile-only extrude, no interior hole cut. Used only for
    curved (m.path) members — see _member_solid_cq_path for why."""
    return (
        cq.Workplane("XY")
        .polyline(outer)
        .close()
        .extrude(length)
    )


def _member_solid_cq_path(cq, m, outer, holes, sec_bar, sec_dep, cx, cy):
    """Curved member (arched/gothic/circular): compound of straight
    sub-solids, one per polyline edge of m.path, each built with the same
    base horizontal orientation used for straight horizontal members plus
    an extra Z rotation for that segment's own angle — the cadquery mirror
    of _member_mesh_path so STEP matches the GLB/STL viewer exactly.

    FIX: curved members no longer call ANY OCC boolean here — neither
    .union() across segments nor .cut() for interior holes. Both are
    native OCC boolean calls, and a curved path (many short segments
    touching face-to-face at each joint) is exactly the geometry where
    OCC's boolean solver can hang indefinitely inside the C kernel
    without ever raising, so neither can be relied on to fail fast.
    Interior chamber holes are therefore not cut on curved members (outer
    profile only) — cosmetic/manufacturing detail only, not structural.
    Rectangular/straight members are untouched: they never call this
    function, and _cq_section_solid (with real hole cuts) still runs for
    them exactly as before.
    """
    pts = m.path
    n = len(pts)
    count = n if m.closed else n - 1
    solids = []
    for i in range(count):
        p0 = pts[i]
        p1 = pts[(i + 1) % n] if m.closed else pts[i + 1]
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        seg_len = math.hypot(dx, dy)
        if seg_len < 0.5:
            continue
        theta_deg = math.degrees(math.atan2(dy, dx))

        solid = _cq_section_solid_no_holes(cq, outer, seg_len)
        # base horizontal mapping: Z(length)->X, X(u)->Y, Y(v)->Z
        solid = solid.rotate((0, 0, 0), (0, 1, 0), 90)
        solid = solid.rotate((0, 0, 0), (1, 0, 0), 90)
        # extra rotation to this segment's own in-plane angle
        solid = solid.rotate((0, 0, 0), (0, 0, 1), theta_deg)

        tx, ty = _path_segment_transform(theta_deg, p0, sec_bar, cx, cy)
        solid = solid.translate((tx, ty, 0.0))

        solids.append(solid)

    if not solids:
        return None
    if len(solids) == 1:
        return solids[0]

    compound = cq.Compound.makeCompound(
        s.val() for s in solids
    )
    return cq.Workplane("XY").newObject([compound])



def _member_solid_cq(cq, m, rings, sec_bar, sec_dep, cx, cy):
    """
    CadQuery implementation of the exact same anchor contract as trimesh.

    No bounding-box centre is used for horizontal or vertical placement.
    Bounding boxes are only unnecessary geometry inspection and therefore are
    deliberately absent from placement.

    Curved (m.path set): see _member_solid_cq_path.
    """
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

    if getattr(m, "path", None):
        return _member_solid_cq_path(cq, m, outer, holes, sec_bar, sec_dep, cx, cy)

    length = float(m.length)
    if length < 1.0:
        return None

    solid = _cq_section_solid(cq, outer, holes, length)

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


# Backward compatibility alias
def generate_3d(window, panes, tenant_id=None, fmt="glb", method=None, z_up=False) -> bytes:
    """Wrapper for generate_3d_assembly for backward compatibility."""
    return generate_3d_assembly(window, panes, tenant_id=tenant_id, fmt=fmt, z_up=z_up)