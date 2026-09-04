"""
Standalone utility — NOT wired into frame_assembly.py / model3d.py /
model3d_freecad.py / head_geometry.py.

Parses a head-profile DXF (verified tag-reader + bulge-arc expansion logic,
carried over from threshold_jamb_assembly_test.py) and writes the resulting
closed-loop points into CadProfile.geometry_json for role='head'. The
existing generic prepare_sections()/_section_rings() pipeline then renders
it for both straight and curved heads with zero changes to production code.

Usage (manual, explicit invocation only):
    from app.services.head_profile_dxf_import import import_head_profile
    import_head_profile(tenant_id=1, material="Aluminium", dxf_path=None,
                         commit=True)
"""
import json
import math
import os

_DEFAULT_DXF = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "cad_sections", "cad_sections", "head.dxf",
)


def parse_head_dxf(dxf_path: str = _DEFAULT_DXF) -> list:
    """
    Extract the first closed LWPOLYLINE from `dxf_path`, expand bulge arcs,
    and return normalised (x, y) points with origin at (0, 0). Returns []
    on any missing/empty/invalid/unparsable file.
    """
    if not dxf_path or not os.path.isfile(dxf_path):
        print(f"WARNING: head profile DXF not found: {dxf_path!r}")
        return []

    try:
        with open(dxf_path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError as exc:
        print(f"WARNING: could not read head profile DXF: {exc}")
        return []

    if not content.strip():
        print(f"WARNING: head profile DXF is empty: {dxf_path!r}")
        return []

    def _tags(text):
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        i = 0
        while i < len(lines) - 1:
            raw = lines[i].strip()
            val = lines[i + 1].strip()
            i += 2
            try:
                yield int(raw), val
            except ValueError:
                pass

    def _lwpolyline_pts(tag_list):
        coords, bulges, closed = [], {}, False
        idx = -1
        for code, val in tag_list:
            try:
                if code == 10:
                    idx += 1
                    coords.append([float(val), None])
                elif code == 20 and coords and coords[-1][1] is None:
                    coords[-1][1] = float(val)
                elif code == 42:
                    bulges[idx] = float(val)
                elif code == 70:
                    closed = bool(int(float(val)) & 1)
            except ValueError:
                pass
        pts = [(c[0], c[1]) for c in coords if c[1] is not None]
        if not pts:
            return [], False

        def _bulge_arc(p1, p2, b, n=12):
            x1, y1 = p1; x2, y2 = p2
            d = math.hypot(x2 - x1, y2 - y1)
            if d < 1e-10 or abs(b) < 1e-9:
                return [p2]
            theta = 4.0 * math.atan(abs(b))
            r = d / (2.0 * math.sin(theta / 2.0))
            dc = math.sqrt(max(0.0, r * r - (d / 2.0) ** 2))
            alpha = math.atan2(y2 - y1, x2 - x1)
            mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            sign = 1 if b > 0 else -1
            cx = mx + sign * dc * math.sin(alpha)
            cy = my - sign * dc * math.cos(alpha)
            sa = math.atan2(y1 - cy, x1 - cx)
            ea = math.atan2(y2 - cy, x2 - cx)
            if b > 0:
                if ea >= sa:
                    ea -= 2.0 * math.pi
            else:
                if ea <= sa:
                    ea += 2.0 * math.pi
            segs = max(n, int(abs(b) * 24))
            return [(cx + r * math.cos(sa + (ea - sa) * k / segs),
                     cy + r * math.sin(sa + (ea - sa) * k / segs))
                    for k in range(1, segs + 1)]

        expanded = [pts[0]]
        n = len(pts)
        last = n if closed else n - 1
        for i in range(last):
            b = bulges.get(i, 0.0)
            if abs(b) > 1e-9:
                expanded.extend(_bulge_arc(pts[i], pts[(i + 1) % n], b))
            else:
                expanded.append(pts[(i + 1) % n])
        return expanded, closed

    _EXCLUDED = ('dim', 'dimension', 'text', 'annot', 'note', 'centre',
                 'center', 'hatch', 'hidden', 'leader', 'title', 'border')

    current_type = None
    current_layer = None
    current_tags = []
    result_pts = []

    for code, val in _tags(content):
        if code == 0:
            if (current_type == "LWPOLYLINE"
                    and not any(s in (current_layer or "").lower() for s in _EXCLUDED)):
                pts, closed = _lwpolyline_pts(current_tags)
                if closed and len(pts) >= 3:
                    result_pts = pts
                    break
            current_type = val
            current_layer = None
            current_tags = []
        else:
            if code == 8:
                current_layer = val
            if current_type == "LWPOLYLINE":
                current_tags.append((code, val))

    if not result_pts:
        print(f"WARNING: no closed LWPOLYLINE found in head profile DXF: {dxf_path!r}")
        return []

    xs = [p[0] for p in result_pts]
    ys = [p[1] for p in result_pts]
    min_x, min_y = min(xs), min(ys)
    return [(round(x - min_x, 3), round(y - min_y, 3)) for x, y in result_pts]


def import_head_profile(tenant_id: int, material: str = "Aluminium",
                         dxf_path: str = _DEFAULT_DXF, commit: bool = True):
    """
    Parse `dxf_path` and write the resulting loop into geometry_json on the
    matching CadProfile (tenant_id, material, role='head', is_role_default).
    Falls back to any active role='head' row for the tenant if no
    role-default row exists. Returns the updated CadProfile, or None if the
    DXF was invalid/empty or no matching row was found.
    """
    return import_profile(tenant_id, role="head", material=material,
                           dxf_path=dxf_path, commit=commit)


def import_profile(tenant_id: int, role: str, material: str = "Aluminium",
                    dxf_path: str = _DEFAULT_DXF, commit: bool = True):
    """
    Role-agnostic version of import_head_profile(): parse `dxf_path` and
    write the resulting loop into geometry_json on the matching CadProfile
    (tenant_id, material, role, is_role_default). Falls back to any active
    row for that role if no role-default row exists. Returns the updated
    CadProfile, or None if the DXF was invalid/empty or no matching row
    was found.
    """
    pts = parse_head_dxf(dxf_path)
    if not pts:
        print(f"ABORT: no valid points parsed from {dxf_path!r} — "
              f"CadProfile (role={role!r}) not modified.")
        return None

    from ..models.cad_profile import CadProfile
    from ..extensions import db

    row = CadProfile.query.filter_by(
        tenant_id=tenant_id, material=material, role=role,
        is_role_default=True, is_active=True,
    ).first()
    if row is None:
        row = CadProfile.query.filter_by(
            tenant_id=tenant_id, role=role, is_active=True,
        ).first()
    if row is None:
        print(f"WARNING: no active CadProfile row with role={role!r} found "
              f"for tenant_id={tenant_id}, material={material!r}.")
        return None

    row.geometry_json = json.dumps([pts])
    row.vertex_count = len(pts)
    row.source_file = os.path.basename(dxf_path)

    if commit:
        db.session.commit()
    return row

