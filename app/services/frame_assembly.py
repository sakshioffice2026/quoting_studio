"""
frame_assembly.py — decompose a parametric window/door into a MEMBER GRAPH.

A real window is not one profile extruded everywhere. It is a set of members,
each with a role (outer frame head/cill/jamb, mullion, transom, sash, glazing
bead …), joined at mitres (corners) or butt joints (T-junctions). This module
turns the 2D pane layout into that graph — pure geometry, no CAD kernel — so the
3D builder, the engineering section view, and the cut-list can all share one
source of truth.

Coordinate convention
---------------------
  * millimetres, origin at the frame's bottom-left INNER corner of the outer box
  * X grows right, Y grows UP  (elevation orientation)
  * pane coords arriving as x_norm/y_norm are TOP-LEFT origin, Y DOWN
    (same as the drawing engine); we flip Y here so everything downstream is
    Y-up and consistent.

Public API
----------
  build_members(window, panes, profiles) -> Assembly
      window   : object with .width_mm, .height_mm, .unit_type/.unitType
      panes    : list of pane objects OR dicts (x,y,w,h, opening/opener, infill)
      profiles : ProfileSet (see resolve_profiles) mapping role -> profile dict

Everything returns plain dataclasses so it is trivially serialisable and
unit-testable without Flask, a DB, or a CAD kernel.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)

# ── roles ────────────────────────────────────────────────────────────────
ROLE_HEAD         = 'head'          # top outer-frame member
ROLE_CILL         = 'cill'          # bottom outer-frame member
ROLE_JAMB         = 'jamb'          # lFeft / right outer-frame members
ROLE_MULLION      = 'mullion'       # internal vertical divider
ROLE_TRANSOM      = 'transom'       # internal horizontal divider
ROLE_SASH         = 'sash'          # opening-leaf sub-frame member
ROLE_GLAZING_BEAD = 'glazing_bead'  # bead retaining the IGU (optional)
ROLE_THRESHOLD    = 'threshold'     # low door threshold (maps to cill if absent)
ROLE_OUTER_FRAME  = 'outer_frame'   # generic fallback for any perimeter member

# Fallback chain: if a role has no profile, walk these until one resolves.
ROLE_FALLBACK = {
    ROLE_HEAD:         [ROLE_HEAD, ROLE_OUTER_FRAME],
    ROLE_CILL:         [ROLE_CILL, ROLE_THRESHOLD, ROLE_OUTER_FRAME],
    ROLE_JAMB:         [ROLE_JAMB, ROLE_OUTER_FRAME],
    ROLE_THRESHOLD:    [ROLE_THRESHOLD, ROLE_CILL, ROLE_OUTER_FRAME],
    ROLE_MULLION:      [ROLE_MULLION, ROLE_TRANSOM, ROLE_OUTER_FRAME],
    ROLE_TRANSOM:      [ROLE_TRANSOM, ROLE_MULLION, ROLE_OUTER_FRAME],
    ROLE_SASH:         [ROLE_SASH, ROLE_OUTER_FRAME],
    ROLE_GLAZING_BEAD: [ROLE_GLAZING_BEAD],
    ROLE_OUTER_FRAME:  [ROLE_OUTER_FRAME],
}

# joint kinds
JOINT_MITRE = 'mitre'   # 45° — where two perpendicular members meet at a corner
JOINT_BUTT  = 'butt'    # square — where a member dies into another's face

# member orientation
ORI_H = 'horizontal'
ORI_V = 'vertical'

_EPS = 1e-4

# Extra distance (mm) a mullion/transom end is pushed past the calculated
# ellipse touch-point on a circular frame. The ring is a facetted polygon
# approximating the true ellipse, and its inner boundary is itself only an
# approximate constant-width offset, so the two curves don't coincide
# exactly. A flat-cut bar end stopped precisely on the touch-point can
# therefore land just outside the ring's actual solid material and leave a
# visible sliver/notch. Overlapping by this margin guarantees the end is
# buried inside the ring instead — and, critically, this is also the margin
# that makes the downstream boolean union (model3d.py::_build_step) succeed:
# solids that only TOUCH can produce a fragile/failed union or a visible
# seam even when unioned; solids that genuinely OVERLAP in volume always
# fuse cleanly.
#
# A flat mm value is fragile across profile sizes — a slim mullion on a
# large-diameter ring needs less embed depth than a heavy mullion on a
# small ring. Scale the overlap off the member's OWN bar width instead, so
# the embed depth is always proportionate to that member's actual solid
# cross-section: never less than 6mm, and at least half the bar width so a
# skinny cross-section still buries a meaningful fraction of itself.
def _ring_embed_overlap(bar_width: float) -> float:
    return max(6.0, float(bar_width) * 0.5)


# ── data structures ────────────────────────────────────────────────────────
@dataclass
class Member:
    """One length of profile in the assembly."""
    id: str
    role: str
    orientation: str            # ORI_H | ORI_V
    # centre-line endpoints (mm, Y-up). A member runs along its centre line;
    # the profile's bar-width straddles this line, the depth runs along +Z.
    x1: float
    y1: float
    x2: float
    y2: float
    bar_width: float            # across the centre line (mm)
    depth: float                # through the wall, +Z (mm)
    # joint at each end: JOINT_MITRE | JOINT_BUTT
    joint_start: str = JOINT_BUTT
    joint_end: str = JOINT_BUTT
    # for mitres: the angle (deg) of the cut plane relative to the member axis.
    # 45 for a standard corner; the sign is resolved by the builder from which
    # way the mating member turns.
    miter_start_deg: float = 0.0
    miter_end_deg: float = 0.0
    profile_code: Optional[str] = None   # filled once profiles are resolved
    # Curved member (arched/gothic head, or a full circular frame ring):
    # an explicit (x, y) polyline in the same mm/Y-up space as x1..y2.
    # When set, this is authoritative for meshing/STEP export (see
    # model3d.py::_member_mesh / _member_solid_cq, which already sweep a
    # profile section along `path`) — x1..y2 are left as a best-effort
    # bounding box only, for any code that still reads the straight
    # centreline (e.g. horn/mullion centring in model3d.py).
    path: Optional[list] = None
    closed: bool = False   # True for a full loop (circular ring); False for
                            # an open curve (arched/gothic head) that still
                            # joins straight jambs at each end.

    @property
    def length(self) -> float:
        if self.path:
            pts = self.path
            n = len(pts)
            count = n if self.closed else n - 1
            return sum(
                math.hypot(pts[(i + 1) % n][0] - pts[i][0],
                           pts[(i + 1) % n][1] - pts[i][1])
                for i in range(count)
            )
        return abs(self.x2 - self.x1) + abs(self.y2 - self.y1)


@dataclass
class GlassCell:
    """A glazed / infilled opening — the clear aperture inside its members."""
    id: str
    x: float                    # bottom-left of the clear aperture (mm, Y-up)
    y: float
    w: float
    h: float
    infill: str = 'glass'       # glass | panel
    opening: str = 'Fixed'
    thickness: float = 24.0     # IGU thickness (mm)
    # For a circular frame: the glass's true visible outline (rectangle
    # clipped to the frame's inner-face ellipse), a closed (x, y) polygon in
    # the same absolute mm/Y-up space as x/y/w/h. x/y/w/h remain the
    # rectangle's bounding box (kept for any code that still reads them);
    # when clip_path is set it is authoritative for meshing/STEP export.
    clip_path: Optional[list] = None


@dataclass
class Assembly:
    width: float
    height: float
    unit_type: str              # window | door
    members: list = field(default_factory=list)
    glass: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    # convenience -----------------------------------------------------------
    def members_by_role(self, role: str):
        return [m for m in self.members if m.role == role]

    def to_dict(self) -> dict:
        return {
            'width': self.width, 'height': self.height,
            'unit_type': self.unit_type,
            'members': [asdict(m) for m in self.members],
            'glass':   [asdict(g) for g in self.glass],
            'warnings': self.warnings,
        }


# ── profile resolution ──────────────────────────────────────────────────────
class ProfileSet:
    """
    Maps a role -> profile dict. A profile dict carries at minimum:
        {'code','bar','depth','loops'?,'glass_rebate'?}
    Missing roles fall back via ROLE_FALLBACK. A single default profile can be
    passed to `default` and is used whenever nothing else resolves.
    """
    def __init__(self, by_role: dict | None = None, default: dict | None = None,
                 sash_clearance: float = 2.0):
        self.by_role = dict(by_role or {})
        self.default = default or {
            'code': 'DEFAULT', 'bar': 58.0, 'depth': 70.0,
            'glass_rebate': 20.0, 'loops': None,
        }
        # Operational gap between sash outer edge and frame inner face.
        # Set from ProfileSystem.sash_clearance_mm when a system is assigned.
        self.sash_clearance = float(sash_clearance)

    def get(self, role: str) -> dict:
        for candidate in ROLE_FALLBACK.get(role, [role]):
            if candidate in self.by_role and self.by_role[candidate]:
                return self.by_role[candidate]
        return self.default

    def has(self, role: str) -> bool:
        return any(c in self.by_role and self.by_role[c]
                   for c in ROLE_FALLBACK.get(role, [role]))


def resolve_profiles(tenant_id, material='Aluminium',
                     window=None) -> ProfileSet:
    """
    Build a ProfileSet for a window/door.

    Resolution order
    ----------------
    1.  window.profile_system  — the pinned ProfileSystem for this unit.
        `to_profile_set()` maps every slot to the correct role and
        calculates the sash clearance from the system's sash_clearance_mm.
    2.  Fallback: scan CadProfile rows for is_role_default / any matching role.
        Same as before — works without any ProfileSystem configured.

    Sash rebate geometry (step 1 only)
    ------------------------------------
    The sash's exact cut dimensions are derived from the outer-frame rebate:
        sash_aperture = internal_clear - 2 * sash_clearance_mm
    where `internal_clear` is calculated in build_members() from the jamb's
    `glass_rebate_mm`.  The sash_clearance is stored on the ProfileSet so
    build_members() can use it without re-querying.
    """
    # ── Step 1: pinned ProfileSystem (merged over library defaults) ───
    # Build the library role-default set FIRST, then overlay the system's
    # filled slots on top. This way a system with only some slots filled
    # (e.g. just mullion + transom) still gets real head/cill/jamb from the
    # library instead of falling back to a generic box.
    sys_by_role = {}
    sys_clearance = 2.0
    if window is not None:
        try:
            sys_obj = getattr(window, 'profile_system', None)
            if sys_obj is None and getattr(window, 'profile_system_id', None):
                from ..models.profile_system import ProfileSystem
                sys_obj = ProfileSystem.query.get(window.profile_system_id)
            if sys_obj:
                unit_type = (getattr(window, 'unit_type', None)
                             or getattr(window, 'unitType', None)
                             or 'window')
                sys_by_role, sys_clearance = sys_obj.to_profile_set(unit_type)
        except Exception as exc:
            logger.warning('ProfileSystem lookup failed: %s', exc)

    # ── Step 2: role-default fallback (original logic) ────────────────
    by_role: dict = {}
    default: dict | None = None
    try:
        from ..models.cad_profile import CadProfile
        import json as _json

        def _to_dict(p):
            loops = None
            if p.geometry_json:
                try:
                    loops = _json.loads(p.geometry_json)
                except Exception:
                    loops = None
            return {
                'code':         p.code or p.name,
                'bar':          float(p.bar_width_mm),
                'depth':        float(p.depth_mm),
                'glass_rebate': float(p.glass_rebate_mm or 20.0),
                'loops':        loops,
            }

        rows = (CadProfile.query
                .filter_by(tenant_id=tenant_id, material=material,
                            is_active=True).all())
        if not rows:
            rows = CadProfile.query.filter_by(
                tenant_id=tenant_id, is_active=True).all()

        for p in rows:
            if p.role and getattr(p, 'is_role_default', False):
                by_role[p.role] = _to_dict(p)
        for p in rows:
            if p.role and p.role not in by_role:
                by_role[p.role] = _to_dict(p)
            if getattr(p, 'is_default', False) and default is None:
                d = _to_dict(p)
                d['bar']   = max(float(d.get('bar',   58.0)), 50.0)
                d['depth'] = max(float(d.get('depth', 70.0)), 65.0)
                default = d
    except Exception as exc:
        logger.warning('resolve_profiles fell back to defaults: %s', exc)

    # ── Overlay ProfileSystem slots on top of library defaults ────────
    # Filled system slots win; empty slots keep the library role-default.
    if sys_by_role:
        by_role.update(sys_by_role)

    return ProfileSet(by_role=by_role, default=default,
                      sash_clearance=sys_clearance)


# ── pane normalisation ──────────────────────────────────────────────────────
# Snap tolerance (mm): pane edges within this distance of the outer frame
# boundary (0 or W/H) or of another pane's edge get pulled exactly onto it.
# Fixes small design_json rounding errors (e.g. y+h = 0.994 instead of 1.0)
# that used to leave a visible gap because no mullion/transom edge lined up
# with the cill/head/jamb.
_SNAP_TOL_MM = 3.0


def _snap_edges(rects, W, H, tol=_SNAP_TOL_MM):
    """Pull each rect's edges onto the outer frame boundary or a nearby
    edge from another rect, if within `tol` mm. Mutates and returns rects."""
    # snap to outer boundary
    for r in rects:
        if r['x'] <= tol:
            r['x'] = 0.0
        if r['y'] <= tol:
            r['y'] = 0.0
        if abs((r['x'] + r['w']) - W) <= tol:
            r['w'] = W - r['x']
        if abs((r['y'] + r['h']) - H) <= tol:
            r['h'] = H - r['y']

    # snap near-matching internal edges (mullion/transom lines) together
    def _snap_axis(get_edges, set_edge):
        edges = sorted(set(get_edges()))
        clusters = []
        for e in edges:
            if clusters and e - clusters[-1][-1] <= tol:
                clusters[-1].append(e)
            else:
                clusters.append([e])
        remap = {}
        for c in clusters:
            target = sum(c) / len(c)
            for e in c:
                remap[e] = target
        set_edge(remap)

    _snap_axis(
        lambda: [r['x'] for r in rects] + [r['x'] + r['w'] for r in rects],
        lambda remap: [r.update(
            x=remap.get(r['x'], r['x']),
            w=(remap.get(r['x'] + r['w'], r['x'] + r['w']) - remap.get(r['x'], r['x']))
        ) for r in rects],
    )
    _snap_axis(
        lambda: [r['y'] for r in rects] + [r['y'] + r['h'] for r in rects],
        lambda remap: [r.update(
            y=remap.get(r['y'], r['y']),
            h=(remap.get(r['y'] + r['h'], r['y'] + r['h']) - remap.get(r['y'], r['y']))
        ) for r in rects],
    )
    return rects


def _norm_panes(panes, W, H):
    """
    Return panes as clear-aperture rects in mm, Y-UP, sorted for determinism.
    Accepts either ORM objects (x_norm…) or dicts (x…). Input Y is TOP-DOWN, so
    we flip: y_up = 1 - (y_top + h).
    """
    out = []
    for i, p in enumerate(panes):
        if isinstance(p, dict):
            x = float(p.get('x', 0)); y = float(p.get('y', 0))
            w = float(p.get('w', 1)); h = float(p.get('h', 1))
            opening = p.get('opening') or p.get('opener') or 'Fixed'
            infill = p.get('infill', 'glass')
        else:
            x = float(p.x_norm); y = float(p.y_norm)
            w = float(p.w_norm); h = float(p.h_norm)
            opening = getattr(p, 'opener_type', None) or getattr(p, 'opening', None) or 'Fixed'
            infill = getattr(p, 'infill', 'glass')
        y_up = 1.0 - (y + h)                 # flip to Y-up
        out.append({
            'i': i,
            'x': x * W, 'y': y_up * H, 'w': w * W, 'h': h * H,
            'opening': opening, 'infill': infill,
        })
    out = _snap_edges(out, W, H)
    out.sort(key=lambda r: (round(r['y'], 2), round(r['x'], 2)))
    return out


def _uniq(vals, tol=0.5):
    """Collapse near-equal coordinates."""
    s = sorted(vals)
    out = []
    for v in s:
        if not out or abs(v - out[-1]) > tol:
            out.append(v)
        else:
            out[-1] = (out[-1] + v) / 2.0
    return out


# ── the build ────────────────────────────────────────────────────────────────
def _load_design(window) -> dict:
    """Parse window.design_json the same defensive way engineering_dxf.py
    and canonical_geometry.py do, so all three exports read the same
    'shape'/'archRise' the Designer wrote."""
    try:
        return json.loads(getattr(window, 'design_json', None) or '{}')
    except (TypeError, ValueError):
        return {}


def _ellipse_points(cx, cy, rx, ry, segments=64):
    """Full ellipse (or circle when rx==ry), sampled CCW starting at 0°."""
    return [
        (cx + rx * math.cos(2 * math.pi * i / segments),
         cy + ry * math.sin(2 * math.pi * i / segments))
        for i in range(segments)
    ]


def _arc_points(cx, cy, r, start_deg, end_deg, segments=32):
    """Arc from start_deg to end_deg (inclusive), degrees measured the same
    way as ezdxf's add_arc (0° = +X axis, CCW)."""
    pts = []
    for i in range(segments + 1):
        t = start_deg + (end_deg - start_deg) * i / segments
        rad = math.radians(t)
        pts.append((cx + r * math.cos(rad), cy + r * math.sin(rad)))
    return pts


