import cv2
import numpy as np

from . import compositor, inpaint, segmenter

CORNER_ORDER = ('tl', 'tr', 'br', 'bl')


def run(photo_path, overlay_png, corners, options=None, use_sam=True, use_lama=True):
    photo = cv2.imread(photo_path, cv2.IMREAD_COLOR)
    if photo is None:
        raise ValueError('Photo could not be read')

    overlay = cv2.imdecode(np.frombuffer(overlay_png, np.uint8), cv2.IMREAD_UNCHANGED)
    if overlay is None:
        raise ValueError('Overlay could not be decoded')
    if overlay.ndim != 3 or overlay.shape[2] != 4:
        raise ValueError('Overlay must have an alpha channel')

    quad = np.float32([corners[key] for key in CORNER_ORDER])

    mask = segmenter.window_mask(photo, quad, use_sam=use_sam)
    clean = inpaint.remove_region(photo, mask, use_lama=use_lama)
    return compositor.compose(clean, photo, overlay, quad, options or {})
