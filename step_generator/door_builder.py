"""Door assembly: L16 double door with a hinge member between the two leaves.

Frame coordinates (mm): X = width, Y = height, Z = wall depth (0 = front face).
One convention for every section: profile X = across, profile Y = depth (+Z),
extrusion = member length.

Parts:
    Head, Sill, Jamb_Left, Jamb_Right   mitred frame
    Hinge_Center                        vertical, square-cut between sill and head
    Base_Rail_<Left|Right>              horizontal, square-cut between jamb and hinge
    Base_Support_<Left|Right>           horizontal, stacked on the base rail
    Bead_<Left|Right>_<Side>            4 mitred beads inside each glazed opening
"""
from pathlib import Path

from . import config, door_config, frame_builder
from .dxf_profile import ProfileError, load_profile
from .frame_builder import build_frame
from .profile_transform import rotate_profile
from .window_builder import (
    WindowBuildError,
    _add_bead_ring,
    _finish,
    _member,
    _register,
)


class DoorBuildError(WindowBuildError):
    pass


_MISSING = object()


def _load(path, report, role=None):
    path = Path(path)
    if not path.is_file():
        raise DoorBuildError(f"Section DXF not found: {path}", report)
    try:
        profile = load_profile(path, normalize_origin=True)
    except ProfileError as exc:
        raise DoorBuildError(f"{path.name}: {exc}", report)
    for warning in profile.warnings:
        report["warnings"].append(f"{path.name}: {warning}")
    return rotate_profile(profile, door_config.PROFILE_ROTATE_DEG.get(role, 0))


def _build_frame_from(files, width, height):
    """Run the Stage 2 frame builder with the door's own section files."""
    rotations = {
        str(files[role]): door_config.PROFILE_ROTATE_DEG.get(role, 0)
        for role in ("Head", "Sill", "Jamb")
    }
    original_loader = frame_builder.load_profile

    def rotating_loader(path, *args, **kwargs):
        profile = original_loader(path, *args, **kwargs)
        return rotate_profile(profile, rotations.get(str(path), 0))

    # The door sill is already turned into place by rotating_loader, so the
    # window sill "swap" orientation must not be applied to it a second time.
    sill_key = Path(str(files["Sill"])).name.lower()
    saved_by_file = getattr(config, "SECTION_ORIENTATION_BY_FILE", _MISSING)

    saved = dict(config.FRAME_SECTION_FILES)
    try:
        config.FRAME_SECTION_FILES.update({
            "Head": str(files["Head"]),
            "Sill": str(files["Sill"]),
            "Jamb_Left": str(files["Jamb"]),
            "Jamb_Right": str(files["Jamb"]),
        })
        config.SECTION_ORIENTATION_BY_FILE = {sill_key: "as_drawn"}
        frame_builder.load_profile = rotating_loader
        return build_frame(width, height)
    finally:
        frame_builder.load_profile = original_loader
        config.FRAME_SECTION_FILES.clear()
        config.FRAME_SECTION_FILES.update(saved)
        if saved_by_file is _MISSING:
            del config.SECTION_ORIENTATION_BY_FILE
        else:
            config.SECTION_ORIENTATION_BY_FILE = saved_by_file


def build_door(width=door_config.DEFAULT_DOOR_WIDTH, height=door_config.DEFAULT_DOOR_HEIGHT,
               sections=None):
    """Return (parts, report). parts maps part name -> cadquery Solid (ordered)."""
    files = dict(door_config.L16_DOUBLE_SECTIONS)
    if sections:
        files.update(sections)

    frame_parts, report = _build_frame_from(files, width, height)
    parts = {}
    for name, solid in frame_parts.items():
        parts[name] = solid
        report["parts"][name]["group"] = "Frame"
    report["stage"] = "door_L16_double"

    a = report["across"]
    aj_l, aj_r = a["Jamb_Left"], a["Jamb_Right"]
    a_h, a_s = a["Head"], a["Sill"]

    hinge = _load(files["Hinge"], report, "Hinge")
    rail = _load(files["Base_Rail"], report, "Base_Rail")
    support = _load(files["Base_Support"], report, "Base_Support")
    bead = _load(files["Bead"], report, "Bead")

    hw, b = hinge.width, bead.width
    cx = width * door_config.HINGE_X_FRACTION
    x_left, x_right = cx - hw / 2.0, cx + hw / 2.0
    y_lo, y_hi = a_s, height - a_h

    rail_y0 = y_lo
    rail_y1 = rail_y0 + rail.width
    sup_y0 = rail_y1
    sup_y1 = sup_y0 + support.width

    report["layout"] = {
        "hinge_x": [x_left, x_right],
        "base_rail_y": [rail_y0, rail_y1],
        "base_support_y": [sup_y0, sup_y1],
        "glazing_y": [sup_y1, y_hi],
        "bead_across": b,
    }

    columns = (("Left", aj_l, x_left), ("Right", x_right, width - aj_r))
    for col_name, xa, xb in columns:
        if xb - xa <= 2.0 * b or y_hi - sup_y1 <= 2.0 * b:
            raise DoorBuildError(
                f"Glazed opening {col_name} is {xb - xa:.1f} x {y_hi - sup_y1:.1f} mm; "
                f"it must exceed twice the bead width ({2.0 * b:.1f} mm) in both directions",
                report)

    depths = list(report["depth"].values())
    depths += [hinge.height, rail.height, support.height, bead.height]
    z_top = max(depths) + 2.0

    # Hinge: across +X, runs downward from the head inner face to the sill inner face.
    shape = _member(
        hinge, "Hinge", "Hinge_Center", (x_left, y_hi, 0.0),
        (1.0, 0.0, 0.0), (0.0, -1.0, 0.0), y_hi - y_lo, report,
    )
    solid = _finish(shape, "Hinge_Center", width, height, report)
    _register(parts, report, "Hinge_Center", "Hinge", Path(files["Hinge"]).name, solid, hinge)

    # Base rail and base support: across +Y, run along +X between jamb and hinge.
    for col_name, xa, xb in columns:
        for prefix, prof, group, y0 in (
            ("Base_Rail", rail, "Base_Rail", rail_y0),
            ("Base_Support", support, "Base_Support", sup_y0),
        ):
            name = f"{prefix}_{col_name}"
            shape = _member(
                prof, group, name, (xa, y0, 0.0),
                (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), xb - xa, report,
            )
            solid = _finish(shape, name, width, height, report)
            _register(parts, report, name, group, Path(files[group]).name, solid, prof)

    # Beads: one mitred ring per glazed opening, above the base support.
    for col_name, xa, xb in columns:
        _add_bead_ring(
            parts, report, bead, f"Bead_{col_name}",
            (xa, sup_y1, xb, y_hi), z_top, width, height,
        )

    return parts, report