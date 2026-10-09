import cv2
import numpy as np

CORNER_ORDER = ('tl', 'tr', 'br', 'bl')


def corners_to_quad(corners):
    return np.float32([[float(corners[k][0]), float(corners[k][1])] for k in CORNER_ORDER])


def source_quad(width, height):
    return np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])


def perspective_matrix(width, height, quad):
    return cv2.getPerspectiveTransform(source_quad(width, height), np.float32(quad))


def warp_bgra(overlay_bgra, quad, size):
    """Warp a BGRA overlay onto a (width, height) canvas.

    Returns (premultiplied float32 BGRA in 0..1, perspective matrix).
    """
    oh, ow = overlay_bgra.shape[:2]
    matrix = perspective_matrix(ow, oh, quad)

    f = overlay_bgra.astype(np.float32) / 255.0
    f[..., :3] *= f[..., 3:4]
    warped = cv2.warpPerspective(
        f, matrix, size,
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )
    return warped, matrix


def warp_mask(mask_u8, matrix, size):
    """Warp a single-channel uint8 mask with an existing matrix; returns float32 0..1."""
    return cv2.warpPerspective(
        mask_u8.astype(np.float32) / 255.0, matrix, size,
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )


def warp_window_onto_photo(photo_path, window_render_path, corners, opacity=0.92):
    """Simple alpha composite of a window render onto a photo.

    corners: {'tl':(x,y), 'tr':(x,y), 'br':(x,y), 'bl':(x,y)} in photo pixels.
    Returns a BGR numpy array, or None when the photo or overlay cannot be read.
    """
    photo = cv2.imread(photo_path, cv2.IMREAD_COLOR)
    overlay = cv2.imread(window_render_path, cv2.IMREAD_UNCHANGED)
    if photo is None or overlay is None:
        return None

    if overlay.ndim == 2:
        overlay = cv2.cvtColor(overlay, cv2.COLOR_GRAY2BGRA)
    elif overlay.shape[2] == 3:
        overlay = cv2.cvtColor(overlay, cv2.COLOR_BGR2BGRA)

    h, w = photo.shape[:2]
    warped, _ = warp_bgra(overlay, corners_to_quad(corners), (w, h))

    alpha = np.clip(warped[..., 3:4] * float(opacity), 0.0, 1.0)
    base = photo.astype(np.float32) / 255.0
    out = warped[..., :3] * float(opacity) + base * (1.0 - alpha)
    return np.clip(out * 255.0, 0, 255).astype(np.uint8)
