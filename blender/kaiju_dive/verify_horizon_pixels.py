"""Regression check at the original frame-24 edge, plus before/after evidence.

This fixed-camera ROI is a discriminating regression for the reported seam,
not a substitute for inspecting the full arc's rendered horizon sweep.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def edge_contrast(path):
    with Image.open(path) as im:
        pixels = np.array(im.convert('RGB').resize((960, 540)), dtype=np.float32)
    contrast = []
    # Original projected upper edge of the square stage, safely left of robot.
    for x in range(20, 240):
        y = round(466+.016*x)
        above = pixels[y-8:y-3, x].mean(axis=0)
        below = pixels[y+3:y+8, x].mean(axis=0)
        contrast.append(float(np.abs(above-below).mean()))
    return float(np.median(contrast))


def check(path):
    contrast = edge_contrast(path)
    assert contrast < 15, f'Hard stage edge remains: {contrast:.3f} code values'
    return contrast


def main():
    p = argparse.ArgumentParser(); p.add_argument('--fixed', type=Path, required=True)
    p.add_argument('--original', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = {'fixed_edge_contrast': check(a.fixed), 'original_edge_contrast': edge_contrast(a.original)}
    try: check(a.original)
    except AssertionError as e: result['negative_original_pixels'] = str(e)
    else: raise AssertionError('Original seam did not fail pixel regression')
    result['status'] = 'PASS'
    a.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__': main()
