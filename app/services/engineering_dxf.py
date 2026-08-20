"""
engineering_dxf.py — engineering drawing sheet generator (DXF output).

Layout (all coords in mm, modelspace 1:1):

  ┌──────────────────────────────────────────────────────────────────┐
  │  ELEVATION (0,SHEET_BOT+TB_H+GAP)        │  PANE SCHEDULE      │
  │                                            │  (right of elev)    │
  │                                            │                     │
  ├────────────────────────────────────────────┘                     │
  │  HORIZONTAL SECTION A-A (plan strip)                             │
  │  SECTION A-A (vertical, right of elev)                           │
  ├──────────────────────────────────────────────────────────────────┤
  │  TITLE BLOCK (bottom full-width strip)                           │
  └──────────────────────────────────────────────────────────────────┘
  Sheet border wraps everything with margin.
"""
import json, logging, math, io, datetime
from ezdxf.enums import TextEntityAlignment
logger = logging.getLogger(__name__)

L_FRAME = 'FRAME'
L_SASH  = 'SASH'
L_GLASS = 'GLASS'
L_SECT  = 'SECTIONS'
L_DIM   = 'DIMENSIONS'
L_ANNOT = 'ANNOTATION'
L_SWING = 'SWING'
L_BORDER= 'BORDER'

# ── Title-block height and margin constants ──────────────────────────
TB_H   = 200    # title block strip height (mm)
GAP    = 200    # gap between plan strip bottom and title block top
MARGIN = 150    # sheet border outer margin
SCHED_GAP = 350 # gap between elevation right edge and pane schedule
DIM_ABOVE = 260 # space above elevation for dimension + label
DIM_LEFT  = 280 # space left of elevation for height dimension
DIM_BELOW = 300 # space below plan strip for dimension + section label


def generate_engineering_dxf(window, panes, tenant_id=None) -> bytes:
    import ezdxf
    doc = ezdxf.new('R2010', setup=True)
    msp = doc.modelspace()

    for name, color in ((L_FRAME, 5), (L_SASH, 4), (L_GLASS, 150),
                        (L_SECT, 3), (L_DIM, 1), (L_ANNOT, 2),
                        (L_SWING, 6), (L_BORDER, 7)):
        if name not in doc.layers:
            doc.layers.add(name, color=color)

    W   = float(window.width_mm)
    H   = float(window.height_mm)
    prof = _load_profile(tenant_id, getattr(window, 'material', 'Aluminium'))
    bar  = prof['bar']
    dep  = prof['depth']

    design = _load_design(window)
    cells  = _cells(panes, design)

    # ── Y offsets ────────────────────────────────────────────────────
    # Plan strip sits BELOW elevation.  Elevation origin stays at Y=0.
    plan_h   = dep + 40          # strip occupies this vertical band
    plan_y0  = -(dep + 120)      # top of strip (Y going up = negative)
    plan_y1  = plan_y0 - plan_h  # bottom of strip

    # Title block bottom edge — below plan strip + DIM_BELOW + GAP
    tb_top = plan_y1 - DIM_BELOW - GAP
    tb_bot = tb_top - TB_H

    # ── X offsets ────────────────────────────────────────────────────
    # Vertical Section A-A sits to the right of the elevation.
    sect_x = W + 300
    # Pane schedule sits further right of the section
    sched_x = sect_x + bar + SCHED_GAP

    # ── 1. Elevation ─────────────────────────────────────────────────
    _elevation(msp, W, H, bar, cells)

    # ── 2. Plan strip ────────────────────────────────────────────────
    _plan_strip(msp, W, bar, dep, cells, prof, plan_y0)

    # ── 3. Vertical Section A-A ──────────────────────────────────────
    _vertical_section(msp, H, bar, dep, prof, sect_x)

    # ── 4. Pane schedule ─────────────────────────────────────────────
    _pane_schedule(msp, cells, design, sched_x, H)

    # ── 5. Dimensions ────────────────────────────────────────────────
    _dimensions(msp, W, H, cells, plan_y0, plan_y1, sect_x, dep)

    # ── 6. View labels ───────────────────────────────────────────────
    _add_text(msp, 'ELEVATION',        W / 2, H + 80,  45, L_ANNOT, halign=1)
    _add_text(msp, 'SCALE 1:1',        W / 2, H + 30,  30, L_ANNOT, halign=1)
    _add_text(msp, 'HORIZONTAL SECTION A-A',
              W / 2, plan_y1 - 40,   35, L_ANNOT, halign=1)
    _add_text(msp, f'PROFILE: {prof["name"]}  ·  '
              f'{bar:.0f}mm FRAME  ·  {dep:.0f}mm DEPTH',
              W / 2, plan_y1 - 90,   25, L_ANNOT, halign=1)
    _add_text(msp, 'SECTION A-A',
              sect_x + bar / 2, H + 80, 35, L_ANNOT, halign=1)

    # ── 7. Title block ───────────────────────────────────────────────
    # Sheet width = from left dim extent to right edge of schedule (or sect)
    content_right = max(sched_x + 900, sect_x + bar + 200)
    content_left  = -DIM_LEFT
    sheet_w = content_right - content_left
    _title_block(msp, window, prof, content_left, tb_bot, sheet_w, TB_H, design)

    # ── 8. Sheet border ──────────────────────────────────────────────
    bx0 = content_left  - MARGIN
    bx1 = content_right + MARGIN
    by0 = tb_bot        - MARGIN
    by1 = H + DIM_ABOVE + MARGIN
    # outer border
    msp.add_lwpolyline(
        [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)],
        close=True, dxfattribs={'layer': L_BORDER})
    # inner margin line
    m2 = 30
    msp.add_lwpolyline(
        [(bx0+m2, by0+m2), (bx1-m2, by0+m2),
         (bx1-m2, by1-m2), (bx0+m2, by1-m2)],
        close=True, dxfattribs={'layer': L_BORDER})

    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode('utf-8')


