"""Photographed climb, locked background, and full-exit contracts for T316."""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np


def read(path):
    image = cv2.imread(str(path))
    assert image is not None and image.shape == (1080, 1920, 3), path
    assert float(image.std()) > 15, f'Blank/flat frame: {path}'
    return image


def measure(path):
    image = read(path)
    roi = image[80:900, 650:1250]
    mask = (roi.max(axis=2) < 65).astype('uint8')
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
    assert count > 1, f'No robot silhouette: {path}'
    idx = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
    x, y, w, h, area = stats[idx].tolist()
    assert area > 1000, f'No substantial early-ascent silhouette: {path}'
    blue, green, red = cv2.split(roi.astype('float32'))
    flames = (red > 180) & (green > 100) & (red > blue*1.18)
    assert flames.sum() > 150, f'No visible warm exhaust: {path}'
    return dict(bbox=[x+650, y+80, w, h], area=area,
                centroid=[float(centroids[idx][0]+650), float(centroids[idx][1]+80)],
                flame_pixels=int(flames.sum()), mean=float(image.mean()))


def registration(start, end):
    shifts = []
    start, end = [cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) for im in (start, end)]
    # DFT-friendly 640x480 avoids half-pixel bias from odd padded FFT sizes.
    for x0, x1 in [(0, 640), (1280, 1920)]:
        a = start[600:1080, x0:x1].astype('float32')
        b = end[600:1080, x0:x1].astype('float32')
        window = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
        shift, response = cv2.phaseCorrelate(a, b, window)
        assert response > .3, f'Background registration unreliable: {response}'
        assert np.hypot(*shift) < .5, f'Camera must remain fixed: background shift {shift}'
        shifts.append(dict(shift_pixels=shift, response=response))
    return shifts


def empty_sky(path):
    image = read(path)
    # Covers the entire receding hero trajectory, avoiding the flanking pillars.
    roi = image[0:850, 700:1230].astype('float32')
    dark = (roi.max(axis=2) < 65).astype('uint8')
    _, _, stats, _ = cv2.connectedComponentsWithStats(dark)
    largest = int(max(stats[1:, cv2.CC_STAT_AREA], default=0))
    blue, green, red = cv2.split(roi)
    flames = int(((red > 180) & (green > 100) & (red > blue*1.18)).sum())
    assert largest < 5 and flames < 5, f'Robot/plume remains at exit: dark={largest}, flame={flames}: {path}'
    return dict(largest_dark_component=largest, flame_pixels=flames)


def check(original, candidate, manifest):
    start_path, early_path = original/'frame_0217.png', candidate/'frame_0265.png'
    start, early = measure(start_path), measure(early_path)
    climb = start['centroid'][1] - early['centroid'][1]
    assert climb > 130, f'Robot must visibly climb: {climb}'
    ratio = early['area']/start['area']
    assert .18 < ratio < .85, f'Robot must recede: {ratio}'
    shifts = registration(read(start_path), read(early_path))
    exits = {}
    exit_frames = [manifest['exit_frame'], manifest['new_frames'][1]] if manifest.get('exit_frame') else []
    for frame in exit_frames:
        path = candidate/f'frame_{frame:04}.png'
        exits[str(frame)] = empty_sky(path)
        registration(read(start_path), read(path))
    return dict(status='PASS', background_registration=shifts,
                early_frames={'217': start, '265': early}, exit_frames=exits,
                climb_pixels_at_two_seconds=climb, area_ratio_at_two_seconds=ratio,
                appended_frames=manifest['new_frames'][1]-217,
                exit_frame=manifest.get('exit_frame'), empty_hold_frames=manifest.get('empty_hold_frames', 0))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--original', type=Path, required=True)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    a = p.parse_args()
    report = check(a.original, a.candidate, json.loads(a.manifest.read_text()))
    a.report.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
