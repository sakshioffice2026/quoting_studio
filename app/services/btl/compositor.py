import cv2
import numpy as np

from .. import homography


def _shift(img, dx, dy):
    h, w = img.shape[:2]
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def _warp_overlay(overlay_bgra, quad, size):
    warped, matrix = homography.warp_bgra(overlay_bgra, quad, size)

    alpha = overlay_bgra[..., 3]
    glass_src = ((alpha > 15) & (alpha < 240)).astype(np.uint8) * 255
    glass_src = cv2.erode(glass_src, np.ones((3, 3), np.uint8))
    glass = homography.warp_mask(glass_src, matrix, size)
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
    dark_room = np.float32([52, 46, 42])
    sampled = np.clip(pixels.mean(axis=0) * 0.5, 20, 90)
    return np.clip(0.75 * dark_room + 0.25 * sampled, 25, 80)


def _sky_colour(clean_bgr):
    rows = max(1, int(0.12 * clean_bgr.shape[0]))
    return (clean_bgr[:rows].reshape(-1, 3).astype(np.float32).mean(axis=0) / 255.0)


def compose(clean_bgr, original_bgr, overlay_bgra, quad, options=None):
    options = options or {}
    shadow_k = float(options.get('shadow', 1.0))
    reflect_k = min(2.0, float(options.get('reflection', 1.0)))
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

    xs_q, ys_q = quad[:, 0], quad[:, 1]
    bx0, bx1 = float(xs_q.min()), float(xs_q.max())
    by0, by1 = float(ys_q.min()), float(ys_q.max())
    bw, bh = max(bx1 - bx0, 1.0), max(by1 - by0, 1.0)

    xs = (np.arange(w, dtype=np.float32) - bx0) / bw
    ys = (np.arange(h, dtype=np.float32) - by0) / bh

    # frame lighting: sun from the top-left, applied to the frame only
    frame_a = np.clip(alpha - glass, 0.0, 1.0)
    lightmap = 1.0 + 0.10 * (0.5 - ys)[:, None] + 0.06 * (0.5 - xs)[None, :]
    lightmap = np.clip(lightmap, 0.8, 1.2).astype(np.float32)
    rgb = rgb * (1.0 + (lightmap[..., None] - 1.0) * frame_a[..., None])
    rgb = np.clip(rgb, 0.0, 1.0)

    sigma = 0.7 + (0.5 if lap_var < 60.0 else 0.0)
    rgb = cv2.GaussianBlur(rgb, (0, 0), sigma)
    alpha = cv2.GaussianBlur(alpha, (0, 0), sigma)
    glass = cv2.GaussianBlur(glass, (0, 0), sigma)
    glass = np.minimum(glass, alpha)

    # bevel: lit rim on the top-left edges, shaded rim on the bottom-right
    k = max(1, int(0.006 * max(bw, bh)))
    hi = np.clip(alpha - _shift(alpha, k, k), 0.0, 1.0)
    lo = np.clip(alpha - _shift(alpha, -k, -k), 0.0, 1.0)
    rgb = rgb + 0.16 * hi[..., None] * (1.0 - rgb)
    rgb = rgb * (1.0 - 0.24 * lo[..., None])
    rgb = np.clip(rgb, 0.0, 1.0)

    base = clean_bgr.astype(np.float32) / 255.0

    off = max(2, int(0.012 * bw))

    # cast shadow on the wall (bottom-right) + ambient occlusion all round
    cast = cv2.GaussianBlur(_shift(alpha, off, off), (0, 0), off * 1.2) * (1.0 - alpha)
    base *= (1.0 - 0.38 * shadow_k * cast)[..., None]
    ao = cv2.GaussianBlur(alpha, (0, 0), off * 3.0) * (1.0 - alpha)
    base *= (1.0 - 0.22 * shadow_k * ao)[..., None]

    # glass: dark room colour with a sky reflection that fades towards the bottom
    interior = (_interior_colour(original_bgr, quad) / 255.0).astype(np.float32)
    sky = _sky_colour(clean_bgr)
    row_factor = np.ones(h, np.float32)
    mix_amt = np.zeros(h, np.float32)
    y_start, y_end = max(0, int(by0)), min(h, int(by1) + 1)
    if y_end > y_start:
        n = y_end - y_start
        row_factor[y_start:y_end] = np.linspace(0.85, 1.1, n, dtype=np.float32)
        mix_amt[y_start:y_end] = (0.18 * reflect_k) * np.linspace(1.0, 0.0, n, dtype=np.float32)
    interior_img = row_factor[:, None, None] * interior[None, None, :]
    glass_img = interior_img * (1.0 - mix_amt[:, None, None]) + sky[None, None, :] * mix_amt[:, None, None]
    glass_img = np.broadcast_to(glass_img, (h, w, 3))

    weight = (glass * 0.90)[..., None]
    base = base * (1.0 - weight) + glass_img * weight

    # reveal depth: shadow cast inside the opening from the top and left
    d = off * 2.0
    reveal = np.clip(glass - _shift(glass, d, d), 0.0, 1.0)
    reveal = cv2.GaussianBlur(reveal, (0, 0), off)
    base *= (1.0 - 0.6 * shadow_k * reveal)[..., None]

    out = rgb + base * (1.0 - alpha)[..., None]

    t = xs[None, :] * 0.6 + ys[:, None] * 0.4
    band = np.exp(-((t - 0.35) / 0.12) ** 2) * 0.55 + np.exp(-((t - 0.75) / 0.07) ** 2) * 0.30
    sheen = (band * 0.30 * reflect_k).astype(np.float32)
    out = 1.0 - (1.0 - out) * (1.0 - sheen[..., None] * glass[..., None])

    if grain_k > 0 and noise_std > 0:
        rng = np.random.default_rng(7)
        noise = cv2.GaussianBlur(
            rng.normal(0.0, min(noise_std, 0.012) * grain_k, size=(h, w)).astype(np.float32),
            (0, 0), 0.8)[..., None]
        out = out + noise * alpha[..., None]

    return np.clip(out * 255.0, 0, 255).astype(np.uint8)
