"""Engineering DXF export compatibility fixes."""
from . import engineering_dxf as _base

_ORIGINAL_PROFILE_PTS = _base._profile_pts


def _cells(panes, design):
    out = []
    source = design.get("panes") if isinstance(design, dict) else None
    if source:
        for p in source:
            try:
                x, y = float(p.get("x", 0)), float(p.get("y", 0))
                w, h = float(p.get("w", 1)), float(p.get("h", 1))
            except (TypeError, ValueError):
                continue
            out.append((x, 1.0-y-h, w, h,
                        p.get("opening") or p.get("opener") or "Fixed"))
    else:
        for p in panes:
            out.append((float(getattr(p, "x_norm", 0)),
                        1.0-float(getattr(p, "y_norm", 0))-float(getattr(p, "h_norm", 1)),
                        float(getattr(p, "w_norm", 1)), float(getattr(p, "h_norm", 1)),
                        getattr(p, "opening_type", None) or getattr(p, "opener_type", None) or "Fixed"))
    cleaned = []
    for x, y, w, h, opening in out:
        x, y = max(0.0, min(1.0, x)), max(0.0, min(1.0, y))
        w, h = max(0.0, min(1.0-x, w)), max(0.0, min(1.0-y, h))
        if w > 0 and h > 0:
            cleaned.append((x, y, w, h, opening))
    return cleaned or [(0.0, 0.0, 1.0, 1.0, "Fixed")]


def _profile_pts(prof):
    loops = prof.get("loops")
    if loops:
        pts = [(float(x), float(y)) for loop in loops for x, y in loop]
        if pts:
            min_x, max_x = min(x for x, _ in pts), max(x for x, _ in pts)
            min_y, max_y = min(y for _, y in pts), max(y for _, y in pts)
            span_x, span_y = max_x-min_x, max_y-min_y
            if span_x > 1e-9 and span_y > 1e-9:
                sx = float(prof.get("bar", 58.0)) / span_x
                sy = float(prof.get("depth", 70.0)) / span_y
                return [[((float(x)-min_x)*sx, (float(y)-min_y)*sy)
                         for x, y in loop] for loop in loops]
    return _ORIGINAL_PROFILE_PTS({**prof, "loops": None})


def _pane_schedule(msp, cells, design, ox, top_y, W, H):
    col_w, row_h = [80, 240, 220, 220], 80
    headers = ["#", "Opener", "Glazing", "Size (mm)"]
    total_w, total_h = sum(col_w), (len(cells)+1)*row_h
    msp.add_lwpolyline([(ox, top_y-total_h), (ox+total_w, top_y-total_h),
                        (ox+total_w, top_y), (ox, top_y)], close=True,
                       dxfattribs={"layer": _base.L_BORDER})
    cx = ox
    for cw in col_w[:-1]:
        cx += cw
        msp.add_line((cx, top_y-total_h), (cx, top_y), dxfattribs={"layer": _base.L_BORDER})
    _base._add_text(msp, "PANE SCHEDULE", ox+total_w/2, top_y+40, 35, _base.L_ANNOT, halign=1)
    for row in range(1, len(cells)+1):
        y = top_y-row*row_h
        msp.add_line((ox, y), (ox+total_w, y), dxfattribs={"layer": _base.L_BORDER})
    cx = ox
    for i, header in enumerate(headers):
        _base._add_text(msp, header, cx+col_w[i]/2, top_y-row_h*.45, 24, _base.L_ANNOT, halign=1)
        cx += col_w[i]
    panes = design.get("panes", []) if isinstance(design, dict) else []
    for i, (x, y, w, h, opening) in enumerate(cells):
        glazing = "DGU"
        if i < len(panes):
            glazing = panes[i].get("glazing") or panes[i].get("glazingType") or glazing
        values = [str(i+1), opening or "Fixed", glazing, f"{w*W:.0f} x {h*H:.0f}"]
        cy, cx = top_y-(i+1.65)*row_h, ox
        for j, value in enumerate(values):
            _base._add_text(msp, value, cx+col_w[j]/2, cy, 22, _base.L_ANNOT, halign=1)
            cx += col_w[j]


def generate_engineering_dxf(window, panes, tenant_id=None):
    original_cells = _base._cells
    original_profile_pts = _base._profile_pts
    original_schedule = _base._pane_schedule
    W, H = float(window.width_mm), float(window.height_mm)
    _base._cells = _cells
    _base._profile_pts = _profile_pts
    _base._pane_schedule = lambda msp, cells, design, ox, top_y: _pane_schedule(msp, cells, design, ox, top_y, W, H)
    try:
        return _base.generate_engineering_dxf(window, panes, tenant_id=tenant_id)
    finally:
        _base._cells = original_cells
        _base._profile_pts = original_profile_pts
        _base._pane_schedule = original_schedule
