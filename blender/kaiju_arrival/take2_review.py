"""Assemble labeled T312 graded stills for the camera-choice gate (Pillow)."""
import argparse
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
    sheet(args.directory, [1, 52, 86], args.directory / 'camera_choices.jpg')
    for take in 'ABC':
        sheet(args.directory, [40, 51, 52, 58, 63, 86],
              args.directory / f'take_{take}_timing.jpg', takes=(take,), width=480)
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