def _quad_bezier_points(p0, p1, p2, segments=20):
    """Quadratic Bezier (p0=start, p1=control, p2=end), including both
    endpoints. Mirrors engineering_dxf.py::_quad_bezier_points so the
    gothic head matches the DXF elevation exactly."""
    pts = []
    for i in range(segments + 1):
        t = i / segments
        mt = 1 - t
        x = mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0]
        y = mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1]
        pts.append((x, y))
    return pts


def _clip_polygon_convex(subject, clip):
    """Sutherland-Hodgman: clip `subject` polygon against a CONVEX `clip`
    polygon (an ellipse polygon is convex, so this gives an exact rectangle
    ∩ ellipse shape — straight edges plus the elliptical arc where the
    rectangle would otherwise poke outside the frame). Both are lists of
    (x, y) points, implicitly closed."""
    def _inside(p, a, b):
        # left-of test for edge a->b of the (CCW) clip polygon
        return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0

    def _intersect(p1, p2, a, b):
        x1, y1 = p1; x2, y2 = p2; x3, y3 = a; x4, y4 = b
        d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(d) < 1e-9:
            return p2
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / d
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))

    output = list(subject)
    n = len(clip)
    for i in range(n):
        a, b = clip[i], clip[(i + 1) % n]
        if not output:
            break
        input_list = output
        output = []
        m = len(input_list)
        for j in range(m):
            cur = input_list[j]
            prev = input_list[j - 1]
            cur_in = _inside(cur, a, b)
            prev_in = _inside(prev, a, b)
            if cur_in:
                if not prev_in:
                    output.append(_intersect(prev, cur, a, b))
                output.append(cur)
            elif prev_in:
                output.append(_intersect(prev, cur, a, b))
    return output


