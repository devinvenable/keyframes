"""Measure matched-frame geometry and luma; write labeled comparison plates."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

import cv2
import numpy as np


def alignment(candidate, reference):
    """RANSAC selects coherent matches, not matches already below the RMS gate."""
    a = cv2.resize(candidate, (960, 540))
    b = cv2.resize(reference, (960, 540))
    sift = cv2.SIFT_create(nfeatures=12000, contrastThreshold=.012)
    ka, da = sift.detectAndCompute(a, None)
    kb, db = sift.detectAndCompute(b, None)
    matches = [m for m, n in cv2.BFMatcher().knnMatch(da, db, k=2)
               if m.distance < .72 * n.distance]
    src = np.float32([ka[m.queryIdx].pt for m in matches])
    dst = np.float32([kb[m.trainIdx].pt for m in matches])
    matrix, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                                ransacReprojThreshold=3, maxIters=5000)
    assert matrix is not None and inliers is not None, 'No coherent image match'
    keep = inliers.ravel().astype(bool)
    # Raw image displacement, BEFORE applying the fitted affine transform.
    errors = np.linalg.norm(src[keep] - dst[keep], axis=1)
    rms = float(np.sqrt(np.mean(errors ** 2)))
    span = np.ptp(src[keep], axis=0)
    return dict(matches=len(matches), inliers=int(keep.sum()), rms_pixels=rms,
                resolution=[960, 540], affine=matrix.tolist(), span_pixels=span.tolist(),
                passed=bool(keep.sum() >= 30 and rms < 5 and span[0] > 400 and span[1] > 200))


def measure(path, reference):
    command = ['ffmpeg', '-hide_banner', '-i', str(path), '-vf',
               'signalstats,metadata=print', '-f', 'null', '-']
    log = subprocess.run(command, capture_output=True, text=True, check=True).stderr
    yavg = float(re.search(r'lavfi.signalstats.YAVG=([0-9.]+)', log)[1])
    command[command.index('-vf') + 1] = (
        'scale=out_color_matrix=bt709:out_range=tv,format=yuv444p,signalstats,metadata=print')
    normalized = subprocess.run(command, capture_output=True, text=True, check=True).stderr
    yavg_bt709 = float(re.search(r'lavfi.signalstats.YAVG=([0-9.]+)', normalized)[1])
    image = cv2.imread(str(path))
    difference = image.astype(float) - reference.astype(float)
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                yavg=yavg, yavg_explicit_bt709=yavg_bt709,
                rgb_mae=float(np.abs(difference).mean()),
                rgb_rmse=float(np.sqrt(np.mean(difference ** 2))))


def plate(paths, labels, output):
    canvas = np.full((580, 960 * len(paths), 3), (32, 26, 22), dtype=np.uint8)
    for i, (path, label) in enumerate(zip(paths, labels)):
        canvas[40:, i * 960:(i + 1) * 960] = cv2.resize(cv2.imread(str(path)), (960, 540))
        cv2.putText(canvas, label, (i * 960 + 16, 27), cv2.FONT_HERSHEY_SIMPLEX,
                    .65, (255, 255, 255), 1, cv2.LINE_AA)
    assert cv2.imwrite(str(output), canvas)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--directory', type=Path, required=True)
    p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--negative-controls', action='store_true')
    a = p.parse_args()
    reference = cv2.imread(str(a.reference))
    candidate = cv2.imread(str(a.directory / 'matched_source_quality.png'))
    geometry = alignment(candidate, reference)
    assert geometry['passed'], f'Camera/pose alignment exceeds probe tolerance: {geometry}'
    results = {'alignment': geometry, 'measurements': {}}
    paths = [a.reference] + [a.directory / name for name in [
        'matched_source_quality.png', 'grade_from_png.png', 'historical_profile.png',
        'extension_grade.png', 'canon_I48.png', 'progress_tail.png', 'grade_bypass.png',
        'extension_grade_trim.png']]
    for path in paths:
        if path.exists():
            results['measurements'][path.stem] = measure(path, reference)
    if a.negative_controls:
        shifted = cv2.warpAffine(candidate, np.float32([[1, 0, 40], [0, 1, 0]]),
                                 (candidate.shape[1], candidate.shape[0]))
        negative = alignment(shifted, reference)
        assert not negative['passed'], 'Alignment gate accepted a 20-preview-pixel shift'
        raw = results['measurements']['matched_source_quality']['rgb_mae']
        graded = results['measurements']['grade_from_png']['rgb_mae']
        bypass = results['measurements']['grade_bypass']['rgb_mae']
        assert graded < raw / 2, 'Recovered grade does not improve RGB error by 2x'
        assert bypass >= raw / 2, 'Bypassed grade unexpectedly passes the improvement gate'
        results['negative_controls'] = dict(shifted_camera=negative,
                                            grade_bypass_fails_improvement=bypass >= raw / 2)
    (a.directory / 'analysis.json').write_text(json.dumps(results, indent=2))
    plate(paths[:2], ['A: teaser endpoint', 'B: April 25 source-quality probe'],
          a.directory / 'ab_source.png')
    plate([paths[0], paths[1], paths[2]],
          ['A: teaser endpoint', 'B: source-quality probe', 'C: recovered compositor on PNG'],
          a.directory / 'ab_grade.png')
    if (a.directory / 'extension_grade_trim.png').exists():
        plate([a.reference, a.directory / 'extension_grade.png',
               a.directory / 'extension_grade_trim.png'],
              ['A: teaser 78.066', 'B: recovered chain 80.610',
               'C: chain + reconstructed RGB trim 78.037'], a.directory / 'ab_extension.png')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
