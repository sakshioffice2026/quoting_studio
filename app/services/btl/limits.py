import hashlib
import json
import os
from datetime import datetime

from flask import current_app

from ...models import Visualisation, Window

CACHE_VERSION = '1'
CACHE_DIR = 'btl_cache'
CORNER_KEYS = ('tl', 'tr', 'br', 'bl')


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def daily_cap(enhanced):
    if enhanced:
        return _env_int('BTL_DAILY_ENHANCE_CAP', 10)
    return _env_int('BTL_DAILY_CAP', 50)


def _file_sha(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def cache_key(photo_path, overlay_png, corners, options, enhance, strength, use_sam, use_lama):
    payload = {
        'v':        CACHE_VERSION,
        'photo':    _file_sha(photo_path),
        'overlay':  hashlib.sha256(overlay_png).hexdigest(),
        'corners':  {k: [round(float(corners[k][0]), 1), round(float(corners[k][1]), 1)] for k in CORNER_KEYS},
        'options':  options,
        'enhance':  bool(enhance),
        'strength': round(float(strength), 3) if enhance else None,
        'sam':      bool(use_sam),
        'lama':     bool(use_lama),
    }
    blob = json.dumps(payload, sort_keys=True).encode('utf-8')
    return hashlib.sha256(blob).hexdigest()[:32]


def cache_relpath(key, enhanced):
    return f"{CACHE_DIR}/{'e' if enhanced else 'c'}-{key}.png"


def cache_fullpath(relpath):
    return os.path.join(current_app.config['UPLOAD_FOLDER'], relpath)


def used_today(tenant_id, enhanced):
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    prefix = f"{CACHE_DIR}/{'e' if enhanced else 'c'}-"
    return (
        Visualisation.query
        .join(Window, Window.id == Visualisation.window_id)
        .filter(
            Window.tenant_id == tenant_id,
            Visualisation.created_at >= start,
            Visualisation.rendered_path.like(prefix + '%'),
        )
        .count()
    )


def within_cap(tenant_id, enhanced):
    cap = daily_cap(enhanced)
    if cap <= 0:
        return True, 0, cap
    used = used_today(tenant_id, enhanced)
    return used < cap, used, cap
