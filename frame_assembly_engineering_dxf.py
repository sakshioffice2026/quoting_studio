"""
Run from project root:
    python frame_assembly_engineering_dxf.py [width_mm] [height_mm]

Standalone check ONLY — NOT wired into frame_assembly.py / model3d.py /
model3d_freecad.py / engineering_dxf.py. Produces a 2D industry-style
engineering drawing sheet (elevation + detail cross-sections + title
block + border) for the threshold/head/jamb assembly, using this
repo's existing dxf_layers.py layer/dimstyle conventions (same
FRAME_GEOMETRY / WINDOW_CILL / DIMENSIONS / BORDER_LAYOUT layers used
by draw_threshold_section / draw_head_section / draw_jamb_section).

Layout (mm, modelspace 1:1):
  - ELEVATION: schematic frame outline (jambs + head + threshold,
    same nested-position logic as frame_assembly_test.py) with overall
    W x H dimensions.
  - DETAIL sections: real traced cross-sections of threshold, head,
    jamb placed below the elevation, each with its own dimensions
    (reusing draw_*_section as-is).
  - TITLE BLOCK + sheet border.

Output: output/frame_assembly_engineering.dxf
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ezdxf
from ezdxf.enums import TextEntityAlignment

from app.services.dxf_layers import setup_layers, setup_dimstyle, setup_text_styles
from app.services.threshold_geometry import get_bbox as threshold_bbox, draw_threshold_section
from app.services.head_geometry import get_head_bbox, draw_head_section
from app.services.jamb_geometry import get_jamb_bbox, draw_jamb_section

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

L_FRAME = "FRAME_GEOMETRY"
L_DIM = "DIMENSIONS"
L_BORDER = "BORDER_LAYOUT"

MARGIN = 150
TB_H = 200


def _add_text(msp, s, x, y, h, layer, halign=0):
    t = msp.add_text(s, dxfattribs={"layer": layer, "height": h})
    if halign == 1:
        t.set_placement((x, y), align=TextEntityAlignment.MIDDLE_CENTER)
    else:
        t.set_placement((x, y))
    return t


def _hline(msp, x0, x1, y, layer=L_BORDER):
    msp.add_line((x0, y), (x1, y), dxfattribs={"layer": layer})


def _vline(msp, x, y0, y1, layer=L_BORDER):
    msp.add_line((x, y0), (x, y1), dxfattribs={"layer": layer})


def _rect(msp, x0, y0, x1, y1, layer=L_FRAME):
    msp.add_lwpolyline(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
        close=True, dxfattribs={"layer": layer, "lineweight": 50},
    )


def _dim_x(msp, x0, x1, y):
    dim_attribs = {"layer": L_DIM}
    dim_override = {
        "dimtxt": 45, "dimasz": 32, "dimexe": 18, "dimexo": 12,
        "dimdec": 0, "dimclrt": 1, "dimclrd": 1, "dimclre": 1,
    }
    d = msp.add_aligned_dim(p1=(x0, y), p2=(x1, y), distance=0,
                             dxfattribs=dim_attribs, override=dim_override)
    d.render()


def _dim_y(msp, x, y0, y1):
    dim_attribs = {"layer": L_DIM}
    dim_override = {
        "dimtxt": 45, "dimasz": 32, "dimexe": 18, "dimexo": 12,
        "dimdec": 0, "dimclrt": 1, "dimclrd": 1, "dimclre": 1,
    }
    d = msp.add_aligned_dim(p1=(x, y0), p2=(x, y1), distance=0,
                             dxfattribs=dim_attribs, override=dim_override)
    d.render()


def _title_block(msp, ox, oy, sw, th, width_mm, height_mm):
    pts = [(ox, oy), (ox + sw, oy), (ox + sw, oy + th), (ox, oy + th)]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": L_BORDER})

    col1_w = sw * 0.28
    _vline(msp, ox + col1_w, oy, oy + th)
    _add_text(msp, "QUOTING STUDIO", ox + col1_w / 2, oy + th * 0.55,
              th * 0.20, L_DIM, halign=1)
    _add_text(msp, "FRAME ASSEMBLY", ox + col1_w / 2, oy + th * 0.25,
              th * 0.10, L_DIM, halign=1)

    col2_x0 = ox + col1_w
    col2_w = sw * 0.5
    _vline(msp, col2_x0 + col2_w, oy, oy + th)

    row_h = th / 3
    rows = [
        ("Drawing Title", "Threshold + Head + Jamb Assembly"),
        ("Size", f"{width_mm:.0f} x {height_mm:.0f} mm"),
        ("Members", "Threshold(bottom) / Head(top) / Jamb L+R"),
    ]
    for i, (k, v) in enumerate(rows):
        cy = oy + (2.5 - i) * row_h
        _add_text(msp, k, col2_x0 + 20, cy + row_h * 0.55, th * 0.10, L_DIM)
        _add_text(msp, v, col2_x0 + 20, cy + row_h * 0.20, th * 0.10, L_DIM)

    col3_x0 = col2_x0 + col2_w
    _add_text(msp, "DRAWING NUMBER", col3_x0 + 20, oy + th * 0.7,
              th * 0.10, L_DIM)
    _add_text(msp, "QS-ASSY-001", col3_x0 + 20, oy + th * 0.3,
              th * 0.18, L_DIM)


def build_drawing(width_mm: float, height_mm: float, dxf_path: str):
    doc = ezdxf.new("R2010", setup=True)
    setup_layers(doc)
    setup_text_styles(doc)
    setup_dimstyle(doc, bar_width=40.0)
    msp = doc.modelspace()

    tminx, tminy, tmaxx, tmaxy = threshold_bbox()
    threshold_y_extent = tmaxx - tminx

    hminx, hminy, hmaxx, hmaxy = get_head_bbox()
    head_y_extent = hmaxx - hminx

    jminx, jminy, jmaxx, jmaxy = get_jamb_bbox()
    jamb_x_width = jmaxx - jminx

    W, H = width_mm, height_mm

    # --- ELEVATION (schematic outline, matches 3D nesting) ---
    _rect(msp, 0, 0, jamb_x_width, H)
    _rect(msp, W - jamb_x_width, 0, W, H)
    _rect(msp, 0, 0, W, threshold_y_extent)
    _rect(msp, 0, H - head_y_extent, W, H)

    _dim_x(msp, 0, W, -80)
    _dim_y(msp, -80, 0, H)
    _add_text(msp, "ELEVATION", W / 2, H + 60, 40, L_DIM, halign=1)
    _add_text(msp, "SCALE 1:1", W / 2, H + 20, 25, L_DIM, halign=1)

    # --- DETAIL SECTIONS ---
    y1 = -400
    draw_threshold_section(msp, origin=(0, y1), layer=L_FRAME)
    _add_text(msp, "SECTION - THRESHOLD", 90, y1 - 60, 30, L_DIM, halign=1)

    y2 = y1 - 250
    draw_head_section(msp, origin=(0, y2), layer=L_FRAME)
    _add_text(msp, "SECTION - HEAD", 90, y2 - 60, 30, L_DIM, halign=1)

    y3 = y2 - 300
    draw_jamb_section(msp, origin=(0, y3), layer=L_FRAME)
    _add_text(msp, "SECTION - JAMB", 90, y3 - 60, 30, L_DIM, halign=1)

    # --- TITLE BLOCK + BORDER ---
    tb_top = y3 - 250
    tb_bot = tb_top - TB_H
    content_left = -300
    content_right = W + 300
    sheet_w = content_right - content_left
    _title_block(msp, content_left, tb_bot, sheet_w, TB_H, W, H)

    bx0 = content_left - MARGIN
    bx1 = content_right + MARGIN
    by0 = tb_bot - MARGIN
    by1 = H + 300 + MARGIN
    msp.add_lwpolyline(
        [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)],
        close=True, dxfattribs={"layer": L_BORDER},
    )
    m2 = 30
    msp.add_lwpolyline(
        [(bx0 + m2, by0 + m2), (bx1 - m2, by0 + m2),
         (bx1 - m2, by1 - m2), (bx0 + m2, by1 - m2)],
        close=True, dxfattribs={"layer": L_BORDER},
    )

    doc.saveas(dxf_path)
    return os.path.isfile(dxf_path)


def main():
    width_mm = float(sys.argv[1]) if len(sys.argv) > 1 else 1000.0
    height_mm = float(sys.argv[2]) if len(sys.argv) > 2 else 1200.0
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    dxf_path = os.path.join(OUTPUT_DIR, "frame_assembly_engineering.dxf")
    ok = build_drawing(width_mm, height_mm, dxf_path)
    print(f"Engineering DXF: {'OK -> ' + dxf_path if ok else 'FAILED'}")


if __name__ == "__main__":
    main()
