#!/usr/bin/env python3
"""Export the hand-drawn SVG using ImageMagick 6/7 (no runtime dependency)."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1] / 'showsync' / 'icons'
SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)


def main():
    convert = shutil.which('magick') or shutil.which('convert')
    if not convert:
        raise SystemExit('Install ImageMagick to regenerate icons.')
    for size in SIZES:
        subprocess.run([convert, '-background', 'none', '-density', '384',
                        'MSVG:' + str(ROOT / 'showsync.svg'), '-resize', f'{size}x{size}',
                        str(ROOT / f'showsync-{size}.png')], check=True)
    subprocess.run([convert, *(str(ROOT / f'showsync-{s}.png') for s in SIZES if s <= 256),
                    str(ROOT / 'showsync.ico')], check=True)


if __name__ == '__main__':
    main()