def _ellipse_span_y(x, cx, cy, rx, ry):
    """Half-height of the ellipse at a given x, or None if x is outside it."""
    t = (x - cx) / rx
    if abs(t) >= 1.0:
        return None
    half = ry * math.sqrt(1.0 - t * t)
    return cy - half, cy + half


def _ellipse_span_x(y, cx, cy, rx, ry):
    """Half-width of the ellipse at a given y, or None if y is outside it."""
    t = (y - cy) / ry
    if abs(t) >= 1.0:
        return None
    half = rx * math.sqrt(1.0 - t * t)
    return cx - half, cx + half


def _add_circular_frame_ring(A: Assembly, W, H, p_head, depth):
    """Build the circular/elliptical frame from its true outer envelope.

    W/H are OUTER bounds.  The profile centreline is inset by half the
    actual profile width; the glass boundary is one full profile width
    inside the outer envelope.
    """
    cx, cy = W / 2.0, H / 2.0
    bar = float(p_head['bar'])

    rx_outer = W / 2.0
    ry_outer = H / 2.0

    # True profile centreline.
    rx_path = max(rx_outer - bar / 2.0, 1.0)
    ry_path = max(ry_outer - bar / 2.0, 1.0)

    path = _ellipse_points(
        cx, cy, rx_path, ry_path, segments=256
    )

    A.members.append(Member(
        id='F_ring',
        role=ROLE_HEAD,
        orientation=ORI_H,
        x1=cx - rx_path,
        y1=cy,
        x2=cx + rx_path,
        y2=cy,
        bar_width=bar,
        depth=depth,
        joint_start=JOINT_BUTT,
        joint_end=JOINT_BUTT,
        profile_code=p_head['code'],
        path=path,
        closed=True,
    ))


