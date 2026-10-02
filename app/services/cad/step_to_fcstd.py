"""
app/services/cad/step_to_fcstd.py — FreeCAD .FCStd (From Sections), same layout
as the draft-views .FCStd produced by model3d_freecad.generate_3d_freecad(fmt='fcstd'):

    discrete Part::Feature members (F_head, F_cill, F_jambL, F_jambR, M_mull1, ...)
    + FrontGroup / SideSectionGroup / TopSectionGroup
      (Background + Profile + Hatch, Draft_*_View / _Profile / _Hatch labels)

Pipeline (same pattern as model3d_freecad.py):
    serialise -> JSON -> generated FreeCAD script -> freecadcmd -> read bytes

The member solids come from the step_generator package (section DXF profiles).
The ortho/section view code is NOT duplicated: the helper block and the views
block are taken verbatim from model3d_freecad._build_script(fmt='fcstd').

    data, filename = generate_fcstd_from_sections(window)
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile

from . import step_generator_service as sgs

logger = logging.getLogger(__name__)

FCSTD_TIMEOUT_SECONDS = 240

_HELPERS_END   = "# ── build each member"
_VIEWS_START   = "    # ── Native 2D orthographic + section views"
_VIEWS_END     = "    # ── TechDraw multi-view drawing page"


# ══════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY
# ══════════════════════════════════════════════════════════════════════

def generate_fcstd_from_sections(window, timeout: int = FCSTD_TIMEOUT_SECONDS) -> tuple[bytes, str]:
    """Returns (fcstd_bytes, filename). Raises StepGeneratorError on failure."""
    from .model3d_freecad import _find_freecad

    freecad = _find_freecad()
    if not freecad:
        raise sgs.StepGeneratorError(
            'FreeCAD not found — install FreeCAD or set the FREECAD_CMD environment variable.')

    # Section DXF -> cadquery solids -> named STEP (child process, own timeout)
    step_bytes, step_name = sgs.generate_step(window)

    # Same temp-dir policy as model3d_freecad.generate_3d_freecad
    tmp_dir = None
    for d in ('E:\\', 'D:\\', 'C:\\'):
        if os.path.isdir(d):
            candidate = os.path.join(d, 'qs_freecad_tmp')
            try:
                os.makedirs(candidate, exist_ok=True)
                testfile = os.path.join(candidate, '.wtest')
                with open(testfile, 'wb') as tf:
                    tf.write(b'x')
                os.remove(testfile)
                tmp_dir = candidate
                break
            except Exception:
                continue
    if tmp_dir is None:
        tmp_dir = tempfile.gettempdir()
    wid = getattr(window, 'id', 0)

    json_path   = os.path.join(tmp_dir, f'qs_secasm_{wid}.json')
    script_path = os.path.join(tmp_dir, f'qs_secfc_{wid}.py')
    step_path   = os.path.join(tmp_dir, f'qs_secin_{wid}.step')
    fcstd_path  = os.path.join(tmp_dir, f'qs_secmodel_{wid}.FCStd')

    try:
        with open(step_path, 'wb') as f:
            f.write(step_bytes)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(_serialise(window, step_path), f)
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write("# -*- coding: utf-8 -*-\n")
            f.write(_build_script(json_path, step_path, fcstd_path))

        env = os.environ.copy()
        env['LIBGL_ALWAYS_SOFTWARE'] = '1'
        try:
            r = subprocess.run([freecad, script_path],
                               capture_output=True, text=True,
                               timeout=timeout, env=env)
        except subprocess.TimeoutExpired as exc:
            raise sgs.StepGeneratorError(
                f'FCStd conversion timed out after {timeout}s') from exc

        logger.debug('FreeCAD stdout: %s', (r.stdout or '')[-4000:])
        if r.stderr:
            logger.warning('FreeCAD stderr: %s', r.stderr[-300:])

        if 'FREECAD_DONE' not in (r.stdout or ''):
            raise sgs.StepGeneratorError(
                'FreeCAD script did not complete. '
                f'stdout: {(r.stdout or "")[-2000:]}')

        data = _read(fcstd_path)
        if len(data) < 200:
            raise sgs.StepGeneratorError(
                'FreeCAD produced an empty .FCStd document '
                f'({len(data)} bytes). stdout tail:\n{(r.stdout or "")[-2000:]}')

        filename = step_name.rsplit('.', 1)[0] + '.FCStd'
        return data, filename

    finally:
        for p in (json_path, script_path, step_path, fcstd_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════
# SERIALISE → JSON
# ══════════════════════════════════════════════════════════════════════

def _serialise(window, step_path: str) -> dict:
    r, g, b = 0.42, 0.42, 0.44
    try:
        h = (getattr(window, 'frame_colour_hex', None) or '#6a6a6c').lstrip('#')
        r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    except Exception:
        pass

    kind, width, height = sgs.resolve_kind(window)

    # Door STEP is exported Z_UP (X = width, Z = height, depth toward -Y).
    # The draft-views layout needs X = width, Y = height, Z = depth.
    zup = False
    if kind == 'door':
        try:
            from step_generator import door_config
            zup = (door_config.EXPORT_ORIENTATION == 'Z_UP')
        except Exception:
            zup = True

    return {
        'kind':      kind,
        'zup':       zup,
        'width':     float(width),
        'height':    float(height),
        'frame_rgb': [r, g, b],
        'members':   [],      # derived inside FreeCAD from the imported section solids
        'glass':     [],
        'step_path': step_path.replace('\\', '/'),
    }


# ══════════════════════════════════════════════════════════════════════
# FREECAD SCRIPT
# ══════════════════════════════════════════════════════════════════════

# Section-part name (step_generator) -> member id used by the draft-views FCStd.
_BODY = r'''
# ══════════════════════════════════════════════════════════════════════
# SECTION PARTS (step_generator STEP) -> discrete Part::Feature members
# ══════════════════════════════════════════════════════════════════════
import Import, re

_ID_MAP = {
    "head": "F_head", "sill": "F_cill", "cill": "F_cill",
    "jamb_left": "F_jambL", "jamb_right": "F_jambR",
    "jambl": "F_jambL", "jambr": "F_jambR",
}
_counters = {}
_bead_groups = {}
_SIDE_MAP = {"bottom": "bot", "top": "top", "left": "L", "right": "R"}

def _member_id(label):
    key = re.sub(r"[^a-z0-9_]+", "", (label or "").lower())
    if key in _ID_MAP:
        return _ID_MAP[key]
    if key.startswith("mullion"):
        _counters["M"] = _counters.get("M", 0) + 1
        return "M_mull%d" % _counters["M"]
    if key.startswith("transom"):
        _counters["T"] = _counters.get("T", 0) + 1
        return "T_trans%d" % _counters["T"]
    if key.startswith("bead"):
        # Bead_<Row>_<Col>_<Side>  ->  B<n>_<top|bot|L|R>, n per glazed opening
        _p = key.split("_")
        _side = _SIDE_MAP.get(_p[-1], _p[-1])
        _grp = "_".join(_p[1:-1])
        if _grp not in _bead_groups:
            _bead_groups[_grp] = len(_bead_groups) + 1
        return "B%d_%s" % (_bead_groups[_grp], _side)
    clean = re.sub(r"[^A-Za-z0-9_]+", "_", label or "Part").strip("_") or "Part"
    _counters[clean] = _counters.get(clean, 0) + 1
    return clean if _counters[clean] == 1 else "%s%d" % (clean, _counters[clean] - 1)

Import.insert(data["step_path"], doc.Name)
doc.recompute()

_imported = []
_seen = set()
for _o in list(doc.Objects):
    _shp = getattr(_o, "Shape", None)
    if _shp is None or _shp.isNull() or len(_shp.Solids) != 1:
        continue
    _sc = _shp.copy()
    try:
        _sc.Placement = _o.getGlobalPlacement()
    except Exception:
        pass
    if data.get("zup"):
        # (x, y, z) -> (x, z, -y): Z-up door back to build coords (Y = height, Z = depth)
        _sc.rotate(V(0, 0, 0), V(1, 0, 0), -90.0)
    _lbl = _o.Label or _o.Name
    _sig = (_lbl, round(_sc.Volume, 1), round(_sc.BoundBox.XMin, 1), round(_sc.BoundBox.YMin, 1))
    if _sig in _seen:
        continue
    _seen.add(_sig)
    _imported.append((_lbl, _sc))

# stable order: frame first, then mullion/transom, then beads
_rank = lambda t: (0 if t[0].lower().startswith(("head", "sill", "jamb")) else
                   1 if t[0].lower().startswith(("mullion", "transom")) else 2, t[0])
_imported.sort(key=_rank)

# drop everything the STEP import created; members are rebuilt as flat features
for _o in list(doc.Objects):
    try:
        doc.removeObject(_o.Name)
    except Exception:
        pass
doc.recompute()

if not _imported:
    raise RuntimeError("STEP import produced no solid parts")

# centre the model on the origin (X = width, Y = height, Z = depth) like the
# draft-views document: member coordinates are window coords minus (cx, cy).
_xmin = min(s.BoundBox.XMin for _, s in _imported)
_xmax = max(s.BoundBox.XMax for _, s in _imported)
_ymin = min(s.BoundBox.YMin for _, s in _imported)
_ymax = max(s.BoundBox.YMax for _, s in _imported)
_shift = V(-(_xmin + _xmax) / 2.0, -(_ymin + _ymax) / 2.0, 0.0)

data["members"] = []
for _label, _s in _imported:
    _s.translate(_shift)
    _mid = _member_id(_label)
    _feat = doc.addObject("Part::Feature", _mid)
    _feat.Label = _mid
    _feat.Shape = _s
    _feat.Visibility = False
    _bb = _s.BoundBox
    _dx, _dy = _bb.XMax - _bb.XMin, _bb.YMax - _bb.YMin
    _orient = "horizontal" if _dx >= _dy else "vertical"
    _xc, _yc = (_bb.XMin + _bb.XMax) / 2.0 + cx, (_bb.YMin + _bb.YMax) / 2.0 + cy
    if _orient == "horizontal":
        _x1, _x2, _y1, _y2 = _bb.XMin + cx, _bb.XMax + cx, _yc, _yc
        _bar = _dy
    else:
        _x1, _x2, _y1, _y2 = _xc, _xc, _bb.YMin + cy, _bb.YMax + cy
        _bar = _dx
    _member_orientation[_mid] = _orient
    data["members"].append({
        "id": _mid, "role": _label, "orientation": _orient,
        "x1": _x1, "y1": _y1, "x2": _x2, "y2": _y2,
        "bar": float(_bar), "depth": float(_bb.ZMax - _bb.ZMin),
        "length": float(max(_dx, _dy)),
    })
    print(f"  {_mid} ok  (section part={_label} orient={_orient})", flush=True)

# ── glass: one pane per bead-ringed opening (Glass0, Glass1, ...) ──────
_gboxes = {}
for _m, (_label, _s) in zip(data["members"], _imported):
    _mid = _m["id"]
    if _mid.startswith("B") and "_" in _mid and _mid[1:2].isdigit():
        _n = int(_mid[1:_mid.index("_")])
        _bb = _s.BoundBox
        _g = _gboxes.setdefault(_n, [1e9, 1e9, -1e9, -1e9, 1e9, -1e9, 1e9])
        _g[0] = min(_g[0], _bb.XMin); _g[1] = min(_g[1], _bb.YMin)
        _g[2] = max(_g[2], _bb.XMax); _g[3] = max(_g[3], _bb.YMax)
        _g[4] = min(_g[4], _bb.ZMin); _g[5] = max(_g[5], _bb.ZMax)
        _g[6] = min(_g[6], min(_bb.XMax - _bb.XMin, _bb.YMax - _bb.YMin))

for _n in sorted(_gboxes):
    _x0, _y0, _x1, _y1, _z0, _z1, _bw = _gboxes[_n]
    _th = 8.0
    _gw, _gh = (_x1 - _x0) - 2 * _bw, (_y1 - _y0) - 2 * _bw
    if _gw <= 1.0 or _gh <= 1.0:
        continue
    _zc = (_z0 + _z1) / 2.0
    _gbox = Part.makeBox(_gw, _gh, _th, V(_x0 + _bw, _y0 + _bw, _zc - _th / 2.0))
    _gname = "Glass%d" % (_n - 1)
    _gf = doc.addObject("Part::Feature", _gname)
    _gf.Label = _gname
    _gf.Shape = _gbox
    _gf.Visibility = False
    print(f"  {_gname} ok", flush=True)

doc.recompute()
print(f"DIAG: {len(data['members'])} section members", flush=True)

# ══════════════════════════════════════════════════════════════════════
# FRONT / SIDE-SECTION / TOP-SECTION (verbatim from model3d_freecad)
# ══════════════════════════════════════════════════════════════════════
if not data["members"]:
    raise RuntimeError("no members built")
else:
'''

_TAIL = '''
App.closeDocument(doc.Name)
print("FREECAD_DONE", flush=True)
'''


def _build_script(json_path: str, step_path: str, fcstd_path: str) -> str:
    from .model3d_freecad import _build_script as _draft_script

    base = _draft_script(json_path, step_path,
                         step_path + '.stl', step_path + '.glass.stl',
                         fcstd_path, fcstd_path + '.td', 'fcstd')

    i_help = base.find(_HELPERS_END)
    i_vs   = base.find(_VIEWS_START)
    i_ve   = base.find(_VIEWS_END)
    if i_help < 0 or i_vs < 0 or i_ve < 0 or not (i_help < i_vs < i_ve):
        raise sgs.StepGeneratorError(
            'model3d_freecad script layout changed — cannot reuse the ortho-view blocks.')

    helpers = base[:i_help]          # imports, data, doc, helpers, build_ortho_view
    views   = base[i_vs:i_ve]        # Front / SideSection / TopSection + saveAs
    return helpers + _BODY + views + _TAIL


# ══════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════

def _read(path: str) -> bytes:
    if not os.path.exists(path) or os.path.getsize(path) < 100:
        raise sgs.StepGeneratorError(f'FreeCAD output missing or empty: {path}')
    with open(path, 'rb') as f:
        return f.read()
