"""Assemble labeled T312 graded stills for the camera-choice gate (Pillow)."""
import argparse
import base64
import html
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def sheet(directory, frames, destination, takes=('A', 'B', 'C'), width=640):
    height = width * 9 // 16
    label_height = 44
    result = Image.new('RGB', (width * len(frames), (height + label_height) * len(takes)), '#16191d')
    draw = ImageDraw.Draw(result)
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 16)
    labels = {1: 'Wide start', 40: 'Airborne', 51: 'Before contact', 52: 'Contact',
              58: 'Dust / zoom', 63: 'Zoom end', 86: 'Fighting pose'}
    for row, take in enumerate(takes):
        manifest = json.loads((directory / take / 'manifest.json').read_text())
        for column, frame in enumerate(frames):
            source = directory / take / 'stills' / f'frame_{frame:04}.png'
            image = Image.open(source).convert('RGB')
            image.thumbnail((width, height), Image.Resampling.LANCZOS)
            x, y = column * width, row * (height + label_height)
            result.paste(image, (x, y))
            text = f'{take} | {manifest["label"]} | {frame:03} {labels[frame]}'
            draw.text((x + 10, y + height + 12), text, fill='#e3e8ef', font=font)
    result.save(destination, quality=94)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    package = {'stage': 'preview choice; final render awaits Devin pick', 'takes': {}}
    for take in 'ABC':
        directory = args.directory / take
        files = [directory / f'take_{take}.blend']
        for frame in [1, 40, 51, 52, 58, 63, 86]:
            path = directory / 'stills' / f'frame_{frame:04}.png'
            with Image.open(path) as image:
                assert image.size == (960, 540), (path, image.size)
                image.verify()
            files.append(path)
        package['takes'][take] = {
            'files': {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in files},
            'grade': json.loads((directory / 'stills' / 'grade.json').read_text()),
        }
    sheet(args.directory, [1, 52, 86], args.directory / 'camera_choices.jpg')
    for take in 'ABC':
        sheet(args.directory, [40, 51, 52, 58, 63, 86],
              args.directory / f'take_{take}_timing.jpg', takes=(take,), width=480)
        manifest = json.loads((args.directory / take / 'manifest.json').read_text())
        parts = [f'<h2>{take}: {html.escape(manifest["label"])}</h2>',
                 f'<p>Camera height {manifest["position"][2]} (original 26). '
                 'Approved motion and lens timing preserved. Draft-quality graded stills.</p>']
        for frame, label in [(86, 'Fighting pose'), (52, 'Contact'), (1, 'Wide start')]:
            data = base64.b64encode((args.directory / take / 'stills' /
                                    f'frame_{frame:04}.png').read_bytes()).decode('ascii')
            parts += [f'<h3>Frame {frame}: {label}</h3>',
                      f'<img alt="{label}" src="data:image/png;base64,{data}">']
        (args.directory / take / 'review.html').write_text('\n'.join(parts))
    (args.directory / 'preview_package.json').write_text(json.dumps(package, indent=2))
    (args.directory / 'REVIEW.txt').write_text(
        'T312 PREVIEW CAMERA CHOICE — final rendering has not started.\n\n'
        'camera_choices.jpg: rows A/B/C; columns wide start / frame-52 contact / frame-86 pose.\n'
        'A — Low classic: original horizontal position, height 9 (was 26).\n'
        'B — Ground hero: closer and almost at ground level, height 4; strongest upward angle.\n'
        'C — Low oblique: farther right and back, height 7; more landscape and breathing room.\n\n'
        'All use the exact approved 32–72mm lens curve, original actor/dust animation,\n'
        'and the same natural quarry HDRI/grade. Lens endpoint remains frame 63.\n'
        'Individual graded PNGs are in A/stills, B/stills, C/stills.\n'
        'take_A_timing.jpg etc. show airborne, pre-contact, contact, dust, zoom end and pose.\n'
        'Pick A, B or C before final-quality EXR rendering and MP4 packaging.\n'
    )


if __name__ == '__main__':
    main()
