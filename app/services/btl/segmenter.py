import os

import cv2
import numpy as np

SAM_MAX_SIDE = 1024
MIN_AREA_RATIO = 0.6
MAX_AREA_RATIO = 1.6
MIN_OVERLAP = 0.7

_predictor = None
_failed = False
_embedded_key = None


def _load_predictor():
    global _predictor, _failed
    if _predictor is not None:
        return _predictor
    if _failed:
        return None

    checkpoint = os.environ.get('BTL_SAM_CHECKPOINT', '')
    if not checkpoint or not os.path.isfile(checkpoint):
        _failed = True
        return None

    try:
        from mobile_sam import sam_model_registry, SamPredictor
        model = sam_model_registry['vit_t'](checkpoint=checkpoint)
        model.to('cpu')
        model.eval()
        _predictor = SamPredictor(model)
    except Exception:
        _failed = True
        return None
    return _predictor


def _clean_mask(mask_u8):
    """Close small gaps, fill holes and keep only the largest blob."""
    k = max(3, int(0.01 * max(mask_u8.shape[:2]))) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    closed = cv2.morphologyEx(mask_u8, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return closed

    largest = max(contours, key=cv2.contourArea)
    out = np.zeros_like(closed)
    cv2.drawContours(out, [largest], -1, 255, thickness=cv2.FILLED)
    return out


def _sam_mask(photo_bgr, quad):
    global _embedded_key

    predictor = _load_predictor()
    if predictor is None:
        return None

    h, w = photo_bgr.shape[:2]
    scale = min(1.0, SAM_MAX_SIDE / float(max(h, w)))
    if scale < 1.0:
        small = cv2.resize(photo_bgr, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    else:
        small = photo_bgr

    rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    q = quad * scale
    cx, cy = q.mean(axis=0)
    box = np.array([q[:, 0].min(), q[:, 1].min(), q[:, 0].max(), q[:, 1].max()])

    key = (small.shape, hash(cv2.resize(small, (16, 16), interpolation=cv2.INTER_AREA).tobytes()))

    try:
        if key != _embedded_key:
            predictor.set_image(rgb)
            _embedded_key = key
        masks, scores, _logits = predictor.predict(
            point_coords=np.array([[cx, cy]]),
            point_labels=np.array([1]),
            box=box,
            multimask_output=True,
        )
    except Exception:
        _embedded_key = None
        return None

    quad_small = np.zeros(small.shape[:2], np.uint8)
    cv2.fillConvexPoly(quad_small, np.round(q).astype(np.int32), 1)

    best, best_score = None, -1.0
    for m, s in zip(masks, scores):
        m8 = m.astype(np.uint8)
        inter = float(np.logical_and(m8 > 0, quad_small > 0).sum())
        union = float(np.logical_or(m8 > 0, quad_small > 0).sum())
        score = inter / max(union, 1.0) + 0.1 * float(s)
        if score > best_score:
            best, best_score = m8, score

    if best is None:
        return None

    mask = _clean_mask(best * 255)
    if scale < 1.0:
        mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
    return mask


def window_mask(photo_bgr, quad, use_sam=True):
    h, w = photo_bgr.shape[:2]
    quad = np.asarray(quad, dtype=np.float32)

    base = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(base, np.round(quad).astype(np.int32), 255)
    base_area = float(max(1, (base > 0).sum()))

    if use_sam:
        sam = _sam_mask(photo_bgr, quad)
        if sam is not None:
            sam_area = float((sam > 0).sum())
            overlap = float(np.logical_and(sam > 0, base > 0).sum()) / base_area
            ratio = sam_area / base_area
            if MIN_AREA_RATIO <= ratio <= MAX_AREA_RATIO and overlap >= MIN_OVERLAP:
                base = np.maximum(base, sam)

    span = float(max(quad[:, 0].max() - quad[:, 0].min(), quad[:, 1].max() - quad[:, 1].min(), 1.0))
    k = max(3, int(0.012 * span)) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    return cv2.dilate(base, kernel)
