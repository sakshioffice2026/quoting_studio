"""Door assembly settings: L16 double door (hinge between doors)."""
from . import config

DEFAULT_DOOR_WIDTH = 1800.0
DEFAULT_DOOR_HEIGHT = 2100.0

DOOR_OUTPUT_NAME = "door_L16_double_{w}x{h}mm.step"

_APP = config.SECTIONS_DIR
_IMP = config.IMPORT_SECTIONS_DIR

# Role -> section DXF. Change a path here to swap a section.
L16_DOUBLE_SECTIONS = {
    "Jamb": _APP / "jamb.dxf",
    "Head": _IMP / "upper base of frame.dxf",
    "Sill": _IMP / "lower base of door frame.dxf",
    "Hinge": _IMP / "hinge between doors(specific for d 19 door).dxf",
    "Base_Rail": _IMP / "lower base of door frame (part 2` specific to L16 door).dxf",
    "Base_Support": _IMP / "lower base of door frame (part 1` specific to L16 door).dxf",
    "Bead": _APP / "bead.dxf",
}

# In-plane profile rotation (counter-clockwise degrees: 0, 90, 180, 270) per role.
# Use it when a section is drawn with across and depth swapped in its DXF.
# The sill is drawn 165 wide x 60 high: it must be 60 across (up) and 165 deep.
PROFILE_ROTATE_DEG = {
    "Sill": 270,
}

# STEP export orientation.
#   "Z_UP"     door stands upright: X = width, Y = depth, Z = height (CAD default)
#   "AS_BUILT" build coordinates: X = width, Y = height, Z = depth
EXPORT_ORIENTATION = "Z_UP"

# Centre line of the hinge member as a fraction of the outer door width.
HINGE_X_FRACTION = 0.5

# Allowed overlap between two members, relative to the smaller member volume.
DOOR_OVERLAP_REL_TOLERANCE = config.WINDOW_OVERLAP_REL_TOLERANCE
