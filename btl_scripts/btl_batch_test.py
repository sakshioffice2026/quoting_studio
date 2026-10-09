import argparse
import json
import os
import sys
import time

import cv2
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.services.btl import enhancer, pipeline  # noqa: E402

CORNER_KEYS = ('tl', 'tr', 'br', 'bl')
IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.webp')
THUMB_H = 360

DEFAULT_DESIGN = {
    'shape': 'rectangle',
    'frame': {'color': '#2B2F33', 'sashColor': '#2B2F33', 'thickness': 58},
    'panes': [
        {'x': 0, 'y': 0, 'w': 0.5, 'h': 1, 'opening': 'Fixed'},
        {'x': 0.5, 'y': 0, 'w': 0.5, 'h': 1, 'opening': 'Left'},
    ],
}


def _load_overlay(path, width_mm, height_mm):
    if path:
        with open(path, 'rb') as fh:
            return fh.read()
    from app.services.window_overlay_png import render_overlay_png
    return render_overlay_png(DEFAULT_DESIGN, width_mm, height_mm)


def _thumb(img):
    h, w = img.shape[:2]
    scale = THUMB_H / float(h)
    return cv2.resize(img, (max(1, int(round(w * scale))), THUMB_H), interpolation=cv2.INTER_AREA)


def _label(img, text):
    out = img.copy()
    cv2.rectangle(out, (0, 0), (out.shape[1], 22), (0, 0, 0), -1)
    cv2.putText(out, text, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return out


def _sheet(rows):
    width = max(sum(t.shape[1] for t in row) for row in rows)
    canvas = np.full((THUMB_H * len(rows), width, 3), 255, np.uint8)
    for r, row in enumerate(rows):
        x = 0
        for t in row:
            canvas[r * THUMB_H:(r + 1) * THUMB_H, x:x + t.shape[1]] = t
            x += t.shape[1]
    return canvas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--photos', default=os.path.join(ROOT, 'btl_test', 'photos'))
    ap.add_argument('--corners', default=os.path.join(ROOT, 'btl_test', 'corners.json'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'btl_test', 'out'))
    ap.add_argument('--overlay', default='')
    ap.add_argument('--width-mm', type=float, default=1200.0)
    ap.add_argument('--height-mm', type=float, default=1400.0)
    ap.add_argument('--enhance', action='store_true')
    ap.add_argument('--strengths', default='0.25,0.35,0.45')
    ap.add_argument('--no-sam', action='store_true')
    ap.add_argument('--no-lama', action='store_true')
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    with open(args.corners, 'r', encoding='utf-8') as fh:
        corners_map = json.load(fh)

    overlay_png = _load_overlay(args.overlay, args.width_mm, args.height_mm)
    strengths = [float(s) for s in args.strengths.split(',') if s.strip()]

    names = sorted(n for n in os.listdir(args.photos) if n.lower().endswith(IMAGE_EXT))
    rows = []
    failures = []

    for name in names:
        corners = corners_map.get(name)
        if not corners:
            print(f'skip {name}: no corners')
            continue

        photo_path = os.path.join(args.photos, name)
        stem = os.path.splitext(name)[0]
        original = cv2.imread(photo_path, cv2.IMREAD_COLOR)
        if original is None:
            failures.append(name)
            print(f'fail {name}: unreadable')
            continue

        c = {k: (float(corners[k][0]), float(corners[k][1])) for k in CORNER_KEYS}
        quad = [c[k] for k in CORNER_KEYS]

        try:
            t0 = time.time()
            cpu = pipeline.run(photo_path, overlay_png, c,
                               use_sam=not args.no_sam, use_lama=not args.no_lama)
            cpu_secs = time.time() - t0
        except Exception as exc:
            failures.append(name)
            print(f'fail {name}: {exc}')
            continue

        cv2.imwrite(os.path.join(args.out, f'{stem}_cpu.jpg'), cpu, [cv2.IMWRITE_JPEG_QUALITY, 92])
        row = [_label(_thumb(original), 'original'), _label(_thumb(cpu), f'cpu {cpu_secs:.1f}s')]
        print(f'ok   {name}: cpu {cpu_secs:.1f}s')

        if args.enhance:
            for strength in strengths:
                try:
                    t1 = time.time()
                    enh = enhancer.enhance(cpu, quad, strength=strength)
                    secs = time.time() - t1
                except enhancer.EnhanceError as exc:
                    print(f'     enhance {strength}: {exc}')
                    continue
                cv2.imwrite(os.path.join(args.out, f'{stem}_enh_{strength:.2f}.jpg'), enh,
                            [cv2.IMWRITE_JPEG_QUALITY, 92])
                row.append(_label(_thumb(enh), f'enh {strength:.2f} {secs:.0f}s'))
                print(f'     enhance {strength}: {secs:.1f}s')

        rows.append(row)

    if rows:
        cv2.imwrite(os.path.join(args.out, 'contact_sheet.jpg'), _sheet(rows), [cv2.IMWRITE_JPEG_QUALITY, 90])

    print(f'done: {len(rows)} rendered, {len(failures)} failed')
    if failures:
        print('failed: ' + ', '.join(failures))


if __name__ == '__main__':
    main()
