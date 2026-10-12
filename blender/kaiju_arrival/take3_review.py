"""Package graded T313 stills and motion clips for the camera-choice gate."""
import argparse
import base64
import hashlib
import html
import json
from pathlib import Path

from PIL import Image

from take2_review import sheet
from take3_preview import BEATS


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def embedded(path, mime):
    return f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode('ascii')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    root = args.directory.resolve()
    package = {'stage': 'PREVIEW ONLY; final render awaits Devin pick', 'takes': {}}
    document = ['<!doctype html><html lang="en"><meta charset="utf-8">',
                '<meta name="viewport" content="width=device-width,initial-scale=1">',
                '<title>Beetle arrival — worm’s-eye camera choices</title>',
                '<style>body{background:#17191c;color:#eee;font:17px/1.5 system-ui;max-width:1200px;margin:32px auto;padding:0 20px}img,video{width:100%;height:auto}figure{margin:24px 0}small{color:#bbb}section{margin:48px 0}a{color:#aacfff}</style>',
                '<h1>Beetle arrival: at the feet</h1>',
                '<p>Two close, ground-level cameras tilt up during the fast zoom. '
                '<strong>Recommended: B</strong> for the strongest near-feet perspective; '
                'A gives the airborne arrival more room. Pick a camera before final rendering.</p>',
                '<p>The wider field of view is intentional and was authorized by the PM. '
                'The original 32–72 mm animation and zoom timing are preserved; '
                'the sensor is wider. Actor motion, frame-52 contact, dust, '
                'foliage HDRI, and the recovered 1960s grade are unchanged.</p>',
                '<p>Clips show every frame from 40 through 86 at the original 24 fps '
                '(1.958 seconds). They are 480×270 / 4-sample motion drafts. '
                'The six stills per take are 960×540 / 16 samples.</p>']
    for take in ['B', 'A']:
        directory = root / take
        manifest = json.loads((directory / 'manifest.json').read_text())
        media = json.loads((directory / 'media_verification.json').read_text())
        locked = json.loads((directory / 'locked_verification.json').read_text())
        animation = json.loads((directory / 'animation_verification.json').read_text())
        assert media['status'] == locked['status'] == animation['status'] == 'PASS'
        scene = directory / f'take_{take}.blend'
        assert digest(scene) == media['scene_sha256'], 'Rendered scene changed'
        source = Path(manifest['source'])
        assert digest(source) == manifest['source_sha256'], 'T312 source changed'
        parent = json.loads((source.parent / 'manifest.json').read_text())
        assert digest(Path(parent['source'])) == parent['source_sha256'], 'T311 master changed'
        video = directory / f'take_{take}_frames_40-86.mp4'
        assert digest(video) == media['video_sha256'], 'Video changed after validation'
        files = [scene, video]
        for frame in BEATS:
            path = directory / 'stills' / f'frame_{frame:04}.png'
            with Image.open(path) as image:
                assert image.size == (960, 540), (path, image.size)
                image.verify()
            files.append(path)
        sheet(root, BEATS, root / f'take_{take}_timing.jpg', takes=(take,), width=480)
        equivalent = manifest['equivalent_36mm_sensor_focal_range']
        document += [f'<section><h2>{take}: {html.escape(manifest["label"])}</h2>',
                     f'<p>Camera height {manifest["position"][2]}; '
                     f'upward tilt {manifest["opening_elevation"]}° → {manifest["hold_elevation"]}°. '
                     f'Sensor {manifest["sensor_width"]} mm '
                     f'(equivalent field of view: {equivalent[0]:.1f}–{equivalent[1]:.1f} mm on 36 mm).</p>',
                     f'<video controls loop playsinline preload="metadata" poster="{embedded(directory / "stills/frame_0086.png", "image/png")}" src="{embedded(video, "video/mp4")}"></video>',
                     '<p><small>40–86 motion preview. Use the controls to replay the upward reveal.</small></p>']
        for frame, label in zip(BEATS, ['Empty opening', 'Airborne', 'Contact / dust birth',
                                      'Dust / zoom', 'Zoom end', 'Fighting pose']):
            document += [f'<figure><img alt="Take {take}, frame {frame}: {label}" '
                         f'src="{embedded(directory / "stills" / f"frame_{frame:04}.png", "image/png")}">',
                         f'<figcaption>{take} · Frame {frame} · {label}</figcaption></figure>']
        document += ['</section>']
        package['takes'][take] = {
            'manifest': manifest, 'media': media,
            'files': {str(path): digest(path) for path in files},
            'unchanged_T312_source': manifest['source_sha256'],
            'unchanged_T311_master': parent['source_sha256'],
        }
    sheet(root, [1, 52, 86], root / 'camera_choices.jpg', takes=('A', 'B'))
    document += ['</html>']
    (root / 'review.html').write_text('\n'.join(document))
    (root / 'preview_package.json').write_text(json.dumps(package, indent=2))
    print('T313 preview package complete:', root / 'review.html')


if __name__ == '__main__':
    main()
