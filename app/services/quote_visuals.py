import base64
import io
import os

from flask import current_app
from PIL import Image

from ..models import Visualisation, Window

MAX_SIDE = 1400
JPEG_QUALITY = 85
MAX_VISUALS = 6


def _safe_path(relative_path):
    if not relative_path:
        return None
    base = os.path.realpath(current_app.config['UPLOAD_FOLDER'])
    full = os.path.realpath(os.path.join(base, relative_path))
    if not full.startswith(base + os.sep) or not os.path.isfile(full):
        return None
    return full


def _jpeg_bytes(path):
    try:
        with Image.open(path) as img:
            img = img.convert('RGB')
            scale = min(1.0, MAX_SIDE / float(max(img.size)))
            if scale < 1.0:
                img = img.resize(
                    (max(1, round(img.size[0] * scale)), max(1, round(img.size[1] * scale))),
                    Image.Resampling.LANCZOS,
                )
            buf = io.BytesIO()
            img.save(buf, 'JPEG', quality=JPEG_QUALITY, optimize=True)
            return buf.getvalue()
    except (OSError, ValueError):
        return None


def _data_uri(data):
    return 'data:image/jpeg;base64,' + base64.b64encode(data).decode('ascii')


def collect(quotation):
    visuals = []
    seen = set()

    for item in (quotation.line_items or []):
        if len(visuals) >= MAX_VISUALS:
            break

        wid = item.get('window_id')
        try:
            wid = int(wid)
        except (TypeError, ValueError):
            continue
        if wid in seen:
            continue
        seen.add(wid)

        window = Window.query.filter_by(id=wid, project_id=quotation.project_id).first()
        if window is None:
            continue

        vis = (Visualisation.query.filter_by(window_id=wid)
               .filter(Visualisation.rendered_path.isnot(None))
               .order_by(Visualisation.created_at.desc()).first())
        if vis is None:
            continue

        after_path = _safe_path(vis.rendered_path)
        if after_path is None:
            continue
        after = _jpeg_bytes(after_path)
        if after is None:
            continue

        before = None
        before_path = _safe_path(vis.photo_path)
        if before_path is not None:
            before = _jpeg_bytes(before_path)

        visuals.append({
            'label':       item.get('label') or getattr(window, 'label', None) or 'Window',
            'after_jpeg':  after,
            'before_jpeg': before,
            'after_uri':   _data_uri(after),
            'before_uri':  _data_uri(before) if before else None,
        })

    return visuals
