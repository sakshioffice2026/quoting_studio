import cv2
import numpy as np

from . import compositor, inpaint, segmenter

CORNER_ORDER = ('tl', 'tr', 'br', 'bl')


def _decode_overlay(overlay_png):
    overlay = cv2.imdecode(np.frombuffer(overlay_png, np.uint8), cv2.IMREAD_UNCHANGED)
    if overlay is None:
        raise ValueError('Overlay could not be decoded')
    if overlay.ndim != 3 or overlay.shape[2] != 4:
        raise ValueError('Overlay must have an alpha channel')
    return overlay


def run_layers(photo_path, layers, options=None, use_sam=True, use_lama=True):
    """layers: list of (overlay_png_bytes, corners_dict) in photo pixels."""
    photo = cv2.imread(photo_path, cv2.IMREAD_COLOR)
    if photo is None:
        raise ValueError('Photo could not be read')
    if not layers:
        raise ValueError('No window openings to render')

    prepared = []
    for overlay_png, corners in layers:
        quad = np.float32([corners[key] for key in CORNER_ORDER])
        prepared.append((_decode_overlay(overlay_png), quad))

    mask = None
    for _overlay, quad in prepared:
        m = segmenter.window_mask(photo, quad, use_sam=use_sam)
        mask = m if mask is None else np.maximum(mask, m)

    clean = inpaint.remove_region(photo, mask, use_lama=use_lama)

    out = clean
    for overlay, quad in prepared:
        out = compositor.compose(out, photo, overlay, quad, options or {})
    return out


def run(photo_path, overlay_png, corners, options=None, use_sam=True, use_lama=True):
    return run_layers(photo_path, [(overlay_png, corners)], options=options,
                      use_sam=use_sam, use_lama=use_lama)
