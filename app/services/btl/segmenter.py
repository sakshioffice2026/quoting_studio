import os

import cv2
import numpy as np

SAM_MAX_SIDE = 1024
MIN_AREA_RATIO = 0.6
MAX_AREA_RATIO = 1.6
MIN_OVERLAP = 0.7

_predictor = None
_failed = False


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


def _sam_mask(photo_bgr, quad):
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

    try:
        predictor.set_image(rgb)
        masks, _scores, _logits = predictor.predict(
            point_coords=np.array([[cx, cy]]),
            point_labels=np.array([1]),
            box=box,
            multimask_output=False,
        )
    except Exception:
        return None

    mask = masks[0].astype(np.uint8) * 255
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

    k = max(3, int(0.015 * max(h, w))) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    return cv2.dilate(base, kernel)
