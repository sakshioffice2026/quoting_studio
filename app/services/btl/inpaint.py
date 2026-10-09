import cv2
import numpy as np

MAX_CROP_SIDE = 1024

_lama = None
_lama_failed = False


def _get_lama():
    global _lama, _lama_failed
    if _lama is not None:
        return _lama
    if _lama_failed:
        return None
    try:
        from simple_lama_inpainting import SimpleLama
        _lama = SimpleLama()
    except Exception:
        _lama_failed = True
        return None
    return _lama


def _inpaint_crop(crop_bgr, crop_mask, use_lama):
    ch, cw = crop_bgr.shape[:2]

    if use_lama:
        lama = _get_lama()
        if lama is not None:
            try:
                from PIL import Image
                result = lama(
                    Image.fromarray(cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)),
                    Image.fromarray(crop_mask),
                )
                out = cv2.cvtColor(np.array(result), cv2.COLOR_RGB2BGR)
                if out.shape[:2] != (ch, cw):
                    out = cv2.resize(out, (cw, ch), interpolation=cv2.INTER_CUBIC)
                return out
            except Exception:
                pass

    return cv2.inpaint(crop_bgr, crop_mask, 5, cv2.INPAINT_TELEA)


def remove_region(photo_bgr, mask, use_lama=True):
    h, w = photo_bgr.shape[:2]
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return photo_bgr.copy()

    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    pad = int(max(64, 0.5 * max(x1 - x0, y1 - y0)))

    cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
    cx1, cy1 = min(w, x1 + pad), min(h, y1 + pad)

    crop = photo_bgr[cy0:cy1, cx0:cx1]
    cmask = mask[cy0:cy1, cx0:cx1]
    ch, cw = crop.shape[:2]

    scale = min(1.0, MAX_CROP_SIDE / float(max(ch, cw)))
    if scale < 1.0:
        small = cv2.resize(crop, (max(1, round(cw * scale)), max(1, round(ch * scale))), interpolation=cv2.INTER_AREA)
        small_mask = cv2.resize(cmask, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST)
    else:
        small, small_mask = crop, cmask

    filled = _inpaint_crop(small, small_mask, use_lama)
    if scale < 1.0:
        filled = cv2.resize(filled, (cw, ch), interpolation=cv2.INTER_CUBIC)

    soft = cv2.GaussianBlur((cmask > 0).astype(np.float32), (0, 0), 2.5)[..., None]
    blended = crop.astype(np.float32) * (1.0 - soft) + filled.astype(np.float32) * soft

    out = photo_bgr.copy()
    out[cy0:cy1, cx0:cx1] = np.clip(blended, 0, 255).astype(np.uint8)
    return out
