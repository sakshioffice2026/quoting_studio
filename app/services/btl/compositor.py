import os

import cv2
import numpy as np

from .. import homography


def _shift(img, dx, dy):
    h, w = img.shape[:2]
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def _ellipse(k):
    k = max(3, int(k)) | 1
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))


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
    return mean_bgr, noise_std, lap_var, ring


def _estimate_light(clean_bgr, ring, bx0, by0, bw, bh):
    """Estimate light direction from the brightness gradient of the wall around the window.

    Returns (lx, ly): >0 means brighter towards right / bottom.
    """
    prior_x, prior_y = -0.06, -0.10
    ys_i, xs_i = np.nonzero(ring)
    if xs_i.size < 400:
        return prior_x, prior_y

    if xs_i.size > 20000:
        idx = np.random.default_rng(3).choice(xs_i.size, 20000, replace=False)
        xs_i, ys_i = xs_i[idx], ys_i[idx]

    gray = cv2.cvtColor(clean_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    lum = gray[ys_i, xs_i]
    mean = max(float(lum.mean()), 1.0)
    nx = (xs_i.astype(np.float32) - bx0) / bw - 0.5
    ny = (ys_i.astype(np.float32) - by0) / bh - 0.5

    def slope(n):
        var = float(n.var())
        if var < 1e-6:
            return 0.0
        return float(((n - n.mean()) * (lum - mean)).mean()) / var / mean

    lx = float(np.clip(0.5 * prior_x + 0.5 * slope(nx), -0.25, 0.25))
    ly = float(np.clip(0.5 * prior_y + 0.5 * slope(ny), -0.25, 0.25))
    return lx, ly


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


def _scene_reflection(clean_bgr, quad):
    """Soft mirrored copy of the surroundings, laid over the window bounding box (float 0..1 BGR)."""
    h, w = clean_bgr.shape[:2]
    xs, ys = quad[:, 0], quad[:, 1]
    bw = float(xs.max() - xs.min())
    bh = float(ys.max() - ys.min())

    x0 = int(max(0, xs.min() - bw))
    x1 = int(min(w, xs.max() + bw))
    y0 = int(max(0, ys.min() - 0.5 * bh))
    y1 = int(min(h, ys.max() + 0.5 * bh))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None

    bx0, by0 = int(xs.min()), int(ys.min())
    bx1, by1 = int(xs.max()) + 1, int(ys.max()) + 1
    bw_i, bh_i = max(bx1 - bx0, 2), max(by1 - by0, 2)

    crop = cv2.flip(clean_bgr[y0:y1, x0:x1], 1)
    refl = cv2.resize(crop, (bw_i, bh_i), interpolation=cv2.INTER_AREA)
    refl = cv2.GaussianBlur(refl, (0, 0), max(2.0, 0.04 * max(bw_i, bh_i)))

    dx0, dy0 = max(bx0, 0), max(by0, 0)
    dx1, dy1 = min(bx1, w), min(by1, h)
    if dx1 <= dx0 or dy1 <= dy0:
        return None

    full = np.zeros((h, w, 3), np.float32)
    full[dy0:dy1, dx0:dx1] = refl[dy0 - by0:dy1 - by0, dx0 - bx0:dx1 - bx0].astype(np.float32) / 255.0
    return full


def _is_interior(clean_bgr, options):
    """True when the photo was taken indoors (no sky in the top of the frame).

    Override with options['interior'] (True/False/'on'/'off'/'auto') or the
    BTL_INTERIOR environment variable (auto | on | off).
    """
    flag = options.get('interior')
    if flag is None:
        flag = os.environ.get('BTL_INTERIOR', 'auto')

    if isinstance(flag, bool):
        return flag
    flag = str(flag).strip().lower()
    if flag in ('on', '1', 'true', 'yes', 'interior'):
        return True
    if flag in ('off', '0', 'false', 'no', 'exterior'):
        return False

    h = clean_bgr.shape[0]
    top = clean_bgr[:max(1, int(0.25 * h))].astype(np.int16)
    b, g, r = top[..., 0], top[..., 1], top[..., 2]
    sky = (b > r + 20) & (b >= g) & (b > 90)
    return float(sky.mean()) < 0.10


def _through_view(original_bgr, clean_bgr, quad):
    """What is seen through the new glass: the original view with the old
    frame and glazing bars removed (grey closing erases thin dark structures)."""
    h, w = original_bgr.shape[:2]
    view_full = clean_bgr.astype(np.float32) / 255.0

    xs, ys = quad[:, 0], quad[:, 1]
    span = float(max(xs.max() - xs.min(), ys.max() - ys.min(), 1.0))
    pad = int(0.08 * span) + 2
    x0, x1 = int(max(0, xs.min() - pad)), int(min(w, xs.max() + pad))
    y0, y1 = int(max(0, ys.min() - pad)), int(min(h, ys.max() + pad))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return view_full

    crop = original_bgr[y0:y1, x0:x1]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    k = max(7, int(0.12 * span)) | 1
    closed = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, _ellipse(k))
    blackhat = cv2.subtract(closed, gray)
    bars = ((gray < 70) & (blackhat > 30)).astype(np.uint8) * 255
    bars = cv2.dilate(bars, _ellipse(max(3, int(0.02 * span))))
    radius = max(3, int(0.03 * span))
    view = cv2.inpaint(crop, bars, radius, cv2.INPAINT_TELEA)
    view = cv2.GaussianBlur(view, (0, 0), 0.8)

    view_full[y0:y1, x0:x1] = view.astype(np.float32) / 255.0
    return view_full


