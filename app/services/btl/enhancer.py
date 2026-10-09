import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

import cv2
import numpy as np

CROP_PADDING = 0.25
DEFAULT_QUEUE_WAIT_SECONDS = 30.0
MAX_WAITING = 3

_gate = threading.Semaphore(1)
_pool = ThreadPoolExecutor(max_workers=2)
_waiting = 0
_waiting_lock = threading.Lock()


def _queue_wait():
    try:
        return max(0.0, float(os.environ.get('BTL_ENHANCE_QUEUE_WAIT', DEFAULT_QUEUE_WAIT_SECONDS)))
    except ValueError:
        return DEFAULT_QUEUE_WAIT_SECONDS


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


def enhance(result_bgr, quad, strength=0.35, steps=20, seed=7, timeout=None):
    if not is_configured():
        raise EnhanceError('Enhance service is not configured')

    if timeout is None:
        try:
            timeout = float(os.environ.get('BTL_ENHANCE_TIMEOUT', '120'))
        except ValueError:
            timeout = 120.0

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

    crop = result_bgr[cy0:cy1, cx0:cx1]
    ch, cw = crop.shape[:2]

    full_mask = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(full_mask, np.round(quad).astype(np.int32), 255)
    grow = max(5, int(0.02 * span)) | 1
    full_mask = cv2.dilate(full_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (grow, grow)))
    cmask = full_mask[cy0:cy1, cx0:cx1]

    _acquire_slot()

    try:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = os.path.join(tmp, 'composite.png')
            mask_path = os.path.join(tmp, 'mask.png')
            cv2.imwrite(image_path, crop)
            cv2.imwrite(mask_path, cmask)

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
        enhanced = cv2.resize(enhanced, (cw, ch), interpolation=cv2.INTER_CUBIC)

    k = max(5, int(0.02 * max(cw, ch))) | 1
    inner = cv2.erode(cmask, np.ones((k, k), np.uint8))
    soft = cv2.GaussianBlur(inner.astype(np.float32) / 255.0, (0, 0), k / 2.0)[..., None]

    blended = crop.astype(np.float32) * (1.0 - soft) + enhanced.astype(np.float32) * soft

    out = result_bgr.copy()
    out[cy0:cy1, cx0:cx1] = np.clip(blended, 0, 255).astype(np.uint8)
    return out
