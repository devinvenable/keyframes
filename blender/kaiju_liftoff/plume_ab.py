"""A/B plates for the graded extension's peak-flame frames (T309 plume caveat).

8-bit inverse AgX cannot restore clipped HDR in the rocket plumes; these plates
exist so a human can look for banding or hue shifts in the flames after grading.
Each plate: ungraded | graded full frames on top, 2x plume crops underneath.
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

CROP = (500, 900, 760, 1200)  # y0, y1, x0, x1 — twin booster plumes


def label(image, text):
    cv2.putText(image, text, (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                (0, 0, 0), 5, cv2.LINE_AA)
    cv2.putText(image, text, (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                (255, 255, 255), 2, cv2.LINE_AA)
    return image


def plume_stats(image):
    y0, y1, x0, x1 = CROP
    region = image[y0:y1, x0:x1].astype(np.float32)
    hsv = cv2.cvtColor(region.astype(np.uint8), cv2.COLOR_BGR2HSV)
    bright = region.max(axis=2) >= 230
    return dict(clipped_fraction=float((region == 255).mean()),
                bright_pixels=int(bright.sum()),
                bright_hue_mean=float(hsv[..., 0][bright].mean()) if bright.any() else None,
                bright_hue_std=float(hsv[..., 0][bright].std()) if bright.any() else None)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--ungraded', type=Path, required=True)
    p.add_argument('--graded', type=Path, required=True)
    p.add_argument('--out-dir', type=Path, required=True)
    p.add_argument('--frames', type=int, nargs='+', default=[120, 150, 174, 180])
    a = p.parse_args()
    a.out_dir.mkdir(parents=True, exist_ok=True)
    y0, y1, x0, x1 = CROP
    report = {}
    for n in a.frames:
        pair = []
        stats = {}
        for name, directory in [('ungraded', a.ungraded), ('graded', a.graded)]:
            image = cv2.imread(str(directory / f'frame_{n:04}.png'))
            assert image is not None, (directory, n)
            stats[name] = plume_stats(image)
            crop = cv2.resize(image[y0:y1, x0:x1], None, fx=2, fy=2,
                              interpolation=cv2.INTER_NEAREST)
            column = np.vstack([label(image.copy(), f'{name} frame {n}'),
                                label(crop, f'{name} plume 2x')])
            pair.append(column)
        plate = np.hstack(pair)
        path = a.out_dir / f'plume_ab_{n:04}.jpg'
        assert cv2.imwrite(str(path), plate, [cv2.IMWRITE_JPEG_QUALITY, 92])
        report[f'frame_{n:04}'] = stats
        print(path)
    (a.out_dir / 'plume_ab_stats.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