def compose(clean_bgr, original_bgr, overlay_bgra, quad, options=None):
    options = options or {}
    shadow_k = float(options.get('shadow', 1.0))
    reflect_k = min(2.0, float(options.get('reflection', 1.0)))
    grain_k = float(options.get('grain', 1.0))
    match_colour = bool(options.get('match_colour', True))

    h, w = clean_bgr.shape[:2]
    quad = np.asarray(quad, dtype=np.float32)

    interior_mode = _is_interior(clean_bgr, options)
    if interior_mode:
        shadow_k *= 0.4

    warped, glass = _warp_overlay(overlay_bgra, quad, (w, h))
    alpha = warped[..., 3]
    rgb = warped[..., :3]

    quad_mask = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(quad_mask, np.round(quad).astype(np.int32), 255)
    mean_bgr, noise_std, lap_var, ring = _scene_stats(clean_bgr, quad_mask)

    if match_colour:
        luminance = float(mean_bgr.mean())
        gain = float(np.clip(luminance / 140.0, 0.72, 1.18))
        tint = 1.0 + 0.12 * (mean_bgr / max(luminance, 1.0) - 1.0)
        rgb = np.clip(rgb * gain * tint[None, None, :], 0.0, 1.0)

    xs_q, ys_q = quad[:, 0], quad[:, 1]
    bx0, bx1 = float(xs_q.min()), float(xs_q.max())
    by0, by1 = float(ys_q.min()), float(ys_q.max())
    bw, bh = max(bx1 - bx0, 1.0), max(by1 - by0, 1.0)

    xs = (np.arange(w, dtype=np.float32) - bx0) / bw
    ys = (np.arange(h, dtype=np.float32) - by0) / bh

    lx, ly = _estimate_light(clean_bgr, ring, bx0, by0, bw, bh)
    dir_x = 1.0 if lx <= 0.0 else -1.0

    # frame lighting follows the brightness gradient of the surrounding wall
    frame_a = np.clip(alpha - glass, 0.0, 1.0)
    lightmap = 1.0 + ly * (ys - 0.5)[:, None] + lx * (xs - 0.5)[None, :]
    lightmap = np.clip(lightmap, 0.8, 1.2).astype(np.float32)
    rgb = rgb * (1.0 + (lightmap[..., None] - 1.0) * frame_a[..., None])
    rgb = np.clip(rgb, 0.0, 1.0)

    sigma = 0.7 + (0.5 if lap_var < 60.0 else 0.0)
    rgb = cv2.GaussianBlur(rgb, (0, 0), sigma)
    alpha = cv2.GaussianBlur(alpha, (0, 0), sigma)
    glass = cv2.GaussianBlur(glass, (0, 0), sigma)
    glass = np.minimum(glass, alpha)

    # bevel: lit rim on the light-facing edges, shaded rim on the opposite edges
    k = max(1, int(0.006 * max(bw, bh)))
    hi = np.clip(alpha - _shift(alpha, k * dir_x, k), 0.0, 1.0)
    lo = np.clip(alpha - _shift(alpha, -k * dir_x, -k), 0.0, 1.0)
    rgb = rgb + 0.16 * hi[..., None] * (1.0 - rgb)
    rgb = rgb * (1.0 - 0.24 * lo[..., None])
    rgb = np.clip(rgb, 0.0, 1.0)

    base = clean_bgr.astype(np.float32) / 255.0

    off = max(2, int(0.012 * bw))

    # cast shadow on the wall (away from the light) + ambient occlusion all round
    cast = cv2.GaussianBlur(_shift(alpha, off * dir_x, off), (0, 0), off * 1.2) * (1.0 - alpha)
    base *= (1.0 - 0.38 * shadow_k * cast)[..., None]
    ao = cv2.GaussianBlur(alpha, (0, 0), off * 3.0) * (1.0 - alpha)
    base *= (1.0 - 0.22 * shadow_k * ao)[..., None]

    # contact line where frame meets wall
    edge = np.clip(alpha - cv2.erode(alpha, _ellipse(3)), 0.0, 1.0)
    edge_out = cv2.GaussianBlur(edge, (0, 0), 1.2) * (1.0 - alpha)
    base *= (1.0 - 0.18 * shadow_k * edge_out)[..., None]

    if interior_mode:
        # transparent glass: keep the view that was behind the old window/door
        through = _through_view(original_bgr, clean_bgr, quad)
        glass_img = np.clip(through * 0.97 + 0.015, 0.0, 1.0)
        glass_weight = 0.95
        sheen_k = 0.5
    else:
        # glass: dark room colour, sky tint fading downward, mirrored scene reflection
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
        glass_img = np.array(np.broadcast_to(glass_img, (h, w, 3)), dtype=np.float32)

        refl = _scene_reflection(clean_bgr, quad)
        if refl is not None:
            fres = np.clip(0.55 + 0.45 * (1.0 - np.clip(ys, 0.0, 1.0)), 0.0, 1.0)[:, None]
            refl_amt = np.clip(0.16 * reflect_k * fres, 0.0, 0.5)
            glass_img = glass_img * (1.0 - refl_amt[..., None]) + refl * refl_amt[..., None]

        glass_weight = 0.90
        sheen_k = 1.0

    # glass darkens next to the frame (depth between pane and frame)
    frame_inner = np.clip(alpha - glass, 0.0, 1.0)
    frame_soft = cv2.GaussianBlur(frame_inner, (0, 0), max(2.0, 0.02 * max(bw, bh)))
    glass_img = glass_img * (1.0 - 0.32 * shadow_k * (frame_soft * glass))[..., None]

    weight = (glass * glass_weight)[..., None]
    base = base * (1.0 - weight) + glass_img * weight

    # reveal depth: shadow cast inside the opening from the light side
    d = off * 2.0
    reveal = np.clip(glass - _shift(glass, d * dir_x, d), 0.0, 1.0)
    reveal = cv2.GaussianBlur(reveal, (0, 0), off)
    base *= (1.0 - 0.6 * shadow_k * reveal)[..., None]

    out = rgb + base * (1.0 - alpha)[..., None]

    t = xs[None, :] * 0.6 + ys[:, None] * 0.4
    band = np.exp(-((t - 0.35) / 0.12) ** 2) * 0.55 + np.exp(-((t - 0.75) / 0.07) ** 2) * 0.30
    sheen = (band * 0.30 * reflect_k * sheen_k).astype(np.float32)
    out = 1.0 - (1.0 - out) * (1.0 - sheen[..., None] * glass[..., None])

    if grain_k > 0 and noise_std > 0:
        rng = np.random.default_rng(7)
        noise = cv2.GaussianBlur(
            rng.normal(0.0, min(noise_std, 0.012) * grain_k, size=(h, w)).astype(np.float32),
            (0, 0), 0.8)[..., None]
        out = out + noise * alpha[..., None]

    return np.clip(out * 255.0, 0, 255).astype(np.uint8)
