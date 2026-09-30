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

# Extra length (mm) added to each member before the mitre cut trims it back.
MITRE_OVERSIZE = 500.0

# Tolerance for the frame checks (volume of member vs. its mitre envelope).
FRAME_VOLUME_REL_TOLERANCE = 5e-3
FRAME_BBOX_TOLERANCE = 5e-3

FRAME_OUTPUT_NAME = "frame_{w}x{h}mm.step"
