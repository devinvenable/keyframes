"""Check photographed climb/readability and seam; reject a frozen/no-climb tail."""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np


def measure(path):
    image = cv2.imread(str(path))
    assert image is not None and image.shape == (1080, 1920, 3), path
    assert float(image.std()) > 15, f'Blank/flat frame: {path}'
    # The hero is between the two pillars. This region excludes both pillars.
    roi = image[80:900, 650:1250]
    mask = (roi.max(axis=2) < 65).astype('uint8')
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
    assert count > 1, f'No robot silhouette: {path}'
    idx = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
    x, y, w, h, area = stats[idx].tolist()
    assert area > 8000 and h > 160 and w > 100, f'Robot no longer readable: {path}: {stats[idx]}'
    assert x > 0 and y > 0 and x+w < 600 and y+h < 820, f'Robot cropped: {path}'
    blue, green, red = cv2.split(roi.astype('float32'))
    flames = (red > 180) & (green > 100) & (red > blue*1.18)
    assert flames.sum() > 150, f'No visible warm exhaust: {path}'
    return dict(bbox=[x+650, y+80, w, h], area=area,
                centroid=[float(centroids[idx][0]+650), float(centroids[idx][1]+80)],
                flame_pixels=int(flames.sum()), mean=float(image.mean()))


def check(original, candidate):
    frames = [217, 233, 249, 265]
    paths = [original/'frame_0217.png'] + [candidate/f'frame_{f:04}.png' for f in frames[1:]]
    measurements = [measure(path) for path in paths]
    ys = [m['centroid'][1] for m in measurements]
    areas = [m['area'] for m in measurements]
    assert all(b < a-8 for a, b in zip(ys, ys[1:])), f'Robot must visibly climb: {ys}'
    assert ys[0]-ys[-1] > 130, f'Insufficient photographed altitude gain: {ys}'
    assert .18 < areas[-1]/areas[0] < .85, f'Altitude/readability scale: {areas}'
    return dict(status='PASS', frames=dict(zip(map(str, frames), measurements)),
                climb_pixels=ys[0]-ys[-1], final_area_ratio=areas[-1]/areas[0])


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--original', type=Path, required=True)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    a = p.parse_args()
    report = check(a.original, a.candidate)
    a.report.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