# ═══════════════════════════════════════════════════ helpers ════════

def _add_text(msp, s, x, y, h, layer, halign=0):
    """Add a TEXT entity.  halign: 0=left, 1=centre, 2=right."""
    import ezdxf
    t = msp.add_text(s, dxfattribs={'layer': layer, 'height': h})
    if halign == 1:
        t.set_placement((x, y), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
    elif halign == 2:
        t.set_placement((x, y), align=ezdxf.enums.TextEntityAlignment.RIGHT)
    else:
        t.set_placement((x, y))
    return t


def _hline(msp, x0, x1, y, layer=L_BORDER):
    msp.add_line((x0, y), (x1, y), dxfattribs={'layer': layer})


def _vline(msp, x, y0, y1, layer=L_BORDER):
    msp.add_line((x, y0), (x, y1), dxfattribs={'layer': layer})


# ═══════════════════════════════════════════════════ title block ═════

def _title_block(msp, window, prof, ox, oy, sw, th, design):
    """
    Full-width title block strip.
    ox,oy = bottom-left corner.  sw = sheet width.  th = strip height.
    """
    date_str = datetime.date.today().strftime('%d/%m/%Y')
    label    = getattr(window, 'label', 'Unit') or 'Unit'
    mat      = getattr(window, 'material', '')
    colour   = getattr(window, 'frame_colour_name', '')
    W, H     = float(window.width_mm), float(window.height_mm)

    # Try to get tenant/company name from the Window → Project → Tenant chain
    company = 'QUOTING STUDIO'
    try:
        company = (window.project.tenant.name or company).upper()
    except Exception:
        pass

    # Build a drawing number: QS-<window_id>
    drw_no = f'QS-{window.id}'

    # Outer border of title block
    pts = [(ox, oy), (ox+sw, oy), (ox+sw, oy+th), (ox, oy+th)]
    msp.add_lwpolyline(pts, close=True, dxfattribs={'layer': L_BORDER})

    # ── Left large cell: company name ────────────────────────────────
    company_w = sw * 0.22
    _vline(msp, ox + company_w, oy, oy + th)
    _add_text(msp, company,
              ox + company_w / 2, oy + th * 0.55, th * 0.22, L_ANNOT, halign=1)
    _add_text(msp, 'QUOTING STUDIO',
              ox + company_w / 2, oy + th * 0.25, th * 0.10, L_ANNOT, halign=1)

    # ── Middle cell: drawing description ────────────────────────────
    mid_x0 = ox + company_w
    mid_w  = sw * 0.42
    mid_x1 = mid_x0 + mid_w
    _vline(msp, mid_x1, oy, oy + th)

    # horizontal dividers inside middle
    row_h = th / 4
    for i in (1, 2, 3):
        _hline(msp, mid_x0, mid_x1, oy + row_h * i)

    cells_desc = [
        ('Drawing Title',  label),
        ('Material',       f'{mat}  ·  {colour}' if colour else mat),
        ('Size',           f'{W:.0f} × {H:.0f} mm'),
        ('Profile',        f'{prof["name"]}  {prof["bar"]:.0f}×{prof["depth"]:.0f}mm'),
    ]
    for i, (hdr, val) in enumerate(cells_desc):
        cy = oy + row_h * (3 - i)  # top row = index 0 in list
        _add_text(msp, hdr,
                  mid_x0 + 20, cy + row_h * 0.72, row_h * 0.20, L_ANNOT)
        _add_text(msp, val,
                  mid_x0 + 20, cy + row_h * 0.30, row_h * 0.28, L_ANNOT)

    # ── Right cell: drawing number / date / scale ────────────────────
    right_x0 = mid_x1
    right_w  = sw - company_w - mid_w
    row_h2   = th / 3
    for i in (1, 2):
        _hline(msp, right_x0, ox + sw, oy + row_h2 * i)

    right_cells = [
        ('Drawing No.',  drw_no),
        ('Date',         date_str),
        ('Scale',        '1:1 (modelspace mm)'),
    ]
    for i, (hdr, val) in enumerate(right_cells):
        cy = oy + row_h2 * (2 - i)
        cx = right_x0 + right_w / 2
        _add_text(msp, hdr, cx, cy + row_h2 * 0.70, row_h2 * 0.18, L_ANNOT, halign=1)
        _add_text(msp, val,  cx, cy + row_h2 * 0.25, row_h2 * 0.28, L_ANNOT, halign=1)


# ═══════════════════════════════════════════════════ data helpers ════

def _load_design(window):
    try:
        if getattr(window, 'design_json', None):
            return json.loads(window.design_json)
    except Exception:
        pass
    return None


def _cells(panes, design):
    """Normalized pane rects [(x,y,w,h,opening), ...] y from bottom."""
    out = []
    if design and design.get('panes'):
        for p in design['panes']:
            out.append((float(p['x']),
                        1.0 - float(p['y']) - float(p['h']),
                        float(p['w']),
                        float(p['h']),
                        p.get('opening', 'Fixed')))
    else:
        for p in panes:
            out.append((float(p.x_norm),
                        1.0 - float(p.y_norm) - float(p.h_norm),
                        float(p.w_norm),
                        float(p.h_norm),
                        getattr(p, 'opening_type', 'Fixed') or 'Fixed'))
    return out or [(0, 0, 1, 1, 'Fixed')]


def _load_profile(tenant_id, material):
    prof = {'bar': 58.0, 'depth': 70.0, 'rebate_w': 15.0, 'rebate_d': 20.0,
            'name': 'DEFAULT', 'loops': None}
    if not tenant_id:
        return prof
    try:
        from ..models.cad_profile import CadProfile
        p = (CadProfile.query
             .filter_by(tenant_id=tenant_id, material=material,
                        is_active=True, is_default=True).first()
             or CadProfile.query
             .filter_by(tenant_id=tenant_id, is_active=True).first())
        if p:
            prof.update(bar=float(p.bar_width_mm),
                        depth=float(p.depth_mm),
                        rebate_w=float(p.rebate_w_mm or 15),
                        rebate_d=float(p.rebate_d_mm or 20),
                        name=p.code or p.name)
            if p.geometry_json:
                try:
                    loops = json.loads(p.geometry_json)
                    if loops:
                        prof['loops'] = loops
                except Exception:
                    pass
    except Exception as exc:
        logger.warning('engineering_dxf profile lookup failed: %s', exc)
    return prof


def _profile_pts(prof):
    """Profile outline(s) normalised to (0,0)..(bar,depth)."""
    if prof.get('loops'):
        allx = [float(x) for lp in prof['loops'] for x, y in lp]
        ally = [float(y) for lp in prof['loops'] for x, y in lp]
        if allx and ally:
            mx, my = min(allx), min(ally)
            return [[(float(x) - mx, float(y) - my) for x, y in lp]
                    for lp in prof['loops']]
    b, d = prof['bar'], prof['depth']
    rw = min(prof['rebate_w'], b - 4)
    rd = min(prof['rebate_d'], d - 4)
    return [[(0, 0), (b, 0), (b, d - rd), (b - rw, d - rd),
             (b - rw, d), (0, d)]]


def _place_loops(msp, loops, ox, oy, rot_deg=0, mirror_u=False,
                 layer=L_SECT):
    a = math.radians(rot_deg)
    ca, sa = math.cos(a), math.sin(a)
    for lp in loops:
        pts = []
        for u, v in lp:
            if mirror_u:
                u = -u
            pts.append((ox + u * ca - v * sa,
                        oy + u * sa + v * ca))
        if len(pts) >= 3:
            msp.add_lwpolyline(pts, close=True,
                               dxfattribs={'layer': layer})


# ═══════════════════════════════════════════════════ views ═══════════

def _elevation(msp, W, H, bar, cells):
    msp.add_lwpolyline(
        [(0, 0), (W, 0), (W, H), (0, H)], close=True,
        dxfattribs={'layer': L_FRAME})
    msp.add_lwpolyline(
        [(bar, bar), (W - bar, bar), (W - bar, H - bar), (bar, H - bar)],
        close=True, dxfattribs={'layer': L_FRAME})
    mb = bar * 0.6
    seen_v, seen_h = set(), set()
    for (x, y, w, h, opening) in cells:
        gx, gy, gw, gh = x * W, y * H, w * W, h * H
        # mullion
        rx = x + w
        if 0.001 < rx < 0.999 and round(rx, 3) not in seen_v:
            seen_v.add(round(rx, 3))
            mx = rx * W
            msp.add_lwpolyline(
                [(mx - mb/2, bar), (mx + mb/2, bar),
                 (mx + mb/2, H - bar), (mx - mb/2, H - bar)],
                close=True, dxfattribs={'layer': L_FRAME})
        # transom
        ty = y + h
        if 0.001 < ty < 0.999 and round(ty, 3) not in seen_h:
            seen_h.add(round(ty, 3))
            my = ty * H
            msp.add_lwpolyline(
                [(bar, my - mb/2), (W - bar, my - mb/2),
                 (W - bar, my + mb/2), (bar, my + mb/2)],
                close=True, dxfattribs={'layer': L_FRAME})
        # glass rect
        gi = bar + 4
        glx = gx + (gi if x <= 0.001 else mb/2 + 4)
        gly = gy + (gi if y <= 0.001 else mb/2 + 4)
        grx = gx + gw - (gi if x + w >= 0.999 else mb/2 + 4)
        gry = gy + gh - (gi if y + h >= 0.999 else mb/2 + 4)
        if grx > glx and gry > gly:
            msp.add_lwpolyline(
                [(glx, gly), (grx, gly), (grx, gry), (glx, gry)],
                close=True, dxfattribs={'layer': L_GLASS})
            _opener_symbol(msp, glx, gly, grx - glx, gry - gly, opening)


def _opener_symbol(msp, x, y, w, h, opening):
    if not opening or opening == 'Fixed':
        return
    d = {'layer': L_SASH, 'linetype': 'DASHED'}
    cx, cy = x + w/2, y + h/2
    op = opening
    if 'Left' in op or op == 'Casement':
        msp.add_line((x + w, y),     (x + w*0.1, cy), dxfattribs=d)
        msp.add_line((x + w, y + h), (x + w*0.1, cy), dxfattribs=d)
    elif 'Right' in op:
        msp.add_line((x,     y),     (x + w*0.9, cy), dxfattribs=d)
        msp.add_line((x,     y + h), (x + w*0.9, cy), dxfattribs=d)
    elif 'Top' in op:
        msp.add_line((x,     y),     (cx, y + h*0.9), dxfattribs=d)
        msp.add_line((x + w, y),     (cx, y + h*0.9), dxfattribs=d)
    elif 'Slid' in op:
        msp.add_line((x + w*0.15, cy), (x + w*0.85, cy), dxfattribs=d)


def _plan_strip(msp, W, bar, dep, cells, prof, plan_y0):
    """
    Horizontal section (plan strip).
    plan_y0 = Y of the TOP edge of the strip.
    The strip occupies Y = [plan_y0 - dep .. plan_y0].
    Profile sections placed at LEFT and RIGHT ends, within X = [0..W].
    """
    loops = _profile_pts(prof)
    plan_y1 = plan_y0 - dep   # bottom edge of strip

    # Left jamb: profile cross-section, bar along X (0→bar), depth down (plan_y1→plan_y0)
    # Normalise the profile so bar dimension maps to X, depth maps downward
    _place_loops(msp, loops, 0,     plan_y1, rot_deg=0,   mirror_u=False)
    # Right jamb: mirror so it faces inward (bar shrinks from W back to W-bar)
    _place_loops(msp, loops, W,     plan_y1, rot_deg=0,   mirror_u=True)

    # Wall lines across the strip (between the two jamb sections)
    for y_edge in (plan_y0, plan_y1):
        msp.add_line((bar, y_edge), (W - bar, y_edge),
                     dxfattribs={'layer': L_SECT})

    # Mullion / stile pairs at every internal vertical division
    mb = bar * 0.6
    seen = set()
    for (x, y, w, h, opening) in cells:
        rx = x + w
        if 0.001 < rx < 0.999 and round(rx, 3) not in seen:
            seen.add(round(rx, 3))
            mx = rx * W
            # stile pair (⊔ shapes)
            st_d = dep * 0.55
            for sx in (mx - mb/2 - 14, mx + mb/2):
                msp.add_lwpolyline(
                    [(sx, plan_y0), (sx + 14, plan_y0),
                     (sx + 14, plan_y0 - st_d), (sx, plan_y0 - st_d)],
                    close=True, dxfattribs={'layer': L_SASH})
            # mullion body
            msp.add_lwpolyline(
                [(mx - mb/2, plan_y0), (mx + mb/2, plan_y0),
                 (mx + mb/2, plan_y1), (mx - mb/2, plan_y1)],
                close=True, dxfattribs={'layer': L_SECT})

        # Swing arc for hinged openers
        if opening and opening not in ('Fixed',) and 'Slid' not in opening:
            gx, gw = x * W, w * W
            if 'Right' in opening:
                cx0, a0, a1 = gx + gw, 90, 160
            else:
                cx0, a0, a1 = gx, 20, 90
            r = min(gw * 0.55, 420)
            msp.add_arc((cx0, plan_y1), r, a0, a1,
                        dxfattribs={'layer': L_SWING, 'color': 6})


def _vertical_section(msp, H, bar, dep, prof, sect_x):
    """Section A-A: head + cill profile with glass line between."""
    loops = _profile_pts(prof)
    _place_loops(msp, loops, sect_x, 0,   rot_deg=0)             # cill
    _place_loops(msp, loops, sect_x, H,   rot_deg=180, mirror_u=True)  # head
    gx = sect_x + bar * 0.45
    for dx in (0, 24):
        msp.add_line((gx + dx, dep + 6), (gx + dx, H - dep - 6),
                     dxfattribs={'layer': L_GLASS})


def _pane_schedule(msp, cells, design, ox, top_y):
    """
    Pane schedule table: right of elevation.
    Rows: # | Opener | Glazing | Size
    """
    col_w = [80, 240, 200, 220]   # column widths
    row_h = 80                    # row height
    headers = ['#', 'Opener', 'Glazing', 'Size']

    total_w = sum(col_w)
    n_rows  = len(cells) + 1      # +1 for header
    total_h = n_rows * row_h

    # outer border
    msp.add_lwpolyline(
        [(ox, top_y - total_h), (ox + total_w, top_y - total_h),
         (ox + total_w, top_y), (ox, top_y)],
        close=True, dxfattribs={'layer': L_BORDER})

    # column dividers
    cx = ox
    for cw in col_w[:-1]:
        cx += cw
        msp.add_line((cx, top_y - total_h), (cx, top_y),
                     dxfattribs={'layer': L_BORDER})

    # header row
    _add_text(msp, 'PANE SCHEDULE',
              ox + total_w / 2, top_y + 40, 35, L_ANNOT, halign=1)
    msp.add_line((ox, top_y - row_h), (ox + total_w, top_y - row_h),
                 dxfattribs={'layer': L_BORDER})
    cx = ox
    for i, hdr in enumerate(headers):
        _add_text(msp, hdr,
                  cx + col_w[i] * 0.5, top_y - row_h * 0.45,
                  28, L_ANNOT, halign=1)
        cx += col_w[i]

    # data rows
    for r_idx, (x, y, w, h, opening) in enumerate(cells):
        ry = top_y - (r_idx + 2) * row_h
        msp.add_line((ox, ry), (ox + total_w, ry),
                     dxfattribs={'layer': L_BORDER})
        # try to get glazing info from design
        glazing = 'DGU'
        if design and design.get('panes') and r_idx < len(design['panes']):
            dp = design['panes'][r_idx]
            glazing = dp.get('glazing') or dp.get('glazingType') or 'DGU'
        cx = ox
        vals = [str(r_idx + 1), opening or 'Fixed', glazing,
                f'{w*100:.0f}×{h*100:.0f}']  # placeholder — real mm needs W/H
        for i, val in enumerate(vals):
            _add_text(msp, val,
                      cx + col_w[i] * 0.5, ry + row_h * 0.35,
                      24, L_ANNOT, halign=1)
            cx += col_w[i]


def _dimensions(msp, W, H, cells, plan_y0, plan_y1, sect_x, dep):
    d  = {'layer': L_DIM}
    ov = {'dimtxt': 45, 'dimasz': 32, 'dimexe': 18, 'dimexo': 12,
          'dimdec': 0,  'dimclrt': 1, 'dimclrd': 1, 'dimclre': 1,
          'dimlfac': 1}

    # overall width — above elevation
    dim = msp.add_aligned_dim(
        p1=(0, H), p2=(W, H), distance=140, dxfattribs=d, override=ov)
    dim.render()

    # overall height — right of section
    dim = msp.add_aligned_dim(
        p1=(sect_x + dep + 20, 0), p2=(sect_x + dep + 20, H),
        distance=110, dxfattribs=d, override=ov)
    dim.render()

    # per-pane widths — below plan strip
    edges = sorted({round(c[0], 4) for c in cells} |
                   {round(c[0] + c[2], 4) for c in cells})
    if len(edges) > 2:
        for i in range(len(edges) - 1):
            x1, x2 = edges[i] * W, edges[i + 1] * W
            dim = msp.add_aligned_dim(
                p1=(x1, plan_y1), p2=(x2, plan_y1),
                distance=-110, dxfattribs=d, override=ov)
            dim.render()

    # per-row heights — left of elevation
    rows = sorted({round(c[1], 4) for c in cells} |
                  {round(c[1] + c[3], 4) for c in cells})
    if len(rows) > 2:
        for i in range(len(rows) - 1):
            y1, y2 = rows[i] * H, rows[i + 1] * H
            dim = msp.add_aligned_dim(
                p1=(0, y1), p2=(0, y2),
                distance=-130, dxfattribs=d, override=ov)
            dim.render()