def _add_arched_head(A: Assembly, W, spring_y, p_head, depth):
    """Semicircular arched head spanning the two jamb tops, radius W/2,
    centred at (W/2, spring_y) — mirrors engineering_dxf.py's 'arched'
    branch (add_arc center=(W/2,spring_y), radius=W/2, 0deg->180deg)."""
    cx = W / 2.0
    path = _arc_points(cx, spring_y, W / 2.0, 180.0, 0.0, segments=32)
    bar = p_head['bar']
    A.members.append(Member(
        id='F_head', role=ROLE_HEAD, orientation=ORI_H,
        x1=0, y1=spring_y, x2=W, y2=spring_y,
        bar_width=bar, depth=depth,
        joint_start=JOINT_MITRE, joint_end=JOINT_MITRE,
        miter_start_deg=45, miter_end_deg=45,
        profile_code=p_head['code'],
        path=path, closed=False))


def _add_gothic_head(A: Assembly, W, H, spring_y, arch_rise, p_head, depth):
    """Pointed (two-centre) gothic head — mirrors engineering_dxf.py's
    'gothic' branch: two quadratic Beziers from each jamb top up to the
    apex, spring-line / control-point (0.6 factor) geometry matched
    exactly so the DXF elevation and the STEP/3D export agree."""
    apex = (W / 2.0, H)
    ctrl_y = spring_y + 0.6 * arch_rise
    right_spring = (W, spring_y)
    right_ctrl = (W, ctrl_y)
    left_ctrl = (0.0, ctrl_y)
    left_spring = (0.0, spring_y)

    path = _quad_bezier_points(right_spring, right_ctrl, apex, segments=16)
    path += _quad_bezier_points(apex, left_ctrl, left_spring, segments=16)[1:]

    bar = p_head['bar']
    A.members.append(Member(
        id='F_head', role=ROLE_HEAD, orientation=ORI_H,
        x1=0, y1=spring_y, x2=W, y2=spring_y,
        bar_width=bar, depth=depth,
        joint_start=JOINT_MITRE, joint_end=JOINT_MITRE,
        miter_start_deg=45, miter_end_deg=45,
        profile_code=p_head['code'],
        path=path, closed=False))


