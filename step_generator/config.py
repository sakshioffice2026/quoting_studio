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
