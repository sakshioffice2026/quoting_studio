from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PACKAGE_DIR / "output"
SECTIONS_DIR = PACKAGE_DIR.parent / "app" / "cad_sections" / "cad_sections"

# DXF units are unitless in the repo files; they are treated as millimetres.
UNIT_SCALE = 1.0

# Endpoint gap (mm) that is still treated as "connected" when chaining edges.
JOIN_TOLERANCE = 1e-3
MIN_SEGMENT_LENGTH = 1e-6
BULGE_LINE_THRESHOLD = 1e-9

# Sampling used only for independent area / bounding-box checks.
ARC_SAMPLES = 64
BBOX_SAMPLES = 720

# Validation tolerances.
VOLUME_REL_TOLERANCE = 2e-3
BBOX_TOLERANCE = 5e-3

DEFAULT_LENGTH = 1000.0

# Layers that hold drilling / annotation marks, never section outline.
IGNORED_LAYERS = {"DRILLS"}

# Loose open edge chains that cannot form a closed loop are dropped (with a
# warning) when the DXF already holds at least one closed outline.
DROP_STRAY_OPEN_CHAINS = True

# Block references (INSERT) are exploded up to this nesting depth.
MAX_BLOCK_DEPTH = 8

# Entities drawn in these linetypes are construction / break lines, not outline.
IGNORED_LINETYPES = {"DASHED", "DASHED2", "DASHEDX2", "HIDDEN", "HIDDEN2", "CENTER",
                     "CENTER2", "PHANTOM", "PHANTOM2", "DASHDOT", "DASHDOT2", "DOT", "DOT2"}

# ---------------------------------------------------------------------------
# Stage 2: mitred frame (Head, Sill, Jamb_Left, Jamb_Right)
# ---------------------------------------------------------------------------

# Outer frame size in mm (X = width, Y = height, Z = wall depth).
DEFAULT_FRAME_WIDTH = 1000.0
DEFAULT_FRAME_HEIGHT = 1200.0

# Section DXF used for each part. Both jambs share jamb.dxf.
FRAME_SECTION_FILES = {
    "Head": "head.dxf",
    "Sill": "sill.dxf",
    "Jamb_Left": "jamb.dxf",
    "Jamb_Right": "jamb.dxf",
}

# Profile convention for every section (after origin normalisation):
#   profile X = across (visible face width, measured inward from the outer edge)
#   profile Y = depth  (through the wall, along frame Z)
# Flip flags reverse a direction if a member looks mirrored when opened in CAD.
ACROSS_FLIP = {"Head": False, "Sill": False, "Jamb_Left": False, "Jamb_Right": False}
DEPTH_FLIP = {"Head": False, "Sill": False, "Jamb_Left": False, "Jamb_Right": False}

# How each section DXF is drawn, so every member ends up on one convention:
#   profile X = across (0 = outer edge of the frame)
#   profile Y = depth  (0 = front / exterior face, z = 0; grows toward the interior)
# Measured from the DXFs (width x height as drawn):
#   jamb.dxf          67 x 90   across on X, depth on Y   -> "as_drawn"
#   head.dxf          90 x 35   depth on X, across on Y   -> "swap"
#   sill.dxf         165 x 60   depth on X, across on Y   -> "swap"
#                              (slope falls toward z = 0, so water sheds outward)
#   meeting_stile.dxf 85 x 27   depth on X, across on Y   -> "swap"
# Modes: as_drawn, swap, rot90, rot180, rot270 (see profile_transform.orient_profile).
SECTION_ORIENTATION = {
    "Head": "swap",
    "Sill": "swap",
    "Jamb_Left": "as_drawn",
    "Jamb_Right": "as_drawn",
    "Mullion": "swap",
    "Transom": "as_drawn",
    "Bead": "as_drawn",
}

# Extra length (mm) added to each member before the mitre cut trims it back.
MITRE_OVERSIZE = 500.0

# Tolerance for the frame checks (volume of member vs. its mitre envelope).
FRAME_VOLUME_REL_TOLERANCE = 5e-3
FRAME_BBOX_TOLERANCE = 5e-3

FRAME_OUTPUT_NAME = "frame_{w}x{h}mm.step"

# ---------------------------------------------------------------------------
# Stage 3: full window (frame + mullion + transom + beads)
# ---------------------------------------------------------------------------

# Same origin convention as Stage 2 for every section:
#   profile X = across, profile Y = depth (frame +Z), extrusion = member length.
STAGE3_SECTION_FILES = {
    "Mullion": "meeting_stile.dxf",   # vertical, butt-jointed to head and sill
    "Transom": "glazing_bar.dxf",     # horizontal, butt-jointed to jambs and mullion
    "Bead": "bead.dxf",               # mitred ring inside every glazed opening
}

# Centre line of the mullion as a fraction of the outer frame width.
MULLION_X_FRACTION = 0.5
# Centre line of the transom as a fraction of the outer frame height.
TRANSOM_Y_FRACTION = 0.6

# Per-group flips and depth offset (mm, along frame +Z) for Stage 3 sections.
GROUP_ACROSS_FLIP = {"Mullion": False, "Transom": False, "Bead": False}
GROUP_DEPTH_FLIP = {"Mullion": False, "Transom": False, "Bead": False}
GROUP_Z_OFFSET = {"Mullion": 0.0, "Transom": 0.0, "Bead": 0.0}

# Allowed overlap between two members, relative to the smaller member volume.
WINDOW_OVERLAP_REL_TOLERANCE = 1e-3

WINDOW_OUTPUT_NAME = "window_{w}x{h}mm.step"

# ---------------------------------------------------------------------------
# Stage 3 (batch): every section DXF in the repo, one origin convention
# ---------------------------------------------------------------------------

IMPORT_SECTIONS_DIR = PACKAGE_DIR.parent / "import_data" / "Sections"

# Folders scanned (recursively) by generate_all_sections.
ALL_SECTION_DIRS = (SECTIONS_DIR, IMPORT_SECTIONS_DIR)

# Backup and temporary DXFs are never processed.
SECTION_SKIP_SUFFIXES = (".bak.dxf",)

SECTION_EXPORT_LENGTH = 1000.0
SECTIONS_OUTPUT_SUBDIR = "sections"
SECTIONS_REPORT_NAME = "sections_report.json"
