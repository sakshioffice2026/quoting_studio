# app/services/homography.py
# Phase 6 — server-side OpenCV homography warp for PDF/saved visualisations


def warp_window_onto_photo(photo_path: str, window_render_path: str,
                            corners: dict, opacity: float = 0.92):
    """
    corners: {'tl':(x,y), 'tr':(x,y), 'bl':(x,y), 'br':(x,y)} in photo pixels
    Returns numpy array (BGR) of the composited image.
    Placeholder until Phase 6.
    """
    try:
        import cv2
        import numpy as np

        photo   = cv2.imread(photo_path)
        overlay = cv2.imread(window_render_path, cv2.IMREAD_UNCHANGED)
        h, w    = overlay.shape[:2]

        src_pts = np.float32([[0, 0], [w, 0], [0, h], [w, h]])
        dst_pts = np.float32([corners['tl'], corners['tr'],
                               corners['bl'], corners['br']])
        M = cv2.getPerspectiveTransform(src_pts, dst_pts)
        warped = cv2.warpPerspective(overlay, M,
                                      (photo.shape[1], photo.shape[0]))

        if warped.shape[2] == 4:
            alpha = (warped[:, :, 3:4] / 255.0) * opacity
        else:
            alpha = opacity

        result = (photo * (1 - alpha) +
                  warped[:, :, :3] * alpha).astype('uint8')
        return result

    except ImportError:
        return None
