"""Package only the revised B endpoint requested after motion previews paused."""
import argparse
import base64
import hashlib
import json
from pathlib import Path

from PIL import Image


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def embedded(path):
    return 'data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode('ascii')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    root = args.directory.resolve()
    directory = root / 'B_hold_left_third'
    report = json.loads((directory / 'hold_verification.json').read_text())
    assert report['status'] == 'PASS'
    assert digest(Path(report['blend'])) == report['blend_sha256']
    source_checks = {}
    source = Path(report['source'])
    assert digest(source) == report['source_sha256']
    source_checks[str(source)] = report['source_sha256']
    # Follow B -> T312 B -> untouched T311 master.
    for _ in range(2):
        manifest = json.loads((source.parent / 'manifest.json').read_text())
        source = Path(manifest['source'])
        assert digest(source) == manifest['source_sha256']
        source_checks[str(source)] = manifest['source_sha256']
    still = directory / 'stills/frame_0086.png'
    with Image.open(still) as image:
        assert image.size == (1920, 1080), image.size
        image.verify()
    grade = json.loads((directory / 'stills/grade.json').read_text())
    assert grade['frames'] == 1, 'Endpoint delivery must contain exactly one graded frame'
    prior = root / 'B/stills/frame_0086.png'
    report.update({
        'current_deliverable': str(still), 'png_sha256': digest(still),
        'resolution': [1920, 1080], 'cycles_samples': 64, 'grade': grade,
        'source_hashes_unchanged': source_checks,
        'motion_previews': 'Stopped on Devin direction; partial EXRs are not delivered clips',
        'initial_stills': {take: [str(root / take / 'stills' / f'frame_{frame:04}.png')
                                  for frame in [1, 40, 52, 58, 63, 86]] for take in 'AB'},
    })
    (directory / 'delivery_verification.json').write_text(json.dumps(report, indent=2))
    document = f'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Beetle arrival — revised B endpoint</title>
<style>body{{background:#17191c;color:#eee;font:17px/1.5 system-ui;max-width:1400px;margin:30px auto;padding:0 20px}}img{{width:100%;height:auto}}summary{{cursor:pointer}}small{{color:#bbb}}</style>
<h1>Revised B: where the shot lands</h1>
<p>Frame 86 · monster on the left-third line · camera 12% closer · upward tilt 31.5° (was 29°).</p>
<img alt="Revised left-third beetle hold, looking up from near the feet" src="{embedded(still)}">
<p><small>1920×1080, 64-sample still with the recovered 1960s film grade.
The horn and both feet remain in frame. Foliage and dust are unchanged.</small></p>
<p>Only this endpoint was rendered after the new direction. The camera-move previews are paused;
the move will be developed backwards from the chosen endpoint.</p>
<details><summary>Compare the previous B hold (960×540 preview)</summary>
<img alt="Previous centered B hold" src="{embedded(prior)}"></details></html>'''
    (root / 'review.html').write_text(document)
    print('T313_ENDPOINT_REVIEW_READY', root / 'review.html')


if __name__ == '__main__':
    main()
