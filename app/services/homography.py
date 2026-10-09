import cv2
import numpy as np

CORNER_ORDER = ('tl', 'tr', 'br', 'bl')


def corners_to_quad(corners):
    return np.float32([[float(corners[k][0]), float(corners[k][1])] for k in CORNER_ORDER])


def source_quad(width, height):
    return np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])


def perspective_matrix(width, height, quad):
    return cv2.getPerspectiveTransform(source_quad(width, height), np.float32(quad))


def _quad_target_size(quad):
    q = np.asarray(quad, dtype=np.float32)
    top = float(np.linalg.norm(q[1] - q[0]))
    bottom = float(np.linalg.norm(q[2] - q[3]))
    left = float(np.linalg.norm(q[3] - q[0]))
    right = float(np.linalg.norm(q[2] - q[1]))
    return max(top, bottom, 1.0), max(left, right, 1.0)


def warp_bgra(overlay_bgra, quad, size):
    """Warp a BGRA overlay onto a (width, height) canvas.

    The overlay is first shrunk with area averaging to about the on-photo size so thin
    frame lines stay clean instead of aliasing.

    Returns (premultiplied float32 BGRA in 0..1, perspective matrix for the ORIGINAL overlay size).
    """
    oh, ow = overlay_bgra.shape[:2]
    matrix = perspective_matrix(ow, oh, quad)

    target_w, target_h = _quad_target_size(quad)
    sx = min(1.0, target_w / float(ow))
    sy = min(1.0, target_h / float(oh))

    f = overlay_bgra.astype(np.float32) / 255.0
    f[..., :3] *= f[..., 3:4]

    if sx < 0.9 or sy < 0.9:
        rw = max(2, int(round(ow * sx)))
        rh = max(2, int(round(oh * sy)))
        f = cv2.resize(f, (rw, rh), interpolation=cv2.INTER_AREA)
        scale = np.array([[rw / float(ow), 0.0, 0.0],
                          [0.0, rh / float(oh), 0.0],
                          [0.0, 0.0, 1.0]], dtype=np.float64)
        warp_matrix = matrix.astype(np.float64) @ np.linalg.inv(scale)
    else:
        warp_matrix = matrix

    warped = cv2.warpPerspective(
        f, warp_matrix, size,
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )
    return np.clip(warped, 0.0, 1.0), matrix


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
