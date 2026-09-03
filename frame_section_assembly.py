"""
Run from project root:
    python frame_section_assembly.py [width_mm] [height_mm]

Standalone 2D DXF assembly of threshold, head and jamb section profiles.
NOT wired into frame_assembly.py / model3d.py / model3d_freecad.py.

Layout — 2D elevation/section view of the assembled frame:

    Threshold : natural orientation at (0, 0),         profile 165 x 60 mm
    Head      : natural orientation at (0, H),         profile  90 x 35 mm
    Left jamb : rotated 90° — across(67) runs +Y,     depth(90) runs -X
    Right jamb: rotated 90° — across(67) runs +Y,     depth(90) runs +X from W

    Frame inner opening outlined with dashed line.
    Overall frame W x H dimensions annotated.

Output: output/frame_section_assembly.dxf
"""
import sys
import os
import importlib.util

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

DIM_OVERRIDE = {
    "dimtxt": 4.5, "dimasz": 3.2, "dimexe": 1.8, "dimexo": 1.2,
    "dimdec": 1,   "dimclrt": 1,  "dimclrd": 1,  "dimclre": 1,
}
DIM_ATTRIBS = {"layer": "DIMENSIONS"}


def _load(rel):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)
    spec = importlib.util.spec_from_file_location("_mod", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _label(msp, text, x, y, height=5.0):
    msp.add_text(
        text,
        dxfattribs={"layer": "DIMENSIONS", "height": height},
    ).set_placement((x, y))


def _dim_h(msp, x0, x1, y):
    d = msp.add_aligned_dim(
        p1=(x0, y), p2=(x1, y),
        distance=0, dxfattribs=DIM_ATTRIBS, override=DIM_OVERRIDE,
    )
    d.render()


def _dim_v(msp, x, y0, y1):
    d = msp.add_aligned_dim(
        p1=(x, y0), p2=(x, y1),
        distance=0, dxfattribs=DIM_ATTRIBS, override=DIM_OVERRIDE,
    )
    d.render()


def draw_assembly(msp, W=1000.0, H=1200.0):
    tmod = _load("app/services/threshold_geometry.py")
    hmod = _load("app/services/head_geometry.py")
    jmod = _load("app/services/jamb_geometry.py")

    # ── THRESHOLD (bottom, natural orientation) ──────────────────────
    t_pts = tmod.get_profile_points_normalised()
    tb = tmod.get_bbox()
    tW, tH = tb[2] - tb[0], tb[3] - tb[1]
    msp.add_lwpolyline(
        t_pts, close=True,
        dxfattribs={"layer": "WINDOW_CILL", "lineweight": 50},
    )
    _label(msp, f"THRESHOLD  {tW:.0f} x {tH:.0f} mm", 0, -14)
    _dim_h(msp, 0, tW, -20)
    _dim_v(msp, -14, 0, tH)

    # ── HEAD (top, natural orientation) ──────────────────────────────
    h_pts = hmod.get_profile_points_normalised()
    hb = hmod.get_bbox()
    hW, hH = hb[2] - hb[0], hb[3] - hb[1]
    h_poly = [(x, y + H) for (x, y) in h_pts]
    msp.add_lwpolyline(
        h_poly, close=True,
        dxfattribs={"layer": "WINDOW_CILL", "lineweight": 50},
    )
    _label(msp, f"HEAD  {hW:.0f} x {hH:.0f} mm", 0, H + hH + 6)
    _dim_h(msp, 0, hW, H + hH + 14)

    # ── JAMB sections (rotated 90° for vertical orientation) ─────────
    j_pts = jmod.get_profile_points_normalised()
    jb = jmod.get_bbox()
    jW, jD = jb[2] - jb[0], jb[3] - jb[1]   # jW=67 (across), jD=90 (depth)

    # Left jamb: (x, y) -> (-y, x)
    #   across (x=0..67) maps to world Y (vertical, 0..67)
    #   depth  (y=0..90) maps to world X left (-90..0)
    left_poly = [(-y, x) for (x, y) in j_pts]
    msp.add_lwpolyline(
        left_poly, close=True,
        dxfattribs={"layer": "FRAME_GEOMETRY", "lineweight": 50},
    )
    _label(msp, f"JAMB (L)  {jW:.0f} x {jD:.0f} mm", -jD - 2, jW + 4)
    _dim_h(msp, -jD, 0, -20)

    # Right jamb: (x, y) -> (W + y, x)
    #   depth (y=0..90) maps to world X right (W..W+90)
    right_poly = [(W + y, x) for (x, y) in j_pts]
    msp.add_lwpolyline(
        right_poly, close=True,
        dxfattribs={"layer": "FRAME_GEOMETRY", "lineweight": 50},
    )
    _label(msp, f"JAMB (R)  {jW:.0f} x {jD:.0f} mm", W + 2, jW + 4)
    _dim_h(msp, W, W + jD, -20)

    # ── Frame inner opening outline (schematic dashed) ────────────────
    msp.add_lwpolyline(
        [(0, 0), (W, 0), (W, H), (0, H)], close=True,
        dxfattribs={"layer": "SWING_LINES", "lineweight": 18},
    )

    # ── Overall frame W x H ───────────────────────────────────────────
    _dim_h(msp, 0, W, -32)
    _dim_v(msp, -28, 0, H)
    _label(msp, f"FRAME  {W:.0f} x {H:.0f} mm", W / 2 - 30, -44)


def main():
    W = float(sys.argv[1]) if len(sys.argv) > 1 else 1000.0
    H = float(sys.argv[2]) if len(sys.argv) > 2 else 1200.0
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    import ezdxf
    dl = _load("app/services/dxf_layers.py")

    doc = ezdxf.new("R2010", setup=True)
    dl.setup_layers(doc)
    dl.setup_dimstyle(doc, bar_width=40.0)
    msp = doc.modelspace()

    draw_assembly(msp, W, H)

    out = os.path.join(OUTPUT_DIR, "frame_section_assembly.dxf")
    doc.saveas(out)
    print(f"Assembly DXF: {out}")
    print(f"  Frame:     {W:.0f} x {H:.0f} mm")
    print(f"  Threshold: 165 x 60 mm  at Y=0  (natural)")
    print(f"  Head:       90 x 35 mm  at Y={H:.0f}  (natural)")
    print(f"  Jamb:       67 x 90 mm  left/right  (rotated 90 deg)")


if __name__ == "__main__":
    main()
