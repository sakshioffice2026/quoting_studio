"""
engineering_dxf.py — engineering drawing sheet generator (DXF output).
FIXED VERSION — All layers, functions, and geometry corrections applied.

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

# FIXED: Corrected layer names per specification
L_FRAME = 'PROF_OUTLINE'
L_SASH  = 'PROF_OUTLINE'
L_GLASS = 'GLASS_OUTLINE'
L_SECT  = 'PROF_OUTLINE'
L_DIM   = 'DIM_ANNOTATION'
L_ANNOT = 'DIM_ANNOTATION'
L_SWING = 'PROF_OUTLINE'
L_BORDER= 'PROF_OUTLINE'
L_HATCH = 'PROF_HATCH'
L_SEAL  = 'GASKET_SEAL'
L_HW    = 'HARDWARE'
L_AXIS  = 'CENTER_AXIS'

TB_H   = 200
GAP    = 200
MARGIN = 150
SCHED_GAP = 350
DIM_ABOVE = 260
DIM_LEFT  = 280
DIM_BELOW = 300


def generate_engineering_dxf(window, panes, tenant_id=None) -> bytes:
    import ezdxf
    from app.services.dxf_layers import setup_layers, setup_dimstyle, setup_text_styles
    
    doc = ezdxf.new('R2010', setup=True)
    msp = doc.modelspace()

    # FIXED: Use centralized layer setup instead of hardcoded
    setup_layers(doc)
    setup_text_styles(doc)
    
    W   = float(window.width_mm)
    H   = float(window.height_mm)
    prof = _load_profile(tenant_id, getattr(window, 'material', 'Aluminium'))
    bar  = prof['bar']
    dep  = prof['depth']
    
    setup_dimstyle(doc, bar_width=bar)

    design = _load_design(window)
    cells  = _cells(panes, design)

    plan_h   = dep + 40
    plan_y0  = -(dep + 120)
    plan_y1  = plan_y0 - plan_h

    tb_top = plan_y1 - DIM_BELOW - GAP
    tb_bot = tb_top - TB_H

    sect_x = W + 300
    sched_x = sect_x + bar + SCHED_GAP

    _elevation(msp, W, H, bar, cells)
    _plan_strip(msp, W, bar, dep, cells, prof, plan_y0)
    _vertical_section(msp, H, bar, dep, prof, sect_x)
    _pane_schedule(msp, cells, design, sched_x, H)
    _dimensions(msp, W, H, cells, plan_y0, plan_y1, sect_x, dep)

    # FIXED: Add missing geometry functions
    _add_hatching(msp, cells, W, H, bar)
    _add_gasket_seals(msp, W, H, bar)
    _add_hardware_cutouts(msp, W, H, bar)
    _add_frame_centerlines(msp, W, H, bar)
    _add_drainage_paths(msp, W, H, bar, prof)

    _add_text(msp, 'ELEVATION',        W / 2, H + 80,  45, L_ANNOT, halign=1)
    _add_text(msp, 'SCALE 1:1',        W / 2, H + 30,  30, L_ANNOT, halign=1)
    _add_text(msp, 'HORIZONTAL SECTION A-A',
              W / 2, plan_y1 - 40,   35, L_ANNOT, halign=1)
    _add_text(msp, f'PROFILE: {prof["name"]}  ·  '
              f'{bar:.0f}mm FRAME  ·  {dep:.0f}mm DEPTH',
              W / 2, plan_y1 - 90,   25, L_ANNOT, halign=1)
    _add_text(msp, 'SECTION A-A',
              sect_x + bar / 2, H + 80, 35, L_ANNOT, halign=1)

    content_right = max(sched_x + 900, sect_x + bar + 200)
    content_left  = -DIM_LEFT
    sheet_w = content_right - content_left
    _title_block(msp, window, prof, content_left, tb_bot, sheet_w, TB_H, design)

    bx0 = content_left  - MARGIN
    bx1 = content_right + MARGIN
    by0 = tb_bot        - MARGIN
    by1 = H + DIM_ABOVE + MARGIN
    
    msp.add_lwpolyline(
        [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)],
        close=True, dxfattribs={'layer': L_BORDER})
    
    m2 = 30
    msp.add_lwpolyline(
        [(bx0+m2, by0+m2), (bx1-m2, by0+m2),
         (bx1-m2, by1-m2), (bx0+m2, by1-m2)],
        close=True, dxfattribs={'layer': L_BORDER})

    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode('utf-8')


def _add_text(msp, s, x, y, h, layer, halign=0):
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


def _title_block(msp, window, prof, ox, oy, sw, th, design):
    date_str = datetime.date.today().strftime('%d/%m/%Y')
    label    = getattr(window, 'label', 'Unit') or 'Unit'
    mat      = getattr(window, 'material', '')
    colour   = getattr(window, 'frame_colour_name', '')
    W, H     = float(window.width_mm), float(window.height_mm)

    company = 'QUOTING STUDIO'
    try:
        company = (window.project.tenant.name or company).upper()
    except Exception:
        pass

    drw_no = f'QS-{window.id}'

    pts = [(ox, oy), (ox+sw, oy), (ox+sw, oy+th), (ox, oy+th)]
    msp.add_lwpolyline(pts, close=True, dxfattribs={'layer': L_BORDER})

    company_w = sw * 0.22
    _vline(msp, ox + company_w, oy, oy + th)
    _add_text(msp, company,
              ox + company_w / 2, oy + th * 0.55, th * 0.22, L_ANNOT, halign=1)
    _add_text(msp, 'QUOTING STUDIO',
              ox + company_w / 2, oy + th * 0.25, th * 0.10, L_ANNOT, halign=1)

    mid_x0 = ox + company_w
    mid_w  = sw * 0.42
    mid_x1 = mid_x0 + mid_w
    _vline(msp, mid_x1, oy, oy + th)

    row_h = th / 4
    for i in (1, 2, 3):
        _hline(msp, mid_x0, mid_x1, oy + row_h * i)

    cells_desc = [
        ('Drawing Title',  label),
        ('Material',       f'{mat}  ·  {colour}' if colour else mat),
        ('Size',           f'{W:.0f} × {H:.0f} mm'),
        ('Drawn',          date_str)
    ]

    cx = mid_x0
    for i, (k, v) in enumerate(cells_desc):
        cy = oy + (3.5 - i) * row_h
        _add_text(msp, k, cx + 20, cy + row_h * 0.6, th * 0.11, L_ANNOT)
        _add_text(msp, v, cx + 20, cy + row_h * 0.25, th * 0.10, L_ANNOT)

    right_x0 = mid_x1
    _vline(msp, right_x0 + (sw - mid_x1) * 0.5, oy, oy + th)
    _add_text(msp, 'DRAWING NUMBER', right_x0 + 20, oy + th * 0.7, th * 0.10, L_ANNOT)
    _add_text(msp, drw_no, right_x0 + 20, oy + th * 0.3, th * 0.20, L_ANNOT)


def _elevation(msp, W, H, bar, cells):
    mb = bar * 0.6

    msp.add_lwpolyline(
        [(0, 0), (W, 0), (W, H), (0, H)],
        close=True, dxfattribs={'layer': L_FRAME})

    seen_v = set()
    for (x, y, w, h, opening) in cells:
        rx = x + w
        if 0.001 < rx < 0.999 and round(rx, 3) not in seen_v:
            seen_v.add(round(rx, 3))
            mx = rx * W
            msp.add_lwpolyline(
                [(mx - mb/2, 0), (mx + mb/2, 0),
                 (mx + mb/2, H), (mx - mb/2, H)],
                close=True, dxfattribs={'layer': L_FRAME})

        seen_h = set()
        gy, gh = y * H, h * H
        ty = y + h
        if 0.001 < ty < 0.999 and round(ty, 3) not in seen_h:
            seen_h.add(round(ty, 3))
            my = ty * H
            msp.add_lwpolyline(
                [(bar, my - mb/2), (W - bar, my - mb/2),
                 (W - bar, my + mb/2), (bar, my + mb/2)],
                close=True, dxfattribs={'layer': L_FRAME})

        gi = bar + 4
        glx = bar + gi if x <= 0.001 else bar + mb/2 + 4
        gly = gy + (gi if y <= 0.001 else mb/2 + 4)
        grx = W - bar - (gi if x + w >= 0.999 else mb/2 + 4)
        gry = gy + gh - (gi if y + h >= 0.999 else mb/2 + 4)
        
        if grx > glx and gry > gly:
            msp.add_lwpolyline(
                [(glx, gly), (grx, gly), (grx, gry), (glx, gry)],
                close=True, dxfattribs={'layer': L_GLASS})
            _opener_symbol(msp, glx, gly, grx - glx, gry - gly, opening)


def _opener_symbol(msp, x, y, w, h, opening):
    if not opening or opening == 'Fixed':
        return
    d = {'layer': L_SWING, 'linetype': 'DASHED'}
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
    loops = _profile_pts(prof)
    plan_y1 = plan_y0 - dep

    _place_loops(msp, loops, 0,     plan_y1, rot_deg=0,   mirror_u=False)
    _place_loops(msp, loops, W,     plan_y1, rot_deg=0,   mirror_u=True)

    for y_edge in (plan_y0, plan_y1):
        msp.add_line((bar, y_edge), (W - bar, y_edge),
                     dxfattribs={'layer': L_SECT})

    mb = bar * 0.6
    seen = set()
    for (x, y, w, h, opening) in cells:
        rx = x + w
        if 0.001 < rx < 0.999 and round(rx, 3) not in seen:
            seen.add(round(rx, 3))
            mx = rx * W
            st_d = dep * 0.55
            for sx in (mx - mb/2 - 14, mx + mb/2):
                msp.add_lwpolyline(
                    [(sx, plan_y0), (sx + 14, plan_y0),
                     (sx + 14, plan_y0 - st_d), (sx, plan_y0 - st_d)],
                    close=True, dxfattribs={'layer': L_SASH})
            
            msp.add_lwpolyline(
                [(mx - mb/2, plan_y0), (mx + mb/2, plan_y0),
                 (mx + mb/2, plan_y1), (mx - mb/2, plan_y1)],
                close=True, dxfattribs={'layer': L_SECT})

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
    loops = _profile_pts(prof)
    _place_loops(msp, loops, sect_x, 0,   rot_deg=0)
    _place_loops(msp, loops, sect_x, H,   rot_deg=180, mirror_u=True)
    gx = sect_x + bar * 0.45
    for dx in (0, 24):
        msp.add_line((gx + dx, dep + 6), (gx + dx, H - dep - 6),
                     dxfattribs={'layer': L_GLASS})


def _pane_schedule(msp, cells, design, ox, top_y):
    col_w = [80, 240, 200, 220]
    row_h = 80
    headers = ['#', 'Opener', 'Glazing', 'Size']

    total_w = sum(col_w)
    n_rows  = len(cells) + 1
    total_h = n_rows * row_h

    msp.add_lwpolyline(
        [(ox, top_y - total_h), (ox + total_w, top_y - total_h),
         (ox + total_w, top_y), (ox, top_y)],
        close=True, dxfattribs={'layer': L_BORDER})

    cx = ox
    for cw in col_w[:-1]:
        cx += cw
        msp.add_line((cx, top_y - total_h), (cx, top_y),
                     dxfattribs={'layer': L_BORDER})

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

    for r_idx, (x, y, w, h, opening) in enumerate(cells):
        ry = top_y - (r_idx + 2) * row_h
        msp.add_line((ox, ry), (ox + total_w, ry),
                     dxfattribs={'layer': L_BORDER})
        glazing = 'DGU'
        if design and design.get('panes') and r_idx < len(design['panes']):
            dp = design['panes'][r_idx]
            glazing = dp.get('glazing') or dp.get('glazingType') or 'DGU'
        cx = ox
        vals = [str(r_idx + 1), opening or 'Fixed', glazing,
                f'{w*100:.0f}×{h*100:.0f}']
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

    dim = msp.add_aligned_dim(
        p1=(0, H), p2=(W, H), distance=140, dxfattribs=d, override=ov)
    dim.render()

    dim = msp.add_aligned_dim(
        p1=(sect_x + dep + 20, 0), p2=(sect_x + dep + 20, H),
        distance=110, dxfattribs=d, override=ov)
    dim.render()

    edges = sorted({round(c[0], 4) for c in cells} |
                   {round(c[0] + c[2], 4) for c in cells})
    if len(edges) > 2:
        for i in range(len(edges) - 1):
            x1, x2 = edges[i] * W, edges[i + 1] * W
            dim = msp.add_aligned_dim(
                p1=(x1, plan_y1), p2=(x2, plan_y1),
                distance=-110, dxfattribs=d, override=ov)
            dim.render()

    rows = sorted({round(c[1], 4) for c in cells} |
                  {round(c[1] + c[3], 4) for c in cells})
    if len(rows) > 2:
        for i in range(len(rows) - 1):
            y1, y2 = rows[i] * H, rows[i + 1] * H
            dim = msp.add_aligned_dim(
                p1=(0, y1), p2=(0, y2),
                distance=-130, dxfattribs=d, override=ov)
            dim.render()


# FIXED: ADD MISSING FUNCTIONS

def _add_hatching(msp, cells, W, H, bar):
    for (x, y, w, h, opening) in cells:
        gx = x * W + bar + 4
        gy = y * H + bar + 4
        gw = w * W - 8
        gh = h * H - 8
        
        if gw > 0 and gh > 0:
            hatch = msp.add_hatch()
            hatch.set_pattern_fill('SOLID')
            hatch.paths.add_polyline_path([
                (gx, gy),
                (gx + gw, gy),
                (gx + gw, gy + gh),
                (gx, gy + gh)
            ], is_closed=True)
            hatch.dxf.layer = L_HATCH
            hatch.dxf.color = 7


def _add_gasket_seals(msp, W, H, bar):
    offset = bar + 7
    x0, x1 = bar + offset, W - bar - offset
    y0, y1 = bar + offset, H - bar - offset
    
    if x1 > x0 and y1 > y0:
        msp.add_lwpolyline(
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            close=True,
            dxfattribs={'layer': L_SEAL, 'linetype': 'DASHED', 'color': 3}
        )


def _add_hardware_cutouts(msp, W, H, bar):
    positions = [(bar+30, bar+20), (bar+30, H-bar-20), (W-bar-30, bar+20), (W-bar-30, H-bar-20)]
    
    for (hx, hy) in positions:
        msp.add_lwpolyline(
            [(hx-10, hy-8), (hx+10, hy-8), (hx+10, hy+8), (hx-10, hy+8)],
            close=True,
            dxfattribs={'layer': L_HW, 'color': 1}
        )
        msp.add_circle((hx, hy-5), 2.5, dxfattribs={'layer': L_HW, 'color': 1})
        msp.add_circle((hx, hy+5), 2.5, dxfattribs={'layer': L_HW, 'color': 1})
    
    lock_x, lock_y = W - bar - 12, H * 0.75
    msp.add_lwpolyline(
        [(lock_x-6, lock_y-10), (lock_x+6, lock_y-10), (lock_x+6, lock_y+10), (lock_x-6, lock_y+10)],
        close=True,
        dxfattribs={'layer': L_HW, 'color': 1}
    )
    
    handle_x, handle_y = W - bar - 15, H / 2
    msp.add_circle((handle_x, handle_y), 4, dxfattribs={'layer': L_HW, 'color': 1})
    msp.add_circle((handle_x, handle_y-60), 4, dxfattribs={'layer': L_HW, 'color': 1})
    msp.add_line((handle_x, handle_y), (handle_x, handle_y-60),
                 dxfattribs={'layer': L_HW, 'linetype': 'DASHED', 'color': 1})


def _add_frame_centerlines(msp, W, H, bar):
    msp.add_line((0, H/2), (W, H/2),
                 dxfattribs={'layer': L_AXIS, 'linetype': 'CENTER', 'color': 6})
    msp.add_line((W/2, 0), (W/2, H),
                 dxfattribs={'layer': L_AXIS, 'linetype': 'CENTER', 'color': 6})


def _add_drainage_paths(msp, W, H, bar, prof):
    drain_width = prof.get('drainage_width', 8)
    drain_depth = prof.get('drainage_depth', 6)
    
    y_drain = bar + drain_depth
    msp.add_lwpolyline(
        [(bar, y_drain), (W-bar, y_drain), (W-bar, y_drain+drain_width), (bar, y_drain+drain_width)],
        close=True,
        dxfattribs={'layer': L_FRAME, 'color': 7}
    )
    
    weep_spacing = (W - 2*bar) / 5
    weep_x = bar + weep_spacing / 2
    
    for _ in range(4):
        msp.add_circle((weep_x, y_drain + drain_width/2), 3,
                      dxfattribs={'layer': L_FRAME, 'color': 7})
        weep_x += weep_spacing


def _place_loops(msp, loops, ox, oy, rot_deg=0, mirror_u=False, layer=L_SECT):
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


def _profile_pts(prof):
    if prof.get('loops'):
        allx = [float(x) for lp in prof['loops'] for x, y in lp]
        ally = [float(y) for lp in prof['loops'] for x, y in lp]
        if allx and ally:
            mx, my = min(allx), min(ally)
            return [[(float(x) - mx, float(y) - my) for x, y in lp]
                    for lp in prof['loops']]
    b, d = prof['bar'], prof['depth']
    min_wall = max(prof.get('wall', 4.0), 1.0)
    rw = min(prof['rebate_w'], b - min_wall) if 'rebate_w' in prof else 15
    rd = min(prof['rebate_d'], d - min_wall) if 'rebate_d' in prof else 20
    rw = max(rw, 0.0)
    rd = max(rd, 0.0)
    return [[(0, 0), (b, 0), (b, d - rd), (b - rw, d - rd),
             (b - rw, d), (0, d)]]


def _load_profile(tenant_id, material):
    prof = {'bar': 58.0, 'depth': 70.0, 'rebate_w': 15.0, 'rebate_d': 20.0,
            'name': 'DEFAULT', 'loops': None}
    if not tenant_id:
        return prof
    try:
        from app.models.cad_profile import CadProfile
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


def _load_design(window):
    try:
        return json.loads(getattr(window, 'design_json', '{}'))
    except:
        return {}


def _cells(panes, design):
    if not panes:
        return [(0, 0, 1, 1, 'Fixed')]
    
    cells = []
    for pane in panes:
        cells.append((
            float(pane.x_norm),
            float(pane.y_norm),
            float(pane.w_norm),
            float(pane.h_norm),
            pane.opener_type or 'Fixed'
        ))
    return cells