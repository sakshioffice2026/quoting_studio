import cv2
import numpy as np


def _shift(img, dx, dy):
    h, w = img.shape[:2]
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def _warp_overlay(overlay_bgra, quad, size):
    oh, ow = overlay_bgra.shape[:2]
    src = np.float32([[0, 0], [ow - 1, 0], [ow - 1, oh - 1], [0, oh - 1]])
    matrix = cv2.getPerspectiveTransform(src, np.float32(quad))

    f = overlay_bgra.astype(np.float32) / 255.0
    f[..., :3] *= f[..., 3:4]
    warped = cv2.warpPerspective(f, matrix, size, flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))

    alpha = overlay_bgra[..., 3]
    glass_src = ((alpha > 15) & (alpha < 240)).astype(np.uint8) * 255
    glass_src = cv2.erode(glass_src, np.ones((3, 3), np.uint8))
    glass = cv2.warpPerspective(glass_src.astype(np.float32) / 255.0, matrix, size,
                                flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return warped, glass


def _scene_stats(clean_bgr, quad_mask):
    h, w = clean_bgr.shape[:2]
    big = int(0.06 * max(h, w)) | 1
    small = max(3, int(0.01 * max(h, w))) | 1
    outer = cv2.dilate(quad_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (big, big)))
    inner = cv2.dilate(quad_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (small, small)))
    ring = (outer > 0) & (inner == 0)

    if int(ring.sum()) < 50:
        ring = np.ones((h, w), dtype=bool)

    pixels = clean_bgr[ring].astype(np.float32)
    mean_bgr = pixels.mean(axis=0)

    gray = cv2.cvtColor(clean_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    detail = gray - cv2.GaussianBlur(gray, (0, 0), 1.5)
    noise_std = float(detail[ring].std()) / 255.0
    lap_var = float(cv2.Laplacian(gray, cv2.CV_32F)[ring].var())
    return mean_bgr, noise_std, lap_var


def _interior_colour(original_bgr, quad):
    h, w = original_bgr.shape[:2]
    centre = quad.mean(axis=0)
    shrunk = centre + (quad - centre) * 0.5
    mask = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(mask, np.round(shrunk).astype(np.int32), 255)
    pixels = original_bgr[mask > 0].astype(np.float32)
    if len(pixels) == 0:
        return np.float32([60, 60, 60])
    return np.clip(pixels.mean(axis=0) * 0.75, 25, 120)


def compose(clean_bgr, original_bgr, overlay_bgra, quad, options=None):
    options = options or {}
    shadow_k = float(options.get('shadow', 1.0))
    reflect_k = float(options.get('reflection', 1.0))
    grain_k = float(options.get('grain', 1.0))
    match_colour = bool(options.get('match_colour', True))

    h, w = clean_bgr.shape[:2]
    quad = np.asarray(quad, dtype=np.float32)

    warped, glass = _warp_overlay(overlay_bgra, quad, (w, h))
    alpha = warped[..., 3]
    rgb = warped[..., :3]

    quad_mask = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(quad_mask, np.round(quad).astype(np.int32), 255)
    mean_bgr, noise_std, lap_var = _scene_stats(clean_bgr, quad_mask)

    if match_colour:
        luminance = float(mean_bgr.mean())
        gain = float(np.clip(luminance / 140.0, 0.75, 1.15))
        tint = 1.0 + 0.08 * (mean_bgr / max(luminance, 1.0) - 1.0)
        rgb = np.clip(rgb * gain * tint[None, None, :], 0.0, 1.0)

    sigma = 0.7 + (0.5 if lap_var < 60.0 else 0.0)
    rgb = cv2.GaussianBlur(rgb, (0, 0), sigma)
    alpha = cv2.GaussianBlur(alpha, (0, 0), sigma)
    glass = cv2.GaussianBlur(glass, (0, 0), sigma)
    glass = np.minimum(glass, alpha)

    xs_q, ys_q = quad[:, 0], quad[:, 1]
    bx0, bx1 = float(xs_q.min()), float(xs_q.max())
    by0, by1 = float(ys_q.min()), float(ys_q.max())
    bw, bh = max(bx1 - bx0, 1.0), max(by1 - by0, 1.0)

    base = clean_bgr.astype(np.float32) / 255.0

    off = max(2, int(0.012 * bw))
    cast = cv2.GaussianBlur(_shift(alpha, off, off), (0, 0), off * 1.2) * (1.0 - alpha)
    base *= (1.0 - 0.30 * shadow_k * cast)[..., None]

    interior = (_interior_colour(original_bgr, quad) / 255.0).astype(np.float32)
    row_factor = np.ones(h, np.float32)
    y_start, y_end = max(0, int(by0)), min(h, int(by1) + 1)
    if y_end > y_start:
        row_factor[y_start:y_end] = np.linspace(0.85, 1.1, y_end - y_start, dtype=np.float32)
    interior_img = row_factor[:, None, None] * interior[None, None, :]
    interior_img = np.broadcast_to(interior_img, (h, w, 3))

    weight = (glass * 0.92)[..., None]
    base = base * (1.0 - weight) + interior_img * weight

    reveal = np.clip(glass - _shift(glass, off * 1.5, off * 1.5), 0.0, 1.0)
    reveal = cv2.GaussianBlur(reveal, (0, 0), off)
    base *= (1.0 - 0.45 * shadow_k * reveal)[..., None]

    out = rgb + base * (1.0 - alpha)[..., None]

    xs = (np.arange(w, dtype=np.float32) - bx0) / bw
    ys = (np.arange(h, dtype=np.float32) - by0) / bh
    t = xs[None, :] * 0.6 + ys[:, None] * 0.4
    band = np.exp(-((t - 0.35) / 0.12) ** 2) * 0.55 + np.exp(-((t - 0.75) / 0.07) ** 2) * 0.30
    sheen = (band * 0.22 * reflect_k).astype(np.float32)
    out = 1.0 - (1.0 - out) * (1.0 - sheen[..., None] * glass[..., None])

    if grain_k > 0 and noise_std > 0:
        rng = np.random.default_rng(7)
        noise = rng.normal(0.0, noise_std * grain_k, size=(h, w, 1)).astype(np.float32)
        out = out + noise * alpha[..., None]

    return np.clip(out * 255.0, 0, 255).astype(np.uint8)