def build_members(window, panes, profiles: ProfileSet | None = None) -> Assembly:
    """
    Decompose `window` + `panes` into an Assembly (members + glass + warnings).

    Steps:
      1. outer frame  → 4 members (head, cill, 2 jambs), mitred at corners
      2. internal edges → mullions (vertical) and transoms (horizontal),
         each spanning only the panes that actually share that edge, butt-jointed
      3. opening panes → a sash sub-frame inset inside the aperture (mitred)
      4. glass cells   → clear aperture inside each pane's members
    """
    W = float(window.width_mm)
    H = float(window.height_mm)
    unit_type = (getattr(window, 'unit_type', None)
                 or getattr(window, 'unitType', None) or 'window')

    if profiles is None:
        profiles = ProfileSet()

    A = Assembly(width=W, height=H, unit_type=unit_type)

    p_head = profiles.get(ROLE_HEAD)
    p_cill = profiles.get(ROLE_CILL if unit_type != 'door' else ROLE_THRESHOLD)
    p_jamb = profiles.get(ROLE_JAMB)
    p_mull = profiles.get(ROLE_MULLION)
    p_tran = profiles.get(ROLE_TRANSOM)

    bar_h  = p_head['bar']
    bar_c  = p_cill['bar']
    bar_j  = p_jamb['bar']
    dep    = max(p_head['depth'], p_jamb['depth'], p_cill['depth'])

    mid = 0                # members are placed on the outer box; centre lines
    # run at bar_width/2 in from each outer edge.

    # Frame shape: design_json['shape'] (written by the Designer) is the
    # source of truth, same as canonical_geometry.py (used for the pane/
    # glass layout) and engineering_dxf.py (2D sheet). Falls back to the
    # legacy window.shape DB column, then 'rectangle'. This is what was
    # previously missing here — build_members() always built a plain
    # rectangle no matter what shape was selected in the Designer.
    design = _load_design(window)
    shape = str(
        design.get('shape') or getattr(window, 'shape', None) or 'rectangle'
    ).lower()
    if shape == 'rectangular':
        shape = 'rectangle'
    arch_rise = design.get('archRise')
    try:
        arch_rise = float(arch_rise) if arch_rise is not None else None
    except (TypeError, ValueError):
        arch_rise = None
    if shape in ('arched', 'gothic') and not (arch_rise and arch_rise > 0):
        # Designer always sends archRise alongside shape; this is only a
        # safety net for older saved records — same fallback formula as
        # engineering_dxf.py so the DXF sheet and the 3D/STEP model agree.
        arch_rise = min(W * 0.25, 400.0)

    # ── 1. OUTER FRAME ──────────────────────────────────────────────
    cill_role = ROLE_CILL if unit_type != 'door' else ROLE_THRESHOLD

    if shape == 'circular':
        # Whole frame is one closed elliptical ring — no separate
        # head/cill/jambs. Internal dividers below still clamp to the W x H
        # bounding box (bar_h/bar_c/bar_j), matching the DXF sheet's
        # documented simplification of not clipping them to the round
        # aperture.
        _add_circular_frame_ring(A, W, H, p_head, dep)
        jy1, jy2 = bar_c, H - bar_h
    else:
        # Cill (bottom) — same for rectangle/arched/gothic.
        A.members.append(Member(
            id='F_cill', role=cill_role, orientation=ORI_H,
            x1=0, y1=bar_c / 2, x2=W, y2=bar_c / 2,
            bar_width=bar_c, depth=p_cill['depth'],
            joint_start=JOINT_MITRE, joint_end=JOINT_MITRE,
            miter_start_deg=45, miter_end_deg=45,
            profile_code=p_cill['code']))

        if shape == 'arched':
            spring_y = H - arch_rise
            _add_arched_head(A, W, spring_y, p_head, p_head['depth'])
            jy1, jy2 = bar_c, spring_y
        elif shape == 'gothic':
            spring_y = H - arch_rise
            _add_gothic_head(A, W, H, spring_y, arch_rise, p_head, p_head['depth'])
            jy1, jy2 = bar_c, spring_y
        else:
            # Plain rectangle (default). Head — centre line at
            # y = H - bar_h/2, spanning full width.
            A.members.append(Member(
                id='F_head', role=ROLE_HEAD, orientation=ORI_H,
                x1=0, y1=H - bar_h / 2, x2=W, y2=H - bar_h / 2,
                bar_width=bar_h, depth=p_head['depth'],
                joint_start=JOINT_MITRE, joint_end=JOINT_MITRE,
                miter_start_deg=45, miter_end_deg=45,
                profile_code=p_head['code']))
            jy1, jy2 = bar_c, H - bar_h

        # Jambs (left / right) — run between cill and head/spring-line.
        A.members.append(Member(
            id='F_jambL', role=ROLE_JAMB, orientation=ORI_V,
            x1=bar_j / 2, y1=jy1, x2=bar_j / 2, y2=jy2,
            bar_width=bar_j, depth=p_jamb['depth'],
            joint_start=JOINT_MITRE, joint_end=JOINT_MITRE,
            miter_start_deg=45, miter_end_deg=45,
            profile_code=p_jamb['code']))
        A.members.append(Member(
            id='F_jambR', role=ROLE_JAMB, orientation=ORI_V,
            x1=W - bar_j / 2, y1=jy1, x2=W - bar_j / 2, y2=jy2,
            bar_width=bar_j, depth=p_jamb['depth'],
            joint_start=JOINT_MITRE, joint_end=JOINT_MITRE,
            miter_start_deg=45, miter_end_deg=45,
            profile_code=p_jamb['code']))

    # ── 2. INTERNAL DIVIDERS (mullions + transoms) ──────────────────
    # For a circular frame the ellipse's INNER face (radius reduced by half
    # the ring's own bar width) is the real boundary — dividers and glass
    # must stop at the arc instead of running out to the square W x H
    # bounding box, otherwise they poke out past the round frame.
    cx, cy = W / 2.0, H / 2.0
    if shape == 'circular':
        rx_in = max(W / 2.0 - bar_h / 2.0, 1.0)
        ry_in = max(H / 2.0 - bar_h / 2.0, 1.0)
        ellipse_poly = _ellipse_points(cx, cy, rx_in, ry_in, segments=96)
    else:
        rx_in = ry_in = None
        ellipse_poly = None

    rects = _norm_panes(panes, W, H)

    # collect vertical edges (mullions) and the y-spans of panes owning each
    v_edges: dict = {}
    h_edges: dict = {}
    for r in rects:
        rx = r['x'] + r['w']            # right edge (candidate mullion)
        if _EPS < rx < W - _EPS:
            v_edges.setdefault(round(rx, 2), []).append((r['y'], r['y'] + r['h']))
        ty = r['y'] + r['h']            # top edge (candidate transom)
        if _EPS < ty < H - _EPS:
            h_edges.setdefault(round(ty, 2), []).append((r['x'], r['x'] + r['w']))

    # ── Lock every pane's internal-facing edges onto the divider that
    # actually gets built ────────────────────────────────────────────
    # v_edges/h_edges above only look at ONE side of each shared line (a
    # pane's own RIGHT edge for mullions, own TOP edge for transoms) — the
    # neighbouring pane's facing edge (its own left/bottom) is never cross-
    # checked against it. _norm_panes() already runs a general edge-snap
    # pass, but only within _SNAP_TOL_MM (3mm); a larger mismatch from the
    # saved design (x_norm/y_norm rounding at a large W/H, etc) survives
    # that pass untouched. The result: the mullion/transom gets built from
    # one pane's edge, but the OTHER pane's glass is positioned from its
    # own, still slightly different, edge — leaving a one-sided sliver
    # between that pane's glass and the divider that doesn't reach it.
    # Now that the real divider positions are known (v_edges/h_edges keys),
    # snap every pane's edge onto the nearest one directly — this is the
    # ground truth for where the solid divider actually is, so this always
    # wins over whatever the pane's own stored coordinate says.
    _DIVIDER_SNAP_TOL = 20.0
    mull_xs = sorted(v_edges.keys())
    tran_ys = sorted(h_edges.keys())

    def _snap_to_divider(value, candidates, tol=_DIVIDER_SNAP_TOL):
        best, best_d = None, tol
        for c in candidates:
            d = abs(value - c)
            if d <= best_d:
                best, best_d = c, d
        return best if best is not None else value

    for r in rects:
        x0, x1 = r['x'], r['x'] + r['w']
        y0, y1 = r['y'], r['y'] + r['h']
        x0 = _snap_to_divider(x0, mull_xs)
        x1 = _snap_to_divider(x1, mull_xs)
        y0 = _snap_to_divider(y0, tran_ys)
        y1 = _snap_to_divider(y1, tran_ys)
        r['x'], r['w'] = x0, x1 - x0
        r['y'], r['h'] = y0, y1 - y0

    def _merge(spans):
        s = sorted(spans)
        out = [list(s[0])]
        for a, b in s[1:]:
            if a <= out[-1][1] + 0.5:
                out[-1][1] = max(out[-1][1], b)
            else:
                out.append([a, b])
        return out

    mb = p_mull['bar']
    tb = p_tran['bar']

    mi = 0
    for x, spans in sorted(v_edges.items()):
        for (y_lo, y_hi) in _merge(spans):
            mi += 1
            if shape == 'circular':
                # The rectangular-frame clamp below (bar_c/bar_h) has no
                # relationship to a round ring's own inner boundary — it was
                # setting y_lo/y_hi from the CILL/HEAD bar widths, which can
                # land on either side of the ring's true ellipse touch-point
                # depending on how those bars compare to the ring's own bar
                # width. When it happened to land short of the touch-point
                # the end floated in the aperture instead of reaching the
                # ring at all, which is exactly the gap in the screenshot.
                # For a circular frame ONLY the ellipse touch-point matters,
                # so skip the rectangular clamp entirely and drive both ends
                # unconditionally from the ring geometry.
                span = _ellipse_span_y(x, cx, cy, rx_in, ry_in)
                if span is None:
                    continue          # this edge lies entirely outside the ring
                # Bury the end past the true touch-point so the flat cut
                # always lands inside the ring's solid material instead of
                # stopping exactly on the (facetted/approximated) inner
                # boundary, which leaves a sliver gap at the join. Depth of
                # the embed scales with this member's OWN bar width.
                embed = _ring_embed_overlap(mb)
                if y_lo <= span[0]:
                    y_lo = span[0] - embed
                if y_hi >= span[1]:
                    y_hi = span[1] + embed
            else:
                # clamp inside outer frame (rectangular/arched/gothic only)
                y_lo = max(y_lo, bar_c)
                y_hi = min(y_hi, H - bar_h)
            if y_hi - y_lo < 1:
                continue
            A.members.append(Member(
                id=f'M_mull{mi}', role=ROLE_MULLION, orientation=ORI_V,
                x1=x, y1=y_lo, x2=x, y2=y_hi,
                bar_width=mb, depth=p_mull['depth'],
                joint_start=JOINT_BUTT, joint_end=JOINT_BUTT,
                profile_code=p_mull['code']))

    ti = 0
    for y, spans in sorted(h_edges.items()):
        for (x_lo, x_hi) in _merge(spans):
            ti += 1
            if shape == 'circular':
                # Same reasoning as the mullion loop above: the JAMB-bar
                # clamp is a rectangular-frame concept and must not be
                # allowed to override the ring's true touch-point.
                span = _ellipse_span_x(y, cx, cy, rx_in, ry_in)
                if span is None:
                    continue
                embed = _ring_embed_overlap(tb)
                if x_lo <= span[0]:
                    x_lo = span[0] - embed
                if x_hi >= span[1]:
                    x_hi = span[1] + embed
            else:
                x_lo = max(x_lo, bar_j)
                x_hi = min(x_hi, W - bar_j)
            if x_hi - x_lo < 1:
                continue
            A.members.append(Member(
                id=f'T_tran{ti}', role=ROLE_TRANSOM, orientation=ORI_H,
                x1=x_lo, y1=y, x2=x_hi, y2=y,
                bar_width=tb, depth=p_tran['depth'],
                joint_start=JOINT_BUTT, joint_end=JOINT_BUTT,
                profile_code=p_tran['code']))

    # ── 3. SASH SUB-FRAMES for opening panes ────────────────────────
    p_sash = profiles.get(ROLE_SASH)
    sb = p_sash['bar']
    have_sash = profiles.has(ROLE_SASH)
    # PWQ-3645 plan section: the sash OVERLAPS the outer frame in the rebate.
    # Measured: jamb face 60mm, sash face 60mm, overlap 16mm — the sash rect
    # EXPANDS beyond the clear pane aperture by `overlap` on every side, so it
    # engages the frame rebate instead of floating inside with a gap.
    # ProfileSystem.sash_clearance_mm now means this rebate engagement (mm);
    # default 16 per the reference drawing when unset or left at old 2mm.
    clr = getattr(profiles, 'sash_clearance', 2.0)
    overlap = 16.0 if clr <= 2.0 else clr
    # Sash insets are recorded per-pane so the glass/bead step (4) uses the
    # exact same inner face — otherwise glass/bead assume the plain mullion
    # inset (mb/2) while the sash actually sits `overlap` mm further out,
    # leaving an unfilled ring around every sash (worst at a shared mullion
    # between two opening panes, where both gaps land in the same spot).
    sash_insets: dict = {}
    sash_rects: dict = {}
    si = 0
    for r in rects:
        if not _is_opening(r['opening']):
            continue
        if not have_sash:
            A.warnings.append(
                f"pane {r['i']} is '{r['opening']}' but no sash profile is "
                f"defined — no sash sub-frame drawn")
            continue
        si += 1
        # Per-edge inset from the pane rect to the sash outer edge.
        # PWQ: sash outer edge = frame INNER face − overlap (engages rebate).
        #   outer edges: inset = full frame bar − overlap
        #   internal edges (mullion/transom): inset = half bar − overlap, ≥ 0
        eps = 0.5
        on_l = r['x'] <= eps
        on_r = r['x'] + r['w'] >= W - eps
        on_b = r['y'] <= eps
        on_t = r['y'] + r['h'] >= H - eps
        il = (bar_j - overlap) if on_l else max(mb / 2 - overlap, 0.0)
        ir = (bar_j - overlap) if on_r else max(mb / 2 - overlap, 0.0)
        ib = (bar_c - overlap) if on_b else max(tb / 2 - overlap, 0.0)
        it = (bar_h - overlap) if on_t else max(tb / 2 - overlap, 0.0)
        sash_insets[r['i']] = {'l': il, 'r': ir, 'b': ib, 't': it}
        ax = r['x'] + il
        ay = r['y'] + ib
        aw = r['w'] - il - ir
        ah = r['h'] - ib - it

        # A sash on the OUTER perimeter (on_l/on_r/on_b/on_t) was being run
        # straight out to the square W x H pane-cell edge via il/ir/ib/it
        # above. That's correct for a rectangular/arched/gothic outer frame,
        # but for a circular frame the outer frame is a ring — running the
        # sash out to the square cell edge pokes it past the round frame,
        # which is the rectangular shape visible over the circular window.
        # Pull those perimeter edges back to the ring's own inner boundary
        # (worst case across the sash's own span, so it never pokes out at
        # any point along that edge) instead of the flat pane-cell edge.
        if shape == 'circular':
            if on_l or on_r:
                y_lo_s = min(max(ay, 1e-6), H - 1e-6)
                y_hi_s = min(max(ay + ah, 1e-6), H - 1e-6)
                spans = [s for s in (
                    _ellipse_span_x(y_lo_s, cx, cy, rx_in, ry_in),
                    _ellipse_span_x(y_hi_s, cx, cy, rx_in, ry_in),
                    _ellipse_span_x((y_lo_s + y_hi_s) / 2.0, cx, cy, rx_in, ry_in),
                ) if s is not None]
                if spans:
                    if on_l:
                        new_ax = max(ax, max(s[0] for s in spans))
                        aw -= (new_ax - ax)
                        ax = new_ax
                    if on_r:
                        new_right = min(ax + aw, min(s[1] for s in spans))
                        aw = new_right - ax
            if on_b or on_t:
                x_lo_s = min(max(ax, 1e-6), W - 1e-6)
                x_hi_s = min(max(ax + aw, 1e-6), W - 1e-6)
                spans = [s for s in (
                    _ellipse_span_y(x_lo_s, cx, cy, rx_in, ry_in),
                    _ellipse_span_y(x_hi_s, cx, cy, rx_in, ry_in),
                    _ellipse_span_y((x_lo_s + x_hi_s) / 2.0, cx, cy, rx_in, ry_in),
                ) if s is not None]
                if spans:
                    if on_b:
                        new_ay = max(ay, max(s[0] for s in spans))
                        ah -= (new_ay - ay)
                        ay = new_ay
                    if on_t:
                        new_top = min(ay + ah, min(s[1] for s in spans))
                        ah = new_top - ay

        if aw <= 2 * sb or ah <= 2 * sb:
            continue
        sash_rects[r['i']] = (ax, ay, aw, ah)
        _add_rect_frame(A, f'S{si}', ROLE_SASH, ax, ay, aw, ah, sb,
                        p_sash['depth'], p_sash['code'])

    # ── 4. GLASS / PANEL CELLS + GLAZING BEAD ────────────────────────
    p_bead = profiles.get(ROLE_GLAZING_BEAD)
    bead_depth = p_bead['depth'] if profiles.has(ROLE_GLAZING_BEAD) else 18.0
    bi = 0
    for r in rects:
        opening = r['opening']
        is_sash = _is_opening(opening) and have_sash and r['i'] in sash_insets
        if is_sash:
            # glass sits inside the sash's own inner face, not the plain
            # mullion/frame inset — keeps glass/bead flush with the sash rect.
            si_ins = sash_insets[r['i']]
            inset = {k: si_ins[k] + sb for k in ('l', 'r', 'b', 't')}
        else:
            inset = _glass_inset(r, bar_j, bar_h, bar_c, mb, tb, W, H)
        gx = r['x'] + inset['l']
        gy = r['y'] + inset['b']
        gw = r['w'] - inset['l'] - inset['r']
        gh = r['h'] - inset['t'] - inset['b']
        if gw <= 0 or gh <= 0:
            continue
        clip_path = None
        if shape == 'circular':
            # Clip the glass rectangle to the ring's inner-face ellipse so it
            # never pokes past the round frame at the pane's outer corner.
            rect_poly = [(gx, gy), (gx + gw, gy), (gx + gw, gy + gh), (gx, gy + gh)]
            clipped = _clip_polygon_convex(rect_poly, ellipse_poly)
            if len(clipped) < 3:
                continue
            clip_path = clipped
        A.glass.append(GlassCell(
            id=f"G{r['i']+1}", x=gx, y=gy, w=gw, h=gh,
            infill=r['infill'], opening=opening,
            thickness=(dep * 0.6 if r['infill'] == 'panel' else 24.0),
            clip_path=clip_path))

        # Bead fills the ring between the glass edge and the surface it
        # actually rebates into: for a sash pane that's the sash's OWN
        # inner face (bar width sb) — not the sash's outer engagement with
        # the frame/mullion, which the sash member itself already fills.
        # Using the full pane-to-glass inset here would duplicate/overlap
        # the sash solid over the whole rebate-engagement zone.
        # For a circular frame the bead is skipped on the pane's ring-facing
        # side (a straight bar there would poke past the arc just like the
        # glass did) — same simplification already used for the outer
        # frame's internal dividers/glass not being individually chamfered
        # bead-by-bead; the ring member itself covers that edge visually.
        bi += 1
        if is_sash and r['i'] in sash_rects:
            ax, ay, aw, ah = sash_rects[r['i']]
            _add_bead_ring(A, f'B{bi}', ax, ay, aw, ah, sb, sb, sb, sb,
                           bead_depth, p_bead['code'])
        elif shape != 'circular':
            _add_bead_ring(A, f'B{bi}', r['x'], r['y'], r['w'], r['h'],
                           inset['l'], inset['r'], inset['b'], inset['t'],
                           bead_depth, p_bead['code'])

    return A


