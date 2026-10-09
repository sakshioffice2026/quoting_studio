import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

import cv2
import numpy as np

CROP_PADDING = 0.45
DEFAULT_QUEUE_WAIT_SECONDS = 30.0
MAX_WAITING = 3
MIN_SEND_SIDE = 640
MAX_SEND_SIDE = 768

_gate = threading.Semaphore(1)
_pool = ThreadPoolExecutor(max_workers=2)
_waiting = 0
_waiting_lock = threading.Lock()


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _queue_wait():
    return max(0.0, _env_float('BTL_ENHANCE_QUEUE_WAIT', DEFAULT_QUEUE_WAIT_SECONDS))


def _acquire_slot():
    global _waiting
    with _waiting_lock:
        if _waiting >= MAX_WAITING:
            raise EnhanceError('Enhance queue is full')
        _waiting += 1
    try:
        got = _gate.acquire(timeout=_queue_wait())
    finally:
        with _waiting_lock:
            _waiting -= 1
    if not got:
        raise EnhanceError('Enhance service is busy')


class EnhanceError(RuntimeError):
    pass


def is_configured():
    return bool(os.environ.get('BTL_ENHANCE_URL'))


def _result_path(result):
    if isinstance(result, (list, tuple)):
        result = result[0] if result else None
    if isinstance(result, dict):
        result = result.get('path') or result.get('value')
    if not isinstance(result, str) or not os.path.isfile(result):
        raise EnhanceError('Enhance service returned no image')
    return result


def _call_remote(image_path, mask_path, strength, steps, seed):
    try:
        from gradio_client import Client, handle_file
    except ImportError:
        raise EnhanceError('gradio_client is not installed')

    url = os.environ.get('BTL_ENHANCE_URL')
    token = os.environ.get('BTL_ENHANCE_TOKEN') or None

    try:
        if token:
            try:
                client = Client(url, hf_token=token)
            except TypeError:
                client = Client(url, token=token)
        else:
            client = Client(url)

        result = client.predict(
            handle_file(image_path),
            handle_file(mask_path),
            strength,
            steps,
            seed,
            api_name='/enhance',
        )
    except EnhanceError:
        raise
    except Exception as exc:
        raise EnhanceError(f'Enhance service failed: {exc}')

    return _result_path(result)


def _ellipse(k):
    k = max(3, int(k)) | 1
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))


def _build_mask(h, w, quad, span, mode):
    quad_mask = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(quad_mask, np.round(quad).astype(np.int32), 255)

    grow = _ellipse(0.08 * span)
    outer = cv2.dilate(quad_mask, grow)

    if mode == 'full':
        return outer

    shrink = _ellipse(0.025 * span)
    inner = cv2.erode(quad_mask, shrink)
    band = cv2.subtract(outer, inner)
    return band


def _detail(img_bgr):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return gray - cv2.GaussianBlur(gray, (0, 0), 1.5)


def _grain_gap(original_bgr, new_bgr, sel):
    """Extra noise std needed so the enhanced area has the same grain as the photo."""
    if int(sel.sum()) < 64:
        return 0.0
    std_o = min(float(_detail(original_bgr)[sel].std()), 8.0)
    std_n = float(_detail(new_bgr)[sel].std())
    return float(np.sqrt(max(0.0, std_o ** 2 - std_n ** 2)))


def enhance(result_bgr, quad, strength=0.35, steps=20, seed=7, timeout=None):
    if not is_configured():
        raise EnhanceError('Enhance service is not configured')

    if timeout is None:
        timeout = _env_float('BTL_ENHANCE_TIMEOUT', 120.0)

    mode = (os.environ.get('BTL_ENHANCE_MODE', 'seam') or 'seam').strip().lower()
    if mode not in ('seam', 'full'):
        mode = 'seam'
    blend = float(np.clip(_env_float('BTL_ENHANCE_BLEND', 0.7), 0.0, 1.0))

    h, w = result_bgr.shape[:2]
    quad = np.asarray(quad, dtype=np.float32)
    x0, y0 = quad.min(axis=0)
    x1, y1 = quad.max(axis=0)
    span = float(max(x1 - x0, y1 - y0))
    pad = CROP_PADDING * span

    cx0, cy0 = int(max(0, x0 - pad)), int(max(0, y0 - pad))
    cx1, cy1 = int(min(w, x1 + pad)), int(min(h, y1 + pad))
    if cx1 - cx0 < 16 or cy1 - cy0 < 16:
        raise EnhanceError('Window area is too small to enhance')

    full_mask = _build_mask(h, w, quad, span, mode)

    crop = result_bgr[cy0:cy1, cx0:cx1]
    cmask = full_mask[cy0:cy1, cx0:cx1]
    ch, cw = crop.shape[:2]

    side = float(max(cw, ch))
    send_scale = 1.0
    if side < MIN_SEND_SIDE:
        send_scale = MIN_SEND_SIDE / side
    elif side > MAX_SEND_SIDE:
        send_scale = MAX_SEND_SIDE / side
    sw = max(64, int(round(cw * send_scale)))
    sh = max(64, int(round(ch * send_scale)))

    interp = cv2.INTER_LANCZOS4 if send_scale > 1.0 else cv2.INTER_AREA
    send_img = cv2.resize(crop, (sw, sh), interpolation=interp)
    send_mask = cv2.resize(cmask, (sw, sh), interpolation=cv2.INTER_NEAREST)

    _acquire_slot()

    try:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = os.path.join(tmp, 'composite.png')
            mask_path = os.path.join(tmp, 'mask.png')
            cv2.imwrite(image_path, send_img)
            cv2.imwrite(mask_path, send_mask)

            future = _pool.submit(_call_remote, image_path, mask_path, float(strength), int(steps), int(seed))
            try:
                out_path = future.result(timeout=timeout)
            except FutureTimeout:
                raise EnhanceError('Enhance service timed out')

            enhanced = cv2.imread(out_path, cv2.IMREAD_COLOR)
            if enhanced is None:
                raise EnhanceError('Enhance result could not be read')
    finally:
        _gate.release()

    if enhanced.shape[:2] != (ch, cw):
        enhanced = cv2.resize(enhanced, (cw, ch), interpolation=cv2.INTER_AREA)

    # restore the fine grain that the diffusion output loses
    sel = cmask > 127
    gap = _grain_gap(crop, enhanced, sel)
    if gap > 0.0:
        rng = np.random.default_rng(13)
        noise = rng.normal(0.0, gap, size=(ch, cw)).astype(np.float32)
        noise = cv2.GaussianBlur(noise, (0, 0), 0.6)
        enhanced = np.clip(enhanced.astype(np.float32) + noise[..., None], 0, 255).astype(np.uint8)

    k = max(5, int(0.02 * max(cw, ch))) | 1
    soft = cv2.GaussianBlur(cmask.astype(np.float32) / 255.0, (0, 0), k / 2.0)
    soft = np.clip(soft, 0.0, 1.0)[..., None] * blend

    blended = crop.astype(np.float32) * (1.0 - soft) + enhanced.astype(np.float32) * soft

    out = result_bgr.copy()
    out[cy0:cy1, cx0:cx1] = np.clip(blended, 0, 255).astype(np.uint8)
    return out
