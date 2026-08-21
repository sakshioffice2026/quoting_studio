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

import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)

# ── roles ────────────────────────────────────────────────────────────────
ROLE_HEAD         = 'head'          # top outer-frame member
ROLE_CILL         = 'cill'          # bottom outer-frame member
ROLE_JAMB         = 'jamb'          # left / right outer-frame members
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

    @property
    def length(self) -> float:
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

    # ── 1. OUTER FRAME ──────────────────────────────────────────────
    # Head (top) — centre line at y = H - bar_h/2, spanning full width.
    A.members.append(Member(
        id='F_head', role=ROLE_HEAD, orientation=ORI_H,
        x1=0, y1=H - bar_h / 2, x2=W, y2=H - bar_h / 2,
        bar_width=bar_h, depth=p_head['depth'],
        joint_start=JOINT_MITRE, joint_end=JOINT_MITRE,
        miter_start_deg=45, miter_end_deg=45,
        profile_code=p_head['code']))
    # Cill (bottom)
    cill_role = ROLE_CILL if unit_type != 'door' else ROLE_THRESHOLD
    A.members.append(Member(
        id='F_cill', role=cill_role, orientation=ORI_H,
        x1=0, y1=bar_c / 2, x2=W, y2=bar_c / 2,
        bar_width=bar_c, depth=p_cill['depth'],
        joint_start=JOINT_MITRE, joint_end=JOINT_MITRE,
        miter_start_deg=45, miter_end_deg=45,
        profile_code=p_cill['code']))
    # Jambs (left / right) — run between head and cill inner faces.
    jy1, jy2 = bar_c, H - bar_h
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
            # clamp inside outer frame
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
        A.glass.append(GlassCell(
            id=f"G{r['i']+1}", x=gx, y=gy, w=gw, h=gh,
            infill=r['infill'], opening=opening,
            thickness=(dep * 0.6 if r['infill'] == 'panel' else 24.0)))

        # Bead fills the ring between the glass edge and the surface it
        # actually rebates into: for a sash pane that's the sash's OWN
        # inner face (bar width sb) — not the sash's outer engagement with
        # the frame/mullion, which the sash member itself already fills.
        # Using the full pane-to-glass inset here would duplicate/overlap
        # the sash solid over the whole rebate-engagement zone.
        bi += 1
        if is_sash and r['i'] in sash_rects:
            ax, ay, aw, ah = sash_rects[r['i']]
            _add_bead_ring(A, f'B{bi}', ax, ay, aw, ah, sb, sb, sb, sb,
                           bead_depth, p_bead['code'])
        else:
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