# ── helpers ───────────────────────────────────────────────────────────────────
def _is_opening(opening: str) -> bool:
    o = (opening or '').lower()
    return bool(o) and 'fixed' not in o


def _glass_inset(rect, bar_j, bar_h, bar_c, mb, tb, W, H):
    """
    How far the clear glass sits in from each side of the pane aperture.
    Outer edges tuck into the frame rebate (half the frame bar); internal edges
    meet the mullion/transom face (half that member's bar).
    """
    eps = 0.5
    on_left   = rect['x'] <= eps
    on_right  = rect['x'] + rect['w'] >= W - eps
    on_bottom = rect['y'] <= eps
    on_top    = rect['y'] + rect['h'] >= H - eps
    return {
        'l': (bar_j / 2) if on_left   else (mb / 2),
        'r': (bar_j / 2) if on_right  else (mb / 2),
        'b': (bar_c / 2) if on_bottom else (tb / 2),
        't': (bar_h / 2) if on_top    else (tb / 2),
    }


def _add_rect_frame(A: Assembly, prefix, role, x, y, w, h, bar, depth, code):
    """Add a mitred 4-member rectangular sub-frame (used for sashes)."""
    # top
    A.members.append(Member(
        id=f'{prefix}_top', role=role, orientation=ORI_H,
        x1=x, y1=y + h - bar / 2, x2=x + w, y2=y + h - bar / 2,
        bar_width=bar, depth=depth,
        joint_start=JOINT_MITRE, joint_end=JOINT_MITRE,
        miter_start_deg=45, miter_end_deg=45, profile_code=code))
    # bottom
    A.members.append(Member(
        id=f'{prefix}_bot', role=role, orientation=ORI_H,
        x1=x, y1=y + bar / 2, x2=x + w, y2=y + bar / 2,
        bar_width=bar, depth=depth,
        joint_start=JOINT_MITRE, joint_end=JOINT_MITRE,
        miter_start_deg=45, miter_end_deg=45, profile_code=code))
    # left
    A.members.append(Member(
        id=f'{prefix}_L', role=role, orientation=ORI_V,
        x1=x + bar / 2, y1=y + bar, x2=x + bar / 2, y2=y + h - bar,
        bar_width=bar, depth=depth,
        joint_start=JOINT_MITRE, joint_end=JOINT_MITRE,
        miter_start_deg=45, miter_end_deg=45, profile_code=code))
    # right
    A.members.append(Member(
        id=f'{prefix}_R', role=role, orientation=ORI_V,
        x1=x + w - bar / 2, y1=y + bar, x2=x + w - bar / 2, y2=y + h - bar,
        bar_width=bar, depth=depth,
        joint_start=JOINT_MITRE, joint_end=JOINT_MITRE,
        miter_start_deg=45, miter_end_deg=45, profile_code=code))


def _add_bead_ring(A: Assembly, prefix, x, y, w, h, il, ir, ib, it, depth, code):
    """
    Add a glazing-bead ring filling the gap between a pane's aperture (x,y,w,h)
    and its glass edge. Unlike `_add_rect_frame`, each side can have a
    different width (il/ir/ib/it) since jamb, mullion and sash rebates differ.
    Sides thinner than 1mm are skipped as not worth modelling.
    """
    if it >= 1.0:
        A.members.append(Member(
            id=f'{prefix}_top', role=ROLE_GLAZING_BEAD, orientation=ORI_H,
            x1=x, y1=y + h - it / 2, x2=x + w, y2=y + h - it / 2,
            bar_width=it, depth=depth,
            joint_start=JOINT_BUTT, joint_end=JOINT_BUTT, profile_code=code))
    if ib >= 1.0:
        A.members.append(Member(
            id=f'{prefix}_bot', role=ROLE_GLAZING_BEAD, orientation=ORI_H,
            x1=x, y1=y + ib / 2, x2=x + w, y2=y + ib / 2,
            bar_width=ib, depth=depth,
            joint_start=JOINT_BUTT, joint_end=JOINT_BUTT, profile_code=code))
    if il >= 1.0:
        A.members.append(Member(
            id=f'{prefix}_L', role=ROLE_GLAZING_BEAD, orientation=ORI_V,
            x1=x + il / 2, y1=y + ib, x2=x + il / 2, y2=y + h - it,
            bar_width=il, depth=depth,
            joint_start=JOINT_BUTT, joint_end=JOINT_BUTT, profile_code=code))
    if ir >= 1.0:
        A.members.append(Member(
            id=f'{prefix}_R', role=ROLE_GLAZING_BEAD, orientation=ORI_V,
            x1=x + w - ir / 2, y1=y + ib, x2=x + w - ir / 2, y2=y + h - it,
            bar_width=ir, depth=depth,
            joint_start=JOINT_BUTT, joint_end=JOINT_BUTT, profile_code=code))


# ── cut list (bonus — proves the graph is complete) ─────────────────────────────
def cut_list(assembly: Assembly) -> list:
    """
    A fabrication cut list from the member graph: one row per member with its
    role, profile, cut length and end treatments. Handy for the quote PDF later.
    """
    rows = []
    for m in assembly.members:
        rows.append({
            'id': m.id,
            'role': m.role,
            'profile': m.profile_code,
            'length_mm': round(m.length, 1),
            'orientation': m.orientation,
            'end_start': m.joint_start,
            'end_end': m.joint_end,
        })
    return rows